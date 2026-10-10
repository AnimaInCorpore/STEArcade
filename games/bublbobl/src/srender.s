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
; A sprite is drawn from its own baked image: the four tiles shifted to its x (16 shifts) as two plane word groups
; per line, the mask inverted and doubled (sr_cache: direct mapped, keyed by the four tiles and the shift).
; Sprites are clipped to the game area by whole groups (the area is 16 groups wide) and by lines.
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
R_GEN = 12				;   ... the colour generations of their banks
R_X = 16				;   x (signed)
R_Y = 18				;   the top line (game coordinates)
R_R0 = 20				;   the first and the last block row
R_R1 = 22
R_CM = 24				;   the block columns
R_KIND = 26				;   0 nothing, 1 a sprite, 2 a column
R_VIS = 27				;   a sprite with something on the screen
R_LA = 28				;   the first line on the screen (0-15) and how many
R_LN = 29
R_GS = 30				;   the groups drawn: 1 the left one, 2 the right one, 3 both
R_G0 = 31				;   the left group (-1..15)
R_TOFF = 32				;   a sprite: its top left tile entry; a column: its x
R_SHIFT = 34				;   a sprite: x & 15; a column: its layer (0 behind the sprites, 2 in front)
R_KEYS = 36				;   the four tiles' keys (with the generations): the baked image's
R_ENT = 52				;   the sprite cache entry it was found in (checked before use)
R_IN = 56				;   drawn this frame (sr_closure)
R_IDX = 57				;   the object's number
R_NB = 58				;   a sprite's tiles are not all blank
SC_N = 512				; sprite cache entries
SC_ENTRY = 408				;   the four tile keys, the shift.w, -.w, 16 lines of 24 bytes
SC_DATA = 20
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
	bsr	sr_flush		; (no baked image yet)
.inited:
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
.active:
	ifd SIM
	addq.l	#1,sim_sr_frames
	endc
	; the static picture
	tst.b	sr_rebuild
	beq.s	.changes
	sf	sr_rebuild
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
	bsr	sr_closure		; sr_chg -> sr_draw (the set), R_IN (the sprites drawn)
	tst.b	sr_full
	bne.s	.no_copy
	bsr	sr_copy			; the last frame's set, outside this one's: from the screen shown
.no_copy:
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
	move.w	#SR_N-1,d0
.hi:	tst.l	-(a0)
	bne.s	.hi_found
	cmp.w	sr_hi,d0
	ble.s	.hi_found
	dbf	d0,.hi
	moveq	#0,d0
.hi_found:
	cmp.w	sr_hi,d0
	bge.s	.hi_ok
	move.w	sr_hi,d0
.hi_ok:
	addq.w	#1,d0
	move.w	d0,sr_end		; objects 0 .. sr_end - 1
	move.w	#-1,sr_hi
	moveq	#0,d6			; the phase: 0 columns, 1 sprites, 2 columns, 3 sprites
	moveq	#0,d7			; the chained x
	moveq	#0,d5			; the object
.obj:
	move.l	(a4)+,d0
	cmp.l	R_ORAM(a2),d0
	bne	.changed
	tst.l	d0
	beq	.next			; (nothing, as before)
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
	move.l	d0,a5			; (mark_rec takes d0-d2)
	mark_rec	sr_chg
	move.l	a5,d0
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
	cmp.w	sr_end,d5
	blo	.obj
	move.l	a3,sr_vend
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

; the record a2's tiles: R_T01, R_T23, R_GEN, R_KEYS; R_VIS set if it has a place on the screen and a tile that is
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
	bsr	sr_gens
	move.l	d4,R_GEN(a2)
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
	bsr	sr_gens
	cmp.l	R_GEN(a2),d4
	bne.s	.diff
.same:
	moveq	#0,d0
	rts
.diff:
	moveq	#1,d0
	rts

; d4 = the colour generations of the record a2's four tile banks (a byte each).  Clobbers d0-d2, a0.
sr_gens:
	lea	sr_gen,a0
	moveq	#0,d4
	move.l	R_T01(a2),d0
	bsr.s	.two
	move.l	R_T23(a2),d0
.two:
	moveq	#2-1,d2
.g:	swap	d0
	move.w	d0,d1
	lsr.w	#2,d1
	and.w	#15,d1
	lsl.l	#8,d4
	move.b	(a0,d1.w),d4
	dbf	d2,.g
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

; d0.w = a tile entry, d1.w = the high bits of the tile number: its key (as draw_tile's) | the generation of its
; bank << 20 at (a1)+.  Keeps d0, d1.  Clobbers d2-d4, a0.
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
	moveq	#15,d4
	and.w	d3,d4			; the bank
	lea	sr_gen,a0
	move.b	(a0,d4.w),d4
	lsl.w	#6,d4
	or.w	d4,d3			; generation << 6 | flips << 4 | bank
	swap	d3
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

; the banks whose colours changed (rf_palette: bank_chg_b): a new generation (their sprites change); sr_genchg
sr_pal_gens:
	sf	sr_genchg
	lea	bank_chg_b,a0
	lea	sr_gen,a1
	moveq	#16-1,d1
.gen:	tst.b	(a0)+
	beq.s	.gn
	addq.b	#1,(a1)
	st	sr_genchg
.gn:	addq.l	#1,a1
	dbf	d1,.gen
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
; changed are drawn again
sr_pal_cells:
	lea	bank_chg_b,a0
	moveq	#0,d0
	moveq	#16-1,d1
.any:	or.b	(a0)+,d0
	dbf	d1,.any
	tst.b	d0
	beq	.none
	lea	sr_map1,a3
	lea	sr_sdirty,a2
	lea	snap_vram,a4
	lea	bb_penmask,a5
	lea	pen_chg,a6
	move.w	#896*4-1,d7		; (both maps, two slots each)
	moveq	#0,d6			; the slot
.cell:
	move.l	(a3)+,d0
	bmi.s	.cn
	moveq	#0,d1
	move.b	1(a4,d0.w),d1		; the entry's second byte
	move.w	d1,d2
	lsr.w	#2,d2
	and.w	#15,d2			; the bank
	add.w	d2,d2
	move.w	(a6,d2.w),d2		; its changed pens
	beq.s	.cn
	and.w	#3,d1
	lsl.w	#8,d1
	move.b	(a4,d0.w),d1		; the tile number's low 10 bits
	swap	d0
	lsl.w	#8,d0
	lsl.w	#2,d0
	or.w	d0,d1			; + the high bits
	add.w	d1,d1
	and.w	(a5,d1.w),d2
	beq.s	.cn
	move.w	d6,d2		; the cell (of either map)
	lsr.w	#1,d2
	cmp.w	#896,d2
	blo.s	.c1
	sub.w	#896,d2
.c1:	bsr	sr_setcell
.cn:	addq.w	#1,d6
	dbf	d7,.cell
.none:
	rts

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

; d6 = the cell row, d5 = the column
sr_cell:
	move.w	d6,d0
	lsl.w	#3,d0
	add.w	#YPAD+16,d0
	mulu	#STRIDE,d0
	move.w	d5,d1
	lsr.w	#1,d1
	lsl.w	#3,d1
	add.w	#16,d1
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
	move.w	d0,-(sp)
	moveq	#0,d0
o	set	0
	rept 8
	movep.l	d0,o(a4)
	clr.b	o*32/STRIDE(a5)
o	set	o+STRIDE
	endr
	moveq	#0,d7			; the back layer's tiles, in order
	lea	sr_map1,a0
	move.w	(sp),d0
	move.l	(a0,d0.w),d0
	bsr.s	.tile
	lea	sr_map1,a0
	move.w	(sp),d0
	move.l	4(a0,d0.w),d0
	bsr.s	.tile
	moveq	#1,d7			; the front layer's, into sr_msk too
	lea	sr_map2,a0
	move.w	(sp),d0
	move.l	(a0,d0.w),d0
	bsr.s	.tile
	lea	sr_map2,a0
	move.w	(sp)+,d0
	move.l	4(a0,d0.w),d0
	bsr.s	.tile
	bra	.any
; d0 = a map entry: its tile on the cell (a4); d7 = 1: its opacity into sr_msk (a5) as well
.tile:
	bsr	sr_key
	bmi	.t_none
	movem.l	d5-d7/a4-a5,-(sp)
	bsr	get_tile
	movem.l	(sp)+,d5-d7/a4-a5
	lea	8(a0),a1
	tst.w	d7
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
; and N clear, or N set if none or blank.  Clobbers d0-d3.
sr_key:
	tst.l	d0
	bmi.s	.none
	lea	snap_vram,a0
	moveq	#0,d4
	moveq	#0,d3
	move.b	(a0,d0.w),d4
	move.b	1(a0,d0.w),d3
	move.w	d3,d1
	and.w	#3,d1
	lsl.w	#8,d1
	or.w	d1,d4
	swap	d0
	moveq	#10,d1
	lsl.w	d1,d0
	or.w	d0,d4			; the tile number
	lea	bb_blank,a0
	move.w	d4,d1
	lsr.w	#3,d1
	move.w	d4,d2
	and.w	#7,d2
	btst	d2,(a0,d1.w)
	bne.s	.none
	moveq	#0,d1
	move.b	d3,d1
	lsr.b	#2,d1
	and.w	#15,d1			; the bank
	moveq	#14,d2
	lsl.l	d2,d1
	or.l	d1,d4
	moveq	#0,d1
	move.b	d3,d1
	lsr.b	#6,d1			; the flips
	moveq	#18,d2
	lsl.l	d2,d1
	or.l	d1,d4			; (N clear)
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
	move.w	R_SHIFT(a2),d0
	cmp.w	(a0),d0
	bne.s	.hash
	addq.l	#4,a0			; the data
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
	move.w	R_SHIFT(a2),d6
	move.w	d6,d2
	mulu	#97,d2
	add.w	d2,d0
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
	cmp.w	(a0),d6
	bne.s	.miss
	move.l	(sp)+,a0
	lea	SC_DATA(a0),a0
	rts
.miss:
	move.l	(sp)+,a0
	bra	sr_bake

; ------------------------------------------------------------------------------
; Baking a sprite image: a0 = the entry, a2 = the record (R_KEYS: the four tile keys), d6 = the shift.  The four
; tiles (tcache) are copied first (the cache could drop one while the next is baked), then per line: the left and
; the right tile's row as four plane words and the opaque mask word (movep: the tiles' plane bytes side by side),
; each shifted right by s across two words (the high one is the left group's).  A line: ~m0:~m0, p0:p1, p2:p3 (the
; left group), ~m1:~m1, p0:p1, p2:p3 (the right group).  Keeps a2; a0 = the data.
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
	move.w	d6,(a0)+
	move.w	d6,-(sp)
	moveq	#0,d5			; the tile
.tile:
	move.l	6(sp),a2		; (the record)
	move.w	d5,d0
	lsl.w	#2,d0
	move.l	R_KEYS(a2,d0.w),d4
	and.l	#$000FFFFF,d4		; (the tile cache's key: no generation)
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
	lsl.w	#6,d0
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
	lsr.l	d6,d0
	not.l	d0			; ~m0 : ~m1
	move.l	d0,d1
	swap	d1
	move.w	d1,d2
	swap	d2
	move.w	d1,d2			; ~m0 : ~m0
	move.l	d2,(a0)
	move.l	d0,d2
	swap	d2
	move.w	d0,d2			; ~m1 : ~m1
	move.l	d2,12(a0)
	moveq	#0,d0			; the planes
	move.w	(a3),d0
	swap	d0
	lsr.l	d6,d0
	moveq	#0,d1
	move.w	2(a3),d1
	swap	d1
	lsr.l	d6,d1
	moveq	#0,d2
	move.w	4(a3),d2
	swap	d2
	lsr.l	d6,d2
	moveq	#0,d3
	move.w	6(a3),d3
	swap	d3
	lsr.l	d6,d3
	move.l	d0,d4			; p0:p1 of the left group
	move.l	d1,d5
	swap	d5
	move.w	d5,d4
	move.l	d4,4(a0)
	move.l	d2,d4			; p2:p3
	move.l	d3,d5
	swap	d5
	move.w	d5,d4
	move.l	d4,8(a0)
	swap	d0			; the right group: the low words
	move.w	d1,d0
	move.l	d0,16(a0)
	swap	d2
	move.w	d3,d2
	move.l	d2,20(a0)
	lea	24(a0),a0
	addq.l	#8,a2
	addq.l	#8,a1
	dbf	d7,.line
	move.l	(sp)+,a0
	lea	SC_DATA(a0),a0
	move.l	(sp)+,a2
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
; Block copies: the blocks of the bitmap a0 from the buffer a5 to the buffer a4 (both in the screen's layout)
; ------------------------------------------------------------------------------

sr_blocks:
	lea	(YPAD+16)*STRIDE+16(a5),a5
	lea	(YPAD+16)*STRIDE+16(a4),a4
	moveq	#SR_ROWS-1,d7
.row:
	move.w	(a0)+,d6
	beq	.nr
	move.l	a5,a1
	move.l	a4,a2
.g:	tst.w	d6
	beq	.nr
	lsr.w	#1,d6
	bcs.s	.found
	addq.l	#8,a1
	addq.l	#8,a2
	bra.s	.g
.found:					; runs of up to three groups at once (movem)
	lsr.w	#1,d6
	bcc	.k1
	lsr.w	#1,d6
	bcc.s	.k2
	movem.l	0(a1),d0-d5
	movem.l	d0-d5,0(a2)
	movem.l	160(a1),d0-d5
	movem.l	d0-d5,160(a2)
	movem.l	320(a1),d0-d5
	movem.l	d0-d5,320(a2)
	movem.l	480(a1),d0-d5
	movem.l	d0-d5,480(a2)
	lea	24(a1),a1
	lea	24(a2),a2
	bra.s	.g
.k2:					; (two, and the group after them is clear)
	movem.l	0(a1),d0-d3
	movem.l	d0-d3,0(a2)
	movem.l	160(a1),d0-d3
	movem.l	d0-d3,160(a2)
	movem.l	320(a1),d0-d3
	movem.l	d0-d3,320(a2)
	movem.l	480(a1),d0-d3
	movem.l	d0-d3,480(a2)
	lea	24(a1),a1
	lea	24(a2),a2
	bra	.g
.k1:					; (one, and the group after it is clear)
	move.l	0(a1),0(a2)
	move.l	4(a1),4(a2)
	move.l	160(a1),160(a2)
	move.l	164(a1),164(a2)
	move.l	320(a1),320(a2)
	move.l	324(a1),324(a2)
	move.l	480(a1),480(a2)
	move.l	484(a1),484(a2)
	lea	16(a1),a1
	lea	16(a2),a2
	bra	.g
.nr:	lea	4*STRIDE(a5),a5
	lea	4*STRIDE(a4),a4
	dbf	d7,.row
	rts

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
	move.l	last_screen_address,a5
	move.l	rf_screen,a4
	bra	sr_blocks

; the set: the static picture
sr_restore:
	lea	sr_draw,a0
	lea	sr_img,a5
	move.l	rf_screen,a4
	bra	sr_blocks

; the front columns again on the blocks of sr_s1 where they have opaque pixels (sr_any)
sr_overlay:
	lea	sr_s1,a0
	lea	sr_any,a1
	move.l	rf_screen,a4
	lea	(YPAD+16)*STRIDE+16(a4),a4
	lea	sr_img+(YPAD+16)*STRIDE+16,a5
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
	move.l	160(a2),d2
	and.l	d1,d2
	move.l	160(a3),d3
	and.l	d0,d3
	or.l	d3,d2
	move.l	d2,160(a2)
	move.l	164(a2),d2
	and.l	d1,d2
	move.l	164(a3),d3
	and.l	d0,d3
	or.l	d3,d2
	move.l	d2,164(a2)
.z1:
	move.w	64(a6,d5.w),d0		; the opaque pixels of the front columns
	beq.s	.z2
	move.w	d0,d1
	swap	d0
	move.w	d1,d0
	move.l	d0,d1
	not.l	d1
	move.l	320(a2),d2
	and.l	d1,d2
	move.l	320(a3),d3
	and.l	d0,d3
	or.l	d3,d2
	move.l	d2,320(a2)
	move.l	324(a2),d2
	and.l	d1,d2
	move.l	324(a3),d3
	and.l	d0,d3
	or.l	d3,d2
	move.l	d2,324(a2)
.z2:
	move.w	96(a6,d5.w),d0		; the opaque pixels of the front columns
	beq.s	.z3
	move.w	d0,d1
	swap	d0
	move.w	d1,d0
	move.l	d0,d1
	not.l	d1
	move.l	480(a2),d2
	and.l	d1,d2
	move.l	480(a3),d3
	and.l	d0,d3
	or.l	d3,d2
	move.l	d2,480(a2)
	move.l	484(a2),d2
	and.l	d1,d2
	move.l	484(a3),d3
	and.l	d0,d3
	or.l	d3,d2
	move.l	d2,484(a2)
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
; One sprite (the record a2) into rf_screen, clipped to its lines and groups
; ------------------------------------------------------------------------------

sr_draw1:
	ifd SIM
	addq.l	#1,sim_c_draw
	endc
	bsr	sr_lookup		; a0 = the baked image
	moveq	#0,d0
	move.b	R_LA(a2),d0
	move.w	d0,d1
	mulu	#24,d1
	add.l	d1,a0			; its first line on the screen
	add.w	R_Y(a2),d0
	add.w	#YPAD,d0
	mulu	#STRIDE,d0
	move.l	rf_screen,a1
	add.l	d0,a1
	move.b	R_G0(a2),d0
	ext.w	d0
	lsl.w	#3,d0
	add.w	#16,d0
	add.w	d0,a1			; the left group's first word
	moveq	#0,d7
	move.b	R_LN(a2),d7
	subq.w	#1,d7
	move.b	R_GS(a2),d0
	cmp.b	#3,d0
	bne.s	.one
.both:
	movem.l	(a0)+,d0-d5
	and.l	d0,(a1)
	or.l	d1,(a1)+
	and.l	d0,(a1)
	or.l	d2,(a1)+
	and.l	d3,(a1)
	or.l	d4,(a1)+
	and.l	d3,(a1)
	or.l	d5,(a1)
	lea	STRIDE-12(a1),a1
	dbf	d7,.both
	rts
.one:
	cmp.b	#1,d0
	beq.s	.left
	lea	12(a0),a0		; the right group only
	addq.l	#8,a1
.left:
	movem.l	(a0)+,d0-d2
	lea	12(a0),a0
	and.l	d0,(a1)
	or.l	d1,(a1)+
	and.l	d0,(a1)
	or.l	d2,(a1)
	lea	STRIDE-4(a1),a1
	dbf	d7,.left
	rts

; ------------------------------------------------------------------------------
	section bss,bss
	ifd SIM
sim_sr_frames:	ds.l	1		; (tools/profile.py: frames the sprite renderer drew)
sim_sr_maps:	ds.l	1		; (... the column maps built, refused)
sim_sr_cannot:	ds.l	1
sim_c_bake:	ds.l	1
sim_c_draw:	ds.l	1
	endc
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
sr_chg:		ds.w	SR_ROWS
sr_draw:	ds.w	SR_ROWS
sr_stale:	ds.w	3*SR_ROWS	; per screen: the blocks it lacks (the sets drawn since it was drawn)
sr_s1:		ds.w	SR_ROWS
sr_tmp:		ds.w	SR_ROWS
sr_any:		ds.w	SR_ROWS
sr_gen:		ds.b	16
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
