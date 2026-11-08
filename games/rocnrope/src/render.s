; Roc'n Rope's picture on the STE (included by rocnrope.s), after Time Pilot's and Track & Field's renderers.
;
; The arcade's screen is turned as MAME's ROT270 turns it (tools/assets.py): the picture is 224 x 256, picture pixel
; (X, Y) the raw pixel (x = 255 - Y, y = X + 16), centred in the 320-pixel screen: black side bands of 48 pixels (three
; 16-pixel groups: the picture's edges lie on group boundaries), borders open (engine/rt/borders.s, PIC_TOP 10,
; PIC_LINES 256).  One palette (rr_pal: 16 fitted colours, every pen mapped to the nearest).
;
; Buffers of BL lines x 160 bytes: buffer line = PIC_TOP + Y, screen x = 48 + X; lines below the picture are guard
; lines for whole sprites.  Three display buffers and a clean screen.  The clean screen holds the tiles (there is no
; scrolling, no layer over the sprites): a cell the video RAM changes (render_tiles: the cells main_io_w / the inline
; stores listed: cell_list) is drawn there (the 8 rows of the tile converted on first use per (code, colour, flips) into
; the tile cache, movep.l a row) and listed for each display buffer.  A buffer is brought to the new picture from the
; clean screen: its last sprites' rectangles (short HOG Blitter copies), its listed cells (movep.l); then the sprites
; are drawn (the entry at $2E first: the first on top) and the buffer is published for the next VBL.
;
; Tiles: raw cell (tx, ty) (video RAM $4C00 + ty * 32 + tx, colour RAM $4800 + the same) is the picture's 8 x 8 cell at
; X = 8 (ty - 2), Y = 248 - 8 tx (ty 2-29 visible).  rr_tiles holds the tiles turned (unflipped); raw flip x (colour bit
; 6) is the picture's flip of the rows, raw flip y (bit 5) of the columns.
;
; Sprites: an entry (x at $4400 + o, code $4401 + o, attributes $4000 + o, y $4001 + o; o = 0, 2 .. $2E) is the 16 x 16
; picture square at X = y - 16, Y = x.  Baked on first use per (code, colour, flips) into a slot of the sprite cache:
; its opaque rows grouped by mask, each with its row offset and mask, then the rows' four plane words in that order, so
; the Blitter's source address runs on from row to row and END1 / END3 are written only when the mask changes
; (docs/sprite-preparation.md).  The generated path (engine/sprite_programs.py) draws a prepared shape's rows by shift;
; the row path (a row is one HOG pass: Y count 4: the planes; X count 2 with NFSR when shifted, 1 when not, OP 3 with
; the opaque pixels as end masks) draws the rest.  Clipped at the picture's edges (AGENTS.md: group-aligned): a sprite
; across the left edge draws only its second word (FXSR, source X increment 0, the mask's second word as END1), across
; the right edge only its first; a sprite wholly in a band is culled.  Top and bottom: whole into the guard lines.

BL = 284				; buffer lines: PIC_TOP above the picture, its 256, 18 guard lines
LB = 160
BUFSZ = BL*LB
NBUF = 3
PIC0 = PIC_TOP*LB			; the picture's line 0 in a buffer
LEFT = 48				; the picture's left edge (screen x)
TC_SLOTS = 2048				; tile cache slots (32 bytes)
SC_SLOTS = 1024				; sprite cache slots
CODES = 256				; sprite codes (tools/assets.py CODES: the shape number)
SC_SIZE = 8+2+16*6+16*8+16*8		; the shape record, the aligned plane words' address, n, (row * 160, mask << 16) a row, the 4 plane words a row (the row path), the same aligned (the generated code)
DMG_MAX = 24				; the entries

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
; init_render: the buffers black, the caches empty, the palettes, the cells' offsets
; ======================================================================================================================
init_render:
	lea	buffers,a0
	move.l	#(NBUF+1)*BUFSZ/16-1,d0
.clr:	clr.l	(a0)+
	clr.l	(a0)+
	clr.l	(a0)+
	clr.l	(a0)+
	subq.l	#1,d0
	bpl.s	.clr
	lea	buffers,a0
	lea	buf_base,a1
	moveq	#NBUF,d0		; (buffers 0-2, then the clean screen)
.bb:	move.l	a0,(a1)+
	add.l	#BUFSZ,a0
	dbf	d0,.bb
	clr.w	shown_idx
	move.w	#-1,prev_idx
	clr.b	frame_ready
	st	tiles_full
	move.l	#cell_list,cell_ptr
	bsr	cache_flush
	bsr	tcache_flush
	lea	rr_pal,a0		; the palettes: the picture's, black around it
	lea	shown_pal,a1
	lea	black_pal,a2
	moveq	#15,d0
.pal:	move.w	(a0)+,(a1)+
	clr.w	(a2)+
	dbf	d0,.pal
	; the cells' offsets in a buffer (raw cell ty * 32 + tx; -1: not shown): screen x = 48 + 8 (ty - 2), Y = 248 - 8 tx
	lea	cell_off,a0
	moveq	#0,d1			; ty
.ty:	moveq	#0,d2			; tx
.tx:	moveq	#-1,d0
	cmp.w	#2,d1
	blo.s	.st
	cmp.w	#29,d1
	bhi.s	.st
	move.w	d1,d3
	subq.w	#2,d3
	lsl.w	#3,d3
	add.w	#LEFT,d3		; screen x
	move.w	d3,d4
	lsr.w	#4,d4
	lsl.w	#3,d4			; the group's byte
	btst	#3,d3
	beq.s	.hi
	addq.w	#1,d4			; (the right half: the odd byte)
.hi:	move.w	#248+PIC_TOP,d0
	move.w	d2,d5
	lsl.w	#3,d5
	sub.w	d5,d0
	mulu	#LB,d0
	ext.l	d4
	add.l	d4,d0
.st:	move.l	d0,(a0)+
	addq.w	#1,d2
	cmp.w	#32,d2
	bne.s	.tx
	addq.w	#1,d1
	cmp.w	#32,d1
	bne.s	.ty
	lea	line_off,a0		; picture line Y's offset
	move.l	#PIC0,d0
	move.w	#256+16-1,d1
.lo:	move.l	d0,(a0)+
	add.l	#LB,d0
	dbf	d1,.lo
	lea	tile_copy,a0		; (no cell drawn yet)
	move.w	#2048/4-1,d0
.tc:	move.l	#-1,(a0)+
	dbf	d0,.tc
	lea	key_attr,a1		; the cache key's part of the attributes: colour << 2 | flip x << 1 | flip y (the
	moveq	#0,d0			; picture's: columns = raw flip y = attribute bit 7 clear, rows = raw flip x = bit 6)
.ky:	moveq	#$0F,d1
	and.w	d0,d1
	lsl.w	#2,d1
	btst	#7,d0
	bne.s	.kb
	or.w	#2,d1
.kb:	btst	#6,d0
	beq.s	.kc
	or.w	#1,d1
.kc:	move.w	d1,(a1)+
	addq.w	#1,d0
	cmp.w	#256,d0
	bne.s	.ky
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
	move.w	#65536/4-1,d0
.c:	clr.l	(a0)+
	clr.l	(a0)+
	clr.l	(a0)+
	clr.l	(a0)+
	dbf	d0,.c
	clr.w	sc_used
	rts

tcache_flush:
	lea	tc_index,a0
	move.w	#65536/8-1,d0
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
; render_frame: the tiles into the clean screen, then a free buffer brought to the arcade frame's picture and published
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
	bsr	restore_damage
	bsr	copy_cells
	bsr	draw_sprites
	move.w	draw_idx,d0
	addq.b	#1,d0
	move.b	d0,frame_ready
	addq.w	#1,pic_count
	movem.l	(sp)+,d0-d7/a0-a6
	rts

; ----------------------------------------------------------------------------------------------------------------------
; render_tiles: the listed cells against tile_copy; each changed cell drawn into the clean screen, listed for each
; display buffer.  The first time: every cell.
; ----------------------------------------------------------------------------------------------------------------------
render_tiles:
	tst.b	tiles_full		; (the first time: every cell)
	bne	.full
	move.l	cell_ptr,a4
	lea	cell_list,a3
	cmp.l	a3,a4
	beq.s	.out
	move.l	a3,cell_ptr
	lea	rr_mem+$4800,a5		; (kept: tile_changed uses d0-d6 a0-a2 only)
	lea	tile_copy,a6
.cell:	move.w	(a3)+,d7		; a written cell (colour RAM 0-$3FF, video RAM $400-$7FF): changed?
	lea	cell_dirty,a2
	clr.b	(a2,d7.w)
	and.w	#$3FF,d7
	lea	$400(a5),a0
	lea	$400(a6),a1
	move.b	(a5,d7.w),d0		; colour
	move.b	(a0,d7.w),d1		; code
	cmp.b	(a6,d7.w),d0
	bne.s	.chg
	cmp.b	(a1,d7.w),d1
	beq.s	.same
.chg:	move.b	d0,(a6,d7.w)
	move.b	d1,(a1,d7.w)
	movem.l	a3-a4,-(sp)
	bsr	tile_changed
	movem.l	(sp)+,a3-a4
.same:	cmp.l	a4,a3
	blo.s	.cell
.out:	rts
.full:	sf	tiles_full
	lea	cell_dirty,a0		; (the list emptied)
	move.w	#2048/4-1,d0
.cd:	clr.l	(a0)+
	dbf	d0,.cd
	move.l	#cell_list,cell_ptr
	moveq	#0,d7
.fc:	lea	rr_mem+$4800,a5
	lea	rr_mem+$4C00,a0
	lea	tile_copy,a6
	lea	tile_copy+$400,a1
	move.b	(a5,d7.w),d0
	move.b	d0,(a6,d7.w)
	move.b	(a0,d7.w),d1
	move.b	d1,(a1,d7.w)
	move.w	d7,-(sp)
	bsr	tile_changed
	move.w	(sp)+,d7
	addq.w	#1,d7
	cmp.w	#1024,d7
	blo.s	.fc
	rts

; tile_changed: d7.w = the cell (ty * 32 + tx), d0.b = its colour byte, d1.b = its code byte.  Drawn into the clean
; screen (converted on first use), listed for the buffers.  d0-d6 a0-a2 used.
tile_changed:
	move.w	d7,d2
	add.w	d2,d2
	add.w	d2,d2
	lea	cell_off,a0
	move.l	(a0,d2.w),d2
	bmi	.out			; (not shown)
	move.l	d2,t_off
	moveq	#0,d3			; the key: code << 6 | flip y << 5 | flip x << 4 | colour (the picture's flips: x =
	move.b	d0,d3			; the columns = raw flip y = colour bit 5, y = the rows = raw flip x = bit 6)
	and.w	#$80,d3
	add.w	d3,d3
	move.b	d1,d3
	lsl.w	#6,d3
	moveq	#15,d4
	and.b	d0,d4
	or.w	d4,d3
	btst	#5,d0
	beq.s	.nx
	or.w	#$10,d3
.nx:	btst	#6,d0
	beq.s	.ny
	or.w	#$20,d3
.ny:	move.w	d3,d2
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
	move.l	buf_base+NBUF*4,a1
	add.l	t_off,a1		; the cell's first byte in the clean screen
	movem.l	(a0),d0-d5/a2		; (rows 0-6; row 7 below)
	movep.l	d0,0(a1)
	movep.l	d1,LB(a1)
	movep.l	d2,2*LB(a1)
	movep.l	d3,3*LB(a1)
	movep.l	d4,4*LB(a1)
	movep.l	d5,5*LB(a1)
	move.l	a2,d0
	movep.l	d0,6*LB(a1)
	move.l	28(a0),d0
	movep.l	d0,7*LB(a1)
	; listed for each display buffer
	lea	dl_flag,a0
	lea	dl_n,a1
	lea	dl_list,a2
	moveq	#NBUF-1,d1
.lb:	tst.b	(a0,d7.w)
	bne.s	.nl
	st	(a0,d7.w)
	move.w	(a1),d2
	add.w	d2,d2
	move.w	d7,(a2,d2.w)
	addq.w	#1,(a1)
.nl:	lea	1024(a0),a0
	addq.l	#2,a1
	lea	2048(a2),a2
	dbf	d1,.lb
.out:	rts

; tile_convert: d2.w = the key (code << 6 | flip y << 5 | flip x << 4 | colour), d3.l = key * 2 -> d4.w = its new slot
; + 1, the tile's 8 rows converted there: a long a row, the planes 0-3 from the high byte (movep.l order).  MAME's
; flips: x reverses the columns, y the rows.  The code modulo 768 (the tiles there are).  d0-d6 a0-a2 used.
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
	move.w	d2,d0
	lsr.w	#6,d0			; the code
	lsl.w	#5,d0
	lea	rr_tiles,a0
	add.w	d0,a0			; its 8 rows of 4 bytes (two pens a byte)
	moveq	#15,d0
	and.w	d2,d0
	lsl.w	#4,d0
	lea	rr_tpen,a2
	add.w	d0,a2			; the colour's 16 pens -> colour index
	moveq	#0,d6			; the row
.row:	move.w	d6,d0
	btst	#5,d2
	beq.s	.nfy
	eor.w	#7,d0			; (flip y: the rows from the last)
.nfy:	lsl.w	#2,d0
	move.l	(a0,d0.w),d5		; the row's 8 pens, the leftmost in the top nibble
	btst	#4,d2
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

; copy_cell: d0.l = the cell's offset; from the clean screen (a2) into the buffer (a3).  d1 / a0 / a1 used.
copy_cell	macro
	lea	(a2,d0.l),a0
	lea	(a3,d0.l),a1
	rept	8
	movep.l	(REPTN*LB)(a0),d1
	movep.l	d1,(REPTN*LB)(a1)
	endr
	endm

; ----------------------------------------------------------------------------------------------------------------------
; copy_cells: the cells listed for the buffer being drawn, from the clean screen
; ----------------------------------------------------------------------------------------------------------------------
copy_cells:
	move.w	draw_idx,d4
	move.w	d4,d5
	add.w	d5,d5
	lea	dl_n,a4
	add.w	d5,a4			; its count
	move.w	(a4),d6
	beq	.out
	clr.w	(a4)
	mulu	#1024,d4
	lea	dl_flag,a5
	add.l	d4,a5			; its flags
	add.l	d4,d4
	lea	dl_list,a6
	add.l	d4,a6			; its list
	move.l	buf_base+NBUF*4,a2
	move.l	draw_base,a3
	lea	cell_off,a4
	subq.w	#1,d6
.c:	move.w	(a6)+,d2
	clr.b	(a5,d2.w)
	add.w	d2,d2
	add.w	d2,d2
	move.l	(a4,d2.w),d0
	copy_cell
	dbf	d6,.c
.out:	rts

; ----------------------------------------------------------------------------------------------------------------------
; restore_damage: the buffer's last sprite rectangles from the clean screen (HOG passes of at most 4 lines, at most 32
; words each; the addresses run on)
; ----------------------------------------------------------------------------------------------------------------------
restore_damage:
	move.w	draw_idx,d0
	move.w	d0,d1
	add.w	d1,d1
	lea	dmg_n,a0
	move.w	(a0,d1.w),d7
	beq	.out
	clr.w	(a0,d1.w)
	mulu	#DMG_MAX*8,d0
	lea	dmg_list,a0
	add.l	d0,a0
	move.l	buf_base+NBUF*4,a2
	move.l	draw_base,a3
	move.w	#$0203,B_HOP.w		; source
	moveq	#-1,d0
	move.w	d0,B_END1.w
	move.w	d0,B_END2.w
	move.w	d0,B_END3.w
	move.w	#2,B_SXI.w
	move.w	#2,B_DXI.w
	clr.b	B_SKEW.w
	lea	B_YC.w,a4
	lea	B_CTRL.w,a5
	moveq	#-1,d4			; (the words of the last rectangle)
	subq.w	#1,d7
.r:	move.l	(a0)+,d0		; the offset
	move.w	(a0)+,d1		; the words a line (4 or 8)
	move.w	(a0)+,d5		; the lines
	cmp.w	d1,d4
	beq.s	.same
	move.w	d1,d4
	move.w	d1,B_XC.w
	move.w	#LB+2,d2
	sub.w	d1,d2
	sub.w	d1,d2			; the Y increments
	move.w	d2,B_SYI.w
	move.w	d2,B_DYI.w
	moveq	#32,d3			; the lines a pass: 32 words (~256 bus cycles)
	divu	d1,d3
.same:	lea	(a2,d0.l),a1
	move.l	a1,B_SRC.w
	lea	(a3,d0.l),a1
	move.l	a1,B_DST.w
.p:	move.w	d3,d6			; (HOG passes of at most 32 words; the addresses run on)
	cmp.w	d6,d5
	bge.s	.p4
	move.w	d5,d6
.p4:	move.w	d6,(a4)
	move.b	#$C0,(a5)
	sub.w	d6,d5
	bgt.s	.p
	dbf	d7,.r
.out:	rts


; ======================================================================================================================
; draw_sprites: the 24 entries ($402E / $442E first: the first entry on top)
; ======================================================================================================================
draw_sprites:
	move.w	draw_idx,d0
	mulu	#DMG_MAX*8,d0
	lea	dmg_list,a0
	add.l	d0,a0
	move.l	a0,dmg_ptr
	clr.w	spr_n
	move.w	#-1,last_mode
	move.w	#$0203,B_HOP.w
	bsr	held_regs
SLOT	macro				; \1 = the entry's offset
	lea	rr_mem+$44\1,a0
	moveq	#0,d3
	moveq	#0,d5
	moveq	#0,d6
	moveq	#0,d7
	move.b	(a0),d5			; x: picture Y
	move.b	1(a0),d6		; code
	move.b	-$400(a0),d7		; attributes
	move.b	-$3FF(a0),d3		; y
	bsr	draw_one
	endm
	SLOT	2E
	SLOT	2C
	SLOT	2A
	SLOT	28
	SLOT	26
	SLOT	24
	SLOT	22
	SLOT	20
	SLOT	1E
	SLOT	1C
	SLOT	1A
	SLOT	18
	SLOT	16
	SLOT	14
	SLOT	12
	SLOT	10
	SLOT	0E
	SLOT	0C
	SLOT	0A
	SLOT	08
	SLOT	06
	SLOT	04
	SLOT	02
	SLOT	00
	move.w	draw_idx,d0
	add.w	d0,d0
	lea	dmg_n,a0
	move.w	spr_n,(a0,d0.w)
	rts

; held_regs: the generated code's registers, kept from sprite to sprite (draw_one): a1 END1, a6 END3, a3 DYI,
; a5 Y count, a4 the destination's low word, a2 control, d1 = 4, d2 = $C0, d4 = 160
held_regs:
	lea	B_END1.w,a1
	lea	B_END3.w,a6
	lea	B_DYI.w,a3
	lea	B_YC.w,a5
	lea	B_DST+2.w,a4
	lea	B_CTRL.w,a2
	moveq	#4,d1
	moveq	#-$40,d2
	move.w	#LB,d4
	rts


; draw_one: d3 = raw y, d5 = raw x (picture Y), d6 = code, d7 = attributes (zero-extended).  The generated path
; (tools/assets.py sprite_programs) with the held registers; clipped sprites, unprepared shapes and 64 KB crossings
; go to draw_cell (the row path).  d0 d3 d5-d7 a0 used.
draw_one:
	sub.w	#16,d3			; picture X
	cmp.w	#-16,d3
	ble	.out
	cmp.w	#224,d3
	bge	.out
	move.w	d3,cell_x
	lsl.w	#8,d6
	add.w	d7,d7
	lea	key_attr,a0
	or.w	(a0,d7.w),d6		; the key: code << 8 | colour << 2 | flips
	move.w	d6,cell_key
	moveq	#0,d0
	move.w	d6,d0
	lsl.l	#2,d0
	lea	sc_index,a0
	move.l	(a0,d0.l),d7		; the slot (rec.l, src.l, n, rows, planes)
	beq	.slow
	move.l	d7,a0
	move.l	d7,cell_slot
	move.l	(a0),d6			; its shape's record (0: no generated code)
	beq	.slow
	add.w	#LEFT,d3		; screen x
	moveq	#15,d0
	and.w	d3,d0			; the shift (kept in d5's upper word)
	swap	d5
	move.w	d0,d5
	swap	d5
	tst.w	d0
	beq.s	.in
	cmp.w	#LEFT,d3		; across a side edge: the clipped variants (one word)
	blt.s	.cl
	cmp.w	#LEFT+224-16,d3
	blt.s	.in
	add.w	#32,d0			; (right: clip 2, the first word only)
	bra.s	.in
.cl:	add.w	#16,d0			; (left: clip 1, the second word only)
.in:	lsl.w	#2,d0			; (* 12)
	move.w	d0,a0
	add.w	d0,d0
	add.w	a0,d0
	add.l	d0,d6			; the variant: code, stream, damage offset, damage size
	lsr.w	#4,d3
	lsl.w	#3,d3			; the first word's byte in the line
	move.w	d5,d0
	add.w	d0,d0
	add.w	d0,d0
	lea	line_off,a0
	move.l	(a0,d0.w),d0
	add.w	d3,d0			; the offset in the buffer
	move.l	draw_base,d3
	add.l	d0,d3			; the destination
	cmp.w	#$FFFF-15*LB-16,d3	; (the code steps the low word: no 64 KB crossing)
	bhi	.slow
	move.l	d6,a0
	move.w	10(a0),d7		; the damage: words a line << 8 | lines (0: nothing drawn)
	beq	.out
	add.w	8(a0),d0		; (the drawn rows' first line, the drawn word)
	move.l	dmg_ptr,a0
	move.l	d0,(a0)+		; the offset, the words a line, the lines
	moveq	#0,d0
	move.b	d7,d0
	lsr.w	#8,d7
	move.w	d7,(a0)+
	move.w	d0,(a0)+
	move.l	a0,dmg_ptr
	addq.w	#1,spr_n
	move.l	d3,B_DST.w		; (the high word; the code writes the low word)
	move.l	cell_slot,a0
	move.l	4(a0),B_SRC.w		; (the slot's plane words)
	cmp.w	#16,last_mode
	beq.s	.set
	move.w	#16,last_mode
	clr.w	B_SXI.w			; (source X increment 0, Y increment 2: every pass type)
	move.w	#2,B_SYI.w
	move.w	#8,B_DXI.w
.set:	move.l	d6,a0			; the variant: its code, its stream
	move.l	(a0)+,-(sp)
	move.l	(a0),a0
	swap	d5
	move.w	d5,d7			; the skew: alone (d7), with NFSR (d5), with FXSR (d6)
	moveq	#NFSR,d5
	or.b	d7,d5
	moveq	#FXSR,d6
	or.b	d7,d6
	move.w	d3,d0			; (the destination's low word)
	rts				; (into the code; it returns to draw_one's caller)
.out:	rts
.slow:	movem.l	d1-d2/d4/a1-a6,-(sp)	; the row path (it lists its damage itself)
	move.w	cell_key,d2
	move.w	cell_x,d3
	move.w	d5,d4
	bsr	draw_cell
	movem.l	(sp)+,d1-d2/d4/a1-a6
	rts

; draw_cell: d2 = the key, d3 = picture X (-15 .. 223), d4 = picture Y.  Bakes it on a miss, clips it at the edges,
; draws it, lists its damage.
draw_cell:
	move.w	d2,cell_key
	move.w	d3,cell_x
	move.w	d4,cell_y
	bsr	sprite_baked		; a0 = the slot
	addq.l	#8,a0			; (its header: the shape record, the plane words' address)
	move.w	cell_x,d0
	add.w	#LEFT,d0		; screen x
	moveq	#15,d5
	and.w	d0,d5			; the shift
	and.w	#-16,d0			; the first word's x
	tst.w	d5
	bne.s	.sh
	moveq	#4,d6			; one word (inside: culled already otherwise)
	moveq	#4,d4			; (its words a line in the damage)
	bra.s	.mode
.sh:	moveq	#0,d6
	moveq	#8,d4
	cmp.w	#LEFT,d0
	bge.s	.l
	moveq	#8,d6			; the first word in the band: left clipped
	moveq	#4,d4
	add.w	#16,d0
	bra.s	.mode
.l:	cmp.w	#LEFT+224-16,d0
	blt.s	.mode
	moveq	#12,d6			; the second word in the band: right clipped
	moveq	#4,d4
.mode:	move.w	d6,cell_mode
	move.w	cell_y,d1		; the first drawn word's offset
	add.w	d1,d1
	add.w	d1,d1
	lea	line_off,a1
	move.l	(a1,d1.w),d1
	lsr.w	#1,d0
	add.w	d0,d1
	; the damage: the offset, the words a line
	cmp.w	#DMG_MAX,spr_n
	bhs	.nod
	addq.w	#1,spr_n
	move.l	dmg_ptr,a1
	move.l	d1,(a1)+
	move.w	d4,(a1)+
	move.w	#16,(a1)+
	move.l	a1,dmg_ptr
.nod:	move.l	draw_base,a1
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

; bake_sprite: d2 = the key (code << 8 | colour << 2 | flip x << 1 | flip y), a0 = the slot.
; n, (row * 160, mask << 16) for the opaque rows in row order, then their 4 plane words.  rr_spr: per code 16 rows of
; 8 bytes (two pens a byte, the leftmost in the high nibble); MAME's flip x reverses the columns, flip y the rows.
bake_sprite:
	move.w	d2,d0
	lsr.w	#8,d0			; the code
	lsl.w	#7,d0			; 128 bytes a code
	lea	rr_spr,a1
	add.w	d0,a1
	move.w	d2,d0
	and.w	#$3C,d0			; the colour * 4
	add.w	d0,d0
	add.w	d0,d0
	lea	rr_spen,a2
	add.w	d0,a2			; its 16 pens' colour indices ($FF: transparent)
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
	move.b	(a2,d5.w),d5		; the colour index
	add.w	d3,d3
	add.l	d4,d4			; (plane 0 in the high word: its carry into bit 16 is cleared below)
	add.l	d6,d6
	and.l	#$FFFEFFFE,d4
	and.l	#$FFFEFFFE,d6
	cmp.b	#$FF,d5
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
	; the slot: the shape's record (rr_shapes), the aligned plane words' address, the opaque rows grouped by mask
	; (the generated code's order), their plane words, the same aligned
	moveq	#0,d0			; shape = (class * CODES + code) << 2 | flips
	move.w	d2,d0
	lsr.w	#2,d0
	and.w	#15,d0
	lea	rr_tclass,a4
	moveq	#0,d1
	move.b	(a4,d0.w),d1		; the colour's transparency class
	mulu	#CODES,d1
	move.w	d2,d0
	lsr.w	#8,d0		; the code
	add.l	d1,d0
	lsl.l	#2,d0
	moveq	#3,d1
	and.w	d2,d1
	or.w	d1,d0
	move.l	d0,d1
	lsl.l	#2,d1
	lea	rr_shapes,a4
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
	include	"rr_assets.s"
rr_spr:		incbin	"rr_spr.bin"
rr_tiles:	incbin	"rr_tiles.bin"
rr_sstream:	incbin	"rr_sstream.bin"
	even

	section bss,bss
	even
buf_base:	ds.l	NBUF+1
draw_base:	ds.l	1
dmg_ptr:	ds.l	1
shown_pal:	ds.w	16
black_pal:	ds.w	16
shown_idx:	ds.w	1
prev_idx:	ds.w	1
draw_idx:	ds.w	1
pic_shown:	ds.w	1
spr_n:		ds.w	1
cell_x:		ds.w	1
cell_y:		ds.w	1
cell_mode:	ds.w	1
cell_key:	ds.w	1
cell_slot:	ds.l	1
last_mode:	ds.w	1
sc_used:	ds.w	1
tc_used:	ds.w	1
dmg_n:		ds.w	NBUF
dl_n:		ds.w	NBUF
t_off:		ds.l	1
frame_ready:	ds.b	1
tiles_full:	ds.b	1
	even
dmg_list:	ds.b	NBUF*DMG_MAX*8		; per buffer: (offset.l, words a line.w, lines.w) a sprite
cell_ptr:	ds.l	1			; the end of cell_list (render_tiles empties it)
cell_list:	ds.w	2048			; the cells written since the renderer looked (the video stores), once each
cell_dirty:	ds.b	2048			; their flags
line_off:	ds.l	256+16			; the offset of picture line Y in a buffer
key_attr:	ds.w	256			; the cache key's part of the attributes (colour << 2, flips)
cell_off:	ds.l	1024
tile_copy:	ds.b	2048			; the colours ($4800 + n) and codes ($4C00 + n) the clean screen has
dl_flag:	ds.b	NBUF*1024
dl_list:	ds.w	NBUF*1024
bake_rows:	ds.w	16*5
bake_ord:	ds.b	18			; bake_sprite: the opaque rows' order ($FF after the last; even: bake_seen is cleared by longs)
bake_seen:	ds.b	16
	even
tc_index:	ds.w	65536			; per tile key: its slot + 1 (0: not converted)
tc_data:	ds.b	TC_SLOTS*32
sc_index:	ds.l	65536			; per sprite key: its slot (0: not baked)
sc_data:	ds.b	SC_SLOTS*SC_SIZE
	cnop	0,256
buffers:	ds.b	(NBUF+1)*BUFSZ
	section text,code
