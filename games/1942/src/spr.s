; ------------------------------------------------------------------------------
; Sprites
;
; 32 entries of 4 bytes at $CC00 (tools/machine.py draw_sprites is the model): code (7 bits + bit 7 = code bit 8), colour (4) +
; code bit 7 (bit 5) + x bit 8 (bit 4) + height (bits 6-7: 1, 2 or 4 parts), raw y, raw x.  A part is 16 x 16 pixels of 16 colours (pen 15 =
; transparent).  The arcade draws entry 0 on top, so entry 31 is drawn first.  The screen is the arcade raster rotated
; 270 degrees: part n of an entry has its left edge at screen x = y + 16 * n - 16 and its top line at screen y = 240 - x
; (x = the sprite's raw x, a signed 9 bit number). Whole parts draw into the
; wider virtual screen and guard rows; the display window hides offscreen pixels.
; Drawing follows stefastbobs2/FAST_BLITTER_SPRITES.md: the baked source has the rows of a part in blit order (equal opaque masks
; adjacent, transparent rows left out), one Blitter call per row draws its four planes (Y count 4, the opaque mask as end masks, NFSR
; for the second destination word), and a generated routine per row structure (tools/spritegen.py) does the whole part with the
; Blitter's registers held in address registers; the masks of the 16 shifts come from a stream.  Parts at a 64 KB boundary of the
; ring take the generic path.  Rectangle records restore the background on the next use of the draw ring.
; ------------------------------------------------------------------------------

MAX_RECTS = 160
SPR_LOW_LIMIT = $EFE0		; (spritegen.py LOW_LIMIT) a part whose first chunk is above this low word is drawn the generic way

; d0.w = code (9 bits), d1.w = colour (4 bits): a0 = the baked part (16 rows of 4 words).  Clobbers d0-d7, a1-a5.

sprite_get:
	move.w	d0,d2
	lsl.w	#4,d2
	or.w	d1,d2				; key (13 bits)
	moveq	#0,d3
	move.w	d2,d3
	lsl.l	#2,d3
	lea	spr_ptr,a0
	move.l	(a0,d3.l),d3
	beq.s	bake_sprite
	move.l	d3,a0
	rts

bake_sprite:
	move.w	d2,-(sp)			; the key
	moveq	#0,d3
	move.w	d0,d3
	lsl.l	#8,d3
	add.l	d3,d3				; * 512: 16 rows of 16 pen masks
	lea	spr_masks,a1
	add.l	d3,a1
	lea	luts+256,a2
	lsl.w	#4,d1
	add.w	d1,a2				; the colour's 16 lookup entries
	lea	cmap,a3
	lea	bk_idx,a0
	moveq	#15,d4
.idx:	moveq	#0,d0
	move.b	(a2)+,d0
	add.w	#64,d0				; the arcade palette entry of a sprite colour
	move.b	(a3,d0.w),d0
	lsl.b	#2,d0
	move.b	d0,(a0)+
	dbf	d4,.idx
	move.l	spr_pool_ptr,a2
	move.l	a2,-(sp)
	lea	orp_tab,a5
	moveq	#15,d2
.row:	moveq	#0,d3
	moveq	#0,d4
	moveq	#0,d5
	moveq	#0,d6
	lea	bk_idx,a0
	moveq	#15,d1
.pen:	move.w	(a1)+,d7
	beq.s	.skip
	moveq	#0,d0
	move.b	(a0)+,d0
	move.l	(a5,d0.w),a4
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
	move.l	a2,spr_pool_ptr
	move.l	(sp)+,a0
	moveq	#0,d0
	move.w	(sp)+,d0
	lsl.l	#2,d0
	lea	spr_ptr,a1
	move.l	a0,(a1,d0.l)
	rts

; ------------------------------------------------------------------------------
; The old rectangles of the draw ring are put back from clean.

rf_spr_restore:
	move.w	draw_idx,d0
	move.w	d0,d1
	add.w	d1,d1
	lea	rect_cnt,a0
	move.w	(a0,d1.w),d6		; (the list stays: overlay_old needs it)
	subq.w	#1,d6
	bmi.s	.none
	mulu	#MAX_RECTS*16,d0
	lea	rects,a4
	add.l	d0,a4
	move.w	draw_idx,d0
	lsl.w	#2,d0
	lea	ring_base,a1
	move.l	(a1,d0.w),a5			; the draw ring
.r:	move.l	(a4),d2				; offset
	move.l	clean_base,a0
	add.l	d2,a0
	lea	(a5,d2.l),a1
	move.w	6(a4),d0			; chunks
	lsl.w	#2,d0				; words
	move.w	4(a4),d1			; lines
	movem.l	d6/a4-a5,-(sp)
	bsr	blit_copy
	movem.l	(sp)+,d6/a4-a5
	lea	16(a4),a4
	dbf	d6,.r
.none:	rts

; ------------------------------------------------------------------------------
; The sprite list: every part of every entry is drawn, one generated Blitter routine per part (tools/spritegen.py).
;
; Registers during the pass (spr_regs): a2 END1, a3 END3, a4 destination address low word, a5 Y count, a6 control, d4 +248, d5 -264,
; d6 4, d7 $c0 - the routines write the Blitter through them and never touch anything else.  The pass itself uses d0-d3, a0, a1
; and the variables below; the rare calls that clobber more (baking, the generic path) reload them with spr_regs.

spr_begin:
	move.w	draw_idx,d0
	move.w	d0,d1
	lsl.w	#2,d1
	lea	ring_base,a0
	move.l	(a0,d1.w),w_base
	mulu	#MAX_RECTS*16,d0
	lea	rects,a0
	add.l	d0,a0
	move.l	a0,rect_base
	move.l	a0,rect_fill
	moveq	#0,d0
	move.w	cur_T,d0
	lsl.l	#8,d0
	add.l	#GAME_X,d0
	move.l	d0,spr_toff			; ring offset of the window's first line, plus the game area's column
	move.w	#2,BLT_SRC_XINC.w
	move.w	#2,BLT_SRC_YINC.w
	move.w	#8,BLT_DST_XINC.w
	move.w	#$ffff,BLT_END2.w
	move.w	#$0203,BLT_HOP_OP.w
spr_regs:
	lea	BLT_END1.w,a2
	lea	BLT_END3.w,a3
	lea	BLT_DST_ADDR+2.w,a4
	lea	BLT_COUNT+2.w,a5
	lea	BLT_CTRL.w,a6
	move.w	#248,d4
	move.w	#-264,d5
	moveq	#4,d6
	move.l	#$c0,d7
	rts

; the number of rectangles recorded goes to the ring's count

spr_end:
	move.l	rect_fill,d0
	sub.l	rect_base,d0
	lsr.l	#4,d0
	move.w	draw_idx,d1
	add.w	d1,d1
	lea	rect_cnt,a0
	move.w	d0,(a0,d1.w)
	rts

rf_sprites:
	bsr	spr_begin
	lea	Z_SPR+31*4,a0
	move.l	a0,spr_ep
	moveq	#31,d0
	move.w	d0,spr_e
.entry:	move.l	spr_ep,a0
	tst.l	(a0)			; (an unused entry is all zero and its picture, sprite 0, is empty: spr_blank[0])
	beq.s	.unused
	bsr.s	sprite_entry
.unused:
	subq.l	#4,spr_ep
	subq.w	#1,spr_e
	bpl.s	.entry
	bra	spr_end

; a0 = the entry

sprite_entry:
	moveq	#0,d0
	move.b	(a0),d0
	moveq	#0,d1
	move.b	1(a0),d1
	moveq	#0,d2
	move.b	2(a0),d2			; raw y
	move.w	d2,spr_y
	moveq	#0,d3
	move.b	3(a0),d3			; raw x (low 8 bits)
	; the top line: 240 - raw x, raw x = x - 256 when the colour byte's bit 4 is set
	move.w	#240,d2
	sub.w	d3,d2
	btst	#4,d1
	beq.s	.xpos
	add.w	#256,d2
.xpos:	move.w	d2,spr_ytop
	; the code: 7 bits + bit 8 from the code byte's bit 7, bit 7 from the colour byte's bit 5
	move.w	d0,d2
	and.w	#$7F,d2
	and.w	#$80,d0
	add.w	d0,d0
	add.w	d0,d2
	move.w	d1,d3
	and.w	#$20,d3
	lsl.w	#2,d3
	add.w	d3,d2
	move.w	d2,spr_code
	move.w	d1,d3
	and.w	#15,d3
	move.w	d3,spr_col
	; the number of parts - 1
	lsr.w	#6,d1
	cmp.w	#2,d1
	bne.s	.parts
	moveq	#3,d1
.parts:	move.w	d1,spr_n
.part:	move.w	spr_n,d1
	move.w	spr_y,d2
	move.w	d1,d3
	lsl.w	#4,d3
	add.w	d3,d2
	sub.w	#16,d2				; screen x of the part
	cmp.w	#-15,d2
	blt.s	.next
	cmp.w	#224,d2
	bge.s	.next
	move.w	spr_code,d0
	add.w	d1,d0
	and.w	#$1FF,d0
	lea	spr_blank,a0
	tst.b	(a0,d0.w)
	bne.s	.next
	move.w	d2,spr_xs
	move.w	d0,spr_pcode
	bsr.s	draw_part
	move.w	spr_xs,d3			; a part across an edge of the game area: its chunk in the margin is
	bmi.s	.left				; cleared (the arcade's monitor shows 224 of the 256 pixels)
	cmp.w	#208,d3
	ble.s	.next
	moveq	#14*8,d0
	bsr	spr_clip
	bra.s	.next
.left:	moveq	#-8,d0
	bsr	spr_clip
.next:	subq.w	#1,spr_n
	bpl.s	.part
	rts

; The margin chunk at byte d0.w of the game area (-8: left, 112: right) cleared for the 16 lines of the part just drawn
; (the Blitter is done: HOG mode).  Clobbers d0-d2, a0.

spr_clip:
	move.w	spr_ytop,d2
	cmp.w	#-15,d2
	blt.s	.out
	cmp.w	#256,d2
	bge.s	.out
	ext.l	d2
	lsl.l	#8,d2
	add.l	spr_toff,d2
	ext.l	d0
	add.l	d0,d2
	add.l	w_base,d2
	move.l	d2,a0
	moveq	#15,d1
.c:	clr.l	(a0)
	clr.l	4(a0)
	lea	STRIDE(a0),a0
	dbf	d1,.c
.out:	rts

; ------------------------------------------------------------------------------
; One whole part: spr_pcode, spr_col, spr_xs (screen x), spr_ytop (screen y of the top line).  Records the rectangle, then draws the
; whole part into the virtual ring without clipping (the display window hides what is off).

draw_part:
	move.w	spr_ytop,d2
	cmp.w	#-15,d2
	blt	.out
	cmp.w	#256,d2
	bge	.out
	; the baked part
	move.w	spr_pcode,d0
	lsl.w	#4,d0
	or.w	spr_col,d0
	lsl.w	#2,d0
	lea	spr_ptr,a0
	move.l	(a0,d0.w),d0
	bne.s	.baked
	move.w	spr_pcode,d0
	move.w	spr_col,d1
	bsr	sprite_get
	move.l	a0,d0
	bsr	spr_regs			; (baking used every register)
.baked:	move.l	d0,a1
	; the ring offset of the part's first chunk
	move.w	spr_ytop,d2
	ext.l	d2
	lsl.l	#8,d2
	add.l	spr_toff,d2
	move.w	spr_xs,d3
	move.w	d3,d0
	asr.w	#4,d0
	ext.l	d0
	lsl.l	#3,d0
	add.l	d0,d2
	; the record: offset, lines, chunks, first chunk column, first and last screen line
	move.l	rect_fill,a0
	move.l	d2,(a0)+
	move.w	#16,(a0)+
	moveq	#1,d0
	move.w	d3,d1
	and.w	#15,d1
	beq.s	.w1
	moveq	#2,d0
.w1:	move.w	d0,(a0)+
	move.w	d3,d0
	asr.w	#4,d0
	move.w	d0,(a0)+
	move.w	spr_ytop,d0
	move.w	d0,(a0)+
	add.w	#15,d0
	move.w	d0,(a0)+
	addq.l	#2,a0
	move.l	a0,rect_fill
	add.l	w_base,d2			; the destination address of the first chunk
	cmp.w	#SPR_LOW_LIMIT,d2		; the routines only add to its low word
	bhi.s	generic_part
	move.l	d2,BLT_DST_ADDR.w
	move.l	a1,BLT_SRC_ADDR.w
	moveq	#0,d0
	move.w	spr_pcode,d0
	lsl.w	#4,d0
	or.w	d1,d0				; code * 16 + shift
	lsl.l	#3,d0
	lea	spr_code_tab,a1
	add.l	d0,a1
	move.l	4(a1),a0			; the stream of masks and the control word
	move.l	(a1),a1				; the routine
	jmp	(a1)
.out:	rts

; A part that reaches a 64 KB boundary of the ring (about one in 16): one blit per row with the whole destination address.  The
; masks are the ones the stream of the routine holds (nothing is computed here), the rows come from the shift independent plan of the
; sprite (spr_plan: per group of rows with the same opaque mask the count and the row steps).
; a1 = the baked part, d2 = the destination address, d3.w = screen x

generic_part:
	move.l	a1,BLT_SRC_ADDR.w
	move.l	d2,a1
	and.w	#15,d3				; the shift
	moveq	#0,d0
	move.w	spr_pcode,d0
	lsl.w	#4,d0
	or.w	d3,d0
	lsl.l	#3,d0
	lea	spr_code_tab,a2
	move.l	4(a2,d0.l),a2			; the stream: END1 (and END3), the control word after the first group's masks
	tst.w	d3
	bne.s	.shifted
	move.w	#1,BLT_COUNT.w
	move.w	#2,BLT_DST_YINC.w
	clr.b	BLT_SKEW.w
	bra.s	.plan
.shifted:
	move.w	#2,BLT_COUNT.w
	move.w	#-6,BLT_DST_YINC.w
	move.b	d3,d0
	or.b	#NFSR,d0
	move.b	d0,BLT_SKEW.w
.plan:	moveq	#0,d0
	move.w	spr_pcode,d0
	lsl.w	#2,d0
	lea	spr_plan_offsets,a0
	move.l	(a0,d0.w),d0
	lea	spr_plan,a0
	add.l	d0,a0
	moveq	#1,d5
.group:	move.w	(a0)+,d1			; rows in the group
	beq.s	.done
	move.w	(a2)+,BLT_END1.w
	tst.w	d3
	beq.s	.n3
	move.w	(a2)+,BLT_END3.w
.n3:	tst.w	d5
	beq.s	.rows
	moveq	#0,d5
	addq.l	#2,a2				; (the control word)
.rows:	subq.w	#1,d1
.row:	adda.w	(a0)+,a1
	move.l	a1,BLT_DST_ADDR.w
	move.w	#4,BLT_COUNT+2.w
	move.b	#$c0,BLT_CTRL.w
	dbf	d1,.row
	bra.s	.group
.done:	bra	spr_regs
