; ------------------------------------------------------------------------------
; The renderer.  The arcade picture (288 x 224) is shown rotated 90 degrees clockwise: display x = 223 - raw y,
; display line = raw x (tools/assets.py).  Three layers, as MAME draws them:
;
;   background: a clean ring of 512 lines (the tile map's 64 tile columns x 8 lines; 224 pixels wide: its 28 visible tile
;       rows) plus a copy of its first 288 lines behind it, so that the picture is one copy of 288 lines starting at line
;       (20 + scroll) & 511.  The ring is updated where the program wrote tile RAM (vblocks, marked by the translated
;       writers; shadow copies of codes and attributes tell the cells that changed);
;   sprites: the sprite registers' 64 entries, each 1 to 4 tiles of 16 x 16, drawn first to last (the last on top);
;   foreground: the character layer over everything, cells with pixels only.
;
; First version, drawn by the CPU for exactness (sprite rows converted from the three pen bit planes and the palette's
; colours, shifted and merged into the four screen planes; the picture copied by the Blitter): the Blitter's masked
; sprite passes of AGENTS.md are not used yet.  Not drawn: the cocktail flip, a foreground scroll, a vertical
; background scroll other than 0 (the game uses none).
; ------------------------------------------------------------------------------

STRIDE = 256				; bytes per line, 512 pixel virtual screen
GAME_X = 24				; byte offset of the game area in a line (3 chunks)
GAME_LINES = 288			; the rotated arcade picture
PIC_Y0 = 32				; the buffer line of the picture's first line
CROP_TOP = 32				; the STE shows 277 of the 288 lines: from this buffer line on
SHOW_OFFSET = CROP_TOP*STRIDE
SCREEN_BYTES = $20000*3
RING_STRIDE = 112			; 224 pixels, 4 planes
RING_LINES = 512+288
RING_BYTES = RING_STRIDE*RING_LINES

; Tile RAM and sprite registers in the shared RAM block
R_BGCODE = g_ram+$4800			; $C800
R_BGATTR = g_ram+$3800			; $B800
R_FGCODE = g_ram+$4000			; $C000
R_FGATTR = g_ram+$3000			; $B000
R_SPR1 = g_ram+$0780			; $8780: y, x low
R_SPR2 = g_ram+$1780			; $9780: flags, x high
R_SPR3 = g_ram+$2780			; $A780: code, colour

init_video:
	move.l	#screens,d0
	add.l	#$10000-1,d0
	and.l	#$ffff0000,d0
	move.l	d0,bg_address
	add.l	#$20000,d0
	move.l	d0,scr_address
	add.l	#$20000,d0
	move.l	d0,scr_address+4

	move.l	bg_address,d0
	bsr	clear_screen
	move.l	scr_address,d0
	bsr	clear_screen
	move.l	scr_address+4,d0
	bsr	clear_screen

	movem.l	ga_palette,d0-d7
	movem.l	d0-d7,$ffff8240.w

	clr.b	$ffff8260.w		; low resolution, 50 Hz
	move.b	#2,$ffff820a.w
	move.b	#(512-320)/2/2,$ffff820f.w	; virtual line width 512 pixels

	move.l	scr_address+4,draw_screen_address
	move.l	scr_address,display_screen_address
	clr	draw_index
	move.l	scr_address,d0		; the screen the VBL shows first
	add.l	#SHOW_OFFSET,d0
	move.l	d0,-(sp)
	move.b	1(sp),$ffff8201.w
	move.b	2(sp),$ffff8203.w
	move.b	3(sp),$ffff820d.w
	addq.l	#4,sp
	rts

; d0 = address of a 128 KiB screen

clear_screen:
	move	#2,$ffff8a2e.w
	move	#$ffff,$ffff8a28.w
	move	#$ffff,$ffff8a2a.w
	move	#$ffff,$ffff8a2c.w
	move.b	#1,$ffff8a3a.w		; HOP 1 (halftone only)
	move.b	#0,$ffff8a3b.w		; OP 0 (destination = 0)
	clr.b	$ffff8a3d.w
	move	#2,$ffff8a30.w		; Destination Y increment
	move	#16,$ffff8a36.w		; X count: 16 words, 4096 lines = 128 KB
	move.l	d0,$ffff8a32.w
	move	#4096,$ffff8a38.w
	bra	blit_go			; (the interrupts run: in pieces)

init_render:
	st	force_all
	rts

; ------------------------------------------------------------------------------
; One frame: the ring brought up to date, the picture copied, the sprites and the foreground drawn.
; ------------------------------------------------------------------------------

render_frame:
	movem.l	d0-d7/a0-a6,-(sp)
	bsr	update_bg
	bsr	compose_bg
	bsr	draw_sprites
	bsr	draw_fg
	st	frame_ready
	movem.l	(sp)+,d0-d7/a0-a6
	rts

; ------------------------------------------------------------------------------
; The background ring.  The marks of the translated writers (vblocks: blocks of 32 bytes of $B000-$CFFF mod 256: the
; foreground codes $00-$3F, the background codes $40-$7F, the foreground attributes $80-$BF, the background attributes
; $C0-$FF) say which cells (32 a block) to compare with their shadows.
; ------------------------------------------------------------------------------

update_bg:
	lea	vblocks,a0
	lea	cell_dirty,a1
	moveq	#63,d1
	tst.b	force_all
	bne.s	.all
	tst.b	vblock_all
	bne.s	.all
	lea	vblocks+$40,a2
	lea	vblocks+$c0,a3
	moveq	#0,d0			; cell blocks: marks of the codes and the attributes
.mk:	move.b	(a2,d0.w),d2
	or.b	(a3,d0.w),d2
	move.b	d2,(a1,d0.w)
	addq.w	#1,d0
	cmp.w	#64,d0
	blo.s	.mk
	bra.s	.clear
.all:	moveq	#63,d0
.alld:	st	(a1,d0.w)
	dbf	d0,.alld
.clear:	moveq	#63,d0			; the marks are taken (the foreground's too: it is drawn from the RAM every frame)
	lea	vblocks,a0
.c1:	clr.l	(a0)+
	dbf	d0,.c1			; (256 bytes)
	clr.b	vblock_all
	clr.b	force_all

	moveq	#0,d7			; the cell block
.blk:	tst.b	(a1,d7.w)
	beq	.next
	move.w	d7,d6
	lsl.w	#5,d6			; its first cell
	moveq	#31,d5
.cell:	lea	R_BGCODE,a2
	lea	R_BGATTR,a3
	lea	shadow_bg,a4
	lea	shadow_bg+2048,a5
	move.b	(a2,d6.w),d0
	move.b	(a3,d6.w),d1
	cmp.b	(a4,d6.w),d0
	bne.s	.chg
	cmp.b	(a5,d6.w),d1
	beq.s	.same
.chg:	move.b	d0,(a4,d6.w)
	move.b	d1,(a5,d6.w)
	movem.l	d5-d7/a1,-(sp)
	move.w	d6,d2
	bsr	draw_bg_cell		; d0 = code, d1 = attribute, d2 = the cell
	movem.l	(sp)+,d5-d7/a1
.same:	addq.w	#1,d6
	dbf	d5,.cell
.next:	addq.w	#1,d7
	cmp.w	#64,d7
	blo.s	.blk
	rts

; plane P of a background row: the pens' masks (d4: pen 0, d3: pen 1, d5: pen 2, d2: pen 3) of the pens whose STE colour has
; the plane's bit (d6 bits 4 * P + pen), stored into tilebuf
selplane macro
	moveq	#0,d0
	btst	#\1*4+0,d6
	beq.s	.a\@
	or.b	d4,d0
.a\@:	btst	#\1*4+1,d6
	beq.s	.b\@
	or.b	d3,d0
.b\@:	btst	#\1*4+2,d6
	beq.s	.c\@
	or.b	d5,d0
.c\@:	btst	#\1*4+3,d6
	beq.s	.d\@
	or.b	d2,d0
.d\@:	move.b	d0,(a3)+
	endm

; One background cell into the ring (and its copy behind the ring when it lies in the first 288 lines): d0.b = code,
; d1.b = attribute, d2.w = the cell (ty * 64 + tx).  Visible tile rows ty 2-29 only (tmy = y + 16).  The cell's rows are
; converted from the two pen bit planes to the four screen planes (a 4-bit plane selection per plane: the pens whose
; STE colour has the plane's bit) into tilebuf, then stored.

draw_bg_cell:
	move.w	d2,d3
	lsr.w	#6,d3			; ty
	cmp.w	#2,d3
	blo	.r
	cmp.w	#29,d3
	bhi	.r
	moveq	#29,d4
	sub.w	d3,d4			; cx = 29 - ty: the 8 pixel column of the display
	and.w	#63,d2			; tx
	move.w	d2,a4
	moveq	#0,d3
	move.b	d1,d3
	and.w	#$3c,d3
	lsr.w	#2,d3			; (attr & $3c) >> 2
	moveq	#0,d5
	move.b	d0,d5
	and.w	#$80,d5
	lsr.w	#3,d5
	or.w	d5,d3
	moveq	#0,d5
	move.b	d1,d5
	and.w	#3,d5
	lsl.w	#5,d5
	or.w	d5,d3			; the colour 0-127
	lsl.w	#2,d3
	lea	bg_lut,a0
	lea	(a0,d3.w),a0		; the four pens' STE colours
	moveq	#0,d6			; the plane selection: bit 4 * plane + pen
	moveq	#3,d3
.pk:	moveq	#3,d5
.pp:	moveq	#0,d7
	move.b	(a0,d5.w),d7
	btst	d3,d7
	beq.s	.np
	move.w	d3,d7
	lsl.w	#2,d7
	add.w	d5,d7
	bset	d7,d6
.np:	dbf	d5,.pp
	dbf	d3,.pk
	moveq	#0,d3			; the tile's rows: tile = code + (attr & 1) * 256, flip = attr >> 6
	move.b	d0,d3
	moveq	#0,d5
	move.b	d1,d5
	and.w	#1,d5
	lsl.w	#8,d5
	add.w	d5,d3
	lsl.w	#2,d3
	moveq	#0,d5
	move.b	d1,d5
	lsr.w	#6,d5
	add.w	d5,d3
	lsl.l	#4,d3
	lea	bgt,a1
	lea	(a1,d3.l),a1
	move.w	a4,d3			; the ring address: tx * 8 lines of 112 bytes, the group cx / 2, the byte cx & 1
	mulu	#RING_STRIDE*8,d3
	move.w	d4,d5
	lsr.w	#1,d5
	lsl.w	#3,d5
	add.w	d5,d3
	and.w	#1,d4
	add.w	d4,d3
	lea	ring,a2
	lea	(a2,d3.l),a2
	lea	tilebuf,a3
	moveq	#7,d7
.row:	moveq	#0,d0
	move.b	(a1)+,d0		; pen bit 0 of the 8 pixels
	moveq	#0,d1
	move.b	(a1)+,d1		; pen bit 1
	move.b	d0,d2
	and.b	d1,d2			; pen 3
	move.b	d1,d3
	not.b	d3
	and.b	d0,d3			; pen 1
	move.b	d0,d5
	not.b	d5
	and.b	d1,d5			; pen 2
	move.b	d0,d4
	or.b	d1,d4
	not.b	d4			; pen 0
	selplane	0
	selplane	1
	selplane	2
	selplane	3
	dbf	d7,.row
	lea	tilebuf,a3
	moveq	#7,d7
.cp:	move.b	(a3)+,(a2)
	move.b	(a3)+,2(a2)
	move.b	(a3)+,4(a2)
	move.b	(a3)+,6(a2)
	lea	RING_STRIDE(a2),a2
	dbf	d7,.cp
	move.w	a4,d3
	cmp.w	#36,d3			; tx * 8 < 288: the copy behind the ring
	bhs.s	.r
	lea	tilebuf,a3
	lea	512*RING_STRIDE-8*RING_STRIDE(a2),a2
	moveq	#7,d7
.cp2:	move.b	(a3)+,(a2)
	move.b	(a3)+,2(a2)
	move.b	(a3)+,4(a2)
	move.b	(a3)+,6(a2)
	lea	RING_STRIDE(a2),a2
	dbf	d7,.cp2
.r:	rts

; ------------------------------------------------------------------------------
; The picture: 288 lines of the ring from line (20 + scroll) & 511 (the Blitter copies 56 words a line).
; ------------------------------------------------------------------------------

compose_bg:
	moveq	#0,d0
	move.w	scroll,d0
	add.w	#20,d0
	and.w	#511,d0
	mulu	#RING_STRIDE,d0
	add.l	#ring,d0
	move	#2,$ffff8a20.w		; source X increment
	move	#2,$ffff8a22.w		; Y: the lines follow each other
	move.l	d0,$ffff8a24.w
	move	#$ffff,$ffff8a28.w
	move	#$ffff,$ffff8a2a.w
	move	#$ffff,$ffff8a2c.w
	move	#2,$ffff8a2e.w
	move	#STRIDE-2*55,$ffff8a30.w	; destination Y increment
	move.l	draw_screen_address,d0
	add.l	#PIC_Y0*STRIDE+GAME_X,d0
	move.l	d0,$ffff8a32.w
	move	#56,$ffff8a36.w
	move	#GAME_LINES,$ffff8a38.w
	move.b	#2,$ffff8a3a.w		; HOP 2: the source
	move.b	#3,$ffff8a3b.w		; OP 3: a copy
	clr.b	$ffff8a3d.w
	bra	blit_go			; (HOG: the CPU waits for the copy, the sprites are drawn over it)

; ------------------------------------------------------------------------------
; One row of up to 16 pixels merged into the picture: d0.w = the opaque pixels (the leftmost the top bit), d1.w-d4.w =
; the planes' bits, d5.w = the display x of the leftmost pixel (-15 to 223), a0 = the picture line (its group 0).  Only
; the groups of the picture (0-13: 16 pixels, 8 bytes) are touched (the outer words are clipped at the picture's
; edges).  Clobbers d5-d7, a1.
; ------------------------------------------------------------------------------

blit_row:
	move.w	d5,d6
	and.w	#15,d6			; the shift
	move.w	d6,blit_s
	asr.w	#4,d5			; the group (floor)
	swap	d0
	clr.w	d0
	swap	d1
	clr.w	d1
	swap	d2
	clr.w	d2
	swap	d3
	clr.w	d3
	swap	d4
	clr.w	d4
	lsr.l	d6,d0			; the high word: the pixels of the group, the low word: those of the next
	lsr.l	d6,d1
	lsr.l	d6,d2
	lsr.l	d6,d3
	lsr.l	d6,d4
	swap	d0			; (the high words in the low ones)
	swap	d1
	swap	d2
	swap	d3
	swap	d4
	cmp.w	#13,d5
	bhi.s	.nohi
	move.w	d5,d7
	lsl.w	#3,d7
	lea	(a0,d7.w),a1
	bsr.s	.merge
.nohi:	tst.w	blit_s
	beq.s	.r
	addq.w	#1,d5
	cmp.w	#13,d5
	bhi.s	.r
	swap	d0			; the low words
	swap	d1
	swap	d2
	swap	d3
	swap	d4
	move.w	d5,d7
	lsl.w	#3,d7
	lea	(a0,d7.w),a1
.merge:	move.w	d0,d7
	not.w	d7
	move.w	(a1),d6
	and.w	d7,d6
	or.w	d1,d6
	move.w	d6,(a1)+
	move.w	(a1),d6
	and.w	d7,d6
	or.w	d2,d6
	move.w	d6,(a1)+
	move.w	(a1),d6
	and.w	d7,d6
	or.w	d3,d6
	move.w	d6,(a1)+
	move.w	(a1),d6
	and.w	d7,d6
	or.w	d4,d6
	move.w	d6,(a1)+
.r:	rts

; pen p of a sprite row: its mask from the three bit planes (d0-d2), if it is opaque, ORed into rowacc (the opaque mask,
; then the planes of its STE colour); clobbers d3-d5
pen	macro
	move.b	\1(a2),d4
	cmp.b	#255,d4
	beq	.n\@
	move.w	#$ffff,d3
	ifne \1&1
	and.w	d0,d3
	else
	move.w	d0,d5
	not.w	d5
	and.w	d5,d3
	endc
	ifne \1&2
	and.w	d1,d3
	else
	move.w	d1,d5
	not.w	d5
	and.w	d5,d3
	endc
	ifne \1&4
	and.w	d2,d3
	else
	move.w	d2,d5
	not.w	d5
	and.w	d5,d3
	endc
	or.w	d3,(a3)
	btst	#0,d4
	beq.s	.p0\@
	or.w	d3,2(a3)
.p0\@:	btst	#1,d4
	beq.s	.p1\@
	or.w	d3,4(a3)
.p1\@:	btst	#2,d4
	beq.s	.p2\@
	or.w	d3,6(a3)
.p2\@:	btst	#3,d4
	beq.s	.p3\@
	or.w	d3,8(a3)
.p3\@:
.n\@:
	endm

; ------------------------------------------------------------------------------
; The sprites: the 64 entries of the registers in order.  A sprite is one tile, two wide or high, or four (MAME's
; draw_sprites: the arrangement depends on the flips); a tile at raw (x, y) is drawn at display (208 - y, x).
; ------------------------------------------------------------------------------

draw_sprites:
	clr.w	spr_off
.next:	move.w	spr_off,d7
	lea	R_SPR3,a0
	move.b	1(a0,d7.w),d0
	btst	#6,d0
	bne	.skip
	moveq	#63,d4
	and.w	d0,d4			; the palette (colour mod 64)
	move.w	d4,spr_pal
	lea	R_SPR2,a1
	moveq	#0,d1
	move.b	(a1,d7.w),d1		; the flags
	move.w	d1,spr_flags
	moveq	#0,d0
	move.b	(a0,d7.w),d0		; the code
	btst	#7,d1
	beq.s	.low
	and.w	#$3f,d0
	add.w	#$100,d0
.low:	move.w	d0,spr_code
	move.w	d1,d6
	lsr.w	#2,d6
	and.w	#3,d6
	move.w	d6,spr_fl		; flip x (bit 0), flip y (bit 1)
	lea	R_SPR1,a2
	moveq	#0,d2
	move.b	1(a2,d7.w),d2
	sub.w	#40,d2
	btst	#0,1(a1,d7.w)
	beq.s	.xl
	add.w	#256,d2			; sx
.xl:	move.w	d2,spr_sx
	moveq	#0,d3
	move.b	(a2,d7.w),d3
	neg.w	d3
	add.w	#223,d3			; sy = 28 * 8 - y - 1
	move.w	d3,spr_sy
	btst	#1,spr_flags+1
	bne.s	.tall
	btst	#0,spr_flags+1
	bne.s	.wide
	moveq	#0,d0			; one tile
	moveq	#0,d1
	moveq	#0,d2
	bsr	put
	bra	.skip
.wide:	and.w	#$fffe,spr_code		; two wide
	moveq	#0,d0
	bsr	pos_wide0
	bsr	put
	moveq	#1,d0
	bsr	pos_wide1
	bsr	put
	bra	.skip
.tall:	btst	#0,spr_flags+1
	beq.s	.t2
	and.w	#$fffc,spr_code		; four tiles
	moveq	#3,d0
	bsr	pos_wide1
	bsr	put
	moveq	#1,d0
	bsr	pos_f1
	bsr	put
	and.w	#$fffd,spr_code
	moveq	#2,d0
	bsr	pos_wide0
	bsr	put
	moveq	#0,d0
	bsr	pos_t0
	bsr	put
	bra.s	.skip
.t2:	and.w	#$fffd,spr_code		; two high
	moveq	#2,d0
	bsr	pos_wide0
	bsr	put
	moveq	#0,d0
	bsr	pos_t0
	bsr	put
.skip:	addq.w	#2,spr_off
	cmp.w	#$80,spr_off
	blo	.next
	rts

; the tile offsets (d1 = dx, d2 = dy from the sprite's sx, sy) by MAME's draw_sprites; d0 = the code offset is kept
pos_wide0:				; flipx ? sx + 16 : sx, flipy ? sy - 16 : sy
	moveq	#0,d1
	moveq	#0,d2
	btst	#0,spr_fl+1
	beq.s	.a
	moveq	#16,d1
.a:	btst	#1,spr_fl+1
	beq.s	.b
	moveq	#-16,d2
.b:	rts
pos_wide1:				; flipx ? sx : sx + 16, flipy ? sy - 16 : sy
	moveq	#16,d1
	moveq	#0,d2
	btst	#0,spr_fl+1
	beq.s	.a
	moveq	#0,d1
.a:	btst	#1,spr_fl+1
	beq.s	.b
	moveq	#-16,d2
.b:	rts
pos_f1:				; flipx ? sx : sx + 16, flipy ? sy : sy - 16
	moveq	#16,d1
	moveq	#-16,d2
	btst	#0,spr_fl+1
	beq.s	.a
	moveq	#0,d1
.a:	btst	#1,spr_fl+1
	beq.s	.b
	moveq	#0,d2
.b:	rts
pos_t0:				; flipx ? sx + 16 : sx, flipy ? sy : sy - 16
	moveq	#0,d1
	moveq	#-16,d2
	btst	#0,spr_fl+1
	beq.s	.a
	moveq	#16,d1
.a:	btst	#1,spr_fl+1
	beq.s	.b
	moveq	#0,d2
.b:	rts

; one tile: code spr_code + d0, at (sx + d1, sy + d2)
put:
	move.w	spr_code,d3
	add.w	d0,d3
	move.w	spr_sx,d4
	add.w	d1,d4
	move.w	spr_sy,d5
	add.w	d2,d5
	move.w	d3,d0
	move.w	d4,d2
	move.w	d5,d3
	; (falls through)

; d0.w = the tile code (0-319), d2.w = raw x, d3.w = raw y; the flips spr_fl, the palette spr_pal
tile_draw:
	move.w	#208,d4
	sub.w	d3,d4			; the display x of its leftmost pixel
	move.w	d4,t_x
	move.w	d2,t_y			; the display line of its first row
	cmp.w	#223,d4
	bgt	.r
	cmp.w	#-15,d4
	blt	.r
	cmp.w	#287,d2
	bgt	.r
	cmp.w	#-15,d2
	blt	.r
	move.w	d0,d5
	lsl.w	#2,d5
	add.w	spr_fl,d5
	mulu	#96,d5
	lea	spt,a4
	lea	(a4,d5.l),a4		; the tile's rows: 3 words each
	move.w	spr_pal,d5
	lsl.w	#3,d5
	lea	spr_lut,a2
	lea	(a2,d5.w),a2		; the 8 pens' STE colours (255: transparent)
	move.l	draw_screen_address,a0
	lea	PIC_Y0*STRIDE+GAME_X(a0),a0
	move.w	d2,d5
	ext.l	d5
	lsl.l	#8,d5
	lea	(a0,d5.l),a0		; the line of the first row (it may lie above the picture)
	move.w	#15,t_row
.row:	move.w	(a4)+,d0
	move.w	(a4)+,d1
	move.w	(a4)+,d2
	move.w	t_y,d5
	bmi	.nextrow
	cmp.w	#287,d5
	bhi	.nextrow
	lea	rowacc,a3
	clr.l	(a3)
	clr.l	4(a3)
	clr.w	8(a3)
	pen	0
	pen	1
	pen	2
	pen	3
	pen	4
	pen	5
	pen	6
	pen	7
	lea	rowacc,a3
	move.w	(a3),d5
	beq	.nextrow		; (nothing opaque)
	move.w	2(a3),d1
	move.w	4(a3),d2
	move.w	6(a3),d3
	move.w	8(a3),d4
	move.w	d5,d0
	move.w	t_x,d5
	bsr	blit_row
.nextrow:
	lea	STRIDE(a0),a0
	addq.w	#1,t_y
	subq.w	#1,t_row
	bpl	.row
.r:	rts

; ------------------------------------------------------------------------------
; The foreground: the characters of the cells that have pixels (tx 4-39, ty 2-30 show), over everything.  A cell
; starts at display line 8 * tx - 32 and display x 234 - 8 * ty (a glyph's rows are display lines, its bits run left to
; right).  Clobbers everything.
; ------------------------------------------------------------------------------

draw_fg:
	move.w	#2,fg_ty
.ty:	move.w	#4,fg_tx
.tx:	move.w	fg_ty,d0
	lsl.w	#6,d0
	add.w	fg_tx,d0
	lea	R_FGCODE,a1
	moveq	#0,d1
	move.b	(a1,d0.w),d1
	lea	fg_any,a2
	tst.b	(a2,d1.w)
	beq	.nocell
	lea	R_FGATTR,a1
	moveq	#0,d2
	move.b	(a1,d0.w),d2		; the attribute
	move.w	d2,d3
	and.w	#3,d3
	lsl.w	#4,d3
	move.w	d2,d4
	and.w	#$3c,d4
	lsr.w	#2,d4
	or.w	d4,d3			; the colour 0-63
	lea	fg_lut,a2
	moveq	#0,d4
	move.b	(a2,d3.w),d4
	move.w	d4,fg_ste
	lsr.w	#6,d2
	and.w	#3,d2			; the flips
	lsl.w	#2,d1
	add.w	d2,d1
	lsl.w	#3,d1			; * 8 rows
	lea	fgt,a4
	lea	(a4,d1.w),a4
	move.w	fg_tx,d0
	lsl.w	#3,d0
	sub.w	#32,d0
	move.w	d0,t_y			; the first line
	move.w	fg_ty,d0
	lsl.w	#3,d0
	neg.w	d0
	add.w	#234,d0
	move.w	d0,t_x			; the leftmost pixel's x
	cmp.w	#224,d0			; (a cell outside)
	bge	.nocell
	cmp.w	#-8,d0
	ble	.nocell
	move.l	draw_screen_address,a0
	lea	PIC_Y0*STRIDE+GAME_X(a0),a0
	move.w	t_y,d5
	ext.l	d5
	lsl.l	#8,d5
	lea	(a0,d5.l),a0
	move.w	#7,t_row
.row:	moveq	#0,d0
	move.b	(a4)+,d0
	move.w	t_y,d5
	bmi.s	.nextrow
	cmp.w	#287,d5
	bhi.s	.nextrow
	tst.b	d0
	beq.s	.nextrow
	lsl.w	#8,d0			; the glyph's 8 pixels at the top of the word
	move.w	fg_ste,d5
	moveq	#0,d1
	moveq	#0,d2
	moveq	#0,d3
	moveq	#0,d4
	btst	#0,d5
	beq.s	.f0
	move.w	d0,d1
.f0:	btst	#1,d5
	beq.s	.f1
	move.w	d0,d2
.f1:	btst	#2,d5
	beq.s	.f2
	move.w	d0,d3
.f2:	btst	#3,d5
	beq.s	.f3
	move.w	d0,d4
.f3:	move.w	t_x,d5
	bsr	blit_row
.nextrow:
	lea	STRIDE(a0),a0
	addq.w	#1,t_y
	subq.w	#1,t_row
	bpl	.row
.nocell:
	addq.w	#1,fg_tx
	cmp.w	#40,fg_tx
	blo	.tx
	addq.w	#1,fg_ty
	cmp.w	#31,fg_ty
	blo	.ty
	rts

; ------------------------------------------------------------------------------
	section bss,bss
	even
tilebuf:	ds.b	32
blit_s:		ds.w	1
rowacc:		ds.w	5
spr_pal:	ds.w	1
spr_fl:		ds.w	1
spr_sx:		ds.w	1
spr_sy:		ds.w	1
spr_code:	ds.w	1
spr_flags:	ds.w	1
spr_off:	ds.w	1
t_x:		ds.w	1
t_y:		ds.w	1
t_row:		ds.w	1
fg_tx:		ds.w	1
fg_ty:		ds.w	1
fg_ste:		ds.w	1
cell_dirty:	ds.b	64
force_all:	ds.b	1
	even
shadow_bg:	ds.b	4096		; the codes, then the attributes, of the background cells as drawn into the ring
	cnop	0,4
ring:		ds.b	RING_BYTES
	section text,code

	borders_handlers
	borders_blit_go
	borders_report
