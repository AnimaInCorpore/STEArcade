; STE enhanced joystick ports: two Jaguar pads / PowerPads (pad A = player 1, pad B = player 2).
;
; The pads are a 4 x 4 matrix each: a write to $FF9202 selects one row per pad (bits 0-3 pad A, 4-7 pad B, active
; low), $FF9202 bits 8-11 / 12-15 return pad A's / pad B's four row lines, $FF9200 bit 1 / bit 3 their fire line (and
; bit 0 / bit 2 Pause in row 0), all active low (Hatari's joy.c; stedaimakaimura's emulator.s reads pad A the same way):
;
;   row 0 ($FFEE): up, down, left, right    fire = A (and Pause)
;   row 1 ($FFDD): *, 7, 4, 1               fire = B
;   row 2 ($FFBB): 0, 8, 5, 2               fire = C
;   row 3 ($FF77): #, 9, 6, 3               fire = Option
;
; jagpad_poll (once a VBL) turns each pad into a button word (JP_* bit numbers below, active high) and ORs, for every
; button held, its long of the port's tables into jp_in (4 bytes, active high): jp_map_a (one long per JP_* button),
; then jp_map_b (pad B).  jagpad_maps builds them from the port's inputs, each a long whose bytes are the input bytes
; of the port's key_table (byte 0 = its first column): JP1_UP, JP1_DOWN, JP1_LEFT, JP1_RIGHT, JP1_B1, JP1_B2, JP1_B3
; (pad A: its A, B, C buttons), the same JP2_* (pad B), JP_START1, JP_START2, JP_COIN1, JP_COIN2.  Option is a coin
; (pad A coin 1, pad B coin 2), Pause a start (pad A start 1, pad B start 2), keypad 1 / 2 / 5 / 6 start 1 / start 2 /
; coin 1 / coin 2 as the keyboard's number keys; * and # held together on either pad set quit_flag (like Esc).
; The port merges jp_in where it merges its keyboard bits.
;
; jagpad_init (supervisor, interrupts may be on) probes the ports: on a plain ST $FF9202 is a bus error, and
; jagpad_poll then does nothing.  The Mega STE has the registers but not the ports ($FF9200 holds its DIP switches,
; the row lines are not pulled up: a tester's Mega STE read fire, Pause and Option held on both pads, so no coin or
; start ever came, tools/mstediag.s): its _MCH cookie ($00010010) leaves the pads off, and so does an idle reading
; (no row selected) with any line low: a pad button held while a game starts also does.  The SIM build leaves jagpad_init out (jp_present stays 0).
; The port places jagpad_text and jagpad_maps in its text, jagpad_vars in its bss; it defines quit_flag.

JP_UP = 0
JP_DOWN = 1
JP_LEFT = 2
JP_RIGHT = 3
JP_A = 4
JP_B = 5
JP_C = 6
JP_OPTION = 7
JP_PAUSE = 8
JP_1 = 9				; keypad 1, 2, 5, 6: start 1 / 2, coin 1 / 2 as the keyboard's number keys
JP_2 = 10
JP_5 = 11
JP_6 = 12
JP_STAR = 13
JP_HASH = 14
JP_BUTTONS = 15

; jp_bit src,bit,dst,dstbit: a low (pressed) source bit sets the destination bit
jp_bit	macro
	btst	#\2,\1
	bne.s	.n\@
	bset	#\4,\3
.n\@:
	endm

; jp_merge byte,dst,n: dst = an active-low input byte with jp_in's byte n merged (d0)
jp_merge macro
	move.b	jp_in+\3,d0
	not.b	d0
	and.b	\1,d0
	move.b	d0,\2
	endm

jagpad_text macro

jagpad_init:
	movem.l	d0/a0-a2,-(sp)
	sf	jp_present
	move.l	$5a0.w,d0		; the cookie jar
	beq.s	.probe\@
	move.l	d0,a0
.cookie\@:
	move.l	(a0)+,d0
	beq.s	.probe\@
	cmp.l	#'_MCH',d0
	beq.s	.mch\@
	addq.l	#4,a0
	bra.s	.cookie\@
.mch\@:	cmp.l	#$00010010,(a0)		; a Mega STE: no ports
	beq.s	.out\@
.probe\@:
	move.l	$8.w,a1
	move.l	sp,a2
	move.l	#.berr\@,$8.w
	move.w	#$ffff,$ffff9202.w	; (deselects every row)
	moveq	#$f,d0			; idle: no fire / Pause line low
	and.w	$ffff9200.w,d0
	cmp.w	#$f,d0
	bne.s	.berr\@
	move.w	$ffff9202.w,d0		; and no row line
	and.w	#$ff00,d0
	cmp.w	#$ff00,d0
	bne.s	.berr\@
	st	jp_present
.berr\@:
	move.l	a2,sp
	move.l	a1,$8.w
.out\@:
	movem.l	(sp)+,d0/a0-a2
	rts

jagpad_poll:
	tst.b	jp_present
	beq	.out\@
	movem.l	d0-d5/a0-a1,-(sp)
	moveq	#0,d2			; pad A buttons
	moveq	#0,d3			; pad B buttons
	lea	$ffff9202.w,a0

	move.w	#$ffee,(a0)		; row 0: directions, A, Pause
	move.w	-2(a0),d0
	move.w	(a0),d1
	move.w	d1,d4
	not.w	d4
	lsr.w	#8,d4
	moveq	#$f,d5
	and.w	d4,d5
	or.w	d5,d2			; up, down, left, right
	lsr.w	#4,d4
	or.w	d4,d3
	jp_bit	d0,1,d2,JP_A
	jp_bit	d0,0,d2,JP_PAUSE
	jp_bit	d0,3,d3,JP_A
	jp_bit	d0,2,d3,JP_PAUSE

	move.w	#$ffdd,(a0)		; row 1: *, 7, 4, 1, B
	move.w	-2(a0),d0
	move.w	(a0),d1
	jp_bit	d0,1,d2,JP_B
	jp_bit	d0,3,d3,JP_B
	jp_bit	d1,8,d2,JP_STAR
	jp_bit	d1,11,d2,JP_1
	jp_bit	d1,12,d3,JP_STAR
	jp_bit	d1,15,d3,JP_1

	move.w	#$ffbb,(a0)		; row 2: 0, 8, 5, 2, C
	move.w	-2(a0),d0
	move.w	(a0),d1
	jp_bit	d0,1,d2,JP_C
	jp_bit	d0,3,d3,JP_C
	jp_bit	d1,10,d2,JP_5
	jp_bit	d1,11,d2,JP_2
	jp_bit	d1,14,d3,JP_5
	jp_bit	d1,15,d3,JP_2

	move.w	#$ff77,(a0)		; row 3: #, 9, 6, 3, Option
	move.w	-2(a0),d0
	move.w	(a0),d1
	jp_bit	d0,1,d2,JP_OPTION
	jp_bit	d0,3,d3,JP_OPTION
	jp_bit	d1,8,d2,JP_HASH
	jp_bit	d1,10,d2,JP_6
	jp_bit	d1,12,d3,JP_HASH
	jp_bit	d1,14,d3,JP_6
	move.w	#$ffff,(a0)

	move.w	#(1<<JP_STAR)|(1<<JP_HASH),d0
	move.w	d2,d1
	and.w	d0,d1
	cmp.w	d0,d1
	beq.s	.quit\@
	move.w	d3,d1
	and.w	d0,d1
	cmp.w	d0,d1
	bne.s	.map\@
.quit\@:
	st	quit_flag

.map\@:
	moveq	#0,d0			; jp_in (4 bytes)
	lea	jp_map_a,a1
	bsr.s	.table\@
	lea	jp_map_b,a1
	move.w	d3,d2
	bsr.s	.table\@
	move.l	d0,jp_in
	movem.l	(sp)+,d0-d5/a0-a1
.out\@:
	rts

.table\@:
	moveq	#JP_BUTTONS-1,d5
.t\@:	lsr.w	#1,d2
	bcc.s	.u\@
	or.l	(a1),d0
.u\@:	addq	#4,a1
	dbf	d5,.t\@
	rts

	endm

jagpad_maps macro
	even
jp_map_a:
	dc.l	JP1_UP,JP1_DOWN,JP1_LEFT,JP1_RIGHT,JP1_B1,JP1_B2,JP1_B3,JP_COIN1,JP_START1
	dc.l	JP_START1,JP_START2,JP_COIN1,JP_COIN2,0,0
jp_map_b:
	dc.l	JP2_UP,JP2_DOWN,JP2_LEFT,JP2_RIGHT,JP2_B1,JP2_B2,JP2_B3,JP_COIN2,JP_START2
	dc.l	JP_START1,JP_START2,JP_COIN1,JP_COIN2,0,0
	endm

jagpad_vars macro
	even
jp_in:		ds.b	4		; the pads' input bits (the port's key_table layout), active high
jp_present:	ds.b	1
	even
	endm
