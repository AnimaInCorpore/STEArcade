; ------------------------------------------------------------------------------
;
; Sound: the arcade's sound board (a Z80 with an SN76489A, a DAC and a VLM5030) as STE DMA sound
;
; The board's output is recorded in MAME, one clip a command (tools/sound_capture.py, tools/sound_convert.py ->
; sb_sound.s) and played on the DMA channel the way the game commands it (after Mario Bros.' src/sound.s):
;
;   - the main CPU writes a command to $3D00 and then the trigger $3D80 (main_io_w puts each command into snd_ring):
;     0 stops the clip; 1-$7F start that effect's clip (a looping one, $09 and $20, repeats until the next command),
;     the newest command wins; $80-$FE (the phrases) are queued: the last one waits, and $FF speaks it;
;   - an effect or a phrase without a clip (the board makes no sound for it) is ignored.
;
; snd_frame runs once per arcade frame, before the IRQ that the idle point delivers, and takes the commands the
; ring got since.  One DMA stream plays at a time: overlapping effects are not mixed (the board's are), and a queue of
; several phrases is spoken as its last.  The Z80 itself is not run (README, Sound).
;
; ------------------------------------------------------------------------------

	include	"sb_sound.s"

; Start a clip.  d0 = start, d1 = end (sb_sound relative), d2 = DMA control (1 once, 3 repeat)

snd_start	macro
	lea	sb_sound,a0
	add.l	a0,d0
	add.l	a0,d1
	lea	$ffff8900.w,a0
	clr.b	1(a0)			; (stopped while the addresses change)
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
	clr.b	snd_tail
	clr.b	snd_pend
	ifd DEBUG
	move.l	#snd_log,snd_log_p
	endc
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

; Once an arcade frame: the commands since the last one, in order.  Every register may be used (the caller saved them).

snd_frame:
	moveq	#0,d3
	move.b	snd_tail,d3
.l:	cmp.b	snd_head,d3
	beq.s	.done
	lea	snd_ring,a1
	moveq	#0,d0
	move.b	(a1,d3.w),d0
	addq.b	#1,d3
	ifd DEBUG			; SNDLOG.BIN: (the VBL, the command) words
	move.l	snd_log_p,a0
	cmp.l	#snd_log+4096,a0
	bhs.s	.nolog
	move.w	frame_counter+2,(a0)+
	move.w	d0,(a0)+
	move.l	a0,snd_log_p
.nolog:
	endc
	move.w	d3,-(sp)
	bsr.s	snd_cmd
	move.w	(sp)+,d3
	bra.s	.l
.done:	move.b	d3,snd_tail
	rts

; d0.w = a command
snd_cmd:
	tst.b	d0
	beq.s	.stop
	cmp.b	#$ff,d0
	beq.s	.speak
	cmp.b	#$80,d0
	bhs.s	.phrase
.start:	move.w	d0,d1			; the clip's record: 12 bytes a command
	lsl.w	#2,d1
	lsl.w	#3,d0
	add.w	d1,d0
	lea	sound_cmds,a2
	add.w	d0,a2
	move.l	4(a2),d1
	beq.s	.out			; (no clip)
	move.l	8(a2),d2
	move.l	(a2),d0
	snd_start
.out:	rts
.stop:	clr.b	$ffff8901.w
	rts
.phrase:
	move.w	d0,d1			; a phrase with a clip waits for the $FF
	lsl.w	#2,d1
	lea	sound_cmds,a2
	move.w	d0,d2
	lsl.w	#3,d2
	add.w	d2,d1
	add.w	d1,a2
	tst.l	4(a2)
	beq.s	.out
	move.b	d0,snd_pend
	rts
.speak:	moveq	#0,d0
	move.b	snd_pend,d0
	beq.s	.out
	clr.b	snd_pend
	bra.s	.start

	section bss,bss
snd_tail:	ds.b	1
snd_pend:	ds.b	1
	even
	section text,code
