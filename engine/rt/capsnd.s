; ------------------------------------------------------------------------------
; Capcom's sound driver (Commando family: Gun.Smoke, 1943) on the YM2149: its effects and music recorded by
; engine/capsnd.py (FxPlayer, MusPlayer, Mixer, combine and Ste there are this code in Python, step for step).
; Generalised from games/commando/src/sfx.s and music.s.
;
; The game defines CS_LATCH (the address of the main CPU's sound latch) and includes this file and its data
; (cs_data.s, generated: CS_FXSLOTS, CS_KILL, cs_cmds, cs_idle, the streams); it calls cs_init once and cs_tick once an
; arcade tick (the four IRQs of the driver, the music, the YM's registers that changed).  Uses d0-d7 / a0-a4.
;
; Effects: per chip CS_FXSLOTS slots; a command (re)starts its effect in its slot, a stop clears the slots of its
; mask; each IRQ steps the highest active slot of each chip (its output after n steps is in the data: phase 0 as
; runs, phases 1-3 (the IRQ counter & 3) as exceptions) and shows it; with CS_KILL the lower slots under it end
; unless their kill byte (a twelfth value of the stream, kept by the slot once $FF) is $FF.  The YM plays the chip
; whose shown effect started last.
; Music: four slots of six channels; a tune command starts its slot, a stop clears the slots of its mask; the highest
; slot that plays steps its channels' streams (a tune that ends plays its tail while no other plays); the loudest
; channels take the YM channels the effect leaves.
; ------------------------------------------------------------------------------

	include	"capsnd_core.s"

; a command (cs_cmds, 10 bytes)
CC_KIND = 0				; .b  0 nothing, 1 effect, 2 tune, 3 stop
CC_SLOT = 1				; .b  effect: chip * 8 + slot; tune: its slot
CC_FXCLR = 2				; .w  stop: the effect slots it clears (bit chip * 8 + slot)
CC_MUCLR = 4				; .b  stop: the music slots it clears
CC_ENT = 6				; .l  the effect or the tune
CC_SIZE = 10

; a music slot
MS_STATE = 0				; .b  0: empty, 1: playing, 2: its tail
MS_N = 2				; .w  ticks played
MS_END = 4				; .w  the tick its tune ends at, 0: it loops
MS_CH = 6
MS_SIZE = MS_CH+6*CH_SIZE

; a tune (cs_muNN)
ME_END = 0				; .w
ME_START = 2				; .l x 6
ME_LOOP = 26				; .l x 6, 0: none

; the command of the latch value d0 (not $FF) -> a1 its cs_cmds entry
cs_cmd	macro
	and.w	#$3F,d0
	mulu	#CC_SIZE,d0
	lea	cs_cmds,a1
	add.w	d0,a1
	endm

; ---------------------------------------------------------------- the effects: one IRQ of the driver
cs_irq:
	addq.b	#1,cs_count
	and.b	#3,cs_count
	move.b	CS_LATCH,d0
	cmp.b	cs_last,d0
	beq	.stepping
	move.b	d0,cs_last
	cmp.b	#$FF,d0
	beq	.stepping
	cs_cmd
	move.b	CC_KIND(a1),d1
	cmp.b	#1,d1
	beq.s	.start
	cmp.b	#3,d1
	bne.s	.stepping
	move.w	CC_FXCLR(a1),d1		; a stop: the slots of its mask (low byte chip 0's, high byte chip 1's)
	not.w	d1
	and.b	d1,cs_act
	lsr.w	#8,d1
	and.b	d1,cs_act+1
	bra.s	.stepping
.start:	moveq	#0,d1
	move.b	CC_SLOT(a1),d1		; chip * 8 + slot
	moveq	#7,d2
	and.w	d1,d2			; the slot
	lsr.w	#3,d1			; the chip
	lea	cs_act,a0
	bset	d2,(a0,d1.w)
	add.w	d1,d1
	add.w	d1,d1
	lea	cs_chips,a0
	move.l	(a0,d1.w),a0
	lsl.w	#6,d2			; (SL_SIZE)
	add.w	d2,a0
	move.l	CC_ENT(a1),a1
	move.l	a1,SL_ENT(a0)
	move.l	SE_RUNS(a1),SL_POS(a0)
	clr.w	SL_N(a0)
	clr.w	SL_T(a0)
	clr.b	SL_LEFT(a0)
	move.b	cs_count,SL_PHASE(a0)
	st	SL_EXCPH(a0)
	addq.w	#1,cs_serial
	move.w	cs_serial,SL_SERIAL(a0)
.stepping:
	lea	cs_act,a4
	moveq	#0,d7			; the chip
.chip:
	bsr	cs_top
	beq.s	.idle
	move.b	cs_count,d0		; phase = (count - n) & 3 (a paused slot resumes with another phase)
	sub.b	SL_N+1(a0),d0
	and.b	#3,d0
	move.b	d0,SL_PHASE(a0)
	bsr	cs_step
	beq.s	.ended
	cmp.b	#$FF,SL_OUT+11(a0)
	bne.s	.shown
	lea	cs_keep,a2
	bset	d6,(a2,d7.w)
	bra.s	.shown
.ended:	bclr	d6,(a4,d7.w)
	bsr	cs_top
	beq.s	.idle
.shown:
	ifne	CS_KILL
	moveq	#-1,d0			; the lower slots end unless their kill byte is $FF (cs_keep)
	lsl.b	d6,d0
	lea	cs_keep,a2
	or.b	(a2,d7.w),d0
	and.b	d0,(a4,d7.w)
	endc
	lea	SL_OUT(a0),a1
	tst.w	SL_N(a0)
	bne.s	.set
	lea	SL_REGS(a0),a1		; (started, not stepped: the driver outputs the slot's old registers)
	bra.s	.set
.idle:
	lea	cs_idle,a1
	tst.w	d7
	beq.s	.idle0
	lea	11(a1),a1
.idle0:	sub.l	a0,a0			; (no slot: serial 0)
.set:
	move.w	d7,d0
	lsl.w	#2,d0
	lea	cs_chip_out,a2
	move.l	a1,(a2,d0.w)
	lea	cs_chip_slot,a2
	move.l	a0,(a2,d0.w)
	addq.w	#1,d7
	cmp.w	#2,d7
	blo	.chip
	rts

; a0 = the highest active slot of chip d7 (a4: cs_act), d6 its number (Z clear), or Z set.  Uses d0.
	if CS_FXSLOTS>5
	fail	"cs_hibit has 32 entries: at most 5 effect slots a chip"
	endc
cs_top:
	moveq	#0,d0
	move.b	(a4,d7.w),d0
	move.b	cs_hibit(pc,d0.w),d6
	bmi.s	.none
	ext.w	d6
	move.w	d7,d0
	lsl.w	#2,d0
	lea	cs_chips,a0
	move.l	(a0,d0.w),a0
	move.w	d6,d0			; + slot * 64
	lsl.w	#6,d0
	add.w	d0,a0
	moveq	#1,d0			; (Z clear)
	rts
.none:	moveq	#0,d0			; (Z set)
	rts
cs_hibit:				; the highest set bit of 0-31, -1 for 0
	dc.b	-1,0,1,1,2,2,2,2
	dcb.b	8,3
	dcb.b	16,4
	even

; ---------------------------------------------------------------- the music: a tick -> cs_vals
cs_mus_tick:
	move.b	CS_LATCH,d0
	cmp.b	cs_mlast,d0
	beq	.run
	move.b	d0,cs_mlast
	cmp.b	#$FF,d0
	beq	.run
	cs_cmd
	move.b	CC_KIND(a1),d1
	cmp.b	#2,d1
	beq.s	.start
	cmp.b	#3,d1
	bne.s	.run
	move.b	CC_MUCLR(a1),d1		; a stop
	lea	cs_mslots,a0
	moveq	#0,d2
.st:	btst	d2,d1
	beq.s	.st1
	clr.b	MS_STATE(a0)
.st1:	lea	MS_SIZE(a0),a0
	addq.w	#1,d2
	cmp.w	#4,d2
	blo.s	.st
	bra.s	.run
.start:	moveq	#0,d1
	move.b	CC_SLOT(a1),d1
	mulu	#MS_SIZE,d1
	lea	cs_mslots,a0
	add.w	d1,a0
	move.l	CC_ENT(a1),a1
	move.b	#1,MS_STATE(a0)
	clr.w	MS_N(a0)
	move.w	ME_END(a1),MS_END(a0)
	lea	MS_CH(a0),a2
	lea	ME_START(a1),a3
	moveq	#6-1,d1
.ci:	move.l	(a3),CH_POS(a2)
	move.l	ME_LOOP-ME_START(a3),CH_LOOP(a2)
	clr.l	CH_PER(a2)		; (period, hold, volume)
	addq.l	#4,a3
	lea	CH_SIZE(a2),a2
	dbf	d1,.ci
.run:
	lea	cs_mslots+3*MS_SIZE,a0	; the highest slot that plays, else the highest tail
	moveq	#4-1,d1
.t1:	cmp.b	#1,MS_STATE(a0)
	beq.s	.top
	lea	-MS_SIZE(a0),a0
	dbf	d1,.t1
	lea	cs_mslots+3*MS_SIZE,a0
	moveq	#4-1,d1
.t2:	tst.b	MS_STATE(a0)
	bne.s	.top
	lea	-MS_SIZE(a0),a0
	dbf	d1,.t2
	lea	cs_vals,a1		; no music
	moveq	#6-1,d1
.z:	clr.l	(a1)+
	dbf	d1,.z
	rts
.top:	lea	MS_CH(a0),a2
	lea	cs_vals,a1
	moveq	#0,d4			; (any volume)
	moveq	#6-1,d3
.ch:	bsr	cs_chan
	move.w	d0,(a1)+
	move.w	d1,(a1)+
	or.b	d1,d4
	lea	CH_SIZE(a2),a2
	dbf	d3,.ch
	addq.w	#1,MS_N(a0)
	cmp.b	#2,MS_STATE(a0)
	bne.s	.playing
	tst.b	d4
	bne.s	.done
	clr.b	MS_STATE(a0)		; the tail has died away
.done:	rts
.playing:
	move.w	MS_END(a0),d0
	beq.s	.others
	cmp.w	MS_N(a0),d0
	bne.s	.others
	move.b	#2,MS_STATE(a0)		; the tune ended: its tail
	rts
.others:
	lea	cs_mslots,a1		; a tune that plays ends the tails
	moveq	#4-1,d1
.o:	cmp.b	#2,MS_STATE(a1)
	bne.s	.o1
	clr.b	MS_STATE(a1)
.o1:	lea	MS_SIZE(a1),a1
	dbf	d1,.o
	rts

cs_chips:
	dc.l	cs_slots,cs_slots+CS_FXSLOTS*SL_SIZE	; each chip's first slot
cs_latch_addr:
	dc.l	CS_LATCH		; (for engine/capsnd_test.py)

; ---------------------------------------------------------------- a tick
; The four IRQs of the effects, the chip whose shown effect started last (or the first chip's idle values), the music
; on the channels it leaves, the YM's registers that changed (no interrupt handler may write the YM meanwhile).
cs_tick:
	bsr	cs_irq
	bsr	cs_irq
	bsr	cs_irq
	bsr	cs_irq
	moveq	#0,d0			; the serials of the two chips' shown slots
	move.l	cs_chip_slot,d1
	beq.s	.s0
	move.l	d1,a0
	move.w	SL_SERIAL(a0),d0
.s0:	moveq	#0,d2
	move.l	cs_chip_slot+4,d1
	beq.s	.s1
	move.l	d1,a0
	move.w	SL_SERIAL(a0),d2
.s1:	move.l	cs_chip_out,a1
	cmp.w	d0,d2
	bls.s	.chosen
	move.l	cs_chip_out+4,a1
.chosen:
	move.l	a1,-(sp)
	bsr	cs_mus_tick
	move.l	(sp)+,a1
	bsr	cs_mix
	lea	cs_regs,a1
	lea	cs_ym,a2
	moveq	#0,d1
.w:	move.b	(a1)+,d0
	cmp.b	(a2),d0
	beq.s	.same
	move.b	d0,(a2)
	move.b	d1,$ffff8800.w
	move.b	d0,$ffff8802.w
.same:	addq.l	#1,a2
	addq.b	#1,d1
	cmp.b	#11,d1
	blo.s	.w
	rts

; At the start: no effects, no music; the YM's shadow made different from everything (the first tick writes all).
cs_init:
	lea	cs_bss,a0
	move.w	#cs_bss_end-cs_bss-1,d0
.c:	clr.b	(a0)+
	dbf	d0,.c
	lea	cs_ym,a0
	moveq	#11-1,d0
.i:	st	(a0)+
	dbf	d0,.i
	bra	cs_mix_init

	section bss,bss
	even
cs_bss:
cs_slots:	ds.b	2*CS_FXSLOTS*SL_SIZE
cs_mslots:	ds.b	4*MS_SIZE
cs_chip_out:	ds.l	2		; per chip: its output registers this IRQ
cs_chip_slot:	ds.l	2		; per chip: the slot shown, 0: idle
cs_serial:	ds.w	1
cs_ym:		ds.b	12		; the YM2149's registers 0-10 as written
cs_act:		ds.b	2		; per chip: its active effect slots (bits)
cs_keep:	ds.b	2		; per chip: the slots whose kill byte is $FF
cs_last:	ds.b	1		; the driver's last latch value (0 at boot)
cs_mlast:	ds.b	1		; the same for the music's tick
cs_count:	ds.b	1		; the driver's IRQ counter & 3
	even
cs_bss_end:
	section text,code
