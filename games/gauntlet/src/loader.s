; GAUNTLET.PRG: moves the runtime (runtime.bin, linked at RT_BASE) into place and starts it.  TOS is left behind:
; the runtime takes the whole machine (gauntlet.s).
	include	"map.i"
	include	"runtime_len.i"

MOVER = $800				; (below every load address; neither source nor destination)

	section text,code
	clr.l	-(sp)
	move	#$20,-(sp)		; Super
	trap	#1
	addq	#6,sp
	move	#$2700,sr
	lea	runtime(pc),a0
	move.l	#RUNTIME_LEN,d0
	lea	RT_BASE,a1
	lea	mover(pc),a2
	lea	MOVER.w,a3
	moveq	#(mover_end-mover)/2-1,d1
.c:	move.w	(a2)+,(a3)+
	dbf	d1,.c
	jmp	MOVER.w

; a0 = source, a1 = destination, d0 = bytes (a multiple of 4): either direction, overlapping
mover:
	cmp.l	a0,a1
	bhi.s	.back
.fwd:	move.l	(a0)+,(a1)+
	subq.l	#4,d0
	bgt.s	.fwd
	bra.s	.go
.back:	add.l	d0,a0
	add.l	d0,a1
.b:	move.l	-(a0),-(a1)
	subq.l	#4,d0
	bgt.s	.b
.go:	jmp	RT_BASE
mover_end:

	section data,data
	even
runtime:
	incbin	"runtime.bin"
