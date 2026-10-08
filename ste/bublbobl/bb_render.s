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

TC_SIZE = 4096				; tile cache slots
TC_ENTRY = 72				; key.l, opaque.l, 8 rows of (data.l, inverted mask.l)

init_render:
	lea	tcache,a0
	move.l	#TC_SIZE-1,d0
.t:	move.l	#-1,(a0)
	lea	TC_ENTRY(a0),a0
	dbf	d0,.t
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
	lea	dirty_prev,a0
	moveq	#28-1,d0
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

render_frame:
	move.l	draw_screen_address,rf_screen
	clr.b	rf_all
	bsr	rf_vdiff
	bsr	rf_palette
	lea	dirty,a0
	moveq	#28-1,d0
.c:	clr.l	(a0)+
	dbf	d0,.c
	tst.b	rf_all
	beq.s	.not_all
	lea	dirty,a0		; (the palette changed: every cell of both screens)
	moveq	#28-1,d0
.a:	move.l	#-1,(a0)+
	dbf	d0,.a
.not_all:
	bsr	rf_objects
	; this frame's dirty cells; the screen to draw also lacks the previous frame's
	lea	dirty,a0
	lea	dirty_prev,a1
	moveq	#28-1,d0
.u:	move.l	(a0),d1
	move.l	(a1),d2
	move.l	d1,(a1)+		; (dirty_prev = this frame's)
	or.l	d2,d1
	move.l	d1,(a0)+
	dbf	d0,.u
	bsr	rf_closure
	bsr	rf_redraw
	bsr	rf_cleanup
	rts

; ------------------------------------------------------------------------------
; The video RAM: compare with the copy (G_VRAM), copy what changed, flag the pages and the tile
; entries (one bit per 2 bytes) that changed.
; ------------------------------------------------------------------------------

rf_vdiff:
	lea	page_dirty,a3
	moveq	#64/4-1,d0
.pz:	clr.l	(a3)+
	dbf	d0,.pz
	lea	tile_dirty,a3
	move.w	#(3712/32)-1,d0
.tz:	clr.l	(a3)+
	dbf	d0,.tz
	lea	S_VRAM,a0
	lea	snap_vram,a1
	lea	tile_dirty,a3
	lea	page_dirty,a2
	move.w	#(7424/4)-1,d0
	moveq	#0,d3			; the long index
.l:
	cmpm.l	(a0)+,(a1)+
	bne.s	.diff
.next:
	addq.w	#1,d3
	dbf	d0,.l
	rts
.diff:
	st	bank_stale		; (a tile entry changed: the banks in use are counted again)
	move.l	-4(a0),-4(a1)		; copy
	move.w	d3,d1
	add.w	d1,d1			; the first tile entry (word) of the long
	move.w	d1,d2
	lsr.w	#3,d2
	bset	d1,(a3,d2.w)		; (bit number mod 8)
	addq.w	#1,d1
	move.w	d1,d2
	lsr.w	#3,d2
	bset	d1,(a3,d2.w)
	move.w	d3,d1
	lsr.w	#5,d1			; the long index / 32 = the page (128 bytes)
	st	(a2,d1.w)
	bra.s	.next

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
	beq.s	.changed		; it was not there
	cmp.w	O_XIN(a3),d7
	bne.s	.changed
	cmp.l	O_ENTRY(a3),d0
	bne.s	.changed
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
.t_clean:
	dbf	d5,.tile
	movem.l	(sp)+,d6-d7/a2-a4
	bra.s	.same
.changed:
	movem.l	d6-d7/a2-a4,-(sp)
	move.w	O_COUNT(a3),d5		; the old tiles' cells
	beq.s	.no_old
	move.l	a2,a0
	bsr	mark_slots
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
	move.w	O_COUNT(a3),d5
	move.l	a2,a0
	bsr	mark_slots
	movem.l	(sp)+,d6-d7/a2-a4
.same:
	move.w	O_SXEND(a3),d7
	add.w	#16,d7
	bra.s	.advance
.inactive:
	tst.w	O_COUNT(a3)
	beq.s	.advance
	movem.l	d6-d7/a2-a4,-(sp)
	move.w	O_COUNT(a3),d5
	move.l	a2,a0
	bsr	mark_slots
	movem.l	(sp)+,d6-d7/a2-a4
	clr.w	O_COUNT(a3)
	clr.l	O_ENTRY(a3)
.advance:
	addq.l	#4,a4
	lea	OBJ_SIZE(a3),a3
	lea	SLOT_BYTES(a2),a2
	dbf	d6,.obj
	rts

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
	lea	dirty,a0
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
	lea	dirty,a0
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
.again:
	clr.b	rf_changed
	lea	objs,a3
	lea	objslots,a2
	move.w	#192-1,d6
.obj:
	tst.w	O_UNAL(a3)
	beq.s	.next
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
	rts

; ------------------------------------------------------------------------------
; Redraw: clear the dirty cells, then draw every object's tiles on them in list order.
; ------------------------------------------------------------------------------

rf_redraw:
	; the columns and rows with something dirty
	lea	dirty,a0
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

	; clear
	move.l	rf_screen,a1
	lea	(YPAD+16)*STRIDE+16(a1),a1	; the first game cell row, column 0
	lea	dirty,a0
	moveq	#0,d1
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
	lea	objs,a3
	lea	objslots,a2
	move.w	#192-1,d6
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
	lea	dirty,a0
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
	lea	dirty,a0
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

; the tiles that hang over the game area are drawn into the black bands around it: erase them

rf_cleanup:
	move.l	rf_screen,a1
	moveq	#0,d1
	move.l	d1,d2
	move.l	d1,d3
	move.l	d1,d4
	lea	(YPAD+9)*STRIDE(a1),a0		; rows 9-15
	moveq	#7-1,d0
.t:
	rept 10
	movem.l	d1-d4,(a0)
	lea	16(a0),a0
	endr
	dbf	d0,.t
	lea	(YPAD+240)*STRIDE(a1),a0	; rows 240-246
	moveq	#7-1,d0
.b:
	rept 10
	movem.l	d1-d4,(a0)
	lea	16(a0),a0
	endr
	dbf	d0,.b
	; the margins: the tiles at x < 0 and x > 248 hang into the groups next to the game area
	lea	(YPAD+16)*STRIDE+8(a1),a0
	lea	(YPAD+16)*STRIDE+144(a1),a2
	move.w	#224-1,d0
.m:	move.l	d1,(a0)
	move.l	d1,4(a0)
	move.l	d1,(a2)
	move.l	d1,4(a2)
	lea	STRIDE(a0),a0
	lea	STRIDE(a2),a2
	dbf	d0,.m
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
	add.w	#16,d4
	btst	#0,d5
	beq.s	.left_even
	addq.w	#1,d4
	lea	(a3,d4.w),a3		; the left cell's byte
	lea	7(a3),a4		; the right cell: the next group's first byte
	bra.s	.u_go
.left_even:
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
	add.w	#16,d5
	btst	#3,d0
	beq.s	.a_even
	addq.w	#1,d5
.a_even:
	lea	(a3,d5.w),a3
	lea	8(a0),a1
	moveq	#8-1,d1
	tst.l	4(a0)
	bne.s	.opaque
.arow:
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
	beq.s	.hit
	move.l	a0,-(sp)		; (the bake walks a0 through the entry)
	bsr	tc_bake
	move.l	(sp)+,a0
.hit:
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
	move.l	d1,(a5)
	rts

; ------------------------------------------------------------------------------
; The palette: when the palette RAM changed, the 15 most used colours of the banks in use
; are kept; every (bank, pen) maps to the nearest of them.  The tile cache and the bake tables
; are rebuilt, everything gets redrawn.
; ------------------------------------------------------------------------------

rf_palette:
	lea	S_PAL,a0
	lea	pal_shadow,a1
	moveq	#128-1,d0
.cmp:	cmpm.l	(a0)+,(a1)+
	bne.s	.changed
	dbf	d0,.cmp
	rts
.changed:
	; entries that change are volatile (flashing colours keep a slot of their own, so that the
	; colour mapping does not change with them)
	lea	S_PAL,a0
	lea	pal_shadow,a1
	lea	vol,a2
	clr.b	rf_newvol
	move.w	#256-1,d0
.vol:
	move.w	(a0)+,d1
	cmp.w	(a1)+,d1
	beq.s	.vsame
	tst.b	(a2)
	bne.s	.vsame
	st	(a2)
	st	rf_newvol
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
	tst.b	rf_newvol
	bne.s	.recompute
	tst.b	bank_stale
	bne.s	.recompute
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
	moveq	#0,d4			; pen 0-14
.pen:
	bsr	get_rgb
	move.w	d6,d0
	lsl.w	#4,d0
	add.w	d4,d0			; the entry number
	lea	vol,a0
	tst.b	(a0,d0.w)
	bne.s	.volatile
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

	; the same mapping as before (the colours merely changed, or the usage did not matter): only the STE
	; palette is new, nothing is re-baked or redrawn
	lea	ttab_new,a0
	lea	ttab,a1
	moveq	#64-1,d0
.same:	cmpm.l	(a0)+,(a1)+
	bne.s	.differs
	dbf	d0,.same
	bsr	.write_ste
	rts
.differs:
	lea	ttab_new,a0
	lea	ttab,a1
	moveq	#64-1,d0
.cpt:	move.l	(a0)+,(a1)+
	dbf	d0,.cpt
	st	rf_all
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

.tables:
	; the bake tables of every bank: data = (S[hi] << 1) | S[lo], transparency pairs
	lea	ttab,a0
	lea	dtab,a1
	lea	mtab,a2
	lea	spread,a3
	moveq	#0,d6			; bank
.tbank:
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
	addq.w	#1,d6
	cmp.w	#16,d6
	blo.s	.tbank

	; the baked tiles are stale
	lea	tcache,a0
	move.l	#TC_SIZE-1,d0
.flush:
	move.l	#-1,(a0)
	lea	TC_ENTRY(a0),a0
	dbf	d0,.flush
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
	cnop	0,4
bb_tiles:	incbin "bb_tiles.bin"
	include "bb_tables.s"
	even
	section bss,bss
tcache:		ds.b	TC_SIZE*TC_ENTRY
pal_shadow:	ds.b	512
snap_vram:	ds.b	$1D00
objs:		ds.b	192*24
objslots:	ds.b	192*SLOT_BYTES
dirty:		ds.l	28
dirty_prev:	ds.l	28
page_dirty:	ds.b	64
tile_dirty:	ds.b	464
ctab:		ds.b	2048
kept_own:	ds.w	16
vol:		ds.b	256
kept:		ds.w	16
ttab:		ds.b	256
ttab_new:	ds.b	256
dtab:		ds.l	16*256
mtab:		ds.b	16*256
bank_cnt:	ds.w	16
ste_pal:	ds.w	16
pal_pending:	ds.b	1
bank_stale:	ds.b	1
	even
rf_screen:	ds.l	1
rf_dcols:	ds.l	1
rf_drows:	ds.l	1
rf_all:		ds.b	1
rf_newvol:	ds.b	1
rf_changed:	ds.b	1
	even
rf_rgb:		ds.w	1
rf_sxend:	ds.w	1
rf_attrhi:	ds.w	1
	section text,code
