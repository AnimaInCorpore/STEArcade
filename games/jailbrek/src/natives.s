; Jail Break's hand-written replacements of 6809 routines (included by jailbrek.s; gen.py NATIVES).  Registers as the
; translation keeps them: d0 = A, d1 = B, d2 = X, d3 = Y, d4 = U (words, the upper words 0), a4 = jb_mem, a5 = the 6809
; stack; scratch d5-d7 and a0.  tools/native_test.py runs each against the 6809.

; nat_9272: the 6809's $9272-$92C0 (frame_sprites, once an arcade frame): the eight objects of $40 bytes at $11C0-$13BF
; copied to the sprite RAM at X ($1000 or $1100) by their priority byte ($10) 1 .. 8 (an object after the others of its
; priority), 16 bytes each (the words $E, $4/$6, $1E, $14/$16, $2E, $24/$26, $3E, $34/$36).  The 6809 loops 8 x 8 times; the
; state at $92C2: A 9, B the last object's byte $36, X after the copies, U $11C0, N Z V C from CMPA #9.
nat_9272:
	lea	(a4,d2.l),a0		; X
	moveq	#1,d5			; the priority
.pri:	move.l	#$11C0,d7		; the object
	moveq	#8-1,d6
.obj:	cmp.b	$10(a4,d7.l),d5
	bne.s	.skip
	move.w	$E(a4,d7.l),(a0)+
	move.b	4(a4,d7.l),(a0)+
	move.b	6(a4,d7.l),(a0)+
	move.w	$1E(a4,d7.l),(a0)+
	move.b	$14(a4,d7.l),(a0)+
	move.b	$16(a4,d7.l),(a0)+
	move.w	$2E(a4,d7.l),(a0)+
	move.b	$24(a4,d7.l),(a0)+
	move.b	$26(a4,d7.l),(a0)+
	move.w	$3E(a4,d7.l),(a0)+
	move.b	$34(a4,d7.l),(a0)+
	move.b	$36(a4,d7.l),d1
	move.b	d1,(a0)+
.skip:	add.l	#$40,d7
	dbf	d6,.obj
	addq.b	#1,d5
	cmp.b	#9,d5
	bne.s	.pri
	move.l	a0,d2
	sub.l	a4,d2			; X
	move.w	#$11C0,d4		; U
	moveq	#9,d0			; A
	cmp.b	#9,d0
	jmp	M0092C2
