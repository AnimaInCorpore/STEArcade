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
	moveq	#0,d6
	move.b	$40E1(a3),d6
	bne.s	.c
	jmp	M7FC37F_t		; (0 slots left: the 6809 would go on 256 more)
.c:	subq.w	#2,d6			; (the slots that may be skipped, less 1; -1: the last slot)
	bmi.s	.f
	lea	(a3,d2.l),a0
.l:	tst.b	(a0)
	bne.s	.s
	lea	40(a0),a0
	dbra	d6,.l
.s:	move.l	a0,d2
	sub.l	a3,d2			; X
.f:	addq.w	#2,d6
	move.b	d6,$40E1(a3)		; (the slots left)
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

; a word from a 68000 address (bytes: the 6809 has no alignment) into \2.w
RDW	macro
	move.b	\1,\2
	lsl.w	#8,\2
	move.b	1+\1,\2
	endm

; $F4B0, the enemy slots against the object at X (main CPU; U the slot, $28 bytes each, <$D5 the slots left, Y a
; box: 4 bytes of x, then y's offset and range):
;   loop: LDA ,U; BEQ n; CMPA #2; BEQ n; LDA 1,U; CMPA #1; BEQ n; CMPA #7; BEQ n
;         LDA $A,X; SUBA $A,U; ADDA 4,Y; CMPA 5,Y; BHI n; LDD 6,X; SUBD 6,U; ADDD ,Y; SUBD 2,Y; BCS $F4E1
;   n:    DEC <$D5; LBEQ $F417; LEAU $28,U; BRA loop
; A B U <$D5 as the loop leaves them; no flags live at $F417 or $F4E1 (tools/gen.py live_main.json).  Y's 6 bytes in
; one slot (else the translation).
nat_scan_F4B0:
	move.w	d3,d6
	and.w	#$1FFF,d6
	cmp.w	#$1FFA,d6
	bls.s	.y
	jmp	M7FF4B0_t
.y:	move.w	d3,d6
	rol.w	#3,d6
	and.w	#7,d6
	add.w	d6,d6
	add.w	d6,d6
	move.l	32(a6,d6.w),a0
	add.l	d3,a0			; Y
	lea	(a3,d4.l),a1		; U
	move.b	$40D5(a3),d5
.l:	move.b	(a1),d0
	beq.s	.n
	cmp.b	#2,d0
	beq.s	.n
	move.b	1(a1),d0
	cmp.b	#1,d0
	beq.s	.n
	cmp.b	#7,d0
	beq.s	.n
	move.b	10(a3,d2.l),d0
	sub.b	10(a1),d0
	add.b	4(a0),d0
	cmp.b	5(a0),d0
	bhi.s	.n
	RDW	6(a3,d2.l),d7
	move.w	6(a1),d6		; (U even, a3 even)
	sub.w	d6,d7
	RDW	0(a0),d6
	add.w	d6,d7
	RDW	2(a0),d6
	sub.w	d6,d7
	bcs.s	.hit
	move.b	d7,d1
	lsr.w	#8,d7
	move.b	d7,d0
.n:	subq.b	#1,d5
	beq.s	.done
	lea	40(a1),a1
	bra.s	.l
.hit:	move.b	d7,d1
	lsr.w	#8,d7
	move.b	d7,d0
	move.b	d5,$40D5(a3)
	move.l	a1,d4
	sub.l	a3,d4
	jmp	M7FF4E1
.done:	move.b	d5,$40D5(a3)
	move.l	a1,d4
	sub.l	a3,d4
	jmp	M7FF417

; $F6C7, the same scan for the object at X of kind 1 against slots of kind 1 / state 2 (Y in slot 7, as the
; translation has it):
;   loop: LDA 1,U; CMPA #1; BNE n; LDA ,U; CMPA #2; BNE n; LDA ,X; CMPA #1; BNE n
;         LDA $A,X; SUBA $A,U; ADDA 4,Y; CMPA 5,Y; BHI n; LDD 6,X; SUBD 6,U; ADDD ,Y; SUBD 2,Y; BCC n
;         LDA $16,U; CMPA #6; BCS $F721
;   n:    DEC <$D5; BEQ $F6FD; LEAU $28,U; BRA loop
nat_scan_F6C7:
	move.l	60(a6),a0
	add.l	d3,a0			; Y (VB[7])
	lea	(a3,d4.l),a1		; U
	move.b	$40D5(a3),d5
.l:	move.b	1(a1),d0
	cmp.b	#1,d0
	bne.s	.n
	move.b	(a1),d0
	cmp.b	#2,d0
	bne.s	.n
	move.b	(a3,d2.l),d0
	cmp.b	#1,d0
	bne.s	.n
	move.b	10(a3,d2.l),d0
	sub.b	10(a1),d0
	add.b	4(a0),d0
	cmp.b	5(a0),d0
	bhi.s	.n
	RDW	6(a3,d2.l),d7
	move.w	6(a1),d6
	sub.w	d6,d7
	RDW	0(a0),d6
	add.w	d6,d7
	RDW	2(a0),d6
	sub.w	d6,d7
	bcc.s	.nd
	move.b	d7,d1
	move.b	22(a1),d0
	cmp.b	#6,d0
	bcs.s	.hit
	bra.s	.n
.nd:	move.b	d7,d1
	lsr.w	#8,d7
	move.b	d7,d0
.n:	subq.b	#1,d5
	beq.s	.done
	lea	40(a1),a1
	bra.s	.l
.hit:	move.b	d5,$40D5(a3)
	move.l	a1,d4
	sub.l	a3,d4
	jmp	M7FF721
.done:	move.b	d5,$40D5(a3)
	move.l	a1,d4
	sub.l	a3,d4
	jmp	M7FF6FD

; $836C, a flag bit from A's bit 0 into a pair of bytes at Y (main CPU; Y in slot 2):
;   CLR <$D7; LSRA; ROL <$D7; LDB 1,Y; EORB <$D7; ANDB <$D7; STB ,Y; LDB <$D7; STB 1,Y; RTS
; C is live at the RTS: ROL's, old bit 7 of the cleared <$D7: 0 (and N Z of the last STB, V clear: move.b).
nat_bit_836C:
	moveq	#0,d6
	lsr.b	#1,d0
	addx.b	d6,d6			; the bit
	move.b	d6,$40D7(a3)
	move.b	1(a3,d3.l),d1
	eor.b	d6,d1
	and.b	d6,d1
	move.b	d1,(a3,d3.l)
	move.b	d6,d1
	move.b	d1,1(a3,d3.l)
	jmp	M7F837D

; $8277, a 17 bit position step (main CPU; X Y U in slot 2):
;   LDD 1,X; ADDD 1,Y; STD 1,X; LDA ,X; ADCA ,Y; STA ,X; LDB 1,X; ANDA #1; STD ,U; LDD $41C3; BNE $828F; RTS
nat_add_8277:
	lea	(a3,d2.l),a0
	lea	(a3,d3.l),a1
	move.b	1(a0),d0
	move.b	2(a0),d1
	add.b	2(a1),d1
	move.b	1(a1),d6
	addx.b	d6,d0
	move.b	d0,1(a0)		; (moves keep X: ADDD's carry for ADCA)
	move.b	d1,2(a0)
	move.b	(a0),d0
	move.b	(a1),d6
	addx.b	d6,d0
	move.b	d0,(a0)
	move.b	1(a0),d1
	and.b	#1,d0
	move.b	d0,(a3,d4.l)
	move.b	d1,1(a3,d4.l)
	move.b	$41C3(a3),d0
	move.b	$41C4(a3),d1
	bne.s	.nz
	tst.b	d0
	bne.s	.nz
	jmp	M7F828E
.nz:	jmp	M7F828F

; $9222, the tile address of a position (main CPU, after its bank write; Y = $4030, slot 2):
;   <$DB = $1F; <$D9 = (((($300 - [$4030] + <$D7) >> 3) << 1) & $7F)
;   Y = ((($300 - [$4032] - <$D5) >> 3) << 7) + <$D9, A & $1F;  D = [Y] (slot 0); RTS (no flags live)
nat_tile_9222:
	move.b	#$1F,$40DB(a3)
	move.w	#$0300,d7
	RDW	$4030(a3),d6
	sub.w	d6,d7
	RDW	$40D7(a3),d6
	add.w	d6,d7
	lsr.w	#3,d7
	add.w	d7,d7
	and.w	#$7F,d7
	clr.b	$40D9(a3)
	move.b	d7,$40DA(a3)
	move.w	d7,d5
	move.w	#$0300,d7
	RDW	$4032(a3),d6
	sub.w	d6,d7
	RDW	$40D5(a3),d6
	sub.w	d6,d7
	lsr.w	#3,d7
	lsl.w	#7,d7
	add.w	d5,d7
	and.w	#$1FFF,d7
	move.w	d7,d3			; Y
	move.l	32(a6),a0
	move.b	(a0,d3.l),d0
	move.b	1(a0,d3.l),d1
	jmp	M7F9261

; a0 = VB[the slot of the 6809 address in \1.l (upper word 0)] + \1 (d6 scratch)
VBA	macro
	move.w	\1,d6
	rol.w	#3,d6
	and.w	#7,d6
	add.w	d6,d6
	add.w	d6,d6
	move.l	32(a6,d6.w),a0
	add.l	\1,a0
	endm

; a bank write STD $E000 + 2 * \1 of d5.w, as the translation's: skipped when the slot holds that page already
BANKW	macro
	and.w	#$3FF,d5
	cmp.w	96+2*\1(a6),d5
	beq.s	.b\@
	moveq	#2*\1,d6
	bsr	main_bank_word
.b\@:
	endm

; $C025, the stage's tile streaming: one 4 x 4 block's source and destination (main CPU; U in slot 1, the tables at
; $C00D $C170 $C190 in slot 6, the stage's data in slot 3, which the routine switches twice, then slot 0):
;   D = [[U]] + $100 & $1FF >> 5; <$D9 = [$C170 + (B << 1)] + [$C190 + (<$D7 & $F) * 2]
;   slot 3 = [4,U]; <$DB = $6000 + [$A,U]; D = [[2,U]] >> 5; <$D5 = B; B = D >> 2
;   Y = <$DB + ([6,U] << 2) * [[$C,U] + B] + [6,U] * (3 - (<$D5 & 3)) + (<$D7 & $F) * 2; D = [Y]
;   <$DC = A; <$DB = 0; D = B << 5; PSHS Y,D (Y = $6000 + D); slot 3 = [$C00D + <$DC] + $230; slot 0 = [8,U]
;   PULS D,Y; <$D5 = [7,U]; U = <$D9; A = <$D7 & $F; Y = $C150 if A >= $C; then $C0DB (no flags live there)
nat_stream_C025:
	moveq	#0,d7
	move.w	d4,d7
	VBA	d7
	RDW	0(a0),d7		; [U]
	VBA	d7
	RDW	0(a0),d7		; [[U]]
	add.w	#$100,d7
	and.w	#$1FF,d7
	lsr.w	#5,d7
	add.b	d7,d7			; ASLB
	ext.w	d7			; (B,Y: B signed)
	move.l	56(a6),a0
	lea	$C170(a0),a1
	RDW	0(a1,d7.w),d5		; Y
	move.b	$40D7(a3),d7
	and.w	#$0F,d7
	add.w	d7,d7
	lea	$C190(a0),a1
	RDW	0(a1,d7.w),d6
	add.w	d6,d5
	move.b	d5,$40DA(a3)		; <$D9
	move.w	d5,d6
	lsr.w	#8,d6
	move.b	d6,$40D9(a3)
	move.l	36(a6),a1
	add.l	d4,a1			; U (slot 1)
	RDW	4(a1),d5
	BANKW	3
	move.w	#$6000,d3
	RDW	10(a1),d7
	add.w	d7,d3			; Y = <$DB
	moveq	#0,d7
	move.w	d4,d7
	addq.w	#2,d7
	VBA	d7
	RDW	0(a0),d7		; [2,U]
	VBA	d7
	RDW	0(a0),d7		; [[2,U]]
	lsr.w	#5,d7
	move.b	d7,$40D5(a3)
	lsr.w	#2,d7			; B
	ext.w	d7
	moveq	#0,d6
	RDW	12(a1),d6		; [$C,U]
	add.w	d7,d6
	move.l	36(a6),a0
	moveq	#0,d1
	move.b	(a0,d6.l),d1		; LDB B,Y (slot 1)
	move.b	6(a1),d0
	add.b	d0,d0
	add.b	d0,d0
	and.w	#$FF,d0
	mulu	d1,d0			; MUL
	add.w	d0,d3
	moveq	#3,d1
	move.b	$40D5(a3),d7
	and.b	#3,d7
	sub.b	d7,d1			; 3 - (<$D5 & 3)
	moveq	#0,d0
	move.b	6(a1),d0
	mulu	d1,d0
	add.w	d0,d3
	move.b	$40D7(a3),d7
	and.w	#$0F,d7
	add.w	d7,d7
	add.w	d7,d3			; LEAY A,Y
	move.b	(a4,d3.l),d0		; LDD ,Y (slot 3: a4)
	move.b	1(a4,d3.l),d1
	move.b	d0,$40DC(a3)
	clr.b	$40DB(a3)
	moveq	#0,d7
	move.b	d1,d7
	lsl.w	#5,d7			; D = B << 5
	move.b	d7,-3(a5)		; PSHS Y,D: Y low, Y high, B, A
	move.w	d7,d6
	lsr.w	#8,d6
	move.b	d6,-4(a5)
	add.w	#$6000,d7
	move.b	d7,-1(a5)
	lsr.w	#8,d7
	move.b	d7,-2(a5)
	move.b	$40DC(a3),d7
	ext.w	d7
	move.l	56(a6),a0
	lea	$C00D(a0),a0
	moveq	#0,d5
	move.b	(a0,d7.w),d5
	add.w	#$0230,d5
	BANKW	3
	RDW	8(a1),d5		; (slot 1: not switched)
	BANKW	0
	move.b	-4(a5),d0		; PULS D,Y
	move.b	-3(a5),d1
	moveq	#0,d3
	RDW	-2(a5),d3
	move.b	7(a1),$40D5(a3)
	moveq	#0,d4
	RDW	$40D9(a3),d4		; U
	move.b	$40D7(a3),d0
	and.b	#$0F,d0
	cmp.b	#$0C,d0
	bcs.s	.y
	move.w	#$C150,d3
.y:	jmp	M7FC0DB
