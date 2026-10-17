; The runtime of Gyruss's translated sub CPU (KONAMI-1, tools/gen_sub.py; included by gyruss.s): its context, the
; boot and the IRQ (machine.GyrussPort), the hooks, the dispatcher, the I/O.
;
; Registers in translated code (engine/m6809x.py): d0 A, d1 B, d2 X, d3 Y, d4 U, a5 = S as a pointer (VB of slot 2 + S),
; a6 = sub_ctx, a3 = VB of slot 2 ($4000-$5FFF: the direct page $42xx, the stack, the sprite RAM), a4 = VB of slot 3
; (the shared RAM: the Z80's $A000-$A7FF), a2 = PB[7] (the ROM); d5 d6 d7 a0 a1 scratch.  The main CPU's registers are
; kept on the 68000 stack while the sub runs (sub_boot / sub_irq save them all).

SPB = 0				; 8 longs: the 68000 address of the page in each slot
SVB = 32			; 8 longs: PB - slot * $2000
STBL = 64			; 8 longs: the dispatcher's table of the page in each slot
SCCHI = 112			; the CC byte's E F H I bits (6809 positions)
SR_D0 = 116			; the registers between runs: d0-d4 (5 longs)
SR_A5 = 136
SR_SR = 140
SCTXSIZE = 160
SEG_MAX = 160			; the sprite entries given to other objects in a frame (the bands' log)

	include	"sub_info.s"

	section text,code
; init_sub: the context (the slots' pages, the dispatcher's tables), the registers 0, I and F set (a reset)
init_sub:
	lea	sub_ctx,a6
	lea	sub_page_tables,a1
	moveq	#0,d0
.s:	move.w	d0,d1
	add.w	d1,d1
	add.w	d1,d1			; slot * 4
	move.l	.pages(pc,d1.w),a0
	move.l	a0,SPB(a6,d1.w)
	move.l	d0,d2
	mulu	#$2000,d2
	sub.l	d2,a0
	move.l	a0,SVB(a6,d1.w)
	move.l	(a1,d1.w),STBL(a6,d1.w)
	addq.w	#1,d0
	cmp.w	#8,d0
	bne.s	.s
	move.b	#$50,SCCHI(a6)
	clr.w	SR_SR(a6)
	lea	SR_D0(a6),a0
	moveq	#5-1,d1
.c:	clr.l	(a0)+
	dbf	d1,.c
	move.l	#sub_ram-$4000,SR_A5(a6)	; (S = 0; the program sets it)
	clr.b	sub_mask
	rts
.pages:	dc.l	sub_null,sub_null,sub_ram,g_block+$2000,sub_null,sub_null,sub_null,sub_rom

; sub_boot: from the reset vector to the idle loop (F0B6: the delay loop, the ROM and RAM tests, the sprite RAM
; cleared, the IRQ mask set).  sub_irq: the IRQ handler (when its mask is set) back to the idle loop.  Both keep every
; register.
sub_boot:
	movem.l	d0-d7/a0-a6,-(sp)
	lea	sub_ctx,a6
	bsr.s	sub_enter_reset
	movem.l	(sp)+,d0-d7/a0-a6
	rts

sub_irq:
	tst.b	sub_mask
	beq.s	.no
	clr.w	sub_reads
	clr.l	sub_acc
	movem.l	d0-d7/a0-a6,-(sp)
	lea	sub_ctx,a6
	bsr.s	sub_enter_irq
	movem.l	(sp)+,d0-d7/a0-a6
.no:	rts

sub_enter_reset:
	bsr	sub_restore
	move.w	SR_SR(a6),d7
	move.w	d7,ccr
	jmp	SUB_RESET

; the IRQ: the entire state pushed (E set; PC = the idle loop, DP = $42), I set, to F0B8
sub_enter_irq:
	bsr	sub_restore
	move.w	#$F0B6,d7
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
	move.b	#$42,-(a5)		; DP
	move.b	d1,-(a5)		; B
	move.b	d0,-(a5)		; A
	move.b	SCCHI(a6),d7		; CC: E F H I from SCCHI, N Z V C from the saved SR; E set
	and.b	#$F0,d7
	move.b	SR_SR+1(a6),d6
	and.b	#$0F,d6
	or.b	d6,d7
	or.b	#$80,d7
	move.b	d7,-(a5)
	or.b	#$90,SCCHI(a6)		; E I
	move.w	SR_SR(a6),d7
	move.w	d7,ccr
	jmp	SUB_IRQ

sub_restore:
	movem.l	SR_D0(a6),d0-d4
	move.l	SR_A5(a6),a5
	move.l	SVB+8(a6),a3
	move.l	SVB+12(a6),a4
	move.l	SPB+28(a6),a2
	rts

; ---- the hooks (gen_sub.HOOKS) ----
sub_hook_idle:				; F0B6 BRA self: back to the runtime (the 68000 stack is as sub_enter_* left it)
	move.w	sr,d5
	move.w	d5,SR_SR(a6)
	movem.l	d0-d4,SR_D0(a6)
	move.l	a5,SR_A5(a6)
	rts

sub_hook_F0CA:				; LDA $6701; BEQ F0CA: the main CPU's NMI ran already (machine.GyrussPort)
	jmp	SUB_F0CF

; ---- the dispatcher: d7.w = a 6809 pc, through the table of the page in its slot; the CCR kept ----
sub_dispatch:
	move.w	sr,d5
	move.w	d7,d6
	rol.w	#3,d6
	and.w	#7,d6
	add.w	d6,d6
	add.w	d6,d6
	move.l	STBL(a6,d6.w),a0
	and.w	#$1FFF,d7
	add.w	d7,d7
	moveq	#0,d6
	move.w	(a0,d7.w),d6
	add.l	d6,d6
	move.l	-4(a0),a0		; (the page's base)
	move.w	d5,ccr
	jmp	(a0,d6.l)

sub_bad_stub:
sub_badpc:
sub_unsupported:
	move.w	d7,badpc
	ifd	SIM
.l:	bra.s	.l
	endc
	move.w	#98,d0
	bra	crash_common

; ---- I/O: d7.w = the address; sub_io_r: the byte in d7 (long: the upper bits 0); sub_io_w: d5.b = the value.  Every
; other register kept. ----
; BEAM: d7 = the beam's next line (sub_line, sub_acc, sub_reads advanced; the shadow taken at the first read)
BEAM	macro
	move.l	sub_acc,d7
	add.l	#154,sub_acc
	lsr.l	#8,d7
	add.w	#25,d7
	cmp.w	#239,d7
	bls.s	.l\@
	move.w	#239,d7
.l\@:	move.w	d7,sub_line
	addq.w	#1,sub_reads
	tst.b	shadow_ok
	bne.s	.s\@
	bsr	sub_shadow
.s\@:
	endm

sub_shadow:
	st	shadow_ok
	movem.l	d0/a0-a1,-(sp)
	lea	sub_ram+$40,a0
	lea	spr_shadow,a1
	moveq	#48-1,d0
.c:	move.l	(a0)+,(a1)+
	dbf	d0,.c
	movem.l	(sp)+,d0/a0-a1
	rts

; The scans for an entry whose sprite the beam has passed (F6A2 / F6FB, gen_sub.NATIVES): LDA >$0000; ADDA $3,U;
; BCS found; LEAU 4,U; CMPU #$4100; BCS again; RTS.  A, U and the flags as the loop leaves them (found: C set).
SCAN	macro				; \1 = found, \2 = the RTS
.l\@:	BEAM
	move.b	d7,d0
	add.b	3(a3,d4.l),d0
	bcs.s	.f\@
	addq.w	#4,d4
	cmp.w	#$4100,d4
	bcs.s	.l\@
	move	#$04,ccr		; (CMPU: equal)
	jmp	\2
.f\@:	jmp	\1
	endm
; The first phase's copy (F48B: the lists from $64C0, the objects from $6000; F4E4: $65C0, $6200): <$00 / <$01 the
; pointer into the lists (a count of objects, then their numbers, per group), <$09 the group's count, <$0A the entries
; left (48), <$0B the group (4); each object's 4 bytes (at data + 4 n) into the next sprite entry; when the groups end,
; the rest's y bytes cleared.  A, B, X, U and the flags (Z: <$0A ran out; N V C clear) as the 6809 code leaves them,
; then its RTS.
COPY	macro				; \1 = the lists, \2 = the objects, \3 = the RTS
	lea	$4200(a3),a0		; (the direct page)
	move.b	\1(a4),d0
	move.b	d0,9(a0)
	move.b	#(\1+1)>>8,(a0)
	move.b	#(\1+1)&255,1(a0)
	move.w	#$4040,d4
	clr.b	11(a0)
	move.b	#$30,10(a0)
.g\@:	cmp.b	#4,11(a0)		; F4F6: the groups done?
	bcc.s	.c\@
.o\@:	tst.b	9(a0)			; F4FC
	beq.s	.n\@
	moveq	#0,d7
	move.b	(a0),d7
	lsl.w	#8,d7
	move.b	1(a0),d7
	moveq	#0,d2
	move.b	(a4,d7.l),d1		; LDB [$4200]
	move.b	d1,d2
	lsl.w	#2,d2
	add.w	#\2,d2			; X = the object
	move.l	(a4,d2.l),0(a3,d4.l)
	move.b	2(a4,d2.l),d0		; (A B: the second LDD)
	move.b	3(a4,d2.l),d1
	addq.w	#2,d2
	addq.w	#4,d4
	addq.b	#1,1(a0)
	subq.b	#1,9(a0)
	subq.b	#1,10(a0)
	bne.s	.o\@
	bra.s	.r\@
.n\@:	move.b	1(a0),d0		; F529: the next group
	and.b	#$C0,d0
	sub.b	#$40,d0
	move.b	d0,1(a0)
	moveq	#0,d7
	move.b	(a0),d7
	lsl.w	#8,d7
	move.b	d0,d7
	move.b	(a4,d7.l),d0		; LDA [$4200]
	move.b	d0,9(a0)
	addq.b	#1,1(a0)
	addq.b	#1,11(a0)
	bra.s	.g\@
.c\@:	moveq	#0,d0			; F51F: the rest's y bytes
.cl\@:	clr.b	3(a3,d4.l)
	addq.w	#4,d4
	subq.b	#1,10(a0)
	bne.s	.cl\@
.r\@:	move	#$04,ccr
	jmp	\3
	endm
native_copy_F48B:
	COPY	$64C0,$6000,SUB_F4C5
native_copy_F4E4:
	COPY	$65C0,$6200,SUB_F51E

native_scan_F6A2:
	SCAN	SUB_F6B2,SUB_F6B1
native_scan_F6FB:
	SCAN	SUB_F70B,SUB_F70A

sub_io_r:
	tst.w	d7
	bne.s	.z
	; the beam (machine.GyrussPort.beam): 25 + 0.6 k at the k-th read of the IRQ, at most 239 (sub_acc = 154 k); the
	; first read keeps the sprite RAM as the first phase left it (spr_shadow: the bands' log starts from it)
	BEAM
.r:	rts
.z:	moveq	#0,d7
	rts

; sub_spr_seg: after the second STD of an entry given to another object (F6CA / F723, gen_sub.AFTER; U = the entry +
; 4): the entry's old content and the beam's line into the log (its chain per entry: seg_head / seg_next), the shadow
; updated.  Keeps every register and the flags.
sub_spr_seg:
	move	sr,-(sp)
	movem.l	d0-d2/a0-a1,-(sp)
	move.w	d4,d0
	sub.w	#$4044,d0		; the entry's offset (entry * 4)
	lea	spr_shadow,a0
	lea	sub_ram+$40,a1
	move.w	seg_n,d1
	cmp.w	#SEG_MAX,d1
	bhs.s	.full
	move.w	d1,d2
	lsl.w	#3,d2
	lea	seg_list,a1
	add.w	d2,a1
	move.l	(a0,d0.w),(a1)+		; (old content.l, line.w, next.w)
	move.w	sub_line,(a1)+
	clr.w	(a1)
	addq.w	#1,d1
	move.w	d1,seg_n
	lsr.w	#1,d0			; (entry * 2: the chains' words)
	lea	seg_head,a1
	tst.w	(a1,d0.w)
	bne.s	.tail
	move.w	d1,(a1,d0.w)
	bra.s	.t
.tail:	lea	seg_tail,a1
	move.w	(a1,d0.w),d2		; the entry's last segment (1-based): its next
	lsl.w	#3,d2
	lea	seg_list-2,a0
	move.w	d1,(a0,d2.w)
	lea	spr_shadow,a0
.t:	lea	seg_tail,a1
	move.w	d1,(a1,d0.w)
	add.w	d0,d0
	lea	sub_ram+$40,a1
.full:	move.l	(a1,d0.w),(a0,d0.w)	; the shadow: the new content
	movem.l	(sp)+,d0-d2/a0-a1
	move	(sp)+,ccr
	rts

; sub_frame_start: the bands' log empty (a frame without the sub's IRQ draws its sprite RAM as it is)
sub_frame_start:
	clr.w	seg_n
	sf	shadow_ok
	movem.l	d0/a0,-(sp)
	lea	seg_head,a0
	moveq	#48/2-1,d0
.c:	clr.l	(a0)+
	dbf	d0,.c
	movem.l	(sp)+,d0/a0
	rts

sub_io_w:
	cmp.w	#$2000,d7
	bne.s	.n
	move.b	d5,sub_mask
	and.b	#1,sub_mask
.n:	rts

	include	"natives.s"
	include	"code_sub.s"
	include	"tables_sub.s"

	section data,data
	even
	dc.l	sub_bad_stub
sub_bad_table:
	dcb.w	8192,0
sub_rom:
	incbin	"sub.rom"

	section bss,bss
	even
sub_ctx:	ds.b	SCTXSIZE
sub_ram:	ds.b	$2000		; $4000-$5FFF ($4000-$47FF the RAM, $4040-$40FF the sprite RAM)
sub_null:	ds.b	$2000		; the slots with nothing (reads 0)
badpc:		ds.w	1
sub_reads:	ds.w	1		; the beam's reads in this IRQ
sub_acc:	ds.l	1		; 154 x the reads
sub_line:	ds.w	1		; the beam's line at the last one
seg_n:		ds.w	1
seg_head:	ds.w	48		; per entry: its first segment (1-based; 0 none)
seg_tail:	ds.w	48		; its last
seg_list:	ds.b	SEG_MAX*8	; (old content.l, line.w, next.w: 1-based, 0 the last)
spr_shadow:	ds.b	192		; the sprite RAM as the log has it
shadow_ok:	ds.b	1
sub_mask:	ds.b	1		; $2000 bit 0: the IRQ mask
	even
