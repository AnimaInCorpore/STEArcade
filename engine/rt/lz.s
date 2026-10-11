; ------------------------------------------------------------------------------
; lz_unpack: engine/lz.py's byte-aligned LZ77.  a0 = the packed data, a1 = the output.  Uses d0-d1 / a0-a2.
;   $00-$7F: n + 1 literal bytes follow;  $80-$FE, hi, lo: (c & $7F) + 3 bytes from hi:lo + 1 bytes back;  $FF: end
; ------------------------------------------------------------------------------

lz_unpack:
	moveq	#0,d0
.token:
	move.b	(a0)+,d0
	bmi.s	.match
.lit:	move.b	(a0)+,(a1)+		; n + 1 literals
	dbf	d0,.lit
	moveq	#0,d0
	bra.s	.token
.match:
	cmp.b	#$FF,d0
	beq.s	.end
	and.w	#$7F,d0
	addq.w	#2,d0			; (dbf: length - 1)
	moveq	#0,d1
	move.b	(a0)+,d1
	lsl.w	#8,d1
	move.b	(a0)+,d1
	addq.l	#1,d1
	move.l	a1,a2
	sub.l	d1,a2
.copy:	move.b	(a2)+,(a1)+
	dbf	d0,.copy
	moveq	#0,d0
	bra.s	.token
.end:	rts
