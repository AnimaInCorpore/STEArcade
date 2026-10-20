; Double Dragon's picture on the STE (Trojan's render.s for one opaque layer): two display rings, virtual screens that
; follow the bg (the hardware scroll: the Shifter's address, $ffff8265 for the fine scroll).
;
; A ring is 52 word columns (832 pixels) by 304 lines.  The bg's column c is at the ring's word columns c + 2 and c + 34
; (twins: the window never wraps): the picture's pixel x shows ring pixel 32 + sx + x (sx = the bg's x scroll), the
; display window starts at word column w0 = sx / 16 with the fine scroll f = sx & 15 (21 words fetched).  Its words
; w0, w0 + 1, w0 + 19, w0 + 20 (and w0 + 18 when f = 0) are the black side bands, w0 + 2 and w0 + 18 black in part
; (their band bits cleared by the column's mask, colmask), w0 + 3 .. w0 + 17 the picture.  Lines: the picture's line y
; is ring line GUARD_T + y (the arcade's screen line y shows the bg's line y + 8 + sy); above and below, guard lines
; take whole sprites (the palette is black there).
;
; Cells: the window's bg tiles in 16 slot rows (slot k's first line GUARD_T - e + 16 k, e = (sy + 8) & 15).  Each ring
; keeps per cell the key of what it shows (the bg entry and its colour's epoch: every bg tile is opaque): a frame
; redraws only the cells whose key changed.  Sprites and text drawn over a cell invalidate its key (it is redrawn
; when this ring is drawn next).
;
; Colours: a fixed 16-colour palette (tools/assets.py, docs/palette.json); every arcade pen maps to its nearest colour
; (pen_map); a 16-pen set whose mapping changes gets a new epoch (its baked tiles, sprites and characters are found
; again only with the new one).  The 24 sets: 0-7 the text's (pens 0-127), 8-15 the sprites' (128-255), 16-23 the bg's.

STRIDE = 416
RING_COLS = 52
GUARD_T = 32
RING_LINES = 304
RING_SIZE = STRIDE*RING_LINES
SLOTS = 16
KEYS = SLOTS*RING_COLS
RING_AREA = 2*RING_SIZE+256
BLT_SRC_ADDR = $ffff8a24
BLT_DST_ADDR = $ffff8a32
PAL_SETS = 24
	ifnd TILE_ENTRIES
TILE_ENTRIES = 512			; baked bg tiles (128 bytes)
	endc
	ifnd SPRITE_ENTRIES
SPRITE_ENTRIES = 768			; baked sprites (row stream order)
	endc
	ifnd CHAR_ENTRIES
CHAR_ENTRIES = 256			; baked characters (8 rows of 4 plane words)
	endc
	ifnd PAIR_ENTRIES
PAIR_ENTRIES = 128			; baked pairs of neighbouring characters (the same, 16 pixels wide)
	endc

; ---------------------------------------------------------------------------------------------------------------------
init_video:
	move.l #ring_area+255,d0
	and.l #$ffffff00,d0
	move.l d0,ring_base
	add.l #RING_SIZE,d0
	move.l d0,ring_base+4
	move.l ring_base,flip_addr
	moveq #-1,d1
	lea keys0,a0
	move.w #2*KEYS-1,d0
.k:	move.l d1,(a0)+
	dbf d0,.k
	lea colmask0,a0
	move.w #2*RING_COLS-1,d0
.m:	move.w #1,(a0)+			; (1: unknown, never a desired mask)
	dbf d0,.m
	move.w #-1,ring_e
	move.w #-1,ring_e+2
	bsr cache_flush
	ifnd SIM
	move.b #0,$ffff8260.w
	move.b #2,$ffff820a.w
	move.b #(STRIDE-160)/2,$ffff820f.w
	clr.b $ffff8265.w
	endc
	lea palette_data,a0
	lea shown_pal,a1
	moveq #7,d0
.pal:	move.l (a0)+,(a1)+
	dbf d0,.pal
	move.l ring_base,a0
	move.w #(2*RING_SIZE)/16-1,d0
.clr:	clr.l (a0)+
	clr.l (a0)+
	clr.l (a0)+
	clr.l (a0)+
	dbf d0,.clr
	rts

vbl_video:
	tst.b frame_ready
	beq.s .done
	clr.b frame_ready
	ifnd SIM
	move.b flip_addr+1,$ffff8201.w
	move.b flip_addr+2,$ffff8203.w
	move.b flip_addr+3,$ffff820d.w
	; the base is loaded into the video counter before the VBL: the counter itself too (Black Tiger's render.s)
	move.b flip_addr+1,$ffff8205.w
	move.b flip_addr+2,$ffff8207.w
	move.b flip_addr+3,$ffff8209.w
	move.b flip_fine,$ffff8265.w
	move.b #(STRIDE-160)/2,d0
	tst.b flip_fine
	beq.s .width
	subq.b #4,d0
.width:	move.b d0,$ffff820f.w
	movem.l black_pal,d0-d7
	movem.l d0-d7,$ffff8240.w
	endc
.done:	rts

; ---------------------------------------------------------------------------------------------------------------------
render_frame:
	ifnd SIM
.wait:	tst.b frame_ready		; (the ring drawn last must have been shown before the other is reused)
	bne.s .wait
	endc
	eor.w #4,ring_index
	move.w ring_index,d0
	lea ring_base,a0
	move.l (a0,d0.w),work_base
	lea keys0,a0
	lea colmask0,a1
	lea dmg0,a2
	lea txtmap0,a3
	lea txtl0,a4
	tst.w d0
	beq.s .r0
	lea keys1,a0
	lea colmask1,a1
	lea dmg1,a2
	lea txtmap1,a3
	lea txtl1,a4
.r0:	move.l a0,cur_keys
	move.l a1,cur_colmask
	move.l a2,cur_dmg
	move.l a3,cur_txtmap
	move.l a4,cur_txtl
	addq.b #1,frame_tag
	bne.s .tag
	lea fmark,a0			; (a wrap: the marks of old frames go)
	move.w #KEYS/4-1,d0
.fm:	clr.l (a0)+
	dbf d0,.fm
	move.b #1,frame_tag
.tag:
	; the scroll: $3809 / $380A and bits 8 from the bank register ($3808 bits 0 and 1)
	moveq #0,d2
	move.b g_bankreg,d2
	moveq #0,d0
	move.b g_scroll_lo,d0
	btst #0,d2
	beq.s .x8
	bset #8,d0
.x8:	move.w d0,scroll_x
	moveq #0,d1
	move.b g_scroll_lo+1,d1
	btst #1,d2
	beq.s .y8
	bset #8,d1
.y8:	move.w d1,scroll_y
	move.w d0,d2
	lsr.w #4,d2
	move.w d2,win_w0
	and.w #15,d0
	move.w d0,fine
	addq.w #8,d1
	move.w d1,d2
	and.w #15,d2
	move.w d2,vphase			; e
	lsr.w #4,d1
	and.w #31,d1
	move.w d1,row0				; r0: the bg row of slot 0
	bsr pal_update
	bsr mapkey_update
	; this ring's keys hold for its vertical phase only
	move.w ring_index,d0
	lsr.w #1,d0
	lea ring_e,a0
	move.w vphase,d1
	cmp.w (a0,d0.w),d1
	beq.s .same_e
	move.w d1,(a0,d0.w)
	move.l cur_keys,a0
	moveq #-1,d1
	move.w #KEYS-1,d0
.inv:	move.l d1,(a0)+
	dbf d0,.inv
.same_e:
	bsr columns_update
	bsr text_build
	bsr text_prepare
	bsr cells_pass
	bsr sprite_pass
	bsr text_pass
	; the display: from the window's first word, GUARD_T - PIC_TOP lines above the picture
	moveq #0,d0
	move.w win_w0,d0
	lsl.w #3,d0
	add.l work_base,d0
	ifd SIM
	add.l #GUARD_T*STRIDE,d0
	else
	add.l #(GUARD_T-PIC_TOP)*STRIDE,d0
	endc
	move.l d0,flip_addr
	move.b fine+1,flip_fine
	st frame_ready
	rts

; ---------------------------------------------------------------------------------------------------------------------
; pal_update: the 24 colour sets of 16 pens ($1000: G R nibbles, $1200: B in the low nibble) against their copy; a set
; that differs is mapped again (pen_map: the STE colour of each pen), and a new mapping gets a new epoch.
pal_update:
	moveq #0,d7			; the set
	moveq #PAL_SETS,d0		; (the end)
	tst.b pal_written
	bne.s .go
	tst.b pal_valid
	beq.s .go
	; (no writer flagged: 2 sets a frame compared anyway)
	move.w pal_roll,d7
	addq.w #2,d7
	cmp.w #PAL_SETS,d7
	blo.s .roll
	moveq #0,d7
.roll:	move.w d7,pal_roll
	move.w d7,d0
	addq.w #2,d0
.go:	clr.b pal_written
	move.w d0,pal_end
	lea g_mem+$1000,a0
	lea pal_shadow,a1
	lea pen_map,a2
	move.w d7,d0
	lsl.w #4,d0
	add.w d0,a0
	add.w d0,a1
	add.w d0,a2
	lea rgb_map,a3
	lea pal_epoch,a4
.set:	tst.b pal_valid
	beq.s .map
	moveq #3,d1
	move.l a0,a5
	move.l a1,a6
.cmp:	move.l (a5)+,d0
	cmp.l (a6)+,d0
	bne.s .map
	move.l $200-4(a5),d0
	cmp.l $200-4(a6),d0
	bne.s .map
	dbf d1,.cmp
	bra .next
.map:	moveq #0,d6			; a pen's colour changed
	moveq #15,d5
	move.l a0,a5
	move.l a1,a6
	move.l a2,d4
.pen:	move.b (a5),d1			; GGGGRRRR
	move.b d1,(a6)
	moveq #15,d0
	and.b d1,d0			; R
	lsl.w #4,d0
	lsr.b #4,d1			; G
	or.b d1,d0
	lsl.w #4,d0
	move.b $200(a5),d1		; ----BBBB
	move.b d1,$200(a6)
	and.b #15,d1
	or.b d1,d0
	move.b (a3,d0.w),d0
	cmp.b (a2),d0
	beq.s .same
	moveq #1,d6
	move.b d0,(a2)
.same:	addq.l #1,a2
	addq.l #1,a5
	addq.l #1,a6
	dbf d5,.pen
	move.l d4,a2
	tst.b pal_valid
	beq.s .newep
	tst.w d6
	beq.s .next
.newep:	addq.b #1,(a4,d7.w)		; a new epoch for the set (0 is never one: a wrap flushes the caches)
	bne.s .next
	move.b #1,(a4,d7.w)
	bsr cache_flush
.next:	lea 16(a0),a0
	lea 16(a1),a1
	lea 16(a2),a2
	addq.w #1,d7
	cmp.w pal_end,d7
	blo .set
	st pal_valid
	rts

; cache_flush: every baked tile, sprite and character forgotten; every ring cell redrawn
cache_flush:
	movem.l d0-d1/a0,-(sp)
	lea cache_tags,a0
	move.w #(cache_tags_end-cache_tags)/4-1,d0
	moveq #-1,d1
.t:	move.l d1,(a0)+
	dbf d0,.t
	lea lut_tags,a0
	moveq #PAL_SETS-1,d0
.l:	move.b #0,(a0)+
	dbf d0,.l
	lea keys0,a0
	move.w #2*KEYS-1,d0
.k:	move.l d1,(a0)+
	dbf d0,.k
	movem.l (sp)+,d0-d1/a0
	rts

; ---------------------------------------------------------------------------------------------------------------------
; columns_update: the window's columns get their mask (the bits cleared: the side bands); a column that changes is
; drawn again (its keys invalid), a column that becomes black is cleared.
columns_update:
	sf cols_changed
	move.w win_w0,d7
	move.l cur_colmask,a4
	moveq #0,d6			; i
.col:	moveq #-1,d5			; the desired mask
	cmp.w #2,d6
	blo.s .have
	cmp.w #19,d6
	bhs.s .have
	moveq #0,d5
	cmp.w #2,d6
	bne.s .right
	move.w fine,d0
	moveq #-1,d5
	lsr.w d0,d5
	not.w d5			; (the first f pixels)
	and.l #$ffff,d5
	bra.s .have
.right:	cmp.w #18,d6
	bne.s .have
	move.w fine,d0
	moveq #0,d5
	move.w #$ffff,d5
	lsr.w d0,d5			; (from pixel f)
.have:	and.l #$ffff,d5
	move.w d7,d0
	add.w d6,d0			; b
	add.w d0,d0
	cmp.w (a4,d0.w),d5
	beq.s .next
	move.w (a4,d0.w),d1		; the old mask
	cmp.w #1,d1
	beq.s .redo
	cmp.w #$ffff,d1
	beq.s .redo
	cmp.w #$ffff,d5
	beq.s .redo
	move.w d5,d2
	not.w d2
	and.w d1,d2			; (old bits the new mask does not clear)
	bne.s .redo
	; (the new mask holds the old: its bits cleared in the drawn column)
	move.w d5,(a4,d0.w)
	lsr.w #1,d0
	bsr col_clear
	bra.s .next
.redo:	move.w d5,(a4,d0.w)
	st cols_changed
	lsr.w #1,d0
	bsr col_invalidate
	cmp.w #$ffff,d5
	bne.s .next
	bsr col_black
.next:	addq.w #1,d6
	cmp.w #21,d6
	blo .col
	rts

; col_invalidate: column d0.w's keys invalid in this ring (keeps d0-d7)
col_invalidate:
	movem.l d0-d1/a0,-(sp)
	move.l cur_keys,a0
	add.w d0,d0
	add.w d0,d0
	add.w d0,a0
	moveq #-1,d1
	rept SLOTS
	move.l d1,(a0)
	lea RING_COLS*4(a0),a0
	endr
	movem.l (sp)+,d0-d1/a0
	rts

; col_clear: the bits d5.w cleared in column d0.w's picture lines (CPU; keeps d0-d7)
col_clear:
	movem.l d0-d1/d5/a0,-(sp)
	move.l work_base,a0
	lsl.w #3,d0
	add.w d0,a0
	lea GUARD_T*STRIDE(a0),a0
	not.w d5
	move.w d5,d1
	swap d5
	move.w d1,d5
	move.w #240-1,d0
.l:	and.l d5,(a0)
	and.l d5,4(a0)
	lea STRIDE(a0),a0
	dbf d0,.l
	movem.l (sp)+,d0-d1/d5/a0
	rts

; col_black: column d0.w's picture lines zero (the Blitter, 240 lines of 4 words; keeps d0-d7)
col_black:
	movem.l d0-d1/a0,-(sp)
	move.l work_base,a0
	lsl.w #3,d0
	add.w d0,a0
	lea GUARD_T*STRIDE(a0),a0
	move.l a0,BLT_DST_ADDR.w
	move.w #2,$ffff8a2e.w
	move.w #STRIDE-6,$ffff8a30.w
	moveq #-1,d0
	move.w d0,$ffff8a28.w
	move.w d0,$ffff8a2a.w
	move.w d0,$ffff8a2c.w
	move.w #4,$ffff8a36.w
	move.w #240,$ffff8a38.w
	move.w #$0000,$ffff8a3a.w	; (HOP 0, OP 0: zeros)
	clr.b $ffff8a3d.w
	bsr blit_go_copy
	movem.l (sp)+,d0-d1/a0
	rts

; ---------------------------------------------------------------------------------------------------------------------
; mapkey_update: bg_mapkey (a long per map cell, column-major: col * 32 + row) = its colour's epoch << 16 | the entry
; word (the tile 0-2047, flip x << 11, flip y << 12, the colour << 13) for the RAM entries the game changed (its
; writers set bg_written: the RAM against a copy, 4 entries two longs; the RAM's order is MAME's background_scan,
; tools/assets.py bg_slot maps it) or all of them when a bg colour set has a new epoch.  map_version: a new number
; when one changed.
mapkey_update:
	lea pal_epoch+16,a0
	lea mk_epochs,a1
	move.l (a0),d0
	cmp.l (a1),d0
	bne .all
	move.l 4(a0),d0
	cmp.l 4(a1),d0
	bne .all
	move.w #1024,d5			; (the end)
	moveq #0,d7			; the entry
	tst.b bg_written
	bne.s .flag
	; (no writer flagged: 64 entries a frame compared anyway, in case a writer is missing in gen.py)
	move.w mk_roll,d7
	add.w #64,d7
	and.w #1023,d7
	move.w d7,mk_roll
	move.w d7,d5
	add.w #64,d5
.flag:	clr.b bg_written
	move.w d5,mk_end
	lea g_mem+$3000,a0
	lea bg_shadow,a1
	move.w d7,d0
	add.w d0,d0
	add.w d0,a0
	add.w d0,a1
	moveq #0,d6			; (a change)
.cmp:	move.l (a0),d0
	cmp.l (a1),d0
	bne.s .chg
	move.l 4(a0),d0
	cmp.l 4(a1),d0
	beq.s .nx
.chg:	move.l (a0),(a1)
	move.l 4(a0),4(a1)
	moveq #1,d6
	moveq #3,d5
.e:	bsr mk_entry
	addq.w #1,d7
	dbf d5,.e
	subq.w #4,d7
.nx:	addq.l #8,a0
	addq.l #8,a1
	addq.w #4,d7
	cmp.w mk_end,d7
	blo.s .cmp
	tst.w d6
	beq.s .done
	addq.w #1,map_version
.done:	rts
.all:	move.l (a0),(a1)
	move.l 4(a0),4(a1)
	clr.b bg_written
	lea g_mem+$3000,a0
	lea bg_shadow,a1
	move.w #$800/4-1,d0
.cp:	move.l (a0)+,(a1)+
	dbf d0,.cp
	moveq #0,d7
.a:	bsr mk_entry
	addq.w #1,d7
	cmp.w #1024,d7
	blo.s .a
	addq.w #1,map_version
	rts
; mk_entry: bg_mapkey of RAM entry d7 (keeps d5-d7/a0-a1; uses d0-d4/a2)
mk_entry:
	lea g_mem+$3000,a2
	move.w d7,d0
	add.w d0,d0
	moveq #0,d1
	move.b (a2,d0.w),d1		; the attribute: flip y 7, flip x 6, colour 3-5, tile bits 8-10 in 0-2
	moveq #0,d2
	move.b 1(a2,d0.w),d2
	moveq #7,d3
	and.b d1,d3
	lsl.w #8,d3
	or.w d3,d2			; the tile
	btst #6,d1
	beq.s .nx
	bset #11,d2
.nx:	btst #7,d1
	beq.s .ny
	bset #12,d2
.ny:	lsr.b #3,d1
	and.w #7,d1			; the colour
	moveq #0,d4
	lea pal_epoch+16,a2
	move.b (a2,d1.w),d4
	ror.w #3,d1
	or.w d1,d2			; (colour << 13)
	swap d4
	move.w d2,d4
	lea bg_slot,a2
	move.w d7,d0
	add.w d0,d0
	move.w (a2,d0.w),d0		; col * 32 + row
	add.w d0,d0
	add.w d0,d0
	lea bg_mapkey,a2
	move.l d4,(a2,d0.w)
	rts

; ---------------------------------------------------------------------------------------------------------------------
; cells_pass: a full pass (every slot of the window's non-black columns against its key) when anything a key holds
; may have changed since this ring's last frame (the window, the map, a column's mask, a damage list that
; overflowed), else only the cells on this ring's damage list (what sprites and text covered, the text's old cells).
; The list is empty afterwards (this frame's sprites and text fill it again).
cells_pass:
	move.w ring_index,d4
	lsr.w #1,d4			; (0 / 2: a word per ring)
	lea rs_state,a0
	add.w d4,d4
	add.w d4,d4
	add.w d4,d4
	add.w d4,a0			; (8 words a ring)
	moveq #0,d7			; full
	tst.b cols_changed
	bne.s .f
	move.l cur_dmg,a1
	tst.w 2(a1)			; (the list overflowed)
	bne.s .f
	move.w map_version,d0
	cmp.w (a0),d0
	bne.s .f
	move.w scroll_x,d0
	cmp.w 4(a0),d0
	bne.s .f
	move.w scroll_y,d0
	cmp.w 6(a0),d0
	beq.s .nf
.f:	moveq #1,d7
.nf:	move.w map_version,(a0)
	move.w scroll_x,4(a0)
	move.w scroll_y,6(a0)
	tst.w d7
	bne cells_full
; the damage list: (k << 8 | b) words
	move.l cur_dmg,a4
	move.w (a4),d7			; the count
	beq .dd
	subq.w #1,d7
	lea 4(a4),a4
.d:	moveq #0,d0
	move.b (a4)+,d0
	move.w d0,cell_k
	moveq #0,d0
	move.b (a4)+,d0
	move.w d0,cell_b
	movem.l d7/a4,-(sp)
	bsr cell_setup
	bsr cell_check
	movem.l (sp)+,d7/a4
	dbf d7,.d
.dd:	move.l cur_dmg,a4
	clr.l (a4)
	rts

cells_full:
	move.l cur_dmg,a4
	clr.l (a4)			; (every cell is checked: the list is done, the overflow too)
	; the slot rows the picture shows: 16 k - e < 240
	moveq #0,d0
	move.w vphase,d0
	add.w #239,d0
	lsr.w #4,d0
	move.w d0,full_rows		; (the last k)
	move.w win_w0,d7
	moveq #0,d6			; i
.col:	move.w d7,d0
	add.w d6,d0			; b
	move.l cur_colmask,a0
	add.w d0,d0
	cmp.w #$ffff,(a0,d0.w)
	beq .next
	lsr.w #1,d0
	move.w d0,cell_b
	bsr cell_setup
	; the column's pointers: a3 its map keys, a2 its ring keys
	lea bg_mapkey,a3
	move.w cell_c32,d0
	add.w d0,d0
	add.w d0,d0
	add.w d0,a3
	move.l cur_keys,a2
	move.w cell_b,d0
	add.w d0,d0
	add.w d0,d0
	add.w d0,a2
	moveq #0,d5			; k
	move.w row0,d3
.slot:	move.w d3,d0
	add.w d5,d0
	and.w #31,d0
	add.w d0,d0
	add.w d0,d0
	move.w d0,d1
	move.l (a3,d0.w),d0
	cmp.l (a2),d0
	beq.s .same
	move.l d0,(a2)
	move.l d0,cell_curkey
	move.w d0,cell_entry
	move.w d5,cell_k
	add.w cell_c32,d1		; (the idx4: (c32 + row) * 4; d1 = row * 4)
	add.w cell_c32,d1
	add.w cell_c32,d1
	add.w cell_c32,d1
	move.w d1,cell_idx4
	movem.l d3-d7/a2-a3,-(sp)
	bsr cell_draw
	movem.l (sp)+,d3-d7/a2-a3
.same:	lea RING_COLS*4(a2),a2
	addq.w #1,d5
	cmp.w full_rows,d5
	bls.s .slot
.next:	addq.w #1,d6
	cmp.w #21,d6
	blo .col
	rts

; cell_setup: cell_b's column: cell_c32 (its bg column * 32)
cell_setup:
	move.w cell_b,d0
	subq.w #2,d0
	and.w #31,d0
	lsl.w #5,d0
	move.w d0,cell_c32
	rts

; cell_check: the slot cell_b, cell_k against its key; drawn when it differs
cell_check:
	bsr cell_key
	move.l cur_keys,a0
	move.w cell_k,d2
	mulu #RING_COLS*4,d2
	move.w cell_b,d3
	add.w d3,d3
	add.w d3,d3
	add.w d3,d2
	cmp.l (a0,d2.w),d0
	beq.s .same
	move.l d0,(a0,d2.w)
	move.l d0,cell_curkey
	bra cell_draw
.same:	rts

; cell_key: the slot cell_b, cell_k (cell_c32) -> d0.l its key, cell_entry, cell_idx4.  Uses d0/a0.
cell_key:
	move.w row0,d0
	add.w cell_k,d0
	and.w #31,d0
	add.w cell_c32,d0
	add.w d0,d0
	add.w d0,d0
	move.w d0,cell_idx4
	lea bg_mapkey,a0
	move.l (a0,d0.w),d0
	move.w d0,cell_entry
	rts

; cell_draw: the slot cell_b, cell_k (cell_entry, cell_curkey, cell_idx4) into the ring: the tile baked (or the image
; this map cell drew last time while it is still in the cache), copied.  Uses d0-d7, a0-a6.
cell_draw:
	ifd SIM
	addq.l #1,cnt_cells
	endc
	move.w cell_k,d0
	mulu #RING_COLS,d0
	add.w cell_b,d0
	move.l cur_txtmap,a0
	tst.b (a0,d0.w)
	beq.s .nt
	st txt_dirty			; (a cell under the text: the text again)
.nt:	moveq #0,d0
	move.w cell_k,d0
	lsl.w #4,d0
	add.w #GUARD_T,d0
	sub.w vphase,d0
	mulu #STRIDE,d0
	moveq #0,d1
	move.w cell_b,d1
	lsl.w #3,d1
	add.l d1,d0
	add.l work_base,d0
	move.l d0,cell_addr
	move.w cell_idx4,d0		; (the image this map entry drew last time, when it is still in the cache)
	lea memo_key,a0
	move.l cell_curkey,d1
	cmp.l (a0,d0.w),d1
	bne.s .miss
	lea memo_tag,a0
	move.l (a0,d0.w),a2
	lea memo_tkey,a0
	move.l (a0,d0.w),d1
	cmp.l (a2),d1
	bne.s .miss
	lea memo_ptr,a0
	move.l (a0,d0.w),a1
	bra.s .have
.miss:	move.w cell_entry,d0
	bsr bg_get			; -> a1 the 16 rows
	move.w cell_idx4,d0
	lea memo_key,a0
	move.l cell_curkey,(a0,d0.w)
	lea memo_tag,a0
	move.l last_tag,(a0,d0.w)
	lea memo_tkey,a0
	move.l last_tkey,(a0,d0.w)
	lea memo_ptr,a0
	move.l a1,(a0,d0.w)
.have:
	bsr cell_keep
	move.l cell_addr,a0
	moveq #15,d1
	cmp.l #-1,d0
	bne .cpm
N	set 0				; (16 rows unrolled: the row's offset as the displacement)
	rept 16
	move.l (a1)+,N*STRIDE(a0)
	move.l (a1)+,N*STRIDE+4(a0)
N	set N+1
	endr
	rts
.cpm:	move.l (a1)+,d2			; (a masked column: its band bits left out)
	and.l d0,d2
	move.l d2,(a0)+
	move.l (a1)+,d2
	and.l d0,d2
	move.l d2,(a0)
	lea STRIDE-4(a0),a0
	dbf d1,.cpm
	rts

; cell_keep: d0.l = the bits cell_b's column keeps, in both words (not its mask).  Uses a0.
cell_keep:
	move.w cell_b,d0
	add.w d0,d0
	move.l cur_colmask,a0
	move.w (a0,d0.w),d0
	not.w d0
	move.w d0,a0
	swap d0
	move.w a0,d0
	rts

; ---------------------------------------------------------------------------------------------------------------------
; Sprites ($2800: 5 bytes an entry, MAME's draw_sprites): from the first to the last (a later one on top), each 1, 2 or
; 4 parts of 16x16.  Their cells' keys go (redrawn when this ring is drawn next).
SPR_ENTRIES = $800/5
sprite_pass:
	move.w #2,$ffff8a20.w		; (the registers every sprite shares)
	move.w #2,$ffff8a22.w
	move.w #8,$ffff8a2e.w
	move.w #$ffff,$ffff8a2a.w
	move.w #$0203,$ffff8a3a.w
	; the black words: L = w0 + 1, R = w0 + 19 (w0 + 18 when f = 0)
	move.w win_w0,d0
	addq.w #1,d0
	move.w d0,clip_l
	add.w #18,d0
	tst.w fine
	bne.s .r
	subq.w #1,d0
.r:	move.w d0,clip_r
	lea g_mem+$2800,a3
	move.w #SPR_ENTRIES-1,d7
.next:	moveq #0,d1
	move.b 1(a3),d1			; the attribute: visible 7, size 4-5, flip x 3, flip y 2, x bit 8 1, y bit 8 0
	bpl .skip
	moveq #0,d2
	move.b 4(a3),d2
	neg.w d2
	add.w #240,d2			; sx = 240 - x + (attr & 2) << 7
	btst #1,d1
	beq.s .x8
	add.w #256,d2
.x8:	moveq #0,d3
	move.b (a3),d3
	neg.w d3
	add.w #232,d3			; sy = 232 - y + (attr & 1) << 8
	btst #0,d1
	beq.s .y8
	add.w #256,d3
.y8:	moveq #0,d0
	move.b 2(a3),d0
	move.w d0,d4
	lsr.w #4,d4
	move.w d4,object_colour
	and.w #15,d0
	lsl.w #8,d0
	move.b 3(a3),d0			; which
	moveq #$30,d4
	and.b d1,d4
	lsr.b #4,d4			; the size
	move.w d4,d5
	not.w d5
	and.w d5,d0			; which & ~size
	moveq #0,d5
	btst #3,d1
	beq.s .fx
	bset #12,d5			; flip x (+4096: the mirror image)
.fx:	btst #2,d1
	beq.s .fy
	bset #13,d5			; flip y (+8192: the stream)
.fy:	move.w d5,object_flip
	add.w d4,d4
	add.w d4,d4
	add.w d4,d4			; size * 8
	lea sprite_parts,a0
	add.w d4,a0			; (order, dx, dy) * up to 4 ... (see sprite_parts)
	movem.l d7/a3,-(sp)
	move.w d0,part_which
	move.w d2,part_sx
	move.w d3,part_sy
	move.l a0,part_list
.part:	move.l part_list,a0
	move.w (a0)+,d0			; order (-1: done), dx, dy as bytes
	bmi .pdone
	move.l a0,part_list
	move.w d0,d1
	lsr.w #8,d1			; the order
	ext.w d0			; (dx, dy packed: dx in bits 4-7, dy in 0-3 as -16 or 0)
	move.w part_which,d4
	add.w d1,d4			; which + order
	move.w part_sx,d2
	btst #4,d0
	beq.s .ndx
	sub.w #16,d2
.ndx:	move.w part_sy,d3
	btst #0,d0
	beq.s .ndy
	sub.w #16,d3
.ndy:	cmp.w #240,d3
	bge .part
	cmp.w #-15,d3
	blt .part
	cmp.w #256,d2
	bge .part
	cmp.w #-15,d2
	blt .part
	and.w #4095,d4
	lea sprite_blank,a0
	tst.b (a0,d4.w)
	bne .part
	or.w object_flip,d4
	move.w d4,object_code
	add.w #32,d2
	add.w scroll_x,d2		; the ring's x
	move.w d2,object_x
	add.w #GUARD_T,d3
	move.w d3,object_y
	bsr sprite_one
	bra .part
.pdone:	movem.l (sp)+,d7/a3
.skip:	addq.l #5,a3
	dbf d7,.next
	bra touch_process

; the parts of each size: (order << 8 | dx16 << 4 | dy16) words, -1 ends (MAME: dx = dy = -16 for the first ones)
sprite_parts:
	dc.w $0000,-1,0,0		; 16x16
	dc.w $0001,$0100,-1,0		; 16x32: (0, sx, sy - 16), (1, sx, sy)
	dc.w $0010,$0200,-1,0		; 32x16: (0, sx - 16, sy), (2, sx, sy)
	dc.w $0011,$0110,$0201,$0300	; 32x32: (0, -16, -16), (1, -16, 0), (2, 0, -16), (3, 0, 0)
	dc.w -1				; (the 32x32 list's end)

; sprite_one: object_code (+4096 mirrored, +8192 flipped in y), object_colour at object_x, object_y (ring coordinates):
; culled in the black words, clipped at their boundary (only the inner word), else whole; its cells marked.
sprite_one:
	ifd SIM
	addq.l #1,cnt_sprites
	endc
	move.w object_x,d0
	move.w d0,d1
	lsr.w #4,d0			; a: its first word
	and.w #15,d1			; s
	move.w clip_l,d2
	move.w clip_r,d3
	tst.w d1
	bne.s .two
	cmp.w d2,d0
	bls sprite_cull
	cmp.w d3,d0
	bhs sprite_cull
	clr.b clip_mode
	bra.s .draw
.two:	cmp.w d2,d0
	blo sprite_cull			; (both words at or left of L)
	bne.s .notl
	move.b #-1,clip_mode		; across L | L + 1: the second word
	bra.s .draw
.notl:	cmp.w d3,d0
	bhs sprite_cull
	addq.w #1,d0
	cmp.w d3,d0
	bne.s .whole
	move.b #1,clip_mode		; across R - 1 | R: the first word
	bra.s .draw
.whole:	clr.b clip_mode
.draw:	bsr sprite_get			; -> a1 the baked rows
	move.l a1,object_source
	bsr sprite_cells
	tst.b clip_mode
	bne sprite_clipped
; sprite_blit: the whole sprite (one word a row when on a word, else two)
	moveq #0,d0
	move.w object_y,d0
	mulu #STRIDE,d0
	moveq #0,d1
	move.w object_x,d1
	and.w #$fff0,d1
	lsr.w #1,d1
	add.l d1,d0
	add.l work_base,d0
	move.l d0,BLT_DST_ADDR.w
	move.l object_source,BLT_SRC_ADDR.w
	moveq #0,d6
	move.w object_x,d6
	and.w #15,d6
	move.w d6,d1
	mulu #DD_MASK_STRIDE,d1
	lea dd_sprite_masks,a1
	add.l d1,a1
	tst.w d6
	beq.s .narrow
	or.w #$c040,d6			; (BUSY, HOG; NFSR, the skew)
	move.w #-6,$ffff8a30.w
	move.w #2,$ffff8a36.w
	bra.s .stream
.narrow:
	or.w #$c000,d6
	move.w #2,$ffff8a30.w
	move.w #1,$ffff8a36.w
.stream:
	lea $ffff8a28.w,a2
	lea $ffff8a2c.w,a3
sprite_stream:
	moveq #0,d0
	move.w object_code,d0
	lsl.l #2,d0
	lea dd_sprite_streams,a0
	move.l (a0,d0.l),a0
	lea $ffff8a32.w,a4
	lea $ffff8a38.w,a5
	lea $ffff8a3c.w,a6
	jsr dd_sprite_draw
sprite_cull:
	rts

; sprite_clipped: across the boundary of a black word: its inner word only, one word a row (X count 1).  The right
; edge (clip_mode 1): the first word, skew s, END1 = the first word's mask (the stream's high word).  The left (-1): the
; second word (+8), FXSR with source Y increment 0 (each row's word read again as the next one's first), END1 = the
; second word's mask (the stream's low word: END1 / END3 swapped).  (Black Tiger's clip_sprite.)
sprite_clipped:
	moveq #0,d0
	move.w object_y,d0
	mulu #STRIDE,d0
	moveq #0,d1
	move.w object_x,d1
	and.w #$fff0,d1
	lsr.w #1,d1
	add.l d1,d0
	add.l work_base,d0
	moveq #0,d6
	move.w object_x,d6
	and.w #15,d6
	move.w d6,d1
	mulu #DD_MASK_STRIDE,d1
	lea dd_sprite_masks,a1
	add.l d1,a1
	move.w #2,$ffff8a30.w
	move.w #1,$ffff8a36.w
	move.l object_source,BLT_SRC_ADDR.w
	tst.b clip_mode
	bmi.s .left
	move.l d0,BLT_DST_ADDR.w
	or.w #$c000,d6
	lea $ffff8a28.w,a2
	lea $ffff8a2c.w,a3
	bra sprite_stream
.left:	addq.l #8,d0
	move.l d0,BLT_DST_ADDR.w
	or.w #$c080,d6
	clr.w $ffff8a22.w
	lea $ffff8a2c.w,a2		; (END1 <- the low word)
	lea $ffff8a28.w,a3
	bsr sprite_stream
	move.w #2,$ffff8a22.w
	rts

; sprite_cells: the cells under the sprite (object_x, object_y; two word columns unless on a word, 16 lines) lose
; their keys.  Uses d0-d5/a0.
sprite_cells:
	move.w object_x,d4
	lsr.w #4,d4			; the first column
	moveq #1,d5			; columns
	moveq #15,d0
	and.w object_x,d0
	beq.s .c
	moveq #2,d5
.c:	move.w object_y,d2
	moveq #16,d3
	; (area_cells follows)
; area_cells: the cells of columns d4 .. d4 + d5 - 1, lines d2 .. d2 + d3 - 1 (ring lines) go to touch_list once a
; frame.  Uses d0-d5/a0.
area_cells:
	movem.l d6-d7/a1-a2,-(sp)
	sub.w #GUARD_T,d2
	add.w vphase,d2			; (the slot rows: (line - GUARD_T + e) / 16)
	move.w d2,d6
	add.w d3,d6
	subq.w #1,d6
	asr.w #4,d2
	asr.w #4,d6
	tst.w d2
	bpl.s .t
	moveq #0,d2
.t:	cmp.w #SLOTS-1,d6
	ble.s .b
	moveq #SLOTS-1,d6
.b:	cmp.w d2,d6
	blt .done
	move.l cur_colmask,a2
	lea fmark,a1
	move.b frame_tag,d3
.col:	move.w d4,d0
	cmp.w #RING_COLS,d0
	bhs.s .ncol
	add.w d0,d0
	cmp.w #$ffff,(a2,d0.w)		; (a black column: no cells)
	beq.s .ncol
	lsr.w #1,d0
	move.w d2,d1			; k
.row:	move.w d1,d7
	add.w d7,d7
	lea kmul52,a0
	move.w (a0,d7.w),d7
	add.w d0,d7			; the cell's number
	cmp.b (a1,d7.w),d3
	beq.s .nrow			; (touched already this frame)
	move.b d3,(a1,d7.w)
	move.w touch_n,d7
	cmp.w #TOUCHES,d7
	bhs.s .nrow
	addq.w #1,touch_n
	add.w d7,d7
	lea touch_list,a0
	move.b d1,(a0,d7.w)		; k
	move.b d0,1(a0,d7.w)		; b
.nrow:	addq.w #1,d1
	cmp.w d6,d1
	ble.s .row
.ncol:	addq.w #1,d4
	subq.w #1,d5
	bne.s .col
.done:	movem.l (sp)+,d6-d7/a1-a2
	rts
TOUCHES = 600

; touch_process: the cells the sprites touched (touch_list): their keys go (the ring's damage list), the text over one
; is drawn again.
touch_process:
	move.w touch_n,d6
	beq .done
	clr.w touch_n
	subq.w #1,d6
	lea touch_list,a4
.c:	moveq #0,d1
	move.b (a4)+,d1			; k
	moveq #0,d0
	move.b (a4)+,d0			; b
	move.w d1,d7
	add.w d7,d7
	lea kmul52,a0
	move.w (a0,d7.w),d7
	add.w d0,d7			; the number
	move.l cur_txtmap,a0
	tst.b (a0,d7.w)
	beq.s .nt
	st txt_dirty
.nt:	bsr cell_damage
	dbf d6,.c
.done:	rts

kmul52:
N	set 0
	rept SLOTS
	dc.w N*RING_COLS
N	set N+1
	endr

; cell_damage: the cell d0 = b, d1 = k (d7 = its number) loses its key in this ring; it goes to the ring's damage list
; (redrawn when the ring is drawn next).  Keeps d0-d7; uses a0.
cell_damage:
	movem.l d2/d7,-(sp)
	add.w d7,d7
	add.w d7,d7
	move.l cur_keys,a0
	moveq #-1,d2
	cmp.l (a0,d7.w),d2
	beq.s .out
	move.l d2,(a0,d7.w)
	move.l cur_dmg,a0
	move.w (a0),d2
	cmp.w #DMG_MAX,d2
	bhs.s .over
	addq.w #1,(a0)
	add.w d2,d2
	move.b d1,4(a0,d2.w)
	move.b d0,5(a0,d2.w)
.out:	movem.l (sp)+,d2/d7
	rts
.over:	st 2(a0)			; (the list is full: a full pass next time)
	bra.s .out
DMG_MAX = 500

; ---------------------------------------------------------------------------------------------------------------------
; The text layer ($1800: 32 x 32 entries of attribute and code, row-major; rows 1-30 are the picture's lines 0-239):
; per row a list of its characters (text_rows: x, ring line, code, colour), made again for the rows whose RAM changed
; (the writers set fg_written: the rows against a copy) or all of them for a new epoch of a text colour set;
; text_version: a new number when one changed.  A ring keeps its text while its version, the scroll and the vertical
; phase stay and none of the cells under it was redrawn or drawn over (txt_dirty); else the old text's cells are
; redrawn (text_prepare) and the text drawn again (text_pass), shifted to the ring's x (32 + sx + 8 col), pen 0
; transparent.
TEXT_ROW = 32*8
text_build:
	move.l a4,-(sp)
	lea pal_epoch,a0
	move.l (a0),d0
	move.l 4(a0),d1
	cmp.l tx_epochs,d0
	bne.s .new
	cmp.l tx_epochs+4,d1
	beq.s .ep
.new:	move.l d0,tx_epochs
	move.l d1,tx_epochs+4
	moveq #-1,d6			; all rows
	bra.s .rows
.ep:	moveq #0,d6
	moveq #1,d7			; the row
	moveq #31,d4			; (the end)
	tst.b fg_written
	bne.s .rows
	; (no writer flagged: one row a frame compared anyway)
	move.w tx_roll,d7
	addq.w #1,d7
	cmp.w #31,d7
	blo.s .r1
	moveq #1,d7
.r1:	move.w d7,tx_roll
	move.w d7,d4
	addq.w #1,d4
	bra.s .r2
.rows:	moveq #1,d7
	moveq #31,d4
.r2:	clr.b fg_written
	move.w d4,tx_end
	moveq #0,d5			; (a row changed)
.row:	move.w d7,d0
	lsl.w #6,d0
	lea g_mem+$1800,a0
	add.w d0,a0
	lea fg_shadow,a1
	add.w d0,a1
	tst.w d6
	bne.s .make
	moveq #15,d1
.c:	cmpm.l (a0)+,(a1)+
	dbne d1,.c
	bne.s .chg
	bra .nrow
.chg:	move.w d7,d0
	lsl.w #6,d0
	lea g_mem+$1800,a0
	add.w d0,a0
	lea fg_shadow,a1
	add.w d0,a1
.make:	moveq #1,d5
	moveq #15,d1
.cp:	move.l (a0)+,(a1)+
	dbf d1,.cp
	sub.w #64,a0
	; the row's list
	lea text_rows,a2
	move.w d7,d0
	mulu #TEXT_ROW+2,d0
	add.l d0,a2
	move.l a2,a3			; (its count)
	clr.w (a2)+
	sub.l a4,a4			; (no run)
	moveq #0,d4			; the column
.ch:	moveq #0,d1
	move.b (a0)+,d1			; the attribute: colour 5-7, code bits 8-10 in 0-2
	moveq #0,d2
	move.b (a0)+,d2
	moveq #3,d3			; (1024 characters: code bit 10 drops out, MAME's modulo)
	and.b d1,d3
	lsl.w #8,d3
	or.w d3,d2			; the code
	lea char_blank,a1
	move.b (a1,d2.w),d0
	beq.s .nrm
	bpl.s .bl			; (1: blank)
	lsr.b #5,d1			; a solid character: it joins the run before it (the same code and colour)
	move.l a4,d3
	beq.s .run
	cmp.w 4(a4),d2
	bne.s .run
	cmp.b 7(a4),d1
	bne.s .run
	addq.b #1,6(a4)			; (the run's length)
	bra.s .nx
.run:	move.l a2,a4
	bsr.s .ent
	or.w #$100,-2(a2)		; (a run of one)
	bra.s .nx
.nrm:	lsr.b #5,d1
	bsr.s .ent
.bl:	sub.l a4,a4
.nx:	addq.w #1,d4
	cmp.w #32,d4
	blo.s .ch
	bsr text_pairs
.nrow:	addq.w #1,d7
	cmp.w tx_end,d7
	blo .row
	tst.w d5
	beq.s .done
	addq.w #1,text_version
	bsr text_columns
.done:	move.l (sp)+,a4
	rts
; (an entry: x, the ring line, the code d2, the colour d1; the row's count up)
.ent:	move.w d4,d0
	lsl.w #3,d0
	move.w d0,(a2)+			; x
	move.w d7,d0
	lsl.w #3,d0
	add.w #GUARD_T-8,d0
	move.w d0,(a2)+			; the ring line
	move.w d2,(a2)+
	move.w d1,(a2)+			; the colour (a solid run: its length in the high byte)
	addq.w #1,(a3)
	rts

; text_columns (the text changed): each solid run's line word: 0 when the row above has the same run (x, code,
; colour: drawn with it), else its height in lines (8 a row it covers, down through the rows that have it too).
; Uses d0-d7/a0-a2.
text_columns:
	moveq #1,d7			; the row
.row:	lea text_rows,a2
	move.w d7,d0
	mulu #TEXT_ROW+2,d0
	add.l d0,a2
	move.w (a2)+,d1
	beq.s .nrow
	subq.w #1,d1
.e:	cmp.w #$100,6(a2)
	blo.s .ne			; (not a run)
	move.l a2,a0
	move.w d7,d3
	subq.w #1,d3
	bsr tx_same
	beq.s .above
	moveq #8,d5
	move.w d7,d3
.dn:	addq.w #1,d3
	cmp.w #31,d3
	bhs.s .h
	bsr tx_same
	bne.s .h
	addq.w #8,d5
	bra.s .dn
.h:	move.w d5,2(a2)
	bra.s .ne
.above:	clr.w 2(a2)
.ne:	addq.l #8,a2
	dbf d1,.e
.nrow:	addq.w #1,d7
	cmp.w #31,d7
	blo.s .row
	rts

; text_pairs: the row's list at a3 (its count, then the entries): two neighbouring ordinary characters of one colour
; become one entry (x, the second's code, the first's, the colour | $80; drawn as one 16-pixel image).  Uses d0-d3/a1/a2.
text_pairs:
	lea 2(a3),a1			; (read)
	move.l a1,a2			; (write)
	move.w (a3),d3
	moveq #0,d2
.l:	tst.w d3
	beq.s .done
	move.w 6(a1),d0
	cmp.w #8,d0
	bhs.s .copy			; (a solid run)
	cmp.w #2,d3
	blo.s .copy
	cmp.w 14(a1),d0
	bne.s .copy
	move.w (a1),d1
	addq.w #8,d1
	cmp.w 8(a1),d1
	bne.s .copy
	move.w (a1),(a2)+
	move.w 12(a1),(a2)+
	move.w 4(a1),(a2)+
	or.w #$80,d0
	move.w d0,(a2)+
	lea 16(a1),a1
	subq.w #2,d3
	addq.w #1,d2
	bra.s .l
.copy:	move.l (a1)+,(a2)+
	move.l (a1)+,(a2)+
	subq.w #1,d3
	addq.w #1,d2
	bra.s .l
.done:	move.w d2,(a3)
	rts

; text_prepare (before the cells): this ring's text state against now; when it differs the old text's cells lose their
; keys (cell_damage) and the text is drawn again.
text_prepare:
	sf txt_dirty
	move.w ring_index,d0
	lsl.w #1,d0			; (8 bytes a ring)
	lea tx_state,a0
	add.w d0,a0
	move.w text_version,d1
	cmp.w (a0),d1
	bne.s .new
	move.w scroll_x,d1
	cmp.w 2(a0),d1
	bne.s .new
	move.w scroll_y,d1
	cmp.w 4(a0),d1
	bne.s .new
	rts
.new:	st txt_dirty
	move.w text_version,(a0)
	move.w scroll_x,2(a0)
	move.w scroll_y,4(a0)
	move.l cur_txtl,a2
	move.w (a2)+,d6			; the old text's cells
	beq.s .none
	subq.w #1,d6
	move.l cur_txtmap,a3
.c:	move.w (a2)+,d7			; its number
	clr.b (a3,d7.w)
	moveq #0,d1
	move.w d7,d1
	divu #RING_COLS,d1
	move.l d1,d0
	swap d0				; b
	bsr cell_damage			; (d1 = k)
	dbf d6,.c
.none:	move.l cur_txtl,a2
	clr.w (a2)
	rts

text_pass:
	tst.b txt_dirty
	beq .done
	move.w #2,$ffff8a20.w
	move.w #2,$ffff8a22.w
	move.w #8,$ffff8a2e.w
	move.w #$0203,$ffff8a3a.w
	move.w #$ffff,$ffff8a2a.w
	moveq #1,d7			; the row
.row:	lea text_rows,a4
	move.w d7,d0
	mulu #TEXT_ROW+2,d0
	add.l d0,a4
	move.w (a4)+,d6
	beq .nrow
	subq.w #1,d6
	move.w d7,d2			; the row's slot rows (k of its first and last line): the text map's first index
	lsl.w #3,d2			; (k0 * RING_COLS), how many more (0 / 1)
	add.w #-8,d2
	add.w vphase,d2
	move.w d2,d3
	addq.w #7,d3
	asr.w #4,d2
	asr.w #4,d3
	sub.w d2,d3
	move.w d3,tx_nk
	mulu #RING_COLS,d2
	move.w d2,tx_k0
	move.w d7,d0			; the row's ring line
	lsl.w #3,d0
	add.w #GUARD_T-8,d0
	move.w d0,object_y
.ch:	move.w (a4)+,d0
	add.w #32,d0
	add.w scroll_x,d0
	move.w d0,object_x
	move.w (a4)+,d2			; (a pair: the second's code)
	move.w (a4)+,d0
	move.w (a4)+,d1
	movem.l d6-d7/a4,-(sp)
	cmp.w #$100,d1
	bhs.s .run
	tst.b d1
	bmi.s .pair
	bsr char_get			; d0 code, d1 colour -> a1 the baked rows (8 x 4 plane words)
	moveq #8,d2
	bsr char_draw
	moveq #8,d4
	bra.s .cells
.pair:	and.w #7,d1
	bsr pair_get
	moveq #0,d2
	bsr char_draw
	moveq #16,d4
	bra.s .cells
.run:	move.w d2,d5			; a solid run: its height (text_columns), 0: drawn with the row above
	beq.s .above
	bsr solid_fill			; -> d4 its width
	bra.s .cells
.above:	moveq #0,d4
	move.w d1,d4
	lsr.w #8,d4
	lsl.w #3,d4
	; its cells (the columns of its width, the row's slot rows) into the ring's text map
.cells:	move.w object_x,d5
	add.w d4,d5
	subq.w #1,d5
	lsr.w #4,d5
	move.w object_x,d4
	lsr.w #4,d4
	sub.w d4,d5			; (columns - 1)
	move.l cur_txtmap,a0
	move.l cur_txtl,a1
	move.w tx_k0,d2
	add.w d4,d2
	move.w tx_nk,d3
.mk:	move.w d2,d0
	move.w d5,d6
.m:	tst.b (a0,d0.w)
	bne.s .nm
	st (a0,d0.w)
	move.w (a1),d1
	addq.w #1,(a1)
	add.w d1,d1
	move.w d0,2(a1,d1.w)
.nm:	addq.w #1,d0
	dbf d6,.m
	add.w #RING_COLS,d2
	dbf d3,.mk
	movem.l (sp)+,d6-d7/a4
	dbf d6,.ch
.nrow:	addq.w #1,d7
	cmp.w #31,d7
	blo .row
.done:	rts

; tx_same: Z when text row d3's list has the entry a0 (its x, code and colour: a solid run in the same place).
; Uses d2/d4/d6/a1.
tx_same:
	lea text_rows,a1
	move.w d3,d2
	mulu #TEXT_ROW+2,d2
	add.l d2,a1
	move.w (a1)+,d6
	beq.s .no
	subq.w #1,d6
	move.w (a0),d2
	move.l 4(a0),d4
.l:	cmp.w (a1),d2
	bne.s .n
	cmp.l 4(a1),d4
	beq.s .yes
.n:	addq.l #8,a1
	dbf d6,.l
.no:	moveq #1,d2			; (Z clear)
.yes:	rts

; solid_fill: a run of solid characters (d0 the code: char_blank's $80 + its pen; d1 the colour, the run's length in
; the high byte) at object_x, object_y, d5 lines tall (8 a text row): its STE colour filled in, plane by plane (HOP all
; ones, the operation 0 or 15), in passes of at most 256 cycles (64 accesses: lines of the words plus two end reads)
; -> d4.l its width.  Uses d0-d7/a0.
solid_fill:
	move.w d5,-(sp)			; (the lines)
	moveq #0,d4
	move.w d1,d4
	lsr.w #8,d4
	lsl.w #3,d4			; the width
	and.w #7,d1
	lsl.w #4,d1
	lea char_blank,a0
	moveq #15,d3
	and.b (a0,d0.w),d3
	add.w d3,d1
	lea pen_map,a0
	move.b (a0,d1.w),d7		; the STE colour
	moveq #0,d0
	move.w object_y,d0
	mulu #STRIDE,d0
	moveq #0,d1
	move.w object_x,d1
	move.w d1,d3
	lsr.w #4,d1			; its first word
	move.w d3,d2
	add.w d4,d2
	subq.w #1,d2			; its last pixel
	move.w d2,d5
	lsr.w #4,d5
	sub.w d1,d5			; (words - 1)
	lsl.w #3,d1
	add.l d1,d0
	add.l work_base,d0
	move.l d0,a0
	and.w #15,d3
	moveq #-1,d0
	lsr.w d3,d0			; END1
	not.w d2
	and.w #15,d2
	moveq #-1,d1
	lsl.w d2,d1			; END3
	tst.w d5
	bne.s .m
	and.w d1,d0			; (one word: END1 both)
.m:	move.w d0,$ffff8a28.w
	move.w d1,$ffff8a2c.w
	move.w d5,d0
	lsl.w #3,d0
	move.w #STRIDE,d1
	sub.w d0,d1
	move.w d1,$ffff8a30.w		; (the next line's first word)
	addq.w #1,d5
	move.w d5,$ffff8a36.w
	addq.w #2,d5
	moveq #0,d2
	move.b .fill_lines(pc,d5.w),d2	; 64 / accesses per line, without DIVU
	move.w (sp)+,d3
	moveq #3,d6
.p:	move.l a0,BLT_DST_ADDR.w
	moveq #0,d0
	lsr.b #1,d7
	bcc.s .z
	moveq #15,d0
.z:	move.w d0,$ffff8a3a.w
	move.w d3,d1			; (the lines to go)
.c:	move.w d2,d0
	cmp.w d1,d0
	bls.s .n
	move.w d1,d0
.n:	move.w d0,$ffff8a38.w
	move.w #$c000,$ffff8a3c.w	; (on from where the last pass ended)
	sub.w d0,d1
	bne.s .c
	addq.l #2,a0
	dbf d6,.p
	move.w #$0203,$ffff8a3a.w
	rts
.fill_lines:
	dc.b 64
	rept 64
	dc.b 64/(REPTN+1)
	endr
	even

; pair_get: the pair d0 (the first's code), d2 (the second's), colour d1 (0-7) -> a1: as char_get's images, the
; first's pixels in the high bytes, the second's in the low ones (made from the two characters' images).
pair_get:
	move.w d2,d7
	moveq #7,d6
	and.w d1,d6			; the set
	lea pal_epoch,a0
	moveq #0,d5
	move.b (a0,d6.w),d5
	moveq #23,d4
	lsl.l d4,d5			; key: epoch << 23 | colour << 20 | first << 10 | second
	moveq #0,d4
	move.w d6,d4
	swap d4
	lsl.l #4,d4
	or.l d4,d5
	moveq #0,d4
	move.w d0,d4
	and.w #$3FF,d4
	lsl.l #8,d4
	lsl.l #2,d4
	or.l d4,d5
	move.w d7,d4
	and.w #$3FF,d4
	or.w d4,d5
	move.w d0,d3			; the set: first ^ second << 3 ^ colour << 5
	move.w d7,d4
	lsl.w #3,d4
	eor.w d4,d3
	move.w d6,d4
	lsl.w #5,d4
	eor.w d4,d3
	and.w #PAIR_ENTRIES/4-1,d3
	move.l d5,d2
	lea cache_tags,a0
	moveq #0,d4
	move.w #CT_PAIRS,d4
	bsr cache_find
	beq.s .hit
	bsr entry_addr
	move.l a1,-(sp)
	move.w d7,-(sp)
	move.w d1,-(sp)
	bsr char_get			; the first -> the pair as it is
	move.l 4(sp),a2
	moveq #80/4-1,d6
.c1:	move.l (a1)+,(a2)+
	dbf d6,.c1
	move.w (sp)+,d1
	move.w (sp)+,d0
	bsr char_get			; the second -> the low bytes, its masks the low byte
	move.l (sp)+,a2
	move.l a2,a0
	moveq #32-1,d6
.c2:	move.b (a1),1(a0)
	addq.l #2,a1
	addq.l #2,a0
	dbf d6,.c2
	moveq #8-1,d6
.c3:	move.w (a1)+,d5
	lsr.w #8,d5
	or.w d5,(a0)+
	dbf d6,.c3
	move.l a2,a1
	rts
.hit:	bra entry_addr

; char_draw: the baked character a1 (8 rows: four plane words, the pixels in the high byte; at 64(a1) the rows'
; masks) at object_x, object_y: a pass a row, one word when it fits in it (the shift at most d2: 8 a character, 0 a
; pair, its second character in the low bytes), else two (NFSR).
char_draw:
	moveq #0,d0
	move.w object_y,d0
	mulu #STRIDE,d0
	moveq #0,d1
	move.w object_x,d1
	and.w #$fff0,d1
	lsr.w #1,d1
	add.l d1,d0
	add.l work_base,d0
	move.l d0,a2			; the row's destination
	move.l a1,BLT_SRC_ADDR.w
	moveq #15,d4
	and.w object_x,d4		; s
	lea 64(a1),a3			; the masks
	moveq #7,d5
	cmp.w d2,d4
	bhi.s .two
	move.w #2,$ffff8a30.w
	move.w #1,$ffff8a36.w
	move.w d4,d6
	or.w #$c000,d6
.r1:	move.w (a3)+,d0
	lsr.w d4,d0
	beq.s .s1
	move.w d0,$ffff8a28.w
	move.l a2,BLT_DST_ADDR.w
	move.w #4,$ffff8a38.w
	move.w d6,$ffff8a3c.w
	lea STRIDE(a2),a2
	dbf d5,.r1
	rts
.s1:	add.l #8,BLT_SRC_ADDR.w		; (an empty row: its source words passed over)
	lea STRIDE(a2),a2
	dbf d5,.r1
	rts
.two:	move.w #-6,$ffff8a30.w
	move.w #2,$ffff8a36.w
	move.w d4,d6
	or.w #$c040,d6
	moveq #16,d3
	sub.w d4,d3
.r2:	move.w (a3)+,d0
	beq.s .s2
	move.w d0,d1
	lsr.w d4,d0
	lsl.w d3,d1
	move.w d0,$ffff8a28.w
	move.w d1,$ffff8a2c.w
	move.l a2,BLT_DST_ADDR.w
	move.w #4,$ffff8a38.w
	move.w d6,$ffff8a3c.w
	lea STRIDE(a2),a2
	dbf d5,.r2
	rts
.s2:	add.l #8,BLT_SRC_ADDR.w
	lea STRIDE(a2),a2
	dbf d5,.r2
	rts

; ---------------------------------------------------------------------------------------------------------------------
; The caches: 4-way sets of baked images, the key (a long) per entry.  cache_find: d2 the key, d3 the set (masked by
; the caller), a0 the tags, d4 the number of the first entry -> d3 the entry's number, Z set on a hit.  (Uses d4/d5/a0.)
cache_find:
	lsl.w #2,d3			; the set's first entry
	add.w d4,d3
	move.w d3,d4
	lsl.w #2,d4
	add.w d4,a0
	cmp.l (a0)+,d2
	beq.s .hit
	addq.w #1,d3
	cmp.l (a0)+,d2
	beq.s .hit
	addq.w #1,d3
	cmp.l (a0)+,d2
	beq.s .hit
	addq.w #1,d3
	cmp.l (a0)+,d2
	beq.s .hit
	subq.w #3,d3
	lea cache_victim,a0		; a miss: the set's ways in turn
	move.w d3,d4
	lsr.w #2,d4
	moveq #3,d5
	and.b (a0,d4.w),d5
	addq.b #1,(a0,d4.w)
	add.w d5,d3
	move.w d3,d4
	lsl.w #2,d4
	lea cache_tags,a0
	move.l d2,(a0,d4.w)
	moveq #1,d5			; (Z clear)
.hit:	rts

; bg_get: the entry word d0.w (tile 0-2047, flip x bit 11, flip y bit 12, colour bits 13-15) -> a1 its 16 rows baked
; (128 bytes).  last_tag / last_tkey: the cache tag (for cell_draw's memo).  Uses d0-d7/a0-a3.
bg_get:
	move.w d0,d1
	moveq #13,d6
	lsr.w d6,d1			; the colour
	moveq #16,d6
	add.w d1,d6			; (its set)
	lea pal_epoch,a0
	moveq #0,d2
	move.b (a0,d6.w),d2
	swap d2
	move.w d0,d2			; key: the entry | epoch << 16
	move.w d2,d3
	eor.w d6,d3
	move.l d2,d4
	swap d4
	mulu #37,d4
	eor.w d4,d3
	move.w d2,d4
	lsr.w #8,d4
	eor.w d4,d3
	and.w #TILE_ENTRIES/4-1,d3
	lea cache_tags,a0
	moveq #0,d4
	move.w #CT_TILES,d4
	bsr cache_find
	seq d5				; (a hit)
	move.l d2,last_tkey
	move.w d3,d4
	lsl.w #2,d4
	lea cache_tags,a0
	add.w d4,a0
	move.l a0,last_tag
	tst.b d5
	bne entry_addr
	; bake
	move.w d0,-(sp)
	move.w d0,d1
	and.w #$7ff,d1
	ext.l d1
	lsl.l #7,d1
	lea bg_pixels,a0
	add.l d1,a0
	move.w d6,d0			; the set
	moveq #16,d5			; rows
	moveq #8,d4			; bytes a row
	bsr entry_addr
	move.w (sp),d1
	btst #11,d1
	sne d7
	btst #12,d1
	beq.s .ny
	; flip y: bake into the scratch, then the rows in reverse
	move.l a1,-(sp)
	lea bake_scratch,a1
	bsr bake
	move.l (sp)+,a1
	lea bake_scratch+120,a0
	moveq #15,d0
.rev:	move.l (a0),(a1)+
	move.l 4(a0),(a1)+
	subq.l #8,a0
	dbf d0,.rev
	sub.w #128,a1
	addq.l #2,sp
	rts
.ny:	bsr bake
	addq.l #2,sp
	rts

; entry_addr: entry d3 -> a1 (CT_TILES, CT_SPRITES: 128 bytes; CT_CHARS, CT_PAIRS: 80 bytes).  Keeps the rest.
entry_addr:
	movem.l d3,-(sp)
	cmp.w #CT_CHARS,d3
	bhs.s .c
	and.l #$ffff,d3
	lsl.l #7,d3
	lea cache_data,a1
	add.l d3,a1
	movem.l (sp)+,d3
	rts
.c:	sub.w #CT_CHARS,d3
	and.l #$ffff,d3
	mulu #80,d3
	lea char_data,a1
	add.l d3,a1
	movem.l (sp)+,d3
	rts

; sprite_get: object_code (the sprite, +4096 mirrored; +8192 flipped in y: the same rows), object_colour -> a1 its rows
; baked in the stream's order (sprite_order).
sprite_get:
	move.w object_code,d0
	and.w #8191,d0
	move.w object_colour,d6
	addq.w #8,d6			; (the set: pens 128 + 16 colour; colours 0-15)
	lea pal_epoch,a0
	moveq #0,d2
	move.b (a0,d6.w),d2
	swap d2
	move.w d0,d2			; key: the code | mirrored << 12 | epoch << 16 | colour << 24 | 1 << 30
	moveq #0,d4
	move.w object_colour,d4
	ror.l #8,d4
	or.l d4,d2
	bset #30,d2
	move.w d0,d3
	move.w object_colour,d4
	lsl.w #7,d4
	eor.w d4,d3
	move.l d2,d4
	swap d4
	mulu #37,d4
	eor.w d4,d3
	move.w d0,d4
	lsr.w #8,d4
	eor.w d4,d3
	and.w #SPRITE_ENTRIES/4-1,d3
	lea cache_tags,a0
	moveq #0,d4
	move.w #CT_SPRITES,d4
	bsr cache_find
	beq .hit
	move.w d0,d2
	and.w #4095,d2
	ext.l d2
	lsl.l #7,d2
	lea sprite_pixels,a0
	add.l d2,a0
	move.w d6,d0
	moveq #16,d5
	moveq #8,d4
	move.w object_code,d7
	btst #12,d7
	sne d7
	move.l d3,-(sp)
	lea bake_scratch,a1
	bsr bake
	move.l (sp)+,d3
	bsr entry_addr
	move.w object_code,d0
	and.l #4095,d0			; (the mirror image: the sprite's own order)
	lsl.l #3,d0
	lea sprite_order,a0
	add.l d0,a0
	lea bake_scratch,a2
	move.l a1,a3
	moveq #7,d0
.ro:	moveq #0,d1			; (two rows a byte, the first in the high nibble)
	move.b (a0)+,d1
	move.w d1,d2
	lsr.w #4,d1
	lsl.w #3,d1
	move.l (a2,d1.w),(a3)+
	move.l 4(a2,d1.w),(a3)+
	and.w #15,d2
	lsl.w #3,d2
	move.l (a2,d2.w),(a3)+
	move.l 4(a2,d2.w),(a3)+
	dbf d0,.ro
	rts
.hit:	bra entry_addr

; char_get: character d0.w (0-1023), colour d1 (0-7: the set) -> a1: 8 rows of four plane words (the pixels in the
; high byte), at 64(a1) the rows' masks (pen 0 transparent).
char_get:
	moveq #7,d6
	and.w d1,d6			; the set
	lea pal_epoch,a0
	moveq #0,d2
	move.b (a0,d6.w),d2
	swap d2
	move.w d6,d2
	ror.w #6,d2			; (colour << 10)
	or.w d0,d2
	bset #29,d2
	move.w d0,d3
	move.w d6,d5
	lsl.w #5,d5
	eor.w d5,d3
	and.w #CHAR_ENTRIES/4-1,d3
	lea cache_tags,a0
	moveq #0,d4
	move.w #CT_CHARS,d4
	bsr cache_find
	beq .hit
	bsr entry_addr
	move.l a1,-(sp)
	move.w d0,d2
	ext.l d2
	lsl.l #5,d2
	lea char_pixels,a0
	add.l d2,a0
	move.w d6,d0
	bsr lut_get			; -> a2 the set's byte table
	lea nz2,a3
	moveq #7,d7
	lea 64(a1),a4			; the masks
.row:	moveq #0,d0			; the planes (a byte each)
	moveq #0,d3			; the mask
	moveq #3,d6
.b:	moveq #0,d1
	move.b (a0)+,d1
	lsl.w #2,d3
	or.b (a3,d1.w),d3
	add.w d1,d1
	add.w d1,d1
	lsl.l #2,d0
	or.l (a2,d1.w),d0
	dbf d6,.b
	movep.l d0,0(a1)
	clr.b 1(a1)
	clr.b 3(a1)
	clr.b 5(a1)
	clr.b 7(a1)
	lsl.w #8,d3
	move.w d3,(a4)+
	addq.l #8,a1
	dbf d7,.row
	move.l (sp)+,a1
	rts
.hit:	bra entry_addr

; bake: the pixels at a0 (d4 bytes a row: two pixels a byte, the first in the high nibble; d5 rows) with set d0's
; pens (lut: per byte value the two pixels' plane bits) -> a1 (four plane words a row); mirrored when d7.b is set.
; Keeps a1.  Uses d0-d7/a0-a3.
bake:
	movem.l a1,-(sp)
	bsr lut_get			; -> a2 the byte table (1 KB), at 1024(a2) the swapped one
	subq.w #1,d5
	tst.b d7
	bne.s .mir
.row:	moveq #0,d0
	moveq #3,d6
.b1:	moveq #0,d1
	move.b (a0)+,d1
	add.w d1,d1
	add.w d1,d1
	lsl.l #2,d0
	or.l (a2,d1.w),d0
	dbf d6,.b1
	movep.l d0,0(a1)
	moveq #0,d0
	moveq #3,d6
.b2:	moveq #0,d1
	move.b (a0)+,d1
	add.w d1,d1
	add.w d1,d1
	lsl.l #2,d0
	or.l (a2,d1.w),d0
	dbf d6,.b2
	movep.l d0,1(a1)
	addq.l #8,a1
	dbf d5,.row
	movem.l (sp)+,a1
	rts
.mir:	lea 1024(a2),a2
.mrow:	addq.l #8,a0
	move.l a0,a3
	moveq #0,d0
	moveq #3,d6
.m1:	moveq #0,d1
	move.b -(a3),d1
	add.w d1,d1
	add.w d1,d1
	lsl.l #2,d0
	or.l (a2,d1.w),d0
	dbf d6,.m1
	movep.l d0,0(a1)
	moveq #0,d0
	moveq #3,d6
.m2:	moveq #0,d1
	move.b -(a3),d1
	add.w d1,d1
	add.w d1,d1
	lsl.l #2,d0
	or.l (a2,d1.w),d0
	dbf d6,.m2
	movep.l d0,1(a1)
	addq.l #8,a1
	dbf d5,.mrow
	movem.l (sp)+,a1
	rts

; lut_get: set d0's byte tables (made again when its epoch is not the one they were made for) -> a2.
; lut[v] = the planes of pixels v >> 4, v & 15 (two bits a byte: plane 0 in the high byte, the first pixel the higher
; bit); at 1024 the same for the nibbles swapped.  Uses d0-d3/a3.
lut_get:
	movem.l d4-d7/a0-a1,-(sp)
	lea lut_tables,a2
	moveq #0,d1
	move.w d0,d1
	moveq #11,d2
	lsl.l d2,d1			; 2 KB a set
	add.l d1,a2
	lea pal_epoch,a3
	move.b (a3,d0.w),d1
	lea lut_tags,a3
	cmp.b (a3,d0.w),d1
	beq.s .ok
	move.b d1,(a3,d0.w)
	lea pen_map,a3
	lsl.w #4,d0
	add.w d0,a3			; the set's 16 pens
	move.l a2,a1
	lea spread4,a0
	moveq #0,d4			; v
.v:	moveq #15,d5
	and.w d4,d5
	moveq #0,d0
	move.b (a3,d5.w),d0
	add.w d0,d0
	add.w d0,d0
	move.l (a0,d0.w),d6		; the second pixel's planes (v & 15)
	move.w d4,d5
	lsr.w #4,d5
	moveq #0,d0
	move.b (a3,d5.w),d0
	add.w d0,d0
	add.w d0,d0
	move.l (a0,d0.w),d7		; the first's (v >> 4)
	move.l d7,d0
	add.l d0,d0
	or.l d6,d0
	move.l d0,(a1)			; lut[v]: v >> 4 first
	move.l d6,d0
	add.l d0,d0
	or.l d7,d0
	move.l d0,1024(a1)		; the mirrored lut[v]: v & 15 first
	addq.l #4,a1
	addq.w #1,d4
	cmp.w #256,d4
	blo.s .v
.ok:	movem.l (sp)+,d4-d7/a0-a1
	rts

spread4:				; a colour's plane bits, one a byte (plane 0 in the high byte)
N	set 0
	rept 16
	dc.l ((N&1)<<24)|(((N>>1)&1)<<16)|(((N>>2)&1)<<8)|((N>>3)&1)
N	set N+1
	endr

CT_TILES = 0
CT_SPRITES = TILE_ENTRIES
CT_CHARS = CT_SPRITES+SPRITE_ENTRIES
CT_PAIRS = CT_CHARS+CHAR_ENTRIES

	include "sprite_code.s"

	section data,data
palette_data: incbin "palette.bin"
nz2: incbin "nz2.bin"
rgb_map: incbin "rgb_map.bin"
sprite_blank: incbin "sprite_blank.bin"
char_blank: incbin "char_blank.bin"
sprite_order: incbin "sprite_order.bin"
	even
bg_slot: incbin "bg_slot.bin"
bg_pixels: incbin "bg_pixels.bin"
sprite_pixels: incbin "sprite_pixels.bin"
char_pixels: incbin "char_pixels.bin"
	section text,code

	section bss,bss
ring_base: ds.l 2
work_base: ds.l 1
flip_addr: ds.l 1
cur_keys: ds.l 1
cur_colmask: ds.l 1
cell_addr: ds.l 1
object_source: ds.l 1
part_list: ds.l 1
ring_index: ds.w 1
ring_e: ds.w 2				; the vertical phase each ring's keys are for
scroll_x: ds.w 1
scroll_y: ds.w 1
win_w0: ds.w 1
fine: ds.w 1
vphase: ds.w 1
row0: ds.w 1
cell_b: ds.w 1
cell_k: ds.w 1
cell_c32: ds.w 1
cell_entry: ds.w 1
object_code: ds.w 1
object_colour: ds.w 1
object_flip: ds.w 1
object_x: ds.w 1
object_y: ds.w 1
part_which: ds.w 1
part_sx: ds.w 1
part_sy: ds.w 1
clip_l: ds.w 1
clip_r: ds.w 1
frame_ready: ds.b 1
flip_fine: ds.b 1
cols_changed: ds.b 1
txt_dirty: ds.b 1
frame_tag: ds.b 1
clip_mode: ds.b 1
pal_valid: ds.b 1
	even
shown_pal: ds.w 16
black_pal: ds.w 16
pen_map: ds.b 16*PAL_SETS
pal_epoch: ds.b 32
lut_tags: ds.b 32
pal_shadow: ds.b $400
colmask0: ds.w RING_COLS
colmask1: ds.w RING_COLS
cur_dmg: ds.l 1
cell_curkey: ds.l 1
last_tag: ds.l 1
last_tkey: ds.l 1
cell_idx4: ds.w 1
touch_n: ds.w 1
touch_list: ds.w TOUCHES
full_rows: ds.w 1
mk_roll: ds.w 1
mk_end: ds.w 1
tx_roll: ds.w 1
tx_end: ds.w 1
tx_k0: ds.w 1				; (text_pass: the row's first text map index, its slot rows - 1)
tx_nk: ds.w 1
pal_roll: ds.w 1
pal_end: ds.w 1
cnt_cells: ds.l 1
cnt_sprites: ds.l 1
cur_txtmap: ds.l 1
cur_txtl: ds.l 1
map_version: ds.w 1
text_version: ds.w 1
rs_state: ds.w 16			; per ring: map_version, -, sx, sy of its last frame
tx_state: ds.w 8			; per ring: text_version, sx, sy of its text
tx_epochs: ds.l 2
mk_epochs: ds.l 2
dmg0: ds.w 2+DMG_MAX			; per ring: the count, the overflow, (k, b) bytes
dmg1: ds.w 2+DMG_MAX
txtl0: ds.w 1+KEYS			; per ring: the text's cells (count, numbers)
txtl1: ds.w 1+KEYS
txtmap0: ds.b KEYS
txtmap1: ds.b KEYS
fmark: ds.b KEYS
bg_shadow: ds.b $800
fg_shadow: ds.b $800
	even
bg_mapkey: ds.l 1024
memo_key: ds.l 1024			; per map cell: the cell key, the cache tag's address, its key, the image it drew
memo_tag: ds.l 1024
memo_tkey: ds.l 1024
memo_ptr: ds.l 1024
text_rows: ds.b 31*(TEXT_ROW+2)
	even
keys0: ds.l KEYS
keys1: ds.l KEYS
cache_victim: ds.b (CT_PAIRS+PAIR_ENTRIES)/4
	even
cache_tags: ds.l CT_PAIRS+PAIR_ENTRIES
cache_tags_end:
bake_scratch: ds.b 128
cache_data: ds.b 128*CT_CHARS
char_data: ds.b 80*(CHAR_ENTRIES+PAIR_ENTRIES)	; (the pairs after the characters)
lut_tables: ds.b 2048*PAL_SETS
	section text,code
