; ------------------------------------------------------------------------------
;
; Sound: the arcade's sound board (the M58715 MCU, a DAC and discrete circuits) as STE DMA sound
;
; The board's output is recorded in MAME and converted to 8 bit PCM (tools/sound_capture.py, tools/sound_convert.py ->
; mario_sound.s); this driver plays those clips on the DMA channel the way the game commands them:
;
;   - the game writes a tune number to $7E00 for three frames, then 0: a change to a number with a clip starts it, the
;     clip plays to its end, the newest command wins (the MCU does the same: it takes the latest number);
;   - a rising edge on bit 0 of $7F00-$7F07 (the death, get coin, ice, crab, turtle, fly, coin, skid) starts that
;     effect's clip, the newest wins.  $7F02 and the walk pulses ($7C00, $7C80) are silent in MAME's netlist.
;
; snd_frame runs once per arcade frame, before its NMI (the hook), reading the Z80 block the previous NMI wrote.
; One DMA stream plays at a time: overlapping effects are not mixed (the arcade's are).
;
; ------------------------------------------------------------------------------

	include	"mario_sound.s"

; Start a clip.  d0 = start, d1 = end (mm_sound relative), d2 = DMA control (1 once, 3 repeat)

snd_start	macro
	lea	mm_sound,a0
	add.l	a0,d0
	add.l	a0,d1
	lea	$ffff8900.w,a0
	movep.l	d0,1(a0)		; $8901 = 0 (stop), $8903/5/7 = frame start
	movep.l	d1,$d(a0)		; ($890d is the read-only counter), $890f/11/13 = frame end
	move.b	d2,1(a0)
	endm

	section text,code

snd_init:
	clr.b	$ffff8901.w
	move.b	#SOUND_MODE,$ffff8921.w
	ifnd SIM
	lea	snd_lmc(pc),a0		; LMC1992: 0 dB, flat, the YM mixed in
	moveq	#snd_lmc_end-snd_lmc-1,d1
	lsr	#1,d1
.mw:	move	(a0)+,d0
	bsr.s	microwire
	dbf	d1,.mw
	endc
	clr.b	snd_last
	lea	snd_pin,a0
	clr.l	(a0)+
	clr.l	(a0)
	move.b	#7,$ffff8800.w		; the YM silent (tones and noise off, volumes 0)
	move.b	$ffff8800.w,d0
	and.b	#$c0,d0
	or.b	#$3f,d0
	move.b	d0,$ffff8802.w
	moveq	#8,d0
.ym:	move.b	d0,$ffff8800.w
	clr.b	$ffff8802.w
	addq.b	#1,d0
	cmp.b	#11,d0
	blo.s	.ym
	rts

snd_lmc:	dc.w	%10011101000		; master volume 0 dB
	dc.w	%10101010100		; left 0 dB
	dc.w	%10100010100		; right 0 dB
	dc.w	%10010000110		; treble flat
	dc.w	%10001000110		; bass flat
	dc.w	%10000000001		; mix: YM + DMA
snd_lmc_end:

; d0 = one LMC1992 command (11 bits).  The mask register rotates while the 16 bits shift out (16 us) and reads $07FF
; again when done; its value before the first write is not defined, so the wait is after the write, and bounded.

microwire:
	move	#$07ff,$ffff8924.w
	move	d0,$ffff8922.w
	move	#999,d2
.busy:	cmp	#$07ff,$ffff8924.w
	dbeq	d2,.busy
	rts

; Once an arcade frame.  d0-d3/a0-a2 are used.

snd_frame:
	moveq	#0,d0
	move.b	G_Z80+$7E00,d0		; the tune number
	cmp.b	snd_last,d0
	beq.s	.pins
	move.b	d0,snd_last
	cmp.w	#40,d0
	bhs.s	.pins
	lsl.w	#3,d0
	lea	sound_tunes,a1
	add.w	d0,a1
	move.l	4(a1),d1
	beq.s	.pins			; (no clip: 0, a number the game does not send)
	move.l	(a1),d0
	moveq	#1,d2
	snd_start
.pins:	lea	snd_pin,a2
	lea	G_Z80+$7F00,a1
	lea	sound_fx,a3
	moveq	#7,d3
.fx:	moveq	#1,d0
	and.b	(a1,d3.w),d0		; the latch bit
	move.b	(a2,d3.w),d1
	move.b	d0,(a2,d3.w)
	cmp.b	d1,d0
	bls.s	.nx			; (no rising edge)
	move.w	d3,d0
	lsl.w	#3,d0
	move.l	4(a3,d0.w),d1
	beq.s	.nx
	move.l	(a3,d0.w),d0
	moveq	#1,d2
	move.l	a3,-(sp)
	snd_start
	move.l	(sp)+,a3
.nx:	dbf	d3,.fx
	rts

	section bss,bss
snd_pin:	ds.b	8
snd_last:	ds.b	1
	even
	section text,code
