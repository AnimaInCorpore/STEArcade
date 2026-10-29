; Hyper Sports: hand-written replacements of hot 6809 routines (tools/gen.py NATIVES; included by hyperspt.s).  Each
; leaves A B X Y U, the memory and the flags the routine's own RTS sees exactly as the 6809 does, and goes on into
; that RTS's translation.  tools/logic_test.py checks them in lock-step; HS_NO_NATIVES=4FBD,... builds without some.
;
; Registers (engine/m6809x.py): d0 A, d1 B, d2 X, d3 Y, d4 U (words, upper words 0), a3 = a4 = hs_mem; d5-d7, a0, a1
; scratch.

	section text,code

; $4FBD / $4FD2 (called by the IRQ handler every frame): LDX #src; LDU #dst; loop LDD ,X++; STD ,U++; LDD ,X++;
; STD ,U++; CMPU #end; BNE loop; RTS.  The sprite RAM ($3600 -> $1000, 144 bytes) and the scrolls ($36C0 -> $10C0,
; 64 bytes) copied as longs (hs_mem is long aligned); X and U end past the blocks, D holds the last word, CMPU's
; flags: equal (Z set, N V C clear).
nat_copy_4FBD:
	lea	hs_mem+$3600,a0
	lea	hs_mem+$1000,a1
	rept	144/4
	move.l	(a0)+,(a1)+
	endr
	move.b	hs_mem+$368E,d0
	move.b	hs_mem+$368F,d1
	move.w	#$3690,d2
	move.w	#$1090,d4
	move	#$04,ccr
	jmp	M004FD1

nat_copy_4FD2:
	lea	hs_mem+$36C0,a0
	lea	hs_mem+$10C0,a1
	rept	64/4
	move.l	(a0)+,(a1)+
	endr
	move.b	hs_mem+$36FE,d0
	move.b	hs_mem+$36FF,d1
	move.w	#$3700,d2
	move.w	#$1100,d4
	move	#$04,ccr
	jmp	M004FE6

; $A62B (weightlifting's hot routine), the 6809 code it replaces:
;   CLR <$5F; CLR <$5E; CLR <$5D; 5 x (ROLB; ROLA)      0:D rotated left 5 (17 bits: the CLRs cleared C)
;   4 x DEC <$5D; STX <$5B; BEQ zero                      the count -4; the divisor X at <$5B; X = 0: C set, RTS
;   BMI loop; norm: INC <$5D; ASL <$5C; ROL <$5B; BPL norm    the divisor shifted up to bit 15, counted
;   loop: CMPD <$5B; BCS 0: SUBD <$5B, C = 1; 0: C = 0; ROL <$5F; ROL <$5E   (a quotient bit)
;         DEC <$5D; BEQ done; LSR <$5B; ROR <$5C; BRA loop
;   done: LDX <$5E; ANDCC #$FE; 5 x (RORA; RORB); RTS      X = the quotient, 0:D rotated right 5
; The count is a byte: one that starts at 0 or below (a divisor of $1000 or more) wraps and the loop runs on (to 256
; rounds), as on the 6809.  The bytes <$5B-$5F end as the 6809 leaves them; at the RTS N Z are RORB's (of B), V clear,
; C the bit RORB shifted out.
nat_div_A62B:
	movem.l	d3-d4,-(sp)		; (Y and U: used as scratch here, given back)
	move.b	d0,d6			; d6.w = D
	lsl.w	#8,d6
	move.b	d1,d6
	andi	#$EF,ccr		; X clear: the CLRs cleared C, the bit the first ROLB takes in
	roxl.w	#5,d6			; 0:D rotated left 5 times (17 bits)
	moveq	#-4,d3			; the count (a byte)
	move.w	d2,d5			; the divisor
	beq	.zero
	bmi.s	.loop
.norm:	addq.b	#1,d3
	add.w	d5,d5
	bpl.s	.norm
.loop:	moveq	#0,d4			; the quotient
.step:	cmp.w	d5,d6			; CMPD: D >= the divisor (unsigned) gives a 1
	bcs.s	.q0
	sub.w	d5,d6
	add.w	d4,d4
	addq.w	#1,d4
	subq.b	#1,d3
	beq.s	.done
	lsr.w	#1,d5
	bra.s	.step
.q0:	add.w	d4,d4
	subq.b	#1,d3
	beq.s	.done
	lsr.w	#1,d5
	bra.s	.step
.done:	move.b	d3,hs_mem+$305D		; (0)
	move.w	d5,-(sp)		; <$5B <$5C: the divisor as it ends
	move.b	(sp)+,hs_mem+$305B
	move.b	d5,hs_mem+$305C
	move.w	d4,d2			; X = the quotient, also at <$5E <$5F
	move.w	d4,-(sp)
	move.b	(sp)+,hs_mem+$305E
	move.b	d4,hs_mem+$305F
	movem.l	(sp)+,d3-d4
	andi	#$EF,ccr		; X clear (ANDCC #$FE: the bit RORA takes in)
	roxr.w	#5,d6			; 0:D rotated right 5 times
	bcs.s	.c1			; (C: the bit the last RORB shifted out)
	move.w	d6,d7
	lsr.w	#8,d7
	move.b	d7,d0
	move.b	d6,d1			; N Z of B, V C clear
	jmp	M00A67A
.c1:	move.w	d6,d7
	lsr.w	#8,d7
	move.b	d7,d0
	move.b	d6,d1
	ori	#$01,ccr		; C set, N Z of B kept
	jmp	M00A67A
.zero:	move.b	d3,hs_mem+$305D		; ($FC) X = 0: <$5B <$5C = 0, the quotient 0, D the rotated dividend
	clr.b	hs_mem+$305B
	clr.b	hs_mem+$305C
	clr.b	hs_mem+$305E
	clr.b	hs_mem+$305F
	move.w	d6,d7
	lsr.w	#8,d7
	move.b	d7,d0
	move.b	d6,d1
	movem.l	(sp)+,d3-d4
	move	#$05,ccr		; STX of 0 (Z set, N V clear), ORCC #1 (C set)
	jmp	M00A67D
