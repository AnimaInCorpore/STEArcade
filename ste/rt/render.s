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
	bsr	init_sprites
	rts

; ------------------------------------------------------------------------------
; a6 = Z80 block

render_frame:
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

.same_bank:
	ifnd NOSPRITES
	lea	tile_marks,a0		; no cell is marked yet in this frame
	moveq	#0,d0
	moveq	#0,d1
	moveq	#0,d2
	moveq	#0,d3
	moveq	#0,d4
	moveq	#0,d5
	moveq	#0,d6
	moveq	#0,d7
	rept MARK_SIZE/32
	movem.l	d0-d7,(a0)
	lea	32(a0),a0
	endr
	endc
	bsr	scan_tiles
	bsr	draw_dirty_tiles
	ifnd NOSPRITES
	bsr	draw_sprites
	endc
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

	tst.b	force_scan
	bne.s	.forced

	; The tiles of the 28 visible rows ($7440 - $77BF), eight longs per turn.

	lea	$40(a0),a0
	lea	$40(a1),a1
	move	#224/8-1,d7

.scan:
	cmpm.l	(a0)+,(a1)+
	bne.s	.diff0
.c1:	cmpm.l	(a0)+,(a1)+
	bne.s	.diff1
.c2:	cmpm.l	(a0)+,(a1)+
	bne.s	.diff2
.c3:	cmpm.l	(a0)+,(a1)+
	bne.s	.diff3
.c4:	cmpm.l	(a0)+,(a1)+
	bne.s	.diff4
.c5:	cmpm.l	(a0)+,(a1)+
	bne.s	.diff5
.c6:	cmpm.l	(a0)+,(a1)+
	bne.s	.diff6
.c7:	cmpm.l	(a0)+,(a1)+
	bne.s	.diff7
.c8:	dbf	d7,.scan
	bra.s	.finished

.diff0:	bsr.s	.diff
	bra.s	.c1
.diff1:	bsr.s	.diff
	bra.s	.c2
.diff2:	bsr.s	.diff
	bra.s	.c3
.diff3:	bsr.s	.diff
	bra.s	.c4
.diff4:	bsr.s	.diff
	bra.s	.c5
.diff5:	bsr.s	.diff
	bra.s	.c6
.diff6:	bsr.s	.diff
	bra.s	.c7
.diff7:	bsr.s	.diff
	bra.s	.c8

; The long before a0 / a1 differs: queue its changed bytes.

.diff:
	subq.l	#4,a0
	subq.l	#4,a1
	move.l	a0,d0
	sub.l	a6,d0
	sub	#$7400,d0		; index of the first byte
	moveq	#3,d3

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
	rts

.forced:
	clr.b	force_scan
	moveq	#0,d0
	move	#1023,d3

.force_one:
	move.b	(a0)+,d1
	move.b	d1,(a1)+
	bsr.s	.queue
	addq	#1,d0
	dbf	d3,.force_one

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
	move	draw_index,d0
	move	d0,d1
	add	d1,d1
	lea	list_count,a1
	move	(a1,d1.w),d7
	beq.s	.nothing
	clr	(a1,d1.w)

	lea	dirty_lists,a2
	moveq	#12,d1
	lsl	d1,d0
	add	d0,a2

	subq	#1,d7

.loop:
	move	(a2)+,d0
	move.l	draw_screen_address,a0
	move.l	a2,-(sp)
	bsr	draw_tile
	move.l	(sp)+,a2

	ifnd NOSPRITES
	move	d0,d1			; sprites on this tile have to be drawn again
	add	d1,d1
	lea	tile_mark_byte,a1
	move	(a1,d1.w),d1
	lea	tile_mark_bit,a1
	move.b	(a1,d0.w),d2
	lea	tile_marks,a1
	bset	d2,(a1,d1.w)
	endc

	dbf	d7,.loop

.nothing:
	rts

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
dirty_lists:	ds.w	2048*2
	section text,code
