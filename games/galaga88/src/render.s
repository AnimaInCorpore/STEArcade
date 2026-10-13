; Galaga '88's picture on the STE: the arcade's 288 x 224 turned (ROT270, the game's flip on) to 224 x 288, at x 48-271
; of 320-pixel lines (the picture's edges on 16-pixel groups).  tools/assets.py turned the graphics, tools/stemodel.py
; is this file's geometry in Python (checked against the reference), tools/render_test.py checks every pixel.
;
; Picture row r = 287 - arcade x, column c = arcade y.  The layers (engine/namcos1.py):
;   0-2  the star fields (each scrolls on its own; ~1-2 opaque pixels a non-empty cell): plotted pixel by pixel in
;        every picture from lists of their non-empty cells, under the layers above them
;   3    the planets / the space station, 4 the HUD, 5 the backdrop (fixed): composed per 8 x 8 cell into the clean
;        buffer (ren_clean) when their tiles, layer 3's scroll, a bank, the priorities or the colour mapping change;
;        a cell line is the merge of its layers' converted character lines (ren_cimgs: 8 planar longs per character
;        and bank, made on first use) by their masks
;   sprites: all of Galaga '88's are priority 6 (above every layer); converted per (code, part, flips, colour) into a
;        cache and drawn with one short HOG Blitter pass a line (4 planes, the row's shifted opaque mask as the end masks)
; Buffers: REN_NBUF shown buffers and the clean one, 160 bytes a line, GUARD lines above and below the picture (whole
; sprites at the top and bottom); what a picture drew is restored from the clean buffer when the buffer comes again.
;
; Colours (as Splatterhouse's renderer): 15 colours + black chosen per scene (ren_choose: the colours on the picture
; sampled - two pixels a cell, the stars x 4, 16 a sprite x 4 -, weighted by the root of their counts, a median cut
; and k-means in Oklab).  A pen's index is the nearest colour of its colour when they were chosen (ren_palsnap;
; ren_lut by the 4 bit colour, filled on demand); the STE's colour of an index is the current colour of a
; representative pen (the pen of the sampled colour nearest the centre), so fades and colour cycling change the STE
; palette, not the picture.  Chosen again: a new scene (the backdrop changed; black until the palette rests 2
; pictures, at most REN_WAIT), or a palette that rested 8 pictures on other colours than those chosen.
;
; Interface: render_init (once, vio holds a state), render_frame (a picture: draws into a free buffer and publishes
; it), render_vbl (in the VBL: shows the published buffer, ren_vbl_pal its palette).  All registers kept.  Needs: vio
; (the virtual space $2E0000-$307FFF: the C116 at +0, tile RAM +$10000, sprite RAM +$1C800, CUS123 control +$1D000),
; blit_go (borders.s), tile_written / tile_written_fix (set by the translated writers of tile RAM: TILE_FLAG).

	ifnd	REN_NBUF
REN_NBUF = 3
	endc
	ifnd	CROP_TOP
CROP_TOP = 0			; the first picture row shown
	endc
	ifnd	REN_WAIT
REN_WAIT = 6
	endc
STRIDE = 160
GUARD = 32
PIC_H = 288
PIC_W = 224
PIC_BYTE = 24			; the picture's first byte in a line (x 48)
BUF_LINES = PIC_H+2*GUARD
BUF_SIZE = BUF_LINES*STRIDE
CROWS = 36			; cells: 36 rows of 28
CCOLS = 28
NCELLS = CROWS*CCOLS
VIO_PAL = 0
VIO_TILE = $10000
VIO_SPR = $1C800
VIO_CTL = $1D000
DMG_MAX = 200			; sprite rectangles a buffer
STAR_MAX = 2400			; plotted star words a buffer
POOL_SIZE = 128*1024		; the sprite cache
HASH_N = 512
NENT_MAX = 1024			; the colours a choice clusters
ENT = 8				; (bytes an entry: L a b centre, weight.w, colour.w)

	section text,code

; ---- init ----
render_init:
	movem.l	d0-d7/a0-a6,-(sp)
	lea	ren_bufs,a0		; the buffers black
	move.l	#(BUF_SIZE*(REN_NBUF+1))/4-1,d0
.c:	clr.l	(a0)+
	subq.l	#1,d0
	bpl	.c
	lea	ren_bufs,a0
	lea	ren_bufp,a1
	moveq	#REN_NBUF+1-1,d0
.b:	move.l	a0,(a1)+
	add.l	#BUF_SIZE,a0
	dbf	d0,.b
	move.l	ren_bufp+4*REN_NBUF,ren_clean
	lea	ren_mask,a0		; the non-empty characters
	lea	ren_nonempty,a1
	move.w	#8192-1,d0
.ne:	move.l	(a0)+,d1
	or.l	(a0)+,d1
	sne	(a1)+
	dbf	d0,.ne
	lea	ren_rep4,a0		; a mask byte in all four bytes
	moveq	#0,d0
.r4:	move.b	d0,d1
	lsl.w	#8,d1
	move.b	d0,d1
	move.w	d1,d2
	swap	d1
	move.w	d2,d1
	move.l	d1,(a0)+
	addq.b	#1,d0
	bne	.r4
	lea	ren_mask,a0		; per character: its rows with pixels (bit 7: row 0)
	lea	ren_rowbits,a1
	move.w	#8192-1,d0
.rb:	moveq	#8-1,d2
	moveq	#0,d1
.rb2:	add.b	d1,d1
	tst.b	(a0)+
	beq	.rb3
	addq.b	#1,d1
.rb3:	dbf	d2,.rb2
	move.b	d1,(a1)+
	dbf	d0,.rb
	lea	ren_onebit,a0		; a mask byte with one pixel: its bit, else -1
	move.w	#256/4-1,d0
.ob:	move.l	#-1,(a0)+
	dbf	d0,.ob
	lea	ren_onebit,a0
	moveq	#0,d0
	moveq	#1,d1
.ob2:	move.b	d0,(a0,d1.w)
	add.w	d1,d1
	addq.w	#1,d0
	cmp.w	#8,d0
	bne	.ob2
	lea	ren_ltab,a0		; the line offsets of the picture's rows -8 .. 295: (GUARD + r) * STRIDE + PIC_BYTE
	move.l	#(GUARD-8)*STRIDE+PIC_BYTE,d0
	move.w	#PIC_H+16-1,d1
.lt:	move.l	d0,(a0)+
	add.l	#STRIDE,d0
	dbf	d1,.lt
	lea	ren_ctab,a0		; the cover planes' rows: r * 28
	moveq	#0,d0
	move.w	#PIC_H-1,d1
.ct:	move.w	d0,(a0)+
	add.w	#CCOLS,d0
	dbf	d1,.ct
	bsr	ren_cache_clear
	move.b	#-1,ren_shown
	move.b	#-1,ren_ready
	move.b	#-1,ren_prev
	st	ren_scene		; (the first picture: a new scene)
	st	ren_all
	movem.l	(sp)+,d0-d7/a0-a6
	rts

; ---- a picture ----
render_frame:
	movem.l	d0-d7/a0-a6,-(sp)
	bsr	ren_pick		; d0 = a free buffer, or -1
	tst.w	d0
	bmi	.none
	move.w	d0,ren_cur
	lsl.w	#2,d0
	lea	ren_bufp,a0
	move.l	(a0,d0.w),ren_dst
	bsr	ren_window		; the C116 window: nothing shown (ren_wblack)
	bsr	ren_palette		; the colours (a choice: everything again); ren_black while a new scene waits
	bsr	ren_bg_check		; what changed of layers 3-5 (dirty cells; a new backdrop: a new scene)
	tst.b	ren_black
	bne	.pub			; (black: the buffer is left as it is)
	bsr	ren_compose		; the dirty cells into the clean buffer (and the cover planes)
	bsr	ren_restore		; this buffer: the cells composed since, the last picture's damage
	bsr	ren_stars
	bsr	ren_sprites
.pub:	ifd	TILE_FLAG
	sf	tile_written		; (the flags are consumed)
	sf	tile_written_fix
	endc
	ifd	TILE_ROWS
	sf	tile_fix_all
	lea	tile_fix_rows,a0
	moveq	#56/4-1,d0
.fr:	clr.l	(a0)+
	dbf	d0,.fr
	endc
	bsr	ren_buf_palette		; the buffer's palette (black when ren_black)
	move.w	ren_cur,d0
	move.b	d0,ren_ready		; published
	addq.l	#1,ren_pictures
	movem.l	(sp)+,d0-d7/a0-a6
	rts
.none:	addq.l	#1,ren_skipped
	movem.l	(sp)+,d0-d7/a0-a6
	rts

; d0.w = a buffer neither shown, nor shown before (the Shifter may still scan it), nor published; else -1
ren_pick:
	moveq	#0,d0
.l:	cmp.b	ren_shown,d0
	beq	.n
	cmp.b	ren_prev,d0
	beq	.n
	cmp.b	ren_ready,d0
	beq	.n
	rts
.n:	addq.w	#1,d0
	cmp.w	#REN_NBUF,d0
	bne	.l
	moveq	#-1,d0
	rts

; ---- the VBL: show the published buffer and its palette (ren_vbl_pal: 16 words) ----
render_vbl:
	movem.l	d0-d1/a0-a1,-(sp)
	move.b	ren_ready,d0
	bmi	.free
	move.b	ren_shown,ren_prev
	move.b	d0,ren_shown
	move.b	#-1,ren_ready
	ext.w	d0
	move.w	d0,d1
	lsl.w	#2,d0
	lea	ren_bufp,a0
	move.l	(a0,d0.w),d0
	add.l	#(GUARD+CROP_TOP)*STRIDE,d0
	move.l	d0,ren_vbase
	ifnd	SIM
	move.l	d0,-(sp)		; (high and middle byte first: writing them clears the STE's low byte)
	lsr.l	#8,d0
	move.b	d0,$ffff8203.w
	lsr.w	#8,d0
	move.b	d0,$ffff8201.w
	move.l	(sp)+,d0
	move.b	d0,$ffff820d.w
	endc
	lsl.w	#5,d1			; the buffer's palette
	lea	ren_bpal,a0
	add.w	d1,a0
	lea	ren_vbl_pal,a1
	moveq	#8-1,d0
.p:	move.l	(a0)+,(a1)+
	dbf	d0,.p
	bra	.r
.free:	move.b	#-1,ren_prev		; (a VBL without a new picture: the one shown before is free)
.r:	movem.l	(sp)+,d0-d1/a0-a1
	rts

; ---- the C116 window: Galaga '88 shows all of MAME's visible area, or nothing (the boot's 0 0 0 0) ----
ren_window:
	lea	vio+VIO_PAL+$1800,a0	; (the registers: the C116's plane 3, words 0-3)
	move.w	(a0),d0			; x0: max(73, reg0 - 1) .. x1: min(360, reg1 - 2) must not be empty
	subq.w	#1,d0
	cmp.w	#73,d0
	bge	.x0
	moveq	#73,d0
.x0:	move.w	2(a0),d1
	subq.w	#2,d1
	cmp.w	#360,d1
	ble	.x1
	move.w	#360,d1
.x1:	cmp.w	d1,d0
	bgt	.black
	move.w	4(a0),d0		; y0: max(16, reg2 - $11) .. y1: min(239, reg3 - $12)
	sub.w	#$11,d0
	cmp.w	#16,d0
	bge	.y0
	moveq	#16,d0
.y0:	move.w	6(a0),d1
	sub.w	#$12,d1
	cmp.w	#239,d1
	ble	.y1
	move.w	#239,d1
.y1:	cmp.w	d1,d0
	bgt	.black
	sf	ren_wblack
	rts
.black:	st	ren_wblack
	rts

; ======== colours ========

; The palette's state per picture: the checksum of sampled pens (its rest), a new scene's wait, a choice.
ren_palette:
	sf	ren_black
	bsr	ren_pal_sum		; d6 = the checksum, d7 = their OR (0: all black)
	tst.b	d7
	seq	ren_allblack
	cmp.l	ren_ck,d6
	beq	.st
	move.l	d6,ren_ck
	clr.b	ren_stable
	bra	.dec
.st:	cmp.b	#250,ren_stable
	bhs	.dec
	addq.b	#1,ren_stable
.dec:	tst.b	ren_wblack
	bne	.blk			; (the window shows nothing)
	tst.b	ren_scene
	beq	.old
	tst.b	ren_allblack		; a new scene: black until the palette rests (not black), then new colours
	bne	.blk
	addq.b	#1,ren_wait
	cmp.b	#REN_WAIT,ren_wait
	bhs	.ch			; (a palette that keeps moving: not longer)
	cmp.b	#2,ren_stable
	blo	.blk
.ch:	clr.b	ren_wait
	addq.l	#1,ren_ch_scene
	bsr	ren_choose
	sf	ren_scene
	rts
.old:	addq.b	#1,ren_qtick		; every 16 pictures: chosen again when the colours fit clearly worse than right
	and.b	#15,ren_qtick		; after the choice
	bne	.r
	tst.b	ren_allblack
	bne	.r
	bsr	ren_quality
	move.w	d0,ren_qlast
	move.w	ren_err0,d1
	move.w	d1,d2
	lsr.w	#2,d2
	add.w	d2,d1
	addq.w	#REN_ERRADD,d1
	cmp.w	d1,d0
	bls	.r
	addq.l	#1,ren_ch_rest
	bsr	ren_choose
.r:	rts
.blk:	st	ren_black
	rts

; d0.w = how well the STE colours fit now: the mean L1 Oklab distance (bytes) between the current colour of the pens
; on the picture (the sprites of the last picture: a pixel each; 126 cells of the background: the top layer's pixel
; (4, 4)) and the current STE colour of their index (its representative's current colour).
REN_ERRADD = 3			; (chosen again: the error above 1.25 x the one right after the choice + this)
ren_quality:
	movem.l	d1-d7/a0-a6,-(sp)
	moveq	#0,d6			; the sum
	moveq	#0,d7			; the samples
	lea	ren_slst,a5		; the sprites of the last picture
.s:	cmp.l	ren_slend,a5
	bhs	.done
	bsr	ren_sl_get
	move.w	ren_ssx,d5
	lsr.w	#1,d5
	move.w	ren_ssy,d4
	lsr.w	#1,d4
	bsr	ren_spr_pen		; (the middle pixel)
	cmp.w	#15,d1
	beq	.sn
	move.w	ren_scol,d0
	lsl.w	#4,d0
	add.w	d1,d0
	bsr	ren_pen_err
.sn:	lea	SL(a5),a5
	bra	.s
.done:	bsr	ren_bg_order		; and 126 cells of the background (every 8th): the top layer's pen at (4, 4)
	moveq	#0,d5
.bc:	move.w	d5,d0
	moveq	#0,d1
	move.w	d0,d1
	divu	#CCOLS,d1
	move.w	d1,ren_cr
	swap	d1
	move.w	d1,ren_cc
	bsr	ren_cell_chars
	bsr	ren_bg_pen		; d0 = the pen, or -1
	tst.w	d0
	bmi	.bn
	bsr	ren_pen_err
.bn:	addq.w	#8,d5
	cmp.w	#NCELLS,d5
	blo	.bc
	move.l	d6,d0
	tst.w	d7
	beq	.r
	divu	d7,d0
.r:	movem.l	(sp)+,d1-d7/a0-a6
	rts

; d0.w = a pen: d6 += the L1 Oklab distance of its current colour and its index's STE colour, d7 += 1
ren_pen_err:
	movem.l	d0-d5/a0-a2,-(sp)
	bsr	ren_pen_index		; d1 = its index
	bsr	.lab			; a1 = its colour's Oklab
	move.l	a1,a2
	move.w	d1,d0			; the index's representative
	add.w	d0,d0
	lea	ren_rep,a0
	move.w	(a0,d0.w),d0
	bmi	.blk
	bsr	.lab
	bra	.d
.blk:	lea	ren_lab,a1		; (black)
.d:	moveq	#3-1,d2
	moveq	#0,d3
.ax:	moveq	#0,d4
	moveq	#0,d5
	move.b	(a1)+,d4
	move.b	(a2)+,d5
	sub.w	d5,d4
	bpl	.p
	neg.w	d4
.p:	add.w	d4,d3
	dbf	d2,.ax
	add.l	d3,d6
	addq.w	#1,d7
	movem.l	(sp)+,d0-d5/a0-a2
	rts
; d0.w = a pen -> a1 = the Oklab bytes of its current colour (4 bits a channel).  d1 kept.
.lab:	move.w	d1,-(sp)
	bsr	ren_pen_addr
	lea	ren_q8,a1
	moveq	#0,d1
	moveq	#0,d2
	move.b	(a0),d1
	move.b	(a1,d1.w),d2
	lsl.w	#4,d2
	move.b	$800(a0),d1
	or.b	(a1,d1.w),d2
	lsl.w	#4,d2
	move.b	$1000(a0),d1
	or.b	(a1,d1.w),d2
	lsl.w	#2,d2
	lea	ren_lab,a1
	add.w	d2,a1
	move.w	(sp)+,d1
	rts

; the cell ren_cr / ren_cc (ren_cch made) -> d0.w = the top layer's pen at its pixel (4, 4), -1 for none.  Keeps
; d1-d7.
ren_bg_pen:
	movem.l	d1-d7/a0/a4,-(sp)
	lea	ren_bgl,a4
	move.w	ren_bgn,d3
	subq.w	#1,d3
	bmi	.none
	moveq	#4,d5			; (the line and the column)
.lay:	move.w	(a4),d0
	sub.w	#3,d0
	lsl.w	#3,d0
	lea	ren_cch,a0
	add.w	d0,a0
	move.w	(a0),d1			; A
	move.w	2(a0),d2
	add.w	d5,d2
	cmp.w	4(a0),d5
	blo	.a
	move.w	6(a0),d1		; B
	move.w	d5,d2
	sub.w	4(a0),d2
.a:	addq.l	#6,a4
	cmp.w	#8192,d1
	bhs	.ln
	lea	ren_mask,a0
	moveq	#0,d0
	move.w	d1,d0
	lsl.l	#3,d0
	add.w	d2,d0
	btst	#3,(a0,d0.l)		; (column 4: bit 3)
	beq	.ln
	lea	ren_chr,a0
	moveq	#0,d0
	move.w	d1,d0
	lsl.l	#6,d0
	lsl.w	#3,d2
	add.w	d2,d0
	addq.w	#4,d0
	moveq	#0,d1
	move.b	(a0,d0.l),d1
	move.w	-4(a4),d0		; the bank
	lsl.w	#8,d0
	add.w	d1,d0
	add.w	#$800,d0
	bra	.r
.ln:	dbf	d3,.lay
.none:	moveq	#-1,d0
.r:	movem.l	(sp)+,d1-d7/a0/a4
	rts

; d6.l = a checksum of sampled pens (every 16th of the banks of layers 3-5, every 32nd sprite pen), d7.b their OR
; (not the star layers': their bank selection cycles all the time)
ren_pal_sum:
	moveq	#0,d6
	moveq	#0,d7
	lea	vio+VIO_CTL+$18+3,a1
	moveq	#3-1,d5
.l:	moveq	#7,d0
	and.b	(a1)+,d0
	lsl.w	#8,d0
	lea	vio+VIO_PAL+$2000,a0
	add.w	d0,a0
	moveq	#16-1,d4
	moveq	#16,d3
	bsr	.sum
	dbf	d5,.l
	lea	vio+VIO_PAL,a0		; pens 0-$7FF
	move.w	#64-1,d4
	moveq	#32,d3
.sum:	rol.l	#1,d6
	moveq	#0,d0
	move.b	(a0),d0
	add.l	d0,d6
	or.b	d0,d7
	move.b	$800(a0),d0
	add.l	d0,d6
	or.b	d0,d7
	move.b	$1000(a0),d0
	add.l	d0,d6
	or.b	d0,d7
	add.w	d3,a0
	dbf	d4,.sum
	rts

; the buffer's 16 STE colours (ren_bpal + buffer * 32): the representatives' current colours; black: all 0
ren_buf_palette:
	move.w	ren_cur,d0
	lsl.w	#5,d0
	lea	ren_bpal,a1
	add.w	d0,a1
	tst.b	ren_black
	bne	.blk
	clr.w	(a1)+
	lea	ren_rep+2,a2
	lea	ren_q8,a3
	lea	ren_stenib(pc),a4
	moveq	#15-1,d5
.c:	move.w	(a2)+,d0
	bmi	.z			; (no colour)
	bsr	ren_pen_addr		; a0 = the pen's red in vio
	moveq	#0,d1
	moveq	#0,d2
	move.b	(a0),d1
	move.b	(a3,d1.w),d1
	move.b	(a4,d1.w),d2		; R
	lsl.w	#4,d2
	move.b	$800(a0),d1
	move.b	(a3,d1.w),d1
	or.b	(a4,d1.w),d2		; G
	lsl.w	#4,d2
	move.b	$1000(a0),d1
	move.b	(a3,d1.w),d1
	or.b	(a4,d1.w),d2		; B
	move.w	d2,(a1)+
	dbf	d5,.c
	rts
.z:	clr.w	(a1)+
	dbf	d5,.c
	rts
.blk:	moveq	#8-1,d5
.bk:	clr.l	(a1)+
	dbf	d5,.bk
	rts

; 4-bit level -> the STE's nibble (bits 3-1 the high bits, bit 0 in bit 3)
ren_stenib:
	dc.b	$0,$8,$1,$9,$2,$a,$3,$b,$4,$c,$5,$d,$6,$e,$7,$f
	even

; d0.w = a pen (0-$FFF) -> a0 = its red byte in vio (green +$800, blue +$1000).  Keeps everything else.
ren_pen_addr:
	move.l	d1,-(sp)
	move.w	d0,d1
	and.w	#$1800,d1
	add.w	d1,d1
	add.w	d1,d1
	move.w	d0,-(sp)
	and.w	#$7FF,d0
	add.w	d1,d0
	lea	vio+VIO_PAL,a0
	add.w	d0,a0
	move.w	(sp)+,d0
	move.l	(sp)+,d1
	rts

; d0.w = a pen (0-$FFF) -> d1.w = its index: 0 for black, else the nearest centre of its colour when the colours were
; chosen (ren_palsnap), by the 4 bit colour (ren_lut: $FF = not known yet).  Keeps everything else.
ren_pen_index:
	movem.l	d0/d2-d5/a0-a2,-(sp)
	move.w	d0,d1
	and.w	#$1800,d1
	add.w	d1,d1
	add.w	d1,d1
	and.w	#$7FF,d0
	add.w	d1,d0
	lea	ren_palsnap,a0
	add.w	d0,a0
	lea	ren_q8,a1
	moveq	#0,d1
	moveq	#0,d2
	move.b	(a0),d1
	move.b	(a1,d1.w),d2
	lsl.w	#4,d2
	move.b	$800(a0),d1
	or.b	(a1,d1.w),d2
	lsl.w	#4,d2
	move.b	$1000(a0),d1
	or.b	(a1,d1.w),d2		; the 4 bit colour
	moveq	#0,d1
	tst.w	d2
	beq	.out			; black
	lea	ren_lut,a1
	move.b	(a1,d2.w),d1
	bpl	.out
	lea	(a1,d2.w),a2
	lsl.w	#2,d2
	lea	ren_lab,a0
	add.w	d2,a0
	bsr	ren_nearest
	move.b	d1,(a2)
.out:	movem.l	(sp)+,d0/d2-d5/a0-a2
	rts

; a0 = an Oklab colour (3 bytes) -> d1.w = the nearest centre (1-15; L1 distance; the first of equals).  Uses d0
; d2-d5, a1.
ren_nearest:
	lea	ren_cent+4,a1
	moveq	#1,d1
	move.w	#$7fff,d5
	moveq	#1,d4
	move.w	ren_ncent,d3
.c:	cmp.w	d3,d4
	bhi	.done
	moveq	#0,d0
	moveq	#0,d2
	move.b	(a0),d0
	move.b	(a1),d2
	sub.w	d2,d0
	bpl	.p1
	neg.w	d0
.p1:	move.w	d0,-(sp)
	moveq	#0,d0
	move.b	1(a0),d0
	move.b	1(a1),d2
	sub.w	d2,d0
	bpl	.p2
	neg.w	d0
.p2:	add.w	d0,(sp)
	moveq	#0,d0
	move.b	2(a0),d0
	move.b	2(a1),d2
	sub.w	d2,d0
	bpl	.p3
	neg.w	d0
.p3:	add.w	(sp)+,d0
	cmp.w	d5,d0
	bhs	.n
	move.w	d0,d5
	move.w	d4,d1
.n:	addq.l	#4,a1
	addq.w	#1,d4
	bra	.c
.done:	rts

; ---- a choice of colours ----
; The palette now as the mapping's (ren_palsnap); the histogram of the 4 bit colours of the samples (ren_hist,
; ren_hpen: a pen of each); the entries (Oklab, the root of the count); the median cut into up to 15 boxes, 4 rounds
; of k-means (3); per centre the representative (the entry nearest it); every mapping, converted character and sprite
; stale, every cell composed again.
ren_choose:
	movem.l	d0-d7/a0-a6,-(sp)
	addq.l	#1,ren_choices
	move.l	ren_ck,ren_ck_chosen
	lea	vio+VIO_PAL,a0
	lea	ren_palsnap,a1
	move.w	#$4000/16-1,d0
.ps:	move.l	(a0)+,(a1)+
	move.l	(a0)+,(a1)+
	move.l	(a0)+,(a1)+
	move.l	(a0)+,(a1)+
	dbf	d0,.ps
	lea	ren_hist,a0
	move.w	#4096/2-1,d0
.hc:	clr.l	(a0)+
	dbf	d0,.hc
	bsr	ren_sample_bg
	bsr	ren_sample_stars
	bsr	ren_sample_sprites
	bsr	ren_entries		; ren_ent, ren_nent
	bsr	ren_median_cut		; ren_cent, ren_ncent
	moveq	#3-1,d7
.km:	bsr	ren_kmeans
	dbf	d7,.km
	bsr	ren_reps
	lea	ren_lut,a0		; the mappings: nothing known
	move.w	#4096/4-1,d0
	moveq	#-1,d1
.lc:	move.l	d1,(a0)+
	dbf	d0,.lc
	bsr	ren_quality		; (the fit right after the choice)
	move.w	d0,ren_err0
	addq.w	#1,ren_epoch		; (the converted characters)
	bsr	ren_cache_clear		; (the sprites)
	st	ren_all
	movem.l	(sp)+,d0-d7/a0-a6
	rts

; d0.w = a pen, d1.w = its weight: into the histogram (counts capped at 4095) by its 4 bit colour (now = ren_palsnap)
ren_hist_add:
	movem.l	d0-d3/a0-a1,-(sp)
	move.w	d0,d3
	bsr	ren_pen_addr
	lea	ren_q8,a1
	moveq	#0,d0
	moveq	#0,d2
	move.b	(a0),d0
	move.b	(a1,d0.w),d2
	lsl.w	#4,d2
	move.b	$800(a0),d0
	or.b	(a1,d0.w),d2
	lsl.w	#4,d2
	move.b	$1000(a0),d0
	or.b	(a1,d0.w),d2
	tst.w	d2
	beq	.r			; (black is index 0)
	add.w	d2,d2
	lea	ren_hist,a0
	add.w	(a0,d2.w),d1
	cmp.w	#4095,d1
	bls	.c
	move.w	#4095,d1
.c:	move.w	d1,(a0,d2.w)
	lea	ren_hpen,a0
	move.w	d3,(a0,d2.w)
.r:	movem.l	(sp)+,d0-d3/a0-a1
	rts

; the background: two pixels of every cell (line 2 column 2, line 5 column 5), the top layer's pen there (the cell's
; characters: ren_cell_chars)
ren_sample_bg:
	bsr	ren_bg_order
	clr.w	ren_cr
	clr.w	ren_cc
	moveq	#0,d7
.cell:	bsr	ren_cell_chars
	moveq	#2,d5
	moveq	#2,d4
	bsr.s	.pix
	moveq	#5,d5
	moveq	#5,d4
	bsr.s	.pix
	addq.w	#1,ren_cc
	cmp.w	#CCOLS,ren_cc
	bne.s	.nx
	clr.w	ren_cc
	addq.w	#1,ren_cr
.nx:	addq.w	#1,d7
	cmp.w	#NCELLS,d7
	bne.s	.cell
	rts
; d5 = the line, d4 = the column: the top layer's pen
.pix:	lea	ren_bgl,a4
	move.w	ren_bgn,d3
	subq.w	#1,d3
	bmi.s	.pr
.lay:	move.w	(a4),d0			; the layer: its character at the line
	sub.w	#3,d0
	lsl.w	#3,d0
	lea	ren_cch,a0
	add.w	d0,a0
	move.w	(a0),d1			; A
	move.w	2(a0),d2
	add.w	d5,d2			; its row
	cmp.w	4(a0),d5
	blo.s	.a
	move.w	6(a0),d1		; B
	move.w	d5,d2
	sub.w	4(a0),d2
.a:	addq.l	#6,a4
	cmp.w	#8192,d1
	bhs.s	.ln
	lea	ren_mask,a0
	moveq	#0,d0
	move.w	d1,d0
	lsl.l	#3,d0
	add.w	d2,d0
	move.b	(a0,d0.l),d0
	moveq	#7,d6
	sub.w	d4,d6
	btst	d6,d0
	beq.s	.ln
	lea	ren_chr,a0		; the pen: character * 64 + row * 8 + column
	moveq	#0,d0
	move.w	d1,d0
	lsl.l	#6,d0
	lsl.w	#3,d2
	add.w	d2,d0
	add.w	d4,d0
	moveq	#0,d1
	move.b	(a0,d0.l),d1
	move.w	-4(a4),d0		; the bank
	lsl.w	#8,d0
	add.w	d1,d0
	add.w	#$800,d0
	moveq	#1,d1
	bra	ren_hist_add
.ln:	dbf	d3,.lay
.pr:	rts

; the stars: the pixels of the first 16 non-empty cells of each enabled star layer, weight 4
ren_sample_stars:
	moveq	#0,d5
.lay:	lea	vio+VIO_CTL,a0
	btst	#3,$10(a0,d5.w)
	bne	.nl
	moveq	#7,d6
	and.b	$18(a0,d5.w),d6
	lsl.w	#8,d6
	add.w	#$800,d6		; the bank's first pen
	move.w	d5,d0			; (the layer's tile words)
	moveq	#13,d1
	lsl.w	d1,d0
	lea	vio+VIO_TILE,a5
	add.w	d0,a5
	lea	ren_nonempty,a1
	move.w	#4096-1,d4		; (words)
	moveq	#16-1,d7
.cell:	move.w	(a5)+,d0
	and.w	#$3FFF,d0
	tst.b	(a1,d0.w)
	bne.s	.ne
	dbf	d4,.cell
	bra.s	.nl
.ne:	movem.l	d4/a1,-(sp)
	lea	ren_mask,a2		; its masks, its pens
	moveq	#0,d1
	move.w	d0,d1
	lsl.l	#3,d1
	add.l	d1,a2
	lea	ren_chr,a3
	lsl.l	#3,d1
	add.l	d1,a3
	moveq	#0,d3			; the pixel
.px:	move.w	d3,d0
	lsr.w	#3,d0
	move.b	(a2,d0.w),d0
	beq.s	.skip			; (an empty row)
	moveq	#7,d1
	and.w	d3,d1
	eor.w	#7,d1
	btst	d1,d0
	beq.s	.pn
	moveq	#0,d0
	move.b	(a3,d3.w),d0
	add.w	d6,d0
	moveq	#4,d1
	bsr	ren_hist_add
.pn:	addq.w	#1,d3
	cmp.w	#64,d3
	bne.s	.px
	bra.s	.cd
.skip:	or.w	#7,d3
	bra.s	.pn
.cd:	movem.l	(sp)+,d4/a1
	subq.w	#1,d4
	bmi.s	.nl
	dbf	d7,.cell
.nl:	addq.w	#1,d5
	cmp.w	#3,d5
	bne	.lay
	rts

; the sprites on the picture: 16 pixels of each (a 4 x 4 grid over the part), weight 4
ren_sample_sprites:
	lea	vio+VIO_SPR,a6
	bsr	ren_spr_offsets
	moveq	#0,d7
.ent:	movem.l	d7/a6,-(sp)
	bsr	ren_spr_geom		; Z: not on the picture
	beq	.n
	moveq	#0,d5			; dr: 0, sizex/4, ...
.r:	moveq	#0,d4
.c:	bsr	ren_spr_pen		; d1 = the pen (4 bits) at (d5, d4)
	cmp.w	#15,d1
	beq	.t
	move.w	ren_scol,d0
	lsl.w	#4,d0
	add.w	d1,d0
	moveq	#4,d1
	bsr	ren_hist_add
.t:	move.w	ren_ssy,d0
	lsr.w	#2,d0
	add.w	d0,d4
	cmp.w	ren_ssy,d4
	blo	.c
	move.w	ren_ssx,d0
	lsr.w	#2,d0
	add.w	d0,d5
	cmp.w	ren_ssx,d5
	blo	.r
.n:	movem.l	(sp)+,d7/a6
	lea	16(a6),a6
	addq.w	#1,d7
	cmp.w	#127,d7
	bne	.ent
	rts

; the histogram's colours -> ren_ent (per entry L, a, b, 0, the weight: the root of the count, the colour); ren_nent
ren_entries:
	lea	ren_hist,a0
	lea	ren_ent,a1
	lea	ren_lab,a2
	lea	ren_sqrt,a3
	moveq	#0,d6			; entries
	moveq	#0,d7			; the colour
.l:	move.w	(a0)+,d0
	beq	.n
	cmp.w	#NENT_MAX,d6
	bhs	.n
	move.w	d7,d1
	lsl.w	#2,d1
	move.l	(a2,d1.w),(a1)+		; L a b 0
	moveq	#0,d1
	move.b	(a3,d0.w),d1
	bne	.w
	moveq	#1,d1
.w:	move.w	d1,(a1)+
	move.w	d7,(a1)+
	addq.w	#1,d6
.n:	addq.w	#1,d7
	cmp.w	#4096,d7
	bne	.l
	move.w	d6,ren_nent
	rts

; The weighted median cut: boxes are ranges of ren_ent (ren_box: first.w, end.w); the box with the largest (the
; widest axis' extent x its weight) is sorted on that axis (a counting sort) and split at its weighted median, until
; 15 boxes or none splits; ren_cent = the boxes' weighted means.
ren_median_cut:
	clr.w	ren_ncent
	move.w	ren_nent,d0
	beq	.r
	lea	ren_box,a0
	clr.w	(a0)+
	move.w	d0,(a0)+
	move.w	#1,ren_nbox
.split:	cmp.w	#15,ren_nbox
	bhs	.means
	moveq	#-1,d7			; the best box
	moveq	#0,d5			; its score
	moveq	#0,d4
.b:	cmp.w	ren_nbox,d4
	bhs	.bd
	bsr	ren_box_score		; d0.l = the score, d1 = the axis
	cmp.l	d5,d0
	bls	.bn
	move.l	d0,d5
	move.w	d4,d7
	move.w	d1,d6
.bn:	addq.w	#1,d4
	bra	.b
.bd:	tst.w	d7
	bmi	.means
	move.w	d7,d4
	bsr	ren_box_sort		; (by axis d6)
	lea	ren_box,a0		; the weighted median
	move.w	d4,d0
	lsl.w	#2,d0
	move.w	(a0,d0.w),d2		; first
	move.w	2(a0,d0.w),d3		; end
	lea	ren_ent,a1
	moveq	#0,d1			; the weight
	move.w	d2,d0
.ws:	move.w	d0,d5
	lsl.w	#3,d5
	add.w	4(a1,d5.w),d1
	addq.w	#1,d0
	cmp.w	d3,d0
	blo	.ws
	lsr.w	#1,d1			; half
	moveq	#0,d5
	move.w	d2,d0
.wm:	move.w	d0,d6
	lsl.w	#3,d6
	add.w	4(a1,d6.w),d5
	addq.w	#1,d0
	cmp.w	d1,d5
	blo	.wm
	cmp.w	d3,d0			; (the split: first .. d0, d0 .. end; neither empty)
	blo	.ok
	move.w	d3,d0
	subq.w	#1,d0
.ok:	cmp.w	d2,d0
	bhi	.ok2
	move.w	d2,d0
	addq.w	#1,d0
.ok2:	move.w	d4,d1
	lsl.w	#2,d1
	move.w	d0,2(a0,d1.w)		; the box: first .. d0
	move.w	ren_nbox,d1
	lsl.w	#2,d1
	move.w	d0,(a0,d1.w)		; a new box: d0 .. end
	move.w	d3,2(a0,d1.w)
	addq.w	#1,ren_nbox
	bra	.split
.means:	lea	ren_box,a0		; the centres: the boxes' weighted means
	lea	ren_cent+4,a2
	moveq	#0,d4
.m:	cmp.w	ren_nbox,d4
	bhs	.md
	move.w	(a0)+,d2
	move.w	(a0)+,d3
	bsr	ren_mean
	addq.l	#4,a2
	addq.w	#1,d4
	bra	.m
.md:	move.w	ren_nbox,ren_ncent
.r:	rts

; d2 = the first entry, d3 = the end: their weighted mean (L a b) into (a2).  Keeps d2-d4, a0, a2.
ren_mean:
	movem.l	d2-d4/a0,-(sp)
	lea	ren_ent,a1
	moveq	#0,d5			; sum L
	moveq	#0,d6			; sum a
	moveq	#0,d7			; sum b
	moveq	#0,d1			; weight
.l:	cmp.w	d3,d2
	bhs	.d
	move.w	d2,d0
	lsl.w	#3,d0
	lea	(a1,d0.w),a0
	moveq	#0,d4
	move.w	4(a0),d4
	add.l	d4,d1
	moveq	#0,d0
	move.b	(a0),d0
	mulu	d4,d0
	add.l	d0,d5
	moveq	#0,d0
	move.b	1(a0),d0
	mulu	d4,d0
	add.l	d0,d6
	moveq	#0,d0
	move.b	2(a0),d0
	mulu	d4,d0
	add.l	d0,d7
	addq.w	#1,d2
	bra	.l
.d:	tst.l	d1
	beq	.r
	divu	d1,d5
	divu	d1,d6
	divu	d1,d7
	move.b	d5,(a2)
	move.b	d6,1(a2)
	move.b	d7,2(a2)
.r:	movem.l	(sp)+,d2-d4/a0
	rts

; d4 = a box -> d0.l = its score (the widest axis' extent x its weight; 0 for a single entry), d1 = that axis.
; Keeps d4-d7.
ren_box_score:
	movem.l	d4-d7,-(sp)
	lea	ren_box,a0
	lsl.w	#2,d4
	move.w	(a0,d4.w),d2
	move.w	2(a0,d4.w),d3
	move.w	d3,d0
	sub.w	d2,d0
	cmp.w	#2,d0
	blt	.zero
	lea	ren_ent,a1
	lea	ren_mm,a2		; minima L a b, maxima L a b (words)
	move.l	#$00FF00FF,(a2)
	move.w	#$00FF,4(a2)
	clr.l	6(a2)
	clr.w	10(a2)
	moveq	#0,d6			; weight
.l:	move.w	d2,d0
	lsl.w	#3,d0
	lea	(a1,d0.w),a0
	add.w	4(a0),d6
	moveq	#0,d7
.ax:	moveq	#0,d0
	move.b	(a0,d7.w),d0
	move.w	d7,d1
	add.w	d1,d1
	cmp.w	(a2,d1.w),d0
	bhs	.n1
	move.w	d0,(a2,d1.w)
.n1:	cmp.w	6(a2,d1.w),d0
	bls	.n2
	move.w	d0,6(a2,d1.w)
.n2:	addq.w	#1,d7
	cmp.w	#3,d7
	bne	.ax
	addq.w	#1,d2
	cmp.w	d3,d2
	blo	.l
	moveq	#0,d0			; the widest axis
	moveq	#0,d1
	moveq	#0,d7
.w:	move.w	d7,d2
	add.w	d2,d2
	move.w	6(a2,d2.w),d3
	sub.w	(a2,d2.w),d3
	cmp.w	d0,d3
	bls	.wn
	move.w	d3,d0
	move.w	d7,d1
.wn:	addq.w	#1,d7
	cmp.w	#3,d7
	bne	.w
	mulu	d6,d0
	movem.l	(sp)+,d4-d7
	rts
.zero:	moveq	#0,d0
	moveq	#0,d1
	movem.l	(sp)+,d4-d7
	rts

; d4 = a box, d6 = an axis (0 L, 1 a, 2 b): its entries sorted on it (a counting sort through ren_tmp)
ren_box_sort:
	movem.l	d0-d7/a0-a3,-(sp)
	lea	ren_box,a0
	move.w	d4,d0
	lsl.w	#2,d0
	move.w	(a0,d0.w),d2
	move.w	2(a0,d0.w),d3
	lea	ren_cnt,a2		; 256 words
	moveq	#128-1,d0
.cc:	clr.l	(a2)+
	dbf	d0,.cc
	lea	ren_cnt,a2
	lea	ren_ent,a1
	move.w	d2,d0
.c1:	move.w	d0,d1
	lsl.w	#3,d1
	add.w	d6,d1
	moveq	#0,d5
	move.b	(a1,d1.w),d5
	add.w	d5,d5
	addq.w	#1,(a2,d5.w)
	addq.w	#1,d0
	cmp.w	d3,d0
	blo	.c1
	move.w	d2,d1			; the starts (prefix sums from the box's first)
	moveq	#0,d0
.ps:	move.w	(a2),d5
	move.w	d1,(a2)+
	add.w	d5,d1
	addq.w	#1,d0
	cmp.w	#256,d0
	bne	.ps
	lea	ren_cnt,a2
	lea	ren_tmp,a3
	move.w	d2,d0
.c2:	move.w	d0,d1
	lsl.w	#3,d1
	move.w	d1,d7
	add.w	d6,d7
	moveq	#0,d5
	move.b	(a1,d7.w),d5
	add.w	d5,d5
	move.w	(a2,d5.w),d7		; its place
	addq.w	#1,(a2,d5.w)
	lsl.w	#3,d7
	move.l	(a1,d1.w),(a3,d7.w)
	move.l	4(a1,d1.w),4(a3,d7.w)
	addq.w	#1,d0
	cmp.w	d3,d0
	blo	.c2
	move.w	d2,d0			; back
.c3:	move.w	d0,d1
	lsl.w	#3,d1
	move.l	(a3,d1.w),(a1,d1.w)
	move.l	4(a3,d1.w),4(a1,d1.w)
	addq.w	#1,d0
	cmp.w	d3,d0
	blo	.c3
	movem.l	(sp)+,d0-d7/a0-a3
	rts

; a round of k-means: each entry to its nearest centre (the entry's byte 3), the centres the means
ren_kmeans:
	movem.l	d0-d7/a0-a6,-(sp)
	move.w	ren_nent,d7
	beq	.r
	lea	ren_ent,a6
	subq.w	#1,d7
.a:	move.l	a6,a0
	bsr	ren_nearest
	move.b	d1,3(a6)
	addq.l	#ENT,a6
	dbf	d7,.a
	lea	ren_ksum,a0		; per centre: L, a, b, weight (longs)
	moveq	#16*4-1,d0
.kc:	clr.l	(a0)+
	dbf	d0,.kc
	lea	ren_ent,a6
	move.w	ren_nent,d7
	subq.w	#1,d7
	lea	ren_ksum,a1
.s:	moveq	#0,d0
	move.b	3(a6),d0
	lsl.w	#4,d0
	lea	(a1,d0.w),a0
	moveq	#0,d1
	move.w	4(a6),d1
	add.l	d1,12(a0)
	moveq	#0,d2
	move.b	(a6),d2
	mulu	d1,d2
	add.l	d2,(a0)
	moveq	#0,d2
	move.b	1(a6),d2
	mulu	d1,d2
	add.l	d2,4(a0)
	moveq	#0,d2
	move.b	2(a6),d2
	mulu	d1,d2
	add.l	d2,8(a0)
	addq.l	#ENT,a6
	dbf	d7,.s
	lea	ren_cent+4,a2
	lea	ren_ksum+16,a1
	move.w	ren_ncent,d7
	subq.w	#1,d7
	bmi	.r
.m:	move.l	12(a1),d1
	beq	.mn			; (no entry: kept)
	move.l	(a1),d0
	divu	d1,d0
	move.b	d0,(a2)
	move.l	4(a1),d0
	divu	d1,d0
	move.b	d0,1(a2)
	move.l	8(a1),d0
	divu	d1,d0
	move.b	d0,2(a2)
.mn:	addq.l	#4,a2
	lea	16(a1),a1
	dbf	d7,.m
.r:	movem.l	(sp)+,d0-d7/a0-a6
	rts

; the representatives: per centre the entry nearest it (L1); its pen (ren_hpen); none: -1 (black)
ren_reps:
	lea	ren_rep,a3
	move.w	#-1,(a3)+		; (index 0: black)
	lea	ren_cent+4,a2
	moveq	#1,d6
.c:	cmp.w	#15,d6
	bhi	.r
	move.w	#-1,(a3)
	cmp.w	ren_ncent,d6
	bhi	.n
	move.w	#$7FFF,d5		; the best distance
	lea	ren_ent,a1
	move.w	ren_nent,d7
	subq.w	#1,d7
	bmi	.n
.e:	moveq	#0,d0
	moveq	#3-1,d4
.ax:	moveq	#0,d1
	moveq	#0,d2
	move.b	(a1,d4.w),d1
	move.b	(a2,d4.w),d2
	sub.w	d2,d1
	bpl	.p
	neg.w	d1
.p:	add.w	d1,d0
	dbf	d4,.ax
	cmp.w	d5,d0
	bhs	.en
	move.w	d0,d5
	move.w	6(a1),d1		; the colour
	add.w	d1,d1
	lea	ren_hpen,a0
	move.w	(a0,d1.w),(a3)
.en:	addq.l	#ENT,a1
	dbf	d7,.e
.n:	addq.l	#2,a3
	addq.l	#4,a2
	addq.w	#1,d6
	bra	.c
.r:	rts

; ======== layers 3-5 ========

; What changed.  The order of the enabled layers 3-5 (all composed again); layer 5's bank (a new scene); layer 3's and 4's banks and
; layer 3's scroll (their non-empty cells, before and after); the tile words (their cells; 64 or more of layer 5's: a
; new scene).
ren_bg_check:
	lea	vio+VIO_CTL,a0
	lea	ren_bgpar,a1
	bsr	ren_bg_order		; the enabled layers 3-5 top first: composed again when that order changes
	moveq	#0,d0
	move.w	ren_bgkey,d0
	lea	ren_bgpar,a1
	cmp.l	4(a1),d0
	beq	.p
	move.l	d0,4(a1)
	st	ren_all
	addq.l	#1,ren_sc_pri
	lea	vio+VIO_CTL,a0
.p:	move.l	$18+2(a0),d0		; banks of 3-5
	and.l	#$00070707,d0
	move.l	8(a1),d1
	cmp.l	d1,d0
	beq	.b
	move.l	d0,8(a1)
	eor.l	d0,d1
	tst.b	d1			; layer 5
	beq	.b4
	st	ren_all
	st	ren_scene
	addq.l	#1,ren_sc_bank5
.b4:	lsr.l	#8,d1
	tst.b	d1			; layer 4
	beq	.b3
	bsr	ren_mark4_all
.b3:	lsr.l	#8,d1
	tst.b	d1			; layer 3
	beq	.b
	bsr	ren_mark3_all
.b:	move.l	12(a0),d0		; layer 3's scroll
	cmp.l	(a1),d0
	beq	.s
	bsr	ren_mark3_all		; (where it was)
	move.l	vio+VIO_CTL+12,ren_bgpar
	bsr	ren_mark3_all		; (and where it is)
.s:	tst.b	ren_all
	bne	.all
	ifd	TILE_FLAG
	tst.b	tile_written_fix	; the fixed layers (their writers say so)
	beq	.l3s
	endc
	lea	vio+VIO_TILE+$7010,a0
	lea	ren_tcopy4,a1
	ifd	TILE_ROWS
	lea	tile_fix_rows,a2
	endc
	bsr	ren_diff_fixed
	clr.w	ren_ndiff
	lea	vio+VIO_TILE+$7810,a0
	lea	ren_tcopy5,a1
	ifd	TILE_ROWS
	lea	tile_fix_rows+28,a2
	endc
	bsr	ren_diff_fixed
	cmp.w	#64,ren_ndiff
	blo	.l3s
	st	ren_scene		; (a new backdrop)
	addq.l	#1,ren_sc_tiles
.l3s:
	ifd	TILE_FLAG
	tst.b	tile_written		; layer 3 (as layers 0-2)
	beq	.r
	endc
	lea	vio+VIO_TILE+$6000,a0	; (compared a long at a time)
	lea	ren_tcopy3,a1
	move.w	#32*64/2-1,d7
	moveq	#0,d6			; the word index
.l3:	cmpm.l	(a0)+,(a1)+
	bne	.d3
.n3:	addq.w	#2,d6
	dbf	d7,.l3
.r:	rts
.d3:	move.w	-4(a0),d0
	cmp.w	-4(a1),d0
	beq	.d3b
	move.w	d0,-4(a1)
	bsr	ren_mark3
.d3b:	move.w	-2(a0),d0
	cmp.w	-2(a1),d0
	beq	.n3
	move.w	d0,-2(a1)
	addq.w	#1,d6
	bsr	ren_mark3
	subq.w	#1,d6
	bra	.n3
.all:	lea	vio+VIO_TILE+$6000,a0	; everything: the copies and every cell
	lea	ren_tcopy3,a1
	move.w	#32*64/2-1,d0
.c3:	move.l	(a0)+,(a1)+
	dbf	d0,.c3
	lea	vio+VIO_TILE+$7010,a0
	lea	ren_tcopy4,a1
	move.w	#36*28/2-1,d0
.c4:	move.l	(a0)+,(a1)+
	dbf	d0,.c4
	lea	vio+VIO_TILE+$7810,a0
	lea	ren_tcopy5,a1
	move.w	#36*28/2-1,d0
.c5:	move.l	(a0)+,(a1)+
	dbf	d0,.c5
	lea	ren_dirty,a0
	move.w	#NCELLS-1,d0
.dl:	st	(a0)+
	dbf	d0,.dl
	sf	ren_all
	st	ren_any
	rts

; a0 = a fixed layer's tile words, a1 = their copy: the changed words' cells dirty (ren_ndiff counts them).
; TILE_ROWS: a2 = the layer's 28 row flags (tile_fix_rows: the rows the translated writers wrote; tile_fix_all: all):
; only those rows are compared.
ren_diff_fixed:
	ifd	TILE_ROWS
	tst.b	tile_fix_all
	bne	.whole
	moveq	#0,d6
	moveq	#28-1,d5
.row:	tst.b	(a2)+
	beq	.skip
	moveq	#36/2-1,d7
.rl:	cmpm.l	(a0)+,(a1)+
	bne	.rd
.rn:	addq.w	#2,d6
	dbf	d7,.rl
	dbf	d5,.row
	rts
.skip:	lea	72(a0),a0
	lea	72(a1),a1
	add.w	#36,d6
	dbf	d5,.row
	rts
.rd:	bsr	.pair
	bra	.rn
.whole:
	endc
	move.w	#36*28/2-1,d7		; (a long at a time)
	moveq	#0,d6
.l:	cmpm.l	(a0)+,(a1)+
	bne	.d
.n:	addq.w	#2,d6
	dbf	d7,.l
	rts
.d:	bsr	.pair
	bra	.n
; the long before a0 / a1 differs: its words (d6 the first's index)
.pair:	move.w	-4(a0),d0
	cmp.w	-4(a1),d0
	beq	.p2
	move.w	d0,-4(a1)
	addq.w	#1,ren_ndiff
	bsr	ren_mark_fixed
.p2:	move.w	-2(a0),d0
	cmp.w	-2(a1),d0
	beq	.p3
	move.w	d0,-2(a1)
	addq.w	#1,ren_ndiff
	addq.w	#1,d6
	bsr	ren_mark_fixed
	subq.w	#1,d6
.p3:	rts

; d6.w = a word of a fixed layer (k: logical row k / 36, column k % 36): its cell (R = k % 36, C = 27 - k / 36) dirty
ren_mark_fixed:
	movem.l	d0-d2/a2,-(sp)
	moveq	#0,d0
	move.w	d6,d0
	divu	#36,d0
	move.l	d0,d1
	swap	d1			; R
	moveq	#27,d2
	sub.w	d0,d2			; C
	mulu	#CCOLS,d1
	add.w	d2,d1
	lea	ren_dirty,a2
	st	(a2,d1.w)
	st	ren_any
	movem.l	(sp)+,d0-d2/a2
	rts

; layer 4's non-empty cells dirty (its bank changed)
ren_mark4_all:
	movem.l	d0-d7/a0-a2,-(sp)
	lea	ren_tcopy4,a0
	lea	ren_nonempty,a1
	moveq	#0,d6
.l:	move.w	(a0)+,d0
	and.w	#$3FFF,d0
	cmp.w	#8192,d0
	bhs	.n
	tst.b	(a1,d0.w)
	beq	.n
	bsr	ren_mark_fixed
.n:	addq.w	#1,d6
	cmp.w	#36*28,d6
	bne	.l
	movem.l	(sp)+,d0-d7/a0-a2
	rts

; layer 3's non-empty cells dirty at its scroll in ren_bgpar (its copy's words)
ren_mark3_all:
	movem.l	d0-d7/a0-a2,-(sp)
	lea	ren_tcopy3,a0
	lea	ren_nonempty,a1
	moveq	#0,d6
.l:	move.w	(a0)+,d0
	and.w	#$3FFF,d0
	cmp.w	#8192,d0
	bhs	.n
	tst.b	(a1,d0.w)
	beq	.n
	bsr	ren_mark3
.n:	addq.w	#1,d6
	cmp.w	#32*64,d6
	bne	.l
	movem.l	(sp)+,d0-d7/a0-a2
	rts

; d6.w = a word of layer 3 (row ly = d6 >> 6, column lx = d6 & 63): its cells dirty.  Rows: X = 8 lx .. 8 lx + 7 at
; r = (8 lx + 332 + sx) & 511 on (two cell rows); the cell column: c0 = (-32 - sy - 8 ly) & 255 (aligned: sy % 8 = 0)
ren_mark3:
	movem.l	d0-d3/a2,-(sp)
	move.w	d6,d0
	and.w	#63,d0
	lsl.w	#3,d0
	add.w	#332,d0
	add.w	ren_bgpar,d0		; sx (the long: x hi, x lo, y hi, y lo)
	and.w	#511,d0			; r of the cell's first row
	move.w	d6,d1
	lsr.w	#6,d1
	lsl.w	#3,d1
	neg.w	d1
	sub.w	#32,d1
	sub.w	ren_bgpar+2,d1		; - sy
	and.w	#255,d1
	cmp.w	#PIC_W,d1
	bhs	.r
	lsr.w	#3,d1			; C
	lea	ren_dirty,a2
	moveq	#2-1,d3
.rows:	cmp.w	#PIC_H,d0
	bhs	.nx
	move.w	d0,d2
	lsr.w	#3,d2
	mulu	#CCOLS,d2
	add.w	d1,d2
	st	(a2,d2.w)
	st	ren_any
.nx:	addq.w	#7,d0
	and.w	#511,d0
	dbf	d3,.rows
.r:	movem.l	(sp)+,d0-d3/a2
	rts

; ---- the dirty cells into the clean buffer ----
ren_compose:
	tst.b	ren_any
	beq	.r
	sf	ren_any
	bsr	ren_bg_order		; ren_bgl: the layers top first
	lea	ren_dirty,a5
	moveq	#0,d7			; the cell
	clr.w	ren_cr
	clr.w	ren_cc
.l:	tst.b	(a5,d7.w)
	beq	.n
	sf	(a5,d7.w)
	bsr	ren_cell
	lea	ren_pend,a0		; every shown buffer copies it again
	move.b	#(1<<REN_NBUF)-1,(a0,d7.w)
	lea	ren_npend,a0
	moveq	#REN_NBUF-1,d0
.np:	addq.w	#1,(a0)+
	dbf	d0,.np
.n:	addq.w	#1,d7
	addq.w	#1,ren_cc
	cmp.w	#CCOLS,ren_cc
	bne	.l
	clr.w	ren_cc
	addq.w	#1,ren_cr
	cmp.w	#NCELLS,d7
	bne	.l
.r:	rts

; ren_bgl: up to 3 entries (layer.w, bank.w, 0.w) of the enabled layers 3-5 top first; ren_bgn = how many
ren_bg_order:
	lea	vio+VIO_CTL,a0
	lea	ren_bgl,a1
	clr.w	ren_bgn
	clr.w	ren_bgkey		; (the order as a number: 4 bits a layer, top first)
	moveq	#7,d2			; priority from 7 down
.pri:	moveq	#5,d1			; layers 5, 4, 3 (the higher number first at equal priority)
.lay:	move.b	$10(a0,d1.w),d0
	btst	#3,d0
	bne	.nx
	and.b	#7,d0
	cmp.b	d2,d0
	bne	.nx
	move.w	d1,(a1)+
	moveq	#7,d0
	and.b	$18(a0,d1.w),d0
	move.w	d0,(a1)+
	clr.w	(a1)+
	addq.w	#1,ren_bgn
	move.w	ren_bgkey,d0
	lsl.w	#4,d0
	or.w	d1,d0
	move.w	d0,ren_bgkey
.nx:	subq.w	#1,d1
	cmp.w	#3,d1
	bge	.lay
	dbf	d2,.pri
	rts

; d0.w = a layer (3-5), d5.w = a line of the cell ren_cr / ren_cc -> d1.w = the character there (8192 on: empty),
; d2.w = its row.  d0 d3-d7 a0-a6 kept.
ren_layer_line:
	move.l	a0,-(sp)
	cmp.w	#3,d0
	beq	.l3
	lea	vio+VIO_TILE+$7010,a0	; the fixed layers: word (27 - C) * 36 + R of $7010 / $7810
	cmp.w	#4,d0
	beq	.f
	lea	vio+VIO_TILE+$7810,a0
.f:	move.w	ren_cc,d1
	add.w	d1,d1
	add.w	ren_fixrow(pc,d1.w),a0	; (27 - C) * 72
	move.w	ren_cr,d1
	add.w	d1,d1
	move.w	(a0,d1.w),d1
	move.w	d5,d2
	bra	.c
.l3:	; X = (r - 332 - sx) & 511 (r = 8R + line), lx = X >> 3, the row X & 7; ly = ((-25 - sy - 8C) & 255) >> 3
	move.w	ren_cr,d2
	lsl.w	#3,d2
	add.w	d5,d2
	sub.w	#332,d2
	sub.w	ren_bgpar,d2
	and.w	#511,d2
	move.w	d2,d1
	lsr.w	#3,d1			; lx
	and.w	#7,d2
	move.w	d3,-(sp)
	move.w	ren_cc,d3
	lsl.w	#3,d3
	neg.w	d3
	sub.w	#25,d3
	sub.w	ren_bgpar+2,d3
	and.w	#255,d3
	lsr.w	#3,d3
	lsl.w	#6,d3
	add.w	d3,d1
	move.w	(sp)+,d3
	add.w	d1,d1
	lea	vio+VIO_TILE+$6000,a0
	move.w	(a0,d1.w),d1
.c:	and.w	#$3FFF,d1
	move.l	(sp)+,a0
	rts

ren_fixrow:
C	set	0
	rept	CCOLS
	dc.w	(27-C)*72
C	set	C+1
	endr

; d7.w = a cell (R * 28 + C, ren_cr / ren_cc): composed into the clean buffer and the cover planes.  a5, d7 kept.
; Each layer's 8 lines first (its character, layer 3's two when it is scrolled into the cell: masks and converted
; lines); then per line the layers bottom first: line = (line & ~mask) | (the layer's line & mask), the mask in all 4
; bytes (ren_rep4); movep.l writes the 4 plane bytes.
ren_cell:
	movem.l	d7/a5,-(sp)
	move.w	ren_cr,d6		; R
	move.w	ren_cc,d0		; C
	move.w	d6,d1			; the clean buffer: ren_ltab[8R] + (C >> 1) * 8 + (C & 1)
	lsl.w	#5,d1			; (8R longs)
	lea	ren_ltab+8*4,a0
	move.l	(a0,d1.w),d1
	move.w	d0,d2
	lsr.w	#1,d2
	lsl.w	#3,d2
	add.w	d2,d1
	moveq	#1,d2
	and.w	d0,d2
	add.w	d2,d1
	move.l	ren_clean,a6
	add.l	d1,a6
	move.w	d6,d1			; the cover planes: line 8R, byte C (R * 224 + C)
	add.w	d1,d1
	lea	ren_rowcell(pc),a0
	move.w	(a0,d1.w),d1
	lsl.w	#3,d1
	add.w	d0,d1
	move.w	d1,ren_covoff
	bsr	ren_cell_chars		; the layers' characters here
	bsr	ren_cell_one		; (one layer of one character here: done; Z clear)
	bne	.done
	; the layers' 8 lines (bottom first): ren_lm (8 masks a layer), ren_lp (8 converted longs a layer)
	clr.l	ren_cv3
	clr.l	ren_cv3+4
	clr.l	ren_cv4
	clr.l	ren_cv4+4
	lea	ren_lm,a4
	lea	ren_lp,a5
	moveq	#0,d4			; the layers prepared
	move.w	ren_bgn,d3
	subq.w	#1,d3
	bmi	.merge
	lea	ren_bgl,a3
	move.w	d3,d0
	add.w	d0,d0
	add.w	d3,d0
	add.w	d0,d0
	add.w	d0,a3			; (the bottom layer first: 6 bytes an entry)
.lay:	move.w	(a3),d0			; the layer: its characters here (ren_cch: A, its first row, the lines from A,
	sub.w	#3,d0			; B; empty ones as 16384)
	lsl.w	#3,d0
	lea	ren_cch,a0
	add.w	d0,a0
	move.w	(a0)+,d6		; A
	move.w	(a0)+,ren_lrow
	move.w	(a0)+,d7		; the lines from A
	move.w	(a0)+,ren_lchb		; B
	cmp.w	#16384,d6
	bne	.use
	cmp.w	#16384,ren_lchb
	beq	.cn			; (both empty: the layer is left out)
.use:	bsr	ren_cell_chr		; a0 = its converted lines, a1 = its masks (empty: zeros)
	move.w	ren_lrow,d2
	lea	(a1,d2.w),a1
	lsl.w	#2,d2
	add.w	d2,a0
	moveq	#0,d5			; the line
.cp:	cmp.w	d7,d5
	bne	.same
	move.w	ren_lchb,d6		; (layer 3: the next character from this line on)
	bsr	ren_cell_chr
.same:	move.b	(a1)+,(a4)+
	move.l	(a0)+,(a5)+
	addq.w	#1,d5
	cmp.w	#8,d5
	bne	.cp
	cmp.w	#3,(a3)			; the cover planes: layer 3's and 4's masks
	bne	.c4
	move.l	-8(a4),ren_cv3
	move.l	-4(a4),ren_cv3+4
.c4:	cmp.w	#4,(a3)
	bne	.cnt
	move.l	-8(a4),ren_cv4
	move.l	-4(a4),ren_cv4+4
.cnt:	addq.w	#1,d4
.cn:	subq.l	#6,a3
	dbf	d3,.lay
.merge:	; per line: the layers bottom first, line = (line & ~mask) | (the layer's line & mask), the mask in all 4 bytes
	lea	ren_rep4,a2
	cmp.w	#1,d4
	bne	.multi
	lea	ren_lm,a0		; one layer: its lines under its masks
	lea	ren_lp,a1
	moveq	#8-1,d5
.one:	moveq	#0,d0
	move.b	(a0)+,d0
	move.l	(a1)+,d6
	cmp.b	#$FF,d0
	beq	.o1
	lsl.w	#2,d0
	and.l	(a2,d0.w),d6
.o1:	movep.l	d6,0(a6)
	lea	STRIDE(a6),a6
	dbf	d5,.one
	bra	.cover
.multi:	moveq	#0,d5			; line
.line:	moveq	#0,d6
	lea	ren_lm,a0
	lea	ren_lp,a1
	add.w	d5,a0
	move.w	d5,d0
	lsl.w	#2,d0
	add.w	d0,a1
	move.w	d4,d3
	subq.w	#1,d3
	bmi	.out
.ml:	moveq	#0,d0
	move.b	(a0),d0
	beq	.mn
	cmp.b	#$FF,d0
	bne	.part
	move.l	(a1),d6			; (opaque: the layer's line)
	bra	.mn
.part:	lsl.w	#2,d0
	move.l	(a2,d0.w),d0		; the mask x 4
	move.l	(a1),d1
	and.l	d0,d1
	not.l	d0
	and.l	d0,d6
	or.l	d1,d6
.mn:	addq.l	#8,a0
	lea	32(a1),a1
	dbf	d3,.ml
.out:	movep.l	d6,0(a6)
	lea	STRIDE(a6),a6
	addq.w	#1,d5
	cmp.w	#8,d5
	bne	.line
.cover:	bsr	ren_cell_cover
.done:	movem.l	(sp)+,d7/a5
	rts

; the cover planes of the cell ren_cr / ren_cc from ren_cv3 / ren_cv4 (written when the cell has cover now or had
; before: ren_cellcov)
ren_cell_cover:
	move.l	ren_cv3,d0
	or.l	ren_cv3+4,d0
	or.l	ren_cv4,d0
	or.l	ren_cv4+4,d0
	sne	d1
	lea	ren_cellcov,a0
	move.w	ren_cr,d2
	add.w	d2,d2
	lea	ren_rowcell(pc),a1
	move.w	(a1,d2.w),d2
	add.w	ren_cc,d2
	move.b	(a0,d2.w),d3
	move.b	d1,(a0,d2.w)
	or.b	d1,d3
	beq	.done
	lea	ren_cov3,a3
	lea	ren_cov4,a5
	move.w	ren_covoff,d0
	add.w	d0,a3
	add.w	d0,a5
	lea	ren_cv3,a0
	lea	ren_cv4,a1
	moveq	#8-1,d5
.cv:	move.b	(a0)+,(a3)
	move.b	(a1)+,(a5)
	lea	CCOLS(a3),a3
	lea	CCOLS(a5),a5
	dbf	d5,.cv
.done:	rts
; d6.w = a character, the layer's bank at 2(a3) -> a0 = its converted lines, a1 = its masks (an empty one: zeros)
ren_cell_chr:
	cmp.w	#8192,d6			; (16384: empty)
	bhs	.empty
	lea	ren_nonempty,a1
	tst.b	(a1,d6.w)
	beq	.empty
	movem.l	d0-d1,-(sp)
	move.w	d6,d1
	move.w	2(a3),d0
	bsr	ren_cimg
	lea	ren_mask,a1
	moveq	#0,d0
	move.w	d6,d0
	lsl.l	#3,d0
	add.l	d0,a1
	movem.l	(sp)+,d0-d1
	rts
.empty:	lea	ren_zero32,a0
	lea	ren_zero32,a1
	rts

; ren_cell's direct way: when only one layer has pixels in the cell and from one character (fixed, or layer 3's rows
; not scrolled across two), its lines from the converted character straight into the clean buffer (a6), under its
; masks; the cover planes as ren_cell's.  Z set when not done (ren_cell then merges).
ren_cell_one:
	lea	ren_bgl,a3
	move.w	ren_bgn,d3
	subq.w	#1,d3
	bmi	.no
	moveq	#0,d4			; the layers with pixels here
	sub.l	a2,a2
.l:	move.w	(a3),d0
	sub.w	#3,d0
	lsl.w	#3,d0
	lea	ren_cch,a0
	add.w	d0,a0
	cmp.w	#16384,(a0)
	bne	.has
	cmp.w	#16384,6(a0)
	beq	.n
.has:	addq.w	#1,d4
	move.l	a0,a2			; (its ren_cch)
	move.l	a3,a5			; (its ren_bgl entry)
.n:	addq.l	#6,a3
	dbf	d3,.l
	cmp.w	#1,d4
	bne	.no
	cmp.w	#8,4(a2)		; (one character for all 8 lines)
	bne	.no
	move.w	(a2),d1			; its converted lines, its masks
	move.w	2(a5),d0
	bsr	ren_cimg
	moveq	#0,d0
	move.w	d1,d0
	lsl.l	#3,d0
	lea	ren_mask,a1
	add.l	d0,a1
	lea	ren_rep4,a2
	move.l	a1,a4			; (the masks again: the cover planes)
	moveq	#8-1,d5
.one:	moveq	#0,d0
	move.b	(a1)+,d0
	move.l	(a0)+,d6
	cmp.b	#$FF,d0
	beq	.o1
	lsl.w	#2,d0
	and.l	(a2,d0.w),d6
.o1:	movep.l	d6,0(a6)
	lea	STRIDE(a6),a6
	dbf	d5,.one
	clr.l	ren_cv3			; the cover planes: this layer's masks when it is 3 or 4
	clr.l	ren_cv3+4
	clr.l	ren_cv4
	clr.l	ren_cv4+4
	move.w	(a5),d0
	cmp.w	#3,d0
	bne	.c4
	move.l	(a4),ren_cv3
	move.l	4(a4),ren_cv3+4
.c4:	cmp.w	#4,d0
	bne	.cv
	move.l	(a4),ren_cv4
	move.l	4(a4),ren_cv4+4
.cv:	bsr	ren_cell_cover
	moveq	#1,d0			; (done: Z clear)
	rts
.no:	moveq	#0,d0
	rts

; the cell ren_cr / ren_cc -> ren_cch: per layer 3, 4, 5 (8 bytes each): A (the character at its line 0; 16384 when
; empty), A's row at line 0, the lines from A, B (layer 3: the character from that line on; the fixed ones: 16384).
; Uses d0-d2 a0-a1.
ren_cell_chars:
	lea	ren_cch,a1
	move.w	ren_cr,d0		; layer 3: X = (8R - 332 - sx) & 511, lx = X >> 3, its row X & 7
	lsl.w	#3,d0
	sub.w	#332,d0
	sub.w	ren_bgpar,d0
	and.w	#511,d0
	moveq	#7,d1
	and.w	d0,d1
	lsr.w	#3,d0
	move.w	ren_cc,d2		; ly = ((-25 - sy - 8C) & 255) >> 3
	lsl.w	#3,d2
	neg.w	d2
	sub.w	#25,d2
	sub.w	ren_bgpar+2,d2
	and.w	#255,d2
	lsr.w	#3,d2
	lsl.w	#7,d2			; (128 bytes a row)
	lea	vio+VIO_TILE+$6000,a0
	add.w	d2,a0
	add.w	d0,d0
	move.w	(a0,d0.w),d2		; A
	bsr	.empty
	move.w	d2,(a1)+
	move.w	d1,(a1)+		; its row
	moveq	#8,d2
	sub.w	d1,d2
	move.w	d2,(a1)+		; the lines from A
	moveq	#-1,d2			; B: the next column (on the 64)
	tst.w	d1
	beq	.nb
	addq.w	#2,d0
	and.w	#127,d0
	move.w	(a0,d0.w),d2
.nb:	bsr	.empty
	move.w	d2,(a1)+
	move.w	ren_cc,d0		; the fixed layers: word (27 - C) * 36 + R
	add.w	d0,d0
	lea	ren_fixrow(pc),a0
	move.w	(a0,d0.w),d0
	move.w	ren_cr,d1
	add.w	d1,d1
	add.w	d1,d0
	lea	vio+VIO_TILE+$7010,a0
	move.w	(a0,d0.w),d2
	bsr	.empty
	move.w	d2,(a1)+
	clr.w	(a1)+
	move.w	#8,(a1)+
	move.w	#16384,(a1)+
	lea	vio+VIO_TILE+$7810,a0
	move.w	(a0,d0.w),d2
	bsr	.empty
	move.w	d2,(a1)+
	clr.w	(a1)+
	move.w	#8,(a1)+
	move.w	#16384,(a1)+
	rts
; d2.w = a tile word -> its character, or 16384 when empty (beyond the ROMs or no pixel)
.empty:	and.w	#$3FFF,d2
	move.l	a0,-(sp)
	lea	ren_nonempty,a0
	tst.b	(a0,d2.w)
	move.l	(sp)+,a0
	bne	.e
	move.w	#16384,d2
.e:	rts

; d1.w = a character (< 8192), d0.w = a bank (0-7) -> a0 = its 8 converted lines (longs: plane 0 in bits 31-24 ...
; plane 3 in 7-0, column 0 the high bit of each byte).  A 2-way cache of CIMG_SETS sets (set = (character + bank *
; 1237) & (CIMG_SETS - 1)); the tag: the epoch (the colours' choice) << 16 | bank << 13 | character; a miss converts
; into the way not used last.  Keeps everything else.
CIMG_SETS = 2048
ren_cimg:
	movem.l	d0-d3/a1,-(sp)
	move.w	d0,d2
	moveq	#13,d3
	lsl.w	d3,d2
	or.w	d1,d2			; bank << 13 | character
	move.w	ren_epoch,d3
	swap	d3
	move.w	d2,d3			; the tag
	move.w	d0,d2
	add.w	d2,d2
	move.w	ren_bankmul(pc,d2.w),d2
	add.w	d1,d2
	and.w	#CIMG_SETS-1,d2		; the set
	lsl.w	#3,d2
	lea	ren_ctag,a1
	cmp.l	(a1,d2.w),d3
	beq	.w0
	cmp.l	4(a1,d2.w),d3
	beq	.w1
	lsr.w	#3,d2			; a miss: the way not used last
	lea	ren_cway,a1
	bchg	#0,(a1,d2.w)
	beq	.n0
	lsl.w	#3,d2
	addq.w	#4,d2			; (way 1)
	bra	.new
.n0:	lsl.w	#3,d2
.new:	lea	ren_ctag,a1
	move.l	d3,(a1,d2.w)
	lea	ren_cimgs,a0
	ext.l	d2
	lsl.l	#3,d2			; (the entry * 32)
	add.l	d2,a0
	bsr	ren_cimg_make
	movem.l	(sp)+,d0-d3/a1
	rts
.w1:	addq.w	#4,d2
.w0:	lea	ren_cimgs,a0
	ext.l	d2
	lsl.l	#3,d2
	add.l	d2,a0
	movem.l	(sp)+,d0-d3/a1
	rts

ren_bankmul:
B	set	0
	rept	8
	dc.w	B*1237
B	set	B+1
	endr

; d1.w = a character, d0.w = a bank, a0 = the entry: its 8 converted lines made.  Keeps everything.
ren_cimg_make:
	movem.l	d0-d7/a0-a3,-(sp)
	move.w	d0,d5			; the bank's indices (ren_bmap: made once per bank and choice)
	add.w	d5,d5
	lea	ren_bmtag,a1
	move.w	ren_epoch,d6
	cmp.w	(a1,d5.w),d6
	beq	.mok
	move.w	d6,(a1,d5.w)
	bsr	ren_bmap_make
.mok:	move.w	d0,d5
	lsl.w	#8,d5
	lea	ren_bmap,a2
	add.w	d5,a2			; the bank's 256 indices
	lea	ren_chr,a1
	moveq	#0,d4
	move.w	d1,d4
	lsl.l	#6,d4
	add.l	d4,a1
	lea	ren_spread(pc),a3
	moveq	#8-1,d7
.ln:	moveq	#0,d6
	moveq	#8-1,d5
.px:	moveq	#0,d4
	move.b	(a1)+,d4
	move.b	(a2,d4.w),d4		; the index
	add.w	d4,d4
	add.w	d4,d4
	add.l	d6,d6
	or.l	(a3,d4.w),d6
	dbf	d5,.px
	move.l	d6,(a0)+
	dbf	d7,.ln
	movem.l	(sp)+,d0-d7/a0-a3
	rts

; an index -> its pixel at column 0 of a converted line (shifted down by the following 7)
ren_spread:
I	set	0
	rept	16
	dc.l	((I&1)<<24)|(((I>>1)&1)<<16)|(((I>>2)&1)<<8)|((I>>3)&1)
I	set	I+1
	endr

; d0.w = a bank: ren_bmap + bank * 256 = the indices of its pens $800 + bank * 256 + n
ren_bmap_make:
	movem.l	d0-d2/a0,-(sp)
	move.w	d0,d2
	lsl.w	#8,d2
	lea	ren_bmap,a0
	add.w	d2,a0
	add.w	#$800,d2
	move.w	#256-1,d1
.p:	move.w	d1,-(sp)
	move.w	d2,d0
	bsr	ren_pen_index
	move.b	d1,(a0)+
	move.w	(sp)+,d1
	addq.w	#1,d2
	dbf	d1,.p
	movem.l	(sp)+,d0-d2/a0
	rts

; ---- this buffer: the cells composed since its last picture, the last picture's damage ----
ren_restore:
	move.l	ren_dst,a1
	move.l	ren_clean,a0
	move.w	ren_cur,d6
	move.w	d6,d0			; the composed cells: many (a full composition) - the whole picture by the Blitter
	add.w	d0,d0
	lea	ren_npend,a2
	move.w	(a2,d0.w),d1
	clr.w	(a2,d0.w)
	tst.w	d1
	beq	.cdone
	cmp.w	#300,d1
	blo	.groups
	lea	ren_pend,a2
	move.w	#NCELLS-1,d0
.pc:	bclr	d6,(a2)+
	dbf	d0,.pc
	lea	$ffff8a20.w,a3
	move.w	#2,(a3)+		; source X increment
	move.w	#STRIDE-110,(a3)+	; source Y increment (56 words a line)
	move.l	ren_clean,d0
	add.l	#GUARD*STRIDE+PIC_BYTE,d0
	move.l	d0,(a3)+
	move.w	#$FFFF,(a3)+
	move.w	#$FFFF,(a3)+
	move.w	#$FFFF,(a3)+
	move.w	#2,(a3)+
	move.w	#STRIDE-110,(a3)+
	move.l	ren_dst,d0
	add.l	#GUARD*STRIDE+PIC_BYTE,d0
	move.l	d0,(a3)+
	move.w	#56,(a3)+		; X count
	move.w	#PIC_H,(a3)+		; Y count
	move.w	#$0203,$ffff8a3a.w
	clr.b	$ffff8a3d.w
	bsr	blit_go
	bra	.cdone
.groups:				; else: per 16-pixel group (two cells) with one of them composed: its 8 lines
	lea	ren_pend,a2
	move.l	ren_clean,a3
	add.l	#GUARD*STRIDE+PIC_BYTE,a3
	move.l	a1,a4
	add.l	#GUARD*STRIDE+PIC_BYTE,a4
	moveq	#CROWS-1,d7
.gr:	moveq	#CCOLS/2-1,d5
.gg:	move.b	(a2)+,d0
	or.b	(a2)+,d0
	btst	d6,d0
	beq	.gn
	bclr	d6,-1(a2)
	bclr	d6,-2(a2)
	move.l	a3,a5
	move.l	a4,a6
	moveq	#8-1,d2
.cc:	move.l	(a5),(a6)
	move.l	4(a5),4(a6)
	lea	STRIDE(a5),a5
	lea	STRIDE(a6),a6
	dbf	d2,.cc
.gn:	addq.l	#8,a3
	addq.l	#8,a4
	dbf	d5,.gg
	lea	8*STRIDE-CCOLS/2*8(a3),a3
	lea	8*STRIDE-CCOLS/2*8(a4),a4
	dbf	d7,.gr
.cdone:
	move.w	d6,d0			; the star words: 4 planes of a 16-pixel group
	mulu	#STAR_MAX*4+4,d0
	lea	ren_sdmg,a2
	add.l	d0,a2
	move.l	(a2)+,d7
	bra	.sn
.sl:	move.l	(a2)+,d0
	move.l	(a0,d0.l),(a1,d0.l)
	move.l	4(a0,d0.l),4(a1,d0.l)
.sn:	subq.l	#1,d7
	bpl	.sl
	move.w	d6,d0			; the sprite rectangles (the Blitter: a pass of the lines, 3 groups x 4 planes)
	mulu	#DMG_MAX*8+4,d0
	lea	ren_dmg,a2
	add.l	d0,a2
	move.l	(a2)+,d7
	beq	.r
	lea	$ffff8a20.w,a3
	move.w	#2,(a3)+		; source X increment
	move.w	#STRIDE-22,(a3)+	; source Y increment
	addq.l	#4,a3			; (source address)
	move.w	#$FFFF,(a3)+		; end masks
	move.w	#$FFFF,(a3)+
	move.w	#$FFFF,(a3)+
	move.w	#2,(a3)+		; destination X increment
	move.w	#STRIDE-22,(a3)+	; destination Y increment
	move.w	#12,$ffff8a36.w		; X count
	move.w	#$0203,$ffff8a3a.w	; HOP source, op source
	clr.b	$ffff8a3d.w		; no skew
.dl:	move.l	(a2)+,d0		; the first word's offset
	move.w	(a2)+,d1		; lines
	addq.l	#2,a2
	lea	(a0,d0.l),a3
	move.l	a3,$ffff8a24.w
	lea	(a1,d0.l),a3
	move.l	a3,$ffff8a32.w
	move.w	d1,$ffff8a38.w
	bsr	blit_go
	subq.l	#1,d7
	bne	.dl
.r:	rts

; ======== the stars ========

; Layers 0-2 by priority (lowest first: a higher one paints over), each where the layers 3-5 above it are
; transparent (ren_cov3 / ren_cov4; layer 5 is opaque everywhere: a star layer below it is not drawn).  Each layer's
; visible window of tile RAM is scanned: the picture's rows r show X = (r - 332 - adj - sx) & 511, so 37 columns lx
; from X0 = (-332 - adj - sx) & 511 (r0 = 8 j - (X0 & 7) for the j-th); its columns c show Y = (-25 - sy - c) & 511
; (sy % 8 = 0): the cell column C shows the row ly = (Y0 >> 3) - C, Y0 = (-25 - sy) & 511.  A non-empty cell's rows
; get their pixels' indices from the bank's map (ren_bmap: the star banks cycle, so no converted characters), merged
; under the shown pixels' mask.
ren_stars:
	move.w	ren_cur,d0
	mulu	#STAR_MAX*4+4,d0
	lea	ren_sdmg,a0
	add.l	d0,a0
	move.l	a0,ren_sdp
	clr.l	(a0)+
	move.l	a0,ren_sdw
	moveq	#0,d6			; priority
.pri:	moveq	#0,d5			; layer
.lay:	lea	vio+VIO_CTL,a0
	move.b	$10(a0,d5.w),d0
	btst	#3,d0
	bne	.nx
	and.b	#7,d0
	cmp.b	d6,d0
	bne	.nx
	bsr	ren_star_layer
.nx:	addq.w	#1,d5
	cmp.w	#3,d5
	bne	.lay
	addq.w	#1,d6
	cmp.w	#8,d6
	bne	.pri
	move.l	ren_sdw,d0		; the count
	sub.l	ren_sdp,d0
	subq.l	#4,d0
	lsr.l	#2,d0
	move.l	ren_sdp,a0
	move.l	d0,(a0)
	rts

; d5.w = a star layer, d6.w = its priority.  d5 d6 kept.
ren_star_layer:
	movem.l	d5-d6,-(sp)
	lea	vio+VIO_CTL,a0
	moveq	#0,d4			; which of the layers 3-5 cover it (bit 0: layer 3, bit 1: layer 4): enabled and
	moveq	#3,d1			; their priority above, or equal (their numbers are higher)
.cv:	move.b	$10(a0,d1.w),d0
	btst	#3,d0
	bne	.cn
	and.b	#7,d0
	cmp.b	d6,d0
	blo	.cn
	cmp.w	#5,d1
	beq	.none			; (layer 5 above: the star layer is hidden)
	moveq	#0,d2
	bset	d1,d2
	lsr.b	#3,d2
	or.b	d2,d4
.cn:	addq.w	#1,d1
	cmp.w	#6,d1
	bne	.cv
	move.b	d4,ren_scover
	moveq	#7,d0			; the bank and its indices (ren_bmap: made once per bank and choice of colours)
	and.b	$18(a0,d5.w),d0
	move.w	d0,ren_sbankn
	move.w	d0,d1
	add.w	d1,d1
	lea	ren_bmtag,a1
	move.w	ren_epoch,d2
	cmp.w	(a1,d1.w),d2
	beq	.mok
	move.w	d2,(a1,d1.w)
	bsr	ren_bmap_make
.mok:	lsl.w	#8,d0
	lea	ren_bmap,a1
	add.w	d0,a1
	move.l	a1,ren_sbmap
	move.w	d5,d0			; the window: X0, Y0
	lsl.w	#2,d0
	move.w	#-332,d1
	lea	ren_adj(pc),a1
	moveq	#0,d2
	move.b	(a1,d5.w),d2
	sub.w	d2,d1
	sub.w	(a0,d0.w),d1		; - sx
	and.w	#511,d1			; X0
	moveq	#7,d2
	and.w	d1,d2
	neg.w	d2
	move.w	d2,ren_sr0b		; r0 of the window's first column: -(X0 & 7)
	lsr.w	#3,d1
	move.w	d1,ren_slx0		; its lx
	move.w	#-25,d1
	sub.w	2(a0,d0.w),d1		; - sy
	and.w	#511,d1
	lsr.w	#3,d1
	move.w	d1,ren_sly		; the row ly of the cell column 0
	move.w	d5,d0			; the layer's tile words
	moveq	#13,d1
	lsl.w	d1,d0
	lea	vio+VIO_TILE,a5
	add.w	d0,a5
	move.l	a5,ren_slay
	move.l	ren_dst,a6
	move.l	ren_sdw,a3		; (the damage list: the groups' offsets)
	lea	ren_nonempty,a4
	clr.w	ren_sc			; the cell column C
.col:	move.w	ren_sc,d2		; the column's group in a line: (C >> 1) * 8, + 1 for an odd cell
	move.w	d2,d0
	lsr.w	#1,d0
	lsl.w	#3,d0
	and.w	#1,d2
	add.w	d2,d0
	move.w	d0,ren_sgrp
	move.w	ren_sly,d0		; its row: ly = ly0 - C (mod 64)
	sub.w	ren_sc,d0
	and.w	#63,d0
	lsl.w	#7,d0
	move.l	ren_slay,a5
	add.w	d0,a5			; the row's 64 words
	move.l	a5,ren_srow
	move.w	ren_slx0,d0		; from lx0: up to the row's end, then from its start (the wrap)
	add.w	d0,d0
	add.w	d0,a5
	moveq	#64,d6
	sub.w	ren_slx0,d6		; the words to the row's end
	cmp.w	#37,d6
	bls	.run
	moveq	#37,d6
.run:	move.w	d6,ren_srun
	moveq	#0,d7			; j: the window's column
	subq.w	#1,d6
.cell:	move.w	(a5)+,d3
	and.w	#$3FFF,d3
	tst.b	(a4,d3.w)
	bne	.vis
.cnx:	addq.w	#1,d7
	dbf	d6,.cell
	cmp.w	#37,d7
	beq	.cdone
	move.l	ren_srow,a5		; (the wrap: the rest from the row's start)
	moveq	#37-1,d6
	sub.w	d7,d6
	bra	.cell
.cdone:	addq.w	#1,ren_sc
	cmp.w	#CCOLS,ren_sc
	bne	.col
	move.l	a3,ren_sdw
.none:	movem.l	(sp)+,d5-d6
	rts
.vis:	; the cell: rows r0 = 8 j + ren_sr0b, columns 8C
	movem.l	d6-d7/a4-a5,-(sp)
	move.w	d7,d1
	lsl.w	#3,d1
	add.w	ren_sr0b,d1		; r0
	moveq	#0,d0			; its pens
	move.w	d3,d0
	lsl.l	#6,d0
	lea	ren_chr,a0
	add.l	d0,a0
	lea	ren_rowbits,a1
	move.b	(a1,d3.w),d4		; the rows with pixels (bit 7: row 0)
	moveq	#0,d0
	move.w	d3,d0
	lsl.l	#3,d0
	lea	ren_mask,a1
	add.l	d0,a1			; its masks
	move.w	ren_sgrp,d7		; the cell's group in the line
	move.l	ren_sbmap,a2
	lea	ren_onebit,a4
	moveq	#0,d6			; the cover: a layer above has pixels in one of the cell's two cell rows
	tst.b	ren_scover
	beq	.cf
	lea	ren_cellcov,a5
	move.w	d1,d2
	bmi	.cf1
	lsr.w	#3,d2
	add.w	d2,d2
	lea	ren_rowcell(pc),a5
	move.w	(a5,d2.w),d2
	add.w	ren_sc,d2
	lea	ren_cellcov,a5
	or.b	(a5,d2.w),d6
.cf1:	move.w	d1,d2
	addq.w	#7,d2
	bmi	.cf
	cmp.w	#PIC_H,d2
	bhs	.cf
	lsr.w	#3,d2
	add.w	d2,d2
	lea	ren_rowcell(pc),a5
	move.w	(a5,d2.w),d2
	add.w	ren_sc,d2
	lea	ren_cellcov,a5
	or.b	(a5,d2.w),d6
.cf:	moveq	#0,d3			; dr
.row:	add.b	d4,d4
	bcc	.rn
	move.w	d1,d5
	add.w	d3,d5			; r
	cmp.w	#PIC_H,d5
	bhs	.rn			; (outside: negative too)
	moveq	#0,d0
	move.b	(a1,d3.w),d0		; the mask
	tst.b	d6
	beq	.nc
	move.w	d5,d2			; the cover: the layers above at this line and cell
	add.w	d2,d2
	lea	ren_ctab,a5
	move.w	(a5,d2.w),d2
	add.w	ren_sc,d2
	btst	#0,ren_scover
	beq	.c3
	lea	ren_cov3,a5
	move.b	(a5,d2.w),d5
	not.b	d5
	and.b	d5,d0
.c3:	btst	#1,ren_scover
	beq	.c4
	lea	ren_cov4,a5
	move.b	(a5,d2.w),d5
	not.b	d5
	and.b	d5,d0
.c4:	move.w	d1,d5
	add.w	d3,d5
	tst.b	d0
	beq	.rn
.nc:	add.w	d5,d5			; the line's group: ren_ltab[r] + the cell's group
	add.w	d5,d5
	lea	ren_ltab+8*4,a5
	move.l	(a5,d5.w),d5
	add.w	d7,d5
	move.l	d5,d2
	and.w	#$FFFE,d2
	move.l	d2,(a3)+		; (the damage: the group)
	lea	(a6,d5.l),a5		; the byte of plane 0
	moveq	#0,d2
	move.b	(a4,d0.w),d2		; one pixel: its bit, else -1
	bmi	.multi
	move.w	d3,d5			; its pen: row * 8 + 7 - bit
	lsl.w	#3,d5
	addq.w	#7,d5
	sub.w	d2,d5
	moveq	#0,d0
	move.b	(a0,d5.w),d0
	move.b	(a2,d0.w),d0		; its index
	lsr.b	#1,d0
	bcc	.a0
	bset	d2,(a5)
	bra	.b0
.a0:	bclr	d2,(a5)
.b0:	lsr.b	#1,d0
	bcc	.a1
	bset	d2,2(a5)
	bra	.b1
.a1:	bclr	d2,2(a5)
.b1:	lsr.b	#1,d0
	bcc	.a2
	bset	d2,4(a5)
	bra	.b2
.a2:	bclr	d2,4(a5)
.b2:	lsr.b	#1,d0
	bcc	.a3
	bset	d2,6(a5)
	bra	.rn
.a3:	bclr	d2,6(a5)
	bra	.rn
.multi:	movem.l	d1/d3-d4/a1/a4,-(sp)	; several: their indices spread into the 4 plane bytes, merged under the mask
	move.w	d3,d2
	lsl.w	#3,d2
	lea	(a0,d2.w),a1		; the row's pens
	lea	ren_spread(pc),a4
	moveq	#0,d5
	moveq	#7,d1			; (the shift: 7 - column)
	move.b	d0,d4
.pp:	add.b	d4,d4
	bcc	.pn
	moveq	#0,d2
	move.b	(a1),d2
	move.b	(a2,d2.w),d2
	add.w	d2,d2
	add.w	d2,d2
	move.l	(a4,d2.w),d2
	lsl.l	d1,d2
	or.l	d2,d5
.pn:	addq.l	#1,a1
	subq.w	#1,d1
	tst.b	d4
	bne	.pp
	lea	ren_rep4,a1
	lsl.w	#2,d0
	move.l	(a1,d0.w),d0		; the shown pixels x 4
	not.l	d0
	movep.l	0(a5),d2
	and.l	d0,d2
	or.l	d5,d2
	movep.l	d2,0(a5)
	movem.l	(sp)+,d1/d3-d4/a1/a4
.rn:	addq.w	#1,d3
	tst.b	d4
	bne	.row
	movem.l	(sp)+,d6-d7/a4-a5
	move.l	a3,d0			; (the damage list full: no more stars)
	sub.l	ren_sdp,d0
	cmp.l	#STAR_MAX*4-32,d0
	blo	.cnx
	move.l	a3,ren_sdw
	movem.l	(sp)+,d5-d6
	rts

ren_adj:	dc.b	4,2,1,0
	even
ren_rowcell:
R	set	0
	rept	CROWS
	dc.w	R*CCOLS
R	set	R+1
	endr

; ======== the sprites ========
; Entries 0-126 in order (the arcade draws from 126 down and the first pixel drawn wins: the STE paints the other way
; round).  An entry (engine/namcos1.py draw_sprites, the flipped screen): rows r0 = 360 - x - (sizex - 1) with
; x = (-(b13 + (b12 & 1) << 8 + xoffs) - sizex) & $1FF, columns c0 = ((b15 + yoffs + 17) & $FF) - 32; the image
; (assets.py ren_spr) by row dr: arcade ix = tx + (flip x ? dr : sizex - 1 - dr) (the flips are inverted by the
; screen's), the turned row 31 - ix; column dc: iy = ty + (flip y ? sizey - 1 - dc : dc).
REN_SIZE:	dc.b	16,8,32,4
ren_sprites:
	move.w	ren_cur,d0
	mulu	#DMG_MAX*8+4,d0
	lea	ren_dmg,a0
	add.l	d0,a0
	move.l	a0,ren_dmp
	clr.l	(a0)+
	move.l	a0,ren_dmw
	lea	vio+VIO_SPR,a6
	bsr	ren_spr_offsets
	sf	ren_order		; (any sprite on the picture with a layer above it)
	lea	ren_slst,a5		; the entries on the picture: SL bytes each
	moveq	#0,d7
.pre:	movem.l	d7/a5-a6,-(sp)
	bsr	ren_spr_geom
	beq	.pn
	bsr	ren_spr_hide
	move.l	(sp)+,d7
	move.l	(sp),a5
	move.w	ren_sr0,(a5)+
	move.w	ren_sc0,(a5)+
	move.w	ren_ssx,(a5)+
	move.w	ren_ssy,(a5)+
	move.l	ren_skey,(a5)+
	move.w	ren_scol,(a5)+
	move.b	ren_hide,(a5)+
	move.b	ren_hall,(a5)+
	move.l	a5,(sp)
	move.l	d7,-(sp)
	tst.b	ren_hide
	bne	.any
	tst.b	ren_hall
	beq	.pn
.any:	st	ren_order
.pn:	movem.l	(sp)+,d7/a5-a6
	lea	16(a6),a6
	addq.w	#1,d7
	cmp.w	#127,d7
	bne	.pre
	move.l	a5,ren_slend
	tst.b	ren_order
	bne	.back
	lea	ren_slst,a5		; none: in order (the later wins)
.ent:	cmp.l	ren_slend,a5
	bhs	.r
	bsr	ren_sl_get
	sf	ren_hide
	sf	ren_hall
	move.l	a5,-(sp)
	bsr	ren_cache_get		; a0 = the image (rows.w, then per row mask.l, 4 plane .l)
	bsr	ren_draw
	move.l	(sp)+,a5
	lea	SL(a5),a5
	bra	.ent
.r:	rts
.back:	; the arcade's way: from entry 126 down, a pixel taken by the first opaque one (ren_taken), shown when no layer
	; above that sprite covers it
	lea	ren_taken,a0
	move.w	#PIC_H*CCOLS/4-1,d0
.tc:	clr.l	(a0)+
	dbf	d0,.tc
	move.l	ren_slend,a5
.b:	cmp.l	#ren_slst,a5
	bls	.r
	lea	-SL(a5),a5
	bsr	ren_sl_get
	move.l	a5,-(sp)
	bsr	ren_cache_get
	bsr	ren_draw
	move.l	(sp)+,a5
	bra	.b

SL = 16				; (ren_slst: r0, c0, rows, columns, the key.l, colour, hide.b, hall.b)
; a5 = an entry of ren_slst -> the ren_s* variables
ren_sl_get:
	move.w	(a5),ren_sr0
	move.w	2(a5),ren_sc0
	move.w	4(a5),ren_ssx
	move.w	6(a5),ren_ssy
	move.l	8(a5),ren_skey
	move.w	12(a5),ren_scol
	move.b	14(a5),ren_hide
	move.b	15(a5),ren_hall
	rts

; a6 = an entry: ren_hide = which of the layers 3 / 4 are above its priority (bit 0 / 1: enabled and their priority
; higher); ren_hall set when layer 5 (opaque everywhere) is above it.  (A hidden sprite pixel still takes the pixel
; from the sprites the arcade draws after it: ren_sprites paints in the arcade's order then.)
ren_spr_hide:
	sf	ren_hall
	moveq	#0,d2
	move.b	14(a6),d2
	lsr.b	#5,d2			; the sprite's priority
	lea	vio+VIO_CTL+$10,a0
	moveq	#0,d3
	moveq	#3,d1
.l:	move.b	(a0,d1.w),d0
	btst	#3,d0
	bne	.n
	and.b	#7,d0
	cmp.b	d2,d0
	bls	.n			; (at or below the sprite)
	cmp.w	#5,d1
	beq	.hid
	moveq	#0,d4
	bset	d1,d4
	lsr.b	#3,d4
	or.b	d4,d3
.n:	addq.w	#1,d1
	cmp.w	#6,d1
	bne	.l
	move.b	d3,ren_hide
	moveq	#1,d0			; (Z clear)
	rts
.hid:	st	ren_hall
	rts

; a3 = a line of a 1-bit plane (28 bytes: ren_cov3, ren_cov4, ren_taken), ren_sc0 = a sprite's first column c0 ->
; d0.l = the plane's bits at columns c0 .. c0 + 31 (bit 31 = c0; outside the picture: 0).  The bytes B0-B4 of the
; cells c0 >> 3 .. + 4: d0 = (B0 B1 B2 B3 << s) | (B4 >> (8 - s)), s = c0 & 7.  Uses d1 d4 d5.
ren_bits32:
	moveq	#0,d0
	move.w	ren_sc0,d1
	asr.w	#3,d1			; the first cell (may be negative)
	moveq	#5-1,d4
.c:	moveq	#0,d5
	cmp.w	#CCOLS,d1		; (unsigned: negative cells too)
	bhs	.z
	move.b	(a3,d1.w),d5
.z:	tst.w	d4
	beq	.last			; (B4 stays in d5)
	lsl.l	#8,d0
	or.b	d5,d0
	addq.w	#1,d1
	dbf	d4,.c
.last:	moveq	#7,d4
	and.w	ren_sc0,d4		; s
	lsl.l	d4,d0
	moveq	#8,d1
	sub.w	d4,d1
	lsr.b	d1,d5			; (s = 0: B4 >> 8 = 0)
	or.b	d5,d0
	rts

; a3 = a line of a 1-bit plane, d0.l = bits at columns c0 .. c0 + 31 (bit 31 = c0): ORed into it (the cells inside
; the picture).  Uses d1 d2 d4 d5.
ren_or32:
	moveq	#7,d4
	and.w	ren_sc0,d4		; s
	move.l	d0,d2
	lsr.l	d4,d2			; B0 B1 B2 B3
	moveq	#8,d1
	sub.w	d4,d1
	move.l	d0,d5
	lsl.l	d1,d5			; B4 in the low byte
	move.w	ren_sc0,d1
	asr.w	#3,d1
	rol.l	#8,d2
	moveq	#4-1,d4
.c:	cmp.w	#CCOLS,d1
	bhs	.n
	or.b	d2,(a3,d1.w)
.n:	rol.l	#8,d2
	addq.w	#1,d1
	dbf	d4,.c
	cmp.w	#CCOLS,d1
	bhs	.r
	or.b	d5,(a3,d1.w)
.r:	rts

; a6 = the sprite RAM: ren_xoffs / ren_yoffs
ren_spr_offsets:
	moveq	#0,d0
	move.b	$7F5(a6),d0
	moveq	#1,d1
	and.b	$7F4(a6),d1
	lsl.w	#8,d1
	add.w	d1,d0
	move.w	d0,ren_xoffs
	moveq	#0,d0
	move.b	$7F7(a6),d0
	move.w	d0,ren_yoffs
	rts

; a6 = an entry -> ren_sr0 / ren_sc0 (its top left), ren_ssx / ren_ssy (rows, columns), ren_skey / ren_scol; Z set
; when it is not on the picture
ren_spr_geom:
	moveq	#0,d0
	move.b	10(a6),d0		; attr1: size x 7-6, flip x 5, tx 4-3, code high 2-0
	move.w	d0,d1
	lsr.w	#6,d1
	lea	REN_SIZE(pc),a1
	move.b	(a1,d1.w),d1		; sizex
	ext.w	d1
	moveq	#0,d2
	move.b	14(a6),d2		; attr2: priority 7-5, ty 4-3, size y 2-1, flip y 0
	move.w	d2,d3
	lsr.w	#1,d3
	and.w	#3,d3
	move.b	(a1,d3.w),d3		; sizey
	ext.w	d3
	moveq	#0,d4			; x = (-(b13 + (b12 & 1) * 256 + xoffs) - sizex) & $1FF
	move.b	13(a6),d4
	btst	#0,12(a6)
	beq	.x8
	add.w	#256,d4
.x8:	add.w	ren_xoffs,d4
	neg.w	d4
	sub.w	d1,d4
	and.w	#$1FF,d4
	move.w	#361,d5			; r0 = 360 - x - (sizex - 1)
	sub.w	d4,d5
	sub.w	d1,d5
	move.w	d5,d4			; r0
	add.w	d1,d5
	ble	.out			; (wholly above)
	cmp.w	#PIC_H,d4
	bge	.out
	moveq	#0,d5			; c0 = ((b15 + yoffs + 17) & $FF) - 32
	move.b	15(a6),d5
	add.w	ren_yoffs,d5
	add.w	#17,d5
	and.w	#$FF,d5
	sub.w	#32,d5
	move.w	d5,d6
	add.w	d3,d6
	ble	.out			; (wholly left)
	cmp.w	#PIC_W,d5
	bge	.out
	move.w	d4,ren_sr0
	move.w	d5,ren_sc0
	move.w	d1,ren_ssx
	move.w	d3,ren_ssy
	moveq	#0,d6			; the cache key: code.w, (attr1 & $F8) << 8 | attr2 & $1F
	move.b	11(a6),d6
	moveq	#7,d4
	and.b	10(a6),d4
	lsl.w	#8,d4
	or.w	d4,d6
	swap	d6
	move.b	10(a6),d4
	and.w	#$F8,d4
	lsl.w	#8,d4
	move.b	14(a6),d4
	and.b	#$1F,d4
	move.w	d4,d6
	move.l	d6,ren_skey
	moveq	#0,d5
	move.b	12(a6),d5
	lsr.b	#1,d5			; the colour (0-127)
	move.w	d5,ren_scol
	moveq	#1,d0			; (Z clear)
	rts
.out:	moveq	#0,d0
	rts

; ---- the sprite cache: ren_skey / ren_scol -> a0 = the converted image (made now when missing) ----
ren_cache_clear:
	lea	ren_hash,a0
	move.w	#HASH_N-1,d0
.c:	clr.l	(a0)+
	dbf	d0,.c
	move.l	#ren_pool,ren_pool_ptr
	rts

ren_cache_get:
	move.l	ren_skey,d0
	move.l	d0,d2
	swap	d2
	eor.w	d0,d2
	add.w	ren_scol,d2
	mulu	#40503,d2
	lsr.w	#7,d2
	and.w	#HASH_N-1,d2
	lsl.w	#2,d2
	lea	ren_hash,a1
	lea	(a1,d2.w),a1
	move.l	(a1),a0
.find:	move.l	a0,d3
	beq	.new
	cmp.l	(a0),d0
	bne	.nx
	move.w	ren_scol,d3
	cmp.w	8(a0),d3
	bne	.nx
	lea	10(a0),a0		; (the image after the header)
	rts
.nx:	move.l	4(a0),a0
	bra	.find
.new:	move.l	ren_pool_ptr,a0		; header: key.l, next.l, colour.w; the image: rows.w, then 20 bytes a row
	move.l	a0,d3
	add.l	#10+2+32*20,d3
	cmp.l	#ren_pool+POOL_SIZE,d3
	bls	.fit
	movem.l	d0/a1,-(sp)
	bsr	ren_cache_clear
	movem.l	(sp)+,d0/a1
	move.l	ren_pool_ptr,a0
.fit:	move.l	d0,(a0)
	move.l	(a1),4(a0)
	move.l	a0,(a1)
	move.w	ren_scol,8(a0)
	lea	10(a0),a0
	move.l	a0,-(sp)
	bsr	ren_convert		; a0 -> past the image
	move.l	a0,ren_pool_ptr
	move.l	(sp)+,a0
	rts

; d5 = a row (dr), d4 = a column (dc) of the sprite ren_skey -> d1.w = its pen (4 bits; 15 transparent).  Keeps the
; other registers.
ren_spr_pen:
	movem.l	d0/d2-d3/a1,-(sp)
	move.w	ren_skey+2,d0
	move.w	d0,d1			; tx & ~(sizex - 1)
	lsr.w	#8,d1
	and.w	#$18,d1
	move.w	ren_ssx,d2
	subq.w	#1,d2
	not.w	d2
	and.w	d2,d1
	btst	#13,d0			; ix = tx + (flip x ? dr : sizex - 1 - dr); flip x: attr1 bit 5 clear
	bne	.fx
	add.w	d5,d1
	bra	.ix
.fx:	add.w	ren_ssx,d1
	subq.w	#1,d1
	sub.w	d5,d1
.ix:	moveq	#31,d2
	sub.w	d1,d2			; the turned row
	lsl.w	#4,d2
	move.w	d0,d1			; ty & ~(sizey - 1)
	and.w	#$18,d1
	move.w	ren_ssy,d3
	subq.w	#1,d3
	not.w	d3
	and.w	d3,d1
	btst	#0,d0			; iy = ty + (flip y ? sizey - 1 - dc : dc); flip y: attr2 bit 0 clear
	bne	.fy
	add.w	ren_ssy,d1
	subq.w	#1,d1
	sub.w	d4,d1
	bra	.iy
.fy:	add.w	d4,d1
.iy:	move.l	ren_skey,d0
	swap	d0
	and.w	#$7FF,d0
	bsr	ren_spr_image
	add.w	d2,a1
	move.w	d1,d2
	lsr.w	#1,d2
	move.b	(a1,d2.w),d2
	btst	#0,d1
	bne	.lo
	lsr.b	#4,d2
.lo:	moveq	#15,d1
	and.w	d2,d1
	movem.l	(sp)+,d0/d2-d3/a1
	rts

; d0.w = a sprite code -> a1 = its turned image (ren_spr; codes from 1536 on: zeros, pen 0 everywhere, as MAME's
; region beyond the ROMs).  Keeps everything else.
ren_spr_image:
	cmp.w	#1536,d0
	bhs	.z
	move.l	d0,-(sp)
	and.l	#$7FF,d0
	lsl.l	#8,d0
	add.l	d0,d0
	lea	ren_spr,a1
	add.l	d0,a1
	move.l	(sp)+,d0
	rts
.z:	lea	ren_spr_zero,a1
	rts

; the image of ren_skey / ren_scol into a0 (rows = sizex): per row the opaque mask.l (bit 31 = column 0) and the 4
; planes .l; pen 15 is transparent.  a0 -> past it.  Per row: the part's pens in column order into ren_upk (the
; flips: the turned row 31 - ix, the columns iy forwards or backwards), then 8 at a time through the colour's spread
; table (ren_sct: an index's plane bits at the bytes' bit 0, as ren_spread; pen 15: 0) into the 4 plane bytes and
; the mask byte of each 8-column group.
ren_convert:
	move.w	ren_scol,d0		; the colour's 16 indices -> spread longs
	lsl.w	#4,d0
	lea	ren_sct,a3
	lea	ren_spread(pc),a2
	moveq	#15-1,d3
.m:	bsr	ren_pen_index
	add.w	d1,d1
	add.w	d1,d1
	move.l	(a2,d1.w),(a3)+
	addq.w	#1,d0
	dbf	d3,.m
	clr.l	(a3)			; (pen 15)
	move.w	ren_ssx,(a0)+		; rows
	move.w	ren_skey+2,d7		; attr1 << 8 | attr2 & $1F
	move.w	d7,d0			; tx & ~(sizex - 1)
	lsr.w	#8,d0
	and.w	#$18,d0
	move.w	ren_ssx,d1
	subq.w	#1,d1
	not.w	d1
	and.w	d1,d0
	move.w	d0,ren_ctx
	move.w	d7,d0			; ty & ~(sizey - 1)
	and.w	#$18,d0
	move.w	ren_ssy,d1
	subq.w	#1,d1
	not.w	d1
	and.w	d1,d0
	move.w	d0,ren_cty
	move.l	ren_skey,d0		; the turned image
	swap	d0
	and.w	#$7FF,d0
	bsr	ren_spr_image
	moveq	#0,d5			; dr
.row:	move.w	ren_ctx,d1		; ix = tx + (flip x ? dr : sizex - 1 - dr); flip x: attr1 bit 5 clear
	btst	#13,d7
	bne	.fx
	add.w	d5,d1
	bra	.ix
.fx:	add.w	ren_ssx,d1
	subq.w	#1,d1
	sub.w	d5,d1
.ix:	moveq	#31,d2
	sub.w	d1,d2
	lsl.w	#4,d2
	lea	(a1,d2.w),a2		; the turned row (16 bytes, 2 pens a byte, the left one high)
	lea	ren_upk,a3		; its pens in column order
	move.w	ren_ssy,d4
	subq.w	#1,d4
	btst	#0,d7			; flip y: attr2 bit 0 clear: the columns backwards
	beq	.back
	move.w	ren_cty,d0		; forwards from ty (even)
	lsr.w	#1,d0
	add.w	d0,a2
	lsr.w	#1,d4			; (pairs; sizey 4 .. 32)
.fw:	move.b	(a2)+,d0
	move.b	d0,d1
	lsr.b	#4,d0
	move.b	d0,(a3)+
	and.b	#15,d1
	move.b	d1,(a3)+
	dbf	d4,.fw
	bra	.conv
.back:	move.w	ren_cty,d0		; backwards from ty + sizey - 1 (odd: a byte's low pen)
	add.w	ren_ssy,d0
	lsr.w	#1,d0
	add.w	d0,a2
	lsr.w	#1,d4
.bw:	move.b	-(a2),d0
	move.b	d0,d1
	and.b	#15,d1
	move.b	d1,(a3)+
	lsr.b	#4,d0
	move.b	d0,(a3)+
	dbf	d4,.bw
.conv:	clr.l	(a0)			; the row's record: mask, 4 planes (left-aligned)
	clr.l	4(a0)
	clr.l	8(a0)
	clr.l	12(a0)
	clr.l	16(a0)
	lea	ren_upk,a3
	lea	ren_sct,a4
	moveq	#0,d6			; the group
.grp:	moveq	#0,d1			; the planes
	moveq	#0,d2			; the mask
	moveq	#8-1,d4
	cmp.w	#4,ren_ssy
	bne	.px
	moveq	#4-1,d4
.px:	moveq	#0,d0
	move.b	(a3)+,d0
	add.l	d1,d1
	add.b	d2,d2
	cmp.b	#15,d0
	beq	.tr
	addq.b	#1,d2
	add.w	d0,d0
	add.w	d0,d0
	or.l	(a4,d0.w),d1
.tr:	dbf	d4,.px
	cmp.w	#4,ren_ssy
	bne	.st
	lsl.l	#4,d1			; (4 columns: left-aligned in the byte)
	lsl.b	#4,d2
.st:	move.b	d2,(a0,d6.w)		; the mask's byte
	rol.l	#8,d1
	move.b	d1,4(a0,d6.w)		; plane 0
	rol.l	#8,d1
	move.b	d1,8(a0,d6.w)
	rol.l	#8,d1
	move.b	d1,12(a0,d6.w)
	rol.l	#8,d1
	move.b	d1,16(a0,d6.w)		; plane 3
	addq.w	#1,d6
	move.w	d6,d0
	lsl.w	#3,d0
	cmp.w	ren_ssy,d0
	blo	.grp
	lea	20(a0),a0
	addq.w	#1,d5
	cmp.w	ren_ssx,d5
	bne	.row
	rts

; ---- a sprite onto the buffer: a0 = its image, ren_sr0 / ren_sc0 the picture row / column of its top left ----
; A HOG pass a line: X count 3 (the groups at x and the two after), Y count 4 (the planes), the source the row's
; plane longs (16-bit words, the skew shifts them), the end masks the row's opaque mask shifted; groups left of the
; picture (x < 48) or right of it (x >= 272) get end mask 0 (the side bands stay clean).  Rows from -32 and to 319
; are in the guard lines.
ren_draw:
	move.w	(a0)+,d7		; rows
	move.w	ren_sc0,d0
	add.w	#48,d0			; x
	moveq	#15,d6
	and.w	d0,d6			; the skew
	asr.w	#4,d0			; the first group (1-16)
	move.w	d0,d1
	moveq	#-1,d2			; the end mask of each group: 0 outside the picture's groups 3-16
	moveq	#-1,d3
	moveq	#-1,d4
	cmp.w	#3,d1
	bge	.g0
	moveq	#0,d2
.g0:	cmp.w	#2,d1
	bge	.g1
	moveq	#0,d3
.g1:	cmp.w	#16,d1
	ble	.g2
	moveq	#0,d2
.g2:	cmp.w	#15,d1
	ble	.g3
	moveq	#0,d3
.g3:	cmp.w	#14,d1
	ble	.g4
	moveq	#0,d4
.g4:	move.w	d2,ren_em1
	move.w	d3,ren_em2
	move.w	d4,ren_em3
	move.w	ren_sr0,d2		; the destination of the first row
	add.w	#GUARD,d2
	mulu	#STRIDE,d2
	lsl.w	#3,d1
	add.w	d1,d2			; + group * 8
	move.l	ren_dst,a1
	add.l	d2,a1
	move.l	ren_dmw,a2		; the damage: the first group's offset, the rows (3 groups)
	move.l	ren_dmp,a3
	cmp.l	#DMG_MAX-1,(a3)
	bhs	.full
	move.l	d2,(a2)+
	move.w	d7,(a2)+
	clr.w	(a2)+
	move.l	a2,ren_dmw
	addq.l	#1,(a3)
.full:	lea	$ffff8a20.w,a3		; the Blitter: source X inc 2, Y inc 0, destination X inc 8, Y inc -14 (the next plane)
	move.w	#2,(a3)+
	clr.w	(a3)+			; (NFSR: the last word is neither read nor stepped; the next plane follows)
	addq.l	#4,a3
	addq.l	#6,a3			; (end masks per row)
	move.w	#8,(a3)+
	move.w	#-14,(a3)+
	move.w	#3,$ffff8a36.w
	move.w	#$0203,$ffff8a3a.w
	move.w	ren_sr0,ren_hrow	; (the row the next mask is for)
	move.b	d6,d0			; skew, NFSR: the source's two words into three destination words
	or.b	#$40,d0
	move.b	d0,$ffff8a3d.w
	subq.w	#1,d7
.row:	move.l	(a0)+,d0		; the mask (bit 31 = column 0)
	tst.b	ren_order
	beq	.nh
	move.w	ren_hrow,d3		; (the arcade's order: rows inside the picture)
	bmi	.nh
	cmp.w	#PIC_H,d3
	bhs	.nh
	bsr	ren_row_order		; d0 = the pixels shown
.nh:	addq.w	#1,ren_hrow
	move.l	d0,d1			; w0 = mask >> (16 + s), w1 = (mask >> s) & $FFFF, w2 = (mask << (16 - s)) & $FFFF
	lsr.l	d6,d1
	move.l	d1,d2
	swap	d2
	moveq	#16,d3
	sub.w	d6,d3
	move.l	d0,d4
	lsl.l	d3,d4
	tst.w	d6
	bne	.s
	moveq	#0,d4
.s:	and.w	ren_em1,d2
	and.w	ren_em2,d1
	and.w	ren_em3,d4
	move.w	d2,$ffff8a28.w
	move.w	d1,$ffff8a2a.w
	move.w	d4,$ffff8a2c.w
	move.l	a0,$ffff8a24.w
	move.l	a1,$ffff8a32.w
	move.w	#4,$ffff8a38.w
	move.b	#$c0,$ffff8a3c.w	; HOG: 4 x 3 words (and the source's 8), well under 256 bus cycles
	lea	16(a0),a0
	lea	STRIDE(a1),a1
	dbf	d7,.row
	rts

; ren_draw's row d3 (inside the picture) in the arcade's order: d0 = the row's opaque pixels -> the ones shown: not
; taken by an entry before (ren_taken), not under a layer above the sprite (ren_hide: ren_cov3 / ren_cov4; ren_hall:
; all); then they all are taken.  Keeps everything else.
ren_row_order:
	movem.l	d1-d5/a3,-(sp)
	mulu	#CCOLS,d3
	lea	ren_taken,a3
	add.w	d3,a3
	move.l	d0,-(sp)		; (the opaque ones)
	bsr	ren_bits32
	move.l	d0,-(sp)		; taken
	move.l	4(sp),d0
	bsr	ren_or32		; (all of them taken now)
	move.l	(sp)+,d1
	move.l	(sp)+,d0
	not.l	d1
	and.l	d1,d0
	tst.b	ren_hall
	bne	.none
	btst	#0,ren_hide
	beq	.n3
	lea	ren_cov3,a3
	add.w	d3,a3
	move.l	d0,-(sp)
	bsr	ren_bits32
	move.l	d0,d1
	move.l	(sp)+,d0
	not.l	d1
	and.l	d1,d0
.n3:	btst	#1,ren_hide
	beq	.r
	lea	ren_cov4,a3
	add.w	d3,a3
	move.l	d0,-(sp)
	bsr	ren_bits32
	move.l	d0,d1
	move.l	(sp)+,d0
	not.l	d1
	and.l	d1,d0
.r:	movem.l	(sp)+,d1-d5/a3
	rts
.none:	moveq	#0,d0
	bra	.r

	section data,data
	even
ren_lab:	incbin	"ren_lab.bin"
ren_q8:		incbin	"ren_q8.bin"
ren_sqrt:	incbin	"ren_sqrt.bin"
	even
ren_chr:	incbin	"ren_chr.bin"
ren_mask:	incbin	"ren_mask.bin"
ren_spr:	incbin	"ren_spr.bin"
ren_epoch:	dc.w	1
ren_zero32:	dcb.l	8,0

	section bss,bss
	even
ren_pictures:	ds.l	1
ren_skipped:	ds.l	1
ren_choices:	ds.l	1
ren_ch_scene:	ds.l	1		; (the choices: new scenes, palettes that rested on colours that fit worse)
ren_ch_rest:	ds.l	1
ren_sc_pri:	ds.l	1		; (new scenes by: the priorities, layer 5's bank, layer 5's tiles)
ren_sc_bank5:	ds.l	1
ren_sc_tiles:	ds.l	1
ren_vbase:	ds.l	1
ren_bufp:	ds.l	REN_NBUF+1
ren_clean:	ds.l	1
ren_dst:	ds.l	1
ren_ck:		ds.l	1
ren_ck_chosen:	ds.l	1
ren_cur:	ds.w	1
ren_vbl_pal:	ds.w	16
ren_bpal:	ds.w	16*REN_NBUF
ren_bgpar:	ds.l	4		; layer 3's scroll, the priorities, the banks
ren_bgl:	ds.b	3*6
ren_bgn:	ds.w	1
ren_bgkey:	ds.w	1
ren_cr:		ds.w	1
ren_cc:		ds.w	1
ren_ndiff:	ds.w	1
ren_ncent:	ds.w	1
ren_err0:	ds.w	1
ren_qlast:	ds.w	1
ren_qtick:	ds.b	1
	even
ren_nent:	ds.w	1
ren_nbox:	ds.w	1
ren_mm:		ds.w	6
ren_cent:	ds.l	16		; (Oklab L a b of index 1-15)
ren_rep:	ds.w	16		; (the representative pens, -1 none)
ren_box:	ds.l	16
ren_shown:	ds.b	1
ren_ready:	ds.b	1
ren_prev:	ds.b	1
ren_black:	ds.b	1
ren_wblack:	ds.b	1
ren_allblack:	ds.b	1
ren_scene:	ds.b	1
ren_stable:	ds.b	1
ren_wait:	ds.b	1
ren_all:	ds.b	1
ren_any:	ds.b	1
ren_scover:	ds.b	1
	even
ren_srb:	ds.w	1
ren_scb:	ds.w	1
ren_sbankn:	ds.w	1
ren_sbmap:	ds.l	1
ren_sr0b:	ds.w	1
ren_slx0:	ds.w	1
ren_sly:	ds.w	1
ren_sc:		ds.w	1
ren_sgrp:	ds.w	1
ren_slay:	ds.l	1
ren_srow:	ds.l	1
ren_srun:	ds.w	1
ren_sdp:	ds.l	1
ren_sdw:	ds.l	1
ren_dmp:	ds.l	1
ren_dmw:	ds.l	1
ren_xoffs:	ds.w	1
ren_yoffs:	ds.w	1
ren_sr0:	ds.w	1
ren_sc0:	ds.w	1
ren_ssx:	ds.w	1
ren_ssy:	ds.w	1
ren_em1:	ds.w	1
ren_em2:	ds.w	1
ren_em3:	ds.w	1
ren_hrow:	ds.w	1
ren_hide:	ds.b	1
ren_hall:	ds.b	1
ren_order:	ds.b	1
	even
ren_slend:	ds.l	1
ren_slst:	ds.b	128*16
ren_spr_zero:	ds.b	512
ren_skey:	ds.l	1
ren_scol:	ds.w	1
ren_smap:	ds.b	16
ren_sct:	ds.l	16
ren_upk:	ds.b	32
ren_ctx:	ds.w	1
ren_cty:	ds.w	1
ren_pool_ptr:	ds.l	1
ren_hash:	ds.l	HASH_N
ren_rep4:	ds.l	256
ren_ksum:	ds.l	16*4
ren_lm:		ds.b	3*8		; (ren_cell: the layers' masks and lines)
ren_lp:		ds.l	3*8
ren_cv3:	ds.b	8
ren_cv4:	ds.b	8
ren_covoff:	ds.w	1
ren_lrow:	ds.w	1
ren_lchb:	ds.w	1
ren_cch:	ds.w	3*4
ren_cnt:	ds.w	256
ren_bmtag:	ds.w	8
ren_dirty:	ds.b	NCELLS
ren_pend:	ds.b	NCELLS
ren_cellcov:	ds.b	NCELLS		; (the cells whose cover planes are not 0)
	even
ren_npend:	ds.w	REN_NBUF	; (per buffer: cells composed since it was drawn)
ren_nonempty:	ds.b	16384		; (characters 8192 on: beyond the ROMs, empty)
ren_rowbits:	ds.b	8192
ren_onebit:	ds.b	256
ren_ltab:	ds.l	PIC_H+16
ren_ctab:	ds.w	PIC_H
ren_bmap:	ds.b	8*256
ren_lut:	ds.b	4096
	even
ren_hist:	ds.w	4096
ren_hpen:	ds.w	4096
ren_ent:	ds.b	NENT_MAX*ENT
ren_tmp:	ds.b	NENT_MAX*ENT
ren_palsnap:	ds.b	$4000
ren_ctag:	ds.l	2*CIMG_SETS	; (the converted characters' 2-way cache: tags, ways used last, the lines)
ren_cway:	ds.b	CIMG_SETS
ren_cimgs:	ds.b	2*CIMG_SETS*32
ren_tcopy3:	ds.b	$1000
ren_tcopy4:	ds.b	36*28*2
ren_tcopy5:	ds.b	36*28*2
ren_cov3:	ds.b	PIC_H*CCOLS
ren_cov4:	ds.b	PIC_H*CCOLS
ren_taken:	ds.b	PIC_H*CCOLS
ren_sdmg:	ds.b	REN_NBUF*(STAR_MAX*4+4)
ren_dmg:	ds.b	REN_NBUF*(DMG_MAX*8+4)
ren_pool:	ds.b	POOL_SIZE
ren_bufs:	ds.b	BUF_SIZE*(REN_NBUF+1)
