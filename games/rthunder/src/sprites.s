; Rolling Thunder's sprites (and the fixed layer's text) drawn over a display buffer, the stefastbobs2 way: HOP 2 / OP 3
; passes whose end masks are the opaque pixels, all four planes in one pass (destination X increment 8, Y count 4, the
; destination Y increment back to the next plane), the source in pass order (the pass leaves the source address at the next
; row), the shift in the pass (skew, NFSR: c source words cover c + 1 destination words), only the registers that change
; written between passes.
;
; A part (a sprite's sub-rectangle with its flips and colour row, key = desc) is made on first use (part_make) and kept in
; `spcache` (direct mapped, SPC_SIZE bytes a slot; the parts of the coverage's runs are made at build time: tools/parts.py,
; ren_parts.bin / ren_pidx.bin, looked up first): +0 key.l, +4 rows.w, +6 groups.w, +8 c.w (the source words a row and plane: 1 up
; to 16 pixels, 2 up to 32), +10 the rows' offset.w, +12 the row groups (6 bytes: rows.w, the opaque mask.l left justified), then
; the rows: per row the planes 0-3 one after the other, c words each.  The fixed layer's runs of tiles are kept in `rpcache`.
;
; desc: bits 0-9 sprite code, 10-16 colour row, 17 flip x, 18 flip y, 19-20 width index (16 8 32 4), 21-22 height index,
; 23-24 x offset in the 32 x 32 image / 8, 25-26 y offset / 8, 31 set.  The sprite ROM (ren_spr.bin) holds 1024 images of
; 32 x 32 pixels, 4 bits each (high nibble first); ren_spm.bin the STE index of colour row * 16 + pen (pen 15 = transparent).
;
; The picture: a sprite at (x, y) on the arcade's canvas lies in the buffer at (x + 13 + ren_wx, y + 16 + ren_wy); sprites
; wholly outside the window are left out, the others drawn whole (the margins and guard lines take what lies outside).  The
; rectangles drawn are kept per display buffer (dmg_list) and copied back from the clean buffer before the next picture.

SPC_SIZE = 720
SPC_SLOTS = 128
RPC_SLOTS = 512
IDX_SLOTS = 8192
DMG_MAX = 600

	section text,code

; ---- ren_sprites: the picture's sprites over the display buffer ren_buf (ren_update has brought it up to date): the rectangles
; of its last picture restored from the clean buffer, then the sprites by priority k (the fixed layer's text after k = 6) ----
ren_sprites:
	movem.l	d0-d1,-(sp)
	bsr	dmg_restore
	bsr	spr_build
	moveq	#0,d0
.k:	cmp.w	#7,d0
	bne.s	.d
	bsr	l3_draw
	moveq	#7,d0
.d:	bsr	spr_draw_k
	addq.w	#1,d0
	cmp.w	#8,d0
	bne.s	.k
	movem.l	(sp)+,d0-d1
	rts

; ---- spr_build: the visible entries of the sprite list (the displayed attributes, bytes 10-15 of a 16 byte entry) into
; splist: bx.w, by.w, desc.l, k.b, width.b, height.b ----
spr_build:
	movem.l	d0-d7/a0-a2,-(sp)
	lea	shared+$1800,a0
	moveq	#0,d0
	move.b	$7F5(a0),d0
	moveq	#0,d1
	move.b	$7F4(a0),d1
	and.w	#1,d1
	lsl.w	#8,d1
	add.w	d1,d0
	move.w	d0,pm_xoffs
	moveq	#0,d0
	move.b	$7F7(a0),d0
	move.w	d0,pm_yoffs
	lea	splist,a2
	clr.w	spl_n
	move.l	a0,a1
	move.w	#127,spl_i
.e:	moveq	#0,d1
	move.b	14(a1),d1		; attr2
	move.w	d1,d3
	and.w	#6,d3
	lsl.w	#7,d3			; the height index * 256
	moveq	#0,d6
	move.b	15(a1),d6
	add.b	pm_yoffs+1,d6
	lea	ren_yvis,a0
	add.w	d3,a0
	tst.b	(a0,d6.w)
	beq	.skip			; (above the picture or below it)
	moveq	#0,d0
	move.b	10(a1),d0		; attr1
	move.w	d0,d2
	lsr.w	#6,d2			; width index
	move.w	d1,d3
	and.w	#6,d3
	lsr.w	#1,d3			; height index
	lea	sizetab,a0
	moveq	#0,d4
	move.b	(a0,d2.w),d4		; width
	moveq	#0,d5
	move.b	(a0,d3.w),d5		; height
	moveq	#0,d6			; the canvas x: left or right of the window: no
	move.b	13(a1),d6
	move.b	12(a1),d7
	and.w	#1,d7
	lsl.w	#8,d7
	add.w	d7,d6
	add.w	pm_xoffs,d6
	and.w	#$1FF,d6
	move.w	d6,pm_x
	move.w	d6,d7
	add.w	d4,d7
	cmp.w	#51,d7
	ble	.skip
	cmp.w	#371,d6
	bge	.skip
	moveq	#0,d6
	move.b	15(a1),d6
	neg.w	d6
	sub.w	d5,d6
	sub.w	pm_yoffs,d6
	add.w	#17,d6			; (sy + 1 + 16)
	and.w	#$FF,d6
	sub.w	#16,d6			; the canvas y
	move.w	d6,d7
	add.w	d5,d7
	cmp.w	#16,d7
	ble	.skip			; above the picture
	cmp.w	#240,d6
	bge	.skip			; below it
	moveq	#19,d7
	lsl.l	d7,d2
	moveq	#21,d7
	lsl.l	d7,d3
	or.l	d3,d2			; the size indices
	moveq	#0,d3
	move.b	11(a1),d3
	and.w	#127,d3
	move.w	d0,d7
	and.w	#7,d7
	lsl.w	#7,d7
	or.w	d7,d3			; the code
	or.l	d3,d2
	moveq	#0,d3
	move.b	12(a1),d3		; the colour byte
	move.w	d3,d7
	and.w	#1,d7
	lsl.w	#8,d7			; x bit 8
	lsr.w	#1,d3
	moveq	#10,d0
	lsl.l	d0,d3
	or.l	d3,d2			; the colour row
	move.w	pm_x,d3			; the canvas x
	add.w	#13,d3
	add.w	ren_wx,d3
	move.w	d3,(a2)			; bx
	add.w	#16,d6
	add.w	ren_wy,d6
	move.w	d6,2(a2)		; by
	moveq	#0,d0
	move.b	10(a1),d0
	btst	#5,d0
	beq.s	.nfx
	bset	#17,d2
.nfx:	btst	#0,d1
	beq.s	.nfy
	bset	#18,d2
.nfy:	move.w	d0,d3			; the offsets into the 32 x 32 image: (attr & $18) & ~(size - 1), / 8
	and.w	#$18,d3
	move.w	d4,d7
	subq.w	#1,d7
	not.w	d7
	and.w	d7,d3
	lsr.w	#3,d3
	moveq	#23,d7
	lsl.l	d7,d3
	or.l	d3,d2
	move.w	d1,d3
	and.w	#$18,d3
	move.w	d5,d7
	subq.w	#1,d7
	not.w	d7
	and.w	d7,d3
	lsr.w	#3,d3
	moveq	#25,d7
	lsl.l	d7,d3
	or.l	d3,d2
	bset	#31,d2
	move.l	d2,4(a2)
	lsr.w	#5,d1
	move.b	d1,8(a2)
	move.b	d4,9(a2)
	move.b	d5,10(a2)
	lea	16(a2),a2
	addq.w	#1,spl_n
.skip:	lea	16(a1),a1
	subq.w	#1,spl_i
	bne	.e
	movem.l	(sp)+,d0-d7/a0-a2
	rts
sizetab:
	dc.b	16,8,32,4

; ---- spr_draw_k: d0.w = the priority k: every record of splist with it, in list order (the lowest entry first) ----
spr_draw_k:
	movem.l	d0-d7/a0-a2,-(sp)
	lea	splist,a1
	move.w	spl_n,d7
	beq.s	.out
	subq.w	#1,d7
.r:	cmp.b	8(a1),d0
	bne.s	.next
	movem.l	d0/d7/a1,-(sp)
	move.l	4(a1),d0
	bsr	part_get
	move.w	(a1),d1
	move.w	2(a1),d2
	bsr	spr_blit
	moveq	#0,d3
	move.b	9(a1),d3
	moveq	#0,d4
	move.b	10(a1),d4
	bsr	dmg_add
	movem.l	(sp)+,d0/d7/a1
.next:	lea	16(a1),a1
	dbf	d7,.r
.out:	movem.l	(sp)+,d0-d7/a0-a2
	rts

; ---- dmg_add: d1 = x, d2 = line, d3 = width, d4 = height: the rectangle (whole 16 pixel groups) into the buffer ren_buf's list ----
dmg_add:
	movem.l	d0-d6/a0,-(sp)
	move.w	ren_buf,d0
	move.w	d0,d5
	add.w	d5,d5
	lea	dmg_n,a0
	move.w	(a0,d5.w),d6
	cmp.w	#DMG_MAX,d6
	bhs.s	.full
	addq.w	#1,(a0,d5.w)
	mulu	#DMG_MAX*8,d0
	lea	dmg_list,a0
	add.l	d0,a0
	lsl.w	#3,d6
	add.w	d6,a0
	move.w	d1,d5
	lsr.w	#4,d5			; the first group
	add.w	d3,d1
	subq.w	#1,d1
	lsr.w	#4,d1
	sub.w	d5,d1
	addq.w	#1,d1			; groups
	mulu	#RB_LB,d2
	lsl.w	#3,d5
	and.l	#$FFFF,d5
	add.l	d5,d2
	move.l	d2,(a0)+
	move.w	d1,(a0)+
	move.w	d4,(a0)
.full:	movem.l	(sp)+,d0-d6/a0
	rts

; ---- spr_blit: part a0, d1 = buffer x, d2 = buffer line: drawn into the display buffer ds_base ----
spr_blit:
	movem.l	d0-d7/a0-a6,-(sp)
	move.w	d2,d3
	mulu	#RB_LB,d3
	move.w	d1,d4
	lsr.w	#4,d4
	lsl.w	#3,d4
	and.l	#$FFFF,d4
	add.l	d4,d3
	add.l	ds_base,d3
	move.l	d3,a5			; the destination, a row
	and.w	#15,d1			; the shift
	move.w	8(a0),a6		; c
	move.w	#2,$ffff8a20.w
	move.w	#2,$ffff8a22.w
	move.w	#8,$ffff8a2e.w
	move.w	a6,d6
	lsl.w	#3,d6
	neg.w	d6
	addq.w	#2,d6
	move.w	d6,$ffff8a30.w
	move.w	a6,d6
	addq.w	#1,d6
	move.w	d6,$ffff8a36.w
	move.w	#$0203,$ffff8a3a.w	; HOP 2 (source), OP 3 (copy)
	move.w	d1,d6
	or.w	#$40,d6			; NFSR
	move.b	d6,$ffff8a3d.w
	move.w	10(a0),d0
	lea	(a0,d0.w),a3
	lea	12(a0),a4
	move.w	6(a0),d7
	subq.w	#1,d7
	lea	$ffff8a3c.w,a0		; the start register
	lea	$ffff8a32.w,a1		; the destination address
	lea	$ffff8a38.w,a2		; the Y count
	moveq	#4,d4			; (the planes)
	move.w	#$c0,d3			; (HOG, busy)
.g:	move.w	(a4)+,d5		; the group's rows
	move.l	(a4)+,d2		; their opaque mask, left justified
	move.w	d5,d6
	lsl.w	#3,d6			; the group's source bytes: 8 c a row
	cmpa.w	#2,a6
	bne.s	.b8
	add.w	d6,d6
.b8:	tst.l	d2
	bne.s	.go
	add.w	d6,a3			; (rows of transparent pixels: nothing drawn)
	move.w	d5,d6
	mulu	#RB_LB,d6
	add.l	d6,a5
	dbf	d7,.g
	bra.s	.end
.go:	move.l	a3,$ffff8a24.w
	add.w	d6,a3
	move.l	d2,d0
	lsr.l	d1,d0
	move.w	d0,$ffff8a2c.w		; (one word: the last)
	swap	d0
	move.w	d0,$ffff8a28.w		; the first
	cmpa.w	#2,a6
	bne.s	.rows
	move.l	d2,d0
	lsr.l	d1,d0
	move.w	d0,$ffff8a2a.w		; the middle one: the second word
	move.w	d1,d6
	moveq	#16,d0
	sub.w	d6,d0
	move.l	d2,d6
	lsl.l	d0,d6
	move.w	d6,$ffff8a2c.w		; the third
.rows:	subq.w	#1,d5
.r:	move.l	a5,(a1)
	move.w	d4,(a2)
	move.b	d3,(a0)
	lea	RB_LB(a5),a5
	dbf	d5,.r
	dbf	d7,.g
.end:	clr.b	$ffff8a3d.w
	movem.l	(sp)+,d0-d7/a0-a6
	rts

; ---- dmg_restore: the rectangles the buffer ren_buf had are copied back from the clean buffer ----
dmg_restore:
	movem.l	d0-d7/a0-a3,-(sp)
	move.w	ren_buf,d0
	move.w	d0,d1
	add.w	d1,d1
	lea	dmg_n,a0
	move.w	(a0,d1.w),d7
	clr.w	(a0,d1.w)
	tst.w	d7
	beq	.out
	subq.w	#1,d7
	mulu	#DMG_MAX*8,d0
	lea	dmg_list,a0
	add.l	d0,a0
	move.w	#2,$ffff8a20.w
	move.w	#2,$ffff8a2e.w
	move.w	#$FFFF,$ffff8a28.w
	move.w	#$FFFF,$ffff8a2a.w
	move.w	#$FFFF,$ffff8a2c.w
	move.w	#$0203,$ffff8a3a.w
	clr.b	$ffff8a3d.w
	move.w	ren_buf,d0
	lsl.w	#2,d0
	lea	dbuf_tab,a3
	move.l	(a3,d0.w),a3
.d:	move.l	(a0)+,d0		; the offset
	move.w	(a0)+,d1		; the groups
	move.w	(a0)+,d2		; the lines
	lea	ren_bg,a1
	add.l	d0,a1
	move.l	a1,$ffff8a24.w
	move.l	a3,a2
	add.l	d0,a2
	move.l	a2,$ffff8a32.w
	move.w	d1,d3
	lsl.w	#3,d3
	neg.w	d3
	add.w	#RB_LB+2,d3
	move.w	d3,$ffff8a22.w
	move.w	d3,$ffff8a30.w
	move.w	d1,d3
	lsl.w	#2,d3
	move.w	d3,$ffff8a36.w
	move.w	d2,$ffff8a38.w
	bsr	blit_go_copy
	dbf	d7,.d
.out:	movem.l	(sp)+,d0-d7/a0-a3
	rts

; ---- part_get: d0.l = desc -> a0 = the part (the build's, else made on first use) ----
part_get:
	movem.l	d1-d3,-(sp)
	move.l	d0,d1
	move.l	d0,d2
	moveq	#9,d3
	lsr.l	d3,d1
	moveq	#18,d3
	lsr.l	d3,d2
	eor.l	d1,d2
	eor.l	d0,d2
	move.l	d2,d1
	and.w	#IDX_SLOTS-1,d1
	lsl.w	#3,d1
	lea	ren_pidx,a0
	add.w	d1,a0
.probe:	cmp.l	(a0),d0
	beq.s	.static
	tst.l	(a0)
	beq.s	.dyn
	addq.l	#8,a0
	cmp.l	#ren_pidx_end,a0
	blo.s	.probe
	lea	ren_pidx,a0
	bra.s	.probe
.static:
	move.l	4(a0),d1
	lea	ren_parts,a0
	add.l	d1,a0
	bra.s	.hit
.dyn:	and.l	#SPC_SLOTS-1,d2
	mulu	#SPC_SIZE,d2
	lea	spcache,a0
	add.l	d2,a0
	cmp.l	(a0),d0
	beq.s	.hit
	bsr	part_make
.hit:	movem.l	(sp)+,d1-d3
	rts

; ---- part_make: d0 = desc, a0 = the slot ----
part_make:
	movem.l	d0-d7/a0-a6,-(sp)
	addq.l	#1,pm_miss
	move.l	d0,(a0)
	move.l	d0,d7
	moveq	#0,d1
	move.w	d7,d1
	and.w	#1023,d1		; code
	move.l	d7,d2
	moveq	#10,d3
	lsr.l	d3,d2
	and.w	#127,d2			; colour row
	lsl.w	#4,d2
	lea	ren_spm,a2
	add.w	d2,a2
	move.l	d7,d2
	moveq	#19,d3
	lsr.l	d3,d2
	and.w	#3,d2
	lea	sizetab,a1
	moveq	#0,d4
	move.b	(a1,d2.w),d4		; width
	move.l	d7,d2
	moveq	#21,d3
	lsr.l	d3,d2
	and.w	#3,d2
	moveq	#0,d5
	move.b	(a1,d2.w),d5		; height
	move.l	d7,d2
	moveq	#23,d3
	lsr.l	d3,d2
	and.w	#3,d2
	lsl.w	#3,d2			; x offset in pixels
	move.w	d2,pm_tx
	move.l	d7,d2
	moveq	#25,d3
	lsr.l	d3,d2
	and.w	#3,d2
	lsl.w	#3,d2
	move.w	d2,pm_ty
	move.l	d7,d2
	lsr.l	#8,d2
	lsr.l	#8,d2
	move.w	d2,pm_flips		; bit 1: flip x, bit 2: flip y
	move.w	d4,pm_w
	move.w	d5,pm_h
	moveq	#1,d6
	cmp.w	#16,d4
	bls.s	.c
	moveq	#2,d6
.c:	move.w	d6,8(a0)		; c
	move.w	d6,pm_c
	move.w	d5,4(a0)		; rows
	move.w	#204,10(a0)		; the rows' offset
	lsl.l	#8,d1			; code * 512
	add.l	d1,d1
	lea	ren_spr,a1
	add.l	d1,a1
	move.l	a1,pm_img
	lea	12(a0),a4		; the groups
	lea	204(a0),a3		; the rows
	clr.w	6(a0)
	move.l	a0,pm_slot
	move.l	#0,pm_prev
	clr.w	pm_prevn
	clr.w	pm_r
.row:	move.w	pm_r,d0
	btst	#2,pm_flips+1
	beq.s	.nfy
	move.w	pm_h,d0
	sub.w	pm_r,d0
	subq.w	#1,d0
.nfy:	add.w	pm_ty,d0
	lsl.w	#4,d0
	and.l	#$FFFF,d0
	move.l	pm_img,a1
	add.l	d0,a1			; the image's row
	lea	pm_pens,a0
	moveq	#15,d0
.un:	move.b	(a1)+,d1
	move.b	d1,d2
	lsr.b	#4,d1
	move.b	d1,(a0)+
	and.b	#15,d2
	move.b	d2,(a0)+
	dbf	d0,.un
	lea	pm_pens,a0
	move.w	pm_tx,d0
	btst	#1,pm_flips+1
	beq.s	.nfx
	add.w	pm_w,d0
	subq.w	#1,d0
.nfx:	add.w	d0,a0			; the first pixel
	moveq	#1,d2
	btst	#1,pm_flips+1
	beq.s	.st
	moveq	#-1,d2
.st:	move.w	pm_w,pm_cnt
	moveq	#0,d3
	moveq	#0,d4
	moveq	#0,d5
	moveq	#0,d6
	moveq	#0,d7
.px:	moveq	#0,d0
	move.b	(a0),d0
	add.w	d2,a0
	cmp.b	#15,d0
	sne	d1
	lsr.b	#1,d1
	roxl.l	#1,d3
	move.b	(a2,d0.w),d1
	lsr.b	#1,d1
	roxl.l	#1,d4
	lsr.b	#1,d1
	roxl.l	#1,d5
	lsr.b	#1,d1
	roxl.l	#1,d6
	lsr.b	#1,d1
	roxl.l	#1,d7
	subq.w	#1,pm_cnt
	bne.s	.px
	moveq	#32,d0
	sub.w	pm_w,d0
	lsl.l	d0,d3			; left justified
	lsl.l	d0,d4
	lsl.l	d0,d5
	lsl.l	d0,d6
	lsl.l	d0,d7
	cmp.w	#2,pm_c
	beq.s	.l
	swap	d4
	swap	d5
	swap	d6
	swap	d7
	move.w	d4,(a3)+
	move.w	d5,(a3)+
	move.w	d6,(a3)+
	move.w	d7,(a3)+
	bra.s	.m
.l:	move.l	d4,(a3)+
	move.l	d5,(a3)+
	move.l	d6,(a3)+
	move.l	d7,(a3)+
.m:	tst.w	pm_r			; the row groups
	beq.s	.new
	cmp.l	pm_prev,d3
	bne.s	.new
	addq.w	#1,pm_prevn
	move.w	pm_prevn,-6(a4)
	bra.s	.nx
.new:	move.l	d3,pm_prev
	move.w	#1,pm_prevn
	move.w	#1,(a4)+
	move.l	d3,(a4)+
	move.l	pm_slot,a0
	addq.w	#1,6(a0)
.nx:	addq.w	#1,pm_r
	move.w	pm_r,d0
	cmp.w	pm_h,d0
	bne	.row
	movem.l	(sp)+,d0-d7/a0-a6
	rts

; ---- l3_draw: the fixed layer's (CUS43 pair, layer 1) non-empty cells inside the window, over the display buffer: a row's
; neighbouring cells (up to four) are one part (a run: text is drawn like sprites, 32 pixels a part) ----
l3_draw:
	movem.l	d0-d7/a0-a6,-(sp)
	moveq	#0,d0
	move.b	hwregs+$14,d0
	lsl.w	#8,d0
	move.b	hwregs+$15,d0
	and.w	#$1FF,d0
	neg.w	d0
	sub.w	#3,d0
	and.w	#511,d0
	move.w	d0,l3_ox
	move.w	d0,d1
	and.w	#7,d1
	sub.w	#8,d1
	move.w	d1,l3_xs0		; the first cell's window x
	sub.w	d0,d1
	asr.w	#3,d1
	and.w	#63,d1
	move.w	d1,l3_c0		; its column
	moveq	#0,d1
	move.b	hwregs+$16,d1
	neg.w	d1
	sub.w	#25,d1
	and.w	#255,d1
	move.w	d1,l3_oy
	clr.w	l3_r
.r:	lea	l3_rc,a0
	move.w	l3_r,d0
	tst.b	(a0,d0.w)
	beq	.nextr
	lsl.w	#3,d0
	add.w	l3_oy,d0
	and.w	#255,d0			; the row's window line
	cmp.w	#224,d0
	blo.s	.yok
	cmp.w	#248,d0
	blo	.nextr
	sub.w	#256,d0
.yok:	add.w	ren_wy,d0
	add.w	#32,d0
	move.w	d0,l3_by
	lea	l3_ne,a2
	move.w	l3_r,d0
	lsl.w	#6,d0
	add.w	d0,a2			; the row's flags
	moveq	#0,d5			; the screen cell
	move.w	l3_c0,d7		; its column
.j:	tst.b	(a2,d7.w)
	bne.s	.start
.skip:	addq.w	#1,d7
	and.w	#63,d7
	addq.w	#1,d5
	cmp.w	#41,d5
	blo.s	.j
	bra	.nextr
.start:	move.w	d5,d0
	lsl.w	#3,d0
	add.w	l3_xs0,d0
	add.w	ren_wx,d0
	add.w	#64,d0
	move.w	d0,l3_bx
	moveq	#0,d6			; the cells of the run
	clr.l	l3_keys
	clr.l	l3_keys+4
	clr.l	l3_keys+8
	clr.l	l3_keys+12
.run:	move.w	l3_r,d0
	lsl.w	#6,d0
	add.w	d7,d0
	bsr	l3_key
	move.w	d6,d3
	lsl.w	#2,d3
	lea	l3_keys,a0
	move.l	d4,(a0,d3.w)
	addq.w	#1,d6
	addq.w	#1,d7
	and.w	#63,d7
	addq.w	#1,d5
	cmp.w	#4,d6
	beq.s	.go
	cmp.w	#41,d5
	beq.s	.go
	tst.b	(a2,d7.w)
	bne.s	.run
.go:	move.w	d6,l3_n
	move.w	d5,-(sp)
	move.w	d7,-(sp)
	move.l	a2,-(sp)
	bsr	part_get_run		; a0 = the part
	move.w	l3_bx,d1
	move.w	l3_by,d2
	bsr	spr_blit
	move.w	l3_n,d3
	lsl.w	#3,d3
	moveq	#8,d4
	move.w	l3_bx,d1
	move.w	l3_by,d2
	bsr	dmg_add
	move.l	(sp)+,a2
	move.w	(sp)+,d7
	move.w	(sp)+,d5
	cmp.w	#41,d5
	blo	.j
.nextr:	addq.w	#1,l3_r
	cmp.w	#32,l3_r
	bne	.r
	movem.l	(sp)+,d0-d7/a0-a6
	rts

; l3_key: d0 = a cell index -> d1 = the tile code (the PROM's select added), d2 = its attribute, d4 = the key
l3_key:
	move.w	d0,d3
	add.w	d3,d3
	lea	vram1+$1000,a0
	moveq	#0,d1
	move.b	(a0,d3.w),d1
	moveq	#0,d2
	move.b	1(a0,d3.w),d2
	move.w	d2,d3
	and.w	#3,d3
	add.w	d3,d3
	lea	ren_hi+16+8,a0
	add.w	(a0,d3.w),d1
	move.l	d1,d4
	and.l	#$7FF,d4
	lsl.l	#8,d4
	or.l	d2,d4
	or.l	#$40000000,d4
	rts

; ---- part_get_run: l3_n cells (l3_keys: their tile keys) as one part -> a0 (the slot's 16 bytes of keys, then the part) ----
part_get_run:
	movem.l	d0-d3,-(sp)
	lea	l3_keys,a1
	moveq	#0,d1
	moveq	#3,d3
.h:	move.l	d1,d2
	lsl.l	#5,d1
	add.l	d2,d1			; * 33
	move.l	(a1)+,d2
	and.l	#$7FFFF,d2
	add.l	d2,d1
	dbf	d3,.h
	lea	l3_keys,a1
	move.l	d1,d2
	moveq	#9,d3
	lsr.l	d3,d2
	move.l	d1,d0
	moveq	#18,d3
	lsr.l	d3,d0
	eor.l	d2,d1
	eor.l	d0,d1
	and.l	#RPC_SLOTS-1,d1
	lsl.l	#8,d1
	lea	rpcache,a0
	add.l	d1,a0
	bsr.s	.cmp			; the slot, then its neighbour (2-way)
	beq.s	.hit
	move.l	a0,-(sp)
	move.l	a0,d2
	eor.l	#256,d2
	move.l	d2,a0
	bsr.s	.cmp
	beq.s	.hit2
	move.l	(sp)+,a2		; a miss: the first slot if it is free, else its neighbour
	tst.l	(a2)
	beq.s	.useA
	move.l	a0,a2
.useA:	move.l	a2,a0
	bsr	part_make_run
	bra.s	.hit
.hit2:	addq.l	#4,sp
.hit:	lea	16(a0),a0
	movem.l	(sp)+,d0-d3
	rts
.cmp:	move.l	(a1),d2			; Z: the slot a0 holds the keys
	cmp.l	(a0),d2
	bne.s	.no
	move.l	4(a1),d2
	cmp.l	4(a0),d2
	bne.s	.no
	move.l	8(a1),d2
	cmp.l	8(a0),d2
	bne.s	.no
	move.l	12(a1),d2
	cmp.l	12(a0),d2
.no:	rts

; part_make_run: a0 = the slot, l3_n, l3_keys (zero beyond the run)
part_make_run:
	movem.l	d0-d7/a0-a6,-(sp)
	addq.l	#1,pm_tmiss
	move.l	a0,pm_slot
	lea	l3_keys,a1
	move.l	(a1),(a0)
	move.l	4(a1),4(a0)
	move.l	8(a1),8(a0)
	move.l	12(a1),12(a0)
	moveq	#0,d6			; the cells' forms (40 bytes: 8 rows of mask, planes 0-3) into l3_f
	lea	l3_f,a4
.f:	cmp.w	l3_n,d6
	beq.s	.formsdone
	move.w	d6,d0
	lsl.w	#2,d0
	lea	l3_keys,a1
	move.l	(a1,d0.w),d0		; key = $40000000 | code << 8 | attribute
	move.l	d0,d1
	lsr.l	#8,d1			; the code
	and.l	#$7FF,d1
	and.l	#$FF,d0
	move.l	d0,d2
	moveq	#1,d0
	move.w	d6,-(sp)
	move.l	a4,-(sp)
	bsr	tile_get
	move.l	(sp)+,a4
	move.w	(sp)+,d6
	moveq	#9,d0
.cp:	move.l	(a0)+,(a4)+
	dbf	d0,.cp
	addq.w	#1,d6
	bra.s	.f
.formsdone:
	move.l	pm_slot,a1
	lea	16(a1),a1		; the part
	move.w	#8,4(a1)
	clr.w	6(a1)
	moveq	#1,d0
	cmp.w	#2,l3_n
	bls.s	.c1
	moveq	#2,d0
.c1:	move.w	d0,8(a1)
	move.w	#60,10(a1)
	lea	60(a1),a3
	lea	12(a1),a4
	clr.w	pm_r
.row:	moveq	#0,d3			; the opaque mask
	moveq	#0,d4
	moveq	#0,d5
	moveq	#0,d6
	moveq	#0,d7
	moveq	#0,d1			; the cell
	lea	l3_f,a0
	move.w	pm_r,d2
	mulu	#5,d2
	add.w	d2,a0			; row r of cell 0
.cell:	cmp.w	l3_n,d1
	beq.s	.celldone
	moveq	#24,d2
	move.w	d1,d0
	lsl.w	#3,d0
	sub.w	d0,d2			; the shift: 24 - 8 cell
	moveq	#0,d0
	move.b	(a0),d0
	lsl.l	d2,d0
	or.l	d0,d3
	moveq	#0,d0
	move.b	1(a0),d0
	lsl.l	d2,d0
	or.l	d0,d4
	moveq	#0,d0
	move.b	2(a0),d0
	lsl.l	d2,d0
	or.l	d0,d5
	moveq	#0,d0
	move.b	3(a0),d0
	lsl.l	d2,d0
	or.l	d0,d6
	moveq	#0,d0
	move.b	4(a0),d0
	lsl.l	d2,d0
	or.l	d0,d7
	lea	40(a0),a0		; the next cell's form
	addq.w	#1,d1
	bra.s	.cell
.celldone:
	cmp.w	#2,8(a1)
	beq.s	.l
	swap	d4
	swap	d5
	swap	d6
	swap	d7
	move.w	d4,(a3)+
	move.w	d5,(a3)+
	move.w	d6,(a3)+
	move.w	d7,(a3)+
	bra.s	.m
.l:	move.l	d4,(a3)+
	move.l	d5,(a3)+
	move.l	d6,(a3)+
	move.l	d7,(a3)+
.m:	tst.w	pm_r
	beq.s	.new
	cmp.l	pm_prev,d3
	bne.s	.new
	addq.w	#1,pm_prevn
	move.w	pm_prevn,-6(a4)
	bra.s	.nx
.new:	move.l	d3,pm_prev
	move.w	#1,pm_prevn
	move.w	#1,(a4)+
	move.l	d3,(a4)+
	addq.w	#1,6(a1)
.nx:	addq.w	#1,pm_r
	cmp.w	#8,pm_r
	bne	.row
	movem.l	(sp)+,d0-d7/a0-a6
	rts

; ---- l3_cell: d0.w = a cell of the fixed layer: its non-empty flag and its row's count follow the tile ----
l3_cell:
	movem.l	d0-d7/a0-a3,-(sp)
	move.w	d0,d6
	add.w	d0,d0
	lea	vram1+$1000,a0
	moveq	#0,d1
	move.b	(a0,d0.w),d1
	moveq	#0,d2
	move.b	1(a0,d0.w),d2
	move.w	d2,d3
	and.w	#3,d3
	add.w	d3,d3
	lea	ren_hi+16+8,a0
	add.w	(a0,d3.w),d1
	moveq	#1,d0
	move.w	d6,-(sp)
	bsr	tile_get
	move.w	(sp)+,d6
	moveq	#0,d1
	rept	8
	or.b	(a0),d1
	lea	5(a0),a0
	endr
	lea	l3_ne,a1
	lea	l3_rc,a2
	move.w	d6,d2
	lsr.w	#6,d2			; the row
	tst.b	d1
	beq.s	.empty
	tst.b	(a1,d6.w)
	bne.s	.out
	st	(a1,d6.w)
	addq.b	#1,(a2,d2.w)
	bra.s	.out
.empty:	tst.b	(a1,d6.w)
	beq.s	.out
	clr.b	(a1,d6.w)
	subq.b	#1,(a2,d2.w)
.out:	movem.l	(sp)+,d0-d7/a0-a3
	rts

	section bss,bss
	even
l3_ox:		ds.w	1
l3_xs0:		ds.w	1
l3_c0:		ds.w	1
l3_j:		ds.w	1
l3_n:		ds.w	1
l3_keys:	ds.l	4
l3_f:		ds.b	160
l3_oy:		ds.w	1
l3_r:		ds.w	1
l3_c:		ds.w	1
l3_bx:		ds.w	1
l3_by:		ds.w	1
l3_ne:		ds.b	2048
l3_rc:		ds.b	32
pm_xoffs:	ds.w	1
pm_x:		ds.w	1
pm_yoffs:	ds.w	1
spl_n:		ds.w	1
spl_i:		ds.w	1
pm_tx:		ds.w	1
pm_ty:		ds.w	1
pm_flips:	ds.w	1
pm_w:		ds.w	1
pm_h:		ds.w	1
pm_c:		ds.w	1
pm_r:		ds.w	1
pm_cnt:		ds.w	1
pm_prevn:	ds.w	1
	even
pm_img:		ds.l	1
pm_prev:	ds.l	1
pm_slot:	ds.l	1
pm_miss:	ds.l	1
pm_tmiss:	ds.l	1
pm_pens:	ds.b	32
dmg_n:		ds.w	3
	even
dmg_list:	ds.b	3*DMG_MAX*8
splist:		ds.b	128*16
spcache:	ds.b	SPC_SLOTS*SPC_SIZE
rpcache:	ds.b	RPC_SLOTS*256

	section data,data
	even
ren_spr:	incbin	"ren_spr.bin"
ren_spm:	incbin	"ren_spm.bin"
ren_yvis:	incbin	"ren_yvis.bin"
ren_pidx:	incbin	"ren_pidx.bin"
ren_pidx_end:
ren_parts:	incbin	"ren_parts.bin"
	even
