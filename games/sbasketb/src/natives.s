; Hand-written replacements of two hot routines (gen.py NATIVES); the translation stays under <label>_t.  Registers as
; the translation's: d0 A, d1 B, d2 X, d3 Y, d4 U, a3 = a4 = sb_mem; d5-d7 a0 a1 scratch.  Both end by jumping to
; the routine's RTS with the 6809's N Z V C in the CCR.

; $8DD8, a division: the dividend <$9C:<$9D, the divisor <$9A:<$9B.  Quotient at $2255:$2256, D the remainder, the
; divisor ends rotated back (its first bit lost: ROR with C = 1 then LSR, as the 6809 code does), <$98 = 0,
; $29DD = $29E3 = 0, the flags of the last CLR (Z).  A divisor of 0 gives D = 0, quotient 0, N 0 Z 1 V 0 and C unchanged.
;   d3 count (<$98)  d4 the $29DD flag  d5 divisor  d6 remainder  d7 quotient  d2 the quotient bit (X, Y, U kept)
nat_div_8DD8:
	move	sr,d6
	move.w	$209A(a3),d5
	bne.s	.go
	moveq	#0,d0			; D = 0, stored at $2255
	moveq	#0,d1
	clr.b	$2255(a3)
	clr.b	$2256(a3)
	clr.b	$2098(a3)
	clr.b	$29DD(a3)
	and.b	#1,d6			; (the old C)
	or.b	#4,d6
	move	d6,ccr
	jmp	M008E38
.go:	movem.l	d2-d4,-(sp)
	moveq	#0,d3
	moveq	#0,d4
.sh:	addq.b	#1,d3			; INC <$98, ASL <$9B, ROL <$9A: until a 1 falls out
	add.w	d5,d5
	bcc.s	.sh
	tst.b	$29E3(a3)
	bne.s	.e3
	move.b	d5,d7			; ROR <$9A (C = 1), LSR <$9B
	lsr.b	#1,d7
	lsr.w	#8,d5
	lsr.b	#1,d5
	or.b	#$80,d5
	lsl.w	#8,d5
	move.b	d7,d5
	bra.s	.d
.e3:	addq.b	#1,d3
	moveq	#1,d4
.d:	move.w	$209C(a3),d6
	moveq	#0,d7
	sub.w	d5,d6			; the first SUBD
	bcc.s	.keep10
	add.w	d5,d6
	moveq	#0,d2
	bra.s	.ins
.keep10: clr.b	$29E3(a3)
	moveq	#1,d2
	bra.s	.ins
.loop:	sub.w	d5,d6
	bcc.s	.keep
	tst.b	$29E3(a3)
	beq.s	.rest
	clr.b	$29E3(a3)
.keep:	moveq	#1,d2
	bra.s	.ins
.rest:	add.w	d5,d6
	moveq	#0,d2
.ins:	lsr.b	#1,d2			; X = the quotient bit
	roxl.w	#1,d7			; ROL <$2256, ROL <$2255: X = the bit that falls out
	tst.b	d4
	beq.s	.nodd
	moveq	#0,d4
	move	#$10,ccr		; ORCC #1 after CLR $29DD
.nodd:	roxr.w	#1,d5			; ROR <$9A, ROR <$9B
	subq.b	#1,d3
	bne.s	.loop
	move.w	d5,$209A(a3)
	move.b	d7,$2256(a3)
	lsr.w	#8,d7
	move.b	d7,$2255(a3)
	clr.b	$2098(a3)
	clr.b	$29DD(a3)
	clr.b	$29E3(a3)
	move.b	d6,d1
	lsr.w	#8,d6
	move.b	d6,d0
	movem.l	(sp)+,d2-d4
	move	#$04,ccr
	jmp	M008E38

; $64F7, the sprite list: for <$98 = $3F down to 0 the object whose number is at $29E4+<$98 (its record at $2500 + 16 *
; number) gives 4 bytes of the sprite RAM at X: record+14, +15, +4 and -(record[6] + $10).  X starts at $38F0
; ($39F0 if $29DF is 0) and goes to $3800 ($3900) when <$98 reaches $3C.  Ends with Y = $29E4, U the last record, X past
; the last entry, A its byte 4, B 0, <$98 = $FF, the flags of INCB (Z).
nat_list_64F7:
	movem.l	a2/a6,-(sp)
	move.w	#$29E4,d3
	lea	sb_mem+$29E4+$40,a2		; the number table, walked down
	lea	sb_mem+$2500,a6			; the records
	lea	sb_mem+$38F0,a0
	tst.b	$29DF(a3)
	bne.s	.a
	lea	sb_mem+$39F0,a0
.a:	moveq	#2,d5				; <$98 = $3F, $3E, $3D: X first goes through the end of the bank
	bsr.s	.run
	lea	sb_mem+$3800,a0
	tst.b	$29DF(a3)
	bne.s	.b
	lea	sb_mem+$3900,a0
.b:	moveq	#60,d5				; <$98 = $3C down to 0
	bsr.s	.run
	move.b	#$FF,$2098(a3)
	move.b	-2(a0),d0
	move.l	a0,d2
	sub.l	a4,d2
	move.l	a1,d4
	sub.l	a4,d4
	moveq	#0,d1
	movem.l	(sp)+,a2/a6
	move	#$04,ccr
	jmp	M00652E
.run:	moveq	#0,d7
	move.b	-(a2),d7
	lsl.w	#4,d7
	lea	(a6,d7.w),a1
	move.w	14(a1),(a0)+
	move.b	4(a1),(a0)+
	moveq	#-16,d1
	sub.b	6(a1),d1
	move.b	d1,(a0)+
	dbf	d5,.run
	rts

; $6000, the power-on delay: 65,536 turns of STA $3C00 (the watchdog), CLRA, STA $3C81 (latch Q1 = 0), LEAX 1,X.  It ends
; with A = 0, X = 0, the latch's Q1 0 and the flags of the last LEAX (Z set; N V C clear from the CLRA).
nat_boot_6000:
	clr.b	sb_latch+1
	moveq	#0,d0
	moveq	#0,d2
	move	#$04,ccr
	jmp	M00600E
