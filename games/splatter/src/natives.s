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

; ---- the sub CPU's $F4CF-$F539: the sprite list, once a frame (with $F714: about a third of the two CPUs' time)
;
;   F4CF  slots 1-6 = pages $17E (sprite RAM), $372-$376 (their words at <$1B-<$26); F6A2: byte 9 of the 127 entries
;         from $2800 = 1; [$51] = $2800
;   F587  the objects on screen (x = [$13] - [$9C] + $40 below $1A0): 32 at $019D ($40 apart, [0] set), 2 at $011D
;         ($40) and 16 at $099D ($20, [0] set and bit 0 of [1] clear): their address and key [$16] in a list
;   F53A  seven passes over the list (the thresholds at $F56F, words): an object whose key is at most the pass's
;         threshold is drawn (F6EA) and leaves the list
;   F51E  slot 2 = page $371 (<$1D); F642: the 32 objects at $0B9D ($20) on screen drawn (F6EA); F687: the 32 at
;         $0F9D ($20, [0] set) drawn by F78F; F6B1: sprite RAM $7F4-$7FF from $F6E2 or $F6E6 (<$3C eor <$3B zero or
;         not), 0, $F6DC; F532: $7F2 = the last of them (the list's latch)
;   F6EA  [$57] = [$13] - [$9C]; B = [$11] & $1F + $20 (+ $20 when [$17] >= $10, + $20 more when >= $40);
;         [$59] = -([$17] - $20 + [$1A] - [$A0]); [$11] = B; then F714 (sub_sprites' work)
;   F78F  [$57] = [$13]; [$59] = -[$1A]; F714
; The list lives on the 6809 stack (S1 = S - $A0 up), in RAM both CPUs share: the main CPU reads it.  So every byte the
; routine leaves on the stack is written here too (SST: the pushes' final values, the list with drawn entries cleared);
; sl_list is a copy for the passes.
; Registers at the RTS: A = [$F6E1], B = 0, X = $3000, Y = $F6E2 / $F6E6 + 4, U = $F6E2; no flags read after it.

SL_BANK	macro	; \1 = slot, \2 = page: the bank (when it changes) and its word at <\3
	move.b	#(\2)>>8,\3(a3)
	move.b	#(\2)&$FF,\3+1(a3)
	cmp.w	#\2,PID+\1*2(a6)
	beq.s	.k\@
	move.w	#\2,d7
	move.w	#\1*2,d6
	bsr	bank_set
.k\@:
	endm

S1	= -$A0				; (the list's start below S, a5)

SST	macro	; \1 = a byte (immediate or register), \2 = k: [S1 - k]
	move.b	\1,S1-\2(a5)
	endm

sub_spritelist:
	move.b	#$F5,-2(a5)		; (JSR $F6A2's return address)
	move.b	#$02,-1(a5)
	move.l	a5,d7			; S1 as a 6809 address
	sub.l	a3,d7
	sub.w	#-S1,d7
	move.w	d7,sl_s1
	SL_BANK	1,$017E,$1B
	SL_BANK	2,$0372,$1D
	SL_BANK	3,$0373,$1F
	SL_BANK	4,$0374,$21
	SL_BANK	5,$0375,$23
	SL_BANK	6,$0376,$25
	moveq	#1,d0			; (F6A2: byte 9 of the 127 entries from $2809, slot 1: a4 = VB[1])
SL_K	set	0
	rept	127
	move.b	d0,$2809+SL_K(a4)
SL_K	set	SL_K+16
	endr
	move.b	#$28,$51(a3)		; [$51] = $2800
	clr.b	$52(a3)
	; F587: the list (a0 here, a1 on the 6809 stack)
	lea	sl_list,a0
	lea	S1(a5),a1
	move.b	$9C(a3),-(sp)
	move.w	(sp)+,d5
	move.b	$9D(a3),d5		; [$9C]
	moveq	#0,d4
	move.w	#$019D,d4
	moveq	#32-1,d6
	moveq	#0,d3			; (no bit 0 test)
	moveq	#$40,d2
	bsr	sl_gather
	move.w	#$011D,d4
	moveq	#2-1,d6
	moveq	#1,d3
	bsr	sl_gather
	move.w	#$099D,d4
	moveq	#16-1,d6
	moveq	#$20,d2
	bsr	sl_gather
	move.l	a0,sl_end
	move.l	a0,d6			; n
	sub.l	#sl_list,d6
	lsr.w	#2,d6
	move.w	sl_s1,d7
	SST	#0,6			; (F587's stack: its counter, n, X = S1, BSR's return; then PSHS B)
	SST	d6,5
	SST	d7,3
	ror.w	#8,d7
	SST	d7,4
	SST	#$F5,2
	SST	d6,1
	; F53A: the passes
	tst.w	d6
	beq	.nolist
	SST	#$F5,2			; (BSR $F53A's return, PSHS B)
	SST	#$1E,1
	SST	d6,3
	move.w	sl_s1,d7
	SST	d7,4			; (PSHS X,B each pass: X = S1)
	ror.w	#8,d7
	SST	d7,5
	SST	#0,7			; (the entries' counter, 0 after each pass)
	lea	S1-14(a5),a0
	move.l	a0,sl_pb		; (F754's PSHS B in a part: there)
	lea	$156F(a2),a0		; the thresholds ($F56F, slot 7)
	moveq	#7-1,d0
.pass:	move.b	d0,d7			; (PSHS X,B: the pass counter, 7 - pass = d0 + 1)
	addq.b	#1,d7
	SST	d7,6
	move.b	(a0)+,-(sp)
	move.w	(sp)+,d1
	move.b	(a0)+,d1		; the threshold
	move.l	a0,-(sp)
	lea	sl_list,a0
.ent:	moveq	#0,d4
	move.w	(a0),d4			; the object (0: drawn)
	beq.s	.nx
	cmp.w	2(a0),d1
	bcs.s	.nx			; (threshold below the key)
	clr.w	(a0)
	movem.l	d0-d1/a0,-(sp)
	; the 6809 stack: the entry's U cleared, PSHS Y,X (Y = $F56F + 2 * pass, X = the entry), JSR's return $F558
	move.l	a0,d7
	sub.l	#sl_list,d7
	lea	S1(a5),a1
	add.w	d7,a1
	clr.b	(a1)+
	clr.b	(a1)
	add.w	sl_s1,d7		; X
	SST	d7,10
	ror.w	#8,d7
	SST	d7,11
	move.w	#$F56F+2*6,d7		; Y = $F56F + 2 * (6 - d0)
	sub.w	d0,d7
	sub.w	d0,d7
	SST	d7,8
	ror.w	#8,d7
	SST	d7,9
	SST	#$F5,13
	SST	#$58,12
	bsr	sl_f6ea
	movem.l	(sp)+,d0-d1/a0
.nx:	addq.l	#4,a0
	cmp.l	sl_end,a0
	bne.s	.ent
	move.l	(sp)+,a0
	dbf	d0,.pass
.nolist:
	SL_BANK	2,$0371,$1D
	; F642 (the 6809 stack: JSR's return, its counter (0 at the end), PSHS U and JSR $F6EA's return for each drawn)
	SST	#$F5,2
	SST	#$2C,1
	SST	#0,3
	lea	S1-8(a5),a0
	move.l	a0,sl_pb
	move.b	$9C(a3),-(sp)
	move.w	(sp)+,d5
	move.b	$9D(a3),d5
	moveq	#0,d4
	move.w	#$0B9D,d4
	moveq	#32-1,d6
.f642:	tst.b	(a3,d4.l)
	beq.s	.n642
	move.b	$13(a3,d4.l),-(sp)
	move.w	(sp)+,d7
	move.b	$14(a3,d4.l),d7
	sub.w	d5,d7
	add.w	#$40,d7
	cmp.w	#$1A0,d7
	bcc.s	.n642
	SST	d4,4
	move.w	d4,d7
	lsr.w	#8,d7
	SST	d7,5
	SST	#$F6,7
	SST	#$60,6
	movem.l	d4-d6,-(sp)
	bsr	sl_f6ea
	movem.l	(sp)+,d4-d6
.n642:	add.w	#$20,d4
	dbf	d6,.f642
	; F687 (the same with JSR $F78F's return)
	SST	#$F5,2
	SST	#$2F,1
	SST	#0,3
	move.w	#$0F9D,d4
	moveq	#32-1,d6
.f687:	tst.b	(a3,d4.l)
	beq.s	.n687
	move.l	d6,-(sp)
	SST	d4,4
	move.w	d4,d7
	lsr.w	#8,d7
	SST	d7,5
	SST	#$F6,7
	SST	#$97,6
	lea	(a3,d4.l),a1
	move.b	$13(a1),$57(a3)		; [$57] = [$13]
	move.b	$14(a1),$58(a3)
	move.b	$1A(a1),d7		; [$59] = -[$1A]
	neg.b	d7
	move.b	d7,$59(a3)
	move.w	d4,-(sp)
	bsr	sl_core
	move.w	(sp)+,d4
	move.l	(sp)+,d6
.n687:	add.w	#$20,d4
	dbf	d6,.f687
	SST	#$F5,2			; (JSR $F6B1's return)
	SST	#$32,1
	; F6B1: sprite RAM $7F4-$7FF
	lea	$2FF4(a4),a0
	lea	$16E2(a2),a1		; ($F6E2)
	move.w	#$F6E2,d3
	move.b	$3C(a3),d7
	move.b	$3B(a3),d6
	eor.b	d6,d7
	beq.s	.y
	addq.l	#4,a1
	addq.w	#4,d3
.y:	addq.w	#4,d3			; Y
	move.b	(a1)+,(a0)+
	move.b	(a1)+,(a0)+
	move.b	(a1)+,(a0)+
	move.b	(a1)+,(a0)+
	clr.b	(a0)+
	clr.b	(a0)+
	lea	$16DC(a2),a1		; ($F6DC)
	moveq	#6-1,d7
.cp:	move.b	(a1)+,(a0)+
	dbf	d7,.cp
	move.b	-1(a1),d0		; A = [$F6E1]
	move.b	d0,$2FF2(a4)		; STA $2FF2: the latch
	st	sprite_latch
	moveq	#0,d1			; B
	moveq	#0,d2
	move.w	#$3000,d2		; X
	and.l	#$FFFF,d3		; Y
	moveq	#0,d4
	move.w	#$F6E2,d4		; U
	jmp	S6EF539			; (the RTS)

; F587's loops: d4 = the first object, d6 = count - 1, d2 = the stride, d3 = 1: bit 0 of [1] must be clear too;
; d5 = [$9C];
; a0 = the list's end (object.w, key.w)
sl_gather:
.l:	tst.b	(a3,d4.l)
	beq.s	.n
	tst.b	d3
	beq.s	.x
	btst	#0,1(a3,d4.l)
	bne.s	.n
.x:	move.b	$13(a3,d4.l),-(sp)
	move.w	(sp)+,d7
	move.b	$14(a3,d4.l),d7
	sub.w	d5,d7
	add.w	#$40,d7
	cmp.w	#$1A0,d7
	bcc.s	.n
	move.w	d4,(a0)+
	move.b	$16(a3,d4.l),(a0)+
	move.b	$17(a3,d4.l),(a0)+
	move.w	-4(a0),d7		; (the same on the 6809 stack)
	move.w	d7,-(sp)
	move.b	(sp)+,(a1)+
	move.b	d7,(a1)+
	move.b	-2(a0),(a1)+
	move.b	-1(a0),(a1)+
.n:	add.w	d2,d4
	dbf	d6,.l
	rts

; F6EA for the object at d4 (slot 0)
sl_f6ea:
	lea	(a3,d4.l),a1
	move.b	$13(a1),-(sp)		; [$57] = [$13] - [$9C]
	move.w	(sp)+,d7
	move.b	$14(a1),d7
	move.b	$9C(a3),-(sp)
	move.w	(sp)+,d6
	move.b	$9D(a3),d6
	sub.w	d6,d7
	move.b	d7,$58(a3)
	lsr.w	#8,d7
	move.b	d7,$57(a3)
	move.b	$11(a1),d1		; B
	and.b	#$1F,d1
	add.b	#$20,d1
	move.b	$17(a1),d0		; A
	cmp.b	#$10,d0
	bcs.s	.b
	add.b	#$20,d1
	cmp.b	#$40,d0
	bcs.s	.b
	add.b	#$20,d1
.b:	sub.b	#$20,d0
	add.b	$1A(a1),d0
	sub.b	$A0(a3),d0
	neg.b	d0
	move.b	d0,$59(a3)
	move.b	d1,$11(a1)
	; fall into sl_core

; F714-F78E for the object at d4 (a1 = it): sub_sprites' work, without the 6809 registers
sl_core:
	moveq	#0,d7
	move.b	8(a1),d7		; X = [$F57D + 2 * obj[8]] (B signed)
	add.b	d7,d7
	ext.w	d7
	lea	$157D(a2),a0
	move.b	(a0,d7.w),-(sp)
	move.w	(sp)+,d2
	move.b	1(a0,d7.w),d2
	moveq	#0,d7
	move.b	9(a1),d7		; X = [X + 2 * obj[9]]
	add.w	d7,d7
	add.w	d2,d7
	bsr	n_rd16
	move.w	d7,d2
	move.b	4(a1),d7		; X += 4 * obj[4] (8 bit)
	add.b	d7,d7
	add.b	d7,d7
	and.w	#$FF,d7
	add.w	d7,d2
	moveq	#0,d7
	move.w	d2,d7
	ADR68	d7,a0
	moveq	#0,d5			; D = obj[5] * X[1] & ~7
	move.b	1(a0),d5
	moveq	#0,d7
	move.b	5(a1),d7
	mulu	d7,d5
	and.w	#$FFF8,d5
	move.b	2(a0),-(sp)		; X = [X + 2] + D
	move.w	(sp)+,d2
	move.b	3(a0),d2
	add.w	d5,d2
	moveq	#0,d7
	move.w	d2,d7
	ADR68	d7,a0
	move.b	1(a0),$5D(a3)
	move.b	2(a0),$5E(a3)
	move.b	3(a0),$5F(a3)
	move.b	$10(a1),$60(a3)
	move.b	$11(a1),$61(a3)
	move.b	6(a0),-(sp)		; Y = [X + 6]
	move.w	(sp)+,d3
	move.b	7(a0),d3
	move.b	$10(a1),d0		; B = (obj[$11] << 2 | bit 5 of obj[$10] << 1) & 6
	move.b	$11(a1),d1
	lsl.b	#3,d0
	roxl.b	#1,d1
	add.b	d1,d1
	and.b	#6,d1
	moveq	#0,d7			; Y = [Y + B]
	move.b	d1,d7
	add.w	d3,d7
	move.l	a0,-(sp)
	bsr	n_rd16
	move.l	(sp)+,a0
	move.w	d7,d3
	moveq	#0,d6
	move.b	(a0),d6			; the parts
	beq	.out
	move.l	sl_pb,a1		; (F754's PSHS B: 0 after the parts)
	clr.b	(a1)
	move.b	4(a0),-(sp)		; X = [X + 4]
	move.w	(sp)+,d2
	move.b	5(a0),d2
	move.b	$51(a3),-(sp)		; U = [$51]
	move.w	(sp)+,d4
	move.b	$52(a3),d4
	; in their slots all the way?  (else a part at a time through ADR68)
	move.w	d6,d7
	lsl.w	#2,d7
	move.w	d2,d5
	and.w	#$1FFF,d5
	add.w	d7,d5
	cmp.w	#$2000,d5
	bhi	.slow
	move.w	d6,d7
	add.w	d7,d7
	move.w	d3,d5
	and.w	#$1FFF,d5
	add.w	d7,d5
	cmp.w	#$2000,d5
	bhi	.slow
	move.w	d6,d7
	lsl.w	#4,d7
	move.w	d4,d5
	and.w	#$1FFF,d5
	add.w	d7,d5
	cmp.w	#$2000,d5
	bhi	.slow
	move.l	a4,-(sp)
	move.w	d6,-(sp)		; (ADR68 uses d6)
	moveq	#0,d7
	move.w	d2,d7
	ADR68	d7,a0			; a0 = X
	moveq	#0,d7
	move.w	d3,d7
	ADR68	d7,a1			; a1 = Y
	moveq	#0,d7
	move.w	d4,d7
	ADR68	d7,a4			; a4 = U
	move.w	(sp)+,d6
	lsl.w	#4,d6
	add.w	d6,d4			; U at the end
	move.l	a2,-(sp)
	lea	(a4,d6.w),a2		; (the end)
	move.w	d4,-(sp)
	move.b	$5F(a3),d2		; the part's constants in registers
	move.b	$5E(a3),d4
	move.b	$60(a3),d5
	move.b	$61(a3),d6
	move.b	$5D(a3),d7
	move.b	$57(a3),-(sp)
	move.w	(sp)+,d3
	move.b	$58(a3),d3		; [$57]
.part:	move.b	(a0)+,d0		; U[4] U[5] = $60 | [$5E] + [X]
	move.b	(a0)+,d1
	add.b	d2,d1
	addx.b	d4,d0
	move.b	d1,5(a4)
	or.b	d5,d0
	move.b	d0,4(a4)
	move.b	d6,8(a4)		; U[8] = [$61]
	addq.l	#1,a0			; U[6] = (low of [X + 2]) + [$5D] | bit 8 of (sext [Y] + [$57]); U[7] = low of that
	move.b	(a0)+,d1
	add.b	d7,d1
	move.b	(a1)+,d0
	ext.w	d0
	add.w	d3,d0
	move.b	d0,7(a4)
	move.w	d0,-(sp)
	move.b	(sp)+,d0
	and.b	#1,d0
	or.b	d0,d1
	move.b	d1,6(a4)
	move.b	(a1)+,d1		; U[9] = [Y + 1] + [$59]
	add.b	$59(a3),d1
	move.b	d1,9(a4)
	lea	16(a4),a4
	cmpa.l	a2,a4
	bne.s	.part
	move.w	(sp)+,d4
	move.l	(sp)+,a2
	move.l	(sp)+,a4
	bra	.end
.slow:	subq.w	#1,d6			; a part at a time: X d2, Y d3, U d4
.sp:	move.w	d6,-(sp)
	moveq	#0,d7
	move.w	d4,d7
	ADR68	d7,a1			; (U: its 10 bytes stay in one slot: entries are 16-byte aligned)
	move.b	$60(a3),4(a1)
	move.b	$61(a3),8(a1)
	bsr	sl_rdx			; d7 = [X++]
	move.w	d7,d0
	lsr.w	#8,d0
	add.b	$5F(a3),d7
	move.b	$5E(a3),d5
	addx.b	d5,d0
	move.b	d7,5(a1)
	or.b	4(a1),d0
	move.b	d0,4(a1)
	bsr	sl_rdx
	add.b	$5D(a3),d7
	move.b	d7,6(a1)
	moveq	#0,d7
	move.w	d3,d7
	ADR68	d7,a0
	move.b	(a0),d1
	addq.w	#1,d3
	move.b	d1,d0
	ext.w	d0
	lsr.w	#8,d0
	add.b	$58(a3),d1
	move.b	$57(a3),d5
	addx.b	d5,d0
	move.b	d1,7(a1)
	and.b	#1,d0
	or.b	6(a1),d0
	move.b	d0,6(a1)
	moveq	#0,d7
	move.w	d3,d7
	ADR68	d7,a0
	move.b	(a0),d1
	addq.w	#1,d3
	add.b	$59(a3),d1
	move.b	d1,9(a1)
	add.w	#16,d4
	move.w	(sp)+,d6
	dbf	d6,.sp
.end:	move.b	d4,$52(a3)		; [$51] = U
	lsr.w	#8,d4
	move.b	d4,$51(a3)
.out:	rts

; d7.w = the word at X (d2), X += 2 (each byte through ADR68: X may cross a slot)
sl_rdx:
	moveq	#0,d7
	move.w	d2,d7
	ADR68	d7,a0
	move.b	(a0),-(sp)
	addq.w	#1,d2
	moveq	#0,d7
	move.w	d2,d7
	ADR68	d7,a0
	move.w	(sp)+,d7
	move.b	(a0),d7
	addq.w	#1,d2
	rts

; ---- the main CPU's $CA57-$CA87: X[6..9] = the word at X times the word at X+2 (two passes of two MULs)
;
;   CA57  B = 2; PSHS U,Y,B; Y = X + 4, U = X + 8; X[6..9] = 0; per pass: D = X[1] * [-Y] + [U]; [U] = D;
;         [U-1] += [U-1] + C; D = X[0] * [Y] + [-U]; [U] = D; [U-1] += [U-1] + C; DEC ,S; PULS B,Y,U,PC
; The product fits in 32 bits, so the carries into X[6] are the product's and the last one is 0: X[6..9] = the
; product, and the second pass's ADCA doubles X[5] (A = that, C = its old bit 7).  X lies in slot 0, as the
; translation's sites (a3).  Flags are not live after the PULS.

main_mul16:
	lea	(a3,d2.l),a0			; a0 = X
	move.b	d4,-1(a5)			; PSHS U,Y,B (B = 0 after the passes)
	move.w	d4,-(sp)
	move.b	(sp)+,-2(a5)
	move.b	d3,-3(a5)
	move.w	d3,-(sp)
	move.b	(sp)+,-4(a5)
	clr.b	-5(a5)
	move.b	(a0),-(sp)			; the two words (X may be odd)
	move.w	(sp)+,d7
	move.b	1(a0),d7
	move.b	2(a0),-(sp)
	move.w	(sp)+,d6
	move.b	3(a0),d6
	mulu	d6,d7
	move.b	d7,9(a0)
	lsr.l	#8,d7
	move.b	d7,8(a0)
	lsr.l	#8,d7
	move.b	d7,7(a0)
	lsr.w	#8,d7
	move.b	d7,6(a0)
	move.b	5(a0),d0			; X[5] doubled: A
	add.b	d0,d0
	move.b	d0,5(a0)
	subq.l	#5,a5				; (S at the PULS: B Y U PC)
	jmp	M7FCA87

; ---- the main CPU's $C5D5-$C5FF with $C630-$C649: the background's class under an object (7 calls a frame)
;
;   C5D5  PSHS D; D = sext B + [$13,U]; X = $C600 + (A << 2, signed); <$0F = $E600 = [X] (slot 3's bank); X = [X+2];
;         PULS D; B = (B + [$14,U]) >> 1; A = (A + [$1A,U]) >> 4 (C = bit 3); B = (B >> 1 | C << 7) & $FE;
;         D = [X + D] (slot 3); BSR $C630; RTS
;   C630  PSHS X,D; PSHS D; X = $C64B; [2,S] = $0004; PULS D; the thresholds at X (words, rising): while D is not
;         below the next one, [0,S] += 1 and [1,S] -= 1 (four at most); PULS D,X,PC: A = their count, B = 4 - it
; Flags are not live after the RTS (its callers TSTA, PSHS A or return).  The stack bytes below S are written as the
; routine leaves them.

main_bgclass:
	move.b	d0,d5				; (A B of the entry)
	move.b	d1,d6
	lea	(a3,d4.l),a1			; a1 = U (slot 0)
	move.b	$13(a1),-(sp)			; SEX; ADDD $13,U
	move.w	(sp)+,d7
	move.b	$14(a1),d7
	ext.w	d1
	add.w	d1,d7
	lsr.w	#8,d7				; ASLA; ASLA; LEAX A,X (X = $C600 + signed)
	lsl.b	#2,d7
	ext.w	d7
	add.w	#$C600,d7
	and.l	#$FFFF,d7
	move.l	VB+6*4(a6),a0			; (slot 6, this code's page)
	move.b	(a0,d7.l),d0			; LDD ,X; STD <$0F; STD $E600
	move.b	1(a0,d7.l),d1
	move.b	d0,$F(a3)
	move.b	d1,$10(a3)
	move.b	2(a0,d7.l),-(sp)		; LDX 2,X
	move.w	(sp)+,d2
	move.b	3(a0,d7.l),d2
	move.b	d0,-(sp)
	move.w	(sp)+,d7
	move.b	d1,d7
	and.w	#$3FF,d7
	cmp.w	PID+3*2(a6),d7
	beq.s	.bank
	move.w	d7,PID+3*2(a6)
	add.w	d7,d7
	add.w	d7,d7
	lea	page_base_table,a0
	move.l	(a0,d7.w),a0
	move.l	a0,PB+3*4(a6)
	suba.l	#$6000,a0
	move.l	a0,VB+3*4(a6)
.bank:	add.b	$14(a1),d6			; PULS D; ADDB $14,U; LSRB
	lsr.b	#1,d6
	add.b	$1A(a1),d5			; ADDA $1A,U; LSRA x4 (C = bit 3 of the sum); RORB; ANDB #$FE
	lsr.b	#1,d6
	btst	#3,d5
	beq.s	.c0
	or.b	#$80,d6
.c0:	and.b	#$FE,d6
	lsr.b	#4,d5
	move.b	d5,-(sp)			; LDD D,X (slot 3)
	move.w	(sp)+,d7
	move.b	d6,d7
	add.w	d2,d7
	and.l	#$FFFF,d7
	move.l	VB+3*4(a6),a0
	move.b	(a0,d7.l),-(sp)
	move.w	(sp)+,d5
	move.b	1(a0,d7.l),d5			; d5 = the map word
	move.b	#$C5,-2(a5)			; BSR $C630 (its return address $C5FF)
	move.b	#$FF,-1(a5)
	move.b	d2,-3(a5)			; PSHS X,D; PSHS D
	move.w	d2,-(sp)
	move.b	(sp)+,-4(a5)
	move.b	d5,-7(a5)
	move.w	d5,-(sp)
	move.b	(sp)+,-8(a5)
	move.l	VB+6*4(a6),a0			; the thresholds at $C64B
	adda.l	#$C64B,a0
	moveq	#0,d0				; A = the count
	moveq	#4-1,d6
.cmp:	move.b	(a0)+,-(sp)
	move.w	(sp)+,d7
	move.b	(a0)+,d7
	cmp.w	d7,d5
	bcs.s	.done
	addq.b	#1,d0
	dbf	d6,.cmp
.done:	moveq	#4,d1				; B = 4 - A
	sub.b	d0,d1
	move.b	d0,-6(a5)
	move.b	d1,-5(a5)
	jmp	M7FC5FF				; (the RTS: its return candidates, else the dispatcher)
