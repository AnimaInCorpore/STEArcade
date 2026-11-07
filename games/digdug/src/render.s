; ------------------------------------------------------------------------------
; Tile renderer
;
; The arcade picture is a background of 36 x 28 tiles of 8 x 8 pixels, 2 bits (dd1.10b names the tile of each cell for
; the picture the video latch selects, bits 0-1 of its outputs, the colour comes from the tile's code and the latch's
; colour bank, bits 4-5; bit 3 turns the colours black), 1-bit characters of the tile RAM $8000-$83FF over it (pixel 0
; transparent, the colour from the character code) and the sprites on top (draw_sprites).  The screen shows it rotated
; by 90 degrees (dd_map_index: display cell -> tile RAM index, tilemap_scan of MAME).
; A cell is 8 rows of 4 plane bytes (one MOVEP.L), the tile's image (tools/assets.py: dd_bg_img per latch configuration)
; with the character's pixels written over it (dd_fg_mask, dd_fg_col).
;
; A background screen holds the tiles and characters.  Changed cells (the tile RAM compared with a copy every frame:
; 1 KB; or all of them when the latch changed) are drawn there at once and queued for both draw screens.  Sprites are
; drawn over the draw screens (sprites.s); the two bands MAME clips them from (arcade x < 16 and >= 272: display lines
; 0-15 and 272-287) get the background back (restore_bands).
; ------------------------------------------------------------------------------

DISP_TOP = 32				; the display's line 0 is this line of a screen buffer

init_render:
	lea	cell_shadow,a0
	move	#255,d0
	moveq	#-1,d1
.clear:
	move.l	d1,(a0)+
	dbf	d0,.clear
	lea	cell_content,a0		; (every cell has content: the sprites' restore always copies the background)
	move	#MARK_SIZE/4-1,d0
.clear_content:
	move.l	d1,(a0)+
	dbf	d0,.clear_content
	clr	list_count
	clr	list_count+2
	clr.b	list_full
	clr.b	list_full+1
	st	force_scan
	move.w	#-1,bg_state
	bsr	init_sprites
	rts

; ------------------------------------------------------------------------------

render_frame:
	ifd SLOWRENDER			; (test: a render of SLOWRENDER x 12 cycles: the next VBL comes during it, as in a busy Hatari scene)
	move.l	#SLOWRENDER,d0
.slow:	subq.l	#1,d0
	bne.s	.slow
	endc
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
	lea	spr_marks,a0
	rept MARK_SIZE/32
	movem.l	d0-d7,(a0)
	lea	32(a0),a0
	endr

	bsr	check_latch
	bsr	scan_cells
	bsr	draw_dirty_cells
	bsr	draw_sprites
	bra	restore_bands

; The video latch ($A000-$A007, cells in the RAM): the picture (Q0, Q1), the colour bank (Q4, Q5), the colours off (Q3).
; A change redraws every cell.  (Q2, the character colour mode, and Q7, the screen flip of the cocktail table, are not
; supported: Dig Dug sets neither in the upright mode.)

check_latch:
	lea	g_ram+$2000,a0
	moveq	#1,d2
	moveq	#0,d0
	move.b	(a0),d0			; Q0
	and	d2,d0
	moveq	#0,d1
	move.b	1(a0),d1		; Q1
	and	d2,d1
	add	d1,d1
	or	d1,d0			; picture
	moveq	#0,d1
	move.b	4(a0),d1		; Q4
	and	d2,d1
	moveq	#0,d3
	move.b	5(a0),d3		; Q5
	and	d2,d3
	add	d3,d3
	or	d3,d1			; bank 0-3
	add	d1,d1			; * 2 + disable = configuration
	moveq	#0,d3
	move.b	3(a0),d3		; Q3
	and	d2,d3
	or	d3,d1			; configuration 0-7
	lsl	#3,d1
	or	d1,d0			; state: picture | configuration << 3
	cmp	bg_state,d0
	beq.s	.same
	move	d0,bg_state
	st	force_scan
	moveq	#3,d1
	and	d0,d1
	lsl	#8,d1
	lsl	#2,d1			; picture * 1024
	move	d1,bg_pic
	lsr	#3,d0			; configuration
	and	#7,d0
	lsl.l	#8,d0
	lsl.l	#5,d0			; * 8192: 256 tiles of 32 bytes
	add.l	#dd_bg_img,d0
	move.l	d0,bg_img_base
.same:
	rts

; ------------------------------------------------------------------------------
; Find the changed cells (tile RAM), draw them into the background and queue them.

scan_cells:
	lea	g_ram,a0		; the tile RAM
	lea	cell_shadow,a1
	lea	dirty_lists,a4		; list for draw screen 0
	move	list_count,d4
	add	d4,d4
	add	d4,a4
	lea	dirty_lists+4096,a5	; list for draw screen 1
	move	list_count+2,d5
	add	d5,d5
	add	d5,a5
	move.l	bg_address,a3

	tst.b	force_scan
	bne	.forced
	moveq	#1024/32-1,d7
	bsr	.compare
	bra	.finished

; d7 + 1 groups of 32 bytes at a0 (the tile RAM) / a1 (its copy): the changed cells queued
.compare:
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
.c8:	dbf	d7,.compare
	rts

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

; The long before a0 / a1 differs: queue the cells of its changed bytes.

.diff:
	subq.l	#4,a0
	subq.l	#4,a1
	move.l	a0,d0
	sub.l	#g_ram,d0		; index of the first byte
	moveq	#3,d3
.byte:
	move.b	(a0)+,d1
	cmp.b	(a1),d1
	beq.s	.same
	move.b	d1,(a1)
	move	d0,d2
	bsr.s	.queue
.same:
	addq.l	#1,a1
	addq	#1,d0
	dbf	d3,.byte
	rts

.forced:
	clr.b	force_scan
	move	#1023,d3
.copy:	move.b	(a0)+,(a1)+
	dbf	d3,.copy
	moveq	#0,d2
.force_one:
	bsr.s	.queue
	addq	#1,d2
	cmp	#1024,d2
	blt.s	.force_one

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

; d2.w = tile RAM index of a cell; preserves everything except a4/a5 (list pointers)

.queue:
	movem.l	d0-d3/a0-a3,-(sp)
	move	d2,d0
	add	d0,d0
	lea	dd_cell_of_index,a1
	move	(a1,d0.w),d0		; display cell
	bmi.s	.skip			; not shown
	move.l	a3,a0
	bsr	draw_cell
	cmp.l	#dirty_lists+4096,a4	; a full list (a draw screen that is not drawn for a few
	blo.s	.q0			; frames while the program rewrites the screen): the
	st	list_full		; screen gets all its cells again
	bra.s	.q1
.q0:	move	d0,(a4)+		; (a4 and a5 are not saved: they advance)
.q1:	cmp.l	#dirty_lists+8192,a5
	blo.s	.q2
	st	list_full+1
	bra.s	.skip
.q2:	move	d0,(a5)+
.skip:
	movem.l	(sp)+,d0-d3/a0-a3
	rts

; ------------------------------------------------------------------------------
; Draw the queued cells into the current draw screen and mark them.

draw_dirty_cells:
	move	draw_index,d0
	move	d0,d1
	add	d1,d1
	lea	list_count,a1
	lea	list_full,a0
	tst.b	(a0,d0.w)
	bne.s	.all
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
	bsr	draw_cell
	move.l	(sp)+,a2
	bsr	mark_cell
	dbf	d7,.loop
.nothing:
	rts

.all:	clr.b	(a0,d0.w)		; the list overflowed: every cell of the screen
	clr	(a1,d1.w)
	moveq	#0,d7
.all_loop:
	move	d7,d0
	add	d0,d0
	lea	dd_cell_of_index,a1
	move	(a1,d0.w),d0
	bmi.s	.all_next
	move.l	draw_screen_address,a0
	bsr	draw_cell
	bsr	mark_cell
.all_next:
	addq	#1,d7
	cmp	#1024,d7
	blo.s	.all_loop
	rts

; d0.w = display cell: the sprites on it have to be drawn again.  Keeps d0.

mark_cell:
	move	d0,d1
	add	d1,d1
	lea	dd_cell_mark_byte,a1
	move	(a1,d1.w),d1
	lea	dd_cell_mark_bit,a3
	move.b	(a3,d0.w),d2
	lea	tile_marks,a1
	bset	d2,(a1,d1.w)
	rts

; ------------------------------------------------------------------------------
; draw_cell: d0.w = display cell, a0 = screen base.  Trashes d1-d3, a1-a3 (d4-d6 kept).

draw_cell:
	movem.l	d4-d6,-(sp)
	move	d0,d1
	add	d1,d1
	lea	dd_map_index,a1
	move	(a1,d1.w),d2		; tile RAM index
	moveq	#0,d3
	move	bg_pic,d3
	add	d2,d3
	lea	dd_bgmap,a1
	moveq	#0,d1
	move.b	(a1,d3.w),d1		; the background tile's code
	lsl	#5,d1
	move.l	bg_img_base,a2
	add.l	d1,a2			; its image: 8 rows of 4 plane bytes
	lea	g_ram,a1
	moveq	#0,d3
	move.b	(a1,d2.w),d3		; the character's code byte
	move	d3,d4
	and	#$7f,d4
	lea	dd_fg_blank,a1
	tst.b	(a1,d4.w)
	bne.s	.plain

	; a character over the tile: per row (tile & ~mask) | (colour & mask), the mask the row's byte in every plane
	move	d0,d6
	lsl	#2,d6
	lea	dd_cell_off,a1
	move.l	(a1,d6.w),d6
	add.l	#DISP_TOP*STRIDE,d6
	add.l	d6,a0			; destination
	lsl	#5,d4
	lea	dd_fg_mask,a3
	add	d4,a3			; its masks: 8 longs
	lsl	#2,d3
	lea	dd_fg_col,a1
	move.l	(a1,d3.w),d5		; its colour's planes
	moveq	#7,d6
.row:	move.l	(a2)+,d1
	move.l	(a3)+,d2
	move.l	d2,d3
	not.l	d3
	and.l	d3,d1
	and.l	d5,d2
	or.l	d2,d1
	movep.l	d1,0(a0)
	lea	256(a0),a0
	dbf	d6,.row
	movem.l	(sp)+,d4-d6
	rts

.plain:	move	d0,d3
	lsl	#2,d3
	lea	dd_cell_off,a3
	move.l	(a3,d3.w),d3
	add.l	#DISP_TOP*STRIDE,d3
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
	movem.l	(sp)+,d4-d6
	rts

; ------------------------------------------------------------------------------
; The bands MAME's sprites do not reach (arcade x < 16 and x >= 272: display lines 0-15 and 272-287): after the sprites
; the background is copied back over them (a plain copy of 16 lines of the picture's width, twice).

restore_bands:
	move	#2,BLT_SRC_XINC.w
	move	#2,BLT_DST_XINC.w
	move	#$ffff,BLT_END1.w
	move	#$ffff,BLT_END2.w
	move	#$ffff,BLT_END3.w
	move	#$0203,BLT_HOP_OP.w
	clr.b	BLT_SKEW.w
	move	#256-28*2+2,d0		; the picture: 28 words (112 bytes) of 4 planes a line, 8 + 16 bytes aside
	move	d0,BLT_SRC_YINC.w
	move	d0,BLT_DST_YINC.w
	move.l	bg_address,d1
	add.l	#(DISP_TOP+0)*STRIDE+24,d1
	move.l	draw_screen_address,d2
	add.l	#(DISP_TOP+0)*STRIDE+24,d2
	bsr.s	.band
	move.l	bg_address,d1
	add.l	#(DISP_TOP+272)*STRIDE+24,d1
	move.l	draw_screen_address,d2
	add.l	#(DISP_TOP+272)*STRIDE+24,d2
.band:	move.l	d1,BLT_SRC_ADDR.w
	move.l	d2,BLT_DST_ADDR.w
	move	#28,BLT_COUNT.w
	move	#16,BLT_COUNT+2.w
	bra	blit_go

; ------------------------------------------------------------------------------
	section bss,bss
; ------------------------------------------------------------------------------

cell_shadow:	ds.b	1024
cell_content:	ds.b	MARK_SIZE		; bit set: the background cell is not black (always: see init_render)
list_count:	ds.w	2
force_scan:	ds.b	1
	even
list_full:	ds.b	2		; per draw screen: its dirty list overflowed
	even
bg_state:	ds.w	1		; the video latch's picture | configuration << 3 (-1: unknown)
bg_pic:		ds.w	1		; picture * 1024: its offset in dd_bgmap
bg_img_base:	ds.l	1		; dd_bg_img of the configuration
dirty_lists:	ds.w	2048*2
	section text,code

; (a render needs no throttle here: Galaga's stars were what it thinned out)
throttle_start:
throttle_update:
	rts
