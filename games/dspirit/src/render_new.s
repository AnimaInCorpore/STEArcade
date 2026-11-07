; Dragon Spirit's picture on the STE (the simple renderer: every picture drawn whole): the arcade's 288 x 224 turned
; upright (ROT90, the game never flips) to 224 x 288, at x 48-271 of 320-pixel lines (the picture's edges on 16-pixel
; groups).  tools/stemodel.py is this file's picture in Python (exact against the reference), tools/assets.py turned the
; graphics, tools/render_test.py checks every pixel.
;
; Picture row r = arcade x, column c = 223 - arcade y.  A picture, bottom to top:
;   * black (the picture's area; the C116 window's outside stays so);
;   * per priority 0-7 the enabled layers of that priority (the lower number first), then the sprites of that priority
;     (the lower entry first);
;   * a layer from its turned image: the scrolling layers 0-3 as a ring of 512 rows (the tile RAM's logical x) by 256
;     columns (logical y turned, modulo 256: the 224 visible columns never collide), its tiles drawn into the ring when
;     they enter the window or change (per 8 x 8 slot a stamp: the tile word, the colours' epoch, the bank, which half
;     of y); the fixed layers 4, 5 as 288 x 224 images, their tiles drawn when they change.  Picture row r shows
;     image row (r + 44 + adj + sx) & 511, column c ring column (c - 248 - sy) & 255.  Per row the image's opaque runs
;     (its mask) are copied by the Blitter: HOG passes, HOP 2 / OP 3, the run's end masks, all 4 planes a pass;
;   * a sprite: converted per (code, part, flips, colour) into a cache, one HOG pass a row (Galaga '88's ren_convert /
;     ren_draw: its turned images and flips are Dragon Spirit's too); x = (b13 + (b12 & 1) 256 + xoffs) & $1FF,
;     y = ((17 - b15 - sizey - yoffs) & $FF) - 16, r0 = x - 73, c0 = 240 - y - sizey; colour $7F (shadow) not drawn.
;     Whole sprites, into GUARD lines above and below; groups outside the picture get end mask 0.  The C116 window
;     does not clip sprites here.
; Buffers: REN_NBUF shown buffers, 160 bytes a line, GUARD lines above and below the picture.
;
; Colours (Galaga '88's renderer, games/galaga88/src/render.s): 15 colours + black chosen per scene (samples of the
; layers' pixels and the sprites, the root of their counts, a median cut and k-means in Oklab); a pen's index is the
; nearest centre of its colour when they were chosen; an index's STE colour is the current colour of a representative
; pen.  A new scene: the enabled layers or their priorities change (black until the palette rests 2 pictures, at most
; REN_WAIT); chosen again every 16 pictures when the colours on the picture fit clearly worse than right after the
; choice.
;
; Interface: render_init (once, vio holds a state), render_frame (a picture: draws into a free buffer and publishes
; it), render_vbl (in the VBL: shows the published buffer, ren_vbl_pal its palette).  All registers kept.  Needs: vio
; (the virtual space $2E0000-$307FFF: the C116 at +0, tile RAM +$10000, sprite RAM +$1C800, CUS123 control +$1D000).

	ifnd	REN_NBUF
REN_NBUF = 2
	endc
	ifnd	CROP_TOP
CROP_TOP = 5			; the first picture row shown (277 lines: rows 5-281)
	endc
	ifnd	REN_WAIT
REN_WAIT = 6
	endc
LINEB = 424			; a buffer line: the terrain's 512 columns and its first 336 again (53 groups: any 320 + the
				; fine scroll's 16 in one line)
VP = 288			; the buffer's period: lines l and l + VP are twins (any SHOWN lines in one block)
TWIN = 512			; (the columns' twins)
PIC_H = 288
PIC_W = 320			; (the widened picture: the user, 2026-11-07; picture column = screen x)
X0 = 48				; (the arcade's picture column 0: x 48)
SHOWN = 277			; (the lines shown: picture rows CROP_TOP ..)
BUF_SIZE = 2*VP*LINEB
CROWS = 36			; cells: 36 rows of 28 (the colours' samples)
CCOLS = 28
NCELLS = CROWS*CCOLS
VIO_PAL = 0
VIO_TILE = $10000
VIO_SPR = $1C800
VIO_CTL = $1D000
POOL_SIZE = 64*1024		; the sprite cache
HASH_N = 512
NENT_MAX = 1024			; the colours a choice clusters
ENT = 8				; (bytes an entry: L a b centre, weight.w, colour.w)
NSPR = 1152			; (tools/assets.py: codes 1152-1279 = 1024-1151, from 1280 on zeros)
IMG_RB = 64			; a scrolling layer's image: a plane row's bytes (512 columns)
IMG_ROW = 4*IMG_RB		; an image row: the 4 plane rows
IMG_SIZE = 512*IMG_ROW
MSK_SIZE = 512*IMG_RB
FIX_RB = 28			; a fixed layer's image: 224 columns
FIX_ROW = 4*FIX_RB
FIX_SIZE = PIC_H*FIX_ROW
FMSK_SIZE = PIC_H*FIX_RB
NSLOT = 64*64			; the image's tile slots: 64 rows of 64
RL_SIZE = 64			; an image row's opaque runs: the count (or $FF: more than RL_MAX), RL_MAX (first, last) words
RL_MAX = 15
FSLOT = 36*28

	section text,code

; ---- init ----
render_init:
	movem.l	d0-d7/a0-a6,-(sp)
	lea	ren_bufs,a0		; the buffers black
	move.l	#(BUF_SIZE*REN_NBUF)/4-1,d0
.c:	clr.l	(a0)+
	subq.l	#1,d0
	bpl	.c
	lea	ren_bufs,a0
	lea	ren_bufp,a1
	moveq	#REN_NBUF-1,d0
.b:	move.l	a0,(a1)+
	add.l	#BUF_SIZE,a0
	dbf	d0,.b
	lea	ren_sxt,a0		; attr1 -> its size x
	lea	REN_SIZE(pc),a1
	moveq	#0,d0
.sx:	move.w	d0,d1
	lsr.w	#6,d1
	move.b	(a1,d1.w),(a0)+
	addq.w	#1,d0
	cmp.w	#256,d0
	bne	.sx
	lea	ren_tvok,a0		; (no buffer holds the terrain yet)
	clr.w	(a0)+
	clr.w	(a0)
	lea	ren_fsrc,a0		; the text layers' row shown at each picture row (tools/stemodel.py fixed_source_row):
	moveq	#0,d0			; rows CROP_TOP .. + 15 their rows 0-15, the last 24 shown their rows 264-287
.fs:	moveq	#-1,d1
	cmp.w	#CROP_TOP,d0
	blt	.fsw
	cmp.w	#CROP_TOP+16,d0
	bge	.fs1
	move.w	d0,d1
	sub.w	#CROP_TOP,d1
	bra	.fsw
.fs1:	cmp.w	#CROP_TOP+SHOWN-24,d0
	bge	.fs2
	move.w	d0,d1
	bra	.fsw
.fs2:	cmp.w	#CROP_TOP+SHOWN,d0
	bge	.fsw
	move.w	d0,d1
	add.w	#PIC_H-CROP_TOP-SHOWN,d1
.fsw:	move.w	d1,(a0)+
	addq.w	#1,d0
	cmp.w	#PIC_H,d0
	bne	.fs
	lea	ren_rdirty,a0		; every row's run list stale
	move.w	#(4*512+2*PIC_H)/4-1,d0
.rd:	move.l	#$01010101,(a0)+
	dbf	d0,.rd
	lea	ren_shtag,a0		; no tile drawn yet
	moveq	#6-1,d0
.st:	move.w	#-1,(a0)+
	dbf	d0,.st
	bsr	ren_cache_clear
	move.w	#-1,ren_l0bank		; (no colours chosen yet)
	move.b	#-1,ren_shown
	move.b	#-1,ren_ready
	move.b	#-1,ren_prev
	st	ren_scene		; (the first picture: a new scene)
	movem.l	(sp)+,d0-d7/a0-a6
	rts

REN_SIZE:	dc.b	16,8,32,4
ren_adj:	dc.b	4,2,1,0
	even

; REN_PHASES (the bench): the VBLs since the last mark into phase n (ren_ph, dspirit.s)
REN_PH	macro
	ifd	REN_PHASES
	move.l	d0,-(sp)
	move.l	cnt_vbls,d0
	sub.l	ren_phlast,d0
	add.l	d0,ren_ph+4*\1
	add.l	d0,ren_phlast
	move.l	(sp)+,d0
	endc
	endm

; ---- a picture ----
render_frame:
	movem.l	d0-d7/a0-a6,-(sp)
	REN_PH	9
	bsr	ren_pick		; d0 = a free buffer, or -1
	tst.w	d0
	bmi	.none
	move.w	d0,ren_cur
	lsl.w	#2,d0
	lea	ren_bufp,a0
	move.l	(a0,d0.w),ren_dst
	bsr	ren_window		; the C116 window: the rows and columns shown, or none (ren_wblack)
	bsr	ren_view		; the buffer's window: its first line, the columns' offset, the lines of the rows
	bsr	ren_layer_order		; the enabled layers bottom first (a new order: a new scene)
	REN_PH	0
	bsr	ren_palette		; the colours (a choice: every tile and sprite again); ren_black while a scene waits
	REN_PH	1
	sf	ren_tmode
	sf	ren_dmgon
	tst.b	ren_black
	bne	.blk
	bsr	ren_sprite_list		; the entries on the picture
	bsr	ren_lock_check		; the layers locked into layer 0 (their banks' maps ready)
	bsr	ren_mode		; the terrain mode (layer 0 the scrolled buffer's terrain) or the whole picture
	tst.b	ren_tmode
	bne	.tm
.blk:	bsr	ren_clear		; the picture black (the buffer's terrain lost)
	move.w	ren_cur,d0
	lea	ren_tvok,a0
	clr.b	(a0,d0.w)
	tst.b	ren_black
	bne	.pub
.tm:
	REN_PH	2
	moveq	#1,d7
.lb:	move.l	ren_lockset,d0
	btst	d7,d0
	beq	.lbn
	lea	vio+VIO_CTL+$18,a0
	moveq	#7,d0
	and.b	(a0,d7.w),d0
	move.w	d7,-(sp)
	bsr	ren_bank_ready
	move.w	(sp)+,d7
.lbn:	addq.w	#1,d7
	cmp.w	#4,d7
	bne	.lb
	lea	ren_lord,a5		; each enabled layer: its tiles, run lists, full rows (ren_lprep)
	move.w	ren_nlord,d6
	bra	.pn
.pl:	moveq	#0,d0
	move.b	(a5),d0
	bsr	ren_locked
	bne	.pln
	movem.l	d6/a5,-(sp)
	bsr	ren_lprep
	movem.l	(sp)+,d6/a5
.pln:	addq.l	#2,a5
.pn:	dbf	d6,.pl
	REN_PH	3
	bsr	ren_cover		; the rows a layer drawn later covers whole: not drawn
	tst.b	ren_tmode
	beq	.nt
	bsr	ren_terrain		; the terrain into the buffer (restored, rows scrolled in, rows changed; or all)
	st	ren_dmgon		; (what is drawn now is damage: restored from the twins next time)
.nt:	REN_PH	4
	moveq	#0,d7			; the priority
.pri:	lea	ren_lord,a5
	move.w	ren_nlord,d6
	bra	.ln
.lay:	move.b	1(a5),d0
	cmp.b	d7,d0
	bne	.lnx
	moveq	#0,d0
	move.b	(a5),d0
	bsr	ren_locked
	bne	.lnx
	tst.b	ren_tmode		; (the terrain mode: layer 0 is the buffer's)
	beq	.ld
	tst.w	d0
	beq	.lnx
.ld:	movem.l	d6-d7/a5,-(sp)
	bsr	ren_ldraw
	movem.l	(sp)+,d6-d7/a5
.lnx:	addq.l	#2,a5
.ln:	dbf	d6,.lay
	move.w	d7,-(sp)
	bsr	ren_sprites		; (those of priority d7)
	move.w	(sp)+,d7
	addq.w	#1,d7
	cmp.w	#8,d7
	bne	.pri
	REN_PH	5
	bsr	ren_lp_end
	bra	.pal
.pub:	bsr	ren_lp_end		; (black: no layer prepared, all forgotten)
.pal:	bsr	ren_buf_palette		; the buffer's palette (black when ren_black)
	move.w	ren_cur,d0		; the buffer's display: its window's first line, the fine scroll
	lsl.w	#2,d0
	lea	ren_bvoff,a0
	move.w	ren_vs,d1
	mulu	#LINEB,d1
	moveq	#0,d2
	move.w	ren_xo,d2
	lsr.w	#4,d2
	lsl.w	#3,d2
	add.l	d2,d1
	move.l	d1,(a0,d0.w)
	lsr.w	#2,d0
	lea	ren_bfine,a0
	moveq	#15,d1
	and.w	ren_xo,d1
	move.b	d1,(a0,d0.w)
	move.w	ren_cur,d0
	move.b	d0,ren_ready		; published
	addq.l	#1,ren_pictures
	REN_PH	6
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
	move.l	(a0,d0.w),a1		; the buffer + its window's offset (ren_bvoff: its first line, the fine scroll's group)
	lea	ren_bvoff,a0
	add.l	(a0,d0.w),a1
	move.l	a1,ren_vbase
	lea	ren_bfine,a0
	move.b	(a0,d1.w),ren_vfine
	ifnd	SIM
	move.l	a1,d0
	move.l	d0,-(sp)		; (high and middle byte first: writing them clears the STE's low byte)
	lsr.l	#8,d0
	move.b	d0,$ffff8203.w
	lsr.w	#8,d0
	move.b	d0,$ffff8201.w
	move.l	(sp)+,d0
	move.b	d0,$ffff820d.w
	move.b	ren_vfine,d0		; the fine scroll and the line's rest: (LINEB - 160) / 2 words, 4 fewer with a scroll
	move.b	d0,$ffff8265.w
	beq	.w0
	move.b	#(LINEB-168)/2,$ffff820f.w
	bra	.w1
.w0:	move.b	#(LINEB-160)/2,$ffff820f.w
.w1:
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

; ---- the C116 window (namcos1.py render_raw): x0 = max(73, reg0 - 1) .. x1 = min(360, reg1 - 2), y0 = max(16,
; reg2 - $11) .. y1 = min(239, reg3 - $12); the picture's rows x0 - 73 .. x1 - 73 and the rows shown (ren_rmin /
; ren_rmax), columns 239 - y1 .. 239 - y0 + X0 (ren_cmin / ren_cmax: screen x; the arcade's whole window: the whole
; width, tools/stemodel.py clip_wide); empty: ren_wblack ----
ren_window:
	lea	vio+VIO_PAL+$1800,a0	; (the registers: the C116's plane 3, words 0-3)
	move.w	(a0),d0
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
	sub.w	#73,d0
	sub.w	#73,d1
	cmp.w	#CROP_TOP,d0
	bge	.r0
	moveq	#CROP_TOP,d0
.r0:	cmp.w	#CROP_TOP+SHOWN-1,d1
	ble	.r1
	move.w	#CROP_TOP+SHOWN-1,d1
.r1:	cmp.w	d1,d0
	bgt	.black
	move.w	d0,ren_rmin
	move.w	d1,ren_rmax
	move.w	4(a0),d0
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
	move.w	#239,d2
	sub.w	d1,d2			; c0
	move.w	#239,d3
	sub.w	d0,d3			; c1
	tst.w	d2
	bne	.part
	cmp.w	#223,d3
	bne	.part
	clr.w	ren_cmin
	move.w	#PIC_W-1,ren_cmax
	sf	ren_wblack
	rts
.part:	add.w	#X0,d2
	add.w	#X0,d3
	move.w	d2,ren_cmin
	move.w	d3,ren_cmax
	sf	ren_wblack
	rts
.black:	st	ren_wblack
	rts

; ---- the picture black (the window's SHOWN lines, the 21 groups from the columns' offset): HOG passes of 3 lines (84
; words each: 252 bus cycles), HOP 0 / OP 0 ----
ren_clear:
	lea	$ffff8a28.w,a0
	move.w	#-1,(a0)+
	move.w	#-1,(a0)+
	move.w	#-1,(a0)+
	move.w	#2,(a0)+		; destination X inc
	move.w	#LINEB-2*83,(a0)+	; Y inc
	move.w	ren_vs,d0
	mulu	#LINEB,d0
	moveq	#0,d1
	move.w	ren_xo,d1
	lsr.w	#4,d1
	lsl.w	#3,d1
	add.l	d1,d0
	add.l	ren_dst,d0
	move.l	d0,(a0)+
	move.w	#84,(a0)+		; X count
	clr.w	$ffff8a3a.w		; HOP 0, OP 0
	clr.b	$ffff8a3d.w
	moveq	#(SHOWN+2)/3-1,d0
.l:	move.w	#3,$ffff8a38.w
	move.b	#$c0,$ffff8a3c.w	; (the address runs on)
	dbf	d0,.l
	rts

; ---- the buffer's window (the picture's rows CROP_TOP .. in its lines ren_vs ..; screen x 0 at its column ren_xo):
; ren_vcur follows layer 0's row base B (unwrapped: the twin lines hold the rows a scroll keeps), ren_vmod = it mod
; VP; the window's first line ren_vs = (CROP_TOP + ren_vmod) mod VP; ren_xo = layer 0's image column of x 0 (its
; terrain's columns are the buffer's: 0 .. 511, again 512 ..); layer 0 off: the last.  ren_ltab: per picture row the
; offset of its line (rows not shown: unused) ----
ren_view:
	lea	vio+VIO_CTL+$10,a0
	btst	#3,(a0)
	bne	.keep
	move.w	#0,ren_ly
	bsr	ren_scroll
	move.w	ren_lb,d0		; dB: -256 .. 255
	sub.w	ren_blast,d0
	add.w	#256,d0
	and.w	#511,d0
	sub.w	#256,d0
	move.w	ren_lb,ren_blast
	ext.l	d0
	add.l	d0,ren_vcur
	add.w	ren_vmod,d0
.m0:	bpl	.m1
	add.w	#VP,d0
	bra	.m0
.m1:	cmp.w	#VP,d0
	blt	.m2
	sub.w	#VP,d0
	bra	.m1
.m2:	move.w	d0,ren_vmod
	move.w	ren_lk,ren_xo
.keep:	move.w	ren_vmod,d0		; ren_vs = (CROP_TOP + vmod) mod VP
	add.w	#CROP_TOP,d0
	cmp.w	#VP,d0
	blt	.s
	sub.w	#VP,d0
.s:	move.w	d0,ren_vs
	move.w	ren_xo,ren_xadd
	sub.w	#CROP_TOP,d0		; the line of picture row r: ren_vs + r - CROP_TOP
	muls	#LINEB,d0
	lea	ren_ltab,a0
	move.w	#PIC_H-1,d1
.lt:	move.l	d0,(a0)+
	add.l	#LINEB,d0
	dbf	d1,.lt
	move.w	ren_cmin,d0		; the window's columns in the buffer (the sprites' end masks)
	add.w	ren_xo,d0
	move.w	d0,ren_wmin
	move.w	ren_cmax,d0
	add.w	ren_xo,d0
	move.w	d0,ren_wmax
	rts

; ---- the mode: the terrain (layer 0 is the scrolled buffer's terrain: only what changed of it is drawn) when layer
; 0 is on, the C116 window shows everything, layer 0 is the first layer drawn (the ones before it locked into it) and
; no sprite lies below its priority; else every layer drawn (the buffer's terrain lost) ----
ren_mode:
	sf	ren_tmode
	lea	vio+VIO_CTL+$10,a0
	btst	#3,(a0)
	bne	.r
	tst.w	ren_cmin
	bne	.r
	cmp.w	#PIC_W-1,ren_cmax
	bne	.r
	cmp.w	#CROP_TOP,ren_rmin
	bne	.r
	cmp.w	#CROP_TOP+SHOWN-1,ren_rmax
	bne	.r
	lea	ren_lord,a1		; the first layer drawn, not locked: layer 0
	move.w	ren_nlord,d6
	subq.w	#1,d6
.l:	moveq	#0,d0
	move.b	(a1),d0
	beq	.l0
	bsr	ren_locked
	beq	.r
	addq.l	#2,a1
	dbf	d6,.l
	bra	.r
.l0:	moveq	#7,d1			; no sprite below layer 0's priority
	and.b	vio+VIO_CTL+$10,d1
	lea	ren_slst,a5
.s:	cmp.l	ren_slend,a5
	bhs	.ok
	cmp.b	14(a5),d1
	bhi	.r
	lea	SL(a5),a5
	bra	.s
.ok:	st	ren_tmode
.r:	rts

; ---- the terrain into this buffer (ren_tmode; layer 0 prepared: its image up to date over all 64 tile columns of
; the rows shown).  The buffer's terrain is kept with its scroll (ren_tvv), its tag (the colours' epoch, layer 0's
; bank, the lock's generation) and the window's first line; this picture: last time's damage restored from the twins
; (ren_trestore), then the rows shown that scrolled in (their lines did not show the same row) or whose image rows
; were drawn (ren_tdirty of the buffer) - or every row, when the buffer holds no terrain, another tag, or the scroll
; moved a window or more.  A row: its image row into its line and the twin line, the 512 columns and 336 again. ----
ren_terrain:
	move.w	ren_cur,d7
	move.w	ren_lbank0,d0		; the tag
	lsl.w	#8,d0
	or.b	ren_lockgen,d0
	swap	d0
	move.w	ren_epoch,d0
	lea	ren_tvtag,a0
	move.w	d7,d1
	lsl.w	#2,d1
	lea	ren_tvv,a1
	move.l	ren_vcur,d2		; d = V - V_b
	sub.l	(a1,d1.w),d2
	move.l	ren_vcur,(a1,d1.w)
	lea	ren_tvok,a1
	tst.b	(a1,d7.w)
	beq	.all
	cmp.l	(a0,d1.w),d0
	bne	.all
	cmp.l	#VP,d2
	bge	.all
	cmp.l	#-VP,d2
	ble	.all
	move.w	d2,ren_td
	move.w	d7,-(sp)
	bsr	ren_trestore		; last time's damage
	move.w	(sp)+,d7
	lea	ren_trow,a2		; the rows to draw: scrolled in (r + d outside the rows shown) or drawn into the image
	move.w	d7,d0
	lsl.w	#8,d0
	add.w	d0,d0			; (512 bytes a buffer)
	lea	ren_tdirty,a3
	add.w	d0,a3
	move.w	ren_lb0,d4		; (layer 0's B: the image row of picture row 0)
	move.w	#CROP_TOP,d5		; (the buffer's VP rows: those shown and the next ones: every line pair is terrain)
	move.w	#VP-1,d6
.fr:	move.w	d5,d0
	add.w	ren_td,d0
	cmp.w	#CROP_TOP,d0
	blt	.in
	cmp.w	#CROP_TOP+VP-1,d0
	bgt	.in
	move.w	d5,d0			; the image row dirty?
	add.w	d4,d0
	and.w	#511,d0
	tst.b	(a3,d0.w)
	sne	(a2)+
	bra	.fn
.in:	st	(a2)+
.fn:	addq.w	#1,d5
	dbf	d6,.fr
	bra	.draw
.all:	move.l	d0,(a0,d1.w)
	st	(a1,d7.w)
	lea	ren_trow,a2
	move.w	#VP-1,d6
.fa:	st	(a2)+
	dbf	d6,.fa
.draw:	move.w	d7,d0			; the buffer's dirty image rows: done
	lsl.w	#8,d0
	add.w	d0,d0
	lea	ren_tdirty,a3
	add.w	d0,a3
	move.w	#512/4-1,d0
.cd:	clr.l	(a3)+
	dbf	d0,.cd
	move.w	ren_vs,ren_tvs0		; (this picture's window: where its damage lies)
	move.w	d7,d0
	add.w	d0,d0
	lea	ren_tvs,a0
	move.w	ren_vs,(a0,d0.w)
	clr.w	ren_xadd		; (the terrain's columns are the buffer's)
	lea	ren_lpar,a6		; layer 0's parameters: its image
	move.l	a6,ren_lpp
	move.w	#IMG_RB,ren_pstr
	bsr	ren_runs_setup
	move.w	#-1,ren_bk0
	lea	ren_trow,a2		; blocks of consecutive rows (their image rows and lines consecutive too)
	move.w	#CROP_TOP,d7
.r:	tst.b	(a2)+
	beq	.rf
	move.w	d7,d1			; the image row
	add.w	ren_lb0,d1
	and.w	#511,d1
	move.w	d7,d2			; the line: (ren_vs + r - CROP_TOP) mod VP
	sub.w	#CROP_TOP,d2
	add.w	ren_vs,d2
	cmp.w	#VP,d2
	blt	.l0
	sub.w	#VP,d2
.l0:	move.w	ren_bk0,d0
	bmi	.new
	move.w	ren_bkir,d0
	add.w	ren_bkn,d0
	cmp.w	d1,d0
	bne	.fl
	move.w	ren_bkl,d0
	add.w	ren_bkn,d0
	cmp.w	d2,d0
	bne	.fl
	addq.w	#1,ren_bkn
	bra	.rn
.fl:	movem.w	d1-d2,-(sp)
	bsr	ren_tblock
	movem.w	(sp)+,d1-d2
.new:	move.w	d1,ren_bkir
	move.w	d2,ren_bkl
	move.w	#1,ren_bkn
	clr.w	ren_bk0
	bra	.rn
.rf:	move.l	a2,-(sp)
	bsr	ren_tblock
	move.l	(sp)+,a2
.rn:	addq.w	#1,d7
	cmp.w	#CROP_TOP+VP,d7
	blt	.r
	bsr	ren_tblock
	move.w	ren_xo,ren_xadd
	move.w	d7,d0			; (this picture's damage: none yet)
	move.w	ren_cur,d0
	mulu	#2*SHOWN,d0
	lea	ren_dspan,a0
	add.l	d0,a0
	move.l	a0,ren_dsp
	move.w	#SHOWN/2-1,d0
.cs:	move.l	#-1,(a0)+
	dbf	d0,.cs
	rts

; the terrain's block (ren_bkir: its first image row, ren_bkl its first line (0 .. VP - 1), ren_bkn rows; ren_bk0 -1:
; none): into the lines and their twins (+ VP), the image's 512 columns at 0 and its first 336 at 512
ren_tblock:
	tst.w	ren_bk0
	bmi	.r
	move.w	#-1,ren_bk0
	movem.l	d7/a2,-(sp)
	moveq	#0,d0
	move.w	ren_bkir,d0
	lsl.l	#8,d0			; * IMG_ROW
	add.l	ren_lpar+LP_IMG,d0
	move.l	d0,ren_simg
	moveq	#2-1,d6			; the line and its twin
	move.w	ren_bkl,d5
.cp:	move.w	d5,d0
	mulu	#LINEB,d0
	add.l	ren_dst,d0
	move.l	d0,ren_ddst
	movem.l	d5-d6,-(sp)
	moveq	#0,d0			; columns 0 .. 511 at 0
	moveq	#0,d5
	move.w	#512,d1
	bsr	ren_bseg
	moveq	#0,d0			; columns 0 .. 335 at 512
	move.w	#TWIN,d5
	move.w	#LINEB*8/4-TWIN,d1
	bsr	ren_bseg
	movem.l	(sp)+,d5-d6
	add.w	#VP,d5
	dbf	d6,.cp
	movem.l	(sp)+,d7/a2
.r:	rts

; last time's damage of this buffer restored from the twins: per row shown of that picture (its window from line
; ren_tvs of the buffer), the groups drawn on (ren_dspan): their 4 plane words of the twin line (the line + VP, or -
; VP), copied in pieces of up to 64 words (128 bus cycles)
ren_trestore:
	move.w	ren_cur,d0
	mulu	#2*SHOWN,d0
	lea	ren_dspan,a2
	add.l	d0,a2
	move.w	ren_cur,d0
	add.w	d0,d0
	lea	ren_tvs,a0
	move.w	(a0,d0.w),d7		; that window's first line
	lea	$ffff8a20.w,a0		; the Blitter: source and destination X / Y inc 2 (the pieces run on), all masks, HOP 2 /
	move.w	#2,(a0)			; OP 3, no skew
	move.w	#2,2(a0)
	move.w	#2,$ffff8a2e.w
	move.w	#2,$ffff8a30.w
	move.w	#-1,$ffff8a28.w
	move.w	#-1,$ffff8a2a.w
	move.w	#-1,$ffff8a2c.w
	move.w	#$0203,$ffff8a3a.w
	clr.b	$ffff8a3d.w
	move.w	#SHOWN-1,d6
.row:	moveq	#0,d0
	move.b	(a2)+,d0		; the first group
	moveq	#0,d1
	move.b	(a2)+,d1		; the last
	cmp.b	#$FF,d0
	beq	.next
	sub.w	d0,d1
	addq.w	#1,d1
	lsl.w	#2,d1			; the words
	lsl.w	#3,d0			; the bytes' offset
	move.w	d7,d2			; the line, its twin
	move.w	d2,d3
	add.w	#VP,d3
	cmp.w	#VP,d2
	blt	.tw
	sub.w	#2*VP,d3
.tw:	mulu	#LINEB,d2
	mulu	#LINEB,d3
	add.l	ren_dst,d2
	add.l	ren_dst,d3
	add.l	d0,d2
	add.l	d0,d3
	move.l	d3,$ffff8a24.w
	move.l	d2,$ffff8a32.w
.pc:	move.w	d1,d4			; pieces of 64 words
	cmp.w	#64,d4
	bls	.p1
	moveq	#64,d4
.p1:	move.w	d4,$ffff8a36.w
	move.w	#1,$ffff8a38.w
	move.b	#$c0,$ffff8a3c.w	; (the addresses run on)
	sub.w	d4,d1
	bne	.pc
.next:	addq.w	#1,d7
	dbf	d6,.row
	rts

; ---- the layers ----

; ren_lord: (layer.b, priority.b) of the enabled layers in drawing order (priority, then the number); ren_nlord.  A
; new order (another set of layers or priorities): a new scene.
ren_layer_order:
	lea	vio+VIO_CTL+$10,a0
	lea	ren_lord,a1
	moveq	#0,d3			; the key: 4 bits a layer (enabled: 8 + priority)
	moveq	#0,d4			; entries
	moveq	#0,d2			; the priority
.p:	moveq	#0,d1
.l:	move.b	(a0,d1.w),d0
	btst	#3,d0
	bne	.n
	and.b	#7,d0
	cmp.b	d2,d0
	bne	.n
	move.b	d1,(a1)+
	move.b	d0,(a1)+
	addq.w	#1,d4
.n:	addq.w	#1,d1
	cmp.w	#6,d1
	bne	.l
	addq.w	#1,d2
	cmp.w	#8,d2
	bne	.p
	move.w	d4,ren_nlord
	moveq	#5,d1
.k:	lsl.l	#4,d3
	move.b	(a0,d1.w),d0
	btst	#3,d0
	bne	.kn
	and.b	#7,d0
	addq.b	#8,d0
	or.b	d0,d3
.kn:	dbf	d1,.k
	cmp.l	ren_lkey,d3
	beq	.r
	move.l	d3,ren_lkey
	st	ren_scene
.r:	rts

; ---- a layer's parameters (LP bytes per layer at ren_lpar + layer * LP) ----
LP_SCR = 0			; .w 1: a scrolling layer (its image: tile RAM's x by y turned), 0: fixed (the picture's)
LP_B = 2			; .w the image row of picture row 0 (scrolling: (44 + adj + sx) & 511)
LP_ROWB = 4			; .w an image row's bytes (4 planes), LP_MROWB a mask row's, LP_PSTR a plane row's
LP_MROWB = 6
LP_PSTR = 8
LP_NSEG = 10			; .w the segments of a row (columns cmin .. cmax: image columns, wrapping at h)
LP_IMG = 12			; .l the image, the mask, the run lists, their dirty flags
LP_MSK = 16
LP_RL = 20
LP_RD = 24
LP_SEG = 28			; 3 x (q.w the first image column, n.w columns, x.w its picture column)
LP_LAST = 46			; 5 words: the window's tiles (tx0, rows, kb0, columns) and the tag last refreshed (tag -1:
LP_SEEN = 56			; refresh all); .w set when prepared this picture
LP_FULL = 58			; PIC_H bytes: every segment inside one run (the row covered whole)
LP_COV = LP_FULL+PIC_H		; PIC_H bytes: covered whole by a layer drawn later
LP_NROWS = LP_COV+PIC_H		; .w the rows with runs (ren_lprep), then per row: its picture row.w, its image row.w
LP_CR0 = LP_NROWS+2		; .w the rows the list was made for (the fixed layers keep it while nothing changed:
LP_CR1 = LP_CR0+2		; LP_CR0 -1: none)
LP_CC0 = LP_CR1+2		; .w and the columns (cmin, cmax)
LP_CC1 = LP_CC0+2
LP_PN = LP_CC1+2		; 16 words: per fine shift (the columns' offset & 15) the fixed layers' recorded passes
LP_PXO = LP_PN+32		; (ren_ldraw); LP_PXO the shifts recorded (bits), LP_PBUF where they are (PC_MAX passes of
LP_PBUF = LP_PXO+2		; PC_SIZE bytes a shift)
LP_ROWS = LP_PBUF+4
LP = LP_ROWS+4*PIC_H
PC_SIZE = 20			; a recorded pass: row.w, the destination's offset in the line.w, source.l, source Y inc.w,
PC_MAX = 700			; END1.w, END3.w, destination Y inc.w, X count.w, skew.b, 0.b

; d0.w = a layer: its parameters, its window's tiles up to date in its image (ren_refresh / ren_frefresh), the run
; lists of its window's rows, its full rows
ren_lprep:
	move.w	d0,ren_ly
	mulu	#LP,d0
	lea	ren_lpar,a6
	add.l	d0,a6
	move.l	a6,ren_lpp
	move.w	#1,LP_SEEN(a6)
	move.w	ren_ly,d0
	lea	vio+VIO_CTL+$18,a0
	moveq	#7,d1
	and.b	(a0,d0.w),d1
	tst.w	d0			; (layer 0: the bank held since the colours were chosen, ren_flash_pen)
	bne	.bk
	tst.w	ren_l0bank
	bmi	.bk
	move.w	ren_l0bank,d1
.bk:	move.w	d1,ren_lbank
	move.w	d1,d0
	bsr	ren_bank_ready		; ren_bspread of the bank for this choice of colours
	move.w	ren_lbank,d1		; the stamps' tag: epoch << 4 | bank << 1
	add.w	d1,d1
	move.w	ren_epoch,d0
	lsl.w	#4,d0
	or.w	d1,d0
	move.w	d0,ren_ltag
	move.w	ren_ly,d0
	move.w	d0,d1
	lsl.w	#2,d1
	lea	ren_imgs,a0
	move.l	(a0,d1.w),LP_IMG(a6)
	move.l	(a0,d1.w),ren_limg
	lea	ren_msks,a0
	move.l	(a0,d1.w),LP_MSK(a6)
	move.l	(a0,d1.w),ren_lmsk
	lea	ren_shds,a0
	move.l	(a0,d1.w),ren_lshd
	lea	ren_rls,a0
	move.l	(a0,d1.w),LP_RL(a6)
	move.l	(a0,d1.w),ren_lrl
	lea	ren_rds,a0
	move.l	(a0,d1.w),LP_RD(a6)
	move.l	(a0,d1.w),ren_lrd
	cmp.w	#4,d0
	bhs	.fixed
	move.w	#1,LP_SCR(a6)
	move.w	#IMG_ROW,LP_ROWB(a6)
	move.w	#IMG_RB,LP_MROWB(a6)
	move.w	#IMG_RB,LP_PSTR(a6)
	bsr	ren_scroll		; ren_lb (B), ren_lk (K: image column of x 0), ren_lh1 (h - 1)
	move.w	ren_lb,LP_B(a6)
	move.w	ren_cmin,d3		; the segments: from (cmin + K) & (h - 1) to the image's end, then from 0 ...
	move.w	d3,d5			; (their picture column)
	add.w	ren_lk,d3
	and.w	ren_lh1,d3
	move.w	ren_cmax,d2
	sub.w	ren_cmin,d2
	addq.w	#1,d2			; the columns left
	lea	LP_SEG(a6),a0
	moveq	#0,d6			; segments
.sg:	move.w	ren_lh1,d4		; h - q
	addq.w	#1,d4
	sub.w	d3,d4
	cmp.w	d2,d4
	bls	.sg2
	move.w	d2,d4
.sg2:	move.w	d3,(a0)+
	move.w	d4,(a0)+
	move.w	d5,(a0)+
	addq.w	#1,d6
	add.w	d4,d5
	moveq	#0,d3
	sub.w	d4,d2
	bne	.sg
	move.w	d6,LP_NSEG(a6)
	move.w	ren_ly,d1		; the layer's tile words
	ror.w	#3,d1
	lea	vio+VIO_TILE,a0
	add.w	d1,a0
	move.l	a0,ren_ltile
	bsr	ren_window_tiles	; ren_tx0 / ren_ntr / ren_kb0 / ren_ntc
	tst.w	ren_ly
	bne	.w
	move.w	ren_lb,ren_lb0		; (layer 0: its B and bank for the terrain)
	move.w	ren_lbank,ren_lbank0
	tst.b	ren_tmode
	beq	.w
	clr.w	ren_kb0			; (the terrain: every column - a pan shows them without a draw; the VP rows)
	move.w	#63,ren_ntc
	move.w	#CROP_TOP,d0
	add.w	ren_lb,d0
	lsr.w	#3,d0
	move.w	#CROP_TOP+VP-1,d1
	add.w	ren_lb,d1
	lsr.w	#3,d1
	sub.w	d0,d1
	move.w	d1,ren_ntr
	move.w	d0,ren_tx0
.w:	bsr	ren_unchanged		; (no tile written, the same tiles and tag: Z)
	beq	.rows0
	bsr	ren_refresh
.rows0:	tst.w	ren_ly			; (the terrain: no run lists, no full rows)
	bne	.rows
	tst.b	ren_tmode
	beq	.rows
	rts
.fixed:	clr.w	LP_SCR(a6)
	clr.w	LP_B(a6)
	move.w	#FIX_ROW,LP_ROWB(a6)
	move.w	#FIX_RB,LP_MROWB(a6)
	move.w	#FIX_RB,LP_PSTR(a6)
	clr.w	LP_NSEG(a6)		; one segment: the window's columns inside x 48-271
	move.w	ren_cmin,d1
	cmp.w	#X0,d1
	bge	.f0
	moveq	#X0,d1
.f0:	move.w	ren_cmax,d2
	cmp.w	#X0+223,d2
	ble	.f1
	move.w	#X0+223,d2
.f1:	sub.w	d1,d2
	bmi	.f2
	addq.w	#1,d2
	move.w	d1,d0
	sub.w	#X0,d0
	move.w	d0,LP_SEG(a6)
	move.w	d2,LP_SEG+2(a6)
	move.w	d1,LP_SEG+4(a6)
	move.w	#1,LP_NSEG(a6)
.f2:	move.w	ren_ly,d0
	subq.w	#4,d0
	mulu	#$800,d0
	lea	vio+VIO_TILE+$7010,a0	; (word $3808 / $3C08)
	add.w	d0,a0
	move.l	a0,ren_ltile
	clr.l	ren_tx0			; (the fixed layers: the tag alone)
	clr.l	ren_kb0
	sf	ren_fdrawn
	bsr	ren_unchanged
	beq	.fu
	bsr	ren_frefresh
.fu:	move.l	ren_lpp,a6		; (no tile drawn and the same window: the list and the recorded passes kept)
	tst.b	ren_fdrawn
	bne	.fcd
	bsr	ren_samewin
	bne	.fcd
	rts
.fcd:	clr.w	LP_PXO(a6)		; (the recorded passes: made again)
.rows:	move.l	ren_lpp,a6		; the window's rows: their run lists (built when stale), full or not, the rows with
	clr.w	LP_NROWS(a6)		; runs listed (LP_ROWS)
	move.w	ren_rmin,d7
	move.w	d7,LP_CR0(a6)
	move.w	ren_rmax,LP_CR1(a6)
	move.w	ren_cmin,LP_CC0(a6)
	move.w	ren_cmax,LP_CC1(a6)
	lea	LP_ROWS(a6),a5
	lea	LP_FULL(a6),a4
	add.w	d7,a4
	move.w	ren_rmax,d6
	sub.w	d7,d6			; rows - 1
	tst.w	LP_SCR(a6)
	beq	.fix
	move.w	d7,d5			; the image row: (r + B) & 511; its mask row, list, dirty flag
	add.w	LP_B(a6),d5
	and.w	#511,d5
	moveq	#0,d0
	move.w	d5,d0
	lsl.l	#6,d0
	move.l	LP_MSK(a6),a0
	add.l	d0,a0
	move.l	LP_RL(a6),a3
	add.l	d0,a3
	move.l	LP_RD(a6),a2
	add.w	d5,a2
.sr:	tst.b	(a2)+
	beq	.sok
	clr.b	-1(a2)
	move.w	#IMG_RB,d0
	bsr	ren_rl_build
.sok:	bsr	.list
	addq.w	#1,d7
	addq.w	#1,d5
	lea	IMG_RB(a0),a0
	lea	RL_SIZE(a3),a3
	cmp.w	#512,d5
	bne	.sw
	moveq	#0,d5			; (the image's end)
	move.l	LP_MSK(a6),a0
	move.l	LP_RL(a6),a3
	move.l	LP_RD(a6),a2
.sw:	dbf	d6,.sr
	rts
.fix:	move.w	d7,d0			; the fixed layers: the image row from ren_fsrc (-1: none)
	add.w	d0,d0
	lea	ren_fsrc,a1
	move.w	(a1,d0.w),d5
	bmi	.fe
	moveq	#0,d0
	move.w	d5,d0
	lsl.l	#6,d0
	move.l	LP_RL(a6),a3
	add.l	d0,a3
	move.l	LP_RD(a6),a2
	tst.b	(a2,d5.w)
	beq	.fok
	clr.b	(a2,d5.w)
	move.w	d5,d0
	mulu	#FIX_RB,d0
	move.l	LP_MSK(a6),a0
	add.l	d0,a0
	move.w	#FIX_RB,d0
	bsr	ren_rl_build
.fok:	bsr	.list
	bra	.fn
.fe:	clr.b	(a4)+
.fn:	addq.w	#1,d7
	dbf	d6,.fix
	rts
; a3 = the row's list: listed when it has runs (d7 the picture row, d5 the image row); its full flag
.list:	moveq	#0,d1
	tst.b	(a3)
	beq	.le
	move.w	d7,(a5)+
	move.w	d5,(a5)+
	addq.w	#1,LP_NROWS(a6)
	cmp.b	#1,(a3)
	bne	.le
	bsr	ren_full		; (d0-d2, a1)
.le:	move.b	d1,(a4)+
	rts

; a6 = a layer's parameters: Z set when its list was made for this window (rows and columns)
ren_samewin:
	move.w	ren_rmin,d0
	cmp.w	LP_CR0(a6),d0
	bne	.r
	move.w	ren_rmax,d0
	cmp.w	LP_CR1(a6),d0
	bne	.r
	move.w	ren_cmin,d0
	cmp.w	LP_CC0(a6),d0
	bne	.r
	move.w	ren_cmax,d0
	cmp.w	LP_CC1(a6),d0
.r:	rts

; ren_ly: its scroll: ren_lb = B = (44 + adj + sx) & 511 (the image row of picture row 0), ren_lk = K = (-296 - sy)
; & (h - 1) (the image column of picture column x 0: k = (x - 48 - 248 - sy) mod h), ren_lh1 = h - 1
ren_scroll:
	move.w	ren_ly,d0
	move.w	d0,d1
	lsl.w	#2,d1
	lea	vio+VIO_CTL,a0
	move.w	(a0,d1.w),d3
	lea	ren_adj(pc),a1
	moveq	#0,d4
	move.b	(a1,d0.w),d4
	add.w	d4,d3
	add.w	#44,d3
	and.w	#511,d3
	move.w	d3,ren_lb
	move.w	2(a0,d1.w),d3
	neg.w	d3
	sub.w	#296,d3
	move.w	#511,d4			; h - 1 (layer 3: 255)
	cmp.w	#3,d0
	bne	.h
	move.w	#255,d4
.h:	and.w	d4,d3
	move.w	d3,ren_lk
	move.w	d4,ren_lh1
	rts

; a6 = the layer's parameters, d0.w = a picture row -> d1.w = its image row (scrolling: (r + B) & 511; fixed: the HUD
; rows moved, ren_fsrc; -1 and N set: none), a0 = its mask row, a3 = its run list, a2 = its dirty flag.  Keeps d7.
ren_irow:
	tst.w	LP_SCR(a6)
	beq	.fix
	move.w	d0,d1
	add.w	LP_B(a6),d1
	and.w	#511,d1
	moveq	#0,d0
	move.w	d1,d0
	lsl.l	#6,d0			; * IMG_RB = * RL_SIZE
	move.l	LP_MSK(a6),a0
	add.l	d0,a0
	move.l	LP_RL(a6),a3
	add.l	d0,a3
	move.l	LP_RD(a6),a2
	add.w	d1,a2
	tst.w	d1			; (N clear)
	rts
.fix:	add.w	d0,d0
	lea	ren_fsrc,a0
	move.w	(a0,d0.w),d1
	bmi	.r
	move.w	d1,d0
	mulu	#FIX_RB,d0
	move.l	LP_MSK(a6),a0
	add.l	d0,a0
	moveq	#0,d0
	move.w	d1,d0
	lsl.l	#6,d0
	move.l	LP_RL(a6),a3
	add.l	d0,a3
	move.l	LP_RD(a6),a2
	add.w	d1,a2
	tst.w	d1
.r:	rts

; a6 = the layer's parameters, a3 = a row's run list -> d1.l = 1 when its one run holds every segment, else 0
ren_full:
	moveq	#0,d1
	cmp.b	#1,(a3)
	bne	.r
	move.w	LP_NSEG(a6),d2
	beq	.r
	lea	LP_SEG(a6),a1
	subq.w	#1,d2
.s:	move.w	(a1)+,d0		; q <= first?
	cmp.w	2(a3),d0
	blo	.r
	add.w	(a1)+,d0		; q + n - 1 <= last?
	subq.w	#1,d0
	cmp.w	4(a3),d0
	bhi	.r
	addq.l	#2,a1
	dbf	d2,.s
	moveq	#1,d1
.r:	rts

; the scrolling layer's window in tiles: ren_tx0 / ren_ntr (tile rows - 1), ren_kb0 / ren_ntc (blocks - 1, at most
; h / 8 - 1: the picture's 320 columns hold layer 3's 256 more than once)
ren_window_tiles:
	move.w	ren_rmin,d0
	add.w	ren_lb,d0
	lsr.w	#3,d0
	move.w	ren_rmax,d1
	add.w	ren_lb,d1
	lsr.w	#3,d1
	sub.w	d0,d1
	move.w	d1,ren_ntr
	move.w	d0,ren_tx0
	move.w	ren_cmin,d0
	add.w	ren_lk,d0
	lsr.w	#3,d0
	move.w	ren_cmax,d1
	add.w	ren_lk,d1
	lsr.w	#3,d1
	sub.w	d0,d1
	move.w	ren_lh1,d2
	lsr.w	#3,d2
	cmp.w	d2,d1
	bls	.n
	move.w	d2,d1
.n:	move.w	d1,ren_ntc
	move.w	d0,ren_kb0
	rts

; a6 = the layer's parameters: Z set when no tile was written since the last picture and the window's tiles and the
; tag are those of the last refresh; else they are remembered (the caller refreshes)
ren_unchanged:
	lea	LP_LAST(a6),a0
	move.w	ren_ly,d0		; (the layer's writers' flag: layers 4 and 5 share the fifth)
	cmp.w	#4,d0
	bls	.f
	moveq	#4,d0
.f:	lea	tile_written,a1
	tst.b	(a1,d0.w)
	bne	.ch
	move.w	ren_tx0,d0
	cmp.w	(a0),d0
	bne	.ch
	move.w	ren_ntr,d0
	cmp.w	2(a0),d0
	bne	.ch
	move.w	ren_kb0,d0
	cmp.w	4(a0),d0
	bne	.ch
	move.w	ren_ntc,d0
	cmp.w	6(a0),d0
	bne	.ch
	move.w	ren_ltag,d0
	cmp.w	8(a0),d0
	bne	.ch
	rts				; (Z)
.ch:	move.w	ren_tx0,(a0)+
	move.w	ren_ntr,(a0)+
	move.w	ren_kb0,(a0)+
	move.w	ren_ntc,(a0)+
	move.w	ren_ltag,(a0)
	moveq	#1,d0			; (Z clear)
	rts

; after a picture: the layers not prepared lose their last refresh (their tiles may change unseen); the writers'
; flags consumed.  ren_lpar's LP_SEEN cleared for the next picture.
ren_lp_end:
	lea	ren_lpar,a0
	moveq	#6-1,d0
.l:	tst.w	LP_SEEN(a0)
	bne	.s
	move.w	#-1,LP_LAST+8(a0)
.s:	clr.w	LP_SEEN(a0)
	lea	LP(a0),a0
	dbf	d0,.l
	lea	tile_written,a0
	clr.l	(a0)+
	clr.b	(a0)
	rts

; The water locked to the terrain (the user, 2026-11-07): the enabled scrolling layers drawn before layer 0 are drawn
; into layer 0's holes as its tiles are drawn (ren_tile: ren_lock_fill), at offsets taken when the set of them
; changes: image row + (B_j - B_0), image column + (K_j - K_0).  A new set, a locked layer's tiles written or its bank
; changed: layer 0 is drawn again.  ren_nlock / ren_lockl: the locked layers top first.
ren_lock_check:
	moveq	#0,d3			; the set: bit j
	lea	vio+VIO_CTL+$10,a0
	btst	#3,(a0)
	bne	.set			; (layer 0 off: none)
	lea	ren_lord,a1
	move.w	ren_nlord,d6
	subq.w	#1,d6
	bmi	.set
.l:	move.b	(a1),d0
	beq	.set			; (up to layer 0)
	cmp.b	#4,d0
	bhs	.n
	bset	d0,d3
.n:	addq.l	#2,a1
	dbf	d6,.l
.set:	move.l	ren_lockset,d4
	move.l	d3,ren_lockset
	cmp.l	d4,d3
	bne	.new
	tst.l	d3
	beq	.r
	moveq	#1,d0			; (the same set: a locked layer written or its bank changed)
.w:	btst	d0,d3
	beq	.wn
	lea	tile_written,a0
	tst.b	(a0,d0.w)
	beq	.wb
	bsr	ren_lk_same		; (written: its tile words changed?)
	bne	.inval
.wb:	lea	vio+VIO_CTL+$18,a0
	moveq	#7,d1
	and.b	(a0,d0.w),d1
	lea	ren_lockbank,a0
	cmp.b	(a0,d0.w),d1
	bne	.inval
.wn:	addq.w	#1,d0
	cmp.w	#4,d0
	bne	.w
.r:	rts
.new:	clr.w	ren_nlock		; the offsets now; the locked layers top first (ren_lord backwards)
	tst.l	d3
	beq	.inval
	move.w	#0,ren_ly
	move.l	d3,-(sp)
	bsr	ren_scroll
	move.l	(sp)+,d3
	move.w	ren_lb,d4		; B_0, K_0
	move.w	ren_lk,d5
	lea	ren_lord,a1
	move.w	ren_nlord,d6
	add.w	d6,a1
	add.w	d6,a1
	subq.w	#1,d6
.lk:	subq.l	#2,a1
	moveq	#0,d0
	move.b	(a1),d0
	btst	d0,d3
	beq	.lkn
	move.w	d0,ren_ly
	movem.l	d3-d6/a1,-(sp)
	bsr	ren_scroll
	movem.l	(sp)+,d3-d6/a1
	move.w	ren_nlock,d1
	add.w	d1,d1
	lea	ren_lockl,a0
	move.w	d0,(a0,d1.w)
	move.w	ren_lb,d2
	sub.w	d4,d2
	and.w	#511,d2
	lea	ren_lockdr,a0
	move.w	d2,(a0,d1.w)
	move.w	ren_lk,d2
	sub.w	d5,d2
	and.w	ren_lh1,d2
	lea	ren_lockdc,a0
	move.w	d2,(a0,d1.w)
	addq.w	#1,ren_nlock
.lkn:	dbf	d6,.lk
.inval:	moveq	#1,d0			; (the locked layers' tile words as drawn now)
.cp:	move.l	ren_lockset,d1
	btst	d0,d1
	beq	.cpn
	bsr	ren_lk_copy
.cpn:	addq.w	#1,d0
	cmp.w	#4,d0
	bne	.cp
	addq.b	#1,ren_lockgen		; (the buffers' terrain: another tag)
	lea	ren_lockbank,a0		; layer 0 drawn again: its stamps, its last refresh
	lea	vio+VIO_CTL+$18,a1
	moveq	#4-1,d0
.bk:	moveq	#7,d1
	and.b	(a1)+,d1
	move.b	d1,(a0)+
	dbf	d0,.bk
	move.w	#-1,ren_shtag		; (its shadow: none)
	move.w	#-1,ren_lpar+LP_LAST+8
	rts

; d0.w = a locked layer (1-3): Z set when its tile words are those layer 0 was drawn with (ren_lkshd; the translated
; writers flag a layer on any store, the same words included).  Keeps d0.
ren_lk_same:
	bsr	ren_lk_addr
.l:	cmpm.l	(a0)+,(a1)+
	dbne	d1,.l
	rts
; d0.w = a locked layer: its tile words into ren_lkshd.  Keeps d0.
ren_lk_copy:
	bsr	ren_lk_addr
.l:	move.l	(a0)+,(a1)+
	dbf	d1,.l
	rts
; d0.w = a layer 1-3 -> a0 = its tile words, a1 = its copy, d1.w = longs - 1
ren_lk_addr:
	move.w	d0,d1
	ror.w	#3,d1			; (j * $2000)
	lea	vio+VIO_TILE,a0
	add.w	d1,a0
	lea	ren_lkshd-$2000,a1
	add.w	d1,a1
	move.w	#64*64/2-1,d1
	cmp.w	#3,d0
	bne	.r
	move.w	#64*32/2-1,d1
.r:	rts

; the covered rows: per enabled layer, the full rows of the layers drawn after it (ren_lord: drawing order)
ren_cover:
	lea	ren_cacc,a0
	moveq	#PIC_H/4-1,d0
.c:	clr.l	(a0)+
	dbf	d0,.c
	move.w	ren_nlord,d6
	lea	ren_lord,a5
	add.w	d6,a5
	add.w	d6,a5
	bra	.n
.l:	subq.l	#2,a5
	moveq	#0,d0
	move.b	(a5),d0
	bsr	ren_locked
	bne	.n
	mulu	#LP,d0
	lea	ren_lpar,a6
	add.l	d0,a6
	lea	ren_cacc,a0
	lea	LP_COV(a6),a1
	lea	LP_FULL(a6),a2
	move.w	ren_rmin,d0		; (only the window's rows: LP_FULL is not cleared outside)
	move.w	ren_rmax,d1
	sub.w	d0,d1
	add.w	d0,a0
	add.w	d0,a1
	add.w	d0,a2
.r:	move.b	(a0),(a1)+
	move.b	(a2)+,d2
	or.b	d2,(a0)+
	dbf	d1,.r
.n:	dbf	d6,.l
	rts

; d0.w = a layer -> Z clear when it is locked into layer 0 (not drawn on its own).  Keeps d0.
ren_locked:
	move.l	d1,-(sp)
	move.l	ren_lockset,d1
	btst	d0,d1
	movem.l	(sp)+,d1		; (movem: the Z of btst kept)
	rts

; d0.w = a layer (ren_lprep done): its window's rows onto the buffer.  A row covered by a later layer: nothing; a
; full row: one of a block of consecutive full rows, copied plane by plane (ren_block: several lines a pass); else
; its runs (ren_seg: a pass each, 4 planes).
ren_ldraw:
	move.w	d0,d1
	mulu	#LP,d0
	lea	ren_lpar,a6
	add.l	d0,a6
	move.l	a6,ren_lpp
	move.l	LP_RL(a6),ren_lrl
	move.l	LP_RD(a6),ren_lrd
	move.w	LP_PSTR(a6),ren_pstr
	bsr	ren_runs_setup
	sf	ren_prec
	cmp.w	#4,d1			; the fixed layers: their passes recorded (Black Tiger's text pieces: made when the
	blo	.nrec			; text or the columns' offset changes, streamed in the other pictures; the terrain
	tst.b	ren_tmode		; mode only: the whole window)
	bne	.rec
	move.l	ren_lpp,a6
	clr.w	LP_PXO(a6)
	bra	.nrec
.rec:
	lea	ren_pbufs,a0
	subq.w	#4,d1
	mulu	#16*PC_SIZE*PC_MAX/4,d1
	lsl.l	#2,d1
	add.l	d1,a0
	moveq	#15,d1			; this shift's passes
	and.w	ren_xo,d1
	move.w	d1,d0
	mulu	#PC_SIZE*PC_MAX,d0
	add.l	d0,a0
	move.l	a0,LP_PBUF(a6)
	move.w	LP_PXO(a6),d0
	btst	d1,d0
	bne	ren_pstream
	st	ren_prec		; (record them while drawing)
	move.l	a0,ren_ppos
	clr.w	ren_pnum
	sf	ren_pfail
.nrec:	move.w	#-1,ren_bk0		; (no block of full rows yet)
	lea	LP_ROWS(a6),a5		; the listed rows (those with runs)
	move.w	LP_NROWS(a6),d6
	bra	.n
.row:	move.l	ren_lpp,a6
	move.w	(a5)+,d7		; the picture row
	move.w	(a5)+,d1		; its image row
	lea	LP_COV(a6),a4
	tst.b	(a4,d7.w)
	bne	.flush
	lea	LP_FULL(a6),a4
	tst.b	(a4,d7.w)
	beq	.part
	move.w	ren_bk0,d0		; a full row: the block goes on (the next picture row, the next image row)
	bmi	.new
	move.w	ren_bkr,d2
	add.w	ren_bkn,d2
	cmp.w	d7,d2
	bne	.fl2
	move.w	ren_bkir,d2
	add.w	ren_bkn,d2
	cmp.w	d1,d2
	bne	.fl2
	addq.w	#1,ren_bkn
	bra	.n
.fl2:	move.w	d1,-(sp)
	bsr	.blk
	move.w	(sp)+,d1
.new:	move.w	d7,ren_bkr
	move.w	d1,ren_bkir
	move.w	#1,ren_bkn
	clr.w	ren_bk0
	bra	.n
.flush:	tst.w	ren_bk0
	bmi	.n
	bsr	.blk
	bra	.n
.part:	tst.w	ren_bk0
	bmi	.nb
	move.w	d1,-(sp)
	bsr	.blk
	move.w	(sp)+,d1
.nb:	movem.l	d6/a5,-(sp)
	move.l	ren_lpp,a6
	moveq	#0,d0			; the list
	move.w	d1,d0
	lsl.l	#6,d0
	add.l	LP_RL(a6),d0
	move.l	d0,ren_rlp
	move.w	d1,d0			; the mask row (ren_runs: more runs than the list holds), the image row
	mulu	LP_MROWB(a6),d0
	move.l	LP_MSK(a6),a0
	add.l	d0,a0
	move.w	d1,d0
	mulu	LP_ROWB(a6),d0
	add.l	LP_IMG(a6),d0
	move.l	d0,ren_simg
	move.w	d7,d0
	add.w	d0,d0
	add.w	d0,d0
	lea	ren_ltab,a1
	move.l	(a1,d0.w),d1
	add.l	ren_dst,d1
	move.l	d1,ren_ddst
	move.w	d7,ren_drow0		; (the damage: this row, its passes' groups gathered: ren_dlo .. ren_dhi)
	move.w	#1,ren_drows
	st	ren_dacc
	move.w	#$7FFF,ren_dlo
	move.w	#-1,ren_dhi
	move.w	LP_NSEG(a6),d6		; the segments
	lea	LP_SEG(a6),a5
	bra	.sn
.sl:	move.w	(a5)+,d0
	move.w	(a5)+,d1
	move.w	(a5)+,d2
	movem.l	d6/a0/a5-a6,-(sp)
	bsr	ren_seg
	movem.l	(sp)+,d6/a0/a5-a6
.sn:	dbf	d6,.sl
	sf	ren_dacc
	move.w	ren_dhi,d3
	bmi	.nd
	move.w	ren_drow0,d0
	moveq	#1,d1
	move.w	ren_dlo,d2
	bsr	ren_dmg
.nd:	movem.l	(sp)+,d6/a5
.n:	dbf	d6,.row
	bsr	.blk
	tst.b	ren_prec		; (recorded: kept unless a block was drawn or too many)
	beq	.r
	sf	ren_prec
	move.l	ren_lpp,a6
	tst.b	ren_pfail
	bne	.r
	moveq	#15,d1
	and.w	ren_xo,d1
	move.w	d1,d0
	add.w	d0,d0
	lea	LP_PN(a6),a0
	move.w	ren_pnum,(a0,d0.w)
	move.w	LP_PXO(a6),d0
	bset	d1,d0
	move.w	d0,LP_PXO(a6)
.r:	rts
.blk:	movem.l	d6/a5,-(sp)		; (the block)
	bsr	ren_block
	movem.l	(sp)+,d6/a5
	rts

; a fixed layer's recorded passes (ren_ldraw; a6 = its parameters): each one's registers, its destination from its
; row's line now; the damage
ren_pstream:
	move.l	LP_PBUF(a6),a2
	moveq	#15,d0
	and.w	ren_xo,d0
	add.w	d0,d0
	lea	LP_PN(a6),a3
	move.w	(a3,d0.w),d6
	lea	ren_ltab,a3
	move.w	ren_xo,d5		; (the offset's whole groups: recorded without)
	lsr.w	#4,d5
	lsl.w	#3,d5
	move.w	#-1,ren_prow		; (the damage: a row's passes gathered)
	bra	.n
.p:	move.w	(a2)+,d7		; the row
	move.w	d7,d0
	add.w	d0,d0
	add.w	d0,d0
	move.l	(a3,d0.w),d1
	add.l	ren_dst,d1
	moveq	#0,d2
	move.w	(a2)+,d2		; the offset in the line
	add.w	d5,d2
	add.l	d2,d1
	move.l	(a2)+,$ffff8a24.w
	move.w	(a2)+,$ffff8a22.w
	move.w	(a2)+,$ffff8a28.w
	move.w	(a2)+,$ffff8a2c.w
	move.w	(a2)+,$ffff8a30.w
	move.w	(a2)+,d4
	move.w	d4,$ffff8a36.w
	move.b	(a2)+,$ffff8a3d.w
	addq.l	#1,a2
	move.l	d1,$ffff8a32.w
	move.w	#4,$ffff8a38.w
	move.b	#$c0,$ffff8a3c.w
	tst.b	ren_dmgon		; (the damage: its row, its groups)
	beq	.n
	move.w	d2,d0			; (the line's start is group 0)
	lsr.w	#3,d0
	move.w	d0,d2
	move.w	d0,d3
	add.w	d4,d3
	subq.w	#1,d3
	cmp.w	ren_prow,d7
	beq	.acc
	bsr	.flush
	move.w	d7,ren_prow
	move.w	d2,ren_dlo
	move.w	d3,ren_dhi
	bra	.n
.acc:	cmp.w	ren_dlo,d2
	bge	.al
	move.w	d2,ren_dlo
.al:	cmp.w	ren_dhi,d3
	ble	.n
	move.w	d3,ren_dhi
.n:	dbf	d6,.p
.flush:	move.w	ren_prow,d0		; (the row's damage)
	bmi	.fr
	movem.l	d1-d3,-(sp)
	moveq	#1,d1
	move.w	ren_dlo,d2
	move.w	ren_dhi,d3
	bsr	ren_dmg
	movem.l	(sp)+,d1-d3
.fr:	rts

; The block of full rows (ren_bkr: its first picture row, ren_bkir its first image row, ren_bkn rows; ren_bk0 -1:
; none) onto the buffer: per segment and plane, HOG passes of up to 256 bus cycles' lines (X count the destination
; words, the source's Y increment to the next image row, the destination's to the next line); then no block.
; Keeps d7.
ren_block:
	tst.w	ren_bk0
	bmi	.r
	move.w	#-1,ren_bk0
	st	ren_pfail		; (a fixed layer's recording: not kept)
	movem.l	d7/a6,-(sp)
	move.l	ren_lpp,a6
	move.w	ren_bkir,d0		; the source: the image row (plane 0)
	mulu	LP_ROWB(a6),d0
	add.l	LP_IMG(a6),d0
	move.l	d0,ren_simg
	move.w	ren_bkr,d0
	add.w	d0,d0
	add.w	d0,d0
	lea	ren_ltab,a1
	move.l	(a1,d0.w),d1
	add.l	ren_dst,d1
	move.l	d1,ren_ddst
	move.w	ren_bkr,ren_drow0	; (the damage: the block's rows)
	move.w	ren_bkn,ren_drows
	move.w	LP_NSEG(a6),d6
	lea	LP_SEG(a6),a5
	bra	.n
.s:	move.w	(a5)+,d0
	move.w	(a5)+,d1
	move.w	(a5)+,d5
	movem.l	d6/a5,-(sp)
	bsr	ren_bseg
	movem.l	(sp)+,d6/a5
.n:	dbf	d6,.s
	movem.l	(sp)+,d7/a6
.r:	rts

; a segment of the block: d0.w = its first source column, d5.w = its picture column, d1.w = its length
ren_bseg:
	move.l	ren_lpp,a6
	move.w	LP_ROWB(a6),d6		; the source steps to the next image row, the destination to the next line
	move.w	#LINEB,d7
	bsr	ren_bsetup		; a0 / a1 = the source / destination of plane 0, d4 = the X count
	move.w	d4,d0			; lines a pass: 256 / (2 n + 3) bus cycles a line
	add.w	d0,d0
	addq.w	#3,d0
	move.l	#256,d1
	divu	d0,d1
	move.w	d1,d6			; lines a pass
	moveq	#4-1,d5			; the planes
.pl:	move.l	a0,$ffff8a24.w
	move.l	a1,$ffff8a32.w
	move.w	ren_bkn,d2
.ps:	move.w	d6,d3
	cmp.w	d2,d3
	bls	.y
	move.w	d2,d3
.y:	move.w	d3,$ffff8a38.w
	move.b	#$c0,$ffff8a3c.w	; (the addresses run on)
	sub.w	d3,d2
	bne	.ps
	add.w	ren_pstr,a0		; the next plane
	addq.l	#2,a1
	dbf	d5,.pl
	rts

; The Blitter's registers for a copy: d0.w = the first source column (bits of the plane rows at ren_simg), d5.w =
; the first picture column (screen x), d1.w = the length, d6.w = the source's step to the next row of the pass (the
; next plane row: ren_pstr; the next image row), d7.w = the destination's (2: the next plane; STRIDE: the next line).
; -> a0 = the source, a1 = the destination of the first row, d4.w = the X count; everything else written but the
; addresses, the Y count and the start.  The skew from the two bit offsets (FXSR when the destination's is the
; smaller), NFSR when the source has fewer words than the destination + FXSR (not for one word: Hatari's blitter then
; reads only the FXSR word, and steps by the X increment - the word after is read instead, masked away); END1 / END3
; the run's ends, END2 all (ren_runs_setup).  Uses d0-d7, a0-a2.
ren_bsetup:
	add.w	ren_xadd,d5		; (the picture's column 0 in the buffer: ren_xo; the terrain's own: 0)
	move.w	d6,-(sp)
	move.w	d7,-(sp)
	moveq	#15,d2
	and.w	d5,d2			; db
	moveq	#15,d3
	and.w	d0,d3			; sb
	move.w	d5,d4			; n = ((x + len - 1) >> 4) - (x >> 4) + 1
	add.w	d1,d4
	subq.w	#1,d4
	move.w	d4,d6			; (the last bit)
	lsr.w	#4,d4
	move.w	d5,d7
	lsr.w	#4,d7
	sub.w	d7,d4
	addq.w	#1,d4			; n
	move.w	d0,a0			; m = ((s + len - 1) >> 4) - (s >> 4) + 1
	move.w	d0,d7
	add.w	d1,d7
	subq.w	#1,d7
	lsr.w	#4,d7
	lsr.w	#4,d0
	sub.w	d0,d7
	addq.w	#1,d7			; m
	moveq	#0,d1			; the skew byte
	move.w	d2,d0
	sub.w	d3,d0			; db - sb
	bpl	.nf
	add.w	#16,d0
	or.b	#$80,d1			; FXSR
.nf:	or.b	d0,d1
	move.w	d4,d0			; reads = n + FXSR
	tst.b	d1
	bpl	.r0
	addq.w	#1,d0
.r0:	cmp.w	d7,d0
	bls	.r1
	cmp.w	#1,d4
	beq	.r1
	or.b	#$40,d1			; NFSR
	subq.w	#1,d0
.r1:	subq.w	#1,d0			; reads - 1
	add.w	d0,d0
	move.w	2(sp),d3
	sub.w	d0,d3			; the source's Y increment
	move.w	a0,d0			; the source: ren_simg + (s >> 4) * 2
	lsr.w	#4,d0
	add.w	d0,d0
	move.l	ren_simg,a0
	add.w	d0,a0
	move.w	d5,d0			; the destination: ren_ddst + (x >> 4) * 8
	lsr.w	#4,d0
	lsl.w	#3,d0
	move.l	ren_ddst,a1
	add.w	d0,a1
	moveq	#-1,d0			; END1 = $FFFF >> db
	lsr.w	d2,d0
	and.w	#15,d6			; END3 = $FFFF << (15 - (last & 15))
	moveq	#15,d2
	sub.w	d6,d2
	moveq	#-1,d6
	lsl.w	d2,d6
	cmp.w	#1,d4
	bne	.two
	and.w	d6,d0			; (one word: END1 alone)
.two:	move.w	d4,d2			; the destination's Y increment: step - 8 (n - 1)
	subq.w	#1,d2
	lsl.w	#3,d2
	neg.w	d2
	add.w	(sp),d2
	addq.l	#4,sp
	move.w	d3,$ffff8a22.w		; source Y inc
	move.w	d0,$ffff8a28.w		; END1
	move.w	d6,$ffff8a2c.w		; END3
	move.w	d2,$ffff8a30.w		; destination Y inc
	move.w	d4,$ffff8a36.w		; X count
	move.b	d1,$ffff8a3d.w
	tst.b	ren_dmgon		; (the damage: the rows ren_drow0 .., the groups x >> 4 .. + n - 1; a row's runs:
	beq	.r			; gathered, ren_dacc)
	move.w	d5,d2
	lsr.w	#4,d2
	move.w	d2,d3
	add.w	d4,d3
	subq.w	#1,d3
	tst.b	ren_dacc
	beq	.dm
	cmp.w	ren_dlo,d2
	bge	.dl
	move.w	d2,ren_dlo
.dl:	cmp.w	ren_dhi,d3
	ble	.r
	move.w	d3,ren_dhi
	rts
.dm:	move.w	ren_drow0,d0
	move.w	ren_drows,d1
	bsr	ren_dmg
.r:	rts

; the damage of the picture drawn now (ren_dmgon): rows d0.w .. d0 + d1 - 1 (picture rows), groups d2.w .. d3.w (the
; buffer's): per row shown the groups' span (ren_dspan of the buffer: first, last; $FF: none).  Keeps d4-d7, a0-a1.
ren_dmg:
	movem.l	d4/a2,-(sp)
	tst.w	d2
	bpl	.g0
	moveq	#0,d2
.g0:	cmp.w	#LINEB/8-1,d3
	ble	.g1
	moveq	#LINEB/8-1,d3
.g1:	cmp.w	d3,d2
	bgt	.r
	sub.w	#CROP_TOP,d0		; the rows shown: 0 .. SHOWN - 1
	bpl	.r0
	add.w	d0,d1
	moveq	#0,d0
.r0:	move.w	d0,d4
	add.w	d1,d4
	cmp.w	#SHOWN,d4
	ble	.r1
	move.w	#SHOWN,d1
	sub.w	d0,d1
.r1:	subq.w	#1,d1
	bmi	.r
	move.l	ren_dsp,a2
	add.w	d0,a2
	add.w	d0,a2
.l:	cmp.b	(a2),d2
	bhs	.lo
	move.b	d2,(a2)
.lo:	cmp.b	1(a2),d3
	bls	.hi
	cmp.b	#$FF,(a2)		; (the first: both)
	beq	.hi
	move.b	d3,1(a2)
.hi:	cmp.b	#$FF,1(a2)
	bne	.n
	move.b	d3,1(a2)
.n:	addq.l	#2,a2
	dbf	d1,.l
.r:	movem.l	(sp)+,d4/a2
	rts

; d0.w = a mask row's bytes, a0 = the mask row (bit 7 the first column), a3 = its run list: the opaque runs (first,
; last column: words), at most RL_MAX (else the count $FF: ren_seg scans the row).  Whole bytes of $FF / 0 at once.
ren_rl_build:
	movem.l	d0-d6/a0-a1,-(sp)
	move.w	ren_ly,d1		; (counted per layer: ren_nbuilds)
	add.w	d1,d1
	add.w	d1,d1
	lea	ren_nbuilds,a1
	addq.l	#1,(a1,d1.w)
	lea	2(a3),a1
	moveq	#0,d6			; runs
	moveq	#-1,d5			; the run's first column
	moveq	#0,d3			; the column
	move.w	d0,d4
	subq.w	#1,d4
.byte:	move.b	(a0)+,d0
	beq	.zero
	cmp.b	#$FF,d0
	beq	.full
	moveq	#7,d1
.bit:	btst	d1,d0
	beq	.b0
	tst.w	d5
	bpl	.bn
	move.w	d3,d5
	bra	.bn
.b0:	tst.w	d5
	bmi	.bn
	bsr	.close
.bn:	addq.w	#1,d3
	dbf	d1,.bit
	bra	.nx
.full:	tst.w	d5
	bpl	.f8
	move.w	d3,d5
.f8:	addq.w	#8,d3
	bra	.nx
.zero:	tst.w	d5
	bmi	.z8
	bsr	.close
.z8:	addq.w	#8,d3
.nx:	dbf	d4,.byte
	tst.w	d5
	bmi	.done
	bsr	.close
.done:	cmp.w	#RL_MAX,d6
	bls	.ok
	moveq	#-1,d6
.ok:	move.b	d6,(a3)
	movem.l	(sp)+,d0-d6/a0-a1
	rts
.close:	addq.w	#1,d6			; the run d5 .. d3 - 1
	cmp.w	#RL_MAX,d6
	bhi	.cl
	move.w	d5,(a1)+
	move.w	d3,d2
	subq.w	#1,d2
	move.w	d2,(a1)+
.cl:	moveq	#-1,d5
	rts

; A segment of a row (a0 = its mask row, d0.w = its first column, d1.w = how many, d2.w = the picture column of the
; first) onto the buffer by the row's run list (ren_rlp): each run's part inside the segment, a pass (ren_blit_run).
; A list of more than RL_MAX runs: ren_runs scans the mask.  Keeps a0.
ren_seg:
	move.l	ren_rlp,a3
	moveq	#0,d3
	move.b	(a3),d3
	addq.l	#2,a3
	cmp.b	#$FF,d3
	beq	ren_runs
	movem.l	d4-d7,-(sp)
	move.w	d0,d6			; the segment's first column
	move.w	d0,d7
	add.w	d1,d7			; its end
	sub.w	d0,d2			; picture column = column + d2
	bra	.n
.l:	move.w	(a3)+,d4		; the run's first column
	move.w	(a3)+,d5
	addq.w	#1,d5			; its end
	cmp.w	d6,d4
	bge	.lo
	move.w	d6,d4
.lo:	cmp.w	d7,d5
	ble	.hi
	move.w	d7,d5
.hi:	cmp.w	d5,d4
	bge	.n
	movem.l	d2-d3/d6-d7/a0/a3,-(sp)
	move.w	d4,d0			; the source column
	move.w	d5,d1
	sub.w	d4,d1			; the length
	move.w	d4,d5
	add.w	d2,d5			; the picture column
	bsr	ren_blit_run
	movem.l	(sp)+,d2-d3/d6-d7/a0/a3
.n:	dbf	d3,.l
	movem.l	(sp)+,d4-d7
	rts

; The window's tiles of a scrolling layer drawn into its image where they differ from the layer's shadow (its tile
; words as last drawn, ren_lshd: tile RAM's layout): tile rows tx = (r + B) >> 3 for r in rmin .. rmax (mod 64),
; blocks kb = k >> 3 for k = (x + K) mod h, x in cmin .. cmax (mod h / 8); the tile at y block ty = h / 8 - 1 - kb,
; its word at (ty * 64 + tx) * 2.  Another tag (colours, bank): the whole shadow made stale first (ren_shadow_tag).
ren_refresh:
	bsr	ren_shadow_tag
	move.w	ren_lh1,d6
	lsr.w	#3,d6			; h / 8 - 1 (the mask of the blocks)
	move.w	ren_kb0,d3
	move.w	ren_ntc,d2
.col:	and.w	d6,d3			; kb: the tiles of y block ty = h / 8 - 1 - kb
	move.w	d6,d1
	sub.w	d3,d1
	lsl.w	#7,d1			; (64 words a tile row)
	move.l	ren_ltile,a2
	add.w	d1,a2
	move.l	ren_lshd,a3
	add.w	d1,a3
	move.w	ren_tx0,d5
	and.w	#63,d5
	move.w	ren_ntr,d4		; the rows - 1: runs of consecutive words to the row's end, then from 0
.run:	moveq	#63,d0
	sub.w	d5,d0
	cmp.w	d4,d0
	bls	.r1
	move.w	d4,d0
.r1:	sub.w	d0,d4
	subq.w	#1,d4			; (the rows after this run - 1)
	move.w	d5,d1
	add.w	d1,d1
	lea	(a2,d1.w),a0
	lea	(a3,d1.w),a1
.cmp:	cmpm.w	(a0)+,(a1)+
	bne	.draw
.cn:	dbf	d0,.cmp
	moveq	#0,d5
	tst.w	d4
	bpl	.run
	addq.w	#1,d3
	dbf	d2,.col
	rts
.draw:	move.w	-2(a0),-2(a1)		; the tile into the image: rows tx * 8 .., its byte kb
	movem.l	d0-d7/a0-a3,-(sp)
	move.l	a0,d5
	sub.l	a2,d5
	subq.w	#2,d5
	lsr.w	#1,d5			; tx
	move.w	d3,d7			; kb
	move.w	-2(a0),d0
	and.w	#$3FFF,d0
	move.w	d5,d1
	lsl.w	#3,d1
	move.w	d1,ren_tX		; (its first image row and column: ren_lock_fill)
	move.w	d7,d2
	lsl.w	#3,d2
	move.w	d2,ren_tk
	moveq	#0,d2
	move.w	d1,d2
	lsl.l	#8,d2			; * IMG_ROW
	move.l	ren_limg,a1
	add.l	d2,a1
	add.w	d7,a1
	moveq	#0,d2
	move.w	d1,d2
	lsl.l	#6,d2			; * IMG_RB
	move.l	ren_lmsk,a2
	add.l	d2,a2
	add.w	d7,a2
	move.w	#IMG_RB,d3
	move.w	#IMG_ROW,d4
	move.w	d5,-(sp)
	move.w	#IMG_RB,d5
	sf	ren_tchg
	bsr	ren_tile
	move.w	(sp)+,d5
	tst.b	ren_tchg		; (the image unchanged: nothing stale)
	beq	.dn
	move.w	d5,d1			; its 8 rows' run lists stale
	lsl.w	#3,d1
	move.l	ren_lrd,a0
	add.w	d1,a0
	move.l	#$01010101,(a0)+
	move.l	#$01010101,(a0)
	tst.w	ren_ly			; (layer 0: its rows to draw again into each buffer's terrain)
	bne	.dn
	lea	ren_tdirty,a0
	add.w	d1,a0
	move.l	#$01010101,(a0)
	move.l	#$01010101,4(a0)
	move.l	#$01010101,512(a0)
	move.l	#$01010101,516(a0)
.dn:	movem.l	(sp)+,d0-d7/a0-a3
	bra	.cn

; ren_ly's shadow made stale when the tag (ren_ltag) is not the one it was drawn with: each word the complement of
; its tile word (every tile drawn again when compared)
ren_shadow_tag:
	move.w	ren_ly,d0
	add.w	d0,d0
	lea	ren_shtag,a0
	move.w	ren_ltag,d1
	cmp.w	(a0,d0.w),d1
	beq	.r
	move.w	d1,(a0,d0.w)
	move.w	#64*64/4-1,d1		; (the words: 4096, layer 3 2048, the fixed layers 1008)
	cmp.w	#6,d0
	blo	.n
	bne	.n3
	move.w	#64*32/4-1,d1
	bra	.n
.n3:	move.w	#FSLOT/4-1,d1
.n:	move.l	ren_ltile,a0
	move.l	ren_lshd,a1
.l:	rept	2
	move.l	(a0)+,d0
	not.l	d0
	move.l	d0,(a1)+
	endr
	dbf	d1,.l
.r:	rts

; The fixed layer's tiles (28 rows R of 36 columns C, the words at (R * 36 + C) * 2) drawn into its image where they
; differ from its shadow: image rows 8 C .., the byte column 27 - R.
ren_frefresh:
	bsr	ren_shadow_tag
	move.l	ren_ltile,a3
	move.l	ren_lshd,a4
	move.w	#FSLOT-1,d6
.c:	cmpm.w	(a3)+,(a4)+
	bne	.draw
.same:	dbf	d6,.c
	rts
.draw:	move.w	-2(a3),-2(a4)
	movem.l	d6/a3-a4,-(sp)
	move.l	a3,d1			; R, C from the word's index
	sub.l	ren_ltile,d1
	subq.w	#2,d1
	lsr.w	#1,d1
	divu	#36,d1
	move.w	d1,d6			; R
	swap	d1
	move.w	d1,d5			; C
	move.w	-2(a3),d0
	and.w	#$3FFF,d0
	move.w	d5,d1			; rows 8 C ..
	lsl.w	#3,d1
	move.w	d1,d2
	mulu	#FIX_ROW,d2
	move.l	ren_limg,a1
	add.l	d2,a1
	moveq	#27,d7
	sub.w	d6,d7			; the byte column
	add.w	d7,a1
	mulu	#FIX_RB,d1
	move.l	ren_lmsk,a2
	add.l	d1,a2
	add.w	d7,a2
	move.w	#FIX_RB,d3
	move.w	#FIX_ROW,d4
	move.w	d5,-(sp)
	move.w	#FIX_RB,d5
	sf	ren_tchg
	bsr	ren_tile
	move.w	(sp)+,d5
	tst.b	ren_tchg		; (the image unchanged: nothing stale)
	beq	.dn
	st	ren_fdrawn
	move.w	d5,d1			; its 8 rows' run lists stale
	lsl.w	#3,d1
	move.l	ren_lrd,a0
	add.w	d1,a0
	move.l	#$01010101,(a0)+
	move.l	#$01010101,(a0)
.dn:	movem.l	(sp)+,d6/a3-a4
	bra	.same

; d0.w = a character, a1 = its first image row's byte (plane 0), a2 = its first mask byte, d3 = the plane stride, d4 =
; the image row stride, d5 = the mask row stride: its 8 rows converted through the bank's spread table (ren_lbank).
; Layer 0 with locked layers: their pixels in its holes (ren_lock_fill; ren_tX / ren_tk the tile's first image row /
; column).
ren_tile:
	move.w	ren_ly,d1		; (counted per layer: ren_ntiles)
	add.w	d1,d1
	add.w	d1,d1
	lea	ren_ntiles,a0
	addq.l	#1,(a0,d1.w)
	moveq	#0,d1
	move.w	d0,d1
	lsl.l	#6,d1
	lea	ren_chr,a4
	add.l	d1,a4
	lsr.l	#3,d1
	lea	ren_mask,a5
	add.l	d1,a5
	move.w	ren_lbank,d1
	moveq	#10,d2
	lsl.w	d2,d1
	lea	ren_bspread,a3
	add.w	d1,a3
	moveq	#8-1,d7
.ln:	moveq	#0,d6
	rept	8
	moveq	#0,d1
	move.b	(a4)+,d1
	add.w	d1,d1
	add.w	d1,d1
	add.l	d6,d6
	or.l	(a3,d1.w),d6
	endr
	move.b	(a5)+,d0		; the row's mask
	tst.w	ren_ly
	bne	.put
	cmp.b	#$FF,d0
	beq	.put
	tst.w	ren_nlock
	beq	.hole
	moveq	#7,d1
	sub.w	d7,d1			; dr
	bsr	ren_lock_fill
	bra	.put
.hole:	moveq	#0,d1			; (layer 0's holes black: the terrain is copied whole)
	move.b	d0,d1
	move.w	d1,d2
	lsl.w	#8,d2
	or.w	d2,d1
	move.w	d1,d2
	swap	d1
	move.w	d2,d1
	and.l	d1,d6
.put:	move.l	a1,a0			; (the bytes that change: ren_tchg)
	rol.l	#8,d6
	cmp.b	(a0),d6			; plane 0
	beq	.p0
	move.b	d6,(a0)
	st	ren_tchg
.p0:	add.w	d3,a0
	rol.l	#8,d6
	cmp.b	(a0),d6
	beq	.p1
	move.b	d6,(a0)
	st	ren_tchg
.p1:	add.w	d3,a0
	rol.l	#8,d6
	cmp.b	(a0),d6
	beq	.p2
	move.b	d6,(a0)
	st	ren_tchg
.p2:	add.w	d3,a0
	rol.l	#8,d6
	cmp.b	(a0),d6
	beq	.p3
	move.b	d6,(a0)
	st	ren_tchg
.p3:	cmp.b	(a2),d0
	beq	.pm
	move.b	d0,(a2)
	st	ren_tchg
.pm:	add.w	d4,a1
	add.w	d5,a2
	dbf	d7,.ln
	rts

; ren_tile's row dr (d1.w) of layer 0: d6.l = its 4 plane bytes, d0.b = its mask: the holes from the locked layers
; (ren_lockl, top first; image row ren_tX + dr + their row offset, column ren_tk + dc + their column offset), d6 / d0
; updated.  Per locked layer its image row's 8 columns: one character row (the offset's columns a multiple of 8) or
; two, each converted whole and shifted into place.  Keeps everything else.
ren_lock_fill:
	movem.l	d1-d5/d7/a0/a3-a6,-(sp)
	moveq	#0,d2			; the holes' bits replicated: their old plane bits cleared
	move.b	d0,d2
	not.b	d2
	move.b	d2,d3
	lsl.w	#8,d3
	move.b	d2,d3
	move.w	d3,d2
	swap	d2
	move.w	d3,d2
	not.l	d2
	and.l	d2,d6
	move.w	d1,a5			; dr
	moveq	#0,d5			; the locked layers, top first
.lay:	cmp.w	ren_nlock,d5
	bhs	.done
	cmp.b	#$FF,d0
	beq	.done			; (no holes left)
	move.w	d5,d1
	add.w	d1,d1
	lea	ren_lockl,a0
	move.w	(a0,d1.w),d4		; j
	move.w	ren_tX,d2		; Xj = (X + dr + dr_j) & 511
	add.w	a5,d2
	lea	ren_lockdr,a0
	add.w	(a0,d1.w),d2
	and.w	#511,d2
	move.w	ren_tk,d3		; kj = (k + dc_j) & (hj - 1), the row's column 0
	lea	ren_lockdc,a0
	add.w	(a0,d1.w),d3
	move.w	#511,d7
	cmp.w	#3,d4
	bne	.hj
	move.w	#255,d7
.hj:	and.w	d7,d3
	lea	ren_lockbank,a0		; its bank's spread table
	moveq	#0,d1
	move.b	(a0,d4.w),d1
	moveq	#10,d7
	lsl.w	d7,d1
	lea	ren_bspread,a3
	add.w	d1,a3
	moveq	#7,d1
	and.w	d3,d1			; s: the column's offset in its character
	bne	.two
	bsr	.tl			; (one character: its row as it is)
	move.w	a4,d7
	bra	.mrg
.two:	sub.w	d1,d3			; character A: its columns s .. 7 to the row's 0 .. 7 - s
	move.w	d1,-(sp)
	bsr	.tl
	move.w	(sp),d7
	lsl.l	d7,d1
	lea	ren_lfhi,a0
	add.w	d7,d7
	add.w	d7,d7
	and.l	(a0,d7.w),d1
	move.l	d1,-(sp)
	move.w	a4,d1
	move.w	4(sp),d7
	lsl.b	d7,d1
	move.w	d1,-(sp)
	addq.w	#8,d3			; character B: its columns 0 .. s - 1 to the row's 8 - s .. 7
	move.w	#511,d7
	cmp.w	#3,d4
	bne	.hj2
	move.w	#255,d7
.hj2:	and.w	d7,d3
	bsr	.tl
	moveq	#8,d7
	sub.w	6(sp),d7		; 8 - s
	lsr.l	d7,d1
	move.w	6(sp),d7
	lea	ren_lfhi,a0
	add.w	d7,d7
	add.w	d7,d7
	move.l	(a0,d7.w),d7
	not.l	d7
	and.l	d7,d1
	or.l	2(sp),d1		; the planes
	move.w	a4,d3
	moveq	#8,d7
	sub.w	6(sp),d7
	lsr.b	d7,d3
	move.w	(sp),d7
	or.b	d3,d7			; the mask
	addq.l	#8,sp
.mrg:	move.b	d0,d3			; the holes it fills: not layer 0's, its opaque pixels
	not.b	d3
	and.b	d7,d3
	beq	.ln
	or.b	d3,d0
	move.b	d3,d2			; replicated into the 4 plane bytes
	lsl.w	#8,d2
	move.b	d3,d2
	move.w	d2,d3
	swap	d2
	move.w	d3,d2
	and.l	d2,d1
	or.l	d1,d6
.ln:	addq.w	#1,d5
	bra	.lay
.done:	movem.l	(sp)+,d1-d5/d7/a0/a3-a6
	rts
; a locked layer's character row: d2.w = Xj, d3.w = kj (a multiple of 8, in the layer's columns), d4.w = j, a3 = the
; spread table -> d1.l = its 4 plane bytes (column 0 bit 7), a4.w = its mask byte.  Uses d7, a0.
.tl:	move.w	d3,d1
	lsr.w	#3,d1			; the column block
	moveq	#63,d7
	cmp.w	#3,d4
	bne	.t1
	moveq	#31,d7
.t1:	sub.w	d1,d7			; the y block
	lsl.w	#6,d7
	move.w	d2,d1
	lsr.w	#3,d1
	add.w	d1,d7
	add.w	d7,d7
	move.w	d4,d1
	ror.w	#3,d1			; (j * $2000)
	add.w	d1,d7
	lea	vio+VIO_TILE,a0
	moveq	#0,d1
	move.w	(a0,d7.w),d1
	and.w	#$3FFF,d1		; the character
	lsl.l	#3,d1
	moveq	#7,d7
	and.w	d2,d7
	add.w	d7,d1			; its row: Xj & 7
	lea	ren_mask,a0
	moveq	#0,d7
	move.b	(a0,d1.l),d7
	move.w	d7,a4
	lsl.l	#3,d1
	lea	ren_chr,a0
	add.l	d1,a0
	moveq	#0,d1
	rept	8
	moveq	#0,d7
	move.b	(a0)+,d7
	add.w	d7,d7
	add.w	d7,d7
	add.l	d1,d1
	or.l	(a3,d7.w),d1
	endr
	rts
ren_lfhi:	dc.l	$FFFFFFFF,$FEFEFEFE,$FCFCFCFC,$F8F8F8F8,$F0F0F0F0,$E0E0E0E0,$C0C0C0C0,$80808080

; d0.w = a representative pen -> d0.w = the pen whose colour the STE shows for its index.  Layer 0 is drawn with the
; bank it had when the colours were chosen (ren_l0bank); while the game shows it with another (the intro's lightning:
; banks 0 and 3 in turn) the pens of the held bank show their colours in the bank shown - a palette flash instead of
; every tile converted again (the user, 2026-11-07).  Other layers' and the sprites' pens of the same index flash
; too.  Keeps everything else.
ren_flash_pen:
	movem.l	d1-d2,-(sp)
	move.w	ren_l0bank,d2
	bmi.s	.r
	moveq	#7,d1
	and.b	vio+VIO_CTL+$18,d1	; layer 0's bank now
	sub.w	d2,d1
	beq.s	.r
	lsl.w	#8,d2
	add.w	#$800,d2		; the held bank's first pen
	neg.w	d2
	add.w	d0,d2
	cmp.w	#256,d2
	bhs.s	.r			; (not one of its pens)
	lsl.w	#8,d1
	add.w	d1,d0
.r:	movem.l	(sp)+,d1-d2
	rts

; Z clear while layer 0 flashes (shown with another bank than the one it is drawn with).  Keeps everything.
ren_flashing:
	movem.l	d0-d1,-(sp)
	move.w	ren_l0bank,d1
	bmi.s	.n
	moveq	#7,d0
	and.b	vio+VIO_CTL+$18,d0
	cmp.w	d0,d1
	bra.s	.r
.n:	cmp.w	d1,d1			; (Z: none held)
.r:	movem.l	(sp)+,d0-d1		; (movem: the flags kept)
	rts

; d0.w = a pen shown -> d0.w = the pen layer 0 drew for it (one of the bank shown while ren_flash_pen flashes: the
; held bank's).  Keeps everything else.
ren_unflash_pen:
	movem.l	d1-d2,-(sp)
	move.w	ren_l0bank,d1
	bmi.s	.r
	moveq	#7,d2
	and.b	vio+VIO_CTL+$18,d2	; layer 0's bank now
	sub.w	d2,d1			; held - now
	beq.s	.r
	lsl.w	#8,d2
	add.w	#$800,d2
	neg.w	d2
	add.w	d0,d2
	cmp.w	#256,d2
	bhs.s	.r
	lsl.w	#8,d1
	add.w	d1,d0
.r:	movem.l	(sp)+,d1-d2
	rts

; d0.w = a bank: its ren_bmap / ren_bspread for the current choice of colours (ren_bmtag)
ren_bank_ready:
	move.w	d0,d1
	add.w	d1,d1
	lea	ren_bmtag,a0
	move.w	ren_epoch,d2
	cmp.w	(a0,d1.w),d2
	beq	.r
	move.w	d2,(a0,d1.w)
	bsr	ren_bmap_make
.r:	rts

; The opaque runs of a mask row onto the buffer (a list of more than RL_MAX runs): a0 = the mask row, d0.w = the
; first column, d1.w = how many, d2.w = the picture column of the first; ren_simg = the image row (plane 0), ren_ddst
; = the buffer line, ren_pstr = the plane stride.  Whole bytes of $FF / 0 at once, else bit by bit.  Keeps d7.
ren_runs:
	move.w	d7,-(sp)
	move.w	d0,d6
	add.w	d1,d6			; the end
	sub.w	d0,d2			; picture column = column + d2
	moveq	#-1,d5			; the run's start (-1: none)
	move.w	d0,d3			; the column
.b:	cmp.w	d6,d3
	bhs	.end
	moveq	#7,d4
	and.w	d3,d4
	bne	.bit
	move.w	d3,d0
	addq.w	#8,d0
	cmp.w	d6,d0
	bhi	.bit
	move.w	d3,d0
	lsr.w	#3,d0
	move.b	(a0,d0.w),d0
	beq	.zero
	cmp.b	#$FF,d0
	bne	.bit
	tst.w	d5			; a whole byte opaque
	bpl	.on8
	move.w	d3,d5
.on8:	addq.w	#8,d3
	bra	.b
.zero:	tst.w	d5			; a whole byte transparent
	bmi	.off8
	bsr	.emit
.off8:	addq.w	#8,d3
	bra	.b
.bit:	move.w	d3,d0
	lsr.w	#3,d0
	move.b	(a0,d0.w),d0
	eor.w	#7,d4
	btst	d4,d0
	beq	.t
	tst.w	d5
	bpl	.n
	move.w	d3,d5
	bra	.n
.t:	tst.w	d5
	bmi	.n
	bsr	.emit
.n:	addq.w	#1,d3
	bra	.b
.end:	tst.w	d5
	bmi	.r
	bsr	.emit
.r:	move.w	(sp)+,d7
	rts
; the run d5 .. d3 - 1: blitted; d5 = -1
.emit:	movem.l	d0-d6/a0,-(sp)
	move.w	d3,d1
	sub.w	d5,d1			; the length
	move.w	d5,d0			; the source column
	add.w	d2,d5			; the picture column
	bsr	ren_blit_run
	movem.l	(sp)+,d0-d6/a0
	moveq	#-1,d5
	rts

; A run onto the buffer: d0.w = its first source column (bits of the plane rows at ren_simg, plane stride ren_pstr),
; d5.w = its first picture column, d1.w = its length.  A HOG pass: X count = the destination words (groups), Y count 4
; (the planes), HOP 2 / OP 3 (ren_bsetup's registers: the source's step the next plane row, the destination's the
; next plane).
ren_blit_run:
	move.w	ren_pstr,d6
	moveq	#2,d7
	bsr	ren_bsetup
	move.l	a0,$ffff8a24.w
	move.l	a1,$ffff8a32.w
	move.w	#4,$ffff8a38.w
	move.b	#$c0,$ffff8a3c.w	; HOG: at most 21 words x 4 planes read and written
	tst.b	ren_prec		; (a fixed layer's pass recorded: ren_pstream)
	beq	.r
	cmp.w	#PC_MAX,ren_pnum
	bhs	.full
	move.l	ren_ppos,a2
	move.w	ren_drow0,(a2)+
	move.l	a1,d0
	sub.l	ren_ddst,d0
	move.w	ren_xo,d1		; (without the offset's whole groups: the shift's passes serve every offset)
	lsr.w	#4,d1
	lsl.w	#3,d1
	sub.w	d1,d0
	move.w	d0,(a2)+
	move.l	a0,(a2)+
	move.w	$ffff8a22.w,(a2)+
	move.w	$ffff8a28.w,(a2)+
	move.w	$ffff8a2c.w,(a2)+
	move.w	$ffff8a30.w,(a2)+
	move.w	$ffff8a36.w,(a2)+
	move.b	$ffff8a3d.w,(a2)+
	clr.b	(a2)+
	move.l	a2,ren_ppos
	addq.w	#1,ren_pnum
.r:	rts
.full:	st	ren_pfail
	rts

; the Blitter's registers the runs share: source X inc 2, END2 $FFFF, destination X inc 8, HOP 2 / OP 3
ren_runs_setup:
	move.w	#2,$ffff8a20.w
	move.w	#-1,$ffff8a2a.w
	move.w	#8,$ffff8a2e.w
	move.w	#$0203,$ffff8a3a.w
	rts

; ---- the colours' samples of the layers ----

; d5.w = a picture row, d4.w = a column -> d0.w = the pen of the top enabled layer opaque there, or -1 (the tile RAM
; and the characters, not the images).  Keeps d1-d7.
ren_bg_pen:
	movem.l	d1-d7/a0-a2,-(sp)
	move.w	ren_nlord,d7
	lea	ren_lord,a2
	add.w	d7,a2
	add.w	d7,a2
	subq.w	#1,d7
	bmi	.none
.lay:	subq.l	#2,a2
	moveq	#0,d6
	move.b	(a2),d6			; the layer
	cmp.w	#4,d6
	bhs	.fix
	lea	vio+VIO_CTL,a0
	move.w	d6,d0
	lsl.w	#2,d0
	move.w	(a0,d0.w),d1		; X = (r + 44 + adj + sx) & 511
	add.w	d5,d1
	add.w	#44,d1
	lea	ren_adj(pc),a1
	moveq	#0,d2
	move.b	(a1,d6.w),d2
	add.w	d2,d1
	and.w	#511,d1
	move.w	2(a0,d0.w),d2		; Y = h - 1 - ((c - 248 - sy) mod h)
	neg.w	d2
	add.w	d4,d2
	sub.w	#248,d2
	move.w	#511,d3
	cmp.w	#3,d6
	bne	.h
	move.w	#255,d3
.h:	and.w	d3,d2
	sub.w	d2,d3
	move.w	d3,d2			; Y
	move.w	d2,d0			; the word: ((Y >> 3) * 64 + (X >> 3)) * 2
	lsr.w	#3,d0
	lsl.w	#6,d0
	move.w	d1,d3
	lsr.w	#3,d3
	add.w	d3,d0
	add.w	d0,d0
	move.w	d6,d3			; + layer * $2000
	ror.w	#3,d3
	add.w	d3,d0
	bra	.pix
.fix:	move.w	d5,d1			; X = r, Y = 223 - c
	move.w	#223,d2
	sub.w	d4,d2
	move.w	d2,d0			; the word: $7010 + (layer - 4) * $800 + ((Y >> 3) * 36 + (X >> 3)) * 2
	lsr.w	#3,d0
	mulu	#36,d0
	move.w	d1,d3
	lsr.w	#3,d3
	add.w	d3,d0
	add.w	d0,d0
	move.w	d6,d3
	subq.w	#4,d3
	mulu	#$800,d3
	add.w	d3,d0
	add.w	#$7010,d0
.pix:	lea	vio+VIO_TILE,a0
	move.w	(a0,d0.w),d0
	and.w	#$3FFF,d0		; the character: R[dr][dc], dr = X & 7, dc = 7 - (Y & 7)
	moveq	#0,d3
	move.w	d0,d3
	lsl.l	#3,d3
	and.w	#7,d1
	add.w	d1,d3
	lea	ren_mask,a0
	move.b	(a0,d3.l),d0		; the row's mask: bit 7 - dc = Y & 7
	and.w	#7,d2
	btst	d2,d0
	beq	.ln
	lsl.l	#3,d3
	moveq	#7,d0
	sub.w	d2,d0
	add.w	d0,d3
	lea	ren_chr,a0
	moveq	#0,d1
	move.b	(a0,d3.l),d1
	lea	vio+VIO_CTL+$18,a0
	moveq	#7,d0
	and.b	(a0,d6.w),d0
	lsl.w	#8,d0
	add.w	d1,d0
	add.w	#$800,d0
	bra	.r
.ln:	dbf	d7,.lay
.none:	moveq	#-1,d0
.r:	movem.l	(sp)+,d1-d7/a0-a2
	rts

; the background's samples for a choice: two pixels a cell ((8R + 2, 8C + 2), (8R + 5, 8C + 5)), weight 1
ren_sample_bg:
	moveq	#0,d6			; R
.r:	moveq	#0,d7			; C
.c:	move.w	d6,d5
	lsl.w	#3,d5
	addq.w	#2,d5
	move.w	d7,d4
	lsl.w	#3,d4
	addq.w	#2,d4
	bsr	ren_bg_pen
	tst.w	d0
	bmi	.n1
	moveq	#1,d1
	bsr	ren_hist_add
.n1:	addq.w	#3,d5
	addq.w	#3,d4
	bsr	ren_bg_pen
	tst.w	d0
	bmi	.n2
	moveq	#1,d1
	bsr	ren_hist_add
.n2:	addq.w	#1,d7
	cmp.w	#CCOLS,d7
	bne	.c
	addq.w	#1,d6
	cmp.w	#CROWS,d6
	bne	.r
	rts

; d0.w = how well the STE colours fit now: the mean L1 Oklab distance (bytes) between the current colour of the pens
; on the picture (the sprites of the last picture: a pixel each; 126 points of the background) and the current STE
; colour of their index (its representative's current colour).
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
.done:	moveq	#0,d3			; 126 points: every 8th cell's (4, 4)
.bc:	moveq	#0,d5
	move.w	d3,d5
	divu	#CCOLS,d5
	move.w	d5,d1
	swap	d5
	move.w	d5,d4
	lsl.w	#3,d4
	addq.w	#4,d4
	move.w	d1,d5
	lsl.w	#3,d5
	addq.w	#4,d5
	bsr	ren_bg_pen
	tst.w	d0
	bmi	.bn
	bsr	ren_pen_err
.bn:	addq.w	#8,d3
	cmp.w	#NCELLS,d3
	blo	.bc
	move.l	d6,d0
	tst.w	d7
	beq	.r
	divu	d7,d0
.r:	movem.l	(sp)+,d1-d7/a0-a6
	rts

; d6.l = a checksum of sampled pens (every 16th of the enabled layers' banks, every 32nd sprite pen), d7.b their OR
ren_pal_sum:
	moveq	#0,d6
	moveq	#0,d7
	lea	vio+VIO_CTL+$18,a1
	moveq	#0,d5
.l:	lea	vio+VIO_CTL+$10,a0
	btst	#3,(a0,d5.w)
	bne	.nl
	moveq	#7,d0
	and.b	(a1,d5.w),d0
	lsl.w	#8,d0
	lea	vio+VIO_PAL+$800,a0
	add.w	d0,a0
	moveq	#16-1,d4
	moveq	#16,d3
	bsr	.sum
.nl:	addq.w	#1,d5
	cmp.w	#6,d5
	bne	.l
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

; ---- a choice of colours ----
; The palette now as the mapping's (ren_palsnap); the histogram of the 4 bit colours of the samples (ren_hist,
; ren_hpen: a pen of each); the entries (Oklab, the root of the count); the median cut into up to 15 boxes, 3 rounds
; of k-means; per centre the representative (the entry nearest it); every mapping, tile image and sprite stale (the
; epoch: the tiles' stamps, the banks' maps).
ren_choose:
	movem.l	d0-d7/a0-a6,-(sp)
	addq.l	#1,ren_choices
	moveq	#7,d0			; (layer 0 drawn with this bank until the next choice: ren_flash_pen)
	and.b	vio+VIO_CTL+$18,d0
	move.w	d0,ren_l0bank
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
	addq.w	#1,ren_epoch		; (the tiles, the banks' maps)
	and.w	#$0FFF,ren_epoch
	bne	.e
	move.w	#1,ren_epoch
.e:	bsr	ren_cache_clear		; (the sprites)
	movem.l	(sp)+,d0-d7/a0-a6
	rts

; ---- the sprites ----

; ren_slst: the entries on the picture (0-126, the arcade's draw goes from 126 down: a later entry here is drawn
; later, on top), SL bytes each; ren_slend
SL = 16				; (ren_slst: r0, c0, rows, columns, the key.l, colour, priority.b, 0.b)
ren_sprite_list:
	lea	vio+VIO_SPR,a6
	bsr	ren_spr_offsets
	lea	ren_slst,a5
	moveq	#0,d7
.l:	movem.l	d7/a5-a6,-(sp)
	bsr	ren_spr_geom
	movem.l	(sp)+,d7/a5-a6
	beq	.n
	move.w	ren_sr0,(a5)+
	move.w	ren_sc0,(a5)+
	move.w	ren_ssx,(a5)+
	move.w	ren_ssy,(a5)+
	move.l	ren_skey,(a5)+
	move.w	ren_scol,(a5)+
	move.b	ren_spri,(a5)+
	clr.b	(a5)+
.n:	lea	16(a6),a6
	addq.w	#1,d7
	cmp.w	#127,d7
	bne	.l
	move.l	a5,ren_slend
	rts

; d7.w = a priority: the listed entries of it drawn
ren_sprites:
	lea	ren_slst,a5
.l:	cmp.l	ren_slend,a5
	bhs	.r
	cmp.b	14(a5),d7
	bne	.n
	bsr	ren_sl_get
	movem.l	d7/a5,-(sp)
	bsr	ren_cache_get		; a0 = the image (rows.w, then per row mask.l, 4 plane .l)
	bsr	ren_draw
	movem.l	(sp)+,d7/a5
.n:	lea	SL(a5),a5
	bra	.l
.r:	rts

; a5 = an entry of ren_slst -> the ren_s* variables
ren_sl_get:
	move.w	(a5),ren_sr0
	move.w	2(a5),ren_sc0
	move.w	4(a5),ren_ssx
	move.w	6(a5),ren_ssy
	move.l	8(a5),ren_skey
	move.w	12(a5),ren_scol
	move.b	14(a5),ren_spri
	rts

; a6 = an entry -> ren_sr0 / ren_sc0 (its top left), ren_ssx / ren_ssy (rows, columns), ren_skey / ren_scol / ren_spri;
; Z set when it is not on the picture (or its colour is $7F: the shadow, not drawn)
ren_spr_geom:
	moveq	#0,d4			; x = (b13 + (b12 & 1) * 256 + xoffs) & $1FF; r0 = x - 73
	move.b	12(a6),d4
	and.w	#1,d4
	lsl.w	#8,d4
	move.b	13(a6),d4
	add.w	ren_xoffs,d4
	and.w	#$1FF,d4
	sub.w	#73,d4
	moveq	#0,d0
	move.b	10(a6),d0		; attr1: size x 7-6, flip x 5, tx 4-3, code high 2-0
	lea	ren_sxt,a1
	moveq	#0,d1
	move.b	(a1,d0.w),d1		; sizex
	cmp.w	#PIC_H,d4
	bge	.out
	move.w	d4,d5
	add.w	d1,d5
	ble	.out
	moveq	#0,d2
	move.b	14(a6),d2		; attr2: priority 7-5, ty 4-3, size y 2-1, flip y 0
	move.w	d2,d3
	lsr.w	#1,d3
	and.w	#3,d3
	lea	REN_SIZE(pc),a1
	move.b	(a1,d3.w),d3
	ext.w	d3			; sizey
	moveq	#17,d5			; y = ((17 - b15 - sizey - yoffs) & $FF) - 16; c0 = 240 - y - sizey
	moveq	#0,d6
	move.b	15(a6),d6
	sub.w	d6,d5
	sub.w	d3,d5
	sub.w	ren_yoffs,d5
	and.w	#$FF,d5
	sub.w	#16,d5
	move.w	#240,d6
	sub.w	d5,d6
	sub.w	d3,d6			; c0
	add.w	#X0,d6			; (screen x)
	cmp.w	#PIC_W,d6
	bge	.out
	move.w	d6,d5
	add.w	d3,d5
	ble	.out
	moveq	#0,d5
	move.b	12(a6),d5
	lsr.b	#1,d5			; the colour (0-127)
	cmp.b	#$7F,d5
	beq	.out
	move.w	d5,ren_scol
	move.w	d4,ren_sr0
	move.w	d6,ren_sc0
	move.w	d1,ren_ssx
	move.w	d3,ren_ssy
	lsr.b	#5,d2
	move.b	d2,ren_spri
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
	moveq	#1,d0			; (Z clear)
	rts
.out:	moveq	#0,d0
	rts

; d0.w = a sprite code -> a1 = its turned image (ren_spr; 1152-1279: 1024-1151 again, from 1280 on zeros, pen 0
; everywhere, as MAME's region).  Keeps everything else.
ren_spr_image:
	cmp.w	#1280,d0
	bhs	.z
	move.l	d0,-(sp)
	and.l	#$7FF,d0
	cmp.w	#NSPR,d0
	blo	.c
	sub.w	#128,d0
.c:	lsl.l	#8,d0
	add.l	d0,d0
	lea	ren_spr,a1
	add.l	d0,a1
	move.l	(sp)+,d0
	rts
.z:	lea	ren_spr_zero,a1
	rts

; ---- a sprite onto the buffer: a0 = its image, ren_sr0 / ren_sc0 the picture row / column of its top left ----
; (Galaga '88's ren_draw.)  A HOG pass a line: X count 3 (the groups at x and the two after), Y count 4 (the planes),
; the source the row's plane longs (16-bit words, the skew shifts them), the end masks the row's opaque mask shifted;
; groups left of the picture (x < 48) or right of it (x >= 272) get end mask 0 (the side bands stay clean).  Rows from
; -32 and to 319 are in the guard lines.
ren_draw:
	move.w	(a0)+,d7		; rows
	move.w	ren_sc0,d0		; x (the buffer's)
	add.w	ren_xo,d0
	moveq	#15,d6
	and.w	d0,d6			; the skew
	asr.w	#4,d0			; the first group (1-16)
	move.w	d0,d1
	move.w	d1,d2			; the end mask of each of the 3 groups: the C116 window's columns (x 48 + cmin ..
	bsr	ren_win_mask		; 48 + cmax, inside the picture's groups 3-16)
	move.w	d0,ren_em1
	addq.w	#1,d2
	bsr	ren_win_mask
	move.w	d0,ren_em2
	addq.w	#1,d2
	bsr	ren_win_mask
	move.w	d0,ren_em3
	move.w	ren_sr0,ren_hrow	; (the row of the next pass: rows outside the window are skipped)
	tst.b	ren_dmgon		; (the damage: its rows, its 3 groups)
	beq	.nd
	movem.l	d0-d3,-(sp)
	move.w	d1,d2
	move.w	d1,d3
	addq.w	#2,d3
	move.w	ren_sr0,d0
	move.w	ren_ssx,d1
	bsr	ren_dmg
	movem.l	(sp)+,d0-d3
.nd:	move.w	ren_vs,d2		; the destination of the first row: line ren_vs + r0 - CROP_TOP, + group * 8
	sub.w	#CROP_TOP,d2
	add.w	ren_sr0,d2
	muls	#LINEB,d2
	lsl.w	#3,d1
	ext.l	d1
	add.l	d1,d2
	move.l	ren_dst,a1
	add.l	d2,a1
	lea	$ffff8a20.w,a3		; the Blitter: source X inc 2, Y inc 2, destination X inc 8, Y inc -14 (the next plane)
	move.w	#2,(a3)+
	move.w	#2,(a3)+		; (with NFSR the read before the skipped one steps by the Y increment, as in Hatari)
	addq.l	#4,a3
	addq.l	#6,a3			; (end masks per row)
	move.w	#8,(a3)+
	move.w	#-14,(a3)+
	move.w	#3,$ffff8a36.w
	move.w	#$0203,$ffff8a3a.w
	moveq	#0,d5			; (the mask of the row drawn before: none)
	move.b	d6,d0			; skew, NFSR: the source's two words into three destination words
	or.b	#$40,d0
	move.b	d0,$ffff8a3d.w
	subq.w	#1,d7
.row:	move.l	(a0)+,d0		; the mask (bit 31 = column 0)
	move.w	ren_hrow,d1		; (a row outside the window: no pass)
	addq.w	#1,ren_hrow
	cmp.w	ren_rmin,d1
	blt	.skip
	cmp.w	ren_rmax,d1
	bgt	.skip
	tst.l	d0			; (a row without pixels: no pass; the mask of the row drawn before: the end
	beq	.skip			; masks as they are)
	cmp.l	d5,d0
	beq	.same
	move.l	d0,d5
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
.same:	move.l	a0,$ffff8a24.w
	move.l	a1,$ffff8a32.w
	move.w	#4,$ffff8a38.w
	move.b	#$c0,$ffff8a3c.w	; HOG: 4 x 3 words (and the source's 8), well under 256 bus cycles
.skip:	lea	16(a0),a0
	lea	LINEB(a1),a1
	dbf	d7,.row
	rts

; d2.w = a group (x 16 g .. 16 g + 15) -> d0.w = its pixels inside the window's columns (x 48 + cmin .. 48 + cmax).
; Keeps d1-d7.
ren_win_mask:
	movem.l	d1-d3,-(sp)
	lsl.w	#4,d2			; the group's first x
	move.w	ren_wmin,d0		; lo = max(16 g, wmin) - 16 g (the window's columns in the buffer)
	sub.w	d2,d0
	bpl	.lo
	moveq	#0,d0
.lo:	move.w	ren_wmax,d1		; hi = min(16 g + 15, wmax) - 16 g
	sub.w	d2,d1
	cmp.w	#15,d1
	ble	.hi
	moveq	#15,d1
.hi:	cmp.w	d1,d0
	bgt	.none
	cmp.w	#15,d0
	bgt	.none
	moveq	#-1,d3			; $FFFF >> lo & $FFFF << (15 - hi)
	lsr.w	d0,d3
	moveq	#15,d2
	sub.w	d1,d2
	moveq	#-1,d0
	lsl.w	d2,d0
	and.w	d3,d0
	movem.l	(sp)+,d1-d3
	rts
.none:	moveq	#0,d0
	movem.l	(sp)+,d1-d3
	rts
