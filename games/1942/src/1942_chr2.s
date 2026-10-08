; ------------------------------------------------------------------------------
; Chunks.  The chunk (cx, cy) lies at the ring lines T + 8 * cy ... T + 8 * cy + 7 (T = the window's top line).
; Every occupied chunk has merged data (chunk_pool, 96 bytes: 8 rows of the keep mask (a long), planes 0/1 and planes 2/3
; of both cells), rebuilt when one of its cells changed (merge_dirty); chr_list lists the occupied chunks: the byte offset of
; the chunk's first line in a window of the ring (8 * cy * STRIDE + GAME_X + 8 * cx) and its data.
; ------------------------------------------------------------------------------

; d0.w = chunk column, d1.w = chunk row: a3 = the lane 0 data of the left cell, a4 = the lane 1 data of the right one
; (blank_cell where a cell has no pixels).  Clobbers d0-d7, a0-a2, a5.

chunk_ptrs:
	move.w	d0,d2
	lsl.w	#6,d2
	add.w	#64+31,d2
	sub.w	d1,d2				; map index of the left cell
	move.w	d2,-(sp)
	bsr.s	cell_ptr
	move.l	a0,-(sp)			; (baking clobbers the registers)
	move.w	4(sp),d2
	add.w	#32,d2
	bsr.s	cell_ptr
	lea	96(a0),a4
	cmp.l	#blank_cell,a0
	bne.s	.r
	lea	blank_cell,a4
.r:	move.l	(sp)+,a3
	addq.l	#2,sp
	rts

; d2.w = map index: a0 = the baked cell (blank_cell if it has no pixels)

cell_ptr:
	moveq	#0,d0
	lea	Z_FG,a0
	move.b	(a0,d2.w),d0
	moveq	#0,d1
	lea	Z_FG+$400,a1
	move.b	(a1,d2.w),d1
	btst	#7,d1
	beq.s	.low
	add.w	#256,d0
.low:	lea	chr_blank,a0
	tst.b	(a0,d0.w)
	beq.s	.draw
	lea	blank_cell,a0
	rts
.draw:	and.w	#$3F,d1
	bra	char_get

; The data of chunk (d4, d6) -> a0

chunk_data:
	move.w	d6,d0
	mulu	#14,d0
	add.w	d4,d0
	mulu	#96,d0
	lea	chunk_pool,a0
	add.l	d0,a0
	rts

; The merged data of the occupied chunks of merge_dirty, then the list of the occupied chunks if anything changed.

chr_merge:
	moveq	#0,d6
	moveq	#0,d3				; anything changed?
.cy:	move.w	d6,d0
	add.w	d0,d0
	lea	merge_dirty,a0
	move.w	(a0,d0.w),d5
	beq.s	.next
	clr.w	(a0,d0.w)
	moveq	#1,d3
	lea	chunk_now,a0
	and.w	(a0,d0.w),d5			; (a chunk that is blank needs no data)
	beq.s	.next
	moveq	#0,d4
.cx:	btst	d4,d5
	beq.s	.skip
	movem.l	d3-d6,-(sp)
	bsr.s	merge_chunk
	movem.l	(sp)+,d3-d6
.skip:	addq.w	#1,d4
	cmp.w	#14,d4
	blo.s	.cx
.next:	addq.w	#1,d6
	cmp.w	#32,d6
	blo.s	.cy
	tst.w	d3
	beq.s	.done
	bsr	chr_build_list
.done:	rts

; d4 = chunk column, d6 = chunk row

merge_chunk:
	move.w	d4,d0
	move.w	d6,d1
	movem.l	d4/d6,-(sp)
	bsr	chunk_ptrs
	movem.l	(sp)+,d4/d6
	bsr	chunk_data
	move.l	a0,a2
	moveq	#7,d7
.row:	move.l	(a3)+,d0
	or.l	(a4)+,d0			; planes 0 / 1
	move.l	(a3)+,d1
	or.l	(a4)+,d1			; planes 2 / 3
	move.l	(a3)+,d2
	or.l	(a4)+,d2			; the mask
	not.l	d2
	move.l	d2,(a2)+
	move.l	d0,(a2)+
	move.l	d1,(a2)+
	dbf	d7,.row
	rts

chr_build_list:
	lea	chr_list,a5
	lea	chunk_now,a1
	moveq	#0,d6
	moveq	#0,d3
.cy:	move.w	(a1)+,d5
	beq.s	.next
	moveq	#0,d4
.cx:	btst	d4,d5
	beq.s	.skip
	moveq	#0,d0
	move.w	d6,d0
	lsl.l	#8,d0
	lsl.l	#3,d0				; 8 lines * STRIDE
	moveq	#0,d1
	move.w	d4,d1
	lsl.l	#3,d1
	add.l	d1,d0
	add.l	#GAME_X,d0
	move.l	d0,(a5)+
	bsr	chunk_data
	move.l	a0,(a5)+
	addq.w	#1,d3
.skip:	addq.w	#1,d4
	cmp.w	#14,d4
	blo.s	.cx
.next:	addq.w	#1,d6
	cmp.w	#32,d6
	blo.s	.cy
	move.w	d3,chr_list_n
	rts

; a1 = ring address of the chunk's first line, a2 = what the background is taken from (clean, or a1 itself to draw over what is
; there), a3 = the chunk's merged data.  8 rows.

draw8:
	rept 8
	movem.l	(a2),d0-d1
	move.l	(a3)+,d2
	and.l	d2,d0
	and.l	d2,d1
	or.l	(a3)+,d0
	or.l	(a3)+,d1
	movem.l	d0-d1,(a1)
	lea	STRIDE(a1),a1
	lea	STRIDE(a2),a2
	endr
	rts

; d0.w = rows - 1: the background (a2) is put back into a1

restore_rows:
	movem.l	(a2),d1-d2
	movem.l	d1-d2,(a1)
	lea	STRIDE(a1),a1
	lea	STRIDE(a2),a2
	dbf	d0,restore_rows
	rts

; The characters of the draw ring.  If the window moved (t_moved) the chunks the ring showed lose their lines that no
; new picture covers and every occupied chunk is drawn at the new lines (the background is taken from clean in the same
; pass), else only the chunks that changed are drawn (or put back, if they are blank now).

rf_chr:
	bsr	chr_merge
	move.w	draw_idx,d0
	lsl.w	#2,d0
	lea	ring_base,a0
	move.l	(a0,d0.w),a5			; the draw ring
	move.l	clean_base,a6
	tst.b	t_moved
	beq	.still

	; the old picture
	move.w	draw_idx,d0
	add.w	d0,d0
	lea	ring_T,a0
	move.w	(a0,d0.w),d3			; the old window (-1: nothing was drawn)
	bmi	.new
	move.w	cur_T,d4
	sub.w	d3,d4				; d = new - old
	move.w	d3,old_T
	move.w	d4,chr_d
	move.w	draw_idx,d0
	lsl.w	#6,d0
	lea	chr_drawn,a4
	add.w	d0,a4
	moveq	#0,d6
.ocy:	move.w	(a4)+,d5
	beq.s	.onext
	moveq	#0,d4
.ocx:	btst	d4,d5
	beq.s	.oskip
	movem.l	d4-d6/a4,-(sp)
	bsr	chr_restore_old
	movem.l	(sp)+,d4-d6/a4
.oskip:	addq.w	#1,d4
	cmp.w	#14,d4
	blo.s	.ocx
.onext:	addq.w	#1,d6
	cmp.w	#32,d6
	blo.s	.ocy

	; the new picture
.new:	move.w	chr_list_n,d7
	subq.w	#1,d7
	bmi.s	.fin
	lea	chr_list,a4
	moveq	#0,d1
	move.w	cur_T,d1
	lsl.l	#8,d1				; the window's offset in the ring
.n:	move.l	(a4)+,d0
	add.l	d1,d0
	move.l	(a4)+,a3
	lea	(a5,d0.l),a1
	lea	(a6,d0.l),a2
	movem.l	d1/d7/a4,-(sp)
	bsr	draw8
	movem.l	(sp)+,d1/d7/a4
	dbf	d7,.n
	bra.s	.fin

.still:	move.w	draw_idx,d0
	lsl.w	#6,d0
	lea	chr_dirty,a4
	add.w	d0,a4
	lea	chunk_now,a0
	moveq	#0,d6
.cy:	move.w	(a4),d3				; the chunks that changed
	clr.w	(a4)+
	move.w	(a0)+,d5			; the occupied ones
	tst.w	d3
	beq.s	.next
	moveq	#0,d4
.cx:	btst	d4,d3
	beq.s	.skip
	movem.l	d3-d6/a0/a4,-(sp)
	btst	d4,d5
	bne.s	.drawit
	bsr	chr_restore_now
	bra.s	.did
.drawit:
	bsr	chr_draw_now
.did:	movem.l	(sp)+,d3-d6/a0/a4
.skip:	addq.w	#1,d4
	cmp.w	#14,d4
	blo.s	.cx
.next:	addq.w	#1,d6
	cmp.w	#32,d6
	blo.s	.cy

.fin:	move.w	draw_idx,d0
	lsl.w	#6,d0
	lea	chr_drawn,a0
	add.w	d0,a0
	lea	chr_dirty,a1
	add.w	d0,a1
	lea	chunk_now,a2
	moveq	#31,d0
.cp:	move.w	(a2)+,(a0)+
	clr.w	(a1)+
	dbf	d0,.cp
	rts

; The chunk (d4, d6) in the draw ring at the current window: a1 = ring, a2 = clean, a3 = data

chunk_addrs:
	move.w	d6,d0
	lsl.w	#3,d0
	add.w	cur_T,d0
	ext.l	d0
	lsl.l	#8,d0
	move.w	d4,d1
	lsl.w	#3,d1
	ext.l	d1
	add.l	d1,d0
	add.l	#GAME_X,d0
	lea	(a5,d0.l),a1
	lea	(a6,d0.l),a2
	rts

chr_draw_now:
	bsr.s	chunk_addrs
	bsr	chunk_data
	move.l	a0,a3
	bra	draw8

chr_restore_now:
	bsr.s	chunk_addrs
	moveq	#7,d0
	bra	restore_rows

; The chunk (d4, d6) is not where it was (old_T, chr_d = new - old window): its lines that the new picture does not cover are
; put back (all of them if the chunk is blank now or the pictures do not overlap).

chr_restore_old:
	move.w	d6,d0
	lsl.w	#3,d0
	add.w	old_T,d0			; the old first line
	move.w	d4,d1
	lsl.w	#3,d1
	ext.l	d1
	moveq	#8,d2				; lines to put back
	lea	chunk_now,a0
	move.w	d6,d3
	add.w	d3,d3
	move.w	(a0,d3.w),d3
	btst	d4,d3
	beq.s	.all				; blank now: all of the old picture
	move.w	chr_d,d3
	beq.s	.out
	bpl.s	.pos
	neg.w	d3				; new window above: the old picture's last |d| lines
	cmp.w	#8,d3
	bhs.s	.all
	move.w	d3,d2
	moveq	#8,d1
	sub.w	d3,d1
	add.w	d1,d0
	move.w	d4,d1
	lsl.w	#3,d1
	ext.l	d1
	bra.s	.go
.pos:	cmp.w	#8,d3				; new window below: the old picture's first d lines
	bhs.s	.all
	move.w	d3,d2
	bra.s	.go
.all:	moveq	#8,d2
.go:	ext.l	d0
	lsl.l	#8,d0
	add.l	d1,d0
	add.l	#GAME_X,d0
	lea	(a5,d0.l),a1
	lea	(a6,d0.l),a2
	move.w	d2,d0
	subq.w	#1,d0
	bsr	restore_rows
.out:	rts

; the chunk (d4, d6) is drawn over what the ring shows (a sprite was drawn there or put back)

chunk_draw_over:
	bsr	chunk_addrs
	move.l	a1,a2
	bsr	chunk_data
	move.l	a0,a3
	bra	draw8
