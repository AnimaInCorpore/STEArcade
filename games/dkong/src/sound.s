; ------------------------------------------------------------------------------
;
; Sound: the arcade's 8035 sound board as STE DMA sound, its discrete circuits on the YM
;
; The 8035 plays one mono stream through its DAC: the tunes selected by $7C00 and the
; effects on the pins $7D03-$7D05 and the interrupt $7D80.  Its output is recorded in MAME
; and converted to 8 bit PCM (tools/sound_capture.py, tools/sound_convert.py -> dk_sound.s),
; and this driver plays those clips on the DMA channel the way the 8035 sequences them
; (measured in MAME):
;
;   - a one-shot tune starts when $7C00 changes to it and plays to its end (the game holds
;     it for 3 frames only, $608B);
;   - a background tune (03 04 08 09 0B) loops for as long as $7C00 holds it, and starts
;     again from its beginning after a one-shot;
;   - a rising edge on $7D03-$7D05 or $7D80 starts that effect; the newest sound wins.
;
; Walk, jump and stomp ($7D00-$7D02) are 555 / noise oscillators with RC envelopes on the
; arcade board, independent of the 8035 and of each other: each gets a YM channel (A, B, C)
; and a patch of one (tone period, volume) a frame, measured from the MAME recording
; (tools/sound_ym.py -> dk_ym.s); a rising edge restarts it.
;
; The game's own driver (Z80 $00E0, in the NMI) rewrites all these ports every frame, so
; sound_update only compares them with the last frame.
;
; ------------------------------------------------------------------------------

SND_IDLE = 0
SND_SHOT = 1				; a one-shot clip: the DMA stops at its end
SND_LOOP = 2				; a background tune in repeat mode

; Start a clip.  d0 = start, d1 = end (dk_sound relative), d2 = DMA control (1 once, 3 repeat)

snd_start	macro
	lea	dk_sound,a0
	add.l	a0,d0
	add.l	a0,d1
	lea	$ffff8900.w,a0
	movep.l	d0,1(a0)		; $8901 = 0 (stop), $8903/5/7 = frame start
	movep.l	d1,$d(a0)		; ($890d is the read-only counter), $890f/11/13 = frame end
	move.b	d2,1(a0)
	endm

init_sound:
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
	clr.b	snd_mode
	clr.b	snd_pins
	clr.b	snd_latch

	; YM: tones A B C on, noise off (bits 6 and 7, the I/O port directions, stay), silent.
	clr.b	snd_disc
	clr.w	ym_chan+4
	clr.w	ym_chan+6+4
	clr.w	ym_chan+12+4
	move.b	#7,$ffff8800.w
	move.b	$ffff8800.w,d0
	and.b	#$c0,d0
	or.b	#$38,d0
	move.b	d0,$ffff8802.w
ym_silence:
	move.b	#8,$ffff8800.w
	clr.b	$ffff8802.w
	move.b	#9,$ffff8800.w
	clr.b	$ffff8802.w
	move.b	#10,$ffff8800.w
	clr.b	$ffff8802.w
	rts

snd_lmc:	dc.w	%10011101000		; master volume 0 dB
	dc.w	%10101010100		; left 0 dB
	dc.w	%10100010100		; right 0 dB
	dc.w	%10010000110		; treble flat
	dc.w	%10001000110		; bass flat
	dc.w	%10000000001		; mix: YM + DMA
snd_lmc_end:

; d0 = one LMC1992 command (11 bits).  The mask register rotates while the 16 bits shift
; out (16 us) and reads $07FF again when done; its value before the first write is not
; defined, so the wait is after the write, and bounded.

microwire:
	move	#$07ff,$ffff8924.w
	move	d0,$ffff8922.w
	move	#999,d2
.busy:	cmp	#$07ff,$ffff8924.w
	dbeq	d2,.busy
	rts

stop_sound:
	clr.b	$ffff8901.w
	bra.s	ym_silence

; Once a frame after the Z80 NMI.  a6 = z80_block.  d0-d4/a0-a2 are used.

sound_update:
	bsr	ym_update

	; $7C00: a change to a one-shot tune starts it; leaving a background tune stops it.
	moveq	#$0f,d0
	and.b	$7c00(a6),d0
	cmp.b	snd_latch,d0
	beq.s	.pins
	move.b	d0,snd_latch
	mulu	#10,d0
	lea	sound_tunes,a1
	add	d0,a1
	tst	8(a1)
	bne.s	.leave
	move.l	4(a1),d1
	beq.s	.leave			; silence (0, 0A): a one-shot plays on
	move.l	(a1),d0
	moveq	#1,d2
	snd_start
	move.b	#SND_SHOT,snd_mode
	bra.s	.pins
.leave:	cmp.b	#SND_LOOP,snd_mode
	bne.s	.pins
	clr.b	$ffff8901.w
	clr.b	snd_mode

	; $7D03 $7D04 $7D05 $7D80: rising edges start the 8035 effects.
.pins:	moveq	#0,d0			; the latches take bit 0 of the data
	move.b	$7d80(a6),d1
	lsr.b	#1,d1
	addx.b	d0,d0
	move.b	$7d05(a6),d1
	lsr.b	#1,d1
	addx.b	d0,d0
	move.b	$7d04(a6),d1
	lsr.b	#1,d1
	addx.b	d0,d0
	move.b	$7d03(a6),d1
	lsr.b	#1,d1
	addx.b	d0,d0			; bit 0 $7D03 ... bit 3 $7D80
	move.b	snd_pins,d1
	move.b	d0,snd_pins
	not.b	d1
	and.b	d1,d0			; rising edges
	beq.s	.ended
	lea	sound_fx_table,a1	; the highest bit wins (the death sound over the rest)
	moveq	#3,d1
.fx:	btst	d1,d0
	dbne	d1,.fx
	lsl	#3,d1
	add	d1,a1
	move.l	(a1)+,d0
	move.l	(a1),d1
	moveq	#1,d2
	snd_start
	move.b	#SND_SHOT,snd_mode

	; A one-shot that ended gives the channel back to the background tune.
.ended:	cmp.b	#SND_SHOT,snd_mode
	bne.s	.idle
	btst	#0,$ffff8901.w
	bne.s	.done
	clr.b	snd_mode
.idle:	tst.b	snd_mode
	bne.s	.done
	moveq	#0,d0
	move.b	snd_latch,d0
	mulu	#10,d0
	lea	sound_tunes,a1
	add	d0,a1
	tst	8(a1)
	beq.s	.done
	move.l	(a1)+,d0
	move.l	(a1),d1
	moveq	#3,d2
	snd_start
	move.b	#SND_LOOP,snd_mode
.done:	rts

; The YM channels: a rising edge on $7D00 (walk, A), $7D01 (jump, B), $7D02 (stomp, C)
; starts the patch; each frame writes its next (period, volume), and a frame of volume 0
; after the last entry.

ym_update:
	moveq	#0,d0			; the latches take bit 0 of the data
	move.b	$7d02(a6),d1
	lsr.b	#1,d1
	addx.b	d0,d0
	move.b	$7d01(a6),d1
	lsr.b	#1,d1
	addx.b	d0,d0
	move.b	$7d00(a6),d1
	lsr.b	#1,d1
	addx.b	d0,d0			; bit 0 walk, bit 1 jump, bit 2 stomp
	move.b	snd_disc,d1
	move.b	d0,snd_disc
	not.b	d1
	and.b	d1,d0			; rising edges
	beq.s	.play
	lea	ym_chan,a1
	lea	ym_patches,a0
	moveq	#2,d2
.start:	lsr.b	#1,d0
	bcc.s	.no
	move.l	(a0),a2			; patch: dc.w frames, then (period, volume) each
	move	(a2)+,d3
	addq	#1,d3			; + the silent frame
	move.l	a2,(a1)
	move	d3,4(a1)
.no:	addq.l	#4,a0
	addq.l	#6,a1
	dbf	d2,.start

.play:	lea	ym_chan,a1
	moveq	#0,d2			; channel
.ch:	move	4(a1),d3		; frames left (with the silent one)
	beq.s	.next
	subq	#1,d3
	move	d3,4(a1)
	beq.s	.off
	move.l	(a1),a0
	move	(a0)+,d0		; tone period
	move	(a0)+,d1		; volume
	move.l	a0,(a1)
	move	d2,d4
	add	d4,d4
	move.b	d4,$ffff8800.w		; fine period
	move.b	d0,$ffff8802.w
	addq	#1,d4
	lsr	#8,d0
	move.b	d4,$ffff8800.w		; coarse period
	move.b	d0,$ffff8802.w
	bra.s	.vol
.off:	moveq	#0,d1
.vol:	moveq	#8,d4
	add	d2,d4
	move.b	d4,$ffff8800.w
	move.b	d1,$ffff8802.w
.next:	addq.l	#6,a1
	addq	#1,d2
	cmp	#3,d2
	bne.s	.ch
	rts

	section data,data

ym_patches:
	dc.l	ym_walk,ym_jump,ym_stomp
	include "dk_ym.s"
	even

sound_fx_table:				; by pin bit: start, end
	dc.l	snd_fx_coin_spring,snd_fx_coin_spring_end
	dc.l	snd_fx_gorilla_fall,snd_fx_gorilla_fall_end
	dc.l	snd_fx_barrel_prize,snd_fx_barrel_prize_end
	dc.l	snd_fx_death,snd_fx_death_end

	include "dk_sound.s"
	even

	section bss,bss

snd_mode:	ds.b	1
snd_pins:	ds.b	1
snd_latch:	ds.b	1
snd_disc:	ds.b	1
	even
ym_chan:	ds.b	6*3		; per channel: the next entry, frames left

	section text,code
