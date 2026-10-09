; ------------------------------------------------------------------------------
; Video and renderer of 1942
;
; The arcade screen is 224 x 256 pixels, rotated 270 degrees (tools/machine.py render_rgb): the background tilemap is 512
; pixels long along the screen's vertical axis and scrolls one line every second frame, sprites and characters are fixed
; to the screen.  The STE scrolls the background with the hardware:
;
;   * Two draw rings and a clean ring of 768 lines of 256 bytes (the Shifter's line offset, LINEWID).  Line L of
;     the ring is tilemap column (511 - L); lines 512-767 repeat 0-255, so that the window the Shifter shows, 256 lines from
;     T = (256 - scroll) & 511, never wraps (everything drawn into lines below 256 is drawn twice, the background
;     tiles in all three rings, sprites and characters in the one the window of the frame covers).
;   * The game area is 14 chunks (16 pixels, 4 words) at byte 24 of a line; the margins stay black.
;   * clean = the background only.  A draw ring = background + the sprites and characters of the frame it shows.  A frame
;     restores the old sprite rectangles of the ring (a Blitter copy from clean), puts in the tiles that changed,
;     redraws the characters (screen fixed: when the window moved every one, else the changed ones), draws the sprites
;     with the Blitter (one blit per line, the opaque mask as end masks) and the characters that sprites cover again.
;   * Colours: 16 per palette bank (docs/palettes.json); the pen masks of the graphics (assets.py) are baked into STE
;     planes once a bank is known, on first use (tile_get / sprite_get / char_get), and cached.
;
; Test harness: tools/render_test.py compares the picture of every frame with the reference renderer through the palette map.
; ------------------------------------------------------------------------------

STRIDE = 256
RING_LINES = 768
RING_GUARD = 16*STRIDE		; whole sprites above/below the display window
RING_SIZE = STRIDE*RING_LINES+2*RING_GUARD
GAME_X = 24				; byte offset of the game area in a line

Z_SCROLL = G_Z80-$37FE			; $C802: background scroll x (word)
Z_PALBANK = G_Z80-$37FB			; $C805: background palette bank
Z_SPR = G_Z80-$3400			; $CC00: 32 sprites of 4 bytes
Z_FG = G_Z80-$3000			; $D000: character codes (1024), $D400 attributes (1024)
Z_BG = G_Z80-$2800			; $D800: background: 32 columns of 16 codes, 16 attributes

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

TILE_POOL_SIZE = $60000
SPR_POOL_SIZE = $40000
CHR_POOL_SIZE = $30000

	section text,code

; ------------------------------------------------------------------------------
; Video
; ------------------------------------------------------------------------------

init_video:
	move.l	#ring_area,d0		; three rings, 256 byte aligned
	add.l	#255,d0
	clr.b	d0
	add.l	#RING_GUARD,d0
	move.l	d0,ring_base
	add.l	#RING_SIZE,d0
	move.l	d0,ring_base+4
	add.l	#RING_SIZE,d0
	move.l	d0,ring_base+8
	add.l	#RING_SIZE,d0
	move.l	d0,clean_base

	move.l	ring_base,a0		; clear guards as well as the rings
	sub.l	#RING_GUARD,a0
	move.l	#(4*RING_SIZE+47)/48-1,d0
	moveq	#0,d1
	move.l	d1,d2
	move.l	d1,d3
	move.l	d1,d4
	move.l	d1,d5
	move.l	d1,d6
	move.l	d1,d7
	move.l	d1,a1
	move.l	d1,a2
	move.l	d1,a3
	move.l	d1,a4
	move.l	d1,a5
.clear:	movem.l	d1-d7/a1-a5,(a0)
	lea	48(a0),a0
	dbf	d0,.clear

	ifd RULER				; (diagnostics: the line number of every ring line, mod 16, as a colour in the left margin)
	moveq	#2,d4
	lea	ring_base,a1
.ruler_ring:
	move.l	(a1)+,a0
	move.w	#768-1,d3
	moveq	#0,d5
.ruler_line:
	move.w	d5,d0
	and.w	#15,d0
	moveq	#0,d1
	moveq	#0,d2
	btst	#0,d0
	beq.s	.r0
	moveq	#-1,d1
.r0:	btst	#1,d0
	beq.s	.r1
	moveq	#-1,d2
.r1:	move.w	d1,(a0)
	move.w	d2,2(a0)
	moveq	#0,d1
	moveq	#0,d2
	btst	#2,d0
	beq.s	.r2
	moveq	#-1,d1
.r2:	btst	#3,d0
	beq.s	.r3
	moveq	#-1,d2
.r3:	move.w	d1,4(a0)
	move.w	d2,6(a0)
	lea	STRIDE(a0),a0
	addq.w	#1,d5
	dbf	d3,.ruler_line
	dbf	d4,.ruler_ring
	endc
	clr.b	$ffff8260.w		; low resolution
	move.b	#(STRIDE-160)/2,$ffff820f.w	; line offset in words

	move.l	ring_base,d0		; the first picture: ring 0, line 0
	move.l	d0,flip_addr
	bsr	show_address
	rts

; d0 = the address of the first line to show

show_address:
	move.l	d0,-(sp)
	move.b	1(sp),$ffff8201.w
	move.b	2(sp),$ffff8203.w
	move.b	3(sp),$ffff820d.w
	addq.l	#4,sp
	rts

init_render:
	move.w	#-1,cur_bank
	move.w	#-1,ring_T
	move.w	#-1,ring_T+2
	move.w	#-1,ring_T+4
	clr.w	draw_idx
	clr.w	shown_idx
	clr.w	prev_idx
	st	full_redraw
	clr.b	frame_ready
	bsr	flush_caches
	moveq	#0,d0
	bsr	set_bank
	; the first palette goes in at once
	movem.l	ste_pal,d0-d7
	movem.l	d0-d7,shown_pal
	clr.b	pal_pending
	rts

; The VBL: show the newest frame that is complete (render_frame leaves the finished ring's address and palette in flip_addr /
; frame_pal and its number + 1 in frame_ready; a frame that has not been shown when the next one is finished is dropped).  (Keeps every register.)

vbl_video:
	movem.l	d0-d7,-(sp)
	movem.l	black_pal,d0-d7		; (the top lines of the picture are black, Timer B switches the palette on)
	movem.l	d0-d7,$ffff8240.w
	move.w	shown_idx,prev_idx	; (the ring that was shown in the frame that ends)
	moveq	#0,d1
	move.b	frame_ready,d1		; the finished ring + 1
	beq.s	.none
	clr.b	frame_ready
	subq.w	#1,d1
	move.w	d1,shown_idx
	move.l	flip_addr,d0
	bsr	show_address
	movem.l	frame_pal,d0-d7		; (the palette of the frame that is shown from now on)
	movem.l	d0-d7,shown_pal
.none:	movem.l	(sp)+,d0-d7
	rts

; ------------------------------------------------------------------------------
; Palette bank and caches
; ------------------------------------------------------------------------------

; d0.w = bank: the colour map and the palette registers; everything baked is flushed and the whole background drawn again

set_bank:
	movem.l	d0-d3/a0-a1,-(sp)
	move.w	d0,cur_bank
	lsl.w	#8,d0
	lea	palmap,a0
	add.w	d0,a0
	lea	cmap,a1
	move.w	#256/4-1,d1
.cm:	move.l	(a0)+,(a1)+
	dbf	d1,.cm
	move.w	cur_bank,d0
	lsl.w	#5,d0
	lea	palette,a0
	add.w	d0,a0
	lea	ste_pal,a1
	moveq	#7,d1
.pl:	move.l	(a0)+,(a1)+
	dbf	d1,.pl
	st	pal_pending
	st	full_redraw
	movem.l	(sp)+,d0-d3/a0-a1
	bsr	flush_caches
	rts

flush_caches:
	movem.l	d0-d7/a0-a5,-(sp)
	lea	tile_ptr,a0
	move.l	#(65536*4+8192*4+32768*4)/32-1,d0	; (the three pointer tables follow each other)
	moveq	#0,d1
	move.l	d1,d2
	move.l	d1,d3
	move.l	d1,d4
	move.l	d1,d5
	move.l	d1,d6
	move.l	d1,d7
	move.l	d1,a1
	move.l	d1,a2
	move.l	d1,a3
	move.l	d1,a4
	move.l	d1,a5
.z:	movem.l	d1-d7/a1,(a0)
	lea	32(a0),a0
	dbf	d0,.z
	move.l	#tile_pool,tile_pool_ptr
	move.l	#spr_pool,spr_pool_ptr
	move.l	#chr_pool,chr_pool_ptr
	movem.l	(sp)+,d0-d7/a0-a5
	rts

; ------------------------------------------------------------------------------
; Baking: pen masks -> STE planes (d3-d6 = planes 0-3 of a row, d7 = the mask of one pen, or_<n> ORs it into the
; planes of the bits of the colour index n)
; ------------------------------------------------------------------------------

; d0.w = key (attr << 8 | code): a0 = the baked tile (16 rows of 4 words: the planes of the 16 pixels of a ring line)

tile_get:
	moveq	#0,d1
	move.w	d0,d1
	lsl.l	#2,d1
	lea	tile_ptr,a0
	move.l	(a0,d1.l),d1
	beq.s	bake_tile
	move.l	d1,a0
	rts

bake_tile:
	move.w	d0,-(sp)			; the key
	moveq	#0,d1
	move.b	d0,d1				; code
	move.w	d0,d2
	lsr.w	#8,d2				; attribute
	move.w	d2,d3
	and.w	#$80,d3
	add.w	d3,d3				; (attribute & $80) << 1
	add.w	d3,d1				; code, 9 bits
	move.w	d2,d3
	lsr.w	#5,d3
	and.w	#3,d3				; flips: bit 0 x, bit 1 y
	lsl.w	#2,d1
	or.w	d3,d1
	lsl.l	#8,d1				; * 256: 16 rows of 8 pen masks
	lea	tile_masks,a1
	add.l	d1,a1
	and.w	#$1F,d2
	lsl.w	#3,d2				; colour * 8
	lea	luts,a2
	add.w	d2,a2
	move.w	cur_bank,d3
	lsl.w	#4,d3
	lea	cmap,a3
	lea	bk_idx,a0
	moveq	#7,d4
.idx:	moveq	#0,d0
	move.b	(a2)+,d0
	add.w	d3,d0				; the arcade palette entry
	move.b	(a3,d0.w),d0			; the STE colour
	lsl.b	#2,d0
	move.b	d0,(a0)+
	dbf	d4,.idx
	move.l	tile_pool_ptr,a2
	move.l	a2,-(sp)
	lea	orp_tab,a3
	moveq	#15,d2
.row:	moveq	#0,d3
	moveq	#0,d4
	moveq	#0,d5
	moveq	#0,d6
	lea	bk_idx,a0
	moveq	#7,d1
.pen:	move.w	(a1)+,d7
	beq.s	.skip
	moveq	#0,d0
	move.b	(a0)+,d0
	move.l	(a3,d0.w),a4
	jsr	(a4)
	dbf	d1,.pen
	bra.s	.done
.skip:	addq.l	#1,a0
	dbf	d1,.pen
.done:	move.w	d3,(a2)+
	move.w	d4,(a2)+
	move.w	d5,(a2)+
	move.w	d6,(a2)+
	dbf	d2,.row
	move.l	a2,tile_pool_ptr
	move.l	(sp)+,a0			; the baked tile
	moveq	#0,d0
	move.w	(sp)+,d0
	lsl.l	#2,d0
	lea	tile_ptr,a1
	move.l	a0,(a1,d0.l)
	rts

; ------------------------------------------------------------------------------
; Background
; ------------------------------------------------------------------------------

; Draws the tile with the baked data a0 at column d1.w (0-31), row d2.w (1-14) into the ring a2 (clean or a draw ring):
; the ring lines 496 - 16 * column ..., twice if they are below 256.  Clobbers d0-d3, a1, a3.

put_tile:
	bsr	tile_offset
	lea	(a2,d3.l),a1
	move.l	a0,a3
	bsr.s	.put
	cmp.l	#256*STRIDE,d3
	bhs.s	.out
	move.l	a3,a0
	lea	(a2,d3.l),a1
	add.l	#512*STRIDE,a1
	bsr.s	.put
.out:	rts
.put:	rept 16
	movem.l	(a0)+,d0-d1
	movem.l	d0-d1,(a1)
	lea	STRIDE(a1),a1
	endr
	rts

; d1.w = column, d2.w = row: d3.l = the byte offset of the tile's first line in a ring.  Clobbers d0.

tile_offset:
	moveq	#0,d3
	move.w	#496,d3
	move.w	d1,d0
	lsl.w	#4,d0
	sub.w	d0,d3				; first line: 496 - 16 * column
	lsl.l	#8,d3				; * STRIDE
	move.w	d2,d0
	subq.w	#1,d0
	lsl.w	#3,d0
	ext.l	d0
	add.l	d0,d3
	add.l	#GAME_X,d3
	rts

; Copies the tile (column d1.w, row d2.w) from clean to the ring a2 (Blitter, 16 lines of 4 words, twice below line 256).

copy_tile:
	bsr.s	tile_offset
	move.l	clean_base,a0
	add.l	d3,a0
	lea	(a2,d3.l),a1
	moveq	#4,d0
	moveq	#16,d1
	move.l	d3,-(sp)
	bsr	blit_copy
	move.l	(sp)+,d3
	cmp.l	#256*STRIDE,d3
	bhs.s	.out
	move.l	clean_base,a0
	add.l	d3,a0
	add.l	#512*STRIDE,a0
	lea	(a2,d3.l),a1
	add.l	#512*STRIDE,a1
	moveq	#4,d0
	moveq	#16,d1
	bsr	blit_copy
.out:	rts

; The Blitter copies a rectangle of d0.w words per line and d1.w lines from a0 to a1 (the rings have STRIDE bytes a line).

blit_copy:
	dbgcnt	dbg_c1,0
	ifd DEBUG
	cmp.l	#$200000,a0			; (assertion: both rectangles are in the rings / clean)
	blo.s	.bad
	cmp.l	#$3F0000,a0
	bhs.s	.bad
	cmp.l	#$200000,a1
	blo.s	.bad
	cmp.l	#$3F0000,a1
	blo.s	.good
.bad:	move.l	(sp),d6				; the caller
	move.w	draw_idx,d5
	bra	z80_badpc
.good:
	endc
	stage	$044
	wait_borders
	move.w	#2,BLT_SRC_XINC.w
	move.w	#2,BLT_DST_XINC.w
	move.w	d0,d2
	add.w	d2,d2
	neg.w	d2
	add.w	#STRIDE+2,d2			; the step from the last word of a line to the first of the next
	move.w	d2,BLT_SRC_YINC.w
	move.w	d2,BLT_DST_YINC.w
	move.l	a0,BLT_SRC_ADDR.w
	move.l	a1,BLT_DST_ADDR.w
	move.w	#$ffff,BLT_END1.w
	move.w	#$ffff,BLT_END2.w
	move.w	#$ffff,BLT_END3.w
	move.w	d0,BLT_COUNT.w
	move.w	#$0203,BLT_HOP_OP.w
	clr.b	BLT_SKEW.w
	; the rows in groups of four (one look at the border timers for each; a group is about as long as the Blitter's busiest stretch
	; in the sprite routines), then the rest
	move.w	d1,d3
	lsr.w	#2,d3
	and.w	#3,d1
	subq.w	#1,d3
	bmi.s	.rest
.group:	wait_borders
	rept 4
	move.w	#1,BLT_COUNT+2.w
	move.b	#$c0,BLT_CTRL.w		; short HOG pass; addresses advance automatically
	endr
	dbf	d3,.group
.rest:	subq.w	#1,d1
	bmi.s	.done
.row:	wait_borders
	move.w	#1,BLT_COUNT+2.w
	move.b	#$c0,BLT_CTRL.w
	dbf	d1,.row
.done:	rts

	include "1942_bg.s"
	include "1942_chr.s"
	include "1942_chr2.s"
	include "1942_spr.s"
	include "1942_frame.s"
