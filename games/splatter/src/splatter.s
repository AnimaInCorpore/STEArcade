; Splatterhouse (Namco System 1) for the Atari STE.
;
; The translated main and sub CPU programs and their runtime: core.s (tools/gen.py, engine/m6809x.py).  The port
; starts from the reference's state after the boot (tools/snapshot.py: build/splatter/snapshot.bin).
;
; SIM: the build the tests drive (tools/logic_test.py): the harness does the vertical blank's work, the MCU and the
; sound CPU in the reference and calls port_frame once a frame.
; Otherwise the program: the snapshot loaded, then in turn an arcade frame (the vertical blank's work: the sprite list
; latch, the MCU; the main CPU, the sub CPU) and a picture (render.s).  The VBL counts the arcade's 60 Hz ticks (six
; per five 50 Hz fields); frames the logic falls behind by more than MAX_BEHIND are dropped (the game slows down).
; The display: render.s' buffers, engine/rt/borders.s (top and bottom border open, the palettes per line: the HUD
; bars' own palette with BD_HUD; -D REN_ONEPAL=1: one).

KEY_ESC = $01
    ifnd SIM
PIC_TOP = 26				; the picture's first displayed line (Black Tiger's timing values)
TA_DATA = 98
TA_NOPS = 84
PIC_LINES = 224
BD_PALETTE = 1
      ifnd REN_ONEPAL
BD_HUD = 1
      endc
MAX_BEHIND = 3
TILE_FLAG = 1				; (render.s compares tile RAM only after the translated writers set tile_written)
      ifnd PIC_EVERY
PIC_EVERY = 2				; (arcade frames a picture at most: the logic's share against the picture rate)
      endc
	include	"ikbd.s"
	include	"borders.s"
shown_pal = ren_vbl_pal
hud_pal = ren_vbl_hpal
hud_top = ren_vbl_htop
hud_bot = ren_vbl_hbot
    endc

	section text,code
start:
	clr.l	-(sp)
	move	#$20,-(sp)
	trap	#1
	addq	#6,sp
	move.l	d0,old_ssp
	lea	own_stack_top,sp
	lea	bad_table,a0
	move.w	#$2000-1,d0
.bad:	move.l	#cpu_badpc,(a0)+
	dbf	d0,.bad
	bsr	init_page_bases
	bsr	init_contexts
    ifd SIM
sim_wait:
	bra.s	sim_wait
    else
	bsr	snapshot_load
	bsr	render_init
	bsr	init_hardware
main_loop:
	tst.b	quit_flag
	bne.s	.quit
	tst.b	ticks
	beq.s	main_loop
	cmp.b	#MAX_BEHIND,ticks	; (behind: drop frames)
	bls.s	.go
	move.b	#MAX_BEHIND,ticks
	addq.l	#1,cnt_dropped
.go:	subq.b	#1,ticks
	ifd	BENCH
	bsr	bench_inputs
	endc
	bsr	vblank_work
	bsr	port_frame
	addq.l	#1,cnt_logic
	addq.b	#1,since_pic		; a picture after every PIC_EVERY-th arcade frame, or when the logic caught up
	cmp.b	#PIC_EVERY,since_pic
	bhs.s	.pic
	tst.b	ticks
	bne	main_loop
.pic:	clr.b	since_pic
	move.w	ren_skipped,-(sp)
	bsr	render_frame
	move.w	(sp)+,d0
	cmp.w	ren_skipped,d0
	bne.s	main_loop
	addq.l	#1,cnt_pictures
	bra.s	main_loop
.quit:	bsr	restore_hardware
	bsr	write_counters
	move.l	old_ssp,-(sp)
	move	#$20,-(sp)
	trap	#1
	addq	#6,sp
	clr	-(sp)
	trap	#1

; the vertical blank: the sprite list latched when the program wrote $7F2 (namcos1_sprite copy_sprites), the MCU,
; the sound CPU's handshakes (no sound CPU here: it acknowledges a tune request, TRIRAM $105 = $40 -> $80, a frame
; later, and clears the sound RAM's $240 that the main CPU sets; the main CPU waits for both)
vblank_work:
	cmp.b	#$40,vio+$1F105
	bne.s	.snd
	move.b	#$80,vio+$1F105
.snd:	clr.b	vio+$1E240
	tst.b	sprite_latch
	beq.s	.mcu
	sf	sprite_latch
	lea	vio+$1C800,a0
	move.w	#128-1,d0
.copy:	move.l	4(a0),10(a0)
	move.w	8(a0),14(a0)
	lea	16(a0),a0
	dbf	d0,.copy
.mcu:	bra	mcu_call

; the MCU (src/mcu.s): TRIRAM and the arcade's input ports (CONTROL0, CONTROL1, COIN, DIPSW, active low)
mcu_call:
	lea	vio+$1F000,a0
	lea	in_control0,a1
	bra	mcu_frame

; ---- the snapshot (tools/snapshot.py) ----
snapshot_load:
	lea	snapshot,a0
	lea	vio,a1
	move.w	#$28000/4-1,d0
.vio:	move.l	(a0)+,(a1)+
	dbf	d0,.vio
	lea	ctx_main,a6
	bsr.s	load_ctx
	lea	ctx_sub,a6
	bsr.s	load_ctx
	lea	key_regs,a1
	moveq	#8-1,d0
.key:	move.b	(a0)+,(a1)+
	dbf	d0,.key
	move.l	(a0)+,rand_seed
	lea	mcu_state,a1
	move.w	#mcu_state_end-mcu_state-1,d0
.mcu:	move.b	(a0)+,(a1)+
	dbf	d0,.mcu
	rts

; a0 -> 8 page words, A B X Y U S CC (words); a6 = the context
load_ctx:
	moveq	#0,d6
	sub.l	a5,a5
.slot:	move.w	(a0)+,d7
	move.l	a0,-(sp)
	move.w	d6,-(sp)
	bsr	bank_set		; (PB, VB, TBL, PID)
	move.w	(sp)+,d6
	move.l	(sp)+,a0
	addq.w	#2,d6
	cmp.w	#16,d6
	bne.s	.slot
	moveq	#0,d0
	lea	R_D0(a6),a1
	moveq	#5-1,d1
.regs:	move.w	(a0)+,d0
	move.l	d0,(a1)+
	dbf	d1,.regs
	move.w	(a0)+,d0		; S
	add.l	PB(a6),d0
	move.l	d0,R_A5(a6)
	move.w	(a0)+,d0		; CC
	move.b	d0,CCHI(a6)
	and.w	#$0F,d0
	move.w	d0,R_SR(a6)
	rts

; untranslated code reached (core.s cpu_badpc: badpc = the offset in the slot * 4, badslot = the slot * 4, badctx = the
; CPU's context; badpc $FFFF: a STOP-like halt): CRASH.TXT "BADPC main|sub PAGE ppp PC xxxx", then back to the desktop
port_crash:
	move	#$2700,sr
	lea	own_stack_top,sp
	bsr	restore_hardware
	lea	crash_text,a0
	lea	crash_cpu,a1
	move.l	badctx,a6
	move.b	#"M",(a1)
	cmp.l	#ctx_main,a6
	beq.s	.m
	move.b	#"S",(a1)
.m:	move.w	badslot,d6
	lsr.w	#1,d6
	move.w	PID(a6,d6.w),d0		; the page
	lea	crash_page,a1
	moveq	#3-1,d2
	bsr.s	.hex
	move.w	badslot,d0		; the 6809 pc: slot * $2000 + offset
	moveq	#11,d1
	lsl.w	d1,d0
	move.w	badpc,d1
	lsr.w	#2,d1
	or.w	d1,d0
	lea	crash_pc,a1
	moveq	#4-1,d2
	bsr.s	.hex
	clr.w	-(sp)
	pea	.name(pc)
	move.w	#$3C,-(sp)		; Fcreate
	trap	#1
	addq.l	#8,sp
	tst.w	d0
	bmi.s	.out
	move.w	d0,-(sp)
	pea	crash_text
	pea	crash_end-crash_text
	move.w	d0,-(sp)
	move.w	#$40,-(sp)		; Fwrite
	trap	#1
	lea	12(sp),sp
	move.w	#$3E,-(sp)		; Fclose
	trap	#1
	addq.l	#4,sp
.out:	bsr	write_counters
	move.l	old_ssp,-(sp)
	move	#$20,-(sp)
	trap	#1
	addq	#6,sp
	clr	-(sp)
	trap	#1
; d0 -> d2 + 1 hex digits at a1
.hex:	add.w	d2,a1
	addq.w	#1,a1
.h:	moveq	#15,d1
	and.w	d0,d1
	move.b	.digits(pc,d1.w),-(a1)
	lsr.w	#4,d0
	dbf	d2,.h
	rts
.digits:	dc.b	"0123456789ABCDEF"
.name:	dc.b	"CRASH.TXT",0
	even

    ifd BENCH
; BENCH: inputs by the arcade frame (coin at 60, start at 140, then right with an attack every 40 frames), the counters
; kept at arcade frame BENCH_FROM and the program quit at BENCH_TO: the same play every run (no host key timing)
BENCH_FROM = 600
BENCH_TO = 1100
bench_inputs:
	move.l	cnt_logic,d0
	move.b	#$FF,in_coin
	move.b	#$FF,in_control0
	cmp.l	#60,d0
	blo.s	.r
	cmp.l	#66,d0
	bhs.s	.c
	move.b	#$EF,in_coin		; (coin 1)
	bra.s	.r
.c:	cmp.l	#140,d0
	blo.s	.r
	cmp.l	#146,d0
	bhs.s	.p
	move.b	#$7F,in_control0	; (start)
	bra.s	.r
.p:	cmp.l	#400,d0
	blo.s	.r
	divu	#40,d0
	swap	d0
	move.b	#$FE,in_control0	; right
	cmp.w	#4,d0
	bhs.s	.r
	move.b	#$EE,in_control0	; right + attack
.r:	move.l	cnt_logic,d0
	cmp.l	#BENCH_FROM,d0
	blo.s	.n
	tst.l	cnt_from
	bne.s	.n
	movem.l	cnt_vbls,d1-d5
	movem.l	d1-d5,cnt_from
.n:	cmp.l	#BENCH_TO,d0
	blo.s	.q
	st	quit_flag
.q:	rts
    endc

; COUNTERS.BIN (longs): VBLs, arcade frames run, pictures drawn, frames dropped, pictures skipped (no free buffer)
write_counters:
	moveq	#0,d0
	move.w	ren_skipped,d0
	move.l	d0,cnt_skipped
	clr.w	-(sp)
	pea	.name(pc)
	move.w	#$3C,-(sp)		; Fcreate
	trap	#1
	addq.l	#8,sp
	tst.w	d0
	bmi.s	.r
	move.w	d0,-(sp)
	pea	cnt_vbls
	pea	40.w				; (and cnt_from: BENCH)
	move.w	d0,-(sp)
	move.w	#$40,-(sp)		; Fwrite
	trap	#1
	lea	12(sp),sp
	move.w	#$3E,-(sp)		; Fclose (the handle is on the stack)
	trap	#1
	addq.l	#4,sp
.r:	rts
.name:	dc.b	"COUNTERS.BIN",0
	even

; ---- the hardware: the VBL (borders, the picture, the ticks), the timers (borders.s), the ACIA (keys, joystick) ----
init_hardware:
	move	#$2700,sr
	movem.l	$ffff8240.w,d0-d7
	movem.l	d0-d7,old_palette
	move.b	$ffff8260.w,old_res
	move.b	$ffff820a.w,old_hz
	move.b	$ffff820f.w,old_linewid
	move.b	$ffff8265.w,old_fine
	move.b	$ffff8201.w,old_screen+1
	move.b	$ffff8203.w,old_screen+2
	move.b	$ffff820d.w,old_screen+3
	lea	$fffffa07.w,a0
	lea	old_mfp,a1
	moveq	#$21-$07,d0		; (the MFP's registers $fffffa07-$fffffa21, odd bytes)
.mfp:	move.b	(a0),(a1)+
	addq.l	#2,a0
	subq.w	#2,d0
	bpl.s	.mfp
	move.l	$68.w,old_hbl
	move.l	$70.w,old_vbl
	move.l	$118.w,old_acia
	move.l	$120.w,old_timer_b
	move.l	$134.w,old_timer_a
	clr.b	$fffffa07.w
	clr.b	$fffffa09.w
	clr.b	$fffffa13.w
	clr.b	$fffffa15.w
	bclr	#3,$fffffa17.w		; (automatic end of interrupt)
	clr.b	$fffffa19.w
	clr.b	$fffffa1b.w
	moveq	#0,d0
	movem.l	d0,$ffff8240.w
	clr.b	$ffff8260.w		; (low resolution, 50 Hz)
	move.b	#2,$ffff820a.w
	move.l	#hbl,$68.w
	move.l	#vbl,$70.w
	move.l	#acia_isr,$118.w
	move.l	#timer_b,$120.w
	move.l	#timer_a,$134.w
	bset	#0,$fffffa07.w		; Timer B
	bset	#0,$fffffa13.w
	bset	#5,$fffffa07.w		; Timer A
	bset	#5,$fffffa13.w
	bset	#6,$fffffa09.w		; ACIA
	bset	#6,$fffffa15.w
	move.b	#$FF,in_control0
	move.b	#$FF,in_control1
	move.b	#$FF,in_coin
	move.b	#$FF,in_dipsw
.w1:	btst	#1,$fffffc00.w
	beq.s	.w1
	move.b	#$14,$fffffc02.w	; joystick events
	move	#$2300,sr
	rts

restore_hardware:
	move	#$2700,sr
	clr.b	$fffffa19.w
	clr.b	$fffffa1b.w
	lea	old_mfp,a0
	lea	$fffffa07.w,a1
	moveq	#$21-$07,d0
.mfp:	move.b	(a0)+,(a1)
	addq.l	#2,a1
	subq.w	#2,d0
	bpl.s	.mfp
	move.l	old_hbl,$68.w
	move.l	old_vbl,$70.w
	move.l	old_acia,$118.w
	move.l	old_timer_b,$120.w
	move.l	old_timer_a,$134.w
	movem.l	old_palette,d0-d7
	movem.l	d0-d7,$ffff8240.w
	move.b	old_res,$ffff8260.w
	move.b	old_hz,$ffff820a.w
	move.b	old_linewid,$ffff820f.w
	move.b	old_fine,$ffff8265.w
	move.b	old_screen+1,$ffff8201.w
	move.b	old_screen+2,$ffff8203.w
	move.b	old_screen+3,$ffff820d.w
.w1:	btst	#1,$fffffc00.w
	beq.s	.w1
	move.b	#$08,$fffffc02.w	; mouse again
	move	#$2300,sr
	rts

hbl:	rte

; the VBL: borders.s' events, the picture published last, the ticks (six arcade frames per five fields)
vbl:	borders_vbl
	bsr	render_vbl
	if BD_HUD
	bsr	bd_hud_plan
	endc
	addq.l	#1,cnt_vbls
	cmp.b	#32,ticks
	bhs.s	.r
	addq.b	#1,ticks
	addq.b	#1,tick_phase
	cmp.b	#5,tick_phase
	blo.s	.r
	clr.b	tick_phase
	addq.b	#1,ticks
.r:	rte

; Keyboard and joystick 1: CONTROL0 (right 0, left 1, down 2, up 3, attack 4, jump 5, start 7) and COIN (coin 1 bit
; 4, coin 2 bit 3), active low.
acia_isr:
	movem.l	d0-d2/a0,-(sp)
.again:
	ikbd_byte
	lea	key_table,a0
.find:	move.b	(a0),d0
	beq	.again
	cmp.b	d0,d1
	beq.s	.found
	addq	#4,a0
	bra.s	.find
.found:	tst.b	d2
	bmi.s	.release
	move.b	1(a0),d0
	or.b	d0,kbd_control
	move.b	2(a0),d0
	or.b	d0,kbd_coin
	bsr.s	compose
	bra	.again
.release:
	move.b	1(a0),d0
	not.b	d0
	and.b	d0,kbd_control
	move.b	2(a0),d0
	not.b	d0
	and.b	d0,kbd_coin
	bsr.s	compose
	bra	.again
.packet_byte:
	clr.b	ikbd_state
	cmp.b	#2,d0
	bne	.again			; (joystick 1, port 1, plays)
	moveq	#0,d0
	btst	#3,d1
	beq.s	.j1
	bset	#0,d0
.j1:	btst	#2,d1
	beq.s	.j2
	bset	#1,d0
.j2:	btst	#1,d1
	beq.s	.j3
	bset	#2,d0
.j3:	btst	#0,d1
	beq.s	.j4
	bset	#3,d0
.j4:	tst.b	d1
	bpl.s	.j5
	bset	#4,d0
.j5:	move.b	d0,joy_control
	bsr.s	compose
	bra	.again
.done:
	movem.l	(sp)+,d0-d2/a0
	rte

compose:
	move.b	kbd_control,d0
	or.b	joy_control,d0
	not.b	d0
	move.b	d0,in_control0
	move.b	kbd_coin,d0
	not.b	d0
	move.b	d0,in_coin
	rts

; scancode, CONTROL0 bits, COIN bits
key_table:
	dc.b	$4d,$01,$00,0		; right
	dc.b	$4b,$02,$00,0		; left
	dc.b	$50,$04,$00,0		; down
	dc.b	$48,$08,$00,0		; up
	dc.b	$39,$10,$00,0		; space = attack
	dc.b	$2c,$10,$00,0		; Z = attack
	dc.b	$38,$20,$00,0		; alternate = jump
	dc.b	$2d,$20,$00,0		; X = jump
	dc.b	$02,$80,$00,0		; 1 = start
	dc.b	$06,$00,$10,0		; 5 = coin 1
	dc.b	$07,$00,$08,0		; 6 = coin 2
	dc.b	0,0,0,0
	even
	borders_handlers
	borders_blit_go
    endc

	include	"core.s"
    ifnd SIM
	include	"mcu.s"
	include	"render.s"
    endc

	section data,data
    ifnd SIM
snapshot:
	incbin	"snapshot.bin"
	even
black_pal:	dcb.w	16,0
crash_text:	dc.b	"BADPC "
crash_cpu:	dc.b	"M PAGE "
crash_page:	dc.b	"000 PC "
crash_pc:	dc.b	"0000",13,10
crash_end:
	even
    endc

	section bss,bss
old_ssp:	ds.l	1
old_vbl:	ds.l	1
old_acia:	ds.l	1
old_hbl:	ds.l	1
old_timer_a:	ds.l	1
old_timer_b:	ds.l	1
old_palette:	ds.w	16
old_screen:	ds.l	1
cnt_vbls:	ds.l	1		; (counters: VBLs, arcade frames run, pictures drawn, frames dropped)
cnt_logic:	ds.l	1
cnt_pictures:	ds.l	1
cnt_dropped:	ds.l	1
cnt_skipped:	ds.l	1
cnt_from:	ds.l	5		; (BENCH: the counters at VBL BENCH_FROM)
old_mfp:	ds.b	14
old_res:	ds.b	1
old_hz:		ds.b	1
old_linewid:	ds.b	1
old_fine:	ds.b	1
ticks:		ds.b	1
tick_phase:	ds.b	1
since_pic:	ds.b	1
in_control0:	ds.b	1		; (mcu_frame reads these four in this order)
in_control1:	ds.b	1
in_coin:	ds.b	1
in_dipsw:	ds.b	1
kbd_control:	ds.b	1
kbd_coin:	ds.b	1
joy_control:	ds.b	1
quit_flag:	ds.b	1
	even
    ifnd SIM
	ikbd_vars
	even
	borders_vars
	even
    endc
