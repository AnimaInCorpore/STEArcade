; Natives: hand-written 68000 code for hot Z80 routines (tools/gen.py NATIVES: the translation jumps here at the
; routine's pc; the translated code stays for its other entries).  Each leaves the registers and the memory as the Z80
; code would and continues where it would (tools/native_test.py checks them against the Z80).  Registers as
; engine/z80x.py keeps them: d0.b A, d1.w BC (B in the low byte), d2.w DE, d3.w HL (the upper words: BC', DE', HL'),
; d4 IX, a2 IY, a5 SP, a6 the block (a signed word index; $8000-$BFFF through g_winbase); d5, d7, a0, a1 scratch.

; nat_1e95: $1E95-$1EA1: `ex de,hl`, then B times `push bc / ldi / ld bc,3 / ex de,hl / add hl,bc / ex de,hl / pop bc /
; djnz`: B bytes from DE on to HL on, 4 bytes apart; continues at the `ret` ($1EA2).  HL = DE + B, DE = HL + 4 B,
; B = 0, C kept (the flags are dead there: the translation leaves them too).  The fast path when the source does not
; cross into or out of the bank window ($8000-$BFFF: g_winbase), the destination's index does not wrap and neither
; touches the word the loop pushes below SP; else the translated loop.
nat_1e95:
	move.w d2,d7			; ex de,hl
	move.w d3,d2
	move.w d7,d3
	moveq #0,d7
	move.b d1,d7			; B (0: 256)
	bne.s .n
	move.w #256,d7
.n:	; the source: from HL, B bytes in one part (the window, or the block around it: $C000 .. $7FFF)
	move.w d3,d5
	sub.w #$8000,d5
	cmp.w #$4000,d5
	bhs.s .blk
	add.w d7,d5			; (in the window: its offset + B - 1 < $4000)
	cmp.w #$4000,d5
	bhi.s .slow
	move.l g_winbase,a0
	bra.s .src
.blk:	move.w d3,d5
	sub.w #$C000,d5			; (the block's part: its offset from $C000 + B - 1 < $C000)
	add.w d7,d5
	bcs.s .slow
	cmp.w #$C000,d5
	bhi.s .slow
	lea (a6),a0
.src:	add.w d3,a0			; (a signed index)
	; (the copy must not read the word the loop pushes below SP: else the translated loop)
	move.l a0,d5
	add.l d7,d5
	addq.l #2,d5
	cmp.l a5,d5
	bls.s .sok			; (it ends below SP - 2)
	cmp.l a5,a0
	blo.s .slow			; (it starts below SP)
.sok:
	; the destination: DE + 4 (B - 1) without the signed index wrapping
	move.w d2,d5
	ext.l d5
	move.l d7,a1
	add.l a1,a1
	add.l a1,a1
	add.l a1,d5
	subq.l #4,d5
	cmp.l #$7fff,d5
	bgt.s .slow
	lea (a6),a1
	add.w d2,a1
	; (nor write it)
	move.l d7,d5
	add.l d5,d5
	add.l d5,d5
	subq.l #2,d5
	add.l a1,d5			; (the last byte written + 2)
	cmp.l a5,d5
	blo.s .dok
	cmp.l a5,a1
	blo.s .slow
.dok:	add.w d7,d3			; HL + B
	move.w d7,d5
	add.w d5,d5
	add.w d5,d5
	add.w d5,d2			; DE + 4 B
	subq.w #1,d7
.cp:	move.b (a0)+,(a1)
	addq.l #4,a1
	dbf d7,.cp
	clr.b d1			; (B = 0, C kept)
	bra Z1EA2
.slow:	bra Z1E96
