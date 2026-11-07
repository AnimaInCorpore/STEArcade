; Mr. HELI's video state for the renderer (engine/rt/m72render.s through render.s), as R-Type's (games/rtype/src/
; video.s): its m72v_* block holds the arcade's video RAMs, palettes and sprite list in the V30's byte order, the V30
; image keeps the bytes of each word swapped (core.s).  m72_sync, before each picture, copies what changed:
;   the palettes and video RAMs: the 256-byte blocks the translated stores marked (v30_vmarks, tools/gen.py
;     store_marks), each swapped back (movep), with the renderer's marks (m72v_vdirty rows, m72v_pdirty);
;   the sprite list: the DMA's copy (m72_spritebuf) after a DMA;
;   the bands: the raster interrupts split the picture at their lines (core.s m72_rlines, m72_rasters: the top panel
;     ends at line 31, the cave's second FG split lower down): the lines up to the first with the scroll registers
;     the VBL handler left (m72_scroll_vbl), up to the second with those after the first raster handler
;     (m72_scroll_r1), then the last written (m72_scroll); port $02 bit 3 turns the display off.

	section text,code
m72_sync:
	movem.l	d0-d7/a0-a6,-(sp)
	lea	v30_vmarks,a4
	moveq	#0,d6			; the 256-byte block: its four 64-byte marks (tools/gen.py MARKS) as a long
.scan:	cmp.w	#$180,d6
	bhs	.spr
	move.w	d6,d0
	add.w	d0,d0
	add.w	d0,d0
	tst.l	(a4,d0.w)
	beq.s	.next
	clr.l	(a4,d0.w)
	bsr	sync_block
.next:	addq.w	#1,d6
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
	move.w	m72_rasters,d1		; n raster interrupts: n + 1 bands (those starting below the picture left out)
	moveq	#0,d4			; band k
	moveq	#0,d0			; its first line
	moveq	#0,d3			; bands
	lea	m72_rlines,a2
.b:	move.w	d0,(a0)+
	lea	m72_scroll,a1		; (the last band: the values last written)
	cmp.w	d1,d4
	beq.s	.src
	lea	m72_scroll_vbl,a1	; (band 0: the VBL handler's)
	tst.w	d4
	beq.s	.src
	lea	m72_scroll_r1,a1	; (band 1 of three: the first raster handler's)
	cmp.w	#1,d4
	beq.s	.src
	lea	m72_scroll,a1
.src:	move.l	(a1),(a0)+
	move.l	4(a1),(a0)+
	move.w	d2,(a0)+
	addq.w	#1,d3
	cmp.w	d1,d4
	beq.s	.end
	addq.w	#1,d4
	move.w	(a2)+,d0		; the raster line: the next band from the line after it
	addq.w	#1,d0
	cmp.w	#256,d0
	blo.s	.b
.end:	move.w	d3,m72v_nbands
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
	move.l	a0,d2			; (the block: the renderer compares the marked ones)
	lea	m72v_pdblk,a0
	st	(a0,d1.w)
	move.l	d2,a0
	bra.s	.copy
.n0:	sub.w	#$40,d1
	bcs.s	.none
	cmp.w	#$0C,d1
	bhs.s	.n1
	lea	m72v_pal1,a1		; $CC000-$CCBFF
	st	m72v_pdirty
	move.l	a0,d2
	lea	m72v_pdblk+12,a0
	st	(a0,d1.w)
	move.l	d2,a0
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
	move.w	#$600/4-1,d0
.l:	move.l	#-1,(a0)+
	dbf	d0,.l
	st	m72_dma_done
	rts
