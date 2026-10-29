; Mr. Do!'s sound on the STE (included by mrdo.s): the two SN76489s (4.1 MHz, written by the game itself: the runtime's
; md_sound* put (chip, byte) pairs into snd_ring) kept as register files after MAME's sn76496.cpp, their six tone
; voices put on the YM2149's three channels once an arcade frame (tools/sound.py is the same in Python;
; tools/sound_test.py compares).
;
; * SN76489 (MAME sn76496_base_device::write): a byte with bit 7 latches register (bits 4-6) and writes its low 4 bits;
;   a byte without bit 7 writes the latched register: a tone period's bits 4-9, otherwise the low 4 bits.  A period of
;   0 counts as $400.  Tone frequency clock / (32 N); volume 2 dB a step, 15 off.  After reset every volume is 0 (the
;   loudest) and every period 0 (MAME's start).  The game never programs the noise: it is left out.
; * The YM (2 MHz: frequency 2000000 / (16 P)): P = N * 40 / 41 (snd_ptab); its fixed levels are ~3 dB a step:
;   level 15 - round(2 a / 3) for attenuation a (snd_vtab), 0 for 15.
; * The mix (Pooyan's and Gyruss's method): the three loudest audible voices (ties: the lower voice; voices 0-2 the
;   first chip's, 3-5 the second's); a YM channel that holds a chosen voice keeps it, the others take the rest in order;
;   only the YM registers that changed are written.

	section text,code

snd_init:
	movem.l	d0-d7/a0-a6,-(sp)
	lea	snd_sn,a0		; (2 x 8 words: periods 0, 2, 4 and the noise control 6; volumes 1, 3, 5, 7)
	moveq	#16-1,d0
.r:	clr.w	(a0)+
	dbf	d0,.r
	clr.w	snd_latch		; (bytes: chip 0, chip 1)
	move.b	snd_head,snd_tail
	st	snd_dirty
	lea	snd_ym_cache,a0
	moveq	#16-1,d0
.y:	move.b	#$FF,(a0)+
	dbf	d0,.y
	move.l	#-1,snd_ymch		; (no voice on the YM's three: -1 bytes)
	lea	snd_ptab,a0		; snd_ptab: per SN period (0-1023; 0 as 1024) the YM's, N * 40 / 41 rounded
	moveq	#0,d0
.p:	move.w	d0,d1
	bne.s	.p1
	move.w	#1024,d1
.p1:	mulu	#80,d1
	add.l	#41,d1
	divu	#82,d1
	move.w	d1,(a0)+
	addq.w	#1,d0
	cmp.w	#1024,d0
	bne.s	.p
	bsr	snd_ym
	movem.l	(sp)+,d0-d7/a0-a6
	rts

; snd_frame: the bytes the game wrote since the last call into the register files, then the YM.  Keeps all registers.
snd_frame:
	movem.l	d0-d7/a0-a6,-(sp)
	lea	snd_ring,a1
	moveq	#0,d0
.b:	move.b	snd_tail,d0
	cmp.b	snd_head,d0
	beq.s	.ym
	addq.b	#2,snd_tail
	moveq	#0,d1
	move.b	(a1,d0.w),d1		; the chip (0, 1)
	move.b	1(a1,d0.w),d2		; the byte
	lea	snd_latch,a2
	add.w	d1,a2
	lsl.w	#4,d1
	lea	snd_sn,a0
	add.w	d1,a0			; its registers
	st	snd_dirty
	tst.b	d2
	bpl.s	.data
	moveq	#$70,d3			; a latch byte: the register, its low 4 bits
	and.b	d2,d3
	lsr.b	#4,d3
	move.b	d3,(a2)
.low:	ext.w	d3
	add.w	d3,d3
	moveq	#$0F,d4
	and.b	d2,d4
	move.w	(a0,d3.w),d5
	and.w	#$3F0,d5
	or.w	d4,d5
	move.w	d5,(a0,d3.w)
	bra	.b
.data:	move.b	(a2),d3			; a data byte: the latched register
	btst	#0,d3
	bne.s	.low			; (a volume: its low 4 bits)
	cmp.b	#6,d3
	beq.s	.low			; (the noise control: the same)
	ext.w	d3			; a period: bits 4-9
	add.w	d3,d3
	moveq	#$3F,d4
	and.b	d2,d4
	lsl.w	#4,d4
	move.w	(a0,d3.w),d5
	and.w	#$0F,d5
	or.w	d4,d5
	move.w	d5,(a0,d3.w)
	bra	.b
.ym:	tst.b	snd_dirty
	beq.s	.out
	bsr	snd_ym
.out:	movem.l	(sp)+,d0-d7/a0-a6
	rts

; snd_ym: the YM's registers from the two register files.  A voice's key: (16 - attenuation) * 8 + 7 - voice (0:
; silent); the three best in d2 > d3 > d4.
SND_KEY	macro				; \1 the voice (0-5): its volume at snd_sn + (\1 / 3) * 16 + (\1 // 3) * 4 + 2
	moveq	#$0F,d1
	and.w	((\1/3)*16+(\1-(\1/3)*3)*4+2)(a0),d1
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
	SND_KEY	4
	SND_KEY	5
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
	lea	snd_voff,a1
	move.b	(a1,d0.w),d0		; the voice's registers' offset in snd_sn (its period; the volume 2 further)
	lea	(a0,d0.w),a1
	move.w	(a1),d2			; the period (10 bits), scaled
	add.w	d2,d2
	move.w	(a4,d2.w),d2
	move.w	d6,d1
	add.w	d1,d1
	move.b	d2,(a2,d1.w)
	lsr.w	#8,d2
	move.b	d2,1(a2,d1.w)
	moveq	#$0F,d1			; the level
	and.w	2(a1),d1
	move.b	(a5,d1.w),8(a2,d6.w)
	bclr	d6,d7			; tone on
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
	SND_YMW	7
	SND_YMW	8
	SND_YMW	9
	SND_YMW	10
	rts

	section data,data
snd_vtab:	dc.b	15,14,14,13,12,12,11,10,10,9,8,8,7,6,6,0	; SN attenuation -> YM level
snd_voff:	dc.b	0,4,8,16,20,24			; voice -> its period's offset in snd_sn
	even

	section bss,bss
	even
snd_sn:		ds.w	16		; the two SN76489s' registers 0-7 (words)
snd_ptab:	ds.w	1024		; SN period -> YM period
snd_ym_writes:	ds.w	1
snd_latch:	ds.b	2		; per chip the latched register
snd_ymch:	ds.b	4		; per YM channel its voice (-1: none)
snd_pick:	ds.b	4
snd_newch:	ds.b	4
snd_ym_new:	ds.b	16
snd_ym_cache:	ds.b	16		; the YM's registers as last written ($FF: not yet)
snd_tail:	ds.b	1
snd_dirty:	ds.b	1
	even
	section text,code
