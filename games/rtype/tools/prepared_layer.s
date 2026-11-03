; Experimental runtime preparation, included only by prepared_layer.py's isolated stage.s.
; All packing, code emission and shifted-mask preparation execute on the 68000.
; 32 direct-mapped row slots, shared by FG/BG. Lazy masks for all 16 shifts
; (eight entries only for a pathological row whose streams would exceed the slot).
PR_SLOT = 16384
PR_DESC = 32
PR_CODE = 1120
PR_PIX = 4192
PR_MASK = 5632
PR_MSZ = 704

	section text,code
; a0 pieces, a2 source row, a3 destination row; d0 layer/row tag, d1 k0, d6 skew.
st_pr_draw:
	movem.l d0-d7/a0-a6,-(sp)
	move.l a0,st_pr_pieces
	move.l a2,st_pr_image
	move.l a3,st_pr_dest
	move.w d6,st_pr_shift
	moveq #0,d7
	move.w d0,d7
	and.w #31,d7
	moveq #14,d2
	lsl.l d2,d7
	lea st_pr_cache,a6
	add.l d7,a6
	addq.w #1,d0
	cmp.w (a6),d0
	bne.s .miss
	cmp.w 2(a6),d1
	beq.s .hit
.miss:	move.w d0,(a6)
	move.w d1,2(a6)
	clr.l 16(a6)
	clr.l 20(a6)
	clr.l 24(a6)
	clr.l 28(a6)
	addq.l #1,st_pr_packs
	bsr st_pr_compile
.hit:	move.w st_pr_shift,d6
	move.w d6,d0
	cmp.w #672,10(a6)
	bls.s .allshifts
	and.w #7,d0
.allshifts:
	moveq #0,d1
	move.b 16(a6,d0.w),d1
	move.w d6,d2
	addq.w #1,d2
	cmp.w d1,d2
	beq.s .mhit
	move.b d2,16(a6,d0.w)
	addq.l #1,st_pr_masks
	mulu 10(a6),d0
	lea PR_MASK(a6),a0
	add.l d0,a0
	move.l a0,st_pr_stream
	bsr st_pr_make_masks
	bra.s .ready
.mhit:	addq.l #1,st_pr_maskhits
	mulu 10(a6),d0
	lea PR_MASK(a6),a0
	add.l d0,a0
	move.l a0,st_pr_stream
.ready:
	addq.l #1,st_pr_rows
	lea PR_CODE(a6),a0
	move.l a0,st_pr_exec
	lea PR_PIX(a6),a0
	move.l a0,BLT_SRC.w
	move.w #2,BLT_SXI.w
	move.w #2,BLT_SYI.w
	move.w #8,BLT_DXI.w
	move.w #$0203,BLT_HOP.w
	move.w st_pr_shift,d0
	beq.s .s0
	or.w #$40,d0
.s0:	move.b d0,BLT_SKEW.w
	move.l st_pr_stream,a0
	lea BLT_END1.w,a1
	lea st_ptab,a2
	move.l st_pr_dest,a3
	lea BLT_DST.w,a4
	lea BLT_YC.w,a5
	lea BLT_CTRL.w,a6
	moveq #4,d4
	moveq #-$40,d2
	bsr .run
	movem.l (sp)+,d0-d7/a0-a6
	rts
.run:	move.l st_pr_exec,-(sp)
	rts

; Emits one routine independent of shift, plus reordered source and mask descriptors.
; Width setup reads the draw call's current st_ptab. Masks come from a lazy shift stream.
st_pr_compile:
	lea PR_CODE(a6),a1
	lea PR_PIX(a6),a2
	lea PR_DESC(a6),a3
	move.l st_pr_image,a4
	move.w #-1,st_pr_width
	move.w #-1,st_pr_type
	clr.w 10(a6)
	moveq #0,d5
	move.l st_pr_pieces,a0
	addq.l #ST_FB,a0
	move.w (a0)+,d3
	subq.w #1,d3
	bmi.s .one
.two:	move.w (a0)+,d0
	move.l (a0)+,d1
	moveq #2,d2
	moveq #2,d4
	bsr st_pr_emit
	dbf d3,.two
.one:	move.l st_pr_pieces,a0
	add.w #ST_FC,a0
	move.w (a0)+,d3
	subq.w #1,d3
	bmi.s .full
.onep:	move.w (a0)+,d0
	moveq #0,d1
	move.w (a0)+,d1
	moveq #1,d2
	moveq #1,d4
	bsr st_pr_emit
	dbf d3,.onep
.full:	move.l st_pr_pieces,a0
	add.w #ST_FF,a0
	move.w (a0)+,d3
	subq.w #1,d3
	bmi.s .done
.fullp:
	move.w (a0)+,d2
	lsr.w #1,d2
	move.w (a0)+,d0
	moveq #-1,d1
	moveq #0,d4
	; Seven full source words would exceed 256 bus cycles when skewed.
	; Split just that existing piece into six words and one; preserve its pixels.
	cmp.w #7,d2
	bne.s .emit
	moveq #6,d2
	move.w d0,-(sp)
	bsr st_pr_emit
	move.w (sp)+,d0
	add.w #48,d0
	moveq #-1,d1
	moveq #1,d2
	moveq #0,d4
.emit:	bsr st_pr_emit
	dbf d3,.fullp
.done:	move.w #$4e75,(a1)+
	move.l a1,d0
	sub.l a6,d0
	sub.w #PR_CODE,d0
	move.w d0,6(a6)
	move.l a2,d0
	sub.l a6,d0
	sub.w #PR_PIX,d0
	move.w d0,8(a6)
	move.l a3,d0
	sub.l a6,d0
	sub.w #PR_DESC,d0
	divu #6,d0
	move.w d0,4(a6)
	rts

; d0 row offset, d1 unshifted mask, d2 source words, d4 mask kind.
; Keeps d3 pass-loop counter, d5 previous destination, a0 list pointer, a6 slot.
st_pr_emit:
	cmp.w st_pr_width,d2
	beq.s .mask
	move.w d2,st_pr_width
	move.w st_pr_twidth,(a1)+
	move.w d2,d7
	add.w d7,d7
	move.w d7,(a1)+
	move.w #BLT_XC&$ffff,(a1)+
	move.w st_pr_twidth+6,(a1)+
	add.w #32,d7
	move.w d7,(a1)+
	move.w #BLT_DYI&$ffff,(a1)+
.mask:	cmp.w st_pr_type,d4
	bne.s .newm
	cmp.l st_pr_lastmask,d1
	beq.s .dst
.newm:	move.w d4,st_pr_type
	move.l d1,st_pr_lastmask
	move.w d4,(a3)+
	move.l d1,(a3)+
	cmp.w #1,d4
	bne.s .wide
	addq.w #4,10(a6)
	move.w st_pr_tsingle,(a1)+
	bra.s .end3
.wide:	addq.w #6,10(a6)
	move.w st_pr_tdouble,(a1)+
.end3:	move.l st_pr_tsingle+2,(a1)+
.dst:	move.w d0,d7
	sub.w d5,d7
	beq.s .step0
	move.w st_pr_tstep,(a1)+
	move.w d7,(a1)+
.step0:
	move.w d0,d5
	move.l st_pr_tdraw,(a1)+
	move.w st_pr_tdraw+4,(a1)+
	; Pack planes in pass order. A c-word pass consumes 4*c consecutive words.
	lea (a4,d0.w),a5
	cmp.w #1,d2
	bne.s .notone
	move.l (a5)+,(a2)+
	move.l (a5),(a2)+
	rts
.notone:
	cmp.w #2,d2
	bne.s .many
	rept 4
	move.w (a5),(a2)+
	move.w 8(a5),(a2)+
	addq.l #2,a5
	endr
	rts
.many:
	move.w d2,d1
	lsl.w #3,d1
	neg.w d1
	addq.w #2,d1
	moveq #3,d6
.plane:
	move.w d2,d7
	subq.w #1,d7
.word:	move.w (a5),(a2)+
	addq.l #8,a5
	dbf d7,.word
	add.w d1,a5
	dbf d6,.plane
	rts

; Template opcodes are assembled, rather than hand-encoded by the emitter.
st_pr_twidth:
	move.w 2(a2),BLT_XC.w
	move.w 34(a2),BLT_DYI.w
st_pr_tsingle:
	move.w (a0)+,(a1)
	move.w (a0)+,4(a1)
st_pr_tdouble:
	move.l (a0)+,(a1)
st_pr_tstep:
	lea 1234(a3),a3
st_pr_tdraw:
	move.l a3,(a4)
	move.w d4,(a5)
	move.b d2,(a6)

st_pr_make_masks:
	lea PR_DESC(a6),a1
	move.w 4(a6),d7
	subq.w #1,d7
	bmi.s .done
	moveq #16,d5
	sub.w d6,d5
.mask:	move.w (a1)+,d2
	move.l (a1)+,d0
	cmp.w #1,d2
	beq.s .one
	tst.w d2
	beq.s .full
	move.w d0,d1
	tst.w d6
	beq.s .two0
	lsr.l d6,d0
	lsl.w d5,d1
.two0:	move.l d0,(a0)+
	move.w d1,(a0)+
	bra.s .next
.one:	swap d0
	lsr.l d6,d0
	move.w d0,d1
	swap d0
	move.w d0,(a0)+
	move.w d1,(a0)+
	bra.s .next
.full:	moveq #-1,d0
	lsr.w d6,d0
	move.w d0,(a0)+
	move.w #-1,(a0)+
	moveq #-1,d0
	tst.w d6
	beq.s .f0
	lsl.w d5,d0
.f0:	move.w d0,(a0)+
.next:	dbf d7,.mask
.done:	rts

	section bss,bss
	even
st_pr_pieces: ds.l 1
st_pr_image: ds.l 1
st_pr_dest: ds.l 1
st_pr_stream: ds.l 1
st_pr_exec: ds.l 1
st_pr_lastmask: ds.l 1
st_pr_shift: ds.w 1
st_pr_width: ds.w 1
st_pr_type: ds.w 1
st_pr_rows: ds.l 1
st_pr_packs: ds.l 1
st_pr_masks: ds.l 1
st_pr_maskhits: ds.l 1
st_pr_cache: ds.b 32*PR_SLOT
