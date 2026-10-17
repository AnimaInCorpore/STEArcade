; HDDTEST.PRG: engine/rt/hdd.s on a hard disk (tools/hddtest.sh builds the disk image and runs it in Hatari).
; Opens HDDTEST.DAT on the first drive from C: that has it (sector i of the file holds the longs i << 8 | j, j = 0..127), reads it with hdd_read /
; hdd_poll (the whole file, then requests across the extents), checks every sector and writes HDDTEST.TXT next to
; the file (or to the current drive when no drive has the file):
;   drives <_drvbits> file <name>
;   open <d0> kind <hdd_kind> unit <hdd_unit> lba <hdd_lba> extents <n> sectors <n>
;   read <first> <count>: <result> bad <sectors> polls <n>          (one line a request)
;   done
;   vasmm68k_mot -Ftos -I engine/rt -o HDDTEST.PRG tools/hddtest.s

	include	"hdd.s"

SCAN = 32*1024

	section text
start:
	clr.l	-(sp)
	move	#$20,-(sp)		; Super
	trap	#1
	addq	#6,sp
	move.l	d0,old_ssp

	lea	report,a6
	lea	t_drives,a0
	bsr	copy
	move.l	$4c2.w,d0		; _drvbits
	bsr	hex
	moveq	#2,d6			; C:
.drive:
	btst	d6,$4c2+3.w
	beq.s	.next_drive
	move.b	d6,d0
	add.b	#'A',d0
	move.b	d0,data_name
	move.b	d0,report_name
	lea	data_name,a0
	lea	scan,a1
	move.l	#SCAN,d0
	bsr	hdd_open
	move.l	d0,d7
	cmp.l	#HDD_E_OPEN,d7
	bne.s	.found
.next_drive:
	addq	#1,d6
	cmp	#16,d6
	blo.s	.drive
	move.l	#report_name+2,report_at	; (no drive has it)
.found:
	lea	t_file,a0
	bsr	copy
	lea	data_name,a0
	bsr	copy
	bsr	newline
	lea	t_open,a0
	bsr	copy
	move.l	d7,d0
	bsr	hex
	lea	t_kind,a0
	bsr	copy
	moveq	#0,d0
	move.b	hdd_kind,d0
	bsr	hex
	lea	t_unit,a0
	bsr	copy
	moveq	#0,d0
	move.b	hdd_unit,d0
	bsr	hex
	lea	t_lba,a0
	bsr	copy
	moveq	#0,d0
	move.b	hdd_lba,d0
	bsr	hex
	lea	t_extents,a0
	bsr	copy
	moveq	#0,d0
	move	hdd_extent_count,d0
	bsr	hex
	lea	t_sectors,a0
	bsr	copy
	move.l	hdd_sectors,d0
	bsr	hex
	bsr	newline
	tst.l	d7
	bne	.finish

	moveq	#0,d0			; the whole file
	move.l	hdd_sectors,d1
	bsr	test_read
	lea	requests,a5		; then pieces (-1: up to the end)
.request:
	move.l	(a5)+,d0
	bmi.s	.finish
	move.l	(a5)+,d1
	bpl.s	.count
	move.l	hdd_sectors,d1
	sub.l	d0,d1
.count:
	move.l	d0,d2
	add.l	d1,d2
	cmp.l	hdd_sectors,d2
	bhi.s	.request		; (a smaller file)
	bsr	test_read
	bra.s	.request

.finish:
	bsr	hdd_stop
	lea	t_done,a0
	bsr	copy

	clr	-(sp)			; Fcreate
	move.l	report_at,-(sp)
	move	#$3c,-(sp)
	trap	#1
	addq	#8,sp
	move	d0,d7
	move.l	a6,d6
	sub.l	#report,d6
	pea	report			; Fwrite
	move.l	d6,-(sp)
	move	d7,-(sp)
	move	#$40,-(sp)
	trap	#1
	lea	12(sp),sp
	move	d7,-(sp)		; Fclose
	move	#$3e,-(sp)
	trap	#1
	addq	#4,sp

	move.l	old_ssp,-(sp)
	move	#$20,-(sp)
	trap	#1
	addq	#6,sp
	clr	-(sp)
	trap	#1

; d0 = first sector, d1 = sectors: reads them into buffer (filled with $DEADBEEF first), checks, reports.
test_read:
	movem.l	d0-d1,-(sp)
	lea	t_read,a0
	bsr	copy
	bsr	hex
	bsr	space
	move.l	d1,d0
	bsr	hex
	move.b	#':',(a6)+
	bsr	space

	move.l	d1,d2
	lsl.l	#7,d2			; longs
	lea	buffer,a0
	move.l	#$deadbeef,d3
.fill:
	move.l	d3,(a0)+
	subq.l	#1,d2
	bne.s	.fill

	movem.l	(sp),d0-d1
	lea	buffer,a0
	bsr	hdd_read
	moveq	#0,d5			; polls
	move.l	$466.w,d4		; _frclock
	tst.l	d0
	bne.s	.result
.poll:
	cmp.l	$466.w,d4
	beq.s	.same
	move.l	$466.w,d4
	hdd_vbl
.same:
	addq.l	#1,d5
	bsr	hdd_poll
	cmp.l	#HDD_BUSY,d0
	beq.s	.poll
.result:
	bsr	hex
	lea	t_bad,a0
	bsr	copy

	movem.l	(sp),d0-d1		; check: sector i = i << 8 | j
	lea	buffer,a0
	moveq	#0,d6			; bad sectors
.sector:
	move.l	d0,d2
	lsl.l	#8,d2
	moveq	#128-1,d3
	moveq	#0,d4
.long:
	cmp.l	(a0)+,d2
	sne	d7
	or.b	d7,d4
	addq.l	#1,d2
	dbf	d3,.long
	tst.b	d4
	beq.s	.good
	addq.l	#1,d6
.good:
	addq.l	#1,d0
	subq.l	#1,d1
	bne.s	.sector
	move.l	d6,d0
	bsr	hex
	lea	t_polls,a0
	bsr	copy
	move.l	d5,d0
	bsr	hex
	bsr	newline
	movem.l	(sp)+,d0-d1
	rts

copy:
	move.b	(a0)+,(a6)+
	bne.s	copy
	subq	#1,a6
	rts

hex:
	movem.l	d0-d2,-(sp)
	moveq	#8-1,d2
.digit:
	rol.l	#4,d0
	moveq	#$f,d1
	and	d0,d1
	move.b	.digits(pc,d1.w),(a6)+
	dbf	d2,.digit
	movem.l	(sp)+,d0-d2
	rts
.digits:
	dc.b	"0123456789ABCDEF"

space:
	move.b	#' ',(a6)+
	rts

newline:
	move.b	#13,(a6)+
	move.b	#10,(a6)+
	rts

	hdd_text

	section data
report_at:	dc.l	report_name
requests:				; first sector, sectors (-1: to the end)
	dc.l	0,1
	dc.l	1,1
	dc.l	5,3
	dc.l	100,37
	dc.l	120,16			; (the extents of hddtest.sh's file meet at 128)
	dc.l	127,2
	dc.l	128,1
	dc.l	130,200
	dc.l	1000,-1
	dc.l	-1
data_name:	dc.b	"C:\HDDTEST.DAT",0
report_name:	dc.b	"C:\HDDTEST.TXT",0
t_drives:	dc.b	"drives ",0
t_file:		dc.b	" file ",0
t_open:		dc.b	"open ",0
t_kind:		dc.b	" kind ",0
t_unit:		dc.b	" unit ",0
t_lba:		dc.b	" lba ",0
t_extents:	dc.b	" extents ",0
t_sectors:	dc.b	" sectors ",0
t_read:		dc.b	"read ",0
t_bad:		dc.b	" bad ",0
t_polls:	dc.b	" polls ",0
t_done:		dc.b	"done",13,10,0

	section bss
old_ssp:	ds.l	1
report:		ds.b	4096
	hdd_vars
scan:		ds.b	SCAN
buffer:		ds.b	1024*1024
