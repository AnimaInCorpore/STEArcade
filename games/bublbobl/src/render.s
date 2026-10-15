; ------------------------------------------------------------------------------
; The renderer.
;
; The arcade draws a list of "objects" (oram $DD00-$DFFF, 4 bytes each: y, tile page, x, flags);
; an object is a strip of 8 x 8 tiles whose shape comes from a PROM (up to 32 rows of 2 tiles,
; columns chained across objects), the tile numbers and colour banks are in the video RAM
; ($C000-$DCFF, 2 bytes per tile).  Objects are drawn in list order, pen 15 is transparent, the
; background is palette entry 255.  See bublbobl.py render_raw.
;
; The STE shows 16 colours: the 15 most used colours of the banks in use are kept (index 0 =
; the background), everything else maps to the nearest of them (rf_palette).  A tile is baked
; per (code, bank, flips) into planar rows (data + inverted mask) and cached (tcache); an aligned
; tile is one movep.l per row, an unaligned one is shifted into two cells.
;
; The game area is 256 x 224 at screen pixel 32, game row y is buffer line y + YPAD; the
; buffer has room for the whole 256 rows and the tiles that hang over.
; ------------------------------------------------------------------------------

	ifnd DYNPAL			; (-D DYNPAL=1: the colours chosen per picture, as before 2026-10-10)
STATICPAL = 1				; the fixed palette (rf_palette)
	endc
YPAD = 10
BUF_LINES = 280
SCREEN_SIZE = STRIDE*BUF_LINES
CROP_TOP = 0

; The renderer reads the video RAM (G_VRAM) and the palette RAM (G_PAL) from copies that
; rf_vdiff / rf_palette bring up to date at the start of a frame (the game goes on while a frame
; is drawn); the live object RAM is read by rf_objects, which keeps its own record per object.
G_VRAM = snap_vram			; $C000
G_PAL = pal_shadow			; $F800
S_VRAM = g_ram+$4000
S_ORAM = g_ram+$5D00
S_PAL = g_ram+$7800

WCAP = 8
VOLMIN = 4				; a palette entry that changed this often is volatile (flashing)
VIDLE = 48				; (STATICPAL) palette changes without one of its own: a flashing entry gives its colour back
TC_SIZE = 4096				; tile cache slots
TC_ENTRY = 72				; key.l, stamp.w, opaque.w, 8 rows of (data.l, inverted mask.l)

; rf_map2 = stale if the object a3 is outside the moving range (its tiles are in the composites)
stale_if_static	macro
	clr.l	rf_map2
	cmp.b	#1,O_LAYER(a3)
	beq.s	.m\@
	move.l	#stale,rf_map2
.m\@:
	endm

; ---- the per-cell macros of the composites (inline in each_cell: keep d0-d2, d5, a0, a1, a3)

; for each cell of the bitmap \1: a4 = its screen byte (from a1 = the screen's first game cell), d4 = its
; offset in a composite table (cell * 32), then \3 (inline: keeps d0-d2, d5, a0, a1, a3)
each_cell	macro
	lea	\1,a0
	moveq	#28-1,d0		; rows to go
	moveq	#0,d5			; the row's first cell * 32
.row\@:
	move.l	(a0)+,d2
	beq	.skip\@
	moveq	#0,d1			; the column
.cell\@:
	btst	d1,d2
	beq	.no\@
	move.w	d1,d4
	lsr.w	#1,d4
	lsl.w	#3,d4
	btst	#0,d1
	beq.s	.even\@
	addq.w	#1,d4
.even\@:
	lea	(a1,d4.w),a4
	move.w	d1,d4
	lsl.w	#5,d4
	add.w	d5,d4
	\3
.no\@:
	addq.w	#1,d1
	cmp.w	#32,d1
	blo	.cell\@
.skip\@:
	lea	8*STRIDE(a1),a1
	add.w	#32*32,d5
	dbf	d0,.row\@
	endm

cap	macro				; \1 = the table: 8 lines of the cell at a4 -> \1 + d4
	lea	\1,a5
	add.w	d4,a5
o	set	0
	rept 8
	movep.l	o(a4),d7
	move.l	d7,(a5)+
o	set	o+STRIDE
	endr
	endm
cap_b	macro
	cap	comp_B
	endm
cap_s	macro
	cap	comp_S
	endm
cap_k	macro
	cap	comp_K
	endm
; the cell on colour 15 against the one on black (comp_K): the pixels where all four planes agree are
; opaque; comp_K = that mask in all four planes, kany = a pixel of it is
cap_kmask	macro
	lea	comp_K,a5
	add.w	d4,a5
	moveq	#0,d6
o	set	0
	rept 8
	movep.l	o(a4),d7
	move.l	d7,(a5)+
	or.b	d7,d6
o	set	o+STRIDE
	endr
	lsr.w	#5,d4
	lea	comp_kany,a5
	move.b	d6,(a5,d4.w)
	endm
cap_mask	macro
	lea	comp_K,a5
	add.w	d4,a5
	moveq	#0,d6
o	set	0
	rept 8
	movep.l	o(a4),d7
	move.l	(a5),d3
	eor.l	d3,d7			; the planes that differ
	move.l	d7,d3
	swap	d3
	or.w	d3,d7
	move.w	d7,d3
	lsr.w	#8,d3
	or.b	d3,d7
	not.b	d7			; opaque pixels
	or.b	d7,d6
	move.b	d7,d3
	lsl.w	#8,d7
	move.b	d3,d7
	move.w	d7,d3
	swap	d7
	move.w	d3,d7
	move.l	d7,(a5)+
o	set	o+STRIDE
	endr
	lsr.w	#5,d4
	lea	comp_kany,a5
	move.b	d6,(a5,d4.w)
	endm

fill_cell	macro			; comp_B where mov (its row's long in d3), else comp_S
	lea	comp_S,a5
	btst	d1,d3
	beq.s	.go\@
	lea	comp_B,a5
.go\@:
	add.w	d4,a5
o	set	0
	rept 8
	move.l	(a5)+,d7
	movep.l	d7,o(a4)
o	set	o+STRIDE
	endr
	endm
fill_row	macro			; d3 = mov's long of this row (row 27 - d0, from a3)
	moveq	#27,d3
	sub.w	d0,d3
	lsl.w	#2,d3
	move.l	(a3,d3.w),d3
	fill_cell
	endm

over_cell	macro
	move.w	d4,d3
	lsr.w	#5,d3
	lea	comp_kany,a5
	tst.b	(a5,d3.w)
	beq	.none\@
	lea	comp_K,a5
	add.w	d4,a5
	lea	comp_S,a6
	add.w	d4,a6
o	set	0
	rept 8
	move.l	(a5)+,d3		; opaque above
	move.l	(a6)+,d6
	and.l	d3,d6
	not.l	d3
	movep.l	o(a4),d7
	and.l	d3,d7
	or.l	d6,d7
	movep.l	d7,o(a4)
o	set	o+STRIDE
	endr
.none\@:
	endm
init_render:
	lea	comp_bad,a0		; (no composite is valid yet)
	lea	comp_bad_k,a1
	moveq	#28-1,d0
.bad:	move.l	#-1,(a0)+
	move.l	#-1,(a1)+
	dbf	d0,.bad
	; xin_used: the 8 shapes whose first row continues the column of the object before (the x entering)
	lea	bb_prom,a0
	lea	xin_used,a1
	moveq	#8-1,d0
.shape:
	sf	(a1)
	moveq	#0,d1
.yc:
	move.w	d1,d2
	lsr.w	#1,d2
	move.b	(a0,d2.w),d3
	btst	#3,d3
	bne.s	.skip_row
	btst	#2,d3
	sne	(a1)
	bra.s	.found
.skip_row:
	addq.w	#1,d1
	cmp.w	#32,d1
	blo.s	.yc
.found:
	addq.l	#1,a1
	lea	16(a0),a0
	dbf	d0,.shape
	st	vmark_all			; (the first frame compares the whole video RAM)
	bsr	tc_flush
	st	bank_stale
	lea	ttab,a0			; (no mapping yet: the first palette builds everything)
	moveq	#64-1,d0
.tt:	move.l	#-1,(a0)+
	dbf	d0,.tt
	; the shadow of the palette RAM differs from it: the first frame builds the mapping
	lea	pal_shadow,a0
	moveq	#127,d0
.p:	move.l	#-1,(a0)+
	dbf	d0,.p
	bra	rf_init_state

rf_init_state:
	lea	old_stale,a0
	moveq	#3*28-1,d0
.dp:	move.l	#-1,(a0)+
	dbf	d0,.dp
	lea	objs,a0
	move.w	#(192*OBJ_SIZE)/4-1,d0
.o:	clr.l	(a0)+
	dbf	d0,.o
	rts

; ------------------------------------------------------------------------------
; The frame
;
;   rf_palette    palette RAM changed: new colour mapping, tile cache flushed, everything dirty
;   rf_vdiff      video RAM against the copy: page / tile entry flags of what changed
;   rf_objects    the object records: footprints of what changed (old and new) are dirty
;   dirty |= what the other screen still lacks; closure over the shifted tiles (a tile that
;   touches a dirty cell makes all its cells dirty); the dirty cells are cleared and every
;   object's tiles on them are drawn in list order.
; ------------------------------------------------------------------------------

; bitmap ops on 28 longs: \1 op \2 -> \2 (or / and / andnot / copy)
bm_or	macro
	lea	\1,a0
	lea	\2,a1
	moveq	#28-1,d0
.l\@:	move.l	(a0)+,d1
	or.l	d1,(a1)+
	dbf	d0,.l\@
	endm
bm_copy	macro
	lea	\1,a0
	lea	\2,a1
	moveq	#28-1,d0
.l\@:	move.l	(a0)+,(a1)+
	dbf	d0,.l\@
	endm
bm_and	macro				; \3 = \1 and \2
	lea	\1,a0
	lea	\2,a1
	lea	\3,a2
	moveq	#28-1,d0
.l\@:	move.l	(a0)+,d1
	and.l	(a1)+,d1
	move.l	d1,(a2)+
	dbf	d0,.l\@
	endm
bm_andnot	macro			; \2 = \2 and not \1
	lea	\1,a0
	lea	\2,a1
	moveq	#28-1,d0
.l\@:	move.l	(a0)+,d1
	not.l	d1
	and.l	d1,(a1)+
	dbf	d0,.l\@
	endm
bm_fill	macro				; \1 = \2 (a long)
	lea	\1,a0
	moveq	#28-1,d0
.l\@:	move.l	#\2,(a0)+
	dbf	d0,.l\@
	endm

FULL_CELLS = 300			; more dirty cells than this: drawn as before, every object on them
NEED_MAX = 1000			; (off: building the composites a frame lacks pays back in the play; 96-160 draw the start of a level faster and the rest slower)

render_frame:
	move.l	draw_screen_address,rf_screen
	lea	scr_address,a0		; rf_buf = its number (0-2): what it lacks is kept per screen
	moveq	#0,d0
.bufno:	move.l	(a0)+,d1
	cmp.l	rf_screen,d1
	beq.s	.bufok
	addq.w	#1,d0
	cmp.w	#3,d0
	blo.s	.bufno
	moveq	#0,d0
.bufok:	move.w	d0,rf_buf
	bsr.s	.frame
	move.l	rf_screen,last_screen_address
	rts
.frame:
	clr.b	rf_all
	move.l	#dirty,rf_map
	clr.l	rf_map2
	clr.l	rf_fill
	sf	rf_noclear
	bsr	rf_vdiff
	bsr	rf_palette
	ifnd NOSR
	move.b	sr_active,sr_was	; the sprite renderer (srender.s) takes the frames it can
	bsr	sr_frame
	tst.w	d0
	beq	.sr_drawn
	tst.b	sr_was
	beq.s	.general
	st	rf_all			; (it drew the frames before: everything again)
.general:
	endc
	bm_fill	dirty,0
	bm_fill	stale,0
	tst.b	rf_all
	beq.s	.not_all
	bm_fill	dirty,-1		; (the palette changed: every cell of both screens)
.not_all:
	bsr	rf_objects		; (stale: the cells of changed objects outside the moving range)
	; General objects can leave whole tiles in the guards too. Restore old
	; guard background before any drawing and redraw the adjacent game cells.
	move.b #$0F,sr_has_guard	; (all four guards)
	bsr sr_guard_restore
	lea dirty,a0
	moveq #28-1,d0
.guard_damage:
	or.l #$80000001,(a0)+
	dbf d0,.guard_damage
	move.l #-1,dirty
	move.l #-1,dirty+27*4
	bsr	classify		; (comp_bad / comp_bad_k: the cells of objects that changed layer)
	bm_copy	stale,stale_k		; (shapes changed there: the masks above too; colours alone leave them)
	tst.b	rf_all
	beq.s	.colours
	bm_fill	comp_bad,-1		; every composite in new colours (the masks: once, at the start)
	tst.b	masks_valid
	bne.s	.colours
	bm_fill	comp_bad_k,-1
	st	masks_valid
.colours:
	bsr	rf_mark_banks		; (stale: the cells of static objects' tiles whose colours changed)
	bm_or	stale,comp_bad
	bm_or	stale_k,comp_bad_k
	bm_or	stale,dirty
	; This frame's changed cells (dirty).  The screen to draw also lacks the previous frame's changes
	; (old_stale); those this frame leaves alone are copied from the screen drawn last, which is complete
	; and equal to them there, the others (dirty) are drawn.
	bm_copy	dirty,dirty_raw
	bsr	closure_rect		; closure over the moving range (the composites hold the rest whole)
	lea	dirty,a0		; many cells: drawn whole, as before (the composites wait)
	moveq	#0,d2
	moveq	#28-1,d0
.count:	move.l	(a0)+,d1
.bits:	tst.l	d1
	beq.s	.counted
	move.l	d1,d3
	subq.l	#1,d3
	and.l	d3,d1
	addq.w	#1,d2
	bra.s	.bits
.counted:
	dbf	d0,.count
	ifd SIM
	add.l	d2,sim_rf_cells		; (tools/profile.py: dirty cells, whole redraws, palette changes)
	tst.b	rf_all
	beq.s	.sim_na
	addq.l	#1,sim_rf_all
.sim_na:
	endc
	sf	rf_whole
	cmp.w	#FULL_CELLS,d2
	bls.s	.composite
	ifd SIM
	addq.l	#1,sim_rf_whole
	endc
	st	rf_whole
	clr.w	rf_lo
	move.w	#191,rf_hi
	bsr	rf_closure
.composite:
	tst.b	rf_whole
	bne.s	.counted_need
	bm_and	dirty,comp_bad,need	; the composites the dirty cells lack: many, drawn whole as well
	lea	need,a0
	moveq	#0,d2
	moveq	#28-1,d0
.ncount:
	move.l	(a0)+,d1
.nbits:	tst.l	d1
	beq.s	.ncounted
	move.l	d1,d3
	subq.l	#1,d3
	and.l	d3,d1
	addq.w	#1,d2
	bra.s	.nbits
.ncounted:
	dbf	d0,.ncount
	cmp.w	#NEED_MAX,d2
	bls.s	.counted_need
	st	rf_whole
	clr.w	rf_lo
	move.w	#191,rf_hi
	move.l	#dirty,rf_map
	bsr	rf_closure
.counted_need:
	bsr	rf_copy
	lea	old_stale,a1		; the other screens lack this frame's changes (before the closure), this one nothing
	moveq	#0,d2
.st_buf:
	lea	dirty_raw,a0
	moveq	#28-1,d0
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
	tst.b	rf_whole
	beq.s	.layers
	move.l	#dirty,rf_map
	clr.w	rf_lo
	move.w	#191,rf_hi
	bsr	rf_redraw
	bra	.done
.layers:
	bm_and	dirty,comp_bad_k,need_k
	bsr	build_composites
	bsr	mov_cells		; the cells the moving range's tiles cover
	bsr	comp_fill		; dirty cells: the composite under the moving range, or the whole static picture
	move.l	#dirty,rf_map
	st	rf_noclear
	move.w	lay_lo,rf_lo
	move.w	lay_hi,rf_hi
	bsr	rf_redraw		; the moving range's tiles, in list order
	sf	rf_noclear
	bsr	comp_overlay		; the objects after it, through their mask
.done:
.sr_drawn:
	rts

; ------------------------------------------------------------------------------
; Layers.  The objects whose tiles changed within the last AGE_K renders make the moving range
; lay_lo..lay_hi (and every object between); the objects before it are composited below it, those after
; it above it, per 8 x 8 cell (comp_B: below, comp_S: below and above, comp_K: where above is opaque).
; An object that changes layer makes its cells' composites stale.
; ------------------------------------------------------------------------------

AGE_K = 8

classify:
	lea	objs,a3
	moveq	#0,d0
	move.w	#192,d1			; lo
	moveq	#-1,d2			; hi
.range:
	tst.w	O_COUNT(a3)
	beq.s	.r_next
	cmp.b	#AGE_K,O_AGE(a3)
	bhs.s	.r_next
	cmp.w	d1,d0
	bge.s	.r_hi
	move.w	d0,d1
.r_hi:
	move.w	d0,d2
.r_next:
	lea	OBJ_SIZE(a3),a3
	addq.w	#1,d0
	cmp.w	#192,d0
	blo.s	.range
	cmp.w	lay_lo,d1
	bne.s	.moved
	cmp.w	lay_hi,d2
	beq	.same			; (no object changes layer)
.moved:
	move.w	d1,lay_lo
	move.w	d2,lay_hi
	lea	objs,a3
	lea	objslots,a2
	moveq	#0,d0
.layer:
	tst.w	O_COUNT(a3)
	beq.s	.l_next
	moveq	#0,d3
	cmp.w	lay_lo,d0
	blt.s	.set
	moveq	#2,d3
	cmp.w	lay_hi,d0
	bgt.s	.set
	moveq	#1,d3
.set:
	cmp.b	O_LAYER(a3),d3
	beq.s	.l_next
	move.b	d3,O_LAYER(a3)
	movem.l	d0/a2-a3,-(sp)
	move.l	#comp_bad,rf_map	; (its cells' composites; the picture stays)
	move.l	#comp_bad_k,rf_map2
	move.w	O_COUNT(a3),d5
	move.l	a2,a0
	bsr	mark_slots
	move.l	#dirty,rf_map
	clr.l	rf_map2
	movem.l	(sp)+,d0/a2-a3
.l_next:
	lea	OBJ_SIZE(a3),a3
	lea	SLOT_BYTES(a2),a2
	addq.w	#1,d0
	cmp.w	#192,d0
	blo.s	.layer
.same:
	rts

; the cells the moving range's objects may cover -> mov (the rows x columns of each object's tiles: a
; superset, which only makes a cell take the composite below and the overlay)
mov_cells:
	lea	mov,a0
	moveq	#28-1,d0
.c:	clr.l	(a0)+
	dbf	d0,.c
	move.w	lay_hi,d6
	sub.w	lay_lo,d6
	bmi.s	.done
	move.w	lay_lo,d0
	mulu	#OBJ_SIZE,d0
	lea	objs,a3
	add.l	d0,a3
	lea	mov,a0
.obj:
	tst.w	O_COUNT(a3)
	beq.s	.next
	move.l	O_COLS(a3),d1
	move.l	O_ROWS(a3),d2
	moveq	#0,d3
.row:
	lsr.l	#1,d2
	bcc.s	.no_row
	or.l	d1,(a0,d3.w)
.no_row:
	addq.w	#4,d3
	tst.l	d2
	bne.s	.row
.next:
	lea	OBJ_SIZE(a3),a3
	dbf	d6,.obj
.done:
	rts

; The composites of the cells need (and the masks of need_k), on the canvas: below (objects 0 ..
; lay_lo-1), then above (lay_hi+1 .. 191) on it; above alone on black and on colour 15: where the two agree it
; is opaque.  They are valid then (comp_bad / comp_bad_k).
build_composites:
	lea	need,a0
	moveq	#0,d0
	moveq	#28-1,d1
.any:	or.l	(a0)+,d0
	dbf	d1,.any
	tst.l	d0
	beq	.no_b
	move.l	#need,rf_map		; (a shifted tile on a cell makes all its cells part of it)
	clr.w	rf_lo
	move.w	#191,rf_hi
	st	rf_skip
	bsr	rf_closure
	sf	rf_skip
	move.l	rf_screen,-(sp)
	move.l	#canvas,rf_screen
	clr.w	rf_lo			; below
	move.w	lay_lo,d0
	subq.w	#1,d0
	move.w	d0,rf_hi
	bsr	rf_redraw
	lea	canvas+(YPAD+16)*STRIDE+GAME_BYTES,a1
	each_cell	need,comp_B,cap_b
	st	rf_noclear		; above, on it
	bsr	set_above
	bsr	rf_redraw
	sf	rf_noclear
	lea	canvas+(YPAD+16)*STRIDE+GAME_BYTES,a1
	each_cell	need,comp_S,cap_s
	move.l	(sp)+,rf_screen
	bm_andnot	need,comp_bad
.no_b:
	lea	need_k,a0
	moveq	#0,d0
	moveq	#28-1,d1
.anyk:	or.l	(a0)+,d0
	dbf	d1,.anyk
	tst.l	d0
	beq	.no_k
	move.l	#need_k,rf_map
	clr.w	rf_lo
	move.w	#191,rf_hi
	st	rf_skip
	bsr	rf_closure
	sf	rf_skip
	move.l	rf_screen,-(sp)
	move.l	#canvas,rf_screen
	bsr	set_above
	st	rf_maskmode		; above as its opacity, on black: the mask in all four planes
	bsr	rf_redraw
	sf	rf_maskmode
	lea	canvas+(YPAD+16)*STRIDE+GAME_BYTES,a1
	each_cell	need_k,comp_K,cap_kmask
	move.l	(sp)+,rf_screen
	bm_andnot	need_k,comp_bad_k
.no_k:
	move.l	#dirty,rf_map
	rts
set_above:
	move.w	lay_hi,d0
	addq.w	#1,d0
	move.w	d0,rf_lo
	move.w	#191,rf_hi
	rts

; the dirty cells of the screen: comp_B where the moving range has tiles (mov), else comp_S
comp_fill:
	move.l	rf_screen,a1
	lea	(YPAD+16)*STRIDE+GAME_BYTES(a1),a1
	lea	mov,a3
	each_cell	dirty,comp_S,fill_row
	rts
; the dirty cells the moving range drew on: the objects above it again, through comp_K, from comp_S
comp_overlay:
	lea	dirty,a0
	lea	mov,a2
	lea	dmov,a3
	moveq	#28-1,d0
.and:	move.l	(a0)+,d1
	and.l	(a2)+,d1
	move.l	d1,(a3)+
	dbf	d0,.and
	move.l	rf_screen,a1
	lea	(YPAD+16)*STRIDE+GAME_BYTES(a1),a1
	each_cell	dmov,comp_S,over_cell
	rts

; ------------------------------------------------------------------------------
; The tiles of the banks whose colour mapping changed (bank_chg_b, set by rf_palette) are drawn again: the cells
; of every tile of the objects with such a bank are dirty.  (rf_all: everything is, nothing to find.)  The flags
; are used up here.
; ------------------------------------------------------------------------------

rf_mark_banks:
	tst.b	rf_all
	bne	.clear
	lea	bank_chg_b,a1
	moveq	#0,d1
	moveq	#16-1,d0
.any:	or.b	(a1)+,d1
	dbf	d0,.any
	tst.b	d1
	beq	.clear
	lea	objs,a3
	lea	objslots,a2
	move.w	#192-1,d6
.obj:
	move.w	O_COUNT(a3),d5
	beq	.next
	move.l	a2,a4
	subq.w	#1,d5
.slot:
	move.w	(a4)+,d0		; x
	move.w	(a4)+,d1		; y
	move.w	(a4)+,d2		; the vram offset
	addq.l	#4,a4
	lea	snap_vram,a0
	moveq	#0,d3
	move.b	1(a0,d2.w),d3
	lsr.b	#2,d3
	and.w	#15,d3			; the tile's bank
	lea	bank_chg_b,a1
	tst.b	(a1,d3.w)
	beq.s	.sn
	lea	pen_chg,a1		; ... and the tile uses a pen whose slot changed
	add.w	d3,d3
	move.w	(a1,d3.w),d3
	moveq	#0,d4
	move.b	(a0,d2.w),d4
	move.b	1(a0,d2.w),d7
	and.w	#3,d7
	lsl.w	#8,d7
	or.w	d7,d4
	moveq	#0,d7
	move.b	O_ENTRY+3(a3),d7
	and.w	#15,d7
	lsl.w	#8,d7
	lsl.w	#2,d7
	or.w	d7,d4			; the tile number
	add.w	d4,d4
	lea	bb_penmask,a1
	and.w	(a1,d4.w),d3
	beq.s	.sn
	stale_if_static
	movem.l	d5-d6/a2-a4,-(sp)
	bsr	mark_tile
	movem.l	(sp)+,d5-d6/a2-a4
	clr.l	rf_map2
.sn:
	dbf	d5,.slot
.next:
	lea	OBJ_SIZE(a3),a3
	lea	SLOT_BYTES(a2),a2
	dbf	d6,.obj
.clear:
	lea	bank_chg_b,a1
	moveq	#16-1,d0
.clr:	sf	(a1)+
	dbf	d0,.clr
	rts

; ------------------------------------------------------------------------------
; The cells the screen to draw lacks (old_stale: the changes since it was drawn) and this frame does not draw
; (not in dirty after the closure) are copied from the screen being shown, which holds the last frame
; complete: nothing changed in them since.  A cell is 8 lines of one movep.l.
; ------------------------------------------------------------------------------

rf_copy:
	move.l	rf_screen,a1
	lea	(YPAD+16)*STRIDE+GAME_BYTES(a1),a1	; the first game cell row, column 0 of the screen to draw
	move.l	last_screen_address,a2
	lea	(YPAD+16)*STRIDE+GAME_BYTES(a2),a2	; ... of the screen drawn last
	move.w	rf_buf,d0
	mulu	#28*4,d0
	lea	old_stale,a0
	add.l	d0,a0			; what this screen lacks
	lea	dirty,a3
	moveq	#28-1,d0
.row:
	move.l	(a0)+,d2
	move.l	(a3)+,d1
	not.l	d1
	and.l	d1,d2			; lacking, and not drawn
	beq	.skip_row
	moveq	#0,d3			; the cell column
.cell:
	btst	d3,d2
	beq	.nocopy
	move.w	d3,d4
	lsr.w	#1,d4
	lsl.w	#3,d4
	btst	#0,d3
	beq.s	.c_even
	addq.w	#1,d4
.c_even:
	lea	(a1,d4.w),a4
	lea	(a2,d4.w),a5
	rept 8
	movep.l	0(a5),d7
	movep.l	d7,0(a4)
	lea	STRIDE(a4),a4
	lea	STRIDE(a5),a5
	endr
.nocopy:
	addq.w	#1,d3
	cmp.w	#32,d3
	blo	.cell
.skip_row:
	lea	8*STRIDE(a1),a1
	lea	8*STRIDE(a2),a2
	dbf	d0,.row
	rts

; ------------------------------------------------------------------------------
; The video RAM: compare with the copy (G_VRAM), copy what changed, flag the pages and the tile
; entries (one bit per 2 bytes) that changed.
; ------------------------------------------------------------------------------

rf_vdiff:
	st	vdiff_busy			; (a VBL may interrupt this: logic_test.py checks the marks only outside)
	bsr.s	.diff
	sf	vdiff_busy
	rts
.diff:
	lea	page_dirty,a2			; (tile_dirty has bits only in the pages page_dirty flags: only those
	lea	tile_dirty,a3			; are cleared, four pages at a time)
	moveq	#0,d6
.c4:	tst.l	(a2,d6.w)
	beq.s	.c4n
	clr.l	(a2,d6.w)
	move.w	d6,d0
	lsl.w	#3,d0
	lea	(a3,d0.w),a0
	moveq	#0,d0
	rept 4
	move.l	d0,(a0)+
	move.l	d0,(a0)+
	endr
	cmp.w	#56,d6
	beq.s	.c4n				; (pages 56, 57: the last 16 bytes of tile_dirty)
	rept 4
	move.l	d0,(a0)+
	move.l	d0,(a0)+
	endr
.c4n:	addq.w	#4,d6
	cmp.w	#58,d6
	blo.s	.c4
	lea	bank_seen_b,a4
	lea	vmarks+$180,a5			; (the pages of C000-DCFF: the translated writers mark them, gen.VRAM_WRITERS)
	tst.b	vmark_all
	bne.s	.all
	move.w	vroll,d0			; one page a frame in turn, in case a writer is missing
	addq.w	#1,d0
	cmp.w	#58,d0
	blo.s	.roll
	moveq	#0,d0
.roll:
	move.w	d0,vroll
	st	(a5,d0.w)
	moveq	#0,d6				; the marks four at a time
.p4:	tst.l	(a5,d6.w)
	bne.s	.some
	addq.w	#4,d6
	cmp.w	#56,d6
	blo.s	.p4
	bra.s	.last
.some:	rept 4
	bsr.s	.one
	addq.w	#1,d6
	endr
	cmp.w	#56,d6
	blo.s	.p4
.last:	bsr.s	.one				; (pages 56, 57)
	addq.w	#1,d6
; page d6: compared if it is marked
.one:	tst.b	(a5,d6.w)
	beq.s	.o_none
	sf	(a5,d6.w)
	move.w	d6,d3
	lsl.w	#5,d3				; the long index
	move.w	d3,d0
	lsl.w	#2,d0
	lea	S_VRAM,a0
	lea	snap_vram,a1
	add.w	d0,a0
	add.w	d0,a1
	moveq	#32-1,d0
	bra	vcompare
.o_none:
	rts
.all:
	sf	vmark_all
	moveq	#58/2-1,d0
.clear:
	clr.w	(a5)+
	dbf	d0,.clear
	lea	S_VRAM,a0
	lea	snap_vram,a1
	move.w	#(7424/4)-1,d0
	moveq	#0,d3
; d0+1 longs from a0 (the video RAM) against a1 (the copy), d3 = the first long index: the copy brought up to
; date, the tile entries and pages that changed flagged.
vcompare:
	move.l	a0,d7			; (the first long: the index of a difference is found from a0)
.l:	cmpm.l	(a0)+,(a1)+
	dbne	d0,.l
	bne.s	.diff
	rts
.diff:
	st	bank_stale		; (a tile entry changed: the banks in use are counted again)
	move.l	-4(a0),d4
	move.l	d4,-4(a1)		; copy
	move.l	d4,d5			; the banks of the two entries (bits 2-5 of their second byte)
	swap	d5
	tst.w	d5
	beq.s	.e1
	lsr.w	#2,d5
	and.w	#15,d5
	st	(a4,d5.w)
.e1:
	move.w	d4,d5
	beq.s	.e2
	lsr.w	#2,d5
	and.w	#15,d5
	st	(a4,d5.w)
.e2:
	move.l	a0,d4			; the long's index: d3 + (a0 - 4 - the first) / 4
	sub.l	d7,d4
	lsr.w	#2,d4
	add.w	d3,d4
	subq.w	#1,d4
	move.w	d4,d1
	add.w	d1,d1			; the first tile entry (word) of the long
	move.w	d1,d2
	lsr.w	#3,d2
	bset	d1,(a3,d2.w)		; (bit number mod 8)
	addq.w	#1,d1
	move.w	d1,d2
	lsr.w	#3,d2
	bset	d1,(a3,d2.w)
	lsr.w	#5,d4			; the long index / 32 = the page (128 bytes)
	st	(a2,d4.w)
	dbf	d0,.l			; (dbne left the count as it was)
	rts

; ------------------------------------------------------------------------------
; The objects.  Per object (OBJ_SIZE bytes): xin.w (the chained x entering), the 4 bytes of the
; entry (y, shape, x, flags) as drawn last, count.w, sxend.w, colmask.l (cell columns covered),
; rowmask.l (cell rows), unaligned.w.  The slots (x.w, y.w, vram offset.w) are in objslots.
; ------------------------------------------------------------------------------

OBJ_SIZE = 24
O_XIN = 0
O_ENTRY = 2
O_COUNT = 6
O_SXEND = 8
O_COLS = 10
O_ROWS = 14
O_UNAL = 18
O_AGE = 20				; renders since the object (or one of its tiles) last changed, up to 255
O_LAYER = 21				; 0 = below the moving range, 1 = in it, 2 = above (classify)
SLOT_MAX = 64
SLOT_REC = 10
SLOT_BYTES = SLOT_MAX*SLOT_REC

rf_objects:
	lea	S_ORAM,a4
	lea	objs,a3
	lea	objslots,a2
	moveq	#0,d7			; the chained x (a word)
	move.w	#192-1,d6
.obj:
	move.l	(a4),d0
	beq	.inactive
	tst.w	O_COUNT(a3)
	beq	.changed		; it was not there
	cmp.l	O_ENTRY(a3),d0
	bne	.changed
	cmp.w	O_XIN(a3),d7
	beq.s	.xin_same
	move.l	d0,d1			; another x entering: a change only for a shape that continues the column
	swap	d1
	lsr.w	#5,d1
	and.w	#7,d1
	lea	xin_used,a0
	tst.b	(a0,d1.w)
	bne	.changed
	move.w	d7,O_XIN(a3)
.xin_same:
	; unchanged: only the tiles whose entries changed
	moveq	#0,d1
	move.b	O_ENTRY+1(a3),d1	; the shape / page number
	move.w	d1,d2
	and.w	#$1F,d2
	move.w	d1,d3
	and.w	#$A0,d3
	cmp.w	#$A0,d3
	bne.s	.pg
	or.w	#$20,d2			; (the page number: $1000 >> 7 = 32)
.pg:
	lea	page_dirty,a0
	tst.b	(a0,d2.w)
	beq	.same
	stale_if_static
	movem.l	d6-d7/a2-a4,-(sp)
	move.w	O_COUNT(a3),d5
	subq.w	#1,d5
	lea	tile_dirty,a1
.tile:
	move.w	(a2)+,d0		; x
	move.w	(a2)+,d1		; y
	move.w	(a2)+,d4		; the vram offset
	addq.l	#4,a2
	lsr.w	#1,d4
	move.w	d4,d2
	lsr.w	#3,d2
	btst	d4,(a1,d2.w)
	beq.s	.t_clean
	movem.l	d5/a1,-(sp)
	bsr	mark_tile
	movem.l	(sp)+,d5/a1
	move.l	12(sp),a0		; (the object: a3 on the stack) changed
	clr.b	O_AGE(a0)
.t_clean:
	dbf	d5,.tile
	movem.l	(sp)+,d6-d7/a2-a4
	clr.l	rf_map2
	bra.s	.same
.changed:
	stale_if_static
	clr.b	O_AGE(a3)
	move.b	#1,O_LAYER(a3)		; (a changed object is in the moving range)
	movem.l	d6-d7/a2-a4,-(sp)
	tst.w	O_COUNT(a3)		; the old tiles' cells (rows x columns)
	beq.s	.no_old
	move.l	O_COLS(a3),d1
	move.l	O_ROWS(a3),d2
	bsr	mark_rect
.no_old:
	movem.l	(sp),d6-d7/a2-a4
	move.w	d7,O_XIN(a3)
	move.l	(a4),O_ENTRY(a3)
	move.l	a2,a5
	bsr	obj_slots		; the new slots at a2; d0 = count, d7 = the x at the end
	move.w	d0,O_COUNT(a3)
	move.w	d7,O_SXEND(a3)
	move.w	d0,d5
	move.l	a2,a0
	bsr	obj_masks		; colmask, rowmask, unaligned
	move.l	d1,O_COLS(a3)
	move.l	d2,O_ROWS(a3)
	move.w	d3,O_UNAL(a3)
	bsr	mark_rect		; the new ones
	movem.l	(sp)+,d6-d7/a2-a4
	clr.l	rf_map2
	bra.s	.next_x
.same:
	addq.b	#1,O_AGE(a3)
	bcc.s	.next_x
	st	O_AGE(a3)
.next_x:
	move.w	O_SXEND(a3),d7
	add.w	#16,d7
	bra.s	.advance
.inactive:
	tst.w	O_COUNT(a3)
	beq.s	.advance
	stale_if_static
	movem.l	d6-d7/a2-a4,-(sp)
	move.l	O_COLS(a3),d1
	move.l	O_ROWS(a3),d2
	bsr	mark_rect
	movem.l	(sp)+,d6-d7/a2-a4
	clr.l	rf_map2
	clr.w	O_COUNT(a3)
	clr.l	O_ENTRY(a3)
.advance:
	addq.l	#4,a4
	lea	OBJ_SIZE(a3),a3
	lea	SLOT_BYTES(a2),a2
	dbf	d6,.obj
	rts

; d1 = columns, d2 = rows: the cells rows x columns into rf_map (and rf_map2): the tiles of an object with
; those masks, or a superset of them.  Clobbers d0, a0, a1.
mark_rect:
	move.l	rf_map,a0
	bsr.s	.one
	move.l	rf_map2,d0
	beq.s	.done
	move.l	d0,a0
.one:
	move.l	d2,d0
	move.l	a0,a1
.r:	lsr.l	#1,d0
	bcc.s	.n
	or.l	d1,(a1)
.n:	addq.l	#4,a1
	tst.l	d0
	bne.s	.r
.done:	rts

; a0 = slots, d5.w = count: the cells of every tile dirty.  Clobbers d0-d7, a0.

mark_slots:
	subq.w	#1,d5
	bmi.s	.done
.l:
	move.w	(a0)+,d0
	move.w	(a0)+,d1
	addq.l	#6,a0
	move.l	a0,-(sp)
	move.w	d5,-(sp)
	bsr	mark_tile
	move.w	(sp)+,d5
	move.l	(sp)+,a0
	dbf	d5,.l
.done:
	rts

; one cell dirty: d2 = column, d3 = row (visible cell rows 0-27), a0 = dirty; uses d6, d7

mark_cell	macro
	cmp.w	#32,d2
	bhs.s	.s\@
	cmp.w	#28,d3
	bhs.s	.s\@
	move.w	d3,d6
	lsl.w	#2,d6
	move.w	d2,d7
	lsr.w	#3,d7
	sub.w	d7,d6
	addq.w	#3,d6			; the byte of bit c in the big endian long of row r
	move.w	d2,d7
	and.w	#7,d7
	bset	d7,(a0,d6.w)
.s\@:
	endm

; d0.w = x (signed), d1.w = y (0-255): the cells of the 8 x 8 tile there dirty.  Clobbers d2-d7, a0.

mark_tile:
	move.l	rf_map,a0
	bsr.s	mark_tile_in
	move.l	rf_map2,d2
	beq.s	.one
	move.l	d2,a0
	bra.s	mark_tile_in
.one:
	rts
mark_tile_in:
	move.w	d0,d2
	asr.w	#3,d2			; cx
	move.w	d1,d3
	lsr.w	#3,d3
	subq.w	#2,d3			; the visible cell row
	move.w	d0,d4
	and.w	#7,d4			; x shift
	move.w	d1,d5
	and.w	#7,d5			; y shift
	mark_cell
	tst.w	d4
	beq.s	.nofx
	addq.w	#1,d2
	mark_cell
	subq.w	#1,d2
.nofx:
	tst.w	d5
	beq.s	.done
	addq.w	#1,d3
	mark_cell
	tst.w	d4
	beq.s	.done
	addq.w	#1,d2
	mark_cell
.done:
	rts

; a0 = slots, d5.w = count -> d1 = the cell columns covered (bit c), d2 = the cell rows (bit r),
; d3 = 1 if a tile is not aligned to the 8 x 8 cells.  Clobbers d4-d7, a0.

obj_masks:
	moveq	#0,d1
	moveq	#0,d2
	moveq	#0,d3
	subq.w	#1,d5
	bmi.s	.done
.l:
	move.w	(a0)+,d4		; x
	move.w	(a0)+,d6		; y
	addq.l	#6,a0
	move.w	d4,d7
	and.w	#7,d7			; the x shift
	or.w	d7,d3
	asr.w	#3,d4			; cx
	cmp.w	#32,d4
	bhs.s	.c2
	bset	d4,d1
.c2:
	tst.w	d7
	beq.s	.y
	addq.w	#1,d4
	cmp.w	#32,d4
	bhs.s	.y
	bset	d4,d1
.y:
	move.w	d6,d7
	and.w	#7,d7			; the y shift
	or.w	d7,d3
	lsr.w	#3,d6
	subq.w	#2,d6			; the visible cell row
	cmp.w	#28,d6
	bhs.s	.r2
	bset	d6,d2
.r2:
	tst.w	d7
	beq.s	.n
	addq.w	#1,d6
	cmp.w	#28,d6
	bhs.s	.n
	bset	d6,d2
.n:
	dbf	d5,.l
.done:
	tst.w	d3
	beq.s	.ret
	moveq	#1,d3
.ret:
	rts

; one slot record at (a5)+: x (d7), y (d3), the vram offset (d1), then the byte of the first cell of
; the tile that is on the screen in the dirty bitmap (-1: none) and its bit.  Keeps everything.

slot_rec	macro
	move.w	d7,(a5)+
	move.w	d3,(a5)+
	move.w	d1,(a5)+
	movem.l	d2/d4-d5,-(sp)
	move.w	d7,d4
	asr.w	#3,d4			; cx
	tst.w	d4
	bpl.s	.cxok\@
	addq.w	#1,d4			; (the left cell is off the screen: the next one)
.cxok\@:
	cmp.w	#32,d4
	bhs.s	.none\@
	move.w	d3,d5
	lsr.w	#3,d5
	subq.w	#2,d5			; cr
	bpl.s	.cr\@
	move.w	d3,d2			; above the screen: the next row if the tile is shifted
	and.w	#7,d2
	beq.s	.none\@
	cmp.w	#-1,d5
	bne.s	.none\@
	moveq	#0,d5
.cr\@:
	cmp.w	#28,d5
	bhs.s	.none\@
	lsl.w	#2,d5
	move.w	d4,d2
	lsr.w	#3,d2
	sub.w	d2,d5
	addq.w	#3,d5
	move.w	d5,(a5)+
	and.w	#7,d4
	move.w	d4,(a5)+
	bra.s	.done\@
.none\@:
	move.w	#-1,(a5)+
	clr.w	(a5)+
.done\@:
	movem.l	(sp)+,d2/d4-d5
	endm

; a4 = the object (4 bytes), d7.w = the x entering, a5 = where the slots go (x.w, y.w, vram
; offset.w per tile): d0.w = the count, d7.w = the x after the object's last row

obj_slots:
	moveq	#0,d1
	move.b	1(a4),d1		; the shape / page number
	move.w	d1,d2
	and.w	#$E0,d2
	lsr.w	#1,d2
	lea	bb_prom,a1
	add.w	d2,a1			; the 16 PROM entries of the shape
	move.w	d1,d2
	and.w	#$1F,d2
	lsl.w	#7,d2			; the page
	move.w	d1,d3
	and.w	#$A0,d3
	cmp.w	#$A0,d3
	bne.s	.n1
	or.w	#$1000,d2
.n1:
	moveq	#0,d3
	move.b	3(a4),d3		; attr
	moveq	#0,d4
	move.b	2(a4),d4		; the x
	btst	#6,d3
	beq.s	.n2
	sub.w	#256,d4
.n2:
	moveq	#0,d5
	move.b	(a4),d5
	neg.w	d5
	and.w	#$FF,d5			; sy
	moveq	#0,d0			; count
	moveq	#0,d6			; yc
.row:
	move.w	d6,d1
	lsr.w	#1,d1
	moveq	#0,d3
	move.b	(a1,d1.w),d3
	btst	#3,d3
	bne	.skip
	btst	#2,d3
	bne.s	.keep
	move.w	d4,d7			; a new column
.keep:
	move.w	d3,d1
	and.w	#3,d1
	lsl.w	#4,d1
	add.w	d2,d1
	move.w	d6,d3
	and.w	#7,d3
	add.w	d3,d3
	add.w	d3,d1			; the vram offset of the left tile
	move.w	d6,d3
	lsl.w	#3,d3
	add.w	d5,d3
	and.w	#$FF,d3			; y
	slot_rec			; d7 = x, d3 = y, d1 = voff -> (a5)+
	addq.w	#8,d7
	add.w	#$40,d1
	slot_rec
	subq.w	#8,d7
	addq.w	#2,d0
.skip:
	addq.w	#1,d6
	cmp.w	#32,d6
	blo	.row
	rts

; ------------------------------------------------------------------------------
; Closure: a shifted tile that touches a dirty cell makes all its cells dirty (it is drawn
; whole), repeated until nothing changes.
; ------------------------------------------------------------------------------

count_cell	macro			; d2 = column, d3 = row: d4 + 1 if on the screen, d5 + 1 if dirty
	cmp.w	#32,d2
	bhs.s	.s\@
	cmp.w	#28,d3
	bhs.s	.s\@
	addq.w	#1,d4
	move.w	d3,d6
	lsl.w	#2,d6
	move.w	d2,d7
	lsr.w	#3,d7
	sub.w	d7,d6
	addq.w	#3,d6
	move.w	d2,d7
	and.w	#7,d7
	btst	d7,(a0,d6.w)
	beq.s	.s\@
	addq.w	#1,d5
.s\@:
	endm

; d0 = x, d1 = y -> d4 = the cells of the tile that are on the screen, d5 = how many of them are
; dirty.  Clobbers d0-d3, d6, d7, a0.

tile_state:
	move.l	rf_map,a0
	moveq	#0,d4
	moveq	#0,d5
	move.w	d0,d2
	asr.w	#3,d2			; cx
	move.w	d1,d3
	lsr.w	#3,d3
	subq.w	#2,d3			; cr
	count_cell
	and.w	#7,d0
	beq.s	.nofx
	addq.w	#1,d2
	count_cell
	subq.w	#1,d2
.nofx:
	and.w	#7,d1
	beq.s	.done
	addq.w	#1,d3
	count_cell
	tst.w	d0
	beq.s	.done
	addq.w	#1,d2
	count_cell
.done:
	rts

rf_closure:
	move.w	rf_hi,d6
	sub.w	rf_lo,d6
	bmi	.none
.again:
	clr.b	rf_changed
	bsr	range_start		; a3, a2, d6 = the objects rf_lo..rf_hi
.obj:
	tst.w	O_UNAL(a3)
	beq	.next
	tst.b	rf_skip			; (the composites: not the moving range)
	beq.s	.take
	cmp.b	#1,O_LAYER(a3)
	beq	.next
.take:
	move.w	O_COUNT(a3),d1
	beq.s	.next
	move.l	d6,-(sp)
	move.l	a2,-(sp)
	move.l	a3,-(sp)
	subq.w	#1,d1
.slot:
	move.w	d1,-(sp)
	move.w	(a2)+,d0		; x
	move.w	(a2)+,d1		; y
	addq.l	#6,a2
	movem.l	d0-d1/a2,-(sp)
	bsr	tile_state
	movem.l	(sp)+,d0-d1/a2
	tst.w	d5			; some dirty but not all of them: the tile spreads
	beq.s	.clean
	cmp.w	d4,d5
	beq.s	.clean
	move.l	a2,-(sp)
	bsr	mark_tile
	move.l	(sp)+,a2
	st	rf_changed
.clean:
	move.w	(sp)+,d1
	dbf	d1,.slot
	move.l	(sp)+,a3
	move.l	(sp)+,a2
	move.l	(sp)+,d6
.next:
	lea	OBJ_SIZE(a3),a3
	lea	SLOT_BYTES(a2),a2
	dbf	d6,.obj
	tst.b	rf_changed
	bne	.again
.none:
	rts

; The closure of the moving range on dirty, by rectangles: a shifted object whose rows x columns are partly
; dirty makes them all dirty (a superset of its tiles' cells: only more cells are drawn).
closure_rect:
	move.w	lay_hi,d6
	sub.w	lay_lo,d6
	bmi	.none
	move.w	d6,d5
	move.w	lay_lo,d0
	mulu	#OBJ_SIZE,d0
	lea	objs,a2
	add.l	d0,a2
	lea	dirty,a0
.again:
	sf	rf_changed
	move.l	a2,a3
	move.w	d5,d6
.obj:
	tst.w	O_UNAL(a3)
	beq.s	.next
	tst.w	O_COUNT(a3)
	beq.s	.next
	move.l	O_COLS(a3),d1
	move.l	O_ROWS(a3),d2
	moveq	#0,d3			; some dirty
	moveq	#0,d4			; some clean
	move.l	a0,a1
.rows:
	lsr.l	#1,d2
	bcc.s	.no_row
	move.l	(a1),d0
	and.l	d1,d0
	or.l	d0,d3
	cmp.l	d1,d0
	beq.s	.no_row
	st	d4
.no_row:
	addq.l	#4,a1
	tst.l	d2
	bne.s	.rows
	tst.l	d3
	beq.s	.next
	tst.b	d4
	beq.s	.next
	move.l	O_ROWS(a3),d2		; partly dirty: all of it
	move.l	a0,a1
.fill:
	lsr.l	#1,d2
	bcc.s	.no_fill
	or.l	d1,(a1)
.no_fill:
	addq.l	#4,a1
	tst.l	d2
	bne.s	.fill
	st	rf_changed
.next:
	lea	OBJ_SIZE(a3),a3
	dbf	d6,.obj
	tst.b	rf_changed
	bne.s	.again
.none:
	rts

; a3 = objs, a2 = objslots of object rf_lo, d6 = rf_hi - rf_lo (a dbf count)
range_start:
	move.w	rf_lo,d6
	move.w	d6,d7
	mulu	#OBJ_SIZE,d7
	lea	objs,a3
	add.l	d7,a3
	move.w	d6,d7
	mulu	#SLOT_BYTES,d7
	lea	objslots,a2
	add.l	d7,a2
	neg.w	d6
	add.w	rf_hi,d6
	rts

; ------------------------------------------------------------------------------
; Redraw: clear the dirty cells, then draw every object's tiles on them in list order.
; ------------------------------------------------------------------------------

rf_redraw:
	; the columns and rows with something dirty
	move.l	rf_map,a0
	moveq	#0,d4			; the OR of the rows
	moveq	#0,d5			; the rows that are not empty
	moveq	#0,d6
	moveq	#28-1,d0
.sum:
	move.l	(a0)+,d1
	beq.s	.empty
	or.l	d1,d4
	bset	d6,d5
.empty:
	addq.w	#1,d6
	dbf	d0,.sum
	move.l	d4,rf_dcols
	move.l	d5,rf_drows
	tst.l	d4
	beq	.nothing

	; clear (rf_fill: 0 or -1)
	tst.b	rf_noclear
	bne	.draw
	move.l	rf_screen,a1
	lea	(YPAD+16)*STRIDE+GAME_BYTES(a1),a1	; the first game cell row, column 0
	move.l	rf_map,a0
	move.l	rf_fill,d1
	moveq	#28-1,d0
.row:
	move.l	(a0)+,d2
	beq.s	.skip_row
	move.l	a1,a3
	moveq	#0,d3			; the cell column
.cell:
	btst	d3,d2
	beq.s	.noclear
	move.w	d3,d4
	lsr.w	#1,d4
	lsl.w	#3,d4
	btst	#0,d3
	beq.s	.c_even
	addq.w	#1,d4
.c_even:
	lea	(a1,d4.w),a4
	rept 8
	movep.l	d1,0(a4)
	lea	STRIDE(a4),a4
	endr
.noclear:
	addq.w	#1,d3
	cmp.w	#32,d3
	blo.s	.cell
.skip_row:
	lea	8*STRIDE(a1),a1
	dbf	d0,.row

	; draw
.draw:
	move.w	rf_hi,d6
	sub.w	rf_lo,d6
	bmi	.nothing
	bsr	range_start
.obj:
	move.w	O_COUNT(a3),d1
	beq	.nextobj
	move.l	O_COLS(a3),d2
	and.l	rf_dcols,d2
	beq	.nextobj
	move.l	O_ROWS(a3),d2
	and.l	rf_drows,d2
	beq	.nextobj
	movem.l	d6/a2-a3,-(sp)
	moveq	#0,d3
	move.b	O_ENTRY+3(a3),d3	; attr: the tile number's high bits
	and.w	#$0F,d3
	moveq	#10,d4
	lsl.w	d4,d3
	move.w	d3,rf_attrhi
	subq.w	#1,d1
	move.l	rf_map,a0
.slot:
	move.w	6(a2),d4		; the byte of the tile's first cell in the dirty bitmap
	bmi.s	.next
	move.w	8(a2),d5
	btst	d5,(a0,d4.w)
	beq.s	.next
	movem.l	d1/a2,-(sp)
	move.w	(a2)+,d0		; x
	move.w	(a2)+,d1		; y
	move.w	(a2)+,d2		; the vram offset
	move.w	rf_attrhi,d3
	bsr	draw_tile
	movem.l	(sp)+,d1/a2
	move.l	rf_map,a0
.next:
	lea	SLOT_REC(a2),a2
	dbf	d1,.slot
	movem.l	(sp)+,d6/a2-a3
.nextobj:
	lea	OBJ_SIZE(a3),a3
	lea	SLOT_BYTES(a2),a2
	dbf	d6,.obj
.nothing:
	rts

; ------------------------------------------------------------------------------
; One tile.  d0.w = x (signed), d1.w = y (0-255), d2.w = the vram offset, d3.w = the tile number's
; high bits (attr & 15) << 10.  Draws into rf_screen.  Keeps nothing but a5-a6 / sp.
; ------------------------------------------------------------------------------

draw_tile:
	cmp.w	#-7,d0
	blt	.out
	cmp.w	#255,d0
	bgt	.out
	cmp.w	#9,d1
	blt	.out
	cmp.w	#239,d1
	bgt	.out
	lea	G_VRAM,a0
	moveq	#0,d4
	moveq	#0,d5
	move.b	(a0,d2.w),d4
	move.b	1(a0,d2.w),d5
	move.w	d5,d6
	and.w	#3,d6
	lsl.w	#8,d6
	or.w	d6,d4
	or.w	d3,d4			; the tile number (14 bits)
	lea	bb_blank,a0		; blank tiles are not drawn
	move.w	d4,d6
	lsr.w	#3,d6
	move.b	(a0,d6.w),d7
	move.w	d4,d6
	and.w	#7,d6
	btst	d6,d7
	bne	.out
	moveq	#0,d6
	move.b	d5,d6
	lsr.b	#2,d6
	and.l	#15,d6			; the bank
	moveq	#14,d7
	lsl.l	d7,d6
	or.l	d6,d4
	moveq	#0,d6
	move.b	d5,d6
	lsr.b	#6,d6			; flips: bit 0 = x, bit 1 = y
	moveq	#18,d7
	lsl.l	d7,d6
	or.l	d6,d4			; the key
	movem.l	d0-d1,-(sp)
	bsr	get_tile		; a0 = the cache entry
	movem.l	(sp)+,d0-d1
	tst.b	rf_maskmode		; (the composites' masks: the tile's opacity as its pixels, colour 15)
	beq	.colours
	lea	mask_entry,a1
	move.l	(a0)+,(a1)+
	move.l	(a0)+,(a1)+
	rept 8
	move.l	4(a0),d5
	not.l	d5
	move.l	d5,(a1)+
	move.l	4(a0),(a1)+
	addq.l	#8,a0
	endr
	lea	mask_entry,a0
.colours:

	; the screen address of the tile's first row
	move.w	d1,d5
	add.w	#YPAD,d5
	mulu	#STRIDE,d5
	move.l	rf_screen,a3
	add.l	d5,a3
	move.w	d0,d6
	and.w	#7,d6			; the shift
	beq	.aligned
	; unaligned: the left cell cx0 = x >> 3 (arithmetic), the right cell the next
	move.w	d0,d5
	asr.w	#3,d5			; cx0
	move.w	d5,d4
	asr.w	#1,d4
	lsl.w	#3,d4
	add.w	#GAME_BYTES,d4
	btst	#0,d5
	beq.s	.left_even
	addq.w	#1,d4
	ifd SIM
	addq.l	#1,sim_cnt_lodd
	endc
	lea	(a3,d4.w),a3		; the left cell's byte
	lea	7(a3),a4		; the right cell: the next group's first byte
	bra.s	.u_go
.left_even:
	ifd SIM
	addq.l	#1,sim_cnt_leven
	endc
	lea	(a3,d4.w),a3
	lea	1(a3),a4
.u_go:
	lea	mh_table,a6
	move.w	d6,d4
	lsl.w	#2,d4
	move.l	(a6,d4.w),d2		; MH: the high s bits of each byte
	move.l	d2,d3
	not.l	d3			; ~MH
	moveq	#8,d4
	sub.w	d6,d4			; the left shift of the right cell's part: 8 - s
	lea	8(a0),a1
	moveq	#8-1,d1
.lrow:					; the left cell: (x >> s), the high s bits transparent
	move.l	(a1)+,d0
	move.l	(a1)+,d5
	lsr.l	d6,d0
	and.l	d3,d0
	lsr.l	d6,d5
	or.l	d2,d5
	movep.l	0(a3),d7
	and.l	d5,d7
	or.l	d0,d7
	movep.l	d7,0(a3)
	lea	STRIDE(a3),a3
	dbf	d1,.lrow
	lea	8(a0),a1
	moveq	#8-1,d1
.rrow:					; the right cell: (x << (8 - s)), the low 8 - s bits transparent
	move.l	(a1)+,d0
	move.l	(a1)+,d5
	lsl.l	d4,d0
	and.l	d2,d0
	lsl.l	d4,d5
	or.l	d3,d5
	movep.l	0(a4),d7
	and.l	d5,d7
	or.l	d0,d7
	movep.l	d7,0(a4)
	lea	STRIDE(a4),a4
	dbf	d1,.rrow
.out:
	rts

.aligned:				; x is a multiple of 8, not below 0
	move.w	d0,d5
	lsr.w	#4,d5
	lsl.w	#3,d5
	add.w	#GAME_BYTES,d5
	btst	#3,d0
	beq.s	.a_even
	addq.w	#1,d5
.a_even:
	lea	(a3,d5.w),a3
	lea	8(a0),a1
	moveq	#8-1,d1
	tst.w	6(a0)			; (the opaque flag; the high word is the palette stamp)
	bne.s	.opaque
.arow:
	ifd SIM
	addq.l	#1,sim_cnt_arows
	endc
	move.l	(a1)+,d0
	move.l	(a1)+,d5
	movep.l	0(a3),d7
	and.l	d5,d7
	or.l	d0,d7
	movep.l	d7,0(a3)
	lea	STRIDE(a3),a3
	dbf	d1,.arow
	rts
.opaque:
	ifd SIM
	addq.l	#1,sim_cnt_orows
	endc
	move.l	(a1)+,d0
	addq.l	#4,a1
	movep.l	d0,0(a3)
	lea	STRIDE(a3),a3
	dbf	d1,.opaque
	rts

; ------------------------------------------------------------------------------
; The tile cache.  d4 = the key (tile number | bank << 14 | flip x << 18 | flip y << 19)
; -> a0 = the baked entry.  Clobbers d2-d7, a1-a3, a5, a6.
; ------------------------------------------------------------------------------

get_tile:
	move.l	d4,d5
	lsr.l	#7,d5
	eor.l	d4,d5
	move.l	d4,d6
	moveq	#13,d7
	lsr.l	d7,d6
	eor.l	d6,d5
	and.l	#TC_SIZE-1,d5
	move.l	d5,d6
	lsl.l	#3,d6
	lsl.l	#6,d5
	add.l	d6,d5			; * 72
	lea	tcache,a0
	add.l	d5,a0
	cmp.l	(a0),d4
	bne.s	.bake
	move.w	4(a0),d5		; baked under the current colour mapping?
	cmp.w	pal_epoch,d5
	bne.s	.stamp
.hit:
	rts
.stamp:					; a pen of the tile's bank changed slot since: is it one the tile uses?
	move.l	d4,d6
	moveq	#14,d7
	lsr.l	d7,d6
	and.w	#15,d6			; the bank
	add.w	d6,d6
	lea	bank_epoch,a1
	cmp.w	(a1,d6.w),d5
	bhs.s	.valid			; (no pen of the bank changed since)
	move.w	d4,d7
	and.w	#$3FFF,d7
	add.w	d7,d7
	lea	bb_penmask,a1
	move.w	(a1,d7.w),d7		; the pens the tile uses
	lsl.w	#4,d6			; the bank * 32: its 16 pens' epochs
	lea	pen_epoch,a1
	add.w	d6,a1
.pens:	lsr.w	#1,d7
	bcc.s	.pn
	cmp.w	(a1),d5
	blo.s	.bake			; (a pen it uses changed slot after it was baked)
.pn:	addq.l	#2,a1
	tst.w	d7
	bne.s	.pens
.valid:
	move.w	pal_epoch,4(a0)
	rts
.bake:
	move.l	a0,-(sp)		; (the bake walks a0 through the entry)
	bsr	tc_bake
	move.l	(sp)+,a0
	rts

; one pixel pair byte of a row: \1 = the source byte, \2 = the shift; accumulates the data in d1 and
; the transparency pairs in d4 (the tables of the tile's bank: a3 = data longs, a2 = mask bytes)

bake_px	macro
	moveq	#0,d2
	move.b	\1(a1),d2
	ifd FLIPX
	move.b	(a6,d2.w),d2		; swap the two pixels
	endc
	move.b	(a2,d2.w),d5
	lsl.w	#2,d2
	move.l	(a3,d2.w),d6
	ifne \2
	lsl.l	#\2,d6
	lsl.b	#\2,d5
	endc
	or.l	d6,d1
	or.b	d5,d4
	endm

bake_finish	macro			; d1 = the data, d4.b = the transparency pairs
	moveq	#0,d5
	move.b	d4,d5
	move.w	d5,d6
	lsl.w	#8,d6
	or.w	d6,d5
	move.w	d5,d6
	swap	d5
	move.w	d6,d5			; the byte in all four bytes: transparent in every plane
	move.l	d1,(a0)+
	move.l	d5,(a0)+
	or.l	d5,d7
	lea	(a1,d3.w),a1
	endm

tc_bake:
	move.l	d4,(a0)+		; the key
	move.l	a0,a5			; the opaque flag's cell
	addq.l	#4,a0
	move.l	d4,d0
	and.l	#$3FFF,d0		; the tile number
	move.l	d4,d1
	moveq	#14,d2
	lsr.l	d2,d1
	and.l	#15,d1			; the bank
	lsl.l	#5,d0
	lea	bb_tiles,a1
	add.l	d0,a1			; the source tile: 8 rows of 4 bytes
	lsl.l	#8,d1			; bank * 256
	lea	mtab,a2
	add.l	d1,a2
	lsl.l	#2,d1
	lea	dtab,a3
	add.l	d1,a3
	lea	swapnib,a6
	moveq	#4,d3			; the source row step
	btst	#19,d4			; flip y: from the last row up
	beq.s	.nfy
	lea	28(a1),a1
	moveq	#-4,d3
.nfy:
	moveq	#0,d7			; the OR of the inverted masks
	moveq	#8-1,d0
	btst	#18,d4
	bne	.flipx
.rows:
	moveq	#0,d1
	moveq	#0,d4
	bake_px	0,6
	bake_px	1,4
	bake_px	2,2
	bake_px	3,0
	bake_finish
	dbf	d0,.rows
	bra	.done
.flipx:
FLIPX = 1
.frows:
	moveq	#0,d1
	moveq	#0,d4
	bake_px	3,6
	bake_px	2,4
	bake_px	1,2
	bake_px	0,0
	bake_finish
	dbf	d0,.frows
.done:
	moveq	#0,d1
	tst.l	d7
	bne.s	.setflag
	moveq	#1,d1			; no transparent pixel: the fast path
.setflag:
	move.w	pal_epoch,(a5)+		; (the colour mapping it was baked under)
	move.w	d1,(a5)
	rts

; ------------------------------------------------------------------------------
; The palette: when the palette RAM changed, the 15 most used colours of the banks in use
; are kept; every (bank, pen) maps to the nearest of them.  The tile cache and the bake tables
; are rebuilt, everything gets redrawn.
; ------------------------------------------------------------------------------

rf_palette:
	ifd STATICPAL
	; The fixed palette (-D STATICPAL=1, docs/palette_static.json): colour 0 the background (entry 255), 1-STAT_PENS
	; fixed, every pen maps to the nearest of them (stat_near, by its 12 bit colour).  The colours after them are lent
	; to flashing entries: an entry that changed VOLMIN times takes a free one, and its changes then only rewrite that
	; STE colour (no tile changes slot); it gives it back after VIDLE palette changes without one of its own.  A new
	; picture (16 entries or more at once) takes the lent colours back.  Only the tiles of the pens whose slot changed
	; are baked and drawn again (.banks: pen_chg).
	lea	S_PAL,a0
	lea	pal_shadow,a1
	moveq	#128-1,d0
.s_cmp:	cmpm.l	(a0)+,(a1)+
	bne.s	.s_changed
	dbf	d0,.s_cmp
	rts
.s_changed:
	addq.w	#1,pal_tick
	lea	S_PAL,a0		; the entries that changed
	lea	pal_shadow,a1
	moveq	#0,d3
	move.w	#256-1,d0
.s_cnt:	cmpm.w	(a0)+,(a1)+
	beq.s	.s_cn
	addq.w	#1,d3
.s_cn:	dbf	d0,.s_cnt
	ifd SIM
	addq.l	#1,sim_pal_chg
	add.l	d3,sim_pal_ent
	endc
	lea	ttab,a0			; the mapping as it is
	lea	ttab_new,a1
	moveq	#64-1,d0
.s_tt:	move.l	(a0)+,(a1)+
	dbf	d0,.s_tt
	sf	rf_sbulk
	cmp.w	#16,d3
	blo.s	.s_map
	st	rf_sbulk		; a new picture: the lent colours back, the counts from 0
	lea	stat_pens,a0
	lea	kept,a1
	moveq	#8-1,d0
.s_k:	move.l	(a0)+,(a1)+
	dbf	d0,.s_k
	lea	vslot_of,a0		; (vcount follows)
	moveq	#128-1,d0
.s_v:	clr.l	(a0)+
	dbf	d0,.s_v
	lea	vowner,a0
	moveq	#16-1,d0
.s_o:	move.w	#-1,(a0)+
	dbf	d0,.s_o
.s_map:
	lea	S_PAL,a2		; every changed entry (in a new picture every entry): its slot
	lea	pal_shadow,a3
	lea	ttab_new,a6
	moveq	#0,d6			; the entry
.s_e:
	move.w	(a2)+,d0
	cmp.w	(a3)+,d0
	bne.s	.s_do
	tst.b	rf_sbulk
	beq	.s_en
.s_do:
	move.w	d0,d1
	lsr.w	#4,d1
	and.w	#$FFF,d1		; the colour (r << 8 | g << 4 | b)
	move.w	d6,d2
	and.w	#15,d2
	cmp.w	#15,d2
	bne.s	.s_pen
	clr.b	(a6,d6.w)		; pen 15: transparent
	cmp.w	#255,d6
	bne	.s_en
	move.w	d1,kept			; (entry 255: the background)
	bra	.s_en
.s_pen:
	lea	vslot_of,a0
	moveq	#0,d2
	move.b	(a0,d6.w),d2
	beq.s	.s_noslot
	add.w	d2,d2			; it has a lent colour: only that is new
	lea	kept,a1
	move.w	d1,(a1,d2.w)
	lea	vlast,a1
	move.w	pal_tick,(a1,d2.w)
	bra	.s_en
.s_noslot:
	tst.b	rf_sbulk
	bne.s	.s_near
	lea	vcount,a0
	addq.b	#1,(a0,d6.w)
	bcc.s	.s_c
	st	(a0,d6.w)
.s_c:	cmp.b	#VOLMIN,(a0,d6.w)
	blo.s	.s_near
	lea	vowner,a1		; flashing: a free lent colour?
	moveq	#STAT_PENS+1,d2
.s_f:	cmp.w	#16,d2
	bhs.s	.s_near
	move.w	d2,d4
	add.w	d4,d4
	tst.w	(a1,d4.w)
	bmi.s	.s_take
	addq.w	#1,d2
	bra.s	.s_f
.s_take:
	move.w	d6,(a1,d4.w)		; its owner
	lea	vslot_of,a0
	move.b	d2,(a0,d6.w)
	lea	kept,a0
	move.w	d1,(a0,d4.w)
	lea	vlast,a0
	move.w	pal_tick,(a0,d4.w)
	move.b	d2,(a6,d6.w)		; (its pixels change slot once)
	bra.s	.s_en
.s_near:
	lea	stat_near,a0
	move.b	(a0,d1.w),(a6,d6.w)
.s_en:
	addq.w	#1,d6
	cmp.w	#256,d6
	blo	.s_e
	lea	vowner,a1		; lent colours whose entry stopped flashing: back to its nearest fixed one
	moveq	#STAT_PENS+1,d2
.s_r:	cmp.w	#16,d2
	bhs.s	.s_rd
	move.w	d2,d4
	add.w	d4,d4
	move.w	(a1,d4.w),d6
	bmi.s	.s_rn
	lea	vlast,a0
	move.w	pal_tick,d0
	sub.w	(a0,d4.w),d0
	cmp.w	#VIDLE,d0
	blo.s	.s_rn
	move.w	#-1,(a1,d4.w)
	lea	vslot_of,a0
	clr.b	(a0,d6.w)
	lea	vcount,a0
	clr.b	(a0,d6.w)
	lea	S_PAL,a0
	move.w	d6,d0
	add.w	d0,d0
	move.w	(a0,d0.w),d1
	lsr.w	#4,d1
	and.w	#$FFF,d1
	lea	stat_near,a0
	move.b	(a0,d1.w),(a6,d6.w)
.s_rn:	addq.w	#1,d2
	bra.s	.s_r
.s_rd:
	lea	S_PAL,a0
	lea	pal_shadow,a1
	moveq	#128-1,d0
.s_cp:	move.l	(a0)+,(a1)+
	dbf	d0,.s_cp
	bra	.banks
	endc
	lea	S_PAL,a0
	lea	pal_shadow,a1
	moveq	#128-1,d0
.cmp:	cmpm.l	(a0)+,(a1)+
	bne.s	.changed
	dbf	d0,.cmp
.pal_same:
	lea	bank_seen_b,a0		; the palette is the same: a bank that came into use needs a slot
	lea	bank_known_b,a1
	moveq	#16-1,d0
.nb:
	tst.b	(a0)+
	beq.s	.nbn
	tst.b	(a1)
	beq	.recompute
.nbn:
	addq.l	#1,a1
	dbf	d0,.nb
	rts
.changed:
	ifd NOCYCLE
	; colour cycling is deferred (-D NOCYCLE=1): fewer than 16 entries changed is an animation (the arcade flashes
	; a few entries; at most 14 at once in the first 1500 frames): ignored, the shadow stays as it is
	lea	S_PAL,a0
	lea	pal_shadow,a1
	moveq	#0,d3
	move.w	#256-1,d0
.cc:	move.w	(a0)+,d1
	cmp.w	(a1)+,d1
	beq.s	.ccn
	addq.w	#1,d3
.ccn:	dbf	d0,.cc
	cmp.w	#16,d3
	blo	.pal_same
	endc
	; entries that change are volatile (flashing colours keep a slot of their own, so that the
	; colour mapping does not change with them)
	lea	S_PAL,a0
	lea	pal_shadow,a1
	lea	vol,a2
	clr.b	rf_newvol
	clr.b	rf_nonvol
	move.w	#256-1,d0
.vol:
	move.w	(a0)+,d1
	cmp.w	(a1)+,d1
	beq.s	.vsame
	move.b	(a2),d2
	cmp.b	#255,d2
	beq.s	.vsame
	addq.b	#1,d2
	move.b	d2,(a2)			; (the number of changes)
	cmp.b	#VOLMIN,d2
	blo.s	.nonvol
	bne.s	.vsame
	st	rf_newvol		; ... that is flashing: it has a slot of its own from now on
	bra.s	.vsame
.nonvol:
	st	rf_nonvol		; a colour that is not flashing (yet) changed: the colour choice is done again
.vsame:
	addq.l	#1,a2
	dbf	d0,.vol
	lea	S_PAL,a0
	lea	pal_shadow,a1
	moveq	#128-1,d0
.cp:	move.l	(a0)+,(a1)+
	dbf	d0,.cp

	; only colours of entries that were volatile already changed, and the banks in use are the same:
	; the mapping stands, the colours of the slots are new
	; The colour choice is made again (.recompute) when
	;   - an entry started to flash (rf_newvol): it gets a slot of its own from now on,
	;   - a colour that is not flashing changed (rf_nonvol) and tile entries changed as well (bank_stale): a new
	;     picture, not a palette animation; with the video RAM still the changes wait for it,
	;   - a bank came into use that has no slot yet.
	; Not when only the colours of flashing entries changed, with or without the tile entries changing (every
	; frame of the play): their slots just get the new colours (.fp).
	tst.b	rf_newvol
	bne.s	.recompute
	tst.b	rf_nonvol
	beq.s	.nv_done
	tst.b	bank_stale
	bne	.recompute
.nv_done:
	lea	bank_seen_b,a0
	lea	bank_known_b,a1
	moveq	#16-1,d0
.nb2:
	tst.b	(a0)+
	beq.s	.nbn2
	tst.b	(a1)
	beq	.recompute
.nbn2:
	addq.l	#1,a1
	dbf	d0,.nb2
	lea	kept_own,a5
	lea	kept,a4
	moveq	#0,d5			; the slot
.fp:
	cmp.w	#16,d5
	bhs.s	.fp_done
	move.w	(a5)+,d0
	tst.w	d5
	beq.s	.fp_bg
	beq.s	.fp_next
	cmp.w	#$FFFF,d0
	beq.s	.fp_next
	tst.w	d0
	beq.s	.fp_next		; (shared: unchanged)
	subq.w	#1,d0			; the entry
	move.w	d0,d6
	lsr.w	#4,d6
	move.w	d0,d4
	and.w	#15,d4
	bsr	get_rgb
	move.w	d1,(a4)
	bra.s	.fp_next
.fp_bg:
	moveq	#15,d6
	moveq	#15,d4
	bsr	get_rgb
	move.w	d1,(a4)
.fp_next:
	addq.l	#2,a4
	addq.w	#1,d5
	bra.s	.fp
.fp_done:
	bsr	.write_ste
	rts
.recompute:
	lea	kept,a0			; the slots as they are: the new choice keeps every colour in its slot
	lea	kept_prev,a1
	moveq	#8-1,d0
.sv:	move.l	(a0)+,(a1)+
	dbf	d0,.sv
	lea	kept_own,a0
	lea	kept_own_prev,a1
	moveq	#8-1,d0
.sv2:	move.l	(a0)+,(a1)+
	dbf	d0,.sv2
	; the tile entries per bank (only if the video RAM changed since)
	tst.b	bank_stale
	beq	.counted
	clr.b	bank_stale
	lea	bank_cnt,a2
	moveq	#16-1,d0
.z:	clr.w	(a2)+
	dbf	d0,.z
	lea	bank_cnt,a2
	lea	G_VRAM,a0
	move.w	#3712-1,d0
.cnt:
	move.w	(a0)+,d1
	beq.s	.cn
	lsr.w	#2,d1
	and.w	#15,d1			; (the second byte of the entry holds the bank in bits 2-5)
	add.w	d1,d1
	addq.w	#1,(a2,d1.w)
.cn:	dbf	d0,.cnt
	lea	bank_cnt,a2		; the banks the mapping covers
	lea	bank_known_b,a3
	lea	bank_seen_b,a4
	moveq	#16-1,d0
.kn:	tst.w	(a2)+
	sne	d1
	move.b	d1,(a3)+
	move.b	d1,(a4)+
	dbf	d0,.kn
.counted:

	; the colours of the banks in use: ctab = (rgb, weight, owner, -); entry 0 the background
	; (palette 255); a volatile (bank, pen) is an entry of its own (owner = its number + 1), the
	; others share an entry per colour
	lea	ctab,a3
	moveq	#15,d6
	moveq	#15,d4
	bsr	get_rgb
	move.w	d1,(a3)+
	move.w	#$FFFF,(a3)+
	clr.l	(a3)+
	moveq	#1,d7
	moveq	#0,d6			; bank
.bank:
	move.w	d6,d0
	add.w	d0,d0
	lea	bank_cnt,a2
	move.w	(a2,d0.w),d5
	beq.s	.nextbank
	cmp.w	#WCAP,d5		; (a bank counts for at most this much: a few tiles of the player compete
	bls.s	.wok			; with the hundreds of the background for the 15 slots)
	moveq	#WCAP,d5
.wok:
	moveq	#0,d4			; pen 0-14
.pen:
	bsr	get_rgb
	move.w	d6,d0
	lsl.w	#4,d0
	add.w	d4,d0			; the entry number
	lea	vol,a0
	cmp.b	#VOLMIN,(a0,d0.w)
	bhs.s	.volatile
	lea	ctab,a1
	move.w	d7,d3
	subq.w	#1,d3
.search:
	tst.w	4(a1)
	bne.s	.snext
	cmp.w	(a1),d1
	beq.s	.found
.snext:
	lea	8(a1),a1
	dbf	d3,.search
	move.w	d1,(a1)			; a new colour
	move.w	d5,2(a1)
	clr.w	4(a1)
	addq.w	#1,d7
	bra.s	.pnext
.found:
	add.w	d5,2(a1)
	bra.s	.pnext
.volatile:
	lea	ctab,a1
	move.w	d7,d3
	lsl.w	#3,d3
	add.w	d3,a1
	move.w	d1,(a1)
	move.w	d5,2(a1)
	addq.w	#1,d0
	move.w	d0,4(a1)
	addq.w	#1,d7
.pnext:
	addq.w	#1,d4
	cmp.w	#15,d4
	blo	.pen
.nextbank:
	addq.w	#1,d6
	cmp.w	#16,d6
	blo	.bank

	; at most 16 colours: kept in the order they appear (the indices stay put while the colours
	; cycle); else the background, the volatile ones, and the heaviest of the rest
	lea	kept,a4
	lea	kept_own,a5
	lea	ctab,a1
	cmp.w	#16,d7
	bhi.s	.heaviest
	move.w	d7,d6
	subq.w	#1,d6
.inorder:
	move.w	(a1),(a4)+
	move.w	4(a1),(a5)+
	lea	8(a1),a1
	dbf	d6,.inorder
	moveq	#16,d3
	sub.w	d7,d3
	beq	.picked
	subq.w	#1,d3
.clr:	clr.w	(a4)+
	move.w	#$FFFF,(a5)+		; (an unused slot: never the nearest)
	dbf	d3,.clr
	bra	.picked
.heaviest:
	move.w	(a1),(a4)+
	clr.w	(a5)+
	moveq	#1,d6			; the slots so far
	lea	ctab+8,a1
	moveq	#1,d4
.vl:
	cmp.w	d7,d4
	bhs.s	.vdone
	cmp.w	#8,d6
	bhs.s	.vdone
	tst.w	4(a1)
	beq.s	.vn
	move.w	(a1),(a4)+
	move.w	4(a1),(a5)+
	addq.w	#1,d6
.vn:
	lea	8(a1),a1
	addq.w	#1,d4
	bra.s	.vl
.vdone:
.pick:
	cmp.w	#16,d6
	bhs.s	.picked
	moveq	#0,d3			; the best weight
	moveq	#0,d2			; its index
	lea	ctab+8,a1
	moveq	#1,d4
.find:
	cmp.w	d7,d4
	bhs.s	.fdone
	tst.w	4(a1)
	bne.s	.fnext
	move.w	2(a1),d0
	cmp.w	d3,d0
	bls.s	.fnext
	move.w	d0,d3
	move.w	d4,d2
.fnext:
	lea	8(a1),a1
	addq.w	#1,d4
	bra.s	.find
.fdone:
	tst.w	d2
	beq.s	.none
	lsl.w	#3,d2
	lea	ctab,a1
	move.w	(a1,d2.w),(a4)+
	clr.w	(a5)+
	clr.w	2(a1,d2.w)
	bra.s	.pnx
.none:
	clr.w	(a4)+
	move.w	#$FFFF,(a5)+
.pnx:
	addq.w	#1,d6
	bra.s	.pick
.picked:
	bsr	.stabilize

	; every (bank, pen) -> its kept colour: a volatile one its own slot, the others the nearest
	; shared slot
	lea	ttab_new,a6
	moveq	#0,d6
.mbank:
	moveq	#0,d4
.mpen:
	bsr	get_rgb			; d1 = the pen's colour
	move.w	d1,rf_rgb
	move.w	d6,d0
	lsl.w	#4,d0
	add.w	d4,d0
	addq.w	#1,d0			; entry + 1
	lea	kept_own,a5
	moveq	#0,d5
.own:
	cmp.w	(a5)+,d0
	beq.s	.found_own
	addq.w	#1,d5
	cmp.w	#16,d5
	blo.s	.own
	move.l	#$7FFFFFFF,d3
	moveq	#0,d7
	lea	kept,a1
	lea	kept_own,a5
	moveq	#0,d5
.near:
	move.w	(a1)+,d1
	tst.w	(a5)+
	bne.s	.nn			; (a volatile or unused slot)
	move.w	rf_rgb,d0
	bsr	rgb_dist
	cmp.l	d3,d0
	bhs.s	.nn
	move.l	d0,d3
	move.w	d5,d7
.nn:
	addq.w	#1,d5
	cmp.w	#16,d5
	blo.s	.near
	bra.s	.store
.found_own:
	move.w	d5,d7
.store:
	move.b	d7,(a6)+
	addq.w	#1,d4
	cmp.w	#15,d4
	blo	.mpen
	clr.b	(a6)+			; pen 15: transparent
	addq.w	#1,d6
	cmp.w	#16,d6
	blo	.mbank

	; the banks whose mapping changed (16 bytes of ttab each; bank_chg_b): only their tiles are baked and drawn
	; again.  No bank changed (the colours merely changed, or the usage did not matter): only the STE palette is
	; new, nothing is re-baked or redrawn.
.banks:
	lea	ttab_new,a0		; the pens whose slot changed, per bank (pen_chg: a word of pen bits)
	lea	ttab,a1
	lea	pen_chg,a2
	moveq	#16-1,d0
.pc_b:	moveq	#0,d1
	moveq	#0,d2
.pc_p:	move.b	(a0)+,d3
	cmp.b	(a1)+,d3
	beq.s	.pc_n
	bset	d2,d1
.pc_n:	addq.w	#1,d2
	cmp.w	#16,d2
	blo.s	.pc_p
	move.w	d1,(a2)+
	dbf	d0,.pc_b
	lea	ttab_new,a0
	lea	ttab,a1
	lea	bank_chg_b,a2
	moveq	#0,d3			; the number of banks that changed
	moveq	#0,d2			; the bank
.cb:
	sf	(a2,d2.w)
	moveq	#0,d4
	moveq	#4-1,d5
.cbl:	move.l	(a0)+,d1
	cmp.l	(a1)+,d1
	beq.s	.cbe
	moveq	#1,d4
.cbe:	dbf	d5,.cbl
	tst.w	d4
	beq.s	.cbn
	st	(a2,d2.w)
	addq.w	#1,d3
.cbn:	addq.w	#1,d2
	cmp.w	#16,d2
	blo.s	.cb
	tst.w	d3
	bne.s	.differs
	bsr	.write_ste
	rts
.differs:
	lea	ttab_new,a0
	lea	ttab,a1
	moveq	#64-1,d0
.cpt:	move.l	(a0)+,(a1)+
	dbf	d0,.cpt
	cmp.w	#16,d3
	bne.s	.partial
	st	rf_all			; (every bank: the first palette, or a new picture altogether)
.partial:
	bsr	.write_ste
	bra	.tables
.write_ste:
	lea	kept,a1
	lea	ste_pal,a2
	lea	ste_nib,a3
	moveq	#16-1,d6
.ste:
	move.w	(a1)+,d1
	move.w	d1,d2
	lsr.w	#8,d2
	and.w	#15,d2
	moveq	#0,d0
	move.b	(a3,d2.w),d0
	lsl.w	#8,d0			; red
	move.w	d1,d2
	lsr.w	#4,d2
	and.w	#15,d2
	moveq	#0,d3
	move.b	(a3,d2.w),d3
	lsl.w	#4,d3			; green
	or.w	d3,d0
	move.w	d1,d2
	and.w	#15,d2
	moveq	#0,d3
	move.b	(a3,d2.w),d3		; blue
	or.w	d3,d0
	move.w	d0,(a2)+
	dbf	d6,.ste
	st	pal_pending
	rts

; The new choice (kept / kept_own: slot 0 the background, then the colours in the order they were found; owner
; 0 = shared colour, entry + 1 = a flashing entry of its own, $FFFF = unused) is put into the slots of the choice
; before (kept_prev / kept_own_prev): a colour that was in a slot stays in it (a flashing entry by owner, a shared
; colour by value), the others take a never used slot first, then any free one.  So a new colour changes the mapping
; of the pens near it, not of everything behind it in the order.  Clobbers d0-d6, a0-a1.

.stabilize:
	lea	slot_claimed,a0
	lea	slot_placed,a1
	moveq	#16-1,d0
.sc:	clr.b	(a0)+
	clr.b	(a1)+
	dbf	d0,.sc
	lea	kept_new,a0
	lea	kept_own_new,a1
	moveq	#16-1,d0
.sn:	clr.w	(a0)+
	move.w	#$FFFF,(a1)+
	dbf	d0,.sn
	lea	kept,a0
	move.w	(a0),kept_new		; slot 0: the background
	clr.w	kept_own_new
	st	slot_claimed
	st	slot_placed
	moveq	#1,d5			; pass 1: the item of the new choice
.p1:
	move.w	d5,d0
	add.w	d0,d0
	lea	kept_own,a0
	move.w	(a0,d0.w),d1		; its owner
	cmp.w	#$FFFF,d1
	beq.s	.p1_next
	lea	kept,a0
	move.w	(a0,d0.w),d2		; its colour
	moveq	#1,d3			; the slots before
.p1_f:
	lea	slot_claimed,a0
	tst.b	(a0,d3.w)
	bne.s	.p1_n
	move.w	d3,d4
	add.w	d4,d4
	lea	kept_own_prev,a0
	cmp.w	(a0,d4.w),d1
	bne.s	.p1_n			; (the same owner)
	tst.w	d1
	bne.s	.p1_take		; a flashing entry: the owner is enough
	lea	kept_prev,a0
	cmp.w	(a0,d4.w),d2
	bne.s	.p1_n			; a shared colour: the colour as well
.p1_take:
	lea	kept_new,a0
	move.w	d2,(a0,d4.w)
	lea	kept_own_new,a0
	move.w	d1,(a0,d4.w)
	lea	slot_claimed,a0
	st	(a0,d3.w)
	lea	slot_placed,a0
	st	(a0,d5.w)
	bra.s	.p1_next
.p1_n:
	addq.w	#1,d3
	cmp.w	#16,d3
	blo.s	.p1_f
.p1_next:
	addq.w	#1,d5
	cmp.w	#16,d5
	blo	.p1
	moveq	#1,d5			; pass 2: the items that had no slot
.p2:
	lea	slot_placed,a0
	tst.b	(a0,d5.w)
	bne.s	.p2_next
	move.w	d5,d0
	add.w	d0,d0
	lea	kept_own,a0
	move.w	(a0,d0.w),d1
	cmp.w	#$FFFF,d1
	beq.s	.p2_next
	lea	kept,a0
	move.w	(a0,d0.w),d2
	moveq	#0,d6			; 0: a never used slot, 1: any free one
.p2_look:
	moveq	#1,d3
.p2_s:
	lea	slot_claimed,a0
	tst.b	(a0,d3.w)
	bne.s	.p2_sn
	tst.w	d6
	bne.s	.p2_go
	move.w	d3,d4
	add.w	d4,d4
	lea	kept_own_prev,a0
	cmp.w	#$FFFF,(a0,d4.w)
	beq.s	.p2_go
.p2_sn:
	addq.w	#1,d3
	cmp.w	#16,d3
	blo.s	.p2_s
	tst.w	d6
	bne.s	.p2_next		; (cannot happen: at most 15 items for 15 slots)
	moveq	#1,d6
	bra.s	.p2_look
.p2_go:
	move.w	d3,d4
	add.w	d4,d4
	lea	kept_new,a0
	move.w	d2,(a0,d4.w)
	lea	kept_own_new,a0
	move.w	d1,(a0,d4.w)
	lea	slot_claimed,a0
	st	(a0,d3.w)
.p2_next:
	addq.w	#1,d5
	cmp.w	#16,d5
	blo	.p2
	lea	kept_new,a0		; the stable choice is the choice
	lea	kept,a1
	moveq	#8-1,d0
.fin:	move.l	(a0)+,(a1)+
	dbf	d0,.fin
	lea	kept_own_new,a0
	lea	kept_own,a1
	moveq	#8-1,d0
.fin2:	move.l	(a0)+,(a1)+
	dbf	d0,.fin2
	rts

.tables:
	; the bake tables of the banks whose mapping changed: data = (S[hi] << 1) | S[lo], transparency pairs
	lea	ttab,a0
	lea	dtab,a1
	lea	mtab,a2
	lea	spread,a3
	lea	bank_chg_b,a4
	moveq	#0,d6			; bank
.tbank:
	tst.b	(a4,d6.w)
	beq	.tskip
	moveq	#0,d5			; v = the pixel pair
.tv:
	move.w	d5,d1
	lsr.w	#4,d1			; the high pixel's pen
	move.w	d5,d2
	and.w	#15,d2			; the low pixel's
	moveq	#0,d4			; transparency pairs
	moveq	#0,d3
	cmp.w	#15,d1
	bne.s	.h
	or.b	#2,d4
	bra.s	.hdone
.h:
	move.w	d6,d0
	lsl.w	#4,d0
	add.w	d1,d0
	move.b	(a0,d0.w),d3		; its STE index
.hdone:
	moveq	#0,d7
	cmp.w	#15,d2
	bne.s	.l
	or.b	#1,d4
	bra.s	.ldone
.l:
	move.w	d6,d0
	lsl.w	#4,d0
	add.w	d2,d0
	move.b	(a0,d0.w),d7
.ldone:
	lsl.w	#2,d3
	move.l	(a3,d3.w),d0
	add.l	d0,d0			; the high pixel's bits: the bit above the low pixel's
	lsl.w	#2,d7
	or.l	(a3,d7.w),d0
	move.w	d6,d1
	lsl.w	#8,d1
	add.w	d5,d1
	move.b	d4,(a2,d1.w)
	lsl.w	#2,d1
	move.l	d0,(a1,d1.w)
	addq.w	#1,d5
	cmp.w	#256,d5
	blo.s	.tv
.tskip:
	addq.w	#1,d6
	cmp.w	#16,d6
	blo	.tbank

	; the baked tiles of the changed banks' changed pens are stale: a new palette epoch, the pens' and their
	; banks' epochs set to it.  get_tile checks a baked tile's stamp against them (lazily: no walk of tcache).
	cmp.w	#$FFFF,pal_epoch
	bne.s	.ep_ok
	bsr	tc_flush		; (the epoch wraps: everything is baked again)
.ep_ok:
	addq.w	#1,pal_epoch
	move.w	pal_epoch,d4
	lea	pen_chg,a1
	lea	pen_epoch,a2
	lea	bank_epoch,a3
	moveq	#0,d6			; bank
.ep_bank:
	tst.b	(a4,d6.w)
	beq.s	.ep_next
	move.w	(a1),d1
	beq.s	.ep_next
	move.w	d4,(a3)
	move.l	a2,a0
.ep_pen:
	lsr.w	#1,d1
	bcc.s	.ep_pn
	move.w	d4,(a0)
	ifd SIM
	addq.l	#1,sim_tc_inval
	endc
.ep_pn:	addq.l	#2,a0
	tst.w	d1
	bne.s	.ep_pen
.ep_next:
	addq.l	#2,a1
	lea	32(a2),a2
	addq.l	#2,a3
	addq.w	#1,d6
	cmp.w	#16,d6
	blo.s	.ep_bank
	rts

; every baked tile dropped, the palette epochs from 0
tc_flush:
	lea	tcache,a0
	move.l	#TC_SIZE-1,d0
.t:	move.l	#-1,(a0)
	lea	TC_ENTRY(a0),a0
	dbf	d0,.t
	clr.w	pal_epoch
	st	pal_wrapped		; (srender.s: its caches' stamps)
	lea	pen_epoch,a0
	move.w	#(256+16)/2-1,d0	; (bank_epoch follows)
.e:	clr.l	(a0)+
	dbf	d0,.e
	rts

; d6 = bank, d4 = pen -> d1 = the colour (r << 8 | g << 4 | b); clobbers d0, d2, a0

get_rgb:
	move.w	d6,d0
	lsl.w	#4,d0
	add.w	d4,d0
	add.w	d0,d0
	lea	G_PAL,a0
	moveq	#0,d1
	move.b	(a0,d0.w),d1
	lsl.w	#4,d1
	moveq	#0,d2
	move.b	1(a0,d0.w),d2
	lsr.b	#4,d2
	or.w	d2,d1
	rts

; d0, d1 = two colours -> d0 = the squared distance; keeps everything else

rgb_dist:
	movem.l	d2-d4,-(sp)
	moveq	#0,d4
	move.w	d0,d2
	move.w	d1,d3
	lsr.w	#8,d2
	lsr.w	#8,d3
	sub.w	d3,d2
	muls	d2,d2
	add.l	d2,d4
	move.w	d0,d2
	move.w	d1,d3
	lsr.w	#4,d2
	lsr.w	#4,d3
	and.w	#15,d2
	and.w	#15,d3
	sub.w	d3,d2
	muls	d2,d2
	add.l	d2,d4
	move.w	d0,d2
	move.w	d1,d3
	and.w	#15,d2
	and.w	#15,d3
	sub.w	d3,d2
	muls	d2,d2
	add.l	d2,d4
	move.l	d4,d0
	movem.l	(sp)+,d2-d4
	rts

	section data,data
bb_prom:	incbin "bb_prom.bin"
bb_blank:	incbin "bb_blank.bin"
	even
bb_penmask:	incbin "bb_penmask.bin"
	cnop	0,4
bb_tiles:	incbin "bb_tiles.bin"
	include "bb_tables.s"
	even
	section bss,bss
	ifd SIM
sim_cnt_arows:	ds.l	1		; (tools/blit_project.py) rows drawn by the aligned / opaque / shifted paths
sim_cnt_orows:	ds.l	1
sim_cnt_leven:	ds.l	1
sim_cnt_lodd:	ds.l	1
	endc
					; (tcache: TC_SIZE * TC_ENTRY bytes, its first part in the data section: bublbobl.s)
pal_shadow:	ds.b	512
snap_vram:	ds.b	$1D00
objs:		ds.b	192*24
objslots:	ds.b	192*SLOT_BYTES
dirty:		ds.l	28
old_stale:	ds.l	3*28		; per screen: the cells it lacks (the changes since it was drawn)
rf_buf:		ds.w	1		; the number of the screen being drawn
stale:		ds.l	28		; cells whose composites are rebuilt this frame
stale_k:	ds.l	28		; (and their masks: a shape changed)
comp_bad:	ds.l	28		; cells whose composites are not valid (built when they are drawn)
comp_bad_k:	ds.l	28		; (their masks)
need:		ds.l	28
need_k:		ds.l	28
rf_whole:	ds.b	1
	even
	ifd SIM
sim_rf_cells:	ds.l	1
sim_tc_inval:	ds.l	1		; pens whose slot changed (their baked tiles are stale)
sim_pal_chg:	ds.l	1		; palette RAM changes seen
sim_pal_ent:	ds.l	1		; ... entries changed
sim_rf_whole:	ds.l	1
sim_rf_all:	ds.l	1
	endc
rf_skip:	ds.b	1
rf_maskmode:	ds.b	1
	even
mask_entry:	ds.b	TC_ENTRY
masks_valid:	ds.b	1
	even
mov:		ds.l	28		; cells the moving range's tiles cover
dmov:		ds.l	28
comp_kany:	ds.b	896
xin_used:	ds.b	8
rf_map:		ds.l	1		; the bitmap mark_tile / tile_state / rf_redraw / rf_closure work on
rf_map2:	ds.l	1		; (mark_tile: a second one, or 0)
rf_fill:	ds.l	1
rf_lo:		ds.w	1		; the objects rf_redraw / rf_closure take
rf_hi:		ds.w	1
lay_lo:		ds.w	1		; the moving range
lay_hi:		ds.w	1
rf_noclear:	ds.b	1
	even
comp_B:		ds.b	896*32
comp_S:		ds.b	896*32
comp_K:		ds.b	896*32
canvas:		ds.b	SCREEN_SIZE
	even
vmarks:	ds.b	512			; the video RAM pages written (gen.VRAM_WRITERS; tested by longs from $180)
vmark_all:	ds.b	1
vdiff_busy:	ds.b	1
	even
vroll:	ds.w	1
	even
dirty_raw:	ds.l	28
	even
page_dirty:	ds.b	64			; (tested by longs)
tile_dirty:	ds.b	464
ctab:		ds.b	2048
kept_own:	ds.w	16
vol:		ds.b	256
kept:		ds.w	16
kept_prev:	ds.w	16
kept_own_prev:	ds.w	16
kept_new:	ds.w	16
kept_own_new:	ds.w	16
slot_claimed:	ds.b	16
slot_placed:	ds.b	16
bank_chg_b:	ds.b	16
pen_chg:	ds.w	16		; per bank: the pens whose slot changed (rf_palette)
pal_wrapped:	ds.b	1
	even
pal_epoch:	ds.w	1		; the colour mapping's epoch (+1 per change of a pen's slot; tcache stamps)
pen_epoch:	ds.w	256		; per bank and pen: the epoch its slot last changed
bank_epoch:	ds.w	16		; (follows pen_epoch) per bank: the latest of its pens'
	ifd STATICPAL
vslot_of:	ds.b	256		; the lent colour of an entry (0: none)
vcount:		ds.b	256		; (follows vslot_of) its changes without one
vowner:		ds.w	16		; the entry a colour is lent to (-1: free)
vlast:		ds.w	16		; pal_tick of its last change
pal_tick:	ds.w	1		; palette changes so far
rf_sbulk:	ds.b	1
	even
	endc
ttab:		ds.b	256
ttab_new:	ds.b	256
dtab:		ds.l	16*256
mtab:		ds.b	16*256
bank_cnt:	ds.w	16
ste_pal:	ds.w	16
pal_pending:	ds.b	1
bank_stale:	ds.b	1
bank_seen_b:	ds.b	16
bank_known_b:	ds.b	16
	even
rf_screen:	ds.l	1
rf_dcols:	ds.l	1
rf_drows:	ds.l	1
rf_all:		ds.b	1
rf_newvol:	ds.b	1
rf_nonvol:	ds.b	1
rf_changed:	ds.b	1
	even
rf_rgb:		ds.w	1
rf_sxend:	ds.w	1
rf_attrhi:	ds.w	1
	section text,code
