; Super Basketball's picture on the STE (included by sbasketb.s), from Super Basketball's renderer and Time Pilot's turning.
;
; The arcade's screen is turned as MAME's ROT90 turns it (tools/assets.py): the picture is 224 x 256, picture pixel
; (X, Y) the raw pixel (x = Y, y = 239 - X), centred in the 320-pixel screen: black side bands of 48 pixels (three
; 16-pixel groups: the picture's edges lie on group boundaries), borders open (engine/rt/borders.s, PIC_TOP 10,
; PIC_LINES 256).  One palette (sb_pal: 16 fitted colours, every pen mapped to the nearest).
;
; The tilemap is 32 x 32 cells of 8 x 8, raw cell (tx, ty) = tile_index ty * 32 + tx; raw columns tx 0-5 stand still
; (the scoreboard: picture lines 0-47), columns 6-31 are scrolled in raw y by $3F80 (the court, picture lines 48-255).
; Turned, a cell is the picture's 8 x 8 square at line 8 tx; the fixed ones at X = 232 - 8 ty (ty 2-29 are shown), the
; scrolled ones at the playfield's x P = 248 - 8 ty (ty 0-31 all lie in a 256-pixel ring): picture X shows P =
; (X + 16 - scroll) mod 256.
;
; The playfield (pf): 256 lines of PF_LB = 240 bytes (30 groups): the fixed cells in lines 0-47 at their X, the scrolled
; ones in lines 48-255 at P, and again at P + 256 where P < 224, so a 224-pixel window at any scroll lies inside without
; wrapping.  A cell the program writes (main_io_w lists it: cell_list, the video RAM's cell is address & $7FF, the colour
; RAM's cell the same + 0: both of a tile's bytes name the tile ty * 32 + tx = cell & $3FF) is drawn there when its code or
; colour changed: its 8 rows converted on first use per (code, colour, flips) into the tile cache (a long a row: the four
; planes' bytes, movep.l).
;
; Display buffers (three) of BL lines x 160 bytes: buffer line = PIC_TOP + picture line Y, screen x = 48 + X; 16 guard
; lines below the picture for whole sprites.  Every picture the buffer is composed again from the playfield: the 48 fixed
; lines unshifted, the 208 scrolled lines shifted by the scroll (one HOG pass per plane and line: 14 words, FXSR and the
; skew; the addresses run on to the next plane), so the last sprites' damage is gone, the guard lines cleared where the
; sprites reached them.  Then the sprites: the 64 entries of the shown bank ($3800 or $3900 by latch Q5) from the first to
; the last (the last on top: MAME's draw_sprites order).
;
; Sprites (x $3802 + 4 i = picture Y, y $3803 + 4 i, attr $3801 + 4 i, code $3800 + 4 i; none where x and y are both 0):
; the 16 x 16 square at picture X = 224 - y, Y = x; code the byte + bit 5 of the attribute * 8, colour attr & 15 + 16 *
; the palette bank ($3C20), raw flip x attr bit 6 (the turned rows reversed), raw flip y bit 7 (the columns).  Baked on
; first use per (code, colour, flips) into a slot of the sprite cache (flushed when the palette bank changes): the opaque
; rows (pen not 0) in row order, each with its row offset and mask, then the rows' four plane words in that order (the
; source address runs on).  The generated path (REN_GEN, engine/sprite_programs.py, docs/sprite-preparation.md): per
; shape (code, flips; the coverage's) and shift the code draws its rows grouped by mask (the slot's rows in that order),
; one- or two-word passes as stefastbobs2 chooses them, the end masks and control words from a stream, from the slot's
; aligned plane words.  Shapes without code and 64 KB crossings take the row path: a row is one HOG pass (Y count 4: the
; planes; X count 2 with NFSR when shifted, 1 when not), OP 3 with the opaque pixels as end masks.  Clipped at the
; picture's edges (AGENTS.md: group-aligned): across the left edge only the second word (FXSR, source X increment 0, the
; mask's second word as END1), across the right edge only the first; a sprite wholly outside is culled.  Top: none
; reaches above line 0.  Bottom: whole into the guard lines (cleared before the buffer's next picture).

BL = PIC_TOP+256+16			; buffer lines
LB = 160
BUFSZ = BL*LB
NBUF = 3
PIC0 = PIC_TOP*LB			; the picture's line 0 in a buffer
LEFT = 48				; the picture's left edge (screen x)
PF_LB = 240				; the playfield's bytes a line
TC_SLOTS = 2048				; tile cache slots (32 bytes)
SC_SLOTS = 1024				; sprite cache slots
CODES = 384				; sprite codes (tools/assets.py CODES: the shape number)
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
	move.l	#(NBUF*BUFSZ+PF_LB*256)/16-1,d0
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
	clr.l	guard_dirty
	lea	buf_scroll,a0		; (every row drawn at the first picture of each buffer)
	move.l	#-1,(a0)
	move.w	#-1,4(a0)
	clr.l	row_dirty
	clr.l	row_dirty+4
	clr.l	row_dirty+8
	clr.l	row_sdirty
	clr.l	row_sdirty+4
	clr.l	row_sdirty+8
	clr.b	last_bank
	move.l	#cell_list,cell_ptr
	lea	tile_copy,a0		; (no cell drawn yet: the first write of each changes it)
	move.w	#2048/4-1,d0
.tc:	move.l	#-1,(a0)+
	dbf	d0,.tc
	bsr	tcache_flush
	bsr	cache_flush
	lea	sb_pal,a0		; the palettes: the picture's, black around it
	lea	shown_pal,a1
	lea	black_pal,a2
	moveq	#15,d0
.pal:	move.w	(a0)+,(a1)+
	clr.w	(a2)+
	dbf	d0,.pal
	lea	line_off,a0		; picture line Y's offset (Y from 0: line_off is Y = 0; 16 lines below)
	move.l	#PIC0,d0
	move.w	#256+16-1,d1
.lo:	move.l	d0,(a0)+
	add.l	#LB,d0
	dbf	d1,.lo
	lea	row_tab,a1		; the tile rows a sprite at line Y covers (bits past 31 fall out)
	moveq	#0,d3
.rt:	move.w	d3,d0
	move.w	d0,d1
	lsr.w	#3,d0
	add.w	#15,d1
	lsr.w	#3,d1
	sub.w	d0,d1
	addq.w	#1,d1
	moveq	#1,d5
	lsl.l	d1,d5
	subq.l	#1,d5
	lsl.l	d0,d5
	move.l	d5,(a1)+
	addq.w	#1,d3
	cmp.w	#256,d3
	bne.s	.rt
	lea	key_attr,a1		; the cache key's part of the attributes: colour << 2 | flip x << 1 | flip y
	moveq	#0,d0			; (the sprite attribute: colour bits 0-3, raw flip x bit 6 = the rows, raw flip y bit 7 = the columns)
.ky:	moveq	#$0F,d1
	and.w	d0,d1
	lsl.w	#2,d1
	btst	#7,d0
	beq.s	.kb
	or.w	#2,d1			; (flip y: the turned columns)
.kb:	btst	#6,d0
	beq.s	.kc
	or.w	#1,d1			; (flip x: the turned rows)
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
	move.w	#32768/4-1,d0
.c:	clr.l	(a0)+
	clr.l	(a0)+
	clr.l	(a0)+
	clr.l	(a0)+
	dbf	d0,.c
	clr.w	sc_used
	rts

tcache_flush:
	lea	tc_index,a0
	move.w	#32768/8-1,d0
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
; render_frame: the changed cells into the playfield, then a free buffer composed into the arcade frame's picture and
; published
; ======================================================================================================================
render_frame:
	movem.l	d0-d7/a0-a6,-(sp)
	bsr	render_tiles
	moveq	#0,d0			; the sprite palette bank: the sprites' colours are baked with it
	move.b	sb_mem+$3C20,d0
	cmp.b	last_bank,d0
	beq.s	.bank
	move.b	d0,last_bank
	bsr	cache_flush
.bank:
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
	bsr	compose
	ifnd NOSPR
	bsr	draw_sprites
	endc
	move.w	draw_idx,d0
	addq.b	#1,d0
	move.b	d0,frame_ready
	addq.w	#1,pic_count
	movem.l	(sp)+,d0-d7/a0-a6
	rts

; ----------------------------------------------------------------------------------------------------------------------
; render_tiles: the cells the program wrote (cell_list: address & $7FF, the colour RAM's 0-$3FF and the video RAM's $400-
; $7FF) against tile_copy; each changed cell's tile (cell & $3FF = ty * 32 + tx) drawn into the playfield
; ----------------------------------------------------------------------------------------------------------------------
render_tiles:
	move.l	cell_ptr,a4
	lea	cell_list,a3
	cmp.l	a3,a4
	beq	.out
	move.l	a3,cell_ptr
.cell:	move.w	(a3)+,d7		; a written cell: its tile (ty * 32 + tx) changed?
	lea	cell_dirty,a2
	clr.b	(a2,d7.w)
	and.w	#$3FF,d7
	lea	sb_mem+$3000,a5
	lea	tile_copy,a6
	move.b	(a5,d7.w),d0		; colour
	lea	$400(a5),a5
	move.b	(a5,d7.w),d1		; code
	cmp.b	(a6,d7.w),d0
	bne.s	.chg
	lea	$400(a6),a5
	cmp.b	(a5,d7.w),d1
	beq.s	.same
.chg:	move.b	d0,(a6,d7.w)
	lea	$400(a6),a5
	move.b	d1,(a5,d7.w)
	movem.l	a3-a4,-(sp)
	bsr	tile_draw
	movem.l	(sp)+,a3-a4
.same:	cmp.l	a4,a3
	blo.s	.cell
.out:	rts

; tile_draw: d7.w = the tile (ty * 32 + tx), d0.b = its colour byte, d1.b = its code byte: drawn into the playfield (the
; scrolled columns twice where the first lies in the window's reach).  d0-d6 a0-a2 used.
tile_draw:
	moveq	#0,d2			; the key: code << 6 | raw flip y << 5 (the columns) | raw flip x << 4 (the rows) | colour
	move.b	d1,d2			; (code = the byte + (colour & $20) * 8; the turned flips: x reverses the rows, y the columns)
	btst	#5,d0
	beq.s	.c0
	or.w	#$100,d2
.c0:	lsl.w	#6,d2
	moveq	#$0F,d3
	and.b	d0,d3
	or.w	d3,d2
	btst	#6,d0
	beq.s	.f0
	or.w	#$20,d2			; (raw flip x: the turned tile's rows reversed = tile_convert's bit 5)
.f0:	btst	#7,d0
	beq.s	.f1
	or.w	#$10,d2			; (raw flip y: its columns reversed = bit 4)
.f1:	lea	tc_index,a0
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
	add.l	d4,a0			; the converted tile
	moveq	#31,d3
	and.w	d7,d3			; tx
	moveq	#1,d6			; its row (8 lines: tx) changed in every buffer
	lsl.l	d3,d6
	or.l	d6,row_dirty
	or.l	d6,row_dirty+4
	or.l	d6,row_dirty+8
	move.w	d7,d2
	lsr.w	#5,d2			; ty
	moveq	#31,d4
	sub.w	d2,d4			; the playfield's cell column of a scrolled column: 31 - ty
	cmp.w	#6,d3
	bhs.s	.scr
	cmp.w	#2,d2			; a fixed column: only ty 2-29 are shown, at cell column 29 - ty
	blo	.none
	cmp.w	#29,d2
	bhi	.none
	subq.w	#2,d4
.scr:	move.w	d3,d2
	lsl.w	#3,d2			; the first line: 8 tx
	mulu	#PF_LB,d2
	move.w	d4,d5
	lsr.w	#1,d5
	lsl.w	#3,d5
	add.w	d5,d2			; + (cell column / 2) * 8 + (cell column & 1)
	btst	#0,d4
	beq.s	.ev
	addq.w	#1,d2
.ev:	move.l	pf_base,a1
	add.l	d2,a1
	cmp.w	#6,d3
	blo.s	.one			; (a fixed column: once)
	cmp.w	#28,d4
	bhs.s	.one			; (the first 224 pixels again at 256: cell columns 0-27 + 32)
	movem.l	(a0),d0-d5/a2		; (rows 0-6; row 7 below)
	movep.l	d0,0(a1)
	movep.l	d0,128(a1)
	movep.l	d1,PF_LB(a1)
	movep.l	d1,PF_LB+128(a1)
	movep.l	d2,2*PF_LB(a1)
	movep.l	d2,2*PF_LB+128(a1)
	movep.l	d3,3*PF_LB(a1)
	movep.l	d3,3*PF_LB+128(a1)
	movep.l	d4,4*PF_LB(a1)
	movep.l	d4,4*PF_LB+128(a1)
	movep.l	d5,5*PF_LB(a1)
	movep.l	d5,5*PF_LB+128(a1)
	move.l	a2,d0
	movep.l	d0,6*PF_LB(a1)
	movep.l	d0,6*PF_LB+128(a1)
	move.l	28(a0),d0
	movep.l	d0,7*PF_LB(a1)
	movep.l	d0,7*PF_LB+128(a1)
.none:	rts
.one:	movem.l	(a0),d0-d5/a2
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
	rts

; tile_convert: d2.w = the key (code << 6 | flip y << 5 | flip x << 4 | colour), d3.l = key * 2 -> d4.w = its new slot
; + 1, the tile's 8 rows converted there: a long a row, the planes 0-3 from the high byte (movep.l order).  MAME's
; flips: x reverses the columns, y the rows.  The tiles are turned (assets.py); the key's bit 5 reverses their rows, bit 4 their columns.  d0-d6 a0-a2 used.
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
	lea	sb_tiles,a0
	add.w	d0,a0			; its 8 rows of 4 bytes (two pens a byte)
	moveq	#15,d0
	and.w	d2,d0
	lsl.w	#4,d0
	lea	sb_tpen,a2
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

; ----------------------------------------------------------------------------------------------------------------------
; guard_clear: the guard lines below the picture that the buffer's last sprites reached, cleared (the picture's columns
; only: the sprites never reach the side bands)
; ----------------------------------------------------------------------------------------------------------------------
guard_clear:
	move.w	draw_idx,d0
	lea	guard_dirty,a0
	tst.b	(a0,d0.w)
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
	move.l	draw_base,a0
	add.l	#PIC0+256*LB+16,a0
	moveq	#16-1,d0		; 16 lines of 128 bytes (the picture's 14 groups and a half band group each side)
.l:	movem.l	d2-d7/a2-a3,(a0)
	movem.l	d2-d7/a2-a3,32(a0)
	movem.l	d2-d7/a2-a3,64(a0)
	movem.l	d2-d7/a2-a3,96(a0)
	lea	LB(a0),a0
	dbf	d0,.l
.out:	rts

; ----------------------------------------------------------------------------------------------------------------------
; compose: the buffer's tile rows (8 lines each: 6 fixed ones, picture lines 0-47, and 26 scrolled ones) that the buffer
; does not hold as the picture has them, from the playfield: all rows when the scroll differs from the one the buffer
; was composed at (buf_scroll), else the rows the buffer's last sprites covered (row_sdirty) or a changed cell lies in
; (row_dirty).  A scrolled row is shifted by the scroll: the window's first pixel is P = (16 - scroll) & 255 (HOG passes
; of one plane and line, 14 words, FXSR and the skew 16 - shift for a shifted line: 15 source words).
; ----------------------------------------------------------------------------------------------------------------------
compose:
	move.w	draw_idx,d2
	add.w	d2,d2
	moveq	#0,d0
	move.b	sb_mem+$3F80,d0
	neg.w	d0
	add.w	#16,d0
	and.w	#255,d0			; P
	move.w	d0,cur_p
	move.w	d2,d1
	add.w	d1,d1			; the buffer's long
	lea	row_sdirty,a1
	move.l	(a1,d1.w),d6		; the rows its last sprites covered
	clr.l	(a1,d1.w)
	lea	row_dirty,a1
	or.l	(a1,d1.w),d6		; the rows with a changed cell
	clr.l	(a1,d1.w)
	lea	buf_scroll,a0
	cmp.w	(a0,d2.w),d0
	beq.s	.same
	move.w	d0,(a0,d2.w)
	moveq	#-1,d6			; (another scroll: every row)
.same:	tst.l	d6
	beq	.done
	move.w	#$0203,B_HOP.w		; source, OP 3
	moveq	#-1,d0
	move.w	d0,B_END1.w
	move.w	d0,B_END2.w
	move.w	d0,B_END3.w
	move.w	#8,B_SXI.w
	move.w	#8,B_DXI.w
	move.w	#14,B_XC.w
	move.w	#LB-13*8,B_DYI.w
	move.w	#PF_LB-13*8,B_SYI.w
	clr.b	B_SKEW.w
	lea	B_SRC.w,a3
	lea	B_DST.w,a4
	lea	B_YC.w,a5
	lea	B_CTRL.w,a6
	moveq	#8,d3			; (the row's 8 lines a pass: 14 + 14 words a line, 232 bus cycles)
	moveq	#-$40,d4		; ($C0: start, HOG)
	move.l	pf_base,a2
	move.l	draw_base,a0
	add.l	#PIC0+LEFT/2,a0
	moveq	#0,d7			; the row
.fix:	btst	d7,d6
	beq.s	.fnx
	move.l	a2,(a3)			; four HOG passes, one plane each (8 lines)
	move.l	a0,(a4)
	move.w	d3,(a5)
	move.b	d4,(a6)
	lea	2(a2),a1
	move.l	a1,(a3)
	lea	2(a0),a1
	move.l	a1,(a4)
	move.w	d3,(a5)
	move.b	d4,(a6)
	lea	4(a2),a1
	move.l	a1,(a3)
	lea	4(a0),a1
	move.l	a1,(a4)
	move.w	d3,(a5)
	move.b	d4,(a6)
	lea	6(a2),a1
	move.l	a1,(a3)
	lea	6(a0),a1
	move.l	a1,(a4)
	move.w	d3,(a5)
	move.b	d4,(a6)
.fnx:	lea	8*PF_LB(a2),a2
	lea	8*LB(a0),a0
	addq.w	#1,d7
	cmp.w	#6,d7
	bne.s	.fix
	move.w	cur_p,d0		; the scrolled rows
	moveq	#15,d1
	and.w	d0,d1			; the shift
	beq.s	.k0
	moveq	#16,d5
	sub.w	d1,d5			; skew 16 - shift, FXSR: 15 source words a line
	or.b	#FXSR,d5
	move.b	d5,B_SKEW.w
	move.w	#PF_LB-14*8,B_SYI.w
.k0:	lsr.w	#4,d0
	lsl.w	#3,d0			; the window's first group
.scr:	btst	d7,d6
	beq.s	.snx
	lea	(a2,d0.w),a1
	move.l	a1,(a3)
	move.l	a0,(a4)
	move.w	d3,(a5)
	move.b	d4,(a6)
	lea	2(a1),a1
	move.l	a1,(a3)
	lea	2(a0),a1
	move.l	a1,(a4)
	move.w	d3,(a5)
	move.b	d4,(a6)
	lea	(a2,d0.w),a1
	lea	4(a1),a1
	move.l	a1,(a3)
	lea	4(a0),a1
	move.l	a1,(a4)
	move.w	d3,(a5)
	move.b	d4,(a6)
	lea	(a2,d0.w),a1
	lea	6(a1),a1
	move.l	a1,(a3)
	lea	6(a0),a1
	move.l	a1,(a4)
	move.w	d3,(a5)
	move.b	d4,(a6)
.snx:	lea	8*PF_LB(a2),a2
	lea	8*LB(a0),a0
	addq.w	#1,d7
	cmp.w	#32,d7
	bne.s	.scr
.done:	rts

; ======================================================================================================================
; draw_sprites: the 64 entries of the shown bank, the first first (the last on top); the guard lines they reach noted
; for the buffer's next picture
; ======================================================================================================================
draw_sprites:
	clr.b	spr_guard
	clr.l	spr_rows
	move.w	#-1,last_mode
	move.w	#$0203,B_HOP.w
	lea	sb_mem+$3800,a0
	tst.b	sb_latch+5		; the sprite RAM bank (OBJ CHE): $3800 or $3900
	beq.s	.b
	lea	$100(a0),a0
.b:	moveq	#63,d0
.e:	move.w	2(a0),d1		; x and y
	beq	.n			; (none where both are 0)
	moveq	#0,d3
	move.b	d1,d3			; y
	lsr.w	#8,d1
	move.w	d1,d5			; x: picture Y
	move.w	#224,d4
	sub.w	d3,d4			; picture X
	move.w	d4,d1
	add.w	#15,d1
	cmp.w	#238,d1			; (-15 .. 223)
	bhi.s	.n
	moveq	#0,d6
	moveq	#0,d7
	move.b	(a0),d6			; code
	move.b	1(a0),d7		; attributes
	btst	#5,d7
	beq.s	.c0
	or.w	#$100,d6
.c0:	lsl.w	#6,d6
	add.w	d7,d7
	lea	key_attr,a1
	or.w	(a1,d7.w),d6		; the key: code << 6 | colour << 2 | flips
	move.w	d6,d2
	move.w	d4,d3			; picture X
	move.w	d5,d4			; picture Y
	movem.l	d0/a0,-(sp)
	bsr	draw_cell
	movem.l	(sp)+,d0/a0
.n:	addq.l	#4,a0
	dbf	d0,.e
	move.w	draw_idx,d0		; the buffer's next picture draws the rows these covered again, and clears the guard lines
	move.w	d0,d1			; they reached
	add.w	d1,d1
	add.w	d1,d1
	lea	row_sdirty,a0
	move.l	spr_rows,(a0,d1.w)
	lea	guard_dirty,a0
	move.b	spr_guard,d2
	or.b	d2,(a0,d0.w)
	rts

; draw_cell: d2 = the key, d3 = picture X (-15 .. 223), d4 = picture Y (0 .. 255).  Baked on a miss, clipped at the
; edges, drawn; the bottom guard noted.
draw_cell:
	move.w	d2,cell_key
	move.w	d3,cell_x
	move.w	d4,cell_y
	cmp.w	#256-15,d4
	blt.s	.nog
	st	spr_guard
.nog:	move.w	d4,d0			; the tile rows it covers: Y / 8 .. (Y + 15) / 8 (bits past 31 fall out): row_tab
	add.w	d0,d0
	add.w	d0,d0
	lea	row_tab,a1
	move.l	(a1,d0.w),d5
	or.l	d5,spr_rows
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
	cmp.w	#LEFT+224-16,d3
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
.l:	cmp.w	#LEFT+224-16,d0
	blt.s	.mode
	moveq	#12,d6			; the second word in the band: right clipped
.mode:	move.w	d6,cell_mode
	move.w	cell_y,d1		; the first drawn word's offset
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

; bake_sprite: d2 = the key (code << 6 | colour << 2 | flip x << 1 | flip y), a0 = the slot.
; n, (row * 160, mask << 16) for the opaque rows in row order, then their 4 plane words.  sb_spr: per code 16 rows of
; 8 bytes (two pens a byte, the leftmost in the high nibble); MAME's flip x reverses the columns, flip y the rows.
bake_sprite:
	moveq	#0,d0
	move.w	d2,d0
	lsr.w	#6,d0			; the code
	lsl.l	#7,d0			; 128 bytes a code
	lea	sb_spr,a1
	add.l	d0,a1
	moveq	#0,d1
	move.b	last_bank,d1		; the colour set: (colour + 16 * the palette bank) & 255, 16 pens each
	lsl.w	#4,d1
	moveq	#$3C,d0
	and.w	d2,d0			; the colour * 4
	lsr.w	#2,d0
	add.w	d0,d1
	and.w	#$FF,d1
	lsl.w	#4,d1
	lea	sb_spen,a2
	add.w	d1,a2			; its 16 pens' colour indices ($FF: transparent, pen 0)
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
	; the slot: the shape's record (sb_shapes), the aligned plane words' address, the opaque rows grouped by mask
	; (the generated code's order), their plane words, the same aligned
	moveq	#0,d0			; shape = code << 2 | flips (one transparency class: pen 0)
	move.w	d2,d0
	lsr.w	#6,d0			; the code
	lsl.l	#2,d0
	moveq	#3,d1
	and.w	d2,d1
	or.w	d1,d0
	move.l	d0,d1
	lsl.l	#2,d1
	lea	sb_shapes,a4
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
	include	"sb_assets.s"
sb_spr:		incbin	"sb_spr.bin"
sb_tiles:	incbin	"sb_tiles.bin"
sb_sstream:	incbin	"sb_sstream.bin"
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
guard_dirty:	ds.b	4			; per buffer: the bottom guard lines hold sprites
row_dirty:	ds.l	NBUF			; per buffer: the tile rows with a changed cell (bit 31 the row 31)
row_sdirty:	ds.l	NBUF			; per buffer: the tile rows its last sprites covered
buf_scroll:	ds.w	NBUF			; per buffer: the P its scrolled rows were composed at (-1: never)
cur_p:		ds.w	1
spr_rows:	ds.l	1			; draw_sprites: the rows the sprites drawn now cover
spr_guard:	ds.b	1
last_bank:	ds.b	1			; the sprite palette bank the sprite cache was baked with
frame_ready:	ds.b	1
	even
cell_ptr:	ds.l	1			; the end of cell_list (render_tiles empties it)
cell_list:	ds.w	2048			; the cells written since the renderer looked (main_io_w), once each
cell_dirty:	ds.b	2048			; their flags
tile_copy:	ds.b	2048			; the colours ($0-$3FF) and codes ($400-$7FF) the playfield has
line_off:	ds.l	256+16			; the offset of picture line Y in a buffer
row_tab:	ds.l	256			; per picture line Y: the tile rows a sprite there covers
key_attr:	ds.w	256			; the cache key's part of the attributes (colour << 2, flips)
bake_rows:	ds.w	16*5
bake_ord:	ds.b	18			; bake_sprite: the opaque rows' order ($FF after the last; even: bake_seen is cleared by longs)
bake_seen:	ds.b	16
	even
tc_index:	ds.w	32768			; per tile key: its slot + 1 (0: not converted)
tc_data:	ds.b	TC_SLOTS*32
sc_index:	ds.l	32768			; per sprite key: its slot (0: not baked)
sc_data:	ds.b	SC_SLOTS*SC_SIZE
	cnop	0,256
buffers:	ds.b	NBUF*BUFSZ+PF_LB*256
	section text,code
