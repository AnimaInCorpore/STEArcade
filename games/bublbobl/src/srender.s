; ------------------------------------------------------------------------------
; The sprite renderer (sr_*): the frames whose object list is columns and sprites in layers.
;
; In the play (and most of the attract mode) the list is: 16 columns (32 rows of 2 tiles, the level's
; background), the sprites (shapes 0-3: one 16 x 16 block of 2 x 2 tiles each), 16 columns again (the level's
; walls and platforms, drawn after the sprites: in front of them), and sometimes more sprites after those.
; So the picture is a static one (both column layers) with the sprites between the layers:
;
;   sr_img    the static picture, in the screen's layout (both column layers; the background 0)
;   sr_msk    the front layer's opacity: a byte per 8 pixels of every game line (bit set = opaque)
;   sr_any    per block: the front layer has an opaque pixel there
;
; The screen is handled in blocks of 16 pixels (a plane word group) x 4 lines, 16 x 56 of them (bitmaps of 56
; words, bit g = group g).  Per frame:
;   * the static picture: the cells whose tile entries (rf_vdiff's tile_dirty, through sr_vinv) or colours
;     (rf_palette's pen_chg) changed are drawn again into sr_img / sr_msk; their blocks changed,
;   * the sprites against the last frame's: the old and the new blocks of each one that changed (its object entry,
;     its four tile entries, the colour generation of their banks) changed,
;   * closure: a sprite with a block in the set is drawn whole, its blocks join the set, until nothing changes,
;   * the screen to draw (it holds the frame before the last one): the blocks of the last frame's set that this
;     one leaves alone are copied from the screen shown (it holds the last frame complete), the set's blocks are
;     restored from sr_img, its sprites are drawn in list order (the first layer's, then the front columns again
;     where they are opaque, from sr_img through sr_msk, then the second layer's).
; Exact: the reference's bitmap through the colour table (tools/render_test.py, tools/render_bench.py).
;
; A sprite is baked unshifted and its rows grouped by opaque mask (stefastbobs2).
; sr_cache is keyed by four tile keys/generations; the Blitter supplies x & 15.
; Sprites draw whole into the virtual screen. Only their damage footprint is bounded to the game area.
;
; Anything else (the columns not on the 8 x 8 grid, as while a level scrolls in, or the layers in another order)
; is drawn by the general renderer (render.s); switching between the two draws everything once.
; ------------------------------------------------------------------------------

SR_ROWS = 56				; block rows (4 lines each) of the game area (lines 16-239)
SR_N = 192				; objects
SREC = 64				; a record per object (sr_recs), as the last frame drawn by this renderer saw it:
R_ORAM = 0				;   the object entry (y, shape, x, flags)
R_T01 = 4				;   a sprite's tile entries: the top row (left, right)
R_T23 = 8				;   ... the bottom row
					;   (12: free)
R_X = 16				;   x (signed)
R_Y = 18				;   the top line (game coordinates)
R_R0 = 20				;   the first and the last block row
R_R1 = 22
R_CM = 24				;   the block columns
R_KIND = 26				;   0 nothing, 1 a sprite, 2 a column
R_VIS = 27				;   a sprite with something on the screen
R_LA = 28				;   the bounded damage footprint: first line (0-15), count
R_LN = 29
R_GS = 30				;   damage groups: 1 left, 2 right, 3 both (drawing is whole)
R_G0 = 31				;   the left group (-1..15)
R_TOFF = 32				;   a sprite: its top left tile entry; a column: its x
R_SHIFT = 34				;   a sprite: x & 15; a column: its layer (0 behind the sprites, 2 in front)
R_KEYS = 36				;   the four tiles' keys (with the generations): the baked image's
R_ENT = 52				;   the sprite cache entry it was found in (checked before use)
R_IN = 56				;   drawn this frame (sr_closure)
R_IDX = 57				;   the object's number
R_NB = 58				;   a sprite's tiles are not all blank
SC_N = 512				; sprite cache entries
SC_ENTRY = 212				;   four tile keys, reserved.l, 16 mask/offset pairs + plane rows
SC_DATA = 20
CC_N = 1024				; composite cache entries (sr_cell)
CC_ENTRY = 64				;   the four tile keys (-1: none), the stamp.w, reserved.w, 8 rows of 4 plane bytes,
CC_DATA = 20				;   8 front opacity bytes
sr_ccache = comp_B			; (the general renderer's composites: unused while this renderer draws; it builds
					; them all again when it takes over, sr_frame: masks_valid)
SR_CMAX = 64				; columns at most

; ---- block bitmaps (56 words)

sb_fill	macro				; \1 = \2
	lea	\1,a0
	move.l	#\2,d1
	moveq	#SR_ROWS/2-1,d0
.l\@:	move.l	d1,(a0)+
	dbf	d0,.l\@
	endm
sb_copy	macro				; \2 = \1
	lea	\1,a0
	lea	\2,a1
	moveq	#SR_ROWS/2-1,d0
.l\@:	move.l	(a0)+,(a1)+
	dbf	d0,.l\@
	endm

; the blocks of the record a2 into the bitmap \1 (uses d0-d2, a0)
mark_rec	macro
	lea	\1,a0
	move.w	R_R0(a2),d0
	move.w	R_R1(a2),d1
	sub.w	d0,d1
	add.w	d0,d0
	add.w	d0,a0
	move.w	R_CM(a2),d2
.m\@:	or.w	d2,(a0)+
	dbf	d1,.m\@
	endm

; ------------------------------------------------------------------------------
; sr_frame: d0 = 0 if the frame was drawn, else the general renderer draws it.  After rf_vdiff / rf_palette.
; ------------------------------------------------------------------------------

sr_frame:
	tst.b	sr_inited
	bne.s	.inited
	st	sr_inited
	sf	pal_wrapped
	bsr	sr_flush		; (no baked image yet)
.inited:
	tst.b	pal_wrapped		; (the palette epochs started again: no stamp can be trusted)
	beq.s	.epochs
	sf	pal_wrapped
	bsr	sr_flush
	bsr	sr_ccflush
.epochs:
	sb_fill	sr_chg,0
	bsr	sr_pal_gens		; colours that changed: the generations of their banks
	bsr	sr_scan			; the objects: the sprites that changed (sr_chg), the visible ones (sr_vlist)
	tst.w	d0
	bne	.not_mine
	tst.b	sr_schg			; the columns changed: their maps again
	beq.s	.st
	clr.b	sr_mstate
.st:	tst.b	sr_mstate
	bne.s	.known
	bsr	sr_columns
	bsr	sr_maps
	move.b	#1,sr_mstate
	st	sr_rebuild
	tst.w	d0
	beq.s	.known
	move.b	#2,sr_mstate		; (three tiles of a layer on one cell: not here, until the columns change)
.known:
	cmp.b	#2,sr_mstate
	beq	.cannot
	tst.b	sr_active
	bne.s	.active
	st	sr_full			; (the general renderer drew the frames before: everything)
	st	sr_rebuild
	st	sr_active
	bsr	sr_ccflush		; (its memory held the general renderer's composites)
	sf	masks_valid		; (... and their masks: built again when it draws)
.active:
	ifd SIM
	addq.l	#1,sim_sr_frames
	endc
	; the static picture
	tst.b	sr_rebuild
	beq.s	.changes
	sf	sr_rebuild
	ifd SIM
	addq.l	#1,sim_sr_rebuild
	endc
	lea	sr_sdirty,a0
	moveq	#28-1,d0
.ac:	move.l	#-1,(a0)+
	dbf	d0,.ac
	bra.s	.cells
.changes:
	lea	sr_sdirty,a0
	moveq	#28-1,d0
.sc:	clr.l	(a0)+
	dbf	d0,.sc
	bsr	sr_vram_cells		; tile entries that changed
	bsr	sr_pal_cells		; colours that changed
.cells:
	bsr	sr_cells		; sr_img, sr_msk, sr_any; their blocks into sr_chg
	tst.b	sr_full
	beq.s	.closure
	sb_fill	sr_chg,-1
.closure:
	bsr sr_guard_marks
	bsr	sr_closure		; sr_chg -> sr_draw (the set), R_IN (the sprites drawn)
	tst.b	sr_full
	bne.s	.no_copy
	bsr	sr_copy			; the last frame's set, outside this one's: from the screen shown
.no_copy:
	bsr sr_guard_restore
	bsr	sr_restore
	bsr	sr_sprites
	lea	sr_stale,a1		; the other screens lack this frame's set, this one nothing
	moveq	#0,d2
.st_buf:
	lea	sr_draw,a0
	moveq	#SR_ROWS/2-1,d0
	cmp.w	rf_buf,d2
	beq.s	.st_clr
.st_or:	move.l	(a0)+,d1
	or.l	d1,(a1)+
	dbf	d0,.st_or
	bra.s	.st_next
.st_clr:
	clr.l	(a1)+
	dbf	d0,.st_clr
.st_next:
	addq.w	#1,d2
	cmp.w	#3,d2
	blo.s	.st_buf
	sf	sr_full
	lea	bank_chg_b,a0		; (the colour changes are used up)
	moveq	#16/4-1,d1
.clr:	clr.l	(a0)+
	dbf	d1,.clr
	moveq	#0,d0
	rts
.cannot:
	ifd SIM
	addq.l	#1,sim_sr_cannot
	endc
.not_mine:
	sf	sr_active		; (the general renderer draws: the static picture is stale from now on)
	moveq	#1,d0
	rts

; ------------------------------------------------------------------------------
 ; Sprites may draw into vertical guard rows. Before drawing
 ; the next picture into a page, restore that page's old guard background.
 ; Boundary sprites join the damage set even if unchanged, so they draw whole
 ; vertically again after that restore. sr_draw1 clips at the side picture edges.
sr_guard_marks:
	sf sr_has_guard			; (bits: 0 left, 1 right, 2 top, 3 bottom guard)
	lea sr_vlist,a3
.loop:
	cmp.l sr_vend,a3
	bhs.s .done
	move.l (a3)+,a2
	moveq #0,d1			; (left and right: sr_draw1 clips at the picture's edges)
	cmp.w #16,R_Y(a2)
	bhs.s .y0
	addq.b #4,d1
.y0:	cmp.w #224,R_Y(a2)
	bls.s .y1
	addq.b #8,d1
.y1:	tst.b d1
	beq.s .loop
	or.b d1,sr_has_guard
	mark_rec sr_chg
	bra.s .loop
.done:
	rts

; the guards this page was drawn into last time (sr_guard_pages): their background again
sr_guard_restore:
	move.w rf_buf,d0
	lea sr_guard_pages,a0
	move.b (a0,d0.w),d1
	move.b sr_has_guard,(a0,d0.w)
	tst.b d1
	beq .done
	move.w #2,$ffff8a2e.w
	move.w #$ffff,$ffff8a28.w
	move.w #$ffff,$ffff8a2a.w
	move.w #$ffff,$ffff8a2c.w
	move.w #0,$ffff8a3a.w     ; zero fill: no source bus reads
	clr.b $ffff8a3d.w
	move.l rf_screen,a0
	btst #0,d1
	beq.s .r
	lea (YPAD+16)*STRIDE+GAME_BYTES-8(a0),a1
	move.l a1,$ffff8a32.w
	bsr sr_guard_column
.r:	btst #1,d1
	beq.s .t
	lea (YPAD+16)*STRIDE+GAME_BYTES+128(a0),a1
	move.l a1,$ffff8a32.w
	bsr sr_guard_column
.t:	btst #2,d1
	beq.s .b
	lea YPAD*STRIDE+GAME_BYTES-8(a0),a1
	move.l a1,$ffff8a32.w
	bsr sr_guard_band
.b:	btst #3,d1
	beq.s .done
	move.l a0,a1
	add.l #(YPAD+240)*STRIDE+GAME_BYTES-8,a1
	move.l a1,$ffff8a32.w
	bsr sr_guard_band
.done:
	rts
sr_guard_column:
	move.w #4,$ffff8a36.w
	move.w #STRIDE-8+2,$ffff8a30.w
	moveq #224/8-1,d0
.loop:
	move.w #8,$ffff8a38.w
	move.b #$c0,$ffff8a3c.w
	dbf d0,.loop
	rts
sr_guard_band:
	; 18 groups would need wide strips; clear one row in three 24-word
	; passes, then advance to the next row. No HOG pass exceeds 128 cycles.
	move.w #24,$ffff8a36.w
	move.w #2,$ffff8a30.w
	moveq #16-1,d0
.row:
	rept 3
	move.w #1,$ffff8a38.w
	move.b #$c0,$ffff8a3c.w
	endr
	lea STRIDE(a1),a1
	move.l a1,$ffff8a32.w
	dbf d0,.row
	rts

; sr_scan: the object list against the records.  A sprite whose entry, tile entries or colour generations changed
; puts its old and its new blocks into sr_chg; the visible sprites go to sr_vlist (record pointers, in list
; order; sr_vend), sr_c2 = the first object of the front columns (192: none), sr_schg = a column changed (or
; came or went).  d0 = 0 if the list has the layers (columns, sprites, columns, sprites, each part possibly
; empty) and the columns are on the 8 x 8 grid.
; ------------------------------------------------------------------------------

sr_scan:
	move.b	sr_active,sr_fast
	lea	S_ORAM,a4
	lea	sr_recs,a2
	lea	sr_vlist,a3
	lea	snap_vram,a6
	sf	sr_schg
	move.w	#SR_N,sr_c2
	move.w	#SR_N,sr_s1first
	; the objects after the last one in use (now or in the records) are skipped: find the last one now
	lea	S_ORAM+SR_N*4,a0
	move.w	sr_hi,d1
	move.w	#SR_N-1,d0
.hi:	cmp.w	d1,d0
	ble.s	.hi_rec			; (not below the last one in the records)
	tst.l	-(a0)
	dbne	d0,.hi
	bne.s	.hi_ok
	moveq	#-1,d0			; (none)
.hi_rec:
	cmp.w	d1,d0
	bge.s	.hi_ok
	move.w	d1,d0
.hi_ok:
	addq.w	#1,d0
	move.w	d0,sr_end		; objects 0 .. sr_end - 1
	move.w	d0,a5			; (the end, for the loop)
	move.w	#-1,sr_hi
	moveq	#0,d6			; the phase: 0 columns, 1 sprites, 2 columns, 3 sprites
	moveq	#0,d7			; the chained x
	moveq	#0,d5			; the object
.obj:
	move.l	(a4)+,d0
	bne.s	.obj_nz
	tst.l	R_ORAM(a2)
	bne	.changed		; (it went)
	lea	SREC(a2),a2		; nothing, as before (the usual case: a short loop)
	addq.w	#1,d5
	cmp.w	a5,d5
	blo.s	.obj
	bra	.end
.obj_nz:
	cmp.l	R_ORAM(a2),d0
	bne	.changed
	move.w	d5,sr_hi
	move.b	R_KIND(a2),d1
	cmp.b	#1,d1
	bne	.col_same
	; a sprite with the same entry
	btst	#0,d6
	bne.s	.in_s
	bsr	sr_phase_s
.in_s:
	move.w	R_X(a2),d7
	add.w	#16,d7
	bsr	sr_tiles_same
	bne.s	.tiles
.same:
	tst.b	R_VIS(a2)
	beq	.next
	clr.b	R_IN(a2)
	move.l	a2,(a3)+
	bra	.next
.tiles:					; same place, other tiles or colours
	tst.b	R_VIS(a2)
	beq.s	.t_new
	mark_rec	sr_chg
.t_new:
	bsr	sr_sprite_tiles
	bra	.s_vis

.changed:
	tst.b	R_VIS(a2)		; the old blocks
	beq.s	.no_old
	move.l	d0,-(sp)		; (mark_rec takes d0-d2)
	mark_rec	sr_chg
	move.l	(sp)+,d0
.no_old:
	cmp.b	#1,R_KIND(a2)		; a sprite that only moved (same shape and flags): its tiles' keys stand
	bne	.not_moved
	move.l	R_ORAM(a2),d1
	eor.l	d0,d1
	and.l	#$00FF00FF,d1
	bne	.not_moved
	move.l	d0,R_ORAM(a2)
	move.w	d5,sr_hi
	moveq	#0,d3
	move.w	d0,d3
	lsr.w	#8,d3			; x
	btst	#6,d0
	beq.s	.m_x
	sub.w	#256,d3
.m_x:
	btst	#0,d6
	bne.s	.m_in
	bsr	sr_phase_s
.m_in:
	move.w	d3,R_X(a2)
	move.w	d3,d7
	add.w	#16,d7
	moveq	#15,d1
	and.w	d3,d1
	move.w	d1,R_SHIFT(a2)
	bsr	sr_sprite_place
	bsr	sr_tiles_same
	beq.s	.m_same
	bsr	sr_sprite_tiles
	bra	.s_vis
.m_same:
	tst.b	R_GS(a2)
	beq	.s_vis
	move.b	R_NB(a2),R_VIS(a2)
	bra	.s_vis
.not_moved:
	cmp.b	#2,R_KIND(a2)
	bne.s	.was_not_col
	st	sr_schg			; (a column changed or went)
.was_not_col:
	move.l	d0,R_ORAM(a2)
	clr.w	R_KIND(a2)		; (and R_VIS)
	tst.l	d0
	beq	.next
	move.w	d5,sr_hi
	move.l	d0,d1
	swap	d1			; the shape / page number
	moveq	#0,d3
	move.w	d0,d3
	lsr.w	#8,d3			; x
	btst	#6,d0			; (the flags' bit 6: x - 256)
	beq.s	.xok
	sub.w	#256,d3
.xok:
	cmp.b	#$80,d1
	bhs	.col_new
	; a sprite (shapes 0-3)
	move.b	#1,R_KIND(a2)
	bsr	sr_phase_s
	move.w	d3,R_X(a2)
	move.w	d3,d7
	add.w	#16,d7
	moveq	#15,d0
	and.w	d3,d0
	move.w	d0,R_SHIFT(a2)
	and.w	#$FF,d1			; the tile entries: (shape & $1F) * $80 + 12 + (prom & 3) * 16
	move.w	d1,d4
	and.w	#$1F,d4
	lsl.w	#7,d4
	move.w	d1,d0
	lsr.w	#1,d0
	and.w	#$70,d0			; (shape >> 5) * 16
	lea	bb_prom+15,a0
	move.b	(a0,d0.w),d0
	and.w	#3,d0
	lsl.w	#4,d0
	add.w	d0,d4
	add.w	#12,d4
	move.w	d4,R_TOFF(a2)
	bsr	sr_sprite_place
	bsr	sr_sprite_tiles
.s_vis:
	tst.b	R_VIS(a2)
	beq	.next
	mark_rec	sr_chg
	clr.b	R_IN(a2)
	move.l	a2,(a3)+
	bra.s	.next

.col_new:
	st	sr_schg
	move.b	#2,R_KIND(a2)
	move.w	d3,R_X(a2)
.col_same:
	tst.b	R_KIND(a2)		; (an entry -1 met a record never filled: as a new one)
	beq	.changed
	move.b	R_ORAM+1(a2),d0		; shapes 4/5 start the column at their x in every row, 6/7 continue the chain
	and.b	#$C0,d0
	cmp.b	#$C0,d0
	beq.s	.chain
	move.w	R_X(a2),d7
.chain:
	cmp.w	R_TOFF(a2),d7
	beq.s	.x_same
	move.w	d7,R_TOFF(a2)
	st	sr_schg
.x_same:
	btst	#0,d6
	beq.s	.c_layer
	cmp.w	#1,d6
	bne.s	.bad			; (columns after the second sprite layer)
	moveq	#2,d6
	move.w	d5,sr_c2
.c_layer:
	cmp.w	R_SHIFT(a2),d6		; (a column's layer: 0 behind the sprites, 2 in front; sprites coming or going
	beq.s	.l_same			; between the column sets move them)
	move.w	d6,R_SHIFT(a2)
	st	sr_schg
.l_same:
	move.w	d7,d0			; on the 8 x 8 grid: x and y multiples of 8
	and.w	#7,d0
	bne.s	.bad
	move.b	R_ORAM(a2),d0
	and.b	#7,d0
	bne.s	.bad
	add.w	#16,d7
.next:
	lea	SREC(a2),a2
	addq.w	#1,d5
	cmp.w	a5,d5
	blo	.obj
.end:
	move.l	a3,sr_vend
	ifd SIM
	move.l	a3,d0
	sub.l	#sr_vlist,d0
	lsr.l	#2,d0
	add.l	d0,sim_sr_vis
	endc
	moveq	#0,d0
	rts
.bad:
	moveq	#1,d0
	rts

; a sprite in the list: the phase (columns -> sprites)
sr_phase_s:
	btst	#0,d6
	bne.s	.in
	tst.w	d6
	bne.s	.second
	move.w	d5,sr_s1first
.second:
	addq.w	#1,d6
.in:	rts

; the record a2's place: R_Y, R_LA / R_LN, R_R0 / R_R1, R_G0 / R_GS / R_CM; R_VIS cleared if none on the screen
; (else left for sr_sprite_tiles).  Clobbers d0-d4.
sr_sprite_place:
	sf	R_VIS(a2)
	sf	R_GS(a2)
	moveq	#0,d0			; the top line: (-y + 240) & 255
	move.b	R_ORAM(a2),d0
	neg.w	d0
	add.w	#240,d0
	and.w	#$FF,d0
	move.w	d0,R_Y(a2)
	cmp.w	#240,d0
	bhs	.off			; (off the screen: lines 240-255, and the wrap to 0-15)
	moveq	#0,d1			; the first line on the screen
	cmp.w	#16,d0
	bhs.s	.top_ok
	moveq	#16,d1
	sub.w	d0,d1
.top_ok:
	moveq	#16,d2			; the end
	move.w	#240,d4
	sub.w	d0,d4
	cmp.w	d2,d4
	bhs.s	.bot_ok
	move.w	d4,d2
.bot_ok:
	sub.w	d1,d2			; lines
	ble.s	.off
	move.b	d1,R_LA(a2)
	move.b	d2,R_LN(a2)
	add.w	d0,d1
	sub.w	#16,d1			; the first line in the game area
	move.w	d1,d4
	lsr.w	#2,d4
	move.w	d4,R_R0(a2)
	add.w	d2,d1
	subq.w	#1,d1
	lsr.w	#2,d1
	move.w	d1,R_R1(a2)
	move.w	R_X(a2),d0		; the groups
	move.w	d0,d1
	asr.w	#4,d1			; the left group
	move.b	d1,R_G0(a2)
	moveq	#0,d2			; the groups drawn
	moveq	#0,d4			; their bits
	cmp.w	#15,d1
	bhi.s	.no_left		; (unsigned: -1 and below are above 15)
	moveq	#1,d2
	bset	d1,d4
.no_left:
	and.w	#15,d0
	beq.s	.groups
	addq.w	#1,d1
	cmp.w	#15,d1
	bhi.s	.groups
	or.w	#2,d2
	bset	d1,d4
.groups:
	move.b	d2,R_GS(a2)
	move.w	d4,R_CM(a2)
.off:
	rts

; the record a2's tiles: R_T01, R_T23, R_KEYS; R_VIS set if it has a place on the screen and a tile that is
; not blank.  a6 = snap_vram.  Clobbers d0-d4, a0, a1.
sr_sprite_tiles:
	move.w	R_TOFF(a2),d4
	move.w	(a6,d4.w),d0
	swap	d0
	move.w	$40(a6,d4.w),d0
	move.l	d0,R_T01(a2)
	move.w	2(a6,d4.w),d0
	swap	d0
	move.w	$42(a6,d4.w),d0
	move.l	d0,R_T23(a2)
	moveq	#0,d1
	move.b	R_ORAM+3(a2),d1
	and.w	#15,d1
	moveq	#10,d0
	lsl.w	d0,d1			; the tile number's high bits
	lea	R_KEYS(a2),a1
	move.l	R_T01(a2),d0
	swap	d0
	bsr	sr_ckey
	swap	d0
	bsr	sr_ckey
	move.l	R_T23(a2),d0
	swap	d0
	bsr	sr_ckey
	swap	d0
	bsr	sr_ckey
	sf	R_VIS(a2)
	sf	R_NB(a2)
	move.l	R_T01(a2),d0
	bsr	sr_blank2
	bne.s	.nb
	move.l	R_T23(a2),d0
	bsr	sr_blank2
	beq.s	.done
.nb:	st	R_NB(a2)
	tst.b	R_GS(a2)
	beq.s	.done			; (no place on the screen)
	st	R_VIS(a2)
.done:	rts

; the record a2's tile entries and colour generations as they are now?  Z set if the same.  Clobbers d0-d4, a0.
sr_tiles_same:
	tst.b	sr_fast			; (the last frame was drawn here: rf_vdiff's page flags cover everything since)
	beq.s	.slow
	moveq	#$1F,d0
	and.b	R_ORAM+1(a2),d0		; the page of its tile entries
	lea	page_dirty,a0
	tst.b	(a0,d0.w)
	beq.s	.gen
.slow:
	move.w	R_TOFF(a2),d4
	move.w	(a6,d4.w),d0
	swap	d0
	move.w	$40(a6,d4.w),d0
	cmp.l	R_T01(a2),d0
	bne.s	.diff
	move.w	2(a6,d4.w),d0
	swap	d0
	move.w	$42(a6,d4.w),d0
	cmp.l	R_T23(a2),d0
	bne.s	.diff
.gen:
	tst.b	sr_genchg
	beq.s	.same
	bsr	sr_penhit		; (a pen of its tiles changed slot)
	bne.s	.diff
.same:
	moveq	#0,d0
	rts
.diff:
	moveq	#1,d0
	rts

; Z clear if a pen used by one of the record a2's four tiles changed slot this frame (rf_palette: pen_chg).
; Clobbers d0-d4, a0.
sr_penhit:
	moveq	#0,d3
	move.b	R_ORAM+3(a2),d3
	and.w	#15,d3
	moveq	#10,d0
	lsl.w	d0,d3			; the tile number's high bits
	move.l	R_T01(a2),d0
	bsr.s	.two
	bne.s	.done
	move.l	R_T23(a2),d0
.two:
	moveq	#2-1,d4
.t:	swap	d0
	moveq	#0,d1
	move.b	d0,d1			; the entry's second byte
	move.w	d1,d2
	lsr.w	#2,d2
	and.w	#15,d2			; the bank
	add.w	d2,d2
	lea	pen_chg,a0
	move.w	(a0,d2.w),d2
	beq.s	.n
	and.w	#3,d1
	lsl.w	#8,d1
	move.w	d0,-(sp)
	move.b	(sp)+,d1		; (the entry's first byte: the tile number's low 8 bits)
	or.w	d3,d1
	add.w	d1,d1
	lea	bb_penmask,a0
	and.w	(a0,d1.w),d2
	bne.s	.done
.n:	dbf	d4,.t
	moveq	#0,d2			; Z
.done:	rts

; a0 = a sprite or composite cache entry: Z set if no pen its four tiles use (keys -1: none) changed slot since it was
; baked (its stamp is then brought up to date).  Clobbers d0-d4, a1.
sr_valid:
	move.w	16(a0),d0		; the stamp
	cmp.w	pal_epoch,d0
	beq.s	.ok
	move.l	a0,a1
	moveq	#4-1,d4
.key:	move.l	(a1)+,d1
	bmi.s	.kskip			; (a cell's slot without a tile)
	move.l	d1,d2
	moveq	#14,d3
	lsr.l	d3,d2
	and.w	#15,d2			; the bank
	add.w	d2,d2
	move.l	a1,-(sp)
	lea	bank_epoch,a1
	cmp.w	(a1,d2.w),d0
	bhs.s	.kn
	and.w	#$3FFF,d1
	add.w	d1,d1
	lea	bb_penmask,a1
	move.w	(a1,d1.w),d1		; its pens
	lsl.w	#4,d2
	lea	pen_epoch,a1
	add.w	d2,a1
.pen:	lsr.w	#1,d1
	bcc.s	.pn
	cmp.w	(a1),d0
	blo.s	.stale
.pn:	addq.l	#2,a1
	tst.w	d1
	bne.s	.pen
.kn:	move.l	(sp)+,a1
.kskip:	dbf	d4,.key
	move.w	pal_epoch,16(a0)
.ok:	cmp.w	d0,d0			; Z
	rts
.stale:	move.l	(sp)+,a1
	moveq	#1,d0			; not Z
	rts

; d0 = two tile entries, d1 = the high bits of the tile number (<< 10): Z clear if one of them is not blank.
; Clobbers d2-d4, a0.
sr_blank2:
	lea	bb_blank,a0
	moveq	#2-1,d3
.t:	swap	d0
	move.w	d0,d2
	lsr.w	#8,d2			; the entry's first byte: the tile number's low 8 bits
	move.w	d0,d4
	and.w	#3,d4
	lsl.w	#8,d4
	or.w	d4,d2
	or.w	d1,d2
	move.w	d2,d4
	lsr.w	#3,d4
	btst	d2,(a0,d4.w)		; (bit number mod 8)
	beq.s	.not_blank
	dbf	d3,.t
	moveq	#0,d2			; Z
	rts
.not_blank:
	moveq	#1,d2			; not Z
	rts

; d0.w = a tile entry, d1.w = the high bits of the tile number: its key (as draw_tile's) at (a1)+.
; Keeps d0, d1.  Clobbers d2-d4.
sr_ckey:
	moveq	#0,d2
	move.b	d0,d2			; the entry's second byte: flips (7-6), bank (5-2), tile number bits 9-8
	move.w	d2,d3
	lsr.b	#2,d3			; flips << 4 | bank
	and.w	#3,d2
	lsl.w	#8,d2
	move.w	d0,d4
	lsr.w	#8,d4
	or.w	d4,d2
	or.w	d1,d2			; the tile number
	swap	d3				; flips << 4 | bank
	clr.w	d3
	lsr.l	#2,d3			; << 14
	or.l	d3,d2
	move.l	d2,(a1)+
	rts

; the columns' list for sr_maps (sr_cnew: index.w, entry.l, x.w, layer.w (0 back, 2 front) per column; sr_ccount)
sr_columns:
	lea	sr_recs,a2
	lea	sr_cnew,a3
	moveq	#0,d5
	moveq	#0,d6			; columns
.o:	cmp.b	#2,R_KIND(a2)
	bne.s	.n
	cmp.w	#SR_CMAX,d6
	bhs.s	.n			; (more cannot be: sr_maps sees the first ones only)
	addq.w	#1,d6
	move.w	d5,(a3)+
	move.l	R_ORAM(a2),(a3)+
	move.w	R_TOFF(a2),(a3)+
	move.w	R_SHIFT(a2),(a3)+	; (the layer)
.n:	lea	SREC(a2),a2
	addq.w	#1,d5
	cmp.w	#SR_N,d5
	blo.s	.o
	move.w	d6,sr_ccount
	rts

; sr_genchg: the colour mapping of a bank changed (rf_palette: bank_chg_b; its pens: pen_chg)
sr_pal_gens:
	sf	sr_genchg
	lea	bank_chg_b,a0
	moveq	#16-1,d1
.gen:	tst.b	(a0)+
	beq.s	.gn
	st	sr_genchg
.gn:	dbf	d1,.gen
	rts

; ------------------------------------------------------------------------------
; sr_maps: the tiles of the two column layers per cell, two slots each in list order (sr_map1 / sr_map2: the high
; bits of the tile number << 16 | the offset of its tile entry, -1 = none) and the cell of every tile entry (sr_vinv: cell + 1, 0 = none),
; from sr_cnew.  d0 = 0, or 1 if three tiles of a layer meet on a cell or an entry is on two cells.
; ------------------------------------------------------------------------------

sr_maps:
	ifd SIM
	addq.l	#1,sim_sr_maps
	endc
	lea	sr_map1,a0		; (sr_map2 follows)
	move.w	#896*4-1,d0
.m:	move.l	#-1,(a0)+
	dbf	d0,.m
	lea	sr_vinv,a0
	move.w	#3712/2-1,d0
.v:	clr.l	(a0)+
	dbf	d0,.v
	lea	sr_cnew,a3
	lea	sr_vinv,a6
	move.w	sr_ccount,d7
	subq.w	#1,d7
	bmi	.ok
.col:
	move.l	2(a3),d6		; the entry
	lea	sr_map1,a4
	tst.w	8(a3)
	beq.s	.l1
	lea	sr_map2,a4
.l1:
	move.l	d6,d1
	swap	d1
	and.w	#$FF,d1			; the shape / page number
	move.w	d1,d2
	and.w	#$1F,d2
	lsl.w	#7,d2			; the page
	move.w	d1,d3
	and.w	#$A0,d3
	cmp.w	#$A0,d3
	bne.s	.n1
	or.w	#$1000,d2
.n1:
	move.w	d1,d0
	and.w	#$E0,d0
	lsr.w	#1,d0
	lea	bb_prom,a5
	add.w	d0,a5			; the shape's 16 PROM entries
	moveq	#0,d3
	move.b	d6,d3
	and.w	#15,d3
	swap	d3			; the high bits of the tile number << 16
	rol.l	#8,d6
	neg.b	d6			; sy = -y
	and.w	#$FF,d6
	moveq	#0,d5			; yc
.row:
	move.w	d5,d0
	lsr.w	#1,d0
	move.b	(a5,d0.w),d0
	btst	#3,d0
	bne.s	.skip
	and.w	#3,d0
	lsl.w	#4,d0
	add.w	d2,d0
	move.w	d5,d1
	and.w	#7,d1
	add.w	d1,d1
	add.w	d1,d0			; the left tile's entry
	move.w	d5,d1
	lsl.w	#3,d1
	add.w	d6,d1
	and.w	#$FF,d1			; y
	sub.w	#16,d1
	cmp.w	#224,d1
	bhs.s	.skip			; (not on the screen)
	and.w	#$F8,d1
	lsl.w	#2,d1			; the cell row * 32
	move.w	6(a3),d4		; the column's x
	bsr.s	sr_maptile
	bne.s	.conflict
	addq.w	#8,d4
	add.w	#$40,d0
	bsr.s	sr_maptile
	bne.s	.conflict
.skip:
	addq.w	#1,d5
	cmp.w	#32,d5
	blo.s	.row
	lea	10(a3),a3
	dbf	d7,.col
.ok:
	moveq	#0,d0
	rts
.conflict:
	moveq	#1,d0
	rts

; d4.w = x, d1.w = the cell row * 32, d0.w = the tile entry, d3.l = the high bits << 16; a4 = the map, a6 = sr_vinv.
; Z clear on a conflict.  Keeps everything but a0.
sr_maptile:
	cmp.w	#255,d4
	bhi.s	.none			; (not on the screen: below 0 or above 255)
	movem.l	d4-d5,-(sp)
	lsr.w	#3,d4
	add.w	d1,d4			; the cell
	move.w	d4,d5
	lsl.w	#3,d5			; (two slots per cell: the tiles in list order)
	lea	(a4,d5.w),a0
	cmp.l	#-1,(a0)
	beq.s	.free
	addq.l	#4,a0
	cmp.l	#-1,(a0)
	bne.s	.bad
.free:
	move.l	d3,d5
	move.w	d0,d5
	move.l	d5,(a0)
	tst.w	(a6,d0.w)		; (the entry offset is even: the word of entry offset / 2)
	bne.s	.bad
	addq.w	#1,d4
	move.w	d4,(a6,d0.w)
	cmp.w	d0,d0			; Z (movem keeps the flags)
	movem.l	(sp)+,d4-d5
	rts
.bad:
	moveq	#1,d4			; not Z
	movem.l	(sp)+,d4-d5
	rts
.none:
	cmp.w	d0,d0
	rts

; ------------------------------------------------------------------------------
; The cells of the static picture to draw again (sr_sdirty, 28 longs, bit c of long r)
; ------------------------------------------------------------------------------

; the tile entries that changed (rf_vdiff's tile_dirty: bit (w & 7) of byte w >> 3 for entry w) -> their cells
; the tile entries that changed (rf_vdiff's tile_dirty: bit (w & 7) of byte w >> 3 for entry w) -> their cells
sr_vram_cells:
	lea	page_dirty,a3		; (only the pages with a change: 64 entries, 8 bytes of tile_dirty each)
	lea	sr_vinv,a1
	lea	sr_sdirty,a2
	moveq	#0,d5			; the page
.page:
	tst.b	(a3,d5.w)
	beq.s	.np
	lea	tile_dirty,a0
	move.w	d5,d0
	lsl.w	#3,d0
	add.w	d0,a0
	move.w	d5,d6
	lsl.w	#6,d6			; the entry of the page's first byte's bit 0
	moveq	#8-1,d7
.byte:	move.b	(a0)+,d0
	beq.s	.nb
	moveq	#0,d1
.bit:	btst	d1,d0
	beq.s	.n
	move.w	d6,d2
	add.w	d1,d2
	add.w	d2,d2
	move.w	(a1,d2.w),d2		; cell + 1
	beq.s	.n
	subq.w	#1,d2
	bsr	sr_setcell
.n:	addq.w	#1,d1
	cmp.w	#8,d1
	blo.s	.bit
.nb:	addq.w	#8,d6
	dbf	d7,.byte
.np:	addq.w	#1,d5
	cmp.w	#58,d5
	blo.s	.page
	rts

; d2.w = a cell (row * 32 + column): its bit in sr_sdirty (a2).  Clobbers d2-d4.
sr_setcell:
	move.w	d2,d3
	lsr.w	#5,d3
	lsl.w	#2,d3			; the row's long
	move.w	d2,d4
	and.w	#31,d4
	move.l	(a2,d3.w),d2
	bset	d4,d2
	move.l	d2,(a2,d3.w)
	rts

; the colours that changed (rf_palette: bank_chg_b, pen_chg): the cells of the static tiles with a pen whose slot
; changed are drawn again.  Only the cells that had a tile of a changed bank when they were composed (sr_cbm) are
; looked at (a cell whose tile entries changed since is drawn again anyway: sr_vram_cells).
sr_pal_cells:
	lea	bank_chg_b,a0		; the changed banks' bits
	moveq	#0,d7
	moveq	#0,d1
.any:	tst.b	(a0)+
	beq.s	.an
	bset	d1,d7
.an:	addq.w	#1,d1
	cmp.w	#16,d1
	blo.s	.any
	tst.w	d7
	beq.s	.none
	lea	sr_cbm,a3
	lea	sr_sdirty,a2
	lea	snap_vram,a4
	lea	bb_penmask,a5
	lea	pen_chg,a6
	move.w	#896-1,d6
.c:	move.w	(a3)+,d0
	and.w	d7,d0
	bne.s	.cand
.cn:	dbf	d6,.c
.none:
	rts
.cand:
	move.w	#896-1,d5
	sub.w	d6,d5			; the cell
	move.w	d5,d2
	bsr.s	sr_cell_pens
	beq.s	.cn
	ifd SIM
	addq.l	#1,sim_sr_palcells
	endc
	move.w	d5,d2
	bsr	sr_setcell
	bra.s	.cn

; d2.w = a cell: Z clear if one of its tiles (both layers' slots) uses a pen whose slot changed.  a4 = snap_vram,
; a5 = bb_penmask, a6 = pen_chg.  Clobbers d0-d4, a0.
sr_cell_pens:
	lsl.w	#3,d2			; (two slots per cell)
	lea	sr_map1,a0
	add.w	d2,a0
	bsr.s	.two
	bne.s	.done
	lea	sr_map2,a0
	add.w	d2,a0
.two:
	moveq	#2-1,d4
.s:	move.l	(a0)+,d0
	bmi.s	.n
	moveq	#0,d1
	move.b	1(a4,d0.w),d1		; the entry's second byte
	move.w	d1,d3
	lsr.w	#2,d3
	and.w	#15,d3			; the bank
	add.w	d3,d3
	move.w	(a6,d3.w),d3		; its changed pens
	beq.s	.n
	and.w	#3,d1
	lsl.w	#8,d1
	move.b	(a4,d0.w),d1		; the tile number's low 10 bits
	swap	d0
	lsl.w	#8,d0
	lsl.w	#2,d0
	or.w	d0,d1			; + the high bits
	add.w	d1,d1
	and.w	(a5,d1.w),d3
	bne.s	.done
.n:	dbf	d4,.s
	moveq	#0,d3			; Z
.done:	rts

; ------------------------------------------------------------------------------
; sr_cells: the cells of sr_sdirty drawn again into sr_img (the back layer's tile, then the front layer's on it)
; and sr_msk (the front layer's opacity); sr_any of their blocks recomputed; their blocks into sr_chg.
; ------------------------------------------------------------------------------

sr_cells:
	lea	sr_sdirty,a0
	moveq	#0,d6			; the cell row
.row:
	move.l	(a0)+,d7
	bne.s	.cols
.nr:	addq.w	#1,d6
	cmp.w	#28,d6
	blo.s	.row
	rts
.cols:
	moveq	#0,d5			; the column
.col:	btst	d5,d7
	beq.s	.nc
	movem.l	d5-d7/a0,-(sp)
	bsr	sr_cell
	movem.l	(sp)+,d5-d7/a0
.nc:	addq.w	#1,d5
	cmp.w	#32,d5
	blo.s	.col
	bra.s	.nr

; d6 = the cell row, d5 = the column.  The cell's four tile slots are resolved to keys (sr_ckeys); a cell
; composed before from the same keys, under the same colours of their pens, is copied from the composite
; cache (sr_ccache); else it is composed (the first tile written, the others merged) and kept there.
sr_cell:
	ifd SIM
	addq.l	#1,sim_sr_cells
	endc
	move.w	d6,d0
	lsl.w	#3,d0
	add.w	#YPAD+16,d0
	mulu	#STRIDE,d0
	move.w	d5,d1
	lsr.w	#1,d1
	lsl.w	#3,d1
	add.w	#GAME_BYTES,d1
	btst	#0,d5
	beq.s	.even
	addq.w	#1,d1
.even:
	add.w	d1,d0
	lea	sr_img,a4
	add.l	d0,a4			; the cell's byte in sr_img
	move.w	d6,d0			; the msk byte of its first line: line * 32 + column
	lsl.w	#8,d0
	add.w	d5,d0
	lea	sr_msk,a5
	add.w	d0,a5
	move.w	d6,d0
	lsl.w	#5,d0
	add.w	d5,d0
	lsl.w	#3,d0			; the cell * 8 (two slots)
	lea	sr_map1,a3
	add.w	d0,a3
	lea	sr_ckeys,a1
	moveq	#0,d7			; (the slots with a tile; bits 16-31: their banks)
	bsr	.key
	bsr	.key
	lea	sr_map2-sr_map1-8(a3),a3
	bsr	.key
	bsr	.key
	move.l	d7,d0			; the cell's banks (sr_cbm: for sr_pal_cells)
	swap	d0
	move.w	d6,d1
	lsl.w	#5,d1
	add.w	d5,d1
	add.w	d1,d1
	lea	sr_cbm,a0
	move.w	d0,(a0,d1.w)
	tst.w	d7
	beq	.empty
	; the composite cache: hash of the four keys
	lea	sr_ckeys,a1
	move.l	(a1)+,d0
	move.l	(a1)+,d1
	rol.l	#5,d1
	eor.l	d1,d0
	move.l	(a1)+,d1
	swap	d1
	eor.l	d1,d0
	move.l	(a1)+,d1
	rol.l	#7,d1
	rol.l	#4,d1
	eor.l	d1,d0
	move.l	d0,d1
	swap	d1
	eor.w	d1,d0
	move.w	d0,d1
	lsr.w	#8,d1
	lsr.w	#2,d1
	eor.w	d1,d0
	and.l	#CC_N-1,d0
	lsl.l	#6,d0			; (CC_ENTRY)
	lea	sr_ccache,a0
	add.l	d0,a0
	move.l	a0,a2
	lea	sr_ckeys,a1
	cmpm.l	(a1)+,(a0)+
	bne.s	.miss
	cmpm.l	(a1)+,(a0)+
	bne.s	.miss
	cmpm.l	(a1)+,(a0)+
	bne.s	.miss
	cmpm.l	(a1)+,(a0)+
	bne.s	.miss
	move.l	a2,a0
	bsr	sr_valid		; (its pens' slots as when it was composed?)
	bne.s	.miss
	ifd SIM
	addq.l	#1,sim_sr_chit
	endc
	lea	CC_DATA(a2),a0
o	set	0
	rept 8
	move.l	(a0)+,d0
	movep.l	d0,o(a4)
o	set	o+STRIDE
	endr
o	set	0
	rept 8
	move.b	(a0)+,o*32/STRIDE(a5)
o	set	o+STRIDE
	endr
	bra	.any
.miss:
	move.l	a2,-(sp)
	lea	sr_ckeys,a1		; (the entry is this cell's from now on: the keys, the stamp)
	move.l	(a1)+,(a2)+
	move.l	(a1)+,(a2)+
	move.l	(a1)+,(a2)+
	move.l	(a1)+,(a2)+
	move.w	pal_epoch,(a2)
	moveq	#0,d7			; (no tile written yet)
	lea	sr_ckeys,a3
	move.l	(a3)+,d4
	moveq	#0,d0			; (the back layer)
	bsr	.tile
	move.l	(a3)+,d4
	moveq	#0,d0
	bsr	.tile
	move.l	(a3)+,d4
	moveq	#1,d0			; the front layer's: into sr_msk too
	bsr	.tile
	move.l	(a3)+,d4
	moveq	#1,d0
	bsr	.tile
	tst.w	d7
	bne.s	.written
	bsr	.clear			; (all blank)
.written:
	move.l	(sp)+,a0		; the composite into the cache
	lea	CC_DATA(a0),a0
o	set	0
	rept 8
	movep.l	o(a4),d0
	move.l	d0,(a0)+
o	set	o+STRIDE
	endr
o	set	0
	rept 8
	move.b	o*32/STRIDE(a5),(a0)+
o	set	o+STRIDE
	endr
	bra	.any
.empty:
	bsr.s	.clear
	bra	.any
.clear:
	moveq	#0,d0
o	set	0
	rept 8
	movep.l	d0,o(a4)
	clr.b	o*32/STRIDE(a5)
o	set	o+STRIDE
	endr
	rts

; a3 = a map slot: its key at (a1)+ (-1: none or blank), d7 + 1 if a tile, and bit 16 + its bank set.  a3 + 4.
.key:
	move.l	(a3)+,d0
	bsr	sr_key
	move.l	d4,(a1)+
	bmi.s	.k_none
	addq.w	#1,d7
	move.l	d4,d0
	lsl.l	#2,d0
	swap	d0			; (the key's bits 14-17: the bank)
	and.w	#15,d0
	add.w	#16,d0
	bset	d0,d7
.k_none:
	rts

; d4 = a key (-1: none): its tile on the cell (a4); d0 = 1: its opacity into sr_msk (a5) as well.  The first
; tile (d7 = 0) is written as it is (its transparent pixels are 0), the others merged.  Keeps a3.
.tile:
	tst.l	d4
	bmi	.t_none
	move.w	d0,-(sp)
	movem.l	d5-d7/a3-a5,-(sp)
	bsr	get_tile
	movem.l	(sp)+,d5-d7/a3-a5
	move.w	(sp)+,d0
	lea	8(a0),a1
	tst.w	d7
	bne	.merge
	moveq	#1,d7
	tst.w	d0
	bne	.f_msk
o	set	0
	rept 8
	move.l	(a1)+,d0
	addq.l	#4,a1
	movep.l	d0,o(a4)
	clr.b	o*32/STRIDE(a5)
o	set	o+STRIDE
	endr
	rts
.f_msk:
o	set	0
	rept 8
	move.l	(a1)+,d0
	move.l	(a1)+,d1
	movep.l	d0,o(a4)
	not.b	d1
	move.b	d1,o*32/STRIDE(a5)
o	set	o+STRIDE
	endr
	rts
.merge:
	tst.w	d0
	bne	.t_msk
o	set	0
	rept 8
	move.l	(a1)+,d0
	move.l	(a1)+,d1		; the inverted mask (the transparent pixels' bits, in all four bytes)
	movep.l	o(a4),d2
	and.l	d1,d2
	or.l	d0,d2
	movep.l	d2,o(a4)
o	set	o+STRIDE
	endr
	rts
.t_msk:
o	set	0
	rept 8
	move.l	(a1)+,d0
	move.l	(a1)+,d1
	movep.l	o(a4),d2
	and.l	d1,d2
	or.l	d0,d2
	movep.l	d2,o(a4)
	not.b	d1
	or.b	d1,o*32/STRIDE(a5)
o	set	o+STRIDE
	endr
.t_none:
	rts
.any:
	; sr_any of the two blocks (rows 2 * row, 2 * row + 1; group column / 2), and both into sr_chg
	move.w	d5,d3
	lsr.w	#1,d3			; the group
	move.w	d5,d0
	and.w	#$FE,d0
	lea	sr_msk,a5
	move.w	d6,d1
	lsl.w	#8,d1
	add.w	d0,a5
	add.w	d1,a5			; the group's msk word of the cell's first line
	lea	sr_any,a1
	lea	sr_chg,a2
	move.w	d6,d1
	lsl.w	#2,d1			; the first block row's word
	moveq	#2-1,d2
.blk:	move.w	(a5),d0
	or.w	32(a5),d0
	or.w	64(a5),d0
	or.w	96(a5),d0
	beq.s	.b_clear
	move.w	(a1,d1.w),d0
	bset	d3,d0
	bra.s	.b_set
.b_clear:
	move.w	(a1,d1.w),d0
	bclr	d3,d0
.b_set:
	move.w	d0,(a1,d1.w)
	move.w	(a2,d1.w),d0
	bset	d3,d0
	move.w	d0,(a2,d1.w)
	lea	128(a5),a5
	addq.w	#2,d1
	dbf	d2,.blk
	rts

; d0.l = a map entry (high bits << 16 | the tile entry's offset, or -1): d4 = the tile's key (as draw_tile makes it)
; and N clear, or N set if none or blank.  Clobbers d0-d3, a0.
sr_key:
	tst.l	d0
	bmi.s	.none
	lea	snap_vram,a0
	moveq	#0,d3
	move.b	1(a0,d0.w),d3		; flips (7-6), bank (5-2), tile number bits 9-8
	moveq	#3,d4
	and.w	d3,d4
	lsl.w	#8,d4
	move.b	(a0,d0.w),d4		; the tile number's low 10 bits
	swap	d0
	ror.w	#6,d0			; (the high bits << 10)
	or.w	d0,d4			; the tile number
	move.w	d4,d1
	lsr.w	#3,d1
	lea	bb_blank,a0
	btst	d4,(a0,d1.w)		; (the bit number mod 8)
	bne.s	.none
	lsr.b	#2,d3			; flips << 4 | bank
	swap	d3
	lsr.l	#2,d3			; << 14
	or.l	d3,d4			; (N clear)
	rts
.none:
	moveq	#-1,d4
	rts
; ------------------------------------------------------------------------------
; Closure: sr_draw = sr_chg and the blocks of every visible sprite that has a block in it (drawn whole), until
; nothing changes; R_IN = drawn.
; ------------------------------------------------------------------------------

sr_closure:
	sb_copy	sr_chg,sr_draw
	move.l	sr_vend,a4
.again:
	moveq	#0,d6			; something added
	lea	sr_vlist,a3
.o:
	cmp.l	a4,a3
	bhs.s	.end
	move.l	(a3)+,a2
	tst.b	R_IN(a2)
	bne.s	.o
	lea	sr_draw,a0
	move.w	R_R0(a2),d0
	move.w	R_R1(a2),d1
	sub.w	d0,d1
	add.w	d0,d0
	add.w	d0,a0
	move.w	R_CM(a2),d2
	move.l	a0,a1
	move.w	d1,d3
.t:	move.w	(a1)+,d0
	and.w	d2,d0
	bne.s	.hit
	dbf	d3,.t
	bra.s	.o
.hit:
	st	R_IN(a2)
.f:	move.w	(a0),d0
	move.w	d0,d4
	or.w	d2,d0
	cmp.w	d4,d0
	beq.s	.same
	moveq	#1,d6
	move.w	d0,(a0)
.same:	addq.l	#2,a0
	dbf	d1,.f
	bra.s	.o
.end:
	tst.w	d6
	bne.s	.again
	rts

; ------------------------------------------------------------------------------
; The sprites of the set in list order: the back layer's, the front columns where they are opaque (from sr_img
; through sr_msk, on the blocks a back layer sprite was drawn on), the front layer's.
; ------------------------------------------------------------------------------

sr_sprites:
	sb_fill	sr_s1,0
	sf	sr_ovl_done
	move.w	sr_c2,d0		; the records of the front layer's sprites start here
	mulu	#SREC,d0
	lea	sr_recs,a5
	add.l	d0,a5
	move.l	a5,sr_c2rec
	lea	sr_vlist,a3
.o:
	cmp.l	sr_vend,a3
	bhs.s	.end
	move.l	(a3)+,a2
	tst.b	R_IN(a2)
	beq.s	.o
	cmp.l	sr_c2rec,a2
	blo.s	.back
	tst.b	sr_ovl_done
	bne.s	.draw
	st	sr_ovl_done
	movem.l	a2-a3,-(sp)
	bsr	sr_overlay
	movem.l	(sp)+,a2-a3
	bra.s	.draw
.back:
	mark_rec	sr_s1
.draw:
	move.l	a3,-(sp)
	bsr	sr_draw1
	move.l	(sp)+,a3
	bra.s	.o
.end:
	tst.b	sr_ovl_done
	bne.s	.done
	bsr	sr_overlay
.done:
	rts

; the record a2 -> a0 = the data of its baked image (sr_cache, baked on a miss).  Keeps a2.
sr_lookup:
	ifd SIM
	addq.l	#1,sim_c_look
	endc
	move.l	R_ENT(a2),d0		; where it was last time
	beq.s	.hash
	move.l	d0,a0
	lea	R_KEYS(a2),a1
	cmpm.l	(a1)+,(a0)+
	bne.s	.hash
	cmpm.l	(a1)+,(a0)+
	bne.s	.hash
	cmpm.l	(a1)+,(a0)+
	bne.s	.hash
	cmpm.l	(a1)+,(a0)+
	bne.s	.hash
	lea	-16(a0),a0
	bsr	sr_valid
	bne	sr_bake
	lea	SC_DATA(a0),a0		; the data
	rts
.hash:
	lea	R_KEYS(a2),a1
	move.l	(a1)+,d0
	move.l	(a1)+,d2
	rol.l	#5,d2
	eor.l	d2,d0
	move.l	(a1)+,d2
	rol.l	#7,d2
	rol.l	#4,d2
	eor.l	d2,d0
	move.l	(a1)+,d2
	swap	d2
	rol.l	#1,d2
	eor.l	d2,d0
	move.l	d0,d2
	swap	d2
	eor.w	d2,d0
	move.w	d0,d2
	lsr.w	#7,d2
	eor.w	d2,d0
	and.w	#SC_N-1,d0
	mulu	#SC_ENTRY,d0
	lea	sr_cache,a0
	add.l	d0,a0
	move.l	a0,R_ENT(a2)
	lea	R_KEYS(a2),a1
	move.l	a0,-(sp)
	cmpm.l	(a1)+,(a0)+
	bne.s	.miss
	cmpm.l	(a1)+,(a0)+
	bne.s	.miss
	cmpm.l	(a1)+,(a0)+
	bne.s	.miss
	cmpm.l	(a1)+,(a0)+
	bne.s	.miss
	move.l	(sp)+,a0
	bsr	sr_valid
	bne	sr_bake
	lea	SC_DATA(a0),a0
	rts
.miss:
	move.l	(sp)+,a0
	bra	sr_bake

; ------------------------------------------------------------------------------
 ; Bake an unshifted image from the four cached tiles, copying colliding entries
 ; first. Each row holds opacity.w, destination offset.w and four plane words.
 ; Group equal masks once on a miss; all 16 skews share the resulting image.
 ; Keeps a2; a0 returns the reordered data.
; ------------------------------------------------------------------------------

sr_bake:
	ifd SIM
	addq.l	#1,sim_c_bake
	endc
	move.l	a2,-(sp)
	move.l	a0,-(sp)
	lea	R_KEYS(a2),a1		; the key
	move.l	(a1)+,(a0)+
	move.l	(a1)+,(a0)+
	move.l	(a1)+,(a0)+
	move.l	(a1)+,(a0)+
	move.w	pal_epoch,(a0)+		; (the stamp: the colour mapping it is baked under)
	clr.w -(sp)
	moveq	#0,d5			; the tile
.tile:
	move.l	6(sp),a2		; (the record)
	move.w	d5,d0
	lsl.w	#2,d0
	move.l	R_KEYS(a2,d0.w),d4
	and.l	#$000FFFFF,d4		; (the tile cache's key)
	move.w	d5,-(sp)
	bsr	get_tile
	move.w	(sp)+,d5
	move.w	d5,d0
	lsl.w	#2,d0
	lea	sr_tptr,a1
	move.l	a0,(a1,d0.w)		; its entry
	addq.w	#1,d5
	cmp.w	#4,d5
	blo.s	.tile
	move.l	6(sp),a2		; all four still there? (the cache is direct mapped: one may have pushed out another)
	lea	sr_tptr,a1
	moveq	#4-1,d5
.chk:	move.l	(a1)+,a0
	move.l	R_KEYS(a2),d0
	and.l	#$000FFFFF,d0
	cmp.l	(a0),d0
	bne.s	.copy
	addq.l	#4,a2
	dbf	d5,.chk
	bra.s	.bake
.copy:					; (rare) one after the other, copied
	moveq	#0,d5
.c_tile:
	move.l	6(sp),a2
	move.w	d5,d0
	lsl.w	#2,d0
	move.l	R_KEYS(a2,d0.w),d4
	and.l	#$000FFFFF,d4
	move.w	d5,-(sp)
	bsr	get_tile
	move.w	(sp)+,d5
	lea	sr_tbuf,a1
	move.w	d5,d0
	mulu	#TC_ENTRY,d0
	add.w	d0,a1
	move.w	d5,d0
	lsl.w	#2,d0
	lea	sr_tptr,a2
	move.l	a1,(a2,d0.w)
	moveq	#18-1,d0		; (the key, the flag, the rows)
.cp:	move.l	(a0)+,(a1)+
	dbf	d0,.cp
	addq.w	#1,d5
	cmp.w	#4,d5
	blo.s	.c_tile
.bake:
	move.w	(sp)+,d6
	move.l	(sp),a0
	lea	SC_DATA(a0),a0
	move.l	sr_tptr,a2		; the left tile's rows
	addq.l	#8,a2
	move.l	sr_tptr+4,a1		; the right one's
	addq.l	#8,a1
	lea	sr_tmp8,a3
	moveq	#16-1,d7
.line:
	cmp.w	#7,d7
	bne.s	.same
	move.l	sr_tptr+8,a2		; the bottom tiles
	addq.l	#8,a2
	move.l	sr_tptr+12,a1
	addq.l	#8,a1
.same:
	move.l	(a2),d0
	movep.l	d0,0(a3)
	move.l	(a1),d0
	movep.l	d0,1(a3)		; the four plane words at a3
	moveq	#0,d0
	move.b	4+3(a2),d0		; the inverted masks (transparent pixels)
	lsl.w	#8,d0
	move.b	4+3(a1),d0
	not.w	d0			; the opaque pixels
	swap	d0
	clr.w	d0

	; Unshifted opaque mask and four plane words. The Blitter does x & 15.
	swap d0
	move.w d0,(a0)+
	moveq #15,d0
	sub.w d7,d0
	mulu #STRIDE,d0
	move.w d0,(a0)+
	move.l (a3),(a0)+
	move.l 4(a3),(a0)+
	addq.l	#8,a2
	addq.l	#8,a1
	dbf	d7,.line
	move.l (sp),a0
	lea SC_DATA(a0),a0
	bsr sr_reorder
	move.l	(sp)+,a0
	lea	SC_DATA(a0),a0
	move.l	(sp)+,a2
	rts

 ; Group identical opaque masks once per miss, followed by contiguous plane rows.
 ; Pairs: mask.w (the group's first row; 0: the same as the row before), offset.w;
 ; the number of opaque rows - 1 in the word before the data (the entry's 18).
 ; The Blitter source advances itself; mask/offset pairs retain original positions.
 ; sr_tbuf is free after the four tiles have been consumed. No sprite is clipped.
sr_reorder:
	move.l a0,a4
	lea sr_tbuf,a1
	moveq #16*12/4-1,d0
.copy:
	move.l (a0)+,(a1)+
	dbf d0,.copy
	move.l a4,a0
	lea 16*4(a0),a5
	moveq #0,d5                ; rows already emitted
	moveq #-1,d3               ; opaque rows - 1
	moveq #0,d7
.outer:
	btst d7,d5
	bne.s .next
	move.w d7,d0
	mulu #12,d0
	lea sr_tbuf,a1
	move.w (a1,d0.w),d6
	beq.s .next              ; transparent rows need no source words
	moveq #0,d4
	lea sr_tbuf,a1
	move.w d6,d2               ; the group's first row carries its mask, the others 0
.same:
	btst d4,d5
	bne.s .skip
	cmp.w (a1),d6
	bne.s .skip
	bset d4,d5
	addq.w #1,d3
	move.w d2,(a0)+          ; the mask (or 0: the same) and the original row offset
	moveq #0,d2
	move.w 2(a1),(a0)+
	move.l 4(a1),(a5)+
	move.l 8(a1),(a5)+
.skip:
	lea 12(a1),a1
	addq.w #1,d4
	cmp.w #16,d4
	blo.s .same
.next:
	addq.w #1,d7
	cmp.w #16,d7
	blo.s .outer
	move.w d3,-2(a4)        ; the rows sr_draw1 draws, - 1 (-1: none)
	rts

; every composite is dropped (a key that cannot be)
sr_ccflush:
	lea	sr_ccache,a0
	move.w	#CC_N-1,d0
	move.l	#$40000000,d1
.f:	move.l	d1,(a0)
	lea	CC_ENTRY(a0),a0
	dbf	d0,.f
	rts

; every baked sprite image is dropped
sr_flush:
	lea	sr_cache,a0
	move.w	#SC_N-1,d0
.f:	move.l	#-1,(a0)
	lea	SC_ENTRY(a0),a0
	dbf	d0,.f
	rts

; ------------------------------------------------------------------------------
; Block copies: the blocks of the bitmap a0 from the buffer a5 to the buffer a4 (both in the screen's layout).
; Per row the runs of set groups are found with two tables (sr_tz: the clear bits below the lowest set bit of a
; byte, sr_to: the set bits from bit 0 up); a run of one to three groups is copied by the CPU, a longer one (up to
; 8 groups: 32 words a line) by the Blitter in HOG passes of one line.  Clobbers d0-d7, a0-a3, a6.
; ------------------------------------------------------------------------------

sr_blocks:
	ifnd CPUCOPIES
	move.w #2,$ffff8a20.w
	move.w #2,$ffff8a2e.w
	move.w #$ffff,$ffff8a28.w
	move.w #$ffff,$ffff8a2a.w
	move.w #$ffff,$ffff8a2c.w
	move.w #$0203,$ffff8a3a.w
	clr.b $ffff8a3d.w
	endc
	lea	(YPAD+16)*STRIDE+GAME_BYTES(a5),a5
	lea	(YPAD+16)*STRIDE+GAME_BYTES(a4),a4
	lea	sr_tz,a3
	lea	sr_to,a6
	moveq	#SR_ROWS-1,d7
.row:
	move.w	(a0)+,d6
	beq	.nr
	move.l	a5,a1
	move.l	a4,a2
.g:					; d6: bit 0 = the group at a1 / a2
	moveq	#0,d0
	move.b	d6,d0
	bne.s	.lo
	lsr.w	#8,d6			; (none in the low byte: 8 groups on)
	beq	.nr
	lea	64(a1),a1
	lea	64(a2),a2
	move.b	d6,d0
.lo:	move.b	(a3,d0.w),d0		; the groups before the run
	lsr.w	d0,d6
	lsl.w	#3,d0
	add.w	d0,a1
	add.w	d0,a2
	moveq	#0,d0
	move.b	d6,d0
	move.b	(a6,d0.w),d0		; the run: 1-8 groups
	lsr.w	d0,d6
	ifd SIM
	move.l	a0,-(sp)
	move.l	sim_blk_dst,a0
	add.l	d0,(a0)
	move.l	(sp)+,a0
	endc
	subq.w	#2,d0
	bmi	.k1
	beq	.k2
	subq.w	#1,d0
	beq.s	.k3
	ifnd CPUCOPIES
	addq.w	#3,d0			; (the run)
	move.w	d0,d1
	lsl.w	#2,d1			; four words per group
	move.w	d1,$ffff8a36.w
	add.w	d1,d1
	move.w	#STRIDE+2,d2
	sub.w	d1,d2
	move.w	d2,$ffff8a22.w
	move.w	d2,$ffff8a30.w
	move.l	a1,$ffff8a24.w
	move.l	a2,$ffff8a32.w
	rept 4				; (a line a pass: at most 32 words)
	move.w	#1,$ffff8a38.w
	move.b	#$c0,$ffff8a3c.w
	endr
	add.w	d1,a1
	add.w	d1,a2
	tst.w	d6
	bne	.g
	bra	.nr
	else
	moveq	#-1,d1			; (the run: three now, the others again)
	lsl.w	d0,d1
	not.w	d1
	lsl.w	d0,d6
	or.w	d1,d6
	endc
.k3:
	movem.l	0(a1),d0-d5
	movem.l	d0-d5,0(a2)
	movem.l	STRIDE(a1),d0-d5
	movem.l	d0-d5,STRIDE(a2)
	movem.l	2*STRIDE(a1),d0-d5
	movem.l	d0-d5,2*STRIDE(a2)
	movem.l	3*STRIDE(a1),d0-d5
	movem.l	d0-d5,3*STRIDE(a2)
	lea	24(a1),a1
	lea	24(a2),a2
	tst.w	d6
	bne	.g
	bra.s	.nr
.k2:
	movem.l	0(a1),d0-d3
	movem.l	d0-d3,0(a2)
	movem.l	STRIDE(a1),d0-d3
	movem.l	d0-d3,STRIDE(a2)
	movem.l	2*STRIDE(a1),d0-d3
	movem.l	d0-d3,2*STRIDE(a2)
	movem.l	3*STRIDE(a1),d0-d3
	movem.l	d0-d3,3*STRIDE(a2)
	lea	16(a1),a1
	lea	16(a2),a2
	tst.w	d6
	bne	.g
	bra.s	.nr
.k1:
	move.l	0(a1),0(a2)
	move.l	4(a1),4(a2)
	move.l	STRIDE(a1),STRIDE(a2)
	move.l	STRIDE+4(a1),STRIDE+4(a2)
	move.l	2*STRIDE(a1),2*STRIDE(a2)
	move.l	2*STRIDE+4(a1),2*STRIDE+4(a2)
	move.l	3*STRIDE(a1),3*STRIDE(a2)
	move.l	3*STRIDE+4(a1),3*STRIDE+4(a2)
	addq.l	#8,a1
	addq.l	#8,a2
	tst.w	d6
	bne	.g
.nr:	lea	4*STRIDE(a5),a5
	lea	4*STRIDE(a4),a4
	dbf	d7,.row
	rts

; the tables of sr_blocks, per byte value: the clear bits below its lowest set bit (sr_tz), the set bits from
; bit 0 up (sr_to)
sr_tz:
v	set	0
	rept 256
b	set	0
	if v
	rept 8
	if ((v>>b)&1)=0
b	set	b+1
	endif
	endr
	endif
	dc.b	b
v	set	v+1
	endr
sr_to:
v	set	0
	rept 256
b	set	0
	rept 8
	if ((v>>b)&1)=1
b	set	b+1
	endif
	endr
	dc.b	b
v	set	v+1
	endr
	even

; the blocks this screen lacks, outside this frame's set: from the screen drawn last (it is complete)
sr_copy:
	move.w	rf_buf,d0
	mulu	#SR_ROWS*2,d0
	lea	sr_stale,a0
	add.l	d0,a0			; what this screen lacks
	lea	sr_draw,a1
	lea	sr_tmp,a2
	moveq	#SR_ROWS-1,d0
.c:	move.w	(a1)+,d1
	not.w	d1
	and.w	(a0)+,d1
	move.w	d1,(a2)+
	dbf	d0,.c
	lea	sr_tmp,a0
	ifd SIM
	move.l	#sim_sr_copyblk,sim_blk_dst
	endc
	move.l	last_screen_address,a5
	move.l	rf_screen,a4
	bra	sr_blocks

; the set: the static picture
sr_restore:
	ifd SIM
	move.l	#sim_sr_restblk,sim_blk_dst
	endc
	lea	sr_draw,a0
	lea	sr_img,a5
	move.l	rf_screen,a4
	bra	sr_blocks

; the front columns again on the blocks of sr_s1 where they have opaque pixels (sr_any)
sr_overlay:
	lea	sr_s1,a0
	lea	sr_any,a1
	move.l	rf_screen,a4
	lea	(YPAD+16)*STRIDE+GAME_BYTES(a4),a4
	lea	sr_img+(YPAD+16)*STRIDE+GAME_BYTES,a5
	lea	sr_msk,a6
	moveq	#SR_ROWS-1,d7
.row:
	move.w	(a0)+,d6
	and.w	(a1)+,d6
	beq	.nr
	move.l	a4,a2
	move.l	a5,a3
	moveq	#0,d5			; the group * 2
.g:	lsr.w	#1,d6
	bcc	.ng
	move.w	0(a6,d5.w),d0		; the opaque pixels of the front columns
	beq.s	.z0
	move.w	d0,d1
	swap	d0
	move.w	d1,d0
	move.l	d0,d1
	not.l	d1
	move.l	0(a2),d2
	and.l	d1,d2
	move.l	0(a3),d3
	and.l	d0,d3
	or.l	d3,d2
	move.l	d2,0(a2)
	move.l	4(a2),d2
	and.l	d1,d2
	move.l	4(a3),d3
	and.l	d0,d3
	or.l	d3,d2
	move.l	d2,4(a2)
.z0:
	move.w	32(a6,d5.w),d0		; the opaque pixels of the front columns
	beq.s	.z1
	move.w	d0,d1
	swap	d0
	move.w	d1,d0
	move.l	d0,d1
	not.l	d1
	move.l	STRIDE(a2),d2
	and.l	d1,d2
	move.l	STRIDE(a3),d3
	and.l	d0,d3
	or.l	d3,d2
	move.l	d2,STRIDE(a2)
	move.l	STRIDE+4(a2),d2
	and.l	d1,d2
	move.l	STRIDE+4(a3),d3
	and.l	d0,d3
	or.l	d3,d2
	move.l	d2,STRIDE+4(a2)
.z1:
	move.w	64(a6,d5.w),d0		; the opaque pixels of the front columns
	beq.s	.z2
	move.w	d0,d1
	swap	d0
	move.w	d1,d0
	move.l	d0,d1
	not.l	d1
	move.l	2*STRIDE(a2),d2
	and.l	d1,d2
	move.l	2*STRIDE(a3),d3
	and.l	d0,d3
	or.l	d3,d2
	move.l	d2,2*STRIDE(a2)
	move.l	2*STRIDE+4(a2),d2
	and.l	d1,d2
	move.l	2*STRIDE+4(a3),d3
	and.l	d0,d3
	or.l	d3,d2
	move.l	d2,2*STRIDE+4(a2)
.z2:
	move.w	96(a6,d5.w),d0		; the opaque pixels of the front columns
	beq.s	.z3
	move.w	d0,d1
	swap	d0
	move.w	d1,d0
	move.l	d0,d1
	not.l	d1
	move.l	3*STRIDE(a2),d2
	and.l	d1,d2
	move.l	3*STRIDE(a3),d3
	and.l	d0,d3
	or.l	d3,d2
	move.l	d2,3*STRIDE(a2)
	move.l	3*STRIDE+4(a2),d2
	and.l	d1,d2
	move.l	3*STRIDE+4(a3),d3
	and.l	d0,d3
	or.l	d3,d2
	move.l	d2,3*STRIDE+4(a2)
.z3:
.ng:	addq.l	#8,a2
	addq.l	#8,a3
	addq.w	#2,d5
	tst.w	d6
	bne	.g
.nr:	lea	4*STRIDE(a4),a4
	lea	4*STRIDE(a5),a5
	lea	128(a6),a6
	dbf	d7,.row
	rts

; ------------------------------------------------------------------------------
 ; One sprite, whole vertically into guard rows and clipped at the aligned
 ; side picture edges using its prepared masks with the outer end mask zero.
sr_draw1:
	ifd SIM
	addq.l #1,sim_c_draw
	endc
	bsr sr_lookup
	move.w R_Y(a2),d0
	add.w #YPAD,d0
	mulu #STRIDE,d0
	move.l rf_screen,a1
	add.l d0,a1
	move.w R_X(a2),d0
	asr.w #4,d0
	lsl.w #3,d0
	add.w #GAME_BYTES,d0
	add.w d0,a1
	move.w R_SHIFT(a2),d6
	move.w -2(a0),d7           ; the opaque rows - 1
	bmi.s .done
	move.w #2,$ffff8a20.w
	move.w #2,$ffff8a22.w
	move.w #8,$ffff8a2e.w
	move.w #-6,$ffff8a30.w
	move.w #$0203,$ffff8a3a.w
	move.w #2,$ffff8a36.w
	move.w #$c040,d3           ; BUSY+HOG, NFSR; the second group reuses the source word
	or.w d6,d3
	lea 16*4(a0),a3
	move.l a3,$ffff8a24.w      ; contiguous source words advance between passes
	lea $ffff8a32.w,a4         ; (the destination; -10 endmask 1, -6 endmask 3, 6 y count, 10 control)
	moveq #4,d5
	move.w R_X(a2),d0          ; across the left or right picture edge: the outer word's end mask is 0
	bmi.s .left
	cmp.w #240,d0
	bgt.s .right
.line:
	move.w (a0)+,d0            ; a new mask group (0: the same mask)
	beq.s .same
	swap d0
	clr.w d0
	lsr.l d6,d0
	move.w d0,-6(a4)
	swap d0
	move.w d0,-10(a4)
.same:
	move.l a1,a3
	add.w (a0)+,a3            ; original row, in the virtual screen
	move.l a3,(a4)
	move.w d5,6(a4)
	move.w d3,10(a4)
	dbf d7,.line
.done:
	rts
.left:
	moveq #0,d4
	not.w d4
	bra.s .cline
.right:
	moveq #-1,d4
	clr.w d4
.cline:
	move.w (a0)+,d0
	beq.s .csame
	swap d0
	clr.w d0
	lsr.l d6,d0
	and.l d4,d0                ; (left: d4 = $0000ffff, right: $ffff0000)
	move.w d0,-6(a4)
	swap d0
	move.w d0,-10(a4)
.csame:
	move.l a1,a3
	add.w (a0)+,a3
	move.l a3,(a4)
	move.w d5,6(a4)
	move.w d3,10(a4)
	dbf d7,.cline
	rts

	section bss,bss
	ifd SIM
sim_sr_frames:	ds.l	1		; (tools/profile.py: frames the sprite renderer drew)
sim_sr_maps:	ds.l	1		; (... the column maps built, refused)
sim_sr_cannot:	ds.l	1
sim_c_bake:	ds.l	1
sim_c_draw:	ds.l	1
sim_c_look:	ds.l	1		; (sprite cache lookups; sim_c_bake the misses)
sim_sr_chit:	ds.l	1		; cells copied from the composite cache
sim_sr_cells:	ds.l	1		; static cells composed
sim_sr_rebuild:	ds.l	1		; whole static rebuilds
sim_sr_palcells:	ds.l	1		; cell slots marked by a pen slot change
sim_sr_vis:	ds.l	1		; visible sprites listed (sim_c_draw: drawn after closure)
sim_sr_copyblk:	ds.l	1		; blocks copied from the last screen
sim_sr_restblk:	ds.l	1		; blocks restored from sr_img
sim_blk_dst:	ds.l	1
	endc
sr_has_guard:	ds.b 1			; the guards drawn into (bits: left, right, top, bottom)
sr_guard_pages:	ds.b 3
	even
sr_recs:	ds.b	SR_N*SREC
sr_vlist:	ds.l	SR_N		; the visible sprites' records, in list order
sr_vend:	ds.l	1
sr_c2rec:	ds.l	1
sr_c2:		ds.w	1		; the first object of the front columns
sr_hi:		ds.w	1		; the last object in use (-1: none)
sr_end:		ds.w	1
sr_s1first:	ds.w	1		; the first sprite
sr_cnew:	ds.b	SR_CMAX*10
sr_ccount:	ds.w	1
sr_map1:	ds.l	896*2
sr_map2:	ds.l	896*2		; (follows sr_map1)
sr_vinv:	ds.w	3712
sr_sdirty:	ds.l	28
sr_ckeys:	ds.l	4		; (sr_cell) the cell's four tile keys
sr_cbm:		ds.w	896		; per cell: the banks of its tiles (as last composed)
sr_chg:		ds.w	SR_ROWS
sr_draw:	ds.w	SR_ROWS
sr_stale:	ds.w	3*SR_ROWS	; per screen: the blocks it lacks (the sets drawn since it was drawn)
sr_s1:		ds.w	SR_ROWS
sr_tmp:		ds.w	SR_ROWS
sr_any:		ds.w	SR_ROWS
sr_tmp8:	ds.b	8
sr_tbuf:	ds.b	4*72
sr_tptr:	ds.l	4		; (sr_bake) the four tiles' entries
sr_active:	ds.b	1
sr_full:	ds.b	1
sr_was:		ds.b	1
sr_ovl_done:	ds.b	1
sr_schg:	ds.b	1
sr_genchg:	ds.b	1
sr_fast:	ds.b	1		; (sr_scan: the records are the last frame's)
sr_inited:	ds.b	1
sr_mstate:	ds.b	1		; the column maps: 0 to build, 1 built, 2 refused
sr_rebuild:	ds.b	1		; the static picture is drawn whole
	even
sr_msk:		ds.b	224*32
sr_img:		ds.b	SCREEN_SIZE
sr_cache:	ds.b	SC_N*SC_ENTRY
	section text,code
