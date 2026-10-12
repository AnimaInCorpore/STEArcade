; Splatterhouse's CUS64 MCU (HD63701) natively: what one arcade frame of it does to TRIRAM.
;
; The 68000 side of tools/mcu.py (MCUNative), checked against it by tools/mcu68k_test.py.  Not here: the voice
; player itself (the samples' DAC streams are converted for the STE separately: mcu.py sample_info/sample_ticks), the
; $02F commands, the $03C EEPROM records and the RAM test ($001): asked for, they set mcu_unsupported and are ignored
; (Splatterhouse uses them during the boot only, before the port's start).
;
;   mcu_frame   one window of the MCU (the vertical blank's work, where machine.run_others runs it)
;               a0 = TRIRAM (the 2 KB as the arcade CPUs see them), a1 = 4 bytes: CONTROL0, CONTROL1, COIN, DIPSW
;               (the arcade's active-low port bytes); all registers kept
;   mcu_p1      the port 1 byte written this frame (bit 0 coin lockout off, bits 1/2 the coin counters)
;   mcu_start   per channel: the voice ROM offset of the header of the sample started this frame, -1 none
;               (the STE's player starts its converted sample; mcu_stop: per channel a byte, 1 = stopped this
;               frame by a request; a sample's own end needs no event)
; The state (mcu_state, mcu_state_end: the snapshot loads it): the MCU's RAM $80-$FF, the two channels' ticks to
; their sample's end counted from the next window's start, the port 1 latch.
;
; Per frame (TRIRAM[0] = $A6, the kludge byte: else the MCU spins and does nothing):
;   the voice requests ($02C/$02E bit 6; page = low nibble, sample $02B/$02D, 0 = stop): bit 6 cleared; a start
;   (unless the channel plays a sample of a higher priority, or the same request with "no restart") at tick
;   MCU_ACT sets bit 7, which the sample's end clears (its length from mcu_samples); a stop at tick MCU_STOP
;   the frame's work: RAM $8F-$AD to TRIRAM $00C-$02A, the inputs, the coin counter pulses ($039/$03A) and the
;   lockout ($03B) on port 1, the time counters (power on, the players of $038's bits), the edges of $038
; A window is 99 ticks (the output compare interrupt every 256 E clocks).

MCU_TICKS = 99
MCU_ACT = 3                     ; tools/mcu.py ACT_TICK, STOP_TICK
MCU_STOP = 1

	section text,code

mcu_frame:
	movem.l	d0-d7/a0-a5,-(sp)
	moveq	#-1,d0
	move.l	d0,mcu_start
	move.l	d0,mcu_start+4
	clr.w	mcu_stop
	cmp.b	#$A6,(a0)
	bne	.out
	lea	mcu_ram-$80,a2			; (a2,addr): the MCU's RAM at its own addresses
	; ---- the voice requests (F469), channel 0 then 1: d6/d7 = what happens (0 none, 1 stop, 2 start)
	moveq	#0,d6
	moveq	#0,d7
	lea	mcu_ch0,a3
	bsr	mcu_request
	move.l	d0,d6
	lea	mcu_ch1,a3
	bsr	mcu_request
	move.l	d0,d7
	; ---- $001 (BCCB): the acknowledge of $8E; the RAM test not modelled
	tst.b	($8E,a2)
	beq.s	.t1
	tst.b	1(a0)
	bne.s	.t2
	clr.b	($8E,a2)
	clr.b	2(a0)
	bra.s	.t2
.t1:	tst.b	1(a0)
	beq.s	.t2
	st	mcu_unsupported
.t2:	; ---- commands ($02F) and records ($03C): not modelled
	moveq	#$0F,d0
	and.b	$2F(a0),d0
	or.b	$3C(a0),d0
	beq.s	.t3
	st	mcu_unsupported
.t3:	; ---- the channels through the window's ticks
	lea	mcu_ch0,a3
	move.l	d6,d0
	bsr	mcu_ticks
	lea	mcu_ch1,a3
	move.l	d7,d0
	bsr	mcu_ticks
	; ---- the frame's work after IRQ1
	bsr	mcu_work
.out:	movem.l	(sp)+,d0-d7/a0-a5
	rts

; a channel's constants: the TRIRAM byte, its RAM bytes (active, header, the request's two bytes), its end tick
	rsreset
CH_TRI	rs.w	1			; $02C / $02E
CH_ACT	rs.w	1			; $D6 / $DF
CH_HDR	rs.w	1			; $DC / $E5
CH_REQ	rs.w	1			; $DD / $E6
CH_END	rs.w	1			; (offset of the long in mcu_end)
CH_NUM	rs.w	1			; 0 / 1

; mcu_request: a3 = the channel; out d0 = 0, 1 (stop), or 2 | the sample's long (header<<24|length) << 8 ... kept in
; mcu_pend (the long) and the request bytes in mcu_preq
mcu_request:
	moveq	#0,d0
	move.w	CH_TRI(a3),d1
	move.b	(a0,d1.w),d2
	btst	#6,d2
	beq.s	.none
	bclr	#6,d2
	move.b	d2,(a0,d1.w)
	move.b	-1(a0,d1.w),d3			; the sample number
	bne.s	.start
	moveq	#1,d0				; stop
.none:	rts
.start:	moveq	#$0F,d4
	and.b	d2,d4				; the page
	mulu	#255,d4
	moveq	#0,d5
	move.b	d3,d5
	add.w	d5,d4
	subq.w	#1,d4
	lsl.l	#2,d4
	lea	mcu_samples,a4
	move.l	(a4,d4.l),d4			; header << 24 | length
	move.w	CH_ACT(a3),d5
	tst.b	(a2,d5.w)
	beq.s	.go
	move.w	CH_REQ(a3),d5
	cmp.b	(a2,d5.w),d3
	bne.s	.prio
	cmp.b	1(a2,d5.w),d2
	bne.s	.prio
	move.w	CH_HDR(a3),d5			; the same request again: restarted unless "no restart"
	tst.b	(a2,d5.w)
	bmi.s	.none
	bra.s	.go
.prio:	move.w	CH_HDR(a3),d5			; another: not if the playing one's priority is below
	move.b	(a2,d5.w),d1
	and.b	#$7C,d1
	move.l	d4,d5
	rol.l	#8,d5
	and.b	#$7C,d5
	cmp.b	d5,d1
	bcs.s	.none
.go:	move.w	CH_NUM(a3),d5
	add.w	d5,d5
	lea	mcu_preq,a4
	move.b	d3,(a4,d5.w)			; the request bytes ($02B, $02C as now)
	move.b	d2,1(a4,d5.w)
	add.w	d5,d5
	lea	mcu_pend,a4
	move.l	d4,(a4,d5.w)
	moveq	#2,d0
	rts

; mcu_ticks: a3 = the channel, d0 = its request (0, 1 stop, 2 start); the end, stop, start in their tick order
mcu_ticks:
	move.w	CH_END(a3),d1
	lea	mcu_end,a4
	add.w	d1,a4				; a4 = the channel's end tick
	move.w	CH_ACT(a3),d2
	move.w	CH_TRI(a3),d3
	tst.b	(a2,d2.w)
	beq.s	.req
	move.l	(a4),d4				; playing: does it end before the request's tick?
	moveq	#MCU_TICKS,d5
	tst.b	d0
	beq.s	.cmp
	moveq	#MCU_STOP,d5
	cmp.b	#1,d0
	beq.s	.cmp
	moveq	#MCU_ACT,d5
.cmp:	cmp.l	d5,d4
	bcc.s	.req
	bsr	.end
.req:	tst.b	d0
	beq.s	.left
	cmp.b	#1,d0
	bne.s	.start
	clr.b	(a2,d2.w)			; stop: off, the header cleared, bit 7 as it is
	move.w	CH_HDR(a3),d5
	clr.b	(a2,d5.w)
	move.w	CH_NUM(a3),d5
	lea	mcu_stop,a5
	st	(a5,d5.w)
	bra.s	.left
.start:	move.w	CH_NUM(a3),d5
	add.w	d5,d5
	lea	mcu_preq,a5
	move.w	CH_REQ(a3),d6
	move.b	(a5,d5.w),(a2,d6.w)
	move.b	1(a5,d5.w),1(a2,d6.w)
	add.w	d5,d5
	lea	mcu_pend,a5
	move.l	(a5,d5.w),d4
	move.l	d4,d6
	rol.l	#8,d6
	move.w	CH_HDR(a3),d5
	move.b	d6,(a2,d5.w)			; the header
	move.b	#1,(a2,d2.w)
	bset	#7,(a0,d3.w)
	and.l	#$00FFFFFF,d4
	addq.l	#MCU_ACT,d4
	move.l	d4,(a4)
	bsr	.offset
	moveq	#MCU_TICKS,d5
	cmp.l	d5,d4
	bcc.s	.left
	bsr	.end
.left:	tst.b	(a2,d2.w)			; still playing: count the window off
	beq.s	.done
	moveq	#MCU_TICKS,d5
	sub.l	d5,(a4)
.done:	rts
.end:	bclr	#7,(a0,d3.w)			; the $FF read: bit 7 cleared, the channel off
	clr.b	(a2,d2.w)
	move.w	CH_HDR(a3),d5
	clr.b	(a2,d5.w)
	rts
.offset:					; mcu_start: the started sample (the pointer of mcu_samples' entry)
	move.w	CH_NUM(a3),d5
	add.w	d5,d5
	lea	mcu_preq,a5
	moveq	#0,d6
	move.b	1(a5,d5.w),d6
	and.w	#$0F,d6
	mulu	#255,d6
	moveq	#0,d1
	move.b	(a5,d5.w),d1
	add.l	d1,d6
	subq.l	#1,d6
	add.w	d5,d5
	lea	mcu_start,a5
	move.l	d6,(a5,d5.w)			; page * 255 + number - 1 (mcu_sample_offsets has the ROM offsets)
	rts

; mcu_work: the frame's work after IRQ1 (B91A, B927, B9B6)
mcu_work:
	lea	($8F,a2),a3
	lea	$0C(a0),a4
	moveq	#31-1,d0
.copy:	move.b	(a3)+,(a4)+
	dbf	d0,.copy
	move.b	(a1),d0				; the inputs, inverted
	not.b	d0
	move.b	d0,($A9,a2)
	move.b	1(a1),d0
	not.b	d0
	move.b	d0,($AA,a2)
	move.b	3(a1),d0			; the DIP nibbles: $1000 = bits 0-3, $1002 = bits 4-7, bit-reversed
	bsr	mcu_dip
	move.b	d1,($AB,a2)
	move.b	3(a1),d0
	lsr.b	#4,d0
	bsr	mcu_dip
	move.b	d1,($AC,a2)
	move.b	2(a1),d0			; the coins (port 1's inputs, bits 3-6)
	not.b	d0
	and.b	#$78,d0
	move.b	d0,($AD,a2)
	move.b	($B4,a2),d1
	move.b	d1,mcu_p1			; (stb $02: the latch of the frame before)
	move.b	d1,mcu_state_p1
	moveq	#2,d2				; coin counter 1: $B5 $B7, $039, bit 1, $A5
	move.w	#$B5,d3
	move.w	#$39,d4
	move.w	#$A5,d5
	bsr	mcu_coin
	moveq	#4,d2				; coin counter 2: $B6 $B8, $03A, bit 2, $A7
	move.w	#$B6,d3
	move.w	#$3A,d4
	move.w	#$A7,d5
	bsr	mcu_coin
	bclr	#0,d1				; the lockout
	tst.b	$3B(a0)
	beq.s	.lock
	bset	#0,d1
.lock:	move.b	d1,($B4,a2)
	; the edges of $038
	move.b	($B2,a2),d0
	move.b	$38(a0),d1
	move.b	d1,($B2,a2)
	not.b	d0
	and.b	d1,d0
	lea	($9F,a2),a3
	moveq	#3-1,d2
.edge:	lsr.b	#1,d0
	bcc.s	.ne
	addq.b	#1,1(a3)
	bne.s	.ne
	addq.b	#1,(a3)
.ne:	addq.l	#2,a3
	dbf	d2,.edge
	; the time counters: power on, then the players of $038's bits 0-2
	moveq	#0,d0
	bsr	mcu_time
	moveq	#1,d0
	btst	#0,d1
	beq.s	.p2
	bsr	mcu_time
.p2:	moveq	#2,d0
	btst	#1,d1
	beq.s	.p3
	bsr	mcu_time
.p3:	moveq	#3,d0
	btst	#2,d1
	beq.s	.p4
	bsr	mcu_time
.p4:	move.b	#1,($B9,a2)
	move.b	#$FB,($BA,a2)
	rts

; d0 = a DIP nibble -> d1 = the inverted port byte (~($F0 | the nibble bit-reversed))
mcu_dip:
	moveq	#0,d1
	moveq	#4-1,d2
.rev:	lsr.b	#1,d0
	addx.b	d1,d1
	dbf	d2,.rev
	not.b	d1
	and.b	#$0F,d1
	rts

; a coin counter: d1 = the port byte being built, d2 = its bit, d3 = the timer's RAM ($B5/$B6; the flag at +2),
; d4 = the request byte in TRIRAM, d5 = the total's RAM word
mcu_coin:
	tst.b	(a2,d3.w)
	beq.s	.flag
	subq.b	#1,(a2,d3.w)
	rts
.flag:	tst.b	2(a2,d3.w)
	beq.s	.req
	clr.b	2(a2,d3.w)
	move.b	#8,(a2,d3.w)
	not.b	d2
	and.b	d2,d1
	not.b	d2
	rts
.req:	tst.b	(a0,d4.w)
	beq.s	.no
	subq.b	#1,(a0,d4.w)
	move.b	#1,2(a2,d3.w)
	move.b	#8,(a2,d3.w)
	or.b	d2,d1
	addq.b	#1,1(a2,d5.w)
	bne.s	.no
	addq.b	#1,(a2,d5.w)
.no:	rts

; BA28: d0 = the counter (0 power on, 1-3): frames mod 60 at $AE+n, then BCD seconds $92+4n, minutes $91+4n,
; hours $8F/$90+4n (ADDA/ADCA + DAA as the 6301 does them: mcu_daa)
mcu_time:
	movem.l	d0-d4/a3,-(sp)
	lea	($AE,a2),a3
	move.b	(a3,d0.w),d1
	addq.b	#1,d1
	cmp.b	#$3C,d1
	bcs.s	.f
	moveq	#0,d1
.f:	move.b	d1,(a3,d0.w)
	bne.s	.out
	lsl.w	#2,d0
	lea	($8F,a2),a3
	add.w	d0,a3
	moveq	#3,d0				; seconds, then minutes
.sm:	move.b	(a3,d0.w),d1
	moveq	#1,d2
	moveq	#0,d3
	bsr.s	mcu_daa
	cmp.b	#$60,d1
	bcs.s	.st
	moveq	#0,d1
.st:	move.b	d1,(a3,d0.w)
	bne.s	.out
	subq.w	#1,d0
	cmp.w	#1,d0
	bne.s	.sm
	move.b	1(a3),d1			; hours, 4 digits
	moveq	#1,d2
	moveq	#0,d3
	bsr.s	mcu_daa
	move.b	d1,1(a3)
	move.b	(a3),d1
	moveq	#0,d2
	bsr.s	mcu_daa				; (d3 = the carry)
	move.b	d1,(a3)
.out:	movem.l	(sp)+,d0-d4/a3
	rts

; mcu_daa: d1 = d1 + d2 + d3 (carry in, 0/1), then DAA (MAME's m6800 daa); out d1, d3 = the carry
mcu_daa:
	move.w	d0,-(sp)
	moveq	#0,d4
	move.b	d1,d4
	add.w	d2,d4
	add.w	d3,d4				; t (9 bits)
	move.b	d1,d0
	eor.b	d2,d0
	eor.b	d4,d0
	and.b	#$10,d0				; H
	moveq	#0,d3
	cmp.w	#$FF,d4
	bls.s	.nc
	moveq	#1,d3				; C of the add
.nc:	and.w	#$FF,d4
	moveq	#0,d2				; cf
	move.b	d4,d1
	and.b	#$0F,d1				; lsn
	cmp.b	#9,d1
	bhi.s	.l6
	tst.b	d0
	beq.s	.l0
.l6:	moveq	#6,d2
.l0:	move.b	d4,d0
	and.b	#$F0,d0				; msn
	cmp.b	#$80,d0
	bls.s	.m1
	cmp.b	#9,d1
	bls.s	.m1
	or.b	#$60,d2
.m1:	cmp.b	#$90,d0
	bhi.s	.m6
	tst.b	d3
	beq.s	.m0
.m6:	or.b	#$60,d2
.m0:	add.w	d2,d4
	cmp.w	#$FF,d4
	bls.s	.r
	moveq	#1,d3
.r:	move.b	d4,d1
	move.w	(sp)+,d0
	rts

mcu_ch0:	dc.w	$2C,$D6,$DC,$DD,0,0
mcu_ch1:	dc.w	$2E,$DF,$E5,$E6,4,1

	include	"mcu_samples.s"			; mcu_samples (tools/mcu.py --tables: per page 0-15, sample 1-255
						; a long, header << 24 | ticks), mcu_sample_offsets (the headers' offsets)

	section bss,bss
	even
mcu_state:
mcu_ram:	ds.b	128			; $80-$FF
mcu_end:	ds.l	2			; ticks from the next window's start to the playing sample's end
mcu_state_p1:	ds.b	1
mcu_unsupported: ds.b	1
mcu_state_end:
	even
mcu_p1:		ds.b	1
		ds.b	1
mcu_stop:	ds.b	2
mcu_start:	ds.l	2			; page * 255 + number - 1 of the sample started, -1 none
mcu_pend:	ds.l	2
mcu_preq:	ds.b	4
