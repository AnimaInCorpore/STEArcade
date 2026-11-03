; Native equivalents of the three E873/E890/E8AD tile-RAM initialization loops.
; Fill the same cells, then mark each affected 64-byte video block once.

NC_ENTRY macro
	tst.w d0
	bne \1
	cmp.w #\2,d1
	bne \1
	cmp.w #\3,d5
	bne \1
	cmp.l #v30_image+\4,a2
	bne \1
	bsr nat_nc_fill
	jmp \5
	endm

	section text,code
nat_nc_tail:
	NC_ENTRY R0EC73_t,$F80,$200,$D0000,R0EC81
nat_nc_fg:
	NC_ENTRY R0EC90_t,$1000,0,$D0000,R0EC9E
nat_nc_bg:
	NC_ENTRY R0ECAD_t,$1000,0,$D8000,R0ECBB

nat_nc_fill:
	lea (a2,d5.l),a0
	move.l a0,a1
	move.w d1,-(sp)
	lsr.w #3,d1
	subq.w #1,d1
	move.l #$0FA00000,d7
.fill:
	rept 8
	move.l d7,(a0)+
	endr
	dbf d1,.fill
	move.l a1,d7
	sub.l #v30_image+$C8000,d7
	lsr.l #6,d7
	lea v30_vmarks,a0
	add.l d7,a0
	move.w (sp)+,d1
	lsr.w #4,d1
	subq.w #1,d1
.mark:	st (a0)+
	dbf d1,.mark
	moveq #0,d1
	move.w #$4000,d5
	rts
