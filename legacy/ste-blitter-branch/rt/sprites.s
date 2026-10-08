; ------------------------------------------------------------------------------
; Sprites
;
; The sprite list ($6900, 96 x y / code+flipy / colour+flipx / x) is turned into Blitter
; work on the draw screen.  Only what changed is redrawn:
;
; * a slot is "changed" when its entry or its position differs from what was drawn into
;   this screen two frames ago, or when the colours were invalidated (palette bank);
; * the rectangles (2 chunks x 16 lines) of changed slots, old and new, and every tile
;   that was redrawn on this screen mark cells (1 chunk x 16 lines) as dirty;
; * unchanged slots that touch a dirty cell are redrawn too, until nothing is added;
; * the old rectangles of redrawn slots are copied back from the background screen with
;   the Blitter and the redrawn sprites are drawn in order through the generated
;   routines (see sprites.py): every routine pops its destination (word) and source (long).
;
; Display position (cabinet flip bit 1):  x = 224 - ((247 - y) & 255), y = (x - 8) & 255
; ------------------------------------------------------------------------------

clear_cells:
	lea	cells,a0
	moveq	#0,d0
	moveq	#127,d1

.clear:
	move.l	d0,(a0)+
	dbf	d1,.clear
	rts

; Clear once, only when tiles or sprites need dirty tracking.
ensure_cells:
	tst.b	cells_ready
	bne.s	.done
	movem.l	d0-d1/a0,-(sp)
	bsr	clear_cells
	st	cells_ready
	movem.l	(sp)+,d0-d1/a0
.done:
	rts

; d0.w = rectangle offset (y * 256 + chunk * 8): marks its cells (up to 2 x 2)
; trashes d0-d2, a0

mark_rect:
	moveq	#0,d1
	move.b	d0,d1
	lsr	#3,d1			; chunk
	lsr	#8,d0			; y
	move	d0,d2
	lsr	#4,d2
	lsl	#5,d2			; first cell row * 32
	add	#15,d0
	lsr	#4,d0
	lsl	#5,d0			; last cell row * 32
	lea	cells,a0
	add	d1,a0
	st	(a0,d2.w)
	st	1(a0,d2.w)
	cmp	d0,d2
	beq.s	.done
	st	(a0,d0.w)
	st	1(a0,d0.w)

.done:
	rts

; d0.w = rectangle offset -> Z clear when one of its cells is dirty
; trashes d0-d3, a0

test_rect:
	moveq	#0,d1
	move.b	d0,d1
	lsr	#3,d1
	lsr	#8,d0
	move	d0,d2
	lsr	#4,d2
	lsl	#5,d2
	add	#15,d0
	lsr	#4,d0
	lsl	#5,d0
	lea	cells,a0
	add	d1,a0
	moveq	#0,d3
	or.b	(a0,d2.w),d3
	or.b	1(a0,d2.w),d3
	cmp	d0,d2
	beq.s	.done
	or.b	(a0,d0.w),d3
	or.b	1(a0,d0.w),d3

.done:
	tst.b	d3
	rts

; d0.w = tile index (visible): marks its cell; trashes d1, d2, a0, a1

mark_tile:
	lea	tile_off,a1
	move	d0,d1
	lsl	#2,d1
	move.l	(a1,d1.w),d1		; screen offset
	bmi.s	.done
	move	d1,d2
	lsr	#8,d2			; y
	lsr	#4,d2
	lsl	#5,d2			; cell row * 32
	and	#$ff,d1
	lsr	#3,d1			; chunk
	lea	cells,a0
	add	d1,d2
	st	(a0,d2.w)

.done:
	rts

; ------------------------------------------------------------------------------

render_sprites:
	move	draw_index,d0

	; Quick exit: same list as drawn into this screen before and no tile redrawn.

	lea	spr_invalid,a2
	tst.b	(a2,d0.w)
	bne.s	.full
	tst	tiles_drawn
	bne.s	.full

	move	d0,d1
	mulu	#384,d1
	lea	spr_prev,a1
	add.l	d1,a1
	lea	z80_block+$6900,a0
	moveq	#95,d7

.same:
	cmpm.l	(a0)+,(a1)+
	dbne	d7,.same
	beq	.exit

.full:
	bsr	ensure_cells
	move	bank16,d0
	cmp	spr_cache_bank,d0
	sne	spr_decode_invalid
	move	d0,spr_cache_bank
	move	draw_index,d0
	lea	spr_invalid,a2
	move.b	(a2,d0.w),spr_inv_cur
	clr.b	(a2,d0.w)

	; --- pass A: the new state of every slot

	move	d0,d1
	mulu	#384,d1
	lea	spr_prev,a5
	add.l	d1,a5
	move	d0,d1
	mulu	#192,d1
	lea	spr_prev_rect,a6
	add.l	d1,a6

	lea	z80_block+$6900,a1
	lea	spr_new_rect,a2
	lea	spr_new_routine,a3
	lea	spr_new_src,a4
	moveq	#0,d5			; slot
	move	#95,d7

.slot:
	; Cache decoding independently of each screen's previous drawn state.
	tst.b	spr_decode_invalid
	bne.s	.decode
	move	d5,d6
	lsl	#2,d6
	lea	spr_cache_entry,a0
	move.l	(a1),d0
	cmp.l	(a0,d6.w),d0
	bne.s	.decode
	move	(a2),d3
	move.l	(a3),d0
	move.l	(a4),d4
	bra	.store

.decode:
	moveq	#0,d0
	move.b	(a1),d0			; y
	move	#247,d1
	sub	d0,d1
	and	#$ff,d1			; first raw row
	move	#224,d2
	sub	d1,d2			; x position on the display
	cmp	#-15,d2
	blt	.hidden
	cmp	#223,d2
	bgt	.hidden

	moveq	#0,d3
	move.b	3(a1),d3
	subq	#8,d3
	and	#$ff,d3			; y position
	cmp	#240,d3
	bhi	.hidden

	moveq	#0,d0
	move.b	1(a1),d0		; code | flip y
	moveq	#0,d1
	move.b	2(a1),d1		; colour | flip x
	move	d0,d4
	and	#$7f,d4
	add	d4,d4
	add	d4,d4			; code * 4
	tst.b	d0
	bpl.s	.no_fy
	addq	#1,d4

.no_fy:
	tst.b	d1
	bpl.s	.no_fx
	addq	#2,d4

.no_fx:
	move	d4,d0
	add	d0,d0
	add	d0,d0
	lea	spr_shape_table,a0
	move.l	(a0,d0.w),d0		; routine table of the shape
	beq	.hidden

	and	#15,d1
	add	bank16,d1		; colour set (bank * 16 + colour code)
	lea	spr_combo_triple,a0
	moveq	#0,d6
	move.b	(a0,d1.w),d6		; colour triple
	mulu	#SPR_TRIPLES,d4
	add	d6,d4
	lsl.l	#2,d4
	lea	spr_data_table,a0
	move.l	(a0,d4.l),d4		; offset + 1 into the source data
	beq	.hidden
	subq.l	#1,d4
	add.l	#dk_sprdata,d4

	move	d2,d1
	add	#48,d1			; x on the screen
	moveq	#15,d6
	and	d1,d6			; pixel shift
	lsr	#4,d1			; chunk
	lsl	#3,d1
	lsl	#8,d3
	add	d1,d3			; destination offset (low word)

	lsl	#2,d6
	move.l	d0,a0
	move.l	(a0,d6.w),d0		; routine of this shift
	bra.s	.store

.hidden:
	move	#$ffff,d3
	moveq	#0,d0
	moveq	#0,d4

.store:
	move	d5,d6
	lsl	#2,d6
	lea	spr_cache_entry,a0
	move.l	(a1),(a0,d6.w)
	move	d3,(a2)+
	move.l	d0,(a3)+
	move.l	d4,(a4)+

	move.l	(a1)+,d1		; entry
	move.l	(a5),d0
	move.l	d1,(a5)+
	cmp.l	d0,d1
	sne	d1			; entry changed
	move	(a6)+,d2		; rectangle drawn before
	cmp	d3,d2
	bne.s	.changed
	cmp	#$ffff,d3
	beq.s	.unchanged		; hidden before and now
	tst.b	d1
	bne.s	.changed
	tst.b	spr_inv_cur
	bne.s	.changed

.unchanged:
	lea	spr_redraw,a0
	clr.b	(a0,d5.w)
	bra.s	.next

.changed:
	lea	spr_redraw,a0
	st	(a0,d5.w)
	move	d3,-(sp)
	move	d2,d0
	cmp	#$ffff,d0
	beq.s	.no_old
	bsr	mark_rect

.no_old:
	move	(sp)+,d0
	cmp	#$ffff,d0
	beq.s	.next
	bsr	mark_rect

.next:
	addq	#1,d5
	dbf	d7,.slot

	; --- unchanged slots that touch a dirty cell are redrawn too

.closure:
	moveq	#0,d6
	lea	spr_new_rect,a2
	lea	spr_redraw,a3
	move	#95,d7

.close:
	move	(a2)+,d0
	cmp	#$ffff,d0
	beq.s	.close_next
	tst.b	(a3)
	bne.s	.close_next
	move	d0,-(sp)
	bsr	test_rect
	beq.s	.clean
	st	(a3)
	move	(sp),d0
	bsr	mark_rect
	moveq	#1,d6

.clean:
	addq.l	#2,sp

.close_next:
	addq.l	#1,a3
	dbf	d7,.close

	tst	d6
	bne.s	.closure

	; --- copy the old rectangles of redrawn slots back from the background

	move	draw_index,d0
	mulu	#192,d0
	lea	spr_prev_rect,a6
	add.l	d0,a6
	lea	spr_redraw,a3
	move.l	bg_address,d1
	move.l	draw_screen_address,d2
	moveq	#0,d6			; blitter configured?
	move	#95,d7

.restore:
	tst.b	(a3)+
	beq.s	.restore_next
	move	(a6),d0
	cmp	#$ffff,d0
	beq.s	.restore_next

	tst	d6
	bne.s	.configured
	moveq	#1,d6
	move	#2,$ffff8a20.w		; Source X increment
	move	#242,$ffff8a22.w	; Source Y increment (256 - 16 + 2)
	move	#2,$ffff8a2e.w		; Destination X increment
	move	#242,$ffff8a30.w	; Destination Y increment
	move	#$ffff,$ffff8a28.w
	move	#$ffff,$ffff8a2a.w
	move	#$ffff,$ffff8a2c.w
	move.b	#2,$ffff8a3a.w		; HOP 2 (source)
	move.b	#3,$ffff8a3b.w		; OP 3 (destination = source)
	clr.b	$ffff8a3d.w
	move	#8,$ffff8a36.w		; X count: 2 chunks of 4 plane words

.configured:
	; A rectangle ending at row 256 advances the Blitter's high word.
	; Rewrite full addresses so the next rectangle stays in this buffer.
	move	d0,d1
	move.l	d1,$ffff8a24.w
	move	d0,d2
	move.l	d2,$ffff8a32.w
	move	#16,$ffff8a38.w
	move.b	#$c0,$ffff8a3c.w	; Busy + Hog

.restore_next:
	addq.l	#2,a6
	dbf	d7,.restore

	; --- remember what is drawn into this screen now

	move	draw_index,d0
	mulu	#192,d0
	lea	spr_prev_rect,a0
	add.l	d0,a0
	lea	spr_new_rect,a1
	moveq	#47,d7

.remember:
	move.l	(a1)+,(a0)+
	dbf	d7,.remember

	; --- chain of the redrawn sprites (the last one is pushed first)

	lea	spr_new_rect+192,a2
	lea	spr_new_routine+384,a3
	lea	spr_new_src+384,a4
	lea	spr_redraw+96,a5
	moveq	#0,d6
	pea	.chain_done(pc)
	move	#95,d7

.chain:
	move.l	-(a3),d0
	move.l	-(a4),d4
	move	-(a2),d3
	tst.b	-(a5)
	beq.s	.chain_next
	cmp	#$ffff,d3
	beq.s	.chain_next
	move.l	d4,-(sp)		; source
	move	d3,-(sp)		; destination
	move.l	d0,-(sp)		; routine
	addq	#1,d6

.chain_next:
	dbf	d7,.chain

	tst	d6
	beq.s	.nothing

	move.b	#2,$ffff8a3a.w		; HOP 2 (source only)
	move.b	#3,$ffff8a3b.w		; OP 3 (destination = source)
	move	#2,$ffff8a20.w		; Source X increment
	move	#2,$ffff8a22.w		; Source Y increment
	move	#8,$ffff8a2e.w		; Destination X increment
	move	#$ffff,$ffff8a2a.w	; Endmask 2
	move	draw_screen_address,$ffff8a32.w

	moveq	#2,d0			; destination Y increment, X count 1
	moveq	#-6,d1			; destination Y increment, X count 2
	move.l	#(1<<16)+4,d2
	move.l	#(2<<16)+4,d3
	move	#STRIDE-8,d4		; next line address offset
	move	#-STRIDE-8,d5		; previous line address offset
	moveq	#4,d6			; Y count
	moveq	#$ffffffc0,d7		; Busy + Hog

	lea	$ffff8a24.w,a0		; Source address
	lea	$ffff8a30.w,a1		; Destination Y increment
	lea	$ffff8a28.w,a2		; Endmask 1
	lea	$ffff8a2c.w,a3		; Endmask 3
	lea	$ffff8a32+2.w,a4	; Destination address (low word)
	lea	$ffff8a38.w,a5		; Y count
	lea	$ffff8a3c.w,a6		; Busy, Hog, Smudge, Line number, FXSR, NFSR, Skew

	rts				; run the chain

.chain_done:
	rts

.nothing:
	addq.l	#4,sp			; the continuation pushed above

.exit:
	rts
