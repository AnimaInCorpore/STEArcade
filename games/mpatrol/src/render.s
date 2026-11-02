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
;   with the text and the sprites (text.s, sprites.s).  A buffer keeps its picture: only the lines (or, where nothing
;   scrolled, the 16-pixel groups) whose content changed are drawn again (pf_draw), each from its frontmost opaque
;   layer as m52.cpp's order gives it: the mountains (rows 0-63 of their image, planes 0-1: their pixel 0 is the
;   background), their fill slot below; the hills or the city over them (rows without transparent pixels, or with
;   nothing / the mountains' fill behind them, as copies; over the mountains' image in prepared passes: runs of
;   opaque words with partial end words, END1 / END3 their masks, HOP 2 / OP 3: no AND + OR pairs), their fill slot
;   below; the text; the sprites.  A background's x: picture x 0 shows its pixel u = (12 - x) mod 256 (the doubled
;   image: group u >> 4, the shift u & 15 by the Blitter's skew with a pre-read); its y: row 0 at picture line y - 6.
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
	bsr	pd_init
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
	bsr	pf_draw
	bsr	spr_draw
	bsr	spr_damage
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
	tst.b	tx_scene		; (the city's: text.s tx_update)
	beq.s	.h
	lea	MP_NPIN*2(a1),a1
.h:	moveq	#MP_NPIN-1,d0
.p:	move.w	(a1)+,(a0)+
	dbf	d0,.p
	moveq	#16-MP_NPIN-1,d0
.z:	clr.w	(a0)+
	dbf	d0,.z
	rts

; ======================================================================================================================
; pf_draw: the playfield (lines PF_TOP .. PF_BOT - 1) into draw_buf.  The buffer still holds the picture drawn into it
; last: its scene (bstate: the control, the backgrounds' x / y, the scroll) and pf_dirty (a word a line: the first and
; the last 16-pixel group changed since by baked text cells or drawn sprites; $FF00 none).  What a line shows depends
; on its segment: the lines between the boundaries of the mountains' rows and fill, the hills' / city's rows with
; transparent pixels, their opaque rows and fill, the ground's rows (186) have one kind of background each:
;   0 slot 0 (nothing), 1 the mountains' fill, 2 the hills' / city's fill (fill_planes: a pass a plane, 4 lines a start)
;   3 the mountains' row: planes 0-1 copied (their slots 0-3), planes 2-3 cleared
;   4 the hills' / city's row (planes 0-2 copied, plane 3 cleared): its transparent pixels are slot 0 (no transparent
;     pixel, or nothing behind it); 5 the version with the mountains' fill in its holes
;   7 a ground line without a transparent pixel at the scroll: 4 planes copied, no background
; and the overlays: the hills' row over the mountains' image in passes (bg_row_list, kind byte bit 3), the text's
; pieces (ovl_text).  A segment whose background's x changed (the mountains' rows: theirs; the hills' rows: theirs,
; and the mountains' where a row with transparent pixels lies over their image) is drawn whole: its lines as one run;
; the others only in their changed groups (runs of lines with the same groups).  The ground's lines one by one: those
; with text show the scroll too; full text lines need no background.  Another control or y: every line.  Every pass
; is HOG and short (AGENTS.md: at most 64 bus accesses, 256 bus cycles).
; ======================================================================================================================
PF_NL = PF_BOT-PF_TOP			; (202 lines: 50-251)
GR_I = 186-PF_TOP			; (the ground's first line)
GR_TOP = 186

pf_draw:
	movem.l	d0-d7/a0-a6,-(sp)
	move.w	draw_idx,d0
	lea	bstate,a5
	lsl.w	#3,d0
	add.w	d0,a5
	move.w	draw_idx,d0
	mulu	#PF_NL*2,d0
	lea	pf_dirty,a6
	add.l	d0,a6
	move.l	a6,pd_dirty
	move.b	io_regs+6,d0		; the scene: d6 the mountains on, d5 1 the hills, 2 the city, 0 none
	moveq	#0,d6
	moveq	#0,d5
	btst	#5,d0
	bne.s	.sc
	btst	#4,d0
	bne.s	.nm
	moveq	#1,d6
.nm:	moveq	#1,d5
	btst	#1,d0
	beq.s	.sc
	moveq	#2,d5
	btst	#2,d0
	beq.s	.sc
	moveq	#0,d5
.sc:	move.w	d5,pd_hk
	moveq	#0,d3			; what changed: $10 the mountains' x, $20 the hills' x, $80 the scroll
	tst.b	(a5)
	beq.s	.full
	cmp.b	1(a5),d0
	bne.s	.full
	move.b	io_regs+3,d1
	cmp.b	3(a5),d1
	bne.s	.full
	move.b	io_regs+5,d1
	cmp.b	5(a5),d1
	bne.s	.full
	move.b	io_regs+2,d1
	cmp.b	2(a5),d1
	beq.s	.h0
	moveq	#$20,d3
.h0:	move.b	io_regs+4,d1
	cmp.b	4(a5),d1
	beq.s	.m0
	or.b	#$10,d3
.m0:	move.b	io_regs,d1
	cmp.b	6(a5),d1
	beq.s	.keep
	or.b	#$80,d3
	bra.s	.keep
.full:	ifd SIM
	addq.l	#1,cnt_full
	endc
	move.l	a6,a0			; (another scene, or the buffer's first picture: every line, every group)
	move.w	#PF_NL-1,d1
.fd:	move.w	#$7FFF,(a0)+
	dbf	d1,.fd
	move.w	#$B0,d3
.keep:	move.b	d3,pd_chg
	st	(a5)+
	move.b	d0,(a5)+
	move.b	io_regs+2,(a5)+
	move.b	io_regs+3,(a5)+
	move.b	io_regs+4,(a5)+
	move.b	io_regs+5,(a5)+
	move.b	io_regs,(a5)+
	move.b	io_regs+4,d0		; the backgrounds' and the ground's window
	bsr	bg_xpos
	move.w	d0,m_g8
	move.b	d2,m_skew
	move.b	io_regs+2,d0
	bsr	bg_xpos
	move.w	d0,bg_g8
	move.w	d1,bg_shift
	move.b	d2,bg_skew
	move.w	pd_hk,d0
	lsl.w	#2,d0
	move.w	d0,bg_img4
	beq.s	.nh
	lea	bg_rowtab-4,a0		; (bg_row_list's tables at this shift)
	move.l	(a0,d0.w),brl_rowtab
	lea	bg_masks-4,a0
	move.l	(a0,d0.w),d1
	move.w	bg_shift,d2
	lsl.w	#6,d2
	add.l	d2,d1
	move.l	d1,brl_masks
	lea	bg_pindex-4,a0
	move.l	(a0,d0.w),d1
	move.w	bg_shift,d2
	lsl.w	#2,d2
	add.l	d2,d1
	move.l	d1,brl_pidx
	lea	bg_plist-4,a0
	move.l	(a0,d0.w),brl_plist
	lea	bg_images,a0
	move.l	(a0,d0.w),brl_img
	move.l	draw_buf,d1
	add.l	#PF_X,d1
	moveq	#0,d2
	move.w	bg_g8,d2
	sub.l	d2,d1
	move.l	d1,brl_dst0
	lsr.w	#3,d2
	move.w	d2,brl_g
.nh:
	moveq	#8,d0			; the ground: tilemap x u = (8 - scroll) mod 256
	sub.b	io_regs,d0
	and.w	#$FF,d0
	move.w	d0,d1
	lsr.w	#4,d1
	lsl.w	#3,d1
	move.w	d1,tx_g8
	and.w	#15,d0
	move.w	d0,tx_s
	moveq	#0,d2
	tst.w	d0
	beq.s	.tk
	moveq	#16,d2
	sub.w	d0,d2
	or.w	#$80,d2
.tk:	move.b	d2,tx_skew
	moveq	#0,d0			; the rows' first lines
	move.b	io_regs+5,d0
	subq.w	#6,d0
	move.w	d0,pd_mline
	moveq	#0,d0
	move.b	io_regs+3,d0
	subq.w	#6,d0
	move.w	d0,pd_hline
	lea	seg_b,a0		; the segments' boundaries
	move.w	#PF_TOP,(a0)+
	move.w	#GR_TOP,(a0)+
	move.w	#BG_BOT,(a0)+
	moveq	#3,d7
	tst.b	d6
	beq.s	.b1
	move.w	pd_mline,d0
	bsr	.addb
	add.w	#64,d0
	bsr	.addb
.b1:	move.w	pd_hk,d1
	beq.s	.b2
	move.w	pd_hline,d0
	bsr	.addb
	add.w	d1,d1
	lea	hoptab,a1
	add.w	(a1,d1.w),d0		; (the first of the rows that are all opaque)
	bsr	.addb
	move.w	pd_hline,d0
	add.w	#64,d0
	bsr	.addb
.b2:	move.w	d7,d4			; (sorted)
	subq.w	#2,d4
.so:	move.w	d7,d3
	subq.w	#2,d3
	lea	seg_b,a1
.si:	move.w	(a1)+,d0
	cmp.w	(a1),d0
	ble.s	.ok
	move.w	(a1),-2(a1)
	move.w	d0,(a1)
.ok:	dbf	d3,.si
	dbf	d4,.so
	lea	mtab+256,a0		; (the classes of the rows by row + 256: mtab 0 none, 1 a row, 2 the fill)
	tst.b	d6
	bne.s	.mt
	lea	ztab+256,a0
.mt:	lea	ztab+256,a1		; (htab: 0 none, 3 an opaque row, 6 a row with transparent pixels, 9 the fill)
	move.w	pd_hk,d0
	beq.s	.ht
	lea	htab1+256,a1
	subq.w	#1,d0
	beq.s	.ht
	lea	htab2+256,a1
.ht:	lea	kindtab,a3
	lea	seg_b,a2
	subq.w	#2,d7
.seg:	move.w	(a2)+,d1		; a segment: lines d1 .. d2 - 1
	move.w	(a2),d2
	cmp.w	d1,d2
	ble.s	.sn
	moveq	#0,d0
	move.w	d1,d4
	sub.w	pd_hline,d4
	move.b	(a1,d4.w),d0
	move.w	d1,d4
	sub.w	pd_mline,d4
	add.b	(a0,d4.w),d0
	move.b	(a3,d0.w),d0
	cmp.w	#GR_TOP,d1
	bhs.s	.sg
	bsr	seg_fixed
	bra.s	.sn
.sg:	bsr	seg_ground
.sn:	dbf	d7,.seg
	move.l	pd_dirty,a6		; lines 250-251: slot 0 where changed
	lea	(BG_BOT-PF_TOP)*2(a6),a6
	move.w	#BG_BOT,d1
	moveq	#1,d3
.lb:	move.w	(a6),d0
	beq.s	.bk
	bsr	set_range
	moveq	#0,d0
	bsr	draw_run
	clr.w	(a6)
.bk:	addq.w	#2,a6
	addq.w	#1,d1
	cmp.w	#PF_BOT,d1
	blo.s	.lb
	movem.l	(sp)+,d0-d7/a0-a6
	rts
.addb:	move.w	d0,d2			; d0 within [PF_TOP, BG_BOT] appended (d0 kept)
	cmp.w	#PF_TOP,d2
	bge.s	.a1
	move.w	#PF_TOP,d2
.a1:	cmp.w	#BG_BOT,d2
	ble.s	.a2
	move.w	#BG_BOT,d2
.a2:	move.w	d2,(a0)+
	addq.w	#1,d7
	rts

; the kinds by (the hills' / city's class * 3 + the mountains' class): the kind, bit 3 the hills' pieces over the
; mountains, bit 4 it shows the mountains' x, bit 5 the hills' x
kindtab:
	dc.b	0,3+$10,1		; nothing in front: slot 0, the mountains' row, their fill
	dc.b	4+$20,4+$20,4+$20	; an opaque row
	dc.b	4+$20,3+$08+$30,5+$20	; a row with transparent pixels: over nothing, the mountains' row, their fill
	dc.b	2,2,2			; the fill
	even


; set_range: d0.w = a line's changed groups (bit g: group g) -> the range drawn: rg_g0 (the first), rg_n (to the
; last), rg_bits (the groups between).  Keeps all.
set_range:
	movem.l	d0-d2,-(sp)
	moveq	#0,d1
.lo:	btst	d1,d0
	bne.s	.l1
	addq.w	#1,d1
	bra.s	.lo
.l1:	moveq	#14,d2
.hi:	btst	d2,d0
	bne.s	.h1
	subq.w	#1,d2
	bra.s	.hi
.h1:	move.w	d1,rg_g0
	sub.w	d1,d2
	addq.w	#1,d2
	move.w	d2,rg_n
	moveq	#0,d0			; ((1 << n) - 1) << g0
	bset	d2,d0
	subq.w	#1,d0
	lsl.w	d1,d0
	move.w	d0,rg_bits
	movem.l	(sp)+,d0-d2
	rts
set_whole:
	clr.w	rg_g0
	move.w	#15,rg_n
	move.w	#$7FFF,rg_bits
	rts

; seg_fixed: the segment d1 .. d2 - 1 above the ground, kind byte d0.  Keeps all.
seg_fixed:
	movem.l	d0-d7/a0-a6,-(sp)
	move.b	d0,d5
	move.l	pd_dirty,a6
	move.w	d1,d4
	sub.w	#PF_TOP,d4
	lea	tx_nz,a4		; (the lines' text groups)
	add.w	d4,d4
	add.w	d4,a6
	add.w	d4,d4
	add.w	d4,a4
	move.b	d5,d4
	and.b	pd_chg,d4
	beq.s	.dirty
	bsr	set_whole		; its background moved: the whole segment
	move.w	d2,d3
	sub.w	d1,d3
	ifd SIM
	add.l	d3,cnt_lw
	endc
	move.b	d5,d0
	bsr	draw_run
.wl:	clr.w	(a6)+
	btst	#3,d5
	beq.s	.w1
	bsr	bg_row_list
.w1:	tst.l	(a4)+
	beq.s	.w2
	bsr	ovl_text
.w2:	addq.w	#1,d1
	cmp.w	d2,d1
	blo.s	.wl
	movem.l	(sp)+,d0-d7/a0-a6
	rts
.dirty:	move.w	d1,d4			; only where it changed: runs of lines with the same groups
.dl:	cmp.w	d2,d4
	bhs.s	.out
	move.w	(a6),d0
	beq.s	.cl
	lea	2(a6),a5
	move.w	d4,d7
.de:	addq.w	#1,d7
	cmp.w	d2,d7
	bhs.s	.dr
	cmp.w	(a5)+,d0
	beq.s	.de
.dr:	bsr	set_range		; lines d4 .. d7 - 1
	move.w	d7,d3
	sub.w	d4,d3
	ifd SIM
	add.l	d3,cnt_ld
	addq.l	#1,cnt_rd
	endc
	move.w	d4,d1
	move.b	d5,d0
	bsr	draw_run
.dw:	clr.w	(a6)+
	btst	#3,d5
	beq.s	.d1
	bsr	bg_row_list
.d1:	tst.l	(a4)+
	beq.s	.d2
	bsr	ovl_text
.d2:	addq.w	#1,d1
	cmp.w	d7,d1
	blo.s	.dw
	move.w	d7,d4
	bra.s	.dl
.cl:	addq.w	#1,d4
	addq.w	#2,a6
	addq.w	#4,a4
	bra.s	.dl
.out:	movem.l	(sp)+,d0-d7/a0-a6
	rts

; seg_ground: the segment d1 .. d2 - 1 on the ground's rows, kind byte d0: line by line (a line with text shows the
; scroll, a full one only the text; over the hills' / city's fill the ground's version with the fill in its holes),
; runs of lines of one kind.  Keeps all.
seg_ground:
	movem.l	d0-d7/a0-a6,-(sp)
	move.b	d0,d5
	and.b	#7,d0
	cmp.b	#2,d0
	bne.s	.nf
	move.b	#6+$80,d5		; (over the fill: the filled version, every line at the scroll)
.nf:	move.l	pd_dirty,a6
	move.w	d1,d0
	sub.w	#PF_TOP,d0
	add.w	d0,d0
	add.w	d0,a6
	lea	gr_cnt-2*GR_TOP,a3
	add.w	d1,a3
	add.w	d1,a3
	lea	lovl-PF_TOP,a4
	add.w	d1,a4
	bsr	set_whole
	move.b	pd_chg,d6
	moveq	#-1,d7			; the run's kind (-1: none), its first line run_l
	move.w	d1,d4
.l:	cmp.w	d2,d4
	bhs.s	.end
	move.b	d5,d3
	move.w	(a3)+,d0
	beq.s	.c
	tst.b	d3
	bmi.s	.c
	or.b	#$C0,d3			; (text: the scroll, its pieces)
	cmp.w	#256,d0
	bne.s	.c
	move.b	#$87,d3			; (the text covers it)
.c:	move.b	d3,d0
	and.b	d6,d0
	bne.s	.need
	tst.w	(a6)
	bne.s	.need
	bsr.s	.flush
	addq.w	#2,a6
	addq.w	#1,a4
	addq.w	#1,d4
	bra.s	.l
.need:	clr.w	(a6)+
	move.b	d3,(a4)+
	and.w	#7,d3
	cmp.w	d7,d3
	beq.s	.ext
	bsr.s	.flush
	move.w	d3,d7
	move.w	d4,run_l
.ext:	addq.w	#1,d4
	bra.s	.l
.end:	bsr.s	.flush
	movem.l	(sp)+,d0-d7/a0-a6
	rts
.flush:	tst.w	d7			; the run d7 from run_l to d4 - 1, then its lines' overlays
	bmi.s	.fx
	movem.l	d0-d3/d6/a0,-(sp)
	move.w	d7,d0
	move.w	run_l,d1
	move.w	d4,d3
	sub.w	d1,d3
	ifd SIM
	add.l	d3,cnt_lg
	endc
	bsr	draw_run
	lea	lovl-PF_TOP,a0
	add.w	d1,a0
	move.w	d1,d6
	sub.w	#PF_TOP,d6
.fo:	move.b	(a0)+,d0
	btst	#3,d0
	beq.s	.f1
	bsr	bg_row_list
.f1:	btst	#6,d0
	beq.s	.f2
	bsr	ovl_text
.f2:	addq.w	#1,d1
	addq.w	#1,d6
	cmp.w	d4,d1
	blo.s	.fo
	movem.l	(sp)+,d0-d3/d6/a0
	moveq	#-1,d7
.fx:	rts

; draw_run: d0 = the kind (bits 0-2), d1 = the first line, d3 = the lines, in the range (rg_g0, rg_n).  Keeps all.
draw_run:
	movem.l	d0/a0,-(sp)
	and.w	#7,d0
	add.w	d0,d0
	move.w	.rt(pc,d0.w),d0
	jsr	.rt(pc,d0.w)
	movem.l	(sp)+,d0/a0
	rts
.rt:	dc.w	run_clear-.rt,run_mfill-.rt,run_hfill-.rt,run_mnt-.rt,run_hop-.rt,run_hopf-.rt,run_tgf-.rt,run_tgr-.rt

; bg_xpos: d0.b = a background's x -> d0 = the first source group * 8, d1 = the shift, d2 = the skew byte (FXSR + 16 -
; the shift, or 0).  Picture x 0 shows its pixel u = (12 - x) mod 256.
bg_xpos:
	moveq	#12,d1
	sub.b	d0,d1
	and.w	#$FF,d1
	move.w	d1,d0
	lsr.w	#4,d0
	lsl.w	#3,d0
	and.w	#15,d1
	moveq	#0,d2
	tst.w	d1
	beq.s	.o
	moveq	#16,d2
	sub.w	d1,d2
	or.w	#$80,d2
.o:	rts

; line_addr: d1 = a picture line -> a1 = its first shown word (plane 0) in draw_buf
line_addr:
	move.l	draw_buf,a1
	move.w	d1,-(sp)
	mulu	#PF_LB,d1
	add.l	d1,a1
	move.w	(sp)+,d1
	lea	PF_X(a1),a1
	rts

; The runs (d1 = the first line, d3 = the lines; keep all registers but d0)
run_clear:
	moveq	#0,d0
	bra.s	fill_run
run_mfill:
	moveq	#0,d0
	move.b	mp_bgfill,d0
	bra.s	fill_run
run_hfill:
	move.l	a0,-(sp)
	lea	mp_bgfill,a0
	move.w	pd_hk,d0
	move.b	(a0,d0.w),d0
	move.l	(sp)+,a0
fill_run:
	movem.l	d4-d5,-(sp)
	moveq	#0,d4
	moveq	#3,d5
	bsr.s	fill_planes
	movem.l	(sp)+,d4-d5
	rts

; fill_planes: planes d4 .. d5 of lines d1 .. d1 + d3 - 1 in the range (rg_g0, rg_n) with slot d0's bits (a pass
; a plane, ones or zeros: at most 15 writes a line, 4 lines a start).  Keeps all.
fill_planes:
	movem.l	d0-d6/a1,-(sp)
	bsr	line_addr
	move.w	rg_g0,d2
	lsl.w	#3,d2
	add.w	d2,a1
	moveq	#-1,d2
	move.w	d2,B_END1.w
	move.w	d2,B_END2.w
	move.w	d2,B_END3.w
	move.w	#8,B_DXI.w
	move.w	rg_n,d2
	move.w	d2,B_XC.w
	subq.w	#1,d2
	lsl.w	#3,d2
	neg.w	d2
	add.w	#PF_LB,d2
	move.w	d2,B_DYI.w
	clr.b	B_HOP.w
	clr.b	B_SKEW.w
	lsr.b	d4,d0			; (the first plane's bit)
	move.w	d4,d2
	add.w	d2,d2
	add.w	d2,a1
.pl:	move.l	a1,B_DST.w
	move.b	#15,B_OP.w		; (ones)
	lsr.b	#1,d0
	bcs.s	.one
	clr.b	B_OP.w			; (zeros)
.one:	move.w	d3,d6
.pc:	moveq	#4,d2
	cmp.w	d2,d6
	bge.s	.p4
	move.w	d6,d2
.p4:	move.w	d2,B_YC.w
	move.b	#$C0,$ffff8a3c.w	; (start: HOG, 60 writes)
	sub.w	d2,d6
	bgt.s	.pc
	addq.w	#2,a1
	addq.w	#1,d4
	cmp.w	d5,d4
	bls.s	.pl
	movem.l	(sp)+,d0-d6/a1
	rts

; cp_planes: planes d4 .. d5 of d3 lines copied in the range (rg_g0, rg_n): the source a0 (the first line's plane 0
; at word 0: with the pre-read its word before the shift), d6 its bytes a line, d2.b the skew byte (bit 7 FXSR); the
; destination a1 (the first line's plane 0, word 0).  At most 15 writes and 16 reads a line: 2 lines a start.  Keeps
; all.
cp_planes:
	movem.l	d0-d7/a0-a1,-(sp)
	move.w	rg_g0,d0
	lsl.w	#3,d0
	add.w	d0,a0
	add.w	d0,a1
	moveq	#-1,d0
	move.w	d0,B_END1.w
	move.w	d0,B_END2.w
	move.w	d0,B_END3.w
	move.w	#8,B_SXI.w
	move.w	#8,B_DXI.w
	move.w	rg_n,d7
	move.w	d7,B_XC.w
	subq.w	#1,d7
	lsl.w	#3,d7			; (the line's words - 1) * 8
	move.w	d6,d0
	sub.w	d7,d0
	tst.b	d2
	bpl.s	.y
	subq.w	#8,d0
.y:	move.w	d0,B_SYI.w
	move.w	#PF_LB,d0
	sub.w	d7,d0
	move.w	d0,B_DYI.w
	move.b	#2,B_HOP.w
	move.b	#3,B_OP.w
	move.b	d2,B_SKEW.w
	move.w	d4,d0
	add.w	d0,d0
	add.w	d0,a0
	add.w	d0,a1
.pl:	move.l	a0,B_SRC.w
	move.l	a1,B_DST.w
	move.w	d3,d7
.pc:	moveq	#2,d0
	cmp.w	d0,d7
	bge.s	.p2
	move.w	d7,d0
.p2:	move.w	d0,B_YC.w
	move.b	#$C0,$ffff8a3c.w	; (start: HOG, at most 62 accesses)
	sub.w	d0,d7
	bgt.s	.pc
	addq.w	#2,a0
	addq.w	#2,a1
	addq.w	#1,d4
	cmp.w	d5,d4
	bls.s	.pl
	movem.l	(sp)+,d0-d7/a0-a1
	rts

run_mnt:				; the mountains' rows: planes 0-1 copied, 2-3 cleared
	movem.l	d1-d6/a0-a1,-(sp)
	move.w	d1,d0
	sub.w	pd_mline,d0		; the row
	lsl.w	#8,d0
	lea	mp_bg0,a0
	add.w	d0,a0
	add.w	m_g8,a0
	bsr	line_addr
	move.w	#256,d6
	move.b	m_skew,d2
	moveq	#0,d4
	moveq	#1,d5
	bsr	cp_planes
	moveq	#0,d0
	moveq	#2,d4
	moveq	#3,d5
	bsr	fill_planes
	movem.l	(sp)+,d1-d6/a0-a1
	rts

run_hopf:				; the hills' / city's rows over the mountains' fill
	movem.l	d1-d6/a0-a1,-(sp)
	lea	bg_fillimg-4,a0
	bra.s	run_h
run_hop:				; the hills' / city's rows (their holes slot 0)
	movem.l	d1-d6/a0-a1,-(sp)
	lea	bg_images,a0
run_h:	move.w	bg_img4,d0
	move.l	(a0,d0.w),a0
	move.w	d1,d0
	sub.w	pd_hline,d0		; the row
	lsl.w	#8,d0
	add.w	d0,a0
	add.w	bg_g8,a0
	bsr	line_addr
	move.w	#256,d6
	move.b	bg_skew,d2
	moveq	#0,d4
	moveq	#2,d5
	bsr	cp_planes
	moveq	#0,d0
	moveq	#3,d4
	moveq	#3,d5
	bsr	fill_planes
	movem.l	(sp)+,d1-d6/a0-a1
	rts

run_tst:				; full text lines of the fixed rows (no shift)
	movem.l	d1-d6/a0-a1,-(sp)
	move.w	d1,d0
	sub.w	#PF_TOP,d0
	mulu	#ST_LB,d0
	lea	st_img,a0
	add.l	d0,a0
	moveq	#ST_LB,d6
	moveq	#0,d2
	bra.s	run_t
run_tgf:				; ground lines over the hills' / city's fill: the filled version at the scroll
	movem.l	d1-d6/a0-a1,-(sp)
	lea	gr_imgf,a0
	bra.s	run_tg
run_tgr:				; full ground lines at the scroll
	movem.l	d1-d6/a0-a1,-(sp)
	lea	gr_img,a0
run_tg:	move.w	d1,d0
	sub.w	#186,d0
	lsl.w	#8,d0			; (GR_LB = 256)
	add.w	d0,a0
	add.w	tx_g8,a0
	move.w	#GR_LB,d6
	move.b	tx_skew,d2
run_t:	bsr	line_addr
	moveq	#0,d4
	moveq	#3,d5
	bsr	cp_planes
	movem.l	(sp)+,d1-d6/a0-a1
	rts

; ovl_text: the text's pieces on line d1 (a line with transparent pixels): the fixed rows' unshifted, the
; ground's at its scroll (window group g, shift s).  The line's group bits (tx_nz, tx_opq) give the shown words that
; have pixels (group g + w, and g + w + 1 when s > 0) and those without a transparent pixel; a pass covers a run of
; full words with a partial word before and after it (their masks END1 / END3: (M[g + w] << s) | (M[g + w + 1] >>
; (16 - s)), the high word of the long at M[g + w] shifted left by s), 4 planes (HOP 2 / OP 3).  Keeps all.
ovl_text:
	movem.l	d0-d7/a0-a3,-(sp)
	move.w	d1,d6
	sub.w	#PF_TOP,d6
	bsr	line_addr
	move.w	d6,d0
	lsl.w	#2,d0
	lea	tx_nz,a2
	move.l	(a2,d0.w),d2
	lea	tx_opq,a2
	move.l	(a2,d0.w),d3
	cmp.w	#GR_I,d6
	bhs.s	.g
	move.w	d6,d0			; a fixed line: g = 0, s = 0
	mulu	#ST_LB,d0
	lea	st_img,a0
	add.l	d0,a0
	move.w	d6,d0
	mulu	#30,d0
	lea	st_mask,a3
	add.l	d0,a3
	moveq	#0,d5
	moveq	#0,d7
	bra.s	.go
.g:	sub.w	#GR_I,d6		; the ground
	move.w	d6,d0
	lsl.w	#8,d0
	lea	gr_img,a0
	add.w	d0,a0
	move.w	tx_g8,d1
	add.w	d1,a0
	lsr.w	#3,d1			; g
	lsl.w	#6,d6			; (64 mask bytes a line)
	lea	gr_mask,a3
	add.w	d6,a3
	add.w	d1,a3
	add.w	d1,a3
	lsr.l	d1,d2
	lsr.l	d1,d3
	move.w	tx_s,d5
	beq.s	.s0
	move.l	d2,d0			; (s > 0: two groups a word)
	lsr.l	#1,d0
	or.l	d0,d2
	move.l	d3,d0
	lsr.l	#1,d0
	and.l	d0,d3
.s0:	moveq	#0,d7
	move.b	tx_skew,d7
.go:	and.w	rg_bits,d2		; d2: the words with pixels (in the range), d3: the full ones (bit w)
	beq	.out
	and.w	d2,d3
	move.w	#8,B_SXI.w
	move.w	#8,B_DXI.w
	move.b	#2,B_HOP.w
	move.b	#3,B_OP.w
	move.w	#-1,B_END2.w
	move.b	d7,B_SKEW.w
	add.b	d7,d7			; (X: the pre-read)
	scs	d7
	and.w	#8,d7			; (8: a source word more a line)
	moveq	#0,d4			; w
.w:	tst.w	d2
	beq	.out
.z:	lsr.w	#1,d2
	bcs.s	.ne
	lsr.w	#1,d3
	addq.w	#1,d4
	bra.s	.z
.ne:	move.w	d4,d6			; the pass's first word
	addq.w	#1,d4
	lsr.w	#1,d3
	bcs.s	.f1
	move.w	d6,d0			; a partial first word
	bsr	.mask
	beq.s	.w			; (no pixel shown there)
	move.w	d0,B_END1.w
	bra.s	.ext
.f1:	move.w	#-1,B_END1.w
.ext:	moveq	#-1,d1			; (END3)
.e1:	btst	#0,d3			; full words after it
	beq.s	.e2
	lsr.w	#1,d2
	lsr.w	#1,d3
	addq.w	#1,d4
	bra.s	.e1
.e2:	btst	#0,d2			; a partial word after it
	beq.s	.pass
	move.w	d4,d0
	bsr	.mask
	beq.s	.pass
	move.w	d0,d1
	lsr.w	#1,d2
	lsr.w	#1,d3
	addq.w	#1,d4
.pass:	move.w	d1,B_END3.w		; words d6 .. d4 - 1
	move.w	d4,d1
	sub.w	d6,d1			; c
	lsl.w	#3,d6
	lea	(a0,d6.w),a2
	move.l	a2,B_SRC.w
	lea	(a1,d6.w),a2
	move.l	a2,B_DST.w
	move.w	d1,B_XC.w
	move.w	d1,d0			; the destination: c writes, then the next plane
	subq.w	#1,d0
	lsl.w	#3,d0
	neg.w	d0
	addq.w	#2,d0
	move.w	d0,B_DYI.w
	sub.w	d7,d0			; the source: c reads (+ the pre-read)
	move.w	d0,B_SYI.w
	cmp.w	#6,d1			; (HOG, at most 64 bus accesses: a plane writes c words, reads c + 1 and the
	bhi.s	.p2			; partial ends' destination: 4 planes a start up to 6 words, 2 up to 14, else 1)
	move.w	#4,B_YC.w
	move.b	#$C0,$ffff8a3c.w
	bra	.w
.p2:	moveq	#1,d0
	cmp.w	#14,d1
	bhi.s	.p3
.p4:	move.w	#2,B_YC.w
	move.b	#$C0,$ffff8a3c.w
	dbf	d0,.p4
	bra	.w
.p3:	moveq	#3,d0
.p5:	move.w	#1,B_YC.w
	move.b	#$C0,$ffff8a3c.w
	dbf	d0,.p5
	bra	.w
.out:	movem.l	(sp)+,d0-d7/a0-a3
	rts
.mask:	add.w	d0,d0			; word d0's mask -> d0.w (flags: tst.w)
	move.l	(a3,d0.w),d0
	lsl.l	d5,d0
	swap	d0
	tst.w	d0
	rts

; spr_damage: the groups the sprites of this picture were drawn on changed in the drawn buffer's lines
spr_damage:
	move.l	pd_dirty,a0
	lea	spr_list,a1
	move.w	spr_count,d7
	bra.s	.nx
.s:	move.w	8(a1),d0		; the sprite's picture line, screen x
	move.w	10(a1),d2
	lea	12(a1),a1
	sub.w	#PF_X*2,d2		; its groups (picture x >> 4, and the next), within 0-14
	moveq	#0,d3
	move.w	d2,d4
	asr.w	#4,d2
	bmi.s	.g0
	bset	d2,d3
.g0:	add.w	#15,d4
	asr.w	#4,d4
	cmp.w	#14,d4
	bgt.s	.g1
	bset	d4,d3
.g1:	move.w	d0,d1
	sub.w	#PF_TOP,d0
	bpl.s	.a
	moveq	#0,d0
.a:	add.w	#16-PF_TOP,d1
	cmp.w	#PF_NL,d1
	ble.s	.b
	move.w	#PF_NL,d1
.b:	sub.w	d0,d1
	ble.s	.nx
	add.w	d0,d0
	lea	(a0,d0.w),a2
	subq.w	#1,d1
.m:	or.w	d3,(a2)+
	dbf	d1,.m
.nx:	dbf	d7,.s
	rts

; pd_init: the row classes (mtab, htab1 / htab2 from the masked rows' table; ztab none), every buffer to be drawn
pd_init:
	lea	ztab,a0
	move.w	#512-1,d0
.z:	clr.b	(a0)+
	dbf	d0,.z
	lea	mtab,a0			; rows < 0: none, 0-63, 64 on: the fill
	lea	htab1,a1
	lea	htab2,a2
	lea	mp_bgr1,a3
	lea	mp_bgr2,a4
	move.w	#-256,d0
.t:	moveq	#0,d1
	moveq	#0,d2
	moveq	#0,d3
	tst.w	d0
	bmi.s	.w
	moveq	#2,d1
	moveq	#9,d2
	moveq	#9,d3
	cmp.w	#64,d0
	bge.s	.w
	moveq	#1,d1
	move.w	d0,d4
	add.w	d4,d4
	moveq	#3,d2
	tst.w	(a3,d4.w)
	beq.s	.t1
	moveq	#6,d2
.t1:	moveq	#3,d3
	tst.w	(a4,d4.w)
	beq.s	.w
	moveq	#6,d3
.w:	move.b	d1,(a0)+
	move.b	d2,(a1)+
	move.b	d3,(a2)+
	addq.w	#1,d0
	cmp.w	#256,d0
	blt.s	.t
	lea	bstate,a0
	moveq	#NBUF*8/2-1,d0
.b:	clr.w	(a0)+
	dbf	d0,.b
	lea	hoptab+2,a0		; the hills' / city's first row of those without transparent pixels to the end
	lea	mp_bgr1+128,a1
	bsr.s	.hop
	lea	mp_bgr2+128,a1
.hop:	moveq	#64,d0
.h:	tst.w	-(a1)
	bne.s	.h1
	subq.w	#1,d0
	bne.s	.h
.h1:	move.w	d0,(a0)+
	rts


; bg_row_list: line d1's row of the hills or the city (bg_img4; row 0 at pd_hline) over the mountains: its passes
; (mp_bgp: runs of opaque words with a partial word at either end, their registers prepared: END1 / END3, the Y
; increments) in the range's words of the window from group g (a run across the range's ends clipped: its end words'
; masks from the mask table at the shift, 32 words a shift), planes 0-2, HOP 2 / OP 3.  Keeps all.
bg_row_list:
	movem.l	d0-d7/a0-a4,-(sp)
	move.w	d1,d3			; the line
	sub.w	pd_hline,d1		; the row
	move.l	brl_rowtab,a0
	move.w	d1,d2
	add.w	d2,d2
	move.w	(a0,d2.w),d2		; the row's block + 1
	subq.w	#1,d2
	move.l	brl_masks,a2		; the masks of the doubled row's 32 words at this shift (1 KB a block)
	moveq	#0,d0
	move.w	d2,d0
	lsl.l	#8,d0
	lsl.l	#2,d0
	add.l	d0,a2
	move.l	brl_pidx,a3		; its list (16 shifts a block)
	lsl.w	#6,d2
	move.l	(a3,d2.w),d2
	move.l	brl_plist,a3
	add.l	d2,a3
	move.l	brl_img,a0		; the source row (word w at 8 w)
	lsl.w	#8,d1
	add.w	d1,a0
	move.l	brl_dst0,a1		; the destination line (word w at 8 (w - g))
	lsl.w	#5,d3
	add.w	d3,a1
	lsl.w	#2,d3
	add.w	d3,a1
	move.w	brl_g,d6
	add.w	rg_g0,d6		; the range's words g + g0 ..
	move.w	rg_n,d7
	add.w	d6,d7			; .. g + g0 + n
	move.w	#8,B_SXI.w
	move.w	#8,B_DXI.w
	move.b	#2,B_HOP.w
	move.b	#3,B_OP.w
	move.w	#-1,B_END2.w
	move.b	bg_skew,B_SKEW.w
	moveq	#0,d5			; (8 with the pre-read)
	tst.b	bg_skew
	beq.s	.p
	moveq	#8,d5
.p:	moveq	#0,d0
	move.b	(a3)+,d0		; the first word
	bmi	.done
	moveq	#0,d1
	move.b	(a3)+,d1		; the end
	cmp.w	d6,d1
	ble.s	.sk			; (before the range)
	cmp.w	d7,d0
	bge	.done			; (after it: the list is in order)
	cmp.w	d6,d0
	blt.s	.clip
	cmp.w	d7,d1
	bgt.s	.clip
	sub.w	d0,d1			; (in the range: as prepared)
	lsl.w	#3,d0
	lea	(a0,d0.w),a4
	move.l	a4,B_SRC.w
	lea	(a1,d0.w),a4
	move.l	a4,B_DST.w
	move.w	d1,B_XC.w
	move.w	(a3)+,B_END1.w
	move.w	(a3)+,B_END3.w
	move.w	(a3)+,B_SYI.w
	move.w	(a3)+,B_DYI.w
	bra.s	.go
.sk:	addq.w	#8,a3
	bra.s	.p
.clip:	addq.w	#8,a3			; (across an end of the range: clipped)
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
	lsl.w	#3,d0
	lea	(a0,d0.w),a4
	move.l	a4,B_SRC.w
	lea	(a1,d0.w),a4
	move.l	a4,B_DST.w
	move.w	d1,B_XC.w
	move.w	d1,d2			; the destination: d1 writes, then the next plane; the source: the pre-read too
	subq.w	#1,d2
	lsl.w	#3,d2
	neg.w	d2
	addq.w	#2,d2
	move.w	d2,B_DYI.w
	sub.w	d5,d2
	move.w	d2,B_SYI.w
.go:	cmp.w	#9,d1			; (start: HOG, at most 64 bus accesses: a plane writes d1 words, reads d1 + 1 and
	bhi.s	.sp			; the ends' destination: 3 planes a start up to 9 words, 2 + 1 up to 14, else 1)
	move.w	#3,B_YC.w
	move.b	#$C0,$ffff8a3c.w
	bra	.p
.sp:	cmp.w	#14,d1
	bhi.s	.s1
	move.w	#2,B_YC.w
	move.b	#$C0,$ffff8a3c.w
	move.w	#1,B_YC.w
	move.b	#$C0,$ffff8a3c.w
	bra	.p
.s1:	moveq	#2,d2
.s2:	move.w	#1,B_YC.w
	move.b	#$C0,$ffff8a3c.w
	dbf	d2,.s2
	bra	.p
.done:	movem.l	(sp)+,d0-d7/a0-a4
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
	lea	slot_long,a4		; the four values' planes as bytes $FF / 0 (hc_s0-3)
	moveq	#0,d1
	move.b	(a1)+,d1
	lsl.w	#2,d1
	move.l	(a4,d1.w),hc_s
	moveq	#0,d1
	move.b	(a1)+,d1
	lsl.w	#2,d1
	move.l	(a4,d1.w),hc_s+4
	moveq	#0,d1
	move.b	(a1)+,d1
	lsl.w	#2,d1
	move.l	(a4,d1.w),hc_s+8
	moveq	#0,d1
	move.b	(a1)+,d1
	lsl.w	#2,d1
	move.l	(a4,d1.w),hc_s+12
	lea	rep4,a1
	moveq	#7,d7
.row:	moveq	#0,d4
	move.b	(a3)+,d4		; the high plane (the pixel value's bit 1)
	moveq	#0,d5
	move.b	(a3)+,d5		; the low plane
	move.w	d4,d0			; pixel 3: high and low
	and.w	d5,d0
	lsl.w	#2,d0
	move.l	(a1,d0.w),d6
	and.l	hc_s+12,d6
	move.w	d5,d0			; pixel 2: high, not low
	not.w	d0
	and.w	d4,d0
	lsl.w	#2,d0
	move.l	(a1,d0.w),d1
	and.l	hc_s+8,d1
	or.l	d1,d6
	move.w	d4,d0			; pixel 1: low, not high
	not.w	d0
	and.w	d5,d0
	lsl.w	#2,d0
	move.l	(a1,d0.w),d1
	and.l	hc_s+4,d1
	or.l	d1,d6
	move.w	d4,d0			; pixel 0: neither
	or.w	d5,d0
	not.b	d0
	and.w	#$FF,d0
	lsl.w	#2,d0
	move.l	(a1,d0.w),d1
	and.l	hc_s,d1
	or.l	d1,d6
	movep.l	d6,0(a2)
	lea	HUD_LB(a2),a2
	dbf	d7,.row
	movem.l	(sp)+,d6-d7/a0-a4
.out:	rts

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
	even
bg_img4:	ds.w	1		; (the hills / the city: the image * 4)
	ifd SIM
cnt_full:	ds.l	1
cnt_lw:		ds.l	1
cnt_ld:		ds.l	1
cnt_rd:		ds.l	1
cnt_lg:		ds.l	1
	endc
pd_hk:		ds.w	1		; (pf_draw: 0 no hills / city, 1 the hills, 2 the city)
pd_mline:	ds.w	1		; (the mountains' / hills' row 0 line)
pd_hline:	ds.w	1
m_g8:		ds.w	1		; (the mountains' first source group * 8)
tx_g8:		ds.w	1		; (the ground's first source group * 8, its shift)
tx_s:		ds.w	1
m_skew:		ds.b	1
tx_skew:	ds.b	1
bstate:		ds.b	NBUF*8		; each buffer's scene as drawn: valid, control, x1, y1, x2, y2, scroll
pf_dirty:	ds.w	NBUF*PF_NL	; each buffer's lines: the groups changed since (bit g: group g)
pd_dirty:	ds.l	1		; (the drawn buffer's)
hoptab:		ds.w	3		; (the hills' / city's first row of the opaque ones)
seg_b:		ds.w	8		; (pf_draw: the segments' boundaries)
brl_rowtab:	ds.l	1		; (bg_row_list: this picture's tables, image, destination, window)
brl_masks:	ds.l	1
brl_pidx:	ds.l	1
brl_plist:	ds.l	1
brl_img:	ds.l	1
brl_dst0:	ds.l	1
brl_g:		ds.w	1
rg_g0:		ds.w	1		; (the range drawn: the first group, the groups, their bits)
rg_n:		ds.w	1
rg_bits:	ds.w	1
run_l:		ds.w	1
pd_chg:		ds.b	1
lovl:		ds.b	PF_NL		; (seg_ground: a line's overlays)
	even
	even
mtab:		ds.b	512		; (the row classes by row + 256)
htab1:		ds.b	512
htab2:		ds.b	512
ztab:		ds.b	512
	even
hud_vram:	ds.b	HUD_ROWS*32	; the panel's text RAM as drawn
hud_cram:	ds.b	HUD_ROWS*32
hc_s:		ds.l	4		; (draw_hud_cell: the values' planes)
hud_full:	ds.b	1
	even
pic_count:	ds.w	1
	section text,code
