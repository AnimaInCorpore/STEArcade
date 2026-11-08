; Mikie (Konami, 1984) for the Atari STE: the main MC6809E program translated (tools/gen.py -> build/mikie/code_main.s,
; engine/m6809x.py), the picture drawn by render.s.
;
; The schedule (machine.MikiePort): the program starts at $6093 (its own initialisation; the boot self-tests are
; skipped).  The foreground is a task loop; at its idle point ($61C5, after the cursor routine $61C7, with an empty queue:
; mk_idle, gen.py NATIVES) and in a task's CWAI ($6FFF: mk_cwai) the runtime draws the picture when due, waits for the
; next arcade frame and delivers the IRQ (while latch Q7 is 1).  The IRQ handler's RTI comes back to the idle point /
; after the CWAI.
;
; Registers in translated code (engine/m6809x.py): d0 A, d1 B, d2 X, d3 Y, d4 U, a5 = S as a pointer (mk_mem + S),
; a6 = main_ctx, a3 = a4 = mk_mem (the VB of slots 1 and 0: every slot's VB is mk_mem), a2 = mk_mem + $E000 (PB[7]);
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

; Border removal and the palette: engine/rt/borders.s (the picture's 256 lines, black above and below).
	ifnd TA_DATA
TA_DATA = 98
	endc
	ifnd TA_NOPS
TA_NOPS = 84
	endc
PIC_TOP = 10				; the picture's first displayed line
PIC_LINES = 256
BD_PALETTE = 1
	include	"borders.s"

; the pads (engine/rt/jagpad.s): SYSTEM, P1, P2 bits as in key_table (bytes 0-2 of each long; active high there)
JP_SH1 = 16
JP_SH2 = 8
JP1_LEFT = $01<<JP_SH1
JP1_RIGHT = $02<<JP_SH1
JP1_UP = $04<<JP_SH1
JP1_DOWN = $08<<JP_SH1
JP1_B1 = $10<<JP_SH1			; (pad A, C: button 1, B: button 2)
JP1_B2 = $20<<JP_SH1
JP1_B3 = $10<<JP_SH1
JP2_LEFT = $01<<JP_SH2
JP2_RIGHT = $02<<JP_SH2
JP2_UP = $04<<JP_SH2
JP2_DOWN = $08<<JP_SH2
JP2_B1 = $10<<JP_SH2
JP2_B2 = $20<<JP_SH2
JP2_B3 = $10<<JP_SH2
JP_START1 = $08<<24
JP_START2 = $10<<24
JP_COIN1 = $01<<24
JP_COIN2 = $02<<24
	include	"jagpad.s"
	include	"ikbd.s"

; the context block (engine/m6809x.py)
SPB = 0				; 8 longs: the 68000 address of the page in each slot
SVB = 32			; 8 longs: PB - slot * $2000 (mk_mem for all)
STBL = 64			; 8 longs: the dispatcher's table of the page in each slot
SCCHI = 112			; the CC byte's E F H I bits (6809 positions)
SCTXSIZE = 160

IDLE_PC = $61C5			; (machine.MikiePort.IDLE)
CWAI_PC = $6FFF			; (machine.MikiePort.CWAI_PC)
DP = $29

	include	"main_info.s"

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
	move.b	#$FF,io_dsw1		; DSW1: 1 coin 1 credit, both slots
	move.b	#$7B,io_dsw2		; DSW2: 3 lives, upright, bonus 20k 70k 50k+, easy, demo sounds on
	ifd DSW2
	move.b	#DSW2,io_dsw2
	endc
	move.b	#$FF,io_sys		; SYSTEM, P1, P2: nothing pressed
	move.b	#$FF,io_p1
	move.b	#$FF,io_p2
	endc
	move.b	#$FE,io_dsw3		; DSW3: flip off, single controls
	move.b	#$FF,in_sys
	move.b	#$FF,in_p1
	move.b	#$FF,in_p2

	bsr	init_main
	lea	main_ctx,a6
	lea	mk_mem,a3
	lea	mk_mem,a4
	lea	mk_mem+$E000,a2
	lea	mk_mem,a5		; S = 0 (the program sets it)
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
	lea	mk_mem,a0
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
	jp_merge	in_p1,io_p1,1
	jp_merge	in_p2,io_p2,2
	endc
	ifd AUTOPLAY				; (benchmark build: coin, start, then walking and hitting; period 4000 frames)
	move.l	d2,-(sp)			; (d2 is the 6809's X: kept)
	moveq	#0,d0
	move.w	isr_count,d0
	divu	#4000,d0
	swap	d0
	cmp.w	#700,d0
	blo.s	.ap1
	cmp.w	#704,d0
	bhs.s	.ap1
	move.b	#$FE,io_sys			; coin 1
.ap1:	cmp.w	#760,d0
	blo.s	.ap2
	cmp.w	#764,d0
	bhs.s	.ap2
	move.b	#$F7,io_sys			; start 1
.ap2:	cmp.w	#840,d0
	blo.s	.ap3
	move.w	d0,d1
	lsr.w	#6,d1
	and.w	#3,d1
	moveq	#$FE-256,d2			; left, right, up, down in turn
	cmp.w	#1,d1
	bne.s	.ap4
	moveq	#$FD-256,d2
.ap4:	cmp.w	#2,d1
	bne.s	.ap5
	moveq	#$FB-256,d2
.ap5:	cmp.w	#3,d1
	bne.s	.ap6
	moveq	#$F7-256,d2
.ap6:	move.w	d0,d1
	and.w	#15,d1
	cmp.w	#4,d1
	bhs.s	.ap7
	and.b	#$EF,d2				; button 1 every 16th frame
.ap7:	move.b	d2,io_p1
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
; The idle points (gen.py NATIVES): mk_idle at $61C5 (BRA $61BC after the cursor routine; the queue's entry at [$2914]
; with bit 7 is empty: the translation runs on, MAIN_IDLE_T, while it has none); mk_cwai at the CWAI #$EF of $6FFF.
; Else the picture is drawn when due, the next arcade frame awaited and the IRQ delivered (latch Q7 1, CC's I clear):
; the entire state pushed (E set, PC the return point), I set, to $620A.  Its RTI comes back (to $61C5, or $7001 after
; the CWAI).  Without the IRQ the frame passes and the loop goes round once (back here).
; ------------------------------------------------------------------------------

; mk_sort: the native at $9933, the sprite list's bubble sort ($9933-$995E: records of 3 bytes at $2890, n = $2951 = $2952 of
; them, $2950 = n - 1; a pass swaps neighbours where the first byte is smaller (unsigned), n - 1 passes of n - 1, n - 2, .. 1
; compares), which is the stable sort by that byte, descending: done by insertion.  The counters it leaves: $2950 = $2951 = 0,
; $2952 = 2 (the last pass starts with 2).  n < 2 (the pass count wraps: 255 passes over what follows the list): the original code.
; The registers and flags it leaves are dead ($9962 loads Y, U and X first).
mk_sort:
	moveq	#0,d7
	move.b	$2951(a3),d7
	cmp.b	#2,d7
	blo.s	.orig
	subq.b	#1,d7			; n - 1 records to insert
	lea	$2890(a3),a0
	moveq	#3,d6			; the offset of the record to insert
.outer:	move.b	(a0,d6.w),d0
	move.b	1(a0,d6.w),d1
	move.b	2(a0,d6.w),d2
	move.w	d6,d3			; its place
.inner:	tst.w	d3
	beq.s	.place
	cmp.b	-3(a0,d3.w),d0		; (while the record before is smaller)
	bls.s	.place
	move.b	-3(a0,d3.w),(a0,d3.w)
	move.b	-2(a0,d3.w),1(a0,d3.w)
	move.b	-1(a0,d3.w),2(a0,d3.w)
	subq.w	#3,d3
	bra.s	.inner
.place:	move.b	d0,(a0,d3.w)
	move.b	d1,1(a0,d3.w)
	move.b	d2,2(a0,d3.w)
	addq.w	#3,d6
	subq.b	#1,d7
	bne.s	.outer
	clr.b	$2950(a3)
	clr.b	$2951(a3)
	move.b	#2,$2952(a3)
	jmp	M009962
.orig:	move.w	#$2890,d4
	jmp	M009936

; mk_sprcopy: the native at $6253, the sprite list's copy ($36D0 -> $2800: 38 words of 2 x 2 bytes, the second pair skipped
; (X + 2) where the first pair's second byte is $FC; then $FC into the second byte of each remaining 4 bytes up to $2888).
; State left as the 6809 code leaves it: A = $FC, B = the last byte read, X, U, $50 = 0; the flags of CMPU #$2888.
mk_sprcopy:
	lea	$36D0(a3),a0
	lea	$2800(a3),a1
	moveq	#$26-1,d6
.l:	move.w	(a0)+,d7		; (A:B; every pair is word aligned)
	cmp.b	#$FC,d7
	beq.s	.skip
	move.w	d7,(a1)+
	move.w	(a0)+,d7
	move.w	d7,(a1)+
	dbf	d6,.l
	bra.s	.e
.skip:	addq.l	#2,a0
	dbf	d6,.l
.e:	move.b	d7,d1			; B = the last byte read
	clr.b	$2950(a3)
	move.l	a0,d7
	sub.l	a3,d7
	move.w	d7,d2			; X
	move.b	#$FC,d0			; A = $FC
	lea	$2888(a3),a2
.f:	cmp.l	a2,a1
	bhs.s	.d
	move.b	d0,1(a1)
	addq.l	#4,a1
	bra.s	.f
.d:	move.l	a1,d7
	sub.l	a3,d7
	move.w	d7,d4			; U
	cmp.w	#$2888,d4		; (CMPU: the flags BCC read)
	jmp	M00627F

; mk_emit (inline call of $998B): X = d2 (the object + $10), U = d4: its 4-byte sprite record; a blank one ($FC) when the
; object's byte at -$10 is 0.  The flags are not live at the three call sites (mk_emit_nf only).
mk_emit_nf:
mk_emit:
	lea	(a3,d2.w),a0
	lea	(a3,d4.w),a1
	tst.b	$29FA(a3)
	beq.s	.p2
	move.b	-16(a0),d1
	beq.s	.blank
	move.b	-8(a0),d0
	move.b	-7(a0),d1
	eor.b	#$10,d1
	move.b	d1,(a1)+
	move.b	-12(a0),d1
	not.b	d1
	sub.b	#3,d1
	move.b	d1,(a1)+
	move.b	d0,(a1)+
	move.b	-10(a0),d1
	move.b	d1,(a1)+
	addq.w	#4,d4
	rts
.p2:	move.b	-16(a0),d1
	beq.s	.blank
	move.b	-8(a0),d0
	move.b	-7(a0),d1
	move.b	d1,(a1)+
	move.b	-12(a0),d1
	not.b	d1
	sub.b	#5,d1
	move.b	d1,(a1)+
	move.b	d0,(a1)+
	move.b	-10(a0),d1
	not.b	d1
	sub.b	#$0F,d1
	move.b	d1,(a1)+
	addq.w	#4,d4
	rts
.blank:	move.b	#$FC,d0
	move.b	d0,1(a1)
	addq.w	#4,d4
	rts

mk_idle:
	move	sr,d5			; the 6809's N Z V C
	moveq	#0,d7
	move.b	mk_mem+$2914,d7
	lsl.w	#8,d7
	move.b	mk_mem+$2915,d7
	tst.b	(a4,d7.l)
	bmi.s	.wait
	move	d5,ccr
	jmp	MAIN_IDLE_T
.wait:	move.w	#IDLE_PC,idle_pc
	st	idle_cwai
	clr.b	idle_cwai
	bra.s	mk_wait

mk_cwai:				; CWAI #$EF: I cleared, E set, the entire state pushed now; the IRQ is taken from here
	move	sr,d5
	move.w	d5,idle_sr
	move.w	#CWAI_PC+2,idle_pc
	clr.b	idle_cwai
	bsr	push_state
	and.b	#$EF,SCCHI(a6)
	or.b	#$80,SCCHI(a6)
	st	idle_cwai
mk_wait:
	move.w	d5,idle_sr
	movem.l	d0-d4/a2-a6,-(sp)
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
	movem.l	(sp)+,d0-d4/a2-a6
	tst.b	mk_latch+7		; the IRQ enable
	beq.s	.none
	tst.b	idle_cwai		; (a CWAI clears I: the interrupt comes whatever it was)
	bne.s	.irq
	btst	#4,SCCHI(a6)		; (I: always clear at the idle point)
	beq.s	.irq
.none:	tst.b	idle_cwai		; (a CWAI with no IRQ stays in it: another frame)
	bne.s	.again
	move.w	idle_sr,d5
	move	d5,ccr
	jmp	MAIN_IDLE_T
.again:	move.w	idle_sr,d5
	bra	mk_wait
.irq:	tst.b	idle_cwai
	bne.s	.go			; (the CWAI pushed the state already)
	bsr	push_state
.go:	or.b	#$90,SCCHI(a6)		; E I
	move.w	idle_sr,d5
	move	d5,ccr
	jmp	MAIN_IRQ

; push_state: the 6809's entire state for an interrupt (E set): PC idle_pc, U Y X DP B A, CC (E F H I from SCCHI, N Z V C
; from idle_sr; I cleared in the pushed copy for a CWAI)
push_state:
	moveq	#0,d7
	move.w	idle_pc,d7
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
	move.b	SCCHI(a6),d7		; CC: E F H I from SCCHI, N Z V C from the idle point's flags; E set
	and.b	#$F0,d7
	move.b	idle_sr+1,d6
	and.b	#$0F,d6
	or.b	d6,d7
	or.b	#$80,d7
	cmp.w	#CWAI_PC+2,idle_pc	; (a CWAI)
	bne.s	.pi
	and.b	#$EF,d7			; (the CWAI cleared I in the pushed state)
.pi:	move.b	d7,-(a5)
	rts

	ifd PLAYBACK
; The recorded play (build/mikie/play_inputs.bin; engine/playbot.py: runs of count, SYSTEM, IN0, a count of 0 at the
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
	move.b	(a0)+,pb_p1
	move.l	a0,pb_ptr
.same:	subq.b	#1,pb_left
	move.b	pb_sys,io_sys
	move.b	pb_p1,io_p1
	move.b	#$FF,io_p2
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

; ---- I/O ($2000-$25FF, the video RAM's writer sites, any address such a site reaches: machine.Mikie rd / wr): d7.w = the
; address; main_io_r: the byte in d7 (long: the upper bits 0); main_io_w: d5.b = the value.  Every other register kept. ----
main_io_r:
	cmp.w	#$2800,d7
	bhs.s	.mem			; (sprite RAM, RAM, video RAM, ROM: an I/O site may reach them; $4000-$5FFF reads 0)
	cmp.w	#$100,d7
	blo.s	.mem
	cmp.w	#$2500,d7
	beq.s	.d1
	cmp.w	#$2501,d7
	beq.s	.d2
	cmp.w	#$2400,d7
	blo.s	.zero
	cmp.w	#$2404,d7
	bhs.s	.zero
	and.w	#3,d7
	move.l	a0,-(sp)
	lea	io_sys,a0		; SYSTEM, P1, P2, DSW3
	move.b	(a0,d7.w),d7
	move.l	(sp)+,a0
	rts
.d1:	moveq	#0,d7
	move.b	io_dsw1,d7
	rts
.d2:	moveq	#0,d7
	move.b	io_dsw2,d7
	rts
.zero:	moveq	#0,d7
	rts
.mem:	cmp.w	#$4000,d7
	blo.s	.rd
	cmp.w	#$6000,d7
	blo.s	.zero
.rd:	move.l	a0,-(sp)
	lea	mk_mem,a0
	and.l	#$FFFF,d7
	move.b	(a0,d7.l),d7
	move.l	(sp)+,a0
	rts

; the video and colour RAM ($3800-$3FFF): the byte stored, the cell (address & $7FF) listed once for render.s (byte
; stores do this inline at their sites: tools/gen.py video_inline)
main_io_w:
	cmp.w	#$3800,d7
	bhs	.vid
	cmp.w	#$2800,d7
	bhs	.ram			; (sprite RAM, RAM: an I/O site may reach them)
	cmp.w	#$100,d7
	blo	.ram
	cmp.w	#$2000,d7
	blo.s	.out
	cmp.w	#$2008,d7
	blo.s	.latch
	cmp.w	#$2200,d7
	beq.s	.pal
	cmp.w	#$2400,d7
	beq.s	.snd
.out:	rts
.latch:	movem.l	d6/a0,-(sp)
	and.w	#7,d7			; the LS259: Q = address bits 0-2, the data's bit 0
	lea	mk_latch,a0
	move.b	d5,d6
	and.b	#1,d6
	cmp.w	#2,d7
	bne.s	.st
	tst.b	d6			; Q2's rising edge: the sound command into the ring
	beq.s	.st
	tst.b	2(a0)
	bne.s	.st
	lea	snd_ring,a0
	moveq	#0,d7
	move.b	snd_head,d7
	move.b	snd_latch,(a0,d7.w)
	addq.b	#1,snd_head
	lea	mk_latch,a0
	moveq	#2,d7
.st:	move.b	d6,(a0,d7.w)
	movem.l	(sp)+,d6/a0
	rts
.pal:	and.b	#7,d5			; the palette bank: the renderer sees it change
	move.b	d5,pal_bank
	rts
.snd:	move.b	d5,snd_latch
	rts
.ram:	move.l	a0,-(sp)
	lea	mk_mem,a0
	move.b	d5,(a0,d7.w)
	move.l	(sp)+,a0
	rts
.vid:	cmp.w	#$4000,d7
	bhs.s	.out2			; (the ROM, the unmapped $4000-$5FFF)
	move.l	a0,-(sp)
	lea	mk_mem,a0
	move.b	d5,(a0,d7.w)		; ($3800-$3FFF: a positive word)
	and.w	#$7FF,d7
	lea	cell_dirty,a0
	tst.b	(a0,d7.w)
	bne.s	.listed
	st	(a0,d7.w)
	move.l	cell_ptr,a0
	move.w	d7,(a0)+
	move.l	a0,cell_ptr
.listed:
	move.l	(sp)+,a0
.out2:	rts

main_bad_table:				; (the dispatcher's table for a slot without code: none)
main_dead:
	move.w	#$6E80,d7		; (gen.py DEAD: the LBRA into padding)
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
; Keyboard / joystick (IKBD): SYSTEM and IN0 are active low bytes
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
	; joystick 1 (port 1) plays player 1, joystick 0 player 2: left 0, right 1, up 2, down 3, fire 4
	move.b	joy1_state,d1
	bsr	.joy
	move.b	d0,p1_joy
	move.b	joy0_state,d1
	bsr	.joy
	move.b	d0,p2_joy
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
	bset	#4,d0		; (fire: button 1)
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

; scancode, SYSTEM bits (coin 1 = 0, coin 2 = 1, start 1 = 3, start 2 = 4), P1 bits (left 0, right 1, up 2, down 3,
; fire 4), P2 bits
key_table:
	dc.b	$4b,$00,$01,$00		; left
	dc.b	$4d,$00,$02,$00		; right
	dc.b	$48,$00,$04,$00		; up
	dc.b	$50,$00,$08,$00		; down
	dc.b	$39,$00,$10,$00		; space = button 1 (kick)
	dc.b	$1d,$00,$10,$00		; control = button 1
	dc.b	$2c,$00,$10,$00		; Z = button 1
	dc.b	$38,$00,$20,$00		; alternate = button 2
	dc.b	$2d,$00,$20,$00		; X = button 2
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
	ifnd NOSOUND
	include	"sound.s"
	endc

; ------------------------------------------------------------------------------
; The translated program (and its dispatch tables in the data section)
	include	"code_main.s"
	include	"tables_main.s"

	section text,code
	include	"rtlib.s"

	section data,data
	ifd PLAYBACK
pb_data:	incbin	"play_inputs.bin"
	even
	endc

; The 6809's 64 KB (machine.Mikie): the RAM, the NVRAM, the video RAM (zero) and the ROM at $6000-$FFFF.
	cnop	0,4
mk_mem:	incbin	"mikie.img"

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
snd_latch:	ds.b	1		; the sound latch ($2400)
mk_latch:	ds.b	8		; the LS259's Q0-Q7 ($2000-$2007: Q0 / Q1 coin counters, Q2 the sound trigger, Q6 flip, Q7 the IRQ enable)
pal_bank:	ds.b	1		; the palette bank latch ($2200)
io_sys:		ds.b	1		; what the program reads: SYSTEM, P1, P2, DSW3 ($2400-$2403), DSW1, DSW2 ($2500, $2501)
io_p1:		ds.b	1
io_p2:		ds.b	1
io_dsw3:	ds.b	1
io_dsw1:	ds.b	1
io_dsw2:	ds.b	1
idle_cwai:	ds.b	1		; the wait is a CWAI (the IRQ's return point $7001, I cleared in the pushed CC)
	even
idle_pc:	ds.w	1
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
