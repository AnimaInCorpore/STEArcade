; Pen masks from bit planes: a port that bakes STE planes from per-pen masks (an STE plane is the OR of the masks of
; the pens whose colour has that bit set) keeps its graphics as the arcade's bit planes instead, a word a plane a row,
; and makes the row's masks when it bakes: 16 pens take 4 words a row instead of 16 (1942's tiles: 96 KB instead of
; 256 KB).  Commando goes further: a row routine per colour, generated from the colour map (its assets.bake_rows).
;
; pm_expand: a0 = the row's planes (plane 0 first), d0.w = how many (2-4)  ->  pm_masks: 1 << d0 words, pen p's mask
;            the pixels whose value is p (pen 0's: of inverted planes only, so set wherever the row has no pixel:
;            narrower graphics clear those bits themselves); a0 past the planes.  d0 / d1 / d3-d7 changed.
;            Planes 0 and 1 give the four masks A0-A3 (registers), the others B (none, or 2 / 4 masks: one at a time);
;            pen a + 4b = A[a] & B[b]: a 16-pen row ~420 cycles, 8 pens ~250, 4 pens ~130.
; The port places pm_text in its text and pm_vars in its bss.

pm_text macro
pm_expand:
	move.l	a6,-(sp)
	lea	pm_masks,a6
	move.w	d0,d1
	move.w	(a0)+,d0		; p0
	move.w	d0,d5
	move.w	d0,d7
	not.w	d0
	move.w	d0,d4
	move.w	d0,d6
	move.w	(a0)+,d0		; p1
	and.w	d0,d6			; A2 = ~p0 & p1
	and.w	d0,d7			; A3 = p0 & p1
	not.w	d0
	and.w	d0,d4			; A0 = ~p0 & ~p1
	and.w	d0,d5			; A1 = p0 & ~p1
	subq.w	#3,d1
	bmi.s	.two\@
	beq.s	.three\@
	move.l	d2,-(sp)		; 4 planes: B from p2, p3
	move.w	(a0)+,d2
	move.w	(a0)+,d3
	move.w	d2,d0
	or.w	d3,d0
	not.w	d0			; ~p2 & ~p3
	bsr.s	.four\@
	move.w	d3,d0
	not.w	d0
	and.w	d2,d0			; p2 & ~p3
	bsr.s	.four\@
	move.w	d2,d0
	not.w	d0
	and.w	d3,d0			; ~p2 & p3
	bsr.s	.four\@
	move.w	d2,d0
	and.w	d3,d0			; p2 & p3
	bsr.s	.four\@
	move.l	(sp)+,d2
	move.l	(sp)+,a6
	rts
.three\@:
	move.w	(a0)+,d0		; p2
	not.w	d0
	bsr.s	.four\@			; ~p2
	not.w	d0
	bsr.s	.four\@			; p2
	move.l	(sp)+,a6
	rts
.two\@:
	movem.w	d4-d7,(a6)
	move.l	(sp)+,a6
	rts
.four\@:				; A[0..3] & d0 -> 4 masks
	move.w	d4,d1
	and.w	d0,d1
	move.w	d1,(a6)+
	move.w	d5,d1
	and.w	d0,d1
	move.w	d1,(a6)+
	move.w	d6,d1
	and.w	d0,d1
	move.w	d1,(a6)+
	move.w	d7,d1
	and.w	d0,d1
	move.w	d1,(a6)+
	rts
	endm

pm_vars macro
pm_masks:	ds.w	16
	endm
