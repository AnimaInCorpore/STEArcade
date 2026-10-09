; ------------------------------------------------------------------------------
; Sound effects on the YM2149: the sound driver's effects (audio ROM) as register streams, tools/sound_sfx.py.
;
; The driver: four IRQs an arcade frame; each reads the latch (0076: a new command != $FF starts its effect in its
; slot, 092E; command 0 / $1C-$1F clear every slot, 00E6), then per chip (two YM2203) steps only the highest active of
; its four slots (0537 / 0564) and outputs that slot's SSG registers, or the idle values (0955 / 0A27).  An effect's
; output after n steps is in sfx_data.s: phase 0 as runs, phases 1-3 (the IRQ counter $4000 & 3 when the effect
; steps: 05F8 works every 4th) as exceptions to it.  sfx_irq is one IRQ of that; sfx_tick runs the four of an arcade
; tick and writes the YM2149, which plays one chip: the one whose effect started last (the STE has 3 channels, the
; arcade 2 x 3).  The music (FM) is not played.  The decoder is tools/sound_sfx.py's Decoded, step for step.
; ------------------------------------------------------------------------------

; a slot (2 chips x 4)
SL_ENT = 0				; .l  its sfx_table entry, 0: inactive
SL_POS = 4				; .l  the next run record
SL_LOOPPOS = 8				; .l  the run record of the loop's index
SL_EXC = 12				; .l  the next exception of its phase
SL_N = 16				; .w  steps done (the stream index of the next one)
SL_SERIAL = 18				; .w  the start order (the YM plays the chip whose effect started last)
SL_LEFT = 20				; .b  steps left in the current run
SL_PHASE = 21				; .b
SL_EXCPH = 22				; .b  the phase SL_EXC belongs to, $FF: none
SL_REGS = 23				; 11 bytes: the registers of phase 0
SL_OUT = 34				; 11 bytes: the output of the last step
SL_SIZE = 46

; sfx_table entries (sfx_data.s)
SE_CHIP = 0				; .b  0 / 1, $FE: clear every slot, $FF: nothing
SE_SLOT = 1
SE_LENGTH = 2				; .w
SE_LOOP = 4				; .w  -1: none
SE_RUNS = 6				; .l
SE_EXC = 10				; .l x 3

LATCH = G_Z80-$3800			; C800 (the main CPU's sound latch)

; one IRQ of the driver; uses d0-d7 / a0-a4
sfx_irq:
	addq.b	#1,sfx_count
	and.b	#3,sfx_count
	move.b	LATCH,d0
	cmp.b	sfx_last,d0
	beq.s	.stepping
	move.b	d0,sfx_last
	cmp.b	#$FF,d0
	beq.s	.stepping
	and.w	#$3F,d0
	mulu	#SFX_ENTRY,d0
	lea	sfx_table,a1
	add.w	d0,a1
	move.b	SE_CHIP(a1),d1
	cmp.b	#$FE,d1
	beq.s	.clear
	bhi.s	.stepping
	ext.w	d1			; the slot: (chip * 4 + slot) * SL_SIZE
	lsl.w	#2,d1
	add.b	SE_SLOT(a1),d1
	mulu	#SL_SIZE,d1
	lea	sfx_slots,a0
	add.w	d1,a0
	move.l	a1,SL_ENT(a0)
	move.l	SE_RUNS(a1),SL_POS(a0)
	clr.w	SL_N(a0)
	clr.b	SL_LEFT(a0)
	move.b	sfx_count,SL_PHASE(a0)
	st	SL_EXCPH(a0)
	addq.w	#1,sfx_serial
	move.w	sfx_serial,SL_SERIAL(a0)
	bra.s	.stepping
.clear:
	lea	sfx_slots,a0
	moveq	#8-1,d1
.cl:	clr.l	SL_ENT(a0)
	lea	SL_SIZE(a0),a0
	dbf	d1,.cl
.stepping:
	moveq	#0,d7			; the chip
.chip:
	bsr	sfx_top
	beq.s	.idle
	move.b	sfx_count,d0		; phase = (count - n) & 3 (a paused slot resumes with another phase)
	sub.b	SL_N+1(a0),d0
	and.b	#3,d0
	move.b	d0,SL_PHASE(a0)
	bsr	sfx_step
	bne.s	.out
	clr.l	SL_ENT(a0)		; ended
	bsr	sfx_top
	beq.s	.idle
.out:
	lea	SL_OUT(a0),a1
	tst.w	SL_N(a0)
	bne.s	.set
	lea	SL_REGS(a0),a1		; (started, not stepped: the driver outputs the slot's old registers)
	bra.s	.set
.idle:
	lea	sfx_idle,a1
	move.w	d7,d0
	mulu	#11,d0
	add.w	d0,a1
	sub.l	a0,a0			; (no slot: serial 0)
.set:
	move.w	d7,d0
	lsl.w	#2,d0
	lea	sfx_chip_out,a2
	move.l	a1,(a2,d0.w)
	lea	sfx_chip_slot,a2
	move.l	a0,(a2,d0.w)
	addq.w	#1,d7
	cmp.w	#2,d7
	blo.s	.chip
	rts

; a0 = the highest active slot of chip d7 (Z clear), or Z set
sfx_top:
	move.w	d7,d0
	mulu	#4*SL_SIZE,d0
	lea	sfx_slots+3*SL_SIZE,a0
	add.w	d0,a0
	moveq	#4-1,d0
.t:	tst.l	SL_ENT(a0)
	bne.s	.found
	lea	-SL_SIZE(a0),a0
	dbf	d0,.t
	moveq	#0,d0			; (Z set)
	rts
.found:
	moveq	#1,d0			; (Z clear)
	rts

; one step of slot a0: Z set when it ended.  Uses d0-d6 / a1-a4.
sfx_step:
	move.l	SL_ENT(a0),a1
	move.w	SL_N(a0),d2
	cmp.w	SE_LENGTH(a1),d2
	blo.s	.in
	move.w	SE_LOOP(a1),d2		; at the end: the loop, or the end
	bmi	.ended
	move.w	d2,SL_N(a0)
	move.l	SL_LOOPPOS(a0),SL_POS(a0)
	clr.b	SL_LEFT(a0)
	st	SL_EXCPH(a0)
.in:
	tst.b	SL_LEFT(a0)
	bne.s	.in_run
	cmp.w	SE_LOOP(a1),d2
	bne.s	.no_loop
	move.l	SL_POS(a0),SL_LOOPPOS(a0)
.no_loop:
	move.l	SL_POS(a0),a2		; a run record: steps, mask, the registers that change
	move.b	(a2)+,SL_LEFT(a0)
	move.b	(a2)+,d0
	lsl.w	#8,d0
	move.b	(a2)+,d0
	lea	SL_REGS(a0),a3
	moveq	#11-1,d1
.r:	lsr.w	#1,d0
	bcc.s	.r_keep
	move.b	(a2)+,(a3)
.r_keep:
	addq.l	#1,a3
	dbf	d1,.r
	move.l	a2,SL_POS(a0)
.in_run:
	subq.b	#1,SL_LEFT(a0)
	move.b	SL_PHASE(a0),d3
	cmp.b	SL_EXCPH(a0),d3
	beq.s	.seeked
	bsr	sfx_seek
.seeked:
	lea	SL_REGS(a0),a2		; the output: phase 0's registers
	lea	SL_OUT(a0),a3
	moveq	#11-1,d1
.o:	move.b	(a2)+,(a3)+
	dbf	d1,.o
	tst.b	d3
	beq.s	.done
	move.l	SL_EXC(a0),a2		; this phase's exception at this index
	move.b	(a2),d0
	lsl.w	#8,d0
	move.b	1(a2),d0
	cmp.w	#$FFFF,d0
	beq.s	.done
	cmp.w	d2,d0
	bne.s	.done
	addq.l	#2,a2
	move.b	(a2)+,d0
	lsl.w	#8,d0
	move.b	(a2)+,d0
	lea	SL_OUT(a0),a3
	moveq	#11-1,d1
.x:	lsr.w	#1,d0
	bcc.s	.x_keep
	move.b	(a2)+,(a3)
.x_keep:
	addq.l	#1,a3
	dbf	d1,.x
	move.l	a2,SL_EXC(a0)
.done:
	addq.w	#1,d2
	move.w	d2,SL_N(a0)
	moveq	#1,d0			; (Z clear: it goes on)
	rts
.ended:
	moveq	#0,d0
	rts

; SL_EXC for SL_PHASE (d3) at index d2: the first exception at or after it.  Uses d0, d1, d4, a2.
sfx_seek:
	move.b	d3,SL_EXCPH(a0)
	tst.b	d3
	beq.s	.none
	moveq	#0,d0
	move.b	d3,d0
	lsl.w	#2,d0
	move.l	SE_EXC-4(a1,d0.w),a2
.s:	move.b	(a2),d0
	lsl.w	#8,d0
	move.b	1(a2),d0
	cmp.w	#$FFFF,d0
	beq.s	.at
	cmp.w	d2,d0
	bhs.s	.at
	move.b	2(a2),d0		; skip it: 4 + the bits of its mask
	lsl.w	#8,d0
	move.b	3(a2),d0
	addq.l	#4,a2
	moveq	#11-1,d1
.b:	lsr.w	#1,d0
	bcc.s	.b0
	addq.l	#1,a2
.b0:	dbf	d1,.b
	bra.s	.s
.at:	move.l	a2,SL_EXC(a0)
.none:
	rts

; The four IRQs of an arcade tick, then the YM2149: the chip whose shown effect started last (or the first chip's
; idle values), the registers that changed.  Uses d0-d7 / a0-a4.
sfx_tick:
	bsr	sfx_irq
	bsr	sfx_irq
	bsr	sfx_irq
	bsr	sfx_irq
	moveq	#0,d0			; the serials of the two chips' shown slots
	move.l	sfx_chip_slot,d1
	beq.s	.s0
	move.l	d1,a0
	move.w	SL_SERIAL(a0),d0
.s0:	moveq	#0,d2
	move.l	sfx_chip_slot+4,d1
	beq.s	.s1
	move.l	d1,a0
	move.w	SL_SERIAL(a0),d2
.s1:	move.l	sfx_chip_out,a1
	cmp.w	d0,d2
	bls.s	.chosen
	move.l	sfx_chip_out+4,a1
.chosen:
	lea	sfx_ym,a2
	moveq	#0,d1			; the register (no interrupt handler of the port writes the YM: no masking, which
					; would make the border events late)
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

; At the start: the YM's shadow made different from everything, so the first tick writes all eleven registers.
sfx_init:
	lea	sfx_ym,a0
	moveq	#11-1,d0
.i:	st	(a0)+
	dbf	d0,.i
	rts

	include	"sfx_data.s"

	section bss,bss
sfx_slots:	ds.b	8*SL_SIZE
sfx_chip_out:	ds.l	2		; per chip: its output registers this IRQ
sfx_chip_slot:	ds.l	2		; per chip: the slot shown, 0: idle
sfx_serial:	ds.w	1
sfx_last:	ds.b	1		; the driver's $4001: the last latch value seen (0 at boot)
sfx_count:	ds.b	1		; the driver's $4000 & 3
sfx_ym:		ds.b	11		; the YM2149's registers 0-10 as written
	even
	section text,code
