; Yie Ar Kung-Fu's sound on the STE (included by yiear.s; tools/sound.py is the same in Python, tools/sound_test.py
; compares): the main CPU's NMI handler writes the SN76489A through $4800 / $4900 (main_io_w calls snd_sn_w: the byte
; into an emulated register file), and once an arcade frame snd_ym puts its four voices (three tones and the noise) on
; the YM2149's three channels (the three loudest, a voice keeping its YM channel while it lasts: Mr. Do!'s method; the
; method and snd_ym are Track & Field's).  The VLM5030's phrases were rendered offline (tools/sndgen.py) and play on the
; DMA sound (12517 Hz, 8 bits, mono) when ST falls (vlm_control -> snd_phrase); RST rising while busy stops them.

	include	"snd_data.s"

	section text,code

snd_init:
	movem.l	d0-d7/a0-a6,-(sp)
	lea	snd_sn,a0		; (8 words: periods 0, 2, 4, the noise control 6; volumes 1, 3, 5, 7: MAME's reset, 0)
	moveq	#8-1,d0
.s:	clr.w	(a0)+
	dbf	d0,.s
	clr.b	snd_sn_latch
	st	snd_dirty
	lea	snd_ym_cache,a0
	moveq	#16-1,d0
.y:	move.b	#$FF,(a0)+
	dbf	d0,.y
	move.l	#-1,snd_ymch		; (no voice on the YM's three: -1 bytes)
	bsr	snd_ym			; (silent)
	ifnd SIM
	clr.b	$ffff8901.w
	endc
	movem.l	(sp)+,d0-d7/a0-a6
	rts

; snd_sn_w: d5.b = the byte written to the SN76489A, into its registers (MAME sn76496_base_device::write).  Registers
; kept (d7 and a0 too).
snd_sn_w:
	movem.l	d1-d2/d7/a0,-(sp)
	st	snd_dirty
	move.b	d5,d1
	bpl.s	.data
	moveq	#$70,d7			; a latch byte: the register, its low 4 bits
	and.b	d1,d7
	lsr.b	#4,d7
	move.b	d7,snd_sn_latch
.low:	ext.w	d7
	add.w	d7,d7
	lea	snd_sn,a0
	moveq	#$0F,d2
	and.b	d1,d2
	and.w	#$3F0,(a0,d7.w)
	or.w	d2,(a0,d7.w)
	movem.l	(sp)+,d1-d2/d7/a0
	rts
.data:	moveq	#0,d7
	move.b	snd_sn_latch,d7		; a data byte: the latched register
	btst	#0,d7
	bne.s	.low			; (a volume: its low 4 bits)
	cmp.b	#6,d7
	beq.s	.low			; (the noise control: the same)
	add.w	d7,d7			; a period: bits 4-9
	lea	snd_sn,a0
	moveq	#$3F,d2
	and.b	d1,d2
	lsl.w	#4,d2
	and.w	#$0F,(a0,d7.w)
	or.w	d2,(a0,d7.w)
	movem.l	(sp)+,d1-d2/d7/a0
	rts

; snd_phrase: d0.b = the VLM's data byte, the phrase's samples (snd_phr_tab: offset, length; 0: none) on the DMA sound.
snd_phrase:
	movem.l	d0-d1/a0,-(sp)
	and.w	#$FF,d0
	move.w	d0,snd_dma_last
	ifnd SIM
	clr.b	$ffff8901.w		; (stopped; a new start sets the addresses)
	lsl.w	#3,d0
	lea	snd_phr_tab,a0
	move.l	4(a0,d0.w),d1		; the length (0: none)
	beq.s	.x
	move.l	(a0,d0.w),d0		; the offset
	add.l	#snd_pcm,d0
	add.l	d0,d1
	move.l	d0,-(sp)
	move.b	1(sp),$ffff8903.w
	move.b	2(sp),$ffff8905.w
	move.b	3(sp),$ffff8907.w
	move.l	d1,(sp)
	move.b	1(sp),$ffff890f.w
	move.b	2(sp),$ffff8911.w
	move.b	3(sp),$ffff8913.w
	addq.l	#4,sp
	move.b	#$81,$ffff8921.w	; mono, 12517 Hz
	move.b	#1,$ffff8901.w		; play once
.x:
	endc
	movem.l	(sp)+,d0-d1/a0
	rts

snd_stop:
	ifnd SIM
	clr.b	$ffff8901.w
	endc
	move.w	#-1,snd_dma_last
	rts

; ---- snd_ym: the YM's registers from the SN's (sound.py YM).  A voice's key: (16 - attenuation) * 8 + 7 - voice (0:
; silent); the three best in d2 > d3 > d4.

SND_KEY	macro				; \1 the voice (0-3): its attenuation at snd_sn + 4 * \1 + 2
	moveq	#$0F,d1
	and.w	4*\1+2(a0),d1
	cmp.w	#15,d1
	beq.s	.n\@
	moveq	#16,d0
	sub.w	d1,d0
	lsl.w	#3,d0
	addq.w	#7-\1,d0
	cmp.w	d4,d0
	bls.s	.n\@
	cmp.w	d3,d0
	bhi.s	.g2\@
	move.w	d0,d4
	bra.s	.n\@
.g2\@:	move.w	d3,d4
	cmp.w	d2,d0
	bhi.s	.g1\@
	move.w	d0,d3
	bra.s	.n\@
.g1\@:	move.w	d2,d3
	move.w	d0,d2
.n\@:
	endm

SND_PICK macro				; \1 a key register -> d0.b its voice (-1: none)
	moveq	#-1,d0
	tst.w	\1
	beq.s	.p\@
	moveq	#7,d1
	and.w	\1,d1
	moveq	#7,d0
	sub.w	d1,d0
.p\@:
	endm

SND_YMW	macro				; \1 a YM register: written if it changed
	move.b	\1(a2),d1
	cmp.b	\1(a1),d1
	beq.s	.s\@
	move.b	d1,\1(a1)
	ifnd SIM
	move.b	#\1,$ffff8800.w
	move.b	d1,$ffff8802.w
	endc
	addq.w	#1,snd_ym_writes
.s\@:
	endm

snd_ym:
	clr.b	snd_dirty
	lea	snd_sn,a0
	moveq	#0,d2
	moveq	#0,d3
	moveq	#0,d4
	SND_KEY	0
	SND_KEY	1
	SND_KEY	2
	SND_KEY	3
	lea	snd_pick,a2
	SND_PICK d2
	move.b	d0,(a2)
	SND_PICK d3
	move.b	d0,1(a2)
	SND_PICK d4
	move.b	d0,2(a2)
	; the YM channels: one that holds a chosen voice keeps it; the others take the remaining ones in order
	lea	snd_ymch,a3
	lea	snd_newch,a4
	move.b	#-1,(a4)
	move.b	#-1,1(a4)
	move.b	#-1,2(a4)
	moveq	#2,d6
.keep:	move.b	(a2,d6.w),d0
	bmi.s	.kn
	moveq	#2,d5
.kc:	cmp.b	(a3,d5.w),d0
	beq.s	.kp
	dbf	d5,.kc
	bra.s	.kn
.kp:	move.b	d0,(a4,d5.w)		; (kept on YM channel d5)
	st	(a2,d6.w)		; (placed)
.kn:	dbf	d6,.keep
	moveq	#0,d6			; the rest, in order of loudness, into the free YM channels from 0
.fill:	move.b	(a2,d6.w),d0
	bmi.s	.fn
	moveq	#0,d5
.ff:	tst.b	(a4,d5.w)
	bpl.s	.fx
	move.b	d0,(a4,d5.w)
	bra.s	.fn
.fx:	addq.w	#1,d5
	bra.s	.ff
.fn:	addq.w	#1,d6
	cmp.w	#3,d6
	blo.s	.fill
	move.b	(a4),(a3)
	move.b	1(a4),1(a3)
	move.b	2(a4),2(a3)
	; the YM's registers into snd_ym_new
	lea	snd_ym_new,a2
	clr.l	(a2)
	clr.l	4(a2)
	clr.l	8(a2)
	clr.l	12(a2)
	lea	snd_ptab,a4
	lea	snd_vtab,a5
	moveq	#$3F,d7			; the mixer: all off
	moveq	#0,d6			; the YM channel
.ych:	moveq	#0,d0
	move.b	(a3,d6.w),d0
	bmi.s	.yn
	lsl.w	#2,d0
	lea	(a0,d0.w),a1		; the voice's period (word 2k), its attenuation 2 further
	cmp.w	#12,d0
	beq.s	.noise
	move.w	(a1),d2			; the period (10 bits), scaled
	add.w	d2,d2
	move.w	(a4,d2.w),d2
	move.w	d6,d1
	add.w	d1,d1
	move.b	d2,(a2,d1.w)
	lsr.w	#8,d2
	move.b	d2,1(a2,d1.w)
	bclr	d6,d7			; tone on
	bra.s	.vol
.noise:	addq.w	#3,d6			; noise on (the tone stays off)
	bclr	d6,d7
	subq.w	#3,d6
	moveq	#31,d2			; the noise period: 31 but for mode 3 with tone 2's period below 16
	moveq	#3,d1
	and.w	12(a0),d1
	cmp.w	#3,d1
	bne.s	.np
	move.w	8(a0),d1
	cmp.w	#16,d1
	bhs.s	.np
	lea	snd_ntab,a1
	move.b	(a1,d1.w),d2
	lea	12(a0),a1
.np:	move.b	d2,6(a2)
.vol:	moveq	#$0F,d1			; the level
	and.w	2(a1),d1
	move.b	(a5,d1.w),8(a2,d6.w)
.yn:	addq.w	#1,d6
	cmp.w	#3,d6
	blo.s	.ych
	or.b	#$C0,d7			; (bits 6 / 7: the STE's ports A and B stay outputs)
	move.b	d7,7(a2)
	lea	snd_ym_cache,a1
	SND_YMW	0
	SND_YMW	1
	SND_YMW	2
	SND_YMW	3
	SND_YMW	4
	SND_YMW	5
	SND_YMW	6
	SND_YMW	7
	SND_YMW	8
	SND_YMW	9
	SND_YMW	10
	rts


	section data,data
	even
snd_pcm:	incbin	"snd_pcm.bin"
	even

	section bss,bss
	even
snd_sn:		ds.w	8		; the SN76489A's registers 0-7 (periods at 0, 2, 4, the noise control 6; attenuations 1, 3, 5, 7)
snd_ym_writes:	ds.w	1
snd_dma_last:	ds.w	1		; the last phrase started (-1: stopped)
snd_sn_latch:	ds.b	1		; the SN's latched register
snd_dirty:	ds.b	1
snd_ymch:	ds.b	4		; per YM channel its voice (-1: none; a long: even)
snd_pick:	ds.b	4
snd_newch:	ds.b	4
snd_ym_new:	ds.b	16
snd_ym_cache:	ds.b	16		; the YM's registers as last written ($FF: not yet)
	even
	section text,code
