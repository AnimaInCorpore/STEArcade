; ------------------------------------------------------------------------------
;
; Super Xevious for the Atari STE
;
; The arcade's three Z80 programs (main, sub, sound) are translated to 68000 code by tools/gen.py (engine/z80x.py); this
; file is the machine around them: STE video (320 x 277 with the borders removed: the game's 224 x 288 rotated
; picture), the renderer (render.s), the custom I/O chips (06XX, 51XX, 50XX, 54XX), input and the schedule of
; tools/machine.py (Xevious.run_frame_port), which the lock-step test (tools/logic_test.py) compares frame by frame:
;
;   The main CPU's program is the foreground thread.  Its idle loop ($044C waits for the flag $8000 its IRQ handler
;   sets) and the boot's two spin loops ($02AD / $0310 wait for the 06XX's first read) are hooks (z80_hook): there the
;   frame happens, with the main CPU's registers on the stack: the sub CPU's foreground runs to its own idle loop
;   ($0356, flag $8002) with its register set, the sound CPU's boot likewise to $0098, the 51XX gets its frame (TC
;   high, low), the main CPU's IRQ handler runs if the program enabled it (latch $6820), the sub CPU's (latch $6821),
;   the sound CPU's NMI handler twice (latch $6822 = 0), the picture is drawn and the next arcade frame awaited.  The
;   06XX's NMIs (transfers to and from the 51XX, 50XX, 54XX) run right at the control write, as often as the program
;   keeps the transfer going.
;
; Memory: one block holds [sub ROM 32K | RAM 32K ($8000-$FFFF) | main ROM 32K]; the main CPU's code addresses with
; a6 = its ROM and signed word offsets (the RAM lies below), the sub CPU's with a6 = its ROM and long offsets (the RAM
; above).  The registers $6800-$7FFF (switches, latches, 06XX) are cells in each CPU's ROM half; the work RAM
; $7900-$7FFF lies in both halves and is copied at every change of CPU (sync_share).  The sound CPU has a block of its
; own (g3_block); the shared bytes it uses are copied around its turns and NMIs (g_sound_in / g_sound_out).
;
; The CPU ROMs are embedded (rom_table).
;
; ------------------------------------------------------------------------------

BUSY = %10000000
HOG = %01000000
NFSR = %01000000

	ifnd FRAMES
FRAMES = 0
	endc
	ifnd MAX_PENDING
MAX_PENDING = 2				; arcade frames that may be waiting for their turn
	endc
KEY_ESC = $01

	ifnd TA_DATA
TA_DATA = 98
	endc
	ifnd TA_NOPS
TA_NOPS = 84
	endc

; The Z80 address space as 68k addresses (see the header).

G_ROM1 = g_block+$10000			; main CPU: a6
G_IO1 = G_ROM1				; its $6800-$7FFF cells: G_IO1+addr
G_IO2 = g_block				; the sub CPU's
TOKEN = $0140				; $4001 on the Z80 stack, byte swapped
SHARE_LO = $7900			; the work RAM both CPUs use, in their own halves
SHARE_HI = $8000

BD_PALETTE = 0
	include	"borders.s"

; the pads (engine/rt/jagpad.s): jp_in bytes: in0 (joystick), in1 (fire, starts, coins), in2 (bit 0: the bomb button)
JP1_RIGHT = $02<<24
JP1_LEFT = $08<<24
JP1_UP = $01<<24
JP1_DOWN = $04<<24
JP1_B1 = $01<<16			; A: the zapper
JP1_B2 = $01<<8				; B: the blaster (bomb)
JP1_B3 = $01<<16			; C: the zapper
JP2_RIGHT = JP1_RIGHT
JP2_LEFT = JP1_LEFT
JP2_UP = JP1_UP
JP2_DOWN = JP1_DOWN
JP2_B1 = JP1_B1
JP2_B2 = JP1_B2
JP2_B3 = JP1_B3
JP_START1 = $04<<16
JP_START2 = $08<<16
JP_COIN1 = $10<<16
JP_COIN2 = JP_COIN1			; (one coin key, as the keyboard's)
	include	"jagpad.s"
	include	"ikbd.s"

chk_sp	macro
	ifd CHKSP
	cmp.l	vbl_sp,sp
	beq.s	.ok\@
	moveq	#\1,d0
	bra	crash_common
.ok\@:
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

	bsr	load_roms

	bsr	init_cells
	bsr	init_hardware
	bsr	init_video
	bsr	init_render

	lea	g1_dispatch,a0		; the dispatch tables in the order the code uses them
	lea	g1_dispatch_sw,a1
	move	#TABLE_ENTRIES,d0
	bsr	z80_init_dispatch
	lea	g2_dispatch,a0
	lea	g2_dispatch_sw,a1
	move	#TABLE_ENTRIES,d0
	bsr	z80_init_dispatch
	lea	g3_dispatch,a0
	lea	g3_dispatch_sw,a1
	move	#TABLE_ENTRIES,d0
	bsr	z80_init_dispatch

	bsr	ctx_reset		; the sub and sound CPUs at their reset vectors
	st	n51_held		; (the custom chips are held in reset until the program releases latch $6823)
	move.l	#$1234,rnd_state
	bsr	n50_init

	; The main CPU: the foreground thread.

	lea	g1_dispatch_sw,a4
	lea	G_ROM1,a6
	lea	g_ram+$1000,a5		; (the program sets SP itself)
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

; The sub and sound CPUs' contexts: registers 0, at their reset vectors.

ctx_reset:
	lea	ctx2,a0
	moveq	#15,d0
.c2:	clr.l	(a0)+
	dbf	d0,.c2
	move.l	#g2_dispatch_sw,ctx2+4*12	; a4
	move.l	#g_block,ctx2+4*14		; a6
	move.l	#Y0000,ctx2+4*15		; resume
	lea	ctx3,a0
	moveq	#15,d0
.c3:	clr.l	(a0)+
	dbf	d0,.c3
	move.l	#g3_dispatch_sw,ctx3+4*12	; a4
	move.l	#g3_block,ctx3+4*14		; a6
	move.l	#X0000,ctx3+4*15
	clr.b	booted2
	clr.b	booted3
	clr.b	g2_iff
	rts

; ------------------------------------------------------------------------------
; The arcade ROMs are part of the program (incbin, rom_table): copied to where the translated code reads them
; ------------------------------------------------------------------------------

load_roms:
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

; The I/O cells: the DIP switches as the program reads them (one bit of each bank per address), in all CPUs' halves.

init_cells:
	lea	G_IO1+$6800,a0
	lea	G_IO2+$6800,a1
	lea	g3_block+$6800,a2
	moveq	#0,d1			; bit
.dsw:
	moveq	#0,d0
	move.b	dswb,d2
	lsr.b	d1,d2
	and	#1,d2
	move.b	dswa,d3
	lsr.b	d1,d3
	and	#1,d3
	add	d3,d3
	or	d3,d2
	move.b	d2,(a0,d1.w)
	move.b	d2,(a1,d1.w)
	move.b	d2,(a2,d1.w)
	addq	#1,d1
	cmp	#8,d1
	blt.s	.dsw
	rts

dswa:	dc.b	$ff			; MAME's defaults: 1C/1C, 20K 60K 60K, 3 lives, upright
dswb:	dc.b	$7f			; Super Xevious: freeze off, normal difficulty, 1C/1C
	even

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
	bsr	snd_off

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

; The VBL: switches the screen when a picture is complete, counts the arcade frames that may run (vbl_pending) and polls
; the pads.  The game's interrupts are not delivered here: the frame is the foreground's stop (frame_stop).

vbl:
	borders_vbl			; (first: Timer B counts the frame's lines)
	movem.l	d0-d1/a0,-(sp)
	bsr	jagpad_poll

	tst.b	frame_ready
	beq.s	.no_swap
	clr.b	frame_ready
	move.l	display_screen_address,d0
	move.l	draw_screen_address,display_screen_address
	move.l	d0,draw_screen_address
	eori	#1,draw_index
	move.l	display_screen_address,d0
	add.l	#SHOW_OFFSET,d0		; the shown part
	move.l	d0,-(sp)
	move.b	1(sp),$ffff8201.w
	move.b	2(sp),$ffff8203.w
	move.b	3(sp),$ffff820d.w
	addq.l	#4,sp
.no_swap:

	addq.l	#1,frame_counter
	addq.b	#1,vbl_pending		; one arcade frame a VBL
	cmp.b	#MAX_PENDING,vbl_pending
	bls.s	.cap
	move.b	#MAX_PENDING,vbl_pending
.cap:
	tst.b	quit_flag
	bne	quit
	if FRAMES
	move.l	frame_counter,d0
	cmp.l	#FRAMES,d0
	blt.s	.go_on
	st	quit_flag
.go_on:
	endc
	movem.l	(sp)+,d0-d1/a0
	rte

; ------------------------------------------------------------------------------
; The hooks of the translated code (d7.w = the Z80 pc, the resume address on the stack): every register is the Z80
; program's.  current: 0 the main CPU, 1 the sub CPU, 2 the sound CPU.
; ------------------------------------------------------------------------------

z80_hook:
	tst.b	current
	bne	hook_other

	; the main CPU: $044C waits for the flag $8000, $02AD / $0310 for $8018 bit 7 (the 06XX's first read)

	cmp.w	#$044C,d7
	bne.s	.spin
	tst.b	-$8000(a6)
	bne.s	.go			; (the flag is set: the loop falls through)
	bra	frame_stop
.spin:	btst	#7,-$7FE8(a6)
	bne.s	.go
	bra	frame_stop
.go:	rts

hook_other:
	cmp.b	#1,current
	bne	hook3

	; the sub CPU: $04DA reads the background pattern ROM logic's BB0 / BB1 (cells F000 / F001 hold the BS latches it
	; wrote); $0356 waits for the flag $8002

	cmp.w	#$04DA,d7
	beq	bb_read
	tst.b	g_ram+2
	bne.s	.go
	bra	turn_end
.go:	rts

hook3:	bra	turn_end		; the sound CPU: $0098, its idle loop

; The frame: the main CPU stopped at its idle loop (or a spin loop).

frame_stop:
	movem.l	d0-d7/a0-a6,-(sp)
	chk_sp	10
	bsr	turn2			; the sub CPU's foreground
	bsr	turn3			; the sound CPU's boot
	bsr	n51_frame_tick		; the 51XX's frame: TC high, then low
	bsr	irq_handlers
	bsr	g_sound_frame
	bsr	picture
	movem.l	(sp)+,d0-d7/a0-a6
	rts

; The IRQ handlers with the CPUs' registers: the main CPU's (registers as the foreground left them: on the stack), the
; sub CPU's (its context).

irq_handlers:
	tst.b	latch
	beq.s	.no_irq1
	tst.b	g1_iff			; the program's ei / di
	beq.s	.no_irq1
	clr.b	g1_iff			; (the handler's ei sets it again)
	movem.l	4(sp),d0-d7/a0-a6
	move.w	#TOKEN,-(a5)
	move.l	#.after_irq1,g1_ret_to
	jmp	Z0038
.after_irq1:
.no_irq1:
	tst.b	latch+1
	beq.s	.no_irq2
	tst.b	latch+3
	beq.s	.no_irq2
	tst.b	g2_iff
	beq.s	.no_irq2
	clr.b	g2_iff
	bsr	sync_to_sub
	movem.l	ctx2,d0-d7/a0-a6
	move.w	#TOKEN,-(a5)
	move.l	#.after_irq2,g2_ret_to
	jmp	Y0038
.after_irq2:
	movem.l	d0-d7/a0-a6,ctx2
	bsr	sync_to_main
.no_irq2:
	rts

g1_ret:
	move.l	g1_ret_to,-(sp)
	rts

g2_ret:
	move.l	g2_ret_to,-(sp)
	rts

g3_ret:
	move.l	g3_ret_to,-(sp)
	rts

; ------------------------------------------------------------------------------
; Turns of the other CPUs: from the main CPU's stop to their own (idle loop; the hook ends the turn).  Every register
; of the stopped CPU is on the stack.
; ------------------------------------------------------------------------------

turn2:
	tst.b	latch+3
	beq.s	.r
	movem.l	d0-d7/a0-a6,-(sp)
	move.l	sp,turn_sp
	bsr	sync_to_sub
	move.b	#1,current
	movem.l	ctx2,d0-d7/a0-a6
	move.l	ctx2+4*15,-(sp)
	rts				; into the sub CPU's code; turn_end brings us back
.r:	rts

turn3:
	tst.b	latch+3
	beq.s	.r
	tst.b	booted3
	bne.s	.r
	movem.l	d0-d7/a0-a6,-(sp)
	move.l	sp,turn_sp
	bsr	g_sound_in
	move.b	#2,current
	movem.l	ctx3,d0-d7/a0-a6
	move.l	ctx3+4*15,-(sp)
	rts
.r:	rts

turn_end:				; (from z80_hook; the resume address is on the stack)
	cmp.b	#2,current
	beq.s	.t3
	movem.l	d0-d7/a0-a6,ctx2
	move.l	(sp)+,ctx2+4*15
	st	booted2
	move.l	turn_sp,sp
	bsr	sync_to_main
	bra.s	.back
.t3:	movem.l	d0-d7/a0-a6,ctx3
	move.l	(sp)+,ctx3+4*15
	st	booted3
	move.l	turn_sp,sp
	bsr	g_sound_out
.back:	movem.l	(sp)+,d0-d7/a0-a6
	clr.b	current
	rts

; The shared work RAM $7900-$7FFF between the two halves.

sync_to_sub:
	lea	G_ROM1+SHARE_LO,a0
	lea	G_IO2+SHARE_LO,a1
	bra.s	sync_copy
sync_to_main:
	lea	G_IO2+SHARE_LO,a0
	lea	G_ROM1+SHARE_LO,a1
sync_copy:
	movem.l	d0-d7/a2-a4,-(sp)
	moveq	#(SHARE_HI-SHARE_LO)/40-1,d0
.l:	movem.l	(a0)+,d1-d7/a2-a4
	movem.l	d1-d7/a2-a4,(a1)
	lea	40(a1),a1
	dbf	d0,.l
	rept ((SHARE_HI-SHARE_LO)-((SHARE_HI-SHARE_LO)/40)*40)/4
	move.l	(a0)+,(a1)+
	endr
	movem.l	(sp)+,d0-d7/a2-a4
	rts

; The sound CPU's NMIs (twice a frame, lines 64 and 192) once it has booted, while its NMION ($6822) is off.  The shared
; bytes it uses are copied in before and out afterwards: its command area $A000-$A0FF and its stack words $A2F0-$A2FF
; (the main CPU writes the commands), the byte $8028 it reads, the byte $8571 it writes.  Clobbers every register.

g_sound_in:
	lea	g_ram+$2000,a0
	lea	g3_ram+$2000,a1
	movem.l	(a0)+,d0-d7/a2-a5		; 48 bytes a time: 256 = 5 x 48 + 16
	movem.l	d0-d7/a2-a5,(a1)
	lea	48(a1),a1
	movem.l	(a0)+,d0-d7/a2-a5
	movem.l	d0-d7/a2-a5,(a1)
	lea	48(a1),a1
	movem.l	(a0)+,d0-d7/a2-a5
	movem.l	d0-d7/a2-a5,(a1)
	lea	48(a1),a1
	movem.l	(a0)+,d0-d7/a2-a5
	movem.l	d0-d7/a2-a5,(a1)
	lea	48(a1),a1
	movem.l	(a0)+,d0-d7/a2-a5
	movem.l	d0-d7/a2-a5,(a1)
	lea	48(a1),a1
	movem.l	(a0)+,d0-d3
	movem.l	d0-d3,(a1)
	movem.l	g_ram+$22F0,d0-d3
	movem.l	d0-d3,g3_ram+$22F0
	move.b	g_ram+$0028,g3_ram+$0028
	rts

g_sound_out:
	lea	g3_ram+$2000,a0
	lea	g_ram+$2000,a1
	movem.l	(a0)+,d0-d7/a2-a5
	movem.l	d0-d7/a2-a5,(a1)
	lea	48(a1),a1
	movem.l	(a0)+,d0-d7/a2-a5
	movem.l	d0-d7/a2-a5,(a1)
	lea	48(a1),a1
	movem.l	(a0)+,d0-d7/a2-a5
	movem.l	d0-d7/a2-a5,(a1)
	lea	48(a1),a1
	movem.l	(a0)+,d0-d7/a2-a5
	movem.l	d0-d7/a2-a5,(a1)
	lea	48(a1),a1
	movem.l	(a0)+,d0-d7/a2-a5
	movem.l	d0-d7/a2-a5,(a1)
	lea	48(a1),a1
	movem.l	(a0)+,d0-d3
	movem.l	d0-d3,(a1)
	movem.l	g3_ram+$22F0,d0-d3
	movem.l	d0-d3,g_ram+$22F0
	move.b	g3_ram+$0571,g_ram+$0571
	rts

g_sound_frame:
	tst.b	booted3
	beq.s	.none
	bsr	g_sound_in
	move.b	#2,nmi3_left
.nmi3:	tst.b	latch+2			; NMION: the NMI is on while the latch is 0
	bne.s	.nmi3_done
	movem.l	ctx3,d0-d7/a0-a6
	move.w	#TOKEN,-(a5)
	move.l	#.after,g3_ret_to
	jmp	X0066
.after:	movem.l	d0-d7/a0-a6,ctx3
	subq.b	#1,nmi3_left
	bne.s	.nmi3
.nmi3_done:
	bsr	g_sound_out
.none:	bra	snd_update

; ------------------------------------------------------------------------------
; Sound: filled in with the sound driver (the WSG as the YM2149's square waves); the frame's hooks are here
; ------------------------------------------------------------------------------

snd_init:
snd_off:
snd_update:
	rts

; ------------------------------------------------------------------------------
; The sub CPU's background pattern ROM read (MAME's xevious_bb_r): the BS latches it wrote at F000 / F001 select the
; bytes BB0 / BB1 it reads next, which replace the cells.  gfx4 = xvi_9.2a (4K at +0), xvi_10.2b (8K at +$1000),
; xvi_11.2c (4K at +$3000): bb_rom.
; ------------------------------------------------------------------------------

bb_read:
	movem.l	d0-d4/a0,-(sp)
	moveq	#0,d0
	move.b	g_ram+$7001,d0		; BS1
	moveq	#0,d1
	move.b	g_ram+$7000,d1		; BS0
	move.w	d0,d2
	and.w	#$7e,d2
	lsl.w	#6,d2
	move.w	d1,d3
	and.w	#$fe,d3
	lsr.w	#1,d3
	or.w	d3,d2			; adr_2b
	moveq	#0,d3
	lea	bb_rom+$1000,a0
	move.b	(a0,d2.w),d3		; rom2b[adr_2b]
	move.w	d2,d4
	lsr.w	#1,d4
	lea	bb_rom,a0
	move.b	(a0,d4.w),d4		; rom2a[adr_2b >> 1]
	and.w	#$ff,d4
	btst	#0,d2
	beq.s	.lo
	and.w	#$f0,d4			; odd: the high nibble
	lsl.w	#4,d4
	bra.s	.c
.lo:	and.w	#$0f,d4			; even: the low nibble
	lsl.w	#8,d4
.c:	or.w	d3,d4			; dat1
	move.w	d4,d2
	and.w	#$1ff,d2
	lsl.w	#2,d2
	and.w	#1,d0
	add.w	d0,d0
	or.w	d0,d2
	and.w	#1,d1
	or.w	d1,d2			; adr_2c
	btst	#10,d4
	beq.s	.n1
	eor.w	#1,d2
.n1:	btst	#9,d4
	beq.s	.n2
	eor.w	#2,d2
.n2:	lea	bb_rom+$3800,a0
	move.b	(a0,d2.w),g_ram+$7001	; BB1 = rom2c[adr_2c | $800]
	moveq	#0,d3
	lea	bb_rom+$3000,a0
	move.b	(a0,d2.w),d3		; BB0: bits 6 and 7 swapped, flipped by dat1 bits 10 and 9
	move.b	d3,d1
	and.b	#$3f,d3
	btst	#6,d1
	beq.s	.b6
	or.b	#$80,d3
.b6:	btst	#7,d1
	beq.s	.b7
	or.b	#$40,d3
.b7:	btst	#10,d4
	beq.s	.f1
	eor.b	#$40,d3
.f1:	btst	#9,d4
	beq.s	.f2
	eor.b	#$80,d3
.f2:	move.b	d3,g_ram+$7000
	movem.l	(sp)+,d0-d4/a0
	rts

; ------------------------------------------------------------------------------
; The latches: a write to $6820-$6827 (any CPU) from the translated code (g_latchw: d7.w = the address, d0.b = the value)
; and to the scroll latch $D000-$D07F (g_vhlatch).  Both keep the CCR (the code saves it).
; ------------------------------------------------------------------------------

g_latchw:
	movem.l	d0-d2/a0,-(sp)
	and.w	#7,d7
	moveq	#1,d1
	and.b	d0,d1
	lea	latch,a0
	move.b	d1,(a0,d7.w)
	cmp.w	#3,d7
	bne.s	.r
	tst.b	d1			; the reset line of the sub CPU, the sound CPU and the custom chips
	bne.s	.release
	st	n51_held
	st	n50_held
	clr.b	chips_on
	bra.s	.r
.release:
	tst.b	chips_on
	bne.s	.r
	st	chips_on
	clr.b	n50_held
	bsr	ctx_reset		; (the CPUs start from their reset vectors)
	move.b	#1,latch+3
	bsr	n51_check
.r:	movem.l	(sp)+,d0-d2/a0
	rts

; (d7.w = the address, d0.b = the value): scroll x of the background ($D000 + 16 * 0 ...): the registers 0-3 and the
; flip register 7; bit 8 of the value is the address bit 0.

g_vhlatch:
	movem.l	d1-d2/a0,-(sp)
	move.w	d7,d1
	lsr.w	#4,d1
	and.w	#15,d1			; the register
	moveq	#0,d2
	move.b	d0,d2
	btst	#0,d7
	beq.s	.v
	or.w	#$100,d2
.v:	cmp.w	#3,d1
	bhi.s	.flip
	add.w	d1,d1
	lea	scroll,a0
	move.w	d2,(a0,d1.w)
	bra.s	.r
.flip:	cmp.w	#7,d1
	bne.s	.r
	and.w	#1,d2
	move.w	d2,flip
.r:	movem.l	(sp)+,d1-d2/a0
	rts

; ------------------------------------------------------------------------------
; 06XX: transfers between the main CPU and the custom chips.  The program writes the control register ($7100, hooked after
; `ld ($7100),a`): bit 4 read/write, bits 0-3 the chips (0: 51XX, 2: 50XX, 3: 54XX), bits 5-7 the clock, which pulses an
; NMI per byte; the NMI handler moves a byte between $7000 and memory with `ldi` and stops the transfer with control
; = $10 when done (after taking the next queued transfer).  Here the handler runs right away, as often as the program
; keeps the clock going (tools/machine.py ctrl06_port): the R/W line and the chip select, the NMI handler (a read's
; first pulse is suppressed: the chips put out their bytes first), the chips after the handler's access, the chip select
; off.  The handler's stop comes back here nested and only sets the register.  A VBL during a transfer cannot start
; the 51XX's frame: the frame happens at the main CPU's stops only.
; ------------------------------------------------------------------------------

g_ctrl06:
	tst.b	n51_busy
	bne	.nested
	move.l	g1_ret_to,-(sp)		; (the IRQ handler we may be in returns through it)
	st	n51_busy
	bsr	n51_check
	st	n51_first
	clr.b	n51_newread
.loop:
	move.b	G_IO1+$7100,d7
	move.b	d7,ctrl06_mode
	and.b	#$e0,d7
	beq	.done
	move.b	ctrl06_mode,d7		; the falling edge: R/W, the chip selects
	lsr.b	#4,d7
	and.b	#1,d7
	move.b	d7,N51_state+N51_S_RW
	move.b	ctrl06_mode,d7
	and.b	#1,d7
	bsr	N51_set_irq
	btst	#4,ctrl06_mode
	beq	.nmi			; write
	tst.b	n51_first
	beq.s	.byte
	btst	#2,ctrl06_mode
	beq.s	.f51
	bsr	n50_pulse		; (the 50XX puts out its first byte)
.f51:	bsr	n51_run			; a read's first pulse: no NMI
	bra	.rise
.byte:	moveq	#-1,d7			; the byte the handler reads: the chips' latches ANDed
	btst	#0,ctrl06_mode
	beq.s	.no51r
	and.b	N51_state+N51_S_PORTO,d7
.no51r:	btst	#2,ctrl06_mode
	beq.s	.ff
	and.b	n50_out,d7
.ff:	rept	16			; the port is the whole $7000-$70FF range: the handler's pointer walks through it
	move.b	d7,G_IO1+$7000+REPTN
	endr
.nmi:
	move.b	g1_iff,-(sp)		; an NMI disables the interrupts until its retn
	clr.b	g1_iff
	move.w	#TOKEN,-(a5)
	move.l	#.back,g1_ret_to
	jmp	Z0066
.back:
	move.b	(sp)+,g1_iff
	btst	#4,ctrl06_mode
	bne.s	.after
	move.b	n06_last,d7		; the byte the handler's `ldi` ($0067) wrote to the port (the handler goes on to the next
					; queued transfer and reloads its pointers, so de' is no longer the port's)
	btst	#0,ctrl06_mode
	beq.s	.no51
	move.b	d7,N51_state+N51_S_PORTO
.no51:	btst	#2,ctrl06_mode
	beq.s	.no50
	bsr	n50_write
.no50:	btst	#3,ctrl06_mode
	beq.s	.after
	bsr	n54_write
.after:	btst	#4,ctrl06_mode		; a read: the 50XX's next byte
	beq.s	.run51
	btst	#2,ctrl06_mode
	beq.s	.run51
	bsr	n50_pulse
.run51:	bsr	n51_run			; the 51XX takes this pulse
.rise:	moveq	#0,d7			; the chip select off
	bsr	N51_set_irq
	bsr	n51_run_low
	move.b	n51_newread,n51_first	; (a control write that starts a read, from inside the handler: the first pulse is
	clr.b	n51_newread		; suppressed again, MAME's read_stretch)
	bra	.loop
.done:
	moveq	#0,d7
	bsr	N51_set_irq
	bsr	n51_run_low
	clr.b	n51_busy
	move.l	(sp)+,g1_ret_to
	rts
.nested:
	move.b	G_IO1+$7100,d7		; (a control write from inside the handler: only the register, and a read starts
	move.b	d7,-(sp)		; the next transfer with a suppressed first pulse)
	and.b	#$e0,d7
	beq.s	.n_r
	btst	#4,(sp)
	beq.s	.n_r
	st	n51_newread
.n_r:	addq.l	#2,sp
	rts

; A plain data write ($7000, hooked): into the chips' latches if the transfer is a write.

g_data06:
	move.b	G_IO1+$7100,d7
	btst	#4,d7
	bne.s	.done
	btst	#0,d7
	beq.s	.no51
	move.b	G_IO1+$7000,N51_state+N51_S_PORTO
.no51:	btst	#2,d7
	beq.s	.no50
	movem.l	d7,-(sp)
	move.b	G_IO1+$7000,d7
	bsr	n50_write
	movem.l	(sp)+,d7
.no50:	btst	#3,d7
	beq.s	.done
	move.b	G_IO1+$7000,d7
	bra	n54_write
.done:
	rts

; ------------------------------------------------------------------------------
; 51XX: the chip's own program, translated (engine/mb88x.py -> build/xevious/n51_code.s): it runs from wait point to wait
; point at its events, as tools/machine.py's event-driven model.  Every routine keeps every register.
; The reset line is latch $6823 (0: held); a release resets the chip and runs its boot to the main loop.
; ------------------------------------------------------------------------------

n51_check:
	tst.b	latch+3
	bne.s	.on
	st	n51_held
	rts
.on:	tst.b	n51_held
	beq.s	.r
	clr.b	n51_held
	bsr	N51_reset
	bsr	N51_run
.r:	rts

n51_run:
	tst.b	n51_held
	bne.s	.r
	bra	N51_run
.r:	rts

; After the chip select went low: only the coinage command's wait for that ($00D) goes on; anywhere else the chip would
; stop again at once.

n51_run_low:
	cmp.l	#N51_00D,N51_state+N51_S_RESUME
	beq.s	n51_run
	rts

; The frame's tick: the TC pin goes high and low (the vertical blank counts), the frame body runs with this frame's
; inputs.

n51_frame_tick:
	movem.l	d6-d7,-(sp)
	bsr	n51_check
	move.b	in0_kbd,d7		; the inputs, active low as the arcade's: R0 / R1 IN0 low / high (joysticks),
	or.b	in0_joy,d7		; R2 / R3 IN1 low / high (fire, starts, coins, service)
	or.b	jp_in,d7
	not.b	d7
	move.b	d7,d6
	and.b	#$0f,d6
	move.b	d6,N51_state+N51_S_R
	lsr.b	#4,d7
	move.b	d7,N51_state+N51_S_R+1
	move.b	in1_kbd,d7
	or.b	in1_joy,d7
	or.b	jp_in+1,d7
	not.b	d7
	move.b	d7,d6
	and.b	#$0f,d6
	move.b	d6,N51_state+N51_S_R+2
	lsr.b	#4,d7
	move.b	d7,N51_state+N51_S_R+3
	move.b	in2_kbd,d7		; the second button reads through the DIP switch bank: bit 0 of $6800 (DSWB bit 0)
	or.b	jp_in+2,d7
	and.b	#1,d7
	eor.b	#1,d7
	move.b	G_IO1+$6800,d6
	and.b	#$fe,d6
	or.b	d7,d6
	move.b	d6,G_IO1+$6800
	move.b	d6,G_IO2+$6800
	move.b	d6,g3_block+$6800
	moveq	#1,d7			; (the rising edge counts nothing: no run)
	bsr	N51_set_tc
	moveq	#0,d7
	bsr	N51_set_tc
	bsr	n51_run
	movem.l	(sp)+,d6-d7
	rts

	include	"n51_code.s"

; ------------------------------------------------------------------------------
; 50XX: a simulation of its score keeper at the register interface, for the commands Xevious sends (the start-up
; protection check): $1x reset the scores, $8x - $Fx add an amount, four reads give the flags and the score (tools/n50.py is the same in
; Python; tools/n50_test.py compares it with the chip's own program).  The 54XX (the noise): the commands are only
; counted.
; ------------------------------------------------------------------------------

n50_init:
	clr.l	n50_score
	clr.b	n50_held
	st	n50_out
	clr.b	n50_idx
	rts

; d7.b = the byte written; keeps every register

n50_write:
	movem.l	d0-d2/a0,-(sp)
	moveq	#0,d0
	move.b	d7,d0
	move.b	d0,d1
	lsr.b	#4,d1			; the command's high nibble
	cmp.b	#1,d1
	bne.s	.inc
	clr.l	n50_score
	bra.s	.read
.inc:	cmp.b	#8,d1
	blo.s	.read
	moveq	#15,d2
	and.w	d0,d2			; the amount's index
	add.w	d2,d2
	moveq	#0,d0
	cmp.b	#$b,d1
	blo.s	.small			; 8x 9x Ax: 5 10 15 ..., x1, x10, x100
	cmp.b	#$e,d1
	bhs.s	.big
	lea	n50_b,a0		; Bx Cx Dx: 10 20 30 ..., x1, x10, x100
	move.w	(a0,d2.w),d0
	sub.b	#$b,d1
	bra.s	.scale
.big:	lea	n50_e,a0		; Ex Fx: 15 30 45 ...
	move.w	(a0,d2.w),d0
	sub.b	#$e,d1
	bra.s	.scale
.small:	lea	n50_a,a0
	move.w	(a0,d2.w),d0
	sub.b	#8,d1
.scale:	tst.b	d1
	beq.s	.add
.mul:	mulu	#10,d0
	subq.b	#1,d1
	bne.s	.mul
.add:	add.l	d0,n50_score
	cmp.l	#10000000,n50_score
	blo.s	.read
	sub.l	#10000000,n50_score
.read:	move.l	n50_score,d0		; the answer: flags (80 high score, 40 first bonus, 20 interval bonus, 10 ?) and the
	moveq	#0,d1			; seven BCD digits: byte 0 = flags + the first digit, then three bytes of two digits
	moveq	#6,d2
.dig:	divu	#10,d0
	swap	d0
	move.b	d0,-(sp)		; the digit
	clr.w	d0
	swap	d0
	dbf	d2,.dig
	lea	n50_buf,a0
	move.b	(sp)+,d1
	tst.l	n50_score
	beq.s	.noflags
	or.b	#$f0,d1
.noflags:
	move.b	d1,(a0)+
	moveq	#2,d2
.pairs:	move.b	(sp)+,d1
	lsl.b	#4,d1
	or.b	(sp)+,d1
	move.b	d1,(a0)+
	dbf	d2,.pairs
	clr.b	n50_idx
	movem.l	(sp)+,d0-d2/a0
	rts

; One chip pulse of a read: the next byte of the answer (after the four, $FF).

n50_pulse:
	movem.l	d0/a0,-(sp)
	moveq	#0,d0
	move.b	n50_idx,d0
	cmp.b	#4,d0
	bhs.s	.ff
	lea	n50_buf,a0
	move.b	(a0,d0.w),n50_out
	addq.b	#1,n50_idx
	bra.s	.r
.ff:	move.b	#$ff,n50_out
.r:	movem.l	(sp)+,d0/a0
	rts

n50_a:	dc.w	5,10,15,20,25,30,40,50,60,70,80,90,100,200,300,500
n50_b:	dc.w	10,20,30,40,50,60,80,100,120,140,160,180,200,400,600,1000
n50_e:	dc.w	15,30,45,60,75,90,120,150,180,210,240,270,300,600,900,1500

n54_write:
	addq.w	#1,n54_count
	rts

; ------------------------------------------------------------------------------
; Halt and the refresh register (`ld a,r`: a pseudo random byte, the reference uses the same generator).

z80_halt:
	move.l	frame_counter,d7
.wait:	cmp.l	frame_counter,d7
	beq.s	.wait
	rts

z80_rnd:
	move.w	rnd_state,d7
	lsr.w	#1,d7
	bcc.s	.no
	eor.w	#$B400,d7
.no:	move.w	d7,rnd_state
	move.b	d7,d0
	rts

; ------------------------------------------------------------------------------
; The picture of the frame and the wait for the next arcade frame
; ------------------------------------------------------------------------------

picture:
	ifd SIM
	bsr	sim_render_start
	endc
	bsr	render_frame
	ifd SIM
	bsr	sim_frame_done
	endc
.wait:	tst.b	vbl_pending
	bne.s	.go
	ifd SIM
	bsr	sim_wait
	endc
	bra.s	.wait
.go:	subq.b	#1,vbl_pending
	rts

	ifd SIM
sim_wait:				; the test harness stops here when the frame waits with nothing pending: it sets
	bra.s	sim_wait		; vbl_pending (and the inputs) and returns (rts) from here
sim_render_start:			; (render_test.py measures from here)
	bra.s	sim_render_start
sim_frame_done:				; the harness compares here (the frame's work is done), returns with rts
	bra.s	sim_frame_done
sim_render_ret:				; render_test.py calls render_frame with this as the return address
	bra.s	sim_render_ret
	endc

; ------------------------------------------------------------------------------
; Keyboard / joystick (IKBD): the pressed bits of in0 (joystick), in1 (buttons), in2 (the bomb)
; ------------------------------------------------------------------------------

	jagpad_text
	jagpad_maps

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
	or.b	d0,in0_kbd
	move.b	2(a0),d0
	or.b	d0,in1_kbd
	move.b	3(a0),d0
	or.b	d0,in2_kbd
	bra	.again

.release:
	move.b	1(a0),d0
	not.b	d0
	and.b	d0,in0_kbd
	move.b	2(a0),d0
	not.b	d0
	and.b	d0,in1_kbd
	move.b	3(a0),d0
	not.b	d0
	and.b	d0,in2_kbd
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
	move.b	joy0_state,d1
	or.b	joy1_state,d1
	moveq	#0,d0
	btst	#0,d1			; up
	beq	.j0
	bset	#0,d0
.j0:	btst	#1,d1			; down
	beq	.j1
	bset	#2,d0
.j1:	btst	#2,d1			; left
	beq	.j2
	bset	#3,d0
.j2:	btst	#3,d1			; right
	beq	.j3
	bset	#1,d0
.j3:	move.b	d0,in0_joy
	moveq	#0,d0
	tst.b	d1			; fire
	bpl	.j4
	bset	#0,d0
.j4:	move.b	d0,in1_joy
	bra	.again

.done:
	movem.l	(sp)+,d0-d2/a0
	rte

; scancode, in0 bits, in1 bits, in2 bits

key_table:
	dc.b	$48,$01,$00,$00		; up
	dc.b	$4d,$02,$00,$00		; right
	dc.b	$50,$04,$00,$00		; down
	dc.b	$4b,$08,$00,$00		; left
	dc.b	$39,$00,$01,$00		; space = fire
	dc.b	$1d,$00,$01,$00		; control = fire
	dc.b	$38,$00,$00,$01		; alternate = bomb
	dc.b	$02,$00,$04,$00		; 1 = start 1
	dc.b	$03,$00,$08,$00		; 2 = start 2
	dc.b	$06,$00,$10,$00		; 5 = coin
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

; A Z80 pc without translated code (the dispatch table's default): CRASH.TXT with vector 98, d7 = the byte swapped pc
; times 4, a4 = the dispatch table of the CPU (g1/g2/g3_dispatch_sw), the stack words the Z80's (a5, return addresses
; byte swapped).
z80_badpc:
z80_badjump:
z80_unsupported:
	move	#$2700,sr
	moveq	#98,d0
	move.l	a5,sp
	bra	crash_common

; the scan of the tile RAM writes (generated code marks blocks): vblock_range marks the blocks from the DE before (vblock_de)
; to the DE after of a block instruction; vblocks / vblock_all are bss

vblock_range:
	move	sr,-(sp)
	movem.l	d0-d1/a0,-(sp)
	move	vblock_de,d0
	move	d2,d1
	cmp	d0,d1
	bhs.s	.up
	exg	d0,d1
.up:	lsr	#5,d0
	lsr	#5,d1
	sub	d0,d1			; blocks - 1
	cmp	#255,d1
	bls.s	.mark
	st	vblock_all
	bra.s	.done
.mark:	lea	vblocks,a0
.m:	and	#255,d0
	st	(a0,d0.w)
	addq	#1,d0
	dbf	d1,.m
.done:	movem.l	(sp)+,d0-d1/a0
	move	(sp)+,ccr
	rts

	include "render.s"

; ------------------------------------------------------------------------------
; The translated programs (and their dispatch tables in the data section).

	include "xevious_code.s"

	section text,code
	include "rtlib.s"

; ------------------------------------------------------------------------------
	section data,data
; ------------------------------------------------------------------------------

rom_table:				; source, destination, bytes
	dc.l	rom_cpu1,G_ROM1,$4000
	dc.l	rom_cpu2,g_block,$2000
	dc.l	rom_cpu3,g3_rom,$1000
	dc.l	0
rom_cpu1:	incbin	"rom_cpu1.rom"
rom_cpu2:	incbin	"rom_cpu2.rom"
rom_cpu3:	incbin	"rom_cpu3.rom"
bb_rom:		incbin	"rom_bb.rom"
	even

	include "xevious_assets.s"

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

quit_flag:	ds.b	1
	jagpad_vars
frame_ready:	ds.b	1		; the draw screen is complete, to be shown at the VBL
vbl_pending:	ds.b	1		; arcade frames that may run
	borders_vars
in0_kbd:	ds.b	1
in0_joy:	ds.b	1
in1_kbd:	ds.b	1
in1_joy:	ds.b	1
in2_kbd:	ds.b	1
	ikbd_vars
joy0_state:	ds.b	1
joy1_state:	ds.b	1
current:	ds.b	1		; 0: the main CPU's code runs, 1: the sub CPU's, 2: the sound CPU's
booted2:	ds.b	1		; the sub CPU reached its idle loop
booted3:	ds.b	1		; the sound CPU reached its idle loop
ctrl06_mode:	ds.b	1
n06_last:	ds.b	1		; the byte the 06XX handler's last ldi wrote
g1_iff:		ds.b	1		; the CPUs' interrupt enable (ei / di)
g2_iff:		ds.b	1
latch:		ds.b	8		; $6820-$6827 (IRQ1, IRQ2, NMI3 off, the reset line, ...)
chips_on:	ds.b	1		; the reset line was released
nmi3_left:	ds.b	1
n51_held:	ds.b	1		; the 51XX is in reset (latch $6823 is 0)
n51_busy:	ds.b	1		; a transfer runs (g_ctrl06)
n51_first:	ds.b	1		; its first pulse
n51_newread:	ds.b	1		; the handler started a read (the next pass's first pulse is suppressed)
n50_held:	ds.b	1
n50_out:	ds.b	1		; the 50XX's output latch
n50_idx:	ds.b	1
n50_buf:	ds.b	4
	even
n54_count:	ds.w	1
scroll:		ds.w	4		; the scroll latches: background x, foreground x, background y, foreground y
flip:		ds.w	1
vblock_de:	ds.w	1
vblock_all:	ds.b	1
	even
vblocks:	ds.b	256		; the 32-byte blocks of the tile RAM ($B000-$CFFF) written since the renderer looked
n50_score:	ds.l	1
	include	"n51_bss.s"
	even

frame_counter:	ds.l	1
vbl_sp:		ds.l	1
cnt_acia:	ds.w	1
crash_vector:	ds.w	1
crash_sp:	ds.l	1
crash_regs:	ds.l	16
crash_text:	ds.b	512
draw_index:	ds.w	1
bg_address:	ds.l	1
scr_address:	ds.l	2
draw_screen_address:	ds.l	1
display_screen_address:	ds.l	1

g1_ret_to:	ds.l	1
g2_ret_to:	ds.l	1
g3_ret_to:	ds.l	1
turn_sp:	ds.l	1
rnd_state:	ds.l	1
ctx2:		ds.l	16		; d0-d7, a0-a6, resume address
ctx3:		ds.l	16		; the sound CPU's registers

	cnop 0,4
g_block:	ds.b	$18000		; [sub ROM 32K | RAM 32K | main ROM 32K]
g_ram = g_block+$8000
g3_block:	ds.b	$10000		; the sound CPU: its ROM, its I/O cells (the WSG at $6800), its RAM at + $8000
g3_rom = g3_block
g3_ram = g3_block+$8000
g3_dispatch_sw:	ds.l	65536
g1_dispatch_sw:	ds.l	65536
g2_dispatch_sw:	ds.l	65536

	ds.b	4096
own_stack_top:

	cnop 0,4
screens:
	ds.b	$10000			; alignment slack
	ds.b	SCREEN_BYTES
