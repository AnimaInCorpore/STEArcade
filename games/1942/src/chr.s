; ------------------------------------------------------------------------------
; Characters (the 32 x 32 map of 8 x 8 cells at $D000, 28 columns of it visible)
;
; The screen cell (cx, cy) (cx 0-27 across, cy 0-31 down) is the map entry row cx + 2, column 31 - cy (index (cx + 2) * 32 + 31 - cy),
; rotated like everything else.  Two cells side by side are one 16 pixel chunk of the ring; a chunk is drawn in one go:
; the background (clean) or what the ring shows, the baked planes and masks of the left cell (lane 0: the high byte of the
; words) and the right cell (lane 1) merged.  Baked cell: lane 0 then lane 1, 8 rows each of 12 bytes: the data of planes
; 0/1 (a long), planes 2/3, the mask (twice).
; ------------------------------------------------------------------------------

; The map against fg_shadow: the cells that changed set bits of the chunk masks of both rings (chr_dirty), update
; cell_occ (a long of cell bits for every cy: the cell has opaque pixels) and chunk_now (the chunk bits of it, a word per cy).

rf_chr_diff:
	lea	Z_FG+64,a2			; (long k = 16 is map row 2 column 0)
	lea	fg_shadow+64,a3
	move.w	#16,d6
.long:	tst.b	full_redraw		; (the first frame: the shadow says nothing)
	bne.s	.diff
	move.l	a2,a0
	move.l	a3,a1
	cmpm.l	(a0)+,(a1)+
	bne.s	.diff
	lea	$400(a2),a0			; the attribute bytes of the same four cells
	lea	$400(a3),a1
	cmpm.l	(a0)+,(a1)+
	beq.s	.same
.diff:	bsr.s	chr_cells
.same:	addq.l	#4,a2
	addq.l	#4,a3
	addq.w	#1,d6
	cmp.w	#240,d6				; (map row 29 ends with long 239)
	blo.s	.long
	; chunk_now from cell_occ: the nibbles of the four bytes through pair_tab
	lea	cell_occ,a0
	lea	chunk_now,a1
	lea	pair_tab,a2
	moveq	#31,d7
.occ:	move.l	(a0)+,d0
	moveq	#0,d1
	moveq	#0,d2
	move.b	d0,d1
	move.b	(a2,d1.w),d2
	lsr.l	#8,d0
	move.b	d0,d1
	moveq	#0,d3
	move.b	(a2,d1.w),d3
	lsl.w	#4,d3
	or.w	d3,d2
	lsr.l	#8,d0
	move.b	d0,d1
	moveq	#0,d3
	move.b	(a2,d1.w),d3
	lsl.w	#8,d3
	or.w	d3,d2
	lsr.l	#8,d0
	move.b	d0,d1
	moveq	#0,d3
	move.b	(a2,d1.w),d3
	lsl.w	#8,d3
	lsl.w	#4,d3
	or.w	d3,d2
	move.w	d2,(a1)+
	dbf	d7,.occ
	rts

; Four cells of map row k >> 3 (k = d6.w, the map index 4 * k): a2 / a3 point at their codes in the map / the shadow.

chr_cells:
	movem.l	d6/a2-a3,-(sp)
	move.w	d6,d5
	lsr.w	#3,d5				; map row
	subq.w	#2,d5				; cell column 0-27
	move.w	d5,d4
	lsr.w	#1,d4				; chunk column
	move.w	d6,d3
	and.w	#7,d3
	lsl.w	#2,d3				; map column of the first cell (0-28)
	moveq	#3,d7
.cell:	moveq	#0,d0
	move.b	(a2),d0				; code
	btst	#7,$400(a2)			; attribute bit 7: code bit 8
	beq.s	.low
	add.w	#256,d0
.low:	lea	chr_blank,a0
	tst.b	(a0,d0.w)
	sne	d2				; $FF: the cell is blank
	move.w	#31,d0
	sub.w	d3,d0				; cy
	lea	cell_occ,a0
	move.w	d0,d1
	lsl.w	#2,d1
	add.w	d1,a0
	move.l	(a0),d1
	tst.b	d2
	bne.s	.blank
	bset	d5,d1
	bra.s	.stored
.blank:	bclr	d5,d1
.stored:
	move.l	d1,(a0)
	add.w	d0,d0
	moveq	#0,d1
	bset	d4,d1				; the chunk's bit
	lea	chr_dirty,a0
	or.w	d1,(a0,d0.w)
	or.w	d1,64(a0,d0.w)
	lea	128(a0),a0
	or.w	d1,(a0,d0.w)
	lea	merge_dirty,a0
	or.w	d1,(a0,d0.w)
	addq.l	#1,a2
	addq.w	#1,d3
	dbf	d7,.cell
	movem.l	(sp)+,d6/a2-a3
	move.l	(a2),(a3)			; the shadow follows
	move.l	$400(a2),$400(a3)
	rts

; ------------------------------------------------------------------------------
; Baking a cell: d0.w = code (9 bits), d1.w = colour (6 bits) -> a0.  Clobbers d0-d7, a1-a5.

char_get:
	move.w	d0,d2
	lsl.w	#6,d2
	or.w	d1,d2				; key
	moveq	#0,d3
	move.w	d2,d3
	lsl.l	#2,d3
	lea	chr_ptr,a0
	move.l	(a0,d3.l),d3
	beq.s	bake_char
	move.l	d3,a0
	rts

bake_char:
	move.w	d2,-(sp)			; the key
	moveq	#0,d3
	move.w	d0,d3
	lsl.l	#5,d3
	lea	chr_masks,a1
	add.l	d3,a1				; 8 rows of M1 M2 M3 opaque
	lea	luts+512,a2
	lsl.w	#2,d1
	add.w	d1,a2
	addq.l	#1,a2				; (pens 1-3)
	lea	cmap,a3
	lea	bk_idx,a0
	moveq	#2,d4
.idx:	moveq	#0,d0
	move.b	(a2)+,d0
	add.w	#128,d0				; the arcade palette entry
	move.b	(a3,d0.w),d0
	lsl.b	#2,d0
	move.b	d0,(a0)+
	dbf	d4,.idx
	move.l	chr_pool_ptr,a2			; lane 0
	move.l	a2,-(sp)
	lea	96(a2),a3			; lane 1
	lea	orp_tab,a5
	moveq	#7,d2
.row:	moveq	#0,d3
	moveq	#0,d4
	moveq	#0,d5
	moveq	#0,d6
	lea	bk_idx,a0
	moveq	#2,d1
.pen:	moveq	#0,d7
	move.b	(a1)+,d7
	beq.s	.skip
	moveq	#0,d0
	move.b	(a0)+,d0
	move.l	(a5,d0.w),a4
	jsr	(a4)
	dbf	d1,.pen
	bra.s	.pens
.skip:	addq.l	#1,a0
	dbf	d1,.pen
.pens:	moveq	#0,d7
	move.b	(a1)+,d7			; the opaque mask
	move.w	d3,(a3)+			; lane 1: the byte in the low half
	move.w	d4,(a3)+
	move.w	d5,(a3)+
	move.w	d6,(a3)+
	move.w	d7,(a3)+
	move.w	d7,(a3)+
	lsl.w	#8,d3				; lane 0: the high half
	lsl.w	#8,d4
	lsl.w	#8,d5
	lsl.w	#8,d6
	lsl.w	#8,d7
	move.w	d3,(a2)+
	move.w	d4,(a2)+
	move.w	d5,(a2)+
	move.w	d6,(a2)+
	move.w	d7,(a2)+
	move.w	d7,(a2)+
	dbf	d2,.row
	move.l	a3,chr_pool_ptr		; (lane 1 ended 192 bytes after the start)
	move.l	(sp)+,a0
	moveq	#0,d0
	move.w	(sp)+,d0
	lsl.l	#2,d0
	lea	chr_ptr,a1
	move.l	a0,(a1,d0.l)
	rts

