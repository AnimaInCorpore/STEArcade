; ------------------------------------------------------------------------------
; The MCU's VBL interrupt ($F046-$F091) in 68000 code: what the 6801U4 firmware does, on the shared RAM directly.
;
; The firmware reaches the Z80 side only through its two bus routines ($F1BF read, $F1DB write: the address on
; P2 / P4, the data on P3, the clock on P2 bit 4, the direction on P1 bit 7), ~56 of them a game frame, each a
; dozen port writes the translation emulates (mcu_bus_read / mcu_bus_write, ~340 cycles a call with the call).
; Here a bus read is a move from the shared RAM ($0C00-$0FFF: G_MCRAM) or the DIP switches / inputs ($0000-$0003:
; dsw0, dsw1, in1, in2), a write a move into it.  What the ports keep afterwards is set once at the end: the handler
; always ends with the read of $0F96 ($F07F), so P1 bit 7 = 1 (read), P2 = $1F, P3 DDR = 0, P4 = $96, ($4A) = $0F96,
; p3_in = the byte read there; P3's data latch keeps the last byte written.  P1 bit 7 is 1 at every point the
; firmware reads P1 itself (a bus read came before each), so its latch is kept with bit 7 set.  The rest of the
; MCU's RAM ($40-$63) is updated as the firmware does it.
;
; Not reproduced: the psha of the three counter checks ($F2D2, $F372, $F41A: a copy that does not match the Z80's
; value; on the board the rts that follows returns into nothing) pushes one byte on the MCU's stack in the
; translation too and nothing else (m6801x: jsr / rts on the 68000 stack); the delay loop of $F089 (the translation
; skips it too).  The ports' directions are the init's (P1 $F0, P2 and P4 $FF), as the translation's fast paths
; assume; otherwise the translation runs.  -D MCU_XLATE: the translation always.
;
; In: a6 = mcu_mem (mcu_irq).  Registers: a1 = G_MCRAM, a4 = G_MCRAM - $C00 (a bus address in d2 as an index),
; d5 = the P1 latch, d7 = IN0 (read once: the inputs of this run), d3 = the last byte written (P3's latch),
; d0 = A, d1 = B, d2 / a0 / a2 scratch.
; ------------------------------------------------------------------------------

; a bus read / write at a constant address of the shared RAM (B = the byte)
mrd	macro
	move.b	\1-$C00(a1),d1
	endm
mwr	macro
	move.b	d1,\1-$C00(a1)
	move.b	d1,d3
	endm
; at the address in d2 (+ \1)
mrdx	macro
	move.b	\1(a4,d2.w),d1
	endm
mwrx	macro
	move.b	d1,\1(a4,d2.w)
	move.b	d1,d3
	endm
; lda $02: P1 as the pins show (the latch where output, IN0 where input: DDR $F0)
mp1rd	macro
	move.b	d5,\1
	and.b	#$F0,\1
	or.b	d7,\1
	endm
; sta $02 (d0): bit 6 high -> low raises the main CPU's interrupt (mcu_wr_p1)
mp1wr	macro
	btst	#6,d5
	beq.s	.n\@
	btst	#6,d0
	bne.s	.n\@
	st	main_irq
.n\@:	move.b	d0,d5
	endm

; $F16F, three times: ($40 + 2k) = the input bit (in bit 7), ($41 + 2k) = 1 if it was 0 before + 2 if it is 1 now;
; ($46) = the byte shifted left
mn_edge	macro
	move.b	d0,d1			; ($46) = A, then asl $0046
	add.b	d1,d1
	move.b	d1,$46(a6)
	move.b	(a0),d1
	move.b	d0,(a0)+
	moveq	#0,d2
	tst.b	d1
	bmi.s	.a\@
	moveq	#1,d2
.a\@:	tst.b	d0
	bpl.s	.b\@
	addq.b	#2,d2
.b\@:	move.b	d2,(a0)+
	add.b	d0,d0
	endm

; a coin slot ($F0B3 / $F0F3): \1 its edge byte, \2 the shift of DSW0 to its coinage, \3 its count
mn_coin	macro
	tst.b	\1(a6)
	bne.s	.x\@
	moveq	#0,d1
	move.b	$4E(a6),d1
	lsr.b	#\2,d1
	and.w	#6,d1
	lea	mcu_mem+$F187,a0	; (coins, credits)
	add.w	d1,a0
	cmp.b	#1,(a0)
	beq.s	.c\@
	addq.b	#1,\3(a6)
	move.b	(a0),d0
	cmp.b	\3(a6),d0
	bne.s	.x\@
	clr.b	\3(a6)
.c\@:	move.b	1(a0),d0
	mrd	$0C1E			; the credits
	add.b	d0,d1
	mwr	$0C1E
	moveq	#1,d1
	mwr	$0F99
.x\@:
	endm

; $F2A7 / $F347: a counter the Z80 asks to change (\1 = 1: from DSW1 bits 4-5 by the table at $F343, 2: +1 up to 10,
; 4: -1, 8: 10; then \1 = 0), its value at \2 and a copy at (\3); without a request and ($0F95) = $42 the firmware
; compares the two (the psha of a mismatch: see the header)
mn_counter macro
	mrd	\1
	cmp.b	#1,d1
	beq.s	.i1\@
	cmp.b	#2,d1
	beq.s	.i2\@
	cmp.b	#4,d1
	beq.s	.i4\@
	cmp.b	#8,d1
	beq.s	.i8\@
	mrd	$0F95
	cmp.b	#$42,d1
	bne.s	.x\@
	mrd	\2
	bra.s	.x\@
.i1\@:	move.b	dsw0+1,d1
	lsr.b	#4,d1
	and.w	#3,d1
	lea	mcu_mem+$F343,a0
	move.b	(a0,d1.w),d1
	bra.s	.st\@
.i2\@:	mrd	\2
	cmp.b	#$0A,d1
	beq.s	.cl\@
	addq.b	#1,d1
	bra.s	.st\@
.i4\@:	mrd	\2
	subq.b	#1,d1
	bra.s	.st\@
.i8\@:	moveq	#$0A,d1
.st\@:	move.b	d1,\3(a6)
	mwr	\2
.cl\@:	moveq	#0,d1
	mwr	\1
.x\@:
	endm

; the distance of a coordinate (A = the reference, B = the object's): A = |A - B|, B = $80 if equal, 0 if the object
; is not above, 1 if it is (sba / nega)
mn_dist	macro
	sub.b	d1,d0
	beq.s	.e\@
	bcc.s	.g\@
	moveq	#1,d1
	neg.b	d0
	bra.s	.d\@
.g\@:	moveq	#0,d1
	bra.s	.d\@
.e\@:	move.b	#$80,d1
.d\@:
	endm

; $F48F / $F585: (\1) bit 0: the position (\2, \3) against the 7 objects at $0C01 (4 bytes: active bit 0, x, y):
; for each active one the side and distance of x and y into $0C27 + 8n (+\4, +\5, +\6, +\7); the first one within 8 in
; both (that was not before one within 8 in x only: $5C) -> \8 = 1, \9 = its number (and (\1) bit 0 again)
mn_scan	macro
	mrd	\1
	btst	#0,d1
	beq	.x\@
	clr.b	$57(a6)
	mrd	\2
	move.b	d1,$55(a6)
	mrd	\3
	move.b	d1,$56(a6)
	move.w	#$0C01,$58(a6)
	move.w	#$0C27,$5A(a6)
	clr.b	$5C(a6)
.l\@:	move.w	$58(a6),d2
	mrdx	0
	btst	#0,d1
	beq.s	.nx\@
	mrdx	1
	move.b	$55(a6),d0
	mn_dist
	move.w	$5A(a6),d2
	mwrx	\4
	move.b	d0,d1
	mwrx	\5
	cmp.b	#8,d0
	bcc.s	.y\@
	addq.b	#1,$5C(a6)
.y\@:	move.w	$58(a6),d2
	mrdx	2
	move.b	$56(a6),d0
	mn_dist
	move.w	$5A(a6),d2
	mwrx	\6
	move.b	d0,d1
	mwrx	\7
	cmp.b	#8,d0
	bcs.s	.h\@
.nx\@:	addq.w	#4,$58(a6)
	addq.w	#8,$5A(a6)
	addq.b	#1,$57(a6)
	cmp.b	#7,$57(a6)
	bne	.l\@
	bra.s	.x\@
.h\@:	tst.b	$5C(a6)
	beq.s	.x\@
	mrd	\1
	btst	#0,d1
	beq.s	.x\@
	moveq	#1,d1
	mwr	\8
	move.b	$57(a6),d1
	mwr	\9
.x\@:
	endm

; $F67F / $F6CB / $F6F1: the next byte of sequence (\1) (a table of pointers at $F717; $FF: from its start) -> \3,
; the position in (\2)
mn_seq	macro
.a\@:	mrd	\1
	moveq	#0,d0
	move.b	d1,d0
	move.l	#$F717,d2
	add.w	d0,d2
	add.w	d0,d2			; (abx, abx)
	move.b	(a6,d2.l),d0		; ldx $00,x (a byte at a time: the table is at an odd address)
	lsl.w	#8,d0
	move.b	1(a6,d2.l),d0
	moveq	#0,d2
	move.b	\2(a6),d2
	add.w	d0,d2
	move.b	(a6,d2.l),d1
	cmp.b	#$FF,d1
	bne.s	.o\@
	clr.b	\2(a6)
	bra.s	.a\@
.o\@:	addq.b	#1,\2(a6)
	mwr	\3
	endm

; $F903 / $F93D / $F977: (\1) = 1: the byte (\3) of the table (\2) (pointers at $F9B1) -> \5 + (\4); then (\1) = $FF
mn_table macro
	mrd	\1
	cmp.b	#1,d1
	bne.s	.x\@
	mrd	\2
	moveq	#0,d0
	move.b	d1,d0
	move.l	#$F9B1,d2
	add.w	d0,d2
	add.w	d0,d2
	move.b	(a6,d2.l),d0
	lsl.w	#8,d0
	move.b	1(a6,d2.l),d0
	mrd	\3
	moveq	#0,d2
	move.b	d1,d2
	add.w	d0,d2
	move.b	(a6,d2.l),d0		; (pshb)
	mrd	\4
	moveq	#0,d2
	move.b	d1,d2
	add.w	#\5,d2
	move.b	d0,d1
	mwrx	0
	moveq	#-1,d1
	mwr	\1
.x\@:
	endm


mcu_native:
	ifnd	MCU_XLATE
	cmp.b	#$F0,(a6)		; (the DDRs the init sets)
	bne	MF046
	cmp.b	#$FF,1(a6)
	bne	MF046
	cmp.b	#$FF,5(a6)
	bne	MF046
	lea	G_MCRAM,a1
	lea	G_MCRAM-$C00,a4
	move.b	in0_val,d7
	move.b	6(a6),d3
	move.b	2(a6),d5		; (the first bus cycle: P1 = the pins | $80)
	and.b	#$F0,d5
	or.b	d7,d5
	or.b	#$80,d5

; $F1F8: ($0F98) = $47: P1 bit 6 low, high, low (the main CPU's interrupt)
	mrd	$0F98
	cmp.b	#$47,d1
	bne.s	.f236
	mp1rd	d0
	and.b	#$BF,d0
	mp1wr
	mp1rd	d0
	or.b	#$40,d0
	mp1wr
	mp1rd	d0
	and.b	#$BF,d0
	mp1wr

; $F236: P1 -> $0C1F, DSW0, DSW1, IN1, IN2 -> ($4E-$51) and $0C20-$0C23
.f236:	mp1rd	d1
	mwr	$0C1F
	move.b	dsw0,d1
	move.b	d1,$4E(a6)
	mwr	$0C20
	move.b	dsw0+1,d1
	move.b	d1,$4F(a6)
	mwr	$0C21
	move.b	dsw0+2,d1
	move.b	d1,$50(a6)
	mwr	$0C22
	move.b	dsw0+3,d1
	move.b	d1,$51(a6)
	mwr	$0C23

	bsr	mn_coins		; $F092
	bsr	mn_lockout		; $F1B0
	mn_counter $0C6F,$0C24,$52	; $F2A7
	mn_counter $0C70,$0C25,$53	; $F347
	bsr	mn_f3e3
	mn_scan	$0C5F,$0C60,$0C61,0,4,2,6,$0C62,$0C63	; $F48F
	mn_scan	$0C67,$0C68,$0C69,1,5,3,7,$0C6A,$0C6B	; $F585
	mn_seq	$0C72,$5D,$0C73		; $F67F
	mn_seq	$0C74,$5E,$0C75
	mn_seq	$0C76,$5F,$0C77		; $F6CB
	mn_seq	$0C80,$60,$0C81		; $F6F1
	bsr	mn_countdown		; $F899
	mrd	$0C71			; $F8D5
	cmp.b	#$0D,d1
	bne.s	.f8f1
	cmp.b	#$0C,$54(a6)
	bne.s	.f8f1
	moveq	#$2A,d1
	mwr	$0C1E
.f8f1:	mrd	$0C7C			; $F8F1: 0..5
	addq.b	#1,d1
	cmp.b	#6,d1
	bne.s	.f8fd
	moveq	#0,d1
.f8fd:	mwr	$0C7C
	mn_table $0F88,$0F8A,$0F89,$0F8B,$0C88	; $F903
	mn_table $0F8C,$0F8E,$0F8D,$0F8F,$0D88	; $F93D
	mn_table $0F90,$0F92,$0F91,$0F93,$0E88	; $F977
	mrd	$0F97			; $F299: $4A asks for a reset
	cmp.b	#$4A,d1
	beq.s	.reset
	mrd	$0F96			; $F07F (the delay of $F089 is not kept)
	move.w	#$0F96,d2
	bra.s	mn_ports
.reset:	move.w	#$0F97,d2
	bsr.s	mn_ports
	bra	mcu_restart
	else
	bra	MF046
	endc


	ifnd	MCU_XLATE
; the ports after the last bus cycle, a read of d2 (B = the byte)
mn_ports:
	move.b	d5,d0			; P1 (bit 7: a read)
	and.b	#$F0,d0
	or.b	d7,d0
	or.b	#$80,d0
	move.b	d0,2(a6)
	or.b	#$0F,d0
	move.b	d0,p1_out
	clr.b	4(a6)			; P3 DDR: in
	move.b	d3,6(a6)
	move.b	d2,7(a6)		; P4 = X low
	move.w	d2,$4A(a6)
	move.w	d2,d0
	lsr.w	#8,d0
	and.b	#$0F,d0
	or.b	#$10,d0
	move.b	d0,3(a6)		; P2 = X high nibble | the clock
	move.b	d0,p2_out
	move.b	d1,p3_in
	rts

; $F092: ($0F98) = $47: the coin inputs (P1 bits 0-2), the credits, the coin lockout
mn_coins:
	mrd	$0F98
	cmp.b	#$47,d1
	bne	mn_rts
	mp1rd	d0
	lsl.b	#4,d0
	lea	$40(a6),a0
	mn_edge
	mn_edge
	mn_edge
	mn_coin	$43,3,$48
	mn_coin	$41,5,$49
	tst.b	$45(a6)			; the service coin
	bne.s	mn_f156
	mrd	$0C1E
	cmp.b	#8,d1
	bhi.s	mn_f161
	addq.b	#1,d1
	mwr	$0C1E
	moveq	#1,d1
	mwr	$0F99
mn_f156:
	mrd	$0C1E			; more than 8 credits: the lockout (P1 bit 4 low)
	cmp.b	#8,d1
	bls.s	mn_f168
mn_f161:
	mp1rd	d0
	and.b	#$EF,d0
	mp1wr
mn_rts:	rts
mn_f168:
	mp1rd	d0
	or.b	#$10,d0
	mp1wr
	rts

; $F1B0: ($0F94) = 1: lockout, $FF: release
mn_lockout:
	mrd	$0F94
	cmp.b	#1,d1
	beq.s	mn_f161
	cmp.b	#$FF,d1
	beq.s	mn_f168
	rts

; $F3E3: ($0C7E) = 1: ($0C26) = 0, 2: +1, 4 / 8 / $10 / $20 / $40: $31 / $62 / $63 / $64 / $65; then ($0C7E) = 0; a copy
; at ($54)
mn_f3e3:
	mrd	$0C7E
	cmp.b	#1,d1
	beq.s	.i1
	cmp.b	#2,d1
	beq.s	.i2
	moveq	#$31,d0
	cmp.b	#4,d1
	beq.s	.set
	moveq	#$62,d0
	cmp.b	#8,d1
	beq.s	.set
	moveq	#$63,d0
	cmp.b	#$10,d1
	beq.s	.set
	moveq	#$64,d0
	cmp.b	#$20,d1
	beq.s	.set
	moveq	#$65,d0
	cmp.b	#$40,d1
	beq.s	.set
	mrd	$0F95
	cmp.b	#$42,d1
	bne.s	.r
	mrd	$0C26
.r:	rts
.i1:	moveq	#0,d1
	mwr	$0C26
	clr.b	$54(a6)
	bra.s	.cl
.i2:	mrd	$0C26
	addq.b	#1,d1
	move.b	d1,$54(a6)
	mwr	$0C26
	bra.s	.cl
.set:	move.b	d0,d1
	mwr	$0C26
	move.b	d0,$54(a6)
.cl:	moveq	#0,d1
	mwr	$0C7E
	rts

; $F899: the 16-bit count at $0C78 (low) / $0C79 while ($0C7A) is set: 0 -> ($0C7A) = 0, ($0C7B) = 1
mn_countdown:
	mrd	$0C7A
	tst.b	d1
	beq.s	.r
	mrd	$0C79
	move.b	d1,d2
	lsl.w	#8,d2
	mrd	$0C78
	move.b	d1,d2
	subq.w	#1,d2
	bne.s	.n
	moveq	#0,d1
	mwr	$0C7A
	moveq	#1,d1
	mwr	$0C7B
.r:	rts
.n:	move.b	d2,d1
	mwr	$0C78
	lsr.w	#8,d2
	move.b	d2,d1
	mwr	$0C79
	rts
	endc
