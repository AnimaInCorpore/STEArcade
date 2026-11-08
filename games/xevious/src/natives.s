; ------------------------------------------------------------------------------
; Hand-written 68000 routines that replace Z80 code (tools/gen.py NATIVES; the translated code jumps here from the
; replaced pc's label).  Register map: see xevious.s (sub CPU: a6 = g_block, long offsets, a5 the Z80 stack, a4 its
; dispatch table; BC' DE' HL' in the upper words of d1-d3, so d1-d3 keep their upper words).  XEV_NO_NATIVES=1 builds
; the translation alone.
; ------------------------------------------------------------------------------

; The sub CPU's $04ED-$0500 (a task of the table at $82C0, with its helpers $0501-$0582): the 64 sprite entries of two
; bytes at $7900+2k (pages $79 $7A $7B $7C) converted to $8100/$8200/$8300+2k.  Per entry (flag = (79,2k):
;	flag = 1: skipped.
;	flag = 0: (7A,2k) (7A,2k+1) (7B,2k+1) (7B,2k) cleared, (79,2k) = 1.
;	c = (79,2k+1); (83,2k) = c.
;	v1 = word (7A,2k); x = v1 >> 5, 0 when v1 >> 13 >= 2; ($8003) = 0: x += 8, else x = $148 (c bit 0) or $158 - x.
;	v2 = word (7B,2k); y = v2 >> 5, its low byte 0 when v2 >> 13 != 0; ($8003) = 0: a = $EF - y.l, else a = $EF + y.l (+ $10
;	when c bit 1 is clear).
;	(83,2k+1) = x.h, (82,2k+1) = x.l, (82,2k) = a, (81,2k) = (7C,2k), (81,2k+1) = (7C,2k+1).
; The task is a dispatch of the loop at $0371: A, F, HL, DE are dead at its ret, BC is popped by the caller.  Translated:
; 22k cycles a frame of 171k.

y_sprconv:
	lea	$7900(a6),a0
	moveq	#63,d5
	tst.b	g_ram+$0003
	bne	.m1
.l0:	move.b	(a0),d7
	subq.b	#1,d7
	beq	.n0
	addq.b	#1,d7
	bne.s	.nz0
	clr.b	$100(a0)
	clr.b	$101(a0)
	clr.b	$201(a0)
	clr.b	$200(a0)
	move.b	#1,(a0)
.nz0:	move.b	1(a0),d1
	move.b	d1,$A00(a0)
	moveq	#0,d7
	move.b	$101(a0),d7
	lsl.w	#8,d7
	move.b	$100(a0),d7
	lsr.w	#5,d7
	cmp.w	#$200,d7
	bcs.s	.x0
	moveq	#0,d7
.x0:	addq.w	#8,d7			; x
	move.b	d7,$901(a0)
	lsr.w	#8,d7
	move.b	d7,$A01(a0)
	moveq	#0,d7
	move.b	$201(a0),d7
	lsl.w	#8,d7
	move.b	$200(a0),d7
	lsr.w	#5,d7
	cmp.w	#$100,d7
	bcs.s	.y0
	clr.b	d7
.y0:	move.b	#$EF,d6
	sub.b	d7,d6
	move.b	d6,$900(a0)
	move.b	$300(a0),$800(a0)
	move.b	$301(a0),$801(a0)
.n0:	addq.l	#2,a0
	dbf	d5,.l0
	bra	.ret
.m1:
.l1:	move.b	(a0),d7
	subq.b	#1,d7
	beq	.n1
	addq.b	#1,d7
	bne.s	.nz1
	clr.b	$100(a0)
	clr.b	$101(a0)
	clr.b	$201(a0)
	clr.b	$200(a0)
	move.b	#1,(a0)
.nz1:	move.b	1(a0),d1
	move.b	d1,$A00(a0)
	moveq	#0,d7
	move.b	$101(a0),d7
	lsl.w	#8,d7
	move.b	$100(a0),d7
	lsr.w	#5,d7
	cmp.w	#$200,d7
	bcs.s	.x1
	moveq	#0,d7
.x1:	move.w	#$158,d6
	btst	#0,d1
	beq.s	.c1
	move.w	#$148,d6
.c1:	sub.w	d7,d6			; x
	move.b	d6,$901(a0)
	lsr.w	#8,d6
	move.b	d6,$A01(a0)
	moveq	#0,d7
	move.b	$201(a0),d7
	lsl.w	#8,d7
	move.b	$200(a0),d7
	lsr.w	#5,d7
	cmp.w	#$100,d7
	bcs.s	.y1
	clr.b	d7
.y1:	add.b	#$EF,d7
	btst	#1,d1
	bne.s	.e1
	add.b	#$10,d7
.e1:	move.b	d7,$900(a0)
	move.b	$300(a0),$800(a0)
	move.b	$301(a0),$801(a0)
.n1:	addq.l	#2,a0
	dbf	d5,.l1
.ret:	moveq	#0,d7				; ret
	move.w	(a5)+,d7
	lsl.l	#2,d7
	move.l	0(a4,d7.l),a3
	jmp	(a3)

; The main CPU's $0469-$046F (the task loop's call of the slot at IX: ld l,(ix+0); ld h,(ix+1); jp (hl)): the dispatch
; table is indexed by the address with its bytes swapped, which is how the two bytes lie in memory.  HL is kept.
z_task:
	moveq	#0,d7
	move.w	(a6,d4.w),d7
	move.w	d7,d3
	ror.w	#8,d3
	lsl.l	#2,d7
	move.l	0(a4,d7.l),a3
	jmp	(a3)

; The main CPU's task loops call a handler through the slot's address (jp (hl) at $0469): the slots at $8280 (the
; loop $045A, 32 slots) and the object slots at $7800 / $784E ($305E, $306D).  Two handlers are quick and common:
; $001F (a ret) and $307A (an object slot: ret z when the byte at $7F00+IXL is 0).  Those are skipped without the call:
; the registers they would change are dead at the loop's next slot (A, DE, HL, F), the stack words are below SP.
slot_dispatch	macro			; \1: the token the call pushes
	move.w	#\1,-(a5)
	move.w	d7,d3
	ror.w	#8,d3
	lsl.l	#2,d7
	move.l	0(a4,d7.l),a3
	jmp	(a3)
	endm

z_slot:					; $045C: push bc; call $0469
	moveq	#0,d7
	move.w	(a6,d4.w),d7
	cmp.w	#$1F00,d7
	bne.s	.d
	addq.w	#2,d4			; inc ix, inc ix
	subq.b	#1,d1			; djnz
	bne	z_slot
	bra	Z044C
.d:	move.w	d1,-(a5)
	slot_dispatch	$6004

obj_slot	macro			; \1: the token, \2: the code after the call
	moveq	#0,d7
	move.w	(a6,d4.w),d7
	cmp.w	#$7A30,d7
	bne.s	.n\@
	moveq	#0,d5
	move.b	d4,d5
	lea	$7F00(a6),a0
	tst.b	(a0,d5.w)
	beq	\2
	bra.s	.d\@
.n\@:	cmp.w	#$1F00,d7
	beq	\2
.d\@:	slot_dispatch	\1
	endm

z_obj_a:
	obj_slot	$6130,Z3061
z_obj_b:
	obj_slot	$7030,Z3070
