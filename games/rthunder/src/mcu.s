; The HD63701's mailbox as a native model (tools/mcu_model.py: the rules, checked against the firmware cus60-60a1.mcu +
; rt3_4.6b that tools/machine.py runs): mcu_init once, mcu_frame at every arcade frame's vertical blank (before port_frame):
; the sprite list latch and the MCU's frame (the inputs, the credits, the sound command's acknowledge in CUS30 RAM).

	section text,code
mcu_init:
	lea	mcu_hist,a0
	moveq	#16,d0
.h:	clr.b	(a0)+
	dbf	d0,.h
	clr.w	snd_head
	clr.w	snd_timer
	rts

; the vertical blank's work: the sprite list buffered when the program wrote the latch ($7F2 of the sprite RAM): the
; displayed attributes (bytes 10-15 of each 16 byte entry) are bytes 4-9 (screen_vblank -> copy_sprites)
mcu_frame:
	movem.l	d0-d7/a0-a3,-(sp)
	tst.b	sprite_latch
	beq.s	.nl
	clr.b	sprite_latch
	lea	shared+$1800,a0
	move.w	#$80-1,d0
.l:	move.l	4(a0),10(a0)
	move.w	8(a0),14(a0)
	lea	16(a0),a0
	dbf	d0,.l
.nl:	lea	cus30,a0
	lea	mcu_tab,a1
	lea	mcu_hist,a2
	moveq	#0,d6			; a coin counted
	moveq	#16,d7
.e:	moveq	#0,d1
	move.b	(a1)+,d1		; the port
	lea	io_in0,a3
	add.w	d1,a3
	move.b	(a3),d2
	moveq	#0,d1
	move.b	(a1)+,d1		; the bit
	moveq	#0,d3
	btst	d1,d2
	seq	d3			; pressed: the bit is low
	and.b	#1,d3
	move.w	(a1)+,d4		; the pulse's offset (the level is the next byte)
	move.b	(a1)+,d5		; 0: input, 1: coin
	addq.l	#1,a1
	moveq	#0,d0
	move.b	(a2),d0			; the last four frames, bit 0 = the previous frame
	tst.b	d5
	bne.s	.coin
	move.b	d0,d1
	and.b	#1,d1
	move.b	d1,1(a0,d4.w)		; the level: the previous frame's
	moveq	#0,d1
	move.b	d0,d2
	and.b	#7,d2
	cmp.b	#3,d2
	bne.s	.np
	moveq	#1,d1
.np:	move.b	d1,(a0,d4.w)		; the pulse: pressed two frames running, not three ago
	bra.s	.upd
.coin:	move.b	d0,d1
	and.b	#1,d1
	eor.b	#1,d1
	move.b	d1,1(a0,d4.w)		; a coin line is inverted
	moveq	#0,d1
	move.b	d0,d2
	and.b	#$0E,d2
	cmp.b	#$0C,d2
	bne.s	.nc
	moveq	#1,d1			; (low three and four frames ago, high two: at least two frames low)
	moveq	#1,d6
.nc:	move.b	d1,(a0,d4.w)
.upd:	add.b	d0,d0
	or.b	d3,d0
	and.b	#15,d0
	move.b	d0,(a2)+
	dbf	d7,.e
	; the credits
	moveq	#0,d0
	move.b	$1A5(a0),d0
	move.b	d0,$1A6(a0)
	move.w	d0,d1
	tst.b	d6
	beq.s	.nev
	cmp.b	#99,d1
	bhs.s	.max
	addq.b	#1,d1
.max:	move.b	d1,$1A5(a0)
	addq.b	#1,$18B(a0)
.nev:	and.l	#$FF,d1
	divu	#10,d1
	move.b	d1,$189(a0)
	swap	d1
	move.b	d1,$18A(a0)
	; the starts
	tst.b	$18C(a0)
	bne.s	.sound
	tst.b	$262(a0)
	beq.s	.try2
	tst.b	$1A5(a0)
	beq.s	.try2
	subq.b	#1,$1A5(a0)
	move.b	#1,$18C(a0)
	move.b	#1,$1A7(a0)
	bra.s	.sound
.try2:	tst.b	$260(a0)
	beq.s	.sound
	cmp.b	#2,$1A5(a0)
	blo.s	.sound
	subq.b	#2,$1A5(a0)
	move.b	#1,$18C(a0)
	move.b	#2,$1A7(a0)
.sound:	move.w	snd_timer,d1		; a jingle ends: the firmware clears the command byte
	beq.s	.nt
	subq.w	#1,d1
	move.w	d1,snd_timer
	bne.s	.nt
	cmp.b	#$FF,$380(a0)
	bne.s	.nt
	clr.b	$380(a0)
.nt:	move.b	$380(a0),d0		; a sound command: acknowledged ($FF); the notes themselves are recorded
	beq.s	.out
	cmp.b	#$FF,d0
	beq.s	.out
	move.b	#$FF,$380(a0)
	moveq	#0,d1
	move.b	d0,d1
	add.w	d1,d1
	lea	snd_dur,a2
	move.w	(a2,d1.w),snd_timer
	move.w	snd_head,d1
	lea	snd_ring,a1
	move.b	d0,(a1,d1.w)
	addq.b	#1,d1
	move.w	d1,snd_head
.out:	movem.l	(sp)+,d0-d7/a0-a3
	rts

; port, bit, the pulse's offset, kind (the level: the next byte)
mcu_tab:
	dc.b	0,1
	dc.w	$276
	dc.b	0,0
	dc.b	0,2
	dc.w	$27C
	dc.b	0,0
	dc.b	0,3
	dc.w	$270
	dc.b	0,0
	dc.b	0,4
	dc.w	$272
	dc.b	0,0
	dc.b	0,6
	dc.w	$262
	dc.b	0,0
	dc.b	1,1
	dc.w	$26A
	dc.b	0,0
	dc.b	1,2
	dc.w	$27A
	dc.b	0,0
	dc.b	1,3
	dc.w	$26E
	dc.b	0,0
	dc.b	1,6
	dc.w	$260
	dc.b	0,0
	dc.b	1,7
	dc.w	$25C
	dc.b	0,0
	dc.b	2,3
	dc.w	$278
	dc.b	0,0
	dc.b	2,4
	dc.w	$280
	dc.b	0,0
	dc.b	2,5
	dc.w	$27E
	dc.b	0,0
	dc.b	2,6
	dc.w	$26C
	dc.b	0,0
	dc.b	2,7
	dc.w	$274
	dc.b	0,0
	dc.b	0,5
	dc.w	$266
	dc.b	1,0
	dc.b	1,5
	dc.w	$264
	dc.b	1,0

	section data,data
	even
snd_dur:	incbin	"ren_snddur.bin"

	section bss,bss
io_in0:		ds.b	1		; the inputs, active low (IN0, IN1, IN2): the keyboard, sticks and pads
io_in1:		ds.b	1
io_in2:		ds.b	1
mcu_hist:	ds.b	17
	even
snd_head:	ds.w	1
snd_timer:	ds.w	1		; frames until the command byte is cleared (0: none)
snd_ring:	ds.b	256		; the sound commands the main CPU sent (the last 256)
