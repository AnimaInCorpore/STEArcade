; The sound: the ADPCM samples (the punches, kicks, shouts: commands $80-$9A) on the STE's DMA sound; the YM2151 music
; and effects are not played yet.
;
; The driver's ADPCM part (21j-0-1 $88E5, its table at $8966: per command the chip (bit 0: 1 chip 0, else chip 1), the
; start and the end, >> 1 in 512-byte units): a command stops its chip and starts the sample there (every priority is
; 0).  Each MSM5205 is decoded here as MAME does (msm5205.cpp: the 12-bit signal, the step table, the high nibble of
; a byte first, reset (signal and step 0) when the sample ends), 7812.5 samples a second, the two mixed into a looping
; DMA buffer at 6258 Hz (mono), filled in the VBL up to where the DMA reads.
SND_BUF = 1024				; samples (bytes): the looping DMA buffer
SND_RATIO = 81815			; 7812.5 / 6258 in 16.16
V_POS = 0				; the next byte's address
V_END = 4
V_ACC = 8				; the 16.16 fraction of a sample
V_SIG = 12				; the signal (word)
V_STEP = 14				; the step index (word)
V_BYTE = 16				; the byte being played (its low nibble next when V_HALF is set)
V_HALF = 17
V_ON = 18
V_SIZE = 20

	section text,code
snd_init:
	lea snd_buf,a0
	move.w #SND_BUF/4-1,d0
.c:	clr.l (a0)+
	dbf d0,.c
	clr.w snd_wpos
	ifnd SIM
	move.l #snd_buf,d0
	move.b d0,$ffff8907.w		; the frame's start (low, mid, high)
	lsr.l #8,d0
	move.b d0,$ffff8905.w
	lsr.l #8,d0
	move.b d0,$ffff8903.w
	move.l #snd_buf+SND_BUF,d0
	move.b d0,$ffff8913.w		; its end
	lsr.l #8,d0
	move.b d0,$ffff8911.w
	lsr.l #8,d0
	move.b d0,$ffff890f.w
	move.b #$80,$ffff8921.w		; mono, 6258 Hz
	move.b #$03,$ffff8901.w		; play, loop
	endc
	rts

snd_off:
	ifnd SIM
	clr.b $ffff8901.w
	endc
	rts

snd_vbl:
	rts

; snd_frame (once an arcade frame): the commands the program sent (core.s's ring) started, the buffer filled.
snd_frame:
	movem.l d0-d7/a0-a4,-(sp)
.cmd:	moveq #0,d0
	move.b snd_tail,d0
	cmp.b snd_head,d0
	beq .fill
	lea snd_ring,a0
	move.b (a0,d0.w),d1
	addq.b #1,snd_tail
	cmp.b #$80,d1
	blo.s .cmd
	cmp.b #$9B,d1
	bhs.s .cmd
	and.w #$7F,d1			; an ADPCM sample
	move.w d1,d2
	add.w d1,d1
	add.w d2,d1
	lea adpcm_table,a0
	add.w d1,a0
	lea voice1,a1			; (bit 0 clear: chip 1)
	lea adpcm_rom+$10000,a2
	btst #0,(a0)
	beq.s .v
	lea voice0,a1
	lea adpcm_rom,a2
.v:	moveq #0,d1
	move.b 1(a0),d1
	lsr.b #1,d1
	and.w #$7F,d1
	lsl.w #8,d1
	add.l d1,d1			; (start >> 1) << 9
	lea (a2,d1.l),a3
	move.l a3,V_POS(a1)
	moveq #0,d1
	move.b 2(a0),d1
	lsr.b #1,d1
	and.w #$7F,d1
	lsl.w #8,d1
	add.l d1,d1
	lea (a2,d1.l),a3
	move.l a3,V_END(a1)
	clr.l V_ACC(a1)
	clr.l V_SIG(a1)			; (signal and step)
	clr.b V_HALF(a1)
	st V_ON(a1)
	bra .cmd
.fill:
	ifd SIM
	move.w #126,d7			; (no DMA: a VBL's worth)
	else
	moveq #0,d0			; the DMA's read position
	move.b $ffff8909.w,d0
	swap d0
	move.b $ffff890b.w,d0
	lsl.w #8,d0
	move.b $ffff890d.w,d0
	sub.l #snd_buf,d0
	sub.w #16,d0			; (a margin)
	sub.w snd_wpos,d0
	and.w #SND_BUF-1,d0
	move.w d0,d7			; samples to write
	endc
	beq.s .done
	subq.w #1,d7
	lea snd_buf,a4
	move.w snd_wpos,d6
	lea msm_diff,a2
	lea msm_shift,a3
	tst.b voice0+V_ON
	bne.s .loop
	tst.b voice1+V_ON
	bne.s .loop
.zero:	clr.b (a4,d6.w)			; (both idle: silence)
	addq.w #1,d6
	and.w #SND_BUF-1,d6
	dbf d7,.zero
	bra.s .end
.loop:	lea voice0,a1
	bsr.s voice_step
	move.w d0,d5
	lea voice1,a1
	bsr.s voice_step
	add.w d5,d0
	asr.w #5,d0			; (two 12-bit signals: 8 bits)
	cmp.w #127,d0
	ble.s .hi
	moveq #127,d0
.hi:	cmp.w #-128,d0
	bge.s .lo
	moveq #-128,d0
.lo:	move.b d0,(a4,d6.w)
	addq.w #1,d6
	and.w #SND_BUF-1,d6
	dbf d7,.loop
.end:	move.w d6,snd_wpos
.done:	movem.l (sp)+,d0-d7/a0-a4
	rts

; voice_step: voice a1 by one output sample (its 7812.5 Hz samples that fall in it decoded) -> d0.w its signal.
; Uses d0-d4, a0.
voice_step:
	tst.b V_ON(a1)
	beq .off
	move.l V_ACC(a1),d1
	add.l #SND_RATIO,d1
.dec:	cmp.l #$10000,d1
	blo .out
	sub.l #$10000,d1
	; the MSM5205's sample: a nibble, or the end
	tst.b V_HALF(a1)
	bne.s .low
	move.l V_POS(a1),a0
	cmp.l V_END(a1),a0
	bhs.s .stop
	move.b (a0)+,d2
	move.l a0,V_POS(a1)
	move.b d2,V_BYTE(a1)
	lsr.b #4,d2
	st V_HALF(a1)
	bra.s .nib
.low:	moveq #15,d2
	and.b V_BYTE(a1),d2
	clr.b V_HALF(a1)
.nib:	and.w #15,d2
	move.w V_STEP(a1),d3
	lsl.w #4,d3
	add.w d2,d3
	add.w d3,d3
	move.w (a2,d3.w),d3		; diff_lookup[step * 16 + nibble]
	move.w V_SIG(a1),d4
	add.w d3,d4
	cmp.w #2047,d4
	ble.s .s1
	move.w #2047,d4
.s1:	cmp.w #-2048,d4
	bge.s .s2
	move.w #-2048,d4
.s2:	move.w d4,V_SIG(a1)
	and.w #7,d2
	move.b (a3,d2.w),d3
	ext.w d3
	add.w V_STEP(a1),d3
	bpl.s .s3
	moveq #0,d3
.s3:	cmp.w #48,d3
	ble.s .s4
	moveq #48,d3
.s4:	move.w d3,V_STEP(a1)
	bra .dec
.out:	move.l d1,V_ACC(a1)
	move.w V_SIG(a1),d0
	rts
.stop:	clr.b V_ON(a1)
	clr.l V_SIG(a1)
.off:	moveq #0,d0
	rts

	section data,data
	even
adpcm_table:	incbin "adpcm_table.bin"	; (the driver's $8966: 27 commands x 3 bytes)
	even
msm_diff:	incbin "msm_diff.bin"		; (49 x 16 words: MAME's diff_lookup)
msm_shift:	dc.b -1,-1,-1,-1,2,4,6,8
	even
adpcm_rom:	incbin "adpcm.bin"		; (21j-6, 21j-7: 64 KB each)

	section bss,bss
	even
voice0:		ds.b V_SIZE
voice1:		ds.b V_SIZE
snd_wpos:	ds.w 1
snd_buf:	ds.b SND_BUF
	section text,code
