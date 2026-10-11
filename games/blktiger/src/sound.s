; ------------------------------------------------------------------------------
; Black Tiger's sound on the YM2149: the sound driver's effects and tunes as streams (tools/sound.py records and
; checks them; its Player and play() are this code in Python), five driver steps a VBL (the arcade's timer A: 250 Hz).
;
; bt_snd_vbl (the VBL): a new latch value is a command (bt_snd_cmd), then five steps (bt_snd_steps) and the YM's
; registers.  Effects: one slot a chip, a priority each (a new effect replaces the playing one unless that has a
; higher priority; the priority is the stream's twelfth value).  Tunes: a main and a backup slot; a tune of the main
; one's priority replaces it, a higher one moves it to the backup first, a lower one goes to the backup unless that
; holds a higher one; when the main tune ends the backup becomes the main one; a main tune with header bit 6 lets the
; backup step on silently.  The tunes are packed (engine/lz.py): a command marks its slot loading and the idle hook
; unpacks it into the slot's buffer (bt_snd_load), so the VBL never waits; a slot steps once it is loaded.
; The YM plays the chip whose effect started last; the music's loudest channels take the YM channels it leaves.
; ------------------------------------------------------------------------------

CS_LATCH = g_sound_latch
	include	"capsnd_core.s"

; a command (bt_cmds, 8 bytes)
BC_KIND = 0				; .b  0 none, 1 effect, 2 tune, 3 stop
BC_HDR = 1				; .b  the header (stop: bit 0 the effects, bit 1 the music)
BC_CHIP = 2				; .b
BC_ENT = 4				; .l

BE_END = 22				; an effect: its registers after its end (11 bytes)

; a tune (bt_muNN)
BM_END = 0				; .w  the step it ends at, 0: it loops
BM_SIZE = 2				; .w  unpacked
BM_CH = 4				; .w x 6: the channels' offsets in the unpacked data
BM_LOOP = 16				; .w x 6: their loops' offsets, -1: none
BM_DATA = 28				; the packed data

; a tune slot
TS_STATE = 0				; .b  0 empty, 1 playing, 2 loading
TS_HDR = 1				; .b
TS_N = 2				; .w  steps played
TS_END = 4				; .w
TS_GEN = 6				; .w  the load requests so far
TS_TUNE = 8				; .l  the tune
TS_BUF = 12				; .l  its buffer
TS_CH = 16				; 6 channels
TS_SIZE = TS_CH+6*CH_SIZE

; ---------------------------------------------------------------- the VBL
bt_snd_vbl:
	bsr	bt_snd_cmd
	bra	bt_snd_steps

; a new latch value: its command.  Uses d0-d2 / a0-a2.
bt_snd_cmd:
	move.b	CS_LATCH,d0
	cmp.b	bt_last,d0
	beq	.none
	move.b	d0,bt_last
	cmp.b	#$FF,d0
	beq	.none
	and.w	#$7F,d0
	lsl.w	#3,d0
	lea	bt_cmds,a1
	add.w	d0,a1
	move.b	BC_KIND(a1),d0
	subq.b	#1,d0
	beq	.fx
	subq.b	#1,d0
	beq	.tune
	subq.b	#1,d0
	bne	.none
	move.b	BC_HDR(a1),d0		; a stop
	btst	#0,d0
	beq.s	.stop_music
	clr.w	bt_fxon
	clr.w	bt_pri
	lea	bt_idle,a0
	move.l	a0,bt_out
	move.l	a0,bt_out+4
.stop_music:
	btst	#1,d0
	beq	.none
	move.l	bt_main,a0
	clr.b	TS_STATE(a0)
	move.l	bt_backup,a0
	clr.b	TS_STATE(a0)
	rts
.fx:	moveq	#0,d1			; an effect on its chip unless a higher one plays
	move.b	BC_CHIP(a1),d1
	lea	bt_pri,a0
	move.b	(a0,d1.w),d0
	and.b	#15,d0
	move.b	BC_HDR(a1),d2
	and.b	#15,d2
	cmp.b	d0,d2
	blo	.none
	move.b	BC_HDR(a1),(a0,d1.w)
	lea	bt_fxon,a0
	st	(a0,d1.w)
	move.w	d1,d2
	lsl.w	#6,d2			; (SL_SIZE)
	lea	bt_fx,a0
	add.w	d2,a0
	move.l	BC_ENT(a1),a2
	move.l	a2,SL_ENT(a0)
	move.l	SE_RUNS(a2),SL_POS(a0)
	clr.w	SL_N(a0)
	clr.w	SL_T(a0)
	clr.b	SL_LEFT(a0)
	st	SL_EXCPH(a0)
	add.w	d1,d1
	addq.w	#1,bt_serials
	lea	bt_serial,a2
	move.w	bt_serials,(a2,d1.w)
	add.w	d1,d1
	lea	bt_out,a2
	lea	bt_idle,a0		; (a start writes the idle registers)
	move.l	a0,(a2,d1.w)
	rts
.tune:	move.b	BC_HDR(a1),d0		; the tune's priority (d0) against the main one's (d1) and the backup's (d2)
	and.b	#15,d0
	moveq	#0,d1
	move.l	bt_main,a0
	tst.b	TS_STATE(a0)
	beq.s	.t1
	move.b	TS_HDR(a0),d1
	and.b	#15,d1
.t1:	cmp.b	d1,d0
	beq.s	.load			; the same: it replaces the main one
	bhi.s	.higher
	moveq	#0,d2
	move.l	bt_backup,a0
	tst.b	TS_STATE(a0)
	beq.s	.t2
	move.b	TS_HDR(a0),d2
	and.b	#15,d2
.t2:	cmp.b	d0,d2
	bhi.s	.none			; lower than the backup's: ignored
	bra.s	.load			; the backup
.higher:
	move.l	bt_backup,a0		; the main one to the backup, the tune into the other slot
	move.l	bt_main,bt_backup
	move.l	a0,bt_main
.load:	move.b	#2,TS_STATE(a0)		; (bt_snd_load unpacks it)
	move.b	BC_HDR(a1),TS_HDR(a0)
	move.l	BC_ENT(a1),TS_TUNE(a0)
	addq.w	#1,TS_GEN(a0)
	st	bt_load_req
.none:	rts

; Five steps and the YM.  Uses d0-d7 / a0-a4.
bt_snd_steps:
	moveq	#5-1,d7
.step:	bsr	bt_step
	dbf	d7,.step
	lea	bt_serial,a0		; the chip whose effect started last
	move.l	bt_out,a1
	move.w	2(a0),d0
	cmp.w	(a0),d0
	bls.s	.chosen
	move.l	bt_out+4,a1
.chosen:
	bsr	cs_mix
	lea	cs_regs,a1
	lea	bt_ym,a2
	moveq	#0,d1
.w:	move.b	(a1)+,d0
	cmp.b	(a2),d0
	beq.s	.same
	move.b	d0,(a2)
	move.b	d1,$ffff8800.w
	move.b	d0,$ffff8802.w
.same:	addq.l	#1,a2
	addq.b	#1,d1
	cmp.b	#11,d1
	blo.s	.w
	rts

; a driver step: the effects of both chips, the music -> cs_vals.  Keeps d7.
bt_step:
	addq.b	#1,bt_count
	and.b	#3,bt_count
	moveq	#0,d6			; the chip
.chip:	lea	bt_fxon,a4
	tst.b	(a4,d6.w)
	beq.s	.next
	move.w	d6,d0
	lsl.w	#6,d0
	lea	bt_fx,a0
	add.w	d0,a0
	move.b	bt_count,d0		; phase = (count - n) & 3
	sub.b	SL_N+1(a0),d0
	and.b	#3,d0
	move.b	d0,SL_PHASE(a0)
	bsr	cs_step
	beq.s	.ended
	lea	bt_pri,a1
	move.b	SL_OUT+11(a0),(a1,d6.w)
	lea	SL_OUT(a0),a1
	bra.s	.out
.ended:	clr.b	(a4,d6.w)
	lea	bt_pri,a1
	clr.b	(a1,d6.w)
	move.l	SL_ENT(a0),a1
	lea	BE_END(a1),a1
.out:	move.w	d6,d0
	lsl.w	#2,d0
	lea	bt_out,a2
	move.l	a1,(a2,d0.w)
.next:	addq.w	#1,d6
	cmp.w	#2,d6
	blo.s	.chip
	move.l	bt_main,a0		; the music
	cmp.b	#1,TS_STATE(a0)
	bne.s	.silent
	bsr.s	bt_tune_ended
	beq.s	.play
	move.l	bt_backup,bt_main	; ended: the backup becomes the main one
	move.l	a0,bt_backup
	clr.b	TS_STATE(a0)
.silent:
	lea	cs_vals,a1
	moveq	#6-1,d1
.z:	clr.l	(a1)+
	dbf	d1,.z
	rts
.play:	lea	cs_vals,a1
	bsr.s	bt_tune_step
	btst	#6,TS_HDR(a0)
	beq.s	.done
	move.l	bt_backup,a0		; header bit 6: the backup steps on silently
	cmp.b	#1,TS_STATE(a0)
	bne.s	.done
	bsr.s	bt_tune_ended
	beq.s	.bg
	clr.b	TS_STATE(a0)
	rts
.bg:	lea	bt_discard,a1
	bra.s	bt_tune_step
.done:	rts

; tune slot a0: Z clear when it has played its last step (the driver's 08DF then)
bt_tune_ended:
	move.w	TS_END(a0),d0
	beq.s	.no
	cmp.w	TS_N(a0),d0
	bhi.s	.no
	moveq	#1,d0
	rts
.no:	moveq	#0,d0
	rts

; a step of tune slot a0's six channels -> (a1): period, volume words.  Keeps a0.
bt_tune_step:
	lea	TS_CH(a0),a2
	moveq	#6-1,d5
.ch:	bsr	cs_chan
	move.w	d0,(a1)+
	move.w	d1,(a1)+
	lea	CH_SIZE(a2),a2
	dbf	d5,.ch
	addq.w	#1,TS_N(a0)
	rts

; ---------------------------------------------------------------- unpacking (the idle hook; not in an interrupt)
; The slots marked loading: their tune unpacked into their buffer, the channels set up, then playing (unless another
; request came meanwhile: then again).  Uses d0-d3 / a0-a3.
bt_snd_load:
	clr.b	bt_load_req
	lea	bt_tslots,a3
	moveq	#2-1,d3
.slot:	cmp.b	#2,TS_STATE(a3)
	bne.s	.next
.again:	move.w	TS_GEN(a3),d2
	move.l	TS_TUNE(a3),a0
	lea	BM_DATA(a0),a0
	move.l	TS_BUF(a3),a1
	bsr	lz_unpack
	move	sr,-(sp)
	move	#$2700,sr
	cmp.w	TS_GEN(a3),d2
	bne.s	.changed
	cmp.b	#2,TS_STATE(a3)
	bne.s	.changed
	move.l	TS_TUNE(a3),a0		; the channels
	move.w	BM_END(a0),TS_END(a3)
	clr.w	TS_N(a3)
	lea	TS_CH(a3),a1
	moveq	#6-1,d1
.ch:	moveq	#0,d0
	move.w	BM_CH(a0),d0
	add.l	TS_BUF(a3),d0
	move.l	d0,CH_POS(a1)
	moveq	#0,d0
	move.w	BM_LOOP(a0),d0
	cmp.w	#$FFFF,d0
	beq.s	.noloop
	add.l	TS_BUF(a3),d0
	bra.s	.loop
.noloop:
	moveq	#0,d0
.loop:	move.l	d0,CH_LOOP(a1)
	clr.l	CH_PER(a1)
	addq.l	#2,a0
	lea	CH_SIZE(a1),a1
	dbf	d1,.ch
	move.b	#1,TS_STATE(a3)
	move	(sp)+,sr
	bra.s	.next
.changed:
	move	(sp)+,sr
	cmp.b	#2,TS_STATE(a3)		; (a new request for this slot: unpack that one)
	beq.s	.again
.next:	lea	TS_SIZE(a3),a3
	dbf	d3,.slot
	rts

	include	"lz.s"

; At the start: no sound.
bt_snd_init:
	lea	bt_bss,a0
	move.w	#bt_bss_end-bt_bss-1,d0
.c:	clr.b	(a0)+
	dbf	d0,.c
	lea	bt_ym,a0
	moveq	#11-1,d0
.y:	st	(a0)+
	dbf	d0,.y
	lea	bt_idle,a0
	move.l	a0,bt_out
	move.l	a0,bt_out+4
	lea	bt_tslots,a0
	move.l	a0,bt_main
	move.l	#bt_buf0,TS_BUF(a0)
	lea	TS_SIZE(a0),a0
	move.l	a0,bt_backup
	move.l	#bt_buf1,TS_BUF(a0)
	bra	cs_mix_init

	section data,data
bt_latch_addr:
	dc.l	CS_LATCH		; (for tools/sound_test.py)
	include	"bt_sound.s"
	section bss,bss
	even
bt_bss:
bt_fx:		ds.b	2*SL_SIZE
bt_tslots:	ds.b	2*TS_SIZE
bt_main:	ds.l	1		; the main tune slot
bt_backup:	ds.l	1
bt_out:		ds.l	2		; per chip: its registers now
bt_serial:	ds.w	2		; per chip: when its effect started
bt_serials:	ds.w	1
bt_discard:	ds.w	2*6		; (the silent backup's values)
bt_fxon:	ds.b	2		; per chip: its effect plays
bt_pri:		ds.b	2		; per chip: its effect's priority (the driver's C020 / C021)
bt_ym:		ds.b	12		; the YM2149's registers 0-10 as written
bt_last:	ds.b	1		; the last latch value
bt_count:	ds.b	1		; the driver's C022 & 3
bt_load_req:	ds.b	1		; a tune slot waits to be unpacked
	even
bt_bss_end:
bt_buf0:	ds.b	BT_TUNE_MAX
bt_buf1:	ds.b	BT_TUNE_MAX
	even
	section text,code
