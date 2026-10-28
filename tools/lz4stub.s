; The self-unpacking stub of an LZ4-packed TOS program (tools/lz4prg.py appends the parameters and the frame).
; Position independent, assembled with vasm -Fbin.  Offsets from the text start T (see tools/lz4prg.py):
;   the stub copies itself to T+X, moves the frame (the data segment) to T+D, unpacks it to T, relocates the game,
;   clears T+TLEN+DLEN .. T+CLEAR_END, sets the basepage to the game's segments and jumps to T.
; While it unpacks, a bar shows the progress: a VBL handler (Setexc, chained to TOS's) reads the depacker's output
; pointer (a1) from the interrupted registers, so the depacker itself runs as fast as without it.  The bar is
; drawn in whole bytes of the Physbase screen (all planes set): low, medium and high resolution alike.

PR_D		equ	0			; the parameters, longs at the stub's end (lz4prg.PARAMS)
PR_X		equ	4
PR_P		equ	8
PR_TLEN		equ	12
PR_DLEN		equ	16
PR_BLEN		equ	20
PR_CLEAR	equ	24
PR_S		equ	28

start:
	move.l	4(sp),a5		; basepage
	move.l	8(a5),a6		; p_tbase: T
	bsr.s	params			; a4: the parameters (the text's last 32 bytes)
	lea	start(pc),a0		; copy the stub to T + X
	move.l	PR_X(a4),a1
	add.l	a6,a1
	move.l	PR_S(a4),d0
	lsr.l	#2,d0
	subq.w	#1,d0
.copy:	move.l	(a0)+,(a1)+		; (the stub is < 256 KB)
	dbra	d0,.copy
	move.l	PR_X(a4),a0
	add.l	a6,a0
	jmp	stage2-start(a0)

params:	lea	start(pc),a4		; a4 = this copy's start + p_tlen - 32
	add.l	12(a5),a4
	lea	-32(a4),a4
	rts

stage2:
	bsr.s	params			; (the copy's)
	bsr	bar_init
	; move the frame up: from T + S .. to T + D .., from its end down
	move.l	PR_P(a4),d0
	move.l	16(a5),a0		; p_dbase = T + S
	add.l	d0,a0
	move.l	PR_D(a4),a1
	add.l	a6,a1
	add.l	d0,a1
	moveq	#40,d1
	divu	d1,d0			; (P < 40 * 65536)
	swap	d0			; the remainder (a multiple of 4) first
	lsr.w	#2,d0
	bra.s	.rest
.long:	move.l	-(a0),-(a1)
.rest:	dbra	d0,.long
	swap	d0
	bra.s	.next
.block:	lea	-40(a0),a0
	movem.l	(a0),d1-d7/a2-a3/a5
	movem.l	d1-d7/a2-a3/a5,-(a1)
.next:	dbra	d0,.block
	move.l	4(sp),a5		; (a5 was used by movem)
	; a1 = T + D: unpack to T
	move.l	a1,a0
	move.l	a6,a1
	lea	vars(pc),a3
	move.l	a6,V_T(a3)
	st	V_ACTIVE(a3)
	bsr	lz4_decode
	lea	vars(pc),a3
	sf	V_ACTIVE(a3)
	move.l	V_OLD(a3),-(sp)		; the VBL vector back: Setexc(28, old)
	move.l	#$0005001c,-(sp)
	trap	#13
	addq.l	#8,sp
	lea	vars(pc),a3
	move.w	V_W(a3),d0		; the bar full
	bsr	bar_to
	bsr	params			; (lz4_decode uses a4)
	; relocate: the table follows the text and data
	move.l	a6,a0
	add.l	PR_TLEN(a4),a0
	add.l	PR_DLEN(a4),a0
	move.l	a0,a3			; the BSS start
	move.l	(a0)+,d0
	beq.s	.cleared
	move.l	a6,d1
	move.l	a6,a1
	add.l	d0,a1
	add.l	d1,(a1)
	moveq	#0,d0
.reloc:	move.b	(a0)+,d0
	beq.s	.cleared
	cmp.b	#1,d0
	bne.s	.fix
	lea	254(a1),a1
	bra.s	.reloc
.fix:	add.l	d0,a1
	add.l	d1,(a1)
	bra.s	.reloc
.cleared:
	; clear T + TLEN + DLEN .. T + CLEAR_END (the table, the frame, the stub as loaded; TOS cleared the rest)
	move.l	PR_CLEAR(a4),d1
	add.l	a6,d1
	sub.l	a3,d1			; bytes (even)
	bls.s	.base
	moveq	#0,d0
	lsr.l	#1,d1
	lsr.l	#1,d1
	bcc.s	.c4
	move.w	d0,(a3)+
.c4:	tst.l	d1
	beq.s	.base
.clr:	move.l	d0,(a3)+
	subq.l	#1,d1
	bne.s	.clr
.base:	; the basepage: the game's segments
	move.l	PR_TLEN(a4),d0
	move.l	d0,12(a5)		; p_tlen
	add.l	a6,d0
	move.l	d0,16(a5)		; p_dbase
	move.l	PR_DLEN(a4),d1
	move.l	d1,20(a5)		; p_dlen
	add.l	d1,d0
	move.l	d0,24(a5)		; p_bbase
	move.l	PR_BLEN(a4),28(a5)	; p_blen
	moveq	#0,d0
	moveq	#0,d1
	sub.l	a0,a0			; (as TOS starts a program: a0 = 0)
	jmp	(a6)

; --- the progress bar ---------------------------------------------------------------------------------------------
V_BAR		equ	0			; long: the bar's first byte on the screen
V_T		equ	4			; long: the output's start
V_OLD		equ	8			; long: TOS's VBL handler
V_BPL		equ	12			; word: bytes a line
V_H		equ	14			; word: the bar's lines - 1
V_W		equ	16			; word: the bar's bytes
V_PER		equ	18			; word: output bytes / 16 a bar byte
V_DONE		equ	20			; word: bytes drawn
V_ACTIVE	equ	22			; byte: the depacker runs (a1 = output)
V_MASK		equ	24			; word: whole 16-pixel groups (-8 low, -4 medium, -2 high)

bar_init:				; (TOS keeps d3-d7/a3-a6)
	lea	vars(pc),a3
	move.w	#2,-(sp)		; Physbase
	trap	#14
	addq.l	#2,sp
	move.l	d0,V_BAR(a3)
	move.w	#4,-(sp)		; Getrez
	trap	#14
	addq.l	#2,sp
	moveq	#80,d1			; high: 80 bytes a line, the bar at line 192, 16 lines high, text column 16
	move.w	#192,d2
	moveq	#16-1,d3
	moveq	#16,d4
	moveq	#-2,d5
	cmp.w	#2,d0
	beq.s	.res
	move.w	#160,d1			; low and medium: 160 bytes a line, line 96, 8 lines; column 4 / 8
	moveq	#96,d2
	moveq	#8-1,d3
	moveq	#4,d4
	moveq	#-8,d5
	tst.w	d0
	beq.s	.res
	moveq	#8,d4
	moveq	#-4,d5
.res:	move.w	d5,V_MASK(a3)
	move.w	d1,V_BPL(a3)
	move.w	d3,V_H(a3)
	lea	text_col(pc),a0
	add.b	d4,(a0)
	mulu	d1,d2			; the bar's start: line y, byte 16
	add.l	d2,V_BAR(a3)
	moveq	#16,d0
	add.l	d0,V_BAR(a3)
	sub.w	#32,d1			; the bar's width: the line - 32 bytes
	move.w	d1,V_W(a3)
	move.l	PR_CLEAR(a4),d0		; (the unpacked size, to within the frame's tail)
	lsr.l	#4,d0
	divu	d1,d0
	addq.w	#1,d0
	move.w	d0,V_PER(a3)
	clr.w	V_DONE(a3)
	sf	V_ACTIVE(a3)
	pea	text(pc)		; Cconws: clear the screen, the cursor off, "Unpacking..." above the bar
	move.w	#9,-(sp)
	trap	#1
	addq.l	#6,sp
	lea	vars(pc),a3
	move.l	V_BAR(a3),a0		; the frame: a line above and below the bar
	move.w	V_BPL(a3),d1
	move.l	a0,a1
	sub.w	d1,a1
	sub.w	d1,a1
	move.w	V_H(a3),d0
	addq.w	#4,d0			; (a free line between the frame and the bar)
	mulu	d1,d0
	add.l	a1,d0
	move.l	d0,a2
	move.w	V_W(a3),d0
	subq.w	#1,d0
.frame:	st	(a1)+
	st	(a2)+
	dbra	d0,.frame
	pea	vbl(pc)			; Setexc(28, vbl)
	move.l	#$0005001c,-(sp)
	trap	#13
	addq.l	#8,sp
	lea	vars(pc),a3
	move.l	d0,V_OLD(a3)
	rts

vbl:	movem.l	d0-d2/a0-a1/a3,-(sp)	; (a1: the interrupted depacker's output pointer)
	lea	vars(pc),a3
	tst.b	V_ACTIVE(a3)
	beq.s	.out
	move.l	a1,d0
	sub.l	V_T(a3),d0
	bls.s	.out
	lsr.l	#4,d0
	divu	V_PER(a3),d0
	bvs.s	.out
	bsr.s	bar_to
.out:	movem.l	(sp)+,d0-d2/a0-a1/a3
	move.l	vars+V_OLD(pc),-(sp)
	rts

bar_to:					; d0.w: the bytes the bar shows now (a3 vars; d0-d2/a0-a1)
	and.w	V_MASK(a3),d0		; (whole groups: all planes set, one colour)
	cmp.w	V_W(a3),d0
	bls.s	.in
	move.w	V_W(a3),d0
.in:	move.w	V_DONE(a3),d1
	cmp.w	d1,d0
	bls.s	.r
	move.w	d0,V_DONE(a3)
	sub.w	d1,d0
	subq.w	#1,d0
	move.l	V_BAR(a3),a0
	add.w	d1,a0
.col:	move.l	a0,a1
	move.w	V_H(a3),d2
.row:	st	(a1)
	add.w	V_BPL(a3),a1
	dbra	d2,.row
	addq.l	#1,a0
	dbra	d0,.col
.r:	rts

	even
vars:	ds.b	26
text:	dc.b	27,"E",27,"f",27,"Y",32+10
text_col:
	dc.b	32,"Unpacking...",0
	even

; The LZ4 frame depacker (7-byte frame header, no block checksums): a0 the frame, a1 the output.
; The length counters are longs (matches of zeros over 64 KB occur); dbra counts 16 bytes a turn: runs < 1 MB.
lz4_decode:
	addq.l	#7,a0
	lea	little_endian+4(pc),a2
	moveq	#0,d2
	move.w	#$f,d4

next_block:
	move.b	(a0)+,-(a2)
	move.b	(a0)+,-(a2)
	move.b	(a0)+,-(a2)
	move.b	(a0)+,-(a2)
	move.l	(a2)+,d3
	bmi	copy_uncompressed_block
	beq	end_of_compressed_data

	lea	(a0,d3.l),a4

next_token:
	moveq	#0,d0
	move.b	(a0)+,d0

	move.l	d0,d1
	lsr.w	#4,d1
	beq.s	match_data_only

	cmp.w	d4,d1
	beq.s	additional_literal_length

	subq.w	#1,d1

short_literal_copy_loop:
	move.b	(a0)+,(a1)+

	dbra	d1,short_literal_copy_loop

	bra.s	process_match_data

additional_literal_length:
	move.b	(a0)+,d2
	add.l	d2,d1
	not.b	d2
	beq.s	additional_literal_length

	move.w	d1,d3
	lsr.l	#4,d1
	and.w	d4,d3
	add.w	d3,d3
	neg.w	d3
	jmp	literal_copy_start(pc,d3.w)

long_literal_copy_loop:
	rept	16
	move.b	(a0)+,(a1)+
	endr
literal_copy_start:
	dbra	d1,long_literal_copy_loop

process_match_data:
	cmpa.l	a4,a0
	beq.s	next_block

match_data_only:
	moveq	#0,d3
	move.b	(a0)+,-(a2)
	move.b	(a0)+,-(a2)
	move.w	(a2)+,d3
	neg.l	d3
	lea	(a1,d3.l),a3

	and.w	d4,d0
	cmp.w	d4,d0
	beq.s	additional_match_length

	move.b	(a3)+,(a1)+
	move.b	(a3)+,(a1)+
	move.b	(a3)+,(a1)+
short_match_copy_loop:
	move.b	(a3)+,(a1)+

	dbra	d0,short_match_copy_loop

	bra.s	next_token

additional_match_length:
	move.b	(a0)+,d2
	add.l	d2,d0
	not.b	d2
	beq.s	additional_match_length

	move.w	d0,d3
	lsr.l	#4,d0
	and.w	d4,d3
	add.w	d3,d3
	neg.w	d3
	jmp	match_copy_start(pc,d3.w)

long_match_copy_loop:
	rept	16
	move.b	(a3)+,(a1)+
	endr
match_copy_start:
	dbra	d0,long_match_copy_loop

	move.b	(a3)+,(a1)+
	move.b	(a3)+,(a1)+
	move.b	(a3)+,(a1)+
	move.b	(a3)+,(a1)+

	bra	next_token

copy_uncompressed_block:
	andi.l	#$7fffffff,d3
block_copy_loop:
	move.b	(a0)+,(a1)+

	subq.l	#1,d3
	bne.s	block_copy_loop

	bra	next_block

end_of_compressed_data:
	rts

	even
little_endian:
	dc.l	0
