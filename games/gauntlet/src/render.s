; Gauntlet's picture on the STE: a hardware-scrolled ring of the playfield torus (the Shifter's address, $ffff8265 for
; the fine scroll), the motion objects by the Blitter, the alphanumerics (the side panel, messages) on top.
;
; The layout: the maze is the arcade's x 8-231 at the STE's 0-223 (14 words), the panel (alphanumerics columns 30-41,
; the arcade's x 240-335) at 224-319; all 240 lines.
;
; The playfield bitmap P (PFB): the 512 x 512 torus in STE planes (32 words x 512 lines), every tile drawn with the
; fixed palette; P' (PFS) the same in the shadow colours (pens $200-$27F: what a motion object's pen 1 shows).  A tile
; is drawn into P / P' when the game changes it inside the visible window (the window's tiles are compared with a
; copy each picture), or when its colours map to other STE colours (lists of the positions per playfield palette).
;
; Two display rings (RING0 / RING1, drawn in turn): 56 word columns x 880 lines, STRIDE bytes a line.  Ring column c
; shows P's column (c - MCOL) & 31, ring line l P's line (l - GUARD) & 511: every ring position shows a fixed place of
; the torus, so the ring needs no redrawing when the window moves, only where it was never filled (each ring keeps a
; valid rectangle that grows with the window) or damaged.  The picture's pixel (x, y) is ring pixel 16 w0 + f + x of
; line T + y: w0 = MCOL + (sx >> 4), f = sx & 15, T = GUARD + sy (sx = (x scroll + 8) & 511, sy = y scroll); the
; display window starts at word w0 (21 words fetched with the fine scroll).  The columns left of w0 (MCOL) and the
; GUARD lines above and below take whole motion objects (hidden: outside the display window, or the palette black).
;
; Damage: each ring lists what was drawn over P (objects, transparent characters, the overlay rectangles); before it
; is drawn again those rectangles are copied back from P (the Blitter, word columns x lines).  The overlay (the
; alphanumerics' opaque characters as rectangles: runs of a character row, equal rows merged; the panel is one) is
; kept when it is the same as the ring has (the same place, the same characters), else drawn again from the
; alphanumerics' image AIMG (the 320 x 240 picture of the alphanumerics in STE planes, drawn per character when one
; changes): a shifted Blitter copy per plane; only its lines that anything else touched when it is kept.
;
; Colours: one fixed palette of 16 (tools/assets.py, docs/palette.json): every pen maps to the nearest colour of its
; IRGB word (irgb_map); a pen whose STE colour changes makes what uses it be drawn again (P's tiles from the lists, the
; characters of its alphanumerics colour, the motion objects' baked images by their set's epoch).
;
; Motion objects (mo_snapshot, mo_draw): drawn whole (the hidden margin left of the window, the guard lines, the panel
; drawn over their right overhang), in MAME's band order (see mo_snapshot); baked on first use per (code, size, flip,
; palette, the palette's colour mapping) into SPR_POOL: a HOG pass a row (Y count 4: the planes, END1-END3 the row's
; opaque mask shifted, the source running on), the shadow rows (pen 1) a pass from P' at the same place.  With the
; panel's characters not all opaque (the title, the high scores) the panel's playfield and objects are composed in
; PBUF and copied in (panel_compose).
;
; Options: -D MO_ORDER=1 the objects' rows sorted by their mask (the reordered source; measured slower, see the
; README), -D NORENDER=1 no pictures (the game alone).
;
; Fixed memory: RING0 $200000, RING1 $260400, PFB $2C0800, PFS $2E0800, AIMG $300800, PF_LISTS $30A000, LUTS
; $31A000, ALUTS $32A000, AL_LISTS $33A000, SPR_POOL $35F800-$3BFFFF, MO_HASH $3C2000-$3C7FFF, PBUF $3E0800-$3EB47F.

STRIDE = 448
RING_COLS = 56
RING_LINES = 880
GUARD = 64
MCOL = 4
RING0 = $200000
RING1 = RING0+STRIDE*RING_LINES
PFB = $2C0800				; P: 512 lines x 256 bytes
PFS = $2E0800				; P': the shadow colours
AIMG = $300800				; the alphanumerics: 240 lines x 160 bytes
PF_LISTS = $30A000			; 8 x 4096 words: the positions of the tiles of each playfield palette
LUTS = $31A000				; 32 x 2 KB: per colour set, a byte of two pixels -> their plane bits (and mirrored)
ALUTS = $32A000				; 64 x 1 KB: per alphanumerics colour, a byte of four 2-bit pixels -> plane nibbles
AL_LISTS = $33A000			; 64 x 1200 words: the character positions of each alphanumerics colour
SPR_POOL = $35F800			; the motion objects' baked images
PBUF = $3E0800				; the panel composed when its characters are not all opaque (120 x 368)
SPR_POOL_END = $3C0000
AL = 160				; AIMG's bytes a line
AL_N = 1200				; (30 rows x 40 characters)

DMG_MAX = 160
OVL_MAX = 64
PEND_MAX = 600
OV_C0 = 0				; an overlay rectangle: characters c0 .. c1 - 1 (0-39), lines y0 .. y1
OV_C1 = 2
OV_Y0 = 4
OV_Y1 = 6
OV_STAMP = 8
OV_DLO = 12				; (the kept one's lines to draw again)
OV_DHI = 14
OV_KEEP = 16
OV_RC0 = 18				; its first and last ring columns
OV_RC1 = 20
OV_SIZE = 24
RS_VC0 = 0				; a ring's state: the valid rectangle (columns, lines; empty when VC1 <= VC0)
RS_VC1 = 2
RS_VL0 = 4
RS_VL1 = 6
RS_W0 = 8				; where it was drawn last
RS_F = 10
RS_T = 12
RS_NDMG = 14
RS_NOVL = 16
RS_NPEND = 18
RS_POVF = 20				; (pending tiles overflowed: the valid rectangle is dropped)
RS_DMG = 24				; col.w, cols.w, line.w, lines.w
RS_OVL = RS_DMG+DMG_MAX*8
RS_PEND = RS_OVL+OVL_MAX*OV_SIZE	; tiles to copy from P (video RAM word index: column * 64 + row)
RS_SIZE = RS_PEND+PEND_MAX*2

BLT_HT = $ffff8a00
BLT_SXI = $ffff8a20
BLT_SYI = $ffff8a22
BLT_SRC = $ffff8a24
BLT_E1 = $ffff8a28
BLT_E2 = $ffff8a2a
BLT_E3 = $ffff8a2c
BLT_DXI = $ffff8a2e
BLT_DYI = $ffff8a30
BLT_DST = $ffff8a32
BLT_XC = $ffff8a36
BLT_YC = $ffff8a38
BLT_HOP = $ffff8a3a
BLT_CTRL = $ffff8a3c
BLT_SKEW = $ffff8a3d

; ---------------------------------------------------------------------------------------------------------------------
init_video:
	lea	palette_data,a0
	lea	shown_pal,a1
	moveq	#8-1,d0
.pal:	move.l	(a0)+,(a1)+
	dbf	d0,.pal
	lea	black_pal,a1
	moveq	#8-1,d0
.bp:	clr.l	(a1)+
	dbf	d0,.bp
	lea	ring_state0,a0
	bsr	ring_reset
	lea	ring_state1,a0
	bsr	ring_reset
	; every pen mapped, every set's tables made; the copies of the video RAM differ from it everywhere
	lea	ARC_PALETTE,a0
	lea	pal_shadow,a1
	move.w	#768/2-1,d0
.ps:	move.l	(a0)+,d1
	not.l	d1
	move.l	d1,(a1)+
	dbf	d0,.ps
	lea	pen_map,a0
	move.w	#768/4-1,d0
.pm:	move.l	#$ffffffff,(a0)+
	dbf	d0,.pm
	lea	ARC_VRAM,a0
	lea	pf_shadow,a1
	move.w	#$2000/4-1,d0
.pf:	move.l	(a0)+,d1
	not.l	d1
	move.l	d1,(a1)+
	dbf	d0,.pf
	lea	ARC_VRAM+$5000,a0
	lea	al_shadow,a1
	move.w	#30*128/4-1,d0
.al:	move.l	(a0)+,d1
	not.l	d1
	move.l	d1,(a1)+
	dbf	d0,.al
	lea	pf_listed,a0
	move.w	#4096/4-1,d0
.pl:	clr.l	(a0)+
	dbf	d0,.pl
	lea	pf_list_n,a0
	moveq	#8-1,d0
.pn:	clr.w	(a0)+
	dbf	d0,.pn
	lea	al_listed,a0
	move.w	#AL_N-1,d0
.ll:	move.b	#$ff,(a0)+
	dbf	d0,.ll
	lea	al_list_n,a0
	moveq	#64-1,d0
.ln:	clr.w	(a0)+
	dbf	d0,.ln
	lea	al_type,a0
	move.w	#AL_N-1,d0
.at:	clr.b	(a0)+
	dbf	d0,.at
	move.w	#30*12,panel_open	; (every panel character is 0: not opaque)
	lea	al_voff,a0		; (a position's word in the alphanumerics: row * 128 + the arcade column * 2)
	moveq	#0,d1
.vr:	moveq	#0,d2
.vk:	move.w	d1,d0
	lsl.w	#7,d0
	move.w	d2,d3
	addq.w	#1,d3
	cmp.w	#28,d2
	blo	.vm
	addq.w	#1,d3
.vm:	add.w	d3,d3
	add.w	d3,d0
	move.w	d0,(a0)+
	addq.w	#1,d2
	cmp.w	#40,d2
	blo	.vk
	addq.w	#1,d1
	cmp.w	#30,d1
	blo	.vr
	lea	row_runs,a0
	move.w	#30*RR_SIZE-1,d0
.rr:	clr.b	(a0)+
	dbf	d0,.rr
	lea	row_t2,a0
	moveq	#30-1,d0
.r2:	clr.b	(a0)+
	dbf	d0,.r2
	lea	row_ver,a0
	moveq	#30-1,d0
.rv:	clr.l	(a0)+
	dbf	d0,.rv
	clr.l	al_counter
	move.w	#1,runs_version
	clr.w	ob_runs_v
	lea	mo_epoch,a0
	moveq	#16-1,d0
.me:	move.b	#1,(a0)+
	dbf	d0,.me
	bsr	mo_flush
	clr.w	map_n
	clr.w	mo_stamp
	lea	mo_stamps,a0
	move.w	#1024/2-1,d0
.ms:	clr.l	(a0)+
	dbf	d0,.ms
	move.w	#-1,last_bank
	clr.w	ring_index
	clr.b	frame_ready
	ifnd SIM
	move.b	#0,$ffff8260.w
	move.b	#2,$ffff820a.w
	move.b	#(STRIDE-160)/2,$ffff820f.w
	clr.b	$ffff8265.w
	move.l	#RING0,d0
	move.l	d0,flip_addr
	lsr.l	#8,d0
	move.b	d0,$ffff8203.w
	lsr.w	#8,d0
	move.b	d0,$ffff8201.w
	clr.b	$ffff820d.w
	endc
	rts

; a0 = a ring's state: nothing valid, nothing drawn
ring_reset:
	clr.w	RS_VC0(a0)
	clr.w	RS_VC1(a0)
	clr.w	RS_VL0(a0)
	clr.w	RS_VL1(a0)
	move.w	#-1,RS_W0(a0)
	move.w	#-1,RS_F(a0)
	move.w	#-1,RS_T(a0)
	clr.w	RS_NDMG(a0)
	clr.w	RS_NOVL(a0)
	clr.w	RS_NPEND(a0)
	clr.w	RS_POVF(a0)
	rts

; the VBL: a finished picture is shown from now on (the address loaded into the video counter too, before the
; display starts)
vbl_video:
	addq.l	#1,rf_vbls
	tst.b	frame_ready
	beq	.done
	clr.b	frame_ready
	ifnd SIM
	move.b	flip_addr+1,$ffff8201.w
	move.b	flip_addr+2,$ffff8203.w
	move.b	flip_addr+3,$ffff820d.w
	move.b	flip_addr+1,$ffff8205.w
	move.b	flip_addr+2,$ffff8207.w
	move.b	flip_addr+3,$ffff8209.w
	move.b	flip_fine,$ffff8265.w
	move.b	#(STRIDE-160)/2,d0
	tst.b	flip_fine
	beq	.width
	subq.b	#4,d0
.width:	move.b	d0,$ffff820f.w
	endc
.done:	rts

; ---------------------------------------------------------------------------------------------------------------------
render_frame:
	ifd NORENDER
	rts
	endc
	ifnd SIM
.wait:	tst.b	frame_ready		; (the ring drawn last must be shown before the other one is drawn again)
	bne	.wait
	endc
	eor.w	#1,ring_index
	lea	ring_state0,a0
	move.l	#RING0,d0
	tst.w	ring_index
	beq	.r0
	lea	ring_state1,a0
	move.l	#RING1,d0
.r0:	move.l	a0,cur_ring
	move.l	d0,work_base
	; what the picture is of: the scroll and the motion objects, between two VBLs (the game changes them only in its
	; frame, which runs from the VBL): taken again when a VBL came meanwhile (twice at most; the VBL is not held
	; back: its border timers start from it)
	move.w	#3-1,snap_tries
.snap:	move.l	rf_vbls,snap_vbls
	move.w	ARC_XSCROLL,d0
	move.w	ARC_VRAM+$5F6E,d1
	move.w	d0,snap_xs
	move.w	d1,snap_ys
	bsr	scroll_set
	bsr	mo_snapshot
	move.l	snap_vbls,d7
	cmp.l	rf_vbls,d7
	beq	.snapped
	subq.w	#1,snap_tries
	bpl	.snap
.snapped:
	bsr	ring_target
	bsr	pal_update
	bsr	alpha_update
	bsr	pf_update
	bsr	ovl_build
	bsr	ovl_classify
	bsr	ring_validate
	bsr	dmg_restore
	bsr	ovl_restore_old
	bsr	pend_apply
	bsr	mo_draw
	tst.w	panel_open
	beq	.np
	bsr	panel_compose
.np:	bsr	alpha_transparent
	bsr	ovl_draw
	bsr	ovl_save
	bra	render_done

; scroll_set: the picture's place from the x scroll d0 and the y scroll word d1
scroll_set:
	addq.w	#8,d0
	and.w	#511,d0
	move.w	d0,sx
	moveq	#15,d2
	and.w	d0,d2
	move.w	d2,fine
	lsr.w	#4,d0
	addq.w	#MCOL,d0
	move.w	d0,w0
	lsl.w	#4,d0
	add.w	d2,d0
	move.w	d0,r0px			; R0 = 16 w0 + f: the ring pixel of the picture's x 0
	moveq	#3,d2
	and.w	d1,d2
	move.w	d2,bank
	lsr.w	#7,d1
	and.w	#511,d1
	move.w	d1,sy
	add.w	#GUARD,d1
	move.w	d1,top_t
	rts

; ring_target: the drawing goes into the work ring
ring_target:
	move.l	cur_ring,a0
	move.w	#STRIDE,tg_stride
	move.w	#MCOL,tg_pcol
	move.w	#GUARD,tg_pline
	move.w	r0px,d0
	subq.w	#8,d0
	move.w	d0,tg_r0		; (the arcade's x 0)
	move.w	top_t,tg_t
	st	tg_dmg
	rts

render_done:
	; the display: from the window's first word, PIC_TOP lines above the picture (SIM: the picture's line 0)
	move.l	cur_ring,a0
	move.w	w0,RS_W0(a0)
	move.w	fine,RS_F(a0)
	move.w	top_t,RS_T(a0)
	moveq	#0,d0
	move.w	top_t,d0
	ifnd SIM
	sub.w	#PIC_TOP,d0
	endc
	mulu	#STRIDE,d0
	moveq	#0,d1
	move.w	w0,d1
	lsl.w	#3,d1
	add.l	d1,d0
	add.l	work_base,d0
	move.l	d0,flip_addr
	move.b	fine+1,flip_fine
	st	frame_ready
	rts

; ---------------------------------------------------------------------------------------------------------------------
; pal_update: the pens $000-$2FF against their copy; a pen whose STE colour (irgb_map) changes is recorded in its
; set's mask (48 sets of 16 pens), then the sets are dealt with: tables made again, P's tiles drawn again, the
; characters of the alphanumerics colours drawn again, the motion objects' epoch.
pal_update:
	lea	ARC_PALETTE,a0
	lea	pal_shadow,a1
	move.w	#768/2,d4
.cmp:	bsr	cmp_run
	beq	.sets
	move.l	-4(a0),-4(a1)
	move.l	a0,d0
	sub.l	#ARC_PALETTE+4,d0
	lsr.w	#1,d0			; the first pen of the two
	lea	-4(a0),a2
	bsr	pen_new
	addq.w	#1,d0
	addq.l	#2,a2
	bsr	pen_new
	tst.w	d4
	bne	.cmp
.sets:	lea	set_mask,a4
	moveq	#0,d7			; the set
.set:	move.w	(a4),d6
	beq	.nset
	clr.w	(a4)
	bsr	set_changed
.nset:	addq.l	#2,a4
	addq.w	#1,d7
	cmp.w	#48,d7
	blo	.set
	rts
; pen d0.w's word at (a2): its STE colour; a change goes into set_mask.  Keeps d0/d6/a0-a2.
pen_new:
	moveq	#0,d1
	move.w	(a2),d1
	lea	irgb_map,a3
	move.b	(a3,d1.l),d1
	lea	pen_map,a3
	cmp.b	(a3,d0.w),d1
	beq	.same
	move.b	d1,(a3,d0.w)
	move.w	d0,d1
	lsr.w	#4,d1
	add.w	d1,d1
	lea	set_mask,a3
	moveq	#15,d2
	and.w	d0,d2
	move.w	(a3,d1.w),d3
	bset	d2,d3
	move.w	d3,(a3,d1.w)
.same:	rts

; set_changed: set d7 (pens 16 d7 ..) changed the pens d6.  Keeps d7/a4.
set_changed:
	cmp.w	#16,d7
	blo	al_set_changed
	cmp.w	#32,d7
	blo	.mo
	; the playfield: 32-39 the shadow sets (P'), 40-47 the sets (P)
	move.w	d7,d0
	sub.w	#32,d0			; the table: 0-7 shadow, 8-15 normal
	lea	lut_stale,a0
	st	(a0,d0.w)
	move.w	d7,d0
	and.w	#7,d0
	move.w	d6,d1
	moveq	#0,d2			; (P')
	cmp.w	#40,d7
	blo	.sh
	moveq	#1,d2			; (P)
.sh:	bra	pf_recolour
.mo:	move.w	d7,d0
	sub.w	#16,d0
	move.w	d0,-(sp)
	bsr	map_id			; (the set's 16 STE colours: their number in the table of the ones seen)
	move.w	(sp)+,d1
	lea	mo_epoch,a0
	move.b	d0,(a0,d1.w)		; (the baked images are keyed by it: a mapping seen before finds them again)
	add.w	#16,d1			; table 16 + the set
	lea	lut_stale,a0
	st	(a0,d1.w)
	rts

; map_id: motion object palette d0.w's 16 STE colours (pen_map) -> d0 = their number (1-255) in map_tab; a new one
; is added; a full table starts again (and the baked images, keyed by the numbers, are forgotten).  Keeps d6/d7/a4.
map_id:
	lea	pen_map+$100,a0
	lsl.w	#4,d0
	add.w	d0,a0
	movem.l	(a0),d0-d3		; (the 16 bytes)
	lea	map_tab,a1
	move.w	map_n,d4
	moveq	#1,d5
	bra	.n
.c:	cmp.l	(a1),d0
	bne	.x
	cmp.l	4(a1),d1
	bne	.x
	cmp.l	8(a1),d2
	bne	.x
	cmp.l	12(a1),d3
	bne	.x
	move.w	d5,d0
	rts
.x:	lea	16(a1),a1
	addq.w	#1,d5
.n:	dbf	d4,.c
	cmp.w	#255,map_n
	blo	.add
	clr.w	map_n			; (full: from the start, the images forgotten)
	movem.l	d0-d3,-(sp)
	bsr	mo_flush
	movem.l	(sp)+,d0-d3
	lea	map_tab,a1
	moveq	#1,d5
.add:	movem.l	d0-d3,(a1)
	addq.w	#1,map_n
	move.w	d5,d0
	rts

; lut_need: table d0.w (0-7 the playfield's shadow sets, 8-15 its sets, 16-31 the motion objects') made when its
; pens changed since.  Keeps every register.
lut_need:
	move.l	a0,-(sp)
	lea	lut_stale,a0
	tst.b	(a0,d0.w)
	beq	.ok
	sf	(a0,d0.w)
	movem.l	d0-d7/a1-a4,-(sp)
	move.w	d0,d1
	cmp.w	#16,d1
	bhs	.mo
	add.w	#32,d1			; (sets 32-47: pens $200-$2FF)
	bra	.p
.mo:	add.w	#16-16,d1		; (16-31: pens $100-$1FF)
.p:	lsl.w	#4,d1
	bsr	lut_build
	movem.l	(sp)+,d0-d7/a1-a4
.ok:	move.l	(sp)+,a0
	rts

; lut_build: table d0.w (2 KB at LUTS) from the 16 pens from d1.w: [b] = the plane bits of the pixels b >> 4 and
; b & 15 (two bits a byte, plane 0 in the high byte, the first pixel the higher bit); at +1024 the pixels swapped.
lut_build:
	lea	LUTS,a1
	and.l	#$ffff,d0
	moveq	#11,d2
	lsl.l	d2,d0
	add.l	d0,a1
	lea	pen_map,a3
	add.w	d1,a3
	lea	spread4,a0
	lea	lut_tmp,a2		; s[16], then s << 1
	moveq	#16-1,d3
.s:	moveq	#0,d0
	move.b	(a3)+,d0
	add.w	d0,d0
	add.w	d0,d0
	move.l	(a0,d0.w),d0
	move.l	d0,(a2)+
	add.l	d0,d0
	move.l	d0,64-4(a2)
	dbf	d3,.s
	lea	lut_tmp+64,a3		; [hi << 4 | lo] = s2[hi] | s[lo]
	moveq	#16-1,d3
.h:	move.l	(a3)+,d2
	lea	lut_tmp,a2
	rept	16
	move.l	(a2)+,d0
	or.l	d2,d0
	move.l	d0,(a1)+
	endr
	dbf	d3,.h
	lea	lut_tmp,a3		; mirrored: s2[lo] | s[hi]
	moveq	#16-1,d3
.m:	move.l	(a3)+,d2
	lea	lut_tmp+64,a2
	rept	16
	move.l	(a2)+,d0
	or.l	d2,d0
	move.l	d0,(a1)+
	endr
	dbf	d3,.m
	rts

spread4:				; a colour's plane bits, one a byte (plane 0 in the high byte)
N	set	0
	rept	16
	dc.l	((N&1)<<24)|(((N>>1)&1)<<16)|(((N>>2)&1)<<8)|((N>>3)&1)
N	set	N+1
	endr

; ---------------------------------------------------------------------------------------------------------------------
; pf_update: the playfield.  A new tile bank: every copy invalid.  The window's tiles (29 columns x 31 rows from
; (sx >> 3, sy >> 3); 42 columns when the panel shows the playfield) against their copy: a changed one is drawn into
; P and P' and queued for both rings.
pf_update:
	move.w	bank,d0
	cmp.w	last_bank,d0
	beq	.same
	move.w	d0,last_bank
	lea	ARC_VRAM,a0
	lea	pf_shadow,a1
	move.w	#$2000/4-1,d0
.inv:	move.l	(a0)+,d1
	not.l	d1
	move.l	d1,(a1)+
	dbf	d0,.inv
.same:	move.w	sx,d7
	lsr.w	#3,d7			; the first column
	moveq	#29-1,d6		; (the maze: the arcade's x 8-231)
	tst.w	panel_open
	beq	.col
	moveq	#42-1,d6		; (and the panel's playfield: 240-335)
.col:	and.w	#63,d7
	move.w	d7,d0
	lsl.w	#7,d0			; (128 bytes a column)
	lea	ARC_VRAM,a0
	add.w	d0,a0
	lea	pf_shadow,a1
	add.w	d0,a1
	move.l	a0,col_base
	move.w	sy,d5
	lsr.w	#4,d5			; the first long (two rows)
	moveq	#32,d4
	sub.w	d5,d4			; longs before the column wraps
	cmp.w	#16,d4
	bls	.w
	moveq	#16,d4
.w:	moveq	#16,d3
	sub.w	d4,d3
	move.w	d3,col_rest		; (then from the column's start)
	lsl.w	#2,d5
	add.w	d5,a0
	add.w	d5,a1
.run:	bsr	cmp_run
	beq	.end
	movem.l	d4/d6-d7/a0-a1,-(sp)
	move.l	-4(a0),-4(a1)
	move.l	a0,d3
	sub.l	#ARC_VRAM+4,d3
	lsr.w	#1,d3			; the index of the first word
	move.w	d3,-(sp)
	bsr	pf_tile_new
	move.w	(sp)+,d3
	addq.w	#1,d3
	bsr	pf_tile_new
	movem.l	(sp)+,d4/d6-d7/a0-a1
	tst.w	d4
	bne	.run
.end:	move.w	col_rest,d4
	beq	.ncol
	clr.w	col_rest
	move.l	col_base,a0
	move.l	a0,a1
	add.l	#pf_shadow-ARC_VRAM,a1
	bra	.run
.ncol:	addq.w	#1,d7
	dbf	d6,.col
	rts

; cmp_run: d4.w longs at a0 / a1: Z clear at the first that differs (a0 / a1 past it, d4 the longs after it), Z set
; when all are equal.  Uses d3/a2/a3.
cmp_run:
.c:	move.w	d4,d3
	cmp.w	#21,d3
	bls	.n
	moveq	#21,d3
.n:	sub.w	d3,d4			; (the longs after this piece)
	move.w	d3,a3
	add.w	d3,a3
	add.w	d3,a3
	add.w	d3,a3
	add.l	a0,a3			; (its end)
	neg.w	d3
	add.w	#21,d3
	add.w	d3,d3
	add.w	d3,d3
	lea	.tab(pc),a2
	jmp	(a2,d3.w)
.tab:
	rept	21
	cmpm.l	(a0)+,(a1)+
	bne.s	.ne
	endr
	tst.w	d4
	bne	.c
	rts				; (Z set)
.ne:	move.l	a3,d3
	sub.l	a0,d3
	lsr.w	#2,d3
	add.w	d3,d4
	moveq	#1,d3			; (Z clear)
	rts

; pf_tile_new: the tile at index d3.w changed: into P and P', queued for both rings, listed under its palette
pf_tile_new:
	move.w	d3,-(sp)
	moveq	#3,d2			; (P and P')
	bsr	pf_tile_draw
	move.w	(sp),d3
	bsr	pend_push
	move.w	(sp)+,d3
	; listed under its palette
	lea	ARC_VRAM,a0
	move.w	d3,d0
	add.w	d0,d0
	move.w	(a0,d0.w),d0
	rol.w	#4,d0
	and.l	#7,d0			; the palette
	lea	pf_listed,a0
	move.b	(a0,d3.w),d1
	btst	d0,d1
	bne	.listed
	bset	d0,d1
	move.b	d1,(a0,d3.w)
	lea	pf_list_n,a0
	move.w	d0,d1
	add.w	d1,d1
	move.w	(a0,d1.w),d2
	addq.w	#1,(a0,d1.w)
	lea	PF_LISTS,a1
	moveq	#13,d1
	lsl.l	d1,d0			; (8 KB a list)
	add.l	d0,a1
	add.w	d2,d2
	move.w	d3,(a1,d2.w)
.listed:
	rts

; pend_push: tile index d3.w queued for both rings (an overflow drops the ring's valid rectangle)
pend_push:
	lea	ring_state0,a0
	bsr	.one
	lea	ring_state1,a0
.one:	move.w	RS_NPEND(a0),d0
	cmp.w	#PEND_MAX,d0
	bhs	.ovf
	addq.w	#1,RS_NPEND(a0)
	add.w	d0,d0
	lea	RS_PEND(a0),a1
	move.w	d3,(a1,d0.w)
	rts
.ovf:	st	RS_POVF(a0)
	rts

; pf_tile_draw: the tile at index d3.w into P (d2 bit 0) and P' (bit 1)
pf_tile_draw:
	lea	ARC_VRAM,a0
	move.w	d3,d0
	add.w	d0,d0
	move.w	(a0,d0.w),d0		; flip x 15, palette 12-14, tile 0-11
	move.w	d0,d4
	and.w	#$0fff,d4
	move.w	bank,d1
	ror.w	#4,d1
	or.w	d1,d4
	eor.w	#$0800,d4
	and.w	#$1fff,d4		; the code (8192 tiles)
	ext.l	d4
	lsl.l	#5,d4
	lea	tile_px,a0
	add.l	d4,a0			; its pixels
	move.w	d0,d5
	rol.w	#4,d5
	and.w	#7,d5			; the palette
	moveq	#11,d1
	lsl.w	d1,d5			; (2 KB a table)
	; the place: P + row * 2048 + (col >> 1) * 8 + (col & 1)
	moveq	#63,d1
	and.w	d3,d1			; the row
	moveq	#11,d4
	lsl.l	d4,d1
	move.w	d3,d4
	lsr.w	#6,d4			; the column
	move.w	d4,d6
	lsr.w	#1,d4
	lsl.w	#3,d4
	and.w	#1,d6
	add.w	d6,d4
	add.l	d4,d1			; (the offset)
	tst.w	d0
	smi	d7			; flip x
	btst	#0,d2
	beq	.nop
	movem.l	d1-d2/a0,-(sp)
	move.w	d5,d0
	moveq	#11,d4
	lsr.w	d4,d0
	addq.w	#8,d0
	bsr	lut_need
	lea	PFB,a1
	add.l	d1,a1
	lea	LUTS+8*2048,a2
	add.w	d5,a2
	bsr	tile_rows
	movem.l	(sp)+,d1-d2/a0
.nop:	btst	#1,d2
	beq	.nos
	move.w	d5,d0
	moveq	#11,d4
	lsr.w	d4,d0
	bsr	lut_need
	lea	PFS,a1
	add.l	d1,a1
	lea	LUTS,a2
	add.w	d5,a2
	bsr	tile_rows
.nos:	rts

; tile_rows: 8 rows of pixels at a0 (4 bytes a row) through the table a2 (d7.b set: mirrored) to a1 (256 bytes a line)
tile_rows:
	moveq	#8-1,d6
	tst.b	d7
	bne	.mir
.row:	moveq	#0,d1
	move.b	(a0)+,d1
	add.w	d1,d1
	add.w	d1,d1
	move.l	(a2,d1.w),d0
	lsl.l	#2,d0
	moveq	#0,d1
	move.b	(a0)+,d1
	add.w	d1,d1
	add.w	d1,d1
	or.l	(a2,d1.w),d0
	lsl.l	#2,d0
	moveq	#0,d1
	move.b	(a0)+,d1
	add.w	d1,d1
	add.w	d1,d1
	or.l	(a2,d1.w),d0
	lsl.l	#2,d0
	moveq	#0,d1
	move.b	(a0)+,d1
	add.w	d1,d1
	add.w	d1,d1
	or.l	(a2,d1.w),d0
	movep.l	d0,0(a1)
	lea	256(a1),a1
	dbf	d6,.row
	rts
.mir:	lea	1024(a2),a2
.mrow:	addq.l	#4,a0
	moveq	#0,d1
	move.b	-(a0),d1
	add.w	d1,d1
	add.w	d1,d1
	move.l	(a2,d1.w),d0
	lsl.l	#2,d0
	moveq	#0,d1
	move.b	-(a0),d1
	add.w	d1,d1
	add.w	d1,d1
	or.l	(a2,d1.w),d0
	lsl.l	#2,d0
	moveq	#0,d1
	move.b	-(a0),d1
	add.w	d1,d1
	add.w	d1,d1
	or.l	(a2,d1.w),d0
	lsl.l	#2,d0
	moveq	#0,d1
	move.b	-(a0),d1
	add.w	d1,d1
	add.w	d1,d1
	or.l	(a2,d1.w),d0
	movep.l	d0,0(a1)
	lea	256(a1),a1
	addq.l	#4,a0
	dbf	d6,.mrow
	rts

; pf_recolour: playfield palette d0.w's pens d1.w map to other colours (in P: d2 = 1, P': d2 = 0): the copies of its
; listed tiles that use them made to differ (pf_update draws them again into P and P' when they are in the window, at
; once or when the window comes there).  Keeps d7/a4.
pf_recolour:
	movem.l	d7/a4,-(sp)
	move.w	d1,d4			; the pens
	move.w	d2,d5
	move.w	d0,d6
	lea	pf_list_n,a0
	add.w	d0,d0
	move.w	(a0,d0.w),d7		; the entries
	lea	PF_LISTS,a3
	moveq	#13,d1
	moveq	#0,d0
	move.w	d6,d0
	lsl.l	d1,d0
	add.l	d0,a3
	bra	.next
.ent:	move.w	(a3)+,d3		; the index
	lea	ARC_VRAM,a0
	move.w	d3,d0
	add.w	d0,d0
	move.w	(a0,d0.w),d0
	move.w	d0,d1
	rol.w	#4,d1
	and.w	#7,d1
	cmp.w	d6,d1
	bne	.next			; (no longer of this palette)
	and.w	#$0fff,d0		; the code's pens
	move.w	bank,d1
	ror.w	#4,d1
	or.w	d1,d0
	eor.w	#$0800,d0
	and.w	#$1fff,d0
	add.w	d0,d0
	lea	tile_pens,a0
	move.w	(a0,d0.w),d0
	and.w	d4,d0
	beq	.next
	lea	ARC_VRAM,a0		; (its copy made to differ: drawn again when the window sees it)
	add.w	d3,d3
	move.w	(a0,d3.w),d0
	not.w	d0
	lea	pf_shadow,a0
	move.w	d0,(a0,d3.w)
.next:	dbf	d7,.ent
	movem.l	(sp)+,d7/a4
	rts

; ---------------------------------------------------------------------------------------------------------------------
; The alphanumerics: rows 0-29, the picture's characters k = 0-39 (the arcade's columns 1-28 and 30-41).  al_type:
; 0 nothing drawn, 1 opaque (every pixel; the panel's characters always), 2 transparent with pixels (the maze).
RR_SIZE = 42				; a row's runs of opaque characters: the count, (c0, c1) pairs

; alpha_update: the rows' words against their copy (longs: columns 0-41); a changed character drawn into AIMG
alpha_update:
	moveq	#0,d7			; the row
.row:	move.w	d7,d0
	lsl.w	#7,d0
	lea	ARC_VRAM+$5000,a0
	add.w	d0,a0
	lea	al_shadow,a1
	add.w	d0,a1
	moveq	#21,d4
.cmp:	bsr	cmp_run
	beq	.nr
	move.l	-4(a0),-4(a1)
	movem.l	d4/d7/a0-a1,-(sp)
	move.l	a0,d0
	sub.l	#ARC_VRAM+$5000+4,d0
	and.w	#127,d0
	lsr.w	#1,d0			; the first arcade column of the long
	move.w	d0,-(sp)
	bsr	al_column
	move.w	(sp)+,d0
	addq.w	#1,d0
	bsr	al_column
	movem.l	(sp)+,d4/d7/a0-a1
	tst.w	d4
	bne	.cmp
.nr:	addq.w	#1,d7
	cmp.w	#30,d7
	blo	.row
	bra	runs_update
; arcade column d0.w of row d7.w: the character drawn again (columns 0 and 29 are not shown)
al_column:
	tst.w	d0
	beq	.no
	cmp.w	#29,d0
	beq	.no
	blo	.m
	subq.w	#1,d0
.m:	subq.w	#1,d0			; k
	bra	al_char
.no:	rts

; al_char: the character k = d0.w of row d7.w drawn into AIMG (or noted as empty); its row's version bumped.
; Keeps d7.
al_char:
	move.w	d7,d1
	mulu	#40,d1
	add.w	d0,d1
	move.w	d1,d5			; the position (row * 40 + k)
	move.w	d0,d4			; k
	move.w	d4,d1
	cmp.w	#28,d1
	blo	.a
	addq.w	#1,d1
.a:	addq.w	#1,d1			; the arcade column
	move.w	d7,d0
	lsl.w	#6,d0
	add.w	d1,d0
	add.w	d0,d0
	lea	ARC_VRAM+$5000,a0
	move.w	(a0,d0.w),d3		; opaque 15, colour 10-13 (+ bit 14: 32), the character 0-9
	move.w	d3,d2
	lsr.w	#8,d2
	lsr.w	#2,d2
	and.w	#$0f,d2
	btst	#14,d3
	beq	.c
	or.w	#$20,d2			; the colour
.c:	; its type
	moveq	#1,d6
	tst.w	d3
	bmi	.t
	move.w	d3,d0
	and.w	#$3ff,d0
	lea	char_blank,a0
	moveq	#0,d6
	tst.b	(a0,d0.w)
	bne	.t
	moveq	#2,d6
.t:	lea	al_type,a0
	move.b	(a0,d5.w),d0
	move.b	d6,(a0,d5.w)
	cmp.w	#28,d4			; the panel: its characters not opaque counted
	blo	.tp
	cmp.b	#1,d0
	beq	.tp0
	subq.w	#1,panel_open
.tp0:	cmp.b	#1,d6
	beq	.tp
	addq.w	#1,panel_open
.tp:
	lea	row_t2,a0
	cmp.b	#2,d0
	bne	.t1
	subq.b	#1,(a0,d7.w)
.t1:	cmp.b	#2,d6
	bne	.t2
	addq.b	#1,(a0,d7.w)
.t2:	; the row's version
	addq.l	#1,al_counter
	move.w	d7,d0
	add.w	d0,d0
	add.w	d0,d0
	lea	row_ver,a0
	move.l	al_counter,(a0,d0.w)
	st	row_dirty
	lea	runs_dirty,a0
	st	(a0,d7.w)
	tst.w	d6
	beq	.done
	; listed under its colour
	lea	al_listed,a0
	cmp.b	(a0,d5.w),d2
	beq	.listed
	move.b	d2,(a0,d5.w)
	lea	al_list_n,a0
	move.w	d2,d0
	add.w	d0,d0
	lea	AL_LISTS,a1
	move.w	d2,d1
	mulu	#AL_N*2,d1
	add.l	d1,a1
	move.w	(a0,d0.w),d1
	cmp.w	#AL_N,d1
	blo	.room
	; (full: the entries listed under another colour since are dropped)
	movem.l	d0/d2-d3/a0-a2,-(sp)
	lea	al_listed,a2
	move.l	a1,a0
	moveq	#0,d3			; kept
	bra	.cn
.cp:	move.w	(a0)+,d0
	cmp.b	(a2,d0.w),d2
	bne	.cn
	move.w	d0,(a1)+
	addq.w	#1,d3
.cn:	dbf	d1,.cp
	move.w	d3,d1
	movem.l	(sp)+,d0/d2-d3/a0-a2
	move.w	d1,(a0,d0.w)
.room:	addq.w	#1,(a0,d0.w)
	add.w	d1,d1
	move.w	d5,(a1,d1.w)
.listed:
	; its pixels: AIMG + row * 8 * AL + (k >> 1) * 8 + (k & 1)
	lea	ALUTS,a2
	moveq	#0,d0
	move.w	d2,d0
	moveq	#10,d1
	lsl.l	d1,d0
	add.l	d0,a2			; the colour's table
	and.w	#$3ff,d3
	lsl.w	#4,d3
	lea	char_rows,a0
	add.w	d3,a0
	move.w	d7,d0
	mulu	#8*AL,d0
	lea	AIMG,a1
	add.l	d0,a1
	move.w	d4,d0
	lsr.w	#1,d0
	lsl.w	#3,d0
	and.w	#1,d4
	add.w	d4,d0
	add.w	d0,a1
	moveq	#8-1,d6
.row:	moveq	#0,d1
	move.b	(a0)+,d1
	add.w	d1,d1
	add.w	d1,d1
	move.l	(a2,d1.w),d0
	lsl.l	#4,d0
	moveq	#0,d1
	move.b	(a0)+,d1
	add.w	d1,d1
	add.w	d1,d1
	or.l	(a2,d1.w),d0
	movep.l	d0,0(a1)
	lea	AL(a1),a1
	dbf	d6,.row
.done:	rts

; al_set_changed: alphanumerics pens 16 d7 .. (colours 4 d7 .. 4 d7 + 3) changed (mask d6): their tables made again,
; their listed characters drawn again.  Keeps d7/a4.
al_set_changed:
	movem.l	d7/a4,-(sp)
	move.w	d7,d5
	lsl.w	#2,d5			; the first colour
	moveq	#4-1,d4
.c:	moveq	#15,d0
	and.w	d6,d0
	beq	.nc
	movem.l	d4-d6,-(sp)
	move.w	d5,d0
	bsr	alut_build
	movem.l	(sp),d4-d6
	move.w	d5,d0
	moveq	#15,d1
	and.w	d6,d1			; (its changed pens)
	bsr	al_recolour
	movem.l	(sp)+,d4-d6
.nc:	lsr.w	#4,d6
	addq.w	#1,d5
	dbf	d4,.c
	movem.l	(sp)+,d7/a4
	rts

; alut_build: colour d0.w's table: [b] = the plane nibbles of the four 2-bit pixels of b (the first the highest bit):
; [hi << 4 | lo] = pairs_hi[hi] | pairs_lo[lo]
alut_build:
	lea	ALUTS,a1
	moveq	#0,d1
	move.w	d0,d1
	moveq	#10,d2
	lsl.l	d2,d1
	add.l	d1,a1
	lea	pen_map,a3
	add.w	d0,a3
	add.w	d0,a3
	add.w	d0,a3
	add.w	d0,a3			; its 4 pens
	lea	spread4,a0
	lea	lut_tmp,a2
	moveq	#4-1,d3			; s[4]
.s:	moveq	#0,d0
	move.b	(a3)+,d0
	add.w	d0,d0
	add.w	d0,d0
	move.l	(a0,d0.w),(a2)+
	dbf	d3,.s
	lea	lut_tmp,a0		; the pairs: hi (s[a] << 3 | s[b] << 2) at +16, lo (s[a] << 1 | s[b]) at +80
	lea	lut_tmp+16,a2
	lea	lut_tmp+80,a3
	moveq	#0,d3			; a
.pa:	moveq	#0,d4			; b
.pb:	move.l	(a0,d3.w),d0
	add.l	d0,d0
	or.l	(a0,d4.w),d0
	move.l	d0,(a3)+
	add.l	d0,d0
	add.l	d0,d0
	move.l	d0,(a2)+
	addq.w	#4,d4
	cmp.w	#16,d4
	blo	.pb
	addq.w	#4,d3
	cmp.w	#16,d3
	blo	.pa
	lea	lut_tmp+16,a3
	moveq	#16-1,d3
.h:	move.l	(a3)+,d2
	lea	lut_tmp+80,a2
	rept	16
	move.l	(a2)+,d0
	or.l	d2,d0
	move.l	d0,(a1)+
	endr
	dbf	d3,.h
	rts

; al_recolour: colour d0.w's listed characters that use its pens d1.w drawn again
al_recolour:
	move.w	d1,d4			; the pens
	move.w	d0,d6
	lea	al_list_n,a0
	add.w	d0,d0
	move.w	(a0,d0.w),d5
	lea	AL_LISTS,a3
	move.w	d6,d0
	mulu	#AL_N*2,d0
	add.l	d0,a3
	bra	.next
.ent:	move.w	(a3)+,d0		; the position
	lea	al_listed,a0
	cmp.b	(a0,d0.w),d6
	bne	.next			; (listed under another colour since)
	move.w	d0,d1			; its character uses the pens?
	add.w	d1,d1
	lea	al_voff,a0
	move.w	(a0,d1.w),d1
	lea	ARC_VRAM+$5000,a0
	move.w	(a0,d1.w),d1
	and.w	#$3ff,d1
	lea	char_pens,a0
	move.b	(a0,d1.w),d1
	and.b	d4,d1
	beq	.next
	movem.l	d4-d7/a3,-(sp)
	ext.l	d0
	divu	#40,d0
	move.w	d0,d7			; the row
	swap	d0			; k
	bsr	al_char
	movem.l	(sp)+,d4-d7/a3
.next:	dbf	d5,.ent
	rts

; runs_update: the runs of opaque characters of the rows that changed
runs_update:
	tst.b	row_dirty
	beq	.done
	sf	row_dirty
	addq.w	#1,runs_version
	moveq	#0,d7
	lea	runs_dirty,a2
.row:	tst.b	(a2,d7.w)
	beq	.nr
	sf	(a2,d7.w)
	lea	al_type,a0
	move.w	d7,d0
	mulu	#40,d0
	add.w	d0,a0
	lea	row_runs,a1
	move.w	d7,d0
	mulu	#RR_SIZE,d0
	add.w	d0,a1
	move.l	a1,a3
	clr.b	(a1)+			; the count
	moveq	#0,d1			; k
.k:	cmp.b	#1,(a0,d1.w)
	bne	.nk
	move.b	d1,(a1)+		; a run's start
.r:	addq.w	#1,d1
	cmp.w	#40,d1
	bhs	.end
	cmp.b	#1,(a0,d1.w)
	beq	.r
.end:	move.b	d1,(a1)+
	addq.b	#1,(a3)
	bra	.k2
.nk:	addq.w	#1,d1
.k2:	cmp.w	#40,d1
	blo	.k
.nr:	addq.w	#1,d7
	cmp.w	#30,d7
	blo	.row
.done:	rts

; ---------------------------------------------------------------------------------------------------------------------
; ovl_build: this picture's overlay rectangles (new_ovl): equal rows' runs merged; their ring columns
ovl_build:
	move.w	runs_version,d0		; (the runs and the ring's place as last time: the same rectangles)
	cmp.w	ob_runs_v,d0
	bne	.new
	move.w	r0px,d0
	cmp.w	ob_r0px,d0
	bne	.new
	lea	new_ovl,a2
	move.w	new_novl,d7
	move.l	al_counter,d5
	bra	.rn
.re2:	move.l	d5,OV_STAMP(a2)
	clr.w	OV_KEEP(a2)
	move.w	#32767,OV_DLO(a2)
	move.w	#-1,OV_DHI(a2)
	lea	OV_SIZE(a2),a2
.rn:	dbf	d7,.re2
	rts
.new:	move.w	runs_version,ob_runs_v
	move.w	r0px,ob_r0px
	lea	new_ovl,a2
	clr.w	new_novl
	moveq	#0,d7			; the row
.grp:	cmp.w	#30,d7
	bhs	.done
	move.w	d7,d6			; the group's last row
	lea	row_runs,a0
	move.w	d7,d0
	mulu	#RR_SIZE,d0
	add.w	d0,a0			; its runs
	move.l	al_counter,d5		; the stamp: the characters as of now
.more:	move.w	d6,d0
	addq.w	#1,d0
	cmp.w	#30,d0
	bhs	.emit
	lea	row_runs,a1
	mulu	#RR_SIZE,d0
	add.w	d0,a1
	moveq	#0,d1
	move.b	(a0),d1
	add.w	d1,d1			; (the pairs' bytes, then the count)
.eq:	move.b	(a0,d1.w),d0
	cmp.b	(a1,d1.w),d0
	bne	.emit
	dbf	d1,.eq
	addq.w	#1,d6
	bra	.more
.emit:	moveq	#0,d4
	move.b	(a0)+,d4		; the runs
	bra	.re
.run:	cmp.w	#OVL_MAX,new_novl
	bhs	.re
	addq.w	#1,new_novl
	moveq	#0,d0
	move.b	(a0)+,d0
	move.w	d0,OV_C0(a2)
	move.b	(a0)+,d0
	move.w	d0,OV_C1(a2)
	move.w	d7,d0
	lsl.w	#3,d0
	move.w	d0,OV_Y0(a2)
	move.w	d6,d0
	lsl.w	#3,d0
	addq.w	#7,d0
	move.w	d0,OV_Y1(a2)
	move.l	d5,OV_STAMP(a2)
	clr.w	OV_KEEP(a2)
	move.w	#32767,OV_DLO(a2)
	move.w	#-1,OV_DHI(a2)
	move.w	OV_C0(a2),d0
	lsl.w	#3,d0
	add.w	r0px,d0
	lsr.w	#4,d0
	move.w	d0,OV_RC0(a2)
	move.w	OV_C1(a2),d0
	lsl.w	#3,d0
	subq.w	#1,d0
	add.w	r0px,d0
	lsr.w	#4,d0
	move.w	d0,OV_RC1(a2)
	lea	OV_SIZE(a2),a2
.re:	dbf	d4,.run
	move.w	d6,d7
	addq.w	#1,d7
	bra	.grp
.done:	rts

; ovl_classify: a new rectangle equal to one the ring has (the same characters' place, the same stamp, the ring at
; the same place) is kept
ovl_classify:
	move.l	cur_ring,a3
	lea	RS_OVL(a3),a1
	move.w	RS_NOVL(a3),d6
	bra	.cn
.cl:	clr.w	OV_KEEP(a1)
	lea	OV_SIZE(a1),a1
.cn:	dbf	d6,.cl
	move.w	RS_W0(a3),d0
	cmp.w	w0,d0
	bne	.done
	move.w	RS_F(a3),d0
	cmp.w	fine,d0
	bne	.done
	move.w	RS_T(a3),d0
	cmp.w	top_t,d0
	bne	.done
	lea	new_ovl,a2
	move.w	new_novl,d7
	bra	.nn
.n:	lea	RS_OVL(a3),a1
	move.w	RS_NOVL(a3),d6
	bra	.no
.o:	move.l	OV_C0(a2),d0
	cmp.l	OV_C0(a1),d0
	bne	.on
	move.l	OV_Y0(a2),d0
	cmp.l	OV_Y0(a1),d0
	bne	.on
	move.w	#1,OV_KEEP(a2)
	move.w	#1,OV_KEEP(a1)		; (the old one: not restored)
	; its rows changed since: drawn again
	move.l	OV_STAMP(a1),d2
	move.w	OV_Y0(a2),d0
	lsr.w	#3,d0
	move.w	OV_Y1(a2),d1
	lsr.w	#3,d1
	lea	row_ver,a0
.rv:	move.w	d0,d3
	add.w	d3,d3
	add.w	d3,d3
	cmp.l	(a0,d3.w),d2
	bhs	.rn
	move.w	d0,d3
	lsl.w	#3,d3
	cmp.w	OV_DLO(a2),d3
	bge	.r1
	move.w	d3,OV_DLO(a2)
.r1:	addq.w	#7,d3
	cmp.w	OV_DHI(a2),d3
	ble	.rn
	move.w	d3,OV_DHI(a2)
.rn:	addq.w	#1,d0
	cmp.w	d1,d0
	bls	.rv
	bra	.nx
.on:	lea	OV_SIZE(a1),a1
.no:	dbf	d6,.o
.nx:	lea	OV_SIZE(a2),a2
.nn:	dbf	d7,.n
.done:	rts

; touch: ring columns d0.w (+ d1.w) x lines d2.w (+ d3.w) are written: the kept overlay rectangles there are drawn
; again in those lines.  Keeps d0-d7/a0-a6 but a5.
touch:
	movem.l	d4-d7/a2,-(sp)
	lea	new_ovl,a2
	move.w	new_novl,d7
	bra	.nn
.n:	tst.w	OV_KEEP(a2)
	beq	.nx
	cmp.w	OV_RC1(a2),d0
	bgt	.nx
	move.w	d0,d4
	add.w	d1,d4
	cmp.w	OV_RC0(a2),d4
	ble	.nx
	move.w	d2,d4
	sub.w	top_t,d4		; the picture's lines
	move.w	d4,d5
	add.w	d3,d5
	subq.w	#1,d5
	cmp.w	OV_Y0(a2),d4
	bge	.lo
	move.w	OV_Y0(a2),d4
.lo:	cmp.w	OV_Y1(a2),d5
	ble	.hi
	move.w	OV_Y1(a2),d5
.hi:	cmp.w	d4,d5
	blt	.nx
	cmp.w	OV_DLO(a2),d4
	bge	.l2
	move.w	d4,OV_DLO(a2)
.l2:	cmp.w	OV_DHI(a2),d5
	ble	.nx
	move.w	d5,OV_DHI(a2)
.nx:	lea	OV_SIZE(a2),a2
.nn:	dbf	d7,.n
	movem.l	(sp)+,d4-d7/a2
	rts

; ---------------------------------------------------------------------------------------------------------------------
; ring_validate: the ring's valid rectangle covers the picture's maze (columns w0 .. w0 + 14, lines T .. T + 239):
; grown to the bounding box when that copies less than the window, else the window alone
ring_validate:
	move.l	cur_ring,a3
	tst.w	RS_POVF(a3)
	beq	.p
	clr.w	RS_POVF(a3)
	clr.w	RS_NPEND(a3)
	clr.w	RS_VC1(a3)		; (pending tiles lost: nothing valid)
	clr.w	RS_VC0(a3)
.p:	move.w	w0,d4			; V: d4 .. d5 - 1, d6 .. d7 - 1
	move.w	d4,d5
	add.w	#15,d5
	move.w	top_t,d6
	move.w	d6,d7
	add.w	#240,d7
	move.w	RS_VC0(a3),d0
	cmp.w	RS_VC1(a3),d0
	bge	.fresh
	; inside?
	cmp.w	RS_VC0(a3),d4
	blt	.out
	cmp.w	RS_VC1(a3),d5
	bgt	.out
	cmp.w	RS_VL0(a3),d6
	blt	.out
	cmp.w	RS_VL1(a3),d7
	bgt	.out
	rts
.out:	; the bounding box B
	move.w	RS_VC0(a3),d0
	cmp.w	d4,d0
	ble	.b1
	move.w	d4,d0
.b1:	move.w	RS_VC1(a3),d1
	cmp.w	d5,d1
	bge	.b2
	move.w	d5,d1
.b2:	move.w	RS_VL0(a3),d2
	cmp.w	d6,d2
	ble	.b3
	move.w	d6,d2
.b3:	move.w	RS_VL1(a3),d3
	cmp.w	d7,d3
	bge	.b4
	move.w	d7,d3
.b4:	; area(B) - area(valid) against area(V) = 15 x 240
	movem.w	d0-d3,bbox
	sub.w	d0,d1
	sub.w	d2,d3
	mulu	d1,d3
	move.w	RS_VC1(a3),d0
	sub.w	RS_VC0(a3),d0
	move.w	RS_VL1(a3),d1
	sub.w	RS_VL0(a3),d1
	mulu	d0,d1
	sub.l	d1,d3
	cmp.l	#15*240,d3
	bhi	.fresh
	; B - valid: above, below (B's width), left, right (valid's lines)
	movem.w	RS_VC0(a3),d4-d7	; valid: d4 .. d5, d6 .. d7
	move.w	bbox,d0			; above
	move.w	bbox+2,d1
	sub.w	d0,d1
	move.w	bbox+4,d2
	move.w	d6,d3
	sub.w	d2,d3
	bsr	copy_rect_s
	move.w	bbox,d0			; below
	move.w	bbox+2,d1
	sub.w	d0,d1
	move.w	d7,d2
	move.w	bbox+6,d3
	sub.w	d2,d3
	bsr	copy_rect_s
	move.w	bbox,d0			; left
	move.w	d4,d1
	sub.w	d0,d1
	move.w	d6,d2
	move.w	d7,d3
	sub.w	d2,d3
	bsr	copy_rect_s
	move.w	d5,d0			; right
	move.w	bbox+2,d1
	sub.w	d0,d1
	move.w	d6,d2
	move.w	d7,d3
	sub.w	d2,d3
	bsr	copy_rect_s
	movem.w	bbox,d0-d3
	movem.w	d0-d3,RS_VC0(a3)
	rts
.fresh:	move.w	w0,d0
	moveq	#15,d1
	move.w	top_t,d2
	move.w	#240,d3
	movem.w	d0-d3,-(sp)
	bsr	copy_rect_s
	movem.w	(sp)+,d0-d3
	add.w	d0,d1
	add.w	d2,d3
	movem.w	d0-d3,RS_VC0(a3)
	rts

; copy_rect_s: copy_rect keeping d4-d7/a3; touches the kept overlay rectangles
copy_rect_s:
	tst.w	d1
	ble	.no
	tst.w	d3
	ble	.no
	bsr	touch
	movem.l	d4-d7/a3,-(sp)
	bsr	copy_rect
	movem.l	(sp)+,d4-d7/a3
.no:	rts

; copy_rect: ring columns d0.w (+ d1.w) x lines d2.w (+ d3.w) from P into the work ring (split where P wraps); the
; target: work_base, tg_stride, tg_pcol / tg_pline (the column and line that show P's column / line 0)
copy_rect:
	move.w	d2,d4
	sub.w	tg_pline,d4
	and.w	#511,d4			; P's line
	move.w	#512,d5
	sub.w	d4,d5			; lines before P wraps
	cmp.w	d3,d5
	bhs	copy_cols
	movem.w	d0-d5,-(sp)
	move.w	d5,d3
	bsr	copy_cols
	movem.w	(sp)+,d0-d5
	add.w	d5,d2
	sub.w	d5,d3
	bra	copy_rect
; d4 = P's line of ring line d2
copy_cols:
	move.w	d0,d5
	sub.w	tg_pcol,d5
	and.w	#31,d5			; P's column
	moveq	#32,d6
	sub.w	d5,d6			; columns before P wraps
	cmp.w	d1,d6
	bhs	copy_piece
	movem.w	d0-d6,-(sp)
	move.w	d6,d1
	bsr	copy_piece
	movem.w	(sp)+,d0-d6
	add.w	d6,d0
	sub.w	d6,d1
	bra	copy_cols
; d0 ring column, d1 columns, d2 ring line, d3 lines, d4 P's line, d5 P's column
copy_piece:
	moveq	#0,d6
	move.w	d4,d6
	lsl.l	#8,d6			; (256 bytes a line)
	lsl.w	#3,d5
	add.w	d5,d6
	add.l	#PFB,d6
	move.l	d6,BLT_SRC.w
	moveq	#0,d6
	move.w	d2,d6
	mulu	tg_stride,d6
	moveq	#0,d5
	move.w	d0,d5
	lsl.w	#3,d5
	add.l	d5,d6
	add.l	work_base,d6
	move.l	d6,BLT_DST.w
	moveq	#2,d6
	move.w	d6,BLT_SXI.w
	move.w	d6,BLT_DXI.w
	moveq	#-1,d6
	move.w	d6,BLT_E1.w
	move.w	d6,BLT_E2.w
	move.w	d6,BLT_E3.w
	move.w	d1,d6
	lsl.w	#2,d6			; the words
	move.w	d6,BLT_XC.w
	add.w	d6,d6
	move.w	#258,d5
	sub.w	d6,d5
	move.w	d5,BLT_SYI.w
	move.w	tg_stride,d5
	addq.w	#2,d5
	sub.w	d6,d5
	move.w	d5,BLT_DYI.w
	move.w	d3,BLT_YC.w
	move.w	#$0203,BLT_HOP.w
	clr.b	BLT_SKEW.w
	bra	blit_go_copy

; ---------------------------------------------------------------------------------------------------------------------
; dmg_restore: the ring's damage (objects, transparent characters) copied back from P
dmg_restore:
	move.l	cur_ring,a3
	lea	RS_DMG(a3),a4
	move.w	RS_NDMG(a3),d7
	clr.w	RS_NDMG(a3)
	bra	.n
.d:	movem.w	(a4)+,d0-d3
	move.l	a4,-(sp)
	move.w	d7,-(sp)
	bsr	copy_rect_s
	move.w	(sp)+,d7
	move.l	(sp)+,a4
.n:	dbf	d7,.d
	rts

; dmg_add: ring columns d0 (+ d1) x lines d2 (+ d3) are damaged (and touch the kept overlay).  Keeps d0-d7/a0-a2/a4-a6.
dmg_add:
	bsr	touch
	move.l	a3,-(sp)
	move.l	cur_ring,a3
	cmp.w	#DMG_MAX,RS_NDMG(a3)
	bhs	.full
	move.l	d4,-(sp)
	move.w	RS_NDMG(a3),d4
	addq.w	#1,RS_NDMG(a3)
	lsl.w	#3,d4
	lea	RS_DMG(a3,d4.w),a3
	movem.w	d0-d3,(a3)
	move.l	(sp)+,d4
	move.l	(sp)+,a3
	rts
.full:	; (no room: the whole guarded window is damaged; the last entry grows to it)
	move.l	d4,-(sp)
	lea	RS_DMG+(DMG_MAX-1)*8(a3),a3
	move.w	w0,d4
	sub.w	#MCOL,d4
	move.w	d4,(a3)+
	move.w	#25,(a3)+
	move.w	top_t,d4
	sub.w	#GUARD,d4
	move.w	d4,(a3)+
	move.w	#240+2*GUARD,(a3)+
	move.l	(sp)+,d4
	move.l	(sp)+,a3
	rts

; ovl_restore_old: the ring's old overlay rectangles not kept: copied back from P; one of the same characters at the
; same lines (the ring moved) only where the new one does not cover whole words
ovl_restore_old:
	move.l	cur_ring,a3
	lea	RS_OVL(a3),a4
	move.w	RS_NOVL(a3),d7
	bra	.n
.o:	tst.w	OV_KEEP(a4)
	bne	.nx
	; its ring rectangle (its place then)
	move.w	OV_RC0(a4),d0
	move.w	OV_RC1(a4),d1
	sub.w	d0,d1
	addq.w	#1,d1
	move.w	RS_T(a3),d2
	add.w	OV_Y0(a4),d2
	move.w	OV_Y1(a4),d3
	sub.w	OV_Y0(a4),d3
	addq.w	#1,d3
	movem.w	d0-d3,orect
	; a new one of the same characters and lines?
	lea	new_ovl,a2
	move.w	new_novl,d6
	bra	.fn
.f:	move.l	OV_C0(a2),d0
	cmp.l	OV_C0(a4),d0
	bne	.fx
	move.l	OV_Y0(a2),d0
	cmp.l	OV_Y0(a4),d0
	beq	.same
.fx:	lea	OV_SIZE(a2),a2
.fn:	dbf	d6,.f
	; none: all of it
	movem.w	orect,d0-d3
	movem.l	d7/a3-a4,-(sp)
	bsr	copy_rect_s
	movem.l	(sp)+,d7/a3-a4
	bra	.nx
.same:	; the new one's whole words: columns (RC0 or RC0 + 1) .. (RC1 or RC1 - 1), lines T + y0 ..
	move.w	OV_RC0(a2),d0
	move.w	OV_C0(a2),d4
	lsl.w	#3,d4
	add.w	r0px,d4
	and.w	#15,d4
	beq	.c0
	addq.w	#1,d0
.c0:	move.w	OV_RC1(a2),d1
	move.w	OV_C1(a2),d4
	lsl.w	#3,d4
	add.w	r0px,d4
	and.w	#15,d4
	beq	.c1
	subq.w	#1,d1
.c1:	addq.w	#1,d1			; (the end)
	move.w	top_t,d2
	add.w	OV_Y0(a2),d2
	move.w	OV_Y1(a2),d3
	add.w	top_t,d3
	addq.w	#1,d3			; (the end)
	movem.w	d0-d3,crect
	movem.l	d7/a3-a4,-(sp)
	bsr	rect_minus
	movem.l	(sp)+,d7/a3-a4
.nx:	lea	OV_SIZE(a4),a4
.n:	dbf	d7,.o
	rts

; rect_minus: orect (col, cols, line, lines) minus crect (col0, col1, line0, line1: ends exclusive) copied from P
rect_minus:
	movem.w	orect,d4-d7		; O: d4 .. d4 + d5, d6 .. d6 + d7
	add.w	d4,d5
	add.w	d6,d7			; (ends)
	movem.w	crect,d0-d3
	; no overlap: all of O
	cmp.w	d5,d0
	bge	.all
	cmp.w	d1,d4
	bge	.all
	cmp.w	d7,d2
	bge	.all
	cmp.w	d3,d6
	bge	.all
	; the lines of O above C
	cmp.w	d2,d6
	bge	.na
	movem.w	d0-d3,-(sp)
	move.w	d4,d0
	move.w	d5,d1
	sub.w	d4,d1
	move.w	d2,d3
	move.w	d6,d2
	sub.w	d2,d3
	bsr	copy_rect_m
	movem.w	(sp)+,d0-d3
	move.w	d2,d6			; (O's rest from C's top)
.na:	cmp.w	d3,d7			; below
	ble	.nb
	movem.w	d0-d3,-(sp)
	move.w	d4,d0
	move.w	d5,d1
	sub.w	d4,d1
	move.w	d3,d2
	move.w	d7,d3
	sub.w	d2,d3
	bsr	copy_rect_m
	movem.w	(sp)+,d0-d3
	move.w	d3,d7
.nb:	cmp.w	d0,d4			; left (the remaining lines)
	bge	.nl
	movem.w	d0-d3,-(sp)
	move.w	d0,d1
	sub.w	d4,d1
	move.w	d4,d0
	move.w	d6,d2
	move.w	d7,d3
	sub.w	d6,d3
	bsr	copy_rect_m
	movem.w	(sp)+,d0-d3
.nl:	cmp.w	d1,d5			; right
	ble	.nr
	move.w	d1,d0
	move.w	d5,d1
	sub.w	d0,d1
	move.w	d6,d2
	move.w	d7,d3
	sub.w	d6,d3
	bsr	copy_rect_m
.nr:	rts
.all:	movem.w	orect,d0-d3
	bra	copy_rect_s
copy_rect_m:
	movem.l	d4-d7,-(sp)
	bsr	copy_rect_s
	movem.l	(sp)+,d4-d7
	rts

; pend_apply: the queued tiles copied from P into the ring where it is valid (every place of the torus's tile: two
; columns, two lines)
pend_apply:
	move.l	cur_ring,a3
	move.w	RS_NPEND(a3),d7
	clr.w	RS_NPEND(a3)
	lea	RS_PEND(a3),a4
	bra	.n
.p:	move.w	(a4)+,d6		; the index: column * 64 + row
	move.w	d6,d5
	and.w	#63,d5
	lsl.w	#3,d5			; P's line
	lsr.w	#6,d6			; the tile column
	; P's address
	moveq	#0,d0
	move.w	d5,d0
	lsl.l	#8,d0
	move.w	d6,d1
	lsr.w	#1,d1
	lsl.w	#3,d1
	add.w	d1,d0
	moveq	#1,d1
	and.w	d6,d1
	add.w	d1,d0
	add.l	#PFB,d0
	move.l	d0,a5			; (the source)
	lsr.w	#1,d6
	addq.w	#MCOL,d6		; the ring column
	add.w	#GUARD,d5		; the ring line
	moveq	#2-1,d4
.cl:	moveq	#2-1,d3
	move.w	d5,d2
.ln:	; inside the valid rectangle?
	cmp.w	RS_VC0(a3),d6
	blt	.nl
	cmp.w	RS_VC1(a3),d6
	bge	.nl
	move.w	d2,d0
	addq.w	#8,d0
	cmp.w	RS_VL0(a3),d0
	ble	.nl
	cmp.w	RS_VL1(a3),d2
	bge	.nl
	movem.l	d2-d7,-(sp)
	move.w	d6,d0
	moveq	#1,d1
	moveq	#8,d3
	bsr	touch
	moveq	#0,d0
	move.w	d2,d0
	mulu	#STRIDE,d0
	moveq	#0,d1
	move.w	d6,d1
	lsl.w	#3,d1
	add.l	d1,d0
	add.l	work_base,d0
	move.l	a5,d1
	btst	#0,d1
	beq	.ev
	addq.l	#1,d0
.ev:	move.l	d0,a1
	move.l	a5,a0
	rept	8
	movep.l	0(a0),d0
	movep.l	d0,0(a1)
	lea	256(a0),a0
	lea	STRIDE(a1),a1
	endr
	movem.l	(sp)+,d2-d7
.nl:	add.w	#512,d2
	cmp.w	#RING_LINES-8,d2
	bhi	.nc
	dbf	d3,.ln
.nc:	add.w	#32,d6
	cmp.w	#RING_COLS,d6
	bhs	.n
	dbf	d4,.cl
.n:	dbf	d7,.p
	rts

; ---------------------------------------------------------------------------------------------------------------------
; ovl_draw: the new overlay rectangles: drawn (the kept ones only in their touched lines)
ovl_draw:
	lea	new_ovl,a4
	move.w	new_novl,d7
	bra	.n
.o:	move.w	OV_Y0(a4),d2
	move.w	OV_Y1(a4),d3
	tst.w	OV_KEEP(a4)
	beq	.draw
	move.w	OV_DLO(a4),d2
	move.w	OV_DHI(a4),d3
	cmp.w	d2,d3
	blt	.nx
.draw:	move.w	OV_C0(a4),d0
	move.w	OV_C1(a4),d1
	movem.l	d7/a4,-(sp)
	bsr	ovl_blit
	movem.l	(sp)+,d7/a4
.nx:	lea	OV_SIZE(a4),a4
.n:	dbf	d7,.o
	rts

; ovl_save: the new rectangles become the ring's
ovl_save:
	move.l	cur_ring,a3
	lea	new_ovl,a0
	lea	RS_OVL(a3),a1
	move.w	new_novl,d0
	move.w	d0,RS_NOVL(a3)
	mulu	#OV_SIZE/4,d0
	bra	.n
.c:	move.l	(a0)+,(a1)+
.n:	dbf	d0,.c
	rts

; ovl_blit: AIMG's characters d0.w .. d1.w - 1 in the picture's lines d2.w .. d3.w into the ring (sblit: AIMG's
; pixel x at the ring's R0 + x)
ovl_blit:
	lsl.w	#3,d0
	lsl.w	#3,d1
	sub.w	d0,d1
	move.w	d1,sb_w
	move.w	d0,sb_spx
	add.w	r0px,d0
	move.w	d0,sb_dpx
	moveq	#0,d0
	move.w	d2,d0
	mulu	#AL,d0
	add.l	#AIMG,d0
	move.l	d0,sb_src
	move.w	#AL,sb_sstride
	moveq	#0,d0
	move.w	d2,d0
	add.w	top_t,d0
	mulu	#STRIDE,d0
	add.l	work_base,d0
	move.l	d0,sb_dst
	move.w	#STRIDE,sb_dstride
	sub.w	d2,d3
	addq.w	#1,d3
	move.w	d3,sb_lines
	bra	sblit

; ---------------------------------------------------------------------------------------------------------------------
; alpha_transparent: the maze's transparent characters with pixels (rare: drawn by the CPU over what is there, their
; pixel 0 left out); their damage noted
alpha_transparent:
	moveq	#0,d7
.row:	lea	row_t2,a0
	tst.b	(a0,d7.w)
	beq	.nr
	moveq	#0,d6
.k:	lea	al_type,a0
	move.w	d7,d0
	mulu	#40,d0
	add.w	d6,d0
	cmp.b	#2,(a0,d0.w)
	bne	.nk
	movem.l	d6-d7,-(sp)
	bsr	al_trans_char
	movem.l	(sp)+,d6-d7
.nk:	addq.w	#1,d6
	cmp.w	#40,d6
	blo	.k
.nr:	addq.w	#1,d7
	cmp.w	#30,d7
	blo	.row
	rts

; al_trans_char: character k = d6 of row d7 (its pixels from AIMG, its mask from the character's pixels not 0)
al_trans_char:
	move.w	d6,d0
	addq.w	#1,d0			; the arcade column
	cmp.w	#28,d6
	blo	.m
	addq.w	#1,d0
.m:
	move.w	d7,d1
	lsl.w	#6,d1
	add.w	d1,d0
	add.w	d0,d0
	lea	ARC_VRAM+$5000,a0
	move.w	(a0,d0.w),d0
	and.w	#$3ff,d0
	lsl.w	#4,d0
	lea	char_rows,a2
	add.w	d0,a2			; the rows' pixels
	move.w	d7,d0
	mulu	#8*AL,d0
	lea	AIMG,a0
	add.l	d0,a0
	move.w	d6,d0
	lsr.w	#1,d0
	lsl.w	#3,d0
	add.w	d0,a0
	moveq	#1,d0
	and.w	d6,d0
	add.w	d0,a0			; AIMG's byte
	move.w	d6,d4
	lsl.w	#3,d4
	add.w	r0px,d4			; the ring pixel
	moveq	#15,d5
	and.w	d4,d5			; its bit (from the left)
	lsr.w	#4,d4			; the ring word
	moveq	#0,d0
	move.w	d7,d0
	lsl.w	#3,d0
	add.w	top_t,d0
	movem.l	d0/d4,-(sp)
	mulu	#STRIDE,d0
	moveq	#0,d1
	move.w	d4,d1
	lsl.w	#3,d1
	add.l	d1,d0
	add.l	work_base,d0
	move.l	d0,a1
	moveq	#8-1,d7
.line:	moveq	#0,d0			; the mask: the pixels not 0
	move.b	(a2)+,d0
	lea	nz4,a3
	move.b	(a3,d0.w),d1
	lsl.b	#4,d1
	move.b	(a2)+,d0
	or.b	(a3,d0.w),d1
	and.l	#$ff,d1
	moveq	#24,d0
	sub.w	d5,d0
	lsl.l	d0,d1			; (at the ring pixel)
	move.l	d1,d2
	not.l	d2
	moveq	#4-1,d6
.pl:	moveq	#0,d3
	move.b	(a0),d3
	lsl.l	d0,d3
	and.l	d1,d3
	swap	d2
	and.w	d2,(a1)
	swap	d3
	or.w	d3,(a1)
	swap	d2
	swap	d3
	and.w	d2,8(a1)
	or.w	d3,8(a1)
	addq.l	#2,a0
	addq.l	#2,a1
	dbf	d6,.pl
	lea	AL-8(a0),a0
	lea	STRIDE-8(a1),a1
	dbf	d7,.line
	movem.l	(sp)+,d2/d4
	move.w	d4,d0
	moveq	#2,d1
	moveq	#8,d3
	bra	dmg_add

; ---------------------------------------------------------------------------------------------------------------------
; The motion objects.  MAME draws each band of 8 lines from the band's SLIP entry along the links until an entry
; repeats, every object clipped to the band, later ones over earlier ones.  mo_snapshot (while no VBL comes) turns
; that into draw records (mo_recs: the object's words, its place, the rows to draw) in drawing order:
; - the usual case: the visible bands' lists are suffixes of one chain (walked once from the first band; a band
;   whose start comes before the chain's first entry and leads to it extends the chain at its front).  An object at
;   chain position p is drawn in band k when the band's start is at a position <= p: whole when every band it covers
;   draws it (its rows outside the picture go into the guard lines), else the rows of those bands;
; - anything else (lists that merge elsewhere, or loop apart): every band walked, its objects' rows in that band.
; An object is 1-8 x 1-8 tiles of 8 x 8 (codes code, code + 1, ... row by row; flip x mirrors), pen 0 transparent,
; pen 1 the shadow (the playfield's colour from P' there), its palette 16 pens from $100.
MO_RECS = 1536
MR_CODE = 0				; a record: the words 0-2, the arcade's x and y of its top left, its rows r0 .. r1
MR_W1 = 2
MR_W2 = 4
MR_X = 6
MR_Y = 8
MR_R0 = 10
MR_R1 = 12
MR_SIZE = 14
MO_HASH = $3C2000			; the baked images: 2048 x (key.l, key2.l, address.l)
MO_HASH_N = 2048

mo_snapshot:
	clr.w	mo_n
	addq.w	#1,mo_pstamp
	bne	.ps
	lea	mp_stamp,a0
	move.w	#1024/2-1,d0
.cp:	clr.l	(a0)+
	dbf	d0,.cp
	move.w	#1,mo_pstamp
.ps:
	addq.w	#1,mo_stamp
	bne	.st
	lea	mo_stamps,a0
	move.w	#1024/2-1,d0
.cs:	clr.l	(a0)+
	dbf	d0,.cs
	move.w	#1,mo_stamp
.st:	; the bands: e = (sy - 1) & 7, the first (sy - 1) >> 3, 30 or 31 of them
	move.w	sy,d0
	subq.w	#1,d0
	and.w	#511,d0
	moveq	#7,d1
	and.w	d0,d1
	move.w	d1,mo_e
	lsr.w	#3,d0
	move.w	d0,mo_band0
	moveq	#30,d2
	tst.w	d1
	beq	.nb
	moveq	#31,d2
.nb:	move.w	d2,mo_nb
	move.w	snap_xs,d0
	and.w	#511,d0
	move.w	d0,mo_xs
	; the first band's chain
	lea	ARC_VRAM+$3800,a0	; (the links: the fourth plane of 1024 words)
	lea	mo_stamps,a1
	lea	mo_pos,a2
	lea	mo_order+2048,a3	; (room for entries put in front)
	move.w	mo_stamp,d5
	move.w	mo_band0,d0
	and.w	#63,d0
	add.w	d0,d0
	lea	ARC_VRAM+$5F80,a4
	move.w	(a4,d0.w),d1
	and.w	#$3ff,d1
	moveq	#0,d6			; the position
	lea	ARC_VRAM+$3000,a6	; (the y plane: the entries in the picture's lines noted in mo_vis)
	lea	mo_vis,a5
	move.w	sy,d7
.w1:	move.w	d1,d0
	add.w	d0,d0
	cmp.w	(a1,d0.w),d5
	beq	.w1e
	move.w	d5,(a1,d0.w)
	move.w	d6,(a2,d0.w)
	move.w	d1,(a3)+
	addq.w	#1,d6
	move.w	(a6,d0.w),d4		; (y + lines: 1 .. 303 when it may be visible)
	lsr.w	#7,d4
	neg.w	d4
	sub.w	d7,d4
	and.w	#511,d4
	beq	.inv
	cmp.w	#240+64,d4
	bhs	.inv
	move.w	d1,(a5)+
.inv:	move.w	(a0,d0.w),d1
	and.w	#$3ff,d1
	bra	.w1
.w1e:	move.w	d6,mo_count
	sub.l	#mo_vis,a5
	move.w	a5,d0
	lsr.w	#1,d0
	move.w	d0,mo_nvis
	clr.w	mo_front		; (the entries put in front)
	; the other bands' starts
	lea	mo_bstart,a5
	moveq	#0,d7			; k
.bk:	move.w	mo_band0,d0
	add.w	d7,d0
	and.w	#63,d0
	add.w	d0,d0
	move.w	(a4,d0.w),d1
	and.w	#$3ff,d1
	move.w	d1,d0
	add.w	d0,d0
	cmp.w	(a1,d0.w),d5
	beq	.known
	bsr	mo_front_walk		; (a start not on the chain: in front of it, or the general way)
	bne	mo_general
	move.w	d1,d0
	add.w	d0,d0
.known:	move.w	(a2,d0.w),(a5)+
	addq.w	#1,d7
	cmp.w	mo_nb,d7
	blo	.bk
	; the records, in the chain's order
	lea	mo_vis,a3		; (the chain's entries in the picture's lines)
	move.w	mo_nvis,d0
	tst.w	mo_front
	beq	.v
	lea	mo_order+2048,a3	; (entries put in front: all of them)
	move.w	mo_front,d0
	add.w	d0,d0
	sub.w	d0,a3
	move.w	mo_count,d0
	add.w	mo_front,d0
.v:	move.w	d0,mo_left
	lea	mo_recs,a6
	lea	ARC_VRAM+$3000,a0
	lea	ARC_VRAM+$2800,a1
.r:	subq.w	#1,mo_left
	bmi	.done
	move.w	(a3)+,d1		; the entry
	bsr	mo_place		; -> d2 x, d3 y, d4 lines; Z: not visible
	beq	.r
	move.w	d1,d0
	add.w	d0,d0
	move.w	(a2,d0.w),d0		; its position
	; the bands it covers: k0 = (max(y, 0) + e) >> 3 .. k1 = (min(y + lines - 1, 239) + e) >> 3
	move.w	d3,d5
	bpl	.y0
	moveq	#0,d5
.y0:	add.w	mo_e,d5
	lsr.w	#3,d5			; k0
	move.w	d3,d6
	add.w	d4,d6
	subq.w	#1,d6
	cmp.w	#239,d6
	ble	.y1
	move.w	#239,d6
.y1:	add.w	mo_e,d6
	lsr.w	#3,d6			; k1
	lea	mo_bstart,a5
	move.w	d5,d7
	add.w	d7,d7
	add.w	d7,a5
	move.w	d5,d7
.ck:	cmp.w	(a5)+,d0
	blt	.part
	addq.w	#1,d7
	cmp.w	d6,d7
	bls	.ck
	; every band draws it: whole
	moveq	#0,d5
	move.w	d4,d6
	subq.w	#1,d6
	bsr	mo_record
	bra	.r
.part:	; some bands only: the rows of each band that does
	lea	mo_bstart,a5
.pk:	move.w	d5,d7
	add.w	d7,d7
	cmp.w	(a5,d7.w),d0
	blt	.pn
	movem.w	d0/d5-d6,-(sp)
	move.w	d5,d7
	lsl.w	#3,d7
	sub.w	mo_e,d7			; the band's first line
	move.w	d7,d5
	addq.w	#7,d7			; its last
	bsr	mo_lines		; -> rows d5 .. d6 of the object in those lines
	bmi	.pz
	bsr	mo_record
.pz:	movem.w	(sp)+,d0/d5-d6
.pn:	addq.w	#1,d5
	cmp.w	d6,d5
	bls	.pk
	bra	.r
.done:	rts

; mo_front_walk: band start d1 is not on the chain: walked until an entry of the chain; when that is the chain's
; first entry, the walked ones go in front of it (Z set), else Z clear.  Keeps d5/d7/a0-a2/a4/a5.
mo_front_walk:
	movem.l	d1/d7/a5,-(sp)
	lea	mo_walk,a5
	moveq	#0,d6
.w:	move.w	d1,d0
	add.w	d0,d0
	cmp.w	(a1,d0.w),d5
	beq	.hit
	move.w	d5,(a1,d0.w)
	move.w	#$7fff,(a2,d0.w)	; (walked now: no position yet)
	move.w	d1,(a5)+
	addq.w	#1,d6
	move.w	(a0,d0.w),d1
	and.w	#$3ff,d1
	bra	.w
.hit:	cmp.w	#$7fff,(a2,d0.w)
	beq	.no			; (a loop of its own)
	lea	mo_order+2048,a3
	move.w	mo_front,d2
	add.w	d2,d2
	sub.w	d2,a3
	cmp.w	(a3),d1
	bne	.no			; (it joins inside the chain)
	; the walked entries before the chain's first: positions first - 1, first - 2, ... from the last walked one
	move.w	(a2,d0.w),d2		; the first's position
.pf:	subq.w	#1,d6
	bmi	.ok
	move.w	-(a5),d1
	move.w	d1,-(a3)
	subq.w	#1,d2
	move.w	d1,d0
	add.w	d0,d0
	move.w	d2,(a2,d0.w)
	addq.w	#1,mo_front
	bra	.pf
.ok:	movem.l	(sp)+,d1/d7/a5
	moveq	#0,d0			; (Z set)
	rts
.no:	movem.l	(sp)+,d1/d7/a5
	moveq	#1,d0			; (Z clear)
	rts

; mo_general: every visible band walked from its SLIP entry; each object's rows in the band
mo_general:
	clr.w	mo_n
	lea	mo_recs,a6
	moveq	#0,d7			; k
.bk:	addq.w	#1,mo_stamp		; (a new walk)
	bne	.st
	lea	mo_stamps,a1
	move.w	#1024/2-1,d0
.cs:	clr.l	(a1)+
	dbf	d0,.cs
	move.w	#1,mo_stamp
.st:	lea	mo_stamps,a1
	move.w	mo_stamp,d5
	move.w	mo_band0,d0
	add.w	d7,d0
	and.w	#63,d0
	add.w	d0,d0
	lea	ARC_VRAM+$5F80,a4
	move.w	(a4,d0.w),d1
	and.w	#$3ff,d1
.w:	move.w	d1,d0
	add.w	d0,d0
	cmp.w	(a1,d0.w),d5
	beq	.nk
	move.w	d5,(a1,d0.w)
	movem.l	d1/d5/d7/a0-a1,-(sp)
	bsr	mo_place_memo
	beq	.nv
	move.w	d7,d5
	lsl.w	#3,d5
	sub.w	mo_e,d5			; the band's lines
	move.w	d5,d7
	addq.w	#7,d7
	bsr	mo_lines
	bmi	.nv
	bsr	mo_record
.nv:	movem.l	(sp)+,d1/d5/d7/a0-a1
	lea	ARC_VRAM+$3800,a0
	move.w	d1,d0
	add.w	d0,d0
	move.w	(a0,d0.w),d1
	and.w	#$3ff,d1
	bra	.w
.nk:	addq.w	#1,d7
	cmp.w	mo_nb,d7
	blo	.bk
	rts

; mo_place_memo: mo_place once a picture per entry (the general way meets an entry in every band that lists it)
mo_place_memo:
	move.w	d1,d0
	add.w	d0,d0
	lea	mp_stamp,a0
	move.w	mo_pstamp,d2
	cmp.w	(a0,d0.w),d2
	beq	.known
	move.w	d2,(a0,d0.w)
	lea	ARC_VRAM+$3000,a0
	lea	ARC_VRAM+$2800,a1
	bsr	mo_place
	sne	d0
	move.w	d1,d5
	lsl.w	#3,d5
	lea	mp_data,a0
	add.w	d5,a0			; (8 bytes an entry: x, y, lines, visible)
	move.w	d2,(a0)+
	move.w	d3,(a0)+
	move.w	d4,(a0)+
	move.b	d0,(a0)
	tst.b	d0
	rts
.known:	lea	mp_data,a0
	lsl.w	#2,d0
	add.w	d0,a0
	move.w	(a0)+,d2
	move.w	(a0)+,d3
	move.w	(a0)+,d4
	tst.b	(a0)
	rts

; mo_place: entry d1 (a0 = the y plane ARC_VRAM + $3000, a1 = the x plane + $2800): d2 = its x, d3 = its y (MAME's
; wrap: y >= 240 is y - 512, x >= 336 x - 512), d4 = its lines; Z set when no part of it is visible (left of the maze,
; in the gap at 232-239, right of the panel, above or below).  Keeps d1/d5-d7/a0-a6.
mo_place:
	move.w	d1,d0
	add.w	d0,d0
	move.w	(a0,d0.w),d4		; y 7-15, flip 6, width - 1 3-5, height - 1 0-2
	move.w	d4,d3
	lsr.w	#7,d3
	neg.w	d3
	sub.w	sy,d3
	and.w	#511,d3			; t = y + lines (mod 512): visible when 0 < t < 240 + lines
	beq	.no
	cmp.w	#240+64,d3
	bhs	.no
	moveq	#7,d2
	and.w	d4,d2
	addq.w	#1,d2
	lsl.w	#3,d2			; the lines
	sub.w	d2,d3			; y (-64 .. 239)
	cmp.w	#240,d3
	bge	.no
	lsr.w	#3,d4
	and.w	#7,d4
	addq.w	#1,d4
	lsl.w	#3,d4			; the width
	move.w	d2,-(sp)		; (the lines)
	move.w	(a1,d0.w),d2
	lsr.w	#7,d2
	sub.w	mo_xs,d2
	and.w	#511,d2
	cmp.w	#336,d2
	blo	.x
	sub.w	#512,d2
.x:	move.w	d2,d0
	add.w	d4,d0			; its right end
	cmp.w	#8,d0
	ble	.no2
	cmp.w	#232,d2
	blt	.yes
	cmp.w	#240,d0
	ble	.no2			; (in the gap)
	tst.w	panel_open
	beq	.no2			; (only the panel: under its characters)
	cmp.w	#336,d2
	bge	.no2
.yes:	move.w	(sp)+,d4
	moveq	#1,d0			; (Z clear)
	rts
.no2:	move.w	(sp)+,d4
.no:	moveq	#0,d0
	rts

; mo_lines: the object at y d3 (d4 lines): its rows in the picture's lines d5 .. d7 (clipped to 0-239) -> rows d5 .. d6;
; N when none
mo_lines:
	tst.w	d5
	bpl	.a
	moveq	#0,d5
.a:	cmp.w	#239,d7
	ble	.b
	move.w	#239,d7
.b:	sub.w	d3,d5
	bpl	.c
	moveq	#0,d5
.c:	move.w	d7,d6
	sub.w	d3,d6
	move.w	d4,d0
	subq.w	#1,d0
	cmp.w	d0,d6
	ble	.d
	move.w	d0,d6
.d:	cmp.w	d5,d6
	rts				; (N: d6 < d5)

; mo_record: a record of entry d1 at d2, d3, rows d5 .. d6 into a6 (keeps d0-d7)
mo_record:
	cmp.w	#MO_RECS,mo_n
	bhs	.full
	addq.w	#1,mo_n
	move.l	a0,-(sp)
	lea	ARC_VRAM+$2000,a0
	move.w	d1,-(sp)
	add.w	d1,d1
	move.w	(a0,d1.w),(a6)+		; MR_CODE
	lea	$800(a0),a0
	move.w	(a0,d1.w),(a6)+		; MR_W1
	lea	$800(a0),a0
	move.w	(a0,d1.w),(a6)+		; MR_W2
	move.w	(sp)+,d1
	move.l	(sp)+,a0
	move.w	d2,(a6)+
	move.w	d3,(a6)+
	move.w	d5,(a6)+
	move.w	d6,(a6)+
.full:	rts

; mo_draw: the records into the work ring (those in the maze)
mo_draw:
	lea	mo_recs,a6
	move.w	mo_n,d7
	bra	.n
.r:	move.w	MR_X(a6),d0
	cmp.w	#232,d0
	bge	.nx
	movem.l	d7/a6,-(sp)
	bsr	mo_object
	movem.l	(sp)+,d7/a6
.nx:	lea	MR_SIZE(a6),a6
.n:	dbf	d7,.r
	rts

; mo_object: record a6 into the target (tg_*): its strips of up to 32 pixels (4 tiles), each a baked image
mo_object:
	move.w	MR_W2(a6),d0
	lsr.w	#3,d0
	and.w	#7,d0
	addq.w	#1,d0
	move.w	d0,ob_w			; tiles across
	move.w	MR_W2(a6),d0
	and.w	#7,d0
	addq.w	#1,d0
	move.w	d0,ob_h
	clr.w	ob_strip
.strip:	move.w	ob_w,d0
	move.w	ob_strip,d1
	lsl.w	#2,d1
	sub.w	d1,d0			; tiles left
	ble	.done
	cmp.w	#4,d0
	bls	.tw
	moveq	#4,d0
.tw:	move.w	d0,ob_tw
	bsr	mo_image		; -> a0
	move.w	MR_X(a6),d4
	add.w	tg_r0,d4
	move.w	ob_strip,d0
	lsl.w	#5,d0
	add.w	d0,d4			; the strip's pixel in the target
	move.w	MR_Y(a6),d5
	add.w	tg_t,d5			; the object's first line in the target
	move.l	a6,-(sp)
	bsr	mo_strip_draw
	move.l	(sp)+,a6
	addq.w	#1,ob_strip
	bra	.strip
.done:	rts

; mo_image: record a6's strip ob_strip (ob_tw tiles) baked -> a0 (found by its key, else made)
mo_image:
	move.w	MR_CODE(a6),d1
	and.w	#$7fff,d1
	eor.w	#$0800,d1
	moveq	#0,d2
	move.w	d1,d2			; key: the code 0-14
	moveq	#15,d0
	and.w	MR_W1(a6),d0		; the palette
	move.w	d0,ob_pal
	lea	mo_epoch,a0
	moveq	#0,d3
	move.b	(a0,d0.w),d3
	lsl.w	#4,d3
	or.w	d0,d3			; epoch << 4 | palette
	swap	d3
	lsl.l	#3,d3			; (bits 19-30)
	or.l	d3,d2
	tst.w	ob_strip
	beq	.s0
	bset	#31,d2
.s0:	moveq	#$3f,d3
	and.w	MR_W2(a6),d3		; key 2: width - 1, height - 1
	btst	#6,MR_W2+1(a6)
	beq	.f
	bset	#6,d3
.f:	; the slot: (code ^ code >> 6 ^ palette << 7 ^ size << 3) & 2047
	move.w	d1,d0
	lsr.w	#6,d0
	eor.w	d1,d0
	move.w	ob_pal,d4
	lsl.w	#7,d4
	eor.w	d4,d0
	move.w	d3,d4
	lsl.w	#3,d4
	eor.w	d4,d0
	and.w	#MO_HASH_N-1,d0
	move.w	d0,d6			; (the first slot)
	moveq	#8-1,d5
.probe:	move.w	d0,d4
	mulu	#12,d4
	lea	MO_HASH,a0
	add.l	d4,a0
	cmp.l	(a0),d2
	bne	.nx
	cmp.l	4(a0),d3
	bne	.nx
	move.l	8(a0),a0
	rts
.nx:	cmp.l	#-1,(a0)
	beq	.empty
	addq.w	#1,d0
	and.w	#MO_HASH_N-1,d0
	dbf	d5,.probe
	move.w	d6,d0			; (no room: the first slot taken over)
	move.w	d0,d4
	mulu	#12,d4
	lea	MO_HASH,a0
	add.l	d4,a0
.empty:	; room in the pool?  (an image: 8 + 8 rows + 8 sw rows bytes at most: 8 + 8 * 64 + 16 * 64)
	move.l	mo_pool,d4
	add.l	#8+8*64+16*64,d4
	cmp.l	#SPR_POOL_END,d4
	blo	.room
	movem.l	d2-d3,-(sp)
	bsr	mo_flush
	movem.l	(sp)+,d2-d3
	bra	mo_image		; (again, in the empty table)
.room:	move.l	d2,(a0)
	move.l	d3,4(a0)
	move.l	mo_pool,8(a0)
	move.l	mo_pool,a0
	movem.l	a0/a6,-(sp)
	bsr	mo_bake
	movem.l	(sp)+,a0/a6
	rts

; mo_flush: every baked image forgotten
mo_flush:
	lea	MO_HASH,a0
	move.w	#MO_HASH_N*3-1,d0
	moveq	#-1,d1
.c:	move.l	d1,(a0)+
	dbf	d0,.c
	move.l	#SPR_POOL,mo_pool
	rts

; mo_bake: record a6's strip into a0: rows.w, sw.w (source words a row: 1 or 2), tw.w, -; the rows' opaque masks
; (longs: pixels not 0 or 1, the first pixel bit 31), their shadow masks (pixels 1); the opaque rows' plane words
; (plane 0's sw words, plane 1's, ...: the Blitter's source runs on through them).  Advances mo_pool.
mo_bake:
	move.w	ob_pal,d0
	add.w	#16,d0
	bsr	lut_need
	lea	LUTS+16*2048,a2
	move.w	ob_pal,d0
	moveq	#11,d1
	lsl.w	d1,d0
	add.w	d0,a2			; the palette's table
	btst	#6,MR_W2+1(a6)
	sne	ob_flip
	beq	.nf
	lea	1024(a2),a2		; (mirrored)
.nf:	move.w	ob_h,d0
	lsl.w	#3,d0
	move.w	d0,(a0)			; rows
	clr.w	6(a0)			; (MO_ORDER: the sorted rows' offset)
	move.l	a0,ob_img
	move.w	d0,ob_rows
	move.w	ob_tw,d1
	addq.w	#1,d1
	lsr.w	#1,d1
	move.w	d1,2(a0)		; sw
	move.w	d1,ob_sw
	move.w	ob_tw,4(a0)
	lea	8(a0),a3		; the opaque masks
	move.w	d0,d1
	add.w	d1,d1
	add.w	d1,d1
	lea	(a3,d1.w),a4		; the shadow masks
	lea	(a4,d1.w),a5		; the data
	move.w	MR_CODE(a6),d0
	and.w	#$7fff,d0
	eor.w	#$0800,d0
	move.w	d0,ob_code
	clr.w	ob_ty
.ty:	; the tiles of this tile row: t(j) = code + ty * w + (flip ? w - 1 - tx : tx), tx = 4 strip + j
	moveq	#0,d7			; r
.r:	moveq	#0,d5			; the opaque mask
	moveq	#0,d6			; the shadow mask
	lea	ob_row,a1
	clr.l	(a1)
	clr.l	4(a1)
	clr.l	8(a1)
	clr.l	12(a1)
	moveq	#0,d4			; j
.j:	move.w	ob_strip,d0
	lsl.w	#2,d0
	add.w	d4,d0			; tx
	tst.b	ob_flip
	beq	.nfl
	neg.w	d0
	add.w	ob_w,d0
	subq.w	#1,d0
.nfl:	move.w	ob_ty,d1
	mulu	ob_w,d1
	add.w	d1,d0
	add.w	ob_code,d0
	and.w	#$1fff,d0		; the tile
	moveq	#0,d1
	move.w	d0,d1
	lsl.l	#4,d1			; (16 bytes of masks a tile)
	lea	tile_masks,a0
	add.l	d1,a0
	move.w	d7,d1
	add.w	d1,d1
	add.w	d1,a0
	moveq	#0,d2
	move.b	(a0)+,d2		; opaque
	moveq	#0,d3
	move.b	(a0),d3			; shadow
	tst.b	ob_flip
	beq	.nm
	lea	bitrev,a0
	move.b	(a0,d2.w),d2
	move.b	(a0,d3.w),d3
.nm:	moveq	#24,d1
	move.w	d4,-(sp)
	lsl.w	#3,d4
	sub.w	d4,d1
	move.w	(sp)+,d4
	lsl.l	d1,d2
	lsl.l	d1,d3
	or.l	d2,d5
	or.l	d3,d6
	; the pixels: 4 bytes through the table (mirrored: in reverse) -> 4 plane bytes
	ext.l	d0
	lsl.l	#5,d0
	lea	tile_px,a0
	add.l	d0,a0
	move.w	d7,d0
	lsl.w	#2,d0
	add.w	d0,a0
	tst.b	ob_flip
	bne	.mir
	moveq	#0,d1
	move.b	(a0)+,d1
	add.w	d1,d1
	add.w	d1,d1
	move.l	(a2,d1.w),d0
	lsl.l	#2,d0
	moveq	#0,d1
	move.b	(a0)+,d1
	add.w	d1,d1
	add.w	d1,d1
	or.l	(a2,d1.w),d0
	lsl.l	#2,d0
	moveq	#0,d1
	move.b	(a0)+,d1
	add.w	d1,d1
	add.w	d1,d1
	or.l	(a2,d1.w),d0
	lsl.l	#2,d0
	moveq	#0,d1
	move.b	(a0)+,d1
	add.w	d1,d1
	add.w	d1,d1
	or.l	(a2,d1.w),d0
	bra	.put
.mir:	addq.l	#4,a0
	moveq	#0,d1
	move.b	-(a0),d1
	add.w	d1,d1
	add.w	d1,d1
	move.l	(a2,d1.w),d0
	lsl.l	#2,d0
	moveq	#0,d1
	move.b	-(a0),d1
	add.w	d1,d1
	add.w	d1,d1
	or.l	(a2,d1.w),d0
	lsl.l	#2,d0
	moveq	#0,d1
	move.b	-(a0),d1
	add.w	d1,d1
	add.w	d1,d1
	or.l	(a2,d1.w),d0
	lsl.l	#2,d0
	moveq	#0,d1
	move.b	-(a0),d1
	add.w	d1,d1
	add.w	d1,d1
	or.l	(a2,d1.w),d0
.put:	; plane k's byte at k * 2 sw + j
	lea	ob_row,a0
	add.w	d4,a0
	move.w	ob_sw,d1
	add.w	d1,d1			; (2 sw)
	rol.l	#8,d0
	move.b	d0,(a0)
	add.w	d1,a0
	rol.l	#8,d0
	move.b	d0,(a0)
	add.w	d1,a0
	rol.l	#8,d0
	move.b	d0,(a0)
	add.w	d1,a0
	rol.l	#8,d0
	move.b	d0,(a0)
	addq.w	#1,d4
	cmp.w	ob_tw,d4
	blo	.j
	move.l	d5,(a3)+
	move.l	d6,(a4)+
	tst.l	d5
	beq	.nd
	lea	ob_row,a0		; (the row's data: 8 sw bytes)
	move.l	(a0)+,(a5)+
	move.l	(a0)+,(a5)+
	cmp.w	#1,ob_sw
	beq	.nd
	move.l	(a0)+,(a5)+
	move.l	(a0)+,(a5)+
.nd:	addq.w	#1,d7
	cmp.w	#8,d7
	blo	.r
	addq.w	#1,ob_ty
	move.w	ob_ty,d0
	cmp.w	ob_h,d0
	blo	.ty
	ifd MO_ORDER
	bsr	mo_sort
	endc
	move.l	a5,d0
	addq.l	#3,d0
	and.w	#$fffc,d0
	move.l	d0,mo_pool
	rts

	ifd MO_ORDER
; mo_sort (MO_ORDER=1, docs/sprite-preparation.md's reordered source): after the image's data (a5), its opaque rows
; sorted by their mask (equal masks together): count.w, -.w, (mask.l, the row's ring offset row * STRIDE.l) each, then
; their plane words in that order (the source runs on).  Advances a5.
mo_sort:
	move.l	ob_img,a0
	move.l	a5,d0
	sub.l	a0,d0
	move.w	d0,6(a0)		; (the section's offset)
	move.w	(a0),d7			; rows
	lea	8(a0),a1		; the masks
	move.w	d7,d0
	lsl.w	#3,d0
	lea	8(a0,d0.w),a2		; the data (natural order)
	move.w	2(a0),d6
	lsl.w	#3,d6			; a row's bytes
	; the opaque rows: (mask, row, data) into ob_sort, inserted in mask order (stable)
	lea	ob_sort,a3
	moveq	#0,d5			; the count
	moveq	#0,d4			; the row
.r:	move.l	(a1)+,d0
	beq	.nr
	; insert at the first entry with a larger mask
	move.w	d5,d1
	mulu	#12,d1
	lea	(a3,d1.w),a4		; (the end)
.ins:	cmp.l	a3,a4
	bls	.put
	cmp.l	-12(a4),d0
	bhs	.put
	move.l	-12(a4),(a4)
	move.l	-8(a4),4(a4)
	move.l	-4(a4),8(a4)
	lea	-12(a4),a4
	bra	.ins
.put:	move.l	d0,(a4)
	move.w	d4,d1
	mulu	#STRIDE,d1
	move.l	d1,4(a4)
	move.l	a2,8(a4)
	add.w	d6,a2
	addq.w	#1,d5
.nr:	addq.w	#1,d4
	cmp.w	d7,d4
	blo	.r
	move.w	d5,(a5)+
	clr.w	(a5)+
	move.w	d5,d0
	bra	.e1
.em:	move.l	(a3)+,(a5)+
	move.l	(a3)+,(a5)+
	addq.l	#4,a3
.e1:	dbf	d0,.em
	lea	ob_sort,a3
	move.w	d5,d0
	bra	.d1
.dm:	move.l	8(a3),a2
	move.w	d6,d1
	lsr.w	#2,d1
	subq.w	#1,d1
.dc:	move.l	(a2)+,(a5)+
	dbf	d1,.dc
	lea	12(a3),a3
.d1:	dbf	d0,.dm
	rts
	endc

; mo_strip_draw: image a0 (record a6's rows MR_R0 .. MR_R1) at the target's pixel d4.w, line d5.w: a HOG pass a row
; (Y count 4: the planes; X count 1-3 words; END1-END3 the row's opaque mask shifted, written when it changes; the
; source runs on), then the shadow rows: P' at the same place, through the shadow mask
mo_strip_draw:
	move.w	MR_R0(a6),d6		; the first row
	move.w	MR_R1(a6),d7		; the last
	moveq	#15,d3
	and.w	d4,d3			; s
	move.w	d3,ob_s
	move.w	4(a0),d0
	lsl.w	#3,d0			; W
	add.w	d3,d0
	subq.w	#1,d0
	lsr.w	#4,d0
	addq.w	#1,d0			; n: the destination words
	move.w	d0,ob_n
	; the damage: columns d4 >> 4 .. + n, lines d5 + r0 .. + r1
	tst.b	tg_dmg
	beq	.nd
	movem.l	d0-d7/a0,-(sp)
	move.w	d0,d1
	move.w	d4,d0
	asr.w	#4,d0
	move.w	d5,d2
	add.w	d6,d2
	move.w	d7,d3
	sub.w	d6,d3
	addq.w	#1,d3
	bsr	dmg_add
	movem.l	(sp)+,d0-d7/a0
.nd:	; the first row's destination
	moveq	#0,d1
	move.w	d5,d1
	add.w	d6,d1
	move.w	d1,ob_line
	mulu	tg_stride,d1
	move.w	d4,d2
	asr.w	#4,d2
	move.w	d2,ob_col
	ext.l	d2
	lsl.l	#3,d2
	add.l	d2,d1
	add.l	work_base,d1
	move.l	d1,ob_dest
	; the source: the opaque rows before r0 skipped
	move.w	(a0),d2			; rows
	lea	8(a0),a1		; the opaque masks
	move.w	d2,d1
	lsl.w	#3,d1
	lea	8(a0,d1.w),a2		; the data
	move.w	2(a0),d1
	lsl.w	#3,d1			; 8 sw: a row's bytes
	move.w	d1,ob_rowb
	move.w	d6,d0
	bra	.sk
.sr:	tst.l	(a1)+
	beq	.sk
	add.w	d1,a2
.sk:	dbf	d0,.sr
	move.l	a0,-(sp)
	; the Blitter: HOP 2 OP 3, source X / Y increment 2, destination X increment 8, Y increment back to the next plane
	move.w	#2,BLT_SXI.w
	move.w	#2,BLT_SYI.w
	move.w	#8,BLT_DXI.w
	move.w	ob_n,d0
	move.w	d0,BLT_XC.w
	subq.w	#1,d0
	lsl.w	#3,d0
	moveq	#2,d1
	sub.w	d0,d1
	move.w	d1,BLT_DYI.w
	move.w	#$0203,BLT_HOP.w
	move.w	#$ffff,BLT_E2.w
	move.l	a2,BLT_SRC.w
	move.w	ob_s,d2
	or.w	#$c000,d2		; BUSY, HOG, the skew
	move.w	ob_n,d0
	cmp.w	2(a0),d0
	bls	.nn
	or.w	#$0040,d2		; NFSR (the source X and Y increments are equal: the Blitter's ways agree)
.nn:	move.l	ob_dest,a5
	moveq	#0,d5
	move.w	tg_stride,d5
	ifd MO_ORDER
	tst.w	6(a0)			; (whole, into the ring: the sorted rows)
	beq	.nat
	tst.w	MR_R0(a6)
	bne	.nat
	move.w	(a0),d0
	subq.w	#1,d0
	cmp.w	MR_R1(a6),d0
	bne	.nat
	cmp.w	#STRIDE,d5
	beq	mo_sorted_draw
.nat:
	endc
	moveq	#-1,d4			; (the last mask: none)
	move.w	ob_s,d3
	moveq	#16,d1
	sub.w	d3,d1			; 16 - s
	lea	BLT_DST.w,a2
	lea	BLT_YC.w,a3
	lea	BLT_CTRL.w,a4
	move.w	ob_n,d0
	subq.w	#2,d0
	bmi	.one
	beq	.two
	; three words: END1 END2 END3 = (m >> s) high, low, m << (16 - s)
	sub.w	d6,d7
.r3:	move.l	(a1)+,d0
	beq	.n3
	cmp.l	d0,d4
	beq	.g3
	move.l	d0,d4
	move.w	d0,d6
	lsl.w	d1,d6
	move.w	d6,BLT_E3.w
	lsr.l	d3,d0
	move.w	d0,BLT_E2.w
	swap	d0
	move.w	d0,BLT_E1.w
.g3:	move.l	a5,(a2)
	move.w	#4,(a3)
	move.w	d2,(a4)
.n3:	add.l	d5,a5
	dbf	d7,.r3
	bra	.shadow
.two:	sub.w	d6,d7
.r2:	move.l	(a1)+,d0
	beq	.n2
	cmp.l	d0,d4
	beq	.g2
	move.l	d0,d4
	lsr.l	d3,d0
	move.w	d0,BLT_E3.w
	swap	d0
	move.w	d0,BLT_E1.w
.g2:	move.l	a5,(a2)
	move.w	#4,(a3)
	move.w	d2,(a4)
.n2:	add.l	d5,a5
	dbf	d7,.r2
	bra	.shadow
.one:	sub.w	d6,d7
.r1:	move.l	(a1)+,d0
	beq	.n1
	cmp.l	d0,d4
	beq	.g1
	move.l	d0,d4
	lsr.l	d3,d0
	swap	d0
	move.w	d0,BLT_E1.w
.g1:	move.l	a5,(a2)
	move.w	#4,(a3)
	move.w	d2,(a4)
.n1:	add.l	d5,a5
	dbf	d7,.r1
.shadow:
	move.l	(sp)+,a0
mo_strip_shadow:
	; the shadow rows: source P' (its line (line - tg_pline) & 511, column (col - tg_pcol) & 31), no skew
	move.w	(a0),d0
	lsl.w	#2,d0
	lea	8(a0,d0.w),a1		; the shadow masks
	move.w	MR_R0(a6),d6
	move.w	MR_R1(a6),d7
	move.w	d6,d0
	lsl.w	#2,d0
	add.w	d0,a1
	sub.w	d6,d7
	move.l	ob_dest,a5
	move.w	ob_line,d6		; the line
	; P' does not wrap inside the rows (the usual case): the source advances a line a row
	move.w	ob_col,d0
	sub.w	tg_pcol,d0
	and.w	#31,d0
	move.w	d0,d2
	add.w	ob_n,d2
	cmp.w	#32,d2
	bls	shadow_fast
	sf	ob_shset
.sh:	move.l	(a1)+,d0
	bne	.sdo
.sn:	add.l	d5,a5
	addq.w	#1,d6
	dbf	d7,.sh
	rts
.sdo:	movem.l	d1-d7/a1,-(sp)
	tst.b	ob_shset
	bne	.ss
	st	ob_shset
	move.w	#8,BLT_SXI.w
	move.w	BLT_DYI.w,BLT_SYI.w	; (2 - (n - 1) 8: the next plane)
	clr.b	BLT_SKEW.w
.ss:	; the masks
	move.w	ob_n,d4
	cmp.w	#1,d4
	bne	.s2
	lsr.l	d3,d0
	swap	d0
	move.w	d0,BLT_E1.w
	bra	.sm
.s2:	cmp.w	#2,d4
	bne	.s3
	lsr.l	d3,d0
	move.w	d0,BLT_E3.w
	swap	d0
	move.w	d0,BLT_E1.w
	bra	.sm
.s3:	move.w	d0,d2
	lsl.w	d1,d2
	move.w	d2,BLT_E3.w
	lsr.l	d3,d0
	move.w	d0,BLT_E2.w
	swap	d0
	move.w	d0,BLT_E1.w
.sm:	; the source
	move.w	d6,d0
	sub.w	tg_pline,d0
	and.w	#511,d0
	moveq	#0,d1
	move.w	d0,d1
	lsl.l	#8,d1
	move.w	ob_col,d0
	sub.w	tg_pcol,d0
	and.w	#31,d0
	move.w	d0,d2
	add.w	d4,d2
	cmp.w	#32,d2
	bhi	.wrap
	lsl.w	#3,d0
	add.w	d0,d1
	add.l	#PFS,d1
	move.l	d1,BLT_SRC.w
	move.l	a5,BLT_DST.w
	move.w	d4,BLT_XC.w
	move.w	#4,BLT_YC.w
	move.w	#$c000,BLT_CTRL.w
	movem.l	(sp)+,d1-d7/a1
	bra	.sn
.wrap:	; (P' wraps inside the row: a word a pass)
	move.l	d1,d7			; (the line's offset)
	move.w	d0,d6			; P's column
	move.l	a5,a1
	move.w	BLT_E1.w,ob_em
	move.w	BLT_E2.w,ob_em+2
	move.w	BLT_E3.w,ob_em+4
	lea	ob_em,a2
	move.w	#2,BLT_SYI.w
	move.w	#2,BLT_DYI.w
	move.w	#1,BLT_XC.w
	moveq	#0,d2			; the word
.ww:	moveq	#0,d0			; its mask: the first END1, the last END3, else END2
	tst.w	d2
	beq	.w1
	moveq	#2,d0
	move.w	d4,d1
	subq.w	#1,d1
	cmp.w	d1,d2
	bne	.w1
	moveq	#4,d0
.w1:	move.w	(a2,d0.w),BLT_E1.w
	move.l	d7,d1
	move.w	d6,d0
	and.w	#31,d0
	lsl.w	#3,d0
	add.w	d0,d1
	add.l	#PFS,d1
	move.l	d1,BLT_SRC.w
	move.l	a1,BLT_DST.w
	move.w	#4,BLT_YC.w
	move.w	#$c000,BLT_CTRL.w
	addq.l	#8,a1
	addq.w	#1,d6
	addq.w	#1,d2
	cmp.w	d4,d2
	blo	.ww
	move.w	ob_n,d0			; (the row passes' increments again)
	subq.w	#1,d0
	lsl.w	#3,d0
	moveq	#2,d1
	sub.w	d0,d1
	move.w	d1,BLT_DYI.w
	move.w	d1,BLT_SYI.w
	move.w	ob_em+2,BLT_E2.w
	movem.l	(sp)+,d1-d7/a1
	bra	.sn

	ifd MO_ORDER
; mo_sorted_draw: the sorted rows of image a0 (ob_dest the row 0's address; the registers as mo_strip_draw's): the
; END masks written when the mask changes, the source runs on through the sorted data
mo_sorted_draw:
	move.w	6(a0),d0
	lea	(a0,d0.w),a1
	move.w	(a1),d7			; the rows
	addq.l	#4,a1
	move.w	d7,d0
	lsl.w	#3,d0
	lea	(a1,d0.w),a2
	move.l	a2,BLT_SRC.w
	move.l	a5,d6			; (row 0)
	moveq	#-1,d4
	move.w	ob_s,d3
	moveq	#16,d1
	sub.w	d3,d1
	lea	BLT_DST.w,a2
	lea	BLT_YC.w,a3
	lea	BLT_CTRL.w,a4
	move.w	ob_n,d0
	subq.w	#1,d7
	bmi	.done
	subq.w	#2,d0
	bmi	.one
	beq	.two
.r3:	move.l	(a1)+,d0
	cmp.l	d0,d4
	beq	.g3
	move.l	d0,d4
	move.w	d0,d5
	lsl.w	d1,d5
	move.w	d5,BLT_E3.w
	lsr.l	d3,d0
	move.w	d0,BLT_E2.w
	swap	d0
	move.w	d0,BLT_E1.w
.g3:	move.l	(a1)+,d5
	add.l	d6,d5
	move.l	d5,(a2)
	move.w	#4,(a3)
	move.w	d2,(a4)
	dbf	d7,.r3
	bra	.done
.two:
.r2:	move.l	(a1)+,d0
	cmp.l	d0,d4
	beq	.g2
	move.l	d0,d4
	lsr.l	d3,d0
	move.w	d0,BLT_E3.w
	swap	d0
	move.w	d0,BLT_E1.w
.g2:	move.l	(a1)+,d5
	add.l	d6,d5
	move.l	d5,(a2)
	move.w	#4,(a3)
	move.w	d2,(a4)
	dbf	d7,.r2
	bra	.done
.one:
.r1:	move.l	(a1)+,d0
	cmp.l	d0,d4
	beq	.g1
	move.l	d0,d4
	lsr.l	d3,d0
	swap	d0
	move.w	d0,BLT_E1.w
.g1:	move.l	(a1)+,d5
	add.l	d6,d5
	move.l	d5,(a2)
	move.w	#4,(a3)
	move.w	d2,(a4)
	dbf	d7,.r1
.done:	; the shadow rows as mo_strip_draw's (the registers it expects)
	moveq	#0,d5
	move.w	tg_stride,d5
	moveq	#16,d1
	sub.w	d3,d1
	move.l	(sp)+,a0
	bra	mo_strip_shadow
	endc

; shadow_fast: the shadow rows of mo_strip_draw (a1 the masks of row r0, d7 the rows - 1, a5 the destination, d6 its
; line, d0 P's column, d5 the stride, d3 s, d1 16 - s): P' a line further each row
SHROW	macro
.r\@:	move.l	(a1)+,d0
	beq	.n\@
	cmp.l	d0,d4
	beq	.g\@
	move.l	d0,d4
	if \1=1
	lsr.l	d3,d0
	swap	d0
	move.w	d0,BLT_E1.w
	endif
	if \1=2
	lsr.l	d3,d0
	move.w	d0,BLT_E3.w
	swap	d0
	move.w	d0,BLT_E1.w
	endif
	if \1=3
	move.w	d0,d2
	lsl.w	d1,d2
	move.w	d2,BLT_E3.w
	lsr.l	d3,d0
	move.w	d0,BLT_E2.w
	swap	d0
	move.w	d0,BLT_E1.w
	endif
.g\@:	move.l	a0,BLT_SRC.w
	move.l	a5,(a2)
	move.w	#4,(a3)
	move.w	#$c000,(a4)
.n\@:	add.l	d5,a5
	lea	256(a0),a0
	cmp.l	a6,a0
	blo	.w\@
	sub.l	#512*256,a0
.w\@:	dbf	d7,.r\@
	rts
	endm
shadow_fast:
	; anything to draw?
	move.l	a1,a0
	move.w	d7,d2
.any:	tst.l	(a0)+
	bne	.yes
	dbf	d2,.any
	rts
.yes:	lsl.w	#3,d0
	move.w	d6,d2
	sub.w	tg_pline,d2
	and.w	#511,d2
	moveq	#0,d4
	move.w	d2,d4
	lsl.l	#8,d4
	add.w	d0,d4
	add.l	#PFS,d4
	move.l	d4,a0			; P' at the first row
	move.l	#PFS+512*256,a6
	move.w	#8,BLT_SXI.w
	move.w	BLT_DYI.w,BLT_SYI.w	; (2 - (n - 1) 8: the next plane)
	clr.b	BLT_SKEW.w
	moveq	#-1,d4
	move.w	ob_n,d0
	cmp.w	#2,d0
	blo	.one
	beq	.two
	SHROW	3
.two:	SHROW	2
.one:	SHROW	1

; ---------------------------------------------------------------------------------------------------------------------
; panel_compose: the panel's characters are not all opaque (the title, the high scores): the arcade's x 240-335 of
; the playfield and the objects composed in PBUF (laid out as a ring: its column c shows P's column
; (c - pb_pcol) & 31, line l P's line (l - (64 - sy)) & 511; the objects drawn whole into its margins), then copied
; into the ring at the picture's x 224 (a shifted copy: a damage rectangle); the characters come on top after.
PB_STRIDE = 120				; 15 words: 4 margin, 7 for the 96 pixels at any shift, 4 margin
PB_LINES = 368
panel_compose:
	move.l	work_base,-(sp)
	move.l	#PBUF,work_base
	move.w	#PB_STRIDE,tg_stride
	move.w	snap_xs,d0
	add.w	#240,d0
	and.w	#511,d0
	move.w	d0,d1
	and.w	#15,d1
	add.w	#64,d1
	move.w	d1,pb_px		; PBUF's pixel of the arcade's x 240
	sub.w	#240,d1
	move.w	d1,tg_r0
	lsr.w	#4,d0
	moveq	#4,d1
	sub.w	d0,d1
	and.w	#31,d1
	move.w	d1,tg_pcol
	moveq	#64,d1
	sub.w	sy,d1
	move.w	d1,tg_pline
	move.w	#64,tg_t
	sf	tg_dmg
	; the playfield: columns 4-10, lines 64-303
	moveq	#4,d0
	moveq	#7,d1
	moveq	#64,d2
	move.w	#240,d3
	bsr	copy_rect
	; the objects there
	lea	mo_recs,a6
	move.w	mo_n,d7
	bra	.n
.r:	move.w	MR_W2(a6),d0
	lsr.w	#3,d0
	and.w	#7,d0
	addq.w	#1,d0
	lsl.w	#3,d0
	add.w	MR_X(a6),d0
	cmp.w	#240,d0
	ble	.nx
	movem.l	d7/a6,-(sp)
	bsr	mo_object
	movem.l	(sp)+,d7/a6
.nx:	lea	MR_SIZE(a6),a6
.n:	dbf	d7,.r
	move.l	(sp)+,work_base
	bsr	ring_target
	; PBUF's 96 pixels from pb_px, lines 64 .. into the ring at R0 + 224, T ..
	move.l	#PBUF+64*PB_STRIDE,sb_src
	move.w	#PB_STRIDE,sb_sstride
	move.w	pb_px,sb_spx
	move.l	work_base,d0
	moveq	#0,d1
	move.w	top_t,d1
	mulu	#STRIDE,d1
	add.l	d1,d0
	move.l	d0,sb_dst
	move.w	#STRIDE,sb_dstride
	move.w	r0px,d0
	add.w	#224,d0
	move.w	d0,sb_dpx
	move.w	#96,sb_w
	move.w	#240,sb_lines
	bsr	sblit
	move.w	r0px,d0			; (its damage: restored next time)
	add.w	#224,d0
	lsr.w	#4,d0
	moveq	#7,d1
	move.w	top_t,d2
	move.w	#240,d3
	bra	dmg_add

; sblit: a shifted copy of sb_w pixels x sb_lines lines from sb_src (pixel sb_spx of its first line, sb_sstride bytes a
; line) to sb_dst (pixel sb_dpx, sb_dstride), four interleaved planes: a pass per plane
sblit:
	move.w	sb_dpx,d4
	move.w	d4,d5
	add.w	sb_w,d5
	subq.w	#1,d5			; the last destination pixel
	moveq	#15,d6
	and.w	d4,d6
	moveq	#-1,d7
	lsr.w	d6,d7
	move.w	d7,BLT_E1.w
	moveq	#15,d6
	and.w	d5,d6
	sub.w	#15,d6
	neg.w	d6
	move.w	#$ffff,d7
	lsl.w	d6,d7
	move.w	d7,BLT_E3.w
	move.w	#$ffff,BLT_E2.w
	lsr.w	#4,d4			; the first destination word
	lsr.w	#4,d5
	move.w	d5,d6
	sub.w	d4,d6
	addq.w	#1,d6			; X count
	cmp.w	#1,d6
	bne	.x2
	move.w	BLT_E1.w,d7
	and.w	BLT_E3.w,d7
	move.w	d7,BLT_E1.w
.x2:	move.w	d6,BLT_XC.w
	; the skew: (dpx - spx) & 15; FXSR when (dpx & 15) < (spx & 15)
	move.w	sb_spx,d0
	moveq	#15,d1
	and.w	d0,d1			; spx & 15
	moveq	#15,d2
	and.w	sb_dpx,d2		; dpx & 15
	moveq	#0,d7
	move.w	d2,d7
	sub.w	d1,d7
	and.w	#15,d7			; the skew
	cmp.w	d1,d2
	bhs	.nf
	or.w	#$80,d7			; FXSR
.nf:	move.b	d7,BLT_SKEW.w
	move.w	d6,d1			; the source's reads a line: X count + FXSR (no NFSR)
	btst	#7,d7
	beq	.r1
	addq.w	#1,d1
.r1:	subq.w	#1,d1
	lsl.w	#3,d1
	move.w	sb_sstride,d7
	sub.w	d1,d7
	move.w	d7,BLT_SYI.w
	move.w	d6,d1
	subq.w	#1,d1
	lsl.w	#3,d1
	move.w	sb_dstride,d7
	sub.w	d1,d7
	move.w	d7,BLT_DYI.w
	moveq	#8,d7
	move.w	d7,BLT_SXI.w
	move.w	d7,BLT_DXI.w
	move.w	#$0203,BLT_HOP.w
	moveq	#0,d1
	move.w	d0,d1
	lsr.w	#4,d1
	lsl.l	#3,d1
	add.l	sb_src,d1		; the source
	moveq	#0,d0
	move.w	d4,d0
	lsl.l	#3,d0
	add.l	sb_dst,d0		; the destination
	; the lines a piece: 256 bus cycles / (4 x (the words + the reads + the two end masks' destination reads))
	move.w	d6,d2
	add.w	d6,d2
	addq.w	#2,d2
	btst	#7,BLT_SKEW.w
	beq	.pf
	addq.w	#1,d2
.pf:	moveq	#0,d3
	move.b	.access_lines(pc,d2.w),d3	; 64 / bus accesses per line
	tst.w	d3
	bne	.pn
	moveq	#1,d3
.pn:	moveq	#4-1,d5
.pl:	move.l	d1,BLT_SRC.w
	move.l	d0,BLT_DST.w
	move.w	sb_lines,BLT_YC.w
	move.l	d1,-(sp)
	move.w	d3,d1
	bsr	blit_go_lines
	move.l	(sp)+,d1
	addq.l	#2,d0
	addq.l	#2,d1
	dbf	d5,.pl
	rts


.access_lines:
	dc.b	64
	rept	64
	dc.b	64/(REPTN+1)
	endr
	even

	include	"sprite_code.s"

	section	data,data
	even
palette_data:	incbin	"palette.bin"
irgb_map:	incbin	"irgb_map.bin"
tile_px:	incbin	"tile_px.bin"
tile_pens:	incbin	"tile_pens.bin"
tile_masks:	incbin	"tile_masks.bin"
char_rows:	incbin	"char_rows.bin"
char_blank:	incbin	"char_blank.bin"
bitrev:		incbin	"bitrev.bin"
char_pens:	incbin	"char_pens.bin"	; per character: bit p set when it has a pixel p
nz4:		incbin	"nz4.bin"		; per byte of four 2-bit pixels: the pixels not 0 (the first the highest bit)
	even

	section	bss,bss
	even
shown_pal:	ds.w	16
black_pal:	ds.w	16
cur_ring:	ds.l	1
col_base:	ds.l	1
rf_vbls:	ds.l	1
snap_vbls:	ds.l	1
mo_pool:	ds.l	1
ob_dest:	ds.l	1
sb_src:		ds.l	1
sb_dst:		ds.l	1
ob_row:		ds.l	4
ob_img:		ds.l	1
ob_sort:	ds.b	12*64
work_base:	ds.l	1
flip_addr:	ds.l	1
al_counter:	ds.l	1
ring_index:	ds.w	1
col_rest:	ds.w	1
snap_tries:	ds.w	1
runs_version:	ds.w	1
ob_runs_v:	ds.w	1
ob_r0px:	ds.w	1
panel_open:	ds.w	1
tg_stride:	ds.w	1
tg_pcol:	ds.w	1
tg_pline:	ds.w	1
tg_r0:		ds.w	1
tg_t:		ds.w	1
pb_px:		ds.w	1
mo_n:		ds.w	1
mo_stamp:	ds.w	1
mo_e:		ds.w	1
mo_band0:	ds.w	1
mo_nb:		ds.w	1
mo_xs:		ds.w	1
mo_count:	ds.w	1
mo_front:	ds.w	1
mo_left:	ds.w	1
mo_nvis:	ds.w	1
map_n:		ds.w	1
mo_pstamp:	ds.w	1
ob_w:		ds.w	1
ob_h:		ds.w	1
ob_tw:		ds.w	1
ob_strip:	ds.w	1
ob_pal:		ds.w	1
ob_rows:	ds.w	1
ob_sw:		ds.w	1
ob_code:	ds.w	1
ob_ty:		ds.w	1
ob_s:		ds.w	1
ob_n:		ds.w	1
ob_line:	ds.w	1
ob_col:		ds.w	1
ob_rowb:	ds.w	1
ob_em:		ds.w	3
sb_sstride:	ds.w	1
sb_spx:		ds.w	1
sb_dstride:	ds.w	1
sb_dpx:		ds.w	1
sb_w:		ds.w	1
sb_lines:	ds.w	1
snap_xs:	ds.w	1
snap_ys:	ds.w	1
sx:		ds.w	1
sy:		ds.w	1
fine:		ds.w	1
w0:		ds.w	1
r0px:		ds.w	1
top_t:		ds.w	1
bank:		ds.w	1
last_bank:	ds.w	1
new_novl:	ds.w	1
bbox:		ds.w	4
orect:		ds.w	4
crect:		ds.w	4
set_mask:	ds.w	48
mo_epoch:	ds.b	16
lut_stale:	ds.b	32
	even
lut_tmp:	ds.l	40
pf_list_n:	ds.w	8
al_list_n:	ds.w	64
row_ver:	ds.l	30
frame_ready:	ds.b	1
flip_fine:	ds.b	1
tg_dmg:		ds.b	1
ob_flip:	ds.b	1
ob_shset:	ds.b	1
row_dirty:	ds.b	1
	even
runs_dirty:	ds.b	30
row_t2:		ds.b	30
	even
pen_map:	ds.b	768
pal_shadow:	ds.w	768
pf_shadow:	ds.w	4096
pf_listed:	ds.b	4096
al_shadow:	ds.w	30*64
al_type:	ds.b	AL_N
	even
al_voff:	ds.w	AL_N
al_listed:	ds.b	AL_N
row_runs:	ds.b	30*RR_SIZE
	even
new_ovl:	ds.b	OVL_MAX*OV_SIZE
mo_stamps:	ds.w	1024
mo_pos:		ds.w	1024
mo_order:	ds.w	2048+1024
mo_walk:	ds.w	1024
mo_vis:		ds.w	1024
map_tab:	ds.b	255*16
mp_stamp:	ds.w	1024
mp_data:	ds.w	4*1024
mo_bstart:	ds.w	32
mo_recs:	ds.b	MO_RECS*MR_SIZE
ring_state0:	ds.b	RS_SIZE
ring_state1:	ds.b	RS_SIZE
	section	text,code
