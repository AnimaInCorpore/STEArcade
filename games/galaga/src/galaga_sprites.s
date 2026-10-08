; ------------------------------------------------------------------------------
; Sprite renderer (Blitter), after games/dkong/src/sprites.s of the Donkey Kong port.
;
; The arcade's sprite table is 64 entries in three parts of the shared RAM: code |
; colour at $8B80, x | y at $9380, flags at $9B80 (flip x, flip y, double width, double
; height, x bit 8), see galaga.py render_raw.  A frame first gathers the 64 entries into
; 8 bytes each (spr_entries) and lists the ones that are on the screen.  An entry is up to
; four 16 x 16 parts (double sizes); every part has a slot record per draw screen (what
; was drawn there: rectangle, cells), 4 records per entry.
;
; The screen is the arcade raster rotated by 90 degrees: a 16 x 16 part at raw (sx, sy)
; has its top line at display line sx and its left edge at display column 208 - sy; a
; line of the blit is a column of the arcade sprite.  Flip x reverses the lines, flip y is
; baked into the data (variant = code * 2 + flip y, tools/assets.py).  Lines are 16
; pixels, two screen words (skew = column & 15), the endmasks are the shape's outline
; per line (dk_spr_masks' way): one blit of 4 planes per line, the source walking
; through the colour data of the shape's colour quad.
;
; Otherwise as in Donkey Kong: a draw screen remembers per slot what it got, restores the
; background under changed/gone parts, draws the parts of the active entries that
; changed or whose cells were touched (8 x 8 cell bits in tile_marks, MARK_TOP rows above
; the display since sprites hang over), later entries over earlier ones.  The cells a
; part is drawn in are also set in spr_marks (the characters are drawn over sprites,
; chars_over).
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

; Slot record (one per part and draw screen)

SLOT_SIZE = 32
S_ENTRY = 0				; .l  the entry drawn (bytes 0-3: code, colour, x, y)
S_RECT = 4				; .l  byte offset of the rectangle's first word in the screen, -1: none
S_WORDS = 8				; .w  words per line (4 or 8)
S_FLAGS = 10				; .w  entry bytes 4-5 (flags, x high) when drawn
S_MASK1 = 12				; .l  the cells: bits of the window long in rows 1-3
S_MASK2 = 16
S_MASK3 = 20
S_MARK = 24				; .w  byte offset of the window long of row 1 in tile_marks
S_LINES = 28				; .w  lines of the rectangle
S_FIRST = 30				; .w  first line of the shape that is drawn

ENTRY_SIZE = 8				; spr_entries: code, colour, x, y, flags, xhigh, pad

init_sprites:
	lea	slot_state,a0
	move	#2*256-1,d0
	moveq	#-1,d1
.slots:
	clr.l	(a0)+
	move.l	d1,(a0)+		; no rectangle drawn
	moveq	#5,d2
.z:	clr.l	(a0)+
	dbf	d2,.z
	dbf	d0,.slots
	lea	spr_entries,a0
	move	#64*ENTRY_SIZE/4-1,d0
.e:	clr.l	(a0)+
	dbf	d0,.e
	lea	slot_any,a0
	moveq	#2*64/4-1,d0
.a:	clr.l	(a0)+
	dbf	d0,.a
	rts

; ------------------------------------------------------------------------------
; The cells of a record's rectangle (a4): mark them (tile_marks, and spr_marks for a
; drawn part) / test whether one is marked.  Both use a6, d0 and d1.

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

mark_drawn	macro
	lea	spr_marks,a6
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

; Z set: no cell under the part's rectangle has a character in the background
test_content	macro
	lea	cell_content,a6
	add	S_MARK(a4),a6
	move.l	S_MASK1(a4),d2
	and.l	(a6),d2
	bne.s	.c\@
	move.l	S_MASK2(a4),d2
	and.l	8(a6),d2
	bne.s	.c\@
	move.l	S_MASK3(a4),d2
	and.l	16(a6),d2
.c\@:
	endm

sprite_first_line	macro
	move	(a0)+,(a1)
	move	(a0)+,(a6)
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

draw_sprites:
	move	#$ffff,BLT_END1.w
	move	#$ffff,BLT_END2.w
	move	#$ffff,BLT_END3.w

	; --- Gather the entries: code, colour, x, y, flags, x high.

	lea	g_ram+$0b80,a0
	lea	g_ram+$1380,a1
	lea	g_ram+$1b80,a2
	lea	spr_entries,a3
	moveq	#63,d7
.gather:
	move	(a0)+,(a3)+		; code, colour
	move	(a1)+,d0		; y (raw sy), x low  (MAME: spriteram_2[offs] = y, +1 = x)
	ror	#8,d0
	move	d0,(a3)+		; x low, y
	move	(a2)+,(a3)+		; flags, x high
	clr	(a3)+
	dbf	d7,.gather

	lea	slot_state,a4
	move	draw_index,d0
	beq.s	.first_screen
	lea	256*SLOT_SIZE(a4),a4	; this screen's records (4 per entry)
.first_screen:
	move.l	a4,slot_base
	mulu	#64,d0
	lea	slot_any,a0		; per entry: 1 if a part of it is on this screen
	add	d0,a0
	move.l	a0,any_base

	; --- A: put the background back under the parts of entries that changed.

	move	#2,BLT_SRC_XINC.w
	move	#2,BLT_DST_XINC.w
	move	#$0203,BLT_HOP_OP.w
	lea	spr_entries,a1
	moveq	#63,d7
.entries_a:
	move.l	(a1),d2
	cmp.l	S_ENTRY(a4),d2
	bne.s	.changed
	move	4(a1),d2
	cmp	S_FLAGS(a4),d2
	beq	.next_a
.changed:
	tst.b	(a0)			; nothing of it on the screen: nothing to restore
	beq	.next_a
	moveq	#3,d6			; the four part records
.parts_a:
	move.l	S_RECT(a4),d0
	bmi	.part_next_a
	ifnd NOZEROFILL
	test_content
	bne.s	.copy_a
	; only black below: fill with zeros (HOP 1, OP 0: no source read, half the bus cycles)
	move	S_WORDS(a4),d1
	move	d1,d2
	add	d2,d2
	neg	d2
	add	#256+2,d2
	move	d2,BLT_DST_YINC.w
	move.l	draw_screen_address,d3
	add.l	d0,d3
	move.l	d3,BLT_DST_ADDR.w
	move	d1,BLT_COUNT.w
	move	S_LINES(a4),BLT_COUNT+2.w
	move	#$0100,BLT_HOP_OP.w
	wait_borders
	move	#$c000,BLT_CTRL.w
	move	#$0203,BLT_HOP_OP.w
	mark_rect
	moveq	#-1,d0
	move.l	d0,S_RECT(a4)
	bra.s	.part_next_a
	endc
.copy_a:
	move	S_WORDS(a4),d1
	move	d1,d2
	add	d2,d2
	neg	d2
	add	#256+2,d2
	move	d2,BLT_SRC_YINC.w
	move	d2,BLT_DST_YINC.w
	move.l	bg_address,d3
	add.l	d0,d3
	move.l	d3,BLT_SRC_ADDR.w
	move.l	draw_screen_address,d3
	add.l	d0,d3
	move.l	d3,BLT_DST_ADDR.w
	move	d1,BLT_COUNT.w
	move	S_LINES(a4),BLT_COUNT+2.w
	wait_borders
	move	#$c000,BLT_CTRL.w
	mark_rect
	moveq	#-1,d0
	move.l	d0,S_RECT(a4)
.part_next_a:
	lea	SLOT_SIZE(a4),a4
	dbf	d6,.parts_a
	bra.s	.next_a2
.next_a:
	lea	4*SLOT_SIZE(a4),a4
.next_a2:
	addq.l	#ENTRY_SIZE,a1
	addq.l	#1,a0
	dbf	d7,.entries_a

	; --- B: draw.  For every entry: changed -> all its parts; else the parts whose
	; cells were touched.

	move	#2,BLT_SRC_XINC.w
	move	#2,BLT_SRC_YINC.w
	move	#8,BLT_DST_XINC.w
	move	#$0203,BLT_HOP_OP.w

	move.l	slot_base,a4
	lea	spr_entries,a1
	move.l	a1,entry_ptr
	lea	BLT_END1.w,a1
	lea	BLT_CTRL.w,a2
	lea	BLT_DST_ADDR+2.w,a3
	lea	BLT_COUNT+2.w,a5
	move	#63,entry_left
	move.l	any_base,any_ptr

entry_loop:
	move.l	entry_ptr,a6
	move.l	(a6),d2
	cmp.l	S_ENTRY(a4),d2
	bne.s	.changed
	move	4(a6),d2
	cmp	S_FLAGS(a4),d2
	bne.s	.changed
	; unchanged: the touched parts again, if any part is on the screen
	move.l	any_ptr,a0
	tst.b	(a0)
	beq.s	.none_u
	moveq	#3,d7
.parts_u:
	tst.l	S_RECT(a4)
	bmi.s	.part_next_u
	test_rect
	beq.s	.part_next_u
	move	d7,-(sp)
	bsr	draw_part
	move	(sp)+,d7
.part_next_u:
	lea	SLOT_SIZE(a4),a4
	dbf	d7,.parts_u
	bra	entry_next
.none_u:
	lea	4*SLOT_SIZE(a4),a4
	bra	entry_next

.changed:
	move.l	entry_ptr,a6
	move.l	(a6),S_ENTRY(a4)	; all four records get the entry
	move	4(a6),S_FLAGS(a4)
	move.l	(a6),SLOT_SIZE+S_ENTRY(a4)
	move	4(a6),SLOT_SIZE+S_FLAGS(a4)
	move.l	(a6),2*SLOT_SIZE+S_ENTRY(a4)
	move	4(a6),2*SLOT_SIZE+S_FLAGS(a4)
	move.l	(a6),3*SLOT_SIZE+S_ENTRY(a4)
	move	4(a6),3*SLOT_SIZE+S_FLAGS(a4)
	move.l	any_ptr,a0
	clr.b	(a0)
	moveq	#3,d7
.parts_c:
	move	d7,-(sp)
	bsr	draw_part
	move	(sp)+,d7
	tst.l	S_RECT(a4)
	bmi.s	.part_none_c
	move.l	any_ptr,a0
	st	(a0)
.part_none_c:
	lea	SLOT_SIZE(a4),a4
	dbf	d7,.parts_c

entry_next:
	addq.l	#1,any_ptr
	addq.l	#ENTRY_SIZE,entry_ptr
	subq	#1,entry_left
	bpl	entry_loop
	rts

; ------------------------------------------------------------------------------
; draw_part: a4 = the record of part 3 - d7 (0: top left ... 3: bottom right in raw
; coordinates), the entry in the record.  Draws it if it exists and is on the screen,
; and sets the record; otherwise the record gets no rectangle.
; Pointers as in the line macros; a6 is free until the lines.

draw_part:
	moveq	#3,d6
	sub	d7,d6			; part number
	move	d6,d5
	and	#1,d5			; x part
	lsr	#1,d6			; y part
	moveq	#0,d2
	move.b	S_FLAGS(a4),d2		; flags: flip x, flip y, size x, size y
	move	d2,d0
	lsr	#2,d0
	and	#1,d0			; size x
	cmp	d5,d0
	blt	.no_part		; (x part 1 only if double width)
	move	d2,d0
	lsr	#3,d0
	and	#1,d0			; size y
	cmp	d6,d0
	blt	.no_part

	; code of the part: sprite + [[0,1],[2,3]][y ^ (sizey * flipy)][x ^ (sizex * flipx)]
	move	d2,d0
	lsr	#3,d0
	and	#1,d0
	move	d2,d1
	lsr	#1,d1
	and	d0,d1			; sizey & flipy
	eor	d6,d1			; y index
	add	d1,d1
	move	d2,d0
	lsr	#2,d0
	and	#1,d0
	move	d2,d3
	and	d0,d3			; sizex & flipx
	eor	d5,d3
	add	d3,d1			; gfx offset 0..3
	moveq	#0,d0
	move.b	(a4),d0			; code
	and	#$7f,d0
	add	d1,d0
	and	#$7f,d0
	move	d2,d1
	and	#2,d1			; flip y -> bit 1
	lsr	#1,d1
	add	d0,d0
	add	d1,d0			; v = code * 2 + flip y
	move	d0,d1			; d1 = v

	; position: raw sx = x | xhigh << 8 - 40 + 16 * xpart; raw sy = (256 - y + 1 - 16 * sizey) & 255 - 32 + 16 * ypart
	moveq	#0,d3
	move.b	2(a4),d3		; x low
	move.b	S_FLAGS+1(a4),d0	; x high
	and	#3,d0
	lsl	#8,d0
	or	d0,d3
	sub	#40,d3
	lsl	#4,d5
	add	d5,d3			; raw sx = display top line (v0)
	move	#257,d0
	moveq	#0,d5
	move.b	3(a4),d5
	sub	d5,d0			; 256 - y + 1
	move	d2,d5
	lsr	#3,d5
	and	#1,d5
	lsl	#4,d5
	sub	d5,d0			; - 16 * sizey
	and	#255,d0
	sub	#32,d0
	lsl	#4,d6
	add	d6,d0			; raw sy
	neg	d0
	add	#208,d0			; u0 = 208 - sy: left display column
	cmp	#-16,d0
	ble	.no_part
	cmp	#224,d0
	bge	.no_part
	cmp	#-16,d3
	ble	.no_part
	cmp	#GAME_LINES,d3
	bge	.no_part

	; the span of lines of the shape
	lea	ga_spr_span,a6
	move	d1,d6
	add	d6,d6
	move	(a6,d6.w),d5		; first line, number of lines
	tst.b	d5
	beq	.no_part
	move	d5,d6
	and	#$ff,d6
	move	d6,S_LINES(a4)
	lsr	#8,d5
	move	d5,S_FIRST(a4)

	move	d0,d4
	asr	#4,d4			; chunk (-1 .. 13)
	and	#15,d0			; skew

	btst	#0,d2			; flip x (flags bit 0; Donkey Kong's is bit 7)
	beq.s	.top_set		; flip x: the drawn lines are at the far end
	moveq	#16,d5
	sub	S_FIRST(a4),d5
	sub	d6,d5
.top_set:
	add	d5,d3			; top display line of the rectangle

	; cells (rows from the top line on, MARK_TOP rows above display line 0)
	move	d3,d5
	add	#MARK_TOP*8,d5
	and	#$fff8,d5		; row * 8
	move	d4,d6
	add	d6,d6
	addq	#4,d6			; first cell column
	cmp	#16,d6
	blt.s	.window0
	addq	#2,d5
	sub	#16,d6
.window0:
	move	d5,S_MARK(a4)
	move.l	#$f0000000,d5
	tst	d0
	bne.s	.four_cells
	move.l	#$c0000000,d5
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

	; the rectangle in the screen
	add	#DISP_TOP,d3
	ext.l	d3
	lsl.l	#8,d3			; (a word shift wrapped the lines from 256 on: the ship at the bottom)
	ext.l	d4
	lsl.l	#3,d4
	add.l	d3,d4
	add.l	#GAME_X,d4
	move.l	d4,S_RECT(a4)
	moveq	#8,d3
	tst	d0
	bne.s	.two_chunks
	moveq	#4,d3
.two_chunks:
	move	d3,S_WORDS(a4)

	moveq	#0,d6
	move	S_LINES(a4),d6
	subq	#1,d6
	lsl.l	#8,d6			; offset of the last line
	move.l	draw_screen_address,d3
	add.l	d4,d3			; address of the top line
	cmp	#$f000,d3		; the lines would cross a 64 KB boundary
	bhs.s	.slow_lines
	move	#248,d4
	btst	#0,d2
	beq.s	.lines_set
	add.l	d6,d3
	move	#-264,d4
	bra.s	.lines_set
.slow_lines:
	bset	#31,d0
	move.l	#256,d4
	btst	#0,d2
	beq.s	.lines_set
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
	ifnd NOSPRITECODE
	tst.l	d0
	bmi.s	.generic_masks
	add.l	d6,d6			; eight-byte code/mask-stream record
	lea	ga_spr_code,a0
	move.l	(a0,d6.l),d5
	move.l	4(a0,d6.l),a0
	bra.s	.masks_set
.generic_masks:
	endc
	lsl.l	#4,d6
	move	S_FIRST(a4),d5
	lsl	#2,d5
	add	d5,d6
	lea	ga_spr_masks,a0
	add.l	d6,a0
.masks_set:

	; colour data: v * variant + quad of the colour code + first * 8
	mulu	#SPR_VARIANT,d1
	moveq	#0,d2
	move.b	1(a4),d2		; colour code
	and	#$3f,d2
	add	d2,d2
	lea	ga_spr_quad,a6
	moveq	#0,d6
	move	(a6,d2.w),d6
	add.l	d6,d1
	moveq	#0,d6
	move	S_FIRST(a4),d6
	lsl.l	#3,d6
	add.l	d6,d1
	add.l	#ga_spr_data,d1
	move.l	d1,BLT_SRC_ADDR.w
	move.l	d3,BLT_DST_ADDR.w

	ifnd NOSPRITECODE
	tst.l	d0
	bpl.s	.go			; generated code sets width/skew itself
	endc
	tst	d0
	beq.s	.skew0
	or.b	#NFSR,d0
	move.b	d0,BLT_SKEW.w
	move	#2,BLT_COUNT.w
	move	#-6,BLT_DST_YINC.w
	bra.s	.go
.skew0:
	clr.b	BLT_SKEW.w
	move	#1,BLT_COUNT.w
	move	#2,BLT_DST_YINC.w
.go:
	moveq	#4,d1
	moveq	#-64,d2

	wait_borders

	ifnd NOSPRITECODE
	tst.l	d0
	bmi.s	.generic_seq
	move.l	d5,a6
	jsr	(a6)
	bra	.blits_done
.generic_seq:
	lea	BLT_END3.w,a6
	moveq	#16,d6
	sub	S_LINES(a4),d6
	move	d6,d5
	add	d5,d5

	bra	.slow_blits
	else
	lea	BLT_END3.w,a6
	moveq	#16,d6
	sub	S_LINES(a4),d6
	move	d6,d5
	add	d5,d5

	tst.l	d0
	bmi	.slow_blits

	lsl	#3,d6
	add	d5,d6
	sprite_first_line
	jmp	.lines(pc,d6.w)
.lines:
	rept 15
	sprite_line
	endr
	bra	.blits_done

	endc

.slow_blits:
	lsl	#4,d6
	sub	d5,d6
	sprite_first_line
	jmp	.slow_seq(pc,d6.w)
.slow_seq:
	rept 15
	sprite_slow_line
	endr

.blits_done:
	mark_rect
	mark_drawn
	rts

.no_part:
	moveq	#-1,d0
	move.l	d0,S_RECT(a4)
	rts

; ------------------------------------------------------------------------------
	section bss,bss
; ------------------------------------------------------------------------------

slot_state:	ds.b	2*256*SLOT_SIZE
slot_base:	ds.l	1
entry_ptr:	ds.l	1
entry_left:	ds.w	1
slot_any:	ds.b	2*64		; per draw screen and entry: a part of it is on the screen
any_base:	ds.l	1
any_ptr:	ds.l	1
spr_entries:	ds.b	64*ENTRY_SIZE
tile_marks:	ds.b	MARK_SIZE
spr_marks:	ds.b	MARK_SIZE
	section text,code
