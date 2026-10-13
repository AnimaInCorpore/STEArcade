; R-Type's video state for the renderer (engine/rt/m72render.s through render.s): its m72v_* block holds the arcade's
; video RAMs, palettes and sprite list in the V30's byte order, the V30 image keeps the bytes of each word swapped
; (core.s).  m72_sync, before each picture, copies what changed:
;   the palettes and video RAMs: the 256-byte blocks the translated stores marked (v30_vmarks, tools/gen.py
;     store_marks), each swapped back (movep), with the renderer's marks (m72v_vdirty rows, m72v_pdirty);
;   the sprite list: the DMA's copy (m72_spritebuf) after a DMA;
;   the bands: R-Type's raster interrupt splits the picture at its line (port $06 - 128, the status bar at 239): the
;     lines above it with the scroll registers before the interrupt (m72_scroll_vbl), the lines after it with those its
;     handler wrote (m72_scroll); port $02 bit 3 turns the display off.

	section text,code
m72_sync:
	movem.l	d0-d7/a0-a6,-(sp)
	lea	v30_vmarks,a4
	moveq	#0,d6			; the block
.scan:	cmp.w	#$180,d6
	bhs	.spr
	move.l	(a4,d6.w),d0		; (four blocks at a time)
	bne.s	.some
	addq.w	#4,d6
	bra.s	.scan
.some:	moveq	#4-1,d5
.four:	tst.b	(a4,d6.w)
	beq.s	.next
	clr.b	(a4,d6.w)
	bsr	sync_block
.next:	addq.w	#1,d6
	dbf	d5,.four
	bra.s	.scan
.spr:	tst.b	m72_dma_done
	beq.s	.bands
	sf	m72_dma_done
	lea	m72_spritebuf,a0
	lea	m72v_spr,a1
	moveq	#$400/8-1,d0
	bsr	swap_copy
.bands:	move.w	m72_port02,d2
	lsr.w	#3,d2
	and.w	#1,d2			; display off
	lea	m72v_bands,a0
	move.w	m72_raster,d0
	sub.w	#128,d0			; the raster line
	cmp.w	#255,d0
	bhs.s	.one
	clr.w	(a0)+			; band 0: the lines before the raster interrupt's handler
	move.l	m72_scroll_vbl,(a0)+
	move.l	m72_scroll_vbl+4,(a0)+
	move.w	d2,(a0)+
	addq.w	#1,d0
	move.w	d0,(a0)+		; band 1: from the line after it
	move.l	m72_scroll,(a0)+
	move.l	m72_scroll+4,(a0)+
	move.w	d2,(a0)+
	move.w	#2,m72v_nbands
	movem.l	(sp)+,d0-d7/a0-a6
	rts
.one:	clr.w	(a0)+
	move.l	m72_scroll,(a0)+
	move.l	m72_scroll+4,(a0)+
	move.w	d2,(a0)+
	move.w	#1,m72v_nbands
	movem.l	(sp)+,d0-d7/a0-a6
	rts

; block d6 ($C8000 + d6 * 256) to the renderer's copy, marked for it (d0-d4 a0-a1 used)
sync_block:
	moveq	#0,d0
	move.w	d6,d0
	lsl.l	#8,d0
	lea	v30_image+$C8000,a0
	add.l	d0,a0
	move.w	d6,d1
	cmp.w	#$0C,d1
	bhs.s	.n0
	lea	m72v_pal0,a1		; $C8000-$C8BFF
	st	m72v_pdirty
	bra.s	.copy
.n0:	sub.w	#$40,d1
	bcs.s	.none
	cmp.w	#$0C,d1
	bhs.s	.n1
	lea	m72v_pal1,a1		; $CC000-$CCBFF
	st	m72v_pdirty
	bra.s	.copy
.n1:	sub.w	#$40,d1
	bcs.s	.none
	cmp.w	#$40,d1
	bhs.s	.n2
	lea	m72v_fg,a1		; $D0000-$D3FFF
	lea	m72v_vdirty,a0
	st	(a0,d1.w)
	bra.s	.row
.n2:	sub.w	#$80,d1
	bcs.s	.none
	cmp.w	#$40,d1
	bhs.s	.none
	lea	m72v_bg,a1		; $D8000-$DBFFF
	lea	m72v_vdirty+64,a0
	st	(a0,d1.w)
.row:	lea	v30_image+$C8000,a0
	add.l	d0,a0
.copy:	and.w	#$3F,d1
	lsl.w	#8,d1
	add.w	d1,a1
	moveq	#256/8-1,d0
	bra.s	swap_copy
.none:	rts

; d0 + 1 blocks of 8 bytes from a0 to a1, the bytes of each word swapped
swap_copy:
.l:	movep.l	0(a0),d1
	movep.l	1(a0),d2
	movep.l	d1,1(a1)
	movep.l	d2,0(a1)
	addq.l	#8,a0
	addq.l	#8,a1
	dbf	d0,.l
	rts

; the whole video state marked (the start)
m72_sync_all:
	lea	v30_vmarks,a0
	move.w	#$180/4-1,d0
.l:	move.l	#-1,(a0)+
	dbf	d0,.l
	st	m72_dma_done
	rts
