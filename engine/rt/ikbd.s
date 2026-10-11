; The IKBD byte stream for the ports' ACIA handlers: one byte per pass of the handler's loop, framed into keys and
; joystick packets.
;
; The keyboard sends key bytes ($01-$72 pressed, +$80 released) and packets: a header ($F6-$FF) and its data bytes
; (joystick $FE / $FF: 1, $FD: 2, relative mouse $F8-$FB: 2, time of day $FC: 6, absolute mouse $F7: 5, status $F6:
; 7).  A data byte read as a key is a key: the joystick's "up" byte ($01) is Esc, "down" ($02) is the key 1.  So:
;
; - every packet is framed by its length (the ports only ask for joystick packets, but any other is skipped whole);
; - an overrun (the ACIA's OVRN after a read: the byte after it was lost) drops the packet being read, and the next
;   byte too when it could be a joystick packet's data byte (bits 4-6 clear) whose header was the lost byte;
; - Esc quits only on its release directly after its press (no byte between): one stray $01 or $81 never quits.
;
; Usage, in the port's ACIA handler (registers d0-d2 free):
;
;   .again:
;	ikbd_byte		; to .done when the ACIA has no byte; joystick data: to .packet_byte (d0.b = 1:
;				; joystick 0, 2: joystick 1; d1 = data); a key: falls through (d1 = scancode without
;				; the release bit, d2 = the byte); everything else: back to .again
;   (the port's key handling, then bra .again)
;
; The port defines KEY_ESC ($01) and quit_flag, and places ikbd_vars in its bss.

IKBD_SKIP = $80				; ikbd_state: $80 + n = n more data bytes of a packet to skip

ikbd_byte macro
	move.b	$fffffc00.w,d0
	btst	#0,d0
	beq	.done

	moveq	#0,d1
	move.b	$fffffc02.w,d1
	btst	#5,$fffffc00.w		; overrun: the byte after this one was lost
	beq.s	.in_sync\@
	st	ikbd_lost		; (this one is still good; the next one tells where the stream is)
	bra.s	.read\@

.in_sync\@:
	tst.b	ikbd_lost
	beq.s	.read\@
	sf	ikbd_lost
	clr.b	ikbd_state		; the packet being read lost a byte, or the lost byte was a header
	sf	ikbd_esc
	cmp.b	#$f6,d1
	bhs.s	.read\@			; a header: in sync again
	move.b	d1,d0
	and.b	#$70,d0
	beq	.again			; maybe a joystick packet's data byte: dropped

.read\@:
	move.b	ikbd_state,d0
	beq.s	.first\@
	bpl	.packet_byte		; 1 / 2: the joystick packet's data byte (the port clears ikbd_state)
	subq.b	#1,d0			; a byte of a skipped packet
	cmp.b	#IKBD_SKIP,d0
	bne.s	.skip\@
	moveq	#0,d0
.skip\@:
	move.b	d0,ikbd_state
	bra	.again

.first\@:
	cmp.b	#$f6,d1
	blo.s	.key\@
	move.w	d1,d0
	sub.w	#$f6,d0
	move.b	.lengths\@(pc,d0.w),ikbd_state
	sf	ikbd_esc
	bra	.again

.lengths\@:
	dc.b	IKBD_SKIP+7,IKBD_SKIP+5,IKBD_SKIP+2,IKBD_SKIP+2,IKBD_SKIP+2,IKBD_SKIP+2,IKBD_SKIP+6,IKBD_SKIP+2
	dc.b	1,2			; $FE / $FF: joystick 0 / 1

.key\@:
	move.b	d1,d2
	and.b	#$7f,d1
	cmp.b	#KEY_ESC,d1
	beq.s	.esc\@
	sf	ikbd_esc
	bra.s	.out\@

.esc\@:
	tst.b	d2
	bmi.s	.esc_up\@
	st	ikbd_esc		; pressed: quits on its release, if nothing comes between
	bra	.again
.esc_up\@:
	tst.b	ikbd_esc
	beq	.again
	st	quit_flag
	bra	.again

.out\@:
	endm

ikbd_vars macro
ikbd_state:	ds.b	1		; 0: a key or a header next; 1 / 2: joystick 0 / 1 data; IKBD_SKIP + n
ikbd_lost:	ds.b	1		; an overrun: the next byte decides
ikbd_esc:	ds.b	1		; the last byte was Esc pressed
	endm
