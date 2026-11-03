; Isolated replacements for EC6D's tile run and C44A's 7 x 6 BG patch.
; These write emulated tile RAM, not STE pixels. Unsupported inputs use the
; original translation. POP-segment continuations do not consume entry flags.+
	section text,code
late_tile_run:
	cmp.l #v30_image+$D0000,a2
	bne R0F06D_t
	tst.w d1
	beq R0F06D_t
	cmp.w #$1000,d1
	bhi R0F06D_t
	move.w d3,d7
	and.w #3,d7
	bne R0F06D_t
	moveq #0,d7
	move.w d1,d7
	lsl.l #2,d7
	add.l d3,d7
	cmp.l #$4000,d7
	bhi R0F06D_t
	lea (a2,d7.l),a1
	lea (a2,d3.l),a0
	move.w d0,d7
	swap d7
	move.w d2,d7
	subq.w #1,d1
.fill:	move.l d7,(a0)+
	dbf d1,.fill
	move.l a1,d7
	sub.l a2,d7
	subq.w #1,d7
	lsr.w #6,d7
	move.w d7,d1
	move.w d3,d7
	lsr.w #6,d7
	sub.w d7,d1
	lea v30_vmarks+$200,a0
	add.l d7,a0
.mark:	st (a0)+
	dbf d1,.mark
	move.l a1,d7
	sub.l a2,d7
	move.w d7,d3
	moveq #0,d1
	jmp R0F079

late_bg_patch:
	cmp.l #v30_image+$10000,a3
	bne R0C84A_t
	cmp.l #v30_image+$D8000,a2
	bne R0C84A_t
	cmp.w #$607,d1
	bne R0C84A_t
	move.w d3,d7
	and.w #3,d7
	bne R0C84A_t
	cmp.b #$E4,d3
	bhi R0C84A_t
	cmp.w #$3A00,d3
	bcc R0C84A_t
	btst #0,d4
	bne R0C84A_t
	cmp.w #$FFAC,d4
	bhi R0C84A_t
.row:	move.w d3,-(sp)
	rept 7
	move.w (a3,d4.l),d0
	move.w d0,d7
	swap d7
	move.w #$81,d7
	move.l d7,(a2,d3.l)
	addq.w #2,d4
	addq.b #4,d3
	endr
	move.w (sp)+,d3
	lea (a2,d3.l),a0
	bsr nat_mark
	lea 27(a2,d3.l),a0
	bsr nat_mark
	move.w d1,-2(a5)
	move.w d3,-4(a5)
	add.w #$100,d3
	sub.w #$100,d1
	cmp.w #7,d1
	bne .row
	jmp R0C86B
