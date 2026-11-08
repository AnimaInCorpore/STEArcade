; ------------------------------------------------------------------------------
;
; Sound: the arcade's two sound CPUs (N2A03s: a 6502 with the NES sound generator) as STE DMA sound
;
; The board's output is recorded in MAME and converted to 8 bit PCM (tools/sound_capture.py, tools/sound_convert.py ->
; dkong3_sound.s): each value the game sends to a sound latch has a clip, recorded with that value alone (the other
; latches 0).  The first N2A03 reads latch 1 ($7C00) and latch 2 ($7C80), the second latch 3 ($7D00); the driver has one
; voice for each CPU and plays the clips the game commands on them:
;
;   - a changed latch value with a clip starts that clip on the CPU's voice (the newest on a voice wins);
;   - a clip marked "hold" (the CPU plays it while the value stays: the tunes) loops from its loop point to its end and
;     stops when the latch changes to a value without a clip, 0 in practice; the other clips play to their end.
;
; The two voices are added (the clips are scaled for it: 6 dB of headroom) into a ring buffer that the DMA plays
; (6258 Hz mono, repeating); every VBL snd_mix brings the ring up to the DMA's position plus SND_LEAD bytes.  snd_frame
; runs once per arcade frame, before its NMI (the hook), reading the Z80 block the previous NMI wrote, and queues the
; commands for snd_mix (the VBL).
;
; ------------------------------------------------------------------------------

	include	"dkong3_sound.s"

SND_RING = 2048				; the ring (bytes: 327 ms)
SND_LEAD = 384				; the samples ready ahead of the DMA's position (61 ms; the VBL comes every 20 ms)
SND_QLEN = 16				; commands queued
SND_VOICES = 6				; a tune and an effect for each latch

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
	lea	snd_vars,a0		; the state: voices stopped, queues empty
	moveq	#(snd_vars_end-snd_vars)/2-1,d0
.cl:	clr.w	(a0)+
	dbf	d0,.cl
	lea	snd_ring,a0		; the ring silent, the DMA looping over it
	move.w	#SND_RING/4-1,d0
.rg:	clr.l	(a0)+
	dbf	d0,.rg
	move.l	#snd_ring,d0
	move.l	d0,-(sp)
	move.b	1(sp),$ffff8903.w
	move.b	2(sp),$ffff8905.w
	move.b	3(sp),$ffff8907.w
	add.l	#SND_RING,d0
	move.l	d0,(sp)
	move.b	1(sp),$ffff890f.w
	move.b	2(sp),$ffff8911.w
	move.b	3(sp),$ffff8913.w
	addq.l	#4,sp
	move.w	#SND_LEAD,snd_wp
	move.b	#3,$ffff8901.w		; play, repeating
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

; ------------------------------------------------------------------------------
; snd_frame, once an arcade frame (the hook): the latches' changes into commands for the voices (d0-d3/a0-a1 used).
; A command is a word, voice << 8 | clip (0: stop the voice): voice 2k the tune of latch k + 1, 2k + 1 its effect.
; ------------------------------------------------------------------------------

snd_latch	macro			; \1 = k (0-2), \2 = the latch's Z80 address, \3 / \4 = its tune / effect tables
	moveq	#0,d0
	move.b	G_Z80+\2,d0
	cmp.b	snd_last+\1,d0
	beq.s	.same\@
	move.b	d0,snd_last+\1
	lea	\3,a0
	move.b	(a0,d0.w),d1		; the tune this value holds (0: none)
	cmp.b	snd_lh+\1,d1
	beq.s	.eff\@
	move.b	d1,snd_lh+\1
	move.w	#(\1*2)<<8,d2
	or.b	d1,d2
	bsr	snd_queue
.eff\@:	lea	\4,a0
	move.b	(a0,d0.w),d1		; the effect it starts (0: none)
	cmp.b	snd_le+\1,d1
	beq.s	.same\@
	move.b	d1,snd_le+\1
	tst.b	d1
	beq.s	.same\@
	move.w	#((\1*2)+1)<<8,d2
	or.b	d1,d2
	bsr	snd_queue
.same\@:
	endm

snd_frame:
	snd_latch 0,$7C00,snd_hold1,snd_eff1
	snd_latch 1,$7C80,snd_hold2,snd_eff2
	snd_latch 2,$7D00,snd_hold3,snd_eff3
	rts

snd_queue:				; d2 = the command
	moveq	#0,d3
	move.b	snd_qt,d3
	lea	snd_q,a1
	move.w	d2,(a1,d3.w)
	addq.b	#2,d3
	and.b	#SND_QLEN*2-1,d3
	move.b	d3,snd_qt		; (the VBL sees the command once the tail moved)
	rts

; ------------------------------------------------------------------------------
; snd_mix, every VBL: the queued commands start and stop voices; the ring is filled up to the DMA's position plus SND_LEAD
; with the voices added (saturating); the voices' pointers advance (a tune loops, an effect ends).
; ------------------------------------------------------------------------------

snd_mix:
	movem.l	d0-d7/a0-a5,-(sp)
	lea	snd_q,a1
	moveq	#0,d3
	move.b	snd_qh,d3
.cmd:	cmp.b	snd_qt,d3
	beq.s	.cmds
	move.w	(a1,d3.w),d2
	addq.b	#2,d3
	and.b	#SND_QLEN*2-1,d3
	moveq	#0,d0
	move.b	d2,d0			; the clip
	moveq	#0,d1
	move.w	d2,d1
	lsr.w	#8,d1			; the voice
	mulu	#12,d1
	lea	snd_voices,a0
	add.w	d1,a0
	tst.w	d0
	beq.s	.stop
	mulu	#12,d0
	lea	snd_clips,a2
	add.w	d0,a2
	lea	dk_sound,a3
	move.l	(a2)+,d4		; start
	add.l	a3,d4
	move.l	d4,(a0)
	move.l	(a2)+,d5		; end
	add.l	a3,d5
	move.l	d5,4(a0)
	tst.l	(a2)			; loops
	beq.s	.nolp
	move.l	d4,8(a0)
	bra.s	.cmd
.nolp:	clr.l	8(a0)
	bra.s	.cmd
.stop:	clr.l	(a0)
	bra.s	.cmd
.cmds:	move.b	d3,snd_qh
.rd:	moveq	#0,d0			; the DMA's address, read twice until it is stable
	move.b	$ffff8909.w,d0
	lsl.l	#8,d0
	move.b	$ffff890b.w,d0
	lsl.l	#8,d0
	move.b	$ffff890d.w,d0
	moveq	#0,d1
	move.b	$ffff8909.w,d1
	lsl.l	#8,d1
	move.b	$ffff890b.w,d1
	lsl.l	#8,d1
	move.b	$ffff890d.w,d1
	cmp.l	d0,d1
	bne.s	.rd
	sub.l	#snd_ring,d0
	add.w	#SND_LEAD,d0
	and.w	#SND_RING-4,d0		; the target: the DMA's position + the lead
	move.w	snd_wp,d1
	move.w	d0,d2
	sub.w	d1,d2
	and.w	#SND_RING-4,d2		; the bytes to mix
	cmp.w	#SND_RING/2,d2
	bls.s	.n_ok
	move.w	d0,d1			; (behind, or the DMA passed us: the lead again)
	sub.w	#SND_LEAD,d1
	and.w	#SND_RING-4,d1
	move.w	#SND_LEAD,d2
.n_ok:	move.w	d0,snd_wp
	tst.w	d2
	beq	.out
	lea	snd_mixbuf,a4		; the voices added into a silent buffer
	move.w	d2,d0
	lsr.w	#2,d0
	subq.w	#1,d0
	moveq	#0,d3
.clr:	move.l	d3,(a4)+
	dbf	d0,.clr
	move.w	d1,-(sp)		; (the ring offset to mix at: the sample loop uses d1)
	lea	snd_voices,a5
	moveq	#SND_VOICES-1,d6
.v:	move.l	(a5),d0
	beq	.nv
	move.l	d0,a0
	move.l	4(a5),a3
	move.l	8(a5),d5		; the loop start (0: none)
	lea	snd_mixbuf,a4
	moveq	#0,d4
	move.w	d2,d4			; the samples still to add
.chunk:	move.l	a3,d0
	sub.l	a0,d0			; the clip's bytes left
	cmp.l	d4,d0
	bhs.s	.rem
	move.l	d0,d7
	bra.s	.go
.rem:	move.l	d4,d7
.go:	sub.l	d7,d4
	subq.w	#1,d7
	bmi.s	.after
.s:	move.b	(a0)+,d1
	move.b	(a4),d0
	add.b	d1,d0
	bvc.s	.ok
	bmi.s	.hi
	move.b	#$80,d0
	bra.s	.ok
.hi:	move.b	#$7f,d0
.ok:	move.b	d0,(a4)+
	dbf	d7,.s
.after:	cmp.l	a3,a0
	blo.s	.save
	tst.l	d5
	beq.s	.off
	move.l	d5,a0
.save:	tst.l	d4
	bne.s	.chunk
	move.l	a0,(a5)
	bra.s	.nv
.off:	clr.l	(a5)
.nv:	lea	12(a5),a5
	dbf	d6,.v
	move.w	(sp)+,d1
	lea	snd_ring,a1		; the buffer into the ring at d1, wrapping
	add.w	d1,a1
	lea	snd_mixbuf,a4
	move.w	#SND_RING,d3
	sub.w	d1,d3			; the bytes to the ring's end
	cmp.w	d2,d3
	bhs.s	.one
	move.w	d3,d0
	lsr.w	#2,d0
	subq.w	#1,d0
.c1:	move.l	(a4)+,(a1)+
	dbf	d0,.c1
	sub.w	d3,d2
	lea	snd_ring,a1
.one:	move.w	d2,d0
	lsr.w	#2,d0
	subq.w	#1,d0
	bmi.s	.out
.c2:	move.l	(a4)+,(a1)+
	dbf	d0,.c2
.out:	movem.l	(sp)+,d0-d7/a0-a5
	rts

	section bss,bss
	even
snd_vars:
snd_wp:		ds.w	1
snd_last:	ds.b	4		; the latches' last values
snd_lh:		ds.b	4		; the tune clip each latch holds
snd_le:		ds.b	4		; the effect clip its value started last
snd_qh:		ds.b	1
snd_qt:		ds.b	1
snd_q:		ds.w	SND_QLEN
snd_voices:	ds.l	3*SND_VOICES	; per voice: pointer (0: silent), end, loop start (0: none)
snd_vars_end:
	even
snd_mixbuf:	ds.b	SND_RING/2
snd_ring:	ds.b	SND_RING
	section text,code
