; R-Type's stage renderer (the user's rule, 2026-10-29: keep the gameplay, leave out what only costs work).  It draws
; tools/stage_model.py's picture: the FG layer over an empty BG (the stars and any BG are not drawn yet), the sprites
; over both (no sprite / tile priority) as whole objects from the native emitters' records (src/natives.s
; SPRITE_LIST), a fixed STE palette per stage (tools/stage_assets.py) and the status bar from its own image.  The same
; interface as engine/rt/m72render.s: m72r_init, m72r_frame (a picture), m72r_vbl (show it), the palettes and the
; status bar's lines for borders.s (BD_HUD, BD_VSWITCH).
;
; It reads the program's state directly (no copies): the V30 image (src/core.s: words native) - the palettes
; ($C8000, $CC000), the FG and BG video RAMs ($D0000, $D8000) -, the blocks the translated stores marked (v30_vmarks:
; it clears the ones it reads), the object records (m72_objs .. m72_objs_end), the scroll registers before and after
; the raster interrupt (m72_scroll_vbl, m72_scroll), the raster line (m72_raster) and port $02 (m72_port02).
;
; Buffers: ST_NBUF display buffers and a clean one, 1024 x (64 + 256 + 64) pixels (ST_LB bytes a line; 64 guard
; lines above and below take whole sprites).  The FG map column c (8 pixels) is at buffer x 8c and 8c + 512, so the
; 320-pixel window at buffer x W = FG scroll x + 96 (mod 512) is always contiguous: the hardware shows it (video
; address and fine scroll, m72r_vbl), nothing is moved.  The clean buffer holds the composed map cells (composed
; when they come into the window or their tiles change: st_cells, tile conversions cached); each composition is
; logged (st_log) and copied into a display buffer before its next picture; a display buffer's sprites are erased
; by copying their rectangles from the clean buffer.
;
; Sprites: an object record (definition BW, entries, colour, x, y) -> its whole sprite (tools/stage_sprites.py:
; st_defs, per definition its strips: a shape of engine/sprite_programs.py's stream mode with long destinations, and
; its pens); a (definition, colour) is coloured into the cache once (st_bake: the colour row's tables; a row's
; version changes when its pens change index); a strip runs its shape's code for its shift.  Drawn from the last
; record to the first (the first on top).  The window's edges are not on 16-pixel boundaries (fine scroll), so the
; strips are drawn whole into the side margins (AGENTS.md); strips wholly outside are culled.
;
; Colours: a pen's index is the stage's colour table at its current colour (st_pidx; a palette row's pens again when
; the game writes the row), the reserved pens their own indices (their STE colour each picture: the pen's colour).

ST_LB		= 512
ST_G		= 64
ST_PL		= 256
ST_LINES	= ST_G+ST_PL+ST_G
ST_BUFSZ	= ST_LINES*ST_LB
	ifnd	ST_NBUF
ST_NBUF		= 3
	endc
ST_DMG		= 600			; erase rectangles a buffer (more: the whole buffer copied)
ST_LOG		= 2048			; clean-buffer changes kept (a power of 2)
ST_POOL		= 1024*1024		; the sprite colour cache
ST_HASH		= 16384
ST_TCN		= 4096			; tile conversions cached
ST_BARLB	= 160			; the status bar's image: 320 x 16
ST_HUDY		= 240

BLT_SXI		= $ffff8a20
BLT_SYI		= $ffff8a22
BLT_SRC		= $ffff8a24
BLT_END1	= $ffff8a28
BLT_END2	= $ffff8a2a
BLT_END3	= $ffff8a2c
BLT_DXI		= $ffff8a2e
BLT_DYI		= $ffff8a30
BLT_DST		= $ffff8a32
BLT_XC		= $ffff8a36
BLT_YC		= $ffff8a38
BLT_HOP		= $ffff8a3a
BLT_CTRL	= $ffff8a3c
BLT_SKEW	= $ffff8a3d

	section text,code

; ======================================================================================================================
; m72r_init
; ======================================================================================================================
m72r_init:
	movem.l	d0-d7/a0-a6,-(sp)
	lea	st_bufs,a0		; the buffers' addresses (each 256-byte aligned)
	move.l	#st_mem+255,d0
	and.w	#$FF00,d0
	moveq	#ST_NBUF+1-1,d1
.b:	move.l	d0,(a0)+
	add.l	#ST_BUFSZ,d0
	dbf	d1,.b
	move.l	d0,st_bar
	move.l	#st_pool,st_poolp
	move.l	#st_scenes+2,st_scn
	move.w	#-1,st_curscn
	; the definitions' lookup: BW >> 1 -> record (1: drawn as nothing - a star, an empty one)
	lea	st_defs,a0
	lea	st_deftab,a1
.d:	moveq	#0,d0
	move.w	(a0)+,d0
	beq.s	.dd
	move.l	(a0)+,d1
	bne.s	.d1
	moveq	#1,d1
.d1:	lsr.w	#1,d0
	lsl.l	#2,d0
	move.l	d1,(a1,d0.l)
	bra.s	.d
.dd:	; every palette block marked: the pens' indices made, the colour tables
	lea	v30_vmarks,a0
	moveq	#12-1,d0
.m:	st	(a0)
	st	$40(a0)
	addq.l	#1,a0
	dbf	d0,.m
	move.l	#$FFFFFFFF,d0
	lea	st_pcol,a0		; (no pen's colour known)
	move.w	#512/2-1,d1
.pc:	move.l	d0,(a0)+
	dbf	d1,.pc
	lea	st_ccol,a0		; (no current colour either)
	move.w	#512/2-1,d1
.cc:	move.l	d0,(a0)+
	dbf	d1,.cc
	move.l	#st_pend,st_pendp
	lea	st_rowprev,a0		; (no colours before)
	move.w	#512/2-1,d1
.rl:	move.l	d0,(a0)+
	dbf	d1,.rl
	lea	st_palraw,a0		; (every palette word read)
	move.w	#2*$C00/4-1,d1
.pr:	move.l	d0,(a0)+
	dbf	d1,.pr
	lea	st_barkey,a0		; (no bar cell drawn yet)
	moveq	#80-1,d1
.bk:	move.l	d0,(a0)+
	dbf	d1,.bk
	st	st_allnew		; (the first picture reads every palette word: st_palraw all -1)
	move.w	#-1,st_sy
	move.w	#-1,m72r_prev
	movem.l	(sp)+,d0-d7/a0-a6
	rts

; ======================================================================================================================
; m72r_frame: a picture
; ======================================================================================================================
m72r_frame:
	movem.l	d0-d7/a0-a6,-(sp)
.snap:	move.w	m72r_shown,d1		; the buffer: not shown, not the one shown before, not waiting
	move.w	m72r_prev,d2
	moveq	#0,d3
	move.b	m72r_ready,d3
	cmp.w	m72r_shown,d1
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
	cmp.w	#ST_NBUF,d0
	blo	.pick
	addq.l	#1,m72r_skipped
	movem.l	(sp)+,d0-d7/a0-a6
	rts
.chosen:
	move.w	d0,st_draw
	lsl.w	#2,d0
	lea	st_bufs,a0
	move.l	(a0,d0.w),st_dbuf
ST_PHASE macro				; (DEBUG: the phase for the VBL's sampled profile, rtype.s main_state)
	ifd	DEBUG
	ifnd	SIM
	move.b	#\1,main_state
	endc
	endc
	endm
	ST_PHASE 4
	ifnd	ST_NOPAL
	bsr	st_palette		; the pens' indices (the palette blocks the game wrote)
	endc
	ST_PHASE 5
	bsr	st_vram			; the video RAM rows the game wrote: the changed cells
	bsr	st_bands		; the window, the bar
	ST_PHASE 6
	bsr	st_compose		; the window's cells into the clean buffer
	ST_PHASE 7
	bsr	st_sync			; the clean buffer's changes and the last sprites' rectangles into this buffer
	ST_PHASE 8
	ifnd	ST_NOSPR
	bsr	st_sprites
	endc
	ST_PHASE 9
	bsr	st_bardraw
	ST_PHASE 2
	; publish: the video address, the fine scroll, the palettes, the bar, then the buffer (one byte store)
	move.w	st_draw,d0
	move.w	d0,d1
	lsl.w	#2,d1
	moveq	#0,d2
	move.w	st_W,d2
	lsr.w	#4,d2
	lsl.w	#3,d2
	add.l	st_dbuf,d2
	add.l	#ST_G*ST_LB,d2
	lea	m72r_disp_addr,a0
	move.l	d2,(a0,d1.w)
	moveq	#15,d2
	and.w	st_W,d2
	lea	m72r_disp_fine,a0
	move.b	d2,(a0,d0.w)
	lsl.w	#5,d0
	lea	m72r_disp_pal,a1
	add.w	d0,a1
	lea	m72r_disp_hpal,a2
	add.w	d0,a2
	lea	st_stepal,a0
	lea	st_hstepal,a3
	moveq	#16-1,d2
	tst.b	st_off
	bne.s	.blk
.pl:	move.w	(a0)+,(a1)+
	move.w	(a3)+,(a2)+
	dbf	d2,.pl
	bra.s	.pd
.blk:	clr.w	(a1)+			; (display off: black)
	clr.w	(a2)+
	dbf	d2,.blk
.pd:	lsr.w	#3,d0
	lea	m72r_disp_hud,a1
	clr.w	(a1,d0.w)
	move.w	st_hbot,2(a1,d0.w)
	lea	m72r_disp_bar,a1
	move.l	st_bar,(a1,d0.w)
	move.w	st_draw,d0
	addq.b	#1,d0
	move.b	d0,m72r_ready
	addq.l	#1,m72r_pictures
	movem.l	(sp)+,d0-d7/a0-a6
	rts

; ======================================================================================================================
; m72r_vbl: show a published picture (as engine/rt/m72render.s)
; ======================================================================================================================
m72r_vbl:
	tst.b	m72r_ready
	bne	.flip
	move.w	#-1,m72r_prev
	rts
.flip:	movem.l	d0-d2/a0-a1,-(sp)
	moveq	#0,d0
	move.b	m72r_ready,d0
	clr.b	m72r_ready
	subq.w	#1,d0
	move.w	m72r_shown,m72r_prev
	move.w	d0,m72r_shown
	move.w	d0,d1
	lsl.w	#2,d1
	lea	m72r_disp_addr,a0
	move.l	(a0,d1.w),d1
	ifd	PIC_TOP
	sub.l	#PIC_TOP*ST_LB,d1
	endc
	move.l	d1,-(sp)
	move.b	1(sp),$ffff8201.w
	move.b	2(sp),$ffff8203.w
	move.b	3(sp),$ffff820d.w
	ifnd	SIM
	move.b	1(sp),$ffff8205.w
	move.b	2(sp),$ffff8207.w
	move.b	3(sp),$ffff8209.w
	endc
	addq.l	#4,sp
	lea	m72r_disp_fine,a0
	move.b	(a0,d0.w),d2
	move.b	d2,$ffff8265.w
	move.b	#(ST_LB-160)/2,d1
	tst.b	d2
	beq	.w
	subq.b	#4,d1
.w:	move.b	d1,$ffff820f.w
	ifd	BD_VSWITCH
	if	BD_VSWITCH
	ext.w	d1
	move.w	d1,bd_vs_pfl
	ext.w	d2
	move.w	d2,bd_vs_pfh
	move.w	#ST_LB,bd_vs_pfs
	move.w	#ST_BARLB,bd_vs_bas
	clr.w	bd_vs_bal
	clr.w	bd_vs_bah
	move.w	d0,d1
	lsl.w	#2,d1
	lea	m72r_disp_addr,a0
	move.l	(a0,d1.w),bd_vs_pf
	lea	m72r_disp_hud,a0
	clr.b	bd_vs_on
	move.w	2(a0,d1.w),d2		; the bar's first line
	cmp.w	#256,d2
	bhs.s	.vx
	lea	m72r_disp_bar,a0
	mulu	#ST_BARLB,d2
	neg.l	d2
	add.l	(a0,d1.w),d2		; (picture line 0 of the bar's image)
	move.l	d2,bd_vs_bar
	st	bd_vs_on
.vx:
	endc
	endc
	lsl.w	#5,d0
	lea	m72r_disp_pal,a0
	add.w	d0,a0
	lea	m72r_vbl_pal,a1
	moveq	#8-1,d1
.p:	move.l	(a0)+,(a1)+
	dbf	d1,.p
	lea	m72r_disp_hpal,a0
	add.w	d0,a0
	lea	m72r_vbl_hpal,a1
	moveq	#8-1,d1
.hp:	move.l	(a0)+,(a1)+
	dbf	d1,.hp
	lsr.w	#3,d0
	lea	m72r_disp_hud,a0
	move.l	(a0,d0.w),m72r_vbl_htop
	movem.l	(sp)+,d0-d2/a0-a1
	rts

; ======================================================================================================================
; Colours
; ======================================================================================================================
; st_palette: the palette blocks the game wrote (v30_vmarks 0-11 palette 0, $40-$4B palette 1): each pen whose colour
; changed gets its index (the stage's colour table; the status bar's for the tile pens); a colour row whose indices
; changed gets new tables and a new version (its tile conversions and sprite colourings are made again; FG cells of a
; changed tile row are composed again: st_rowcells).  Then the STE palettes (the reserved indices: their pens' colours).
st_palette:
	; the marked blocks against their copy (st_palraw): the pens whose words differ listed (st_plist)
	lea	st_plist,a6
	lea	st_pflag,a5
	moveq	#0,d6			; the palette (0: $C8000, 1: $CC000)
.pals:	moveq	#0,d5			; its block
.blk:	lea	v30_vmarks,a4
	move.w	d6,d0
	lsl.w	#6,d0
	add.w	d5,d0
	tst.b	(a4,d0.w)
	beq	.bn
	clr.b	(a4,d0.w)
	move.w	d5,d0
	lsl.w	#8,d0			; the block's byte offset in the palette
	move.w	d0,d1
	and.w	#$3FF,d1
	cmp.w	#$200,d1
	bhs	.bn			; (a mirror: A9 set - not read)
	lsr.w	#1,d1			; the block's first pen
	move.w	d6,d2
	lsl.w	#8,d2
	add.w	d2,d1			; (+ 256 for the tile palette)
	moveq	#0,d2
	move.w	d6,d2
	swap	d2
	lsr.l	#2,d2			; (the palette's offset: $4000)
	add.w	d0,d2
	lea	v30_image+$C8000,a0
	add.l	d2,a0
	lea	st_palraw,a1
	move.w	d6,d2
	mulu	#$C00,d2
	add.w	d0,d2
	add.w	d2,a1
	moveq	#64-1,d3
.cmp:	cmpm.l	(a0)+,(a1)+
	beq	.ce
	move.l	-4(a0),-4(a1)
	moveq	#63,d4			; the long's two pens
	sub.w	d3,d4
	add.w	d4,d4
	add.w	d1,d4
	tst.b	(a5,d4.w)
	bne	.c2
	st	(a5,d4.w)
	move.w	d4,(a6)+
.c2:	addq.w	#1,d4
	tst.b	(a5,d4.w)
	bne	.ce
	st	(a5,d4.w)
	move.w	d4,(a6)+
.ce:	dbf	d3,.cmp
.bn:	addq.w	#1,d5
	cmp.w	#12,d5
	blo	.blk
	addq.w	#1,d6
	cmp.w	#2,d6
	blo	.pals
	move.l	a6,st_plend
	; (the colour rule, the user 2026-10-30: no colour animation with 16 colours.  A pen keeps its committed colour
	; (st_pcol, its index) until its palette row is loaded - ST_ROWLOAD or more of the row's pens off their committed
	; colours - or its new colour has stayed ST_STABLE pictures; a reserved pen follows its colour at once (fades))
	clr.l	st_rowchg		; (rows whose indices changed: bits 0-31 = sprite rows 0-15, tile rows 16-31)
	clr.l	st_rowtch		; (rows with a pen whose colour changed)
.pens0:	lea	st_plist,a6
	lea	st_q4,a5
.pa:	cmp.l	st_plend,a6		; A: the listed pens' current colours (st_ccol); a changed one is pending
	beq	.pb
	move.w	(a6)+,d7
	addq.l	#1,st_npens
	lea	st_pflag,a0
	clr.b	(a0,d7.w)
	move.w	d7,d0
	add.w	d0,d0
	lea	v30_image+$C8000,a0
	cmp.w	#256,d7
	blo	.p0
	lea	v30_image+$CC000-$200,a0
.p0:	add.w	d0,a0
	moveq	#31,d1
	and.w	(a0),d1
	move.b	(a5,d1.w),d1		; red, 4 bits
	lsl.w	#4,d1
	moveq	#31,d2
	and.w	$400(a0),d2
	or.b	(a5,d2.w),d1
	lsl.w	#4,d1
	moveq	#31,d2
	and.w	$800(a0),d2
	or.b	(a5,d2.w),d1		; the 12-bit colour
	lea	st_ccol,a1
	cmp.w	(a1,d0.w),d1
	beq	.pa
	move.w	d1,(a1,d0.w)
	lea	st_pchg,a0
	st	(a0,d7.w)		; (changed this picture)
	move.w	d7,d3
	lsr.w	#4,d3
	move.l	st_rowtch,d4
	bset	d3,d4
	move.l	d4,st_rowtch
	lea	st_pendf,a0
	tst.b	(a0,d7.w)
	bne	.pa
	st	(a0,d7.w)
	move.l	st_pendp,a0
	move.w	d7,(a0)+
	move.l	a0,st_pendp
	bra	.pa
.pb:	move.l	st_rowtch,d4		; B: a touched row with ST_ROWLOAD pens off their committed colours: loaded -
	beq	.pc			; unless it went back to the colours it had before its last load (an animation,
	moveq	#0,d5			; A B A: frozen)
.rb:	btst	d5,d4
	beq	.rbn
	lea	st_ccol,a0
	lea	st_rowprev,a1
	move.w	d5,d0
	lsl.w	#5,d0
	add.w	d0,a0
	add.w	d0,a1
	moveq	#16-1,d3
.pv:	cmpm.w	(a0)+,(a1)+
	bne	.pvn
	dbf	d3,.pv
	bsr	st_rowbright		; (its colours before: an animation - the brighter of the two sets kept)
	bls	.rbn
	bra	.ld
.pvn:	lea	st_ccol,a0
	lea	st_pcol,a1
	move.w	d5,d0
	lsl.w	#5,d0
	add.w	d0,a0
	add.w	d0,a1
	moveq	#0,d2
	moveq	#16-1,d3
.cnt:	cmpm.w	(a0)+,(a1)+
	beq	.cn1
	addq.w	#1,d2
.cn1:	dbf	d3,.cnt
	cmp.w	#ST_ROWLOAD,d2
	blo	.rbn
.ld:	lea	st_pcol,a0		; (its committed colours kept as the ones before)
	lea	st_rowprev,a1
	move.w	d5,d0
	lsl.w	#5,d0
	add.w	d0,a0
	add.w	d0,a1
	moveq	#16/2-1,d3
.kp:	move.l	(a0)+,(a1)+
	dbf	d3,.kp
	move.w	d5,d7
	lsl.w	#4,d7
	moveq	#16-1,d6
.cm:	bsr	st_commit
	addq.w	#1,d7
	dbf	d6,.cm
.rbn:	addq.w	#1,d5
	cmp.w	#32,d5
	blo	.rb
.pc:	lea	st_pend,a6		; C: the pending pens (kept in place: a5)
	move.l	a6,a5
.pl:	cmp.l	st_pendp,a6
	beq	.pdone
	move.w	(a6)+,d7
	move.w	d7,d0
	add.w	d0,d0
	lea	st_ccol,a0
	move.w	(a0,d0.w),d1
	lea	st_pcol,a0
	cmp.w	(a0,d0.w),d1
	beq	.pdrop			; (committed, or back to its colour)
	bsr	st_isres
	beq	.pcom			; (a reserved pen: at once)
	lea	st_bright,a0		; (a brighter colour at once: an animation rests on its brightest - the
	move.b	(a0,d1.w),d2		; power-up crystal's blue; the user, 2026-10-30)
	lea	st_pcol,a1
	move.w	(a1,d0.w),d3
	cmp.w	#$FFFF,d3
	beq	.pcom
	cmp.b	(a0,d3.w),d2
	bhi	.pcom
	lea	st_pchg,a0
	tst.b	(a0,d7.w)
	beq	.pst
	clr.b	(a0,d7.w)
	lea	st_pstab,a0
	clr.b	(a0,d7.w)
	bra	.pkeep
.pst:	lea	st_pstab,a0
	addq.b	#1,(a0,d7.w)
	cmp.b	#ST_STABLE,(a0,d7.w)
	blo	.pkeep
.pcom:	bsr	st_commit
.pdrop:	lea	st_pendf,a0
	clr.b	(a0,d7.w)
	lea	st_pchg,a0
	clr.b	(a0,d7.w)
	bra	.pl
.pkeep:	move.w	d7,(a5)+
	bra	.pl
.pdone:	move.l	a5,st_pendp
	lea	st_pidx,a2		; (for the reserved pens below)
.pend:	tst.b	st_tilechg		; the scene: the best match of the tile palette (st_scene)
	beq	.nosc
	sf	st_tilechg
	bsr	st_scene
	tst.w	d0
	beq	.nosc
	lea	st_pcol,a1		; (another scene: every pen again with its tables, everything composed again)
	lea	st_ccol,a3
	lea	st_plist,a6
	move.l	a6,a0
	moveq	#0,d7
.al:	move.w	#$FFFF,(a1)+
	move.w	#$FFFF,(a3)+
	move.w	d7,(a0)+
	addq.w	#1,d7
	cmp.w	#512,d7
	blo	.al
	move.l	a0,st_plend
	clr.l	st_rowtch
	lea	st_rowprev,a0		; (no colours before: the new scene's committed at once)
	move.w	#512/2-1,d1
	moveq	#-1,d0
.rq:	move.l	d0,(a0)+
	dbf	d1,.rq
	st	st_allnew
	bra	.pens0
.nosc:	; the reserved pens: their own indices
	move.l	st_scn,a0
	lea	SC_RES(a0),a0
	move.w	(a0)+,d0
	beq	.rr
	moveq	#16,d1
	sub.w	d0,d1
	subq.w	#1,d0
.r:	move.w	(a0)+,d2
	cmp.b	(a2,d2.w),d1
	beq	.r1
	move.b	d1,(a2,d2.w)
	move.w	d2,d3
	lsr.w	#4,d3
	move.l	st_rowchg,d4
	bset	d3,d4
	move.l	d4,st_rowchg
.r1:	addq.w	#1,d1
	dbf	d0,.r
.rr:	move.l	st_hrowchg,d4		; the status bar's changed rows: its tables, its version
	beq	.hr
	clr.l	st_hrowchg
	addq.b	#1,st_hver
	moveq	#0,d5
.hrow:	btst	d5,d4
	beq	.hn
	movem.l	d4-d5,-(sp)
	lea	st_hidx,a0
	move.w	d5,d0
	lsl.w	#4,d0
	add.w	d0,a0
	moveq	#0,d0
	move.w	d5,d0
	moveq	#10,d1
	lsl.l	d1,d0
	lea	st_htt,a1
	add.l	d0,a1
	lea	st_httf,a2
	add.l	d0,a2
	bsr	st_tiletables
	movem.l	(sp)+,d4-d5
.hn:	addq.w	#1,d5
	cmp.w	#16,d5
	blo	.hrow
.hr:	; the changed rows: tables, versions
	move.l	st_rowchg,d4
	beq	.pal
	moveq	#0,d5
.row:	btst	d5,d4
	beq	.rn
	lea	st_ver,a0
	addq.b	#1,(a0,d5.w)
	addq.l	#1,st_nrows
	bsr	st_rowtables
	cmp.w	#16,d5
	blo	.rn
	bsr	st_rowcells		; (a tile row: its cells again)
.rn:	addq.w	#1,d5
	cmp.w	#32,d5
	blo	.row
.pal:	; the STE palettes: the stage's, the reserved indices their pens' current colours
	move.l	st_scn,a0
	lea	SC_PAL(a0),a0
	lea	st_stepal,a1
	lea	st_hstepal,a2
	moveq	#16-1,d0
.c:	move.w	32(a0),(a2)+
	move.w	(a0)+,(a1)+
	dbf	d0,.c
	move.l	st_scn,a0
	lea	SC_RES(a0),a0
	move.w	(a0)+,d0
	beq	.x
	moveq	#16,d1
	sub.w	d0,d1
	add.w	d1,d1
	lea	st_stepal,a1
	add.w	d1,a1
	lea	st_pcol,a3
	lea	st_ste12,a4
	subq.w	#1,d0
.rc:	move.w	(a0)+,d2
	add.w	d2,d2
	move.w	(a3,d2.w),d2		; its 12-bit colour
	add.w	d2,d2
	move.w	(a4,d2.w),(a1)+		; (the STE's bit order)
	dbf	d0,.rc
.x:	rts

; st_commit: d7 = a pen: its current colour (st_ccol) committed (st_pcol), its indices from the scene's tables
st_commit:
	movem.l	d0-d4/a0-a3,-(sp)
	move.w	d7,d0
	add.w	d0,d0
	lea	st_ccol,a0
	move.w	(a0,d0.w),d1
	lea	st_pcol,a0
	cmp.w	(a0,d0.w),d1
	beq	.x
	move.w	d1,(a0,d0.w)
	cmp.w	#256,d7
	blo	.pt
	st	st_tilechg		; (a tile pen's colour: the scene looked at)
.pt:	cmp.w	#$FFFF,d1
	beq	.x			; (not read yet)
	move.l	st_scn,a3
	lea	SC_CTAB(a3),a3
	moveq	#0,d2
	move.b	(a3,d1.w),d2		; the playfield's index
	lea	st_pidx,a2
	cmp.b	(a2,d7.w),d2
	beq	.hud
	move.b	d2,(a2,d7.w)
	move.w	d7,d3
	lsr.w	#4,d3
	move.l	st_rowchg,d4
	bset	d3,d4
	move.l	d4,st_rowchg
.hud:	cmp.w	#256,d7
	blo	.x
	move.l	st_scn,a0
	lea	SC_HTAB(a0),a0
	move.b	(a0,d1.w),d2
	lea	st_hidx-256,a0
	cmp.b	(a0,d7.w),d2
	beq	.x
	move.b	d2,(a0,d7.w)
	move.w	d7,d3			; (the status bar's tables of this tile row again)
	lsr.w	#4,d3
	sub.w	#16,d3
	move.l	st_hrowchg,d4
	bset	d3,d4
	move.l	d4,st_hrowchg
.x:	movem.l	(sp)+,d0-d4/a0-a3
	rts

; st_rowbright: d5 = a row: the flags hi when its current colours (st_ccol) are brighter in sum than its committed
; ones (st_pcol)
st_rowbright:
	movem.l	d0-d4/a0-a2,-(sp)
	lea	st_ccol,a0
	lea	st_pcol,a1
	move.w	d5,d0
	lsl.w	#5,d0
	add.w	d0,a0
	add.w	d0,a1
	lea	st_bright,a2
	moveq	#0,d1			; (the current colours' sum)
	moveq	#0,d2			; (the committed ones')
	moveq	#0,d4
	moveq	#16-1,d3
.l:	move.w	(a0)+,d0
	cmp.w	#$FFFF,d0
	beq	.c
	move.b	(a2,d0.w),d4
	add.w	d4,d1
.c:	move.w	(a1)+,d0
	cmp.w	#$FFFF,d0
	beq	.n
	move.b	(a2,d0.w),d4
	add.w	d4,d2
.n:	dbf	d3,.l
	cmp.w	d2,d1
	movem.l	(sp)+,d0-d4/a0-a2
	rts

; st_isres: d7 = a pen: Z set when it is one of the scene's reserved pens
st_isres:
	movem.l	d0/a0,-(sp)
	move.l	st_scn,a0
	lea	SC_RES(a0),a0
	move.w	(a0)+,d0
	subq.w	#1,d0
	bmi	.no
.l:	cmp.w	(a0)+,d7
	beq	.yes
	dbf	d0,.l
.no:	movem.l	(sp)+,d0/a0
	andi	#$FB,ccr
	rts
.yes:	movem.l	(sp)+,d0/a0
	ori	#4,ccr
	rts

; st_scene: the scene whose reference tile palette has the most pens equal to the current colours (the first of
; equals; tools/stage_assets.py choose_scene): d0 = 1 when it becomes the scene (st_scn) - the first time, or when it
; matches SCENE_MATCH pens - else 0
st_scene:
	addq.l	#1,st_nscene
	movem.l	d1-d7/a0-a3,-(sp)
	lea	st_scenes,a0
	move.w	(a0)+,d7		; the scenes
	moveq	#-1,d6			; the best's count
	moveq	#0,d5			; the best
	moveq	#0,d4
.s:	lea	st_pcol+512,a1		; (the tile pens' colours)
	move.l	a0,a3			; (the scene's reference)
	moveq	#0,d3
	move.w	#256-1,d2
.c:	cmpm.w	(a1)+,(a3)+
	bne	.n
	addq.w	#1,d3
.n:	dbf	d2,.c
	cmp.w	d6,d3
	ble	.nb
	move.w	d3,d6
	move.w	d4,d5
.nb:	add.l	#SC_SIZE,a0
	addq.w	#1,d4
	cmp.w	d7,d4
	blo	.s
	moveq	#0,d0
	cmp.w	st_curscn,d5
	beq	.x
	tst.w	st_curscn
	bmi.s	.sw			; (the first)
	cmp.w	#SCENE_MATCH,d6
	blo	.x
.sw:	addq.l	#1,st_switches
	move.w	d5,st_curscn
	mulu	#SC_SIZE,d5
	lea	st_scenes+2,a0
	add.l	d5,a0
	move.l	a0,st_scn
	moveq	#1,d0
.x:	movem.l	(sp)+,d1-d7/a0-a3
	rts

; st_rowtables: d5 = a colour row (0-15 sprites, 16-31 tiles): its tables from st_pidx (pen 0: index 0 - transparent
; for the tiles over the empty BG, masked for the sprites).  Tiles: st_tt (a byte of 2 pens -> each plane's 2 bits at
; the bottom of its byte of a long: movep order), st_ttf (the pens in the other order: flip x).  Sprites: st_ta (planes
; 0 / 1: 2 bits at the bottom of each word of a long), st_tb (planes 2 / 3).
st_rowtables:
	movem.l	d0-d1/a0-a4,-(sp)
	lea	st_pidx,a0
	move.w	d5,d0
	lsl.w	#4,d0
	add.w	d0,a0			; the row's 16 indices
	moveq	#15,d0
	and.w	d5,d0
	moveq	#10,d1
	lsl.l	d1,d0			; (1 KB a table)
	cmp.w	#16,d5
	bhs.s	.tile
	lea	st_ta,a1		; the sprites: planes 0 / 1, planes 2 / 3
	add.l	d0,a1
	lea	st_sal,a3
	lea	st_sar,a4
	bsr	st_mktab
	lea	st_tb,a1
	add.l	d0,a1
	lea	st_sbl,a3
	lea	st_sbr,a4
	bsr	st_mktab
	movem.l	(sp)+,d0-d1/a0-a4
	rts
.tile:	lea	st_tt,a1
	add.l	d0,a1
	lea	st_ttf,a2
	add.l	d0,a2
	bsr	st_tiletables
	movem.l	(sp)+,d0-d1/a0-a4
	rts

; st_tiletables: a0 = a colour row's 16 indices: a1 its tile table, a2 its flipped one (see st_rowtables)
st_tiletables:
	movem.l	a1/a3-a4,-(sp)
	lea	st_tl,a3
	lea	st_tr,a4
	bsr	st_mktab
	move.l	a2,a1			; (flipped: the left pixel's bits from the right pixel's table)
	lea	st_tr,a3
	lea	st_tl,a4
	bsr	st_mktab
	movem.l	(sp)+,a1/a3-a4
	rts

; st_mktab: a0 = 16 indices (pen 0: 0), a3 / a4 = the left / right pixel's bits of each index (16 longs): a1 = 256
; longs, entry b = a3[index of b >> 4] | a4[index of b & 15]
st_mktab:
	movem.l	d0-d2/d6/a0-a2,-(sp)
	lea	st_mkr,a2		; (the right pixel's bits by pen)
	moveq	#0,d1
	moveq	#16-1,d2
.r:	moveq	#0,d0
	tst.w	d1
	beq.s	.r1			; (pen 0)
	move.b	(a0,d1.w),d0
.r1:	add.w	d0,d0
	add.w	d0,d0
	move.l	(a4,d0.w),(a2)+
	addq.w	#1,d1
	dbf	d2,.r
	moveq	#0,d1
	moveq	#16-1,d2
.l:	moveq	#0,d0
	tst.w	d1
	beq.s	.l1
	move.b	(a0,d1.w),d0
.l1:	add.w	d0,d0
	add.w	d0,d0
	move.l	(a3,d0.w),d0		; the left pixel's bits
	lea	st_mkr,a2
	rept	16
	move.l	d0,d6
	or.l	(a2)+,d6
	move.l	d6,(a1)+
	endr
	addq.w	#1,d1
	dbf	d2,.l
	movem.l	(sp)+,d0-d2/d6/a0-a2
	rts

; st_rowcells: d5 = a tile colour row (16-31): the FG cells of that colour in the columns it was composed into
; (st_colused) and the picture's map rows (the clean buffer holds no others) composed again, those columns looked at
; again
st_rowcells:
	movem.l	d0-d7/a0-a3,-(sp)
	moveq	#15,d3
	and.w	d5,d3
	lea	st_colused,a3
	move.w	d3,d0
	lsl.w	#6,d0
	add.w	d0,a3			; the colour's column flags
	lea	st_cells,a1
	lea	st_colok,a2
	moveq	#0,d6			; the column
.col:	tst.b	(a3,d6.w)
	beq	.cn
	clr.b	(a3,d6.w)
	move.w	st_sy,d4
	lsr.w	#3,d4			; the picture's first map row (33 of them)
	moveq	#33-1,d7
.r:	and.w	#63,d4
	move.w	d4,d0
	lsl.w	#6,d0
	add.w	d6,d0			; the cell
	move.w	d0,d1
	lsl.w	#2,d1
	lea	v30_image+$D0002,a0	; (its attribute word)
	moveq	#15,d2
	and.w	(a0,d1.w),d2
	cmp.w	d3,d2
	bne.s	.n
	clr.b	(a1,d0.w)
	clr.b	(a2,d6.w)
.n:	addq.w	#1,d4
	dbf	d7,.r
.cn:	addq.w	#1,d6
	cmp.w	#64,d6
	blo	.col
	movem.l	(sp)+,d0-d7/a0-a3
	rts


; ======================================================================================================================
; Video RAM: the rows the game wrote (v30_vmarks $80-$BF FG, $100-$13F BG): the FG cells whose entries changed are
; invalid (composed again when in the window); the status bar's rows dirty.  BG: not drawn yet (st_bgcells counts the
; BG cells that are not empty - what the model draws and this renderer does not).
; ======================================================================================================================
st_vram:
	lea	v30_vmarks+$80,a4
	moveq	#0,d6			; the row
.r:	tst.b	(a4,d6.w)
	beq	.n
	clr.b	(a4,d6.w)
	move.w	d6,d0
	lsl.w	#8,d0			; (256 bytes a row)
	lea	v30_image+$D0000,a0
	add.w	d0,a0
	lea	st_fgcopy,a1
	add.w	d0,a1
	lea	st_cells,a2
	move.w	d6,d1
	lsl.w	#6,d1
	add.w	d1,a2			; the row's 64 cell flags
	lea	st_colok,a3
	moveq	#0,d2			; the column
.c:	cmpm.l	(a0)+,(a1)+
	beq.s	.cs
	move.l	-4(a0),-4(a1)
	clr.b	(a2)			; (composed again: its column looked at again)
	clr.b	(a3,d2.w)
	move.w	d6,d0			; (a cell of the status bar: st_bardraw draws it)
	sub.w	st_barpos,d0
	and.w	#63,d0
	cmp.w	#2,d0
	bhs.s	.cs
	mulu	#40,d0
	move.w	d2,d1
	sub.w	st_barpos+2,d1
	and.w	#63,d1
	cmp.w	#40,d1
	bhs.s	.cs
	add.w	d1,d0
	lea	st_bardc,a1
	st	(a1,d0.w)
	lea	st_fgcopy,a1		; (a1 again: the copy's next long)
	move.w	d6,d0
	lsl.w	#8,d0
	add.w	d0,a1
	move.w	d2,d0
	addq.w	#1,d0
	lsl.w	#2,d0
	add.w	d0,a1
	st	st_bardirty
.cs:	addq.l	#1,a2
	addq.w	#1,d2
	cmp.w	#64,d2
	blo.s	.c
.n:	addq.w	#1,d6
	cmp.w	#64,d6
	blo	.r
	lea	v30_vmarks+$100,a4	; BG: the marks consumed
	moveq	#64/4-1,d0
.bg:	clr.l	(a4)+
	dbf	d0,.bg
	rts

; ======================================================================================================================
; The bands: the playfield's scroll (before the raster interrupt when it splits the picture), the status bar (a band
; from line 240), display off
; ======================================================================================================================
st_bands:
	move.w	m72_raster,d0
	sub.w	#128,d0
	lea	m72_scroll,a0
	move.w	#256,st_hbot
	cmp.w	#255,d0
	bhs.s	.one
	lea	m72_scroll_vbl,a0
	cmp.w	#ST_HUDY-1,d0
	bne.s	.one
	move.w	#ST_HUDY,st_hbot	; (the status bar: from line 240 with the scroll after the interrupt)
	move.w	m72_scroll,st_bary
	move.w	m72_scroll+2,st_barx
.one:	move.w	2(a0),d0		; FG x
	add.w	#96,d0
	move.l	st_scn,a1
	moveq	#0,d1
	move.b	SC_FLAGS(a1),d1
	move.w	d1,st_tdx		; (the scene's tile shift: the window moves by it)
	add.w	d1,d0
	and.w	#511,d0
	move.w	d0,st_W
	move.w	(a0),d0			; FG y
	add.w	#128,d0
	and.w	#511,d0
	cmp.w	st_sy,d0
	beq.s	.y
	move.w	d0,st_sy
	st	st_allnew
.y:	move.w	m72_port02,d0
	lsr.w	#3,d0
	and.b	#1,d0
	move.b	d0,st_off
	tst.b	st_allnew
	beq.s	.x
	sf	st_allnew
	lea	st_cells,a0		; everything composed again
	move.w	#4096/4-1,d0
.c:	clr.l	(a0)+
	dbf	d0,.c
	lea	st_colok,a0
	moveq	#64/4-1,d0
.k:	clr.l	(a0)+
	dbf	d0,.k
.x:	rts

; ======================================================================================================================
; Composition into the clean buffer: the window's map columns (W >> 3 .. (W + 319) >> 3) whose flag is not set: their
; rows (the picture's lines 0-255: map rows from sy >> 3, 33 of them) that are not composed
; ======================================================================================================================
st_compose:
	move.w	st_loghead,st_logstart
	move.w	st_W,d6
	lsr.w	#3,d6			; the first column
	moveq	#41-1,d7
.col:	and.w	#63,d6
	lea	st_colok,a0
	tst.b	(a0,d6.w)
	bne.s	.cn
	st	(a0,d6.w)
	bsr	st_column
.cn:	addq.w	#1,d6
	dbf	d7,.col
	rts

; st_column: d6 = a map column: its cells in the picture's rows composed where not done
st_column:
	movem.l	d6-d7,-(sp)
	move.w	st_sy,d5
	lsr.w	#3,d5			; the first map row
	moveq	#33-1,d7
.row:	and.w	#63,d5
	move.w	d5,d0
	lsl.w	#6,d0
	add.w	d6,d0
	lea	st_cells,a0
	tst.b	(a0,d0.w)
	bne.s	.rn
	st	(a0,d0.w)
	bsr	st_cell
.rn:	addq.w	#1,d5
	dbf	d7,.row
	movem.l	(sp)+,d6-d7
	rts

; st_cell: d5 = the map row, d6 = the column: the FG tile into the clean buffer at both copies of the column, logged
st_cell:
	movem.l	d5-d7,-(sp)
	move.w	d5,d0
	lsl.w	#3,d0
	sub.w	st_sy,d0		; the cell's first picture line (-7 .. 255: into the guard lines when partly out)
	and.w	#511,d0
	cmp.w	#512-8,d0
	blo.s	.l
	sub.w	#512,d0
.l:	move.w	d0,d4			; (the line)
	add.w	#ST_G,d0
	mulu	#ST_LB,d0
	moveq	#0,d1
	move.w	d6,d1
	lsr.w	#1,d1
	lsl.w	#3,d1			; the group's byte
	add.l	d1,d0
	moveq	#1,d1
	and.w	d6,d1
	add.l	d1,d0			; (the right half: the odd byte)
	move.l	d0,d7			; the offset in a buffer
	move.l	st_bufs+4*ST_NBUF,a1
	add.l	d0,a1			; (the clean buffer)
	; the tile: its entry, its conversion (cached)
	move.w	d5,d0
	lsl.w	#6,d0
	add.w	d6,d0
	lsl.w	#2,d0
	lea	v30_image+$D0000,a0
	move.w	(a0,d0.w),d1		; code: tile, flip x (14), flip y (15)
	move.w	2(a0,d0.w),d2		; attribute: colour 0-3
	and.w	#15,d2
	lea	st_colused,a0		; (the columns each colour is composed into: st_rowcells)
	move.w	d2,d0
	lsl.w	#6,d0
	add.w	d6,d0
	st	(a0,d0.w)
	bsr	st_tile			; -> a0: 8 longs (movep order)
	moveq	#8-1,d0
.w:	move.l	(a0)+,d1
	movep.l	d1,0(a1)
	movep.l	d1,256(a1)		; (the copy 512 pixels on)
	lea	ST_LB(a1),a1
	dbf	d0,.w
	; the log: the cell (one byte of each plane, 8 lines) at both copies
	move.l	d7,d0
	bsr	st_logcell
	move.l	d7,d0
	add.l	#256,d0
	bsr	st_logcell
	movem.l	(sp)+,d5-d7
	rts

; st_logcell: d0 = the cell's offset: a log entry (offset, the byte's masks), merged with the entry before when it is
; the cell above at the same offset
st_logcell:
	move.w	st_loghead,d1
	lea	st_log,a0
	move.w	d1,d2
	subq.w	#1,d2
	and.w	#ST_LOG-1,d2
	lsl.w	#3,d2
	move.l	(a0,d2.w),d3		; the entry before: offset, lines
	moveq	#0,d4
	move.w	4(a0,d2.w),d4
	mulu	#ST_LB,d4
	add.l	d4,d3
	cmp.l	d3,d0
	bne.s	.new
	cmp.w	st_logstart,d1		; (only an entry of this picture: no display buffer has copied it yet)
	beq.s	.new
	addq.w	#8,4(a0,d2.w)		; (8 lines more)
	rts
.new:	move.w	d1,d2
	lsl.w	#3,d2
	move.l	d0,(a0,d2.w)
	move.w	#8,4(a0,d2.w)
	move.w	#$FF00,d3
	btst	#0,d0
	beq.s	.m
	move.w	#$00FF,d3
.m:	move.w	d3,6(a0,d2.w)
	addq.w	#1,d1
	and.w	#ST_LOG-1,d1
	move.w	d1,st_loghead
	addq.l	#1,st_logn
	rts

; st_tile: d1 = the code word, d2 = the colour row (0-15): a0 = its 8 rows converted (longs for movep), cached
st_tile:
	lea	st_ver+16,a0
	moveq	#0,d3
	move.b	(a0,d2.w),d3
	ror.l	#8,d3			; the key: version << 24 | colour << 16 | code, + 1 (0: an empty slot)
	moveq	#0,d0
	move.w	d2,d0
	swap	d0
	move.w	d1,d0
	or.l	d3,d0
	addq.l	#1,d0
	moveq	#0,d3
	move.w	d1,d3
	eor.w	d2,d3
	and.w	#ST_TCN-1,d3		; the slot
	lsl.l	#2,d3
	lea	st_tckey,a0
	cmp.l	(a0,d3.l),d0
	beq	.hit
	move.l	d0,(a0,d3.l)
	lsl.l	#3,d3			; (32 bytes a slot)
	lea	st_tcdata,a0
	add.l	d3,a0
	movem.l	d1-d7/a1-a3,-(sp)
	move.l	a0,a3
	moveq	#0,d0
	move.w	d1,d0
	and.w	#$0FFF,d0		; (4096 tiles)
	lsl.l	#5,d0
	lea	st_tiles,a1
	add.l	d0,a1			; the tile's pens: 8 rows of 4 bytes
	moveq	#10,d0
	lsl.l	d0,d2
	lea	st_tt,a2
	btst	#14,d1
	beq.s	.nfx
	lea	st_ttf,a2
.nfx:	add.l	d2,a2			; the row's table
	moveq	#4,d4			; the next row
	btst	#15,d1
	beq.s	.nfy
	lea	28(a1),a1
	moveq	#-4,d4
.nfy:	moveq	#8-1,d5
	btst	#14,d1
	bne	.fx
.row:	moveq	#0,d0
	moveq	#0,d6
	rept	4
	move.b	(a1)+,d6
	lsl.l	#2,d0
	lsl.w	#2,d6
	or.l	(a2,d6.w),d0
	lsr.w	#2,d6
	endr
	move.l	d0,(a3)+
	lea	-4(a1,d4.w),a1
	dbf	d5,.row
	bra.s	.done
.fx:	moveq	#0,d0
	moveq	#0,d6
	addq.l	#4,a1			; (the row's end: its bytes backwards)
	rept	4
	move.b	-(a1),d6
	lsl.l	#2,d0
	lsl.w	#2,d6
	or.l	(a2,d6.w),d0
	lsr.w	#2,d6
	endr
	move.l	d0,(a3)+
	add.w	d4,a1
	dbf	d5,.fx
.done:	lea	-32(a3),a0
	movem.l	(sp)+,d1-d7/a1-a3
	rts
.hit:	lsl.l	#3,d3
	lea	st_tcdata,a0
	add.l	d3,a0
	rts

; ======================================================================================================================
; st_sync: the display buffer brought up to the clean buffer: the logged compositions since its last picture (or, too
; many, the whole buffer), the rectangles of its last sprites
; ======================================================================================================================
st_sync:
	move.w	st_draw,d0
	add.w	d0,d0
	lea	st_logread,a0
	add.w	d0,a0
	move.l	st_bufs+4*ST_NBUF,a5	; (the clean buffer)
	move.l	st_dbuf,a6
	lea	st_full,a1
	tst.b	(a1,d0.w)
	bne	.full
	move.l	st_logn,d1		; (entries since: more than the log keeps -> the whole buffer)
	lea	st_logcnt,a2
	add.w	d0,a2
	add.w	d0,a2
	move.l	d1,d2
	sub.l	(a2),d2
	cmp.l	#ST_LOG-2,d2
	bhi	.full
	move.l	d1,(a2)
	move.w	st_loghead,d7
	move.w	(a0),d6
	move.w	d7,(a0)
	lea	st_log,a3
.l:	cmp.w	d6,d7
	beq.s	.lx
	move.w	d6,d2
	lsl.w	#3,d2
	move.l	(a3,d2.w),d0		; offset
	lea	(a5,d0.l),a0
	lea	(a6,d0.l),a1
	moveq	#4,d0			; (the 4 planes' words of the group)
	move.w	4(a3,d2.w),d1		; lines
	move.w	6(a3,d2.w),d2		; the byte's mask
	move.w	d2,d3
	move.w	d2,d4
	bsr	st_copy
	addq.w	#1,d6
	and.w	#ST_LOG-1,d6
	bra.s	.l
.lx:	; the last sprites' rectangles
	move.w	st_draw,d0
	add.w	d0,d0
	lea	st_dmgn,a0
	move.w	(a0,d0.w),d7
	clr.w	(a0,d0.w)
	lea	st_dmg,a2
	mulu	#ST_DMG*8/2,d0
	add.l	d0,a2
	subq.w	#1,d7
	bmi.s	.dx
.d:	move.l	(a2)+,d0
	lea	(a5,d0.l),a0
	lea	(a6,d0.l),a1
	moveq	#0,d0
	move.b	(a2)+,d0		; words a line
	moveq	#0,d1
	move.b	(a2)+,d1		; lines
	addq.l	#2,a2
	moveq	#-1,d2
	moveq	#-1,d3
	moveq	#-1,d4
	bsr	st_copy
	dbf	d7,.d
.dx:	rts
.full:	; (the whole buffer from the clean one)
	clr.b	(a1,d0.w)
	move.w	st_loghead,(a0)
	lea	st_logcnt,a2
	add.w	d0,a2
	add.w	d0,a2
	move.l	st_logn,(a2)
	lea	st_dmgn,a0
	clr.w	(a0,d0.w)
	moveq	#ST_LB/64-1,d7		; (column strips of 32 words: short passes)
.fs:	move.l	a5,a0
	move.l	a6,a1
	moveq	#32,d0
	move.w	#ST_LINES,d1
	moveq	#-1,d2
	moveq	#-1,d3
	moveq	#-1,d4
	bsr	st_copy
	lea	64(a5),a5
	lea	64(a6),a6
	dbf	d7,.fs
	rts

; st_copy: a0 source, a1 destination (the same layout: ST_LB a line), d0 words a line, d1 lines, d2 / d4 / d3 END1 /
; END2 / END3: a HOG copy in passes of at most 32 words (AGENTS.md: short passes)
st_copy:
	movem.l	d0-d5,-(sp)
	move.w	#2,BLT_SXI.w
	move.w	#2,BLT_DXI.w
	move.w	d0,d5
	subq.w	#1,d5
	add.w	d5,d5
	neg.w	d5
	add.w	#ST_LB,d5
	move.w	d5,BLT_SYI.w
	move.w	d5,BLT_DYI.w
	move.w	d2,BLT_END1.w
	move.w	d4,BLT_END2.w
	move.w	d3,BLT_END3.w
	move.w	#$0203,BLT_HOP.w
	clr.b	BLT_SKEW.w
	move.l	a0,BLT_SRC.w
	move.l	a1,BLT_DST.w
	move.w	d0,BLT_XC.w
	moveq	#1,d5			; the lines a pass: 32 words (or a line)
	cmp.w	#32,d0
	bhi.s	.p
	move.b	st_lpp(pc,d0.w),d5
.p:	move.w	d5,d2
	cmp.w	d1,d2
	bls.s	.go
	move.w	d1,d2
.go:	move.w	d2,BLT_YC.w
	ifnd	ST_NOCOPY
	move.b	#$C0,BLT_CTRL.w
	endc
	sub.w	d2,d1
	bne.s	.p
	movem.l	(sp)+,d0-d5
	rts

st_lpp:		; (32 / words, the lines of a short pass)
w	set	0
	rept	33
	if	w=0
	dc.b	1
	else
	dc.b	32/w
	endc
w	set	w+1
	endr
	even

; ======================================================================================================================
; Sprites: the object records from the last to the first
; ======================================================================================================================
st_sprites:
	move.w	#$0203,BLT_HOP.w
	clr.w	BLT_SXI.w
	move.w	#2,BLT_SYI.w
	move.w	#8,BLT_DXI.w
	move.w	#$FFFF,BLT_END2.w
	move.w	st_draw,d0
	add.w	d0,d0
	lea	st_dmgn,a0
	add.w	d0,a0
	move.l	a0,st_dmgnp
	mulu	#ST_DMG*8/2,d0
	lea	st_dmg,a0
	add.l	d0,a0
	move.l	a0,st_dmgp
	lea	m72_objs,a6		; the fixed slots ($3F8 .. $3C0: last in the list, so under the others), then the list
	move.w	#$3F8,d7		; (from its end down to $C0)
.f:	move.w	(a6,d7.w),d0
	beq.s	.fn
	movem.l	d7/a6,-(sp)
	lea	(a6,d7.w),a0
	bsr	st_object
	movem.l	(sp)+,d7/a6
.fn:	subq.w	#8,d7
	cmp.w	#$3C0,d7
	bhs.s	.f
	move.w	m72_objs_end,d7
	cmp.w	#$3C0,d7
	bls.s	.e
	move.w	#$3C0,d7
.e:	subq.w	#8,d7			; the last slot
	cmp.w	#$C0,d7
	blt	.x
.o:	move.w	(a6,d7.w),d0		; the definition
	beq	.on
	movem.l	d7/a6,-(sp)
	lea	(a6,d7.w),a0
	bsr	st_object
	movem.l	(sp)+,d7/a6
.on:	subq.w	#8,d7
	cmp.w	#$C0,d7
	bge.s	.o
.x:	rts

; st_object: a0 = the record (BW, entries, colour, x, y)
st_object:
	moveq	#0,d0
	move.w	(a0),d0
	lsr.w	#1,d0
	lsl.l	#2,d0
	lea	st_deftab,a1
	move.l	(a1,d0.l),d1
	beq	.unknown
	cmp.l	#1,d1
	beq	.out			; (a star, an empty one)
	move.l	d1,a2			; the whole sprite: OX, OY, H, NS, strips
	moveq	#15,d2
	and.b	3(a0),d2		; the colour row
	; the top line: 384 - y + OY; the left buffer x: W + (x - 256 + OX) - 96
	move.w	#384,d4
	sub.w	6(a0),d4
	add.w	2(a2),d4
	move.w	d4,d0
	add.w	4(a2),d0
	ble	.out			; (above the picture)
	cmp.w	#ST_PL,d4
	bge	.out			; (below)
	cmp.w	#-ST_G,d4
	blt	.out			; (beyond the guard lines: never visible)
	move.w	4(a0),d1		; x
	move.l	st_scn,a1
	btst	#0,SC_FLAGS+1(a1)
	beq.s	.nsq
	move.w	d1,d0			; (squeezed: x moves by -(x - 320 - 192) / 10, the user's title logo at 320 pixels)
	sub.w	#320+192,d0
	ext.l	d0
	divs	#10,d0
	sub.w	d0,d1
.nsq:	move.w	st_W,d3			; (relative to the window: a scene's tile shift leaves the sprites in place)
	add.w	d1,d3
	add.w	(a2),d3
	sub.w	#256+96,d3		; the composite's buffer x
	; its colouring (the cache)
	movem.l	d2-d4/a2,-(sp)
	bsr	st_bake			; -> a3: the strips' plane words' addresses
	movem.l	(sp)+,d2-d4/a2
	; the strips
	move.w	d4,d0
	add.w	#ST_G,d0
	mulu	#ST_LB,d0
	move.l	st_dbuf,a4
	add.l	d0,a4			; the top line in the buffer
	move.w	6(a2),d6		; NS
	lea	8(a2),a5		; strip: x, shape, rows, pens.l
	subq.w	#1,d6
	move.w	#$7FFF,st_omin		; (the drawn strips' buffer x: the object's erase rectangle)
	move.w	#-$8000,st_omax
.s:	move.w	d3,d5
	add.w	(a5),d5			; the strip's buffer x
	move.w	st_W,d0
	sub.w	#16,d0
	cmp.w	d0,d5
	ble.s	.sn			; (wholly left of the window)
	add.w	#320+16,d0
	cmp.w	d0,d5
	bge.s	.sn			; (right)
	cmp.w	st_omin,d5
	bge.s	.mi
	move.w	d5,st_omin
.mi:	cmp.w	st_omax,d5
	ble.s	.ma
	move.w	d5,st_omax
.ma:	movem.l	d3/d6/a2-a5,-(sp)
	bsr	st_strip
	movem.l	(sp)+,d3/d6/a2-a5
.sn:	addq.l	#4,a3
	lea	10(a5),a5
	dbf	d6,.s
	; the erase rectangle: the drawn strips' groups (a strip at x covers x >> 4 .. (x + 15) >> 4), H lines
	move.w	st_omax,d1
	cmp.w	st_omin,d1
	blt.s	.out
	move.l	st_dmgnp,a1
	cmp.w	#ST_DMG,(a1)
	bhs.s	.full
	addq.w	#1,(a1)
	add.w	#15,d1
	asr.w	#4,d1			; the last group
	move.w	st_omin,d0
	asr.w	#4,d0			; the first
	sub.w	d0,d1
	addq.w	#1,d1
	lsl.w	#2,d1			; words a line
	lsl.w	#3,d0
	ext.l	d0
	move.l	a4,d2
	sub.l	st_dbuf,d2
	add.l	d2,d0			; the offset
	move.l	st_dmgp,a1
	move.l	d0,(a1)+
	move.b	d1,(a1)+
	move.b	5(a2),(a1)+		; (H: lines)
	clr.w	(a1)+
	move.l	a1,st_dmgp
.out:	rts
.full:	move.w	st_draw,d1		; (too many: the whole buffer again next time)
	lea	st_full,a1
	st	(a1,d1.w)
	rts
.unknown:
	addq.l	#1,st_unknown
	rts

; st_strip: d5 = its buffer x, a4 = the buffer's line of the composite's top, (a3) = its plane words, a5 = its entry
; (x, shape, rows, pens): the shape's code for the shift; its damage listed
st_strip:
	move.l	(a3),BLT_SRC.w		; the strip's plane words
	move.w	2(a5),d6		; the shape
	lsl.w	#2,d6
	moveq	#15,d3
	and.w	d5,d3
	mulu	#12,d3			; its variant for the shift (code, stream, damage offset, damage size)
	move.w	d5,d1
	asr.w	#4,d1
	lsl.w	#3,d1
	ext.l	d1
	add.l	a4,d1			; the strip's destination (row 0, its first word)
	moveq	#0,d0			; (the code per shape and pass-type pattern steps the destination's low word: a strip
	move.w	d1,d0			; that would cross a 64 KB boundary takes the long-destination code)
	move.w	4(a2),d2		; (the composite's rows)
	mulu	#ST_LB,d2
	add.l	d2,d0
	add.l	#16,d0
	cmp.l	#$10000,d0
	bhi.s	.long
	lea	st_shapes_n,a0
	move.l	(a0,d6.w),a0
	add.w	d3,a0
	move.l	d1,BLT_DST.w		; (the high word; the code writes the low word)
	move.w	d1,d0
	move.l	(a0)+,-(sp)		; the code
	move.l	(a0),a0			; its stream
	lea	BLT_END1.w,a1
	lea	BLT_END3.w,a6
	lea	BLT_DYI.w,a3
	lea	BLT_DST+2.w,a4
	lea	BLT_YC.w,a5
	moveq	#4,d1
	moveq	#-$40,d2
	move.w	#ST_LB,d4
	lea	BLT_CTRL.w,a2
	rts				; (into the code: it returns to st_strip's caller)
.long:	addq.l	#1,st_nlong
	lea	st_shapes,a0
	move.l	(a0,d6.w),a0
	add.w	d3,a0
	move.l	d1,a3			; (the destination)
	move.l	(a0)+,-(sp)
	move.l	(a0),a0
	lea	BLT_END1.w,a1
	lea	BLT_END3.w,a6
	lea	BLT_DST.w,a4
	lea	BLT_YC.w,a5
	moveq	#4,d1
	moveq	#-$40,d2
	move.w	#ST_LB,d4
	lea	BLT_CTRL.w,a2
	rts

; st_bake: d2 = the colour row, a2 = the whole sprite's record: a3 = the address of its strips' plane-word addresses
; for this colour (cached: the key is the record, the colour and the row's version)
st_bake:
	lea	st_ver,a0
	moveq	#0,d0
	move.b	(a0,d2.w),d0
	lsl.w	#4,d0
	or.w	d2,d0			; version << 4 | colour
	move.l	a2,d1
	lsr.l	#3,d1
	eor.w	d0,d1
	and.w	#ST_HASH-1,d1
	mulu	#10,d1
	lea	st_hash,a0
	add.l	d1,a0			; the slot: record.l, key.w, data.l
	cmp.l	(a0),a2
	bne.s	.miss
	cmp.w	4(a0),d0
	bne.s	.miss
	move.l	6(a0),a3
	rts
.miss:	addq.l	#1,st_nbake
	move.l	a2,(a0)
	move.w	d0,4(a0)
	move.w	6(a2),d5		; NS
	move.l	st_poolp,a3		; (the pool: the addresses, then the plane words)
	move.w	d5,d1
	lsl.w	#2,d1
	lea	(a3,d1.w),a1
	moveq	#0,d1			; (the room: every strip's rows x 8)
	lea	8(a2),a4
	move.w	d5,d3
	subq.w	#1,d3
.sz:	moveq	#0,d4
	move.w	4(a4),d4
	lsl.l	#3,d4
	add.l	d4,d1
	lea	10(a4),a4
	dbf	d3,.sz
	add.l	a1,d1
	cmp.l	#st_pool+ST_POOL,d1
	blo.s	.room
	addq.l	#1,st_npool
	movem.l	d0/a0,-(sp)		; (full: everything coloured again)
	lea	st_hash,a1
	move.w	#ST_HASH*10/4-1,d1
.clr:	clr.l	(a1)+
	dbf	d1,.clr
	movem.l	(sp)+,d0/a0
	move.l	a2,(a0)
	move.w	d0,4(a0)
	lea	st_pool,a3
	move.w	d5,d1
	lsl.w	#2,d1
	lea	(a3,d1.w),a1
.room:	move.l	a3,6(a0)
	movem.l	d2/d5-d7/a2/a3,-(sp)
	moveq	#10,d0
	lsl.l	d0,d2
	lea	st_ta,a5
	add.l	d2,a5			; the row's tables
	lea	st_tb,a6
	add.l	d2,a6
	lea	8(a2),a4
	subq.w	#1,d5
.strip:	move.l	a1,(a3)+		; the strip's plane words
	move.l	6(a4),a0		; its pens
	move.w	4(a4),d7		; its rows
	subq.w	#1,d7
	bmi	.sx
.row:	moveq	#0,d0
	moveq	#0,d1
	moveq	#0,d6
	rept	8
	move.b	(a0)+,d6
	lsl.l	#2,d0
	lsl.l	#2,d1
	lsl.w	#2,d6
	or.l	(a5,d6.w),d0
	or.l	(a6,d6.w),d1
	lsr.w	#2,d6
	endr
	move.l	d0,(a1)+
	move.l	d1,(a1)+
	dbf	d7,.row
.sx:	lea	10(a4),a4
	dbf	d5,.strip
	move.l	a1,st_poolp
	movem.l	(sp)+,d2/d5-d7/a2/a3
	rts

; ======================================================================================================================
; The status bar: its FG cells (2 rows from the bar band's map row, 40 columns from its x) into the bar's image when
; their entries or colours changed
; ======================================================================================================================
st_bardraw:
	cmp.w	#ST_HUDY,st_hbot
	bne	.x
	move.w	st_bary,d0
	add.w	#ST_HUDY+128,d0
	lsr.w	#3,d0
	move.w	st_barx,d1
	add.w	#96,d1
	lsr.w	#3,d1
	cmp.w	st_barpos,d0
	bne.s	.mv
	cmp.w	st_barpos+2,d1
	bne.s	.mv
	move.b	st_hver,d2
	cmp.b	st_barhv,d2
	bne.s	.mv
	tst.b	st_bardirty
	beq	.x			; (nothing of the bar changed)
	sf	st_bardirty		; only the cells the game changed (st_vram: st_bardc)
	lea	st_bardc,a4
	moveq	#0,d5
.dr:	moveq	#0,d6
.dc:	tst.b	(a4)
	beq.s	.dn
	clr.b	(a4)
	movem.l	d5-d6/a4,-(sp)
	bsr	st_barcell
	movem.l	(sp)+,d5-d6/a4
.dn:	addq.l	#1,a4
	addq.w	#1,d6
	cmp.w	#40,d6
	blo.s	.dc
	addq.w	#1,d5
	cmp.w	#2,d5
	blo.s	.dr
	rts
.mv:	sf	st_bardirty
	addq.l	#1,st_nbarfull
	lea	st_bardc,a4		; (everything checked)
	moveq	#80/4-1,d2
.cl:	clr.l	(a4)+
	dbf	d2,.cl
	move.b	st_hver,st_barhv
	move.w	d0,st_barpos
	move.w	d1,st_barpos+2
	lea	st_barkey,a4
	moveq	#0,d5			; the bar's row
.r:	moveq	#0,d6			; its column
.c:	move.w	st_barpos,d0
	add.w	d5,d0
	and.w	#63,d0
	lsl.w	#6,d0
	move.w	st_barpos+2,d1
	add.w	d6,d1
	and.w	#63,d1
	add.w	d1,d0
	lsl.w	#2,d0
	lea	v30_image+$D0000,a0
	move.w	(a0,d0.w),d1		; the code
	moveq	#15,d2
	and.w	2(a0,d0.w),d2		; the colour
	move.w	d1,d3			; the key: code << 16 | colour << 8 | the bar's version
	swap	d3
	move.w	d2,d3
	lsl.w	#8,d3
	move.b	st_hver,d3
	cmp.l	(a4),d3
	beq.s	.cn
	move.l	d3,(a4)
	bsr	st_bartile
	move.l	st_bar,a1
	move.w	d5,d0
	mulu	#8*ST_BARLB,d0
	add.w	d0,a1
	move.w	d6,d0
	lsr.w	#1,d0
	lsl.w	#3,d0
	add.w	d0,a1
	moveq	#1,d0
	and.w	d6,d0
	add.w	d0,a1
	moveq	#8-1,d0
.w:	move.l	(a0)+,d1
	movep.l	d1,0(a1)
	lea	ST_BARLB(a1),a1
	dbf	d0,.w
.cn:	addq.l	#4,a4
	addq.w	#1,d6
	cmp.w	#40,d6
	blo	.c
	addq.w	#1,d5
	cmp.w	#2,d5
	blo	.r
.x:	rts

; st_barcell: d5 = the bar's row (0-1), d6 = its column: the cell drawn, its key set
st_barcell:
	addq.l	#1,st_nbarcells
	move.w	st_barpos,d0
	add.w	d5,d0
	and.w	#63,d0
	lsl.w	#6,d0
	move.w	st_barpos+2,d1
	add.w	d6,d1
	and.w	#63,d1
	add.w	d1,d0
	lsl.w	#2,d0
	lea	v30_image+$D0000,a0
	move.w	(a0,d0.w),d1		; the code
	moveq	#15,d2
	and.w	2(a0,d0.w),d2		; the colour
	move.w	d1,d3
	swap	d3
	move.w	d2,d3
	lsl.w	#8,d3
	move.b	st_hver,d3
	move.w	d5,d0
	mulu	#40,d0
	add.w	d6,d0
	lsl.w	#2,d0
	lea	st_barkey,a4
	move.l	d3,(a4,d0.w)
	bsr	st_bartile
	move.l	st_bar,a1
	move.w	d5,d0
	mulu	#8*ST_BARLB,d0
	add.w	d0,a1
	move.w	d6,d0
	lsr.w	#1,d0
	lsl.w	#3,d0
	add.w	d0,a1
	moveq	#1,d0
	and.w	d6,d0
	add.w	d0,a1
	moveq	#8-1,d0
.w:	move.l	(a0)+,d1
	movep.l	d1,0(a1)
	lea	ST_BARLB(a1),a1
	dbf	d0,.w
	rts

; st_bartile: d1 = the code word, d2 = the colour row: a0 = 8 longs (movep order) in the status bar's indices
; (st_htt / st_httf: the status bar's tables)
st_bartile:
	movem.l	d1-d7/a1-a3,-(sp)
	lea	st_bartmp,a3
	moveq	#0,d0
	move.w	d1,d0
	and.w	#$0FFF,d0
	lsl.l	#5,d0
	lea	st_tiles,a1
	add.l	d0,a1
	moveq	#10,d0
	lsl.l	d0,d2
	lea	st_htt,a2
	btst	#14,d1
	beq.s	.nfx
	lea	st_httf,a2
.nfx:	add.l	d2,a2
	moveq	#4,d4
	btst	#15,d1
	beq.s	.nfy
	lea	28(a1),a1
	moveq	#-4,d4
.nfy:	moveq	#8-1,d5
	moveq	#0,d6
	btst	#14,d1
	bne.s	.fx
.row:	moveq	#0,d0
	rept	4
	move.b	(a1)+,d6
	lsl.l	#2,d0
	lsl.w	#2,d6
	or.l	(a2,d6.w),d0
	lsr.w	#2,d6
	endr
	move.l	d0,(a3)+
	lea	-4(a1,d4.w),a1
	dbf	d5,.row
	bra.s	.done
.fx:	moveq	#0,d0
	addq.l	#4,a1
	rept	4
	move.b	-(a1),d6
	lsl.l	#2,d0
	lsl.w	#2,d6
	or.l	(a2,d6.w),d0
	lsr.w	#2,d6
	endr
	move.l	d0,(a3)+
	add.w	d4,a1
	dbf	d5,.fx
.done:	lea	-32(a3),a0
	movem.l	(sp)+,d1-d7/a1-a3
	rts

; ======================================================================================================================
	section data,data
	even
st_scenes:	incbin	"stage_scenes.bin"	; (tools/stage_assets.py scenes)
SC_REF		= 0			; a scene: 256 words its reference tile colours
SC_PAL		= 512			; 16 + 16 words the playfield's and the status bar's STE colours
SC_HPAL		= 544
SC_CTAB		= 576			; 4096 bytes the playfield's index of each 12-bit colour
SC_HTAB		= 576+4096		; the status bar's
SC_RES		= 576+8192		; a word R, 2 words the reserved pens (indices 16 - R .. 15)
SC_FLAGS	= SC_RES+6		; a word: bit 0 the sprites squeezed toward the centre (st_object), bits 8-15
					; the tiles' shift (the window over the tiles moves, the sprites keep their places)
SC_SIZE		= SC_RES+8
SCENE_MATCH	= 192
ST_ROWLOAD	= 8			; pens of a row off their committed colours: the row was loaded (committed at once)
ST_STABLE	= 50			; pictures a single pen's new colour must stay before it is committed
st_tiles:	incbin	"stage_tiles.bin"
; the pixel bits of each index for the colour tables (st_mktab): tiles (a long of 4 plane bytes, plane 0 the high
; byte: the left pixel bit 1, the right bit 0 of each), sprites (st_ta: planes 0 / 1 in the words' bits 1 / 0, st_tb:
; planes 2 / 3)
st_tl:
i	set	0
	rept	16
	dc.l	((i&1)<<25)|(((i>>1)&1)<<17)|(((i>>2)&1)<<9)|(((i>>3)&1)<<1)
i	set	i+1
	endr
st_tr:
i	set	0
	rept	16
	dc.l	((i&1)<<24)|(((i>>1)&1)<<16)|(((i>>2)&1)<<8)|((i>>3)&1)
i	set	i+1
	endr
st_sal:
i	set	0
	rept	16
	dc.l	((i&1)<<17)|(((i>>1)&1)<<1)
i	set	i+1
	endr
st_sar:
i	set	0
	rept	16
	dc.l	((i&1)<<16)|((i>>1)&1)
i	set	i+1
	endr
st_sbl:
i	set	0
	rept	16
	dc.l	(((i>>2)&1)<<17)|(((i>>3)&1)<<1)
i	set	i+1
	endr
st_sbr:
i	set	0
	rept	16
	dc.l	(((i>>2)&1)<<16)|((i>>3)&1)
i	set	i+1
	endr
st_q4:		; 5-bit channel -> 4 bits (round(pal5bit(v) / 17))
v	set	0
	rept	32
	dc.b	((((v<<3)|(v>>2))*2+17)/34)
v	set	v+1
	endr
	even
st_bright:	; 12-bit colour -> r + g + b (4 bits each): the brighter colour of an animation
c	set	0
	rept	4096
	dc.b	((c>>8)&15)+((c>>4)&15)+(c&15)
c	set	c+1
	endr
	even
st_ste12:	; 12-bit colour -> the STE's palette word (4 bits a channel, bit 3 the lowest)
c	set	0
	rept	4096
	dc.w	((((c>>8)&15)>>1)|((((c>>8)&15)&1)<<3))<<8|((((c>>4)&15)>>1)|((((c>>4)&15)&1)<<3))<<4|(((c&15)>>1)|(((c&15)&1)<<3))
c	set	c+1
	endr
	include	"stage_sprites.s"
	section data,data
	even
st_sstream:	incbin	"stage_sstream.bin"
	even
st_nstream:	incbin	"stage_nstream.bin"

	section bss,bss
	even
m72r_pictures:	ds.l	1
m72r_skipped:	ds.l	1
m72r_lates:	ds.l	1
st_unknown:	ds.l	1
st_switches:	ds.l	1		; (scene switches)
st_npens:	ds.l	1		; (pens looked up)
st_nscene:	ds.l	1		; (scene checks)
st_nrows:	ds.l	1		; (colour rows' tables made)
st_nbarfull:	ds.l	1		; (status bar: whole checks, cells drawn)
st_nbarcells:	ds.l	1
st_nbake:	ds.l	1		; (sprite colourings, pool resets)
st_npool:	ds.l	1
st_nlong:	ds.l	1		; (strips drawn with the long-destination code: 64 KB crossings)
st_logn:	ds.l	1
m72r_shown:	ds.w	1
m72r_prev:	ds.w	1
m72r_ready:	ds.b	1
st_off:		ds.b	1
st_allnew:	ds.b	1
st_bardirty:	ds.b	1
st_hver:	ds.b	1
st_tilechg:	ds.b	1
st_barhv:	ds.b	1
	even
st_draw:	ds.w	1
st_dbuf:	ds.l	1
st_W:		ds.w	1
st_sy:		ds.w	1
st_hbot:	ds.w	1
st_barx:	ds.w	1
st_bary:	ds.w	1
st_barpos:	ds.l	1
st_rowchg:	ds.l	1
st_scn:		ds.l	1		; the scene (st_scenes + 2 + n * SC_SIZE)
st_curscn:	ds.w	1
st_loghead:	ds.w	1
st_logstart:	ds.w	1
st_dmgnp:	ds.l	1
st_dmgp:	ds.l	1
st_omin:	ds.w	1
st_tdx:		ds.w	1
st_omax:	ds.w	1
st_poolp:	ds.l	1
st_bufs:	ds.l	ST_NBUF+1
st_bar:		ds.l	1
m72r_disp_addr:	ds.l	ST_NBUF
m72r_disp_bar:	ds.l	ST_NBUF
m72r_disp_hud:	ds.l	ST_NBUF
m72r_disp_fine:	ds.b	ST_NBUF
	even
m72r_disp_pal:	ds.w	16*ST_NBUF
m72r_disp_hpal:	ds.w	16*ST_NBUF
m72r_vbl_pal:	ds.w	16
m72r_vbl_hpal:	ds.w	16
m72r_vbl_htop:	ds.w	1
m72r_vbl_hbot:	ds.w	1
st_stepal:	ds.w	16
st_hstepal:	ds.w	16
st_logread:	ds.w	ST_NBUF
st_logcnt:	ds.l	ST_NBUF
st_full:	ds.b	ST_NBUF
	even
st_dmgn:	ds.w	ST_NBUF
st_dmg:		ds.b	ST_NBUF*ST_DMG*8
st_log:		ds.b	ST_LOG*8
st_pcol:	ds.w	512		; the pens' 12-bit colours
st_palraw:	ds.b	2*$C00		; (the palettes as last read: st_palette compares the marked blocks)
st_plist:	ds.w	512		; (the pens whose words changed)
st_plend:	ds.l	1
st_pflag:	ds.b	512
st_ccol:	ds.w	512		; (the pens' current colours; st_pcol: the committed ones)
st_pchg:	ds.b	512		; (changed this picture)
st_pendf:	ds.b	512		; (pending: current != committed)
st_pstab:	ds.b	512		; (pictures its colour stayed)
st_pend:	ds.w	512
st_pendp:	ds.l	1
st_rowtch:	ds.l	1
st_rowprev:	ds.w	512		; (each row's committed colours before its last load)
st_pidx:	ds.b	512		; their playfield indices
st_hidx:	ds.b	256		; the tile pens' status bar indices
st_ver:		ds.b	32		; the colour rows' versions (sprites 0-15, tiles 16-31)
st_cells:	ds.b	4096		; the map cells composed in the clean buffer
st_colok:	ds.b	64		; (a column's window rows all composed)
st_colused:	ds.b	16*64		; (per tile colour the columns it was composed into)
st_fgcopy:	ds.b	$4000
st_bartmp:	ds.l	8
st_mkr:		ds.l	16
st_barkey:	ds.l	80		; (the bar's cells as drawn: code << 16 | colour << 8 | st_hver)
st_bardc:	ds.b	80		; (the bar's cells the game changed)
st_hrowchg:	ds.l	1
st_htt:		ds.l	256*16
st_httf:	ds.l	256*16
st_ta:		ds.l	256*16
st_tb:		ds.l	256*16
st_tt:		ds.l	256*16
st_ttf:		ds.l	256*16
st_tckey:	ds.l	ST_TCN
st_tcdata:	ds.b	ST_TCN*32
st_hash:	ds.b	ST_HASH*10
st_deftab:	ds.l	32768
st_pool:	ds.b	ST_POOL
st_mem:		ds.b	(ST_NBUF+1)*ST_BUFSZ+ST_BARLB*16+256
