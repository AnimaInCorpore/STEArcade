; Natives for the game's hottest routines (tools/gen.py NATIVES, included by core.s): the background and object
; collision of bank 4 ($4000, entered through $FB00 / $FF10), written at the level of what they compute instead of
; instruction by instruction.  ref/routines.py found them: about a quarter of the main CPU's time in play.
;
; The routines (bank 4; DP = $0B, its variables at $0Bxx):
;   $40E6  a group n = [$58] (1-4): the 3 signed bytes at $0B31 + 13 + 3 (n - 1); none set -> A = 0; else the
;          group's position $5A / $5E / $60 from the object's $4E / $50 / $52, moved by the direction table $4130
;          ([$59]); A = $FF
;   $4154  the map cell under the group ($4780 tables): [$56] = its list of boxes; out of the map or ($37, $3B)
;          out of range: the whole scan ends ($41A1 drops two return addresses)
;   $41A7  a box (Y) of the list: $62 / $64 / $66, and $5C as the box's x anchor ($9,Y bits 6-7)
;   $4565  the same for an object's own box (X = [$56] the object in RAM, Y its template)
;   $41E0  the overlap test of the group's point against the box ($6,Y $7,Y $8,Y the sizes, 0 = 256); a hit writes
;          the overlaps $68-$6D and gives A = $FF
;   $4251  what a hit does: long and rare, it stays translated: the natives continue the translation at its JSR with
;          the registers as the 6809 has them there (Y the box, X, A = $FF, B = the last overlap)
; Each native runs its loop to its end (the translated RTS) or to a hit.  The bytes the 6809's pushes leave below S
; (return addresses, $41E0's three sizes) are not written: they are dead (tools/logic_test.py does not compare
; below S).  a0 the bank's base (VB of slot 2: $4000-$7FFF), a3 g_mem; a2 is saved.

; a word of the bank at offset \1 (a long, zero-extended) -> \2.w (bytes: the address may be odd)
BANKW	macro
	move.b (a0,\1.l),\2
	lsl.w #8,\2
	move.b 1(a0,\1.l),\2
	endm
; a word at \1(\2) (an address register) -> \3.w
WORDAT	macro
	move.b \1(\2),\3
	lsl.w #8,\3
	move.b \1+1(\2),\3
	endm

; $40E6: group [$58] -> Z set when empty (A = 0); else $5A $5E $60 set.  Uses d5-d7/a2.
coll_group:
	move.b $B58(a3),d6
	subq.b #1,d6
	move.b d6,d7
	add.b d7,d7
	add.b d6,d7
	add.b #13,d7			; B = 3 (n - 1) + 13 (MUL's low byte, ADDB)
	moveq #0,d6
	move.b d7,d6
	lea $B31(a3),a2
	add.w d6,a2			; X
	move.b (a2),d5
	or.b 1(a2),d5
	or.b 2(a2),d5
	beq.s .none
	move.b (a2),d6
	ext.w d6
	add.w $B4E(a3),d6
	move.w d6,$B5A(a3)
	move.b 1(a2),d6
	ext.w d6
	add.w $B50(a3),d6
	move.w d6,$B5E(a3)
	move.b 2(a2),d7
	ext.w d7
	add.w $B52(a3),d7
	sub.w d6,d7
	subq.w #1,d7
	move.w d7,$B60(a3)
	moveq #0,d7
	move.b $B59(a3),d7
	lsl.b #2,d7			; (ASLB ASLB)
	add.w #$4130,d7
	BANKW d7,d6
	add.w $B5A(a3),d6
	bpl.s .p
	moveq #0,d6
.p:	move.w d6,$B5A(a3)
	addq.w #2,d7
	BANKW d7,d6
	add.w d6,$B5E(a3)
	moveq #1,d5			; (Z clear)
.none:	rts

; $41E0: the box at a1 against the group's point -> d0 = $FF (a hit: $68-$6D written, d1 = B) or 0.
; Uses d0 d1 d5-d7.
TESTAX	macro				; \1 the size's offset, \2 the box's start, \3 the point
	moveq #0,d5
	move.b \1(a1),d5
	bne.s .s\@
	move.w #$100,d5
.s\@:	move.w \2(a3),d6
	cmp.w \3(a3),d6
	bgt .miss
	add.w d5,d6
	cmp.w \3(a3),d6
	ble .miss
	endm
OVERLAP	macro				; \1 the size's offset, \2 the point's low byte, \3 the box's, \4 the near, \5 the far
	move.b \2(a3),d1
	sub.b \3(a3),d1
	move.b d1,\4(a3)
	move.b \1(a1),d0
	subq.b #1,d0
	sub.b d1,d0
	move.b d0,\5(a3)
	endm
coll_test:
	TESTAX 6,$B62,$B5C
	TESTAX 7,$B64,$B5E
	TESTAX 8,$B66,$B60
	OVERLAP 6,$B5D,$B63,$B69,$B6B
	OVERLAP 7,$B5F,$B65,$B6A,$B6C
	OVERLAP 8,$B61,$B67,$B6D,$B68
	moveq #0,d1
	move.b d0,d1			; B: the last overlap
	move.l #$FF,d0
	rts
.miss:	moveq #0,d0
	rts

; the box's x anchor ($9,Y bits 6-7 against $40): d7 = the box's x, d5 = [$64] -> $62, $5C.  Uses d6.
ANCHOR	macro
	move.b 9(a1),d6
	and.b #$C0,d6
	cmp.b #$40,d6
	bcs.s .lt\@
	beq.s .eq\@
	move.w d7,$B62(a3)		; (above: the box's x as it is)
	move.w $B5A(a3),$B5C(a3)
	bra.s .done\@
.lt\@:	sub.w d5,d7
	move.w d7,$B62(a3)
	move.w $B5A(a3),d6
	sub.w $B5E(a3),d6
	move.w d6,$B5C(a3)
	bra.s .done\@
.eq\@:	add.w d5,d7
	move.w d7,$B62(a3)
	move.w $B5A(a3),d6
	add.w $B5E(a3),d6
	move.w d6,$B5C(a3)
.done\@:
	endm

; ---- bank 4 $40B3: the groups' map boxes (from $40AF; again from $40E3 after a hit) ----
native_coll_groups:
	move.l a2,-(sp)
	move.l 40(a6),a0
cg_group:	bsr coll_group
	beq cg_next
	; $4154: the map cell's list of boxes -> [$56]
	move.w $B60(a3),d6
	add.w $B5E(a3),d6		; t
	move.w d6,d5
	lsr.w #8,d5
	lsl.w #7,d5			; (t >> 8) * $80 (MUL)
	move.w $B5A(a3),d7
	add.w d7,d7
	lsr.w #8,d7
	add.b d7,d7
	and.w #$FF,d7
	add.w d5,d7
	add.w #$4780,d7
	moveq #0,d5
	move.w d7,d5
	BANKW d5,d7			; the row's table
	tst.w d7
	beq cg_abort
	moveq #0,d5
	move.b d6,d5
	lsr.b #3,d5
	add.b d5,d5
	add.w d7,d5			; (the column)
	and.l #$FFFF,d5
	BANKW d5,d7
	move.w d7,$B56(a3)		; the list
	cmp.b #$20,$B37(a3)
	bcc cg_abort
	move.b $B3B(a3),d5
	beq cg_abort
	cmp.b #4,d5
	bcc cg_abort
	move.l #$0B31,d2		; X (LDX #$0B31)
	bra.s cg_box
; ---- bank 4 $40BC: the boxes of the group's list (again from $40DB after a hit) ----
native_coll_boxes:
	move.l a2,-(sp)
	move.l 40(a6),a0
cg_box:	moveq #0,d5
	move.w $B56(a3),d5
	moveq #0,d3
	BANKW d5,d3			; Y = [[$56]]
	lea (a0,d3.l),a1
	; $41A7
	WORDAT 2,a1,d5
	move.w d5,$B64(a3)
	WORDAT 4,a1,d6
	sub.w d5,d6
	move.w d6,$B66(a3)
	WORDAT 0,a1,d7
	ANCHOR
	bsr coll_test
	tst.b d0
	bne cg_hit
	; $40CD: the next box ($FFFF ends the list)
	moveq #0,d2
	move.w $B56(a3),d2
	addq.w #2,d2
	move.w d2,$B56(a3)
	BANKW d2,d7
	cmp.w #$FFFF,d7
	bne cg_box
cg_next:	addq.b #1,$B58(a3)		; $40DD
	cmp.b #5,$B58(a3)
	bcs cg_group
cg_abort:	move.l (sp)+,a2			; ($41A1 from $4154: the scan's RTS too)
	jmp M0200E5
cg_hit:	move.l (sp)+,a2
	jmp M0200CA			; JSR $4251 (Y the box, X, A = $FF, B)

; ---- bank 4 $454A: an object's own box against its groups (from $4546: Y its template; again after a hit) ----
native_coll_object:
	move.l a2,-(sp)
	move.l 40(a6),a0
	lea (a0,d3.l),a1		; (Y: the template)
.group:	bsr coll_group
	beq .next
	; $4565: X = [$56] the object
	moveq #0,d2
	move.w $B56(a3),d2
	lea (a3,d2.l),a2
	WORDAT 6,a2,d5
	WORDAT 2,a1,d6
	add.w d6,d5
	move.w d5,$B64(a3)
	WORDAT 8,a2,d6
	WORDAT 4,a1,d7
	add.w d7,d6
	move.w d6,$B66(a3)
	WORDAT 4,a2,d7
	WORDAT 0,a1,d6
	add.w d6,d7
	ANCHOR
	bsr coll_test
	tst.b d0
	bne .hit
.next:	addq.b #1,$B58(a3)		; $455C
	cmp.b #5,$B58(a3)
	bcs .group
	move.l (sp)+,a2
	jmp M020564
.hit:	move.l (sp)+,a2
	jmp M020559			; JSR $4251 (Y the template, X the object, A = $FF, B)

; ---- bank 4 $450E: the 16 objects from [$56] (B the count): a type of the table at $453B calls its routine ----
native_coll_scan:
	move.l 40(a6),a0
.obj:	moveq #0,d2
	move.w $B56(a3),d2
	tst.b (a3,d2.l)
	bpl.s .skip
	move.b $17(a3,d2.l),d0		; the type
	move.l #$453B,d6
.find:	cmp.b (a0,d6.l),d0
	beq.s .call
	addq.w #5,d6
	cmp.b #$FF,(a0,d6.l)
	bne.s .find
.skip:	add.w #$21,$B56(a3)		; $452E: the next object
	subq.b #1,d1
	bne.s .obj
	moveq #0,d2
	move.w $B56(a3),d2
	jmp M02053A
.call:	move.b d1,-(a5)			; PSHS B (the count), JSR [$01,X]
	move.b #$2E,-(a5)
	move.b #$45,-(a5)
	move.l d6,d2			; X: the entry
	moveq #0,d3
	addq.w #3,d6
	BANKW d6,d3			; Y
	subq.w #2,d6
	BANKW d6,d7			; the routine
	move.l #$FF,d1			; (LDB #$FF)
	jmp main_dispatch
