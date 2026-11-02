; Mr. HELI's i8751 MCU after the boot as native 68000 code: tools/mcu.py's MCU step for step (checked by
; tools/mcu68k_test.py against the model, the model by tools/mcu_test.py against the real program in the board).
; The interface: docs/mcu-interface.md, "The MCU (agent B)".
;
; The dual-port RAM is the V30's $B0000-$B0FFF: a0 points to it (the V30 image + $B0000).  MCU_SWAP (default 1):
; the image keeps the V30's bytes swapped in each word (V30 byte o at a0 + (o ^ 1)), 0: in V30 order.
; MCU_HB_POLL (default 0): 1 = mcu_frame finds the V30's heartbeat itself (the byte $FFE changed since the last
; frame) instead of calls of mcu_hb at the V30's stores to $B0FFE/F.
;
; Entries (all registers kept):
;   mcu_frame   a0 = dpram.  At every arcade frame boundary (the board's line 256, before the V30's VBL handler).
;   mcu_cmd     a0 = dpram, d0.b = the byte the V30 wrote to port C0, d1.w = units (1/3 MCU cycle = 4 V30 cycles)
;               since the frame boundary (the VBL handler's writes: 128, one line).
;   mcu_init    a0 = dpram, a1 = the 14 bytes of mcu_state (a snapshot's, mcu.py state_image).
;   mcu_hb      the V30 wrote the word at $B0FFE (or one of its bytes): the MCU's INT0.  a0 = dpram (dead MCU).
; Outputs for the sound code: mcu_snd_start.b = the sample command taken last ($FF none; the sound code clears it),
; mcu_snd_count.w + 1 at every start; the sample's data: mcu_samples (tools/mcu.py --tables: index n & 63).
;
; mcu_state (14 bytes, mcu.py state_image): state.b (0 main loop, 1 ROM test answered, 2 dead, 3 ROM test summing)
; wipe.b ($5B) wd.b ($44) hb.b ($5D) prio.b (bank 1 r3) pad.b end.l (the playing sample's end, units from the last
; frame boundary) romsum.l (state 3: when the answer lands, likewise).

	ifnd MCU_SWAP
MCU_SWAP	equ	1
	endc
	ifnd MCU_HB_POLL
MCU_HB_POLL	equ	0
	endc

MCU_UNITS_FRAME	equ	36352
MCU_LAG		equ	256		; port C0 -> the MCU's timer 1 started (mcu.py CMD_LAG)
MS_STATE	equ	0
MS_WIPE		equ	1
MS_WD		equ	2
MS_HB		equ	3
MS_PRIO		equ	4
MS_END		equ	6
MS_ROMSUM	equ	10
MS_SIZE		equ	14

	section text,code

mcu_init:
	movem.l	d0/a1-a2,-(sp)
	lea	mcu_state,a2
	moveq	#MS_SIZE-1,d0
.i:	move.b	(a1)+,(a2)+
	dbf	d0,.i
	st	mcu_snd_start
	clr.w	mcu_snd_count
	move.b	($FFE^MCU_SWAP)(a0),mcu_hb_last
	movem.l	(sp)+,d0/a1-a2
	rts

mcu_frame:
	movem.l	d0-d2/a1-a2,-(sp)
	lea	mcu_state,a1
	cmp.b	#$FF,MS_PRIO(a1)		; the playing sample's end
	beq.s	.idle
	sub.l	#MCU_UNITS_FRAME,MS_END(a1)
	bgt.s	.idle
	st	MS_PRIO(a1)
.idle:
	ifne MCU_HB_POLL
	move.b	($FFE^MCU_SWAP)(a0),d0
	cmp.b	mcu_hb_last,d0
	beq.s	.nohb
	move.b	d0,mcu_hb_last
	addq.b	#1,MS_HB(a1)
.nohb:
	endc
	move.b	MS_STATE(a1),d0
	beq.s	.run
	subq.b	#2,d0
	beq.s	.dead
	bcs	.out			; the ROM test answered: no ticks
	sub.l	#MCU_UNITS_FRAME,MS_ROMSUM(a1)	; summing: the answer lands?
	bgt	.out
	move.b	#1,MS_STATE(a1)
	movem.l	d3,-(sp)
	lea	mcu_romans(pc),a2
	move.w	#$FE0,d2
	moveq	#14-1,d1
.r:	move.w	d2,d3
	eor.w	#MCU_SWAP,d3
	move.b	(a2)+,0(a0,d3.w)
	addq.w	#1,d2
	dbf	d1,.r
	movem.l	(sp)+,d3
	bra.s	.out
.dead:	move.b	MS_WD(a1),($FFC^MCU_SWAP)(a0)	; dead: $FFC = $44 for ever
	bra.s	.out
.run:	move.b	MS_WIPE(a1),d0		; timer 0: $5B counts down (0, $FF: off)
	beq.s	.wd
	cmp.b	#$FF,d0
	beq.s	.wd
	subq.b	#1,MS_WIPE(a1)
.wd:	cmp.b	#1,MS_HB(a1)		; the watchdog: one heartbeat since the last tick
	bne.s	.miss
	cmp.b	#$80,MS_WD(a1)
	beq.s	.wdok
	clr.b	MS_WD(a1)
	bra.s	.wdok
.miss:	addq.b	#1,MS_WD(a1)
.wdok:	clr.b	MS_HB(a1)
	tst.b	MS_WIPE(a1)		; the main loop: the wipe
	bne.s	.nowipe
	st	MS_WIPE(a1)
	lea	mcu_wipe(pc),a2
	moveq	#32,d1
	bsr.s	mcu_copy
.nowipe:
	cmp.b	#$1E,MS_WD(a1)
	blo.s	.out
	move.b	#2,MS_STATE(a1)
	move.b	MS_WD(a1),($FFC^MCU_SWAP)(a0)
.out:	movem.l	(sp)+,d0-d2/a1-a2
	rts

; d1.w bytes from (a2) to dpram offsets 0.. (d2 = 0); d0-d2/a2 changed
mcu_copy:
	moveq	#0,d2
	subq.w	#1,d1
.c:	move.w	d2,d0
	eor.w	#MCU_SWAP,d0
	move.b	(a2)+,0(a0,d0.w)
	addq.w	#1,d2
	dbf	d1,.c
	rts

mcu_hb:
	addq.b	#1,mcu_state+MS_HB
	cmp.b	#2,mcu_state+MS_STATE
	bne.s	.r
	move.b	mcu_state+MS_WD,($FFC^MCU_SWAP)(a0)
.r:	rts

mcu_cmd:
	movem.l	d0-d3/a1-a2,-(sp)
	lea	mcu_state,a1
	move.b	MS_STATE(a1),d2
	cmp.b	#2,d2
	bhs	.out			; dead, or summing its ROM (interrupts off)
	cmp.b	#$10,d0
	beq.s	.check
	cmp.b	#$11,d0
	beq.s	.romtest
	; a sample command: the entry of n & 63
	and.w	#63,d0
	move.w	d0,d3
	lsl.w	#3,d3			; 8 bytes an entry: prio.b restart.b period.b vol.b length.l (units)
	lea	mcu_samples,a2
	add.w	d3,a2
	and.l	#$FFFF,d1
	add.l	#MCU_LAG,d1
	moveq	#-1,d3			; the playing priority ($FF when ended by now)
	move.b	MS_PRIO(a1),d3
	cmp.b	#$FF,d3
	beq.s	.cur
	cmp.l	MS_END(a1),d1
	blt.s	.cur
	move.b	#$FF,d3
.cur:	and.w	#$FF,d3
	moveq	#0,d2
	move.b	(a2),d2			; the new priority
	cmp.w	d3,d2
	blo.s	.take
	bne.s	.out
	tst.b	1(a2)			; equal: restart?
	beq.s	.out
.take:	move.b	d2,MS_PRIO(a1)
	add.l	4(a2),d1
	move.l	d1,MS_END(a1)
	move.b	d0,mcu_snd_start
	addq.w	#1,mcu_snd_count
	bra.s	.out
.check:	tst.b	d2			; $10: the protection check's code to $B0000, wiped after 3 ticks
	bne.s	.out
	lea	mcu_check(pc),a2
	moveq	#31,d1
	bsr	mcu_copy
	move.b	#3,MS_WIPE(a1)
	bra.s	.out
.romtest:
	tst.b	d2			; $11: the ROM test's answer at $FE0-$FED 65721 cycles later, then samples only
	bne.s	.out
	move.b	#3,MS_STATE(a1)
	and.l	#$FFFF,d1
	add.l	#3*65721,d1
	move.l	d1,MS_ROMSUM(a1)
.out:	movem.l	(sp)+,d0-d3/a1-a2
	rts

mcu_wipe:
	dc.b	$20,$1F,$1E,$1D,$1C,$1B,$1A,$19,$18,$17,$16,$15,$14,$13,$12,$11
	dc.b	$10,$0F,$0E,$0D,$0C,$0B,$0A,$09,$08,$07,$06,$05,$04,$03,$02,$01
	include	"mcu_tables.s"		; mcu_check (31 bytes), mcu_romans (14), mcu_samples (64 x 8)
	even

	section bss,bss
mcu_state:	ds.b	MS_SIZE
mcu_snd_count:	ds.w	1
mcu_snd_start:	ds.b	1
mcu_hb_last:	ds.b	1
