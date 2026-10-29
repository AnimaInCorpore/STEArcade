; Moon Patrol's picture on the STE (included by mpatrol.s).
;
; The arcade picture (240 x 252) lies at screen x 32-271 (both edges on 16-pixel groups: AGENTS.md's clipping), the
; borders open (engine/rt/borders.s, PIC_TOP 10, PIC_LINES 252).  Two sources, switched by borders.s' Timer B events
; (BD_HUD, BD_VSWITCH), each with its own colours:
;
; * the score panel (tile rows 0-6, opaque, never scrolled: picture lines 0-49): an image of its own (hud_img), whose
;   cells are drawn when the text RAM changes them (movep.l rows: the panel is opaque), with its 9 colours
;   (mp_hudpal / mp_hudmap: tools/assets.py, docs/hud_pens.json);
; * the playfield (picture lines 50-251): so far a black buffer; the parallax layers, the text and the sprites come
;   next (README: "The picture").
;
; Tile column c (1-30 visible) shows at picture x 8c - 8, screen x 24 + 8c: byte aligned; tile row r at picture line
; 8r - 6 (row 0's first six lines lie above the picture, in the image's top rows).

HUD_LB = 160
HUD_ROWS = 7
HUD_PRE = 8				; image lines above picture line 0 (tile row 0 starts at -6)
HUD_AREA = (PIC_TOP+HUD_PRE+50)*HUD_LB
PF_LB = 160

	section text,code

; ======================================================================================================================
; init_render: the buffers black, the panel drawn whole at the first frame, the display on the panel image
; ======================================================================================================================
init_render:
	lea	hud_area,a0
	move.w	#HUD_AREA/4-1,d0
.clh:	clr.l	(a0)+
	dbf	d0,.clh
	lea	pf_buf,a0
	move.w	#PIC_LINES*PF_LB/4-1,d0
.clp:	clr.l	(a0)+
	dbf	d0,.clp
	st	hud_full
	lea	mp_hudpal,a0
	movem.l	(a0),d0-d7
	movem.l	d0-d7,hud_pal
	lea	shown_pal,a0		; (the playfield black so far)
	moveq	#7,d0
.sp:	clr.l	(a0)+
	dbf	d0,.sp
	lea	black_pal,a0
	moveq	#7,d0
.bp:	clr.l	(a0)+
	dbf	d0,.bp
	move.w	#50,hud_top
	move.w	#PIC_LINES,hud_bot
	lea	hud_img,a0
	move.l	a0,d0
	sub.l	#PIC_TOP*HUD_LB,d0
	bsr	set_base
	lea	pf_buf,a1
	move.l	a1,bd_vs_pf
	move.w	#PF_LB,bd_vs_pfs
	clr.w	bd_vs_pfl
	clr.w	bd_vs_pfh
	move.l	a0,bd_vs_bar
	move.w	#HUD_LB,bd_vs_bas
	clr.w	bd_vs_bal
	clr.w	bd_vs_bah
	st	bd_vs_on
	rts

set_base:				; d0 = the address of the display's first line
	ifnd SIM
	move.l	d0,-(sp)
	move.b	1(sp),$ffff8201.w
	move.b	2(sp),$ffff8203.w
	move.b	3(sp),$ffff820d.w
	move.b	1(sp),$ffff8205.w	; (the counter too: the STE's is writable)
	move.b	2(sp),$ffff8207.w
	move.b	3(sp),$ffff8209.w
	addq.l	#4,sp
	clr.b	$ffff8265.w
	clr.b	$ffff820f.w
	endc
	rts

; ======================================================================================================================
; vbl_video: the published picture on screen (so far nothing changes: the panel image and the black playfield)
; ======================================================================================================================
vbl_video:
	rts

; ======================================================================================================================
; render_frame: the arcade frame's picture
; ======================================================================================================================
render_frame:
	bsr	hud_update
	addq.w	#1,pic_count
	rts

; ----------------------------------------------------------------------------------------------------------------------
; hud_update: the panel's cells whose text RAM (codes $8000, colours $8400: rows 0-6) changed since they were drawn
; ----------------------------------------------------------------------------------------------------------------------
hud_update:
	movem.l	d0-d7/a0-a6,-(sp)
	lea	Z_RAM+$8000,a0
	lea	Z_RAM+$8400,a1
	lea	hud_vram,a2
	lea	hud_cram,a3
	moveq	#0,d6			; the cell
	tst.b	hud_full
	bne.s	.all
.long:	cmpm.l	(a0)+,(a2)+		; (four cells at a time: equal longs skipped)
	bne.s	.diff4
	cmpm.l	(a1)+,(a3)+
	bne.s	.diff4
	addq.w	#4,d6
	cmp.w	#HUD_ROWS*32,d6
	blo.s	.long
	bra.s	.out
.diff4:	lea	Z_RAM+$8000,a0		; (the four pointers at the long's first cell again)
	add.w	d6,a0
	lea	hud_vram,a2
	add.w	d6,a2
	lea	Z_RAM+$8400,a1
	add.w	d6,a1
	lea	hud_cram,a3
	add.w	d6,a3
	moveq	#3,d7
.cell:	move.b	(a0)+,d0
	move.b	(a1)+,d1
	cmp.b	(a2),d0
	bne.s	.chg
	cmp.b	(a3),d1
	beq.s	.same
.chg:	move.b	d0,(a2)
	move.b	d1,(a3)
	bsr	draw_hud_cell
.same:	addq.w	#1,a2
	addq.w	#1,a3
	addq.w	#1,d6
	dbf	d7,.cell
	cmp.w	#HUD_ROWS*32,d6
	blo.s	.long
	bra.s	.out
.all:	clr.b	hud_full
.al:	move.b	(a0)+,(a2)+
	move.b	(a1)+,(a3)+
	bsr	draw_hud_cell
	addq.w	#1,d6
	cmp.w	#HUD_ROWS*32,d6
	blo.s	.al
.out:	movem.l	(sp)+,d0-d7/a0-a6
	rts

; d6 = the cell (row * 32 + column): its tile and colour from hud_vram / hud_cram, drawn into hud_img.  Keeps all
; but d0-d5.
draw_hud_cell:
	move.w	d6,d0
	and.w	#31,d0			; the column: 1-30 visible
	beq	.out
	cmp.w	#31,d0
	beq	.out
	movem.l	d6-d7/a0-a4,-(sp)
	lea	hud_vram,a0
	moveq	#0,d1
	move.b	(a0,d6.w),d1		; the code
	lea	hud_cram,a0
	moveq	#0,d2
	move.b	(a0,d6.w),d2
	bpl.s	.lo
	bset	#8,d1
.lo:	and.w	#$7F,d2			; the colour: its four pens' panel indices
	lsl.w	#2,d2
	lea	mp_hudmap,a1
	add.w	d2,a1
	lsl.w	#4,d1			; the tile's rows (16 bytes)
	lea	mp_tiles,a3
	add.w	d1,a3
	move.w	d6,d1			; the destination: row * 8 - 6 lines, x = 24 + 8 * column
	lsr.w	#5,d1
	mulu	#8*HUD_LB,d1
	lea	hud_img-6*HUD_LB,a2
	add.l	d1,a2
	add.w	#3,d0			; (x / 8 = column + 3)
	move.w	d0,d1
	lsr.w	#1,d1
	lsl.w	#3,d1			; the group's 8 bytes
	and.w	#1,d0			; its first or second byte
	add.w	d0,d1
	add.w	d1,a2
	lea	cell_planes,a4
	moveq	#7,d7
.row:	move.b	(a3)+,d4		; the high plane (the pixel value's bit 1)
	move.b	(a3)+,d5		; the low plane
	clr.l	(a4)
	move.b	d4,d0			; pixel 3: high and low
	and.b	d5,d0
	move.b	3(a1),d1
	bsr.s	.add
	move.b	d5,d0			; pixel 2: high, not low
	not.b	d0
	and.b	d4,d0
	move.b	2(a1),d1
	bsr.s	.add
	move.b	d4,d0			; pixel 1: low, not high
	not.b	d0
	and.b	d5,d0
	move.b	1(a1),d1
	bsr.s	.add
	move.b	d4,d0			; pixel 0: neither
	or.b	d5,d0
	not.b	d0
	move.b	(a1),d1
	bsr.s	.add
	move.l	(a4),d0
	movep.l	d0,0(a2)
	lea	HUD_LB(a2),a2
	dbf	d7,.row
	movem.l	(sp)+,d6-d7/a0-a4
.out:	rts
.add:	lsr.b	#1,d1			; d0 = the pixels, d1 = their panel index: its bits into planes 0-3
	bcc.s	.p1
	or.b	d0,(a4)
.p1:	lsr.b	#1,d1
	bcc.s	.p2
	or.b	d0,1(a4)
.p2:	lsr.b	#1,d1
	bcc.s	.p3
	or.b	d0,2(a4)
.p3:	lsr.b	#1,d1
	bcc.s	.p4
	or.b	d0,3(a4)
.p4:	rts

	include	"mp_assets.s"

; ======================================================================================================================
	section bss,bss
; ======================================================================================================================
	cnop	0,256
hud_area:	ds.b	PIC_TOP*HUD_LB
		ds.b	HUD_PRE*HUD_LB
hud_img:	ds.b	50*HUD_LB	; picture lines 0-49 (HUD_PRE lines above for tile row 0)
	cnop	0,256
pf_buf:		ds.b	PIC_LINES*PF_LB	; the playfield (black so far)
hud_vram:	ds.b	HUD_ROWS*32	; the panel's text RAM as drawn
hud_cram:	ds.b	HUD_ROWS*32
cell_planes:	ds.l	1
hud_full:	ds.b	1
	even
pic_count:	ds.w	1
	section text,code
