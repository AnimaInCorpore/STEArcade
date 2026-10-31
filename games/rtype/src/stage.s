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
; The BG scroll mode (the user, 2026-10-31: stage 3's warship; a scene with flag bit 2 while the BG map holds a tile
; that is not empty, st_bgon): the buffers' lines from ST_LINES (zero until then: an empty BG cell that was never
; drawn needs no work, st_bz) hold the BG map at its own scroll - column c at x 8c and 8c + 512, row r at line
; ST_LINES + ST_G + 8r and, r < 32, also 512 lines below (the window wraps) -, the window at BG x + 96 and line BG y
; + 128 (st_dorg: the picture's line -ST_G).  In such a scene the FG image is kept in both modes (the switch makes
; nothing again).  The FG is drawn over it each picture like sprites
; (st_fgdraw: stefastbobs2's copy passes from the FG image st_fgimg, the opaque pixels st_fgmsk as end masks), its
; rectangles erased with the sprites'.
;
; Colours: a pen's index is the stage's colour table at its current colour (st_pidx; a palette row's pens again when
; the game writes the row), the reserved pens their own indices (their STE colour each picture: the pen's colour).

ST_LB		= 512
ST_G		= 64
ST_PL		= 256
ST_LINES	= ST_G+ST_PL+ST_G
ST_LINESB	= ST_G+512+ST_PL+ST_G	; (the BG scroll mode: the BG map's 512 lines, its first 256 again below)
ST_BUFSZ	= (ST_LINES+ST_LINESB)*ST_LB	; (the BG scroll mode's lines below the FG mode's: they start empty)
ST_RUN		= 7			; (the FG pieces: full chunks a pass at most - 32 words)
	ifnd	ST_NBUF
ST_NBUF		= 3
	endc
ST_DMG		= 600			; erase rectangles a buffer (more: the whole buffer copied)
ST_LOG		= 2048			; clean-buffer changes kept (a power of 2)
ST_POOL		= 1024*1024		; the sprite colour cache
ST_HASH		= 65536			; (14 MB development system: room for the pre-coloured sprites)
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
	move.l	d0,d2
	lsl.l	#2,d0
	move.l	d1,(a1,d0.l)
	lsl.l	#4,d2			; (st_dt2: the record, no colouring yet, the 64 KB test's H * ST_LB + 64)
	lea	st_dt2,a2
	add.l	d2,a2
	move.l	d1,(a2)
	move.w	#$FFFF,8(a2)
	cmp.l	#1,d1
	beq.s	.d
	move.l	d1,a3
	move.w	4(a3),d2
	mulu	#ST_LB,d2
	add.w	#64,d2
	move.w	d2,10(a2)
	bra.s	.d
.dd:	move.l	#$FFFFFFFF,d0
	lea	st_rtgt,a0		; (no row's target known: every row read at the first picture)
	moveq	#32/2-1,d1
.rt:	move.l	d0,(a0)+
	dbf	d1,.rt
	lea	st_barkey,a0		; (no bar cell drawn yet)
	moveq	#80-1,d1
.bk:	move.l	d0,(a0)+
	dbf	d1,.bk
	st	st_allnew
	move.w	#-1,st_sy
	move.w	#-1,m72r_prev
	lea	st_bz,a0		; (the BG scroll mode's region: every cell empty, zero)
	move.w	#4096/4-1,d1
.bz:	move.l	d0,(a0)+
	dbf	d1,.bz
	move.w	#-1,st_fk0		; (the FG rows' pieces: none made)
	bsr	st_preins
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
	move.l	st_dbuf,d0		; the picture's origin: the BG scroll mode's window line
	move.w	#ST_LINES,st_flines
	move.l	st_scn,a0
	btst	#2,SC_FLAGS+1(a0)
	beq.s	.fl
	move.w	#ST_LINES+ST_LINESB,st_flines	; (a BG scroll scene: whole copies take both regions)
.fl:	tst.b	st_bgon
	beq.s	.org
	moveq	#0,d1
	move.w	st_by,d1
	add.w	#ST_LINES,d1
	moveq	#9,d2
	lsl.l	d2,d1			; (* ST_LB)
	add.l	d1,d0
.org:	move.l	d0,st_dorg
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
	add.l	st_dorg,d2
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
; st_palette (the user, 2026-10-30: as if the game were written for the STE): a palette row's colours are always its
; record's target's colour table in ROM (work RAM $42D34: 12 bytes a row, sprite rows 0-15, tile rows 16-31; the target
; in word 0's low byte; the game fades and sets its rows to them, FADE_SNAP at once).  A row whose target changed takes
; the scene's 16 indices of that target (tools/stage_assets.py scenes: pre-mapped, no colours at run time), the status
; bar's for a tile row; a changed tile row looks for the scene (st_scene).  Rows whose indices changed: their tables
; again and a new version (their sprite colourings, tile conversions made again), a tile row's cells composed again.
st_palette:
	clr.l	st_rowchg		; (rows whose indices changed: bits 0-31)
	clr.l	st_hrowchg
	lea	v30_image+$42D34,a0	; the records (words native)
	lea	st_rtgt,a1		; the targets the rows show
	moveq	#0,d5			; the row
	moveq	#0,d6			; (rows whose target changed)
.t:	moveq	#0,d0
	move.b	1(a0),d0		; (word 0's low byte)
	cmp.w	(a1),d0
	beq.s	.tn
	move.w	d0,(a1)
	bset	d5,d6
.tn:	lea	12(a0),a0
	addq.l	#2,a1
	addq.w	#1,d5
	cmp.w	#32,d5
	blo.s	.t
	tst.l	d6
	beq	.pal
	move.l	d6,d0			; (a tile row: the scene looked at)
	clr.w	d0
	tst.l	d0
	beq.s	.ns
	bsr	st_scene
	tst.w	d0
	beq.s	.ns
	moveq	#-1,d6			; (another scene: every row again, everything composed again)
	st	st_allnew
.ns:	moveq	#0,d5
.r:	btst	d5,d6
	beq	.rn
	move.l	st_scn,a2
	move.w	d5,d0
	add.w	d0,d0
	lea	st_rtgt,a1
	move.w	(a1,d0.w),d0		; the target
	lsl.w	#4,d0
	lea	SC_SPR(a2),a0
	cmp.w	#16,d5
	blo.s	.k
	lea	SC_TILE(a2),a0
.k:	add.w	d0,a0			; its 16 indices
	lea	st_pidx,a1
	move.w	d5,d1
	lsl.w	#4,d1
	add.w	d1,a1
	moveq	#16-1,d2
	moveq	#0,d3			; (any changed)
.c:	move.b	(a0)+,d4
	cmp.b	(a1),d4
	beq.s	.c1
	move.b	d4,(a1)
	moveq	#1,d3
.c1:	addq.l	#1,a1
	dbf	d2,.c
	tst.w	d3
	beq.s	.h
	move.l	st_rowchg,d4
	bset	d5,d4
	move.l	d4,st_rowchg
.h:	cmp.w	#16,d5			; the status bar's indices of a tile row
	blo.s	.rn
	lea	SC_HUD(a2),a0
	add.w	d0,a0
	lea	st_hidx-256,a1
	add.w	d1,a1
	moveq	#16-1,d2
	moveq	#0,d3
.hc:	move.b	(a0)+,d4
	cmp.b	(a1),d4
	beq.s	.hc1
	move.b	d4,(a1)
	moveq	#1,d3
.hc1:	addq.l	#1,a1
	dbf	d2,.hc
	tst.w	d3
	beq.s	.rn
	move.w	d5,d4
	sub.w	#16,d4
	move.l	st_hrowchg,d3
	bset	d4,d3
	move.l	d3,st_hrowchg
.rn:	addq.w	#1,d5
	cmp.w	#32,d5
	blo	.r
	move.l	st_hrowchg,d4		; the status bar's changed rows: its tables, its version
	beq.s	.hr
	addq.b	#1,st_hver
	moveq	#0,d5
.hrow:	btst	d5,d4
	beq.s	.hn
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
	blo.s	.hrow
.hr:	move.l	st_rowchg,d4		; the changed rows: tables, versions, a tile row's cells
	beq.s	.pal
	moveq	#0,d5
.row:	btst	d5,d4
	beq.s	.rw
	lea	st_ver,a0
	addq.b	#1,(a0,d5.w)
	addq.l	#1,st_nrows
	bsr	st_rowtables
	cmp.w	#16,d5
	bhs.s	.tl
	move.w	st_curscn,d0		; a sprite row: its colouring's id (tools/stage_sprites.py st_cidtab: the scene's
	lsl.w	#8,d0			; target -> the id of its 16 indices; the sprites' cache key)
	lea	st_rtgt,a0
	move.w	d5,d1
	add.w	d1,d1
	add.w	(a0,d1.w),d0
	add.l	d0,d0
	lea	st_cidtab,a0
	move.w	(a0,d0.l),d0
	lea	st_rcid,a0
	move.w	d0,(a0,d1.w)
	bra.s	.rw
.tl:	bsr	st_rowcells
.rw:	addq.w	#1,d5
	cmp.w	#32,d5
	blo.s	.row
.pal:	move.l	st_scn,a0		; the STE palettes: the scene's
	lea	SC_PAL(a0),a0
	lea	st_stepal,a1
	lea	st_hstepal,a2
	moveq	#16-1,d0
.p:	move.w	32(a0),(a2)+
	move.w	(a0)+,(a1)+
	dbf	d0,.p
	rts

; st_scene: the scene whose reference has the most tile-row targets equal to the rows' (st_rtgt 16-31; the first of
; equals; tools/stage_assets.py choose_scene): d0 = 1 when it becomes the scene (st_scn) - the first time, or when it
; matches SCENE_MATCH rows - else 0
st_scene:
	addq.l	#1,st_nscene
	movem.l	d1-d7/a0-a3,-(sp)
	lea	st_scenes,a0
	move.w	(a0)+,d7		; the scenes
	moveq	#-1,d6			; the best's count
	moveq	#0,d5			; the best
	moveq	#0,d4
.s:	lea	st_rtgt+32,a1		; (the tile rows' targets: words)
	move.l	a0,a3			; (the scene's reference: bytes)
	moveq	#0,d3
	moveq	#16-1,d2
.c:	moveq	#0,d0
	move.b	(a3)+,d0
	cmp.w	(a1)+,d0
	bne.s	.n
	addq.w	#1,d3
.n:	dbf	d2,.c
	cmp.w	d6,d3
	ble.s	.nb
	move.w	d3,d6
	move.w	d4,d5
.nb:	add.l	#SC_SIZE,a0
	addq.w	#1,d4
	cmp.w	d7,d4
	blo.s	.s
	moveq	#0,d0
	cmp.w	st_curscn,d5
	beq.s	.x
	tst.w	st_curscn
	bmi.s	.sw			; (the first)
	cmp.w	#SCENE_MATCH,d6
	blo.s	.x
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
	movem.l	d0/a0,-(sp)		; (the FG image again: its cells, the rows' pieces)
	lea	st_fgcells,a0
	move.w	#4096/4-1,d0
.fc:	clr.l	(a0)+
	dbf	d0,.fc
	lea	st_fgcolok,a0
	moveq	#64/4-1,d0
.fk:	clr.l	(a0)+
	dbf	d0,.fk
	move.w	#-1,st_fk0
	movem.l	(sp)+,d0/a0
	tst.b	st_bgon
	beq.s	.fg
	st	st_allnew		; (the BG scroll mode: everything composed again)
	rts
.fg:	movem.l	d0-d7/a0-a3,-(sp)
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
	lea	st_fgcells,a5
	add.w	d1,a5
	lea	st_fgcolok,a6
	moveq	#64-1,d3		; (the cells left: the column = 63 - d3)
.c:	cmpm.l	(a0)+,(a1)+		; (the unchanged cells: 30 cycles each)
	dbne	d3,.c
	beq.s	.n			; (the row's end, the last cell equal)
	move.l	-4(a0),-4(a1)
	moveq	#63,d2			; the column
	sub.w	d3,d2
	clr.b	(a2,d2.w)		; (composed again: its column looked at again)
	clr.b	(a3,d2.w)
	clr.b	(a5,d2.w)		; (the FG image's cell too)
	clr.b	(a6,d2.w)
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
	move.l	a1,-(sp)
	lea	st_bardc,a1
	st	(a1,d0.w)
	move.l	(sp)+,a1
	st	st_bardirty
.cs:	dbf	d3,.c
.n:	addq.w	#1,d6
	cmp.w	#64,d6
	blo	.r
	lea	v30_vmarks+$100,a4	; BG: the cells that are not empty counted (st_bgn), a changed one composed again in
	lea	st_bgstar,a5		; the BG scroll mode
	moveq	#0,d6
.br:	tst.b	(a4,d6.w)
	beq	.bn
	clr.b	(a4,d6.w)
	move.w	d6,d0
	lsl.w	#8,d0
	lea	v30_image+$D8000,a0
	add.w	d0,a0
	lea	st_bgcopy,a1
	add.w	d0,a1
	lea	st_cells,a2
	move.w	d6,d1
	lsl.w	#6,d1
	add.w	d1,a2
	lea	st_colok,a3
	moveq	#64-1,d3
.bc:	cmpm.l	(a0)+,(a1)+
	dbne	d3,.bc
	beq.s	.bn
	move.w	-4(a1),d0		; (empty before) - (empty now): +1 a cell that is not empty now
	and.w	#$FFF,d0
	moveq	#0,d1
	move.b	(a5,d0.w),d1
	move.w	-4(a0),d0
	and.w	#$FFF,d0
	sub.b	(a5,d0.w),d1
	ext.w	d1
	add.w	d1,st_bgn
	move.l	-4(a0),-4(a1)
	tst.b	st_bgon
	beq.s	.bs
	moveq	#63,d2
	sub.w	d3,d2
	clr.b	(a2,d2.w)
	clr.b	(a3,d2.w)
.bs:	dbf	d3,.bc
.bn:	addq.w	#1,d6
	cmp.w	#64,d6
	blo	.br
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
	move.w	d0,d1			; (unwrapped: st_fgabs, the BG strip's position)
	sub.w	st_fgprev,d1
	add.w	#256,d1
	and.w	#511,d1
	sub.w	#256,d1
	ext.l	d1
	add.l	d1,st_fgabs
	move.w	d0,st_fgprev
	add.w	#96,d0
	move.l	st_scn,a1
	moveq	#0,d1
	move.b	SC_FLAGS(a1),d1
	move.w	d1,st_tdx		; (the scene's tile shift: the window moves by it)
	add.w	d1,d0
	and.w	#511,d0
	move.w	d0,d4			; (the FG's window)
	move.w	d4,st_wf		; (the FG image's window and rows - both modes: a BG scroll scene keeps the image;
	move.w	(a0),d0			; its columns looked at again when the first row changes)
	add.w	#128,d0
	and.w	#511,d0
	move.w	st_fy,d1
	move.w	d0,st_fy
	eor.w	d0,d1
	and.w	#$1F8,d1
	beq.s	.f1
	lea	st_fgcolok,a2
	moveq	#64/4-1,d1
.fk:	clr.l	(a2)+
	dbf	d1,.fk
.f1:	move.w	m72_port02,d0
	lsr.w	#3,d0
	and.b	#1,d0
	move.b	d0,st_off
	moveq	#0,d2			; the BG scroll mode: a scene with flag bit 2, the BG map not empty
	btst	#2,SC_FLAGS+1(a1)
	beq.s	.md
	tst.w	st_bgn
	sne	d2
.md:	cmp.b	st_bgon,d2
	beq.s	.ms
	move.b	d2,st_bgon
	st	st_allnew
	move.w	#-1,st_sy
.ms:	tst.b	st_bgon
	bne	.bgm
	move.w	d4,st_W
	move.w	(a0),d0			; FG y
	add.w	#128,d0
	and.w	#511,d0
	cmp.w	st_sy,d0
	beq.s	.y
	move.w	d0,st_sy
	st	st_allnew
.y:	move.l	st_scn,a1		; a BG strip scene (SC_FLAGS bit 1): its origin, the FG column at its first picture
	btst	#1,SC_FLAGS+1(a1)
	beq.s	.ns
	tst.b	st_stripon
	bne.s	.al
	st	st_stripon
	move.l	st_fgabs,d0
	add.l	#96,d0
	asr.l	#3,d0
	move.w	d0,st_origin
	st	st_allnew
	bra.s	.al
.ns:	tst.b	st_stripon
	beq.s	.al
	sf	st_stripon
	st	st_allnew
.al:	tst.b	st_allnew
	beq.s	.x
	sf	st_allnew
	lea	st_cells,a0		; everything composed again (not the FG image: map positions)
	move.w	#4096/4-1,d0
.c:	clr.l	(a0)+
	dbf	d0,.c
	lea	st_colok,a0
	moveq	#64/4-1,d0
.k:	clr.l	(a0)+
	dbf	d0,.k
.x:	rts
.bgm:	move.w	6(a0),d0		; the BG scroll mode: the window over the BG: x, its first line
	add.w	#96,d0
	add.w	st_tdx,d0
	and.w	#511,d0
	move.w	d0,st_W
	move.w	4(a0),d0
	add.w	#128,d0
	and.w	#511,d0
	move.w	st_by,d1
	move.w	d0,st_by
	eor.w	d0,d1
	and.w	#$1F8,d1
	beq	.al
	lea	st_colok,a2
	moveq	#64/4-1,d1
.bk:	clr.l	(a2)+
	dbf	d1,.bk
	bra	.al

; ======================================================================================================================
; Composition into the clean buffer: the window's map columns (W >> 3 .. (W + 319) >> 3) whose flag is not set: their
; rows (the picture's lines 0-255: map rows from sy >> 3, 33 of them) that are not composed
; ======================================================================================================================
st_compose:
	move.w	st_loghead,st_logstart
	tst.b	st_bgon
	bne	st_composeb
	tst.b	st_stripon
	bne	st_composes
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
	move.l	st_scn,a0		; (a BG scroll scene: the FG image kept)
	btst	#2,SC_FLAGS+1(a0)
	bne	st_fgcomp
	rts

; (a BG strip scene: each window column's absolute FG column - its ring column composed again when it is another one)
st_composes:
	move.l	st_fgabs,d0
	add.l	#96,d0
	move.w	st_tdx,d1
	ext.l	d1
	add.l	d1,d0
	asr.l	#3,d0
	move.w	d0,d5			; the first column's absolute column
	moveq	#41-1,d7
.sc:	move.w	d5,d6
	and.w	#63,d6
	lea	st_colabs,a0
	move.w	d6,d1
	add.w	d1,d1
	cmp.w	(a0,d1.w),d5
	beq.s	.same
	move.w	d5,(a0,d1.w)
	lea	st_colok,a0
	clr.b	(a0,d6.w)
	lea	st_cells,a0
	add.w	d6,a0
	moveq	#64-1,d1
.cl:	clr.b	(a0)
	lea	64(a0),a0
	dbf	d1,.cl
.same:	lea	st_colok,a0
	tst.b	(a0,d6.w)
	bne.s	.sn
	st	(a0,d6.w)
	move.w	d5,-(sp)
	bsr	st_column
	move.w	(sp)+,d5
.sn:	addq.w	#1,d5
	dbf	d7,.sc
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
	and.w	#$CFFF,d1		; (bits 12, 13 unused: bit 12 marks a BG strip's tile in st_tile)
	lea	st_colused,a0		; (the columns each colour is composed into: st_rowcells)
	move.w	d2,d0
	lsl.w	#6,d0
	add.w	d6,d0
	st	(a0,d0.w)
	tst.b	st_stripon
	bne.s	.strip
	bsr	st_tile			; -> a0: 8 longs (movep order)
	moveq	#8-1,d0
.w:	move.l	(a0)+,d1
	movep.l	d1,0(a1)
	movep.l	d1,256(a1)		; (the copy 512 pixels on)
	lea	ST_LB(a1),a1
	dbf	d0,.w
	bra	.logs
.strip:	; the FG tile over the BG strip's: each line BG ^ ((BG ^ FG) & the FG's opaque pixels)
	movem.l	a2-a3,-(sp)
	move.w	d1,-(sp)		; (the FG code: its mask)
	bsr	st_tile
	lea	st_cf,a2		; (a copy: the BG's conversion may take the cache slot)
	rept	8
	move.l	(a0)+,(a2)+
	endr
	lea	st_colabs,a2		; the strip's column: (the absolute column - the origin) mod its length
	move.w	d6,d0
	add.w	d0,d0
	move.w	(a2,d0.w),d0
	sub.w	st_origin,d0
	ext.l	d0
	divs	st_strip,d0
	swap	d0
	tst.w	d0
	bpl.s	.sp
	add.w	st_strip,d0
.sp:	and.l	#$FFFF,d0
	lsl.l	#8,d0			; (256 bytes a column)
	moveq	#0,d3
	move.w	d5,d3
	lsl.w	#2,d3
	add.l	d3,d0
	lea	st_strip+2,a2
	add.l	d0,a2
	move.w	(a2),d1			; its code ($FFFF: empty, black)
	cmp.w	#$FFFF,d1
	beq.s	.be
	move.w	2(a2),d2
	and.w	#15,d2
	lea	st_colused,a0		; (its colour's columns too)
	move.w	d2,d0
	lsl.w	#6,d0
	add.w	d6,d0
	st	(a0,d0.w)
	bsr	st_tile
	bra.s	.bc
.be:	lea	st_zero8,a0
.bc:	move.w	(sp)+,d1		; the FG's mask: 8 longs a tile (then the X-flipped ones), rows backwards Y-flipped
	moveq	#0,d0
	move.w	d1,d0
	and.w	#$0FFF,d0
	lsl.l	#5,d0
	lea	st_tmask,a3
	add.l	d0,a3
	btst	#14,d1
	beq.s	.nx
	add.l	#4096*32,a3
.nx:	moveq	#4,d4
	btst	#15,d1
	beq.s	.ny
	lea	28(a3),a3
	moveq	#-4,d4
.ny:	lea	st_cf,a2
	moveq	#8-1,d0
.r:	move.l	(a0)+,d1		; BG
	move.l	(a2)+,d3		; FG
	eor.l	d1,d3
	and.l	(a3),d3
	eor.l	d1,d3
	movep.l	d3,0(a1)
	movep.l	d3,256(a1)
	lea	ST_LB(a1),a1
	add.w	d4,a3
	dbf	d0,.r
	movem.l	(sp)+,a2-a3
.logs:
	; the log: the cell (one byte of each plane, 8 lines) at both copies
	move.l	d7,d0
	bsr	st_logcell
	move.l	d7,d0
	add.l	#256,d0
	bsr	st_logcell
	movem.l	(sp)+,d5-d7
	rts

; ======================================================================================================================
; The BG scroll mode's composition: the BG window's map columns (W >> 3, 41 of them) into the clean buffer at their map
; positions (rows from st_by >> 3, 33 of them), the FG window's (st_wf) into the FG image
; ======================================================================================================================
st_composeb:
	move.w	st_W,d6
	lsr.w	#3,d6
	moveq	#41-1,d7
.col:	and.w	#63,d6
	lea	st_colok,a0
	tst.b	(a0,d6.w)
	bne.s	.cn
	st	(a0,d6.w)
	bsr	st_columnb
.cn:	addq.w	#1,d6
	dbf	d7,.col
; st_fgcomp: the FG image's cells of the window's chunks k0 .. k0 + 21 (both cells of each) where not made
st_fgcomp:
	move.w	st_wf,d6
	lsr.w	#4,d6
	add.w	d6,d6
	moveq	#44-1,d7
.fc:	and.w	#63,d6
	lea	st_fgcolok,a0
	tst.b	(a0,d6.w)
	bne.s	.fn
	st	(a0,d6.w)
	bsr	st_fgcolumn
.fn:	addq.w	#1,d6
	dbf	d7,.fc
	rts

; st_columnb: d6 = a BG map column: its cells in the window's rows composed where not done
st_columnb:
	movem.l	d6-d7,-(sp)
	move.w	st_by,d5
	lsr.w	#3,d5
	moveq	#33-1,d7
.row:	and.w	#63,d5
	move.w	d5,d0
	lsl.w	#6,d0
	add.w	d6,d0
	lea	st_cells,a0
	tst.b	(a0,d0.w)
	bne.s	.rn
	st	(a0,d0.w)
	bsr	st_cellb
.rn:	addq.w	#1,d5
	dbf	d7,.row
	movem.l	(sp)+,d6-d7
	rts

; st_cellb: d5 = a BG map row, d6 = a column: the BG tile (black when empty: st_bgstar) into the clean buffer at line
; ST_G + 8 * row (rows 0-31 also 512 lines below), both copies of the column, logged
st_cellb:
	movem.l	d5-d7,-(sp)
	move.w	d5,d0			; (an empty cell whose place holds zeros already: nothing)
	lsl.w	#6,d0
	add.w	d6,d0
	move.w	d0,d1
	lsl.w	#2,d1
	lea	v30_image+$D8000,a0
	move.w	(a0,d1.w),d1
	and.w	#$FFF,d1
	lea	st_bgstar,a0
	move.b	(a0,d1.w),d1
	lea	st_bz,a0
	add.w	d0,a0
	tst.b	d1
	beq.s	.nz
	tst.b	(a0)
	bne	.x
.nz:	move.b	d1,(a0)			; (zeros after this one: an empty cell)
	move.w	d5,d0
	lsl.w	#3,d0
	add.w	#ST_LINES+ST_G,d0
	mulu	#ST_LB,d0
	moveq	#0,d1
	move.w	d6,d1
	lsr.w	#1,d1
	lsl.w	#3,d1
	add.l	d1,d0
	moveq	#1,d1
	and.w	d6,d1
	add.l	d1,d0
	move.l	d0,d7			; the offset in a buffer
	move.l	st_bufs+4*ST_NBUF,a1
	add.l	d0,a1
	move.w	d5,d0
	lsl.w	#6,d0
	add.w	d6,d0
	lsl.w	#2,d0
	lea	v30_image+$D8000,a0
	move.w	(a0,d0.w),d1		; code
	move.w	2(a0,d0.w),d2		; attribute: the colour
	and.w	#15,d2
	moveq	#0,d0
	move.w	d1,d0
	and.w	#$FFF,d0
	lea	st_bgstar,a0
	tst.b	(a0,d0.w)
	bne.s	.e
	and.w	#$CFFF,d1
	or.w	#$1000,d1		; (bit 12: a BG tile)
	bsr	st_tile			; -> a0
	bra.s	.t
.e:	lea	st_zero8,a0
.t:	move.l	a1,a2
	add.l	#512*ST_LB,a2
	moveq	#8-1,d0
	cmp.w	#32,d5
	bhs.s	.o
.w:	move.l	(a0)+,d1
	movep.l	d1,0(a1)
	movep.l	d1,256(a1)
	movep.l	d1,0(a2)
	movep.l	d1,256(a2)
	lea	ST_LB(a1),a1
	lea	ST_LB(a2),a2
	dbf	d0,.w
	move.l	d7,d0
	add.l	#512*ST_LB,d0
	bsr	st_logcell
	move.l	d7,d0
	add.l	#512*ST_LB+256,d0
	bsr	st_logcell
	bra.s	.l
.o:	move.l	(a0)+,d1
	movep.l	d1,0(a1)
	movep.l	d1,256(a1)
	lea	ST_LB(a1),a1
	dbf	d0,.o
.l:	move.l	d7,d0
	bsr	st_logcell
	move.l	d7,d0
	add.l	#256,d0
	bsr	st_logcell
.x:	movem.l	(sp)+,d5-d7
	rts

; st_fgcolumn: d6 = a FG map column: its cells in the FG window's rows into the FG image where not done
st_fgcolumn:
	movem.l	d6-d7,-(sp)
	move.w	st_fy,d5
	lsr.w	#3,d5
	moveq	#33-1,d7
.row:	and.w	#63,d5
	move.w	d5,d0
	lsl.w	#6,d0
	add.w	d6,d0
	lea	st_fgcells,a0
	tst.b	(a0,d0.w)
	bne.s	.rn
	st	(a0,d0.w)
	bsr	st_fgcell
.rn:	addq.w	#1,d5
	dbf	d7,.row
	movem.l	(sp)+,d6-d7
	rts

; st_fgcell: d5 = a FG map row, d6 = a column: the tile into the FG image (st_fgimg: the FG map's 512 lines of ST_LB
; bytes, the screen's layout, column c at x 8c and 8c + 512), its opaque pixels into st_fgmsk (a byte a line, 128 bytes
; a line: chunk k's mask word at 2k), the row's cells with opaque pixels (st_fgrm: bit c & 7 of byte c >> 3)
st_fgcell:
	movem.l	d5-d7,-(sp)
	move.w	d5,d0
	lsl.w	#6,d0
	add.w	d6,d0
	lsl.w	#2,d0
	lea	v30_image+$D0000,a0
	move.w	(a0,d0.w),d1		; code
	move.w	2(a0,d0.w),d2		; attribute: the colour
	and.w	#15,d2
	and.w	#$CFFF,d1
	move.w	d1,d7
	bsr	st_tile			; -> a0
	moveq	#0,d0
	move.w	d5,d0
	moveq	#12,d3
	lsl.l	d3,d0			; (8 lines of ST_LB a row)
	moveq	#0,d3
	move.w	d6,d3
	lsr.w	#1,d3
	lsl.w	#3,d3
	add.l	d3,d0
	moveq	#1,d3
	and.w	d6,d3
	add.l	d3,d0
	lea	st_fgimg,a1
	add.l	d0,a1
	moveq	#8-1,d0
.i:	move.l	(a0)+,d1
	movep.l	d1,0(a1)
	movep.l	d1,256(a1)
	lea	ST_LB(a1),a1
	dbf	d0,.i
	moveq	#0,d0			; its opaque pixels: 8 longs a tile (the X-flipped ones after), rows backwards Y-flipped
	move.w	d7,d0
	and.w	#$0FFF,d0
	lsl.l	#5,d0
	lea	st_tmask,a3
	add.l	d0,a3
	btst	#14,d7
	beq.s	.nx
	add.l	#4096*32,a3
.nx:	moveq	#4,d4
	btst	#15,d7
	beq.s	.ny
	lea	28(a3),a3
	moveq	#-4,d4
.ny:	moveq	#0,d0
	move.w	d5,d0
	moveq	#10,d3
	lsl.l	d3,d0			; (8 lines of 128 bytes a row)
	moveq	#0,d3
	move.w	d6,d3
	lsr.w	#1,d3
	add.w	d3,d3
	add.l	d3,d0
	moveq	#1,d3
	and.w	d6,d3
	add.l	d3,d0
	lea	st_fgmsk,a2
	add.l	d0,a2
	moveq	#0,d3
	moveq	#8-1,d0
.m:	move.b	(a3),d1
	move.b	d1,(a2)
	move.b	d1,64(a2)
	or.b	d1,d3
	lea	128(a2),a2
	add.w	d4,a3
	dbf	d0,.m
	lea	st_fgrm,a2
	move.w	d5,d0
	lsl.w	#3,d0
	add.w	d0,a2
	move.w	d6,d0
	lsr.w	#3,d0
	add.w	d0,a2
	moveq	#7,d0
	and.w	d6,d0
	btst	d0,(a2)			; (the row's pieces change when the cell has opaque pixels or had)
	sne	d4
	or.b	d3,d4
	bclr	d0,(a2)
	tst.b	d3
	beq.s	.c
	bset	d0,(a2)
.c:	move.b	(a2),d1			; its chunk (cells 2k, 2k + 1): st_fgrc, bit k of the row's long
	moveq	#6,d0
	and.w	d6,d0
	lsr.b	d0,d1
	lea	st_fgrc,a2
	move.w	d5,d0
	lsl.w	#2,d0
	add.w	d0,a2
	move.l	(a2),d3
	move.w	d6,d0
	lsr.w	#1,d0
	bclr	d0,d3
	and.b	#3,d1
	beq.s	.x
	bset	d0,d3
.x:	move.l	d3,(a2)
	tst.b	d4
	beq.s	.nd
	lea	st_fgdirty,a2		; (the row's pieces made again)
	st	(a2,d5.w)
.nd:	movem.l	(sp)+,d5-d7
	rts

; ======================================================================================================================
; st_fgdraw: the BG scroll mode's FG over the display buffer (a0 = the erase rectangles' pointer: -> a0 after this
; picture's FG rectangles).  stefastbobs2's way (AGENTS.md): a FG row's pieces in the window's chunks (st_fgbuild,
; made again when the row's cells or the window's first chunk change) - two partial chunks, one, a run of full chunks
; (ST_RUN at most) of a line -, each a copy pass (HOP 2, OP 3) from the FG image, all four planes in it (X increments
; 8, Y count 4, the Y increments back to the next plane), the end masks the opaque pixels shifted by the skew (the
; FG's offset from the window; NFSR: n chunks cover n + 1 words), grouped by kind (XC, SYI, DYI once a group).  A
; row's rectangle (its chunks drawn, its 8 lines) is erased with the sprites'.
; ======================================================================================================================
ST_FROW		= 2048			; a row's pieces (st_fgpcs): first, last chunk; the two-chunk pieces (count, then
ST_FB		= 4			; offset, mask 1, mask 2), the one-chunk ones (count, offset, mask), the full runs
ST_FC		= ST_FB+2+88*6		; (count, n * 2, offset); an offset: line * ST_LB + (chunk - k0) * 8
ST_FF		= ST_FC+2+176*4

st_fgdraw:
	move.l	a0,st_fgrp
	movem.l	d0-d7/a0-a6,-(sp)
	move.w	st_wf,d0		; the window's chunks k0 .. k0 + 21: the rows' pieces again when k0 changes
	lsr.w	#4,d0
	cmp.w	st_fk0,d0
	beq.s	.k0
	move.w	d0,st_fk0
	lea	st_fgdirty,a0
	moveq	#64/4-1,d1
.dk:	move.l	#$FFFFFFFF,(a0)+
	dbf	d1,.dk
.k0:	move.w	st_W,d0			; chunk k (FG x 16k) -> the destination's group st_fgd + k, the skew
	sub.w	st_wf,d0
	moveq	#15,d6
	and.w	d0,d6
	asr.w	#4,d0
	move.w	d0,st_fgd
	moveq	#16,d5
	sub.w	d6,d5
	moveq	#0,d3
	moveq	#0,d0
	moveq	#-1,d1			; the full chunks' end masks
	move.w	d1,st_fe3
	lsr.w	d6,d1
	move.w	d1,st_fe1
	tst.w	d6
	beq.s	.s0
	moveq	#1,d3
	moveq	#-1,d1
	lsl.w	d5,d1
	move.w	d1,st_fe3
	moveq	#$40,d0
	or.w	d6,d0			; (NFSR)
.s0:	move.w	d3,st_fsf
	move.b	d0,BLT_SKEW.w
	lea	st_ptab,a5		; per n chunks: XC, SYI, DYI
	moveq	#1,d0
.pt:	move.w	d0,d1
	add.w	d3,d1
	move.w	d0,d2
	add.w	d2,d2
	move.w	d1,(a5,d2.w)
	move.w	d0,d4
	subq.w	#1,d4
	lsl.w	#3,d4
	neg.w	d4
	addq.w	#2,d4
	move.w	d4,16(a5,d2.w)
	move.w	d1,d4
	subq.w	#1,d4
	lsl.w	#3,d4
	neg.w	d4
	addq.w	#2,d4
	move.w	d4,32(a5,d2.w)
	addq.w	#1,d0
	cmp.w	#ST_RUN,d0
	bls.s	.pt
	move.w	#$0203,BLT_HOP.w
	move.w	#8,BLT_SXI.w
	move.w	#8,BLT_DXI.w
	move.w	st_fy,d0
	lsr.w	#3,d0
	move.w	d0,st_frow
	move.w	#33-1,st_frows
.row:	move.w	st_frow,d0
	and.w	#63,d0
	move.w	d0,d1			; its first line in the picture (-7 .. 255)
	lsl.w	#3,d1
	sub.w	st_fy,d1
	and.w	#511,d1
	cmp.w	#512-8,d1
	blo.s	.t
	sub.w	#512,d1
.t:	cmp.w	#ST_PL,d1
	bge	.rn
	move.w	d1,st_ftop
	lea	st_fgdirty,a0
	tst.b	(a0,d0.w)
	beq.s	.built
	clr.b	(a0,d0.w)
	bsr	st_fgbuild
.built:	move.w	d0,d1			; the row's pieces
	mulu	#ST_FROW,d1
	lea	st_fgpcs,a0
	add.l	d1,a0
	tst.w	(a0)
	bmi	.rn
	moveq	#0,d1			; the source: the row's first line, chunk k0
	move.w	d0,d1
	moveq	#12,d2
	lsl.l	d2,d1
	lea	st_fgimg,a2
	add.l	d1,a2
	move.w	st_fk0,d1
	lsl.w	#3,d1
	add.w	d1,a2
	move.w	st_ftop,d1		; the destination
	add.w	#ST_G,d1
	mulu	#ST_LB,d1
	move.l	st_dorg,a3
	add.l	d1,a3
	move.w	st_fgd,d1
	add.w	st_fk0,d1
	ext.l	d1
	lsl.l	#3,d1
	add.l	d1,a3
	lea	BLT_END1.w,a4
	moveq	#4,d4
	moveq	#-$40,d2		; ($C0: busy, HOG)
    ifd ST_NOCOPY
	moveq	#0,d2
    endc
	move.l	a0,-(sp)
	addq.l	#ST_FB,a0
	move.w	(a0)+,d7		; two partial chunks
	beq	.p1
	move.w	4(a5),BLT_XC.w
	move.w	16+4(a5),BLT_SYI.w
	move.w	32+4(a5),BLT_DYI.w
	subq.w	#1,d7
	tst.w	d6
	beq.s	.q2
.p2:	move.w	(a0)+,d0
	move.l	(a0)+,d1
	move.w	d1,d3
	lsr.l	d6,d1
	move.l	d1,(a4)			; END1, END2
	lsl.w	d5,d3
	move.w	d3,4(a4)		; END3
	lea	(a2,d0.w),a1
	move.l	a1,BLT_SRC.w
	lea	(a3,d0.w),a1
	move.l	a1,BLT_DST.w
	move.w	d4,BLT_YC.w
	move.b	d2,BLT_CTRL.w
	dbf	d7,.p2
	bra.s	.p1x
.q2:	move.w	(a0)+,d0		; (no skew)
	move.l	(a0)+,d1
	move.w	d1,4(a4)
	swap	d1
	move.w	d1,(a4)
	lea	(a2,d0.w),a1
	move.l	a1,BLT_SRC.w
	lea	(a3,d0.w),a1
	move.l	a1,BLT_DST.w
	move.w	d4,BLT_YC.w
	move.b	d2,BLT_CTRL.w
	dbf	d7,.q2
.p1x:	move.l	(sp),a0
	add.w	#ST_FC,a0
	bra.s	.p1y
.p1:	move.l	(sp),a0
	add.w	#ST_FC,a0
.p1y:	move.w	(a0)+,d7		; one partial chunk
	beq.s	.pf
	move.w	2(a5),BLT_XC.w
	move.w	16+2(a5),BLT_SYI.w
	move.w	32+2(a5),BLT_DYI.w
	subq.w	#1,d7
.p1l:	move.w	(a0)+,d0
	moveq	#0,d1
	move.w	(a0)+,d1
	swap	d1
	lsr.l	d6,d1
	move.w	d1,4(a4)		; END3
	swap	d1
	move.w	d1,(a4)			; END1
	lea	(a2,d0.w),a1
	move.l	a1,BLT_SRC.w
	lea	(a3,d0.w),a1
	move.l	a1,BLT_DST.w
	move.w	d4,BLT_YC.w
	move.b	d2,BLT_CTRL.w
	dbf	d7,.p1l
.pf:	move.l	(sp),a0
	add.w	#ST_FF,a0
	move.w	(a0)+,d7		; full chunks
	beq.s	.pd
	move.w	st_fe1,(a4)
	move.w	#-1,2(a4)
	move.w	st_fe3,4(a4)
	subq.w	#1,d7
	moveq	#-1,d3			; (the n written)
.pfl:	move.w	(a0)+,d1		; n * 2
	cmp.w	d1,d3
	beq.s	.pfs
	move.w	d1,d3
	move.w	(a5,d1.w),BLT_XC.w
	move.w	16(a5,d1.w),BLT_SYI.w
	move.w	32(a5,d1.w),BLT_DYI.w
.pfs:	move.w	(a0)+,d0
	lea	(a2,d0.w),a1
	move.l	a1,BLT_SRC.w
	lea	(a3,d0.w),a1
	move.l	a1,BLT_DST.w
	move.w	d4,BLT_YC.w
	move.b	d2,BLT_CTRL.w
	dbf	d7,.pfl
.pd:	move.l	(sp)+,a0		; the row's rectangle: its chunks (+ 1 shifted), its 8 lines (the lines outside the
	move.l	st_dorg,d0		; window are BG lines that scroll into it)
	sub.l	st_dbuf,d0
	move.w	st_ftop,d3
	add.w	#ST_G,d3
	mulu	#ST_LB,d3
	add.l	d3,d0
	move.w	st_fgd,d3
	add.w	st_fk0,d3
	add.w	(a0),d3
	ext.l	d3
	lsl.l	#3,d3
	add.l	d3,d0
	move.l	st_fgrp,a1
	move.l	d0,(a1)+
	move.w	2(a0),d3
	sub.w	(a0),d3
	addq.w	#1,d3
	add.w	st_fsf,d3
	lsl.w	#2,d3
	move.b	d3,(a1)+
	move.b	#8,(a1)+
	clr.w	(a1)+
	move.l	a1,st_fgrp
.rn:	addq.w	#1,st_frow
	subq.w	#1,st_frows
	bpl	.row
	movem.l	(sp)+,d0-d7/a0-a6
	move.l	st_fgrp,a0
	rts

; st_fgbuild: d0 = a FG row: its pieces in the window's chunks k0 .. k0 + 21 (st_fgpcs + row * ST_FROW: the first and
; the last chunk with pieces - relative to k0, -1: none -, then the pieces by kind; see ST_FROW).  Keeps d0, d2, d4-d6,
; a2-a5.
st_fgbuild:
	movem.l	d0-d7/a0-a6,-(sp)
	move.w	d0,d1
	mulu	#ST_FROW,d1
	lea	st_fgpcs,a6
	add.l	d1,a6
	move.w	#-1,(a6)		; (none yet)
	lea	st_fgrc,a0		; (a row without opaque pixels: none)
	move.w	d0,d1
	lsl.w	#2,d1
	tst.l	(a0,d1.w)
	beq	.x
	move.w	#$7FFF,st_fr0
	move.w	#-1,st_fr1
	lea	ST_FB+2(a6),a2		; the kinds' next entries: two, one, full
	lea	ST_FC+2(a6),a3
	lea	ST_FF+2(a6),a5
	lsl.w	#3,d0
	move.w	d0,st_fml		; the row's first FG map line
	clr.w	st_fl
.line:	move.w	st_fml,d0		; a line: its mask words from chunk k0 (a1, a4)
	add.w	st_fl,d0
	moveq	#0,d1
	move.w	d0,d1
	lsl.l	#7,d1
	lea	st_fgmsk,a1
	add.l	d1,a1
	move.w	st_fk0,d1
	add.w	d1,d1
	add.w	d1,a1
	move.l	a1,a4
	move.w	st_fl,d6		; (the line's offset)
	moveq	#9,d1
	lsl.w	d1,d6
	moveq	#21,d7
.k:	move.w	(a1)+,d0		; (empty chunks)
	dbne	d7,.k
	beq	.le
	move.l	a1,d3			; the chunk: (its index - k0) * 2
	sub.l	a4,d3
	subq.w	#2,d3
	move.w	d3,d4			; its offset
	add.w	d4,d4
	add.w	d4,d4
	add.w	d6,d4
	lsr.w	#1,d3			; (the index)
	cmp.w	st_fr0,d3
	bge.s	.f0
	move.w	d3,st_fr0
.f0:	cmp.w	#-1,d0
	beq.s	.full
	tst.w	d7
	beq.s	.one
	move.w	(a1),d1
	beq.s	.one
	cmp.w	#-1,d1
	beq.s	.one
	move.w	d4,(a2)+		; two partial chunks
	move.w	d0,(a2)+
	move.w	d1,(a2)+
	moveq	#2,d1
	bra.s	.go
.one:	move.w	d4,(a3)+
	move.w	d0,(a3)+
	moveq	#1,d1
	bra.s	.go
.full:	move.w	d7,d0			; full chunks: as many as follow (ST_RUN at most)
	beq.s	.f1
	cmp.w	#ST_RUN-1,d0
	bls.s	.fm
	moveq	#ST_RUN-1,d0
.fm:	move.l	a1,a0
	subq.w	#1,d0
.fr:	cmp.w	#-1,(a0)+
	dbne	d0,.fr
	beq.s	.fa
	subq.l	#2,a0
.fa:	move.l	a0,d1
	sub.l	a1,d1
	lsr.w	#1,d1
	addq.w	#1,d1
	bra.s	.fe
.f1:	moveq	#1,d1
.fe:	move.w	d1,d0
	add.w	d0,d0
	move.w	d0,(a5)+
	move.w	d4,(a5)+
.go:	add.w	d1,d3			; the last chunk
	subq.w	#1,d3
	cmp.w	st_fr1,d3
	ble.s	.l1
	move.w	d3,st_fr1
.l1:	subq.w	#1,d1			; (the chunks after the first)
	add.w	d1,a1
	add.w	d1,a1
	addq.w	#1,d1
	sub.w	d1,d7
	bpl	.k
.le:	addq.w	#1,st_fl
	cmp.w	#8,st_fl
	blo	.line
	move.l	a2,d0			; the counts
	sub.l	a6,d0
	sub.w	#ST_FB+2,d0
	divu	#6,d0
	move.w	d0,ST_FB(a6)
	move.l	a3,d0
	sub.l	a6,d0
	sub.w	#ST_FC+2,d0
	lsr.w	#2,d0
	move.w	d0,ST_FC(a6)
	move.l	a5,d0
	sub.l	a6,d0
	sub.w	#ST_FF+2,d0
	lsr.w	#2,d0
	move.w	d0,ST_FF(a6)
	move.w	st_fr1,d0
	bmi.s	.x
	move.w	st_fr0,(a6)
	move.w	d0,2(a6)
.x:	movem.l	(sp)+,d0-d7/a0-a6
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
	btst	#12,d1
	beq.s	.fgt
	add.l	#4096*32,a1		; (bit 12: a BG strip's tile - the BG tiles follow the FG's)
.fgt:
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
ST_PASSES	macro			; d1 lines in passes of d3 lines (a4 BLT_YC, d5 the start); d1 >= 1
.p\@:	cmp.w	d3,d1
	bls.s	.q\@
	move.w	d3,(a4)
	move.b	d5,4(a4)
	sub.w	d3,d1
	bra.s	.p\@
.q\@:	move.w	d1,(a4)
	move.b	d5,4(a4)
	endm

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
	; (the registers that stay: a copy, 2 a word, HOG passes started by d5 at BLT_YC + 4)
	move.w	#2,BLT_SXI.w
	move.w	#2,BLT_DXI.w
	move.w	#$0203,BLT_HOP.w
	clr.b	BLT_SKEW.w
	lea	BLT_YC.w,a4
    ifd ST_NOCOPY
	moveq	#0,d5
    else
	moveq	#-$40,d5		; ($C0: busy, HOG)
    endc
	; the log: a group's 4 plane words a line, the byte's mask, 8 lines a pass
	move.w	#4,BLT_XC.w
	move.w	#ST_LB-6,BLT_SYI.w
	move.w	#ST_LB-6,BLT_DYI.w
	moveq	#0,d4			; (the masks loaded: none yet)
.l:	cmp.w	d6,d7
	beq.s	.lx
	move.w	d6,d2
	lsl.w	#3,d2
	move.l	(a3,d2.w),d0		; offset
	lea	(a5,d0.l),a0
	move.l	a0,BLT_SRC.w
	lea	(a6,d0.l),a0
	move.l	a0,BLT_DST.w
	move.w	6(a3,d2.w),d3		; the byte's mask
	cmp.w	d3,d4
	beq.s	.m
	move.w	d3,d4
	move.w	d3,BLT_END1.w
	move.w	d3,BLT_END2.w
	move.w	d3,BLT_END3.w
.m:	move.w	4(a3,d2.w),d1		; lines
    ifd DEBUG
	addq.l	#1,st_nlog
	add.l	d1,st_nlogl
    endc
	moveq	#8,d3
	ST_PASSES
	addq.w	#1,d6
	and.w	#ST_LOG-1,d6
	bra.s	.l
.lx:	; the last sprites' rectangles
	moveq	#-1,d0
	move.w	d0,BLT_END1.w
	move.w	d0,BLT_END2.w
	move.w	d0,BLT_END3.w
	move.w	st_draw,d0
	add.w	d0,d0
	lea	st_dmgn,a0
	move.w	(a0,d0.w),d7
	clr.w	(a0,d0.w)
	lea	st_dmg,a2
	mulu	#ST_DMG*8/2,d0
	add.l	d0,a2
	lea	st_lpp,a3
	subq.w	#1,d7
	bmi.s	.dx
.d:	move.l	(a2)+,d0
	lea	(a5,d0.l),a0
	move.l	a0,BLT_SRC.w
	lea	(a6,d0.l),a0
	move.l	a0,BLT_DST.w
	moveq	#0,d0
	move.b	(a2)+,d0		; words a line
	moveq	#0,d1
	move.b	(a2)+,d1		; lines
	addq.l	#2,a2
    ifd DEBUG
	move.w	d0,d2
	mulu	d1,d2
	add.l	d2,st_nrectw
    endc
	move.w	d0,BLT_XC.w
	move.w	#ST_LB+2,d2
	sub.w	d0,d2
	sub.w	d0,d2
	move.w	d2,BLT_SYI.w
	move.w	d2,BLT_DYI.w
	moveq	#1,d3			; the lines a pass: 32 words
	cmp.w	#32,d0
	bhi.s	.lp
	move.b	(a3,d0.w),d3
.lp:	ST_PASSES
	dbf	d7,.d
.dx:	rts
.full:	; (the whole buffer from the clean one)
    ifd DEBUG
	addq.l	#1,st_nfull
    endc
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
	move.w	st_flines,d1
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
st_sprites_sq:				; (the squeezed scenes: st_object for each object)
	move.w	#$0203,BLT_HOP.w
	move.w	#2,BLT_SXI.w		; (the plane words of a piece's row, the planes in order: the source runs on)
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

; st_sprites: the fast loop (not squeezed): the sprite code's registers set once (a1 END1, a6 END3, a5 YC, a2 CTRL,
; d1 4, d2 the start, d4 a line), d5 the window st_W, d6 the erase rectangles' pointer, d7 the slot - the code keeps
; them (it uses d0, a0, a3, a4); st_obj2 a record.  The rectangles' count once at the end (at most 112 objects).
st_sprites:
	move.l	st_scn,a0
	btst	#0,SC_FLAGS+1(a0)
	bne	st_sprites_sq
	movem.l	d5-d6,-(sp)		; (the caller's)
	move.w	#$0203,BLT_HOP.w
	move.w	#2,BLT_SXI.w
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
	move.l	a0,d6
	move.l	a0,st_dmg0
	tst.b	st_bgon
	beq.s	.nf
	bsr	st_fgdraw		; (the BG scroll mode: the FG under the sprites, its rectangles first)
	move.l	a0,d6
	move.w	#2,BLT_SXI.w
	move.w	#2,BLT_SYI.w
	move.w	#8,BLT_DXI.w
	move.w	#$FFFF,BLT_END2.w
	clr.b	BLT_SKEW.w
.nf:	move.w	st_W,d5
	lea	BLT_END1.w,a1
	lea	BLT_END3.w,a6
	lea	BLT_YC.w,a5
	lea	BLT_CTRL.w,a2
	moveq	#4,d1
	moveq	#-$40,d2
	move.w	#ST_LB,d4
	move.w	#$3F8,d7		; the fixed slots ($3F8 .. $3C0: under the others), then the list from its end
.f:	lea	m72_objs,a0
	tst.w	(a0,d7.w)
	beq.s	.fn
	add.w	d7,a0
	bsr	st_obj2
.fn:	subq.w	#8,d7
	cmp.w	#$3C0,d7
	bhs.s	.f
	move.w	m72_objs_end,d7
	cmp.w	#$3C0,d7
	bls.s	.e
	move.w	#$3C0,d7
.e:	subq.w	#8,d7
	cmp.w	#$C0,d7
	blt.s	.x
.o:	lea	m72_objs,a0
	tst.w	(a0,d7.w)
	beq.s	.on
	add.w	d7,a0
	bsr	st_obj2
.on:	subq.w	#8,d7
	cmp.w	#$C0,d7
	bge.s	.o
.x:	move.l	d6,d0			; the rectangles' count
	sub.l	st_dmg0,d0
	lsr.l	#3,d0
	move.l	st_dmgnp,a0
	move.w	d0,(a0)
	movem.l	(sp)+,d5-d6
	rts

; st_obj2: a0 = the record (BW, entries, colour, x, y): as st_object (see there), with the loop's registers; scratch
; d0, d3, a0, a3, a4 (and the stack).
st_obj2:
    ifd SIM
	addq.l	#1,st_nobj
    endc
	moveq	#0,d0
	move.w	(a0),d0
	lsr.w	#1,d0
	lsl.l	#4,d0
	lea	st_dt2,a3
	add.l	d0,a3			; its entry: the record, the last colouring (data, key), H * ST_LB + 64
	move.l	(a3),d0
	beq	.unknown
	subq.l	#1,d0
	beq	.out			; (a star, an empty one)
	addq.l	#1,d0
	move.l	d0,a4			; the whole sprite's record
	move.w	#384,d0			; the top line: 384 - y + OY
	sub.w	6(a0),d0
	add.w	2(a4),d0
	move.w	d0,d3
	add.w	4(a4),d3
	ble	.out			; (above the picture)
	cmp.w	#ST_PL,d0
	bge	.out			; (below)
	cmp.w	#-ST_G,d0
	blt	.out
	move.w	4(a0),d3		; x relative to the window: x + OX - 352
	add.w	(a4),d3
	sub.w	#256+96,d3
	add.w	6(a4),d3
	ble	.out			; (wholly left)
	sub.w	6(a4),d3
	cmp.w	#320,d3
	bge	.out			; (right)
	add.w	d5,d3			; the buffer x
    ifd SIM
	addq.l	#1,st_ndrawn
    endc
	move.w	d0,-(sp)		; (the top line, x)
	move.w	d3,-(sp)
	moveq	#15,d3			; the colour: its plane words (the entry's last colouring, else st_bake)
	and.b	3(a0),d3
	lea	st_rcid,a0
	move.w	d3,d0
	add.w	d0,d0
	move.w	(a0,d0.w),d0		; the key: the row's colouring id
	cmp.w	8(a3),d0
	bne.s	.miss
	move.l	4(a3),BLT_SRC.w
	bra.s	.hit
.miss:	movem.l	d0-d2/d4/a1-a6,-(sp)
	moveq	#15,d2
	and.w	d3,d2
	move.l	a4,a2
	bsr	st_bake			; -> a3
	move.l	a3,d3
	movem.l	(sp)+,d0-d2/d4/a1-a6
	move.l	d3,4(a3)
	move.w	d0,8(a3)
	move.l	d3,BLT_SRC.w
.hit:	move.l	a3,a0			; (the entry)
	move.w	(sp)+,d3		; x
	move.w	(sp),d0			; the top line (kept on the stack)
	add.w	#ST_G,d0		; the destination: the line, the first word
	mulu	d4,d0
	add.l	st_dorg,d0
	move.w	d3,-(sp)
	asr.w	#4,d3
	lsl.w	#3,d3
	ext.l	d3
	add.l	d3,d0
	move.l	d6,a3			; the erase rectangle: offset, words a line ((x & 15) + W - 1) / 16 + 1 groups, the
	move.l	d0,d3			; visible lines (the guard rows are drawn into, never erased: never shown)
	sub.l	st_dbuf,d3
	move.l	d3,(a3)+
	move.w	(sp),d3
	and.w	#15,d3
	add.w	6(a4),d3
	subq.w	#1,d3
	lsr.w	#4,d3
	addq.w	#1,d3
	lsl.w	#2,d3
	move.b	d3,(a3)+
	tst.b	st_bgon			; (the BG scroll mode: the lines above and below the window are BG lines that
	beq.s	.clip			; scroll into it - the whole sprite erased)
	move.b	5(a4),(a3)+
	bra.s	.lns
.clip:	moveq	#0,d3			; the bottom: min(top + H, ST_PL)
	move.b	5(a4),d3
	add.w	2(sp),d3
	cmp.w	#ST_PL,d3
	ble.s	.bot
	move.w	#ST_PL,d3
.bot:	tst.w	2(sp)
	bpl.s	.top
	move.b	d3,(a3)+		; (above the picture: from line 0)
	move.w	2(sp),d3
	neg.w	d3
	mulu	d4,d3
	add.l	d3,-6(a3)
	bra.s	.lns
.top:	sub.w	2(sp),d3
	move.b	d3,(a3)+
.lns:	clr.w	(a3)+
	move.l	a3,d6
	move.w	10(a0),d3		; (a 64 KB crossing: the long-destination code)
	add.w	d0,d3
	scs	d3
	move.w	d3,a3
	move.w	(sp)+,d3		; the shift's stream
	addq.l	#2,sp			; (the top line)
	and.w	#15,d3
	lsl.w	#2,d3
	move.l	24(a4,d3.w),a0
	move.w	a3,d3
	tst.b	d3
	bne.s	.long
	move.l	12(a4),-(sp)		; the code
	move.l	d0,BLT_DST.w		; (the high word; the code writes the low word)
	lea	BLT_DYI.w,a3
	lea	BLT_DST+2.w,a4
	rts				; (into the code: it returns to the loop)
.long:	addq.l	#1,st_nlong
	move.l	16(a4),-(sp)
	move.l	d0,a3
	lea	BLT_DST.w,a4
	rts
.out:	rts
.unknown:
	addq.l	#1,st_unknown
	rts

; st_object: a0 = the record (BW, entries, colour, x, y): its whole sprite (tools/stage_sprites.py: OX, OY, H, W,
; its plane bytes / 8, its groups G, the code (word / long destination), its pens, 16 streams (a shift each), G x (class,
; rows)) coloured (st_bake) and drawn by its code: per group of pieces (rows up to 32 pixels, the same mask and position
; in their word) one setup - XC, DYI, END1 (+ END2), END3, control - from the shift's stream, then each piece a
; destination step and a restart (stefastbobs2 / stedaimakaimura's sprite_compiler.js).  Culled when wholly outside
; the window; drawn whole into the side margins (the window's edges are not on 16-pixel boundaries).  The erase
; rectangle: its words and lines.
st_object:
    ifd SIM
	addq.l	#1,st_nobj
    endc
	moveq	#0,d0
	move.w	(a0),d0
	lsr.w	#1,d0
	lsl.l	#2,d0
	lea	st_deftab,a1
	move.l	(a1,d0.l),d1
	beq	.unknown
	cmp.l	#1,d1
	beq	.out			; (a star, an empty one)
	move.l	d1,a2			; the whole sprite's record
	moveq	#15,d2
	and.b	3(a0),d2		; the colour row
	move.w	#384,d4			; the top line: 384 - y + OY
	sub.w	6(a0),d4
	add.w	2(a2),d4
	move.w	d4,d0
	add.w	4(a2),d0
	ble	.out			; (above the picture)
	cmp.w	#ST_PL,d4
	bge	.out			; (below)
	cmp.w	#-ST_G,d4
	blt	.out
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
	sub.w	#256+96,d3		; the sprite's buffer x
	move.w	st_W,d0
	sub.w	6(a2),d0
	cmp.w	d0,d3
	ble	.out			; (wholly left of the window)
	add.w	6(a2),d0
	add.w	#320,d0
	cmp.w	d0,d3
	bge	.out			; (right)
	bsr	st_bake			; -> a3: its plane words (d3, d4, a2 kept)
	move.l	a3,BLT_SRC.w
	move.w	d4,d0			; the destination: the top line, the first word
	add.w	#ST_G,d0
	mulu	#ST_LB,d0
	add.l	st_dorg,d0
	move.w	d3,d1
	asr.w	#4,d1
	lsl.w	#3,d1
	ext.l	d1
	add.l	d1,d0
	; the erase rectangle: words (x >> 4 .. (x + W - 1) >> 4), H lines
	move.l	st_dmgnp,a1
	cmp.w	#ST_DMG,(a1)
	bhs.s	.full
	addq.w	#1,(a1)
	move.w	d3,d1
	add.w	6(a2),d1
	subq.w	#1,d1
	asr.w	#4,d1
	move.w	d3,d5
	asr.w	#4,d5
	sub.w	d5,d1
	addq.w	#1,d1
	lsl.w	#2,d1			; words a line
	move.l	st_dmgp,a1
	move.l	d0,d5
	sub.l	st_dbuf,d5
	move.l	d5,(a1)+
	move.b	d1,(a1)+
	tst.b	st_bgon			; (the BG scroll mode: all its lines)
	beq.s	.clip
	move.b	5(a2),(a1)+
	bra.s	.lns
.clip:	moveq	#0,d1			; the visible lines: min(top + H, ST_PL) - max(top, 0)
	move.b	5(a2),d1
	add.w	d4,d1
	cmp.w	#ST_PL,d1
	ble.s	.bot
	move.w	#ST_PL,d1
.bot:	tst.w	d4
	bpl.s	.top
	move.b	d1,(a1)+
	move.w	d4,d1
	neg.w	d1
	mulu	#ST_LB,d1
	add.l	d1,-6(a1)
	bra.s	.lns
.top:	sub.w	d4,d1
	move.b	d1,(a1)+
.lns:	clr.w	(a1)+
	move.l	a1,st_dmgp
	bra.s	.draw
.full:	move.w	st_draw,d1		; (too many: the whole buffer again next time)
	lea	st_full,a1
	st	(a1,d1.w)
.draw:
    ifd SIM
	addq.l	#1,st_ndrawn
    endc
	moveq	#15,d1			; the shift's stream
	and.w	d3,d1
	lsl.w	#2,d1
	move.l	24(a2,d1.w),-(sp)
	moveq	#0,d1			; (the code steps the destination's low word: a sprite that would cross a 64 KB
	move.w	d0,d1			; boundary takes the long-destination code)
	move.w	4(a2),d5
	mulu	#ST_LB,d5
	add.l	d5,d1
	add.l	#64,d1
	cmp.l	#$10000,d1
	bhi.s	.long
	move.l	d0,BLT_DST.w		; (the high word; the code writes the low word)
	move.l	(sp)+,a0		; the stream
	move.l	12(a2),-(sp)		; the code
	lea	BLT_END1.w,a1
	lea	BLT_END3.w,a6
	lea	BLT_DYI.w,a3
	lea	BLT_DST+2.w,a4
	lea	BLT_YC.w,a5
	moveq	#4,d1
	moveq	#-$40,d2
	move.w	#ST_LB,d4
	lea	BLT_CTRL.w,a2
	rts				; (into the code: it returns to st_object's caller)
.long:	addq.l	#1,st_nlong
	move.l	(sp)+,a0
	move.l	16(a2),-(sp)
	move.l	d0,a3			; (the destination)
	lea	BLT_END1.w,a1
	lea	BLT_END3.w,a6
	lea	BLT_DST.w,a4
	lea	BLT_YC.w,a5
	moveq	#4,d1
	moveq	#-$40,d2
	move.w	#ST_LB,d4
	lea	BLT_CTRL.w,a2
	rts
.out:	rts
.unknown:
	addq.l	#1,st_unknown
	rts

; st_bake: d2 = the colour row, a2 = the whole sprite's record: a3 = its plane words in this colour (cached: the key
; is the record and the colouring's id: the same colours in any row, any scene share it; pre-coloured ones from
; st_preins).  A piece's row: 16 pixels -> its 4 plane words; 32 -> the planes
; in order, each its 2 words (the source of a pass runs on).
; st_preins: the pre-coloured sprites (tools/stage_sprites.py st_precol: BW, colouring id, data; BW 0 ends) into
; st_hash, each in its slot unless the slot is taken (that pair is coloured at run time then)
st_preins:
	movem.l	d0-d2/a0-a2,-(sp)
	lea	st_precol,a1
.l:	moveq	#0,d0
	move.w	(a1)+,d0		; BW
	beq.s	.x
	move.w	(a1)+,d2		; the colouring id
	lsr.w	#1,d0
	lsl.l	#2,d0
	lea	st_deftab,a0
	move.l	(a0,d0.l),a2		; the record
	move.l	a2,d1
	lsr.l	#3,d1
	eor.w	d2,d1
	and.l	#ST_HASH-1,d1
	lsl.l	#4,d1
	lea	st_hash,a0
	add.l	d1,a0
	tst.l	(a0)
	bne.s	.n
	move.l	a2,(a0)
	move.w	d2,4(a0)
	move.l	(a1),6(a0)
.n:	addq.l	#4,a1
	bra.s	.l
.x:	movem.l	(sp)+,d0-d2/a0-a2
	rts

; st_dt2inv: every st_dt2 entry's colouring forgotten (the colour pool starts again)
st_dt2inv:
	movem.l	d0/a0-a1,-(sp)
	lea	st_defs,a0
.l:	moveq	#0,d0
	move.w	(a0)+,d0
	beq.s	.x
	addq.l	#4,a0
	lsr.w	#1,d0
	lsl.l	#4,d0
	lea	st_dt2,a1
	move.w	#$FFFF,8(a1,d0.l)
	bra.s	.l
.x:	movem.l	(sp)+,d0/a0-a1
	rts

st_bake:
	lea	st_rcid,a0
	move.w	d2,d0
	add.w	d0,d0
	move.w	(a0,d0.w),d0		; the key: the row's colouring id
	move.l	a2,d1
	lsr.l	#3,d1
	eor.w	d0,d1
	and.l	#ST_HASH-1,d1
	lsl.l	#4,d1
	lea	st_hash,a0
	add.l	d1,a0			; the slot (16 bytes): record.l, key.w, data.l
	cmp.l	(a0),a2
	bne.s	.miss
	cmp.w	4(a0),d0
	bne.s	.miss
	move.l	6(a0),a3
	rts
.miss:	addq.l	#1,st_nbake
	move.l	a2,(a0)
	move.w	d0,4(a0)
	move.l	st_poolp,a3
	moveq	#0,d1
	move.w	8(a2),d1
	lsl.l	#3,d1			; (its plane bytes)
	add.l	a3,d1
	cmp.l	#st_pool+ST_POOL,d1
	blo.s	.room
	addq.l	#1,st_npool
	bsr	st_dt2inv		; (st_dt2's colourings too)
	movem.l	d0/a0,-(sp)		; (full: everything coloured again)
	lea	st_hash,a1
	move.l	#ST_HASH*16/16-1,d1
.clr:	clr.l	(a1)+
	clr.l	(a1)+
	clr.l	(a1)+
	clr.l	(a1)+
	subq.l	#1,d1
	bpl.s	.clr
	bsr	st_preins		; (the pre-coloured ones again)
	movem.l	(sp)+,d0/a0
	move.l	a2,(a0)
	move.w	d0,4(a0)
	lea	st_pool,a3
.room:	move.l	a3,6(a0)
	movem.l	d2-d7/a2-a3,-(sp)
	moveq	#10,d0
	lsl.l	d0,d2
	lea	st_ta,a5
	add.l	d2,a5			; the row's tables
	lea	st_tb,a6
	add.l	d2,a6
	move.l	20(a2),a0		; its pens
	move.l	a3,a1
	move.w	10(a2),d5		; its groups
	lea	88(a2),a4		; (class, rows)
	subq.w	#1,d5
.grp:	move.b	(a4)+,d3		; the class
	moveq	#0,d7
	move.b	(a4)+,d7		; the rows
	subq.w	#1,d7
.row:	bsr.s	.half			; (16 pixels -> d0 planes 0 / 1, d1 planes 2 / 3)
	tst.b	d3
	bne.s	.w2
	move.l	d0,(a1)+
	move.l	d1,(a1)+
	dbf	d7,.row
	bra.s	.gn
.w2:	move.l	d0,d4			; (32 pixels: the planes in order, each its two words)
	move.l	d1,d6
	bsr.s	.half
	swap	d4
	swap	d0
	move.w	d4,(a1)+		; plane 0
	move.w	d0,(a1)+
	swap	d4
	swap	d0
	move.w	d4,(a1)+		; plane 1
	move.w	d0,(a1)+
	swap	d6
	swap	d1
	move.w	d6,(a1)+		; plane 2
	move.w	d1,(a1)+
	swap	d6
	swap	d1
	move.w	d6,(a1)+		; plane 3
	move.w	d1,(a1)+
	dbf	d7,.row
.gn:	dbf	d5,.grp
	move.l	a1,st_poolp
	movem.l	(sp)+,d2-d7/a2-a3
	rts
.half:	moveq	#0,d0			; 8 pen bytes at a0 -> d0 (planes 0 : 1), d1 (planes 2 : 3)
	moveq	#0,d1
	moveq	#0,d2
	rept	8
	move.b	(a0)+,d2
	lsl.l	#2,d0
	lsl.l	#2,d1
	lsl.w	#2,d2
	or.l	(a5,d2.w),d0
	or.l	(a6,d2.w),d1
	lsr.w	#2,d2
	endr
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
SC_REF		= 0			; a scene (tools/stage_assets.py scenes): 16 bytes its tile-row targets
SC_PAL		= 16			; 16 + 16 words the playfield's and the status bar's STE colours
SC_SPR		= 80			; 256 x 16 bytes: each sprite target's pen indices
SC_TILE		= 80+4096		; each tile target's
SC_HUD		= 80+8192		; each tile target's in the status bar
SC_FLAGS	= 80+12288		; a word: bit 0 the sprites squeezed toward the centre (st_object), bits 8-15 the tiles'
					; shift (the window over the tiles moves, the sprites keep their places)
SC_SIZE		= SC_FLAGS+2
SCENE_MATCH	= 12
st_tiles:	incbin	"stage_tiles.bin"
	even
st_tmask:	incbin	"stage_tmask.bin"	; (the FG tiles' opaque pixels: st_cell over a BG strip)
st_bgstar:	incbin	"stage_bgstar.bin"	; (the BG tiles drawn empty: tools/stage_assets.py)
	even
st_strip:	incbin	"stage_strip_s2.bin"	; (stage 2's BG: tools/stage_bg.py, stage_assets.py strips)
	even
st_zero8:	dcb.l	8,0
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
	include	"stage_sprites.s"
	section data,data
	even
st_sstream:	incbin	"stage_sstream.bin"

	section bss,bss
	even
m72r_pictures:	ds.l	1
m72r_skipped:	ds.l	1
m72r_lates:	ds.l	1
st_unknown:	ds.l	1
st_switches:	ds.l	1		; (scene switches)
st_nlog:	ds.l	1		; (DEBUG: log entries copied, their lines, the erase rectangles' words, whole copies)
st_nlogl:	ds.l	1
st_nrectw:	ds.l	1
st_nfull:	ds.l	1
st_nscene:	ds.l	1		; (scene checks)
st_nrows:	ds.l	1		; (colour rows' tables made)
st_nbarfull:	ds.l	1		; (status bar: whole checks, cells drawn)
st_nbarcells:	ds.l	1
st_nbake:	ds.l	1		; (sprite colourings, pool resets)
st_npool:	ds.l	1
st_fgabs:	ds.l	1		; (the FG's x unwrapped, its last x)
st_fgprev:	ds.w	1
st_origin:	ds.w	1		; (a BG strip scene: its first window column)
st_colabs:	ds.w	64		; (a strip scene: the absolute column each ring column was composed for)
st_cf:		ds.l	8
st_stripon:	ds.b	1
	even
st_dmg0:	ds.l	1		; (this picture's first erase rectangle)
st_nobj:	ds.l	1		; (SIM: the objects, those drawn)
st_ndrawn:	ds.l	1
st_nlong:	ds.l	1		; (sprites drawn with the long-destination code: 64 KB crossings)
st_logn:	ds.l	1
m72r_shown:	ds.w	1
m72r_prev:	ds.w	1
m72r_ready:	ds.b	1
st_off:		ds.b	1
st_allnew:	ds.b	1
st_bardirty:	ds.b	1
st_hver:	ds.b	1
st_barhv:	ds.b	1
	even
st_draw:	ds.w	1
st_dbuf:	ds.l	1
st_dorg:	ds.l	1		; (the picture's line -ST_G: st_dbuf, + st_by lines in the BG scroll mode)
st_fgrp:	ds.l	1
st_fr0:		ds.w	1		; (st_fgdraw: a row's chunks with opaque pixels in the window, the first, the last)
st_fr1:		ds.w	1
st_bgn:		ds.w	1		; (the BG map's cells that are not empty)
st_by:		ds.w	1		; (the BG scroll mode: the window's first BG map line, the FG's window, its first line)
st_wf:		ds.w	1
st_fy:		ds.w	1
st_flines:	ds.w	1		; (the lines a whole copy copies)
st_fgd:		ds.w	1		; (st_fgdraw's)
st_fsf:		ds.w	1
st_fe1:		ds.w	1
st_fe3:		ds.w	1
st_fk0:		ds.w	1
st_fkn:		ds.w	1
st_frow:	ds.w	1
st_frows:	ds.w	1
st_ftop:	ds.w	1
st_fml:		ds.w	1
st_fl:		ds.w	1
st_ptab:	ds.w	24
st_bgon:	ds.b	1
	even
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
st_tdx:		ds.w	1
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
st_rtgt:	ds.w	32		; the targets the rows show (st_palette)
st_pidx:	ds.b	512		; the pens' playfield indices
st_hidx:	ds.b	256		; the tile pens' status bar indices
st_rcid:	ds.w	16		; the sprite rows' colouring ids (st_palette; the sprites' cache key)
st_ver:		ds.b	32		; the colour rows' versions (sprites 0-15, tiles 16-31)
st_cells:	ds.b	4096		; the map cells composed in the clean buffer
st_colok:	ds.b	64		; (a column's window rows all composed)
st_colused:	ds.b	16*64		; (per tile colour the columns it was composed into)
st_fgcopy:	ds.b	$4000
st_bgcopy:	ds.b	$4000
st_fgcells:	ds.b	4096		; (the BG scroll mode: the FG image's cells made, its columns, the rows' cells with
st_fgcolok:	ds.b	64		; opaque pixels)
st_fgrm:	ds.b	512
st_fgrc:	ds.l	64
st_fgdirty:	ds.b	64
st_bz:		ds.b	4096		; (the BG scroll mode's cells whose places hold zeros: never drawn, or empty)
st_fgpcs:	ds.b	64*ST_FROW
st_fgmsk:	ds.b	512*128
st_fgimg:	ds.b	512*ST_LB
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
st_hash:	ds.b	ST_HASH*16
st_deftab:	ds.l	32768
st_dt2:		ds.b	32768*16		; (st_obj2: the record.l, the last colouring's data.l and key.w, H * ST_LB + 64)
st_pool:	ds.b	ST_POOL
st_mem:		ds.b	(ST_NBUF+1)*ST_BUFSZ+ST_BARLB*16+256
