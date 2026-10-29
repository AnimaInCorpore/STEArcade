; Mr. Do! (Universal, 1982) for the Atari STE: the Z80 program translated (tools/gen.py -> build/mrdo/code_main.s),
; the picture drawn by render.s.  After Pooyan's runtime (games/pooyan/src/pooyan.s).
;
; The schedule (machine.MrDoPort): the whole game runs from the IRQ (RST 38); the foreground spins at $00AC (after the
; boot) or $0154 (after a maze search the IRQ started): the idle hooks.  There the runtime draws the picture when due,
; waits for the next arcade frame and delivers the IRQ with TOKEN as its return address.  When the handler returns
; (z80_irq_ret), the foreground goes on at the hook; when it starts a search instead (a new Z80 stack), the search
; runs to its end at the hook $0154.

	ifnd MAX_PENDING
MAX_PENDING = 3				; arcade frames that may be waiting (the game catches up after a slow picture)
	endc
	ifnd MAX_SKIP
MAX_SKIP = 3				; arcade frames in a row that are not drawn while the game is behind
	endc
	ifnd FRAMES
FRAMES = 0
	endc

KEY_ESC = $01

; Border removal and the palette: engine/rt/borders.s (the picture's 240 lines, black above and below).
	ifnd TA_DATA
TA_DATA = 98
	endc
	ifnd TA_NOPS
TA_NOPS = 84
	endc
PIC_TOP = 18				; the picture's first displayed line (240 lines centred as the 256 of the other ports at 10)
PIC_LINES = 240
BD_PALETTE = 1
	include	"borders.s"

; the pads (engine/rt/jagpad.s): P2 ($A001), P1 ($A000) bits as in key_table (bytes 0-1 of each long; active high)
JP_SH1 = 16
JP_SH2 = 16				; (pad B plays too: the players take turns on the upright cabinet)
JP1_LEFT = $01<<JP_SH1
JP1_DOWN = $02<<JP_SH1
JP1_RIGHT = $04<<JP_SH1
JP1_UP = $08<<JP_SH1
JP1_B1 = $10<<JP_SH1			; (pad A, B, C: fire)
JP1_B2 = $10<<JP_SH1
JP1_B3 = $10<<JP_SH1
JP2_LEFT = $01<<JP_SH2
JP2_DOWN = $02<<JP_SH2
JP2_RIGHT = $04<<JP_SH2
JP2_UP = $08<<JP_SH2
JP2_B1 = $10<<JP_SH2
JP2_B2 = $10<<JP_SH2
JP2_B3 = $10<<JP_SH2
JP_START1 = $20<<JP_SH1
JP_START2 = $40<<JP_SH1
JP_COIN1 = $40<<24
JP_COIN2 = $80<<24
	include	"jagpad.s"
	include	"ikbd.s"

; The Z80's 64 KB: a6 = g_block + $8000 = Z80 address 0 (signed word offsets: $8000-$FFFF lie below a6).
G_Z80 = g_block+$8000
Z_RAM = g_block-$8000			; + a Z80 address >= $8000
TOKEN = $FEFF				; $FFFE on the Z80 stack, byte swapped (gen.py / machine.py TOKEN)
IO_P1 = Z_RAM+$A000			; the inputs as the program reads them (the block's bytes)
IO_P2 = Z_RAM+$A001
IO_DSW1 = Z_RAM+$A002
IO_DSW2 = Z_RAM+$A003

	section text,code

start:
	clr.l	-(sp)
	move	#$20,-(sp)
	trap	#1
	addq	#6,sp
	move.l	d0,old_ssp
	lea	own_stack_top,sp
	lea	own_stack_top-4096,a0	; (the unused part of the stack is marked: the crash dump shows how deep it went)
	move	#1024-1,d0
.mark:	move.l	#$A5A5A5A5,(a0)+
	dbf	d0,.mark

	bsr	init_hardware
	bsr	init_render
	ifnd NOSOUND
	bsr	snd_init
	endc

	ifnd SIM			; (the test harness sets the ports, the DIP switches of its seed)
	move.b	#$DF,IO_DSW1		; DSW1: easy, rack test off, special / extra easy, upright, 3 lives
	ifd DSW1
	move.b	#DSW1,IO_DSW1
	endc
	move.b	#$FF,IO_DSW2		; DSW2: 1 coin 1 credit, both slots
	ifd DSW2
	move.b	#DSW2,IO_DSW2
	endc
	move.b	#$FF,IO_P1		; nothing pressed
	move.b	#$FF,IO_P2
	endc
	move.b	#$FF,in_sys
	move.b	#$FF,in_p1
	move.b	#$FF,in_p2

	lea	z80_dispatch_sw,a4
	lea	G_Z80,a6
	lea	G_Z80-1,a5		; SP = $FFFF as after a reset (the program sets it itself)
	moveq	#0,d0
	moveq	#0,d1
	moveq	#0,d2
	moveq	#0,d3
	moveq	#0,d4
	moveq	#0,d5
	moveq	#0,d6
	moveq	#0,d7
	sub.l	a0,a0
	sub.l	a1,a1
	sub.l	a2,a2
	sub.l	a3,a3
	move	#$2300,sr
	jmp	Z0000

; ------------------------------------------------------------------------------
; Hardware
; ------------------------------------------------------------------------------

init_hardware:
	move	#$2700,sr
	movem.l	$ffff8240.w,d0-d7
	movem.l	d0-d7,old_palette
	move.b	$ffff8260.w,old_res
	move.b	$ffff820a.w,old_hz
	move.b	$ffff820f.w,old_linewid
	move.b	$ffff8265.w,old_fine
	clr.b	$ffff8260.w		; low resolution, 50 Hz (the border timing is for 50)
	move.b	#2,$ffff820a.w
	move.b	$ffff8201.w,old_screen+1
	move.b	$ffff8203.w,old_screen+2
	move.b	$ffff820d.w,old_screen+3
	move.b	$fffffa07.w,old_fa07
	move.b	$fffffa09.w,old_fa09
	move.b	$fffffa13.w,old_fa13
	move.b	$fffffa15.w,old_fa15
	move.b	$fffffa17.w,old_fa17
	move.b	$fffffa19.w,old_fa19
	move.b	$fffffa1b.w,old_fa1b
	move.b	$fffffa1d.w,old_fa1d
	move.b	$fffffa1f.w,old_fa1f
	move.b	$fffffa21.w,old_fa21
	move.l	$68.w,old_hbl
	move.l	$70.w,old_vbl
	move.l	$118.w,old_acia
	move.l	$120.w,old_timer_b
	move.l	$134.w,old_timer_a
	clr.b	$fffffa07.w
	clr.b	$fffffa09.w
	clr.b	$fffffa13.w
	clr.b	$fffffa15.w
	bclr	#3,$fffffa17.w
	lea	crash_stubs,a0		; exception vectors 2..11 -> crash dump
	lea	$08.w,a1
	moveq	#9,d0
.crash_vec:
	move.l	a0,(a1)+
	addq	#6,a0
	dbf	d0,.crash_vec
	move.l	#hbl,$68.w
	move.l	#vbl,$70.w
	move.l	#acia_isr,$118.w
	move.l	#timer_b,$120.w
	move.l	#timer_a,$134.w
	bset	#0,$fffffa07.w		; Timer B
	bset	#0,$fffffa13.w
	bset	#5,$fffffa07.w		; Timer A
	bset	#5,$fffffa13.w
	bset	#6,$fffffa09.w		; ACIA (keyboard, joysticks)
	bset	#6,$fffffa15.w
	ifnd SIM
.w1:	btst	#1,$fffffc00.w
	beq.s	.w1
	move.b	#$14,$fffffc02.w	; joysticks on
.w2:	btst	#1,$fffffc00.w
	beq.s	.w2
	move.b	#$12,$fffffc02.w	; mouse off
	bsr	jagpad_init
	endc
	rts

restore_hardware:
	move	#$2700,sr
	clr.b	$ffff8901.w		; (the DMA sound off)
	moveq	#8,d0			; the YM2149 silent
.silence:
	move.b	d0,$ffff8800.w
	clr.b	$ffff8802.w
	addq.b	#1,d0
	cmp.b	#11,d0
	blo.s	.silence
	movem.l	old_palette,d0-d7
	movem.l	d0-d7,$ffff8240.w
	move.b	old_res,$ffff8260.w
	move.b	old_hz,$ffff820a.w
	move.b	old_linewid,$ffff820f.w
	move.b	old_fine,$ffff8265.w
	move.b	old_screen+1,$ffff8201.w
	move.b	old_screen+2,$ffff8203.w
	move.b	old_screen+3,$ffff820d.w
	move.b	old_fa07,$fffffa07.w
	move.b	old_fa09,$fffffa09.w
	move.b	old_fa13,$fffffa13.w
	move.b	old_fa15,$fffffa15.w
	move.b	old_fa17,$fffffa17.w
	move.b	old_fa1f,$fffffa1f.w
	move.b	old_fa19,$fffffa19.w
	move.b	old_fa1b,$fffffa1b.w
	move.b	old_fa1d,$fffffa1d.w
	move.b	old_fa21,$fffffa21.w
	move.l	old_hbl,$68.w
	move.l	old_vbl,$70.w
	move.l	old_acia,$118.w
	move.l	old_timer_b,$120.w
	move.l	old_timer_a,$134.w
	ifnd SIM
.w1:	btst	#1,$fffffc00.w
	beq.s	.w1
	move.b	#$08,$fffffc02.w	; mouse on
	endc
	move	#$2300,sr
	rts

quit:
	ifd DEBUG
	bsr	dbg_counters
	endc
	bsr	restore_hardware
	move.l	old_ssp,-(sp)
	move	#$20,-(sp)
	trap	#1
	addq	#6,sp
	clr	-(sp)
	trap	#1

; ------------------------------------------------------------------------------
; Interrupts
; ------------------------------------------------------------------------------

hbl:
	rte

; The VBL: the borders' events, the finished picture shown (render.s vbl_video), the inputs copied into the ports the
; program reads, the arcade's frames counted: 59.94 Hz against the STE's 50, six to five VBLs.

vbl:
	ifnd SIM
	borders_vbl
	endc
	movem.l	d0-d1/a0,-(sp)
	addq.l	#1,frame_counter
	ifd DEBUG
	subq.w	#1,dbg_tl_n		; every 100 VBLs: the arcade frames and pictures so far (RATE.BIN, bench.sh)
	bgt.s	.tl
	move.w	#100,dbg_tl_n
	move.l	dbg_tl_p,a0
	cmp.w	#0,a0
	bne.s	.tl1
	lea	dbg_tl,a0
.tl1:	cmp.l	#dbg_tl_end,a0
	bhs.s	.tl
	move.w	isr_count,(a0)+
	move.w	pic_count,(a0)+
	move.l	a0,dbg_tl_p
.tl:
	endc
	tst.b	quit_flag
	bne	quit
	bsr	vbl_video
	ifnd PLAYBACK
	bsr	jagpad_poll
	jp_merge	in_sys,IO_P2,0
	jp_merge	in_p1,IO_P1,1
	endc
	ifd AUTOPLAY				; (benchmark build: coin, start and random-ish play, period 4000 frames)
	moveq	#0,d0
	move.w	isr_count,d0
	divu	#4000,d0
	swap	d0
	cmp.w	#700,d0
	blo.s	.ap1
	cmp.w	#704,d0
	bhs.s	.ap1
	move.b	#$BF,IO_P2			; coin 1
.ap1:	cmp.w	#760,d0
	blo.s	.ap2
	cmp.w	#764,d0
	bhs.s	.ap2
	move.b	#$DF,IO_P1			; start 1
.ap2:	cmp.w	#840,d0
	blo.s	.ap3
	lsr.w	#5,d0
	and.w	#7,d0
	lea	ap_dirs(pc),a0
	move.b	(a0,d0.w),d0
	btst	#1,frame_counter+3
	beq.s	.ap4
	and.b	#$EF,d0				; fire every other pair of frames
.ap4:	move.b	d0,IO_P1
.ap3:
	endc
	addq.b	#1,vbl_pending		; one arcade frame a VBL, and a second one every 5th: 60 a second
	subq.b	#1,vbl_phase
	bpl.s	.ph
	move.b	#4,vbl_phase
	addq.b	#1,vbl_pending
.ph:	cmp.b	#MAX_PENDING,vbl_pending
	bls.s	.cap
	move.b	#MAX_PENDING,vbl_pending	; (a game that is behind by more than this runs slower)
.cap:
	if FRAMES
	move.l	frame_counter,d0
	cmp.l	#FRAMES,d0
	blt.s	.go_on
	st	quit_flag
.go_on:
	endc
	movem.l	(sp)+,d0-d1/a0
	rte

	ifd AUTOPLAY
ap_dirs:	dc.b	$FE,$F7,$FB,$FD,$FE,$F6,$F7,$FB	; (active low: left 0, down 1, right 2, up 3)
	endc

; ------------------------------------------------------------------------------
; The idle hooks (gen.py HOOKS: $00AC, $0154, d7 = the pc; both are spins): the picture is drawn when due, the next
; arcade frame awaited, and the IRQ (RST 38) delivered with TOKEN as its return address.  Its return (z80_irq_ret)
; continues after the hook (hook_resume: the spin's jr).  When the handler starts a maze search instead (a new Z80
; stack), the next hook simply comes; nothing waits on the 68000 stack: the hook took its continuation off it.
; ------------------------------------------------------------------------------

z80_hook:
	movem.l	d0-d7/a0-a6,-(sp)
	tst.b	frame_dirty
	beq	.check
	tst.b	vbl_pending
	beq	.render
	addq.b	#1,render_skips
	cmp.b	#MAX_SKIP,render_skips
	bls	.check
.render:
	clr.b	render_skips
	clr.b	frame_dirty
	ifd SIM
	bsr	sim_render_start
	endc
	bsr	render_frame
	ifd SIM
	bsr	sim_frame_done
	endc
.check:
	tst.b	vbl_pending
	bne	.deliver
	ifd SIM
	bsr	sim_wait
	bra	.check
	else
	bra	.check
	endc
.deliver:
	ifd PLAYBACK
	bsr	pb_inputs
	endc
	ifnd NOSOUND
	bsr	snd_frame
	endc
	subq.b	#1,vbl_pending
	st	frame_dirty
	addq.w	#1,isr_count
	movem.l	(sp)+,d0-d7/a0-a6
	move.l	(sp)+,hook_resume	; (the continuation: after the IRQ)
	move.w	#TOKEN,-(a5)
	jmp	Z0038
z80_irq_ret:
	move.l	hook_resume,-(sp)
	rts

	ifd PLAYBACK
; The recorded play (build/mrdo/play_inputs.bin; engine/playbot.py: runs of count, SYSTEM (here P2: the coins), P1,
; a count of 0 at the end): the inputs of the arcade frame about to run.
pb_inputs:
	tst.b	pb_left
	bne.s	.same
	move.l	pb_ptr,a0
	cmp.w	#0,a0
	bne.s	.next
	lea	pb_data,a0
.next:	move.b	(a0)+,pb_left
	bne.s	.run
	st	quit_flag		; (the recording is over)
	rts
.run:	move.b	(a0)+,pb_sys
	move.b	(a0)+,pb_p1
	move.l	a0,pb_ptr
.same:	subq.b	#1,pb_left
	move.b	pb_sys,IO_P2
	move.b	pb_p1,IO_P1
	rts
	endc

; `ld ($9801),a` / `ld ($9802),a`: the byte for the SN76489 #1 / #2 into the sound ring (pairs of chip, byte; a
; player would read them); keeps the registers and the flags.
md_sound_bc:				; `ld (bc),a` (5C3A, 5C3E, 5C45): C = $01 / $02 (d1: C in the high byte)
	move	sr,-(sp)
	btst	#9,d1
	bne.s	.two
	move	(sp)+,ccr
	bra.s	md_sound1
.two:	move	(sp)+,ccr
	bra.s	md_sound2
md_sound1:
	move	sr,-(sp)
	move.l	a0,-(sp)
	move.w	d7,-(sp)
	lea	snd_ring,a0
	moveq	#0,d7
	move.b	snd_head,d7
	clr.b	(a0,d7.w)
	bra.s	md_sound
md_sound2:
	move	sr,-(sp)
	move.l	a0,-(sp)
	move.w	d7,-(sp)
	lea	snd_ring,a0
	moveq	#0,d7
	move.b	snd_head,d7
	move.b	#1,(a0,d7.w)
md_sound:
	move.b	d0,1(a0,d7.w)
	addq.b	#2,snd_head		; (128 pairs)
	move.w	(sp)+,d7
	move.l	(sp)+,a0
	move	(sp)+,ccr
	rts

; The video RAM's stores (gen.py tile_marks): the cell (address & $3FF, + $400 for the foreground $8800-$8FFF; the
; attribute and code halves of a layer share it) listed once in cell_list (cell_dirty: its flag) for the renderer.
; Keep everything but d7 and a0 (the translator's scratch registers), the flags too.
md_mark_hl:
	move	sr,-(sp)
	move.w	d3,d7
md_mark_d7:
	btst	#11,d7			; (the foreground)
	beq.s	.bg
	and.w	#$3FF,d7
	or.w	#$400,d7
	bra.s	.cell
.bg:	and.w	#$3FF,d7
.cell:
md_mark_cell:
	lea	cell_dirty,a0		; (a0: a scratch register of the translated code)
	tst.b	(a0,d7.w)
	bne.s	.out
	st	(a0,d7.w)
	move.l	cell_ptr,a0
	move.w	d7,(a0)+
	move.l	a0,cell_ptr
.out:	move	(sp)+,ccr
	rts
md_mark_de:
	move	sr,-(sp)
	move.w	d2,d7
	bra.s	md_mark_d7
md_mark_bc:
	move	sr,-(sp)
	move.w	d1,d7
	ror.w	#8,d7
	bra.s	md_mark_d7
md_mark_ix:				; (the displacement on the stack, above the return address)
	move	sr,-(sp)
	move.w	d4,d7
	add.w	8(sp),d7
	bra.s	md_mark_d7
md_mark_iy:
	move	sr,-(sp)
	move.w	a2,d7
	add.w	8(sp),d7
	bra.s	md_mark_d7
md_mark_n:				; (a static address: the cell on the stack, already computed)
	move	sr,-(sp)
	move.w	8(sp),d7
	bra.s	md_mark_cell
md_mark_all:
	st	tiles_all
	rts

	borders_handlers
	jagpad_text
	jagpad_maps
	borders_blit_go

; ------------------------------------------------------------------------------
; Keyboard / joystick (IKBD): SYSTEM, P1 and P2 are active low bytes
; ------------------------------------------------------------------------------

acia_isr:
	movem.l	d0-d2/a0,-(sp)
.again:
	ikbd_byte
.not_esc:
	lea	key_table,a0
.find:	move.b	(a0),d0
	beq	.again
	cmp.b	d0,d1
	beq	.found
	addq	#4,a0
	bra	.find
.found:	tst.b	d2
	bmi	.release
	move.b	1(a0),d0
	or.b	d0,sys_kbd
	move.b	2(a0),d0
	or.b	d0,p1_kbd
	move.b	3(a0),d0
	or.b	d0,p2_kbd
	bsr	compose_inputs
	bra	.again
.release:
	move.b	1(a0),d0
	not.b	d0
	and.b	d0,sys_kbd
	move.b	2(a0),d0
	not.b	d0
	and.b	d0,p1_kbd
	move.b	3(a0),d0
	not.b	d0
	and.b	d0,p2_kbd
	bsr	compose_inputs
	bra	.again
.packet_byte:
	clr.b	ikbd_state
	cmp.b	#1,d0
	bne	.joy1
	move.b	d1,joy0_state
	bra	.joy_update
.joy1:	move.b	d1,joy1_state
.joy_update:
	; both joysticks play (the players take turns): left 0, down 1, right 2, up 3, fire 4
	move.b	joy1_state,d1
	bsr	.joy
	move.b	d0,p1_joy
	move.b	joy0_state,d1
	bsr	.joy
	or.b	d0,p1_joy
	bsr	compose_inputs
	bra	.again
.joy:	moveq	#0,d0
	btst	#2,d1			; left
	beq.s	.j1
	bset	#0,d0
.j1:	btst	#1,d1			; down
	beq.s	.j2
	bset	#1,d0
.j2:	btst	#3,d1			; right
	beq.s	.j3
	bset	#2,d0
.j3:	btst	#0,d1			; up
	beq.s	.j4
	bset	#3,d0
.j4:	tst.b	d1			; fire
	bpl.s	.j5
	bset	#4,d0
.j5:	rts
.done:	movem.l	(sp)+,d0-d2/a0
	rte

compose_inputs:
	move.b	sys_kbd,d0
	not.b	d0
	move.b	d0,in_sys
	move.b	p1_kbd,d0
	or.b	p1_joy,d0
	not.b	d0
	move.b	d0,in_p1
	move.b	p2_kbd,d0
	or.b	p2_joy,d0
	not.b	d0
	move.b	d0,in_p2
	rts

; scancode, P2 bits (coin 1 = 6, coin 2 = 7), P1 bits (left 0, down 1, right 2, up 3, fire 4, start 1 = 5,
; start 2 = 6), unused
key_table:
	dc.b	$4b,$00,$01,$00		; left
	dc.b	$50,$00,$02,$00		; down
	dc.b	$4d,$00,$04,$00		; right
	dc.b	$48,$00,$08,$00		; up
	dc.b	$39,$00,$10,$00		; space = fire
	dc.b	$1d,$00,$10,$00		; control = fire
	dc.b	$2c,$00,$10,$00		; Z = fire
	dc.b	$02,$00,$20,$00		; 1 = start 1
	dc.b	$03,$00,$40,$00		; 2 = start 2
	dc.b	$06,$40,$00,$00		; 5 = coin 1
	dc.b	$07,$80,$00,$00		; 6 = coin 2
	dc.b	0,0,0,0
	even

; ------------------------------------------------------------------------------
; Crash dump (CRASH.TXT: vector, registers, the stack top)
; ------------------------------------------------------------------------------

crash_stubs:
	rept 10
	moveq	#REPTN+2,d0
	bra.w	crash_common
	endr

crash_common:
	move	#$2700,sr
	move	d0,crash_vector
	movem.l	d0-d7/a0-a6,crash_regs
	move.l	sp,crash_sp
	lea	crash_text,a0
	lea	crash_vector,a1
	moveq	#0,d1
	move	(a1),d1
	bsr	hex_word
	move.b	#' ',(a0)+
	lea	crash_sp,a1
	move.l	(a1),d1
	bsr	hex_long
	move.b	#' ',(a0)+
	lea	start(pc),a1		; the load address: map address = address - this
	move.l	a1,d1
	bsr	hex_long
	move.b	#13,(a0)+
	move.b	#10,(a0)+
	lea	crash_regs,a1
	moveq	#14,d2
.regs:	move.l	(a1)+,d1
	bsr	hex_long
	move.b	#' ',(a0)+
	dbf	d2,.regs
	move.b	#13,(a0)+
	move.b	#10,(a0)+
	move.l	crash_sp,a1
	moveq	#15,d2
.stack:	move	(a1)+,d1
	bsr	hex_word
	move.b	#' ',(a0)+
	dbf	d2,.stack
	move.b	#13,(a0)+
	move.b	#10,(a0)+
	lea	own_stack_top,sp
	move.l	a0,d7
	sub.l	#crash_text,d7
	clr	-(sp)			; Fcreate
	pea	crash_name
	move	#$3c,-(sp)
	trap	#1
	addq	#8,sp
	move	d0,d6
	pea	crash_text		; Fwrite
	move.l	d7,-(sp)
	move	d6,-(sp)
	move	#$40,-(sp)
	trap	#1
	lea	12(sp),sp
	move	d6,-(sp)		; Fclose
	move	#$3e,-(sp)
	trap	#1
	addq	#4,sp
	bsr	restore_hardware
	bsr	crash_notice
	clr	-(sp)
	trap	#1

hex_long:
	swap	d1
	bsr.s	hex_word
	swap	d1
hex_word:
	move	d1,-(sp)
	lsr	#8,d1
	bsr.s	hex_byte
	move	(sp)+,d1
hex_byte:
	move	d1,-(sp)
	lsr	#4,d1
	bsr.s	hex_digit
	move	(sp)+,d1
hex_digit:
	and	#15,d1
	move.b	hex_chars(pc,d1.w),(a0)+
	rts
hex_chars:
	dc.b	"0123456789ABCDEF"
crash_name:
	dc.b	"CRASH.TXT",0
	even

	ifd SIM
sim_wait:				; the test harness stops here when the foreground waits with nothing pending: it
	bra.s	sim_wait		; sets vbl_pending (and the inputs) and returns (rts) from here
sim_render_start:			; (render_test.py measures from here)
	bra.s	sim_render_start
sim_frame_done:				; the harness compares here (a picture is drawn), returns with rts
	bra.s	sim_frame_done
sim_render_ret:				; render_test.py calls render_frame with this as the return address
	bra.s	sim_render_ret
	endc

z80_halt:				; (not in the program: a halt in data taken for code)
	move.l	frame_counter,d7
.wait:	cmp.l	frame_counter,d7
	beq.s	.wait
	rts

	ifd DEBUG
; COUNTERS.BIN (words): VBLs, pictures, arcade frames, the frames whose top border the VBL armed, the late border
; events (engine/rt/borders.s); RATE.BIN: (arcade frames, pictures) every 100 VBLs
dbg_counters:
	lea	dbg_buf,a0
	move.w	frame_counter+2,(a0)+
	move.w	pic_count,(a0)+
	move.w	isr_count,(a0)+
	move.w	bd_fallbacks,(a0)+
	move.w	bd_late_top,(a0)+
	move.w	bd_late_on,(a0)+
	move.w	bd_late_low,(a0)+
	move.w	bd_late_off,(a0)+
	move.l	bd_pieced,(a0)+
	lea	dbg_name3,a1
	lea	dbg_tl,a2
	move.l	dbg_tl_p,d0
	sub.l	a2,d0
	bsr	dbg_write
	lea	dbg_name2,a1
	lea	dbg_buf,a2
	moveq	#20,d0
	bsr	dbg_write
	rts
dbg_write:				; a1 = the name, a2 = the data, d0.l = its length
	movem.l	d0/a2,-(sp)
	clr	-(sp)
	move.l	a1,-(sp)
	move	#$3c,-(sp)
	trap	#1
	addq	#8,sp
	move	d0,d6
	movem.l	(sp)+,d0/a2
	move.l	a2,-(sp)
	move.l	d0,-(sp)
	move	d6,-(sp)
	move	#$40,-(sp)
	trap	#1
	lea	12(sp),sp
	move	d6,-(sp)
	move	#$3e,-(sp)
	trap	#1
	addq	#4,sp
	rts
dbg_name2:
	dc.b	"COUNTERS.BIN",0
dbg_name3:
	dc.b	"RATE.BIN",0
	even
	endc

; ------------------------------------------------------------------------------
; Fatal errors of the translated code
; ------------------------------------------------------------------------------

z80_badpc:
z80_badjump:
z80_unsupported:
	move	#$2700,sr
	ifd SIM
	bra.s	z80_badpc
	endc
	moveq	#99,d0			; the dump: d7 = the address
	bra	crash_common

	include	"render.s"
	ifnd NOSOUND
	include	"sound.s"
	endc

; ------------------------------------------------------------------------------
; The translated program (and its dispatch table in the data section)
	include	"code_main.s"

	section text,code
	include	"rtlib.s"

	section data,data
	ifd PLAYBACK
pb_data:	incbin	"play_inputs.bin"
	even
	endc

; The Z80's 64 KB (a6 = its address 0, signed offsets): $8000-$FFFF (video, sprite RAM, the inputs at $A000-$A003, the
; RAM, the scroll registers; IY / F' at $9E00 / $9E02: gen.py) first, then the ROM at $0000-$7FFF.
	cnop	0,4
g_block:	dcb.b	$8000,0
	incbin	"mrdo.rom"

; ------------------------------------------------------------------------------
	section bss,bss
; ------------------------------------------------------------------------------

old_ssp:	ds.l	1
old_screen:	ds.l	1
old_palette:	ds.l	8
old_hbl:	ds.l	1
old_vbl:	ds.l	1
old_acia:	ds.l	1
old_timer_b:	ds.l	1
old_timer_a:	ds.l	1
hook_resume:	ds.l	1
old_res:	ds.b	1
old_hz:		ds.b	1
old_linewid:	ds.b	1
old_fine:	ds.b	1
old_fa07:	ds.b	1
old_fa09:	ds.b	1
old_fa13:	ds.b	1
old_fa15:	ds.b	1
old_fa17:	ds.b	1
old_fa19:	ds.b	1
old_fa1b:	ds.b	1
old_fa1d:	ds.b	1
old_fa1f:	ds.b	1
old_fa21:	ds.b	1
	even
quit_flag:	ds.b	1
	borders_vars
	jagpad_vars
vbl_pending:	ds.b	1		; arcade frames that have come (the VBL adds, the hook takes one)
vbl_phase:	ds.b	1
render_skips:	ds.b	1
frame_dirty:	ds.b	1		; an arcade frame ran since the last picture
snd_head:	ds.b	1
	even
cell_ptr:	ds.l	1		; the end of cell_list (render_tiles empties it)
cell_list:	ds.w	2048		; the video RAM cells written since the renderer looked (md_mark_*), once each
cell_dirty:	ds.b	2048		; their flags
tiles_all:	ds.b	1		; (a block copy into the video RAM: every cell)
	even
snd_ring:	ds.b	256		; the SN76489 bytes (the last 128: chip, byte)
	ikbd_vars
joy0_state:	ds.b	1
joy1_state:	ds.b	1
sys_kbd:	ds.b	1
p1_kbd:		ds.b	1
p2_kbd:		ds.b	1
p1_joy:		ds.b	1
p2_joy:		ds.b	1
in_sys:		ds.b	1
in_p1:		ds.b	1
in_p2:		ds.b	1
	even
isr_count:	ds.w	1
pic_count:	ds.w	1
	ifd PLAYBACK
pb_ptr:		ds.l	1
pb_left:	ds.b	1
pb_sys:		ds.b	1
pb_p1:		ds.b	1
	even
	endc
	ifd DEBUG
dbg_tl_n:	ds.w	1
dbg_tl_p:	ds.l	1
dbg_tl:		ds.l	400		; (40000 VBLs)
dbg_tl_end:
dbg_buf:	ds.l	16
	endc
crash_vector:	ds.w	1
crash_sp:	ds.l	1
crash_regs:	ds.l	16
crash_text:	ds.b	512
frame_counter:	ds.l	1
	ds.l	1024
own_stack_top:
