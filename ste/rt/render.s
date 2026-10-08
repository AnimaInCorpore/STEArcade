; ------------------------------------------------------------------------------
; Tile renderer
;
; The arcade background is a 32 x 32 tile map in video RAM ($7400-$77FF), 8 x 8
; pixels, 2 bit, the screen shown rotated by 270 degrees (28 x 32 visible tiles).
; Tiles are expanded offline for every (tile, colour set) into 4 bitplane bytes
; per row (assets.py).  A tile is 8 pixels wide = half of a 16 pixel chunk, so a
; row is written with one MOVEP.L (the left tile to the high bytes, the right
; tile to the low bytes of the plane words).
;
; A background screen holds the tiles only.  Changed tiles are drawn there at
; once and queued for both draw screens (each takes them on its next turn).
; ------------------------------------------------------------------------------

init_render:
	lea	tile_shadow,a0
	move	#255,d0
	moveq	#-1,d1

.clear:
	move.l	d1,(a0)+
	dbf	d0,.clear

	clr	list_count
	clr	list_count+2
	move	#-1,old_bank
	clr	bank16
	st	force_scan
	st	spr_invalid
	st	spr_invalid+1
	move	#-1,spr_cache_bank
	lea	spr_prev_rect,a0
	move	#95,d0
	moveq	#-1,d1
.hide:
	move.l	d1,(a0)+
	dbf	d0,.hide
	rts

; ------------------------------------------------------------------------------
; a6 = Z80 block

render_frame:
	clr.b	cells_ready
	moveq	#0,d0
	move.b	$7d86(a6),d0
	and	#1,d0
	moveq	#0,d1
	move.b	$7d87(a6),d1
	and	#1,d1
	add	d1,d1
	or	d1,d0

	cmp	old_bank,d0
	beq.s	.same_bank

	move	d0,old_bank
	lsl	#4,d0
	move	d0,bank16
	st	force_scan
	st	spr_invalid
	st	spr_invalid+1

.same_bank:
	bsr	scan_tiles
	bsr	draw_dirty_tiles
	bsr	render_sprites
	rts

; ------------------------------------------------------------------------------
; Find the changed tiles, draw them into the background and queue them.

scan_tiles:
	lea	$7400(a6),a0		; video RAM
	lea	tile_shadow,a1
	lea	dirty_lists,a4		; list for draw screen 0
	move	list_count,d4
	add	d4,d4
	add	d4,a4
	lea	dirty_lists+4096,a5	; list for draw screen 1
	move	list_count+2,d5
	add	d5,d5
	add	d5,a5
	move.l	bg_address,a3
	lea	tile_off,a2

	moveq	#0,d6			; byte index of the current long
	move	#255,d7

	tst.b	force_scan
	bne.s	.forced

.scan:
	cmpm.l	(a0)+,(a1)+
	bne.s	.diff

.next_long:
	addq	#4,d6
	dbf	d7,.scan
	bra.s	.finished

.diff:
	subq.l	#4,a0
	subq.l	#4,a1
	moveq	#3,d3
	move	d6,d0			; index of the first byte

.byte:
	move.b	(a0)+,d1
	cmp.b	(a1),d1
	beq.s	.same
	move.b	d1,(a1)
	bsr.s	.queue

.same:
	addq.l	#1,a1
	addq	#1,d0
	dbf	d3,.byte
	bra.s	.next_long

.forced:
	clr.b	force_scan
	lea	tile_blank,a6
	moveq	#0,d0
	move	#1023,d4

.force_one:
	moveq	#0,d1
	move.b	(a0)+,d1
	moveq	#0,d2
	move.b	(a1),d2
	move.b	d1,(a1)+
	move.b	(a6,d2.w),d5
	and.b	(a6,d1.w),d5		; blank before and after: nothing to redraw
	bne.s	.force_skip
	bsr.s	.queue

.force_skip:
	addq	#1,d0
	dbf	d4,.force_one

.finished:
	sub.l	#dirty_lists,a4
	move.l	a4,d0
	lsr	#1,d0
	move	d0,list_count
	lea	dirty_lists+4096,a4
	sub.l	a4,a5
	move.l	a5,d0
	lsr	#1,d0
	move	d0,list_count+2
	rts

; d0.w = tile index (its code is already in the shadow)
; preserves everything except a4/a5 (list pointers)

.queue:
	movem.l	d0-d3/a0-a3,-(sp)

	move	d0,d2
	lsl	#2,d2
	move.l	(a2,d2.w),d2
	bmi.s	.skip			; not visible

	move.l	a3,a0
	bsr	draw_tile

	move.l	(sp),d0
	move	d0,(a4)+
	move	d0,(a5)+

.skip:
	movem.l	(sp)+,d0-d3/a0-a3
	rts

; ------------------------------------------------------------------------------
; Draw the queued tiles into the current draw screen.

draw_dirty_tiles:
	clr	tiles_drawn
	move	draw_index,d0
	move	d0,d1
	add	d1,d1
	lea	list_count,a1
	move	(a1,d1.w),d7
	beq.s	.nothing
	bsr	ensure_cells
	clr	(a1,d1.w)
	move	d7,tiles_drawn

	lea	dirty_lists,a2
	moveq	#12,d1
	lsl	d1,d0
	add	d0,a2

	subq	#1,d7

.loop:
	move	(a2)+,d0
	move.l	a2,-(sp)
	bsr	mark_tile
	move.l	draw_screen_address,a0	; mark_tile clobbers a0
	bsr	draw_tile
	move.l	(sp)+,a2
	dbf	d7,.loop

.nothing:
	rts


	include "sprites.s"

; ------------------------------------------------------------------------------
; draw_tile: d0.w = tile index (visible), a0 = screen base
; trashes d1-d3, a1-a3

draw_tile:
	lea	tile_shadow,a1
	moveq	#0,d1
	move.b	(a1,d0.w),d1
	lsl	#5,d1			; code * 32

	lea	tile_cc,a2
	moveq	#0,d2
	move.b	(a2,d0.w),d2
	add	bank16,d2
	lsl	#2,d2
	lea	dk_tile_combo,a2
	move.l	(a2,d2.w),d2
	add.l	d1,d2
	lea	dk_tiles,a2
	add.l	d2,a2			; source

	lea	tile_off,a3
	move	d0,d3
	lsl	#2,d3
	move.l	(a3,d3.w),d3
	add.l	d3,a0			; destination

	move.l	(a2)+,d3
	movep.l	d3,0(a0)
	move.l	(a2)+,d3
	movep.l	d3,256(a0)
	move.l	(a2)+,d3
	movep.l	d3,512(a0)
	move.l	(a2)+,d3
	movep.l	d3,768(a0)
	move.l	(a2)+,d3
	movep.l	d3,1024(a0)
	move.l	(a2)+,d3
	movep.l	d3,1280(a0)
	move.l	(a2)+,d3
	movep.l	d3,1536(a0)
	move.l	(a2)+,d3
	movep.l	d3,1792(a0)
	rts

; ------------------------------------------------------------------------------
	section bss,bss
; ------------------------------------------------------------------------------

tile_shadow:	ds.b	1024
list_count:	ds.w	2
old_bank:	ds.w	1
bank16:		ds.w	1
force_scan:	ds.b	1
	even
tiles_drawn:	ds.w	1
spr_inv_cur:	ds.b	1
	even
cells:		ds.b	512
cells_ready:	ds.b	1
spr_decode_invalid:	ds.b	1
spr_cache_bank:	ds.w	1
spr_cache_entry:	ds.l	96
spr_new_rect:	ds.w	96
spr_new_routine:	ds.l	96
spr_new_src:	ds.l	96
spr_redraw:	ds.b	96
spr_prev_rect:	ds.w	96*2
spr_invalid:	ds.b	2
	even
spr_prev:	ds.b	384*2

	even
dirty_lists:	ds.w	2048*2
	section text,code
