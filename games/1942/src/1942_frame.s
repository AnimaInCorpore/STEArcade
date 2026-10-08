; ------------------------------------------------------------------------------
; One frame
; ------------------------------------------------------------------------------

; Draws the game's picture into the draw ring (see the header of this file's parent) and makes it the frame to be shown.
; Everything is free to use, the Z80 registers are dead at the idle point where the hook calls this.

render_frame:
	dbgcnt	dbg_c2,1
	stage	$f0f
	; the window: T = (256 - scroll) & 511, the palette bank
	moveq	#0,d0
	move.b	Z_SCROLL+1,d0
	lsl.w	#8,d0
	move.b	Z_SCROLL,d0
	neg.w	d0
	add.w	#256,d0
	and.w	#$1FF,d0
	move.w	d0,cur_T
	moveq	#0,d0
	move.b	Z_PALBANK,d0
	and.w	#3,d0
	cmp.w	cur_bank,d0
	beq.s	.same_bank
	bsr	set_bank
.same_bank:
	; baked data nearly out of memory: start the caches over (the pictures stay)
	cmp.l	#tile_pool+TILE_POOL_SIZE-$20000,tile_pool_ptr
	bhs.s	.flush
	cmp.l	#spr_pool+SPR_POOL_SIZE-$8000,spr_pool_ptr
	bhs.s	.flush
	cmp.l	#chr_pool+CHR_POOL_SIZE-$8000,chr_pool_ptr
	blo.s	.pools
.flush:	bsr	flush_caches
.pools:
	; the background and character RAM are only looked at after a store to them (the translated program sets bg_dirty / fg_dirty
	; at the sites that store there), after a palette bank change, and every 32nd frame as a safety net
	subq.b	#1,rescan
	bpl.s	.norescan
	move.b	#31,rescan
	st	bg_dirty
	st	fg_dirty
.norescan:
	tst.b	full_redraw
	bne.s	.bg
	tst.b	bg_dirty
	beq.s	.nobg
.bg:	clr.b	bg_dirty
	bsr	rf_bg
.nobg:
	tst.b	full_redraw
	bne.s	.fg
	tst.b	fg_dirty
	beq.s	.nofg
.fg:	clr.b	fg_dirty
	bsr	rf_chr_diff
.nofg:
	tst.b	full_redraw
	beq.s	.partial
	bsr	rf_full
	stage	$300
.partial:
	move.w	draw_idx,d0
	add.w	d0,d0
	lea	ring_T,a0
	moveq	#0,d1
	move.w	cur_T,d2
	cmp.w	(a0,d0.w),d2
	beq.s	.still
	moveq	#1,d1
.still:	move.b	d1,t_moved

	; the old rectangles of the sprites go back
	bsr	rf_spr_restore
	stage	$400
	move.w	draw_idx,d0
	lsl.w	#2,d0
	lea	ring_base,a1
	move.l	(a1,d0.w),a2
	bsr	rf_apply_tiles
	stage	$500
	bsr	rf_chr
	stage	$600
	tst.b	t_moved
	bne.s	.nooverlay
	bsr	overlay_old
.nooverlay:
	bsr	rf_sprites_start
	bsr	rf_sprites
	stage	$700
	bsr	overlay_new
	stage	$777

	; this ring is the next picture
	move.w	draw_idx,d0
	add.w	d0,d0
	lea	ring_T,a0
	move.w	cur_T,(a0,d0.w)
	move.w	draw_idx,d0
	lsl.w	#2,d0
	lea	ring_base,a1
	move.l	(a1,d0.w),d1
	moveq	#0,d2
	move.w	cur_T,d2
	lsl.l	#8,d2
	add.l	d2,d1
	sub.l	#PIC_TOP*STRIDE,d1		; (the first lines shown are black: the picture is centred)
	move.l	d1,flip_addr
	eori.w	#1,draw_idx
	st	frame_ready
	rts

; The whole clean ring is the picture of both draw rings (a palette bank change or the start): Blitter copies of the
; game area (14 chunks of every line), and the rings forget what they showed.

rf_full:
	moveq	#1,d3
.ring:	move.w	d3,d0
	lsl.w	#2,d0
	lea	ring_base,a1
	move.l	(a1,d0.w),a1
	add.l	#GAME_X,a1
	move.l	clean_base,a0
	add.l	#GAME_X,a0
	moveq	#RING_LINES/32-1,d4		; 32 lines at a time
.seg:	movem.l	d3-d4/a0-a1,-(sp)
	moveq	#56,d0
	moveq	#32,d1
	bsr	blit_copy
	movem.l	(sp)+,d3-d4/a0-a1
	add.l	#32*STRIDE,a0
	add.l	#32*STRIDE,a1
	dbf	d4,.seg
	dbf	d3,.ring
	lea	tile_pend,a0
	moveq	#63,d0
.pend:	clr.w	(a0)+
	dbf	d0,.pend
	lea	chr_drawn,a0
	lea	chr_dirty,a1
	moveq	#63,d0
.chr:	clr.w	(a0)+
	clr.w	(a1)+
	dbf	d0,.chr
	clr.w	rect_cnt
	clr.w	rect_cnt+2
	move.w	#-1,ring_T
	move.w	#-1,ring_T+2
	clr.b	full_redraw
	rts

rf_sprites_start:
	move.w	draw_idx,d0
	add.w	d0,d0
	lea	rect_cnt,a0
	clr.w	(a0,d0.w)
	rts

; The chunks with characters that the rectangles of the sprites touch are drawn over what the ring shows.

overlay_old:
	move.w	draw_idx,d0
	bra.s	overlay_list

overlay_new:
	move.w	draw_idx,d0
overlay_list:
	move.w	d0,d1
	move.w	d0,-(sp)
	lsl.w	#2,d0
	lea	ring_base,a0
	move.l	(a0,d0.w),a5
	move.l	clean_base,a6
	move.w	(sp)+,d0
	add.w	d1,d1
	lea	rect_cnt,a0
	move.w	(a0,d1.w),d7
	subq.w	#1,d7
	bmi.s	.none
	mulu	#MAX_RECTS*16,d0
	lea	rects,a4
	add.l	d0,a4
.rect:	movem.l	d7/a4,-(sp)
	bsr.s	overlay_rect
	movem.l	(sp)+,d7/a4
	lea	16(a4),a4
	dbf	d7,.rect
.none:	rts

; a4 = a rectangle record

overlay_rect:
	move.w	10(a4),d0
	move.w	12(a4),d1
	tst.w	d0
	bpl.s	.y0
	moveq	#0,d0
.y0:	cmp.w	#255,d1
	ble.s	.y1
	move.w	#255,d1
.y1:	cmp.w	d0,d1
	blt.s	.out
	lsr.w	#3,d0				; first chunk row
	lsr.w	#3,d1				; last
	move.w	6(a4),d2
	moveq	#1,d3
	lsl.w	d2,d3
	subq.w	#1,d3				; chunks bits
	move.w	8(a4),d2
	bmi.s	.neg
	lsl.w	d2,d3
	bra.s	.cols
.neg:	neg.w	d2
	lsr.w	d2,d3
.cols:	and.w	#$3FFF,d3
	beq.s	.out
	move.w	d0,d6
.cy:	lea	chunk_now,a0
	move.w	d6,d2
	add.w	d2,d2
	move.w	(a0,d2.w),d5
	and.w	d3,d5
	beq.s	.skip
	moveq	#0,d4
.cx:	btst	d4,d5
	beq.s	.nocx
	movem.l	d1/d3-d6,-(sp)
	bsr	chunk_draw_over
	movem.l	(sp)+,d1/d3-d6
.nocx:	addq.w	#1,d4
	cmp.w	#14,d4
	blo.s	.cx
.skip:	addq.w	#1,d6
	cmp.w	d1,d6
	ble.s	.cy
.out:	rts

; ------------------------------------------------------------------------------
	section data,data
; ------------------------------------------------------------------------------

	cnop	0,2
tile_masks:	incbin "tile_masks.bin"
spr_masks:	incbin "spr_masks.bin"
spr_opaque:	incbin "spr_opaque.bin"
spr_plan_offsets:	incbin "spr_plan_offsets.bin"	; (the generic path: shift independent plans per sprite)
spr_plan:	incbin "spr_plan.bin"
	include "spr_code.s"			; the generated Blitter routines (spritegen.py); leaves the text section selected
	section data,data
chr_masks:	incbin "chr_masks.bin"
spr_blank:	incbin "spr_blank.bin"
chr_blank:	incbin "chr_blank.bin"
luts:		incbin "luts.bin"
palmap:		incbin "palmap.bin"
palette:	incbin "palette.bin"
	include "render_tables.s"
blank_cell:	ds.b	96

; ------------------------------------------------------------------------------
	section bss,bss
; ------------------------------------------------------------------------------

ring_base:	ds.l	2
clean_base:	ds.l	1
flip_addr:	ds.l	1
w_base:		ds.l	1
rect_base:	ds.l	1
rect_fill:	ds.l	1
spr_toff:	ds.l	1
spr_ep:		ds.l	1
spr_e:		ds.w	1
tile_pool_ptr:	ds.l	1
spr_pool_ptr:	ds.l	1
chr_pool_ptr:	ds.l	1
draw_idx:	ds.w	1
cur_bank:	ds.w	1
cur_T:		ds.w	1
old_T:		ds.w	1
ring_T:		ds.w	2
spr_code:	ds.w	1
spr_col:	ds.w	1
spr_ytop:	ds.w	1
spr_n:		ds.w	1
spr_y:		ds.w	1
spr_xs:		ds.w	1
spr_pcode:	ds.w	1
rect_cnt:	ds.w	2
ste_pal:	ds.w	16
shown_pal:	ds.w	16
black_pal:	ds.w	16
tile_pend:	ds.w	64
chr_dirty:	ds.w	64
chr_drawn:	ds.w	64
chunk_now:	ds.w	32
merge_dirty:	ds.w	32
chr_list_n:	ds.w	1
chr_d:	ds.w	1
rescan:	ds.b	1
fg_dirty:	ds.b	1
bg_dirty:	ds.b	1
	even
cell_occ:	ds.l	32
t_moved:	ds.b	1
full_redraw:	ds.b	1
pal_pending:	ds.b	1
	even
cmap:		ds.b	256
bk_idx:		ds.b	16
bg_shadow:	ds.b	1024
fg_shadow:	ds.b	2048
rects:		ds.b	2*MAX_RECTS*16
chr_list:	ds.b	448*8
chunk_pool:	ds.b	448*96
tile_ptr:	ds.l	65536
spr_ptr:	ds.l	8192
chr_ptr:	ds.l	32768
tile_pool:	ds.b	TILE_POOL_SIZE
spr_pool:	ds.b	SPR_POOL_SIZE
chr_pool:	ds.b	CHR_POOL_SIZE
ring_area:	ds.b	3*RING_SIZE+256
	section text,code
