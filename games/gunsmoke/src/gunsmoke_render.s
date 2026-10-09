; Gun.Smoke renderer: the arcade raster rotated (screen row r = 255 - raw x, column c = raw y - 16), 224 x 256 shown.
;
; Background: 32 x 32 tiles from the map ROM (bgtiles: 2048 columns of 8 tiles, a word each: code, attribute), a pure
; function of the scroll registers D800/D801 (S: map line M = S + 255 - r) and D802 (the map row k of a tile is at
; screen x = 32k - 16 - D802, modulo 256).  As in Commando the three display buffers are virtual screens shown at the
; scroll position by the video address: buffer line l and l+RING_H hold the same background, so the band of 288 lines
; (the 256 shown and 16 guard lines on each side for whole sprites) is contiguous wherever the window is.  Whole tiles
; at the band's edges reach up to 31 lines beyond it, into the 32 spare line pairs (RING_H = 288 + 32); a tile is
; drawn at its line, its twin RING_H below and, when it crosses line RING_H, RING_H above, hence 32 lines above and below.
; Each buffer draws only the tile rows that scrolled into its band since it was drawn last; a new D802, background on/off
; or a jump of more than 200 lines draws the band whole.  Tiles that reach beside the window clear the two chunks there.
;
; Sprites and characters are drawn whole over it; what they covered is a damage list per buffer, copied back from the
; twin lines the next time that buffer is drawn.  Graphics are baked into STE planes on first use (a hashed cache per
; kind) from their pixel-value planes through a routine per colour bank (assets.py: the pens' masks ORed into the
; planes by the 16 colour palette).
STRIDE = 256
GAME_X = 24
RING_H = 320
RING_ABOVE = 32
RING_LINES = RING_ABOVE+2*RING_H+32
RING_SIZE = RING_LINES*STRIDE
DMG_MAX = 520				; damage rectangles a frame (12 bytes: destination, source, words, lines)
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

Z_TEXT = G_Z80-$3000			; D000 codes, D400 attributes
Z_SCROLL = G_Z80-$2800			; D800 / D801: S, D802: the map rows' offset

TILE_POOL = $30000			; baked objects: tiles 512 bytes, sprites 160, characters 64
SPR_POOL = $20000
CHR_POOL = $8000

 section text,code
init_video:
 move.l #screen_area+255,d0
 clr.b d0
 add.l #RING_ABOVE*STRIDE,d0
 move.l d0,ring_base
 add.l #RING_SIZE,d0
 move.l d0,ring_base+4
 add.l #RING_SIZE,d0
 move.l d0,ring_base+8
 move.b #48,$ffff820f.w
 move.l ring_base,d0
 sub.l #PIC_TOP*STRIDE,d0
 bsr show_address
 rts
show_address:
 move.l d0,-(sp)
 move.b 1(sp),$ffff8201.w
 move.b 2(sp),$ffff8203.w
 move.b 3(sp),$ffff820d.w
 addq.l #4,sp
 rts
init_render:
 clr.l ring_valid
 lea ring_dmg,a0
 move.l a0,ring_dmg_end
 lea DMG_MAX*12(a0),a0
 move.l a0,ring_dmg_end+4
 lea DMG_MAX*12(a0),a0
 move.l a0,ring_dmg_end+8
 movem.l ste_pal,d0-d7
 movem.l d0-d7,shown_pal
 lea screen_area,a0
 move.l #3*RING_SIZE/16-1,d0
.clear:
 clr.l (a0)+
 clr.l (a0)+
 clr.l (a0)+
 clr.l (a0)+
 subq.l #1,d0
 bpl.s .clear
 lea cache,a0
 move.w #3*4096*8/4-1,d0
.cache:
 clr.l (a0)+
 dbf d0,.cache
 move.l #tile_pool,pool_ptr
 move.l #spr_pool,pool_ptr+4
 move.l #chr_pool,pool_ptr+8
 st fg_full
 st band_rows
 lea fg_offsets,a0		; cell: column c = cell / 32 (x = 8c - 16), row r = cell & 31 (y = 248 - 8r)
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
 move.w #0,shown_idx
 move.w #1,prev_idx
 rts
vbl_video:
 movem.l d0-d7,-(sp)
 movem.l black_pal,d0-d7
 movem.l d0-d7,$ffff8240.w
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
 movem.l (sp)+,d0-d7
 rts

; Draw a frame into a buffer that is neither shown, nor was shown during the last frame, nor waits to be shown.
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
 st frame_dirty
 rts
.chosen:
 move.w d0,draw_idx
 dbgcnt dbg_renders
 bsr ring_update
 btst #5,Z_LAYERS
 beq.s .no_sprites
 bsr draw_sprites
.no_sprites:
 bsr draw_foreground
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

; ------------------------------------------------------------------------------
; Background
; ------------------------------------------------------------------------------

; Bring the buffer draw_idx up to the scroll: restore the damage of its last frame, move its window by the scroll since,
; draw the tiles of the map lines that came into its band.  draw_base = the window's first line.
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
 move.b Z_SCROLL+1,d1		; S = D801:D800
 lsl.w #8,d1
 move.b Z_SCROLL,d1
 move.w d1,cur_S
 moveq #0,d1
 move.b Z_SCROLL+2,d1
 move.w d1,cur_sy
 move.b Z_LAYERS,d1
 and.b #16,d1
 move.b d1,cur_bg
 move.w draw_idx,d2
 lea ring_valid,a0
 tst.b (a0,d2.w)
 beq .full
 lea ring_bg,a0
 cmp.b (a0,d2.w),d1
 bne .full
 move.w ring_off2,d2
 lea ring_sy,a0
 move.w cur_sy,d1
 sub.w (a0,d2.w),d1		; D802 since: 1-15 more (the map slides left) shifts the buffer, other changes redraw
 move.w d1,shift_d
 cmp.w #15,d1
 bhi .full			; (unsigned: a step back too)
 lea ring_S,a0
 move.w cur_S,d0
 sub.w (a0,d2.w),d0		; the scroll since: map lines
 move.w d0,d7
 bpl.s .positive
 neg.w d7
.positive:
 cmp.w #200,d7
 bhi .full
 move.w d0,scroll_d
 bsr restore_damage
 tst.w shift_d
 beq.s .no_shift
 bsr shift_ring
 move.w ring_off2,d2
 lea ring_sy,a0
 move.w cur_sy,(a0,d2.w)
.no_shift:
 move.w ring_off2,d2
 lea ring_S,a0
 move.w cur_S,(a0,d2.w)
 lea ring_top,a0
 move.w (a0,d2.w),d1
 sub.w scroll_d,d1		; (S up: the window moves up the buffer)
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
 beq.s .done
 bmi.s .back
 move.w cur_S,d1		; forward: map lines S+272-d .. S+271 (the band's top)
 add.w #272,d1
 sub.w d0,d1
 bra.s .band
.back:
 neg.w d0			; back: S-16 .. S-16-d-1 (the band's bottom)
 move.w cur_S,d1
 sub.w #16,d1
.band:
 bsr draw_band
.done:
 tst.w shift_d
 beq.s .no_strip
 bsr draw_strip
.no_strip:
 move.l ring_addr,d0
 moveq #0,d1
 move.w cur_top,d1
 lsl.l #8,d1
 add.l d1,d0
 move.l d0,draw_base
 move.l dmg_start,dmg_ptr
 rts
.full:
 clr.w shift_d
 move.w draw_idx,d2
 lea ring_valid,a0
 st (a0,d2.w)
 lea ring_bg,a0
 move.b cur_bg,(a0,d2.w)
 move.w ring_off2,d2
 lea ring_sy,a0
 move.w cur_sy,(a0,d2.w)
 lea ring_S,a0
 move.w cur_S,(a0,d2.w)
 lea ring_top,a0
 clr.w (a0,d2.w)
 clr.w cur_top
 move.l ring_addr,a0		; the side chunks of the whole buffer black (the damage list is dropped)
 lea -RING_ABOVE*STRIDE(a0),a0
 moveq #RING_LINES/32-1,d0
 bsr clear_margins
 move.w cur_S,d1
 sub.w #16,d1
 move.w #288,d0
 bsr draw_band
 bra .done

; D802 grew by shift_d (1-15) since the buffer was drawn: the window's chunks move left by that many pixels (Blitter,
; skew 16 - shift_d with FXSR, in place: each destination word is written after the source word right of it was read),
; 16 lines at a time per plane.  Only the lines that must hold the background are moved: the band of the buffer's
; window (from line 0) and the twins of the band's lines.  What comes in on the right is the margin's black: draw_strip.
shift_ring:
 move.w #$ffff,BLT_END1.w
 move.w #$ffff,BLT_END2.w
 move.w #$ffff,BLT_END3.w
 move.w #8,BLT_SRC_XINC.w
 move.w #STRIDE-14*8,BLT_SRC_YINC.w	; (15 source words a line: FXSR)
 move.w #8,BLT_DST_XINC.w
 move.w #STRIDE-13*8,BLT_DST_YINC.w
 move.w #14,BLT_COUNT.w
 move.w #$0203,BLT_HOP_OP.w
 moveq #16,d0
 sub.w shift_d,d0
 or.b #$80,d0			; FXSR
 move.b d0,BLT_SKEW.w
 move.w ring_off2,d2
 lea ring_top,a0
 move.w (a0,d2.w),d4		; the band: b0 = top - 16 .. b1 = top + 271
 move.w d4,d5
 sub.w #16,d4
 add.w #271,d5
 move.w d4,d0			; the band from line 0
 bpl.s .r1
 moveq #0,d0
.r1:
 move.w d5,d1
 bsr.s shift_lines
 move.w d4,d0			; the twins of its lines below RING_H: + RING_H
 add.w #RING_H,d0
 move.w d5,d1
 cmp.w #RING_H-1,d1
 ble.s .r2
 move.w #RING_H-1,d1
.r2:
 add.w #RING_H,d1
 bsr.s shift_lines
 move.w d5,d1			; of those from RING_H: - RING_H
 sub.w #RING_H,d1
 bmi.s .out
 moveq #0,d0
 bsr.s shift_lines
.out:
 rts

; d0 .. d1: buffer lines of the buffer ring_addr moved by shift_ring's set-up (keeps d4, d5).
shift_lines:
 sub.w d0,d1			; lines - 1
 move.l ring_addr,a1
 ext.l d0
 lsl.l #8,d0
 add.l d0,a1
 lea GAME_X(a1),a1
 moveq #3,d3
.plane:
 move.l a1,a0
 move.w d1,d2
.burst:
 moveq #7,d0			; up to 8 lines a burst (HOG: under 2 scanlines)
 cmp.w d0,d2
 bge.s .n
 move.w d2,d0
.n:
 sub.w d0,d2
 addq.w #1,d0
 wait_borders
 move.l a0,BLT_SRC_ADDR.w
 move.l a0,BLT_DST_ADDR.w
 move.w d0,BLT_COUNT+2.w
 move.b #$c0,BLT_CTRL.w
 ext.l d0
 lsl.l #8,d0
 add.l d0,a0
 subq.w #1,d2
 bpl.s .burst
 addq.l #2,a1
 dbf d3,.plane
 rts

; After shift_ring: the tiles of the map rows that reach the shift_d pixels at the window's right edge, over the band.
draw_strip:
 moveq #0,d3			; the rows (bits)
 moveq #0,d5
 move.w #224,d4
 sub.w shift_d,d4
.k:
 move.w d5,d2			; x = ((32k + 16 - D802) & 255) - 32, as draw_cell
 lsl.w #5,d2
 add.w #16,d2
 sub.w cur_sy,d2
 and.w #255,d2
 sub.w #32,d2
 cmp.w #-32,d2
 beq.s .next
 cmp.w #223,d2
 bgt.s .next
 add.w #31,d2
 cmp.w d4,d2
 blt.s .next
 bset d5,d3
.next:
 addq.w #1,d5
 cmp.w #8,d5
 blo.s .k
 move.b d3,band_rows
 st strip_mode
 move.w cur_S,d1
 sub.w #16,d1
 move.w #288,d0
 bsr draw_band
 st band_rows
 sf strip_mode
 rts

; draw_strip's part of the tile a1 (dest_x, dest_y): the window's last chunk (x 208-223), where it is in the tile and in
; the shift_d pixels at the right edge; one word a line per plane, taken from the baked tile's two words with FXSR and
; skew (o = 208 - x: the words o / 16 and the one after it, shifted left by o & 15).
strip_blit:
 move.w #208,d0
 sub.w dest_x,d0		; o, -15 .. 31
 move.w d0,d1
 asr.w #4,d1			; the first source word
 and.w #15,d0
 bne.s .shifted
 subq.w #1,d1			; (no shift: the second word read is the one)
.shifted:
 neg.w d0
 and.w #15,d0
 or.b #$80,d0			; FXSR, skew (16 - o & 15) & 15
 move.b d0,BLT_SKEW.w
 add.w d1,d1
 lea (a1,d1.w),a2		; the source
 move.w #224,d2			; the pixels: from max(x, 224 - shift_d) to min(x + 31, 223)
 sub.w shift_d,d2
 move.w dest_x,d0
 cmp.w d2,d0
 ble.s .lo
 move.w d0,d2
.lo:
 sub.w #208,d2
 add.w #31,d0
 cmp.w #223,d0
 ble.s .hi
 move.w #223,d0
.hi:
 sub.w #208,d0
 moveq #-1,d3
 lsr.w d2,d3			; from pixel d2
 moveq #-1,d1
 moveq #15,d2
 sub.w d0,d2
 lsl.w d2,d1			; to pixel d0
 and.w d1,d3
 move.w d3,BLT_END1.w
 move.w #2,BLT_SRC_XINC.w
 move.w #2,BLT_SRC_YINC.w
 move.w #STRIDE,BLT_DST_YINC.w
 move.w #1,BLT_COUNT.w
 move.w #$0203,BLT_HOP_OP.w
 bsr destination_line
 add.l #GAME_X+13*8,d2
 moveq #3,d3
.plane:
 wait_borders
 move.l a2,BLT_SRC_ADDR.w
 move.l d2,BLT_DST_ADDR.w
 move.w #32,BLT_COUNT+2.w
 move.b #$c0,BLT_CTRL.w
 lea 128(a2),a2
 addq.l #2,d2
 dbf d3,.plane
 rts

; a0 = a line, d0 = segments of 32 lines - 1: the two chunks on each side of the window are cleared, 32 lines at a time.
clear_margins:
 bsr.s margin_setup
 move.l a0,a1
 lea GAME_X-16(a0),a0
 bsr.s .column
 lea GAME_X+112(a1),a0
.column:
 move.w d0,d1
.segment:
 wait_borders
 move.l a0,BLT_DST_ADDR.w
 move.w #32,BLT_COUNT+2.w
 move.b #$80,BLT_CTRL.w
.wait:
 btst #7,BLT_CTRL.w
 bne .wait
 lea 32*STRIDE(a0),a0
 dbf d1,.segment
 rts
margin_setup:
 move.w #$ffff,BLT_END1.w
 move.w #$ffff,BLT_END2.w
 move.w #$ffff,BLT_END3.w
 move.w #2,BLT_DST_XINC.w
 move.w #STRIDE-14,BLT_DST_YINC.w
 move.w #8,BLT_COUNT.w
 clr.w BLT_HOP_OP.w
 clr.b BLT_SKEW.w
 rts

; d1 = the first map line (a word, modulo 65536), d0 = lines: the tiles of the map columns that hold them.
draw_band:
 move.w d1,d6
 lsr.w #5,d6			; the first column
 add.w d0,d1
 subq.w #1,d1
 lsr.w #5,d1			; the last
 move.w d1,band_last
.column:
 moveq #0,d5
.row:
 btst d5,band_rows		; (the map rows to draw: all, but draw_strip's)
 beq.s .skip
 bsr draw_cell
.skip:
 addq.w #1,d5
 cmp.w #8,d5
 blo.s .row
 cmp.w band_last,d6
 beq.s .out
 addq.w #1,d6
 and.w #2047,d6
 bra.s .column
.out:
 rts

; d6 = the map column j, d5 = the row k: the tile, if it reaches the band (screen rows -16 .. 271), at its buffer line,
; the twin and (when it crosses line RING_H) the line RING_H above.  Keeps all registers.
draw_cell:
 movem.l d0-d7/a0-a6,-(sp)
 move.w cur_S,d1		; the tile's top row: S + 224 - 32j
 add.w #224,d1
 move.w d6,d0
 lsl.w #5,d0
 sub.w d0,d1
 cmp.w #-48,d1
 ble .out
 cmp.w #272,d1
 bge .out
 move.w d5,d2			; x = ((32k - 16 - D802 + 32) & 255) - 32
 lsl.w #5,d2
 add.w #16,d2
 sub.w cur_sy,d2
 and.w #255,d2
 sub.w #32,d2
 cmp.w #-32,d2
 beq .out
 move.w d2,dest_x
 add.w cur_top,d1
 bpl.s .p
 add.w #RING_H,d1
.p:
 cmp.w #RING_H,d1
 blo.s .q
 sub.w #RING_H,d1
.q:
 move.w d1,cell_line
 lea tile_black,a1
 tst.b cur_bg
 beq.s .draw
 move.w d6,d0			; the map word: code, attribute (bit 0: code bit 8, 2-5: colour, 6-7: flips)
 lsl.w #3,d0
 add.w d5,d0
 add.w d0,d0
 lea bgmap,a0
 move.b 1(a0,d0.w),d1
 lsl.w #8,d1
 move.b (a0,d0.w),d1
 move.w d1,d0
 moveq #0,d1
 bsr get_object
.draw:
 move.l ring_addr,draw_base
 move.w cell_line,dest_y
 bsr tile_twice
 move.w cell_line,d0
 add.w #RING_H,d0
 move.w d0,dest_y
 bsr tile_twice
 cmp.w #RING_H-32,cell_line
 ble.s .out
 move.w cell_line,d0
 sub.w #RING_H,d0
 move.w d0,dest_y
 bsr tile_twice
.out:
 movem.l (sp)+,d0-d7/a0-a6
 rts

; The tile a1 at dest_x / dest_y, and black in the side chunks it reaches.  Keeps a1.
tile_twice:
 move.l a1,-(sp)
 tst.b strip_mode
 beq.s .whole
 bsr strip_blit
 bra.s .out
.whole:
 bsr draw_tile
 move.w dest_x,d0
 bmi.s .left
 cmp.w #192,d0
 ble.s .out
 move.l #GAME_X+112,d1
 bra.s .clear
.left:
 moveq #GAME_X-16,d1
.clear:
 bsr margin_setup
 bsr destination_line
 add.l d1,d2
 wait_borders
 move.l d2,BLT_DST_ADDR.w
 move.w #32,BLT_COUNT+2.w
 move.b #$c0,BLT_CTRL.w
.out:
 move.l (sp)+,a1
 rts

; a1 = 4 planes x 32 rows x 2 words, the whole tile at dest_x / dest_y.
draw_tile:
 move.w dest_x,d0
 and.w #15,d0
 mulu #10,d0
 lea tile_shift,a0
 add.w d0,a0
 move.w (a0)+,BLT_END1.w
 move.w #$ffff,BLT_END2.w
 move.w (a0)+,BLT_END3.w
 move.w (a0)+,tile_ctrl
 move.w (a0)+,BLT_COUNT.w
 move.w (a0)+,BLT_DST_YINC.w
 move.w #2,BLT_SRC_XINC.w
 move.w #2,BLT_SRC_YINC.w
 move.w #8,BLT_DST_XINC.w
 move.w #$0203,BLT_HOP_OP.w
 bsr destination
 moveq #3,d3
.plane:
 wait_borders
 move.l a1,BLT_SRC_ADDR.w
 move.l d2,BLT_DST_ADDR.w
 move.w #32,BLT_COUNT+2.w
 move.w tile_ctrl,BLT_CTRL.w
 lea 128(a1),a1
 addq.l #2,d2
 dbf d3,.plane
 rts

; d2 = the destination chunk of dest_x / dest_y (floor x / 16; guard positions are signed).
destination:
 bsr.s destination_line
 move.w dest_x,d0
 asr.w #4,d0
 lsl.w #3,d0
 add.w #GAME_X,d0
 ext.l d0
 add.l d0,d2
 rts
destination_line:
 move.w dest_y,d2
 ext.l d2
 lsl.l #8,d2			; (STRIDE)
 add.l draw_base,d2
 rts

; The damage list of the buffer (dmg_start .. its end): copied back from the twin lines.
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
 wait_borders
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

; d2 = the address of a rectangle's first line and chunk, d0 = its buffer line, d1 = lines, d3 = words a line: added to
; the damage list with its twin as the source (split at line RING_H).  Keeps all registers.
add_damage:
 movem.l d1-d2/d4/a0,-(sp)
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
 movem.l (sp)+,d1-d2/d4/a0
 rts

; ------------------------------------------------------------------------------
; Sprites: 128 entries of (code, attribute, y, x), entry 127 first (entry 0 on top).  Attribute: bank 6-7 (3: + the
; sprite bank of D806), x bit 8 in bit 5, y flip 4 (a mirror on the screen), colour 0-3.
; ------------------------------------------------------------------------------

draw_sprites:
 lea sprite_buffer+127*4,a0
 move.l a0,spr_ptr
.loop:
 move.l spr_ptr,a0
 moveq #0,d1
 move.b 1(a0),d1
 moveq #0,d3			; the top row: 240 - raw x
 move.b 3(a0),d3
 btst #5,d1
 beq.s .positive
 sub.w #256,d3
.positive:
 neg.w d3
 add.w #240,d3
 cmp.w #-16,d3
 ble .next
 cmp.w #256,d3
 bge .next
 moveq #0,d4			; x: raw y - 16
 move.b 2(a0),d4
 sub.w #16,d4
 cmp.w #-16,d4
 ble .next
 cmp.w #224,d4
 bge .next
 move.w d3,dest_y
 move.w d4,dest_x
 move.w d1,d2			; the code: + 256 * bank (bank 3: + the sprite bank)
 lsr.w #6,d2
 cmp.w #3,d2
 bne.s .bank
 move.b Z_LAYERS,d0
 and.w #7,d0
 add.w d0,d2
.bank:
 lsl.w #8,d2
 moveq #0,d0
 move.b (a0),d0
 add.w d2,d0
 and.w #2047,d0
 move.w d0,d2			; the shape: code * 2 + flip
 add.w d2,d2
 btst #4,d1
 beq.s .shape
 addq.w #1,d2
 bset #11,d0
.shape:
 move.w d2,spr_shape_n
 and.w #15,d1			; the key: code, flip << 11, colour << 12
 ror.w #4,d1
 or.w d1,d0
 moveq #1,d1
 bsr get_object
 bsr sprite_part
 move.w dest_x,d0		; a sprite over a side of the window: the side chunk it reaches black again (the screen
 bmi.s .left			; shows 48 pixels on each side; the damage list restores the chunk from its black twin)
 cmp.w #208,d0
 ble .next
 move.l #GAME_X+112,d1
 bra.s .side
.left:
 moveq #GAME_X-8,d1
.side:
 bsr destination_line
 add.l d1,d2
 move.w #$ffff,BLT_END1.w
 move.w #$ffff,BLT_END2.w
 move.w #$ffff,BLT_END3.w
 move.w #2,BLT_DST_XINC.w
 move.w #STRIDE-6,BLT_DST_YINC.w
 move.w #4,BLT_COUNT.w
 clr.w BLT_HOP_OP.w
 clr.b BLT_SKEW.w
 wait_borders
 move.l d2,BLT_DST_ADDR.w
 move.w #16,BLT_COUNT+2.w
 move.b #$c0,BLT_CTRL.w
.next:
 subq.l #4,spr_ptr
 cmp.l #sprite_buffer,spr_ptr
 bhs .loop
 rts

; a1 = the baked sprite at dest_x / dest_y: its damage, then the generated routine of its shape and shift (spritegen.py)
; or, for the shapes without one, the generic path.
sprite_part:
 bsr destination
 move.l dmg_ptr,a0		; damage: 16 lines of 1 or 2 chunks, the twin as source (split at line RING_H: add_damage)
 move.w dest_y,d0
 add.w cur_top,d0
 moveq #4,d3
 moveq #15,d1
 and.w dest_x,d1
 beq.s .one
 moveq #8,d3
.one:
 cmp.w #RING_H-16,d0
 bgt.s .lower
 move.l d2,(a0)+
 move.l d2,d1
 add.l #RING_H*STRIDE,d1
 bra.s .store
.lower:
 cmp.w #RING_H,d0
 blt.s .split
 move.l d2,(a0)+
 move.l d2,d1
 sub.l #RING_H*STRIDE,d1
.store:
 move.l d1,(a0)+
 move.w d3,(a0)+
 move.w #16,(a0)+
 move.l a0,dmg_ptr
 bra.s .damaged
.split:
 moveq #16,d1
 bsr add_damage
.damaged:
 move.w dest_x,d3
 and.w #15,d3
 move.w #2,BLT_SRC_XINC.w
 move.w #2,BLT_SRC_YINC.w
 move.w #8,BLT_DST_XINC.w
 move.w #$ffff,BLT_END2.w
 move.w #$0203,BLT_HOP_OP.w
 moveq #0,d0
 move.w spr_shape_n,d0
 add.w d0,d0
 lea spr_shape,a0
 move.w (a0,d0.w),d0
 cmp.w #$ffff,d0
 beq any_part
 move.w d0,spr_pcode
 move.l a1,BLT_SRC_ADDR.w
 move.l d2,BLT_DST_ADDR.w
 lsl.l #4,d0
 or.w d3,d0
 lsl.l #3,d0
 lea spr_code_tab,a0
 move.l (a0,d0.l),a1
 move.l 4(a0,d0.l),a0
 move.l a1,d0
 beq .out
 move.w d2,d0
 cmp.w #$efe0,d0
 bhi generic_part
 lea BLT_END1.w,a2
 lea BLT_END3.w,a3
 lea BLT_DST_ADDR+2.w,a4
 lea BLT_COUNT+2.w,a5
 lea BLT_CTRL.w,a6
 move.w #248,d4
 move.w #-264,d5
 moveq #4,d6
 move.w #$c0,d7
 wait_borders
 jsr (a1)
.out:
 rts

; Crossing a 64 KB boundary uses full addresses; the masks still come from the baked streams.  d2 = the destination,
; d3 = the shift, a0 = the stream.
generic_part:
 move.l d2,a1
 tst.w d3
 bne .shifted
 move.w #1,BLT_COUNT.w
 move.w #2,BLT_DST_YINC.w
 clr.b BLT_SKEW.w
 bra .plan
.shifted:
 move.w #2,BLT_COUNT.w
 move.w #-6,BLT_DST_YINC.w
 move.b d3,d0
 or.b #NFSR,d0
 move.b d0,BLT_SKEW.w
.plan:
 move.l a0,a2
 moveq #0,d0
 move.w spr_pcode,d0
 lsl.l #2,d0
 lea spr_plan_offsets,a0
 move.l (a0,d0.l),d0
 lea spr_plan,a0
 add.l d0,a0
 moveq #1,d5
.group:
 move.w (a0)+,d1
 beq .done
 move.w (a2)+,BLT_END1.w
 tst.w d3
 beq .n3
 move.w (a2)+,BLT_END3.w
.n3:
 tst.w d5
 beq .rows
 moveq #0,d5
 addq.l #2,a2
.rows:
 subq.w #1,d1
.row:
 adda.w (a0)+,a1
 wait_borders
 move.l a1,BLT_DST_ADDR.w
 move.w #4,BLT_COUNT+2.w
 move.b #$c0,BLT_CTRL.w
 dbf d1,.row
 bra .group
.done:
 rts

; A shape without generated code: its rows in order, the end masks from its opaque rows (128(a1)), one Blitter call
; per row.  d2 = the destination, d3 = the shift, a1 = the baked sprite.
any_part:
 dbgcnt dbg_any
 moveq #2,d5			; the destination Y increment
 moveq #1,d6			; X count
 move.b d3,d7			; skew
 beq.s .set
 moveq #-6,d5
 moveq #2,d6
 or.b #NFSR,d7
.set:
 move.w d5,BLT_DST_YINC.w
 move.w d6,BLT_COUNT.w
 move.b d7,BLT_SKEW.w
 lea 128(a1),a2
 moveq #15,d4
.row:
 move.w (a2)+,d0
 beq.s .skip
 move.w d0,d1
 lsr.w d3,d0
 moveq #16,d7
 sub.w d3,d7
 lsl.w d7,d1
 wait_borders
 move.w d0,BLT_END1.w
 move.w d1,BLT_END3.w
 move.l a1,BLT_SRC_ADDR.w
 move.l d2,BLT_DST_ADDR.w
 move.w #4,BLT_COUNT+2.w
 move.b #$c0,BLT_CTRL.w
.skip:
 addq.l #8,a1
 add.l #STRIDE,d2
 dbf d4,.row
 rts

; ------------------------------------------------------------------------------
; Text: 8 x 8 characters, code D000 + attribute bits 5-7 * 256, colour attribute bits 0-4; the pens the lookup PROM marks
; $4F are transparent.  fg_ptr has a baked character (8 rows of a keep mask and the four plane bytes, for movep.l) for
; every visible, not blank cell, or 0.  It changes where the text RAM differs from its copy fg_raw, compared as longs
; when a translated writer ran (fg_written, gen.py text_sites) and 128 bytes a frame in case one is missing; then
; fg_list (the screen offset and the baked character of each cell to draw) is made again.  A pool roll-over of the
; characters (pool_epoch) frees the baked characters: then every cell is done again.
; ------------------------------------------------------------------------------

draw_foreground:
 sf fg_retry
 move.w pool_epoch+4,d0
 cmp.w fg_epoch,d0
 beq.s .same_pool
 st fg_full
.same_pool:
 lea Z_TEXT,a2
 lea fg_raw,a3
 tst.b fg_full
 beq.s .scan_start
.full:
 clr.b fg_full
 clr.b fg_written
 move.w pool_epoch+4,fg_epoch
 move.w #255,d0
.copy:
 move.l $400(a2),$400(a3)
 move.l (a2)+,(a3)+
 dbf d0,.copy
 moveq #0,d6
.all:
 bsr fg_cell
 addq.w #1,d6
 cmp.w #1024,d6
 blo.s .all
 st fg_dirty
 bra .scanned
.scan_start:
 sf fg_dirty
 tst.b fg_written
 bne.s .written
 move.w fg_roll,d0
 add.w #128,d0
 and.w #$7ff,d0
 move.w d0,fg_roll
 lea (a2,d0.w),a4
 lea (a3,d0.w),a5
 moveq #128/4-1,d0
.roll:
 cmpm.l (a4)+,(a5)+
 dbne d0,.roll
 beq .scanned
.written:
 clr.b fg_written
 lea $400(a2),a4
 lea $400(a3),a5
 move.w #255,d6
.scan:
 cmpm.l (a2)+,(a3)+
 bne.s .diff
 cmpm.l (a4)+,(a5)+
 bne.s .diff2
 dbf d6,.scan
 bra .scanned
.diff:
 addq.l #4,a4
 addq.l #4,a5
.diff2:
 move.l -4(a2),-4(a3)
 move.l -4(a4),-4(a5)
 st fg_dirty
 movem.l d6/a2-a5,-(sp)
 move.w #255,d0
 sub.w d6,d0
 lsl.w #2,d0
 move.w d0,d6
 bsr fg_cell
 addq.w #1,d6
 bsr fg_cell
 addq.w #1,d6
 bsr fg_cell
 addq.w #1,d6
 bsr fg_cell
 movem.l (sp)+,d6/a2-a5
 dbf d6,.scan
.scanned:
 move.w pool_epoch+4,d0		; (the pool rolled over while baking: every pointer again, once)
 cmp.w fg_epoch,d0
 beq.s .same
 tst.b fg_retry
 bne.s .same
 st fg_retry
 lea Z_TEXT,a2
 lea fg_raw,a3
 bra .full
.same:
 tst.b fg_dirty
 beq.s .draw
.list:
 lea fg_rows,a3			; (the first and last chunk of each character row: $ff = none)
 moveq #-1,d1
 moveq #15,d0
.no_rows:
 move.l d1,(a3)+
 dbf d0,.no_rows
 lea fg_rows,a3
 lea fg_ptr+2*4*32,a0		; (columns 0 and 1 and 30 and 31 are outside the window)
 lea fg_list,a1
 lea fg_offsets+2*4*32,a2
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
 move.l a1,fg_list_end
 sf fg_dirty
.draw:
 tst.b Z_LATCH			; (bit 7: the text layer on)
 bpl .off
 lea fg_rows,a3			; damage: each character row's chunks, in four bursts of 2 lines (HOG Blitter: short)
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
 add.w #248,d0			; y
 moveq #0,d2
 move.w d0,d2
 lsl.l #8,d2
 add.l draw_base,d2
 lsl.w #3,d4
 add.w d4,d2
 add.l #GAME_X,d2
 add.w cur_top,d0
 moveq #2,d1
 moveq #3,d5
.burst:
 bsr add_damage
 add.l #2*STRIDE,d2
 addq.w #2,d0
 dbf d5,.burst
.no_row:
 addq.w #1,d6
 cmp.w #32,d6
 blo.s .row
 move.l draw_base,d1
 lea fg_list,a2
 move.l fg_list_end,a3
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
.off:
 rts

; d6 = the cell: fg_ptr[cell] = its baked character or 0 (blank, or outside the window).  Keeps d6.
fg_cell:
 move.w d6,d4
 add.w d4,d4
 add.w d4,d4
 lea fg_ptr,a0
 clr.l (a0,d4.w)
 move.w d6,d0
 lsr.w #5,d0
 subq.w #2,d0
 cmp.w #28,d0
 bhs.s .out
 lea Z_TEXT,a0
 moveq #0,d2
 move.b (a0,d6.w),d2
 lea $400(a0),a0
 moveq #0,d1
 move.b (a0,d6.w),d1
 move.w d1,d3
 and.w #$e0,d3
 lsl.w #2,d3
 add.w d3,d2
 and.w #$3ff,d2			; the code (MAME: the byte + attribute bits 5-7 * 128, of 1024)
 and.w #31,d1			; the colour
 lea chr_trans,a0
 move.b (a0,d1.w),d3
 not.b d3
 lea chr_pens,a0
 and.b (a0,d2.w),d3
 and.b #15,d3
 beq.s .out			; (only transparent pens)
 lsl.w #8,d1
 lsl.w #2,d1
 or.w d1,d2
 move.w d2,d0			; the key: code, colour << 10
 moveq #2,d1
 bsr get_object
 lea fg_ptr,a0
 move.l a1,(a0,d4.w)
.out:
 rts

; ------------------------------------------------------------------------------
; The caches.  d0.w = the key, d1 = the kind (0 tile: the map word; 1 sprite: code, flip << 11, colour << 12; 2
; character: code, colour << 10) -> a1 = the baked object.  A hashed slot (tag = kind << 16 + key, pointer) per key;
; each kind has its own pool, which starts again (its slots cleared, pool_epoch + kind * 2 counted) when it is full.
; ------------------------------------------------------------------------------

get_object:
 movem.l d2-d3/a2,-(sp)		; (a hit: only the slot is looked at)
 move.w d1,d2
 swap d2
 move.w d0,d2
 move.w d0,d3
 lsr.w #4,d3
 eor.w d0,d3
 and.w #$fff,d3
 lsl.w #3,d3
 lea cache,a2
 tst.w d1
 beq.s .kind
 add.l #32768,a2
 cmp.w #1,d1
 beq.s .kind
 add.l #32768,a2
.kind:
 add.w d3,a2
 cmp.l (a2),d2
 bne.s .miss
 move.l 4(a2),a1
 move.l a1,d3
 beq.s .miss
 movem.l (sp)+,d2-d3/a2
 rts
.miss:
 movem.l (sp)+,d2-d3/a2
 movem.l d0-d7/a0/a2-a6,-(sp)
 addq.l #1,cache_misses
 and.l #$ffff,d0
 move.w d0,obj_key
 move.w d1,obj_kind
 swap d1
 or.l d1,d0
 move.l d0,obj_tag
 move.w obj_key,d2
 move.w d2,d3
 lsr.w #4,d3
 eor.w d3,d2
 and.w #$fff,d2
 lsl.w #3,d2
 moveq #0,d3
 move.w obj_kind,d3
 move.w d3,d4
 swap d3
 lsr.l #1,d3			; kind * 32768
 lea cache,a2
 add.l d3,a2
 add.w d2,a2
 move.l a2,cache_slot
 add.w d4,d4
 add.w d4,d4			; kind * 4
 lea pool_ptr,a3
 lea pool_end,a4
 move.l (a3,d4.w),a1
 lea pool_size,a5
 move.l (a5,d4.w),d5
 add.l a1,d5
 cmp.l (a4,d4.w),d5
 bls.s .room
 lea pool_start,a5		; full: this kind's pool again, its slots cleared
 move.l (a5,d4.w),a1
 lsr.w #1,d4
 lea pool_epoch,a5
 addq.w #1,(a5,d4.w)
 lsl.w #1,d4
 move.l d3,d5
 lea cache,a0
 add.l d5,a0
 move.w #4096*8/16-1,d5
.clear:
 clr.l (a0)+
 clr.l (a0)+
 clr.l (a0)+
 clr.l (a0)+
 dbf d5,.clear
.room:
 lea pool_size,a5
 move.l (a5,d4.w),d5
 add.l a1,d5
 move.l d5,(a3,d4.w)
 move.l a1,baked_ptr
 move.l cache_slot,a2
 move.l obj_tag,(a2)
 move.l a1,4(a2)
 move.w obj_kind,d1
 beq.s .tile
 cmp.w #1,d1
 beq.s .sprite
 bsr bake_char
 bra.s .baked
.tile:
 bsr bake_tile
 bra.s .baked
.sprite:
 bsr bake_sprite
.baked:
 move.l baked_ptr,a1
 movem.l (sp)+,d0-d7/a0/a2-a6
 rts

; The 16 pen masks of a row of pixel-value bits d0-d3 (v0-v3) as longs at (a4) (pen * 4).  Uses d2, d4-d7, a2, a3,
; a5, a6.
pen_masks:
 move.l d0,d4			; the low two bits: L3 = v0 & v1, L1 = v0 & ~v1, L2 = ~v0 & v1, L0 = ~(v0 | v1)
 and.l d1,d4
 move.l d0,d5
 eor.l d4,d5
 move.l d1,d6
 eor.l d4,d6
 move.l d0,d7
 or.l d1,d7
 not.l d7
 move.l d7,a2
 move.l d5,a3
 move.l d6,a5
 move.l d4,a6
 move.l d2,d4			; the high two bits: H3 = d4, H1 = d5, H2 = d6, H0 = d2
 and.l d3,d4
 move.l d2,d5
 eor.l d4,d5
 move.l d3,d6
 eor.l d4,d6
 or.l d3,d2
 not.l d2
pen_h macro			; \1 = H, \2 = the first pen
 move.l a2,d7
 and.l \1,d7
 move.l d7,(\2)*4(a4)
 move.l a3,d7
 and.l \1,d7
 move.l d7,(\2+1)*4(a4)
 move.l a5,d7
 and.l \1,d7
 move.l d7,(\2+2)*4(a4)
 move.l a6,d7
 and.l \1,d7
 move.l d7,(\2+3)*4(a4)
 endm
 pen_h d2,0
 pen_h d5,4
 pen_h d6,8
 pen_h d4,12
 rts

; d0-d3: each long's 32 bits mirrored (d6, d7, a0 used).
mirror32:
 lea reverse_bits,a0
 bsr.s .one
 exg d0,d1
 bsr.s .one
 exg d0,d1
 exg d0,d2
 bsr.s .one
 exg d0,d2
 exg d0,d3
 bsr.s .one
 exg d0,d3
 rts
.one:
 moveq #0,d7
 rept 4
 move.b d0,d7			; the low byte, mirrored, goes in at the bottom of d6 (it ends at the top)
 move.b (a0,d7.w),d7
 lsl.l #8,d6
 move.b d7,d6
 lsr.l #8,d0
 endr
 move.l d6,d0
 rts

; A tile (obj_key = the map word) into (a1): plane-major, 4 x 32 rows x 2 words.
bake_tile:
 move.w obj_key,d0
 moveq #0,d1
 move.w d0,d1
 and.w #$1ff,d1			; (attribute bit 0 is code bit 8)
 lsl.l #8,d1
 add.l d1,d1			; code * 512
 lea tile_planes,a0
 add.l d1,a0
 move.l a0,bake_src
 lsr.w #8,d0
 lsr.w #2,d0
 and.w #15,d0
 lsl.w #2,d0
 lea acc_tile_tab,a0
 move.l (a0,d0.w),bake_acc
 clr.w obj_row
.row:
 move.w obj_row,d0		; the source row: flip (attribute bit 6) reverses the rows
 btst #6,obj_key
 beq.s .down
 neg.w d0
 add.w #31,d0
.down:
 lsl.w #4,d0
 move.l bake_src,a0
 movem.l (a0,d0.w),d0-d3
 btst #7,obj_key		; (attribute bit 7 mirrors)
 beq.s .straight
 bsr mirror32
.straight:
 lea pen_scratch,a4
 bsr pen_masks
 move.l bake_acc,a0
 jsr (a0)
 move.l baked_ptr,a1
 move.w obj_row,d4
 lsl.w #2,d4
 add.w d4,a1
 move.l d0,(a1)
 move.l d1,128(a1)
 move.l d2,256(a1)
 move.l d3,384(a1)
 addq.w #1,obj_row
 cmp.w #32,obj_row
 blo.s .row
 rts

; A sprite (obj_key: code, flip << 11, colour << 12) into (a1): 16 rows of 4 plane words, in the order of its shape's
; generated code (spr_order) or in natural order (then the opaque row masks follow at 128).
bake_sprite:
 move.w obj_key,d0
 moveq #0,d1
 move.w d0,d1
 and.w #$7ff,d1
 lsl.l #7,d1			; code * 128
 lea spr_planes,a0
 add.l d1,a0
 move.l a0,bake_src
 move.w d0,d1
 lsr.w #8,d1
 lsr.w #2,d1
 and.w #$3c,d1			; colour * 4
 lea acc_spr_tab,a0
 move.l (a0,d1.w),bake_acc
 move.w d0,d1			; the shape: code * 2 + flip
 and.w #$7ff,d1
 add.w d1,d1
 btst #11,d0
 beq.s .s
 addq.w #1,d1
.s:
 add.w d1,d1
 lea spr_shape,a0
 move.w (a0,d1.w),d1
 sub.l a3,a3			; (no order: natural)
 cmp.w #$ffff,d1
 beq.s .order
 ext.l d1
 lsl.l #4,d1
 lea spr_order,a3
 add.l d1,a3
.order:
 move.l a3,bake_order
 clr.w obj_row
.row:
 move.w obj_row,d0
 move.l bake_order,d1
 beq.s .natural
 move.l d1,a0
 move.b (a0,d0.w),d0
 ext.w d0
.natural:
 move.w d0,obj_srow
 lsl.w #3,d0
 move.l bake_src,a0
 add.w d0,a0
 moveq #0,d0
 moveq #0,d1
 moveq #0,d2
 moveq #0,d3
 move.w (a0)+,d0
 move.w (a0)+,d1
 move.w (a0)+,d2
 move.w (a0)+,d3
 btst #3,obj_key		; (bit 11: mirrored)
 beq.s .straight
 bsr mirror32
 swap d0
 swap d1
 swap d2
 swap d3
.straight:
 move.w d0,d4			; the opaque pixels (pixel value not 0)
 or.w d1,d4
 or.w d2,d4
 or.w d3,d4
 move.w d4,obj_opaque
 lea pen_scratch,a4
 bsr pen_masks
 move.l bake_acc,a0
 jsr (a0)
 move.l baked_ptr,a1
 move.w obj_row,d4
 lsl.w #3,d4
 add.w d4,a1
 move.w d0,(a1)+
 move.w d1,(a1)+
 move.w d2,(a1)+
 move.w d3,(a1)+
 move.l baked_ptr,a1
 move.w obj_row,d4
 add.w d4,d4
 lea 128(a1),a1
 move.w obj_opaque,(a1,d4.w)
 addq.w #1,obj_row
 cmp.w #16,obj_row
 blo .row
 rts

; A character (obj_key: code, colour << 10) into (a1): 8 rows of (keep mask, plane bytes) longs for movep.l.
bake_char:
 move.w obj_key,d0
 move.w d0,d1
 and.w #$3ff,d1
 lsl.w #4,d1			; code * 16
 lea chr_planes,a0
 add.w d1,a0
 move.l a0,bake_src
 lsr.w #8,d0
 and.w #$7c,d0			; colour * 4
 lea acc_chr_tab,a0
 move.l (a0,d0.w),bake_acc
 clr.w obj_row
.row:
 move.l bake_src,a0
 move.w obj_row,d0
 add.w d0,d0
 moveq #0,d4
 moveq #0,d1
 move.b (a0,d0.w),d4		; plane 0 of the row
 move.b 1(a0,d0.w),d1
 move.l d4,d0
 move.l d4,d5			; (pen_masks: L only matters, pens 0-3)
 and.l d1,d4
 eor.l d4,d5
 move.l d1,d6
 eor.l d4,d6
 move.l d0,d7
 or.l d1,d7
 not.l d7
 lea pen_scratch,a4
 move.l d7,(a4)
 move.l d5,4(a4)
 move.l d6,8(a4)
 move.l d4,12(a4)
 move.l bake_acc,a0
 jsr (a0)
 move.l baked_ptr,a1
 move.w obj_row,d5
 lsl.w #3,d5
 add.w d5,a1
 move.b d4,d5			; the keep mask: not opaque, in each byte
 not.b d5
 move.b d5,d6
 lsl.w #8,d6
 move.b d5,d6
 move.w d6,d5
 swap d5
 move.w d6,d5
 move.l d5,(a1)+
 move.b d0,d5			; the plane bytes 0-3
 lsl.l #8,d5
 move.b d1,d5
 lsl.l #8,d5
 move.b d2,d5
 lsl.l #8,d5
 move.b d3,d5
 move.l d5,(a1)
 addq.w #1,obj_row
 cmp.w #8,obj_row
 blo .row
 rts

 include "render_tables.s"
 include "spr_code.s"
 section data,data
 even
ste_pal: incbin "palette.bin"
black_pal: dcb.w 16,0
reverse_bits: incbin "reverse.bin"
bgmap: incbin "bgtiles.rom"
tile_planes: incbin "tile_planes.bin"
spr_planes: incbin "spr_planes.bin"
chr_planes: incbin "chr_planes.bin"
chr_pens: incbin "chr_pens.bin"
chr_trans: incbin "chr_trans.bin"
 even
spr_shape: incbin "spr_shape.bin"
spr_order: incbin "spr_order.bin"
 even
spr_plan_offsets: incbin "spr_plan_offsets.bin"
spr_plan: incbin "spr_plan.bin"
 even
pool_start: dc.l tile_pool,spr_pool,chr_pool
pool_end: dc.l tile_pool+TILE_POOL,spr_pool+SPR_POOL,chr_pool+CHR_POOL
pool_size: dc.l 512,160,64
 section bss,bss
 even
tile_black: ds.b 512
cache: ds.b 3*4096*8
pool_ptr: ds.l 3
pool_epoch: ds.w 3
cache_misses: ds.l 1
dbg_any: ds.w 1
pen_scratch: ds.l 16
bake_src: ds.l 1
bake_acc: ds.l 1
bake_order: ds.l 1
fg_roll: ds.w 1
fg_epoch: ds.w 1
fg_written: ds.b 1
fg_full: ds.b 1
fg_dirty: ds.b 1
fg_retry: ds.b 1
cur_bg: ds.b 1
 even
fg_list_end: ds.l 1
fg_raw: ds.b 2048
fg_ptr: ds.l 1024
fg_offsets: ds.l 1024
fg_list: ds.l 2*28*32
fg_rows: ds.b 64
ring_valid: ds.b 4
ring_bg: ds.b 4
ring_top: ds.w 3
ring_S: ds.w 3
ring_sy: ds.w 3
ring_off2: ds.w 1
ring_addr: ds.l 1
cur_S: ds.w 1
cur_sy: ds.w 1
cur_top: ds.w 1
scroll_d: ds.w 1
shift_d: ds.w 1
band_rows: ds.b 1
strip_mode: ds.b 1
 even
band_last: ds.w 1
cell_line: ds.w 1
dmg_start: ds.l 1
dmg_ptr: ds.l 1
ring_dmg_end: ds.l 3
ring_dmg: ds.b 3*DMG_MAX*12
cache_slot: ds.l 1
baked_ptr: ds.l 1
obj_tag: ds.l 1
obj_key: ds.w 1
obj_kind: ds.w 1
obj_row: ds.w 1
obj_srow: ds.w 1
obj_opaque: ds.w 1
dest_x: ds.w 1
dest_y: ds.w 1
tile_ctrl: ds.w 1
spr_ptr: ds.l 1
spr_shape_n: ds.w 1
spr_pcode: ds.w 1
draw_idx: ds.w 1
shown_idx: ds.w 1
prev_idx: ds.w 1
ring_base: ds.l 3
draw_base: ds.l 1
flip_addr: ds.l 1
shown_pal: ds.w 16
tile_pool: ds.b TILE_POOL
spr_pool: ds.b SPR_POOL
chr_pool: ds.b CHR_POOL
screen_area: ds.b 3*RING_SIZE+256
 section text,code
