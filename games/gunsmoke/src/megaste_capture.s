; Diagnostic only. Copy a completed, unpublished picture and its reference state.
; No disk access while the game owns the display. The source has 512-pixel rows;
; retain 336 pixels so every fine-scroll value has all 320 displayed pixels.
MC_HEAD = 96
MC_RAWSTRIDE = 168
MC_RAW = MC_RAWSTRIDE*256
MC_STATE = 2048+512
MC_SLOT = MC_HEAD+MC_RAW+MC_STATE
MC_BMP = 118+160*256

	section text,code
mc_capture_frame:
	movem.l d0-d7/a0-a6,-(sp)
	cmp.w #3,mc_n
	bhs .done
	tst.b mc_pending
	bne.s .capture
	tst.w mc_n
	bne .done
	cmp.w #700,isr_count
	blo .done
.capture:
	clr.b mc_pending
	moveq #0,d0
	move.w mc_n,d0
	mulu #MC_SLOT,d0
	lea mc_slots,a3
	add.l d0,a3
	move.l #'GSF3',(a3)
	move.w #3,4(a3)
	moveq #0,d0
	move.b flip_fine,d0
	move.w d0,6(a3)
	moveq #0,d0
	move.w isr_count,d0
	move.l d0,8(a3)
	move.l draw_base,12(a3)
	move.l flip_addr,16(a3)
	move.b Z_LATCH,20(a3)
	move.b Z_LAYERS,21(a3)
	move.b Z_SCROLL,22(a3)
	move.b Z_SCROLL+1,23(a3)
	move.b Z_SCROLL+2,24(a3)
	tst.b mt_mega
	beq.s .no_mega
	move.b $ffff8e21.w,25(a3)
.no_mega:
	move.w draw_idx,26(a3)
	move.w #MC_RAWSTRIDE,28(a3)
	move.w #336,30(a3)
	move.w #256,32(a3)
	move.b $ffff820f.w,34(a3)
	move.b $ffff8265.w,35(a3)
	lea start(pc),a0
	move.l a0,36(a3)
	move.l frame_counter,40(a3)
	move.w mc_n,44(a3)
	lea shown_pal,a0
	lea 48(a3),a1
	moveq #7,d0
.palette:
	move.l (a0)+,(a1)+
	dbf d0,.palette
	move.l draw_base,a0
	moveq #0,d0
	move.w cur_hw,d0
	lsr.w #4,d0
	lsl.w #3,d0
	add.l d0,a0
	lea MC_HEAD(a3),a1
	move.w #255,d1
.row:
	moveq #MC_RAWSTRIDE/4-1,d0
.words:
	move.l (a0)+,(a1)+
	dbf d0,.words
	adda.w #STRIDE-MC_RAWSTRIDE,a0
	dbf d1,.row
	lea Z_TEXT,a0
	move.w #2048/4-1,d0
.text:
	move.l (a0)+,(a1)+
	dbf d0,.text
	lea sprite_buffer,a0
	move.w #512/4-1,d0
.sprites:
	move.l (a0)+,(a1)+
	dbf d0,.sprites
	addq.w #1,mc_n
.done:
	movem.l (sp)+,d0-d7/a0-a6
	rts

; Called after hardware/CPU restoration, before writing the text report.
mc_finish:
	clr.w mc_write_slot
.next:
	moveq #0,d0
	move.w mc_write_slot,d0
	cmp.w mc_n,d0
	bhs .done
	add.b #'0',d0
	move.b d0,mc_name+5
	move.b #'B',mc_name+7
	move.b #'I',mc_name+8
	move.b #'N',mc_name+9
	moveq #0,d0
	move.w mc_write_slot,d0
	mulu #MC_SLOT,d0
	lea mc_slots,a3
	add.l d0,a3
	lea mc_name,a0
	move.l a3,a1
	move.l #MC_SLOT,d0
	bsr mc_write_file
	bsr mc_bmp
	move.b #'B',mc_name+7
	move.b #'M',mc_name+8
	move.b #'P',mc_name+9
	lea mc_name,a0
	lea mc_bitmap,a1
	move.l #MC_BMP,d0
	bsr mc_write_file
	addq.w #1,mc_write_slot
	bra .next
.done:
	rts

; a3 = one captured slot. Generate a standard bottom-up 4bpp Windows BMP.
mc_bmp:
	lea mc_bmp_header,a0
	lea mc_bitmap,a1
	moveq #118/2-1,d0
.header:
	move.w (a0)+,(a1)+
	dbf d0,.header
	lea 48(a3),a0
	lea mc_bitmap+54,a1
	moveq #15,d4
.palette:
	move.w (a0)+,d0
	bsr mc_component
	move.b d1,(a1)+	; blue, green, red, zero
	lsr.w #4,d0
	bsr mc_component
	move.b d1,(a1)+
	lsr.w #4,d0
	bsr mc_component
	move.b d1,(a1)+
	clr.b (a1)+
	dbf d4,.palette
	lea MC_HEAD(a3),a2
	adda.l #255*MC_RAWSTRIDE,a2
	lea mc_bitmap+118,a1
	move.w #255,d6
.row:
	move.l a2,a0
	move.w 6(a3),d5
	moveq #15,d0
	sub.w d5,d0
	move.w d0,d5
	move.w #159,d4
.pair:
	bsr mc_pixel
	lsl.b #4,d7
	move.b d7,(a1)
	bsr mc_pixel
	or.b d7,(a1)+
	dbf d4,.pair
	suba.w #MC_RAWSTRIDE,a2
	dbf d6,.row
	rts

mc_component:
	move.w d0,d1
	and.w #7,d1
	add.w d1,d1
	btst #3,d0
	beq.s .even
	addq.w #1,d1
.even:
	move.w d1,d2
	lsl.w #4,d1
	add.w d2,d1
	rts

mc_pixel:
	moveq #0,d7
	move.w (a0),d0
	btst d5,d0
	beq.s .p1
	bset #0,d7
.p1:
	move.w 2(a0),d0
	btst d5,d0
	beq.s .p2
	bset #1,d7
.p2:
	move.w 4(a0),d0
	btst d5,d0
	beq.s .p3
	bset #2,d7
.p3:
	move.w 6(a0),d0
	btst d5,d0
	beq.s .next
	bset #3,d7
.next:
	subq.w #1,d5
	bpl.s .same
	moveq #15,d5
	addq.l #8,a0
.same:
	rts

; a0 path, a1 bytes, d0 length. Preserve all registers; record any save failure.
mc_write_file:
	movem.l d0-d7/a0-a6,-(sp)
	move.l a1,a4
	move.l d0,d5
	clr.w -(sp)
	move.l a0,-(sp)
	move.w #$3c,-(sp)
	trap #1
	addq.l #8,sp
	tst.l d0
	bmi.s .bad
	move.w d0,d6
	move.l a4,-(sp)
	move.l d5,-(sp)
	move.w d6,-(sp)
	move.w #$40,-(sp)
	trap #1
	lea 12(sp),sp
	cmp.l d5,d0
	beq.s .close
	addq.w #1,mc_save_bad
.close:
	move.w d6,-(sp)
	move.w #$3e,-(sp)
	trap #1
	addq.l #4,sp
	tst.l d0
	bpl.s .done
.bad:
	addq.w #1,mc_save_bad
.done:
	movem.l (sp)+,d0-d7/a0-a6
	rts

	section data,data
mc_report_text: dc.b 'RAM captures / save errors (hex): ',0
mc_name: dc.b 'GSCAP0.BIN',0
	even
mc_bmp_header:
	dc.b 'BM',$76,$a0,0,0,0,0,0,0,118,0,0,0
	dc.b 40,0,0,0,$40,1,0,0,0,1,0,0,1,0,4,0
	dc.b 0,0,0,0,0,$a0,0,0,0,0,0,0,0,0,0,0,16,0,0,0,16,0,0,0
	dcb.b 64,0
	section bss,bss
mc_n: ds.w 1
mc_save_bad: ds.w 1
mc_write_slot: ds.w 1
mc_pending: ds.b 1
	even
mc_slots: ds.b 3*MC_SLOT
mc_bitmap: ds.b MC_BMP
	even
	section text,code
