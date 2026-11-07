; Countdown overlay, drawn by the CPU. No Blitter register or OS call is used
; during updates. Save/restore ACTUAL underlying pixels, never reference pixels.
; Fixed durations use a deadline; automatic work uses an explicitly estimated ETA.
	section text
progress_begin:
	movem.l d0-d7/a0-a6,-(sp)
	bsr progress_hide
	move.w d0,progress_stage
	move.w d0,d3
	add.b #'0',d3
	cmp.b #'9',d3
	bls .stage_char
	addq.b #7,d3
.stage_char:
	move.b d3,progress_string
	cmp.w #11,d0
	beq .no_title
	move.l d0,d3
	lsl.w #2,d3
	lea progress_titles,a0
	move.l (a0,d3.w),a0
	movem.l d0-d2,-(sp)
	bsr print
	movem.l (sp)+,d0-d2
.no_title:
	move.w d1,progress_total
	clr.w progress_done
	move.w d2,progress_fixed
	move.l $4ba.w,progress_start
	move.l $4ba.w,progress_next
	moveq #0,d0
	move.w d1,d0
	mulu #200,d0
	add.l progress_start,d0
	move.l d0,progress_deadline
	st progress_active
	clr.w progress_origin
	movem.l (sp)+,d0-d7/a0-a6
	bsr progress_update
	rts
progress_unit:
	addq.w #1,progress_done
	bra progress_update
progress_update:
	movem.l d0-d7/a0-a6,-(sp)
	tst.b progress_active
	beq .out
	move.l $4ba.w,d0
	cmp.l progress_next,d0
	blo .out
	add.l #200,d0
	move.l d0,progress_next
	bsr progress_hide
	tst.w progress_fixed
	beq .estimate
	move.l progress_deadline,d0
	sub.l $4ba.w,d0
	bpl .ticks
	moveq #0,d0
.ticks:
	add.l #199,d0
	divu #200,d0
	and.l #65535,d0
	move.b #'-',progress_string+1
	bra .format
.estimate:
	move.b #'~',progress_string+1
	moveq #0,d3
	move.w progress_done,d3
	moveq #0,d4
	move.w progress_total,d4
	sub.w d3,d4
	moveq #0,d0
	tst.w d4
	ble .format
	tst.w d3
	beq .unknown
	move.l $4ba.w,d0
	sub.l progress_start,d0
	add.l #199,d0
	divu #200,d0
	and.l #65535,d0
	mulu d4,d0
	; DIVU quotient must fit a word. Clamp huge first-sample ETAs.
	move.l d0,d1
	swap d1
	cmp.w d3,d1
	bhs .unknown
	divu d3,d0
	and.l #65535,d0
	tst.w d0
	bne .format
	moveq #1,d0
	bra .format
.unknown:
	move.l #$2d2d2d2d,progress_string+2
	bra .draw_overlay
.format:
	cmp.l #9999,d0
	bls .number
	move.l #9999,d0
.number:
	lea progress_string+2,a0
	moveq #3,d4
	lea progress_powers,a1
.digit:
	move.w (a1)+,d1
	moveq #'0',d2
.subtract:
	cmp.w d1,d0
	blo .put
	sub.w d1,d0
	addq.b #1,d2
	bra .subtract
.put:
	move.b d2,(a0)+
	dbf d4,.digit
.draw_overlay:
	; The only supported display modes are low/medium, both 160 bytes/line.
	moveq #4,d6
	tst.b $ffff8260.w
	beq .low
	moveq #2,d6
.low:
	move.w d6,progress_planes
	moveq #0,d0
	move.b $ffff8201.w,d0
	lsl.l #8,d0
	move.b $ffff8203.w,d0
	lsl.l #8,d0
	move.b $ffff820d.w,d0
	move.w progress_origin,d1
	addq.w #8,d1
	mulu #160,d1
	add.l d1,d0
	add.l #128,d0
	move.l d0,progress_target
	move.l d0,a0
	lea progress_underlay,a1
	moveq #7,d7
.save_row:
	move.w d6,d5
	lsl.w #2,d5
	subq.w #1,d5
.save_word:
	move.w (a0)+,(a1)+
	dbf d5,.save_word
	move.w d6,d5
	lsl.w #3,d5
	move.w #160,d4
	sub.w d5,d4
	add.w d4,a0
	dbf d7,.save_row
	st progress_visible
	moveq #0,d7
.row:
	move.l progress_target,a0
	move.w d7,d0
	mulu #160,d0
	add.l d0,a0
	lea progress_string,a1
	moveq #3,d5
.pair:
	moveq #0,d4
	moveq #1,d3
.char:
	moveq #0,d0
	move.b (a1)+,d0
	bsr progress_glyph
	lsl.w #8,d4
	or.w d0,d4
	dbf d3,.char
	moveq #0,d2
.plane:
	move.w d4,d0
	cmp.w #3,d2
	bne .ink
	moveq #0,d0		; low-res ink colour 7, background colour 0
.ink:
	move.w d0,(a0)+
	addq.w #1,d2
	cmp.w d6,d2
	blo .plane
	dbf d5,.pair
	addq.w #1,d7
	cmp.w #8,d7
	blo .row
.out:
	movem.l (sp)+,d0-d7/a0-a6
	rts
progress_glyph:
	; Compact 8x8 font, characters 0..9, T, ~, -, s and space.
	sub.w #'0',d0
	cmp.w #9,d0
	bls .indexed
	moveq #10,d0
	cmp.b #'T',-1(a1)
	beq .indexed
	moveq #11,d0
	cmp.b #'~',-1(a1)
	beq .indexed
	moveq #12,d0
	cmp.b #'-',-1(a1)
	beq .indexed
	moveq #13,d0
	cmp.b #'s',-1(a1)
	beq .indexed
	moveq #15,d0
	cmp.b #'A',-1(a1)
	beq .indexed
	moveq #16,d0
	cmp.b #'B',-1(a1)
	beq .indexed
	moveq #14,d0
.indexed:
	lsl.w #3,d0
	add.w d7,d0
	lea progress_font,a2
	move.b (a2,d0.w),d0
	and.w #255,d0
	rts
progress_hide:
	movem.l d0-d2/a0-a1,-(sp)
	tst.b progress_visible
	beq .out
	move.l progress_target,a0
	lea progress_underlay,a1
	moveq #7,d0
.row:
	move.w progress_planes,d1
	lsl.w #2,d1
	subq.w #1,d1
.word:
	move.w (a1)+,(a0)+
	dbf d1,.word
	move.w progress_planes,d1
	lsl.w #3,d1
	move.w #160,d2
	sub.w d1,d2
	add.w d2,a0
	dbf d0,.row
	sf progress_visible
.out:
	movem.l (sp)+,d0-d2/a0-a1
	rts
progress_end:
	clr.w progress_done
	clr.b progress_active
	bra progress_hide
	section data
progress_titles:
	dc.l pt0,pt1,pt2,pt3,pt4,pt5,pt6,pt7,pt8,pt9,pt10,pt11
pt0: dc.b 27,'Y',54,32,27,'K','0: TOS keyboard baseline',0
pt1: dc.b 27,'E','1: CPU arithmetic and code fetch',13,10,0
pt2: dc.b 27,'E','2: Private RAM - 37 patterns + lanes',13,10,0
pt3: dc.b 27,'E','3: File write / reopen / read / check',13,10,0
pt4: dc.b 27,'E','4: Tight bob setup timing kernels',13,10,0
pt5: dc.b 27,'E','5: Blitter shifts / masks / clipping',13,10,0
pt6: dc.b 27,'E','6: Palette bits and normal video',13,10,0
pt7: dc.b 27,'Y',54,32,27,'K','7: Optional keys / mouse / joystick',0
pt8: dc.b 27,'E','8: 32 bob scenes - pixel comparison',13,10,0
pt9: dc.b 27,'E','9: YM beep, DMA left then right',13,10,0
pt10: dc.b 27,'E','A: 320x256 open borders + Blitter load',13,10,0
pt11: dc.b 0
	even
progress_string: dc.b '~ 9999s '
progress_powers: dc.w 1000,100,10,1
progress_font:
	dc.b $3c,$66,$6e,$76,$66,$66,$3c,0
	dc.b $18,$38,$18,$18,$18,$18,$7e,0
	dc.b $3c,$66,$06,$0c,$18,$30,$7e,0
	dc.b $3c,$66,$06,$1c,$06,$66,$3c,0
	dc.b $0c,$1c,$3c,$6c,$7e,$0c,$0c,0
	dc.b $7e,$60,$7c,$06,$06,$66,$3c,0
	dc.b $1c,$30,$60,$7c,$66,$66,$3c,0
	dc.b $7e,$06,$0c,$18,$30,$30,$30,0
	dc.b $3c,$66,$66,$3c,$66,$66,$3c,0
	dc.b $3c,$66,$66,$3e,$06,$0c,$38,0
	dc.b $7e,$18,$18,$18,$18,$18,$18,0
	dc.b 0,0,$32,$4c,0,0,0,0
	dc.b 0,0,0,$7e,0,0,0,0
	dc.b 0,0,$3e,$60,$3c,$06,$7c,0
	dcb.b 8,0
	dc.b $18,$3c,$66,$66,$7e,$66,$66,0
	dc.b $7c,$66,$66,$7c,$66,$66,$7c,0
	even
	section bss
progress_start: ds.l 1
progress_deadline: ds.l 1
progress_next: ds.l 1
progress_target: ds.l 1
progress_total: ds.w 1
progress_done: ds.w 1
progress_fixed: ds.w 1
progress_origin: ds.w 1
progress_stage: ds.w 1
progress_planes: ds.w 1
progress_active: ds.b 1
progress_visible: ds.b 1
progress_underlay: ds.b 256
