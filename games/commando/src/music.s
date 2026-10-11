; ------------------------------------------------------------------------------
; The music on the YM2149: the sound driver's FM tunes as square waves, recorded per FM channel (tools/sound_music.py,
; its Player / Channel / Mixer are this code in Python, step for step).
;
; The driver: commands $20-$2C start a tune in its slot ($4100-$4400), $2D / $2E stop every slot; only the highest
; slot that plays steps (a lower tune pauses).  Here a slot steps its six channels' streams a tick; a tune that ends
; plays the release of its notes (its tail) while no other tune plays.  The six channels (two YM2203, 3 FM channels
; each) share the YM's three with the effect: the effect keeps the channels it sounds on, the loudest music channels
; take the others (one that played the tick before wins a tie, and keeps its YM channel if it can).
;
; A stream is bytes, a tick a step:  $00-$7F hold n + 1 ticks, $80-$8F volume n, $90-$9F volume - 1 then hold n & 15
; + 1 ticks, $A0-$AF b: period (n & 15) << 8 | b (no tick), $FF the end (the loop, or silence).
; ------------------------------------------------------------------------------

; a channel of a slot
CH_POS = 0				; .l  the next byte
CH_LOOP = 4				; .l  the loop, 0: none
CH_PER = 8				; .w  the period
CH_LEFT = 10				; .b  ticks left to hold
CH_VOL = 11				; .b  the volume
CH_SIZE = 12

; a slot
MS_STATE = 0				; .b  0: empty, 1: playing, 2: its tail
MS_N = 2				; .w  ticks played
MS_END = 4				; .w  the tick its tune ends at, 0: it loops
MS_CH = 6				; 6 channels
MS_SIZE = MS_CH+6*CH_SIZE

; mus_table entries (music_data.s), commands $20-$2F
ME_SLOT = 0				; .b  0-3, $FE: stop every slot, $FF: nothing
ME_END = 2				; .w
ME_START = 4				; .l x 6
ME_LOOP = 28				; .l x 6, 0: none

; the latch (of the tick before) and the highest slot's tick -> mus_vals.  Uses d0-d4 / a0-a3.
mus_tick:
	move.b	LATCH,d0
	cmp.b	mus_last,d0
	beq.s	.run
	move.b	d0,mus_last
	sub.b	#$20,d0
	cmp.b	#$10,d0
	bhs.s	.run
	and.w	#15,d0
	mulu	#ME_SIZE,d0
	lea	mus_table,a1
	add.w	d0,a1
	move.b	ME_SLOT(a1),d1
	cmp.b	#$FE,d1
	beq.s	.stop
	bhi.s	.run
	ext.w	d1
	mulu	#MS_SIZE,d1
	lea	mus_slots,a0
	add.w	d1,a0
	move.b	#1,MS_STATE(a0)
	clr.w	MS_N(a0)
	move.w	ME_END(a1),MS_END(a0)
	lea	MS_CH(a0),a2
	lea	ME_START(a1),a3
	moveq	#6-1,d1
.ci:	move.l	(a3),CH_POS(a2)
	move.l	ME_LOOP-ME_START(a3),CH_LOOP(a2)
	clr.l	CH_PER(a2)		; (period, hold, volume)
	addq.l	#4,a3
	lea	CH_SIZE(a2),a2
	dbf	d1,.ci
	bra.s	.run
.stop:	lea	mus_slots,a0
	moveq	#4-1,d1
.st:	clr.b	MS_STATE(a0)
	lea	MS_SIZE(a0),a0
	dbf	d1,.st
.run:
	lea	mus_slots+3*MS_SIZE,a0	; the highest slot that plays, else the highest tail
	moveq	#4-1,d1
.t1:	cmp.b	#1,MS_STATE(a0)
	beq.s	.top
	lea	-MS_SIZE(a0),a0
	dbf	d1,.t1
	lea	mus_slots+3*MS_SIZE,a0
	moveq	#4-1,d1
.t2:	tst.b	MS_STATE(a0)
	bne.s	.top
	lea	-MS_SIZE(a0),a0
	dbf	d1,.t2
	lea	mus_vals,a1		; no music
	moveq	#6-1,d1
.z:	clr.l	(a1)+
	dbf	d1,.z
	rts
.top:	lea	MS_CH(a0),a2
	lea	mus_vals,a1
	moveq	#0,d4			; (any volume)
	moveq	#6-1,d3
.ch:	bsr.s	mus_chan
	move.w	d0,(a1)+
	move.w	d1,(a1)+
	or.b	d1,d4
	lea	CH_SIZE(a2),a2
	dbf	d3,.ch
	addq.w	#1,MS_N(a0)
	cmp.b	#2,MS_STATE(a0)
	bne.s	.playing
	tst.b	d4
	bne.s	.done
	clr.b	MS_STATE(a0)		; the tail has died away
.done:	rts
.playing:
	move.w	MS_END(a0),d0
	beq.s	.others
	cmp.w	MS_N(a0),d0
	bne.s	.others
	move.b	#2,MS_STATE(a0)		; the tune ended: its tail
	rts
.others:
	lea	mus_slots,a1		; a tune that plays ends the tails
	moveq	#4-1,d1
.o:	cmp.b	#2,MS_STATE(a1)
	bne.s	.o1
	clr.b	MS_STATE(a1)
.o1:	lea	MS_SIZE(a1),a1
	dbf	d1,.o
	rts

; a tick of the channel at a2 -> d0.w period, d1.w volume.  Uses a3.
mus_chan:
	tst.b	CH_LEFT(a2)
	beq.s	.read
	subq.b	#1,CH_LEFT(a2)
	bra.s	.cur
.read:	move.l	CH_POS(a2),a3
.r:	moveq	#0,d0
	move.b	(a3)+,d0
	cmp.b	#$FF,d0
	beq.s	.end
	cmp.b	#$A0,d0
	bhs.s	.per
	cmp.b	#$90,d0
	bhs.s	.down
	cmp.b	#$80,d0
	bhs.s	.vol
	move.b	d0,CH_LEFT(a2)		; hold
	bra.s	.save
.down:	subq.b	#1,CH_VOL(a2)
	and.b	#15,d0
	move.b	d0,CH_LEFT(a2)
	bra.s	.save
.vol:	and.b	#15,d0
	move.b	d0,CH_VOL(a2)
	bra.s	.save
.per:	and.w	#15,d0
	lsl.w	#8,d0
	move.b	(a3)+,d0
	move.w	d0,CH_PER(a2)
	bra.s	.r
.end:	move.l	CH_LOOP(a2),d0
	beq.s	.silent
	move.l	d0,a3
	bra.s	.r
.silent:
	subq.l	#1,a3			; (stays at the end)
	clr.b	CH_VOL(a2)
.save:	move.l	a3,CH_POS(a2)
.cur:	move.w	CH_PER(a2),d0
	moveq	#0,d1
	move.b	CH_VOL(a2),d1
	rts

; The YM's registers 0-10 -> mus_regs: the effect's (a1) on the channels it sounds on, the music on the others.
; Uses d0-d7 / a0-a4.

; YM channel \1 of the effect: free for the music (a bit in d5) unless it sounds (a volume, the tone or the noise on);
; a free one is silent with tone and noise off until the music takes it
mus_free macro
	move.b	8+\1(a0),d0
	and.b	#$1F,d0
	beq.s	.f\@
	moveq	#9<<\1,d0
	and.b	d2,d0
	cmp.b	#9<<\1,d0
	bne.s	.u\@
.f\@:	bset	#\1,d5
	clr.b	8+\1(a0)
	or.b	#9<<\1,d2
.u\@:
	endm

; the key of music channel \1: volume * 2 + (it played last tick), -1: silent
mus_key macro
	moveq	#-1,d0
	tst.w	4*\1(a1)
	beq.s	.k\@
	moveq	#0,d0
	move.w	4*\1+2(a1),d0
	beq.s	.z\@
	add.w	d0,d0
	tst.b	\1(a2)
	bmi.s	.k\@
	addq.w	#1,d0
	bra.s	.k\@
.z\@:	moveq	#-1,d0
.k\@:	move.w	d0,2*\1(a3)
	endm

; the best key so far (d3) and its channel (d4) against channel \1's
mus_best macro
	move.w	2*\1(a3),d0
	cmp.w	d3,d0
	ble.s	.n\@
	move.w	d0,d3
	moveq	#\1,d4
.n\@:
	endm

mus_mix:
	lea	mus_regs,a0
	rept	11
	move.b	(a1)+,(a0)+
	endr
	lea	-11(a0),a0
	move.b	7(a0),d2		; the mixer
	moveq	#0,d5			; the YM channels free for the music
	mus_free 0
	mus_free 1
	mus_free 2
	lea	mus_new,a4		; the new YM channel of each music channel, -1: none
	moveq	#-1,d0
	move.l	d0,(a4)
	move.w	d0,4(a4)
	lea	mus_vals,a1
	lea	mus_ym,a2
	lea	mus_key,a3
	mus_key	0
	mus_key	1
	mus_key	2
	mus_key	3
	mus_key	4
	mus_key	5
	lea	mus_pick,a1		; the loudest (the lowest channel of a tie), as many as are free
	moveq	#0,d7
	lea	mus_popc,a2
	move.b	(a2,d5.w),d7
	moveq	#0,d6			; (picked)
	bra.s	.p_next
.p:	moveq	#-1,d3
	moveq	#-1,d4
	mus_best 0
	mus_best 1
	mus_best 2
	mus_best 3
	mus_best 4
	mus_best 5
	tst.w	d4
	bmi.s	.p_done			; (no more that sound)
	add.w	d4,d4
	move.w	#-1,(a3,d4.w)		; (taken)
	lsr.w	#1,d4
	move.b	d4,(a1)+
	addq.w	#1,d6
.p_next:
	dbf	d7,.p
.p_done:
	subq.w	#1,d6
	bmi.s	.none
	moveq	#0,d4			; the YM channels taken (bits)
	lea	mus_pick,a1		; the picked ones that keep their YM channel
	lea	mus_ym,a2
	move.w	d6,d1
	moveq	#0,d0
.a:	move.b	(a1)+,d0
	move.b	(a2,d0.w),d3
	bmi.s	.a1
	btst	d3,d5
	beq.s	.a1
	bset	d3,d4
	move.b	d3,(a4,d0.w)
.a1:	dbf	d1,.a
	lea	mus_pick,a1		; the others on the lowest free ones; then all of them to their channels
	lea	mus_vals,a2
.b:	move.b	(a1)+,d0
	move.b	(a4,d0.w),d3
	bpl.s	.b2
	moveq	#0,d3
.b1:	btst	d3,d5
	beq.s	.b1n
	btst	d3,d4
	beq.s	.b1f
.b1n:	addq.w	#1,d3
	bra.s	.b1
.b1f:	bset	d3,d4
	move.b	d3,(a4,d0.w)
.b2:	ext.w	d3
	lsl.w	#2,d0
	move.b	3(a2,d0.w),8(a0,d3.w)	; the volume
	bclr	d3,d2			; the tone on
	add.w	d3,d3
	move.b	1(a2,d0.w),(a0,d3.w)	; the period
	move.b	(a2,d0.w),1(a0,d3.w)
	moveq	#0,d0
	dbf	d6,.b
.none:	move.b	d2,7(a0)
	move.l	(a4),mus_ym		; (the new YM channels)
	move.w	4(a4),mus_ym+4
	rts

mus_popc:
	dc.b	0,1,1,2,1,2,2,3

; At the start: no music.
mus_init:
	lea	mus_slots,a0
	move.w	#4*MS_SIZE-1,d0
.c:	clr.b	(a0)+
	dbf	d0,.c
	moveq	#-1,d0
	move.l	d0,mus_ym
	move.w	d0,mus_ym+4
	clr.b	mus_last
	rts

	include	"music_data.s"

	section bss,bss
mus_slots:	ds.b	4*MS_SIZE
mus_vals:	ds.w	2*6		; per music channel: the period, the volume of this tick
mus_key:	ds.w	6
mus_regs:	ds.b	12		; the YM's registers 0-10 of this tick
mus_ym:		ds.b	6		; per music channel: its YM channel, -1: none
mus_new:	ds.b	6
mus_pick:	ds.b	4
mus_last:	ds.b	1		; the driver's $4001 (as sfx_last)
	even
	section text,code
