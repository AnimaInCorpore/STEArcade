; ------------------------------------------------------------------------------
;
; Sound: Junior's sound board as STE DMA sound, its discrete circuits on the YM
; (games/dkong/src/sound.s with Junior's ports, MAME 0.286 dkong_a.cpp dkongjr_audio)
;
; The 8035 (djr1-c_3h.3h) plays one mono stream through its DAC: the tunes selected
; by $7C00 (5 bits) and the effects on its pins $7C81, $7D03-$7D06 and its IRQ $7D80.
; Its output is recorded in MAME and converted to 8 bit PCM (tools/sound_capture.py,
; tools/sound_convert.py -> dkjr_sound.s), and this driver plays those clips on the DMA
; channel the way the 8035 sequences them (measured in MAME):
;
;   - a one-shot tune (07-0E: $608A, held 3 frames by the game) starts when $7C00
;     changes to it and plays to its end;
;   - a background tune (01-06: $6089) loops for as long as $7C00 holds it, and starts
;     again from its beginning after a one-shot;
;   - a rising edge on a pin starts that effect (the highest pin bit wins); the newest
;     sound wins.
;
; Walk ($7D00; $7D07 set: the circuit's second form), jump ($7D01), climb ($7D02) and
; fall ($7D81) are discrete circuits, independent of the 8035: YM channels A (walk and
; fall: Junior never walks while it falls), B, C, one (tone period, volume) a 50 Hz frame,
; measured from the MAME recordings (tools/sound_ym.py -> dkjr_ym.s).  A rising edge
; starts a patch; fall stops when $7D81 drops (the game holds it 41-48 frames).
;
; The game's own driver (Z80 $00E0, in the NMI) rewrites the ports every frame, so
; sound_update only compares them with the last frame.
;
; ------------------------------------------------------------------------------

SND_IDLE = 0
SND_SHOT = 1				; a one-shot clip: the DMA stops at its end
SND_LOOP = 2				; a background tune in repeat mode
SND_PINS = 6				; the 8035 effect pins

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

; bit 0 of the port at d(a6) into the low end of d0

pin_bit	macro
	move.b	\1(a6),d1
	lsr.b	#1,d1
	addx.b	d0,d0
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
	clr.b	ym_falling
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
	moveq	#$1f,d0
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
	beq.s	.leave			; silence (0, 0F-1F): a one-shot plays on
	move.l	(a1),d0
	moveq	#1,d2
	snd_start
	move.b	#SND_SHOT,snd_mode
	bra.s	.pins
.leave:	cmp.b	#SND_LOOP,snd_mode
	bne.s	.pins
	clr.b	$ffff8901.w
	clr.b	snd_mode

	; the pins: rising edges start the 8035 effects
.pins:	moveq	#0,d0			; the latches take bit 0 of the data
	pin_bit	$7d80			; bit 5
	pin_bit	$7c81			; bit 4
	pin_bit	$7d06			; bit 3
	pin_bit	$7d05			; bit 2
	pin_bit	$7d04			; bit 1
	pin_bit	$7d03			; bit 0
	move.b	snd_pins,d1
	move.b	d0,snd_pins
	not.b	d1
	and.b	d1,d0			; rising edges
	beq.s	.ended
	lea	sound_fx_table,a1	; the highest bit wins (the IRQ's sound over the rest)
	moveq	#SND_PINS-1,d1
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

; The YM channels.  A rising edge on $7D00 (walk, A; walk2 when $7D07 is set), $7D01 (jump,
; B), $7D02 (climb, C), $7D81 (fall, A) starts the patch; each frame writes its next
; (period, volume), and a frame of volume 0 after the last entry.  Fall ends early when
; $7D81 drops.

ym_update:
	moveq	#0,d0			; the latches take bit 0 of the data
	pin_bit	$7d81			; bit 3
	pin_bit	$7d02			; bit 2
	pin_bit	$7d01			; bit 1
	pin_bit	$7d00			; bit 0
	move.b	snd_disc,d1
	move.b	d0,snd_disc
	btst	#3,d0			; fall held?
	bne.s	.held
	tst.b	ym_falling
	beq.s	.held
	clr.b	ym_falling		; dropped: the silent frame next
	move	#1,ym_chan+4
.held:	not.b	d1
	and.b	d1,d0			; rising edges
	beq.s	.play
	lea	ym_patches,a0
	btst	#0,$7d07(a6)		; walk: the second form while $7D07 is set
	beq.s	.walk1
	lea	ym_patches2,a0
.walk1:	moveq	#0,d2			; patch index
.start:	lsr.b	#1,d0
	bcc.s	.no
	move.l	(a0),a2			; patch: dc.w frames, then (period, volume) each
	move	(a2)+,d3
	addq	#1,d3			; + the silent frame
	lea	ym_patch_chan,a1
	move.b	(a1,d2.w),d4
	ext	d4
	lea	ym_chan,a1
	add	d4,a1
	move.l	a2,(a1)
	move	d3,4(a1)
	tst	d4
	bne.s	.no
	cmp	#3,d2
	seq	ym_falling		; channel A: fall (cut when $7D81 drops) or walk
.no:	addq.l	#4,a0
	addq	#1,d2
	tst.b	d0
	bne.s	.start

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

ym_patch_chan:				; patch index -> offset of its channel record (A, B, C, A)
	dc.b	0,6,12,0
	even

	section data,data

ym_patches:				; by discrete bit: walk, jump, climb, fall
	dc.l	ym_walk,ym_jump,ym_climb,ym_fall
ym_patches2:				; the same with $7D07 set
	dc.l	ym_walk2,ym_jump,ym_climb,ym_fall
	include "dkjr_ym.s"
	even

sound_fx_table:				; by pin bit: start, end
	dc.l	snd_fx_7d03,snd_fx_7d03_end
	dc.l	snd_fx_7d04,snd_fx_7d04_end
	dc.l	snd_fx_7d05,snd_fx_7d05_end
	dc.l	snd_fx_7d06,snd_fx_7d06_end
	dc.l	snd_fx_7c81,snd_fx_7c81_end
	dc.l	snd_fx_irq,snd_fx_irq_end

	include "dkjr_sound.s"
	even

	section bss,bss

snd_mode:	ds.b	1
snd_pins:	ds.b	1
snd_latch:	ds.b	1
snd_disc:	ds.b	1
ym_falling:	ds.b	1		; channel A plays the fall patch
	even
ym_chan:	ds.b	6*3		; per channel: the next entry, frames left

	section text,code
