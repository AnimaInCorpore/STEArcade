; Moon Patrol's text layer on the playfield (included by render.s): tile rows 7-31, pen 0 transparent.
;
; Two images hold the text as the tile RAM has it, baked when a cell changes (tx_update): the fixed rows 7-23 (picture
; lines 50-185) in picture coordinates (st_img: 136 lines x 15 groups; column c at picture x 8c - 8), the ground rows
; 24-31 (lines 186-249, scrolled) in tilemap coordinates twice side by side (gr_img: 64 lines x 32 groups: any window
; of 15 groups and the Blitter's pre-read is one stretch).  Each has a mask plane of its opaque pixels (st_mask,
; gr_mask: bit 15 the first pixel), a count of the opaque pixels a line (st_cnt over the 240 shown, gr_cnt over the
; 256 of the ring) and a line's group bits (tx_nz: groups with pixels, tx_opq: groups without a transparent pixel; the
; ground's 32 groups, twice).  The ground also has a version with the hills' / city's fill slot in its holes (gr_imgf:
; the lines over that fill are drawn as copies of it).  A baked cell marks its 8 lines changed in every buffer
; (pf_dirty: its group; a ground cell the whole line); a tile without pixels where there was none is not baked.
; render.s draws the text (ovl_text: pieces from the group bits; full lines as copies, no background under them).
; The fixed rows need no shift; the ground's window starts at tilemap x u = (8 - scroll) mod 256 (group u >> 4, the
; skew u & 15 with a pre-read).
;
; Colours: a cell's pens (colour * 4 + the tile's pixel values: mp_tused) have colour ids (mp_pencid: pens that look
; the same on the STE share one), and the ids hold the playfield's slots: 0 .. MP_NPIN - 1 pinned to the scene
; (mp_pincid: the background, the mountains, the hills or the city), the others given to an id while a cell of the
; images uses it (cid_ref counts them; the last one gone frees the slot).  An id that finds no free slot borrows the nearest colour's slot
; (mp_cidnear: an approximation, more than 16 colours on the playfield; flagged $80 in cid_slot).  A new scene (the
; hills / the city) pins other colours: everything is baked again (no background shown: the scene stays).

ST_LINES = 136
ST_LB = 120				; (15 groups)
GR_LINES = 64
GR_LB = 256				; (32 groups)
TX_FIRST = 7*32				; the first cell of the playfield's text
TX_CELLS = 25*32

	section text,code

; tx_reset: the images empty, no slots given; the scene's colours pinned (d0 = 0 hills, 1 city); every cell baked
; again by the next tx_update
tx_reset:
	movem.l	d0-d2/a0-a1,-(sp)
	move.b	d0,tx_scene
	movem.l	d3-d5,-(sp)		; the hills' / city's fill slot as plane bytes (tb_fill: plane 0 in the high
	lea	mp_bgfill+1,a0		; byte, as movep.l writes it first); gr_imgf all of it (empty cells are not baked)
	move.b	(a0,d0.w),d2
	moveq	#0,d1
	moveq	#3,d3
.tf:	lsl.l	#8,d1
	lsr.b	#1,d2
	bcc.s	.tf0
	st	d1
.tf0:	dbf	d3,.tf
	move.l	d1,tb_fill
	moveq	#0,d3			; (as ST words: planes 0-1, 2-3)
	moveq	#0,d4
	btst	#31,d1
	beq.s	.w0
	move.l	#$FFFF0000,d3
.w0:	btst	#23,d1
	beq.s	.w1
	or.w	#$FFFF,d3
.w1:	btst	#15,d1
	beq.s	.w2
	move.l	#$FFFF0000,d4
.w2:	btst	#7,d1
	beq.s	.w3
	or.w	#$FFFF,d4
.w3:	lea	gr_imgf,a0
	move.w	#GR_LINES*GR_LB/8-1,d5
.wf:	move.l	d3,(a0)+
	move.l	d4,(a0)+
	dbf	d5,.wf
	movem.l	(sp)+,d3-d5
	lea	st_img,a0
	move.w	#(ST_LINES*ST_LB+ST_LINES*30+GR_LINES*GR_LB+GR_LINES*64)/4-1,d1
.cl:	clr.l	(a0)+
	dbf	d1,.cl
	lea	st_cnt,a0		; (the counts, the group bits)
	move.w	#(ST_LINES+GR_LINES)*5/2-1,d1
.cc:	clr.l	(a0)+
	dbf	d1,.cc
	lea	cid_ref,a0
	move.w	#MP_NCID-1,d1
.cr:	clr.w	(a0)+
	dbf	d1,.cr
	lea	cid_slot,a0
	move.w	#MP_NCID-1,d1
.cs:	clr.b	(a0)+
	dbf	d1,.cs
	lea	slot_cid,a0		; slots 0 .. MP_NPIN - 1 pinned, the rest free
	moveq	#MP_NPIN-1,d1
.sp:	clr.b	(a0)+
	dbf	d1,.sp
	moveq	#16-MP_NPIN-1,d1
.sf:	st	(a0)+
	dbf	d1,.sf
	lea	mp_pincid,a0		; the scene's pinned ids (an id pinned twice keeps its first slot)
	tst.b	d0
	beq.s	.hl
	lea	MP_NPIN(a0),a0
.hl:	lea	cid_slot,a1
	moveq	#0,d1
.pin:	moveq	#0,d2
	move.b	(a0,d1.w),d2
	beq.s	.pn			; (id 0: slot 0 already)
	tst.b	(a1,d2.w)
	bne.s	.pn
	move.b	d1,(a1,d2.w)
.pn:	addq.w	#1,d1
	cmp.w	#MP_NPIN,d1
	blo.s	.pin
	st	tx_full
	movem.l	(sp)+,d0-d2/a0-a1
	rts

; tx_update: the scene's pins (a new one: tx_reset), then the cells of rows 7-31 whose code or colour changed since
; they were baked (every one after a reset)
tx_update:
	movem.l	d0-d7/a0-a6,-(sp)
	moveq	#0,d0			; the scene: the city when the hills are off (no background at all: the scene
	move.b	io_regs+6,d1		; stays, its pinned colours too: a new scene bakes every cell again)
	btst	#1,d1
	beq.s	.s1
	moveq	#1,d0
	btst	#2,d1
	bne.s	.s0
.s1:	btst	#5,d1
	beq.s	.sc
.s0:	tst.b	tx_scene
	bpl.s	.same			; (but the first picture's)
.sc:	cmp.b	tx_scene,d0
	beq.s	.same
	bsr	tx_reset
.same:	lea	Z_RAM+$8000+TX_FIRST,a0
	lea	Z_RAM+$8400+TX_FIRST,a1
	lea	tx_vram,a2
	lea	tx_cram,a3
	move.w	#TX_FIRST,d6		; the cell
	tst.b	tx_full
	bne	.all
.long:	rept	5			; (four cells at a time: equal longs skipped)
	cmpm.l	(a0)+,(a2)+
	bne.s	.dc
	cmpm.l	(a1)+,(a3)+
	bne.s	.dk
	endr
	cmp.l	#tx_vram+TX_CELLS,a2
	blo.s	.long
	bra.s	.out
.dc:	move.l	a3,d6			; (the codes differ: the colours' pointer is at the long)
	bra.s	.diff4
.dk:	move.l	a3,d6			; (the colours differ)
	subq.l	#4,d6
.diff4:	sub.l	#tx_cram-TX_FIRST,d6	; the long's first cell (past the end: the unrolled compares overran)
	cmp.w	#TX_FIRST+TX_CELLS,d6
	bhs.s	.out
	lea	Z_RAM+$8000,a0		; (the four pointers at the long's first cell again)
	add.w	d6,a0
	lea	Z_RAM+$8400,a1
	add.w	d6,a1
	lea	tx_vram-TX_FIRST,a2
	add.w	d6,a2
	lea	tx_cram-TX_FIRST,a3
	add.w	d6,a3
	moveq	#3,d7
.cell:	move.b	(a0)+,d0
	move.b	(a1)+,d1
	cmp.b	(a2),d0
	bne.s	.chg
	cmp.b	(a3),d1
	beq.s	.nc
.chg:	bsr	tx_cell
.nc:	addq.w	#1,a2
	addq.w	#1,a3
	addq.w	#1,d6
	dbf	d7,.cell
	cmp.w	#TX_FIRST+TX_CELLS,d6
	blo	.long
	bra.s	.out
.all:	moveq	#0,d7			; (every cell: the old one counts as nothing)
.al:	move.b	(a0)+,d0
	move.b	(a1)+,d1
	bsr	tx_cell
	addq.w	#1,a2
	addq.w	#1,a3
	addq.w	#1,d6
	cmp.w	#TX_FIRST+TX_CELLS,d6
	blo.s	.al
	clr.b	tx_full
.out:	movem.l	(sp)+,d0-d7/a0-a6
	rts

; tx_cell: cell d6 (row * 32 + column) is now code d0.b / colour d1.b (the copies at a2 / a3 hold the old ones,
; unless tx_full): its ids counted, slots given and freed, the cell baked; the copies updated.  Keeps d6-d7/a0-a3.
tx_cell:
	movem.l	d6-d7/a0-a3,-(sp)
	move.w	d6,d2
	lsr.w	#5,d2			; the row
	move.w	d6,d3
	and.w	#31,d3			; the column
	cmp.w	#24,d2
	bhs.s	.vis			; (the ground: all 32 columns are in its ring)
	tst.w	d3
	beq.s	.copy			; (fixed rows: columns 1-30 are shown)
	cmp.w	#31,d3
	beq.s	.copy
.vis:	moveq	#0,d4			; (a tile without pixels where there was none: nothing to bake)
	move.b	d0,d4
	btst	#7,d1
	beq.s	.e1
	bset	#8,d4
.e1:	lea	mp_tused,a0
	tst.b	(a0,d4.w)
	bne.s	.e3
	tst.b	tx_full
	bne.s	.copy
	moveq	#0,d4
	move.b	(a2),d4
	btst	#7,(a3)
	beq.s	.e2
	bset	#8,d4
.e2:	tst.b	(a0,d4.w)
	beq.s	.copy
.e3:	tst.b	tx_full
	bne.s	.new
	move.b	(a2),d4			; the old cell's ids released
	move.b	(a3),d5
	movem.w	d0-d3,-(sp)
	move.b	d4,d0
	move.b	d5,d1
	bsr	cell_code
	bsr	cids_dec
	movem.w	(sp)+,d0-d3
.new:	movem.w	d0-d3,-(sp)
	bsr	cell_code
	bsr	cids_inc
	movem.w	(sp)+,d0-d3
	movem.w	d0-d1,-(sp)		; (the raw bytes kept for the copies)
	bsr	cell_code		; (the colour byte's bit 7 is the code's bit 8)
	bsr	tx_bake
	movem.w	(sp)+,d0-d1
.copy:	movem.l	(sp)+,d6-d7/a0-a3
	move.b	d0,(a2)
	move.b	d1,(a3)
	rts

; cell_code: d0.b = the tile byte, d1.b = the colour byte -> d0.w = the code (9 bits), d1.w = the colour (7 bits)
cell_code:
	and.w	#$FF,d0
	and.w	#$FF,d1
	bclr	#7,d1
	beq.s	.lo
	bset	#8,d0
.lo:	rts

; cids_inc / cids_dec: the ids of code d0 / colour d1's pens (the tile's pixel values 1-3) counted up (a first use
; takes a free slot, or borrows the nearest colour's) or down (the last use frees its slot).  d0-d5/a0-a1 changed.
cids_inc:
	moveq	#1,d5
	bra.s	cids
cids_dec:
	moveq	#-1,d5
cids:	lea	mp_tused,a0
	move.b	(a0,d0.w),d4		; the pixel values used (bits 1-3)
	lsl.w	#2,d1			; the colour's first pen
	moveq	#1,d3
.v:	btst	d3,d4
	beq.s	.nv
	lea	mp_pencid,a0
	move.w	d1,d2
	add.w	d3,d2
	moveq	#0,d0
	move.b	(a0,d2.w),d0		; the id
	bsr.s	cid_count
.nv:	addq.w	#1,d3
	cmp.w	#4,d3
	blo.s	.v
	rts

; cid_count: id d0 counted by d5 (+1 / -1); keeps d1/d3-d5
cid_count:
	lea	cid_ref,a0
	add.w	d0,d0
	tst.w	d5
	bmi.s	.dec
	addq.w	#1,(a0,d0.w)
	cmp.w	#1,(a0,d0.w)
	bne	.out
	lsr.w	#1,d0			; a first use: a slot unless pinned
	lea	cid_slot,a0
	tst.b	(a0,d0.w)
	bne	.out
	tst.w	d0
	beq.s	.out			; (id 0 is slot 0's)
	bra	cid_give
.dec:	subq.w	#1,(a0,d0.w)
	bne.s	.out
	lsr.w	#1,d0			; the last use: its slot free (a pinned one stays)
	lea	cid_slot,a0
	move.b	(a0,d0.w),d2
	bmi.s	.unb
	cmp.b	#MP_NPIN,d2
	blo.s	.out
	lea	slot_cid,a1
	st	(a1,d2.w)
.unb:	clr.b	(a0,d0.w)
.out:	rts

; cid_give: id d0 (a0 = cid_slot) takes a free slot (MP_NPIN-15), or (none free) borrows the nearest colour's own slot
; (flagged $80).  d2/d6/a1 changed.
cid_give:
	lea	slot_cid+MP_NPIN,a1	; a free slot MP_NPIN-15
	moveq	#MP_NPIN,d2
.find:	cmp.b	#$FF,(a1)+
	beq.s	.take
	addq.w	#1,d2
	cmp.w	#16,d2
	blo.s	.find
	lea	mp_cidnear,a1		; none: the nearest colour with a slot (borrowed)
	move.w	d0,d2
	mulu	#MP_NCID,d2
	add.w	d2,a1
	moveq	#MP_NCID-1,d2
.near:	moveq	#0,d6
	move.b	(a1)+,d6
	tst.w	d6
	beq.s	.bz			; (id 0: slot 0)
	move.b	(a0,d6.w),d6
	beq.s	.nn
	bmi.s	.nn			; (a borrowed one: not its own)
	or.b	#$80,d6
	move.b	d6,(a0,d0.w)
	rts
.bz:	move.b	#$80,(a0,d0.w)		; (slot 0, borrowed)
	rts
.nn:	dbf	d2,.near
	rts
.take:	move.b	d2,(a0,d0.w)
	move.b	d0,-(a1)
	rts
	rts

; tx_retry: an id the text cells use whose slot is borrowed (no slot was free) gets one now if one is (or borrows
; another); its cells are baked again when its slot changed
tx_retry:
	movem.l	d0-d7/a0-a1,-(sp)
	moveq	#1,d0
.c:	lea	cid_slot,a0
	move.b	(a0,d0.w),d7
	bpl.s	.n
	lea	cid_ref,a1
	move.w	d0,d1
	add.w	d1,d1
	tst.w	(a1,d1.w)
	beq.s	.n
	clr.b	(a0,d0.w)
	move.w	d0,-(sp)
	bsr	cid_give
	move.w	(sp)+,d0
	cmp.b	(a0,d0.w),d7
	beq.s	.n
	bsr	tx_rebake
.n:	addq.w	#1,d0
	cmp.w	#MP_NCID,d0
	blo.s	.c
	movem.l	(sp)+,d0-d7/a0-a1
	rts

; tx_rebake: the baked cells that use id d0 baked again (their slots changed).  Keeps all.
tx_rebake:
	movem.l	d0-d7/a0-a4,-(sp)
	move.w	d0,d7
	lea	tx_vram,a2
	lea	tx_cram,a3
	move.w	#TX_FIRST,d6
.cell:	move.w	d6,d2
	lsr.w	#5,d2			; the row
	move.w	d6,d3
	and.w	#31,d3			; the column
	cmp.w	#24,d2
	bhs.s	.vis
	tst.w	d3
	beq.s	.nx
	cmp.w	#31,d3
	beq.s	.nx
.vis:	move.b	(a2),d0
	move.b	(a3),d1
	bsr	cell_code
	lea	mp_tused,a0
	move.b	(a0,d0.w),d4		; the values its tile has
	move.w	d1,d5
	lsl.w	#2,d5
	lea	mp_pencid,a0
	add.w	d5,a0
	moveq	#1,d5
.v:	btst	d5,d4
	beq.s	.nv
	moveq	#0,d4
	move.b	(a0,d5.w),d4
	cmp.w	d7,d4
	bne.s	.nv0
	bsr	tx_bake
	bra.s	.nx
.nv0:	lea	mp_tused,a1		; (d4 was the values: again)
	move.b	(a1,d0.w),d4
.nv:	addq.w	#1,d5
	cmp.w	#4,d5
	blo.s	.v
.nx:	addq.w	#1,a2
	addq.w	#1,a3
	addq.w	#1,d6
	cmp.w	#TX_FIRST+TX_CELLS,d6
	blo.s	.cell
	movem.l	(sp)+,d0-d7/a0-a4
	rts

; tx_bake: code d0.w / colour d1.w into the image at row d2 / column d3 (a fixed row: st_img, columns 1-30; the
; ground: gr_img, both copies): 8 lines of plane bytes (the pens' slots) and the mask byte; the lines' counts.
tx_bake:
	movem.l	d0-d7/a0-a6,-(sp)
	ifd SIM
	lea	cnt_rows,a0
	move.w	d2,d4
	lsl.w	#2,d4
	addq.l	#1,(a0,d4.w)
	endc
	lea	pf_dirty-7*8*2,a0	; (its 8 lines changed in every buffer: render.s pf_draw; a fixed row's cell in
	move.w	d2,d4			; its group (column - 1) >> 1, a ground cell everywhere)
	lsl.w	#4,d4
	add.w	d4,a0
	move.w	#$7FFF,d5
	cmp.w	#24,d2
	bhs.s	.dg
	move.w	d3,d4
	subq.w	#1,d4
	asr.w	#1,d4
	bmi.s	.dn			; (columns 0 and 31 are not shown)
	cmp.w	#14,d4
	bhi.s	.dn
	moveq	#0,d5
	bset	d4,d5
.dg:	moveq	#2,d4
.db:	rept	8
	or.w	d5,(a0)+
	endr
	lea	(PF_NL-8)*2(a0),a0
	dbf	d4,.db
.dn:
	lea	mp_pencid,a0		; the slots of pixel values 1-3 (bits 0-3; a borrowed one's too)
	lea	cid_slot,a1
	lsl.w	#2,d1
	moveq	#0,d4
	move.b	1(a0,d1.w),d4
	move.b	(a1,d4.w),d4
	and.w	#15,d4
	moveq	#0,d5
	move.b	2(a0,d1.w),d5
	move.b	(a1,d5.w),d5
	and.w	#15,d5
	moveq	#0,d6
	move.b	3(a0,d1.w),d6
	move.b	(a1,d6.w),d6
	and.w	#15,d6
	lea	slot_long,a0		; (each value's planes as bytes $FF / 0: tb_s1-3)
	lsl.w	#2,d4
	move.l	(a0,d4.w),tb_s1
	lsl.w	#2,d5
	move.l	(a0,d5.w),tb_s2
	lsl.w	#2,d6
	move.l	(a0,d6.w),tb_s3
	lsl.w	#4,d0			; the tile's rows
	lea	mp_tiles,a3
	add.w	d0,a3
	cmp.w	#24,d2
	bhs.s	.ground
	sub.w	#7,d2			; a fixed row: image line (row - 7) * 8, x = 8 * (column - 1)
	lsl.w	#3,d2
	move.w	d2,d0
	mulu	#ST_LB,d0
	lea	st_img,a4
	add.l	d0,a4
	move.w	d2,d0
	mulu	#30,d0
	lea	st_mask,a5
	add.l	d0,a5
	subq.w	#1,d3
	move.w	d3,d0
	lsr.w	#1,d0
	move.w	d0,tb_grp		; (the cell's group)
	move.w	d0,d1
	lsl.w	#3,d0
	add.w	d1,d1
	and.w	#1,d3
	add.w	d3,d0
	add.w	d3,d1
	add.w	d0,a4			; the plane bytes' first
	add.w	d1,a5			; the mask byte
	lea	st_cnt,a6
	add.w	d2,a6
	add.w	d2,a6
	move.w	#ST_LB,d7
	sub.l	a2,a2			; (no twin)
	moveq	#30,d3			; (the mask's bytes a line)
	bra.s	.lines
.ground: sub.w	#24,d2			; the ground: image line (row - 24) * 8, x = 8 * column, and 256 further
	lsl.w	#3,d2
	move.w	d2,d0
	lsl.w	#8,d0			; (GR_LB = 256)
	lea	gr_img,a4
	add.w	d0,a4
	move.w	d2,d0
	lsl.w	#6,d0			; (64 mask bytes a line)
	lea	gr_mask,a5
	add.w	d0,a5
	move.w	d3,d0
	lsr.w	#1,d0
	move.w	d0,tb_grp		; (the cell's group)
	move.w	d0,d1
	lsl.w	#3,d0
	add.w	d1,d1
	and.w	#1,d3
	add.w	d3,d0
	add.w	d3,d1
	add.w	d0,a4
	add.w	d1,a5
	lea	gr_cnt,a6
	add.w	d2,a6
	add.w	d2,a6
	move.w	#GR_LB,d7
	move.w	#1,a2			; (the twin: 128 bytes / 32 mask bytes further)
	moveq	#64,d3
.lines:	moveq	#7,d2
	lea	rep4,a1
.row:	moveq	#0,d4
	move.b	(a3)+,d4		; the high plane (the pixel value's bit 1)
	moveq	#0,d5
	move.b	(a3)+,d5		; the low plane
	move.w	d4,d0			; value 3: high and low, its slot's planes
	and.w	d5,d0
	add.w	d0,d0
	add.w	d0,d0
	move.l	(a1,d0.w),d6		; (the byte in all four planes)
	and.l	tb_s3,d6
	move.w	d5,d0			; value 2: high, not low
	not.w	d0
	and.w	d4,d0
	add.w	d0,d0
	add.w	d0,d0
	move.l	(a1,d0.w),d1
	and.l	tb_s2,d1
	or.l	d1,d6
	move.w	d4,d0			; value 1: low, not high
	not.w	d0
	and.w	d5,d0
	add.w	d0,d0
	add.w	d0,d0
	move.l	(a1,d0.w),d1
	and.l	tb_s1,d1
	or.l	d1,d6
	movep.l	d6,0(a4)
	or.b	d5,d4			; the mask: any pixel but 0
	cmp.w	#0,a2
	beq.s	.nf
	move.b	d4,d0			; (the ground: the version with the fill's slot in the holes, gr_imgf)
	not.b	d0
	move.l	tb_fill,d1
	and.b	d0,d1
	ror.l	#8,d1
	and.b	d0,d1
	ror.l	#8,d1
	and.b	d0,d1
	ror.l	#8,d1
	and.b	d0,d1
	ror.l	#8,d1
	or.l	d6,d1
	movep.l	d1,gr_imgf-gr_img(a4)
	movep.l	d1,gr_imgf-gr_img+128(a4)
.nf:	and.w	#$FF,d4
	moveq	#0,d0			; the line's count: + the new pixels - the old
	moveq	#0,d1
	move.b	(a5),d1
	lea	popcnt,a0
	move.b	(a0,d4.w),d0
	sub.b	(a0,d1.w),d0
	ext.w	d0
	add.w	d0,(a6)+
	move.b	d4,(a5)
	cmp.w	#0,a2
	beq.s	.nt
	movep.l	d6,128(a4)
	move.b	d4,32(a5)
.nt:	add.w	d7,a4
	add.w	d3,a5
	dbf	d2,.row
	move.l	a6,d0			; the 8 lines' group bits (tx_nz: any pixel, tx_opq: all 16; the ground's twin
	sub.l	#st_cnt+16,d0		; group too, 16 further): the line index (st_cnt, gr_cnt: a word a line)
	add.w	d0,d0
	lea	tx_nz,a0
	add.w	d0,a0
	lea	tx_opq,a1
	add.w	d0,a1
	move.w	d3,d0			; the group's mask word in the first line
	lsl.w	#3,d0
	sub.w	d0,a5
	move.l	a5,d0
	bclr	#0,d0
	move.l	d0,a5
	move.w	tb_grp,d1
	moveq	#16,d5
	add.w	d1,d5			; (the twin's bit)
	moveq	#7,d2
.nb:	move.l	(a0),d6
	move.l	(a1),d7
	bclr	d1,d6
	bclr	d1,d7
	move.w	(a5),d0
	beq.s	.nb1
	bset	d1,d6
	cmp.w	#-1,d0
	bne.s	.nb1
	bset	d1,d7
.nb1:	cmp.w	#0,a2
	beq.s	.nb2
	bclr	d5,d6
	bclr	d5,d7
	btst	d1,d6
	beq.s	.nb2
	bset	d5,d6
	btst	d1,d7
	beq.s	.nb2
	bset	d5,d7
.nb2:	move.l	d6,(a0)+
	move.l	d7,(a1)+
	add.w	d3,a5
	dbf	d2,.nb
	movem.l	(sp)+,d0-d7/a0-a6
	rts

; the playfield's slots MP_NPIN-15 into the drawn buffer's palette (the ids' colours; a free slot black)
pf_slots:
	move.w	draw_idx,d0
	lsl.w	#5,d0
	lea	pf_pal+2*MP_NPIN,a0
	add.w	d0,a0
	lea	slot_cid+MP_NPIN,a1
	lea	mp_cidcol,a2
	moveq	#16-MP_NPIN-1,d1
.s:	moveq	#0,d0
	move.b	(a1)+,d0
	cmp.b	#$FF,d0
	bne.s	.c
	clr.w	(a0)+
	bra.s	.n
.c:	add.w	d0,d0
	move.w	(a2,d0.w),(a0)+
.n:	dbf	d1,.s
	rts

; popcnt: the bits set in a byte (made by init_render)
make_popcnt:
	lea	rep4,a0			; (and rep4, slot_long)
	moveq	#0,d0
.r:	move.b	d0,d1
	lsl.w	#8,d1
	move.b	d0,d1
	move.w	d1,d2
	swap	d1
	move.w	d2,d1
	move.l	d1,(a0)+
	addq.w	#1,d0
	cmp.w	#256,d0
	blo.s	.r
	lea	slot_long,a0
	moveq	#0,d0
.sl:	moveq	#0,d1
	moveq	#3,d3
	move.w	d0,d2
.s1:	lsl.l	#8,d1
	lsr.w	#1,d2
	bcc.s	.s2
	st	d1
.s2:	dbf	d3,.s1
	move.l	d1,(a0)+
	addq.w	#1,d0
	cmp.w	#16,d0
	blo.s	.sl
	lea	popcnt,a0
	moveq	#0,d0
.b:	moveq	#0,d1
	move.w	d0,d2
	moveq	#7,d3
.c:	lsr.w	#1,d2
	bcc.s	.z
	addq.b	#1,d1
.z:	dbf	d3,.c
	move.b	d1,(a0)+
	addq.w	#1,d0
	cmp.w	#256,d0
	blo.s	.b
	rts


	section bss,bss
	even
st_img:		ds.b	ST_LINES*ST_LB
st_mask:	ds.b	ST_LINES*30
gr_img:		ds.b	GR_LINES*GR_LB
gr_mask:	ds.b	GR_LINES*64
gr_imgf:	ds.b	GR_LINES*GR_LB	; (the ground with the hills' / city's fill in its holes)
st_cnt:		ds.w	ST_LINES
gr_cnt:		ds.w	GR_LINES
tx_nz:		ds.l	ST_LINES+GR_LINES	; a line's groups with text pixels (bit k: group k; the ground: 32, twice)
tx_opq:		ds.l	ST_LINES+GR_LINES	; and those without a transparent pixel
tb_grp:		ds.w	1
tb_fill:	ds.l	1
cid_ref:	ds.w	MP_NCID
tb_s1:		ds.l	1		; (tx_bake: the values' planes)
tb_s2:		ds.l	1
tb_s3:		ds.l	1
rep4:		ds.l	256		; a byte in all four bytes of a long
slot_long:	ds.l	16		; a slot's planes as bytes $FF / 0 (plane 0 the high byte)
	ifd SIM
cnt_rows:	ds.l	32
	endc
tx_vram:	ds.b	TX_CELLS
tx_cram:	ds.b	TX_CELLS
cid_slot:	ds.b	MP_NCID		; an id's slot (0: none, but id 0's; $80 + n: borrowed)
slot_cid:	ds.b	16		; a slot's id ($FF: free)
popcnt:		ds.b	256
tx_scene:	ds.b	1
tx_full:	ds.b	1
	even
	section text,code
