; ------------------------------------------------------------------------------
; Sound on the YM2149: the sound driver's programs (tunes, effects) as recorded register images, played in the
; driver's own scheme (tools/sound.py, its `Player` is this player in Python, step for step).
;
; Eight slots: music $4480 / $4300 (two chips: both chips' output, three of their six channels recorded), $4580 /
; $4600 (the first chip: tunes, the in-game drums), effects $4100 / $4200 / $4180 / $4080 (the second chip).  A
; command starts a program in its slot or stops slots (snd_cmd_tab).  Per tick (the driver's four IRQs) the highest
; active music slot and the highest active effect slot step one tick of their program; $4180 / $4080 start their
; effect again when the counter (four a tick) & $1F / & 7 is 0.  The YM gets the two chip program, else the music's
; image with every channel the effect sounds on taken from the effect.
;
; A program is words, per tick (images: 12 bytes, registers 0-10 of the YM, periods for its 2 MHz):
;   $0nnn        image n for one tick
;   $8000 + r << 12 + n   image n for r + 2 ticks
;   $F000, w     go on at word w of the program (a loop)
;   $FFF8 + j, n the last tick: image n, the slot ended in the driver's IRQ j of the tick
; ------------------------------------------------------------------------------

SND_LATCH = G_Z80-$3800			; C800 (the main CPU's sound latch)
SND_JUMP = $F000
SND_END = $FFF8

SL_POS = 0				; .l  the next word, 0: inactive
SL_BASE = 4				; .l  the program
SL_IMG = 8				; .l  the image of its last step, 0: none yet
SL_LEFT = 12				; .w  ticks left of the current image
SL_RMASK = 14				; .b  restarts when the counter & this is 0 (0: never)
SL_RPROG = 16				; .l  the program it restarts
SL_SIZE = 32

; channel \1 of the effect (a3) over the buffer (a0) when it sounds: period, volume, its mixer bits
snd_chan macro
	tst.b	8+\1(a3)
	beq.s	.c\@
	move.b	2*\1(a3),2*\1(a0)
	move.b	2*\1+1(a3),2*\1+1(a0)
	move.b	8+\1(a3),8+\1(a0)
	and.b	#~(9<<\1),d1
	move.b	7(a3),d0
	and.b	#9<<\1,d0
	or.b	d0,d1
	btst	#3+\1,7(a3)
	bne.s	.c\@
	st	d2
.c\@:
	endm

; one tick: the latch (of the tick before), the slots, the YM.  Clobbers d0-d4 / a0-a3.
snd_tick:
	move.b	SND_LATCH,d0
	cmp.b	snd_last,d0
	beq.s	.run
	move.b	d0,snd_last
	cmp.b	#$20,d0
	bhs.s	.run
	and.w	#$1F,d0
	lsl.w	#3,d0
	lea	snd_cmd_tab,a0
	add.w	d0,a0
	move.w	(a0)+,d1		; the slot to start, -1: none
	bmi.s	.stops
	lsl.w	#5,d1
	lea	snd_slots,a1
	add.w	d1,a1
	move.l	2(a0),d1
	move.l	d1,SL_POS(a1)
	move.l	d1,SL_BASE(a1)
	clr.w	SL_LEFT(a1)
.stops:	move.w	(a0),d1			; the slots it stops: bit n = slot n
	beq.s	.run
	lea	snd_slots,a1
.st:	lsr.w	#1,d1
	bcc.s	.st1
	clr.l	SL_POS(a1)
.st1:	lea	SL_SIZE(a1),a1
	tst.w	d1
	bne.s	.st
.run:
	addq.b	#4,snd_count
	lea	snd_slots,a1		; the music
	moveq	#4-1,d3
	bsr.s	snd_advance
	lea	snd_slots+4*SL_SIZE,a1	; the effects
	moveq	#4-1,d3
	bsr.s	snd_advance
	bra	snd_output

; The highest active slot of the four at a1 steps a tick (d3 = 3).  A slot whose program ended in the IRQ 0 or 1 of
; the tick hands the tick to the next active one (once).  Clobbers d0-d4 / a0-a2.
snd_advance:
	moveq	#1,d2			; (one hand-over)
.find:	tst.l	SL_POS(a1)
	bne.s	.step
.next:	lea	SL_SIZE(a1),a1
	dbf	d3,.find
	rts
.step:	moveq	#-1,d1			; (not ended)
	move.w	SL_LEFT(a1),d0
	beq.s	.word
	subq.w	#1,SL_LEFT(a1)
	bra.s	.stepped
.word:	move.l	SL_POS(a1),a0
	move.w	(a0)+,d0
	cmp.w	#SND_JUMP,d0
	bne.s	.nojump
	move.w	(a0),d0
	add.w	d0,d0
	move.l	SL_BASE(a1),a0
	add.w	d0,a0
	move.w	(a0)+,d0
.nojump:
	cmp.w	#SND_END,d0
	bhs.s	.end
	move.l	a0,SL_POS(a1)
	move.w	d0,d4
	bpl.s	.one
	rol.w	#4,d4			; a run: r + 2 ticks, r + 1 left after this one
	and.w	#7,d4
	addq.w	#1,d4
	move.w	d4,SL_LEFT(a1)
.one:	and.w	#$0FFF,d0
	bsr.s	.image
	bra.s	.stepped
.end:	moveq	#3,d1
	and.w	d0,d1			; the IRQ it ended in
	move.w	(a0),d0
	bsr.s	.image
.stepped:
	move.b	SL_RMASK(a1),d0
	beq.s	.norestart
	and.b	snd_count,d0
	bne.s	.norestart
	tst.w	d1
	bmi.s	.restart
	cmp.w	#3,d1
	bne.s	.norestart
.restart:				; (after the step: the tick shows it)
	move.l	SL_RPROG(a1),d0
	move.l	d0,SL_POS(a1)
	move.l	d0,SL_BASE(a1)
	clr.w	SL_LEFT(a1)
	rts
.norestart:
	tst.w	d1
	bmi.s	.done
	clr.l	SL_POS(a1)		; ended
	cmp.w	#1,d1
	bhi.s	.done
	subq.w	#1,d2
	beq	.next			; the rest of the tick for the next one
.done:	rts
.image:	and.l	#$FFFF,d0		; image d0 -> SL_IMG
	mulu	#12,d0
	add.l	#snd_images,d0
	move.l	d0,SL_IMG(a1)
	rts

; The YM's registers 0-10: a two chip tune, or the music with the effect's sounding channels over it.
snd_output:
	lea	snd_slots,a1
	moveq	#4-1,d3
	moveq	#0,d2
.tm:	tst.l	SL_POS(a1)
	bne.s	.music
	lea	SL_SIZE(a1),a1
	addq.w	#1,d2
	dbf	d3,.tm
	sub.l	a2,a2			; no music
	bra.s	.effect
.music:	move.l	SL_IMG(a1),a2
	cmp.w	#2,d2
	bhs.s	.effect
	move.l	a2,d0			; a two chip tune: it alone
	bne	snd_write
	bra.s	.silent
.effect:
	sub.l	a3,a3
	lea	snd_slots+4*SL_SIZE,a1
	moveq	#4-1,d3
.te:	tst.l	SL_POS(a1)
	bne.s	.eff
	lea	SL_SIZE(a1),a1
	dbf	d3,.te
	bra.s	.noeff
.eff:	move.l	SL_IMG(a1),a3
.noeff:	move.l	a3,d0
	bne.s	.over
	move.l	a2,d0			; no effect: the music
	bne	snd_write
.silent:
	lea	snd_silent,a2
	bra	snd_write
.over:	move.l	a2,d0
	bne.s	.both
	move.l	a3,a2			; no music: the effect
	bra	snd_write
.both:	lea	snd_buf,a0
	move.l	(a2)+,(a0)+
	move.l	(a2)+,(a0)+
	move.l	(a2)+,(a0)+
	lea	snd_buf,a0
	move.b	7(a0),d1		; the mixer
	moveq	#0,d2			; the noise of the effect is used
	snd_chan 0
	snd_chan 1
	snd_chan 2
	move.b	d1,7(a0)
	tst.b	d2
	beq.s	.nonoise
	move.b	6(a3),6(a0)
	bra.s	.ov
.nonoise:
	move.b	d1,d0
	and.b	#$38,d0
	cmp.b	#$38,d0
	bne.s	.ov
	clr.b	6(a0)
.ov:	move.l	a0,a2
	; fall through

; the registers 0-10 at a2 to the YM, the ones that changed (no interrupt handler of the port touches the YM)
snd_write:
	lea	snd_ym,a0
	moveq	#0,d1
.w:	move.b	(a2)+,d0
	cmp.b	(a0),d0
	beq.s	.same
	move.b	d0,(a0)
	move.b	d1,$ffff8800.w
	move.b	d0,$ffff8802.w
.same:	addq.l	#1,a0
	addq.b	#1,d1
	cmp.b	#11,d1
	blo.s	.w
	rts

; At the start: the slots empty, the YM silent.
snd_init:
	lea	snd_slots,a0
	move.w	#8*SL_SIZE/2-1,d0
.c:	clr.w	(a0)+
	dbf	d0,.c
	move.b	#$1F,snd_slots+6*SL_SIZE+SL_RMASK	; $4180: effect 0 every 32 IRQs
	move.l	#snd_e00,snd_slots+6*SL_SIZE+SL_RPROG
	move.b	#$07,snd_slots+7*SL_SIZE+SL_RMASK	; $4080: effect $0A every 8 IRQs
	move.l	#snd_e0A,snd_slots+7*SL_SIZE+SL_RPROG
	clr.b	snd_last
	clr.b	snd_count
	lea	snd_ym,a0
	lea	snd_silent,a1
	moveq	#0,d1
.y:	move.b	(a1)+,d0
	move.b	d0,(a0)+
	move.b	d1,$ffff8800.w
	move.b	d0,$ffff8802.w
	addq.b	#1,d1
	cmp.b	#11,d1
	blo.s	.y
	rts

; the YM silent (at the exit)
snd_off:
	moveq	#8,d0
.v:	move.b	d0,$ffff8800.w
	clr.b	$ffff8802.w
	addq.b	#1,d0
	cmp.b	#11,d0
	blo.s	.v
	rts

	even
snd_silent:
	dc.b	0,0,0,0,0,0,0,$FF,0,0,0,0

	even
	include	"sound_data.s"
	even

	section bss,bss
snd_slots:	ds.b	8*SL_SIZE
snd_buf:	ds.b	12
snd_ym:		ds.b	12		; the YM2149's registers 0-10 as written
snd_last:	ds.b	1		; the driver's $4002: the last latch value (0 at boot)
snd_count:	ds.b	1		; the driver's $4000 at the end of a tick
	even
	section text,code
