; Runtime helpers of the 6809 translation (engine/m6809x.py): the instructions that are not worth inline code.
; Registers as the translation keeps them: d0 = A, d1 = B, the 6809's N Z V C in the CCR, a6 = the CPU's context
; (+112: the CC bits E F H I).  They use d5-d7 only.

; DAA as MAME's m6809 core does it: the correction from H, C and the nibbles; V cleared, C = the old C or the
; carry of the correction, N Z of the result.
m6809_daa:
	move.w	sr,d5
	moveq	#0,d6
	move.b	d0,d7
	and.b	#$0F,d7
	cmp.b	#$09,d7
	bhi.s	.l6
	btst	#5,112(a6)		; H
	beq.s	.l1
.l6:	moveq	#6,d6
.l1:	move.b	d0,d7
	and.b	#$F0,d7
	cmp.b	#$80,d7
	bls.s	.l2
	move.b	d0,d7
	and.b	#$0F,d7
	cmp.b	#$09,d7
	bls.s	.l2
	or.b	#$60,d6
.l2:	move.b	d0,d7
	and.b	#$F0,d7
	cmp.b	#$90,d7
	bhi.s	.l3
	btst	#0,d5			; C
	beq.s	.l4
.l3:	or.b	#$60,d6
.l4:	and.b	#1,d5
	add.b	d6,d0
	scs	d7
	and.b	#1,d7
	or.b	d7,d5			; C |= the carry
	tst.b	d0
	move.w	sr,d7
	and.b	#$0C,d7			; N Z
	or.b	d5,d7
	move.w	d7,ccr
	rts

; MUL: D = A * B; Z = D == 0, C = bit 7 of the result; N V unchanged.
m6809_mul:
	move.w	sr,d5
	moveq	#0,d6
	move.b	d0,d6
	moveq	#0,d7
	move.b	d1,d7
	mulu	d7,d6
	move.b	d6,d1
	move.w	d6,d7
	lsr.w	#8,d7
	move.b	d7,d0
	and.b	#$0A,d5			; N V
	tst.w	d6
	bne.s	.nz
	or.b	#4,d5
.nz:	btst	#7,d6
	beq.s	.nc
	or.b	#1,d5
.nc:	move.w	d5,ccr
	rts
