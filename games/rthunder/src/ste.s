; Rolling Thunder for the Atari STE: the program around the translated CPUs (core.s), the picture (render.s) and the MCU's
; mailbox (mcu.s).
;
; Start: the state of the reference at arcade frame 200 (tools/build.py: build/rthunder/snap.bin: the tile RAMs, the shared
; RAM with the sprite RAM, the MCU's mailbox, the scroll registers, both CPUs' registers and banks) is loaded and both
; CPUs wait at their idle points.  Then, once per arcade frame (the VBL counts them: 60 a second against the STE's 50,
; six to five): the inputs, the vertical blank's work (sprite list latch, the MCU's frame), port_frame (both CPUs, core.s),
; and the picture when it is due (render_picture) - published for the VBL, which shows it (hardware scroll: video address,
; fine scroll, line width).

KEY_ESC = $01

	ifnd MAX_PENDING
MAX_PENDING = 3				; arcade frames that may be waiting (the game catches up after a slow picture)
	endc
	ifnd MAX_SKIP
MAX_SKIP = 3				; arcade frames in a row that are not drawn while the game is behind
	endc
	ifnd FRAMES
FRAMES = 0
	endc
	ifnd TA_DATA
TA_DATA = 98
	endc
	ifnd TA_NOPS
TA_NOPS = 84
	endc
PIC_TOP = 20				; the picture's first displayed line
PIC_LINES = 224
BD_PALETTE = 1
	include	"borders.s"

; the pads (engine/rt/jagpad.s): byte 0 = IN0, byte 1 = IN1, byte 2 = IN2 of the key_table's longs (active high there).
; IN0: button 2 (bit 1), down (2), P2 down (3), P2 right (4), coin 1 (5), start 1 (6), service (7); IN1: button 3 (0),
; P2 button 2 (1), up (2), P2 up (3), service 1 (4), coin 2 (5), start 2 (6); IN2: button 1 (3), left (4), right (5),
; P2 button 1 (6), P2 left (7).  Pad A plays player 1, pad B player 2.
JP1_LEFT = $10<<8
JP1_RIGHT = $20<<8
JP1_UP = $04<<16
JP1_DOWN = $04<<24
JP1_B1 = $08<<8
JP1_B2 = $02<<24
JP1_B3 = $01<<16
JP2_LEFT = $80<<8
JP2_RIGHT = $10<<24
JP2_UP = $08<<16
JP2_DOWN = $08<<24
JP2_B1 = $40<<8
JP2_B2 = $02<<16
JP2_B3 = 0
JP_START1 = $40<<24
JP_START2 = $40<<16
JP_COIN1 = $20<<24
JP_COIN2 = $20<<16
	include	"jagpad.s"
	include	"ikbd.s"

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
	bsr	init_tables
	bsr	init_contexts
	bsr	load_snapshot
	bsr	mcu_init
	bsr	init_hardware
	bsr	init_picture
	move.b	#$FF,kin0
	move.b	#$FF,kin1
	move.b	#$FF,kin2
	move.b	#$FF,io_in0
	move.b	#$FF,io_in1
	move.b	#$FF,io_in2
	move	#$2300,sr
	bra	game_loop

; the dispatch tables' unused entries
init_tables:
	lea	bad_block,a0
	move.w	#256-1,d0
.bad:	move.l	#cpu_badpc,(a0)+
	dbf	d0,.bad
	lea	bad_table,a0
	moveq	#32-1,d0
.bdir:	move.l	#bad_block,(a0)+
	dbf	d0,.bdir
	rts

; ---- load_snapshot: build/rthunder/snap.bin (tools/build.py) into the RAMs and the CPUs' contexts ----
; layout: vram0 $2000, vram1 $2000, shared $2000 (with the sprite RAM), cus30 $400, hwregs $40, then per CPU 16 bytes:
; A.w B.w X.w Y.w U.w S.w CC.b bank.b (2 spare)
load_snapshot:
	lea	snapshot,a1
	lea	vram0,a0
	move.w	#($2000*3+$400+$40)/4-1,d0
.c:	move.l	(a1)+,(a0)+
	dbf	d0,.c
	lea	ctx_main,a6
	moveq	#8,d6			; the stack's slot * 4 (main: slot 2)
	lea	banks_main,a2
	lea	main_page_tables,a3
	bsr.s	load_cpu
	lea	ctx_sub,a6
	moveq	#0,d6			; sub: slot 0
	lea	rom_sub,a2
	lea	sub_page_tables,a3
; a1 = the CPU's record, a6 = its context, d6 = its stack's slot * 4, a2 = the banks' base, a3 = the page tables
load_cpu:
	lea	R_D0(a6),a0
	moveq	#4,d2
.r:	moveq	#0,d0
	move.w	(a1)+,d0
	move.l	d0,(a0)+
	dbf	d2,.r
	moveq	#0,d0
	move.w	(a1)+,d0		; S
	add.l	VB(a6,d6.w),d0
	move.l	d0,R_A5(a6)
	moveq	#0,d0
	move.b	(a1)+,d0		; CC
	move.w	d0,d1
	and.w	#$0F,d1
	move.w	d1,R_SR(a6)
	and.b	#$F0,d0
	move.b	d0,CCHI(a6)
	moveq	#0,d0
	move.b	(a1)+,d0		; the bank
	addq.l	#2,a1
	move.w	d0,d1
	addq.w	#8,d1			; its page
	move.w	d1,PID+6(a6)
	mulu	#$2000,d0
	add.l	a2,d0
	move.l	d0,PB+12(a6)
	sub.l	#$6000,d0
	move.l	d0,VB+12(a6)
	lsl.w	#2,d1
	move.l	(a3,d1.w),TBL+12(a6)
	rts

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
.w1:	btst	#1,$fffffc00.w
	beq.s	.w1
	move.b	#$14,$fffffc02.w	; joysticks on
.w2:	btst	#1,$fffffc00.w
	beq.s	.w2
	move.b	#$12,$fffffc02.w	; mouse off
	bsr	jagpad_init
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
.w1:	btst	#1,$fffffc00.w
	beq.s	.w1
	move.b	#$08,$fffffc02.w	; mouse on
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

; The VBL: the borders' events, the finished picture shown, the inputs merged, the arcade's frames counted: 60 Hz against
; the STE's 50, six to five VBLs.
vbl:
	borders_vbl
	movem.l	d0-d2/a0,-(sp)
	addq.l	#1,frame_counter
	tst.b	quit_flag
	bne	quit
	bsr	vbl_video
	bsr	jagpad_poll
	jp_merge	kin0,io_in0,0
	jp_merge	kin1,io_in1,1
	jp_merge	kin2,io_in2,2
	ifd AUTOPLAY
	bsr	autoplay
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
	movem.l	(sp)+,d0-d2/a0
	rte

; vbl_video: the published picture shown from the next frame on (the video base is read at the frame's start): the video
; address of its first line less the border lines above the picture, the fine scroll and the line width
vbl_video:
	moveq	#0,d1
	move.b	frame_ready,d1
	beq.s	.out
	clr.b	frame_ready
	subq.w	#1,d1
	move.w	d1,shown_idx
	lsl.w	#2,d1
	lea	pub_vid,a0
	move.l	(a0,d1.w),d0
	sub.l	#PIC_TOP*RB_LB,d0
	move.l	d0,-(sp)
	move.b	1(sp),$ffff8201.w
	move.b	2(sp),$ffff8203.w
	move.b	3(sp),$ffff820d.w
	addq.l	#4,sp
	lsr.w	#1,d1
	lea	pub_fine,a0
	move.w	(a0,d1.w),d2
	move.b	d2,$ffff8265.w
	move.b	#(RB_LB-160)/2,d1
	tst.b	d2
	beq.s	.w
	subq.b	#4,d1			; (the fine scroll fetches one more group a line)
.w:	move.b	d1,$ffff820f.w
	addq.w	#1,pic_shown
	tst.b	pal_on			; the first picture: the palette comes on
	bne.s	.out
	st	pal_on
	lea	ren_pal,a0
	lea	shown_pal,a1
	moveq	#7,d0
.p:	move.l	(a0)+,(a1)+
	dbf	d0,.p
.out:	rts

; ------------------------------------------------------------------------------
; The program
; ------------------------------------------------------------------------------

game_loop:
.wait:	tst.b	vbl_pending
	beq.s	.wait
	subq.b	#1,vbl_pending
	addq.w	#1,isr_count
	bsr	mcu_frame		; the vertical blank's work: the sprite list latched, the MCU's frame
	bsr	port_frame		; both CPUs
	tst.b	vbl_pending		; behind: not every frame is drawn
	beq.s	.draw
	addq.b	#1,render_skips
	cmp.b	#MAX_SKIP,render_skips
	bls.s	game_loop
.draw:	clr.b	render_skips
	bsr	render_picture
	bra.s	game_loop

; render_picture: a display buffer neither shown nor waiting brought up to the arcade frame, then published
render_picture:
	moveq	#0,d0
	moveq	#0,d1
	move.b	frame_ready,d1
	subq.w	#1,d1			; (-1: none waiting)
.pick:	cmp.w	shown_idx,d0
	beq.s	.nx
	cmp.w	d1,d0
	bne.s	.got
.nx:	addq.w	#1,d0
	bra.s	.pick
.got:	move.w	d0,ren_buf
	bsr	ren_update
	move.w	ren_buf,d0
	move.w	d0,d1
	lsl.w	#2,d1
	lea	dbuf_tab,a0
	move.l	(a0,d1.w),d2
	add.l	ren_voff,d2
	lea	pub_vid,a0
	move.l	d2,(a0,d1.w)
	move.w	d0,d1
	add.w	d1,d1
	lea	pub_fine,a0
	move.w	ren_fine,(a0,d1.w)
	addq.b	#1,d0
	move.b	d0,frame_ready
	addq.w	#1,pic_count
	rts

init_picture:
	lea	rbss_start,a0
	lea	rbss_end,a1
.cl:	clr.l	(a0)+
	cmp.l	a1,a0
	blo.s	.cl
	lea	tcache,a0
	move.l	#TC_SLOTS*TC_SIZE/4,d0
.tc:	clr.l	(a0)+
	subq.l	#1,d0
	bne.s	.tc
	lea	black_pal,a1
	lea	shown_pal,a2
	moveq	#15,d0
.pl:	clr.w	(a1)+
	clr.w	(a2)+
	dbf	d0,.pl
	clr.b	pal_on
	clr.w	shown_idx
	clr.b	frame_ready
	rts

; ------------------------------------------------------------------------------
; Keyboard / joystick (IKBD): the active low bytes IN0, IN1, IN2
; ------------------------------------------------------------------------------

acia_isr:
	movem.l	d0-d5/a0-a2,-(sp)
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
	or.b	d0,kb0
	move.b	2(a0),d0
	or.b	d0,kb1
	move.b	3(a0),d0
	or.b	d0,kb2
	bsr	compose_inputs
	bra	.again
.release:
	move.b	1(a0),d0
	not.b	d0
	and.b	d0,kb0
	move.b	2(a0),d0
	not.b	d0
	and.b	d0,kb1
	move.b	3(a0),d0
	not.b	d0
	and.b	d0,kb2
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
	move.b	joy1_state,d1		; joystick 1 (port 1) plays player 1, joystick 0 player 2
	lea	joy_p1,a1
	lea	jy_a,a2
	bsr	.joy
	move.b	joy0_state,d1
	lea	joy_p2,a1
	lea	jy_b,a2
	bsr	.joy
	bsr	compose_inputs
	bra	.again
; d1 = the stick's byte, a1 = the player's table (5 entries: bit, column, mask), a2 = the 3 column bytes to fill
.joy:	clr.b	(a2)
	clr.b	1(a2)
	clr.b	2(a2)
	moveq	#4,d3
.jl:	move.b	(a1)+,d0
	move.b	(a1)+,d4
	move.b	(a1)+,d5
	btst	d0,d1
	beq.s	.jn
	and.w	#3,d4
	or.b	d5,(a2,d4.w)
.jn:	dbf	d3,.jl
	rts
.done:	movem.l	(sp)+,d0-d5/a0-a2
	rte

compose_inputs:
	move.b	kb0,d0
	or.b	jy_a,d0
	or.b	jy_b,d0
	not.b	d0
	move.b	d0,kin0
	move.b	kb1,d0
	or.b	jy_a+1,d0
	or.b	jy_b+1,d0
	not.b	d0
	move.b	d0,kin1
	move.b	kb2,d0
	or.b	jy_a+2,d0
	or.b	jy_b+2,d0
	not.b	d0
	move.b	d0,kin2
	rts

; the sticks: bit of the IKBD byte (0 up, 1 down, 2 left, 3 right, 7 fire), the column (IN0, IN1, IN2), the mask
joy_p1:
	dc.b	0,1,$04,1,0,$04,2,2,$10,3,2,$20,7,2,$08
joy_p2:
	dc.b	0,1,$08,1,0,$08,2,2,$80,3,0,$10,7,2,$40

; scancode, IN0 bits, IN1 bits, IN2 bits (active high here)
key_table:
	dc.b	$4b,$00,$00,$10		; left
	dc.b	$4d,$00,$00,$20		; right
	dc.b	$48,$00,$04,$00		; up
	dc.b	$50,$04,$00,$00		; down
	dc.b	$2c,$00,$00,$08		; Z = button 1
	dc.b	$39,$00,$00,$08		; space = button 1
	dc.b	$1d,$00,$00,$08		; control = button 1
	dc.b	$2d,$02,$00,$00		; X = button 2
	dc.b	$38,$02,$00,$00		; alternate = button 2
	dc.b	$2e,$00,$01,$00		; C = button 3
	dc.b	$24,$00,$00,$80		; J = player 2 left
	dc.b	$26,$10,$00,$00		; L = player 2 right
	dc.b	$17,$00,$08,$00		; I = player 2 up
	dc.b	$25,$08,$00,$00		; K = player 2 down
	dc.b	$30,$00,$00,$40		; B = player 2 button 1
	dc.b	$31,$00,$02,$00		; N = player 2 button 2
	dc.b	$02,$40,$00,$00		; 1 = start 1
	dc.b	$03,$00,$40,$00		; 2 = start 2
	dc.b	$06,$20,$00,$00		; 5 = coin 1
	dc.b	$07,$00,$20,$00		; 6 = coin 2
	dc.b	$3b,$80,$00,$00		; F1 = service
	dc.b	$3c,$00,$10,$00		; F2 = service 1
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
	move.b	#' ',(a0)+
	moveq	#0,d1
	move.w	badpc,d1		; (the 6809 address of a bad pc)
	bsr	hex_word
	move.b	#' ',(a0)+
	move.l	badctx,d1
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

	ifd DEBUG
; COUNTERS.BIN (words): VBLs, pictures shown, arcade frames, the frames whose top border the VBL armed, the late border
; events (engine/rt/borders.s), pictures made
dbg_counters:
	lea	dbg_buf,a0
	move.w	frame_counter+2,(a0)+
	move.w	pic_shown,(a0)+
	move.w	isr_count,(a0)+
	move.w	bd_fallbacks,(a0)+
	move.w	bd_late_top,(a0)+
	move.w	bd_late_on,(a0)+
	move.w	bd_late_low,(a0)+
	move.w	bd_late_off,(a0)+
	move.l	bd_pieced,(a0)+
	move.w	pic_count,(a0)+
	lea	dbg_name2,a1
	lea	dbg_buf,a2
	moveq	#22,d0
	bsr.s	dbg_write
	move.w	shown_idx,d0		; SCREEN.BIN: the shown buffer from the picture's first line (224 lines of RB_LB bytes)
	lsl.w	#2,d0
	lea	pub_vid,a2
	move.l	(a2,d0.w),a2
	lea	dbg_name3,a1
	move.l	#224*RB_LB,d0
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
	dc.b	"SCREEN.BIN",0
	even
	endc

; ------------------------------------------------------------------------------
	borders_handlers
	jagpad_text
	jagpad_maps
	include	"core.s"
	include	"render.s"
	include	"mcu.s"

	section data,data
	even
snapshot:	incbin	"snap.bin"

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
	borders_vars
	jagpad_vars
	ikbd_vars
vbl_pending:	ds.b	1		; arcade frames that have come (the VBL adds, the main loop takes one)
vbl_phase:	ds.b	1
render_skips:	ds.b	1
frame_ready:	ds.b	1		; a published picture (its buffer + 1) waits for the VBL
pal_on:		ds.b	1
joy0_state:	ds.b	1
joy1_state:	ds.b	1
kb0:		ds.b	1		; the keyboard's bits (active high)
kb1:		ds.b	1
kb2:		ds.b	1
jy_a:		ds.b	3		; the sticks' bits
jy_b:		ds.b	3
kin0:		ds.b	1		; keyboard and sticks, active low
kin1:		ds.b	1
kin2:		ds.b	1
io_in0:		ds.b	1		; + the pads: what the MCU model reads
io_in1:		ds.b	1
io_in2:		ds.b	1
	even
shown_pal:	ds.w	16
black_pal:	ds.w	16
shown_idx:	ds.w	1
pub_vid:	ds.l	3
pub_fine:	ds.w	3
isr_count:	ds.w	1
pic_count:	ds.w	1
pic_shown:	ds.w	1
frame_counter:	ds.l	1
crash_vector:	ds.w	1
crash_sp:	ds.l	1
crash_regs:	ds.l	16
crash_text:	ds.b	512
	ifd DEBUG
dbg_buf:	ds.l	8
	endc
