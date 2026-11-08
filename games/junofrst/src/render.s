; Juno First's picture on the STE (included by junofrst.s).
;
; The arcade's video RAM is a 256 x 256 bitmap of 4 bpp (the program draws into it with the CPU and with a 16 x 16
; blitter), and the screen shows its lines 16-239 turned as MAME's ROT90 turns them (tools/machine.py Video): picture
; line L = 255 - x, picture column C = y - 16, so the picture is 224 x 256 like Gyruss's, centred in the 320-pixel
; screen (black side bands of 48 pixels, three 16-pixel groups), borders open (engine/rt/borders.s, PIC_TOP 10,
; PIC_LINES 256).  The 16 pens are the 16 STE colours (the palette RAM's bytes through ste_pal_tab: tools/assets.py).
;
; The video RAM is not kept as bytes: `vram` is the picture itself, 256 lines of 160 bytes (the 224 pixels at x 48, the
; bands zero), planar.  The program's accesses go through main_io_r / main_io_w (junofrst.s): vram_rd / vram_wr turn a
; byte (two pixels: x even in the low nibble) into two pixel reads / writes, blit_run runs the blitter's 16 x 16 blit
; pixel by pixel (MAME's junofrst_state::blitter_w: source nibbles from jf_blitrom, 0 skipped, a zero written when the
; source address' bit 0 is clear).  Pixels in the arcade's lines 0-15 and 240-255 (not shown) are dropped.
;
; render_frame: a free display buffer (three, as Gyruss) gets the picture by one Blitter copy (HOG pieces,
; borders_blit_go) and is published for the next VBL, with the palette of the moment.
;
; NOT OPTIMISED: the pixel routines are plain 68000 code (the sprite blits are the cost); the prepared Blitter sprite
; passes of docs/sprite-preparation.md are not done (README, "Open").

BL = 280				; buffer lines: PIC_TOP above the picture, its 256, 14 guard lines
LB = 160
VW_BASE = 32650			; vram_wr's table: offsets from vram+32650 (a byte outside the picture's 24..135 of a line)
BUFSZ = BL*LB
NBUF = 3
PIC0 = PIC_TOP*LB			; the picture's line 0 in a buffer
VSZ = 256*LB

B_SXI = $ffff8a20
B_SYI = $ffff8a22
B_SRC = $ffff8a24
B_END1 = $ffff8a28
B_END2 = $ffff8a2a
B_END3 = $ffff8a2c
B_DXI = $ffff8a2e
B_DYI = $ffff8a30
B_DST = $ffff8a32
B_XC = $ffff8a36
B_YC = $ffff8a38
B_HOP = $ffff8a3a
B_OP = $ffff8a3b
B_CTRL = $ffff8a3c
B_SKEW = $ffff8a3d

	section text,code

; ======================================================================================================================
; init_render: the buffers and the picture black, the palettes
; ======================================================================================================================
init_render:
	lea	buffers,a0
	move.l	#(NBUF*BUFSZ+VSZ)/16-1,d0
.clr:	clr.l	(a0)+
	clr.l	(a0)+
	clr.l	(a0)+
	clr.l	(a0)+
	subq.l	#1,d0
	bpl.s	.clr
	lea	buffers,a0
	lea	buf_base,a1
	moveq	#NBUF-1,d0
.bb:	move.l	a0,(a1)+
	add.l	#BUFSZ,a0
	dbf	d0,.bb
	clr.w	shown_idx
	move.w	#-1,prev_idx
	clr.b	frame_ready
	lea	shown_pal,a1
	lea	black_pal,a2
	lea	pend_pal,a3
	moveq	#15,d0
.pal:	clr.w	(a1)+
	clr.w	(a2)+
	clr.w	(a3)+
	dbf	d0,.pal
	move.l	buf_base,d0		; the video base: buffer 0
	move.l	d0,-(sp)
	move.b	1(sp),$ffff8201.w
	move.b	2(sp),$ffff8203.w
	move.b	3(sp),$ffff820d.w
	addq.l	#4,sp
	lea	vw_ptr,a0		; per video RAM byte the address of its low nibble's pixel (plane 0 byte); 0 where not shown
	moveq	#0,d2
.yr:	cmp.w	#16,d2
	blo.s	.inv
	cmp.w	#240,d2
	bhs.s	.inv
	move.w	d2,d3
	sub.w	#16,d3			; the picture column
	move.w	d3,d4
	lsr.w	#4,d4
	lsl.w	#3,d4
	btst	#3,d3
	beq.s	.nb
	addq.w	#1,d4
.nb:	lea	vram+24+255*LB,a1	; (x = 0: the picture's last line)
	add.w	d4,a1
	moveq	#127,d0
.xb:	move.l	a1,(a0)+
	lea	-2*LB(a1),a1		; (x + 2: two lines up)
	dbf	d0,.xb
	bra.s	.yn
.inv:	moveq	#127,d0
.iz:	clr.l	(a0)+
	dbf	d0,.iz
.yn:	addq.w	#1,d2
	cmp.w	#256,d2
	bne.s	.yr
	lea	vw_ptr,a0		; vram_wr's table: per video RAM byte (the plane 0 byte's offset from vram+VW_BASE) << 16
	lea	vw_tab,a1		; | (68 * (y & 7)), the offset of its row of vw_bt; 0 where the row is not shown
	moveq	#0,d2
.vt:	move.l	(a0)+,d0
	beq.s	.vh
	sub.l	#vram+VW_BASE,d0
	swap	d0
	clr.w	d0
	move.w	d2,d3			; the low word: the cell k * 16 + g (the line pair k = 127 - (a & 127), the group g =
	lsr.w	#7,d3			; (y - 16) >> 4: cell_marks) | (y & 7) << 11 (the pixel's bit row in vw_bt)
	move.w	d3,d4
	and.w	#7,d4
	lsl.w	#8,d4
	lsl.w	#3,d4
	sub.w	#16,d3
	lsr.w	#4,d3
	move.w	d2,d5
	and.w	#127,d5
	neg.w	d5
	add.w	#127,d5
	lsl.w	#4,d5
	or.w	d3,d5
	or.w	d4,d5
	or.w	d5,d0
.vh:	move.l	d0,(a1)+
	addq.w	#1,d2
	bpl.s	.vt
	bra	mark_all

; ======================================================================================================================
; vbl_video: the published buffer shown from the next frame on (the video base is read at the frame's start), its
; palette with it
; ======================================================================================================================
vbl_video:
	movem.l	d0-d1/a0-a1,-(sp)
	move.w	shown_idx,prev_idx
	moveq	#0,d1
	move.b	frame_ready,d1
	beq.s	.out
	clr.b	frame_ready
	subq.w	#1,d1
	move.w	d1,shown_idx
	add.w	d1,d1
	add.w	d1,d1
	lea	buf_base,a0
	move.l	(a0,d1.w),d0
	move.l	d0,-(sp)
	move.b	1(sp),$ffff8201.w
	move.b	2(sp),$ffff8203.w
	move.b	3(sp),$ffff820d.w
	addq.l	#4,sp
	lea	pend_pal,a0
	lea	shown_pal,a1
	rept	8
	move.l	(a0)+,(a1)+
	endr
	addq.w	#1,pic_shown
.out:	movem.l	(sp)+,d0-d1/a0-a1
	rts

; ======================================================================================================================
; render_frame: a free buffer gets the picture and is published
; ======================================================================================================================
render_frame:
	movem.l	d0-d7/a0-a6,-(sp)
.snap:	move.w	shown_idx,d1		; a buffer neither shown, nor scanned out once more, nor waiting
	move.w	prev_idx,d2
	moveq	#0,d3
	move.b	frame_ready,d3
	cmp.w	shown_idx,d1
	bne.s	.snap
	subq.w	#1,d3
	moveq	#0,d0
.pick:	cmp.w	d1,d0
	beq.s	.nx
	cmp.w	d2,d0
	beq.s	.nx
	cmp.w	d3,d0
	bne.s	.got
.nx:	addq.w	#1,d0
	cmp.w	#NBUF,d0
	blo.s	.pick
	moveq	#0,d0			; (cannot happen: three buffers, at most two in use)
.got:	move.w	d0,draw_idx
	add.w	d0,d0
	add.w	d0,d0
	lea	buf_base,a0
	move.l	(a0,d0.w),a1
	lea	PIC0(a1),a1
	; the palette of this picture: the 16 palette RAM bytes through ste_pal_tab
	lea	jf_mem+$8000,a0
	lea	ste_pal_tab,a2
	lea	pend_pal,a3
	moveq	#15,d0
.pl:	moveq	#0,d1
	move.b	(a0)+,d1
	add.w	d1,d1
	move.w	(a2,d1.w),(a3)+
	dbf	d0,.pl
	; the cells changed since this buffer was last drawn: 2 lines x 8 bytes each (cell_marks: a bit per buffer)
	move.w	draw_idx,d0
	moveq	#1,d5
	lsl.b	d0,d5			; the buffer's bit
	move.w	d5,d6
	lsl.w	#8,d6
	or.w	d5,d6
	move.w	d6,d7
	swap	d6
	move.w	d7,d6			; (in all four bytes of a long)
	not.b	d5			; (to clear it)
	lea	cell_marks,a2
	lea	vram+24,a3
	lea	24(a1),a4
	moveq	#128-1,d7
.row:	movem.l	(a2),d0-d3
	and.l	#$FFFF0000,d3		; (the bytes 14 and 15 of a row are no cells)
	or.l	d1,d0
	or.l	d3,d2
	or.l	d2,d0
	and.l	d6,d0
	beq.s	.next
	moveq	#0,d1
.cell:	move.b	(a2,d1.w),d0
	and.b	d6,d0
	beq.s	.nc
	and.b	d5,(a2,d1.w)
	move.w	d1,d4
	lsl.w	#3,d4
	lea	(a3,d4.w),a0
	lea	(a4,d4.w),a1
	move.l	(a0)+,(a1)+
	move.l	(a0)+,(a1)+
	lea	LB-8(a0),a0
	lea	LB-8(a1),a1
	move.l	(a0)+,(a1)+
	move.l	(a0)+,(a1)+
.nc:	addq.w	#1,d1
	cmp.w	#14,d1
	blo.s	.cell
.next:	lea	16(a2),a2
	lea	2*LB(a3),a3
	lea	2*LB(a4),a4
	dbf	d7,.row
	move.w	draw_idx,d0
	addq.b	#1,d0
	move.b	d0,frame_ready
	addq.w	#1,pic_count
	movem.l	(sp)+,d0-d7/a0-a6
	rts

; ======================================================================================================================
; The picture as the video RAM.  Internal routines (free: d0-d4, d6, a0, a1 are saved by the entries):
;   px_addr: d1.w = picture line L, d2.w = picture column C -> a0 the byte of plane 0, d4.w the bit number (the planes' bytes are 2 apart)
;   put_px:  d0.b = the pixel (0-15)      get_px: -> d0.b
; ======================================================================================================================
px_addr:
	moveq	#0,d4
	move.w	d1,d4
	mulu	#LB,d4
	lea	vram+24,a0
	add.l	d4,a0
	move.w	d2,d4
	lsr.w	#4,d4
	lsl.w	#3,d4
	add.w	d4,a0
	btst	#3,d2
	beq.s	.l
	addq.l	#1,a0
.l:	moveq	#7,d4
	and.w	d2,d4
	neg.w	d4
	addq.w	#7,d4
	rts

put_px:
	bsr	px_addr
	btst	#0,d0
	beq.s	.a0
	bset	d4,(a0)
	bra.s	.a1
.a0:	bclr	d4,(a0)
.a1:	btst	#1,d0
	beq.s	.b0
	bset	d4,2(a0)
	bra.s	.b1
.b0:	bclr	d4,2(a0)
.b1:	btst	#2,d0
	beq.s	.c0
	bset	d4,4(a0)
	bra.s	.c1
.c0:	bclr	d4,4(a0)
.c1:	btst	#3,d0
	beq.s	.d0
	bset	d4,6(a0)
	rts
.d0:	bclr	d4,6(a0)
	rts

get_px:
	bsr	px_addr
	moveq	#0,d0
	btst	d4,(a0)
	beq.s	.a
	bset	#0,d0
.a:	btst	d4,2(a0)
	beq.s	.b
	bset	#1,d0
.b:	btst	d4,4(a0)
	beq.s	.c
	bset	#2,d0
.c:	btst	d4,6(a0)
	beq.s	.d
	bset	#3,d0
.d:	rts

; vram_wr: d7.w = the address ($0000-$7FFF), d5.b = the byte: pixel x = 2 * (a & 127) in the low nibble, x + 1 in the
; high nibble, row y = a >> 7
vram_wr:
	movem.l	d0-d1/a0-a1,-(sp)
	and.l	#$FFFF,d7
	lsl.l	#2,d7
	lea	vw_tab,a0
	move.l	(a0,d7.l),d1		; the plane 0 byte's offset << 16 | (y & 7) << 11 | the cell (0: a row not shown)
	beq.s	.out
	move.w	d1,d0
	and.w	#$7FF,d0
	lea	cell_marks,a1
	st	(a1,d0.w)		; the cell changed (all three buffers' bits)
	and.w	#$3800,d1
	lsr.w	#4,d1
	lea	vw_bt,a1
	add.w	d1,a1			; (128 bytes: the 16 pixel values' bits in the four plane bytes, then the inverted mask)
	swap	d1
	lea	vram+VW_BASE,a0
	add.w	d1,a0
	move.l	64(a1),d1		; the pixel's bit cleared in the four plane bytes
	tst.b	d5
	beq.s	.erase
	moveq	#15,d7
	and.w	d5,d7			; the low nibble
	lsl.w	#2,d7
	move.l	(a1,d7.w),d0
	movep.l	0(a0),d7		; the four planes' bytes (every other byte)
	and.l	d1,d7
	or.l	d0,d7
	movep.l	d7,0(a0)
	moveq	#0,d0			; the high nibble: the next picture line (160 bytes above)
	move.b	d5,d0
	lsr.b	#4,d0
	lsl.w	#2,d0
	move.l	(a1,d0.w),d0
	movep.l	-LB(a0),d7
	and.l	d1,d7
	or.l	d0,d7
	movep.l	d7,-LB(a0)
.out:	movem.l	(sp)+,d0-d1/a0-a1
	rts
.erase:	movep.l	0(a0),d7		; a zero byte: both pixels cleared
	and.l	d1,d7
	movep.l	d7,0(a0)
	movep.l	-LB(a0),d7
	and.l	d1,d7
	movep.l	d7,-LB(a0)
	movem.l	(sp)+,d0-d1/a0-a1
	rts

; vram_rd: d7.w = the address -> d7 the byte (the invisible rows read 0)
vram_rd:
	movem.l	d0-d4/d6/a0,-(sp)
	moveq	#0,d6
	move.w	d7,d2
	lsr.w	#7,d2
	cmp.w	#16,d2
	blo.s	.out
	cmp.w	#240,d2
	bhs.s	.out
	sub.w	#16,d2
	moveq	#127,d1
	and.w	d7,d1
	add.w	d1,d1
	neg.w	d1
	add.w	#255,d1
	bsr	get_px
	move.b	d0,d6
	subq.w	#1,d1
	bsr	get_px
	lsl.b	#4,d0
	or.b	d0,d6
.out:	move.l	d6,d7			; (d5 and d6 are kept: the result goes to d7 before they come back)
	movem.l	(sp)+,d0-d4/d6/a0
	rts

; blit_run: MAME's blitter_w at the write to $8073 (blit_slow below is the pixel by pixel version, the reference of
; the fast one).  The fast path: the source image (tools/assets.py: 16 shifts x 16 lines, a line = its two mask words
; and the plane words of the two 16-pixel groups it covers) is drawn by 16 short HOG passes of the Blitter, HOP 2 /
; OP 3 with the opaque pixels as the end masks (an erasing blit: HOP 0 / OP 0 with the same masks).  A blit's pixel
; column k is a picture line (255 - x - k), its 16 rows are the picture columns c0 .. c0 + 15 (c0 = y - 16), so the
; shift is c0 & 15.  Only the words inside the picture are drawn (AGENTS.md: group-aligned edges); the slow path takes
; what has no image, or a row that wraps into the next (x > 240).
blit_run:
	bsr	mark_blit
	movem.l	d0-d4/d6/a0-a3,-(sp)
	lea	jf_blt,a2
	moveq	#0,d3
	move.b	(a2),d3
	lsl.w	#8,d3
	move.b	1(a2),d3		; the destination nibble address
	moveq	#0,d6
	move.b	2(a2),d6
	lsl.w	#8,d6
	move.b	3(a2),d6
	and.w	#$FFFC,d6		; the source nibble address
	lea	jf_blitimg,a0
	move.l	(a0,d6.l),d0
	beq	.slow
	move.l	d0,a1
	moveq	#0,d6
	move.b	d3,d6			; x0
	cmp.w	#240,d6
	bhi	.slow
	move.w	d3,d2
	lsr.w	#8,d2
	sub.w	#16,d2			; c0
	cmp.w	#-16,d2
	ble	.out			; (wholly left of the picture: nothing shown)
	cmp.w	#224,d2
	bge	.out
	move.w	d2,d4
	asr.w	#4,d4			; the group g of its first column
	and.w	#15,d2			; the shift
	move.w	#$0203,d0		; the pass: HOP 2 / OP 3, an erasing blit HOP 0 / OP 0
	btst	#0,3(a2)
	bne.s	.cp
	moveq	#0,d0
.cp:	move.w	d0,B_HOP.w
	move.w	d2,d0
	lsl.w	#8,d0
	move.w	d2,d1
	lsl.w	#6,d1
	add.w	d1,d0			; shift * 320
	add.w	d0,a1
	move.w	#255,d0
	sub.w	d6,d0			; the first picture line
	mulu	#LB,d0
	lea	vram+24,a2
	add.l	d0,a2
	moveq	#16-1,d3
	tst.w	d2
	beq	.one0			; (shift 0: the second word is empty)
	cmp.w	#13,d4
	beq	.one0			; (the last group: the second word is outside the picture)
	tst.w	d4
	bmi	.one1			; (the group before the first: only its second word)
	; both words: 2 words x 4 planes
	move.w	#2,B_SXI.w
	move.w	#2,B_SYI.w
	move.w	#8,B_DXI.w
	move.w	#-6,B_DYI.w
	move.w	#2,B_XC.w
	lsl.w	#3,d4
	add.w	d4,a2
.l2:	tst.l	(a1)
	beq.s	.s2
	move.w	(a1),B_END1.w
	move.w	2(a1),B_END3.w
	lea	4(a1),a0
	move.l	a0,B_SRC.w
	move.l	a2,B_DST.w
	move.w	#4,B_YC.w
	move.b	#$C0,B_CTRL.w
.s2:	lea	20(a1),a1
	lea	-LB(a2),a2
	dbf	d3,.l2
	bra	.out
	; one word (the first): 1 word x 4 planes, the source's next plane 4 bytes on
.one0:	moveq	#0,d0			; the mask word offset 0, the source offset 4
	lsl.w	#3,d4
	add.w	d4,a2
	bra.s	.one
.one1:	moveq	#2,d0			; the second word: the mask word offset 2, the source offset 6; the group 0
.one:	move.w	#4,B_SYI.w
	move.w	#2,B_DYI.w
	move.w	#2,B_SXI.w
	move.w	#2,B_DXI.w
	move.w	#1,B_XC.w
.l1:	tst.l	(a1)
	beq.s	.s1
	move.w	(a1,d0.w),B_END1.w
	lea	4(a1),a0
	add.w	d0,a0
	move.l	a0,B_SRC.w
	move.l	a2,B_DST.w
	move.w	#4,B_YC.w
	move.b	#$C0,B_CTRL.w
.s1:	lea	20(a1),a1
	lea	-LB(a2),a2
	dbf	d3,.l1
.out:	movem.l	(sp)+,d0-d4/d6/a0-a3
	rts
.slow:	movem.l	(sp)+,d0-d4/d6/a0-a3
	bra	blit_slow

; blit_slow: MAME's blitter_w at the write to $8073: 16 x 16 pixels, the source nibbles from jf_blitrom
; (address & $FFFC, the high nibble first), the destination nibble address (a row is 256 nibbles on), a source pixel
; of 0 skipped, else written (the source address' bit 0 set) or a zero.
blit_slow:
	movem.l	d0-d4/d6/a0-a2,-(sp)
	lea	jf_blt,a2
	moveq	#0,d3
	move.b	(a2),d3
	lsl.w	#8,d3
	move.b	1(a2),d3		; the destination nibble address
	moveq	#0,d6
	move.b	2(a2),d6
	lsl.w	#8,d6
	move.b	3(a2),d6
	and.w	#$FFFC,d6		; the source nibble address
	moveq	#15,d7
.row:	moveq	#15,d5
.px:	move.l	d6,d0
	lsr.l	#1,d0
	cmp.l	#$6000,d0
	bhs.s	.zero			; (beyond the ROM: MAME reads past its region)
	lea	jf_blitrom,a0
	move.b	(a0,d0.l),d0
	btst	#0,d6
	bne.s	.lo
	lsr.b	#4,d0
.lo:	and.b	#15,d0
	bra.s	.got
.zero:	moveq	#0,d0
.got:	addq.l	#1,d6
	tst.b	d0
	beq.s	.skip
	btst	#0,3(a2)
	bne.s	.cp
	moveq	#0,d0			; (the clear blit)
.cp:	cmp.l	#$10000,d3
	bhs.s	.skip
	move.w	d3,d2
	lsr.w	#8,d2			; y
	cmp.w	#16,d2
	blo.s	.skip
	cmp.w	#240,d2
	bhs.s	.skip
	sub.w	#16,d2
	moveq	#0,d1
	move.b	d3,d1			; x
	neg.w	d1
	add.w	#255,d1
	bsr	put_px
.skip:	addq.l	#1,d3
	dbf	d5,.px
	add.l	#240,d3
	dbf	d7,.row
	movem.l	(sp)+,d0-d4/d6/a0-a2
	rts


; mark_all: every cell changed.  mark_blit: the cells the blit of jf_blt may change (a conservative rectangle).
mark_all:
	movem.l	d0-d1/a0,-(sp)
	lea	cell_marks,a0
	move.w	#2048/4-1,d0
	moveq	#-1,d1
.l:	move.l	d1,(a0)+
	dbf	d0,.l
	movem.l	(sp)+,d0-d1/a0
	rts

; mark_rows: the cells of the video RAM rows d2.w .. d3.w - 1 (every line; the groups of those rows).  Keeps every register.
mark_rows:
	movem.l	d0-d4/a0,-(sp)
	move.w	d2,d0
	sub.w	#16,d0
	bpl.s	.a
	moveq	#0,d0
.a:	lsr.w	#4,d0			; the first group
	move.w	d3,d1
	subq.w	#1,d1
	sub.w	#16,d1
	bmi.s	.out			; (only rows not shown)
	lsr.w	#4,d1
	cmp.w	#13,d1
	ble.s	.b
	moveq	#13,d1
.b:	cmp.w	d0,d1
	blt.s	.out
	sub.w	d0,d1			; groups - 1
	lea	cell_marks,a0
	add.w	d0,a0
	moveq	#128-1,d3
.row:	move.w	d1,d4
	move.l	a0,-(sp)
.col:	st	(a0)+
	dbf	d4,.col
	move.l	(sp)+,a0
	lea	16(a0),a0
	dbf	d3,.row
.out:	movem.l	(sp)+,d0-d4/a0
	rts

mark_blit:
	movem.l	d0-d4/a0-a1,-(sp)
	moveq	#0,d0
	move.b	jf_blt+1,d0		; x0
	cmp.w	#240,d0
	bhi.s	.all			; (a row that wraps)
	moveq	#0,d2
	move.b	jf_blt,d2
	sub.w	#16,d2			; the first column
	cmp.w	#-16,d2
	ble.s	.out
	cmp.w	#224,d2
	bge.s	.out
	move.w	d2,d3
	asr.w	#4,d3			; the first group (-1 .. 13)
	move.w	d3,d4
	addq.w	#1,d4			; the second
	tst.w	d3
	bpl.s	.g1
	moveq	#0,d3
.g1:	cmp.w	#13,d4
	ble.s	.g2
	moveq	#13,d4
.g2:	move.w	#255,d1
	sub.w	d0,d1			; the first picture line
	move.w	d1,d0
	lsr.w	#1,d0			; the last pair
	sub.w	#15,d1
	lsr.w	#1,d1			; the first pair
	sub.w	d1,d0			; pairs - 1
	lsl.w	#4,d1
	lea	cell_marks,a0
	add.w	d1,a0
	add.w	d3,a0
	sub.w	d3,d4			; groups - 1
.row:	move.w	d4,d2
	move.l	a0,a1
.col:	st	(a1)+
	dbf	d2,.col
	lea	16(a0),a0
	dbf	d0,.row
.out:	movem.l	(sp)+,d0-d4/a0-a1
	rts
.all:	bsr	mark_all
	bra.s	.out

; ----------------------------------------------------------------------------------------------------------------------
; vram_clear_bytes: the video RAM bytes d5.l .. d7.l - 1 to 0 (the program's clear loops, natives below); keeps every
; register but d5 / d7.  The partial rows at the ends pixel by pixel, the rows between by Blitter fills (clear_rows).
; ----------------------------------------------------------------------------------------------------------------------
vram_clear_bytes:
	movem.l	d0-d4/d6/a0-a2,-(sp)
	move.l	d5,d0
	move.l	d7,d1
	cmp.l	d1,d0
	bhs	.out
	move.w	d0,d2
	and.w	#127,d2
	beq.s	.full
.pa:	move.w	d0,d7			; (the first row's bytes from the start)
	moveq	#0,d5
	bsr	vram_wr
	addq.l	#1,d0
	cmp.l	d1,d0
	bhs.s	.out
	move.w	d0,d2
	and.w	#127,d2
	bne.s	.pa
.full:	move.l	d0,d2
	lsr.l	#7,d2			; the first full row
	move.l	d1,d3
	lsr.l	#7,d3			; the row the end is in
	cmp.w	d3,d2
	bhs.s	.tail
	bsr	mark_rows
	bsr	clear_rows
	move.l	d3,d0
	lsl.l	#7,d0
.tail:	cmp.l	d1,d0
	bhs.s	.out
	move.w	d0,d7
	moveq	#0,d5
	bsr	vram_wr
	addq.l	#1,d0
	bra.s	.tail
.out:	movem.l	(sp)+,d0-d4/d6/a0-a2
	rts

; clear_rows: the arcade rows d2.w .. d3.w - 1 (the shown ones: 16-239) in every picture line: the columns row - 16.  The
; interior groups by one fill (blit_go_fill: short HOG pieces), a partial group at an end plane by plane (all 256 lines).
clear_rows:
	cmp.w	#16,d2
	bge.s	.a
	moveq	#16,d2
.a:	cmp.w	#240,d3
	ble.s	.b
	move.w	#240,d3
.b:	cmp.w	d3,d2
	bhs	.ret
	sub.w	#16,d2			; the first column
	sub.w	#17,d3			; the last column
	move.w	d2,d0
	lsr.w	#4,d0
	move.w	d0,cr_ga
	move.w	d3,d0
	lsr.w	#4,d0
	move.w	d0,cr_gb
	move.w	#$FFFF,d0
	and.w	#15,d2
	lsr.w	d2,d0			; the columns from the first one's bit on
	move.w	d0,cr_first
	move.w	#$FFFF,d0
	moveq	#15,d1
	and.w	d3,d1
	neg.w	d1
	add.w	#15,d1
	lsl.w	d1,d0			; the columns to the last one's bit
	move.w	d0,cr_last
	move.w	#0,B_HOP.w		; HOP 0 / OP 0: a fill with zero
	moveq	#-1,d0
	move.w	d0,B_END2.w
	clr.b	B_SKEW.w
	move.w	cr_ga,d4
	move.w	cr_gb,d6
	cmp.w	d6,d4
	bne.s	.multi
	move.w	cr_first,d0
	and.w	cr_last,d0
	cmp.w	#$FFFF,d0
	beq.s	.inter
	bsr	cr_partial
	bra.s	.ret
.inter:	bsr	cr_interior
	bra.s	.ret
.multi:	move.w	cr_first,d0
	cmp.w	#$FFFF,d0
	beq.s	.nofirst
	movem.w	d4/d6,-(sp)
	bsr	cr_partial
	movem.w	(sp)+,d4/d6
	addq.w	#1,d4
.nofirst:
	move.w	cr_last,d0
	cmp.w	#$FFFF,d0
	beq.s	.nolast
	movem.w	d4/d6,-(sp)
	move.w	d6,d4
	bsr	cr_partial
	movem.w	(sp)+,d4/d6
	subq.w	#1,d6
.nolast:
	cmp.w	d6,d4
	bhi.s	.ret
	bsr	cr_interior
.ret:	rts

; cr_partial: group d4.w, the columns' mask d0.w, in each of the four planes
cr_partial:
	move.w	d0,B_END1.w
	move.w	d0,B_END3.w
	move.w	#LB,B_DYI.w
	move.w	#1,B_XC.w
	lea	vram+24,a0
	move.w	d4,d0
	lsl.w	#3,d0
	add.w	d0,a0
	moveq	#3,d1
.p:	move.l	a0,B_DST.w
	move.w	#256,B_YC.w
	bsr	blit_go_fill
	addq.l	#2,a0
	dbf	d1,.p
	rts

; cr_interior: the groups d4.w .. d6.w, whole: one fill of (groups * 4) words a line
cr_interior:
	moveq	#-1,d0
	move.w	d0,B_END1.w
	move.w	d0,B_END3.w
	move.w	d6,d1
	sub.w	d4,d1
	addq.w	#1,d1
	lsl.w	#2,d1			; the words a line
	move.w	d1,B_XC.w
	move.w	#2,B_DXI.w
	add.w	d1,d1
	neg.w	d1
	add.w	#LB+2,d1		; LB - 2 * (words - 1)
	move.w	d1,B_DYI.w
	lea	vram+24,a0
	move.w	d4,d0
	lsl.w	#3,d0
	add.w	d0,a0
	move.l	a0,B_DST.w
	move.w	#256,B_YC.w
	bra	blit_go_fill

; the natives (gen.py NATIVES): the program's clear loops
; $A0ED: STD ,U++ x 4; CMPU #$7A00; BNE: the video RAM from U to $7A00 (D = 0)
native_clear_A0ED:
	moveq	#0,d5
	move.w	d4,d5
	move.l	#$7A00,d7
	bsr	vram_clear_bytes
	move.w	#$7A00,d4
	moveq	#0,d7			; (CMPU's flags at the end: Z)
	jmp	M00A0FB
; $A055: CLR ,X+; LDA $801C; CMPX #$8000; BNE: the video RAM from X to $8000 (A = 0)
native_clear_A055:
	moveq	#0,d5
	move.w	d2,d5
	move.l	#$8000,d7
	bsr	vram_clear_bytes
	move.w	#$8000,d2
	moveq	#0,d0
	moveq	#0,d7
	jmp	M00A05F

	section data,data
	even
vw_bt:					; per y & 7 (128 bytes): the 16 pixel values' bit (7 - y & 7) in the four plane bytes ($01 each, plane
N	set	0			; 0 the high byte of the long), then the inverted bit in all four
	rept	8
M0	set	(1<<(7-N))*$1000000
M1	set	(1<<(7-N))*$10000
M2	set	(1<<(7-N))*$100
M3	set	(1<<(7-N))
V	set	0
	rept	16
	dc.l	(V&1)*M0+((V>>1)&1)*M1+((V>>2)&1)*M2+((V>>3)&1)*M3
V	set	V+1
	endr
	dc.l	~((1<<(7-N))*$01010101)
	dcb.b	60,0
N	set	N+1
	endr
	section bss,bss
	cnop	0,4
buf_base:	ds.l	NBUF
shown_idx:	ds.w	1
prev_idx:	ds.w	1
draw_idx:	ds.w	1
pic_shown:	ds.w	1
frame_ready:	ds.b	1
	even
cr_ga:		ds.w	1
cr_gb:		ds.w	1
cr_first:	ds.w	1
cr_last:	ds.w	1
	even
shown_pal:	ds.w	16
black_pal:	ds.w	16
pend_pal:	ds.w	16
	cnop	0,4
buffers:	ds.b	NBUF*BUFSZ
vram:		ds.b	VSZ
vw_ptr:		ds.l	32768
vw_tab:		ds.l	32768
cell_marks:	ds.b	2048		; per cell (16 line pairs' cells a row: k * 16 + g): a bit per display buffer that does not have it yet
	section data,data
	include	"jf_assets.s"
	include	"jf_blitimg.s"
	section text,code
