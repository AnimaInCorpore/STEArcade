; Isolated experiment: partial full-refreshes, including scrolling BG buffers.
; A buffer initialized this way keeps a valid rectangle. Before reusing it, copy
; newly exposed strips from the current clean buffer, then run ordinary sync.
; All coordinates below are physical 16-pixel groups / physical buffer lines.

	section text,code
st_wi_incoming:
	move.l d0,-(sp)
	move.w st_draw,d0
	btst d0,st_wi_active
	beq .out
	movem.l d1-d7/a0-a6,-(sp)
	bsr st_wi_geometry
	cmp.w (a4),d0
	bne.s .changed
	cmp.w 2(a4),d1
	bne.s .changed
	cmp.w 4(a4),d2
	beq .done
.changed:
	move.w (a4),d4
	cmp.w d0,d4
	bge.s .left
	move.w d0,d4
.left:	move.w (a4),d5
	add.w 4(a4),d5
	move.w d0,d3
	add.w d2,d3
	cmp.w d3,d5
	ble.s .right
	move.w d3,d5
.right:	move.w 2(a4),d6
	cmp.w d1,d6
	bge.s .top
	move.w d1,d6
.top:	move.w 2(a4),d7
	add.w #256,d7
	move.w d1,d3
	add.w #256,d3
	cmp.w d3,d7
	ble.s .bottom
	move.w d3,d7
.bottom:
	cmp.w d4,d5
	ble.s .whole
	cmp.w d6,d7
	ble.s .whole
	; Top and bottom strips cover the entire new width.
	move.w d6,d3
	sub.w d1,d3
	bsr st_wi_rect
	move.w st_wi_y,d3
	add.w #256,d3
	sub.w d7,d3
	move.w d7,d1
	bsr st_wi_rect
	; Left and right strips cover only the vertical intersection.
	move.w d6,d1
	move.w d4,d2
	sub.w d0,d2
	move.w d7,d3
	sub.w d6,d3
	bsr st_wi_rect
	move.w st_wi_x,d2
	add.w st_wi_w,d2
	sub.w d5,d2
	move.w d5,d0
	bsr st_wi_rect
	bra.s .remember
.whole:
	bsr st_wi_current
.remember:
	bsr st_wi_remember
.done:	movem.l (sp)+,d1-d7/a0-a6
.out:	move.l (sp)+,d0
	rts

st_wi_full:
	movem.l d0-d7/a0-a6,-(sp)
	bsr st_wi_geometry
	bsr st_wi_current
	bsr st_wi_remember
	move.w st_draw,d0
	bset d0,st_wi_active
	movem.l (sp)+,d0-d7/a0-a6
	rts

st_wi_forget:
	move.l d0,-(sp)
	move.w st_draw,d0
	bclr d0,st_wi_active
	move.l (sp)+,d0
	rts

st_wi_geometry:
	move.w st_draw,d0
	lsl.w #3,d0
	lea st_wi_meta,a4
	add.w d0,a4
	move.w st_W,d0
	lsr.w #4,d0
	move.l st_dorg,d1
	sub.l st_dbuf,d1
	lsr.l #8,d1
	lsr.l #1,d1
	add.w #64,d1
	moveq #20,d2
	moveq #15,d3
	and.w st_W,d3
	beq.s .aligned
	addq.w #1,d2
.aligned:
	move.w d0,st_wi_x
	move.w d1,st_wi_y
	move.w d2,st_wi_w
	rts

st_wi_remember:
	move.w st_wi_x,(a4)
	move.w st_wi_y,2(a4)
	move.w st_wi_w,4(a4)
	rts

st_wi_current:
	move.w st_wi_x,d0
	move.w st_wi_y,d1
	move.w st_wi_w,d2
	move.w #256,d3
	bra st_wi_rect

; d0 x groups, d1 y lines, d2 width groups, d3 height; preserves all registers.
st_wi_rect:
	tst.w d2
	ble .out
	tst.w d3
	ble .out
	movem.l d0-d7/a0-a3,-(sp)
	move.w d2,d6
	move.w d3,d7
	moveq #0,d4
	move.w d1,d4
	lsl.l #8,d4
	add.l d4,d4
	lsl.w #3,d0
	ext.l d0
	add.l d0,d4
	lea (a5,d4.l),a0
	lea (a6,d4.l),a1
.strip:
	moveq #8,d5
	cmp.w d5,d6
	bge.s .size
	move.w d6,d5
.size:	move.w d5,d0
	lsl.w #2,d0
	lsl.w #3,d5
	move.w d7,d1
	moveq #-1,d2
	moveq #-1,d3
	moveq #-1,d4
	bsr st_copy
	add.w d5,a0
	add.w d5,a1
	lsr.w #2,d0
	sub.w d0,d6
	bgt.s .strip
	movem.l (sp)+,d0-d7/a0-a3
.out:	rts

	section bss,bss
st_wi_active: ds.b 1
st_wi_seen: ds.b 1
	even
st_wi_x: ds.w 1
st_wi_y: ds.w 1
st_wi_w: ds.w 1
st_wi_meta: ds.w 3*4
