; Rolling Thunder's picture on the STE (renderer, step 1: the scrolling layers' composite).
;
; The three scrolling layers (CUS42 pair layers 0 and 1, CUS43 pair layer 0) move in lock step (their scroll values differ
; by the layers' dx offsets, tools/machine.py render_raw), so they are composed into one tile-aligned virtual screen
; `ren_bg`: 512 x 256 pixels, planar like the STE's screen (32 groups of 16 pixels = 8 bytes: plane 0-3 words, one tile
; column = one byte of a plane word), 256 bytes a line.  A cell is 8 x 8 pixels: cell (c, r) of the map (c 0-63, r 0-31)
; lies at ren_bg + r * 2048 + (c >> 1) * 8 + (c & 1), plane p at +2p, line y at + 256 y.
;
; A tile's STE form (`tcache`, tile_get): 8 lines of 5 bytes: the opaque mask, the planes 0-3 (zero where transparent),
; made on first use from the 3 bit pens (assets: ren_t0 / ren_t1) and the colour row's map (ren_rowmap: pens 0-6 -> STE
; index).  Direct mapped, 8192 slots of 44 bytes: key (long: $10000000 | dev << 24 | code << 8 | attr, 0 = empty), form.

TC_SLOTS = 8192
TC_SIZE = 44

	section text,code
; ---- tile_get: d0.w = device (0 CUS42 pair, 1 CUS43 pair), d1.w = tile code, d2.w = colour row (attribute byte) ->
; a0 = the tile's 40 byte form; d0-d7 a1-a3 clobbered ----
tile_get:
	moveq	#0,d3
	move.b	d0,d3
	swap	d3
	lsl.l	#8,d3			; dev << 24
	moveq	#0,d4
	move.w	d1,d4
	lsl.l	#8,d4			; code << 8
	or.l	d4,d3
	moveq	#0,d4
	move.b	d2,d4
	or.l	d4,d3
	or.l	#$10000000,d3		; the key
	move.w	d1,d4
	mulu	#37,d4			; the slot: a multiplicative mix of code, attribute and device
	moveq	#0,d5
	move.b	d2,d5
	mulu	#131,d5
	add.l	d5,d4
	move.w	d0,d5
	mulu	#1021,d5
	add.l	d5,d4
	lsr.l	#1,d4
	and.w	#TC_SLOTS-1,d4
	mulu	#TC_SIZE,d4
	lea	tcache,a1
	add.l	d4,a1
	cmp.l	(a1)+,d3
	beq.s	.hit
	move.l	d3,-4(a1)
	addq.l	#1,tc_miss
	lea	ren_t0,a2
	tst.w	d0
	beq.s	.d0
	lea	ren_t1,a2
.d0:	moveq	#0,d4
	move.w	d1,d4
	lsl.l	#6,d4
	add.l	d4,a2
	lea	ren_rowmap,a3
	moveq	#0,d4
	move.b	d2,d4
	lsl.w	#3,d4
	add.l	d4,a3
	move.l	a1,-(sp)
	bsr	tile_make
	move.l	(sp)+,a0
	rts
.hit:	move.l	a1,a0
	rts

; a1 = the form (written, 40 bytes, advanced), a2 = 64 pens, a3 = the row's 8 map entries (d0-d7 clobbered)
tile_make:
	move.w	#8,tm_rows
.row:	moveq	#0,d3
	moveq	#0,d4
	moveq	#0,d5
	moveq	#0,d6
	moveq	#0,d7
	rept	8
	moveq	#0,d0
	move.b	(a2)+,d0
	move.b	(a3,d0.w),d1
	subq.b	#7,d0
	sne	d2
	lsr.b	#1,d2
	roxl.b	#1,d3
	lsr.b	#1,d1
	roxl.b	#1,d4
	lsr.b	#1,d1
	roxl.b	#1,d5
	lsr.b	#1,d1
	roxl.b	#1,d6
	lsr.b	#1,d1
	roxl.b	#1,d7
	endr
	move.b	d3,(a1)+
	move.b	d4,(a1)+
	move.b	d5,(a1)+
	move.b	d6,(a1)+
	move.b	d7,(a1)+
	subq.w	#1,tm_rows
	bne	.row
	rts

; ---- ren_setup: the picture's layer order (the three scrolling layers by priority, ties the higher layer first: tools/
; machine.py render_raw) and the back colour's planes, from hwregs ----
ren_setup:
	lea	hwregs,a0
	moveq	#2,d7
.l:	move.w	d7,d0
	lsr.w	#1,d0
	lsl.w	#4,d0			; dev * 16
	move.w	d7,d1
	and.w	#1,d1
	lsl.w	#2,d1
	add.w	d1,d0			; + layer * 4
	moveq	#0,d1
	move.b	(a0,d0.w),d1		; the x scroll's high byte
	lsr.w	#1,d1
	and.w	#7,d1			; priority
	lsl.w	#2,d1
	moveq	#3,d2
	sub.w	d7,d2
	add.w	d2,d1			; key = priority * 4 + (3 - i)
	lsl.w	#8,d1
	or.w	d7,d1
	lea	lord,a1
	add.w	d7,d7
	move.w	d1,(a1,d7.w)
	lsr.w	#1,d7
	dbf	d7,.l
	lea	lord,a1			; sort the three (bubble: 0-1, 1-2, 0-1)
	bsr.s	.cs
	addq.l	#2,a1
	bsr.s	.cs
	subq.l	#2,a1
	bsr.s	.cs
	bra.s	.sorted
.cs:	move.w	(a1),d0
	cmp.w	2(a1),d0
	bls.s	.cr
	move.w	2(a1),(a1)
	move.w	d0,2(a1)
.cr:	rts
.sorted:
	moveq	#0,d0
	move.b	hwregs+$20,d0
	lea	ren_bk,a0
	move.b	(a0,d0.w),d0		; the STE index
	lea	bkp,a0
	moveq	#3,d1
.p:	lsr.b	#1,d0
	scs	d2
	move.b	d2,(a0)+
	dbf	d1,.p
	rts

; ---- ren_cell: d0.w = column (0-63), d1.w = row (0-31): the cell of ren_bg from the back colour and the layers ----
ren_cell:
	movem.l	d0-d7/a0-a5,-(sp)
	move.w	d0,d6			; column
	move.w	d1,d7			; row
	lea	ren_bg,a5
	moveq	#0,d2
	move.w	d7,d2
	lsl.l	#8,d2
	lsl.l	#3,d2			; row * 2048
	add.l	d2,a5
	move.w	d6,d2
	lsr.w	#1,d2
	lsl.w	#3,d2
	add.w	d2,a5
	move.w	d6,d2
	and.w	#1,d2
	add.w	d2,a5			; the cell's plane 0 byte of line 0
	lea	bkp,a0
	move.b	(a0)+,d0
	move.b	(a0)+,d1
	move.b	(a0)+,d2
	move.b	(a0)+,d3
	move.l	a5,a1
	moveq	#7,d4
.f:	move.b	d0,(a1)
	move.b	d1,2(a1)
	move.b	d2,4(a1)
	move.b	d3,6(a1)
	lea	256(a1),a1
	dbf	d4,.f
	clr.w	rc_n
.lay:	lea	lord,a0
	move.w	rc_n,d0
	add.w	d0,d0
	moveq	#0,d4
	move.b	1(a0,d0.w),d4		; the layer (lowest priority first)
	move.w	d4,d3
	lsr.w	#1,d3			; device
	lea	vram0,a0
	tst.w	d3
	beq.s	.v0
	lea	vram1,a0
.v0:	move.w	d4,d0
	and.w	#1,d0			; layer in the device
	lsl.w	#8,d0
	lsl.w	#4,d0
	add.w	d0,a0			; + layer * $1000
	move.w	d7,d0
	lsl.w	#6,d0
	add.w	d6,d0
	add.w	d0,d0
	add.w	d0,a0			; + (row * 64 + column) * 2
	moveq	#0,d1
	move.b	(a0)+,d1		; code (low)
	moveq	#0,d2
	move.b	(a0),d2			; attribute
	move.w	d3,d5
	lsl.w	#4,d5			; dev * 16
	move.w	d4,d0
	and.w	#1,d0
	lsl.w	#3,d0
	add.w	d0,d5			; + layer * 8
	move.w	d2,d0
	and.w	#3,d0
	add.w	d0,d0
	add.w	d0,d5			; + (attribute & 3) * 2
	lea	ren_hi,a0
	add.w	(a0,d5.w),d1		; + the PROM's select
	tst.w	d3
	bne.s	.nt
	moveq	#0,d0
	move.b	hwregs+$30,d0
	lsl.w	#8,d0
	lsl.w	#3,d0
	add.w	d0,d1			; + tile bank << 11
.nt:	move.w	d3,d0
	movem.l	d6-d7,-(sp)
	bsr	tile_get
	movem.l	(sp)+,d6-d7
	move.l	a5,a1
	moveq	#7,d4
.m:	move.b	(a0)+,d0		; mask
	beq.s	.skip
	cmp.b	#$FF,d0
	bne.s	.part
	move.b	(a0)+,(a1)
	move.b	(a0)+,2(a1)
	move.b	(a0)+,4(a1)
	move.b	(a0)+,6(a1)
	bra.s	.next
.part:	not.b	d0
	move.b	(a0)+,d1
	move.b	(a1),d2
	and.b	d0,d2
	or.b	d1,d2
	move.b	d2,(a1)
	move.b	(a0)+,d1
	move.b	2(a1),d2
	and.b	d0,d2
	or.b	d1,d2
	move.b	d2,2(a1)
	move.b	(a0)+,d1
	move.b	4(a1),d2
	and.b	d0,d2
	or.b	d1,d2
	move.b	d2,4(a1)
	move.b	(a0)+,d1
	move.b	6(a1),d2
	and.b	d0,d2
	or.b	d1,d2
	move.b	d2,6(a1)
	bra.s	.next
.skip:	addq.l	#4,a0
.next:	lea	256(a1),a1
	dbf	d4,.m
	addq.w	#1,rc_n
	cmp.w	#3,rc_n
	bne	.lay
	movem.l	(sp)+,d0-d7/a0-a5
	rts

; ---- ren_bg_all: every cell of ren_bg (ren_setup first) ----
ren_bg_all:
	bsr	ren_setup
	moveq	#0,d1
.r:	moveq	#0,d0
.c:	bsr	ren_cell
	addq.w	#1,d0
	cmp.w	#64,d0
	bne.s	.c
	addq.w	#1,d1
	cmp.w	#32,d1
	bne.s	.r
	rts

	section bss,bss
	even
tm_rows:	ds.w	1
	even
tc_miss:	ds.l	1
lord:		ds.w	3
rc_n:		ds.w	1
bkp:		ds.b	4
	even
ren_bg:		ds.b	256*256
tcache:		ds.b	TC_SLOTS*TC_SIZE
	section data,data
	even
ren_t0:		incbin	"ren_t0.bin"
ren_t1:		incbin	"ren_t1.bin"
ren_rowmap:	incbin	"ren_rowmap.bin"
ren_hi:		incbin	"ren_hi.bin"
ren_bk:		incbin	"ren_bk.bin"
ren_pal:	incbin	"ren_pal.bin"
