; Moon Patrol's picture on the STE (included by mpatrol.s).
;
; The arcade picture (240 x 252) lies at screen x 32-271 (both edges on 16-pixel groups: AGENTS.md's clipping), the
; borders open (engine/rt/borders.s, PIC_TOP 10, PIC_LINES 252).  Two sources, switched by borders.s' Timer B events
; (BD_HUD, BD_VSWITCH), each with its own colours:
;
; * the score panel (tile rows 0-6, opaque, never scrolled: picture lines 0-49): an image of its own (hud_img), whose
;   cells are drawn when the text RAM changes them (movep.l rows: the panel is opaque), with its 9 colours
;   (mp_hudpal / mp_hudmap: tools/assets.py, docs/hud_pens.json);
; * the playfield (picture lines 50-251): drawn into one of three buffers (one neither shown nor shown in the frame
;   before: Hatari scans the old one out once more), each with its own 16 colours (pf_pal), published for the VBL.
;   Slot 0 is the background (the sprite palette's pen 0); 1 .. MP_NPIN - 1 hold the mountains' and the hills' or the
;   city's colours (tools/assets.py pinned(): a colour the scene has twice, black ones too, one slot); the rest come
;   with the text and the sprites (text.s, sprites.s).  The playfield is cleared to slot 0, then the
;   backgrounds are drawn as the arcade does (m52.cpp draw_background): the mountains (rows 0-63 of their image as
;   opaque copies of planes 0-1: their pixel 0 is the background), from their row 64 on their fill slot to the bottom; the
;   hills or the city over them (planes 0-2: rows without transparent pixels as copies, the others in pieces: runs
;   of opaque words copied, a partial word a one-word pass with its prepared mask as END1, HOP 2 / OP 3: no AND + OR
;   pairs), from their row 64 on their fill slot (mp_bgfill).  A background's x: picture x 0 shows its pixel u = (12 - x) mod 256 (the
;   doubled image: group u >> 4, the shift u & 15 by the Blitter's skew with a pre-read); its y: row 0 at picture
;   line y - 6.
;
; Tile column c (1-30 visible) shows at picture x 8c - 8, screen x 24 + 8c: byte aligned; tile row r at picture line
; 8r - 6 (row 0's first six lines lie above the picture, in the image's top rows).

HUD_LB = 160
HUD_ROWS = 7
HUD_PRE = 8				; image lines above picture line 0 (tile row 0 starts at -6)
HUD_AREA = (PIC_TOP+HUD_PRE+50)*HUD_LB
PF_LB = 160
PF_TOP = 50				; the playfield's picture lines
PF_BOT = 252
BG_BOT = 250				; the backgrounds end here: lines 250-251 show tile row 0's first lines (the tilemap
					; wraps), which only the RAM clear at 05FA writes: tile 0, colour 0, black like slot 0
PF_X = 16				; the picture's first byte in a line (group 2: screen x 32)
NBUF = 3
BUF_LINES = PIC_LINES+16		; (16 guard lines below the picture: whole sprites at its bottom)
BUF_SZ = BUF_LINES*PF_LB

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
B_SKEW = $ffff8a3d

	section text,code

; ======================================================================================================================
; init_render: the buffers black, the panel drawn whole at the first frame, the display on the panel image
; ======================================================================================================================
init_render:
	lea	hud_area,a0
	move.w	#HUD_AREA/4-1,d0
.clh:	clr.l	(a0)+
	dbf	d0,.clh
	lea	pf_bufs,a0
	move.l	#NBUF*BUF_SZ/4-1,d0
.clp:	clr.l	(a0)+
	subq.l	#1,d0
	bpl.s	.clp
	clr.w	shown_idx
	move.w	#-1,prev_idx
	clr.b	frame_ready
	st	hud_full
	bsr	make_popcnt
	st	tx_scene		; (no scene yet: the first tx_update resets)
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
	lea	pf_bufs,a1
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
; vbl_video: the picture published last goes on screen: its buffer and its colours (borders.s' events)
; ======================================================================================================================
vbl_video:
	movem.l	d0-d3/a0-a1,-(sp)
	move.w	shown_idx,prev_idx
	moveq	#0,d1
	move.b	frame_ready,d1
	beq.s	.out
	clr.b	frame_ready
	subq.w	#1,d1
	move.w	d1,shown_idx
	move.w	d1,d0
	mulu	#BUF_SZ,d0
	add.l	#pf_bufs,d0
	move.l	d0,bd_vs_pf
	lsl.w	#5,d1
	lea	pf_pal,a0
	add.w	d1,a0
	movem.l	(a0),d0-d3
	movem.l	d0-d3,shown_pal
	movem.l	16(a0),d0-d3
	movem.l	d0-d3,shown_pal+16
.out:	movem.l	(sp)+,d0-d3/a0-a1
	rts

; ======================================================================================================================
; render_frame: the arcade frame's picture: the panel's changed cells, the playfield into a free buffer, published
; ======================================================================================================================
render_frame:
	movem.l	d0-d7/a0-a6,-(sp)
	bsr	hud_update
	clr.b	frame_ready		; (a picture not shown yet is dropped: its buffer may be the free one)
	move.w	shown_idx,d1		; a buffer neither shown nor scanned out once more
	move.w	prev_idx,d2
	moveq	#0,d0
.pick:	cmp.w	d1,d0
	beq.s	.nx
	cmp.w	d2,d0
	bne.s	.got
.nx:	addq.w	#1,d0
	bra.s	.pick
.got:	move.w	d0,draw_idx
	mulu	#BUF_SZ,d0
	add.l	#pf_bufs,d0
	move.l	d0,draw_buf
	bsr	spr_need		; (the colours: the sprites' slots kept or given back, the text's, the sprites')
	bsr	spr_release
	bsr	tx_retry
	bsr	tx_update
	bsr	spr_alloc
	bsr	spr_colours
	bsr	pf_palette
	bsr	pf_slots
	bsr	pf_clear
	clr.b	bg_mnt
	move.b	io_regs+6,d0		; the background control
	btst	#5,d0
	bne.s	.nobg
	btst	#4,d0
	bne.s	.nomnt
	moveq	#0,d5			; the distant mountains: background 2's x / y
	move.b	io_regs+4,d6
	move.b	io_regs+5,d7
	bsr	draw_bg
.nomnt:	move.b	io_regs+6,d0
	moveq	#1,d5			; the hills
	btst	#1,d0
	beq.s	.b1
	moveq	#2,d5			; or the city
	btst	#2,d0
	bne.s	.nobg
.b1:	move.b	io_regs+2,d6
	move.b	io_regs+3,d7
	bsr	draw_bg
.nobg:	bsr	tx_draw
	bsr	spr_draw
	move.w	draw_idx,d0
	addq.w	#1,d0
	move.w	d0,pub_idx
	move.b	d0,frame_ready		; (one store: the VBL sees the whole picture or none)
	addq.w	#1,pic_count
	movem.l	(sp)+,d0-d7/a0-a6
	rts

; pf_palette: the drawn buffer's colours: the scene's pinned slots 0 .. MP_NPIN - 1 (the hills' or the city's), the
; rest black (pf_slots then gives the text's and the sprites')
pf_palette:
	move.w	draw_idx,d0
	lsl.w	#5,d0
	lea	pf_pal,a0
	add.w	d0,a0
	lea	mp_pincol,a1
	btst	#1,io_regs+6		; the city when the hills are off
	beq.s	.h
	lea	MP_NPIN*2(a1),a1
.h:	moveq	#MP_NPIN-1,d0
.p:	move.w	(a1)+,(a0)+
	dbf	d0,.p
	moveq	#16-MP_NPIN-1,d0
.z:	clr.w	(a0)+
	dbf	d0,.z
	rts

; pf_clear: the playfield's lines, 15 groups of 4 planes each (60 words a line), slot 0
pf_clear:
	move.l	draw_buf,a0
	lea	PF_TOP*PF_LB+PF_X(a0),a0
	moveq	#-1,d0
	move.w	d0,B_END1.w
	move.w	d0,B_END2.w
	move.w	d0,B_END3.w
	move.w	#2,B_DXI.w
	move.w	#PF_LB-2*59,B_DYI.w
	move.l	a0,B_DST.w
	move.w	#60,B_XC.w
	move.w	#PF_BOT-PF_TOP,B_YC.w
	clr.b	B_HOP.w
	clr.b	B_OP.w
	clr.b	B_SKEW.w
	bra	blit_go_fill

; draw_bg: d5 = the image (0 mountains, 1 hills, 2 city), d6.b = its x, d7.b = its y.  Its rows on the playfield's
; lines (copies; the hills' and the city's rows with transparent pixels in pieces), then its slot 3 / 6 below them.
draw_bg:
	and.w	#$FF,d6
	and.w	#$FF,d7
	subq.w	#6,d7			; row 0's picture line
	moveq	#12,d0			; u = (12 - x) mod 256
	sub.w	d6,d0
	and.w	#$FF,d0
	move.w	d0,d1
	lsr.w	#4,d1			; g: the first source group
	lsl.w	#3,d1
	move.w	d1,bg_g8
	and.w	#15,d0			; s: the shift
	move.w	d0,bg_shift
	moveq	#0,d2			; the skew byte: FXSR + 16 - s, or 0
	tst.w	d0
	beq.s	.sk
	moveq	#16,d2
	sub.w	d0,d2
	or.w	#$80,d2
.sk:	move.b	d2,bg_skew
	move.w	d5,d0
	lsl.w	#2,d0
	lea	bg_images,a0
	move.l	(a0,d0.w),a4		; the image
	moveq	#0,d1			; the first row k0 = max(0, PF_TOP - line), the end k1 = min(64, PF_BOT - line)
	move.w	#PF_TOP,d2
	sub.w	d7,d2
	ble.s	.k0
	move.w	d2,d1
.k0:	moveq	#64,d2
	move.w	#BG_BOT,d3
	sub.w	d7,d3
	cmp.w	d2,d3
	bge.s	.k1
	move.w	d3,d2
.k1:	cmp.w	d2,d1
	bge	.fill
	tst.w	d5
	bne.s	.masked
	move.w	d7,bg_mline		; (the hills / the city look at what lies behind them)
	st	bg_mnt
	moveq	#0,d4			; the mountains: planes 0 and 1, all their rows a pass each
	bsr	bg_rows
	moveq	#1,d4
	bsr	bg_rows
	bra	.fill
.masked:				; the hills / the city: each row as what lies behind it allows
	lea	bg_rowtab-4,a3
	move.l	(a3,d0.w),a3		; the rows' mask blocks (d0 = the image * 4)
	lea	bg_fillimg-4,a5
	move.l	(a5,d0.w),a5		; the version over the mountains' fill
	move.w	d0,bg_img4
	move.w	d2,d3			; k1
.run:	cmp.w	d3,d1
	bge	.fill
	bsr	.class
	cmp.w	#2,d0
	bne.s	.opq
	bsr	bg_row_list		; over the mountains' image: the row's passes
	addq.w	#1,d1
	bra.s	.run
.opq:	move.w	d0,d4			; a run of rows of one opaque kind: d6 .. d1 - 1
	move.w	d1,d6
.rs:	addq.w	#1,d1
	cmp.w	d3,d1
	bge.s	.re
	bsr	.class
	cmp.w	d4,d0
	beq.s	.rs
.re:	move.w	d1,d2
	move.w	d1,-(sp)
	move.w	d6,d1
	move.l	a4,-(sp)
	tst.w	d4
	beq.s	.v0
	move.l	a5,a4			; (behind them the mountains' fill: the version with its slot in the holes)
.v0:	moveq	#0,d4
	bsr	bg_rows
	moveq	#1,d4
	bsr	bg_rows
	moveq	#2,d4
	bsr	bg_rows
	move.l	(sp)+,a4
	move.w	(sp)+,d1
	bra.s	.run
.class:	; row d1 -> d0: 0 opaque (no transparent pixel, or nothing but slot 0 behind it), 1 opaque over the mountains'
	; fill, 2 over the mountains' image (in passes)
	move.w	d1,d0
	add.w	d0,d0
	tst.w	(a3,d0.w)
	beq.s	.c0
	tst.b	bg_mnt
	beq.s	.c0
	move.w	d7,d0			; the mountains' row behind it
	add.w	d1,d0
	sub.w	bg_mline,d0
	bmi.s	.c0
	cmp.w	#64,d0
	bge.s	.c1
	moveq	#2,d0
	rts
.c1:	moveq	#1,d0
	rts
.c0:	moveq	#0,d0
	rts
.fill:	move.w	d7,d1			; slot 3 (the mountains) or 6 from row 64 to the bottom
	add.w	#64,d1
	cmp.w	#PF_TOP,d1
	bge.s	.f0
	move.w	#PF_TOP,d1
.f0:	cmp.w	#BG_BOT,d1
	bge.s	.out
	lea	mp_bgfill,a0		; (its pixel value 3's slot)
	moveq	#0,d0
	move.b	(a0,d5.w),d0
	bra	pf_fill
.out:	rts

; bg_row_list: row d1 of the image a4 (the hills or the city: bg_img4) at line d7 + d1 over the mountains: its passes
; (mp_bgp: runs of opaque words with a partial word at either end; END1 / END3 the end words' masks at the shift: the
; mask table, 32 words a shift) clipped to the window's 15 words from group g, planes 0-2, HOP 2 / OP 3.  Keeps all.
bg_row_list:
	movem.l	d0-d7/a0-a4,-(sp)
	move.w	bg_img4,d0
	lea	bg_rowtab-4,a0
	move.l	(a0,d0.w),a0
	move.w	d1,d2
	add.w	d2,d2
	move.w	(a0,d2.w),d2		; the row's block + 1
	subq.w	#1,d2
	lea	bg_masks-4,a0
	move.l	(a0,d0.w),a2
	move.w	d2,d3
	mulu	#16*32*2,d3
	add.l	d3,a2
	move.w	bg_shift,d3
	lsl.w	#6,d3
	add.w	d3,a2			; the masks of the doubled row's 32 words at this shift
	lea	bg_pindex-4,a0
	move.l	(a0,d0.w),a0
	lsl.w	#4,d2
	add.w	bg_shift,d2
	add.w	d2,d2
	move.w	(a0,d2.w),d2		; the list's offset
	lea	bg_plist-4,a3
	move.l	(a3,d0.w),a3
	add.w	d2,a3
	move.w	d1,d0			; the source row, the destination line
	lsl.w	#8,d0
	move.l	a4,a0
	add.w	d0,a0
	move.w	d7,d0
	add.w	d1,d0
	mulu	#PF_LB,d0
	move.l	draw_buf,a1
	add.l	d0,a1
	lea	PF_X(a1),a1
	move.w	#8,B_SXI.w
	move.w	#8,B_DXI.w
	move.b	#2,B_HOP.w
	move.b	#3,B_OP.w
	move.w	#-1,B_END2.w
	move.w	bg_g8,d6
	lsr.w	#3,d6			; g
	moveq	#15,d7
	add.w	d6,d7			; g + 15
	moveq	#0,d5			; 1 with the pre-read
	tst.b	bg_skew
	beq.s	.p
	moveq	#1,d5
.p:	moveq	#0,d0
	move.b	(a3)+,d0		; the first word
	cmp.b	#$FF,d0
	beq	.done
	moveq	#0,d1
	move.b	(a3)+,d1		; the end
	cmp.w	d6,d1
	ble.s	.p			; (before the window)
	cmp.w	d7,d0
	bge.s	.done			; (after it: the list is in order)
	cmp.w	d6,d0
	bge.s	.c1
	move.w	d6,d0
.c1:	cmp.w	d7,d1
	ble.s	.c2
	move.w	d7,d1
.c2:	move.w	d0,d2
	add.w	d2,d2
	move.w	(a2,d2.w),B_END1.w
	move.w	d1,d2
	add.w	d2,d2
	move.w	-2(a2,d2.w),B_END3.w
	sub.w	d0,d1			; the words
	move.w	d0,d2
	lsl.w	#3,d2
	lea	(a0,d2.w),a4
	move.l	a4,B_SRC.w
	sub.w	d6,d0
	lsl.w	#3,d0
	lea	(a1,d0.w),a4
	move.l	a4,B_DST.w
	move.w	d1,B_XC.w
	move.w	#3,B_YC.w
	move.w	d1,d2			; the source: d1 reads (+ the pre-read), then the next plane
	add.w	d5,d2
	subq.w	#1,d2
	lsl.w	#3,d2
	neg.w	d2
	addq.w	#2,d2
	move.w	d2,B_SYI.w
	move.w	d1,d2			; the destination: d1 writes, then the next plane
	subq.w	#1,d2
	lsl.w	#3,d2
	neg.w	d2
	addq.w	#2,d2
	move.w	d2,B_DYI.w
	move.b	bg_skew,B_SKEW.w
	move.b	#$C0,$ffff8a3c.w	; (start: at most 15 words of 3 planes: a short pass)
	bra	.p
.done:	movem.l	(sp)+,d0-d7/a0-a4
	rts

; bg_rows: rows d1 .. d2 - 1 of the image a4 at line d7 + k, plane d4: one pass (the Blitter's skew and pre-read).
; Keeps all registers.
bg_rows:
	movem.l	d0-d3/a0-a1,-(sp)
	move.w	d2,d3
	sub.w	d1,d3			; the rows
	move.w	d1,d0
	lsl.w	#8,d0			; (256 bytes a row)
	move.l	a4,a0
	add.w	d0,a0
	add.w	bg_g8,a0
	add.w	d4,a0
	add.w	d4,a0
	move.w	d7,d0
	add.w	d1,d0
	mulu	#PF_LB,d0
	move.l	draw_buf,a1
	add.l	d0,a1
	lea	PF_X(a1),a1
	add.w	d4,a1
	add.w	d4,a1
	moveq	#-1,d0
	move.w	d0,B_END1.w
	move.w	d0,B_END2.w
	move.w	d0,B_END3.w
	move.w	#8,B_SXI.w
	move.w	#8,B_DXI.w
	move.w	#256-8*14,d0		; (15 reads a line; 16 with the pre-read)
	tst.b	bg_skew
	beq.s	.y
	subq.w	#8,d0
.y:	move.w	d0,B_SYI.w
	move.w	#PF_LB-8*14,B_DYI.w
	move.l	a0,B_SRC.w
	move.l	a1,B_DST.w
	move.w	#15,B_XC.w
	move.w	d3,B_YC.w
	move.b	#2,B_HOP.w
	move.b	#3,B_OP.w
	move.b	bg_skew,B_SKEW.w
	bsr	blit_go
	movem.l	(sp)+,d0-d3/a0-a1
	rts

; row_full: a line's 15 destination words from a0 to a1 as one pass (row_pieces' operands; no masks: every pixel of
; the line is opaque).  Keeps all registers.
row_full:
	move.l	d2,-(sp)
	moveq	#-1,d2
	move.w	d2,B_END1.w
	move.w	d2,B_END2.w
	move.w	d2,B_END3.w
	move.w	#8,B_SXI.w
	move.w	#8,B_DXI.w
	move.b	#2,B_HOP.w
	move.b	#3,B_OP.w
	move.l	a0,B_SRC.w
	move.l	a1,B_DST.w
	move.w	#15,B_XC.w
	move.w	pc_planes,B_YC.w
	move.w	#2-8*14,d2		; the source: 15 reads (+ the pre-read), then the next plane
	tst.b	pc_skew
	beq.s	.y
	subq.w	#8,d2
.y:	move.w	d2,B_SYI.w
	move.w	#2-8*14,B_DYI.w
	move.b	pc_skew,B_SKEW.w
	move.b	#$C0,$ffff8a3c.w	; (start: 60 words and 64 reads, under 256 bus cycles)
	move.l	(sp)+,d2
	rts

; row_pieces: a line's 15 destination words from a0 (the source at destination word 0, plane 0; with pc_skew's
; pre-read: the group before) to a1 (word 0, plane 0), their masks at a2 (15 words): a run of $FFFF words one pass,
; a partial word a one-word pass with its mask as END1 (HOP 2 / OP 3: the opaque pixels only), an empty word
; skipped; pc_planes planes a pass (Y count), pc_skew the skew byte.  Every pass is short: started directly.  Keeps
; all registers.
row_pieces:
	movem.l	d0-d6/a3,-(sp)
	move.w	#8,B_SXI.w
	move.w	#8,B_DXI.w
	move.b	#2,B_HOP.w
	move.b	#3,B_OP.w
	moveq	#0,d6			; the word
.w:	cmp.w	#15,d6
	bge.s	.done
	move.w	d6,d0
	add.w	d0,d0
	move.w	(a2,d0.w),d0
	bne.s	.nz
	addq.w	#1,d6
	bra.s	.w
.nz:	cmp.w	#-1,d0
	bne.s	.part
	move.w	d6,d5			; a run of full words: d5 .. d6 - 1
.full:	addq.w	#1,d6
	cmp.w	#15,d6
	bge.s	.fe
	move.w	d6,d2
	add.w	d2,d2
	cmp.w	#-1,(a2,d2.w)
	beq.s	.full
.fe:	move.w	d6,d4
	sub.w	d5,d4			; the words
	moveq	#-1,d0
	bsr.s	.pass
	bra.s	.w
.part:	move.w	d6,d5
	moveq	#1,d4
	addq.w	#1,d6
	bsr.s	.pass
	bra.s	.w
.done:	movem.l	(sp)+,d0-d6/a3
	rts
.pass:	; words d5 .. d5 + d4 - 1, END1 = d0 (a partial word) or $FFFF; pc_planes planes (Y count)
	move.w	d0,B_END1.w
	move.w	#-1,B_END2.w
	move.w	#-1,B_END3.w
	move.w	d5,d2
	lsl.w	#3,d2
	lea	(a0,d2.w),a3
	move.l	a3,B_SRC.w
	lea	(a1,d2.w),a3
	move.l	a3,B_DST.w
	move.w	d4,B_XC.w
	move.w	pc_planes,B_YC.w
	move.w	d4,d2			; the source: d4 reads (+ the pre-read), then the next plane
	tst.b	pc_skew
	bne.s	.p2
	subq.w	#1,d2
.p2:	lsl.w	#3,d2
	neg.w	d2
	addq.w	#2,d2
	move.w	d2,B_SYI.w
	move.w	d4,d2			; the destination: d4 writes, then the next plane
	subq.w	#1,d2
	lsl.w	#3,d2
	neg.w	d2
	addq.w	#2,d2
	move.w	d2,B_DYI.w
	move.b	pc_skew,B_SKEW.w
	move.b	#$C0,$ffff8a3c.w	; (start: busy, HOG.  At most 15 words of 4 planes and their 16 reads: under 256
	rts				; bus cycles, short as blit_go's pieces)

; pf_fill: lines d1 .. BG_BOT - 1 of the playfield in slot d0 (a plane pass each: ones or zeros)
pf_fill:
	movem.l	d0-d4/a0,-(sp)
	move.l	draw_buf,a0
	move.w	d1,d2
	mulu	#PF_LB,d2
	add.l	d2,a0
	lea	PF_X(a0),a0
	move.w	#BG_BOT,d3
	sub.w	d1,d3			; the lines
	moveq	#-1,d2
	move.w	d2,B_END1.w
	move.w	d2,B_END2.w
	move.w	d2,B_END3.w
	move.w	#8,B_DXI.w
	move.w	#PF_LB-8*14,B_DYI.w
	clr.b	B_HOP.w
	clr.b	B_SKEW.w
	moveq	#3,d4
.pl:	move.l	a0,B_DST.w
	move.w	#15,B_XC.w
	move.w	d3,B_YC.w
	move.b	#15,B_OP.w		; (ones)
	lsr.b	#1,d0
	bcs.s	.one
	clr.b	B_OP.w			; (zeros)
.one:	bsr	blit_go_fill
	addq.w	#2,a0
	dbf	d4,.pl
	movem.l	(sp)+,d0-d4/a0
	rts

bg_images:	dc.l	mp_bg0,mp_bg1,mp_bg2
bg_fillimg:	dc.l	mp_bg1f,mp_bg2f
bg_plist:	dc.l	mp_bgp1,mp_bgp2
bg_pindex:	dc.l	mp_bgpi1,mp_bgpi2
bg_rowtab:	dc.l	mp_bgr1,mp_bgr2
bg_masks:	dc.l	mp_bgm1,mp_bgm2

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

	include	"text.s"
	include	"sprites.s"
	include	"mp_assets.s"

; ======================================================================================================================
	section bss,bss
; ======================================================================================================================
	cnop	0,256
hud_area:	ds.b	PIC_TOP*HUD_LB
		ds.b	HUD_PRE*HUD_LB
hud_img:	ds.b	50*HUD_LB	; picture lines 0-49 (HUD_PRE lines above for tile row 0)
	cnop	0,256
pf_bufs:	ds.b	NBUF*BUF_SZ	; the playfield buffers (picture line 0 at each one's start)
pf_pal:		ds.w	NBUF*16		; their colours
draw_buf:	ds.l	1
draw_idx:	ds.w	1
shown_idx:	ds.w	1
prev_idx:	ds.w	1
pub_idx:	ds.w	1		; (the last published buffer + 1: the tests read it)
bg_shift:	ds.w	1
bg_g8:		ds.w	1
frame_ready:	ds.b	1		; a picture published for the VBL: its buffer + 1
bg_skew:	ds.b	1
pc_skew:	ds.b	1		; (row_pieces: the skew byte, the planes a pass)
	even
pc_planes:	ds.w	1
bg_img4:	ds.w	1		; (the hills / the city: the image * 4)
bg_mline:	ds.w	1		; the mountains' row 0 line (bg_mnt: drawn this picture)
bg_mnt:		ds.b	1
	even
hud_vram:	ds.b	HUD_ROWS*32	; the panel's text RAM as drawn
hud_cram:	ds.b	HUD_ROWS*32
cell_planes:	ds.l	1
hud_full:	ds.b	1
	even
pic_count:	ds.w	1
	section text,code
