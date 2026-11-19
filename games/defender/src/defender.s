; Defender (Williams, 1980) for the Atari STE: the main 6809 program translated (tools/gen.py -> build/defender/
; code_main.s, engine/m6809x.py); the picture is the 6809's own video RAM turned planar as it is written (vput).  No
; sound yet.  -D SIM: the simulator build (tools/logic_test.py).
;
; The picture: the arcade's bitmap ($0000-$97FF: byte = (x / 2) * 256 + y, the left pixel in the high nibble) shows x
; 12-303 and y 7-246 (292 x 240); here at x + 2 (centred in 320 pixels: 14 on the left, 14 on the right) on screen
; lines PIC_TOP .. PIC_TOP + 239 with both borders open (engine/rt/borders.s).  The bytes stay in df_mem (the program
; reads them); every store into the video RAM (the I/O sites that write there: main_io_w) and every PSHU into it
; (engine/m6809x.py video_push: main_vlist) also writes its two pixels into the screen (vput: movep.l of the four plane
; bytes).  One screen, drawn while it is shown (the arcade draws while the beam runs too).  The 16 pens: df_mem
; $C000-$C00F through ste_pal_tab into shown_pal every VBL (borders.s puts it on at the picture's first line).
;
; The power-on tests are skipped: the program starts at $D738 (MAIN_RESET), where they go when they pass.
;
; The schedule (machine.DefenderPort): the foreground waits at $E7C3 (LDA <$5D; BEQ $E7C3) for the IRQ's frame count.
; At that idle point (df_idle, gen.py NATIVES) with $A05D = 0 the runtime delivers the IRQ's two passes of an arcade
; frame, each with $E7C3 as the return address: the line-128 pass (the video counter reads $80, then $98), then the
; line-0 pass (it reads 0; it raises $A05D).  After the second RTI the foreground runs the frame and comes back.
;
; Registers in translated code (engine/m6809x.py): d0 A, d1 B, d2 X, d3 Y, d4 U, a5 = S as a pointer (df_mem + S),
; a6 = the context of the view selected (ctx_views + 256 * view: slot 6 holds that view's page 8 + view), a3 = df_mem +
; $A000 (DP $A0 and the stack), a4 = df_mem (every slot's VB is df_mem), a2 = df_mem + $E000 (PB[7]); d5 d6 d7 a0 a1
; scratch.  The video RAM is memory (df_mem $0000-$97FF), and so is the palette (df_mem $C000-$C00F: the IRQ writes it
; with PSHU, which the translation does as memory stores; main_io_w's palette stores land there too).  The accesses to $C000-$CFFF (the I/O in view 0, the bank's
; bytes in views 1-7) and the stores to $D000-$DFFF (the view select) go through main_io_r / main_io_w.

; the context block (engine/m6809x.py)
SPB = 0				; 8 longs: the 68000 address of the page in each slot
SVB = 32			; 8 longs: PB - slot * $2000 (df_mem for all)
STBL = 64			; 8 longs: the dispatcher's table of the page in each slot
SPID = 96			; 8 words: the virtual page in each slot
SCCHI = 112			; the CC byte's E F H I bits (6809 positions)
CTX_STRIDE = 256		; (ctx_views: a context per view)
NVIEWS = 16

IDLE_PC = $E7C3			; (machine.DefenderPort.IDLE)
FLAG = $A05D			; the IRQ's frame count
DP = $A0

	ifnd MAX_PENDING
MAX_PENDING = 3				; arcade frames that may be waiting (the game catches up after a slow frame)
	endc
	ifnd FRAMES
FRAMES = 0
	endc

KEY_ESC = $01
LB = 160				; bytes a screen line
PIC_W_LINES = 240
SCR_LINES = 290				; the lines a frame with both borders open reads, and some
	ifnd TA_DATA
TA_DATA = 98
	endc
	ifnd TA_NOPS
TA_NOPS = 84
	endc
PIC_TOP = 18				; the picture's first displayed line (240 of them, centred in the 276 the open borders show)
PIC_LINES = PIC_W_LINES
BD_PALETTE = 1
	include	"borders.s"

; the pads (engine/rt/jagpad.s): bytes 0-2 of each long are IN0, IN1, IN2 (key_table's columns), active high.
; IN0: fire 0, thrust 1, smart bomb 2, hyperspace 3, start 2 4, start 1 5, reverse 6, down 7; IN1: up 0;
; IN2: coin 1 4, coin 2 5.  Pad A: up / down, A fire, B thrust, C smart bomb, right thrust, left reverse.
JP1_UP = $01<<16
JP1_DOWN = $80<<24
JP1_LEFT = $40<<24
JP1_RIGHT = $02<<24
JP1_B1 = $01<<24
JP1_B2 = $02<<24
JP1_B3 = $04<<24
JP2_UP = $01<<16
JP2_DOWN = $80<<24
JP2_LEFT = $40<<24
JP2_RIGHT = $02<<24
JP2_B1 = $01<<24
JP2_B2 = $02<<24
JP2_B3 = $08<<24			; (pad B's C: hyperspace)
JP_START1 = $20<<24
JP_START2 = $10<<24
JP_COIN1 = $10<<8
JP_COIN2 = $20<<8
	include	"jagpad.s"
	include	"ikbd.s"

	include	"main_info.s"

	section text,code

start:
	clr.l	-(sp)			; (supervisor mode)
	move	#$20,-(sp)
	trap	#1
	addq	#6,sp
	move.l	d0,old_ssp
	lea	own_stack_top,sp
	bsr	init_hardware
	bsr	init_render
	bsr	init_main
	lea	ctx_views,a6
	lea	df_mem+$A000,a3		; (PB of slot 5: the direct page and the stack, engine/m6809x.py a3_pb)
	lea	df_mem,a4
	lea	df_mem+$E000,a2
	lea	df_mem,a5		; S = 0 (the program sets it)
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
	move	#$2300,sr
	move	#0,ccr
	jmp	MAIN_RESET

; init_main: a context per view (main_io_w's view select switches a6): the slots' pages, the dispatcher's tables, I and
; F set (a reset).  Slot 6 holds the view's page 8 + view; every VB is df_mem.
init_main:
	lea	view_pages,a0		; the window's pages: bank k (4 KB) and $D000-$DFFF for views 1-7, zeros and $D000-$DFFF
	lea	df_banks,a1		; for 8-15
	moveq	#7,d3
.vp:	move.w	#$1000/4-1,d0
	cmp.w	#0,d3
	bne.s	.vb
.vz:	clr.l	(a0)+
	dbf	d0,.vz
	bra.s	.vd
.vb:	move.l	(a1)+,(a0)+
	dbf	d0,.vb
.vd:	lea	df_mem+$D000,a2
	move.w	#$1000/4-1,d0
.vr:	move.l	(a2)+,(a0)+
	dbf	d0,.vr
	subq.w	#1,d3
	bpl.s	.vp
	lea	main_page_tables,a1
	moveq	#NVIEWS-1,d3		; the view
.b:	move.w	d3,d1
	lsl.w	#8,d1			; (CTX_STRIDE)
	lea	ctx_views,a6
	add.w	d1,a6
	moveq	#0,d0			; the slot
.s:	move.w	d0,d1
	add.w	d1,d1
	add.w	d1,d1			; slot * 4
	move.l	d0,d2
	mulu	#$2000,d2
	lea	df_mem,a0
	move.l	a0,SVB(a6,d1.w)
	add.l	d2,a0
	move.l	a0,SPB(a6,d1.w)
	move.l	(a1,d1.w),STBL(a6,d1.w)
	move.w	d0,d2
	add.w	d2,d2
	move.w	d0,SPID(a6,d2.w)
	addq.w	#1,d0
	cmp.w	#8,d0
	bne.s	.s
	move.w	d3,d0			; slot 6: the view's page 8 + view
	addq.w	#8,d0
	move.w	d0,SPID+12(a6)
	add.w	d0,d0
	add.w	d0,d0
	move.l	(a1,d0.w),STBL+24(a6)
	lea	df_mem+$C000,a0		; its memory: view 0 df_mem, 1-7 view_pages (bank, fixed ROM), 8-15 the zero page
	tst.w	d3
	beq.s	.p
	lea	view_pages+7*$2000,a0
	cmp.w	#7,d3
	bhi.s	.p
	move.w	d3,d0
	subq.w	#1,d0
	mulu	#$2000,d0
	lea	view_pages,a0
	add.l	d0,a0
.p:	move.l	a0,SPB+24(a6)
	sub.l	#$C000,a0
	move.l	a0,SVB+24(a6)
	move.b	#$50,SCCHI(a6)
	dbf	d3,.b
	clr.b	df_view
	rts

; ------------------------------------------------------------------------------
; The idle point (gen.py NATIVES: $E7C3 LDA <$5D; BEQ $E7C3): while $A05D is not 0 the translation runs on
; (MAIN_IDLE_T).  Else, after the line-128 pass (df_pass 1) the line-0 pass is delivered at once; otherwise the frame
; is over: the picture, the next arcade frame awaited, the line-128 pass delivered.  An IRQ: the entire state pushed
; (E set, PC $E7C3), I set, the video counter's answers queued, to $DF17 (the RAM vector's JMP).  No IRQ while I is set.
; ------------------------------------------------------------------------------

df_idle:
	tst.b	df_mem+FLAG
	beq.s	.idle
	jmp	MAIN_IDLE_T
.idle:	move	sr,d5			; the 6809's N Z V C
	move.w	d5,idle_sr
	tst.b	df_pass
	beq.s	.frame
	clr.b	df_pass
	lea	pass_top,a0
	bra	.irq
.frame:	movem.l	d0-d4/a2-a6,-(sp)
	ifd SIM
	bsr	sim_frame_done		; (the harness compares the frame just completed)
	endc
	addq.w	#1,pic_count
.check:	tst.b	vbl_pending
	bne.s	.deliver
	ifd SIM
	bsr	sim_wait
	endc
	bra.s	.check
.deliver:
	subq.b	#1,vbl_pending
	addq.w	#1,isr_count
	movem.l	(sp)+,d0-d4/a2-a6
	move.b	#1,df_pass
	lea	pass_low,a0
.irq:	btst	#4,SCCHI(a6)		; (I set: no IRQ)
	beq.s	.go
	clr.b	df_pass
	move.w	idle_sr,d5
	move	d5,ccr
	jmp	MAIN_IDLE_T
.go:	move.l	a0,vq_ptr		; the video counter's answers of this pass
	move.w	#IDLE_PC,d7
	move.b	d7,-(a5)		; PC
	lsr.w	#8,d7
	move.b	d7,-(a5)
	move.b	d4,-(a5)		; U
	move.w	d4,d7
	lsr.w	#8,d7
	move.b	d7,-(a5)
	move.b	d3,-(a5)		; Y
	move.w	d3,d7
	lsr.w	#8,d7
	move.b	d7,-(a5)
	move.b	d2,-(a5)		; X
	move.w	d2,d7
	lsr.w	#8,d7
	move.b	d7,-(a5)
	move.b	main_dpv,-(a5)		; DP (engine/m6809x.py dp_data)
	move.b	d1,-(a5)		; B
	move.b	d0,-(a5)		; A
	move.b	SCCHI(a6),d7		; CC: E F H I from SCCHI, N Z V C from the idle point's flags; E set
	and.b	#$F0,d7
	move.b	idle_sr+1,d6
	and.b	#$0F,d6
	or.b	d6,d7
	or.b	#$80,d7
	move.b	d7,-(a5)
	or.b	#$90,SCCHI(a6)		; E I
	move.w	idle_sr,d5
	move	d5,ccr
	jmp	MAIN_IRQ

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
	clr.b	$ffff820f.w
	clr.b	$ffff8265.w
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
	ifd SHOT
	move	#$2700,sr		; (-D SHOT=1: SCREEN.BIN, the palette, the picture's 240 lines, the counters: tools/hatari.ps1)
	move.l	screen,a0
	lea	PIC_TOP*LB(a0),a0
	lea	shot_buf+32,a1
	move.w	#PIC_W_LINES*LB/4-1,d0
.sc:	move.l	(a0)+,(a1)+
	dbf	d0,.sc
	lea	shown_pal,a0
	lea	shot_buf,a1
	moveq	#7,d0
.sp:	move.l	(a0)+,(a1)+
	dbf	d0,.sp
	lea	shot_buf+32+PIC_W_LINES*LB,a1	; then the VBLs (long) and the arcade frames (word) so far
	move.l	frame_counter,(a1)+
	move.w	isr_count,(a1)+
	bsr	restore_hardware
	clr	-(sp)			; Fcreate
	pea	shot_name
	move	#$3c,-(sp)
	trap	#1
	addq	#8,sp
	move	d0,d6
	pea	shot_buf		; Fwrite
	move.l	#32+PIC_W_LINES*LB+6,-(sp)
	move	d6,-(sp)
	move	#$40,-(sp)
	trap	#1
	lea	12(sp),sp
	move	d6,-(sp)		; Fclose
	move	#$3e,-(sp)
	trap	#1
	addq	#4,sp
	bra.s	.gone
	endc
	bsr	restore_hardware
.gone:
	move.l	old_ssp,-(sp)
	move	#$20,-(sp)
	trap	#1
	addq	#6,sp
	clr	-(sp)
	trap	#1

hbl:
	rte

; The VBL: the borders' events, the palette of the moment, the inputs, the arcade's frames counted (60.1 Hz against
; the STE's 50: six to five VBLs).  (SIM: the harness sets the inputs and vbl_pending.)
vbl:
	ifnd SIM
	borders_vbl
	endc
	movem.l	d0-d2/a0-a2,-(sp)
	addq.l	#1,frame_counter
	tst.b	quit_flag
	bne	quit
	lea	df_mem+$C000,a0		; the 16 pens: palette bytes -> STE colours (borders.s shows them from PIC_TOP)
	lea	ste_pal_tab,a1
	lea	shown_pal,a2
	moveq	#15,d1
.pal:	moveq	#0,d0
	move.b	(a0)+,d0
	add.w	d0,d0
	move.w	(a1,d0.w),(a2)+
	dbf	d1,.pal
	ifnd SIM
	bsr	jagpad_poll
	move.b	kbd_in0,d0		; the inputs the program reads (active high)
	or.b	joy_in0,d0
	or.b	jp_in+0,d0
	move.b	d0,io_in0
	move.b	kbd_in1,d0
	or.b	joy_in1,d0
	or.b	jp_in+1,d0
	move.b	d0,io_in1
	move.b	kbd_in2,d0
	or.b	jp_in+2,d0
	move.b	d0,io_in2
	addq.b	#1,vbl_pending		; one arcade frame a VBL, and a second one every 5th: 60 a second
	subq.b	#1,vbl_phase
	bpl.s	.ph
	move.b	#4,vbl_phase
	addq.b	#1,vbl_pending
.ph:	cmp.b	#MAX_PENDING,vbl_pending
	bls.s	.cap
	move.b	#MAX_PENDING,vbl_pending	; (a game that is behind by more than this runs slower)
.cap:
	endc
	if FRAMES
	move.l	frame_counter,d0
	cmp.l	#FRAMES,d0
	blt.s	.go_on
	st	quit_flag
.go_on:
	endc
	movem.l	(sp)+,d0-d2/a0-a2
	rte

; ------------------------------------------------------------------------------
; The picture
; ------------------------------------------------------------------------------

; init_render: the screen black and 256-byte aligned, the video base, vline (per y the screen address of its line, 0
; where y is not shown), the palettes black
init_render:
	move.l	#screen_mem+255,d0
	and.l	#$FFFFFF00,d0
	move.l	d0,screen
	move.l	d0,a0
	move.w	#SCR_LINES*LB/16-1,d1
.clr:	clr.l	(a0)+
	clr.l	(a0)+
	clr.l	(a0)+
	clr.l	(a0)+
	dbf	d1,.clr
	move.l	d0,-(sp)
	move.b	1(sp),$ffff8201.w
	move.b	2(sp),$ffff8203.w
	move.b	3(sp),$ffff820d.w
	addq.l	#4,sp
	add.l	#PIC_TOP*LB,d0
	lea	vline,a0
	moveq	#0,d1			; y
.vl:	cmp.w	#7,d1
	blo.s	.vz
	cmp.w	#7+PIC_W_LINES,d1
	bhs.s	.vz
	move.l	d0,(a0)+
	add.l	#LB,d0
	bra.s	.vn
.vz:	clr.l	(a0)+
.vn:	addq.w	#1,d1
	cmp.w	#256,d1
	bne.s	.vl
	lea	vtab,a0		; per video RAM address (col * 256 + y): vline[y] + the column's byte | position * 4 << 24
	lea	vcol,a1
	move.w	#152-1,d2
.vc:	move.l	(a1)+,d3		; offset << 16 | position * 1024, or -1
	lea	vline,a2
	move.w	#256-1,d1
.vy:	move.l	(a2)+,d0
	beq.s	.vh
	tst.l	d3
	bmi.s	.vh
	move.l	d3,d4
	swap	d4
	ext.l	d4
	add.l	d4,d0
	move.l	d3,d4
	lsr.w	#8,d4			; position * 4
	ror.l	#8,d4
	and.l	#$FF000000,d4
	or.l	d4,d0
	bra.s	.vs
.vh:	moveq	#0,d0
.vs:	move.l	d0,(a0)+
	dbf	d1,.vy
	dbf	d2,.vc
	lea	shown_pal,a0
	lea	black_pal,a1
	moveq	#15,d0
.p:	clr.w	(a0)+
	clr.w	(a1)+
	dbf	d0,.p
	rts

; df_vstore (gen.py io_w_alt: the sites that store only into the video RAM): d7.w = the address, d5.b = the byte; the
; byte into df_mem and its two pixels on the screen when it changes; another address goes on to main_io_w.  Keeps all
; but d7.
df_vstore:
	cmp.w	#$9800,d7
	bhs	main_io_w
	and.l	#$FFFF,d7
	cmp.b	(a4,d7.l),d5		; (a4 = df_mem in translated code)
	beq.s	.same			; (the byte is there already: so are its pixels; in play 930 stores a frame, 500 change)
	move.b	d5,(a4,d7.l)
	bra.s	vput
.same:	rts

; vput: d7.w = a video RAM address (< $9800), d5.b = its byte: the two pixels into the screen (where shown).  vtab:
; per address the screen byte | the pixel pair's position * 4 << 24 (0: not shown); vv_tab: per byte * 16 + position
; * 4 the two pixels' bits in the four plane bytes (movep.l order), vm_tab: per position * 4 the other pixels' bits.
; Keeps every register but d7.
vput:
	movem.l	d0/d6/a0,-(sp)
	moveq	#0,d6
	move.w	d7,d6
	add.l	d6,d6
	add.l	d6,d6
	lea	vtab,a0
	move.l	(a0,d6.l),d0
	beq.s	.out
	move.b	(a0,d6.l),d6		; (the entry's top byte: the position * 4)
	and.w	#$C,d6
	moveq	#0,d7
	move.b	d5,d7
	lsl.w	#4,d7
	or.w	d6,d7
	and.l	#$FFFFFF,d0
	move.l	d0,a0
	move.l	vm_tab(pc,d6.w),d6
	movep.l	0(a0),d0
	and.l	d6,d0
	or.l	vv_tab(pc,d7.w),d0
	movep.l	d0,0(a0)
.out:	movem.l	(sp)+,d0/d6/a0
	rts
vm_tab:	dc.l	$3F3F3F3F,$CFCFCFCF,$F3F3F3F3,$FCFCFCFC
vv_tab:	include	"df_vv.s"

; main_vlist (engine/m6809x.py video_push): a PSHU wrote bytes d7.w .. d7.w + d6.w (count - 1); the video RAM's of them
; into the screen.  Keeps every register but d6, d7.
main_vlist:
	movem.l	d0-d1/d5/a0,-(sp)
	moveq	#0,d0
	move.w	d7,d0
	move.w	d6,d1
	lea	df_mem,a0
.l:	cmp.w	#$9800,d0
	bhs.s	.n
	move.b	(a0,d0.l),d5		; (a long index: $8000 and above)
	move.w	d0,d7
	bsr	vput
.n:	addq.w	#1,d0
	dbf	d1,.l
	movem.l	(sp)+,d0-d1/d5/a0
	rts

; ---- the dispatcher: d7.w = a 6809 pc; $D000-$DFFF through page 6's table (the fixed ROM is always in slot 6's upper
; half), the rest through the table of the page in its slot; the CCR kept ----
main_dispatch:
	move.w	sr,d5
	ifd SIM
	move.w	d7,dispatch_pc		; (the harness's report of a bad pc)
	endc
	move.w	d7,d6
	and.w	#$F000,d6
	cmp.w	#$D000,d6
	bne.s	.slot
	move.l	main_page_tables+6*4,a0
	bra.s	.tbl
.slot:	move.w	d7,d6
	rol.w	#3,d6
	and.w	#7,d6
	add.w	d6,d6
	add.w	d6,d6
	move.l	STBL(a6,d6.w),a0
	cmp.l	#main_bad_table,a0	; (a slot without code: a pc the coverage never saw)
	beq	main_badpc
.tbl:	and.w	#$1FFF,d7
	add.w	d7,d7
	add.w	d7,d7
	move.l	(a0,d7.w),a0		; (gen.py dispatch_tables: a long a 6809 address)
	move.w	d5,ccr
	jmp	(a0)

; ---- I/O: d7.w = the address; main_io_r: the byte in d7 (long: the upper bits 0); main_io_w: d5.b = the value.  Every
; other register kept (main_io_w: but a6 when the view changes).  machine.Defender rd / wr: in view 0 $C000-$C3FF the
; palette and video control (write only), $C400-$C7FF the CMOS, $C800-$CBFF the video counter, $CC00-$CFFF the PIAs;
; in views 1-7 the bank's bytes, 8-15 nothing; $D000-$DFFF stores select the view. ----
main_io_r:
	cmp.w	#$C000,d7
	bhs.s	.io0
	and.l	#$FFFF,d7		; RAM and video RAM: a4 = df_mem in translated code
	move.b	(a4,d7.l),d7
	and.l	#$FF,d7
	rts
.io0:
	cmp.w	#$D000,d7
	bhs	.mem
	move.l	d6,-(sp)
	moveq	#0,d6
	move.b	df_view,d6
	beq.s	.io
	cmp.b	#7,d6
	bhi.s	.zero
	move.l	a0,-(sp)		; a bank: (view - 1) * $1000 + the offset
	subq.w	#1,d6
	lsl.w	#8,d6
	lsl.w	#4,d6
	and.w	#$FFF,d7
	add.w	d7,d6
	lea	df_banks,a0
	moveq	#0,d7
	move.b	(a0,d6.l),d7
	move.l	(sp)+,a0
	move.l	(sp)+,d6
	rts
.zero:	moveq	#0,d7
	move.l	(sp)+,d6
	rts
.io:	and.w	#$FFF,d7
	cmp.w	#$400,d7
	blo.s	.zero			; (the palette and video control: write only)
	cmp.w	#$800,d7
	blo.s	.cmos
	cmp.w	#$C00,d7
	blo.s	.vcnt
	and.w	#$1F,d7			; the PIAs: 0-3 PIA 1, 4-7 PIA 0
	cmp.w	#8,d7
	bhs.s	.zero
	move.l	a0,-(sp)
	lea	pia1,a0
	cmp.w	#4,d7
	blo.s	.pia
	lea	pia0,a0
	subq.w	#4,d7
.pia:	bsr	pia_read
	move.l	(sp)+,a0
	move.l	(sp)+,d6
	rts
.cmos:	and.w	#$FF,d7
	move.l	a0,-(sp)
	lea	df_cmos,a0
	move.b	(a0,d7.w),d7
	and.l	#$FF,d7
	move.l	(sp)+,a0
	move.l	(sp)+,d6
	rts
.vcnt:	move.l	a0,-(sp)		; the next answer of this pass (machine.DefenderPort.vpos)
	move.l	vq_ptr,a0
	moveq	#0,d7
	move.b	(a0)+,d7
	move.l	a0,vq_ptr
	move.l	(sp)+,a0
	move.l	(sp)+,d6
	rts
.mem:	move.l	a0,-(sp)
	lea	df_mem,a0
	and.l	#$FFFF,d7
	move.b	(a0,d7.l),d7
	and.l	#$FF,d7
	move.l	(sp)+,a0
	rts

; pia_read: a0 = the PIA's registers (PIA_*), d7.w = the register 0-3 -> d7.l the byte (machine.PIA.read; the IRQ flags
; are never set in the port's schedule).  pia_write: d5.b the value.
PIA_OUTA = 0
PIA_OUTB = 1
PIA_DDRA = 2
PIA_DDRB = 3
PIA_CTLA = 4
PIA_CTLB = 5
PIA_INA = 6			; (a pointer's byte: the input port's value is read through PIA_INA_P)
PIA_INA_P = 8			; the address of the port A input byte
PIA_INB_P = 12			; the address of the port B input byte (0: none, reads 0)
PIA_SND = 16			; 1: port B writes are sound commands (PIA 1)
PIA_SIZE = 18

pia_read:
	move.l	d6,-(sp)
	move.l	a1,-(sp)
	cmp.w	#1,d7
	beq.s	.ctla
	cmp.w	#3,d7
	beq.s	.ctlb
	cmp.w	#2,d7
	beq.s	.b
	btst	#2,PIA_CTLA(a0)		; port A: the DDR or (input & ~DDR) | (output & DDR)
	bne.s	.da
	moveq	#0,d7
	move.b	PIA_DDRA(a0),d7
	bra.s	.ret
.da:	move.l	PIA_INA_P(a0),a1
	move.b	(a1),d7
	move.b	PIA_DDRA(a0),d6
	not.b	d6
	and.b	d6,d7
	not.b	d6
	and.b	PIA_OUTA(a0),d6
	or.b	d6,d7
	and.l	#$FF,d7
	bra.s	.ret
.b:	btst	#2,PIA_CTLB(a0)
	bne.s	.db
	moveq	#0,d7
	move.b	PIA_DDRB(a0),d7
	bra.s	.ret
.db:	moveq	#0,d7
	move.b	PIA_OUTB(a0),d7
	cmp.b	#$FF,PIA_DDRB(a0)
	beq.s	.ret
	and.b	PIA_DDRB(a0),d7
	move.l	PIA_INB_P(a0),d6
	beq.s	.ret
	move.l	d6,a1
	move.b	PIA_DDRB(a0),d6
	not.b	d6
	and.b	(a1),d6
	or.b	d6,d7
	bra.s	.ret
.ctla:	moveq	#0,d7
	move.b	PIA_CTLA(a0),d7
	bra.s	.ret
.ctlb:	moveq	#0,d7
	move.b	PIA_CTLB(a0),d7
.ret:	move.l	(sp)+,a1
	move.l	(sp)+,d6
	rts

pia_write:
	cmp.w	#1,d7
	beq.s	.ctla
	cmp.w	#3,d7
	beq.s	.ctlb
	cmp.w	#2,d7
	beq.s	.b
	btst	#2,PIA_CTLA(a0)
	bne.s	.oa
	move.b	d5,PIA_DDRA(a0)
	rts
.oa:	move.b	d5,PIA_OUTA(a0)
	rts
.b:	btst	#2,PIA_CTLB(a0)
	bne.s	.ob
	move.b	d5,PIA_DDRB(a0)
	rts
.ob:	move.b	d5,PIA_OUTB(a0)
	tst.b	PIA_SND(a0)
	beq.s	.r
	move.l	d6,-(sp)		; the sound command (| $C0) into the ring
	move.l	a1,-(sp)
	lea	snd_ring,a1
	moveq	#0,d6
	move.b	snd_head,d6
	move.b	d5,(a1,d6.w)
	or.b	#$C0,(a1,d6.w)
	addq.b	#1,snd_head
	move.l	(sp)+,a1
	move.l	(sp)+,d6
.r:	rts
.ctla:	and.b	#$3F,d5
	move.b	d5,PIA_CTLA(a0)
	rts
.ctlb:	and.b	#$3F,d5
	move.b	d5,PIA_CTLB(a0)
	rts

main_io_w:
	cmp.w	#$C000,d7
	blo	.ram
	cmp.w	#$E000,d7
	bhs	.out			; (ROM)
	cmp.w	#$D000,d7
	bhs	.view
	tst.b	df_view
	bne	.out			; (a bank or nothing: ROM)
	and.w	#$FFF,d7
	cmp.w	#$400,d7
	blo.s	.pal
	cmp.w	#$800,d7
	blo.s	.cmos
	cmp.w	#$C00,d7
	blo	.out			; (the video counter)
	and.w	#$1F,d7
	cmp.w	#8,d7
	bhs	.out
	move.l	a0,-(sp)
	lea	pia1,a0
	cmp.w	#4,d7
	blo.s	.pia
	lea	pia0,a0
	subq.w	#4,d7
.pia:	bsr	pia_write
	move.l	(sp)+,a0
	rts
.pal:	cmp.w	#$3FF,d7
	beq	.out			; (the watchdog)
	and.w	#$1F,d7
	cmp.w	#$10,d7
	bhs.s	.vctl
	move.l	a0,-(sp)
	lea	df_mem+$C000,a0
	move.b	d5,(a0,d7.w)
	move.l	(sp)+,a0
	st	pal_dirty
	rts
.vctl:	move.b	d5,df_cocktail
	and.b	#1,df_cocktail
	rts
.cmos:	and.w	#$FF,d7
	move.l	a0,-(sp)
	lea	df_cmos,a0
	move.b	d5,(a0,d7.w)
	or.b	#$F0,(a0,d7.w)
	move.l	(sp)+,a0
	rts
.view:	moveq	#15,d7			; the view: a6 becomes its context (the CC's E F H I go on)
	and.b	d5,d7
	move.b	d7,df_view
	lsl.w	#8,d7			; (CTX_STRIDE)
	move.l	a0,-(sp)
	lea	ctx_views,a0
	add.w	d7,a0
	move.b	SCCHI(a6),SCCHI(a0)
	move.l	a0,a6
	move.l	(sp)+,a0
	rts
.ram:	move.l	a0,-(sp)
	lea	df_mem,a0
	and.l	#$FFFF,d7
	move.b	d5,(a0,d7.l)
	move.l	(sp)+,a0
	cmp.w	#$9800,d7
	blo	vput			; (the video RAM: the screen too)
.out:	rts

main_bad_table:				; (the dispatcher's table for a slot without code: none)
main_badpc:
main_unsupported:
z80_badpc:				; (engine/rt/rtlib.s's name)
	move	#$2700,sr
	move.w	d7,badpc
	ifd SIM
.l:	bra.s	.l
	endc
	moveq	#99,d0			; the dump: badpc = the 6809 address (dispatch_pc: the last dispatched one)
	bra	crash_common

	include	"m6809rt.s"

	borders_handlers
	jagpad_text
	jagpad_maps

; ------------------------------------------------------------------------------
; Keyboard / joystick (IKBD): kbd_in0-2 and joy_in0-1, active high, ORed into io_in0-2 by the VBL
; ------------------------------------------------------------------------------

acia_isr:
	movem.l	d0-d2/a0,-(sp)
.again:
	ikbd_byte
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
	or.b	d0,kbd_in0
	move.b	2(a0),d0
	or.b	d0,kbd_in1
	move.b	3(a0),d0
	or.b	d0,kbd_in2
	bra	.again
.release:
	move.b	1(a0),d0
	not.b	d0
	and.b	d0,kbd_in0
	move.b	2(a0),d0
	not.b	d0
	and.b	d0,kbd_in1
	move.b	3(a0),d0
	not.b	d0
	and.b	d0,kbd_in2
	bra	.again
.packet_byte:
	clr.b	ikbd_state
	moveq	#0,d0			; either joystick: up / down, left reverse, right thrust, fire
	moveq	#0,d2
	btst	#0,d1
	beq.s	.j1
	moveq	#1,d2			; (IN1: up)
.j1:	btst	#1,d1
	beq.s	.j2
	bset	#7,d0			; down
.j2:	btst	#2,d1
	beq.s	.j3
	bset	#6,d0			; reverse
.j3:	btst	#3,d1
	beq.s	.j4
	bset	#1,d0			; thrust
.j4:	tst.b	d1
	bpl.s	.j5
	bset	#0,d0			; fire
.j5:	move.b	d0,joy_in0
	move.b	d2,joy_in1
	bra	.again
.done:	movem.l	(sp)+,d0-d2/a0
	rte

; scancode, IN0 bits, IN1 bits, IN2 bits (active high): see the README's Controls
key_table:
	dc.b	$48,$00,$01,$00		; up
	dc.b	$50,$80,$00,$00		; down
	dc.b	$4b,$40,$00,$00		; left = reverse
	dc.b	$4d,$02,$00,$00		; right = thrust
	dc.b	$39,$01,$00,$00		; space = fire
	dc.b	$2c,$01,$00,$00		; Z = fire
	dc.b	$1d,$01,$00,$00		; control = fire
	dc.b	$2d,$02,$00,$00		; X = thrust
	dc.b	$2e,$40,$00,$00		; C = reverse
	dc.b	$30,$04,$00,$00		; B = smart bomb
	dc.b	$23,$08,$00,$00		; H = hyperspace
	dc.b	$02,$20,$00,$00		; 1 = start 1
	dc.b	$03,$10,$00,$00		; 2 = start 2
	dc.b	$06,$00,$00,$10		; 5 = coin 1
	dc.b	$07,$00,$00,$20		; 6 = coin 2
	dc.b	0,0,0,0
	even

; ------------------------------------------------------------------------------
; Crash dump (CRASH.TXT: vector, badpc, the last dispatch, the stack pointer, the load address; the registers; the
; stack top.  Vector 99: a 6809 pc without code)
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
	ifd SIM
crash_sim_stop:
	bra.s	crash_sim_stop
	endc
	lea	crash_text,a0
	moveq	#0,d1
	move.w	crash_vector,d1
	bsr	hex_word
	move.b	#32,(a0)+
	move.w	badpc,d1
	bsr	hex_word
	move.b	#32,(a0)+
	move.w	dispatch_pc,d1
	bsr	hex_word
	move.b	#32,(a0)+
	move.l	crash_sp,d1
	bsr	hex_long
	move.b	#32,(a0)+
	lea	start(pc),a1		; the load address: map address = address - this
	move.l	a1,d1
	bsr	hex_long
	move.b	#13,(a0)+
	move.b	#10,(a0)+
	lea	crash_regs,a1
	moveq	#14,d2
.regs:	move.l	(a1)+,d1
	bsr	hex_long
	move.b	#32,(a0)+
	dbf	d2,.regs
	move.b	#13,(a0)+
	move.b	#10,(a0)+
	move.l	crash_sp,a1
	moveq	#15,d2
.stack:	move	(a1)+,d1
	bsr	hex_word
	move.b	#32,(a0)+
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
shot_name:
	dc.b	"SCREEN.BIN",0
	even

	ifd SIM
sim_wait:				; the harness stops here (a loop), sets the inputs and vbl_pending, returns (rts)
	bra.s	sim_wait
sim_frame_done:				; the harness stops here and compares (an arcade frame completed), returns (rts)
	bra.s	sim_frame_done
	endc

	include	"code_main.s"
	include	"tables_main.s"

	section text,code
	include	"rtlib.s"
	include	"df_assets.s"

	section data,data
	even
pass_low:	dc.b	$80,$98,$FF,$FF	; the video counter's answers: the line-128 pass, the line-0 pass
pass_top:	dc.b	$00,$FF,$FF,$FF
pia0:		dc.b	0,0,0,0,0,0,0,0	; (PIA_*: IN0 / IN1)
		dc.l	io_in0,io_in1
		dc.b	0,0
pia1:		dc.b	0,0,0,0,0,0,0,0	; (IN2; port B the sound command)
		dc.l	io_in2,0
		dc.b	1,0
	even
df_mem:		incbin	"defender.img"
df_banks:	incbin	"banks.rom"
df_cmos:	incbin	"cmos.bin"

	section bss,bss
	even
old_ssp:	ds.l	1
old_screen:	ds.l	1
old_palette:	ds.l	8
old_hbl:	ds.l	1
old_vbl:	ds.l	1
old_acia:	ds.l	1
old_timer_b:	ds.l	1
old_timer_a:	ds.l	1
frame_counter:	ds.l	1
screen:		ds.l	1
crash_sp:	ds.l	1
crash_regs:	ds.l	16
crash_vector:	ds.w	1
pic_count:	ds.w	1
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
vbl_phase:	ds.b	1
kbd_in0:	ds.b	1
kbd_in1:	ds.b	1
kbd_in2:	ds.b	1
joy_in0:	ds.b	1
joy_in1:	ds.b	1
	even
	borders_vars
	ikbd_vars
	jagpad_vars
	even
shown_pal:	ds.w	16
black_pal:	ds.w	16
vline:		ds.l	256		; per y the screen address of its line, 0 where not shown (init_render)
vtab:		ds.l	152*256		; per video RAM address its screen byte | position * 4 << 24 (init_render)
crash_text:	ds.b	512
	even
screen_mem:	ds.b	SCR_LINES*LB+256
	ifd SHOT
shot_buf:	ds.b	32+PIC_W_LINES*LB+6
	endc
	even

ctx_views:	ds.b	NVIEWS*CTX_STRIDE
view_pages:	ds.b	8*$2000		; slot 6's pages of views 1-7 and of the empty views (init_main)
vq_ptr:		ds.l	1
idle_sr:	ds.w	1
badpc:		ds.w	1
dispatch_pc:	ds.w	1
isr_count:	ds.w	1
df_view:	ds.b	1
main_dpv:	ds.b	1		; DP as data (engine/m6809x.py dp_data; 0 at the reset)
df_pass:	ds.b	1		; 1: the line-128 pass was delivered, the line-0 pass is next
df_cocktail:	ds.b	1
vbl_pending:	ds.b	1
pal_dirty:	ds.b	1
snd_head:	ds.b	1
io_in0:		ds.b	1		; what the program reads: IN0, IN1 (PIA 0), IN2 (PIA 1); active high
io_in1:		ds.b	1
io_in2:		ds.b	1
	even
snd_ring:	ds.b	256		; the sound commands (the last 256)
	even
		ds.l	1024
own_stack_top:
