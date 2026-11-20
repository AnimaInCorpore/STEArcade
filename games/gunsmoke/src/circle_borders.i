; Fixed CIRCLE settings. Preload counts before synchronization so the timed
; instructions from STOP / the Timer B poll through both sync writes match CIRCLE.
bd_circle_top macro
	moveq #0,d3
	lea .wait(pc),a0
	move.l (a0),d0
	move.l 4(a0),d0
	move.l 8(a0),d0
	move.l 12(a0),d0
	move.l 16(a0),d0
	move.l 20(a0),d0
	move.l 24(a0),d0
	move.l 28(a0),d0
	move.l 32(a0),d0
	moveq #78,d2
	moveq #8,d0
.wait:
	stop #$2100
	move #$2700,sr
	clr.b $fffffa19.w
.delay:
	dbf d2,.delay
	move.b d3,$ffff820a.w
	nop
	move.w d0,d2
.pulse:
	dbf d2,.pulse
	move.b #2,$ffff820a.w
	rts
	endm

bd_circle_low macro
	movem.l d3-d5/a1,-(sp)
	moveq #0,d3
	moveq #101,d4
	moveq #17,d5
	; Synchronize one DE falling edge earlier, then wait one cached scanline.
	; DBF #101 = 101 taken * 10 + final 14 = 1024 CPU cycles (512 video).
	addq.b #1,d0
	lea .circle_delay(pc),a1
	move.l (a1),d2
	move.l 4(a1),d2
	move.l 8(a1),d2
	move.l 12(a1),d2
	move.l 16(a1),d2
	move.l 20(a1),d2
	bd_poll
.circle_delay:
	dbf d4,.circle_delay
	move.b d3,$ffff820a.w
	nop
	move.w d5,d2
.circle_width:
	dbf d2,.circle_width
	move.b #2,$ffff820a.w
	movem.l (sp)+,d3-d5/a1
	endm
