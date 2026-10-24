; ------------------------------------------------------------------------------
; Sound effects on the YM2149: the sound driver's effects (audio ROM) as register streams, tools/sound_sfx.py.
;
; The driver: four IRQs an arcade frame; each reads the latch (0076: a new command != $FF starts its effect in its
; slot, 092E; command 0 / $1C-$1F clear every slot, 00E6), then per chip (two YM2203) steps only the highest active of
; its four slots (0537 / 0564) and outputs that slot's SSG registers, or the idle values (0955 / 0A27).  An effect's
; output at step n and phase (the IRQ counter $4000 & 3 when the effect steps: 05F8 works every 4th) is in sfx_data.s:
; a table per phase of offsets into sfx_dict (every distinct output once).  sfx_irq is one IRQ of that; sfx_tick runs
; the four of an arcade tick and writes the YM2149, which plays one chip: the one whose effect started last (the STE
; has 3 channels, the arcade 2 x 3); the music (music.s) takes the channels the effect does not sound on.  The
; reference is tools/sound_sfx.py's Decoded (the same outputs from runs and exceptions), step for step.
; ------------------------------------------------------------------------------

; a slot (2 chips x 4)
SL_ENT = 0				; .l  its sfx_table entry, 0: inactive
SL_OUTP = 4				; .l  the output of the last step (in sfx_dict)
SL_REGP = 8				; .l  the last step's output at phase 0 (a slot started, not stepped, outputs it)
SL_N = 12				; .w  steps done (the stream index of the next one)
SL_SERIAL = 14				; .w  the start order (the YM plays the chip whose effect started last)
SL_PHASE = 16				; .b
SL_IDX = 17				; .b  the slot in its chip (its bit in sfx_act)
SL_SIZE = 18

; sfx_table entries (sfx_data.s)
SE_CHIP = 0				; .b  0 / 1, $FE: clear every slot, $FF: nothing
SE_SLOT = 1
SE_LENGTH = 2				; .w
SE_LOOP = 4				; .w  -1: none
SE_TAB = 8				; .l x 4  per phase: the steps' outputs (offsets in sfx_dict, words)

LATCH = G_Z80-$3800			; C800 (the main CPU's sound latch)

; Chip \1 in an IRQ: its highest active slot (sfx_act: a bit per active slot) steps; its output (or the next active
; slot's, when it ended; or the idle values) is the chip's (sfx_chip_out, sfx_chip_slot).
sfx_chip	macro
	moveq	#0,d0
	move.b	sfx_act+\1,d0
	beq.s	.idle\@
	lea	sfx_hioff,a1
	moveq	#0,d1
	move.b	(a1,d0.w),d1
	lea	sfx_slots+\1*4*SL_SIZE,a0
	add.w	d1,a0
	move.b	sfx_count,d0		; phase = (count - n) & 3 (a paused slot resumes with another phase)
	sub.b	SL_N+1(a0),d0
	and.b	#3,d0
	move.b	d0,SL_PHASE(a0)
	bsr	sfx_step
	bne.s	.out\@
	clr.l	SL_ENT(a0)		; ended
	move.b	SL_IDX(a0),d0
	bclr	d0,sfx_act+\1
	moveq	#0,d0
	move.b	sfx_act+\1,d0
	beq.s	.idle\@
	lea	sfx_hioff,a1
	moveq	#0,d1
	move.b	(a1,d0.w),d1
	lea	sfx_slots+\1*4*SL_SIZE,a0
	add.w	d1,a0
.out\@:	move.l	SL_OUTP(a0),a1
	tst.w	SL_N(a0)
	bne.s	.set\@
	move.l	SL_REGP(a0),a1		; (started, not stepped: the driver outputs the slot's old registers)
	bra.s	.set\@
.idle\@:	lea	sfx_idle+11*\1,a1
	sub.l	a0,a0			; (no slot: serial 0)
.set\@:	move.l	a1,sfx_chip_out+4*\1
	move.l	a0,sfx_chip_slot+4*\1
	endm

; one IRQ of the driver; uses d0-d7 / a0-a4
sfx_irq:
	addq.b	#1,sfx_count
	and.b	#3,sfx_count
	move.b	LATCH,d0
	cmp.b	sfx_last,d0
	beq	.stepping
	move.b	d0,sfx_last
	cmp.b	#$FF,d0
	beq	.stepping
	and.w	#$3F,d0
	mulu	#SFX_ENTRY,d0
	lea	sfx_table,a1
	add.w	d0,a1
	move.b	SE_CHIP(a1),d1
	cmp.b	#$FE,d1
	beq.s	.clear
	bhi	.stepping
	ext.w	d1			; the slot: (chip * 4 + slot) * SL_SIZE
	moveq	#0,d2
	move.b	SE_SLOT(a1),d2
	lea	sfx_act,a0		; (active: its bit in the chip's mask)
	bset	d2,(a0,d1.w)
	lsl.w	#2,d1
	add.b	d2,d1
	mulu	#SL_SIZE,d1
	lea	sfx_slots,a0
	add.w	d1,a0
	move.b	d2,SL_IDX(a0)
	move.l	a1,SL_ENT(a0)
	clr.w	SL_N(a0)
	move.b	sfx_count,SL_PHASE(a0)
	addq.w	#1,sfx_serial
	move.w	sfx_serial,SL_SERIAL(a0)
	bra	.stepping
.clear:
	lea	sfx_slots,a0
	moveq	#8-1,d1
.cl:	clr.l	SL_ENT(a0)
	lea	SL_SIZE(a0),a0
	dbf	d1,.cl
	clr.w	sfx_act
.stepping:
	sfx_chip	0
	sfx_chip	1
	rts

; one step of slot a0 (its phase in SL_PHASE): Z set when it ended.  Uses d0 / d2 / a1-a2.
sfx_step:
	move.l	SL_ENT(a0),a1
	move.w	SL_N(a0),d2
	cmp.w	SE_LENGTH(a1),d2
	blo.s	.in
	move.w	SE_LOOP(a1),d2		; at the end: the loop, or the end
	bmi.s	.ended
.in:	add.w	d2,d2
	moveq	#0,d0
	move.b	SL_PHASE(a0),d0
	lsl.w	#2,d0
	move.l	SE_TAB(a1,d0.w),a2	; the output at this index and phase
	move.w	(a2,d2.w),d0
	lea	sfx_dict,a2
	add.w	d0,a2
	move.l	a2,SL_OUTP(a0)
	move.l	SE_TAB(a1),a2		; and at phase 0
	move.w	(a2,d2.w),d0
	lea	sfx_dict,a2
	add.w	d0,a2
	move.l	a2,SL_REGP(a0)
	lsr.w	#1,d2
	addq.w	#1,d2
	move.w	d2,SL_N(a0)
	moveq	#1,d0			; (Z clear: it goes on)
	rts
.ended:
	moveq	#0,d0
	rts

; The four IRQs of an arcade tick and the music's tick, then the YM2149: the chip whose shown effect started last (or
; the first chip's idle values) with the music on the channels it leaves, the registers that changed.  Uses d0-d7 /
; a0-a4.
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
	move.l	a1,-(sp)
	bsr	mus_tick
	move.l	(sp)+,a1
	bsr	mus_mix
	lea	mus_regs,a1
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
	clr.w	sfx_act
	lea	sfx_slots,a0		; (a slot never used: its old registers are 0, sfx_dict's first output)
	moveq	#8-1,d0
.r:	move.l	#sfx_dict,SL_REGP(a0)
	lea	SL_SIZE(a0),a0
	dbf	d0,.r
	lea	sfx_ym,a0
	moveq	#11-1,d0
.i:	st	(a0)+
	dbf	d0,.i
	rts

sfx_hioff:				; the highest bit of a slot mask (1-15) * SL_SIZE
	dc.b	0,0*SL_SIZE,1*SL_SIZE,1*SL_SIZE,2*SL_SIZE,2*SL_SIZE,2*SL_SIZE,2*SL_SIZE
	dcb.b	8,3*SL_SIZE
	even

	include	"sfx_data.s"

	section bss,bss
sfx_slots:	ds.b	8*SL_SIZE
sfx_chip_out:	ds.l	2		; per chip: its output registers this IRQ
sfx_chip_slot:	ds.l	2		; per chip: the slot shown, 0: idle
sfx_serial:	ds.w	1
sfx_act:	ds.b	2		; per chip: its active slots (bit n: slot n)
sfx_last:	ds.b	1		; the driver's $4001: the last latch value seen (0 at boot)
sfx_count:	ds.b	1		; the driver's $4000 & 3
sfx_ym:		ds.b	11		; the YM2149's registers 0-10 as written
	even
	section text,code
