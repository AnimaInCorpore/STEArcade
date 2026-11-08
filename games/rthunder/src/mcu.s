; The HD63701's mailbox as a native model (tools/machine.py: the firmware cus60-60a1.mcu + rt3_4.6b is the reference):
; mcu_init once, mcu_frame at every arcade frame's vertical blank (before port_frame): the sprite list latch and the MCU's
; frame (the inputs into CUS30 RAM).

	section text,code
mcu_init:
	rts

; the vertical blank's work: the sprite list buffered when the program wrote the latch ($7F2 of the sprite RAM): the
; displayed attributes (bytes 10-15 of each 16 byte entry) are bytes 4-9 (screen_vblank -> copy_sprites)
mcu_frame:
	tst.b	sprite_latch
	beq.s	.nl
	clr.b	sprite_latch
	lea	shared+$1800,a0
	move.w	#$80-1,d0
.l:	move.l	4(a0),10(a0)
	move.w	8(a0),14(a0)
	lea	16(a0),a0
	dbf	d0,.l
.nl:	rts
