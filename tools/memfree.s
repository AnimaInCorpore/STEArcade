; MEMFREE.PRG: how much memory TOS gives a program started this way (the measure for the ports' memory budget).
; Writes MEMFREE.TXT next to itself and shows the same on the screen:
;   TPA      the memory this program was given (p_hitpa - p_lowtpa): GEMDOS's largest free block at the start
;   membot / memtop / phystop   the system variables
; A port starts if its text + data + BSS + 256 (the basepage) fit into TPA.
;   vasmm68k_mot -Ftos -o MEMFREE.PRG tools/memfree.s        (port.py memfree builds and runs it in Hatari)

	section text
start:
	move.l	4(sp),a0		; the basepage
	move.l	4(a0),d0		; p_hitpa
	sub.l	(a0),d0			; - p_lowtpa
	move.l	d0,tpa
	clr.l	-(sp)
	move.w	#$20,-(sp)		; Super
	trap	#1
	addq.l	#6,sp
	move.l	$432.w,membot
	move.l	$436.w,memtop
	move.l	$42e.w,phystop
	move.l	d0,-(sp)
	move.w	#$20,-(sp)		; back to user mode
	trap	#1
	addq.l	#6,sp

	lea	text,a1			; the report
	lea	l_tpa,a0
	bsr	copy
	move.l	tpa,d0
	bsr	decimal
	lea	l_bot,a0
	bsr	copy
	move.l	membot,d0
	bsr	hex
	lea	l_top,a0
	bsr	copy
	move.l	memtop,d0
	bsr	hex
	lea	l_phys,a0
	bsr	copy
	move.l	phystop,d0
	bsr	hex
	lea	crlf,a0
	bsr	copy
	clr.b	(a1)
	move.l	a1,d7
	sub.l	#text,d7		; the length

	pea	text
	move.w	#9,-(sp)		; Cconws
	trap	#1
	addq.l	#6,sp
	clr.w	-(sp)
	pea	name
	move.w	#$3c,-(sp)		; Fcreate
	trap	#1
	addq.l	#8,sp
	tst.w	d0
	bmi.s	.done
	move.w	d0,d6
	pea	text
	move.l	d7,-(sp)
	move.w	d6,-(sp)
	move.w	#$40,-(sp)		; Fwrite
	trap	#1
	lea	12(sp),sp
	move.w	d6,-(sp)
	move.w	#$3e,-(sp)		; Fclose
	trap	#1
	addq.l	#4,sp
.done:
	clr.w	-(sp)			; Pterm0
	trap	#1

copy:	move.b	(a0)+,d1		; the string a0 to a1
	beq.s	.e
	move.b	d1,(a1)+
	bra.s	copy
.e:	rts

decimal:				; d0 (unsigned, below 10^8) as decimal at a1
	lea	powers,a2
	moveq	#0,d3			; (a digit written)
.p:	move.l	(a2)+,d2
	beq.s	.last
	moveq	#'0',d1
.s:	cmp.l	d2,d0
	blo.s	.put
	sub.l	d2,d0
	addq.b	#1,d1
	bra.s	.s
.put:	cmp.b	#'0',d1
	bne.s	.w
	tst.b	d3
	beq.s	.p
.w:	move.b	d1,(a1)+
	st	d3
	bra.s	.p
.last:	add.b	#'0',d0
	move.b	d0,(a1)+
	rts

hex:	move.b	#'$',(a1)+		; d0 as 8 hex digits at a1
	moveq	#8-1,d2
.h:	rol.l	#4,d0
	moveq	#15,d1
	and.w	d0,d1
	move.b	digits(pc,d1.w),(a1)+
	dbf	d2,.h
	rts
digits:	dc.b	"0123456789ABCDEF"

	section data
powers:	dc.l	10000000,1000000,100000,10000,1000,100,10,0
name:	dc.b	"MEMFREE.TXT",0
l_tpa:	dc.b	"TPA ",0
l_bot:	dc.b	" bytes, membot ",0
l_top:	dc.b	", memtop ",0
l_phys:	dc.b	", phystop ",0
crlf:	dc.b	13,10,0
	section bss
tpa:	ds.l	1
membot:	ds.l	1
memtop:	ds.l	1
phystop:	ds.l	1
text:	ds.b	256
