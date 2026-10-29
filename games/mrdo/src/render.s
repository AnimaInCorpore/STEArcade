; Mr. Do!'s picture on the STE (included by mrdo.s), after Time Pilot's renderer (games/timeplt/src/render.s).
;
; The arcade's screen is turned as MAME's ROT270 turns it (tools/assets.py): the picture is 192 x 240, picture pixel
; (X, Y) the raw pixel (x = 247 - Y, y = 32 + X), centred in the 320-pixel screen: black side bands of 64 pixels (four
; 16-pixel groups: the picture's edges lie on group boundaries), borders open (engine/rt/borders.s, PIC_TOP 18,
; PIC_LINES 240).  One palette (md_pal: 16 fitted colours, every pen mapped to the nearest).
;
; Buffers of BL lines x 160 bytes: buffer line = GUARD + Y (picture line 0 at GUARD; the display starts PIC_TOP lines
; above it), screen x = 64 + X.  The lines above and below the picture are guard lines for whole sprites (a sprite's
; picture Y is -23 .. 232).  Three display buffers and a clean screen.
;
; Tiles: raw cell (tx, ty) (video RAM offset ty * 32 + tx) is the picture's 8 x 8 cell at X = 8 ty - 32, Y = 240 - 8 tx
; (ty 4-27, tx 1-30 shown): a byte of each plane in its 16-pixel group.  The two layers are kept converted to STE
; planes (tile_conv: the colour's four pens from sel_tab, long operations on md_tiles' rows):
; * the background (scrolled: picture column X shows its column X + 32 + scroll y, mod 256) in bg_img: per raw column
;   tx a band of 8 lines x 256 pixels, a cell's byte at its 8-pixel chunk;
; * the foreground per cell in fg_cache: a row's four plane bytes (a long, movep order) and the bits to keep of what
;   is below (its transparent pixels), fg_kind 0 (empty), 1 (partly transparent), 2 (opaque).
; A changed video RAM cell (the writers' cell_list, compared with vcopy) updates its layer and marks the screen cells it
; shows in (sd_list); a new scroll value marks the rows with background content (not under opaque foreground).  A
; marked cell is composited (the background's bytes, shifted when the scroll is not a multiple of 8, the foreground
; over them) into the clean screen with movep.l and listed for each display buffer.  A buffer is brought to the new
; picture from the clean screen: its last sprites' rectangles (short HOG Blitter copies), its listed cells (movep.l);
; then the sprites are drawn over everything (entry 63 first: entry 0 on top) and the buffer is published for the
; next VBL.
;
; Sprites: an entry (code, 256 - y, attributes: colour 0-3, flip x 4, flip y 5; x) at $9000 + 4 n is the 16 x 16
; picture square at X = 224 - byte 1, Y = 232 - byte 3 (byte 1 = 0: not shown).  The generated code of its shape and
; shift (tools/assets.py sprite_programs, engine/sprite_programs.py: rows grouped by mask, one- or two-word passes as
; stefastbobs2 chooses them, end masks from a stream) draws it from the sprite cache's aligned plane words (baked on
; first use per code, colour and flips); shapes the coverage did not see, and 64 KB crossings, take the row path
; (draw_cell: a HOG pass a row).  Clipped at the picture's group-aligned left and right edges (AGENTS.md: the inner
; word only), culled wholly outside; top and bottom: whole into the guard lines.

	ifnd REN_GEN
REN_GEN = 1				; 1: the generated shape code (tools/assets.py sprite_programs)
	endc
GUARD = 24				; buffer lines above the picture
BL = 284				; buffer lines: GUARD, the picture's 240, 20 guard lines
LB = 160
BUFSZ = BL*LB
NBUF = 3
PIC0 = GUARD*LB				; the picture's line 0 in a buffer
VIEW = (GUARD-PIC_TOP)*LB		; the video base's offset in a buffer
LEFT = 64				; the picture's left edge (screen x)
PICW = 192
SC_SLOTS = 1024				; sprite cache slots
SC_SIZE = 8+2+16*6+16*8+16*8		; the shape record, the aligned plane words' address, n, (row * 160, mask << 16) a row, the 4 plane words a row (the row path), the same aligned (the generated code)
DMG_MAX = 64				; the entries

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
; init_render: the buffers black, the caches empty, the palettes, the tables
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
	lea	md_pal,a0		; the palettes: the picture's, black around it
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
	cmp.w	#4,d1
	blo.s	.st
	cmp.w	#27,d1
	bhi.s	.st
	cmp.w	#1,d2
	blo.s	.st
	cmp.w	#30,d2
	bhi.s	.st
	move.w	d1,d3			; screen x = 64 + 8 ty - 32
	lsl.w	#3,d3
	add.w	#LEFT-32,d3
	move.w	d3,d4
	lsr.w	#4,d4
	lsl.w	#3,d4			; the group's byte
	btst	#3,d3
	beq.s	.hi
	addq.w	#1,d4			; (the right half: the odd byte)
.hi:	move.w	#240,d0			; picture Y = 240 - 8 tx
	move.w	d2,d3
	lsl.w	#3,d3
	sub.w	d3,d0
	mulu	#LB,d0
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
	lea	line_off,a0		; buffer line L's offset
	moveq	#0,d0
	move.w	#BL-1,d1
.lo:	move.l	d0,(a0)+
	add.l	#LB,d0
	dbf	d1,.lo
	lea	key_attr,a1		; the cache key's part of the attributes: colour << 2 | flip x << 1 | flip y
	moveq	#0,d0
.ky:	moveq	#$0F,d1
	and.w	d0,d1
	lsl.w	#2,d1
	btst	#4,d0
	beq.s	.kb
	or.w	#2,d1			; flip x (raw x mirrored: the turned rows reversed)
.kb:	btst	#5,d0
	beq.s	.kc
	or.w	#1,d1			; flip y (the bits reversed)
.kc:	move.w	d1,(a1)+
	addq.w	#1,d0
	cmp.w	#256,d0
	bne.s	.ky
	; sel_tab: per (opaque << 6 | colour) the four pens' plane selections: a long, byte 3 - p $FF when the pen's STE
	; colour has bit p (movep order: plane 0 in the high byte); a transparent pen 0 is 0
	lea	sel_tab,a0
	moveq	#0,d1			; opaque << 6 | colour
.sl:	moveq	#0,d2			; the pen
.sp:	moveq	#0,d3
	move.w	d1,d4
	and.w	#$3F,d4
	lsl.w	#2,d4
	add.w	d2,d4
	lea	md_cpen,a1
	move.b	(a1,d4.w),d3		; its STE colour
	tst.w	d2
	bne.s	.so
	btst	#6,d1
	bne.s	.so
	moveq	#0,d3			; (pen 0 of a transparent cell: the black of an empty screen)
.so:	moveq	#0,d5
	moveq	#0,d4			; the plane
.sb:	lsl.l	#8,d5
	btst	d4,d3
	beq.s	.sn
	move.b	#$FF,d5
.sn:	addq.w	#1,d4
	cmp.w	#4,d4
	bne.s	.sb
	move.l	d5,(a0)+
	addq.w	#1,d2
	cmp.w	#4,d2
	bne.s	.sp
	addq.w	#1,d1
	cmp.w	#128,d1
	bne.s	.sl
	; tile_blank: per character (the foreground's 512, the background's) 1 when it has no pixel
	lea	md_tiles,a0
	lea	tile_blank,a1
	move.w	#1023,d1
.tb:	moveq	#15,d2
	moveq	#0,d0
.tw:	or.l	(a0)+,d0
	dbf	d2,.tw
	tst.l	d0
	seq	(a1)+
	dbf	d1,.tb
	; himask: per shift 1-7 the bits of each byte that come from the left chunk
	lea	himask,a0
	moveq	#0,d1
.hm:	moveq	#-1,d0			; ($FF << sh) & $FF in each byte
	move.b	#$FF,d2
	lsl.b	d1,d2
	move.b	d2,d0
	lsl.l	#8,d0
	move.b	d2,d0
	lsl.l	#8,d0
	move.b	d2,d0
	lsl.l	#8,d0
	move.b	d2,d0
	move.l	d0,(a0)+
	addq.w	#1,d1
	cmp.w	#8,d1
	bne.s	.hm
	; the video base: buffer 0
	move.l	buf_base,d0
	add.l	#VIEW,d0
	move.l	d0,-(sp)
	move.b	1(sp),$ffff8201.w
	move.b	2(sp),$ffff8203.w
	move.b	3(sp),$ffff820d.w
	addq.l	#4,sp
	rts

cache_flush:
	lea	sc_index,a0
	move.w	#32768/4-1,d0
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
	add.l	#VIEW,d0
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
; render_tiles: the written cells (cell_list: the video RAM offset & $3FF, + $400 for the foreground) against vcopy;
; a changed one converted into its layer and its screen cells marked; a new scroll value marks the rows with
; background content; the marked cells composited.  The first time, and after a block copy: every cell.
; ----------------------------------------------------------------------------------------------------------------------
render_tiles:
	moveq	#0,d0
	move.b	Z_RAM+$F800,d0		; the background's scroll (raw y: picture X)
	move.w	d0,scroll_now
	tst.b	tiles_full
	bne	.full
	tst.b	tiles_all
	bne	.full
	move.l	cell_ptr,a4
	lea	cell_list,a3
	cmp.l	a3,a4
	beq	.scr
	move.l	a3,cell_ptr
.cell:	move.w	(a3)+,d7		; a written cell
	lea	cell_dirty,a2
	clr.b	(a2,d7.w)
	move.w	d7,d6
	and.w	#$3FF,d6
	lea	vcopy,a1
	add.w	d6,a1			; (its copy: attributes, code at +$400; the foreground's at +$800, +$C00)
	btst	#10,d7
	bne.s	.fg
	lea	Z_RAM+$8000,a0
	add.w	d6,a0
	move.b	(a0),d0			; attributes
	move.b	$400(a0),d1		; code
	cmp.b	(a1),d0
	bne.s	.bch
	cmp.b	$400(a1),d1
	beq.s	.same
.bch:	move.b	d0,(a1)
	move.b	d1,$400(a1)
	movem.l	a3-a4,-(sp)
	bsr	bg_changed
	movem.l	(sp)+,a3-a4
	bra.s	.same
.fg:	lea	Z_RAM+$8800,a0
	add.w	d6,a0
	move.b	(a0),d0
	move.b	$400(a0),d1
	cmp.b	$800(a1),d0
	bne.s	.fch
	cmp.b	$C00(a1),d1
	beq.s	.same
.fch:	move.b	d0,$800(a1)
	move.b	d1,$C00(a1)
	movem.l	a3-a4,-(sp)
	bsr	fg_changed
	movem.l	(sp)+,a3-a4
.same:	cmp.l	a4,a3
	blo.s	.cell
.scr:	move.w	scroll_now,d0
	cmp.w	scroll_last,d0
	beq.s	.comp
	move.w	d0,scroll_last
	bsr	scroll_marks
.comp:	bra	composite
.full:	sf	tiles_full
	sf	tiles_all
	move.w	scroll_now,scroll_last
	lea	cell_dirty,a0		; (the list emptied)
	move.w	#2048/4-1,d0
.cd:	clr.l	(a0)+
	dbf	d0,.cd
	move.l	#cell_list,cell_ptr
	lea	bg_blank,a0		; (the background empty: bg_changed counts from there)
	move.w	#1024/4-1,d0
.bk:	move.l	#$01010101,(a0)+
	dbf	d0,.bk
	lea	row_cnt,a0
	moveq	#31,d0
.rc:	clr.w	(a0)+
	dbf	d0,.rc
	moveq	#0,d6
.fc:	lea	Z_RAM+$8000,a0
	add.w	d6,a0
	lea	vcopy,a1
	add.w	d6,a1
	move.b	(a0),d0
	move.b	$400(a0),d1
	move.b	d0,(a1)
	move.b	d1,$400(a1)
	move.b	$800(a0),$800(a1)
	move.b	$C00(a0),$C00(a1)
	move.w	d6,-(sp)
	bsr	bg_changed
	move.w	(sp),d6
	lea	Z_RAM+$8800,a0
	add.w	d6,a0
	move.b	(a0),d0
	move.b	$400(a0),d1
	bsr	fg_changed
	move.w	(sp)+,d6
	addq.w	#1,d6
	cmp.w	#1024,d6
	blo.s	.fc
	moveq	#0,d0			; every shown cell
.fm:	bsr	mark_cell
	addq.w	#1,d0
	cmp.w	#1024,d0
	blo.s	.fm
	bra	composite

; mark_cell: d0.w = a screen cell (ty * 32 + tx): listed for composite once, when shown.  d1 / a0 used.
mark_cell:
	move.w	d0,d1
	add.w	d1,d1
	add.w	d1,d1
	lea	cell_off,a0
	tst.l	(a0,d1.w)
	bmi.s	.out
	lea	sd_flag,a0
	tst.b	(a0,d0.w)
	bne.s	.out
	st	(a0,d0.w)
	move.w	sd_n,d1
	add.w	d1,d1
	lea	sd_list,a0
	move.w	d0,(a0,d1.w)
	addq.w	#1,sd_n
.out:	rts

; tile_conv: a0 = a character's 8 rows (md_tiles), a1 = its colour's 4 selections (sel_tab), a2 = 8 longs out: a row's
; four plane bytes (movep order).  d0-d7 used.
tile_conv:
	movem.l	(a1),d4-d7		; S0-S3
	rept	8
	move.l	(a0)+,d0		; the pens' bit 0 (in each byte)
	move.l	(a0)+,d1		; bit 1
	move.l	d0,d2
	and.l	d1,d2
	and.l	d7,d2			; pen 3
	move.l	d1,d3
	not.l	d3
	and.l	d0,d3
	and.l	d5,d3			; pen 1
	or.l	d3,d2
	move.l	d0,d3
	not.l	d3
	and.l	d1,d3
	and.l	d6,d3			; pen 2
	or.l	d3,d2
	move.l	d0,d3
	or.l	d1,d3
	not.l	d3
	and.l	d4,d3			; pen 0
	or.l	d3,d2
	move.l	d2,(a2)+
	endr
	rts

; bg_changed: d6.w = the background cell (bty * 32 + tx), d0.b its attributes, d1.b its code: converted into bg_img,
; the row counts kept, its screen cells marked (two when the scroll is not a multiple of 8).
bg_changed:
	moveq	#0,d2			; the character: 512 + code (+ 256: attribute bit 7)
	move.b	d1,d2
	btst	#7,d0
	beq.s	.c8
	add.w	#256,d2
.c8:	add.w	#512,d2
	moveq	#0,d3			; the selections: (opaque << 6 | colour) * 16
	move.b	d0,d3
	and.w	#$7F,d3
	lsl.w	#4,d3
	lea	sel_tab,a1
	add.w	d3,a1
	lea	tile_blank,a0		; empty: no pixel and transparent
	move.b	(a0,d2.w),d4
	btst	#6,d0
	beq.s	.ob
	moveq	#0,d4
.ob:	moveq	#31,d5
	and.w	d6,d5			; tx
	lea	bg_blank,a0
	move.b	(a0,d6.w),d3
	move.b	d4,(a0,d6.w)
	lea	row_cnt,a0
	add.w	d5,d5
	tst.b	d3
	beq.s	.wasn
	tst.b	d4
	bne.s	.cnt
	addq.w	#1,(a0,d5.w)		; (empty -> content)
	bra.s	.cnt
.wasn:	tst.b	d4
	beq.s	.cnt
	subq.w	#1,(a0,d5.w)		; (content -> empty)
.cnt:	tst.w	(a0,d5.w)
	beq.s	.nh
	lea	row_had,a0
	lsr.w	#1,d5
	st	(a0,d5.w)
.nh:	lsl.w	#6,d2			; (64 bytes a character)
	lea	md_tiles,a0
	add.l	d2,a0
	lea	conv_out,a2
	move.w	d6,-(sp)
	bsr	tile_conv
	move.w	(sp)+,d6
	moveq	#31,d5
	and.w	d6,d5			; tx: its band in bg_img (1024 bytes)
	move.w	d6,d4
	lsr.w	#5,d4			; bty: its chunk
	moveq	#10,d0
	lsl.w	d0,d5
	lea	bg_img,a0
	add.w	d5,a0
	move.w	d4,d0
	lsr.w	#1,d0
	lsl.w	#3,d0
	btst	#0,d4
	beq.s	.ev
	addq.w	#1,d0
.ev:	add.w	d0,a0
	lea	conv_out,a2
	moveq	#0,d1
	rept	8
	move.l	(a2)+,d0
	movep.l	d0,REPTN*128(a0)
	endr
	; its screen cells: ty = ((8 bty - scroll) & 255) / 8, and the next when the scroll is not a multiple of 8
	move.w	d4,d2
	lsl.w	#3,d2
	sub.w	scroll_now,d2
	and.w	#255,d2
	lsr.w	#3,d2
	moveq	#31,d3
	and.w	d6,d3			; tx
	move.w	d2,d0
	lsl.w	#5,d0
	add.w	d3,d0
	bsr	mark_cell
	moveq	#7,d1
	and.w	scroll_now,d1
	beq.s	.out
	addq.w	#1,d2
	and.w	#31,d2
	move.w	d2,d0
	lsl.w	#5,d0
	add.w	d3,d0
	bsr	mark_cell
.out:	rts

; fg_changed: d6.w = the foreground cell, d0.b its attributes, d1.b its code: converted into fg_cache (value, the bits
; kept below), fg_kind, the cell marked.
fg_changed:
	moveq	#0,d2
	move.b	d1,d2
	btst	#7,d0
	beq.s	.c8
	add.w	#256,d2
.c8:	moveq	#0,d3
	move.b	d0,d3
	and.w	#$7F,d3
	lsl.w	#4,d3
	lea	sel_tab,a1
	add.w	d3,a1
	move.w	d6,d3			; the cache: 64 bytes a cell
	lsl.w	#6,d3
	lea	fg_cache,a3
	add.l	d3,a3
	lea	fg_kind,a2
	btst	#6,d0
	bne.s	.opq
	lea	tile_blank,a0
	tst.b	(a0,d2.w)
	beq.s	.part
	clr.b	(a2,d6.w)		; empty
	bra	.mark
.opq:	move.b	#2,(a2,d6.w)		; opaque: the values only (nothing kept below)
	lsl.w	#6,d2
	lea	md_tiles,a0
	add.l	d2,a0
	lea	conv_out,a2
	move.w	d6,-(sp)
	bsr	tile_conv
	move.w	(sp)+,d6
	lea	conv_out,a2
	rept	8
	move.l	(a2)+,(a3)+
	clr.l	(a3)+
	endr
	bra	.mark
.part:	lsl.w	#6,d2
	lea	md_tiles,a0
	add.l	d2,a0
	move.l	a0,-(sp)
	lea	conv_out,a2
	move.w	d6,-(sp)
	bsr	tile_conv
	move.w	(sp)+,d6
	move.l	(sp)+,a0
	lea	conv_out,a2
	moveq	#0,d2			; (the kept bits of all rows: none -> opaque after all)
	rept	8
	move.l	(a2)+,(a3)+
	move.l	(a0)+,d0
	or.l	(a0)+,d0
	not.l	d0
	or.l	d0,d2
	move.l	d0,(a3)+
	endr
	lea	fg_kind,a2
	moveq	#1,d0
	tst.l	d2
	bne.s	.k
	moveq	#2,d0
.k:	move.b	d0,(a2,d6.w)
.mark:	move.w	d6,d0
	bra	mark_cell

; scroll_marks: a new scroll value: the shown cells of the rows that have (or had) background content, unless under
; opaque foreground
scroll_marks:
	lea	row_cnt+2,a3
	lea	row_had+1,a4
	moveq	#1,d6			; tx
.r:	tst.w	(a3)
	bne.s	.m
	tst.b	(a4)
	beq.s	.n
.m:	tst.w	(a3)
	sne	(a4)
	moveq	#4,d5			; ty
.c:	move.w	d5,d0
	lsl.w	#5,d0
	add.w	d6,d0
	lea	fg_kind,a0
	cmp.b	#2,(a0,d0.w)
	beq.s	.s
	bsr	mark_cell
.s:	addq.w	#1,d5
	cmp.w	#28,d5
	bne.s	.c
.n:	addq.l	#2,a3
	addq.l	#1,a4
	addq.w	#1,d6
	cmp.w	#31,d6
	bne.s	.r
	rts

; composite: the marked cells into the clean screen (the background's bytes, shifted, the foreground over them), each
; listed for each display buffer
composite:
	move.w	sd_n,d7
	beq	.out
	clr.w	sd_n
	subq.w	#1,d7
	lea	sd_list,a6
.cell:	move.w	(a6)+,d6		; the cell
	lea	sd_flag,a0
	clr.b	(a0,d6.w)
	move.w	d6,d0
	add.w	d0,d0
	add.w	d0,d0
	lea	cell_off,a0
	move.l	(a0,d0.w),d0
	move.l	buf_base+NBUF*4,a1
	add.l	d0,a1			; its first byte in the clean screen
	move.w	d6,d0			; the foreground's cache
	lsl.w	#6,d0
	lea	fg_cache,a2
	add.l	d0,a2
	lea	fg_kind,a0
	move.b	(a0,d6.w),d4
	cmp.b	#2,d4
	beq	.opq
	moveq	#31,d0			; the background: bg_img's band tx, chunk (8 ty + scroll) / 8
	and.w	d6,d0
	moveq	#10,d1
	lsl.w	d1,d0
	lea	bg_img,a0
	add.w	d0,a0
	move.w	d6,d1
	lsr.w	#5,d1
	lsl.w	#3,d1
	add.w	scroll_now,d1
	and.w	#255,d1
	moveq	#7,d5
	and.w	d1,d5			; the shift
	lsr.w	#3,d1			; the chunk
	move.w	d1,d0
	lsr.w	#1,d0
	lsl.w	#3,d0
	btst	#0,d1
	beq.s	.e0
	addq.w	#1,d0
.e0:	lea	(a0,d0.w),a3		; the chunk's first byte
	tst.w	d5
	bne	.sh
	tst.b	d4
	bne.s	.mix0
	rept	8
	movep.l	REPTN*128(a3),d0
	movep.l	d0,REPTN*LB(a1)
	endr
	bra	.list
.mix0:	rept	8
	movep.l	REPTN*128(a3),d0
	and.l	4(a2),d0
	or.l	(a2),d0
	addq.l	#8,a2
	movep.l	d0,REPTN*LB(a1)
	endr
	bra	.list
.opq:	rept	8
	move.l	(a2),d0
	addq.l	#8,a2
	movep.l	d0,REPTN*LB(a1)
	endr
	bra	.list
.sh:	addq.w	#1,d1			; the next chunk (mod 32)
	and.w	#31,d1
	move.w	d1,d0
	lsr.w	#1,d0
	lsl.w	#3,d0
	btst	#0,d1
	beq.s	.e1
	addq.w	#1,d0
.e1:	lea	(a0,d0.w),a4
	move.w	d5,d0
	add.w	d0,d0
	add.w	d0,d0
	lea	himask,a0
	move.l	(a0,d0.w),d2		; the left chunk's bits
	move.l	d2,d3
	not.l	d3			; the right chunk's
	moveq	#8,d1
	sub.w	d5,d1
	tst.b	d4
	bne	.mixs
	rept	8
	movep.l	REPTN*128(a3),d0
	lsl.l	d5,d0
	and.l	d2,d0
	movep.l	REPTN*128(a4),d4
	lsr.l	d1,d4
	and.l	d3,d4
	or.l	d4,d0
	movep.l	d0,REPTN*LB(a1)
	endr
	bra	.list
.mixs:	rept	8
	movep.l	REPTN*128(a3),d0
	lsl.l	d5,d0
	and.l	d2,d0
	movep.l	REPTN*128(a4),d4
	lsr.l	d1,d4
	and.l	d3,d4
	or.l	d4,d0
	and.l	4(a2),d0
	or.l	(a2),d0
	addq.l	#8,a2
	movep.l	d0,REPTN*LB(a1)
	endr
.list:	lea	dl_flag,a0		; listed for each display buffer
	lea	dl_n,a1
	lea	dl_list,a2
	moveq	#NBUF-1,d1
.lb:	tst.b	(a0,d6.w)
	bne.s	.nl
	st	(a0,d6.w)
	move.w	(a1),d2
	add.w	d2,d2
	move.w	d6,(a2,d2.w)
	addq.w	#1,(a1)
.nl:	lea	1024(a0),a0
	addq.l	#2,a1
	lea	2048(a2),a2
	dbf	d1,.lb
	dbf	d7,.cell
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
; restore_damage: the buffer's last sprite rectangles from the clean screen (HOG passes of at most 32 words each; the
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
; draw_sprites: the 64 entries ($9000-$90FF), the 63rd first (entry 0 on top)
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
	move.l	#Z_RAM+$90FC,spr_ptr
.e:	move.l	spr_ptr,a0
	moveq	#0,d3
	move.b	1(a0),d3		; 256 - y
	beq.s	.n			; (0: not shown)
	moveq	#0,d5
	moveq	#0,d6
	moveq	#0,d7
	move.b	(a0),d6
	and.b	#$7F,d6			; code
	move.b	2(a0),d7		; attributes
	moveq	#0,d0
	move.b	3(a0),d0
	move.w	#GUARD+232,d5		; buffer line = GUARD + 232 - x
	sub.w	d0,d5
	neg.w	d3
	add.w	#224,d3			; picture X = 224 - byte 1
	bsr	draw_one
.n:	subq.l	#4,spr_ptr
	cmp.l	#Z_RAM+$9000,spr_ptr
	bhs.s	.e
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

; draw_one: d3 = picture X, d5 = buffer line, d6 = code, d7 = attributes (zero-extended).  The generated path
; (tools/assets.py sprite_programs) with the held registers; unprepared shapes and 64 KB crossings go to draw_cell (the
; row path).  d0 d3 d5-d7 a0 used.
draw_one:
	cmp.w	#-16,d3
	ble	.out
	cmp.w	#PICW,d3
	bge	.out
	move.w	d3,cell_x
	move.w	d5,cell_y
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
	if REN_GEN=0
	moveq	#0,d6
	endc
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
	cmp.w	#LEFT+PICW-16,d3
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
	move.w	cell_y,d4
	bsr	draw_cell
	movem.l	(sp)+,d1-d2/d4/a1-a6
	rts

; draw_cell: d2 = the key, d3 = picture X (-15 .. 191), d4 = buffer line.  Bakes it on a miss, clips it at the edges,
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
.l:	cmp.w	#LEFT+PICW-16,d0
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
	addq.w	#1,spr_n
	move.l	dmg_ptr,a1
	move.l	d1,(a1)+
	move.w	d4,(a1)+
	move.w	#16,(a1)+
	move.l	a1,dmg_ptr
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
; n, (row * 160, mask) for the opaque rows in row order, then their 4 plane words.  md_spr: per code the turned
; sprite's 16 rows of (pen bit 0, pen bit 1) words, then the same with the bits reversed; flip x reverses the rows,
; flip y the bits (the second copy).
bake_sprite:
	move.w	d2,d0
	lsr.w	#8,d0			; the code
	lsl.w	#7,d0			; 128 bytes a code
	lea	md_spr,a1
	add.w	d0,a1
	btst	#0,d2
	beq.s	.nfy
	lea	64(a1),a1		; (flip y: the bit-reversed copy)
.nfy:	moveq	#4,d1
	move.w	d2,d0
	and.w	#$FC,d0			; the colour * 4
	lea	md_spen,a2
	add.w	d0,a2			; its 4 pens' STE colours
	lea	bake_rows,a3		; 16 x (mask, 4 planes)
	moveq	#0,d7			; the row
.row:	move.w	d7,d0
	btst	#1,d2
	beq.s	.nfx
	eor.w	#15,d0			; (flip x: the rows from the last)
.nfx:	lsl.w	#2,d0
	move.w	(a1,d0.w),d3		; pen bit 0
	move.w	2(a1,d0.w),d4		; pen bit 1
	move.w	d3,d5			; masks of pens 1-3 (pen 0 transparent)
	not.w	d5
	and.w	d4,d5			; m2 = ~b0 b1
	move.w	d4,d6
	not.w	d6
	and.w	d3,d6			; m1 = b0 ~b1
	and.w	d4,d3			; m3 = b0 b1
	move.w	d5,d4
	or.w	d6,d4
	or.w	d3,d4			; the opaque mask
	move.w	d4,(a3)+
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
	cmp.w	d1,d0
	bne.s	.pl
	addq.w	#1,d7
	cmp.w	#16,d7
	bne	.row
	; the slot: the shape's record (md_shapes), the plane words' address, the opaque rows in md_order's order
	; (grouped by mask: the generated code's order), their plane words
	move.w	d2,d0			; shape = code << 2 | flips
	moveq	#3,d1
	and.w	d2,d1
	lsr.w	#8,d0
	lsl.w	#2,d0
	or.w	d1,d0
	move.w	d0,d1
	add.w	d1,d1
	add.w	d1,d1
	lea	md_shapes,a4
	move.l	(a4,d1.w),(a0)+
	move.l	a0,a5			; (the plane words' address: below)
	addq.l	#4,a0
	lsl.w	#4,d0			; (md_order: 16 bytes a shape)
	lea	md_order,a4
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
	include	"md_assets.s"
	even
md_tiles:	incbin	"md_tiles.bin"
md_spr:		incbin	"md_spr.bin"
md_order:	incbin	"md_order.bin"
md_sstream:	incbin	"md_sstream.bin"
	even

	section bss,bss
	even
buf_base:	ds.l	NBUF+1
draw_base:	ds.l	1
dmg_ptr:	ds.l	1
spr_ptr:	ds.l	1
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
sd_n:		ds.w	1
scroll_now:	ds.w	1
scroll_last:	ds.w	1
frame_ready:	ds.b	1
tiles_full:	ds.b	1
	even
dmg_list:	ds.b	NBUF*DMG_MAX*8		; per buffer: (offset.l, words a line.w, lines.w) a sprite
line_off:	ds.l	BL			; the offset of buffer line L
key_attr:	ds.w	256			; the cache key's part of the attributes (colour << 2, flips)
cell_off:	ds.l	1024			; a screen cell's first byte in a buffer (-1: not shown)
sel_tab:	ds.l	128*4			; per (opaque << 6 | colour) the four pens' plane selections
himask:		ds.l	8			; per shift the bytes' bits from the left chunk
conv_out:	ds.l	8
row_cnt:	ds.w	32			; per raw column tx: the background cells with content
row_had:	ds.b	32			; per tx: content since the last scroll change
vcopy:		ds.b	4096			; the video RAM as last converted
tile_blank:	ds.b	1024			; per character: no pixel
bg_blank:	ds.b	1024			; per background cell: empty
fg_kind:	ds.b	1024			; per foreground cell: 0 empty, 1 partly transparent, 2 opaque
sd_flag:	ds.b	1024			; the screen cells marked for composite
sd_list:	ds.w	1024
dl_flag:	ds.b	NBUF*1024
dl_list:	ds.w	NBUF*1024
bake_rows:	ds.w	16*5
	even
fg_cache:	ds.l	1024*16			; per foreground cell 8 x (the plane bytes, the bits kept below)
bg_img:		ds.b	32*1024			; per raw column tx: 8 lines x 128 bytes (256 pixels) of the background
sc_index:	ds.l	32768			; per key: its slot (0: not baked)
sc_data:	ds.b	SC_SLOTS*SC_SIZE
	cnop	0,256
buffers:	ds.b	(NBUF+1)*BUFSZ
