; Hand-written 68000 routines that replace Z80 code of the main program (gen.py NATIVES).  Register map: z80x.FAST
; (d0.b A, d1.w BC, d2.w DE, d3.w HL, d6.w flags: S 8 Z 4 C 1, H 32, N 64; the upper words of d1-d3 hold BC' DE' HL').

; $00CD  otir  (ld bc,$0D00 before: B = 13, C = port 0): the program of the Z80 DMA, the 13 bytes at HL.  The DMA's copy
; ($6900 -> $7000, $180 bytes) is z80_dma, called by the store to $7E85: nothing to send.  Leaves what OTIR does: HL += B,
; B = 0, flags Z and N set, S and H clear, C kept.
nat_otir:
	moveq	#0,d5
	move.w	d1,d5
	lsr.w	#8,d5
	add.w	d5,d3
	and.w	#$00ff,d1
	and.w	#$0001,d6
	or.w	#$0044,d6
	jmp	Z00CF

; `ld a,r` (the refresh register; the game's random numbers): a pseudo random byte, a 16-bit shift register.  The
; reference (tools/machine.py Mario.rnd) has the same.
z80_rnd:
	move.w	rnd_state,d7
	lsr.w	#1,d7
	bcc.s	.no
	eor.w	#$b400,d7
.no:	move.w	d7,rnd_state
	move.b	d7,d0
	rts

	section data,data
rnd_state:	dc.w	$ace1
	section text,code
