; Trojan's picture on the STE: two display rings, virtual screens that follow bg1 (the hardware scroll: the Shifter's
; address, $ffff8265 for the fine scroll), a third buffer that holds bg2.
;
; A ring is 52 word columns (832 pixels) by 304 lines.  bg1's column c is at the ring's word columns c + 2 and c + 34
; (twins: the window never wraps): the picture's pixel x shows ring pixel 32 + sx + x (sx = bg1's x scroll), the
; display window starts at word column w0 = sx / 16 with the fine scroll f = sx & 15 (21 words fetched).  Its words
; w0, w0 + 1, w0 + 19, w0 + 20 (and w0 + 18 when f = 0) are the black side bands, w0 + 2 and w0 + 18 black in part
; (their band bits cleared by the column's mask, colmask), w0 + 3 .. w0 + 17 the picture.  Lines: the picture's line y
; is ring line GUARD_T + y; above and below, guard lines take whole sprites (the palette is black there).
;
; Cells: the window's bg1 tiles in 16 slot rows (slot k's first line GUARD_T - e + 16 k, e = (sy + 8) & 15).  Each ring
; keeps per cell the key of what it shows (cell_key: the bg1 entry, its colour's epoch, the backdrop): a frame redraws
; only the cells whose key changed.  The backdrop of a cell whose tile has pen 0 pixels: one colour when the bg2
; pixels behind it are one colour (bg2_uniform), else bg2 itself at the frame's position (the key then holds bg2_gen:
; such cells are redrawn when bg2 moves against bg1).  Sprites and text drawn over a cell invalidate its key (it is
; redrawn when this ring is drawn next).
;
; bg2 (b2_base): 33 word columns by 288 lines (bg2's lines -16 .. 271: its 16 tile rows and a wrapped one at each
; end), world column wc (bg2's x / 16: image * 16 + its tilemap column) at word wc & 31, column 0 also at 32.
;
; Colours: a fixed 16-colour palette (tools/assets.py, docs/palette.json); every arcade pen maps to its nearest colour
; (pen_map); a 16-pen colour set whose mapping changes gets a new epoch (its baked tiles, sprites and characters are
; found again only with the new one).

STRIDE = 416
RING_COLS = 52
GUARD_T = 32
RING_LINES = 304
RING_SIZE = STRIDE*RING_LINES
SLOTS = 16
KEYS = SLOTS*RING_COLS
B2_STRIDE = 264
B2_LINES = 288
B2_SIZE = B2_STRIDE*B2_LINES
RING_AREA = 2*RING_SIZE+B2_SIZE+256
BLT_SRC_ADDR = $ffff8a24
BLT_DST_ADDR = $ffff8a32
KEY_BAD = -1
	ifnd TILE_ENTRIES
TILE_ENTRIES = 1024			; baked bg1 tiles (128 bytes)
	endc
	ifnd B2_ENTRIES
B2_ENTRIES = 256			; baked bg2 tiles
	endc
	ifnd SPRITE_ENTRIES
SPRITE_ENTRIES = 512			; baked sprites (row stream order)
	endc
	ifnd CHAR_ENTRIES
CHAR_ENTRIES = 512			; baked characters (8 rows of 4 plane words)
	endc

; ---------------------------------------------------------------------------------------------------------------------
init_video:
	move.l #ring_area+255,d0
	and.l #$ffffff00,d0
	move.l d0,ring_base
	add.l #RING_SIZE,d0
	move.l d0,ring_base+4
	add.l #RING_SIZE,d0
	move.l d0,b2_base
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
	lea b2_keys,a0
	moveq #31,d0
.b:	move.l d1,(a0)+
	dbf d0,.b
	bsr cache_flush
	move.b #1,bg2_gen
	move.b #0,$ffff8260.w
	move.b #2,$ffff820a.w
	move.b #(STRIDE-160)/2,$ffff820f.w
	clr.b $ffff8265.w
	lea palette_data,a0
	lea shown_pal,a1
	moveq #7,d0
.pal:	move.l (a0)+,(a1)+
	dbf d0,.pal
	; the ring's picture lines start black (the bands: colmask 1 makes every column's first state a change)
	move.l ring_base,a0
	move.w #(2*RING_SIZE+B2_SIZE)/16-1,d0
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
	move.b flip_addr+1,$ffff8201.w
	move.b flip_addr+2,$ffff8203.w
	move.b flip_addr+3,$ffff820d.w
	ifnd SIM
	; the base is loaded into the video counter before the VBL: the counter itself too (Black Tiger's render.s)
	move.b flip_addr+1,$ffff8205.w
	move.b flip_addr+2,$ffff8207.w
	move.b flip_addr+3,$ffff8209.w
	endc
	move.b flip_fine,$ffff8265.w
	move.b #(STRIDE-160)/2,d0
	tst.b flip_fine
	beq.s .width
	subq.b #4,d0
.width:	move.b d0,$ffff820f.w
	ifd SIM
	movem.l shown_pal,d0-d7
	else
	movem.l black_pal,d0-d7
	endc
	movem.l d0-d7,$ffff8240.w
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
	tst.w d0
	beq.s .r0
	lea keys1,a0
	lea colmask1,a1
.r0:	move.l a0,cur_keys
	move.l a1,cur_colmask
	lea dmg0,a0
	lea txtmap0,a1
	lea txtl0,a2
	tst.w d0
	beq.s .r1
	lea dmg1,a0
	lea txtmap1,a1
	lea txtl1,a2
.r1:	move.l a0,cur_dmg
	move.l a1,cur_txtmap
	move.l a2,cur_txtl
	addq.b #1,frame_tag
	bne.s .tag
	lea fmark,a0			; (a wrap: the marks of old frames go)
	move.w #KEYS/4-1,d0
.fm:	clr.l (a0)+
	dbf d0,.fm
	move.b #1,frame_tag
.tag:
	; the registers ($F800-$F805: what the program last wrote there)
	moveq #0,d0
	move.b Z_RAM+$F801,d0
	lsl.w #8,d0
	move.b Z_RAM+$F800,d0
	and.w #511,d0
	move.w d0,scroll_x
	moveq #0,d1
	move.b Z_RAM+$F803,d1
	lsl.w #8,d1
	move.b Z_RAM+$F802,d1
	and.w #511,d1
	move.w d1,scroll_y
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
	move.w d1,row0				; r0: the bg1 row of slot 0
	moveq #0,d0
	move.b Z_RAM+$F805,d0
	lsl.w #8,d0
	move.b Z_RAM+$F804,d0
	move.w d0,bg2_x				; X2 = image * 256 + scroll
	bsr pal_update
	bsr mapkey_update
	bsr b2_update
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
	bsr front_pass
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
; pal_update: the 64 colour sets of 16 pens ($F000: R G nibbles, $F400: B in the high nibble) against their copy;
; a set that differs is mapped again (pen_map: the STE colour of each pen), and a new mapping gets a new epoch.
pal_update:
	moveq #0,d7			; the set
	moveq #64,d0			; (the end)
	tst.b pal_written
	bne.s .go
	tst.b pal_valid
	beq.s .go
	; (no writer flagged: 4 sets a frame compared anyway)
	move.w pal_roll,d7
	addq.w #4,d7
	and.w #63,d7
	move.w d7,pal_roll
	move.w d7,d0
	addq.w #4,d0
.go:	clr.b pal_written
	move.w d0,pal_end
	lea Z_RAM+$F000,a0
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
	move.l (a0),d0
	cmp.l (a1),d0
	bne.s .map
	move.l 4(a0),d0
	cmp.l 4(a1),d0
	bne.s .map
	move.l 8(a0),d0
	cmp.l 8(a1),d0
	bne.s .map
	move.l 12(a0),d0
	cmp.l 12(a1),d0
	bne.s .map
	move.l $400(a0),d0
	cmp.l $400(a1),d0
	bne.s .map
	move.l $404(a0),d0
	cmp.l $404(a1),d0
	bne.s .map
	move.l $408(a0),d0
	cmp.l $408(a1),d0
	bne.s .map
	move.l $40c(a0),d0
	cmp.l $40c(a1),d0
	beq.s .next
.map:	moveq #0,d6			; a pen's colour changed
	moveq #15,d5
	move.l a0,a5
	move.l a1,a6
	move.l a2,d4
.pen:	moveq #0,d0
	move.b (a5),d0			; RRRRGGGG
	move.b d0,(a6)
	lsl.w #4,d0
	move.b $400(a5),d1		; BBBBxxxx
	move.b d1,$400(a6)
	lsr.b #4,d1
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
	bne.s .ep
	move.b #1,(a4,d7.w)
	bsr cache_flush
.ep:	cmp.w #8,d7
	bhs.s .next
	addq.b #1,bg2_epoch		; (a bg2 set: bg2 is drawn again)
.next:	lea 16(a0),a0
	lea 16(a1),a1
	lea 16(a2),a2
	addq.w #1,d7
	cmp.w pal_end,d7
	blo .set
	st pal_valid
.done:	rts

; cache_flush: every baked tile, sprite and character forgotten; every ring cell and bg2 column redrawn
cache_flush:
	movem.l d0-d1/a0,-(sp)
	lea cache_tags,a0
	move.w #(cache_tags_end-cache_tags)/4-1,d0
	moveq #-1,d1
.t:	move.l d1,(a0)+
	dbf d0,.t
	lea lut_tags,a0
	moveq #63,d0
.l:	move.b #0,(a0)+
	dbf d0,.l
	lea keys0,a0
	move.w #2*KEYS-1,d0
.k:	move.l d1,(a0)+
	dbf d0,.k
	lea b2_keys,a0
	moveq #31,d0
.b:	move.l d1,(a0)+
	dbf d0,.b
	movem.l (sp)+,d0-d1/a0
	rts

; ---------------------------------------------------------------------------------------------------------------------
; b2_update: bg2's world columns the frame can show ((X2 - 48) / 16 .. (X2 + 304) / 16) drawn into b2 where their
; key (the world column, bg2_epoch) differs; then u_cells: per such column (relative to the first) and slot row, the
; colour of its bg2 pixels behind the slot when they are one colour, else $FF.  bg2_gen changes when bg2 moves
; against bg1 or is drawn again.
b2_update:
	move.w bg2_x,d0
	sub.w #48,d0
	asr.w #4,d0			; (X2 < 48: a negative first column)
	move.w d0,b2_first
	moveq #0,d7			; a column was drawn again
	moveq #23-1,d6
	move.w d0,d5
.col:	move.w d5,d0
	and.w #31,d0
	add.w d0,d0
	add.w d0,d0
	lea b2_keys,a0
	moveq #0,d1
	move.b bg2_epoch,d1
	swap d1
	move.w d5,d1
	cmp.l (a0,d0.w),d1
	beq.s .ok
	move.l d1,(a0,d0.w)
	movem.l d5-d6,-(sp)
	move.w d5,d0
	bsr b2_column
	movem.l (sp)+,d5-d6
	moveq #1,d7
.ok:	addq.w #1,d5
	dbf d6,.col
	; bg2_gen: a new number when X2 against sx changed or a column was drawn
	move.w bg2_x,d0
	cmp.w last_bg2_x,d0
	beq.s .x_same
	move.w d0,last_bg2_x
	moveq #1,d7
.x_same:
	move.w scroll_x,d0
	cmp.w last_sx,d0
	beq.s .sx_same
	move.w d0,last_sx
	moveq #1,d7
.sx_same:
	move.w vphase,d0
	cmp.w last_vphase,d0
	beq.s .v_same
	move.w d0,last_vphase
	moveq #1,d7
.v_same:
	tst.w d7
	beq.s .gen_same
	addq.b #1,bg2_gen
	cmp.b #$80,bg2_gen
	blo.s .gen_same
	move.b #1,bg2_gen		; (a wrap: every key with an old number goes)
	bsr cache_flush
.gen_same:
	tst.w d7
	beq .u_done			; (nothing moved: u_cells holds)
	; u_cells[i][k] for the 23 columns from b2_first and the 16 slot rows: slot k's bg2 lines are its arcade lines
	; 16 k - e + 8 .. + 15 (tile rows t0 = that / 16, t1 = (that + 15) / 16, mod 16)
	lea u_cells,a1
	move.w b2_first,d5
	moveq #23-1,d6
.ucol:	move.w d5,d0
	and.w #31,d0
	lsl.w #4,d0
	lea b2_uni,a0
	add.w d0,a0			; the column's 16 tile rows
	moveq #8,d4
	sub.w vphase,d4			; the arcade line of slot 0 (-7 .. 8)
	moveq #SLOTS-1,d3
.urow:	move.w d4,d0
	asr.w #4,d0
	and.w #15,d0
	move.w d4,d1
	add.w #15,d1
	asr.w #4,d1
	and.w #15,d1
	move.b (a0,d0.w),d2
	cmp.b (a0,d1.w),d2
	beq.s .u1
	moveq #-1,d2
.u1:	move.b d2,(a1)+
	add.w #16,d4
	dbf d3,.urow
	addq.w #1,d5
	dbf d6,.ucol
.u_done:
	rts

; b2_column: world column d0.w (its tiles from the map ROM: tile row tr's entry at (tr * $800 + wc * 2) & $7FFF) into
; b2's column wc & 31 (and 32 for 0), lines 16 + 16 tr; tile row 15 again at lines 0-15, row 0 at 272-287.  b2_uni:
; per row the colour of a one-pen tile, else $FF.  Uses d0-d7/a0-a6.
b2_column:
	move.w d0,d7
	moveq #31,d6
	and.w d7,d6			; the b2 column
	moveq #0,d5			; the tile row
.row:	move.w d5,d0
	moveq #11,d1
	lsl.w d1,d0
	move.w d7,d1
	add.w d1,d1
	add.w d1,d0
	and.w #$7fff,d0
	lea bg2_map,a0
	moveq #0,d1
	move.b (a0,d0.w),d1		; the code's low byte
	moveq #0,d2
	move.b 1(a0,d0.w),d2		; the attribute
	btst #7,d2
	beq.s .c8
	bset #8,d1
.c8:	; the one-pen colour
	lea b2_uni,a1
	move.w d6,d0
	lsl.w #4,d0
	add.w d5,d0
	lea bg2_uniform,a2
	moveq #0,d3
	move.b (a2,d1.w),d3
	cmp.b #$ff,d3
	beq.s .nu
	moveq #7,d4
	and.w d2,d4
	lsl.w #4,d4
	add.w d4,d3
	lea pen_map,a2
	move.b (a2,d3.w),d3
.nu:	move.b d3,(a1,d0.w)
	; the baked tile: code d1, colour attr & 7, flips attr bits 4 (x), 5 (y)
	movem.l d5-d7,-(sp)
	move.w d1,d0
	move.w d2,d1
	bsr bg2_get			; -> a1
	movem.l (sp)+,d5-d7
	move.l b2_base,a0
	move.w d6,d0
	lsl.w #3,d0
	add.w d0,a0
	move.w d5,d0
	addq.w #1,d0
	mulu #16*B2_STRIDE,d0
	add.l d0,a0			; line 16 + 16 tr
	bsr.s .put
	cmp.w #15,d5
	bne.s .r0
	sub.l #16*16*B2_STRIDE,a0	; row 15 again at lines 0-15
	bsr.s .put
.r0:	tst.w d5
	bne.s .next
	add.l #16*16*B2_STRIDE,a0	; row 0 again at 272-287
	bsr.s .put
.next:	addq.w #1,d5
	cmp.w #16,d5
	blo .row
	rts
; the 16 rows (a1) at a0, and at column 32 too for column 0 (keeps a0, a1)
.put:	movem.l a0-a1,-(sp)
	moveq #15,d0
.p:	move.l (a1)+,(a0)
	move.l (a1)+,4(a0)
	tst.w d6
	bne.s .p1
	move.l -8(a1),32*8(a0)
	move.l -4(a1),32*8+4(a0)
.p1:	lea B2_STRIDE(a0),a0
	dbf d0,.p
	movem.l (sp)+,a0-a1
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
	bsr blit_go
	movem.l (sp)+,d0-d1/a0
	rts

; ---------------------------------------------------------------------------------------------------------------------
; mapkey_update: bg1_mapkey (a long per map entry, column-major as the RAM: the entry, its colour's epoch << 16, the top
; byte $FF when the tile has pen 0 pixels) for the entries the game changed (its writers set bg_written: the RAM
; against a copy, 4 entries a long) or all of them when a bg1 colour set has a new epoch.  map_version: a new number
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
	lea Z_RAM+$E800,a0
	lea bg1_shadow,a1
	add.w d7,a0
	add.w d7,a1
	moveq #0,d6			; (a change)
.cmp:	move.l (a0),d0
	cmp.l (a1),d0
	bne.s .chg
	move.l $400(a0),d0
	cmp.l $400(a1),d0
	beq.s .nx
.chg:	move.l (a0),(a1)
	move.l $400(a0),$400(a1)
	moveq #1,d6
	moveq #3,d5
.e:	bsr mk_entry
	addq.w #1,d7
	dbf d5,.e
	subq.w #4,d7
.nx:	addq.l #4,a0
	addq.l #4,a1
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
	lea Z_RAM+$E800,a0
	lea bg1_shadow,a1
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
; mk_entry: bg1_mapkey's entry d7 (keeps d5-d7/a0-a1; uses d0-d4/a2)
mk_entry:
	lea Z_RAM+$EC00,a2
	moveq #0,d1
	move.b (a2,d7.w),d1
	lsl.w #8,d1
	lea Z_RAM+$E800,a2
	move.b (a2,d7.w),d1		; the entry
	move.w d1,d2
	lsr.w #5,d2
	and.w #$700,d2
	move.b d1,d2			; the tile
	lea bg1_class,a2
	move.b (a2,d2.w),d3
	move.w d1,d0
	lsr.w #8,d0
	and.w #7,d0
	lea pal_epoch+16,a2
	moveq #0,d4
	move.b (a2,d0.w),d4
	swap d4
	move.w d1,d4
	cmp.b #1,d3
	beq.s .op
	or.l #$ff000000,d4
.op:	lea bg1_mapkey,a2
	move.w d7,d0
	add.w d0,d0
	add.w d0,d0
	move.l d4,(a2,d0.w)
	; mk_front: a group 1 entry whose tile has front pens
	moveq #0,d0
	btst #11,d1			; (attr bit 3)
	beq.s .nf
	btst #12,d1			; (attr bit 4: flip x)
	beq.s .nx
	add.w #2048,d2
.nx:	lsl.w #2,d2
	lea tr_bg1_front,a2
	tst.l (a2,d2.w)
	sne d0
.nf:	lea mk_front,a2
	move.b d0,(a2,d7.w)
	rts

; ---------------------------------------------------------------------------------------------------------------------
; cells_pass: a full pass (every slot of the window's non-black columns against its key) when anything a key holds
; may have changed since this ring's last frame (the window, the map, bg2 against bg1, a column's mask, a damage list
; that overflowed), else only the cells on this ring's damage list (what sprites and text covered, the text's old
; cells).  The list is empty afterwards (this frame's sprites and text fill it again).
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
	moveq #0,d0
	move.b bg2_gen,d0
	cmp.w 2(a0),d0
	bne.s .f
	move.w scroll_x,d0
	cmp.w 4(a0),d0
	bne.s .f
	move.w scroll_y,d0
	cmp.w 6(a0),d0
	beq.s .nf
.f:	moveq #1,d7
.nf:	move.w map_version,(a0)
	moveq #0,d0
	move.b bg2_gen,d0
	move.w d0,2(a0)
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
	; the column's pointers: a3 its map keys, a2 its ring keys, a4 its backdrop colours (u_cells, 16 a column)
	lea bg1_mapkey,a3
	move.w cell_c32,d0
	add.w d0,d0
	add.w d0,d0
	add.w d0,a3
	move.l cur_keys,a2
	move.w cell_b,d0
	add.w d0,d0
	add.w d0,d0
	add.w d0,a2
	lea u_cells,a4
	move.w cell_bx2,d0
	asr.w #4,d0
	sub.w b2_first,d0
	lsl.w #4,d0
	add.w d0,a4
	moveq #15,d4
	and.w cell_bx2,d4		; (not on a word: two bg2 columns)
	moveq #0,d5			; k
	move.w row0,d3
.slot:	move.w d3,d0
	add.w d5,d0
	and.w #31,d0
	add.w d0,d0
	add.w d0,d0
	move.l (a3,d0.w),d0
	bpl.s .key			; (opaque: the map's key)
	move.b (a4,d5.w),d1
	tst.w d4
	beq.s .one
	cmp.b 16(a4,d5.w),d1
	beq.s .one
	moveq #-1,d1
.one:	cmp.b #$ff,d1
	beq.s .bg2
	or.b #$80,d1
	bra.s .k
.bg2:	move.b bg2_gen,d1
.k:	and.l #$00ffffff,d0
	swap d1
	clr.w d1
	lsl.l #8,d1
	or.l d1,d0
.key:	cmp.l (a2),d0
	beq.s .same
	move.l d0,(a2)
	move.l d0,cell_curkey
	move.w d5,cell_k
	movem.l d3-d7/a2-a4,-(sp)
	bsr cell_key			; (cell_entry, cell_backdrop, cell_idx4)
	bsr cell_draw
	movem.l (sp)+,d3-d7/a2-a4
.same:	lea RING_COLS*4(a2),a2
	addq.w #1,d5
	cmp.w full_rows,d5
	bls.s .slot
.next:	addq.w #1,d6
	cmp.w #21,d6
	blo .col
	rts

; cell_setup: cell_b's column: cell_c32 (its bg1 column * 32), cell_bx2 (bg2's x behind its left edge)
cell_setup:
	move.w cell_b,d0
	subq.w #2,d0
	move.w d0,d1
	and.w #31,d0
	lsl.w #5,d0
	move.w d0,cell_c32
	lsl.w #4,d1
	sub.w scroll_x,d1
	add.w bg2_x,d1
	move.w d1,cell_bx2
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

; cell_key: the slot cell_b, cell_k (cell_c32, cell_bx2) -> d0.l its key; cell_entry (the code byte, the attribute in
; the high byte), cell_backdrop (the backdrop's colour, $FF: bg2 itself, $FE: none).  Uses d0-d3/a0.
cell_key:
	move.w row0,d0
	add.w cell_k,d0
	and.w #31,d0
	add.w cell_c32,d0
	add.w d0,d0
	add.w d0,d0
	move.w d0,cell_idx4
	lea bg1_mapkey,a0
	move.l (a0,d0.w),d0
	move.w d0,cell_entry
	tst.l d0
	bmi.s .back
	move.b #$fe,cell_backdrop
	rts
.back:	; the backdrop: the bg2 columns (cell_bx2 >> 4, and the next unless on a word) in u_cells
	move.w cell_bx2,d1
	asr.w #4,d1
	sub.w b2_first,d1
	lsl.w #4,d1			; (16 slot rows a column)
	add.w cell_k,d1
	lea u_cells,a0
	move.b (a0,d1.w),d2
	moveq #15,d3
	and.w cell_bx2,d3
	beq.s .one
	cmp.b 16(a0,d1.w),d2
	beq.s .one
	moveq #-1,d2
.one:	move.b d2,cell_backdrop
	cmp.b #$ff,d2
	beq.s .bg2
	or.b #$80,d2			; $80 | colour
	bra.s .k
.bg2:	move.b bg2_gen,d2		; (1-127)
.k:	and.l #$00ffffff,d0
	moveq #0,d3
	move.b d2,d3
	ror.l #8,d3
	or.l d3,d0
	rts

; cell_draw: the slot cell_b, cell_k (cell_entry, cell_tile, cell_backdrop from cell_key) into the ring.  Uses d0-d7,
; a0-a6.
cell_draw:
	ifd SIM
	addq.l #1,cnt_cells
	endc
	move.w cell_entry,d0
	move.w d0,d1
	lsr.w #5,d1
	and.w #$700,d1
	move.b d0,d1
	move.w d1,cell_tile
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
	move.w cell_tile,d0
	lea bg1_class,a0
	move.b (a0,d0.w),d2		; 0 no pixel, 1 opaque, 2 pen 0 too
	move.b cell_backdrop,d3
	cmp.b #$ff,d3
	beq .bg2
	cmp.b #1,d2
	beq .copy			; (opaque)
	tst.b d2
	bne .comp
	; no pixel: the backdrop's one colour
	and.w #15,d3
	lsl.w #3,d3
	lea colour_words,a0
	move.l (a0,d3.w),d1
	move.l 4(a0,d3.w),d2
	bsr cell_keep			; d0 = the column's kept bits (a long)
	and.l d0,d1
	and.l d0,d2
	move.l cell_addr,a0
	rept 16
	move.l d1,(a0)
	move.l d2,4(a0)
	lea STRIDE(a0),a0
	endr
	rts
.comp:	; pen 0 pixels over one colour: the composite, baked and cached like a tile
	moveq #0,d4
	move.b d3,d4
	and.w #15,d4
	addq.w #1,d4
	move.w d4,bake_comp
	bra.s .get
.copy:	clr.w bake_comp
.get:	move.w cell_idx4,d0		; (the image this map entry drew last time, when it is still in the cache)
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
.miss:	move.w cell_entry,d1
	lsr.w #8,d1
	move.w cell_tile,d0
	bsr bg1_get			; -> a1 the 16 rows
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
	bne.s .cpm
.cp:	move.l (a1)+,(a0)+
	move.l (a1)+,(a0)
	lea STRIDE-4(a0),a0
	dbf d1,.cp
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

.bg2:	; bg2 at bg2 x = cell_bx2, its lines 16 k - e + 8 (b2 line + 16)
	ifd SIM
	addq.l #1,cnt_cells_bg2
	endc
	moveq #0,d0
	move.w cell_bx2,d0
	and.w #511,d0
	moveq #15,d3
	and.w d0,d3			; s
	lsr.w #4,d0
	lsl.w #3,d0			; the word's offset
	moveq #0,d1
	move.w cell_k,d1
	lsl.w #4,d1
	add.w #24,d1
	sub.w vphase,d1
	mulu #B2_STRIDE,d1
	add.l d1,d0
	add.l b2_base,d0
	move.l cell_addr,a1
	move.w #-1,$ffff8a28.w
	move.w #-1,$ffff8a2a.w
	move.w #-1,$ffff8a2c.w
	move.w #$0203,$ffff8a3a.w	; HOP 2 (source), OP 3 (source)
	tst.w d3
	bne.s .skewed
	; on a word: the four plane words of each line, one pass
	move.l d0,BLT_SRC_ADDR.w
	move.l a1,BLT_DST_ADDR.w
	move.w #2,$ffff8a20.w
	move.w #B2_STRIDE-6,$ffff8a22.w
	move.w #2,$ffff8a2e.w
	move.w #STRIDE-6,$ffff8a30.w
	move.w #4,$ffff8a36.w
	move.w #16,$ffff8a38.w
	clr.b $ffff8a3d.w
	bsr blit_go
	bra.s .tile
.skewed:
	; a plane a pass: the word and the next, shifted left by s (skew 16 - s, FXSR)
	move.w #8,$ffff8a20.w
	move.w #B2_STRIDE-8,$ffff8a22.w
	move.w #STRIDE,$ffff8a30.w
	move.w #1,$ffff8a36.w
	moveq #16,d1
	sub.w d3,d1
	or.w #$80,d1			; FXSR
	move.b d1,$ffff8a3d.w
	moveq #3,d2
.plane:	move.l d0,BLT_SRC_ADDR.w
	move.l a1,BLT_DST_ADDR.w
	move.w #16,$ffff8a38.w
	move.b #$c0,$ffff8a3c.w		; (48 bus accesses: one piece)
	addq.l #2,d0
	addq.l #2,a1
	dbf d2,.plane
	clr.b $ffff8a3d.w
.tile:	; bg1's tile over it: its runs of rows with pixels (tools/assets.py bg1_runs)
	move.w cell_tile,d0
	lea bg1_class,a0
	tst.b (a0,d0.w)
	beq .masked
	clr.w bake_comp
	move.w cell_entry,d1
	lsr.w #8,d1
	bsr bg1_get			; d0 tile, d1 attribute -> a1 the baked rows
	move.w cell_tile,d0
	btst #12,cell_entry		; (attr bit 4: flip x)
	beq.s .nf
	add.w #2048,d0
.nf:	lsl.w #2,d0
	lea tr_bg1_runs,a0
	move.l (a0,d0.w),a0
	move.l cell_addr,a2
	bsr draw_runs
.masked:
	; the column's band bits cleared
	move.w cell_b,d0
	add.w d0,d0
	move.l cur_colmask,a0
	move.w (a0,d0.w),d0
	beq.s .done
	move.l cell_addr,a2
	bsr band_clear
.done:	rts

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

; draw_runs: the runs at a0 (tools/assets.py: the destination offset, the source offset, the mask, the rows - 1;
; -1 ends) of the baked rows a1 into a2 (four plane words a row; END1-3 the mask).  Uses d0-d2/a0.
draw_runs:
	move.w #2,$ffff8a20.w
	move.w #2,$ffff8a22.w
	move.w #2,$ffff8a2e.w
	move.w #STRIDE-6,$ffff8a30.w
	move.w #4,$ffff8a36.w
	move.w #$0203,$ffff8a3a.w
	clr.b $ffff8a3d.w
.run:	move.w (a0)+,d0
	bmi.s .done
	lea (a2,d0.w),a3
	move.l a3,BLT_DST_ADDR.w
	move.w (a0)+,d0
	lea (a1,d0.w),a3
	move.l a3,BLT_SRC_ADDR.w
	move.w (a0)+,d0
	move.w d0,$ffff8a28.w
	move.w d0,$ffff8a2a.w
	move.w d0,$ffff8a2c.w
	move.w (a0)+,d2
	addq.w #1,d2
	move.w d2,$ffff8a38.w
	moveq #4,d1			; (lines a piece: the destination is read when the mask is not whole)
	cmp.w #-1,d0
	bne.s .go
	moveq #8,d1
.go:	movem.l a0-a3,-(sp)
	bsr blit_go_lines
	movem.l (sp)+,a0-a3
	bra.s .run
.done:	rts

; band_clear: the bits d0.w cleared in the 16 lines of the four plane words at a2 (HOP 0, OP 0 under the end masks)
band_clear:
	move.l a2,BLT_DST_ADDR.w
	move.w d0,$ffff8a28.w
	move.w d0,$ffff8a2a.w
	move.w d0,$ffff8a2c.w
	move.w #2,$ffff8a2e.w
	move.w #STRIDE-6,$ffff8a30.w
	move.w #4,$ffff8a36.w
	move.w #16,$ffff8a38.w
	move.w #$0000,$ffff8a3a.w
	clr.b $ffff8a3d.w
	moveq #4,d1
	bra blit_go_lines

; ---------------------------------------------------------------------------------------------------------------------
; Sprites (the buffer the DMA copied): from the last to the first, the first on top.  Their cells' keys go (redrawn
; when this ring is drawn next); the cells with front pens are drawn again after them (front_pass).
sprite_pass:
	clr.w front_count
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
	lea tr_sprites+$17c,a3
	moveq #95,d7
.next:	moveq #0,d3
	move.b 2(a3),d3			; y
	cmp.b #$f8,d3			; (parked: the picture's line 240)
	beq .skip
	moveq #0,d1
	move.b 1(a3),d1			; the attribute
	cmp.w #$f8,d3
	bls.s .y
	sub.w #256,d3
.y:	subq.w #8,d3			; the picture's line
	cmp.w #240,d3
	bge .skip
	cmp.w #-15,d3
	blt .skip
	moveq #0,d2
	move.b 3(a3),d2
	btst #0,d1
	beq.s .x
	sub.w #256,d2
.x:	cmp.w #256,d2
	bge .skip
	cmp.w #-15,d2
	blt .skip
	moveq #0,d0
	move.b (a3),d0			; the code: attr bits 7, 5, 6 -> 10, 9, 8
	btst #6,d1
	beq.s .c8
	bset #8,d0
.c8:	btst #5,d1
	beq.s .c9
	bset #9,d0
.c9:	btst #7,d1
	beq.s .c10
	bset #10,d0
.c10:	lea sprite_blank,a0
	tst.b (a0,d0.w)
	bne .skip
	btst #4,d1
	beq.s .nf
	add.w #2048,d0			; (flip x: the mirror image)
.nf:	move.w d0,object_code
	lsr.w #1,d1
	and.w #7,d1
	move.w d1,object_colour
	add.w #32,d2
	add.w scroll_x,d2		; the ring's x
	move.w d2,object_x
	add.w #GUARD_T,d3
	move.w d3,object_y
	movem.l d7/a3,-(sp)
	bsr sprite_one
	movem.l (sp)+,d7/a3
.skip:	subq.l #4,a3
	dbf d7,.next
	bra touch_process

; sprite_one: object_code (+2048 mirrored), object_colour at object_x, object_y (ring coordinates): culled in the
; black words, clipped at their boundary (only the inner word), else whole; its cells marked.
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
	bls .cull
	cmp.w d3,d0
	bhs .cull
	clr.b clip_mode
	bra.s .draw
.two:	cmp.w d2,d0
	blo .cull			; (both words at or left of L)
	bne.s .notl
	move.b #-1,clip_mode		; across L | L + 1: the second word
	bra.s .draw
.notl:	cmp.w d3,d0
	bhs .cull
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
	bra.s .blit
.cull:	rts
.blit:
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
	mulu #TR_MASK_STRIDE,d1
	lea tr_sprite_masks,a1
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
	lea tr_sprite_streams,a0
	move.l (a0,d0.l),a0
	lea $ffff8a32.w,a4
	lea $ffff8a38.w,a5
	lea $ffff8a3c.w,a6
	jsr tr_sprite_draw
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
	mulu #TR_MASK_STRIDE,d1
	lea tr_sprite_masks,a1
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
; their keys; those with front pens (a group 1 entry whose tile has pens 7-11) go to front_list.  Uses d0-d5/a0.
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
; area_cells: the cells of columns d4 .. d4 + d5 - 1, lines d2 .. d2 + d3 - 1 (ring lines) lose their keys, and go
; to front_list when they have front pens.  Uses d0-d5/a0.
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
TOUCHES = 400

; touch_process: the cells the sprites touched (touch_list): their keys go (the ring's damage list), the text over one
; is drawn again, those with front pens go to front_list.
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
	; front pens?  mk_front of the entry: bg1 column (b - 2) & 31, row (r0 + k) & 31
	move.w d0,d3
	subq.w #2,d3
	and.w #31,d3
	lsl.w #5,d3
	move.w row0,d2
	add.w d1,d2
	and.w #31,d2
	add.w d2,d3
	lea mk_front,a0
	tst.b (a0,d3.w)
	beq.s .n
	move.w front_count,d3
	cmp.w #FRONTS,d3
	bhs.s .n
	addq.w #1,front_count
	lsl.w #2,d3
	lea front_list,a0
	move.w d0,(a0,d3.w)
	move.w d1,2(a0,d3.w)
.n:	dbf d6,.c
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
DMG_MAX = 400

FRONTS = 128

; front_pass: bg1's front pens (group 1 entries: pens 7-11) over the sprites, in the cells sprites touched; the band
; bits of a masked column stay black.
front_pass:
	move.w front_count,d7
	beq .done
	subq.w #1,d7
	lea front_list,a4
.cell:	move.w (a4)+,d0
	move.w (a4)+,d1
	move.w d0,cell_b
	move.w d1,cell_k
	movem.l d7/a4,-(sp)
	subq.w #2,d0
	and.w #31,d0
	lsl.w #5,d0
	bsr cell_setup
	bsr cell_key			; (cell_entry)
	move.w cell_entry,d0
	move.w d0,d1
	lsr.w #5,d1
	and.w #$700,d1
	move.b d0,d1
	move.w d1,cell_tile
	moveq #0,d0
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
	move.l d0,a2
	move.w cell_tile,d0
	move.w cell_entry,d1
	lsr.w #8,d1
	move.l a2,-(sp)
	bsr bg1_get
	move.l (sp)+,a2
	move.w cell_tile,d0
	btst #12,cell_entry
	beq.s .nf
	add.w #2048,d0
.nf:	lsl.w #2,d0
	lea tr_bg1_front,a0
	move.l (a0,d0.w),a0
	move.w cell_b,d0
	add.w d0,d0
	move.l cur_colmask,a3
	move.w (a3,d0.w),d0
	not.w d0
	move.w d0,front_keep		; (the bits a masked column keeps)
	bsr draw_front
	movem.l (sp)+,d7/a4
	dbf d7,.cell
.done:	rts

; draw_front: draw_runs with the masks ANDed with front_keep
draw_front:
	move.w #2,$ffff8a20.w
	move.w #2,$ffff8a22.w
	move.w #2,$ffff8a2e.w
	move.w #STRIDE-6,$ffff8a30.w
	move.w #4,$ffff8a36.w
	move.w #$0203,$ffff8a3a.w
	clr.b $ffff8a3d.w
.run:	move.w (a0)+,d0
	bmi.s .done
	lea (a2,d0.w),a3
	move.l a3,BLT_DST_ADDR.w
	move.w (a0)+,d0
	lea (a1,d0.w),a3
	move.l a3,BLT_SRC_ADDR.w
	move.w (a0)+,d0
	and.w front_keep,d0
	move.w (a0)+,d2
	tst.w d0
	beq.s .run
	move.w d0,$ffff8a28.w
	move.w d0,$ffff8a2a.w
	move.w d0,$ffff8a2c.w
	addq.w #1,d2
	move.w d2,$ffff8a38.w
	moveq #4,d1
	movem.l a0-a3,-(sp)
	bsr blit_go_lines
	movem.l (sp)+,a0-a3
	bra.s .run
.done:	rts

; ---------------------------------------------------------------------------------------------------------------------
; The text layer (rows 1-30: the picture's lines 0-239): per row a list of its characters (text_rows: x, ring line,
; code, attribute), made again for the rows whose RAM changed (the writers set fg_written: the rows against a copy) or
; all of them for a new epoch of a text colour set; text_version: a new number when one changed.  A ring keeps its
; text while its version, the scroll and the vertical phase stay and none of the cells under it was redrawn or drawn
; over (txt_dirty); else the old text's cells are redrawn (text_prepare) and the text drawn again (text_pass), shifted
; to the ring's x (32 + sx + 8 col), pen 3 transparent.
TEXT_ROW = 32*8
text_build:
	lea pal_epoch+48,a0
	move.l (a0),d0
	cmp.l tx_epochs,d0
	beq.s .ep
	move.l d0,tx_epochs
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
	lsl.w #5,d0
	lea Z_RAM+$E000,a0
	add.w d0,a0
	lea fg_shadow,a1
	add.w d0,a1
	tst.w d6
	bne.s .make
	moveq #7,d1
.c:	move.l (a0)+,d0
	cmp.l (a1)+,d0
	bne.s .chg
	move.l $400-4(a0),d0
	cmp.l $400-4(a1),d0
	bne.s .chg
	dbf d1,.c
	bra .nrow
.chg:	move.w d7,d0
	lsl.w #5,d0
	lea Z_RAM+$E000,a0
	add.w d0,a0
	lea fg_shadow,a1
	add.w d0,a1
.make:	moveq #1,d5
	moveq #7,d1
.cp:	move.l (a0)+,(a1)+
	move.l $400-4(a0),$400-4(a1)
	dbf d1,.cp
	sub.w #32,a0
	; the row's list
	lea text_rows,a2
	move.w d7,d0
	mulu #TEXT_ROW+2,d0
	add.l d0,a2
	move.l a2,a3			; (its count)
	clr.w (a2)+
	moveq #0,d4			; the column
.ch:	moveq #0,d1
	move.b $400(a0),d1		; the attribute
	moveq #0,d2
	move.b (a0)+,d2
	move.w d1,d3
	and.w #$c0,d3
	add.w d3,d3
	add.w d3,d3
	or.w d3,d2			; the code
	lea char_blank,a1
	tst.b (a1,d2.w)
	bne.s .bl
	move.w d4,d0
	lsl.w #3,d0
	move.w d0,(a2)+			; x
	move.w d7,d0
	lsl.w #3,d0
	add.w #GUARD_T-8,d0
	move.w d0,(a2)+			; the ring line
	move.w d2,(a2)+
	move.w d1,(a2)+
	addq.w #1,(a3)
.bl:	addq.w #1,d4
	cmp.w #32,d4
	blo.s .ch
.nrow:	addq.w #1,d7
	cmp.w tx_end,d7
	blo .row
	tst.w d5
	beq.s .done
	addq.w #1,text_version
.done:	rts

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
.ch:	move.w (a4)+,d0
	add.w #32,d0
	add.w scroll_x,d0
	move.w d0,object_x
	move.w (a4)+,object_y
	move.w (a4)+,d0
	move.w (a4)+,d1
	movem.l d6-d7/a4,-(sp)
	bsr char_get			; d0 code, d1 attribute -> a1 the baked rows (8 x 4 plane words)
	bsr char_draw
	; its cells (one or two columns, the slot rows of its 8 lines) into the ring's text map
	move.w object_x,d4
	lsr.w #4,d4
	moveq #1,d5
	moveq #15,d0
	and.w object_x,d0
	cmp.w #8,d0
	bls.s .one
	moveq #2,d5
.one:	move.w object_y,d2
	sub.w #GUARD_T,d2
	add.w vphase,d2
	move.w d2,d3
	addq.w #7,d3
	asr.w #4,d2			; k: the slot rows of its first and last line
	asr.w #4,d3
	move.l cur_txtmap,a0
	move.l cur_txtl,a1
.mk:	movem.w d4-d5,-(sp)
.m:	move.w d2,d0
	mulu #RING_COLS,d0
	add.w d4,d0
	tst.b (a0,d0.w)
	bne.s .nm
	st (a0,d0.w)
	move.w (a1),d1
	addq.w #1,(a1)
	add.w d1,d1
	move.w d0,2(a1,d1.w)
.nm:	addq.w #1,d4
	subq.w #1,d5
	bne.s .m
	movem.w (sp)+,d4-d5
	addq.w #1,d2
	cmp.w d3,d2
	ble.s .mk
	movem.l (sp)+,d6-d7/a4
	dbf d6,.ch
.nrow:	addq.w #1,d7
	cmp.w #31,d7
	blo .row
.done:	rts

; char_draw: the baked character a1 (8 rows: four plane words, the pixels in the high byte; at 64(a1) the rows'
; masks) at object_x, object_y: a pass a row, one word when it fits in it, else two (NFSR).
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
	cmp.w #8,d4
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

; bg1_get: tile d0.w, attribute d1 (colour bits 0-2, flip x bit 4) -> a1 its 16 rows baked (128 bytes).
; Uses d0-d7/a0-a3.
bg1_get:
	moveq #7,d6
	and.w d1,d6			; the colour
	add.w #16,d6			; (its set)
	lea pal_epoch,a0
	moveq #0,d2
	move.b (a0,d6.w),d2
	swap d2
	move.w d0,d2
	btst #4,d1
	beq.s .k
	bset #11,d2
.k:	moveq #7,d3
	and.w d1,d3
	ror.w #4,d3
	or.w d3,d2			; key: tile | flip << 11 | colour << 12 | epoch << 16 | comp << 24
	move.w bake_comp,d3
	ror.l #8,d3
	clr.w d3
	or.l d3,d2
	move.w d2,d3
	eor.w d6,d3
	move.l d2,d4
	swap d4
	mulu #37,d4
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
	movem.l d1/d3,-(sp)
	tst.b d5
	bne.s .hit
	; bake
	move.w d0,d1
	ext.l d1
	lsl.l #7,d1
	lea bg1_pixels,a0
	add.l d1,a0
	move.w d6,d0			; the set
	move.l (sp),d1
	moveq #16,d5			; rows
	moveq #8,d4			; bytes a row
	bsr entry_addr
	btst #4,d1
	sne d7
	movem.l d0/d7/a0,-(sp)
	bsr bake
	movem.l (sp)+,d0/d7/a0
	tst.w bake_comp
	beq.s .done
	bsr composite
	bra.s .done
.hit:	bsr entry_addr
.done:	addq.l #8,sp
	rts

; composite: the pen 0 pixels of the baked tile a1 (its pixels at a0, mirrored when d7.b is set) become the colour
; bake_comp - 1.  Keeps a1.  Uses d0-d6/a0/a2-a3.
composite:
	move.w bake_comp,d0
	subq.w #1,d0
	lsl.w #3,d0
	lea colour_words,a2
	movem.w (a2,d0.w),d3-d6		; (the colour's four plane words, sign-extended: the low words count)
	lea nz2,a2			; per byte: (the first pixel not 0) << 1 | (the second not 0)
	tst.b d7
	beq.s .n
	lea 256(a2),a2			; (mirrored: the bits the other way)
.n:	move.l a1,a3
	moveq #15,d2
.row:	moveq #0,d0			; the row's mask: its pixels not 0
	moveq #7,d1
	tst.b d7
	bne.s .rm
.b:	lsl.w #2,d0
	moveq #0,d6
	move.b (a0)+,d6
	or.b (a2,d6.w),d0
	dbf d1,.b
	bra.s .m
.rm:	addq.l #8,a0
.rb:	lsl.w #2,d0
	moveq #0,d6
	move.b -(a0),d6
	or.b (a2,d6.w),d0
	dbf d1,.rb
	addq.l #8,a0
.m:	move.w d0,d1
	not.w d1			; (the pen 0 pixels)
	movem.w d3-d5,-(sp)
	and.w d0,(a3)
	and.w d1,d3
	or.w d3,(a3)+
	and.w d0,(a3)
	and.w d1,d4
	or.w d4,(a3)+
	and.w d0,(a3)
	and.w d1,d5
	or.w d5,(a3)+
	move.w bake_comp,d6
	subq.w #1,d6
	lsl.w #3,d6
	move.l a2,-(sp)
	lea colour_words+6,a2
	move.w (a2,d6.w),d6
	move.l (sp)+,a2
	and.w d0,(a3)
	and.w d1,d6
	or.w d6,(a3)+
	movem.w (sp)+,d3-d5
	dbf d2,.row
	rts
; entry_addr: entry d3 -> a1 (CT_TILES, CT_B2, CT_SPRITES: 128 bytes; CT_CHARS: 80 bytes).  Keeps the rest.
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

; bg2_get: bg2 tile d0.w (0-511), attribute d1 (colour 0-2, flip x 4, flip y 5) -> a1 its 16 rows baked.
bg2_get:
	moveq #7,d6
	and.w d1,d6			; the set (0-7)
	lea pal_epoch,a0
	moveq #0,d2
	move.b (a0,d6.w),d2
	swap d2
	move.w d1,d2
	and.w #$37,d2
	ror.w #7,d2
	or.w d0,d2			; key: code | (colour, flips) << 9 | epoch << 16
	bset #31,d2			; (apart from the bg1 tiles' keys)
	move.w d2,d3
	lsr.w #3,d3
	eor.w d0,d3
	and.w #B2_ENTRIES/4-1,d3
	lea cache_tags,a0
	moveq #0,d4
	move.w #CT_B2,d4
	bsr cache_find
	beq.s .hit
	movem.l d1,-(sp)
	move.w d0,d2
	ext.l d2
	lsl.l #7,d2
	lea bg2_pixels,a0
	add.l d2,a0
	move.w d6,d0
	moveq #16,d5
	moveq #8,d4
	bsr entry_addr
	btst #4,d1
	sne d7
	btst #5,d1
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
	movem.l (sp)+,d1
	rts
.ny:	bsr bake
	movem.l (sp)+,d1
	rts
.hit:	bra entry_addr

; sprite_get: object_code (+2048 mirrored), object_colour -> a1 its rows baked in the stream's order (sprite_order).
sprite_get:
	move.w object_code,d0
	move.w object_colour,d6
	add.w #40,d6			; (the set: pens 640-767)
	lea pal_epoch,a0
	moveq #0,d2
	move.b (a0,d6.w),d2
	swap d2
	move.w object_colour,d2
	ror.w #4,d2
	or.w d0,d2
	bset #30,d2
	move.w d0,d3
	move.w object_colour,d4
	lsl.w #5,d4
	eor.w d4,d3
	move.l d2,d4
	swap d4
	mulu #37,d4
	eor.w d4,d3
	and.w #SPRITE_ENTRIES/4-1,d3
	lea cache_tags,a0
	moveq #0,d4
	move.w #CT_SPRITES,d4
	bsr cache_find
	beq.s .hit
	move.w d0,d2
	and.w #2047,d2
	ext.l d2
	lsl.l #7,d2
	lea sprite_pixels,a0
	add.l d2,a0
	move.w d6,d0
	moveq #16,d5
	moveq #8,d4
	move.w object_code,d7
	btst #11,d7
	sne d7
	move.l d3,-(sp)
	lea bake_scratch,a1
	bsr bake
	move.l (sp)+,d3
	bsr entry_addr
	move.w object_code,d0
	and.l #2047,d0			; (the mirror image: the sprite's own order)
	lsl.l #4,d0
	lea sprite_order,a0
	add.l d0,a0
	lea bake_scratch,a2
	move.l a1,a3
	moveq #15,d0
.ro:	moveq #0,d1
	move.b (a0)+,d1
	lsl.w #3,d1
	move.l (a2,d1.w),(a3)+
	move.l 4(a2,d1.w),(a3)+
	dbf d0,.ro
	rts
.hit:	bra entry_addr

; char_get: character d0.w (0-1023), attribute d1 (colour 0-3, flip x 4, flip y 5) -> a1: 8 rows of four plane words
; (the pixels in the high byte), at 64(a1) the rows' masks (pen 3 transparent).
char_get:
	moveq #15,d6
	and.w d1,d6
	move.w d6,d5
	lsr.w #2,d6
	add.w #48,d6			; the set (pens 768-831: four colours of four pens a set)
	lea pal_epoch,a0
	moveq #0,d2
	move.b (a0,d6.w),d2
	swap d2
	move.w d1,d2
	and.w #$3f,d2
	ror.w #6,d2
	or.w d0,d2
	bset #29,d2
	move.w d0,d3
	lsl.w #3,d5
	eor.w d5,d3
	and.w #CHAR_ENTRIES/4-1,d3
	lea cache_tags,a0
	moveq #0,d4
	move.w #CT_CHARS,d4
	bsr cache_find
	beq .hit
	bsr entry_addr
	movem.l d1/a1,-(sp)
	move.w d0,d2
	ext.l d2
	lsl.l #5,d2
	lea char_pixels,a0
	add.l d2,a0
	; the pens of the colour: its four pens at the set's 4 * (colour & 3)
	moveq #3,d4
	and.w d1,d4
	lsl.w #2,d4
	move.w d6,d0
	lsl.w #4,d0
	add.w d4,d0
	lea pen_map,a2
	add.w d0,a2
	lea char_pens,a3		; (the pens 0-3 of this colour, then 0)
	move.l (a2),(a3)
	clr.l 4(a3)
	clr.l 8(a3)
	clr.l 12(a3)
	bsr char_bake
	movem.l (sp)+,d1/a1
	btst #5,d1
	beq.s .ny
	; flip y: the rows and the masks reversed
	lea bake_scratch,a0
	moveq #19,d0
.cp:	move.l (a1)+,(a0)+
	dbf d0,.cp
	sub.w #80,a1
	lea bake_scratch+56,a0
	moveq #7,d0
.rv:	move.l (a0),(a1)+
	move.l 4(a0),(a1)+
	subq.l #8,a0
	dbf d0,.rv
	lea bake_scratch+78,a0
	moveq #7,d0
.rm:	move.w (a0),(a1)+
	subq.l #2,a0
	dbf d0,.rm
	sub.w #80,a1
.ny:	rts
.hit:	bra entry_addr

; char_bake: the 8 x 8 pixels at a0 (two a byte) with the pens char_pens -> a1: rows of four plane words (the high
; byte), at 64(a1) the masks (pen != 3); flip x by d1 bit 4.  Uses d0-d7/a0-a3.
char_bake:
	moveq #7,d7
	lea 64(a1),a3
.row:	moveq #0,d2			; the planes (a byte each in d2's four bytes)
	moveq #0,d3			; the mask
	moveq #3,d6			; four bytes
	btst #4,d1
	beq.s .byte
	addq.l #4,a0
.byte:	btst #4,d1
	beq.s .nx
	move.b -(a0),d0
	ror.b #4,d0			; (mirrored: the pixels of a byte swapped, the bytes backwards)
	bra.s .px
.nx:	move.b (a0)+,d0
.px:	moveq #0,d4
	move.b d0,d4
	lsr.b #4,d4			; the first pixel
	bsr.s .one
	moveq #15,d4
	and.b d0,d4
	bsr.s .one
	dbf d6,.byte
	btst #4,d1
	beq.s .st
	addq.l #4,a0
.st:	movep.l d2,0(a1)
	clr.b 1(a1)
	clr.b 3(a1)
	clr.b 5(a1)
	clr.b 7(a1)
	lsl.w #8,d3
	move.w d3,(a3)+
	addq.l #8,a1
	dbf d7,.row
	rts
.one:	add.w d3,d3
	lsl.l #1,d2
	cmp.b #3,d4
	beq.s .tr
	addq.w #1,d3
	lea char_pens,a2
	move.b (a2,d4.w),d4
	lea spread4,a2
	add.w d4,d4
	add.w d4,d4
	or.l (a2,d4.w),d2
.tr:	rts

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
colour_words:				; a colour's four plane words (two longs)
N	set 0
	rept 16
	dc.w -(N&1),-((N>>1)&1),-((N>>2)&1),-((N>>3)&1)
N	set N+1
	endr

CT_TILES = 0
CT_B2 = TILE_ENTRIES
CT_SPRITES = CT_B2+B2_ENTRIES
CT_CHARS = CT_SPRITES+SPRITE_ENTRIES

	include "sprite_code.s"
	include "bg1_runs.s"

	section data,data
palette_data: incbin "palette.bin"
nz2: incbin "nz2.bin"
rgb_map: incbin "rgb_map.bin"
bg1_class: incbin "bg1_class.bin"
bg2_uniform: incbin "bg2_uniform.bin"
bg2_map: incbin "bg2_map.bin"
sprite_blank: incbin "sprite_blank.bin"
char_blank: incbin "char_blank.bin"
sprite_order: incbin "sprite_order.bin"
	even
bg1_pixels: incbin "bg1_pixels.bin"
bg2_pixels: incbin "bg2_pixels.bin"
sprite_pixels: incbin "sprite_pixels.bin"
char_pixels: incbin "char_pixels.bin"
	section text,code

	section bss,bss
ring_base: ds.l 2
b2_base: ds.l 1
work_base: ds.l 1
flip_addr: ds.l 1
cur_keys: ds.l 1
cur_colmask: ds.l 1
cell_addr: ds.l 1
object_source: ds.l 1
ring_index: ds.w 1
ring_e: ds.w 2				; the vertical phase each ring's keys are for
scroll_x: ds.w 1
scroll_y: ds.w 1
win_w0: ds.w 1
fine: ds.w 1
vphase: ds.w 1
row0: ds.w 1
bg2_x: ds.w 1
b2_first: ds.w 1
last_bg2_x: ds.w 1
last_sx: ds.w 1
last_vphase: ds.w 1
cell_b: ds.w 1
cell_k: ds.w 1
cell_c32: ds.w 1
cell_bx2: ds.w 1
cell_entry: ds.w 1
cell_tile: ds.w 1
object_code: ds.w 1
object_colour: ds.w 1
object_x: ds.w 1
object_y: ds.w 1
clip_l: ds.w 1
clip_r: ds.w 1
front_count: ds.w 1
front_keep: ds.w 1
front_list: ds.l FRONTS
frame_ready: ds.b 1
flip_fine: ds.b 1
cols_changed: ds.b 1
txt_dirty: ds.b 1
frame_tag: ds.b 1
cell_backdrop: ds.b 1
clip_mode: ds.b 1
bg2_gen: ds.b 1
bg2_epoch: ds.b 1
pal_valid: ds.b 1
	even
shown_pal: ds.w 16
black_pal: ds.w 16
char_pens: ds.b 16
pen_map: ds.b 1024
pal_epoch: ds.b 64
lut_tags: ds.b 64
pal_shadow: ds.b $800
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
pal_roll: ds.w 1
pal_end: ds.w 1
bake_comp: ds.w 1
cnt_cells: ds.l 1
cnt_cells_bg2: ds.l 1
cnt_sprites: ds.l 1
cur_txtmap: ds.l 1
cur_txtl: ds.l 1
map_version: ds.w 1
text_version: ds.w 1
rs_state: ds.w 16			; per ring: map_version, bg2_gen, sx, sy of its last frame
tx_state: ds.w 8			; per ring: text_version, sx, sy of its text
tx_epochs: ds.l 1
mk_epochs: ds.l 2
dmg0: ds.w 2+DMG_MAX			; per ring: the count, the overflow, (k, b) bytes
dmg1: ds.w 2+DMG_MAX
txtl0: ds.w 1+KEYS			; per ring: the text's cells (count, numbers)
txtl1: ds.w 1+KEYS
txtmap0: ds.b KEYS
txtmap1: ds.b KEYS
fmark: ds.b KEYS
mk_front: ds.b 1024
bg1_shadow: ds.b $800
fg_shadow: ds.b $800
	even
bg1_mapkey: ds.l 1024
memo_key: ds.l 1024			; per map entry: the cell key, the cache tag's address, its key, the image it drew
memo_tag: ds.l 1024
memo_tkey: ds.l 1024
memo_ptr: ds.l 1024
text_rows: ds.b 31*(TEXT_ROW+2)
	even
keys0: ds.l KEYS
keys1: ds.l KEYS
b2_keys: ds.l 32
b2_uni: ds.b 32*16
u_cells: ds.b 23*16
cache_victim: ds.b (CT_CHARS+CHAR_ENTRIES)/4
	even
cache_tags: ds.l CT_CHARS+CHAR_ENTRIES
cache_tags_end:
bake_scratch: ds.b 128
cache_data: ds.b 128*CT_CHARS
char_data: ds.b 80*CHAR_ENTRIES
lut_tables: ds.b 2048*64
	section text,code
