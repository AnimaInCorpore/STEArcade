; Runtime helpers shared by the translated code and the bench.
; Conventions: see z80x.py (d0=A, d6=flags image, d5/d7 scratch)

; DAA: d0 = A, d6 bit0=C bit5=H bit6=N  ->  A, S Z C H updated, N kept
z80_daa:
	moveq	#0,d7
	move.b	d0,d5
	andi.b	#$0F,d5
	btst	#5,d6
	bne.s	.l1
	cmpi.b	#9,d5
	bls.s	.l2
.l1:	moveq	#6,d7
.l2:	btst	#0,d6
	bne.s	.l3
	cmpi.b	#$99,d0
	bls.s	.l4
.l3:	ori.b	#$60,d7
.l4:	btst	#6,d6
	bne.s	.subm
	cmpi.b	#9,d5
	shi	d5			; H' = low nibble > 9
	bra.s	.hdone
.subm:	btst	#5,d6
	beq.s	.h0
	cmpi.b	#6,d5
	scs	d5			; H' = H and low nibble < 6
	bra.s	.hdone
.h0:	moveq	#0,d5
.hdone:	btst	#6,d6
	bne.s	.dosub
	add.b	d7,d0
	bra.s	.done
.dosub:	sub.b	d7,d0
.done:	andi.b	#$40,d6
	btst	#6,d7
	beq.s	.nc
	ori.b	#1,d6
.nc:	tst.b	d5
	beq.s	.nh
	ori.b	#$20,d6
.nh:	tst.b	d0
	bpl.s	.ns
	ori.b	#8,d6
.ns:	tst.b	d0
	bne.s	.nz
	ori.b	#4,d6
.nz:	rts

