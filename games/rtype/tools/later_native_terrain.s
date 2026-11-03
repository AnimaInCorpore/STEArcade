; 0040:2736: remove breakable FG tiles in the 2 x 2 cells around an object.
; Keep the lookup, coordinates, DS1, live registers and all stack residues exact.
LATE_BREAK_CELL macro
	cmp.w #$9F6,d0
	bne.s .next\@
	move.l #$0FA00000,(a2,d3.l)
	moveq #0,d7
	move.w d3,d7
	lsr.w #6,d7
	lea v30_vmarks+$200,a0
	st (a0,d7.l)
	addq.b #1,$2F31(a3)
.next\@:
	endm

LATE_TERRAIN macro
	btst #0,d6
	bne .fallback
	cmp.w #$140,4(a4,d6.l)
	bcc.s .probe
	NEXIT \1,R02B35
.probe:
	move.w 4(a4,d6.l),-(a5)
	move.w 8(a4,d6.l),-(a5)
	move.w 0(a6),-(a5)
	move.w #$D000,0(a6)
	lea v30_image+$D0000,a2
	subq.w #4,4(a4,d6.l)
	addq.w #4,8(a4,d6.l)
	move.w #$2754,-2(a5)
	move.w 6(a6),-4(a5)
	FG_AT
	move.w (a2,d3.l),d0
	and.w #$FFF,d0
	LATE_BREAK_CELL
	addq.b #4,d3
	move.w (a2,d3.l),d0
	and.w #$FFF,d0
	LATE_BREAK_CELL
	add.w #$100,d3
	and.w #$3FFF,d3
	move.w (a2,d3.l),d0
	and.w #$FFF,d0
	LATE_BREAK_CELL
	subq.b #4,d3
	move.w (a2,d3.l),d0
	and.w #$FFF,d0
	LATE_BREAK_CELL
	moveq #0,d7
	move.w (a5)+,d7
	move.w d7,0(a6)
	lsl.l #4,d7
	lea v30_image,a2
	add.l d7,a2
	move.w (a5)+,8(a4,d6.l)
	move.w (a5)+,4(a4,d6.l)
	NEXIT \1,R02BCB
.fallback:
	NFALL \1,R02B36_t
	endm

	section text,code
late_terrain:
	LATE_TERRAIN 0
late_leaf_terrain:
	subq.l #2,a5
	LATE_TERRAIN 1
