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
	rts

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
	; one HOG copy of the 256 lines (80 words each)
	move.w	#$0203,B_HOP.w
	moveq	#-1,d0
	move.w	d0,B_END1.w
	move.w	d0,B_END2.w
	move.w	d0,B_END3.w
	move.w	#2,B_SXI.w
	move.w	#2,B_SYI.w
	move.w	#2,B_DXI.w
	move.w	#2,B_DYI.w
	clr.b	B_SKEW.w
	move.l	#vram,B_SRC.w
	move.l	a1,B_DST.w
	move.w	#LB/2,B_XC.w
	move.w	#256,B_YC.w
	bsr	blit_go_copy
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
	movem.l	d0-d4/d6/a0,-(sp)
	move.w	d7,d2
	lsr.w	#7,d2			; y
	cmp.w	#16,d2
	blo.s	.out
	cmp.w	#240,d2
	bhs.s	.out
	sub.w	#16,d2			; the picture column
	moveq	#127,d1
	and.w	d7,d1
	add.w	d1,d1			; x
	neg.w	d1
	add.w	#255,d1			; the picture line
	move.b	d5,d0
	and.b	#15,d0
	bsr	put_px
	subq.w	#1,d1
	move.b	d5,d0
	lsr.b	#4,d0
	bsr	put_px
.out:	movem.l	(sp)+,d0-d4/d6/a0
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

; blit_run: MAME's blitter_w at the write to $8073: 16 x 16 pixels, the source nibbles from jf_blitrom
; (address & $FFFC, the high nibble first), the destination nibble address (a row is 256 nibbles on), a source pixel
; of 0 skipped, else written (the source address' bit 0 set) or a zero.
blit_run:
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

	section bss,bss
	cnop	0,4
buf_base:	ds.l	NBUF
shown_idx:	ds.w	1
prev_idx:	ds.w	1
draw_idx:	ds.w	1
pic_shown:	ds.w	1
frame_ready:	ds.b	1
	even
shown_pal:	ds.w	16
black_pal:	ds.w	16
pend_pal:	ds.w	16
	cnop	0,4
buffers:	ds.b	NBUF*BUFSZ
vram:		ds.b	VSZ
	section data,data
	include	"jf_assets.s"
	section text,code
