; ------------------------------------------------------------------------------
; The renderer.
;
; The arcade draws a list of "objects" (oram $DD00-$DFFF, 4 bytes each: y, tile page, x, flags);
; an object is a strip of 8 x 8 tiles whose shape comes from a PROM (up to 32 rows of 2 tiles,
; columns chained across objects), the tile numbers and colour banks are in the video RAM
; ($C000-$DCFF, 2 bytes per tile).  Objects are drawn in list order, pen 15 is transparent, the
; background is palette entry 255.  See bublbobl.py render_raw.
;
; The STE shows 16 colours: the 15 most used colours of the banks in use are kept (index 0 =
; the background), everything else maps to the nearest of them (rf_palette).  A tile is baked
; per (code, bank, flips) into planar rows (data + inverted mask) and cached (tcache); an aligned
; tile is one movep.l per row, an unaligned one is shifted into two cells.
;
; The game area is 256 x 224 at screen pixel 32, game row y is buffer line y + YPAD; the
; buffer has room for the whole 256 rows and the tiles that hang over.
; ------------------------------------------------------------------------------

YPAD = 10
BUF_LINES = 280
SCREEN_SIZE = STRIDE*BUF_LINES
CROP_TOP = 0

G_VRAM = g_ram+$4000			; $C000
G_ORAM = g_ram+$5D00			; $DD00
G_PAL = g_ram+$7800			; $F800

TC_SIZE = 4096				; tile cache slots
TC_ENTRY = 72				; key.l, opaque.l, 8 rows of (data.l, inverted mask.l)

init_render:
	lea	tcache,a0
	move.l	#TC_SIZE-1,d0
.t:	move.l	#-1,(a0)
	lea	TC_ENTRY(a0),a0
	dbf	d0,.t
	; the shadow of the palette RAM differs from it: the first frame builds the mapping
	lea	pal_shadow,a0
	moveq	#127,d0
.p:	move.l	#-1,(a0)+
	dbf	d0,.p
	rts

; ------------------------------------------------------------------------------
; The frame (full redraw)
; ------------------------------------------------------------------------------

render_frame:
	move.l	draw_screen_address,rf_screen
	bsr	rf_palette
	bsr	rf_clear
	bsr	rf_draw_all
	bsr	rf_cleanup
	rts

; clear the game rows 16-239 of the draw screen

rf_clear:
	move.l	rf_screen,a0
	lea	(YPAD+16)*STRIDE(a0),a0
	move.l	#224-1,d0
	moveq	#0,d1
	move.l	d1,d2
	move.l	d1,d3
	move.l	d1,d4
	move.l	d1,d5
	move.l	d1,d6
	move.l	d1,d7
	sub.l	a2,a2
.l:
	rept 5
	movem.l	d1-d7/a2,(a0)		; 32 bytes
	lea	32(a0),a0
	endr
	dbf	d0,.l
	rts

; the tiles that hang over the game area are drawn into the black bands around it: erase them

rf_cleanup:
	move.l	rf_screen,a1
	moveq	#0,d1
	move.l	d1,d2
	move.l	d1,d3
	move.l	d1,d4
	lea	(YPAD+9)*STRIDE(a1),a0		; rows 9-15
	moveq	#7-1,d0
.t:
	rept 10
	movem.l	d1-d4,(a0)
	lea	16(a0),a0
	endr
	dbf	d0,.t
	lea	(YPAD+240)*STRIDE(a1),a0	; rows 240-246
	moveq	#7-1,d0
.b:
	rept 10
	movem.l	d1-d4,(a0)
	lea	16(a0),a0
	endr
	dbf	d0,.b
	; the margins: the tiles at x < 0 and x > 248 hang into the groups next to the game area
	lea	(YPAD+16)*STRIDE+8(a1),a0
	lea	(YPAD+16)*STRIDE+144(a1),a2
	move.w	#224-1,d0
.m:	move.l	d1,(a0)
	move.l	d1,4(a0)
	move.l	d1,(a2)
	move.l	d1,4(a2)
	lea	STRIDE(a0),a0
	lea	STRIDE(a2),a2
	dbf	d0,.m
	rts

; ------------------------------------------------------------------------------
; The object list, as the reference renders it.
; ------------------------------------------------------------------------------

rf_draw_all:
	lea	G_ORAM,a4
	moveq	#0,d7			; the chained x (a word)
	move.w	#192-1,d6
.object:
	tst.l	(a4)
	beq.s	.next
	movem.l	d6-d7/a4,-(sp)
	bsr	obj_slots		; slotbuf, d0 = count, d7 = the x at the end
	move.w	d7,rf_sxend
	move.l	8(sp),a4
	moveq	#0,d3
	move.b	3(a4),d3		; attr: the tile number's high bits
	and.w	#$0F,d3
	moveq	#10,d1
	lsl.w	d1,d3
	move.w	d3,rf_attrhi
	lea	slotbuf,a5
	subq.w	#1,d0
	bmi.s	.done
.slot:
	move.w	d0,-(sp)
	move.w	(a5)+,d0
	move.w	(a5)+,d1
	move.w	(a5)+,d2
	move.w	rf_attrhi,d3
	move.l	a5,-(sp)
	bsr	draw_tile
	move.l	(sp)+,a5
	move.w	(sp)+,d0
	dbf	d0,.slot
.done:
	movem.l	(sp)+,d6-d7/a4
	move.w	rf_sxend,d7
	add.w	#16,d7
.next:
	addq.l	#4,a4
	dbf	d6,.object
	rts

; a4 = the object (4 bytes), d7.w = the x entering: slotbuf = (x.w, y.w, vram offset.w) per tile,
; d0.w = the count, d7.w = the x after the object's last row

obj_slots:
	lea	slotbuf,a5
	moveq	#0,d1
	move.b	1(a4),d1		; the shape / page number
	move.w	d1,d2
	and.w	#$E0,d2
	lsr.w	#1,d2
	lea	bb_prom,a3
	add.w	d2,a3			; the 16 PROM entries of the shape
	move.w	d1,d2
	and.w	#$1F,d2
	lsl.w	#7,d2			; the page
	move.w	d1,d3
	and.w	#$A0,d3
	cmp.w	#$A0,d3
	bne.s	.n1
	or.w	#$1000,d2
.n1:
	moveq	#0,d3
	move.b	3(a4),d3		; attr
	moveq	#0,d4
	move.b	2(a4),d4		; the x
	btst	#6,d3
	beq.s	.n2
	sub.w	#256,d4
.n2:
	moveq	#0,d5
	move.b	(a4),d5
	neg.w	d5
	and.w	#$FF,d5			; sy
	moveq	#0,d0			; count
	moveq	#0,d6			; yc
.row:
	move.w	d6,d1
	lsr.w	#1,d1
	moveq	#0,d3
	move.b	(a3,d1.w),d3
	btst	#3,d3
	bne.s	.skip
	btst	#2,d3
	bne.s	.keep
	move.w	d4,d7			; a new column
.keep:
	move.w	d3,d1
	and.w	#3,d1
	lsl.w	#4,d1
	add.w	d2,d1
	move.w	d6,d3
	and.w	#7,d3
	add.w	d3,d3
	add.w	d3,d1			; the vram offset of the left tile
	move.w	d6,d3
	lsl.w	#3,d3
	add.w	d5,d3
	and.w	#$FF,d3			; y
	move.w	d7,(a5)+
	move.w	d3,(a5)+
	move.w	d1,(a5)+
	addq.w	#8,d7
	add.w	#$40,d1
	move.w	d7,(a5)+
	move.w	d3,(a5)+
	move.w	d1,(a5)+
	subq.w	#8,d7
	addq.w	#2,d0
.skip:
	addq.w	#1,d6
	cmp.w	#32,d6
	blo.s	.row
	rts

; ------------------------------------------------------------------------------
; One tile.  d0.w = x (signed), d1.w = y (0-255), d2.w = the vram offset, d3.w = the tile number's
; high bits (attr & 15) << 10.  Draws into rf_screen.  Keeps nothing but a5-a6 / sp.
; ------------------------------------------------------------------------------

draw_tile:
	cmp.w	#-7,d0
	blt	.out
	cmp.w	#255,d0
	bgt	.out
	cmp.w	#9,d1
	blt	.out
	cmp.w	#239,d1
	bgt	.out
	lea	G_VRAM,a0
	moveq	#0,d4
	moveq	#0,d5
	move.b	(a0,d2.w),d4
	move.b	1(a0,d2.w),d5
	move.w	d5,d6
	and.w	#3,d6
	lsl.w	#8,d6
	or.w	d6,d4
	or.w	d3,d4			; the tile number (14 bits)
	lea	bb_blank,a0		; blank tiles are not drawn
	move.w	d4,d6
	lsr.w	#3,d6
	move.b	(a0,d6.w),d7
	move.w	d4,d6
	and.w	#7,d6
	btst	d6,d7
	bne	.out
	moveq	#0,d6
	move.b	d5,d6
	lsr.b	#2,d6
	and.l	#15,d6			; the bank
	moveq	#14,d7
	lsl.l	d7,d6
	or.l	d6,d4
	moveq	#0,d6
	move.b	d5,d6
	lsr.b	#6,d6			; flips: bit 0 = x, bit 1 = y
	moveq	#18,d7
	lsl.l	d7,d6
	or.l	d6,d4			; the key
	movem.l	d0-d1,-(sp)
	bsr	get_tile		; a0 = the cache entry
	movem.l	(sp)+,d0-d1

	; the screen address of the tile's first row
	move.w	d1,d5
	add.w	#YPAD,d5
	mulu	#STRIDE,d5
	move.l	rf_screen,a3
	add.l	d5,a3
	move.w	d0,d6
	and.w	#7,d6			; the shift
	beq	.aligned
	; unaligned: the left cell cx0 = x >> 3 (arithmetic), the right cell the next
	move.w	d0,d5
	asr.w	#3,d5			; cx0
	move.w	d5,d4
	asr.w	#1,d4
	lsl.w	#3,d4
	add.w	#16,d4
	btst	#0,d5
	beq.s	.left_even
	addq.w	#1,d4
	lea	(a3,d4.w),a3		; the left cell's byte
	lea	7(a3),a4		; the right cell: the next group's first byte
	bra.s	.u_go
.left_even:
	lea	(a3,d4.w),a3
	lea	1(a3),a4
.u_go:
	lea	mh_table,a2
	move.w	d6,d4
	lsl.w	#2,d4
	move.l	(a2,d4.w),d2		; MH: the high s bits of each byte
	move.l	d2,d3
	not.l	d3			; ~MH
	moveq	#8,d4
	sub.w	d6,d4			; the left shift of the right cell's part: 8 - s
	lea	8(a0),a1
	moveq	#8-1,d1
.lrow:					; the left cell: (x >> s), the high s bits transparent
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
.rrow:					; the right cell: (x << (8 - s)), the low 8 - s bits transparent
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
.out:
	rts

.aligned:				; x is a multiple of 8, not below 0
	move.w	d0,d5
	lsr.w	#4,d5
	lsl.w	#3,d5
	add.w	#16,d5
	btst	#3,d0
	beq.s	.a_even
	addq.w	#1,d5
.a_even:
	lea	(a3,d5.w),a3
	lea	8(a0),a1
	moveq	#8-1,d1
	tst.l	4(a0)
	bne.s	.opaque
.arow:
	move.l	(a1)+,d0
	move.l	(a1)+,d5
	movep.l	0(a3),d7
	and.l	d5,d7
	or.l	d0,d7
	movep.l	d7,0(a3)
	lea	STRIDE(a3),a3
	dbf	d1,.arow
	rts
.opaque:
	move.l	(a1)+,d0
	addq.l	#4,a1
	movep.l	d0,0(a3)
	lea	STRIDE(a3),a3
	dbf	d1,.opaque
	rts

; ------------------------------------------------------------------------------
; The tile cache.  d4 = the key (tile number | bank << 14 | flip x << 18 | flip y << 19)
; -> a0 = the baked entry.  Clobbers d2-d7, a1-a3, a5, a6.
; ------------------------------------------------------------------------------

get_tile:
	move.l	d4,d5
	lsr.l	#7,d5
	eor.l	d4,d5
	move.l	d4,d6
	moveq	#13,d7
	lsr.l	d7,d6
	eor.l	d6,d5
	and.l	#TC_SIZE-1,d5
	move.l	d5,d6
	lsl.l	#3,d6
	lsl.l	#6,d5
	add.l	d6,d5			; * 72
	lea	tcache,a0
	add.l	d5,a0
	cmp.l	(a0),d4
	beq.s	.hit
	move.l	a0,-(sp)		; (the bake walks a0 through the entry)
	bsr	tc_bake
	move.l	(sp)+,a0
.hit:
	rts

; one pixel pair byte of a row: \1 = the source byte, \2 = the shift; accumulates the data in d1 and
; the transparency pairs in d4 (the tables of the tile's bank: a3 = data longs, a2 = mask bytes)

bake_px	macro
	moveq	#0,d2
	move.b	\1(a1),d2
	ifd FLIPX
	move.b	(a6,d2.w),d2		; swap the two pixels
	endc
	move.b	(a2,d2.w),d5
	lsl.w	#2,d2
	move.l	(a3,d2.w),d6
	ifne \2
	lsl.l	#\2,d6
	lsl.b	#\2,d5
	endc
	or.l	d6,d1
	or.b	d5,d4
	endm

bake_finish	macro			; d1 = the data, d4.b = the transparency pairs
	moveq	#0,d5
	move.b	d4,d5
	move.w	d5,d6
	lsl.w	#8,d6
	or.w	d6,d5
	move.w	d5,d6
	swap	d5
	move.w	d6,d5			; the byte in all four bytes: transparent in every plane
	move.l	d1,(a0)+
	move.l	d5,(a0)+
	or.l	d5,d7
	lea	(a1,d3.w),a1
	endm

tc_bake:
	move.l	d4,(a0)+		; the key
	move.l	a0,a5			; the opaque flag's cell
	addq.l	#4,a0
	move.l	d4,d0
	and.l	#$3FFF,d0		; the tile number
	move.l	d4,d1
	moveq	#14,d2
	lsr.l	d2,d1
	and.l	#15,d1			; the bank
	lsl.l	#5,d0
	lea	bb_tiles,a1
	add.l	d0,a1			; the source tile: 8 rows of 4 bytes
	lsl.l	#8,d1			; bank * 256
	lea	mtab,a2
	add.l	d1,a2
	lsl.l	#2,d1
	lea	dtab,a3
	add.l	d1,a3
	lea	swapnib,a6
	moveq	#4,d3			; the source row step
	btst	#19,d4			; flip y: from the last row up
	beq.s	.nfy
	lea	28(a1),a1
	moveq	#-4,d3
.nfy:
	moveq	#0,d7			; the OR of the inverted masks
	moveq	#8-1,d0
	btst	#18,d4
	bne	.flipx
.rows:
	moveq	#0,d1
	moveq	#0,d4
	bake_px	0,6
	bake_px	1,4
	bake_px	2,2
	bake_px	3,0
	bake_finish
	dbf	d0,.rows
	bra	.done
.flipx:
FLIPX = 1
.frows:
	moveq	#0,d1
	moveq	#0,d4
	bake_px	3,6
	bake_px	2,4
	bake_px	1,2
	bake_px	0,0
	bake_finish
	dbf	d0,.frows
.done:
	moveq	#0,d1
	tst.l	d7
	bne.s	.setflag
	moveq	#1,d1			; no transparent pixel: the fast path
.setflag:
	move.l	d1,(a5)
	rts

; ------------------------------------------------------------------------------
; The palette: when the palette RAM changed, the 15 most used colours of the banks in use
; are kept; every (bank, pen) maps to the nearest of them.  The tile cache and the bake tables
; are rebuilt, everything gets redrawn.
; ------------------------------------------------------------------------------

rf_palette:
	lea	G_PAL,a0
	lea	pal_shadow,a1
	moveq	#128-1,d0
.cmp:	cmpm.l	(a0)+,(a1)+
	bne.s	.changed
	dbf	d0,.cmp
	rts
.changed:
	lea	G_PAL,a0
	lea	pal_shadow,a1
	moveq	#128-1,d0
.cp:	move.l	(a0)+,(a1)+
	dbf	d0,.cp

	; the tile entries per bank
	lea	bank_cnt,a2
	moveq	#16-1,d0
.z:	clr.w	(a2)+
	dbf	d0,.z
	lea	bank_cnt,a2
	lea	G_VRAM,a0
	move.w	#3712-1,d0
.cnt:
	move.w	(a0)+,d1
	beq.s	.cn
	lsr.w	#2,d1
	and.w	#15,d1			; (the second byte of the entry holds the bank in bits 2-5)
	add.w	d1,d1
	addq.w	#1,(a2,d1.w)
.cn:	dbf	d0,.cnt

	; the colours of the banks in use: ctab = (rgb, weight); entry 0 the background (palette 255)
	lea	ctab,a3
	moveq	#15,d6
	moveq	#15,d4
	bsr	get_rgb
	move.w	d1,(a3)
	move.w	#$FFFF,2(a3)
	moveq	#1,d7
	moveq	#0,d6			; bank
.bank:
	move.w	d6,d0
	add.w	d0,d0
	lea	bank_cnt,a2
	move.w	(a2,d0.w),d5
	beq.s	.nextbank
	moveq	#0,d4			; pen 0-14
.pen:
	bsr	get_rgb
	lea	ctab,a1
	move.w	d7,d3
	subq.w	#1,d3
.search:
	cmp.w	(a1),d1
	beq.s	.found
	addq.l	#4,a1
	dbf	d3,.search
	move.w	d1,(a1)+		; a new colour
	move.w	d5,(a1)
	addq.w	#1,d7
	bra.s	.pnext
.found:
	add.w	d5,2(a1)
.pnext:
	addq.w	#1,d4
	cmp.w	#15,d4
	blo.s	.pen
.nextbank:
	addq.w	#1,d6
	cmp.w	#16,d6
	blo.s	.bank

	; the 15 heaviest colours (besides the background) are kept
	lea	kept,a4
	lea	ctab,a1
	move.w	(a1),(a4)+
	moveq	#1,d6
.pick:
	moveq	#0,d3			; the best weight
	moveq	#0,d2			; its index
	lea	ctab+4,a1
	moveq	#1,d4
.find:
	cmp.w	d7,d4
	bhs.s	.fdone
	move.w	2(a1),d0
	cmp.w	d3,d0
	bls.s	.fnext
	move.w	d0,d3
	move.w	d4,d2
.fnext:
	addq.l	#4,a1
	addq.w	#1,d4
	bra.s	.find
.fdone:
	tst.w	d2
	beq.s	.none
	lsl.w	#2,d2
	lea	ctab,a1
	move.w	(a1,d2.w),(a4)+
	clr.w	2(a1,d2.w)
	bra.s	.picked
.none:
	clr.w	(a4)+
.picked:
	addq.w	#1,d6
	cmp.w	#16,d6
	blo.s	.pick

	; every (bank, pen) -> the nearest kept colour
	lea	ttab,a5
	moveq	#0,d6
.mbank:
	moveq	#0,d4
.mpen:
	bsr	get_rgb			; d1 = the pen's colour
	move.w	d1,rf_rgb
	move.l	#$7FFFFFFF,d3
	moveq	#0,d7
	lea	kept,a1
	moveq	#0,d5
.near:
	move.w	(a1)+,d1
	move.w	rf_rgb,d0
	bsr	rgb_dist		; d0 = the distance
	cmp.l	d3,d0
	bhs.s	.nn
	move.l	d0,d3
	move.w	d5,d7
.nn:
	addq.w	#1,d5
	cmp.w	#16,d5
	blo.s	.near
	move.b	d7,(a5)+
	addq.w	#1,d4
	cmp.w	#15,d4
	blo.s	.mpen
	clr.b	(a5)+			; pen 15: transparent
	addq.w	#1,d6
	cmp.w	#16,d6
	blo.s	.mbank

	; the STE palette
	lea	kept,a1
	lea	ste_pal,a2
	lea	ste_nib,a3
	moveq	#16-1,d6
.ste:
	move.w	(a1)+,d1
	move.w	d1,d2
	lsr.w	#8,d2
	and.w	#15,d2
	moveq	#0,d0
	move.b	(a3,d2.w),d0
	lsl.w	#8,d0			; red
	move.w	d1,d2
	lsr.w	#4,d2
	and.w	#15,d2
	moveq	#0,d3
	move.b	(a3,d2.w),d3
	lsl.w	#4,d3			; green
	or.w	d3,d0
	move.w	d1,d2
	and.w	#15,d2
	moveq	#0,d3
	move.b	(a3,d2.w),d3		; blue
	or.w	d3,d0
	move.w	d0,(a2)+
	dbf	d6,.ste
	st	pal_pending

	; the bake tables of every bank: data = (S[hi] << 1) | S[lo], transparency pairs
	lea	ttab,a0
	lea	dtab,a1
	lea	mtab,a2
	lea	spread,a3
	moveq	#0,d6			; bank
.tbank:
	moveq	#0,d5			; v = the pixel pair
.tv:
	move.w	d5,d1
	lsr.w	#4,d1			; the high pixel's pen
	move.w	d5,d2
	and.w	#15,d2			; the low pixel's
	moveq	#0,d4			; transparency pairs
	moveq	#0,d3
	cmp.w	#15,d1
	bne.s	.h
	or.b	#2,d4
	bra.s	.hdone
.h:
	move.w	d6,d0
	lsl.w	#4,d0
	add.w	d1,d0
	move.b	(a0,d0.w),d3		; its STE index
.hdone:
	moveq	#0,d7
	cmp.w	#15,d2
	bne.s	.l
	or.b	#1,d4
	bra.s	.ldone
.l:
	move.w	d6,d0
	lsl.w	#4,d0
	add.w	d2,d0
	move.b	(a0,d0.w),d7
.ldone:
	lsl.w	#2,d3
	move.l	(a3,d3.w),d0
	add.l	d0,d0			; the high pixel's bits: the bit above the low pixel's
	lsl.w	#2,d7
	or.l	(a3,d7.w),d0
	move.w	d6,d1
	lsl.w	#8,d1
	add.w	d5,d1
	move.b	d4,(a2,d1.w)
	lsl.w	#2,d1
	move.l	d0,(a1,d1.w)
	addq.w	#1,d5
	cmp.w	#256,d5
	blo.s	.tv
	addq.w	#1,d6
	cmp.w	#16,d6
	blo.s	.tbank

	; the baked tiles are stale
	lea	tcache,a0
	move.l	#TC_SIZE-1,d0
.flush:
	move.l	#-1,(a0)
	lea	TC_ENTRY(a0),a0
	dbf	d0,.flush
	rts

; d6 = bank, d4 = pen -> d1 = the colour (r << 8 | g << 4 | b); clobbers d0, d2, a0

get_rgb:
	move.w	d6,d0
	lsl.w	#4,d0
	add.w	d4,d0
	add.w	d0,d0
	lea	G_PAL,a0
	moveq	#0,d1
	move.b	(a0,d0.w),d1
	lsl.w	#4,d1
	moveq	#0,d2
	move.b	1(a0,d0.w),d2
	lsr.b	#4,d2
	or.w	d2,d1
	rts

; d0, d1 = two colours -> d0 = the squared distance; keeps everything else

rgb_dist:
	movem.l	d2-d4,-(sp)
	moveq	#0,d4
	move.w	d0,d2
	move.w	d1,d3
	lsr.w	#8,d2
	lsr.w	#8,d3
	sub.w	d3,d2
	muls	d2,d2
	add.l	d2,d4
	move.w	d0,d2
	move.w	d1,d3
	lsr.w	#4,d2
	lsr.w	#4,d3
	and.w	#15,d2
	and.w	#15,d3
	sub.w	d3,d2
	muls	d2,d2
	add.l	d2,d4
	move.w	d0,d2
	move.w	d1,d3
	and.w	#15,d2
	and.w	#15,d3
	sub.w	d3,d2
	muls	d2,d2
	add.l	d2,d4
	move.l	d4,d0
	movem.l	(sp)+,d2-d4
	rts

	section data,data
bb_prom:	incbin "bb_prom.bin"
bb_blank:	incbin "bb_blank.bin"
	cnop	0,4
bb_tiles:	incbin "bb_tiles.bin"
	include "bb_tables.s"
	even
	section bss,bss
tcache:		ds.b	TC_SIZE*TC_ENTRY
pal_shadow:	ds.b	512
slotbuf:	ds.b	64*6
ctab:		ds.b	1024
kept:		ds.w	16
ttab:		ds.b	256
dtab:		ds.l	16*256
mtab:		ds.b	16*256
bank_cnt:	ds.w	16
ste_pal:	ds.w	16
pal_pending:	ds.b	1
	even
rf_screen:	ds.l	1
rf_rgb:		ds.w	1
rf_sxend:	ds.w	1
rf_attrhi:	ds.w	1
	section text,code
