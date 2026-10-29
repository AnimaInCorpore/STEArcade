; Pooyan's picture on the STE (included by pooyan.s), after Time Pilot's renderer (games/timeplt/src/render.s).
;
; The arcade's screen is turned as MAME's ROT90 turns it (tools/assets.py): the picture is 224 x 256, picture pixel
; (X, Y) the raw pixel (x = Y, y = 239 - X), centred in the 320-pixel screen: black side bands of 48 pixels (three
; 16-pixel groups: the picture's edges lie on group boundaries), borders open (engine/rt/borders.s, PIC_TOP 10,
; PIC_LINES 256).  One palette (py_pal: black and the 15 most frequent of the arcade's 17 colours).
;
; Buffers of BL lines x 160 bytes: buffer line = PIC_TOP + Y, screen x = 48 + X; the lines below the picture are guard
; lines for whole sprites.  Three display buffers and a clean screen.  The clean screen holds the tiles: a cell the
; colour or video RAM changed (render_tiles: only the cells the program listed, cell_list) is drawn there with movep.l
; and listed for each display buffer.  A buffer is brought to the new picture from the clean screen (its last sprites'
; rectangles: short HOG Blitter copies; its listed cells: movep.l), then the 24 sprites are drawn, the entry at $10
; first (MAME draws $10 to $3E: the last on top), and the buffer is published for the next VBL.
;
; Tiles: raw cell (tx, ty) is the picture's 8 x 8 cell at X = 232 - 8 ty, Y = 8 tx (ty 2-29 visible): a byte of each
; plane in its 16-pixel group.  A cell's image (code, flips: colour RAM bits 6-7, colour: bits 0-3) is baked on first use
; into tile_bake (directly indexed: 16,384 x 32 bytes; py_tiles: the turned tile's 4 pen planes a row, py_tpen: the
; colour's 16 pens' STE colours).
;
; Sprites: an entry (x at $9000 + o, code $9001 + o, attributes $9400 + o, y $9401 + o) is the 16 x 16 picture square at
; X = y - 16, Y = x.  Baked on first use per (code, colour, flips) into a slot of the sprite cache: its opaque rows (a
; pen is transparent where the colour's lookup entry is colour 0: py_spen $FF) in the order of py_order (grouped by
; mask), each with its row offset and mask, then the rows' four plane words in that order, then the same aligned for the
; generated code (engine/sprite_programs.py: per shape = transparency class, code and flips, the coverage's shapes;
; docs/sprite-preparation.md).  Others, and 64 KB crossings, take the row path (draw_cell: a HOG pass a row).  Clipped
; at the picture's group-aligned side edges (AGENTS.md: the inner word only; wholly outside: culled); top and bottom:
; whole into the guard lines.

	ifnd REN_GEN
REN_GEN = 1				; 1: the generated shape code (tools/assets.py); 0: every sprite on the row path (to measure)
	endc
BL = 284				; buffer lines: PIC_TOP above the picture, its 256, 18 guard lines
LB = 160
BUFSZ = BL*LB
NBUF = 3
PIC0 = PIC_TOP*LB			; the picture's line 0 in a buffer
LEFT = 48				; the picture's left edge (screen x)
SC_SLOTS = 512				; sprite cache slots
SC_SIZE = 8+2+16*6+16*8+16*8		; the shape record, the aligned plane words' address, n, (row * 160, mask << 16) a row, the 4 plane words a row (the row path), the same aligned (the generated code)
DMG_MAX = 24
TILE_KEYS = 16384			; (flips << 8 | code) << 4 | colour

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
	lea	tile_ok,a0		; (no tile baked)
	move.w	#TILE_KEYS/4-1,d0
.tk:	clr.l	(a0)+
	dbf	d0,.tk
	lea	py_pal,a0		; the palettes: the picture's, black around it
	lea	shown_pal,a1
	lea	black_pal,a2
	moveq	#15,d0
.pal:	move.w	(a0)+,(a1)+
	clr.w	(a2)+
	dbf	d0,.pal
	; the cells' offsets in a buffer (raw cell ty * 32 + tx; -1: not shown)
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
	lea	line_off,a0		; picture line Y's offset
	move.l	#PIC0,d0
	move.w	#256+16-1,d1
.lo:	move.l	d0,(a0)+
	add.l	#LB,d0
	dbf	d1,.lo
	lea	key_attr,a1		; the cache key's part of the attributes: colour << 2 | flip x << 1 | flip y
	moveq	#0,d0
.ky:	moveq	#$0F,d1
	and.w	d0,d1
	lsl.w	#2,d1
	btst	#6,d0
	bne.s	.kb
	or.w	#2,d1			; MAME's flip x: bit 6 clear
.kb:	btst	#7,d0
	beq.s	.kc
	or.w	#1,d1			; flip y
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
	move.w	#4096/4-1,d0
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
	move.w	draw_idx,d0
	addq.b	#1,d0
	move.b	d0,frame_ready
	addq.w	#1,pic_count
	movem.l	(sp)+,d0-d7/a0-a6
	rts

; ----------------------------------------------------------------------------------------------------------------------
; render_tiles: the listed cells against tile_copy; each changed cell drawn into the clean screen and listed for each
; display buffer.  The first time (and after a block copy into the video RAM): every cell.
; ----------------------------------------------------------------------------------------------------------------------
render_tiles:
	tst.b	tiles_full
	bne	.full
	tst.b	tiles_all
	bne	.full
	move.l	cell_ptr,a4
	lea	cell_list,a3
	cmp.l	a3,a4
	beq.s	.out
	move.l	a3,cell_ptr
.cell:	move.w	(a3)+,d7		; a written cell: changed?
	lea	cell_dirty,a2
	clr.b	(a2,d7.w)
	lea	Z_RAM+$8000,a5
	lea	Z_RAM+$8400,a0
	move.b	(a5,d7.w),d0		; colour
	move.b	(a0,d7.w),d1		; code
	lea	tile_copy,a6
	lea	tile_copy+$400,a1
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
	sf	tiles_all
	lea	cell_dirty,a0		; (the list emptied)
	move.w	#1024/4-1,d0
.cd:	clr.l	(a0)+
	dbf	d0,.cd
	move.l	#cell_list,cell_ptr
	moveq	#0,d7
.fc:	lea	Z_RAM+$8000,a5
	lea	tile_copy,a6
	move.b	(a5,d7.w),d0
	move.b	d0,(a6,d7.w)
	lea	$400(a5),a5
	lea	$400(a6),a6
	move.b	(a5,d7.w),d1
	move.b	d1,(a6,d7.w)
	move.w	d7,-(sp)
	bsr	tile_changed
	move.w	(sp)+,d7
	addq.w	#1,d7
	cmp.w	#1024,d7
	blo.s	.fc
	rts

; tile_changed: d7.w = the cell (ty * 32 + tx), d0.b = its colour byte, d1.b = its code.  Its image (baked on first
; use) drawn into the clean screen, the cell listed for the buffers (when shown).  d7 kept.
tile_changed:
	move.w	d7,d2
	add.w	d2,d2
	add.w	d2,d2
	lea	cell_off,a0
	move.l	(a0,d2.w),d2
	bmi	.out			; (not shown)
	move.l	buf_base+NBUF*4,a1
	add.l	d2,a1			; the cell's first byte in the clean screen
	moveq	#0,d3			; the key: (flips << 8 | code) << 4 | colour
	move.b	d0,d3
	lsr.b	#6,d3
	lsl.w	#8,d3
	move.b	d1,d3
	lsl.w	#4,d3
	moveq	#15,d4
	and.b	d0,d4
	or.w	d4,d3
	lea	tile_ok,a0
	tst.b	(a0,d3.w)
	bne.s	.baked
	st	(a0,d3.w)
	bsr	bake_tile
.baked:	moveq	#0,d4
	move.w	d3,d4
	lsl.l	#5,d4
	lea	tile_bake,a0
	add.l	d4,a0
	rept	8
	move.l	(a0)+,d0
	movep.l	d0,(REPTN*LB)(a1)
	endr
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

; bake_tile: d3.w = the key.  tile_bake + key * 32: per row the 4 STE plane bytes (plane 0 first: a movep.l long).
; Keeps d3, d7, a1.
bake_tile:
	movem.l	d3/d7/a1,-(sp)
	move.w	d3,d0
	lsr.w	#4,d0			; flips << 8 | code
	lsl.w	#5,d0			; (32 bytes a tile)
	lea	py_tiles,a2
	add.w	d0,a2
	moveq	#15,d0
	and.w	d3,d0
	lsl.w	#4,d0
	lea	py_tpen,a3
	add.w	d0,a3			; the colour's 16 pens' STE colours
	moveq	#0,d0
	move.w	d3,d0
	lsl.l	#5,d0
	lea	tile_bake,a4
	add.l	d0,a4
	moveq	#7,d6
.row:	move.b	(a2)+,d1		; the pens' bit planes 0-3
	move.b	(a2)+,d2
	move.b	(a2)+,d4
	move.b	(a2)+,d5
	lea	bake_pix,a5		; the 8 pixels' STE colours
	moveq	#7,d3
.px:	moveq	#0,d0
	add.b	d5,d5
	addx.b	d0,d0
	add.b	d4,d4
	addx.b	d0,d0
	add.b	d2,d2
	addx.b	d0,d0
	add.b	d1,d1
	addx.b	d0,d0
	move.b	(a3,d0.w),(a5)+
	dbf	d3,.px
	lea	bake_pix,a5		; packed into the 4 plane bytes
	moveq	#7,d3
.pk:	move.b	(a5)+,d0
	lsr.b	#1,d0
	addx.b	d1,d1
	lsr.b	#1,d0
	addx.b	d2,d2
	lsr.b	#1,d0
	addx.b	d4,d4
	lsr.b	#1,d0
	addx.b	d5,d5
	dbf	d3,.pk
	move.b	d1,(a4)+
	move.b	d2,(a4)+
	move.b	d4,(a4)+
	move.b	d5,(a4)+
	dbf	d6,.row
	movem.l	(sp)+,d3/d7/a1
	rts

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
	lea	(a2,d0.l),a0
	lea	(a3,d0.l),a1
	rept	8
	movep.l	(REPTN*LB)(a0),d1
	movep.l	d1,(REPTN*LB)(a1)
	endr
	dbf	d6,.c
.out:	rts

; ----------------------------------------------------------------------------------------------------------------------
; restore_damage: the buffer's last sprite rectangles from the clean screen (HOG passes of at most 32 words; the
; addresses run on)
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
; draw_sprites: the 24 entries ($9010-$903F / $9410-$943F), the one at $10 first (the last on top)
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
	lea	Z_RAM+$90\1,a0
	moveq	#0,d3
	moveq	#0,d5
	moveq	#0,d6
	moveq	#0,d7
	move.b	(a0),d5			; x: picture Y
	move.b	1(a0),d6		; code
	move.b	$400(a0),d7		; attributes
	move.b	$401(a0),d3		; y
	bsr	draw_one
	endm
	SLOT	10
	SLOT	12
	SLOT	14
	SLOT	16
	SLOT	18
	SLOT	1A
	SLOT	1C
	SLOT	1E
	SLOT	20
	SLOT	22
	SLOT	24
	SLOT	26
	SLOT	28
	SLOT	2A
	SLOT	2C
	SLOT	2E
	SLOT	30
	SLOT	32
	SLOT	34
	SLOT	36
	SLOT	38
	SLOT	3A
	SLOT	3C
	SLOT	3E
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
; (tools/assets.py: engine/sprite_programs.py) with the held registers; unprepared shapes and 64 KB crossings go to
; draw_cell (the row path).  d0 d3 d5-d7 a0 used.
draw_one:
	sub.w	#16,d3			; picture X
	cmp.w	#-16,d3
	ble	.out
	cmp.w	#224,d3
	bge	.out
	move.w	d3,cell_x
	and.w	#63,d6
	lsl.w	#6,d6
	add.w	d7,d7
	lea	key_attr,a0
	or.w	(a0,d7.w),d6		; the key: code << 6 | colour << 2 | flips
	move.w	d6,cell_key
	if REN_GEN=0
	bra	.slow
	endc
	moveq	#0,d0
	move.w	d6,d0
	lsl.w	#2,d0
	lea	sc_index,a0
	move.l	(a0,d0.w),d7		; the slot (rec.l, src.l, n, rows, planes)
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
	move.l	4(a0),B_SRC.w		; (the slot's aligned plane words)
	cmp.w	#16,last_mode
	beq.s	.set
	move.w	#16,last_mode
	clr.w	B_SXI.w			; (source X increment 0, Y increment 2: every pass type)
	move.w	#2,B_SYI.w
	move.w	#8,B_DXI.w
.set:	move.l	d6,a0			; the variant: its code, its stream
	move.l	(a0)+,-(sp)
	move.l	(a0),a0
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
; draws it a HOG pass a row, lists its damage.
draw_cell:
	move.w	d2,cell_key
	move.w	d3,cell_x
	move.w	d4,cell_y
	bsr	sprite_baked		; a0 = the slot
	addq.l	#8,a0			; (its header: the shape record, the aligned plane words' address)
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
	cmp.w	#DMG_MAX,spr_n		; the damage: the offset, the words a line, 16 lines
	bhs.s	.nod
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
	move.w	#8,B_DXI.w
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
	move.w	#8,B_DXI.w
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
	move.w	#8,B_DXI.w
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
	lsl.w	#2,d0
	move.l	(a0,d0.w),d1
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
	move.l	a0,(a1,d0.w)
	movem.l	d2-d7/a0-a6,-(sp)
	bsr	bake_sprite
	movem.l	(sp)+,d2-d7/a0-a6
	rts

; bake_sprite: d2 = the key (code << 6 | colour << 2 | flip x << 1 | flip y), a0 = the slot.
; The shape's record, the aligned plane words' address, n, (row * 160, mask << 16) for the opaque rows in py_order's
; order, then their 4 plane words, then the same aligned.  py_spr: per code the turned sprite's 16 rows of 4 pen plane
; words, then the same with the bits reversed; MAME's flip x reverses the rows, flip y the bits (the second copy).
bake_sprite:
	move.w	d2,d0
	lsr.w	#6,d0			; the code
	lsl.w	#8,d0			; 256 bytes a code
	lea	py_spr,a1
	add.w	d0,a1
	btst	#0,d2
	beq.s	.nfy
	lea	128(a1),a1		; (flip y: the bit-reversed copy)
.nfy:	move.w	d2,d0
	and.w	#$3C,d0			; colour * 4
	lsl.w	#2,d0			; colour * 16
	lea	py_spen,a2
	add.w	d0,a2			; its 16 pens' STE colours ($FF: transparent)
	lea	bake_rows,a3		; 16 x (mask, 4 planes)
	sub.l	a5,a5			; the row
.row:	move.w	a5,d0
	btst	#1,d2
	beq.s	.nfx
	eor.w	#15,d0			; (flip x: the rows from the last)
.nfx:	lsl.w	#3,d0
	movem.w	(a1,d0.w),d3-d6		; the pens' bit planes 0-3
	lea	bake_pix,a4		; the 16 pixels' STE colours
	moveq	#15,d1
.px:	moveq	#0,d0
	add.w	d6,d6
	addx.w	d0,d0
	add.w	d5,d5
	addx.w	d0,d0
	add.w	d4,d4
	addx.w	d0,d0
	add.w	d3,d3
	addx.w	d0,d0
	move.b	(a2,d0.w),(a4)+
	dbf	d1,.px
	lea	bake_pix,a4		; packed: the opaque mask, the 4 planes
	moveq	#0,d0
	moveq	#0,d3
	moveq	#0,d4
	moveq	#0,d5
	moveq	#0,d6
	moveq	#15,d1
.pk:	add.w	d0,d0
	add.w	d3,d3
	add.w	d4,d4
	add.w	d5,d5
	add.w	d6,d6
	move.b	(a4)+,d7
	bmi.s	.tr
	addq.w	#1,d0
	lsr.b	#1,d7
	bcc.s	.b1
	addq.w	#1,d3
.b1:	lsr.b	#1,d7
	bcc.s	.b2
	addq.w	#1,d4
.b2:	lsr.b	#1,d7
	bcc.s	.b3
	addq.w	#1,d5
.b3:	lsr.b	#1,d7
	bcc.s	.tr
	addq.w	#1,d6
.tr:	dbf	d1,.pk
	move.w	d0,(a3)+
	move.w	d3,(a3)+
	move.w	d4,(a3)+
	move.w	d5,(a3)+
	move.w	d6,(a3)+
	addq.w	#1,a5
	cmp.w	#16,a5
	bne	.row
	; the slot: the shape's record (py_shapes), the aligned plane words' address, the opaque rows in py_order's order
	; (grouped by mask: the generated code's order), their plane words, the same aligned
	moveq	#0,d0			; shape = class << 8 | code << 2 | flips
	move.w	d2,d0
	lsr.w	#2,d0
	and.w	#15,d0
	lea	py_tclass,a4
	move.b	(a4,d0.w),d0		; the colour's transparency class
	lsl.w	#8,d0
	move.w	d2,d1
	lsr.w	#4,d1
	and.w	#$FC,d1			; code << 2
	or.w	d1,d0
	moveq	#3,d1
	and.w	d2,d1
	or.w	d1,d0
	move.w	d0,d1
	add.w	d1,d1
	add.w	d1,d1
	lea	py_shapes,a4
	move.l	(a4,d1.w),(a0)+
	move.l	a0,a5			; (the aligned plane words' address: below)
	addq.l	#4,a0
	lsl.w	#4,d0			; (py_order: 16 bytes a shape)
	lea	py_order,a4
	add.w	d0,a4
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
	include	"py_assets.s"
py_spr:		incbin	"py_spr.bin"
py_tiles:	incbin	"py_tiles.bin"
py_order:	incbin	"py_order.bin"
py_sstream:	incbin	"py_sstream.bin"
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
dmg_n:		ds.w	NBUF
dl_n:		ds.w	NBUF
frame_ready:	ds.b	1
tiles_full:	ds.b	1
	even
dmg_list:	ds.b	NBUF*DMG_MAX*8		; per buffer: (offset.l, words a line.w, lines.w) a sprite
line_off:	ds.l	256+16			; the offset of picture line Y in a buffer
key_attr:	ds.w	256			; the cache key's part of the attributes (colour << 2, flips)
cell_off:	ds.l	1024
tile_copy:	ds.b	2048
dl_flag:	ds.b	NBUF*1024
dl_list:	ds.w	NBUF*1024
bake_rows:	ds.w	16*5
bake_pix:	ds.b	16
sc_index:	ds.l	4096			; per key: its slot (0: not baked)
sc_data:	ds.b	SC_SLOTS*SC_SIZE
tile_ok:	ds.b	TILE_KEYS		; per tile key: baked
tile_bake:	ds.b	TILE_KEYS*32		; per tile key: 8 rows of 4 plane bytes
	cnop	0,256
buffers:	ds.b	(NBUF+1)*BUFSZ
	section text,code
