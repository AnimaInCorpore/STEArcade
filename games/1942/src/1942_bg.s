; ------------------------------------------------------------------------------
; Background: the tilemap RAM ($D800, 32 columns of 32 bytes: 16 codes, 16 attributes) against bg_shadow, what the
; clean ring shows.  A changed tile (rows 1-14 are visible, the tilemap's rows 0 and 15 are off screen) is baked and put into
; the clean ring and noted for both draw rings (tile_pend, a word of row bits per column and ring).
; ------------------------------------------------------------------------------

rf_bg:
	lea	Z_BG,a2
	lea	bg_shadow,a3
	moveq	#0,d6				; column
.col:	tst.b	full_redraw
	bne.s	.changed
	move.l	a2,a0
	move.l	a3,a1
	rept 8
	cmpm.l	(a0)+,(a1)+
	bne.s	.changed
	endr
	bra.s	.next_col
.changed:
	moveq	#1,d5				; row
.row:	moveq	#0,d0
	move.b	16(a2,d5.w),d0
	lsl.w	#8,d0
	move.b	(a2,d5.w),d0			; the key of the tile: attribute, code
	tst.b	full_redraw
	bne.s	.draw
	moveq	#0,d1
	move.b	16(a3,d5.w),d1
	lsl.w	#8,d1
	move.b	(a3,d5.w),d1
	cmp.w	d1,d0
	beq.s	.skip
.draw:	movem.l	d5-d6/a2-a3,-(sp)
	bsr	tile_get			; a0 = the baked tile
	move.w	6(sp),d1			; column
	move.w	2(sp),d2			; row
	move.l	clean_base,a2
	bsr	put_tile
	movem.l	(sp)+,d5-d6/a2-a3
	tst.b	full_redraw			; (the whole ring is copied then)
	bne.s	.skip
	moveq	#0,d0
	bset	d5,d0				; this row's bit
	move.w	d6,d1
	add.w	d1,d1
	lea	tile_pend,a0
	or.w	d0,(a0,d1.w)
	or.w	d0,64(a0,d1.w)
.skip:	addq.w	#1,d5
	cmp.w	#15,d5
	blo.s	.row
	move.l	a2,a0				; the shadow of the column is up to date
	move.l	a3,a1
	movem.l	(a0),d0-d5/a4-a5
	movem.l	d0-d5/a4-a5,(a1)
.next_col:
	lea	32(a2),a2
	lea	32(a3),a3
	addq.w	#1,d6
	cmp.w	#32,d6
	blo	.col
	rts

; The tiles that changed since the draw ring a2 was last drawn are copied from clean into it.

rf_apply_tiles:
	stage	$040
	move.w	draw_idx,d0
	lsl.w	#6,d0
	lea	tile_pend,a4
	add.w	d0,a4				; this ring's 32 words
	moveq	#0,d6
.col:	move.w	(a4),d4
	beq.s	.next
	clr.w	(a4)
	moveq	#1,d5
.row:	btst	d5,d4
	beq.s	.skip
	movem.l	d4-d6/a2/a4,-(sp)
	move.w	d6,d1
	move.w	d5,d2
	bsr	copy_tile
	movem.l	(sp)+,d4-d6/a2/a4
.skip:	addq.w	#1,d5
	cmp.w	#15,d5
	blo.s	.row
.next:	addq.l	#2,a4
	addq.w	#1,d6
	cmp.w	#32,d6
	blo.s	.col
	rts
