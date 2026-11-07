; Dragon Spirit: hand-written replacements of hot 6809 routines (tools/gen.py NATIVES; included by dspirit.s).  Each
; leaves A B X Y U, the memory and the flags as the 6809 does where the translation goes on.  tools/logic_test.py
; checks them in lock-step; NO_NATIVES=1 builds without them.
;
; Registers (engine/m6809x.py, core.s): d0 A, d1 B (bytes), d2 X, d3 Y, d4 U (words, upper words 0), a3 = VB of the
; direct page's slot (the main CPU: slot 2, the work RAM), a6 the context; d5-d7, a0, a1 scratch.

	section text,code

; $C37F, the main CPU's object slots (X the slot, $28 bytes each; <$E1 the slots left):
;   loop: LDU #$C39B; LDA $1,X; LDB #2; MUL; LDY D,U; LDA ,X; BEQ next; ASLA; JSR [A,Y]
;   next: DEC <$E1; BNE more; RTS;  more: LEAX $28,X; BRA loop
; A slot without a routine (X[0] = 0) and not the last: skipped here (its DEC and LEAX; what it loads into U D Y the
; next slot loads again).  A slot with a routine, or the last slot: U, D (= X[1] * 2) and Y (the word at $C39B + D,
; slot 6) set as the loop's head sets them, then the translation goes on at $C38A (LDA ,X: the flags are its own).
nat_slots_C37F:
.l:	tst.b	(a3,d2.l)
	bne.s	.go
	cmp.b	#1,$40E1(a3)
	beq.s	.go
	subq.b	#1,$40E1(a3)
	add.w	#$28,d2
	bra.s	.l
.go:	move.w	#$C39B,d4		; U
	moveq	#0,d7
	move.b	1(a3,d2.l),d7
	add.w	d7,d7			; D = X[1] * 2
	move.b	d7,d1			; B
	move.w	d7,d6
	lsr.w	#8,d6
	move.b	d6,d0			; A
	add.w	d4,d7
	move.l	56(a6),a0		; (VB[6])
	moveq	#0,d3
	move.b	(a0,d7.l),d3		; Y
	lsl.w	#8,d3
	move.b	1(a0,d7.l),d3
	jmp	M7FC38A

; $7A54, a column of tiles (main CPU; slot 0: tile RAM):
;   loop: STU ,Y; TFR Y,D; TSTB; BNE p; STU -$2,Y; BRA n;  p: STU $7E,Y;  n: SUBD #$80; ANDA #$0F; TFR D,Y
;         DEC <$D5; BNE loop; RTS
; U at Y and at Y + $7E (Y's low byte 0: at Y - 2, through main_io_w as the translation: $FFFE is the MMU's), Y
; stepped back $80 in $0000-$0FFF, <$D5 times.  At the RTS: D = Y, the flags DEC's (Z set, N V clear) with the last
; SUBD's borrow in C.
nat_fill_7A54:
	st	tile_written+3		; (the translation's writer flags: layer 3, the fixed layers)
	st	tile_written+4
	move.w	d4,d5
	lsr.w	#8,d5			; U's high byte
	move.l	32(a6),a1		; VB[0]
.l:	move.b	d5,(a1,d3.l)
	move.b	d4,1(a1,d3.l)
	tst.b	d3
	bne.s	.p
	moveq	#0,d7			; STU -$2,Y
	move.w	d3,d7
	subq.w	#2,d7
	move.w	d7,-(sp)
	move.w	d4,d5
	lsr.w	#8,d5
	bsr	main_io_w
	move.w	(sp)+,d7
	addq.w	#1,d7
	move.b	d4,d5
	bsr	main_io_w
	move.w	d4,d5
	lsr.w	#8,d5
	move.l	32(a6),a1		; (an MMU write may have moved slot 0)
	bra.s	.n
.p:	move.b	d5,$7E(a1,d3.l)
	move.b	d4,$7F(a1,d3.l)
.n:	move.w	d3,d6			; (the borrow: Y below $80)
	sub.w	#$80,d3
	and.w	#$0FFF,d3
	subq.b	#1,$40D5(a3)
	bne.s	.l
	move.b	d3,d1			; D = Y
	move.w	d3,d7
	lsr.w	#8,d7
	move.b	d7,d0
	moveq	#$04,d7			; Z
	cmp.w	#$80,d6
	bcc.s	.c
	moveq	#$05,d7			; Z C
.c:	move	d7,ccr
	jmp	M76DA6D

; $C0DB, a 4 x 4 block of tile words (main CPU; from the stage's tile streaming, $C025): 16 times LDD ,Y++; ADDA <$D5;
; STD k,U with k = 0, -$80, -$100, -$180, then 2, -$7E .. (columns of 4); RTS.  Y's 32 bytes in one slot (else the
; translation), U's stores into slot 0 as the translation does them (its writer flags: layers 0-2).  At the RTS: D the
; last word, Y + 32, the flags STD's (N Z of D, V clear) with the last ADDA's carry in C (and X).
BLK_OFS	macro
	move.b	(a0)+,d0
	move.b	(a0)+,d1
	add.b	d5,d0
	move.b	d0,\1(a1)
	move.b	d1,\1+1(a1)
	endm
nat_block_C0DB:
	move.w	d3,d6
	and.w	#$1FFF,d6
	cmp.w	#$2000-32,d6
	bhi	M7FC0DB_t
	move.w	d3,d6
	rol.w	#3,d6
	and.w	#7,d6
	add.w	d6,d6
	add.w	d6,d6
	move.l	32(a6,d6.w),a0
	add.l	d3,a0			; the source
	add.w	#32,d3			; (Y++ 16 times)
	move.l	32(a6),a1
	add.l	d4,a1			; U in slot 0
	move.b	$40D5(a3),d5
	st	tile_written+0
	st	tile_written+1
	st	tile_written+2
	BLK_OFS	0
	BLK_OFS	-$80
	BLK_OFS	-$100
	BLK_OFS	-$180
	BLK_OFS	2
	BLK_OFS	-$7E
	BLK_OFS	-$FE
	BLK_OFS	-$17E
	BLK_OFS	4
	BLK_OFS	-$7C
	BLK_OFS	-$FC
	BLK_OFS	-$17C
	BLK_OFS	6
	BLK_OFS	-$7A
	BLK_OFS	-$FA
	move.b	(a0)+,d0		; (the last: its carry kept)
	move.b	(a0)+,d1
	add.b	d5,d0
	scs	d6
	move.b	d0,-$17A(a1)
	move.b	d1,-$179(a1)
	move.b	d0,-(sp)		; (moves: X stays the carry)
	move.w	(sp)+,d7
	move.b	d1,d7
	tst.b	d6
	beq.s	.nc
	tst.w	d7
	ori	#1,ccr
	jmp	M7FC14F
.nc:	tst.w	d7
	jmp	M7FC14F
