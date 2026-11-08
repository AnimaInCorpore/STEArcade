; The runtime of Rolling Thunder's translated main and sub CPU programs (included by rthunder.s): the CPUs' contexts, the
; schedule of one arcade frame (port_frame: tools/machine.py RthunderRule), the dispatcher, the I/O.
; (From Dragon Spirit's runtime, games/dspirit/src/core.s; this board has no MMU: the slots are fixed, only slot 3, the
; banked ROM window of $6000-$7FFF, changes.)
;
; main: DP = $56 (slot 2, `shared`), stack in slot 2, a4 = VB[0] (vram0); sub: DP = $16 (slot 0, `shared`), a4 = VB[1].
; a3 = VB[DPS], a4 = VB[A4SLOT], a2 = PB[7]; S = a5 - a3 (the stack lies in the DP's slot).
;
; The schedule.  Both CPUs take their IRQ at their idle point (cpu_irq_setup), then run in turns, the one with the
; counter $1604 != $1605 (cpu1 has counted a sub-step that cpu2 has not taken) first, else cpu2: a CPU runs until it
; is idle again (<cpu>_idle: its queues are empty), until it has written a semaphore byte (<cpu>_sem_yield, called from
; the translation after the store) or until a spin wait's branch is taken (<cpu>_spin_<pc>, hooks_<cpu>.s).  A CPU that
; gives up the CPU saves its registers in its context, a resume address (the label it goes on at) and returns to the
; scheduler; the 68000 stack holds nothing of the translated code at those points.

; ---- the context block (engine/m6809x.py) ----
PB = 0				; 8 longs: the 68000 address of the page in each slot
VB = 32				; 8 longs: PB - slot * $2000
TBL = 64			; 8 longs: the dispatcher's table of the page in each slot (bad_table: no code there)
PID = 96			; 8 words: the virtual page in each slot
CCHI = 112			; the CC byte's E F H I bits (6809 positions)
R_D0 = 116			; the registers while the CPU is not running: d0-d4 (5 longs)
R_A5 = 136
R_SR = 140
IRQV = 144			; the IRQ handler's label
IDLEPC = 148			; the idle point's 6809 pc
A4SLOT = 150			; the slot whose VB a4 holds, * 4
TABLES = 152			; the page tables of the dispatcher
IDLENEXT = 156			; the label the idle loop's BRA goes to
DPS = 168			; the direct page's slot * 4 (a3 = VB[DPS])
DPR = 170			; the DP register's value (a byte, in the word's low half)
R_RESUME = 172			; where the CPU goes on
RUNNING = 176			; byte: the CPU has not finished its frame
CTXSIZE = 178

	include	"gen_info.s"

	section text,code
; slot -> page, page -> memory: main {0 vram0, 1 vram1, 2 shared, 3 the bank, 4-7 rom_main}; sub {0 shared, 1 vram0,
; 2 vram1, 3 the bank, 4-7 rom_sub + $8000}
init_contexts:
	lea	ctx_main,a6
	move.l	#MAIN_IRQ_LABEL,IRQV(a6)
	move.w	#MAIN_IDLE_PC,IDLEPC(a6)
	move.w	#MAIN_A4SLOT*4,A4SLOT(a6)
	move.l	#main_page_tables,TABLES(a6)
	move.l	#MAIN_IDLE_NEXT,IDLENEXT(a6)
	move.w	#(MAIN_DP>>5)*4,DPS(a6)
	move.w	#MAIN_DP,DPR(a6)
	lea	main_map,a0
	bsr	set_map
	lea	ctx_sub,a6
	move.l	#SUB_IRQ_LABEL,IRQV(a6)
	move.w	#SUB_IDLE_PC,IDLEPC(a6)
	move.w	#SUB_A4SLOT*4,A4SLOT(a6)
	move.l	#sub_page_tables,TABLES(a6)
	move.l	#SUB_IDLE_NEXT,IDLENEXT(a6)
	move.w	#(SUB_DP>>5)*4,DPS(a6)
	move.w	#SUB_DP,DPR(a6)
	lea	sub_map,a0
	bsr	set_map
	rts
; a0 = 8 (page, address) pairs (word page, long base), a6 = the context
set_map:
	moveq	#0,d6			; slot * 4
.l:	move.l	(a0)+,d7
	move.l	(a0)+,d5
	bsr	slot_set
	addq.w	#4,d6
	cmp.w	#32,d6
	bne.s	.l
	rts
; d6.w = slot * 4, d7.w = the page, d5.l = its address: PID, PB, VB, TBL (d0-d4 a5 a6 kept; d5 a0 clobbered)
slot_set:
	move.l	d5,PB(a6,d6.w)
	sub.l	slot_offsets(pc,d6.w),d5
	move.l	d5,VB(a6,d6.w)
	lsr.w	#1,d6
	move.w	d7,PID(a6,d6.w)
	add.w	d6,d6
	add.w	d7,d7
	add.w	d7,d7
	move.l	TABLES(a6),a1
	move.l	(a1,d7.w),TBL(a6,d6.w)
	rts
slot_offsets:
	dc.l	0,$2000,$4000,$6000,$8000,$A000,$C000,$E000
main_map:
	dc.l	0,vram0
	dc.l	1,vram1
	dc.l	2,shared
	dc.l	8,banks_main
	dc.l	4,rom_main
	dc.l	5,rom_main+$2000
	dc.l	6,rom_main+$4000
	dc.l	7,rom_main+$6000
sub_map:
	dc.l	0,shared
	dc.l	1,vram0
	dc.l	2,vram1
	dc.l	8,rom_sub
	dc.l	4,rom_sub+$8000
	dc.l	5,rom_sub+$A000
	dc.l	6,rom_sub+$C000
	dc.l	7,rom_sub+$E000

; ---- one arcade frame of the two translated CPUs (the harness has done the vertical blank, the MCU and the sound CPU) ----
port_frame:
	lea	ctx_main,a6
	bsr	cpu_irq_setup
	lea	ctx_sub,a6
	bsr	cpu_irq_setup
	lea	sched_order,a0
	lea	shared,a1
	move.b	$1604(a1),d0
	cmp.b	$1605(a1),d0
	beq.s	.sub1
	move.l	#ctx_main,(a0)		; (cpu1 has counted a sub-step that cpu2 has not taken: cpu1 first)
	move.l	#ctx_sub,4(a0)
	bra.s	.go
.sub1:	move.l	#ctx_sub,(a0)
	move.l	#ctx_main,4(a0)
.go:	clr.b	sched_blocked
.round:	lea	sched_order,a0
	move.l	(a0),a6
	bsr	run_ctx
	lea	sched_order,a0
	move.l	4(a0),a6
	bsr	run_ctx
	tst.b	ctx_main+RUNNING
	bne.s	.alive
	tst.b	ctx_sub+RUNNING
	beq.s	.done
.alive:	cmp.b	#12,sched_blocked	; (both blocked for good: the schedule is stuck)
	bcs.s	.round
	move.w	#$FFFE,badpc
	move.l	a6,badctx
	bra	sim_badpc
.done:	rts

run_ctx:
	tst.b	RUNNING(a6)
	beq.s	.r
	bsr	cpu_resume
	move.b	yield_status,d0
	beq.s	.idle
	cmp.b	#1,d0
	beq.s	.sem
	addq.b	#1,sched_blocked	; 2: a spin wait's branch was taken
	rts
.sem:	clr.b	sched_blocked
	rts
.idle:	clr.b	RUNNING(a6)
	clr.b	sched_blocked
.r:	rts

; The IRQ at the idle point: the entire state on the 6809 stack (E set), I set; the CPU's resume address is the handler.
cpu_irq_setup:
	movem.l	R_D0(a6),d0-d4
	move.l	R_A5(a6),a5
	move.w	IDLEPC(a6),d7
	move.b	d7,-(a5)		; PC
	lsr.w	#8,d7
	move.b	d7,-(a5)
	move.b	d4,-(a5)		; U
	move.w	d4,d7
	lsr.w	#8,d7
	move.b	d7,-(a5)
	move.b	d3,-(a5)		; Y
	move.w	d3,d7
	lsr.w	#8,d7
	move.b	d7,-(a5)
	move.b	d2,-(a5)		; X
	move.w	d2,d7
	lsr.w	#8,d7
	move.b	d7,-(a5)
	move.b	DPR+1(a6),-(a5)	; DP
	move.b	d1,-(a5)		; B
	move.b	d0,-(a5)		; A
	move.w	R_SR(a6),d7
	and.b	#$0F,d7
	move.b	CCHI(a6),d6
	and.b	#$70,d6
	or.b	d6,d7
	or.b	#$80,d7			; E
	move.b	d7,-(a5)		; CC
	or.b	#$90,CCHI(a6)		; E, I
	move.l	a5,R_A5(a6)
	move.l	IRQV(a6),R_RESUME(a6)
	move.b	#1,RUNNING(a6)
	rts

; Run the CPU of context a6 until it yields (cpu_exit / <cpu>_sem_yield / spin_exit / cpu_idle: an rts to run_ctx).
cpu_resume:
	movem.l	R_D0(a6),d0-d4
	move.l	R_A5(a6),a5
	move.l	PB+28(a6),a2		; (the translation's cached slot bases: PB[7], VB[DPS], VB[A4SLOT])
	move.w	DPS(a6),d7
	move.l	VB(a6,d7.w),a3
	move.w	A4SLOT(a6),d7
	move.l	VB(a6,d7.w),a4
	move.l	R_RESUME(a6),a0
	move.w	R_SR(a6),d7
	move.w	d7,ccr
	jmp	(a0)

; the idle points (tools/machine.py idle): idle (save the state, back to the scheduler) or on round the loop
;   main $81BC: idle while the queues $56B3 / $56B4 and $566E / $566F are equal
;   sub  $80A6: idle while the queue $1667 / $1668 is equal
main_idle:
	move.w	sr,d5
	move.b	$56B3(a3),d6
	cmp.b	$56B4(a3),d6
	bne.s	idle_go
	move.b	$566E(a3),d6
	cmp.b	$566F(a3),d6
	bne.s	idle_go
	bra.s	cpu_idle
sub_idle:
	move.w	sr,d5
	move.b	$1667(a3),d6
	cmp.b	$1668(a3),d6
	beq.s	cpu_idle
idle_go:
	move.l	IDLENEXT(a6),a0
	move.w	d5,ccr
	jmp	(a0)
cpu_idle:
	clr.b	yield_status
	move.w	d5,R_SR(a6)
	bra.s	cpu_save
; a store to a semaphore byte (bsr from the translation, after the store): the return address is where the CPU goes on
main_sem_yield:
sub_sem_yield:
	move.w	sr,R_SR(a6)
	move.l	(sp)+,R_RESUME(a6)
	move.b	#1,yield_status
	bra.s	cpu_save
; a spin wait's branch was taken (hooks_<cpu>.s: R_RESUME = the loop head)
spin_exit:
	move.w	sr,R_SR(a6)
	move.b	#2,yield_status
cpu_save:
	movem.l	d0-d4,R_D0(a6)
	move.l	a5,R_A5(a6)
	rts

; ---- the dispatcher: d7.w = a 6809 pc, through the table of the page in its slot (TBL: a directory of 32 blocks of
; 256 labels; bad_table / bad_block where no code is); the CCR is kept ----
main_dispatch:
sub_dispatch:
	move.w	sr,d5
	move.w	d7,d6
	rol.w	#3,d6
	and.w	#7,d6
	add.w	d6,d6
	add.w	d6,d6
	move.l	TBL(a6,d6.w),a0	; the page's directory: 32 blocks of 256 pcs (tools/gen.py dispatch_tables)
	move.w	d7,d6
	and.w	#$1F00,d6
	lsr.w	#6,d6
	move.l	(a0,d6.w),a0
	and.w	#$FF,d7
	add.w	d7,d7
	add.w	d7,d7
	move.l	(a0,d7.w),a0
	move.w	d5,ccr
	jmp	(a0)

; the same when no flags are live at the target (the translation knows): the CCR is not kept
main_dispatch_nf:
sub_dispatch_nf:
	move.w	d7,d6
	rol.w	#3,d6
	and.w	#7,d6
	add.w	d6,d6
	add.w	d6,d6
	move.l	TBL(a6,d6.w),a0
	move.w	d7,d6
	and.w	#$1F00,d6
	lsr.w	#6,d6
	move.l	(a0,d6.w),a0
	and.w	#$FF,d7
	add.w	d7,d7
	add.w	d7,d7
	move.l	(a0,d7.w),a0
	jmp	(a0)

main_badpc:
sub_badpc:
main_unsupported:
sub_unsupported:
cpu_badpc:
	move.w	d7,badpc
	move.w	d6,badslot
	move.l	a6,badctx
sim_badpc:
	bra.s	sim_badpc

; ---- I/O: d7.w = the 6809 address, d5.b = the value (io_w) / the byte in d7 (io_r); d0-d4 a5 a6 kept ----
; main: $4000-$43FF the CUS30 mailbox (`cus30`); stores: $6000-$7FFF cus115 (select = bits 12-9: 4 the bank, 0-3 the PCM
; player), $8000 watchdog, $8400 IRQ acknowledge, $8800-$8FFF tile bank (hwregs+$30), $9000-$9006 / $9400-$9406 scroll
; registers (hwregs+0 / +$10, the byte at +3 / +$13 not kept), $A000 back colour (hwregs+$20).  sub: $8000 watchdog,
; $8800 acknowledge, $D803 the bank (page 8 + bank & 3).
main_io_r:
	cmp.w	#$4000,d7
	bcs.s	sub_io_r
	cmp.w	#$4400,d7
	bcc.s	sub_io_r
	and.w	#$3FF,d7
	lea	cus30,a0
	move.b	(a0,d7.w),d6
	moveq	#0,d7
	move.b	d6,d7
	rts
sub_io_r:
	bsr	addr_page
	moveq	#0,d7
	move.b	(a0),d7
	rts

main_io_w:
	cmp.w	#$4000,d7
	bcs	.ram
	cmp.w	#$4400,d7
	bcc.s	.hi
	and.w	#$3FF,d7
	lea	cus30,a0
	move.b	d5,(a0,d7.w)
	rts
.hi:	cmp.w	#$6000,d7
	bcs	.ram
	cmp.w	#$8000,d7
	bcc.s	.reg
	move.w	d7,d6			; cus115_w: select = (a - $6000) & $1E00 >> 9
	and.w	#$1E00,d6
	cmp.w	#$0800,d6
	bne.s	.r			; (0-3: the 63701X sample player: not modelled yet)
	moveq	#0,d7
	move.b	d5,d7
	and.w	#$1F,d7			; the bank
	moveq	#0,d6
	move.w	d7,d6
	lsl.l	#8,d6
	lsl.l	#5,d6
	add.l	#banks_main,d6
	add.w	#8,d7			; the page number 8 + bank
	move.l	d6,d5
	moveq	#12,d6
	bra	slot_set
.reg:	cmp.w	#$8800,d7
	bcs.s	.r
	cmp.w	#$9000,d7
	bcs.s	.tb
	cmp.w	#$9007,d7
	bcs.s	.s0
	cmp.w	#$9400,d7
	bcs.s	.r
	cmp.w	#$9407,d7
	bcs.s	.s1
	cmp.w	#$A000,d7
	bne.s	.r
	move.b	d5,hwregs+$20
.r:	rts
.tb:	btst	#10,d7			; (a - $8800) >> 10 & 1
	sne	d6
	and.b	#1,d6
	move.b	d6,hwregs+$30
	rts
.s0:	sub.w	#$9000,d7
	bra.s	.st
.s1:	sub.w	#$9400-$10,d7
.st:	cmp.w	#3,d7
	beq.s	.r
	cmp.w	#$13,d7
	beq.s	.r
	lea	hwregs,a0
	move.b	d5,(a0,d7.w)
	rts
.ram:	cmp.w	#$5FF2,d7
	bne.s	.n
	st	sprite_latch
.n:	bsr	addr_page
	move.b	d5,(a0)
	rts

sub_io_w:
	cmp.w	#$6000,d7
	bcc.s	.hi
	cmp.w	#$1FF2,d7
	bne.s	.n
	st	sprite_latch
.n:	bsr	addr_page
	move.b	d5,(a0)
	rts
.hi:	cmp.w	#$D803,d7
	bne.s	.r
	moveq	#0,d6
	move.b	d5,d6
	and.w	#3,d6			; the bank
	move.w	d6,d7
	add.w	#8,d7			; the page number
	lsl.w	#8,d6
	lsl.w	#5,d6
	moveq	#0,d5
	move.w	d6,d5
	add.l	#rom_sub,d5
	moveq	#12,d6
	bra	slot_set
.r:	rts

; d7.w = a 6809 address -> a0 = the 68000 address of the byte; d6 clobbered
addr_page:
	move.w	d7,d6
	rol.w	#3,d6
	and.w	#7,d6
	add.w	d6,d6
	add.w	d6,d6
	move.l	PB(a6,d6.w),a0
	move.w	d7,d6
	and.w	#$1FFF,d6
	add.w	d6,a0
	rts

	include	"m6809rt.s"
	include	"code_main.s"
	include	"code_sub.s"
	include	"hooks_main.s"
	include	"hooks_sub.s"
	include	"tables_main.s"
	include	"tables_sub.s"

	section data,data
	even
rom_main:
	incbin	"rom_main.bin"
banks_main:
	incbin	"banks_main.bin"
rom_sub:
	incbin	"rom_sub.bin"

	section bss,bss
ctx_main:	ds.b	CTXSIZE
ctx_sub:	ds.b	CTXSIZE
	even
vram0:		ds.b	$2000
vram1:		ds.b	$2000
shared:		ds.b	$2000
cus30:		ds.b	$400
hwregs:		ds.b	$40
sched_order:	ds.l	2
yield_status:	ds.b	1
sched_blocked:	ds.b	1
sprite_latch:	ds.b	2
	even
bad_table:	ds.l	32		; (a page without code: every block bad_block)
bad_block:	ds.l	256		; (filled with cpu_badpc)
badpc:		ds.w	1
badslot:	ds.w	1
badctx:		ds.l	1
nopage:		ds.b	$2000
		ds.b	4096
own_stack_top:
