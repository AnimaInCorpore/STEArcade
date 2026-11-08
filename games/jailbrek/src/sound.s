; Jail Break's sound on the STE (included by jailbrek.s unless NOSOUND): the game drives its two chips from the main CPU,
; so there is no sound CPU to translate.
;
; The SN76489A ($3100: the writes, jb_sn_w; the routine at $AF96 is a native, nat_sn_AF96): its register file (jb_sn,
; MAME's sn76496_base_device::write) goes to the YM2149's three channels once an arcade frame (snd_ym: the three loudest
; voices, a voice keeping its YM channel while it lasts, Mr. Do!'s method; Track & Field's player, tables from
; tools/assets.py: the SN here runs at 1.536 MHz).
;
; The VLM5030: its pins ($4000) and data latch ($5000) are in main_io_w (the BSY count); ST's falling edge also asks the
; DMA sound for the phrase (the data latch, the parameter RST's falling edge latched): the samples were rendered offline
; (engine/vlm5030.py, tools/assets.py SPEECH) at 12517 Hz, 8 bits, mono, and start at the end of the arcade frame (the
; last request of a frame wins); RST rising on a busy chip stops them.

snd_init:
	movem.l	d0-d1/a0,-(sp)
	lea	jb_sn,a0		; (8 words: periods 0, 2, 4, the noise control 6; volumes 1, 3, 5, 7: MAME's reset, 0)
	moveq	#8-1,d0
.s:	clr.w	(a0)+
	dbf	d0,.s
	clr.b	snd_sn_latch
	clr.b	snd_dma_req
	st	snd_dirty
	lea	snd_ym_cache,a0
	moveq	#16-1,d0
.y:	move.b	#$FF,(a0)+
	dbf	d0,.y
	move.l	#-1,snd_ymch		; (no voice on the YM's three: -1 bytes)
	movem.l	(sp)+,d0-d1/a0
	rts

; snd_frame (once an arcade frame, before its interrupts): the YM from the SN when a write came, the DMA when a phrase
; was asked.  Keeps all registers.
snd_frame:
	tst.b	snd_dirty
	bne.s	.go
	tst.b	snd_dma_req
	bne.s	.go
	rts
.go:	movem.l	d0-d7/a0-a6,-(sp)
	tst.b	snd_dirty
	beq.s	.d
	bsr	snd_ym
.d:	tst.b	snd_dma_req
	beq.s	.out
	bsr	snd_dma
.out:	movem.l	(sp)+,d0-d7/a0-a6
	rts

; nat_sn_AF96: the native of $AF96 (`nop` x 5; `sta $3100`; `sta $3200`; `rts`: A to the SN76489A, the register file
; of jb_sn_w written in place): the same state at the RTS ($AFA1): N Z from A, V clear, C kept.  d0 = A.  Scratch: d5-d7,
; a0, as in the translation.  Called in three ways: from the 6809 (nat_sn_AF96: a return address on the 6809 stack, left
; through the RTS's translation), directly (m6809x inline_calls: `jsr nat_sn_AF96_i`, no return address; `_nf` when no flag
; is read afterwards).
	macro	SNBODY
	ifnd NOSOUND
	st	snd_dirty
	lea	jb_sn,a0
	move.b	d0,d5
	bpl.s	.data\@
	moveq	#$70,d7			; a latch byte: the register, its low 4 bits
	and.b	d5,d7
	lsr.b	#4,d7
	move.b	d7,snd_sn_latch
	add.w	d7,d7
.low\@:	and.b	#$0F,d5
	and.b	#$F0,1(a0,d7.w)
	or.b	d5,1(a0,d7.w)
	bra.s	.done\@
.data\@:	moveq	#0,d7			; a data byte: the latched register
	move.b	snd_sn_latch,d7
	btst	#0,d7
	bne.s	.vol\@			; (a volume: its low 4 bits)
	cmp.b	#6,d7
	beq.s	.vol\@			; (the noise control: the same)
	add.w	d7,d7			; a period: bits 4-9
	and.w	#$3F,d5
	lsl.w	#4,d5
	and.w	#$0F,(a0,d7.w)
	or.w	d5,(a0,d7.w)
	bra.s	.done\@
.vol\@:	add.w	d7,d7
	bra.s	.low\@
.done\@:
	endc
	endm
	macro	SNFLAGS
	move.w	(sp)+,d6
	and.w	#1,d6
	tst.b	d0
	move.w	sr,d7
	or.b	d6,d7
	move.w	d7,ccr
	endm
nat_sn_AF96:
	move.w	sr,-(sp)
	SNBODY
	SNFLAGS
	jmp	M00AFA1
nat_sn_AF96_i:
	move.w	sr,-(sp)
	SNBODY
	SNFLAGS
	rts
nat_sn_AF96_i_nf:
	SNBODY
	rts

; jb_sn_w: d5.b = a byte written to the SN76489A.  Keeps every register.
jb_sn_w:
	movem.l	d1-d3/a0,-(sp)
	st	snd_dirty
	move.b	d5,d1
	bpl.s	.data
	moveq	#$70,d3			; a latch byte: the register, its low 4 bits
	and.b	d1,d3
	lsr.b	#4,d3
	move.b	d3,snd_sn_latch
.low:	add.w	d3,d3
	lea	jb_sn,a0
	moveq	#$0F,d2
	and.b	d1,d2
	and.w	#$3F0,(a0,d3.w)
	or.w	d2,(a0,d3.w)
	movem.l	(sp)+,d1-d3/a0
	rts
.data:	moveq	#0,d3			; a data byte: the latched register
	move.b	snd_sn_latch,d3
	btst	#0,d3
	bne.s	.low			; (a volume: its low 4 bits)
	cmp.b	#6,d3
	beq.s	.low			; (the noise control: the same)
	add.w	d3,d3			; a period: bits 4-9
	lea	jb_sn,a0
	moveq	#$3F,d2
	and.b	d1,d2
	lsl.w	#4,d2
	and.w	#$0F,(a0,d3.w)
	or.w	d2,(a0,d3.w)
	movem.l	(sp)+,d1-d3/a0
	rts

; jb_phrase: ST fell: the phrase of the data latch and the parameter -> the DMA request (snd_dma_last = the table entry's
; offset; 0 / no entry: none).  Keeps every register.
jb_phrase:
	movem.l	d0-d1/a0,-(sp)
	move.b	jb_vlm_latch,d0
	lsl.w	#8,d0
	move.b	jb_param,d0
	lea	jb_phr_tab,a0
	moveq	#JB_PHRASES-1,d1
.f:	cmp.w	(a0),d0
	beq.s	.found
	lea	10(a0),a0
	dbf	d1,.f
	movem.l	(sp)+,d0-d1/a0
	rts
.found:	move.l	a0,snd_dma_last
	st	snd_dma_req
	movem.l	(sp)+,d0-d1/a0
	rts

; jb_phrase_stop: RST rose on a busy chip: the samples stop
jb_phrase_stop:
	clr.l	snd_dma_last
	st	snd_dma_req
	rts

; snd_dma (the frame's end): the last request of the frame on the DMA sound
snd_dma:
	clr.b	snd_dma_req
	ifnd SIM
	clr.b	$ffff8901.w		; (stopped; a new start sets the addresses)
	move.l	snd_dma_last,d0
	beq.s	.x
	move.l	d0,a0
	move.l	2(a0),d0		; the offset
	move.l	6(a0),d1		; the length (0: none)
	beq.s	.x
	add.l	#jb_pcm,d0
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
	rts

; ---- snd_ym: the YM's registers from the SN's.  A voice's key: (16 - attenuation) * 8 + 7 - voice (0: silent); the three
; best in d2 > d3 > d4.

SND_KEY	macro				; \1 the voice (0-3): its attenuation at jb_sn + 4 * \1 + 2
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
.s\@:
	endm

snd_ym:
	clr.b	snd_dirty
	lea	jb_sn,a0
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
	lea	jb_ptab,a4
	lea	jb_vtab,a5
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
	lea	jb_ntab,a1
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

	section bss,bss
	even
jb_sn:		ds.w	8		; the SN76489A's registers 0-7
snd_dma_last:	ds.l	1		; the phrase table entry the DMA plays (0: none)
snd_sn_latch:	ds.b	1		; the SN's latched register
snd_dirty:	ds.b	1
snd_dma_req:	ds.b	1
	even
snd_ymch:	ds.b	4		; per YM channel its voice (-1: none; a long: even)
snd_pick:	ds.b	4
snd_newch:	ds.b	4
snd_ym_new:	ds.b	16
snd_ym_cache:	ds.b	16		; the YM's registers as last written ($FF: not yet)
	even
	section text,code
