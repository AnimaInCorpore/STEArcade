; Gauntlet (Atari Games 1985) for the Atari STE: the arcade's own 68010 program, run natively (tools/patch.py: the
; ROM at its own addresses $000000-$04FFFF, its windows moved below 4 MB, its I/O and slapstic as calls of this
; runtime), the runtime's schedule, the picture (render.s).
;
; Linked at RT_BASE ($50000, after the program's image) and moved there by loader.s (the .PRG): the machine is the
; game's from then on (the program's addresses $000000-$04FFFF are TOS's memory; Esc resets the STE).
;
; The schedule (tools/stemodel.py runs the same in Python): two threads.  The picture is the foreground; the game
; runs from the VBL: the VBL delivers the game's IRQ 4 (its handler at $34A, as an interrupt) and switches to the
; game's own thread, which runs on its own stack until it waits for the next frame (TRAP #14 at $40C28, TRAP #13 at
; $40F88: tools/patch.py SCHEDULE); the trap switches back and the VBL's RTE resumes the picture.  A VBL that comes
; while the game still runs (its frame took longer than one) delivers only the IRQ 4, as the arcade does.
;
; Registers the game's thread owns: all (its stack: the arcade's at $904F00, here ARC_VRAM + $4F00).  The picture's
; thread: own_stack.

	include	"map.i"			; (tools/patch.py: ARC_VRAM ... RT_BASE)

ARC_IRQ4 = $34A				; the arcade's vector 28 (IRQ 4, the vertical blank)
ARC_IRQ6 = $36C				; vector 30 (IRQ 6, a sound response)
KEY_ESC = $01
MFP_VEC = $A0				; the MFP's vector base: vectors $A0-$AF at $280-$2BF (unused by the game's ROM)
	include	"ikbd.s"

; the pads (engine/rt/jagpad.s): jp_in byte 0 player 1's bits, byte 1 player 2's, byte 2 the coins (bit 0 coin 1,
; bit 1 coin 2); A fire, B magic (the start), C magic too, Option / keypad 5, 6 a coin, Pause / keypad 1, 2 magic
JP_SH1 = 24
JP_SH2 = 16
JP_SHX = 8
JP1_UP = IN_UP<<JP_SH1
JP1_DOWN = IN_DOWN<<JP_SH1
JP1_LEFT = IN_LEFT<<JP_SH1
JP1_RIGHT = IN_RIGHT<<JP_SH1
JP1_B1 = IN_FIRE<<JP_SH1
JP1_B2 = IN_MAGIC<<JP_SH1
JP1_B3 = IN_MAGIC<<JP_SH1
JP2_UP = IN_UP<<JP_SH2
JP2_DOWN = IN_DOWN<<JP_SH2
JP2_LEFT = IN_LEFT<<JP_SH2
JP2_RIGHT = IN_RIGHT<<JP_SH2
JP2_B1 = IN_FIRE<<JP_SH2
JP2_B2 = IN_MAGIC<<JP_SH2
JP2_B3 = IN_MAGIC<<JP_SH2
JP_START1 = IN_MAGIC<<JP_SH1
JP_START2 = IN_MAGIC<<JP_SH2
JP_COIN1 = $01<<JP_SHX
JP_COIN2 = $02<<JP_SHX
	include	"jagpad.s"

; the borders (engine/rt/borders.s): 240 lines from the 18th displayed one, the palette black outside them
	ifnd PIC_TOP
PIC_TOP = 18
	endc
TA_DATA = 98
TA_NOPS = 84
PIC_LINES = 240
BD_PALETTE = 1				; (render.s: shown_pal, black_pal)
	include	"borders.s"

; arcade inputs (the words at $803000-$803006, active low)
IN_UP = $80
IN_DOWN = $40
IN_LEFT = $20
IN_RIGHT = $10
IN_FIRE = $02
IN_MAGIC = $01

; memory the runtime pins (F030Arcade's lesson: large buffers at fixed addresses, not in the bss)
; (render.s's buffers: $200000-$3BFFFF, $3C2000-$3C7FFF, $3E0800-$3EB47F)
CRASH_INFO = $3C1000			; the crash dump: vector, SR, PC, registers

	section text,code
rt_entry:
	bra.w	start
	dcb.b	$10-4,0
; the routines the patched program calls (tools/patch.py STUB_ORDER: entry k at RT_BASE + $10 + 6 * k)
rt_stubs:				; (jmp xxx.l spelled out: the assembler would shorten a jmp)
	dc.w	$4ef9
	dc.l	snd_cmd_d0
	dc.w	$4ef9
	dc.l	snd_cmd_sp10
	dc.w	$4ef9
	dc.l	snd_reset_d0
	dc.w	$4ef9
	dc.l	slap_bank0
	dc.w	$4ef9
	dc.l	slap_bank3
	dc.w	$4ef9
	dc.l	slap_a0d0
	dc.w	$4ef9
	dc.l	slap_a0

start:
	move	#$2700,sr
	lea	own_stack_top,sp
	bsr	init_hardware
	bsr	install_image
	bsr	install_vectors
	bsr	init_arcade
	bsr	init_video
	bsr	init_game
	bsr	snd_init
	bsr	snd_out_init
	move	#$2300,sr
render_loop:
	tst.b	quit_flag
	bne	reset_ste
	move.l	frames_done,d0
	cmp.l	frames_drawn,d0
	beq.s	render_loop
	move.l	d0,frames_drawn
	bsr	render_frame
	addq.l	#1,pictures
	bra.s	render_loop

; Esc: the STE's reset (TOS's reset vector: $0-$7 read the ROM)
reset_ste:
	move	#$2700,sr
	move.l	$4.w,a0
	jmp	(a0)

; ---- the machine -------------------------------------------------------------------------------------------------
init_hardware:
	clr.b	$fffffa07.w		; MFP: no interrupts but the ACIA's
	clr.b	$fffffa09.w
	clr.b	$fffffa13.w
	clr.b	$fffffa15.w
	move.b	#MFP_VEC,$fffffa17.w	; the MFP's vectors at $280 (TOS's $100-$13F is the BIOS's jump table, which the
					; game calls: jsr $12A ...), automatic end of interrupt
	bset	#6,$fffffa09.w		; ACIA (keyboard, joysticks)
	bset	#6,$fffffa15.w
	bset	#0,$fffffa07.w		; Timer B, Timer A (the borders)
	bset	#0,$fffffa13.w
	bset	#5,$fffffa07.w
	bset	#5,$fffffa13.w
	ifnd SIM
	bsr	jagpad_init		; (the STE pads: absent on a plain ST)
	endc
	ifnd SIM
.w1:	btst	#1,$fffffc00.w
	beq.s	.w1
	move.b	#$14,$fffffc02.w	; joystick events
.w2:	btst	#1,$fffffc00.w
	beq.s	.w2
	move.b	#$12,$fffffc02.w	; no mouse
	endc
	rts

; the patched program to $000008-$04FFFF ($0-$7 are TOS's ROM on the ST)
install_image:
	lea	program_image+8,a0
	lea	$8.w,a1
	move.l	#(IMAGE_END-8)/4-1,d0
.copy:	move.l	(a0)+,(a1)+
	subq.l	#1,d0
	bpl.s	.copy
	rts

install_vectors:
	lea	crash_stubs,a0		; vectors 2-15 (bus error ... ) -> the crash dump
	lea	$8.w,a1
	moveq	#14-1,d0
.c:	move.l	a0,(a1)+
	addq.l	#8,a0
	dbf	d0,.c
	move.l	#rte_stub,$60.w		; spurious, autovectors 1-7
	move.l	#rte_stub,$64.w
	move.l	#rte_stub,$68.w		; HBL
	move.l	#rte_stub,$6c.w
	move.l	#vbl,$70.w
	move.l	#rte_stub,$74.w
	move.l	#rte_stub,$78.w
	move.l	#rte_stub,$7c.w
	lea	$80.w,a1		; traps: crash, but #13 / #14 (the game's waits)
	moveq	#16-1,d0
.t:	move.l	#crash_trap,(a1)+
	dbf	d0,.t
	move.l	#trap_queue,$b4.w
	move.l	#trap_main,$b8.w
	lea	MFP_VEC*4,a1		; MFP
	moveq	#16-1,d0
.m:	move.l	#rte_stub,(a1)+
	dbf	d0,.m
	move.l	#acia_isr,MFP_VEC*4+6*4
	move.l	#timer_b,MFP_VEC*4+8*4
	move.l	#timer_a,MFP_VEC*4+13*4
	rts

rte_stub:
	rte

; the arcade's windows as the BIOS handed them over (build/gauntlet/boot_ste.bin: tools/build.py relocated it), the
; slapstic's bank, the I/O block
init_arcade:
	lea	boot_state,a0
	lea	ARC_VRAM,a1
	move	#$6000/4-1,d0
.v:	move.l	(a0)+,(a1)+
	dbf	d0,.v
	lea	ARC_PALETTE,a1
	move	#$800/4-1,d0
.p:	move.l	(a0)+,(a1)+
	dbf	d0,.p
	lea	ARC_RAM,a1
	move	#$2000/4-1,d0
.r:	move.l	(a0)+,(a1)+
	dbf	d0,.r
	lea	ARC_EEPROM,a1
	move	#$400/4-1,d0
.e:	move.l	(a0)+,(a1)+
	dbf	d0,.e
	lea	boot_regs,a1
	moveq	#16+2-1,d0		; D0-D7/A0-A7, SR.w PC.l bank.w (18 longs' worth)
.g:	move.l	(a0)+,(a1)+
	dbf	d0,.g
	lea	ARC_IO,a0
	moveq	#-1,d0
	move.l	d0,(a0)			; the inputs: nothing pressed
	move.l	d0,4(a0)
	move.w	#$0048,8(a0)		; status: service off, no command / response pending, not in the vertical blank
	move.w	d0,$e(a0)		; the response latch
	moveq	#-1,d0
	move.w	d0,cur_bank		; (none yet)
	moveq	#3,d0			; the slapstic's first bank
	bsr	load_bank
	rts

; the game's thread at the hand-off: its stack holds an exception frame (SR, PC) and its registers below it
init_game:
	move.l	boot_regs+15*4,a0	; A7
	move.l	boot_regs+16*4+2,-(a0)	; PC
	move.w	boot_regs+16*4,-(a0)	; SR
	lea	boot_regs+15*4,a1
	moveq	#15-1,d0
.r:	move.l	-(a1),-(a0)		; A6 ... D0 (the order movem.l (sp)+,d0-d7/a0-a6 reads)
	dbf	d0,.r
	move.l	a0,game_sp
	sf	game_started
	rts

; ---- the schedule ------------------------------------------------------------------------------------------------
vbl:
	ifnd SIM
	borders_vbl
	endc
	move.l	sp,vbl_sp		; the VBL's own work on its own stack (the game's, in the arcade's video RAM, has
	lea	vbl_stack_top,sp	; little room below the program's variables)
	movem.l	d0-d7/a0-a6,-(sp)
	addq.l	#1,vbl_count
	bsr	vbl_video
	bsr	vbl_inputs
	bsr	snd_out_vbl
	movem.l	(sp)+,d0-d7/a0-a6
	move.l	vbl_sp,sp
	tst.b	in_game
	bne.s	vbl_nested
	movem.l	d0-d7/a0-a6,-(sp)
	move.l	sp,render_sp		; the picture's thread: its registers and the VBL's frame on its stack
	st	in_game
	move.l	game_sp,sp
	tst.b	game_started
	beq.s	.first
	move.l	#game_resume,-(sp)	; the game's IRQ 4, which returns to the game's thread where it waited
	move.w	#$2300,-(sp)
	move.b	snd_rtail,d0		; sound replies waiting: their IRQ 6 first (into the IRQ 4)
	cmp.b	snd_rhead,d0
	beq.s	.irq4
	move.l	#ARC_IRQ4,-(sp)
	move.w	#$2400,-(sp)
	bra	irq6_chain
.irq4:	jmp	ARC_IRQ4
.first:	st	game_started		; (the hand-off: the BIOS's SR masks the IRQ; the program starts)
game_resume:
	movem.l	(sp)+,d0-d7/a0-a6
	rte
vbl_nested:				; the game's frame is still running: only its IRQ 4 (the CPU's frame is on its
	jmp	ARC_IRQ4		; stack)

; IRQ 6 for each sound reply waiting (the replies, oldest first, through the game's handler), then the frame on the
; stack (the caller's RTE target).  Interrupts off.
irq6_chain:
	movem.l	d0/a0,-(sp)
	bsr	snd_pop
	tst.b	d0
	beq.s	.done
	movem.l	(sp)+,d0/a0
	move.l	#irq6_chain,-(sp)	; (after the handler: the next one)
	move.w	#$2700,-(sp)
	move	#$2600,sr
	jmp	ARC_IRQ6
.done:	movem.l	(sp)+,d0/a0
	rte

; TRAP #14 in place of the main loop's bra.s $40C22 (the frame counter was 0): the frame is done (the sound replies
; first: their IRQ 6, then here again)
trap_main:
	move	#$2700,sr
	move.l	#$40C22,2(sp)
	move.l	d0,-(sp)
	move.b	snd_rtail,d0
	cmp.b	snd_rhead,d0
	movem.l	(sp)+,d0		; (the flags stay)
	beq.s	.go
	move.l	#trap_main,-(sp)
	move.w	#$2700,-(sp)
	bra	irq6_chain
.go:	addq.l	#1,frames_done
	bra.s	yield

; TRAP #13 in place of bne.s $40F80 at $40F88 (after jsr $4802; tst.l d0): wait while d0 is not 0
trap_queue:
	btst	#2,1(sp)		; Z of the trap's SR: the queue is empty, go on at $40F8A
	bne.s	.on
	move	#$2700,sr
	move.l	d0,-(sp)
	move.b	snd_rtail,d0
	cmp.b	snd_rhead,d0
	movem.l	(sp)+,d0
	beq.s	.go
	move.l	#trap_queue,-(sp)
	move.w	#$2700,-(sp)
	bra	irq6_chain
.go:	move.l	#$40F80,2(sp)
	bra.s	yield
.on:	rte

yield:
	movem.l	d0-d7/a0-a6,-(sp)
	move.l	sp,game_sp
	sf	in_game
	move.l	render_sp,sp
	movem.l	(sp)+,d0-d7/a0-a6
	rte				; (the VBL's frame: the picture goes on)

; ---- the runtime's calls (patch.py SITES): the sound board in sound.s ------------------------------------------
; the slapstic: the routines at $4FED4 / $4FEEA (bank 0 / 3, leaving d0.w = SR as their move sr,d0), $4FF00 (the
; bank of (a0,d0.w)), $4FF0C (the bank of (a0), then move.w (a0),(a1) with the old bank's word)
slap_bank0:
	move	sr,-(sp)
	movem.l	d1/a0-a2,-(sp)
	moveq	#0,d0
	bsr	load_bank
	movem.l	(sp)+,d1/a0-a2
	move	(sp),d0
	move	(sp)+,sr
	rts
slap_bank3:
	move	sr,-(sp)
	movem.l	d1/a0-a2,-(sp)
	moveq	#3,d0
	bsr	load_bank
	movem.l	(sp)+,d1/a0-a2
	move	(sp),d0
	move	(sp)+,sr
	rts
slap_a0d0:
	movem.l	d0-d1/a0-a2,-(sp)
	move.w	d0,d1			; (a0,d0.w): d0 sign extended
	ext.l	d1
	add.l	a0,d1
	bsr	bank_of
	bmi.s	.n
	bsr	load_bank
.n:	movem.l	(sp)+,d0-d1/a0-a2
	rts
slap_a0:
	movem.l	d0-d1/a0-a2,-(sp)
	move.w	(a0),-(sp)		; (the read sees the old bank)
	move.l	a0,d1
	bsr	bank_of
	bmi.s	.n
	bsr	load_bank
.n:	move.w	(sp)+,(a1)
	movem.l	(sp)+,d0-d1/a0-a2
	rts

; d1 = an address -> d0 = the bank a direct switch there selects (its address $38040 / $38050 / $38060 / $38070 in
; the window and its mirrors), or -1
bank_of:
	move.l	d1,d0
	and.l	#$ffffff&~($7fff|$280000),d0
	cmp.l	#$38000,d0
	bne.s	.no
	move.l	d1,d0
	lsr.l	#1,d0
	and.w	#$3fff,d0
	sub.w	#$20,d0
	bmi.s	.no
	cmp.w	#$18,d0
	bhi.s	.no
	move	d0,d1
	and	#7,d1
	bne.s	.no
	lsr	#3,d0
	ext.l	d0
	rts
.no:	moveq	#-1,d0
	rts

; d0 = bank: its 8 KB into $38000-$3FFFF (all four mirrors)
load_bank:
	cmp.w	cur_bank,d0
	beq.s	.same
	move.w	d0,cur_bank
	lea	slapstic_banks,a0
	mulu	#$2000,d0
	add.l	d0,a0
	lea	$38000,a1
	moveq	#4-1,d1
.m:	move.l	a0,a2
	move	#$2000/16-1,d0
.c:	move.l	(a2)+,(a1)+
	move.l	(a2)+,(a1)+
	move.l	(a2)+,(a1)+
	move.l	(a2)+,(a1)+
	dbf	d0,.c
	dbf	d1,.m
.same:	rts

; ---- input -------------------------------------------------------------------------------------------------------
; the keyboard and the joysticks into the arcade's input words (active low): player 1 the keyboard (arrows, Space,
; Control or Z fire, Alternate or X magic = start) and joystick 1, player 2 joystick 0
vbl_inputs:
	ifnd SIM
	bsr	jagpad_poll
	endc
	move.b	p1_kbd,d0
	or.b	p1_joy,d0
	or.b	jp_in,d0
	not.b	d0
	move.b	d0,ARC_IO+1
	move.b	p2_joy,d0
	or.b	jp_in+1,d0
	not.b	d0
	move.b	d0,ARC_IO+3
	move.b	jp_in+2,d1		; the pads' coins: a count on a press
	move.b	jp_coins,d0
	move.b	d1,jp_coins
	not.b	d0
	and.b	d0,d1
	btst	#0,d1
	beq.s	.c2
	moveq	#0,d0
	bsr	coin
.c2:	btst	#1,d1
	beq.s	.c3
	moveq	#1,d0
	bsr	coin
.c3:	rts

acia_isr:
	movem.l	d0-d2/a0,-(sp)
.again:
	ikbd_byte
	lea	key_table,a0
.find:	move.b	(a0),d0
	beq	.again
	cmp.b	d0,d1
	beq.s	.found
	addq	#2,a0
	bra.s	.find
.found:	move.b	1(a0),d0
	bne.s	.joyk
	tst.b	d2			; a coin key (bits 0): a count on its press
	bmi	.again
	moveq	#0,d0
	move.b	d1,d0
	subq.b	#6,d0
	bsr	coin
	bra	.again
.joyk:	tst.b	d2
	bmi.s	.rel
	or.b	d0,p1_kbd
	bra	.again
.rel:	not.b	d0
	and.b	d0,p1_kbd
	bra	.again
.packet_byte:
	clr.b	ikbd_state
	moveq	#0,d2			; IKBD joystick bits (0 up, 1 down, 2 left, 3 right, 7 fire) -> the arcade's
	btst	#0,d1
	beq.s	.j1
	or.b	#IN_UP,d2
.j1:	btst	#1,d1
	beq.s	.j2
	or.b	#IN_DOWN,d2
.j2:	btst	#2,d1
	beq.s	.j3
	or.b	#IN_LEFT,d2
.j3:	btst	#3,d1
	beq.s	.j4
	or.b	#IN_RIGHT,d2
.j4:	tst.b	d1
	bpl.s	.j5
	or.b	#IN_FIRE,d2
.j5:	cmp.b	#2,d0			; (ikbd.s: d0 = 1 joystick 0, 2 joystick 1)
	bne.s	.joy0
	move.b	d2,p1_joy		; joystick 1: player 1
	bra	.again
.joy0:	move.b	d2,p2_joy
	bra	.again
.done:	movem.l	(sp)+,d0-d2/a0
	rte

key_table:				; scancode, the bits of player 1's word (0: a coin key)
	dc.b	$48,IN_UP,$50,IN_DOWN,$4b,IN_LEFT,$4d,IN_RIGHT
	dc.b	$39,IN_FIRE,$2c,IN_FIRE,$1d,IN_FIRE,$38,IN_MAGIC,$2d,IN_MAGIC
	dc.b	$06,0,$07,0,$08,0,$09,0	; 5 / 6 / 7 / 8: coin 1-4 (players 1-4)
	dc.b	0,0
	even

; ---- crashes -----------------------------------------------------------------------------------------------------
; an exception: at CRASH_INFO the vector.w, SR.w, PC.l, the registers D0-A7 (16 longs, A7 at the exception), and for a
; bus or address error (vectors 2, 3: the 68000's long frame) its access address.l and instruction word.w at +$48; a
; red screen, and nothing more (TOS is gone)
crash_stubs:
	rept	14
	move.w	#REPTN+2,-(sp)
	bra.w	crash_common
	endr
crash_trap:
	move.w	#32,-(sp)
crash_common:
	move	#$2700,sr
	movem.l	d0-d7/a0-a7,CRASH_INFO+8
	move.w	(sp)+,CRASH_INFO
	cmp.w	#3,CRASH_INFO
	bhi.s	.short
	move.l	2(sp),CRASH_INFO+$48	; (bus / address error: function code.w, address.l, IR.w, SR.w, PC.l)
	move.w	6(sp),CRASH_INFO+$4c
	addq.l	#8,sp
.short:	move.w	(sp),CRASH_INFO+2
	move.l	2(sp),CRASH_INFO+4
	addq.l	#6,sp
	move.l	sp,CRASH_INFO+8+15*4
	move.w	#$700,$ffff8240.w
.halt:	bra.s	.halt

	include	"render.s"
	include	"sound.s"
	include	"sound_out.s"
	ifnd shown_pal				; (a render.s without the borders' palettes)
shown_pal:	dc.w	$000,$777,$700,$770,$007,$070,$077,$707,$333,$555,$400,$440,$004,$040,$044,$404
black_pal:	dcb.w	16,0
	endc
	ifnd vbl_video
vbl_video:
	movem.l	shown_pal,d0-d7		; (the palette for the picture's lines: borders.s switches it)
	rts
	endc
	borders_handlers
	borders_blit_go
	jagpad_text
	jagpad_maps

	section data,data
	even
program_image:
	incbin	"program_ste.bin"
boot_state:
	incbin	"boot_ste.bin"
slapstic_banks:
	incbin	"slapstic_banks.bin"
	even

	section bss,bss
	ikbd_vars
	borders_vars
	sound_vars
	jagpad_vars
jp_coins:	ds.b	1
	even
quit_flag:	ds.b	1
in_game:	ds.b	1
game_started:	ds.b	1
snd_last:	ds.b	1
p1_kbd:		ds.b	1
p1_joy:		ds.b	1
p2_joy:		ds.b	1
	even
cur_bank:	ds.w	1
game_sp:	ds.l	1
render_sp:	ds.l	1
vbl_count:	ds.l	1
frames_done:	ds.l	1
frames_drawn:	ds.l	1
pictures:	ds.l	1
boot_regs:	ds.l	18
vbl_sp:		ds.l	1
		ds.b	1024
vbl_stack_top:
		ds.b	8192
own_stack_top:
