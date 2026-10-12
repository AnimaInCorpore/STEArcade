; ------------------------------------------------------------------------------
; Hand-written 68000 routines that replace Z80 code (tools/gen.py SUB_NATIVES; the translated code jumps here from
; the replaced pc's label).  Each leaves the registers, memory and the flags the code after it reads as the Z80
; code would (z80x register map: A d0, BC d1 (B in the low byte), DE d2, HL d3, IX d4, F d6 in the CCR format,
; BC' DE' HL' a0-a2, IY in memory; the sub CPU: a6 = its block, long offsets, a5 the Z80 stack, a4 its dispatch
; table).  BB_NO_NATIVES=1 builds the translation alone.
; ------------------------------------------------------------------------------

Y_IY = g_ram+$3FF8			; (IY_SUB)

; The sub CPU's $0849-$089B (an entry of the jump table at $0785, reached from the object loop $03CF with IX one of
; the objects at $E76C, 40 bytes each): the count of the ($E76B) objects near IX:
;
;	for IY in the objects: unless IX+33 has bit 4 or 5, skip IY when (IY+0) & $1D = 0;
;	skip it when IY+29 = IX+29, |IY+2 - IX+2| >= 13, IY+1 - IX+1 not in 0..12;
;	else IY+19 += 1, and once more when IY+30 bit 0.
;
; IX+33 is read once (the loop writes only IY+19 of objects 40 bytes apart, IX among them): the loop without the
; test of (IY+0) when it has bit 4 or 5.  The ret reads S Z C (its return point is reached by jp (hl)): they are those
; of the translation (the last flag op of the last object, C of the last add iy,de: 0, the objects do not cross
; $FFFF; when they would, the translated code runs).  Translated: ~210 cycles an object; here ~50.

near_cand	macro			; \1: the next object
	move.b	29(a6,d4.l),d0		; ld a,(ix+29)
	cmp.b	29(a3),d0		; cp a,(iy+29)
	move	sr,d6
	beq.s	\1
	move.b	2(a3),d0		; ld a,(iy+2)
	sub.b	2(a6,d4.l),d0		; sub a,(ix+2)
	bpl.s	.p\@
	neg.b	d0
.p\@:	cmp.b	#$0D,d0
	move	sr,d6
	bcc.s	\1
	move.b	1(a3),d0		; ld a,(iy+1)
	sub.b	1(a6,d4.l),d0		; sub a,(ix+1)
	move	sr,d6
	bmi.s	\1
	cmp.b	#$0D,d0
	move	sr,d6
	bcc.s	\1
	addq.b	#1,19(a3)		; inc (iy+19)
	move	sr,d6
	btst	#0,30(a3)		; bit $00,(iy+30): Z into F
	move	sr,d7
	eor.b	d6,d7
	and.b	#$04,d7
	eor.b	d7,d6
	move	d6,ccr
	beq.s	\1
	addq.b	#1,19(a3)		; inc (iy+19)
	move	sr,d6
	endm

y_near:
	move.b	g_ram+$676B,d0		; ld a,($E76B)
	move.b	d0,d1			; ld b,a
	moveq	#0,d5
	move.b	d0,d5
	subq.b	#1,d5			; (djnz: B = 0 runs 256 times; dbf counts d5 + 1)
	cmp.w	#155,d5			; (IY + 30 of the last object past $FFFF: the translation)
	bhi	.translated
	move.l	#$E76C,d7
	lea	(a6,d7.l),a3		; a3 = IY
	move.b	33(a6,d4.l),d7		; ld a,(ix+33): bit 4 or 5?
	and.b	#$30,d7
	bne	.all
.lp:	move.b	(a3),d0			; ld a,(iy+0)
	and.b	#$1D,d0			; and a,$1D
	move	sr,d6
	bne.s	.cand			; (jr z: the next object)
.nx:	lea	40(a3),a3		; add iy,de
	dbf	d5,.lp			; djnz
	bra	.done
.cand:	near_cand .nx
	lea	40(a3),a3
	dbf	d5,.lp
	bra	.done

.all:	near_cand .nxa			; (ld a,(ix+33) is overwritten by ld a,(ix+29))
.nxa:	lea	40(a3),a3
	dbf	d5,.all

.done:	and.b	#$FE,d6			; (C of add iy,de)
	move.l	a3,d7
	sub.l	a6,d7
	move.w	d7,Y_IY			; IY
	clr.b	d1			; B
	moveq	#40,d2			; DE
	moveq	#0,d7			; ret
	move.w	(a5)+,d7
	lsl.l	#2,d7
	move.l	0(a4,d7.l),a3
	jmp	(a3)

.translated:
	move.w	#$E76C,Y_IY		; ld iy,$E76C
	jmp	Y084D

; The objects' state dispatch of both CPUs: the main CPU's $5C37-$5C75 and the sub CPU's $03CF-$03F9, the head of
; a loop over the objects at $E76C (IX).  `push af` (the loop counter, as the translation stores it: popped by the
; translated tail), then the first set bit of a list of bits of (IX+33) and (IX+0) picks the handler.  The
; translation pays a flag merge (`bit` puts Z into F) and a `move d6,ccr` per test, ~58 cycles, 11 (8) tests for an
; object with none of them; here an object with no bit set costs two tests.  Left as the translation leaves them:
; A (the byte the last test read), F (Z of the last test: clear at a handler, set at the end; the rest as it was),
; the CCR = F (the handlers' code may branch on it).

state_push	macro			; push af (z80x: F in the Z80 format on the Z80 stack)
	move.b	d6,d7
	andi.b	#$0C,d7
	lsl.b	#4,d7
	move.b	d6,d5
	andi.b	#1,d5
	or.b	d5,d7
	move.b	d0,-(a5)
	move.b	d7,-(a5)
	endm

state_go	macro			; a bit was set: \1 its handler
	and.b	#$FB,d6			; (Z clear)
	move	d6,ccr
	jmp	\1
	endm

z_state:				; main CPU $5C37
	state_push
	move.b	33(a6,d4.w),d0		; ld a,(ix+33): bits 7, 5, 6
	move.b	d0,d7
	and.b	#$E0,d7
	bne.s	.hi
	move.b	(a6,d4.w),d0		; ld a,(ix+0): bits 0, 1, 2, 3, 4, 6, 5, 7
	bne.s	.lo
.none:	or.b	#$04,d6			; (Z set)
	move	d6,ccr
	jmp	Z6D8B
.hi:	btst	#7,d0
	bne.s	.h7
	btst	#5,d0
	bne.s	.h5
	state_go Z6559			; (bit 6)
.h7:	state_go Z5CE8
.h5:	state_go Z5C78
.lo:	btst	#0,d0
	bne.s	.l0
	btst	#1,d0
	bne.s	.l1
	btst	#2,d0
	bne.s	.l2
	btst	#3,d0
	bne.s	.l3
	btst	#4,d0
	bne.s	.l4
	btst	#6,d0
	bne.s	.l6
	btst	#5,d0
	bne.s	.l5
	state_go Z5F96			; (bit 7)
.l0:	state_go Z5D57
.l1:	state_go Z5D96
.l2:	state_go Z5E10
.l3:	state_go Z5EB1
.l4:	state_go Z5F0B
.l6:	state_go Z663D
.l5:	state_go Z66CA

y_state:				; sub CPU $03CF
	state_push
	move.b	(a6,d4.l),d0		; ld a,(ix+0): bits 0, 2, 3, 4, 5
	move.b	d0,d7
	and.b	#$3D,d7
	bne.s	.lo
	move.b	33(a6,d4.l),d0		; ld a,(ix+33): bits 6, 5
	move.b	d0,d7
	and.b	#$60,d7
	bne.s	.hi
	or.b	#$04,d6			; (Z set)
	move	d6,ccr
	jmp	Y0635
.lo:	btst	#0,d0
	bne.s	.l0
	btst	#2,d0
	bne.s	.l2
	btst	#3,d0
	bne.s	.l3
	btst	#4,d0
	bne.s	.l4
	state_go Y04EC			; (bit 5)
.l0:	state_go Y03FC
.l2:	state_go Y0433
.l3:	state_go Y047E
.l4:	state_go Y04B5
.hi:	btst	#6,d0
	bne.s	.h6
	state_go Y05C7			; (bit 5)
.h6:	state_go Y05FE
