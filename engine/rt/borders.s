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
; at the counter (the palette events load the palette first), and the top border handler that the VBL arms (the
; fallback) has less than a line.  Every pass is short (stefastbobs2's rule: only short line passes): longer ones run
; in pieces of at most ~256 bus cycles (borders_blit_go: lines, or column strips of a wide line; the Blitter keeps
; its addresses between them).  With 64-word pieces (up to ~770 cycles with the destination read) Gun.Smoke still had
; palette events late now and then, with 32 none.  And every pass is HOG: one that shares the bus runs on during the
; interrupts and stretches the timed code that opens the borders.  BLIT_STATS=256 (engine/sim.py) lists the passes
; of a simulator run that are longer, and every pass without HOG.
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

; blit_go: starts the HOG pass set up in the Blitter's registers (the lines in its Y count): whole when it is at most a
; piece, else in pieces of as many lines as fit in one (at least one).  A piece is BLIT_PIECE words, half that when the
; op reads the destination (a masked draw: three bus accesses a word).  A line wider than a piece is cut into column
; strips of at most a piece when the pass has no skew, FXSR or NFSR (the copies and fills: a strip is then the same
; pass on fewer words); with them it runs a line a pass.  The registers end as one pass would leave them.  Keeps all
; registers.
;
; So no HOG pass holds the CPU longer than ~half a line (32 words of a copy: 256 bus cycles), the rule of
; stefastbobs2: only short line passes, whenever the top border's interrupt may come.
	ifnd BLIT_PIECE
BLIT_PIECE = 32
	endc
borders_blit_go	macro
; blit_go_lines: as blit_go, d1.w = the lines a piece (BLIT_PIECE / the words a line: the caller knows them, no divu)
blit_go_lines:
	movem.l	d0-d2,-(sp)
	move.w	$ffff8a38.w,d0		; the lines
	bra.s	blit_go_split
; the lines a piece by the words a line (0-BLIT_PIECE): a copy or fill, an op that reads the destination
bd_lines:
BD_W	set	1
	dc.b	0
	rept	BLIT_PIECE
	dc.b	BLIT_PIECE/BD_W
BD_W	set	BD_W+1
	endr
bd_lines_d:
BD_W	set	1
	dc.b	0
	rept	BLIT_PIECE
	dc.b	(BLIT_PIECE/2)/BD_W
BD_W	set	BD_W+1
	endr
	even
blit_go:
	movem.l	d0-d2,-(sp)
	move.w	$ffff8a38.w,d0		; the lines
	moveq	#15,d1
	and.b	$ffff8a3b.w,d1
	move.w	#%1001000000001001,d2	; (the ops 0, 3, 12, 15 do not read the destination)
	btst	d1,d2
	beq.s	.h
	move.w	$ffff8a36.w,d2		; the words a line
	moveq	#BLIT_PIECE,d1		; the words a piece
	cmp.w	d1,d2
	bhi.s	blit_go_wide
	move.b	bd_lines(pc,d2.w),d1	; the lines a piece
	bra.s	blit_go_split
.h:	move.w	$ffff8a36.w,d2
	moveq	#BLIT_PIECE/2,d1	; (a destination read too: half)
	cmp.w	d1,d2
	bhi.s	blit_go_wide
	move.b	bd_lines_d(pc,d2.w),d1
blit_go_split:
	cmp.w	d0,d1
	bhs.s	.whole
	ifd DEBUG
	addq.l	#1,bd_pieced
	endc
	tst.w	d1
	bne.s	.n
	moveq	#1,d1
.n:	bsr.s	bd_pieces
	movem.l	(sp)+,d0-d2
	rts
.whole:	move.b	#$c0,$ffff8a3c.w
	movem.l	(sp)+,d0-d2
	rts
; d0.w lines in pieces of d1.w (at least 1).  Uses d0 / d2.
bd_pieces:
	move.w	d1,d2
	cmp.w	d0,d2
	bls.s	.go
	move.w	d0,d2
.go:	move.w	d2,$ffff8a38.w
	move.b	#$c0,$ffff8a3c.w
	sub.w	d2,d0
	bne.s	bd_pieces
	rts
; a line of more than a piece (d0 the lines, d1 the words a piece, d2 the words a line)
blit_go_wide:
	move.w	d1,bd_c_piece
	ifd DEBUG
	addq.l	#1,bd_pieced
	endc
	moveq	#1,d1
	tst.b	$ffff8a3d.w		; (skew, FXSR, NFSR: the source words of a strip would differ)
	bne	.n
	movem.l	d3-d7/a0-a1,-(sp)
	move.w	d0,d7			; the lines
	move.w	d2,d6			; the words a line
	move.l	$ffff8a24.w,a0		; the first source and destination words
	move.l	$ffff8a32.w,a1
	move.w	$ffff8a22.w,bd_c_syi
	move.w	$ffff8a30.w,bd_c_dyi
	move.w	$ffff8a28.w,bd_c_em1
	move.w	$ffff8a2c.w,bd_c_em3
	moveq	#0,d3			; the strip's first word
.strip:	move.w	d6,d4
	sub.w	d3,d4
	cmp.w	bd_c_piece,d4
	bls.s	.w
	move.w	bd_c_piece,d4		; its words
.w:	move.w	d4,$ffff8a36.w
	move.w	$ffff8a20.w,d5		; its first words: + its first word x the X increments
	muls	d3,d5
	add.l	a0,d5
	move.l	d5,$ffff8a24.w
	move.w	$ffff8a2e.w,d5
	muls	d3,d5
	add.l	a1,d5
	move.l	d5,$ffff8a32.w
	move.w	d6,d2			; the Y increments: + the words it leaves out x the X increments
	sub.w	d4,d2
	move.w	$ffff8a20.w,d5
	muls	d2,d5
	add.w	bd_c_syi,d5
	move.w	d5,$ffff8a22.w
	move.w	$ffff8a2e.w,d5
	muls	d2,d5
	add.w	bd_c_dyi,d5
	move.w	d5,$ffff8a30.w
	move.w	$ffff8a2a.w,d5		; the end masks: the middle one but at the line's ends
	move.w	d5,$ffff8a28.w
	move.w	d5,$ffff8a2c.w
	tst.w	d3
	bne.s	.m1
	move.w	bd_c_em1,$ffff8a28.w
.m1:	cmp.w	d3,d2			; (the last strip: the words it leaves out are those before it)
	bne.s	.m3
	move.w	bd_c_em3,$ffff8a2c.w
	cmp.w	#1,d4
	bne.s	.m3
	move.w	bd_c_em3,$ffff8a28.w	; (a strip of one word has endmask 1 only)
.m3:	move.w	bd_c_piece,d1
	divu	d4,d1			; its lines a piece
	move.w	d7,d0
	bsr	bd_pieces
	add.w	d4,d3
	cmp.w	d6,d3
	blo	.strip
	move.w	d6,$ffff8a36.w		; the registers as one pass leaves them
	move.w	bd_c_em1,$ffff8a28.w
	move.w	bd_c_em3,$ffff8a2c.w
	move.w	bd_c_syi,$ffff8a22.w
	move.w	bd_c_dyi,$ffff8a30.w
	subq.w	#1,d6
	move.w	$ffff8a2e.w,d5		; the destination: + the lines x ((words - 1) x X increment + Y increment)
	muls	d6,d5
	add.w	bd_c_dyi,d5
	muls	d7,d5
	add.l	a1,d5
	move.l	d5,$ffff8a32.w
	move.l	a0,$ffff8a24.w
	moveq	#2,d5
	and.b	$ffff8a3a.w,d5		; (the source moves only when the HOP reads it)
	beq.s	.x
	move.w	$ffff8a20.w,d5
	muls	d6,d5
	add.w	bd_c_syi,d5
	muls	d7,d5
	add.l	a0,d5
	move.l	d5,$ffff8a24.w
.x:	movem.l	(sp)+,d3-d7/a0-a1
	movem.l	(sp)+,d0-d2
	rts
.n:	bra	blit_go_split
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
	even
bd_c_syi:	ds.w	1		; (blit_go's column strips: the pass's Y increments and end masks)
bd_c_dyi:	ds.w	1
bd_c_em1:	ds.w	1
bd_c_em3:	ds.w	1
bd_c_piece:	ds.w	1
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
