; Hand-written 68000 routines that replace Z80 code of the main program (gen.py NATIVES).  Register map: z80x.FAST
; (d0.b A, d1.w BC, d2.w DE, d3.w HL, d6.w flags: S 8 Z 4 C 1, H 32, N 64; the upper words of d1-d3 hold BC' DE' HL').

	section text,code

; $00DD  otir  (ld bc,$0D00 before: B = 13, C = port 0): the program of the Z80 DMA, the 13 bytes at HL.  The DMA's copy
; ($6900 -> $7000, $1A0 bytes) is dk3_dma, called by the store to $7E85: nothing to send.  Leaves what OTIR does: HL += B,
; B = 0, flags Z and N set, S and H clear, C kept.
nat_otir:
	moveq	#0,d5
	move.w	d1,d5
	lsr.w	#8,d5
	add.w	d5,d3
	and.w	#$00ff,d1
	and.w	#$0001,d6
	or.w	#$0044,d6
	jmp	Z00DF

; $0251  the sprite list copy (called from $023E only, once a frame): 33 entries of 16 bytes from $6400; an entry whose first
; byte is not 0 gives 4 bytes (+7, +5, +8, +9) at DE, else DE steps 4.  Leaves what the loop leaves: A = 0, A' = the last
; entry's temp (7, or 0 when it is empty), HL = $6610, DE = $69FC, BC = $0006 ($0010 when the last is empty), Z set; returns to $0241.
nat_sprcopy:
	lea	$6400(a6),a0
	lea	$6978(a6),a1
	moveq	#33-1,d7
.l:	tst.b	(a0)
	beq.s	.z
	move.b	7(a0),(a1)+
	move.b	5(a0),(a1)+
	move.b	8(a0),(a1)+
	move.b	9(a0),(a1)+
	lea	16(a0),a0
	dbf	d7,.l
	bra.s	.e
.z:	addq.l	#4,a1
	lea	16(a0),a0
	dbf	d7,.l
.e:	moveq	#7,d5			; the last entry: A' = 7 and BC = $0006 when it is used, else 0 and $0010
	move.w	#$0600,d1		; (BC is kept swapped: C in the high byte)
	tst.b	-16(a0)
	bne.s	.u
	moveq	#0,d5
	move.w	#$1000,d1
.u:	swap	d0
	move.b	d5,d0
	swap	d0
	clr.b	d0
	move.w	#$6610,d3
	move.w	#$69FC,d2
	and.w	#$FFF0,d6
	or.w	#$0004,d6
	addq.l	#2,a5			; (the return address)
	jmp	Z0241

; $0114  the first timer loop (24 objects of $20 bytes from $6100: an object whose first byte is not 0 counts its byte 3 down
; to 0), then on at $012E.  Leaves HL = $6400, DE = $20, B = 0, A = the last object's temp (0, or its old byte 3).
nat_timers1:
	lea	$6100(a6),a0
	moveq	#24-1,d7
.l:	moveq	#0,d5
	tst.b	(a0)
	beq.s	.n
	move.b	3(a0),d5
	beq.s	.n
	subq.b	#1,3(a0)
.n:	lea	$20(a0),a0
	dbf	d7,.l
	move.b	d5,d0
	move.w	#$6400,d3
	move.w	#$0020,d2
	clr.b	d1
	jmp	Z012E

; $0138  the second timer loop (32 objects of $10 bytes from $6400: byte 2 counts down to 0 when byte 0 is not 0), then the
; translated `ret` at $0151.  Leaves HL = $6600, DE = $10, B = 0, A = 0 or the last object's old byte 2, S and Z as the last
; `cp a,(hl)` / `or a,a` set them, C clear.
nat_timers2:
	lea	$6400(a6),a0
	moveq	#32-1,d7
.l:	moveq	#0,d5
	tst.b	(a0)
	beq.s	.n
	move.b	2(a0),d5
	beq.s	.n
	subq.b	#1,2(a0)
.n:	lea	$10(a0),a0
	dbf	d7,.l
	move.b	d5,d0
	move.w	#$6600,d3
	move.w	#$0010,d2
	clr.b	d1
	and.w	#$FFF0,d6
	tst.b	-16(a0)
	beq.s	.zero
	tst.b	d5
	bne.s	.nz
.zero:	or.w	#$0004,d6		; (Z)
	jmp	Z0151
.nz:	bpl.s	.out
	or.w	#$0008,d6		; (S)
.out:	jmp	Z0151

; `ld a,r` (the refresh register; the game's random numbers): a pseudo random byte, a 16-bit shift register.  The
; reference (tools/machine.py DK3.rnd) has the same.
z80_rnd:
	move.w	rnd_state,d7
	lsr.w	#1,d7
	bcc.s	.no
	eor.w	#$b400,d7
.no:	move.w	d7,rnd_state
	move.b	d7,d0
	rts

; the sprite copy: $6900 -> $7000, $1A0 bytes (the Z80 DMA); a6 = the Z80 block
dk3_dma:
	movem.l	d1-d4/d6/a0-a2,-(sp)
	lea	$6900(a6),a0
	lea	$7000(a6),a1
DMA_OFF	set	0
	rept	$1A0/32
	movem.l	(a0)+,d1-d7/a2
	movem.l	d1-d7/a2,DMA_OFF(a1)
DMA_OFF	set	DMA_OFF+32
	endr
	movem.l	(sp)+,d1-d4/d6/a0-a2
	rts

	section data,data
rnd_state:	dc.w	$ace1
	section text,code
