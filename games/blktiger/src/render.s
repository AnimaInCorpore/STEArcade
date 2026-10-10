; 768-pixel virtual screens, 256-pixel scroll pages inside a 544-line buffer.
; The camera moves the Shifter window.  A clean screen holds the background of
; the visible window (and its twins 16 cells away, ready for the next page);
; each of the two display rings restores only the cells on its damage list.
; Whole objects draw into hidden margins; the black side margins are masks
; kept per cell.
STRIDE = 384
RING_LINES = 544
TEXT_RUNS = 8                    ; runs a text row (at most 7: four blanks split a run)
TEXT_ROW_POOL = 2048             ; strip bytes a text row (at most about 2000)
TEXT_CELLS = 1280                ; text cells a ring records (with repeats: runs sharing a cell)
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
BYTE_LUTS = 16                   ; cached byte tables of bake_pixels (4 KB each)
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
    lea 24(a0),a0
.ring0:
    lea cur_flags,a1
    rept 6
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
    bsr sprite_pass
    bsr front_pass
    bsr character_pass
    bsr strip_mask
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
    bne.s .full_compare
    tst.b palette_valid
    beq.s .full_compare
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
    bne.s .full_compare
    rts
.full_compare:
    clr.b pal_dirty
    lea g_block+$5800,a0
    lea palette_shadow,a1
    move #511,d0
.compare_palette:
    cmpm.l (a0)+,(a1)+
    dbne d0,.compare_palette
    bne.s .changed
    tst.b palette_valid
    beq.s .map_palette
    rts
.changed:
    subq.l #4,a0
    subq.l #4,a1
.copy_palette:
    move.l (a0)+,(a1)+
    dbf d0,.copy_palette
.map_palette:
    st palette_valid
    lea palette_dirty,a0
    moveq #15,d0
.clear_dirty:
    clr.l (a0)+
    dbf d0,.clear_dirty
    lea g_block+$5800,a0
    lea g_block+$5c00,a1
    lea pen_map,a2
    lea rgb_map,a3
    lea palette_dirty,a4
    move #1023,d0
    moveq #0,d6
.next:
    moveq #0,d1
    move.b (a1)+,d1
    lsl.w #8,d1
    move.b (a0)+,d1
    and.w #$fff,d1
    move.b (a3,d1.w),d2
    cmp.b (a2),d2
    beq.s .same
    move.w d6,d3
    lsr.w #4,d3
    st (a4,d3.w)
.same:
    move.b d2,(a2)+
    addq.w #1,d6
    dbf d0,.next
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

; draw_at: cell_src (0: blank) with key cell_keyv into clean cell d6, both rings
; restore it.  Uses d0-d2/a0/a1/a3.
draw_at:
    move.w d6,d0
    lsl.w #2,d0
    lea clean_tags,a0
    move.l cell_keyv,(a0,d0.w)
    lea cell_offsets,a0
    move.l (a0,d0.w),d0
    move.l clean_base,a0
    add.l d0,a0
    move.l cell_src,d1
    beq .blank
    move.l d1,a1
    rept 16
    move.l (a1)+,REPTN*STRIDE(a0)
    move.l (a1)+,REPTN*STRIDE+4(a0)
    endr
    lea 32(a1),a1                ; the front masks
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
    rept 16
    clr.l REPTN*STRIDE(a0)
    clr.l REPTN*STRIDE+4(a0)
    endr
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

; The ring's damage list: copy the cells from the clean screen.
ring_restore:
    move.l cur_count,a0
    move.w (a0),d7
    clr.w (a0)
    subq.w #1,d7
    bmi .done
    move.l cur_list,a3
    move.l cur_flags,a4
    move.l cur_applied,a5
    lea cell_offsets,a6
    move.l clean_base,d4
    move.l work_base,d5
    lea restored_tag,a2
    move.b frame_tag,d1
.cell:
    move.w (a3)+,d6
    clr.b (a4,d6.w)
    move.b d1,(a2,d6.w)          ; (the text pass redraws the runs over restored cells)
    add.w d6,d6
    clr.w (a5,d6.w)
    add.w d6,d6
    move.l (a6,d6.w),d0
    move.l d4,a0
    add.l d0,a0
    move.l d5,a1
    add.l d0,a1
    rept 16
    move.l REPTN*STRIDE(a0),REPTN*STRIDE(a1)
    move.l REPTN*STRIDE+4(a0),REPTN*STRIDE+4(a1)
    endr
    dbf d7,.cell
.done:
    rts

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
; were go to the damage list (before the restore).
strip_unmask:
    move.b strip_w0+1,d0
    lsl.w #8,d0
    move.b fine_scroll,d0
    swap d0
    move.w win_r0,d0
    lea strip_state,a0
    add.w ring_index,a0
    cmp.l (a0),d0
    beq.s .done
    move.l d0,(a0)
    move.l cur_strip_count,a3
    move.w (a3),d7
    clr.w (a3)
    subq.w #1,d7
    bmi.s .done
    move.l cur_strip,a3
    move.l cur_applied,a4
.cell:
    move.w (a3)+,d6
    lea cell_col,a0
    moveq #0,d4
    move.b (a0,d6.w),d4
    lea cell_row,a0
    moveq #0,d5
    move.b (a0,d6.w),d5
    bsr strip_desired
    move.w d6,d0
    add.w d0,d0
    move.w (a4,d0.w),d1
    not.w d3
    and.w d3,d1
    beq.s .keep
    bsr mark_ring
.keep:
    dbf d7,.cell
.done:
    rts

; After all drawing: black the side margins where this ring's cells lack the mask.
strip_mask:
    move.l cur_strip,a3
    move.l cur_applied,a4
    lea cell_offsets,a5
    moveq #0,d7
    lea strip_words,a2
    moveq #5,d5
.column:
    move.w (a2)+,d0
    add.w d0,d0
    lea strip_mask_tab,a0
    move.w (a0,d0.w),d3
    beq .next_column
    move.w d3,d1
    swap d1
    move.w d3,d1
    not.l d1
    move.w strip_w0,d4
    add.w -2(a2),d4
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
    add.w d6,d6
    cmp.w (a4,d6.w),d3
    beq .masked
    move.w d3,(a4,d6.w)
    add.w d6,d6
    move.l (a5,d6.w),d0
    move.l work_base,a1
    add.l d0,a1
    rept 16
    and.l d1,REPTN*STRIDE(a1)
    and.l d1,REPTN*STRIDE+4(a1)
    endr
.masked:
    dbf d2,.row
.next_column:
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

; a0 packed pixels, a1 output planes, a2 colour LUT; masks at +128/+160.
bake_pixels:
    addq.l #1,bake_calls
    ; The byte table of this colour (two pixels a lookup): cached in BYTE_LUTS slots, valid while the colour's
    ; 16 pens, the transparent pen and the front limit are the same.
    move.l a2,d0
    lsr.w #4,d0
    and.w #BYTE_LUTS-1,d0
    move.w d0,d1
    mulu #20,d1
    lea byte_lut_tags,a5
    add.w d1,a5
    moveq #12,d1
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
    ; Expand this colour's sixteen pens once, then build two planes per long.
    lea bake_lut+64,a5
    lea mapped_bits,a6
    moveq #0,d0
.lut:
    move.w d0,d4
    lsl.w #2,d4
    moveq #0,d1
    moveq #0,d2
    moveq #0,d3
    cmp.b bake_transparent,d0
    beq.s .lut_save
    moveq #1,d3
    cmp.b bake_limit,d0
    bhs.s .lut_back
    or.l #$10000,d3
.lut_back:
    move.b (a2,d0.w),d1
    lsl.w #3,d1
    move.l 4(a6,d1.w),d2
    move.l (a6,d1.w),d1
.lut_save:
    move.l d1,-64(a5,d4.w)
    move.l d2,(a5,d4.w)
    move.l d3,64(a5,d4.w)
    addq.w #1,d0
    cmp.w #16,d0
    blo.s .lut
    ; byte b: its high pixel first (the first pixel shifted once more), entries of 16 bytes: planes 0/1, 2/3, mask
    move.l byte_lut,a4
    lea bake_lut+64,a3
    moveq #0,d0
.byte_hi:
    move.w d0,d4
    lsl.w #2,d4
    move.l -64(a3,d4.w),d1
    add.l d1,d1
    move.l (a3,d4.w),d2
    add.l d2,d2
    move.l 64(a3,d4.w),d3
    add.l d3,d3
    lea bake_lut,a6
    moveq #15,d5
.byte_lo:
    move.l (a6),d6
    or.l d1,d6
    move.l d6,(a4)+
    move.l 64(a6),d6
    or.l d2,d6
    move.l d6,(a4)+
    move.l 128(a6),d6
    or.l d3,d6
    move.l d6,(a4)+
    addq.l #4,a4
    addq.l #4,a6
    dbf d5,.byte_lo
    addq.w #1,d0
    cmp.w #16,d0
    blo.s .byte_hi
.rows:
    move.l byte_lut,a5
    lea nibble_swap,a6
    lea 128(a1),a3
    lea 160(a1),a4
    move.w bake_rows,bake_row_count
    move.w bake_width,d0
    lsr.w #1,d0
    move.w d0,bake_stride
    tst.b bake_vflip
    beq.s .row
    move.w bake_rows,d1
    subq.w #1,d1
    mulu d0,d1
    add.l d1,a0
.row:
    moveq #0,d2
    moveq #0,d3
    moveq #0,d5
    move.w bake_stride,d7
    subq.w #1,d7
    tst.b bake_flip
    beq.s .forward
    add.w bake_stride,a0
.reverse:
    moveq #0,d6
    move.b -(a0),d6
    move.b (a6,d6.w),d6          ; (mirrored: the low pixel first)
    lsl.w #4,d6
    lsl.l #2,d2
    lsl.l #2,d3
    lsl.l #2,d5
    or.l (a5,d6.w),d3
    or.l 4(a5,d6.w),d5
    or.l 8(a5,d6.w),d2
    dbf d7,.reverse
    add.w bake_stride,a0
    bra.s .save
.forward:
    moveq #0,d6
    move.b (a0)+,d6
    lsl.w #4,d6
    lsl.l #2,d2
    lsl.l #2,d3
    lsl.l #2,d5
    or.l (a5,d6.w),d3
    or.l 4(a5,d6.w),d5
    or.l 8(a5,d6.w),d2
    dbf d7,.forward
.save:
    cmp.w #8,bake_width
    bne.s .full
    lsl.l #8,d2
    lsl.l #8,d3
    lsl.l #8,d5
.full:
    swap d3
    move.w d3,(a1)+
    swap d3
    move.w d3,(a1)+
    swap d5
    move.w d5,(a1)+
    swap d5
    move.w d5,(a1)+
    move.w d2,(a3)+
    swap d2
    move.w d2,(a4)+
    tst.b bake_vflip
    beq.s .advance
    sub.w bake_stride,a0
    sub.w bake_stride,a0
.advance:
    subq.w #1,bake_row_count
    bne .row
    rts

; Front pens over the sprites: only the cells sprites touched, from the clean screen.
front_pass:
    move.w front_count,d7
    clr.w front_count
    subq.w #1,d7
    bmi .done
    lea front_list,a3
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

; A sprite's cells (2 by 2, 1 column when it is on a word, 1 row on a cell line) go to this
; ring's damage list; those with front pens to the front list.
mark_sprite:
    bsr.s object_cell
    bsr.s .row
    move.w object_y,d0
    and.w #15,d0
    beq.s .done
    add.w #COLS,d6
.row:
    bsr.s .one
    move.w object_x,d0
    and.w #15,d0
    beq.s .done
    addq.w #1,d6
    bsr.s .one
    subq.w #1,d6
.done:
    rts
.one:
    bsr mark_ring
    lea cell_has_front,a0
    tst.b (a0,d6.w)
    beq.s .no
    lea front_flag,a0
    tst.b (a0,d6.w)
    bne.s .no
    st (a0,d6.w)
    move.w front_count,d0
    addq.w #1,front_count
    add.w d0,d0
    lea front_list,a0
    move.w d6,(a0,d0.w)
.no:
    rts

; Sprites in descending RAM order; an entry with y = 0 is off the screen in both orientations.
sprite_pass:
    btst #2,g_video_enable
    bne .done
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
    cmp.w #-15,d2
    blt .skip
    cmp.w #256,d2
    bge .skip
    cmp.w #240,d3
    bge .skip
    cmp.w #1,d3
    blt .skip
    add.w physical_x,d2
    add.w #64,d2
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

sprite_get:
    movem.l d0-d7/a0-a6,-(sp)
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
    movem.l (sp)+,d0-d7/a0-a6
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
    move.w #2,$ffff8a20.w
    move.w #2,$ffff8a22.w
    move.w #8,$ffff8a2e.w
    move.w #$ffff,$ffff8a2a.w
    move.w #$0203,$ffff8a3a.w
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
    moveq #0,d0
    move.w object_code,d0
    btst #6,g_control
    beq.s .normal_stream
    add.w #4096,d0
.normal_stream:
    lsl.l #2,d0
    lea bt_sprite_streams,a0
    move.l (a0,d0.l),a0
    lea $ffff8a28.w,a2
    lea $ffff8a2c.w,a3
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
    beq.s .column
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
.char:
    move.w 2(a1),object_code
    move.w 4(a1),object_colour
    moveq #0,d0
    move.w (a1),d0
    sub.w run_x0,d0
    lsr.w #3,d0                  ; byte in the line
    move.l a1,-(sp)
    bsr char_get                 ; a1 = planes (pixels in the high bytes), +128 masks
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
    move.w (a3)+,d2              ; N
    move.w (a3)+,d3              ; bytes a line
    move.l (a3)+,a2              ; the mask block
    movem.l d0-d3/d7/a2-a3,-(sp)
    ; the cells: words x>>4 .. +N, lines y .. y+7 (text_cell: recorded, or checked when the ring keeps its text)
    clr.b text_hit
    move.w d0,object_x
    move.w d1,object_y
    bsr object_cell
    move.w d2,d5
.mark_top:
    bsr text_cell
    addq.w #1,d6
    dbf d5,.mark_top
    move.w object_y,d0
    and.w #15,d0
    cmp.w #8,d0
    bls.s .one_row
    add.w #COLS-1,d6
    sub.w d2,d6
    move.w d2,d5
.mark_bottom:
    bsr text_cell
    addq.w #1,d6
    dbf d5,.mark_bottom
.one_row:
    movem.l (sp)+,d0-d3/d7/a2-a3
    tst.b text_keep
    beq.s .draw
    tst.b text_hit
    beq .skip                    ; kept: none of its cells restored or drawn over this frame
.draw:
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
    move.w d2,d5
    addq.w #1,d5
    move.w d5,$ffff8a36.w
    move.w d2,d5
    lsl.w #3,d5
    neg.w d5
    add.w #STRIDE,d5
    move.w d5,$ffff8a30.w
    lsl.w #3,d3                  ; bytes a block
    move.l a2,a1
    add.w d3,a1                  ; plane 0
    moveq #3,d6
.plane:
    move.l a2,$ffff8a24.w
    move.l d4,$ffff8a32.w
    move.w #8,$ffff8a38.w
    move.b #4,$ffff8a3b.w        ; NOT mask AND screen
    jsr blit_go                  ; (up to ~17 x 8 words: in pieces)
    move.l a1,$ffff8a24.w
    move.l d4,$ffff8a32.w
    move.w #8,$ffff8a38.w
    move.b #7,$ffff8a3b.w        ; pixels OR screen
    jsr blit_go
    add.w d3,a1
    addq.l #2,d4
    dbf d6,.plane
.skip:
    dbf d7,.run
.done:
    tst.b text_keep
    bne.s .kept
    move.w ring_index,d1         ; the ring's text record: what it shows, the cells it covers
    lea ring_txt_count,a0
    move.l txt_list_ptr,d0
    sub.l txt_list_base,d0
    lsr.l #1,d0
    move.l d0,(a0,d1.w)
    lea ring_txt_key1,a0
    move.w scroll_x,d0
    swap d0
    move.w scroll_y,d0
    move.l d0,(a0,d1.w)
    bsr text_key2
    tst.b txt_overflow
    beq.s .whole
    move.b #2,d0                 ; (the list full, the rest in the damage list: restored, never kept)
.whole:
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
; scroll and flip as when it was drawn there) - else its old text cells are restored and the text drawn whole.
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
    lea ring_txt_lists,a2
    tst.w d1
    beq.s .ring0
    lea TEXT_CELLS*2(a2),a2
.ring0:
    move.l a2,txt_list_base
    move.l a2,txt_list_ptr
    lea TEXT_CELLS*2(a2),a0
    move.l a0,txt_list_end
    clr.b txt_overflow
    lea ring_txt_key2,a0
    tst.b 3(a0,d1.w)
    bne.s .restore               ; (1: a record, 2: one that overflowed, 0: none)
    rts
.restore:
    clr.l (a0,d1.w)
    lea ring_txt_count,a0
    move.l (a0,d1.w),d5
    subq.w #1,d5
    bmi.s .restored
.old:
    move.w (a2)+,d6              ; the old text cells to this ring's damage list
    bsr mark_ring
    dbf d5,.old
.restored:
    rts

; text_cell, cell d6 of a text run: drawing whole, the cell recorded for the ring (mark_ring when the list is full);
; keeping, text_hit set when the cell was restored or drawn over (a sprite: its flag in this ring's list) this frame.
text_cell:
    tst.b text_keep
    bne.s .check
    move.l txt_list_ptr,a0
    cmp.l txt_list_end,a0
    bhs.s .full
    move.w d6,(a0)+
    move.l a0,txt_list_ptr
    rts
.full:
    st txt_overflow
    bra mark_ring
.check:
    lea restored_tag,a0
    move.b frame_tag,d0
    cmp.b (a0,d6.w),d0
    beq.s .hit
    move.l cur_flags,a0
    tst.b (a0,d6.w)
    beq.s .done
.hit:
    st text_hit
.done:
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
mapped_bits: dc.l 0,0,65536,0,1,0,65537,0,0,65536,65536,65536,1,65536,65537,65536,0,1,65536,1,1,1,65537,1,0,65537,65536,65537,1,65537,65537,65537
front_limits: dc.b 12,12,8,8,4,4,0,0,0,0,0,0,0,0,0,0
    even
ring_tables:
    dc.l dmg_flag0,dmg_list0,dmg_count0,applied0,strip_list0,strip_count0
    dc.l dmg_flag1,dmg_list1,dmg_count1,applied1,strip_list1,strip_count1
twin_offsets:
    dc.w -16,0,16,0,0,-16,0,16,-16,-16,-16,16,16,-16,16,16
row_cells:
    rept ROWS
    dc.w REPTN*COLS
    endr
strip_words:
    dc.w 0,1,2,18,19,20
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
ring_index: ds.w 1
strip_state: ds.l 2              ; per ring: the window word, the fine scroll and the first row of its last frame
frame_ready: ds.b 1
fine_scroll: ds.b 1
view_flip: ds.b 1
map_dirty: ds.b 1
epoch_changed: ds.b 1
prev_mode: ds.b 1
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
byte_luts: ds.b 4096*BYTE_LUTS
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
txt_overflow: ds.b 1
frame_tag: ds.b 1
    even
text_gen: ds.w 1
txt_list_base: ds.l 1
txt_list_ptr: ds.l 1
txt_list_end: ds.l 1
ring_txt_key1: ds.l 2            ; per ring: the scroll its text was drawn at
ring_txt_key2: ds.l 2            ; text_gen, flip, valid
ring_txt_count: ds.l 2
ring_txt_lists: ds.w 2*TEXT_CELLS
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
ring_area: ds.b 3*RING_SIZE+256
    section text,code
