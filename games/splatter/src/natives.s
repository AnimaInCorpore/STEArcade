; Hand-written 68000 routines in place of translated 6809 code (tools/gen.py NATIVES; the translation stays under
; <label>_t and tools/native_test.py compares the two).  Registers as engine/m6809x.py keeps them: d0 = A, d1 = B,
; d2-d4 = X Y U (upper words 0), a5 = S, a6 = the context, a3 = PB[0] (the direct page), a2 = PB[7], a4 = VB[1];
; d5-d7 a0 a1 free.

; ---- the sub CPU's $F714-$F78E: one object's sprite parts into the sprite list (17% of the two CPUs' time on stage 3)
;
;   F714  X = [$F57D + 2 * obj[8]] (B signed), X = [X + 2 * obj[9]], X += 4 * obj[4] (8 bit), D = obj[5] * X[1] & ~7,
;         X = [X + 2] + D, $5D = X[1], $5E = [X + 2], $60 = obj[$10] obj[$11], Y = [X + 6], Y = [Y + B] with
;         B = (obj[$11] << 2 | bit 5 of obj[$10] << 1) & 6, A = obj[$10] << 3; B = X[0]: no parts, RTS
;   F754  the parts (B of them): X = [X + 4], U = [$51]; per part U[4] = $60 | high of $5E + [X], U[5] = low of that,
;         U[8] = $61, U[6] = (low of [X+2]) + $5D | ((sext [Y] + [$57]) high & 1), U[7] = low of that, U[9] = [Y+1] + $59;
;         X += 4, Y += 2, U += 16; then [$51] = U, B = 0, RTS
; The parts' loop runs on 68000 pointers when X, Y and U stay in their 8 KB slots, else the translation from $F754.

ADR68	macro	; \1 = a 6809 address in a data register (upper word 0) -> \2 = its 68000 address
	move.w	\1,d6
	rol.w	#3,d6
	and.w	#7,d6
	add.w	d6,d6
	add.w	d6,d6
	move.l	32(a6,d6.w),\2
	adda.l	\1,\2
	endm

sub_sprites:
	moveq	#0,d7
	move.w	d4,d7
	ADR68	d7,a1				; a1 = the object (U)
	move.b	8(a1),d7			; LDB 8,U; ASLB; LDX B,X (B signed)
	add.b	d7,d7
	ext.w	d7
	lea	$157D(a2),a0			; ($F57D, slot 7)
	move.b	(a0,d7.w),-(sp)
	move.w	(sp)+,d2
	move.b	1(a0,d7.w),d2			; X
	moveq	#0,d7
	move.b	9(a1),d7			; LDB 9,U; CLRA; ASLB; ROLA; LDX D,X
	add.w	d7,d7
	add.w	d2,d7
	bsr	n_rd16				; X = [X + D]
	move.w	d7,d2
	move.b	4(a1),d7			; LDB 4,U; ASLB; ASLB; ABX
	add.b	d7,d7
	add.b	d7,d7
	and.w	#$FF,d7
	add.w	d7,d2
	moveq	#0,d7
	move.w	d2,d7
	ADR68	d7,a0
	moveq	#0,d5
	move.b	1(a0),d5			; LDA 5,U; LDB 1,X; MUL; ANDB #$F8
	moveq	#0,d7
	move.b	5(a1),d7
	mulu	d7,d5
	and.w	#$FFF8,d5
	move.b	2(a0),-(sp)			; LDX 2,X; LEAX D,X
	move.w	(sp)+,d2
	move.b	3(a0),d2
	add.w	d5,d2
	moveq	#0,d7
	move.w	d2,d7
	ADR68	d7,a0				; a0 = X (the object's frame)
	move.b	1(a0),$5D(a3)			; LDA 1,X; STA <$5D
	move.b	2(a0),$5E(a3)			; LDD 2,X; STD <$5E
	move.b	3(a0),$5F(a3)
	move.b	$10(a1),$60(a3)			; LDA $10,U; LDB $11,U; STD <$60
	move.b	$11(a1),$61(a3)
	move.b	6(a0),-(sp)			; LDY 6,X
	move.w	(sp)+,d3
	move.b	7(a0),d3
	move.b	$10(a1),d0			; ASLA x3; ROLB; ASLB; ANDB #6
	move.b	$11(a1),d1
	lsl.b	#3,d0				; (C = bit 5 of obj[$10])
	roxl.b	#1,d1
	add.b	d1,d1
	and.b	#6,d1
	moveq	#0,d7				; LDY B,Y (B = 0..6)
	move.b	d1,d7
	add.w	d3,d7
	move.l	a0,-(sp)
	bsr	n_rd16
	move.l	(sp)+,a0
	move.w	d7,d3				; Y
	move.b	(a0),d1				; LDB ,X; BEQ $F78E
	bne.s	.parts
	; no parts: RTS with LDB's flags (C from ASLB: bit 6 of obj[$11])
	move.b	$11(a1),d5
	lsl.b	#2,d5				; (C = bit 6)
	scs	d5
	move.w	#4,d7				; Z
	tst.b	d5
	beq.s	.c0
	addq.w	#1,d7
.c0:	move.w	d7,ccr
	jmp	S6EF78E				; (the RTS: its return candidates, else the dispatcher)

.parts:
	; the loop's pointers: X = [X + 4], Y, U = [$51]; all in their slots?
	move.b	4(a0),-(sp)
	move.w	(sp)+,d5
	move.b	5(a0),d5			; X for the loop (not set yet: the fallback starts at $F754)
	moveq	#0,d7
	move.b	d1,d7				; n
	move.w	d5,d6				; X + 4 n
	and.w	#$1FFF,d6
	add.w	d7,d6
	add.w	d7,d6
	add.w	d7,d6
	add.w	d7,d6
	cmp.w	#$2000,d6
	bhi	.slow
	move.w	d3,d6				; Y + 2 n
	and.w	#$1FFF,d6
	add.w	d7,d6
	add.w	d7,d6
	cmp.w	#$2000,d6
	bhi	.slow
	move.b	$51(a3),-(sp)			; U = [$51]
	move.w	(sp)+,d6
	move.b	$52(a3),d6
	move.w	d6,-(sp)
	and.w	#$1FFF,d6			; U + 16 n
	lsl.w	#4,d7
	add.w	d7,d6
	cmp.w	#$2000,d6
	bhi	.slow_u
	; the fast loop: a0 = X, a1 = Y, a4 = U (VB[1] again at the end), d6 = n - 1
	moveq	#0,d7
	move.w	d5,d7
	move.w	d7,d2				; X (the loop's)
	ADR68	d7,a0
	moveq	#0,d7
	move.w	d3,d7
	ADR68	d7,a1
	moveq	#0,d4
	move.w	(sp)+,d4			; U = [$51]
	moveq	#0,d7
	move.w	d4,d7
	ADR68	d7,a4
	moveq	#0,d6
	move.b	d1,d6
	move.w	d6,-(sp)			; (n)
	subq.w	#1,d6
.part:	move.b	$60(a3),4(a4)			; LDD <$60; STA 4,U; STB 8,U
	move.b	$61(a3),8(a4)
	move.b	1(a0),d1			; LDD <$5E; ADDD ,X++; STB 5,U; ORA 4,U; STA 4,U
	move.b	(a0),d0
	add.b	$5F(a3),d1
	move.b	$5E(a3),d5
	addx.b	d5,d0
	addq.l	#2,a0
	move.b	d1,5(a4)
	or.b	4(a4),d0
	move.b	d0,4(a4)
	move.b	(a0)+,d0			; LDD ,X++; ADDB <$5D; STB 6,U
	move.b	(a0)+,d1
	add.b	$5D(a3),d1
	move.b	d1,6(a4)
	move.b	(a1)+,d1			; LDB ,Y+; SEX; ADDD <$57; STB 7,U; ANDA #1; ORA 6,U; STA 6,U
	move.b	d1,d0
	ext.w	d0
	lsr.w	#8,d0
	add.b	$58(a3),d1
	move.b	$57(a3),d5
	addx.b	d5,d0
	move.b	d1,7(a4)
	and.b	#1,d0
	or.b	6(a4),d0
	move.b	d0,6(a4)
	move.b	(a1)+,d1			; LDB ,Y+; ADDB <$59; STB 9,U
	add.b	$59(a3),d1
	move.w	sr,d5				; (its C stays to the RTS)
	move.b	d1,9(a4)
	lea	16(a4),a4			; LEAU 16,U; DEC ,S; BNE
	dbf	d6,.part
	move.w	(sp)+,d7			; n: X += 4 n, Y += 2 n, U += 16 n
	add.w	d7,d7
	add.w	d7,d3
	add.w	d7,d7
	add.w	d7,d2
	lsl.w	#2,d7
	add.w	d7,d4
	move.l	32+4(a6),a4			; (a4 = VB[1] again)
	clr.b	-1(a5)				; (PSHS B; DEC ,S to 0; PULS B: the 0 stays below S)
	moveq	#0,d1				; B = 0
	move.w	d4,-(sp)			; STU <$51 (N Z of U, V clear, C of the last ADDB)
	move.b	(sp)+,$51(a3)
	move.b	d4,$52(a3)
	and.w	#1,d5
	tst.w	d4
	bpl.s	.n
	or.w	#8,d5
.n:	tst.w	d4
	bne.s	.z
	or.w	#4,d5
.z:	move.w	d5,ccr
	jmp	S6EF78E				; (the RTS)

.slow_u:
	addq.l	#2,sp
.slow:	; the translation from $F754: X = the frame (d2), B = n, A = obj[$10] << 3, Y, U as they are
	jmp	S6EF754

; d7 = a 6809 address (upper word 0) -> d7.w = the big endian word there (d6 a0 used)
n_rd16:
	ADR68	d7,a0
	move.b	(a0),-(sp)
	move.w	(sp)+,d7
	move.b	1(a0),d7
	rts
