; Hyper Sports' picture on the STE (included by hyperspt.s).
;
; The arcade's picture is 256 x 224 (raw lines 16-239), unturned, centred in the 320-pixel screen: black side bands of
; 32 pixels (two 16-pixel groups: the picture's edges lie on group boundaries), borders open (engine/rt/borders.s,
; PIC_TOP 20, PIC_LINES 224).  One palette (hs_pal: 16 fitted colours, every pen mapped to the nearest).
;
; The playfield (pf): the 64 x 32 tilemap (512 x 256 pixels; 1024 tiles: code bits 8, 9 = colour bits 7, 6) in STE planes, 768 pixels wide (48 groups, 384 bytes a
; line): the first 256 pixels again at 512-767, so a 256-pixel window at any scroll lies inside without wrapping.  A
; cell the program writes (main_io_w lists it: cell_list) is drawn there when its code or colour changed: its 8 rows
; converted on first use per (code, colour, flips) into the tile cache (a long a row: the four planes' bytes, movep.l).
;
; Display buffers (three) of BL lines x 160 bytes: buffer line = PIC_TOP + picture line Y, screen x = 32 + X; 16 guard
; lines below the picture (and PIC_TOP above) for whole sprites.  A buffer is brought to the new picture row by row:
; tile row r (raw row 2 + r, picture lines 8r-8r+7) is copied from the playfield at its scroll ($10C0 + 2 row, bit 8
; at $10C1 + 2 row: screen x shows playfield x + scroll) when the scroll differs from what the buffer holds there, or a cell
; of the row changed, or the buffer's last sprites covered it; one HOG pass per plane and line (16 words, the source
; shifted with FXSR: ~132 bus cycles; the addresses run on to the next plane).  Then the sprites: the 32 entries from
; the last to the first (the first on top), each at x and at x - 256 (MAME's wrap); the rows they cover and the guard
; lines they reach are noted for the buffer's next picture.
;
; Sprites (48 entries at $1000 + 4 n: attributes, y, code, x; attributes bit 5 adds 256 to the code): the 16 x 16
; square at picture X = x, Y = 225 - y; colour attr & 15, MAME's flip x when bit 6 is clear, flip y bit 7.  Baked on first use
; per (code, colour, flips) into a slot of the sprite cache: the opaque rows (the colour's lookup entry not 0) in row
; order, each with its row offset and mask, then the rows' four plane words in that order (the source address runs
; on).  A row is one HOG pass (Y count 4: the planes; X count 2 with NFSR when shifted, 1 when not), OP 3 with the
; opaque pixels as end masks.  Clipped at the picture's edges (AGENTS.md: group-aligned): across the left edge only
; the second word (FXSR, source X increment 0, the mask's second word as END1), across the right edge only the first;
; a sprite wholly outside is culled.  Top and bottom: whole into the guard lines (cleared before the buffer's next
; picture).

BL = PIC_TOP+224+16			; buffer lines
LB = 160
BUFSZ = BL*LB
NBUF = 3
PIC0 = PIC_TOP*LB			; the picture's line 0 in a buffer
LEFT = 32				; the picture's left edge (screen x)
PF_LB = 384				; the playfield's bytes a line
TC_SLOTS = 2048				; tile cache slots (32 bytes)
SC_SLOTS = 1024				; sprite cache slots
SC_SIZE = 2+16*6+16*8			; n, (row * 160, mask << 16) a row, the 4 plane words a row

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
	lea	row_scroll,a0		; (every row drawn at the first picture of each buffer)
	move.w	#NBUF*28-1,d0
.rs:	move.w	#-1,(a0)+
	dbf	d0,.rs
	clr.l	row_dirty
	clr.l	row_dirty+4
	clr.l	row_dirty+8
	clr.l	guard_dirty
	move.l	#cell_list,cell_ptr
	lea	tile_copy,a0		; (no cell drawn yet: the first write of each changes it)
	move.w	#4096/4-1,d0
.tc:	move.l	#-1,(a0)+
	dbf	d0,.tc
	bsr	tcache_flush
	bsr	cache_flush
	lea	hs_pal,a0		; the palettes: the picture's, black around it
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
; render_tiles: the cells the program wrote (cell_list) against tile_copy; each changed visible cell (raw rows 2-29)
; drawn into the playfield and its row marked for every buffer
; ----------------------------------------------------------------------------------------------------------------------
render_tiles:
	move.l	cell_ptr,a4
	lea	cell_list,a3
	cmp.l	a3,a4
	beq	.out
	move.l	a3,cell_ptr
	moveq	#0,d6			; the rows changed
.cell:	move.w	(a3)+,d7		; a written cell (ty * 64 + tx): changed?
	lea	cell_dirty,a2
	clr.b	(a2,d7.w)
	lea	hs_mem+$2000,a5
	lea	tile_copy,a6
	move.b	(a5,d7.w),d1		; code
	lea	$800(a5),a5
	move.b	(a5,d7.w),d0		; colour
	cmp.b	(a6,d7.w),d1
	bne.s	.chg
	lea	$800(a6),a5
	cmp.b	(a5,d7.w),d0
	beq.s	.same
.chg:	move.b	d1,(a6,d7.w)
	lea	$800(a6),a5
	move.b	d0,(a5,d7.w)
	move.w	d7,d2
	lsr.w	#6,d2			; ty
	subq.w	#2,d2
	bmi.s	.same
	cmp.w	#28,d2
	bhs.s	.same
	bset	d2,d6
	movem.l	d6/a3-a4,-(sp)
	bsr	tile_draw
	movem.l	(sp)+,d6/a3-a4
.same:	cmp.l	a4,a3
	blo.s	.cell
	or.l	d6,row_dirty
	or.l	d6,row_dirty+4
	or.l	d6,row_dirty+8
.out:	rts

; tile_draw: d7.w = the cell (ty * 64 + tx), d0.b = its colour byte, d1.b = its code byte: drawn into the playfield
; (twice when tx < 32).  d0-d5 a0-a2 used.
tile_draw:
	moveq	#0,d2			; the key: code << 6 | colour bits 0-5 (code = the byte + 256 colour bit 7 + 512 bit 6)
	tst.b	d0
	bpl.s	.c7
	move.w	#$100,d2
.c7:	btst	#6,d0
	beq.s	.c6
	or.w	#$200,d2
.c6:	move.b	d1,d2
	lsl.w	#6,d2
	moveq	#$3F,d3
	and.b	d0,d3
	or.w	d3,d2
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
	move.w	d7,d2			; the cell's first byte in the playfield: ty * 8 * 384 + (tx / 2) * 8 + (tx & 1)
	lsr.w	#6,d2
	mulu	#8*PF_LB,d2
	moveq	#63,d3
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
	cmp.w	#32,d3
	bhs.s	.one
	movem.l	(a0),d0-d5/a2		; (rows 0-6; row 7 below)
	movep.l	d0,0(a1)
	movep.l	d0,256(a1)
	movep.l	d1,PF_LB(a1)
	movep.l	d1,PF_LB+256(a1)
	movep.l	d2,2*PF_LB(a1)
	movep.l	d2,2*PF_LB+256(a1)
	movep.l	d3,3*PF_LB(a1)
	movep.l	d3,3*PF_LB+256(a1)
	movep.l	d4,4*PF_LB(a1)
	movep.l	d4,4*PF_LB+256(a1)
	movep.l	d5,5*PF_LB(a1)
	movep.l	d5,5*PF_LB+256(a1)
	move.l	a2,d0
	movep.l	d0,6*PF_LB(a1)
	movep.l	d0,6*PF_LB+256(a1)
	move.l	28(a0),d0
	movep.l	d0,7*PF_LB(a1)
	movep.l	d0,7*PF_LB+256(a1)
	rts
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
; flips: x reverses the columns, y the rows.  d0-d6 a0-a2 used.
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
	lsr.w	#6,d0			; the code (0-1023)
	lsl.w	#5,d0
	lea	hs_tiles,a0
	add.w	d0,a0			; its 8 rows of 4 bytes (two pens a byte)
	moveq	#15,d0
	and.w	d2,d0
	lsl.w	#4,d0
	lea	hs_tpen,a2
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
	move.l	(a0,d1.w),d6		; the rows to draw whatever their scroll
	clr.l	(a0,d1.w)
	mulu	#56,d0
	lea	row_scroll,a2
	add.w	d0,a2			; the buffer's rows' scrolls
	move.w	#$0203,B_HOP.w		; source, OP 3
	moveq	#-1,d0
	move.w	d0,B_END1.w
	move.w	d0,B_END2.w
	move.w	d0,B_END3.w
	move.w	#8,B_SXI.w
	move.w	#8,B_DXI.w
	move.w	#16,B_XC.w
	move.w	#2-15*8,B_DYI.w
	lea	B_SRC.w,a3
	lea	B_DST.w,a4
	lea	B_YC.w,a5
	lea	B_CTRL.w,a6
	moveq	#1,d3
	moveq	#-$40,d4		; ($C0: start, HOG)
	move.l	draw_base,a1
	lea	PIC0+16(a1),a1		; the picture's first line, its first group
	move.l	pf_base,a0
	lea	2*8*PF_LB(a0),a0	; raw row 2
	moveq	#0,d7			; the row
.row:	lea	hs_mem+$10C4,a1		; its scroll: $10C0 + 2 (2 + r), bit 8 from the byte after
	move.w	d7,d1
	add.w	d1,d1
	moveq	#0,d0
	move.b	(a1,d1.w),d0
	btst	#0,1(a1,d1.w)
	beq.s	.s
	or.w	#$100,d0
.s:	cmp.w	(a2),d0
	bne.s	.draw
	btst	d7,d6
	beq	.next
.draw:	move.w	d0,(a2)
	moveq	#15,d1
	and.w	d0,d1			; the shift
	beq.s	.k0
	moveq	#16,d2
	sub.w	d1,d2			; skew 16 - shift, FXSR: 17 source words a line
	or.b	#FXSR,d2
	move.b	d2,B_SKEW.w
	move.w	#2-16*8,B_SYI.w
	bra.s	.k
.k0:	clr.b	B_SKEW.w
	move.w	#2-15*8,B_SYI.w
.k:	lsr.w	#4,d0
	lsl.w	#3,d0
	lea	(a0,d0.w),a1		; (the source's first group)
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
	lea	8*PF_LB(a0),a0
	addq.w	#1,d7
	cmp.w	#28,d7
	bne	.row
	rts

; ======================================================================================================================
; draw_sprites: the 48 entries, the last first (the first on top), each at x and x - 256; the rows they cover and the
; guard lines they reach noted for the buffer's next picture
; ======================================================================================================================
draw_sprites:
	clr.l	spr_rows
	clr.b	spr_guard
	move.w	#-1,last_mode
	move.w	#$0203,B_HOP.w
	move.w	#$BC,d0
.e:	move.w	d0,-(sp)
	lea	hs_mem+$1000,a0
	add.w	d0,a0
	moveq	#0,d3
	moveq	#0,d5
	moveq	#0,d6
	moveq	#0,d7
	move.b	(a0)+,d7		; attributes
	move.b	(a0)+,d3		; y
	move.b	(a0)+,d6		; code
	move.b	(a0),d5			; x: picture X
	move.w	#225,d4
	sub.w	d3,d4			; picture Y
	cmp.w	#-15,d4
	blt.s	.n
	cmp.w	#223,d4
	bgt.s	.n
	btst	#5,d7
	beq.s	.lo
	add.w	#256,d6			; (attributes bit 5: the code's bit 8)
.lo:	lsl.w	#6,d6
	add.w	d7,d7
	lea	key_attr,a0
	or.w	(a0,d7.w),d6		; the key: code << 6 | colour << 2 | flips
	move.w	d6,d2
	move.w	d5,d3
	movem.w	d2-d4,-(sp)
	bsr	draw_cell
	movem.w	(sp)+,d2-d4
	sub.w	#256,d3			; (MAME draws each sprite at x - 256 too)
	bsr	draw_cell
.n:	move.w	(sp)+,d0
	subq.w	#4,d0
	bpl.s	.e
	move.w	draw_idx,d0		; the buffer's next picture redraws what these covered
	move.w	d0,d1
	add.w	d1,d1
	add.w	d1,d1
	lea	row_dirty,a0
	move.l	spr_rows,d2
	or.l	d2,(a0,d1.w)
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
	move.l	spr_rows,d5
.rb:	bset	d0,d5
	addq.w	#1,d0
	cmp.w	d1,d0
	bls.s	.rb
	move.l	d5,spr_rows
	bsr	sprite_baked		; a0 = the slot
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

; bake_sprite: d2 = the key (code << 6 | colour << 2 | flip x << 1 | flip y), a0 = the slot.
; n, (row * 160, mask << 16) for the opaque rows in row order, then their 4 plane words.  hs_spr: per code 16 rows of
; 8 bytes (two pens a byte, the leftmost in the high nibble); MAME's flip x reverses the columns, flip y the rows.
bake_sprite:
	moveq	#0,d0
	move.w	d2,d0
	lsr.w	#6,d0			; the code (0-511)
	lsl.l	#7,d0			; 128 bytes a code
	lea	hs_spr,a1
	add.l	d0,a1
	move.w	d2,d0
	and.w	#$3C,d0			; the colour * 4
	add.w	d0,d0
	add.w	d0,d0
	lea	hs_spen,a2
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
	; the slot: n, the opaque rows (row * 160, mask << 16), their plane words
	lea	bake_rows,a3
	moveq	#0,d0			; n
	moveq	#15,d1
.cnt:	tst.w	(a3)
	beq.s	.c0
	addq.w	#1,d0
.c0:	lea	10(a3),a3
	dbf	d1,.cnt
	move.w	d0,(a0)+
	move.w	d0,d1
	add.w	d0,d0
	add.w	d1,d0
	add.w	d0,d0			; (6 bytes a row)
	lea	(a0,d0.w),a2		; the plane words' place
	lea	bake_rows,a3
	moveq	#0,d1			; the row
.ord:	move.w	(a3)+,d0
	beq.s	.skip
	move.w	d1,d3
	mulu	#LB,d3
	move.w	d3,(a0)+
	move.w	d0,(a0)+
	clr.w	(a0)+
	move.l	(a3)+,(a2)+
	move.l	(a3)+,(a2)+
	bra.s	.nr
.skip:	addq.l	#8,a3
.nr:	addq.w	#1,d1
	cmp.w	#16,d1
	bne.s	.ord
	rts

	section data,data
	include	"hs_assets.s"
hs_spr:		incbin	"hs_spr.bin"
hs_tiles:	incbin	"hs_tiles.bin"
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
row_scroll:	ds.w	NBUF*28			; per buffer and row: the scroll it was drawn at (-1: never)
guard_dirty:	ds.b	4			; per buffer: bit 0 the top guard lines, bit 1 the bottom ones hold sprites
spr_guard:	ds.b	1
frame_ready:	ds.b	1
	even
cell_ptr:	ds.l	1			; the end of cell_list (render_tiles empties it)
cell_list:	ds.w	2048			; the cells written since the renderer looked (main_io_w), once each
cell_dirty:	ds.b	2048			; their flags
tile_copy:	ds.b	4096			; the codes and colours the playfield has
line_off:	ds.l	16+224+16		; the offset of picture line Y (from -16) in a buffer
key_attr:	ds.w	256			; the cache key's part of the attributes (colour << 2, flips)
bake_rows:	ds.w	16*5
tc_index:	ds.w	65536			; per tile key: its slot + 1 (0: not converted)
tc_data:	ds.b	TC_SLOTS*32
sc_index:	ds.l	32768			; per sprite key: its slot (0: not baked)
sc_data:	ds.b	SC_SLOTS*SC_SIZE
	cnop	0,256
buffers:	ds.b	NBUF*BUFSZ+PF_LB*256
	section text,code
