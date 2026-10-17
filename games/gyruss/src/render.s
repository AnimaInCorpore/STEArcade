; Gyruss's picture on the STE (included by gyruss.s).
;
; The arcade's screen is turned as MAME's ROT90 turns it (tools/assets.py): the picture is 224 x 256, picture pixel
; (X, Y) the raw pixel (x = Y, y = 239 - X), centred in the 320-pixel screen: black side bands of 48 pixels (three
; 16-pixel groups: the picture's edges lie on group boundaries), borders open (engine/rt/borders.s, PIC_TOP 10,
; PIC_LINES 256).  One palette (gy_pal: black and 15 fitted colours, every pen mapped to the nearest).
;
; Buffers of BL lines x 160 bytes: buffer line = PIC_TOP + Y (the display starts PIC_TOP lines above the picture),
; screen x = 48 + X; lines below the picture are guard lines for whole sprites.  Three display buffers and a clean
; screen.  The clean screen holds the tiles: a cell the video RAM changes (render_tiles: only the rows the program
; marked, tile_rows) is drawn there with movep.l and listed for each display buffer.  A buffer is brought to the new
; picture from the clean screen: its last sprites' rectangles (short HOG Blitter copies, blit_go), its listed cells
; (movep.l); then the sprites are drawn (the 48th entry first: the first on top) and the front tiles (colour bit 4,
; MAME's group 0: opaque) copied back over the cells the sprites covered, and the buffer is published for the next VBL.
;
; Tiles: raw cell (tx, ty) is the picture's 8 x 8 cell at X = 232 - 8 ty, Y = 8 tx (ty 2-29 visible): a byte of each
; plane in its 16-pixel group.  gy_tiles: the turned tile's two pen planes a row; raw flip x (colour bit 6) reverses
; the rows, raw flip y (bit 7) the bits; the colour's four pens (gy_tpen) give the STE planes.
;
; Sprites: an entry (raw x, code / bank, attributes, y) is the 16 x 8 picture cell at X = y - 17, Y = raw x.  Baked on
; first use per (bank, code, flips, colour) into a slot of the sprite cache: its opaque rows in natural row order, each
; with its row index and mask, then the rows' four plane words in that order, so the Blitter's source address runs on
; from row to row and END1 / END3 are written only when the mask changes (docs/sprite-preparation.md).  A row is one
; HOG pass (Y count 4: the planes; X count 2 with NFSR when shifted, 1 when not).  Clipped at the picture's edges
; (AGENTS.md: group-aligned): a cell across the left edge draws only its second word (FXSR, source X increment 0, the
; mask's second word as END1), across the right edge only its first; a cell wholly in a band is culled.  Top and
; bottom: whole into the guard lines.

	ifnd REN_ORDER
REN_ORDER = 0				; 1: a slot's rows with equal masks one after the other (docs/sprite-preparation.md)
	endc
BL = 280				; buffer lines: PIC_TOP above the picture, its 256, 14 guard lines
LB = 160
BUFSZ = BL*LB
NBUF = 3
PIC0 = PIC_TOP*LB			; the picture's line 0 in a buffer
LEFT = 48				; the picture's left edge (screen x)
SC_SLOTS = 1024				; sprite cache slots
SC_SIZE = 2+8*4+8*8			; n, (row * 160, mask) a row, the 4 plane words a row
DMG_MAX = 48+160				; the entries and their logged old contents (sub.s SEG_MAX)

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
	bsr	cache_flush
	lea	gy_pal,a0		; the palettes: the picture's, black around it
	lea	shown_pal,a1
	lea	black_pal,a2
	moveq	#15,d0
.pal:	move.w	(a0)+,(a1)+
	clr.w	(a2)+
	dbf	d0,.pal
	; the cells' offsets in a buffer (raw cell ty * 32 + tx; -1: not shown) and their columns / rows
	lea	cell_off,a0
	moveq	#0,d1			; ty
.ty:	moveq	#0,d2			; tx
.tx:	moveq	#-1,d0
	cmp.w	#2,d1
	blo.s	.st
	cmp.w	#29,d1
	bhi.s	.st
	move.w	#280,d3			; screen x = 48 + 232 - 8 ty
	move.w	d1,d4
	lsl.w	#3,d4
	sub.w	d4,d3
	move.w	d3,d4
	lsr.w	#4,d4
	lsl.w	#3,d4			; the group's byte
	btst	#3,d3
	beq.s	.hi
	addq.w	#1,d4			; (the right half: the odd byte)
.hi:	move.w	d2,d0
	mulu	#8*LB,d0
	add.l	#PIC0,d0
	ext.l	d4
	add.l	d4,d0
.st:	move.l	d0,(a0)+
	addq.w	#1,d2
	cmp.w	#32,d2
	bne.s	.tx
	addq.w	#1,d1
	cmp.w	#32,d1
	bne.s	.ty
	lea	rev8,a0			; bytes bit-reversed
	moveq	#0,d0
.rv:	moveq	#7,d2
	moveq	#0,d3
	move.b	d0,d1
.rb:	lsr.b	#1,d1
	addx.b	d3,d3
	dbf	d2,.rb
	move.b	d3,(a0)+
	addq.w	#1,d0
	cmp.w	#256,d0
	bne.s	.rv
	lea	line_off,a0		; picture line Y's offset
	move.l	#PIC0,d0
	move.w	#256-1,d1
.lo:	move.l	d0,(a0)+
	add.l	#LB,d0
	dbf	d1,.lo
	lea	key_b1,a0		; the cache key's parts: byte 1 (bank, code bits 0-6), the attributes
	lea	key_attr,a1
	moveq	#0,d0
.ky:	move.w	d0,d1
	and.w	#1,d1
	lsl.w	#8,d1
	lsl.w	#6,d1			; bank << 14
	move.w	d0,d2
	lsr.w	#1,d2
	lsl.w	#6,d2
	or.w	d2,d1
	move.w	d1,(a0)+
	moveq	#15,d1			; colour
	and.w	d0,d1
	btst	#5,d0
	beq.s	.ka
	or.w	#$2000,d1		; code bit 7
.ka:	btst	#6,d0
	bne.s	.kb
	or.w	#$20,d1			; raw flip x: bit 6 clear
.kb:	btst	#7,d0
	beq.s	.kc
	or.w	#$10,d1			; raw flip y
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
	move.w	#32768/8-1,d0
.c:	clr.l	(a0)+
	clr.l	(a0)+
	clr.l	(a0)+
	clr.l	(a0)+
	dbf	d0,.c
	clr.w	sc_used
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
	bsr	front_cells
	move.w	draw_idx,d0
	addq.b	#1,d0
	move.b	d0,frame_ready
	addq.w	#1,pic_count
	movem.l	(sp)+,d0-d7/a0-a6
	rts

; ----------------------------------------------------------------------------------------------------------------------
; render_tiles: the marked rows of the video RAM against tile_copy; each changed cell drawn into the clean screen, its
; front flag set, listed for each display buffer.  The first time: every cell.
; ----------------------------------------------------------------------------------------------------------------------
render_tiles:
	lea	Z_RAM+$8000,a2		; the colours
	lea	Z_RAM+$8400,a5		; the codes
	lea	tile_copy,a3
	lea	tile_copy+$400,a6
	lea	tile_rows,a4
	moveq	#0,d6			; the row (ty)
.row:	tst.b	tiles_full
	bne.s	.all
	tst.b	(a4,d6.w)
	beq	.nrow
.all:	clr.b	(a4,d6.w)
	move.w	d6,d7
	lsl.w	#5,d7			; the row's first cell
	moveq	#31,d5
.cell:	move.b	(a2,d7.w),d0		; colour
	move.b	(a5,d7.w),d1		; code
	tst.b	tiles_full
	bne.s	.chg
	cmp.b	(a3,d7.w),d0
	bne.s	.chg
	cmp.b	(a6,d7.w),d1
	beq.s	.same
.chg:	move.b	d0,(a3,d7.w)
	move.b	d1,(a6,d7.w)
	movem.l	d5-d7/a2-a6,-(sp)
	bsr	tile_changed
	movem.l	(sp)+,d5-d7/a2-a6
.same:	addq.w	#1,d7
	dbf	d5,.cell
.nrow:	addq.w	#1,d6
	cmp.w	#32,d6
	bne.s	.row
	sf	tiles_full
	rts

; tile_changed: d7.w = the cell (ty * 32 + tx), d0.b = its colour, d1.b = its code byte.  Drawn into the clean screen,
; the front flag, listed for the buffers (when shown).
PLANE	macro				; \1 = the plane: d7 = the OR of the masks of the pens whose colour has its bit
	moveq	#0,d7
	btst	#\1,(a2)
	beq.s	.a\@
	or.b	d5,d7
.a\@:	btst	#\1,1(a2)
	beq.s	.b\@
	or.b	d3,d7
.b\@:	btst	#\1,2(a2)
	beq.s	.c\@
	or.b	d4,d7
.c\@:	btst	#\1,3(a2)
	beq.s	.d\@
	or.b	d2,d7
.d\@:	lsl.l	#8,d6
	move.b	d7,d6
	endm

tile_changed:
	lea	front,a0
	btst	#4,d0
	sne	(a0,d7.w)
	move.w	d7,d2			; front_cols: column 29 - ty, row tx (ty 2-29)
	lsr.w	#5,d2
	cmp.w	#2,d2
	blo.s	.nf
	cmp.w	#29,d2
	bhi.s	.nf
	moveq	#29,d3
	sub.w	d2,d3
	add.w	d3,d3
	add.w	d3,d3
	lea	front_cols,a0
	add.w	d3,a0
	moveq	#31,d3
	and.w	d7,d3
	move.l	(a0),d4
	bclr	d3,d4
	btst	#4,d0
	beq.s	.fc
	bset	d3,d4
.fc:	move.l	d4,(a0)
.nf:
	move.w	d7,d2
	add.w	d2,d2
	add.w	d2,d2
	lea	cell_off,a0
	move.l	(a0,d2.w),d2
	bmi	.out			; (not shown)
	move.w	d7,-(sp)
	move.l	buf_base+NBUF*4,a1
	add.l	d2,a1			; the cell's first byte in the clean screen
	moveq	#0,d3			; the code (bit 5 of the colour: bit 8)
	move.b	d1,d3
	btst	#5,d0
	beq.s	.c
	add.w	#256,d3
.c:	lsl.w	#4,d3
	lea	gy_tiles,a0
	add.w	d3,a0
	moveq	#15,d3			; the colour's four pens
	and.b	d0,d3
	lsl.w	#2,d3
	lea	gy_tpen,a2
	add.w	d3,a2
	lea	rev8,a3
	move.w	#LB,a4			; the row step (raw flip x: from the last row up)
	btst	#6,d0
	beq.s	.nfx
	lea	7*LB(a1),a1
	move.w	#-LB,a4
.nfx:	move.b	d0,-(sp)		; (bit 7: raw flip y, the bits reversed)
	moveq	#7,d7
	move.w	d7,a5
.r:	moveq	#0,d0
	moveq	#0,d1
	move.b	(a0)+,d0		; pen bit 0 of the row's pixels
	move.b	(a0)+,d1		; pen bit 1
	tst.b	(sp)
	bpl.s	.nfy
	move.b	(a3,d0.w),d0
	move.b	(a3,d1.w),d1
.nfy:	move.b	d0,d2			; m3 = b0 b1
	and.b	d1,d2
	move.b	d1,d3			; m1 = b0 ~b1
	not.b	d3
	and.b	d0,d3
	move.b	d0,d4			; m2 = ~b0 b1
	not.b	d4
	and.b	d1,d4
	move.b	d0,d5			; m0 = ~(b0 | b1)
	or.b	d1,d5
	not.b	d5
	PLANE	0
	PLANE	1
	PLANE	2
	PLANE	3
	movep.l	d6,0(a1)
	add.w	a4,a1
	subq.w	#1,a5
	move.w	a5,d7
	bpl	.r
	addq.l	#2,sp
	move.w	(sp)+,d7
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
; restore_damage: the buffer's last sprite rectangles from the clean screen (a HOG copy each, blit_go: short pieces)
; ----------------------------------------------------------------------------------------------------------------------
restore_damage:
	move.w	draw_idx,d0
	move.w	d0,d1
	add.w	d1,d1
	lea	dmg_n,a0
	move.w	(a0,d1.w),d7
	beq	.out
	clr.w	(a0,d1.w)
	mulu	#DMG_MAX*6,d0
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
	moveq	#4,d3
	moveq	#-1,d4			; (the words of the last rectangle)
	subq.w	#1,d7
.r:	move.l	(a0)+,d0		; the offset
	move.w	(a0)+,d1		; the words a line (4 or 8)
	cmp.w	d1,d4
	beq.s	.same
	move.w	d1,d4
	move.w	d1,B_XC.w
	move.w	#LB+2,d2
	sub.w	d1,d2
	sub.w	d1,d2			; the Y increments
	move.w	d2,B_SYI.w
	move.w	d2,B_DYI.w
.same:	lea	(a2,d0.l),a1
	move.l	a1,B_SRC.w
	lea	(a3,d0.l),a1
	move.l	a1,B_DST.w
	move.w	d3,(a4)			; two HOG passes of 4 lines (at most 32 words each; the addresses run on)
	move.b	#$C0,(a5)
	move.w	d3,(a4)
	move.b	#$C0,(a5)
	dbf	d7,.r
.out:	rts

; ----------------------------------------------------------------------------------------------------------------------
; front_cells: the front tiles (colour bit 4) over the cells the sprites drawn now cover, from the clean screen
; ----------------------------------------------------------------------------------------------------------------------
front_cells:
	move.w	front_n,d7
	beq	.out
	lea	frontq,a6		; (per sprite over a front cell: the first cell column, row, columns - 1 | rows - 1 << 8)
	move.l	buf_base+NBUF*4,a2
	move.l	draw_base,a3
	lea	front,a4
	lea	cell_off,a5
	subq.w	#1,d7
.r:	move.w	(a6)+,d3		; cx0: picture X / 8 (raw ty = 29 - cx)
	move.w	(a6)+,d4		; cy0: picture Y / 8 (raw tx)
	move.w	(a6)+,d5		; columns - 1 (1 or 2), rows - 1 in the upper byte
.cx:	move.w	d5,-(sp)
	move.w	d4,-(sp)
	lsr.w	#8,d5			; rows - 1
.cy:	cmp.w	#28,d3			; (the visible columns 0-27, rows 0-31)
	bhs.s	.nc
	cmp.w	#32,d4
	bhs.s	.nc
	moveq	#29,d2
	sub.w	d3,d2
	lsl.w	#5,d2
	add.w	d4,d2			; the cell ty * 32 + tx
	tst.b	(a4,d2.w)
	beq.s	.nc
	add.w	d2,d2
	add.w	d2,d2
	move.l	(a5,d2.w),d0
	copy_cell
.nc:	addq.w	#1,d4
	dbf	d5,.cy
	move.w	(sp)+,d4
	move.w	(sp)+,d5
	addq.w	#1,d3
	subq.b	#1,d5
	bpl.s	.cx
	dbf	d7,.r
.out:	rts

; ======================================================================================================================
; draw_sprites: the 48 entries of the sprite RAM ($4040-$40FF of the sub CPU), the last first
; ======================================================================================================================
draw_sprites:
	move.w	draw_idx,d0
	mulu	#DMG_MAX*6,d0
	lea	dmg_list,a0
	add.l	d0,a0
	move.l	a0,dmg_ptr
	move.l	#frontq,dmgc_ptr
	clr.w	front_n
	clr.w	spr_n
	move.w	#-1,last_mode
	move.w	#$0203,B_HOP.w
	move.w	#$BC,spr_offs
.ent:	move.w	spr_offs,d0
	lsr.w	#1,d0			; (the entry * 2)
	lea	seg_head,a0
	move.w	(a0,d0.w),d1		; its bands (machine.GyrussPort: the multiplexing)
	bne.s	.segs
	sf	clip_on
	move.w	#-1000,clip_lo
	move.w	#1000,clip_hi
	lea	sub_ram+$40,a0
	add.w	spr_offs,a0
	bsr	draw_entry
	bra.s	.next
.segs:	st	clip_on
	move.w	#1000,clip_hi		; each old content on the lines above its line (X >= 239 - line)
.sg:	subq.w	#1,d1
	lsl.w	#3,d1
	lea	seg_list,a0
	add.w	d1,a0
	move.w	#239,d0
	sub.w	4(a0),d0
	move.w	d0,clip_lo
	move.w	6(a0),-(sp)		; (the next)
	move.w	d0,-(sp)
	bsr	draw_entry
	move.w	(sp)+,clip_hi
	move.w	(sp)+,d1
	bne.s	.sg
	move.w	#-1000,clip_lo		; the final content below the last
	lea	sub_ram+$40,a0
	add.w	spr_offs,a0
	bsr	draw_entry
.next:	sub.w	#4,spr_offs
	bpl	.ent
	move.w	draw_idx,d0
	add.w	d0,d0
	lea	dmg_n,a0
	move.w	spr_n,(a0,d0.w)
	rts

; draw_entry: a0 = a sprite entry (raw x, code / bank, attributes, y); clip_lo / clip_hi: the picture columns
; [lo, hi) it may cover
draw_entry:
	moveq	#0,d3
	move.b	3(a0),d3
	sub.w	#17,d3			; picture X
	cmp.w	#-16,d3
	ble	.out
	cmp.w	#224,d3
	bge	.out
	moveq	#0,d4
	move.b	(a0),d4			; picture Y
	moveq	#0,d1			; the key: bank << 14 | code << 6 | flip x << 5 | flip y << 4 | colour
	move.b	1(a0),d1
	add.w	d1,d1
	lea	key_b1,a1
	move.w	(a1,d1.w),d2
	moveq	#0,d1
	move.b	2(a0),d1
	add.w	d1,d1
	lea	key_attr,a1
	or.w	(a1,d1.w),d2
	bra	draw_cell
.out:	rts

; draw_cell: d2 = the key, d3 = picture X (-15 .. 223), d4 = picture Y.  Bakes it on a miss, clips it at the edges,
; draws it, lists its damage.
draw_cell:
	move.w	d3,cell_x
	move.w	d4,cell_y
	bsr	sprite_baked		; a0 = the slot
	tst.b	clip_on
	beq.s	.ncl
	move.w	clip_lo,d0		; a band's columns: the slot's masks cut to them (clip_slot)
	sub.w	cell_x,d0
	bgt.s	.cl
	move.w	clip_hi,d0
	sub.w	cell_x,d0
	cmp.w	#16,d0
	bge.s	.ncl
.cl:	bsr	clip_slot
	beq	.out
.ncl:	move.w	cell_x,d0
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
	move.l	a1,dmg_ptr
	; over a front tile?  (front_cols: a long of the front rows per cell column)
	move.w	cell_x,d2
	bpl.s	.x0
	moveq	#0,d2			; (the columns in the left band are no cells)
.x0:	lsr.w	#3,d2			; the first cell column
	add.w	d2,d2
	add.w	d2,d2
	lea	front_cols,a1
	add.w	d2,a1
	move.l	(a1)+,d3
	or.l	(a1)+,d3
	moveq	#7,d4
	and.w	cell_x,d4
	beq.s	.c2
	tst.w	cell_x
	bmi.s	.c2
	or.l	(a1),d3			; (a third column)
.c2:	tst.l	d3
	beq.s	.nod
	move.w	cell_y,d4
	lsr.w	#3,d4
	moveq	#1,d2
	moveq	#7,d7
	and.w	cell_y,d7
	beq.s	.one
	moveq	#3,d2			; (two rows)
.one:	lsl.l	d4,d2
	and.l	d2,d3
	beq.s	.nod
	cmp.w	#DMG_MAX,front_n	; listed for front_cells
	bhs.s	.nod
	addq.w	#1,front_n
	move.l	dmgc_ptr,a1
	move.w	cell_x,d2
	bpl.s	.f0
	moveq	#0,d2
.f0:	lsr.w	#3,d2
	move.w	d2,(a1)+		; the first cell column
	move.w	d4,(a1)+		; the first cell row
	moveq	#0,d2
	tst.w	d7
	beq.s	.f1
	move.w	#$0100,d2		; rows - 1
.f1:	moveq	#7,d3
	and.w	cell_x,d3
	sne	d3			; columns - 1: 2 when not on a cell's first column, else 1
	and.b	#1,d3
	addq.b	#1,d3
	tst.w	cell_x
	bpl.s	.f2
	moveq	#1,d3			; (left of the picture: at most two cells)
.f2:	move.b	d3,d2
	move.w	d2,(a1)+
	move.l	a1,dmgc_ptr
.nod:	move.l	draw_base,a1
	add.l	d1,a1
	move.w	(a0)+,d4		; the rows
	beq	.out
	subq.w	#1,d4
	move.w	d4,d1
	addq.w	#1,d1
	lsl.w	#2,d1
	lea	(a0,d1.w),a3		; the plane words
	move.l	a3,B_SRC.w
	lea	B_END1.w,a3
	lea	B_END3.w,a4
	lea	B_DST.w,a5
	lea	B_YC.w,a6
	moveq	#4,d3
	move.w	d5,d1
	moveq	#16,d6
	sub.w	d5,d6			; 16 - shift
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
.k1:	bra.w	.r1
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

	; two words: X count 2, NFSR, DXI 8, DYI -6
.m2:	move.w	#2,B_XC.w
	move.w	#2,B_SXI.w
	move.w	#2,B_SYI.w
	move.w	#8,B_DXI.w
	move.w	#-6,B_DYI.w
	or.b	#NFSR,d1
	move.b	d1,B_SKEW.w
.r2:	move.w	(a0)+,d0		; row * 160
	move.w	(a0)+,d1		; mask
	cmp.w	d1,d7
	beq.s	.s2
	move.w	d1,d7
	move.w	d1,d2
	lsr.w	d5,d2
	move.w	d2,(a3)
	lsl.w	d6,d1
	move.w	d1,(a4)
.s2:	lea	(a1,d0.w),a2
	move.l	a2,(a5)
	move.w	d3,(a6)
	move.b	#$C0,B_CTRL.w
	dbf	d4,.r2
	rts
	; one word, no shift: X count 1, DYI 2
.m1:	move.w	#1,B_XC.w
	move.w	#2,B_SXI.w
	move.w	#2,B_SYI.w
	move.w	#2,B_DYI.w
	clr.b	B_SKEW.w
.r1:	move.w	(a0)+,d0
	move.w	(a0)+,d1
	cmp.w	d1,d7
	beq.s	.s1
	move.w	d1,d7
	move.w	d1,(a3)
.s1:	lea	(a1,d0.w),a2
	move.l	a2,(a5)
	move.w	d3,(a6)
	move.b	#$C0,B_CTRL.w
	dbf	d4,.r1
	rts
	; left clipped (the second word only): FXSR, source X increment 0, END1 = the mask's second word
.ml:	move.w	#1,B_XC.w
	clr.w	B_SXI.w
	move.w	#2,B_SYI.w
	move.w	#2,B_DYI.w
	or.b	#FXSR,d1
	move.b	d1,B_SKEW.w
.rl:	move.w	(a0)+,d0
	move.w	(a0)+,d1
	cmp.w	d1,d7
	beq.s	.sl
	move.w	d1,d7
	lsl.w	d6,d1
	move.w	d1,(a3)
.sl:	lea	(a1,d0.w),a2
	move.l	a2,(a5)
	move.w	d3,(a6)
	move.b	#$C0,B_CTRL.w
	dbf	d4,.rl
	rts
	; right clipped (the first word only): END1 = the mask's first word
.mr:	move.w	#1,B_XC.w
	move.w	#2,B_SXI.w
	move.w	#2,B_SYI.w
	move.w	#2,B_DYI.w
	move.b	d1,B_SKEW.w
.rr:	move.w	(a0)+,d0
	move.w	(a0)+,d1
	cmp.w	d1,d7
	beq.s	.sr
	move.w	d1,d7
	lsr.w	d5,d1
	move.w	d1,(a3)
.sr:	lea	(a1,d0.w),a2
	move.l	a2,(a5)
	move.w	d3,(a6)
	move.b	#$C0,B_CTRL.w
	dbf	d4,.rr
	rts

; clip_slot: a0 = a slot -> a0 = clip_tmp: its rows with the masks cut to the columns [clip_lo, clip_hi) (picture X;
; the sprite at cell_x), the rows left empty out; Z set when none is left.  d0-d4 used.
clip_slot:
	move.w	clip_lo,d0
	sub.w	cell_x,d0		; the first column in
	move.w	clip_hi,d1
	sub.w	cell_x,d1		; the first column out
	moveq	#-1,d2
	tst.w	d0
	ble.s	.l
	cmp.w	#16,d0
	bge.s	.none
	lsr.w	d0,d2
.l:	tst.w	d1
	ble.s	.none
	cmp.w	#16,d1
	bge.s	.h
	move.w	#$FFFF,d3
	lsr.w	d1,d3
	not.w	d3
	and.w	d3,d2
.h:	move.w	(a0)+,d3		; the rows
	lea	clip_tmp+2,a1
	lea	clip_tmp+2+8*4,a2	; (the planes: after the largest row list; draw_cell finds them after the n listed)
	moveq	#0,d4
	subq.w	#1,d3
	bmi.s	.none
	move.w	d3,d0
	addq.w	#1,d0
	lsl.w	#2,d0
	lea	(a0,d0.w),a3		; the slot's plane words
.r:	move.w	(a0)+,d0		; row * 160
	move.w	(a0)+,d1
	and.w	d2,d1
	beq.s	.e
	move.w	d0,(a1)+
	move.w	d1,(a1)+
	move.l	(a3),(a2)+
	move.l	4(a3),(a2)+
	addq.w	#1,d4
.e:	addq.l	#8,a3
	dbf	d3,.r
	tst.w	d4
	beq.s	.none
	; the planes right after the n listed rows (the slot's layout)
	lea	clip_tmp,a0
	move.w	d4,(a0)
	move.w	d4,d0
	lsl.w	#2,d0
	lea	2(a0,d0.w),a1
	lea	clip_tmp+2+8*4,a2
	subq.w	#1,d4
.p:	move.l	(a2)+,(a1)+
	move.l	(a2)+,(a1)+
	dbf	d4,.p
	moveq	#1,d0			; (Z clear)
	rts
.none:	moveq	#0,d0			; (Z set)
	rts

; sprite_baked: d2 = the key -> a0 = the slot (baked now on a miss).  Keeps d5-d7.
sprite_baked:
	lea	sc_index,a0
	moveq	#0,d0
	move.w	d2,d0
	add.l	d0,d0
	move.w	(a0,d0.l),d1
	beq.s	.bake
	subq.w	#1,d1
	mulu	#SC_SIZE,d1
	lea	sc_data,a0
	add.l	d1,a0
	rts
.bake:	move.w	sc_used,d1
	cmp.w	#SC_SLOTS,d1
	blo.s	.room
	movem.l	d0/d2/d5-d7,-(sp)	; (full: all again from now on; what is drawn stays)
	bsr	cache_flush
	movem.l	(sp)+,d0/d2/d5-d7
	moveq	#0,d1
.room:	addq.w	#1,d1
	move.w	d1,sc_used
	lea	sc_index,a0
	move.w	d1,(a0,d0.l)
	subq.w	#1,d1
	mulu	#SC_SIZE,d1
	lea	sc_data,a0
	add.l	d1,a0
	movem.l	d2-d7/a0-a6,-(sp)
	bsr	bake_sprite
	movem.l	(sp)+,d2-d7/a0-a6
	rts

; bake_sprite: d2 = the key (bank << 14 | code << 6 | flip x << 5 | flip y << 4 | colour), a0 = the slot.
; n, (row * 160, mask) for the opaque rows in row order, then their 4 plane words.  Raw flip x reverses the rows,
; raw flip y the columns.
bake_sprite:
	move.w	d2,a5			; (the key: the flips)
	move.w	d2,d0
	lsr.w	#6,d0			; bank * 256 + code
	lsl.w	#6,d0
	lea	gy_spr,a1
	add.w	d0,a1			; (64 bytes a sprite: < 32 KB)
	moveq	#15,d0
	and.w	d2,d0
	lsl.w	#4,d0
	lea	gy_spen,a2
	add.w	d0,a2			; the colour's 16 pens
	lea	bake_rows,a3		; 8 x (mask, 4 planes)
	moveq	#0,d7			; the row
.row:	move.w	d7,d0			; the source row
	move.w	a5,d1
	btst	#5,d1
	beq.s	.nfx
	eor.w	#7,d0
.nfx:	lsl.w	#3,d0
	lea	(a1,d0.w),a4		; its 8 bytes (16 nibbles, the leftmost the first high nibble)
	lea	bake_px,a6		; unpacked: 16 pens, the columns reversed for flip y
	moveq	#1,d6
	btst	#4,d1
	beq.s	.up
	lea	16(a6),a6
	moveq	#7,d0
.ur:	move.b	(a4)+,d1		; (pixels 2k, 2k + 1 to 15 - 2k, 14 - 2k)
	move.b	d1,d2
	lsr.b	#4,d2
	move.b	d2,-(a6)
	and.b	#15,d1
	move.b	d1,-(a6)
	dbf	d0,.ur
	bra.s	.pix
.up:	moveq	#7,d0
.uf:	move.b	(a4)+,d1
	move.b	d1,1(a6)
	and.b	#15,1(a6)
	lsr.b	#4,d1
	move.b	d1,(a6)
	addq.l	#2,a6
	dbf	d0,.uf
	lea	-16(a6),a6
.pix:	moveq	#0,d3			; mask
	moveq	#0,d4			; plane 0
	moveq	#0,d5			; plane 1
	moveq	#0,d2			; plane 2
	moveq	#0,d1			; plane 3
	moveq	#15,d6
.px:	moveq	#0,d0
	move.b	(a6)+,d0
	beq.s	.tr
	add.w	d3,d3
	addq.w	#1,d3
	move.b	(a2,d0.w),d0		; the colour index
	lsr.b	#1,d0
	addx.w	d4,d4
	lsr.b	#1,d0
	addx.w	d5,d5
	lsr.b	#1,d0
	addx.w	d2,d2
	lsr.b	#1,d0
	addx.w	d1,d1
	dbf	d6,.px
	bra.s	.done
.tr:	add.w	d3,d3
	add.w	d4,d4
	add.w	d5,d5
	add.w	d2,d2
	add.w	d1,d1
	dbf	d6,.px
.done:	move.w	d3,(a3)+		; mask, planes 0-3
	move.w	d4,(a3)+
	move.w	d5,(a3)+
	move.w	d2,(a3)+
	move.w	d1,(a3)+
	addq.w	#1,d7
	cmp.w	#8,d7
	bne	.row
	; the slot: the opaque rows
	lea	bake_rows,a3
	moveq	#0,d0			; n
	moveq	#7,d1
.cnt:	tst.w	(a3)
	beq.s	.c0
	addq.w	#1,d0
.c0:	lea	10(a3),a3
	dbf	d1,.cnt
	move.w	d0,(a0)+
	lsl.w	#2,d0
	lea	(a0,d0.w),a2		; the plane words' place
	lea	bake_rows,a3
	moveq	#0,d1			; the row
	if REN_ORDER
	clr.l	bake_used		; (REN_ORDER: each row not placed yet, then the later rows with the same mask)
	clr.l	bake_used+4
	endc
.ord:
	if REN_ORDER
	lea	bake_used,a4
	tst.b	(a4,d1.w)
	bne.s	.e
	endc
	move.w	(a3),d3
	beq.s	.e
	bsr.s	.emit
	if REN_ORDER
	move.w	d1,d4			; the later rows with this mask
	move.l	a3,a5
.same:	addq.w	#1,d4
	lea	10(a5),a5
	cmp.w	#8,d4
	bhs.s	.e
	cmp.w	(a5),d3
	bne.s	.same
	st	(a4,d4.w)
	movem.l	d1/a3,-(sp)
	move.w	d4,d1
	move.l	a5,a3
	bsr.s	.emit
	movem.l	(sp)+,d1/a3
	bra.s	.same
	endc
.e:	lea	10(a3),a3
	addq.w	#1,d1
	cmp.w	#8,d1
	bne.s	.ord
	rts
.emit:	move.w	d1,d0			; row d1 (its record at a3): (row * 160, mask), its planes
	mulu	#LB,d0
	move.w	d0,(a0)+
	move.w	(a3),(a0)+
	move.l	2(a3),(a2)+
	move.l	6(a3),(a2)+
	rts

	section data,data
	include	"gy_assets.s"
gy_spr:		incbin	"gy_spr.bin"
gy_tiles:	incbin	"gy_tiles.bin"
	even

	section bss,bss
	even
buf_base:	ds.l	NBUF+1
draw_base:	ds.l	1
dmg_ptr:	ds.l	1
dmgc_ptr:	ds.l	1
shown_pal:	ds.w	16
black_pal:	ds.w	16
shown_idx:	ds.w	1
prev_idx:	ds.w	1
draw_idx:	ds.w	1
pic_shown:	ds.w	1
spr_n:		ds.w	1
spr_offs:	ds.w	1
cell_x:		ds.w	1
cell_y:		ds.w	1
cell_mode:	ds.w	1
clip_lo:	ds.w	1
last_mode:	ds.w	1
front_n:	ds.w	1
clip_hi:	ds.w	1
sc_used:	ds.w	1
dmg_n:		ds.w	NBUF
dl_n:		ds.w	NBUF
frame_ready:	ds.b	1
tiles_full:	ds.b	1
	even
dmg_list:	ds.b	NBUF*DMG_MAX*6		; per buffer: (offset.l, words a line.w) a sprite
frontq:		ds.b	DMG_MAX*6		; the sprites over front cells: (cell column, cell row, columns - 1 | rows - 1 << 8)
front_cols:	ds.l	32			; per cell column (picture X / 8): bit (picture Y / 8) set for a front cell
line_off:	ds.l	256			; the offset of picture line Y in a buffer
key_b1:		ds.w	256			; the cache key's part of the entry's byte 1 (bank << 14 | code bits 0-6 << 6)
key_attr:	ds.w	256			; and of its attributes (code bit 7 << 13, flips, colour)
clip_on:	ds.b	1
	even
cell_off:	ds.l	1024
tile_copy:	ds.b	2048
front:		ds.b	1024
dl_flag:	ds.b	NBUF*1024
dl_list:	ds.w	NBUF*1024
rev8:		ds.b	256
bake_rows:	ds.w	8*5
bake_px:	ds.b	16
bake_used:	ds.b	8
	even
clip_tmp:	ds.b	2+8*4+8*8+8*8
sc_index:	ds.w	32768
sc_data:	ds.b	SC_SLOTS*SC_SIZE
	cnop	0,256
buffers:	ds.b	(NBUF+1)*BUFSZ
