; 768-pixel virtual screens, 256-pixel scroll pages inside a 544-line buffer.
; The camera moves the Shifter window.  A clean screen holds the background of
; the visible window (and its twins 16 cells away, ready for the next page);
; each of the two display rings restores only the cells on its damage list.
; The black side margins are masks restored before new objects, with camera state kept per cell.  A sprite
; across the always-black band words (window words 0, 1 | 2 and 18 | 19, 20) draws only its inner word
; (clip_sprite); the game's own edge (word 2 or 18 + the fine scroll) is not group-aligned: whole there.
STRIDE = 384
RING_LINES = 544
TEXT_RUNS = 8                    ; runs a text row (at most 7: four blanks split a run)
TEXT_ROW_POOL = 2048             ; strip bytes a text row (at most about 2000)
RECTS = 128+TEXT_RUNS*28         ; rectangles a ring restores at its next use: the sprites, and the text when it is redone
RING_SIZE = STRIDE*RING_LINES
GUARD = 16*STRIDE
COLS = 48
ROWS = 34
CELLS = COLS*ROWS
WIN_COLS = 17                    ; the cells the 256-pixel view can touch
WIN_ROWS = 15                    ; and the 224 lines
    ifnd TILE_ENTRIES
TILE_ENTRIES = 512
    endc
TILE_SETS = TILE_ENTRIES/4
BYTE_LUTS = 32                   ; cached byte tables of bake_pixels (2 KB each: tiles 0-15, sprites 16-23, characters 24-31)
    ifnd SPRITE_ENTRIES
SPRITE_ENTRIES = 512
    endc
SPRITE_SETS = SPRITE_ENTRIES/4
BLT_SRC_ADDR = $ffff8a24
BLT_DST_ADDR = $ffff8a32

init_video:
    move.l #ring_area+255,d0
    and.l #$ffffff00,d0
    add.l #GUARD,d0
    move.l d0,ring_base
    add.l #RING_SIZE,d0
    move.l d0,ring_base+4
    add.l #RING_SIZE,d0
    move.l d0,clean_base
    move.l ring_base,work_base
    move.l ring_base,flip_addr
    lea clean_tags,a0
    move.w #CELLS-1,d0
    moveq #-1,d1
.tags:
    move.l d1,(a0)+
    dbf d0,.tags
    ; cell -> buffer offset, column, row
    lea cell_offsets,a0
    lea cell_col,a1
    lea cell_row,a2
    moveq #0,d1
.orow:
    moveq #0,d2
.ocol:
    move.l d1,d3
    mulu #16*STRIDE,d3
    move.w d2,d4
    lsl.w #3,d4
    ext.l d4
    add.l d4,d3
    move.l d3,(a0)+
    move.b d2,(a1)+
    move.b d1,(a2)+
    addq.w #1,d2
    cmp.w #COLS,d2
    blo.s .ocol
    addq.w #1,d1
    cmp.w #ROWS,d1
    blo.s .orow
    st map_dirty
    move.b #0,$ffff8260.w
    move.b #2,$ffff820a.w
    move.b #(STRIDE-160)/2,$ffff820f.w
    clr.b $ffff8265.w
    lea palette_data,a0
    lea shown_pal,a1
    moveq #7,d0
.pal:
    move.l (a0)+,(a1)+
    dbf d0,.pal
    rts
vbl_video:
    tst.b frame_ready
    beq.s .done
    clr.b frame_ready
    move.b flip_addr+1,$ffff8201.w
    move.b flip_addr+2,$ffff8203.w
    move.b flip_addr+3,$ffff820d.w
    ifnd SIM
    ; the base is loaded into the video counter before the VBL: the counter itself too, or the ring just
    ; released stays on screen one more frame while render_frame erases its text (STE: the counter is writable)
    move.b flip_addr+1,$ffff8205.w
    move.b flip_addr+2,$ffff8207.w
    move.b flip_addr+3,$ffff8209.w
    endc
    move.b fine_scroll,$ffff8265.w
    move.b #(STRIDE-160)/2,d0
    tst.b fine_scroll
    beq.s .width
    subq.b #4,d0
.width:
    move.b d0,$ffff820f.w
    ifd SIM
    movem.l shown_pal,d0-d7
    else
    movem.l black_pal,d0-d7
    endc
    movem.l d0-d7,$ffff8240.w
.done:
    rts

render_frame:
    ; Wait until the VBL has shown the previous ring before reusing it.
    ifnd SIM
.wait:
    tst.b frame_ready
    bne.s .wait
    endc
    eor.w #4,ring_index
    move.w ring_index,d0
    lea ring_base,a0
    move.l (a0,d0.w),work_base
    lea ring_tables,a0
    tst.w d0
    beq.s .ring0
    lea 40(a0),a0
.ring0:
    lea cur_flags,a1
    rept 10
    move.l (a0)+,(a1)+
    endr
    moveq #0,d0
    move.b g_scroll+1,d0
    lsl.w #8,d0
    move.b g_scroll,d0
    move.w d0,scroll_x
    moveq #0,d1
    move.b g_scroll+3,d1
    lsl.w #8,d1
    move.b g_scroll+2,d1
    move.w d1,scroll_y
    btst #6,g_control
    sne view_flip
    beq.s .normal_camera
    neg.w d0
    neg.w d1
.normal_camera:
    and.w #$ff,d0
    and.w #$ff,d1
    move.w d0,physical_x
    move.w d1,physical_y
    move.w d0,d2
    and.w #15,d2
    move.b d2,fine_scroll
    move.w d2,fine_word
    sub.w #16,d2
    move.w d2,fine_m16
    move.w d0,d2
    and.w #$f0,d2
    add.w #64,d2
    move.w d2,sprite_x0          ; a sprite's x + the fine scroll + this: its buffer x
    add.w #16,d2
    move.w d2,sprite_x16
    lsr.w #4,d0
    addq.w #2,d0
    move.w d0,strip_w0           ; the first word of the display window
    addq.w #2,d0
    move.w d0,win_c0             ; the 64-pixel hidden left margin, then the game
    lsr.w #4,d1
    addq.w #1,d1
    move.w d1,win_r0             ; (the game shows lines 16-239)
    ; world cell of physical cell 0, 0 (flipped: the world runs backwards)
    tst.b view_flip
    bne.s .flipped_base
    move.w scroll_x,d0
    and.w #$ff00,d0
    lsr.w #4,d0
    subq.w #4,d0
    move.w d0,base_x
    move.w scroll_y,d0
    and.w #$ff00,d0
    lsr.w #4,d0
    move.w d0,base_y
    bra.s .based
.flipped_base:
    move.w scroll_x,d0
    add.w physical_x,d0
    lsr.w #4,d0
    add.w #19,d0
    move.w d0,base_x
    move.w scroll_y,d0
    add.w physical_y,d0
    lsr.w #4,d0
    add.w #15,d0
    move.w d0,base_y
.based:
    ; side margins: words 0, 1 and 19, 20 of the window black, 2 and 18 by the fine scroll
    moveq #0,d0
    move.b fine_scroll,d0
    moveq #-1,d1
    lsr.w d0,d1
    lea strip_mask_tab,a0
    move.w d1,18*2(a0)
    not.w d1
    move.w d1,2*2(a0)
    bsr penmap_update
    bsr clean_update
    bsr strip_unmask
    bsr text_prepare
    bsr ring_restore
    bsr strip_columns
    bsr sprite_pass
    bsr front_pass
    bsr character_pass
    bsr strip_track
    moveq #0,d0
    move.w physical_y,d0
    add.w #16,d0
    mulu #STRIDE,d0
    moveq #0,d1
    move.w physical_x,d1
    and.w #$f0,d1
    lsr.w #1,d1
    add.w #16,d1                 ; display starts 32 pixels before the game
    add.l d1,d0
    add.l work_base,d0
    ifnd SIM
    sub.l #PIC_TOP*STRIDE,d0
    endc
    move.l d0,flip_addr
    st frame_ready
    rts

; The palette writers set pal_dirty (gen.PAL_WRITERS); 128 bytes a frame are compared in case one is missing.
penmap_update:
    tst.b pal_dirty
    bne .full_compare
    tst.b palette_valid
    beq .full_compare
    tst.w pal_noted_n
    bne .noted
    moveq #0,d0
    move.w pal_roll,d0
    add.w #128,d0
    and.w #$7ff,d0
    move.w d0,pal_roll
    lea g_block+$5800,a0
    add.l d0,a0
    lea palette_shadow,a1
    add.l d0,a1
    moveq #128/4-1,d0
.roll:
    cmpm.l (a0)+,(a1)+
    dbne d0,.roll
    bne .full_compare
    rts
.noted:
    ; the blocks of 128 entries the game's block writes touched (pal_note: the ranges), compared and mapped
    moveq #0,d5
    move.w pal_noted_n,d0
    clr.w pal_noted_n
    subq.w #1,d0
    lea pal_noted,a0
.range:
    move.w (a0)+,d1              ; its first and last address, D800-DFFF (the entry: the address' low 10 bits)
    move.w (a0)+,d2
    and.w #$3ff,d1
    and.w #$3ff,d2
    lsr.w #7,d1
    lsr.w #7,d2
.mark:
    bset d1,d5                   ; (a range over both halves: the blocks of the first to the last entry)
    addq.w #1,d1
    cmp.w d2,d1
    bls.s .mark
    dbf d0,.range
    bra.s .blocks
.full_compare:
    ; in blocks of 128 entries (their low bytes at $5800, high bytes at $5c00): a block that differs is copied and
    ; mapped again
    clr.b pal_dirty
    clr.w pal_noted_n
    moveq #-1,d5                 ; all blocks
.blocks:
    lea palette_dirty,a0
    moveq #15,d0
.clear_dirty:
    clr.l (a0)+
    dbf d0,.clear_dirty
    moveq #0,d6                  ; the block's first entry
    sf d7                        ; a block mapped
.block:
    lsr.w #1,d5
    bcc .next_block
    lea g_block+$5800,a0
    add.w d6,a0
    lea palette_shadow,a1
    add.w d6,a1
    tst.b palette_valid
    beq.s .map                   ; (the first frame: all)
    moveq #128/4-1,d0
.low:
    cmpm.l (a0)+,(a1)+
    dbne d0,.low
    bne.s .map
    lea $400-128(a0),a0
    lea $400-128(a1),a1
    moveq #128/4-1,d0
.high:
    cmpm.l (a0)+,(a1)+
    dbne d0,.high
    bne.s .map
    bra.s .next_block
.map:
    st d7
    lea g_block+$5800,a0
    add.w d6,a0
    lea palette_shadow,a1
    add.w d6,a1
    moveq #128/4-1,d0
.copy:
    move.l (a0)+,(a1)+
    move.l $400-4(a0),$400-4(a1)
    dbf d0,.copy
    bsr map_block
.next_block:
    add.w #128,d6
    cmp.w #1024,d6
    blo.s .block
    st palette_valid
    tst.b d7
    beq .done
    lea palette_dirty,a0
    lea palette_epoch,a1
    moveq #63,d0
.epochs:
    tst.b (a0)+
    beq.s .unchanged
    st epoch_changed
    bsr epoch_lookup
.unchanged:
    addq.l #1,a1
    dbf d0,.epochs
.done:
    rts

; map_block: the pens of palette entries d6 .. d6+127 from the game's palette; a colour whose pens change is marked in
; palette_dirty.  Uses d0-d3/a0-a4.
map_block:
    lea g_block+$5800,a0
    add.w d6,a0
    lea g_block+$5c00,a1
    add.w d6,a1
    lea pen_map,a2
    add.w d6,a2
    lea rgb_map,a3
    lea palette_dirty,a4
    move.w d6,d3
    lsr.w #4,d3
    add.w d3,a4                  ; its first colour
    moveq #7,d0                  ; eight colours of sixteen pens
.colour:
    moveq #15,d3
.pen:
    moveq #0,d1
    move.b (a1)+,d1
    lsl.w #8,d1
    move.b (a0)+,d1
    and.w #$fff,d1
    move.b (a3,d1.w),d2
    cmp.b (a2),d2
    beq.s .same
    st (a4)
.same:
    move.b d2,(a2)+
    dbf d3,.pen
    addq.l #1,a4
    dbf d0,.colour
    rts

; epoch_lookup: colour 63-d0 has a new pen mapping -> its epoch (a1): the number it had when the colour last
; showed the same mapping (its last PEN_HISTORY mappings: flashes and cycles find their baked tiles again),
; else a new one.  Keeps all registers.
PEN_LOG = 3
PEN_HISTORY = 1<<PEN_LOG
epoch_lookup:
    movem.l d0-d3/a0-a4,-(sp)
    moveq #63,d1
    sub.w d0,d1                  ; the colour
    lea pen_map,a2
    move.w d1,d2
    lsl.w #4,d2
    add.w d2,a2                  ; its 16 pens now
    lea pen_hist,a3
    move.w d1,d2
    lsl.w #4,d2
    lsl.w #PEN_LOG,d2
    add.w d2,a3                  ; its mappings (16 bytes each)
    lea pen_hist_id,a4
    move.w d1,d2
    lsl.w #1+PEN_LOG,d2
    add.w d2,a4                  ; their numbers ($100 | epoch, 0: empty)
    moveq #PEN_HISTORY-1,d3
.find:
    move.w (a4)+,d2
    beq.s .next
    move.l (a3),d0
    cmp.l (a2),d0
    bne.s .next
    move.l 4(a3),d0
    cmp.l 4(a2),d0
    bne.s .next
    move.l 8(a3),d0
    cmp.l 8(a2),d0
    bne.s .next
    move.l 12(a3),d0
    cmp.l 12(a2),d0
    bne.s .next
    move.b d2,(a1)               ; seen before: its tiles may still be in the caches
    bra.s .done
.next:
    lea 16(a3),a3
    dbf d3,.find
    lea pen_next,a0              ; a new mapping: a new number
    move.b (a0,d1.w),d2
    addq.b #1,d2
    move.b d2,(a0,d1.w)
    move.b d2,(a1)
    bne.s .store
    bsr epoch_wrap
.store:
    lea pen_slot,a0
    moveq #0,d3
    move.b (a0,d1.w),d3
    addq.b #1,d3
    and.b #PEN_HISTORY-1,d3
    move.b d3,(a0,d1.w)
    lea pen_hist,a3
    move.w d1,d0
    lsl.w #4,d0
    lsl.w #PEN_LOG,d0
    add.w d0,a3
    move.w d3,d0
    lsl.w #4,d0
    add.w d0,a3
    move.l (a2)+,(a3)+
    move.l (a2)+,(a3)+
    move.l (a2)+,(a3)+
    move.l (a2)+,(a3)+
    lea pen_hist_id,a4
    move.w d1,d0
    lsl.w #1+PEN_LOG,d0
    add.w d0,a4
    add.w d3,d3
    and.w #$ff,d2
    or.w #$100,d2
    move.w d2,(a4,d3.w)
.done:
    movem.l (sp)+,d0-d3/a0-a4
    rts

; epoch_wrap: a colour's numbers start again: the caches and every colour's mapping history are forgotten
; (a number must not find tiles or a mapping from before).
epoch_wrap:
    movem.l d0-d1/a0,-(sp)
    lea clean_tags,a0
    move.w #CELLS-1,d0
    moveq #-1,d1
.invalidate:
    move.l d1,(a0)+
    dbf d0,.invalidate
    lea tile_cache_tags,a0
    move #(cache_tags_end-tile_cache_tags)/4-1,d0
.clear:
    clr.l (a0)+
    dbf d0,.clear
    lea pen_hist_id,a0
    move #64*PEN_HISTORY/2-1,d0
.forget:
    clr.l (a0)+
    dbf d0,.forget
    movem.l (sp)+,d0-d1/a0
    rts

; cell_key: physical cell d4 = column, d5 = row -> d2 cache key (0: no background),
; d0 variant code, d1 colour.  Uses d0-d3/a0.
cell_key:
    btst #1,g_video_enable
    bne .off
    move.w base_x,d0
    move.w base_y,d1
    tst.b view_flip
    bne.s .flip
    add.w d4,d0
    add.w d5,d1
    bra.s .map
.flip:
    sub.w d4,d0
    sub.w d5,d1
.map:
    tst.b g_layout
    beq.s .tall
    and.w #127,d0
    and.w #63,d1
    move.w d0,d2
    and.w #15,d2
    move.w d1,d3
    and.w #15,d3
    lsl.w #4,d3
    or.w d3,d2
    and.w #$70,d0
    lsl.w #4,d0
    or.w d0,d2
    and.w #$30,d1
    lsl.w #7,d1
    or.w d1,d2
    bra.s .read
.tall:
    and.w #63,d0
    and.w #127,d1
    move.w d0,d2
    and.w #15,d2
    move.w d1,d3
    and.w #15,d3
    lsl.w #4,d3
    or.w d3,d2
    and.w #$30,d0
    lsl.w #4,d0
    or.w d0,d2
    and.w #$70,d1
    lsl.w #6,d1
    or.w d1,d2
.read:
    add.w d2,d2
    lea g_bg,a0
    moveq #0,d0
    move.b (a0,d2.w),d0
    moveq #0,d1
    move.b 1(a0,d2.w),d1
    move.w d1,d2
    and.w #7,d2
    lsl.w #8,d2
    or.w d2,d0
    move.b g_control,d3
    lsl.b #1,d3
    eor.b d3,d1
    btst #7,d1
    beq.s .noflip
    add.w #2048,d0
.noflip:
    lsr.w #3,d1
    and.w #15,d1
    move.l d1,d2
    lsl.w #8,d2
    lsl.w #4,d2
    or.w d0,d2
    tst.b view_flip
    beq.s .normal_key
    or.l #$10000,d2
.normal_key:
    lea palette_epoch,a0
    moveq #0,d3
    move.b (a0,d1.w),d3
    ror.l #8,d3
    or.l d3,d2
    or.l #$100000,d2
    rts
.off:
    moveq #0,d2
    rts

; The clean screen: a full check of the window when the page, the mode, the
; map or a palette changed, else only the cells scrolled in.
clean_update:
    moveq #0,d7
    tst.b map_dirty
    beq.s .map_same
    clr.b map_dirty
    moveq #1,d7
.map_same:
    tst.b epoch_changed
    beq.s .epoch_same
    clr.b epoch_changed
    moveq #1,d7
.epoch_same:
    move.b g_control,d0
    and.b #$40,d0
    tst.b g_layout
    beq.s .tall
    or.b #1,d0
.tall:
    move.b g_video_enable,d1
    and.b #2,d1
    or.b d1,d0
    cmp.b prev_mode,d0
    beq.s .mode_same
    move.b d0,prev_mode
    moveq #1,d7
.mode_same:
    move.w base_x,d0
    cmp.w prev_base_x,d0
    beq.s .bx_same
    move.w d0,prev_base_x
    moveq #1,d7
.bx_same:
    move.w base_y,d0
    cmp.w prev_base_y,d0
    beq.s .by_same
    move.w d0,prev_base_y
    moveq #1,d7
.by_same:
    move.w win_c0,d2
    sub.w prev_c0,d2
    move.w win_c0,prev_c0
    move.w win_r0,d3
    sub.w prev_r0,d3
    move.w win_r0,prev_r0
    tst.w d7
    bne .full
    movem.w d2-d3,-(sp)
    bsr check_noted
    movem.w (sp)+,d2-d3
    move.w d2,d0
    addq.w #4,d0
    cmp.w #8,d0
    bhi .full
    move.w d3,d0
    addq.w #4,d0
    cmp.w #8,d0
    bhi .full
    tst.w d2
    beq.s .rows
    bmi.s .left
    move.w win_c0,d4             ; columns in at the right
    add.w #WIN_COLS,d4
    sub.w d2,d4
    move.w d2,d6
    bra.s .columns
.left:
    move.w win_c0,d4
    move.w d2,d6
    neg.w d6
.columns:
    move.w d3,-(sp)
    move.w win_r0,d5
    moveq #WIN_ROWS,d7
    bsr check_rect
    move.w (sp)+,d3
.rows:
    tst.w d3
    beq.s .done
    bmi.s .up
    move.w win_r0,d5             ; rows in at the bottom
    add.w #WIN_ROWS,d5
    sub.w d3,d5
    move.w d3,d7
    bra.s .row_rect
.up:
    move.w win_r0,d5
    move.w d3,d7
    neg.w d7
.row_rect:
    move.w win_c0,d4
    moveq #WIN_COLS,d6
    bra check_rect
.full:
    clr.w bg_noted_n                ; (all cells checked)
    ifd DEBUG
    addq.l #1,dbg_full
    endc
    move.w win_c0,d4
    move.w win_r0,d5
    moveq #WIN_COLS,d6
    moveq #WIN_ROWS,d7
    bra check_rect
.done:
    rts

; The background entries the game wrote since the last frame (bg_note): the window's cells that show one are checked
; (cells outside the window are checked when they scroll in).  cell_key's packing of the entry reversed.
check_noted:
    move.w bg_noted_n,d0
    beq .none
    clr.w bg_noted_n
    btst #1,g_video_enable
    bne .none                       ; (the background off: no keys; switching it on checks all)
    subq.w #1,d0
    lea bg_noted,a4
    st no_twins                     ; (an animated tile is drawn where it shows; its twins when the page jumps there)
.next:
    move.w d0,-(sp)
    move.l a4,-(sp)
    move.w (a4),d0
    move.w d0,d4                    ; x, y bits 0-3
    and.w #15,d4
    move.w d0,d5
    lsr.w #4,d5
    and.w #15,d5
    lsr.w #8,d0
    tst.b g_layout
    beq.s .tall
    move.w d0,d1                    ; wide: x bits 4-6, y bits 4-5
    and.w #7,d1
    lsl.w #4,d1
    or.w d1,d4
    lsr.w #3,d0
    and.w #3,d0
    lsl.w #4,d0
    or.w d0,d5
    move.w #127,d2
    moveq #63,d3
    bra.s .world
.tall:
    move.w d0,d1                    ; tall: x bits 4-5, y bits 4-6
    and.w #3,d1
    lsl.w #4,d1
    or.w d1,d4
    lsr.w #2,d0
    and.w #7,d0
    lsl.w #4,d0
    or.w d0,d5
    moveq #63,d2
    move.w #127,d3
.world:
    tst.b view_flip                 ; the cell: world - base (flipped: base - world), as cell_key wraps it
    bne.s .flip
    sub.w base_x,d4
    sub.w base_y,d5
    bra.s .masked
.flip:
    neg.w d4
    add.w base_x,d4
    neg.w d5
    add.w base_y,d5
.masked:
    and.w d2,d4
    and.w d3,d5
    move.w d4,d0
    sub.w win_c0,d0
    cmp.w #WIN_COLS,d0
    bhs.s .skip
    move.w d5,d0
    sub.w win_r0,d0
    cmp.w #WIN_ROWS,d0
    bhs.s .skip
    bsr check_cell
.skip:
    move.l (sp)+,a4
    addq.l #2,a4
    move.w (sp)+,d0
    dbf d0,.next
    clr.b no_twins
.none:
    rts

; check_rect: d4 first column, d5 first row, d6 columns, d7 rows.
check_rect:
    move.w d4,rect_c0
    move.w d6,rect_cols
    subq.w #1,d7
.row:
    move.w rect_c0,d4
    move.w rect_cols,d6
    subq.w #1,d6
.col:
    movem.w d6-d7,-(sp)
    bsr check_cell
    movem.w (sp)+,d6-d7
    addq.w #1,d4
    dbf d6,.col
    addq.w #1,d5
    dbf d7,.row
    rts

; check_cell: the clean cell d4, d5 against its key; a new tile goes to the
; cell and to its twins outside the window.  Keeps d4/d5.
check_cell:
    ifd DEBUG
    addq.l #1,dbg_checks
    endc
    bsr cell_key
    move.w d5,d6
    add.w d6,d6
    lea row_cells,a0
    move.w (a0,d6.w),d6
    add.w d4,d6
    move.w d6,d3
    lsl.w #2,d3
    lea clean_tags,a0
    cmp.l (a0,d3.w),d2
    bne.s .draw
    rts
.draw:
    move.l d2,cell_keyv
    sub.l a1,a1
    tst.l d2
    beq.s .got
    bsr tile_get
.got:
    move.l a1,cell_src
    bsr draw_at
    tst.b no_twins
    bne.s .no_twins
    movem.w d4-d5,-(sp)
    lea twin_offsets,a2
    moveq #7,d7
.twin:
    movem.w (sp),d4-d5
    add.w (a2)+,d4
    add.w (a2)+,d5
    cmp.w #4,d4
    blt.s .skip
    cmp.w #35,d4
    bgt.s .skip
    cmp.w #1,d5
    blt.s .skip
    cmp.w #30,d5
    bgt.s .skip
    move.w d4,d0
    sub.w win_c0,d0
    cmp.w #WIN_COLS,d0
    bhs.s .outside
    move.w d5,d0
    sub.w win_r0,d0
    cmp.w #WIN_ROWS,d0
    blo.s .skip
.outside:
    move.w d5,d6
    add.w d6,d6
    lea row_cells,a0
    move.w (a0,d6.w),d6
    add.w d4,d6
    move.w d6,d3
    lsl.w #2,d3
    lea clean_tags,a0
    move.l cell_keyv,d2
    cmp.l (a0,d3.w),d2
    beq.s .skip
    bsr draw_at
.skip:
    dbf d7,.twin
    movem.w (sp)+,d4-d5
.no_twins:
    rts

mark_both macro
    lea \1,a3
    tst.b (a3,d6.w)
    bne.s .mb\@
    st (a3,d6.w)
    move.w \3,d0
    addq.w #1,\3
    add.w d0,d0
    lea \2,a3
    move.w d6,(a3,d0.w)
.mb\@:
    endm

; draw_at: cell_src (0: blank) with key cell_keyv into clean cell d6 (the Blitter: a copy of the baked tile, or
; zeroes), both rings restore it.  Uses d0-d2/a0/a1/a3.
draw_at:
    ifd DEBUG
    addq.l #1,dbg_draws
    endc
    move.w d6,d0
    lsl.w #2,d0
    lea clean_tags,a0
    move.l cell_keyv,(a0,d0.w)
    lea cell_offsets,a0
    move.l (a0,d0.w),d0
    add.l clean_base,d0
    move.l d0,$ffff8a32.w
    move.w #2,$ffff8a2e.w
    move.w #STRIDE-6,$ffff8a30.w
    moveq #-1,d0
    move.w d0,$ffff8a28.w
    move.w d0,$ffff8a2a.w
    move.w d0,$ffff8a2c.w
    clr.b $ffff8a3d.w
    move.w #4,$ffff8a36.w
    move.l cell_src,d1
    beq .blank
    move.l d1,$ffff8a24.w
    move.w #2,$ffff8a20.w
    move.w #2,$ffff8a22.w
    move.w #$0203,$ffff8a3a.w    ; the source
    move.w #8,$ffff8a38.w        ; (two pieces)
    move.b #$c0,$ffff8a3c.w
    move.w #8,$ffff8a38.w
    move.b #$c0,$ffff8a3c.w
    move.l cell_src,a1
    lea 160(a1),a1               ; the front masks (after the planes and the transparency masks)
    moveq #0,d0
    move.w d6,d0
    lsl.l #5,d0
    lea cell_front,a3
    add.l d0,a3
    moveq #0,d1
    rept 8
    move.l (a1)+,d2
    or.l d2,d1
    move.l d2,(a3)+
    endr
    lea cell_has_front,a3
    tst.l d1
    sne (a3,d6.w)
    bra .mark
.blank:
    move.w #$0000,$ffff8a3a.w    ; all ones AND nothing: zeroes
    move.w #16,$ffff8a38.w       ; (64 words: one piece)
    move.b #$c0,$ffff8a3c.w
    lea cell_has_front,a3
    clr.b (a3,d6.w)
.mark:
    mark_both dmg_flag0,dmg_list0,dmg_count0
    mark_both dmg_flag1,dmg_list1,dmg_count1
    rts
; mark_ring: this ring restores cell d6 at its next use (uses d0/a0/a1).
mark_ring:
    move.l cur_applied,a0
    move.w d6,d0
    add.w d0,d0
    clr.w (a0,d0.w)
    move.l cur_flags,a0
    tst.b (a0,d6.w)
    bne.s .listed
    st (a0,d6.w)
    move.l cur_count,a0
    move.w (a0),d0
    addq.w #1,(a0)
    add.w d0,d0
    move.l cur_list,a1
    move.w d6,(a1,d0.w)
.listed:
    rts

; The ring's damage list (cells) and its rectangle list (what sprites and the text covered: word columns by lines):
; copied from the clean screen by the Blitter.
ring_restore:
    move.w #2,$ffff8a20.w        ; a copy: the four planes of each word column
    move.w #2,$ffff8a2e.w
    moveq #-1,d0
    move.w d0,$ffff8a28.w
    move.w d0,$ffff8a2a.w
    move.w d0,$ffff8a2c.w
    move.w #$0203,$ffff8a3a.w
    clr.b $ffff8a3d.w
    bsr ring_rects               ; (first: a rectangle over a band cell lists the cell, restored with its mask below)
    move.l cur_count,a0
    move.w (a0),d7
    ifd DEBUG
    moveq #0,d0
    move.w d7,d0
    add.l d0,dbg_restored
    endc
    clr.w (a0)
    subq.w #1,d7
    bmi .done
    move.w #STRIDE-6,$ffff8a22.w
    move.w #STRIDE-6,$ffff8a30.w
    move.w #4,$ffff8a36.w
    move.l cur_list,a3
    move.l cur_flags,a4
    move.l cur_applied,a5
    lea cell_offsets,a6
    move.l clean_base,d4
    move.l work_base,d5
    lea restored_tag,a2
    move.b frame_tag,d2
    moveq #0,d3                  ; the halftone loaded (the visible bits of a part-masked column)
.cell:
    move.w (a3)+,d6
    clr.b (a4,d6.w)
    move.b d2,(a2,d6.w)          ; (the text pass redraws the runs over restored cells)
    ; a cell in one of the window's margin columns gets its mask with the restore: black, or the clean screen AND
    ; the visible bits (the halftone)
    lea cell_col,a0
    moveq #0,d0
    move.b (a0,d6.w),d0
    sub.w strip_w0,d0
    cmp.w #21,d0
    bhs .plain
    lea cell_row,a0
    moveq #0,d1
    move.b (a0,d6.w),d1
    sub.w win_r0,d1
    cmp.w #WIN_ROWS,d1
    bhs .plain
    add.w d0,d0
    lea strip_mask_tab,a0
    move.w (a0,d0.w),d1          ; its black bits
    beq .plain
    move.w d6,d0
    add.w d0,d0
    move.w d1,(a5,d0.w)
    addq.w #1,d1
    beq .black
    subq.w #1,d1
    cmp.w d1,d3
    beq.s .loaded
    move.w d1,d3
    not.w d1
    move.w d1,d0
    swap d1
    move.w d0,d1
    lea $ffff8a00.w,a0
    rept 8
    move.l d1,(a0)+
    endr
.loaded:
    move.w #$0303,$ffff8a3a.w    ; the source AND the halftone
    add.w d6,d6
    add.w d6,d6
    move.l (a6,d6.w),d0
    move.l d0,d1
    add.l d4,d0
    move.l d0,$ffff8a24.w
    add.l d5,d1
    move.l d1,$ffff8a32.w
    move.w #8,$ffff8a38.w        ; (two pieces)
    move.b #$c0,$ffff8a3c.w
    move.w #8,$ffff8a38.w
    move.b #$c0,$ffff8a3c.w
    move.w #$0203,$ffff8a3a.w
    dbf d7,.cell
    rts
.black:
    move.w #$0000,$ffff8a3a.w    ; zeroes
    add.w d6,d6
    add.w d6,d6
    move.l (a6,d6.w),d1
    add.l d5,d1
    move.l d1,$ffff8a32.w
    move.w #16,$ffff8a38.w       ; (64 words of zeroes: one piece)
    move.b #$c0,$ffff8a3c.w
    move.w #$0203,$ffff8a3a.w
    dbf d7,.cell
    rts
.plain:
    add.w d6,d6
    clr.w (a5,d6.w)
    add.w d6,d6
    move.l (a6,d6.w),d0
    move.l d0,d1
    add.l d4,d0
    move.l d0,$ffff8a24.w
    add.l d5,d1
    move.l d1,$ffff8a32.w
    move.w #8,$ffff8a38.w        ; (two pieces)
    move.b #$c0,$ffff8a3c.w
    move.w #8,$ffff8a38.w
    move.b #$c0,$ffff8a3c.w
    dbf d7,.cell
.done:
    rts

; ring_rects: the rectangles (sprites, text) from the clean screen.  One flagged (bit 15: it may cover window words
; 0-2 or 18-20; every rectangle after the window's word moved) lists its cells in those words (rect_band): the cell
; restore puts their mask back.
ring_rects:
    move.l cur_rect_count,a0
    move.w (a0),d7
    clr.w (a0)
    subq.w #1,d7
    bmi .done
    move.l cur_rect,a3
    tst.b rect_all
    beq.s .flagged
    move.l a3,a0                 ; (the window's word moved: all flagged)
    move.w d7,d0
.all:
    or.w #$8000,6(a0)
    addq.l #8,a0
    dbf d0,.all
.flagged:
    move.l clean_base,a4
    move.l work_base,a5
    lea bd_lines,a6              ; (engine/rt/borders.s: the lines a piece by the words a line)
.rect:
    move.l (a3)+,d0              ; the offset of its first word
    move.w (a3)+,d6              ; its first cell
    move.w (a3)+,d3              ; its shape
    move.w d3,-(sp)
    bmi .flag
.restore:
    moveq #8,d2                  ; the lines
    btst #1,d3
    beq.s .lines
    moveq #16,d2
.lines:
    move.w d3,d4
    lsr.w #8,d4
    addq.w #1,d4                 ; the word columns
.chunk:
    move.w d4,d5                 ; up to eight a pass (32 words: one piece a line)
    cmp.w #8,d5
    bls.s .width
    moveq #8,d5
.width:
    sub.w d5,d4
    lsl.w #2,d5                  ; the words a line
    move.w d5,$ffff8a36.w
    move.w #STRIDE+2,d1
    sub.w d5,d1
    sub.w d5,d1
    move.w d1,$ffff8a22.w
    move.w d1,$ffff8a30.w
    lea (a4,d0.l),a0
    move.l a0,$ffff8a24.w
    lea (a5,d0.l),a0
    move.l a0,$ffff8a32.w
    moveq #0,d1
    move.b (a6,d5.w),d1          ; the lines a piece
    move.w d2,d3
.piece:
    cmp.w d3,d1
    bls.s .lines_left
    move.w d3,d1
.lines_left:
    move.w d1,$ffff8a38.w
    move.b #$c0,$ffff8a3c.w
    sub.w d1,d3
    bne.s .piece
    moveq #0,d1
    move.w d5,d1
    add.l d1,d0                  ; (the next chunk: 8 bytes a column)
    add.l d1,d0
    tst.w d4
    bne.s .chunk
    move.w (sp)+,d3
    bmi .band
.touch:
    bsr touch_cells
    dbf d7,.rect
.done:
    rts
.flag:
    and.w #$7fff,d3
    bra .restore
.band:
    and.w #$7fff,d3
    bsr rect_band
    bra .touch

; rect_band: the rectangle just restored (-8(a3): its offset; d6, d3: its first cell, its shape) in window words 0-2
; and 18-20: its lines there blacked where the side margin is (zeroes under the end masks: the column's black bits;
; 8 lines a pass when part of the word stays, 16 when all is black).  The Blitter is left as ring_rects has it.
; A rectangle reaching out of the window's rows lists its cells in those words instead (ring_restore: masked in the
; window, plain out of it).  Uses d0-d2/d4/d5/a0/a1.
rect_band:
    lea cell_row,a0
    moveq #0,d0
    move.b (a0,d6.w),d0
    sub.w win_r0,d0
    bmi .cells
    moveq #1,d1
    and.w d3,d1
    add.w d1,d0
    cmp.w #WIN_ROWS,d0
    bhs .cells
    lea cell_col,a0
    moveq #0,d4
    move.b (a0,d6.w),d4
    sub.w strip_w0,d4            ; the window word of its first column
    move.w d3,d5
    lsr.w #8,d5                  ; its columns - 1
    move.l -8(a3),d0
    add.l a5,d0                  ; (work_base) its first column's first word
    lea strip_mask_tab,a1
    move.w #$0000,$ffff8a3a.w    ; zeroes
    move.w #4,$ffff8a36.w
    move.w #STRIDE-6,$ffff8a30.w
.col:
    cmp.w #21,d4
    bhs.s .next                  ; (outside the window)
    move.w d4,d1
    add.w d1,d1
    move.w (a1,d1.w),d1          ; the black bits
    beq.s .next
    move.w d1,$ffff8a28.w
    move.w d1,$ffff8a2a.w
    move.w d1,$ffff8a2c.w
    move.l d0,$ffff8a32.w
    moveq #8,d2
    btst #1,d3
    beq.s .pass
    addq.w #1,d1
    bne.s .two
    moveq #16,d2                 ; (all black: writes only)
    bra.s .pass
.two:
    move.w #8,$ffff8a38.w
    move.b #$c0,$ffff8a3c.w
.pass:
    move.w d2,$ffff8a38.w
    move.b #$c0,$ffff8a3c.w
.next:
    addq.l #8,d0
    addq.w #1,d4
    dbf d5,.col
    moveq #-1,d0
    move.w d0,$ffff8a28.w
    move.w d0,$ffff8a2a.w
    move.w d0,$ffff8a2c.w
    move.w #$0203,$ffff8a3a.w
    rts
.cells:
    movem.l d3/d6,-(sp)
    lea cell_col,a0
    moveq #0,d4
    move.b (a0,d6.w),d4
    sub.w strip_w0,d4
    move.w d3,d5
    lsr.w #8,d5
.cell:
    cmp.w #21,d4
    bhs.s .next_cell
    cmp.w #3,d4
    blo.s .mark
    cmp.w #18,d4
    blo.s .next_cell
.mark:
    bsr mark_ring
    btst #0,d3
    beq.s .next_cell
    add.w #COLS,d6
    bsr mark_ring
    sub.w #COLS,d6
.next_cell:
    addq.w #1,d6
    addq.w #1,d4
    dbf d5,.cell
    movem.l (sp)+,d3/d6
    rts

; touch_cells: cell d6 and the shape d3 (bits 8-12: word columns - 1, bit 0: a second cell row) change their pixels
; this frame (restored, or drawn over): restored_tag (the text pass redraws the runs there).  Their side-margin mask
; (applied) stays: a part of the cell may still have its black bits (strip_unmask restores it when they must go; a
; restore over a band cell lists the cell, ring_rects).  Uses d0-d2/a0.
touch_cells:
    lea restored_tag,a0
    move.b frame_tag,d2
    move.w d3,d1
    lsr.w #8,d1
    move.w d6,d0
.col:
    move.b d2,(a0,d0.w)
    addq.w #1,d0
    dbf d1,.col
    btst #0,d3
    beq.s .done
    move.w d3,d1
    lsr.w #8,d1
    move.w d6,d0
    add.w #COLS,d0
.col2:
    move.b d2,(a0,d0.w)
    addq.w #1,d0
    dbf d1,.col2
.done:
    rts

; add_rect: the rectangle d0.l (the buffer offset of its first word), first cell d6, shape d3 (touch_cells; bit 1: 16
; lines, else 8) to this ring's list: restored at its next use.  Uses d0-d2/a0/a1.
add_rect:
    move.l cur_rect_count,a0
    move.w (a0),d1
    addq.w #1,(a0)
    lsl.w #3,d1
    move.l cur_rect,a1
    add.w d1,a1
    move.l d0,(a1)+
    move.w d6,(a1)+
    move.w d3,(a1)
    bra.s touch_cells
; strip_desired: the side-margin mask of cell d4, d5 in this frame -> d3 (uses d0/a0).
strip_desired:
    moveq #0,d3
    move.w d5,d0
    sub.w win_r0,d0
    cmp.w #WIN_ROWS,d0
    bhs.s .none
    move.w d4,d0
    sub.w strip_w0,d0
    cmp.w #21,d0
    bhs.s .none
    add.w d0,d0
    lea strip_mask_tab,a0
    move.w (a0,d0.w),d3
.none:
    rts

; Margin cells of this ring's last frame that are no longer black where they
; were go to the damage list (before the restore); not those of the two part-masked
; word columns, strip_columns does them whole.
strip_unmask:
    move.b strip_w0+1,d0
    lsl.w #8,d0
    move.b fine_scroll,d0
    swap d0
    move.w win_r0,d0
    lea strip_state,a0
    add.w ring_index,a0
    move.l (a0),d1               ; the last frame's: its window word and fine scroll, its first row
    clr.b rect_all
    cmp.l d1,d0
    beq .done
    move.l d0,(a0)
    st strip_changed
    move.l d0,d2
    eor.l d1,d2
    and.l #$ff00ffff,d2
    beq.s .same_words            ; (the fine scroll only: strip_columns)
    cmp.l #$01000000,d2
    blo.s .same_word
    st rect_all                  ; (the word: the rectangles may lie in other columns now)
.same_word:
    movem.l d0-d1,-(sp)
    bsr strip_enter
    movem.l (sp)+,d0-d1
.same_words:
    move.l cur_strip_count,a3
    move.w (a3),d7
    beq .done
    clr.w (a3)
    ; the list: the six margin columns of the last frame (strip_words, in that order), WIN_ROWS cells each
    move.l cur_strip,a3
    move.l cur_applied,a4
    lea strip_words,a2
    lea strip_mask_tab,a6
    move.l d1,d2
    swap d2
    lsr.w #8,d2
    sub.w strip_w0,d2            ; the last window's first word in this one
    swap d1
    and.w #15,d1                 ; the fine scroll then
    moveq #5,d7
.column:
    move.w (a2)+,d0              ; the column's word of the last window
    moveq #-1,d3                 ; its black bits then: all, or the fine scroll's part
    cmp.w #2,d0
    beq.s .part_left
    cmp.w #18,d0
    bne.s .was
    lsr.w d1,d3
    bra.s .was
.part_left:
    lsr.w d1,d3
    not.w d3
.was:
    add.w d2,d0                  ; its word of this window
    moveq #0,d4                  ; its black bits now
    cmp.w #21,d0
    bhs.s .now
    cmp.w #2,d0
    beq .rows_out                ; (the part-masked columns: strip_columns, but for the rows out of the window)
    cmp.w #18,d0
    beq .rows_out
    add.w d0,d0
    move.w (a6,d0.w),d4
.now:
    not.w d4
    and.w d4,d3                  ; black then where it may not be now: the column's cells
    beq.s .rows_out
    lea cell_row,a5
    moveq #WIN_ROWS-1,d5
.cell:
    move.w (a3)+,d6
    move.w d6,d0
    add.w d0,d0
    move.w (a4,d0.w),d0
    beq.s .next                  ; (no black bits)
    and.w d4,d0
    bne.s .mark
    moveq #0,d0                  ; (they stay: but not out of the window, where it may be any column next time)
    move.b (a5,d6.w),d0
    sub.w win_r0,d0
    cmp.w #WIN_ROWS,d0
    blo.s .next
.mark:
    ifd DEBUG
    addq.l #1,dbg_strip_cells
    endc
    bsr mark_ring
.next:
    dbf d5,.cell
    dbf d7,.column
    bra.s .done
.rows_out:
    ; the mask stays: only the cells whose row left the window lose it
    lea cell_row,a5
    moveq #WIN_ROWS-1,d5
.row:
    move.w (a3)+,d6
    moveq #0,d0
    move.b (a5,d6.w),d0
    sub.w win_r0,d0
    cmp.w #WIN_ROWS,d0
    blo.s .inside
    move.w d6,d0
    add.w d0,d0
    tst.w (a4,d0.w)
    beq.s .inside
    ifd DEBUG
    addq.l #1,dbg_strip_cells
    endc
    bsr mark_ring
.inside:
    dbf d5,.row
    dbf d7,.column
    bra.s .done
.skip:
    lea 2*WIN_ROWS(a3),a3
    dbf d7,.column
.done:
    rts

; strip_enter: the window's word or first row moved: the cells of its words 0, 1, 19 and 20 not wholly black in
; this ring (applied: the mask they have) are blacked now (the Blitter: zeroes, 16 lines of a word column a pass, 256
; bus cycles; the column's next cell below needs no new address), and every rectangle of the ring is checked for the
; band columns (rect_all).  Uses d0-d6/a0-a2/a4-a6.
strip_enter:
    move.w #2,$ffff8a2e.w
    move.w #STRIDE-6,$ffff8a30.w
    moveq #-1,d0
    move.w d0,$ffff8a28.w
    move.w d0,$ffff8a2a.w
    move.w d0,$ffff8a2c.w
    move.w #$0000,$ffff8a3a.w    ; zeroes
    clr.b $ffff8a3d.w
    move.w #4,$ffff8a36.w
    move.l cur_applied,a4
    lea cell_offsets,a5
    move.l work_base,d3
    lea $ffff8a38.w,a6
    move.w win_r0,d2
    add.w d2,d2
    lea row_cells,a0
    move.w (a0,d2.w),d2
    add.w strip_w0,d2            ; window word 0, its first row
    lea strip_black,a2
    moveq #3,d5
.column:
    move.w d2,d6
    add.w (a2)+,d6
    move.w d6,d0
    add.w d0,d0
    lea (a4,d0.w),a1             ; (its applied word)
    moveq #WIN_ROWS-1,d4
    moveq #0,d1                  ; (the destination address follows: the cell above was blacked)
.cell:
    cmp.w #-1,(a1)
    beq.s .black
    move.w #-1,(a1)
    tst.w d1
    bne.s .fill
    move.w d6,d0
    lsl.w #2,d0
    move.l (a5,d0.w),d0
    add.l d3,d0
    move.l d0,$ffff8a32.w
    moveq #1,d1
.fill:
    ifd DEBUG
    addq.l #1,dbg_strip_cells
    endc
    move.w #16,(a6)
    move.b #$c0,$ffff8a3c.w
    lea 2*COLS(a1),a1
    add.w #COLS,d6
    dbf d4,.cell
    dbf d5,.column
    rts
.black:
    moveq #0,d1
    lea 2*COLS(a1),a1
    add.w #COLS,d6
    dbf d4,.cell
    dbf d5,.column
    rts

; The two word columns the fine scroll masks in part (words 2 and 18 of the window), when the window moved: the
; Blitter copies the window's rows from the clean screen with the visible bits (the halftone) only.
strip_columns:
    tst.b strip_changed
    beq .done
    clr.b strip_changed
    move.w #2,$ffff8a20.w
    move.w #2,$ffff8a2e.w
    move.w #STRIDE-6,$ffff8a22.w
    move.w #STRIDE-6,$ffff8a30.w
    moveq #-1,d0
    move.w d0,$ffff8a28.w
    move.w d0,$ffff8a2a.w
    move.w d0,$ffff8a2c.w
    move.w #$0303,$ffff8a3a.w    ; source AND halftone
    clr.b $ffff8a3d.w
    move.w #4,$ffff8a36.w
    moveq #2,d7
.column:
    move.w d7,d0
    add.w d0,d0
    lea strip_mask_tab,a0
    move.w (a0,d0.w),d3          ; the black bits
    move.w d3,d1
    not.w d1
    move.w d1,d2
    swap d1
    move.w d2,d1
    lea $ffff8a00.w,a0
    rept 8
    move.l d1,(a0)+
    endr
    move.w win_r0,d0
    add.w d0,d0
    lea row_cells,a0
    move.w (a0,d0.w),d6
    add.w strip_w0,d6
    add.w d7,d6                  ; the column's first cell
    move.w d6,d0
    lsl.w #2,d0
    lea cell_offsets,a0
    move.l (a0,d0.w),d0
    move.l d0,d1
    add.l clean_base,d0
    move.l d0,$ffff8a24.w
    add.l work_base,d1
    move.l d1,$ffff8a32.w
    moveq #WIN_ROWS*2-1,d1       ; (two pieces a cell)
.piece:
    move.w #8,$ffff8a38.w
    move.b #$c0,$ffff8a3c.w
    dbf d1,.piece
    lea restored_tag,a0
    move.l cur_applied,a1
    move.b frame_tag,d2
    moveq #WIN_ROWS-1,d1
.cell:
    move.b d2,(a0,d6.w)
    move.w d6,d0
    add.w d0,d0
    move.w d3,(a1,d0.w)
    add.w #COLS,d6
    dbf d1,.cell
    add.w #16,d7
    cmp.w #18,d7
    beq .column
.done:
    rts
 ; Track background margin cells for the next camera move. Never mask after
 ; drawing: whole sprites/front tiles can cross into the visible side bands.
strip_track:
    move.l cur_strip,a3
    moveq #0,d7
    lea strip_words,a2
    moveq #5,d5
.column:
    move.w (a2)+,d4
    add.w strip_w0,d4
    move.w win_r0,d2
    add.w d2,d2
    lea row_cells,a0
    add.w d2,a0
    moveq #WIN_ROWS-1,d2
.row:
    move.w (a0)+,d6
    add.w d4,d6
    move.w d6,(a3)+
    addq.w #1,d7
    dbf d2,.row
    dbf d5,.column
    move.l cur_strip_count,a0
    move.w d7,(a0)
    rts

; Cache lookups preserve all caller registers except returned a1.
tile_get:
    movem.l d0-d7/a0-a6,-(sp)
    move.l d2,cache_key
    move.w d1,d3                 ; (TILE_SETS sets of 4: the code with the colour and its palette epoch, so that
    lsl.w #5,d3                  ; the versions of a tile for a colour's recent mappings stay apart)
    eor.w d0,d3
    move.l d2,d4
    rol.l #8,d4
    and.w #$ff,d4
    mulu #37,d4
    eor.w d4,d3
    and.w #TILE_SETS-1,d3
    lsl.w #2,d3                  ; the set's first entry
    move.w d3,d4
    lsl.w #2,d4
    lea tile_cache_tags,a0
    add.w d4,a0
    cmp.l (a0)+,d2
    beq .way
    addq.w #1,d3
    cmp.l (a0)+,d2
    beq .way
    addq.w #1,d3
    cmp.l (a0)+,d2
    beq .way
    addq.w #1,d3
    cmp.l (a0)+,d2
    beq .way
    and.w #-4,d3                 ; a miss: the set's ways in turn
    move.w d3,d4
    lsr.w #2,d4
    lea tile_victim,a0
    moveq #3,d5
    and.b (a0,d4.w),d5
    addq.b #1,(a0,d4.w)
    add.w d5,d3
    move.w d3,d4
    lsl.w #2,d4
    lea tile_cache_tags,a0
    move.l d2,(a0,d4.w)
    mulu #192,d3
    lea tile_cache,a1
    add.l d3,a1
    move.l a1,cache_result
    clr.b bake_vflip
    btst #6,g_control
    beq.s .no_vertical_flip
    st bake_vflip
.no_vertical_flip:
    clr.b bake_flip
    btst #11,d0
    beq.s .normal_pixels
    st bake_flip
.normal_pixels:
    and.l #2047,d0
    move.l d0,d3
    lsl.l #7,d3
    lea tile_pixels,a0
    add.l d3,a0
    lea pen_map,a2
    lsl.w #4,d1
    add.w d1,a2
    lsr.w #4,d1
    lea front_limits,a3
    move.b (a3,d1.w),bake_limit
    move.b #15,bake_transparent
    move.w #16,bake_width
    move.w #16,bake_rows
    ifd SIM
    addq.l #1,bake_n_tile
    endc
    bsr bake_pixels
    bra.s .done
.way:
.hit:
    mulu #192,d3
    lea tile_cache,a1
    add.l d3,a1
    move.l a1,cache_result
.done:
    movem.l (sp)+,d0-d7/a0-a6
    move.l cache_result,a1
    rts

; bake_pixels: a0 = packed pixels (two a byte, the first in the high nibble), a2 = the colour's 16 pens (pen_map),
; a1 = the output: a row's four planes as words (128 bytes), at 128(a1) the rows' transparency masks (a word each, a
; set bit an opaque pixel), at 160(a1) their front masks.  bake_width 8 or 16, bake_rows, bake_flip (mirrored),
; bake_vflip, bake_transparent, bake_limit (the pens below it are front pens).
; A byte table of the colour gives two pixels at once: a long with the four planes' two bits in its four bytes (plane
; 0 in the high byte), and a word with the two transparency bits in its high byte and the front bits in its low byte;
; a row's eight pixels are accumulated with two-bit shifts, then movep puts the four bytes into the plane words.
bake_pixels:
    addq.l #1,bake_calls
    ; The byte table of this colour: cached in BYTE_LUTS slots, valid while the colour's 16 pens, the transparent pen
    ; and the front limit are the same.
    move.l a2,d0
    sub.l #pen_map,d0
    lsr.w #4,d0                  ; the colour: tiles 0-15, sprites 32-39, characters 48-55 (four pens each)
    cmp.w #48,d0
    blo.s .not_char
    sub.w #24,d0
    bra.s .slot
.not_char:
    cmp.w #32,d0
    blo.s .slot
    sub.w #16,d0
.slot:
    and.w #BYTE_LUTS-1,d0
    move.w d0,d1
    mulu #20,d1
    lea byte_lut_tags,a5
    add.w d1,a5
    moveq #11,d1
    lsl.l d1,d0
    add.l #byte_luts,d0
    move.l d0,byte_lut
    move.l (a2),d0
    cmp.l (a5),d0
    bne.s .build
    move.l 4(a2),d0
    cmp.l 4(a5),d0
    bne.s .build
    move.l 8(a2),d0
    cmp.l 8(a5),d0
    bne.s .build
    move.l 12(a2),d0
    cmp.l 12(a5),d0
    bne.s .build
    move.b bake_transparent,d0
    cmp.b 16(a5),d0
    bne.s .build
    move.b bake_limit,d0
    cmp.b 17(a5),d0
    bne.s .build
    tst.b 18(a5)
    bne .rows
.build:
    move.l (a2),(a5)+            ; the slot's tag
    move.l 4(a2),(a5)+
    move.l 8(a2),(a5)+
    move.l 12(a2),(a5)+
    move.b bake_transparent,(a5)+
    move.b bake_limit,(a5)+
    st (a5)
    ifd DEBUG
    addq.l #1,dbg_byte_luts
    endc
    ; Each pen once: its planes spread over the four bytes (spread4), its masks
    lea bake_lut,a5
    lea spread4,a6
    moveq #0,d0
.lut:
    moveq #0,d1
    moveq #0,d3
    cmp.b bake_transparent,d0
    beq.s .lut_save
    move.w #$100,d3              ; opaque
    cmp.b bake_limit,d0
    bhs.s .lut_back
    addq.w #1,d3                 ; a front pen
.lut_back:
    move.b (a2,d0.w),d1
    lsl.w #2,d1
    move.l (a6,d1.w),d1
.lut_save:
    move.w d0,d4
    lsl.w #2,d4
    move.l d1,(a5,d4.w)
    move.w d0,d4
    add.w d4,d4
    move.w d3,64(a5,d4.w)        ; (the masks: words after the 16 longs)
    addq.w #1,d0
    cmp.w #16,d0
    blo.s .lut
    ; byte b: its high pixel first (shifted once more); entries of 8 bytes: the planes, the masks, a pad
    move.l byte_lut,a4
    moveq #0,d0
.byte_hi:
    move.w d0,d4
    lsl.w #2,d4
    move.l (a5,d4.w),d1
    add.l d1,d1
    move.w d0,d4
    add.w d4,d4
    move.w 64(a5,d4.w),d2
    add.w d2,d2
    lea bake_lut,a6
    lea bake_lut+64,a3
    moveq #15,d5
.byte_lo:
    move.l (a6)+,d6
    or.l d1,d6
    move.l d6,(a4)+
    move.w (a3)+,d6
    or.w d2,d6
    move.w d6,(a4)+
    addq.l #2,a4
    dbf d5,.byte_lo
    addq.w #1,d0
    cmp.w #16,d0
    blo.s .byte_hi
.rows:
    move.l byte_lut,a5
    lea nibble_swap,a6
    lea 128(a1),a3               ; the transparency masks
    lea 160(a1),a4               ; the front masks
    move.w bake_rows,bake_row_count
    move.w bake_width,d0
    lsr.w #1,d0
    move.w d0,bake_stride        ; bytes a row
    tst.b bake_vflip
    beq.s .from_top
    move.w bake_rows,d1
    subq.w #1,d1
    mulu d0,d1
    add.l d1,a0                  ; (the last row first)
.from_top:
    lea .half,a2
    tst.b bake_flip
    beq.s .row
    lea .half_mirrored,a2
.row:
    tst.b bake_flip
    beq.s .forward
    add.w bake_stride,a0         ; (mirrored: the row's bytes from its end)
.forward:
    jsr (a2)                     ; pixels 0-7
    movep.l d2,0(a1)
    move.w d4,d5
    lsr.w #8,d5
    move.b d5,(a3)+
    move.b d4,(a4)+
    cmp.w #8,bake_width
    beq.s .narrow
    jsr (a2)                     ; pixels 8-15
    movep.l d2,1(a1)
    move.w d4,d5
    lsr.w #8,d5
    move.b d5,(a3)+
    move.b d4,(a4)+
    bra.s .next_row
.narrow:
    moveq #0,d2
    movep.l d2,1(a1)
    clr.b (a3)+
    clr.b (a4)+
.next_row:
    addq.l #8,a1
    tst.b bake_flip
    beq.s .advance
    add.w bake_stride,a0         ; (mirrored: back to the row's end)
.advance:
    tst.b bake_vflip
    beq.s .counted
    sub.w bake_stride,a0
    sub.w bake_stride,a0
.counted:
    subq.w #1,bake_row_count
    bne .row
    rts
; eight pixels: d2 = the planes (a byte each), d4 = the masks (the transparency byte over the front byte)
.half:
    moveq #0,d2
    moveq #0,d4
    rept 4
    moveq #0,d6
    move.b (a0)+,d6
    lsl.w #3,d6
    lsl.l #2,d2
    or.l (a5,d6.w),d2
    lsl.w #2,d4
    or.w 4(a5,d6.w),d4
    endr
    rts
.half_mirrored:                  ; (the bytes from the row's end, each with its two pixels swapped)
    moveq #0,d2
    moveq #0,d4
    rept 4
    moveq #0,d6
    move.b -(a0),d6
    move.b (a6,d6.w),d6
    lsl.w #3,d6
    lsl.l #2,d2
    or.l (a5,d6.w),d2
    lsl.w #2,d4
    or.w 4(a5,d6.w),d4
    endr
    rts

; front_band_pass: front_pass when an edge sprite listed front cells (front_band): those in window words 2 and 18
; get the front pens only in their visible part (not the band's: the whole sprite shows there).
front_band_pass:
.cell:
    move.w (a3)+,d6
    lea front_flag,a0
    clr.b (a0,d6.w)
    moveq #-1,d2                 ; the visible bits
    lea cell_col,a0
    moveq #0,d0
    move.b (a0,d6.w),d0
    sub.w strip_w0,d0
    cmp.w #2,d0
    beq.s .band
    cmp.w #18,d0
    bne.s .visible
.band:
    add.w d0,d0
    lea strip_mask_tab,a0
    move.w (a0,d0.w),d2
    not.w d2
.visible:
    moveq #0,d0
    move.w d6,d0
    lsl.l #5,d0
    lea cell_front,a2
    add.l d0,a2
    move.w d6,d0
    lsl.w #2,d0
    lea cell_offsets,a0
    move.l (a0,d0.w),d0
    move.l clean_base,a0
    add.l d0,a0
    move.l work_base,a1
    add.l d0,a1
    moveq #15,d5
.row:
    move.w (a2)+,d1
    and.w d2,d1
    beq.s .empty
    move.w d1,d4
    not.w d4
    rept 4
    move.w (a0)+,d3
    and.w d1,d3
    and.w d4,(a1)
    or.w d3,(a1)+
    endr
    lea STRIDE-8(a0),a0
    lea STRIDE-8(a1),a1
    dbf d5,.row
    bra.s .next
.empty:
    lea STRIDE(a0),a0
    lea STRIDE(a1),a1
    dbf d5,.row
.next:
    dbf d7,.cell
    rts

; Front pens over the sprites: only the cells sprites touched, from the clean screen.
front_pass:
    move.w front_count,d7
    ifd DEBUG
    moveq #0,d0
    move.w d7,d0
    add.l d0,dbg_fronts
    endc
    clr.w front_count
    move.b front_band,d0
    clr.b front_band
    subq.w #1,d7
    bmi .done
    lea front_list,a3
    tst.b d0
    bne front_band_pass
.cell:
    move.w (a3)+,d6
    lea front_flag,a0
    clr.b (a0,d6.w)
    moveq #0,d0
    move.w d6,d0
    lsl.l #5,d0
    lea cell_front,a2
    add.l d0,a2
    move.w d6,d0
    lsl.w #2,d0
    lea cell_offsets,a0
    move.l (a0,d0.w),d0
    move.l clean_base,a0
    add.l d0,a0
    move.l work_base,a1
    add.l d0,a1
    moveq #15,d5
.row:
    move.w (a2)+,d1
    beq.s .empty
    move.w d1,d4
    not.w d4
    rept 4
    move.w (a0)+,d3
    and.w d1,d3
    and.w d4,(a1)
    or.w d3,(a1)+
    endr
    lea STRIDE-8(a0),a0
    lea STRIDE-8(a1),a1
    dbf d5,.row
    bra.s .next
.empty:
    lea STRIDE(a0),a0
    lea STRIDE(a1),a1
    dbf d5,.row
.next:
    dbf d7,.cell
.done:
    rts

; object_cell: the cell of object_x / object_y -> d6 (uses d0/d1/a0).
object_cell:
    move.w object_y,d1
    lsr.w #4,d1
    add.w d1,d1
    lea row_cells,a0
    move.w (a0,d1.w),d6
    move.w object_x,d0
    lsr.w #4,d0
    add.w d0,d6
    rts

; A sprite's rectangle (one word column when it is on a word, else two; 16 lines) goes to this ring's rectangle list;
; its cells with front pens to the front list.
mark_sprite:
    ifd DEBUG
    addq.l #1,dbg_sprite_cells
    endc
    bsr object_cell
    moveq #0,d0
    move.w object_y,d0
    mulu #STRIDE,d0
    moveq #0,d1
    move.w object_x,d1
    lsr.w #4,d1
    lsl.w #3,d1
    add.l d1,d0
    moveq #2,d3                  ; 16 lines
    move.w object_x,d1
    and.w #15,d1
    beq.s .one_column
    or.w #$100,d3
.one_column:
    move.w object_y,d1
    and.w #15,d1
    beq.s .one_row
    bset #0,d3
.one_row:
    bsr add_rect
    ; its cells with front pens (cell_has_front: few) to the front list
    lea cell_has_front,a0
    move.w d6,d1
    tst.b (a0,d1.w)
    bne.s .fronts
    btst #8,d3
    beq.s .second_row
    tst.b 1(a0,d1.w)
    bne.s .fronts
.second_row:
    btst #0,d3
    beq.s .done
    add.w #COLS,d1
    tst.b (a0,d1.w)
    bne.s .fronts
    btst #8,d3
    beq.s .done
    tst.b 1(a0,d1.w)
    beq.s .done
.fronts:
    move.w d6,d1
    bsr.s .one
    btst #8,d3
    beq.s .row_done
    addq.w #1,d1
    bsr.s .one
    subq.w #1,d1
.row_done:
    btst #0,d3
    beq.s .done
    add.w #COLS,d1
    bsr.s .one
    btst #8,d3
    beq.s .done
    addq.w #1,d1
    bsr.s .one
.done:
    rts
.one:
    lea cell_has_front,a0
    tst.b (a0,d1.w)
    beq.s .no
    lea front_flag,a0
    tst.b (a0,d1.w)
    bne.s .no
    st (a0,d1.w)
    move.w front_count,d0
    addq.w #1,front_count
    add.w d0,d0
    lea front_list,a0
    move.w d1,(a0,d0.w)
.no:
    rts
; Sprites in descending RAM order; an entry with y = 0 is off the screen in both orientations.
sprite_pass:
    btst #2,g_video_enable
    bne .done
    move.w #2,$ffff8a20.w        ; (sprite_blit: the registers every sprite shares)
    move.w #2,$ffff8a22.w
    move.w #8,$ffff8a2e.w
    move.w #$ffff,$ffff8a2a.w
    move.w #$0203,$ffff8a3a.w
    lea bt_sprites+$1fc,a3
    moveq #127,d7
.next:
    moveq #0,d3
    move.b 2(a3),d3
    beq .skip
    moveq #0,d1
    move.b 1(a3),d1
    moveq #0,d2
    move.b 3(a3),d2
    btst #4,d1
    beq.s .positive
    sub.w #256,d2
.positive:
    tst.b view_flip
    beq.s .normal_position
    neg.w d2
    add.w #240,d2
    neg.w d3
    add.w #240,d3
    eor.b #8,d1
.normal_position:
    add.w fine_m16,d2            ; x from the window's word 3 (the game's edge: word 2 + the fine scroll)
    cmp.w #224,d2
    bhi .edge                    ; (on window word 2 or 18, across 1|2 or 18|19, or off the picture)
    cmp.w #240,d3
    bge .skip
    cmp.w #1,d3
    blt .skip
    add.w sprite_x16,d2
    move.w d2,object_x
    add.w physical_y,d3
    move.w d3,object_y
    moveq #0,d2
    move.b (a3),d2
    move.w d1,d3
    and.w #$e0,d3
    lsl.w #3,d3
    or.w d3,d2
    btst #3,d1
    beq.s .unflipped
    add.w #2048,d2
.unflipped:
    lea sprite_blank,a0
    tst.b (a0,d2.w)
    bne.s .skip
    move.w d2,object_code
    and.w #7,d1
    move.w d1,object_colour
    movem.l d7/a3,-(sp)
    ifd DEBUG
    addq.l #1,dbg_sprites
    endc
    bsr sprite_get
    move.l a1,object_source
    bsr mark_sprite
    bsr sprite_blit
    movem.l (sp)+,d7/a3
.skip:
    subq.l #4,a3
    dbf d7,.next
.done:
    rts
; A sprite off the window's words 3-17 at the left or the right: off the picture (culled); across the 16-pixel
; group boundary of the always-black band words 0, 1 | 2 or 18 | 19, 20: only its inner word is drawn (the game's
; own edge, word 2 or 18 + the fine scroll, is not group-aligned: the band part of words 2 and 18 shows it whole);
; else whole on word 2 or 18.  Its rectangle is flagged: its restore leaves the band parts black (ring_rects).
.edge:
    add.w #16,d2                 ; x from the window's word 2
    move.w d2,d0
    sub.w fine_word,d0           ; x
    tst.w d2
    bmi.s .left
    cmp.w #16,d2
    blo.s .whole                 ; (starting on word 2)
    cmp.w #256,d0
    bge .skip
    cmp.w #256,d2
    bls.s .whole                 ; (across 17|18, or on 18)
    clr.b clip_mode              ; (across 18|19)
    bra.s .clip
.whole:
    move.b #1,clip_mode
    bra.s .clip
.left:
    cmp.w #-15,d0
    blt .skip
    st clip_mode
.clip:
    cmp.w #240,d3
    bge .skip
    cmp.w #1,d3
    blt .skip
    add.w sprite_x0,d2
    move.w d2,object_x
    add.w physical_y,d3
    move.w d3,object_y
    moveq #0,d2
    move.b (a3),d2
    move.w d1,d3
    and.w #$e0,d3
    lsl.w #3,d3
    or.w d3,d2
    btst #3,d1
    beq.s .clip_unflipped
    add.w #2048,d2
.clip_unflipped:
    lea sprite_blank,a0
    tst.b (a0,d2.w)
    bne .skip
    move.w d2,object_code
    and.w #7,d1
    move.w d1,object_colour
    movem.l d7/a3,-(sp)
    ifd DEBUG
    addq.l #1,dbg_sprites
    endc
    bsr sprite_get
    move.l a1,object_source
    bsr clip_sprite
    movem.l (sp)+,d7/a3
    bra .skip

; clip_sprite: the sprite at object_x, object_y on window word 2 or 18 (clip_mode 1: whole), or (shifted) across a
; band boundary: its inner word only, one word a line (xcount 1).  Right (clip_mode 0): the first word, skew s,
; END1 = the first word's mask (the stream's high word).  Left (-1): the second word (+8), FXSR with source Y
; increment 0 (each line's word read again as the next one's first), END1 = the second word's mask (the stream's low
; word: its END1/END3 registers swapped).  The damage: the inner word column only.  Its rectangle is flagged.
clip_sprite:
    st front_band                ; (its front cells may lie in window word 2 or 18: front_band_pass)
    tst.b clip_mode
    bgt .whole
    move.w object_x,d0
    move.w d0,-(sp)
    and.w #$fff0,d0
    tst.b clip_mode
    beq.s .mark
    add.w #16,d0
.mark:
    move.w d0,object_x           ; (on a word: one column)
    bsr mark_sprite
    move.w (sp)+,object_x
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
    mulu #BT_MASK_STRIDE,d1
    lea bt_sprite_masks,a1
    add.l d1,a1
    move.w #2,$ffff8a30.w
    move.w #1,$ffff8a36.w
    move.l object_source,BLT_SRC_ADDR.w
    tst.b clip_mode
    bne.s .left
    move.l d0,BLT_DST_ADDR.w
    or.w #$c000,d6
    lea $ffff8a28.w,a2
    lea $ffff8a2c.w,a3
    bsr sprite_stream
    bra.s band_flag
.left:
    addq.l #8,d0
    move.l d0,BLT_DST_ADDR.w
    or.w #$c080,d6
    clr.w $ffff8a22.w
    lea $ffff8a2c.w,a2           ; (END1 <- the low word)
    lea $ffff8a28.w,a3
    bsr sprite_stream
    move.w #2,$ffff8a22.w
    bra.s band_flag
.whole:
    bsr mark_sprite
    bsr sprite_blit
; band_flag: the rectangle listed last (bit 15 of its shape) may cover the band columns: ring_rects checks its cells.
band_flag:
    move.l cur_rect_count,a0
    move.w (a0),d1
    lsl.w #3,d1
    move.l cur_rect,a1
    or.w #$8000,-2(a1,d1.w)
    rts

sprite_get:                      ; (sprite_pass keeps nothing in the registers: none saved)
    moveq #0,d0
    move.w object_code,d0
    moveq #0,d1
    move.w object_colour,d1
    move.l d1,d2
    lsl.w #8,d2
    lsl.w #4,d2
    or.w d0,d2
    lea palette_epoch+32,a0
    moveq #0,d3
    move.b (a0,d1.w),d3
    ror.l #8,d3
    or.l d3,d2
    or.l #$100000,d2
    move.w d1,d3                 ; (SPRITE_SETS sets of 4, as tile_get's: the code with the colour and its epoch)
    lsl.w #5,d3
    eor.w d0,d3
    move.l d2,d4
    rol.l #8,d4
    and.w #$ff,d4
    mulu #37,d4
    eor.w d4,d3
    and.w #SPRITE_SETS-1,d3
    lsl.w #2,d3                  ; the set's first entry
    move.w d3,d4
    lsl.w #2,d4
    lea sprite_cache_tags,a0
    add.w d4,a0
    cmp.l (a0)+,d2
    beq .hit
    addq.w #1,d3
    cmp.l (a0)+,d2
    beq .hit
    addq.w #1,d3
    cmp.l (a0)+,d2
    beq .hit
    addq.w #1,d3
    cmp.l (a0)+,d2
    beq .hit
    and.w #-4,d3                 ; a miss: the set's ways in turn
    move.w d3,d4
    lsr.w #2,d4
    lea sprite_victim,a0
    moveq #3,d5
    and.b (a0,d4.w),d5
    addq.b #1,(a0,d4.w)
    add.w d5,d3
    move.w d3,d4
    lsl.w #2,d4
    lea sprite_cache_tags,a0
    move.l d2,(a0,d4.w)
    and.l #$ffff,d3
    lsl.l #7,d3
    lea sprite_cache,a1
    add.l d3,a1
    move.l a1,cache_result
    clr.b bake_vflip
    clr.b bake_flip
    btst #11,d0
    beq.s .normal_pixels
    st bake_flip
.normal_pixels:
    and.l #2047,d0
    move.l d0,d3
    lsl.l #7,d3
    lea sprite_pixels,a0
    add.l d3,a0
    lea pen_map+$200,a2
    lsl.w #4,d1
    add.w d1,a2
    lea bake_scratch,a1
    move.b #15,bake_transparent
    clr.b bake_limit
    move.w #16,bake_width
    move.w #16,bake_rows
    ifd SIM
    addq.l #1,bake_n_sprite
    endc
    bsr bake_pixels
    moveq #0,d0
    move.w object_code,d0
    lsl.l #4,d0
    lea sprite_order,a0
    add.l d0,a0
    move.l cache_result,a1
    lea bake_scratch,a2
    moveq #15,d0
.reorder:
    moveq #0,d1
    move.b (a0)+,d1
    lsl.w #3,d1
    move.l (a2,d1.w),(a1)+
    move.l 4(a2,d1.w),(a1)+
    dbf d0,.reorder
    bra.s .done
.hit:
    and.l #$ffff,d3
    lsl.l #7,d3
    lea sprite_cache,a1
    add.l d3,a1
    move.l a1,cache_result
.done:
    move.l cache_result,a1
    rts

sprite_blit:
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
    mulu #BT_MASK_STRIDE,d1
    lea bt_sprite_masks,a1
    add.l d1,a1
    tst.w d6
    beq.s .narrow
    or.w #$c040,d6
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
; sprite_stream: the sprite's stream of row groups (bt_sprite_draw), the Blitter set but its END1 (a2), END3 (a3).
sprite_stream:
    moveq #0,d0
    move.w object_code,d0
    btst #6,g_control
    beq.s .normal_stream
    add.w #4096,d0
.normal_stream:
    lsl.l #2,d0
    lea bt_sprite_streams,a0
    move.l (a0,d0.l),a0
    lea $ffff8a32.w,a4
    lea $ffff8a38.w,a5
    lea $ffff8a3c.w,a6
    jsr bt_sprite_draw
    rts

; The text layer: runs of characters on one text row (gaps up to three blanks),
; composed into planar strips when the text RAM or the flip changes; a frame
; draws each run with the Blitter (shifted, two passes per plane).
; A strip line is [0, bytes of the run.., 0 ..] (L = N+2 words, N words of
; pixels), read with FXSR; blocks: mask, planes 0-3, 8 lines each.
text_scan:
    move.b g_control,d0
    and.b #$40,d0
    cmp.b text_flip,d0
    bne.s .all
    tst.b text_valid
    bne.s .rows
.all:
    st text_valid                ; a flip (or the first frame): every row again
    move.b d0,text_flip
    st text_force
.rows:
    move.w text_roll,d0          ; one row a frame is compared anyway (a writer missing from gen.TEXT_WRITERS)
    addq.w #1,d0
    cmp.w #30,d0
    blo.s .roll
    moveq #2,d0
.roll:
    move.w d0,text_roll
    move.w #2,text_row
.check:
    move.w text_row,d1
    tst.b text_force
    bne .changed
    lea text_rows_dirty,a0
    tst.b (a0,d1.w)
    bne.s .compare               ; a hooked store to its codes
    tst.b 32(a0,d1.w)
    bne.s .compare               ; or to its attributes (the same value written again rebuilds nothing)
    tst.b text_compare
    bne.s .compare               ; a block copy: every row compared
    cmp.w text_roll,d1
    bne .next_check
.compare:
    lsl.w #5,d1
    lea g_block+$5000,a0
    add.w d1,a0
    lea text_shadow,a1
    add.w d1,a1
    rept 8
    cmpm.l (a0)+,(a1)+
    bne.s .changed
    endr
    lea $400-32(a0),a0
    lea $400-32(a1),a1
    rept 8
    cmpm.l (a0)+,(a1)+
    bne.s .changed
    endr
    bra .next_check
.changed:
    move.w text_row,d1           ; the row's codes and attributes to the shadow
    lsl.w #5,d1
    lea g_block+$5000,a0
    add.w d1,a0
    lea text_shadow,a1
    add.w d1,a1
    rept 8
    move.l (a0)+,(a1)+
    endr
    lea $400-32(a0),a0
    lea $400-32(a1),a1
    rept 8
    move.l (a0)+,(a1)+
    endr
    ifd DEBUG
    addq.l #1,dbg_text_rows
    endc
    bsr text_row_build
    st text_relist
.next_check:
    addq.w #1,text_row
    cmp.w #30,text_row
    blo .check
    clr.b text_force
    clr.b text_compare
    tst.b text_relist
    beq.s .listed
    clr.b text_relist
    addq.w #1,text_gen
    lea run_list,a0              ; the rows' runs one after the other in draw_list
    lea draw_list,a1
    lea text_runs,a2
    moveq #0,d2
    moveq #28-1,d1
.relist_row:
    move.l a0,a3
    move.w (a2)+,d0
    add.w d0,d2
    subq.w #1,d0
    bmi.s .relist_next
.relist_run:
    move.l (a3)+,(a1)+
    move.l (a3)+,(a1)+
    move.l (a3)+,(a1)+
    dbf d0,.relist_run
.relist_next:
    lea TEXT_RUNS*12(a0),a0
    dbf d1,.relist_row
    move.w d2,run_count
.listed:
    lea text_rows_dirty,a0
    rept 16
    clr.l (a0)+
    endr
    rts

; text_row_build: the runs of row text_row (2-29) from the shadow, into the row's own slots of run_list
; (TEXT_RUNS runs) and text_pool (TEXT_ROW_POOL bytes), its count to text_runs.
text_row_build:
    move.w text_row,d0
    subq.w #2,d0
    move.w d0,d1
    mulu #TEXT_RUNS*12,d1
    add.l #run_list,d1
    move.l d1,run_next
    mulu #TEXT_ROW_POOL,d0
    add.l #text_pool,d0
    move.l d0,pool_next
    clr.w run_count
.row:
    ; the row's characters in screen order: x = i*8 (flipped: column 31-i)
    lea row_tmp,a1
    moveq #0,d5
    moveq #0,d4
.gather:
    move.w d4,d0
    tst.b text_flip
    beq .column
    neg.w d0
    add.w #31,d0
.column:
    move.w text_row,d1
    lsl.w #5,d1
    add.w d0,d1
    lea text_shadow,a0
    moveq #0,d2
    move.b (a0,d1.w),d2
    lea text_shadow+$400,a0
    moveq #0,d3
    move.b (a0,d1.w),d3
    move.w d3,d0
    and.w #$e0,d0
    lsl.w #3,d0
    or.w d0,d2
    lea char_blank,a0
    tst.b (a0,d2.w)
    bne.s .blank
    move.w d4,d0
    lsl.w #3,d0
    move.w d0,(a1)+
    move.w d2,(a1)+
    and.w #31,d3
    move.w d3,(a1)+
    addq.w #1,d5
.blank:
    addq.w #1,d4
    cmp.w #32,d4
    blo.s .gather
    move.w text_row,d1
    lsl.w #3,d1
    tst.b text_flip
    beq.s .row_y
    neg.w d1
    add.w #248,d1
.row_y:
    move.w d1,row_y
    lea row_tmp,a1
.run:
    tst.w d5
    beq .next_row
    ; extend the run while the next character is at most three blanks away
    move.l a1,a2
    move.w d5,d3
    subq.w #1,d3
    moveq #1,d2
.extend:
    tst.w d3
    beq.s .run_end
    move.w 6(a2),d0
    sub.w (a2),d0
    cmp.w #32,d0
    bhi.s .run_end
    addq.l #6,a2
    subq.w #1,d3
    addq.w #1,d2
    bra.s .extend
.run_end:
    move.w d3,chars_left
    move.w d2,run_chars
    move.w (a2),d0
    addq.w #8,d0
    sub.w (a1),d0
    lsr.w #3,d0
    addq.w #1,d0
    lsr.w #1,d0                  ; N words
    move.w d0,d1
    addq.w #2,d1
    add.w d1,d1                  ; bytes a line
    move.w d1,d6
    lsl.w #3,d6                  ; bytes a block
    move.l run_next,a0
    move.w (a1),(a0)+
    move.w row_y,(a0)+
    move.w d0,(a0)+
    move.w d1,(a0)+
    move.l pool_next,a4
    move.l a4,(a0)+
    move.l a0,run_next
    addq.w #1,run_count
    move.w d6,d0                 ; clear the five blocks
    mulu #5,d0
    lsr.w #1,d0
    subq.w #1,d0
    move.l a4,a0
.clear:
    clr.w (a0)+
    dbf d0,.clear
    move.l a0,pool_next
    move.w (a1),run_x0
    clr.b run_planes
.char:
    move.w 2(a1),object_code
    move.w 4(a1),object_colour
    moveq #0,d0
    move.w (a1),d0
    sub.w run_x0,d0
    lsr.w #3,d0                  ; byte in the line
    move.l a1,-(sp)
    bsr char_get                 ; a1 = planes (pixels in the high bytes), +128 masks
    move.w object_colour,d2      ; the planes its pens can set
    lsl.w #2,d2
    lea pen_map+$300,a2
    add.w d2,a2
    move.b (a2)+,d2
    or.b (a2)+,d2
    or.b (a2),d2
    or.b d2,run_planes
    lea 128(a1),a3
    lea 2(a4,d0.w),a0
    moveq #7,d4
.char_row:
    move.l a0,a2
    move.b (a3),(a2)
    addq.l #2,a3
    add.w d6,a2
    move.b (a1),(a2)
    add.w d6,a2
    move.b 2(a1),(a2)
    add.w d6,a2
    move.b 4(a1),(a2)
    add.w d6,a2
    move.b 6(a1),(a2)
    addq.l #8,a1
    add.w d1,a0
    dbf d4,.char_row
    move.l (sp)+,a1
    addq.l #6,a1
    subq.w #1,run_chars
    bne .char
    move.l run_next,a0
    move.b run_planes,-8(a0)     ; (the high byte of the run's N: the planes to draw)
    move.w chars_left,d5
    bra .run
.next_row:
    move.w text_row,d0
    subq.w #2,d0
    add.w d0,d0
    lea text_runs,a0
    move.w run_count,(a0,d0.w)
    rts

character_pass:
    btst #7,g_control
    bne .off
    move.w #2,$ffff8a20.w
    move.w #2,$ffff8a22.w
    move.w #-1,$ffff8a28.w
    move.w #-1,$ffff8a2a.w
    move.w #-1,$ffff8a2c.w
    move.w #8,$ffff8a2e.w
    move.b #2,$ffff8a3a.w
    move.w run_count,d7
    subq.w #1,d7
    bmi .done
    lea draw_list,a3
.run:
    move.w (a3)+,d0
    add.w physical_x,d0
    add.w #64,d0
    move.w (a3)+,d1
    add.w physical_y,d1
    move.w (a3)+,d2              ; N, the planes to draw in the high byte
    move.w (a3)+,d3              ; bytes a line
    move.l (a3)+,a2              ; the mask block
    movem.l d0-d3/d7/a2-a3,-(sp)
    ; its rectangle: words x>>4 .. +N, lines y .. y+7; its cells: two rows when the lines cross a cell line
    move.w d0,object_x
    move.w d1,object_y
    bsr object_cell
    moveq #0,d3
    move.b d2,d3
    lsl.w #8,d3
    move.w object_y,d0
    and.w #15,d0
    cmp.w #8,d0
    bls.s .one_row
    bset #0,d3
.one_row:
    tst.b text_keep
    bne.s .check
    move.w object_x,d1           ; (its columns on window word 2 or 18, or beyond: flagged, see band_flag)
    sub.w sprite_x0,d1
    cmp.w #16,d1
    blo.s .band
    lsr.w #4,d1
    move.w d3,d0
    lsr.w #8,d0
    add.w d0,d1
    cmp.w #16,d1
    blo.s .inner
.band:
    or.w #$8000,d3
.inner:
    moveq #0,d0                  ; drawing whole: recorded for the ring (text_prepare restores it when the text is redone)
    move.w object_y,d0
    mulu #STRIDE,d0
    moveq #0,d1
    move.w object_x,d1
    lsr.w #4,d1
    lsl.w #3,d1
    add.l d1,d0
    move.l cur_text_count,a0
    move.w (a0),d1
    addq.w #1,(a0)
    lsl.w #3,d1
    move.l cur_text,a1
    add.w d1,a1
    move.l d0,(a1)+
    move.w d6,(a1)+
    move.w d3,(a1)
    movem.l (sp)+,d0-d3/d7/a2-a3
    bra.s .draw
.check:
    bsr text_cells_hit           ; kept: drawn again when a cell was restored or drawn over this frame
    movem.l (sp)+,d0-d3/d7/a2-a3
    tst.b text_hit
    beq .skip
.draw:
    ifd DEBUG
    addq.l #1,dbg_runs
    endc
    moveq #0,d4
    move.w d1,d4
    mulu #STRIDE,d4
    moveq #0,d5
    move.w d0,d5
    lsr.w #4,d5
    lsl.w #3,d5
    add.l d5,d4
    add.l work_base,d4           ; plane 0 of the first word
    and.w #15,d0
    or.w #$80,d0                 ; FXSR
    move.b d0,$ffff8a3d.w
    moveq #0,d5
    move.b d2,d5                 ; N
    lsl.w #3,d5
    neg.w d5
    add.w #STRIDE,d5
    move.w d5,$ffff8a30.w
    moveq #0,d5
    move.b d2,d5
    addq.w #1,d5                 ; the words a line
    move.w d5,$ffff8a36.w
    lea bd_lines_d,a0            ; (engine/rt/borders.s: the lines a piece of a pass reading the screen)
    moveq #0,d6
    move.b (a0,d5.w),d6
    bne.s .fits
    moveq #1,d6
.fits:
    lsr.w #8,d2                  ; the planes to draw
    lsl.w #3,d3                  ; bytes a block
    move.l a2,a1
    add.w d3,a1                  ; plane 0
    moveq #3,d0
.plane:
    move.l a2,$ffff8a24.w
    move.l d4,$ffff8a32.w
    move.b #4,$ffff8a3b.w        ; NOT mask AND screen
    bsr.s .pieces
    lsr.w #1,d2
    bcc.s .next_plane            ; (no pixel of the run in this plane)
    move.l a1,$ffff8a24.w
    move.l d4,$ffff8a32.w
    move.b #7,$ffff8a3b.w        ; pixels OR screen
    bsr.s .pieces
.next_plane:
    add.w d3,a1
    addq.l #2,d4
    dbf d0,.plane
.skip:
    dbf d7,.run
    bra.s .done
.pieces:
    ; the eight lines in HOG pieces of d6 (at most ~256 bus cycles each, engine/rt/borders.s)
    moveq #8,d1
.piece:
    move.w d6,d5
    cmp.w d1,d5
    bls.s .lines
    move.w d1,d5
.lines:
    move.w d5,$ffff8a38.w
    move.b #$c0,$ffff8a3c.w
    sub.w d5,d1
    bne.s .piece
    rts
.done:
    tst.b text_keep
    bne.s .kept
    move.w ring_index,d1         ; the ring's text record: what it shows (the rectangles it covers: cur_text)
    lea ring_txt_key1,a0
    move.w scroll_x,d0
    swap d0
    move.w scroll_y,d0
    move.l d0,(a0,d1.w)
    bsr text_key2
    lea ring_txt_key2,a0
    move.l d0,(a0,d1.w)
.kept:
.off:
    rts

; text_key2: d0 = text_gen, view_flip, 1 (what a ring's text was drawn from; the low byte: a record, keepable)
text_key2:
    move.w text_gen,d0
    swap d0
    move.b view_flip,d0
    lsl.w #8,d0
    move.b #1,d0
    rts

; text_prepare (before ring_restore): the text layer's rows; whether this ring keeps the text it shows (the same text,
; scroll and flip as when it was drawn there) - else its old text rectangles are restored and the text drawn whole.
text_prepare:
    addq.b #1,frame_tag
    clr.b text_keep
    btst #7,g_control
    bne.s .redo
    bsr text_scan
    move.w ring_index,d1
    lea ring_txt_key1,a0
    move.w scroll_x,d0
    swap d0
    move.w scroll_y,d0
    cmp.l (a0,d1.w),d0
    bne.s .redo
    bsr text_key2
    lea ring_txt_key2,a0
    cmp.l (a0,d1.w),d0
    bne.s .redo
    st text_keep
    ifd DEBUG
    addq.l #1,dbg_text_kept
    endc
    rts
.redo:
    move.w ring_index,d1
    lea ring_txt_key2,a0
    clr.l (a0,d1.w)
    move.l cur_text_count,a0     ; the ring's text rectangles to its restore list (ring_restore, next)
    move.w (a0),d5
    clr.w (a0)
    subq.w #1,d5
    bmi.s .restored
    move.l cur_text,a2
    move.l cur_rect_count,a0
    move.w (a0),d1
    move.w d1,d0
    add.w d5,d0
    addq.w #1,d0
    move.w d0,(a0)
    lsl.w #3,d1
    move.l cur_rect,a1
    add.w d1,a1
.old:
    ifd DEBUG
    addq.l #1,dbg_text_cells
    endc
    move.l (a2)+,(a1)+
    move.l (a2)+,(a1)+
    dbf d5,.old
.restored:
    rts

; text_cells_hit: cell d6 and the shape d3 (touch_cells) of a text run the ring keeps: text_hit when one of its cells
; was restored or drawn over this frame (restored_tag) or is on the damage list.  Uses d0-d2/a0/a1.
text_cells_hit:
    clr.b text_hit
    movem.l d3/d6,-(sp)
.row:
    lea restored_tag,a0
    move.l cur_flags,a1
    move.b frame_tag,d2
    move.w d3,d1
    lsr.w #8,d1
    move.w d6,d0
.col:
    cmp.b (a0,d0.w),d2
    beq.s .hit
    tst.b (a1,d0.w)
    bne.s .hit
    addq.w #1,d0
    dbf d1,.col
    add.w #COLS,d6
    bclr #0,d3
    bne.s .row
    bra.s .done
.hit:
    st text_hit
.done:
    movem.l (sp)+,d3/d6
    rts

char_get:
    movem.l d0-d7/a0-a6,-(sp)
    moveq #0,d0
    move.w object_code,d0
    moveq #0,d1
    move.w object_colour,d1
    move.l d1,d2
    lsl.w #8,d2
    lsl.w #3,d2
    or.w d0,d2
    btst #6,g_control
    beq.s .normal_key
    or.l #$10000,d2
.normal_key:
    lea palette_epoch+48,a0
    move.w d1,d4
    lsr.w #2,d4
    moveq #0,d3
    move.b (a0,d4.w),d3
    ror.l #8,d3
    or.l d3,d2
    or.l #$100000,d2
    move.w d0,d3
    and.w #127,d3
    move.w d3,d4
    lsl.w #2,d4
    lea char_cache_tags,a0
    cmp.l (a0,d4.w),d2
    beq .hit
    move.l d2,(a0,d4.w)
    mulu #192,d3
    lea char_cache,a1
    add.l d3,a1
    move.l a1,cache_result
    move.l d0,d3
    lsl.l #5,d3
    lea char_pixels,a0
    add.l d3,a0
    lea pen_map+$300,a2
    lsl.w #2,d1
    add.w d1,a2
    clr.b bake_flip
    clr.b bake_vflip
    btst #6,g_control
    beq.s .normal_pixels
    st bake_flip
    st bake_vflip
.normal_pixels:
    move.b #3,bake_transparent
    clr.b bake_limit
    move.w #8,bake_width
    move.w #8,bake_rows
    ifd SIM
    addq.l #1,bake_n_char
    endc
    bsr bake_pixels
    bra.s .done
.hit:
    mulu #192,d3
    lea char_cache,a1
    add.l d3,a1
    move.l a1,cache_result
.done:
    movem.l (sp)+,d0-d7/a0-a6
    move.l cache_result,a1
    rts
    section data,data
nibble_swap:                     ; (a byte with its two pixels swapped: the mirrored bakes)
NS set 0
    rept 256
    dc.b ((NS&15)<<4)|(NS>>4)
NS set NS+1
    endr
spread4:                         ; a pen's four plane bits, one a byte (plane 0 in the high byte)
SP4 set 0
    rept 16
    dc.l ((SP4&1)<<24)|((SP4&2)<<15)|((SP4&4)<<6)|((SP4&8)>>3)
SP4 set SP4+1
    endr
front_limits: dc.b 12,12,8,8,4,4,0,0,0,0,0,0,0,0,0,0
    even
ring_tables:
    dc.l dmg_flag0,dmg_list0,dmg_count0,applied0,strip_list0,strip_count0,rect_list0,rect_count0,text_list0,text_count0
    dc.l dmg_flag1,dmg_list1,dmg_count1,applied1,strip_list1,strip_count1,rect_list1,rect_count1,text_list1,text_count1
twin_offsets:
    dc.w -16,0,16,0,0,-16,0,16,-16,-16,-16,16,16,-16,16,16
row_cells:
    rept ROWS
    dc.w REPTN*COLS
    endr
strip_words:
    dc.w 0,1,2,18,19,20
strip_black:
    dc.w 0,1,19,20
strip_mask_tab:                  ; per word of the display window (2 and 18 set each frame)
    dc.w -1,-1,0
    dcb.w 15,0
    dc.w -1,-1,-1
palette_data: incbin "palette.bin"
rgb_map: incbin "rgb_map.bin"
tile_front: incbin "tile_front.bin"
    even
tile_pixels: incbin "tile_pixels.bin"
sprite_pixels: incbin "sprite_pixels.bin"
char_pixels: incbin "char_pixels.bin"
sprite_order: incbin "sprite_order.bin"
sprite_blank: incbin "sprite_blank.bin"
char_blank: incbin "char_blank.bin"
    even
    include "sprite_code.s"
    section bss,bss
ring_base: ds.l 2
clean_base: ds.l 1
work_base: ds.l 1
flip_addr: ds.l 1
cur_flags: ds.l 1                ; this ring's tables (ring_tables)
cur_list: ds.l 1
cur_count: ds.l 1
cur_applied: ds.l 1
cur_strip: ds.l 1
cur_strip_count: ds.l 1
cur_rect: ds.l 1
cur_rect_count: ds.l 1
cur_text: ds.l 1
cur_text_count: ds.l 1
ring_index: ds.w 1
strip_state: ds.l 2              ; per ring: the window word, the fine scroll and the first row of its last frame
frame_ready: ds.b 1
fine_scroll: ds.b 1
clip_mode: ds.b 1
front_band: ds.b 1
rect_all: ds.b 1
    even
fine_word: ds.w 1
sprite_x0: ds.w 1
fine_m16: ds.w 1
sprite_x16: ds.w 1
view_flip: ds.b 1
map_dirty: ds.b 1
epoch_changed: ds.b 1
prev_mode: ds.b 1
no_twins: ds.b 1
text_flip: ds.b 1
text_valid: ds.b 1
    even
scroll_x: ds.w 1
scroll_y: ds.w 1
physical_x: ds.w 1
physical_y: ds.w 1
strip_w0: ds.w 1
win_c0: ds.w 1
win_r0: ds.w 1
base_x: ds.w 1
base_y: ds.w 1
prev_c0: ds.w 1
prev_r0: ds.w 1
prev_base_x: ds.w 1
prev_base_y: ds.w 1
rect_c0: ds.w 1
rect_cols: ds.w 1
object_code: ds.w 1
object_colour: ds.w 1
object_x: ds.w 1
object_y: ds.w 1
object_source: ds.l 1
cache_result: ds.l 1
cache_key: ds.l 1
cell_keyv: ds.l 1
cell_src: ds.l 1
bake_stride: ds.w 1
bake_width: ds.w 1
bake_rows: ds.w 1
bake_pixel_count: ds.w 1
bake_row_count: ds.w 1
bake_vflip: ds.b 1
bake_flip: ds.b 1
bake_limit: ds.b 1
bake_transparent: ds.b 1
bake_byte: ds.b 1
bake_half: ds.b 1
    even
palette_epoch: ds.b 64
pen_next: ds.b 64                 ; per colour: the last epoch number given
pen_slot: ds.b 64                 ; per colour: the history slot written last
pen_hist_id: ds.w 64*PEN_HISTORY
pen_hist: ds.b 64*PEN_HISTORY*16
palette_dirty: ds.b 64
bake_lut: ds.l 48
byte_lut: ds.l 1
byte_lut_tags: ds.b 20*BYTE_LUTS
byte_luts: ds.b 2048*BYTE_LUTS
bake_calls: ds.l 1
    ifd SIM
bake_n_tile: ds.l 1                ; (perf_test frames: the bakes by kind)
bake_n_sprite: ds.l 1
bake_n_char: ds.l 1
    endc
pen_map: ds.b 1024
shown_pal: ds.w 16
palette_valid: ds.b 1
pal_dirty: ds.b 1
    even
palette_shadow: ds.b 2048
black_pal: ds.w 16
clean_tags: ds.l CELLS
cell_offsets: ds.l CELLS
cell_col: ds.b CELLS
cell_row: ds.b CELLS
cell_has_front: ds.b CELLS
front_flag: ds.b CELLS
dmg_flag0: ds.b CELLS
dmg_flag1: ds.b CELLS
    even
dmg_count0: ds.w 1
dmg_count1: ds.w 1
strip_count0: ds.w 1
strip_count1: ds.w 1
front_count: ds.w 1
dmg_list0: ds.w CELLS
dmg_list1: ds.w CELLS
applied0: ds.w CELLS
applied1: ds.w CELLS
strip_list0: ds.w 6*WIN_ROWS
strip_list1: ds.w 6*WIN_ROWS
front_list: ds.w CELLS
cell_front: ds.w CELLS*16
text_shadow: ds.b $800
run_list: ds.b TEXT_RUNS*12*28
text_runs: ds.w 28
text_roll: ds.w 1
text_relist: ds.b 1
text_keep: ds.b 1                ; this frame: the ring keeps its text, only runs over restored cells drawn
text_hit: ds.b 1
strip_changed: ds.b 1
frame_tag: ds.b 1
    even
text_gen: ds.w 1
ring_txt_key1: ds.l 2            ; per ring: the scroll its text was drawn at
ring_txt_key2: ds.l 2            ; text_gen, flip, valid
rect_count0: ds.w 1
rect_count1: ds.w 1
text_count0: ds.w 1
text_count1: ds.w 1
rect_list0: ds.b RECTS*8         ; a rectangle: the buffer offset of its first word (long), its first cell, its shape
rect_list1: ds.b RECTS*8
text_list0: ds.b TEXT_RUNS*28*8
text_list1: ds.b TEXT_RUNS*28*8
restored_tag: ds.b CELLS         ; the frame_tag of the last restore of each cell
    even
draw_list: ds.b TEXT_RUNS*12*28
text_force: ds.b 1
text_compare: ds.b 1              ; (set by the translated block copies to the text RAM)
text_rows_dirty: ds.b 64          ; (set by the translated stores: rows 0-31 codes, 32-63 attributes)
    even
row_tmp: ds.w 3*32
text_pool: ds.b TEXT_ROW_POOL*28
pool_next: ds.l 1
run_next: ds.l 1
run_count: ds.w 1
run_chars: ds.w 1
chars_left: ds.w 1
run_x0: ds.w 1
run_planes: ds.b 1
    even
row_y: ds.w 1
text_row: ds.w 1
pal_roll: ds.w 1
tile_cache_tags: ds.l TILE_ENTRIES
sprite_cache_tags: ds.l SPRITE_ENTRIES
char_cache_tags: ds.l 128
cache_tags_end:                   ; (epoch_wrap clears the tags above)
tile_victim: ds.b TILE_SETS
sprite_victim: ds.b SPRITE_SETS
    even
tile_cache: ds.b TILE_ENTRIES*192
sprite_cache: ds.b SPRITE_ENTRIES*128
char_cache: ds.b 128*192
bake_scratch: ds.b 192
    ifd DEBUG
dbg_restored: ds.l 1
dbg_draws: ds.l 1
dbg_checks: ds.l 1
dbg_sprites: ds.l 1
dbg_fronts: ds.l 1
dbg_runs: ds.l 1
dbg_text_cells: ds.l 1
dbg_full: ds.l 1
dbg_sprite_cells: ds.l 1
dbg_strip_cells: ds.l 1
dbg_ands: ds.l 1
    endc
; ring_area: 3*RING_SIZE+256 bytes, in blktiger.s (its first part in the data section)
    section text,code
