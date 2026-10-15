; Kung-Fu Master's picture on the STE (included by kungfum.s).
;
; The arcade picture (256 x 256) is centred in the 320-pixel screen: black side bands of 32 pixels; borders open
; (engine/rt/borders.s, PIC_TOP 10, PIC_LINES 256).  Two sources, switched by borders.s' Timer B events (BD_HUD,
; BD_VSWITCH), each with its own 16 colours:
;
; * the score panel (tile rows 0-5, lines 0-47, never scrolled): one image of 48 lines x 160 bytes (hud_img), whose
;   cells are drawn when the tile RAM changes them (the panel's palette and pen map, kf_hudpal / kf_hudmap);
; * the playfield (tile rows 6-31, lines 48-255): hardware scrolled.  Three display rings and a clean screen are
;   virtual screens of RL lines x LB bytes: buffer x b shows tilemap x (b mod 512) (twin columns b and b + 512 for
;   b < 336), so the 320-pixel window at Wx = (scroll + 96) mod 512 is contiguous; buffer line = arcade line + 16
;   (guard lines above line 48 and below line 255 for whole sprites).  The window: the video address by words,
;   $ffff8265 by pixels (the line width 4 words less then).
;
; The clean screen holds the tiles (cells drawn with movep.l from baked cells when the tile RAM changes them; twins
; too).  A ring is brought to the new picture from the clean screen with short HOG Blitter passes (blit_go):
;   - the window's movement since the ring was drawn (at most MOVE_MAX pixels, else the whole window again): the
;     columns that came into the picture span copied, the band columns that were picture or came into view blackened;
;   - the damage of its last picture (its sprites' rectangles) copied back inside the span, black outside;
;   - the cells the tile RAM changed since (a bitmap per ring) copied inside the span;
; then the sprites are drawn (the first entry first: the last on top), the front tiles (colours 26-31, MAME's
; category 1) copied back over the sprites' cells, and the ring is published for the next VBL.
;
; The picture's edges lie at buffer x Wx + 32 and Wx + 288: on 16-pixel groups when Wx is.  Sprites are clipped at the
; word boundaries at or outside the edges (AGENTS.md: exactly at a group-aligned edge; at an edge inside a word, up to
; 15 pixels of a sprite show in the band, as whole sprites there would, and nothing is erased after drawing).  A cell
; across such a boundary draws only its inner destination word as a one-word pass (left: FXSR, source X increment 0,
; the row mask's second word as END1; right: the first word).  A cell wholly outside is culled.
;
; Sprites (stefastbobs2's preparation, docs/sprite-preparation.md): a cell (code, colour, flip x) is baked on first
; use into a slot of the sprite cache: its opaque rows (transparent rows left out) in an order that groups equal row
; masks, each with its row index and mask, then the rows' four plane words in that order, so the Blitter's source
; address runs on from row to row and END1 / END3 are written only when the mask changes.  A row is one HOG pass (Y
; count 4: the planes; X count 2 with NFSR when shifted, 1 when not).  -D REN_ORDER=0 keeps the rows in their
; natural order (the comparison of the README).
;
; Colours: kf_scene picks the scene (the floor while a game or the demo runs, else the attract screens); each scene
; has 16 colours and a map of the 512 pens (tools/assets.py).  A change of scene flushes the caches and draws
; everything again.

	ifnd REN_ORDER
REN_ORDER = 1
	endc

LB = 424				; bytes a buffer line (53 words: the window's 21 from any Wx < 512)
RL = 304				; buffer lines: arcade lines -16 .. 287 (cells from line 33 to 255 on)
ROW_OFF = 16				; buffer line = arcade line + 16
PF_TOP = 48+ROW_OFF			; the playfield's first buffer line (arcade line 48)
PF_LINES = 208
RINGSZ = LB*RL
NRING = 3
HUD_LB = 160
HUD_AREA = (PIC_TOP+48)*HUD_LB
TC_SLOTS = 2048				; tile cache slots (32 bytes: 8 rows of movep.l data)
	ifnd REN_SHIFTS
REN_SHIFTS = 0
	endc
SC_BASE = 2+16*4+16*8			; n, (row * 2, mask) a row, the 4 plane words a row
	if REN_SHIFTS
SC_SLOTS = 400				; sprite cache slots
SC_SIZE = SC_BASE+2+16*16*4		; + the shifts made (bits), the rows' END1:END3 longs for each shift
	else
SC_SLOTS = 600
SC_SIZE = SC_BASE
	endc
DMG_MAX = 32
MOVE_MAX = 48				; a window move up to this: strips; more: the whole window again

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

; pen_masks size,first: d0 / d1 / d2 = the row's planes 0-2 -> (a3): 8 masks of that size, pen p's pixels (pens
; first..7).  d0-d3 changed.
pen_masks macro
	move.\1	d0,d3
	and.\1	d1,d3			; p0 p1
	move.\1	d3,3*SZ\1(a3)
	move.\1	d0,d3
	not.\1	d1
	and.\1	d1,d3			; p0 ~p1
	move.\1	d3,1*SZ\1(a3)
	not.\1	d0
	move.\1	d0,d3
	and.\1	d1,d3			; ~p0 ~p1
	move.\1	d3,0*SZ\1(a3)
	not.\1	d1
	and.\1	d1,d0			; ~p0 p1
	move.\1	d0,2*SZ\1(a3)
	move.\1	0*SZ\1(a3),d0		; pens 4-7: & p2, pens 0-3: & ~p2
	and.\1	d2,d0
	move.\1	d0,4*SZ\1(a3)
	move.\1	1*SZ\1(a3),d0
	and.\1	d2,d0
	move.\1	d0,5*SZ\1(a3)
	move.\1	2*SZ\1(a3),d0
	and.\1	d2,d0
	move.\1	d0,6*SZ\1(a3)
	move.\1	3*SZ\1(a3),d0
	and.\1	d2,d0
	move.\1	d0,7*SZ\1(a3)
	not.\1	d2
	and.\1	d2,0*SZ\1(a3)
	and.\1	d2,1*SZ\1(a3)
	and.\1	d2,2*SZ\1(a3)
	and.\1	d2,3*SZ\1(a3)
	endm
SZb = 1
SZw = 2

; planes size,first: (a3) the pen masks, a2 the pens' colour indices -> d0-d3: the OR of the masks of the pens
; whose index has plane 0-3's bit (pens first..7).  d4-d6 / a4 changed.
planes	macro
	moveq	#\2,d6
	lea	\2*SZ\1(a3),a4
.p\@:	move.b	(a2,d6.w),d4
	move.\1	(a4)+,d5
	lsr.b	#1,d4
	bcc.s	.a\@
	or.\1	d5,d0
.a\@:	lsr.b	#1,d4
	bcc.s	.b\@
	or.\1	d5,d1
.b\@:	lsr.b	#1,d4
	bcc.s	.c\@
	or.\1	d5,d2
.c\@:	lsr.b	#1,d4
	bcc.s	.d\@
	or.\1	d5,d3
.d\@:	addq.w	#1,d6
	cmp.w	#8,d6
	blo.s	.p\@
	endm


; rev16 reg: the word bit-reversed (flip x); a4 = rev8, d3 changed
rev16	macro
	moveq	#0,d3
	move.b	\1,d3
	move.b	(a4,d3.w),d3
	lsl.w	#8,d3
	lsr.w	#8,\1
	move.b	(a4,\1.w),d3
	move.w	d3,\1
	endm

	section text,code

; ======================================================================================================================
; init_render: the buffers black, the caches empty, the display on the panel image and ring 0
; ======================================================================================================================
init_render:
	lea	buffers,a0
	move.l	#(NRING+1)*RINGSZ/16-1,d0
.clr:	clr.l	(a0)+
	clr.l	(a0)+
	clr.l	(a0)+
	clr.l	(a0)+
	subq.l	#1,d0
	bpl.s	.clr
	lea	hud_area,a0
	move.w	#HUD_AREA/4-1,d0
.clh:	clr.l	(a0)+
	dbf	d0,.clh
	lea	buffers,a0
	lea	ring_base,a1
	moveq	#NRING,d0		; (rings 0-2, then the clean screen)
.rb:	move.l	a0,(a1)+
	add.l	#RINGSZ,a0
	dbf	d0,.rb
	move.w	#-1,ring_wx
	move.w	#-1,ring_wx+2
	move.w	#-1,ring_wx+4
	move.w	#-1,cur_scene
	clr.w	shown_idx
	move.w	#-1,prev_idx
	clr.b	frame_ready
	st	tiles_full
	bsr	cache_flush
	lea	rowoff_n,a0		; (the rows' offsets in a cell: row r and, flipped vertically, 15 - r)
	lea	rowoff_f,a1
	moveq	#0,d0
	move.w	#15*LB,d1
	moveq	#15,d2
.ro:	move.w	d0,(a0)+
	move.w	d1,(a1)+
	add.w	#LB,d0
	sub.w	#LB,d1
	dbf	d2,.ro
	lea	rev8,a0			; (bytes bit-reversed: flip x)
	moveq	#0,d0
.rv:	moveq	#7,d2
	moveq	#0,d1
	move.b	d0,d3
.rv1:	lsr.b	#1,d3
	addx.b	d1,d1
	dbf	d2,.rv1
	move.b	d1,(a0)+
	addq.w	#1,d0
	cmp.w	#256,d0
	blo.s	.rv
	lea	kf_hudpal,a0		; the panel's colours
	movem.l	(a0),d0-d7
	movem.l	d0-d7,hud_pal
	move.w	#48,hud_top
	move.w	#PIC_LINES,hud_bot
	lea	hud_img,a0		; the display: the panel's image, then ring 0 at Wx 0
	move.l	a0,d0
	sub.l	#PIC_TOP*HUD_LB,d0
	bsr	set_base
	move.l	ring_base,d0
	add.l	#ROW_OFF*LB,d0
	move.l	d0,bd_vs_pf
	move.w	#LB,bd_vs_pfs
	move.w	#(LB-160)/2,bd_vs_pfl
	clr.w	bd_vs_pfh
	move.l	a0,bd_vs_bar
	move.w	#HUD_LB,bd_vs_bas
	clr.w	bd_vs_bal
	clr.w	bd_vs_bah
	st	bd_vs_on
	rts

set_base:				; d0 = the address of the display's first line
	ifnd SIM
	move.l	d0,-(sp)
	move.b	1(sp),$ffff8201.w
	move.b	2(sp),$ffff8203.w
	move.b	3(sp),$ffff820d.w
	move.b	1(sp),$ffff8205.w	; (the counter too: the STE's is writable)
	move.b	2(sp),$ffff8207.w
	move.b	3(sp),$ffff8209.w
	addq.l	#4,sp
	clr.b	$ffff8265.w
	clr.b	$ffff820f.w
	endc
	rts

cache_flush:				; the tile and sprite caches empty (a change of scene, a full cache)
	lea	tc_index,a0
	move.w	#65536*2/32-1,d0
	moveq	#0,d1
.t:	rept	8
	move.l	d1,(a0)+
	endr
	dbf	d0,.t
	lea	sc_index,a0
	move.w	#65536*2/32-1,d0
.s:	rept	8
	move.l	d1,(a0)+
	endr
	dbf	d0,.s
	clr.w	tc_used
	clr.w	sc_used
	rts

; ======================================================================================================================
; vbl_video: the picture published last goes on screen: its playfield address, fine scroll, line width and colours
; for borders.s' events (the base: the panel image's line 0 less PIC_TOP lines, set once)
; ======================================================================================================================
vbl_video:
	movem.l	d0-d3/a0-a1,-(sp)
	move.w	shown_idx,prev_idx
	moveq	#0,d1
	move.b	frame_ready,d1
	beq	.out
	clr.b	frame_ready
	subq.w	#1,d1
	move.w	d1,shown_idx
	add.w	d1,d1
	lea	pub_wx,a0
	move.w	(a0,d1.w),d0		; Wx
	add.w	d1,d1
	lea	ring_base,a0
	move.l	(a0,d1.w),d2
	add.l	#ROW_OFF*LB,d2		; (picture line 0 = arcade line 0: buffer line 16)
	moveq	#0,d1
	move.w	d0,d1
	lsr.w	#4,d1
	lsl.w	#3,d1
	add.l	d1,d2
	move.l	d2,bd_vs_pf
	and.w	#15,d0
	move.w	d0,bd_vs_pfh
	move.w	#(LB-160)/2,d1
	tst.w	d0
	beq.s	.w
	subq.w	#4,d1
.w:	move.w	d1,bd_vs_pfl
	move.w	pub_scene,d0
	lsl.w	#5,d0
	lea	kf_pals,a0
	add.w	d0,a0
	movem.l	(a0),d0-d3
	movem.l	d0-d3,shown_pal
	movem.l	16(a0),d0-d3
	movem.l	d0-d3,shown_pal+16
	addq.w	#1,pic_shown
.out:	movem.l	(sp)+,d0-d3/a0-a1
	rts

; ======================================================================================================================
; render_frame: draws the arcade frame's picture into a free ring and publishes it
; ======================================================================================================================
render_frame:
.snap:	move.w	shown_idx,d1		; a ring neither shown, nor scanned out once more, nor waiting
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
	cmp.w	#NRING,d0
	blo.s	.pick
	st	frame_dirty		; (none free: at the next idle time)
	rts
.got:	move.w	d0,draw_idx
	lsl.w	#2,d0
	lea	ring_base,a0
	move.l	(a0,d0.w),draw_base
	move.l	NRING*4(a0),clean_base
	bsr	kf_scene
	cmp.w	cur_scene,d0
	beq.s	.same
	move.w	d0,cur_scene		; a new scene: its colours, everything baked and drawn again
	lsl.w	#8,d0
	add.w	d0,d0
	lea	kf_maps,a0
	add.w	d0,a0
	move.l	a0,pen_map
	bsr	cache_flush
	st	tiles_full
	move.w	#-1,ring_wx
	move.w	#-1,ring_wx+2
	move.w	#-1,ring_wx+4
.same:	moveq	#0,d0			; Wx = (scroll + 96) mod 512
	move.b	Z_RAM+$B000,d0
	lsl.w	#8,d0
	move.b	Z_RAM+$A000,d0
	add.w	#96,d0
	and.w	#511,d0
	move.w	d0,cur_wx
	add.w	#32,d0
	move.w	d0,span_a		; the picture span [span_a, span_b) in buffer x
	add.w	#256,d0
	move.w	d0,span_b
	move.w	span_a,d0		; the clip boundaries: the word boundaries at or outside the edges
	and.w	#-16,d0
	move.w	d0,clip_l
	move.w	span_b,d0
	add.w	#15,d0
	and.w	#-16,d0
	move.w	d0,clip_r
	bsr	tiles_update
	bsr	ring_update
	bsr	draw_sprites
	bsr	draw_fronts
	move.w	draw_idx,d0		; publish: its Wx and scene, then the ring (one byte: the VBL takes it)
	add.w	d0,d0
	lea	pub_wx,a0
	move.w	cur_wx,(a0,d0.w)
	move.w	cur_scene,pub_scene
	addq.w	#1,pic_count
	move.w	draw_idx,d0
	addq.b	#1,d0
	move.b	d0,frame_ready
	rts

; kf_scene: d0 = the scene (assets.py scene_of): the floor (E080 & 7) in the states 2 3 4 6 7 8 12, else 5
kf_scene:
	moveq	#0,d0
	move.b	Z_RAM+$E000,d0
	cmp.w	#12,d0
	bhi.s	.att
	move.w	#%1000111011100,d1	; (the states 2-4, 6-8, 12)
	btst	d0,d1
	beq.s	.att
	moveq	#7,d0
	and.b	Z_RAM+$E080,d0
	cmp.w	#4,d0
	bhi.s	.att
	rts
.att:	moveq	#5,d0
	rts

; ======================================================================================================================
; Tiles: the marked rows of the tile RAM compared with the copy; a changed cell is drawn into the clean screen (rows
; 6-31, and its twin) and marked in the rings' bitmaps, or into the panel image (rows 0-5, the visible columns 16-47)
; ======================================================================================================================
tiles_update:
	lea	tile_rows,a5
	moveq	#0,d7			; the row
.row:	tst.b	tiles_full
	bne.s	.do
	tst.b	(a5,d7.w)
	beq	.next
.do:	clr.b	(a5,d7.w)
	move.w	d7,d0
	lsl.w	#6,d0
	lea	Z_RAM+$D000,a3
	add.w	d0,a3			; the row's codes (its attributes $800 further)
	lea	tile_copy,a4
	add.w	d0,a4
	moveq	#0,d6			; the column
.long:	tst.b	tiles_full		; (four columns at a time: equal longs skipped)
	bne.s	.col
	move.l	(a3),d0
	cmp.l	(a4),d0
	bne.s	.col
	move.l	$800(a3),d0
	cmp.l	$800(a4),d0
	bne.s	.col
	addq.w	#4,a3
	addq.w	#4,a4
	addq.w	#4,d6
	bra.s	.lnx
.col:	move.b	(a3),d0
	move.b	$800(a3),d1
	tst.b	tiles_full
	bne.s	.chg
	cmp.b	(a4),d0
	bne.s	.chg
	cmp.b	$800(a4),d1
	beq.s	.same
.chg:	move.b	d0,(a4)
	move.b	d1,$800(a4)
	movem.l	d6-d7/a3-a5,-(sp)
	bsr	cell_changed		; d0 code byte, d1 attribute, d6 column, d7 row
	movem.l	(sp)+,d6-d7/a3-a5
.same:	addq.w	#1,a3
	addq.w	#1,a4
	addq.w	#1,d6
	moveq	#3,d0
	and.w	d6,d0
	bne.s	.col
.lnx:	cmp.w	#64,d6
	blo.s	.long
.next:	addq.w	#1,d7
	cmp.w	#32,d7
	blo	.row
	sf	tiles_full
	rts

; d0.b code, d1.b attribute, d6 column, d7 row
cell_changed:
	moveq	#0,d2			; the cache key: code (10 bits) << 6 | colour (5) << 1 | panel
	move.b	d1,d2
	and.w	#$C0,d2
	lsl.w	#2,d2
	move.b	d0,d2
	lsl.w	#6,d2
	moveq	#$1F,d3
	and.b	d1,d3
	add.w	d3,d3
	or.w	d3,d2
	btst	#5,d1
	sne	d5			; flip x
	cmp.w	#6,d7
	bhs.s	.pf
	cmp.w	#16,d6			; the panel: visible columns 16-47 at screen x 8c - 96
	blo.s	.out
	cmp.w	#48,d6
	bhs.s	.out
	addq.w	#1,d2			; (the panel's colours)
	bsr	tile_baked		; a0 = the cell's 8 longs
	lea	hud_img,a1
	move.w	d7,d0
	mulu	#8*HUD_LB,d0
	add.w	d0,a1
	move.w	d6,d0
	sub.w	#12,d0			; (screen x / 8)
	move.w	d0,d1
	lsr.w	#1,d0
	lsl.w	#3,d0
	and.w	#1,d1
	add.w	d1,d0
	add.w	d0,a1
	bra	draw_cell_hud
.out:	rts
.pf:	move.w	d7,d4			; front cell? (colour >= 26)
	lsl.w	#6,d4
	add.w	d6,d4
	lea	front_map,a2
	and.b	#$1F,d1
	cmp.b	#26,d1
	shs	d3
	cmp.b	(a2,d4.w),d3
	beq.s	.fs
	move.b	d3,(a2,d4.w)		; (and the row's count of front cells)
	lea	row_front,a2
	tst.b	d3
	beq.s	.f0
	addq.b	#1,(a2,d7.w)
	bra.s	.fs
.f0:	subq.b	#1,(a2,d7.w)
.fs:
	bsr	tile_baked
	move.l	clean_base,a1		; the clean screen: buffer line 8 * row + 16, x = 8 * column (and + 512)
	move.w	d7,d0
	lsl.w	#3,d0
	add.w	#ROW_OFF,d0
	mulu	#LB,d0
	add.l	d0,a1
	move.w	d6,d0
	move.w	d0,d1
	lsr.w	#1,d0
	lsl.w	#3,d0
	and.w	#1,d1
	add.w	d1,d0
	add.w	d0,a1
	bsr	draw_cell_pf
	cmp.w	#42,d6
	bhs.s	.marks
	add.w	#512/16*8,a1		; the twin
	bsr	draw_cell_pf
.marks:	move.w	d7,d0			; the rings' bitmaps: (row - 6) * 8 bytes + column / 8, bit column & 7
	subq.w	#6,d0
	lsl.w	#3,d0
	move.w	d6,d1
	lsr.w	#3,d1
	add.w	d1,d0
	moveq	#7,d1
	and.w	d6,d1
	lea	ring_dirty,a2
	add.w	d0,a2
	bset	d1,(a2)
	bset	d1,26*8(a2)
	bset	d1,2*26*8(a2)
	rts

; a0 = the baked cell (8 longs: the four plane bytes of a row), a1 = its first byte in the buffer; d5.b: flip x
; (the bytes of the baked cell bit-reversed)
draw_cell_pf:
	tst.b	d5
	bne.s	.flip
	movem.l	(a0),d0-d4/a2-a4
	movep.l	d0,0(a1)
	movep.l	d1,LB(a1)
	movep.l	d2,2*LB(a1)
	movep.l	d3,3*LB(a1)
	movep.l	d4,4*LB(a1)
	move.l	a2,d0
	movep.l	d0,5*LB(a1)
	move.l	a3,d0
	movep.l	d0,6*LB(a1)
	move.l	a4,d0
	movep.l	d0,7*LB(a1)
	rts
.flip:	move.l	a1,-(sp)
	move.l	a0,a2
	lea	rev8,a3
	moveq	#7,d3
	moveq	#0,d1
.fr:	move.l	(a2)+,d0
	rept	4
	move.b	d0,d1
	move.b	(a3,d1.w),d0
	ror.l	#8,d0
	endr
	movep.l	d0,0(a1)
	add.w	#LB,a1
	dbf	d3,.fr
	move.l	(sp)+,a1
	rts
draw_cell_hud:
	tst.b	d5
	bne.s	.flip
	movem.l	(a0),d0-d4/a2-a4
	movep.l	d0,0(a1)
	movep.l	d1,HUD_LB(a1)
	movep.l	d2,2*HUD_LB(a1)
	movep.l	d3,3*HUD_LB(a1)
	movep.l	d4,4*HUD_LB(a1)
	move.l	a2,d0
	movep.l	d0,5*HUD_LB(a1)
	move.l	a3,d0
	movep.l	d0,6*HUD_LB(a1)
	move.l	a4,d0
	movep.l	d0,7*HUD_LB(a1)
	rts
.flip:	move.l	a0,a2
	lea	rev8,a3
	moveq	#7,d3
	moveq	#0,d1
.fr:	move.l	(a2)+,d0
	rept	4
	move.b	d0,d1
	move.b	(a3,d1.w),d0
	ror.l	#8,d0
	endr
	movep.l	d0,0(a1)
	add.w	#HUD_LB,a1
	dbf	d3,.fr
	rts

; tile_baked: d2 = the key -> a0 = the baked cell (baked now on a miss).  Keeps d5-d7 / a1.
tile_baked:
	lea	tc_index,a0
	moveq	#0,d0
	move.w	d2,d0
	add.l	d0,d0
	moveq	#0,d1
	move.w	(a0,d0.l),d1
	beq.s	.bake
	subq.w	#1,d1
	lsl.l	#5,d1
	lea	tc_data,a0
	add.l	d1,a0
	rts
.bake:	move.w	tc_used,d1
	cmp.w	#TC_SLOTS,d1
	blo.s	.room
	movem.l	d0/d2/d5-d7/a1,-(sp)	; (full: all again from now on; what is drawn stays)
	bsr	cache_flush
	movem.l	(sp)+,d0/d2/d5-d7/a1
	moveq	#0,d1
.room:	addq.w	#1,d1
	move.w	d1,tc_used
	lea	tc_index,a0
	move.w	d1,(a0,d0.l)
	subq.w	#1,d1
	ext.l	d1
	lsl.l	#5,d1
	lea	tc_data,a0
	add.l	d1,a0
	movem.l	d2-d7/a0-a6,-(sp)
	move.w	d2,d0			; the pen map: the panel's or the scene's tile pens; + colour * 8
	lea	kf_hudmap,a2
	btst	#0,d0
	bne.s	.pm
	move.l	pen_map,a2
.pm:	and.w	#$3E,d0
	lsl.w	#2,d0
	add.w	d0,a2			; a2 = the 8 pens' colour indices
	move.w	d2,d0
	lsr.w	#6,d0			; the code
	mulu	#24,d0
	lea	kf_tiles,a1
	add.l	d0,a1
	lea	pm_m,a3
	move.w	#7,bake_n
.row:	move.b	(a1)+,d0		; p0 p1 p2
	move.b	(a1)+,d1
	move.b	(a1)+,d2
	pen_masks b,0
	moveq	#0,d0
	moveq	#0,d1
	moveq	#0,d2
	moveq	#0,d3
	planes	b,0
	move.b	d0,(a0)+		; (movep.l: plane 0 the long's top byte)
	move.b	d1,(a0)+
	move.b	d2,(a0)+
	move.b	d3,(a0)+
	subq.w	#1,bake_n
	bpl	.row
	movem.l	(sp)+,d2-d7/a0-a6
	rts

; ======================================================================================================================
; blit_rect: the pixels [d0, d1) of buffer lines d2 .. d2 + d3 - 1 of the drawn ring: d4 = 0 black, 1 copied from the
; clean screen.  Whole words in one pass over the four planes; with edges inside words a pass a plane (the end masks
; from the tables).  Short HOG passes (blit_go).  d0-d7 / a0-a1 changed.
; ======================================================================================================================
blit_rect:
	cmp.w	d1,d0
	bge	.none
	tst.w	d3
	ble	.none
	move.w	d0,d5
	lsr.w	#4,d5			; w0
	move.w	d1,d6
	subq.w	#1,d6
	moveq	#15,d7
	and.w	d6,d7
	lsr.w	#4,d6			; w1
	add.w	d7,d7
	lea	rmask,a0
	move.w	(a0,d7.w),d7		; END3
	moveq	#15,d1
	and.w	d0,d1
	add.w	d1,d1
	lea	lmask,a0
	move.w	(a0,d1.w),d1		; END1
	sub.w	d5,d6			; nw - 1
	bne.s	.two
	and.w	d7,d1
	move.w	d1,d7
.two:	mulu	#LB,d2			; the offset of the first word
	lsl.w	#3,d5
	ext.l	d5
	add.l	d5,d2
	move.l	draw_base,a0
	add.l	d2,a0
	move.l	clean_base,a1
	add.l	d2,a1
	move.w	#$ffff,B_END2.w
	clr.b	B_SKEW.w
	move.b	#2,B_HOP.w
	moveq	#3,d0
	tst.w	d4
	bne.s	.op
	moveq	#0,d0
.op:	move.b	d0,B_OP.w
	move.w	d3,d5			; the lines
	cmp.w	#$ffff,d1
	bne.s	.planes
	cmp.w	#$ffff,d7
	bne.s	.planes
	; whole words: the four planes in one pass
	move.w	d6,d0
	addq.w	#1,d0
	lsl.w	#2,d0			; 4 * nw words
	move.w	d0,B_XC.w
	moveq	#2,d2
	move.w	d2,B_SXI.w
	move.w	d2,B_DXI.w
	add.w	d0,d0
	neg.w	d0
	add.w	#LB+2,d0		; LB - (4nw - 1) * 2
	move.w	d0,B_SYI.w
	move.w	d0,B_DYI.w
	move.w	d1,B_END1.w
	move.w	d7,B_END3.w
	move.l	a1,B_SRC.w
	move.l	a0,B_DST.w
	move.w	d5,B_YC.w
	bra	blit_go
.planes:
	move.w	d6,d0
	addq.w	#1,d0
	move.w	d0,B_XC.w		; nw
	moveq	#8,d2
	move.w	d2,B_SXI.w
	move.w	d2,B_DXI.w
	lsl.w	#3,d6
	neg.w	d6
	add.w	#LB,d6			; LB - (nw - 1) * 8
	move.w	d6,B_SYI.w
	move.w	d6,B_DYI.w
	move.w	d1,B_END1.w
	move.w	d7,B_END3.w
	moveq	#16,d2		; (masked: the destination is read too, whatever the op: BLIT_PIECE / 2 words a piece)
	divu	d0,d2
	tst.w	d2
	bne.s	.lp
	moveq	#1,d2
.lp:	move.w	d2,blit_lines
	moveq	#3,d6
.pl:	move.l	a1,B_SRC.w
	move.l	a0,B_DST.w
	move.w	d5,B_YC.w
	move.w	blit_lines,d1
	bsr	blit_go_lines
	addq.l	#2,a0
	addq.l	#2,a1
	dbf	d6,.pl
.none:	rts

; ======================================================================================================================
; ring_update: the drawn ring brought to the new window (span_a / span_b, cur_wx): whole again, or the strips of the
; window's move; its last picture's damage restored; the changed cells copied
; ======================================================================================================================
ring_update:
	move.w	draw_idx,d0
	add.w	d0,d0
	lea	ring_wx,a0
	move.w	(a0,d0.w),d1		; the ring's Wx
	move.w	cur_wx,(a0,d0.w)
	move.w	cur_wx,d2
	tst.w	d1
	bmi	.whole
	sub.w	d1,d2			; the move
	beq	.dmg
	cmp.w	#MOVE_MAX,d2
	bgt	.whole
	cmp.w	#-MOVE_MAX,d2
	blt	.whole
	move.w	d1,old_wx
	tst.w	d2
	bmi	.left
	; moved right (vn > vo): copy [max(vn + 32, vo + 288), vn + 288); black [max(vn, vo + 32), vn + 32) and
	; [max(vn + 288, vo + 320), vn + 320)
	move.w	cur_wx,d0
	add.w	#32,d0
	move.w	old_wx,d1
	add.w	#288,d1
	cmp.w	d1,d0
	bge.s	.r1
	move.w	d1,d0
.r1:	move.w	cur_wx,d1
	add.w	#288,d1
	moveq	#1,d4
	bsr	.strip
	move.w	cur_wx,d0
	move.w	old_wx,d1
	add.w	#32,d1
	cmp.w	d1,d0
	bge.s	.r2
	move.w	d1,d0
.r2:	move.w	cur_wx,d1
	add.w	#32,d1
	moveq	#0,d4
	bsr	.strip
	move.w	cur_wx,d0
	add.w	#288,d0
	move.w	old_wx,d1
	add.w	#320,d1
	cmp.w	d1,d0
	bge.s	.r3
	move.w	d1,d0
.r3:	move.w	cur_wx,d1
	add.w	#320,d1
	moveq	#0,d4
	bsr	.strip
	bra	.dmg
.left:	; moved left: copy [vn + 32, min(vn + 288, vo + 32)); black [vn, min(vn + 32, vo)) and
	; [vn + 288, min(vn + 320, vo + 288))
	move.w	cur_wx,d0
	add.w	#32,d0
	move.w	d0,d1
	add.w	#256,d1
	move.w	old_wx,d2
	add.w	#32,d2
	cmp.w	d2,d1
	ble.s	.l1
	move.w	d2,d1
.l1:	moveq	#1,d4
	bsr	.strip
	move.w	cur_wx,d0
	move.w	d0,d1
	add.w	#32,d1
	cmp.w	old_wx,d1
	ble.s	.l2
	move.w	old_wx,d1
.l2:	moveq	#0,d4
	bsr	.strip
	move.w	cur_wx,d0
	add.w	#288,d0
	move.w	d0,d1
	add.w	#32,d1
	move.w	old_wx,d2
	add.w	#288,d2
	cmp.w	d2,d1
	ble.s	.l3
	move.w	d2,d1
.l3:	moveq	#0,d4
	bsr	.strip
	bra	.dmg
.strip:	move.w	#PF_TOP,d2
	move.w	#PF_LINES,d3
	bra	blit_rect
.whole:	; the window whole: the span copied, the bands black; the old damage and the changed cells done with it
	move.w	span_a,d0
	move.w	span_b,d1
	moveq	#1,d4
	bsr	.strip
	move.w	cur_wx,d0
	move.w	span_a,d1
	moveq	#0,d4
	bsr	.strip
	move.w	span_b,d0
	move.w	cur_wx,d1
	add.w	#320,d1
	moveq	#0,d4
	bsr	.strip
	move.w	draw_idx,d0		; (the damage list and the bitmap: nothing left)
	add.w	d0,d0
	lea	ring_dmgn,a0
	clr.w	(a0,d0.w)
	move.w	draw_idx,d0
	mulu	#26*8,d0
	lea	ring_dirty,a0
	add.w	d0,a0
	moveq	#26*8/4-1,d0
.cd:	clr.l	(a0)+
	dbf	d0,.cd
	bra	.done
.dmg:	; the damage of the ring's last picture: copied inside the span, black outside
	move.w	draw_idx,d0
	add.w	d0,d0
	lea	ring_dmgn,a0
	move.w	(a0,d0.w),d7
	clr.w	(a0,d0.w)
	move.w	draw_idx,d0
	mulu	#DMG_MAX*8,d0
	lea	ring_dmg,a5
	add.l	d0,a5
	bra	.dn
.dl:	movem.w	(a5)+,d0-d3		; x0, x1, line, lines
	movem.w	d0-d3,dmg_cur
	move.w	span_a,d1		; [x0, min(x1, a)) black
	cmp.w	dmg_cur+2,d1
	ble.s	.d1
	move.w	dmg_cur+2,d1
.d1:	moveq	#0,d4
	move.w	dmg_cur+4,d2
	move.w	dmg_cur+6,d3
	move.w	d7,-(sp)
	bsr	blit_rect
	move.w	dmg_cur,d0		; [max(x0, a), min(x1, b)) copied
	cmp.w	span_a,d0
	bge.s	.d2
	move.w	span_a,d0
.d2:	move.w	dmg_cur+2,d1
	cmp.w	span_b,d1
	ble.s	.d3
	move.w	span_b,d1
.d3:	moveq	#1,d4
	move.w	dmg_cur+4,d2
	move.w	dmg_cur+6,d3
	bsr	blit_rect
	move.w	dmg_cur,d0		; [max(x0, b), x1) black
	cmp.w	span_b,d0
	bge.s	.d4
	move.w	span_b,d0
.d4:	move.w	dmg_cur+2,d1
	moveq	#0,d4
	move.w	dmg_cur+4,d2
	move.w	dmg_cur+6,d3
	bsr	blit_rect
	move.w	(sp)+,d7
.dn:	dbf	d7,.dl
	; the changed cells: each instance (x = 8c, and 512 + 8c below column 42) in the span
	move.w	draw_idx,d0
	mulu	#26*8,d0
	lea	ring_dirty,a5
	add.w	d0,a5
	moveq	#0,d6			; the byte: row * 8 + column / 8
.cb:	move.b	(a5),d7
	beq	.cbn
	clr.b	(a5)
	moveq	#0,d5			; the bit
.cbit:	btst	d5,d7
	beq.s	.cbx
	move.w	d6,d0			; the column: (byte & 7) * 8 + bit
	and.w	#7,d0
	lsl.w	#3,d0
	add.w	d5,d0
	movem.l	d5-d7/a5,-(sp)
	move.w	d0,cell_col
	move.w	d6,d0
	lsr.w	#3,d0
	lsl.w	#3,d0
	add.w	#PF_TOP,d0
	move.w	d0,cell_line
	move.w	cell_col,d0
	lsl.w	#3,d0
	bsr	cell_span
	move.w	cell_col,d0
	cmp.w	#42,d0
	bhs.s	.ctw
	lsl.w	#3,d0
	add.w	#512,d0
	bsr	cell_span
.ctw:	movem.l	(sp)+,d5-d7/a5
.cbx:	addq.w	#1,d5
	cmp.w	#8,d5
	blo.s	.cbit
.cbn:	addq.w	#1,a5
	addq.w	#1,d6
	cmp.w	#26*8,d6
	blo	.cb
.done:	rts

; cell_span: d0 = a cell's buffer x, cell_line its first line: its part in the span copied
cell_span:
	cmp.w	span_a,d0
	blt.s	.part
	move.w	d0,d1
	addq.w	#8,d1
	cmp.w	span_b,d1
	bgt.s	.part
	move.w	cell_line,d1		; wholly inside: the CPU copies it (movep.l: a byte of each plane, 8 lines)
	mulu	#LB,d1
	move.w	d0,d2
	lsr.w	#4,d2
	lsl.w	#3,d2
	btst	#3,d0
	beq.s	.e
	addq.w	#1,d2
.e:	ext.l	d2
	add.l	d2,d1
	move.l	clean_base,a0
	add.l	d1,a0
	move.l	draw_base,a1
	add.l	d1,a1
CS	set	0
	rept	8
	movep.l	CS(a0),d1
	movep.l	d1,CS(a1)
CS	set	CS+LB
	endr
	rts
.part:	move.w	d0,d1
	addq.w	#8,d1
	cmp.w	span_a,d0
	bge.s	.a
	move.w	span_a,d0
.a:	cmp.w	span_b,d1
	ble.s	.b
	move.w	span_b,d1
.b:	moveq	#1,d4
	move.w	cell_line,d2
	moveq	#8,d3
	bra	blit_rect

; ======================================================================================================================
; draw_sprites: the 32 entries of the sprite RAM ($C000), the first first (MAME's draw_sprites: the last on top); a
; sprite is 1, 2 or 4 cells high (the height PROM); its damage goes into the ring's list
; ======================================================================================================================
draw_sprites:
	move.w	draw_idx,d0
	mulu	#DMG_MAX*8,d0
	lea	ring_dmg,a0
	add.l	d0,a0
	move.l	a0,dmg_ptr
	clr.w	dmg_n
	move.w	#$ffff,B_END2.w		; (the Blitter's frame constants for the sprites)
	move.b	#2,B_HOP.w
	move.b	#3,B_OP.w
	moveq	#0,d7			; the entry's offset
.ent:	lea	Z_RAM+$C000,a0
	add.w	d7,a0
	moveq	#1,d2			; sx first: an entry wholly beside the picture is culled at once
	and.b	7(a0),d2
	lsl.w	#8,d2
	move.b	6(a0),d2
	cmp.w	#128-16,d2
	ble	.nod
	cmp.w	#384,d2
	bge	.nod
	moveq	#0,d0
	move.b	5(a0),d0
	and.w	#7,d0
	lsl.w	#8,d0
	move.b	4(a0),d0		; code
	moveq	#$1F,d1
	and.b	(a0),d1			; colour
	moveq	#1,d3
	and.b	3(a0),d3
	lsl.w	#8,d3
	move.b	2(a0),d3
	neg.w	d3
	add.w	#256+128-15,d3		; sy
	move.b	5(a0),d4		; flips: bit 6 x, bit 7 y
	move.w	d0,d5
	lsr.w	#5,d5
	and.w	#31,d5
	lea	kf_height,a1
	moveq	#0,d6
	move.b	(a1,d5.w),d6		; i
	cmp.b	#1,d6
	bne.s	.h2
	and.w	#~1,d0
	sub.w	#16,d3
	bra.s	.h
.h2:	cmp.b	#2,d6
	bne.s	.h
	moveq	#3,d6
	and.w	#~3,d0
	sub.w	#48,d3
.h:	tst.b	d4
	bpl.s	.fy
	add.w	d6,d0			; flip y: code + i, the cells downwards
.fy:	movem.w	d0-d4,spr_code		; code, colour, sx, sy, flips
	move.w	d6,spr_i
	move.w	#$7fff,spr_ly0
	clr.w	spr_ly1
	; the cells i .. 0 (MAME's order), each at sy + 16 i, code + i (- i when flipped)
.cell:	move.w	spr_i,d6
	move.w	d6,d0
	tst.b	spr_flip+1
	bpl.s	.c1
	neg.w	d0
.c1:	add.w	spr_code,d0
	and.w	#1023,d0
	move.w	d6,d3
	lsl.w	#4,d3
	add.w	spr_sy,d3		; the cell's arcade y
	cmp.w	#48-16,d3
	ble.s	.skip
	cmp.w	#256,d3
	bge.s	.skip
	move.w	spr_sx,d2
	cmp.w	#128-16,d2
	ble.s	.skip
	cmp.w	#384,d2
	bge.s	.skip
	movem.l	d6-d7,-(sp)
	bsr	draw_cell
	movem.l	(sp)+,d6-d7
.skip:	subq.w	#1,spr_i
	bpl.s	.cell
	move.w	spr_ly1,d1		; the damage: one rectangle a sprite
	beq.s	.nod
	cmp.w	#DMG_MAX,dmg_n
	bhs.s	.nod
	move.l	dmg_ptr,a1
	move.w	spr_dx0,(a1)+
	move.w	spr_dx1,(a1)+
	move.w	spr_ly0,(a1)+
	sub.w	spr_ly0,d1
	move.w	d1,(a1)+
	move.l	a1,dmg_ptr
	addq.w	#1,dmg_n
.nod:	addq.w	#8,d7
	cmp.w	#256,d7
	blo	.ent
	move.w	draw_idx,d0
	add.w	d0,d0
	lea	ring_dmgn,a0
	move.w	dmg_n,(a0,d0.w)
	rts

; draw_cell: d0 = the cell's code, d2 = its arcade x (in MAME's 384 wide bitmap), d3 = its arcade y; spr_colour,
; spr_flip.  Bakes it on a miss, culls / clips it at the clip boundaries, draws it, lists its damage.
draw_cell:
	add.w	cur_wx,d2
	sub.w	#96,d2			; buffer x
	add.w	#ROW_OFF,d3		; buffer line
	move.w	d2,cell_x
	move.w	d3,cell_line
	move.w	d0,d2			; the key: code << 6 | colour << 1 | flip x
	lsl.w	#6,d2
	move.w	spr_colour,d1
	add.w	d1,d1
	or.w	d1,d2
	btst	#6,spr_flip+1
	beq.s	.nf
	addq.w	#1,d2
.nf:	bsr	sprite_baked		; a0 = the slot
	; the destination words and the mode: 0 two words, 1 one word (no shift), 2 left clipped, 3 right clipped
	move.w	cell_x,d0
	moveq	#15,d5
	and.w	d0,d5			; the shift
	and.w	#-16,d0			; the first word's x
	move.w	clip_l,d1
	move.w	clip_r,d2
	sub.w	#16,d2			; (the last word inside starts here)
	tst.w	d5
	bne.s	.sh
	cmp.w	d1,d0			; one word
	blt	.out
	cmp.w	d2,d0
	bgt	.out
	moveq	#1,d6
	moveq	#1,d4			; (words)
	bra.s	.mode
.sh:	moveq	#0,d6
	moveq	#2,d4
	cmp.w	d1,d0
	bge.s	.l
	moveq	#2,d6			; the first word outside: left clipped
	moveq	#1,d4
	add.w	#16,d0
	cmp.w	d2,d0
	bgt	.out			; (the second too)
	bra.s	.mode
.l:	move.w	d0,d3
	add.w	#16,d3
	cmp.w	d2,d3
	ble.s	.mode
	moveq	#3,d6			; the second word outside: right clipped
	moveq	#1,d4
	cmp.w	d2,d0
	bgt	.out
.mode:	lsl.w	#2,d6
	move.w	d6,cell_mode
	; the sprite's damage (draw_sprites lists it): [x, x + 16 words), its cells' lines
	move.w	d0,spr_dx0
	lsl.w	#4,d4
	add.w	d0,d4
	move.w	d4,spr_dx1
	move.w	cell_line,d1
	cmp.w	spr_ly0,d1
	bge.s	.y0
	move.w	d1,spr_ly0
.y0:	add.w	#16,d1
	cmp.w	spr_ly1,d1
	ble.s	.full
	move.w	d1,spr_ly1
.full:	; the destination: the first drawn word's address
	move.w	cell_line,d1
	mulu	#LB,d1
	lsr.w	#4,d0
	lsl.w	#3,d0
	ext.l	d0
	add.l	d0,d1
	move.l	draw_base,a1
	add.l	d1,a1
	lea	rowoff_n,a2
	tst.b	spr_flip+1
	bpl.s	.fn
	lea	rowoff_f,a2
.fn:	move.w	(a0)+,d4		; the rows
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
	move.w	cell_mode,d0
	moveq	#0,d7			; (the mask written last: none yet; a listed row's mask is never 0)
	jmp	.modes(pc,d0.w)
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
	if REN_SHIFTS
	; the rows' END1:END3 for this shift: made once a slot and shift (the slot's bit), then read in blit order
	lea	SC_BASE-2(a0),a3	; (a0 = the slot + 2)
	move.w	(a3)+,d0		; the shifts made
	move.w	d5,d1
	add.w	d1,d1
	add.w	d1,d1
	lsl.w	#4,d1
	add.w	d1,a3			; + shift * 64
	btst	d5,d0
	bne.s	.mk
	bset	d5,d0
	move.w	d0,SC_BASE-2(a0)
	movem.l	a0/a3/d4,-(sp)
.mm:	addq.w	#2,a0
	move.w	(a0)+,d1
	move.w	d1,d2
	lsr.w	d5,d2
	swap	d2
	lsl.w	d6,d1
	move.w	d1,d2
	move.l	d2,(a3)+
	dbf	d4,.mm
	movem.l	(sp)+,a0/a3/d4
.mk:
.r2:	move.w	(a0)+,d0		; row * 2
	move.w	(a0)+,d1		; mask
	move.l	(a3)+,d2		; END1:END3
	cmp.w	d1,d7
	beq.s	.s2
	move.w	d1,d7
	move.w	d2,B_END3.w
	swap	d2
	move.w	d2,B_END1.w
	else
.r2:	move.w	(a0)+,d0		; row * 2
	move.w	(a0)+,d1		; mask
	cmp.w	d1,d7
	beq.s	.s2
	move.w	d1,d7
	move.w	d1,d2
	lsr.w	d5,d2
	move.w	d2,(a3)
	lsl.w	d6,d1
	move.w	d1,(a4)
	endc
.s2:	move.w	(a2,d0.w),d0
	lea	(a1,d0.w),a1
	move.l	a1,(a5)
	sub.w	d0,a1			; (a word subtracted from an address register: sign-extended, as the lea added it)
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
.s1:	move.w	(a2,d0.w),d0
	lea	(a1,d0.w),a1
	move.l	a1,(a5)
	sub.w	d0,a1
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
.sl:	move.w	(a2,d0.w),d0
	lea	(a1,d0.w),a1
	move.l	a1,(a5)
	sub.w	d0,a1
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
.sr:	move.w	(a2,d0.w),d0
	lea	(a1,d0.w),a1
	move.l	a1,(a5)
	sub.w	d0,a1
	move.w	d3,(a6)
	move.b	#$C0,B_CTRL.w
	dbf	d4,.rr
	rts

; sprite_baked: d2 = the key (code << 6 | colour << 1 | flip x) -> a0 = the slot (baked now on a miss).  Keeps d5-d7.
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

; bake_sprite: d2 = the key, a0 = the slot.  The 16 rows' masks and plane words into bake_rows (mask.w, 4 planes),
; then the slot: n, (row * 2, mask) in the blit order, the plane words in that order.
bake_sprite:
	move.l	a0,-(sp)
	move.w	d2,d0
	and.w	#$3E,d0
	lsl.w	#2,d0			; colour * 8
	move.l	pen_map,a2
	add.w	d0,a2
	lea	256(a2),a2		; the sprite pens of the colour
	move.w	d2,d0
	lsr.w	#6,d0
	mulu	#96,d0
	lea	kf_spr,a1
	add.l	d0,a1
	move.w	d2,bake_flip
	lea	bake_rows,a0
	lea	pm_m,a3
	move.w	#15,bake_n
.row:	move.w	(a1)+,d0
	move.w	(a1)+,d1
	move.w	(a1)+,d2
	btst	#0,bake_flip+1
	beq.s	.nf
	lea	rev8,a4			; flip x: the words bit-reversed
	rev16	d0
	rev16	d1
	rev16	d2
.nf:	move.w	d0,d3
	or.w	d1,d3
	or.w	d2,d3
	move.w	d3,(a0)+		; the opaque mask
	beq	.empty
	pen_masks w,0
	moveq	#0,d0
	moveq	#0,d1
	moveq	#0,d2
	moveq	#0,d3
	planes	w,1
	movem.w	d0-d3,(a0)
.empty:	addq.w	#8,a0
	subq.w	#1,bake_n
	bpl	.row
	; the order: each row not placed yet, then (REN_ORDER) the later rows with the same mask
	move.l	(sp)+,a0
	lea	bake_rows,a1
	moveq	#0,d0			; n
	moveq	#15,d1
.cnt:	tst.w	(a1)
	beq.s	.c0
	addq.w	#1,d0
.c0:	lea	10(a1),a1
	dbf	d1,.cnt
	if REN_SHIFTS
	clr.w	SC_BASE(a0)		; (no shift's masks made yet)
	endc
	move.w	d0,(a0)+
	lsl.w	#2,d0
	lea	(a0,d0.w),a2		; the plane words' place
	lea	bake_used,a3
	clr.l	(a3)
	clr.l	4(a3)
	clr.l	8(a3)
	clr.l	12(a3)
	lea	bake_rows,a1
	moveq	#0,d1			; the row
.ord:	tst.b	(a3,d1.w)
	bne.s	.onx
	move.w	d1,d2
	mulu	#10,d2
	move.w	(a1,d2.w),d3		; its mask
	beq.s	.onx
	bsr.s	.emit
	if REN_ORDER
	move.w	d1,d4			; the later rows with this mask
.same:	addq.w	#1,d4
	cmp.w	#16,d4
	bhs.s	.onx
	tst.b	(a3,d4.w)
	bne.s	.same
	move.w	d4,d2
	mulu	#10,d2
	cmp.w	(a1,d2.w),d3
	bne.s	.same
	exg	d1,d4
	bsr.s	.emit
	exg	d1,d4
	bra.s	.same
	endc
.onx:	addq.w	#1,d1
	cmp.w	#16,d1
	blo.s	.ord
	rts
.emit:	st	(a3,d1.w)		; row d1 (its bake_rows entry at d2): (row * 2, mask), its planes
	move.w	d1,d0
	add.w	d0,d0
	move.w	d0,(a0)+
	move.w	(a1,d2.w),(a0)+
	move.l	2(a1,d2.w),(a2)+
	move.l	6(a1,d2.w),(a2)+
	rts

; ======================================================================================================================
; draw_fronts: the front cells (colours 26-31: over the sprites) under this picture's sprites copied back from the
; clean screen (inside the span)
; ======================================================================================================================
draw_fronts:
	move.w	dmg_n,d7
	beq	.out
	move.w	draw_idx,d0
	mulu	#DMG_MAX*8,d0
	lea	ring_dmg,a5
	add.l	d0,a5
	subq.w	#1,d7
.rect:	movem.w	(a5)+,d0-d3		; x0, x1, line, lines
	movem.l	d7/a5,-(sp)
	move.w	d2,d4			; the tile rows: (line - 16) / 8 .. (line + lines - 17) / 8, within 6-31
	sub.w	#ROW_OFF,d4
	bpl.s	.t0
	moveq	#0,d4
.t0:	lsr.w	#3,d4
	add.w	d2,d3
	sub.w	#ROW_OFF+1,d3
	lsr.w	#3,d3
	cmp.w	#6,d4
	bhs.s	.t1
	moveq	#6,d4
.t1:	cmp.w	#31,d3
	bls.s	.t2
	moveq	#31,d3
.t2:	move.w	d3,fr_r1
	and.w	#-8,d0
	move.w	d0,fr_x0
	sub.w	d0,d1
	addq.w	#7,d1
	lsr.w	#3,d1
	subq.w	#1,d1
	move.w	d1,fr_n			; the columns - 1
.row:	cmp.w	fr_r1,d4
	bhi.s	.rn
	lea	row_front,a0
	tst.b	(a0,d4.w)
	beq.s	.cn
	move.w	d4,d0
	lsl.w	#6,d0
	lea	front_map,a4
	add.w	d0,a4			; the row's 64 flags
	move.w	fr_x0,d5
	move.w	d5,d1
	lsr.w	#3,d1
	and.w	#63,d1			; the column: (x mod 512) / 8
	move.w	fr_n,d6
.col:	tst.b	(a4,d1.w)
	beq.s	.cx
	movem.w	d1/d4-d6,-(sp)
	move.w	d4,d0
	lsl.w	#3,d0
	add.w	#ROW_OFF,d0
	move.w	d0,cell_line
	move.w	d5,d0
	move.l	a4,-(sp)
	bsr	cell_span
	move.l	(sp)+,a4
	movem.w	(sp)+,d1/d4-d6
.cx:	addq.w	#8,d5
	addq.w	#1,d1
	and.w	#63,d1
	dbf	d6,.col
.cn:	addq.w	#1,d4
	bra.s	.row
.rn:	movem.l	(sp)+,d7/a5
	dbf	d7,.rect
.out:	rts

; ======================================================================================================================
lmask:	dc.w	$ffff,$7fff,$3fff,$1fff,$0fff,$07ff,$03ff,$01ff,$00ff,$007f,$003f,$001f,$000f,$0007,$0003,$0001
rmask:	dc.w	$8000,$c000,$e000,$f000,$f800,$fc00,$fe00,$ff00,$ff80,$ffc0,$ffe0,$fff0,$fff8,$fffc,$fffe,$ffff

	include	"kf_assets.s"

	section bss,bss
	even
shown_pal:	ds.w	16
hud_pal:	ds.w	16
black_pal:	ds.w	16
hud_top:	ds.w	1
hud_bot:	ds.w	1
ring_base:	ds.l	NRING+1		; the rings, then the clean screen
draw_base:	ds.l	1
clean_base:	ds.l	1
pen_map:	ds.l	1
dmg_ptr:	ds.l	1
ring_wx:	ds.w	NRING		; the window each ring shows (-1: none: all again)
pub_wx:		ds.w	NRING
pub_scene:	ds.w	1
cur_scene:	ds.w	1
cur_wx:		ds.w	1
old_wx:		ds.w	1
span_a:		ds.w	1
span_b:		ds.w	1
clip_l:		ds.w	1
clip_r:		ds.w	1
shown_idx:	ds.w	1
prev_idx:	ds.w	1
draw_idx:	ds.w	1
pic_shown:	ds.w	1
tc_used:	ds.w	1
sc_used:	ds.w	1
bake_n:		ds.w	1
bake_flip:	ds.w	1
dmg_n:		ds.w	1
dmg_cur:	ds.w	4
cell_x:		ds.w	1
cell_line:	ds.w	1
cell_col:	ds.w	1
cell_mode:	ds.w	1
spr_code:	ds.w	1		; (movem.w: code, colour, sx, sy, flips)
spr_colour:	ds.w	1
spr_sx:		ds.w	1
spr_sy:		ds.w	1
spr_flip:	ds.w	1
spr_i:		ds.w	1
spr_dx0:	ds.w	1
spr_dx1:	ds.w	1
spr_ly0:	ds.w	1
spr_ly1:	ds.w	1
fr_x0:		ds.w	1
fr_x1:		ds.w	1
fr_r1:		ds.w	1
fr_n:		ds.w	1
blit_lines:	ds.w	1
ring_dmgn:	ds.w	NRING
rowoff_n:	ds.w	16
rowoff_f:	ds.w	16
pm_m:		ds.w	8
bake_rows:	ds.w	16*5
bake_used:	ds.b	16
frame_ready:	ds.b	1
tiles_full:	ds.b	1
rev8:		ds.b	256
front_map:	ds.b	32*64
row_front:	ds.b	32
	even
tile_copy:	ds.b	$1000
ring_dirty:	ds.b	NRING*26*8
	even
ring_dmg:	ds.b	NRING*DMG_MAX*8
tc_index:	ds.w	65536
sc_index:	ds.w	65536
tc_data:	ds.b	TC_SLOTS*32
sc_data:	ds.b	SC_SLOTS*SC_SIZE
hud_area:	ds.b	PIC_TOP*HUD_LB
hud_img:	ds.b	48*HUD_LB
	cnop	0,8
buffers:	ds.b	(NRING+1)*RINGSZ
	section text,code
