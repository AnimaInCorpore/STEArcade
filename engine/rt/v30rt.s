; Runtime helpers of the V30 translation (engine/v30x.py): the PSW, the REP string instructions, the parity table.
; Registers as the translation keeps them: d0 = AW, d1 = CW, d2 = DW, d3 = BW, d4 = IX, d5 = IY, d6 = BP (upper words
; 0), a2 / a3 / a4 = the DS1 / DS0 / SS bases, a5 = SS:SP, a6 = the context (V30_IE, V30_DF, V30_PB below), the V30's
; S Z O C = the CCR's N Z V C.  The image keeps the V30's bytes swapped in each word: V30 byte a at (a ^ 1).
; They use d7 a0 a1 only.

V30_SEG = 0			; 4 words: DS1 PS SS DS0
V30_IE = 8			; byte: IE ($FF set)
V30_DF = 9			; byte: DF
V30_PB = 10			; byte: the last result byte a parity is read from
V30_AX = 11			; byte: bit 4 = AC (where it is read: ADJ4A / ADJ4S)

; a0.w = a PSW -> IE, DF, P (as a result byte of that parity) to the context, C Z S O to the CCR
v30_psw_in:
	move.w	a0,-(sp)
	moveq	#0,d7
	btst	#0,1(sp)		; C
	beq.s	.c
	moveq	#1,d7
.c:	btst	#6,1(sp)		; Z
	beq.s	.z
	addq.b	#4,d7
.z:	btst	#7,1(sp)		; S
	beq.s	.n
	addq.b	#8,d7
.n:	btst	#3,(sp)			; O (bit 11)
	beq.s	.v
	addq.b	#2,d7
.v:	btst	#1,(sp)			; IE (bit 9)
	sne	V30_IE(a6)
	btst	#2,(sp)			; DF (bit 10)
	sne	V30_DF(a6)
	btst	#2,1(sp)		; P: a byte of even parity (0) when set, odd (1) when clear
	seq	V30_PB(a6)
	andi.b	#1,V30_PB(a6)
	addq.l	#2,sp
	move.w	d7,ccr
	rts

; d7.w = the PSW of the CCR and the context (MAME's compress(): bits 1, 12-15 set; AC and TF 0); the CCR kept
v30_psw_out:
	move.w	sr,-(sp)
	moveq	#0,d7
	move.b	V30_PB(a6),d7
	lea	v30_parity,a0
	move.b	(a0,d7.w),d7		; 1: even
	lsl.w	#2,d7			; P (bit 2)
	or.w	#$F002,d7
	btst	#0,1(sp)		; C
	beq.s	.c
	addq.w	#1,d7
.c:	btst	#2,1(sp)		; Z
	beq.s	.z
	or.w	#$40,d7
.z:	btst	#3,1(sp)		; N
	beq.s	.n
	or.w	#$80,d7
.n:	btst	#1,1(sp)		; V
	beq.s	.v
	or.w	#$800,d7
.v:	tst.b	V30_IE(a6)
	beq.s	.i
	or.w	#$200,d7
.i:	tst.b	V30_DF(a6)
	beq.s	.d
	or.w	#$400,d7
.d:	move.w	(sp)+,ccr
	rts

; REP STMW: CW words of AW to DS1:IY (DF 0)
v30_rep_stmw:
	tst.w	d1
	beq.s	.r
	btst	#0,d5
	bne.s	.odd
	lea	(a2,d5.l),a0
	move.w	d1,d7
	add.w	d7,d5
	add.w	d7,d5
	subq.w	#1,d7
.l:	move.w	d0,(a0)+
	dbf	d7,.l
	moveq	#0,d1
.r:	rts
.odd:	move.w	d0,-(sp)		; (an odd IY: byte by byte, low then high)
.o:	moveq	#0,d7
	move.w	d5,d7
	eori.w	#1,d7
	move.b	1(sp),(a2,d7.l)
	addq.w	#1,d5
	moveq	#0,d7
	move.w	d5,d7
	eori.w	#1,d7
	move.b	(sp),(a2,d7.l)
	addq.w	#1,d5
	subq.w	#1,d1
	bne.s	.o
	addq.l	#2,sp
	rts

; REP STMB: CW bytes of AL to DS1:IY
v30_rep_stmb:
	tst.w	d1
	beq.s	.r
.l:	moveq	#0,d7
	move.w	d5,d7
	eori.w	#1,d7
	move.b	d0,(a2,d7.l)
	addq.w	#1,d5
	subq.w	#1,d1
	bne.s	.l
.r:	rts

; REP MOVBKW: CW words from (a0 = the source segment's base):IX to DS1:IY
v30_rep_movbkw:
	tst.w	d1
	beq.s	.r
	move.w	d4,d7
	or.w	d5,d7
	btst	#0,d7
	bne.s	.odd
	move.l	a0,-(sp)
	lea	(a0,d4.l),a0
	lea	(a2,d5.l),a1
	move.w	d1,d7
	add.w	d7,d4
	add.w	d7,d4
	add.w	d7,d5
	add.w	d7,d5
	move.l	a1,-(sp)		; (the destination 2 bytes above the source: word by word, as the V30 copies)
	subq.l	#2,(sp)
	cmpa.l	(sp)+,a0
	bne.s	.long
	subq.w	#1,d7
.l:	move.w	(a0)+,(a1)+
	dbf	d7,.l
	bra.s	.done
.long:	lsr.w	#1,d7			; (words in pairs: the image keeps each word's bytes swapped, a long is two words)
	bcc.s	.even
	move.w	(a0)+,(a1)+
.even:	subq.w	#1,d7
	bmi.s	.done
.ll:	move.l	(a0)+,(a1)+
	dbf	d7,.ll
.done:	moveq	#0,d1
	move.l	(sp)+,a0
.r:	rts
.odd:	add.w	d1,d1			; (an odd address: as bytes)
	bsr.s	v30_rep_movbkb
	rts

; REP MOVBKB: CW bytes from (a0 = the source segment's base):IX to DS1:IY, one by one (overlaps as the V30 does);
; DF set: downwards
v30_rep_movbkb:
	tst.w	d1
	beq.s	.r
	tst.b	V30_DF(a6)
	bne.s	.down
.l:	moveq	#0,d7
	move.w	d4,d7
	eori.w	#1,d7
	move.b	(a0,d7.l),-(sp)
	move.w	d5,d7
	eori.w	#1,d7
	move.b	(sp)+,(a2,d7.l)
	addq.w	#1,d4
	addq.w	#1,d5
	subq.w	#1,d1
	bne.s	.l
.r:	rts
.down:	moveq	#0,d7
	move.w	d4,d7
	eori.w	#1,d7
	move.b	(a0,d7.l),-(sp)
	move.w	d5,d7
	eori.w	#1,d7
	move.b	(sp)+,(a2,d7.l)
	subq.w	#1,d4
	subq.w	#1,d5
	subq.w	#1,d1
	bne.s	.down
	rts

; ADJ4A / ADJ4S (DAA / DAS) as MAME's nec core: AL from AC (V30_AX bit 4) and C; the second step tests the adjusted AL
; > $9F; C Z S and P (V30_PB) from it, O kept
v30_adj4a:
	move.w	sr,-(sp)
	movem.l	d1-d2,-(sp)
	moveq	#0,d1
	move.b	d0,d1
	moveq	#0,d2
	btst	#0,9(sp)
	beq.s	.c
	moveq	#1,d2
.c:	btst	#4,V30_AX(a6)
	bne.s	.adj
	move.b	d1,d7
	and.b	#$0F,d7
	cmp.b	#9,d7
	bls.s	.two
.adj:	addq.w	#6,d1
	btst	#8,d1
	beq.s	.nc
	moveq	#1,d2
.nc:	and.w	#$FF,d1
	move.b	#$10,V30_AX(a6)
.two:	tst.b	d2
	bne.s	.adj2
	cmp.b	#$9F,d1
	bls.s	adj_out
.adj2:	add.b	#$60,d1
	moveq	#1,d2
	bra.s	adj_out

v30_adj4s:
	move.w	sr,-(sp)
	movem.l	d1-d2,-(sp)
	moveq	#0,d1
	move.b	d0,d1
	moveq	#0,d2
	btst	#0,9(sp)
	beq.s	.c
	moveq	#1,d2
.c:	btst	#4,V30_AX(a6)
	bne.s	.adj
	move.b	d1,d7
	and.b	#$0F,d7
	cmp.b	#9,d7
	bls.s	.two
.adj:	subq.w	#6,d1
	btst	#8,d1
	beq.s	.nc
	moveq	#1,d2
.nc:	and.w	#$FF,d1
	move.b	#$10,V30_AX(a6)
.two:	tst.b	d2
	bne.s	.adj2
	cmp.b	#$9F,d1
	bls.s	adj_out
.adj2:	sub.b	#$60,d1
	moveq	#1,d2
adj_out:
	move.b	d1,d0
	move.b	d1,V30_PB(a6)
	move.w	8(sp),d7
	and.w	#$02,d7			; O kept
	or.b	d2,d7			; C
	tst.b	d1
	bne.s	.z
	or.b	#4,d7
.z:	btst	#7,d1
	beq.s	.n
	or.b	#8,d7
.n:	movem.l	(sp)+,d1-d2
	addq.l	#2,sp
	move.w	d7,ccr
	rts

; ADD4S as MAME's nec core (bcd4s): (CL + 1) / 2 BCD bytes of DS1:IY += DS0:IX, low byte first; the registers
; unchanged; C the last carry, Z when every result byte is 0; S O kept
v30_add4s:
	move.w	sr,-(sp)
	movem.l	d0-d6,-(sp)		; (the saved SR at 28(sp))
	moveq	#0,d6
	move.b	d1,d6
	addq.w	#1,d6
	lsr.w	#1,d6
	move.w	d4,d0			; si
	move.w	d5,d1			; di
	moveq	#0,d2			; C
	moveq	#0,d3			; a result byte not 0
	tst.w	d6
	beq.s	.end
.l:	moveq	#0,d7
	move.w	d0,d7
	eori.w	#1,d7
	moveq	#0,d4
	move.b	(a3,d7.l),d4
	move.w	d1,d7
	eori.w	#1,d7
	lea	(a2,d7.l),a0
	moveq	#0,d5
	move.b	(a0),d5
	bsr.s	.bin4
	exg	d4,d5
	bsr.s	.bin4
	add.w	d5,d4
	add.w	d2,d4
	moveq	#0,d2
	cmp.w	#99,d4
	bls.s	.c
	moveq	#1,d2
.c:	divu	#100,d4
	clr.w	d4
	swap	d4			; res % 100
	divu	#10,d4			; q (low) r (high)
	move.w	d4,d7
	lsl.w	#4,d7
	swap	d4
	or.w	d4,d7
	move.b	d7,(a0)
	beq.s	.zero
	moveq	#1,d3
.zero:	addq.w	#1,d0
	addq.w	#1,d1
	subq.w	#1,d6
	bne.s	.l
.end:	move.w	28(sp),d7
	and.w	#$0A,d7			; S O kept
	or.b	d2,d7
	tst.b	d3
	bne.s	.nz
	or.b	#4,d7
.nz:	movem.l	(sp)+,d0-d6
	addq.l	#2,sp
	move.w	d7,ccr
	rts
; d4 = a BCD byte -> its value (the digits as MAME takes them: (b >> 4) * 10 + (b & 15))
.bin4:	move.w	d4,d7
	lsr.w	#4,d7
	mulu	#10,d7
	and.w	#$0F,d4
	add.w	d7,d4
	rts

; the parity of a byte: 1 when it has an even number of bits set (the V30's P)
v30_parity:
	dc.b	1,0,0,1,0,1,1,0,0,1,1,0,1,0,0,1
	dc.b	0,1,1,0,1,0,0,1,1,0,0,1,0,1,1,0
	dc.b	0,1,1,0,1,0,0,1,1,0,0,1,0,1,1,0
	dc.b	1,0,0,1,0,1,1,0,0,1,1,0,1,0,0,1
	dc.b	0,1,1,0,1,0,0,1,1,0,0,1,0,1,1,0
	dc.b	1,0,0,1,0,1,1,0,0,1,1,0,1,0,0,1
	dc.b	1,0,0,1,0,1,1,0,0,1,1,0,1,0,0,1
	dc.b	0,1,1,0,1,0,0,1,1,0,0,1,0,1,1,0
	dc.b	0,1,1,0,1,0,0,1,1,0,0,1,0,1,1,0
	dc.b	1,0,0,1,0,1,1,0,0,1,1,0,1,0,0,1
	dc.b	1,0,0,1,0,1,1,0,0,1,1,0,1,0,0,1
	dc.b	0,1,1,0,1,0,0,1,1,0,0,1,0,1,1,0
	dc.b	1,0,0,1,0,1,1,0,0,1,1,0,1,0,0,1
	dc.b	0,1,1,0,1,0,0,1,1,0,0,1,0,1,1,0
	dc.b	0,1,1,0,1,0,0,1,1,0,0,1,0,1,1,0
	dc.b	1,0,0,1,0,1,1,0,0,1,1,0,1,0,0,1
	even
