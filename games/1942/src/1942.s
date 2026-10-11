; ------------------------------------------------------------------------------
;
; 1942 for the Atari STE
;
; The arcade's main Z80 program is translated to 68000 code by tools/gen.py (engine/z80x.py); this
; file is the machine around it: STE video, input, the schedule, the ROM banks.  (The sound CPU is not
; translated: the main CPU only writes commands to it.)
;
; The schedule.  The program is a small cooperative kernel: tasks that sleep with `rst $18`, a scheduler
; that scans the task table in an idle loop ($0084-$009A, interrupts enabled) and two interrupts, RST 08
; (a sound command, line 109) and RST 10 (the vertical blank: sprite DMA, scroll, the tasks' timers).
; The foreground runs the tasks.  The VBL interrupt of the STE only raises `vbl_pending`; when the
; scheduler finds nothing to run (the hook at $009A, `z80_hook`) the runtime
;   1. draws the frame if the last pending VBL has been handled (its tasks have all slept again),
;   2. delivers a pending VBL: RST 08 and RST 10 run to completion with a token on the Z80 stack
;      (a return to it continues at the idle loop); RST 10 may also hand the CPU to another task
;      (`jp $0084`), then the handler's frame is simply gone: the 68000 stack was reset first.
; The arcade holds an interrupt line while it is masked, and ticks at 59.6 Hz.  The STE's 50 Hz VBL adds one tick to `vbl_pending`
; and every 5th VBL a second one, so the game runs at the arcade's speed (60 ticks a second) when the CPU allows; ticks that are due
; are run before the next frame is drawn (at most MAX_SKIP + 1 ticks per frame), the VBL shows the newest finished frame.  A game
; that is further behind than MAX_PENDING ticks runs slower.  -D NOTICK60: one tick per VBL as before.
; tools/machine.py `run_frame_port` is this schedule in Python; the lock-step test compares RAM at the
; end of every frame.
;
; Memory: one 64 KB block, a6 = block + $8000 (the Z80 address $0000-$7FFF above a6, $8000-$FFFF below it:
; the video RAM and RAM at $C000-$EFFF).  The ROM bank window $8000-$BFFF of the block is unused: the
; translated code reads the window through g_winbase (the current bank's copy + $8000, see gen.py).
;
; The CPU ROMs srb-03.m3 srb-04.m4 srb-05.m5 srb-06.m6 srb-07.m7 are embedded (rom_table).
;
; ------------------------------------------------------------------------------

MAX_PENDING = 3				; ticks that may be waiting (the game catches up with the 60 Hz of the arcade after a slow frame)
MAX_SKIP = 2				; frames that are not drawn in a row while the game is behind

BUSY = %10000000
HOG = %01000000
NFSR = %01000000

KEY_ESC = $01

	ifnd FRAMES
FRAMES = 0
	endc

; Border removal and the palette on / off: engine/rt/borders.s.  Its events come early and sync themselves to the
; video, so a Blitter pass may start at any time: none waits.  Passes longer than BLIT_PIECE words run in pieces
; (blit_go, there).

	ifnd TA_DATA
TA_DATA = 98
	endc
	ifnd TA_NOPS
TA_NOPS = 84
	endc

; The picture (256 lines) is centred in the ~276 lines the open borders show: the display starts PIC_TOP lines above the
; picture's first line and the palette is black there and below the picture (it must start at its 10th displayed line
; and end at the 265th).

PIC_TOP = 10				; the picture's first displayed line (the display starts this many lines above the window)
PIC_LINES = 256
BD_PALETTE = 1
	include	"borders.s"

; the pads (engine/rt/jagpad.s): SYSTEM, P1, P2 bits as in key_table (bytes 0-2 of each long)
JP_SH1 = 16
JP_SH2 = 8
JP1_RIGHT = $01<<JP_SH1
JP1_LEFT = $02<<JP_SH1
JP1_DOWN = $04<<JP_SH1
JP1_UP = $08<<JP_SH1
JP1_B1 = $10<<JP_SH1
JP1_B2 = $20<<JP_SH1
JP1_B3 = 0<<JP_SH1
JP2_RIGHT = $01<<JP_SH2
JP2_LEFT = $02<<JP_SH2
JP2_DOWN = $04<<JP_SH2
JP2_UP = $08<<JP_SH2
JP2_B1 = $10<<JP_SH2
JP2_B2 = $20<<JP_SH2
JP2_B3 = 0<<JP_SH2
JP_START1 = $01<<24
JP_START2 = $02<<24
JP_COIN1 = $80<<24
JP_COIN2 = $40<<24
	include	"jagpad.s"
	include	"ikbd.s"

; The Z80 address space as 68k addresses.

G_Z80 = g_block+$8000			; a6
Z_SYSTEM = g_block+$8000-$4000		; $C000: SYSTEM, P1, P2, DSWA, DSWB
Z_BANK = g_block+$8000-$37FA		; $C806
TOKEN = $FEBF				; $BFFE on the Z80 stack, byte swapped

dbgcnt	macro	; \1 = a word counter, \2 = the line: increased and shown as bits in plane 0 of the first chunk of that line of ring 0
	ifd DEBUG
	addq.w	#1,\1
	move.l	a0,-(sp)
	move.l	ring_base,a0
	move.w	\1,GAME_X+\2*STRIDE(a0)
	move.l	(sp)+,a0
	endc
	endm

stage	macro	; (colour of the background colour as progress marks, -D STAGES=1)
	ifd STAGES
	move	#\1,$ffff8240.w
	endc
	endm

	section text,code

; ------------------------------------------------------------------------------
; Start
; ------------------------------------------------------------------------------

start:
	clr.l	-(sp)
	move	#$20,-(sp)
	trap	#1
	addq	#6,sp
	move.l	d0,old_ssp
	lea	own_stack_top,sp
	lea	own_stack_top-4096,a0	; (the unused part of the stack is marked: the crash dump shows how deep it went)
	move	#1024-1,d0
.mark:	move.l	#$A5A5A5A5,(a0)+
	dbf	d0,.mark

	stage	$f00
	bsr	load_roms
	stage	$ff0

	bsr	init_hardware
	stage	$0ff
	bsr	init_video
	stage	$0f0
	bsr	init_render
	stage	$00f
	ifd DEBUG
	bsr	dbg_dump
	endc

	lea	z80_dispatch_sw,a1	; the dispatch table: every translated pc, and the token
	lea	z80_entries,a2
	bsr	init_table

	move.b	#$FF,Z_SYSTEM
	move.b	#$FF,Z_SYSTEM+1
	move.b	#$FF,Z_SYSTEM+2
	move.b	#$F7,Z_SYSTEM+3		; DSWA: upright, 20K 80K 80K+, 3 lives, 1 coin 1 credit
	move.b	#$FF,Z_SYSTEM+4		; DSWB: normal, no freeze, no flip, no service
	move.b	#$FF,in_sys
	move.b	#$FF,in_p1
	move.b	#$FF,in_p2
	clr.b	g_bank
	bsr	g_bank_w_set

	lea	z80_dispatch_sw,a4
	lea	G_Z80,a6
	lea	G_Z80-1,a5		; SP = $FFFF as after a reset (the program sets it itself)
	moveq	#0,d0
	moveq	#0,d1
	moveq	#0,d2
	moveq	#0,d3
	moveq	#0,d4
	moveq	#0,d5
	moveq	#0,d6
	moveq	#0,d7
	sub.l	a0,a0
	sub.l	a1,a1
	sub.l	a2,a2
	sub.l	a3,a3
	move	#$2300,sr
	jmp	Z0000

; ------------------------------------------------------------------------------
; The arcade ROMs are part of the program (incbin, rom_table): copied to where the
; translated code reads them
; ------------------------------------------------------------------------------

load_roms:
	lea	g_win,a0		; the banks: 3 ROMs, padded with $FF (the board reads FF there)
	move.l	#$10000/4-1,d0
	moveq	#-1,d1
.fill:	move.l	d1,(a0)+
	dbf	d0,.fill
	lea	rom_table,a2
.next:	move.l	(a2)+,d0		; source, 0 = the end
	beq.s	.done
	move.l	d0,a0
	move.l	(a2)+,a1		; destination
	move.l	(a2)+,d0		; bytes, a multiple of 4
	lsr.l	#2,d0
	subq.l	#1,d0
.copy:	move.l	(a0)+,(a1)+
	subq.l	#1,d0
	bpl.s	.copy
	bra.s	.next
.done:
	rts

; The dispatch table (byte swapped pc order, 65536 longs): a1 = the table, a2 = the list of
; (pc.w, label.l) ending with $FFFF

init_table:
	move.l	a1,a4
	move.l	#z80_badpc,d1
	move	#65536/8-1,d2
.fill:
	rept 8
	move.l	d1,(a4)+
	endr
	dbf	d2,.fill
.next:
	moveq	#0,d2
	move.w	(a2)+,d2
	cmp.w	#$ffff,d2
	beq.s	.done
	move.l	(a2)+,d3
	ror.w	#8,d2
	lsl.l	#2,d2
	move.l	d3,(a1,d2.l)
	bra.s	.next
.done:
	rts

; ------------------------------------------------------------------------------
; Hardware
; ------------------------------------------------------------------------------

init_hardware:
	move	#$2700,sr

	movem.l	$ffff8240.w,d0-d7
	movem.l	d0-d7,old_palette

	move.b	$ffff8260.w,old_res
	move.b	$ffff820a.w,old_hz
	move.b	$ffff820f.w,old_linewid

	move.b	$ffff8201.w,old_screen+1
	move.b	$ffff8203.w,old_screen+2
	move.b	$ffff820d.w,old_screen+3

	move.b	$fffffa07.w,old_fa07
	move.b	$fffffa09.w,old_fa09
	move.b	$fffffa13.w,old_fa13
	move.b	$fffffa15.w,old_fa15
	move.b	$fffffa17.w,old_fa17
	move.b	$fffffa19.w,old_fa19
	move.b	$fffffa1b.w,old_fa1b
	move.b	$fffffa1d.w,old_fa1d
	move.b	$fffffa1f.w,old_fa1f
	move.b	$fffffa21.w,old_fa21

	move.l	$68.w,old_hbl
	move.l	$70.w,old_vbl
	move.l	$118.w,old_acia
	move.l	$120.w,old_timer_b
	move.l	$134.w,old_timer_a

	clr.b	$fffffa07.w
	clr.b	$fffffa09.w
	clr.b	$fffffa13.w
	clr.b	$fffffa15.w
	bclr	#3,$fffffa17.w

	lea	crash_stubs,a0		; exception vectors 2..11 -> crash dump
	lea	$08.w,a1
	moveq	#9,d0
.crash_vec:
	move.l	a0,(a1)+
	addq	#6,a0
	dbf	d0,.crash_vec

	move.l	#hbl,$68.w
	move.l	#vbl,$70.w
	move.l	#acia_isr,$118.w
	move.l	#timer_b,$120.w
	move.l	#timer_a,$134.w

	bset	#0,$fffffa07.w		; Timer B
	bset	#0,$fffffa13.w
	bset	#5,$fffffa07.w		; Timer A
	bset	#5,$fffffa13.w
	bset	#6,$fffffa09.w		; ACIA (keyboard, joysticks)
	bset	#6,$fffffa15.w

	ifnd SIM
.w1:	btst	#1,$fffffc00.w
	beq.s	.w1
	move.b	#$14,$fffffc02.w
.w2:	btst	#1,$fffffc00.w
	beq.s	.w2
	move.b	#$12,$fffffc02.w
	bsr	jagpad_init		; (the STE pads: absent on a plain ST)
	endc
	rts

restore_hardware:
	move	#$2700,sr

	movem.l	old_palette,d0-d7
	movem.l	d0-d7,$ffff8240.w

	move.b	old_res,$ffff8260.w
	move.b	old_hz,$ffff820a.w
	move.b	old_linewid,$ffff820f.w

	move.b	old_screen+1,$ffff8201.w
	move.b	old_screen+2,$ffff8203.w
	move.b	old_screen+3,$ffff820d.w

	move.b	old_fa07,$fffffa07.w
	move.b	old_fa09,$fffffa09.w
	move.b	old_fa13,$fffffa13.w
	move.b	old_fa15,$fffffa15.w
	move.b	old_fa17,$fffffa17.w
	move.b	old_fa1f,$fffffa1f.w
	move.b	old_fa19,$fffffa19.w
	move.b	old_fa1b,$fffffa1b.w
	move.b	old_fa1d,$fffffa1d.w
	move.b	old_fa21,$fffffa21.w

	move.l	old_hbl,$68.w
	move.l	old_vbl,$70.w
	move.l	old_acia,$118.w
	move.l	old_timer_b,$120.w
	move.l	old_timer_a,$134.w

	ifnd SIM
.w1:	btst	#1,$fffffc00.w
	beq.s	.w1
	move.b	#$08,$fffffc02.w
	endc

	move	#$2300,sr
	rts

quit:
	ifd DEBUG
	bsr	dbg_counters
	endc
	bsr	restore_hardware
	move.l	old_ssp,-(sp)
	move	#$20,-(sp)
	trap	#1
	addq	#6,sp
	clr	-(sp)
	trap	#1

; ------------------------------------------------------------------------------
; Interrupts
; ------------------------------------------------------------------------------

hbl:
	rte

; The VBL: shows the finished frame, copies the input into the Z80 block, tells the foreground that the arcade's
; vertical blank has come.  (Border removal and the scroll registers come with the renderer.)

vbl:
	ifnd SIM
	borders_vbl			; (first thing: Timer B counts the frame's lines)
	endc
	movem.l	d0-d1/a0,-(sp)
	dbgcnt	dbg_c4,3
	addq.l	#1,frame_counter
	tst.b	quit_flag
	bne	quit
	bsr	vbl_video
	bsr	jagpad_poll
	jp_merge	in_sys,Z_SYSTEM,0	; (the program only reads them; the pads merged)
	jp_merge	in_p1,Z_SYSTEM+1,1
	jp_merge	in_p2,Z_SYSTEM+2,2
	ifd AUTOPLAY				; (benchmark build: MAME's cheats for 1942b: lives E101, invincibility E0A5, and every FINISH frames
	move.b	#6,g_block+$E101-$8000		; "Finish Current Level Now!" (EBD0, E099, E102) to get to the later stages)
	move.b	#2,g_block+$E0A5-$8000
	ifd FINISH
	move.l	frame_counter,d0
	cmp.l	#1000,d0
	blo.s	.nofin
	divu	#FINISH,d0
	swap	d0
	tst.w	d0
	bne.s	.nofin
	move.b	#7,g_block+$EBD0-$8000
	move.b	#1,g_block+$E099-$8000
	move.b	#$43,g_block+$E102-$8000
.nofin:
	endc
	endc
	ifd AUTOPLAY				; (benchmark build: scripted coin, start, fire and joystick, period 3000 frames)
	move.l	frame_counter,d0
	divu	#3000,d0
	swap	d0
	and.l	#$ffff,d0
	cmp.w	#700,d0
	blo.s	.ap1
	cmp.w	#740,d0
	bhs.s	.ap1
	move.b	#$7F,Z_SYSTEM			; coin 1
.ap1:	cmp.w	#760,d0
	blo.s	.ap2
	cmp.w	#800,d0
	bhs.s	.ap2
	move.b	#$FE,Z_SYSTEM			; start 1
.ap2:	cmp.w	#840,d0
	blo.s	.ap3
	lsr.w	#5,d0
	and.w	#7,d0
	lea	ap_dirs(pc),a0
	move.b	(a0,d0.w),d0
	and.b	#$EF,d0				; fire held
	move.b	d0,Z_SYSTEM+1
.ap3:
	endc
	ifd NOTICK60
	st	vbl_pending
	else
	addq.b	#1,vbl_pending		; the arcade ticks at 59.6 Hz, the STE shows 50: six ticks to five VBLs (a counter now)
	subq.b	#1,vbl_phase
	bpl.s	.ph
	move.b	#4,vbl_phase
	addq.b	#1,vbl_pending
.ph:	cmp.b	#MAX_PENDING,vbl_pending
	bls.s	.cap
	move.b	#MAX_PENDING,vbl_pending	; (a game that is behind by more than this runs slower)
.cap:
	endc
	if FRAMES
	move.l	frame_counter,d0
	cmp.l	#FRAMES,d0
	blt.s	.go_on
	st	quit_flag
.go_on:
	endc
	movem.l	(sp)+,d0-d1/a0
	rte

	ifd AUTOPLAY
ap_dirs:	dc.b	$FF,$FE,$F7,$FD,$FA,$F6,$F9,$F5		; (active low: right 0, left 1, down 2, up 3)
	endc

; ------------------------------------------------------------------------------
; The hook at $009A (the scheduler found no task to run) = the schedule, see the header.
; Reached from the translated code with the continuation (Z009A_r) on the native stack; the Z80 registers are
; dead here, a4-a6 are kept.
; ------------------------------------------------------------------------------

z80_hook:
	cmp.w	#$0087,d7
	beq	scan_native
	stage	$0f0
	dbgcnt	dbg_c3,2
	tst.b	frame_dirty
	beq.s	.check
	ifnd NOTICK60
	tst.b	vbl_pending		; another tick is due: the frame is drawn when the game has caught up, at the latest every
	beq.s	.render			; MAX_SKIP + 1 ticks
	addq.b	#1,render_skips
	cmp.b	#MAX_SKIP,render_skips
	bls.s	.check
	endc
.render:
	clr.b	render_skips
	clr.b	frame_dirty
	movem.l	d0-d7/a0-a6,-(sp)
	bsr	render_frame		; (makes the frame ready to be shown)
	movem.l	(sp)+,d0-d7/a0-a6
	ifd SIM
	bsr	sim_frame_done		; the test harness compares the RAM here
	endc
.check:
	tst.b	vbl_pending
	bne.s	.deliver
	ifd DEBUG				; idle spins: waiting for the ring to be shown (a frame to draw, dbg_idle_b) or for nothing (dbg_idle_f)
	tst.b	frame_dirty
	beq.s	.idle_f
	addq.l	#1,dbg_idle_b
	bra.s	.idle_x
.idle_f:	addq.l	#1,dbg_idle_f
.idle_x:
	endc
	ifd SIM
	bsr	sim_wait		; (the harness: sets vbl_pending and the inputs, returns)
	bra.s	.check
	endc
	rts				; to Z009A_r: the scan goes on

.deliver:
	stage	$ff0
	addq.w	#1,isr_count
	ifd DEBUG				; histogram: VBLs since the last tick (bin 0-9)
	movem.l	d0-d1/a0,-(sp)			; (the Z80 registers: A, BC and their alternates in the upper words)
	move.l	frame_counter,d0
	move.l	d0,d1
	sub.l	dbg_last,d1
	move.l	d0,dbg_last
	cmp.w	#9,d1
	bls.s	.hb
	moveq	#9,d1
.hb:	add.w	d1,d1
	lea	dbg_hist,a0
	addq.w	#1,(a0,d1.w)
	movem.l	(sp)+,d0-d1/a0
	endc
	subq.b	#1,vbl_pending
	st	frame_dirty
	lea	own_stack_top,sp	; the hook's frame is dropped
	clr.b	g_iff			; (an interrupt disables the interrupts until the handler's ei)
	move.b	#1,isr_stage
	move.w	#TOKEN,-(a5)
	jmp	Z0008

; The scheduler's search for a task to run ($0087-$009A: `ei`, then 16 task records of 4 bytes from $EFC0: the first whose state byte is
; $20 or more) done at once.  It ends at $009C (found: A = the state, HL = the record, B = the records left, C = its number) or, when
; there is none, at the idle hook $009A with the registers the loop leaves.  The hook's frame (the scan's continuation) is dropped.

scan_native:
	lea	own_stack_top,sp
	st	g_iff				; ei
	clr.w	d1				; C (z80x.FAST: word writes only, the upper words of d1-d3 are BC' DE' HL')
	move.w	#$EFC0,d7			; the record
	moveq	#15,d5
.next:	move.b	(a6,d7.w),d0
	cmp.b	#$20,d0
	bhs.s	.found
	addq.w	#4,d7
	addq.w	#1,d1
	dbf	d5,.next
	; none: C = 16, B = 0, HL = $F000, A = the last state
	move.w	#$1000,d1			; (C in the high byte)
	move.w	#$F000,d3
	move.w	#4,d2
	clr.w	d6				; (F; the upper word is F', z80x alt_af="upper")
	jmp	Z009A
.found:	move.w	d1,d5				; the number of the record
	lsl.w	#8,d5				; C
	move.w	#16,d3
	sub.w	d1,d3				; B
	or.w	d3,d5
	move.w	d5,d1
	move.w	d7,d3				; HL
	move.w	#4,d2
	clr.w	d6
	jmp	Z009C

; The token on the Z80 stack returns here: after RST 08 comes RST 10, after that the idle loop goes on.

z80_irq_ret:
	cmp.b	#1,isr_stage
	bne.s	.done
	move.b	#2,isr_stage
	clr.b	g_iff
	move.w	#TOKEN,-(a5)
	jmp	Z0010
.done:
	clr.b	isr_stage
	jmp	Z009A_r

; ------------------------------------------------------------------------------
; The bank latch ($C806, hooked after every store to it): the window $8000-$BFFF of the Z80 shows ROM bank 0-2
; (srb-05, srb-06, srb-07), bank 3 is empty ($FF).  g_winbase = the bank's copy + $8000.
; ------------------------------------------------------------------------------

g_bank_w:
	move.b	Z_BANK,d7
	and.b	#3,d7
	move.b	d7,g_bank
g_bank_w_set:
	moveq	#0,d7
	move.b	g_bank,d7
	lsl.w	#7,d7
	lsl.w	#7,d7			; * $4000
	add.l	#g_win+$8000,d7
	move.l	d7,g_winbase
	rts

	borders_handlers
	jagpad_text
	jagpad_maps
	borders_blit_go

; ------------------------------------------------------------------------------
; Keyboard / joystick (IKBD): SYSTEM, P1 and P2 are active low bytes
; ------------------------------------------------------------------------------

acia_isr:
	addq	#1,cnt_acia
	movem.l	d0-d2/a0,-(sp)

.again:
	ikbd_byte

.not_esc:
	lea	key_table,a0

.find:
	move.b	(a0),d0
	beq	.again
	cmp.b	d0,d1
	beq	.found
	addq	#4,a0
	bra	.find

.found:
	tst.b	d2
	bmi	.release

	move.b	1(a0),d0
	or.b	d0,sys_kbd
	move.b	2(a0),d0
	or.b	d0,p1_kbd
	move.b	3(a0),d0
	or.b	d0,p2_kbd
	bsr	compose_inputs
	bra	.again

.release:
	move.b	1(a0),d0
	not.b	d0
	and.b	d0,sys_kbd
	move.b	2(a0),d0
	not.b	d0
	and.b	d0,p1_kbd
	move.b	3(a0),d0
	not.b	d0
	and.b	d0,p2_kbd
	bsr	compose_inputs
	bra	.again

.packet_byte:
	clr.b	ikbd_state
	cmp.b	#1,d0
	bne	.joy1
	move.b	d1,joy0_state
	bra	.joy_update

.joy1:
	move.b	d1,joy1_state

.joy_update:
	; joystick 1 (port 1) plays player 1, joystick 0 player 2: right 0, left 1, down 2, up 3, fire 4 (button 1)
	moveq	#0,d0
	move.b	joy1_state,d1
	btst	#3,d1			; right
	beq	.j1
	bset	#0,d0
.j1:	btst	#2,d1			; left
	beq	.j2
	bset	#1,d0
.j2:	btst	#1,d1			; down
	beq	.j3
	bset	#2,d0
.j3:	btst	#0,d1			; up
	beq	.j4
	bset	#3,d0
.j4:	tst.b	d1			; fire
	bpl	.j5
	bset	#4,d0
.j5:	move.b	d0,p1_joy
	moveq	#0,d0
	move.b	joy0_state,d1
	btst	#3,d1
	beq	.k1
	bset	#0,d0
.k1:	btst	#2,d1
	beq	.k2
	bset	#1,d0
.k2:	btst	#1,d1
	beq	.k3
	bset	#2,d0
.k3:	btst	#0,d1
	beq	.k4
	bset	#3,d0
.k4:	tst.b	d1
	bpl	.k5
	bset	#4,d0
.k5:	move.b	d0,p2_joy
	bsr	compose_inputs
	bra	.again

.done:
	movem.l	(sp)+,d0-d2/a0
	rte

; in_sys / in_p1 / in_p2: active low

compose_inputs:
	move.b	sys_kbd,d0
	not.b	d0
	move.b	d0,in_sys
	move.b	p1_kbd,d0
	or.b	p1_joy,d0
	not.b	d0
	move.b	d0,in_p1
	move.b	p2_kbd,d0
	or.b	p2_joy,d0
	not.b	d0
	move.b	d0,in_p2
	rts

; scancode, SYSTEM bits (start 1 = 0, start 2 = 1, coin 2 = 6, coin 1 = 7), player 1 bits (right 0, left 1, down 2,
; up 3, button 1 = 4 (fire), button 2 = 5 (loop)), player 2 bits

key_table:
	dc.b	$4d,$00,$01,$00		; right
	dc.b	$4b,$00,$02,$00		; left
	dc.b	$50,$00,$04,$00		; down
	dc.b	$48,$00,$08,$00		; up
	dc.b	$39,$00,$10,$00		; space = fire
	dc.b	$1d,$00,$10,$00		; control = fire
	dc.b	$38,$00,$20,$00		; alternate = loop
	dc.b	$02,$01,$00,$00		; 1 = start 1
	dc.b	$03,$02,$00,$00		; 2 = start 2
	dc.b	$06,$80,$00,$00		; 5 = coin 1
	dc.b	$07,$40,$00,$00		; 6 = coin 2
	dc.b	0,0,0,0
	even

; ------------------------------------------------------------------------------
; Crash dump (CRASH.TXT: vector, registers, the stack top)

crash_stubs:
	rept 10
	moveq	#REPTN+2,d0
	bra.w	crash_common
	endr

crash_common:
	move	#$2700,sr
	move	d0,crash_vector
	movem.l	d0-d7/a0-a6,crash_regs
	move.l	sp,crash_sp
	lea	crash_text,a0
	lea	crash_vector,a1
	moveq	#0,d1
	move	(a1),d1
	bsr	hex_word
	move.b	#' ',(a0)+
	lea	crash_sp,a1
	move.l	(a1),d1
	bsr	hex_long
	move.b	#' ',(a0)+
	lea	start(pc),a1		; the load address: map address = address - this
	move.l	a1,d1
	bsr	hex_long
	move.b	#13,(a0)+
	move.b	#10,(a0)+

	lea	crash_regs,a1
	moveq	#14,d2
.regs:
	move.l	(a1)+,d1
	bsr	hex_long
	move.b	#' ',(a0)+
	dbf	d2,.regs
	move.b	#13,(a0)+
	move.b	#10,(a0)+

	move.l	crash_sp,a1
	moveq	#15,d2
.stack:
	move	(a1)+,d1
	bsr	hex_word
	move.b	#' ',(a0)+
	dbf	d2,.stack
	move.b	#13,(a0)+
	move.b	#10,(a0)+
	lea	own_stack_top-4096,a1	; untouched stack longs from the bottom
	moveq	#0,d1
.untouched:
	cmp.l	#$A5A5A5A5,(a1)+
	bne.s	.touched
	addq.l	#1,d1
	cmp.w	#1024,d1
	blo.s	.untouched
.touched:
	bsr	hex_word
	move.b	#13,(a0)+
	move.b	#10,(a0)+

	lea	own_stack_top,sp
	move.l	a0,d7
	sub.l	#crash_text,d7

	clr	-(sp)			; Fcreate
	pea	crash_name
	move	#$3c,-(sp)
	trap	#1
	addq	#8,sp
	move	d0,d6

	pea	crash_text		; Fwrite
	move.l	d7,-(sp)
	move	d6,-(sp)
	move	#$40,-(sp)
	trap	#1
	lea	12(sp),sp

	move	d6,-(sp)		; Fclose
	move	#$3e,-(sp)
	trap	#1
	addq	#4,sp

	bsr	restore_hardware
	bsr	crash_notice
	clr	-(sp)
	trap	#1

hex_long:
	swap	d1
	bsr.s	hex_word
	swap	d1
hex_word:
	move	d1,-(sp)
	lsr	#8,d1
	bsr.s	hex_byte
	move	(sp)+,d1
hex_byte:
	move	d1,-(sp)
	lsr	#4,d1
	bsr.s	hex_digit
	move	(sp)+,d1
hex_digit:
	and	#15,d1
	move.b	hex_chars(pc,d1.w),(a0)+
	rts

hex_chars:
	dc.b	"0123456789ABCDEF"
crash_name:
	dc.b	"CRASH.TXT",0
	even

	ifd SIM
sim_wait:				; the test harness stops here when the foreground idles with nothing pending: it
	bra.s	sim_wait		; sets vbl_pending (and the inputs) and returns (rts) from here
sim_frame_done:				; the harness compares the RAM here (a frame is drawn), returns with rts
	bra.s	sim_frame_done
sim_render_ret:				; render_test.py calls render_frame with this as the return address
	bra.s	sim_render_ret
	endc

; The Z80 halt: not used by the program (the translator emits the call for a halt in data it took for code).

z80_halt:
	move.l	frame_counter,d7
.wait:	cmp.l	frame_counter,d7
	beq.s	.wait
	rts


	ifd DEBUG
; DEBUG.BIN: addresses of the program (longs: start, ring_base 0/1, clean_base, own_stack_top, g_block, z80_dispatch_sw)

dbg_dump:
	lea	dbg_buf,a0
	lea	start(pc),a1
	move.l	a1,(a0)+
	move.l	ring_base,(a0)+
	move.l	ring_base+4,(a0)+
	move.l	clean_base,(a0)+
	move.l	#own_stack_top,(a0)+
	move.l	#g_block,(a0)+
	move.l	#z80_dispatch_sw,(a0)+
	clr	-(sp)			; Fcreate
	pea	dbg_name
	move	#$3c,-(sp)
	trap	#1
	addq	#8,sp
	move	d0,d6
	pea	dbg_buf			; Fwrite
	move.l	#28,-(sp)
	move	d6,-(sp)
	move	#$40,-(sp)
	trap	#1
	lea	12(sp),sp
	move	d6,-(sp)		; Fclose
	move	#$3e,-(sp)
	trap	#1
	addq	#4,sp
	rts
dbg_name:
	dc.b	"DEBUG.BIN",0
	even
	endc


	ifd DEBUG
; COUNTERS.BIN (words): VBLs, hook calls, renders, blit_copy calls (low 16 bits each), the frames the Z80 handled (isr_count),
; dbg_hist; (longs) dbg_idle_b, dbg_idle_f, blit_go's passes run in pieces; (words) the frames whose top border the VBL
; armed, the top border / palette on / bottom border / palette off events that started too late (engine/rt/borders.s)

dbg_counters:
	lea	dbg_buf,a0
	move.w	frame_counter+2,(a0)+
	move.w	dbg_c3,(a0)+
	move.w	dbg_c2,(a0)+
	move.w	dbg_c1,(a0)+
	move.w	isr_count,(a0)+
	lea	dbg_hist,a1
	moveq	#9,d0
.h:	move.w	(a1)+,(a0)+
	dbf	d0,.h
	move.l	dbg_idle_b,(a0)+
	move.l	dbg_idle_f,(a0)+
	move.l	bd_pieced,(a0)+
	move.w	bd_fallbacks,(a0)+
	move.w	bd_late_top,(a0)+
	move.w	bd_late_on,(a0)+
	move.w	bd_late_low,(a0)+
	move.w	bd_late_off,(a0)+
	clr	-(sp)
	pea	dbg_name2
	move	#$3c,-(sp)
	trap	#1
	addq	#8,sp
	move	d0,d6
	pea	dbg_buf
	move.l	#52,-(sp)
	move	d6,-(sp)
	move	#$40,-(sp)
	trap	#1
	lea	12(sp),sp
	move	d6,-(sp)
	move	#$3e,-(sp)
	trap	#1
	addq	#4,sp
	rts
dbg_name2:
	dc.b	"COUNTERS.BIN",0
	even
	endc

; ------------------------------------------------------------------------------
; Fatal errors of the translated code
; ------------------------------------------------------------------------------

z80_badpc:
z80_badjump:
z80_unsupported:
	move	#$2700,sr
	ifd SIM
	bra.s	z80_badpc
	endc
	moveq	#99,d0			; the dump: d7 = the address (an untranslated target: its pc; a
	bra	crash_common		; dispatch miss: the swapped pc * 4), the stack

	include "render.s"

; ------------------------------------------------------------------------------
; The translated program (and its dispatch list in the data section).

	include "code_1942.s"

	section text,code
	include "rtlib.s"

; ------------------------------------------------------------------------------
	section data,data
; ------------------------------------------------------------------------------

rom_table:				; source, destination, bytes
	dc.l	rom_fixed,G_Z80,$8000
	dc.l	rom_banks,g_win,$C000
	dc.l	0
rom_fixed:	incbin	"rom_fixed.rom"
rom_banks:	incbin	"rom_banks.rom"
	even
	even

; ------------------------------------------------------------------------------
	section bss,bss
; ------------------------------------------------------------------------------

old_ssp:	ds.l	1
old_screen:	ds.l	1
old_palette:	ds.l	8
old_hbl:	ds.l	1
old_vbl:	ds.l	1
old_acia:	ds.l	1
old_timer_b:	ds.l	1
old_timer_a:	ds.l	1
old_res:	ds.b	1
old_hz:		ds.b	1
old_linewid:	ds.b	1
old_fa07:	ds.b	1
old_fa09:	ds.b	1
old_fa13:	ds.b	1
old_fa15:	ds.b	1
old_fa17:	ds.b	1
old_fa19:	ds.b	1
old_fa1b:	ds.b	1
old_fa1d:	ds.b	1
old_fa1f:	ds.b	1
old_fa21:	ds.b	1
	even

quit_flag:	ds.b	1
	borders_vars
	jagpad_vars
vbl_pending:	ds.b	1		; the arcade's vertical blanks that have come (a counter: the VBL adds, the idle hook takes one)
vbl_phase:	ds.b	1		; (every 5th VBL adds a second one: 60 ticks a second)
render_skips:	ds.b	1		; the ticks since the last frame was drawn
frame_dirty:	ds.b	1		; the tasks of the last tick have run: draw
frame_ready:	ds.b	1		; a frame is drawn, to be shown at the VBL
isr_stage:	ds.b	1		; 1 RST 08 runs, 2 RST 10
g_iff:		ds.b	1		; the program's interrupt enable (ei / di)
g1_ireg:	ds.b	1
g_bank:		ds.b	1
	ikbd_vars
joy0_state:	ds.b	1
joy1_state:	ds.b	1
sys_kbd:	ds.b	1
p1_kbd:		ds.b	1
p2_kbd:		ds.b	1
p1_joy:		ds.b	1
p2_joy:		ds.b	1
in_sys:		ds.b	1
in_p1:		ds.b	1
in_p2:		ds.b	1
	even
cnt_acia:	ds.w	1
dbg_c1:	ds.w	1
dbg_c2:	ds.w	1
dbg_c3:	ds.w	1
dbg_c4:	ds.w	1
dbg_c5:	ds.w	1
dbg_c6:	ds.w	1
isr_count:	ds.w	1
crash_vector:	ds.w	1
crash_sp:	ds.l	1
crash_regs:	ds.l	16
crash_text:	ds.b	512
frame_counter:	ds.l	1
g_winbase:	ds.l	1		; the current ROM bank's window copy + $8000
dbg_buf:	ds.l	16
dbg_hist:	ds.w	10
dbg_last:	ds.l	1
dbg_idle_b:	ds.l	1
dbg_idle_f:	ds.l	1

	ds.l	1024
own_stack_top:

g_block:	ds.b	$10000		; the Z80's 64 KB
g_win:		ds.b	$10000		; the ROM banks' copies: 3 + the empty one
z80_dispatch_sw:	ds.l	65536
