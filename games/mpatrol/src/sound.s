; Moon Patrol's sound on the STE (included by mpatrol.s): the M52 sound board's M6803 driver (mp-s1.1a), translated
; (tools/sndgen.py -> build/mpatrol/snd_code.s, engine/m6801x.py's emitter), drives two emulated AY-3-8910 register
; files; their six channels go to the YM2149's three each arcade frame (snd_ym: the loudest audible ones, kept on their
; YM channel while they last), the periods scaled from the AYs' 894.886 kHz to the YM's 2 MHz.  Kung-Fu Master's
; player (games/kungfum/src/sound.s) on this board.
;
; snd_frame (once an arcade frame, before its IRQ): the sound commands the game wrote since the last call (mp_sound's
; ring) each run one iteration of the driver's main loop ($BC = the command & $1F; bit 7 set: the second write of a
; pair, ignored as by the driver's IRQ), then the frame's ticks one iteration each ($C0 = 1; 250 a second: 141/32 an
; arcade frame), then snd_ym.  tools/sound.py STEBoard is the same in Python (tools/sound_test.py compares).
;
; The 6803's context (m6801x): d0 = A, d1 = B, d2 = X (upper word 0), a5 = SP + 1, a6 = mcu_mem (its 64 KB: the
; registers $00-$1F, the RAM $80-$FF, the ROM at $F000); d3 / d6 / d7 / a0 scratch.  JSR / RTS on the 68000's
; stack; the loop's `jmp $FB1B` returns (mcu_restart).

	section text,code

snd_init:
	movem.l	d0-d7/a0-a6,-(sp)
	lea	snd_rom,a0
	lea	mcu_mem+$F000,a1
	move.w	#$1000/4-1,d0
.c:	move.l	(a0)+,(a1)+
	dbf	d0,.c
	clr.b	snd_tail
	clr.b	snd_acc
	move.b	#$FF,snd_mixer
	st	snd_dirty
	lea	snd_ym_cache,a0
	moveq	#16-1,d0
.y:	move.b	#$FF,(a0)+
	dbf	d0,.y
	move.l	#-1,snd_ymch		; (no AY channel on the YM's three: -1 bytes)
	clr.w	snd_wp
	clr.l	snd_v1
	clr.l	snd_v1+4
	ifnd SIM
	bsr	snd_dma_init
	endc
	bsr.s	.boot
	movem.l	(sp)+,d0-d7/a0-a6
	rts
.boot:	move.l	sp,snd_sp0		; (mcu_restart returns from here)
	lea	mcu_mem,a6
	moveq	#0,d0
	moveq	#0,d1
	moveq	#0,d2
	moveq	#0,d3
	clr.l	snd_regs
	clr.l	snd_regs+4
	clr.l	snd_regs+8
	jmp	MFB00			; the driver's reset (and its first iteration)

snd_iteration:				; one iteration of the driver's main loop (changes d0-d7 / a0 / a5 / a6)
	move.l	sp,snd_sp0
	lea	mcu_mem,a6
	lea	mcu_mem+$100,a5		; (SP = $FF)
	movem.l	snd_regs,d0-d2		; (A, B, X as the last iteration left them)
	jmp	MFB1B
mcu_restart:
	movem.l	d0-d2,snd_regs
	move.l	snd_sp0,sp
	rts

; snd_frame: an arcade frame of the sound board.  Keeps all registers.
snd_frame:
	movem.l	d0-d7/a0-a6,-(sp)
	ifd VOICE_TEST			; (a check of the DMA voice in Hatari: voices 1-3 in turn every 128 frames)
	move.w	isr_count,d0
	and.w	#127,d0
	bne.s	.vt
	move.w	isr_count,d0
	lsr.w	#7,d0
	and.w	#3,d0
	beq.s	.vt
	bsr	snd_voice
	endc
.vt:
.cmd:	move.b	snd_tail,d0
	cmp.b	snd_head,d0
	beq.s	.ticks
	addq.b	#1,snd_tail
	and.w	#$FF,d0
	lea	snd_ring,a0
	move.b	(a0,d0.w),d0
	bmi.s	.cmd			; (bit 7 set: no IRQ)
	move.b	d0,snd_latch
	and.b	#$1F,d0
	move.b	d0,mcu_mem+$BC
	clr.b	mcu_mem+$C0
	bsr	snd_voice		; (the ADPCM voice: commands 1-3)
	bsr	snd_iteration
	bra.s	.cmd
.ticks:	move.b	snd_acc,d0		; 141/32 ticks a frame
	add.b	#141,d0
	move.b	d0,d1
	and.b	#31,d0
	move.b	d0,snd_acc
	lsr.b	#5,d1
	and.w	#7,d1
	move.w	d1,snd_n
	bra.s	.tn
.tick:	move.b	#1,mcu_mem+$C0
	bsr	snd_iteration
.tn:	subq.w	#1,snd_n
	bpl.s	.tick
	bsr	snd_ym
	ifnd SIM
	bsr	snd_dma_fill
	endc
	movem.l	(sp)+,d0-d7/a0-a6
	rts

; The 6803's ports (m6801x hooks: d7 = the value / the result; everything else kept).  P2: bit 0 the write strobe
; (on its falling edge the bus is written), bit 2 address (1) / data (0), bit 3 selects AY 45M (chip 0), bit 4 AY 45L.
mcu_wr_p1:
	move.b	d7,snd_p1
	rts
mcu_rd_p1:
	move.l	a0,-(sp)
	move.b	snd_p2,d7
	btst	#3,d7
	beq.s	.l
	moveq	#0,d7
	move.b	snd_addr,d7
	cmp.b	#14,d7
	beq.s	.latch
	lea	snd_ay,a0
	move.b	(a0,d7.w),d7
	move.l	(sp)+,a0
	rts
.latch:	move.b	snd_latch,d7		; (port A: the sound command)
	move.l	(sp)+,a0
	rts
.l:	btst	#4,d7
	beq.s	.none
	moveq	#0,d7
	move.b	snd_addr+1,d7
	lea	snd_ay+16,a0
	move.b	(a0,d7.w),d7
	move.l	(sp)+,a0
	rts
.none:	move.l	(sp)+,a0
	moveq	#-1,d7
	rts
mcu_rd_p3:
	moveq	#-1,d7
	rts
mcu_wr_p2:
	btst	#0,snd_p2		; a falling strobe? (else just the new value)
	beq	.st
	btst	#0,d7
	bne	.st
	movem.l	d6/a0,-(sp)
	move.b	snd_p2,d6
	move.b	d7,snd_p2
	btst	#2,d6
	beq.s	.data
	move.b	snd_p1,d7		; the address
	and.b	#15,d7
	btst	#3,d6
	beq.s	.a1
	move.b	d7,snd_addr
.a1:	btst	#4,d6
	beq.s	.done
	move.b	d7,snd_addr+1
	bra.s	.done
.data:	btst	#3,d6
	beq.s	.d1
	moveq	#0,d7
	move.b	snd_addr,d7
	lea	snd_ay,a0
	move.b	snd_p1,(a0,d7.w)
	st	snd_dirty
	cmp.b	#13,d7
	bne.s	.d1
	st	snd_env			; (the envelope's shape written: it restarts)
.d1:	btst	#4,d6
	beq.s	.done
	moveq	#0,d7
	move.b	snd_addr+1,d7
	lea	snd_ay+16,a0
	move.b	snd_p1,(a0,d7.w)
	st	snd_dirty
	cmp.b	#13,d7
	bne.s	.done
	st	snd_env+1
.done:	move.b	snd_p2,d7
	movem.l	(sp)+,d6/a0
	rts
.st:	move.b	d7,snd_p2
	rts

; snd_ym: the YM2149 from the two AY register files.  An AY channel (c = chip * 3 + voice) is audible when its
; volume (or envelope mode) is not 0 and its tone or noise is enabled; the three loudest go on the YM (a channel that
; was on a YM channel keeps it), ties to the lower number.  Their periods x 2000000 / 894886 (2 p + p * 15396 / 65536),
; volumes and mixer bits; noise and the envelope from the chip of the first chosen channel that uses them.  Only
; changed YM registers are written (the shape only when the AY's was written).  sound.py ym() is the same.
snd_score_ch macro			; \1 = the chip's offset (0 / 16), \2 = the voice: its score into (a1)+
	moveq	#-1,d5
	move.b	8+\2+\1(a0),d1
	and.b	#$1F,d1
	beq.s	.n\@
	move.b	7+\1(a0),d4
	btst	#\2,d4
	beq.s	.a\@
	btst	#\2+3,d4
	bne.s	.n\@
.a\@:	moveq	#15,d5
	btst	#4,d1
	bne.s	.n\@
	moveq	#0,d5
	move.b	d1,d5
.n\@:	move.b	d5,(a1)+
	endm

snd_ym:
	tst.b	snd_dirty		; (no AY register written: the YM's stay)
	beq	.yout
	clr.b	snd_dirty
	lea	snd_ay,a0
	lea	snd_score,a1
	snd_score_ch 0,0
	snd_score_ch 0,1
	snd_score_ch 0,2
	snd_score_ch 16,0
	snd_score_ch 16,1
	snd_score_ch 16,2
	lea	snd_score,a1
	; the three best: kept ones first (their YM channel), then the best of the rest by score, lower number first
	lea	snd_pick,a2		; 3 bytes: the chosen channels in score order
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
	cmp.w	#6,d2
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
	moveq	#-1,d4			; the chip whose noise is used (-1 none)
	moveq	#-1,d5			; the chip whose envelope
	moveq	#0,d6			; the YM channel
.ych:	move.b	(a3,d6.w),d0
	bmi	.yn
	ext.w	d0
	moveq	#0,d3			; chip offset, voice
	cmp.w	#3,d0
	blo.s	.y0
	subq.w	#3,d0
	moveq	#16,d3
.y0:	lea	(a0,d3.w),a1		; the chip's registers
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
	clr.w	snd_env
	rts
.shape:	tst.w	d5
	bmi.s	.wn
	lea	snd_env,a3
	tst.w	d5
	beq.s	.s0
	addq.w	#1,a3
.s0:	tst.b	(a3)
	beq.s	.wn
	move.b	13(a2),d1
	move.b	d1,(a1,d0.w)
	ifnd SIM
	move.b	d0,$ffff8800.w
	move.b	d1,$ffff8802.w
	endc
	addq.w	#1,snd_ym_writes
	bra.s	.wn

snd_scale:				; d2.w = an AY period -> d2.l the YM's (x 2000000 / 894886: 2 p + p * 15396 / 65536)
	move.l	d3,-(sp)
	and.l	#$FFFF,d2
	move.l	d2,d3
	mulu	#15396,d3
	swap	d3
	and.l	#$FFFF,d3
	add.l	d2,d2
	add.l	d3,d2
	move.l	(sp)+,d3
	rts

; The ADPCM voice (tools/sound.py VoiceMix: the same in Python): the MSM5205's output of each voice command, decoded
; offline (build/mpatrol/snd_voices.bin, signed bytes at the DMA's 6258 Hz; voice 2 goes on with voice 3 there, as the
; driver does), copied into a ring the DMA sound plays in a loop; snd_frame fills the ring SND_LEAD bytes ahead of the
; DMA's counter.
SND_RING = 2048
SND_LEAD = 700

snd_voice:				; d0.b = the command & $1F: 1-3 (re)start the voice; 0 and the tunes $18-$1F end it
	movem.l	d0-d1/a0-a1,-(sp)	; (FC98 resets the MSM5205)
	and.w	#$1F,d0
	beq.s	.stop
	cmp.w	#$18,d0
	bhs.s	.stop
	cmp.w	#4,d0
	bhs.s	.out
	move.w	d0,d1
	subq.w	#1,d1
	lsl.w	#3,d1
	lea	snd_vtab,a0
	movem.l	(a0,d1.w),d1/a0		; offset, length
	add.l	#snd_voices,d1
	add.l	d1,a0			; the end
	move.l	d1,snd_v1
	move.l	a0,snd_v1+4
	bra.s	.out
.stop:	clr.l	snd_v1
	clr.l	snd_v1+4
.out:	movem.l	(sp)+,d0-d1/a0-a1
	rts

; snd_mix: d0.w bytes (a multiple of 4) of the voice (or silence) into the ring at snd_wp.  Keeps all registers.
snd_mix:
	movem.l	d0-d4/a0-a1/a4,-(sp)
	move.l	snd_v1,a0
	move.l	snd_v1+4,a1
	lea	snd_ring_buf,a4
	moveq	#0,d3
	move.w	snd_wp,d3
	add.l	d3,a4
	moveq	#0,d2
	move.w	d0,d2			; the bytes left
.seg:	tst.w	d2
	beq.s	.done
	moveq	#0,d4
	move.w	#SND_RING,d4		; this run: to the ring's end, the voice's end, the bytes left
	sub.w	d3,d4
	cmp.w	d2,d4
	bls.s	.r1
	move.w	d2,d4
.r1:	move.l	a1,d0
	sub.l	a0,d0
	bls.s	.none
	cmp.l	d4,d0
	bhs.s	.r2
	move.w	d0,d4
.r2:	sub.w	d4,d2
	add.w	d4,d3
	move.w	d4,d1
	lsr.w	#2,d1
	subq.w	#1,d1
.one:	move.l	(a0)+,(a4)+
	dbf	d1,.one
	bra.s	.wrap
.none:	sub.w	d4,d2
	add.w	d4,d3
	move.w	d4,d1
	lsr.w	#2,d1
	subq.w	#1,d1
.z:	clr.l	(a4)+
	dbf	d1,.z
.wrap:	cmp.w	#SND_RING,d3
	blo.s	.seg
	moveq	#0,d3
	lea	snd_ring_buf,a4
	bra.s	.seg
.done:	move.w	d3,snd_wp
	move.l	a0,snd_v1
	movem.l	(sp)+,d0-d4/a0-a1/a4
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

	include	"snd_code.s"
	include	"snd_voices.s"

	section data,data
	even
snd_rom:	incbin	"snd_rom.bin"

	section bss,bss
	even
snd_sp0:	ds.l	1
snd_v1:		ds.l	2		; the voice: the next byte, the end
snd_wp:		ds.w	1
snd_regs:	ds.l	3
snd_n:		ds.w	1
snd_ymch:	ds.b	4		; the AY channel on each YM channel (-1: none)
snd_newch:	ds.b	4
snd_pick:	ds.b	4
snd_score:	ds.b	6
snd_ay:		ds.b	32		; the two AYs' registers
snd_ym_new:	ds.b	16
snd_ym_cache:	ds.b	16
snd_addr:	ds.b	2
snd_env:	ds.b	2
snd_ym_writes:	ds.w	1
snd_p1:		ds.b	1
snd_p2:		ds.b	1
snd_latch:	ds.b	1
snd_tail:	ds.b	1
snd_acc:	ds.b	1
snd_mixer:	ds.b	1
snd_dirty:	ds.b	1
	even
mcu_mem:	ds.b	$10000
snd_ring_buf:	ds.b	SND_RING
	section text,code
