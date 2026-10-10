; Blitter vs CPU for the Bubble Bobble tile renderer: the routines of ref/blit_bench.py.
;
; Screen: 160 bytes a line, 16 pixel groups of 4 plane words; a cell is 8 pixels = one byte of each plane word
; (even cell: the high bytes, odd cell: the low bytes).  A baked tile (the renderer's tcache entry, +8 = rows):
; per row the data long (plane 0-3 bytes) and the inverted mask long (1 = transparent).
;
; The CPU routines are the loops of draw_tile (render.s) unchanged.  The Blitter routines draw one tile row
; per blit (Y count 4 = the four planes, source = one word per plane, the row's opaque pixels as end masks).

STRIDE = 160
BLT = $ff8a00

	section text,code

; --- CPU: aligned tile with transparent pixels.  a1 = rows, a3 = the cell's first byte, d1 = 7
cpu_aligned:
.l:	move.l	(a1)+,d0
	move.l	(a1)+,d5
	movep.l	0(a3),d7
	and.l	d5,d7
	or.l	d0,d7
	movep.l	d7,0(a3)
	lea	STRIDE(a3),a3
	dbf	d1,.l
	rts

; --- CPU: aligned tile without transparent pixels
cpu_opaque:
.l:	move.l	(a1)+,d0
	addq.l	#4,a1
	movep.l	d0,0(a3)
	lea	STRIDE(a3),a3
	dbf	d1,.l
	rts

; --- CPU: tile at a shift of 1-7 pixels into its cell.  a0 = the entry, a3 = the left cell, a4 = the right cell,
;     d6 = the shift, d2 = MH (the high s bits of every byte), d3 = ~MH, d4 = 8 - s
cpu_shift:
	lea	8(a0),a1
	moveq	#8-1,d1
.lrow:
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
.rrow:
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
	rts

; --- CPU: clear a cell / copy a cell (rf_redraw, rf_copy).  a4 = destination cell, a5 = source cell, d1 = 0
cpu_clear:
	rept 8
	movep.l	d1,0(a4)
	lea	STRIDE(a4),a4
	endr
	rts

cpu_copy:
	rept 8
	movep.l	0(a5),d7
	movep.l	d7,0(a4)
	lea	STRIDE(a4),a4
	lea	STRIDE(a5),a5
	endr
	rts

; --- Blitter: one tile, one blit per row.  The tile's setup (source, destination, skew) is written by the
;     driver through the registers like a renderer would (counted as the first rows below).
;     a1 = END1 ($ff8a28), a6 = END3 ($ff8a2c), a2 = control ($ff8a3c), a3 = destination low word ($ff8a34),
;     a5 = Y count ($ff8a38), a4 = the row masks (END1 [, END3] per row), d3 = 4, d2 = $c0, d4 = 152, d1 = 7
blt_row1:				; one destination word a row (the tile inside one word)
.l:	move.w	(a4)+,(a1)		; END1
	move.w	d3,(a5)			; Y count 4
	move.b	d2,(a2)			; start (HOG)
	add.w	d4,(a3)			; the destination: the next line
	dbf	d1,.l
	rts

blt_row2:				; two destination words a row (the tile spills into the next group)
.l:	move.w	(a4)+,(a1)		; END1
	move.w	(a4)+,(a6)		; END3
	move.w	d3,(a5)
	move.b	d2,(a2)
	add.w	d4,(a3)
	dbf	d1,.l
	rts

; --- Blitter: a run of k groups x 8 lines in one blit (the driver writes the registers); a2 = control
blt_run:
	move.b	d2,(a2)
	rts
