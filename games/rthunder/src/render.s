; Rolling Thunder's picture on the STE (renderer, step 1: the scrolling layers' composite).
;
; The three scrolling layers (CUS42 pair layers 0 and 1, CUS43 pair layer 0) move in lock step (their scroll values differ
; by the layers' dx offsets, tools/machine.py render_raw), so they are composed into one tile-aligned virtual screen
; `ren_bg`: 512 x 256 pixels, planar like the STE's screen (32 groups of 16 pixels = 8 bytes: plane 0-3 words, one tile
; column = one byte of a plane word), 256 bytes a line.  A cell is 8 x 8 pixels: cell (c, r) of the map (c 0-63, r 0-31)
; lies at ren_bg + r * 2048 + (c >> 1) * 8 + (c & 1), plane p at +2p, line y at + 256 y.
;
; A tile's STE form (`tcache`, tile_get): 8 lines of 5 bytes: the opaque mask, the planes 0-3 (zero where transparent),
; made on first use from the 3 bit pens (assets: ren_t0 / ren_t1) and the colour row's map (ren_rowmap: pens 0-6 -> STE
; index).  Direct mapped, 8192 slots of 44 bytes: key (long: $10000000 | dev << 24 | code << 8 | attr, 0 = empty), form.

RB_LB = 544			; a buffer line: 1088 pixels = 68 groups: the map twice with 8 cells (64 pixels) of margin each side
DB_ROWS = 68			; a buffer: 68 cell rows = 544 lines: the map twice with 4 rows (32 lines) of guard above and below
DB_SIZE = RB_LB*DB_ROWS*8
; Map cell (c, r) lies at buffer cells (bc, br) = (c + 8 + {0, 64, -64 if c >= 56}, r + 4 + {0, 32, -32 if r >= 28}); the
; display buffers (dbuf0/1) hold the same layout as the clean buffer ren_bg, copies of the cells inside the window.
TC_SLOTS = 8192
TC_SIZE = 44

	section text,code
; ---- tile_get: d0.w = device (0 CUS42 pair, 1 CUS43 pair), d1.w = tile code, d2.w = colour row (attribute byte) ->
; a0 = the tile's 40 byte form; d0-d7 a1-a3 clobbered ----
tile_get:
	moveq	#0,d3
	move.b	d0,d3
	swap	d3
	lsl.l	#8,d3			; dev << 24
	moveq	#0,d4
	move.w	d1,d4
	lsl.l	#8,d4			; code << 8
	or.l	d4,d3
	moveq	#0,d4
	move.b	d2,d4
	or.l	d4,d3
	or.l	#$10000000,d3		; the key
	move.w	d1,d4
	mulu	#37,d4			; the slot: a multiplicative mix of code, attribute and device
	moveq	#0,d5
	move.b	d2,d5
	mulu	#131,d5
	add.l	d5,d4
	move.w	d0,d5
	mulu	#1021,d5
	add.l	d5,d4
	lsr.l	#1,d4
	and.w	#TC_SLOTS-1,d4
	mulu	#TC_SIZE,d4
	lea	tcache,a1
	add.l	d4,a1
	cmp.l	(a1)+,d3
	beq.s	.hit
	move.l	d3,-4(a1)
	addq.l	#1,tc_miss
	lea	ren_t0,a2
	tst.w	d0
	beq.s	.d0
	lea	ren_t1,a2
.d0:	moveq	#0,d4
	move.w	d1,d4
	lsl.l	#6,d4
	add.l	d4,a2
	lea	ren_rowmap,a3
	moveq	#0,d4
	move.b	d2,d4
	lsl.w	#3,d4
	add.l	d4,a3
	move.l	a1,-(sp)
	bsr	tile_make
	move.l	(sp)+,a0
	rts
.hit:	move.l	a1,a0
	rts

; a1 = the form (written, 40 bytes, advanced), a2 = 64 pens, a3 = the row's 8 map entries (d0-d7 clobbered)
tile_make:
	move.w	#8,tm_rows
.row:	moveq	#0,d3
	moveq	#0,d4
	moveq	#0,d5
	moveq	#0,d6
	moveq	#0,d7
	rept	8
	moveq	#0,d0
	move.b	(a2)+,d0
	move.b	(a3,d0.w),d1
	subq.b	#7,d0
	sne	d2
	lsr.b	#1,d2
	roxl.b	#1,d3
	lsr.b	#1,d1
	roxl.b	#1,d4
	lsr.b	#1,d1
	roxl.b	#1,d5
	lsr.b	#1,d1
	roxl.b	#1,d6
	lsr.b	#1,d1
	roxl.b	#1,d7
	endr
	move.b	d3,(a1)+
	move.b	d4,(a1)+
	move.b	d5,(a1)+
	move.b	d6,(a1)+
	move.b	d7,(a1)+
	subq.w	#1,tm_rows
	bne	.row
	rts

; ---- ren_setup: the picture's layer order (the three scrolling layers by priority, ties the higher layer first: tools/
; machine.py render_raw) and the back colour's planes, from hwregs ----
ren_setup:
	lea	hwregs,a0
	moveq	#2,d7
.l:	move.w	d7,d0
	lsr.w	#1,d0
	lsl.w	#4,d0			; dev * 16
	move.w	d7,d1
	and.w	#1,d1
	lsl.w	#2,d1
	add.w	d1,d0			; + layer * 4
	moveq	#0,d1
	move.b	(a0,d0.w),d1		; the x scroll's high byte
	lsr.w	#1,d1
	and.w	#7,d1			; priority
	lsl.w	#2,d1
	moveq	#3,d2
	sub.w	d7,d2
	add.w	d2,d1			; key = priority * 4 + (3 - i)
	lsl.w	#8,d1
	or.w	d7,d1
	lea	lord,a1
	add.w	d7,d7
	move.w	d1,(a1,d7.w)
	lsr.w	#1,d7
	dbf	d7,.l
	lea	lord,a1			; sort the three (bubble: 0-1, 1-2, 0-1)
	bsr.s	.cs
	addq.l	#2,a1
	bsr.s	.cs
	subq.l	#2,a1
	bsr.s	.cs
	bra.s	.sorted
.cs:	move.w	(a1),d0
	cmp.w	2(a1),d0
	bls.s	.cr
	move.w	2(a1),(a1)
	move.w	d0,2(a1)
.cr:	rts
.sorted:
	moveq	#0,d0
	move.b	hwregs+$20,d0
	lea	ren_bk,a0
	move.b	(a0,d0.w),d0		; the STE index
	lea	bkp,a0
	moveq	#3,d1
.p:	lsr.b	#1,d0
	scs	d2
	move.b	d2,(a0)+
	dbf	d1,.p
	rts

; ---- ren_cell: d0.w = column (0-63), d1.w = row (0-31): the cell of ren_bg from the back colour and the layers ----
ren_cell:
	movem.l	d0-d7/a0-a5,-(sp)
	move.w	d0,d6			; column
	move.w	d1,d7			; row
	move.w	d6,d2
	addq.w	#8,d2
	move.w	d7,d3
	addq.w	#4,d3
	lea	ren_bg,a2
	bsr	cell_addr
	move.l	a1,a5			; the cell's plane 0 byte of line 0
	lea	bkp,a0
	move.b	(a0)+,d0
	move.b	(a0)+,d1
	move.b	(a0)+,d2
	move.b	(a0)+,d3
	move.l	a5,a1
	moveq	#7,d4
.f:	move.b	d0,(a1)
	move.b	d1,2(a1)
	move.b	d2,4(a1)
	move.b	d3,6(a1)
	lea	RB_LB(a1),a1
	dbf	d4,.f
	clr.w	rc_n
.lay:	lea	lord,a0
	move.w	rc_n,d0
	add.w	d0,d0
	moveq	#0,d4
	move.b	1(a0,d0.w),d4		; the layer (lowest priority first)
	move.w	d4,d3
	lsr.w	#1,d3			; device
	lea	vram0,a0
	tst.w	d3
	beq.s	.v0
	lea	vram1,a0
.v0:	move.w	d4,d0
	and.w	#1,d0			; layer in the device
	lsl.w	#8,d0
	lsl.w	#4,d0
	add.w	d0,a0			; + layer * $1000
	move.w	d7,d0
	lsl.w	#6,d0
	add.w	d6,d0
	add.w	d0,d0
	add.w	d0,a0			; + (row * 64 + column) * 2
	moveq	#0,d1
	move.b	(a0)+,d1		; code (low)
	moveq	#0,d2
	move.b	(a0),d2			; attribute
	move.w	d3,d5
	lsl.w	#4,d5			; dev * 16
	move.w	d4,d0
	and.w	#1,d0
	lsl.w	#3,d0
	add.w	d0,d5			; + layer * 8
	move.w	d2,d0
	and.w	#3,d0
	add.w	d0,d0
	add.w	d0,d5			; + (attribute & 3) * 2
	lea	ren_hi,a0
	add.w	(a0,d5.w),d1		; + the PROM's select
	tst.w	d3
	bne.s	.nt
	moveq	#0,d0
	move.b	hwregs+$30,d0
	lsl.w	#8,d0
	lsl.w	#3,d0
	add.w	d0,d1			; + tile bank << 11
.nt:	move.w	d3,d0
	movem.l	d6-d7,-(sp)
	bsr	tile_get
	movem.l	(sp)+,d6-d7
	move.l	a5,a1
	moveq	#7,d4
.m:	move.b	(a0)+,d0		; mask
	beq.s	.skip
	cmp.b	#$FF,d0
	bne.s	.part
	move.b	(a0)+,(a1)
	move.b	(a0)+,2(a1)
	move.b	(a0)+,4(a1)
	move.b	(a0)+,6(a1)
	bra.s	.next
.part:	not.b	d0
	move.b	(a0)+,d1
	move.b	(a1),d2
	and.b	d0,d2
	or.b	d1,d2
	move.b	d2,(a1)
	move.b	(a0)+,d1
	move.b	2(a1),d2
	and.b	d0,d2
	or.b	d1,d2
	move.b	d2,2(a1)
	move.b	(a0)+,d1
	move.b	4(a1),d2
	and.b	d0,d2
	or.b	d1,d2
	move.b	d2,4(a1)
	move.b	(a0)+,d1
	move.b	6(a1),d2
	and.b	d0,d2
	or.b	d1,d2
	move.b	d2,6(a1)
	bra.s	.next
.skip:	addq.l	#4,a0
.next:	lea	RB_LB(a1),a1
	dbf	d4,.m
	addq.w	#1,rc_n
	cmp.w	#3,rc_n
	bne	.lay
	; the other instances: columns c + {0, 64, -64 (c >= 56)}, rows r + {0, 32, -32 (r >= 28)}
	moveq	#0,d0
.ci:	cmp.w	#2,d0
	bne.s	.cok
	cmp.w	#56,d6
	bcs.s	.nextci
.cok:	moveq	#0,d1
.ri:	cmp.w	#2,d1
	bne.s	.rok
	cmp.w	#28,d7
	bcs.s	.nextri
.rok:	move.w	d0,d2
	or.w	d1,d2
	beq.s	.nextri
	lea	coloff,a0
	move.w	d0,d2
	add.w	d2,d2
	move.w	(a0,d2.w),d2
	add.w	d6,d2
	addq.w	#8,d2
	lea	rowoff,a0
	move.w	d1,d3
	add.w	d3,d3
	move.w	(a0,d3.w),d3
	add.w	d7,d3
	addq.w	#4,d3
	lea	ren_bg,a2
	bsr	cell_addr
	move.l	a5,a0
	bsr	cell_cp
.nextri:
	addq.w	#1,d1
	cmp.w	#3,d1
	bne.s	.ri
.nextci:
	addq.w	#1,d0
	cmp.w	#3,d0
	bne.s	.ci
	; the log of composed cells (the display buffers copy them)
	move.l	clog_n,d0
	and.l	#4095,d0
	add.w	d0,d0
	lea	clog,a0
	move.w	d7,d1
	lsl.w	#6,d1
	add.w	d6,d1
	move.w	d1,(a0,d0.w)
	addq.l	#1,clog_n
	movem.l	(sp)+,d0-d7/a0-a5
	rts

; d2 = buffer cell column bc, d3 = row br, a2 = the buffer -> a1 = the cell's plane 0 byte of line 0 (d4 clobbered)
cell_addr:
	move.w	d3,d4
	mulu	#RB_LB*8,d4
	move.l	a2,a1
	add.l	d4,a1
	move.w	d2,d4
	lsr.w	#1,d4
	lsl.w	#3,d4
	add.w	d4,a1
	btst	#0,d2
	beq.s	.e
	addq.l	#1,a1
.e:	rts

; a0 -> a1: a cell's 8 lines of 4 plane bytes (d4, d5 clobbered)
cell_cp:
	moveq	#7,d4
.l:	movep.l	0(a0),d5
	movep.l	d5,0(a1)
	lea	RB_LB(a0),a0
	lea	RB_LB(a1),a1
	dbf	d4,.l
	rts

; ---- ren_window: where the display window lies in a buffer: the 320 x 224 pixels from picture column -16 (the picture's 288
; columns with a 16 pixel band each side).  ren_wx = (4 + sx) mod 512 (the first layer's scroll: its dx 47, the picture from
; arcade x 67), ren_wy = (25 + sy) mod 256; in a buffer the window starts at pixel 64 + ren_wx, line 32 + ren_wy: ren_voff =
; the offset of its first line's group, ren_fine = the fine scroll (0-15), ren_wc0/1, ren_wr0/1 = its cells ----
ren_window:
	moveq	#0,d0
	move.b	hwregs,d0
	lsl.w	#8,d0
	move.b	hwregs+1,d0		; sx
	addq.w	#4,d0
	and.w	#511,d0
	move.w	d0,ren_wx
	moveq	#0,d1
	move.b	hwregs+2,d1
	add.w	#25,d1
	and.w	#255,d1
	move.w	d1,ren_wy
	move.w	d0,d2
	and.w	#15,d2
	move.w	d2,ren_fine
	move.w	d0,d2
	lsr.w	#3,d2
	addq.w	#8,d2
	move.w	d2,ren_wc0
	move.w	d0,d2
	add.w	#64+319,d2
	lsr.w	#3,d2
	move.w	d2,ren_wc1
	move.w	d1,d2
	lsr.w	#3,d2
	addq.w	#4,d2
	move.w	d2,ren_wr0
	move.w	d1,d2
	add.w	#32+223,d2
	lsr.w	#3,d2
	move.w	d2,ren_wr1
	add.w	#32,d1
	add.w	#64,d0
	lsr.w	#4,d0
	lsl.w	#3,d0			; (x >> 4) * 8
	mulu	#RB_LB,d1
	add.l	d0,d1
	move.l	d1,ren_voff
	rts

; ---- ren_update: the composite follows the game: a layer the translated stores marked (tile_written + layer) is compared
; with its shadow, the cells that differ (any of the three layers: a cell index is shared) are decomposed, a change of the
; layer order, the back colour or the tile bank decomposes all; then the cells of the window are composed (cell_ok) ----
ren_update:
	bsr	ren_setup
	move.l	lord,d0			; (the layer order: 3 words = 6 bytes; the back colour's planes; the tile bank)
	move.w	lord+4,d1
	move.l	bkp,d2
	moveq	#0,d3
	move.b	hwregs+$30,d3
	cmp.l	sv_lord,d0
	bne.s	.all
	cmp.w	sv_lord+4,d1
	bne.s	.all
	cmp.l	sv_bkp,d2
	bne.s	.all
	cmp.b	sv_tb,d3
	beq.s	.nochg
.all:	st	rw_dirty
	move.l	d0,sv_lord
	move.w	d1,sv_lord+4
	move.l	d2,sv_bkp
	move.b	d3,sv_tb
	lea	cell_ok,a0
	move.w	#2048/4-1,d0
.clr:	clr.l	(a0)+
	dbf	d0,.clr
.nochg:	moveq	#2,d7
.lay:	lea	tile_written,a0
	tst.b	(a0,d7.w)
	beq.s	.nolay
	clr.b	(a0,d7.w)
	bsr	ren_scan
.nolay:	dbf	d7,.lay
	bsr	ren_window
	; the window's cells: columns (x >> 3) .. (x + 319) >> 3, rows (line >> 3) .. (line + 223) >> 3 (the buffer's map twice)
	move.w	ren_wx,d4
	lsr.w	#3,d4			; first column
	move.w	ren_wx,d0
	add.w	#319,d0
	lsr.w	#3,d0
	sub.w	d4,d0			; columns - 1
	move.w	ren_wy,d5
	lsr.w	#3,d5			; first row
	move.w	ren_wy,d1
	add.w	#223,d1
	lsr.w	#3,d1
	sub.w	d5,d1			; rows - 1
	move.w	d1,rw_rows
	move.w	d0,rw_cols
	move.w	d4,rw_c0
	move.w	d5,rw_r0
	move.l	d4,d2			; the window's cell range: unchanged and nothing decomposed: nothing to compose
	swap	d2
	move.w	d5,d2
	move.w	rw_cols,d3
	lsl.w	#8,d3
	or.w	rw_rows,d3
	cmp.l	rw_sig,d2
	bne.s	.go
	cmp.w	rw_sig2,d3
	bne.s	.go
	tst.b	rw_dirty
	beq	ren_sync
.go:	move.l	d2,rw_sig
	move.w	d3,rw_sig2
	clr.b	rw_dirty
	clr.w	rw_r
.rr:	move.w	rw_r0,d1
	add.w	rw_r,d1
	and.w	#31,d1
	clr.w	rw_c
.cc:	move.w	rw_c0,d0
	add.w	rw_c,d0
	and.w	#63,d0
	move.w	d1,d2
	lsl.w	#6,d2
	add.w	d0,d2
	lea	cell_ok,a0
	tst.b	(a0,d2.w)
	bne.s	.ok
	st	(a0,d2.w)
	movem.l	d0-d2,-(sp)
	bsr	ren_cell
	movem.l	(sp)+,d0-d2
.ok:	move.w	rw_c,d0
	addq.w	#1,d0
	move.w	d0,rw_c
	cmp.w	rw_cols,d0
	bls.s	.cc
	move.w	rw_r,d0
	addq.w	#1,d0
	move.w	d0,rw_r
	cmp.w	rw_rows,d0
	bls.s	.rr
	bra	ren_sync

; d7 = the layer 0-2: its cells against the shadow
ren_scan:
	lea	vram0,a0
	move.w	d7,d0
	lsr.w	#1,d0
	beq.s	.d0
	lea	vram1,a0
.d0:	move.w	d7,d0
	and.w	#1,d0
	lsl.w	#8,d0
	lsl.w	#4,d0
	add.w	d0,a0			; the layer's 4096 bytes
	move.l	a0,a2
	lea	shadow,a1
	move.w	d7,d0
	lsl.w	#8,d0
	lsl.w	#4,d0
	add.w	d0,a1
	move.w	#1024-1,d6
.l:	cmpm.l	(a0)+,(a1)+
	beq.s	.same
	move.l	-4(a0),-4(a1)
	move.l	a0,d0
	sub.l	a2,d0
	lsr.l	#1,d0
	subq.w	#2,d0			; the first of the two cells
	lea	cell_ok,a3
	clr.b	(a3,d0.w)
	clr.b	1(a3,d0.w)
	st	rw_dirty
.same:	dbf	d6,.l
	rts

; ---- ren_sync: the display buffer ren_buf (0, 1) follows the clean buffer inside the window: the cells logged since its last
; sync (clog) that lie in the new window, and the cells that entered the window since (all, when it has no state or the log
; wrapped) are copied from ren_bg ----
ren_sync:
	movem.l	d0-d7/a0-a4,-(sp)
	moveq	#0,d0
	move.w	ren_buf,d0
	lsl.w	#4,d0
	lea	dstate,a4
	add.w	d0,a4
	move.w	ren_buf,d0
	lsl.w	#2,d0
	lea	dbuf_tab,a0
	move.l	(a0,d0.w),ds_base
	move.l	clog_n,d7
	sub.l	12(a4),d7		; entries not yet seen
	tst.w	(a4)
	beq	.full
	cmp.l	#4096,d7
	bhi	.full
	; the logged cells inside the new window
	move.l	12(a4),d6
.lg:	cmp.l	clog_n,d6
	beq	.strips
	move.l	d6,d0
	and.l	#4095,d0
	add.w	d0,d0
	lea	clog,a0
	move.w	(a0,d0.w),d1
	move.w	d1,d0
	and.w	#63,d0			; c
	lsr.w	#6,d1			; r
	addq.w	#8,d0
	move.w	ren_wc0,d2
	move.w	ren_wc1,d3
	moveq	#64,d4
	bsr	pick
	bmi.s	.lgn
	move.w	d0,d2
	move.w	d1,d0
	addq.w	#4,d0
	move.w	ren_wr0,d3
	move.w	d2,-(sp)
	move.w	d3,d2
	move.w	ren_wr1,d3
	moveq	#32,d4
	bsr	pick
	move.w	(sp)+,d2
	tst.w	d0
	bmi.s	.lgn
	move.w	d0,d3
	bsr	dcopy
.lgn:	addq.l	#1,d6
	bra.s	.lg
.strips:
	move.w	ren_wr0,d3
.sr:	cmp.w	ren_wr1,d3
	bhi	.done
	cmp.w	6(a4),d3
	bcs.s	.allrow
	cmp.w	8(a4),d3
	bhi.s	.allrow
	move.w	ren_wc0,d0
	cmp.w	2(a4),d0
	bcc.s	.right
	move.w	2(a4),d1
	subq.w	#1,d1
	cmp.w	ren_wc1,d1
	bls.s	.l1
	move.w	ren_wc1,d1
.l1:	bsr	dcopyrow
.right:	move.w	ren_wc1,d1
	cmp.w	4(a4),d1
	bls.s	.nr
	move.w	4(a4),d0
	addq.w	#1,d0
	cmp.w	ren_wc0,d0
	bcc.s	.l2
	move.w	ren_wc0,d0
.l2:	bsr	dcopyrow
.nr:	addq.w	#1,d3
	bra.s	.sr
.allrow:
	move.w	ren_wc0,d0
	move.w	ren_wc1,d1
	bsr	dcopyrow
	addq.w	#1,d3
	bra.s	.sr
.full:	move.w	ren_wr0,d3
.fr:	move.w	ren_wc0,d0
	move.w	ren_wc1,d1
	bsr	dcopyrow
	addq.w	#1,d3
	cmp.w	ren_wr1,d3
	bls.s	.fr
.done:	move.w	#1,(a4)
	move.w	ren_wc0,2(a4)
	move.w	ren_wc1,4(a4)
	move.w	ren_wr0,6(a4)
	move.w	ren_wr1,8(a4)
	move.l	clog_n,12(a4)
	movem.l	(sp)+,d0-d7/a0-a4
	rts

; d0 = v, d2 = lo, d3 = hi, d4 = step (64/32): d0 = v, v + step or v - step (>= 0) when inside lo..hi, else -1 (Z clear, N set)
pick:	cmp.w	d2,d0
	bcs.s	.p1
	cmp.w	d3,d0
	bls.s	.ok
.p1:	move.w	d0,d5
	add.w	d4,d5
	cmp.w	d2,d5
	bcs.s	.p2
	cmp.w	d3,d5
	bhi.s	.p2
	move.w	d5,d0
	bra.s	.ok
.p2:	move.w	d0,d5
	sub.w	d4,d5
	bcs.s	.no
	cmp.w	d2,d5
	bcs.s	.no
	cmp.w	d3,d5
	bhi.s	.no
	move.w	d5,d0
.ok:	tst.w	d0
	rts
.no:	moveq	#-1,d0
	rts

; d3 = row, d0..d1 = columns: copy the cells (dcopy with d2 = column, d3 = row) (d0-d2 clobbered)
dcopyrow:
.l:	move.w	d0,d2
	bsr.s	dcopy
	addq.w	#1,d0
	cmp.w	d1,d0
	bls.s	.l
	rts

; d2 = column, d3 = row (buffer cells): ren_bg's cell to the display buffer ds_base (d4, d5, a0-a2 clobbered)
dcopy:	move.l	a4,-(sp)
	lea	ren_bg,a2
	bsr	cell_addr
	move.l	a1,a0
	move.l	ds_base,a2
	bsr	cell_addr
	bsr	cell_cp
	move.l	(sp)+,a4
	rts

; ---- ren_bg_all: every cell of ren_bg (ren_setup first) ----
ren_bg_all:
	bsr	ren_setup
	bsr	ren_window
	moveq	#0,d1
.r:	moveq	#0,d0
.c:	bsr	ren_cell
	addq.w	#1,d0
	cmp.w	#64,d0
	bne.s	.c
	addq.w	#1,d1
	cmp.w	#32,d1
	bne.s	.r
	rts

	section bss,bss
	even
rbss_start:
tile_written:	ds.b	4
cell_ok:	ds.b	2048
shadow:		ds.b	3*4096
tm_rows:	ds.w	1
	even
tc_miss:	ds.l	1
lord:		ds.w	3
rc_n:		ds.w	1
ren_fine:	ds.w	1
ren_wx:		ds.w	1
ren_wy:		ds.w	1
rw_rows:	ds.w	1
rw_cols:	ds.w	1
rw_c0:		ds.w	1
rw_r0:		ds.w	1
rw_r:		ds.w	1
rw_c:		ds.w	1
sv_lord:	ds.w	3
sv_bkp:		ds.l	1
sv_tb:		ds.b	1
rw_dirty:	ds.b	1
	even
rw_sig:		ds.l	1
rw_sig2:	ds.w	1
	even
	even
ren_voff:	ds.l	1
ren_wc0:	ds.w	1
ren_wc1:	ds.w	1
ren_wr0:	ds.w	1
ren_wr1:	ds.w	1
ren_buf:	ds.w	1
ds_base:	ds.l	1
clog_n:		ds.l	1
dstate:		ds.b	48
clog:		ds.w	4096
bkp:		ds.b	4
rbss_end:
	even
ren_bg:		ds.b	DB_SIZE
dbuf0:		ds.b	DB_SIZE
dbuf1:		ds.b	DB_SIZE
dbuf2:		ds.b	DB_SIZE
tcache:		ds.b	TC_SLOTS*TC_SIZE
	section data,data
	even
dbuf_tab:	dc.l	dbuf0,dbuf1,dbuf2
coloff:	dc.w	0,64,-64
rowoff:	dc.w	0,32,-32
ren_t0:		incbin	"ren_t0.bin"
ren_t1:		incbin	"ren_t1.bin"
ren_rowmap:	incbin	"ren_rowmap.bin"
ren_hi:		incbin	"ren_hi.bin"
ren_bk:		incbin	"ren_bk.bin"
ren_pal:	incbin	"ren_pal.bin"
