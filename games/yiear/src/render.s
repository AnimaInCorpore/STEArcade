; Yie Ar Kung-Fu's picture on the STE (included by yiear.s; after Mario Bros.' render.s, which came from Track & Field's).
;
; The arcade's picture is 256 x 224 (raw lines 16-239), unturned, centred in the 320-pixel screen: black side bands of
; 32 pixels (two 16-pixel groups: the picture's edges lie on group boundaries), borders open (engine/rt/borders.s,
; PIC_TOP 20, PIC_LINES 224).  One palette (ya_pal: 16 fitted colours, every pen mapped to one index: ya_pen, the
; arcade's pens 0-15 the sprites', 16-31 the tiles').
;
; The playfield (pf): the 32 x 32 tile map (256 x 256 pixels) in STE planes, 128 bytes a line, plus the first 8 lines
; again at 256-263 (a run of 8 lines from any start line lies inside).  It never scrolls and is never flipped (the
; cocktail's flip is not done).  A cell whose two video RAM bytes (attribute, code) changed against tile_vram
; (render_tiles) is drawn there, its tile converted on first use per (code, flips) into the tile cache (a long a row:
; the four planes' bytes, movep.l).
;
; Display buffers (three) of BL lines x 160 bytes: buffer line = PIC_TOP + picture line Y, screen x = 32 + X; 16 guard
; lines below the picture (and PIC_TOP above) for whole sprites.  A buffer is brought to the new picture row by row:
; tile row r (picture lines 8r-8r+7) is copied from the playfield when a cell of the row changed or the buffer was
; never drawn (one HOG pass per plane and line: 16 words, the addresses run on to the next plane), or only the
; 16-pixel groups the buffer's last sprites covered when nothing else changed in the row.  Then the sprites: the 24
; entries from the last to the first (the first on top), the rows they cover and the guard lines they reach noted for
; the buffer's next picture.
;
; Sprites (attribute and y $5000 + o, x and code $5400 + o; o = 0, 2 .. $2E): the 16 x 16 square at picture X = x,
; Y = 224 - y (+ 1 for o < $26: MAME's `sy++`), the code's bit 8 the attribute's bit 0, flip x when attribute bit 6 is
; clear (MAME inverts it), flip y bit 7, pen 0 transparent.  Baked on first use per (code, flips) into a slot of the
; sprite cache: the opaque rows in row order, each with its row offset and mask, then the rows' four plane words in that
; order (the source address runs on).  The generated path (REN_GEN, engine/sprite_programs.py,
; docs/sprite-preparation.md): per shape (code, flips; the coverage's) and shift the code draws its rows grouped by
; mask, one- or two-word passes as stefastbobs2 chooses them, the end masks and control words from a stream, from the
; slot's aligned plane words.  Shapes without code and 64 KB crossings take the row path: a row is one HOG pass (Y
; count 4: the planes; X count 2 with NFSR when shifted, 1 when not), OP 3 with the opaque pixels as end masks.
; Clipped at the picture's edges (AGENTS.md: group-aligned): across the left edge only the second word (FXSR, source X
; increment 0, the mask's second word as END1), across the right edge only the first; a sprite wholly outside is
; culled.  Top and bottom: whole into the guard lines (cleared before the buffer's next picture).

VRAM = ya_mem+$5800			; the video RAM: (attribute, code) a cell, 32 x 32 cells
SPR1 = ya_mem+$5000			; sprite RAM 1: attribute, y
SPR2 = ya_mem+$5400			; sprite RAM 2: x, code

BL = PIC_TOP+224+16			; buffer lines
LB = 160
BUFSZ = BL*LB
NBUF = 3
PIC0 = PIC_TOP*LB			; the picture's line 0 in a buffer
LEFT = 32				; the picture's left edge (screen x)
PF_LB = 128				; the playfield's bytes a line
PF_LINES = 264
TC_SLOTS = 2048				; tile cache slots (32 bytes): every (code, flips) fits
SC_SLOTS = 1024				; sprite cache slots
CODES = 512				; sprite codes (tools/assets.py CODES: the cache key is code << 2 | flip x << 1 | flip y)
SC_SIZE = 8+2+16*6+16*8+16*8		; the shape record, the aligned plane words' address, n, (row * 160, mask << 16) a row, the 4 plane words a row (the row path), the same aligned (the generated code)
	ifnd REN_GEN
REN_GEN = 1				; 1: the generated shape code (tools/assets.py sprite_programs); 0: every sprite on the row path (to measure)
	endc

B_HT = $ffff8a00
B_SXI = $ffff8a20
B_SYI = $ffff8a22
B_SRC = $ffff8a24
B_END1 = $ffff8a28
B_END2 = $ffff8a2a
B_END3 = $ffff8a2c
B_DXI = $ffff8a2e
B_DYI = $ffff8a30
B_DST = $ffff8a32
B_XC = $ffff8a36
B_YC = $ffff8a38
B_HOP = $ffff8a3a
B_OP = $ffff8a3b
B_CTRL = $ffff8a3c
B_SKEW = $ffff8a3d
FXSR = $80
NFSR = $40

	section text,code

; ======================================================================================================================
; init_render: the buffers and the playfield black, the caches empty, the palettes, the tables
; ======================================================================================================================
init_render:
	lea	buffers,a0
	move.l	#(NBUF*BUFSZ+PF_LB*PF_LINES)/16-1,d0
.clr:	clr.l	(a0)+
	clr.l	(a0)+
	clr.l	(a0)+
	clr.l	(a0)+
	subq.l	#1,d0
	bpl.s	.clr
	lea	buffers,a0
	lea	buf_base,a1
	moveq	#NBUF-1,d0
.bb:	move.l	a0,(a1)+
	add.l	#BUFSZ,a0
	dbf	d0,.bb
	move.l	a0,pf_base
	clr.w	shown_idx
	move.w	#-1,prev_idx
	clr.b	frame_ready
	lea	row_scroll,a0		; (every row drawn at the first picture of each buffer)
	move.w	#NBUF*28-1,d0
.rs:	move.w	#-1,(a0)+
	dbf	d0,.rs
	clr.l	row_dirty
	clr.l	row_dirty+4
	clr.l	row_dirty+8
	clr.l	guard_dirty
	move.w	#-1,tile_mode		; (nothing drawn yet: the first picture draws every cell)
	lea	tile_vram,a0
	move.w	#2048/4-1,d0
.tc:	clr.l	(a0)+
	dbf	d0,.tc
	lea	ya_pal,a0		; the palettes: the picture's, black around it
	lea	shown_pal,a1
	lea	black_pal,a2
	moveq	#15,d0
.pal:	move.w	(a0)+,(a1)+
	clr.w	(a2)+
	dbf	d0,.pal
	lea	line_off,a0		; picture line Y's offset (Y from -16: line_off + 64 is Y = 0)
	move.l	#PIC0-16*LB,d0
	move.w	#16+224+16-1,d1
.lo:	move.l	d0,(a0)+
	add.l	#LB,d0
	dbf	d1,.lo
	bsr	tcache_flush
	bsr	cache_flush
	; the video base: buffer 0
	move.l	buf_base,d0
	move.l	d0,-(sp)
	move.b	1(sp),$ffff8201.w
	move.b	2(sp),$ffff8203.w
	move.b	3(sp),$ffff820d.w
	addq.l	#4,sp
	rts

cache_flush:
	lea	sc_index,a0
	move.w	#CODES*4*4/16-1,d0
.c:	clr.l	(a0)+
	clr.l	(a0)+
	clr.l	(a0)+
	clr.l	(a0)+
	dbf	d0,.c
	clr.w	sc_used
	rts

tcache_flush:
	lea	tc_index,a0
	move.w	#CODES*4*2/16-1,d0
.c:	clr.l	(a0)+
	clr.l	(a0)+
	clr.l	(a0)+
	clr.l	(a0)+
	dbf	d0,.c
	clr.w	tc_used
	rts

; ======================================================================================================================
; vbl_video: the published buffer shown from the next frame on (the video base is read at the frame's start)
; ======================================================================================================================
vbl_video:
	movem.l	d0-d1/a0,-(sp)
	move.w	shown_idx,prev_idx
	moveq	#0,d1
	move.b	frame_ready,d1
	beq.s	.out
	clr.b	frame_ready
	subq.w	#1,d1
	move.w	d1,shown_idx
	add.w	d1,d1
	add.w	d1,d1
	lea	buf_base,a0
	move.l	(a0,d1.w),d0
	move.l	d0,-(sp)
	move.b	1(sp),$ffff8201.w
	move.b	2(sp),$ffff8203.w
	move.b	3(sp),$ffff820d.w
	addq.l	#4,sp
	addq.w	#1,pic_shown
.out:	movem.l	(sp)+,d0-d1/a0
	rts

; ======================================================================================================================
; render_frame: the changed cells into the playfield, then a free buffer brought to the arcade frame's picture and
; published
; ======================================================================================================================
render_frame:
	movem.l	d0-d7/a0-a6,-(sp)
	bsr	render_tiles
.snap:	move.w	shown_idx,d1		; a buffer neither shown, nor scanned out once more, nor waiting
	move.w	prev_idx,d2
	moveq	#0,d3
	move.b	frame_ready,d3
	cmp.w	shown_idx,d1
	bne.s	.snap
	subq.w	#1,d3
	moveq	#0,d0
.pick:	cmp.w	d1,d0
	beq.s	.nx
	cmp.w	d2,d0
	beq.s	.nx
	cmp.w	d3,d0
	bne.s	.got
.nx:	addq.w	#1,d0
	cmp.w	#NBUF,d0
	blo.s	.pick
	moveq	#0,d0			; (cannot happen: three buffers, at most two in use)
.got:	move.w	d0,draw_idx
	add.w	d0,d0
	add.w	d0,d0
	lea	buf_base,a0
	move.l	(a0,d0.w),draw_base
	bsr	guard_clear
	bsr	draw_rows
	bsr	draw_sprites
	move.w	draw_idx,d0
	addq.b	#1,d0
	move.b	d0,frame_ready
	addq.w	#1,pic_count
	movem.l	(sp)+,d0-d7/a0-a6
	rts

; ----------------------------------------------------------------------------------------------------------------------
; render_tiles: the playfield brought to the video RAM: every cell at the first picture, then the cells whose bytes differ
; from tile_vram.  The picture's line 0 is raw line 16 of the playfield (row_off, constant).
; ----------------------------------------------------------------------------------------------------------------------
render_tiles:
	move.w	#16,row_off
	moveq	#0,d6			; the rows changed
	tst.w	tile_mode
	bpl.s	.diff
	clr.w	tile_mode
	moveq	#0,d7
.all:	move.w	d7,-(sp)
	bsr	cell_draw
	move.w	(sp)+,d7
	addq.w	#1,d7
	cmp.w	#1024,d7
	bne.s	.all
	lea	VRAM,a0			; (what was drawn)
	lea	tile_vram,a1
	move.w	#2048/4-1,d5
.cp:	move.l	(a0)+,(a1)+
	dbf	d5,.cp
	bra.s	.done
.diff:	lea	VRAM,a0
	lea	tile_vram,a1
	moveq	#0,d7			; the cell of the long's first word
	move.w	#512-1,d5
.cmp:	move.l	(a0),d0
	cmp.l	(a1),d0
	bne.s	.chg
.nx:	addq.l	#4,a0
	addq.l	#4,a1
	addq.w	#2,d7
	dbf	d5,.cmp
	bra.s	.done
.chg:	movem.l	d5/d7/a0-a1,-(sp)
	move.w	(a0),d0
	cmp.w	(a1),d0
	beq.s	.w2
	move.w	d0,(a1)
	movem.l	d5/d7/a0-a1,-(sp)
	bsr	cell_draw
	movem.l	(sp)+,d5/d7/a0-a1
.w2:	move.w	2(a0),d0
	cmp.w	2(a1),d0
	beq.s	.wd
	move.w	d0,2(a1)
	addq.w	#1,d7
	movem.l	d5/d7/a0-a1,-(sp)
	bsr	cell_draw
	movem.l	(sp)+,d5/d7/a0-a1
.wd:	movem.l	(sp)+,d5/d7/a0-a1
	bra.s	.nx
.done:	or.l	d6,row_dirty
	or.l	d6,row_dirty+4
	or.l	d6,row_dirty+8
	rts

; cell_draw: d7.w = a video RAM cell (ty * 32 + tx): its tile drawn into the playfield, the picture rows it covers added
; to d6.  Keeps d5-d6 as it changes d6 only.
cell_draw:
	lea	VRAM,a0
	moveq	#0,d1
	move.w	d7,d0
	add.w	d0,d0
	move.b	(a0,d0.w),d3		; the attribute: bit 4 the code's bit 8, bit 6 flip y, bit 7 flip x
	move.b	1(a0,d0.w),d1		; the code's low byte
	move.b	d3,d0
	and.w	#$10,d0
	lsl.w	#4,d0
	or.w	d0,d1			; the code
	lsl.w	#2,d1			; key = code << 2 | flip x << 1 | flip y
	btst	#7,d3
	beq.s	.nx
	or.w	#2,d1
.nx:	btst	#6,d3
	beq.s	.ny
	or.w	#1,d1
.ny:	move.w	d7,d2			; the playfield cell
	move.w	d1,-(sp)
	move.w	d2,-(sp)
	; the rows: pf line l = 8 * pfrow, screen line (l - o) & 255
	move.w	d2,d0
	lsr.w	#5,d0			; pf row
	lsl.w	#3,d0
	sub.w	row_off,d0
	and.w	#255,d0			; Ys
	move.w	d0,d1
	lsr.w	#3,d1			; the first row
	cmp.w	#28,d1
	bhs.s	.r2
	bset	d1,d6
.r2:	and.w	#7,d0
	beq.s	.rd
	addq.w	#1,d1			; (and the next)
	and.w	#31,d1
	cmp.w	#28,d1
	bhs.s	.rd
	bset	d1,d6
.rd:	move.w	(sp)+,d7
	move.w	(sp)+,d2
	move.l	d6,-(sp)		; (tile_convert uses d6)
	bsr	tile_draw
	move.l	(sp)+,d6
	rts

; tile_draw: d2.w = the key (code << 6 | flip y << 5 | flip x << 4 | colour), d7.w = the playfield cell (ty * 32 + tx):
; the tile drawn there, twice when ty = 0 (the copy at lines 256-263).  d0-d5 a0-a2 used.
tile_draw:
	lea	tc_index,a0
	moveq	#0,d3
	move.w	d2,d3
	add.l	d3,d3
	move.w	(a0,d3.l),d4		; slot + 1
	bne.s	.have
	move.w	d7,-(sp)
	bsr	tile_convert		; -> d4 = slot + 1
	move.w	(sp)+,d7
.have:	subq.w	#1,d4
	and.l	#$FFFF,d4
	lsl.l	#5,d4
	lea	tc_data,a0
	add.l	d4,a0
	move.w	d7,d2			; the cell's first byte in the playfield: ty * 8 * 128 + (tx / 2) * 8 + (tx & 1)
	lsr.w	#5,d2
	mulu	#8*PF_LB,d2
	moveq	#31,d3
	and.w	d7,d3
	move.w	d3,d4
	lsr.w	#1,d4
	lsl.w	#3,d4
	add.w	d4,d2
	moveq	#1,d4
	and.w	d3,d4
	add.w	d4,d2
	move.l	pf_base,a1
	add.l	d2,a1
	movem.l	(a0),d0-d5/a2		; (rows 0-6; row 7 below)
	movep.l	d0,0(a1)
	movep.l	d1,PF_LB(a1)
	movep.l	d2,2*PF_LB(a1)
	movep.l	d3,3*PF_LB(a1)
	movep.l	d4,4*PF_LB(a1)
	movep.l	d5,5*PF_LB(a1)
	move.l	a2,d0
	movep.l	d0,6*PF_LB(a1)
	move.l	28(a0),d0
	movep.l	d0,7*PF_LB(a1)
	cmp.w	#32,d7
	bhs.s	.out
	lea	256*PF_LB(a1),a1	; row 0 again below the map
	movem.l	(a0),d0-d5/a2
	movep.l	d0,0(a1)
	movep.l	d1,PF_LB(a1)
	movep.l	d2,2*PF_LB(a1)
	movep.l	d3,3*PF_LB(a1)
	movep.l	d4,4*PF_LB(a1)
	movep.l	d5,5*PF_LB(a1)
	move.l	a2,d0
	movep.l	d0,6*PF_LB(a1)
	move.l	28(a0),d0
	movep.l	d0,7*PF_LB(a1)
.out:	rts

; tile_convert: d2.w = the key (code << 2 | flip x << 1 | flip y), d3.l = key * 2 -> d4.w = its new slot + 1, the tile's 8 rows converted there: a long a row, the planes 0-3
; from the high byte (movep.l order).  MAME's flips: x reverses the columns, y the rows.  d0-d6 a0-a2 used.
tile_convert:
	move.w	tc_used,d4
	cmp.w	#TC_SLOTS,d4
	blo.s	.room
	movem.l	d2-d3,-(sp)		; (full: all again from now on; what is drawn stays)
	bsr	tcache_flush
	movem.l	(sp)+,d2-d3
	moveq	#0,d4
.room:	addq.w	#1,d4
	move.w	d4,tc_used
	lea	tc_index,a0
	move.w	d4,(a0,d3.l)
	move.w	d4,-(sp)
	subq.w	#1,d4
	and.l	#$FFFF,d4
	lsl.l	#5,d4
	lea	tc_data,a1
	add.l	d4,a1			; the slot
	moveq	#0,d0
	move.w	d2,d0
	lsr.w	#2,d0			; the code (9 bits)
	lsl.l	#5,d0
	lea	ya_tiles,a0
	add.l	d0,a0			; its 8 rows of 4 bytes (two pens a byte)
	lea	ya_pen+16,a2		; the tiles' pens 0-15 -> colour index
	moveq	#0,d6			; the row
.row:	move.w	d6,d0
	btst	#0,d2
	beq.s	.nfy
	eor.w	#7,d0			; (flip y: the rows from the last)
.nfy:	lsl.w	#2,d0
	move.l	(a0,d0.w),d5		; the row's 8 pens, the leftmost in the top nibble
	btst	#1,d2
	beq.s	.nfx
	moveq	#0,d0			; (flip x: the nibbles reversed)
	moveq	#7,d1
.rv:	lsl.l	#4,d0
	moveq	#15,d4
	and.w	d5,d4
	or.w	d4,d0
	lsr.l	#4,d5
	dbf	d1,.rv
	move.l	d0,d5
.nfx:	moveq	#0,d0			; planes 0, 1, 2, 3 in d0's bytes from the top (shifted in, one bit a pixel)
	moveq	#7,d1
.px:	rol.l	#4,d5
	moveq	#15,d4
	and.w	d5,d4
	move.b	(a2,d4.w),d4		; the colour index
	lsl.l	#1,d0			; (each byte one bit left; the bits that cross into the next byte are cleared)
	and.l	#$FEFEFEFE,d0
	lsr.b	#1,d4
	bcc.s	.b0
	or.l	#$01000000,d0
.b0:	lsr.b	#1,d4
	bcc.s	.b1
	or.l	#$00010000,d0
.b1:	lsr.b	#1,d4
	bcc.s	.b2
	or.w	#$0100,d0
.b2:	lsr.b	#1,d4
	bcc.s	.b3
	or.w	#$0001,d0
.b3:	dbf	d1,.px
	move.l	d0,(a1)+
	addq.w	#1,d6
	cmp.w	#8,d6
	bne.s	.row
	move.w	(sp)+,d4
	rts

; ----------------------------------------------------------------------------------------------------------------------
; guard_clear: the guard lines the buffer's last sprites reached (above and below the picture), cleared (the picture's
; columns only: the sprites never reach the side bands)
; ----------------------------------------------------------------------------------------------------------------------
guard_clear:
	move.w	draw_idx,d0
	lea	guard_dirty,a0
	move.b	(a0,d0.w),d1
	beq.s	.out
	clr.b	(a0,d0.w)
	moveq	#0,d2
	moveq	#0,d3
	moveq	#0,d4
	moveq	#0,d5
	moveq	#0,d6
	moveq	#0,d7
	move.l	d2,a2
	move.l	d2,a3
	btst	#0,d1
	beq.s	.b
	move.l	draw_base,a0
	lea	PIC0-16*LB+16(a0),a0
	bsr.s	.clr16
.b:	btst	#1,d1
	beq.s	.out
	move.l	draw_base,a0
	add.l	#PIC0+224*LB+16,a0
.clr16:	moveq	#16-1,d0		; 16 lines of 128 bytes (the picture's 16 groups)
.l:	movem.l	d2-d7/a2-a3,(a0)
	movem.l	d2-d7/a2-a3,32(a0)
	movem.l	d2-d7/a2-a3,64(a0)
	movem.l	d2-d7/a2-a3,96(a0)
	lea	LB(a0),a0
	dbf	d0,.l
.out:	rts

; ----------------------------------------------------------------------------------------------------------------------
; draw_rows: the 28 visible tile rows that the buffer does not hold as the picture has them, from the playfield
; ----------------------------------------------------------------------------------------------------------------------
draw_rows:
	move.w	draw_idx,d0
	move.w	d0,d1
	add.w	d1,d1
	add.w	d1,d1
	lea	row_dirty,a0
	move.l	(a0,d1.w),d6		; the rows to draw whatever their offset
	clr.l	(a0,d1.w)
	lea	row_sdirty,a0
	move.l	(a0,d1.w),sd_rows	; the rows only the buffer's last sprites covered: their groups
	mulu	#56,d0
	lea	row_scroll,a2
	add.w	d0,a2			; the buffer's rows' offsets
	move.w	#$0203,B_HOP.w		; source, OP 3
	moveq	#-1,d0
	move.w	d0,B_END1.w
	move.w	d0,B_END2.w
	move.w	d0,B_END3.w
	move.w	#8,B_SXI.w
	move.w	#8,B_DXI.w
	move.w	#16,B_XC.w
	move.w	#2-15*8,B_DYI.w
	move.w	#2-15*8,B_SYI.w
	clr.b	B_SKEW.w
	lea	B_SRC.w,a3
	lea	B_DST.w,a4
	lea	B_YC.w,a5
	lea	B_CTRL.w,a6
	moveq	#1,d3
	moveq	#-$40,d4		; ($C0: start, HOG)
	move.w	row_off,d0		; the offset o
	moveq	#0,d7			; the row
.row:	cmp.w	(a2),d0
	bne.s	.draw
	btst	d7,d6
	bne.s	.draw
	move.l	sd_rows,d1
	btst	d7,d1
	bne	.part
	bra	.next
.draw:	move.w	d0,(a2)
	move.w	d7,d1			; the source's first line: (8 * row + o) & 255
	lsl.w	#3,d1
	add.w	d0,d1
	and.w	#255,d1
	mulu	#PF_LB,d1
	move.l	pf_base,a1
	add.l	d1,a1
	move.l	draw_base,d2
	add.l	#PIC0+16,d2
	move.w	d7,d1
	mulu	#8*LB,d1
	add.l	d1,d2			; the destination
	moveq	#8-1,d5
.line:	move.l	a1,(a3)
	move.l	d2,(a4)
	move.w	d3,(a5)			; four HOG passes of one plane (the addresses run on)
	move.b	d4,(a6)
	move.w	d3,(a5)
	move.b	d4,(a6)
	move.w	d3,(a5)
	move.b	d4,(a6)
	move.w	d3,(a5)
	move.b	d4,(a6)
	lea	PF_LB(a1),a1
	add.l	#LB,d2
	dbf	d5,.line
.next:	addq.l	#2,a2
	addq.w	#1,d7
	cmp.w	#28,d7
	bne	.row
	rts
.part:	moveq	#0,d5			; the groups g0 .. g1 of the row (row_span)
	move.b	row_span-row_scroll(a2),d5
	moveq	#0,d2
	move.b	row_span-row_scroll+1(a2),d2
	sub.w	d5,d2			; n - 1
	move.w	d2,d1
	addq.w	#1,d1
	move.w	d1,B_XC.w		; n
	lsl.w	#3,d2
	moveq	#2,d1
	sub.w	d2,d1
	move.w	d1,B_DYI.w		; 2 - (n - 1) * 8
	move.w	d1,B_SYI.w
	move.w	d7,d1			; the source's first line, its group g0
	lsl.w	#3,d1
	add.w	d0,d1
	and.w	#255,d1
	mulu	#PF_LB,d1
	move.l	pf_base,a1
	add.l	d1,a1
	lsl.w	#3,d5
	add.w	d5,a1
	move.w	d7,d1
	mulu	#8*LB,d1
	add.l	d5,d1
	move.l	draw_base,d2
	add.l	#PIC0+16,d2
	add.l	d1,d2			; the destination's group g0
	moveq	#8-1,d5
.pl:	move.l	a1,(a3)
	move.l	d2,(a4)
	move.w	d3,(a5)
	move.b	d4,(a6)
	move.w	d3,(a5)
	move.b	d4,(a6)
	move.w	d3,(a5)
	move.b	d4,(a6)
	move.w	d3,(a5)
	move.b	d4,(a6)
	lea	PF_LB(a1),a1
	add.l	#LB,d2
	dbf	d5,.pl
	move.w	#16,B_XC.w
	move.w	#2-15*8,B_DYI.w
	move.w	#2-15*8,B_SYI.w
	bra	.next

; ======================================================================================================================
; draw_sprites: the 24 entries, the last first (the first on top), each once; the rows they cover and the guard lines
; they reach noted for the buffer's next picture
; ======================================================================================================================
draw_sprites:
	clr.l	spr_rows
	clr.b	spr_guard
	move.w	draw_idx,d0
	mulu	#56,d0
	lea	row_span,a0
	add.w	d0,a0
	move.l	a0,spr_span		; (a row's span is written when a sprite first covers it)
	move.w	#-1,last_mode
	move.w	#$0203,B_HOP.w
	moveq	#$2E,d0			; the entry's offset
.e:	move.w	d0,-(sp)
	lea	SPR1,a0
	moveq	#0,d7
	move.b	(a0,d0.w),d7		; attributes
	moveq	#0,d3
	move.b	1(a0,d0.w),d3		; y
	lea	SPR2,a0
	moveq	#0,d6
	move.b	1(a0,d0.w),d6		; code, low byte
	moveq	#0,d5
	move.b	(a0,d0.w),d5		; picture X = x
	move.w	#224,d4
	sub.w	d3,d4			; picture Y = 224 - y
	cmp.w	#$26,d0
	bhs.s	.pos
	addq.w	#1,d4			; (MAME: sy++ for the first entries)
.pos:	cmp.w	#-15,d4
	blt.s	.n
	cmp.w	#223,d4
	bgt.s	.n
	btst	#0,d7			; the code's bit 8
	beq.s	.c8
	or.w	#$100,d6
.c8:	lsl.w	#2,d6			; the key: code << 2 | flip x << 1 | flip y
	btst	#6,d7
	bne.s	.fx			; (MAME: flip x when the bit is clear)
	or.w	#2,d6
.fx:	btst	#7,d7
	beq.s	.fy
	or.w	#1,d6
.fy:	move.w	d6,d2
	move.w	d5,d3			; picture X
	bsr	draw_cell
.n:	move.w	(sp)+,d0
	subq.w	#2,d0
	bpl	.e
	move.w	draw_idx,d0		; the buffer's next picture redraws what these covered
	move.w	d0,d1
	add.w	d1,d1
	add.w	d1,d1
	lea	row_sdirty,a0
	move.l	spr_rows,(a0,d1.w)
	lea	guard_dirty,a0
	move.b	spr_guard,d2
	or.b	d2,(a0,d0.w)
	rts

; draw_cell: d2 = the key, d3 = picture X, d4 = picture Y (-15 .. 223).  Culled when wholly outside the picture's
; columns; baked on a miss, clipped at the edges, drawn; the rows and guards it covers noted.
draw_cell:
	cmp.w	#-16,d3
	ble	.out
	cmp.w	#256,d3
	bge	.out
	move.w	d2,cell_key
	move.w	d3,cell_x
	move.w	d4,cell_y
	move.w	d4,d0			; the rows it covers: Y / 8 .. (Y + 15) / 8 within 0-27; the guards
	bpl.s	.r0
	bset	#0,spr_guard
	moveq	#0,d0
.r0:	move.w	d4,d1
	add.w	#15,d1
	cmp.w	#223,d1
	ble.s	.r1
	bset	#1,spr_guard
	move.w	#223,d1
.r1:	lsr.w	#3,d0
	lsr.w	#3,d1
	move.w	d3,d6			; the groups: X >> 4 .. (X + 15) >> 4 within 0-15
	asr.w	#4,d6
	bpl.s	.g0
	moveq	#0,d6
.g0:	move.w	d3,d7
	add.w	#15,d7
	asr.w	#4,d7
	cmp.w	#15,d7
	ble.s	.g1
	moveq	#15,d7
.g1:	move.l	spr_span,a1
	add.w	d0,a1
	add.w	d0,a1
	move.l	spr_rows,d5
.rb:	bset	d0,d5
	bne.s	.ru
	move.b	d6,(a1)+		; (the row's first sprite)
	move.b	d7,(a1)+
	bra.s	.rn
.ru:	cmp.b	(a1)+,d6
	bhs.s	.ru0
	move.b	d6,-1(a1)
.ru0:	cmp.b	(a1)+,d7
	bls.s	.rn
	move.b	d7,-1(a1)
.rn:	addq.w	#1,d0
	cmp.w	d1,d0
	bls.s	.rb
	move.l	d5,spr_rows
	bsr	sprite_baked		; a0 = the slot
	if REN_GEN
	; the generated path (engine/sprite_programs.py): the shape's code for the shift and clip case, the end masks
	; from its stream, the slot's aligned plane words; 64 KB crossings and shapes without code take the row path
	move.l	(a0),d6			; the shape's record (0: no generated code)
	beq	.rp
	move.w	cell_x,d3
	add.w	#LEFT,d3		; screen x
	moveq	#15,d0
	and.w	d3,d0			; the shift
	beq.s	.gin
	cmp.w	#LEFT,d3		; across a side edge: the clipped variants (one word)
	blt.s	.gcl
	cmp.w	#LEFT+256-16,d3
	blt.s	.gin
	add.w	#32,d0			; (right: clip 2, the first word only)
	bra.s	.gin
.gcl:	add.w	#16,d0			; (left: clip 1, the second word only)
.gin:	lsl.w	#2,d0			; (* 12: a variant's record)
	move.w	d0,d1
	add.w	d0,d0
	add.w	d1,d0
	add.l	d0,d6
	lsr.w	#4,d3
	lsl.w	#3,d3			; the first word's byte in the line
	move.w	cell_y,d1
	add.w	#16,d1
	add.w	d1,d1
	add.w	d1,d1
	lea	line_off,a1
	move.l	(a1,d1.w),d1
	add.w	d3,d1			; the offset in the buffer
	move.l	draw_base,d3
	add.l	d1,d3			; the destination
	cmp.w	#$FFFF-15*LB-16,d3	; (the code steps the low word: no 64 KB crossing)
	bhi.s	.rp
	move.l	d6,a3
	tst.w	10(a3)			; (the damage size: 0 nothing drawn)
	beq	.out
	move.l	d3,B_DST.w		; (the high word; the code writes the low word)
	move.l	4(a0),B_SRC.w		; (the slot's aligned plane words)
	cmp.w	#16,last_mode
	beq.s	.gset
	move.w	#16,last_mode
	clr.w	B_SXI.w			; (source X increment 0, Y increment 2: every pass type)
	move.w	#2,B_SYI.w
	move.w	#8,B_DXI.w
.gset:	move.l	(a3)+,-(sp)		; its code
	move.l	(a3),a0			; its stream
	move.w	d3,d0			; (the destination's low word)
	lea	B_END1.w,a1		; (the code's registers)
	lea	B_END3.w,a6
	lea	B_DYI.w,a3
	lea	B_YC.w,a5
	lea	B_DST+2.w,a4
	lea	B_CTRL.w,a2
	moveq	#4,d1
	moveq	#-$40,d2
	move.w	#LB,d4
	rts				; (into the code; it returns to draw_cell's caller)
.rp:
	endc
	addq.l	#8,a0			; (the slot's header: the shape record, the aligned plane words' address)
	move.w	cell_x,d0
	add.w	#LEFT,d0		; screen x
	moveq	#15,d5
	and.w	d0,d5			; the shift
	and.w	#-16,d0			; the first word's x
	tst.w	d5
	bne.s	.sh
	moveq	#4,d6			; one word (inside: culled already otherwise)
	bra.s	.mode
.sh:	moveq	#0,d6
	cmp.w	#LEFT,d0
	bge.s	.l
	moveq	#8,d6			; the first word in the band: left clipped
	add.w	#16,d0
	bra.s	.mode
.l:	cmp.w	#LEFT+256-16,d0
	blt.s	.mode
	moveq	#12,d6			; the second word in the band: right clipped
.mode:	move.w	d6,cell_mode
	move.w	cell_y,d1		; the first drawn word's offset
	add.w	#16,d1
	add.w	d1,d1
	add.w	d1,d1
	lea	line_off,a1
	move.l	(a1,d1.w),d1
	lsr.w	#1,d0
	add.w	d0,d1
	move.l	draw_base,a1
	add.l	d1,a1
	move.w	(a0)+,d4		; the rows
	beq	.out
	move.w	d4,d1			; the plane words after the n rows (6 bytes each)
	add.w	d1,d1
	move.w	d1,d0
	add.w	d1,d1
	add.w	d0,d1
	subq.w	#1,d4
	lea	(a0,d1.w),a3
	move.l	a3,B_SRC.w
	lea	B_END1.w,a3
	lea	B_END3.w,a4
	lea	B_DST.w,a5
	lea	B_CTRL.w,a6
	moveq	#4,d3
	move.w	d5,d1
	moveq	#-$40,d6		; ($C0: start, HOG)
	moveq	#0,d7			; (the mask written last: none yet; a listed row's mask is never 0)
	move.w	cell_mode,d0
	cmp.w	last_mode,d0		; (the pass type's registers as the last sprite left them: only the skew)
	beq.s	.same
	move.w	d0,last_mode
	jmp	.modes(pc,d0.w)
.same:	jmp	.skews(pc,d0.w)
.skews:	bra.w	.k2
	bra.w	.k1
	bra.w	.kl
	bra.w	.kr
.k2:	or.b	#NFSR,d1
	move.b	d1,B_SKEW.w
	bra.w	.r2
.k1:	bra.w	.r1w
.kl:	or.b	#FXSR,d1
	move.b	d1,B_SKEW.w
	bra.w	.rl
.kr:	move.b	d1,B_SKEW.w
	bra.w	.rr
.modes:	bra.w	.m2
	bra.w	.m1
	bra.w	.ml
	bra.w	.mr
.out:	rts

	; a row: (row * 160).w, (mask << 16).l; lsr.l by the shift: the first word's end mask in the upper word, the
	; second's in the lower
	; two words: X count 2, NFSR, DXI 8, DYI -6
.m2:	move.w	#2,B_XC.w
	move.w	#2,B_SXI.w
	move.w	#2,B_SYI.w
	move.w	#8,B_DXI.w
	move.w	#-6,B_DYI.w
	or.b	#NFSR,d1
	move.b	d1,B_SKEW.w
.r2:	move.w	(a0)+,d0		; row * 160
	move.l	(a0)+,d1		; mask << 16
	cmp.l	d1,d7
	beq.s	.s2
	move.l	d1,d7
	lsr.l	d5,d1
	move.w	d1,(a4)
	swap	d1
	move.w	d1,(a3)
.s2:	lea	(a1,d0.w),a2
	move.l	a2,(a5)
	move.w	d3,6(a5)
	move.b	d6,(a6)
	dbf	d4,.r2
	rts
	; one word, no shift: X count 1, DYI 2
.m1:	move.w	#1,B_XC.w
	move.w	#2,B_SXI.w
	move.w	#2,B_SYI.w
	move.w	#2,B_DYI.w
	clr.b	B_SKEW.w
.r1w:	move.w	(a0)+,d0
	move.l	(a0)+,d1
	cmp.l	d1,d7
	beq.s	.s1
	move.l	d1,d7
	swap	d1
	move.w	d1,(a3)
.s1:	lea	(a1,d0.w),a2
	move.l	a2,(a5)
	move.w	d3,6(a5)
	move.b	d6,(a6)
	dbf	d4,.r1w
	rts
	; left clipped (the second word only): FXSR, source X increment 0, END1 = the mask's second word
.ml:	move.w	#1,B_XC.w
	clr.w	B_SXI.w
	move.w	#2,B_SYI.w
	move.w	#2,B_DYI.w
	or.b	#FXSR,d1
	move.b	d1,B_SKEW.w
.rl:	move.w	(a0)+,d0
	move.l	(a0)+,d1
	cmp.l	d1,d7
	beq.s	.sl
	move.l	d1,d7
	lsr.l	d5,d1
	move.w	d1,(a3)
.sl:	lea	(a1,d0.w),a2
	move.l	a2,(a5)
	move.w	d3,6(a5)
	move.b	d6,(a6)
	dbf	d4,.rl
	rts
	; right clipped (the first word only): END1 = the mask's first word
.mr:	move.w	#1,B_XC.w
	move.w	#2,B_SXI.w
	move.w	#2,B_SYI.w
	move.w	#2,B_DYI.w
	move.b	d1,B_SKEW.w
.rr:	move.w	(a0)+,d0
	move.l	(a0)+,d1
	cmp.l	d1,d7
	beq.s	.sr
	move.l	d1,d7
	lsr.l	d5,d1
	swap	d1
	move.w	d1,(a3)
.sr:	lea	(a1,d0.w),a2
	move.l	a2,(a5)
	move.w	d3,6(a5)
	move.b	d6,(a6)
	dbf	d4,.rr
	rts

; sprite_baked: d2 = the key -> a0 = the slot (baked now on a miss).  Keeps d5-d7.
sprite_baked:
	lea	sc_index,a0
	moveq	#0,d0
	move.w	d2,d0
	lsl.l	#2,d0
	move.l	(a0,d0.l),d1
	beq.s	.bake
	move.l	d1,a0
	rts
.bake:	move.w	sc_used,d1
	cmp.w	#SC_SLOTS,d1
	blo.s	.room
	movem.l	d0/d2/d5-d7,-(sp)	; (full: all again from now on; what is drawn stays)
	bsr	cache_flush
	movem.l	(sp)+,d0/d2/d5-d7
	moveq	#0,d1
.room:	addq.w	#1,sc_used
	mulu	#SC_SIZE,d1
	lea	sc_data,a0
	add.l	d1,a0
	lea	sc_index,a1
	move.l	a0,(a1,d0.l)
	movem.l	d2-d7/a0-a6,-(sp)
	bsr	bake_sprite
	movem.l	(sp)+,d2-d7/a0-a6
	rts

; bake_sprite: d2 = the key (code << 2 | flip x << 1 | flip y), a0 = the slot.
; n, (row * 160, mask << 16) for the opaque rows in row order, then their 4 plane words.  ya_spr: per code 16 rows of
; 8 bytes (two pens a byte, the leftmost in the high nibble); MAME's flip x reverses the columns, flip y the rows.
bake_sprite:
	moveq	#0,d0
	move.w	d2,d0
	lsr.w	#2,d0			; the code
	lsl.l	#7,d0			; 128 bytes a code
	lea	ya_spr,a1
	add.l	d0,a1
	lea	ya_pen,a2		; the pens' colour indices (pen 0: transparent)
	lea	bake_rows,a3		; 16 x (mask, 4 planes)
	moveq	#0,d7			; the row
.row:	move.w	d7,d0
	btst	#0,d2
	beq.s	.nfy
	eor.w	#15,d0			; (flip y: the rows from the last)
.nfy:	lsl.w	#3,d0
	lea	(a1,d0.w),a4		; the source row's 8 bytes
	moveq	#0,d3			; mask
	moveq	#0,d4			; planes 0, 1 (d4 high, low words), 2, 3 (d6)
	moveq	#0,d6
	moveq	#0,d1			; the pixel
.px:	move.w	d1,d0
	btst	#1,d2
	beq.s	.nfx
	eor.w	#15,d0			; (flip x: the columns from the last)
.nfx:	move.w	d0,d5
	lsr.w	#1,d5
	move.b	(a4,d5.w),d5
	btst	#0,d0
	bne.s	.lo
	lsr.b	#4,d5
.lo:	and.w	#15,d5
	move.b	d5,d0			; the pen (d0 is free here)
	move.b	(a2,d5.w),d5		; the colour index
	add.w	d3,d3
	add.l	d4,d4			; (plane 0 in the high word: its carry into bit 16 is cleared below)
	add.l	d6,d6
	and.l	#$FFFEFFFE,d4
	and.l	#$FFFEFFFE,d6
	tst.b	d0
	beq.s	.tr
	addq.w	#1,d3
	lsr.b	#1,d5
	bcc.s	.p1
	or.l	#$10000,d4
.p1:	lsr.b	#1,d5
	bcc.s	.p2
	addq.w	#1,d4
.p2:	lsr.b	#1,d5
	bcc.s	.p3
	or.l	#$10000,d6
.p3:	lsr.b	#1,d5
	bcc.s	.tr
	addq.w	#1,d6
.tr:	addq.w	#1,d1
	cmp.w	#16,d1
	bne.s	.px
	move.w	d3,(a3)+
	move.l	d4,(a3)+
	move.l	d6,(a3)+
	addq.w	#1,d7
	cmp.w	#16,d7
	bne	.row
	; the slot: the shape's record (ya_shapes), the aligned plane words' address, the opaque rows grouped by mask
	; (the generated code's order), their plane words, the same aligned
	moveq	#0,d0			; shape = the key (one transparency class)
	move.w	d2,d0
	move.l	d0,d1
	lsl.l	#2,d1
	lea	ya_shapes,a4
	move.l	(a4,d1.l),(a0)+
	move.l	a0,a5			; (the aligned plane words' address: below)
	addq.l	#4,a0
	; the opaque rows' order (engine/sprite_programs.py shape_order): grouped by mask, the groups in the order of
	; their first rows -> bake_ord ($FF after the last)
	lea	bake_ord,a4
	lea	bake_seen,a6
	clr.l	(a6)
	clr.l	4(a6)
	clr.l	8(a6)
	clr.l	12(a6)
	lea	bake_rows,a3		; (10 bytes a row: its mask first)
	moveq	#0,d0			; the row
.o1:	move.w	(a3),d4
	beq.s	.o4
	tst.b	(a6,d0.w)
	bne.s	.o4
	move.l	a3,a2			; the rows from here with its mask
	move.w	d0,d1
.o2:	cmp.w	(a2),d4
	bne.s	.o3
	move.b	d1,(a4)+
	st	(a6,d1.w)
.o3:	lea	10(a2),a2
	addq.w	#1,d1
	cmp.w	#16,d1
	bne.s	.o2
.o4:	lea	10(a3),a3
	addq.w	#1,d0
	cmp.w	#16,d0
	bne.s	.o1
	move.b	#$FF,(a4)
	lea	bake_ord,a4
	moveq	#0,d0			; n
.cnt:	cmp.w	#16,d0
	beq.s	.cn
	tst.b	(a4,d0.w)
	bmi.s	.cn
	addq.w	#1,d0
	bra.s	.cnt
.cn:	move.w	d0,(a0)+
	move.w	d0,d1
	add.w	d0,d0
	add.w	d1,d0
	add.w	d0,d0			; (6 bytes a row)
	lea	(a0,d0.w),a2		; the plane words' place
	move.w	d1,d0
	lsl.w	#3,d0
	lea	(a2,d0.w),a6		; the aligned copy's place (after them)
	move.l	a6,(a5)
	subq.w	#1,d1
	bmi.s	.none
.ord:	moveq	#0,d0
	move.b	(a4)+,d0		; the row: (row * 160, mask << 16), its planes
	move.w	d0,d3
	mulu	#10,d3
	lea	bake_rows,a3
	add.w	d3,a3
	mulu	#LB,d0
	move.w	d0,(a0)+
	move.w	(a3),(a0)+
	clr.w	(a0)+
	move.l	2(a3),(a2)+
	move.l	6(a3),(a2)+
	move.w	(a3)+,d3		; the aligned copy (engine/sprite_programs.py align_of): shifted left by the row's
	moveq	#0,d5			; empty columns (0 in every plane there, so a long shift of two planes is exact)
.lz:	tst.w	d3
	bmi.s	.al
	add.w	d3,d3
	addq.w	#1,d5
	bra.s	.lz
.al:	move.l	(a3)+,d4
	move.l	(a3),d6
	lsl.l	d5,d4
	lsl.l	d5,d6
	move.l	d4,(a6)+
	move.l	d6,(a6)+
	dbf	d1,.ord
.none:	rts

	section data,data
	include	"ya_assets.s"
ya_spr:		incbin	"ya_spr.bin"
ya_tiles:	incbin	"ya_tiles.bin"
ya_sstream:	incbin	"ya_sstream.bin"
	even
	even

	section bss,bss
	even
buf_base:	ds.l	NBUF
pf_base:	ds.l	1
draw_base:	ds.l	1
shown_pal:	ds.w	16
black_pal:	ds.w	16
shown_idx:	ds.w	1
prev_idx:	ds.w	1
draw_idx:	ds.w	1
pic_shown:	ds.w	1
cell_x:		ds.w	1
cell_y:		ds.w	1
cell_mode:	ds.w	1
cell_key:	ds.w	1
last_mode:	ds.w	1
sc_used:	ds.w	1
tc_used:	ds.w	1
spr_rows:	ds.l	1			; draw_sprites: the rows the sprites drawn now cover
row_dirty:	ds.l	NBUF			; per buffer: rows to draw whatever their scroll
row_scroll:	ds.w	NBUF*28			; per buffer and row: the offset o it was drawn at (-1: never)
row_span:	ds.b	NBUF*56			; per buffer and row: the groups g0, g1 its last sprites covered
row_sdirty:	ds.l	NBUF			; per buffer: the rows its last sprites covered (only their groups drawn)
sd_rows:	ds.l	1			; draw_rows: the buffer's row_sdirty
spr_span:	ds.l	1			; draw_sprites: the buffer's row_span
guard_dirty:	ds.b	4			; per buffer: bit 0 the top guard lines, bit 1 the bottom ones hold sprites
spr_guard:	ds.b	1
frame_ready:	ds.b	1
	even
tile_mode:	ds.w	1			; -1: no picture drawn yet (every cell is drawn)
row_off:	ds.w	1			; the picture's line 0 in the playfield (render_tiles)
tile_vram:	ds.b	2048			; the video RAM the playfield was drawn from
line_off:	ds.l	16+224+16		; the offset of picture line Y (from -16) in a buffer
bake_rows:	ds.w	16*5
bake_ord:	ds.b	18			; bake_sprite: the opaque rows' order ($FF after the last; even: bake_seen is cleared by longs)
bake_seen:	ds.b	16
	even
tc_index:	ds.w	CODES*4			; per tile key: its slot + 1 (0: not converted)
tc_data:	ds.b	TC_SLOTS*32
sc_index:	ds.l	CODES*4			; per sprite key: its slot (0: not baked)
sc_data:	ds.b	SC_SLOTS*SC_SIZE
	cnop	0,256
buffers:	ds.b	NBUF*BUFSZ+PF_LB*PF_LINES
	section text,code
