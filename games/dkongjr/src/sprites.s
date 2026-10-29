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
; a 16 line block with its left edge at display column u0 = y - 23 and its top
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
; lets the second word reuse the one source word of a plane (a skew of 0 is one word).
; The empty lines at either end of a shape are left out (dk_spr_span), a blank shape
; draws nothing.  The game area's left and right edges lie on chunk boundaries (GAME_X =
; 3 chunks, 14 chunks wide): a sprite across one draws only its inner word, one word a
; line (sprite_edge, sprite_draw 1; the side bands stay black and are never restored),
; a sprite entirely outside is left out.  The common path tests both with one unsigned
; compare.  Sprites are not clipped at the top and bottom (MARK_ROWS, the 64 KB screens).
;
; Most of the 128 entries are empty (y = 0), so a frame first lists the entries that are
; not (the active list), and each draw screen keeps the list it was last drawn with.
; Each draw screen remembers, per sprite slot, what it got there: the list entry, the
; colour bank, the rectangle and its cells (slot_state).  A frame first puts the
; background back where a slot's sprite has changed or is gone (A, over the screen's old
; list), then draws the active list (B): a sprite that is the same as this screen already
; shows is skipped unless its rectangle touches something that was restored or drawn in
; this frame (a tile, the old rectangle of another sprite, a sprite earlier in the list),
; in which case it is drawn again over its own pixels.  The touched places are 8 x 8
; cells, a bit each in tile_marks (a row of the display is 8 bytes, bit 7 of the first
; byte is cell column 0 = tile column -4), cleared every frame; a sprite's cells are a
; window of four bits in up to three rows, kept in its slot record.
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

; (MARK_ROWS / MARK_SIZE of tile_marks: dkong.s)

; Slot record (one per sprite slot and draw screen)

SLOT_SIZE = 32
S_ENTRY = 0				; .l  the list entry drawn
S_RECT = 4				; .l  byte offset of the rectangle's first word in the screen, -1: none
S_WORDS = 8				; .w  words per line of the rectangle (4: one chunk, 8: two)
S_BANK = 10				; .w  colour bank it was drawn with
S_MASK1 = 12				; .l  the cells: bits of the window long in row 1
S_MASK2 = 16				; .l  the same for row 2 (0 if the rectangle has one row)
S_MASK3 = 20				; .l  the same for row 3 (0 if it has two)
S_MARK = 24				; .w  byte offset of the window long of row 1 in tile_marks
S_LIST = 26				; .w  byte offset of the slot's entry in the sprite list
S_LINES = 28				; .w  lines of the rectangle
S_FIRST = 30				; .w  first line of the shape that is drawn

init_sprites:
	lea	slot_state,a0
	moveq	#0,d2			; entry offset
	move	#2*128-1,d0
.slots:
	clr.l	(a0)+			; entry
	moveq	#-1,d1
	move.l	d1,(a0)+		; no rectangle drawn
	clr.l	(a0)+			; words, bank
	clr.l	(a0)+			; masks
	clr.l	(a0)+
	clr.l	(a0)+
	clr	(a0)+			; mark
	move	d2,(a0)+		; list
	clr.l	(a0)+			; lines, first
	addq	#4,d2
	and	#$1ff,d2		; the second screen's slots start over
	dbf	d0,.slots

	lea	lists,a0		; the screens' lists are empty, the third is free
	clr.l	(a0)
	move.l	a0,screen_lists
	lea	(128+1)*4(a0),a0
	clr.l	(a0)
	move.l	a0,screen_lists+4
	lea	(128+1)*4(a0),a0
	move.l	a0,free_list
	rts

; ------------------------------------------------------------------------------
; The cells of a slot's rectangle (a4 = slot record): mark them / test whether one of
; them is marked (Z clear).  Both use a6, d0 and d1.

mark_rect	macro
	lea	tile_marks,a6
	add	S_MARK(a4),a6
	move.l	S_MASK1(a4),d0
	or.l	d0,(a6)
	move.l	S_MASK2(a4),d0
	or.l	d0,8(a6)
	move.l	S_MASK3(a4),d0
	or.l	d0,16(a6)
	endm

test_rect	macro
	lea	tile_marks,a6
	add	S_MARK(a4),a6
	move.l	S_MASK1(a4),d0
	and.l	(a6),d0
	bne.s	.t\@
	move.l	S_MASK2(a4),d0
	and.l	8(a6),d0
	bne.s	.t\@
	move.l	S_MASK3(a4),d0
	and.l	16(a6),d0
.t\@:
	endm

; ------------------------------------------------------------------------------
; The four plane blits of one sprite line.  d1 = Y count (4 planes), d2 = start (BUSY |
; HOG); a0 = masks, a1 = END1, a6 = END3, a2 = control, a3 = destination address (low word),
; a5 = Y count, d3 / d4 = see below.  Everything that stays the same from line to line
; (X count, skew, increments, the source address that walks on through the colour data)
; was written before.  The blitter registers are written through preloaded pointers.
;
; Fast: the destination register ends a line 8 bytes after its first word, so d4 (248, or
; -264 for flip x) takes it to the next line, added to the low word of the register.  That
; wraps at a 64 KB boundary, which the lines of a sprite on the bottom edge cross, so
; those use the slow macro: d3 = address of the line, d4 = +-256, the whole address.
; The macros are 10 and 14 bytes: a sprite of n lines enters the unrolled sequence
; 16 - n lines from its start.

sprite_first_line	macro
	move	(a0)+,(a1)		; END1
	move	(a0)+,(a6)		; END3
	move	d1,(a5)
	move.b	d2,(a2)
	endm

sprite_line	macro
	move	(a0)+,(a1)
	move	(a0)+,(a6)
	add	d4,(a3)
	move	d1,(a5)
	move.b	d2,(a2)
	endm

sprite_slow_line	macro
	move	(a0)+,(a1)
	move	(a0)+,(a6)
	add.l	d4,d3
	move.l	d3,-2(a3)
	move	d1,(a5)
	move.b	d2,(a2)
	endm

; ------------------------------------------------------------------------------
; One sprite from its u0 (d0) on, d1 = code | flip y << 7, d2 = colour | flip x << 7, d3 = x, a4 = slot record.
; \1 = 1: a sprite across the left or right edge of the game area (sprite_edge).

sprite_draw	macro

	; v = code * 2 + flip y; the lines of the shape that are drawn.

	move	d1,d6
	lsl	#1,d6
	and	#$100,d6		; flip y (bit 7 of d1) -> bit 8
	lsr	#8,d6
	and	#$7f,d1
	add	d1,d1
	add	d6,d1			; v
	lea	dk_spr_span,a6
	move	d1,d6
	add	d6,d6
	move	(a6,d6.w),d5		; first line, number of lines
	tst.b	d5
	beq	sprite_loop		; blank shape (nothing to restore either)
	move	d5,d6
	and	#$ff,d6
	move	d6,S_LINES(a4)
	lsr	#8,d5
	move	d5,S_FIRST(a4)

	move	d0,d4
	asr	#4,d4			; chunk of the left word (-1 .. 13)
	and	#15,d0			; skew
	ifne \1
	tst	d4			; edge: -1 left (the second word is drawn), 13 right (the first)
	bpl.s	.inner
	moveq	#0,d4			; (the inner chunk: the rectangle and cells are its own)
	bset	#30,d0			; left
.inner:
	endc

	add	#$f8,d3
	and	#$ff,d3			; v0: display line of the shape's line 0
	tst.b	d2
	bpl.s	.top_set
	moveq	#16,d5			; flip x: the drawn lines are at the far end
	sub	S_FIRST(a4),d5
	sub	d6,d5
.top_set:
	add	d5,d3			; top display line of the rectangle

	; The cells: rows from the top line on (one to three), cell columns 2 * chunk + 4 on
	; (four, two if the skew is 0): a window of bits in the row's long at byte 0 or 2.

	move	d3,d5
	and	#$f8,d5			; row * 8
	move	d4,d6
	add	d6,d6
	addq	#4,d6			; first cell column
	cmp	#16,d6
	blt.s	.window0
	addq	#2,d5
	sub	#16,d6
.window0:
	move	d5,S_MARK(a4)
	ifeq \1
	move.l	#$f0000000,d5
	tst	d0
	bne.s	.four_cells
	endc
	move.l	#$c0000000,d5		; (an edge sprite: the inner chunk's two)
.four_cells:
	lsr.l	d6,d5
	move.l	d5,S_MASK1(a4)
	move	d3,d6
	and	#7,d6
	add	S_LINES(a4),d6
	subq	#1,d6
	lsr	#3,d6			; rows - 1
	beq.s	.one_row
	move.l	d5,S_MASK2(a4)
	subq	#1,d6
	beq.s	.two_rows
	move.l	d5,S_MASK3(a4)
	bra.s	.rows_set
.one_row:
	clr.l	S_MASK2(a4)
.two_rows:
	clr.l	S_MASK3(a4)
.rows_set:

	; What this screen gets (for restoring later): the rectangle of the drawn lines, both
	; chunks (one if the skew is 0, or the inner one of an edge sprite).

	lsl	#8,d3			; line offset
	ext.l	d4
	lsl.l	#3,d4
	add.l	d3,d4
	add.l	#GAME_X,d4		; byte offset of the left word of plane 0
	move.l	d4,S_RECT(a4)
	ifeq \1
	moveq	#8,d3
	tst	d0
	bne.s	.two_chunks
	endc
	moveq	#4,d3
.two_chunks:
	move	d3,S_WORDS(a4)
	move	bank16,S_BANK(a4)

	moveq	#0,d6
	move	S_LINES(a4),d6
	subq	#1,d6
	lsl.l	#8,d6			; offset of the last line
	move.l	draw_screen_address,d3
	add.l	d4,d3			; address of the top line
	ifeq \1				; (an edge sprite: the generic masks and full addresses)
	cmp	#$f000,d3		; the lines would cross a 64 KB boundary (low word wraps)
	bhs.s	.slow_lines

	move	#248,d4			; step from the end of one line's blits to the next line
	tst.b	d2
	bpl.s	.lines_set
	add.l	d6,d3			; flip x: from the last line upwards
	move	#-264,d4
	bra.s	.lines_set
	endc

.slow_lines:
	bset	#31,d0			; (the skew is in the low word)
	move.l	#256,d4
	tst.b	d2
	bpl.s	.lines_set
	add.l	d6,d3
	move.l	#-256,d4
.lines_set:

	; Shape/skew selects code shared by all colour quads. Boundary sprites
	; retain the generic masks and full destination address writes.
	moveq	#0,d6
	move	d1,d6
	lsl.l	#4,d6
	add	d0,d6
	lsl.l	#2,d6
	ifeq \1
	ifnd NOSPRITECODE
	tst.l	d0
	bmi.s	.generic_masks
	add.l	d6,d6			; eight-byte code/mask-stream record
	lea	dk_spr_code,a0
	move.l	(a0,d6.l),d5
	move.l	4(a0,d6.l),a0
	bra.s	.masks_set
.generic_masks:
	endc
	endc
	lsl.l	#4,d6
	move	S_FIRST(a4),d5
	lsl	#2,d5
	add	d5,d6
	lea	dk_spr_masks,a0
	add.l	d6,a0
.masks_set:

	; Colour data: (v * variant + quad of the colour code + first * 8) bytes.

	mulu	#SPR_VARIANT,d1
	and	#15,d2
	add	bank16,d2
	add	d2,d2
	lea	dk_spr_quad,a6
	moveq	#0,d6
	move	(a6,d2.w),d6
	add.l	d6,d1
	moveq	#0,d6
	move	S_FIRST(a4),d6
	lsl.l	#3,d6
	add.l	d6,d1
	add.l	#dk_spr_data,d1
	move.l	d1,BLT_SRC_ADDR.w
	move.l	d3,BLT_DST_ADDR.w

	ifne \1
	; An edge sprite: one word a line (X count 1, END1).  Right edge: the first word, the
	; skewed source word under the line's END1 mask (the bits of the word before it fall
	; outside the mask).  Left edge: the second word (its address is the rectangle's), FXSR:
	; (this source word : the next) >> skew under the line's END3 mask, which the line
	; macros write to END1 after the END1 mask (a6 = END1); the source Y increment 0 makes
	; the two reads of a plane advance one word.  No other mask is computed: the stored
	; masks of the shape and skew, the lines of the generic sequence.
	move	#1,BLT_COUNT.w
	move	#2,BLT_DST_YINC.w	; next plane
	lea	BLT_END3.w,a6		; (right: END3 is not used)
	bclr	#30,d0
	beq.s	.right
	or.b	#$80,d0			; FXSR
	clr	BLT_SRC_YINC.w
	lea	BLT_END1.w,a6
.right:
	move.b	d0,BLT_SKEW.w		; (no NFSR)
	moveq	#4,d1			; Y count: the four planes
	moveq	#-64,d2			; BUSY | HOG
	moveq	#16,d6
	sub	S_LINES(a4),d6		; lines of the unrolled sequence to leave out
	move	d6,d5
	add	d5,d5			; (on at .slow_blits)
	else

	ifnd NOSPRITECODE
	tst.l	d0
	bpl.s	.go			; generated code sets width/skew itself
	endc
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

	ifnd NOSPRITECODE
	tst.l	d0
	bmi.s	.generic_seq
	move.l	d5,a6
	jsr	(a6)
	bra	.blits_done
.generic_seq:
	lea	BLT_END3.w,a6
	moveq	#16,d6
	sub	S_LINES(a4),d6		; lines of the unrolled sequence to leave out
	move	d6,d5
	add	d5,d5

	bra	.slow_blits
	else
	lea	BLT_END3.w,a6
	moveq	#16,d6
	sub	S_LINES(a4),d6		; lines of the unrolled sequence to leave out
	move	d6,d5
	add	d5,d5

	tst.l	d0
	bmi	.slow_blits

	lsl	#3,d6
	add	d5,d6			; * 10 bytes
	sprite_first_line
	jmp	.lines(pc,d6.w)
.lines:
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
	bra	.blits_done

	endc
	endc

.slow_blits:
	lsl	#4,d6
	sub	d5,d6			; * 14 bytes
	sprite_first_line
	jmp	.slow_seq(pc,d6.w)
.slow_seq:
	sprite_slow_line
	sprite_slow_line
	sprite_slow_line
	sprite_slow_line
	sprite_slow_line
	sprite_slow_line
	sprite_slow_line
	sprite_slow_line
	sprite_slow_line
	sprite_slow_line
	sprite_slow_line
	sprite_slow_line
	sprite_slow_line
	sprite_slow_line
	sprite_slow_line

.blits_done:
	ifne \1
	move	#2,BLT_SRC_YINC.w	; (the left edge's 0)
	endc
	mark_rect			; sprites later in the list that touch it are drawn again
	bra	sprite_loop
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
	move.l	a1,spr_list

	lea	slot_state,a4
	move	draw_index,d0
	beq.s	.first_screen
	lea	128*SLOT_SIZE(a4),a4	; this screen's slots
.first_screen:

	; --- The active list: the records of the entries that are not empty.

	move.l	free_list,a2
	move.l	a1,a5
	moveq	#32-1,d7
.scan:
	tst.l	(a5)+
	bne.s	.f0
.c1:	tst.l	(a5)+
	bne.s	.f1
.c2:	tst.l	(a5)+
	bne.s	.f2
.c3:	tst.l	(a5)+
	bne.s	.f3
.c4:	lea	4*SLOT_SIZE(a4),a4
	dbf	d7,.scan
	clr.l	(a2)
	bra.s	.scanned

.f0:	move.l	a4,(a2)+
	bra.s	.c1
.f1:	lea	SLOT_SIZE(a4),a0
	move.l	a0,(a2)+
	bra.s	.c2
.f2:	lea	2*SLOT_SIZE(a4),a0
	move.l	a0,(a2)+
	bra.s	.c3
.f3:	lea	3*SLOT_SIZE(a4),a0
	move.l	a0,(a2)+
	bra.s	.c4
.scanned:

	; --- A: put the background back where a slot's sprite has changed or is gone (the
	; slots of the screen's last list).

	move	#2,BLT_SRC_XINC.w
	move	#2,BLT_DST_XINC.w
	move	#$0203,BLT_HOP_OP.w	; HOP 2 (source), OP 3 (destination = source)
	move	bank16,d6
	add	d0,d0
	add	d0,d0
	lea	screen_lists,a2
	move.l	(a2,d0.w),a2

.restore:
	move.l	(a2)+,d0
	beq	.restored
	move.l	d0,a4
	move.l	S_RECT(a4),d0
	bmi.s	.restore		; nothing on the screen
	move	S_LIST(a4),d1
	move.l	(a1,d1.w),d2
	cmp.l	(a4),d2
	bne.s	.changed
	cmp	S_BANK(a4),d6
	beq.s	.restore

.changed:
	move	S_WORDS(a4),d1
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
	move	S_LINES(a4),BLT_COUNT+2.w
	clr.b	BLT_SKEW.w
	bsr	blit_go			; (up to 8 x 16 words: in pieces)
	mark_rect			; the sprites that touch it have to be drawn again
	moveq	#-1,d0
	move.l	d0,S_RECT(a4)
	bra	.restore

.restored:

	; --- B: draw the active list.

	move	#2,BLT_SRC_XINC.w
	move	#2,BLT_SRC_YINC.w
	move	#8,BLT_DST_XINC.w	; next chunk of the same plane
	move	#$0203,BLT_HOP_OP.w	; HOP 2 (source), OP 3 (destination = source)

	move.l	free_list,d7		; the list pointer (exchanged into a6 for a moment)
	lea	BLT_END1.w,a1
	lea	BLT_CTRL.w,a2
	lea	BLT_DST_ADDR+2.w,a3
	lea	BLT_COUNT+2.w,a5

sprite_loop:
	exg	d7,a6
	move.l	(a6)+,d0
	exg	d7,a6
	beq	sprites_done
	move.l	d0,a4
	tst.l	S_RECT(a4)
	bmi.s	.fresh
	test_rect			; drawn and unchanged: is something on it?
	beq	sprite_loop		; no

.fresh:
	move.l	spr_list,a6
	move	S_LIST(a4),d1
	move.l	(a6,d1.w),(a4)		; the entry this screen gets

	moveq	#0,d0
	move.b	(a4),d0			; y
	moveq	#0,d1
	move.b	1(a4),d1		; code | flip y << 7
	moveq	#0,d2
	move.b	2(a4),d2		; colour | flip x << 7
	moveq	#0,d3
	move.b	3(a4),d3		; x

	sub	#23,d0			; u0: left display column (-23 .. 232)
	cmp	#224-16,d0
	bhi	sprite_edge		; u0 < 0 or > 208: across the left or right edge, or outside
	sprite_draw 0

; Sprites across the left (u0 -15 .. -1) or right (209 .. 223) edge of the game area: only the inner word.

sprite_edge:
	cmp	#-16,d0
	ble	sprite_loop		; completely left of the game area
	cmp	#224,d0
	bge	sprite_loop		; completely right of it
	sprite_draw 1

sprites_done:
	; The active list is what this screen shows now; its old list is free.

	move	draw_index,d0
	add	d0,d0
	add	d0,d0
	lea	screen_lists,a0
	move.l	free_list,d1
	move.l	(a0,d0.w),free_list
	move.l	d1,(a0,d0.w)
	rts

; ------------------------------------------------------------------------------
	section bss,bss
; ------------------------------------------------------------------------------

slot_state:	ds.b	2*128*SLOT_SIZE
lists:		ds.l	3*(128+1)	; records, 0 ends a list
screen_lists:	ds.l	2		; the list each draw screen was drawn with
free_list:	ds.l	1
spr_list:	ds.l	1		; the sprite list of the frame (bank applied)
tile_marks:	ds.b	MARK_SIZE
	section text,code
