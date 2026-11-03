; Isolated FADE_SNAP experiment. Caller has already saved d2/d5.
; Standard ROM palette targets are available as native words in fade_tab.
; Count each changed channel exactly, while copying two channels per longword.

NF_PAIR macro
	move.l (a1)+,d0
    if \1
	move.w d0,d5
	sub.w 2(a0),d5
    endc
	move.l (a0),d7
	eor.l d0,d7
	beq.s .same\@
	move.l d0,(a0)
	tst.w d7
	beq.s .low\@
	addq.w #1,d2
.low\@:	swap d7
	tst.w d7
	beq.s .same\@
	addq.w #1,d2
.same\@:
	addq.l #4,a0
	endm

	section text,code
nat_nf_copy:
	lea (a3,d3.l),a0
	moveq #0,d0
	move.w d4,d0
	add.l d0,d0
	lea fade_tab,a1
	add.l d0,a1
	moveq #0,d2
	rept 8
	NF_PAIR 0
	endr
	lea $200-32(a0),a0
	rept 8
	NF_PAIR 0
	endr
	lea $200-32(a0),a0
	rept 7
	NF_PAIR 0
	endr
	NF_PAIR 1
	moveq #0,d0
	move.w d5,d0
	add.w #48,d4
	rts
