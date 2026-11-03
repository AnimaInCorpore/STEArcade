; The ROM's E5CD handler: scroll a decorative object in x and emit its sprite.
; Keep the original cleanup/screen tests, registers and V30 stack residues.

	section text,code
nat_nh_e5cd:
	btst #0,d6
	bne R0E9CD_t
	tst.b $2FC5(a3)
	bne R0E9F7
	lea (a4,d6.l),a0
	move.w $30(a0),d0
	POSADD 4
	move.w $34(a0),d3
	move.w #$E5E0,-2(a5)
	NH_EMIT
	jmp R0E9E0
