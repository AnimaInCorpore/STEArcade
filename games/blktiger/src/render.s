; 768-pixel virtual screens, 256-byte scroll pages inside a 512-line cache.
; The camera moves the Shifter window; tiles are refreshed by descriptor and
; only old object damage is restored. Whole objects have hidden guard space.
STRIDE = 384
RING_LINES = 544
RING_SIZE = STRIDE*RING_LINES
GUARD = 16*STRIDE
CELLS = 48*32
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
    move.l #clean_tags,a0
    move.l #(CELLS*3)/4-1,d0
    moveq #-1,d1
.tags:
    rept 4
    move.l d1,(a0)+
    endr
    subq.l #1,d0
    bpl.s .tags
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
    tst.w d0
    beq.s .ring0
    lea draw_tags1,a0
    lea damage1,a1
    bra.s .selected
.ring0:
    lea draw_tags0,a0
    lea damage0,a1
.selected:
    move.l a0,current_tags
    move.l a1,current_damage
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
    addq.w #3,d0                 ; 64 px hidden left margin, minus one guard tile
    move.w d0,first_col
    lsr.w #4,d1
    move.w d1,first_row
    bsr penmap_update
    bsr background_pass
    bsr sprite_pass
    bsr front_pass
    bsr character_pass
    bsr black_margins
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

penmap_update:
    lea g_block+$5800,a0
    lea palette_shadow,a1
    move #511,d0
    moveq #0,d2
.compare_palette:
    move.l (a0)+,d1
    cmp.l (a1),d1
    beq.s .palette_same
    moveq #1,d2
.palette_same:
    move.l d1,(a1)+
    dbf d0,.compare_palette
    tst.b palette_valid
    beq.s .map_palette
    tst.b d2
    bne.s .map_palette
    rts
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
    addq.b #1,(a1)
    bne.s .unchanged
    ; Epoch wrap must not resurrect stale cache entries.
    movem.l d0/a0-a1,-(sp)
    lea clean_tags,a0
    move.l #(CELLS*3)/4-1,d0
    moveq #-1,d1
.invalidate:
    rept 4
    move.l d1,(a0)+
    endr
    subq.l #1,d0
    bpl.s .invalidate
    lea tile_cache_tags,a0
    move #128*3-1,d0
.clear:
    clr.l (a0)+
    dbf d0,.clear
    movem.l (sp)+,d0/a0-a1
.unchanged:
    addq.l #1,a1
    dbf d0,.epochs
    rts

; cell_address: physical cell in bg_col/bg_row -> d0 cell index, a0 clean, a1 draw.
cell_address:
    moveq #0,d0
    move.w bg_row,d0
    mulu #48,d0
    add.w bg_col,d0
    moveq #0,d1
    move.w bg_row,d1
    mulu #16*STRIDE,d1
    moveq #0,d2
    move.w bg_col,d2
    lsl.w #3,d2
    add.l d2,d1
    move.l clean_base,a0
    add.l d1,a0
    move.l work_base,a1
    add.l d1,a1
    rts

; tile_descriptor: world map -> d0 variant code, d1 colour, d2 cache key.
tile_descriptor:
    btst #6,g_control
    bne.s .flipped_map
    move.w scroll_x,d0
    and.w #$ff00,d0
    lsr.w #4,d0
    add.w bg_col,d0
    subq.w #4,d0
    move.w scroll_y,d1
    and.w #$ff00,d1
    lsr.w #4,d1
    add.w bg_row,d1
    bra.s .map
.flipped_map:
    move.w scroll_x,d0
    add.w physical_x,d0
    lsr.w #4,d0
    add.w #19,d0
    sub.w bg_col,d0
    move.w scroll_y,d1
    add.w physical_y,d1
    lsr.w #4,d1
    add.w #15,d1
    sub.w bg_row,d1
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
    btst #6,g_control
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

background_pass:
    move.w first_row,bg_row
    move.w #16,row_count
.rows:
    move.w first_col,bg_col
    move.w #19,col_count
.cols:
    bsr tile_descriptor
    btst #1,g_video_enable
    beq.s .enabled
    moveq #0,d2
.enabled:
    move.l d2,bg_key
    bsr cell_address
    move.w d0,bg_cell
    lsl.w #2,d0
    lea clean_tags,a2
    move.l bg_key,d2
    cmp.l (a2,d0.w),d2
    beq.s .restore
    move.l d2,(a2,d0.w)
    move.l a0,bg_destination
    tst.l d2
    beq.s .clear_tile
    bsr tile_descriptor
    bsr tile_get
    move.l bg_destination,a0
    lea 160(a1),a2
    moveq #15,d0
.write:
    move.w (a2)+,d1
    not.w d1
    moveq #3,d2
.planes:
    move.w (a1)+,d3
    and.w d1,d3
    move.w d3,(a0)+
    dbf d2,.planes
    lea STRIDE-8(a0),a0
    dbf d0,.write
    bra.s .restore
.clear_tile:
    move.l bg_destination,a0
    moveq #15,d0
.clear:
    clr.l (a0)
    clr.l 4(a0)
    lea STRIDE(a0),a0
    dbf d0,.clear
.restore:
    moveq #0,d0
    move.w bg_cell,d0
    move.l current_damage,a2
    tst.b (a2,d0.w)
    bne.s .copy
    lsl.w #2,d0
    move.l current_tags,a2
    move.l bg_key,d1
    cmp.l (a2,d0.w),d1
    beq.s .next
.copy:
    bsr cell_address
    moveq #15,d1
.copy_rows:
    move.l (a0),(a1)
    move.l 4(a0),4(a1)
    lea STRIDE(a0),a0
    lea STRIDE(a1),a1
    dbf d1,.copy_rows
    moveq #0,d0
    move.w bg_cell,d0
    move.l current_damage,a2
    clr.b (a2,d0.w)
    lsl.w #2,d0
    move.l current_tags,a2
    move.l bg_key,(a2,d0.w)
.next:
    addq.w #1,bg_col
    subq.w #1,col_count
    bpl .cols
    addq.w #1,bg_row
    subq.w #1,row_count
    bpl .rows
    rts

; Cache lookups preserve all caller registers except returned a1.
tile_get:
    movem.l d0-d7/a0-a6,-(sp)
    move.l d2,cache_key
    move.w d0,d3
    and.w #127,d3
    move.w d3,d4
    lsl.w #2,d4
    lea tile_cache_tags,a0
    cmp.l (a0,d4.w),d2
    beq .hit
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
    bsr bake_pixels
    bra.s .done
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
    move.w d6,d4
    and.w #15,d4
    bsr.s .accumulate
    move.w d6,d4
    lsr.w #4,d4
    bsr.s .accumulate
    dbf d7,.reverse
    add.w bake_stride,a0
    bra.s .save
.forward:
    moveq #0,d6
    move.b (a0)+,d6
    move.w d6,d4
    lsr.w #4,d4
    bsr.s .accumulate
    move.w d6,d4
    and.w #15,d4
    bsr.s .accumulate
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
.accumulate:
    lsl.w #2,d4
    add.l d2,d2
    add.l d3,d3
    add.l d5,d5
    or.l -64(a5,d4.w),d3
    or.l (a5,d4.w),d5
    or.l 64(a5,d4.w),d2
    rts

front_pass:
    btst #1,g_video_enable
    bne .done
    move.w first_row,bg_row
    move.w #16,row_count
.rows:
    move.w first_col,bg_col
    move.w #19,col_count
.cols:
    bsr tile_descriptor
    cmp.w #6,d1
    bhs.s .next
    move.w d0,d3
    and.w #2047,d3
    lea tile_front,a0
    move.b (a0,d3.w),d3
    moveq #2,d4
    lsr.w #1,d1
    sub.w d1,d4
    btst d4,d3
    beq .next
    add.w d1,d1
    ; Recover the exact colour (odd colours share the same split mask).
    bsr tile_descriptor
    bsr tile_get
    move.l a1,front_source
    bsr cell_address
    move.l a1,a0
    move.l front_source,a1
    lea 160(a1),a2
    moveq #15,d0
.row:
    move.w (a2)+,d1
    beq.s .empty
    move.w d1,d4
    not.w d4
    moveq #3,d2
.plane:
    move.w (a1)+,d3
    and.w d1,d3
    and.w d4,(a0)
    or.w d3,(a0)+
    dbf d2,.plane
    lea STRIDE-8(a0),a0
    bra.s .row_next
.empty:
    addq.l #8,a1
    lea STRIDE(a0),a0
.row_next:
    dbf d0,.row
    move.l current_damage,a0
    moveq #0,d0
    move.w bg_row,d0
    mulu #48,d0
    add.w bg_col,d0
    st (a0,d0.w)
.next:
    addq.w #1,bg_col
    subq.w #1,col_count
    bpl .cols
    addq.w #1,bg_row
    subq.w #1,row_count
    bpl .rows
.done:
    rts

; Whole-object damage, physical pixel x/y in object_x/object_y.
mark_damage:
    move.w object_x,d0
    lsr.w #4,d0
    move.w object_y,d1
    lsr.w #4,d1
    mulu #48,d1
    add.w d0,d1
    move.l current_damage,a0
    st (a0,d1.w)
    st 1(a0,d1.w)
    st 48(a0,d1.w)
    st 49(a0,d1.w)
    rts

sprite_pass:
    btst #2,g_video_enable
    bne .done
    move.w #$1fc,sprite_offset
.next:
    lea bt_sprites,a0
    move.w sprite_offset,d0
    moveq #0,d1
    move.b 1(a0,d0.w),d1
    moveq #0,d2
    move.b 3(a0,d0.w),d2
    btst #4,d1
    beq.s .positive
    sub.w #256,d2
.positive:
    moveq #0,d3
    move.b 2(a0,d0.w),d3
    btst #6,g_control
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
    move.b (a0,d0.w),d2
    move.w d1,d3
    and.w #$e0,d3
    lsl.w #3,d3
    or.w d3,d2
    btst #3,d1
    beq.s .unflipped
    add.w #2048,d2
.unflipped:
    move.w d2,object_code
    and.w #7,d1
    move.w d1,object_colour
    lea sprite_blank,a0
    tst.b (a0,d2.w)
    bne .skip
    bsr sprite_get
    move.l a1,object_source
    bsr mark_damage
    bsr sprite_blit
.skip:
    subq.w #4,sprite_offset
    bpl .next
.done:
    rts

sprite_get:
    movem.l d0-d7/a0-a6,-(sp)
    moveq #0,d0
    move.w object_code,d0
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
    move.w d0,d3
    and.w #127,d3
    move.w d3,d4
    lsl.w #2,d4
    lea sprite_cache_tags,a0
    cmp.l (a0,d4.w),d2
    beq .hit
    move.l d2,(a0,d4.w)
    lsl.w #7,d3
    lea sprite_cache,a1
    add.w d3,a1
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
    lsl.w #7,d3
    lea sprite_cache,a1
    add.w d3,a1
    move.l a1,cache_result
.done:
    movem.l (sp)+,d0-d7/a0-a6
    move.l cache_result,a1
    rts

sprite_blit:
    moveq #0,d0
    move.w object_y,d0
    mulu #STRIDE,d0
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

character_pass:
    btst #7,g_control
    bne .done
    clr.w char_offset
.next:
    lea g_block+$5000,a0
    move.w char_offset,d0
    moveq #0,d1
    lea $400(a0),a1
    move.b (a1,d0.w),d1
    moveq #0,d2
    move.b (a0,d0.w),d2
    move.w d1,d3
    and.w #$e0,d3
    lsl.w #3,d3
    or.w d3,d2
    lea char_blank,a0
    tst.b (a0,d2.w)
    bne .skip
    move.w d2,object_code
    and.w #31,d1
    move.w d1,object_colour
    cmp.w #64,d0
    blo .skip
    cmp.w #960,d0
    bhs .skip
    move.w d0,d1
    and.w #31,d1
    lsl.w #3,d1
    btst #6,g_control
    beq.s .normal_char_x
    neg.w d1
    add.w #248,d1
.normal_char_x:
    add.w physical_x,d1
    add.w #64,d1
    move.w d1,object_x
    lsr.w #5,d0
    lsl.w #3,d0
    btst #6,g_control
    beq.s .normal_char_y
    neg.w d0
    add.w #248,d0
.normal_char_y:
    add.w physical_y,d0
    move.w d0,object_y
    bsr char_get
    move.l a1,object_source
    bsr mark_damage
    bsr char_blit
.skip:
    addq.w #1,char_offset
    cmp.w #1024,char_offset
    blo .next
.done:
    rts
char_get:
    movem.l d0-d7/a0-a6,-(sp)
    moveq #0,d0
    move.w object_code,d0
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
char_blit:
    move.l object_source,a1
    lea 128(a1),a2
    moveq #0,d0
    move.w object_y,d0
    mulu #STRIDE,d0
    move.w object_x,d1
    move.w d1,d5
    and.w #15,d5
    and.w #$fff0,d1
    lsr.w #1,d1
    add.l d1,d0
    move.l work_base,a0
    add.l d0,a0
    moveq #7,d0
.row:
    moveq #0,d1
    move.w (a2)+,d1
    swap d1
    lsr.l d5,d1
    move.l d1,d2
    not.l d2
    moveq #3,d3
.plane:
    moveq #0,d4
    move.w (a1)+,d4
    swap d4
    lsr.l d5,d4
    and.l d1,d4
    and.w d2,8(a0)
    or.w d4,8(a0)
    swap d2
    swap d4
    and.w d2,(a0)
    or.w d4,(a0)+
    swap d2
    dbf d3,.plane
    lea STRIDE-8(a0),a0
    dbf d0,.row
    rts

; Clear the hardware viewport's extra 32 pixels on both sides. This is a
; screen-fixed overlay; it never clips objects before they are drawn whole.
black_margins:
    move.w physical_x,d0
    add.w #32,d0
    move.w d0,object_x
    bsr clear_strip
    move.w physical_x,d0
    add.w #320,d0
    move.w d0,object_x
    bsr clear_strip
    rts
clear_strip:
    move.w physical_y,d0
    add.w #16,d0
    move.w d0,object_y
    mulu #STRIDE,d0
    move.w object_x,d1
    move.w d1,d2
    and.w #15,d2
    and.w #$fff0,d1
    lsr.w #1,d1
    add.l d1,d0
    move.l work_base,a0
    add.l d0,a0
    moveq #-1,d3
    lsr.w d2,d3
    move.w d3,d4
    not.w d4
    move.w #223,d0
.row:
    moveq #3,d1
.plane:
    and.w d4,(a0)
    clr.w 8(a0)
    and.w d3,16(a0)
    addq.l #2,a0
    dbf d1,.plane
    lea STRIDE-8(a0),a0
    dbf d0,.row
    ; Both strips touch tile columns outside the game; restore them next use.
    move.w object_y,d1
    lsr.w #4,d1
    move.w #14,d2
.damage:
    move.w d1,d0
    mulu #48,d0
    move.w object_x,d3
    lsr.w #4,d3
    add.w d3,d0
    move.l current_damage,a0
    st (a0,d0.w)
    st 1(a0,d0.w)
    st 2(a0,d0.w)
    addq.w #1,d1
    dbf d2,.damage
    rts

    section data,data
mapped_bits: dc.l 0,0,65536,0,1,0,65537,0,0,65536,65536,65536,1,65536,65537,65536,0,1,65536,1,1,1,65537,1,0,65537,65536,65537,1,65537,65537,65537
front_limits: dc.b 12,12,8,8,4,4,0,0,0,0,0,0,0,0,0,0
    even
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
ring_index: ds.w 1
frame_ready: ds.b 1
fine_scroll: ds.b 1
scroll_x: ds.w 1
scroll_y: ds.w 1
physical_x: ds.w 1
physical_y: ds.w 1
first_col: ds.w 1
first_row: ds.w 1
bg_col: ds.w 1
bg_row: ds.w 1
bg_cell: ds.w 1
row_count: ds.w 1
col_count: ds.w 1
sprite_offset: ds.w 1
char_offset: ds.w 1
object_code: ds.w 1
object_colour: ds.w 1
object_x: ds.w 1
object_y: ds.w 1
object_source: ds.l 1
current_tags: ds.l 1
current_damage: ds.l 1
cache_result: ds.l 1
cache_key: ds.l 1
bg_key: ds.l 1
bg_destination: ds.l 1
front_source: ds.l 1
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
palette_dirty: ds.b 64
bake_lut: ds.l 48
bake_calls: ds.l 1
pen_map: ds.b 1024
shown_pal: ds.w 16
palette_valid: ds.b 1
    even
palette_shadow: ds.b 2048
black_pal: ds.w 16
clean_tags: ds.l CELLS
draw_tags0: ds.l CELLS
draw_tags1: ds.l CELLS
damage0: ds.b CELLS
damage1: ds.b CELLS
tile_cache_tags: ds.l 128
sprite_cache_tags: ds.l 128
char_cache_tags: ds.l 128
tile_cache: ds.b 128*192
sprite_cache: ds.b 128*128
char_cache: ds.b 128*192
bake_scratch: ds.b 192
ring_area: ds.b 3*RING_SIZE+256
    section text,code
