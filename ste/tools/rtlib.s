; Runtime helpers shared by the translated code and the bench.
; Conventions: see z80x.py (d0=A, d6=flags image, d5/d7 scratch)

; 8257 sprite DMA ($7D85 bit 0 written): $6900 -> $7000, $180 bytes (what dkong.py's do_dma
; does).  a6 = Z80 block.  Keeps every register of the translated program.
z80_dma:
	movem.l	d1-d4/a1-a2,-(sp)
	lea	$6900(a6),a1
	lea	$7000(a6),a2
	moveq	#$180/16-1,d1
.copy:
	movem.l	(a1)+,d2-d5
	movem.l	d2-d5,(a2)
	lea	16(a2),a2
	dbf	d1,.copy
	movem.l	(sp)+,d1-d4/a1-a2
	rts

; The dispatch table the translated code uses is in byte swapped pc order (a return
; address read from the Z80 stack as a word): a0 = z80_dispatch (TABLE_ENTRIES longs in
; pc order), a1 = the table to fill (65536 longs), d0 = TABLE_ENTRIES.
z80_init_dispatch:
	move.l	a1,a2
	move.l	#z80_badpc,d1
	move	#65536/8-1,d2
.fill:
	rept 8
	move.l	d1,(a2)+
	endr
	dbf	d2,.fill

	moveq	#0,d1			; pc
.scatter:
	move	d1,d2
	ror	#8,d2
	and.l	#$ffff,d2
	lsl.l	#2,d2
	move.l	(a0)+,(a1,d2.l)
	addq	#1,d1
	cmp	d0,d1
	blo.s	.scatter
	rts

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

