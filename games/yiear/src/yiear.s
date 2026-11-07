; Yie Ar Kung-Fu (Konami, 1985) for the Atari STE: the main 6809 program translated (tools/gen.py -> build/yiear/
; code_main.s, engine/m6809x.py), the picture drawn by render.s.
;
; The schedule (machine.YieArPort): the foreground is a task loop; at its idle point ($807C with an empty queue: ya_idle,
; gen.py NATIVES) the runtime draws the picture when due and delivers, per arcade frame, the IRQ (while control bit 2 is
; 1), and after the tasks it queued the eight NMIs (bit 1: the sound driver's tick), each with $807C as its return
; address.  Their RTIs come back to $807C, whose label is ya_idle again: the queued tasks run, then the next delivery.
;
; Registers in translated code (engine/m6809x.py): d0 A, d1 B, d2 X, d3 Y, d4 U, a5 = S as a pointer (ya_mem + S),
; a6 = main_ctx, a3 = a4 = ya_mem (the VB of slots 2 and 0: every slot's VB is ya_mem), a2 = ya_mem + $E000 (PB[7]);
; d5 d6 d7 a0 a1 scratch.  The 6809's N Z V C are the CCR's; E F H I the context byte SCCHI.

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

; Border removal and the palette: engine/rt/borders.s (the picture's 224 lines, black above and below).
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


; the pads (engine/rt/jagpad.s): SYSTEM (byte 0), P1 = IN1 (byte 1) and P2 = IN2 (byte 2) of the key_table's longs
; (active high there).  IN1: left 0, right 1, up 2, down 3, kick (button 1) 4, punch (button 2) 5, button 3 6.
; Pad A plays player 1, pad B player 2 (the arcade reads IN2 only with dual controls or in a cocktail cabinet).
JP_SH = 16
JP1_LEFT = $01<<JP_SH
JP1_RIGHT = $02<<JP_SH
JP1_UP = $04<<JP_SH
JP1_DOWN = $08<<JP_SH
JP1_B1 = $10<<JP_SH
JP1_B2 = $20<<JP_SH
JP1_B3 = $40<<JP_SH
JP2_LEFT = $01<<8
JP2_RIGHT = $02<<8
JP2_UP = $04<<8
JP2_DOWN = $08<<8
JP2_B1 = $10<<8
JP2_B2 = $20<<8
JP2_B3 = $40<<8
JP_START1 = $08<<24
JP_START2 = $10<<24
JP_COIN1 = $01<<24
JP_COIN2 = $02<<24
	include	"jagpad.s"
	include	"ikbd.s"

; the context block (engine/m6809x.py)
SPB = 0				; 8 longs: the 68000 address of the page in each slot
SVB = 32			; 8 longs: PB - slot * $2000 (ya_mem for all)
STBL = 64			; 8 longs: the dispatcher's table of the page in each slot
SCCHI = 112			; the CC byte's E F H I bits (6809 positions)
SCTXSIZE = 160

IDLE_PC = $807C			; (machine.YieArPort.IDLE)
DP = $51
QPTR = $51DA			; the task queue's read pointer
NMIS = 8			; NMIs an arcade frame

	include	"main_info.s"
	include	"start_info.s"

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

	bsr	init_main
	lea	main_ctx,a6
	lea	ya_mem,a3
	lea	ya_mem,a4
	lea	ya_mem+$E000,a2
	move.b	#$FF,io_dsw1		; DSW1: 1 coin 1 credit
	move.b	#$5B,io_dsw2		; DSW2: 1 life, upright, bonus 30000 80000, normal, demo sounds on
	move.b	#$FF,io_dsw3		; DSW3: no flip, single controls, no service
	ifd DSW2
	move.b	#DSW2,io_dsw2
	move.b	#DSW3,io_dsw3
	endc
	move.b	#$FF,io_sys
	move.b	#$FF,io_in1
	move.b	#$FF,io_in2
	move.b	#$FF,in_sys
	move.b	#$FF,in_in1
	move.b	#$FF,in_in2
	; the registers the self-test leaves at the entry (tools/gen.py start_regs -> start_info.s)
	lea	ya_mem+START_S,a5
	moveq	#0,d0
	move.b	#START_A,d0
	moveq	#0,d1
	move.b	#START_B,d1
	move.w	#START_X,d2
	and.l	#$FFFF,d2
	move.w	#START_Y,d3
	and.l	#$FFFF,d3
	move.w	#START_U,d4
	and.l	#$FFFF,d4
	moveq	#0,d5
	moveq	#0,d6
	moveq	#0,d7
	sub.l	a0,a0
	sub.l	a1,a1
	move.b	#START_CCHI,main_ctx+SCCHI
	move	#$2300,sr
	move	#START_CCR,ccr
	jmp	MAIN_RESET

; init_main: the context (the slots' pages, the dispatcher's tables), I and F set (a reset)
init_main:
	lea	main_ctx,a6
	lea	main_page_tables,a1
	moveq	#0,d0
.s:	move.w	d0,d1
	add.w	d1,d1
	add.w	d1,d1			; slot * 4
	move.l	d0,d2
	mulu	#$2000,d2
	lea	ya_mem,a0
	move.l	a0,SVB(a6,d1.w)
	add.l	d2,a0
	move.l	a0,SPB(a6,d1.w)
	move.l	(a1,d1.w),STBL(a6,d1.w)
	addq.w	#1,d0
	cmp.w	#8,d0
	bne.s	.s
	move.b	#$50,SCCHI(a6)
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
; program reads, the arcade's frames counted: 60 Hz against the STE's 50, six to five VBLs.

vbl:
	ifnd SIM
	borders_vbl
	endc
	movem.l	d0-d1/a0,-(sp)
	addq.l	#1,frame_counter
	ifd DEBUG
	move.w	dbg_pc_n,d0		; the interrupted PCs of the last 256 VBLs (PCS.BIN: where the program spends them)
	and.w	#255,d0
	lsl.w	#2,d0
	lea	dbg_pcs,a0
	add.w	d0,a0
	move.l	14(sp),d0
	sub.l	#start,d0		; (relative to the program's start: the map's addresses)
	move.l	d0,(a0)
	addq.w	#1,dbg_pc_n
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
	jp_merge	in_sys,io_sys,0
	jp_merge	in_in1,io_in1,1
	jp_merge	in_in2,io_in2,2
	endc
	ifd AUTOPLAY				; (benchmark build: coin, start, then moves and kicks; period 4000 arcade frames)
	move.l	d2,-(sp)			; (d2 is the 6809's X: kept)
	moveq	#0,d0
	move.w	isr_count,d0
	divu	#4000,d0
	swap	d0
	cmp.w	#300,d0
	blo.s	.ap1
	cmp.w	#304,d0
	bhs.s	.ap1
	move.b	#$FE,io_sys			; coin 1
.ap1:	cmp.w	#360,d0
	blo.s	.ap2
	cmp.w	#364,d0
	bhs.s	.ap2
	move.b	#$F7,io_sys			; start 1
.ap2:	cmp.w	#420,d0
	blo.s	.ap3
	move.w	d0,d2
	lsr.w	#4,d2
	and.w	#7,d2
	move.b	.ap_tab(pc,d2.w),io_in1
	bra.s	.ap3
.ap_tab:
	dc.b	$FD,$ED,$DD,$FE,$FB,$E7,$EF,$DF	; right, right+kick, right+punch, left, up, down+kick, kick, punch
.ap3:	move.l	(sp)+,d2
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

; ------------------------------------------------------------------------------
; The idle point (gen.py NATIVES: $807C LDX <$DA; LDD ,X; ASLA; BCS $807C): while the queue's entry at [$51DA] has no
; bit 7, the translation runs on (MAIN_IDLE_T).  Else, with the queue empty: the NMIs of the frame that was delivered
; (nmi_left, one a visit), then the picture when due, the next arcade frame awaited, the VLM's BSY counted down, and
; the IRQ delivered (control bit 2, CC's I clear).  An interrupt pushes the entire state (E set, PC $807C), sets I (and
; F for the NMI) and jumps to its handler; its RTI comes back here.  Without the IRQ the frame passes and the loop
; goes round once (and back here).
; ------------------------------------------------------------------------------

ya_idle:
	move	sr,d5			; the 6809's N Z V C
	moveq	#0,d7
	move.b	ya_mem+QPTR,d7
	lsl.w	#8,d7
	move.b	ya_mem+QPTR+1,d7
	tst.b	(a4,d7.l)
	bmi.s	.wait
	move	d5,ccr
	jmp	MAIN_IDLE_T
.wait:	move.w	d5,idle_sr
	tst.b	nmi_left
	beq.s	.frame
	subq.b	#1,nmi_left
	btst	#1,ya_ctl		; NMI enable
	bne	.nmi
	clr.b	nmi_left
.frame:	movem.l	d0-d4/a2-a6,-(sp)
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
	subq.b	#1,vbl_pending
	st	frame_dirty
	addq.w	#1,isr_count
	tst.b	vlm_left		; the VLM's BSY: counted down at each frame's start
	beq.s	.nv
	subq.b	#1,vlm_left
	bne.s	.nv
	clr.b	vlm_busy
.nv:	movem.l	(sp)+,d0-d4/a2-a6
	move.b	#NMIS,nmi_left
	btst	#2,ya_ctl		; the IRQ enable
	beq.s	.none
	btst	#4,SCCHI(a6)		; (I: clear here)
	beq.s	.irq
.none:	move.w	idle_sr,d5
	move	d5,ccr
	jmp	MAIN_IDLE_T
.irq:	bsr	push_state
	or.b	#$90,SCCHI(a6)		; E I
	move.w	idle_sr,d5
	move	d5,ccr
	jmp	MAIN_IRQ
.nmi:	bsr	push_state
	or.b	#$D0,SCCHI(a6)		; E F I
	move.w	idle_sr,d5
	move	d5,ccr
	jmp	MAIN_NMI

; push_state: the 6809's interrupt frame (E set, PC IDLE_PC) on its stack (a5); CC's E F H I from SCCHI, N Z V C from
; idle_sr.  d6 d7 used.
push_state:
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
	move.b	#DP,-(a5)		; DP
	move.b	d1,-(a5)		; B
	move.b	d0,-(a5)		; A
	move.b	SCCHI(a6),d7		; CC
	and.b	#$F0,d7
	move.b	idle_sr+1,d6
	and.b	#$0F,d6
	or.b	d6,d7
	or.b	#$80,d7
	move.b	d7,-(a5)
	rts

	ifd PLAYBACK
; The recorded play (build/yiear/play_inputs.bin; engine/playbot.py: runs of count, SYSTEM, IN0, a count of 0 at the
; end): the inputs of the arcade frame about to run.
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
	move.b	(a0)+,pb_in1
	move.l	a0,pb_ptr
.same:	subq.b	#1,pb_left
	move.b	pb_sys,io_sys
	move.b	pb_in1,io_in1
	move.b	#$FF,io_in2
	rts
	endc

; ---- the dispatcher: d7.w = a 6809 pc, through the table of the page in its slot; the CCR kept ----
main_dispatch:
	move.w	sr,d5
	move.w	d7,d6
	rol.w	#3,d6
	and.w	#7,d6
	add.w	d6,d6
	add.w	d6,d6
	move.l	STBL(a6,d6.w),a0
	and.w	#$1FFF,d7
	add.w	d7,d7
	moveq	#0,d6
	move.w	(a0,d7.w),d6
	add.l	d6,d6
	move.l	-4(a0),a0		; (the page's base)
	move.w	d5,ccr
	jmp	(a0,d6.l)

; ---- I/O ($0000 and $4000-$4FFF; also any address such a site reaches: machine.YieAr rd / wr): d7.w = the address;
; main_io_r: the byte in d7 (long: the upper bits 0); main_io_w: d5.b = the value.  Every other register kept. ----
main_io_r:
	cmp.w	#$5000,d7
	bhs.s	.mem			; (RAM, video RAM, ROM: an I/O site may reach them; $6000-$7FFF reads 0)
	cmp.w	#$4C00,d7
	blo.s	.low
	cmp.w	#$4F00,d7
	bhs.s	.zero
	cmp.w	#$4C00,d7
	beq.s	.dsw2
	cmp.w	#$4D00,d7
	beq.s	.dsw3
	cmp.w	#$4E04,d7
	bhs.s	.zero
	cmp.w	#$4E00,d7
	blo.s	.zero
	and.w	#3,d7
	move.l	a0,-(sp)
	lea	io_sys,a0		; SYSTEM, IN1, IN2, DSW1
	move.b	(a0,d7.w),d7
	move.l	(sp)+,a0
	rts
.dsw2:	moveq	#0,d7
	move.b	io_dsw2,d7
	rts
.dsw3:	moveq	#0,d7
	move.b	io_dsw3,d7
	rts
.low:	tst.w	d7
	bne.s	.zero
	moveq	#0,d7			; $0000: the VLM5030's BSY.  A read with ST low while it is up ends the phrase there: the
	tst.b	vlm_busy		; game waits for BSY to fall ($C8C5, in an NMI) before the next phrase, and no time
	beq.s	.zero			; passes here between frames (machine.YieArPort.rd)
	tst.b	vlm_st
	bne.s	.busy
	clr.b	vlm_busy
	clr.b	vlm_left
	rts
.busy:	moveq	#1,d7
	rts
.zero:	moveq	#0,d7
	rts
.mem:	cmp.w	#$6000,d7
	blo.s	.rd
	cmp.w	#$8000,d7
	blo.s	.zero
.rd:	move.l	a0,-(sp)
	lea	ya_mem,a0
	and.l	#$FFFF,d7
	move.b	(a0,d7.l),d7
	move.l	(sp)+,a0
	rts

main_io_w:
	cmp.w	#$5000,d7
	bhs.s	.ram
	cmp.w	#$4000,d7
	bne.s	.n0
	move.b	d5,ya_ctl		; the control latch: bit 1 NMI enable, bit 2 IRQ enable (flip and coin counters ignored)
	rts
.n0:	cmp.w	#$4800,d7
	bne.s	.n1
	move.b	d5,sn_latch
	rts
.n1:	cmp.w	#$4900,d7
	bne.s	.n2
	move.b	sn_latch,d5		; the SN76489A's data into the sound ring: (kind 0, value)
	moveq	#0,d7
	bra.s	.log
.n2:	cmp.w	#$4A00,d7
	bne.s	.n3
	bsr	vlm_control
	moveq	#1,d7
	bra.s	.log
.n3:	cmp.w	#$4B00,d7
	bne.s	.out
	move.b	d5,vlm_data
	moveq	#2,d7
.log:	move.l	a0,-(sp)		; the sound ring: words kind << 8 | value
	lea	snd_ring,a0
	move.l	d6,-(sp)
	moveq	#0,d6
	move.b	snd_head,d6
	add.w	d6,d6
	lsl.w	#8,d7
	move.b	d5,d7
	move.w	d7,(a0,d6.w)
	addq.b	#1,snd_head
	move.l	(sp)+,d6
	move.l	(sp)+,a0
.out:	rts
.ram:	cmp.w	#$6000,d7
	bhs.s	.out			; (the ROM, $6000-$7FFF unmapped)
	move.l	a0,-(sp)
	lea	ya_mem,a0
	move.b	d5,(a0,d7.w)		; ($5000-$5FFF: a positive word)
	move.l	(sp)+,a0
	rts

; vlm_control: the byte d5 written to $4A00.  BSY rises with ST (bit 1) and, ST falling, stays up the phrase's length in
; frames (ya_vlmf: tools/vlm_frames.py, by the latched data) counted from the frame it started in.  d6 d7 kept.
vlm_control:
	movem.l	d0/a0,-(sp)
	moveq	#2,d0
	and.b	d5,d0
	beq.s	.low
	tst.b	vlm_st
	bne.s	.same
	st	vlm_busy
	clr.b	vlm_left
	bra.s	.same
.low:	tst.b	vlm_st
	beq.s	.same
	moveq	#0,d0
	move.b	vlm_data,d0
	lea	ya_vlmf,a0
	move.b	(a0,d0.w),vlm_left
.same:	moveq	#2,d0
	and.b	d5,d0
	move.b	d0,vlm_st
	movem.l	(sp)+,d0/a0
	rts

main_bad_table:				; (the dispatcher's table for a slot without code: none)
main_badpc:
main_unsupported:
z80_badpc:				; (engine/rt/rtlib.s's name)
	move	#$2700,sr
	move.w	d7,badpc
	ifd SIM
.l:	bra.s	.l
	endc
	moveq	#99,d0			; the dump: d7 = the address
	bra	crash_common

	include	"m6809rt.s"

	borders_handlers
	jagpad_text
	jagpad_maps
	borders_blit_go

; ------------------------------------------------------------------------------
; Keyboard / joystick (IKBD): SYSTEM, IN1 and IN2 are active low bytes
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
	or.b	d0,in1_kbd
	bsr	compose_inputs
	bra	.again
.release:
	move.b	1(a0),d0
	not.b	d0
	and.b	d0,sys_kbd
	move.b	2(a0),d0
	not.b	d0
	and.b	d0,in1_kbd
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
	; joystick 1 (port 1) plays player 1, joystick 0 player 2: the stick as IN1 / IN2's bits 0-3, fire = kick
	move.b	joy1_state,d1
	bsr	.joy
	move.b	d0,in1_joy
	move.b	joy0_state,d1
	bsr	.joy
	move.b	d0,in2_joy
	bsr	compose_inputs
	bra	.again
.joy:	moveq	#0,d0
	btst	#2,d1			; left
	beq.s	.j1
	bset	#0,d0
.j1:	btst	#3,d1			; right
	beq.s	.j2
	bset	#1,d0
.j2:	btst	#0,d1			; up
	beq.s	.j3
	bset	#2,d0
.j3:	btst	#1,d1			; down
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
	move.b	in1_kbd,d0
	or.b	in1_joy,d0
	not.b	d0
	move.b	d0,in_in1
	move.b	in2_joy,d0
	not.b	d0
	move.b	d0,in_in2
	rts

; scancode, SYSTEM bits (coin 1 = 0, coin 2 = 1, start 1 = 3, start 2 = 4), IN1 bits (left 0, right 1, up 2, down 3,
; kick 4, punch 5, button 3 6), (unused)
key_table:
	dc.b	$4b,$00,$01,$00		; left
	dc.b	$4d,$00,$02,$00		; right
	dc.b	$48,$00,$04,$00		; up
	dc.b	$50,$00,$08,$00		; down
	dc.b	$2c,$00,$10,$00		; Z = kick
	dc.b	$39,$00,$10,$00		; space = kick
	dc.b	$1d,$00,$10,$00		; control = kick
	dc.b	$2d,$00,$20,$00		; X = punch
	dc.b	$38,$00,$20,$00		; alternate = punch
	dc.b	$2e,$00,$40,$00		; C = button 3
	dc.b	$02,$08,$00,$00		; 1 = start 1
	dc.b	$03,$10,$00,$00		; 2 = start 2
	dc.b	$06,$01,$00,$00		; 5 = coin 1
	dc.b	$07,$02,$00,$00		; 6 = coin 2
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
	lea	dbg_name4,a1
	lea	dbg_pcs,a2
	move.l	#1024,d0
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
dbg_name4:
	dc.b	"PCS.BIN",0
	even
	endc

	include	"render.s"

; ------------------------------------------------------------------------------
; The translated program (and its dispatch tables in the data section)
	include	"code_main.s"
	include	"tables_main.s"
	include	"vlm_tab.s"

	section text,code
	include	"rtlib.s"

	section data,data
	ifd PLAYBACK
pb_data:	incbin	"play_inputs.bin"
	even
	endc

; The 6809's 64 KB (machine.YieArPort after its boot self-test): the RAM, the video RAM and the ROM at $8000-$FFFF.
	cnop	0,4
ya_mem:	incbin	"yiear.img"

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
	even
main_ctx:	ds.b	SCTXSIZE
idle_sr:	ds.w	1
badpc:		ds.w	1
quit_flag:	ds.b	1
	borders_vars
	jagpad_vars
vbl_pending:	ds.b	1		; arcade frames that have come (the VBL adds, the idle point takes one)
vbl_phase:	ds.b	1
render_skips:	ds.b	1
frame_dirty:	ds.b	1		; an arcade frame ran since the last picture
snd_head:	ds.b	1
sn_latch:	ds.b	1		; the SN76489A's latch ($4800)
ya_ctl:		ds.b	1		; the control latch ($4000): bit 1 NMI enable, bit 2 IRQ enable
nmi_left:	ds.b	1		; NMIs still to deliver this frame
vlm_busy:	ds.b	1		; the VLM5030's BSY ($0000)
vlm_left:	ds.b	1		; frames until it falls
vlm_st:		ds.b	1		; ST (bit 1 of the last $4A00 write)
vlm_data:	ds.b	1		; the VLM's data latch ($4B00)
io_sys:		ds.b	1		; what the program reads: SYSTEM, IN1, IN2, DSW1 ($4E00-$4E03), DSW2 ($4C00), DSW3 ($4D00)
io_in1:		ds.b	1
io_in2:		ds.b	1
io_dsw1:	ds.b	1
io_dsw2:	ds.b	1
io_dsw3:	ds.b	1
	even
snd_ring:	ds.w	256		; the sound writes (the last 256): kind << 8 | value (0 SN76489A, 1 VLM control, 2 VLM data)
	ikbd_vars
joy0_state:	ds.b	1
joy1_state:	ds.b	1
sys_kbd:	ds.b	1
in1_kbd:	ds.b	1
in1_joy:	ds.b	1
in2_joy:	ds.b	1
in_sys:		ds.b	1
in_in1:		ds.b	1
in_in2:		ds.b	1
	even
isr_count:	ds.w	1
pic_count:	ds.w	1
	ifd PLAYBACK
pb_ptr:		ds.l	1
pb_left:	ds.b	1
pb_sys:		ds.b	1
pb_in1:		ds.b	1
pb_in2:		ds.b	1
	even
	endc
	ifd DEBUG
dbg_tl_n:	ds.w	1
dbg_tl_p:	ds.l	1
dbg_tl:		ds.l	400		; (40000 VBLs)
dbg_tl_end:
dbg_buf:	ds.l	16
dbg_pc_n:	ds.w	1
dbg_pcs:	ds.l	256
	endc
crash_vector:	ds.w	1
crash_sp:	ds.l	1
crash_regs:	ds.l	16
crash_text:	ds.b	512
frame_counter:	ds.l	1
	ds.l	1024
own_stack_top:
