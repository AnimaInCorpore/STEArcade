; Juno First's sound on the STE (included by junofrst.s): the sound board's Z80 driver, translated (tools/sndgen.py ->
; build/junofrst/snd_code.s), drives an emulated AY-3-8910 register file whose three channels are the YM2149's three
; (snd_ym each arcade frame: periods scaled from the AY's 1.789773 MHz to the YM's 2 MHz).  The i8039's effects (its
; program synthesises them on a DAC) were rendered offline (tools/i8039.py, engine/mcs48.py) and play on the DMA sound:
; the Z80's write to $6000 (the i8039's IRQ) restarts the effect of the latch it wrote to $5000 (1-8; 0 and 9-15 are
; silence), as the i8039 does; one voice, a 2 KB ring at 6258 Hz filled SND_LEAD bytes ahead of the DMA's counter once
; an arcade frame (Kung-Fu Master's player, src/sound.s there).  The i8039's status (AY port A bits 0-2) is 1 while an
; effect of the commands 5-8 plays (snd_busy).
;
; snd_frame (once an arcade frame, before its NMI-less VBL work): the commands the game wrote since the last call
; (snd_ring) each run the driver's IRQ handler ($0038, TOKEN as the return address), then the frame's ticks run its
; main loop once each ($0186 to the loop's head $0169, the hook snd_hook): TICKS_FX (16.16) a frame; while bit 6 of the
; slot $2000 is set the loop passes run instead of the ticks (X0169_r, at most SND_MAX_FAST a frame).  tools/sound.py
; TickBoard + YM are the same in Python (tools/sound_test.py compares).
;
; The driver's registers between runs: snd_regs (d0-d4, d6, a2, a5: z80x.FAST's map); a6 = snd_g + $8000 (its 64 KB,
; signed offsets: $8000-$FFFF below), a4 = snd_dispatch_sw.  The main program's registers are saved around a run.

SND_TICKS_FX = 945000			; (tools/sound.py TICKS_FX: 14.42 ticks an arcade frame)
SND_MAX_FAST = 64			; (sound.py MAX_FAST)
SND_TOKEN = $FEFF			; $FFFE on the Z80 stack, byte swapped (sound.py TOKEN)
SND_LOOP_SW = $6901			; $0169, byte swapped
G_SND = snd_g+$8000

	section text,code

snd_init:
	movem.l	d0-d7/a0-a6,-(sp)
	clr.b	snd_tail
	clr.l	snd_acc
	st	snd_dirty
	clr.b	snd_env
	clr.b	snd_busy
	clr.b	snd_status
	clr.b	snd_tm
	clr.b	snd_ayr
	clr.b	snd_addr
	lea	snd_ym_cache,a0
	moveq	#16-1,d0
.y:	move.b	#$FF,(a0)+
	dbf	d0,.y
	lea	snd_ay,a0
	moveq	#16/4-1,d0
.a:	clr.l	(a0)+
	dbf	d0,.a
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
snd_hook:				; (d7 = the pc: only the loop's head is a hook; the resume address is on the stack)
	tst.b	snd_tm			; the frame's ticks: from the hook on (no register save between them)
	beq.s	snd_back
	tst.w	snd_n
	beq.s	snd_back		; (no ticks left)
	btst	#6,G_SND+$2000		; the slot $2000's bit 6: loop passes at once instead of the ticks
	beq.s	.tick
	tst.w	snd_fast
	beq.s	snd_back		; (the frame's time is spent)
	subq.w	#1,snd_fast
	rts				; (the pass: the resume address)
.tick:	subq.w	#1,snd_n
	addq.l	#4,sp			; (the resume address dropped)
	jmp	X0186
snd_first:				; (the first step of the frame's ticks: as the hook, entered from snd_run)
	tst.w	snd_n
	beq.s	snd_back
	btst	#6,G_SND+$2000
	beq.s	.tick
	tst.w	snd_fast
	beq.s	snd_back
	subq.w	#1,snd_fast
	jmp	X0169_r
.tick:	subq.w	#1,snd_n
	jmp	X0186
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
	move.b	(a0,d0.w),snd_zlatch
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
	move.w	#SND_MAX_FAST,snd_fast
	st	snd_tm
	move.l	#snd_first,snd_entry
	bsr	snd_run
	clr.b	snd_tm
	tst.b	snd_busy		; the i8039's effect: the frames left
	beq.s	.nb
	subq.b	#1,snd_busy
	bne.s	.nb
	clr.b	snd_status
.nb:	bsr	snd_ym
	ifnd SIM
	bsr	snd_dma_fill
	endc
	movem.l	(sp)+,d0-d7/a0-a6
	rts

; The write hooks of the translation (bsr after the store; d0.b = A; every register kept but d7 / a0 / a1 / d5).
; snd_ay_addr ($4000): the AY's register address; snd_ayr ($4001's value: the register, port A = the i8039's status).
snd_ay_addr:
	moveq	#15,d7
	and.b	d0,d7
	move.b	d7,snd_addr
	cmp.b	#14,d7
	beq.s	.st
	lea	snd_ay,a0
	move.b	(a0,d7.w),snd_ayr
	rts
.st:	move.b	snd_status,snd_ayr	; (port A: the i8039's status)
	rts
snd_ay_data:				; ($4002)
	moveq	#0,d7
	move.b	snd_addr,d7
	lea	snd_ay,a0
	move.b	d0,(a0,d7.w)
	st	snd_dirty
	cmp.b	#14,d7
	beq.s	.x			; (port A reads the status whatever is written)
	move.b	d0,snd_ayr
	cmp.b	#13,d7			; (the envelope's shape: written, the YM's too)
	bne.s	.x
	st	snd_env
.x:	rts
snd_latch2_w:				; ($5000: the i8039's latch)
	move.b	d0,snd_latch2
	rts

; snd_effect ($6000, the i8039's IRQ): its effect snd_latch2 & 15 from the start (0 and 9-15: silence); status 1 for
; the frames of the commands 5-8.  Keeps every register but d7 / a0 / a1.
snd_effect:
	movem.l	d0-d1,-(sp)
	addq.w	#1,snd_effects
	moveq	#15,d0
	and.b	snd_latch2,d0
	lea	snd_busy_tab,a0
	move.b	(a0,d0.w),snd_busy
	sne	d1
	and.b	#1,d1
	move.b	d1,snd_status
	lsl.w	#3,d0
	lea	snd_dac_tab,a0
	movem.l	(a0,d0.w),d0-d1		; offset, length
	add.l	#snd_dac,d0
	move.l	d0,snd_v
	add.l	d0,d1
	move.l	d1,snd_v+4
	movem.l	(sp)+,d0-d1
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

; snd_ym: the YM's registers from the AY (tools/sound.py YM): the channels' periods x 2000000 / 1789773, the noise and
; envelope periods too, volumes and the mixer ($C0 added: the STE's ports A and B stay outputs) as they are; only the
; changed registers are written (the shape when the AY's was written).
snd_ym:
	tst.b	snd_dirty		; (no AY register written: the YM's stay)
	beq	.yout
	clr.b	snd_dirty
	lea	snd_ay,a0
	lea	snd_ym_new,a2
	moveq	#2,d5			; the channels' periods
.pd:	move.w	d5,d1
	add.w	d1,d1
	moveq	#0,d2
	move.b	1(a0,d1.w),d2
	lsl.w	#8,d2
	move.b	(a0,d1.w),d2
	and.w	#$0FFF,d2
	bsr	snd_scale
	cmp.l	#$0FFF,d2
	bls.s	.t1
	move.w	#$0FFF,d2
.t1:	move.b	d2,(a2,d1.w)
	lsr.w	#8,d2
	move.b	d2,1(a2,d1.w)
	move.b	8(a0,d5.w),d1		; volume
	and.b	#$1F,d1
	move.b	d1,8(a2,d5.w)
	dbf	d5,.pd
	moveq	#0,d2			; noise period
	move.b	6(a0),d2
	and.w	#$1F,d2
	bsr	snd_scale
	cmp.l	#31,d2
	bls.s	.n1
	moveq	#31,d2
.n1:	move.b	d2,6(a2)
	move.b	7(a0),d1		; mixer
	and.b	#$3F,d1
	or.b	#$C0,d1
	move.b	d1,7(a2)
	moveq	#0,d2			; envelope period
	move.b	12(a0),d2
	lsl.w	#8,d2
	move.b	11(a0),d2
	bsr	snd_scale
	cmp.l	#$FFFF,d2
	bls.s	.e1
	move.w	#$FFFF,d2
.e1:	move.b	d2,11(a2)
	lsr.w	#8,d2
	move.b	d2,12(a2)
	move.b	13(a0),13(a2)
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
.yout:	clr.b	snd_env
	rts
.shape:	tst.b	snd_env
	beq.s	.wn
	move.b	13(a2),d1
	move.b	d1,(a1,d0.w)
	ifnd SIM
	move.b	d0,$ffff8800.w
	move.b	d1,$ffff8802.w
	endc
	addq.w	#1,snd_ym_writes
	bra.s	.wn

snd_scale:				; d2.w = an AY period -> d2.l the YM's (x 2000000 / 1789773: p + p * 7698 / 65536)
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
; The sound Z80's 64 KB (a6 = its address 0, signed offsets): $8000-$FFFF first, then the ROM at $0000-$0FFF, the
; RAM at $2000-$23FF (and the translation's IY / F' words at $27F0).
	cnop	0,4
snd_g:		dcb.b	$8000,0
		incbin	"snd.rom"
		dcb.b	$7000,0

	section bss,bss
	even
snd_regs:	ds.l	8		; d0-d4, d6, a2, a5 between runs
snd_v:		ds.l	2		; the effect: the next byte, the end
snd_wp:		ds.w	1
snd_ring_buf:	ds.b	SND_RING
snd_entry:	ds.l	1
snd_sp0:	ds.l	1
snd_acc:	ds.l	1
snd_n:		ds.w	1
snd_fast:	ds.w	1
snd_effects:	ds.w	1
snd_ym_writes:	ds.w	1
snd_ay:		ds.b	16		; the AY's registers
snd_ym_new:	ds.b	16
snd_ym_cache:	ds.b	16
snd_tail:	ds.b	1
snd_zlatch:	ds.b	1		; the Z80's command latch ($3000)
snd_latch2:	ds.b	1		; the i8039's latch ($5000)
snd_dirty:	ds.b	1
snd_env:	ds.b	1		; the envelope's shape written this frame
snd_addr:	ds.b	1		; the AY's register address
snd_ayr:	ds.b	1		; the AY's data read ($4001)
snd_busy:	ds.b	1		; frames of an effect (5-8) left
snd_status:	ds.b	1		; the i8039's status (port A bits 2-0)
snd_tm:		ds.b	1		; the frame's ticks are running (the hook goes on)
	even
