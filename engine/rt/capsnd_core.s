; ------------------------------------------------------------------------------
; The parts of the Capcom sound players (engine/rt/capsnd.s, games/blktiger/src/sound.s) that do not depend on the
; driver's scheme: an effect slot's stream (cs_step: runs, phase exceptions, a total; engine/capsnd.py fx_step), a
; music channel's stream (cs_chan: Channel), the mixer of the music around the effect (cs_mix: combine / Mixer),
; cs_off.  The including file defines CS_FXSLOTS and the data's tables and calls cs_mix_init at its start.
; ------------------------------------------------------------------------------

CS_NREG = 12				; the registers 0-10 and the kill byte

	ifnd	CS_MCH
CS_MCH = 6				; the music channels (cs_vals, the mixer)
	endc
	ifnd	CS_BOOST
CS_BOOST = 0				; 1: the game's table cs_boost adds to each music channel's key
	endc

; an effect slot
SL_ENT = 0				; .l  its effect (cs_fxNN), 0: inactive
SL_POS = 4				; .l  the next run record
SL_LOOPPOS = 8				; .l  the run record of the loop's index
SL_EXC = 12				; .l  the next exception of its phase
SL_N = 16				; .w  steps done
SL_SERIAL = 18				; .w  the start order
SL_LEFT = 20				; .b  steps left in the current run
SL_PHASE = 21				; .b
SL_EXCPH = 22				; .b  the phase SL_EXC belongs to, $FF: none
SL_FLAG = 23				; .b  the kill byte ($FF: stays under a higher slot), kept across effects
SL_REGS = 24				; 12 bytes: the values of phase 0
SL_OUT = 36				; 12 bytes: the output of the last step
SL_T = 48				; .w  steps done in all (an effect with a total ends after it)
SL_SIZE = 64

; an effect (cs_fxNN)
SE_LENGTH = 0				; .w
SE_LOOP = 2				; .w  -1: none
SE_RUNS = 4				; .l
SE_EXC = 8				; .l x 3
SE_TOTAL = 20				; .w  the steps in all (its loop repeated), 0: no limit

; a music channel
CH_POS = 0				; .l  the next byte
CH_LOOP = 4				; .l  the loop, 0: none
CH_PER = 8				; .w
CH_LEFT = 10				; .b
CH_VOL = 11				; .b
CH_SIZE = 12

	section text,code

; value \1 of a run record: taken from (a2)+ when its mask bit (the low bit of d0) is set
cs_bit	macro
	lsr.w	#1,d0
	bcc.s	.b\@
	move.b	(a2)+,SL_REGS+\1(a0)
.b\@:
	endm

; one step of slot a0: Z set when it ended.  Uses d0-d3 / a1-a3.
cs_step:
	move.l	SL_ENT(a0),a1
	move.w	SE_TOTAL(a1),d0		; a total: it ends after so many steps
	beq.s	.no_total
	cmp.w	SL_T(a0),d0
	bls	.ended
.no_total:
	addq.w	#1,SL_T(a0)
	move.w	SL_N(a0),d2
	cmp.w	SE_LENGTH(a1),d2
	blo.s	.in
	move.w	SE_LOOP(a1),d2		; at the end: the loop, or the end
	bmi	.ended
	move.w	d2,SL_N(a0)
	move.l	SL_LOOPPOS(a0),SL_POS(a0)
	clr.b	SL_LEFT(a0)
	st	SL_EXCPH(a0)
.in:
	tst.b	SL_LEFT(a0)
	bne.s	.in_run
	cmp.w	SE_LOOP(a1),d2
	bne.s	.no_loop
	move.l	SL_POS(a0),SL_LOOPPOS(a0)
.no_loop:
	move.l	SL_POS(a0),a2		; a run record: steps, mask, the values that change
	move.b	(a2)+,SL_LEFT(a0)
	move.b	(a2)+,d0
	lsl.w	#8,d0
	move.b	(a2)+,d0
	cs_bit	0
	cs_bit	1
	cs_bit	2
	cs_bit	3
	cs_bit	4
	cs_bit	5
	cs_bit	6
	cs_bit	7
	cs_bit	8
	cs_bit	9
	cs_bit	10
	cs_bit	11
	move.l	a2,SL_POS(a0)
.in_run:
	subq.b	#1,SL_LEFT(a0)
	move.b	SL_PHASE(a0),d3
	cmp.b	SL_EXCPH(a0),d3
	beq.s	.seeked
	bsr	cs_seek
.seeked:
	lea	SL_REGS(a0),a2		; the output: phase 0's values
	lea	SL_OUT(a0),a3
	rept	CS_NREG/4
	move.l	(a2)+,(a3)+
	endr
	tst.b	d3
	beq.s	.done
	move.l	SL_EXC(a0),a2		; this phase's exception at this index
	move.b	(a2),d0
	lsl.w	#8,d0
	move.b	1(a2),d0
	cmp.w	#$FFFF,d0
	beq.s	.done
	cmp.w	d2,d0
	bne.s	.done
	addq.l	#2,a2
	move.b	(a2)+,d0
	lsl.w	#8,d0
	move.b	(a2)+,d0
	lea	SL_OUT(a0),a3
	moveq	#CS_NREG-1,d1
.x:	lsr.w	#1,d0
	bcc.s	.x_keep
	move.b	(a2)+,(a3)
.x_keep:
	addq.l	#1,a3
	dbf	d1,.x
	move.l	a2,SL_EXC(a0)
.done:
	addq.w	#1,d2
	move.w	d2,SL_N(a0)
	moveq	#1,d0			; (Z clear: it goes on)
	rts
.ended:
	moveq	#0,d0
	rts

; SL_EXC for SL_PHASE (d3) at index d2: the first exception at or after it.  Uses d0, d1, a2.
cs_seek:
	move.b	d3,SL_EXCPH(a0)
	tst.b	d3
	beq.s	.none
	moveq	#0,d0
	move.b	d3,d0
	lsl.w	#2,d0
	move.l	SE_EXC-4(a1,d0.w),a2
.s:	move.b	(a2),d0
	lsl.w	#8,d0
	move.b	1(a2),d0
	cmp.w	#$FFFF,d0
	beq.s	.at
	cmp.w	d2,d0
	bhs.s	.at
	move.b	2(a2),d0		; skip it: 4 + the bits of its mask
	lsl.w	#8,d0
	move.b	3(a2),d0
	addq.l	#4,a2
	moveq	#CS_NREG-1,d1
.b:	lsr.w	#1,d0
	bcc.s	.b0
	addq.l	#1,a2
.b0:	dbf	d1,.b
	bra.s	.s
.at:	move.l	a2,SL_EXC(a0)
.none:
	rts

; a tick of the channel at a2 -> d0.w period, d1.w volume.  Uses a3.
cs_chan:
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

; ---------------------------------------------------------------- the YM's registers 0-10 -> cs_regs: the effect's (a1)
; on the channels it sounds on, the music on the others

; YM channel \1 of the effect: free for the music (a bit in d5) unless it sounds (a volume, the tone or the noise on);
; a free one is silent with tone and noise off until the music takes it
cs_free	macro
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
cs_key	macro
	moveq	#-1,d0
	tst.w	4*\1(a1)
	beq.s	.k\@
	moveq	#0,d0
	move.w	4*\1+2(a1),d0
	beq.s	.z\@
	add.w	d0,d0
	tst.b	\1(a2)
	bmi.s	.b\@
	addq.w	#1,d0
.b\@:
	ifne	CS_BOOST
	add.b	cs_boost+\1,d0
	endc
	bra.s	.k\@
.z\@:	moveq	#-1,d0
.k\@:	move.w	d0,2*\1(a3)
	endm

; the best key so far (d3) and its channel (d4) against channel \1's
cs_best	macro
	move.w	2*\1(a3),d0
	cmp.w	d3,d0
	ble.s	.n\@
	move.w	d0,d3
	moveq	#\1,d4
.n\@:
	endm

cs_mix:
	lea	cs_regs,a0
	rept	11
	move.b	(a1)+,(a0)+
	endr
	lea	-11(a0),a0
	move.b	7(a0),d2		; the mixer
	moveq	#0,d5			; the YM channels free for the music
	cs_free	0
	cs_free	1
	cs_free	2
	lea	cs_new,a4		; the new YM channel of each music channel, -1: none
	moveq	#CS_MCH-1,d1
.n:	st	(a4)+
	dbf	d1,.n
	lea	-CS_MCH(a4),a4
	lea	cs_vals,a1
	lea	cs_ym_of,a2
	lea	cs_key_,a3
CS_CH	set	0
	rept	CS_MCH
	cs_key	CS_CH
CS_CH	set	CS_CH+1
	endr
	lea	cs_pick,a1		; the loudest (the lowest channel of a tie), as many as are free
	moveq	#0,d7
	lea	cs_popc,a2
	move.b	(a2,d5.w),d7
	moveq	#0,d6			; (picked)
	bra	.p_next
.p:	moveq	#-1,d3
	moveq	#-1,d4
CS_CH	set	0
	rept	CS_MCH
	cs_best	CS_CH
CS_CH	set	CS_CH+1
	endr
	tst.w	d4
	bmi	.p_done			; (no more that sound)
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
	lea	cs_pick,a1		; the picked ones that keep their YM channel
	lea	cs_ym_of,a2
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
	lea	cs_pick,a1		; the others on the lowest free ones; then all of them to their channels
	lea	cs_vals,a2
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
	lea	cs_ym_of,a2		; (the new YM channels)
	moveq	#CS_MCH-1,d1
.c:	move.b	(a4)+,(a2)+
	dbf	d1,.c
	rts

cs_popc:
	dc.b	0,1,1,2,1,2,2,3
	even
; the mixer at the start: no music channel on a YM channel
cs_mix_init:
	lea	cs_ym_of,a0
	moveq	#CS_MCH-1,d0
.i:	st	(a0)+
	dbf	d0,.i
	rts

; The YM silent (at the exit).
cs_off:
	move.b	#7,$ffff8800.w
	move.b	#$FF,$ffff8802.w
	moveq	#8,d0
.o:	move.b	d0,$ffff8800.w
	clr.b	$ffff8802.w
	addq.b	#1,d0
	cmp.b	#11,d0
	blo.s	.o
	rts

	section bss,bss
	even
cs_vals:	ds.w	2*CS_MCH	; per music channel: the period, the volume of this tick
cs_key_:	ds.w	CS_MCH
cs_regs:	ds.b	12		; the YM's registers 0-10 of this tick
cs_ym_of:	ds.b	CS_MCH		; per music channel: its YM channel, -1: none
cs_new:		ds.b	CS_MCH
cs_pick:	ds.b	4
	even
	section text,code
