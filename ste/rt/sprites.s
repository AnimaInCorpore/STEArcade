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
; flip x draws the lines the other way round, flip y is baked into the data.
;
; The endmasks are the mask of the sprite: one blit per sprite line writes the four
; planes of the line (Y count 4, source = destination, see the bob routines of
; stefastbobs2), and END1 / END3 are the outline of that line shifted to the two screen
; words it covers, holes included, so the pixels of the sprite replace what is below it and
; the rest is left alone.  The masks of every (shape, flip y, skew) come from a table
; (dk_spr_masks), the line words of the four planes from the colour data of the sprite
; (dk_spr_data: one set for every colour quad, i.e. for every distinct mapping of the pen
; values to the planes), which the Blitter's source address walks through line by line.
; The 16 pixel line is two screen words wide (u0 & 15 is the skew); the Blitter's NFSR
; lets the second word reuse the one source word of the plane (a skew of 0 is one word).
; Sprites are not clipped at the left and right of the game area (they spill into the
; black margin), only sprites entirely outside it are left out.
;
; Each draw screen remembers, per sprite slot, what it got there: the list entry, the
; colour bank and the rectangle (slot_state).  A frame first puts the background back
; where a slot's sprite has changed or is gone (A), then draws (B): a sprite that is the
; same as this screen already shows is skipped unless its rectangle touches something that
; was restored or drawn in this frame (a tile, the old rectangle of another sprite, a
; sprite earlier in the list), in which case it is drawn again over its own pixels.  The
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
BLT_SKEW = $ffff8a3d

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
; screen, d1.w = words per line (4: one chunk, 8: two); trashes d0-d5 and a6.

mark_rect:
	bsr.s	rect_cells
	move	mark_stamp,d2
.row:
	move	d4,d5
.col:
	move	d2,(a6,d5.w)
	subq	#2,d5
	bpl.s	.col
	lea	MARK_COLUMNS*2(a6),a6
	dbf	d3,.row
	rts

; Z set if none of the cells of the rectangle has been marked in this frame.

test_rect:
	bsr.s	rect_cells
	move	mark_stamp,d2
.row:
	move	d4,d5
.col:
	cmp	(a6,d5.w),d2
	beq.s	.touched
	subq	#2,d5
	bpl.s	.col
	lea	MARK_COLUMNS*2(a6),a6
	dbf	d3,.row
	moveq	#0,d5			; clean
	rts
.touched:
	moveq	#1,d5
	rts

; -> a6 = first cell, d3 = rows - 1, d4 = byte offset of the last column (a chunk is two
; 8 pixel tiles)

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
	lea	tile_marks,a6
	add	d5,a6
	move	d1,d4
	lsr	#2,d4			; chunks
	add	d4,d4			; tiles
	subq	#1,d4
	add	d4,d4
	rts

; ------------------------------------------------------------------------------
; The four plane blits of one sprite line.  d1 = Y count (4 planes), d2 = start (BUSY |
; HOG); a0 = masks, a1 = END1, a2 = control, a3 = destination address, a5 = Y count,
; d3 = address of the line, d4 = step to the next one.  Everything that stays the same
; from line to line (X count, skew, increments, the source address that walks on through
; the colour data) was written before.

sprite_first_line	macro
	move	(a0)+,(a1)		; END1
	move	(a0)+,4(a1)		; END3
	move	d1,(a5)
	move.b	d2,(a2)
	endm

sprite_line	macro
	move	(a0)+,(a1)
	move	(a0)+,4(a1)
	add.l	d4,d3
	move.l	d3,(a3)
	move	d1,(a5)
	move.b	d2,(a2)
	endm

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
	move.l	a4,a3

	; --- A: put the background back where a slot's sprite has changed or is gone.

	move	#2,BLT_SRC_XINC.w
	move	#2,BLT_DST_XINC.w
	move	#$0203,BLT_HOP_OP.w	; HOP 2 (source), OP 3 (destination = source)
	move	bank16,d6
	moveq	#127,d7

.restore:
	move.l	4(a4),d0		; rectangle (-1: nothing drawn)
	bmi.s	.store_entry
	move.l	(a1),d2
	cmp.l	(a4),d2
	bne.s	.changed
	cmp	10(a4),d6
	beq.s	.restore_next

.changed:
	move	8(a4),d1
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
	bsr	mark_rect		; the sprites that touch it have to be drawn again
	moveq	#-1,d0
	move.l	d0,4(a4)

.store_entry:
	move.l	(a1),(a4)		; the entry loop B works from

.restore_next:
	addq.l	#4,a1
	lea	SLOT_SIZE(a4),a4
	dbf	d7,.restore

	; --- B: draw the sprites.

	move	#2,BLT_SRC_XINC.w
	move	#2,BLT_SRC_YINC.w
	move	#8,BLT_DST_XINC.w	; next chunk of the same plane
	move	#$0203,BLT_HOP_OP.w	; HOP 2 (source), OP 3 (destination = source)

	move.l	a3,a4
	lea	BLT_END1.w,a1
	lea	BLT_CTRL.w,a2
	lea	BLT_DST_ADDR.w,a3
	lea	BLT_COUNT+2.w,a5
	moveq	#127,d7

sprite_loop:
	move.l	4(a4),d0
	bmi.s	.fresh
	move	8(a4),d1		; drawn and unchanged: is something on it?
	bsr	test_rect
	beq	sprite_next		; no

.fresh:
	moveq	#0,d0
	move.b	(a4),d0			; y
	moveq	#0,d1
	move.b	1(a4),d1		; code | flip y << 7
	moveq	#0,d2
	move.b	2(a4),d2		; colour | flip x << 7
	moveq	#0,d3
	move.b	3(a4),d3		; x

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

	; What this screen gets (for restoring later): both chunks (one if the skew is 0).

	move.l	d4,4(a4)
	moveq	#8,d3
	tst	d0
	bne.s	.two_chunks
	moveq	#4,d3
.two_chunks:
	move	d3,8(a4)
	move	bank16,10(a4)

	move.l	draw_screen_address,d3
	add.l	d4,d3			; address of the first line
	move.l	#256,d4			; step to the next line
	tst.b	d2
	bpl.s	.no_flip_x
	add.l	#15*256,d3		; flip x: from the last line upwards
	move.l	#-256,d4
.no_flip_x:

	; Masks: v = code * 2 + flip y, (v * 16 + skew) * 64.

	moveq	#0,d6
	move	d1,d6
	lsl	#1,d6
	and	#$100,d6		; flip y (bit 7 of d1) -> bit 8
	lsr	#8,d6
	and	#$7f,d1
	add	d1,d1
	add	d6,d1			; v
	moveq	#0,d6
	move	d1,d6
	lsl.l	#4,d6
	add	d0,d6
	lsl.l	#6,d6
	lea	dk_spr_masks,a0
	add.l	d6,a0

	; Colour data: (v * variant + quad of the colour code) bytes.

	mulu	#SPR_VARIANT,d1
	and	#15,d2
	add	bank16,d2
	add	d2,d2
	lea	dk_spr_quad,a6
	moveq	#0,d6
	move	(a6,d2.w),d6
	add.l	d6,d1
	add.l	#dk_spr_data,d1
	move.l	d1,BLT_SRC_ADDR.w
	move.l	d3,(a3)

	tst	d0
	beq.s	.skew0
	or.b	#NFSR,d0		; two words from the one source word of a plane
	move.b	d0,BLT_SKEW.w
	move	#2,BLT_COUNT.w		; X count (stays: only the Y count counts down)
	move	#-6,BLT_DST_YINC.w	; from the last word of a plane to the first of the next
	bra.s	.go
.skew0:
	clr.b	BLT_SKEW.w
	move	#1,BLT_COUNT.w
	move	#2,BLT_DST_YINC.w
.go:
	moveq	#4,d1			; Y count: the four planes
	moveq	#-64,d2			; BUSY | HOG
	wait_borders

	sprite_first_line
	sprite_line
	sprite_line
	sprite_line
	sprite_line
	sprite_line
	sprite_line
	sprite_line
	sprite_line
	sprite_line
	sprite_line
	sprite_line
	sprite_line
	sprite_line
	sprite_line
	sprite_line

	move.l	4(a4),d0		; sprites later in the list that touch it are drawn again
	move	8(a4),d1
	bsr	mark_rect

sprite_next:
	lea	SLOT_SIZE(a4),a4
	dbf	d7,sprite_loop
	rts

; ------------------------------------------------------------------------------
	section bss,bss
; ------------------------------------------------------------------------------

slot_state:	ds.b	2*128*SLOT_SIZE
tile_marks:	ds.w	MARK_ROWS*MARK_COLUMNS
mark_stamp:	ds.w	1
	section text,code
