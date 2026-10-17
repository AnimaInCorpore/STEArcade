; Gyruss's sound on the STE (included by gyruss.s): the sound board's Z80 driver, translated (tools/sndgen.py ->
; build/gyruss/snd_code.s), drives five emulated AY-3-8910 register files; their fifteen channels go to the YM2149's
; three each arcade frame (snd_ym: the loudest audible ones, kept on their YM channel while they last, Kung-Fu Master's
; method), the periods scaled from the AYs' 1.789772 MHz to the YM's 2 MHz.  The i8039's effects (its program
; synthesises them on a DAC) were rendered offline (tools/i8039.py, engine/mcs48.py: equal to MAME's DAC writes) and
; play on the DMA sound: `out ($14)` (its IRQ) restarts the effect of the latch `out ($18)` wrote (1-7; 0 and 8-15
; stop), as the i8039 does; one voice, a 2 KB ring at 6258 Hz filled SND_LEAD bytes ahead of the DMA's counter once an
; arcade frame (Kung-Fu Master's player, src/sound.s there).
;
; snd_frame (once an arcade frame, before its NMI): the commands the game wrote since the last call (gy_sound's ring)
; each run the driver's IRQ handler ($0038, TOKEN as the return address), then the frame's ticks run its main loop once
; each ($010C to the loop's head $00FD, the hook snd_hook): TICKS_FX (16.16) a frame.  tools/sound.py TickBoard + YM
; are the same in Python (tools/sound_test.py compares).
;
; The driver's registers between runs: snd_regs (d0-d4, d6, a2, a5: z80x.FAST's map); a6 = snd_g + $8000 (its 64 KB,
; signed offsets: $8000-$FFFF below), a4 = snd_dispatch_sw.  The main program's registers are saved around a run.

SND_TICKS_FX = 756000			; (tools/sound.py TICKS_FX: 11.536 ticks an arcade frame)
SND_TOKEN = $FEFF			; $FFFE on the Z80 stack, byte swapped (sound.py TOKEN)
SND_LOOP_SW = $FD00			; $00FD, byte swapped
G_SND = snd_g+$8000

	section text,code

snd_init:
	movem.l	d0-d7/a0-a6,-(sp)
	clr.b	snd_tail
	clr.l	snd_acc
	st	snd_dirty
	lea	snd_ym_cache,a0
	moveq	#16-1,d0
.y:	move.b	#$FF,(a0)+
	dbf	d0,.y
	move.l	#-1,snd_ymch		; (no AY channel on the YM's three: -1 bytes)
	lea	snd_regs,a0
	moveq	#8-1,d0
.r:	clr.l	(a0)+
	dbf	d0,.r
	move.l	#G_SND-1,snd_regs+28	; (a5: SP = $FFFF; the driver sets it)
	clr.w	snd_wp
	clr.l	snd_v
	clr.l	snd_v+4
	ifnd SIM
	bsr	snd_dma_init
	endc
	move.l	#X0000,snd_entry
	bsr	snd_run			; the boot: to the loop's head
	movem.l	(sp)+,d0-d7/a0-a6
	rts

; snd_run: the driver from snd_entry until it comes back (snd_hook at the loop's head, or snd_token_ret)
snd_run:
	move.l	sp,snd_sp0
	movem.l	snd_regs,d0-d4/d6/a2/a5
	lea	G_SND,a6
	lea	snd_dispatch_sw,a4
	move.l	snd_entry,a0
	jmp	(a0)
snd_hook:				; (d7 = the pc: only the loop's head is a hook)
snd_back:
	movem.l	d0-d4/d6/a2/a5,snd_regs
	move.l	snd_sp0,sp
	rts
snd_token_ret:				; the IRQ handler returned: the loop's head it interrupted popped
	addq.l	#2,a5
	bra.s	snd_back

snd_badpc:
	move	#$2700,sr
	ifd SIM
.l:	bra.s	.l
	endc
	moveq	#97,d0
	bra	crash_common

; snd_frame: an arcade frame of the sound board.  Keeps all registers.
snd_frame:
	movem.l	d0-d7/a0-a6,-(sp)
.cmd:	move.b	snd_tail,d0
	cmp.b	snd_head,d0
	beq.s	.ticks
	addq.b	#1,snd_tail
	and.w	#$FF,d0
	lea	snd_ring,a0
	move.b	(a0,d0.w),snd_latch
	move.l	snd_regs+28,a5		; the IRQ: the loop's head and TOKEN pushed
	move.w	#SND_LOOP_SW,-(a5)
	move.w	#SND_TOKEN,-(a5)
	move.l	a5,snd_regs+28
	move.l	#X0038,snd_entry
	bsr	snd_run
	bra.s	.cmd
.ticks:	move.l	snd_acc,d0
	add.l	#SND_TICKS_FX,d0
	move.l	d0,d1
	and.l	#$FFFF,d0
	move.l	d0,snd_acc
	swap	d1
	move.w	d1,snd_n
	bra.s	.tn
.tick:	move.l	#X010C,snd_entry
	bsr	snd_run
.tn:	subq.w	#1,snd_n
	bpl.s	.tick
	bsr	snd_ym
	ifnd SIM
	bsr	snd_dma_fill
	endc
	movem.l	(sp)+,d0-d7/a0-a6
	rts

; snd_effect: the i8039's IRQ: its effect snd_latch2 (1-7) from the start, 0 and 8-15 silence.  Keeps every register.
snd_effect:
	movem.l	d0-d1/a0,-(sp)
	moveq	#0,d0
	move.b	snd_latch2,d0
	cmp.w	#8,d0
	bhs.s	.stop
	lsl.w	#3,d0
	lea	snd_dac_tab,a0
	movem.l	(a0,d0.w),d0-d1		; offset, length
	add.l	#snd_dac,d0
	move.l	d0,snd_v
	add.l	d0,d1
	move.l	d1,snd_v+4
	bra.s	.out
.stop:	clr.l	snd_v
	clr.l	snd_v+4
.out:	movem.l	(sp)+,d0-d1/a0
	rts

SND_RING = 2048
SND_LEAD = 700

; snd_mix: d0.w = the bytes to add to the ring (a multiple of 4): the voice's (biased by 64; +64, then the sign bit
; flipped: signed for the DMA) or silence
snd_mix:
	movem.l	d0-d7/a0-a4,-(sp)
	move.l	snd_v,a0
	move.l	snd_v+4,a1
	lea	snd_ring_buf,a4
	moveq	#0,d3
	move.w	snd_wp,d3
	add.l	d3,a4
	move.l	#$80808080,d5
	move.l	#$40404040,d6
	moveq	#0,d7
	move.w	d0,d7			; the bytes left
.seg:	tst.w	d7
	beq.s	.done
	moveq	#0,d4
	move.w	#SND_RING,d4		; this run: to the ring's end, the voice's end, the bytes left
	sub.w	d3,d4
	cmp.w	d7,d4
	bls.s	.r1
	move.w	d7,d4
.r1:	moveq	#0,d2
	move.l	a1,d0
	sub.l	a0,d0
	bls.s	.r2
	moveq	#1,d2
	cmp.l	d4,d0
	bhs.s	.r2
	move.w	d0,d4
.r2:	sub.w	d4,d7
	add.w	d4,d3
	move.w	d4,d1
	lsr.w	#2,d1
	subq.w	#1,d1
	tst.w	d2
	bne.s	.one
.none:	clr.l	(a4)+
	dbf	d1,.none
	bra.s	.wrap
.one:	move.l	(a0)+,d0
	add.l	d6,d0
	eor.l	d5,d0
	move.l	d0,(a4)+
	dbf	d1,.one
.wrap:	cmp.w	#SND_RING,d3
	blo.s	.seg
	moveq	#0,d3
	lea	snd_ring_buf,a4
	bra.s	.seg
.done:	move.w	d3,snd_wp
	move.l	a0,snd_v
	movem.l	(sp)+,d0-d7/a0-a4
	rts

	ifnd SIM
snd_dma_init:				; the DMA sound: the ring in a loop, mono, 6258 Hz
	clr.b	$ffff8901.w
	move.l	#snd_ring_buf,d0
	move.l	d0,d1
	add.l	#SND_RING,d1
	move.l	d0,-(sp)
	move.b	1(sp),$ffff8903.w
	move.b	2(sp),$ffff8905.w
	move.b	3(sp),$ffff8907.w
	move.l	d1,(sp)
	move.b	1(sp),$ffff890f.w
	move.b	2(sp),$ffff8911.w
	move.b	3(sp),$ffff8913.w
	addq.l	#4,sp
	move.b	#$80,$ffff8921.w
	move.b	#3,$ffff8901.w
	rts

snd_dma_fill:				; the ring filled up to SND_LEAD bytes ahead of the DMA's counter
	movem.l	d0-d1,-(sp)
.rd:	moveq	#0,d0			; (the counter: read twice, the same value)
	move.b	$ffff8909.w,d0
	swap	d0
	move.b	$ffff890b.w,d0
	lsl.w	#8,d0
	move.b	$ffff890d.w,d0
	moveq	#0,d1
	move.b	$ffff8909.w,d1
	swap	d1
	move.b	$ffff890b.w,d1
	lsl.w	#8,d1
	move.b	$ffff890d.w,d1
	cmp.l	d0,d1
	bne.s	.rd
	sub.l	#snd_ring_buf,d0
	add.w	#SND_LEAD,d0
	sub.w	snd_wp,d0
	and.w	#SND_RING-1,d0
	cmp.w	#SND_LEAD+256,d0	; (never more than the lead and a bit: a wrap at the start)
	bhi.s	.x
	and.w	#-4,d0
	bsr	snd_mix
.x:	movem.l	(sp)+,d0-d1
	rts
	endc

; snd_out (`out (c),r`): d7.b = the port, d5.b = the value (the AYs' address $00 / $04 / ... / $10, data +2; the
; i8039's latch $18 and IRQ $14).  snd_in: d7.b = the port -> d7 the byte (an AY's register; the third AY's port A, the
; timer, 0).  Both keep every register but d5 / d7 / a0 / a1 (the translation's scratch; the flags: the Z80's are in
; d6).
snd_out:
	cmp.b	#$12,d7
	bhi.s	.other
	btst	#1,d7
	bne.s	.data
	btst	#0,d7
	bne.s	.out
	lsr.b	#2,d7			; the address
	and.w	#7,d7
	lea	snd_addr,a0
	and.b	#15,d5
	move.b	d5,(a0,d7.w)
	rts
.data:	btst	#0,d7
	bne.s	.out
	move.w	d6,-(sp)
	lsr.b	#2,d7			; the chip
	and.w	#7,d7
	lea	snd_addr,a0
	moveq	#0,d6
	move.b	(a0,d7.w),d6
	cmp.b	#13,d6			; (the envelope's shape: written, the YM's too)
	bne.s	.ne
	lea	snd_env,a0
	st	(a0,d7.w)
.ne:	lsl.w	#4,d7
	add.w	d6,d7
	lea	snd_ay,a0
	move.b	d5,(a0,d7.w)
	st	snd_dirty
	move.w	(sp)+,d6
	rts
.other:	cmp.b	#$18,d7
	bne.s	.o14
	move.b	d5,snd_latch2
	rts
.o14:	cmp.b	#$14,d7
	bne.s	.out
	addq.w	#1,snd_effects
	bra	snd_effect
.out:	rts

snd_in:
	movem.l	d6/a0,-(sp)
	and.w	#$FF,d7
	cmp.w	#$11,d7
	bhi.s	.ff
	move.w	d7,d6
	and.w	#3,d6
	cmp.w	#1,d6
	bne.s	.ff
	lsr.w	#2,d7			; the chip
	lea	snd_addr,a0
	moveq	#0,d6
	move.b	(a0,d7.w),d6
	cmp.w	#2,d7
	bne.s	.reg
	cmp.w	#14,d6
	bne.s	.reg
	moveq	#0,d7			; (the timer)
	bra.s	.out
.reg:	lsl.w	#4,d7
	add.w	d6,d7
	lea	snd_ay,a0
	move.b	(a0,d7.w),d7
	and.l	#$FF,d7
	bra.s	.out
.ff:	moveq	#-1,d7
	and.l	#$FF,d7
.out:	movem.l	(sp)+,d6/a0
	rts

; snd_ym: the YM's registers from the five AYs (tools/sound.py YM): each channel's score (its volume, 15 for the
; envelope; -1 silent: volume 0 or neither tone nor noise on), the three best (ties: the lower number), a YM channel
; holding a chosen one keeps it, the others take the rest in order; periods x 2000000 / 1789772; the noise and envelope
; of the first chosen channel's chip that uses them; only the changed registers written (the shape when its chip wrote
; it this frame).
snd_ym:
	tst.b	snd_dirty		; (no AY register written: the YM's stay)
	beq	.yout
	clr.b	snd_dirty
	lea	snd_ay,a0
	lea	snd_score,a1
	moveq	#0,d2			; the channel 0-14
	moveq	#0,d3			; its chip's offset
	moveq	#0,d4			; its voice
.sc:	moveq	#-1,d0
	move.w	d3,d7
	add.w	d4,d7
	move.b	8(a0,d7.w),d1		; the voice's volume
	and.b	#$1F,d1
	beq.s	.s1
	move.b	7(a0,d3.w),d5		; tone or noise on (0 = on)?
	btst	d4,d5
	beq.s	.on
	addq.w	#3,d4
	btst	d4,d5
	sne	d7
	subq.w	#3,d4
	tst.b	d7
	bne.s	.s1
.on:	moveq	#15,d0
	btst	#4,d1
	bne.s	.s1
	move.b	d1,d0
.s1:	move.b	d0,(a1,d2.w)
	addq.w	#1,d2
	addq.w	#1,d4
	cmp.w	#3,d4
	blo.s	.sc
	moveq	#0,d4
	add.w	#16,d3
	cmp.w	#15,d2
	blo.s	.sc
	; the three best: their channels in score order
	lea	snd_pick,a2
	moveq	#2,d6
.pk:	moveq	#-1,d3			; the best score
	moveq	#-1,d4			; its channel
	moveq	#0,d2
.pl:	move.b	(a1,d2.w),d0
	ext.w	d0
	cmp.w	d3,d0
	ble.s	.pn
	move.w	d0,d3
	move.w	d2,d4
.pn:	addq.w	#1,d2
	cmp.w	#15,d2
	blo.s	.pl
	move.b	d4,(a2)+
	tst.w	d4
	bmi.s	.pz
	move.b	#-2,(a1,d4.w)		; (taken)
.pz:	dbf	d6,.pk
	; the YM channels: one that holds a chosen channel keeps it; the others take the remaining ones in order
	lea	snd_ymch,a3
	lea	snd_newch,a4
	move.l	#-1,(a4)
	lea	snd_pick,a2
	moveq	#2,d6
.keep:	move.b	(a2)+,d0
	bmi.s	.kn
	moveq	#2,d5
.kk:	cmp.b	(a3,d5.w),d0
	bne.s	.kx
	move.b	d0,(a4,d5.w)
	move.b	#-1,-1(a2)		; (placed)
.kx:	dbf	d5,.kk
.kn:	dbf	d6,.keep
	lea	snd_pick,a2
	moveq	#2,d6
.fill:	move.b	(a2)+,d0
	bmi.s	.fn
	moveq	#0,d5
.ff:	tst.b	(a4,d5.w)
	bmi.s	.fp
	addq.w	#1,d5
	bra.s	.ff
.fp:	move.b	d0,(a4,d5.w)
.fn:	dbf	d6,.fill
	move.l	(a4),(a3)		; (snd_ymch: this frame's)
	; the YM's registers into snd_ym_new
	lea	snd_ym_new,a2
	clr.l	(a2)
	clr.l	4(a2)
	clr.l	8(a2)
	clr.l	12(a2)
	moveq	#$3F,d7			; the mixer: all off
	moveq	#-1,d4			; the chip whose noise is used (-1 none: its offset)
	moveq	#-1,d5			; the chip whose envelope
	moveq	#0,d6			; the YM channel
.ych:	move.b	(a3,d6.w),d0
	bmi	.yn
	ext.w	d0
	moveq	#0,d3			; the chip's offset, the voice
.y0:	cmp.w	#3,d0
	blo.s	.y1
	subq.w	#3,d0
	add.w	#16,d3
	bra.s	.y0
.y1:	lea	(a0,d3.w),a1		; the chip's registers
	move.w	d0,d1
	add.w	d1,d1
	moveq	#0,d2
	move.b	1(a1,d1.w),d2
	lsl.w	#8,d2
	move.b	(a1,d1.w),d2
	and.w	#$0FFF,d2
	bsr	snd_scale
	cmp.l	#$0FFF,d2
	bls.s	.t1
	move.w	#$0FFF,d2
.t1:	move.w	d6,d1
	add.w	d1,d1
	move.b	d2,(a2,d1.w)
	lsr.w	#8,d2
	move.b	d2,1(a2,d1.w)
	move.b	8(a1,d0.w),d1		; volume
	and.b	#$1F,d1
	move.b	d1,8(a2,d6.w)
	btst	#4,d1
	beq.s	.ne
	tst.w	d5
	bpl.s	.ne
	move.w	d3,d5
.ne:	move.b	7(a1),d1		; tone / noise enables (0 = on)
	btst	d0,d1
	bne.s	.nt
	bclr	d6,d7
.nt:	addq.w	#3,d0
	btst	d0,d1
	bne.s	.yn
	addq.w	#3,d6
	bclr	d6,d7
	subq.w	#3,d6
	tst.w	d4
	bpl.s	.yn
	move.w	d3,d4
.yn:	addq.w	#1,d6
	cmp.w	#3,d6
	blo	.ych
	or.b	#$C0,d7			; (bits 6 / 7: the STE's ports A and B stay outputs)
	move.b	d7,7(a2)
	tst.w	d4			; noise period
	bmi.s	.nn
	moveq	#0,d2
	move.b	6(a0,d4.w),d2
	and.w	#$1F,d2
	bsr	snd_scale
	cmp.l	#31,d2
	bls.s	.n1
	moveq	#31,d2
.n1:	move.b	d2,6(a2)
.nn:	tst.w	d5			; envelope period and shape
	bmi.s	.ne2
	moveq	#0,d2
	move.b	12(a0,d5.w),d2
	lsl.w	#8,d2
	move.b	11(a0,d5.w),d2
	bsr	snd_scale
	cmp.l	#$FFFF,d2
	bls.s	.e1
	move.w	#$FFFF,d2
.e1:	move.b	d2,11(a2)
	lsr.w	#8,d2
	move.b	d2,12(a2)
	move.b	13(a0,d5.w),13(a2)
.ne2:	; write the registers that changed; the shape when the chosen chip's was written
	lea	snd_ym_cache,a1
	moveq	#0,d0
.w:	cmp.w	#13,d0
	beq.s	.shape
	move.b	(a2,d0.w),d1
	cmp.b	(a1,d0.w),d1
	beq.s	.wn
	move.b	d1,(a1,d0.w)
	ifnd SIM
	move.b	d0,$ffff8800.w
	move.b	d1,$ffff8802.w
	endc
	addq.w	#1,snd_ym_writes
.wn:	addq.w	#1,d0
	cmp.w	#14,d0
	blo.s	.w
.yout:
	clr.l	snd_env
	clr.l	snd_env+4
	rts
.shape:	tst.w	d5
	bmi.s	.wn
	move.w	d5,d1
	lsr.w	#4,d1			; (the chip)
	lea	snd_env,a3
	tst.b	(a3,d1.w)
	beq.s	.wn
	move.b	13(a2),d1
	move.b	d1,(a1,d0.w)
	ifnd SIM
	move.b	d0,$ffff8800.w
	move.b	d1,$ffff8802.w
	endc
	addq.w	#1,snd_ym_writes
	bra.s	.wn

snd_scale:				; d2.w = an AY period -> d2.l the YM's (x 2000000 / 1789772: p + p * 7698 / 65536)
	move.l	d3,-(sp)
	and.l	#$FFFF,d2
	move.l	d2,d3
	mulu	#7698,d3
	swap	d3
	and.l	#$FFFF,d3
	add.l	d3,d2
	move.l	(sp)+,d3
	rts

	include	"snd_code.s"
	include	"snd_dac.s"

	section data,data
; The sound Z80's 64 KB (a6 = its address 0, signed offsets): $8000-$FFFF first, then the ROM at $0000-$3FFF, the RAM
; at $6000-$63FF.
	cnop	0,4
snd_g:		dcb.b	$8000,0
	incbin	"snd.rom"
	dcb.b	$4000,0

	section bss,bss
	even
snd_regs:	ds.l	8		; d0-d4, d6, a2, a5 between runs
snd_v:		ds.l	2		; the effect: the next byte, the end
snd_wp:		ds.w	1
snd_ring_buf:	ds.b	SND_RING
snd_entry:	ds.l	1
snd_sp0:	ds.l	1
snd_acc:	ds.l	1
snd_ymch:	ds.l	1		; the AY channel on each YM channel (-1 none), 4th byte unused
snd_newch:	ds.l	1
snd_n:		ds.w	1
snd_effects:	ds.w	1
snd_ym_writes:	ds.w	1
snd_ay:		ds.b	5*16
snd_env:	ds.b	8		; the envelope shape written this frame, by chip
snd_addr:	ds.b	8		; (5 used: the chips; 8 keep the words after it even)
snd_score:	ds.b	16
snd_pick:	ds.b	4
snd_ym_new:	ds.b	16
snd_ym_cache:	ds.b	16
snd_tail:	ds.b	1
snd_latch:	ds.b	1
snd_latch2:	ds.b	1
snd_dirty:	ds.b	1
	even
