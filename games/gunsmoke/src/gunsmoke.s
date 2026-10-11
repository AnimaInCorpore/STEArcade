; Gun.Smoke for Atari STE; translated main CPU (fixed ROM and four banks), sound omitted.
MAX_PENDING = 3				; ticks that may be waiting (the game catches up with the 60 Hz of the arcade after a slow frame)
	ifnd MAX_SKIP
MAX_SKIP = 2				; frames that are not drawn in a row while the game is behind
	endc

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
; picture's first line and the palette is black there and below the picture.

PIC_TOP = 10
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
JP1_B1 = $10<<JP_SH1				; A, B, C: shoot left, straight, right
JP1_B2 = $20<<JP_SH1
JP1_B3 = $40<<JP_SH1
JP2_RIGHT = $01<<JP_SH2
JP2_LEFT = $02<<JP_SH2
JP2_DOWN = $04<<JP_SH2
JP2_UP = $08<<JP_SH2
JP2_B1 = $10<<JP_SH2
JP2_B2 = $20<<JP_SH2
JP2_B3 = $40<<JP_SH2
JP_START1 = $01<<24
JP_START2 = $02<<24
JP_COIN1 = $40<<24
JP_COIN2 = $80<<24
	include	"jagpad.s"
	include	"ikbd.s"

; The Z80 address space as 68k addresses ("signed" model: a6 = G_Z80 = the Z80 address 0, 8000-FFFF below it).

G_Z80 = g_block+$8000			; a6
Z_SYSTEM = G_Z80-$4000			; $C000: SYSTEM, P1, P2, DSW1, DSW2
Z_PROT = G_Z80-$3B37			; $C4C9-C4CB: the protection bytes (MAME: ff 00 00)
Z_LATCH = G_Z80-$37FC			; $C804: bank (bits 2-3), flip (6), text on (7)
Z_LAYERS = G_Z80-$27FA			; $D806: background on (4), sprites on (5), sprite bank 3 (0-2)
RESCAN = $B000				; $00B0 byte swapped: where the interrupt returns to (the scheduler's scan)

dbgcnt	macro	; \1 = a word counter (DEBUG builds)
	ifd DEBUG
	addq.w	#1,\1
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

	lea	fixed_rom,a0		; the fixed ROM at Z80 0000-7FFF
	lea	G_Z80,a1
	move	#$8000/4-1,d0
.copyrom:
	move.l	(a0)+,(a1)+
	dbf	d0,.copyrom
	lea	g_block,a0		; 8000-FFFF: the unmapped I/O reads $FF, RAM and video RAM start as 0
	move	#$5000/4-1,d0
.ff:	move.l	#-1,(a0)+
	dbf	d0,.ff
	move	#$3000/4-1,d0
.zero:	clr.l	(a0)+
	dbf	d0,.zero
	move.b	#$FF,Z_PROT
	clr.b	Z_PROT+1
	clr.b	Z_PROT+2
	clr.b	Z_LATCH
	clr.b	Z_LAYERS

	stage	$ff0
	bsr	init_hardware
	stage	$0ff
	bsr	init_video
	stage	$0f0
	bsr	init_render
	stage	$00f
	bsr	init_dispatch
	bsr	gs_latch
	bsr	cs_init

	move.b	#$FF,Z_SYSTEM
	move.b	#$FF,Z_SYSTEM+1
	move.b	#$FF,Z_SYSTEM+2
	move.b	#$F7,Z_SYSTEM+3		; DSW1: bonus 30K 100K 100K+, demo on, upright, normal, no freeze, no service
	move.b	#$FF,Z_SYSTEM+4		; DSW2: 1 coin 1 credit, 3 lives, demo sound on
	move.b	#$FF,in_sys
	move.b	#$FF,in_p1
	move.b	#$FF,in_p2

	lea	gs_fixed_dispatch,a4
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
; Dispatch by the natural Z80 pc (d7.w): 0000-7FFF through the fixed table (a4), 8000-BFFF through the table of the
; current bank, E0F8 / E0FB the RAM trampoline (gen.TRAMPOLINE).
; ------------------------------------------------------------------------------

gs_dispatch:
	and.l	#$ffff,d7
	cmp.w	#$8000,d7
	bhs.s	.high
	lsl.l	#2,d7
	move.l	(a4,d7.l),-(sp)
	rts
.high:
	cmp.w	#$c000,d7
	bhs.s	.ram
	sub.w	#$8000,d7
	lsl.l	#2,d7
	move.l	a0,-(sp)
	move.l	g_wdispatch,a0
	move.l	(a0,d7.l),d7
	move.l	(sp)+,a0
	move.l	d7,-(sp)
	rts
.ram:
	cmp.w	#$e0f8,d7
	beq	ZE0F8
	cmp.w	#$e0fb,d7
	beq	ZE0FB
	jmp	z80_badpc

init_dispatch:
	lea	gs_fixed_dispatch,a0
	move.l	#z80_badpc,d0
	move.l	#32768/4-1,d1
	bsr	fill_dispatch
	lea	gs_invalid_dispatch,a0	; (and the bank tables after it)
	move.l	#(GS_WINDOW_TABLES*16384)/4-1,d1
	bsr	fill_dispatch
	lea	gs_fixed_dispatch,a0
	lea	gs_entries_fixed,a1
	bsr	scatter
	lea	gs_entry_banks,a2
	lea	gs_dispatch_targets,a3
	moveq	#3,d3
.bank:
	move.l	(a2)+,a1
	move.l	(a3)+,a0
	bsr	scatter
	dbf	d3,.bank
	rts
fill_dispatch:
	move.l	d0,(a0)+
	move.l	d0,(a0)+
	move.l	d0,(a0)+
	move.l	d0,(a0)+
	subq.l	#1,d1
	bpl.s	fill_dispatch
	rts
scatter:
	moveq	#0,d1
.next:
	move.w	(a1)+,d1
	cmp.w	#$ffff,d1
	beq.s	.done
	lsl.l	#2,d1
	move.l	(a1)+,(a0,d1.l)
	moveq	#0,d1
	bra.s	.next
.done:
	rts

; After a store to C804 or D806 (gen.LATCH_SITES): the bank from C804 (bits 2-3) selects the window's ROM copy and its
; dispatch table.  Keeps every register and the condition codes.
gs_latch:
	move	sr,-(sp)
	movem.l	d0/a0,-(sp)
	moveq	#0,d0
	move.b	Z_LATCH,d0
	lsr.b	#2,d0
	and.w	#3,d0
	move.b	d0,g_bank
	lea	gs_dispatch_targets,a0
	lsl.w	#2,d0
	move.l	(a0,d0.w),g_wdispatch
	lsl.w	#8,d0
	lsl.w	#4,d0			; bank * $4000
	lea	bank_rom+$8000,a0
	add.l	d0,a0
	move.l	a0,g_winbase
	movem.l	(sp)+,d0/a0
	move	(sp)+,sr
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
	bsr	cs_off

	ifnd SIM
.w1:	btst	#1,$fffffc00.w
	beq.s	.w1
	move.b	#$08,$fffffc02.w
	endc

	move	#$2300,sr
	rts

quit:
	move	#$2700,sr
	lea	own_stack_top,sp
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

; The VBL: shows the finished frame, copies the input into the Z80 block, counts the arcade's vertical blanks: six
; ticks to five VBLs (the arcade runs at 59.6 Hz, the STE shows 50).

vbl:
	ifnd SIM
	borders_vbl			; (first thing: Timer B counts the frame's lines)
	endc
	movem.l	d0-d1/a0,-(sp)
	addq.l	#1,frame_counter
	bsr	vbl_video
	bsr	jagpad_poll
	jp_merge	in_sys,Z_SYSTEM,0	; (the program only reads them; the pads merged)
	jp_merge	in_p1,Z_SYSTEM+1,1
	jp_merge	in_p2,Z_SYSTEM+2,2
	ifd AUTOPLAY				; (benchmark build: scripted coin, start, fire and joystick, period 3000 ticks)
	moveq #0,d0
	move.w isr_count,d0
	divu	#3000,d0
	swap	d0
	and.l	#$ffff,d0
	cmp.w	#700,d0
	blo.s	.ap1
	cmp.w	#704,d0
	bhs.s	.ap1
	move.b	#$BF,Z_SYSTEM			; coin 1
.ap1:	cmp.w	#740,d0
	blo.s	.ap2
	cmp.w	#744,d0
	bhs.s	.ap2
	move.b	#$FE,Z_SYSTEM			; start 1
.ap2:	cmp.w	#800,d0
	blo.s	.ap3
	move.w	d0,d1
	lsr.w	#5,d0
	and.w	#7,d0
	lea	ap_dirs(pc),a0
	move.b	(a0,d0.w),d0
	btst	#2,d1
	beq.s	.apf
	and.b	#$9F,d0				; buttons 2 and 3 every other 4 ticks
.apf:	move.b	d0,Z_SYSTEM+1
.ap3:
	endc
	addq.b	#1,vbl_pending
	subq.b	#1,vbl_phase
	bpl.s	.ph
	move.b	#4,vbl_phase
	addq.b	#1,vbl_pending
.ph:	cmp.b	#MAX_PENDING,vbl_pending
	bls.s	.cap
	move.b	#MAX_PENDING,vbl_pending	; (a game that is behind by more than this runs slower)
.cap:
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
ap_dirs:	dc.b	$F7,$F7,$F6,$F7,$F5,$F7,$FE,$FD		; (active low: right 0, left 1, down 2, up 3)
	endc

; ------------------------------------------------------------------------------
; The idle hook ($00CE: the scheduler found no task ready, machine.py run_frame_port): draws the frame the last tick
; made, then delivers the interrupt when a tick is due (RST 38, returning to the scheduler's scan at $00B0), else
; returns: the scheduler scans again (nothing changes) and comes back here.
; ------------------------------------------------------------------------------

z80_hook:
	tst.b	quit_flag
	bne	quit
	movem.l	d0-d7/a0-a6,-(sp)
	tst.b	frame_dirty
	beq.s	.check
	tst.b	vbl_pending
	beq.s	.render
	addq.b	#1,render_skips
	cmp.b	#MAX_SKIP,render_skips
	bls.s	.check
.render:
	clr.b	render_skips
	clr.b	frame_dirty
	bsr	render_frame
	ifd SIM
	bsr	sim_frame_done
	endc
.check:
	tst.b	vbl_pending
	bne.s	.deliver
	ifd SIM
	bsr	sim_wait
	bra.s	.check
	endc
	movem.l	(sp)+,d0-d7/a0-a6
	rts
.deliver:
	ifnd NOSOUND
	bsr	cs_tick			; (the sound driver's tick: the latch the last tick left)
	endc
	movem.l	(sp)+,d0-d7/a0-a6
	lea	own_stack_top,sp	; (the hook's continuation is dropped: the handler returns to $00B0 by itself)
	subq.b	#1,vbl_pending
	st	frame_dirty
	addq.w	#1,isr_count
	move.w	#RESCAN,-(a5)
	jmp	Z0038

; C806 (005F, gen config write hook) latches the sprite list: the first four bytes of each of the 128 entries of 32
; bytes at F000-FFFF (code, attribute, y, x).  Keeps every register and the condition codes.
buffer_sprites:
	movem.l	d0/a0-a1,-(sp)
	lea	G_Z80-$1000,a0
	lea	sprite_buffer,a1
	moveq	#127,d0
.loop:
	move.l	(a0),(a1)+
	lea	32(a0),a0
	dbf	d0,.loop
	movem.l	(sp)+,d0/a0-a1
	rts

	borders_handlers
	jagpad_text
	jagpad_maps

; ------------------------------------------------------------------------------
; Keyboard / joystick (IKBD): SYSTEM, P1 and P2 are active low bytes
; ------------------------------------------------------------------------------

acia_isr:
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
	; joystick 1 (port 1) plays player 1, joystick 0 player 2: right 0, left 1, down 2, up 3, fire = button 2 (5,
	; the straight shot)
	moveq	#0,d0
	move.b	joy1_state,d1
	bsr.s	joy_bits
	move.b	d0,p1_joy
	moveq	#0,d0
	move.b	joy0_state,d1
	bsr.s	joy_bits
	move.b	d0,p2_joy
	bsr	compose_inputs
	bra	.again

.done:
	movem.l	(sp)+,d0-d2/a0
	rte

joy_bits:
	btst	#3,d1			; right
	beq.s	.j1
	bset	#0,d0
.j1:	btst	#2,d1			; left
	beq.s	.j2
	bset	#1,d0
.j2:	btst	#1,d1			; down
	beq.s	.j3
	bset	#2,d0
.j3:	btst	#0,d1			; up
	beq.s	.j4
	bset	#3,d0
.j4:	tst.b	d1			; fire
	bpl.s	.j5
	bset	#5,d0
.j5:	rts

; in_sys / in_p1 / in_p2: active low (SYSTEM bit 3, MAME's unconnected VBLANK, stays 1)

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

; scancode, SYSTEM bits (start 1 = 0, start 2 = 1, coin 1 = 6, coin 2 = 7), player 1 bits (right 0, left 1, down 2,
; up 3, the shots left 4, straight 5, right 6), player 2 bits

key_table:
	dc.b	$4d,$00,$01,$00		; right
	dc.b	$4b,$00,$02,$00		; left
	dc.b	$50,$00,$04,$00		; down
	dc.b	$48,$00,$08,$00		; up
	dc.b	$1d,$00,$10,$00		; control = shoot left
	dc.b	$39,$00,$20,$00		; space = shoot straight
	dc.b	$38,$00,$40,$00		; alternate = shoot right
	dc.b	$2c,$00,$10,$00		; Z = shoot left
	dc.b	$2d,$00,$20,$00		; X = shoot straight
	dc.b	$2e,$00,$40,$00		; C = shoot right
	dc.b	$02,$01,$00,$00		; 1 = start 1
	dc.b	$03,$02,$00,$00		; 2 = start 2
	dc.b	$06,$40,$00,$00		; 5 = coin 1
	dc.b	$07,$80,$00,$00		; 6 = coin 2
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

	borders_blit_go

; The Z80 halt: not used by the program (the translator emits the call for a halt in data it took for code).

z80_halt:
	move.l	frame_counter,d7
.wait:	cmp.l	frame_counter,d7
	beq.s	.wait
	rts

	ifd DEBUG
; COUNTERS.BIN (words): VBLs, renders, the ticks the Z80 handled (isr_count), the frames whose top border the VBL
; armed, the top border / Timer B events that started too late (engine/rt/borders.s); (long) blit_go's passes run in
; pieces

dbg_counters:
	lea	dbg_buf,a0
	move.w	frame_counter+2,(a0)+
	move.w	dbg_renders,(a0)+
	move.w	isr_count,(a0)+
	move.w	bd_fallbacks,(a0)+
	move.w	bd_late_top,(a0)+
	move.w	bd_late_on,(a0)+
	move.w	bd_late_low,(a0)+
	move.w	bd_late_off,(a0)+
	move.l	bd_pieced,(a0)+
	clr	-(sp)
	pea	dbg_name2
	move	#$3c,-(sp)
	trap	#1
	addq	#8,sp
	move	d0,d6
	pea	dbg_buf
	move.l	#20,-(sp)
	move	d6,-(sp)
	move	#$40,-(sp)
	trap	#1
	lea	12(sp),sp
	move	d6,-(sp)
	move	#$3e,-(sp)
	trap	#1
	addq	#4,sp
	ifd BD_PCLOG
	move.l	#init_hardware,bd_pc_base	; (to find the PCs in the map: its address)
	clr	-(sp)
	pea	bd_pc_name
	move	#$3c,-(sp)
	trap	#1
	addq	#8,sp
	move	d0,d6
	pea	bd_pc_base
	move.l	#4+2+256,-(sp)
	move	d6,-(sp)
	move	#$40,-(sp)
	trap	#1
	lea	12(sp),sp
	move	d6,-(sp)
	move	#$3e,-(sp)
	trap	#1
	addq	#4,sp
	endc
	rts
	ifd BD_PCLOG
bd_pc_name:
	dc.b	"LATEPC.BIN",0
	even
	endc
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
	moveq	#99,d0			; the dump: d7 = the address (an untranslated target: its pc), the stack
	bra	crash_common

	include "render.s"

; ------------------------------------------------------------------------------
; The sound (engine/rt/capsnd.s; the data from tools/sound.py)

CS_LATCH = G_Z80-$3800			; C800: the main CPU's sound latch
	include	"cs_data.s"
	section text,code
	include	"capsnd.s"
	section text,code

; ------------------------------------------------------------------------------
; The translated program (and its dispatch lists in the data section).

	include "code_gunsmoke.s"

	section text,code
	include "rtlib.s"

; ------------------------------------------------------------------------------
	section data,data
; ------------------------------------------------------------------------------

	even
fixed_rom:	incbin "fixed.rom"
bank_rom:	incbin "banks.rom"

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
frame_ready:	ds.b	1		; a frame is drawn, to be shown at the VBL (its ring + 1)
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
isr_count:	ds.w	1
dbg_renders:	ds.w	1
	even
crash_vector:	ds.w	1
crash_sp:	ds.l	1
crash_regs:	ds.l	16
crash_text:	ds.b	512
frame_counter:	ds.l	1
g_winbase:	ds.l	1		; the current ROM bank's copy + $8000
g_wdispatch:	ds.l	1		; the current bank's dispatch table
dbg_buf:	ds.l	16

	ds.l	1024
own_stack_top:

g_block:	ds.b	$10000		; the Z80's 64 KB (a6 = g_block + $8000)
sprite_buffer:	ds.b	512		; 128 x (code, attribute, y, x)
gs_fixed_dispatch:	ds.l	32768
