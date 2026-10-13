; The Irem M72 picture on the STE (R-Type, Mr. HELI; included by games/<game>/src/render.s): the centred 320-pixel
; window (picture x 32-351, MAME's bitmap x 96-415) of the 384 x 256 picture, from the video state the translated V30
; program leaves in `m72v` (below).  The reference is engine/m72.py (equal to MAME); games/rtype/tools/render_test.py
; checks every picture against it (pixel for pixel after the colour reduction), tools/sprite_test.py the sprites at the
; edges.  Assets: engine/m72_assets.py (build/<game>/m72_*.bin, from the ROM sets; not in git).
;
; =====================================================================================================================
; Interface for the main program
; =====================================================================================================================
; The includer defines (before the include):
;   M72_NTF, M72_NTB   the FG / BG tile counts of the game (powers of 2: R-Type 4096, Mr. HELI 8192)
;   M72_HUD_TOP        a band ending at this line (lines 0 .. M72_HUD_TOP - 1) may be a HUD bar with its own palette
;                      (Mr. HELI: 32; 0: none)
;   M72_HUD_BOT        a band starting at this line (.. 255) may be a HUD bar (R-Type: 240; 256: none)
;   REN_NBUF           display buffers (default 2)
; and includes this file in its text (it switches to its data and bss sections and back to text); the assets m72_*.bin
; must be on the include path.  -D M72_STATS=1: counters for the tests.
;
; The video state (`m72v_*`, in this file's bss): what the arcade's video hardware would draw from.  The V30 program
; writes it as it writes the board, in the V30's byte order (little-endian words, the addresses' order kept: V30 address
; $D0000 + n is m72v_fg + n):
;   m72v_fg      $4000 bytes  FG video RAM ($D0000-$D3FFF): 64 x 64 tiles, row-major, two words each: code (bits 0-13
;                             the tile, 14 flip x, 15 flip y), attribute (bits 0-3 colour, 6-7 priority group)
;   m72v_bg      $4000 bytes  BG video RAM ($D8000-$DBFFF), the same
;   m72v_spr     $400 bytes   the sprite buffer: the copy of sprite RAM ($C0000-$C03FF) made by the last write to port
;                             $04 (the DMA; MAME's buffered sprite RAM, the program's own sprite RAM is elsewhere):
;                             128 entries of 4 words (y, code, attribute, x); an entry of all 0 is skipped quickly
;   m72v_pal0    $C00 bytes   palette 0 (the sprites' pens 0-255, $C8000-$C8BFF) with A9 folded (a write to an address
;                             with bit 9 set goes to the word without it): words $000-$0FF red, $200-$2FF green,
;                             $400-$4FF blue (byte offsets $000, $400, $800), 5 bits each (the low byte)
;   m72v_pal1    $C00 bytes   palette 1 (the tiles' pens 256-511, $CC000-$CCBFF), the same
; With M72V_EXTERN defined these five are the includer's labels (e.g. `m72v_fg = v30_image+$D0000` when the program's
; V30 memory image holds them in the V30's byte order: no copies; the palettes then need the A9 fold in the program's
; palette writes, and m72v_spr must be the DMA's copy, not the program's sprite RAM).
;   m72v_nbands  word         1-8: the raster bands of the picture (MAME's partial updates)
;   m72v_bands   8 x 6 words  per band: its first line (band 0: 0; a raster interrupt at line L (port $06 - 128) starts
;                             a band at L + 1: MAME draws the line L with the registers before the interrupt's handler),
;                             FG scroll y, FG scroll x, BG scroll y, BG scroll x (ports $80 $82 $84 $86 as the band's lines
;                             see them), flags (bit 0: display off, port $02 bit 3)
;   m72v_vdirty  128 bytes    FG rows 0-63, then BG rows 0-63 (a row = 256 bytes of video RAM): nonzero when the row may
;                             have changed since the last picture (the program sets it after its video RAM stores, e.g.
;                             `st (row)`); the renderer compares the marked rows with its copy and clears the bytes.  All
;                             $FF is fine (everything compared: ~100k cycles); a row left unmarked is never seen
;   m72v_pdirty  byte         nonzero when the palettes may have changed (the renderer compares them with its copy:
;                             ~20k cycles; R-Type cycles colours every frame)
; The bands and the video RAM are taken as they are when m72r_frame runs (the STE draws a picture once): a video RAM
; write that MAME's earlier bands of the same frame would not show is shown in all of them (render_test counts these
; pixels apart: "mid-frame VRAM", not a renderer error).
;
; Routines (all registers kept):
;   m72r_init    once, before the first picture
;   m72r_frame   one picture, any time between the arcade's frames: draws into a buffer that is neither shown, nor the
;                one shown before it (the Shifter scans that once more), nor waiting, and publishes it (one byte
;                store); returns at once when none is free (m72r_skipped + 1)
;   m72r_vbl     in the VBL: shows a published buffer (video base and counter, $ffff8265 fine scroll, $ffff820f line
;                width; PIC_TOP lines are subtracted when PIC_TOP is defined) and copies its palettes and HUD lines to
;                m72r_vbl_pal (16 words: the playfield), m72r_vbl_hpal (the status bar), m72r_vbl_htop / m72r_vbl_hbot
;                (words: picture lines 0 .. htop - 1 and hbot .. 255 use hpal; 0 / 256: none): the main program
;                hands them to engine/rt/borders.s (BD_PALETTE, BD_HUD: shown_pal, hud_pal, hud_top, hud_bot); with
;                BD_VSWITCH (borders.s) it also sets bd_vs_* so the status bar's lines come from its own screen.
;                A VBL without a new picture frees the buffer shown before.
;
; =====================================================================================================================
; Design
; =====================================================================================================================
; The M72 has two 512 x 512 tile layers (64 x 64 tiles of 8 x 8, 4 bits a pixel, 16 colours of 16 pens from palette 1)
; that scroll independently in x and y, per tile a priority group (which pens are over the sprites, which BG pens are
; drawn over FG's under pixels: engine/m72.py), raster bands with other scroll registers (R-Type's status bar, Mr.
; HELI's top panel and cave splits), and up to 128 sprite entries of 16 x 16 pieces (1/2/4/8 wide and tall, flips;
; palette 0).  R-Type's and Mr. HELI's layers scroll at different speeds almost always (parallax: FG 0.5 and BG 1 or
; 0.25 pixel a frame in R-Type; FG 2 and BG 1 in Mr. HELI), so no composed picture stays valid when they scroll.
;
; * Layer images (m72r_imgf / m72r_imgb, 192 KB each): each layer's whole map in STE indices, plane-separated and
;   column-major (a word column's 512 lines consecutive: a tile's 4 rows of a plane are one movep.l), plus mask planes:
;   FG opaque, FG over the sprites; BG over the sprites, BG drawn over FG's under pixels.  A tile is converted when the
;   picture first needs it (its valid bit; video RAM changes and a new colour mapping clear it) through a direct-mapped
;   cache of conversions (layer, tile, flips, colour, group, mapping): repeated tiles cost a copy.
; * Buffers (REN_NBUF, 147 KB each): virtual screens of 1024 x 288 (16 guard lines above and below the picture).  The
;   window (buffer x W .. W + 319) follows one layer's x scroll (W = its scroll x + 96 mod 512, or + 512, the nearer to
;   the buffer's last window; the video address and the fine scroll register): that layer does not move in the buffer.
;   Which layer: the one that leaves fewer cells to draw (m72r_follow_check, every 8 pictures from the cells each layer
;   contributes and the layers' recent moves; R-Type's starfield stages follow FG, its organic stage 3 BG).
; * Cells (8 x 8 of the buffer): a buffer remembers per cell row what it drew (the bands' offsets, the cells FG and BG
;   contributed to: BS_FDEP / BS_BDEP, the cells of sprites not saved: BS_DMG, tiles changed since: BS_DIRF /
;   BS_DIRB).  A picture draws a cell again when it entered the window, an unsaved sprite covered it, a tile under it
;   changed, or a layer that
;   contributes to it (now or in the buffer's last picture) moved relative to the buffer.  FG contributes where it has
;   an opaque pixel; BG where it is not neutral (one pen of the scene's most frequent BG index m72r_p0, no over pixel)
;   and FG does not cover it.  These are 64-bit row operations on per-layer tile flag bitmaps (projections: the 1-2 map
;   rows of a cell row, the tile to the right when the offset is not a multiple of 8, a rotation by the offset;
;   cached per row for the layer that stays put).  Rows within one band take a fast path (m72r_frow); a row with a band
;   boundary is cut into segments.
; * Drawing a segment's cells: runs of cells by class, Blitter passes from the layer images (per plane: the source is
;   skewed for the moving layer): BG copy (FG transparent), FG copy (FG covers: all over, or all opaque and no BG
;   pixel drawn over FG under pixels), FG over BG (BG copy, the FG opaque plane ANDed out, the FG planes ORed in);
;   cells where BG pixels go over FG's under pixels (groups 1 / 3 over 0 / 1) get those again through two temporary
;   rows (m72r_bodfix).  Display-off bands are black.
; * Sprites: the list from entry 0 on (the arcade draws from the last and the first pixel drawn wins: the STE paints
;   the other way round); a piece in a colour and flip x is converted once into the cache (chunky source, a table per
;   colour: its opaque rows' masks, then their plane words: the Blitter's source runs on).  A line is one HOG pass (Y
;   count 4: the planes).  A whole piece without priority pixels runs its generated routine (per code, flip x and
;   skew, colour-independent: stefastbobs2's unrolled passes, END1/END3 as immediates written only where they change
;   from the line before, add.l d4,(a4) to the next line's destination); clipped pieces and pieces with priority
;   pixels take m72r_sdraw's line loop over a baked mask stream.  Clipped at the 16-pixel groups nearest the window's
;   edges (CL = W & ~15, CR = (W + 335) & ~15: the inner word only), culled when wholly outside, whole into the guard
;   lines at the top and bottom.  A piece over tiles with pixels over the sprites (MAME's priority: FG group 1 pens
;   8-15, groups 2/3, the same for BG) or over a display-off band gets those pixels out of its masks line by line
;   (from the layer images' over planes).  The background under every piece is saved before any is drawn (Blitter
;   copies, 4-8 lines a pass) and copied back before the buffer's next composition (any order: all were saved
;   clean); a piece the save area has no room for marks its cells as damage (recomposed) instead.
;
; Colours: pens map to STE indices through m72r_pidx.  A choice takes the offline scene whose reference tile palette
; fits (engine/m72_palettes.py), else (an unknown scene at rest, or pens no scene colour fits) samples the picture
; and the visible sprites' pens and clusters (Oklab, k-means); index 0 stays black.  An index's STE colour is the
; current colour of its representative: the pen nearest its centre among the pens in use (m72r_suse: marked by
; the tile conversions and the sprites drawn; m72r_urep every 32 pictures, m72r_repfix when a representative's colour
; leaves its centre), so fades and colour cycles change the STE palette without redrawing.  The mapping is repaired
; incrementally (m72r_sdiv, when the palette or the pens in use change, before a picture's tiles and again before its
; sprites when new sprite pens appear): a pen in use more than M72_DIV from the colour its index shows goes to the
; nearest shown colour once its colour has settled (M72_STABLE / M72_SSTABLE pictures); a sprite colour row then gets
; a new mapping version (m72r_shrow: its conversions keyed by it, a cycle's last M72_SROWS mappings reused), a tile
; colour row only its own tiles converted again (m72r_cinval: per-row tile maps m72r_rowmap, conversions keyed by the
; row's version m72r_cver; a row at most every M72_CWAIT pictures); no shown colour near: the index of the nearer of
; the two most alike shown colours takes the pen's colour (m72r_repurp, its pens to the other one); many far pens: a
; new choice.  A new choice: the first picture, a palette that rested 2 pictures with 16 or more pens changed,
; m72r_sdiv.  It converts the window's tiles again (~13-16M cycles over 15-18 calls).
; The status bar (R-Type's bottom bar, Mr. HELI's top panel; a band FG covers completely, on the 8-pixel grid) is a
; screen of its own: drawn from its FG tiles into the buffer's bar area (m72r_bardraw: the tiles changed since that
; buffer's last picture), its colours exact (m72r_barpens: each pen its tiles use an index of its own, the index's
; colour that pen's current colour), its band black and out of the playfield's colours; borders.s (BD_VSWITCH, with
; BD_HUD) switches the video address, the fine scroll, the line width and the palette at its first line (and back
; at a top bar's end): m72r_vbl sets bd_vs_* from the picture shown (m72r_disp_bar, m72r_disp_hud).

; Every Blitter pass is HOG and at most 256 bus cycles (AGENTS.md; checked with BLIT_STATS=256): passes are cut into
; pieces of lines from a table of the bus accesses a line.  No NFSR in the composition passes (Hatari and engine/sim.py
; apply the source increments differently after an NFSR line end); the sprite passes use NFSR only with SXI = SYI.
;
; Measured on Musashi (CPU + Blitter bus cycles of m72r_frame, the game logic apart): see the summary at the end of the
; file ("Measurements").
; =====================================================================================================================

	ifnd	REN_NBUF
REN_NBUF	= 2
	endc
	ifnd	M72_HUD_TOP
M72_HUD_TOP	= 0
	endc
	ifnd	M72_HUD_BOT
M72_HUD_BOT	= 256
	endc

M72_G		= 16			; guard lines above and below the picture
M72_LB		= 512			; bytes a buffer line
M72_LINES	= M72_G+256+M72_G
M72_BUFSZ	= M72_LINES*M72_LB
M72_PL		= 32768			; a layer image plane: 32 word columns x 512 lines (column-major: a column's lines
					; are consecutive words)
M72_POOL	= 128*1024		; the sprite cache
M72_HASH	= 2048			; its slots
M72_MPOOL	= 32*1024		; the mask streams (a skew, a code, flip x: the pieces drawn by m72r_sdraw)
M72_MHASH	= 1024
M72_CCN		= 2048			; the conversion cache's slots
M72_CCS		= 56			; key, epoch, 12 longs
M72_NSAMP	= 8			; lines between the colour samples
M72_SCENE	= 648			; an offline scene (engine/m72_palettes.py)
M72_CBUDGET	= 250			; tile conversions a picture at most (a new scene takes a few calls)
M72_FALLBACK	= 30			; pictures an unknown tile palette rests before the run-time choice
	ifnd	M72_SPRW
M72_SPRW	= 4			; a visible sprite piece's pen: its weight (a tile sample's: 16; more: brighter sprites, duller tiles)
	endc

; the per-buffer state (a5)
BS_W		= 0			; .w the window's buffer x of the last picture (-1: nothing valid)
BS_NB		= 2			; .w its bands
BS_BT		= 4			; its band table (8 x 16 bytes, see m72r_bt)
BS_FDEP		= BS_BT+128		; 32 cell rows x 8 bytes: the cells (mod 64) the FG layer contributed to
BS_BDEP		= BS_FDEP+256		; the same for the BG layer (not neutral and not covered)
BS_DMG		= BS_BDEP+256		; 36 cell rows (-2 .. 33) x 16 bytes: the cells sprites drew into
BS_DIRF		= BS_DMG+576		; 64 x 8 bytes: FG map tiles changed since the buffer's last picture
BS_DIRB		= BS_DIRF+512		; the same for BG
BS_ND		= BS_DIRB+512		; .w bit 0: FG tiles changed, bit 1: BG
BS_PRI		= BS_ND+4		; 32 cell rows x 8 bytes: the cells (mod 64) with tile pixels over the sprites
BS_SIZE		= BS_PRI+256

; the band table (m72r_bt, BS_BT): 8 entries of 16 bytes
BT_Y0		= 0			; first line
BT_Y1		= 2			; last line + 1
BT_OXF		= 4			; FG map x of buffer x 0 (mod 512)
BT_OYF		= 6			; FG map y of picture line 0 (mod 512)
BT_OXB		= 8
BT_OYB		= 10
BT_OFF		= 12			; display off
BT_SXF		= 14			; (the FG scroll x as written: the window choice)

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
BLT_GO		= $c0			; BUSY + HOG
BLT_NFSR	= $40
BLT_FXSR	= $80

	section	text,code

; ======================================================================================================================
; init
; ======================================================================================================================
m72r_init:
	movem.l	d0-d7/a0-a6,-(sp)
	move.l	#m72r_bufarea+255,d0
	clr.b	d0
	lea	m72r_buf,a0
	moveq	#REN_NBUF-1,d1
.b:	move.l	d0,(a0)+
	add.l	#M72_BUFSZ,d0
	dbf	d1,.b

	move.l	m72r_buf,a0		; the buffers black
	move.l	#REN_NBUF*M72_BUFSZ/16-1,d0
.clr:	clr.l	(a0)+
	clr.l	(a0)+
	clr.l	(a0)+
	clr.l	(a0)+
	subq.l	#1,d0
	bpl	.clr
	lea	m72r_bs,a0		; the buffers' states: nothing valid
	move.w	#REN_NBUF*BS_SIZE/2-1,d0
.bs:	clr.w	(a0)+
	dbf	d0,.bs
	lea	m72r_bs,a0
	moveq	#REN_NBUF-1,d1
.bw:	move.w	#-1,BS_W(a0)
	lea	BS_SIZE(a0),a0
	dbf	d1,.bw
	; the bit reversal of a byte (flip x)
	lea	m72r_rev8,a0
	moveq	#0,d0
.rv:	moveq	#0,d1
	moveq	#7,d2
	move.b	d0,d3
.rb:	lsr.b	#1,d3
	addx.b	d1,d1
	dbf	d2,.rb
	move.b	d1,(a0)+
	addq.w	#1,d0
	cmp.w	#256,d0
	blo	.rv
	; the minterm offsets: pen p -> 4 offsets into the X table (b0, ~b0, b1, ~b1, ...: longs)
	lea	m72r_moff,a0
	moveq	#0,d0
.mo:	moveq	#0,d2
.mk:	move.w	d2,d3
	lsl.w	#3,d3			; 8k
	btst	d2,d0
	bne	.m1
	addq.w	#4,d3			; the inverted plane
.m1:	move.b	d3,(a0)+
	addq.w	#1,d2
	cmp.w	#4,d2
	blo	.mk
	addq.w	#1,d0
	cmp.w	#16,d0
	blo	.mo
	; bytes: the index of the first set bit (0-7, MSB = 0; 8 for 0) and the population
	lea	m72r_lz8,a0
	lea	m72r_pop8,a1
	moveq	#0,d0
.lz:	moveq	#0,d1
	move.b	d0,d2
	beq	.lz0
.lz1:	btst	#7,d2
	bne	.lz2
	add.b	d2,d2
	addq.b	#1,d1
	bra	.lz1
.lz0:	moveq	#8,d1
.lz2:	move.b	d1,(a0)+
	moveq	#0,d1
	move.b	d0,d2
.pc:	tst.b	d2
	beq	.pc1
	lsr.b	#1,d2
	bcc	.pc
	addq.b	#1,d1
	bra	.pc
.pc1:	move.b	d1,(a1)+
	addq.w	#1,d0
	cmp.w	#256,d0
	blo	.lz
	; the lines a piece by the bus accesses a line (4 cycles each): 256 / (4 a), at least 1
	lea	m72r_ptab,a0
	moveq	#0,d0
.pt:	move.l	#64,d1
	tst.w	d0
	beq	.pt1
	divu	d0,d1
	tst.w	d1
	bne	.pt1
	moveq	#1,d1
.pt1:	move.b	d1,(a0)+
	addq.w	#1,d0
	cmp.w	#128,d0
	blo	.pt
	; the source's Y increments by the fetches (2 - (f - 1) * 1024) and the destination's by the words (512 - (n - 1) * 8)
	lea	m72r_xtab,a0
	moveq	#0,d0
.xt:	move.w	d0,d1
	subq.w	#1,d1
	lsl.w	#8,d1
	lsl.w	#2,d1
	neg.w	d1
	addq.w	#2,d1
	move.w	d1,(a0)
	move.w	d0,d1
	subq.w	#1,d1
	lsl.w	#3,d1
	neg.w	d1
	add.w	#M72_LB,d1
	move.w	d1,64(a0)
	addq.l	#2,a0
	addq.w	#1,d0
	cmp.w	#32,d0
	blo	.xt
	clr.b	m72r_x_op2
	st	m72r_vclr
	; the tiles' classes: pen 0 * 4 + (pens 1-7) * 2 + (pens 8-15); bit 3 one pen only, bits 4-7 that pen
	lea	m72r_uf,a0
	lea	m72r_tcf,a1
	move.w	#M72_NTF-1,d0
	bsr	m72r_classes
	lea	m72r_ub,a0
	lea	m72r_tcb,a1
	move.w	#M72_NTB-1,d0
	bsr	m72r_classes
	lea	m72r_ckmap,a0		; (the colour -> index cache of the mapping: empty)
	move.w	#4096/4-1,d0
.ck:	move.l	#-1,(a0)+
	dbf	d0,.ck
	; the colours: none chosen yet (the first picture chooses)
	clr.b	m72r_ncent
	clr.b	m72r_hncent
	st	m72r_need
	move.w	#-1,m72r_scene
	clr.b	m72r_unk
	clr.b	m72r_hud_on
	clr.w	m72r_htop
	move.w	#256,m72r_hbot
	clr.w	m72r_rest
	move.w	#1,m72r_epoch
	lea	m72r_hudrow,a0
	moveq	#64/4-1,d0
.hr:	clr.l	(a0)+
	dbf	d0,.hr
	lea	m72r_pidx,a0
	move.w	#1024/4-1,d0		; (m72r_pidx, m72r_hidx)
.pi:	clr.l	(a0)+
	dbf	d0,.pi
	; the copies of video RAM: compare everything first
	lea	m72v_vdirty,a0
	moveq	#128/4-1,d0
.vd:	move.l	#-1,(a0)+
	dbf	d0,.vd
	lea	m72r_shadow,a0		; (the copies differ from anything: every tile is new)
	move.w	#$8000/4-1,d0
.sh:	move.l	#$ffffffff,(a0)+
	dbf	d0,.sh
	lea	m72r_flags,a0		; flags and valid bits: nothing
	move.w	#M72_FLSZ/4-1,d0
.fl:	clr.l	(a0)+
	dbf	d0,.fl
	clr.w	m72r_nbod
	st	m72v_pdirty
	lea	m72r_palsh,a0		; (the palette copy differs from anything: every pen computed)
	move.w	#2*$c00/4-1,d0
.ps:	move.l	#$ffffffff,(a0)+
	dbf	d0,.ps
	bsr	m72r_stinit
	lea	m72r_rowmap,a0		; (every tile in colour row 0's maps: m72r_tcol all 0)
	move.w	#2*16*512/4-1,d0
.rm:	clr.l	(a0)+
	dbf	d0,.rm
	lea	m72r_rowmap,a0
	moveq	#512/4-1,d0
.r0:	move.l	#-1,16*512(a0)
	move.l	#-1,(a0)+
	dbf	d0,.r0
	lea	m72r_tcol,a0
	move.w	#2*4096/4-1,d0
.tc:	clr.l	(a0)+
	dbf	d0,.tc
	bsr	m72r_flush
	clr.l	m72r_svc		; (no sprite backgrounds saved)
	clr.b	m72r_ready
	move.w	#-1,m72r_shown
	move.w	#-2,m72r_kscene		; (none)
	move.w	#-1,m72r_prev
	clr.w	m72r_follow
	clr.w	m72r_fcount
	clr.l	m72r_pictures
	clr.l	m72r_skipped
	clr.l	m72r_clusters
	movem.l	(sp)+,d0-d7/a0-a6
	rts

; m72r_classes: the class bytes (a1) of d0 + 1 tiles' pen masks (a0)
m72r_classes:
.t:	move.w	(a0)+,d1
	moveq	#0,d2
	btst	#0,d1
	beq	.c1
	addq.b	#4,d2
.c1:	move.b	d1,d3
	and.b	#$fe,d3
	beq	.c2
	addq.b	#2,d2
.c2:	move.w	d1,d3
	and.w	#$ff00,d3
	beq	.c3
	addq.b	#1,d2
.c3:	move.w	d1,d3			; one pen?
	beq	.c5
	subq.w	#1,d3
	and.w	d1,d3
	bne	.c5
	moveq	#-1,d3
.c4:	addq.b	#1,d3
	lsr.w	#1,d1
	bcc	.c4
	lsl.b	#4,d3
	or.b	d3,d2
	or.b	#8,d2
.c5:	move.b	d2,(a1)+
	dbf	d0,.t
	rts

; m72r_sflush: the sprite conversions and the colours' tables only (a sprite pen's index changed: the mask streams and
; the generated routines depend on the shapes alone)
m72r_sflush:
	move.l	a0,-(sp)
	move.l	d0,-(sp)
	clr.l	m72r_stv
	clr.l	m72r_stv+4
	clr.l	m72r_stv+8
	clr.l	m72r_stv+12
	lea	m72r_hash,a0
	move.w	#M72_HASH-1,d0
.h:	clr.l	(a0)+
	clr.l	(a0)+
	dbf	d0,.h
	move.l	#m72r_pool,m72r_poolp
	addq.l	#1,m72r_flushes
	move.l	(sp)+,d0
	move.l	(sp)+,a0
	rts

; the sprite cache: empty
m72r_flush:
	lea	m72r_mhash,a0		; (the mask streams too: rarely needed, cheap)
	move.w	#M72_MHASH-1,d0
.m:	clr.l	(a0)+
	clr.l	(a0)+
	dbf	d0,.m
	move.l	#m72r_mpool,m72r_mpoolp
	bsr	m72r_gflush
	clr.l	m72r_stv		; (the colours' tables: the mapping may have changed)
	clr.l	m72r_stv+4
	clr.l	m72r_stv+8
	clr.l	m72r_stv+12
	lea	m72r_hash,a0
	move.w	#M72_HASH-1,d0
.h:	clr.l	(a0)+
	clr.l	(a0)+
	dbf	d0,.h
	move.l	#m72r_pool,m72r_poolp
	addq.l	#1,m72r_flushes
	rts

; ======================================================================================================================
; m72r_frame: one picture
; ======================================================================================================================
m72r_frame:
	movem.l	d0-d7/a0-a6,-(sp)
	; the buffer: not shown, not the one shown before, not waiting
.snap:	move.w	m72r_shown,d1
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
	cmp.w	#REN_NBUF,d0
	blo	.pick
	addq.l	#1,m72r_skipped
	movem.l	(sp)+,d0-d7/a0-a6
	rts
.chosen:
	move.w	d0,m72r_draw
	move.w	d0,d1
	lsl.w	#2,d1
	lea	m72r_buf,a0
	move.l	(a0,d1.w),m72r_dbuf

	mulu	#BS_SIZE,d0
	lea	m72r_bs,a5
	add.l	d0,a5
	move.l	a5,m72r_cbs
	bsr	m72r_tiles		; video RAM changes: flags, tiles to convert, the buffers' dirty marks
	bsr	m72r_bulkstep		; (after a mass change: the flags again, a part a call)
	bsr	m72r_bands		; the bands, the window, the offsets
	bsr	m72r_palette		; the colours (a new choice when the palette rests on other colours)
	tst.b	m72r_divp
	beq	.nd
	bsr	m72r_sdiv		; (pens in use far from the colour their index shows: mapped again)
.nd:
	bsr	m72r_hud		; the HUD bars
	bsr	m72r_bar		; (a bar: its own buffer and colours)
	tst.b	m72r_need
	beq	.nn
	bsr	m72r_choose		; (a new choice: no picture this call; the conversions from the next)
	bsr	m72r_stepals
	bra	.late
.nn:	bsr	m72r_stepals
	tst.w	m72r_bkpend		; (the flags not done: no conversions, no picture)
	bne	.late
	bsr	m72r_validate		; the tiles the picture shows converted
	tst.b	m72r_late
	beq	.draw
.late:	addq.l	#1,m72r_lates		; (conversions left: no picture this time, the last one stays shown)
	movem.l	(sp)+,d0-d7/a0-a6
	rts
.draw:	bsr	m72r_srestore		; (the background under the buffer's last sprites)
	bsr	m72r_compose
	bsr	m72r_bardraw
	bsr	m72r_follow_check
	bsr	m72r_sprites
	bsr	m72r_uwork		; (the pens used: the representatives)
	addq.w	#1,m72r_since
	bcc	.sn
	subq.w	#1,m72r_since
.sn:	tst.w	m72r_kwait
	beq	.kw
	subq.w	#1,m72r_kwait
.kw:	tst.w	m72r_rpwait
	beq	.kr
	subq.w	#1,m72r_rpwait
.kr:	lea	m72r_cwait,a0
	moveq	#0,d0
.cw:	tst.b	(a0,d0.w)
	beq	.cw1
	subq.b	#1,(a0,d0.w)
	bne	.cw1
	st	m72r_divp		; (its pending pens: m72r_sdiv)
.cw1:	addq.w	#1,d0
	cmp.w	#32,d0
	blo	.cw
	; publish: the window's first line, the fine scroll, the palettes, then the buffer (one byte store)
	move.l	m72r_cbs,a5
	move.w	m72r_draw,d0
	move.w	d0,d1
	lsl.w	#2,d1
	lea	m72r_disp_addr,a0
	move.w	BS_W(a5),d2
	lsr.w	#4,d2
	lsl.w	#3,d2
	ext.l	d2
	add.l	m72r_dbuf,d2
	add.l	#M72_G*M72_LB,d2
	move.l	d2,(a0,d1.w)
	lea	m72r_disp_fine,a0
	moveq	#15,d2
	and.w	BS_W(a5),d2
	move.b	d2,(a0,d0.w)
	lsl.w	#5,d0
	lea	m72r_disp_pal,a1
	add.w	d0,a1
	lea	m72r_stepal,a0
	moveq	#8-1,d2
.pal:	move.l	(a0)+,(a1)+
	dbf	d2,.pal
	lea	m72r_disp_hpal,a1
	add.w	d0,a1
	lea	m72r_stehpal,a0
	moveq	#8-1,d2
.hpl:	move.l	(a0)+,(a1)+
	dbf	d2,.hpl
	lsr.w	#3,d0
	lea	m72r_disp_hud,a1
	move.w	m72r_htop,(a1,d0.w)
	move.w	m72r_hbot,2(a1,d0.w)
	move.w	m72r_draw,d0
	move.w	d0,d1
	mulu	#M72_BARSZ,d1
	add.l	#m72r_barbuf,d1
	lsl.w	#2,d0
	lea	m72r_disp_bar,a1
	move.l	d1,(a1,d0.w)
	move.w	m72r_draw,d0
	addq.b	#1,d0
	move.b	d0,m72r_ready
	addq.l	#1,m72r_pictures
	movem.l	(sp)+,d0-d7/a0-a6
	rts

; ======================================================================================================================
; m72r_vbl: show a published buffer
; ======================================================================================================================
m72r_vbl:
	tst.b	m72r_ready
	bne	.flip
	move.w	#-1,m72r_prev		; (the buffer before the shown one: scanned once more after the flip, free now)
	rts
.flip:
	movem.l	d0-d2/a0-a1,-(sp)
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
	sub.l	#PIC_TOP*M72_LB,d1
	endc
	move.l	d1,-(sp)
	move.b	1(sp),$ffff8201.w
	move.b	2(sp),$ffff8203.w
	move.b	3(sp),$ffff820d.w
	ifnd	SIM
	move.b	1(sp),$ffff8205.w	; (the counter too: the STE's is writable)
	move.b	2(sp),$ffff8207.w
	move.b	3(sp),$ffff8209.w
	endc
	addq.l	#4,sp
	lea	m72r_disp_fine,a0
	move.b	(a0,d0.w),d2
	move.b	d2,$ffff8265.w
	move.b	#(M72_LB-160)/2,d1
	tst.b	d2
	beq	.w
	subq.b	#4,d1
.w:	move.b	d1,$ffff820f.w
	ifd	BD_VSWITCH
	if	BD_VSWITCH
	ext.w	d1			; (borders.s switches to the bar's own screen and back: the playfield's registers)
	move.w	d1,bd_vs_pfl
	ext.w	d2
	move.w	d2,bd_vs_pfh
	move.w	#M72_LB,bd_vs_pfs
	move.w	#M72_LB,bd_vs_bas
	move.w	#(M72_LB-160)/2,bd_vs_bal
	clr.w	bd_vs_bah
	move.w	d0,d1
	lsl.w	#2,d1
	lea	m72r_disp_addr,a0
	move.l	(a0,d1.w),bd_vs_pf
	lea	m72r_disp_bar,a0
	move.l	(a0,d1.w),d2		; the bar's line 0 (its first line)
	lea	m72r_disp_hud,a0
	clr.b	bd_vs_on
	tst.w	(a0,d1.w)		; a top bar: from picture line 0
	bne	.vt
	move.w	2(a0,d1.w),d1		; a bottom bar: from its first line
	cmp.w	#256,d1
	bhs	.vx
	mulu	#M72_LB,d1
	sub.l	d1,d2
.vt:	move.l	d2,bd_vs_bar
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
	move.l	(a0,d0.w),m72r_vbl_htop	; (m72r_vbl_htop, m72r_vbl_hbot)
	movem.l	(sp)+,d0-d2/a0-a1
	rts


; ======================================================================================================================
; video RAM: changes, tile flags, conversion into the layer images
; ======================================================================================================================
; The layer images (m72r_imgf, m72r_imgb): the whole 512 x 512 map of each layer in STE indices, 6 planes of 32 KB:
; plane k (0-3) the index bits, FG plane 4 the opaque pixels (pen != 0; the colour planes are 0 there), FG plane 5 the
; pixels over the sprites (MAME's layer 0: group 1 pens 8-15, groups 2/3 pens 1-15), BG plane 4 the pixels over the
; sprites (group 1 pens 8-15, groups 2/3 pens 1-15), BG plane 5 the pixels drawn over FG's under pixels (group 1 pens
; 8-15, group 3 pens 1-15).  A plane is column-major: word column c (16 pixels) at c * 1024, its 512 lines as consecutive
; words, so a tile's 4 rows of a plane are one movep.l.  A tile is converted when the picture needs it (m72r_validate)
; and its valid bit set; a change of its video RAM entry or of the colour mapping clears the bit.
;
; Tile flags (64 x 64 bits a layer, a row of the map = 8 bytes, bit 7 of byte 0 = column 0), from the pens a tile uses
; and its group: FG ne (any opaque pixel), fo (all opaque), fv (all pixels over the sprites), pri (any), und (any
; opaque pixel under the sprites); BG nn (not neutral: not one pen of index m72r_p0 without over pixels), pri, bod.

F_NE		= 0
F_FO		= 512
F_FV		= 1024
F_PRI		= 1536
F_UND		= 2048
B_NN		= 2560
B_PRI		= 3072
B_BOD		= 3584
V_F		= 4096			; converted
V_B		= 4608
M72_FLSZ	= 5120

; m72r_tiles: the rows of video RAM marked in m72v_vdirty compared with the copy; the changed tiles listed: each its
; flags, its valid bit cleared, the dirty marks of every buffer; more than M72_BULK changes in a picture: the flags of
; both maps again row by row (m72r_bulk), every tile invalid, every buffer drawn again
M72_BULK	= 256
m72r_tiles:
	lea	m72r_chg,a5		; the list: layer.b, tx.b, ty.w
	moveq	#0,d6			; the changes
	moveq	#0,d0			; layer
.lay:	lea	m72v_vdirty,a2
	move.w	d0,d1
	lsl.w	#6,d1
	add.w	d1,a2			; the layer's 64 dirty bytes
	lea	m72v_fg,a3
	lea	m72r_shadow,a4
	tst.w	d0
	beq	.l0
	lea	m72v_bg,a3
	lea	m72r_shadow+$4000,a4
.l0:	moveq	#0,d2			; row
.row:	tst.b	(a2,d2.w)
	beq	.nr
	clr.b	(a2,d2.w)
	move.w	d2,d3
	lsl.w	#8,d3
	lea	(a3,d3.w),a0
	lea	(a4,d3.w),a1
	moveq	#64-1,d4
.cmp:	cmpm.l	(a0)+,(a1)+
	dbne	d4,.cmp
	beq	.nr			; (the row is equal)
	move.l	-4(a0),-4(a1)
	moveq	#63,d1
	sub.w	d4,d1			; tx
	move.w	d2,d3			; its valid bit cleared (byte ty * 8 + tx / 8, bit 7 - tx & 7)
	lsl.w	#3,d3
	move.w	d1,d5
	lsr.w	#3,d5
	add.w	d5,d3
	moveq	#7,d5
	and.w	d1,d5
	eor.w	#7,d5
	lea	m72r_flags+V_F,a6
	tst.w	d0
	beq	.vf
	lea	m72r_flags+V_B,a6
.vf:	bclr	d5,(a6,d3.w)
	lea	m72r_rowchg,a6		; (the row's flags again if this is a mass change)
	move.w	d0,d3
	lsl.w	#6,d3
	add.w	d2,d3
	st	(a6,d3.w)
	lea	m72r_vrchg,a6		; (and for the status bar: its rows changed)
	st	(a6,d3.w)
	addq.w	#1,d6
	cmp.w	#M72_BULK,d6
	bhi	.over
	move.b	d0,(a5)+
	move.b	d1,(a5)+		; tx
	move.w	d2,(a5)+		; ty
.over:	subq.w	#1,d4
	bpl	.cmp
.nr:	addq.w	#1,d2
	cmp.w	#64,d2
	blo	.row
	addq.w	#1,d0
	cmp.w	#2,d0
	blo	.lay
	cmp.w	#M72_BULK,d6
	bhi	.bulk
	lea	m72r_rowchg,a0		; (no mass change: the row marks cleared)
	moveq	#128/4-1,d1
.rc:	clr.l	(a0)+
	dbf	d1,.rc
	; each change
	lea	m72r_chg,a5
	subq.w	#1,d6
	bmi	.x
.ch:	moveq	#0,d0
	move.b	(a5)+,d0
	moveq	#0,d1
	move.b	(a5)+,d1
	move.w	(a5)+,d2
	bsr	m72r_tflags
	movem.l	d6/a5,-(sp)
	bsr	m72r_tchg
	movem.l	(sp)+,d6/a5
	dbf	d6,.ch
.x:	rts
.bulk:	lea	m72r_rowchg,a0		; a mass change (the changed tiles' valid bits are clear): the flags of the
	lea	m72r_bkmark,a1		; changed rows again, M72_BKROWS rows a call (m72r_bulkstep)
	lea	m72r_frver,a2		; (their cached projections are stale)
	moveq	#128-1,d1
.vr:	tst.b	(a0)
	beq	.vn
	clr.b	(a0)
	st	(a1)
	addq.w	#1,(a2)
.vn:	addq.l	#1,a0
	addq.l	#1,a1
	addq.l	#2,a2
	dbf	d1,.vr
	bsr	m72r_bkcount
	st	m72r_vclr
	lea	m72r_bs,a0		; every buffer drawn again
	moveq	#REN_NBUF-1,d1
.b:	move.w	#-1,BS_W(a0)
	lea	BS_SIZE(a0),a0
	dbf	d1,.b
	addq.l	#1,m72r_bulks
	rts

; m72r_bulkstep: the flags of up to M72_BKROWS map rows marked in m72r_bkmark (FG rows 0-63, BG 64-127; m72r_bkpend
; of them left): a mass video RAM change (m72r_tiles .bulk: the changed rows) or a new m72r_p0 (m72r_bgnn: the BG's
; rows) is spread over calls this way, no picture drawn until done
M72_BKROWS	= 16
m72r_bulkstep:
	tst.w	m72r_bkpend
	beq	.r
	movem.l	d0-d3/a0,-(sp)
	moveq	#M72_BKROWS,d2
	lea	m72r_bkmark,a0
	moveq	#0,d3			; FG rows 0-63, BG 64-127
.s:	tst.b	(a0,d3.w)
	beq	.n
	clr.b	(a0,d3.w)
	move.w	d3,d0
	lsr.w	#6,d0
	moveq	#63,d1
	and.w	d3,d1
	bsr	m72r_bulk
	subq.w	#1,m72r_bkpend
	beq	.x
	subq.w	#1,d2
	beq	.x
.n:	addq.w	#1,d3
	cmp.w	#128,d3
	blo	.s
.x:	movem.l	(sp)+,d0-d3/a0
.r:	rts

; m72r_bkcount: m72r_bkpend = the rows marked in m72r_bkmark
m72r_bkcount:
	movem.l	d0-d1/a0,-(sp)
	lea	m72r_bkmark,a0
	moveq	#0,d0
	moveq	#128-1,d1
.c:	tst.b	(a0)+
	beq	.n
	addq.w	#1,d0
.n:	dbf	d1,.c
	move.w	d0,m72r_bkpend
	movem.l	(sp)+,d0-d1/a0
	rts

; m72r_bulk: the flags of map row d1 of layer d0 (a flag byte a tile, then each flag's 64 bits shifted together);
; the BG's count of bod tiles
m72r_bulk:
	movem.l	d0-d7/a0-a6,-(sp)
	move.w	d1,d2			; (the row's tiles in their colour rows' maps)
	moveq	#0,d1
.tr:	bsr	m72r_trow
	addq.w	#1,d1
	cmp.w	#64,d1
	blo	.tr
	move.w	d2,d1
	move.w	d0,m72r_cl
	move.w	d1,d7			; the row
.row:	move.w	d7,-(sp)
	; the flag bytes
	lea	m72v_fg,a0
	lea	m72r_tcf,a1
	move.w	#M72_NTF-1,d6
	lea	m72r_ftab,a2
	tst.w	m72r_cl
	beq	.l
	lea	m72v_bg,a0
	lea	m72r_tcb,a1
	move.w	#M72_NTB-1,d6
	lea	m72r_btab,a2
.l:	move.w	d7,d0
	lsl.w	#8,d0
	add.w	d0,a0			; the row's entries
	lea	m72r_fbytes,a3
	lea	m72r_pidx+256,a4
	moveq	#64-1,d5
.t:	move.b	1(a0),d0		; the code
	lsl.w	#8,d0
	move.b	(a0),d0
	and.w	d6,d0
	move.b	(a1,d0.w),d1		; the class: bits 0-2 pen 0 * 4 + (1-7) * 2 + (8-15), bit 3 one pen, 4-7 that pen
	moveq	#0,d2
	move.b	2(a0),d2		; colour, group
	move.w	d2,d3
	and.w	#$c0,d3
	lsr.w	#3,d3
	moveq	#7,d4
	and.b	d1,d4
	or.w	d4,d3
	move.b	(a2,d3.w),d3		; the flags
	tst.w	m72r_cl
	beq	.st
	bchg	#2,d3			; BG: nn = not "may be neutral" ...
	beq	.st
	btst	#3,d1			; ... unless one pen of index m72r_p0
	beq	.nn
	and.w	#15,d2
	lsl.w	#4,d2
	lsr.b	#4,d1
	add.b	d1,d2
	move.b	(a4,d2.w),d2
	cmp.b	m72r_p0,d2
	beq	.st			; (neutral: nn clear)
.nn:	bset	#2,d3
.st:	move.b	d3,(a3)+
	addq.l	#4,a0
	dbf	d5,.t
	; the flags' bits: two halves of 32 tiles, 5 (FG) / 3 (BG) accumulators
	move.w	(sp),d7
	lsl.w	#3,d7			; the row's byte offset
	lea	m72r_flags,a5
	add.w	d7,a5
	lea	m72r_fbytes,a3
	moveq	#2-1,d6
.half:	moveq	#32-1,d5
.b:	move.b	(a3)+,d7
	lsr.b	#1,d7
	addx.l	d0,d0
	lsr.b	#1,d7
	addx.l	d1,d1
	lsr.b	#1,d7
	addx.l	d2,d2
	lsr.b	#1,d7
	addx.l	d3,d3
	lsr.b	#1,d7
	addx.l	d4,d4
	dbf	d5,.b
	tst.w	m72r_cl
	bne	.hb
	move.l	d0,F_NE(a5)
	move.l	d1,F_FO(a5)
	move.l	d2,F_FV(a5)
	move.l	d3,F_PRI(a5)
	move.l	d4,F_UND(a5)
	bra	.hn
.hb:	move.l	d0,B_PRI(a5)
	move.l	d2,B_NN(a5)
	moveq	#0,d3			; (the bod tiles: the new ones' count less the old ones')
	lea	m72r_pop8,a6
	move.l	B_BOD(a5),d0
	move.l	d1,B_BOD(a5)
	moveq	#4-1,d4
.pc:	rol.l	#8,d1
	moveq	#0,d7
	move.b	d1,d7
	move.b	(a6,d7.w),d7
	add.w	d7,d3
	rol.l	#8,d0
	moveq	#0,d7
	move.b	d0,d7
	move.b	(a6,d7.w),d7
	sub.w	d7,d3
	dbf	d4,.pc
	add.w	d3,m72r_nbod
.hn:	addq.l	#4,a5
	dbf	d6,.half
	move.w	(sp)+,d7
	movem.l	(sp)+,d0-d7/a0-a6
	rts

; m72r_tchg: tile (d0 layer, d1 tx, d2 ty) changed: its valid bit cleared, the buffers' dirty marks
m72r_tchg:
	move.w	d2,d3			; the bit: byte ty * 8 + tx / 8, bit 7 - tx & 7
	lsl.w	#3,d3
	move.w	d1,d4
	lsr.w	#3,d4
	add.w	d4,d3
	moveq	#7,d4
	and.w	d1,d4
	eor.w	#7,d4
	st	m72r_vclr
	lea	m72r_flags+V_F,a0
	move.w	#BS_DIRF,d5
	moveq	#1,d6
	tst.w	d0
	beq	.f
	lea	m72r_flags+V_B,a0
	move.w	#BS_DIRB,d5
	moveq	#2,d6
.f:	bclr	d4,(a0,d3.w)
	lea	m72r_bs,a1
	moveq	#REN_NBUF-1,d7
.b:	lea	(a1,d5.w),a0
	bset	d4,(a0,d3.w)
	or.w	d6,BS_ND(a1)
	lea	BS_SIZE(a1),a1
	dbf	d7,.b
	rts

; m72r_trow: tile (d0 layer, d1 tx, d2 ty) into the map of its colour row (m72r_rowmap: per layer and colour row the
; tiles of that colour, the valid bits' layout; m72r_tcol: each tile's colour as mapped): m72r_cinval finds a row's
; tiles there.  Keeps all registers.
m72r_trow:
	movem.l	d3-d6/a0-a1,-(sp)
	move.w	d0,d3
	lsl.w	#6,d3
	add.w	d2,d3
	lsl.w	#6,d3
	add.w	d1,d3			; layer * 4096 + ty * 64 + tx
	move.w	d2,d4
	lsl.w	#6,d4
	add.w	d1,d4
	lsl.w	#2,d4			; the entry
	lea	m72v_fg,a0
	tst.w	d0
	beq	.f
	lea	m72v_bg,a0
.f:	moveq	#15,d5
	and.b	2(a0,d4.w),d5		; its colour
	lea	m72r_tcol,a1
	moveq	#0,d6
	move.b	(a1,d3.w),d6		; as mapped
	cmp.b	d6,d5
	beq	.x
	move.b	d5,(a1,d3.w)
	move.w	d2,d3			; the bit: byte ty * 8 + tx / 8, bit 7 - tx & 7
	lsl.w	#3,d3
	move.w	d1,d4
	lsr.w	#3,d4
	add.w	d4,d3
	moveq	#7,d4
	and.w	d1,d4
	eor.w	#7,d4
	lea	m72r_rowmap,a0
	tst.w	d0
	beq	.l
	lea	16*512(a0),a0
.l:	lsl.w	#8,d6
	add.w	d6,d6
	add.w	d3,d6
	bclr	d4,(a0,d6.w)
	lsl.w	#8,d5
	add.w	d5,d5
	add.w	d3,d5
	bset	d4,(a0,d5.w)
.x:	movem.l	(sp)+,d3-d6/a0-a1
	rts

; m72r_tflags: the flags of tile (d0 layer, d1 tx, d2 ty) from its entry (the pens it uses: pen 0, any of 1-7, any of
; 8-15; its group; BG nn also from the colour mapping); keeps all registers
m72r_tflags:
	bsr	m72r_trow
	movem.l	d0-d6/a0-a2,-(sp)
	move.w	d2,d3
	lsl.w	#6,d3
	add.w	d1,d3
	lsl.w	#2,d3
	lea	m72v_fg,a0
	lea	m72r_uf,a1
	move.w	#M72_NTF-1,d6
	lea	m72r_frver,a2
	tst.w	d0
	beq	.l
	lea	m72v_bg,a0
	lea	m72r_ub,a1
	move.w	#M72_NTB-1,d6
	lea	m72r_brver,a2
.l:	move.w	d2,d4			; (the row's version: the cached projections of the row are stale)
	add.w	d4,d4
	addq.w	#1,(a2,d4.w)
	add.w	d3,a0
	move.b	1(a0),d5		; the code
	lsl.w	#8,d5
	move.b	(a0),d5
	and.w	d6,d5
	add.w	d5,d5
	move.w	(a1,d5.w),d5		; the pens it uses
	moveq	#0,d6
	move.b	2(a0),d6		; colour, group
	; the table index: group * 8 + pen 0 * 4 + (1-7) * 2 + (8-15)
	move.w	d6,d4
	and.w	#$c0,d4
	lsr.w	#3,d4
	btst	#0,d5
	beq	.i0
	addq.w	#4,d4
.i0:	move.b	d5,d3
	and.b	#$fe,d3
	beq	.i1
	addq.w	#2,d4
.i1:	move.w	d5,d3
	and.w	#$ff00,d3
	beq	.i2
	addq.w	#1,d4
.i2:	lea	m72r_ftab,a0
	tst.w	d0
	beq	.i3
	lea	m72r_btab,a0
.i3:	move.b	(a0,d4.w),d4		; the flags (bit 0 F_NE .. or B_PRI B_BOD B_NN)
	; the bit: byte ty * 8 + tx / 8, bit 7 - tx & 7
	move.w	d2,d3
	lsl.w	#3,d3
	move.w	d1,d0
	lsr.w	#3,d0
	add.w	d0,d3
	lea	m72r_flags,a2
	add.w	d3,a2
	moveq	#7,d3
	and.w	d1,d3
	eor.w	#7,d3
	tst.w	2(sp)			; (the layer: the saved d0's low word)
	bne	.bg
	moveq	#5-1,d1			; FG: F_NE F_FO F_FV F_PRI F_UND, 512 bytes apart
.f:	lsr.b	#1,d4
	bcc	.fc
	bset	d3,(a2)
	bra	.fn
.fc:	bclr	d3,(a2)
.fn:	lea	512(a2),a2
	dbf	d1,.f
	movem.l	(sp)+,d0-d6/a0-a2
	rts
.bg:	lea	B_PRI(a2),a2		; BG: B_PRI, B_BOD (with the count of bod tiles), B_NN
	lsr.b	#1,d4
	bcc	.b1
	bset	d3,(a2)
	bra	.b2
.b1:	bclr	d3,(a2)
.b2:	btst	d3,512(a2)		; bod
	sne	d1
	lsr.b	#1,d4
	scs	d2
	cmp.b	d1,d2
	beq	.b4
	tst.b	d2
	beq	.b3
	addq.w	#1,m72r_nbod
	bset	d3,512(a2)
	bra	.b4
.b3:	subq.w	#1,m72r_nbod
	bclr	d3,512(a2)
.b4:	; nn: not neutral unless one pen, no over pixel, the index m72r_p0
	lsr.b	#1,d4			; (the table: may be neutral)
	bcc	.nn1
	tst.w	d5
	beq	.nn1
	move.w	d5,d1
	move.w	d5,d2
	subq.w	#1,d2
	and.w	d2,d1
	bne	.nn1			; (more than one pen)
	moveq	#-1,d2			; the pen: the bit's number
.pn:	addq.w	#1,d2
	lsr.w	#1,d5
	bcc	.pn
	and.w	#15,d6			; the colour
	lsl.w	#4,d6
	add.w	d2,d6
	lea	m72r_pidx+256,a1
	move.b	(a1,d6.w),d2
	cmp.b	m72r_p0,d2
	bne	.nn1
	bclr	d3,B_NN-B_PRI(a2)
	movem.l	(sp)+,d0-d6/a0-a2
	rts
.nn1:	bset	d3,B_NN-B_PRI(a2)
	movem.l	(sp)+,d0-d6/a0-a2
	rts

; the flag tables, by group * 8 + pen 0 * 4 + (pens 1-7) * 2 + (pens 8-15)
; FG bits: 0 ne, 1 fo (all opaque), 2 fv (all over), 3 pri (any over), 4 und (any opaque under)
; BG bits: 0 pri, 1 bod, 2 may be neutral (no over pixel; the pen and its index are checked)
m72r_ftab:
FT	macro	; \1 group, the 8 combinations
FTG	set	\1
FTI	set	0
	rept	8
FTP0	set	(FTI>>2)&1
FTLO	set	(FTI>>1)&1
FTHI	set	FTI&1
FTNE	set	FTLO|FTHI
FTFO	set	1-FTP0
	if	FTG=0
FTFV	set	0
FTPR	set	0
FTUN	set	FTNE
	endc
	if	FTG=1
FTFV	set	(1-FTP0)*(1-FTLO)
FTPR	set	FTHI
FTUN	set	FTLO
	endc
	if	FTG>=2
FTFV	set	1-FTP0
FTPR	set	FTNE
FTUN	set	0
	endc
	dc.b	FTNE|(FTFO<<1)|(FTFV<<2)|(FTPR<<3)|(FTUN<<4)
FTI	set	FTI+1
	endr
	endm
	FT	0
	FT	1
	FT	2
	FT	3
m72r_btab:
BT	macro
BTG	set	\1
BTI	set	0
	rept	8
BTLO	set	(BTI>>1)&1
BTHI	set	BTI&1
	if	BTG=0
BTPR	set	0
BTBD	set	0
	endc
	if	BTG=1
BTPR	set	BTHI
BTBD	set	BTHI
	endc
	if	BTG=2
BTPR	set	BTLO|BTHI
BTBD	set	0
	endc
	if	BTG=3
BTPR	set	BTLO|BTHI
BTBD	set	BTLO|BTHI
	endc
	dc.b	BTPR|(BTBD<<1)|((1-BTPR)<<2)
BTI	set	BTI+1
	endr
	endm
	BT	0
	BT	1
	BT	2
	BT	3
	even

; m72r_bgnn: the BG nn bits of the whole map again (a new mapping or m72r_p0): a tile is neutral when it has one pen,
; no pixel over the sprites (its table entry's "may be neutral"), and that pen's index is m72r_p0
m72r_bgnn:
	; the B_NN bits of every BG tile again: the BG's flags recomputed, M72_BKROWS rows a call (m72r_bulkstep)
	lea	m72r_brver,a0		; (the cached projections are stale)
	moveq	#64-1,d1
.v:	addq.w	#1,(a0)+
	dbf	d1,.v
	lea	m72r_bkmark+64,a0
	moveq	#64/4-1,d1
.m:	move.l	#-1,(a0)+
	dbf	d1,.m
	bra	m72r_bkcount

; m72r_conv: tile (d0 layer, d1 tx, d2 ty) into its layer image; sets its valid bit.  Keeps d0-d2.
; The minterms: per opaque pen p the pixels of that pen (the AND of the 4 bit planes or their complements, rows as bytes,
; 4 rows a long), ORed into the index planes its index sets.
m72r_conv:
	addq.l	#1,m72r_nconv
	movem.l	d0-d7/a0-a6,-(sp)
	move.w	d0,m72r_cl
	move.w	d2,d3
	lsl.w	#6,d3
	add.w	d1,d3
	lsl.w	#2,d3
	lea	m72v_fg,a0
	lea	m72r_tf,a1
	lea	m72r_uf,a2
	move.w	#M72_NTF-1,d7
	tst.w	d0
	beq	.l
	lea	m72v_bg,a0
	lea	m72r_tb,a1
	lea	m72r_ub,a2
	move.w	#M72_NTB-1,d7
.l:	add.w	d3,a0
	moveq	#0,d5
	move.b	1(a0),d5		; the code
	lsl.w	#8,d5
	move.b	(a0),d5
	move.w	d5,d6			; (flips: bits 14, 15)
	and.w	d7,d5
	move.l	d5,d4
	add.w	d4,d4
	move.w	(a2,d4.l),m72r_cpens	; the pens it uses
	move.w	d5,m72r_ctile
	lsl.l	#5,d5
	add.l	d5,a1			; its bit planes
	moveq	#0,d4
	move.b	2(a0),d4		; colour, group
	move.w	d4,m72r_cattr
	movem.l	d3-d4/a3,-(sp)	; (its pens in use from now on: m72r_suse; new ones for m72r_sdiv)
	and.w	#15,d4
	add.w	d4,d4
	lea	m72r_suse+32,a3
	add.w	d4,a3
	move.w	m72r_cpens,d4
	tst.w	d0
	bne	.ub
	and.w	#$fffe,d4		; (FG pen 0: transparent)
.ub:	move.w	(a3),d3
	not.w	d3
	and.w	d3,d4			; (the new ones)
	beq	.uo
	or.w	d4,(a3)
	st	m72r_divp
	movem.l	d2-d3,-(sp)
	move.w	d4,d2
	moveq	#15,d3
	and.b	m72r_cattr+1,d3
	add.w	#16,d3
	lsl.w	#4,d3
	bsr	m72r_pnew
	movem.l	(sp)+,d2-d3
.uo:	movem.l	(sp)+,d3-d4/a3
	; the mapping row of the colour: tiles are pens 256-511
	and.w	#15,d4
	lsl.w	#4,d4
	moveq	#0,d3			; (the HUD mapping: none, the bar is drawn by m72r_bartile)
	lea	m72r_pidx+256,a4
	add.w	d4,a4
	; the destination: column tx / 2, line ty * 8, byte tx & 1
	lea	m72r_imgf,a5
	tst.w	d0
	beq	.dd
	lea	m72r_imgb,a5
.dd:	moveq	#0,d4
	move.w	d1,d4
	lsr.w	#1,d4
	moveq	#10,d5
	lsl.l	d5,d4
	add.l	d4,a5
	move.w	d2,d4
	lsl.w	#4,d4
	add.w	d4,a5
	moveq	#1,d4
	and.w	d1,d4
	add.w	d4,a5
	; the conversion cache (direct mapped): key = layer, HUD mapping, group, colour; flips, tile; and the epoch
	move.b	m72r_cattr+1,d4
	and.w	#$cf,d4
	move.w	d0,d5
	lsl.w	#5,d5
	or.w	d5,d4
	lsl.w	#4,d3
	or.w	d3,d4
	swap	d4
	move.w	d6,d4
	and.w	#$c000,d4
	or.w	m72r_ctile,d4		; the key
	move.w	m72r_ctile,d5		; the slot
	move.w	d4,d3
	swap	d3
	lsl.w	#3,d3
	eor.w	d3,d5
	move.w	d6,d3
	lsr.w	#3,d3
	eor.w	d3,d5
	and.w	#M72_CCN-1,d5
	mulu	#M72_CCS,d5
	lea	m72r_cc_slots,a6
	add.l	d5,a6
	move.l	a6,m72r_ccslot
	moveq	#15,d5			; (the epoch: the choice's + its colour row's remaps, m72r_pdiv)
	and.b	m72r_cattr+1,d5
	add.w	d5,d5
	lea	m72r_cver,a0
	move.w	(a0,d5.w),d5
	add.w	m72r_epoch,d5
	move.w	d5,m72r_cepk
	cmp.l	(a6),d4
	bne	.cmiss
	cmp.w	4(a6),d5
	bne	.cmiss
	; a hit: the 12 longs into the image
	lea	8(a6),a6
	bsr	.put6
	addq.l	#8,a5
	bsr	.put6
	bra	.valid
.put6:	move.l	a5,a0
	moveq	#6-1,d3
.p6:	move.l	(a6)+,d4
	movep.l	d4,0(a0)
	add.l	#M72_PL,a0
	dbf	d3,.p6
	rts
.cmiss:	addq.l	#1,m72r_nmiss
	move.l	d4,(a6)			; (this tile's from now on)
	move.w	m72r_cepk,4(a6)
	lea	8(a6),a6
	move.l	a6,m72r_ccdat
	; the 8 longs (plane b: rows 0-3, rows 4-7) into the X tables (half 0: m72r_xt, half 1: m72r_xt+32), flipped
	lea	m72r_xt,a2
	lea	m72r_rev8,a3
	moveq	#4-1,d7
.ld:	move.l	(a1)+,d4		; rows 0-3
	move.l	(a1)+,d5		; rows 4-7
	btst	#14,d6
	beq	.nx
	moveq	#4-1,d3			; flip x: each byte reversed
.fx:	moveq	#0,d0
	rol.l	#8,d4
	move.b	d4,d0
	move.b	(a3,d0.w),d4
	moveq	#0,d0
	rol.l	#8,d5
	move.b	d5,d0
	move.b	(a3,d0.w),d5
	dbf	d3,.fx
.nx:	btst	#15,d6
	beq	.ny
	exg	d4,d5			; flip y: the rows reversed
	ror.w	#8,d4
	swap	d4
	ror.w	#8,d4
	ror.w	#8,d5
	swap	d5
	ror.w	#8,d5
.ny:	move.l	d4,(a2)
	not.l	d4
	move.l	d4,4(a2)
	move.l	d5,32(a2)
	not.l	d5
	move.l	d5,36(a2)
	addq.l	#8,a2
	dbf	d7,.ld
	lea	m72r_xt,a2
	bsr	.half
	lea	m72r_xt+32,a2
	addq.l	#8,a5
	bsr	.half
	; valid
.valid:	movem.l	(sp),d0-d2
	move.w	d2,d3
	lsl.w	#3,d3
	move.w	d1,d4
	lsr.w	#3,d4
	add.w	d4,d3
	moveq	#7,d4
	and.w	d1,d4
	eor.w	#7,d4
	lea	m72r_flags+V_F,a0
	tst.w	d0
	beq	.v
	lea	m72r_flags+V_B,a0
.v:	bset	d4,(a0,d3.w)
	movem.l	(sp)+,d0-d7/a0-a6
	rts
; one half (4 rows): a2 = its X table, a4 = the mapping row, a5 = the destination
.half:	moveq	#0,d0
	moveq	#0,d1
	moveq	#0,d2
	moveq	#0,d3
	move.w	m72r_cpens,d6
	tst.w	m72r_cl
	bne	.h0
	and.w	#$fffe,d6		; (FG: pen 0 is transparent)
.h0:	lea	m72r_moff,a3
	moveq	#0,d7			; the pen
.pen:	lsr.w	#1,d6
	bcc	.np
	move.l	a3,a6
	moveq	#0,d5
	move.b	(a6)+,d5
	move.l	(a2,d5.w),d4
	move.b	(a6)+,d5
	and.l	(a2,d5.w),d4
	move.b	(a6)+,d5
	and.l	(a2,d5.w),d4
	move.b	(a6)+,d5
	and.l	(a2,d5.w),d4
	move.b	(a4,d7.w),d5		; its index
	lsr.b	#1,d5
	bcc	.o1
	or.l	d4,d0
.o1:	lsr.b	#1,d5
	bcc	.o2
	or.l	d4,d1
.o2:	lsr.b	#1,d5
	bcc	.o3
	or.l	d4,d2
.o3:	lsr.b	#1,d5
	bcc	.np
	or.l	d4,d3
.np:	addq.l	#4,a3
	addq.w	#1,d7
	tst.w	d6
	bne	.pen
	move.l	m72r_ccdat,a6		; (into the cache)
	movem.l	d0-d3,(a6)
	add.l	#16,m72r_ccdat
	move.l	a5,a6
	movep.l	d0,0(a6)
	add.l	#M72_PL,a6
	movep.l	d1,0(a6)
	add.l	#M72_PL,a6
	movep.l	d2,0(a6)
	add.l	#M72_PL,a6
	movep.l	d3,0(a6)
	add.l	#M72_PL,a6
	; the masks: opaque = not pen 0 (the complement of pen 0's minterm), b3 = pens 8-15
	moveq	#-1,d0
	btst	#0,m72r_cpens+1
	beq	.m0
	move.l	4(a2),d0		; ~b0 & ~b1 & ~b2 & ~b3: pen 0
	and.l	12(a2),d0
	and.l	20(a2),d0
	and.l	28(a2),d0
	not.l	d0
.m0:	move.l	24(a2),d1		; b3
	moveq	#0,d2
	move.b	m72r_cattr+1,d2
	lsr.b	#6,d2			; the group
	tst.w	m72r_cl
	bne	.mb
	movep.l	d0,0(a6)		; FG plane 4: opaque
	add.l	#M72_PL,a6
	moveq	#0,d3			; plane 5: over
	cmp.b	#1,d2
	blo	.f5
	bne	.f523
	move.l	d1,d3
	bra	.f5
.f523:	move.l	d0,d3
.f5:	movep.l	d3,0(a6)
	move.l	m72r_ccdat,a6
	move.l	d0,(a6)+
	move.l	d3,(a6)+
	move.l	a6,m72r_ccdat
	rts
.mb:	moveq	#0,d3			; BG plane 4: over
	moveq	#0,d4			; plane 5: drawn over FG's under pixels
	cmp.b	#1,d2
	blo	.b5
	bne	.b23
	move.l	d1,d3
	move.l	d1,d4
	bra	.b5
.b23:	move.l	d0,d3
	cmp.b	#3,d2
	bne	.b5
	move.l	d0,d4
.b5:	movep.l	d3,0(a6)
	add.l	#M72_PL,a6
	movep.l	d4,0(a6)
	move.l	m72r_ccdat,a6
	move.l	d3,(a6)+
	move.l	d4,(a6)+
	move.l	a6,m72r_ccdat
	rts

; ======================================================================================================================
; projections: a layer's tile bits over a run of lines, as bits of the buffer's cell columns (mod 64)
; ======================================================================================================================
; m72r_proj_or / m72r_proj_and: in a0 = 64 x 64 bits, d4 = map x of buffer x 0 (0-511), d5 = map y of picture line 0,
; d6 = first line, d7 = last line + 1 (at most 8 lines: 1 or 2 map rows); out d0:d1 = bit c (MSB first) for buffer cell
; c (mod 64): the OR / AND of the bits of the tiles under it.  Destroys d2, d3.
m72r_proj_or:
	movem.l	d6-d7,-(sp)
	add.w	d5,d6
	and.w	#511,d6
	lsr.w	#3,d6
	lsl.w	#3,d6
	move.l	(a0,d6.w),d0
	move.l	4(a0,d6.w),d1
	subq.w	#1,d7
	add.w	d5,d7
	and.w	#511,d7
	lsr.w	#3,d7
	lsl.w	#3,d7
	cmp.w	d6,d7
	beq	.one
	or.l	(a0,d7.w),d0
	or.l	4(a0,d7.w),d1
.one:	moveq	#7,d2
	and.w	d4,d2
	beq	.al
	move.l	d0,d6			; and the tile to the right
	move.l	d1,d7
	add.l	d7,d7
	addx.l	d6,d6
	moveq	#0,d2
	addx.l	d2,d2
	or.l	d2,d7
	or.l	d6,d0
	or.l	d7,d1
.al:	bra	m72r_rol
m72r_proj_and:
	movem.l	d6-d7,-(sp)
	add.w	d5,d6
	and.w	#511,d6
	lsr.w	#3,d6
	lsl.w	#3,d6
	move.l	(a0,d6.w),d0
	move.l	4(a0,d6.w),d1
	subq.w	#1,d7
	add.w	d5,d7
	and.w	#511,d7
	lsr.w	#3,d7
	lsl.w	#3,d7
	cmp.w	d6,d7
	beq	.one
	and.l	(a0,d7.w),d0
	and.l	4(a0,d7.w),d1
.one:	moveq	#7,d2
	and.w	d4,d2
	beq	m72r_rol
	move.l	d0,d6
	move.l	d1,d7
	add.l	d7,d7
	addx.l	d6,d6
	moveq	#0,d2
	addx.l	d2,d2
	or.l	d2,d7
	and.l	d6,d0
	and.l	d7,d1
; rotate d0:d1 left by d4 / 8 (tile c + k to cell c); pops d6-d7
m72r_rol:
	move.w	d4,d2
	lsr.w	#3,d2
	btst	#5,d2
	beq	.lo
	exg	d0,d1
.lo:	and.w	#31,d2
	beq	.done
	moveq	#32,d3
	sub.w	d2,d3
	move.l	d0,d6
	move.l	d1,d7
	lsl.l	d2,d0
	lsl.l	d2,d1
	lsr.l	d3,d6
	lsr.l	d3,d7
	or.l	d7,d0
	or.l	d6,d1
.done:	movem.l	(sp)+,d6-d7
	rts

; ======================================================================================================================
; the bands, the window
; ======================================================================================================================
; m72r_bands: m72v_bands -> m72r_bt (the offsets relative to the buffer of this picture) and m72r_W
m72r_bands:
	move.l	m72r_cbs,a5
	move.w	m72v_nbands,d7
	bne	.n1
	moveq	#1,d7
.n1:	cmp.w	#8,d7
	bls	.n2
	moveq	#8,d7
.n2:	; the main band (the most lines) and the followed layer's x scroll there
	lea	m72v_bands,a0
	moveq	#0,d0			; band
	moveq	#-1,d5			; the most lines
	moveq	#0,d6			; its scroll
.mb:	move.w	d0,d1
	mulu	#12,d1
	move.w	(a0,d1.w),d2		; first line
	move.w	#256,d3
	move.w	d0,d4
	addq.w	#1,d4
	cmp.w	d7,d4
	bhs	.last
	move.w	12(a0,d1.w),d3
.last:	sub.w	d2,d3
	cmp.w	d5,d3
	ble	.mn
	move.w	d3,d5
	move.w	4(a0,d1.w),d6		; FG x
	tst.w	m72r_follow
	beq	.mn
	move.w	8(a0,d1.w),d6		; BG x
.mn:	addq.w	#1,d0
	cmp.w	d7,d0
	blo	.mb
	; W: the followed layer's map x of picture x 0 (96 + scroll) mod 512, or that + 512 when it is nearer the buffer's
	; last window (the window may run to 704: 704 + 320 = 1024)
	add.w	#96,d6
	and.w	#511,d6
	move.w	BS_W(a5),d1
	bmi	.w
	cmp.w	#704-512,d6
	bhi	.w
	move.w	d6,d2
	sub.w	d1,d2
	bpl	.a1
	neg.w	d2
.a1:	move.w	d6,d3
	add.w	#512,d3
	sub.w	d1,d3
	bpl	.a2
	neg.w	d3
.a2:	cmp.w	d2,d3
	bhs	.w
	add.w	#512,d6
.w:	move.w	d6,m72r_W
	; the table
	lea	m72r_bt,a1
	moveq	#0,d0
	moveq	#0,d5			; bands kept
.bt:	move.w	d0,d1
	mulu	#12,d1
	move.w	(a0,d1.w),d2		; y0
	move.w	#256,d3
	move.w	d0,d4
	addq.w	#1,d4
	cmp.w	d7,d4
	bhs	.l2
	move.w	12(a0,d1.w),d3
.l2:	tst.w	d0
	bne	.y0
	moveq	#0,d2			; (band 0 from line 0)
.y0:	cmp.w	#256,d3
	bls	.y1
	move.w	#256,d3
.y1:	cmp.w	d3,d2
	bhs	.skip
	move.w	d2,BT_Y0(a1)
	move.w	d3,BT_Y1(a1)
	move.w	4(a0,d1.w),d2		; FG x
	move.w	d2,BT_SXF(a1)
	add.w	#96,d2
	sub.w	m72r_W,d2
	and.w	#511,d2
	move.w	d2,BT_OXF(a1)
	move.w	2(a0,d1.w),d2		; FG y
	add.w	#128,d2
	and.w	#511,d2
	move.w	d2,BT_OYF(a1)
	move.w	8(a0,d1.w),d2		; BG x
	add.w	#96,d2
	sub.w	m72r_W,d2
	and.w	#511,d2
	move.w	d2,BT_OXB(a1)
	move.w	6(a0,d1.w),d2		; BG y
	add.w	#128,d2
	and.w	#511,d2
	move.w	d2,BT_OYB(a1)
	moveq	#1,d2
	and.w	10(a0,d1.w),d2
	move.w	d2,BT_OFF(a1)
	lea	16(a1),a1
	addq.w	#1,d5
.skip:	addq.w	#1,d0
	cmp.w	d7,d0
	blo	.bt
	move.w	d5,m72r_nb
	; the window's cells (128 bits) and the clip groups
	lea	m72r_win,a0
	move.w	m72r_W,d0
	move.w	d0,d1
	lsr.w	#3,d0			; first cell
	add.w	#319,d1
	lsr.w	#3,d1			; last cell
	bsr	m72r_cellmask
	move.w	d0,d2			; the window's longs: first, count - 1
	lsr.w	#5,d2
	move.w	d2,m72r_wl0
	move.w	d1,d3
	lsr.w	#5,d3
	sub.w	d2,d3
	move.w	d3,m72r_wln
	move.l	(a0),d0			; (mod 64)
	or.l	8(a0),d0
	move.l	d0,m72r_win64
	move.l	4(a0),d0
	or.l	12(a0),d0
	move.l	d0,m72r_win64+4
	; the band of each line
	lea	m72r_bt,a1
	lea	m72r_lband,a0
	moveq	#0,d0
	move.w	m72r_nb,d2
	subq.w	#1,d2
.lb:	move.w	BT_Y0(a1),d1
	move.w	BT_Y1(a1),d3
.lb1:	cmp.w	d3,d1
	bhs	.lb2
	move.b	d0,(a0,d1.w)
	addq.w	#1,d1
	bra	.lb1
.lb2:	lea	16(a1),a1
	addq.w	#1,d0
	dbf	d2,.lb
	rts

; m72r_follow_check: which layer the window follows (W = its x scroll): the one that leaves fewer cells to draw again.
; Each picture notes the moves of the main band (FG y, BG y, BG x against FG x); every 8 pictures the cells each layer
; contributes in the window (BS_FDEP / BS_BDEP of this buffer) give the estimates: following FG, BG's cells count when
; BG moved against FG (x) or in y, FG's when FG moved in y; following BG the other way round.  The other layer is
; followed when its estimate is below 5/8 of the current one twice in a row (the switch draws every buffer again).
m72r_follow_check:
	movem.l	d0-d7/a0-a2,-(sp)
	; the main band's scrolls
	lea	m72r_bt,a0
	move.w	m72r_nb,d7
	subq.w	#1,d7
	moveq	#-1,d6
	move.l	a0,a1
.mb:	move.w	BT_Y1(a0),d0
	sub.w	BT_Y0(a0),d0
	cmp.w	d6,d0
	ble	.mn
	move.w	d0,d6
	move.l	a0,a1
.mn:	lea	16(a0),a0
	dbf	d7,.mb
	lea	m72r_mv,a2		; (counters: relative x, FG y, BG y)
	move.w	BT_OXB(a1),d0
	sub.w	BT_OXF(a1),d0
	and.w	#511,d0			; BG x against FG x
	cmp.w	m72r_last,d0
	beq	.m1
	move.b	#8,(a2)
.m1:	move.w	d0,m72r_last
	move.w	BT_OYF(a1),d0
	cmp.w	m72r_last+2,d0
	beq	.m2
	move.b	#8,1(a2)
.m2:	move.w	d0,m72r_last+2
	move.w	BT_OYB(a1),d0
	cmp.w	m72r_last+4,d0
	beq	.m3
	move.b	#8,2(a2)
.m3:	move.w	d0,m72r_last+4
	moveq	#3-1,d0
.dc:	tst.b	(a2)
	beq	.dn
	subq.b	#1,(a2)
.dn:	addq.l	#1,a2
	dbf	d0,.dc
	addq.w	#1,m72r_fcount
	moveq	#7,d0
	and.w	m72r_fcount,d0
	bne	.x
	; the contributions in the window
	move.l	m72r_cbs,a0
	lea	BS_FDEP(a0),a1
	bsr	.count
	move.w	d5,-(sp)		; FG cells
	lea	BS_BDEP(a0),a1
	bsr	.count			; d5: BG cells
	move.w	(sp)+,d6
	lea	m72r_mv,a2
	moveq	#0,d0			; following FG
	moveq	#0,d1			; following BG
	move.b	(a2),d2			; (relative x moved)
	or.b	2(a2),d2		; BG moves in the buffer when following FG
	beq	.e1
	add.w	d5,d0
.e1:	tst.b	1(a2)
	beq	.e2
	add.w	d6,d0
.e2:	move.b	(a2),d2
	or.b	1(a2),d2		; FG moves when following BG
	beq	.e3
	add.w	d6,d1
.e3:	tst.b	2(a2)
	beq	.e4
	add.w	d5,d1
.e4:	tst.w	m72r_follow		; the current one d0, the other d1
	beq	.cmp
	exg	d0,d1
.cmp:	mulu	#5,d0
	lsl.w	#3,d1
	cmp.w	d0,d1
	bhs	.no
	addq.b	#1,m72r_fvote
	cmp.b	#2,m72r_fvote
	blo	.x
	eor.w	#1,m72r_follow		; switch
	addq.l	#1,m72r_switches
.no:	clr.b	m72r_fvote
.x:	movem.l	(sp)+,d0-d7/a0-a2
	rts
; d5 = the set bits of 32 rows of 64 bits (a1) within the window's columns (m72r_win64)
.count:	moveq	#0,d5
	lea	m72r_pop8,a2
	movem.l	m72r_win64,d3-d4
	moveq	#32-1,d7
.cr:	move.l	(a1)+,d0
	and.l	d3,d0
	move.l	(a1)+,d1
	and.l	d4,d1
	moveq	#4-1,d2
.cb:	rol.l	#8,d0
	moveq	#0,d6
	move.b	d0,d6
	move.b	(a2,d6.w),d6
	add.w	d6,d5
	rol.l	#8,d1
	moveq	#0,d6
	move.b	d1,d6
	move.b	(a2,d6.w),d6
	add.w	d6,d5
	dbf	d2,.cb
	dbf	d7,.cr
	rts

; m72r_cellmask: (a0) 16 bytes = cells d0 .. d1 (0-127) set, others clear (keeps all but the 16 bytes)
m72r_cellmask:
	movem.l	d2-d5/a0,-(sp)
	moveq	#0,d2			; the long's first cell
.l:	moveq	#0,d5
	move.w	d0,d3			; a = max(d0, first)
	cmp.w	d2,d3
	bge	.a
	move.w	d2,d3
.a:	move.w	d2,d4			; b = min(d1, first + 31)
	add.w	#31,d4
	cmp.w	d1,d4
	ble	.b
	move.w	d1,d4
.b:	cmp.w	d4,d3
	bgt	.s			; (none in this long)
	moveq	#-1,d5
	sub.w	d2,d3
	lsr.l	d3,d5			; from a
	sub.w	d2,d4
	eor.w	#31,d4
	moveq	#-1,d3
	lsl.l	d4,d3			; to b
	and.l	d3,d5
.s:	move.l	d5,(a0)+
	add.w	#32,d2
	cmp.w	#128,d2
	blo	.l
	movem.l	(sp)+,d2-d5/a0
	rts

; ======================================================================================================================
; m72r_validate: the tiles the window's cells show converted (a tile is converted when it is first needed: after a new
; colour choice the window's at once, the others as they scroll in)
; ======================================================================================================================
m72r_validate:
	movem.l	d0-d7/a0-a4,-(sp)
	move.w	#M72_CBUDGET,m72r_budget
	clr.b	m72r_late
	tst.b	m72r_vclr		; (nothing invalidated, the same window and bands: nothing to convert)
	bne	.go
	move.w	m72r_W,d0
	cmp.w	m72r_vW,d0
	bne	.go
	move.w	m72r_nb,d0
	cmp.w	m72r_vnb,d0
	bne	.go
	lea	m72r_bt,a0
	lea	m72r_vbt,a1
	moveq	#128/4-1,d0
.cmp:	cmpm.l	(a0)+,(a1)+
	dbne	d0,.cmp
	bne	.go
	movem.l	(sp)+,d0-d7/a0-a4
	rts
.go:	clr.b	m72r_vclr
	move.w	m72r_W,m72r_vW
	move.w	m72r_nb,m72r_vnb
	lea	m72r_bt,a0
	lea	m72r_vbt,a1
	moveq	#128/4-1,d0
.cp:	move.l	(a0)+,(a1)+
	dbf	d0,.cp
	lea	m72r_bt,a4
	move.w	m72r_nb,d7
	subq.w	#1,d7
.band:	tst.w	BT_OFF(a4)
	bne	.nb
	clr.w	m72r_vlay		; FG
	move.w	BT_OXF(a4),d4
	move.w	BT_OYF(a4),d5
	bsr	.lay
	move.w	#1,m72r_vlay		; BG
	move.w	BT_OXB(a4),d4
	move.w	BT_OYB(a4),d5
	bsr	.lay
.nb:	tst.b	m72r_late
	bne	.late
	lea	16(a4),a4
	dbf	d7,.band
	movem.l	(sp)+,d0-d7/a0-a4
	rts
.late:	st	m72r_vclr		; (validate again next time)
	movem.l	(sp)+,d0-d7/a0-a4
	rts
; layer d0 at d4 (map x of buffer x 0), d5 (map y of line 0) in band a4's lines
.lay:	movem.l	d4-d7/a4,-(sp)
	; the columns (64 bits, MSB = column 0): the window's cells
	move.w	m72r_W,d1
	move.w	d1,d2
	add.w	#319,d2
	and.w	#$fff8,d1
	or.w	#7,d2
	sub.w	d1,d2			; the cells' pixels - 1
	add.w	d4,d1
	and.w	#511,d1
	add.w	d1,d2
	lsr.w	#3,d1			; first column
	lsr.w	#3,d2			; last (unwrapped)
	sub.w	d1,d2
	addq.w	#1,d2			; columns (at most 42)
	moveq	#-1,d4			; the mask: d2 ones from the left, rotated right by the first column
	moveq	#-1,d5
	moveq	#64,d3
	sub.w	d2,d3			; zeros at the right
	cmp.w	#32,d3
	blo	.z1
	moveq	#0,d5
	sub.w	#32,d3
	lsl.l	d3,d4
	bra	.z2
.z1:	lsl.l	d3,d5
.z2:	moveq	#64,d3			; rotate right by d1 = left by 64 - d1
	sub.w	d1,d3
	and.w	#63,d3
	btst	#5,d3
	beq	.r1
	exg	d4,d5
.r1:	and.w	#31,d3
	beq	.r2
	moveq	#32,d6
	sub.w	d3,d6
	move.l	d4,d0
	move.l	d5,d7
	lsl.l	d3,d4
	lsl.l	d3,d5
	lsr.l	d6,d0
	lsr.l	d6,d7
	or.l	d7,d4
	or.l	d0,d5
.r2:	movem.l	d4-d5,m72r_vmask
	movem.l	(sp),d4-d5		; (the offsets again)
	moveq	#0,d0			; (the layer: from the caller's d0, saved below)
	move.w	m72r_vlay,d0
	; the rows
	move.w	BT_Y0(a4),d2
	add.w	d5,d2
	move.w	BT_Y1(a4),d3
	subq.w	#1,d3
	add.w	d5,d3
	lsr.w	#3,d2
	lsr.w	#3,d3
	sub.w	d2,d3			; rows - 1
	lea	m72r_flags+V_F,a0
	tst.w	d0
	beq	.r0
	lea	m72r_flags+V_B,a0
.r0:
.row:	move.w	d2,d6
	and.w	#63,d6
	lsl.w	#3,d6
	movem.l	(a0,d6.w),d4-d5		; the row's valid bits
	not.l	d4
	not.l	d5
	and.l	m72r_vmask,d4
	and.l	m72r_vmask+4,d5
	move.l	d4,d6
	or.l	d5,d6
	beq	.rn			; (all converted)
	move.w	d2,-(sp)
	and.w	#63,d2
	movem.l	d3/a0,-(sp)
	lea	m72r_lz8,a0
.c:	; the first column still to convert: the leading zeros of d4:d5
	moveq	#0,d1
	move.l	d4,d6
	bne	.c1
	moveq	#32,d1
	move.l	d5,d6
.c1:	moveq	#0,d7
.c2:	rol.l	#8,d6
	move.b	d6,d7
	bne	.c3
	addq.w	#8,d1
	bra	.c2
.c3:	add.b	(a0,d7.w),d1		; (the column)
	bsr	m72r_conv
	subq.w	#1,m72r_budget
	bmi	.over
	moveq	#63,d6			; its bit off
	sub.w	d1,d6
	cmp.w	#32,d6
	bhs	.c4
	bclr	d6,d5
	bra	.c5
.c4:	bclr	d6,d4
.c5:	move.l	d4,d6
	or.l	d5,d6
	bne	.c
	movem.l	(sp)+,d3/a0
	move.w	(sp)+,d2
.rn:	addq.w	#1,d2
	dbf	d3,.row
	movem.l	(sp)+,d4-d7/a4
	rts
.over:	st	m72r_late		; (the budget is spent: the rest the next time; this picture is not drawn)
	movem.l	(sp)+,d3/a0
	move.w	(sp)+,d2
	movem.l	(sp)+,d4-d7/a4
	rts

; ======================================================================================================================
; m72r_compose: the buffer's cells that changed since its last picture, from the layer images
; ======================================================================================================================
; A cell (8 x 8 pixels of the buffer, cell columns 0-127, rows 0-31 = picture lines 8r .. 8r + 7) is drawn again when
; it entered the window, a sprite drew into it (the damage of the buffer's last picture), a tile under it changed, or a
; layer that contributes to it moved relative to the buffer: FG contributes where it has an opaque pixel (ne), BG where
; it is not neutral and FG does not cover it (full: all pixels over, or all opaque without BG pixels drawn over FG's
; under pixels).  The cells a layer contributed to in the buffer's last picture are drawn again too (BS_FDEP / BS_BDEP:
; what moved away).  A row is cut into segments by the bands; each segment is drawn with its band's offsets:
;   BG copy (cells not covered), FG copy (covered), FG over BG (the rest with an opaque FG pixel: the FG opaque plane
;   ANDed out, the FG planes ORed in), and where BG pixels are drawn over FG's under pixels, those again (m72r_bodfix).
m72r_compose:
	move.l	m72r_cbs,a5
	move.l	m72r_dbuf,a6
	; the window's cells new to the buffer
	lea	m72r_ent,a0
	tst.w	BS_W(a5)
	bmi	.allw
	move.w	BS_W(a5),d0
	move.w	d0,d1
	lsr.w	#3,d0
	add.w	#319,d1
	lsr.w	#3,d1
	bsr	m72r_cellmask
	moveq	#4-1,d0
	lea	m72r_win,a1
.en:	move.l	(a0),d1
	not.l	d1
	and.l	(a1)+,d1
	move.l	d1,(a0)+
	dbf	d0,.en
	bra	.gd
.allw:	lea	m72r_win,a1
	moveq	#4-1,d0
.aw:	move.l	(a1)+,(a0)+
	dbf	d0,.aw
	; the guard rows' damage: black again
.gd:	lea	BS_DMG(a5),a2
	moveq	#-2,d6
	bsr	m72r_guard
	lea	BS_DMG+16(a5),a2
	moveq	#-1,d6
	bsr	m72r_guard
	lea	BS_DMG+34*16(a5),a2
	moveq	#32,d6
	bsr	m72r_guard
	lea	BS_DMG+35*16(a5),a2
	moveq	#33,d6
	bsr	m72r_guard
	; the bands against the buffer's last picture: when they have the same lines, each band's moves (bit 0 FG, bit 1
	; BG, bit 2 the display switched: all cells) for the rows within one band (m72r_frow); else the general way
	clr.b	m72r_fast
	tst.w	BS_W(a5)
	bmi	.nf
	move.w	m72r_nb,d7
	cmp.w	BS_NB(a5),d7
	bne	.nf
	lea	m72r_bt,a0
	lea	BS_BT(a5),a1
	lea	m72r_bmov,a2
	subq.w	#1,d7
.cm:	move.l	BT_Y0(a0),d0		; (y0, y1)
	cmp.l	BT_Y0(a1),d0
	bne	.nf
	moveq	#0,d1
	move.w	BT_OFF(a0),d0
	cmp.w	BT_OFF(a1),d0
	beq	.c1
	moveq	#7,d1
.c1:	move.l	BT_OXF(a0),d0		; (oxF, oyF)
	cmp.l	BT_OXF(a1),d0
	beq	.c2
	bset	#0,d1
.c2:	move.l	BT_OXB(a0),d0		; (oxB, oyB)
	cmp.l	BT_OXB(a1),d0
	beq	.c3
	bset	#1,d1
.c3:	move.b	d1,(a2)+
	lea	16(a0),a0
	lea	16(a1),a1
	dbf	d7,.cm
	st	m72r_fast
.nf:	; any entered cell?
	lea	m72r_ent,a0
	move.l	(a0)+,d0
	or.l	(a0)+,d0
	or.l	(a0)+,d0
	or.l	(a0)+,d0
	sne	m72r_entany
	; the rows
	clr.w	m72r_row
.row:	tst.b	m72r_fast
	beq	.rgen
	bsr	m72r_frow
	beq	.nrow
.rgen:	move.w	m72r_row,d0
	lea	BS_PRI(a5),a0		; (the priority cells: ORed by the segments)
	lsl.w	#3,d0
	clr.l	(a0,d0.w)
	clr.l	4(a0,d0.w)
	move.w	m72r_row,d0
	; R = damage | entered
	lea	BS_DMG+32(a5),a0
	lsl.w	#4,d0
	add.w	d0,a0
	lea	m72r_ent,a1
	lea	m72r_R,a2
	moveq	#4-1,d1
.r0:	move.l	(a0)+,d2
	or.l	(a1)+,d2
	move.l	d2,(a2)+
	dbf	d1,.r0
	clr.l	m72r_fd
	clr.l	m72r_fd+4
	clr.l	m72r_bd
	clr.l	m72r_bd+4
	; the segments
	lea	m72r_seg,a3
	clr.w	m72r_nseg
	lea	m72r_bt,a4
	move.w	m72r_nb,d7
	subq.w	#1,d7
.band:	move.w	m72r_row,d6
	lsl.w	#3,d6			; the row's first line
	move.w	d6,d5
	addq.w	#8,d5
	cmp.w	BT_Y0(a4),d6
	bhs	.s0
	move.w	BT_Y0(a4),d6
.s0:	cmp.w	BT_Y1(a4),d5
	bls	.s1
	move.w	BT_Y1(a4),d5
.s1:	cmp.w	d5,d6
	bhs	.nband
	move.w	d7,-(sp)
	move.w	d5,d7			; d6, d7: the segment's lines
	bsr	m72r_segment
	move.w	(sp)+,d7
.nband:	lea	16(a4),a4
	dbf	d7,.band
	; R within the window; the contributions for the next time
	lea	m72r_R,a0
	lea	m72r_win,a1
	moveq	#0,d2
	moveq	#4-1,d1
.rw:	move.l	(a1)+,d0
	and.l	d0,(a0)
	or.l	(a0)+,d2
	dbf	d1,.rw
	move.w	m72r_row,d0
	lsl.w	#3,d0
	lea	BS_FDEP(a5),a0
	move.l	m72r_fd,(a0,d0.w)
	move.l	m72r_fd+4,4(a0,d0.w)
	lea	BS_BDEP(a5),a0
	move.l	m72r_bd,(a0,d0.w)
	move.l	m72r_bd+4,4(a0,d0.w)
	tst.l	d2
	beq	.nrow
	; draw the segments
	lea	m72r_seg,a3
	move.w	m72r_nseg,d7
	subq.w	#1,d7
.ds:	move.w	d7,-(sp)
	bsr	m72r_drawseg
	move.w	(sp)+,d7
	lea	SG_SIZE(a3),a3
	dbf	d7,.ds
.nrow:	addq.w	#1,m72r_row
	cmp.w	#32,m72r_row
	blo	.row
	; the buffer's state for the next time
	move.w	m72r_W,BS_W(a5)
	move.w	m72r_nb,BS_NB(a5)
	lea	m72r_bt,a0
	lea	BS_BT(a5),a1
	moveq	#128/4-1,d0
.cb:	move.l	(a0)+,(a1)+
	dbf	d0,.cb
	lea	BS_DMG(a5),a0
	move.w	#576/4-1,d0
.cd:	clr.l	(a0)+
	dbf	d0,.cd
	tst.w	BS_ND(a5)
	beq	.x
	lea	BS_DIRF(a5),a0
	move.w	#1024/4-1,d0
.cr:	clr.l	(a0)+
	dbf	d0,.cr
	clr.w	BS_ND(a5)
.x:	rts

; the segment list of a row (m72r_seg)
SG_Y0		= 0
SG_Y1		= 2
SG_BAND		= 4			; .l the band's entry
SG_NE		= 8			; 64 bits: FG opaque somewhere
SG_FULL		= 16			; covered by FG
SG_SLOW		= 24			; BG pixels over FG under pixels possible
SG_SIZE		= 32

; m72r_segment: lines d6 .. d7 - 1 of the row with band a4: classes into the segment list (a3 advanced), the
; contributions, the cells to draw (m72r_R)
m72r_segment:
	move.w	d6,SG_Y0(a3)
	move.w	d7,SG_Y1(a3)
	move.l	a4,SG_BAND(a3)
	tst.w	BT_OFF(a4)
	beq	.on
	moveq	#0,d0			; display off: nothing contributes, everything black
	moveq	#0,d1
	move.l	d0,m72r_ne
	move.l	d0,m72r_ne+4
	move.l	d0,m72r_bnn
	move.l	d0,m72r_bnn+4
	move.l	d0,SG_NE(a3)
	move.l	d0,SG_NE+4(a3)
	move.l	d0,SG_FULL(a3)
	move.l	d0,SG_FULL+4(a3)
	move.l	d0,SG_SLOW(a3)
	move.l	d0,SG_SLOW+4(a3)
	moveq	#-1,d0			; (no sprite there: all cells "over")
	bsr	.pri
	moveq	#0,d0
	bra	.moved
.on:	bsr	m72r_fgp		; FG: ne fo fv und (cached)
	bsr	m72r_bgp		; BG: nn bod (cached)
	move.l	m72r_pne,SG_NE(a3)
	move.l	m72r_pne+4,SG_NE+4(a3)
	movem.l	m72r_fpri,d0-d1		; the cells with pixels over the sprites
	or.l	m72r_bpri,d0
	or.l	m72r_bpri+4,d1
	bsr	.pri2
	moveq	#0,d0
	moveq	#0,d1
	moveq	#0,d2
	moveq	#0,d3
	tst.w	m72r_nbod
	beq	.nb
	movem.l	m72r_bbod,d0-d1		; slow = bod & und
	move.l	d0,d2
	move.l	d1,d3
	and.l	m72r_fund,d2
	and.l	m72r_fund+4,d3
.nb:	move.l	d2,SG_SLOW(a3)
	move.l	d3,SG_SLOW+4(a3)
	not.l	d0			; full = fv | (fo & ~bod)
	not.l	d1
	and.l	m72r_fo,d0
	and.l	m72r_fo+4,d1
	or.l	m72r_fv,d0
	or.l	m72r_fv+4,d1
	move.l	d0,SG_FULL(a3)
	move.l	d1,SG_FULL+4(a3)
	not.l	d0			; bd = nn & ~full
	not.l	d1
	and.l	m72r_pnn,d0
	and.l	m72r_pnn+4,d1
	move.l	d0,m72r_bnn
	move.l	d1,m72r_bnn+4
	move.l	SG_NE(a3),m72r_ne
	move.l	SG_NE+4(a3),m72r_ne+4
	; the contributions of the row
	or.l	d0,m72r_bd
	or.l	d1,m72r_bd+4
	move.l	SG_NE(a3),d0
	or.l	d0,m72r_fd
	move.l	SG_NE+4(a3),d0
	or.l	d0,m72r_fd+4
.moved:	; moved: the buffer's last picture had other offsets (or display) in these lines
	tst.w	BS_W(a5)
	bmi	.dirty
	moveq	#0,d2			; bit 0: FG moved, bit 1: BG moved
	lea	BS_BT(a5),a0
	move.w	BS_NB(a5),d3
	subq.w	#1,d3
.ob:	cmp.w	BT_Y1(a0),d6		; overlap: y0 < old y1 and old y0 < y1
	bhs	.on2
	cmp.w	BT_Y0(a0),d7
	bls	.on2
	move.w	BT_OFF(a0),d0
	cmp.w	BT_OFF(a4),d0
	beq	.o1
	moveq	#7,d2			; (display on / off: all cells)
	bra	.on2
.o1:	move.w	BT_OXF(a0),d0
	cmp.w	BT_OXF(a4),d0
	bne	.fm
	move.w	BT_OYF(a0),d0
	cmp.w	BT_OYF(a4),d0
	beq	.o2
.fm:	bset	#0,d2
.o2:	move.w	BT_OXB(a0),d0
	cmp.w	BT_OXB(a4),d0
	bne	.bm
	move.w	BT_OYB(a0),d0
	cmp.w	BT_OYB(a4),d0
	beq	.on2
.bm:	bset	#1,d2
.on2:	lea	16(a0),a0
	dbf	d3,.ob
	move.w	m72r_row,d3
	lsl.w	#3,d3
	btst	#2,d2
	beq	.nal
	movem.l	m72r_win,d0-d1		; (the window's cells, both halves)
	or.l	d0,m72r_R
	or.l	d1,m72r_R+4
	movem.l	m72r_win+8,d0-d1
	or.l	d0,m72r_R+8
	or.l	d1,m72r_R+12
.nal:	btst	#0,d2
	beq	.nfm
	lea	BS_FDEP(a5),a0
	move.l	m72r_ne,d0
	or.l	(a0,d3.w),d0
	move.l	m72r_ne+4,d1
	or.l	4(a0,d3.w),d1
	bsr	.addr
.nfm:	btst	#1,d2
	beq	.dirty
	lea	BS_BDEP(a5),a0
	move.l	m72r_bnn,d0
	or.l	(a0,d3.w),d0
	move.l	m72r_bnn+4,d1
	or.l	4(a0,d3.w),d1
	bsr	.addr
.dirty:	; tiles changed since the buffer's last picture
	tst.w	BT_OFF(a4)
	bne	.x
	btst	#0,BS_ND+1(a5)
	beq	.d1
	move.w	BT_OXF(a4),d4
	move.w	BT_OYF(a4),d5
	lea	BS_DIRF(a5),a0
	bsr	.dproj
.d1:	btst	#1,BS_ND+1(a5)
	beq	.x
	move.w	BT_OXB(a4),d4
	move.w	BT_OYB(a4),d5
	lea	BS_DIRB(a5),a0
	bsr	.dproj
.x:	lea	SG_SIZE(a3),a3
	addq.w	#1,m72r_nseg
	rts
.dproj:	; the dirty tiles under the segment (only when one of its map rows has any)
	move.w	d6,d0
	add.w	d5,d0
	and.w	#511,d0
	lsr.w	#3,d0
	lsl.w	#3,d0
	move.l	(a0,d0.w),d1
	or.l	4(a0,d0.w),d1
	move.w	d7,d0
	subq.w	#1,d0
	add.w	d5,d0
	and.w	#511,d0
	lsr.w	#3,d0
	lsl.w	#3,d0
	or.l	(a0,d0.w),d1
	or.l	4(a0,d0.w),d1
	beq	.dn
	bsr	m72r_proj_or
	bra	.addr
.dn:	rts
.pri:	move.l	d0,d1			; the row's priority cells |= d0:d1
.pri2:	move.w	m72r_row,d2
	lsl.w	#3,d2
	lea	BS_PRI(a5),a0
	add.w	d2,a0
	or.l	d0,(a0)+
	or.l	d1,(a0)
	rts
.addr:	or.l	d0,m72r_R		; R |= d0:d1 twice (cells 0-63, 64-127)
	or.l	d1,m72r_R+4
	or.l	d0,m72r_R+8
	or.l	d1,m72r_R+12
	rts

; m72r_fgp / m72r_bgp: the FG (ne fo fv und) / BG (nn bod) projections of segment lines d6 .. d7 - 1 of band a4 into
; m72r_pne m72r_fo m72r_fv m72r_fund / m72r_pnn m72r_bbod, from a cache per row and segment (keyed by the offsets, the
; lines and the layer's flag version: the layer that stays put in the buffer is not projected again)
FC_SIZE		= 56
BC_SIZE		= 40
m72r_fgp:
	move.w	m72r_nseg,d0
	cmp.w	#2,d0
	bhs	m72r_fgp_calc
	move.w	m72r_row,d1
	add.w	d1,d1
	add.w	d0,d1
	mulu	#FC_SIZE,d1
	lea	m72r_fcache,a1
	add.w	d1,a1
	move.w	BT_OXF(a4),d0
	cmp.w	(a1),d0
	bne	.miss
	move.w	BT_OYF(a4),d0
	cmp.w	2(a1),d0
	bne	.miss
	cmp.w	4(a1),d6
	bne	.miss
	cmp.w	6(a1),d7
	bne	.miss
	bsr	m72r_fgp_ver
	cmp.l	8(a1),d0
	bne	.miss
	lea	12(a1),a1
	lea	m72r_pne,a0
	move.l	(a1)+,(a0)+
	move.l	(a1)+,(a0)+
	lea	m72r_fo,a0
	move.l	(a1)+,(a0)+
	move.l	(a1)+,(a0)+
	lea	m72r_fv,a0
	move.l	(a1)+,(a0)+
	move.l	(a1)+,(a0)+
	lea	m72r_fund,a0
	move.l	(a1)+,(a0)+
	move.l	(a1)+,(a0)+
	lea	m72r_fpri,a0
	move.l	(a1)+,(a0)+
	move.l	(a1)+,(a0)+
	rts
.miss:	move.l	a1,-(sp)
	bsr	m72r_fgp_calc
	move.l	(sp)+,a1
	move.w	BT_OXF(a4),(a1)+
	move.w	BT_OYF(a4),(a1)+
	move.w	d6,(a1)+
	move.w	d7,(a1)+
	bsr	m72r_fgp_ver
	move.l	d0,(a1)+
	lea	m72r_pne,a0
	move.l	(a0)+,(a1)+
	move.l	(a0)+,(a1)+
	lea	m72r_fo,a0
	move.l	(a0)+,(a1)+
	move.l	(a0)+,(a1)+
	lea	m72r_fv,a0
	move.l	(a0)+,(a1)+
	move.l	(a0)+,(a1)+
	lea	m72r_fund,a0
	move.l	(a0)+,(a1)+
	move.l	(a0)+,(a1)+
	lea	m72r_fpri,a0
	move.l	(a0)+,(a1)+
	move.l	(a0)+,(a1)+
	rts
m72r_fgp_ver:
.ver:	move.w	BT_OYF(a4),d1		; d0 = the versions of the two map rows of the lines
	move.w	d6,d0
	add.w	d1,d0
	and.w	#511,d0
	lsr.w	#3,d0
	add.w	d0,d0
	move.w	d7,d2
	subq.w	#1,d2
	add.w	d1,d2
	and.w	#511,d2
	lsr.w	#3,d2
	add.w	d2,d2
	lea	m72r_frver,a0
	move.w	(a0,d0.w),d0
	swap	d0
	move.w	(a0,d2.w),d0
	rts
m72r_fgp_calc:
	move.w	BT_OXF(a4),d4
	move.w	BT_OYF(a4),d5
	lea	m72r_flags+F_NE,a0
	bsr	m72r_proj_or
	movem.l	d0-d1,m72r_pne
	lea	m72r_flags+F_FV,a0
	bsr	m72r_proj_and
	movem.l	d0-d1,m72r_fv
	lea	m72r_flags+F_FO,a0
	bsr	m72r_proj_and
	movem.l	d0-d1,m72r_fo
	lea	m72r_flags+F_UND,a0
	bsr	m72r_proj_or
	movem.l	d0-d1,m72r_fund
	lea	m72r_flags+F_PRI,a0
	bsr	m72r_proj_or
	movem.l	d0-d1,m72r_fpri
	rts
m72r_bgp:
	move.w	m72r_nseg,d0
	cmp.w	#2,d0
	bhs	m72r_bgp_calc
	move.w	m72r_row,d1
	add.w	d1,d1
	add.w	d0,d1
	mulu	#BC_SIZE,d1
	lea	m72r_bcache,a1
	add.w	d1,a1
	move.w	BT_OXB(a4),d0
	cmp.w	(a1),d0
	bne	.miss
	move.w	BT_OYB(a4),d0
	cmp.w	2(a1),d0
	bne	.miss
	cmp.w	4(a1),d6
	bne	.miss
	cmp.w	6(a1),d7
	bne	.miss
	bsr	m72r_bgp_ver
	cmp.l	8(a1),d0
	bne	.miss
	lea	12(a1),a1
	lea	m72r_pnn,a0
	move.l	(a1)+,(a0)+
	move.l	(a1)+,(a0)+
	lea	m72r_bbod,a0
	move.l	(a1)+,(a0)+
	move.l	(a1)+,(a0)+
	lea	m72r_bpri,a0
	move.l	(a1)+,(a0)+
	move.l	(a1)+,(a0)+
	rts
.miss:	move.l	a1,-(sp)
	bsr	m72r_bgp_calc
	move.l	(sp)+,a1
	move.w	BT_OXB(a4),(a1)+
	move.w	BT_OYB(a4),(a1)+
	move.w	d6,(a1)+
	move.w	d7,(a1)+
	bsr	m72r_bgp_ver
	move.l	d0,(a1)+
	lea	m72r_pnn,a0
	move.l	(a0)+,(a1)+
	move.l	(a0)+,(a1)+
	lea	m72r_bbod,a0
	move.l	(a0)+,(a1)+
	move.l	(a0)+,(a1)+
	lea	m72r_bpri,a0
	move.l	(a0)+,(a1)+
	move.l	(a0)+,(a1)+
	rts
m72r_bgp_ver:
.ver:	move.w	BT_OYB(a4),d1		; d0 = the versions of the two map rows of the lines
	move.w	d6,d0
	add.w	d1,d0
	and.w	#511,d0
	lsr.w	#3,d0
	add.w	d0,d0
	move.w	d7,d2
	subq.w	#1,d2
	add.w	d1,d2
	and.w	#511,d2
	lsr.w	#3,d2
	add.w	d2,d2
	lea	m72r_brver,a0
	move.w	(a0,d0.w),d0
	swap	d0
	move.w	(a0,d2.w),d0
	rts
m72r_bgp_calc:
	move.w	BT_OXB(a4),d4
	move.w	BT_OYB(a4),d5
	lea	m72r_flags+B_NN,a0
	bsr	m72r_proj_or
	movem.l	d0-d1,m72r_pnn
	lea	m72r_flags+B_PRI,a0
	bsr	m72r_proj_or
	movem.l	d0-d1,m72r_bpri
	clr.l	m72r_bbod
	clr.l	m72r_bbod+4
	tst.w	m72r_nbod
	beq	.c1
	lea	m72r_flags+B_BOD,a0
	bsr	m72r_proj_or
	movem.l	d0-d1,m72r_bbod
.c1:	rts

; m72r_frow: row m72r_row when it lies within one band that is not off and the bands compare (m72r_fast): Z set when
; done, clear when the general way must do it
m72r_frow:
	move.w	m72r_row,d6
	lsl.w	#3,d6			; y0
	lea	m72r_lband,a0
	move.b	(a0,d6.w),d0
	cmp.b	7(a0,d6.w),d0
	bne	.gen			; (a band starts in the row)
	moveq	#0,d1
	move.b	d0,d1
	lea	m72r_bmov,a0
	move.b	(a0,d1.w),m72r_rmov
	lsl.w	#4,d1
	lea	m72r_bt,a4
	add.w	d1,a4
	tst.w	BT_OFF(a4)
	bne	.gen
	; nothing changed in the row since the buffer's last picture (the band did not move, no damage, no changed tiles,
	; no cell entered the window): nothing to draw, the contributions stay
	tst.b	m72r_rmov
	bne	.ch
	tst.b	m72r_entany
	bne	.ch
	tst.w	BS_ND(a5)
	bne	.ch
	move.w	m72r_row,d0
	lsl.w	#4,d0
	lea	BS_DMG+32(a5),a0
	add.w	d0,a0
	move.l	(a0)+,d0
	or.l	(a0)+,d0
	or.l	(a0)+,d0
	or.l	(a0)+,d0
	beq	.x
.ch:	move.w	d6,d7
	addq.w	#8,d7			; y1
	clr.w	m72r_nseg		; (the cache slot of the row's first segment)
	lea	m72r_seg,a3
	move.w	d6,SG_Y0(a3)
	move.w	d7,SG_Y1(a3)
	move.l	a4,SG_BAND(a3)
	bsr	m72r_fgq		; a1 = FG ne fo fv und
	bsr	m72r_bgq		; a2 = BG nn bod
	; full, slow
	movem.l	8(a1),d0-d1		; fo
	moveq	#0,d2
	moveq	#0,d3
	tst.w	m72r_nbod
	beq	.nb
	movem.l	8(a2),d2-d3		; bod
	not.l	d2
	not.l	d3
	and.l	d2,d0
	and.l	d3,d1
	or.l	16(a1),d0		; full = fv | (fo & ~bod)
	or.l	20(a1),d1
	movem.l	8(a2),d2-d3
	and.l	24(a1),d2		; slow = bod & und
	and.l	28(a1),d3
.nb:	move.l	d0,SG_FULL(a3)
	move.l	d1,SG_FULL+4(a3)
	move.l	d2,SG_SLOW(a3)
	move.l	d3,SG_SLOW+4(a3)
	move.l	(a1),SG_NE(a3)
	move.l	4(a1),SG_NE+4(a3)
	move.w	m72r_row,d4		; the row's cells with pixels over the sprites (FG | BG over)
	lsl.w	#3,d4
	lea	BS_PRI(a5),a0
	add.w	d4,a0
	move.l	32(a1),d4
	or.l	16(a2),d4
	move.l	d4,(a0)+
	move.l	36(a1),d4
	or.l	20(a2),d4
	move.l	d4,(a0)
	not.l	d0			; bd = nn & ~full
	not.l	d1
	and.l	(a2),d0
	and.l	4(a2),d1
	; the contributions for the next time; R
	move.w	m72r_row,d2
	lsl.w	#3,d2
	lea	BS_BDEP(a5),a0
	add.w	d2,a0
	lea	BS_FDEP(a5),a1
	add.w	d2,a1
	move.l	d0,d2			; (the old ones, when the layer moved)
	move.l	d1,d3
	btst	#1,m72r_rmov
	beq	.b0
	or.l	(a0),d2
	or.l	4(a0),d3
	bra	.b1
.b0:	moveq	#0,d2
	moveq	#0,d3
.b1:	move.l	d0,(a0)+		; (BS_BDEP)
	move.l	d1,(a0)
	move.l	SG_NE(a3),d0
	move.l	SG_NE+4(a3),d1
	btst	#0,m72r_rmov
	beq	.f0
	move.l	d0,d4
	move.l	d1,d5
	or.l	(a1),d4
	or.l	4(a1),d5
	or.l	d4,d2
	or.l	d5,d3
.f0:	move.l	d0,(a1)+		; (BS_FDEP)
	move.l	d1,(a1)
	; R = (FG / BG moves) twice | damage | entered (| everything: display switched)
	move.w	m72r_row,d0
	lsl.w	#4,d0
	lea	BS_DMG+32(a5),a0
	add.w	d0,a0
	movem.l	(a0),d4-d7
	or.l	d2,d4
	or.l	d3,d5
	or.l	d2,d6
	or.l	d3,d7
	tst.b	m72r_entany
	beq	.ne
	lea	m72r_ent,a0
	or.l	(a0)+,d4
	or.l	(a0)+,d5
	or.l	(a0)+,d6
	or.l	(a0)+,d7
.ne:	btst	#2,m72r_rmov
	beq	.na
	moveq	#-1,d4
	moveq	#-1,d5
	moveq	#-1,d6
	moveq	#-1,d7
.na:	movem.l	d4-d7,m72r_R
	; tiles changed since the buffer's last picture
	tst.w	BS_ND(a5)
	beq	.nd
	move.w	SG_Y0(a3),d6
	move.w	SG_Y1(a3),d7
	btst	#0,BS_ND+1(a5)
	beq	.d1
	move.w	BT_OXF(a4),d4
	move.w	BT_OYF(a4),d5
	lea	BS_DIRF(a5),a0
	bsr	m72r_dproj
.d1:	btst	#1,BS_ND+1(a5)
	beq	.nd
	move.w	BT_OXB(a4),d4
	move.w	BT_OYB(a4),d5
	lea	BS_DIRB(a5),a0
	bsr	m72r_dproj
.nd:	; within the window; draw
	movem.l	m72r_R,d4-d7
	lea	m72r_win,a0
	and.l	(a0)+,d4
	and.l	(a0)+,d5
	and.l	(a0)+,d6
	and.l	(a0)+,d7
	movem.l	d4-d7,m72r_R
	or.l	d5,d4
	or.l	d6,d4
	or.l	d7,d4
	beq	.x
	bsr	m72r_drawseg
.x:	moveq	#0,d0			; (Z: done)
	rts
.gen:	moveq	#1,d0
	rts

; m72r_dproj: the dirty tiles a0 under lines d6 .. d7 - 1 at d4 / d5 into m72r_R (only when one of its map rows has any)
m72r_dproj:
	move.w	d6,d0
	add.w	d5,d0
	and.w	#511,d0
	lsr.w	#3,d0
	lsl.w	#3,d0
	move.l	(a0,d0.w),d1
	or.l	4(a0,d0.w),d1
	move.w	d7,d0
	subq.w	#1,d0
	add.w	d5,d0
	and.w	#511,d0
	lsr.w	#3,d0
	lsl.w	#3,d0
	or.l	(a0,d0.w),d1
	or.l	4(a0,d0.w),d1
	beq	.dn
	bsr	m72r_proj_or
	or.l	d0,m72r_R
	or.l	d1,m72r_R+4
	or.l	d0,m72r_R+8
	or.l	d1,m72r_R+12
.dn:	rts

; m72r_fgq / m72r_bgq: m72r_fgp / m72r_bgp of the row's first segment, the values by pointer (a1 / a2: ne fo fv und /
; nn bod)
m72r_fgq:
	move.w	m72r_row,d1
	add.w	d1,d1
	mulu	#FC_SIZE,d1
	lea	m72r_fcache,a1
	add.w	d1,a1
	move.w	BT_OXF(a4),d0
	cmp.w	(a1),d0
	bne	.miss
	move.w	BT_OYF(a4),d0
	cmp.w	2(a1),d0
	bne	.miss
	cmp.w	4(a1),d6
	bne	.miss
	cmp.w	6(a1),d7
	bne	.miss
	move.l	a1,-(sp)
	bsr	m72r_fgp_ver
	move.l	(sp)+,a1
	cmp.l	8(a1),d0
	bne	.miss
	lea	12(a1),a1
	rts
.miss:	bsr	m72r_fgp		; (computes, fills the slot)
	move.w	m72r_row,d1
	add.w	d1,d1
	mulu	#FC_SIZE,d1
	lea	m72r_fcache+12,a1
	add.w	d1,a1
	rts
m72r_bgq:
	move.w	m72r_row,d1
	add.w	d1,d1
	mulu	#BC_SIZE,d1
	lea	m72r_bcache,a2
	add.w	d1,a2
	move.w	BT_OXB(a4),d0
	cmp.w	(a2),d0
	bne	.miss
	move.w	BT_OYB(a4),d0
	cmp.w	2(a2),d0
	bne	.miss
	cmp.w	4(a2),d6
	bne	.miss
	cmp.w	6(a2),d7
	bne	.miss
	movem.l	a1-a2,-(sp)
	bsr	m72r_bgp_ver
	movem.l	(sp)+,a1-a2
	cmp.l	8(a2),d0
	bne	.miss
	lea	12(a2),a2
	rts
.miss:	move.l	a1,-(sp)
	bsr	m72r_bgp
	move.l	(sp)+,a1
	move.w	m72r_row,d1
	add.w	d1,d1
	mulu	#BC_SIZE,d1
	lea	m72r_bcache+12,a2
	add.w	d1,a2
	rts

; m72r_drawseg: the segment a3 of the row: the cells m72r_R
m72r_drawseg:
	move.l	SG_BAND(a3),a4
	tst.w	BT_OFF(a4)
	beq	.on
	lea	m72r_R,a0		; display off: black
	bsr	m72r_runs
	move.b	#0,m72r_x_op
	bsr	m72r_fillruns
	rts
.on:	; the classes: BG copy = R & ~full, FG copy = R & full, FG over = R & ne & ~full, of these the slow ones & slow
	lea	m72r_R,a0
	lea	m72r_cbg,a1
	lea	m72r_cfg,a2
	lea	m72r_cmx,a6
	lea	m72r_csl,a4
	moveq	#0,d6			; (any slow)
	moveq	#2-1,d7
.c:	move.l	SG_FULL(a3),d0
	move.l	SG_NE(a3),d1
	move.l	SG_SLOW(a3),d2
	bsr	.cls
	move.l	SG_FULL+4(a3),d0
	move.l	SG_NE+4(a3),d1
	move.l	SG_SLOW+4(a3),d2
	bsr	.cls
	dbf	d7,.c
	move.l	SG_BAND(a3),a4
	move.l	m72r_dbuf,a6
	clr.b	m72r_x_dk
	; BG copy
	lea	m72r_cbg,a0
	bsr	m72r_runs
	ifd	M72_STATS
	move.w	m72r_nrun,d0
	ext.l	d0
	add.l	d0,m72r_st_bg
	endc
	tst.w	m72r_nrun
	beq	.nbg
	move.l	#m72r_imgb,m72r_x_src
	move.w	BT_OXB(a4),m72r_x_ox
	move.w	BT_OYB(a4),m72r_x_oy
	move.l	#M72_PL,m72r_x_sstep
	move.w	#4,m72r_x_planes
	move.b	#3,m72r_x_op
	bsr	m72r_xruns
.nbg:	; FG copy
	lea	m72r_cfg,a0
	bsr	m72r_runs
	ifd	M72_STATS
	move.w	m72r_nrun,d0
	ext.l	d0
	add.l	d0,m72r_st_fg
	endc
	tst.w	m72r_nrun
	beq	.nfg
	move.l	#m72r_imgf,m72r_x_src
	move.w	BT_OXF(a4),m72r_x_ox
	move.w	BT_OYF(a4),m72r_x_oy
	move.l	#M72_PL,m72r_x_sstep
	move.w	#4,m72r_x_planes
	move.b	#3,m72r_x_op
	bsr	m72r_xruns
.nfg:	; FG over BG
	lea	m72r_cmx,a0
	bsr	m72r_runs
	ifd	M72_STATS
	move.w	m72r_nrun,d0
	ext.l	d0
	add.l	d0,m72r_st_mx
	endc
	tst.w	m72r_nrun
	beq	.nmx
	move.l	#m72r_imgf+4*M72_PL,m72r_x_src	; the opaque plane ANDed out of the 4 planes
	move.w	BT_OXF(a4),m72r_x_ox
	move.w	BT_OYF(a4),m72r_x_oy
	clr.l	m72r_x_sstep
	move.w	#4,m72r_x_planes
	move.b	#4,m72r_x_op
	move.l	#m72r_imgf,m72r_x_src2	; then the FG planes ORed in
	move.b	#7,m72r_x_op2
	bsr	m72r_xruns
	clr.b	m72r_x_op2
.nmx:	tst.l	d6
	beq	.x
	lea	m72r_csl,a0
	bsr	m72r_runs
	tst.w	m72r_nrun
	beq	.x
	bsr	m72r_bodfix
.x:	rts
; one long of each class: a0 = R, d0 = full, d1 = ne, d2 = slow
.cls:	move.l	(a0)+,d3
	move.l	d3,d4
	and.l	d0,d4
	move.l	d4,(a2)+		; FG copy
	not.l	d0
	and.l	d0,d3
	move.l	d3,(a1)+		; BG copy
	and.l	d1,d3
	move.l	d3,(a6)+		; FG over
	and.l	d2,d3
	move.l	d3,(a4)+		; slow
	or.l	d3,d6
	rts

; ----------------------------------------------------------------------------------------------------------------------
; runs of set bits of a 128-bit row (a0, MSB first) -> m72r_runl: (first cell, last cell + 1) words, m72r_nrun; a run is
; at most M72_RUNMAX cells (so a pass that reads the destination stays within 256 bus cycles a line)
; ----------------------------------------------------------------------------------------------------------------------
M72_RUNMAX	= 36
m72r_runs:
	move.l	(a0),d0
	or.l	4(a0),d0
	or.l	8(a0),d0
	or.l	12(a0),d0
	bne	.any
	clr.w	m72r_nrun
	rts
.any:	movem.l	d0-d7/a0-a2,-(sp)
	lea	m72r_lz8,a2
	lea	m72r_runl,a1
	moveq	#0,d7			; runs
	moveq	#-1,d6			; the open run's first cell (-1: none)
	move.w	m72r_wl0,d5		; (only the longs of the window)
	add.w	d5,d5
	add.w	d5,d5
	add.w	d5,a0
	lsl.w	#3,d5			; the cell of the current bit
	move.w	m72r_wln,d4
.long:	move.l	(a0)+,d0
	move.w	d5,d3
	add.w	#32,d3			; the long's end
	tst.w	d6
	bmi	.find
	tst.l	d0			; an open run: does this long start with a one?
	bmi	.ones
	bsr	.emit
.find:	tst.l	d0
	beq	.endl
	; leading zeros
.z:	move.l	d0,d1
	rol.l	#8,d1
	tst.b	d1
	bne	.zb
	lsl.l	#8,d0
	addq.w	#8,d5
	bra	.z
.zb:	moveq	#0,d2
	move.b	d1,d2
	move.b	(a2,d2.w),d2
	lsl.l	d2,d0
	add.w	d2,d5
	move.w	d5,d6			; a run starts
.ones:	move.l	d0,d1			; leading ones: the leading zeros of the complement
	not.l	d1
	beq	.all
.o:	move.l	d1,d2
	rol.l	#8,d2
	tst.b	d2
	bne	.ob
	lsl.l	#8,d1
	lsl.l	#8,d0
	addq.w	#8,d5
	bra	.o
.ob:	and.w	#$ff,d2
	move.b	(a2,d2.w),d2
	lsl.l	d2,d0
	add.w	d2,d5
	cmp.w	d3,d5
	bhs	.endl			; (the run reaches the long's end: it may go on)
	bsr	.emit
	bra	.find
.all:	move.w	d3,d5			; ones to the long's end
.endl:	move.w	d3,d5
	dbf	d4,.long
	tst.w	d6
	bmi	.done
	bsr	.emit
.done:	move.w	d7,m72r_nrun
	movem.l	(sp)+,d0-d7/a0-a2
	rts
.emit:	; the run d6 .. d5 (cut at M72_RUNMAX cells)
	move.w	d5,d1
	sub.w	d6,d1
	cmp.w	#M72_RUNMAX,d1
	bls	.e1
	move.w	d6,(a1)+
	add.w	#M72_RUNMAX,d6
	move.w	d6,(a1)+
	addq.w	#1,d7
	bra	.emit
.e1:	move.w	d6,(a1)+
	move.w	d5,(a1)+
	addq.w	#1,d7
	moveq	#-1,d6
	rts

; ----------------------------------------------------------------------------------------------------------------------
; transfers: m72r_xruns (the runs of m72r_runl in the segment a3's lines, from the layer image m72r_x_src at m72r_x_ox /
; m72r_x_oy to the buffer), m72r_fillruns (op only, no source), m72r_xfer (one rectangle)
; ----------------------------------------------------------------------------------------------------------------------
m72r_xruns:
	ifd	M72_STATS
	addq.l	#1,m72r_st_xr
	move.w	m72r_nrun,d0
	ext.l	d0
	add.l	d0,m72r_st_runs
	endc
	movem.l	d0-d7/a0-a6,-(sp)
	; the constants of the op
	move.b	#2,BLT_HOP.w
	move.b	m72r_x_op,BLT_OP.w
	move.w	#1024,BLT_SXI.w
	move.w	#8,BLT_DXI.w
	move.w	#$ffff,BLT_E2.w
	moveq	#0,d0
	move.b	m72r_x_op,d0
	move.w	#%0110100111110110,d1	; (ops that read the destination)
	btst	d0,d1
	sne	m72r_x_rd
	; the lines: cut where the map lines wrap
	move.w	SG_Y0(a3),d0
	move.w	SG_Y1(a3),d5
	sub.w	d0,d5			; lines
	move.w	d0,d1
	add.w	m72r_x_oy,d1
	and.w	#511,d1			; the map line
	move.w	#512,d2
	sub.w	d1,d2			; lines to the wrap
	cmp.w	d5,d2
	bhs	.one
	movem.w	d0/d2/d5,-(sp)
	move.w	d2,d5
	bsr	.part
	movem.w	(sp)+,d0/d2/d5
	add.w	d2,d0
	sub.w	d2,d5
	moveq	#0,d1
.one:	bsr	.part
	movem.l	(sp)+,d0-d7/a0-a6
	rts
; the runs in lines d0 (picture) .. + d5, map line d1
.part:	add.w	d1,d1
	move.w	d1,m72r_x_sl		; the source line's offset
	add.w	#M72_G,d0
	ext.l	d0
	moveq	#9,d1
	lsl.l	d1,d0
	add.l	m72r_dbuf,d0
	move.l	d0,a5			; the destination line
	lea	m72r_ptab,a4
	lea	m72r_xtab,a6
	lea	m72r_runl,a2
	move.w	m72r_nrun,d7
	subq.w	#1,d7
.r:	move.w	(a2)+,d0		; c0
	move.w	(a2)+,d1		; c1
	sub.w	d0,d1
	lsl.w	#3,d0			; dx
	lsl.w	#3,d1			; w
	move.w	d0,d2
	add.w	m72r_x_ox,d2
	and.w	#511,d2			; sx
	move.w	#512,d3
	sub.w	d2,d3			; pixels to the map's wrap
	cmp.w	d1,d3
	bhs	.r1
	movem.w	d0-d3,-(sp)
	move.w	d3,d1
	bsr	m72r_xrect
	movem.w	(sp)+,d0-d3
	add.w	d3,d0
	sub.w	d3,d1
	moveq	#0,d2
.r1:	bsr	m72r_xrect
	dbf	d7,.r
	rts

; m72r_xrect: one rectangle of m72r_xruns: buffer x d0, d1 pixels, map x d2 (no wrap), lines d5 from the destination
; line a5 (source line offset m72r_x_sl); a4 = m72r_ptab, a6 = m72r_xtab; keeps d5, d7, a2-a6
m72r_xrect:
	ifd	M72_STATS
	move.l	d0,-(sp)
	move.w	d1,d0
	mulu	d5,d0
	add.l	d0,m72r_xarea
	addq.l	#1,m72r_nx
	tst.b	m72r_x_op2
	beq	.st
	addq.l	#1,m72r_nx2
.st:	move.l	(sp)+,d0
	endif
	cmp.w	#8,d1			; one cell (8 pixels from a cell's start): one word a line, one piece
	bne	.gen
	moveq	#7,d4
	and.w	d0,d4
	bne	.gen
	move.w	#1,BLT_XC.w
	moveq	#8,d4
	and.w	d0,d4			; db: the cell's half of the word
	move.w	#$ff00,d1
	tst.w	d4
	beq	.c1
	move.w	#$00ff,d1
.c1:	move.w	d1,BLT_E1.w
	moveq	#15,d1
	and.w	d2,d1			; sb
	move.w	#2,BLT_SYI.w
	sub.w	d1,d4			; the skew: db - sb, FXSR when negative (two fetches a line)
	bcc	.c2
	and.w	#15,d4
	or.w	#BLT_FXSR,d4
	move.w	#2-1024,BLT_SYI.w
.c2:	move.b	d4,BLT_SKEW.w
	move.w	#M72_LB,BLT_DYI.w
	move.l	m72r_x_src,a0
	lsr.w	#4,d2
	moveq	#10,d1
	lsl.w	d1,d2
	add.w	m72r_x_sl,d2
	moveq	#0,d1
	move.w	d2,d1
	add.l	d1,a0			; the source
	lsr.w	#4,d0
	lsl.w	#3,d0
	lea	(a5,d0.w),a1		; the destination
	move.w	m72r_x_planes,d4
	subq.w	#1,d4
	move.l	m72r_x_sstep,d6
	bra	.pl
.gen:	; nd, the end masks, the destination's accesses
	move.w	d0,d3
	add.w	d1,d3
	subq.w	#1,d3			; the last pixel
	moveq	#15,d4
	and.w	d3,d4
	lsr.w	#4,d3
	move.w	d0,d6
	lsr.w	#4,d6
	sub.w	d6,d3
	addq.w	#1,d3			; nd
	move.w	d3,BLT_XC.w
	move.w	d3,d6			; (the writes)
	eor.w	#15,d4
	moveq	#-1,d1
	lsl.w	d4,d1			; END3
	move.w	d1,-(sp)
	moveq	#15,d4
	and.w	d0,d4
	move.w	d4,a0			; (dx & 15)
	moveq	#-1,d1
	lsr.w	d4,d1			; END1
	move.w	(sp)+,d4		; END3
	cmp.w	#1,d3
	bne	.e1
	and.w	d4,d1
	bra	.e2
.e1:	cmp.w	#$ffff,d4
	beq	.e2
	addq.w	#1,d6
.e2:	cmp.w	#$ffff,d1
	beq	.e4
	addq.w	#1,d6
.e4:	move.w	d1,BLT_E1.w
	move.w	d4,BLT_E3.w
	tst.b	m72r_x_rd
	beq	.e5
	move.w	d3,d6			; (the op reads every word)
	add.w	d3,d6
.e5:	; the skew: (dx & 15) - (sx & 15), FXSR when the source starts further right
	moveq	#15,d1
	and.w	d2,d1			; sb
	move.w	a0,d4			; db
	add.w	d3,d6			; (+ the fetches: nd, + 1 with FXSR)
	move.w	d3,a1			; fetched
	sub.w	d1,d4
	bcc	.nf
	addq.w	#1,d6
	addq.w	#1,a1
	and.w	#15,d4
	or.w	#BLT_FXSR,d4
.nf:	move.b	d4,BLT_SKEW.w
	move.w	a1,d4
	add.w	d4,d4
	move.w	(a6,d4.w),BLT_SYI.w	; 2 - (fetched - 1) * 1024
	add.w	d3,d3
	move.w	64(a6,d3.w),BLT_DYI.w	; 512 - (nd - 1) * 8
	moveq	#0,d3
	move.b	(a4,d6.w),d3		; the lines a piece
	; the addresses
	move.l	m72r_x_src,a0
	lsr.w	#4,d2
	moveq	#10,d1
	lsl.w	d1,d2
	add.w	m72r_x_sl,d2
	moveq	#0,d1
	move.w	d2,d1
	add.l	d1,a0			; the source
	lsr.w	#4,d0
	lsl.w	#3,d0
	lea	(a5,d0.w),a1		; the destination
	move.w	m72r_x_planes,d4
	subq.w	#1,d4
	move.l	m72r_x_sstep,d6
	cmp.w	d5,d3
	blo	.pieces
.pl:	move.l	a0,BLT_SRC.w		; (one piece a plane)
	move.l	a1,BLT_DST.w
	move.w	d5,BLT_YC.w
	move.b	#BLT_GO,BLT_CTRL.w
	add.l	d6,a0
	addq.l	#2,a1
	dbf	d4,.pl
	tst.b	m72r_x_op2		; the second op on the same rectangle (FG: the planes ORed in after the mask)
	beq	.nr
	move.b	m72r_x_op2,BLT_OP.w
	move.l	m72r_x_src2,a0
	add.l	d1,a0
	subq.l	#8,a1
	moveq	#4-1,d4
.pl2:	move.l	a0,BLT_SRC.w
	move.l	a1,BLT_DST.w
	move.w	d5,BLT_YC.w
	move.b	#BLT_GO,BLT_CTRL.w
	add.l	#M72_PL,a0
	addq.l	#2,a1
	dbf	d4,.pl2
	move.b	m72r_x_op,BLT_OP.w
.nr:	rts
.pieces:
	move.l	a1,-(sp)
	bsr	.planes
	move.l	(sp)+,a1
	tst.b	m72r_x_op2
	beq	.nr
	move.b	m72r_x_op2,BLT_OP.w
	move.l	m72r_x_src2,a0
	add.l	d1,a0
	moveq	#4-1,d4
	move.l	#M72_PL,d6
	bsr	.planes
	move.b	m72r_x_op,BLT_OP.w
	rts
.planes:
.pp:	move.l	a0,BLT_SRC.w
	move.l	a1,BLT_DST.w
	move.w	d5,d2			; lines left
.pi:	move.w	d3,d0
	cmp.w	d0,d2
	bhs	.pi1
	move.w	d2,d0
.pi1:	move.w	d0,BLT_YC.w
	move.b	#BLT_GO,BLT_CTRL.w
	sub.w	d0,d2
	bne	.pi
	add.l	d6,a0
	addq.l	#2,a1
	dbf	d4,.pp
	rts

m72r_fillruns:
	movem.l	d0-d7/a0-a6,-(sp)
	move.b	#3,m72r_x_sk		; (no source)
	move.w	#4,m72r_x_planes
	lea	m72r_runl,a2
	move.w	m72r_nrun,d7
	subq.w	#1,d7
	bmi	.x
.r:	move.w	(a2)+,d0
	move.w	(a2)+,d1
	sub.w	d0,d1
	lsl.w	#3,d0
	lsl.w	#3,d1
	move.w	d0,m72r_x_dx
	move.w	d1,m72r_x_w
	move.w	SG_Y0(a3),d2
	move.w	d2,m72r_x_y0
	move.w	SG_Y1(a3),d3
	sub.w	d2,d3
	move.w	d3,m72r_x_n
	bsr	m72r_xfer
	dbf	d7,.r
.x:	movem.l	(sp)+,d0-d7/a0-a6
	rts

; m72r_guard: the damage of a guard row (a2: 16 bytes, d6 = the row -2, -1, 32, 33) black again
m72r_guard:
	movem.l	d0-d7/a0-a6,-(sp)
	move.l	(a2),d0
	or.l	4(a2),d0
	or.l	8(a2),d0
	or.l	12(a2),d0
	beq	.x
	move.l	a2,a0
	move.l	m72r_wl0,-(sp)		; (all four longs: sprites draw a little beyond the window's cells)
	clr.w	m72r_wl0
	move.w	#3,m72r_wln
	bsr	m72r_runs
	move.l	(sp)+,m72r_wl0
	move.b	#3,m72r_x_sk
	clr.b	m72r_x_dk
	move.w	#4,m72r_x_planes
	clr.b	m72r_x_op
	lsl.w	#3,d6
	lea	m72r_runl,a2
	move.w	m72r_nrun,d7
	subq.w	#1,d7
.r:	move.w	(a2)+,d0
	move.w	(a2)+,d1
	sub.w	d0,d1
	lsl.w	#3,d0
	lsl.w	#3,d1
	move.w	d0,m72r_x_dx
	move.w	d1,m72r_x_w
	move.w	d6,m72r_x_y0
	move.w	#8,m72r_x_n
	bsr	m72r_xfer
	dbf	d7,.r
.x:	movem.l	(sp)+,d0-d7/a0-a6
	rts

; m72r_xfer: the rectangle m72r_x_dx (buffer x), m72r_x_w (pixels), lines m72r_x_y0 (picture line) .. + m72r_x_n:
;   source kind m72r_x_sk: 0 the layer image plane(s) m72r_x_src (+ m72r_x_sstep a plane) at map x = buffer x +
;   m72r_x_ox, map y = line + m72r_x_oy (both mod 512: cut where they wrap); 1 / 2 the temporary rows m72r_tmp /
;   m72r_tmp2 (the grid of the destination's words from m72r_tw0, m72r_tnd words a line, lines from m72r_ty0); 3 none
;   destination kind m72r_x_dk: 0 the buffer (m72r_dbuf: m72r_x_planes planes), 1 / 2 the temporary rows (one plane)
;   op m72r_x_op (HOP 2: the source)
m72r_xfer:
	movem.l	d0-d7/a0-a2,-(sp)
	move.w	m72r_x_dx,d0
	move.w	m72r_x_w,d1
	move.w	m72r_x_y0,d4
	move.w	m72r_x_n,d5
	tst.b	m72r_x_sk
	bne	.one
	move.w	m72r_x_ox,d2
	add.w	d0,d2
	and.w	#511,d2			; sx
	move.w	m72r_x_oy,d3
	add.w	d4,d3
	and.w	#511,d3			; sy
	; cut where the map x wraps
	move.w	#512,d6
	sub.w	d2,d6			; pixels to the wrap
	cmp.w	d1,d6
	bhs	.nx
	move.w	d1,d7
	sub.w	d6,d7			; the rest
	move.w	d6,d1
	movem.w	d0/d7,-(sp)
	bsr	.lines
	movem.w	(sp)+,d0/d7
	add.w	d1,d0
	move.w	d7,d1
	moveq	#0,d2
	move.w	m72r_x_oy,d3
	add.w	d4,d3
	and.w	#511,d3
.nx:	bsr	.lines
	movem.l	(sp)+,d0-d7/a0-a2
	rts
.one:	moveq	#0,d2
	moveq	#0,d3
	bsr	m72r_xcore
	movem.l	(sp)+,d0-d7/a0-a2
	rts
; cut where the map y wraps: d0 dx, d1 w, d2 sx, d3 sy, d4 y0, d5 n
.lines:	move.w	#512,d6
	sub.w	d3,d6
	cmp.w	d5,d6
	bhs	m72r_xcore
	movem.w	d4-d5,-(sp)
	move.w	d6,d5
	bsr	m72r_xcore
	movem.w	(sp)+,d4-d5
	add.w	d6,d4
	sub.w	d6,d5
	moveq	#0,d3
	bra	m72r_xcore

; m72r_xcore: d0 dx, d1 w, d2 sx, d3 sy, d4 y0, d5 n (keeps d0-d6)
m72r_xcore:
	movem.l	d0-d6,-(sp)
	move.w	d0,d6
	add.w	d1,d6
	subq.w	#1,d6			; the last pixel
	move.w	d6,d7
	lsr.w	#4,d7
	move.w	d0,a0
	move.w	d0,d1
	lsr.w	#4,d1
	sub.w	d1,d7
	addq.w	#1,d7			; nd: destination words a line
	move.w	d7,BLT_XC.w
	; the end masks
	moveq	#15,d1
	and.w	d0,d1
	moveq	#-1,d2
	lsr.w	d1,d2			; END1
	not.w	d6
	and.w	#15,d6
	moveq	#-1,d1
	lsl.w	d6,d1			; END3
	cmp.w	#1,d7
	bne	.e
	and.w	d1,d2
.e:	move.w	d2,BLT_E1.w
	move.w	#$ffff,BLT_E2.w
	move.w	d1,BLT_E3.w
	; the destination reads a line (for the pieces): all words when the op reads it, else the partial end words
	moveq	#0,d6
	move.b	m72r_x_op,d6
	move.w	#%0110100111110110,d0	; (ops 1 2 4 5 6 7 8 9 10 11 13 14 read the destination)
	btst	d6,d0
	beq	.nr
	move.w	d7,d6
	bra	.dr
.nr:	moveq	#0,d6
	cmp.w	#$ffff,d2
	beq	.nr1
	addq.w	#1,d6
.nr1:	cmp.w	#1,d7
	beq	.dr
	cmp.w	#$ffff,d1
	beq	.dr
	addq.w	#1,d6
.dr:	add.w	d7,d6			; + the writes
	; the source: skew, FXSR, increments, address
	move.l	(sp),d0			; (dx)
	movem.l	8(sp),d2-d3		; (sx, sy)
	move.b	m72r_x_sk,d1
	beq	.img
	cmp.b	#3,d1
	beq	.nos
	; the temporary rows (aligned with the destination's words)
	clr.b	BLT_SKEW.w
	move.w	#2,BLT_SXI.w
	move.w	m72r_tnd,d1
	sub.w	d7,d1
	add.w	d1,d1
	addq.w	#2,d1
	move.w	d1,BLT_SYI.w
	add.w	d7,d6			; (the source reads)
	lea	m72r_tmp,a1
	cmp.b	#1,m72r_x_sk
	beq	.t1
	lea	m72r_tmp2,a1
.t1:	bsr	m72r_tpos
	move.l	a1,m72r_x_s0
	bra	.dst
.nos:	clr.b	BLT_SKEW.w
	bra	.dst
.img:	moveq	#15,d1
	and.w	d2,d1			; sx & 15
	moveq	#15,d5
	and.w	d0,d5			; dx & 15
	move.w	d7,a1			; fetched = nd + fxsr
	cmp.w	d5,d1
	bls	.nf
	addq.w	#1,a1
	sub.w	d1,d5
	and.w	#15,d5
	or.w	#BLT_FXSR,d5
	bra	.sk
.nf:	sub.w	d1,d5
.sk:	move.b	d5,BLT_SKEW.w
	move.w	#1024,BLT_SXI.w
	move.w	a1,d1
	add.w	d1,d6			; (the source reads)
	subq.w	#1,d1
	moveq	#10,d5
	lsl.w	d5,d1
	neg.w	d1
	addq.w	#2,d1
	move.w	d1,BLT_SYI.w
	move.l	m72r_x_src,a1
	move.w	d2,d1
	lsr.w	#4,d1
	moveq	#10,d5
	lsl.l	d5,d1
	and.l	#$ffff,d1
	add.l	d1,a1
	add.w	d3,a1
	add.w	d3,a1
	move.l	a1,m72r_x_s0
.dst:	; the destination
	tst.b	m72r_x_dk
	bne	.dt
	move.w	#8,BLT_DXI.w
	move.w	d7,d1
	subq.w	#1,d1
	lsl.w	#3,d1
	neg.w	d1
	add.w	#M72_LB,d1
	move.w	d1,BLT_DYI.w
	move.l	m72r_dbuf,a1
	move.l	16(sp),d1		; (y0)
	add.w	#M72_G,d1
	ext.l	d1
	moveq	#9,d5
	lsl.l	d5,d1
	add.l	d1,a1
	move.w	d0,d1
	lsr.w	#4,d1
	lsl.w	#3,d1
	add.w	d1,a1
	move.l	#2,m72r_x_dstep
	bra	.go
.dt:	move.w	#2,BLT_DXI.w
	move.w	m72r_tnd,d1
	sub.w	d7,d1
	add.w	d1,d1
	addq.w	#2,d1
	move.w	d1,BLT_DYI.w
	lea	m72r_tmp,a1
	cmp.b	#1,m72r_x_dk
	beq	.d1
	lea	m72r_tmp2,a1
.d1:	move.l	(sp),d0
	move.l	16(sp),d4
	bsr	m72r_tpos
	clr.l	m72r_x_dstep
.go:	; the lines a piece: 256 bus cycles / (4 x accesses a line)
	lsl.w	#2,d6
	move.l	#256,d1
	divu	d6,d1
	tst.w	d1
	bne	.p1
	moveq	#1,d1
.p1:	move.w	d1,m72r_x_piece
	move.b	#2,BLT_HOP.w
	cmp.b	#3,m72r_x_sk
	bne	.hp
	clr.b	BLT_HOP.w		; (no source: all ones, the op ignores it)
.hp:
	move.b	m72r_x_op,BLT_OP.w
	move.l	m72r_x_s0,a0
	move.w	m72r_x_planes,d6
	tst.b	m72r_x_dk
	beq	.pl
	moveq	#1,d6
.pl:	subq.w	#1,d6
	move.l	20(sp),d5		; (n)
.plane:	move.l	a0,BLT_SRC.w
	move.l	a1,BLT_DST.w
	move.w	d5,d2			; lines left
.piece:	move.w	m72r_x_piece,d3
	cmp.w	d3,d2
	bhs	.pc
	move.w	d2,d3
.pc:	move.w	d3,BLT_YC.w
	move.b	#BLT_GO,BLT_CTRL.w
	sub.w	d3,d2
	bne	.piece
	add.l	m72r_x_sstep,a0
	add.l	m72r_x_dstep,a1
	dbf	d6,.plane
	movem.l	(sp)+,d0-d6
	rts

; m72r_tpos: a1 = the temporary rows' address of buffer x d0, picture line d4
m72r_tpos:
	move.w	d4,d1
	sub.w	m72r_ty0,d1
	mulu	m72r_tnd,d1
	move.w	d0,d5
	lsr.w	#4,d5
	sub.w	m72r_tw0,d5
	add.w	d5,d1
	add.w	d1,d1
	add.w	d1,a1
	rts

; m72r_bodfix: the runs of m72r_runl (cells with BG pixels drawn over FG's under pixels, segment a3) after FG was drawn
; over BG: tmp = BG bod & FG opaque & ~FG over (the BG pixels that show over FG there); per plane: D &= ~tmp, D |= (BG &
; tmp)
m72r_bodfix:
	ifd	M72_STATS
	addq.l	#1,m72r_st_bod
	endc
	movem.l	d0-d7/a0-a6,-(sp)
	move.l	SG_BAND(a3),a4
	lea	m72r_runl,a2
	move.w	m72r_nrun,d7
	subq.w	#1,d7
.r:	move.w	(a2)+,d0
	move.w	(a2)+,d1
	sub.w	d0,d1
	lsl.w	#3,d0
	lsl.w	#3,d1
	move.w	d0,m72r_x_dx
	move.w	d1,m72r_x_w
	move.w	SG_Y0(a3),d2
	move.w	d2,m72r_x_y0
	move.w	d2,m72r_ty0
	move.w	SG_Y1(a3),d3
	sub.w	d2,d3
	move.w	d3,m72r_x_n
	move.w	d0,d2			; the temporary grid: the destination's words
	lsr.w	#4,d2
	move.w	d2,m72r_tw0
	add.w	d1,d0
	subq.w	#1,d0
	lsr.w	#4,d0
	sub.w	d2,d0
	addq.w	#1,d0
	move.w	d0,m72r_tnd
	; tmp = 0, |= BG bod, &= FG opaque, &= ~FG over
	move.b	#3,m72r_x_sk
	move.b	#1,m72r_x_dk
	move.b	#0,m72r_x_op
	bsr	.whole
	clr.b	m72r_x_sk
	move.w	#1,m72r_x_planes
	clr.l	m72r_x_sstep
	move.l	#m72r_imgb+5*M72_PL,m72r_x_src
	move.w	BT_OXB(a4),m72r_x_ox
	move.w	BT_OYB(a4),m72r_x_oy
	move.b	#7,m72r_x_op
	bsr	m72r_xfer
	move.l	#m72r_imgf+4*M72_PL,m72r_x_src
	move.w	BT_OXF(a4),m72r_x_ox
	move.w	BT_OYF(a4),m72r_x_oy
	move.b	#1,m72r_x_op
	bsr	m72r_xfer
	move.l	#m72r_imgf+5*M72_PL,m72r_x_src
	move.b	#4,m72r_x_op
	bsr	m72r_xfer
	; the planes
	moveq	#0,d6
.pl:	move.w	d6,m72r_bplane
	; D &= ~tmp
	move.b	#1,m72r_x_sk
	clr.b	m72r_x_dk
	move.w	#1,m72r_x_planes
	move.b	#4,m72r_x_op
	move.l	m72r_dbuf,-(sp)
	moveq	#0,d0
	move.w	d6,d0
	add.w	d0,d0
	add.l	d0,m72r_dbuf		; (plane k of the buffer)
	bsr	.whole
	move.l	(sp),m72r_dbuf
	; tmp2 = BG plane k, &= tmp
	clr.b	m72r_x_sk
	move.b	#2,m72r_x_dk
	move.b	#3,m72r_x_op
	move.w	d6,d0
	ext.l	d0
	moveq	#15,d1
	lsl.l	d1,d0
	add.l	#m72r_imgb,d0
	move.l	d0,m72r_x_src
	move.w	BT_OXB(a4),m72r_x_ox
	move.w	BT_OYB(a4),m72r_x_oy
	bsr	.whole
	move.b	#1,m72r_x_sk
	move.b	#1,m72r_x_op
	bsr	.whole
	; D |= tmp2
	move.b	#2,m72r_x_sk
	clr.b	m72r_x_dk
	move.b	#7,m72r_x_op
	moveq	#0,d0
	move.w	d6,d0
	add.w	d0,d0
	add.l	d0,m72r_dbuf
	bsr	.whole
	move.l	(sp)+,m72r_dbuf
	addq.w	#1,d6
	cmp.w	#4,d6
	blo	.pl
	dbf	d7,.r
	movem.l	(sp)+,d0-d7/a0-a6
	rts
; the whole words of the run (the temporary rows are kept 0 outside it)
.whole:	move.w	m72r_x_dx,d0
	move.w	m72r_x_w,d1
	move.w	m72r_tw0,d2
	lsl.w	#4,d2
	move.w	m72r_tnd,d3
	lsl.w	#4,d3
	move.w	d2,m72r_x_dx
	move.w	d3,m72r_x_w
	bsr	m72r_xfer
	move.w	d0,m72r_x_dx
	move.w	d1,m72r_x_w
	rts


; ======================================================================================================================
; sprites
; ======================================================================================================================
; The list from entry 0 on (the arcade draws from the last entry and the first pixel drawn wins: the STE paints the
; other way round), each entry w x h pieces of 16 x 16.  A piece in a colour, flipped or not in x, is converted once
; into the cache (m72r_pool): its opaque rows' masks, then their 4 plane words, so the Blitter's source runs on from
; line to line.  A line is one HOG pass (Y count 4: the planes), the mask shifted into END1/END3.  Clipped at the
; 16-pixel groups nearest the window's edges (the inner word only: one-word passes), culled when wholly outside; top
; and bottom whole into the guard lines.  A piece over tiles with pixels over the sprites (MAME's priority) takes those
; pixels out of its masks line by line (from the layer images' over planes).  The background under the pieces is
; saved (m72r_ssave) and restored before the buffer's next composition (m72r_srestore).
;
; Rows reordered by equal masks (stefastbobs2's source order) were measured and not kept: in R-Type's and Mr. HELI's
; 4096 pieces the mask changes from one opaque row to the next in 69% / 48% of the rows in their own order and 62% /
; 43% with equal masks grouped (one mask write pair saved per piece on average), while a reordered piece needs a
; destination step per line (add.w #imm,(a4): 4 cycles a line more than the constant step in d4) and its own source
; order for the priority and clip paths; the generated routines already write a mask only where it changes.
; m72r_sprites: the sprites into the buffer.  1. the pieces in the list's order (m72r_plist: code, attribute, buffer
; x, picture line; empty and wholly outside pieces left out); 2. the background under each saved (m72r_ssave: all
; before any is drawn, so the next picture of this buffer restores them in any order: m72r_srestore, before the
; composition); 3. each drawn (m72r_pdraw): a whole piece without priority pixels by its generated routine
; (m72r_gcache: stefastbobs2's unrolled line passes, the end masks as immediates, written only where they change),
; the others (clipped at CL / CR, or with priority pixels) by m72r_sdraw's line loop.
m72r_sprites:
	ifd	M72_NOSPR
	rts
	endif
	move.l	a5,-(sp)
	move.w	m72r_W,d0
	move.w	d0,d1
	and.w	#$fff0,d0
	move.w	d0,m72r_cl		; the clip groups: CL .. CR - 1
	add.w	#320+15,d1
	and.w	#$fff0,d1
	move.w	d1,m72r_cr
	ifd	M72_NOCLIP
	clr.w	m72r_cl			; (a test: the clipping off; tools/sprite_test.py must fail)
	move.w	#1024,m72r_cr
	endc
	lea	m72r_plist,a4
	lea	m72r_su,a2
	lea	m72v_spr,a1
	lea	m72v_spr+128*8,a5	; (the list's end)
.e0:	move.l	a5,d7
	sub.l	a1,d7
	lsr.w	#3,d7
	subq.w	#1,d7			; entries left - 1
	bmi	.done
.e1:	move.l	(a1)+,d0		; (an empty entry: all 0)
	or.l	(a1)+,d0
	dbne	d7,.e1
	beq	.done
	lea	-8(a1),a0
	ifd	M72_STATS
	addq.l	#1,m72r_st_ent
	endif
	moveq	#0,d6
	move.b	5(a0),d6		; the attribute's high byte: log2 w (bits 7-6), log2 h (5-4), flip x (3), flip y (2)
	move.w	d6,d0
	lsr.w	#6,d0
	moveq	#1,d5
	lsl.w	d0,d5			; w
	move.w	d5,d0			; (the next entry: w on)
	subq.w	#1,d0
	lsl.w	#3,d0
	add.w	d0,a1
	cmp.l	a5,a1
	bls	.in
	move.l	a5,a1
.in:	lsr.w	#4,d6
	and.w	#3,d6
	moveq	#16,d0
	lsl.w	d6,d0
	move.w	d0,d6			; 16 h
	moveq	#0,d0
	move.b	(a0),d0			; y
	btst	#0,1(a0)
	beq	.y
	add.w	#256,d0
.y:	move.w	#384,d4
	sub.w	d0,d4
	sub.w	d6,d4			; the top line
	cmp.w	#256,d4
	bge	.e0
	move.w	d4,d0
	add.w	d6,d0
	ble	.e0
	moveq	#3,d3			; x
	and.b	7(a0),d3
	lsl.w	#8,d3
	move.b	6(a0),d3
	sub.w	#256+96,d3
	add.w	m72r_W,d3		; buffer x
	cmp.w	m72r_cr,d3
	bge	.e0
	move.w	d5,d0
	lsl.w	#4,d0
	add.w	d3,d0
	cmp.w	m72r_cl,d0
	ble	.e0
	ifd	M72_STATS
	addq.l	#1,m72r_st_entin
	endif
	move.w	4(a0),d2		; attribute
	ror.w	#8,d2
	move.w	2(a0),d1		; code
	ror.w	#8,d1
	lsr.w	#4,d6			; h
	; the pieces: column d7 (px), row a5 (py); code + 8 a column + 1 a row, flipped
	movem.l	a1/a5,-(sp)
	moveq	#0,d7
.pxl:	move.w	d7,d0
	lsl.w	#4,d0
	add.w	d3,d0			; the column's buffer x
	cmp.w	m72r_cr,d0
	bge	.pxd			; (the next columns are further right)
	move.w	d0,a6
	add.w	#16,d0
	cmp.w	m72r_cl,d0
	ble	.pxn
	move.w	d7,d0
	btst	#11,d2
	beq	.fx
	move.w	d5,d0
	subq.w	#1,d0
	sub.w	d7,d0
.fx:	lsl.w	#3,d0
	add.w	d1,d0
	move.w	d0,a3			; the column's code
	sub.l	a5,a5
.pyl:	move.w	a5,d0
	lsl.w	#4,d0
	add.w	d4,d0			; picture line
	cmp.w	#-16,d0
	ble	.pyn
	cmp.w	#256,d0
	bge	.pxn			; (the next rows are further down)
	move.w	d0,a0
	move.w	a5,d0
	btst	#10,d2
	beq	.fy
	move.w	d6,d0
	subq.w	#1,d0
	sub.w	a5,d0
.fy:	add.w	a3,d0
	and.w	#4096-1,d0
	ifd	M72_STATS
	addq.l	#1,m72r_st_pc
	endif
	move.w	d0,(a4)
	lsl.w	#2,d0
	cmp.b	#255,2(a2,d0.w)		; an empty piece?
	beq	.pyn
	addq.l	#2,a4
	move.w	d2,(a4)+
	move.w	a6,(a4)+
	move.w	a0,(a4)+
.pyn:	addq.w	#1,a5
	cmp.w	a5,d6
	bhi	.pyl
.pxn:	addq.w	#1,d7
	cmp.w	d5,d7
	blo	.pxl
.pxd:	movem.l	(sp)+,a1/a5
	bra	.e0
.done:	move.l	a4,d0
	sub.l	#m72r_plist,d0
	lsr.l	#3,d0
	move.w	d0,m72r_np
	beq	.x
	ifd	M72_STATS
	add.l	d0,m72r_st_drawn
	endif
	bsr	m72r_usprites		; (their pens in use; new ones looked at before they are drawn: m72r_sdiv)
	movem.l	d0-d3/a0-a1,-(sp)
	lea	m72r_umask,a0
	lea	m72r_suse,a1
	moveq	#0,d0
	moveq	#16-1,d1
.su:	move.w	(a0),d2
	clr.w	(a0)+
	move.w	(a1),d3
	not.w	d3
	and.w	d3,d2			; (the new ones)
	beq	.sn
	or.w	d2,(a1)
	moveq	#1,d0
	move.w	d1,-(sp)
	moveq	#15,d3
	sub.w	d1,d3
	lsl.w	#4,d3			; (the row's first pen)
	bsr	m72r_pnew
	move.w	(sp)+,d1
.sn:	addq.l	#2,a1
	dbf	d1,.su
	tst.w	d0
	beq	.so
	st	m72r_sonly		; (the sprites' pens only: the tiles of this picture are drawn already)
	bsr	m72r_sdiv
	clr.b	m72r_sonly
.so:	movem.l	(sp)+,d0-d3/a0-a1
	bsr	m72r_ssave
	move.l	m72r_cbs,a0		; (any priority cell? none: m72r_spri skipped)
	lea	BS_PRI(a0),a0
	moveq	#0,d0
	moveq	#256/4-1,d1
.pr:	or.l	(a0)+,d0
	dbf	d1,.pr
	tst.l	d0
	sne	m72r_anypri
	move.b	#2,BLT_HOP.w
	move.b	#3,BLT_OP.w
	move.w	#2,BLT_SXI.w
	move.w	#8,BLT_DXI.w
	lea	m72r_plist,a1
	lea	m72r_psaved,a0
	move.w	m72r_np,d7
	subq.w	#1,d7
.dr:	move.w	(a1)+,m72r_pcode
	move.w	(a1)+,m72r_sattr
	move.w	(a1)+,m72r_bx
	move.w	(a1)+,m72r_by
	move.b	(a0)+,m72r_psv
	movem.l	d7/a0-a1,-(sp)
	bsr	m72r_pdraw
	movem.l	(sp)+,d7/a0-a1
	dbf	d7,.dr
.x:	move.l	(sp)+,a5
	rts

; m72r_srect: the rectangle a piece's save covers (m72r_plist record a1): d0.l = its buffer address, d1 = its words a
; line (4: one word group, 8: two), d2 = its lines.  Destroys d3, a0.
m72r_srect:
	move.w	(a1),d0
	lsl.w	#2,d0
	lea	m72r_su,a0
	add.w	d0,a0
	moveq	#0,d2
	move.b	3(a0),d2		; y1
	moveq	#0,d3
	move.b	2(a0),d3		; y0
	move.w	6(a1),d0		; the piece's line
	btst	#10,2(a1)		; (attribute bit 10, its high byte first: flip y)
	beq	.ny
	add.w	#15,d0
	sub.w	d2,d0			; flipped: the first line is by + 15 - y1
	bra	.n
.ny:	add.w	d3,d0
.n:	sub.w	d3,d2
	addq.w	#1,d2			; lines
	add.w	#M72_G,d0
	ext.l	d0
	moveq	#9,d3
	lsl.l	d3,d0
	add.l	m72r_dbuf,d0
	move.w	4(a1),d3		; buffer x
	moveq	#8,d1
	cmp.w	m72r_cl,d3
	bge	.l
	move.w	m72r_cl,d3		; left clip: the inner word only
	moveq	#4,d1
	bra	.w
.l:	add.w	#16,d3
	cmp.w	m72r_cr,d3
	bgt	.rc
	sub.w	#16,d3
	bra	.r
.rc:	sub.w	#16,d3
	moveq	#4,d1			; right clip: the first word only
	bra	.w
.r:	moveq	#15,d1
	and.w	d3,d1
	sne	d1
	and.w	#4,d1
	addq.w	#4,d1			; skew 0: one word group
.w:	asr.w	#4,d3
	lsl.w	#3,d3
	ext.l	d3
	add.l	d3,d0
	rts

; m72r_ssave: the background under every piece of m72r_plist copied to the buffer's save area (m72r_svp + buffer *
; M72_SVSZ; the list m72r_svl, the count m72r_svc); m72r_psaved: 1 saved, 0 not (no room: its cells marked as damage)
M72_SVSZ	= 32*1024
M72_SVN		= 160
m72r_ssave:
	ifd	M72_NOSAVE
	lea	m72r_psaved,a0		; (a test: every piece's cells marked as damage, recomposed)
	move.w	m72r_np,d0
	subq.w	#1,d0
.z:	clr.b	(a0)+
	dbf	d0,.z
	rts
	endif
	movem.l	d0-d7/a0-a6,-(sp)
	move.w	m72r_draw,d0
	move.w	d0,d1
	mulu	#M72_SVN*12,d1
	lea	m72r_svl,a2
	add.l	d1,a2			; the list
	mulu	#M72_SVSZ,d0
	lea	m72r_svp,a3
	add.l	d0,a3			; the area
	move.l	a3,a6
	add.l	#M72_SVSZ,a6		; its end
	moveq	#0,d6			; the count
	move.b	#2,BLT_HOP.w
	move.b	#3,BLT_OP.w
	moveq	#-1,d0
	move.l	d0,BLT_E1.w
	move.w	d0,BLT_E3.w
	move.w	#2,BLT_SXI.w
	move.w	#2,BLT_DXI.w
	move.w	#2,BLT_DYI.w
	clr.b	BLT_SKEW.w
	lea	m72r_plist,a1
	lea	m72r_psaved,a4
	move.w	m72r_np,d7
	subq.w	#1,d7
.p:	bsr	m72r_srect
	clr.b	(a4)
	cmp.w	#M72_SVN,d6
	bhs	.n
	move.w	d1,d3
	mulu	d2,d3
	add.w	d3,d3			; bytes
	lea	(a3,d3.w),a5
	cmp.l	a6,a5
	bhi	.n
	st	(a4)
	move.l	d0,(a2)+		; the record: buffer address, save address, words, lines
	move.l	a3,(a2)+
	move.w	d1,(a2)+
	move.w	d2,(a2)+
	addq.w	#1,d6
	move.w	d1,BLT_XC.w
	move.w	d1,d3
	add.w	d3,d3
	neg.w	d3
	add.w	#M72_LB+2,d3
	move.w	d3,BLT_SYI.w		; 512 - (words - 1) * 2
	move.l	d0,BLT_SRC.w
	move.l	a3,BLT_DST.w
	moveq	#8,d3			; lines a pass: 32 / words (a pass at most 256 bus cycles: 64 accesses)
	cmp.w	#8,d1
	bne	.lp
	moveq	#4,d3
.lp:	move.w	d2,d0
.ps:	cmp.w	d3,d0
	bhs	.p1
	move.w	d0,d3
.p1:	move.w	d3,BLT_YC.w
	move.b	#BLT_GO,BLT_CTRL.w
	sub.w	d3,d0
	bne	.ps
	move.l	a5,a3
.n:	addq.l	#8,a1
	addq.l	#1,a4
	dbf	d7,.p
	move.w	m72r_draw,d0
	add.w	d0,d0
	lea	m72r_svc,a0
	move.w	d6,(a0,d0.w)
	movem.l	(sp)+,d0-d7/a0-a6
	rts

; m72r_srestore: the backgrounds saved under the sprites of the buffer's last picture copied back (before the
; composition: the buffer is then what that composition left)
m72r_srestore:
	movem.l	d0-d3/a0-a1,-(sp)
	move.w	m72r_draw,d0
	move.w	d0,d1
	add.w	d1,d1
	lea	m72r_svc,a0
	add.w	d1,a0
	move.w	(a0),d3
	beq	.x
	clr.w	(a0)
	mulu	#M72_SVN*12,d0
	lea	m72r_svl,a1
	add.l	d0,a1
	move.b	#2,BLT_HOP.w
	move.b	#3,BLT_OP.w
	moveq	#-1,d0
	move.l	d0,BLT_E1.w
	move.w	d0,BLT_E3.w
	move.w	#2,BLT_SXI.w
	move.w	#2,BLT_SYI.w
	move.w	#2,BLT_DXI.w
	clr.b	BLT_SKEW.w
	subq.w	#1,d3
.r:	move.l	(a1)+,BLT_DST.w
	move.l	(a1)+,BLT_SRC.w
	move.w	(a1)+,d1
	move.w	d1,BLT_XC.w
	add.w	d1,d1
	neg.w	d1
	add.w	#M72_LB+2,d1
	move.w	d1,BLT_DYI.w
	moveq	#8,d2			; lines a pass: 32 / words
	cmp.w	#M72_LB+2-16,d1
	bne	.lp
	moveq	#4,d2
.lp:	move.w	(a1)+,d0
.ps:	cmp.w	d2,d0
	bhs	.p1
	move.w	d0,d2
.p1:	move.w	d2,BLT_YC.w
	move.b	#BLT_GO,BLT_CTRL.w
	sub.w	d2,d0
	bne	.ps
	dbf	d3,.r
.x:	movem.l	(sp)+,d0-d3/a0-a1
	rts

; m72r_pdraw: piece m72r_pcode (m72r_sattr, at buffer x m72r_bx, picture line m72r_by; m72r_psv: its background saved)
m72r_pdraw:
	ifd	M72_NODRAW
	rts
	endif
	move.l	m72r_cbs,a5
	; the priority: tiles with pixels over the sprites (or a band with the display off) under the piece?
	clr.b	m72r_spri_on
	tst.b	m72r_anypri
	beq	.nopri
	bsr	m72r_spri
.nopri:
	tst.b	m72r_psv
	bne	.dx
	; not saved: the damage, the cells of rows by >> 3 .. (by + 15) >> 3, columns max(bx, CL) >> 3 ..
	; min(bx + 15, CR - 1) >> 3 (2 or 3 cells: a mask over two bytes of each row)
	move.w	m72r_bx,d0
	cmp.w	m72r_cl,d0
	bge	.d0
	move.w	m72r_cl,d0
.d0:	lsr.w	#3,d0			; c0
	move.w	m72r_bx,d1
	add.w	#15,d1
	cmp.w	m72r_cr,d1
	blt	.d1
	move.w	m72r_cr,d1
	subq.w	#1,d1
.d1:	lsr.w	#3,d1
	sub.w	d0,d1			; cells - 1
	add.w	d1,d1
	move.w	.dm(pc,d1.w),d4		; the cells' bits from the left
	moveq	#7,d1
	and.w	d0,d1
	lsr.w	d1,d4			; at c0's bit
	lsr.w	#3,d0			; c0's byte
	move.w	d4,d5
	lsr.w	#8,d5			; (the first byte's bits; d4's low byte: the next byte's)
	move.w	m72r_by,d2
	asr.w	#3,d2
	addq.w	#2,d2			; the first damage row (-2 .. 33 -> 0 .. 35)
	move.w	m72r_by,d3
	add.w	#15,d3
	asr.w	#3,d3
	addq.w	#2,d3
	lea	BS_DMG(a5),a0
.dr:	cmp.w	#36,d2
	bhs	.dn
	move.w	d2,d1
	lsl.w	#4,d1
	add.w	d0,d1
	or.b	d5,(a0,d1.w)
	or.b	d4,1(a0,d1.w)
.dn:	addq.w	#1,d2
	cmp.w	d3,d2
	ble	.dr
	bra	.dx
.dm:	dc.w	$8000,$c000,$e000
.dx:	bsr	m72r_scache		; -> a2 = the entry
	ifd	M72_STATS
	move.w	m72r_bx,d0
	cmp.w	m72r_cl,d0
	blt	.stc
	add.w	#16,d0
	cmp.w	m72r_cr,d0
	ble	.stn
.stc:	addq.l	#1,m72r_st_clip
.stn:
	endif
	tst.b	m72r_spri_on
	bne	.slow
	ifd	M72_NOGEN
	bra	.slow
	endif
	bsr	m72r_gdraw		; (whole, no priority: the generated routine; else d0 = 0)
	tst.w	d0
	bne	.out
.slow:	bsr	m72r_mcache		; -> a0 = the mask stream of the skew
	tst.b	m72r_spri_on
	beq	.np
	bsr	m72r_sprio		; (the tiles' over pixels out of the masks: a0 = a stream of this piece)
.np:	bsr	m72r_sdraw
.out:	rts

; m72r_gdraw: a whole piece (cache entry a2) by its generated routine; d0 = 0 when it cannot (clipped)
m72r_gdraw:
	move.w	m72r_bx,d1
	cmp.w	m72r_cl,d1
	blt	.no
	add.w	#16,d1
	cmp.w	m72r_cr,d1
	bgt	.no
	moveq	#0,d0
	move.b	(a2),d0			; y0
	moveq	#0,d5
	move.b	1(a2),d5
	sub.w	d0,d5			; rows - 1
	move.w	m72r_by,d2
	move.w	#M72_LB-8,d4		; the step from line to line (the passes end 8 bytes on)
	btst	#10,m72r_sattr
	beq	.ny
	add.w	#15,d2
	sub.w	d0,d2
	move.w	#-M72_LB-8,d4
	bra	.ly
.ny:	add.w	d0,d2
.ly:	add.w	#M72_G,d2
	ext.l	d2
	moveq	#9,d3
	lsl.l	d3,d2
	move.l	m72r_dbuf,a1
	add.l	d2,a1
	move.w	m72r_bx,d3
	asr.w	#4,d3
	lsl.w	#3,d3
	add.w	d3,a1			; the first line's first word
	ext.l	d4
	move.w	d5,d1
	addq.w	#1,d1
	add.w	d1,d1
	lea	2(a2,d1.w),a3		; the planes
	bsr	m72r_gcache		; -> a0 = the routine
	move.l	a3,BLT_SRC.w
	move.l	a1,BLT_DST.w
	moveq	#15,d0
	and.w	m72r_bx,d0		; skew
	beq	.s0
	move.w	#2,BLT_XC.w
	move.w	#2,BLT_SYI.w
	move.w	#-6,BLT_DYI.w
	or.b	#BLT_NFSR,d0
	move.b	d0,BLT_SKEW.w
	bra	.go
.s0:	move.w	#1,BLT_XC.w
	move.w	#2,BLT_SYI.w
	move.w	#2,BLT_DYI.w
	clr.b	BLT_SKEW.w
.go:	lea	BLT_E1.w,a2
	lea	BLT_E3.w,a3
	lea	BLT_DST.w,a4
	lea	BLT_YC.w,a5
	lea	BLT_CTRL.w,a6
	moveq	#4,d2
	moveq	#BLT_GO-256,d3
	jsr	(a0)
	ifd	M72_STATS
	addq.l	#1,m72r_st_fast
	endif
	moveq	#1,d0
	rts
.no:	moveq	#0,d0
	rts

; m72r_gcache: a0 = the generated routine of the piece's code, flip x and skew (m72r_pcode, m72r_sattr, m72r_bx & 15),
; generated from the cache entry a2's masks when missing.  Per line: move.w #END1,(a2) and move.w #END3,(a3) where
; they differ from the line before, move.w d2,(a5) (Y count 4: the planes), move.b d3,(a6) (go, HOG), add.l d4,(a4)
; (the next line's destination); rts.  Keeps d4, a1-a3.
M72_GPOOL	= 64*1024
M72_GHASH	= 1024
m72r_gcache:
	moveq	#0,d0
	move.w	m72r_pcode,d0
	moveq	#15,d1
	and.w	m72r_bx,d1
	move.l	d1,d2
	lsl.w	#1,d2
	btst	#11,m72r_sattr
	beq	.k
	addq.w	#1,d2
.k:	moveq	#12,d3
	lsl.l	d3,d2
	or.l	d0,d2			; key: skew, flip x, code
	addq.l	#1,d2			; (never 0)
	move.w	d0,d3			; the slot
	eor.w	d1,d3
	move.w	d1,d6
	lsl.w	#5,d6
	eor.w	d6,d3
	btst	#11,m72r_sattr
	beq	.s
	eor.w	#$200,d3
.s:	and.w	#M72_GHASH-1,d3
	lsl.w	#3,d3
	lea	m72r_ghash,a0
	add.w	d3,a0
	cmp.l	(a0),d2
	bne	.miss
	move.l	4(a0),a0
	rts
.miss:
	ifd	M72_STATS
	addq.l	#1,m72r_st_gmiss
	endif
	move.l	m72r_gpoolp,a4
	move.l	a4,d3
	add.l	#16*14+2,d3
	cmp.l	#m72r_gpool+M72_GPOOL,d3
	bls	.room
	move.l	a0,-(sp)		; (full: empty it)
	bsr	m72r_gflush
	move.l	(sp)+,a0
	move.l	m72r_gpoolp,a4
.room:	move.l	d2,(a0)
	move.l	a4,4(a0)
	move.l	a4,a0
	moveq	#0,d5
	move.b	1(a2),d5
	sub.b	(a2),d5			; rows - 1
	lea	2(a2),a5		; the masks
	moveq	#16,d6
	sub.w	d1,d6			; 16 - skew
	moveq	#-1,d2			; (END1, END3 before: none)
	moveq	#-1,d3
.l:	moveq	#0,d0
	move.w	(a5)+,d0
	move.l	d0,d7
	lsr.w	d1,d0			; END1
	cmp.l	d0,d2
	beq	.e1
	move.w	#$34bc,(a4)+		; move.w #END1,(a2)
	move.w	d0,(a4)+
	move.l	d0,d2
.e1:	tst.w	d1
	beq	.e3
	lsl.w	d6,d7			; END3
	cmp.l	d7,d3
	beq	.e3
	move.w	#$36bc,(a4)+		; move.w #END3,(a3)
	move.w	d7,(a4)+
	move.l	d7,d3
.e3:	move.l	#$3a821c83,(a4)+	; move.w d2,(a5); move.b d3,(a6)
	tst.w	d5
	beq	.last
	move.w	#$d994,(a4)+		; add.l d4,(a4)
	subq.w	#1,d5
	bra	.l
.last:	move.w	#$4e75,(a4)+		; rts
	move.l	a4,m72r_gpoolp
	rts

; m72r_gflush: the generated routines: none
m72r_gflush:
	movem.l	d0/a0,-(sp)
	lea	m72r_ghash,a0
	move.w	#M72_GHASH-1,d0
.c:	clr.l	(a0)+
	clr.l	(a0)+
	dbf	d0,.c
	move.l	#m72r_gpool,m72r_gpoolp
	movem.l	(sp)+,d0/a0
	rts

; m72r_scache: a2 = the cache entry of piece m72r_pcode in the entry's colour and flip x (converted when missing)
m72r_scache:
	move.w	m72r_sattr,d1
	and.w	#15,d1			; colour
	move.w	m72r_pcode,d0
	moveq	#0,d2
	move.w	d1,d2			; (the epoch: the choice's + the colour row's remaps, m72r_sdiv)
	add.w	d2,d2
	lea	m72r_scver,a0
	move.w	(a0,d2.w),d2
	add.w	m72r_epoch,d2
	move.w	d2,m72r_skv
	lsl.l	#4,d2
	or.w	d1,d2
	lsl.l	#1,d2
	btst	#11,m72r_sattr
	beq	.k
	addq.l	#1,d2
.k:	lsl.l	#8,d2
	lsl.l	#4,d2
	or.w	d0,d2			; key: epoch, colour, flip x, code
	move.w	d0,d3			; the slot
	lsl.w	#4,d1
	eor.w	d1,d3
	btst	#11,m72r_sattr
	beq	.s
	eor.w	#$400,d3
.s:	move.w	m72r_skv,d1		; (the version too: a colour cycle's mappings in different slots)
	rol.w	#7,d1
	eor.w	d1,d3
	and.w	#M72_HASH-1,d3
	lsl.w	#3,d3
	lea	m72r_hash,a0
	add.w	d3,a0
	cmp.l	(a0),d2
	bne	.miss
	move.l	4(a0),a2
	rts
.miss:	move.l	d2,(a0)
	move.l	m72r_poolp,a2
	move.l	a2,d3
	add.l	#2+16*10,d3
	cmp.l	#m72r_pool+M72_POOL,d3
	bls	.room
	move.l	a0,-(sp)
	bsr	m72r_sflush		; (full: start again)
	move.l	(sp)+,a0
	move.l	d2,(a0)
	move.l	m72r_poolp,a2
.room:	move.l	a2,4(a0)
	bsr	m72r_sconv
	rts

; m72r_sconv: convert piece m72r_pcode (colour, flip x of m72r_sattr) into the cache entry a2 (m72r_poolp advanced);
; keeps a2
m72r_sconv:
	addq.l	#1,m72r_nsconv
	movem.l	d0-d7/a0-a6,-(sp)
	move.w	m72r_pcode,d0
	lea	m72r_su,a0
	move.w	d0,d1
	lsl.w	#2,d1
	moveq	#0,d4
	move.b	2(a0,d1.w),d4		; first opaque row
	moveq	#0,d5
	move.b	3(a0,d1.w),d5		; last
	move.b	d4,(a2)
	move.b	d5,1(a2)
	sub.w	d4,d5			; rows - 1
	move.w	d5,d7
	addq.w	#1,d7
	lea	2(a2),a3		; the masks
	add.w	d7,d7
	lea	(a3,d7.w),a4		; the planes
	move.w	d5,d7
	addq.w	#1,d7
	mulu	#10,d7
	lea	2(a2,d7.w),a1
	move.l	a1,m72r_poolp
	; the colour's table (built when missing)
	move.w	m72r_sattr,d1
	and.w	#15,d1
	lea	m72r_stv,a0
	tst.b	(a0,d1.w)
	bne	.tv
	st	(a0,d1.w)
	bsr	m72r_stbuild
.tv:	moveq	#10,d2
	lsl.w	d2,d1
	lea	m72r_stab,a5
	add.w	d1,a5			; 256 longs: two pixels' pens -> their 2 bits in each plane's byte
	lea	m72r_sopq,a6		; (and their opaque bits)
	; the rows: chunky source, 8 bytes a row
	lea	m72r_sp,a1
	moveq	#0,d1
	move.w	d0,d1
	lsl.l	#7,d1
	add.l	d1,a1
	lsl.w	#3,d4
	add.w	d4,a1			; the first opaque row
	moveq	#0,d4
	btst	#11,m72r_sattr
	bne	.fl
.row:	moveq	#0,d0
	moveq	#0,d2
	moveq	#0,d1
	rept	4
	move.b	(a1)+,d4
	lsl.w	#2,d4
	lsl.l	#2,d0
	or.l	(a5,d4.w),d0
	lsl.w	#2,d1
	or.w	2(a6,d4.w),d1
	moveq	#0,d4
	endr
	rept	4
	move.b	(a1)+,d4
	lsl.w	#2,d4
	lsl.l	#2,d2
	or.l	(a5,d4.w),d2
	lsl.w	#2,d1
	or.w	2(a6,d4.w),d1
	moveq	#0,d4
	endr
	movep.l	d0,0(a4)		; plane words: the high bytes from the left half, the low from the right
	movep.l	d2,1(a4)
	addq.l	#8,a4
	move.w	d1,(a3)+
	dbf	d5,.row
	movem.l	(sp)+,d0-d7/a0-a6
	rts
.fl:	lea	m72r_nswap,a0		; flip x: the bytes from the right, their pixels swapped
	addq.l	#8,a1
.frow:	moveq	#0,d0
	moveq	#0,d2
	moveq	#0,d1
	rept	4
	move.b	-(a1),d4
	move.b	(a0,d4.w),d4
	lsl.w	#2,d4
	lsl.l	#2,d0
	or.l	(a5,d4.w),d0
	lsl.w	#2,d1
	or.w	2(a6,d4.w),d1
	moveq	#0,d4
	endr
	rept	4
	move.b	-(a1),d4
	move.b	(a0,d4.w),d4
	lsl.w	#2,d4
	lsl.l	#2,d2
	or.l	(a5,d4.w),d2
	lsl.w	#2,d1
	or.w	2(a6,d4.w),d1
	moveq	#0,d4
	endr
	movep.l	d0,0(a4)
	movep.l	d2,1(a4)
	addq.l	#8,a4
	move.w	d1,(a3)+
	lea	16(a1),a1
	dbf	d5,.frow
	movem.l	(sp)+,d0-d7/a0-a6
	rts

; m72r_stbuild: colour d1's table m72r_stab + d1 * 1024: for the byte of two pens a (high nibble), b: the long with
; plane k's two bits (a's, b's) in byte 3 - k (plane 0 in the high byte); keeps d0-d1, a1-a6
m72r_stbuild:
	movem.l	d0-d7/a0-a6,-(sp)
	move.w	d1,d0
	lsl.w	#4,d0
	lea	m72r_pidx,a2
	add.w	d0,a2			; the colour's 16 pens' indices
	moveq	#10,d0
	lsl.w	d0,d1
	lea	m72r_stab,a0
	add.w	d1,a0
	lea	m72r_spread,a1
	moveq	#0,d6			; a
.a:	moveq	#0,d0
	move.b	(a2,d6.w),d0
	lsl.w	#2,d0
	move.l	(a1,d0.w),d2
	add.l	d2,d2			; a's bits: the left pixel
	moveq	#0,d7			; b
.b:	moveq	#0,d0
	move.b	(a2,d7.w),d0
	lsl.w	#2,d0
	move.l	(a1,d0.w),d3
	or.l	d2,d3
	move.l	d3,(a0)+
	addq.w	#1,d7
	cmp.w	#16,d7
	blo	.b
	addq.w	#1,d6
	cmp.w	#16,d6
	blo	.a
	movem.l	(sp)+,d0-d7/a0-a6
	rts

; m72r_stinit: the colour-independent tables: m72r_spread (an index's bits in the plane bytes), m72r_sopq (a byte's
; two pixels' opaque bits, in the low word of a long), m72r_nswap (a byte's nibbles swapped)
m72r_stinit:
	movem.l	d0-d3/a0,-(sp)
	lea	m72r_spread,a0
	moveq	#0,d0
.sp:	moveq	#0,d1
	btst	#0,d0
	beq	.s1
	or.l	#$01000000,d1
.s1:	btst	#1,d0
	beq	.s2
	or.l	#$00010000,d1
.s2:	btst	#2,d0
	beq	.s3
	or.w	#$0100,d1
.s3:	btst	#3,d0
	beq	.s4
	or.w	#$0001,d1
.s4:	move.l	d1,(a0)+
	addq.w	#1,d0
	cmp.w	#16,d0
	blo	.sp
	lea	m72r_sopq,a0
	moveq	#0,d0
.op:	moveq	#0,d1
	move.b	d0,d2
	and.b	#$f0,d2
	beq	.o1
	moveq	#2,d1
.o1:	move.b	d0,d2
	and.b	#$0f,d2
	beq	.o2
	addq.w	#1,d1
.o2:	move.l	d1,(a0)+
	addq.w	#1,d0
	cmp.w	#256,d0
	blo	.op
	lea	m72r_nswap,a0
	moveq	#0,d0
.ns:	move.b	d0,d1
	ror.b	#4,d1
	move.b	d1,(a0)+
	addq.w	#1,d0
	cmp.w	#256,d0
	blo	.ns
	movem.l	(sp)+,d0-d3/a0
	rts

; m72r_mcache: a0 = the mask stream of the piece's code, flip x and skew (m72r_bx & 15): END1 / END3 a row, the mask
; shifted (built from the cache entry a2 when missing: stefastbobs2's baked masks, the same for every colour)
m72r_mcache:
	moveq	#0,d0
	move.w	m72r_pcode,d0
	moveq	#15,d1
	and.w	m72r_bx,d1
	move.l	d1,d2
	lsl.w	#1,d2
	btst	#11,m72r_sattr
	beq	.k
	addq.w	#1,d2
.k:	moveq	#12,d3
	lsl.l	d3,d2
	or.l	d0,d2			; key: skew, flip x, code
	addq.l	#1,d2			; (never 0)
	move.w	d0,d3			; the slot
	eor.w	d1,d3
	move.w	d1,d4
	lsl.w	#5,d4
	eor.w	d4,d3
	and.w	#M72_MHASH-1,d3
	lsl.w	#3,d3
	lea	m72r_mhash,a0
	add.w	d3,a0
	cmp.l	(a0),d2
	bne	.miss
	move.l	4(a0),a0
	rts
.miss:
	ifd	M72_STATS
	addq.l	#1,m72r_st_mmiss
	endif
	move.l	m72r_mpoolp,a1
	move.l	a1,d3
	add.l	#16*4,d3
	cmp.l	#m72r_mpool+M72_MPOOL,d3
	bls	.room
	movem.l	d1-d2/a0,-(sp)		; (full: empty it)
	lea	m72r_mhash,a1
	move.w	#M72_MHASH-1,d3
.cl:	clr.l	(a1)+
	clr.l	(a1)+
	dbf	d3,.cl
	move.l	#m72r_mpool,m72r_mpoolp
	movem.l	(sp)+,d1-d2/a0
	move.l	m72r_mpoolp,a1
.room:	move.l	d2,(a0)
	move.l	a1,4(a0)
	move.l	a1,a0
	moveq	#0,d3
	move.b	1(a2),d3
	sub.b	(a2),d3			; rows - 1
	lea	2(a2),a3		; the masks
	moveq	#16,d4
	sub.w	d1,d4			; 16 - skew
	tst.w	d1
	bne	.sh
.s0:	move.w	(a3)+,(a1)+		; skew 0: END1 = the mask
	clr.w	(a1)+
	dbf	d3,.s0
	bra	.x
.sh:	move.w	(a3)+,d0
	move.w	d0,d2
	lsr.w	d1,d0
	lsl.w	d4,d2
	move.w	d0,(a1)+
	move.w	d2,(a1)+
	dbf	d3,.sh
.x:	move.l	a1,m72r_mpoolp
	rts

; m72r_sdraw: the piece's lines: cache entry a2, mask stream a0, at buffer x m72r_bx, picture line m72r_by (flip y from
; m72r_sattr); the source runs on from line to line (4 plane words a line), the masks come from the stream
m72r_sdraw:
	movem.l	a5-a6,-(sp)
	moveq	#0,d0
	move.b	(a2),d0			; y0
	moveq	#0,d7
	move.b	1(a2),d7
	sub.w	d0,d7			; rows - 1
	move.w	d7,d1
	addq.w	#1,d1
	add.w	d1,d1
	lea	2(a2,d1.w),a3		; the planes
	move.l	a3,BLT_SRC.w
	; the first line's address and the step
	move.w	m72r_by,d2
	move.l	#M72_LB,d6
	btst	#10,m72r_sattr
	beq	.ny
	add.w	#15,d2
	sub.w	d0,d2
	neg.l	d6
	bra	.ly
.ny:	add.w	d0,d2
.ly:	add.w	#M72_G,d2
	ext.l	d2
	moveq	#9,d3
	lsl.l	d3,d2
	move.l	m72r_dbuf,a1
	add.l	d2,a1
	move.w	m72r_bx,d3
	moveq	#15,d4
	and.w	d3,d4			; skew
	asr.w	#4,d3
	lsl.w	#3,d3
	add.w	d3,a1			; the first word
	lea	BLT_E1.w,a2
	lea	BLT_E3.w,a3
	lea	BLT_DST.w,a4
	lea	BLT_YC.w,a5
	lea	BLT_CTRL.w,a6
	moveq	#4,d2
	moveq	#BLT_GO-256,d3
	move.w	m72r_bx,d5
	tst.w	d4
	beq	.m1
	cmp.w	m72r_cl,d5
	blt	.ml
	add.w	#16,d5
	cmp.w	m72r_cr,d5
	bgt	.mr
	; two words
	move.w	#2,BLT_XC.w
	move.w	#2,BLT_SYI.w
	move.w	#-6,BLT_DYI.w
	or.b	#BLT_NFSR,d4
	move.b	d4,BLT_SKEW.w
.l2:	move.w	(a0)+,(a2)
	move.w	(a0)+,(a3)
	move.l	a1,(a4)
	move.w	d2,(a5)
	move.b	d3,(a6)
	add.l	d6,a1
	dbf	d7,.l2
	movem.l	(sp)+,a5-a6
	rts
.m1:	move.w	#1,BLT_XC.w		; one word (skew 0)
	move.w	#2,BLT_SYI.w
	move.w	#2,BLT_DYI.w
	clr.b	BLT_SKEW.w
.l1:	move.w	(a0)+,(a2)
	addq.l	#2,a0
	move.l	a1,(a4)
	move.w	d2,(a5)
	move.b	d3,(a6)
	add.l	d6,a1
	dbf	d7,.l1
	movem.l	(sp)+,a5-a6
	rts
.ml:	move.w	#1,BLT_XC.w		; the second word only: FXSR, the source's Y increment 0
	clr.w	BLT_SYI.w
	move.w	#2,BLT_DYI.w
	or.b	#BLT_FXSR,d4
	move.b	d4,BLT_SKEW.w
	addq.l	#8,a1
.lc:	addq.l	#2,a0
	move.w	(a0)+,(a2)
	move.l	a1,(a4)
	move.w	d2,(a5)
	move.b	d3,(a6)
	add.l	d6,a1
	dbf	d7,.lc
	movem.l	(sp)+,a5-a6
	rts
.mr:	move.w	#1,BLT_XC.w		; the first word only
	move.w	#2,BLT_SYI.w
	move.w	#2,BLT_DYI.w
	move.b	d4,BLT_SKEW.w
.rc:	move.w	(a0)+,(a2)
	addq.l	#2,a0
	move.l	a1,(a4)
	move.w	d2,(a5)
	move.b	d3,(a6)
	add.l	d6,a1
	dbf	d7,.rc
	movem.l	(sp)+,a5-a6
	rts

; m72r_spri: m72r_spri_on = the piece (m72r_bx, m72r_by) lies over a cell with tile pixels over the sprites or in a
; display-off band (BS_PRI: the composition's projections of the FG / BG pri flags, a row of 64 cells mod 64)
m72r_spri:
	clr.b	m72r_spri_on
	ifd	M72_NOPRI
	rts
	endif
	move.w	m72r_by,d0
	asr.w	#3,d0			; the first cell row
	move.w	m72r_by,d1
	add.w	#15,d1
	asr.w	#3,d1			; the last
	tst.w	d0
	bpl	.r0
	moveq	#0,d0
.r0:	cmp.w	#31,d1
	ble	.r1
	moveq	#31,d1
.r1:	sub.w	d0,d1			; rows - 1
	bmi	.x			; (wholly in the guard lines)
	move.w	m72r_bx,d2
	lsr.w	#3,d2
	and.w	#63,d2			; the first cell column (mod 64)
	moveq	#7,d3
	and.w	d2,d3
	lsr.w	#3,d2			; its byte
	move.w	#$e000,d4
	lsr.w	d3,d4			; the 3 cells in two bytes
	move.w	d2,d3
	addq.w	#1,d3
	and.w	#7,d3			; the next byte (mod 64)
	lsl.w	#3,d0
	move.l	m72r_cbs,a0
	lea	BS_PRI(a0),a0
	add.w	d0,a0
.r:	move.b	(a0,d2.w),d5
	lsl.w	#8,d5
	move.b	(a0,d3.w),d5
	and.w	d4,d5
	bne	.hit
	addq.l	#8,a0
	dbf	d1,.r
.x:	rts
.hit:	st	m72r_spri_on
	ifd	M72_STATS
	addq.l	#1,m72r_st_pri
	endif
	rts

; m72r_sprio: a0 = a copy of the mask stream a0 (END1 / END3 a row) with the tiles' over pixels taken out (FG plane 5 |
; BG plane 4 of the layer images, the 32 pixels from the piece's first word, each row's line; the columns found once a
; band; a band with the display off: the whole row); a2 = the cache entry (kept)
m72r_sprio:
	movem.l	d0-d7/a1-a4,-(sp)
	move.l	a0,a3			; the stream
	ifd	M72_NOFASTPRIO
	bra	.gen
	endif
	; the fast case: the piece's lines in one band (display on), the 3 columns of each over plane without a wrap,
	; their lines without a wrap: a pointer a layer, the lines in ascending order (flip y: the streams backwards)
	moveq	#0,d6
	move.b	(a2),d6			; y0
	moveq	#0,d7
	move.b	1(a2),d7
	sub.w	d6,d7			; rows - 1
	move.w	m72r_by,d2
	btst	#10,m72r_sattr
	beq	.fny
	add.w	#15,d2
	sub.w	d6,d2
	sub.w	d7,d2			; (flipped: the last row's line is the first)
	bra	.fl
.fny:	add.w	d6,d2			; the first line
.fl:	cmp.w	#256,d2
	bhs	.gen
	move.w	d2,d3
	add.w	d7,d3			; the last
	cmp.w	#256,d3
	bhs	.gen
	lea	m72r_lband,a0
	moveq	#0,d1
	move.b	(a0,d3.w),d1
	moveq	#0,d3
	move.b	(a0,d2.w),d3
	cmp.w	d1,d3
	bne	.gen
	movem.l	d2/d6-d7/a2,-(sp)	; (the columns of this piece's x)
	bsr	m72r_pcols
	movem.l	(sp)+,d2/d6-d7/a2
	tst.b	m72r_poff
	bne	.gen
	move.l	m72r_pfg+8,d0		; (FG's columns: no wrap)
	sub.l	m72r_pfg,d0
	cmp.l	#2048,d0
	bne	.gen
	move.l	m72r_pbg+8,d0
	sub.l	m72r_pbg,d0
	cmp.l	#2048,d0
	bne	.gen
	move.w	m72r_pfg+14,d0		; FG's map line of the first line
	add.w	d2,d0
	and.w	#511,d0
	move.w	d0,d1
	add.w	d7,d1
	cmp.w	#512,d1
	bhs	.gen
	add.w	d0,d0
	move.l	m72r_pfg,a0
	add.w	d0,a0
	move.w	m72r_pbg+14,d0
	add.w	d2,d0
	and.w	#511,d0
	move.w	d0,d1
	add.w	d7,d1
	cmp.w	#512,d1
	bhs	.gen
	add.w	d0,d0
	move.l	m72r_pbg,a1
	add.w	d0,a1
	move.w	m72r_pfg+12,d4		; FG's shift
	moveq	#16,d6
	sub.w	d4,d6
	move.w	m72r_pbg+12,d5
	moveq	#16,d3
	sub.w	d5,d3
	lea	m72r_pstream,a4
	btst	#10,m72r_sattr
	bne	.fb
.f:	move.w	(a0),d0			; FG's 32 over pixels
	swap	d0
	move.w	1024(a0),d0
	moveq	#0,d2
	move.w	2048(a0),d2
	lsl.l	d4,d0
	lsr.l	d6,d2
	or.l	d2,d0
	move.w	(a1),d1			; BG's
	swap	d1
	move.w	1024(a1),d1
	moveq	#0,d2
	move.w	2048(a1),d2
	lsl.l	d5,d1
	lsr.l	d3,d2
	or.l	d2,d1
	or.l	d1,d0
	not.l	d0
	and.l	(a3)+,d0
	move.l	d0,(a4)+
	addq.l	#2,a0
	addq.l	#2,a1
	dbf	d7,.f
	bra	.fx
.fb:	move.w	d7,d0			; flip y: the streams from their ends
	addq.w	#1,d0
	lsl.w	#2,d0
	add.w	d0,a3
	add.w	d0,a4
.fbl:	move.w	(a0),d0
	swap	d0
	move.w	1024(a0),d0
	moveq	#0,d2
	move.w	2048(a0),d2
	lsl.l	d4,d0
	lsr.l	d6,d2
	or.l	d2,d0
	move.w	(a1),d1
	swap	d1
	move.w	1024(a1),d1
	moveq	#0,d2
	move.w	2048(a1),d2
	lsl.l	d5,d1
	lsr.l	d3,d2
	or.l	d2,d1
	or.l	d1,d0
	not.l	d0
	and.l	-(a3),d0
	move.l	d0,-(a4)
	addq.l	#2,a0
	addq.l	#2,a1
	dbf	d7,.fbl
.fx:	lea	m72r_pstream,a0
	movem.l	(sp)+,d0-d7/a1-a4
	rts
.gen:	move.l	a3,a0
	lea	m72r_pstream,a4		; the copy
	moveq	#0,d6
	move.b	(a2),d6			; y0
	moveq	#0,d7
	move.b	1(a2),d7
	sub.w	d6,d7			; rows - 1
	move.w	#-1,m72r_pband
.row:	move.w	m72r_by,d2		; the row's line
	btst	#10,m72r_sattr
	beq	.ny
	add.w	#15,d2
	sub.w	d6,d2
	bra	.l
.ny:	add.w	d6,d2
.l:	moveq	#0,d1			; the over pixels
	cmp.w	#256,d2
	bhs	.np
	lea	m72r_lband,a0
	moveq	#0,d3
	move.b	(a0,d2.w),d3
	cmp.w	m72r_pband,d3
	beq	.same
	movem.l	d6-d7,-(sp)
	bsr	m72r_pcols
	movem.l	(sp)+,d6-d7
.same:	moveq	#-1,d1			; (the display off: nothing)
	tst.b	m72r_poff
	bne	.np
	movem.l	d6-d7,-(sp)
	lea	m72r_pfg,a0
	bsr	m72r_pget
	move.l	d3,d1
	lea	m72r_pbg,a0
	bsr	m72r_pget
	or.l	d3,d1
	movem.l	(sp)+,d6-d7
.np:	not.l	d1
	move.l	(a3)+,d0		; END1 (high word), END3
	and.l	d1,d0
	move.l	d0,(a4)+
	addq.w	#1,d6
	dbf	d7,.row
	lea	m72r_pstream,a0
	movem.l	(sp)+,d0-d7/a1-a4
	rts

; m72r_pcols: band d3 (m72r_pband): the over planes' column addresses (3 words from buffer x m72r_bx & ~15) and shifts
m72r_pcols:
	move.w	d3,m72r_pband
	lsl.w	#4,d3
	lea	m72r_bt,a0
	add.w	d3,a0
	tst.w	BT_OFF(a0)
	sne	m72r_poff
	bne	.x
	move.l	a0,-(sp)
	move.w	BT_OXF(a0),d4
	move.w	BT_OYF(a0),d5
	lea	m72r_imgf+5*M72_PL,a1
	lea	m72r_pfg,a2
	bsr	.cols
	move.l	(sp)+,a0
	move.w	BT_OXB(a0),d4
	move.w	BT_OYB(a0),d5
	lea	m72r_imgb+4*M72_PL,a1
	lea	m72r_pbg,a2
.cols:	; a2: 3 column addresses (longs), the shift (word), map y of line 0 (word)
	move.w	m72r_bx,d6
	and.w	#$fff0,d6
	add.w	d4,d6
	and.w	#511,d6			; map x
	move.w	d6,d7
	lsr.w	#4,d7			; column
	moveq	#3-1,d3
.c:	moveq	#0,d4
	move.w	d7,d4
	moveq	#10,d0
	lsl.l	d0,d4
	add.l	a1,d4
	move.l	d4,(a2)+
	addq.w	#1,d7
	and.w	#31,d7
	dbf	d3,.c
	and.w	#15,d6
	move.w	d6,(a2)+		; the shift
	move.w	d5,(a2)+		; map y of line 0
.x:	rts

; m72r_pget: d3 = the 32 over pixels of picture line d2 from the columns a0 (see m72r_pcols); destroys d4-d7, a1
m72r_pget:
	move.w	14(a0),d5
	add.w	d2,d5
	and.w	#511,d5
	add.w	d5,d5			; the line's offset
	move.l	(a0),a1
	move.w	(a1,d5.w),d3
	swap	d3
	move.l	4(a0),a1
	move.w	(a1,d5.w),d3
	move.l	8(a0),a1
	moveq	#0,d7
	move.w	(a1,d5.w),d7
	move.w	12(a0),d4		; the shift
	lsl.l	d4,d3
	moveq	#16,d6
	sub.w	d4,d6
	lsr.l	d6,d7
	or.l	d7,d3
	rts

; ======================================================================================================================
; the colours
; ======================================================================================================================
; Pens map to the 16 STE indices through m72r_pidx (512 bytes; the HUD bars' FG rows through m72r_hidx).  The indices'
; colours are chosen per scene: samples of the picture (a pixel every 8 x M72_NSAMP: the visible tile pen) and the
; visible sprites' pens give a histogram of the colours (the pens at STE resolution, 4 bits a channel); index 0 is
; black, 15 centres are seeded by the farthest colour (Oklab L1 x the square root of the weight) and refined by 8
; rounds of k-means; a pen's index is the nearest centre of its colour.  The STE colour of an index is the current
; colour of its representative pen (the heaviest pen of the colour nearest the centre), so fades and colour cycles
; change the STE palette, not the mapping.  A new choice: the first picture, and when the palette has rested for 2
; pictures with 16 pens or more changed since the last choice.  Then every tile is converted again (the window's at once,
; the others when they scroll in), the sprite cache flushed, the buffers drawn again.

; m72r_palette: the pens' colours from palette RAM; rest and change counting; the STE palettes
m72r_palette:
	tst.b	m72v_pdirty
	beq	.rest
	clr.b	m72v_pdirty
	bsr	m72r_pcolours
	tst.b	m72r_pchg		; changed since the last picture?
	beq	.rest
	clr.w	m72r_rest
	st	m72r_divp		; (pens now far from the colour their index shows: mapped again)
	bra	.ste
.rest:	cmp.w	#1000,m72r_rest
	bhs	.ste
	addq.w	#1,m72r_rest
	tst.b	m72r_ncent
	beq	.ste			; (the first choice: m72r_init asks for it)
	cmp.w	#2,m72r_rest
	beq	.r2
	cmp.w	#M72_FALLBACK,m72r_rest
	bne	.ste
	tst.b	m72r_unk		; a long rest on an unknown tile palette: the run-time choice
	beq	.ste
	clr.b	m72r_unk
	move.w	#-1,m72r_nscene
	bra	.sw1
.r2:	; rested: the pens changed since the mapping (tiles, sprites)
	lea	m72r_pcur,a0
	lea	m72r_psnap,a1
	moveq	#0,d2			; sprites
	move.w	#256-1,d0
.ns:	cmpm.w	(a0)+,(a1)+
	beq	.ns1
	addq.w	#1,d2
.ns1:	dbf	d0,.ns
	moveq	#0,d1			; tiles
	move.w	#256-1,d0
.nt:	cmpm.w	(a0)+,(a1)+
	beq	.nt1
	addq.w	#1,d1
.nt1:	dbf	d0,.nt
	cmp.w	#16,d1
	bhs	.match
	tst.w	d2
	beq	.ste
.match:	movem.w	d1-d2,-(sp)
	bsr	m72r_match		; d0 = the scene or -1
	movem.w	(sp)+,d1-d2
	tst.w	d0
	bmi	.unk
	clr.b	m72r_unk		; (a known scene: no run-time choice later)
	cmp.w	m72r_kscene,d0		; (the scene m72r_sdiv found wanting: the run-time choice stays)
	bne	.mk
	move.w	m72r_scene,d0
.mk:	cmp.w	m72r_scene,d0
	bne	.sw
	tst.w	d2			; the same scene: the sprites' pens mapped again
	beq	.ste
	st	m72r_divp		; (the sprites' pens: m72r_sdiv, per colour row)
	bra	.ste
.sw:	move.w	d0,m72r_nscene
.sw1:	or.b	#1,m72r_need
	tst.b	m72r_hud_on
	beq	.ste
	or.b	#2,m72r_need
	bra	.ste
.unk:	tst.w	m72r_scene		; (a run-time choice: its sprites' pens mapped again too)
	bpl	.unk1
	tst.w	d2
	beq	.unk1
	st	m72r_divp		; (the sprites' pens: m72r_sdiv, per colour row)
.unk1:	cmp.w	#16,d1
	blo	.ste
	st	m72r_unk		; (a fade or an unknown scene: wait)
.ste:	rts

; m72r_match: d0 = the offline scene (m72_pal.bin) whose reference tile palette has the most pens equal to the current
; one (at least M72_MATCH), -1 none
M72_MATCH	= 232
m72r_match:
	movem.l	d1-d7/a0-a2,-(sp)
	lea	m72r_paltab,a0
	move.w	(a0)+,d7		; scenes
	moveq	#-1,d0			; the best
	move.w	#M72_MATCH-1,d6		; its count
	moveq	#0,d5			; the scene
	bra	.n
.s:	lea	m72r_pcur+512,a2	; (the tile pens)
	move.l	a0,a1
	moveq	#0,d3
	move.w	#256-1,d2
.k:	cmpm.w	(a1)+,(a2)+
	bne	.k1
	addq.w	#1,d3
.k1:	dbf	d2,.k
	cmp.w	d6,d3
	bls	.nx
	move.w	d3,d6
	move.w	d5,d0
.nx:	lea	M72_SCENE(a0),a0
	addq.w	#1,d5
.n:	dbf	d7,.s
	ext.l	d0
	movem.l	(sp)+,d1-d7/a0-a2
	rts

; m72r_loadcent: m72r_ccw / m72r_nc from the centres d7 = 0 m72r_cent / m72r_ncent, 1 m72r_hcent / m72r_hncent
m72r_loadcent:
	movem.l	d0-d1/a0-a1,-(sp)
	lea	m72r_cent,a0
	moveq	#0,d0
	move.b	m72r_ncent,d0
	tst.w	d7
	beq	.l
	lea	m72r_hcent,a0
	move.b	m72r_hncent,d0
.l:	move.w	d0,m72r_nc
	lea	m72r_ccw,a1
	moveq	#16-1,d1
.c:	moveq	#0,d0
	move.b	(a0)+,d0
	move.w	d0,(a1)+
	move.b	(a0)+,d0
	move.w	d0,(a1)+
	move.b	(a0)+,d0
	move.w	d0,(a1)+
	clr.w	(a1)+
	addq.l	#1,a0
	dbf	d1,.c
	movem.l	(sp)+,d0-d1/a0-a1
	rts

; m72r_sprremap: the sprites' pens (0-255) whose colour changed since their mapping: their nearest centre again (a change
; of index flushes the sprite cache)
m72r_sprremap:
	movem.l	d0-d7/a0-a6,-(sp)
	moveq	#0,d7
	bsr	m72r_loadcent
	lea	m72r_pcur,a2
	lea	m72r_psnap,a3
	lea	m72r_pidx,a4
	lea	m72r_lab,a6
	moveq	#0,d6			; (an index changed)
	moveq	#0,d7			; the pen
.p:	move.w	(a2)+,d0
	cmp.w	(a3)+,d0
	beq	.n
	move.w	d0,-2(a3)
	lsl.w	#2,d0
	moveq	#0,d3
	move.b	(a6,d0.w),d3
	moveq	#0,d4
	move.b	1(a6,d0.w),d4
	moveq	#0,d5
	move.b	2(a6,d0.w),d5
	bsr	m72r_nearw
	cmp.b	(a4,d7.w),d1
	beq	.n
	move.b	d1,(a4,d7.w)
	moveq	#1,d6
.n:	addq.w	#1,d7
	cmp.w	#256,d7
	blo	.p
	tst.w	d6
	beq	.x
	bsr	m72r_sflush
.x:	movem.l	(sp)+,d0-d7/a0-a6
	rts

; m72r_sdiv: a pen in use (m72r_suse: the sprites' and the window's tiles' pens, m72r_urep) whose colour is now more
; than M72_DIV (Oklab bytes, L1) from the colour its index shows (its representative's) goes to the index whose shown
; colour is nearest (a palette that never rests, colour cycles: the mapping of the last choice would show such pens in
; a wrong colour): a sprite pen empties the sprite cache, a tile pen makes its colour row's tiles be converted again
; (m72r_cinval).  No shown colour near enough (a fade in from black, a new scene): a new choice (m72r_need).  Run when
; the palette changed and after new representatives (m72r_divp), before the picture is drawn.
M72_DIV		= 45
M72_NFAR	= 8
M72_CHOICEGAP	= 8
M72_KWAIT	= 500
M72_CWAIT	= 4
M72_STABLE	= 2
M72_SSTABLE	= 1
M72_SWAIT	= 1
M72_RPWAIT	= 32
M72_RPTWIN	= 40
m72r_sdiv:
	movem.l	d0-d7/a0-a6,-(sp)
	clr.b	m72r_divp
	clr.b	m72r_cnn
	clr.b	m72r_dpend
	clr.b	m72r_rpdone
	clr.l	m72r_rpmask
	tst.b	m72r_ncent
	beq	.x
	tst.b	m72r_sonly
	bne	.rf
	bsr	m72r_repfix		; (representatives that moved away from their centres: another pen in use)
.rf:
	lea	m72r_pcur,a2
	lea	m72r_lab,a3
	lea	m72r_slab,a1		; the shown colours' Oklab bytes
	lea	m72r_rep,a0
	moveq	#0,d0
.sl:	moveq	#0,d1			; (index 0: black)
	tst.w	d0
	beq	.s0
	move.w	d0,d1
	add.w	d1,d1
	move.w	(a0,d1.w),d1
	add.w	d1,d1
	move.w	(a2,d1.w),d1
.s0:	lsl.w	#2,d1
	move.l	(a3,d1.w),d1
	cmp.l	(a1),d1			; (the indices whose shown colour changed: m72r_dchg)
	beq	.s1
	move.w	m72r_dchg,d2
	bset	d0,d2
	move.w	d2,m72r_dchg
.s1:	move.l	d1,(a1)+
	addq.w	#1,d0
	cmp.w	#16,d0
	blo	.sl
	lea	m72r_suse,a0
	lea	m72r_pidx,a4
	lea	m72r_slab,a5
	moveq	#0,d6			; (bit 31: a sprite pen moved; bits 0-15: tile colour rows)
	moveq	#0,d7			; the pen
	clr.w	m72r_nfar
.row:	tst.b	m72r_sonly		; (the sprites' rows only)
	beq	.ro
	cmp.w	#256,d7
	bhs	.end
.ro:	move.w	(a0)+,d5
	bne	.pen
	add.w	#16,d7			; (no pen of the row in use)
	cmp.w	#512,d7
	blo	.row
	bra	.end
.pen:	lsr.w	#1,d5
	bcc	.pn
	move.w	d7,d0			; (the pen's colour and its index's shown colour as at its last look: that result)
	add.w	d0,d0
	move.w	(a2,d0.w),d1
	lea	m72r_dcol,a1
	cmp.w	(a1,d0.w),d1
	bne	.chk
	moveq	#0,d1
	move.b	(a4,d7.w),d1
	move.w	m72r_dchg,d2
	btst	d1,d2
	bne	.chk
	lea	m72r_dres,a1
	move.b	(a1,d7.w),d1
	beq	.pn
	cmp.b	#1,d1			; (pending: looked at again)
	beq	.ag
	move.w	m72r_dchg,d4		; (far at its last look: looked at again when a shown colour changed to one
	beq	.fc			; nearer than its nearest then)
	move.w	(a2,d0.w),d1
	lsl.w	#2,d1
	lea	(a3,d1.w),a6
	moveq	#0,d1
.fl:	btst	d1,d4
	beq	.fln
	movem.w	d1/d4,-(sp)
	lsl.w	#2,d1
	bsr	.dist
	movem.w	(sp)+,d1/d4
	move.w	d7,d0
	add.w	d0,d0
	lea	m72r_dbest,a1
	cmp.w	(a1,d0.w),d2
	blo	.ag0
.fln:	addq.w	#1,d1
	cmp.w	#16,d1
	blo	.fl
.fc:	addq.w	#1,m72r_nfar
	bra	.pn
.ag0:	move.w	d7,d0
	add.w	d0,d0
.ag:	lea	m72r_dcol,a1
.chk:	move.w	(a2,d0.w),d1		; (its colour changed since its last look: the time noted)
	cmp.w	(a1,d0.w),d1
	beq	.ck1
	move.w	d1,(a1,d0.w)
	lea	m72r_dtime,a1
	move.w	m72r_pictures+2,(a1,d0.w)
.ck1:	lea	m72r_dres,a1
	clr.b	(a1,d7.w)
	move.w	(a2,d0.w),d0
	lsl.w	#2,d0
	lea	(a3,d0.w),a6		; the pen's colour
	moveq	#0,d1
	move.b	(a4,d7.w),d1
	lsl.w	#2,d1
	bsr	.dist			; to its index's shown colour
	cmp.w	#M72_DIV,d2
	bls	.pn
	move.w	d7,d0			; (a pen whose colour changed in the last M72_STABLE (sprites: M72_SSTABLE)
	add.w	d0,d0			; pictures, a cycling or fading pen: pending, looked at again next picture)
	lea	m72r_dtime,a1
	move.w	m72r_pictures+2,d1
	sub.w	(a1,d0.w),d1
	moveq	#M72_STABLE,d0
	cmp.w	#256,d7
	bhs	.st0
	moveq	#M72_SSTABLE,d0
.st0:	cmp.w	d0,d1
	bhs	.stb
.pend:	lea	m72r_dres,a1		; (not counted far: no choice for it)
	move.b	#1,(a1,d7.w)
	st	m72r_dpend
	bra	.pn
.stb:	move.w	d7,d0			; (its row remapped lately: pending)
	lsr.w	#4,d0
	lea	m72r_cwait,a1
	tst.b	(a1,d0.w)
	bne	.pend
.sq:	moveq	#0,d1			; the nearest shown colour
	move.w	#$7fff,d3
	moveq	#0,d4
.nr:	movem.w	d1/d3-d4,-(sp)
	bsr	.dist
	movem.w	(sp)+,d1/d3-d4
	cmp.w	d3,d2
	bhs	.nn
	move.w	d2,d3
	move.w	d1,d4
.nn:	addq.w	#4,d1
	moveq	#0,d0
	move.b	m72r_ncent,d0
	lsl.w	#2,d0
	cmp.w	d0,d1
	blo	.nr
	cmp.w	#M72_DIV,d3
	bls	.near
	move.w	d7,d0			; (its nearest: m72r_dbest)
	add.w	d0,d0
	lea	m72r_dbest,a1
	move.w	d3,(a1,d0.w)
	tst.b	m72r_rpdone		; no index near: once a pass an index given to this pen's colour (m72r_repurp)
	bne	.nf
	tst.b	m72r_sonly
	bne	.nf
	tst.w	m72r_rpwait		; (none found lately: not looked for again yet)
	bne	.nf
	bsr	m72r_repurp
	tst.w	d0
	beq	.nf
	move.w	d0,d4			; (the pen to it)
	lsl.w	#2,d4
	bra	.near
.nf:	addq.w	#1,m72r_nfar		; (no index near: counted; the nearest taken if clearly nearer)
	lea	m72r_dres,a1
	st	(a1,d7.w)
	movem.w	d1/d3-d4,-(sp)
	moveq	#0,d1
	move.b	(a4,d7.w),d1
	lsl.w	#2,d1
	bsr	.dist
	movem.w	(sp)+,d1/d3-d4
	sub.w	#M72_DIV/2,d2
	cmp.w	d2,d3
	bhs	.pn
.near:	lsr.w	#2,d4
	cmp.b	(a4,d7.w),d4
	beq	.pn
	move.w	d7,d0
	lsr.w	#4,d0
	lea	m72r_cwait,a1		; (a row remapped in the last M72_CWAIT pictures: not again yet, pending)
	tst.b	(a1,d0.w)
	bne	.pend
	move.b	m72r_p0,d1		; (a BG tile's nn flag depends on the index m72r_p0)
	cmp.b	(a4,d7.w),d1
	beq	.p0
	cmp.b	d4,d1
	bne	.p1
.p0:	st	m72r_cnn
.p1:	move.b	d4,(a4,d7.w)
	cmp.w	#256,d7
	bhs	.tp
	add.w	#16,d0
	bset	d0,d6			; (bits 16-31: sprite colour rows)
	bra	.pn
.tp:	sub.w	#16,d0
	bset	d0,d6			; (its colour row)
.pn:	addq.w	#1,d7
	moveq	#15,d0
	and.w	d7,d0
	bne	.pen
	cmp.w	#512,d7
	blo	.row
.end:	tst.b	m72r_sonly		; (the tiles' pens: the next full pass sees the changed indices)
	bne	.e1
	clr.w	m72r_dchg
.e1:
	tst.b	m72r_dpend		; (pens pending: the next picture again)
	beq	.np
	st	m72r_divp
.np:
	or.l	m72r_rpmask,d6		; (the rows of the pens m72r_repurp moved)
	moveq	#16,d0			; sprite rows remapped: their conversions stale, their colour tables built again
.sr:	btst	d0,d6
	beq	.sn
	move.w	d0,d1
	sub.w	#16,d1
	bsr	m72r_shrow		; (the row's mapping's version: the conversions' key; its colour table again)
	lea	m72r_cwait,a1		; (the row waits M72_SWAIT pictures)
	move.b	#M72_SWAIT,(a1,d1.w)
.sn:	addq.w	#1,d0
	cmp.w	#32,d0
	blo	.sr
.nt:	moveq	#0,d0
.cr:	btst	d0,d6
	beq	.cn
	bsr	m72r_cinval
.cn:	addq.w	#1,d0
	cmp.w	#16,d0
	blo	.cr
	; pens far from every shown colour, the last choice M72_CHOICEGAP pictures ago or more: many of them (a fade in
	; from black, a new scene) a new choice; still (or a few) then the run-time choice (k-means over the picture and
	; the sprites' pens), the offline scene of now not taken again until the tile palette changes; then a pause
	tst.w	m72r_nfar
	beq	.x
	tst.w	m72r_kwait
	bne	.w
	st	m72r_divp		; (looked at again next picture, until it is time)
.w:	cmp.w	#M72_CHOICEGAP,m72r_since
	blo	.x
	tst.w	m72r_kwait
	bne	.x
	tst.b	m72r_dtry
	bne	.k
	cmp.w	#M72_NFAR,m72r_nfar
	blo	.k
	st	m72r_dtry
	or.b	#1,m72r_need
	bra	.x
.k:	clr.b	m72r_dtry
	move.w	m72r_scene,m72r_kscene
	move.w	#-1,m72r_nscene
	move.w	#M72_KWAIT,m72r_kwait
	or.b	#1,m72r_need
.x:	movem.l	(sp)+,d0-d7/a0-a6
	rts
; d2 = Oklab L1 between the colour a6 and the shown colour at m72r_slab + d1; destroys d0, d4
.dist:	moveq	#0,d2
	move.b	(a6),d2
	moveq	#0,d0
	move.b	(a5,d1.w),d0
	sub.w	d0,d2
	bpl	.d1
	neg.w	d2
.d1:	moveq	#0,d4
	move.b	1(a6),d4
	moveq	#0,d0
	move.b	1(a5,d1.w),d0
	sub.w	d0,d4
	bpl	.d2
	neg.w	d4
.d2:	add.w	d4,d2
	moveq	#0,d4
	move.b	2(a6),d4
	moveq	#0,d0
	move.b	2(a5,d1.w),d0
	sub.w	d0,d4
	bpl	.d3
	neg.w	d4
.d3:	add.w	d4,d2
	rts

; m72r_shrow: sprite colour row d1's mapping changed: its version (m72r_scver, in the sprite conversions' key: one of
; the row's last M72_SROWS mappings keeps its version, so a colour cycle's mappings find their conversions again; a
; new one gets a new version) and its colour table built again.  Keeps all registers.
m72r_shrow:
	movem.l	d0-d3/a0-a2,-(sp)
	lea	m72r_pidx,a0
	move.w	d1,d0
	lsl.w	#4,d0
	add.w	d0,a0			; the row's 16 indices
	lea	m72r_srows,a1		; its last M72_SROWS mappings (16 bytes, version word)
	move.w	d1,d0
	mulu	#M72_SROWS*18,d0
	add.l	d0,a1
	moveq	#M72_SROWS-1,d2
.f:	move.l	a1,a2
	move.l	(a0),d0
	cmp.l	(a2)+,d0
	bne	.n
	move.l	4(a0),d0
	cmp.l	(a2)+,d0
	bne	.n
	move.l	8(a0),d0
	cmp.l	(a2)+,d0
	bne	.n
	move.l	12(a0),d0
	cmp.l	(a2)+,d0
	bne	.n
	move.w	(a2),d0			; (seen before: its conversions are in the cache still)
	bra	.set
.n:	lea	18(a1),a1
	dbf	d2,.f
	lea	m72r_srows,a1		; (new: a slot in turn, a new version)
	move.w	d1,d0
	mulu	#M72_SROWS*18,d0
	add.l	d0,a1
	lea	m72r_srnext,a2
	moveq	#0,d0
	move.b	(a2,d1.w),d0
	addq.b	#1,(a2,d1.w)
	and.w	#M72_SROWS-1,d0
	mulu	#18,d0
	add.l	d0,a1
	move.l	(a0)+,(a1)+
	move.l	(a0)+,(a1)+
	move.l	(a0)+,(a1)+
	move.l	(a0)+,(a1)+
	addq.w	#1,m72r_srver
	move.w	m72r_srver,d0
	move.w	d0,(a1)
.set:	lea	m72r_scver,a0
	add.w	d1,a0
	add.w	d1,a0
	move.w	d0,(a0)
	lea	m72r_stv,a0
	clr.b	(a0,d1.w)
	movem.l	(sp)+,d0-d3/a0-a2
	rts

; m72r_shall: every sprite row's hash (after a choice)
m72r_shall:
	move.l	d1,-(sp)
	moveq	#0,d1
.r:	bsr	m72r_shrow
	addq.w	#1,d1
	cmp.w	#16,d1
	blo	.r
	move.l	(sp)+,d1
	rts

; m72r_pnew: pens newly in use (d2: a mask of row d3's 16, its first pen d3): looked at by m72r_sdiv at once (pending,
; their colour as now and settled).  Keeps all registers.
m72r_pnew:
	movem.l	d0-d3/a0-a2,-(sp)
	lea	m72r_dcol,a0
	lea	m72r_dtime,a1
	lea	m72r_dres,a2
	move.w	m72r_pictures+2,d1
	sub.w	#100,d1
.p:	lsr.w	#1,d2
	bcc	.n
	move.w	d3,d0
	move.b	#1,(a2,d0.w)
	add.w	d0,d0
	move.w	d1,(a1,d0.w)
	move.l	a0,-(sp)
	lea	m72r_pcur,a0
	move.w	(a0,d0.w),d0
	move.l	(sp)+,a0
	move.w	d3,-(sp)
	add.w	d3,d3
	move.w	d0,(a0,d3.w)
	move.w	(sp)+,d3
.n:	addq.w	#1,d3
	tst.w	d2
	bne	.p
	movem.l	(sp)+,d0-d3/a0-a2
	rts

; m72r_repfix: an index whose representative's colour is now more than M72_DIV from its centre (a cycling or flashing
; pen) gets the pen in use (m72r_suse) on it nearest its centre instead, when that one is nearer (no conversion: only
; the STE colour changes)
m72r_repfix:
	movem.l	d0-d7/a0-a6,-(sp)
	lea	m72r_pcur,a2
	lea	m72r_lab,a3
	lea	m72r_cent,a4
	lea	m72r_rep,a5
	lea	m72r_pidx,a6
	moveq	#1,d7			; the index
.i:	moveq	#0,d0
	move.b	m72r_ncent,d0
	cmp.w	d0,d7
	bhs	.x
	move.w	d7,d0
	add.w	d0,d0
	move.w	(a5,d0.w),d0		; its representative
	bsr	.dc			; d2 = its distance to the centre
	cmp.w	#M72_DIV,d2
	bls	.n
	move.w	d2,d6			; the best so far
	lea	m72r_suse,a0
	moveq	#0,d5			; the pen
.r:	move.w	(a0)+,d4
	bne	.p
	add.w	#16,d5
	bra	.rn
.p:	lsr.w	#1,d4
	bcc	.pn
	cmp.b	(a6,d5.w),d7
	bne	.pn
	move.w	d5,d0
	bsr	.dc
	cmp.w	d6,d2
	bhs	.pn
	move.w	d2,d6
	move.w	d7,d0
	add.w	d0,d0
	move.w	d5,(a5,d0.w)
	addq.l	#1,m72r_nrepfix
.pn:	addq.w	#1,d5
	moveq	#15,d0
	and.w	d5,d0
	bne	.p
.rn:	cmp.w	#512,d5
	blo	.r
.n:	addq.w	#1,d7
	bra	.i
.x:	movem.l	(sp)+,d0-d7/a0-a6
	rts
; d2 = Oklab L1 between pen d0's colour and index d7's centre; destroys d0, d1, d3
.dc:	add.w	d0,d0
	move.w	(a2,d0.w),d0
	lsl.w	#2,d0
	move.w	d7,d1
	lsl.w	#2,d1
	moveq	#0,d2
	moveq	#3-1,d3
.dl:	movem.w	d0-d1,-(sp)
	move.b	(a3,d0.w),d0
	and.w	#$ff,d0
	move.b	(a4,d1.w),d1
	and.w	#$ff,d1
	sub.w	d1,d0
	bpl	.dp
	neg.w	d0
.dp:	add.w	d0,d2
	movem.w	(sp)+,d0-d1
	addq.w	#1,d0
	addq.w	#1,d1
	dbf	d3,.dl
	rts

; m72r_repurp (m72r_sdiv): pen d7 (colour a6's Oklab, its row not waiting) far from every shown colour: of the two
; nearest shown colours (at most M72_RPTWIN apart) the index fewer pens in use map to (m72r_suse) becomes this colour (its centre, its representative this pen; the pens on it
; are looked at again next pass: m72r_dchg); d0 = that index (the pen goes to it), 0 none (no index, a pass done
; already).  Keeps d1-d7, a0-a6 but m72r_slab's entry and m72r_cent are updated.
m72r_repurp:
	movem.l	d1-d7/a0-a6,-(sp)
	st	m72r_rpdone
	; the victim: of the two nearest shown colours (not 0, not m72r_p0; at most M72_RPTWIN apart) the one fewer pens
	; in use map to (its pens have the other one near)
	lea	m72r_slab,a5
	moveq	#0,d0			; the pair
	moveq	#0,d6
	move.w	#M72_RPTWIN+1,d5	; its distance
	moveq	#0,d7
	move.b	m72r_ncent,d7
	moveq	#1,d1			; i
.i:	cmp.w	d7,d1
	bhs	.pr
	cmp.b	m72r_p0,d1
	beq	.in
	move.w	d1,d2
	addq.w	#1,d2			; j
.j:	cmp.w	d7,d2
	bhs	.in
	cmp.b	m72r_p0,d2
	beq	.jn
	bsr	.pd
	cmp.w	d5,d3
	bhs	.jn
	move.w	d3,d5
	move.w	d1,d0
	move.w	d2,d6
.jn:	addq.w	#1,d2
	bra	.j
.in:	addq.w	#1,d1
	bra	.i
.pr:	tst.w	d0
	beq	.nw			; (none near enough: no index given)
	lea	m72r_rpcnt,a0		; the pens in use per index
	moveq	#16/2-1,d1
.c:	clr.l	(a0)+
	dbf	d1,.c
	lea	m72r_suse,a0
	lea	m72r_pidx,a1
	lea	m72r_rpcnt,a2
	moveq	#0,d2			; the pen
.r:	move.w	(a0)+,d3
	bne	.p
	add.w	#16,d2
	bra	.rn
.p:	lsr.w	#1,d3
	bcc	.pn
	moveq	#0,d4
	move.b	(a1,d2.w),d4
	add.w	d4,d4
	addq.w	#1,(a2,d4.w)
.pn:	addq.w	#1,d2
	moveq	#15,d4
	and.w	d2,d4
	bne	.p
.rn:	cmp.w	#512,d2
	blo	.r
	move.w	d0,d1
	add.w	d1,d1
	move.w	d6,d2
	add.w	d2,d2
	move.w	(a2,d1.w),d3
	cmp.w	(a2,d2.w),d3
	bls	.v
	exg	d0,d6			; (the other one has fewer)
.v:	bsr	.free			; its pens' rows not waiting? else the other one
	beq	.v1
	exg	d0,d6
	bsr	.free
	bne	.no
.v1:	; its pens to the twin d6: their rows' conversions stale (m72r_rpmask, bits as m72r_sdiv's d6)
	lea	m72r_suse,a0
	lea	m72r_pidx,a1
	moveq	#0,d2
.mv:	move.w	(a0)+,d3
	bne	.mp
	add.w	#16,d2
	bra	.mvn
.mp:	lsr.w	#1,d3
	bcc	.mq
	cmp.b	(a1,d2.w),d0
	bne	.mq
	move.b	d6,(a1,d2.w)
	move.l	a1,-(sp)		; (looked at again on its new index)
	lea	m72r_dres,a1
	move.b	#1,(a1,d2.w)
	move.l	(sp)+,a1
	move.w	d2,d4
	lsr.w	#4,d4
	cmp.w	#16,d4
	bhs	.mt
	add.w	#16,d4			; (sprite rows: bits 16-31)
	bra	.ms
.mt:	sub.w	#16,d4			; (tile rows: bits 0-15)
	st	m72r_cnn
.ms:	move.l	m72r_rpmask,d5
	bset	d4,d5
	move.l	d5,m72r_rpmask
.mq:	addq.w	#1,d2
	moveq	#15,d4
	and.w	d2,d4
	bne	.mp
.mvn:	cmp.w	#512,d2
	blo	.mv
	lea	m72r_rep,a2		; the pen its representative, its colour the centre
	move.w	d0,d2
	add.w	d2,d2
	move.w	24+2(sp),(a2,d2.w)	; (the saved d7: the pen)
	move.w	d0,d2
	lsl.w	#2,d2
	move.l	(a6),d3
	clr.b	d3
	lea	m72r_cent,a2
	move.l	d3,(a2,d2.w)
	move.l	(a6),(a5,d2.w)		; (m72r_slab)
	move.w	m72r_dchg,d3		; (the pens on it: looked at again)
	bset	d0,d3
	move.w	d3,m72r_dchg
	addq.l	#1,m72r_nrepurp
	st	m72r_divp		; (the pens on it: next picture)
.x:	movem.l	(sp)+,d1-d7/a0-a6
	rts
.no:	moveq	#0,d0
.nw:	move.w	#M72_RPWAIT,m72r_rpwait
	bra	.x
; Z: no pen in use on index d0 has its row waiting (m72r_cwait); destroys d2-d4, a0-a1
.free:	lea	m72r_suse,a0
	lea	m72r_pidx,a1
	moveq	#0,d2
.fr:	move.w	(a0)+,d3
	bne	.fp
	add.w	#16,d2
	bra	.fn2
.fp:	lsr.w	#1,d3
	bcc	.fn
	cmp.b	(a1,d2.w),d0
	bne	.fn
	move.w	d2,d4
	lsr.w	#4,d4
	move.l	a0,-(sp)
	lea	m72r_cwait,a0
	tst.b	(a0,d4.w)
	move.l	(sp)+,a0
	bne	.fx			; (NZ)
.fn:	addq.w	#1,d2
	moveq	#15,d4
	and.w	d2,d4
	bne	.fp
.fn2:	cmp.w	#512,d2
	blo	.fr
	moveq	#0,d2			; (Z)
.fx:	rts
; d3 = Oklab L1 between the shown colours of indices d1 and d2 (m72r_slab, a5)
.pd:	movem.l	d1-d2/d4-d5,-(sp)
	lsl.w	#2,d1
	lsl.w	#2,d2
	moveq	#0,d3
	moveq	#0,d4
	move.b	(a5,d1.w),d4
	moveq	#0,d5
	move.b	(a5,d2.w),d5
	sub.w	d5,d4
	bpl	.p1
	neg.w	d4
.p1:	add.w	d4,d3
	moveq	#0,d4
	move.b	1(a5,d1.w),d4
	moveq	#0,d5
	move.b	1(a5,d2.w),d5
	sub.w	d5,d4
	bpl	.p2
	neg.w	d4
.p2:	add.w	d4,d3
	moveq	#0,d4
	move.b	2(a5,d1.w),d4
	moveq	#0,d5
	move.b	2(a5,d2.w),d5
	sub.w	d5,d4
	bpl	.p3
	neg.w	d4
.p3:	add.w	d4,d3
	movem.l	(sp)+,d1-d2/d4-d5
	rts

; m72r_cinval: tile colour row d0's pens mapped anew: its conversions stale (m72r_cver), its tiles not valid and dirty
; in every buffer (both maps scanned)
m72r_cinval:
	movem.l	d0-d7/a0-a6,-(sp)
	addq.l	#1,m72r_ncinval
	move.w	d0,d7
	lea	m72r_cwait+16,a0
	move.b	#M72_CWAIT,(a0,d0.w)
	lea	m72r_cver,a0
	add.w	d0,a0
	add.w	d0,a0
	addq.w	#1,(a0)
	st	m72r_vclr
	moveq	#0,d6			; the layer
.lay:	lea	m72r_rowmap,a0		; the row's tiles
	move.w	d6,d0
	lsl.w	#4,d0
	add.w	d7,d0
	moveq	#9,d1
	lsl.w	d1,d0
	add.w	d0,a0
	lea	m72r_flags+V_F,a1
	move.w	#BS_DIRF,d4
	moveq	#1,d5
	tst.w	d6
	beq	.f
	lea	m72r_flags+V_B,a1
	move.w	#BS_DIRB,d4
	moveq	#2,d5
.f:	moveq	#0,d3			; (any)
	moveq	#512/4-1,d0
.v:	move.l	(a0)+,d1		; not valid
	or.l	d1,d3
	not.l	d1
	and.l	d1,(a1)+
	dbf	d0,.v
	tst.l	d3
	beq	.nl
	lea	-512(a0),a0
	lea	m72r_bs,a2		; dirty in every buffer
	moveq	#REN_NBUF-1,d2
.b:	lea	(a2,d4.w),a3
	move.l	a0,a4
	moveq	#512/4-1,d0
.d:	move.l	(a4)+,d1
	or.l	d1,(a3)+
	dbf	d0,.d
	or.w	d5,BS_ND(a2)
	lea	BS_SIZE(a2),a2
	dbf	d2,.b
	tst.w	d6			; BG: the nn flags of its tiles again (they depend on the mapping)
	beq	.nl
	tst.b	m72r_cnn
	beq	.nl
	moveq	#0,d4			; the byte (ty * 8 + tx / 8)
.nb:	move.b	(a0,d4.w),d3
	beq	.nn
	move.w	d4,d2
	lsr.w	#3,d2			; ty
	moveq	#7,d1
	and.w	d4,d1
	lsl.w	#3,d1			; tx of bit 7
.nt:	add.b	d3,d3
	bcc	.nz
	moveq	#1,d0
	bsr	m72r_tflags
.nz:	addq.w	#1,d1
	tst.b	d3
	bne	.nt
.nn:	addq.w	#1,d4
	cmp.w	#512,d4
	blo	.nb
	lea	m72r_brver,a1		; (the cached projections are stale)
	moveq	#64-1,d0
.bv:	addq.w	#1,(a1)+
	dbf	d0,.bv
.nl:	addq.w	#1,d6
	cmp.w	#2,d6
	blo	.lay
	movem.l	(sp)+,d0-d7/a0-a6
	rts

; m72r_usescene: the offline scene m72r_nscene's colours (d7 = 0: the playfield's, m72r_p0; 1: the HUD's): every pen's
; index the nearest centre of its colour, the representatives the pens nearest their centres
m72r_usescene:
	movem.l	d0-d7/a0-a6,-(sp)
	move.w	d7,m72r_ckind
	lea	m72r_paltab+2,a0
	move.w	m72r_nscene,d0
	mulu	#M72_SCENE,d0
	add.l	d0,a0
	lea	512(a0),a1		; the centres
	move.w	576(a0),d0
	tst.w	d7
	beq	.c
	lea	578(a0),a1
	move.w	642(a0),d0
.c:	move.w	d0,m72r_nc
	lea	m72r_ccw,a2
	moveq	#16-1,d1
.cw:	moveq	#0,d0
	move.b	(a1)+,d0
	move.w	d0,(a2)+
	move.b	(a1)+,d0
	move.w	d0,(a2)+
	move.b	(a1)+,d0
	move.w	d0,(a2)+
	clr.w	(a2)+
	addq.l	#1,a1
	dbf	d1,.cw
	tst.w	d7
	bne	.m
	move.b	645(a0),m72r_p0
.m:	; every pen: its nearest centre (once a colour: m72r_ckmap), the representatives: per centre the pen nearest it
	lea	m72r_rbest,a0
	moveq	#16-1,d0
.rb:	move.w	#$7fff,(a0)+
	dbf	d0,.rb
	lea	m72r_rep,a5
	lea	m72r_pidx,a2
	tst.w	d7
	beq	.m0
	lea	m72r_hrep,a5
	lea	m72r_hidx,a2
.m0:	moveq	#16-1,d0
	move.l	a5,a0
.rc:	clr.w	(a0)+
	dbf	d0,.rc
	lea	m72r_pcur,a3
	lea	m72r_lab,a6
	lea	m72r_ckmap,a4
	moveq	#0,d6			; the pen
.mp:	move.w	(a3)+,d0
	move.b	(a4,d0.w),d1		; (a colour seen before: its centre and distance)
	cmp.b	#255,d1
	beq	.mq
	add.w	d0,d0
	lea	m72r_ckdist,a0
	move.w	(a0,d0.w),d2
	bra	.mr
.mq:	move.w	d0,-(sp)
	lsl.w	#2,d0
	moveq	#0,d3
	move.b	(a6,d0.w),d3
	moveq	#0,d4
	move.b	1(a6,d0.w),d4
	moveq	#0,d5
	move.b	2(a6,d0.w),d5
	bsr	m72r_nearw		; d1 centre, d2 distance
	move.w	(sp)+,d0
	move.b	d1,(a4,d0.w)
	add.w	d0,d0
	lea	m72r_ckdist,a0
	move.w	d2,(a0,d0.w)
.mr:	move.b	d1,(a2)+
	add.w	d1,d1
	lea	m72r_rbest,a0
	cmp.w	(a0,d1.w),d2
	bhs	.mn
	move.w	d2,(a0,d1.w)
	move.w	d6,(a5,d1.w)
.mn:	addq.w	#1,d6
	cmp.w	#512,d6
	blo	.mp
	lea	m72r_pcur,a3		; (m72r_ckmap back to 255)
	move.w	#512-1,d6
.mc:	move.w	(a3)+,d0
	st	(a4,d0.w)
	dbf	d6,.mc
	; the centres as bytes (for the test)
	lea	m72r_ccw,a0
	lea	m72r_cent,a1
	tst.w	d7
	beq	.cb
	lea	m72r_hcent,a1
.cb:	moveq	#16-1,d0
.cb1:	move.w	(a0)+,d1
	move.b	d1,(a1)+
	move.w	(a0)+,d1
	move.b	d1,(a1)+
	move.w	(a0)+,d1
	move.b	d1,(a1)+
	clr.b	(a1)+
	addq.l	#2,a0
	dbf	d0,.cb1
	move.w	m72r_nc,d0
	tst.w	d7
	bne	.h
	move.b	d0,m72r_ncent
	bra	.x
.h:	move.b	d0,m72r_hncent
.x:	movem.l	(sp)+,d0-d7/a0-a6
	rts

; m72r_stepals: the STE palettes: the representatives' current colours
m72r_stepals:
	lea	m72r_rep,a0
	lea	m72r_stepal,a1
	move.b	m72r_ncent,d2
	bsr	.pal
	lea	m72r_hrep,a0
	lea	m72r_stehpal,a1
	move.b	m72r_hncent,d2
	bsr	.pal
	rts
.pal:	clr.w	(a1)+			; (index 0: black)
	lea	m72r_pcur,a2
	moveq	#1,d0
.p:	moveq	#0,d1
	cmp.b	d0,d2
	bls	.p1
	move.w	d0,d3
	add.w	d3,d3
	move.w	(a0,d3.w),d3		; the representative pen
	add.w	d3,d3
	move.w	(a2,d3.w),d1		; its colour (r g b nibbles)
	bsr	m72r_steword
.p1:	move.w	d1,(a1)+
	addq.w	#1,d0
	cmp.w	#16,d0
	blo	.p
	rts

; m72r_steword: d1 = r << 8 | g << 4 | b (0-15) -> the STE colour word (each nibble's bit 0 moved to bit 3)
m72r_steword:
	move.w	d1,d3
	and.w	#$0eee,d1
	lsr.w	#1,d1
	and.w	#$0111,d3
	lsl.w	#3,d3
	or.w	d3,d1
	rts

; m72r_pcolours: m72r_pcur = the 512 pens' colours (STE levels r << 8 | g << 4 | b), recomputed for the pens whose
; palette words changed (palette RAM against its copy m72r_palsh); m72r_pchg = any changed
m72r_pcolours:
	movem.l	d0-d7/a0-a4,-(sp)
	clr.b	m72r_pchg
	lea	m72r_q4,a2
	lea	m72v_pal0,a0
	lea	m72r_palsh,a1
	lea	m72r_pcur,a3
	bsr	.pal
	lea	m72v_pal1,a0
	lea	m72r_palsh+$c00,a1
	lea	m72r_pcur+512,a3
	bsr	.pal
	movem.l	(sp)+,d0-d7/a0-a4
	rts
; one palette: the red, green and blue blocks (128 longs each) compared; a differing long: its two pens again
.pal:	moveq	#0,d5			; the block offset
.blk:	lea	(a0,d5.w),a4
	lea	(a1,d5.w),a5
	moveq	#128-1,d7
.c:	cmpm.l	(a4)+,(a5)+
	dbne	d7,.c
	beq	.bn			; (the rest is equal)
	; the long at -4: pens 2i, 2i + 1 (i = 127 - d7)
	movem.l	d5/d7/a4-a5,-(sp)
	move.l	a4,d0
	sub.l	a0,d0
	subq.l	#4,d0
	sub.w	d5,d0			; the long's byte offset in the block
	lea	(a0,d0.w),a4		; (pen 2i's red word)
	lea	(a1,d0.w),a5
	move.l	(a4),(a5)		; the copy: all three blocks
	move.l	$400(a4),$400(a5)
	move.l	$800(a4),$800(a5)
	lea	(a3,d0.w),a6		; (pen 2i's colour)
	bsr	.pen
	addq.l	#2,a4
	addq.l	#2,a6
	bsr	.pen
	st	m72r_pchg
	movem.l	(sp)+,d5/d7/a4-a5
	subq.w	#1,d7
	bpl	.c
.bn:	add.w	#$400,d5
	cmp.w	#$c00,d5
	blo	.blk
	rts
.pen:	moveq	#31,d1
	and.b	(a4),d1			; red (the word's low byte)
	move.b	(a2,d1.w),d2
	lsl.w	#4,d2
	moveq	#31,d1
	and.b	$400(a4),d1
	or.b	(a2,d1.w),d2
	lsl.w	#4,d2
	moveq	#31,d1
	and.b	$800(a4),d1
	or.b	(a2,d1.w),d2
	move.w	d2,(a6)
	rts

; ======================================================================================================================
; m72r_hud: the HUD bars (their own palette): a band ending at M72_HUD_TOP / starting at M72_HUD_BOT that FG covers
; completely in the window; its FG rows convert through m72r_hidx
; ======================================================================================================================
m72r_hud:
	moveq	#0,d0			; top
	move.w	#256,d1			; bottom
	lea	m72r_bt,a4
	if	M72_HUD_TOP>0
	cmp.w	#M72_HUD_TOP,BT_Y1(a4)
	bne	.nt
	moveq	#0,d6
	move.w	#M72_HUD_TOP,d7
	bsr	.full
	bne	.nt
	move.w	#M72_HUD_TOP,d0
.nt:
	endc
	if	M72_HUD_BOT<256
	move.w	m72r_nb,d2
	subq.w	#1,d2
	lsl.w	#4,d2
	lea	(a4,d2.w),a4
	cmp.w	#M72_HUD_BOT,BT_Y0(a4)
	bne	.nb
	move.w	#M72_HUD_BOT,d6
	move.w	#256,d7
	bsr	.full
	bne	.nb
	move.w	#M72_HUD_BOT,d1
.nb:
	endc
	move.w	d0,m72r_htop
	move.w	d1,m72r_hbot
	tst.w	d0
	sne	d2
	cmp.w	#256,d1
	sne	d3
	or.b	d3,d2
	move.b	d2,m72r_hud_on
	; the FG rows the bars show
	lea	m72r_newhud,a0
	moveq	#64/4-1,d2
.cl:	clr.l	(a0)+
	dbf	d2,.cl
	lea	m72r_newhud,a0
	lea	m72r_bt,a4
	moveq	#0,d6
	move.w	d0,d7
	bsr	.rows
	move.w	m72r_nb,d2
	subq.w	#1,d2
	lsl.w	#4,d2
	lea	(a4,d2.w),a4
	move.w	d1,d6
	move.w	#256,d7
	bsr	.rows
	; changed rows: not valid, dirty in every buffer
	moveq	#0,d5			; (any change)
	lea	m72r_newhud,a0
	lea	m72r_hudrow,a1
	moveq	#0,d2
.r:	move.b	(a0,d2.w),d3
	cmp.b	(a1,d2.w),d3
	beq	.rn
	move.b	d3,(a1,d2.w)
	moveq	#1,d5
	move.w	d2,d3
	lsl.w	#3,d3
	st	m72r_vclr
	lea	m72r_flags+V_F,a2
	clr.l	(a2,d3.w)
	clr.l	4(a2,d3.w)
	lea	m72r_bs,a2
	moveq	#REN_NBUF-1,d4
.rb:	moveq	#-1,d6
	lea	BS_DIRF(a2),a3
	move.l	d6,(a3,d3.w)
	move.l	d6,4(a3,d3.w)
	or.w	#1,BS_ND(a2)
	lea	BS_SIZE(a2),a2
	dbf	d4,.rb
.rn:	addq.w	#1,d2
	cmp.w	#64,d2
	blo	.r
	rts
; Z: band a4 (not off) covers lines d6 .. d7 - 1 completely in the window (FG full in every cell)
.full:	tst.w	BT_OFF(a4)
	bne	.no
	movem.l	d0-d1/d6-d7,-(sp)
	move.w	d6,m72r_hy
	move.w	d7,m72r_hy1
.fr:	move.w	m72r_hy,d6
	move.w	d6,d7
	addq.w	#8,d7
	cmp.w	m72r_hy1,d7
	bls	.f1
	move.w	m72r_hy1,d7
.f1:	move.w	BT_OXF(a4),d4
	move.w	BT_OYF(a4),d5
	lea	m72r_flags+F_FV,a0
	bsr	m72r_proj_and
	movem.l	d0-d1,m72r_fv
	lea	m72r_flags+F_FO,a0
	bsr	m72r_proj_and
	movem.l	d0-d1,m72r_fo
	moveq	#0,d0
	moveq	#0,d1
	tst.w	m72r_nbod
	beq	.f2
	move.w	BT_OXB(a4),d4
	move.w	BT_OYB(a4),d5
	lea	m72r_flags+B_BOD,a0
	bsr	m72r_proj_or
.f2:	not.l	d0
	not.l	d1
	and.l	m72r_fo,d0
	and.l	m72r_fo+4,d1
	or.l	m72r_fv,d0
	or.l	m72r_fv+4,d1
	; every window cell (mod 64) in it?
	not.l	d0
	not.l	d1
	and.l	m72r_win64,d0
	and.l	m72r_win64+4,d1
	or.l	d1,d0
	bne	.fn
	add.w	#8,m72r_hy
	move.w	m72r_hy,d6
	cmp.w	m72r_hy1,d6
	blo	.fr
	movem.l	(sp)+,d0-d1/d6-d7
	moveq	#0,d2			; (Z)
	rts
.fn:	movem.l	(sp)+,d0-d1/d6-d7
.no:	moveq	#1,d2			; (NZ)
	rts
; the FG rows of band a4's lines d6 .. d7 - 1 into m72r_newhud
.rows:	cmp.w	d7,d6
	bhs	.rx
	move.w	BT_OYF(a4),d5
	move.w	d6,d2
.rr:	move.w	d2,d3
	add.w	d5,d3
	and.w	#511,d3
	lsr.w	#3,d3
	st	(a0,d3.w)
	addq.w	#1,d2
	cmp.w	d7,d2
	blo	.rr
.rx:	rts


; ======================================================================================================================
; the representatives among the pens the picture uses
; ======================================================================================================================
; An index's STE colour is its representative pen's current colour (fades and cycles follow).  The representative is
; the pen nearest the index's centre among the pens the picture uses: the tiles of the playfield's window (both layers,
; display-on bands; one of the 32 cell rows a picture, all at once after a new choice) and the
; sprites drawn (every picture), as 16-bit pen masks per colour row (m72r_umask: 0-15 the sprites' palette 0 rows,
; 16-31 the tiles' palette 1 rows).  An index no used pen maps to keeps its representative.  (A representative among
; all 512 pens, as before, could be a pen of the same colour at the choice that is unused and later changes: a whole
; index shown in the wrong colour.)

; m72r_uwork: a picture's share: its sprites, every second picture a cell row (after a new choice: all 32), every
; 32nd row (and
; after a new choice) the representatives and the STE palettes again
m72r_uwork:
	movem.l	d0-d2/a0-a1,-(sp)
	tst.b	m72r_ufull		; every 32nd picture and after a new choice: the representatives
	bne	.r
	addq.w	#1,m72r_ucyc
	and.w	#31,m72r_ucyc
	bne	.x
.r:	clr.b	m72r_ufull
	bsr	m72r_urep
	st	m72r_divp		; (m72r_sdiv before the next picture is drawn)
	bsr	m72r_stepals
.x:	movem.l	(sp)+,d0-d2/a0-a1
	rts

; m72r_usprites: the pieces of m72r_plist into m72r_umask (rows 0-15)
m72r_usprites:
	movem.l	d0-d2/a0-a2,-(sp)
	lea	m72r_plist,a0
	lea	m72r_su,a1
	lea	m72r_umask,a2
	move.w	m72r_np,d2
	subq.w	#1,d2
	bmi	.x
.p:	move.w	(a0)+,d0		; code
	lsl.w	#2,d0
	move.w	(a1,d0.w),d0		; its pens
	and.w	#$fffe,d0
	moveq	#15,d1
	and.w	(a0)+,d1		; colour
	add.w	d1,d1
	or.w	d0,(a2,d1.w)
	addq.l	#4,a0
	dbf	d2,.p
.x:	movem.l	(sp)+,d0-d2/a0-a2
	rts

; m72r_urep: the representatives from m72r_umask (each index: its used pen nearest its centre); the masks cleared
m72r_urep:
	movem.l	d0-d7/a0-a6,-(sp)
	lea	m72r_ubest,a0
	moveq	#16-1,d0
.b:	move.w	#$7fff,(a0)+
	dbf	d0,.b
	lea	m72r_suse,a0
	lea	m72r_pidx,a1
	lea	m72r_pcur,a2
	lea	m72r_lab,a3
	lea	m72r_cent,a4
	lea	m72r_ubest,a5
	lea	m72r_rep,a6
	moveq	#0,d7			; the pen
.row:	move.w	(a0),d6			; the row's mask
	addq.l	#2,a0
.pen:	lsr.w	#1,d6
	bcc	.pn
	moveq	#0,d0
	move.b	(a1,d7.w),d0		; its index
	beq	.pn
	move.w	d7,d1
	add.w	d1,d1
	move.w	(a2,d1.w),d1		; its colour
	lsl.w	#2,d1
	move.w	d0,d2
	lsl.w	#2,d2			; the centre
	moveq	#0,d3
	move.b	(a3,d1.w),d3
	moveq	#0,d4
	move.b	(a4,d2.w),d4
	sub.w	d4,d3
	bpl	.d1
	neg.w	d3
.d1:	moveq	#0,d5
	move.b	1(a3,d1.w),d5
	moveq	#0,d4
	move.b	1(a4,d2.w),d4
	sub.w	d4,d5
	bpl	.d2
	neg.w	d5
.d2:	add.w	d5,d3
	moveq	#0,d5
	move.b	2(a3,d1.w),d5
	moveq	#0,d4
	move.b	2(a4,d2.w),d4
	sub.w	d4,d5
	bpl	.d3
	neg.w	d5
.d3:	add.w	d5,d3			; the distance
	add.w	d0,d0
	cmp.w	(a5,d0.w),d3
	bhs	.pn
	move.w	d3,(a5,d0.w)
	move.w	d7,(a6,d0.w)
.pn:	addq.w	#1,d7
	moveq	#15,d0
	and.w	d7,d0
	bne	.pen
	cmp.w	#512,d7
	blo	.row
	movem.l	(sp)+,d0-d7/a0-a6
	rts

; ======================================================================================================================
; the status bar: its own buffer, its own palette (a raster split: borders.s' BD_HUDSCR events switch the video
; address, the fine scroll and the palette at the bar's first line and back at a top bar's end)
; ======================================================================================================================
; A bar (m72r_hud: a band at M72_HUD_TOP / M72_HUD_BOT that FG covers completely) whose tiles lie on the 8-pixel grid
; is drawn from its FG tiles into the buffer's bar area (m72r_barbuf: 320 pixels, M72_LB a line, fine scroll 0) and
; its band is display-off for the playfield (black there, nothing composed, no conversions, its pens out of the
; playfield's colours).  Its colours are exact: each pen its tiles use gets an index of its own (16 or more: the pens
; of equal colours share one, beyond 15 colours the nearest of the first 15), the index's colour is that pen's current
; colour (m72r_hrep, m72r_stepals), so fades and cycles follow.  A buffer's bar is drawn again where its tiles changed
; since that buffer's last picture (m72r_barcp), wholly when the mapping or the bar's place changed (m72r_barfull).
M72_BARL	= 32			; the bar's lines at most
M72_BARSZ	= M72_BARL*M72_LB

; m72r_bar: the bar of this picture (after m72r_hud): its place, its tiles' pens and their indices
m72r_bar:
	movem.l	d0-d7/a0-a6,-(sp)
	clr.b	m72r_baron
	lea	m72r_bt,a4
	moveq	#0,d6			; y0
	move.w	m72r_htop,d7		; y1
	bne	.got
	move.w	m72r_hbot,d6
	move.w	#256,d7
	cmp.w	d7,d6
	bhs	.off
	move.w	m72r_nb,d0
	subq.w	#1,d0
	lsl.w	#4,d0
	add.w	d0,a4
.got:	move.w	d7,d0
	sub.w	d6,d0
	cmp.w	#M72_BARL,d0
	bhi	.no
	moveq	#7,d1
	and.w	d0,d1
	bne	.no
	move.w	BT_OXF(a4),d2
	add.w	m72r_W,d2
	and.w	#511,d2			; map x of the bar's x 0
	moveq	#7,d1
	and.w	d2,d1
	bne	.no
	move.w	BT_OYF(a4),d3
	add.w	d6,d3
	and.w	#511,d3			; map y of its line 0
	moveq	#7,d1
	and.w	d3,d1
	bne	.no
	st	m72r_baron
	move.w	#1,BT_OFF(a4)		; (the playfield: black there)
	; its place changed: every buffer's bar drawn again, the pens again
	cmp.w	m72r_bary0,d6
	bne	.new
	cmp.w	m72r_bary1,d7
	bne	.new
	cmp.w	m72r_barmx,d2
	bne	.new
	cmp.w	m72r_barmy,d3
	beq	.same
.new:	move.w	d6,m72r_bary0
	move.w	d7,m72r_bary1
	move.w	d2,m72r_barmx
	move.w	d3,m72r_barmy
	st	m72r_barfull
	st	m72r_barpd
.same:	; the tiles (m72r_barsig): changed ones make the pens be looked at again (only when its rows changed)
	move.w	d3,d0
	lsr.w	#3,d0
	move.w	d7,d1
	sub.w	d6,d1
	lsr.w	#3,d1
	subq.w	#1,d1
	lea	m72r_vrchg,a0
	moveq	#0,d4
.vc:	and.w	#63,d0
	or.b	(a0,d0.w),d4
	addq.w	#1,d0
	dbf	d1,.vc
	tst.b	d4
	bne	.sig
	tst.b	m72r_barpd
	beq	.ng
.sig:	move.w	d7,d5
	sub.w	d6,d5
	lsr.w	#3,d5
	subq.w	#1,d5			; rows - 1
	lsr.w	#3,d3			; map row
	lsr.w	#3,d2			; map column
	lea	m72r_barsig,a1
.sr:	lea	m72v_fg,a0
	move.w	d3,d0
	and.w	#63,d0
	lsl.w	#8,d0
	add.w	d0,a0
	moveq	#40-1,d4
	move.w	d2,d1
.sc:	and.w	#63,d1
	move.w	d1,d0
	lsl.w	#2,d0
	move.l	(a0,d0.w),d0
	cmp.l	(a1),d0
	beq	.sn
	move.l	d0,(a1)
	bsr	m72r_barchk		; (a pen the bar did not use: its indices again)
.sn:	addq.l	#4,a1
	addq.w	#1,d1
	dbf	d4,.sc
	addq.w	#1,d3
	dbf	d5,.sr
	tst.b	m72r_bargrp		; (pens sharing indices by colour: a colour change makes the grouping again)
	beq	.ng
	lea	m72r_barpl,a0
	lea	m72r_barpc,a1
	lea	m72r_pcur,a2
	move.w	m72r_barnp,d0
	subq.w	#1,d0
.gc:	move.w	(a0)+,d1
	add.w	d1,d1
	move.w	(a2,d1.w),d1
	cmp.w	(a1)+,d1
	beq	.gn
	st	m72r_barpd
	bra	.ng
.gn:	dbf	d0,.gc
.ng:	tst.b	m72r_barpd
	beq	.x
	clr.b	m72r_barpd
	bsr	m72r_barpens
	bra	.x
.no:	clr.w	m72r_htop		; (not on the grid: no bar, the playfield shows those lines)
	move.w	#256,m72r_hbot
	clr.b	m72r_hud_on
.off:	clr.w	m72r_bary1		; (a bar later: its place is new)
.x:	lea	m72r_vrchg,a0		; (seen)
	moveq	#64/4-1,d0
.vx:	clr.l	(a0)+
	dbf	d0,.vx
	movem.l	(sp)+,d0-d7/a0-a6
	rts

; m72r_barchk: tile entry d0 (video RAM order) in the bar: any of its pens not in m72r_barset makes m72r_barpd
m72r_barchk:
	movem.l	d0-d2/a0,-(sp)
	move.l	d0,d1
	swap	d0
	ror.w	#8,d0
	and.w	#M72_NTF-1,d0
	add.w	d0,d0
	lea	m72r_uf,a0
	move.w	(a0,d0.w),d2
	and.w	#$fffe,d2
	lsr.w	#8,d1
	and.w	#15,d1
	lsl.w	#4,d1
	add.w	#256,d1
	lea	m72r_barset,a0
.p:	lsr.w	#1,d2
	bcc	.n
	tst.b	(a0,d1.w)
	bne	.n
	st	m72r_barpd
	bra	.x
.n:	addq.w	#1,d1
	tst.w	d2
	bne	.p
.x:	movem.l	(sp)+,d0-d2/a0
	rts

; m72r_barpens: the pens the bar's tiles use (m72r_barsig) -> m72r_barpl (m72r_barnp of them, ascending), their
; indices (m72r_hidx; another mapping than before: every buffer's bar drawn again), m72r_hrep, m72r_hncent
m72r_barpens:
	lea	m72r_barset,a0
	moveq	#512/4-1,d0
.c:	clr.l	(a0)+
	dbf	d0,.c
	lea	m72r_barset,a0
	lea	m72r_uf,a2
	lea	m72r_barsig,a1
	move.w	m72r_bary1,d7
	sub.w	m72r_bary0,d7
	lsr.w	#3,d7
	mulu	#40,d7
	subq.w	#1,d7
.t:	move.l	(a1)+,d0		; code low, code high, attribute (colour), -
	move.w	d0,d1
	swap	d0
	ror.w	#8,d0			; the code
	and.w	#M72_NTF-1,d0
	add.w	d0,d0
	move.w	(a2,d0.w),d2		; its pens
	and.w	#$fffe,d2		; (pen 0: transparent)
	lsr.w	#8,d1
	and.w	#15,d1
	lsl.w	#4,d1
	add.w	#256,d1			; pen 0 of its colour row
.p:	lsr.w	#1,d2
	bcc	.pn
	st	(a0,d1.w)
.pn:	addq.w	#1,d1
	tst.w	d2
	bne	.p
	dbf	d7,.t
	; the list
	lea	m72r_barpl,a1
	moveq	#0,d0
	moveq	#0,d1
.l:	tst.b	(a0,d0.w)
	beq	.ln
	move.w	d0,(a1)+
	addq.w	#1,d1
.ln:	addq.w	#1,d0
	cmp.w	#512,d0
	blo	.l
	move.w	d1,m72r_barnp
	; the indices: a pen each (15 at most), else by colour (equal colours share), beyond 15 colours the nearest
	lea	m72r_barnew,a3		; the new mapping (512 bytes)
	move.l	a3,a0
	moveq	#512/4-1,d0
.cn:	clr.l	(a0)+
	dbf	d0,.cn
	lea	m72r_hrep,a4
	clr.w	(a4)+			; (index 0: black)
	clr.b	m72r_bargrp
	lea	m72r_barpl,a1
	move.w	m72r_barnp,d7
	beq	.done
	cmp.w	#15,d7
	bhi	.grp
	subq.w	#1,d7
	moveq	#1,d0
.one:	move.w	(a1)+,d1
	move.b	d0,(a3,d1.w)
	move.w	d1,(a4)+
	addq.w	#1,d0
	dbf	d7,.one
	bra	.done
.grp:	st	m72r_bargrp
	lea	m72r_pcur,a2
	lea	m72r_barpc,a5		; (the colours, to see them change)
	moveq	#1,d6			; the next index
	subq.w	#1,d7
.g:	move.w	(a1)+,d1		; the pen
	move.w	d1,d2
	add.w	d2,d2
	move.w	(a2,d2.w),d2		; its colour
	move.w	d2,(a5)+
	lea	m72r_hrep+2,a0		; an index of that colour already?
	moveq	#1,d0
.gf:	cmp.w	d6,d0
	bhs	.gnew
	move.w	(a0)+,d3
	add.w	d3,d3
	cmp.w	(a2,d3.w),d2
	beq	.gset
	addq.w	#1,d0
	bra	.gf
.gnew:	cmp.w	#16,d6
	bhs	.near
	move.w	d6,d0
	move.w	d1,(a4)+
	addq.w	#1,d6
	bra	.gset
.near:	movem.l	d1/d6-d7/a1,-(sp)	; the nearest of the 15 (Oklab L1)
	lea	m72r_lab,a6
	lsl.w	#2,d2
	moveq	#0,d3
	move.b	(a6,d2.w),d3
	moveq	#0,d4
	move.b	1(a6,d2.w),d4
	moveq	#0,d5
	move.b	2(a6,d2.w),d5
	lea	m72r_hrep+2,a0
	moveq	#1,d0			; the best index
	move.w	#$7fff,d7		; its distance
	moveq	#1,d6
.nr:	move.w	(a0)+,d1		; the index's pen
	add.w	d1,d1
	move.w	(a2,d1.w),d1		; its colour
	lsl.w	#2,d1
	lea	(a6,d1.w),a1
	moveq	#0,d2
	move.b	(a1)+,d2
	sub.w	d3,d2
	bpl	.n1
	neg.w	d2
.n1:	moveq	#0,d1
	move.b	(a1)+,d1
	sub.w	d4,d1
	bpl	.n2
	neg.w	d1
.n2:	add.w	d1,d2
	moveq	#0,d1
	move.b	(a1)+,d1
	sub.w	d5,d1
	bpl	.n3
	neg.w	d1
.n3:	add.w	d1,d2
	cmp.w	d7,d2
	bhs	.nn
	move.w	d2,d7
	move.w	d6,d0
.nn:	addq.w	#1,d6
	cmp.w	#16,d6
	blo	.nr
	movem.l	(sp)+,d1/d6-d7/a1
.gset:	move.b	d0,(a3,d1.w)
	dbf	d7,.g
	move.w	d6,d1
	bra	.cnt
.done:	move.l	a4,d1
	sub.l	#m72r_hrep,d1
	lsr.w	#1,d1			; indices
.cnt:	move.b	d1,m72r_hncent
	; another mapping: every buffer's bar again
	lea	m72r_barnew,a0
	lea	m72r_hidx,a1
	moveq	#512/4-1,d0
	moveq	#0,d1
.cm:	move.l	(a0)+,d2
	cmp.l	(a1),d2
	beq	.cs
	moveq	#1,d1
.cs:	move.l	d2,(a1)+
	dbf	d0,.cm
	tst.w	d1
	beq	.r
	st	m72r_barfull
.r:	rts

; m72r_bardraw: the drawn buffer's bar (its tiles changed since its last picture, or all)
m72r_bardraw:
	tst.b	m72r_baron
	beq	.r
	movem.l	d0-d7/a0-a6,-(sp)
	move.w	m72r_draw,d0
	move.w	d0,d1
	mulu	#M72_BARSZ,d1
	lea	m72r_barbuf,a5
	add.l	d1,a5			; the buffer's bar
	move.w	d0,d1
	mulu	#M72_BARL/8*40*4,d1
	lea	m72r_barcp,a4
	add.l	d1,a4			; its tiles as last drawn
	moveq	#0,d7			; (all)
	bclr	d0,m72r_barfull
	beq	.p
	moveq	#1,d7
.p:	lea	m72r_barsig,a3
	move.w	m72r_bary1,d6
	sub.w	m72r_bary0,d6
	lsr.w	#3,d6
	subq.w	#1,d6			; rows - 1
	moveq	#0,d4			; the row
.r0:	moveq	#0,d5			; the column
.c0:	move.l	(a3)+,d0
	tst.w	d7
	bne	.dr
	cmp.l	(a4),d0
	beq	.cn
.dr:	move.l	d0,(a4)
	movem.l	d4-d7/a3-a5,-(sp)
	bsr	m72r_bartile
	movem.l	(sp)+,d4-d7/a3-a5
.cn:	addq.l	#4,a4
	addq.w	#1,d5
	cmp.w	#40,d5
	blo	.c0
	addq.w	#1,d4
	dbf	d6,.r0
	movem.l	(sp)+,d0-d7/a0-a6
.r:	rts

; m72r_bartile: tile entry d0 (as in video RAM) at bar row d4, column d5 of the bar a5, its pens through m72r_hidx
m72r_bartile:
	move.l	d0,d6
	swap	d6
	ror.w	#8,d6			; code with the flips (bits 14, 15)
	moveq	#0,d1
	move.w	d6,d1
	and.w	#M72_NTF-1,d1
	lea	m72r_uf,a0
	add.w	d1,d1
	move.w	(a0,d1.w),m72r_cpens
	lsl.l	#4,d1			; * 32
	lea	m72r_tf,a1
	add.l	d1,a1
	lsr.w	#8,d0
	and.w	#15,d0
	lsl.w	#4,d0
	lea	m72r_hidx+256,a4
	add.w	d0,a4			; the colour row's indices
	; the destination: row d4 (8 lines), column d5 (byte d5 & 1 of word group d5 / 2)
	moveq	#0,d0
	move.w	d4,d0
	moveq	#12,d1
	lsl.l	d1,d0			; * 8 * 512
	add.l	d0,a5
	move.w	d5,d0
	lsr.w	#1,d0
	lsl.w	#3,d0
	add.w	d0,a5
	moveq	#1,d0
	and.w	d5,d0
	add.w	d0,a5
	; the X tables (as m72r_conv), flipped
	lea	m72r_xt,a2
	lea	m72r_rev8,a3
	moveq	#4-1,d7
.ld:	move.l	(a1)+,d4
	move.l	(a1)+,d5
	btst	#14,d6
	beq	.nx
	moveq	#4-1,d3
.fx:	moveq	#0,d0
	rol.l	#8,d4
	move.b	d4,d0
	move.b	(a3,d0.w),d4
	moveq	#0,d0
	rol.l	#8,d5
	move.b	d5,d0
	move.b	(a3,d0.w),d5
	dbf	d3,.fx
.nx:	btst	#15,d6
	beq	.ny
	exg	d4,d5
	ror.w	#8,d4
	swap	d4
	ror.w	#8,d4
	ror.w	#8,d5
	swap	d5
	ror.w	#8,d5
.ny:	move.l	d4,(a2)
	not.l	d4
	move.l	d4,4(a2)
	move.l	d5,32(a2)
	not.l	d5
	move.l	d5,36(a2)
	addq.l	#8,a2
	dbf	d7,.ld
	lea	m72r_xt,a2
	bsr	.half
	lea	m72r_xt+32,a2
	add.l	#4*M72_LB,a5
.half:	moveq	#0,d0
	moveq	#0,d1
	moveq	#0,d2
	moveq	#0,d3
	move.w	m72r_cpens,d6
	and.w	#$fffe,d6
	lea	m72r_moff,a3
	moveq	#0,d7
.pen:	lsr.w	#1,d6
	bcc	.np
	move.l	a3,a6
	moveq	#0,d5
	move.b	(a6)+,d5
	move.l	(a2,d5.w),d4
	move.b	(a6)+,d5
	and.l	(a2,d5.w),d4
	move.b	(a6)+,d5
	and.l	(a2,d5.w),d4
	move.b	(a6)+,d5
	and.l	(a2,d5.w),d4
	move.b	(a4,d7.w),d5
	lsr.b	#1,d5
	bcc	.o1
	or.l	d4,d0
.o1:	lsr.b	#1,d5
	bcc	.o2
	or.l	d4,d1
.o2:	lsr.b	#1,d5
	bcc	.o3
	or.l	d4,d2
.o3:	lsr.b	#1,d5
	bcc	.np
	or.l	d4,d3
.np:	addq.l	#4,a3
	addq.w	#1,d7
	tst.w	d6
	bne	.pen
	move.l	a5,a6			; 4 lines: the planes' bytes 2 apart
	moveq	#4-1,d7
.w:	rol.l	#8,d0
	move.b	d0,(a6)
	rol.l	#8,d1
	move.b	d1,2(a6)
	rol.l	#8,d2
	move.b	d2,4(a6)
	rol.l	#8,d3
	move.b	d3,6(a6)
	lea	M72_LB(a6),a6
	dbf	d7,.w
	rts

; ======================================================================================================================
; m72r_choose: a new colour choice (m72r_need bit 0: the playfield, bit 1: the HUD bars)
; ======================================================================================================================
m72r_choose:
	movem.l	d0-d7/a0-a6,-(sp)
	btst	#0,m72r_need
	beq	.hud
	moveq	#0,d7
	tst.b	m72r_ncent		; (the first choice: an offline scene if one fits)
	bne	.c0
	bsr	m72r_match
	move.w	d0,m72r_nscene
.c0:	move.w	m72r_nscene,m72r_scene
	bmi	.km
	bsr	m72r_usescene
	bra	.c1
.km:	bsr	m72r_cluster		; (an unknown scene: the run-time choice)
	tst.b	m72r_cstage
	bne	.unf
.c1:
	lea	m72r_pcur,a0		; the colours the mapping was made with
	lea	m72r_psnap,a1
	move.w	#512/2-1,d0
.sn:	move.l	(a0)+,(a1)+
	dbf	d0,.sn
	bsr	m72r_bgnn		; (m72r_p0 may have changed: the BG's flags again, over calls)
	addq.w	#1,m72r_epoch
	st	m72r_vclr
	lea	m72r_flags+V_F,a0	; every tile converted again
	move.w	#1024/4-1,d0
.v:	clr.l	(a0)+
	dbf	d0,.v
	bsr	m72r_sflush
	bsr	m72r_shall		; (the sprite rows' mapping hashes)
	bclr	#0,m72r_need
	clr.w	m72r_since
	lea	m72r_suse,a0		; (the pens in use: from now on)
	moveq	#16-1,d0
.cu:	clr.l	(a0)+
	dbf	d0,.cu
	lea	m72r_dcol,a0		; (every pen looked at again: pending, its colour as now)
	lea	m72r_pcur,a1
	move.w	#512/2-1,d0
.cd:	move.l	(a1)+,(a0)+
	dbf	d0,.cd
	lea	m72r_dres,a0
	move.w	#512/4-1,d0
.cr:	move.l	#$01010101,(a0)+
	dbf	d0,.cr
	st	m72r_ufull		; (the representatives among the used pens: the next picture)
.hud:	bra	.all			; (the bars' colours: m72r_barpens, exact; no choice here)
	btst	#1,m72r_need
	beq	.all
	tst.b	m72r_hud_on
	beq	.all
	moveq	#1,d7
	tst.w	m72r_scene		; (the scene's HUD colours if it has them)
	bmi	.hk
	move.l	a0,-(sp)
	lea	m72r_paltab+2,a0
	move.w	m72r_scene,d0
	mulu	#M72_SCENE,d0
	add.l	d0,a0
	tst.w	642(a0)
	move.l	(sp)+,a0
	beq	.hk
	move.w	m72r_scene,m72r_nscene
	bsr	m72r_usescene
	bra	.hk1
.hk:	bsr	m72r_cluster
	tst.b	m72r_cstage
	bne	.unf
.hk1:	addq.w	#1,m72r_epoch		; (the conversion cache's HUD entries are stale)
	st	m72r_vclr
	lea	m72r_hudrow,a0		; the bars' rows converted again
	lea	m72r_flags+V_F,a1
	moveq	#64-1,d0
.hr:	tst.b	(a0)+
	beq	.hn
	clr.l	(a1)
	clr.l	4(a1)
.hn:	addq.l	#8,a1
	dbf	d0,.hr
.all:	lea	m72r_bs,a0		; every buffer drawn again
	moveq	#REN_NBUF-1,d0
.b:	move.w	#-1,BS_W(a0)
	lea	BS_SIZE(a0),a0
	dbf	d0,.b
	clr.b	m72r_need
	addq.l	#1,m72r_clusters
.unf:	movem.l	(sp)+,d0-d7/a0-a6
	rts

; m72r_cluster: d7 = 0 the playfield (the lines outside the HUD bars), 1 the HUD bars: the centres, representatives and
; the mapping (m72r_pidx / m72r_hidx); the playfield's also m72r_p0 (the index most BG samples have)
m72r_cluster:
	move.w	d7,m72r_ckind
	tst.b	m72r_cstage		; (the samples taken in the call before: the rest now)
	beq	.s0
	clr.b	m72r_cstage
	bra	.nospr
.s0:	lea	m72r_hist,a0		; (m72r_hist, m72r_bgw)
	move.w	#1024-1,d0
.c:	clr.l	(a0)+
	dbf	d0,.c
	; the samples: a pixel every 8 pixels, every M72_NSAMP lines
	moveq	#2,d6			; the line
.line:	move.w	d6,d0
	cmp.w	m72r_htop,d0
	blo	.inh
	cmp.w	m72r_hbot,d0
	bhs	.inh
	tst.w	m72r_ckind
	bne	.nl
	bra	.take
.inh:	tst.w	m72r_ckind
	beq	.nl
.take:	lea	m72r_lband,a0
	moveq	#0,d0
	move.b	(a0,d6.w),d0
	lsl.w	#4,d0
	lea	m72r_bt,a4
	add.w	d0,a4
	tst.w	BT_OFF(a4)
	bne	.nl
	moveq	#3,d5			; the first x
	btst	#2,d6
	beq	.x
	moveq	#7,d5
.x:	move.w	m72r_W,d2
	add.w	d5,d2			; buffer x
	moveq	#0,d0			; FG
	move.w	BT_OXF(a4),d3
	add.w	d2,d3
	move.w	BT_OYF(a4),d4
	add.w	d6,d4
	bsr	m72r_pixpen
	tst.w	d0
	bne	.fg
	moveq	#1,d0			; BG
	move.w	BT_OXB(a4),d3
	add.w	d2,d3
	move.w	BT_OYB(a4),d4
	add.w	d6,d4
	bsr	m72r_pixpen
	lsl.w	#4,d1
	add.w	d1,d0
	add.w	#256,d0
	lsl.w	#2,d0
	lea	m72r_bgw,a0
	add.l	#16,(a0,d0.w)
	bra	.add
.fg:	lsl.w	#4,d1
	add.w	d1,d0
	add.w	#256,d0
	lsl.w	#2,d0
.add:	lea	m72r_hist,a0
	add.l	#16,(a0,d0.w)
	addq.w	#8,d5
	cmp.w	#320,d5
	blo	.x
.nl:	addq.w	#M72_NSAMP,d6
	cmp.w	#256,d6
	blo	.line
	tst.w	m72r_ckind
	bne	.smp
	bsr	m72r_sprpens
.smp:	st	m72r_cstage		; (the samples this call, the choice the next: m72r_choose returns unfinished)
	rts
.nospr:	; the colours: pens with samples, by their colour
	lea	m72r_hist,a0
	lea	m72r_pcur,a1
	lea	m72r_ckw,a2
	lea	m72r_ckey,a3
	moveq	#0,d5			; colours
	moveq	#0,d0
.pc:	move.l	(a0)+,d1
	beq	.pn
	move.w	d0,d2
	add.w	d2,d2
	move.w	(a1,d2.w),d2		; the colour
	move.w	d2,d3
	lsl.w	#2,d3
	tst.l	(a2,d3.w)
	bne	.pk
	move.w	d2,(a3)+		; a new colour
	addq.w	#1,d5
.pk:	add.l	d1,(a2,d3.w)
.pn:	addq.w	#1,d0
	cmp.w	#512,d0
	blo	.pc
	move.w	d5,m72r_ncol
	; their weights (the square root, 1-127) and Oklab (words: L a b, 0)
	lea	m72r_ckey,a3
	lea	m72r_cwt,a4
	lea	m72r_clw,a5
	lea	m72r_lab,a6
	move.w	d5,d7
	subq.w	#1,d7
	bmi	.nocol
.cw:	move.w	(a3)+,d2
	move.w	d2,d3
	lsl.w	#2,d3
	move.l	(a2,d3.w),d0
	clr.l	(a2,d3.w)
	bsr	m72r_isqrt
	cmp.w	#127,d0
	bls	.w1
	moveq	#127,d0
.w1:	tst.w	d0
	bne	.w2
	moveq	#1,d0
.w2:	move.w	d0,(a4)+
	moveq	#0,d0
	move.b	(a6,d3.w),d0
	move.w	d0,(a5)+
	move.b	1(a6,d3.w),d0
	move.w	d0,(a5)+
	move.b	2(a6,d3.w),d0
	move.w	d0,(a5)+
	clr.w	(a5)+
	dbf	d7,.cw
.nocol:	; the centres: black, then the farthest colour by weight, 15 times
	lea	m72r_ccw,a0
	moveq	#0,d0
	move.b	(a6),d0			; (black: the STE colour 0)
	move.w	d0,(a0)+
	move.b	1(a6),d0
	move.w	d0,(a0)+
	move.b	2(a6),d0
	move.w	d0,(a0)+
	clr.w	(a0)+
	move.w	#1,m72r_nc
	lea	m72r_cdist,a2		; the distances to the nearest centre
	move.w	m72r_ncol,d7
	subq.w	#1,d7
	bmi	.seeded
.d0:	move.w	#$7fff,(a2)+
	dbf	d7,.d0
	lea	m72r_ccw,a0
	bsr	m72r_cdupd
.seed:	cmp.w	#16,m72r_nc
	bhs	.seeded
	lea	m72r_cdist,a2
	lea	m72r_cwt,a3
	moveq	#0,d5			; the best value
	moveq	#-1,d6			; its colour
	moveq	#0,d3
	move.w	m72r_ncol,d7
	subq.w	#1,d7
.sb:	move.w	(a2)+,d0
	mulu	(a3)+,d0
	cmp.l	d5,d0
	bls	.sn
	move.l	d0,d5
	move.w	d3,d6
.sn:	addq.w	#1,d3
	dbf	d7,.sb
	tst.l	d5
	beq	.seeded
	lea	m72r_clw,a1
	lsl.w	#3,d6
	move.w	m72r_nc,d1
	lsl.w	#3,d1
	lea	m72r_ccw,a0
	add.w	d1,a0
	move.l	(a1,d6.w),(a0)
	move.l	4(a1,d6.w),4(a0)
	addq.w	#1,m72r_nc
	bsr	m72r_cdupd		; (the distances to the new centre a0)
	bra	.seed
.seeded:
	; k-means, 6 rounds (the black centre stays)
	moveq	#6-1,d7
.round:	move.w	d7,-(sp)
	lea	m72r_csum,a0
	moveq	#16*4-1,d0
.cs:	clr.l	(a0)+
	dbf	d0,.cs
	lea	m72r_clw,a1
	lea	m72r_cwt,a3
	move.w	m72r_ncol,d7
	subq.w	#1,d7
	bmi	.rx
.as:	movem.w	(a1),d3-d5		; the colour
	bsr	m72r_nearw		; -> d1 the centre
	move.w	(a3)+,d2		; the weight
	lsl.w	#4,d1
	lea	m72r_csum,a0
	add.w	d1,a0
	move.w	d3,d0
	mulu	d2,d0
	add.l	d0,(a0)+
	move.w	d4,d0
	mulu	d2,d0
	add.l	d0,(a0)+
	move.w	d5,d0
	mulu	d2,d0
	add.l	d0,(a0)+
	ext.l	d2
	add.l	d2,(a0)+
	addq.l	#8,a1
	dbf	d7,.as
	lea	m72r_csum+16,a0		; the new centres 1 ..
	lea	m72r_ccw+8,a1
	move.w	m72r_nc,d7
	subq.w	#2,d7
	bmi	.rx
.nc:	move.l	12(a0),d2
	beq	.nn
	move.l	(a0),d0
	divu	d2,d0
	move.w	d0,(a1)
	move.l	4(a0),d0
	divu	d2,d0
	move.w	d0,2(a1)
	move.l	8(a0),d0
	divu	d2,d0
	move.w	d0,4(a1)
.nn:	lea	16(a0),a0
	addq.l	#8,a1
	dbf	d7,.nc
.rx:	move.w	(sp)+,d7
	dbf	d7,.round
	; the representatives: per centre the member colour nearest it, its heaviest pen
	lea	m72r_rbest,a0
	moveq	#16-1,d0
.rb:	move.w	#$7fff,(a0)+
	dbf	d0,.rb
	lea	m72r_rkey,a0
	moveq	#16-1,d0
.rk:	move.w	#-1,(a0)+
	dbf	d0,.rk
	lea	m72r_clw,a1
	lea	m72r_ckey,a3
	move.w	m72r_ncol,d7
	subq.w	#1,d7
	bmi	.repd
.rm:	movem.w	(a1),d3-d5
	bsr	m72r_nearw		; d1 = centre, d2 = distance
	add.w	d1,d1
	lea	m72r_rbest,a0
	cmp.w	(a0,d1.w),d2
	bhs	.rn
	move.w	d2,(a0,d1.w)
	lea	m72r_rkey,a0
	move.w	(a3),(a0,d1.w)
.rn:	addq.l	#2,a3
	addq.l	#8,a1
	dbf	d7,.rm
.repd:	lea	m72r_rep,a2
	tst.w	m72r_ckind
	beq	.r0
	lea	m72r_hrep,a2
.r0:	moveq	#0,d6			; centre
.rp:	move.w	d6,d0
	add.w	d0,d0
	lea	m72r_rkey,a0
	move.w	(a0,d0.w),d4		; its key
	clr.w	(a2,d0.w)
	tst.w	d4
	bmi	.rq
	lea	m72r_pcur,a0
	lea	m72r_hist,a1
	moveq	#0,d5			; the best weight
	moveq	#0,d3
.rs:	cmp.w	(a0)+,d4
	bne	.rt
	move.w	d3,d1
	lsl.w	#2,d1
	move.l	(a1,d1.w),d1
	cmp.l	d5,d1
	bls	.rt
	move.l	d1,d5
	move.w	d3,(a2,d0.w)
.rt:	addq.w	#1,d3
	cmp.w	#512,d3
	blo	.rs
.rq:	addq.w	#1,d6
	cmp.w	#16,d6
	blo	.rp
	; the mapping: every pen to its colour's nearest centre (once a colour: m72r_ckmap, 255 = not yet)
	lea	m72r_pidx,a2
	tst.w	m72r_ckind
	beq	.m0
	lea	m72r_hidx,a2
.m0:	lea	m72r_pcur,a3
	lea	m72r_lab,a6
	lea	m72r_ckmap,a4
	moveq	#0,d6
.mp:	move.w	(a3)+,d0
	move.b	(a4,d0.w),d1
	cmp.b	#255,d1
	bne	.mk
	lsl.w	#2,d0
	moveq	#0,d3
	move.b	(a6,d0.w),d3
	moveq	#0,d4
	move.b	1(a6,d0.w),d4
	moveq	#0,d5
	move.b	2(a6,d0.w),d5
	bsr	m72r_nearw
	move.w	-2(a3),d0
	move.b	d1,(a4,d0.w)
.mk:	move.b	d1,(a2)+
	addq.w	#1,d6
	cmp.w	#512,d6
	blo	.mp
	lea	m72r_pcur,a3		; (m72r_ckmap back to 255)
	move.w	#512-1,d6
.mc:	move.w	(a3)+,d0
	st	(a4,d0.w)
	dbf	d6,.mc
	; the centres as bytes (m72r_cent / m72r_hcent: L a b 0, for the test)
	lea	m72r_ccw,a0
	lea	m72r_cc,a1
	moveq	#16-1,d0
.cb:	move.w	(a0)+,d1
	move.b	d1,(a1)+
	move.w	(a0)+,d1
	move.b	d1,(a1)+
	move.w	(a0)+,d1
	move.b	d1,(a1)+
	clr.b	(a1)+
	addq.l	#2,a0
	dbf	d0,.cb
	move.w	m72r_nc,d0
	tst.w	m72r_ckind
	bne	.hk
	move.b	d0,m72r_ncent
	; m72r_p0: the index of most BG samples
	lea	m72r_csum,a0
	moveq	#16-1,d0
.pz:	clr.l	(a0)+
	dbf	d0,.pz
	lea	m72r_bgw,a0
	lea	m72r_pidx,a1
	lea	m72r_csum,a2
	moveq	#0,d0
.pb:	move.l	(a0)+,d1
	beq	.pb1
	moveq	#0,d2
	move.b	(a1,d0.w),d2
	lsl.w	#2,d2
	add.l	d1,(a2,d2.w)
.pb1:	addq.w	#1,d0
	cmp.w	#512,d0
	blo	.pb
	moveq	#0,d1			; the best
	moveq	#0,d2
	moveq	#0,d0
.pm:	move.l	(a2)+,d3
	cmp.l	d1,d3
	bls	.pm1
	move.l	d3,d1
	move.w	d0,d2
.pm1:	addq.w	#1,d0
	cmp.w	#16,d0
	blo	.pm
	move.b	d2,m72r_p0
	lea	m72r_cc,a0
	lea	m72r_cent,a1
	moveq	#16-1,d0
.cc:	move.l	(a0)+,(a1)+
	dbf	d0,.cc
	rts
.hk:	move.b	d0,m72r_hncent
	lea	m72r_cc,a0
	lea	m72r_hcent,a1
	moveq	#16-1,d0
.hc:	move.l	(a0)+,(a1)+
	dbf	d0,.hc
	rts

; m72r_cdupd: m72r_cdist[i] = min(itself, the L1 distance of colour i (m72r_clw) to centre a0 (words L a b))
m72r_cdupd:
	movem.l	d0-d7/a1-a2,-(sp)
	movem.w	(a0),d3-d5
	lea	m72r_clw,a1
	lea	m72r_cdist,a2
	move.w	m72r_ncol,d7
	subq.w	#1,d7
	bmi	.x
.c:	move.w	(a1)+,d0
	sub.w	d3,d0
	bpl	.p1
	neg.w	d0
.p1:	move.w	(a1)+,d1
	sub.w	d4,d1
	bpl	.p2
	neg.w	d1
.p2:	add.w	d1,d0
	move.w	(a1)+,d1
	sub.w	d5,d1
	bpl	.p3
	neg.w	d1
.p3:	add.w	d1,d0
	addq.l	#2,a1
	cmp.w	(a2),d0
	bhs	.n
	move.w	d0,(a2)
.n:	addq.l	#2,a2
	dbf	d7,.c
.x:	movem.l	(sp)+,d0-d7/a1-a2
	rts

; m72r_nearw: d1 = the nearest centre (m72r_ccw, m72r_nc of them) of the colour d3 d4 d5 (L a b words), d2 = its
; distance; keeps the others but d0
m72r_nearw:
	movem.l	d6-d7/a0,-(sp)
	lea	m72r_ccw,a0
	move.w	#$7fff,d2		; the best distance
	moveq	#0,d1			; its centre
	move.w	m72r_nc,d7
	subq.w	#1,d7
.c:	move.w	(a0)+,d0
	sub.w	d3,d0
	bpl	.p1
	neg.w	d0
.p1:	move.w	(a0)+,d6
	sub.w	d4,d6
	bpl	.p2
	neg.w	d6
.p2:	add.w	d6,d0
	move.w	(a0)+,d6
	sub.w	d5,d6
	bpl	.p3
	neg.w	d6
.p3:	add.w	d6,d0
	addq.l	#2,a0
	cmp.w	d2,d0
	bhs	.n
	move.w	d0,d2
	move.w	m72r_nc,d1
	subq.w	#1,d1
	sub.w	d7,d1
.n:	dbf	d7,.c
	movem.l	(sp)+,d6-d7/a0
	rts

; m72r_isqrt: d0 = the integer square root of d0 (32 bits; the result < 65536); destroys d1-d2
m72r_isqrt:
	movem.l	d3,-(sp)
	moveq	#0,d1			; the result
	move.l	#$40000000,d2		; the bit
.b:	cmp.l	d0,d2
	bls	.l
	lsr.l	#2,d2
	bne	.b
	bra	.x
.l:	move.l	d1,d3
	add.l	d2,d3
	cmp.l	d3,d0
	blo	.s
	sub.l	d3,d0
	lsr.l	#1,d1
	add.l	d2,d1
	bra	.n
.s:	lsr.l	#1,d1
.n:	lsr.l	#2,d2
	bne	.l
.x:	move.l	d1,d0
	movem.l	(sp)+,d3
	rts

; m72r_pixpen: the pen d0 and colour d1 of layer d0's map pixel (d3 x, d4 y; any, mod 512); keeps d2-d7
m72r_pixpen:
	movem.l	d2-d7/a0-a1,-(sp)
	and.w	#511,d3
	and.w	#511,d4
	move.w	d4,d5
	lsr.w	#3,d5
	lsl.w	#6,d5
	move.w	d3,d6
	lsr.w	#3,d6
	add.w	d6,d5
	lsl.w	#2,d5			; the entry
	lea	m72v_fg,a0
	lea	m72r_tf,a1
	move.w	#M72_NTF-1,d7
	tst.w	d0
	beq	.l
	lea	m72v_bg,a0
	lea	m72r_tb,a1
	move.w	#M72_NTB-1,d7
.l:	add.w	d5,a0
	move.b	1(a0),d5		; the code
	lsl.w	#8,d5
	move.b	(a0),d5
	moveq	#15,d1
	and.b	2(a0),d1		; the colour
	and.w	#7,d3
	and.w	#7,d4
	btst	#14,d5
	beq	.fx
	eor.w	#7,d3
.fx:	btst	#15,d5
	beq	.fy
	eor.w	#7,d4
.fy:	and.w	d7,d5
	moveq	#0,d6
	move.w	d5,d6
	lsl.l	#5,d6
	add.l	d6,a1
	add.w	d4,a1			; the row of plane 0
	eor.w	#7,d3			; the bit
	moveq	#0,d0
	btst	d3,(a1)
	beq	.b1
	moveq	#1,d0
.b1:	btst	d3,8(a1)
	beq	.b2
	addq.w	#2,d0
.b2:	btst	d3,16(a1)
	beq	.b3
	addq.w	#4,d0
.b3:	btst	d3,24(a1)
	beq	.b4
	addq.w	#8,d0
.b4:	movem.l	(sp)+,d2-d7/a0-a1
	rts

; m72r_sprpens: the visible sprite entries' pens into the histogram (4 a pen a piece)
m72r_sprpens:
	moveq	#0,d7
.ent:	cmp.w	#128,d7
	bhs	.x
	lea	m72v_spr,a0
	move.w	d7,d0
	lsl.w	#3,d0
	add.w	d0,a0
	move.b	1(a0),d0		; y
	lsl.w	#8,d0
	move.b	(a0),d0
	and.w	#$1ff,d0
	move.b	3(a0),d1		; code
	lsl.w	#8,d1
	move.b	2(a0),d1
	move.b	5(a0),d2		; attribute
	lsl.w	#8,d2
	move.b	4(a0),d2
	move.b	7(a0),d3		; x
	lsl.w	#8,d3
	move.b	6(a0),d3
	and.w	#$3ff,d3
	sub.w	#256+96,d3		; picture x
	move.w	d2,d4
	rol.w	#2,d4
	and.w	#3,d4
	moveq	#1,d5
	lsl.w	d4,d5			; w
	move.w	d2,d4
	lsr.w	#8,d4
	lsr.w	#4,d4
	and.w	#3,d4
	moveq	#1,d6
	lsl.w	d4,d6			; h
	add.w	d5,d7
	; in the window?
	move.w	d6,d4
	lsl.w	#4,d4
	move.w	#384,d0
	sub.w	d0,d0
	move.b	1(a0),d0
	lsl.w	#8,d0
	move.b	(a0),d0
	and.w	#$1ff,d0
	neg.w	d0
	add.w	#384,d0
	sub.w	d4,d0			; y
	cmp.w	#256,d0
	bge	.ent
	add.w	d4,d0
	ble	.ent
	cmp.w	#320,d3
	bge	.ent
	move.w	d5,d4
	lsl.w	#4,d4
	add.w	d4,d3
	ble	.ent
	; the pieces' pens
	and.w	#15,d2
	lsl.w	#6,d2			; colour * 16 * 4 (the histogram's longs)
	subq.w	#1,d5
.px:	move.w	d6,d4
	subq.w	#1,d4
.py:	move.w	d5,d0
	lsl.w	#3,d0
	add.w	d4,d0
	add.w	d1,d0
	and.w	#4096-1,d0
	lsl.w	#2,d0
	lea	m72r_su,a1
	move.w	(a1,d0.w),d0		; the pens
	and.w	#$fffe,d0
	lea	m72r_hist,a1
	add.w	d2,a1
.pp:	lsr.w	#1,d0
	addq.l	#4,a1
	bcc	.pq
	add.l	#M72_SPRW,-4(a1)
.pq:	tst.w	d0
	bne	.pp
	dbf	d4,.py
	dbf	d5,.px
	bra	.ent
.x:	rts

; ======================================================================================================================
; data
; ======================================================================================================================
	section	data,data
	even
m72r_tf:	incbin	"m72_tf.bin"
m72r_uf:	incbin	"m72_uf.bin"
m72r_tb:	incbin	"m72_tb.bin"
m72r_ub:	incbin	"m72_ub.bin"
m72r_sp:	incbin	"m72_sp.bin"
m72r_su:	incbin	"m72_su.bin"
m72r_lab:	incbin	"m72_lab.bin"
m72r_q4:	incbin	"m72_q4.bin"
	even
m72r_paltab:	incbin	"m72_pal.bin"
	even

; ======================================================================================================================
; bss
; ======================================================================================================================
	section	bss,bss
	even
; the video state (the interface, see the top)
	ifnd	M72V_EXTERN
m72v_fg:	ds.b	$4000
m72v_bg:	ds.b	$4000
m72v_spr:	ds.b	$400
m72v_pal0:	ds.b	$c00
m72v_pal1:	ds.b	$c00
	endc
m72v_nbands:	ds.w	1
m72v_bands:	ds.w	8*6
m72v_vdirty:	ds.b	128
m72v_pdirty:	ds.b	1
	even
; the published pictures (for the VBL)
m72r_vbl_pal:	ds.w	16
m72r_vbl_hpal:	ds.w	16
m72r_vbl_htop:	ds.w	1
m72r_vbl_hbot:	ds.w	1
m72r_disp_addr:	ds.l	REN_NBUF
m72r_disp_fine:	ds.b	REN_NBUF
	even
m72r_disp_pal:	ds.w	16*REN_NBUF
m72r_disp_hpal:	ds.w	16*REN_NBUF
m72r_disp_hud:	ds.w	2*REN_NBUF
m72r_disp_bar:	ds.l	REN_NBUF
m72r_baron:	ds.b	1
m72r_barfull:	ds.b	1
m72r_barpd:	ds.b	1
m72r_bargrp:	ds.b	1
m72r_bary0:	ds.w	1
m72r_bary1:	ds.w	1
m72r_barmx:	ds.w	1
m72r_barmy:	ds.w	1
m72r_barnp:	ds.w	1
m72r_barpl:	ds.w	512
m72r_barpc:	ds.w	512
m72r_barset:	ds.b	512
m72r_barnew:	ds.b	512
m72r_barsig:	ds.l	M72_BARL/8*40
m72r_barcp:	ds.l	REN_NBUF*M72_BARL/8*40
m72r_barbuf:	ds.b	REN_NBUF*M72_BARSZ
m72r_buf:	ds.l	REN_NBUF+1
m72r_dbuf:	ds.l	1
m72r_cbs:	ds.l	1
m72r_draw:	ds.w	1
m72r_shown:	ds.w	1
m72r_prev:	ds.w	1
m72r_ready:	ds.b	1
m72r_need:	ds.b	1
m72r_hud_on:	ds.b	1
m72r_ncent:	ds.b	1
m72r_hncent:	ds.b	1
m72r_p0:	ds.b	1
m72r_spri_on:	ds.b	1
m72r_poff:	ds.b	1
m72r_x_op:	ds.b	1
m72r_x_rd:	ds.b	1
m72r_x_op2:	ds.b	1
m72r_fast:	ds.b	1
m72r_entany:	ds.b	1
m72r_rmov:	ds.b	1
m72r_bmov:	ds.b	8
m72r_pchg:	ds.b	1
m72r_x_sk:	ds.b	1
m72r_x_dk:	ds.b	1
	even
m72r_pictures:	ds.l	1
m72r_skipped:	ds.l	1
m72r_clusters:	ds.l	1
m72r_flushes:	ds.l	1
m72r_nconv:	ds.l	1
m72r_nsconv:	ds.l	1
m72r_ncinval:	ds.l	1
m72r_st_ent:	ds.l	1
m72r_st_entin:	ds.l	1
m72r_st_pc:	ds.l	1
m72r_st_drawn:	ds.l	1
m72r_st_clip:	ds.l	1
m72r_st_mmiss:	ds.l	1
m72r_st_pri:	ds.l	1
m72r_st_fast:	ds.l	1
m72r_st_gmiss:	ds.l	1
m72r_nmiss:	ds.l	1
m72r_xarea:	ds.l	1
m72r_nx:	ds.l	1
m72r_nx2:	ds.l	1
m72r_st_xr:	ds.l	1
m72r_st_runs:	ds.l	1
m72r_st_bg:	ds.l	1
m72r_st_fg:	ds.l	1
m72r_st_mx:	ds.l	1
m72r_st_bod:	ds.l	1
m72r_epoch:	ds.w	1
m72r_rest:	ds.w	1
m72r_follow:	ds.w	1
m72r_last:	ds.w	3
m72r_mv:	ds.b	3
m72r_fvote:	ds.b	1
m72r_switches:	ds.l	1
m72r_fcount:	ds.w	1
m72r_W:		ds.w	1
m72r_nb:	ds.w	1
m72r_bt:	ds.b	8*16
m72r_lband:	ds.b	256
m72r_win:	ds.l	4
m72r_win64:	ds.l	2
m72r_wl0:	ds.w	1
m72r_wln:	ds.w	1
m72r_ent:	ds.l	4
m72r_R:		ds.l	4
m72r_cbg:	ds.l	4
m72r_cfg:	ds.l	4
m72r_cmx:	ds.l	4
m72r_csl:	ds.l	4
m72r_fd:	ds.l	2
m72r_bd:	ds.l	2
m72r_ne:	ds.l	2
m72r_bnn:	ds.l	2
m72r_fv:	ds.l	2
m72r_fo:	ds.l	2
m72r_fund:	ds.l	2
m72r_bbod:	ds.l	2
m72r_pne:	ds.l	2
m72r_fpri:	ds.l	2
m72r_bpri:	ds.l	2
m72r_pnn:	ds.l	2
m72r_frver:	ds.w	64
m72r_brver:	ds.w	64
m72r_fcache:	ds.b	64*FC_SIZE
m72r_bcache:	ds.b	64*BC_SIZE
m72r_row:	ds.w	1
m72r_nseg:	ds.w	1
m72r_seg:	ds.b	4*SG_SIZE
m72r_nrun:	ds.w	1
m72r_runl:	ds.w	2*72
m72r_x_dx:	ds.w	1
m72r_x_w:	ds.w	1
m72r_x_y0:	ds.w	1
m72r_x_n:	ds.w	1
m72r_x_ox:	ds.w	1
m72r_x_oy:	ds.w	1
m72r_x_planes:	ds.w	1
m72r_x_piece:	ds.w	1
m72r_x_src:	ds.l	1
m72r_x_sstep:	ds.l	1
m72r_x_dstep:	ds.l	1
m72r_x_s0:	ds.l	1
m72r_x_src2:	ds.l	1
m72r_x_sl:	ds.w	1
m72r_tw0:	ds.w	1
m72r_tnd:	ds.w	1
m72r_ty0:	ds.w	1
m72r_bplane:	ds.w	1
m72r_tmp:	ds.w	24*8
m72r_tmp2:	ds.w	24*8
m72r_vmask:	ds.l	2
m72r_vbt:	ds.b	128
m72r_vW:	ds.w	1
m72r_vnb:	ds.w	1
m72r_vclr:	ds.b	1
m72r_late:	ds.b	1
	even
m72r_budget:	ds.w	1
m72r_lates:	ds.l	1
	even
m72r_vlay:	ds.w	1
m72r_cl:	ds.w	1
m72r_cr:	ds.w	1
m72r_cattr:	ds.w	1
m72r_cpens:	ds.w	1
m72r_nbod:	ds.w	1
m72r_bkpend:	ds.w	1
m72r_bkmark:	ds.b	128
m72r_rowchg:	ds.b	128
m72r_vrchg:	ds.b	128
m72r_cstage:	ds.b	1
	even
m72r_bulks:	ds.l	1
m72r_chg:	ds.l	M72_BULK
m72r_fbytes:	ds.b	64
m72r_ctile:	ds.w	1
m72r_ccslot:	ds.l	1
m72r_ccdat:	ds.l	1
m72r_cc_slots:	ds.b	M72_CCN*M72_CCS
m72r_tcf:	ds.b	M72_NTF
m72r_tcb:	ds.b	M72_NTB
m72r_htop:	ds.w	1
m72r_hbot:	ds.w	1
m72r_hy:	ds.w	1
m72r_hy1:	ds.w	1
m72r_hudrow:	ds.b	64
m72r_newhud:	ds.b	64
; sprites
m72r_sx:	ds.w	1
m72r_sy:	ds.w	1
m72r_sw:	ds.w	1
m72r_sh:	ds.w	1
m72r_scode:	ds.w	1
m72r_sattr:	ds.w	1
m72r_px:	ds.w	1
m72r_py:	ds.w	1
m72r_pcode:	ds.w	1
m72r_bx:	ds.w	1
m72r_by:	ds.w	1
m72r_pband:	ds.w	1
m72r_pfg:	ds.w	8
m72r_pstream:	ds.l	16
m72r_pbg:	ds.w	8
m72r_sy0:	ds.w	1
m72r_sy1:	ds.w	1
m72r_smp:	ds.l	1
m72r_spp:	ds.l	1
m72r_poolp:	ds.l	1
; tables
m72r_rev8:	ds.b	256
	even
m72r_stab:	ds.l	16*256
m72r_stv:	ds.b	16
m72r_spread:	ds.l	16
m72r_sopq:	ds.l	256
m72r_nswap:	ds.b	256
m72r_lz8:	ds.b	256
m72r_pop8:	ds.b	256
m72r_ptab:	ds.b	128
m72r_xtab:	ds.w	64
m72r_moff:	ds.b	64
m72r_xt:	ds.l	16
; colours
m72r_palsh:	ds.b	2*$c00
m72r_pcur:	ds.w	512
m72r_psnap:	ds.w	512
m72r_pidx:	ds.b	512
m72r_hidx:	ds.b	512
m72r_rep:	ds.w	16
m72r_umask:	ds.w	32
m72r_ubest:	ds.w	16
m72r_ucyc:	ds.w	1
m72r_ufull:	ds.b	1
	even
m72r_suse:	ds.w	32
m72r_cver:	ds.w	16
m72r_rowmap:	ds.b	2*16*512
m72r_tcol:	ds.b	2*4096
m72r_cnn:	ds.b	1
	even
m72r_rpcnt:	ds.w	16
m72r_nrepurp:	ds.l	1
m72r_nrepfix:	ds.l	1
m72r_rpmask:	ds.l	1
m72r_rpwait:	ds.w	1
m72r_dpend:	ds.b	1
m72r_sonly:	ds.b	1
	even
m72r_rpdone:	ds.b	1
	even
m72r_scver:	ds.w	16
M72_SROWS	= 4
m72r_srows:	ds.b	16*M72_SROWS*18
m72r_srnext:	ds.b	16
m72r_srver:	ds.w	1
m72r_skv:	ds.w	1
m72r_dcol:	ds.w	512
m72r_dtime:	ds.w	512
m72r_dbest:	ds.w	512
m72r_dres:	ds.b	512
m72r_dchg:	ds.w	1
m72r_cepk:	ds.w	1
m72r_nfar:	ds.w	1
m72r_since:	ds.w	1
m72r_kwait:	ds.w	1
m72r_kscene:	ds.w	1
m72r_dtry:	ds.b	1
m72r_cwait:	ds.b	32
	even
m72r_divp:	ds.b	1
	even
m72r_slab:	ds.l	16
	even
m72r_hrep:	ds.w	16
m72r_stepal:	ds.w	16
m72r_stehpal:	ds.w	16
m72r_cent:	ds.l	16
m72r_hcent:	ds.l	16
m72r_cc:	ds.l	16
m72r_csum:	ds.l	16*4
m72r_rbest:	ds.w	16
m72r_rkey:	ds.w	16
m72r_ckind:	ds.w	1
m72r_scene:	ds.w	1
m72r_nscene:	ds.w	1
m72r_unk:	ds.b	1
	even
m72r_ncol:	ds.w	1
m72r_nc:	ds.w	1
m72r_hist:	ds.l	512
m72r_bgw:	ds.l	512
m72r_ckw:	ds.l	4096
m72r_ckey:	ds.w	512
m72r_cwt:	ds.w	512
m72r_clw:	ds.w	4*512
m72r_ccw:	ds.w	4*16
m72r_ckmap:	ds.b	4096
m72r_ckdist:	ds.w	4096
m72r_cdist:	ds.w	512
; the flags, the copies of video RAM, the buffers' states
m72r_flags:	ds.b	M72_FLSZ
m72r_shadow:	ds.b	$8000
m72r_bs:	ds.b	REN_NBUF*BS_SIZE
; the sprite cache
m72r_hash:	ds.l	2*M72_HASH
m72r_mhash:	ds.l	2*M72_MHASH
m72r_mpoolp:	ds.l	1
m72r_ghash:	ds.l	2*M72_GHASH
m72r_gpoolp:	ds.l	1
m72r_gpool:	ds.b	M72_GPOOL
M72_MAXP	= 1024
m72r_plist:	ds.w	4*M72_MAXP
m72r_psaved:	ds.b	M72_MAXP
m72r_np:	ds.w	1
m72r_psv:	ds.b	1
m72r_anypri:	ds.b	1
	even
m72r_svc:	ds.w	REN_NBUF
m72r_svl:	ds.b	REN_NBUF*M72_SVN*12
m72r_svp:	ds.b	REN_NBUF*M72_SVSZ
m72r_mpool:	ds.b	M72_MPOOL
m72r_pool:	ds.b	M72_POOL
; the layer images and the buffers
m72r_imgf:	ds.b	6*M72_PL
m72r_imgb:	ds.b	6*M72_PL
m72r_bufarea:	ds.b	REN_NBUF*M72_BUFSZ+256
	section	text,code

; =====================================================================================================================
; Measurements (2026-10-13; Musashi via games/rtype/tools/render_test.py: CPU cycles + Blitter bus cycles of m72r_frame,
; the game logic apart; REN_NBUF 2; states recorded from the reference board, engine/m72board.py)
; =====================================================================================================================
; A picture for every arcade frame (the buffer's last picture 2 frames before) / every 4th arcade frame (closer to the
; picture rate the STE will manage), median (10% .. 90%):
;   R-Type stage 1 (attract 1000-1400)       668k (503k .. 825k)      every 4th: 1.04M (0.75 .. 1.64M)
;   R-Type stage 3 (attract 3400-3800)       916k (556k .. 1.68M)     every 4th: 1.68M (1.13 .. 2.49M)
;   R-Type play, many sprites (1000-1600)    939k (822k .. 1.09M)     every 4th: 1.08M (0.94 .. 1.48M)
;   Mr. HELI attract (900-1400)              809k (531k .. 986k)      every 4th: 906k (585k .. 1.51M)
;   Mr. HELI play (2000-2600)                765k (589k .. 1.22M)     every 4th: 1.21M (0.75 .. 1.67M)
;   a picture without changes                ~75k
;   the first picture / a new scene          13-16M, spread over 15-18 calls of at most ~1.5-3.5M each (the colours
;                                            from the offline scenes, engine/m72_palettes.py; the flags of changed
;                                            map rows 16 rows a call; tile conversions M72_CBUDGET a call; no picture
;                                            drawn until done: the last one stays shown); Mr. HELI's boot screen 33M
;   a mass video RAM change (stage 3 start)  2.5-10M (only the changed tiles converted, the changed rows' flags)
;   an unknown scene (no offline colours)    after M72_FALLBACK frames at rest the run-time choice: samples one
;                                            call, k-means + mapping the next (~3M), then the conversions
; Where a typical picture's cycles go (every arcade frame; the background with the sprites off (M72_NOSPR), the
; sprites = the rest: drawing, priority, conversion and the damage they leave):
;   R-Type stage 1      889k = background 456k (composition 372k: stars ~330 cells / ~85 Blitter rectangles a
;                       picture; fixed 76k) + sprites 433k (priority 108k, conversions of new pieces 82k)
;   R-Type stage 3      472k = background 418k + sprites 54k
;   R-Type play        1153k = background 434k + sprites 719k (priority 128k)
;   Mr. HELI attract    514k = background  60k + sprites 454k
;   Mr. HELI play       753k = background 228k + sprites 525k (priority 138k)
; The sprite path rebuilt (2026-10-13: generated line routines, save/restore of the background, the entry scan without
; per-entry work for empty entries, priority masks with one pointer a layer, chunky conversion), the same 20 pictures,
; per drawn 16 x 16 piece CPU + Blitter (drawing incl. the list, cache lookups and set-up; save + restore; priority;
; conversion), before -> after:
;   synthetic, 64 cached pieces, static, no priority   9.1k (5.8k draw + 2.8k restore + 0.5k test) -> 8.1k (3.5k +
;                                                       1.3k draw, 1.3k + 2.0k save/restore)
;   R-Type stage 1      16.8k -> 11.8k   picture 916k -> 787k
;   R-Type stage 3      (1.5 pieces)       picture 488k -> 469k
;   R-Type play         10.6k -> 7.2k    picture 1204k -> 966k
;   Mr. HELI attract     7.2k -> 6.8k    picture 531k -> 502k
;   Mr. HELI play       17.6k -> 9.7k    picture 787k -> 541k
; render_test medians (every arcade frame): stage 1 670k -> 624k, stage 3 840k -> 753k, R-Type play 943k -> 804k,
; Mr. HELI attract 809k -> 761k, Mr. HELI play 770k -> 542k.
; (M72_NOPRI: the sprite/tile priority off, M72_NOSPR: the sprites off, M72_STATS: rectangle counters; measuring only.)
; R-Type stage 1, where the cycles go (a typical picture, ~620k): the composition passes ~145k (Blitter ~60k: ~60 runs,
; most of them the stars' cells), finding the runs and classes ~85k, the rows' bookkeeping ~70k, sprites ~100k
; (~20 pieces: a 16 x 16 piece ~2.5k of drawing, Blitter-bound, + ~2k of finding, caching, damage), the palette
; compare ~25k, the bands, the window, the tile checks ~40k.  Mr. HELI: its 50-80 sprite pieces ~350-450k.
; Memory (the renderer, its assets and state): R-Type 1.93 MB (text 15 KB, data 836 KB: tiles 2 x 136 KB, sprites
; 528 KB; bss 1.17 MB: layer images 384 KB, buffers 288 KB, sprite cache 128 KB, conversion cache 112 KB, mask streams
; 64 KB, copies and tables), Mr. HELI 2.20 MB (tiles 2 x 272 KB).
; Every Blitter pass HOG and at most 256 bus cycles (BLIT_STATS=256: none longer, none shared).
;
; Evaluation.  The target (well under one STE frame, 160k, for typical scenes) is not reached: 0.65-0.95M a picture
; with a picture every arcade frame, 0.9-1.7M at every 4th.  What was tried and measured:
;   * the composed picture redrawn every picture (both layers through the Blitter): >= 650k for the masked merges
;     alone (4 planes x mask + OR passes), rejected;
;   * a buffer that follows one layer, cells redrawn only where the other layer contributes and moved (this file):
;     R-Type's starfield stages 0.5-0.8M (the stars move one pixel a frame against FG: ~50 cells), stage 3 with BG
;     followed ~0.9M (FG's pods and walls move against BG); a static picture ~75k;
;   * a priority plane per buffer (FG over | BG over, written with the cells) for the sprites: more composition
;     passes than it saved in every scene measured (R-Type 720k -> 907k, Mr. HELI 752k -> 965k), reverted;
;   * splitting runs by class per cell: slower on long runs, reverted.
; Further steps, by expected gain:
;   * raster bands that follow different layers: a Timer B event at a band boundary reloading the video address and
;     $ffff8265 (borders.s' BD_HUD event chain extended), so the top and bottom bands follow FG (Mr. HELI's rocks,
;     R-Type's stage 3 walls) and the middle BG: most "moved" cells go; needs Hatari verification;
;   * the stars as pixels: BG tiles of a few non-neutral pixels drawn as dots where FG is transparent (the layer image
;     holding them neutral) and erased from a per-buffer list: R-Type's stages 1/2 lose ~50 cell runs (~100k);
;   * vertical twin lines for the followed layer (Mr. HELI's FG scrolls vertically too: every FG cell is redrawn then);
;   * sprites: rows whose mask fits one word as one-word passes, the damage cells' recomposition shared with the
;     moved cells; the palette compare (~25k) with per-pen-group dirty marks from the program's palette writers.
; Known limits: video RAM written during a frame is drawn in all of its bands (MAME shows the old contents above a
; raster split; render_test counts those pixels as "mid-frame VRAM"); sprite pixels in a HUD bar's lines would map
; through the playfield's colours (never seen: a bar is only given its palette when FG covers it completely;
; render_test fails if it happens); the display flip bit (port $02 bit 2, a cocktail cabinet) is not modelled (nor in
; engine/m72.py).
