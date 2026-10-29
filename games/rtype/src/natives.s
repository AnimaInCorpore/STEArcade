; R-Type: hand-written replacements for translated V30 code (tools/gen.py NATIVES: the translated label jumps here,
; the instruction's own translation follows under <label>_t).
;
; FADE_SNAP (the STE program's default; the SIM build the lock-step test drives keeps the arcade's fade unless it is
; defined): the palette fade's inner loop (0040:5384 and 0040:5436, the same loop over a row of 16 pens x 3 channels in
; the work RAM's palette copy, DS0:[BW], toward the target bytes DS1:[IX]) sets every channel to its target at once
; instead of a step of 1 where the remaining difference reaches the fade's counter [BP+0Ah].  The fade's own bookkeeping
; runs on unchanged ([BP+2h] counts the channels changed, the counter still counts down: the game sees the fade end at
; the same frame), so only the colours between the start and the end are left out (the user's choice, 2026-10-29).
; The registers and the stack below SP are left as the loop leaves them (CW 0, BW + 32, IX + 48, AW the last channel's
; target - value, the last pushes BW + 30 and CW 1); the flags are dead after the loop (the translation does not keep
; them either).

	section text,code

    ifd FADE_SNAP
FADE_ROW macro
	movem.l	d2/d5,-(sp)
	lea	(a3,d3.l),a0		; DS0:[BW]: pen 0's red word (green +$200, blue +$400)
	moveq	#0,d2			; channels changed
	moveq	#16-1,d5
.pen\@:
	moveq	#1,d7
	eor.w	d4,d7
	moveq	#0,d0
	move.b	(a2,d7.l),d0		; red's target
	sub.w	(a0),d0
	beq.s	.g\@
	add.w	d0,(a0)
	addq.w	#1,d2
.g\@:	addq.w	#1,d4
	moveq	#1,d7
	eor.w	d4,d7
	moveq	#0,d0
	move.b	(a2,d7.l),d0
	sub.w	$200(a0),d0
	beq.s	.b\@
	add.w	d0,$200(a0)
	addq.w	#1,d2
.b\@:	addq.w	#1,d4
	moveq	#1,d7
	eor.w	d4,d7
	moveq	#0,d0
	move.b	(a2,d7.l),d0
	sub.w	$400(a0),d0
	beq.s	.n\@
	add.w	d0,$400(a0)
	addq.w	#1,d2
.n\@:	addq.w	#1,d4
	addq.l	#2,a0
	dbf	d5,.pen\@
	add.w	d2,2(a4,d6.l)		; [BP+2h]
	add.w	#32,d3
	moveq	#0,d1
	move.w	d3,d7
	subq.w	#2,d7
	move.w	d7,-2(a5)		; (the loop's last pushes)
	move.w	#1,-4(a5)
	movem.l	(sp)+,d2/d5
	jmp	\1
	endm

nat_fade_a:
	FADE_ROW	R057B4
nat_fade_b:
	FADE_ROW	R05866
    else
nat_fade_a:
	jmp	R05784_t
nat_fade_b:
	jmp	R05836_t
    endc
