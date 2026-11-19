; Defender (Williams, 1980) for the Atari STE: the main 6809 program translated (tools/gen.py -> build/defender/
; code_main.s, engine/m6809x.py).  So far the simulator build only (-D SIM: tools/logic_test.py); the STE's hardware,
; picture, input and sound are not written yet.
;
; The power-on tests are skipped: the program starts at $D738 (MAIN_RESET), where they go when they pass.
;
; The schedule (machine.DefenderPort): the foreground waits at $E7C3 (LDA <$5D; BEQ $E7C3) for the IRQ's frame count.
; At that idle point (df_idle, gen.py NATIVES) with $A05D = 0 the runtime delivers the IRQ's two passes of an arcade
; frame, each with $E7C3 as the return address: the line-128 pass (the video counter reads $80, then $98), then the
; line-0 pass (it reads 0; it raises $A05D).  After the second RTI the foreground runs the frame and comes back.
;
; Registers in translated code (engine/m6809x.py): d0 A, d1 B, d2 X, d3 Y, d4 U, a5 = S as a pointer (df_mem + S),
; a6 = the context of the view selected (ctx_views + 256 * view: slot 6 holds that view's page 8 + view), a3 = df_mem +
; $A000 (DP $A0 and the stack), a4 = df_mem (every slot's VB is df_mem), a2 = df_mem + $E000 (PB[7]); d5 d6 d7 a0 a1
; scratch.  The video RAM is memory (df_mem $0000-$97FF), and so is the palette (df_mem $C000-$C00F: the IRQ writes it
; with PSHU, which the translation does as memory stores; main_io_w's palette stores land there too).  The accesses to $C000-$CFFF (the I/O in view 0, the bank's
; bytes in views 1-7) and the stores to $D000-$DFFF (the view select) go through main_io_r / main_io_w.

; the context block (engine/m6809x.py)
SPB = 0				; 8 longs: the 68000 address of the page in each slot
SVB = 32			; 8 longs: PB - slot * $2000 (df_mem for all)
STBL = 64			; 8 longs: the dispatcher's table of the page in each slot
SPID = 96			; 8 words: the virtual page in each slot
SCCHI = 112			; the CC byte's E F H I bits (6809 positions)
CTX_STRIDE = 256		; (ctx_views: a context per view)
NVIEWS = 16

IDLE_PC = $E7C3			; (machine.DefenderPort.IDLE)
FLAG = $A05D			; the IRQ's frame count
DP = $A0

	include	"main_info.s"

	section text,code

start:
	ifnd SIM
	illegal				; (the STE build is not written yet)
	endc
	clr.l	-(sp)			; (supervisor mode)
	move	#$20,-(sp)
	trap	#1
	addq	#6,sp
	lea	own_stack_top,sp
	bsr	init_main
	lea	ctx_views,a6
	lea	df_mem+$A000,a3		; (PB of slot 5: the direct page and the stack, engine/m6809x.py a3_pb)
	lea	df_mem,a4
	lea	df_mem+$E000,a2
	lea	df_mem,a5		; S = 0 (the program sets it)
	moveq	#0,d0
	moveq	#0,d1
	moveq	#0,d2
	moveq	#0,d3
	moveq	#0,d4
	moveq	#0,d5
	moveq	#0,d6
	moveq	#0,d7
	sub.l	a0,a0
	sub.l	a1,a1
	move	#$2300,sr
	move	#0,ccr
	jmp	MAIN_RESET

; init_main: a context per view (main_io_w's view select switches a6): the slots' pages, the dispatcher's tables, I and
; F set (a reset).  Slot 6 holds the view's page 8 + view; every VB is df_mem.
init_main:
	lea	view_pages,a0		; the window's pages: bank k (4 KB) and $D000-$DFFF for views 1-7, zeros and $D000-$DFFF
	lea	df_banks,a1		; for 8-15
	moveq	#7,d3
.vp:	move.w	#$1000/4-1,d0
	cmp.w	#0,d3
	bne.s	.vb
.vz:	clr.l	(a0)+
	dbf	d0,.vz
	bra.s	.vd
.vb:	move.l	(a1)+,(a0)+
	dbf	d0,.vb
.vd:	lea	df_mem+$D000,a2
	move.w	#$1000/4-1,d0
.vr:	move.l	(a2)+,(a0)+
	dbf	d0,.vr
	subq.w	#1,d3
	bpl.s	.vp
	lea	main_page_tables,a1
	moveq	#NVIEWS-1,d3		; the view
.b:	move.w	d3,d1
	lsl.w	#8,d1			; (CTX_STRIDE)
	lea	ctx_views,a6
	add.w	d1,a6
	moveq	#0,d0			; the slot
.s:	move.w	d0,d1
	add.w	d1,d1
	add.w	d1,d1			; slot * 4
	move.l	d0,d2
	mulu	#$2000,d2
	lea	df_mem,a0
	move.l	a0,SVB(a6,d1.w)
	add.l	d2,a0
	move.l	a0,SPB(a6,d1.w)
	move.l	(a1,d1.w),STBL(a6,d1.w)
	move.w	d0,d2
	add.w	d2,d2
	move.w	d0,SPID(a6,d2.w)
	addq.w	#1,d0
	cmp.w	#8,d0
	bne.s	.s
	move.w	d3,d0			; slot 6: the view's page 8 + view
	addq.w	#8,d0
	move.w	d0,SPID+12(a6)
	add.w	d0,d0
	add.w	d0,d0
	move.l	(a1,d0.w),STBL+24(a6)
	lea	df_mem+$C000,a0		; its memory: view 0 df_mem, 1-7 view_pages (bank, fixed ROM), 8-15 the zero page
	tst.w	d3
	beq.s	.p
	lea	view_pages+7*$2000,a0
	cmp.w	#7,d3
	bhi.s	.p
	move.w	d3,d0
	subq.w	#1,d0
	mulu	#$2000,d0
	lea	view_pages,a0
	add.l	d0,a0
.p:	move.l	a0,SPB+24(a6)
	sub.l	#$C000,a0
	move.l	a0,SVB+24(a6)
	move.b	#$50,SCCHI(a6)
	dbf	d3,.b
	clr.b	df_view
	rts

; ------------------------------------------------------------------------------
; The idle point (gen.py NATIVES: $E7C3 LDA <$5D; BEQ $E7C3): while $A05D is not 0 the translation runs on
; (MAIN_IDLE_T).  Else, after the line-128 pass (df_pass 1) the line-0 pass is delivered at once; otherwise the frame
; is over: the picture, the next arcade frame awaited, the line-128 pass delivered.  An IRQ: the entire state pushed
; (E set, PC $E7C3), I set, the video counter's answers queued, to $DF17 (the RAM vector's JMP).  No IRQ while I is set.
; ------------------------------------------------------------------------------

df_idle:
	tst.b	df_mem+FLAG
	beq.s	.idle
	jmp	MAIN_IDLE_T
.idle:	move	sr,d5			; the 6809's N Z V C
	move.w	d5,idle_sr
	tst.b	df_pass
	beq.s	.frame
	clr.b	df_pass
	lea	pass_top,a0
	bra	.irq
.frame:	movem.l	d0-d4/a2-a6,-(sp)
	ifd SIM
	bsr	sim_frame_done		; (the harness compares the frame just completed)
	endc
	bsr	render_frame
.check:	tst.b	vbl_pending
	bne.s	.deliver
	ifd SIM
	bsr	sim_wait
	endc
	bra.s	.check
.deliver:
	subq.b	#1,vbl_pending
	addq.w	#1,isr_count
	movem.l	(sp)+,d0-d4/a2-a6
	move.b	#1,df_pass
	lea	pass_low,a0
.irq:	btst	#4,SCCHI(a6)		; (I set: no IRQ)
	beq.s	.go
	clr.b	df_pass
	move.w	idle_sr,d5
	move	d5,ccr
	jmp	MAIN_IDLE_T
.go:	move.l	a0,vq_ptr		; the video counter's answers of this pass
	move.w	#IDLE_PC,d7
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
	move.b	main_dpv,-(a5)		; DP (engine/m6809x.py dp_data)
	move.b	d1,-(a5)		; B
	move.b	d0,-(a5)		; A
	move.b	SCCHI(a6),d7		; CC: E F H I from SCCHI, N Z V C from the idle point's flags; E set
	and.b	#$F0,d7
	move.b	idle_sr+1,d6
	and.b	#$0F,d6
	or.b	d6,d7
	or.b	#$80,d7
	move.b	d7,-(a5)
	or.b	#$90,SCCHI(a6)		; E I
	move.w	idle_sr,d5
	move	d5,ccr
	jmp	MAIN_IRQ

render_frame:				; (no picture yet)
	rts

; ---- the dispatcher: d7.w = a 6809 pc; $D000-$DFFF through page 6's table (the fixed ROM is always in slot 6's upper
; half), the rest through the table of the page in its slot; the CCR kept ----
main_dispatch:
	move.w	sr,d5
	ifd SIM
	move.w	d7,dispatch_pc		; (the harness's report of a bad pc)
	endc
	move.w	d7,d6
	and.w	#$F000,d6
	cmp.w	#$D000,d6
	bne.s	.slot
	move.l	main_page_tables+6*4,a0
	bra.s	.tbl
.slot:	move.w	d7,d6
	rol.w	#3,d6
	and.w	#7,d6
	add.w	d6,d6
	add.w	d6,d6
	move.l	STBL(a6,d6.w),a0
	cmp.l	#main_bad_table,a0	; (a slot without code: a pc the coverage never saw)
	beq	main_badpc
.tbl:	and.w	#$1FFF,d7
	add.w	d7,d7
	add.w	d7,d7
	move.l	(a0,d7.w),a0		; (gen.py dispatch_tables: a long a 6809 address)
	move.w	d5,ccr
	jmp	(a0)

; ---- I/O: d7.w = the address; main_io_r: the byte in d7 (long: the upper bits 0); main_io_w: d5.b = the value.  Every
; other register kept (main_io_w: but a6 when the view changes).  machine.Defender rd / wr: in view 0 $C000-$C3FF the
; palette and video control (write only), $C400-$C7FF the CMOS, $C800-$CBFF the video counter, $CC00-$CFFF the PIAs;
; in views 1-7 the bank's bytes, 8-15 nothing; $D000-$DFFF stores select the view. ----
main_io_r:
	cmp.w	#$C000,d7
	blo	.mem
	cmp.w	#$D000,d7
	bhs	.mem
	move.l	d6,-(sp)
	moveq	#0,d6
	move.b	df_view,d6
	beq.s	.io
	cmp.b	#7,d6
	bhi.s	.zero
	move.l	a0,-(sp)		; a bank: (view - 1) * $1000 + the offset
	subq.w	#1,d6
	lsl.w	#8,d6
	lsl.w	#4,d6
	and.w	#$FFF,d7
	add.w	d7,d6
	lea	df_banks,a0
	moveq	#0,d7
	move.b	(a0,d6.l),d7
	move.l	(sp)+,a0
	move.l	(sp)+,d6
	rts
.zero:	moveq	#0,d7
	move.l	(sp)+,d6
	rts
.io:	and.w	#$FFF,d7
	cmp.w	#$400,d7
	blo.s	.zero			; (the palette and video control: write only)
	cmp.w	#$800,d7
	blo.s	.cmos
	cmp.w	#$C00,d7
	blo.s	.vcnt
	and.w	#$1F,d7			; the PIAs: 0-3 PIA 1, 4-7 PIA 0
	cmp.w	#8,d7
	bhs.s	.zero
	move.l	a0,-(sp)
	lea	pia1,a0
	cmp.w	#4,d7
	blo.s	.pia
	lea	pia0,a0
	subq.w	#4,d7
.pia:	bsr	pia_read
	move.l	(sp)+,a0
	move.l	(sp)+,d6
	rts
.cmos:	and.w	#$FF,d7
	move.l	a0,-(sp)
	lea	df_cmos,a0
	move.b	(a0,d7.w),d7
	and.l	#$FF,d7
	move.l	(sp)+,a0
	move.l	(sp)+,d6
	rts
.vcnt:	move.l	a0,-(sp)		; the next answer of this pass (machine.DefenderPort.vpos)
	move.l	vq_ptr,a0
	moveq	#0,d7
	move.b	(a0)+,d7
	move.l	a0,vq_ptr
	move.l	(sp)+,a0
	move.l	(sp)+,d6
	rts
.mem:	move.l	a0,-(sp)
	lea	df_mem,a0
	and.l	#$FFFF,d7
	move.b	(a0,d7.l),d7
	and.l	#$FF,d7
	move.l	(sp)+,a0
	rts

; pia_read: a0 = the PIA's registers (PIA_*), d7.w = the register 0-3 -> d7.l the byte (machine.PIA.read; the IRQ flags
; are never set in the port's schedule).  pia_write: d5.b the value.
PIA_OUTA = 0
PIA_OUTB = 1
PIA_DDRA = 2
PIA_DDRB = 3
PIA_CTLA = 4
PIA_CTLB = 5
PIA_INA = 6			; (a pointer's byte: the input port's value is read through PIA_INA_P)
PIA_INA_P = 8			; the address of the port A input byte
PIA_INB_P = 12			; the address of the port B input byte (0: none, reads 0)
PIA_SND = 16			; 1: port B writes are sound commands (PIA 1)
PIA_SIZE = 18

pia_read:
	move.l	d6,-(sp)
	move.l	a1,-(sp)
	cmp.w	#1,d7
	beq.s	.ctla
	cmp.w	#3,d7
	beq.s	.ctlb
	cmp.w	#2,d7
	beq.s	.b
	btst	#2,PIA_CTLA(a0)		; port A: the DDR or (input & ~DDR) | (output & DDR)
	bne.s	.da
	moveq	#0,d7
	move.b	PIA_DDRA(a0),d7
	bra.s	.ret
.da:	move.l	PIA_INA_P(a0),a1
	move.b	(a1),d7
	move.b	PIA_DDRA(a0),d6
	not.b	d6
	and.b	d6,d7
	not.b	d6
	and.b	PIA_OUTA(a0),d6
	or.b	d6,d7
	and.l	#$FF,d7
	bra.s	.ret
.b:	btst	#2,PIA_CTLB(a0)
	bne.s	.db
	moveq	#0,d7
	move.b	PIA_DDRB(a0),d7
	bra.s	.ret
.db:	moveq	#0,d7
	move.b	PIA_OUTB(a0),d7
	cmp.b	#$FF,PIA_DDRB(a0)
	beq.s	.ret
	and.b	PIA_DDRB(a0),d7
	move.l	PIA_INB_P(a0),d6
	beq.s	.ret
	move.l	d6,a1
	move.b	PIA_DDRB(a0),d6
	not.b	d6
	and.b	(a1),d6
	or.b	d6,d7
	bra.s	.ret
.ctla:	moveq	#0,d7
	move.b	PIA_CTLA(a0),d7
	bra.s	.ret
.ctlb:	moveq	#0,d7
	move.b	PIA_CTLB(a0),d7
.ret:	move.l	(sp)+,a1
	move.l	(sp)+,d6
	rts

pia_write:
	cmp.w	#1,d7
	beq.s	.ctla
	cmp.w	#3,d7
	beq.s	.ctlb
	cmp.w	#2,d7
	beq.s	.b
	btst	#2,PIA_CTLA(a0)
	bne.s	.oa
	move.b	d5,PIA_DDRA(a0)
	rts
.oa:	move.b	d5,PIA_OUTA(a0)
	rts
.b:	btst	#2,PIA_CTLB(a0)
	bne.s	.ob
	move.b	d5,PIA_DDRB(a0)
	rts
.ob:	move.b	d5,PIA_OUTB(a0)
	tst.b	PIA_SND(a0)
	beq.s	.r
	move.l	d6,-(sp)		; the sound command (| $C0) into the ring
	move.l	a1,-(sp)
	lea	snd_ring,a1
	moveq	#0,d6
	move.b	snd_head,d6
	move.b	d5,(a1,d6.w)
	or.b	#$C0,(a1,d6.w)
	addq.b	#1,snd_head
	move.l	(sp)+,a1
	move.l	(sp)+,d6
.r:	rts
.ctla:	and.b	#$3F,d5
	move.b	d5,PIA_CTLA(a0)
	rts
.ctlb:	and.b	#$3F,d5
	move.b	d5,PIA_CTLB(a0)
	rts

main_io_w:
	cmp.w	#$C000,d7
	blo	.ram
	cmp.w	#$E000,d7
	bhs	.out			; (ROM)
	cmp.w	#$D000,d7
	bhs	.view
	tst.b	df_view
	bne	.out			; (a bank or nothing: ROM)
	and.w	#$FFF,d7
	cmp.w	#$400,d7
	blo.s	.pal
	cmp.w	#$800,d7
	blo.s	.cmos
	cmp.w	#$C00,d7
	blo	.out			; (the video counter)
	and.w	#$1F,d7
	cmp.w	#8,d7
	bhs	.out
	move.l	a0,-(sp)
	lea	pia1,a0
	cmp.w	#4,d7
	blo.s	.pia
	lea	pia0,a0
	subq.w	#4,d7
.pia:	bsr	pia_write
	move.l	(sp)+,a0
	rts
.pal:	cmp.w	#$3FF,d7
	beq	.out			; (the watchdog)
	and.w	#$1F,d7
	cmp.w	#$10,d7
	bhs.s	.vctl
	move.l	a0,-(sp)
	lea	df_mem+$C000,a0
	move.b	d5,(a0,d7.w)
	move.l	(sp)+,a0
	st	pal_dirty
	rts
.vctl:	move.b	d5,df_cocktail
	and.b	#1,df_cocktail
	rts
.cmos:	and.w	#$FF,d7
	move.l	a0,-(sp)
	lea	df_cmos,a0
	move.b	d5,(a0,d7.w)
	or.b	#$F0,(a0,d7.w)
	move.l	(sp)+,a0
	rts
.view:	moveq	#15,d7			; the view: a6 becomes its context (the CC's E F H I go on)
	and.b	d5,d7
	move.b	d7,df_view
	lsl.w	#8,d7			; (CTX_STRIDE)
	move.l	a0,-(sp)
	lea	ctx_views,a0
	add.w	d7,a0
	move.b	SCCHI(a6),SCCHI(a0)
	move.l	a0,a6
	move.l	(sp)+,a0
	rts
.ram:	move.l	a0,-(sp)
	lea	df_mem,a0
	and.l	#$FFFF,d7
	move.b	d5,(a0,d7.l)
	move.l	(sp)+,a0
.out:	rts

main_bad_table:				; (the dispatcher's table for a slot without code: none)
main_badpc:
main_unsupported:
	move	#$2700,sr
	move.w	d7,badpc
.l:	bra.s	.l

	include	"m6809rt.s"

	ifd SIM
sim_wait:				; the harness stops here (a loop), sets the inputs and vbl_pending, returns (rts)
	bra.s	sim_wait
sim_frame_done:				; the harness stops here and compares (an arcade frame completed), returns (rts)
	bra.s	sim_frame_done
	endc

	include	"code_main.s"
	include	"tables_main.s"

	section data,data
	even
pass_low:	dc.b	$80,$98,$FF,$FF	; the video counter's answers: the line-128 pass, the line-0 pass
pass_top:	dc.b	$00,$FF,$FF,$FF
pia0:		dc.b	0,0,0,0,0,0,0,0	; (PIA_*: IN0 / IN1)
		dc.l	io_in0,io_in1
		dc.b	0,0
pia1:		dc.b	0,0,0,0,0,0,0,0	; (IN2; port B the sound command)
		dc.l	io_in2,0
		dc.b	1,0
	even
df_mem:		incbin	"defender.img"
df_banks:	incbin	"banks.rom"
df_cmos:	incbin	"cmos.bin"

	section bss,bss
	even
ctx_views:	ds.b	NVIEWS*CTX_STRIDE
view_pages:	ds.b	8*$2000		; slot 6's pages of views 1-7 and of the empty views (init_main)
vq_ptr:		ds.l	1
idle_sr:	ds.w	1
badpc:		ds.w	1
dispatch_pc:	ds.w	1
isr_count:	ds.w	1
df_view:	ds.b	1
main_dpv:	ds.b	1		; DP as data (engine/m6809x.py dp_data; 0 at the reset)
df_pass:	ds.b	1		; 1: the line-128 pass was delivered, the line-0 pass is next
df_cocktail:	ds.b	1
vbl_pending:	ds.b	1
pal_dirty:	ds.b	1
snd_head:	ds.b	1
io_in0:		ds.b	1		; what the program reads: IN0, IN1 (PIA 0), IN2 (PIA 1); active high
io_in1:		ds.b	1
io_in2:		ds.b	1
	even
snd_ring:	ds.b	256		; the sound commands (the last 256)
	even
		ds.l	1024
own_stack_top:
