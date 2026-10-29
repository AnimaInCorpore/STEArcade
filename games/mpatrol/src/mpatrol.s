; Moon Patrol (Irem M52, 1982) for the Atari STE: the main Z80 program translated (tools/gen.py ->
; build/mpatrol/code_mpatrol.s), the picture drawn by render.s (so far the score panel; the playfield is black).
; SIM: the simulator build for the tests (tools/logic_test.py): no hardware, the harness drives the frames.

	ifnd MAX_PENDING
MAX_PENDING = 3				; arcade frames that may be waiting (the game catches up after a slow picture)
	endc
	ifnd MAX_SKIP
MAX_SKIP = 2				; arcade frames in a row that are not drawn while the game is behind
	endc
	ifnd FRAMES
FRAMES = 0				; (a test build quits after this many VBLs)
	endc
ARCADE_FRAC = 8830			; the arcade's 56.7376 Hz on the STE's 50: 1 + 8830 / 65536 frames a VBL

KEY_ESC = $01

; Border removal, the palettes and the panel's own image: engine/rt/borders.s (BD_HUD + BD_VSWITCH: the score panel,
; picture lines 0-49, from its own image with its own palette; the playfield below it from its buffer).
	ifnd TA_DATA
TA_DATA = 98
	endc
	ifnd TA_NOPS
TA_NOPS = 84
	endc
PIC_TOP = 10				; the picture's first displayed line
PIC_LINES = 252
BD_PALETTE = 1
BD_HUD = 1
BD_VSWITCH = 1
	include	"borders.s"

; the pads (engine/rt/jagpad.s): IN0, IN1, IN2 bits as in key_table (bytes 0-2 of each long; active high there)
JP_SH1 = 16
JP_SH2 = 8
JP1_RIGHT = $01<<JP_SH1
JP1_LEFT = $02<<JP_SH1
JP1_DOWN = 0
JP1_UP = 0
JP1_B1 = $80<<JP_SH1			; (pad A: button 1)
JP1_B2 = $20<<JP_SH1			; (pad B: button 2)
JP1_B3 = 0
JP2_RIGHT = $01<<JP_SH2
JP2_LEFT = $02<<JP_SH2
JP2_DOWN = 0
JP2_UP = 0
JP2_B1 = $80<<JP_SH2
JP2_B2 = $20<<JP_SH2
JP2_B3 = 0
JP_START1 = $01<<24
JP_START2 = $02<<24
JP_COIN1 = $08<<24
JP_COIN2 = $10<<JP_SH2			; (coin 2 is IN2 bit 4)
	include	"jagpad.s"
	include	"ikbd.s"

; The Z80's 64 KB: a6 = g_block + $8000 = Z80 address 0 (signed word offsets: $8000-$FFFF lie below a6).
G_Z80 = g_block+$8000
Z_RAM = g_block-$8000			; + a Z80 address >= $8000
TOKEN = $FEF7				; $F7FE on the Z80 stack, byte swapped (gen.py / machine.py TOKEN)

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

	ifnd SIM			; (the test harness sets the inputs, the DIP switches of its seed)
	move.l	#$FFFFFFFE,io_in	; IN0, IN1, IN2: nothing pressed; DSW1: 3 lives, bonus 10000 30000 50000, 1 coin 1
	move.b	#$FD,io_in+4		; credit; DSW2: no flip, upright, coin mode 1, no cheats
	ifd DSW2
	move.b	#DSW2,io_in+4
	endc
	move.b	#$FF,in_sys
	move.b	#$FF,in_p1
	move.b	#$FF,in_p2
	endc
	bsr	init_hardware
	bsr	init_render
	move.w	#$ACE1,rnd_state
	bsr	put_inputs

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

; The memory-mapped inputs live in the Z80 block ($D000-$D004: IN0, IN1, IN2, DSW1, DSW2; the program reads them
; there, also through (de) and (hl)): io_in is copied there when an arcade frame starts.
put_inputs:
	move.l	io_in,Z_RAM+$D000
	move.b	io_in+4,Z_RAM+$D004
	rts

; ------------------------------------------------------------------------------
; Hardware
; ------------------------------------------------------------------------------

init_hardware:
	ifnd SIM
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
	ifnd SIM
	move	#$2700,sr
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
.w1:	btst	#1,$fffffc00.w
	beq.s	.w1
	move.b	#$08,$fffffc02.w	; mouse on
	move	#$2300,sr
	endc
	rts

quit:
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

; The VBL: the borders' events, the panel and playfield shown (render.s vbl_video), the inputs copied into io_in, the
; arcade's frames counted: 56.7376 Hz on the STE's 50 (ARCADE_FRAC).
vbl:
	ifnd SIM
	borders_vbl
	endc
	movem.l	d0-d1/a0,-(sp)
	addq.l	#1,frame_counter
	tst.b	quit_flag
	bne	quit
	bsr	vbl_video
	ifnd SIM
	bsr	bd_hud_plan
	bsr	jagpad_poll
	jp_merge	in_sys,io_in,0
	jp_merge	in_p1,io_in+1,1
	jp_merge	in_p2,io_in+2,2
	endc
	addq.b	#1,vbl_pending
	add.w	#ARCADE_FRAC,vbl_frac
	bcc.s	.ph
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

; ------------------------------------------------------------------------------
; The idle hooks (gen.py: machine.MoonPatrolPort.HOOKS and IRQ_WAITS; d7 = the pc): the foreground goes on (rts)
; unless it waits for the IRQ there; then the picture is drawn when due, the next arcade frame awaited and the IRQ
; (RST 38) delivered with TOKEN as its return address.  Its return (z80_irq_ret) continues after the hook
; (hook_resume): the instruction at the hook runs before its condition is looked at again.  When the handler restarts
; the foreground instead (0104: a new Z80 stack), the next hook simply comes.  An IRQ wait ($00AF, the stop mode:
; inside the handler) waits for the next arcade frame and goes on there, without an IRQ.
; ------------------------------------------------------------------------------

z80_hook:
	movem.l	d0-d7/a0-a6,-(sp)
	cmp.w	#$026E,d7		; the work loop: once a frame
	beq	.wait
	cmp.w	#$05ED,d7
	beq.s	.e050
	cmp.w	#$0359,d7
	beq.s	.e050
	cmp.w	#$0315,d7
	beq.s	.e050
	cmp.w	#$078E,d7
	beq.s	.e047
	cmp.w	#$010D,d7
	beq.s	.start
	cmp.w	#$01A7,d7
	beq.s	.cont
	cmp.w	#$0B59,d7
	beq.s	.select
	cmp.w	#$00AF,d7
	beq.s	.stop
	bra.s	.busy
.e050:	tst.b	Z_RAM+$E050		; a wait of $E050 frames
	bne.s	.wait
	bra.s	.busy
.e047:	tst.b	Z_RAM+$E047
	bne.s	.wait
	bra.s	.busy
.start:	bsr	starts			; push start
	beq.s	.wait
	bra.s	.busy
.cont:	tst.b	Z_RAM+$E050		; the continue's countdown
	beq.s	.busy
	tst.b	Z_RAM+$E048
	beq.s	.wait
	bsr	starts
	beq.s	.wait
	bra.s	.busy
.select: cmp.b	#1,Z_RAM+$E051		; sector selection: until the time runs out
	bhi.s	.wait
	bra.s	.busy
.stop:	btst	#0,Z_RAM+$D000		; stop mode: the handler waits for start 1
	beq.s	.busy
	bsr	next_frame
	movem.l	(sp)+,d0-d7/a0-a6
	rts
.busy:	movem.l	(sp)+,d0-d7/a0-a6
	rts
.wait:	bsr	next_frame
	movem.l	(sp)+,d0-d7/a0-a6
	move.l	(sp)+,hook_resume	; (the continuation: after the IRQ)
	move.w	#TOKEN,-(a5)
	jmp	Z0038
z80_irq_ret:
	move.l	hook_resume,-(sp)
	rts

; 0533's start check (machine.MoonPatrolPort.starts): ne when start 1, or start 2 with more than one credit
starts:
	btst	#0,Z_RAM+$E053
	bne.s	.yes
	btst	#1,Z_RAM+$E053
	beq.s	.no
	cmp.b	#1,Z_RAM+$E048
	beq.s	.no
.yes:	moveq	#-1,d7
	rts
.no:	moveq	#0,d7
	rts

; The end of an arcade frame: the picture when due, then the next arcade frame (its inputs into the block).
next_frame:
	tst.b	frame_dirty
	beq.s	.check
	tst.b	vbl_pending
	beq.s	.render
	addq.b	#1,render_skips
	cmp.b	#MAX_SKIP,render_skips
	bls.s	.check
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
.check:	tst.b	vbl_pending
	bne.s	.go
	ifd SIM
	bsr	sim_wait
	endc
	bra.s	.check
.go:	subq.b	#1,vbl_pending
	st	frame_dirty
	addq.w	#1,isr_count
	bra	put_inputs

; ------------------------------------------------------------------------------
; The latches and the I/O ports (gen.py): they keep the registers (but d7) and the flags (but mp_outi's)
; ------------------------------------------------------------------------------

; `ld ($D000),a`: the sound command (d0) into the ring; IN0 back into the block
mp_sound:
	move	sr,-(sp)
	move.l	a0,-(sp)
	lea	snd_ring,a0
	moveq	#0,d7
	move.b	snd_head,d7
	move.b	d0,(a0,d7.w)
	addq.b	#1,snd_head
	move.b	io_in,Z_RAM+$D000
	move.l	(sp)+,a0
	move	(sp)+,ccr
	rts

; `ld ($D001),a`: the flip latch and the coin counters; IN1 back into the block
mp_flip:
	move	sr,-(sp)
	move.b	d0,io_flip
	move.b	io_in+1,Z_RAM+$D001
	move	(sp)+,ccr
	rts

; `out ($C0),a`: the background control
mp_out_c0:
	move	sr,-(sp)
	move.b	d0,io_regs+6
	move	(sp)+,ccr
	rts

; `out (c),a`: the port is C (d1's high byte)
mp_out_c:
	move	sr,-(sp)
	move.w	d1,d7
	lsr.w	#8,d7
	bsr.s	mp_port
	move	(sp)+,ccr
	rts

; `outi`: (hl) to port C, hl + 1, b - 1; returns with the CCR's N and Z of b - 1 and C the carry of (hl) + l (MAME)
mp_outi:
	move.l	d0,-(sp)
	move.w	d1,d7
	lsr.w	#8,d7
	move.b	(a6,d3.w),d0
	bsr.s	mp_port
	addq.w	#1,d3
	add.b	d3,d0
	scs	d7
	move.l	(sp)+,d0
	subq.b	#1,d1
	move	sr,-(sp)
	andi.w	#$FFFE,(sp)
	tst.b	d7
	beq.s	.out
	ori.w	#1,(sp)
.out:	move	(sp)+,ccr
	rts

; d7.b = the port, d0.b = the byte: io_regs + (port >> 5); port $40 (background 1 x) also sets the protection read
; at $8800: popcount(x & $7F) ^ (x >> 7).  Keeps everything but d7 and the flags.
mp_port:
	movem.l	d0-d1/a0,-(sp)
	and.w	#$E0,d7
	lsr.w	#5,d7
	lea	io_regs,a0
	move.b	d0,(a0,d7.w)
	cmp.w	#2,d7
	bne.s	.out
	moveq	#0,d7
	moveq	#6,d1
.count:	btst	d1,d0
	beq.s	.zero
	addq.b	#1,d7
.zero:	dbf	d1,.count
	btst	#7,d0
	beq.s	.put
	eor.b	#1,d7
.put:	move.b	d7,Z_RAM+$8800
.out:	movem.l	(sp)+,d0-d1/a0
	rts

; `ld a,r` (the refresh register): a pseudo random byte; the reference (machine.MoonPatrolPort.rnd) has the same.
z80_rnd:
	move.w	rnd_state,d7
	lsr.w	#1,d7
	bcc.s	.no
	eor.w	#$B400,d7
.no:	move.w	d7,rnd_state
	move.b	d7,d0
	rts

	borders_handlers
	jagpad_text
	jagpad_maps
	borders_blit_go

; ------------------------------------------------------------------------------
; Keyboard / joystick (IKBD): IN0, IN1 and IN2 are active low bytes
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
	; joystick 1 (port 1) plays player 1, joystick 0 player 2: right 0, left 1, up = button 2 (5), fire = button 1 (7)
	move.b	joy1_state,d1
	bsr	.joy
	move.b	d0,p1_joy
	move.b	joy0_state,d1
	bsr	.joy
	move.b	d0,p2_joy
	bsr	compose_inputs
	bra	.again
.joy:	moveq	#0,d0
	btst	#3,d1			; right
	beq.s	.j1
	bset	#0,d0
.j1:	btst	#2,d1			; left
	beq.s	.j2
	bset	#1,d0
.j2:	btst	#0,d1			; up
	beq.s	.j4
	bset	#5,d0
.j4:	tst.b	d1			; fire
	bpl.s	.j5
	bset	#7,d0
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

; scancode, IN0 bits (start 1 = 0, start 2 = 1, coin 1 = 3), IN1 bits (right 0, left 1, button 2 = 5, button 1 = 7),
; IN2 bits (coin 2 = 4)
key_table:
	dc.b	$4d,$00,$01,$00		; right
	dc.b	$4b,$00,$02,$00		; left
	dc.b	$48,$00,$20,$00		; up = button 2
	dc.b	$39,$00,$80,$00		; space = button 1
	dc.b	$1d,$00,$80,$00		; control = button 1
	dc.b	$2c,$00,$80,$00		; Z = button 1
	dc.b	$38,$00,$20,$00		; alternate = button 2
	dc.b	$2d,$00,$20,$00		; X = button 2
	dc.b	$02,$01,$00,$00		; 1 = start 1
	dc.b	$03,$02,$00,$00		; 2 = start 2
	dc.b	$06,$08,$00,$00		; 5 = coin 1
	dc.b	$07,$00,$00,$10		; 6 = coin 2
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
	ifd SIM
	bra.s	crash_common
	endc
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
sim_render_start:			; (render tests measure from here)
	bra.s	sim_render_start
sim_frame_done:				; the harness compares here (a picture is drawn), returns with rts
	bra.s	sim_frame_done
sim_render_ret:				; render_test.py calls render_frame with this as the return address
	bra.s	sim_render_ret
	endc

z80_halt:				; (not in the program: a halt in data taken for code)
	rts

; Fatal errors of the translated code (d7 = the address)
z80_badpc:
z80_badjump:
z80_unsupported:
	move	#$2700,sr
	ifd SIM
	bra.s	z80_badpc
	endc
	moveq	#99,d0
	bra	crash_common

	include	"render.s"

; ------------------------------------------------------------------------------
; The translated program (and its dispatch table in the data section)
	include	"code_mpatrol.s"

	section text,code
	include	"rtlib.s"

	section data,data
; The Z80's 64 KB (a6 = its address 0, signed offsets): $8000-$FFFF (RAM, zero) first, then the ROM at $0000-$7FFF.
	cnop	0,4
g_block:	dcb.b	$8000,0
	incbin	"mpatrol.rom"

; ------------------------------------------------------------------------------
	section bss,bss
; ------------------------------------------------------------------------------
	even
old_ssp:	ds.l	1
old_screen:	ds.l	1
old_palette:	ds.l	8
old_hbl:	ds.l	1
old_vbl:	ds.l	1
old_acia:	ds.l	1
old_timer_b:	ds.l	1
old_timer_a:	ds.l	1
hook_resume:	ds.l	1
io_in:		ds.b	8		; IN0, IN1, IN2, DSW1, DSW2 (active low; the harness / the IKBD keeps them)
io_regs:	ds.b	8		; the I/O ports by port >> 5: 0 text scroll, 2 / 3 bg 1 x / y, 4 / 5 bg 2 x / y, 6 control
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
quit_flag:	ds.b	1
vbl_pending:	ds.b	1		; arcade frames that have come (the VBL adds, the hook takes one)
render_skips:	ds.b	1
frame_dirty:	ds.b	1		; an arcade frame ran since the last picture
io_flip:	ds.b	1		; `ld ($D001),a`
snd_head:	ds.b	1
	even
	borders_vars
	jagpad_vars
shown_pal:	ds.w	16		; the playfield's colours (borders.s)
black_pal:	ds.w	16
hud_pal:	ds.w	16		; the panel's
hud_top:	ds.w	1
hud_bot:	ds.w	1
vbl_frac:	ds.w	1
snd_ring:	ds.b	256		; the sound commands (the last 256)
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
rnd_state:	ds.w	1
isr_count:	ds.w	1
crash_vector:	ds.w	1
crash_sp:	ds.l	1
crash_regs:	ds.l	16
crash_text:	ds.b	512
frame_counter:	ds.l	1
	ds.l	1024
own_stack_top:
