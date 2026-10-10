; Whole tiles and objects draw into guarded screens; visible window is 224x256.
STRIDE = 256
GAME_X = 24
; The three display buffers are virtual screens scrolled by the video address, as in stedaimakaimura: buffer line l and
; l+RING_H always hold the same background, so the 256 shown lines (and 16 guard lines above and below them for whole
; sprites) are contiguous wherever the window is.  The 288 lines in use are 288 of the 320 line pairs; whole tiles at the
; band's edges overhang into the 32 others.  Lines -16 .. 2*RING_H+15 exist.
RING_H = 320
RING_ABOVE = 16
RING_LINES = RING_ABOVE+2*RING_H+16
RING_SIZE = RING_LINES*STRIDE
DMG_MAX = 400				; damage rectangles a frame (12 bytes: destination, source, words, lines)
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
 move.l d0,clean_base
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
 move.w #STRIDE,dest_stride
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
 st bg_full
 st fg_full
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
 addq.w #1,dbg_c2
 bsr bg_scan
 bsr ring_update
 bsr draw_sprites
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

; a0 = a line, d0 = segments of 32 lines - 1: the chunk columns beside the window (where whole sprites and tiles reach)
; are cleared, in bursts of 32 lines (the border timers).
clear_margins:
 move.w #$ffff,BLT_END1.w
 move.w #$ffff,BLT_END2.w
 move.w #$ffff,BLT_END3.w
 move.w #2,BLT_DST_XINC.w
 move.w #256-6,BLT_DST_YINC.w
 move.w #4,BLT_COUNT.w
 clr.w BLT_HOP_OP.w
 clr.b BLT_SKEW.w
 move.l a0,a1
 lea GAME_X-8(a0),a0
 bsr.s .column
 lea GAME_X+112(a1),a0
.column:
 move.w d0,d1
.segment:
 move.l a0,BLT_DST_ADDR.w
 move.w #32,BLT_COUNT+2.w
 move.b #$80,BLT_CTRL.w
.wait:
 btst #7,BLT_CTRL.w
 bne .wait
 lea 32*256(a0),a0
 dbf d1,.segment
 rts

; Hash caches: tag (long with object type), pointer. Pools roll over together.
; d0=code+attribute*256, d1=kind (0 tile,1 sprite,2 char). Returns a1 baked planes.
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
 cmp.w #2,d1
 bne.s .hit
 lea 64(a1),a1
.hit:
 movem.l (sp)+,d2-d3/a2
 rts
.miss:
 movem.l (sp)+,d2-d3/a2
get_object_bake:
 movem.l d0-d7/a0/a2-a6,-(sp)
 and.l #$ffff,d0
 move.w d0,obj_key
 move.w d1,obj_kind
 swap d1
 or.l d1,d0
 move.l d0,obj_tag
 move.w d0,d2
 move.w d2,d3
 lsr.w #4,d3
 eor.w d3,d2
 and.w #$fff,d2
 lsl.w #3,d2
 lea cache,a2
 moveq #0,d3
 move.w obj_kind,d3
 mulu #32768,d3
 add.l d3,a2
 add.w d2,a2
 move.l a2,cache_slot
 cmp.l (a2),d0
 bne .bake
 move.l 4(a2),a1
 move.l a1,d2
 bne .cached
.bake:
 addq.l #1,cache_misses
 move.l pool_ptr,d2
 bne .allocated
 move.l #pool,d2
 move.l d2,pool_ptr
.allocated:
 cmp.l #pool+POOL_SIZE-128,d2
 blo .room
 addq.w #1,pool_epoch
 lea cache,a0
 move.w #3*4096*8/4-1,d3
.clear:
 clr.l (a0)+
 dbf d3,.clear
 move.l #pool,d2
.room:
 move.l d2,baked_ptr
 move.l d2,a1
 add.l #128,d2
 move.l d2,pool_ptr
 move.l obj_tag,(a2)
 move.l a1,4(a2)
 ; Decode code/colour/raw flips from the packed arcade attribute.
 moveq #0,d0
 move.w obj_key,d0
 move.w d0,d2
 lsr.w #8,d2
 move.w d2,d3
 and.w #$c0,d3
 lsl.w #2,d3
 and.w #255,d0
 or.w d3,d0
 move.w d0,obj_code
 move.w obj_kind,d1
 cmp.w #1,d1
 beq .sprite
 move.w d2,d3
 lsr.w #4,d3
 and.w #3,d3
 move.w d3,obj_flip
 and.w #15,d2
 cmp.w #2,d1
 beq .char
 lsl.w #3,d2
 lea cmap,a5
 add.w d2,a5
 lea tile_masks,a4
 lsl.l #8,d0
 add.l d0,a4
 move.w #8,obj_pens
 move.w #16,obj_height
 clr.w obj_order
 bra .rows
.char:
 lsl.w #2,d2
 lea cmap+192,a5
 add.w d2,a5
 lea chr_masks,a4
 lsl.l #6,d0
 add.l d0,a4
 move.w #4,obj_pens
 move.w #8,obj_height
 clr.w obj_order
 bra .rows
.sprite:
 ; Sprite colour is bits 4/5, flips bits 2/3; screen row flip is raw X.
 move.w d2,d3
 lsr.w #2,d3
 and.w #3,d3
 move.w d3,obj_flip
 lsr.w #4,d2
 and.w #3,d2
 lsl.w #4,d2
 lea cmap+128,a5
 add.w d2,a5
 lea spr_masks,a4
 lsl.l #8,d0
 add.l d0,d0
 add.l d0,a4
 move.w #16,obj_pens
 move.w #16,obj_height
 moveq #1,d0
 move.w d0,obj_order
 moveq #0,d0
 move.w obj_code,d0
 lsl.w #2,d0
 or.w d3,d0
 move.w d0,obj_pcode
 lsl.l #4,d0
 lea spr_order,a3
 add.l d0,a3
.rows:
 clr.w obj_row
.row:
 move.w obj_row,d0
 tst.w obj_order
 beq .no_order
 moveq #0,d0
 move.b (a3)+,d0
.no_order:
 btst #0,obj_flip+1
 beq .forward
 move.w obj_height,d1
 subq.w #1,d1
 sub.w d0,d1
 move.w d1,d0
.forward:
 mulu obj_pens,d0
 add.w d0,d0
 lea (a4,d0.w),a0
 moveq #0,d3
 moveq #0,d4
 moveq #0,d5
 moveq #0,d6
 moveq #0,d2
.pen:
 moveq #0,d7
 move.w (a0)+,d7
 btst #1,obj_flip+1
 beq .normal
 ; Mirror words using a byte reversal table. 8px chars shift back to MSB.
 move.w d7,d0
 and.w #255,d0
 lea reverse_bits,a6
 move.b (a6,d0.w),d1
 lsl.w #8,d1
 lsr.w #8,d7
 move.b (a6,d7.w),d1
 move.w d1,d7
 cmp.w #8,obj_height
 bne .normal
 lsl.w #8,d7
.normal:
 moveq #0,d0
 move.b (a5,d2.w),d0
 lsl.w #2,d0
 lea orp_tab,a6
 move.l (a6,d0.w),a6
 jsr (a6)
 addq.w #1,d2
 cmp.w obj_pens,d2
 blo .pen
 ; Tiles/chars plane-major for rectangle/row drawing. Sprites row-major
 ; in mask-group order for the automatically advancing Blitter source.
 tst.w obj_order
 beq .planes
 movem.w d3-d6,(a1)
 addq.l #8,a1
 bra .row_done
.planes:
 move.w obj_height,d0
 add.w d0,d0
 move.w d3,(a1)
 move.w d4,(a1,d0.w)
 add.w d0,d0
 move.w d5,(a1,d0.w)
 move.w obj_height,d0
 mulu #6,d0
 move.w d6,(a1,d0.w)
 addq.l #2,a1
.row_done:
 addq.w #1,obj_row
 move.w obj_row,d0
 cmp.w obj_height,d0
 blo .row
 move.l baked_ptr,a1
 cmp.w #2,obj_kind
 bne.s .cached
 bsr char_convert
.cached:
 cmp.w #2,obj_kind		; (characters: the movep form after the planes)
 bne.s .ret
 lea 64(a1),a1
.ret:
 movem.l (sp)+,d0-d7/a0/a2-a6
 rts

; a1 = a character's planes (plane-major, 8 rows, the pixels in the high bytes): 64(a1) gets 8 rows of (the keep mask,
; the four plane bytes masked by the opaque pixels) as longs for movep.l.  The opaque pixels: chr_opaque, left position.
char_convert:
 moveq #0,d0
 move.w obj_code,d0
 lsl.w #2,d0
 or.w obj_flip,d0
 lsl.l #5,d0
 lea chr_opaque,a0
 add.l d0,a0
 lea 64(a1),a2
 move.l a1,a3
 moveq #7,d7
.row:
 move.b (a0),d1			; opaque pixels
 addq.l #2,a0
 move.b d1,d4
 lsl.w #8,d4
 move.b d1,d4
 move.w d4,d3
 swap d4
 move.w d3,d4			; opaque, in each byte
 moveq #0,d5
 move.b (a3),d5
 lsl.l #8,d5
 move.b 16(a3),d5
 lsl.l #8,d5
 move.b 32(a3),d5
 lsl.l #8,d5
 move.b 48(a3),d5
 and.l d4,d5
 not.l d4
 move.l d4,(a2)+
 move.l d5,(a2)+
 addq.l #2,a3
 dbf d7,.row
 rts

; The tile RAM (D800 codes, DC00 attributes) against its copy bg_raw, as longs: a changed long (4 cells) is marked in
; ring_dirty for each of the three buffers.
bg_scan:
 lea G_Z80-$2800,a2
 lea bg_raw,a3
 tst.b bg_full
 beq.s .start
 clr.b bg_full			; (the first frame: the buffers are drawn whole anyway)
 move.w #255,d0
.copy:
 move.l $400(a2),$400(a3)
 move.l (a2)+,(a3)+
 dbf d0,.copy
 rts
.start:
 tst.b bg_written			; (set by the translated writers, gen.BG_WRITERS)
 bne.s .written
 move.w bg_roll,d0			; else 128 bytes a frame, in case a writer is missing there
 add.w #128,d0
 and.w #$7ff,d0
 move.w d0,bg_roll
 lea (a2,d0.w),a4
 lea (a3,d0.w),a5
 moveq #128/4-1,d0
.roll:
 cmpm.l (a4)+,(a5)+
 dbne d0,.roll
 bne.s .written
 rts
.written:
 clr.b bg_written
 lea $400(a2),a4
 lea $400(a3),a5
 lea ring_dirty,a0
 move.w #255,d6
.scan:
 cmpm.l (a2)+,(a3)+
 bne.s .diff
 cmpm.l (a4)+,(a5)+
 bne.s .diff2
 addq.l #1,a0
 dbf d6,.scan
 rts
.diff:
 addq.l #4,a4
 addq.l #4,a5
.diff2:
 move.l -4(a2),-4(a3)
 move.l -4(a4),-4(a5)
 st (a0)
 st 256(a0)
 st 512(a0)
 addq.l #1,a0
 dbf d6,.scan
 rts

; Bring the buffer draw_idx up to the current scroll: restore what the last frame drawn into it covered (from the twin
; lines), move its window by the scroll, draw the tile rows that came into the band and the tiles that changed.  A new
; horizontal scroll, a jump or a first use draws the band whole.  draw_base = the window's first line.
ring_update:
 move.w draw_idx,d0
 move.w d0,d1
 add.w d1,d1
 move.w d1,ring_off2
 lsl.w #2,d0
 lea ring_base,a0
 move.l (a0,d0.w),ring_addr
 lea ring_dmg,a1			; (the damage list's start)
 move.w draw_idx,d1
 mulu #DMG_MAX*12,d1
 add.l d1,a1
 move.l a1,dmg_start
 moveq #0,d0			; the window's first map row: T = 256 - scroll x (C808), the horizontal scroll C80A
 move.b G_Z80-$37F8,d0
 moveq #0,d1
 move.b G_Z80-$37F7,d1
 lsl.w #8,d1
 or.w d0,d1
 neg.w d1
 add.w #256,d1
 and.w #511,d1
 move.w d1,cur_T
 moveq #0,d0
 move.b G_Z80-$37F6,d0
 moveq #0,d1
 move.b G_Z80-$37F5,d1
 lsl.w #8,d1
 or.w d0,d1
 and.w #511,d1
 move.w d1,cur_sy
 move.w draw_idx,d2
 lea ring_valid,a0
 tst.b (a0,d2.w)
 beq .full
 move.w ring_off2,d2
 lea ring_sy,a0
 cmp.w (a0,d2.w),d1
 bne .full
 lea ring_T,a0
 move.w cur_T,d0
 sub.w (a0,d2.w),d0
 add.w #256,d0
 and.w #511,d0
 sub.w #256,d0			; the scroll since: -256 .. 255 lines
 move.w d0,d7
 bpl.s .positive
 neg.w d7
.positive:
 cmp.w #200,d7
 bhi .full
 move.w d0,scroll_d
 bsr restore_damage
 move.w ring_off2,d2
 lea ring_top,a0
 move.w (a0,d2.w),d1
 add.w scroll_d,d1
 bpl.s .t1
 add.w #RING_H,d1
.t1:
 cmp.w #RING_H,d1
 blo.s .t2
 sub.w #RING_H,d1
.t2:
 move.w d1,(a0,d2.w)
 move.w d1,cur_top
 lea ring_T,a0
 move.w cur_T,(a0,d2.w)
 move.w scroll_d,d0
 beq.s .dirty
 bmi.s .up
 move.w cur_T,d1		; down: map rows T+272-d .. T+271
 add.w #272,d1
 sub.w d0,d1
 bra.s .band
.up:
 neg.w d0			; up: T-16 .. T-16-d-1
 move.w cur_T,d1
 sub.w #16,d1
.band:
 bsr draw_band
.dirty:
 lea ring_dirty,a2		; the changed tiles (groups of 4 cells)
 move.w draw_idx,d0
 lsl.w #8,d0
 add.w d0,a2
 move.l a2,a3
 moveq #63,d5
.dlong:
 tst.l (a3)+
 bne.s .dfound
.dnext:
 dbf d5,.dlong
 bra.s .margins
.dfound:
 lea -4(a3),a4
 moveq #3,d4
.dgroup:
 tst.b (a4)
 beq.s .dskip
 clr.b (a4)
 move.l a4,d0
 sub.l a2,d0
 lsl.w #2,d0
 bsr draw_cell
 addq.w #1,d0
 bsr draw_cell
 addq.w #1,d0
 bsr draw_cell
 addq.w #1,d0
 bsr draw_cell
.dskip:
 addq.l #1,a4
 dbf d4,.dgroup
 bra.s .dnext
.margins:
 move.w cur_sy,d0		; (tiles reach beside the window only when the horizontal scroll is not a multiple of 16)
 and.w #15,d0
 beq.s .no_margins
 move.l ring_addr,a0
 moveq #0,d1
 move.w cur_top,d1
 lsl.l #8,d1
 add.l d1,a0
 moveq #256/32-1,d0
 bsr clear_margins
.no_margins:
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
 move.w ring_off2,d2
 lea ring_sy,a0
 move.w cur_sy,(a0,d2.w)
 lea ring_T,a0
 move.w cur_T,(a0,d2.w)
 lea ring_top,a0
 clr.w (a0,d2.w)
 clr.w cur_top
 lea ring_dirty,a0
 move.w draw_idx,d0
 lsl.w #8,d0
 add.w d0,a0
 moveq #63,d0
.clear_dirty:
 clr.l (a0)+
 dbf d0,.clear_dirty
 move.l ring_addr,a0
 lea -RING_ABOVE*STRIDE(a0),a0
 moveq #RING_LINES/32-1,d0
 bsr clear_margins
 move.w cur_T,d1
 sub.w #16,d1
 move.w #288,d0
 bsr draw_band
 bra .margins

; d1 = the first map row (any integer: used modulo 512), d0 = rows: the tiles of the visible columns that cover them.
draw_band:
 move.w d1,d2
 add.w d0,d2
 subq.w #1,d2
 asr.w #4,d1
 asr.w #4,d2
.row:
 move.w d1,d0
 and.w #31,d0
 neg.w d0
 add.w #31,d0
 lsl.w #5,d0			; the cell of column 0
 move.w cur_sy,d3
 add.w #16,d3
 lsr.w #4,d3			; the first visible column
 moveq #14,d4
.column:
 and.w #31,d3
 move.w d0,d5
 add.w d3,d5
 exg d0,d5
 bsr draw_cell
 exg d0,d5
 addq.w #1,d3
 dbf d4,.column
 addq.w #1,d1
 cmp.w d2,d1
 ble.s .row
 rts

; d0 = a cell: its tile, if it covers the band (window lines -16 .. 271) and a visible column, at its buffer line and
; the twin (and above line 0 when it crosses line RING_H).  Keeps all registers.
draw_cell:
 movem.l d0-d7/a0-a6,-(sp)
 move.w d0,d6
 move.w d6,d1
 lsr.w #5,d1
 neg.w d1
 add.w #31,d1
 lsl.w #4,d1			; the map row
 sub.w cur_T,d1
 add.w #32,d1
 and.w #511,d1
 sub.w #32,d1			; window line, -32 .. 479
 cmp.w #-32,d1
 ble .out
 cmp.w #272,d1
 bge .out
 move.w d6,d2
 and.w #31,d2
 lsl.w #4,d2
 sub.w cur_sy,d2
 and.w #511,d2
 sub.w #16,d2			; x, -16 .. 495
 cmp.w #-16,d2
 ble .out
 cmp.w #224,d2
 bge .out
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
 lea G_Z80-$2800,a0
 moveq #0,d2
 move.b (a0,d6.w),d2
 lea $400(a0),a0
 moveq #0,d1
 move.b (a0,d6.w),d1
 lsl.w #8,d1
 or.w d2,d1
 move.w d1,d0
 moveq #0,d1
 bsr get_object
 move.l ring_addr,draw_base
 move.w cell_line,dest_y
 move.l a1,-(sp)
 bsr draw_tile
 move.l (sp),a1
 add.w #RING_H,dest_y
 bsr draw_tile
 move.l (sp)+,a1
 cmp.w #RING_H-16,cell_line
 ble.s .out
 move.w cell_line,d0
 sub.w #RING_H,d0
 move.w d0,dest_y
 bsr draw_tile
.out:
 movem.l (sp)+,d0-d7/a0-a6
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
 lea piece_lines,a0
 bra .test
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
 cmp.w #16,d2
 bhi.s .divide			; (wider than the table: blit_go divides)
 moveq #0,d1
 move.b -1(a0,d2.w),d1		; the lines a piece: BLIT_PIECE / the words a line
 bsr blit_go_lines		; (up to 8 x 16 words: in pieces)
.test:
 cmp.l a3,a2
 blo .rect
 rts
.divide:
 bsr blit_go
 bra.s .test

 section data,data
piece_lines:			; BLIT_PIECE / the words a line, for 1-16 words (restore_damage: no divu)
 rept 16
 dc.b BLIT_PIECE/(REPTN+1)
 endr
 even
 section text,code

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

; a1=4 planes x 16 rows, whole tile at dest_x/dest_y.
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
 move.w (a0)+,d0
 add.w dest_stride,d0
 sub.w #256,d0
 move.w d0,BLT_DST_YINC.w
 move.w #2,BLT_SRC_XINC.w
 move.w #2,BLT_SRC_YINC.w
 move.w #8,BLT_DST_XINC.w
 move.w #$0203,BLT_HOP_OP.w
 bsr destination
 moveq #3,d3
.plane:
 move.l a1,BLT_SRC_ADDR.w
 move.l d2,BLT_DST_ADDR.w
 move.w #16,BLT_COUNT+2.w
 move.w tile_ctrl,BLT_CTRL.w
 lea 32(a1),a1
 addq.l #2,d2
 dbf d3,.plane
 rts

; d2=destination chunk address (floor x/16; signed guard positions).
destination:
 move.w dest_y,d2
 ext.l d2
 lsl.l #8,d2			; (STRIDE)
 add.l draw_base,d2
 move.w dest_x,d0
 asr.w #4,d0
 lsl.w #3,d0
 add.w #GAME_X,d0
 ext.l d0
 add.l d0,d2
 rts

; Draw complete sprite parts in original priority order, after explicit C806 latch.  The Blitter registers no sprite
; routine changes are set once.
draw_sprites:
 move.w #2,BLT_SRC_XINC.w
 move.w #2,BLT_SRC_YINC.w
 move.w #8,BLT_DST_XINC.w
 move.w #$ffff,BLT_END2.w
 move.w #$0203,BLT_HOP_OP.w
 lea sprite_buffer+$180,a0
.next:
 subq.l #4,a0
 cmp.l #sprite_buffer,a0
 bhs.s .loop
 rts
.loop:
 moveq #0,d4
 move.b 2(a0),d4			; x + 16: 0 (the hidden sprites) and 240 .. 255 are outside
 beq.s .next
 cmp.b #240,d4
 bhs.s .next
 moveq #0,d1
 move.b 1(a0),d1			; attribute: bank 6-7 (3 = none), colour 4-5, flips 2-3, x bit 8 in bit 0
 cmp.b #$c0,d1
 bhs.s .next
 moveq #0,d3
 move.b 3(a0),d3
 btst #0,d1
 beq.s .positive
 sub.w #256,d3
.positive:
 neg.w d3
 add.w #240,d3			; y
 cmp.w #-16,d3
 ble.s .next
 cmp.w #256,d3
 bge.s .next
 sub.w #16,d4			; x
 move.w d1,d2			; the shape: bank, code, flips
 and.w #$c0,d2
 moveq #0,d0
 move.b (a0),d0
 lsl.w #2,d2
 or.w d0,d2
 lsl.w #2,d2
 move.w d1,d5
 lsr.w #2,d5
 and.w #3,d5
 or.w d5,d2
 move.w d2,spr_pcode		; (generic_part)
 ext.l d2
 lsl.l #4,d2
 moveq #15,d5
 and.w d4,d5
 or.w d5,d2
 lsl.l #3,d2
 lea spr_code_tab,a2		; its code for this shift; none: blank, nothing to draw
 add.l d2,a2
 tst.l (a2)
 beq .next
 lsl.w #8,d1			; the baked planes (get_object's hit path)
 or.w d1,d0
 move.w d0,d5
 lsr.w #4,d5
 eor.w d0,d5
 and.w #$fff,d5
 lsl.w #3,d5
 lea cache+32768,a1
 add.w d5,a1
 moveq #1,d6
 swap d6
 move.w d0,d6
 cmp.l (a1),d6
 bne.s .bake
 move.l 4(a1),a1
 move.l a1,d6
 bne.s .baked
.bake:
 moveq #1,d1
 bsr get_object_bake
.baked:
 move.l a0,-(sp)
 move.w d3,d2			; the destination chunk (destination)
 ext.l d2
 lsl.l #8,d2			; (STRIDE)
 add.l draw_base,d2
 move.w d4,d0
 asr.w #4,d0
 lsl.w #3,d0
 add.w #GAME_X,d0
 ext.l d0
 add.l d0,d2			; damage: 16 lines of 1 or 2 chunks, the twin as source (split at line RING_H: add_damage)
 move.w d3,d0
 add.w cur_top,d0
 moveq #4,d3
 moveq #15,d1
 and.w d4,d1
 beq.s .one
 moveq #8,d3
.one:
 move.l dmg_ptr,a0
 moveq #16,d1
 cmp.w #RING_H-16,d0
 bgt.s .lower
 move.l d2,(a0)+
 move.l d2,d7
 add.l #RING_H*STRIDE,d7
 bra.s .store
.lower:
 cmp.w #RING_H,d0
 blt.s .split
 move.l d2,(a0)+
 move.l d2,d7
 sub.l #RING_H*STRIDE,d7
.store:
 move.l d7,(a0)+
 move.w d3,(a0)+
 move.w d1,(a0)+
 move.l a0,dmg_ptr
 bra.s .damaged
.split:
 bsr add_damage
.damaged:
 move.l a1,BLT_SRC_ADDR.w
 move.l d2,BLT_DST_ADDR.w
 move.l (a2),a1
 move.l 4(a2),a0
 cmp.w #$efe0,d2
 bhi .generic
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
 move.l (sp)+,a0
 bra .next
.generic:
 move.w d4,d3
 bsr generic_part
 move.l (sp)+,a0
 bra .next

; Crossing a 64KB boundary uses full addresses; masks still come from baked streams.
generic_part:
 move.l d2,a1
 and.w #15,d3
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
 lsl.w #2,d0
 lea spr_plan_offsets,a0
 move.l (a0,d0.w),d0
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

; Foreground 8x8 characters.  fg_ptr has a baked character (get_object kind 2: 8 rows of a keep mask and the four plane
; bytes, for movep.l) for every visible, not blank cell, or 0.  It changes only where the character RAM (D000 codes, D400
; attributes) differs from its copy fg_raw, compared as longs; then fg_list (the screen offset and the baked character of
; each cell to draw) is made again.  A pool roll-over (pool_epoch) frees the baked characters: then every cell is done again.
draw_foreground:
 sf fg_retry
 move.w pool_epoch,d0
 cmp.w fg_epoch,d0
 beq.s .same_pool
 st fg_full
.same_pool:
 lea G_Z80-$3000,a2
 lea fg_raw,a3
 tst.b fg_full
 beq.s .scan_start
.full:
 clr.b fg_full
 move.w pool_epoch,fg_epoch
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
 tst.b fg_written			; (set by the translated writers, gen.FG_WRITERS)
 bne.s .written
 move.w fg_roll,d0			; else 128 bytes a frame, in case a writer is missing there
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
 move.w pool_epoch,d0		; (the pool rolled over while baking: every pointer again, once)
 cmp.w fg_epoch,d0
 beq.s .same
 tst.b fg_retry
 bne.s .same
 st fg_retry
 lea G_Z80-$3000,a2
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
 lea fg_rows,a3			; damage: each character row's chunks, in four pieces of 2 lines
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
 bsr add_damage
 add.l #2*STRIDE,d2
 addq.w #2,d0
 bsr add_damage
 add.l #2*STRIDE,d2
 addq.w #2,d0
 bsr add_damage
 add.l #2*STRIDE,d2
 addq.w #2,d0
 bsr add_damage
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
 rts

; d6 = the cell: fg_ptr[cell] = its baked character or 0 (blank or outside the window).  Keeps d6.
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
 lea G_Z80-$3000,a0
 moveq #0,d2
 move.b (a0,d6.w),d2
 lea $400(a0),a0
 moveq #0,d1
 move.b (a0,d6.w),d1
 move.w d1,d3
 and.w #$c0,d3
 lsl.w #2,d3
 or.w d2,d3
 lea chr_blank,a0
 tst.b (a0,d3.w)
 bne.s .out
 lsl.w #8,d1
 or.w d1,d2
 move.w d2,d0
 moveq #2,d1
 bsr get_object
 lea fg_ptr,a0
 move.l a1,(a0,d4.w)
.out:
 rts

 include "render_tables.s"
 include "spr_code.s"
 section data,data
ste_pal: incbin "palette.bin"
cmap: incbin "palmap.bin"
black_pal: dcb.w 16,0
reverse_bits: incbin "reverse.bin"
tile_masks: incbin "tile_masks.bin"
spr_masks: incbin "spr_masks.bin"
chr_masks: incbin "chr_masks.bin"
chr_blank: incbin "chr_blank.bin"
spr_order: incbin "spr_order.bin"
chr_opaque: incbin "chr_opaque.bin"
spr_plan_offsets: incbin "spr_plan_offsets.bin"
spr_plan: incbin "spr_plan.bin"
 section bss,bss
POOL_SIZE = $20000
cache: ds.b 3*4096*8
pool_ptr: ds.l 1
pool: ds.b POOL_SIZE
cache_misses: ds.l 1
pool_epoch: ds.w 1
bg_roll: ds.w 1
fg_roll: ds.w 1
fg_epoch: ds.w 1
bg_full: ds.b 1
bg_written: ds.b 1
fg_written: ds.b 1
fg_full: ds.b 1
fg_dirty: ds.b 1
fg_retry: ds.b 1
fg_list_end: ds.l 1
bg_raw: ds.b 2048
fg_raw: ds.b 2048
fg_ptr: ds.l 1024
fg_offsets: ds.l 1024
fg_list: ds.l 2*28*32
fg_rows: ds.b 64
ring_valid: ds.b 4
ring_top: ds.w 3
ring_T: ds.w 3
ring_sy: ds.w 3
ring_off2: ds.w 1
ring_addr: ds.l 1
cur_T: ds.w 1
cur_sy: ds.w 1
cur_top: ds.w 1
scroll_d: ds.w 1
cell_line: ds.w 1
dmg_start: ds.l 1
dmg_ptr: ds.l 1
ring_dmg_end: ds.l 3
ring_dirty: ds.b 3*256
ring_dmg: ds.b 3*DMG_MAX*12
cache_slot: ds.l 1
baked_ptr: ds.l 1
obj_tag: ds.l 1
obj_key: ds.w 1
obj_kind: ds.w 1
obj_code: ds.w 1
obj_flip: ds.w 1
obj_order: ds.w 1
obj_pcode: ds.w 1
obj_row: ds.w 1
obj_height: ds.w 1
obj_pens: ds.w 1
dest_stride: ds.w 1
copy_src_y: ds.w 1
copy_xinc: ds.w 1
copy_skew: ds.w 1
dest_x: ds.w 1
dest_y: ds.w 1
tile_ctrl: ds.w 1
bg_col: ds.w 1
bg_row: ds.w 1
bg_index: ds.w 1
fg_index: ds.w 1
spr_key: ds.w 1
spr_pcode: ds.w 1
chr_pcode: ds.w 1
scroll_x: ds.w 1
scroll_y: ds.w 1
draw_idx: ds.w 1
shown_idx: ds.w 1
prev_idx: ds.w 1
ring_base: ds.l 3
clean_base: ds.l 1
draw_base: ds.l 1
flip_addr: ds.l 1
shown_pal: ds.w 16
screen_area: ds.b 3*RING_SIZE+256
 section text,code
