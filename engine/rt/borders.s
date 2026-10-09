; Top and bottom border removal for the STE ports, safe against late interrupts: the foreground never waits for it.
;
; A Blitter pass in HOG mode (or a long instruction, or another interrupt) holds an interrupt back.  The old handlers
; came exactly when they had to act, so every pass near one of their events had to wait.  Here every event comes
; early and then syncs itself to the video; it acts on time if it starts up to ~1.5 lines late:
;
; - Timer B (event count: the ends of the displayed lines) fires BD_K lines before an event's line and polls its
;   counter down to that line's end: the bottom border, and with BD_PALETTE the palette on before the picture's first
;   line (PIC_TOP displayed lines from the top) and off after its last (PIC_LINES).  Each event starts the next one.
; - Timer A opens the top border.  The bottom border event starts it (a line-exact point), so the VBL's own lateness
;   does not move it: two periods (BD_TA_P1, then the reload BD_TA_P2) end ~3 lines before the HBL the border needs;
;   the handler waits for HBLs and reads Timer A (still counting from the reload) to know which one it is.
; - The VBL only restarts Timer B.  It arms Timer A the old way (TA_DATA, exact only if the VBL is on time) when the
;   bottom border did not (the first frame, or a frame whose top border stayed closed).
;
; A HOG pass must stay well under ~1.5 lines: a Timer B event has ~750 cycles from its interrupt to its first look
; at the counter (the palette events load the palette first).  Longer passes run in pieces (borders_blit_go: at most
; BLIT_PIECE words, at least a line each; the Blitter keeps its addresses between them).  With 64-word pieces (up to
; ~770 cycles with the destination read) Gun.Smoke still had palette events late now and then, with 32 none.
;
; The port defines TA_DATA, TA_NOPS (the old handler's tuning), PIC_TOP / PIC_LINES and BD_PALETTE (1: shown_pal and
; black_pal are the palettes), and places borders_vbl first in its VBL, borders_handlers in its text, borders_vars
; in its bss (borders_blit_go, borders_report: optional); the vectors are timer_a ($134) and timer_b ($120); an HBL
; handler ($68) of just rte is needed.
; DEBUG counts bd_fallbacks (frames with the top border armed by the VBL), bd_late_top / bd_late_on / bd_late_low /
; bd_late_off (events that started too late: a border may have stayed closed, a palette switch came late) and
; bd_pieced; -D BD_PCLOG=1 keeps the last 64 interrupted PCs of late Timer B events (bd_pc_base: what held them back).

	ifnd BD_PALETTE
BD_PALETTE = 0
	endc

BD_K = 2				; Timer B events fire this many lines early
BD_POLL = 120				; poll limit (~4 lines; only a missing line would reach it)
BD_LOW = 229				; the line end after which the bottom border is opened
	if BD_PALETTE
BD_ON = PIC_TOP				; the line end after which the palette comes on
BD_OFF = PIC_TOP+PIC_LINES		; and goes off
BD_FIRST = BD_ON
BD_SAVED = 44				; (Timer B's saved registers)
	else
BD_FIRST = BD_LOW
BD_SAVED = 16
	endc

; Timer A (/50) from the bottom border event to the top border: the HBL the old handler waited for comes 260 counts
; after the start (measured in Hatari, a Timer D stopwatch: 1997 of 2000 frames).  It fires 10 counts (~3 lines)
; before it, at the HBL the reload has counted 9 or 10 (old handler: 4 or 3 at its HBL, two values in 93 / 7%); one
; HBL earlier it shows 6 or 7.
BD_TA_P2 = 125
BD_TA_P1 = 260-10-BD_TA_P2
BD_TA_THR = BD_TA_P2-8			; the top border's HBL: the reload at or below this
BD_TA_LOOP = 8				; the sync's cycles after the HBL in nops (move.b, cmp.b, dbls: 32 cycles)

borders_vbl	macro
	clr.b	$fffffa1b.w		; Timer B: counts this frame's lines from the first
	move.b	#BD_FIRST-BD_K,$fffffa21.w
	move.b	#8,$fffffa1b.w
	if BD_PALETTE
	clr.b	bd_tb_state
	else
	move.b	#1,bd_tb_state
	endc
	tst.b	bd_ta_state		; Timer A is counting to the top border already (the bottom border started it)
	bne.s	.c\@
	clr.b	$fffffa19.w
	move.b	#TA_DATA,$fffffa1f.w
	move.b	#4,$fffffa19.w
	ifd DEBUG
	addq.w	#1,bd_fallbacks
	endc
.c\@:
	endm

bd_top_open	macro
	clr.b	$ffff820a.w		; Remove the top border
	rept 9
	nop
	endr
	move.b	#2,$ffff820a.w
	endm

; Timer B's poll: d0 = the counter value at the event's line end, d1 = BD_POLL, a0 = $fffffa21
bd_poll	macro
.p\@:	cmp.b	(a0),d0
	dbcc	d1,.p\@
	endm

bd_check_late	macro			; \1 = the event's counter
	ifd DEBUG
	cmp.w	#BD_POLL,d1		; (the line end had passed at the first look, or never came)
	beq.s	.l\@
	tst.w	d1
	bpl.s	.k\@
.l\@:	addq.w	#1,\1
	ifd BD_PCLOG
	move.w	bd_pc_n,d2		; (the interrupted PC: what held the interrupt back)
	and.w	#63,d2
	lsl.w	#2,d2
	lea	bd_pcs,a1
	move.l	BD_SAVED+2(sp),(a1,d2.w)
	addq.w	#1,bd_pc_n
	endc
.k\@:
	endc
	endm

borders_handlers	macro

; Top border (Timer A).  bd_ta_state: 0 the VBL armed it (old timing), 2 the first period of the bottom border's
; start, 1 the early event.
timer_a:
	tst.b	bd_ta_state
	bne	bd_ta_chain
	move	#$2100,sr		; Enable HBL
	stop	#$2100			; Wait for HBL
	move	#$2700,sr		; Stop all interrupts
	clr.b	$fffffa19.w		; Stop Timer A
	rept TA_NOPS
	nop
	endr
	bd_top_open
	rte
bd_ta_chain:
	subq.b	#1,bd_ta_state
	bne	.pre			; (the first period: the reload runs on by itself)
	movem.l	d0-d1,-(sp)
	moveq	#8,d1
	move	#$2100,sr		; (an HBL pending from before is taken here)
.line:	stop	#$2100			; Wait for HBL
	move.b	$fffffa1f.w,d0
	cmp.b	#BD_TA_THR,d0
	dbls	d1,.line		; (an earlier HBL: the reload reads 3 counts more)
	move	#$2700,sr		; Stop all interrupts
	clr.b	$fffffa19.w		; Stop Timer A
	rept TA_NOPS-BD_TA_LOOP
	nop
	endr
	bd_top_open
	ifd DEBUG
	cmp.b	#BD_TA_THR-3,d0		; (the HBL after the border's: started more than ~3 lines late)
	bhi.s	.ok
	addq.w	#1,bd_late_top
.ok:
	endc
	movem.l	(sp)+,d0-d1
.pre:	rte

; Bottom border and palette (Timer B).  bd_tb_state: 0 the palette on, 1 the bottom border, 2 the palette off.
timer_b:
	if BD_PALETTE
	movem.l	d0-d7/a0-a2,-(sp)
	else
	movem.l	d0-d2/a0,-(sp)
	endc
	lea	$fffffa21.w,a0
	moveq	#BD_POLL,d1
	if BD_PALETTE
	move.b	bd_tb_state,d0
	beq	.on
	subq.b	#1,d0
	bne	.off
	move.b	#BD_LOW-BD_ON-2*BD_K,d0
	else
	move.b	#BD_LOW-2*BD_K,d0
	endc
	bd_poll
	clr.b	$ffff820a.w		; Remove the bottom border
	moveq	#2,d2
.w2:	nop
	dbf	d2,.w2
	nop
	nop
	nop
	nop
	nop
	move.b	#2,$ffff820a.w
	clr.b	$fffffa19.w		; Timer A to the next frame's top border
	move.b	#BD_TA_P1,$fffffa1f.w
	move.b	#4,$fffffa19.w
	move.b	#BD_TA_P2,$fffffa1f.w	; (the reload)
	move.b	#2,bd_ta_state
	clr.b	$fffffa1b.w
	if BD_PALETTE
	move.b	#BD_OFF-BD_LOW-BD_K,$fffffa21.w
	move.b	#8,$fffffa1b.w
	move.b	#2,bd_tb_state
	endc
	bd_check_late bd_late_low
	if BD_PALETTE
	bra	.out
.on:	movem.l	shown_pal,d2-d7/a1-a2
	move.b	#BD_ON-2*BD_K,d0
	bd_poll
	movem.l	d2-d7/a1-a2,$ffff8240.w
	clr.b	$fffffa1b.w
	move.b	#BD_LOW-BD_ON-BD_K,$fffffa21.w
	move.b	#8,$fffffa1b.w
	move.b	#1,bd_tb_state
	bd_check_late bd_late_on
	bra	.out
.off:	movem.l	black_pal,d2-d7/a1-a2
	move.b	#BD_OFF-BD_LOW-2*BD_K,d0
	bd_poll
	movem.l	d2-d7/a1-a2,$ffff8240.w
	clr.b	$fffffa1b.w		; (the VBL starts the next frame's)
	move.b	#3,bd_tb_state
	bd_check_late bd_late_off
.out:	movem.l	(sp)+,d0-d7/a0-a2
	else
	movem.l	(sp)+,d0-d2/a0
	endc
	rte
	endm

; blit_go: starts the HOG pass set up in the Blitter's registers (the lines in its Y count): whole when it is at most
; BLIT_PIECE words, else in pieces of as many lines as fit in that (at least one).  Keeps all registers.
	ifnd BLIT_PIECE
BLIT_PIECE = 32
	endc
borders_blit_go	macro
blit_go:
	movem.l	d0-d2,-(sp)
	move.w	$ffff8a38.w,d0		; the lines
	move.w	$ffff8a36.w,d2		; the words a line
	moveq	#BLIT_PIECE,d1
	divu	d2,d1			; the lines a piece
	cmp.w	d0,d1
	bhs.s	.whole
	ifd DEBUG
	addq.l	#1,bd_pieced
	endc
	tst.w	d1
	bne.s	.n
	moveq	#1,d1
.n:	move.w	d1,d2
	cmp.w	d0,d2
	bls.s	.go
	move.w	d0,d2
.go:	move.w	d2,$ffff8a38.w
	move.b	#$c0,$ffff8a3c.w
	sub.w	d2,d0
	bne.s	.n
	movem.l	(sp)+,d0-d2
	rts
.whole:	move.b	#$c0,$ffff8a3c.w
	movem.l	(sp)+,d0-d2
	rts
	endm

; bd_report (DEBUG, for ports without a counters file of their own; call it at the quit, after the hardware is
; restored): BORDERS.BIN = bd_fallbacks, bd_late_top, bd_late_on, bd_late_low, bd_late_off (words), bd_pieced (long).
borders_report	macro
	ifd DEBUG
bd_report:
	clr	-(sp)
	pea	bd_rname
	move	#$3c,-(sp)		; Fcreate
	trap	#1
	addq	#8,sp
	move	d0,d6
	pea	bd_fallbacks
	move.l	#14,-(sp)
	move	d6,-(sp)
	move	#$40,-(sp)		; Fwrite
	trap	#1
	lea	12(sp),sp
	move	d6,-(sp)
	move	#$3e,-(sp)		; Fclose
	trap	#1
	addq	#4,sp
	rts
bd_rname:
	dc.b	"BORDERS.BIN",0
	even
	endc
	endm

borders_vars	macro
bd_ta_state:	ds.b	1
bd_tb_state:	ds.b	1
	ifd DEBUG
	even
bd_fallbacks:	ds.w	1
bd_late_top:	ds.w	1
bd_late_on:	ds.w	1
bd_late_low:	ds.w	1
bd_late_off:	ds.w	1
bd_pieced:	ds.l	1			; (blit_go's passes run in pieces)
	ifd BD_PCLOG
bd_pc_base:	ds.l	1		; (a known label's address; then the count and the PCs)
bd_pc_n:	ds.w	1
bd_pcs:	ds.l	64
	endc
	endc
	endm
