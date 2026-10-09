; ------------------------------------------------------------------------------
; Tile renderer, stars, characters over sprites
;
; The arcade tile map is 36 x 28 characters of 8 x 8 pixels, 2 bits, in the video RAM
; $8000-$83FF (codes) and $8400-$87FF (colour codes); the screen shows it rotated by 90
; degrees (ga_map_index: display cell -> video RAM index, tilemap_scan of MAME).
; A character cell is 4 bytes per row in the screen (one MOVEP.L), expanded offline per
; colour quad (tools/assets.py), pen 0 black.
;
; A background screen holds the characters only.  Changed cells are drawn there at once
; and queued for both draw screens.  The characters are drawn over the sprites in the
; arcade (their pen 0 is transparent): after the sprites, the cells a sprite was drawn in
; this frame get their character back, masked (chars_over).
;
; The stars (05XX, galaga_stars.s) are single pixels in the two grey colours 14 and 15,
; plotted where the draw screen is black after the sprites; the previous frame's stars of
; a draw screen are cleared before any screen updates.
; ------------------------------------------------------------------------------

DISP_TOP = 32				; the display's line 0 is this line of a screen buffer

init_render:
	lea	cell_shadow,a0
	move	#511,d0
	moveq	#-1,d1
.clear:
	move.l	d1,(a0)+
	dbf	d0,.clear
	lea	cell_content,a0
	move	#MARK_SIZE/4-1,d0
.clear_content:
	clr.l	(a0)+
	dbf	d0,.clear_content
	clr	list_count
	clr	list_count+2
	clr.b	list_full
	clr.b	list_full+1
	st	force_scan
	clr	star_count
	clr	star_count+2
	bsr	init_sprites
	bsr	init_stars
	rts

; ------------------------------------------------------------------------------

render_frame:
	lea	tile_marks,a0		; no cell is marked yet in this frame
	moveq	#0,d0
	moveq	#0,d1
	moveq	#0,d2
	moveq	#0,d3
	moveq	#0,d4
	moveq	#0,d5
	moveq	#0,d6
	moveq	#0,d7
	rept MARK_SIZE/32
	movem.l	d0-d7,(a0)
	lea	32(a0),a0
	endr
	lea	spr_marks,a0
	rept MARK_SIZE/32
	movem.l	d0-d7,(a0)
	lea	32(a0),a0
	endr

	; Remove only stars from the previous completed picture, before any writes.
	ifnd NOSTARS
	bsr	erase_stars
	endc
	bsr	scan_cells
	bsr	draw_dirty_cells
	bsr	draw_sprites
	bsr	chars_over
	; Plot last: every recorded star owns a previously black pixel.
	ifnd NOSTARS
	bsr	draw_stars
	endc
	rts

; ------------------------------------------------------------------------------
; After a translated block instruction that wrote the video RAM (gen.py): the blocks of 32 bytes from vblock_de (DE
; before) to d2 (DE after), either direction, marked; more than all of them: vblock_all.  Registers and CCR kept.

vblock_range:
	move	sr,-(sp)
	movem.l	d0-d1/a0,-(sp)
	move	vblock_de,d0
	move	d2,d1
	cmp	d0,d1
	bhs.s	.up
	exg	d0,d1
.up:	lsr	#5,d0
	lsr	#5,d1
	sub	d0,d1			; blocks - 1
	cmp	#63,d1
	bls.s	.mark
	st	vblock_all
	bra.s	.done
.mark:	lea	vblocks,a0
.m:	and	#63,d0
	st	(a0,d0.w)
	addq	#1,d0
	dbf	d1,.m
.done:	movem.l	(sp)+,d0-d1/a0
	move	(sp)+,ccr
	rts

; ------------------------------------------------------------------------------
; Find the changed cells (code or colour), draw them into the background and queue them.

scan_cells:
	lea	g_ram,a0		; video RAM: codes, then colours
	lea	cell_shadow,a1
	lea	dirty_lists,a4		; list for draw screen 0
	move	list_count,d4
	add	d4,d4
	add	d4,a4
	lea	dirty_lists+4096,a5	; list for draw screen 1
	move	list_count+2,d5
	add	d5,d5
	add	d5,a5
	move.l	bg_address,a3

	tst.b	force_scan
	bne	.forced

	; The translated writers of the video RAM mark the blocks of 32 bytes they wrote (vblocks, gen.py; vblock_all: any
	; of it): only those are compared with the copy, then 128 bytes a render in case a writer is missing there (a
	; change found there is still drawn; DEBUG counts it in scan_missed).  A mark is cleared before its block is
	; compared: a write during the compare marks it again for the next render.
	clr.b	scan_rolling
	lea	vblocks,a2
	tst.b	vblock_all
	beq.s	.blocks
	clr.b	vblock_all
	moveq	#64/4-1,d7
.clr:	clr.l	(a2)+
	dbf	d7,.clr
	move	#512/8-1,d7
	bsr	.compare
	bra	.finished
.blocks:
	moveq	#0,d6			; the block
.bl4:	tst.l	(a2,d6.w)		; (four marks at a time)
	bne.s	.bl
	addq	#4,d6
	cmp	#64,d6
	blo.s	.bl4
	bra.s	.roll
.bl:	tst.b	(a2,d6.w)
	beq.s	.nob
	clr.b	(a2,d6.w)
	move	d6,-(sp)
	move	d6,d0
	lsl	#5,d0
	lea	g_ram,a0
	lea	cell_shadow,a1
	add	d0,a0
	add	d0,a1
	moveq	#0,d7
	bsr	.compare
	move	(sp)+,d6
.nob:	addq	#1,d6
	moveq	#3,d0
	and	d6,d0
	bne.s	.bl
	cmp	#64,d6
	blo.s	.bl4
.roll:
	st	scan_rolling
	move	chars_roll,d0
	add	#128,d0
	and	#$7ff,d0
	move	d0,chars_roll
	lea	g_ram,a0
	lea	cell_shadow,a1
	add	d0,a0
	add	d0,a1
	moveq	#128/32-1,d7
	bsr	.compare
	clr.b	scan_rolling
	bra	.finished

; d7 + 1 groups of 32 bytes at a0 (the video RAM) / a1 (its copy): the changed cells queued
.compare:
	cmpm.l	(a0)+,(a1)+
	bne.s	.diff0
.c1:	cmpm.l	(a0)+,(a1)+
	bne.s	.diff1
.c2:	cmpm.l	(a0)+,(a1)+
	bne.s	.diff2
.c3:	cmpm.l	(a0)+,(a1)+
	bne.s	.diff3
.c4:	cmpm.l	(a0)+,(a1)+
	bne.s	.diff4
.c5:	cmpm.l	(a0)+,(a1)+
	bne.s	.diff5
.c6:	cmpm.l	(a0)+,(a1)+
	bne.s	.diff6
.c7:	cmpm.l	(a0)+,(a1)+
	bne.s	.diff7
.c8:	dbf	d7,.compare
	rts

.diff0:	bsr.s	.diff
	bra.s	.c1
.diff1:	bsr.s	.diff
	bra.s	.c2
.diff2:	bsr.s	.diff
	bra.s	.c3
.diff3:	bsr.s	.diff
	bra.s	.c4
.diff4:	bsr.s	.diff
	bra.s	.c5
.diff5:	bsr.s	.diff
	bra.s	.c6
.diff6:	bsr.s	.diff
	bra.s	.c7
.diff7:	bsr.s	.diff
	bra.s	.c8

; The long before a0 / a1 differs: queue the cells of its changed bytes.

.diff:
	ifd DEBUG
	tst.b	scan_rolling
	beq.s	.counted
	addq	#1,scan_missed		; a change no translated writer flagged
.counted:
	endc
	subq.l	#4,a0
	subq.l	#4,a1
	move.l	a0,d0
	sub.l	#g_ram,d0		; index of the first byte
	moveq	#3,d3
.byte:
	move.b	(a0)+,d1
	cmp.b	(a1),d1
	beq.s	.same
	move.b	d1,(a1)
	move	d0,d2
	and	#$3ff,d2		; the cell (code or colour byte)
	bsr.s	.queue
.same:
	addq.l	#1,a1
	addq	#1,d0
	dbf	d3,.byte
	rts

.forced:
	clr.b	force_scan
	move	#2047,d3
.copy:	move.b	(a0)+,(a1)+
	dbf	d3,.copy
	moveq	#0,d2
.force_one:
	bsr.s	.queue
	addq	#1,d2
	cmp	#1024,d2
	blt.s	.force_one

.finished:
	sub.l	#dirty_lists,a4
	move.l	a4,d0
	lsr	#1,d0
	move	d0,list_count
	lea	dirty_lists+4096,a4
	sub.l	a4,a5
	move.l	a5,d0
	lsr	#1,d0
	move	d0,list_count+2
	rts

; d2.w = video RAM index of a cell; preserves everything except a4/a5 (list pointers)

.queue:
	movem.l	d0-d3/a0-a3,-(sp)
	move	d2,d0
	add	d0,d0
	lea	ga_cell_of_index,a1
	move	(a1,d0.w),d0		; display cell
	bmi.s	.skip			; not shown
	move.l	a3,a0
	bsr	draw_cell
	move	d0,d1			; cell_content: a bit per cell whose character has an opaque pixel
	add	d1,d1			; (tile_marks' layout; the restore of the sprites tests it)
	lea	ga_map_index,a1
	move	(a1,d1.w),d2		; video RAM index
	lea	g_ram,a1
	moveq	#0,d3
	move.b	(a1,d2.w),d3
	and	#$7f,d3
	lea	ga_char_blank,a1
	move.b	(a1,d3.w),d3		; 1: blank
	lea	ga_cell_mark_byte,a1
	move	(a1,d1.w),d1
	lea	ga_cell_mark_bit,a1
	move.b	(a1,d0.w),d2
	lea	cell_content,a1
	tst.b	d3
	bne.s	.cc_blank
	bset	d2,(a1,d1.w)
	bra.s	.cc_done
.cc_blank:
	bclr	d2,(a1,d1.w)
.cc_done:
	cmp.l	#dirty_lists+4096,a4	; a full list (a draw screen that is not drawn for a few
	blo.s	.q0			; frames while the program rewrites the screen): the
	st	list_full		; screen gets all its cells again
	bra.s	.q1
.q0:	move	d0,(a4)+		; (a4 and a5 are not saved: they advance)
.q1:	cmp.l	#dirty_lists+8192,a5
	blo.s	.q2
	st	list_full+1
	bra.s	.skip
.q2:	move	d0,(a5)+
.skip:
	movem.l	(sp)+,d0-d3/a0-a3
	rts

; ------------------------------------------------------------------------------
; Draw the queued cells into the current draw screen and mark them.

draw_dirty_cells:
	move	draw_index,d0
	move	d0,d1
	add	d1,d1
	lea	list_count,a1
	lea	list_full,a0
	tst.b	(a0,d0.w)
	bne.s	.all
	move	(a1,d1.w),d7
	beq.s	.nothing
	clr	(a1,d1.w)
	lea	dirty_lists,a2
	moveq	#12,d1
	lsl	d1,d0
	add	d0,a2
	subq	#1,d7
.loop:
	move	(a2)+,d0
	move.l	draw_screen_address,a0
	move.l	a2,-(sp)
	bsr	draw_cell
	move.l	(sp)+,a2
	bsr	mark_cell
	dbf	d7,.loop
.nothing:
	rts

.all:	clr.b	(a0,d0.w)		; the list overflowed: every cell of the screen
	clr	(a1,d1.w)
	moveq	#0,d7
.all_loop:
	move	d7,d0
	add	d0,d0
	lea	ga_cell_of_index,a1
	move	(a1,d0.w),d0
	bmi.s	.all_next
	move.l	draw_screen_address,a0
	bsr	draw_cell
	bsr	mark_cell
.all_next:
	addq	#1,d7
	cmp	#1024,d7
	blo.s	.all_loop
	rts

; d0.w = display cell: the sprites on it have to be drawn again.  Keeps d0.

mark_cell:
	move	d0,d1
	add	d1,d1
	lea	ga_cell_mark_byte,a1
	move	(a1,d1.w),d1
	lea	ga_cell_mark_bit,a3
	move.b	(a3,d0.w),d2
	lea	tile_marks,a1
	bset	d2,(a1,d1.w)
	rts

; ------------------------------------------------------------------------------
; draw_cell: d0.w = display cell, a0 = screen base.  Trashes d1-d3, a1-a3.

draw_cell:
	move	d0,d1
	add	d1,d1
	lea	ga_map_index,a1
	move	(a1,d1.w),d2		; video RAM index
	lea	g_ram+$400,a1
	moveq	#0,d3
	move.b	(a1,d2.w),d3		; colour code
	and	#$3f,d3
	lsl	#2,d3
	lea	ga_char_quad,a2
	move.l	(a2,d3.w),d3		; the quad's characters
	lea	g_ram,a1
	moveq	#0,d1
	move.b	(a1,d2.w),d1
	and	#$7f,d1
	lsl	#5,d1			; code * 32
	add.l	d1,d3
	lea	ga_chars,a2
	add.l	d3,a2			; source

	move	d0,d3
	lsl	#2,d3
	lea	ga_cell_off,a3
	move.l	(a3,d3.w),d3
	add.l	#DISP_TOP*STRIDE,d3
	add.l	d3,a0			; destination

	move.l	(a2)+,d3
	movep.l	d3,0(a0)
	move.l	(a2)+,d3
	movep.l	d3,256(a0)
	move.l	(a2)+,d3
	movep.l	d3,512(a0)
	move.l	(a2)+,d3
	movep.l	d3,768(a0)
	move.l	(a2)+,d3
	movep.l	d3,1024(a0)
	move.l	(a2)+,d3
	movep.l	d3,1280(a0)
	move.l	(a2)+,d3
	movep.l	d3,1536(a0)
	move.l	(a2)+,d3
	movep.l	d3,1792(a0)
	rts

; ------------------------------------------------------------------------------
; The characters over the sprites: every cell a sprite was drawn in this frame
; (spr_marks) whose character is not blank (cell_content, the same layout) gets the
; character back, the opaque pixels only.  (A cell the program rewrites during the
; render is caught up by the next frame's scan_cells.)

chars_over:
	lea	spr_marks,a4
	lea	cell_content,a3
	lea	ga_mark_cell,a5		; per mark bit: the display cell or -1
	move	#MARK_ROWS-1,d7
.row:
	move.l	(a4)+,d5		; cells 0-31 of the row
	and.l	(a3)+,d5
	move.b	(a4),d6			; cells 32-39
	and.b	(a3),d6
	addq.l	#4,a4
	addq.l	#4,a3
	moveq	#0,d4			; cell * 2
	tst.l	d5
	beq.s	.high
.bit:
	add.l	d5,d5
	bcc.s	.no_bit
	move	(a5,d4.w),d0		; display cell
	bmi.s	.no_bit
	movem.l	d4-d7/a3-a5,-(sp)
	bsr	draw_cell_masked
	movem.l	(sp)+,d4-d7/a3-a5
.no_bit:
	addq	#2,d4
	tst.l	d5
	bne.s	.bit
.high:
	tst.b	d6
	beq.s	.next_row
	moveq	#64,d4
.bit_h:
	add.b	d6,d6
	bcc.s	.no_bit_h
	move	(a5,d4.w),d0
	bmi.s	.no_bit_h
	movem.l	d4-d7/a3-a5,-(sp)
	bsr	draw_cell_masked
	movem.l	(sp)+,d4-d7/a3-a5
.no_bit_h:
	addq	#2,d4
	tst.b	d6
	bne.s	.bit_h
.next_row:
	lea	80(a5),a5
	dbf	d7,.row
	rts

; d0.w = display cell: the character's opaque pixels over the draw screen.  Trashes
; d0-d7, a0-a2.
; Opaque are the pixels not black in the colour quad's data: a pen that looks up colour
; $1f is transparent in the arcade (colour codes 27-29 have such pens 1-3), and no other
; pen is STE colour 0 (tools/assets.py).

draw_cell_masked:
	move	d0,d1
	add	d1,d1
	lea	ga_map_index,a1
	move	(a1,d1.w),d2
	lea	g_ram+$400,a1
	moveq	#0,d4
	move.b	(a1,d2.w),d4
	and	#$3f,d4
	lsl	#2,d4
	lea	ga_char_quad,a2
	move.l	(a2,d4.w),d4
	lea	g_ram,a1
	moveq	#0,d1
	move.b	(a1,d2.w),d1
	and	#$7f,d1			; code
	lsl	#5,d1
	add.l	d1,d4
	lea	ga_chars,a2
	add.l	d4,a2			; source: 8 rows of 4 plane bytes
	move	d0,d1
	lsl	#2,d1
	lea	ga_cell_off,a1
	move.l	(a1,d1.w),d1
	add.l	#DISP_TOP*STRIDE,d1
	move.l	draw_screen_address,a0
	add.l	d1,a0
	moveq	#7,d7
.rows:
	move.b	(a2)+,d0
	move.b	(a2)+,d1
	move.b	(a2)+,d2
	move.b	(a2)+,d3
	move.b	d0,d4			; mask: 1 = opaque
	or.b	d1,d4
	or.b	d2,d4
	or.b	d3,d4
	beq.s	.next_row
	not.b	d4
	and.b	d4,(a0)
	or.b	d0,(a0)
	and.b	d4,2(a0)
	or.b	d1,2(a0)
	and.b	d4,4(a0)
	or.b	d2,4(a0)
	and.b	d4,6(a0)
	or.b	d3,6(a0)
.next_row:
	lea	256(a0),a0
	dbf	d7,.rows
	rts

; ------------------------------------------------------------------------------
; Stars.  The 05XX's LFSR sequence (period 65535) is walked once per frame
; (galaga_stars.s, star_frame -> star_list: step in the window = raw x | raw y << 8, and
; the STE colour); the plots are single pixels, only where the draw screen is black
; (nothing else is drawn there), and each draw screen keeps its list (offset, bit,
; colour) to clear them before any writes next time. Characters are composed before
; plotting, so no later renderer write can overwrite a recorded star.

erase_stars:
	move	draw_index,d0
	add	d0,d0
	lea	star_count,a1
	move	(a1,d0.w),d7
	beq.s	.none
	clr	(a1,d0.w)
	lea	star_lists,a2
	mulu	#512*6/2,d0		; the list of this screen (d0 = 0 or 2)
	add.l	d0,a2
	move.l	draw_screen_address,a3
	subq	#1,d7
.loop:
	move.l	(a2)+,a0		; the pixel's byte in plane 0
	move	(a2)+,d1		; its bit (low byte), its colour (high byte)
	add.l	a3,a0
	bclr	d1,(a0)
	bclr	d1,2(a0)
	bclr	d1,4(a0)
	bclr	d1,6(a0)
.keep:
	dbf	d7,.loop
.none:
	rts

draw_stars:
	cmp	#3,star_level		; throttled: no stars (the erase of the old ones ran)
	bhs	.none
	bsr	star_frame		; -> star_list / star_n: step.w, colour.w per star
	move	star_n,d7
	beq	.none
	move	draw_index,d0
	add	d0,d0
	lea	star_count,a1
	lea	star_lists,a2
	move	d0,d1
	mulu	#512*6/2,d1		; this screen's list of plotted stars (d1 = 0 or 2)
	add.l	d1,a2
	move.l	draw_screen_address,a3
	lea	star_list,a4
	lea	star_ytab,a5
	lea	star_ybit,a6
	moveq	#0,d6			; plotted
	subq	#1,d7
.loop:
	move	(a4)+,d0		; step: raw x | raw y << 8
	move	(a4)+,d2		; STE colour 1..15
	moveq	#0,d1
	move.b	d0,d1
	add	#16+DISP_TOP,d1		; display line = raw x + 16
	lsl.l	#8,d1			; line offset
	lsr	#8,d0			; raw y
	add	d0,d0
	add	(a5,d0.w),d1		; byte of plane 0 (display x = 223 - raw y)
	move	(a6,d0.w),d3		; bit
	lea	(a3,d1.l),a0
	move.b	(a0),d4			; black there?
	or.b	2(a0),d4
	or.b	4(a0),d4
	or.b	6(a0),d4
	btst	d3,d4
	bne.s	.next
	btst	#0,d2
	beq.s	.c1
	bset	d3,(a0)
.c1:	btst	#1,d2
	beq.s	.c2
	bset	d3,2(a0)
.c2:	btst	#2,d2
	beq.s	.c3
	bset	d3,4(a0)
.c3:	btst	#3,d2
	beq.s	.c4
	bset	d3,6(a0)
.c4:
	move.l	d1,(a2)+		; remember for erasing: offset, bit and colour
	lsl	#8,d2
	or	d2,d3
	move	d3,(a2)+
	addq	#1,d6
.next:
	dbf	d7,.loop
	move	draw_index,d0
	add	d0,d0
	move	d6,(a1,d0.w)
.none:
	rts

; ------------------------------------------------------------------------------
	section bss,bss
; ------------------------------------------------------------------------------

cell_shadow:	ds.b	2048
cell_content:	ds.b	MARK_SIZE		; bit set: the background cell is not black
list_count:	ds.w	2
force_scan:	ds.b	1
vblock_all:	ds.b	1		; (the translated writers: all of the video RAM may have changed)
scan_rolling:	ds.b	1
	even
vblocks:	ds.b	64		; (the translated writers: the blocks of 32 bytes they wrote, gen.py)
	even
vblock_de:	ds.w	1		; (DE before a block instruction that writes the video RAM)
chars_roll:	ds.w	1
scan_missed:	ds.w	1		; (DEBUG)
list_full:	ds.b	2		; per draw screen: its dirty list overflowed
	even
dirty_lists:	ds.w	2048*2
star_count:	ds.w	2
star_lists:	ds.b	2*512*6		; two lists of up to 512 stars: offset.l, bit.w
	section text,code
