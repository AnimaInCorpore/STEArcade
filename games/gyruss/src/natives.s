; Hand-written replacements of the sub CPU's hottest routines (included by sub.s; gen_sub.NATIVES): the object
; projections F273, F2DC, F386, F3F1.  Each runs the 6809 routine's loop exactly (the same RAM writes in the same
; order; A, B, X, U as it leaves them; the flags of its last DEC) and ends at its RTS.
;
; An object is a record at U (the shared RAM's object list, slot 3: a4): byte 0 its distance code, 3 its angle.  The
; distance's scale is the ROM's byte at $E000 + code (<$08), the angle's cosine / sine the ROM's words at
; $E400 + 2 angle and $E600 + 2 angle; a coordinate is the scale times the word's low byte (MUL: the high byte of the
; product), negated for a negative word; it must stay in 0-$7F (else the object is skipped).  The visible ones are
; appended to their band's list through [$4211] (<$11 / <$12: a pointer into $64xx / $65xx, <$12 the group's base
; + its count), the entry's number (U's low byte / 4, plus the list's offset).
;
; Registers as the translation keeps them: d0 A, d1 B, d2 X, d3 Y (kept), d4 U, a2 = the ROM ($E000), a3 / a4 = VB
; of slots 2 / 3; a0 = the direct page here, a1 the angle's words; d5-d7 scratch.

; MULAB: D = <$08 x B (MUL)
MULAB	macro
	moveq	#0,d5
	move.b	8(a0),d5
	moveq	#0,d6
	move.b	d1,d6
	mulu	d6,d5
	move.b	d5,d1
	lsr.w	#8,d5
	move.b	d5,d0
	endm

; COORD off,skip: LDD off,X; BPL p; LDA <$08; MUL; NEGA; BMI ok; BEQ ok; BRA skip; p: LDA <$08; MUL; TSTA; BMI skip
COORD	macro
	move.b	\1(a1),d0
	move.b	\1+1(a1),d1
	tst.b	d0
	bpl.s	.p\@
	MULAB
	neg.b	d0
	beq.s	.ok\@
	bmi.s	.ok\@
	bra	\2
.p\@:	MULAB
	tst.b	d0
	bmi	\2
.ok\@:
	endm

; SCALE skip: LDX #$E000; LDB ,U; BEQ skip; CLRA; LDA D,X; STA <$08; LDX #$E400; LDB 3,U; CLRA; ASLB; ROLA; LEAX D,X
SCALE	macro
	move.w	#$E000,d2
	move.b	0(a4,d4.l),d1
	beq	\1
	moveq	#0,d5
	move.b	d1,d5
	move.b	(a2,d5.w),d0
	move.b	d0,8(a0)
	moveq	#0,d2
	move.b	3(a4,d4.l),d2
	add.w	d2,d2
	lea	(a2,d2.w),a1
	lea	$400(a1),a1		; (the angle's words: X - $E000 + the ROM)
	add.w	#$E400,d2		; X
	endm

; ADDLIST off: INC [$4211]; LDA [$4211]; ADDA <$12; STA <$12; STU <$0D; LDB <$0E; LSRB; LSRB; (ADDB #off;) STB [$4211]
ADDLIST	macro
	moveq	#0,d7
	move.b	$11(a0),d7
	lsl.w	#8,d7
	move.b	$12(a0),d7
	addq.b	#1,(a4,d7.l)
	move.b	(a4,d7.l),d0
	add.b	$12(a0),d0
	move.b	d0,$12(a0)
	move.b	d0,d7
	move.w	d4,d5
	move.b	d5,$0E(a0)
	lsr.w	#8,d5
	move.b	d5,$0D(a0)
	move.b	$0E(a0),d1
	lsr.b	#2,d1
	ifne	\1
	add.b	#\1,d1
	endc
	move.b	d1,(a4,d7.l)
	endm

ENDLOOP	macro				; \1 = the record's size, \2 = the loop, \3 = the RTS
	addq.w	#\1,d4			; LEAU n,U
	subq.b	#1,$0C(a0)		; DEC <$0C
	bne	\2
	move	#$04,ccr
	jmp	\3
	endm

; F273 / F386: one sprite an object (4-byte records); the list's offset 0 / $40
PROJ1	macro				; \1 = the list's offset, \2 = the RTS
	lea	$4200(a3),a0
.l\@:	SCALE	.s\@
	COORD	$200,.s\@
	add.b	#$7C,d0			; ADDA #$7C; STA ,U
	move.b	d0,0(a4,d4.l)
	COORD	0,.s\@
	add.b	#$78,d0			; ADDA #$78; STA 3,U; ANDA #$C0; STA <$12
	move.b	d0,3(a4,d4.l)
	and.b	#$C0,d0
	move.b	d0,$12(a0)
	ADDLIST	\1
.s\@:	ENDLOOP	4,.l\@,\2
	endm

native_proj_F273:
	PROJ1	0,SUB_F2DB
native_proj_F386:
	PROJ1	$40,SUB_F3F0

; F2DC: two sprites an object (8-byte records: the second at +4, 8 pixels on); the colour byte's bit 4 (a big one) puts
; both into the list, else one
native_proj_F2DC:
	lea	$4200(a3),a0
.l:	SCALE	.s
	COORD	$200,.s
	move.b	2(a4,d4.l),d1		; LDB 2,U; ANDB #$10; BNE: ADDA #$78, else ADDA #$7C
	and.b	#$10,d1
	bne.s	.big
	add.b	#$7C,d0
	bra.s	.st
.big:	add.b	#$78,d0
.st:	move.b	d0,0(a4,d4.l)		; STA ,U; ADDA #8; STA 4,U
	addq.b	#8,d0
	move.b	d0,4(a4,d4.l)
	COORD	0,.s
	add.b	#$78,d0			; ADDA #$78; STA 3,U; STA 7,U
	move.b	d0,3(a4,d4.l)
	move.b	d0,7(a4,d4.l)
	move.b	2(a4,d4.l),d0		; LDA 2,U; ANDA #$10; BEQ one
	and.b	#$10,d0
	beq.s	.one
	move.b	3(a4,d4.l),d0		; LDA 3,U; ANDA #$C0; STA <$12
	and.b	#$C0,d0
	move.b	d0,$12(a0)
	moveq	#0,d7			; LDA [$4211]; ADDA #2; STA [$4211]; ADDA <$12; STA <$12
	move.b	$11(a0),d7
	lsl.w	#8,d7
	move.b	d0,d7
	move.b	(a4,d7.l),d0
	addq.b	#2,d0
	move.b	d0,(a4,d7.l)
	add.b	$12(a0),d0
	move.b	d0,$12(a0)
	move.b	d0,d7
	move.w	d4,d5			; STU <$0D; LDB <$0E; LSRB; LSRB; STB [$4211]
	move.b	d5,$0E(a0)
	lsr.w	#8,d5
	move.b	d5,$0D(a0)
	move.b	$0E(a0),d1
	lsr.b	#2,d1
	move.b	d1,(a4,d7.l)
	subq.b	#1,$12(a0)		; DEC <$12; INCB; STB [$4211]
	subq.b	#1,d7
	addq.b	#1,d1
	move.b	d1,(a4,d7.l)
	bra.s	.s
.one:	move.b	3(a4,d4.l),d0		; LDA 3,U; ANDA #$C0; STA <$12; then the list (F36E)
	and.b	#$C0,d0
	move.b	d0,$12(a0)
	ADDLIST	0
.s:	ENDLOOP	8,.l,SUB_F367

; F3F1: two sprites an object, the second in the record 8 on (+$20: $23 its y, $20 its x), both into the lists
; (offsets $40 and $48)
native_proj_F3F1:
	lea	$4200(a3),a0
.l:	SCALE	.s
	COORD	$200,.s
	add.b	#$7C,d0			; ADDA #$7C; STA ,U; ADDA #$FC; STA $23,U
	move.b	d0,0(a4,d4.l)
	add.b	#$FC,d0
	move.b	d0,$23(a4,d4.l)
	COORD	0,.s
	add.b	#$78,d0			; ADDA #$78; STA 3,U; LDB 3,U; ADDB #4; STB $20,U; ANDA #$C0; STA <$12
	move.b	d0,3(a4,d4.l)
	move.b	d0,d1
	addq.b	#4,d1
	move.b	d1,$20(a4,d4.l)
	and.b	#$C0,d0
	move.b	d0,$12(a0)
	ADDLIST	$40
	move.b	$23(a4,d4.l),d0		; LDA $23,U; ANDA #$C0; STA <$12
	and.b	#$C0,d0
	move.b	d0,$12(a0)
	ADDLIST	$48
.s:	ENDLOOP	4,.l,SUB_F48A
