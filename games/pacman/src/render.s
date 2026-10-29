; Pac-Man's picture on the STE (included by pacman.s), after Time Pilot's renderer (games/timeplt/src/render.s).
;
; The arcade's screen is turned as MAME's ROT90 turns it (tools/assets.py): the picture is 224 wide, its column X the
; raw y = 223 - X, its line the raw x.  Screen x = 48 + X: black side bands of 48 pixels (three 16-pixel groups: the
; picture's edges lie on group boundaries).  Borders open (engine/rt/borders.s): Hatari shows 274 lines from buffer
; line GT.
;
; Buffers of BL lines x 160 bytes: buffer line = arcade line for the maze (24-271) and the sprites; the HUD rows
; elsewhere (tools/assets.py hud_line): row 0's lines 0-6 at 10-16, row 1's lines 9-15 at 17-23, rows 34-35's lines
; 275-286 at 272-283.  Not shown: lines 7, 8 and 272 (never drawn), 273 and row 2 (lines 16-23: only on the level-256
; split screen), 287 (hardly ever), 274 (the life and fruit icons' top line).  The bands (buffer lines 10-23 and 272
; on) hold tiles only: MAME clips the sprites to lines 16-271, so the
; lines of a sprite that reach a band are copied back from the clean screen after the sprites (band_restore).
;
; Colours: the STE pixel is the arcade's colour index (pm_pal: the palette PROM's first 16).  Three display buffers and
; a clean screen.  The clean screen holds the tiles: a cell the video RAM changes (render_tiles: the cells the program
; listed, cell_list) is drawn there with a converter of its colour (pm_tconv) and listed for each display buffer.  A
; buffer is brought to the new picture from the clean screen: its last sprites' rectangles (short HOG Blitter copies),
; its listed cells (movep.l); then the sprites are drawn (MAME's order: entries 7 to 3, then 2 to 0 one column to the
; left; each also 256 lines up, MAME's wrap) and the bands restored, and the buffer is published for the next VBL.
;
; Sprites: entry o (code / flips at $4FF0 + 2o, colour at $4FF1 + 2o, y at $5060 + 2o, x at $5061 + 2o) is the 16 x 16
; square at line 272 - x, X = 239 - y (238 - y for entries 0-2).  Baked on first use per (code, colour, flips) into a
; slot of the sprite cache: its opaque rows (the pens whose colour is not black) grouped by mask, so the Blitter's
; source address runs on (docs/sprite-preparation.md); the generated code of engine/sprite_programs.py for the shapes
; the coverage drew (tools/assets.py), the row path for the others.  Clipped at the picture's side edges (AGENTS.md:
; group-aligned): across the left edge only the second word, across the right only the first; wholly in a side band:
; culled.  Top and bottom: whole into the guard lines and the bands (restored).

GT = 10					; guard lines above the display (the wrapped sprites reach line 1)
BL = 288				; buffer lines
LB = 160
BUFSZ = BL*LB
NBUF = 3
LEFT = 48				; the picture's left edge (screen x)
BAND_TOP = 24				; buffer lines below this: the top band (and the guard)
BAND_BOT = 272				; from this one on: the bottom band
SC_SLOTS = 512				; sprite cache slots
SC_SIZE = 8+2+16*6+16*8+16*8		; the shape record, the aligned plane words' address, n, (row * 160, mask << 16) a row, the 4 plane words a row (the row path), the same aligned (the generated code)
DMG_MAX = 16				; damage rectangles a buffer (8 entries, their wrapped copies)

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
; init_render: the buffers black, the cache empty, the palette, the lines' offsets, the video base
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
	lea	pm_pal,a0		; the palette (one for the whole display: the bands are black)
	lea	$ffff8240.w,a1
	moveq	#15,d0
.pal:	move.w	(a0)+,(a1)+
	dbf	d0,.pal
	lea	line_off,a0		; buffer line L's offset
	moveq	#0,d0
	move.w	#BL+16-1,d1
.lo:	move.l	d0,(a0)+
	add.l	#LB,d0
	dbf	d1,.lo
	move.l	buf_base,d0		; the video base: buffer 0's line GT
	add.l	#GT*LB,d0
	move.l	d0,-(sp)
	move.b	1(sp),$ffff8201.w
	move.b	2(sp),$ffff8203.w
	move.b	3(sp),$ffff820d.w
	addq.l	#4,sp
	rts

cache_flush:
	lea	sc_index,a0
	move.w	#16384/4-1,d0
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
	add.l	#GT*LB,d0
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
	bsr	band_restore
	move.w	draw_idx,d0
	addq.b	#1,d0
	move.b	d0,frame_ready
	addq.w	#1,pic_count
	movem.l	(sp)+,d0-d7/a0-a6
	rts

; ----------------------------------------------------------------------------------------------------------------------
; render_tiles: the listed cells of the video RAM against tile_copy; each changed cell drawn into the clean screen and
; listed for each display buffer.  The first time, and after a block copy or fill (tiles_all): every cell.
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
	lea	cell_dirty,a2
	lea	G_Z80+$4000,a5		; codes
	lea	G_Z80+$4400,a0		; colours
	lea	tile_copy,a6
	lea	tile_copy+$400,a1
.cell:	move.w	(a3)+,d7		; a written cell: changed?
	clr.b	(a2,d7.w)
	move.b	(a5,d7.w),d1		; code
	move.b	(a0,d7.w),d0		; colour
	cmp.b	(a6,d7.w),d1
	bne.s	.chg
	cmp.b	(a1,d7.w),d0
	beq.s	.same
.chg:	move.b	d1,(a6,d7.w)
	move.b	d0,(a1,d7.w)
	movem.l	a0-a6,-(sp)
	bsr	tile_changed
	movem.l	(sp)+,a0-a6
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
.fc:	lea	G_Z80+$4000,a5
	lea	tile_copy,a6
	move.b	(a5,d7.w),d1
	move.b	d1,(a6,d7.w)
	lea	$400(a5),a5
	lea	$400(a6),a6
	move.b	(a5,d7.w),d0
	move.b	d0,(a6,d7.w)
	move.w	d7,-(sp)
	bsr	tile_changed
	move.w	(sp)+,d7
	addq.w	#1,d7
	cmp.w	#1024,d7
	blo.s	.fc
	rts

; tile_changed: d7.w = the cell, d0.b = its colour, d1.b = its code.  Drawn into the clean screen (pm_tconv: the
; colour's routine, the entry for the lines the cell shows), listed for the buffers (when shown).
tile_changed:
	move.w	d7,d2
	add.w	d2,d2
	add.w	d2,d2
	lea	pm_cells,a0
	move.l	(a0,d2.w),d2
	bmi	.out			; (not shown)
	move.l	buf_base+NBUF*4,a1
	add.l	d2,a1			; the first drawn line's byte in the clean screen
	moveq	#0,d3
	move.b	d1,d3
	lsl.w	#4,d3
	lea	pm_tiles,a0
	add.w	d3,a0
	moveq	#31,d3			; (colour * 4 + the kind) * 4
	and.w	d0,d3
	add.w	d3,d3
	add.w	d3,d3
	lea	pm_ckind,a3
	moveq	#0,d2
	move.b	(a3,d7.w),d2
	add.w	d2,d3
	add.w	d3,d3
	add.w	d3,d3
	lea	pm_tconv,a3
	move.l	(a3,d3.w),a3
	jsr	(a3)
	lea	dl_flag,a0		; listed for each display buffer
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

; copy_cell: d0.l = the cell's offset; 8 lines from the clean screen (a2) into the buffer (a3) (a cell of fewer lines
; copies lines of its neighbour too: the clean screen is the truth there as well).  d1 / a0 / a1 used.
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
	lea	pm_cells,a4
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
	bra	rect_copy
.out:	rts

; ----------------------------------------------------------------------------------------------------------------------
; band_restore: the lines of the sprites drawn now that reach into the bands, from the clean screen
; ----------------------------------------------------------------------------------------------------------------------
band_restore:
	move.l	band_ptr,d7
	lea	band_list,a0
	sub.l	a0,d7
	beq	.out
	lsr.w	#3,d7
	move.l	buf_base+NBUF*4,a2
	move.l	draw_base,a3
	bra	rect_copy
.out:	rts

; rect_copy: d7 = the rectangles at a0 (offset.l, words a line.w, lines.w) from a2 into a3
rect_copy:
	move.w	#$0203,B_HOP.w		; source
	moveq	#-1,d0
	move.w	d0,B_END1.w
	move.w	d0,B_END2.w
	move.w	d0,B_END3.w
	move.w	#2,B_SXI.w
	move.w	#2,B_DXI.w
	clr.b	B_SKEW.w
	move.w	#-1,last_mode
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
; draw_sprites: the 8 entries in MAME's order (7 to 3, then 2 to 0 one column to the left), each also 256 lines up
; when that copy reaches the maze (MAME's wrap; its lines in the top band are restored)
; ======================================================================================================================
draw_sprites:
	move.w	draw_idx,d0
	mulu	#DMG_MAX*8,d0
	lea	dmg_list,a0
	add.l	d0,a0
	move.l	a0,dmg_ptr
	clr.w	spr_n
	move.l	#band_list,band_ptr
	move.w	#-1,last_mode
	move.w	#$0203,B_HOP.w
	bsr	held_regs
SLOT	macro				; \1 = the entry's offset, \2 = the X base (239, or 238 for entries 0-2)
	moveq	#\1,d0
	move.w	#\2,d7
	bsr	draw_entry
	endm
	SLOT	14,239
	SLOT	12,239
	SLOT	10,239
	SLOT	8,239
	SLOT	6,239
	SLOT	4,238
	SLOT	2,238
	SLOT	0,238
	move.w	draw_idx,d0
	add.w	d0,d0
	lea	dmg_n,a0
	move.w	spr_n,(a0,d0.w)
	rts

; draw_entry: d0 = the entry's offset, d7 = 239 / 238.  The key, the line, X; culls; the wrapped copy.
draw_entry:
	lea	G_Z80+$4FF0,a0
	moveq	#0,d6
	move.b	1(a0,d0.w),d6		; colour
	and.w	#31,d6
	lea	pm_cpat,a0
	tst.b	(a0,d6.w)
	bmi	.out			; (every pen black: nothing drawn)
	lsl.w	#2,d6
	lea	G_Z80+$4FF0,a0
	moveq	#0,d3
	move.b	(a0,d0.w),d3		; code << 2 | flip y << 1 | flip x
	moveq	#3,d5
	and.w	d3,d5
	move.b	.flips(pc,d5.w),d5	; (the key: flip x << 1 | flip y)
	or.w	d5,d6
	lsr.w	#2,d3
	lsl.w	#8,d3
	or.w	d3,d6			; the key: code << 8 | colour << 2 | flips
	lea	G_Z80+$5060,a0
	moveq	#0,d3
	move.b	(a0,d0.w),d3		; y
	sub.w	d3,d7			; X
	move.w	d7,d3
	cmp.w	#-16,d3
	ble	.out
	cmp.w	#224,d3
	bge	.out
	moveq	#0,d5
	move.b	1(a0,d0.w),d5		; x
	neg.w	d5
	add.w	#272,d5			; the line
	cmp.w	#BAND_BOT,d5		; (from line 272 on: clipped away; the wrapped copy may show)
	bge.s	.wrap
	movem.w	d3/d5-d6,-(sp)
	bsr	note_bands
	bsr	draw_one
	movem.w	(sp)+,d3/d5-d6
.wrap:	cmp.w	#BAND_TOP+256-15,d5	; the copy 256 lines up reaches line 24?
	blt.s	.out
	sub.w	#256,d5
	bsr	note_bands
	bra	draw_one		; (its rts returns to the caller)
.out:	rts
.flips:	dc.b	0,2,1,3

; note_bands: d3 = X, d5 = the line: the sprite's lines in a band listed for band_restore.  Keeps d3 d5 d6.
note_bands:
	cmp.w	#BAND_TOP,d5
	blt.s	.top
	move.w	d5,d0
	add.w	#16,d0
	cmp.w	#BAND_BOT,d0
	bgt.s	.bot
	rts
.top:	move.w	d5,d0			; lines L .. 23
	moveq	#BAND_TOP,d1
	sub.w	d5,d1
	bra.s	.note
.bot:	move.w	#BAND_BOT,d0		; lines 272 .. L + 15
	move.w	d5,d1
	add.w	#16-BAND_BOT,d1
.note:	move.l	band_ptr,a0
	add.w	d0,d0
	add.w	d0,d0
	lea	line_off,a1
	move.l	(a1,d0.w),d0
	move.w	d3,d2
	add.w	#LEFT,d2
	moveq	#4,d4			; (one group, or two when shifted)
	moveq	#15,d7
	and.w	d2,d7
	beq.s	.w
	moveq	#8,d4
.w:	lsr.w	#4,d2
	lsl.w	#3,d2
	add.w	d2,d0
	move.l	d0,(a0)+
	move.w	d4,(a0)+
	move.w	d1,(a0)+
	move.l	a0,band_ptr
	bra	held_regs		; (d4 was the line's bytes)

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

; draw_one: d3 = X, d5 = the buffer line, d6 = the key.  The generated path (tools/assets.py, sprite_programs) with the
; held registers; clipped sprites, shapes without code and 64 KB crossings go to draw_cell (the row path).  d0 d3 d5-d7
; a0 used.
draw_one:
	move.w	d3,cell_x
	move.w	d5,cell_y
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
	cmp.w	#DMG_MAX,spr_n
	bhs.s	.draw
	move.l	dmg_ptr,a0
	move.l	d0,(a0)+		; the offset, the words a line, the lines
	moveq	#0,d0
	move.b	d7,d0
	lsr.w	#8,d7
	move.w	d7,(a0)+
	move.w	d0,(a0)+
	move.l	a0,dmg_ptr
	addq.w	#1,spr_n
.draw:	move.l	d3,B_DST.w		; (the high word; the code writes the low word)
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
	move.w	cell_y,d4
	bsr	draw_cell
	movem.l	(sp)+,d1-d2/d4/a1-a6
	rts

; draw_cell: d2 = the key, d3 = X (-15 .. 223), d4 = the buffer line.  Bakes it on a miss, clips it at the side
; edges, draws it row by row, lists its damage.
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
	cmp.w	#DMG_MAX,spr_n		; the damage: the offset, the words a line
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
; The shape's record, the plane words' address, n, (row * 160, mask) for the opaque rows in pm_order's order, then
; their 4 plane words, then the same aligned (the generated code's copy).  pm_spr: per code the turned sprite's 16 rows
; of (pen bit 0, pen bit 1) words, then the same with the bits reversed; MAME's flip x reverses the rows, flip y the
; bits (the second copy).  A pen is opaque when its colour is not black.
bake_sprite:
	move.w	d2,d0
	lsr.w	#8,d0			; the code
	lsl.w	#7,d0			; 128 bytes a code
	lea	pm_spr,a1
	add.w	d0,a1
	btst	#0,d2
	beq.s	.nfy
	lea	64(a1),a1		; (flip y: the bit-reversed copy)
.nfy:	move.w	d2,d0
	and.w	#$7C,d0			; the colour * 4
	lea	pm_cpen,a2
	add.w	d0,a2			; its 4 pens' colours
	lea	bake_rows,a3		; 16 x (mask, 4 planes)
	moveq	#0,d7			; the row
.row:	move.w	d7,d0
	btst	#1,d2
	beq.s	.nfx
	eor.w	#15,d0			; (flip x: the rows from the last)
.nfx:	lsl.w	#2,d0
	move.w	(a1,d0.w),d3		; pen bit 0
	move.w	2(a1,d0.w),d4		; pen bit 1
	move.w	d3,d5			; masks of pens 1-3 (pen 0 is black in every colour)
	not.w	d5
	and.w	d4,d5			; m2 = ~b0 b1
	move.w	d4,d6
	not.w	d6
	and.w	d3,d6			; m1 = b0 ~b1
	and.w	d4,d3			; m3 = b0 b1
	moveq	#0,d4			; the opaque mask: the pens whose colour is not black
	tst.b	1(a2)
	beq.s	.o2
	or.w	d6,d4
.o2:	tst.b	2(a2)
	beq.s	.o3
	or.w	d5,d4
.o3:	tst.b	3(a2)
	beq.s	.o4
	or.w	d3,d4
.o4:	move.w	d4,(a3)+
	moveq	#0,d0			; plane k = the masks of the pens whose colour has bit k
.pl:	moveq	#0,d4
	btst	d0,1(a2)
	beq.s	.p1
	or.w	d6,d4
.p1:	btst	d0,2(a2)
	beq.s	.p2
	or.w	d5,d4
.p2:	btst	d0,3(a2)
	beq.s	.p3
	or.w	d3,d4
.p3:	move.w	d4,(a3)+
	addq.w	#1,d0
	cmp.w	#4,d0
	bne.s	.pl
	addq.w	#1,d7
	cmp.w	#16,d7
	bne	.row
	; the slot: the shape's record (pm_shapes), the plane words' address, the opaque rows in pm_order's order (grouped
	; by mask: the generated code's order), their plane words
	move.w	d2,d0			; shape = pattern << 8 | code << 2 | flips
	lsr.w	#2,d0
	and.w	#31,d0
	lea	pm_cpat,a4
	moveq	#0,d1
	move.b	(a4,d0.w),d1
	lsl.w	#8,d1
	move.w	d2,d0
	lsr.w	#6,d0
	and.w	#$FC,d0
	or.w	d0,d1
	moveq	#3,d0
	and.w	d2,d0
	or.w	d0,d1
	move.w	d1,d0
	add.w	d1,d1
	add.w	d1,d1
	lea	pm_shapes,a4
	move.l	(a4,d1.w),(a0)+
	move.l	a0,a5			; (the plane words' address: below)
	addq.l	#4,a0
	lsl.w	#4,d0			; (pm_order: 16 bytes a shape)
	lea	pm_order,a4
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
	include	"pm_assets.s"
pm_spr:		incbin	"pm_spr.bin"
pm_tiles:	incbin	"pm_tiles.bin"
pm_order:	incbin	"pm_order.bin"
pm_sstream:	incbin	"pm_sstream.bin"
	even

	section bss,bss
	even
buf_base:	ds.l	NBUF+1
draw_base:	ds.l	1
dmg_ptr:	ds.l	1
band_ptr:	ds.l	1
shown_idx:	ds.w	1
prev_idx:	ds.w	1
draw_idx:	ds.w	1
pic_shown:	ds.w	1
pic_count:	ds.w	1
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
band_list:	ds.b	DMG_MAX*8		; band_restore: (offset.l, words a line, lines) a sprite's lines in a band
line_off:	ds.l	BL+16			; the offset of buffer line L
tile_copy:	ds.b	2048
dl_flag:	ds.b	NBUF*1024
dl_list:	ds.w	NBUF*1024
bake_rows:	ds.w	16*5
sc_index:	ds.l	16384			; per key: its slot (0: not baked)
sc_data:	ds.b	SC_SLOTS*SC_SIZE
	cnop	0,256
buffers:	ds.b	(NBUF+1)*BUFSZ
