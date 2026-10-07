; ------------------------------------------------------------------------------
; Sprite renderer (Blitter)
;
; The sprite list is the 128 entries at $7000 (bank = $7D83 bit 0 selects the
; half), filled by the sprite DMA (z80_dma, hooked on the $7D85 write): y, code
; | flip y, colour | flip x | code bit 7, x.  This is draw_sprites of MAME's
; dkong_v.cpp without the 16-sprites-per-scanline limit and without the wrap
; around: later entries are drawn over earlier ones.
;
; The screen is the arcade raster rotated 270 degrees (see assets.py): a sprite is
; a 16 line block with its left edge at display column u0 = y - 22 and its top
; line at display line v0 = (x + $F8) & $FF.  Lines run in sprite columns, so
; flip x is a Blitter source with the lines in reverse order, flip y is baked into the
; source streams (assets.py build_sprites).
;
; Every sprite is drawn plane by plane: one Blitter pass per screen plane that has bits
; set (source OR destination, the pen values that set that plane come from dk_spr_planes
; for the colour code).  There is no pass that clears the sprite's pixels first, so an
; opaque pixel is ORed into whatever is below it (see the notes in ste/README.md).
; The 16 pixel line is two screen words wide (u0 & 15 is the skew), the stream line is
; one source word that the Blitter's NFSR reuses for the neighbouring word.  Sprites are not
; clipped at the left and right of the game area (they spill into the black margin), only
; sprites entirely outside it are left out.
;
; Each draw screen remembers, per sprite slot, what it got there: the list entry, the
; colour bank and the rectangle (slot_state).  A frame first puts the background back
; where a slot's sprite has changed or is gone (A), then draws (B): a sprite that is the
; same as this screen already shows is skipped unless its rectangle touches something that
; was restored or redrawn in this frame (a tile, or the old rectangle of another sprite),
; in which case it is drawn again over its own pixels, which ORing makes harmless.  The
; touched places are 8 x 8 cells with the number of the frame in tile_marks.
; ------------------------------------------------------------------------------

BLT_SRC_XINC = $ffff8a20
BLT_SRC_YINC = $ffff8a22
BLT_SRC_ADDR = $ffff8a24
BLT_END1 = $ffff8a28
BLT_END2 = $ffff8a2a
BLT_END3 = $ffff8a2c
BLT_DST_XINC = $ffff8a2e
BLT_DST_YINC = $ffff8a30
BLT_DST_ADDR = $ffff8a32
BLT_COUNT = $ffff8a36
BLT_HOP_OP = $ffff8a3a
BLT_CTRL = $ffff8a3c

SPRITE_LINES = 16
SLOT_SIZE = 12				; list entry, rectangle offset (-1: none), words per line, colour bank
MARK_COLUMNS = 40			; cells per row of tile_marks: tile column + 4, 8 pixel tiles
MARK_ROWS = 36

init_sprites:
	lea	slot_state,a0
	move	#2*128-1,d0
.slots:
	clr.l	(a0)+
	moveq	#-1,d1
	move.l	d1,(a0)+		; no rectangle drawn
	clr.l	(a0)+
	dbf	d0,.slots

	lea	tile_marks,a0
	move	#MARK_ROWS*MARK_COLUMNS-1,d0
.marks:
	clr	(a0)+
	dbf	d0,.marks

	move	#1,mark_stamp
	rts

; ------------------------------------------------------------------------------
; The 8 x 8 cells of a rectangle.  d0.l = byte offset of the left word of plane 0 in the
; screen, d1.w = words per line (4: one chunk, 8: two); keeps d0 and d1, trashes d2-d5,
; a0, a2.

mark_rect:
	bsr.s	rect_cells
	move	mark_stamp,d2
.row:
	move.l	a2,a0
	move	d4,d5
.col:
	move	d2,(a0)+
	dbf	d5,.col
	lea	MARK_COLUMNS*2(a2),a2
	dbf	d3,.row
	rts

; Z set if none of the cells of the rectangle has been marked in this frame.

test_rect:
	bsr.s	rect_cells
	move	mark_stamp,d2
.row:
	move.l	a2,a0
	move	d4,d5
.col:
	cmp	(a0)+,d2
	beq.s	.touched
	dbf	d5,.col
	lea	MARK_COLUMNS*2(a2),a2
	dbf	d3,.row
	moveq	#0,d5			; clean
	rts
.touched:
	moveq	#1,d5
	rts

; -> a2 = first cell, d3 = rows - 1, d4 = columns - 1 (a chunk is two 8 pixel tiles)

rect_cells:
	move.l	d0,d2
	lsr.l	#8,d2			; display line of the top
	move	d2,d3
	lsr	#3,d3			; tile row of the top
	add	#15,d2
	lsr	#3,d2			; tile row of the bottom
	sub	d3,d2			; rows - 1
	move	d3,d5
	lsl	#5,d5
	lsl	#3,d3
	add	d3,d5			; row * 40
	move	d2,d3
	moveq	#0,d4
	move	d0,d4
	and	#255,d4
	sub	#GAME_X,d4
	asr	#3,d4			; chunk of the left word (-1 .. 14)
	add	d4,d4			; tile column
	addq	#4,d4
	add	d4,d5			; cell index
	add	d5,d5
	lea	tile_marks,a2
	add	d5,a2
	move	d1,d4
	lsr	#2,d4			; chunks
	add	d4,d4			; tiles
	subq	#1,d4
	rts

; ------------------------------------------------------------------------------
; a6 = Z80 block

draw_sprites:
	; Blitter state that stays: masks open, no halftone.

	move	#$ffff,BLT_END1.w
	move	#$ffff,BLT_END2.w
	move	#$ffff,BLT_END3.w

	moveq	#0,d0
	move.b	$7d83(a6),d0
	and	#1,d0
	lsl	#8,d0
	add	d0,d0
	lea	$7000(a6),a1
	add	d0,a1			; sprite list (bank)

	lea	slot_state,a4
	tst	draw_index
	beq.s	.first_screen
	lea	128*SLOT_SIZE(a4),a4	; this screen's slots
.first_screen:
	move.l	a1,a5			; for the second pass
	move.l	a4,a3

	; --- A: put the background back where a slot's sprite has changed or is gone.

	move	#2,BLT_SRC_XINC.w
	move	#2,BLT_DST_XINC.w
	move	#$0203,BLT_HOP_OP.w	; HOP 2 (source), OP 3 (destination = source)
	move	bank16,d6
	moveq	#127,d7

.restore:
	move.l	4(a4),d0		; rectangle (-1: nothing drawn)
	bmi.s	.restore_next
	move.l	(a1),d2
	cmp.l	(a4),d2
	bne.s	.changed
	cmp	10(a4),d6
	beq.s	.restore_next

.changed:
	move	8(a4),d1
	bsr	mark_rect		; the sprites that touch it have to be drawn again

	move	d1,d2
	add	d2,d2
	neg	d2
	add	#256+2,d2		; Y increment: back to the start, one line down
	move	d2,BLT_SRC_YINC.w
	move	d2,BLT_DST_YINC.w
	move.l	bg_address,d3
	add.l	d0,d3
	move.l	d3,BLT_SRC_ADDR.w
	move.l	draw_screen_address,d3
	add.l	d0,d3
	move.l	d3,BLT_DST_ADDR.w
	move	d1,BLT_COUNT.w		; X count
	move	#SPRITE_LINES,BLT_COUNT+2.w
	wait_borders
	move	#$c000,BLT_CTRL.w
	moveq	#-1,d0
	move.l	d0,4(a4)

.restore_next:
	addq.l	#4,a1
	lea	SLOT_SIZE(a4),a4
	dbf	d7,.restore

	; --- B: draw the sprites.

	move	#2,BLT_SRC_XINC.w
	move	#8,BLT_DST_XINC.w	; next chunk of the same plane
	move	#256-8,BLT_DST_YINC.w
	move	#$0207,BLT_HOP_OP.w	; HOP 2 (source), OP 7 (source OR destination)

	move.l	a5,a1
	move.l	a3,a4
	move.l	draw_screen_address,a3
	moveq	#127,d7

sprite_loop:
	move.l	4(a4),d0
	bmi.s	.fresh
	move	8(a4),d1		; drawn and unchanged: is something on it?
	bsr	test_rect
	bne.s	.fresh
	addq.l	#4,a1
	bra	sprite_next

.fresh:
	moveq	#0,d0
	move.b	(a1)+,d0		; y
	moveq	#0,d1
	move.b	(a1)+,d1		; code | flip y << 7
	moveq	#0,d2
	move.b	(a1)+,d2		; colour | flip x << 7 | code bit 7
	moveq	#0,d3
	move.b	(a1)+,d3		; x

	sub	#22,d0			; u0: left display column (-22 .. 233)
	cmp	#-16,d0
	ble	sprite_next		; completely left of the game area
	cmp	#224,d0
	bge	sprite_next		; completely right of it

	move	d0,d4
	asr	#4,d4			; chunk of the left word (-1 .. 13)
	and	#15,d0			; skew

	add	#$f8,d3
	and	#$ff,d3			; v0: top display line
	lsl	#8,d3			; line offset

	ext.l	d4
	lsl.l	#3,d4
	add.l	d3,d4
	add.l	#GAME_X,d4		; byte offset of the left word of plane 0

	; Rectangle for restoring: both chunks (one if the skew is 0).

	move.l	d4,4(a4)
	moveq	#8,d3
	tst	d0
	bne.s	.two_chunks
	moveq	#4,d3
.two_chunks:
	move	d3,8(a4)
	move	d6,10(a4)
	move.l	-4(a1),(a4)

	move.l	a3,a2
	add.l	d4,a2			; screen address of plane 0, left word

	; Source stream.

	move	d1,d3
	lsl	#1,d3
	and	#$100,d3		; flip y (bit 7 of d1) -> bit 8
	and	#$7f,d1
	add	d1,d1
	lsr	#8,d3			; flip y as 0/1
	add	d3,d1			; code * 2 + flip y
	move.l	d1,d3
	lsl.l	#3,d1
	sub.l	d3,d1
	lsl.l	#5,d1			; * 7 streams of 32 bytes
	lea	dk_sprites-32,a0
	add.l	d1,a0			; the stream of pen mask n is at + n * 32

	moveq	#2,d3			; source Y increment: the next line word
	tst.b	d2
	bpl.s	.no_flip_x
	lea	30(a0),a0		; flip x: lines from the last one
	moveq	#-2,d3			; and the previous one
.no_flip_x:

	; Colour code -> which pen values set each plane.

	and	#15,d2
	add	d6,d2
	lsl	#2,d2
	lea	dk_spr_planes,a5
	add	d2,a5			; a5: the four plane masks

	; The routine for this skew draws the four planes.

	add	d0,d0
	add	d0,d0
	lea	sprite_routines,a6
	move.l	(a6,d0.w),a6
	jmp	(a6)

sprite_next:
	lea	SLOT_SIZE(a4),a4
	dbf	d7,sprite_loop
	rts

; ------------------------------------------------------------------------------
; One routine per skew (u0 & 15), the way the bob routines of stefastbobs2 are: the
; endmask of the left word (the bits that word takes from the sprite), the skew and the
; word count are constants.  A line is one source word; for skew 1-15 the Blitter's NFSR
; lets the right destination word reuse it (both endmasks are constants, they keep what
; the Blitter shifts in for the second word out).  Only the source address, the destination address, the counts and the
; start change from one pass to the next.
; a0 = stream base, a2 = left word of plane 0, a5 = plane masks, d3 = source Y increment.

sprite_plane	macro
	moveq	#0,d1
	move.b	(a5)+,d1		; pen values that set this plane
	beq.s	.none\@
	lsl	#5,d1
	lea	(a0,d1.w),a6
	move.l	a6,BLT_SRC_ADDR.w
	move.l	a2,BLT_DST_ADDR.w
	move	#SPRITE_LINES,BLT_COUNT+2.w	; Y count (the X count stays)
	move	#$c000+\2+\1,BLT_CTRL.w	; BUSY | HOG, NFSR (two words from one source word), skew
.none\@:
	addq.l	#2,a2
	endm

; \1 = skew, \2 = X count, \3 = destination Y increment, \4 = NFSR (a sprite of skew 0 is
; one word wide, so it needs no NFSR), \5 = endmask of the right word

sprite_skew	macro
draw_sprite_\1:
	wait_borders
	move	#$ffff>>\1,BLT_END1.w
	move	#\5,BLT_END3.w
	move	#\2,BLT_COUNT.w
	move	#\3,BLT_DST_YINC.w
	move	d3,BLT_SRC_YINC.w
	sprite_plane	\1,\4
	sprite_plane	\1,\4
	sprite_plane	\1,\4
	sprite_plane	\1,\4
	bra	sprite_next
	endm

	sprite_skew	0,1,256,0,$ffff
	sprite_skew	1,2,256-8,NFSR,($ffff<<(16-1))&$ffff
	sprite_skew	2,2,256-8,NFSR,($ffff<<(16-2))&$ffff
	sprite_skew	3,2,256-8,NFSR,($ffff<<(16-3))&$ffff
	sprite_skew	4,2,256-8,NFSR,($ffff<<(16-4))&$ffff
	sprite_skew	5,2,256-8,NFSR,($ffff<<(16-5))&$ffff
	sprite_skew	6,2,256-8,NFSR,($ffff<<(16-6))&$ffff
	sprite_skew	7,2,256-8,NFSR,($ffff<<(16-7))&$ffff
	sprite_skew	8,2,256-8,NFSR,($ffff<<(16-8))&$ffff
	sprite_skew	9,2,256-8,NFSR,($ffff<<(16-9))&$ffff
	sprite_skew	10,2,256-8,NFSR,($ffff<<(16-10))&$ffff
	sprite_skew	11,2,256-8,NFSR,($ffff<<(16-11))&$ffff
	sprite_skew	12,2,256-8,NFSR,($ffff<<(16-12))&$ffff
	sprite_skew	13,2,256-8,NFSR,($ffff<<(16-13))&$ffff
	sprite_skew	14,2,256-8,NFSR,($ffff<<(16-14))&$ffff
	sprite_skew	15,2,256-8,NFSR,($ffff<<(16-15))&$ffff

sprite_routines:
	dc.l	draw_sprite_0,draw_sprite_1,draw_sprite_2,draw_sprite_3
	dc.l	draw_sprite_4,draw_sprite_5,draw_sprite_6,draw_sprite_7
	dc.l	draw_sprite_8,draw_sprite_9,draw_sprite_10,draw_sprite_11
	dc.l	draw_sprite_12,draw_sprite_13,draw_sprite_14,draw_sprite_15

; ------------------------------------------------------------------------------
	section bss,bss
; ------------------------------------------------------------------------------

slot_state:	ds.b	2*128*SLOT_SIZE
tile_marks:	ds.w	MARK_ROWS*MARK_COLUMNS
mark_stamp:	ds.w	1
	section text,code
