; The runtime of Splatterhouse's translated main and sub CPU programs (included by splatter.s): the CPUs' contexts, the
; schedule of one arcade frame (port_frame), the dispatcher, the MMU, the I/O pages, the key custom.
;

; ---- the context block (engine/m6809x.py) ----
PB = 0				; 8 longs: the 68000 address of the page in each slot
VB = 32				; 8 longs: PB - slot * $2000
TBL = 64			; 8 longs: the dispatcher's table of the page in each slot (bad_table: no code there)
PID = 96			; 8 words: the virtual page in each slot
CCHI = 112			; the CC byte's E F H I bits (6809 positions)
R_D0 = 116			; the registers while the CPU is idle: d0-d4 (5 longs)
R_A5 = 136
R_SR = 140
IRQV = 144			; the IRQ handler's label
IDLEPC = 148			; the idle point's 6809 pc
FLAG = 150			; the direct page byte the idle loop waits on
TABLES = 152			; the page tables of the dispatcher
IDLENEXT = 156			; the label after the idle loop's STA $F200
CTXSIZE = 160			; (the fields used with an index register stay below 128)

VIO_PAGE0 = $170		; vio = virtual $2E0000-$307FFF
KEY_PAGE = $17C
SPR_PAGE = $17E

	include	"gen_info.s"


	section text,code
init_contexts:
	lea	ctx_main,a6
	move.l	#MAIN_IRQ_LABEL,IRQV(a6)
	move.w	#MAIN_IDLE_PC,IDLEPC(a6)
	move.w	#MAIN_FLAG,FLAG(a6)
	move.l	#main_page_tables,TABLES(a6)
	move.l	#MAIN_IDLE_NEXT,IDLENEXT(a6)
	lea	ctx_sub,a6
	move.l	#SUB_IRQ_LABEL,IRQV(a6)
	move.w	#SUB_IDLE_PC,IDLEPC(a6)
	move.w	#SUB_FLAG,FLAG(a6)
	move.l	#sub_page_tables,TABLES(a6)
	move.l	#SUB_IDLE_NEXT,IDLENEXT(a6)
	rts

; One arcade frame of the two translated CPUs (the harness has done the vertical blank, the MCU and the sound CPU).
port_frame:
	lea	ctx_main,a6
	bsr	cpu_frame
	lea	ctx_sub,a6
	bsr	cpu_frame
	rts

; The IRQ at the idle point: the entire state on the 6809 stack (E set), I set, the handler; back here (rts) through
; the idle hook when the CPU is idle again.
cpu_frame:
	moveq	#28,d6			; (TBL from the pages: the harness sets PID)
.tbl:	bsr	set_tbl
	subq.w	#4,d6
	bpl.s	.tbl
	movem.l	R_D0(a6),d0-d4
	move.l	R_A5(a6),a5
	move.l	PB+28(a6),a2		; (the translation's cached slot bases: PB[7], PB[0], VB[1])
	move.l	PB(a6),a3
	move.l	VB+4(a6),a4
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
	clr.b	-(a5)			; DP
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
	move.l	IRQV(a6),a0
	move.w	R_SR(a6),d7
	move.w	d7,ccr
	jmp	(a0)

; The idle point (the translated label jumps here): idle when the flag is set (save the state, back to cpu_frame's
; caller), else the loop goes on (LDA <flag; BNE: the translation after STA $F200, whose flags LDA replaces).
main_idle:
sub_idle:
	move.w	sr,d5
	move.l	PB(a6),a0
	move.w	FLAG(a6),d6
	tst.b	(a0,d6.w)
	beq.s	.go
	move.w	d5,R_SR(a6)
	movem.l	d0-d4,R_D0(a6)
	move.l	a5,R_A5(a6)
	rts
.go:	move.l	IDLENEXT(a6),a0
	move.w	d5,ccr
	jmp	(a0)

; ---- the dispatcher: d7.w = a 6809 pc, through the table of the page in its slot (TBL); the CCR is kept ----
main_dispatch:
sub_dispatch:
	move.w	sr,d5
	move.w	d7,d6
	rol.w	#3,d6
	and.w	#7,d6
	add.w	d6,d6
	add.w	d6,d6
	move.l	TBL(a6,d6.w),a0
	and.w	#$1FFF,d7
	add.w	d7,d7
	add.w	d7,d7
	move.l	(a0,d7.w),a0
	move.w	d5,ccr
	jmp	(a0)

; TBL[slot] from PID[slot] (d6.w = slot * 4)
set_tbl:
	move.w	d6,d7
	lsr.w	#1,d7
	move.w	PID(a6,d7.w),d7
	add.w	d7,d7
	add.w	d7,d7
	move.l	TABLES(a6),a0
	move.l	(a0,d7.w),TBL(a6,d6.w)
	rts

main_badpc:
sub_badpc:
main_unsupported:
sub_unsupported:
cpu_badpc:
	move.w	d7,badpc
	move.w	d6,badslot
	move.l	a6,badctx
    ifnd SIM
	bra	port_crash		; (splatter.s: CRASH.TXT, back to the desktop)
    endc
sim_badpc:
	bra.s	sim_badpc

; ---- I/O: d7.w = the 6809 address, d5.b = the value (io_w) / the byte in d7 (io_r); d0-d4 a5 a6 kept ----
main_io_w:
sub_io_w:
	cmp.w	#$E000,d7
	bcc	mmu_w
	bsr	addr_page		; d6 = the page, a0 = its byte
	cmp.w	#KEY_PAGE,d6
	beq.s	.key
	cmp.w	#SPR_PAGE,d6
	beq.s	.spr
	move.b	d5,(a0)
	rts
.key:	and.w	#$70,d7			; key custom type 3: the register (A4-A6 of the address) is written
	lsr.w	#4,d7
	lea	key_regs,a0
	move.b	d5,(a0,d7.w)
	rts
.spr:	and.w	#$1FFF,d7
	cmp.w	#$1000,d7
	bcc.s	.ctl
	move.b	d5,(a0)
	cmp.w	#$0FF2,d7
	bne.s	.r
	st	sprite_latch
.r:	rts
.ctl:	and.w	#$1F,d7			; CUS123 control: 32 bytes mirrored over 2FD000-2FDFFF
	lea	vio+(SPR_PAGE-VIO_PAGE0)*$2000+$1000,a0
	move.b	d5,(a0,d7.w)
	rts

main_io_r:
sub_io_r:
	bsr	addr_page
	cmp.w	#KEY_PAGE,d6
	beq.s	.key
	cmp.w	#SPR_PAGE,d6
	beq.s	.spr
	moveq	#0,d7
	move.b	(a0),d7
	rts
.key:	and.w	#$70,d7
	lsr.w	#4,d7
	cmp.w	#3,d7
	beq.s	.id
	cmp.w	#4,d7
	beq.s	mame_rand
	moveq	#0,d7
	rts
.id:	move.l	#181,d7			; CUS181
	rts
.spr:	and.w	#$1FFF,d7
	cmp.w	#$1000,d7
	bcc.s	.ctl
	moveq	#0,d7
	move.b	(a0),d7
	rts
.ctl:	and.w	#$1F,d7
	lea	vio+(SPR_PAGE-VIO_PAGE0)*$2000+$1000,a0
	move.b	(a0,d7.w),d7
	rts

; d7.w = a 6809 address -> d6.w = the virtual page of its slot, a0 = the 68000 address of the byte
addr_page:
	move.w	d7,d6
	rol.w	#3,d6
	and.w	#7,d6
	add.w	d6,d6
	add.w	d6,d6
	move.l	PB(a6,d6.w),a0
	lsr.w	#1,d6
	move.w	PID(a6,d6.w),d6
	move.w	d7,-(sp)
	and.w	#$1FFF,d7
	add.w	d7,a0
	move.w	(sp)+,d7
	rts

; MAME's running_machine::rand(): seed = seed * 1664525 + 1013904223, the byte (seed >> 16) & $FF
mame_rand:
	move.l	d5,-(sp)			; (the translation may hold a carry in d5: ADC / SBC)
	move.l	rand_seed,d5
	move.w	d5,d6
	mulu	#$660D,d6			; lo * $660D (32 bits)
	move.l	d5,d7
	swap	d7
	mulu	#$660D,d7			; hi * $660D (its low word counts)
	move.w	d5,-(sp)			; lo * $19 = lo << 4 + lo << 3 + lo (its low word counts)
	lsl.w	#3,d5
	add.w	d5,d7
	add.w	d5,d5
	add.w	d5,d7
	add.w	(sp)+,d7
	swap	d7
	clr.w	d7
	add.l	d7,d6
	add.l	#1013904223,d6
	move.l	d6,rand_seed
	swap	d6
	moveq	#0,d7
	move.b	d6,d7
	move.l	(sp)+,d5
	rts

; A slot's page from a static store (the translation: d6.w = slot * 2, d5 = the value): _word sets bits 9-0 (STD
; $E000 + 2n), _hi bits 9-8 (an even address), _lo bits 7-0 (odd).  PB / VB from page_base_table; slot 0 holds the
; stack: S keeps its 6809 value (a5 moves with the page).
main_bank_word:
sub_bank_word:
	and.w	#$3FF,d5
	move.w	d5,d7
	bra.s	bank_set
main_bank_hi:
sub_bank_hi:
	move.w	PID(a6,d6.w),d7
	and.w	#$FF,d7
	and.w	#3,d5
	lsl.w	#8,d5
	or.w	d5,d7
	bra.s	bank_set
main_bank_lo:
sub_bank_lo:
	move.w	PID(a6,d6.w),d7
	and.w	#$300,d7
	and.w	#$FF,d5
	or.w	d5,d7
bank_set:
	move.w	d7,PID(a6,d6.w)
	add.w	d7,d7
	add.w	d7,d7			; page * 4
	add.w	d6,d6			; slot * 4
	move.l	TABLES(a6),a0
	move.l	(a0,d7.w),TBL(a6,d6.w)	; the dispatcher's table (bad_table: no code in that page)
	lea	page_base_table,a0
	move.l	(a0,d7.w),a0
	move.l	a0,PB(a6,d6.w)
	move.l	VB(a6,d6.w),d5		; the old VB
	suba.l	slot_offsets(pc,d6.w),a0
	move.l	a0,VB(a6,d6.w)
	tst.w	d6
	bne.s	.n0
	sub.l	d5,a5			; slot 0: the stack moves with it, a3
	add.l	a0,a5
	move.l	a0,a3
	rts
.n0:	cmp.w	#4,d6
	bne.s	.n1
	move.l	a0,a4			; slot 1: a4 = VB[1]
	rts
.n1:	cmp.w	#28,d6
	bne.s	.r
	move.l	PB+28(a6),a2		; slot 7: a2 = PB[7]
.r:	rts

slot_offsets:
	dc.l	0,$2000,$4000,$6000,$8000,$A000,$C000,$E000

; page_base_table[p] = page_base(p) for the 1024 virtual pages
init_page_bases:
	lea	page_base_table,a1
	moveq	#0,d7
.l:	bsr	page_base
	move.l	a0,(a1)+
	addq.w	#1,d7
	cmp.w	#$400,d7
	bne.s	.l
	rts

; The MMU's registers ($E000-$FFFF) from an indexed store: $E000 + 2n even / odd = slot n's page bits 9-8 / 7-0;
; the rest (resets, watchdog, IRQ acknowledges, FIRQ to the sub CPU, the sub CPU's slot 7) is the boot's or not
; needed by the port.
mmu_w:
	move.w	d7,d6
	lsr.w	#8,d6
	lsr.w	#1,d6
	and.w	#$0F,d6			; the register
	cmp.w	#8,d6
	bcc.s	.other
	add.w	d6,d6			; slot * 2
	btst	#0,d7
	bne	main_bank_lo
	bra	main_bank_hi
.other:
    ifd SIM
	cmp.w	#8,d6			; SUBRES, the sub CPU's FIRQ, its slot 7: not expected after the boot
	beq.s	.stop
	cmp.w	#13,d6
	beq.s	.stop
	cmp.w	#14,d6
	beq.s	.stop
    endc
	rts
.stop:	move.w	#$FFFF,badpc
	move.l	a6,badctx
	bra	sim_badpc

; d7.w = a virtual page -> a0 = its 68000 address (rom_image, vio, nopage)
page_base:
	cmp.w	#$200,d7
	bcs.s	.io
	move.w	d7,d5
	sub.w	#$200,d5
	lsr.w	#6,d5			; the ROM (64 KB each)
	swap	d5
	clr.w	d5
	move.w	d7,-(sp)
	and.w	#7,d7
	lsl.w	#8,d7
	lsl.w	#5,d7			; (page & 7) * $2000
	or.w	d7,d5
	move.w	(sp)+,d7
	lea	rom_image,a0
	add.l	d5,a0
	rts
.io:	cmp.w	#VIO_PAGE0,d7
	bcs.s	.none
	cmp.w	#VIO_PAGE0+$13,d7
	bhi.s	.none
	move.w	d7,d5
	sub.w	#VIO_PAGE0,d5
	mulu	#$2000,d5
	lea	vio,a0
	add.l	d5,a0
	rts
.none:	lea	nopage,a0
	rts

	include	"m6809rt.s"
	include	"natives.s"
	include	"code_main.s"
	include	"code_sub.s"
	include	"tables_main.s"
	include	"tables_sub.s"

	section data,data
	even
rom_image:
	incbin	"rom_image.bin"
rand_seed:
	dc.l	$9D14ABD7

	section bss,bss
ctx_main:	ds.b	CTXSIZE
ctx_sub:	ds.b	CTXSIZE
key_regs:	ds.b	8
tile_written:	ds.b	1		; (the render's writer flags: set after the translated stores into tile RAM, tools/gen.py)
tile_written_fix:	ds.b	1
tile_fix_all:	ds.b	1		; (and per row of the fixed layers: tools/gen.py tile_marks, render.s TILE_ROWS)
	even
tile_fix_rows:	ds.b	56
page_base_table:	ds.l	$400
bad_table:	ds.l	$2000		; (filled with cpu_badpc)
sprite_latch:	ds.b	2
sl_end:		ds.l	1		; (natives.s: the sprite list's objects)
sl_list:	ds.l	50
sl_pb:		ds.l	1
sl_s1:		ds.w	1
badpc:		ds.w	1
badslot:	ds.w	1
badctx:		ds.l	1
vio:		ds.b	$28000
nopage:		ds.b	$2000
		ds.b	4096
own_stack_top:
