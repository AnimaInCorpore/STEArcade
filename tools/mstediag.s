; MSTEDIAG.PRG: what the ports see on a machine they misbehave on (the Mega STE report, 2026-10-13).  Shows, and writes
; to MSTEDIAG.TXT next to itself (the first snapshot):
;   machine   the _MCH cookie (STE $00010000, Mega STE $00010010), TOS version, $FF8E21 (Mega STE speed/cache)
;   video     $FF820A (sync: bit 1 set = 50 Hz) and $FF8260 at the start; VBLs in one second (the 200 Hz timer) as
;             found, and with 50 Hz forced (the desktop's rate is restored afterwards)
;   pads      the ports' probe (engine/rt/jagpad.s jagpad_init: a write to $FF9202 without a bus error = pads), the
;             raw words of $FF9200 / $FF9202 for every row select the ports use, and what jagpad_poll makes of them
;             (decoded even when the probe leaves the pads off: what check 1 and the released games saw; nothing pressed
;             should read "none")
; The pad lines repeat live until a key is pressed (pads / joysticks may be pressed meanwhile).
;   vasmm68k_mot -Ftos -I engine/rt -o MSTEDIAG.PRG tools/mstediag.s       (tools/mstediag.sh: build, run in Hatari)

	include	"jagpad.s"

; jagpad_poll's tables: one bit per button (jp_in, active high)
JP1_UP = 1<<0
JP1_DOWN = 1<<1
JP1_LEFT = 1<<2
JP1_RIGHT = 1<<3
JP1_B1 = 1<<4
JP1_B2 = 1<<5
JP1_B3 = 1<<6
JP_COIN1 = 1<<7
JP_START1 = 1<<8
JP_START2 = 1<<9
JP_COIN2 = 1<<10
JP2_UP = 1<<16
JP2_DOWN = 1<<17
JP2_LEFT = 1<<18
JP2_RIGHT = 1<<19
JP2_B1 = 1<<20
JP2_B2 = 1<<21
JP2_B3 = 1<<22

LIVE_ROW = 5				; the screen line of the first pad line (after the head's five)

	section text
start:
	clr.l	-(sp)
	move.w	#$20,-(sp)		; Super
	trap	#1
	addq.l	#6,sp
	move.l	d0,old_ssp

	lea	head,a1			; the lines that do not change
	lea	t_title,a0
	bsr	copy
	lea	t_mch,a0
	bsr	copy
	move.l	$5a0.w,d0		; the cookie jar
	beq.s	.nojar
	move.l	d0,a2
.cookie:
	move.l	(a2)+,d0
	beq.s	.nojar
	move.l	(a2)+,d1
	cmp.l	#'_MCH',d0
	bne.s	.cookie
	move.l	d1,d0
	moveq	#8,d2
	bsr	hex
	bra.s	.tos
.nojar:	lea	t_none,a0
	bsr	copy
.tos:	lea	t_tos,a0
	bsr	copy
	move.l	$4f2.w,a0		; _sysbase: os_version
	move.w	2(a0),d0
	moveq	#4,d2
	bsr	hex
	lea	t_cache,a0
	bsr	copy
	lea	$ffff8e21.w,a0
	bsr	peekb
	bsr	hex_or_berr

	lea	t_video,a0
	bsr	copy
	move.b	$ffff820a.w,d0
	move.b	d0,old_hz
	moveq	#2,d2
	bsr	hex
	lea	t_res,a0
	bsr	copy
	move.b	$ffff8260.w,d0
	moveq	#2,d2
	bsr	hex
	lea	t_rate,a0
	bsr	copy
	bsr	vbl_rate
	bsr	decimal
	lea	t_forced,a0
	bsr	copy
	move.b	#2,$ffff820a.w		; 50 Hz, as the ports should
	bsr	vsync
	bsr	vsync
	bsr	vbl_rate
	move.b	old_hz,$ffff820a.w
	bsr	decimal

	lea	t_probe,a0		; the ports' probe
	bsr	copy
	bsr	jagpad_init
	moveq	#0,d0
	move.b	jp_present,d0
	beq.s	.absent
	lea	t_present,a0
	bra.s	.probed
.absent:
	lea	t_absent,a0
.probed:
	bsr	copy
	clr.b	(a1)
	sub.l	#head,a1
	move.l	a1,head_len

	pea	t_clear			; the screen: the head once, the pad lines live
	move.w	#9,-(sp)		; Cconws
	trap	#1
	addq.l	#6,sp
	pea	head
	move.w	#9,-(sp)
	trap	#1
	addq.l	#6,sp

	bsr	pad_lines		; the first snapshot to MSTEDIAG.TXT
	clr.w	-(sp)
	pea	name
	move.w	#$3c,-(sp)		; Fcreate
	trap	#1
	addq.l	#8,sp
	tst.w	d0
	bmi.s	.live
	move.w	d0,d6
	lea	filebuf,a1		; head and pads without the screen's escapes
	lea	head,a0
	bsr	plain
	lea	pads,a0
	bsr	plain
	sub.l	#filebuf,a1
	pea	filebuf
	move.l	a1,-(sp)
	move.w	d6,-(sp)
	move.w	#$40,-(sp)		; Fwrite
	trap	#1
	lea	12(sp),sp
	move.w	d6,-(sp)
	move.w	#$3e,-(sp)		; Fclose
	trap	#1
	addq.l	#4,sp
	lea	t_saved,a0
	bra.s	.note
.live:	lea	t_unsaved,a0
.note:	move.l	a0,save_note

.loop:	pea	t_home
	move.w	#9,-(sp)
	trap	#1
	addq.l	#6,sp
	pea	pads
	move.w	#9,-(sp)
	trap	#1
	addq.l	#6,sp
	move.l	save_note,-(sp)
	move.w	#9,-(sp)
	trap	#1
	addq.l	#6,sp
	moveq	#5-1,d7
.wait:	bsr	vsync
	dbf	d7,.wait
	move.w	#$b,-(sp)		; Cconis
	trap	#1
	addq.l	#2,sp
	tst.w	d0
	bne.s	.quit
	bsr	pad_lines
	bra.s	.loop

.quit:	move.w	#8,-(sp)		; Cnecin (the key)
	trap	#1
	addq.l	#2,sp
	move.l	old_ssp,-(sp)
	move.w	#$20,-(sp)
	trap	#1
	addq.l	#6,sp
	clr.w	-(sp)			; Pterm0
	trap	#1

; pad_lines: the raw rows and jagpad_poll's buttons into pads (pads_len)
pad_lines:
	lea	pads,a1
	lea	t_read,a0
	bsr	copy
	lea	$ffff9200.w,a0
	bsr	peekw
	bsr	hex_or_berr
	lea	t_read2,a0
	bsr	copy
	lea	$ffff9202.w,a0
	bsr	peekw
	bsr	hex_or_berr
	lea	t_eol,a0
	bsr	copy
	lea	selects,a3
.row:	move.w	(a3)+,d3
	beq.s	.rows_done
	lea	t_sel,a0
	bsr	copy
	move.w	d3,d0
	moveq	#4,d2
	bsr	hex
	lea	t_colon,a0
	bsr	copy
	move.w	d3,d0
	lea	$ffff9202.w,a0
	bsr	pokew
	tst.w	d1
	bmi.s	.wberr
	sf	no_regs
	lea	$ffff9200.w,a0
	bsr	peekw
	bsr	hex_or_berr
	move.b	#' ',(a1)+
	lea	$ffff9202.w,a0
	bsr	peekw
	bsr	hex_or_berr
	bra.s	.row_end
.wberr:	st	no_regs
	lea	t_wberr,a0
	bsr	copy
.row_end:
	lea	t_eol,a0
	bsr	copy
	bra.s	.row
.rows_done:
	move.w	#$ffff,d0		; (nothing selected, as the ports leave it)
	lea	$ffff9202.w,a0
	bsr	pokew

	lea	t_poll,a0
	bsr	copy
	clr.l	jp_in
	tst.b	no_regs			; (a plain ST: no registers to decode)
	bne.s	.decoded
	move.b	jp_present,-(sp)
	st	jp_present		; decoded even when the probe leaves the pads off
	bsr	jagpad_poll
	move.b	(sp)+,jp_present
.decoded:
	move.l	jp_in,d4
	move.l	d4,d0
	moveq	#8,d2
	bsr	hex
	move.b	#' ',(a1)+
	tst.l	d4
	bne.s	.held
	lea	t_nothing,a0
	bsr	copy
	bra.s	.quitf
.held:	lea	button_names,a2
	moveq	#0,d5			; the bit
.name:	tst.b	(a2)
	beq.s	.quitf
	btst	d5,d4
	beq.s	.skip
	move.l	a2,a0
	bsr	copy
	move.b	#' ',(a1)+
.skip:	tst.b	(a2)+			; the next name
	bne.s	.skip
	addq.w	#1,d5
	bra.s	.name
.quitf:	tst.b	quit_flag
	beq.s	.eol
	lea	t_quitf,a0
	bsr	copy
.eol:	lea	t_eol,a0
	bsr	copy
	clr.b	(a1)
	sub.l	#pads,a1
	move.l	a1,pads_len
	rts

; peekw / peekb / pokew: a0 = the address, d0 = the value; d1 = 0, or -1 after a bus error
peekw:	bsr.s	berr_on
	move.w	(a0),d0
	moveq	#0,d1
	bra.s	berr_off
peekb:	moveq	#0,d0
	bsr.s	berr_on
	move.b	(a0),d0
	moveq	#0,d1
	bra.s	berr_off
pokew:	bsr.s	berr_on
	move.w	d0,(a0)
	moveq	#0,d1
	bra.s	berr_off

berr_on:
	move.l	(sp)+,a4		; (the return)
	move.l	$8.w,old_berr
	move.l	sp,berr_sp
	move.l	#berr,$8.w
	moveq	#-1,d1
	jmp	(a4)
berr:	move.l	berr_sp,sp
berr_off:
	move.l	old_berr,$8.w
	rts

hex_or_berr:				; d1 < 0: "bus error", else d0 as 4 hex digits at a1
	tst.w	d1
	bmi.s	.b
	moveq	#4,d2
	bra	hex
.b:	lea	t_berr,a0
	bra.s	copy

vsync:	movem.l	d1-d2/a1-a2,-(sp)	; (XBIOS uses d0-d2 / a0-a2; a1 is the text)
	move.w	#37,-(sp)		; Vsync
	trap	#14
	addq.l	#2,sp
	movem.l	(sp)+,d1-d2/a1-a2
	rts

vbl_rate:				; d0 = the VBLs in one second (200 ticks of _hz_200)
	move.l	$4ba.w,d1
.w0:	cmp.l	$4ba.w,d1
	beq.s	.w0
	move.l	$4ba.w,d1
	move.l	$466.w,d2		; _frclock
	add.l	#200,d1
.w1:	cmp.l	$4ba.w,d1
	bhi.s	.w1
	move.l	$466.w,d0
	sub.l	d2,d0
	rts

plain:	move.b	(a0)+,d1		; the string a0 to a1 without its escapes (ESC and the next byte)
	beq.s	.e
	cmp.b	#27,d1
	bne.s	.c
	tst.b	(a0)+
	bne.s	plain
	rts
.c:	move.b	d1,(a1)+
	bra.s	plain
.e:	rts

copy:	move.b	(a0)+,d1		; the string a0 to a1
	beq.s	.e
	move.b	d1,(a1)+
	bra.s	copy
.e:	rts

decimal:				; d0 (below 1000) as decimal at a1
	moveq	#0,d3
	lea	powers,a2
.p:	move.w	(a2)+,d2
	beq.s	.last
	moveq	#'0',d1
.s:	cmp.w	d2,d0
	blo.s	.put
	sub.w	d2,d0
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

hex:	move.b	#'$',(a1)+		; the low d2 hex digits of d0 at a1
	move.w	d2,d1
	lsl.w	#2,d1
	ror.l	d1,d0
	subq.w	#1,d2
.h:	rol.l	#4,d0
	moveq	#15,d1
	and.w	d0,d1
	move.b	digits(pc,d1.w),(a1)+
	dbf	d2,.h
	rts
digits:	dc.b	"0123456789ABCDEF"
	even

	jagpad_text
	jagpad_maps

	section data
selects:	dc.w	$ffff,$ffee,$ffdd,$ffbb,$ff77,0
powers:	dc.w	100,10,0
name:		dc.b	"MSTEDIAG.TXT",0
t_clear:	dc.b	27,"E",0
t_home:		dc.b	27,"Y",32+LIVE_ROW,32,0
t_title:	dc.b	"STEArcade hardware check 2",13,10,0
t_mch:		dc.b	"machine: _MCH ",0
t_none:		dc.b	"(none)",0
t_tos:		dc.b	"  TOS ",0
t_cache:	dc.b	"  $FF8E21 ",0
t_video:	dc.b	13,10,"video: $FF820A ",0
t_res:		dc.b	"  $FF8260 ",0
t_rate:		dc.b	13,10,"VBLs a second: ",0
t_forced:	dc.b	",  with 50 Hz forced: ",0
t_probe:	dc.b	13,10,"pad probe (jagpad_init): ",0
t_present:	dc.b	"the games use pads",13,10,0
t_absent:	dc.b	"the games ignore pads",13,10,0
t_read:		dc.b	"read: $FF9200 ",0
t_read2:	dc.b	"  $FF9202 ",0
t_sel:		dc.b	"select ",0
t_colon:	dc.b	": ",0
t_wberr:	dc.b	"write: bus error",0
t_berr:		dc.b	"bus error",0
t_poll:		dc.b	"pads decoded, held: ",0
t_nothing:	dc.b	"none",0
t_quitf:	dc.b	" (quit)",0
t_eol:		dc.b	27,"K",13,10,0
t_saved:	dc.b	13,10,"Saved MSTEDIAG.TXT. Press a key to quit.",27,"K",0
t_unsaved:	dc.b	13,10,"MSTEDIAG.TXT not saved. Press a key to quit.",27,"K",0
button_names:	dc.b	"1up",0,"1down",0,"1left",0,"1right",0,"1fireA",0,"1fireB",0,"1fireC",0,"coin1",0
		dc.b	"start1",0,"start2",0,"coin2",0,"-",0,"-",0,"-",0,"-",0,"-",0
		dc.b	"2up",0,"2down",0,"2left",0,"2right",0,"2fireA",0,"2fireB",0,"2fireC",0,0

	section bss
old_ssp:	ds.l	1
old_berr:	ds.l	1
berr_sp:	ds.l	1
head_len:	ds.l	1
pads_len:	ds.l	1
save_note:	ds.l	1
old_hz:		ds.b	1
no_regs:	ds.b	1
quit_flag:	ds.b	1
	jagpad_vars
head:		ds.b	512
pads:		ds.b	512
filebuf:	ds.b	1024
