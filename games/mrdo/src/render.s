; Mr. Do!'s picture on the STE (included by mrdo.s).
;
; A stand-in until the renderer is written: one black screen (the borders open, engine/rt/borders.s), the palettes
; the border code needs, and render_frame counting the pictures and emptying the cell list as a renderer does.  The
; real renderer (two 2bpp tile layers, the background scrolled; sprites through engine/sprite_programs.py) comes next.

BL = 284				; buffer lines: PIC_TOP above the picture, its 256, 18 guard lines
LB = 160
BUFSZ = BL*LB

	section text,code

init_render:
	lea	buffers,a0
	move.w	#BUFSZ/16-1,d0
.clr:	clr.l	(a0)+
	clr.l	(a0)+
	clr.l	(a0)+
	clr.l	(a0)+
	dbf	d0,.clr
	lea	shown_pal,a1
	lea	black_pal,a2
	moveq	#15,d0
.pal:	clr.w	(a1)+
	clr.w	(a2)+
	dbf	d0,.pal
	move.w	#$0007,shown_pal+2	; (pen 1 dark blue: nothing draws it yet)
	move.l	#cell_list,cell_ptr
	move.l	#buffers,d0
	move.l	d0,-(sp)
	move.b	1(sp),$ffff8201.w
	move.b	2(sp),$ffff8203.w
	move.b	3(sp),$ffff820d.w
	addq.l	#4,sp
	rts

vbl_video:
	rts

render_frame:				; (z80_hook keeps the registers)
	move.l	cell_ptr,a0		; the listed cells: their flags cleared, the list emptied
	lea	cell_dirty,a1
.c:	cmp.l	#cell_list,a0
	beq.s	.e
	move.w	-(a0),d7
	clr.b	(a1,d7.w)
	bra.s	.c
.e:	move.l	a0,cell_ptr
	clr.b	tiles_all
	addq.w	#1,pic_count
	rts

	section bss,bss
	even
shown_pal:	ds.w	16
black_pal:	ds.w	16
	cnop	0,256
buffers:	ds.b	BUFSZ
	section text,code
