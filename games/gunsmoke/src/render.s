; Gun.Smoke renderer: the arcade raster rotated (screen row r = 255 - raw x, column c = raw y - 16), 224 x 256 shown.
;
; Background: 32 x 32 tiles from the map ROM (bgtiles: 2048 columns of 8 tiles, a word each: code, attribute), a pure
; function of the scroll registers D800/D801 (S: map line M = S + 255 - r) and D802 (the map row k of a tile is at
; screen x = 32k - 16 - D802, modulo 256).  Both axes scroll in hardware.  Vertically, as in Commando, the three display
; buffers are virtual screens shown at the scroll position by the video address: buffer line l and l+RING_H hold the
; same background, so the band of 288 lines (the 256 shown and 16 guard lines on each side for whole sprites) is
; contiguous wherever the window is.  Whole tiles at the band's edges reach up to 31 lines beyond it, into the 32 spare
; line pairs (RING_H = 288 + 32); a tile is drawn at its line, its twin RING_H below and, when it crosses line RING_H,
; RING_H above, hence 32 lines above and below.  Horizontally, as in Black Tiger, the tiles stay where they are on the
; 512-pixel lines (map row k at x = 32 + 32k and 256 to the right) and D802 moves the Shifter's window: the video
; address by chunks, $ffff8265 by pixels (the line width $ffff820f 4 words less then); the window starts at buffer
; x 48 + D802 (cur_wx).  D802 above HW_MAX moves the tiles by the rest instead (never seen in the game).
; Each buffer draws the tile rows that scrolled into its band since it was drawn last, with the side bars of the line
; pairs that came into it black, and, when its window moved, the columns that came into the window (only those
; columns of the tiles) and black where the side bars went (hw_strips).  A change of the tiles' offset, background
; on/off or a jump of more than 200 lines draws the band whole.  The screen shows 48 pixels on each side of the
; window: they stay black (a tile drawn whole over a side clears its part there; a sprite across a side draws only its
; inner word while the window starts on a 16-pixel group, else whole and clears its 16 pixels there).
;
; Sprites are drawn at the window's position (whole into the guard lines above and below), text as a strip per text row (composed with movep.l when the row
; changes, drawn with the Blitter at the window's pixel offset: NOT mask AND screen, then the planes ORed in); what they
; covered is a damage list per buffer, copied back from the twin lines the next time that buffer is drawn.  Graphics
; are baked into STE planes on first use (a hashed cache per kind) from their pixel-value planes through a routine per
; colour bank (assets.py: the pens' masks ORed into the planes by the 16 colour palette).
STRIDE = 256
GAME_X = 24				; (the window's first chunk when D802 is 0)
HW_MAX = 192				; D802 up to this moves the Shifter's window (the 512-pixel lines hold it and its bars)
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
FXSR = $80

Z_TEXT = G_Z80-$3000			; D000 codes, D400 attributes
Z_SCROLL = G_Z80-$2800			; D800 / D801: S, D802: the map rows' offset

STRIP_WORDS = 15			; a text row's strip: 15 chunks (14 and a 0 one) of 8 lines, then its opaque plane
STRIP_MASK = 8*STRIP_WORDS*8
STRIP_ROW = STRIP_MASK+8*STRIP_WORDS*2
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
 clr.b $ffff8265.w
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
 ifnd SIM			; (as Black Tiger: the STE loads the base into the video counter before the VBL, so the
 move.b flip_addr+1,$ffff8205.w	; base alone would show the frame one VBL later, under the fine scroll written now)
 move.b flip_addr+2,$ffff8207.w
 move.b flip_addr+3,$ffff8209.w
 endc
 move.b flip_fine,d0		; the fine scroll; the Shifter then reads a chunk more a line: the line width 4 words less
 move.b d0,$ffff8265.w
 move.b #48,d1
 tst.b d0
 beq.s .width
 subq.b #4,d1
.width:
 move.b d1,$ffff820f.w
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
 move.l draw_base,d0		; the video address: PIC_TOP lines above, the chunk of the window's offset
 sub.l #PIC_TOP*STRIDE,d0
 moveq #0,d1
 move.w cur_hw,d1
 move.b d1,d2
 and.b #15,d2
 move.b d2,flip_fine
 lsr.w #4,d1
 lsl.w #3,d1
 add.l d1,d0
 move.l d0,flip_addr
 move.w draw_idx,d0
 addq.b #1,d0
 move.b d0,frame_ready
 rts

; ------------------------------------------------------------------------------
; Background
; ------------------------------------------------------------------------------

; Bring the buffer draw_idx up to the scroll: restore the damage of its last frame; when the hardware window moved
; (D802), draw the columns that came into it and black those that went into the side bars (hw_strips); move its window
; by the vertical scroll since and draw the tiles of the map lines that came into its band.  draw_base = the window's
; first line (x 0 of the buffer).
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
 moveq #0,d1			; D802: the window's offset hw (up to HW_MAX), the rest (soft) moves the tiles
 move.b Z_SCROLL+2,d1
 move.w d1,cur_sy
 moveq #0,d0
 cmp.w #HW_MAX,d1
 bls.s .hw
 move.w d1,d0
 sub.w #HW_MAX,d0
 move.w #HW_MAX,d1
.hw:
 move.w d1,cur_hw
 move.w d0,cur_soft
 add.w #48,d1
 move.w d1,cur_wx
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
 lea ring_soft,a0
 move.w cur_soft,d1
 cmp.w (a0,d2.w),d1
 bne .full
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
 move.w ring_off2,d2
 lea ring_hw,a0
 move.w (a0,d2.w),d0
 cmp.w cur_hw,d0
 beq.s .same_hw
 move.w d0,old_hw
 move.w cur_hw,(a0,d2.w)
 move.w cur_S,new_S		; (the strips go over the band as it was drawn: the old S and top)
 lea ring_S,a0
 move.w (a0,d2.w),cur_S
 lea ring_top,a0
 move.w (a0,d2.w),cur_top
 bsr hw_strips
 move.w new_S,cur_S
.same_hw:
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
 move.w cur_top,d2		; (their line pairs: from top - 16)
 sub.w #16,d2
 bra.s .band
.back:
 neg.w d0			; back: S-16 .. S-16-d-1 (the band's bottom)
 move.w cur_S,d1
 sub.w #16,d1
 move.w cur_top,d2		; (from top + 272 - d)
 add.w #272,d2
 sub.w d0,d2
.band:
 movem.w d0-d1,-(sp)
 move.w d0,d1			; the line pairs that came into the band: their side bars black (they may hold what an
 move.w d2,d0			; earlier window drew there)
 bsr class_bars
 movem.w (sp)+,d0-d1
 bsr draw_band
.done:
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
 lea ring_bg,a0
 move.b cur_bg,(a0,d2.w)
 move.w ring_off2,d2
 lea ring_hw,a0
 move.w cur_hw,(a0,d2.w)
 lea ring_soft,a0
 move.w cur_soft,(a0,d2.w)
 lea ring_S,a0
 move.w cur_S,(a0,d2.w)
 lea ring_top,a0
 clr.w (a0,d2.w)
 clr.w cur_top
 move.w cur_S,d1
 sub.w #16,d1
 move.w #288,d0
 bsr draw_band
 moveq #0,d0			; the side bars of all line pairs black (the damage list is dropped)
 move.w #RING_H,d1
 bsr class_bars
 bra .done

; d0 = a line pair (any integer, modulo RING_H), d1 = pairs (1 .. RING_H): the side bars of the window cur_wx black
; on both lines of each pair.
class_bars:
 tst.w d1
 ble .out
 ext.l d0
 divs #RING_H,d0
 swap d0				; (the remainder)
 tst.w d0
 bpl.s .pos
 add.w #RING_H,d0
.pos:
 move.w d0,d2
 add.w d1,d2
 cmp.w #RING_H,d2
 ble.s .one
 movem.w d0-d2,-(sp)		; [c0, RING_H) and [0, c0 + n - RING_H)
 move.w #RING_H,d1
 sub.w d0,d1
 bsr.s .interval
 movem.w (sp)+,d0-d2
 sub.w #RING_H,d2
 move.w d2,d1
 moveq #0,d0
.one:
.interval:			; pairs d0 .. d0 + d1 - 1
 movem.w d0-d1,-(sp)
 bsr.s .lines
 movem.w (sp)+,d0-d1
 add.w #RING_H,d0
.lines:				; lines d0 .. d0 + d1 - 1: both bars
 movem.w d0-d1,-(sp)
 move.l ring_addr,d2
 ext.l d0
 lsl.l #8,d0
 add.l d0,d2
 move.l d2,-(sp)
 move.w cur_wx,d4
 sub.w #48,d4
 move.w cur_wx,d5
 bsr clear_span
 move.l (sp)+,d2
 move.w 2(sp),d1
 move.w cur_wx,d4
 add.w #224,d4
 move.w d4,d5
 add.w #48,d5
 bsr clear_span
 movem.w (sp)+,d0-d1
.out:
 rts

; The window moved from 48 + old_hw to cur_wx (buffer pixels) since the buffer was drawn: over the band (cur_S, cur_top
; as drawn) and the twins of its lines, the columns the new window has and the old one had not get the background
; (draw_band with strip_x0 .. strip_x1: only those columns of the tiles), and the side bars of the new window that
; were not the old one's turn black.  Equal widths: each difference is one interval.
hw_strips:
 move.w old_hw,d6
 add.w #48,d6			; o
 move.w cur_wx,d7		; n
 cmp.w d6,d7
 blt.s .left
 move.w d6,d0			; right: [max(n, o + 224), n + 224)
 add.w #224,d0
 cmp.w d7,d0
 bge.s .r1
 move.w d7,d0
.r1:
 move.w d7,d1
 add.w #224,d1
 bsr.s .enter
 move.w d7,d4			; the left bar: [max(o, n - 48), n)
 sub.w #48,d4
 cmp.w d6,d4
 bge.s .r2
 move.w d6,d4
.r2:
 move.w d7,d5
 bsr band_clear
 move.w d6,d4			; the right bar: [max(n + 224, o + 272), n + 272)
 add.w #272,d4
 move.w d7,d0
 add.w #224,d0
 cmp.w d0,d4
 bge.s .r3
 move.w d0,d4
.r3:
 move.w d7,d5
 add.w #272,d5
 bra band_clear
.left:
 move.w d7,d0			; left: [n, min(n + 224, o))
 move.w d7,d1
 add.w #224,d1
 cmp.w d6,d1
 ble.s .l1
 move.w d6,d1
.l1:
 bsr.s .enter
 move.w d7,d4			; the left bar: [n - 48, min(n, o - 48))
 sub.w #48,d4
 move.w d6,d5
 sub.w #48,d5
 cmp.w d7,d5
 ble.s .l2
 move.w d7,d5
.l2:
 bsr band_clear
 move.w d7,d4			; the right bar: [n + 224, min(n + 272, o + 224))
 add.w #224,d4
 move.w d6,d5
 add.w #224,d5
 move.w d7,d0
 add.w #272,d0
 cmp.w d0,d5
 ble.s .l3
 move.w d0,d5
.l3:
 bra band_clear
.enter:				; d0 .. d1: the columns that came into the window
 cmp.w d1,d0
 bge.s .none
 movem.l d6-d7,-(sp)
 move.w d0,strip_x0
 move.w d1,strip_x1
 st strip_mode
 move.w cur_S,d1
 sub.w #16,d1
 move.w #288,d0
 bsr draw_band
 sf strip_mode
 movem.l (sp)+,d6-d7
.none:
 rts

; d4 .. d5 (buffer pixels, d5 exclusive): black over the band (cur_top, from line 0) and the twins of its lines.
; Keeps d6, d7.
band_clear:
 cmp.w d5,d4
 bge.s .out
 move.w cur_top,d0		; the band: top - 16 .. top + 271
 sub.w #16,d0
 bpl.s .r1
 moveq #0,d0
.r1:
 move.w cur_top,d1
 add.w #271,d1
 bsr.s .range
 move.w cur_top,d0		; the twins of its lines below RING_H: + RING_H
 add.w #RING_H-16,d0
 move.w cur_top,d1
 add.w #271,d1
 cmp.w #RING_H-1,d1
 ble.s .r2
 move.w #RING_H-1,d1
.r2:
 add.w #RING_H,d1
 bsr.s .range
 move.w cur_top,d1		; of those from RING_H: - RING_H
 add.w #271-RING_H,d1
 bmi.s .out
 moveq #0,d0
.range:				; lines d0 .. d1
 movem.l d4-d7,-(sp)
 sub.w d0,d1
 addq.w #1,d1
 move.l ring_addr,d2
 ext.l d0
 lsl.l #8,d0
 add.l d0,d2
 bsr clear_span
 movem.l (sp)+,d4-d7
.out:
 rts

; d2 = a line's address (x 0), d1 = lines, d4 .. d5 = buffer pixels (d5 exclusive): black, plane by plane with the end
; masks of the first and the last word, 32 lines a burst.
clear_span:
 cmp.w d5,d4
 bge .out
 move.w d4,d0			; the first word and END1
 asr.w #4,d0
 move.w d5,d3			; the last word and END3
 subq.w #1,d3
 asr.w #4,d3
 sub.w d0,d3			; words - 1
 lsl.w #3,d0
 ext.l d0
 add.l d0,d2
 and.w #15,d4
 moveq #-1,d0
 lsr.w d4,d0
 subq.w #1,d5
 and.w #15,d5
 moveq #15,d6
 sub.w d5,d6
 moveq #-1,d5
 lsl.w d6,d5
 tst.w d3
 bne.s .wide
 and.w d5,d0
.wide:
 move.w d0,BLT_END1.w
 move.w #$ffff,BLT_END2.w
 move.w d5,BLT_END3.w
 move.w #8,BLT_DST_XINC.w
 move.w d3,d0
 lsl.w #3,d0
 neg.w d0
 add.w #STRIDE,d0
 move.w d0,BLT_DST_YINC.w
 addq.w #1,d3
 move.w d3,BLT_COUNT.w
 clr.w BLT_HOP_OP.w
 clr.b BLT_SKEW.w
 moveq #3,d4
.plane:
 move.l d2,a0
 move.w d1,d3
.burst:
 moveq #32,d0
 cmp.w d0,d3
 bge.s .n
 move.w d3,d0
.n:
 sub.w d0,d3
 move.l a0,BLT_DST_ADDR.w
 move.w d0,BLT_COUNT+2.w
 bsr blit_go_fill
 ext.l d0
 lsl.l #8,d0
 add.l d0,a0
 tst.w d3
 bne.s .burst
 addq.l #2,d2
 dbf d4,.plane
.out:
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
 bsr draw_cell
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
; the twin and (when it crosses line RING_H) the line RING_H above; in each of its two places on the line (the map
; row k at x = 32 + 32k + 256n - soft) that reaches the window (strip_mode: strip_x0 .. strip_x1).  Keeps all registers.
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
 add.w cur_top,d1
 bpl.s .p
 add.w #RING_H,d1
.p:
 cmp.w #RING_H,d1
 blo.s .q
 sub.w #RING_H,d1
.q:
 move.w d1,cell_line
 move.w cur_wx,d3		; the columns wanted: the window, or the strip
 move.w d3,d4
 add.w #224,d4
 tst.b strip_mode
 beq.s .want
 move.w strip_x0,d3
 move.w strip_x1,d4
.want:
 move.w d5,d2			; x = 32 + 32k - soft (n = 0), + 256 (n = 1)
 lsl.w #5,d2
 add.w #32,d2
 sub.w cur_soft,d2
 sub.l a1,a1			; (the tile: baked on its first place)
 bsr.s .place
 add.w #256,d2
 bsr.s .place
.out:
 movem.l (sp)+,d0-d7/a0-a6
 rts
.place:
 cmp.w d4,d2			; x < end and x + 32 > start
 bge .no
 move.w d2,d0
 add.w #32,d0
 cmp.w d3,d0
 ble .no
 move.w d2,dest_x
 move.l a1,d0
 bne.s .baked
 lea tile_black,a1
 tst.b cur_bg
 beq.s .baked
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
.baked:
 movem.l d2-d4,-(sp)
 move.l ring_addr,draw_base
 move.w cell_line,dest_y
 bsr tile_twice
 move.w cell_line,d0
 add.w #RING_H,d0
 move.w d0,dest_y
 bsr tile_twice
 cmp.w #RING_H-32,cell_line
 ble.s .two
 move.w cell_line,d0
 sub.w #RING_H,d0
 move.w d0,dest_y
 bsr tile_twice
.two:
 movem.l (sp)+,d2-d4
.no:
 rts

; The tile a1 at dest_x / dest_y: whole, and black in the side bars it reaches; or (strip_mode) only its columns in
; strip_x0 .. strip_x1 (part_blit).  Keeps a1.
tile_twice:
 move.l a1,-(sp)
 tst.b strip_mode
 beq.s .whole
 bsr part_blit
 bra .out
.whole:
 moveq #15,d0			; window and tile on 16-pixel groups (nearly always): a tile across the window's edge
 and.w cur_wx,d0		; is drawn as its inner chunk only, nothing in the side bar (it stays black)
 bne.s .full
 move.w dest_x,d0
 moveq #15,d1
 and.w d0,d1
 bne.s .full
 sub.w cur_wx,d0		; x - wx
 cmp.w #-16,d0
 beq.s .right_chunk
 cmp.w #224-16,d0
 bne.s .full
 moveq #0,d0			; the left chunk (the right one is in the right bar)
 bsr draw_tile_chunk
 bra .out
.right_chunk:
 moveq #1,d0			; the right chunk (the left one is in the left bar)
 bsr draw_tile_chunk
 bra .out
.full:
 bsr draw_tile
 bsr destination_line
 move.w dest_x,d4		; the left bar: [max(x, wx - 48), wx)
 move.w cur_wx,d5
 cmp.w d5,d4
 bge.s .right
 move.w d5,d0
 sub.w #48,d0
 cmp.w d0,d4
 bge.s .l
 move.w d0,d4
.l:
 moveq #32,d1
 move.l d2,-(sp)
 bsr clear_span
 move.l (sp)+,d2
.right:
 move.w cur_wx,d4		; the right bar: [wx + 224, min(x + 32, wx + 272))
 add.w #224,d4
 move.w dest_x,d5
 add.w #32,d5
 move.w cur_wx,d0
 add.w #272,d0
 cmp.w d0,d5
 ble.s .r
 move.w d0,d5
.r:
 moveq #32,d1
 bsr clear_span
.out:
 move.l (sp)+,a1
 rts

; The columns strip_x0 .. strip_x1 of the tile a1 at dest_x / dest_y, word by word: each destination word takes the
; tile's two words around it (FXSR, skew) under the mask of its pixels in both; 4 planes x 32 lines.
part_blit:
 move.w strip_x0,d6		; x0 = max(strip_x0, x), x1 = min(strip_x1, x + 32)
 move.w dest_x,d0
 cmp.w d0,d6
 bge.s .a
 move.w d0,d6
.a:
 move.w strip_x1,d7
 add.w #32,d0
 cmp.w d0,d7
 ble.s .b
 move.w d0,d7
.b:
 cmp.w d7,d6
 bge .out
 move.w #2,BLT_SRC_XINC.w
 move.w #2,BLT_SRC_YINC.w
 move.w #STRIDE,BLT_DST_YINC.w
 move.w #1,BLT_COUNT.w
 move.w #$0203,BLT_HOP_OP.w
 bsr destination_line
 move.l d2,a3			; the line
 move.w d6,d5
 and.w #$fff0,d5		; the destination word's first pixel
.word:
 move.w d6,d0			; p0 = max(x0, w), p1 = min(x1, w + 16): the mask
 cmp.w d5,d0
 bge.s .c
 move.w d5,d0
.c:
 move.w d5,d1
 add.w #16,d1
 cmp.w d7,d1
 ble.s .d
 move.w d7,d1
.d:
 sub.w d5,d0
 sub.w d5,d1
 moveq #-1,d2
 lsr.w d0,d2
 moveq #16,d0
 sub.w d1,d0
 moveq #-1,d1
 lsl.w d0,d1
 and.w d1,d2
 move.w d2,BLT_END1.w
 move.w d5,d0			; o = w - x: the tile's words o / 16 and the next, shifted left by o & 15
 sub.w dest_x,d0
 move.w d0,d1
 asr.w #4,d1
 and.w #15,d0
 bne.s .shifted
 subq.w #1,d1
.shifted:
 neg.w d0
 and.w #15,d0
 or.b #$80,d0			; FXSR
 move.b d0,BLT_SKEW.w
 add.w d1,d1
 lea (a1,d1.w),a2
 move.w d5,d0
 asr.w #4,d0
 lsl.w #3,d0
 lea (a3,d0.w),a4
 moveq #3,d3
.plane:
 move.l a2,BLT_SRC_ADDR.w
 move.l a4,BLT_DST_ADDR.w
 move.w #32,BLT_COUNT+2.w
 bsr blit_go
 lea 128(a2),a2
 addq.l #2,a4
 dbf d3,.plane
 add.w #16,d5
 cmp.w d7,d5
 blt .word
.out:
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
 move.b tile_ctrl+1,BLT_SKEW.w
.plane:
 move.l a1,BLT_SRC_ADDR.w
 move.l d2,BLT_DST_ADDR.w
 move.w #32,BLT_COUNT+2.w
 bsr blit_go
 lea 128(a1),a1
 addq.l #2,d2
 dbf d3,.plane
 rts

; Chunk d0 (0: the left, 1: the right) of the tile a1 (4 planes x 32 rows x 2 words) at dest_x / dest_y, both on
; 16-pixel groups: a copy pass a plane, a word a line.
draw_tile_chunk:
 move.w #$ffff,BLT_END1.w
 move.w #$ffff,BLT_END2.w
 move.w #$ffff,BLT_END3.w
 move.w #2,BLT_SRC_XINC.w
 move.w #4,BLT_SRC_YINC.w	; (the row's other word skipped)
 move.w #8,BLT_DST_XINC.w
 move.w #STRIDE,BLT_DST_YINC.w
 move.w #$0203,BLT_HOP_OP.w
 clr.b BLT_SKEW.w
 move.w d0,-(sp)
 bsr destination
 move.w (sp)+,d0
 move.l a1,a0
 tst.w d0
 beq.s .left
 addq.l #2,a0
 addq.l #8,d2
.left:
 moveq #3,d3
.plane:
 move.l a0,BLT_SRC_ADDR.w
 move.l d2,BLT_DST_ADDR.w
 move.w #1,BLT_COUNT.w
 move.w #32,BLT_COUNT+2.w
 bsr blit_go
 lea 128(a0),a0
 addq.l #2,d2
 dbf d3,.plane
 rts

; d2 = the destination chunk of dest_x (buffer pixels) / dest_y.
destination:
 bsr.s destination_line
 move.w dest_x,d0
 asr.w #4,d0
 lsl.w #3,d0
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
 move.w d4,BLT_SRC_YINC.w
 move.w d4,BLT_DST_YINC.w
 move.w d2,BLT_COUNT.w
 move.l d1,BLT_SRC_ADDR.w
 move.l d0,BLT_DST_ADDR.w
 move.w d3,BLT_COUNT+2.w
 bsr blit_go_copy
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
 lea sprite_buffer+128*4,a0
 moveq #127,d7
.scan:				; (the culling in registers: most entries are off the screen)
 subq.l #4,a0
 move.b 2(a0),d4		; visible lines: raw y 1-239 (x = raw y - 16 in -15..223)
 subq.b #1,d4
 cmp.b #238,d4
 bhi.s .skip
 btst #5,1(a0)			; the top row: 240 - raw x (bit 5 clear: -15..240), 496 - raw x (set: visible
 beq.s .visible			; below 256, raw x 241-255)
 cmp.b #240,3(a0)
 bhi.s .visible
.skip:
 dbf d7,.scan
 rts
.visible:
 move.l a0,spr_ptr
 move.w d7,spr_left
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
 move.w d4,spr_sx
 add.w cur_wx,d4
 move.w d4,dest_x		; (buffer pixels)
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
 move.w spr_sx,d0
 cmp.w #208,d0
 bhi.s .edge			; (unsigned: left of the window too)
 bsr sprite_part
 bra.s .next
.edge:				; across the window's left or right edge
 moveq #15,d1
 and.w cur_wx,d1
 bne.s .unaligned
 bsr sprite_edge		; (the edges on 16-pixel groups: only the inner word)
 bra.s .next
.unaligned:			; (the window at a fine offset, D802 not a multiple of 16: the edges inside a word)
 bsr sprite_part
 move.w spr_sx,d0		; drawn whole: its 16 pixels beside the window black again (the screen shows the side
 bmi.s .left			; bars; the damage list restores them from their black twins)
 move.w cur_wx,d4
 add.w #224,d4
 bra.s .side
.left:
 move.w cur_wx,d4
 sub.w #16,d4
.side:
 move.w d4,d5
 add.w #16,d5
 bsr destination_line
 moveq #16,d1
 bsr clear_span
.next:
 move.l spr_ptr,a0
 move.w spr_left,d7
 bra .skip

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

; A sprite across the window's left or right edge (spr_sx -15 .. -1 or 209 .. 223, always shifted) when the window
; starts on a 16-pixel group (cur_wx & 15 = 0): only its inner word, and only that word's damage; the side bars are
; not touched.  a1 = the baked sprite at dest_x / dest_y.
sprite_edge:
 bsr destination
 moveq #2,d5			; (right edge: the first word)
 tst.w spr_sx
 bpl.s .right
 moveq #1,d5			; (left edge: the second word)
 addq.l #8,d2
.right:
 move.w dest_y,d0
 add.w cur_top,d0
 moveq #16,d1
 moveq #4,d3
 bsr add_damage
 move.w dest_x,d3
 and.w #15,d3
 move.w #2,BLT_SRC_XINC.w
 move.w #$0203,BLT_HOP_OP.w
 move.w #1,BLT_COUNT.w
 move.w #2,BLT_DST_YINC.w
 move.b d3,d0			; the skew; left: FXSR and the source Y increment 0 (two reads a line advance one word)
 move.w #2,BLT_SRC_YINC.w
 cmp.w #1,d5
 bne.s .skew
 or.b #FXSR,d0
 clr.w BLT_SRC_YINC.w
.skew:
 move.b d0,BLT_SKEW.w
 moveq #0,d0
 move.w spr_shape_n,d0
 add.w d0,d0
 lea spr_shape,a0
 move.w (a0,d0.w),d0
 cmp.w #$ffff,d0
 beq.s .any
 move.w d0,spr_pcode
 move.l a1,BLT_SRC_ADDR.w
 lsl.l #4,d0
 or.w d3,d0
 lsl.l #3,d0
 lea spr_code_tab,a0
 tst.l (a0,d0.l)
 beq.s .out
 move.l 4(a0,d0.l),a0
 bsr.s clip_part
.out:
 move.w #2,BLT_SRC_YINC.w
 rts
.any:				; (a shape without generated code: its rows in order, the masks from its opaque rows)
 lea 128(a1),a2
 moveq #16,d6
 sub.w d3,d6
 moveq #15,d4
.row:
 move.w (a2)+,d0
 beq.s .skip
 cmp.w #1,d5
 beq.s .l
 lsr.w d3,d0			; right: the first word, mask >> shift
 bra.s .m
.l:
 lsl.w d6,d0			; left: the second word, mask << (16 - shift)
.m:
 move.w d0,BLT_END1.w
 move.l a1,BLT_SRC_ADDR.w
 move.l d2,BLT_DST_ADDR.w
 move.w #4,BLT_COUNT+2.w
 move.b #$c0,BLT_CTRL.w
.skip:
 addq.l #8,a1
 add.l #STRIDE,d2
 dbf d4,.row
 bra.s .out

; The inner word of an edge sprite with generated code (sprite_edge has set the Blitter: one word a line, the skew),
; d2 = its address, d5 = 1 left / 2 right.  Right: the first word, (previous source word : this one) >> skew under the
; stream's END1 (the previous word's bits fall outside it).  Left: the second word, FXSR (this source word : the next)
; >> skew under the stream's END3.  The masks from the stream (a0), the lines from spr_plan; full addresses (a 64 KB
; crossing is no matter).
clip_part:
 move.l d2,a1
 move.l a0,a2
 moveq #0,d0
 move.w spr_pcode,d0
 lsl.l #2,d0
 lea spr_plan_offsets,a0
 move.l (a0,d0.l),d0
 lea spr_plan,a0
 add.l d0,a0
 moveq #1,d4
.group:
 move.w (a0)+,d1
 beq.s .done
 move.w (a2)+,d0		; END1
 move.w (a2)+,d3		; END3
 cmp.w #1,d5
 bne.s .m
 move.w d3,d0
.m:
 move.w d0,BLT_END1.w
 tst.w d4
 beq.s .rows
 moveq #0,d4
 addq.l #2,a2			; (the control word of the first row)
.rows:
 subq.w #1,d1
.row:
 adda.w (a0)+,a1
 move.l a1,BLT_DST_ADDR.w
 move.w #4,BLT_COUNT+2.w
 move.b #$c0,BLT_CTRL.w
 dbf d1,.row
 bra.s .group
.done:
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
 tst.b fg_dirty			; the rows whose cells changed: their strips again
 beq.s .draw
 sf fg_dirty
 moveq #0,d6
.compose:
 lea fg_row_dirty,a0
 tst.b (a0,d6.w)
 beq.s .clean
 clr.b (a0,d6.w)
 bsr fg_compose
.clean:
 addq.w #1,d6
 cmp.w #32,d6
 blo.s .compose
.draw:
 tst.b Z_LATCH			; (bit 7: the text layer on)
 bpl .off
 move.w cur_wx,d7
 and.w #15,d7			; the skew: the window's pixel offset in its first word
 moveq #0,d6
.row:
 lea fg_rows,a3
 moveq #0,d4
 move.b (a3,d6.w),d4		; the first and the last chunk with characters
 cmp.b #$ff,d4
 beq .no_row
 moveq #0,d3
 move.b 32(a3,d6.w),d3
 sub.w d4,d3			; source words - 1
 tst.w d7
 beq.s .aligned
 addq.w #1,d3			; (shifted: a word more, the next strip word is 0)
.aligned:
 move.w d6,d0
 lsl.w #3,d0
 neg.w d0
 add.w #248,d0			; y
 moveq #0,d2
 move.w d0,d2
 lsl.l #8,d2
 add.l draw_base,d2
 move.w d4,d1			; the destination: the word of the window's pixel 16 * first
 lsl.w #4,d1
 add.w cur_wx,d1
 asr.w #4,d1
 lsl.w #3,d1
 add.w d1,d2
 move.l d2,a4
 movem.l d0/d2-d3,-(sp)		; damage: the row's words, in four bursts of 2 lines (HOG Blitter: short)
 add.w cur_top,d0
 addq.w #1,d3
 lsl.w #2,d3
 moveq #2,d1
 moveq #3,d5
.burst:
 bsr add_damage
 add.l #2*STRIDE,d2
 addq.w #2,d0
 dbf d5,.burst
 movem.l (sp)+,d0/d2-d3
 ; the Blitter as stefastbobs2 draws its bobs (fg_pieces): copy passes (HOP 2, OP 3) whose end masks are the opaque
 ; pixels, a piece of one or two chunks a line, its four planes in one pass (destination X increment 8, Y count 4, the Y
 ; increment back to the next plane), the planes stored in pass order (the source runs on), the skew the window's.
 move.w #2,BLT_SRC_XINC.w
 move.w #2,BLT_SRC_YINC.w
 move.w #8,BLT_DST_XINC.w
 move.w #$0203,BLT_HOP_OP.w
 move.w d6,d0
 mulu #PIECE_ROW,d0
 lea fg_pieces,a0
 add.l d0,a0
 movem.l d6-d7,-(sp)
 move.w d6,d2			; the row's shifted end masks (fg_smasks)
 mulu #SMASK_ROW,d2
 lea fg_smasks,a2
 add.l d2,a2
 move.w d7,d0			; the skew
 move.w (a0)+,d7
 move.w (a0)+,d1
 move.w d7,d2
 add.w d1,d2
 mulu #6,d2
 lea (a0,d2.w),a1
 move.l a1,BLT_SRC_ADDR.w	; (it runs on from piece to piece)
 lea BLT_END1.w,a5		; END1, END2 at 2(a5), END3 at 4(a5)
 lea BLT_DST_ADDR.w,a6
 lea BLT_COUNT+2.w,a3		; Y count, start at 4(a3)
 moveq #4,d5			; the four planes
 moveq #$ffffffc0,d6		; BUSY + HOG
 tst.w d0
 beq .fp_aligned
 ; shifted: a piece of c chunks covers c + 1 destination words, NFSR (c words read), its masks shifted here
 move.b d0,d2
 or.b #$40,d2
 move.b d2,BLT_SKEW.w
 move.w 2(sp),d2		; (the row) its masks shifted for this skew already?
 lea fg_sskew,a1
 cmp.b (a1,d2.w),d0
 beq.s .fp_cached
 move.b d0,(a1,d2.w)
 bsr fg_shift_masks
.fp_cached:
 subq.w #1,d7
 bmi.s .fp_s_ones
 move.w #3,BLT_COUNT.w
 move.w #-14,BLT_DST_YINC.w
.fp_s_two:
 move.l (a2)+,(a5)		; END1, END2 (fg_shift_masks)
 move.w (a2)+,4(a5)		; END3
 addq.l #4,a0
 add.w (a0)+,a4
 move.l a4,(a6)
 move.w d5,(a3)
 move.b d6,4(a3)
 dbf d7,.fp_s_two
.fp_s_ones:
 subq.w #1,d1
 bmi .fp_drawn
 move.w #2,BLT_COUNT.w
 move.w #-6,BLT_DST_YINC.w
.fp_s_one:
 move.w (a2)+,(a5)		; END1
 move.w (a2)+,4(a5)		; END3
 addq.l #4,a0
 add.w (a0)+,a4
 move.l a4,(a6)
 move.w d5,(a3)
 move.b d6,4(a3)
 dbf d1,.fp_s_one
 bra.s .fp_drawn
.fp_aligned:
 clr.b BLT_SKEW.w
 subq.w #1,d7
 bmi.s .fp_a_ones
 move.w #2,BLT_COUNT.w
 move.w #-6,BLT_DST_YINC.w
.fp_a_two:
 move.w (a0)+,(a5)
 move.w (a0)+,4(a5)
 add.w (a0)+,a4
 move.l a4,(a6)
 move.w d5,(a3)
 move.b d6,4(a3)
 dbf d7,.fp_a_two
.fp_a_ones:
 subq.w #1,d1
 bmi.s .fp_drawn
 move.w #1,BLT_COUNT.w
 move.w #2,BLT_DST_YINC.w
.fp_a_one:
 move.w (a0)+,(a5)
 addq.l #2,a0
 add.w (a0)+,a4
 move.l a4,(a6)
 move.w d5,(a3)
 move.b d6,4(a3)
 dbf d1,.fp_a_one
.fp_drawn:
 move.w #$ffff,BLT_END2.w	; (as the other passes expect it)
 movem.l (sp)+,d6-d7
.no_row:
 addq.w #1,d6
 cmp.w #32,d6
 blo .row
.off:
 rts

; d6 = a text row: its strip made again from its baked characters (fg_ptr), with movep.l at byte positions: 8 lines of
; STRIP_WORDS chunks (the 224 pixels of the window and a 0 chunk for the shifted blits), then the opaque pixels as one
; plane; fg_rows gets the first and the last chunk with characters ($ff: none).  Keeps d6.
fg_compose:
 move.w d6,d0
 mulu #STRIP_ROW,d0
 lea fg_strips,a2
 add.l d0,a2
 move.l a2,a0
 move.w #STRIP_ROW/4-1,d0
.clear:
 clr.l (a0)+
 dbf d0,.clear
 moveq #-1,d4			; the first chunk ($ff), the last
 moveq #0,d5
 moveq #2,d3			; the column c (x = 8c - 16)
.cell:
 move.w d3,d0
 lsl.w #5,d0
 add.w d6,d0
 lsl.w #2,d0
 lea fg_ptr,a0
 move.l (a0,d0.w),d0
 beq .empty
 move.l d0,a0
 move.w d3,d1
 subq.w #2,d1
 move.w d1,d2
 lsr.w #1,d1			; the chunk
 and.w #1,d2			; the byte in it
 cmp.b d1,d4
 bls.s .known
 move.b d1,d4
.known:
 move.b d1,d5
 move.w d1,d0
 lsl.w #3,d0
 add.w d2,d0
 lea (a2,d0.w),a1
 add.w d1,d1
 add.w d1,d2
 lea STRIP_MASK(a2),a3
 add.w d2,a3
 rept 8
 move.l (a0)+,d1		; the keep mask
 move.l (a0)+,d0		; the plane bytes
 movep.l d0,REPTN*STRIP_WORDS*8(a1)
 not.b d1
 move.b d1,REPTN*STRIP_WORDS*2(a3)
 endr
.empty:
 addq.w #1,d3
 cmp.w #30,d3
 blo .cell
 lea fg_rows,a0
 move.b d4,(a0,d6.w)
 move.b d5,32(a0,d6.w)
 bra fg_pieces_build

; fg_shift_masks: a row's end masks for skew d0 (1-15) at a2 (fg_smasks), from its pieces' mask words at a0 (d7.w
; two-chunk pieces, then d1.w one-chunk ones): END1 = 1 >> s, END2 = (1:2) >> s, END3 = 2 << (16 - s) (6 bytes); a
; one-chunk piece END1, END3 (4 bytes).  draw_foreground keeps them per row while the skew stays (fg_sskew).  Keeps
; all registers.
fg_shift_masks:
 movem.l d1-d4/d7/a0/a2,-(sp)
 moveq #16,d3
 sub.w d0,d3
 subq.w #1,d7
 bmi.s .ones
.two:
 move.l (a0)+,d2		; mask words 1, 2
 move.w d2,d4
 lsr.l d0,d2			; END1 (high word), END2 (low)
 move.l d2,(a2)+
 lsl.w d3,d4
 move.w d4,(a2)+		; END3
 addq.l #2,a0			; (the step)
 dbf d7,.two
.ones:
 subq.w #1,d1
 bmi.s .done
.one:
 move.l (a0)+,d2		; mask word, 0
 lsr.l d0,d2			; END1 (high), END3 (low)
 move.l d2,(a2)+
 addq.l #2,a0
 dbf d1,.one
.done:
 movem.l (sp)+,d1-d4/d7/a0/a2
 rts

; fg_pieces_build: row d6's strip (fg_compose; chunks fg_rows .. 32+fg_rows) as stefastbobs2's bob pieces in
; fg_pieces + d6 * PIECE_ROW: a line's opaque chunks in pieces of two (or one) from the left, an entry n2, n1, the
; two-chunk pieces (mask words 1, 2, destination step), the one-chunk ones (mask word, 0, destination step), then the
; pieces' planes in pass order (plane 0's words, plane 1's ...).  A step from the row's first chunk (plane 0, line 0;
; chunk j lands on destination words j and j + 1) and from the last piece.  Keeps d6.
PIECE_ROW = 1600			; at most 8 x 14 chunks: 112 x (8 + 6) + 4
SMASK_ROW = 112*6			; fg_smasks: a row's end masks for the window's skew (fg_shift_masks)
fg_pieces_build:
 lea fg_sskew,a0		; (its shifted masks are old now)
 clr.b (a0,d6.w)
 movem.l d6,-(sp)
 move.w d6,d0
 mulu #STRIP_ROW,d0
 lea fg_strips,a2
 add.l d0,a2			; the strip
 move.w d6,d0
 mulu #PIECE_ROW,d0
 lea fg_pieces,a6
 add.l d0,a6			; the entry
 lea fg_rows,a0
 moveq #0,d4
 move.b (a0,d6.w),d4		; the first chunk
 moveq #0,d2
 move.b 32(a0,d6.w),d2		; the last
 clr.w fg_n2
 clr.w fg_n1
 lea fg_tmp,a5			; the pieces: c, mask 1, mask 2, the plane words' offset in the strip, destination offset
 cmp.b #$ff,d4
 beq .listed
 lea STRIP_MASK(a2),a1		; line 0's mask words
 moveq #0,d3			; the line
.line:
 move.w d4,d5			; the chunk
.chunk:
 cmp.w d2,d5
 bhi.s .line_end
 move.w d5,d0
 add.w d0,d0
 move.w (a1,d0.w),d1
 beq.s .empty
 cmp.w d2,d5
 beq.s .single
 tst.w 2(a1,d0.w)
 beq.s .single
 move.w #2,(a5)+
 move.w d1,(a5)+
 move.w 2(a1,d0.w),(a5)+
 addq.w #1,fg_n2
 bra.s .place
.single:
 move.w #1,(a5)+
 move.w d1,(a5)+
 clr.w (a5)+
 addq.w #1,fg_n1
.place:
 move.w d3,d1			; the plane words: line * STRIP_WORDS * 8 + chunk * 8
 mulu #STRIP_WORDS*8,d1
 move.w d5,d0
 lsl.w #3,d0
 add.w d0,d1
 move.w d1,(a5)+
 move.w d3,d1			; destination: line * STRIDE + (chunk - first) * 8
 mulu #STRIDE,d1
 move.w d5,d0
 sub.w d4,d0
 lsl.w #3,d0
 add.w d0,d1
 move.w d1,(a5)+
 add.w -10(a5),d5
 bra.s .chunk
.empty:
 addq.w #1,d5
 bra.s .chunk
.line_end:
 lea STRIP_WORDS*2(a1),a1
 addq.w #1,d3
 cmp.w #8,d3
 blo.s .line
.listed:
 move.l a5,fg_tmp_end
 move.w fg_n2,(a6)+
 move.w fg_n1,(a6)+
 move.w fg_n2,d0			; the data after the pieces
 add.w fg_n1,d0
 mulu #6,d0
 lea (a6,d0.w),a3
 moveq #0,d7			; the last piece's destination
 moveq #2,d4			; two-chunk pieces, then one-chunk ones
.kind:
 lea fg_tmp,a5
.piece:
 cmp.l fg_tmp_end,a5
 bhs.s .kind_end
 cmp.w (a5),d4
 bne.s .other
 move.w 2(a5),(a6)+		; mask words
 move.w 4(a5),(a6)+
 move.w 8(a5),d1
 move.w d1,d5
 sub.w d7,d1
 move.w d1,(a6)+		; destination step
 move.w d5,d7
 move.l a2,a0			; the planes: interleaved in the strip, chunk after chunk
 add.w 6(a5),a0
 move.w (a0),(a3)+
 move.w 2(a0),(a3)+
 move.w 4(a0),(a3)+
 move.w 6(a0),(a3)+
 cmp.w #2,d4
 bne.s .other
 ; two chunks: plane p's two words together
 lea -8(a3),a3
 move.w (a0),(a3)+
 move.w 8(a0),(a3)+
 move.w 2(a0),(a3)+
 move.w 10(a0),(a3)+
 move.w 4(a0),(a3)+
 move.w 12(a0),(a3)+
 move.w 6(a0),(a3)+
 move.w 14(a0),(a3)+
.other:
 lea 10(a5),a5
 bra.s .piece
.kind_end:
 subq.w #1,d4
 bne.s .kind
 movem.l (sp)+,d6
 rts

; d6 = the cell: fg_ptr[cell] = its baked character or 0 (blank, or outside the window).  Keeps d6.
fg_cell:
 move.w d6,d0			; (its row's strip is made again)
 and.w #31,d0
 lea fg_row_dirty,a0
 st (a0,d0.w)
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
fg_rows: ds.b 64
fg_row_dirty: ds.b 32
fg_strips: ds.b 32*STRIP_ROW
fg_pieces: ds.b 32*PIECE_ROW		; the rows' strips as bob pieces (fg_pieces_build)
fg_tmp: ds.b 8*14*10
fg_tmp_end: ds.l 1
fg_n2: ds.w 1
fg_n1: ds.w 1
ring_valid: ds.b 4
ring_bg: ds.b 4
ring_top: ds.w 3
ring_S: ds.w 3
ring_hw: ds.w 3
ring_soft: ds.w 3
ring_off2: ds.w 1
ring_addr: ds.l 1
cur_S: ds.w 1
cur_sy: ds.w 1
cur_hw: ds.w 1
cur_soft: ds.w 1
cur_wx: ds.w 1
old_hw: ds.w 1
new_S: ds.w 1
strip_x0: ds.w 1
strip_x1: ds.w 1
cur_top: ds.w 1
scroll_d: ds.w 1
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
fg_sskew: ds.b 32		; a row's skew of its fg_smasks (0: none)
	even
fg_smasks: ds.b 32*SMASK_ROW
spr_left: ds.w 1		; (draw_sprites: the entries left to scan)
spr_shape_n: ds.w 1
spr_sx: ds.w 1
spr_pcode: ds.w 1
draw_idx: ds.w 1
shown_idx: ds.w 1
prev_idx: ds.w 1
ring_base: ds.l 3
draw_base: ds.l 1
flip_addr: ds.l 1
flip_fine: ds.b 1
 even
shown_pal: ds.w 16
tile_pool: ds.b TILE_POOL
spr_pool: ds.b SPR_POOL
chr_pool: ds.b CHR_POOL
screen_area: ds.b 3*RING_SIZE+256
 section text,code
