; 1943 renderer.  The screen is the arcade raster rotated (ROT270): 224 x 256, screen x = raw y - 16, screen y = 255 -
; raw x.  Both layers scroll along the screen's vertical axis (raw x), at different speeds (the back layer, the sea, at
; half the speed of the front: clouds, islands, ships); the front layer also scrolls horizontally in a few stages.
;
; Three display rings are virtual screens scrolled by the video address (as in the Commando port): ring line l and
; l+RING_H always hold the same picture of the BACK layer (twin lines), so the band the window shows (256 lines, 32
; guard lines above and below for whole objects) is contiguous wherever it is.  The back layer's lines are drawn once,
; when they scroll into the band (all copies of the line).  Everything else is drawn every frame into the band and
; noted in the ring's damage list, which the next visit of that ring copies back from the twin lines:
;   1. the sprites of colours 10 and 11 (behind the front layer, tools/video.py), the last entry first
;   2. the front layer's tiles: whole 32 x 32 tiles, baked with their runs of lines of equal opaque masks (one Blitter
;      call per run and plane, the masks shifted to the horizontal scroll), the blank ones skipped
;   3. the other sprites, the last entry first (the generated Blitter routines of games/1942/tools/spritegen.py)
;   4. the characters (a list of the visible non-blank cells, rebuilt when the character RAM changes; movep.l)
; What a front tile or a sprite draws beside the 224 pixels of the window (the 48 pixel margins show) is cleared.
STRIDE = 256
GAME_X = 24				; the window's first chunk in a line (the display shows 3 chunks of margin each side)
RING_H = 320
RING_ABOVE = 32
RING_LINES = RING_ABOVE+2*RING_H+32
RING_SIZE = RING_LINES*STRIDE
DMG_MAX = 700				; damage rectangles a frame (12 bytes: destination, source, words, lines)
NFSR = $40
BLT_SRC_XINC = $ffff8a20
BLT_SRC_YINC = $ffff8a22
BLT_SRC_ADDR = $ffff8a24
BLT_END1 = $ffff8a28
BLT_END2 = $ffff8a2a
BLT_END3 = $ffff8a2c
BLT_DST_XINC = $ffff8a2e
BLT_DST_YINC = $ffff8a30
BLT_DST_ADDR = $ffff8a32
BLT_COUNT = $ffff8a36
BLT_HOP_OP = $ffff8a3a
BLT_CTRL = $ffff8a3c
BLT_SKEW = $ffff8a3d
; the Z80's video latches (in the block: address a at G_Z80 + a - $10000)
Z_CHR = G_Z80+$d000-$10000
Z_SCROLL = G_Z80+$d800-$10000

	ifd SIM
wait_b	macro
	endm
	else
wait_b	macro
.a\@:	tst.b	border_a
	bne.s	.a\@
	cmp.b	#6,$fffffa21.w
	bhi.s	.d\@
	tst.b	border_b
	bne.s	.a\@
.d\@:
	endm
	endc

 section text,code
init_video:
 move.l #screen_area+255,d0
 clr.b d0
 add.l #RING_ABOVE*STRIDE,d0
 lea ring_base,a0
 moveq #2,d1
.rings:
 move.l d0,(a0)+
 add.l #RING_SIZE,d0
 dbf d1,.rings
 move.b #(STRIDE-160)/2,$ffff820f.w
 clr.b $ffff8265.w
 move.l ring_base,d0
 sub.l #PIC_TOP*STRIDE,d0
 bsr show_address
 movem.l ste_pal,d0-d7
 movem.l d0-d7,shown_pal
 lea screen_area,a0
 move.l #(3*RING_SIZE+256)/16-1,d0
.clear:
 clr.l (a0)+
 clr.l (a0)+
 clr.l (a0)+
 clr.l (a0)+
 subq.l #1,d0
 bpl.s .clear
 clr.l ring_valid
 lea ring_dmg,a0
 move.l a0,ring_dmg_end
 lea DMG_MAX*12(a0),a0
 move.l a0,ring_dmg_end+4
 lea DMG_MAX*12(a0),a0
 move.l a0,ring_dmg_end+8
 lea chr_offsets,a0		; cell: column c = cell / 32 (x = 8c - 16), row r = cell & 31 (y = 248 - 8r)
 moveq #0,d0
.offset:
 move.w d0,d1
 and.w #31,d1
 lsl.w #3,d1
 neg.w d1
 add.w #248,d1
 mulu #STRIDE,d1
 move.w d0,d2
 lsr.w #5,d2
 subq.w #2,d2
 move.w d2,d3
 asr.w #1,d2
 lsl.w #3,d2
 ext.l d2
 add.l d2,d1
 and.w #1,d3
 add.w d3,d1
 add.l #GAME_X,d1
 move.l d1,(a0)+
 addq.w #1,d0
 cmp.w #1024,d0
 blo.s .offset
 st chr_full
 bsr cache_clear
 move.w #0,shown_idx
 move.w #1,prev_idx
 rts
show_address:
 move.l d0,-(sp)
 move.b 1(sp),$ffff8201.w
 move.b 2(sp),$ffff8203.w
 move.b 3(sp),$ffff820d.w
 addq.l #4,sp
 rts
vbl_video:
 movem.l d0-d1,-(sp)
 move.w shown_idx,prev_idx
 moveq #0,d1
 move.b frame_ready,d1
 beq .out
 clr.b frame_ready
 subq.w #1,d1
 move.w d1,shown_idx
 move.l flip_addr,d0
 bsr show_address
.out:
 movem.l (sp)+,d0-d1
 rts

; One frame into a ring that is not shown, not waiting to be shown and was not shown until the last VBL (Hatari
; scans that one out once more).  The finished ring is published with one store (frame_ready = ring + 1).
render_frame:
.snapshot:
 move.w shown_idx,d1
 move.w prev_idx,d2
 moveq #0,d3
 move.b frame_ready,d3
 cmp.w shown_idx,d1
 bne .snapshot
 subq.w #1,d3
 moveq #0,d0
.pick:
 cmp.w d1,d0
 beq .next
 cmp.w d2,d0
 beq .next
 cmp.w d3,d0
 bne .chosen
.next:
 addq.w #1,d0
 cmp.w #3,d0
 blo .pick
 st frame_dirty			; (no ring free: the next idle point draws)
 rts
.chosen:
 move.w d0,draw_idx
 bsr ring_update
 move.b g_layers,d0
 btst #6,d0
 beq.s .no_sprites1
 st spr_pass
 bsr draw_sprites		; (colours 10 and 11: behind the front layer)
.no_sprites1:
 btst #4,g_layers
 beq.s .no_front
 bsr draw_front
.no_front:
 btst #6,g_layers
 beq.s .no_sprites2
 sf spr_pass
 bsr draw_sprites
.no_sprites2:
 tst.b g_control
 bpl.s .no_chars
 bsr draw_chars
.no_chars:
 move.w draw_idx,d0
 lsl.w #2,d0
 lea ring_dmg_end,a0
 move.l dmg_ptr,(a0,d0.w)
 move.l draw_base,d0
 sub.l #PIC_TOP*STRIDE,d0
 move.l d0,flip_addr
 move.w draw_idx,d0
 addq.b #1,d0
 move.b d0,frame_ready
 rts

; ---- the back layer -------------------------------------------------------------------------------------------------
; Bring ring draw_idx up to the back layer's scroll: restore its damage, move its window by the scroll since its last
; visit and draw the map lines that came into the band (a first use, a change of the back layer's enable or a jump of
; more than 200 lines draws the band whole).  draw_base = the window's line 0.  Window line y shows map line
; M = bx + 255 - y (bx = the back scroll, D803-D804), buffer line ring_top + y.
ring_update:
 move.w draw_idx,d0
 move.w d0,d1
 add.w d1,d1
 move.w d1,ring_off2
 lsl.w #2,d0
 lea ring_base,a0
 move.l (a0,d0.w),ring_addr
 lea ring_dmg,a1
 move.w draw_idx,d1
 mulu #DMG_MAX*12,d1
 add.l d1,a1
 move.l a1,dmg_start
 moveq #0,d0
 move.b Z_SCROLL+3,d0
 moveq #0,d1
 move.b Z_SCROLL+4,d1
 lsl.w #8,d1
 or.w d0,d1
 move.w d1,cur_bx
 move.b g_layers,d0
 and.b #$20,d0
 move.b d0,cur_back
 move.w draw_idx,d2
 lea ring_valid,a0
 tst.b (a0,d2.w)
 beq .full
 lea ring_back,a0
 cmp.b (a0,d2.w),d0
 bne .full
 move.w ring_off2,d2
 lea ring_bx,a0
 move.w cur_bx,d0
 sub.w (a0,d2.w),d0		; the scroll since the last visit
 move.w d0,d7
 bpl.s .positive
 neg.w d7
.positive:
 cmp.w #200,d7
 bhi .full
 move.w d0,scroll_d
 bsr restore_damage
 move.w ring_off2,d2
 lea ring_bx,a0
 move.w cur_bx,(a0,d2.w)
 lea ring_top,a0
 move.w (a0,d2.w),d1
 sub.w scroll_d,d1		; (bx + 1: the picture one line down, the window one line up in the ring)
 bpl.s .t1
 add.w #RING_H,d1
.t1:
 cmp.w #RING_H,d1
 blo.s .t2
 sub.w #RING_H,d1
.t2:
 move.w d1,(a0,d2.w)
 move.w d1,cur_top
 move.w scroll_d,d0
 beq.s .base
 bmi.s .down
 move.w #-RING_ABOVE,d1		; scrolled forward: window lines -32 .. -32 + d - 1 are new
 bra.s .lines
.down:
 neg.w d0			; backward: 288 - d .. 287
 move.w #256+32,d1
 sub.w d0,d1
.lines:
 bsr back_lines
.base:
 move.l ring_addr,d0
 moveq #0,d1
 move.w cur_top,d1
 lsl.l #8,d1
 add.l d1,d0
 move.l d0,draw_base
 move.l dmg_start,dmg_ptr
 rts
.full:
 move.w draw_idx,d2
 lea ring_valid,a0
 st (a0,d2.w)
 lea ring_back,a0
 move.b cur_back,(a0,d2.w)
 move.w ring_off2,d2
 lea ring_bx,a0
 move.w cur_bx,(a0,d2.w)
 lea ring_top,a0
 clr.w (a0,d2.w)
 clr.w cur_top
 move.w #-RING_ABOVE,d1
 move.w #RING_ABOVE+256+32,d0
 bsr back_lines
 bra.s .base

; d1 = the first window line (-32 .. 287), d0 = lines: the back layer's lines there, into every copy in the ring.
back_lines:
 subq.w #1,d0
.line:
 movem.w d0-d1,-(sp)
 bsr back_line
 movem.w (sp)+,d0-d1
 addq.w #1,d1
 dbf d0,.line
 rts

; d1 = a window line: map line M = bx + 255 - y; 14 chunks (the window) of the 8 tiles of map column M / 32 at
; their line 31 - (M & 31), or black when the layer is off, into buffer line b = top + y (mod RING_H), b + RING_H,
; b + 2 RING_H (b < 32) and b - RING_H (b >= RING_H - 32).
back_line:
 move.w cur_top,d2
 add.w d1,d2
 bpl.s .b1
 add.w #RING_H,d2
.b1:
 cmp.w #RING_H,d2
 blo.s .b2
 sub.w #RING_H,d2
.b2:
 move.w cur_bx,d3
 add.w #255,d3
 sub.w d1,d3			; M
 lea back_ptrs,a2		; the 8 source lines
 tst.b cur_back
 beq.s .black
 moveq #31,d4
 and.w d3,d4
 eor.w #31,d4
 lsl.w #4,d4			; (line 31 - (M & 31)) * 16
 lsr.w #5,d3			; the map column
 lsl.w #4,d3			; (8 words a column)
 lea back_map,a0
 add.w d3,a0
 lea back_tiles,a1
 moveq #7,d5
.tile:
 moveq #0,d6
 move.w (a0)+,d6
 moveq #9,d7
 lsl.l d7,d6			; (512 bytes a tile)
 add.l a1,d6
 add.l d4,d6
 move.l d6,(a2)+
 dbf d5,.tile
 bra.s .copies
.black:
 moveq #7,d5
.zero:
 move.l #zero_line,(a2)+
 dbf d5,.zero
.copies:
 move.w d2,d0
 bsr.s .put
 move.w d2,d0
 add.w #RING_H,d0
 bsr.s .put
 cmp.w #32,d2
 bhs.s .no_third
 move.w d2,d0
 add.w #2*RING_H,d0
 bsr.s .put
.no_third:
 cmp.w #RING_H-32,d2
 blo.s .done
 move.w d2,d0
 sub.w #RING_H,d0
 bsr.s .put
.done:
 rts
; d0 = a buffer line: the 14 chunks from back_ptrs
.put:
 ext.l d0
 lsl.l #8,d0
 move.l ring_addr,a1
 add.l d0,a1
 lea GAME_X(a1),a1
 lea back_ptrs,a2
 move.l (a2)+,a0
 move.l 8(a0),(a1)+		; (tile 0: its right chunk only)
 move.l 12(a0),(a1)+
 rept 6
 move.l (a2)+,a0
 movem.l (a0),d3-d6
 movem.l d3-d6,(a1)
 lea 16(a1),a1
 endr
 move.l (a2)+,a0
 move.l (a0)+,(a1)+		; (tile 7: its left chunk only)
 move.l (a0)+,(a1)+
 rts

; The damage list of the ring (dmg_start .. its end): copied back from the twin lines.
restore_damage:
 move.w draw_idx,d0
 lsl.w #2,d0
 lea ring_dmg_end,a0
 move.l (a0,d0.w),a3
 move.l dmg_start,a2
 move.w #$ffff,BLT_END1.w
 move.w #$ffff,BLT_END2.w
 move.w #$ffff,BLT_END3.w
 move.w #2,BLT_SRC_XINC.w
 move.w #2,BLT_DST_XINC.w
 move.w #$0203,BLT_HOP_OP.w
 clr.b BLT_SKEW.w
 bra.s .test
.rect:
 move.l (a2)+,d0
 move.l (a2)+,d1
 move.w (a2)+,d2
 move.w (a2)+,d3
 move.w d2,d4
 add.w d4,d4
 neg.w d4
 add.w #STRIDE+2,d4
 wait_b
 move.w d4,BLT_SRC_YINC.w
 move.w d4,BLT_DST_YINC.w
 move.w d2,BLT_COUNT.w
 move.l d1,BLT_SRC_ADDR.w
 move.l d0,BLT_DST_ADDR.w
 move.w d3,BLT_COUNT+2.w
 move.b #$c0,BLT_CTRL.w
.test:
 cmp.l a3,a2
 blo.s .rect
 rts

; d2 = the address of a rectangle's first line and chunk, d0 = its window line, d1 = lines (at most 16: short HOG
; bursts), d3 = words a line: into the damage list with its twin as the source (split at buffer line RING_H).
; Keeps all registers.
add_damage:
 movem.l d0-d2/d4/a0,-(sp)
 add.w cur_top,d0		; (the buffer line)
 move.l dmg_ptr,a0
 cmp.w #RING_H,d0
 bge.s .lower
 move.w d0,d4
 add.w d1,d4
 cmp.w #RING_H,d4
 ble.s .upper
 move.w #RING_H,d4
 sub.w d0,d4
 sub.w d4,d1
 move.l d2,(a0)+
 move.l d2,(a0)
 add.l #RING_H*STRIDE,(a0)+
 move.w d3,(a0)+
 move.w d4,(a0)+
 ext.l d4
 lsl.l #8,d4
 add.l d4,d2
 bra.s .lower
.upper:
 move.l d2,(a0)+
 move.l d2,(a0)
 add.l #RING_H*STRIDE,(a0)+
 move.w d3,(a0)+
 move.w d1,(a0)+
 bra.s .done
.lower:
 move.l d2,(a0)+
 move.l d2,(a0)
 sub.l #RING_H*STRIDE,(a0)+
 move.w d3,(a0)+
 move.w d1,(a0)+
.done:
 move.l a0,dmg_ptr
 movem.l (sp)+,d0-d2/d4/a0
 rts

; d2 = the address of a rectangle's first line and chunk, d0 = its first chunk (-3 .. 16), d4 = its chunks, d1 =
; lines: the chunks of it outside the window (0 .. 13) cleared.  Keeps all registers.
clear_outside:
 movem.l d0-d6/a0,-(sp)
 move.w d0,d6			; the first chunk
 move.w d0,d5
 add.w d4,d5			; the chunk after the last
 move.w d5,d3			; left: chunks d6 .. min(d5, 0) - 1
 ble.s .l1
 moveq #0,d3
.l1:
 sub.w d6,d3
 ble.s .right
 move.l d2,a0
 bsr.s .clear
.right:
 moveq #14,d0			; right: chunks max(d6, 14) .. d5 - 1
 cmp.w d6,d0
 bge.s .r1
 move.w d6,d0
.r1:
 move.w d5,d3
 sub.w d0,d3
 ble.s .out
 sub.w d6,d0
 lsl.w #3,d0
 move.l d2,a0
 add.w d0,a0
 bsr.s .clear
.out:
 movem.l (sp)+,d0-d6/a0
 rts
; a0 = the first chunk, d3 = chunks, d1 = lines
.clear:
 lsl.w #2,d3			; words a line
 move.w #$ffff,BLT_END1.w
 move.w #$ffff,BLT_END2.w
 move.w #$ffff,BLT_END3.w
 move.w #2,BLT_DST_XINC.w
 move.w d3,d0
 add.w d0,d0
 neg.w d0
 add.w #STRIDE+2,d0
 move.w d0,BLT_DST_YINC.w
 clr.w BLT_HOP_OP.w		; (all zero)
 clr.b BLT_SKEW.w
 wait_b
 move.l a0,BLT_DST_ADDR.w
 move.w d3,BLT_COUNT.w
 move.w d1,BLT_COUNT+2.w
 move.b #$c0,BLT_CTRL.w
 rts

; ---- the front layer ------------------------------------------------------------------------------------------------
; Map column c covers raw x 32c - fx .. +31 (fx = D800-D801): its tiles' first window line is 224 - (32c - fx); row r
; covers raw y (32r - fy) & 255 .. +31 (fy = D802), window x = that - 16, and wraps at raw y 256 (drawn again 256
; pixels to the left).
draw_front:
 moveq #0,d0
 move.b Z_SCROLL,d0
 moveq #0,d1
 move.b Z_SCROLL+1,d1
 lsl.w #8,d1
 or.w d0,d1			; fx
 move.w d1,d0
 and.w #31,d0
 add.w #224,d0
 move.w d0,front_y		; the first column's line: 224 - rx, rx = -(fx & 31)
 lsr.w #5,d1
 move.w d1,front_col
 moveq #8,d7			; nine columns
.column:
 cmp.w #-32,front_y
 ble.s .done			; (rx > 255: off the window)
 moveq #0,d6			; row
.row:
 moveq #0,d0
 move.w front_col,d0
 and.w #2047,d0
 lsl.w #3,d0
 add.w d6,d0
 lsl.l #2,d0
 lea front_map,a0
 move.l (a0,d0.l),d0
 beq.s .blank
 lea front_tiles-1,a0
 add.l d0,a0
 move.w d6,d1
 lsl.w #5,d1
 moveq #0,d2
 move.b Z_SCROLL+2,d2
 sub.w d2,d1
 and.w #255,d1			; raw y of the tile's first pixel
 sub.w #16,d1			; window x
 move.w d1,front_x
 bsr front_tile
 cmp.w #224-16,front_x
 ble.s .blank
 sub.w #256,front_x		; (wraps at raw y 256)
 bsr front_tile
.blank:
 addq.w #1,d6
 cmp.w #8,d6
 blo.s .row
 addq.w #1,front_col
 sub.w #32,front_y
 dbf d7,.column
.done:
 rts

; a0 = a baked front tile, front_x / front_y = its window position (whole: up to 31 lines beyond the window).
front_tile:
 movem.l d6-d7/a0,-(sp)
 move.w front_x,d0
 asr.w #4,d0
 move.w d0,obj_chunk
 lsl.w #3,d0
 move.w front_y,d2
 add.w cur_top,d2		; (the band is contiguous: no wrap)
 ext.l d2
 lsl.l #8,d2
 add.l ring_addr,d2
 ext.l d0
 add.l d0,d2
 add.l #GAME_X,d2		; d2 = the first chunk of its first line
 move.l d2,obj_addr
 moveq #15,d5
 and.w front_x,d5		; shift
 moveq #2,d4			; chunks
 tst.w d5
 beq.s .w
 moveq #3,d4
.w:
 move.w d4,d3
 lsl.w #2,d3			; words a line (damage)
 move.w front_y,d0
 moveq #16,d1
 bsr add_damage
 add.l #16*STRIDE,d2
 add.w #16,d0
 bsr add_damage
 ; the Blitter: one call per run and plane, Y count = the run's lines
 move.w #2,BLT_SRC_XINC.w
 move.w #2,BLT_SRC_YINC.w
 move.w #8,BLT_DST_XINC.w
 move.w #$0203,BLT_HOP_OP.w
 move.w #$ffff,BLT_END2.w
 move.w d4,BLT_COUNT.w		; X count = chunks (one word of each)
 move.w d4,d0
 lsl.w #3,d0
 neg.w d0
 add.w #STRIDE+8,d0
 move.w d0,BLT_DST_YINC.w
 move.b d5,d0
 beq.s .skew
 or.b #NFSR,d0
.skew:
 move.b d0,BLT_SKEW.w
 lea 512(a0),a1			; the runs
.run:
 move.w (a1)+,d1		; lines
 beq .runs_done
 move.w (a1)+,d0		; first line
 move.w (a1)+,d2		; masks
 move.w (a1)+,d3
 tst.w d5
 bne.s .shifted
 move.w d2,BLT_END1.w
 move.w d3,BLT_END3.w
 bra.s .planes
.shifted:
 swap d2
 move.w d3,d2			; the 32 opaque pixels
 move.l d2,d6
 lsr.l d5,d6			; words 0, 1 of the 48
 moveq #16,d7
 sub.w d5,d7
 lsl.w d7,d3			; word 2: the low word << (16 - shift)
 move.w d3,BLT_END3.w
 move.w d6,BLT_END2.w
 swap d6
 move.w d6,BLT_END1.w
.planes:
 move.l obj_addr,d2
 move.w d0,d3
 ext.l d3
 lsl.l #8,d3
 add.l d3,d2			; the run's first line
 lsl.w #2,d0
 lea (a0,d0.w),a2		; the run's first line, plane 0 (4 bytes a line, 128 a plane)
 moveq #3,d3
.plane:
 wait_b
 move.l a2,BLT_SRC_ADDR.w
 move.l d2,BLT_DST_ADDR.w
 move.w d1,BLT_COUNT+2.w
 move.b #$c0,BLT_CTRL.w
 lea 128(a2),a2
 addq.l #2,d2
 dbf d3,.plane
 bra .run
.runs_done:
 move.w obj_chunk,d0		; the chunks beside the window
 cmp.w #13,d0
 bgt.s .outside
 add.w d4,d0
 cmp.w #14,d0
 bgt.s .outside
 tst.w obj_chunk
 bpl.s .inside
.outside:
 move.l obj_addr,d2
 move.w obj_chunk,d0
 moveq #32,d1
 bsr clear_outside
.inside:
 movem.l (sp)+,d6-d7/a0
 rts

; ---- sprites ----------------------------------------------------------------------------------------------------------
; The 128 entries of the buffered list (g_sprites: code, attribute, y, x), the last first (the earlier ones win).
; spr_pass set: the entries of colours 10 and 11 only, else the others.  Attribute: bits 5-7 code bits 8-10, bit 4
; x bit 8 (subtracted), bits 0-3 colour.  Window x = y - 16, window line = 240 - x.
draw_sprites:
 lea g_sprites+127*4,a0
 move.l a0,spr_ptr
.loop:
 move.l spr_ptr,a0
 moveq #0,d1
 move.b 1(a0),d1
 move.w d1,d0
 and.w #15,d0
 cmp.w #10,d0
 beq.s .behind
 cmp.w #11,d0
 beq.s .behind
 tst.b spr_pass
 bne .next
 bra.s .pass
.behind:
 tst.b spr_pass
 beq .next
.pass:
 moveq #0,d3
 move.b 3(a0),d3
 btst #4,d1
 beq.s .positive
 sub.w #256,d3
.positive:
 neg.w d3
 add.w #240,d3			; window line
 cmp.w #-16,d3
 ble .next
 cmp.w #256,d3
 bge .next
 moveq #0,d4
 move.b 2(a0),d4
 sub.w #16,d4			; window x
 cmp.w #-16,d4
 ble .next
 move.w d3,dest_y
 move.w d4,dest_x
 moveq #0,d0
 move.b (a0),d0
 move.w d1,d2
 and.w #$e0,d2
 lsl.w #3,d2
 or.w d2,d0			; code
 move.w d0,spr_code
 and.w #15,d1			; colour
 bsr sprite_get
 bsr sprite_part
.next:
 subq.l #4,spr_ptr
 cmp.l #g_sprites,spr_ptr
 bhs .loop
 rts

; d0 = code, d1 = colour: a1 = the baked sprite (16 lines in blit order of 4 plane words), from the cache or baked
; now (the pool rolls over: the cache is cleared then).
sprite_get:
 move.w d0,d3
 lsl.w #4,d3
 or.w d1,d3			; tag = code * 16 + colour
 move.w d3,d5
 lsr.w #4,d5
 eor.w d3,d5
 and.w #$fff,d5
 lsl.w #3,d5
 lea spr_cache,a1
 add.w d5,a1
 move.w pool_epoch,d2
 cmp.w 2(a1),d2
 bne.s .bake
 cmp.w (a1),d3
 bne.s .bake
 move.l 4(a1),a1
 rts
.bake:
 movem.l d0-d7/a0/a2-a6,-(sp)
 addq.l #1,cache_misses
 move.l pool_ptr,a2
 cmp.l #pool+POOL_SIZE-128,a2
 blo.s .room
 bsr cache_clear
 move.l pool_ptr,a2
.room:
 move.w d3,(a1)
 move.w pool_epoch,2(a1)
 move.l a2,4(a1)
 lea 128(a2),a3
 move.l a3,pool_ptr
 moveq #0,d2
 move.w d0,d2
 lsl.l #7,d2			; (128 bytes a sprite: 16 lines of 8 bytes)
 lea spr_pix,a0
 add.l d2,a0
 lea spr_cmap,a3
 lsl.w #4,d1
 add.w d1,a3			; the colour's 16 pens
 moveq #15,d7
.line:
 moveq #0,d3
 moveq #0,d4
 moveq #0,d5
 moveq #0,d6
 moveq #7,d1
.pair:
 move.b (a0)+,d0
 move.w d0,d2
 lsr.b #4,d2
 bsr.s .pixel
 move.b d0,d2
 bsr.s .pixel
 dbf d1,.pair
 movem.w d3-d6,(a2)
 addq.l #8,a2
 dbf d7,.line
 movem.l (sp)+,d0-d7/a0/a2-a6
 move.l 4(a1),a1
 rts
; d2 (low nibble) = a pen: one more pixel into the plane words d3-d6
.pixel:
 and.w #15,d2
 move.b (a3,d2.w),d2
 add.w d3,d3
 add.w d4,d4
 add.w d5,d5
 add.w d6,d6
 lsr.b #1,d2
 bcc.s .p1
 addq.w #1,d3
.p1:
 lsr.b #1,d2
 bcc.s .p2
 addq.w #1,d4
.p2:
 lsr.b #1,d2
 bcc.s .p3
 addq.w #1,d5
.p3:
 lsr.b #1,d2
 bcc.s .p4
 addq.w #1,d6
.p4:
 rts

; The pool rolls over: every cached object is stale (the slots carry the epoch they were baked in).
cache_clear:
 move.l #pool,pool_ptr
 addq.w #1,pool_epoch
 rts

; a1 = the baked sprite, spr_code, dest_x / dest_y: the whole part (generated routine, or the generic path at a 64 KB
; boundary of the low word), its damage, and what it drew beside the window cleared.
sprite_part:
 move.w dest_y,d2
 add.w cur_top,d2
 ext.l d2
 lsl.l #8,d2
 add.l ring_addr,d2
 move.w dest_x,d0
 asr.w #4,d0
 move.w d0,obj_chunk
 lsl.w #3,d0
 ext.l d0
 add.l d0,d2
 add.l #GAME_X,d2
 move.l d2,obj_addr
 moveq #4,d3
 moveq #15,d1
 and.w dest_x,d1
 beq.s .one
 moveq #8,d3
.one:
 move.w dest_y,d0
 moveq #16,d1
 bsr add_damage
 move.w dest_x,d3
 move.w #2,BLT_SRC_XINC.w
 move.w #2,BLT_SRC_YINC.w
 move.w #8,BLT_DST_XINC.w
 move.w #$ffff,BLT_END2.w
 move.w #$0203,BLT_HOP_OP.w
 move.l a1,BLT_SRC_ADDR.w
 move.l d2,BLT_DST_ADDR.w
 moveq #0,d0
 move.w spr_code,d0
 lsl.l #4,d0
 move.w d3,d1
 and.w #15,d1
 or.w d1,d0
 lsl.l #2,d0
 lea spr_code_tab,a0
 move.l (a0,d0.l),d0		; routine << 20 | stream offset
 beq .out
 move.l d0,d1
 swap d1
 lsr.w #4,d1
 lsl.w #2,d1
 lea spr_routines,a1
 move.l (a1,d1.w),a1
 and.l #$fffff,d0
 lea spr_streams,a0
 add.l d0,a0
 move.w d2,d0
 cmp.w #$efe0,d0
 bhi.s .generic
 movem.l d4-d7/a2-a6,-(sp)
 lea BLT_END1.w,a2
 lea BLT_END3.w,a3
 lea BLT_DST_ADDR+2.w,a4
 lea BLT_COUNT+2.w,a5
 lea BLT_CTRL.w,a6
 move.w #248,d4
 move.w #-264,d5
 moveq #4,d6
 move.w #$c0,d7
 wait_b
 jsr (a1)
 movem.l (sp)+,d4-d7/a2-a6
 bra.s .margins
.generic:
 bsr generic_part
.margins:
 move.w obj_chunk,d0
 bmi.s .outside
 cmp.w #13,d0
 blt.s .out
 bgt.s .outside
 moveq #15,d1
 and.w dest_x,d1
 beq.s .out			; (one chunk, the window's last)
.outside:
 move.l obj_addr,d2
 moveq #1,d4
 moveq #15,d1
 and.w dest_x,d1
 beq.s .c
 moveq #2,d4
.c:
 moveq #16,d1
 bsr clear_outside
.out:
 rts

; Crossing a 64 KB boundary: full addresses; the masks still come from the stream (a0), the lines from spr_plan.
generic_part:
 movem.l d2-d5/a1-a2,-(sp)
 move.l d2,a1
 and.w #15,d3
 bne.s .shifted
 move.w #1,BLT_COUNT.w
 move.w #2,BLT_DST_YINC.w
 clr.b BLT_SKEW.w
 bra.s .plan
.shifted:
 move.w #2,BLT_COUNT.w
 move.w #-6,BLT_DST_YINC.w
 move.b d3,d0
 or.b #NFSR,d0
 move.b d0,BLT_SKEW.w
.plan:
 move.l a0,a2
 moveq #0,d0
 move.w spr_code,d0
 lsl.l #2,d0
 lea spr_plan_offsets,a0
 move.l (a0,d0.l),d0
 lea spr_plan,a0
 add.l d0,a0
 moveq #1,d5
.group:
 move.w (a0)+,d1
 beq.s .done
 move.w (a2)+,BLT_END1.w
 tst.w d3
 beq.s .n3
 move.w (a2)+,BLT_END3.w
.n3:
 tst.w d5
 beq.s .rows
 moveq #0,d5
 addq.l #2,a2			; (the control word of the first row)
.rows:
 subq.w #1,d1
.row:
 adda.w (a0)+,a1
 wait_b
 move.l a1,BLT_DST_ADDR.w
 move.w #4,BLT_COUNT+2.w
 move.b #$c0,BLT_CTRL.w
 dbf d1,.row
 bra.s .group
.done:
 movem.l (sp)+,d2-d5/a1-a2
 rts

; ---- characters -------------------------------------------------------------------------------------------------------
; chr_ptr[cell] = the baked character (8 lines of a keep mask and the four plane bytes, for movep.l) of every visible,
; non-blank cell, or 0.  It changes only where the character RAM (D000 codes, D400 attributes) differs from its copy
; chr_raw (compared as longs); then chr_list (the offset and the baked character of each cell) is made again.  The
; cache's pool rolling over (pool_epoch) frees the baked characters: every cell is done again then.
draw_chars:
 move.w pool_epoch,d0
 cmp.w chr_epoch,d0
 beq.s .same_pool
 st chr_full
.same_pool:
 lea Z_CHR,a2
 lea chr_raw,a3
 tst.b chr_full
 beq.s .scan_start
.full:
 clr.b chr_full
 move.w pool_epoch,chr_epoch
 move.w #255,d0
.copy:
 move.l $400(a2),$400(a3)
 move.l (a2)+,(a3)+
 dbf d0,.copy
 moveq #0,d6
.all:
 bsr chr_cell
 addq.w #1,d6
 cmp.w #1024,d6
 blo.s .all
 bra .list
.scan_start:
 sf chr_dirty
 lea $400(a2),a4
 lea $400(a3),a5
 move.w #255,d6
.scan:
 cmpm.l (a2)+,(a3)+
 bne.s .diff
 cmpm.l (a4)+,(a5)+
 bne.s .diff2
 dbf d6,.scan
 bra.s .scanned
.diff:
 addq.l #4,a4
 addq.l #4,a5
.diff2:
 move.l -4(a2),-4(a3)
 move.l -4(a4),-4(a5)
 st chr_dirty
 movem.l d6/a2-a5,-(sp)
 move.w #255,d0
 sub.w d6,d0
 lsl.w #2,d0
 move.w d0,d6
 bsr chr_cell
 addq.w #1,d6
 bsr chr_cell
 addq.w #1,d6
 bsr chr_cell
 addq.w #1,d6
 bsr chr_cell
 movem.l (sp)+,d6/a2-a5
 dbf d6,.scan
.scanned:
 move.w pool_epoch,d0		; (the pool rolled over while baking: every cell again)
 cmp.w chr_epoch,d0
 beq.s .same
 lea Z_CHR,a2
 lea chr_raw,a3
 bra .full
.same:
 tst.b chr_dirty
 beq.s .draw
.list:
 lea chr_rows,a3		; (the first and last chunk of each character row: $ff = none)
 moveq #-1,d1
 moveq #15,d0
.no_rows:
 move.l d1,(a3)+
 dbf d0,.no_rows
 lea chr_rows,a3
 lea chr_ptr+2*4*32,a0		; (columns 0 and 1 and 30 and 31 are outside the window)
 lea chr_list,a1
 lea chr_offsets+2*4*32,a2
 moveq #64,d3
 move.w #28*32-1,d0
.gather:
 move.l (a0)+,d1
 beq.s .empty
 move.l (a2),(a1)+
 move.l d1,(a1)+
 move.w d3,d4
 and.w #31,d4
 move.w d3,d5
 lsr.w #5,d5
 subq.w #2,d5
 lsr.w #1,d5
 cmp.b #$ff,(a3,d4.w)
 bne.s .known
 move.b d5,(a3,d4.w)
.known:
 move.b d5,32(a3,d4.w)
.empty:
 addq.l #4,a2
 addq.w #1,d3
 dbf d0,.gather
 move.l a1,chr_list_end
 sf chr_dirty
.draw:
 lea chr_rows,a3		; damage: each character row's chunks
 moveq #0,d6
.row:
 moveq #0,d4
 move.b (a3,d6.w),d4
 cmp.b #$ff,d4
 beq.s .no_row
 moveq #0,d3
 move.b 32(a3,d6.w),d3
 sub.w d4,d3
 addq.w #1,d3
 lsl.w #2,d3			; words a line
 move.w d6,d0
 lsl.w #3,d0
 neg.w d0
 add.w #248,d0			; window line
 move.l draw_base,d2
 move.w d0,d1
 ext.l d1
 lsl.l #8,d1
 add.l d1,d2
 lsl.w #3,d4
 ext.l d4
 add.l d4,d2
 add.l #GAME_X,d2
 moveq #8,d1
 bsr add_damage
.no_row:
 addq.w #1,d6
 cmp.w #32,d6
 blo.s .row
 move.l draw_base,d1
 lea chr_list,a2
 move.l chr_list_end,a3
 bra.s .test
.char:
 move.l (a2)+,a1
 add.l d1,a1
 move.l (a2)+,a0
 rept 8
 movep.l (REPTN*STRIDE)(a1),d0
 and.l (a0)+,d0
 or.l (a0)+,d0
 movep.l d0,(REPTN*STRIDE)(a1)
 endr
.test:
 cmp.l a3,a2
 blo.s .char
 rts

; d6 = a cell: chr_ptr[cell] = its baked character or 0 (blank or outside the window).  Keeps d6.
chr_cell:
 move.w d6,d4
 add.w d4,d4
 add.w d4,d4
 lea chr_ptr,a0
 clr.l (a0,d4.w)
 move.w d6,d0
 lsr.w #5,d0
 subq.w #2,d0
 cmp.w #28,d0
 bhs.s .out
 lea Z_CHR,a0
 moveq #0,d2
 move.b (a0,d6.w),d2
 moveq #0,d1
 lea $400(a0),a0
 move.b (a0,d6.w),d1
 move.w d1,d3
 and.w #$e0,d3
 lsl.w #3,d3
 or.w d3,d2			; code
 lea chr_blank,a0
 tst.b (a0,d2.w)
 bne.s .out
 and.w #31,d1			; colour
 bsr chr_get
 lea chr_ptr,a0
 move.l a1,(a0,d4.w)
.out:
 rts

; d2 = code, d1 = colour: a1 = the baked character (hashed cache: tag = code * 32 + colour, 4096 slots).
chr_get:
 move.w d2,d3
 lsl.w #5,d3
 or.w d1,d3			; tag
 move.w d3,d5
 lsr.w #4,d5
 eor.w d3,d5
 and.w #$fff,d5
 lsl.w #3,d5
 lea chr_cache,a1
 add.w d5,a1
 move.w pool_epoch,d0
 cmp.w 2(a1),d0
 bne.s .bake
 cmp.w (a1),d3
 bne.s .bake
 move.l 4(a1),a1
 rts
.bake:
 movem.l d0-d7/a0/a2-a6,-(sp)
 move.l pool_ptr,a2
 cmp.l #pool+POOL_SIZE-64,a2
 blo.s .room
 bsr cache_clear			; (the caller sees pool_epoch change and does every cell again)
 move.l pool_ptr,a2
.room:
 move.w d3,(a1)
 move.w pool_epoch,2(a1)
 move.l a2,4(a1)
 lea 64(a2),a3
 move.l a3,pool_ptr
 lea chr_pix,a0
 lsl.w #4,d2
 add.w d2,a0			; (16 bytes a character; d2 < 2048)
 lea chr_cmap,a3
 lsl.w #2,d1
 add.w d1,a3
 moveq #7,d7
.line:
 move.w (a0)+,d0		; 8 pens of 2 bits
 moveq #0,d3			; opaque
 moveq #0,d4			; the four plane bytes (plane 0 in the top byte)
 moveq #7,d6
.pixel:
 rol.w #2,d0
 moveq #3,d1
 and.w d0,d1
 add.b d3,d3
 tst.w d1
 beq.s .clear
 addq.b #1,d3
.clear:
 move.b (a3,d1.w),d1		; the STE index
 lsl.l #1,d4			; (the 4 bytes: each gets the next bit)
 and.l #$fefefefe,d4
 lsr.b #1,d1
 bcc.s .b0
 bset #24,d4
.b0:
 lsr.b #1,d1
 bcc.s .b1
 bset #16,d4
.b1:
 lsr.b #1,d1
 bcc.s .b2
 bset #8,d4
.b2:
 lsr.b #1,d1
 bcc.s .b3
 bset #0,d4
.b3:
 dbf d6,.pixel
 move.b d3,d5			; the keep mask in each byte, the plane bytes masked
 lsl.w #8,d5
 move.b d3,d5
 move.w d5,d1
 swap d5
 move.w d1,d5
 and.l d5,d4
 not.l d5
 move.l d5,(a2)+
 move.l d4,(a2)+
 dbf d7,.line
 movem.l (sp)+,d0-d7/a0/a2-a6
 move.l 4(a1),a1
 rts

 include "spr_code.s"
 section data,data
ste_pal: incbin "palette.bin"
black_pal: dcb.w 16,0
zero_line: dcb.b 16,0
back_tiles: incbin "back_tiles.bin"
back_map: incbin "back_map.bin"
front_tiles: incbin "front_tiles.bin"
 even
front_map: incbin "front_map.bin"
spr_pix: incbin "spr_pix.bin"
spr_cmap: incbin "spr_cmap.bin"
chr_pix: incbin "chr_pix.bin"
chr_cmap: incbin "chr_cmap.bin"
chr_blank: incbin "chr_blank.bin"
spr_plan_offsets: incbin "spr_plan_offsets.bin"
spr_plan: incbin "spr_plan.bin"
 section bss,bss
POOL_SIZE = $18000
spr_cache: ds.l 2*4096
chr_cache: ds.l 2*4096
pool_ptr: ds.l 1
pool: ds.b POOL_SIZE
cache_misses: ds.l 1
pool_epoch: ds.w 1
chr_epoch: ds.w 1
chr_full: ds.b 1
chr_dirty: ds.b 1
spr_pass: ds.b 1
cur_back: ds.b 1
frame_ready: ds.b 1
 even
chr_list_end: ds.l 1
chr_raw: ds.b 2048
chr_ptr: ds.l 1024
chr_offsets: ds.l 1024
chr_list: ds.l 2*28*32
chr_rows: ds.b 64
ring_valid: ds.b 4
ring_back: ds.b 4
ring_top: ds.w 3
ring_bx: ds.w 3
ring_off2: ds.w 1
ring_addr: ds.l 1
back_ptrs: ds.l 8
cur_bx: ds.w 1
cur_top: ds.w 1
scroll_d: ds.w 1
front_x: ds.w 1
front_y: ds.w 1
front_col: ds.w 1
obj_chunk: ds.w 1
obj_addr: ds.l 1
dmg_start: ds.l 1
dmg_ptr: ds.l 1
ring_dmg_end: ds.l 3
ring_dmg: ds.b 3*DMG_MAX*12
spr_ptr: ds.l 1
spr_code: ds.w 1
dest_x: ds.w 1
dest_y: ds.w 1
draw_idx: ds.w 1
shown_idx: ds.w 1
prev_idx: ds.w 1
ring_base: ds.l 3
draw_base: ds.l 1
flip_addr: ds.l 1
shown_pal: ds.w 16
screen_area: ds.b 3*RING_SIZE+256
 section text,code
