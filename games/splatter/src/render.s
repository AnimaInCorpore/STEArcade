; Splatterhouse's STE renderer: the arcade picture (288 x 224, the player's view: MAME's screen turned by the cabinet's
; ROT180 with the game's flip on) from the CUS123 / CUS116 / sprite state in `vio` (core.s).  See the README,
; "Renderer", for the design and the measurements; tools/render_test.py checks it against engine/namcos1.py.
;
; Interface (the main program):
;   render_init   once, after vio holds a state (registers: all kept)
;   render_frame  once per picture, any time between the game's frames (registers: all kept); draws into a buffer
;                 that is neither shown, nor the one shown before it (Hatari scans the old one once more), nor
;                 waiting, and then publishes it (ren_ready = buffer + 1).  Returns at once (ren_skipped + 1) when no
;                 buffer is free.
;   render_vbl    in the VBL (registers: all kept): shows a published buffer: video base and counter, fine scroll,
;                 line width, and the palette into ren_vbl_pal (the main program uses it as borders.s' shown_pal:
;                 `shown_pal = ren_vbl_pal`, BD_PALETTE = 1, PIC_TOP = the first picture line, PIC_LINES = 224).
;   needs blit_go (engine/rt/borders.s: borders_blit_go, borders_vars) and the label vio.
;
; Picture geometry: the screen is 320 pixels wide, the picture 288 at screen x 16-303 (the 16-pixel side bands show
; what the playfield has there: the arcade does not show it).  Each of the three buffers is a virtual screen of
; 1024 x 288 pixels (512 bytes a line): 32 guard lines, the picture's 224 lines, 32 guard lines.  The scroll layers
; that move together (the "group": layers 0-2 in play) are composed into it ONCE per change: tilemap column u is at
; buffer x = u and u + 512 (twin columns), so the window (buffer x W .. W+319, W = the group's scroll - 16) is
; complete wherever it is and the horizontal scroll costs nothing (the video address and the fine scroll register).
; Everything else is drawn per picture and put back from the twin columns at the buffer's next turn (the damage list),
; or, in the rows the fixed layers 4/5 cover completely (the HUD bars), copied from the bar image (ren_fi).

	ifnd	REN_NBUF
REN_NBUF	= 2			; display buffers (3: 147 KB more; a picture then need not wait a VBL after a flip)
	endc
REN_LINEB	= 512
REN_GUARD	= 32
REN_LINES	= REN_GUARD+224+REN_GUARD
REN_BUFSZ	= REN_LINES*REN_LINEB
REN_PIC		= REN_GUARD*REN_LINEB
REN_NCHR	= $C0000/64		; characters with data (higher codes: pens 0)
	ifnd	REN_DMG
REN_DMG		= 400			; damage rectangles a buffer (12 bytes)
	endc
REN_POOL	= 128*1024
REN_PTS		= 32			; the sprite colours' pair tables (1 KB each)		; the cache of converted sprites and overlay cells
REN_HASH	= 2048			; its slots (direct mapped: key, address)
REN_BUDGET	= 12			; group cells outside the window drawn a picture
REN_MAXPTS	= 1024			; colour samples (distinct pens)
REN_WAIT	= 6			; pictures a new scene waits at most for its palette to rest
REN_QPER	= 128			; pictures between the checks of the colours
	ifnd	REN_SPRW
REN_SPRW	= 2			; a sprite sample's weight (a tile cell's is 1)
	endc
FI_STRIDE	= 168			; the bar image: 21 groups (336 pixels; screen x 0-319 used)

V_C116		= $1800
V_TILE		= $10000
V_SPR		= $1C800
V_CTRL		= $1D000

BLT_HT		= $ffff8a00
BLT_SXI		= $ffff8a20
BLT_SYI		= $ffff8a22
BLT_SRC		= $ffff8a24
BLT_E1		= $ffff8a28
BLT_E2		= $ffff8a2a
BLT_E3		= $ffff8a2c
BLT_DXI		= $ffff8a2e
BLT_DYI		= $ffff8a30
BLT_DST		= $ffff8a32
BLT_XC		= $ffff8a36
BLT_YC		= $ffff8a38
BLT_HOP		= $ffff8a3a
BLT_OP		= $ffff8a3b
BLT_CTRL	= $ffff8a3c
BLT_SKEW	= $ffff8a3d
BLT_NFSR	= $40
BLT_FXSR	= $80

; one step of the sprite row conversion (ren_cvf): d0 = the byte * 16
	macro	CVSTEP
	if	(J>>2)=0
	or.l	((J&3)*4)(a3,d0.w),d1
	endc
	if	(J>>2)=1
	or.l	((J&3)*4)(a3,d0.w),d2
	endc
	if	(J>>2)=2
	or.l	((J&3)*4)(a3,d0.w),d3
	endc
	if	(J>>2)=3
	or.l	((J&3)*4)(a3,d0.w),d4
	endc
	if	J<8
	or.w	((J&7)*2)(a4,d0.w),d5
	else
	or.w	((J&7)*2)(a4,d0.w),d6
	endc
	endm

	section	text,code

; ======================================================================================================================
; init
; ======================================================================================================================
render_init:
	movem.l	d0-d7/a0-a6,-(sp)
	move.l	#ren_buf_area+255,d0
	clr.b	d0
	lea	ren_buf,a0
	moveq	#REN_NBUF-1,d1
.b:	move.l	d0,(a0)+
	add.l	#REN_BUFSZ,d0
	dbf	d1,.b
	move.l	d0,(a0)			; (two buffers: the third pointer is the second's, see ren_cell)
	sub.l	#REN_BUFSZ,(a0)
	move.l	ren_buf,a0		; clear the buffers
	move.l	#REN_NBUF*REN_BUFSZ/16-1,d0
.clr:	clr.l	(a0)+
	clr.l	(a0)+
	clr.l	(a0)+
	clr.l	(a0)+
	subq.l	#1,d0
	bpl	.clr
	; the c2p table: STE index i -> bit 0 of byte 3-k = bit k of i (movep.l writes byte 3 to plane 0)
	lea	ren_t16,a0
	moveq	#0,d0
.t:	moveq	#0,d1
	btst	#0,d0
	beq	.t1
	bset	#24,d1
.t1:	btst	#1,d0
	beq	.t2
	bset	#16,d1
.t2:	btst	#2,d0
	beq	.t3
	bset	#8,d1
.t3:	btst	#3,d0
	beq	.t4
	bset	#0,d1
.t4:	move.l	d1,(a0)+
	addq.w	#1,d0
	cmp.w	#16,d0
	blo	.t
	; the mask expansion: byte m -> m in all four bytes
	lea	ren_exp,a0
	moveq	#0,d0
.e:	move.b	d0,d1
	lsl.w	#8,d1
	move.b	d0,d1
	move.w	d1,d2
	swap	d1
	move.w	d2,d1
	move.l	d1,(a0)+
	addq.w	#1,d0
	cmp.w	#256,d0
	blo	.e
	; priority p -> its bits as bytes ($FF) for the priority planes (bytes 3, 2, 1: bits 0, 1, 2)
	lea	ren_pril,a0
	moveq	#0,d0
.p:	moveq	#0,d1
	btst	#0,d0
	beq	.p1
	or.l	#$ff000000,d1
.p1:	btst	#1,d0
	beq	.p2
	or.l	#$00ff0000,d1
.p2:	btst	#2,d0
	beq	.p3
	or.l	#$0000ff00,d1
.p3:	move.l	d1,(a0)+
	addq.w	#1,d0
	cmp.w	#8,d0
	blo	.p
	; the sprite pair masks: byte b (two 4-bit pixels, 15 transparent) * 16 + 2 * p -> the pair's opaque bits as
	; the p-th of 16 pixels (bit 15 - 2p the left one, 14 - 2p the right)
	lea	ren_pm16,a0
	moveq	#0,d0
.m:	moveq	#0,d1
	move.b	d0,d2
	and.b	#$f0,d2
	cmp.b	#$f0,d2
	beq	.m1
	moveq	#2,d1
.m1:	move.b	d0,d2
	and.b	#$0f,d2
	cmp.b	#$0f,d2
	beq	.m2
	addq.b	#1,d1
.m2:	ror.w	#2,d1			; (p = 0: bits 15 14)
	moveq	#8-1,d2
.mp:	move.w	d1,(a0)+
	lsr.w	#2,d1
	dbf	d2,.mp
	addq.w	#1,d0
	cmp.w	#256,d0
	blo	.m
	; nothing valid yet
	move.w	#1,ren_epoch
	move.l	#1,ren_tgen		; (the overlay bitmaps' rows: stamp 0, stale)
	bsr	ren_flush
	clr.b	ren_grp_key
	move.b	#$ff,ren_grp_key+1	; (no group key matches: the first picture redraws everything)
	moveq	#-1,d0
	move.l	d0,ren_fix_old
	move.l	d0,ren_fix_old+4
	move.l	d0,ren_soffs		; (no sprite entry known)
	lea	ren_ptslot,a0
	moveq	#256/4-1,d1
.ps:	move.l	d0,(a0)+
	dbf	d1,.ps
	st	ren_scene
	clr.b	ren_stable
	clr.l	ren_ck
	moveq	#-1,d0
	move.l	d0,ren_ck_cluster
	clr.b	ren_ready
	move.w	#-1,ren_shown
	move.w	#-1,ren_prev
	lea	ren_dmg_end,a0
	lea	ren_dmg,a1
	moveq	#REN_NBUF-1,d1
.dm:	move.l	a1,(a0)+
	lea	REN_DMG*12(a1),a1
	dbf	d1,.dm
	lea	ren_bar_w,a0
	moveq	#REN_NBUF-1,d1
.bw:	move.w	#-1,(a0)+
	dbf	d1,.bw
	move.w	#1,ren_fi_ver
	clr.w	ren_htop		; (no HUD region yet)
	move.w	#224,ren_hbot
	clr.w	ren_hudn
	lea	ren_bar_line,a0		; no bars
	move.w	#224/4-1,d1
.bl:	clr.l	(a0)+
	dbf	d1,.bl
	lea	ren_rep,a0		; (index 0: black, the others: pen 0 until the first colours)
	moveq	#16-1,d1
.rp:	clr.w	(a0)+
	dbf	d1,.rp
	clr.w	ren_ntree
	move.b	#$80,ren_tree		; (a tree of one leaf: index 1)
	movem.l	(sp)+,d0-d7/a0-a6
	rts

; the caches are stale: the hash table cleared, the pool empty
ren_flush:
	lea	ren_hash,a0
	move.w	#REN_HASH-1,d0
.h:	clr.l	(a0)+
	clr.l	(a0)+
	dbf	d0,.h
	move.l	#ren_pool,ren_pool_ptr
	addq.l	#1,ren_flushes
	rts

; ======================================================================================================================
; render_frame
; ======================================================================================================================
	ifd	REN_PHASES
; (measuring in the program: the VBLs that pass in each phase of render_frame, summed: ren_ph_vbl, 10 longs; the main
; program's cnt_vbls is the clock)
REN_PH_IN	macro
	move.l	cnt_vbls,ren_ph_t
	endm
REN_PH_OUT	macro
	move.l	d0,-(sp)
	move.l	cnt_vbls,d0
	sub.l	ren_ph_t,d0
	add.l	d0,ren_ph_vbl+4*\1
	move.l	(sp)+,d0
	endm
	endc

render_frame:
	movem.l	d0-d7/a0-a6,-(sp)
	; the buffer: not shown, not the one shown before, not waiting
.snap:	move.w	ren_shown,d1
	move.w	ren_prev,d2
	moveq	#0,d3
	move.b	ren_ready,d3
	cmp.w	ren_shown,d1
	bne	.snap
	subq.w	#1,d3
	moveq	#0,d0
.pick:	cmp.w	d1,d0
	beq	.next
	cmp.w	d2,d0
	beq	.next
	cmp.w	d3,d0
	bne	.chosen
.next:	addq.w	#1,d0
	cmp.w	#REN_NBUF,d0
	blo	.pick
	addq.l	#1,ren_skipped
	movem.l	(sp)+,d0-d7/a0-a6
	rts
.chosen:
	move.w	d0,ren_draw
	lsl.w	#2,d0
	lea	ren_buf,a0
	move.l	(a0,d0.w),ren_dbuf
	ifd	REN_PHASES
	REN_PH_IN
	endc
	bsr	ren_config
	ifd	REN_PHASES
	REN_PH_OUT 0
	endc
	ifd	REN_PHASES
	REN_PH_IN
	endc
	bsr	ren_fixed
	ifd	REN_PHASES
	REN_PH_OUT 1
	endc
	ifd	REN_PHASES
	REN_PH_IN
	endc
	bsr	ren_sprites_list
	ifd	REN_PHASES
	REN_PH_OUT 2
	endc
	sf	ren_newcols
	ifd	REN_PHASES
	REN_PH_IN
	endc
	bsr	ren_palette
	ifd	REN_PHASES
	REN_PH_OUT 3
	endc
	tst.b	ren_newcols
	beq	.nc
	moveq	#-1,d0			; new colours: the bar image again
	move.l	d0,ren_fix_old
	bsr	ren_fixed
.nc:	ifd	REN_PHASES
	REN_PH_IN
	endc
	bsr	ren_tiles
	ifd	REN_PHASES
	REN_PH_OUT 4
	endc
	tst.b	ren_black		; (a black picture: nothing drawn, the changes kept for later)
	bne	.pub
	ifd	REN_PHASES
	REN_PH_IN
	endc
	bsr	ren_bg
	ifd	REN_PHASES
	REN_PH_OUT 5
	endc
	ifd	REN_PHASES
	REN_PH_IN
	endc
	bsr	ren_restore
	ifd	REN_PHASES
	REN_PH_OUT 6
	endc
	ifd	REN_PHASES
	REN_PH_IN
	endc
	bsr	ren_bars
	ifd	REN_PHASES
	REN_PH_OUT 7
	endc
	ifd	REN_PHASES
	REN_PH_IN
	endc
	bsr	ren_objects
	ifd	REN_PHASES
	REN_PH_OUT 8
	endc
	ifd	REN_PHASES
	REN_PH_IN
	endc
	bsr	ren_clipwin
	ifd	REN_PHASES
	REN_PH_OUT 9
	endc
	move.w	ren_draw,d0		; (the damage list's end)
	lsl.w	#2,d0
	lea	ren_dmg_end,a0
	move.l	ren_dmgp,(a0,d0.w)
.pub:
	; publish: the window's first line, the fine scroll, the palette, then the buffer (one byte store)
	move.w	ren_draw,d0
	move.w	d0,d1
	lsl.w	#2,d1
	lea	ren_disp_addr,a0
	move.w	ren_w,d2
	lsr.w	#4,d2
	lsl.w	#3,d2
	ext.l	d2
	add.l	ren_dbuf,d2
	add.l	#REN_PIC,d2
	move.l	d2,(a0,d1.w)
	lea	ren_disp_fine,a0
	moveq	#15,d2
	and.w	ren_w,d2
	move.b	d2,(a0,d0.w)
	lsl.w	#5,d0
	lea	ren_disp_pal,a1
	add.w	d0,a1
	lea	ren_pal,a0
	moveq	#8-1,d2
.pal:	move.l	(a0)+,(a1)+
	dbf	d2,.pal
	lea	ren_disp_hpal,a1
	add.w	d0,a1
	lea	ren_hpal,a0
	moveq	#8-1,d2
.hpl:	move.l	(a0)+,(a1)+
	dbf	d2,.hpl
	lsr.w	#3,d0
	lea	ren_disp_hud,a1		; (the HUD region's lines: top, bottom)
	move.w	ren_htop,(a1,d0.w)
	move.w	ren_hbot,2(a1,d0.w)
	move.w	ren_draw,d0
	addq.b	#1,d0
	move.b	d0,ren_ready
	addq.l	#1,ren_pictures
	movem.l	(sp)+,d0-d7/a0-a6
	rts

; ======================================================================================================================
; render_vbl: show a published buffer
; ======================================================================================================================
render_vbl:
	tst.b	ren_ready
	bne	.flip
	move.w	#-1,ren_prev		; (the buffer before the shown one: scanned once more after the flip, free now)
	rts
.flip:
	movem.l	d0-d2/a0-a1,-(sp)
	moveq	#0,d0
	move.b	ren_ready,d0
	clr.b	ren_ready
	subq.w	#1,d0
	move.w	ren_shown,ren_prev
	move.w	d0,ren_shown
	move.w	d0,d1
	lsl.w	#2,d1
	lea	ren_disp_addr,a0
	move.l	(a0,d1.w),d1
	ifd	PIC_TOP
	sub.l	#PIC_TOP*REN_LINEB,d1
	endc
	move.l	d1,-(sp)
	move.b	1(sp),$ffff8201.w
	move.b	2(sp),$ffff8203.w
	move.b	3(sp),$ffff820d.w
	ifnd	SIM
	move.b	1(sp),$ffff8205.w	; (the counter too: the STE's is writable, see blktiger's render.s)
	move.b	2(sp),$ffff8207.w
	move.b	3(sp),$ffff8209.w
	endc
	addq.l	#4,sp
	lea	ren_disp_fine,a0
	move.b	(a0,d0.w),d2
	move.b	d2,$ffff8265.w
	move.b	#(REN_LINEB-160)/2,d1
	tst.b	d2
	beq	.w
	subq.b	#4,d1
.w:	move.b	d1,$ffff820f.w
	lsl.w	#5,d0
	lea	ren_disp_pal,a0
	add.w	d0,a0
	lea	ren_vbl_pal,a1
	moveq	#8-1,d1
.p:	move.l	(a0)+,(a1)+
	dbf	d1,.p
	lea	ren_disp_hpal,a0
	add.w	d0,a0
	lea	ren_vbl_hpal,a1
	moveq	#8-1,d1
.hp:	move.l	(a0)+,(a1)+
	dbf	d1,.hp
	lsr.w	#3,d0
	lea	ren_disp_hud,a0
	move.l	(a0,d0.w),ren_vbl_htop	; (ren_vbl_htop, ren_vbl_hbot)
	movem.l	(sp)+,d0-d2/a0-a1
	rts

; ======================================================================================================================
; the layer setup
; ======================================================================================================================
; ren_lay: per tile layer 0-3 (16 bytes): ex.w, ey.w (the player view's tilemap column / row at picture x / y 0),
; pri.b, bank.b, enabled.b, height mask (rows - 1).b, then 8 spare.
; The group: the enabled layers 0-2 that share ex and ey with the most others; its members top first (priority, then
; the higher layer: MAME's order) in ren_grp (layer, pri, bank; 4 bytes each).  A change of the group's key (members,
; priorities, banks, ey) redraws the whole buffer (ren_full) and is a new scene (ren_scene).
ren_config:
	lea	vio+V_CTRL,a0
	lea	ren_lay,a1
	lea	ren_adj(pc),a2
	moveq	#0,d7
.lay:	move.w	d7,d0
	lsl.w	#2,d0
	moveq	#0,d1
	move.b	(a0,d0.w),d1
	lsl.w	#8,d1
	move.b	1(a0,d0.w),d1		; scroll x
	moveq	#0,d2
	move.b	2(a0,d0.w),d2
	lsl.w	#8,d2
	move.b	3(a0,d0.w),d2		; scroll y
	moveq	#0,d3
	move.b	(a2,d7.w),d3
	add.w	d3,d1			; (the hardware's per-layer offset: 4 2 1 0)
	add.w	#332,d1
	neg.w	d1			; ex = -(x + offset) - 332 (the flipped screen turned)
	and.w	#511,d1
	add.w	#248,d2
	neg.w	d2			; ey = -y - 248
	moveq	#63,d3			; (64 rows; layer 3: 32)
	cmp.w	#3,d7
	bne	.h
	moveq	#31,d3
.h:	move.w	d3,d4
	addq.w	#1,d4
	lsl.w	#3,d4
	subq.w	#1,d4
	and.w	d4,d2
	move.w	d1,(a1)+
	move.w	d2,(a1)+
	move.b	$10(a0,d7.w),d0
	moveq	#7,d1
	and.b	d0,d1
	move.b	d1,(a1)+		; pri
	moveq	#7,d1
	and.b	$18(a0,d7.w),d1
	move.b	d1,(a1)+		; bank
	btst	#3,d0
	seq	(a1)+			; enabled
	move.b	d3,(a1)+
	addq.l	#8,a1
	addq.w	#1,d7
	cmp.w	#4,d7
	blo	.lay
	; the group's lead: the enabled layer 0-2 whose scroll most others share
	lea	ren_lay,a1
	moveq	#-1,d5			; lead
	moveq	#0,d6			; its count
	moveq	#0,d7
.lead:	move.w	d7,d0
	lsl.w	#4,d0
	tst.b	6(a1,d0.w)
	beq	.ln
	move.l	(a1,d0.w),d1		; ex:ey
	moveq	#0,d2
	moveq	#0,d3
.cnt:	move.w	d3,d4
	lsl.w	#4,d4
	tst.b	6(a1,d4.w)
	beq	.cn
	cmp.l	(a1,d4.w),d1
	bne	.cn
	addq.w	#1,d2
.cn:	addq.w	#1,d3
	cmp.w	#3,d3
	blo	.cnt
	cmp.w	d6,d2
	bls	.ln
	move.w	d2,d6
	move.w	d7,d5
.ln:	addq.w	#1,d7
	cmp.w	#3,d7
	blo	.lead
	; the members, top first (priority descending, then the higher layer)
	lea	ren_newkey,a3
	clr.l	(a3)
	clr.l	4(a3)
	clr.l	8(a3)
	clr.l	12(a3)
	moveq	#0,d6			; members
	clr.w	ren_ex
	clr.w	ren_ey
	clr.b	ren_grp_max
	tst.w	d5
	bmi	.nogrp
	move.w	d5,d0
	lsl.w	#4,d0
	move.l	(a1,d0.w),d4		; the group's ex:ey
	move.l	d4,ren_ex		; (ren_ex, ren_ey)
	moveq	#7,d3			; priority from 7 down
.pri:	moveq	#2,d7			; layer from 2 down
.pl:	move.w	d7,d0
	lsl.w	#4,d0
	tst.b	6(a1,d0.w)
	beq	.pn
	cmp.l	(a1,d0.w),d4
	bne	.pn
	cmp.b	4(a1,d0.w),d3
	bne	.pn
	move.w	d6,d1
	lsl.w	#2,d1
	move.b	d7,1(a3,d1.w)		; layer
	move.b	d3,2(a3,d1.w)		; pri
	move.b	5(a1,d0.w),3(a3,d1.w)	; bank
	tst.w	d6
	bne	.nm
	move.b	d3,ren_grp_max
.nm:	move.b	d3,ren_grp_min		; (the last member's: the lowest)
	addq.w	#1,d6
.pn:	dbf	d7,.pl
	dbf	d3,.pri
.nogrp:	move.b	d6,(a3)			; key: count, (layer, pri, bank) x 3, ey
	move.w	ren_ey,14(a3)
	move.b	d6,ren_grp_n
	; W = ex - 16 (the window's buffer x)
	move.w	ren_ex,d0
	sub.w	#16,d0
	and.w	#511,d0
	move.w	d0,ren_w
	; changed?  (not the banks: a member's bank changing is a palette change, see ren_dbank)
	lea	ren_grp_key,a0
	moveq	#4-1,d0
	moveq	#0,d1
.k:	move.l	(a3),d2
	move.l	(a0),d3
	cmp.w	#1,d0
	blo	.km
	clr.b	d2
	clr.b	d3
.km:	cmp.l	d3,d2
	beq	.ks
	moveq	#1,d1
.ks:	move.l	(a3)+,(a0)+
	dbf	d0,.k
	lea	ren_grp_key+1,a0	; the banks the cells are drawn with
	moveq	#2,d0
.db:	moveq	#0,d2
	move.b	(a0),d2
	lea	ren_dbank,a1
	move.b	(a1,d2.w),2(a0)
	addq.l	#4,a0
	dbf	d0,.db
	; the drawn banks' colours come from the current banks (the representatives' colours)
	lea	ren_bankcol,a1
	moveq	#0,d0
.bc:	move.b	d0,(a1,d0.w)
	addq.w	#1,d0
	cmp.w	#8,d0
	blo	.bc
	lea	ren_grp_key+1,a0
	moveq	#0,d0
	move.b	ren_grp_n,d0
	bra	.bt
.bm:	moveq	#0,d2
	move.b	(a0),d2
	lsl.w	#4,d2
	lea	ren_lay,a2
	move.b	5(a2,d2.w),d3		; current
	moveq	#0,d2
	move.b	2(a0),d2		; drawn
	move.b	d3,(a1,d2.w)
	addq.l	#4,a0
.bt:	dbf	d0,.bm
	tst.w	d1
	beq	.same
	st	ren_full
	st	ren_scene
	moveq	#-1,d0
	move.l	d0,ren_fix_old		; (the bars depend on the group's priority)
.same:	; the overlay layers: enabled layers 0-2 outside the group, and layer 3
	lea	ren_ovl,a2
	moveq	#0,d0
	lea	ren_lay,a1
	moveq	#0,d7
.ov:	move.w	d7,d1
	lsl.w	#4,d1
	tst.b	6(a1,d1.w)
	beq	.on
	cmp.w	#3,d7
	beq	.oadd
	move.l	(a1,d1.w),d2
	cmp.l	ren_ex,d2
	bne	.oadd
	tst.b	ren_grp_n
	bne	.on
.oadd:	move.b	d7,(a2)+		; (layer, pri)
	move.b	4(a1,d1.w),(a2)+
	addq.w	#1,d0
.on:	addq.w	#1,d7
	cmp.w	#4,d7
	blo	.ov
	move.w	d0,ren_novl
	rts

; ren_ovl sorted by priority (a stable insertion sort of at most six)
ren_ovl_sort:
	move.w	ren_novl,d0
	moveq	#1,d1
.so:	cmp.w	d0,d1
	bhs	.sd
	move.w	d1,d2
.si:	lea	ren_ovl,a0
	move.w	d2,d3
	add.w	d3,d3
	move.b	-1(a0,d3.w),d4		; the one before's priority
	cmp.b	1(a0,d3.w),d4
	bls	.sx
	move.w	-2(a0,d3.w),d4
	move.w	(a0,d3.w),-2(a0,d3.w)
	move.w	d4,(a0,d3.w)
	subq.w	#1,d2
	bne	.si
.sx:	addq.w	#1,d1
	bra	.so
.sd:	rts

ren_adj:
	dc.b	4,2,1,0
	even

; ======================================================================================================================
; tile RAM changes
; ======================================================================================================================
; The group's visible rows (and every row on a full redraw) are compared with the copy ren_tcopy as longs; a changed
; long marks its two cells in ren_dirty (64 x 64, the tilemap's rows and columns).
ren_tiles:
	ifd	TILE_FLAG
	tst.b	tile_written		; (a write since the last look: the overlay layers' bitmaps are stale)
	beq	.nw
	addq.l	#1,ren_tgen
	tst.b	ren_grp_n
	bne	.nw
	sf	tile_written		; (no group: nothing else reads the flag; a new group redraws everything)
.nw:
	endc
	tst.b	ren_grp_n
	beq	.out
	tst.b	ren_full
	beq	.diff
	sf	ren_full
	lea	ren_grp_key+1,a0	; the cells drawn with the current banks from now on
	moveq	#0,d0
	move.b	ren_grp_n,d0
	bra	.dt
.dm:	moveq	#0,d1
	move.b	(a0),d1
	move.w	d1,d2
	lsl.w	#4,d2
	lea	ren_lay,a1
	move.b	5(a1,d2.w),d2
	lea	ren_dbank,a1
	move.b	d2,(a1,d1.w)
	move.b	d2,2(a0)
	lea	ren_bankcol,a1
	move.b	d2,(a1,d2.w)
	addq.l	#4,a0
.dt:	dbf	d0,.dm
	lea	ren_dirty,a0		; everything dirty, the copy taken
	move.w	#4096/4-1,d0
	move.l	#$01010101,d1
.fd:	move.l	d1,(a0)+
	dbf	d0,.fd
	lea	ren_coldirty,a0
	moveq	#64/4-1,d0
.fcd:	move.l	d1,(a0)+
	dbf	d0,.fcd
	lea	ren_grp_key+1,a2
	moveq	#0,d6
	move.b	ren_grp_n,d6
	subq.w	#1,d6
.fm:	moveq	#0,d0
	move.b	(a2),d0
	addq.l	#4,a2
	lsl.w	#8,d0
	lsl.w	#5,d0			; * $2000
	lea	vio+V_TILE,a0
	add.w	d0,a0
	lea	ren_tcopy,a1
	add.w	d0,a1
	move.w	#$2000/4-1,d0
.fc:	move.l	(a0)+,(a1)+
	dbf	d0,.fc
	dbf	d6,.fm
	rts
.diff:	ifd	TILE_FLAG
	tst.b	tile_written		; (the translated writers' flag, see the README)
	beq	.out
	sf	tile_written
	endc
	move.w	ren_ey,d0
	lsr.w	#3,d0
	move.w	d0,d5			; the first row
	move.w	ren_ey,d4
	add.w	#223,d4
	lsr.w	#3,d4
	sub.w	d0,d4			; rows - 1
	lea	ren_grp_key+1,a2
	moveq	#0,d6
	move.b	ren_grp_n,d6
	subq.w	#1,d6
.mem:	moveq	#0,d0
	move.b	(a2),d0
	addq.l	#4,a2
	lsl.w	#8,d0
	lsl.w	#5,d0
	move.w	d0,d3			; the layer's offset
	move.w	d4,d7
	move.w	d5,d2
	move.w	d6,-(sp)
.row:	and.w	#63,d2
	move.w	d2,d0
	lsl.w	#7,d0
	add.w	d3,d0
	lea	vio+V_TILE,a4
	add.w	d0,a4			; the row
	lea	ren_tcopy,a5
	add.w	d0,a5
	ifd	TILE_FLAG
	moveq	#0,d0			; (a writer was there: the whole row)
	moveq	#32,d1
	bsr	ren_diff_seg
	bra	.rd
	endc
	; the window's 21 longs (41 columns; wrapping at 32), and a quarter of the row in turn
	move.w	ren_w,d0
	lsr.w	#4,d0			; the first long
	moveq	#21,d1
	move.w	d0,d6
	add.w	d1,d6
	sub.w	#32,d6			; (longs past the row's end)
	ble	.one
	sub.w	d6,d1
	bsr	ren_diff_seg
	moveq	#0,d0
	move.w	d6,d1
.one:	bsr	ren_diff_seg
	move.w	ren_roll,d0
	lsl.w	#3,d0
	moveq	#8,d1
	bsr	ren_diff_seg
.rd:	addq.w	#1,d2
	dbf	d7,.row
	move.w	(sp)+,d6
	dbf	d6,.mem
	addq.w	#1,ren_roll
	and.w	#3,ren_roll
	cmp.w	#150,ren_changed	; (longs: two cells each) many changes: a new scene, black from now on
	blo	.out
	clr.w	ren_changed
	st	ren_scene
	st	ren_black
	clr.b	ren_stable
	lea	ren_pal,a0
	moveq	#8-1,d0
.bk:	clr.l	(a0)+
	dbf	d0,.bk
	lea	ren_hpal,a0
	moveq	#8-1,d0
.bh:	clr.l	(a0)+
	dbf	d0,.bh
.out:	rts

; d0.w longs from the first d0 (of 32) of the row at a4 (tile RAM) / a5 (the copy), d2 = the row: the changed longs
; mark their cells.  Keeps d2-d7/a2-a6.
ren_diff_seg:
	lsl.w	#2,d0
	lea	(a4,d0.w),a0
	lea	(a5,d0.w),a1
	subq.w	#1,d1
	bmi	.out
.c:	cmpm.l	(a0)+,(a1)+
	dbne	d1,.c
	beq	.out
	move.l	-4(a0),-4(a1)		; a changed long: its two cells
	move.l	a1,d0
	sub.l	a5,d0
	subq.w	#4,d0
	lsr.w	#1,d0			; the first cell's column
	movem.l	d1/a2,-(sp)
	lea	ren_coldirty,a2
	st	(a2,d0.w)
	st	1(a2,d0.w)
	move.w	d2,d1
	lsl.w	#6,d1
	add.w	d1,d0
	lea	ren_dirty,a2
	move.b	#1,(a2,d0.w)
	move.b	#1,1(a2,d0.w)
	movem.l	(sp)+,d1/a2
	addq.w	#1,ren_changed
	dbf	d1,.c
.out:	rts

; ======================================================================================================================
; the group's cells into the buffers
; ======================================================================================================================
; The dirty cells of the visible rows: the window's 41 columns all, the others REN_BUDGET a picture (they are drawn
; before they come into the window: the window's columns are checked every picture).  Many changes in the window: a
; new scene (the colours are chosen again).
ren_bg:
	clr.w	ren_changed
	tst.b	ren_grp_n
	beq	.out
	bsr	ren_grp_tables
	move.w	ren_ey,d0
	lsr.w	#3,d0
	move.w	d0,ren_row0
	move.w	ren_ey,d4
	add.w	#223,d4
	lsr.w	#3,d4
	sub.w	d0,d4
	move.w	d4,ren_nrows		; rows - 1
	; the window's columns
	clr.w	ren_wcells
	move.w	ren_w,d0
	lsr.w	#3,d0
	move.w	d0,ren_col0
	moveq	#41-1,d6
.wc:	move.w	ren_col0,d0
	add.w	#40,d0
	sub.w	d6,d0
	and.w	#63,d0
	bsr	ren_bg_col
	dbf	d6,.wc
.few:	; the other columns, as far as the budget goes
	move.w	#REN_BUDGET,ren_budget
	moveq	#23-1,d6
.oc:	tst.w	ren_budget
	ble	.out
	move.w	ren_col0,d0
	add.w	#41,d0
	add.w	d6,d0
	and.w	#63,d0
	bsr	ren_bg_col
	dbf	d6,.oc
.out:	rts

; d0.w = a column: its dirty cells in the visible rows
ren_bg_col:
	lea	ren_coldirty,a0
	tst.b	(a0,d0.w)
	bne	.go
	rts
.go:	sf	(a0,d0.w)
	movem.l	d6,-(sp)
	move.w	d0,ren_col
	move.w	ren_nrows,d7
	move.w	ren_row0,d5
	moveq	#0,d4
	move.w	ren_ey,d4
	and.w	#7,d4
	neg.w	d4			; the cell's top line in the picture
.r:	and.w	#63,d5
	move.w	d5,d0
	lsl.w	#6,d0
	add.w	ren_col,d0
	lea	ren_dirty,a0
	tst.b	(a0,d0.w)
	beq	.n
	clr.b	(a0,d0.w)
	addq.w	#1,ren_wcells
	subq.w	#1,ren_budget
	movem.l	d4-d5/d7,-(sp)
	move.w	d5,ren_row
	move.w	d4,ren_ytop
	bsr	ren_cell
	movem.l	(sp)+,d4-d5/d7
.n:	addq.w	#1,d5
	addq.w	#8,d4
	dbf	d7,.r
	movem.l	(sp)+,d6
	rts

; the c2p tables of the group's banks (made after a change of the colours)
ren_grp_tables:
	lea	ren_grp_key+1,a2
	moveq	#0,d6
	move.b	ren_grp_n,d6
	subq.w	#1,d6
.m:	moveq	#0,d0
	move.b	2(a2),d0
	bsr	ren_mt_get
	addq.l	#4,a2
	dbf	d6,.m
	rts

; d0.w = a tile bank: a0 = its c2p table (256 longs: pen -> the STE index's bits), made when stale.  Keeps d1-d7/a1-a6.
ren_mt_get:
	movem.l	d0-d7/a1-a6,-(sp)
	move.w	d0,d7			; (bank; + 8 for the HUD's palette)
	tst.b	ren_curmap
	beq	.m0
	addq.w	#8,d7
.m0:	move.w	d7,d0
	lea	ren_mt_ep,a1
	add.w	d0,d0
	move.w	ren_epoch,d1
	cmp.w	(a1,d0.w),d1
	beq	.ok
	move.w	d1,(a1,d0.w)
	move.w	d7,d0
	and.w	#7,d0
	lsl.w	#8,d0
	add.w	#$800,d0		; the bank's first pen
	move.w	d0,d6
	move.w	d7,d0
	lsl.w	#8,d0
	lsl.w	#2,d0
	lea	ren_mt,a3
	add.w	d0,a3
	lea	ren_t16,a4
	move.w	#256-1,d5
.p:	move.w	d6,d0
	bsr	ren_pen_index
	lsl.w	#2,d1
	move.l	(a4,d1.w),(a3)+
	addq.w	#1,d6
	dbf	d5,.p
.ok:	move.w	d7,d0
	lsl.w	#8,d0
	lsl.w	#2,d0
	lea	ren_mt,a0
	add.w	d0,a0
	movem.l	(sp)+,d0-d7/a1-a6
	rts

; One cell of the group: tilemap row ren_row, column ren_col, its top line ren_ytop in the picture.  The members from
; the top down to the first opaque one; one opaque member: its pixels; else the members' rows merged bottom up by
; their masks (black where none is opaque).  Into the three buffers (both twins) and the priority planes.
ren_cell:
	lea	ren_grp_key+1,a2
	moveq	#0,d6
	move.b	ren_grp_n,d6
	subq.w	#1,d6
	lea	ren_src,a3		; per member: chr data, mask, c2p table, pri (16 bytes)
	moveq	#0,d5			; the members used
	moveq	#0,d4			; the cell's highest priority
.m:	moveq	#0,d0
	move.b	(a2),d0
	lsl.w	#8,d0
	lsl.w	#5,d0			; the layer's tile RAM
	move.w	ren_row,d1
	lsl.w	#7,d1
	add.w	d1,d0
	move.w	ren_col,d1
	add.w	d1,d1
	add.w	d1,d0
	lea	vio+V_TILE,a0
	move.w	(a0,d0.w),d0
	and.w	#$3fff,d0
	lea	ren_chrflag,a0
	move.b	(a0,d0.w),d1
	beq	.mn			; transparent
	moveq	#0,d2
	move.w	d0,d2
	lsl.l	#3,d2
	lea	ren_chrmask,a0
	add.l	d2,a0
	move.l	a0,4(a3)
	lea	ren_zero64,a0
	cmp.w	#REN_NCHR,d0
	bhs	.z
	lsl.l	#3,d2
	lea	ren_chr,a0
	add.l	d2,a0
.z:	move.l	a0,(a3)
	moveq	#0,d0
	move.b	2(a2),d0
	move.l	a2,-(sp)
	bsr	ren_mt_get
	move.l	(sp)+,a2
	move.l	a0,8(a3)
	move.b	1(a2),12(a3)		; pri
	move.b	d1,13(a3)		; flag
	tst.w	d5
	bne	.nt
	move.b	1(a2),d4
.nt:	lea	16(a3),a3
	addq.w	#1,d5
	cmp.b	#2,d1
	beq	.done			; opaque: nothing below shows
.mn:	addq.l	#4,a2
	dbf	d6,.m
.done:	; the cell's highest priority (for the sprites' priority repair)
	move.w	ren_row,d0
	lsl.w	#6,d0
	add.w	ren_col,d0
	lea	ren_cellpri,a0
	move.b	d4,(a0,d0.w)
	moveq	#0,d2			; the lowest priority when the members cover all of it (else 0)
	tst.w	d5
	beq	.cm
	cmp.b	#2,-16+13(a3)
	bne	.cm
	move.b	-16+12(a3),d2
.cm:	lea	ren_cellmin,a0
	move.b	d2,(a0,d0.w)
	; the destinations: line ren_ytop of the three buffers, the column's byte
	move.w	ren_col,d0
	move.w	d0,d1
	lsr.w	#1,d0
	lsl.w	#3,d0
	and.w	#1,d1
	add.w	d1,d0			; the byte in a line
	move.w	ren_ytop,d1
	moveq	#0,d2
	move.w	d1,d2
	add.w	#REN_GUARD,d2
	moveq	#9,d3
	lsl.l	d3,d2
	add.w	d0,d2			; offset in a buffer (< 160 KB: a long)
	lea	ren_buf,a0
	move.l	(a0)+,a4
	add.l	d2,a4
	move.l	(a0)+,a5
	add.l	d2,a5
	move.l	(a0)+,a6
	add.l	d2,a6
	ext.l	d1
	lsl.l	#8,d1			; the priority planes: 256 bytes a line
	lea	ren_pri,a1
	add.l	d1,a1
	add.w	d0,a1
	move.w	ren_ytop,d3		; the line, for the picture's range
	moveq	#8-1,d7
	tst.w	d5
	beq	.black
	cmp.w	#1,d5
	bne	.mixed
	cmp.b	#2,ren_src+13
	bne	.mixed
	; one opaque member
	move.l	ren_src,a0
	move.l	ren_src+8,a2
	moveq	#0,d0
	move.b	ren_src+12,d0
	lsl.w	#2,d0
	lea	ren_pril,a3
	move.l	(a3,d0.w),d6		; its priority bits
	lea	ren_bar_line,a3
.o:	moveq	#0,d1
	rept	8
	moveq	#0,d0
	move.b	(a0)+,d0
	add.w	d0,d0
	add.w	d0,d0
	add.l	d1,d1
	or.l	(a2,d0.w),d1
	endr
	cmp.w	#224,d3
	bhs	.os			; (above or below the picture)
	movep.l	d1,0(a4)
	movep.l	d1,256(a4)
	movep.l	d1,0(a5)
	movep.l	d1,256(a5)
	movep.l	d1,0(a6)
	movep.l	d1,256(a6)
	movep.l	d6,0(a1)
	tst.b	(a3,d3.w)		; (a bar line: copied again in every buffer)
	beq	.os
	bsr	ren_bar_touch
.os:	lea	REN_LINEB(a4),a4
	lea	REN_LINEB(a5),a5
	lea	REN_LINEB(a6),a6
	lea	256(a1),a1
	addq.w	#1,d3
	dbf	d7,.o
	rts
.black:	moveq	#0,d1
.bl:	cmp.w	#224,d3
	bhs	.bs
	movep.l	d1,0(a4)
	movep.l	d1,256(a4)
	movep.l	d1,0(a5)
	movep.l	d1,256(a5)
	movep.l	d1,0(a6)
	movep.l	d1,256(a6)
	movep.l	d1,0(a1)
	bsr	ren_bar_touch
.bs:	lea	REN_LINEB(a4),a4
	lea	REN_LINEB(a5),a5
	lea	REN_LINEB(a6),a6
	lea	256(a1),a1
	addq.w	#1,d3
	dbf	d7,.bl
	rts
	; several members: rows merged bottom up
.mixed:	move.w	d5,ren_nsrc
	clr.w	ren_srow
.mr:	moveq	#0,d1			; the row (black)
	moveq	#0,d6			; its priority bits
	move.w	ren_nsrc,d5
	subq.w	#1,d5			; (the bottom member)
	lea	ren_src,a3		; the topmost member opaque in this row: those below it do not show
	moveq	#0,d0
.fb:	cmp.w	d5,d0
	bhs	.fbd
	move.l	4(a3),a0
	add.w	ren_srow,a0
	cmp.b	#$ff,(a0)
	beq	.fbd
	lea	16(a3),a3
	addq.w	#1,d0
	bra	.fb
.fbd:	move.w	d0,d5			; (merged from there up)
.ml:	move.l	4(a3),a0
	add.w	ren_srow,a0
	moveq	#0,d0
	move.b	(a0),d0			; its mask row
	beq	.mskip
	lsl.w	#2,d0
	lea	ren_exp,a0
	move.l	(a0,d0.w),d2		; expanded
	move.l	(a3),a0
	move.w	ren_srow,d0
	lsl.w	#3,d0
	add.w	d0,a0
	move.l	8(a3),a2
	moveq	#0,d0
	move.l	d1,-(sp)
	moveq	#0,d1
	rept	8
	moveq	#0,d0
	move.b	(a0)+,d0
	add.w	d0,d0
	add.w	d0,d0
	add.l	d1,d1
	or.l	(a2,d0.w),d1
	endr
	move.l	d1,d0			; the member's row
	move.l	(sp)+,d1
	and.l	d2,d0
	not.l	d2
	and.l	d2,d1
	or.l	d0,d1
	and.l	d2,d6			; its priority where opaque
	not.l	d2
	moveq	#0,d0
	move.b	12(a3),d0
	lsl.w	#2,d0
	lea	ren_pril,a0
	move.l	(a0,d0.w),d0
	and.l	d2,d0
	or.l	d0,d6
.mskip:	lea	-16(a3),a3
	dbf	d5,.ml
	cmp.w	#224,d3
	bhs	.ms
	movep.l	d1,0(a4)
	movep.l	d1,256(a4)
	movep.l	d1,0(a5)
	movep.l	d1,256(a5)
	movep.l	d1,0(a6)
	movep.l	d1,256(a6)
	movep.l	d6,0(a1)
	bsr	ren_bar_touch
.ms:	lea	REN_LINEB(a4),a4
	lea	REN_LINEB(a5),a5
	lea	REN_LINEB(a6),a6
	lea	256(a1),a1
	addq.w	#1,d3
	addq.w	#1,ren_srow
	dbf	d7,.mr
	rts

; d3.w = a picture line the group's cells wrote: a bar line there is copied again in every buffer.  Keeps all.
ren_bar_touch:
	move.l	a0,-(sp)
	lea	ren_bar_line,a0
	tst.b	(a0,d3.w)
	beq	.n
	lea	ren_bar_dirty,a0
	add.w	d3,a0
	st	(a0)
	st	224(a0)
	if	REN_NBUF=3
	st	448(a0)
	endc
.n:	move.l	(sp)+,a0
	rts

; ======================================================================================================================
; Colours
; ======================================================================================================================
; Each pen maps to an STE index (ren_pen_index): its colour (palette RAM, rounded to 4 bits a channel) in Oklab
; (ren_lab) goes down a k-d tree (ren_tree) to one of up to 15 boxes, index 1-15; black is index 0.  The tree comes
; from a median cut of the colours on screen (ren_cluster: pens sampled from the window's cells and the sprites,
; weighted by their counts).  The STE colour of index i is the CURRENT colour of the box's representative pen
; (ren_rep): a fade of the palette RAM is the STE palette's fade, without drawing anything again.  The colours are
; chosen again at a new scene (the group changed, or 300 of the window's cells), once the palette has not moved for
; two pictures and is not black (the picture stays black until then), or when the palette settled on other colours
; than at the last choice (8 pictures without a change).
ren_palette:
	; a checksum of sampled pens: every 16th pen of the group's banks and the fixed layers' banks, every 32nd
	; sprite pen
	moveq	#0,d6
	moveq	#0,d7			; (their OR: zero = all black)
	lea	ren_grp_key+1,a2
	moveq	#0,d5
	move.b	ren_grp_n,d5
	bra	.gt
.g:	moveq	#0,d0
	move.b	(a2),d0
	lsl.w	#4,d0
	lea	ren_lay,a0
	move.b	5(a0,d0.w),d0		; (the current bank)
	bsr	.bank
	addq.l	#4,a2
.gt:	dbf	d5,.g
	lea	ren_fix,a2		; (the fixed layers: enabled, pri, bank)
	moveq	#2-1,d5
.f:	tst.b	(a2)
	beq	.fn
	moveq	#0,d0
	move.b	2(a2),d0
	bsr	.bank
.fn:	addq.l	#4,a2
	dbf	d5,.f
	lea	vio,a0
	moveq	#32-1,d4
.s:	rol.l	#1,d6
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
	lea	64(a0),a0
	dbf	d4,.s
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
.dec:	tst.b	ren_scene
	beq	.old
	; a new scene: black until the palette rests (not black), then new colours
	st	ren_black
	tst.b	ren_allblack
	bne	.ste
	addq.b	#1,ren_wait
	cmp.b	#REN_WAIT,ren_wait
	bhs	.cl			; (a palette that keeps moving: not longer)
	cmp.b	#2,ren_stable
	blo	.ste
.cl:	clr.b	ren_wait
	bsr	ren_cluster
	sf	ren_scene
	sf	ren_black
	bra	.ste
.old:	cmp.b	#8,ren_stable
	bne	.ste
	tst.b	ren_allblack
	bne	.ste
	move.l	ren_ck,d0
	cmp.l	ren_ck_cluster,d0
	beq	.ste
	bsr	ren_cluster		; (settled on other colours)
.ste:	bsr	ren_quality
	; the STE palettes: the representatives' current colours
	lea	ren_pal,a1
	lea	ren_rep+2,a2
	bsr	.one
	lea	ren_hpal,a1
	lea	ren_hrep+2,a2
.one:	tst.b	ren_black
	bne	.blk
	clr.w	(a1)+
	lea	ren_q4,a3
	lea	ren_stenib(pc),a4
	moveq	#15-1,d5
.c:	move.w	(a2)+,d0
	cmp.w	#$800,d0		; a tile pen: its bank's current colours
	blo	.cs
	cmp.w	#$1000,d0
	bhs	.cs
	move.w	d0,d1
	lsr.w	#8,d1
	and.w	#7,d1
	lea	ren_bankcol,a0
	move.b	(a0,d1.w),d1
	and.w	#$ff,d0
	lsl.w	#8,d1
	add.w	d1,d0
	add.w	#$800,d0
.cs:	move.w	d0,d1
	and.w	#$7ff,d0
	and.w	#$f800,d1
	add.w	d1,d1
	add.w	d1,d1			; page * $2000
	add.w	d1,d0
	lea	vio,a0
	add.w	d0,a0
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
.blk:	moveq	#8-1,d5
.bk:	clr.l	(a1)+
	dbf	d5,.bk
	rts
; d0 = a tile bank: 16 of its pens into the checksum d6 (and ren_allblack: the whole sample black)
.bank:	lsl.w	#8,d0
	lea	vio+$2000,a0
	add.w	d0,a0
	moveq	#8-1,d4
.bp:	rol.l	#1,d6
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
	lea	32(a0),a0
	dbf	d4,.bp
	rts

; 4-bit level -> the STE's nibble (bits 3-1 the high bits, bit 0 in bit 3)
ren_stenib:
	dc.b	$0,$8,$1,$9,$2,$a,$3,$b,$4,$c,$5,$d,$6,$e,$7,$f
	even

; d0.w = a pen (0-$17FF) -> d1.w = its STE index in the palette ren_curmap (0 the playfield's, 1 the HUD bars'):
; black is 0, any other colour (the palette when the colours were chosen, ren_palsnap, rounded to the STE's 4 bits a
; channel) the nearest of the palette's centres (Oklab bytes, L1), index 1-15.  Looked up in ren_lut, filled on
; demand.  Keeps d0 d2-d7/a0-a6.
ren_pen_index:
	movem.l	d0/d2-d5/a0-a2,-(sp)
	move.w	d0,d1
	and.w	#$7ff,d0
	lsr.w	#8,d1
	lsr.w	#3,d1
	lsl.w	#8,d1
	lsl.w	#5,d1
	add.w	d1,d0
	lea	ren_palsnap,a0		; (the palette as it was when the colours were chosen)
	add.w	d0,a0
	lea	ren_q4,a1
	moveq	#0,d1
	moveq	#0,d2
	move.b	(a0),d1
	move.b	(a1,d1.w),d2
	lsl.w	#4,d2
	move.b	$800(a0),d1
	or.b	(a1,d1.w),d2
	lsl.w	#4,d2
	move.b	$1000(a0),d1
	or.b	(a1,d1.w),d2		; r g b, 4 bits each
	moveq	#0,d1
	tst.w	d2
	beq	.out			; black
	lea	ren_lut,a1
	tst.b	ren_curmap
	beq	.m0
	lea	4096(a1),a1
.m0:	move.b	(a1,d2.w),d1
	bpl	.out			; (known)
	lea	(a1,d2.w),a2		; (to fill)
	lsl.w	#2,d2
	lea	ren_lab,a0
	add.w	d2,a0			; L a b
	bsr	ren_nearest
	move.b	d1,(a2)
.out:	movem.l	(sp)+,d0/d2-d5/a0-a2
	rts

; a0 = an Oklab colour (3 bytes) -> d1.w = the nearest centre (1-n) of the palette ren_curmap (0 when it has none).
; Uses d2-d5, a1.
ren_nearest:
	lea	ren_cent+4,a1
	moveq	#0,d1
	tst.b	ren_curmap
	beq	.m0
	lea	16*4(a1),a1
.m0:	move.w	#$7fff,d5		; the best distance
	moveq	#1,d4
	move.w	ren_ncent,d3
	tst.b	ren_curmap
	beq	.c
	move.w	ren_ncent+2,d3
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

; New colours: the samples' histogram, the median cut, the tree, the representatives; every converted thing stale.
ren_cluster:
	movem.l	d0-d7/a0-a6,-(sp)
	addq.l	#1,ren_clusters
	move.l	ren_ck,ren_ck_cluster
	lea	vio,a0			; the palette now: the mapping's (ren_pen_index)
	lea	ren_palsnap,a1
	move.w	#$6000/16-1,d0
.ps:	move.l	(a0)+,(a1)+
	move.l	(a0)+,(a1)+
	move.l	(a0)+,(a1)+
	move.l	(a0)+,(a1)+
	dbf	d0,.ps
	lea	ren_ch,a0		; the histograms (both palettes)
	move.w	#2*4096/2-1,d0
.hc:	clr.l	(a0)+
	dbf	d0,.hc
	lea	ren_cs,a0
	move.w	#2*4096/4-1,d0
.hs:	clr.l	(a0)+
	dbf	d0,.hs
	sf	ren_smap
	bsr	ren_sample_group
	bsr	ren_sample_fixed
	bsr	ren_sample_ovl
	bsr	ren_sample_sprites
	sf	ren_smap
	move.w	#-1,ren_qbase
	clr.w	ren_qcount
	clr.w	ren_ncent+2
	sf	ren_curmap
	bsr	ren_palette_of		; the playfield's palette
	tst.w	ren_hudn
	beq	.nh
	st	ren_curmap
	bsr	ren_palette_of		; the HUD bars'
.nh:	sf	ren_curmap
	lea	ren_lut,a0		; the mappings: nothing known
	move.w	#2*4096/4-1,d0
	moveq	#-1,d1
.lc:	move.l	d1,(a0)+
	dbf	d0,.lc
	st	ren_newcols
	addq.w	#1,ren_epoch		; every table and cache stale
	bsr	ren_flush
	st	ren_full		; the buffers again
	movem.l	(sp)+,d0-d7/a0-a6
	rts

; the samples of the group: two pixels (2,2) and (5,5) of each visible cell in the window
ren_sample_group:
	tst.b	ren_grp_n
	beq	.out
	move.w	ren_ey,d0
	lsr.w	#3,d0
	move.w	d0,d5			; row
	move.w	ren_ey,d4
	add.w	#223,d4
	lsr.w	#3,d4
	sub.w	d0,d4
	move.w	ren_ey,d0
	and.w	#7,d0
	neg.w	d0
	move.w	d0,ren_sy		; the row's top line
.r:	move.w	ren_w,d0
	lsr.w	#3,d0
	move.w	d0,d3			; column
	moveq	#41-1,d7
.c:	and.w	#63,d3
	and.w	#63,d5
	move.w	d3,d0
	add.w	d5,d0
	and.w	ren_smask,d0
	bne	.cn			; (the light sample: every 4th cell)
	move.w	d3,d1			; pixel (k, k), k = 1 + (column + 3 row) & 3 * 2 (one a cell, its place varying)
	add.w	d5,d1
	add.w	d5,d1
	add.w	d5,d1
	and.w	#3,d1
	add.w	d1,d1
	addq.w	#1,d1
	move.w	ren_sy,d0		; (its line: in the picture, not in the HUD bars)
	add.w	d1,d0
	cmp.w	#224,d0
	bhs	.cn
	bsr	ren_in_hud
	bne	.cn
	bsr	.px
.cn:	addq.w	#1,d3
	dbf	d7,.c
	addq.w	#1,d5
	addq.w	#8,ren_sy
	dbf	d4,.r
.out:	rts
; the composed pen at pixel (d1, d1) of cell (d5, d3) into the histogram
.px:	movem.l	d3-d5/d7,-(sp)
	lea	ren_grp_key+1,a2
	moveq	#0,d6
	move.b	ren_grp_n,d6
	subq.w	#1,d6
.m:	moveq	#0,d0
	move.b	(a2),d0
	lsl.w	#8,d0
	lsl.w	#5,d0
	move.w	d5,d2
	lsl.w	#7,d2
	add.w	d2,d0
	move.w	d3,d2
	add.w	d2,d2
	add.w	d2,d0
	lea	vio+V_TILE,a0
	move.w	(a0,d0.w),d0
	and.w	#$3fff,d0
	moveq	#0,d2
	move.b	(a2),d2
	lsl.w	#4,d2
	lea	ren_lay,a0
	move.b	5(a0,d2.w),d2		; the current bank
	bsr	ren_sample_chr
	bne	.done
	addq.l	#4,a2
	dbf	d6,.m
.done:	movem.l	(sp)+,d3-d5/d7
	rts

; d0.w = a character, d1.w = its pixel (d1, d1), d2.w = the bank: its pen counted when opaque (Z clear), else Z set.
; Keeps d1-d7/a2-a6.
ren_sample_chr:
	movem.l	d1-d3/a1,-(sp)
	moveq	#0,d3
	move.w	d0,d3
	lsl.l	#3,d3
	lea	ren_chrmask,a0
	add.l	d3,a0
	move.b	(a0,d1.w),d3
	moveq	#7,d0
	sub.w	d1,d0
	btst	d0,d3
	beq	.no
	move.l	a0,d3
	sub.l	#ren_chrmask,d3
	cmp.l	#REN_NCHR*8,d3
	bhs	.zero
	lsl.l	#3,d3
	lea	ren_chr,a0
	add.l	d3,a0
	move.w	d1,d0
	lsl.w	#3,d0
	add.w	d1,d0
	moveq	#0,d3
	move.b	(a0,d0.w),d3
	bra	.pen
.zero:	moveq	#0,d3
.pen:	lsl.w	#8,d2
	add.w	d2,d3
	add.w	#$800,d3
	moveq	#1,d0
	bsr	ren_count
	moveq	#1,d0			; (Z clear)
	movem.l	(sp)+,d1-d3/a1
	rts
.no:	moveq	#0,d0			; (Z set)
	movem.l	(sp)+,d1-d3/a1
	rts

; the fixed layers: two pixels of every cell (top layer first)
ren_sample_fixed:
	moveq	#0,d5			; row
.r:	moveq	#0,d3			; column
	move.w	d5,d0			; (the HUD bars' samples to their palette)
	lsl.w	#3,d0
	bsr	ren_in_hud
	sne	ren_smap
.c:	move.w	d3,d0
	add.w	d5,d0
	and.w	ren_smask,d0
	bne	.cn
	moveq	#2,d1
	bsr	.px
	tst.w	ren_smask
	bne	.cn
	moveq	#5,d1
	bsr	.px
.cn:
	addq.w	#1,d3
	cmp.w	#36,d3
	blo	.c
	addq.w	#1,d5
	cmp.w	#28,d5
	blo	.r
	sf	ren_smap
	rts
.px:	lea	ren_fixord,a2		; the enabled fixed layers top first: layer offset.w, bank.b, pri.b
	move.w	ren_nfix,d6
	bra	.mt
.m:	move.w	d5,d0
	mulu	#36,d0
	add.w	d3,d0
	add.w	d0,d0
	add.w	(a2),d0
	lea	vio+V_TILE,a0
	move.w	(a0,d0.w),d0
	and.w	#$3fff,d0
	moveq	#0,d2
	move.b	2(a2),d2
	bsr	ren_sample_chr
	bne	.done
	addq.l	#4,a2
.mt:	dbf	d6,.m
.done:	rts

; the sprites: 16 pixels of each visible sprite (a 4 x 4 grid), counted twice
ren_sample_sprites:
	lea	ren_slist,a2
	move.w	ren_nspr,d7
	bra	.t
.s:	moveq	#0,d3
	move.b	SL_COL(a2),d3
	lsl.w	#4,d3			; the colour's first pen
	moveq	#0,d6			; grid row
.y:	moveq	#0,d0
	move.b	SL_SY(a2),d0
	mulu	d6,d0
	lsr.w	#2,d0			; the row
	move.w	d0,-(sp)
	btst	#1,SL_FL(a2)		; (its line: the HUD bars' samples to their palette)
	beq	.yn
	neg.w	d0
	add.b	SL_SY(a2),d0
	subq.w	#1,d0
.yn:	add.w	SL_Y(a2),d0
	bsr	ren_in_hud
	sne	ren_smap
	move.w	(sp)+,d0
	bsr	ren_spr_row
	moveq	#0,d1			; grid column
.x:	moveq	#0,d2
	move.b	SL_SX(a2),d2
	mulu	d1,d2
	lsr.w	#2,d2			; the pixel
	lea	ren_brow,a0
	move.w	d2,d0
	lsr.w	#1,d0
	move.b	(a0,d0.w),d0
	btst	#0,d2
	bne	.lo
	lsr.b	#4,d0
.lo:	and.w	#15,d0
	cmp.w	#15,d0
	beq	.xn
	add.w	d3,d0
	movem.l	d0/d3,-(sp)
	move.w	d0,d3
	moveq	#REN_SPRW,d0
	bsr	ren_count
	movem.l	(sp)+,d0/d3
.xn:	addq.w	#1,d1
	cmp.w	#4,d1
	blo	.x
	addq.w	#1,d6
	cmp.w	#4,d6
	blo	.y
	lea	SL_SIZE(a2),a2
.t:	dbf	d7,.s
	sf	ren_smap
	rts

; d0.w = a picture line: Z clear when it is in the HUD bars' region (the bar lines at the top and at the bottom: the
; palette ren_hpal).  Keeps all.
ren_in_hud:
	tst.w	ren_hudn
	beq	.no
	cmp.w	#224,d0
	bhs	.no			; (the guard lines, above and below: the playfield's)
	cmp.w	ren_htop,d0
	blt	.yes
	cmp.w	ren_hbot,d0
	bge	.yes
.no:	cmp.w	d0,d0			; (Z set)
	rts
.yes:	tst.w	ren_hudn		; (Z clear: ren_hudn is not 0 here)
	rts

; d3.w = a pen, d0.w = its weight: counted (ren_ch), or in the quality check (ren_qmode) its colour now against its
; index's STE colour (Oklab, L1 of the byte coordinates) summed into ren_qsum, ren_qn.  Keeps all.
ren_count:
	tst.b	ren_qmode
	bne	.q
	movem.l	d1-d3/a0-a1,-(sp)	; the colour's histogram of the palette ren_smap (counts, sprite use, a pen)
	move.w	d3,d1
	move.w	d3,d2
	and.w	#$7ff,d1
	lsr.w	#8,d2
	lsr.w	#3,d2
	lsl.w	#8,d2
	lsl.w	#5,d2
	add.w	d2,d1
	lea	vio,a0
	add.w	d1,a0
	lea	ren_q4,a1
	moveq	#0,d1
	moveq	#0,d2
	move.b	(a0),d1
	move.b	(a1,d1.w),d2
	lsl.w	#4,d2
	move.b	$800(a0),d1
	or.b	(a1,d1.w),d2
	lsl.w	#4,d2
	move.b	$1000(a0),d1
	or.b	(a1,d1.w),d2		; r g b
	beq	.cx			; (black: index 0 anyway)
	tst.b	ren_smap
	beq	.c0
	add.w	#4096,d2
.c0:	lea	ren_cs,a1
	cmp.w	#$800,d3
	bhs	.ns
	st	(a1,d2.w)		; (a sprite's colour)
.ns:	add.w	d2,d2
	lea	ren_ch,a1
	add.w	d0,(a1,d2.l)
	lea	ren_cp,a1
	move.w	d3,(a1,d2.l)
.cx:	movem.l	(sp)+,d1-d3/a0-a1
	rts
.q:	tst.b	ren_smap
	bne	.qx			; (the playfield's colours only)
	movem.l	d0-d5/a0-a1,-(sp)
	move.w	d0,d5			; weight
	move.w	d3,d0
	bsr	ren_pen_index		; d1 = the index (the mapping's palette)
	lsl.w	#2,d1
	lea	ren_stelab,a1
	add.w	d1,a1			; its STE colour's Oklab
	move.w	d3,d0			; the pen's colour now
	move.w	d0,d1
	and.w	#$7ff,d0
	lsr.w	#8,d1
	lsr.w	#3,d1
	lsl.w	#8,d1
	lsl.w	#5,d1
	add.w	d1,d0
	lea	vio,a0
	add.w	d0,a0
	moveq	#0,d1
	moveq	#0,d2
	move.l	a1,-(sp)
	lea	ren_q4,a1
	move.b	(a0),d1
	move.b	(a1,d1.w),d2
	lsl.w	#4,d2
	move.b	$800(a0),d1
	or.b	(a1,d1.w),d2
	lsl.w	#4,d2
	move.b	$1000(a0),d1
	or.b	(a1,d1.w),d2
	move.l	(sp)+,a1
	lsl.w	#2,d2
	lea	ren_lab,a0
	add.w	d2,a0
	moveq	#0,d4			; the distance
	moveq	#3-1,d2
.d:	moveq	#0,d0
	moveq	#0,d1
	move.b	(a0)+,d0
	move.b	(a1)+,d1
	sub.w	d1,d0
	bpl	.p
	neg.w	d0
.p:	add.w	d0,d4
	dbf	d2,.d
	mulu	d5,d4
	add.l	d4,ren_qsum
	add.l	d5,ren_qn
	movem.l	(sp)+,d0-d5/a0-a1
.qx:	rts

; the overlay layers 0-3: two pixels of their visible non-empty cells
ren_sample_ovl:
	moveq	#0,d7
.o:	cmp.w	ren_novl,d7
	bhs	.out
	lea	ren_ovl,a0
	move.w	d7,d0
	add.w	d0,d0
	moveq	#0,d6
	move.b	(a0,d0.w),d6		; layer
	cmp.w	#4,d6
	bhs	.on
	move.w	d6,d0
	lsl.w	#4,d0
	lea	ren_lay,a3
	add.w	d0,a3
	move.w	d6,d0
	lsl.w	#8,d0
	lsl.w	#5,d0
	move.w	d0,ren_ooff
	moveq	#0,d0
	move.b	5(a3),d0
	move.w	d0,ren_obank
	move.w	2(a3),d5
	move.w	d5,d0
	and.w	#7,d0
	neg.w	d0
	addq.w	#4,d0
	move.w	d0,ren_sy		; (the row's middle line)
	lsr.w	#3,d5			; row
	moveq	#29-1,d4
.r:	move.w	ren_sy,d0
	bsr	ren_in_hud
	sne	ren_smap
	moveq	#0,d0
	move.b	7(a3),d0
	and.w	d0,d5
	move.w	(a3),d3
	lsr.w	#3,d3			; column
	moveq	#37-1,d2
.c:	and.w	#63,d3
	move.w	d3,d0
	add.w	d5,d0
	and.w	ren_smask,d0
	bne	.cn
	move.w	d5,d0
	lsl.w	#7,d0
	move.w	d3,d1
	add.w	d1,d1
	add.w	d1,d0
	add.w	ren_ooff,d0
	lea	vio+V_TILE,a0
	move.w	(a0,d0.w),d0
	and.w	#$3fff,d0
	lea	ren_chrflag,a0
	tst.b	(a0,d0.w)
	beq	.cn
	movem.l	d0/d2,-(sp)
	moveq	#2,d1
	move.w	ren_obank,d2
	bsr	ren_sample_chr
	movem.l	(sp)+,d0/d2
	movem.l	d0/d2,-(sp)
	moveq	#5,d1
	move.w	ren_obank,d2
	bsr	ren_sample_chr
	movem.l	(sp)+,d0/d2
.cn:	addq.w	#1,d3
	dbf	d2,.c
	addq.w	#1,d5
	addq.w	#8,ren_sy
	dbf	d4,.r
.on:	addq.w	#1,d7
	bra	.o
.out:	sf	ren_smap
	rts

; Every REN_QPER pictures (not in a new scene): the colours on screen now (a light sample: a pixel of every 16th cell,
; the sprites) against the STE colours of their indices; much worse than the first check after the colours were
; chosen (half as large again and 8 more): new colours (the screen shows colours the choice did not see).
ren_quality:
	addq.w	#1,ren_qcount
	cmp.w	#REN_QPER,ren_qcount
	blo	.out
	clr.w	ren_qcount
	tst.b	ren_scene
	bne	.out
	tst.b	ren_black
	bne	.out
	tst.b	ren_allblack
	bne	.out
	addq.l	#1,ren_qchecks
	; the STE colours' Oklab
	lea	ren_pal,a0
	lea	ren_stelab,a1
	lea	ren_lab,a2
	lea	ren_stelev(pc),a3
	moveq	#16-1,d7
.sl:	move.w	(a0)+,d0
	moveq	#0,d1
	move.w	d0,d2			; STE nibble -> level
	lsr.w	#8,d2
	and.w	#15,d2
	move.b	(a3,d2.w),d1
	lsl.w	#4,d1
	move.w	d0,d2
	lsr.w	#4,d2
	and.w	#15,d2
	or.b	(a3,d2.w),d1
	lsl.w	#4,d1
	move.w	d0,d2
	and.w	#15,d2
	or.b	(a3,d2.w),d1
	lsl.w	#2,d1
	move.l	(a2,d1.w),(a1)+
	dbf	d7,.sl
	clr.l	ren_qsum
	clr.l	ren_qn
	st	ren_qmode
	move.w	#15,ren_smask
	bsr	ren_sample_group
	bsr	ren_sample_ovl
	bsr	ren_sample_sprites
	sf	ren_qmode
	clr.w	ren_smask
	move.l	ren_qn,d1
	beq	.out
	move.l	ren_qsum,d0
	divu	d1,d0			; (the mean distance * 1: < 765)
	and.l	#$ffff,d0
	move.w	d0,ren_qlast
	tst.w	ren_qbase
	bpl	.cmp
	move.w	d0,ren_qbase		; (the first check after the choice)
	bra	.out
.cmp:	move.w	ren_qbase,d1
	move.w	d1,d2
	lsr.w	#1,d2
	add.w	d2,d1
	addq.w	#8,d1
	cmp.w	d1,d0
	bls	.out
	addq.l	#1,ren_requal
	bsr	ren_cluster		; (new colours: the buffers again)
.out:	rts

; the STE's nibble -> its 4-bit level
ren_stelev:
	dc.b	0,2,4,6,8,10,12,14,1,3,5,7,9,11,13,15
	even

; The palette ren_curmap from its histogram: the points (a distinct colour each, weighted by 16 x the root of its
; samples, 4 times that when a sprite uses it), the median cut's boxes as seeds, REN_LLOYD rounds of k-means (each
; colour to the nearest centre, each centre to its colours' weighted mean), then each centre's representative: the
; colour nearest it (a pen of that colour: ren_rep / ren_hrep, whose colour the STE shows, fades included).
REN_LLOYD = 12
ren_palette_of:
	movem.l	d0-d7/a0-a6,-(sp)
	lea	ren_ch,a2
	lea	ren_cs,a4
	lea	ren_cp,a6
	tst.b	ren_curmap
	beq	.m0
	lea	8192(a2),a2
	lea	4096(a4),a4
	lea	8192(a6),a6
.m0:	lea	ren_pts,a3
	lea	ren_lab,a5
	moveq	#0,d7			; points
	moveq	#0,d6			; colour
.pt:	move.w	(a2)+,d5
	beq	.pn
	moveq	#0,d0			; 16 * sqrt(count)
	move.w	d5,d0
	lsl.l	#8,d0
	bsr	ren_isqrt
	tst.b	(a4,d6.w)
	beq	.w
	lsl.w	#2,d0			; (a sprite's colour)
.w:	move.w	d0,(a3)+		; weight
	move.w	d6,d0
	lsl.w	#2,d0
	move.b	(a5,d0.w),(a3)+		; L a b
	move.b	1(a5,d0.w),(a3)+
	move.b	2(a5,d0.w),(a3)+
	clr.b	(a3)+
	move.w	d6,d0
	add.w	d0,d0
	move.w	(a6,d0.w),(a3)+		; a pen of it
	addq.w	#1,d7
	cmp.w	#REN_MAXPTS,d7
	bhs	.pe
.pn:	addq.w	#1,d6
	cmp.w	#4096,d6
	blo	.pt
.pe:	move.w	d7,ren_npts
	bsr	ren_median_cut		; the boxes
	bsr	ren_lloyd		; the centres, refined; the representatives
	movem.l	(sp)+,d0-d7/a0-a6
	rts

; d0.l -> d0.w = its integer square root (d0 < 2^30).  Keeps the rest.
ren_isqrt:
	movem.l	d1-d4,-(sp)
	move.l	d0,d2
	moveq	#0,d3			; root
	move.l	#$4000,d4
.r:	move.l	d3,d1
	add.l	d4,d1
	move.l	d1,d0
	mulu	d1,d0
	cmp.l	d2,d0
	bhi	.rn
	move.l	d1,d3
.rn:	lsr.l	#1,d4
	bne	.r
	move.l	d3,d0
	movem.l	(sp)+,d1-d4
	rts

; The boxes' weighted means as the centres (index 1-n, ren_cent of the palette ren_curmap), REN_LLOYD rounds of
; k-means over the points, the representatives.
ren_lloyd:
	movem.l	d0-d7/a0-a6,-(sp)
	move.w	ren_nbox,d0
	tst.w	ren_npts
	bne	.has
	moveq	#0,d0
.has:	lea	ren_ncent,a0
	tst.b	ren_curmap
	beq	.n0
	addq.l	#2,a0
.n0:	move.w	d0,(a0)
	beq	.out
	; the sums per centre (weight, L, a, b: longs) from the boxes
	bsr	ren_ksum_clear
	lea	ren_pts,a3
	moveq	#0,d7			; box
.bx:	move.w	d7,d0
	lsl.w	#4,d0
	lea	ren_boxes,a2
	add.w	d0,a2
	move.w	(a2),d6
.bp:	cmp.w	2(a2),d6
	bhs	.bn
	move.w	d6,d0
	lsl.w	#3,d0
	lea	(a3,d0.w),a0
	move.w	d7,d1
	addq.w	#1,d1
	bsr	ren_ksum_add
	addq.w	#1,d6
	bra	.bp
.bn:	addq.w	#1,d7
	cmp.w	ren_nbox,d7
	blo	.bx
	bsr	ren_ksum_centres
	; the rounds
	moveq	#REN_LLOYD-1,d7
.round:	bsr	ren_ksum_clear
	lea	ren_pts,a0
	move.w	ren_npts,d6
	subq.w	#1,d6
.pp:	movem.l	d6-d7/a0,-(sp)
	addq.l	#2,a0			; (its L a b)
	bsr	ren_nearest
	movem.l	(sp)+,d6-d7/a0
	bsr	ren_ksum_add
	addq.l	#8,a0
	dbf	d6,.pp
	bsr	ren_ksum_centres
	dbf	d7,.round
	; the representatives: per centre the point nearest it
	lea	ren_rep+2,a4
	tst.b	ren_curmap
	beq	.r0
	lea	ren_hrep+2,a4
.r0:	lea	ren_cent+4,a1
	tst.b	ren_curmap
	beq	.r1
	lea	16*4(a1),a1
.r1:	moveq	#15-1,d7
.rc:	clr.w	(a4)
	lea	ren_pts,a0
	move.w	ren_npts,d6
	subq.w	#1,d6
	move.w	#$7fff,d5
.rp:	moveq	#0,d0
	moveq	#0,d2
	moveq	#0,d4
	move.b	2(a0),d0
	move.b	(a1),d2
	sub.w	d2,d0
	bpl	.a1
	neg.w	d0
.a1:	move.w	d0,d4
	moveq	#0,d0
	move.b	3(a0),d0
	move.b	1(a1),d2
	sub.w	d2,d0
	bpl	.a2
	neg.w	d0
.a2:	add.w	d0,d4
	moveq	#0,d0
	move.b	4(a0),d0
	move.b	2(a1),d2
	sub.w	d2,d0
	bpl	.a3
	neg.w	d0
.a3:	add.w	d0,d4
	cmp.w	d5,d4
	bhs	.rn
	move.w	d4,d5
	move.w	6(a0),(a4)
.rn:	addq.l	#8,a0
	dbf	d6,.rp
	addq.l	#2,a4
	addq.l	#4,a1
	dbf	d7,.rc
.out:	movem.l	(sp)+,d0-d7/a0-a6
	rts

ren_ksum_clear:
	lea	ren_ksum,a1
	moveq	#16*4-1,d0
.c:	clr.l	(a1)+
	dbf	d0,.c
	rts

; a0 = a point, d1.w = its centre (1-15): its weight and weighted L a b into the centre's sums.  Keeps all.
ren_ksum_add:
	movem.l	d0-d2/a1,-(sp)
	lea	ren_ksum,a1
	lsl.w	#4,d1
	add.w	d1,a1
	moveq	#0,d2
	move.w	(a0),d2			; weight
	add.l	d2,(a1)+
	moveq	#0,d0
	move.b	2(a0),d0
	mulu	d2,d0
	add.l	d0,(a1)+
	moveq	#0,d0
	move.b	3(a0),d0
	mulu	d2,d0
	add.l	d0,(a1)+
	moveq	#0,d0
	move.b	4(a0),d0
	mulu	d2,d0
	add.l	d0,(a1)
	movem.l	(sp)+,d0-d2/a1
	rts

; the centres (ren_cent of ren_curmap, 1-n) = their sums / weights (an empty one stays)
ren_ksum_centres:
	movem.l	d0-d6/a0-a1,-(sp)
	lea	ren_ksum+16,a0
	lea	ren_cent+4,a1
	move.w	ren_ncent,d6
	tst.b	ren_curmap
	beq	.m0
	lea	16*4(a1),a1
	move.w	ren_ncent+2,d6
.m0:	subq.w	#1,d6
	bmi	.out
.c:	move.l	(a0)+,d4		; weight
	beq	.skip
	move.l	(a0)+,d1
	move.l	(a0)+,d2
	move.l	(a0)+,d3
.sc:	cmp.l	#$ffff,d4		; (divu: a 16-bit divisor)
	bls	.dv
	lsr.l	#1,d4
	lsr.l	#1,d1
	lsr.l	#1,d2
	lsr.l	#1,d3
	bra	.sc
.dv:	divu	d4,d1
	divu	d4,d2
	divu	d4,d3
	move.b	d1,(a1)+
	move.b	d2,(a1)+
	move.b	d3,(a1)+
	addq.l	#1,a1
	dbf	d6,.c
	bra	.out
.skip:	lea	12(a0),a0
	addq.l	#4,a1
	dbf	d6,.c
.out:	movem.l	(sp)+,d0-d6/a0-a1
	rts

; The median cut of the points (ren_pts: weight.w, L a b, 0, pen.w) into up to 15 boxes: the box whose widest axis
; times the root of its weight is largest splits at its weighted median on that axis (the lower values and the median
; go left).  The tree (ren_tree, 4 bytes a node: axis 0-2 or $80 + box, threshold, left, right) and the boxes'
; representatives (ren_rep: the point nearest the box's weighted mean).
REN_BOX = 16				; a box: first, end (point numbers), node, score.l, axis, pad, weight.l
ren_median_cut:
	lea	ren_tree,a0
	move.b	#$80,(a0)		; one leaf: box 0
	move.w	#1,ren_ntree
	lea	ren_boxes,a1
	clr.w	(a1)
	move.w	ren_npts,2(a1)
	clr.w	4(a1)
	move.w	#1,ren_nbox
	tst.w	ren_npts
	beq	.reps
	moveq	#0,d0
	bsr	ren_box_score
.loop:	cmp.w	#15,ren_nbox
	bhs	.reps
	; the box to split
	lea	ren_boxes,a1
	moveq	#-1,d6			; its number
	moveq	#0,d5			; its score
	moveq	#0,d7
.best:	move.w	d7,d0
	lsl.w	#4,d0
	move.l	6(a1,d0.w),d1
	cmp.l	d5,d1
	bls	.bn
	move.l	d1,d5
	move.w	d7,d6
.bn:	addq.w	#1,d7
	cmp.w	ren_nbox,d7
	blo	.best
	tst.w	d6
	bmi	.reps
	; its weighted median on its axis: a histogram of the 256 values
	move.w	d6,d0
	lsl.w	#4,d0
	lea	(a1,d0.w),a2		; the box
	lea	ren_axh,a0
	move.w	#256-1,d0
.ac:	clr.l	(a0)+
	dbf	d0,.ac
	moveq	#0,d4
	move.b	10(a2),d4		; axis
	lea	ren_pts,a3
	move.w	(a2),d0
	lsl.w	#3,d0
	add.w	d0,a3
	move.w	2(a2),d7
	sub.w	(a2),d7
	subq.w	#1,d7
	lea	ren_axh,a0
	moveq	#0,d3			; the total weight
.ah:	moveq	#0,d0
	move.b	2(a3,d4.w),d0
	lsl.w	#2,d0
	moveq	#0,d1
	move.w	(a3),d1
	add.l	d1,(a0,d0.w)
	add.l	d1,d3
	addq.l	#8,a3
	dbf	d7,.ah
	; the smallest value whose running sum reaches half the weight, below the largest value present
	moveq	#0,d0			; value
	moveq	#0,d1			; running sum
	moveq	#-1,d2			; the last value present below
.ms:	move.w	d0,d7
	lsl.w	#2,d7
	move.l	(a0,d7.w),d7
	beq	.mn
	add.l	d7,d1
	move.l	d1,d7
	add.l	d7,d7
	cmp.l	d3,d7
	bhs	.mf
	move.w	d0,d2
.mn:	addq.w	#1,d0
	cmp.w	#256,d0
	blo	.ms
	bra	.reps			; (cannot happen)
.mf:	cmp.l	d3,d1			; everything at or below this value: the one below
	bne	.mt
	move.w	d2,d0
	bmi	.nosplit
.mt:	move.w	d0,d2			; the threshold
	; partition: values <= threshold first
	lea	ren_pts,a3
	move.w	(a2),d0
	lsl.w	#3,d0
	lea	(a3,d0.w),a4		; low
	move.w	2(a2),d0
	lsl.w	#3,d0
	lea	(a3,d0.w),a5		; high (end)
.pl:	cmp.l	a5,a4
	bhs	.pd
	cmp.b	2(a4,d4.w),d2
	bcs	.sw			; (value > threshold)
	addq.l	#8,a4
	bra	.pl
.sw:	subq.l	#8,a5
	move.l	(a4),d0
	move.l	(a5),(a4)
	move.l	d0,(a5)
	move.l	4(a4),d0
	move.l	4(a5),4(a4)
	move.l	d0,4(a5)
	bra	.pl
.pd:	move.l	a4,d0
	sub.l	#ren_pts,d0
	lsr.l	#3,d0			; the first point of the right box
	; the tree: the box's leaf becomes a split node with two new leaves
	lea	ren_tree,a0
	move.w	4(a2),d1
	lsl.w	#2,d1
	move.b	d4,(a0,d1.w)
	move.b	d2,1(a0,d1.w)
	move.w	ren_ntree,d3
	move.b	d3,2(a0,d1.w)		; left: the old box
	move.w	d3,4(a2)
	lsl.w	#2,d3
	move.b	d6,(a0,d3.w)
	or.b	#$80,(a0,d3.w)
	move.w	ren_ntree,d3
	addq.w	#1,d3
	move.b	d3,3(a0,d1.w)		; right: a new box
	lsl.w	#2,d3
	move.w	ren_nbox,d7
	move.b	d7,(a0,d3.w)
	or.b	#$80,(a0,d3.w)
	addq.w	#2,ren_ntree
	move.w	d7,d1
	lsl.w	#4,d1
	lea	(a1,d1.w),a3		; the new box
	move.w	d0,(a3)
	move.w	2(a2),2(a3)
	move.w	ren_ntree,d3
	subq.w	#1,d3
	move.w	d3,4(a3)
	move.w	d0,2(a2)
	addq.w	#1,ren_nbox
	move.w	d6,d0
	bsr	ren_box_score
	move.w	d7,d0
	bsr	ren_box_score
	bra	.loop
.nosplit:
	clr.l	6(a2)			; (a box of one value: no score)
	bra	.loop
	; the representatives
.reps:	rts

; d0.w = a box: its extents, the widest axis and its score (extent * the root of the weight)
ren_box_score:
	movem.l	d0-d7/a0-a3,-(sp)
	lsl.w	#4,d0
	lea	ren_boxes,a2
	add.w	d0,a2
	lea	ren_pts,a3
	move.w	(a2),d0
	lsl.w	#3,d0
	add.w	d0,a3
	move.w	2(a2),d7
	sub.w	(a2),d7
	subq.w	#1,d7
	moveq	#-1,d1			; minima (bytes 0-2 of d1: as words in d1, d2, d3)
	move.w	#255,d1
	move.w	#255,d2
	move.w	#255,d3
	moveq	#0,d4			; maxima
	moveq	#0,d5
	moveq	#0,d6
	move.l	#0,a0			; weight
.p:	moveq	#0,d0
	move.b	2(a3),d0
	cmp.w	d1,d0
	bhs	.1
	move.w	d0,d1
.1:	cmp.w	d4,d0
	bls	.2
	move.w	d0,d4
.2:	move.b	3(a3),d0
	cmp.w	d2,d0
	bhs	.3
	move.w	d0,d2
.3:	cmp.w	d5,d0
	bls	.4
	move.w	d0,d5
.4:	move.b	4(a3),d0
	cmp.w	d3,d0
	bhs	.5
	move.w	d0,d3
.5:	cmp.w	d6,d0
	bls	.6
	move.w	d0,d6
.6:	move.w	(a3),d0
	add.l	d0,a0
	addq.l	#8,a3
	dbf	d7,.p
	sub.w	d1,d4			; extents
	sub.w	d2,d5
	sub.w	d3,d6
	moveq	#0,d0			; the widest
	move.w	d4,d1
	cmp.w	d1,d5
	bls	.a1
	moveq	#1,d0
	move.w	d5,d1
.a1:	cmp.w	d1,d6
	bls	.a2
	moveq	#2,d0
	move.w	d6,d1
.a2:	move.b	d0,10(a2)
	move.l	a0,12(a2)
	; the root of the weight (bit by bit)
	move.l	a0,d2
	moveq	#0,d3			; root
	move.l	#$4000,d4
.r:	move.l	d3,d5
	add.l	d4,d5
	move.l	d5,d6
	mulu	d5,d6
	cmp.l	d2,d6
	bhi	.rn
	move.l	d5,d3
.rn:	lsr.l	#1,d4
	bne	.r
	mulu	d3,d1
	move.l	d1,6(a2)
	movem.l	(sp)+,d0-d7/a0-a3
	rts

; a2 = a box -> d0.w = the pen of its point nearest its weighted mean.  Keeps d1-d7/a0-a6.
ren_box_rep:
	movem.l	d1-d7/a0-a3,-(sp)
	lea	ren_pts,a3
	move.w	(a2),d0
	lsl.w	#3,d0
	add.w	d0,a3
	move.w	2(a2),d7
	sub.w	(a2),d7
	subq.w	#1,d7
	bmi	.none
	move.l	a3,a1
	move.w	d7,d6
	moveq	#0,d1			; sums
	moveq	#0,d2
	moveq	#0,d3
	moveq	#0,d4			; weight
.s:	move.w	(a1),d5
	ext.l	d5
	add.l	d5,d4
	moveq	#0,d0
	move.b	2(a1),d0
	mulu	d5,d0
	add.l	d0,d1
	moveq	#0,d0
	move.b	3(a1),d0
	mulu	d5,d0
	add.l	d0,d2
	moveq	#0,d0
	move.b	4(a1),d0
	mulu	d5,d0
	add.l	d0,d3
	addq.l	#8,a1
	dbf	d6,.s
	divu	d4,d1			; (weights < 65536 * 255: the quotients fit)
	divu	d4,d2
	divu	d4,d3
	move.l	#$7fffffff,d6		; the best distance
	moveq	#0,d0
.n:	moveq	#0,d4
	move.b	2(a3),d4
	sub.w	d1,d4
	muls	d4,d4
	moveq	#0,d5
	move.b	3(a3),d5
	sub.w	d2,d5
	muls	d5,d5
	add.l	d5,d4
	moveq	#0,d5
	move.b	4(a3),d5
	sub.w	d3,d5
	muls	d5,d5
	add.l	d5,d4
	cmp.l	d6,d4
	bhs	.nn
	move.l	d4,d6
	move.w	6(a3),d0
.nn:	addq.l	#8,a3
	dbf	d7,.n
	movem.l	(sp)+,d1-d7/a0-a3
	rts
.none:	moveq	#0,d0
	movem.l	(sp)+,d1-d7/a0-a3
	rts

; ======================================================================================================================
; stubs of the later parts
; ======================================================================================================================
; ======================================================================================================================
; The fixed layers (4 and 5: 36 x 28 cells, not scrolled)
; ======================================================================================================================
; A cell is "solid" when the topmost enabled fixed layer with something there is opaque in all of it.  A cell row of
; 36 solid cells of one priority is a bar row: its lines show only the fixed layers (and sprites of at least that
; priority), so the buffers' bar lines are copies of the bar image ren_fi (made from the cells, 336 pixels a line: the
; screen's x 0-319, black side bands), copied at the window's position (ren_bars).  The other non-empty cells are drawn
; per picture as an overlay (ren_overlay).  ren_bar_line[y] = the bar's priority + 1 (0: no bar).
ren_fixed:
	lea	vio+V_CTRL,a0
	lea	ren_fix,a1
	moveq	#4,d7
.l:	move.b	$10(a0,d7.w),d0
	btst	#3,d0
	seq	(a1)+			; enabled
	and.b	#7,d0
	move.b	d0,(a1)+		; pri
	moveq	#7,d0
	and.b	$18(a0,d7.w),d0
	move.b	d0,(a1)+		; bank
	clr.b	(a1)+
	addq.w	#1,d7
	cmp.w	#6,d7
	blo	.l
	; top first: the higher priority (equal: layer 5)
	lea	ren_fix,a1
	lea	ren_fixord,a2
	moveq	#0,d6
	move.b	1(a1),d0		; layer 4's priority
	move.b	5(a1),d1		; layer 5's
	cmp.b	d0,d1
	bhs	.f5
	bsr	.add4
	bsr	.add5
	bra	.fo
.f5:	bsr	.add5
	bsr	.add4
.fo:	move.w	d6,ren_nfix
	; changed: every cell again
	move.l	ren_fix,d0
	move.l	ren_fix+4,d1
	cmp.l	ren_fix_old,d0
	bne	.chg
	cmp.l	ren_fix_old+4,d1
	beq	.diff
.chg:	move.l	d0,ren_fix_old
	move.l	d1,ren_fix_old+4
	lea	ren_fdirty,a0
	move.w	#1008-1,d0
.fd:	st	(a0)+
	dbf	d0,.fd
	lea	vio+V_TILE+$7010,a0	; the copy
	lea	ren_tcopy+$7010,a1
	move.w	#$800/4-1,d0
.fc:	move.l	(a0)+,(a1)+
	dbf	d0,.fc
	lea	vio+V_TILE+$7810,a0
	lea	ren_tcopy+$7810,a1
	move.w	#$800/4-1,d0
.fc2:	move.l	(a0)+,(a1)+
	dbf	d0,.fc2
	st	ren_fany
	bra	.cells
.diff:	ifd	TILE_FLAG
	tst.b	tile_written_fix
	beq	.cells
	sf	tile_written_fix
	endc
	move.w	#$7010,d5
	bsr	.cmp
	move.w	#$7810,d5
	bsr	.cmp
.cells:	; the dirty cells: their class; the rows whose cells changed: bar or not
	tst.b	ren_fany
	beq	.ovl
	sf	ren_fany
	bsr	ren_fix_vis
	lea	ren_fdirty,a2
	moveq	#0,d5			; row
.r:	moveq	#0,d4			; column
	sf	ren_rowchg
.c:	tst.b	(a2)
	beq	.cn
	sf	(a2)
	bsr	ren_fix_class
	st	ren_rowchg
.cn:	addq.l	#1,a2
	addq.w	#1,d4
	cmp.w	#36,d4
	blo	.c
	tst.b	ren_rowchg
	beq	.rn
	bsr	ren_fix_row
.rn:	addq.w	#1,d5
	cmp.w	#28,d5
	blo	.r
	; the bars' line count and running sum
	lea	ren_bar_line,a0
	lea	ren_bar_cum,a1
	moveq	#0,d0
	moveq	#0,d1
.cu:	move.w	d1,(a1)+
	tst.b	(a0)+
	beq	.cz
	addq.w	#1,d1
.cz:	addq.w	#1,d0
	cmp.w	#224,d0
	blo	.cu
	move.w	d1,(a1)+
	move.w	d1,ren_nbar
	moveq	#0,d1			; the highest bar value
	lea	ren_frow,a0
	moveq	#28-1,d0
.bm:	cmp.b	(a0)+,d1
	bhs	.bmn
	move.b	-1(a0),d1
.bmn:	dbf	d0,.bm
	move.b	d1,ren_barmax
	; the HUD region: the bar lines at the top and at the bottom (their own palette, ren_hpal)
	lea	ren_bar_line,a0
	moveq	#0,d0
.ht:	cmp.w	#224,d0
	bhs	.hb
	tst.b	(a0,d0.w)
	beq	.hb
	addq.w	#1,d0
	bra	.ht
.hb:	move.w	#224,d1
.hb2:	cmp.w	d0,d1
	bls	.hc
	tst.b	-1(a0,d1.w)
	beq	.hc
	subq.w	#1,d1
	bra	.hb2
.hc:	ifd	REN_ONEPAL		; (one palette for all lines: no raster palette change needed)
	moveq	#0,d0
	move.w	#224,d1
	endc
	cmp.w	ren_htop,d0
	bne	.hn
	cmp.w	ren_hbot,d1
	beq	.ovl
.hn:	move.w	d0,ren_htop
	move.w	d1,ren_hbot
	move.w	#224,d2
	sub.w	d1,d2
	add.w	d0,d2
	move.w	d2,ren_hudn
	st	ren_scene		; (other HUD lines: the colours again)
.ovl:	; non-empty cells outside the bar rows: the enabled fixed layers are overlays too
	lea	ren_frow,a0
	lea	ren_fne,a1
	moveq	#28-1,d0
	moveq	#0,d1
.ne:	tst.b	(a0)+
	bne	.nb
	add.b	(a1),d1
.nb:	addq.l	#1,a1
	dbf	d0,.ne
	tst.w	d1
	beq	.srt
	lea	ren_ovl,a0
	move.w	ren_novl,d0
	add.w	d0,d0
	add.w	d0,a0
	lea	ren_fix,a1
	tst.b	(a1)
	beq	.o5
	move.b	1(a1),d0		; (below the group with nothing but black and empty cells: it cannot show)
	cmp.b	ren_grp_min,d0
	bhs	.a4o
	tst.b	ren_grp_n
	beq	.a4o
	tst.w	ren_fvis
	beq	.o5
.a4o:	move.b	#4,(a0)+
	move.b	1(a1),(a0)+
	addq.w	#1,ren_novl
.o5:	tst.b	4(a1)
	beq	.srt
	move.b	5(a1),d0
	cmp.b	ren_grp_min,d0
	bhs	.a5o
	tst.b	ren_grp_n
	beq	.a5o
	tst.w	ren_fvis+2
	beq	.srt
.a5o:	move.b	#5,(a0)+
	move.b	5(a1),(a0)+
	addq.w	#1,ren_novl
.srt:	bra	ren_ovl_sort
.add4:	tst.b	(a1)
	beq	.a4
	move.w	#$7010,(a2)+
	move.b	2(a1),(a2)+
	move.b	1(a1),(a2)+
	addq.w	#1,d6
.a4:	rts
.add5:	tst.b	4(a1)
	beq	.a5
	move.w	#$7810,(a2)+
	move.b	6(a1),(a2)+
	move.b	5(a1),(a2)+
	addq.w	#1,d6
.a5:	rts
; d5 = a fixed layer's offset in tile RAM: its changed longs mark their cells
.cmp:	lea	vio+V_TILE,a0
	add.w	d5,a0
	lea	ren_tcopy,a1
	add.w	d5,a1
	move.w	#504-1,d1
.cl:	cmpm.l	(a0)+,(a1)+
	dbne	d1,.cl
	beq	.ce
	move.l	-4(a0),-4(a1)
	move.w	#503,d0
	sub.w	d1,d0
	add.w	d0,d0			; the first word's cell
	lea	ren_fdirty,a2
	st	(a2,d0.w)
	st	1(a2,d0.w)
	st	ren_fany
	dbf	d1,.cl
.ce:	rts

; ren_fvis: per fixed layer the cells that can show something other than black (not empty, not an opaque character of
; one black pen: ren_chruni and the mapping's palette).  Keeps d4-d7/a2.
ren_fix_vis:
	movem.l	d4-d7/a2,-(sp)
	lea	ren_fvis,a2
	lea	ren_fix,a3
	move.w	#$7010,d6
	bsr	.layer
	addq.l	#4,a3
	move.w	#$7810,d6
	bsr	.layer
	movem.l	(sp)+,d4-d7/a2
	rts
.layer:	moveq	#0,d7			; count
	lea	vio+V_TILE,a0
	add.w	d6,a0
	lea	ren_chrflag,a4
	lea	ren_chruni,a5
	lea	ren_q4,a6
	moveq	#0,d5
	move.b	2(a3),d5
	lsl.w	#8,d5			; the bank's pens in the palette page
	move.w	#1008-1,d4
.c:	move.w	(a0)+,d0
	and.w	#$3fff,d0
	move.b	(a4,d0.w),d1
	beq	.n			; empty
	cmp.b	#2,d1
	bne	.v
	add.w	d0,d0
	move.w	(a5,d0.w),d1
	bmi	.v			; (more than one pen)
	add.w	d5,d1
	lea	ren_palsnap+$2000,a1
	add.w	d1,a1
	moveq	#0,d0
	move.b	(a1),d0
	tst.b	(a6,d0.w)
	bne	.v
	move.b	$800(a1),d0
	tst.b	(a6,d0.w)
	bne	.v
	move.b	$1000(a1),d0
	tst.b	(a6,d0.w)
	beq	.n			; (black)
.v:	addq.w	#1,d7
.n:	dbf	d4,.c
	move.w	d7,(a2)+
	rts

; the class of fixed cell (d5 row, d4 column) into ren_fcls: 0 empty, 1 partial (something, not opaque), $10 + the
; lowest priority among the layers that show in it when the layers together are opaque in all of it ("solid": the
; topmost layers down to the first opaque one); in a bar row, its pixels into the bar image.  Keeps d4-d7/a2.
ren_fix_class:
	movem.l	d4-d7/a2,-(sp)
	move.w	d5,d0
	mulu	#36,d0
	add.w	d4,d0
	move.w	d0,d3			; the cell's number
	add.w	d0,d0
	lea	ren_fixord,a2
	move.w	ren_nfix,d6
	moveq	#0,d1			; class
	moveq	#7,d5			; the lowest priority seen
	bra	.t
.m:	move.w	d0,d2
	add.w	(a2),d2
	lea	vio+V_TILE,a0
	move.w	(a0,d2.w),d2
	and.w	#$3fff,d2
	lea	ren_chrflag,a0
	move.b	(a0,d2.w),d7
	beq	.n			; empty here: the layer below
	moveq	#1,d1
	cmp.b	3(a2),d5
	bls	.lo
	move.b	3(a2),d5
.lo:	cmp.b	#2,d7
	bne	.n
	moveq	#$10,d1			; opaque: solid
	or.b	d5,d1
	bra	.done
.n:	addq.l	#4,a2
.t:	dbf	d6,.m
.done:	lea	ren_fcls,a0
	move.b	d1,(a0,d3.w)
	movem.l	(sp),d4-d5		; (the row and column again)
	; in a bar row: the bar image
	lea	ren_frow,a0
	tst.b	(a0,d5.w)
	beq	.out
	bsr	ren_fi_cell
.out:	movem.l	(sp)+,d4-d7/a2
	rts

; fixed cell (d5 row, d4 column): the fixed layers' composed pixels (top layers down to the first opaque one, merged
; bottom up by their masks) into the bar image.  Keeps all.
ren_fi_cell:
	movem.l	d0-d7/a0-a6,-(sp)
	move.w	d5,d0			; (a cell of the HUD region: the HUD's palette)
	lsl.w	#3,d0
	bsr	ren_in_hud
	sne	ren_curmap
	move.w	d5,d0
	mulu	#36,d0
	add.w	d4,d0
	add.w	d0,d0
	lea	ren_fixord,a2
	move.w	ren_nfix,d6
	lea	ren_src,a3		; per layer: chr data, mask, c2p table (16 bytes)
	moveq	#0,d3			; layers used
	bra	.t
.m:	move.w	d0,d2
	add.w	(a2),d2
	lea	vio+V_TILE,a0
	move.w	(a0,d2.w),d2
	and.w	#$3fff,d2
	lea	ren_chrflag,a0
	move.b	(a0,d2.w),d7
	beq	.n
	move.w	d0,-(sp)
	moveq	#0,d0
	move.b	2(a2),d0
	bsr	ren_mt_get
	move.l	a0,8(a3)
	moveq	#0,d1
	move.w	d2,d1
	lsl.l	#3,d1
	lea	ren_chrmask,a0
	add.l	d1,a0
	move.l	a0,4(a3)
	lea	ren_zero64,a0
	cmp.w	#REN_NCHR,d2
	bhs	.z
	lsl.l	#3,d1
	lea	ren_chr,a0
	add.l	d1,a0
.z:	move.l	a0,(a3)
	move.w	(sp)+,d0
	lea	16(a3),a3
	addq.w	#1,d3
	cmp.b	#2,d7
	beq	.got
.n:	addq.l	#4,a2
.t:	dbf	d6,.m
.got:	tst.w	d3
	beq	.out
	move.w	d5,d1
	lsl.w	#3,d1
	mulu	#FI_STRIDE,d1
	lea	ren_fi,a4
	add.l	d1,a4
	move.w	d4,d1
	lsr.w	#1,d1
	addq.w	#1,d1
	lsl.w	#3,d1
	move.w	d4,d2
	and.w	#1,d2
	add.w	d2,d1
	add.w	d1,a4			; the cell's byte at screen x 16 + 8 * column
	moveq	#0,d7			; row
.row:	moveq	#0,d6			; the composed row
	move.w	d3,d5
	subq.w	#1,d5
	move.w	d5,d0
	lsl.w	#4,d0
	lea	ren_src,a3
	add.w	d0,a3			; the bottom layer
.l:	move.l	4(a3),a0
	moveq	#0,d0
	move.b	(a0,d7.w),d0
	beq	.ln
	lsl.w	#2,d0
	lea	ren_exp,a0
	move.l	(a0,d0.w),d2
	move.l	(a3),a0
	move.w	d7,d0
	lsl.w	#3,d0
	add.w	d0,a0
	move.l	8(a3),a1
	moveq	#0,d1
	rept	8
	moveq	#0,d0
	move.b	(a0)+,d0
	add.w	d0,d0
	add.w	d0,d0
	add.l	d1,d1
	or.l	(a1,d0.w),d1
	endr
	and.l	d2,d1
	not.l	d2
	and.l	d2,d6
	or.l	d1,d6
.ln:	lea	-16(a3),a3
	dbf	d5,.l
	movep.l	d6,0(a4)
	lea	FI_STRIDE(a4),a4
	addq.w	#1,d7
	cmp.w	#8,d7
	blo	.row
	addq.w	#1,ren_fi_ver
.out:	sf	ren_curmap
	movem.l	(sp)+,d0-d7/a0-a6
	rts

; fixed row d5 changed: bar or not (ren_frow, ren_bar_line); becoming a bar: its cells into the bar image; a change
; of the bar's lines: the group's cells there again (the buffers have bar lines at old window positions).  Keeps d5.
ren_fix_row:
	move.w	d5,d0
	mulu	#36,d0
	lea	ren_fcls,a0
	add.w	d0,a0
	move.l	a0,a1			; (the non-empty cells)
	moveq	#36-1,d0
	moveq	#0,d1
.ne:	tst.b	(a1)+
	beq	.nz
	addq.b	#1,d1
.nz:	dbf	d0,.ne
	lea	ren_fne,a1
	move.b	d1,(a1,d5.w)
	moveq	#0,d2			; the bar's value: the lowest priority + 1, 0 none
	moveq	#7,d3
	moveq	#36-1,d0
.c:	move.b	(a0)+,d1
	cmp.b	#$10,d1
	blo	.no
	and.b	#7,d1
	cmp.b	d1,d3
	bls	.cl
	move.b	d1,d3
.cl:	dbf	d0,.c
	cmp.b	ren_grp_max,d3
	blo	.no			; (a group layer above it: not a bar)
	move.b	d3,d2
	addq.b	#1,d2
.no:	lea	ren_frow,a0
	move.b	(a0,d5.w),d3
	move.b	d2,(a0,d5.w)
	cmp.b	d2,d3
	beq	.same
	st	ren_full		; (the bar's lines changed)
	lea	ren_bar_line,a0
	move.w	d5,d0
	lsl.w	#3,d0
	add.w	d0,a0
	moveq	#8-1,d0
.bl:	move.b	d2,(a0)+
	dbf	d0,.bl
	addq.w	#1,ren_fi_ver
	tst.b	d2
	beq	.same
	movem.l	d4-d5,-(sp)
	moveq	#0,d4
.fc:	bsr	ren_fi_cell
	addq.w	#1,d4
	cmp.w	#36,d4
	blo	.fc
	movem.l	(sp)+,d4-d5
.same:	rts

; The draw buffer's bar lines: all of them when the window moved or the bar image changed since this buffer had them,
; else the lines marked (sprites over them, group cells drawn there).  Four passes a run of lines (one a plane),
; shifted to the window's fine scroll.
ren_bars:
	move.w	ren_draw,d7
	move.w	d7,d6
	add.w	d6,d6
	lea	ren_bar_dirty,a2
	mulu	#224,d7
	add.w	d7,a2
	sf	ren_allbars
	lea	ren_bar_w,a0
	move.w	ren_w,d0
	cmp.w	(a0,d6.w),d0
	bne	.all
	lea	ren_bar_v,a0
	move.w	ren_fi_ver,d0
	cmp.w	(a0,d6.w),d0
	beq	.go
.all:	st	ren_allbars
	lea	ren_bar_w,a0
	move.w	ren_w,(a0,d6.w)
	lea	ren_bar_v,a0
	move.w	ren_fi_ver,(a0,d6.w)
.go:	tst.w	ren_nbar
	beq	.clr
	tst.b	ren_allbars
	bne	.some
	move.l	a2,a0			; (nothing marked: nothing to copy)
	moveq	#224/4-1,d0
.q:	tst.l	(a0)+
	dbne	d0,.q
	beq	.out
.some:
	; the Blitter: per plane, 21 words a line (20 unshifted)
	moveq	#15,d5
	and.w	ren_w,d5
	moveq	#21,d4
	tst.w	d5
	bne	.x
	moveq	#20,d4
.x:	move.w	d4,BLT_XC.w
	move.w	#8,BLT_SXI.w
	move.w	#8,BLT_DXI.w
	move.w	d4,d0
	subq.w	#1,d0
	lsl.w	#3,d0
	move.w	#FI_STRIDE,d1
	sub.w	d0,d1
	move.w	d1,BLT_SYI.w
	move.w	#REN_LINEB,d1
	sub.w	d0,d1
	move.w	d1,BLT_DYI.w
	moveq	#-1,d0
	lsr.w	d5,d0
	move.w	d0,BLT_E1.w
	move.w	#-1,BLT_E2.w
	move.w	#-1,BLT_E3.w
	move.w	#$0203,BLT_HOP.w
	move.b	d5,BLT_SKEW.w
	lea	ren_bar_line,a1
	moveq	#0,d3			; line
.ln:	tst.b	(a1,d3.w)
	beq	.nx
	tst.b	ren_allbars
	bne	.st
	tst.b	(a2,d3.w)
	beq	.nx
.st:	move.w	d3,d2			; a run: d3 .. d2 - 1
.rl:	addq.w	#1,d2
	cmp.w	#224,d2
	bhs	.re
	tst.b	(a1,d2.w)
	beq	.re
	tst.b	ren_allbars
	bne	.rl
	tst.b	(a2,d2.w)
	bne	.rl
.re:	bsr	ren_bar_copy
	move.w	d2,d3
	bra	.lt
.nx:	addq.w	#1,d3
.lt:	cmp.w	#224,d3
	blo	.ln
.clr:	moveq	#224/4-1,d0
.c:	clr.l	(a2)+
	dbf	d0,.c
.out:	rts

; bar lines d3 .. d2 - 1 into the draw buffer (the Blitter set up by ren_bars).  Keeps all.
ren_bar_copy:
	movem.l	d0-d7/a0,-(sp)
	move.w	d2,d7
	sub.w	d3,d7			; lines
	move.w	d3,d0
	mulu	#FI_STRIDE,d0
	add.l	#ren_fi,d0
	move.w	d3,d1
	add.w	#REN_GUARD,d1
	ext.l	d1
	moveq	#9,d2
	lsl.l	d2,d1
	move.w	ren_w,d2
	lsr.w	#4,d2
	lsl.w	#3,d2
	add.w	d2,d1
	add.l	ren_dbuf,d1
	moveq	#4-1,d6
.p:	move.l	d0,BLT_SRC.w
	move.l	d1,BLT_DST.w
	move.w	d7,BLT_YC.w
	bsr	blit_go
	addq.l	#2,d0
	addq.l	#2,d1
	dbf	d6,.p
	addq.l	#1,ren_barcopies
	movem.l	(sp)+,d0-d7/a0
	rts

; ======================================================================================================================
; Sprites
; ======================================================================================================================
; The list (ren_slist, SL_SIZE bytes an entry) of the visible sprites in the arcade's sprite RAM order from entry 0 up:
; the arcade draws from the last entry down and a pixel drawn once stays ("the first drawn wins"), so the STE draws the
; other way round, each over the earlier ones.  Player view: x' = 361 - x - width, y' = 240 - y - height of MAME's
; screen position (namcos1_sprite with the screen flipped), the image flipped as the attributes say.  The shadow colour
; ($7F, never seen in Splatterhouse) is not drawn.
SL_CODE	= 0				; .w the 32 x 32 cell
SL_COL	= 2				; .b colour
SL_TX	= 3				; .b the sub-rectangle's x in the cell
SL_TY	= 4				; .b its y
SL_SX	= 5				; .b width (4, 8, 16, 32)
SL_SY	= 6				; .b height
SL_FL	= 7				; .b bit 0 flip x, bit 1 flip y
SL_X	= 8				; .w picture x'
SL_Y	= 10				; .w picture y'
SL_PRI	= 12				; .b
SL_KEY	= 14				; .w (the attribute bits of the cache key)
SL_SIZE	= 16
ren_sprites_list:
	lea	vio+V_SPR,a0
	lea	ren_slist,a1
	moveq	#0,d7			; count
	moveq	#0,d5
	move.b	$7f4(a0),d5
	and.w	#1,d5
	lsl.w	#8,d5
	move.b	$7f5(a0),d5		; xoffs
	moveq	#0,d6
	move.b	$7f7(a0),d6		; yoffs
	add.w	#17,d6
	lea	ren_sizes(pc),a2
	lea	ren_sizes4(pc),a3
	lea	(a0),a4			; the entry
	; an entry whose attributes (and the offsets) did not change: last picture's result (ren_sprev: per entry
	; the copy of its 6 bytes, its list entry or none)
	move.l	$7f4(a0),d0
	and.l	#$01ff00ff,d0
	cmp.l	ren_soffs,d0
	beq	.same
	move.l	d0,ren_soffs
	lea	ren_sprev,a5		; (offsets changed: nothing reused: the copies made unequal)
	move.w	#127-1,d0
.inv:	move.l	10(a4),d1
	not.l	d1
	move.l	d1,(a5)
	move.w	14(a4),d1
	not.w	d1
	move.w	d1,4(a5)
	lea	16(a4),a4
	lea	SP_SIZE(a5),a5
	dbf	d0,.inv
	lea	vio+V_SPR,a4
.same:	lea	ren_sprev,a5
	lea	10(a4),a4		; (the attributes)
	move.w	#127-1,d4
.e:	cmpm.l	(a4)+,(a5)+
	bne	.new4
	cmpm.w	(a4)+,(a5)+
	bne	.new6
	tst.b	(a5)
	beq	.n6			; (invisible)
	move.l	2(a5),(a1)+		; (visible: its list entry again)
	move.l	6(a5),(a1)+
	move.l	10(a5),(a1)+
	move.l	14(a5),(a1)+
	addq.w	#1,d7
.n6:	lea	10(a4),a4
	lea	SP_SIZE-6(a5),a5
	dbf	d4,.e
	move.w	d7,ren_nspr
	rts
.new6:	subq.l	#2,a4
	subq.l	#2,a5
.new4:	lea	-14(a4),a4		; (the entry)
	subq.l	#4,a5
.new:	move.l	10(a4),(a5)
	move.w	14(a4),4(a5)
	sf	6(a5)
	st	7(a5)
	; x' = 361 - ((-(x + ((colour & 1) << 8) + xoffs) - width) & $1FF) - width: visible?
	moveq	#0,d1
	move.b	10(a4),d1		; attr1
	move.w	d1,d3
	lsr.w	#6,d3
	moveq	#0,d2
	move.b	(a2,d3.w),d2		; width
	moveq	#0,d0
	move.b	13(a4),d0
	btst	#0,12(a4)
	beq	.xh
	add.w	#$100,d0
.xh:	add.w	d5,d0
	add.w	d2,d0
	neg.w	d0
	and.w	#$1ff,d0
	neg.w	d0
	add.w	#361,d0
	sub.w	d2,d0
	cmp.w	#288,d0
	bge	.n
	move.w	d0,SL_X(a1)
	add.w	d2,d0
	ble	.n
	; y' = 240 - (((y + yoffs + 17) & $FF) - 16) - height
	moveq	#0,d0
	move.b	14(a4),d0		; attr2
	lsr.w	#1,d0
	and.w	#3,d0
	moveq	#0,d3
	move.b	(a2,d0.w),d3		; height
	moveq	#0,d0
	move.b	15(a4),d0
	add.w	d6,d0
	and.w	#$ff,d0
	neg.w	d0
	add.w	#256,d0
	sub.w	d3,d0
	cmp.w	#224,d0
	bge	.n
	move.w	d0,SL_Y(a1)
	add.w	d3,d0
	ble	.n
	moveq	#0,d0
	move.b	12(a4),d0
	lsr.b	#1,d0
	cmp.b	#$7f,d0
	beq	.n			; (shadow)
	move.b	d0,SL_COL(a1)
	move.b	d2,SL_SX(a1)
	move.b	d3,SL_SY(a1)
	; tx, ty: (attr & $18) & ~(size - 1); the key's bits: szx(2) szy(2) tx/8(2) ty/8(2) fx(1)
	moveq	#0,d2
	move.b	14(a4),d2		; attr2
	move.w	d1,d0
	and.w	#$18,d0
	moveq	#0,d3
	move.b	SL_SX(a1),d3
	and.b	-1(a3,d3.w),d0		; (~(size - 1) & $18)
	move.b	d0,SL_TX(a1)
	move.w	d1,d3
	lsr.w	#6,d3			; szx
	lsl.w	#2,d3
	move.w	d2,d0
	lsr.w	#1,d0
	and.w	#3,d0
	or.w	d0,d3			; szy
	lsl.w	#2,d3
	moveq	#0,d0
	move.b	SL_TX(a1),d0
	lsr.w	#3,d0
	or.w	d0,d3
	move.w	d2,d0
	and.w	#$18,d0
	moveq	#0,d1
	move.b	SL_SY(a1),d1
	and.b	-1(a3,d1.w),d0
	move.b	d0,SL_TY(a1)
	lsr.w	#3,d0
	lsl.w	#2,d3
	or.w	d0,d3
	moveq	#0,d0			; flips
	btst	#5,10(a4)
	beq	.nfx
	moveq	#1,d0
.nfx:	btst	#0,d2
	beq	.nfy
	addq.b	#2,d0
.nfy:	move.b	d0,SL_FL(a1)
	add.w	d3,d3
	and.w	#1,d0
	or.w	d0,d3
	move.w	d3,SL_KEY(a1)
	moveq	#7,d0			; code
	and.b	10(a4),d0
	lsl.w	#8,d0
	move.b	11(a4),d0
	move.w	d0,SL_CODE(a1)
	move.w	d2,d0
	lsr.w	#5,d0
	move.b	d0,SL_PRI(a1)
	st	6(a5)			; (kept for the next picture)
	move.l	(a1),8(a5)
	move.l	4(a1),12(a5)
	move.l	8(a1),16(a5)
	move.l	12(a1),20(a5)
	lea	SL_SIZE(a1),a1
	addq.w	#1,d7
.n:	lea	16+10(a4),a4
	lea	SP_SIZE(a5),a5
	dbf	d4,.e
	move.w	d7,ren_nspr
	rts
SP_SIZE	= 24

ren_sizes:
	dc.b	16,8,32,4
; size - 1 -> ~(size - 1) & $18, at size - 1 (4, 8, 16, 32)
ren_sizes4:
	dc.b	0,0,0,$18,0,0,0,$18,0,0,0,0,0,0,0,$10,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
	even

; ---- the cache of converted sprites and overlay cells --------------------------------------------------------------
; An entry: rows.w, first row.w (in the sub-rectangle), words a row (1 or 2: 16 or 32 pixels).w, 0.w, the rows' opaque
; masks (longs, left aligned), then per row the four planes' words (plane by plane: the Blitter's source runs through
; them without being set again).  Keys: sprites code << 16 | colour << 9 | the attribute bits; overlay cells
; $80000000 | bank << 14 | code.

; d0.l = key -> a1 = the entry or 0 (Z set: not there).  Uses d1, a0.
ren_cache_find:
	move.l	d0,d1
	swap	d1
	eor.w	d0,d1
	rol.w	#5,d1
	eor.w	d0,d1
	and.w	#REN_HASH-1,d1
	lsl.w	#3,d1
	lea	ren_hash,a0
	add.w	d1,a0
	cmp.l	(a0),d0
	bne	.no
	move.l	4(a0),a1
	move.l	a1,d1
	rts
.no:	move.l	a0,ren_slot
	sub.l	a1,a1
	moveq	#0,d1
	rts

; d0.l = key, d1.l = the entry's size: a1 = room for it in the pool, entered in the slot ren_cache_find left.  The
; pool full: everything goes (then the slot is still the key's).
ren_cache_new:
	move.l	d1,-(sp)
	move.l	ren_pool_ptr,a1
	add.l	a1,d1
	cmp.l	#ren_pool+REN_POOL,d1
	bls	.ok
	movem.l	d0/a0,-(sp)
	move.l	ren_slot,-(sp)
	bsr	ren_flush
	move.l	(sp)+,ren_slot
	movem.l	(sp)+,d0/a0
	move.l	ren_pool_ptr,a1
	move.l	(sp),d1
	add.l	a1,d1
.ok:	move.l	d1,ren_pool_ptr
	move.l	(sp)+,d1
	move.l	ren_slot,a0
	move.l	d0,(a0)+
	move.l	a1,(a0)
	addq.l	#1,ren_bakes
	rts

; d0.w = a sprite colour: a3 = its pair table (byte of two pixels * 16 + 4 * k -> their planes' bits as the k-th
; pair of 8 pixels: bits 7 - 2k (the left one) and 6 - 2k of each plane's byte), made when stale.  Keeps all but a3.
ren_pt_get:
	movem.l	d0-d7/a0-a2/a4,-(sp)
	move.w	d0,d7			; (colour; + 128 for the HUD's palette)
	tst.b	ren_curmap
	beq	.m0
	add.w	#128,d7
.m0:
	; its slot (REN_PTS of them, given round in turn): the colour's, made in this epoch?
	lea	ren_ptslot,a0
	moveq	#0,d1
	move.b	(a0,d7.w),d1		; (255: none)
	cmp.w	#REN_PTS,d1
	bhs	.new
	lea	ren_ptown,a0
	cmp.b	(a0,d1.w),d7
	bne	.new
	lea	ren_pt_ep,a0
	add.w	d1,d1
	move.w	ren_epoch,d0
	cmp.w	(a0,d1.w),d0
	bne	.make
	lsr.w	#1,d1
	bra	.ok
.new:	move.w	ren_ptnext,d1		; a slot for it
	addq.w	#1,ren_ptnext
	cmp.w	#REN_PTS,ren_ptnext
	blo	.n1
	clr.w	ren_ptnext
.n1:	lea	ren_ptslot,a0
	move.b	d1,(a0,d7.w)
	lea	ren_ptown,a0
	move.b	d7,(a0,d1.w)
	add.w	d1,d1
.make:	lea	ren_pt_ep,a0
	move.w	ren_epoch,(a0,d1.w)
	lsr.w	#1,d1
	move.w	d1,ren_ptcur
	; the colour's 15 indices' bits (15: transparent, 0)
	lea	ren_pt16,a1
	lea	ren_t16,a2
	move.w	d7,d6
	and.w	#127,d6
	lsl.w	#4,d6
	moveq	#0,d5
.i:	moveq	#0,d1
	cmp.w	#15,d5
	beq	.t
	move.w	d6,d0
	add.w	d5,d0
	bsr	ren_pen_index
	lsl.w	#2,d1
	move.l	(a2,d1.w),d1
.t:	move.l	d1,(a1)+
	addq.w	#1,d5
	cmp.w	#16,d5
	blo	.i
	moveq	#0,d0
	move.w	ren_ptcur,d0
	moveq	#12,d1
	lsl.l	d1,d0
	lea	ren_pt,a3
	add.l	d0,a3
	lea	ren_pt16,a1
	moveq	#0,d5			; left
.h:	move.w	d5,d0
	lsl.w	#2,d0
	move.l	(a1,d0.w),d2
	add.l	d2,d2
	moveq	#0,d4			; right
.l:	move.w	d4,d0
	lsl.w	#2,d0
	move.l	(a1,d0.w),d0
	or.l	d2,d0			; (the pair's bits: 1 the left pixel, 0 the right, in each plane's byte)
	move.l	d0,d1
	lsl.l	#6,d1
	move.l	d1,(a3)+		; (the pair first in its 8 pixels)
	move.l	d0,d1
	lsl.l	#4,d1
	move.l	d1,(a3)+
	move.l	d0,d1
	add.l	d1,d1
	add.l	d1,d1
	move.l	d1,(a3)+
	move.l	d0,(a3)+		; (last)
	addq.w	#1,d4
	cmp.w	#16,d4
	blo	.l
	addq.w	#1,d5
	cmp.w	#16,d5
	blo	.h
	move.w	ren_ptcur,d1
.ok:	moveq	#0,d0
	move.w	d1,d0
	moveq	#12,d1
	lsl.l	d1,d0
	lea	ren_pt,a3
	add.l	d0,a3
	movem.l	(sp)+,d0-d7/a0-a2/a4
	rts

; a2 = a list entry: a1 = its converted image (from the cache, or converted now)
ren_sprite_get:
	moveq	#0,d0
	move.w	SL_CODE(a2),d0
	swap	d0
	moveq	#0,d1
	move.b	SL_COL(a2),d1
	lsl.w	#8,d1
	add.w	d1,d1
	or.w	SL_KEY(a2),d1
	move.w	d1,d0
	tst.b	ren_curmap
	beq	.k0
	bset	#27,d0			; (the HUD's palette)
.k0:	bsr	ren_cache_find
	bne	.hit
	addq.l	#1,ren_misses
	movem.l	d0/d2-d7/a2-a6,-(sp)
	move.l	d0,d7			; key
	move.l	a2,a5			; (the list entry)
	; the rows that can have something: the sub-rectangle's rows within the cell's opaque box (ren_spr_idx)
	moveq	#0,d4
	move.b	SL_SX(a2),d4
	lsr.w	#1,d4			; bytes a row
	moveq	#0,d0
	move.w	SL_CODE(a2),d0
	lsl.w	#3,d0
	lea	ren_spr_idx,a0
	add.l	d0,a0
	moveq	#0,d2
	move.b	4(a0),d2		; y0
	moveq	#0,d3
	move.b	5(a0),d3		; y1
	cmp.w	#255,d2
	beq	.empty
	moveq	#0,d0
	move.b	SL_TY(a2),d0
	sub.w	d0,d2			; y0 - ty
	bpl	.r0
	moveq	#0,d2
.r0:	sub.w	d0,d3			; y1 - ty
	moveq	#0,d0
	move.b	SL_SY(a2),d0
	cmp.w	d0,d3
	blt	.r1
	move.w	d0,d3
	subq.w	#1,d3
.r1:	cmp.w	d2,d3
	blt	.empty
	moveq	#0,d0			; and its columns
	move.b	SL_TX(a2),d0
	lsr.w	#1,d0			; the first byte
	moveq	#0,d1
	move.b	7(a0),d1		; b1
	cmp.w	d1,d0
	bgt	.empty
	add.w	d4,d0
	subq.w	#1,d0			; the last byte
	move.b	6(a0),d1		; b0
	cmp.w	d1,d0
	bge	.some
.empty:	moveq	#0,d2			; (empty: no rows)
	moveq	#-1,d3
.some:	sub.w	d2,d3
	addq.w	#1,d3			; rows
	moveq	#1,d6			; words a row
	cmp.w	#8,d4
	bls	.w1
	moveq	#2,d6
.w1:	; the size: 8 + rows * (4 + 8 * words)
	move.w	d6,d1
	lsl.w	#3,d1
	addq.w	#4,d1
	mulu	d3,d1
	addq.l	#8,d1
	move.l	d7,d0
	bsr	ren_cache_new
	move.l	a1,-(sp)
	move.w	d3,(a1)+
	move.w	d2,(a1)+
	move.w	d6,(a1)+
	clr.w	(a1)+
	lea	(a1),a6			; masks
	move.w	d3,d0
	lsl.w	#2,d0
	lea	(a1,d0.w),a1		; data
	subq.w	#1,d3
	bmi	.done
	move.w	d6,ren_cw
	moveq	#0,d0
	move.b	SL_COL(a2),d0
	bsr	ren_pt_get		; (a3: its planes table)
	lea	ren_pm16,a4
	; the box's bytes of the sub-rectangle's rows: cs = the sub-rectangle's first byte in the box row (may be
	; negative), its bytes ja .. jb - 1 in the box (the others transparent: not converted)
	moveq	#0,d0
	move.w	SL_CODE(a2),d0
	lsl.w	#3,d0
	lea	ren_spr_idx,a0
	add.l	d0,a0
	moveq	#0,d1
	move.b	7(a0),d1
	moveq	#0,d5
	move.b	6(a0),d5		; b0
	sub.w	d5,d1
	addq.w	#1,d1			; bytes a box row
	move.w	d1,ren_cbw
	moveq	#0,d0
	move.b	SL_TX(a2),d0
	lsr.w	#1,d0
	sub.w	d5,d0			; cs
	moveq	#0,d5			; ja = max(0, -cs)
	tst.w	d0
	bpl	.ja
	sub.w	d0,d5
.ja:	sub.w	d0,d1			; jb = min(bytes, bw - cs)
	cmp.w	d4,d1
	ble	.jb
	move.w	d4,d1
.jb:	moveq	#0,d7			; the first row's box row: ty + first - y0
	move.b	SL_TY(a2),d7
	add.w	d2,d7
	sub.b	4(a0),d7
	mulu	ren_cbw,d7
	add.l	(a0),d7
	add.l	#ren_spr,d7
	ext.l	d0
	add.l	d0,d7
	move.l	d7,a5			; (box byte cs of the first row)
	btst	#0,SL_FL(a2)
	bne	.fx
	add.w	d5,a5			; forward: from byte ja, steps ja .. jb - 1
	mulu	#ren_cvf1-ren_cvf,d5
	lea	ren_cvf,a2
	add.l	a2,d5
	mulu	#ren_cvf1-ren_cvf,d1
	add.l	a2,d1
	bra	.ent
.fx:	add.w	d1,a5			; flip x: from byte jb - 1 down, steps bytes - jb .. bytes - ja - 1
	move.w	d4,d0
	sub.w	d1,d0
	sub.w	d5,d4
	mulu	#ren_cvb1-ren_cvb,d0
	lea	ren_cvb,a2
	add.l	a2,d0
	mulu	#ren_cvb1-ren_cvb,d4
	add.l	a2,d4
	move.l	d0,d5
	move.l	d4,d1
.ent:	move.l	d5,a2			; the first step
	move.l	d1,a0			; the step after the last: rts there for this image
	move.w	(a0),ren_cvsave
	move.w	#$4e75,(a0)
	move.l	a0,ren_cvend
	move.w	d3,d7			; rows - 1
.row:	move.l	a5,a0
	moveq	#0,d1
	moveq	#0,d2
	moveq	#0,d3
	moveq	#0,d4
	moveq	#0,d5
	moveq	#0,d6
	jsr	(a2)			; d1-d4: the 8-pixel blocks' planes (bytes: planes 0-3), d5 d6: the mask's words
	adda.w	ren_cbw,a5
	cmp.w	#1,ren_cw
	bne	.two
	swap	d5
	clr.w	d5
	move.l	d5,(a6)+
	movep.l	d1,0(a1)
	movep.l	d2,1(a1)
	addq.l	#8,a1
	dbf	d7,.row
	bra	.cvx
.two:	swap	d5
	move.w	d6,d5
	move.l	d5,(a6)+
	lea	ren_btmp,a0		; (plane by plane: p0w0 p0w1 p1w0 ...)
	movep.l	d1,0(a0)
	movep.l	d2,1(a0)
	movep.l	d3,8(a0)
	movep.l	d4,9(a0)
	move.w	(a0),(a1)+
	move.w	8(a0),(a1)+
	move.w	2(a0),(a1)+
	move.w	10(a0),(a1)+
	move.w	4(a0),(a1)+
	move.w	12(a0),(a1)+
	move.w	6(a0),(a1)+
	move.w	14(a0),(a1)+
	dbf	d7,.row
.cvx:	move.l	ren_cvend,a0
	move.w	ren_cvsave,(a0)
.done:	move.l	(sp)+,a1
	movem.l	(sp)+,d0/d2-d7/a2-a6
.hit:	rts

; a2 = a list entry, d0.w = a row of its sub-rectangle: the row's bytes (pixel pairs) into ren_brow (16, $FF beyond
; the sub-rectangle and outside the cell's box; flip x: in reverse order, the nibbles swapped).  Keeps all but d0.
ren_spr_row:
	movem.l	d1-d6/a0-a1,-(sp)
	lea	ren_brow,a1
	moveq	#-1,d1
	move.l	d1,(a1)
	move.l	d1,4(a1)
	move.l	d1,8(a1)
	move.l	d1,12(a1)
	moveq	#0,d1
	move.w	SL_CODE(a2),d1
	lsl.w	#3,d1
	lea	ren_spr_idx,a0
	add.l	d1,a0
	moveq	#0,d1
	move.b	SL_TY(a2),d1
	add.w	d0,d1			; the cell's row
	moveq	#0,d2
	move.b	4(a0),d2		; y0
	cmp.w	#255,d2
	beq	.out
	sub.w	d2,d1
	bmi	.out
	moveq	#0,d2
	move.b	5(a0),d2
	sub.b	4(a0),d2		; y1 - y0
	cmp.w	d2,d1
	bgt	.out
	moveq	#0,d3
	move.b	7(a0),d3
	moveq	#0,d4
	move.b	6(a0),d4		; b0
	sub.w	d4,d3
	addq.w	#1,d3			; bytes a box row
	mulu	d3,d1
	add.l	(a0),d1
	lea	ren_spr,a0
	add.l	d1,a0			; the row's first box byte
	moveq	#0,d5
	move.b	SL_TX(a2),d5
	lsr.w	#1,d5
	sub.w	d4,d5			; the sub-rectangle's first byte in the box row (may be negative)
	moveq	#0,d6
	move.b	SL_SX(a2),d6
	lsr.w	#1,d6			; bytes
	btst	#0,SL_FL(a2)
	bne	.fx
	subq.w	#1,d6
.b:	cmp.w	d3,d5			; (outside the box: $FF stays)
	bhs	.bn
	move.b	(a0,d5.w),(a1)
.bn:	addq.l	#1,a1
	addq.w	#1,d5
	dbf	d6,.b
	bra	.out
.fx:	add.w	d6,a1			; backwards, the nibbles swapped
	subq.w	#1,d6
.f:	subq.l	#1,a1
	cmp.w	d3,d5
	bhs	.fn
	move.b	(a0,d5.w),d0
	ror.b	#4,d0
	move.b	d0,(a1)
.fn:	addq.w	#1,d5
	dbf	d6,.f
.out:	movem.l	(sp)+,d1-d6/a0-a1
	rts

; The conversion of a sprite row's bytes (pixel pairs), one step a byte of the sub-rectangle's row (16 at most): a0 =
; the byte (forward: (a0)+; flip x: -(a0), the nibbles swapped), a3 = the colour's pair table, a4 = ren_pm16; the
; planes into d1-d4 (8 pixels each), the mask into d5 (pixels 0-15) and d6.  ren_sprite_get calls the first step of
; the box's bytes and puts an rts after the last one for the time of the image.
ren_cvf:
J	set	0
	rept	16
	moveq	#0,d0
	move.b	(a0)+,d0
	lsl.w	#4,d0
	CVSTEP
J	set	J+1
	endr
	rts
ren_cvb:
J	set	0
	rept	16
	moveq	#0,d0
	move.b	-(a0),d0
	ror.b	#4,d0
	lsl.w	#4,d0
	CVSTEP
J	set	J+1
	endr
	rts
ren_cvf1	= ren_cvf+14		; (step sizes)
ren_cvb1	= ren_cvb+16

; ---- drawing ---------------------------------------------------------------------------------------------------------
; a1 = a converted image, a2 = its list entry: drawn at its place (Blitter: one pass a line, the four planes, the
; line's opaque mask shifted into the end masks).  Clipped at the group boundaries in the side bands nearest the
; picture's edges (ren_cl, ren_cr: the first group and the group after the last one drawn): the words outside get end
; mask 0.  Lines in bar rows that cover the sprite's priority are left out.  The rectangle drawn goes into the
; buffer's damage list (bar rows: the bar lines to copy again).  Then the priority repair: where the group's layers
; have a higher priority than the sprite (ren_pri planes), the background is put back from the twin columns.
ren_draw_image:
	move.w	(a1),d7
	beq	.out			; (empty)
	move.l	a2,ren_cur
	move.l	a1,ren_cur_img
	move.w	4(a1),d6		; words a row
	move.w	d6,d0
	addq.w	#1,d0
	move.w	d0,ren_nw		; destination words
	; x
	move.w	SL_X(a2),d0
	add.w	ren_w,d0
	add.w	#16,d0			; buffer x
	moveq	#15,d1
	and.w	d0,d1
	move.w	d1,ren_s		; skew
	asr.w	#4,d0
	move.w	d0,ren_g0
	move.w	ren_cl,d2
	move.w	ren_cr,d3
	move.w	d0,d1
	add.w	ren_nw,d1		; the group after
	cmp.w	d2,d1
	ble	.out			; wholly left
	cmp.w	d3,d0
	bge	.out			; wholly right
	moveq	#-1,d4			; the clip masks c0, c1, c2 (words)
	moveq	#-1,d5
	move.w	#-1,ren_c2
	sf	ren_slow
	sf	ren_clip
	cmp.w	d2,d0
	bge	.lok
	st	ren_clip		; left: group g0 (and g0 + 1) outside
	addq.l	#1,ren_slowclip
	clr.w	d4
	move.w	d0,d1
	addq.w	#1,d1
	cmp.w	d2,d1
	bge	.lok
	clr.w	d5
.lok:	move.w	d0,d1
	add.w	ren_nw,d1
	subq.w	#1,d1			; the last group
	cmp.w	d3,d1
	blt	.rok
	st	ren_clip		; right: the last (and the one before)
	addq.l	#1,ren_slowclip
	cmp.w	#3,ren_nw
	bne	.r2
	clr.w	ren_c2
	subq.w	#1,d1
	cmp.w	d3,d1
	blt	.rok
	clr.w	d5
	bra	.rok
.r2:	clr.w	d5
	subq.w	#1,d1
	cmp.w	d3,d1
	blt	.rok
	clr.w	d4
.rok:	move.w	d4,ren_c0
	move.w	d5,ren_c1
	; the damage's groups
	move.w	d0,d1
	cmp.w	d2,d1
	bge	.d1
	move.w	d2,d1
.d1:	move.w	d1,ren_dg0
	move.w	d0,d1
	add.w	ren_nw,d1
	cmp.w	d3,d1
	ble	.d2
	move.w	d3,d1
.d2:	move.w	d1,ren_dg1
	; the lines: first row's line, the step
	move.w	SL_Y(a2),d0
	move.w	2(a1),d1		; first row
	move.w	#REN_LINEB,d4
	btst	#1,SL_FL(a2)
	beq	.ny
	moveq	#0,d2			; flip y: line y' + height - 1 - row, upwards
	move.b	SL_SY(a2),d2
	add.w	d2,d0
	subq.w	#1,d0
	sub.w	d1,d0
	neg.w	d4
	move.w	d0,ren_ylast		; (the first line drawn; the range is set below)
	sub.w	d7,d0
	addq.w	#1,d0
	move.w	d0,ren_ya
	move.w	ren_ylast,d0
	bra	.yd
.ny:	add.w	d1,d0
	move.w	d0,ren_ya
.yd:	move.w	d0,ren_y0		; the first row's line
	move.w	ren_ya,d1
	add.w	d7,d1
	move.w	d1,ren_yb
	move.w	d4,ren_step
	; the lines drawn: of one palette only (ren_linesel: the lines of an interval, or else line by line), and bar
	; rows in the range that can hide the sprite: the lines at either end left out; others between: the slow path
	move.w	ren_ya,d2
	move.w	ren_yb,d3
	tst.b	ren_linesel
	beq	.ls0
	bsr	ren_sel_range
	bmi	.out			; (no line of the palette)
	beq	.ls0
	st	ren_slow		; (two parts: line by line)
	moveq	#0,d5
	bra	.nob
.ls0:	tst.w	ren_nbar
	beq	.trim
	moveq	#0,d6
	move.b	SL_PRI(a2),d6
	addq.b	#1,d6
	cmp.b	ren_barmax,d6
	bhs	.trim
	lea	ren_bar_line,a0
.tt:	cmp.w	d3,d2			; the top
	bge	.out
	cmp.w	#224,d2
	bhs	.tb
	cmp.b	(a0,d2.w),d6
	bhs	.tb
	addq.w	#1,d2
	bra	.tt
.tb:	move.w	d3,d0			; the bottom
	subq.w	#1,d0
	cmp.w	#224,d0
	bhs	.bd
	cmp.b	(a0,d0.w),d6
	bhs	.bd
	move.w	d0,d3
	bra	.tb
.bd:	move.w	d2,d0			; bars between: the slow path
	bsr	ren_bar_clamp
	move.w	d0,d1
	move.w	d3,d0
	bsr	ren_bar_clamp
	lea	ren_bar_cum,a0
	add.w	d0,d0
	add.w	d1,d1
	move.w	(a0,d0.w),d0
	cmp.w	(a0,d1.w),d0
	beq	.trim
	st	ren_slow
.trim:	; the rows: left out at the start (non-flipped: the top; flipped: the bottom)
	moveq	#0,d5			; (rows left out at the start)
	move.w	d2,d0
	sub.w	ren_ya,d0
	move.w	ren_yb,d1
	sub.w	d3,d1
	move.w	d0,d4
	or.w	d1,d4
	beq	.nob			; (all of them)
	tst.w	ren_step
	bpl	.nf
	exg	d0,d1
.nf:	move.w	d0,d5			; rows left out first
	sub.w	d0,d7
	sub.w	d1,d7			; rows drawn
	move.w	d2,ren_ya
	move.w	d3,ren_yb
	move.w	ren_y0,d0
	tst.w	ren_step
	bpl	.nf2
	sub.w	d5,d0
	bra	.nf3
.nf2:	add.w	d5,d0
.nf3:	move.w	d0,ren_y0
.nob:	; the Blitter (SXI, SYI 2, DXI 8, HOP / OP: ren_objects set them)
	move.w	ren_nw,BLT_XC.w
	moveq	#-14,d0
	cmp.w	#3,ren_nw
	beq	.dy
	moveq	#-6,d0
.dy:	move.w	d0,BLT_DYI.w
	move.w	ren_s,d0
	or.w	#BLT_NFSR,d0
	move.b	d0,BLT_SKEW.w
	lea	8(a1),a0		; masks
	move.w	(a1),d0
	lsl.w	#2,d0
	lea	(a0,d0.w),a3
	move.w	d5,d0			; (rows left out)
	lsl.w	#2,d0
	add.w	d0,a0
	tst.w	d5
	beq	.sr
	move.w	4(a1),d0
	lsl.w	#3,d0
	mulu	d5,d0
	add.w	d0,a3
.sr:	move.l	a3,BLT_SRC.w		; the planes
	move.l	a3,ren_srcp
	move.l	a0,ren_maskp
	; the first line's address
	move.w	ren_y0,d0
	add.w	#REN_GUARD,d0
	ext.l	d0
	moveq	#9,d1
	lsl.l	d1,d0
	move.w	ren_g0,d1
	ext.l	d1
	lsl.l	#3,d1
	add.l	d1,d0
	add.l	ren_dbuf,d0
	move.l	d0,a1
	movem.l	a2/a4-a6,-(sp)
	lea	BLT_DST.w,a3
	lea	BLT_YC.w,a4
	lea	BLT_CTRL.w,a5
	lea	BLT_E1.w,a6
	move.w	d7,ren_nrow
	move.w	ren_step,d4
	ext.l	d4
	move.w	ren_s,d5
	moveq	#16,d6
	sub.w	d5,d6
	subq.w	#1,d7
	tst.b	ren_slow
	bne	.slow
	cmp.w	#3,ren_nw
	beq	.f3
	moveq	#4,d2			; (Y count: the four planes)
	move.w	#$c0,d3			; (start, HOG)
	tst.b	ren_clip
	bne	.f2c
.f2:	move.l	(a0)+,d0		; one source word: two destination words
	lsr.l	d5,d0
	move.w	d0,4(a6)
	swap	d0
	move.w	d0,(a6)
	move.l	a1,(a3)
	move.w	d2,(a4)
	move.b	d3,(a5)
	add.l	d4,a1
	dbf	d7,.f2
	bra	.drawn
.f2c:	move.l	(a0)+,d0		; (clipped: the words outside get end mask 0)
	lsr.l	d5,d0
	and.w	ren_c1,d0
	move.w	d0,4(a6)
	swap	d0
	and.w	ren_c0,d0
	move.w	d0,(a6)
	move.l	a1,(a3)
	move.w	d2,(a4)
	move.b	d3,(a5)
	add.l	d4,a1
	dbf	d7,.f2c
	bra	.drawn
.f3:	; two source words a row: one pass a line; a mask like the line before's: the Blitter's state as it is.  A new
	; mask: its three destination words, and only those passes' words that are not 0 (END3 0: two words; END1 0: from
	; the second word, the first source word read ahead (FXSR); both: one word).  The skew register's FXSR bit says
	; whether a1 is the line's second word.
	move.w	ren_s,d0
	move.b	d0,ren_sv+1		; (w2 = 0: two words, no NFSR)
	or.b	#BLT_NFSR,d0
	move.b	d0,ren_sv		; (three words)
	or.b	#BLT_FXSR,d0
	move.b	d0,ren_sv+2		; (w0 = 0: from the second word)
	and.b	#$ff-BLT_NFSR,d0
	move.b	d0,ren_sv+3		; (one word)
	move.w	#$c030,d3		; (CTRL: start, HOG; SKEW: set by the first mask, $30 no kind of pass)
	move.l	(a0),d2
	not.l	d2			; (no mask is the first's complement: the first row sets the registers)
	move.w	#4,a2			; (Y count: the four planes)
	tst.b	ren_clip
	bne	.cl
.ul:	move.l	(a0)+,d0
	cmp.l	d0,d2
	bne	.um
.ug:	move.l	a1,(a3)
	move.w	a2,(a4)
	move.w	d3,(a5)
	add.l	d4,a1
	dbf	d7,.ul
	bra	.drawn
.um:	move.l	d0,d2			; a new mask: its words (w0 w1 w2), the narrowest pass that covers them
	move.l	d0,d1
	lsr.l	d5,d1			; w0:w1
	lsl.w	d6,d0			; w2
	beq	.uz
	swap	d1
	tst.w	d1
	beq	.ua
	move.w	d1,(a6)			; three words
	swap	d1
	move.w	d1,2(a6)
	move.w	d0,4(a6)
	cmp.b	ren_sv,d3
	beq	.ug			; (the same kind of pass)
	tst.b	d3
	bpl	.u0
	subq.l	#8,a1
.u0:	move.b	ren_sv,d3
	move.w	#3,BLT_XC.w
	move.w	#-14,BLT_DYI.w
	bra	.ug
.ua:	swap	d1			; w0 = 0: w1 w2 from the second word (FXSR)
	move.w	d1,(a6)
	move.w	d0,4(a6)
	cmp.b	ren_sv+2,d3
	beq	.ug			; (the same kind of pass)
	tst.b	d3
	bmi	.u2
	addq.l	#8,a1
.u2:	move.b	ren_sv+2,d3
	move.w	#2,BLT_XC.w
	move.w	#-6,BLT_DYI.w
	bra	.ug
.uz:	swap	d1			; w2 = 0
	tst.w	d1
	beq	.ub
	move.w	d1,(a6)			; w0 w1
	swap	d1
	move.w	d1,4(a6)
	cmp.b	ren_sv+1,d3
	beq	.ug			; (the same kind of pass)
	tst.b	d3
	bpl	.u1
	subq.l	#8,a1
.u1:	move.b	ren_sv+1,d3
	move.w	#2,BLT_XC.w
	move.w	#-6,BLT_DYI.w
	bra	.ug
.ub:	swap	d1			; w1 alone
	move.w	d1,(a6)
	cmp.b	ren_sv+3,d3
	beq	.ug			; (the same kind of pass)
	tst.b	d3
	bmi	.u3
	addq.l	#8,a1
.u3:	move.b	ren_sv+3,d3
	move.w	#1,BLT_XC.w
	move.w	#2,BLT_DYI.w
	bra	.ug
.cl:	move.l	(a0)+,d0
	cmp.l	d0,d2
	bne	.cm
.cg:	move.l	a1,(a3)
	move.w	a2,(a4)
	move.w	d3,(a5)
	add.l	d4,a1
	dbf	d7,.cl
	bra	.drawn
.cm:	move.l	d0,d2			; a new mask: its words (w0 w1 w2), the narrowest pass that covers them
	move.l	d0,d1
	lsr.l	d5,d1			; w0:w1
	lsl.w	d6,d0			; w2
	and.w	ren_c2,d0
	beq	.cz
	swap	d1
	and.w	ren_c0,d1
	beq	.ca
	move.w	d1,(a6)			; three words
	swap	d1
	and.w	ren_c1,d1
	move.w	d1,2(a6)
	move.w	d0,4(a6)
	cmp.b	ren_sv,d3
	beq	.cg			; (the same kind of pass)
	tst.b	d3
	bpl	.c0
	subq.l	#8,a1
.c0:	move.b	ren_sv,d3
	move.w	#3,BLT_XC.w
	move.w	#-14,BLT_DYI.w
	bra	.cg
.ca:	swap	d1			; w0 = 0: w1 w2 from the second word (FXSR)
	and.w	ren_c1,d1
	move.w	d1,(a6)
	move.w	d0,4(a6)
	cmp.b	ren_sv+2,d3
	beq	.cg			; (the same kind of pass)
	tst.b	d3
	bmi	.c2
	addq.l	#8,a1
.c2:	move.b	ren_sv+2,d3
	move.w	#2,BLT_XC.w
	move.w	#-6,BLT_DYI.w
	bra	.cg
.cz:	swap	d1			; w2 = 0
	and.w	ren_c0,d1
	beq	.cb
	move.w	d1,(a6)			; w0 w1
	swap	d1
	and.w	ren_c1,d1
	move.w	d1,4(a6)
	cmp.b	ren_sv+1,d3
	beq	.cg			; (the same kind of pass)
	tst.b	d3
	bpl	.c1
	subq.l	#8,a1
.c1:	move.b	ren_sv+1,d3
	move.w	#2,BLT_XC.w
	move.w	#-6,BLT_DYI.w
	bra	.cg
.cb:	swap	d1			; w1 alone
	and.w	ren_c1,d1
	move.w	d1,(a6)
	cmp.b	ren_sv+3,d3
	beq	.cg			; (the same kind of pass)
	tst.b	d3
	bmi	.c3
	addq.l	#8,a1
.c3:	move.b	ren_sv+3,d3
	move.w	#1,BLT_XC.w
	move.w	#2,BLT_DYI.w
	bra	.cg
	; the slow path: the clip masks, bar lines left out (the source then set for each line)
.slow:	addq.l	#1,ren_slowdraws
	move.w	ren_y0,d3		; the line
	move.l	ren_srcp,a2
	move.l	ren_cur,a0
	moveq	#0,d2
	move.b	SL_PRI(a0),d2
	addq.b	#1,d2			; a bar line hides the sprite when its value is above this
	move.l	ren_maskp,a0
.sl:	tst.b	ren_linesel
	beq	.sa
	move.w	d3,d0			; (the lines of one palette only)
	bsr	ren_in_hud
	seq	d0
	addq.b	#2,d0			; (1: playfield line, 2: HUD line)
	cmp.b	ren_linesel,d0
	bne	.sk
.sa:	cmp.w	#224,d3
	bhs	.sd			; (guard lines: never bars)
	lea	ren_bar_line,a1
	cmp.b	(a1,d3.w),d2
	bcs	.sk			; (the bar's priority above the sprite's)
.sd:	move.l	(a0),d0
	move.l	d0,d1
	lsr.l	d5,d1
	and.w	ren_c1,d1
	move.w	d1,2(a6)		; (END2, or END3 of a two-word line: set again below)
	swap	d1
	and.w	ren_c0,d1
	move.w	d1,(a6)
	cmp.w	#3,ren_nw
	bne	.s2
	lsl.w	d6,d0
	and.w	ren_c2,d0
	move.w	d0,4(a6)
	bra	.sg
.s2:	move.w	2(a6),4(a6)
.sg:	move.w	d3,d0
	add.w	#REN_GUARD,d0
	ext.l	d0
	moveq	#9,d1
	lsl.l	d1,d0
	move.w	ren_g0,d1
	ext.l	d1
	lsl.l	#3,d1
	add.l	d1,d0
	add.l	ren_dbuf,d0
	move.l	d0,(a3)
	move.l	a2,BLT_SRC.w
	move.w	#4,(a4)
	move.b	#$c0,(a5)
.sk:	addq.l	#4,a0
	move.w	ren_nw,d0
	subq.w	#1,d0
	lsl.w	#3,d0
	add.w	d0,a2			; (the row's planes: 8 bytes a word)
	tst.w	d4
	bmi	.su
	addq.w	#1,d3
	bra	.sn
.su:	subq.w	#1,d3
.sn:	dbf	d7,.sl
.drawn:	movem.l	(sp)+,a2/a4-a6
	; the damage
	tst.w	ren_nrow
	beq	.out
	move.w	ren_dg0,d0
	move.w	ren_dg1,d1
	move.w	ren_ya,d2
	move.w	ren_yb,d3
	bsr	ren_damage
	; the priority repair
	cmp.b	#2,ren_linesel
	beq	.out
	move.l	ren_cur,a2
	moveq	#0,d0
	move.b	SL_PRI(a2),d0
	cmp.b	ren_grp_max,d0
	bhs	.out
	tst.b	ren_grp_n
	beq	.out
	bsr	ren_repair
.out:	rts

; d2 .. d3 - 1 (lines): the part in the palette ren_linesel's lines (1: the playfield's: < 0, htop .. hbot - 1,
; >= 224; 2: the HUD's: 0 .. htop - 1, hbot .. 223).  N: none; Z: one interval, into d2 d3; else two (d2 d3 kept).
; Uses d0.
ren_sel_range:
	movem.l	d1/d4-d6,-(sp)
	moveq	#0,d6			; (intervals found: lo d4, hi d5)
	cmp.b	#2,ren_linesel
	beq	.hud
	move.w	d2,d0			; lines < 0
	moveq	#0,d1
	bsr	.piece
	move.w	ren_htop,d0
	move.w	ren_hbot,d1
	bsr	.piece
	move.w	#224,d0
	move.w	d3,d1
	bsr	.piece
	bra	.end
.hud:	moveq	#0,d0
	move.w	ren_htop,d1
	bsr	.piece
	move.w	ren_hbot,d0
	move.w	#224,d1
	bsr	.piece
.end:	tst.w	d6
	beq	.none
	cmp.w	#1,d6
	bne	.two
	move.w	d4,d2
	move.w	d5,d3
	movem.l	(sp)+,d1/d4-d6
	moveq	#0,d0			; (Z)
	rts
.two:	movem.l	(sp)+,d1/d4-d6
	moveq	#1,d0
	rts
.none:	movem.l	(sp)+,d1/d4-d6
	moveq	#-1,d0
	rts
; the lines d0 .. d1 - 1 within d2 .. d3 - 1: one more interval (or a continuation of the last)
.piece:	cmp.w	d2,d0
	bge	.p0
	move.w	d2,d0
.p0:	cmp.w	d3,d1
	ble	.p1
	move.w	d3,d1
.p1:	cmp.w	d1,d0
	bge	.pn
	tst.w	d6
	beq	.pf
	cmp.w	d5,d0
	bne	.p2
	move.w	d1,d5			; (adjacent)
	rts
.p2:	moveq	#2,d6
	rts
.pf:	moveq	#1,d6
	move.w	d0,d4
	move.w	d1,d5
.pn:	rts

; d0.w = a line (any): the line clamped to 0-224
ren_bar_clamp:
	tst.w	d0
	bpl	.p
	moveq	#0,d0
.p:	cmp.w	#224,d0
	ble	.q
	move.w	#224,d0
.q:	rts

; The damage of groups d0 .. d1 - 1, lines d2 .. d3 - 1 (any; clamped to the buffer): the bar lines among them are
; marked for copying again, the others put into the buffer's damage list as rectangles with their twin as the source
; (split at group 32, the twins' boundary).  Keeps d4-d7/a2-a6.
ren_damage:
	addq.l	#1,ren_dmgs
	cmp.w	d1,d0
	bge	.out
	cmp.w	#-REN_GUARD,d2
	bge	.c0
	move.w	#-REN_GUARD,d2
.c0:	cmp.w	#224+REN_GUARD,d3
	ble	.c1
	move.w	#224+REN_GUARD,d3
.c1:	cmp.w	d3,d2
	bge	.out
	movem.l	d4-d7/a2,-(sp)
	tst.w	ren_nbar		; (no bar line among them: one rectangle)
	beq	.nobar
	move.w	d2,d4
	bpl	.p0
	moveq	#0,d4
.p0:	move.w	d3,d5
	cmp.w	#224,d5
	ble	.p1
	move.w	#224,d5
.p1:	cmp.w	d5,d4
	bge	.nobar
	lea	ren_bar_cum,a1
	add.w	d4,d4
	add.w	d5,d5
	move.w	(a1,d4.w),d4
	cmp.w	(a1,d5.w),d4
	bne	.bars
.nobar:	move.w	d2,d4
	move.w	d3,d5
	lea	ren_bar_line,a1
	bsr	.rect2
	movem.l	(sp)+,d4-d7/a2
	rts
.bars:	move.w	ren_draw,d4
	mulu	#224,d4
	lea	ren_bar_dirty,a2
	add.w	d4,a2
	; the guard lines above the picture, the picture's runs of equal bar values, the guard lines below
	move.w	d2,d4
	bpl	.g1
	moveq	#0,d5
	bsr	.rect2			; (lines d2 .. -1)
	moveq	#0,d4
.g1:	lea	ren_bar_line,a1
.run:	move.w	d3,d7			; (the picture's part ends here; again after .rect2, .bar: they use d6 d7)
	cmp.w	#224,d7
	ble	.g2
	move.w	#224,d7
.g2:	cmp.w	d7,d4
	bge	.below
	move.b	(a1,d4.w),d6		; the run's value
	move.w	d4,d5
.r0:	addq.w	#1,d5
	cmp.w	d7,d5
	bge	.re
	cmp.b	(a1,d5.w),d6
	beq	.r0
.re:	tst.b	d6
	beq	.rect
	bsr	.bar			; (lines d4 .. d5 - 1: from the bar image)
	move.w	d5,d4
	lea	ren_bar_line,a1
	bra	.run
.rect:	bsr	.rect2
	move.w	d5,d4
	lea	ren_bar_line,a1
	bra	.run
.below:	cmp.w	d3,d4
	bge	.done
	move.w	d3,d5
	bsr	.rect2			; (lines 224 .. d3 - 1)
.done:	movem.l	(sp)+,d4-d7/a2
.out:	rts
; groups d0 .. d1 - 1, lines d4 .. d5 - 1: split at group 32
.rect2:	movem.l	d0-d1,-(sp)
	cmp.w	#32,d0
	bge	.hi
	cmp.w	#32,d1
	ble	.lo
	move.w	d1,-(sp)
	moveq	#32,d1
	bsr	.add
	move.w	(sp)+,d1
	moveq	#32,d0
	bra	.hi
.lo:	bsr	.add
	bra	.rd
.hi:	bsr	.add
.rd:	movem.l	(sp)+,d0-d1
	rts
; bar lines d4 .. d5 - 1 (0-223), groups d0 .. d1 - 1: a rectangle copied from the bar image (words | $8000; source:
; the bar image's word before the first group's, read ahead: the window's fine scroll is the skew)
.bar:	move.l	ren_dmgp,a0
	cmp.l	ren_dmglim,a0
	bhs	.full
	move.w	d4,d7
	add.w	#REN_GUARD,d7
	ext.l	d7
	moveq	#9,d6
	lsl.l	d6,d7
	move.w	d0,d6
	ext.l	d6
	lsl.l	#3,d6
	add.l	d6,d7
	add.l	ren_dbuf,d7
	move.l	d7,(a0)+		; destination
	move.w	d4,d7
	mulu	#FI_STRIDE,d7
	add.l	#ren_fi-8,d7
	move.w	ren_w,d6
	lsr.w	#4,d6
	neg.w	d6
	add.w	d0,d6
	lsl.w	#3,d6
	add.w	d6,d7			; (the group's word in the bar image's line, minus one)
	move.l	d7,(a0)+
	move.w	d1,d7
	sub.w	d0,d7
	or.w	#$8000,d7
	move.w	d7,(a0)+		; words | $8000
	move.w	d5,d7
	sub.w	d4,d7
	move.w	d7,(a0)+		; lines
	move.l	a0,ren_dmgp
	rts
; groups d0 .. d1 - 1 (one side of 32), lines d4 .. d5 - 1
.add:	move.l	ren_dmgp,a0
	cmp.l	ren_dmglim,a0
	bhs	.full
	move.w	d4,d7
	add.w	#REN_GUARD,d7
	ext.l	d7
	moveq	#9,d6
	lsl.l	d6,d7
	move.w	d0,d6
	ext.l	d6
	lsl.l	#3,d6
	add.l	d6,d7
	add.l	ren_dbuf,d7
	move.l	#256,d6
	cmp.w	#32,d0
	blt	.tw
	neg.l	d6
.tw:	; the rectangle before: the same lines and the groups just left of these, or the same groups and the lines
	; just above: one rectangle (the overlay cells come in rows)
	movem.l	d0/d1,-(sp)
	cmp.l	ren_dmgbase,a0
	bls	.new			; (the list is empty)
	tst.w	-4(a0)
	bmi	.new			; (a bar image rectangle)
	move.l	-12(a0),d0		; its destination
	move.l	-8(a0),d1
	sub.l	d0,d1
	cmp.l	d1,d6
	bne	.new			; (the other twin)
	move.w	-4(a0),d1		; its words
	ext.l	d1
	add.l	d1,d1
	add.l	d0,d1
	cmp.l	d1,d7
	bne	.vert
	move.w	d5,d1			; side by side: the same lines?
	sub.w	d4,d1
	cmp.w	-2(a0),d1
	bne	.new
	movem.l	(sp)+,d0/d1
	move.w	d1,d6
	sub.w	d0,d6
	lsl.w	#2,d6
	add.w	d6,-4(a0)		; (wider)
	lea	ren_bar_line,a1
	rts
.vert:	move.w	-2(a0),d1		; one above the other: the same groups?
	ext.l	d1
	moveq	#9,d6
	lsl.l	d6,d1
	add.l	d0,d1
	cmp.l	d1,d7
	bne	.new0
	movem.l	(sp),d0/d1
	move.w	d1,d6
	sub.w	d0,d6
	lsl.w	#2,d6
	cmp.w	-4(a0),d6
	bne	.new0
	movem.l	(sp)+,d0/d1
	move.w	d5,d6
	sub.w	d4,d6
	add.w	d6,-2(a0)		; (taller)
	lea	ren_bar_line,a1
	rts
.new0:	move.l	-8(a0),d6		; (d6 again: the twin's offset)
	sub.l	-12(a0),d6
.new:	movem.l	(sp)+,d0/d1
	move.l	d7,(a0)+		; destination
	add.l	d6,d7
	move.l	d7,(a0)+		; source: the twin
	move.w	d1,d7
	sub.w	d0,d7
	lsl.w	#2,d7
	move.w	d7,(a0)+		; words
	move.w	d5,d7
	sub.w	d4,d7
	move.w	d7,(a0)+		; lines
	move.l	a0,ren_dmgp
	lea	ren_bar_line,a1
	rts
.full:	addq.l	#1,ren_dmg_over		; (the list full: the whole window is put back next time)
	move.w	ren_draw,d6
	lea	ren_dmgall,a0
	move.w	ren_w,d7
	bset	#15,d7
	add.w	d6,d6
	move.w	d7,(a0,d6.w)
	lea	ren_bar_line,a1
	rts

; The repair of the sprite just drawn (ren_cur, ren_cur_img; ren_g0, ren_s, ren_y0, ren_step): where the group's
; priority at a pixel (ren_pri: three bit planes) is above the sprite's, the pixels the sprite set get the background
; from the twin column again.  Only where a cell under the sprite has a higher priority (ren_cellpri).
ren_repair:
	movem.l	d0-d7/a0-a6,-(sp)
	move.l	ren_cur,a2
	moveq	#0,d7
	move.b	SL_PRI(a2),d7		; P
	move.w	ren_ya,d0
	bsr	ren_bar_clamp
	move.w	d0,d2
	move.w	ren_yb,d0
	bsr	ren_bar_clamp
	move.w	d0,d3
	cmp.w	d3,d2
	bge	.out
	move.w	d2,ren_ra
	move.w	d3,ren_rb
	; the cell rows under the sprite with a cell above P (bit r - the first row in d6)
	add.w	ren_ey,d2
	lsr.w	#3,d2			; the first cell row (unwrapped)
	move.w	d2,ren_rrow
	subq.w	#1,d3
	add.w	ren_ey,d3
	lsr.w	#3,d3
	sub.w	d2,d3			; rows - 1
	move.w	ren_dg0,d4
	add.w	d4,d4			; the first cell column (the window: buffer x = tilemap x)
	move.w	ren_dg1,d5
	add.w	d5,d5
	sub.w	d4,d5
	subq.w	#1,d5			; columns - 1
	moveq	#0,d6			; the rows' bits
	moveq	#0,d1			; row number
.cr:	move.w	d2,d0
	add.w	d1,d0
	and.w	#63,d0
	lsl.w	#6,d0
	lea	ren_cellpri,a2
	add.w	d0,a2			; the row's cells
	moveq	#63,d0
	and.w	d4,d0
	move.w	d0,a1
	add.w	d5,d0
	cmp.w	#64,d0
	bhs	.wrap
	lea	(a2,a1.w),a1		; (no wrap: the cells in a row)
	move.w	d5,d0
.cf:	cmp.b	(a1)+,d7
	dbcs	d0,.cf
	bcs	.need
	bra	.nx
.wrap:	move.w	d5,d0
	move.w	d0,a1			; (column counter)
.cc:	move.w	d4,d0
	add.w	a1,d0
	and.w	#63,d0
	cmp.b	(a2,d0.w),d7
	bcs	.need
	subq.w	#1,a1
	move.w	a1,d0
	bpl	.cc
	bra	.nx
.need:	bset	d1,d6
.nx:	addq.w	#1,d1
	cmp.w	d3,d1
	bls	.cr
	move.l	ren_cur,a2
	tst.l	d6
	beq	.out
	move.l	d6,ren_rmask
	addq.l	#1,ren_repairs
	; per line the sprite drew in ren_ra .. ren_rb - 1, in a marked cell row, per destination word
	move.w	ren_nrow,d4
	subq.w	#1,d4			; rows - 1
	move.l	ren_maskp,a3		; masks: row r at the line ren_y0 + r * step
	move.w	ren_s,d5
	moveq	#16,d6
	sub.w	d5,d6
	moveq	#0,d2
	move.b	SL_PRI(a2),d2
	addq.b	#1,d2
	move.w	ren_y0,d3
.ln:	move.l	(a3)+,d0		; the row's mask
	cmp.w	ren_ra,d3
	blt	.lnn
	cmp.w	ren_rb,d3
	bge	.lnn
	move.w	d3,d1
	add.w	ren_ey,d1
	lsr.w	#3,d1
	sub.w	ren_rrow,d1
	btst	d1,ren_rmask+3
	beq	.lnn
	lea	ren_bar_line,a0
	cmp.b	(a0,d3.w),d2
	bcs	.lnn			; (not drawn)
	; the shifted mask's words into ren_mw (3 words), with the clip masks
	move.l	d0,d1
	lsr.l	d5,d1
	move.w	d1,ren_mw+2
	swap	d1
	move.w	d1,ren_mw
	lsl.w	d6,d0
	move.w	d0,ren_mw+4
	move.w	ren_c0,d0
	and.w	d0,ren_mw
	move.w	ren_c1,d0
	and.w	d0,ren_mw+2
	move.w	ren_c2,d0
	and.w	d0,ren_mw+4
	; the line's addresses
	move.w	d3,d0
	add.w	#REN_GUARD,d0
	ext.l	d0
	moveq	#9,d1
	lsl.l	d1,d0
	add.l	ren_dbuf,d0
	move.l	d0,a4			; the buffer line
	move.w	d3,d0
	ext.l	d0
	lsl.l	#8,d0
	lea	ren_pri,a5
	add.l	d0,a5			; the priority line
	moveq	#0,d1			; word
.wd:	move.w	ren_g0,d0
	add.w	d1,d0
	lea	ren_mw,a0
	add.w	d1,a0
	add.w	d1,a0
	move.w	(a0),d5			; the sprite's pixels in this word
	beq	.wn
	move.w	d0,-(sp)
	and.w	#31,d0
	lsl.w	#3,d0
	movem.w	(a5,d0.w),a0/a1/a6	; q0 q1 q2 (sign extended)
	move.w	(sp)+,d0
	bsr	ren_pri_above		; d7 = P -> d6 = the pixels above P (uses a0 a1 a6)
	and.w	d6,d5
	beq	.wn
	; put back the background on d5's pixels
	move.l	#256,d6
	cmp.w	#32,d0
	blt	.t1
	neg.l	d6
.t1:	ext.l	d0
	lsl.l	#3,d0
	lea	(a4,d0.l),a0		; the destination group
	lea	(a0,d6.l),a2		; its twin
	move.w	d5,d6
	not.w	d6
	move.w	d1,-(sp)
	rept	4
	move.w	(a0),d0
	and.w	d6,d0
	move.w	(a2)+,d1
	and.w	d5,d1
	or.w	d1,d0
	move.w	d0,(a0)+
	endr
	move.w	(sp)+,d1
.wn:	move.w	ren_s,d5		; (d5 again: the skew)
	moveq	#16,d6
	sub.w	d5,d6
	addq.w	#1,d1
	cmp.w	ren_nw,d1
	blo	.wd
.lnn:	tst.w	ren_step
	bmi	.up
	addq.w	#1,d3
	bra	.lc
.up:	subq.w	#1,d3
.lc:	dbf	d4,.ln
.out:	movem.l	(sp)+,d0-d7/a0-a6
	rts

; d7 = P, a0 / a1 / a6 = the priority bit planes' words (bits 0, 1, 2) -> d6.w = the pixels whose priority is
; above P.  Keeps the rest.
ren_pri_above:
	move.l	d0,-(sp)
	move.w	d7,d0
	add.w	d0,d0
	move.w	.tab(pc,d0.w),d0
	jmp	.tab(pc,d0.w)
.tab:	dc.w	.p0-.tab,.p1-.tab,.p2-.tab,.p3-.tab,.p4-.tab,.p5-.tab,.p6-.tab,.p7-.tab
.p0:	move.w	a0,d6			; > 0: any bit
	move.w	a1,d0
	or.w	d0,d6
	move.w	a6,d0
	or.w	d0,d6
	bra	.o
.p1:	move.w	a1,d6			; > 1: q2 | q1
	move.w	a6,d0
	or.w	d0,d6
	bra	.o
.p2:	move.w	a1,d6			; > 2: q2 | (q1 & q0)
	move.w	a0,d0
	and.w	d0,d6
	move.w	a6,d0
	or.w	d0,d6
	bra	.o
.p3:	move.w	a6,d6			; > 3: q2
	bra	.o
.p4:	move.w	a1,d6			; > 4: q2 & (q1 | q0)
	move.w	a0,d0
	or.w	d0,d6
	move.w	a6,d0
	and.w	d0,d6
	bra	.o
.p5:	move.w	a6,d6			; > 5: q2 & q1
	move.w	a1,d0
	and.w	d0,d6
	bra	.o
.p6:	move.w	a6,d6			; > 6: q2 & q1 & q0
	move.w	a1,d0
	and.w	d0,d6
	move.w	a0,d0
	and.w	d0,d6
	bra	.o
.p7:	moveq	#0,d6
.o:	move.l	(sp)+,d0
	rts

; the buffer's damage put back (twin columns), its list emptied.  The bar image's rectangles only when the window and
; the bar image are as they were then (else ren_bars copies all bar lines, and a change of the bar lines redraws the
; group's cells)
ren_restore:
	move.w	ren_draw,d0
	add.w	d0,d0
	lea	ren_bar_w,a0
	move.w	ren_w,d1
	cmp.w	(a0,d0.w),d1
	seq	ren_barok
	lea	ren_bar_v,a0
	move.w	ren_fi_ver,d1
	cmp.w	(a0,d0.w),d1
	beq	.bv
	sf	ren_barok
.bv:
	move.w	ren_draw,d0
	add.w	d0,d0
	lea	ren_dmgall,a0
	move.w	(a0,d0.w),d1
	bpl	.lst
	clr.w	(a0,d0.w)
	bsr	ren_restore_all
.lst:	move.w	ren_draw,d0
	move.w	d0,d1
	lsl.w	#2,d0
	lea	ren_dmg_end,a0
	move.l	(a0,d0.w),a3
	mulu	#REN_DMG*12,d1
	lea	ren_dmg,a2
	add.l	d1,a2
	move.l	a2,(a0,d0.w)		; (emptied)
	move.l	a2,ren_dmgp		; (this picture's list: ren_dmgp, stored at the end)
	move.l	a2,ren_dmgbase
	lea	REN_DMG*12(a2),a0
	move.l	a0,ren_dmglim
; the rectangles a2 .. a3 put back
ren_restore_list:
	cmp.l	a3,a2
	bhs	.out
	moveq	#-1,d0
	move.w	d0,BLT_E1.w
	move.w	d0,BLT_E2.w
	move.w	d0,BLT_E3.w
	move.w	#2,BLT_SXI.w
	move.w	#2,BLT_DXI.w
	move.w	#$0203,BLT_HOP.w
	clr.b	BLT_SKEW.w
.r:	move.l	(a2)+,d0		; destination
	move.l	(a2)+,d1		; source
	move.w	(a2)+,d2		; words
	move.w	(a2)+,d3		; lines
	tst.w	d2
	bmi	.bar
	move.w	d2,d4
	subq.w	#1,d4
	add.w	d4,d4
	neg.w	d4
	add.w	#REN_LINEB,d4
	move.w	d4,BLT_SYI.w
	move.w	d4,BLT_DYI.w
	move.w	d2,BLT_XC.w
	move.l	d1,BLT_SRC.w
	move.l	d0,BLT_DST.w
	move.w	d3,BLT_YC.w
	bsr	blit_go
	addq.l	#1,ren_restores
	cmp.l	a3,a2
	blo	.r
.out:	rts
.bar:	tst.b	ren_barok
	beq	.bsk
	and.w	#$7fff,d2		; a bar image rectangle: a pass a plane, shifted by the window's fine scroll
	move.w	#8,BLT_SXI.w
	move.w	#8,BLT_DXI.w
	move.w	d2,d4
	lsl.w	#3,d4
	neg.w	d4
	add.w	#FI_STRIDE,d4
	move.w	d4,BLT_SYI.w
	add.w	#REN_LINEB-FI_STRIDE+8,d4
	move.w	d4,BLT_DYI.w
	move.w	d2,BLT_XC.w
	moveq	#15,d4
	and.w	ren_w,d4
	or.b	#BLT_FXSR,d4
	move.b	d4,BLT_SKEW.w
	moveq	#4-1,d4
.bp:	move.l	d1,BLT_SRC.w
	move.l	d0,BLT_DST.w
	move.w	d3,BLT_YC.w
	bsr	blit_go
	addq.l	#2,d0
	addq.l	#2,d1
	dbf	d4,.bp
	addq.l	#1,ren_restores
	move.w	#2,BLT_SXI.w		; (the twin copies' settings again)
	move.w	#2,BLT_DXI.w
	clr.b	BLT_SKEW.w
.bsk:	cmp.l	a3,a2
	blo	.r
	rts

; the damage list overflowed in this buffer's last picture: the whole window it had (d1.w: W) put back from the
; twin columns, all its lines (and the bar lines copied again).
ren_restore_all:
	movem.l	d0-d7/a0-a2,-(sp)
	and.w	#511,d1
	lsr.w	#4,d1			; the first group
	move.w	d1,d0
	add.w	#21,d1			; the group after the last
	moveq	#-REN_GUARD,d2
	move.w	#224+REN_GUARD,d3
	move.w	ren_draw,d4
	add.w	d4,d4
	lea	ren_bar_w,a0
	move.w	#-1,(a0,d4.w)		; (the bars all again)
	move.l	ren_dmgp,-(sp)
	move.l	ren_dmglim,-(sp)
	move.l	ren_dmgbase,-(sp)
	lea	ren_dmgtmp,a0		; (a list of its own, put back at once)
	move.l	a0,ren_dmgp
	move.l	a0,ren_dmgbase
	lea	8*12(a0),a1
	move.l	a1,ren_dmglim
	clr.w	ren_nbarsave
	move.w	ren_nbar,ren_nbarsave
	clr.w	ren_nbar		; (every line from the twins)
	bsr	ren_damage
	move.w	ren_nbarsave,ren_nbar
	lea	ren_dmgtmp,a2
	move.l	ren_dmgp,a3
	bsr	ren_restore_list
	move.l	(sp)+,ren_dmgbase
	move.l	(sp)+,ren_dmglim
	move.l	(sp)+,ren_dmgp
	movem.l	(sp)+,d0-d7/a0-a2
	rts

; The objects in priority order: the overlay layers (ren_ovl) between the sprites, each sprite after the overlays of
; its priority or lower (and the sprites in their list order within the stretch between two overlays).
ren_objects:
	; the clip groups: the group boundaries in the side bands nearest the picture's edges
	move.w	ren_w,d0
	add.w	#16,d0
	asr.w	#4,d0
	move.w	d0,ren_cl
	move.w	ren_w,d0
	add.w	#304+15,d0
	asr.w	#4,d0
	move.w	d0,ren_cr
	ifd	REN_NOCLIP		; (render_test: the band check must see this)
	subq.w	#4,ren_cl
	addq.w	#4,ren_cr
	endc
	move.w	#2,BLT_SXI.w		; (the sprite lines' Blitter settings, for ren_draw_image)
	move.w	#2,BLT_SYI.w
	move.w	#8,BLT_DXI.w
	move.w	#$0203,BLT_HOP.w
	moveq	#-1,d6			; the priority drawn up to
	moveq	#0,d5			; the next overlay
.stretch:
	moveq	#8,d4			; the next overlay's priority (8: none)
	cmp.w	ren_novl,d5
	bhs	.sp
	lea	ren_ovl,a0
	move.w	d5,d0
	add.w	d0,d0
	moveq	#0,d4
	move.b	1(a0,d0.w),d4
.sp:	; the sprites with priority > d6 and < d4, in list order
	lea	ren_slist,a2
	move.w	ren_nspr,d7
	bra	.st
.s:	moveq	#0,d0
	move.b	SL_PRI(a2),d0
	cmp.w	d6,d0
	ble	.sn
	cmp.w	d4,d0
	bge	.sn
	movem.l	d4-d7/a2,-(sp)
	move.l	#ren_sprite_get,ren_getter
	bsr	ren_draw_obj
	movem.l	(sp)+,d4-d7/a2
.sn:	lea	SL_SIZE(a2),a2
.st:	dbf	d7,.s
	cmp.w	#8,d4
	bhs	.out
	move.w	d4,d6
	subq.w	#1,d6			; (sprites of the overlay's priority come after it)
	movem.l	d4-d6,-(sp)
	move.w	d5,d0
	bsr	ren_overlay
	movem.l	(sp)+,d4-d6
	addq.w	#1,d5
	bra	.stretch
.out:	rts

; Overlay layer number d0 (ren_ovl: layer, pri): its visible non-empty cells drawn as 8 x 8 images (the cache's
; converted cells) with the sprites' code.  Layers 0-3 at their own scroll; the fixed layers' cells outside the bar rows.
ren_overlay:
	lea	ren_ovl,a0
	add.w	d0,d0
	moveq	#0,d7
	move.b	(a0,d0.w),d7		; layer
	moveq	#0,d6
	move.b	1(a0,d0.w),d6		; pri
	lea	ren_ocell,a2		; the fake list entry
	move.b	d6,SL_PRI(a2)
	clr.b	SL_FL(a2)
	move.b	#8,SL_SX(a2)
	move.b	#8,SL_SY(a2)
	cmp.w	#4,d7
	bhs	.fixed
	move.w	d7,d0
	lsl.w	#4,d0
	lea	ren_lay,a3
	add.w	d0,a3
	moveq	#0,d0
	move.b	5(a3),d0
	move.w	d0,ren_obank
	moveq	#0,d0
	move.b	7(a3),d0
	move.w	d0,ren_omask		; rows - 1
	move.w	d7,d0
	lsl.w	#8,d0
	lsl.w	#5,d0
	move.w	d0,ren_ooff		; the layer's tile RAM
	move.w	2(a3),d5		; ey
	move.w	d5,d0
	and.w	#7,d0
	neg.w	d0
	move.w	d0,ren_oy		; the first row's y'
	lsr.w	#3,d5
	moveq	#29-1,d4		; rows
	ifd	TILE_FLAG
	; the layer's bitmap of non-empty cells (ren_obm, a row rebuilt when tile RAM may have changed since): the
	; visible rows' bits of the 37 columns, cells wholly outside the clip groups left out
	move.w	(a3),d3			; ex
	move.w	d3,d0
	and.w	#7,d0
	neg.w	d0
	move.w	d0,ren_ox		; the first column's x'
	lsr.w	#3,d3
	move.w	d3,ren_oc0		; the first column
	move.w	ren_w,d0		; the cull: x' + W + 16 >> 4 in cl - 1 .. cr - 1
	add.w	#16,d0
	add.w	ren_ox,d0
	move.w	d0,ren_obx
	lsl.w	#6,d7
	move.w	d7,ren_olrow		; (the layer's first bitmap row)
.br:	and.w	ren_omask,d5
	move.w	d5,d0
	add.w	ren_olrow,d0		; the bitmap row
	move.w	d0,d1
	lsl.w	#2,d1
	lea	ren_obst,a0
	move.l	ren_tgen,d2
	cmp.l	(a0,d1.w),d2
	beq	.bok
	move.l	d2,(a0,d1.w)
	bsr	ren_obuild
.bok:	lea	ren_obr,a0
	tst.b	(a0,d0.w)
	beq	.bnx
	lsl.w	#4,d0
	lea	ren_obm,a0
	add.w	d0,a0
	move.w	ren_oc0,d0
	move.w	d0,d1
	lsr.w	#3,d1
	add.w	d1,a0			; the first column's byte
	and.w	#7,d0
	moveq	#0,d6
	sub.w	d0,d6			; (the byte's first bit: column c0 + d6)
	add.w	#36,d0
	lsr.w	#3,d0
	move.w	d0,d1			; bytes - 1
.bb:	move.b	(a0)+,d2
	bne	.bit
	addq.w	#8,d6
	dbf	d1,.bb
	bra	.bnx
.bit:	moveq	#8-1,d0
.bt:	add.b	d2,d2
	bcc	.bn
	cmp.w	#37,d6
	bhs	.bn
	move.w	d6,d7
	lsl.w	#3,d7
	move.w	ren_obx,d3
	add.w	d7,d3
	asr.w	#4,d3			; the cell's first group
	addq.w	#2,d3
	cmp.w	ren_cl,d3
	ble	.bn			; (wholly left of the clip)
	subq.w	#2,d3
	cmp.w	ren_cr,d3
	bge	.bn			; (wholly right)
	movem.l	d0-d6/a0/a3,-(sp)
	add.w	ren_ox,d7
	move.w	d7,SL_X(a2)
	move.w	ren_oy,SL_Y(a2)
	add.w	ren_oc0,d6
	and.w	#63,d6
	add.w	d6,d6
	move.w	d5,d0
	lsl.w	#7,d0
	add.w	d6,d0
	add.w	ren_ooff,d0
	lea	vio+V_TILE,a0
	move.w	(a0,d0.w),d0
	and.w	#$3fff,d0
	move.w	ren_obank,d1
	move.w	d0,ren_gcode
	move.w	d1,ren_gbank
	bsr	ren_cell_get
	bsr	ren_ovl_skip
	bne	.bs
	addq.l	#1,ren_ocells
	move.l	#ren_cell_getg,ren_getter
	bsr	ren_draw_obj
.bs:	movem.l	(sp)+,d0-d6/a0/a3
.bn:	addq.w	#1,d6
	dbf	d0,.bt
	dbf	d1,.bb
.bnx:	addq.w	#8,ren_oy
	addq.w	#1,d5
	dbf	d4,.br
	rts
	endc
	move.w	#-1,ren_oblank		; (no blank word known)
.r:	and.w	ren_omask,d5
	move.w	d5,d0
	lsl.w	#7,d0
	add.w	ren_ooff,d0
	lea	vio+V_TILE,a4
	add.w	d0,a4			; the row
	move.w	(a3),d3			; ex
	move.w	d3,d0
	and.w	#7,d0
	neg.w	d0
	move.w	d0,ren_ox		; the first column's x'
	lsr.w	#3,d3			; the first column
	; two runs of words: to the row's end, from its start (37 columns)
	moveq	#64,d2
	sub.w	d3,d2			; columns to the end
	cmp.w	#37,d2
	bls	.two
	moveq	#37,d2
.two:	move.w	d3,d0
	add.w	d0,d0
	lea	(a4,d0.w),a0
	move.w	d2,d1
	bsr	.run
	moveq	#37,d1
	sub.w	d2,d1
	beq	.rn
	move.l	a4,a0
	bsr	.run
.rn:	addq.w	#8,ren_oy
	addq.w	#1,d5
	dbf	d4,.r
	rts
; d1 words from a0 (the columns from ren_ox on): the non-empty cells drawn; ren_ox advanced past them
.run:	subq.w	#1,d1
	move.w	ren_oblank,d6
.w:	cmp.w	(a0)+,d6		; (a blank word: next)
	dbne	d1,.w
	beq	.rend
	movem.l	d1-d6/a0/a3-a4,-(sp)
	move.l	a0,d0
	sub.l	a4,d0
	subq.w	#2,d0
	lsl.w	#2,d0			; (the column * 8)
	move.w	d3,d1
	lsl.w	#3,d1
	sub.w	d1,d0
	and.w	#511,d0
	add.w	ren_ox,d0
	move.w	d0,SL_X(a2)		; x' = (column - first) * 8 + the first's x'
	move.w	ren_oy,SL_Y(a2)
	move.w	-2(a0),d0
	and.w	#$3fff,d0
	lea	ren_chrflag,a1
	tst.b	(a1,d0.w)
	bne	.ne
	move.w	-2(a0),ren_oblank	; (blank: the word to skip from now on)
	bra	.wn
.ne:	move.w	ren_obank,d1
	move.w	d0,ren_gcode
	move.w	d1,ren_gbank
	bsr	ren_cell_get
	bsr	ren_ovl_skip
	bne	.wn
	addq.l	#1,ren_ocells
	move.l	#ren_cell_getg,ren_getter
	bsr	ren_draw_obj
.wn:	movem.l	(sp)+,d1-d6/a0/a3-a4
	move.w	ren_oblank,d6
	dbf	d1,.w
.rend:	rts
.fixed:	; layer 4 or 5: the cells of the non-bar rows
	lea	ren_fix,a3
	move.w	#$7010,d0
	cmp.w	#4,d7
	beq	.f4
	addq.l	#4,a3
	move.w	#$7810,d0
.f4:	move.w	d0,ren_ooff
	moveq	#0,d0
	move.b	2(a3),d0
	move.w	d0,ren_obank
	moveq	#0,d5			; row
.fr:	lea	ren_frow,a0
	tst.b	(a0,d5.w)
	bne	.frn
	move.w	d5,d0
	mulu	#36*2,d0
	add.w	ren_ooff,d0
	lea	vio+V_TILE,a4
	add.w	d0,a4			; the row's words
	moveq	#0,d3
.fcl:	move.w	(a4)+,d0
	and.w	#$3fff,d0
	lea	ren_chrflag,a0
	tst.b	(a0,d0.w)
	beq	.fcn
	move.w	d3,d1
	lsl.w	#3,d1
	move.w	d1,SL_X(a2)
	move.w	d5,d1
	lsl.w	#3,d1
	move.w	d1,SL_Y(a2)
	move.w	ren_obank,d1
	movem.l	d3-d5/a2-a4,-(sp)
	move.w	d0,ren_gcode
	move.w	d1,ren_gbank
	bsr	ren_cell_get
	bsr	ren_ovl_skip
	bne	.fsk
	addq.l	#1,ren_ocells
	move.l	#ren_cell_getg,ren_getter
	bsr	ren_draw_obj
.fsk:	movem.l	(sp)+,d3-d5/a2-a4
.fcn:	addq.w	#1,d3
	cmp.w	#36,d3
	blo	.fcl
.frn:	addq.w	#1,d5
	cmp.w	#28,d5
	blo	.fr
	rts

; d0.w = a bitmap row (layer * 64 + row), d5.w = the row in the layer (ren_ooff: the layer's tile RAM): the row's
; bits (bit 7 of byte 0: column 0; a cell is non-empty when its character has opaque pixels) into ren_obm (8 bytes,
; then the same again: 37 columns from any first are consecutive), whether any into ren_obr.  Keeps all.
ren_obuild:
	movem.l	d0-d7/a0-a2,-(sp)
	move.w	d0,d3
	lea	ren_obm,a2
	move.w	d0,d1
	lsl.w	#4,d1
	add.w	d1,a2
	move.w	d5,d0
	lsl.w	#7,d0
	add.w	ren_ooff,d0
	lea	vio+V_TILE,a0
	add.w	d0,a0
	lea	ren_chrflag,a1
	move.w	#$3fff,d6
	moveq	#0,d7			; (the bytes' OR)
	moveq	#8-1,d4
.by:	moveq	#0,d2
	rept	8
	move.w	(a0)+,d0
	and.w	d6,d0
	move.b	(a1,d0.w),d1
	neg.b	d1			; (X: non-empty)
	addx.b	d2,d2
	endr
	move.b	d2,8(a2)
	move.b	d2,(a2)+
	or.b	d2,d7
	dbf	d4,.by
	lea	ren_obr,a1
	tst.b	d7
	sne	(a1,d3.w)
	movem.l	(sp)+,d0-d7/a0-a2
	rts

; a1 = an overlay cell's image, a2 = its list entry: Z clear when it cannot show: an opaque black cell below all the
; group's layers (it shows only where the group has nothing: black there anyway), or ren_covered.  Keeps all but d7.
ren_ovl_skip:
	tst.w	6(a1)
	beq	ren_covered
	tst.b	ren_grp_n
	beq	ren_covered
	move.b	SL_PRI(a2),d7
	cmp.b	ren_grp_min,d7
	bhs	ren_covered
	moveq	#1,d7			; (Z clear)
	rts

; a2 = an overlay cell's list entry (code in d0.w): Z clear when the group covers it wholly with layers above its
; priority (it cannot show), Z set when it must be drawn (or is outside the picture).  Keeps d0-d7/a2-a6.
ren_covered:
	movem.l	d0-d6,-(sp)
	tst.w	ren_nbar		; all its lines bar lines of a higher priority: hidden
	beq	.nobar
	move.w	SL_Y(a2),d2
	bmi	.nobar
	cmp.w	#224-8,d2
	bgt	.nobar
	moveq	#0,d6
	move.b	SL_PRI(a2),d6
	addq.b	#1,d6
	lea	ren_bar_line,a0
	cmp.b	(a0,d2.w),d6
	bhs	.nobar
	cmp.b	7(a0,d2.w),d6
	bhs	.nobar
	lea	ren_bar_cum,a0
	add.w	d2,d2
	move.w	16(a0,d2.w),d0
	sub.w	(a0,d2.w),d0
	cmp.w	#8,d0
	beq	.hidden
.nobar:	tst.b	ren_grp_n
	beq	.draw
	moveq	#0,d6
	move.b	SL_PRI(a2),d6
	cmp.b	ren_grp_max,d6
	bhs	.draw
	move.w	SL_Y(a2),d2
	bmi	.draw
	cmp.w	#224-8,d2
	bgt	.draw
	move.w	SL_X(a2),d3
	bmi	.draw
	cmp.w	#288-8,d3
	bgt	.draw
	add.w	ren_ey,d2		; the group cells: rows (y + ey) / 8 .. (y + 7 + ey) / 8, likewise the columns
	add.w	ren_ex,d3
	lea	ren_cellmin,a0
	moveq	#2-1,d4
.r:	move.w	d2,d5
	lsr.w	#3,d5
	and.w	#63,d5
	lsl.w	#6,d5			; the row
	move.w	d3,d1
	lsr.w	#3,d1
	and.w	#63,d1
	add.w	d5,d1
	cmp.b	(a0,d1.w),d6
	bhs	.draw
	move.w	d3,d1
	addq.w	#7,d1
	lsr.w	#3,d1
	and.w	#63,d1
	add.w	d5,d1
	cmp.b	(a0,d1.w),d6
	bhs	.draw
	addq.w	#7,d2
	dbf	d4,.r
.hidden:
	movem.l	(sp)+,d0-d6
	moveq	#1,d7			; (Z clear: covered)
	rts
.draw:	movem.l	(sp)+,d0-d6
	moveq	#0,d7			; (Z set)
	rts

; (ren_getter for overlay cells: the character ren_gcode of bank ren_gbank)
ren_cell_getg:
	move.w	ren_gcode,d0
	move.w	ren_gbank,d1
	bra	ren_cell_get

; a2 = a list entry, ren_getter its image's getter: drawn in the palette of the lines it covers.  An object only in
; the playfield's lines (or hidden in the HUD bars by them): the playfield's palette; only in the HUD region: the HUD's;
; across the boundary: twice, the playfield's lines and then the HUD's (ren_linesel 1, 2).
ren_draw_obj:
	sf	ren_curmap
	clr.b	ren_linesel
	tst.w	ren_hudn
	beq	.pf
	moveq	#0,d6
	move.b	SL_PRI(a2),d6
	addq.b	#1,d6			; (a bar line shows it when its value is at most this)
	move.w	SL_Y(a2),d2
	moveq	#0,d3
	move.b	SL_SY(a2),d3
	add.w	d2,d3			; lines d2 .. d3 - 1
	moveq	#0,d4			; in the HUD region (visible there)?
	moveq	#0,d5			; in the playfield's lines?
	lea	ren_bar_line,a0
	move.w	ren_htop,d0		; the top part: lines 0 .. htop - 1
	beq	.b
	cmp.b	(a0),d6
	blo	.b
	cmp.w	d0,d2
	bge	.b
	tst.w	d3
	ble	.b
	moveq	#1,d4
.b:	move.w	ren_hbot,d0		; the bottom part: hbot .. 223
	cmp.w	#224,d0
	bhs	.p
	cmp.b	223(a0),d6
	blo	.p
	cmp.w	#224,d2
	bge	.p
	cmp.w	d0,d3
	ble	.p
	moveq	#1,d4
.p:	cmp.w	ren_htop,d3		; the playfield's lines htop .. hbot - 1 (the guard lines: either)
	ble	.pd
	cmp.w	ren_hbot,d2
	bge	.pd
	moveq	#1,d5
.pd:	tst.w	d4
	beq	.pf
	tst.w	d5
	beq	.hud
	move.b	#1,ren_linesel		; both: the playfield's lines, then the HUD's
	bsr	.draw
	move.l	ren_cur,a2
	move.b	#2,ren_linesel
	st	ren_curmap
	bsr	.draw
	bra	.out
.hud:	st	ren_curmap		; (its lines all in the HUD region: drawn as usual, in the HUD's palette)
.pf:	bsr	.draw
.out:	sf	ren_curmap
	clr.b	ren_linesel
	rts
.draw:	move.l	a2,-(sp)
	move.l	ren_getter,a0
	jsr	(a0)
	move.l	(sp)+,a2
	bra	ren_draw_image

; d0.w = a character, d1.w = its bank: a1 = its converted 8 x 8 image (cache key $80000000 | bank << 14 | code).
; Keeps a2.
ren_cell_get:
	moveq	#0,d2
	move.w	d1,d2
	move.w	d1,d2
	moveq	#14,d3
	lsl.l	d3,d2
	or.w	d0,d2
	bset	#31,d2
	tst.b	ren_curmap
	beq	.k0
	bset	#30,d2			; (the HUD's palette)
.k0:
	move.w	d0,d3			; (the code)
	move.l	d2,d0
	move.w	d1,d4			; (the bank)
	bsr	ren_cache_find
	bne	.hit
	addq.l	#1,ren_misses
	movem.l	d2-d7/a2-a6,-(sp)
	moveq	#8+8*4+8*8,d1
	bsr	ren_cache_new
	move.l	a1,-(sp)
	move.w	#8,(a1)+
	clr.w	(a1)+
	move.w	#1,(a1)+
	clr.w	(a1)+
	moveq	#0,d1
	move.w	d3,d1
	lsl.l	#3,d1
	lea	ren_chrmask,a0
	add.l	d1,a0
	moveq	#8-1,d0
	moveq	#-1,d5			; (the masks' AND: opaque?)
.m:	moveq	#0,d1
	move.b	(a0)+,d1
	and.b	d1,d5
	ror.l	#8,d1			; (left aligned)
	move.l	d1,(a1)+
	dbf	d0,.m
	moveq	#0,d6			; (the rows' OR: black?)
	move.w	d4,d0
	bsr	ren_mt_get
	move.l	a0,a3
	lea	ren_zero64,a0
	cmp.w	#REN_NCHR,d3
	bhs	.z
	moveq	#0,d1
	move.w	d3,d1
	lsl.l	#6,d1
	lea	ren_chr,a0
	add.l	d1,a0
.z:	moveq	#8-1,d7
.row:	moveq	#0,d1
	rept	8
	moveq	#0,d0
	move.b	(a0)+,d0
	add.w	d0,d0
	add.w	d0,d0
	add.l	d1,d1
	or.l	(a3,d0.w),d1
	endr
	clr.l	(a1)
	clr.l	4(a1)
	movep.l	d1,0(a1)		; the planes' high bytes
	or.l	d1,d6
	addq.l	#8,a1
	dbf	d7,.row
	move.l	(sp)+,a1
	tst.l	d6			; opaque and black: header word 3 set (ren_ovl_skip)
	bne	.nb
	cmp.b	#$ff,d5
	bne	.nb
	move.w	#1,6(a1)
.nb:
	movem.l	(sp)+,d2-d7/a2-a6
.hit:	rts

; The C116's window: outside it the picture is black (MAME: no layer, no sprite there).  Black rectangles over the
; picture's parts outside it, put back next time like sprites.
ren_clipwin:
	lea	vio+V_C116,a0
	move.w	(a0),d0
	subq.w	#1,d0			; x0 = max(73, left - 1)
	cmp.w	#73,d0
	bge	.a
	moveq	#73,d0
.a:	move.w	2(a0),d1
	subq.w	#2,d1			; x1 = min(360, right - 2)
	cmp.w	#360,d1
	ble	.b
	move.w	#360,d1
.b:	move.w	4(a0),d2
	sub.w	#$11,d2			; y0 = max(16, top - 17)
	cmp.w	#16,d2
	bge	.c
	moveq	#16,d2
.c:	move.w	6(a0),d3
	sub.w	#$12,d3			; y1 = min(239, bottom - 18)
	cmp.w	#239,d3
	ble	.d
	move.w	#239,d3
.d:	cmp.w	d1,d0
	bgt	.allb
	cmp.w	d3,d2
	bgt	.allb
	; the player's view: x' 360 - x1 .. 360 - x0, y' 239 - y1 .. 239 - y0 (inclusive)
	move.w	#360,d4
	sub.w	d1,d4			; xa
	move.w	#361,d5
	sub.w	d0,d5			; xb (exclusive)
	move.w	#239,d6
	sub.w	d3,d6			; ya
	move.w	#240,d7
	sub.w	d2,d7			; yb (exclusive)
	tst.w	d4
	bne	.cut
	cmp.w	#288,d5
	bne	.cut
	tst.w	d6
	bne	.cut
	cmp.w	#224,d7
	bne	.cut
	rts				; (the whole picture)
.cut:	movem.w	d4-d7,-(sp)
	moveq	#0,d0			; above
	move.w	#288,d1
	moveq	#0,d2
	move.w	d6,d3
	bsr	ren_fill
	movem.w	(sp),d4-d7
	moveq	#0,d0			; below
	move.w	#288,d1
	move.w	d7,d2
	move.w	#224,d3
	bsr	ren_fill
	movem.w	(sp),d4-d7
	moveq	#0,d0			; left
	move.w	d4,d1
	move.w	d6,d2
	move.w	d7,d3
	bsr	ren_fill
	movem.w	(sp)+,d4-d7
	move.w	d5,d0			; right
	move.w	#288,d1
	move.w	d6,d2
	move.w	d7,d3
	bra	ren_fill
.allb:	moveq	#0,d0
	move.w	#288,d1
	moveq	#0,d2
	move.w	#224,d3
	bra	ren_fill

; Black over picture x d0 .. d1 - 1, y d2 .. d3 - 1 (clamped to the picture): a Blitter pass a plane, the end masks at
; the rectangle's edges; into the damage list.
ren_fill:
	tst.w	d0
	bpl	.x0
	moveq	#0,d0
.x0:	cmp.w	#288,d1
	ble	.x1
	move.w	#288,d1
.x1:	tst.w	d2
	bpl	.y0
	moveq	#0,d2
.y0:	cmp.w	#224,d3
	ble	.y1
	move.w	#224,d3
.y1:	cmp.w	d1,d0
	bge	.out
	cmp.w	d3,d2
	bge	.out
	addq.l	#1,ren_fills
	move.w	ren_w,d4
	add.w	#16,d4
	add.w	d4,d0			; buffer x
	add.w	d4,d1
	moveq	#-1,d4
	moveq	#15,d5
	and.w	d0,d5
	lsr.w	d5,d4			; END1
	moveq	#-1,d6
	move.w	d1,d5
	subq.w	#1,d5
	and.w	#15,d5
	eor.w	#15,d5
	lsl.w	d5,d6			; END3
	asr.w	#4,d0			; first group
	move.w	d1,d5
	subq.w	#1,d5
	asr.w	#4,d5			; last group
	move.w	d5,d1
	sub.w	d0,d1
	addq.w	#1,d1			; words a line
	cmp.w	#1,d1
	bne	.w
	and.w	d6,d4
.w:	move.w	d4,BLT_E1.w
	move.w	#-1,BLT_E2.w
	move.w	d6,BLT_E3.w
	move.w	d1,BLT_XC.w
	move.w	#8,BLT_DXI.w
	move.w	d1,d4
	subq.w	#1,d4
	lsl.w	#3,d4
	neg.w	d4
	add.w	#REN_LINEB,d4
	move.w	d4,BLT_DYI.w
	clr.w	BLT_HOP.w		; (HOP 0, op 0: zero)
	clr.b	BLT_SKEW.w
	movem.w	d0-d3/d5,-(sp)
	move.w	d2,d4
	add.w	#REN_GUARD,d4
	ext.l	d4
	moveq	#9,d6
	lsl.l	d6,d4
	move.w	d0,d6
	ext.l	d6
	lsl.l	#3,d6
	add.l	d6,d4
	add.l	ren_dbuf,d4
	sub.w	d2,d3			; lines
	moveq	#4-1,d6
.p:	move.l	d4,BLT_DST.w
	move.w	d3,BLT_YC.w
	bsr	blit_go
	addq.l	#2,d4
	dbf	d6,.p
	movem.w	(sp)+,d0-d3/d5
	move.w	d5,d1
	addq.w	#1,d1
	bra	ren_damage
.out:	rts

	section	data,data
ren_chr:	incbin	"ren_chr.bin"
ren_chrmask:	incbin	"ren_chrmask.bin"
ren_chrflag:	incbin	"ren_chrflag.bin"
ren_chruni:	incbin	"ren_chruni.bin"
ren_spr:	incbin	"ren_spr.bin"
ren_spr_idx:	incbin	"ren_spr_idx.bin"
ren_lab:	incbin	"ren_lab.bin"
ren_q4:		incbin	"ren_q4.bin"
	even

	section	bss,bss
	even
ren_buf_area:	ds.b	REN_NBUF*REN_BUFSZ+256
ren_pri:	ds.b	224*256
ren_tcopy:	ds.b	$8000
ren_dirty:	ds.b	4096
ren_cellpri:	ds.b	4096
ren_cellmin:	ds.b	4096
ren_dbank:	ds.b	4
ren_coldirty:	ds.b	64
ren_roll:	ds.w	1
ren_rrow:	ds.w	1
ren_rmask:	ds.l	1
ren_palsnap:	ds.b	$6000
ren_bankcol:	ds.b	8
ren_mt:		ds.l	16*256
ren_mt_ep:	ds.w	16
ren_t16:	ds.l	16
ren_exp:	ds.l	256
ren_pril:	ds.l	8
ren_pm16:	ds.w	256*8
ren_zero64:	ds.b	64
ren_hash:	ds.l	2*REN_HASH
ren_pool:	ds.b	REN_POOL
ren_pool_ptr:	ds.l	1
ren_ch:		ds.w	2*4096
ren_cs:		ds.b	2*4096
ren_cp:		ds.w	2*4096
ren_lut:	ds.b	2*4096
ren_cent:	ds.b	2*16*4
ren_ncent:	ds.w	2
ren_hrep:	ds.w	16
ren_hpal:	ds.w	16
ren_ksum:	ds.l	16*4
ren_hudn:	ds.w	1
ren_htop:	ds.w	1
ren_hbot:	ds.w	1
ren_curmap:	ds.b	1
	even
ren_sy:		ds.w	1
ren_smap:	ds.b	1
ren_linesel:	ds.b	1
	even
ren_getter:	ds.l	1
ren_gcode:	ds.w	1
ren_gbank:	ds.w	1
ren_pts:	ds.l	2*REN_MAXPTS
ren_axh:	ds.l	256
ren_boxes:	ds.b	16*REN_BOX
ren_tree:	ds.l	32
ren_rep:	ds.w	16
ren_pal:	ds.w	16
ren_vbl_pal:	ds.w	16
ren_vbl_hpal:	ds.w	16
ren_vbl_htop:	ds.w	1
ren_vbl_hbot:	ds.w	1
ren_disp_hpal:	ds.w	3*16
ren_disp_hud:	ds.w	3*2
ren_disp_pal:	ds.w	3*16
ren_disp_addr:	ds.l	3
ren_buf:	ds.l	4
ren_dbuf:	ds.l	1
ren_dmg:	ds.b	REN_NBUF*REN_DMG*12
ren_dmg_end:	ds.l	3
ren_bar_w:	ds.w	3
ren_bar_v:	ds.w	3
ren_bar_dirty:	ds.b	3*224
ren_bar_line:	ds.b	224
ren_lay:	ds.b	4*16
ren_grp_key:	ds.b	16
ren_newkey:	ds.b	16
ren_ex:		ds.w	1		; (ren_ex, ren_ey: one long)
ren_ey:		ds.w	1
ren_w:		ds.w	1
ren_ovl:	ds.b	12
ren_novl:	ds.w	1
ren_fix:	ds.b	8
ren_fixord:	ds.b	8
ren_nfix:	ds.w	1
ren_fi_ver:	ds.w	1
ren_src:	ds.b	3*16
ren_nsrc:	ds.w	1
ren_srow:	ds.w	1
ren_row:	ds.w	1
ren_col:	ds.w	1
ren_ytop:	ds.w	1
ren_row0:	ds.w	1
ren_col0:	ds.w	1
ren_nrows:	ds.w	1
ren_budget:	ds.w	1
ren_wcells:	ds.w	1
ren_changed:	ds.w	1
ren_epoch:	ds.w	1
ren_ntree:	ds.w	1
ren_npts:	ds.w	1
ren_nbox:	ds.w	1
ren_nspr:	ds.w	1
ren_slist:	ds.b	128*SL_SIZE
ren_sprev:	ds.b	128*24
ren_soffs:	ds.l	1
ren_pt:		ds.l	REN_PTS*1024
ren_pt_ep:	ds.w	REN_PTS
ren_ptslot:	ds.b	256
ren_ptown:	ds.b	REN_PTS
	even
ren_ptnext:	ds.w	1
ren_ptcur:	ds.w	1
ren_pt16:	ds.l	16
ren_brow:	ds.b	16
ren_bwords:	ds.l	8
ren_btmp:	ds.b	16
ren_mw:		ds.w	4
ren_bar_cum:	ds.w	226
ren_slot:	ds.l	1
ren_fi:		ds.b	224*FI_STRIDE
ren_fdirty:	ds.b	1008
ren_fcls:	ds.b	1008
ren_frow:	ds.b	28
ren_fne:	ds.b	28
	even
ren_fvis:	ds.w	2
ren_fix_old:	ds.l	2
ren_ocell:	ds.b	SL_SIZE
ren_obank:	ds.w	1
ren_omask:	ds.w	1
ren_ooff:	ds.w	1
ren_oblank:	ds.w	1
ren_ox:		ds.w	1
ren_oc0:	ds.w	1
ren_obx:	ds.w	1
ren_olrow:	ds.w	1
ren_tgen:	ds.l	1
ren_obst:	ds.l	4*64
ren_obr:	ds.b	4*64
ren_obm:	ds.b	4*64*16
ren_oy:		ds.w	1
ren_barcopies:	ds.l	1
ren_fills:	ds.l	1
ren_ocells:	ds.l	1
ren_slowclip:	ds.l	1
ren_dmgs:	ds.l	1
ren_rowchg:	ds.b	1
ren_allbars:	ds.b	1
ren_newcols:	ds.b	1
ren_fany:	ds.b	1
ren_wait:	ds.b	1
ren_qmode:	ds.b	1
	even
ren_smask:	ds.w	1
ren_qcount:	ds.w	1
ren_qbase:	ds.w	1
ren_qlast:	ds.w	1
ren_qsum:	ds.l	1
ren_qn:		ds.l	1
ren_qchecks:	ds.l	1
ren_requal:	ds.l	1
ren_stelab:	ds.l	16
ren_barmax:	ds.b	1
	even
ren_cur:	ds.l	1
ren_cur_img:	ds.l	1
ren_srcp:	ds.l	1
ren_misses:	ds.l	1
ren_bakes:	ds.l	1
ren_slowdraws:	ds.l	1
ren_repairs:	ds.l	1
ren_restores:	ds.l	1
ren_dmg_over:	ds.l	1
ren_nbar:	ds.w	1
ren_nw:		ds.w	1
ren_s:		ds.w	1
ren_g0:		ds.w	1
ren_cl:		ds.w	1
ren_cr:		ds.w	1
ren_c0:		ds.w	1
ren_c1:		ds.w	1
ren_c2:		ds.w	1
ren_dg0:	ds.w	1
ren_dg1:	ds.w	1
ren_ya:		ds.w	1
ren_yb:		ds.w	1
ren_y0:		ds.w	1
ren_ylast:	ds.w	1
ren_step:	ds.w	1
ren_ra:		ds.w	1
ren_nrow:	ds.w	1
ren_maskp:	ds.l	1
ren_dmgp:	ds.l	1
ren_dmgall:	ds.w	4
ren_dmgtmp:	ds.b	8*12
ren_nbarsave:	ds.w	1
ren_dmgbase:	ds.l	1
ren_dmglim:	ds.l	1
ren_rb:		ds.w	1
ren_bfx:	ds.b	1
	even
ren_cw:		ds.w	1
ren_cbw:	ds.w	1
ren_cvsave:	ds.w	1
ren_cvend:	ds.l	1
	even
ren_brr:	ds.w	1
ren_slow:	ds.b	1
ren_clip:	ds.b	1
ren_barok:	ds.b	1
ren_sv:		ds.b	4
	even
ren_draw:	ds.w	1
ren_shown:	ds.w	1
ren_prev:	ds.w	1
ren_ck:		ds.l	1
ren_ck_cluster:	ds.l	1
ren_skipped:	ds.l	1
	ifd	REN_PHASES
ren_ph_t:	ds.l	1
ren_ph_vbl:	ds.l	10
	endc
ren_pictures:	ds.l	1
ren_clusters:	ds.l	1
ren_flushes:	ds.l	1
ren_disp_fine:	ds.b	4
ren_ready:	ds.b	1
ren_grp_n:	ds.b	1
ren_grp_max:	ds.b	1
ren_grp_min:	ds.b	1
ren_fix_key:	ds.b	1
ren_full:	ds.b	1
ren_scene:	ds.b	1
ren_black:	ds.b	1
ren_allblack:	ds.b	1
ren_stable:	ds.b	1
	even
