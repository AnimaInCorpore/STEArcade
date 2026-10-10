; ------------------------------------------------------------------------------
;
; Bubble Bobble for the Atari STE
;
; The arcade's main and sub Z80 programs and the protection MCU's firmware are
; translated to 68000 code (tools/gen.py: engine/z80x.py, engine/m6801x.py); this file is the
; machine around them: STE video, the tile renderer (render.s), input, and the
; schedule:
;
;   At every VBL the MCU's IRQ1 handler runs (it reads the inputs and the DIP switches,
;   moves bytes to and from the shared RAM and raises the main CPU's interrupt through
;   its port 1), then the main CPU's interrupt handler (IM 2, the vector byte is in the
;   shared RAM at $FC00) and the sub CPU's (IM 1), each to completion, then the frame is
;   drawn.  The CPUs' foreground threads only boot to their idle loops (the main CPU's
;   boot waits for the MCU's handshake at $0158: the hook gives the MCU and the sub CPU a
;   turn).  There is no sound CPU (its commands go nowhere).
;
; Memory: one block holds [sub ROM 32K | shared RAM 32K ($8000-$FFFF) | main ROM 32K];
; the main CPU's code addresses with a6 = its ROM and signed word offsets (the RAM lies
; below), the sub CPU's with a6 = its ROM and long offsets (the RAM above).  The window
; $8000-$BFFF of the main CPU shows one of four 16 KB ROM banks: g_winbase = the current
; one's copy + $8000 (g_win + $4000 * bank + $8000), a4 = the current bank's dispatch table.
; (a0-a3 hold A' BC' DE' HL' for the translated code: nothing is left for the window.)
;
; The CPU ROMs a78-06-1.51 a78-05-1.52 a78-08.37 a78-01.17 are embedded, the boot tests patched (rom_table).
;
; ------------------------------------------------------------------------------

BUSY = %10000000
HOG = %01000000
NFSR = %01000000

STRIDE = 160				; bytes per line
KEY_ESC = $01

	ifnd TA_DATA
TA_DATA = 98
	endc
	ifnd TA_NOPS
TA_NOPS = 84
	endc
	ifnd FRAMES
FRAMES = 0
	endc

; the pads (engine/rt/jagpad.s): IN0, P1, P2 bits as in key_table (bytes 0-2 of each long)
JP1_LEFT = $01<<16
JP1_RIGHT = $02<<16
JP1_UP = $10<<16			; (bubble, as the joystick's up)
JP1_DOWN = 0
JP1_B1 = $20<<16			; A: jump, B: bubble
JP1_B2 = $10<<16
JP1_B3 = 0
JP2_LEFT = $01<<8
JP2_RIGHT = $02<<8
JP2_UP = $10<<8
JP2_DOWN = 0
JP2_B1 = $20<<8
JP2_B2 = $10<<8
JP2_B3 = 0
JP_START1 = $40<<16
JP_START2 = $40<<8
JP_COIN1 = $04<<24
JP_COIN2 = $08<<24
	include	"jagpad.s"

; The Z80 address space as 68k addresses (see the header).

G_ROM1 = g_block+$10000			; main CPU: a6
G_ROM2 = g_block			; sub CPU: a6
g_ram = g_block+$8000			; $8000-$FFFF
G_MCRAM = g_ram+$7C00			; $FC00-$FFFF: the RAM shared with the MCU
TOKEN = $FE7F				; $7FFE on the Z80 stack, byte swapped

arm_border_timers	macro
	clr.b	$fffffa1b.w
	move.b	#199+29,$fffffa21.w
	move.b	#8,$fffffa1b.w
	move.b	#TA_DATA,$fffffa1f.w
	move.b	#4,$fffffa19.w
	st	border_a
	st	border_b
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

	bsr	load_roms

	bsr	init_cells
	bsr	init_hardware
	bsr	init_video
	bsr	init_render

	lea	g1_dispatch_sw,a1	; the dispatch tables (fixed code + the bank's window code)
	lea	g1_entries_fixed,a2
	lea	g1_entries_bank0,a3
	bsr	init_table
	lea	g1_dispatch_sw+$40000,a1
	lea	g1_entries_fixed,a2
	lea	g1_entries_bank1,a3
	bsr	init_table
	lea	g1_dispatch_sw+$80000,a1
	lea	g1_entries_fixed,a2
	lea	g1_entries_bank2,a3
	bsr	init_table
	lea	g1_dispatch_sw+$C0000,a1
	lea	g1_entries_fixed,a2
	lea	g1_entries_bank3,a3
	bsr	init_table
	lea	g2_dispatch_sw,a1
	lea	g2_entries,a2
	sub.l	a3,a3
	bsr	init_table

	; the four ROM banks' windows were loaded into g_win (the program reads the window as
	; data), a 5th, empty one for the bank values the board decodes to nothing

	; the MCU's memory: its ROM at $F000

	lea	mcu_rom,a0
	lea	mcu_mem+$F000,a1
	move	#$1000/4-1,d0
.mrom:	move.l	(a0)+,(a1)+
	dbf	d0,.mrom

	; The sub CPU's context: registers 0, at its reset vector.

	lea	ctx2,a0
	moveq	#15,d0
.ctx:	clr.l	(a0)+
	dbf	d0,.ctx
	move.l	#g2_dispatch_sw,ctx2+4*12	; a4
	move.l	#g_block,ctx2+4*14		; a6
	move.l	#Y0000,ctx2+4*15		; resume

	move.w	#$1234,rnd_state
	move.b	#$03,in0_val
	move.b	#$ff,in1_val
	move.b	#$ff,in2_val
	move.b	#$fe,dsw0
	move.b	#$ff,dsw1
	moveq	#0,d0
	bsr	bb_set_bank

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

; ------------------------------------------------------------------------------
; The arcade ROMs are part of the program (incbin, rom_table): copied to where the
; translated code reads them
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

init_cells:
	rts

; The dispatch table (byte swapped pc order, 65536 longs): a1 = the table, a2 / a3 = lists of
; (pc.w, label.l) ending with $FFFF (a3 = 0: none)

init_table:
	move.l	a1,a4
	move.l	#z80_badpc,d1
	move	#65536/8-1,d2
.fill:
	rept 8
	move.l	d1,(a4)+
	endr
	dbf	d2,.fill
	bsr.s	.apply
	move.l	a3,d0
	beq.s	.done
	move.l	a3,a2
.apply:
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
	bsr	restore_hardware
	move.l	old_ssp,-(sp)
	move	#$20,-(sp)
	trap	#1
	addq	#6,sp
	clr	-(sp)
	trap	#1

; ------------------------------------------------------------------------------
; Video
; ------------------------------------------------------------------------------

init_video:
	move.l	#screens,d0
	add.l	#$100-1,d0
	and.l	#$ffffff00,d0
	move.l	d0,scr_address
	add.l	#SCREEN_SIZE,d0
	move.l	d0,scr_address+4

	move.l	scr_address,a0
	bsr	clear_screen
	move.l	scr_address+4,a0
	bsr	clear_screen

	clr.b	$ffff8260.w		; low resolution
	clr.b	$ffff820f.w

	move.l	scr_address+4,draw_screen_address
	move.l	scr_address,display_screen_address
	clr	draw_index
	rts

; a0 = screen

clear_screen:
	move.l	#SCREEN_SIZE/16-1,d0
	moveq	#0,d1
	move.l	d1,d2
	move.l	d1,d3
	move.l	d1,d4
.c:	movem.l	d1-d4,(a0)
	lea	16(a0),a0
	dbf	d0,.c
	rts

; ------------------------------------------------------------------------------
; Interrupts
; ------------------------------------------------------------------------------

hbl:
	rte

; The VBL starts the frame: it switches the screen, runs the MCU, the two CPUs' IRQ
; handlers and draws.  The registers of the interrupted foreground thread are kept on
; the stack and restored at the end.

vbl:
	ifnd NOBORDER
	arm_border_timers		; (first thing: the timers count from here)
	endc
	tst.b	in_logic		; the game's interrupts of the last VBL still run (they are not masked
	bne	vbl_late		; against the VBL): this one only arms the timers, the game runs slower
	st	in_logic
	move.l	2(sp),dbg_vbl_pc
	move.l	sp,dbg_vbl_sp
	addq.w	#1,dbg_nest
	ifd DEBUG
	addq	#1,cnt_vbl
	endc
	movem.l	d0-d7/a0-a6,-(sp)
	bsr	jagpad_poll
	move	sr,-(sp)
	move	#$2600,sr		; (the keyboard composes them too)
	bsr	compose_inputs
	move	(sp)+,sr

	; A frame finished drawing since the last VBL: show it, draw into the other one.

	tst.b	frame_ready
	beq.s	.no_swap
	clr.b	frame_ready
	move.l	display_screen_address,d0
	move.l	draw_screen_address,display_screen_address
	move.l	d0,draw_screen_address
	eori	#1,draw_index
	move.l	display_screen_address,d0
	add.l	#CROP_TOP*STRIDE,d0	; the shown part
	move.l	d0,-(sp)
	move.b	1(sp),$ffff8201.w
	move.b	2(sp),$ffff8203.w
	move.b	3(sp),$ffff820d.w
	addq.l	#4,sp
	tst.b	pal_pending
	beq.s	.no_swap
	clr.b	pal_pending
	movem.l	ste_pal,d0-d7
	movem.l	d0-d7,$ffff8240.w
.no_swap:

	addq.l	#1,frame_counter

	tst.b	quit_flag
	bne	quit

	move	#$2300,sr		; (the VBL itself may interrupt the game's interrupts: see in_logic)

	tst.b	in_turn			; a booting chip's registers are live: no handlers
	bne	vbl_render

	; The game's interrupts cost 0.5-1.1 frames here: while a frame has been drawing for a few VBLs,
	; every other VBL skips them (the game slows down, the picture keeps coming).
	tst.b	in_render
	beq.s	.do_logic
	addq.b	#1,render_age
	cmp.b	#4,render_age
	blo.s	.do_logic
	eori.b	#1,skip_phase
	bne	vbl_render
.do_logic:

	tst.b	booted1			; (the chips' interrupts start once the main CPU idles; nothing is
	beq	vbl_done		; drawn before that: the boot's RAM test only fills the video RAM)
	ifd SIM
	addq.l	#1,sim_game_frames	; (profile.py: game frames run)
	endc
	bsr	mcu_irq			; the MCU first: it raises the main CPU's interrupt

	; Main CPU IRQ (IM 2) with the interrupted registers, if requested and enabled.
	; Its register state afterwards is dropped: the handler restores every Z80
	; register itself.  While the runtime renders (this VBL interrupted the renderer,
	; not the main CPU), the main CPU's registers are in main_ctx.

	tst.b	main_irq
	beq.s	.no_irq1
	tst.b	g1_iff			; the program's ei / di
	beq.s	.no_irq1
	tst.b	booted1
	beq.s	.no_irq1
	clr.b	main_irq
	clr.b	g1_iff			; (the handler's ei sets it again)
	movem.l	(sp),d0-d7/a0-a6
	tst.b	in_render
	beq.s	.regs1
	movem.l	main_ctx,d0-d7/a0-a6
.regs1:
	moveq	#0,d7
	move.b	g1_ireg,d7
	lsl.w	#8,d7
	move.b	G_MCRAM,d7		; the vector byte the MCU left at $FC00
	lea	G_ROM1,a6
	move.w	(a6,d7.w),d7		; the handler's address (byte swapped pc)
	bsr	bb_load_bank		; a2, a4: the current bank's
	move.w	#TOKEN,-(a5)
	move.l	#.after_irq1,g1_ret_to
	and.l	#$ffff,d7
	lsl.l	#2,d7
	move.l	0(a4,d7.l),a3
	jmp	(a3)
.after_irq1:
.no_irq1:

	; Sub CPU IRQ with its own registers, once it has booted and enabled it.

	tst.b	booted2
	beq.s	.no_irq2
	tst.b	g2_iff
	beq.s	.no_irq2
	tst.b	sub_run
	beq.s	.no_irq2
	clr.b	g2_iff
	movem.l	ctx2,d0-d7/a0-a6
	ifd CHKCTX
	cmp.l	#g_block,a6
	beq.s	.c1
	moveq	#31,d0			; the sub CPU's context was damaged before its interrupt
	bra	crash_common
.c1:	cmp.l	#g2_dispatch_sw,a4
	beq.s	.c2
	moveq	#32,d0
	bra	crash_common
.c2:
	endc
	move.w	#TOKEN,-(a5)
	move.l	#.after_irq2,g2_ret_to
	jmp	Y0038
.after_irq2:
	ifd CHKCTX
	cmp.l	#g_block,a6
	beq.s	.c3
	moveq	#33,d0			; ... by its interrupt handler
	bra	crash_common
.c3:
	endc
	movem.l	d0-d7/a0-a6,ctx2
.no_irq2:

	bsr	g_boot_turns		; a booting chip waiting for the main CPU gets on

	ifd SIM
	bsr	sim_frame_done
	endc

vbl_render:
	clr.b	in_logic
	; Draw the frame, with the VBL enabled: when it takes longer than a frame, the
	; next VBL runs the game's interrupts (above) and skips the drawing.
	tst.b	in_render
	bne.s	vbl_done
	tst.b	in_turn
	bne.s	vbl_done
	movem.l	(sp),d0-d7/a0-a6	; the main CPU's registers for its IRQ handler
	movem.l	d0-d7/a0-a6,main_ctx
	st	in_render
	ifd SIM
	addq.l	#1,sim_renders		; (profile.py: renders started)
	endc
	move	#$2300,sr
	bsr	render_frame
	move	#$2400,sr
	clr.b	in_render
	clr.b	render_age
	st	frame_ready

vbl_done:
	clr.b	in_logic
	subq.w	#1,dbg_nest
	if FRAMES
	move.l	frame_counter,d0
	cmp.l	#FRAMES,d0
	blt.s	.go_on
	st	quit_flag
.go_on:
	endc

	movem.l	(sp)+,d0-d7/a0-a6
	rte

vbl_late:
	addq.w	#1,cnt_late
	rte

; The token on a Z80 stack returns here: back to whoever started the handler.

g1_ret:
	move.l	g1_ret_to,-(sp)
	rts

g2_ret:
	move.l	g2_ret_to,-(sp)
	rts

; The top and bottom borders are removed (Timer A in the middle of the last line before the
; border, Timer B at the bottom border), as in the Galaga port: 277 lines.

timer_a:
	move.l	2(sp),dbg_t_pc
	move	#$2100,sr
	stop	#$2100
	move	#$2700,sr
	clr.b	$fffffa19.w
	rept TA_NOPS
	nop
	endr
	clr.b	$ffff820a.w
	rept 9
	nop
	endr
	move.b	#2,$ffff820a.w
	clr.b	border_a
	rte

timer_b:
	movem.l	d0/a0,-(sp)
	lea	$fffffa21.w,a0
	move.b	(a0),d0
.wait1:
	cmp.b	(a0),d0
	beq.s	.wait1
	clr.b	$ffff820a.w
	moveq	#2,d0
.wait2:
	nop
	dbf	d0,.wait2
	nop
	nop
	nop
	nop
	nop
	move.b	#2,$ffff820a.w
	move.b	(a0),d0
.wait3:
	cmp.b	(a0),d0
	beq.s	.wait3
	movem.l	(sp)+,d0/a0
	clr.b	border_b
	rte

; ------------------------------------------------------------------------------
; The boot schedule.  z80_hook is reached from the translated code at the spin loops
; of the boot handshake (d7 = the Z80 pc of the instruction): the main CPU gives the
; MCU and the sub CPU a turn and continues; the sub CPU, running in a turn, hands back
; at its idle loop.
; ------------------------------------------------------------------------------

z80_hook:				; (the hook pushed the address it continues at)
	tst.b	current
	bne.s	.sub_yields

	cmp.w	#$01ED,d7		; the main CPU's idle loop: the boot is done
	bne.s	.handshake
	st	booted1
	rts
.handshake:
	movem.l	d0-d7/a0-a6,-(sp)	; the handshake loop: the others get a turn
	bsr	g_boot_turns
	movem.l	(sp)+,d0-d7/a0-a6
	rts				; to the resume address

.sub_yields:
	movem.l	d0-d7/a0-a6,ctx2
	move.l	(sp)+,ctx2+4*15		; where it continues next time
	st	booted2			; (its only hook: the idle loop)
.back:
	move.l	turn_sp,sp
	movem.l	(sp)+,d0-d7/a0-a6
	clr.b	in_turn			; (after the registers: a VBL in between sees the turn)
	clr.b	current
	rts

; Turns for the chips that are released and still booting.  Keeps every register.

g_boot_turns:
	tst.b	mcu_run
	beq.s	.nomcu
	tst.b	mcu_booted
	bne.s	.nomcu
	bsr	mcu_boot
.nomcu:
	tst.b	sub_run
	beq.s	.none
	bsr.s	g_boot_turn2
.none:
	rts

g_boot_turn2:
	tst.b	booted2
	bne.s	.done
	movem.l	d0-d7/a0-a6,-(sp)
	move.l	sp,turn_sp
	st	in_turn
	move.b	#1,current
	movem.l	ctx2,d0-d7/a0-a6
	move.l	ctx2+4*15,-(sp)
	rts				; into the sub CPU's code; z80_hook brings us back
.done:
	rts

; ------------------------------------------------------------------------------
; The Z80 halt (the main CPU waits for its interrupt = the next VBL; the sub CPU never
; halts) -- not used by this program, but the translator emits the call.

z80_halt:
	move.l	frame_counter,d7
.wait:	cmp.l	frame_counter,d7
	beq.s	.wait
	rts

; `ld a,r` (the refresh register): a pseudo random byte, one generator for both CPUs
; (the reference uses the same)

z80_rnd:
	move.w	rnd_state,d7
	lsr.w	#1,d7
	bcc.s	.no
	eor.w	#$B400,d7
.no:	move.w	d7,rnd_state
	move.b	d7,d0
	rts

; ------------------------------------------------------------------------------
; The bank / reset / video latch ($FB40, hooked after `ld ($FB40),a`; d0 = the byte):
; bits 0-2 the ROM bank (entry (v ^ 4) & 7: 0-3 the four banks, 4-7 nothing), bit 4 releases
; the sub CPU (rising edge: it boots), bit 5 the MCU, bit 6 enables the display, bit 7 flips
; the screen.  Sets g_winbase / a4 / g_bank4 for the main CPU's code.
; ------------------------------------------------------------------------------

bb_bank:
	move.l	d1,-(sp)
	moveq	#0,d1
	move.b	d0,d1
	move.b	g_fb40,d7
	move.b	d1,g_fb40
	; bit 4: the sub CPU
	btst	#4,d1
	beq.s	.sub_off
	btst	#4,d7
	bne.s	.sub_done
	bsr	sub_reset
	bra.s	.sub_done
.sub_off:
	clr.b	sub_run
.sub_done:
	btst	#5,d1
	beq.s	.mcu_off
	btst	#5,d7
	bne.s	.mcu_done
	clr.b	mcu_booted
	st	mcu_run
	bra.s	.mcu_done
.mcu_off:
	clr.b	mcu_run
.mcu_done:
	move.b	d1,d7
	and.b	#$40,d7
	move.b	d7,video_enable
	move.b	d1,d7
	and.b	#$80,d7
	move.b	d7,video_flip
	move.l	(sp)+,d1
	; falls into the bank selection (d0 still the byte)

; d0 = the latch value: a2 / a4 / g_bank4 for its bank

bb_set_bank:
	moveq	#0,d7
	move.b	d0,d7
	eori.b	#4,d7
	and.b	#7,d7
	cmp.b	#4,d7
	blo.s	.ok
	moveq	#4,d7			; nothing there: the empty window; the first table
.ok:
	move.b	d7,g_bank
	move.w	d7,-(sp)
	lsl.w	#2,d7
	and.w	#12,d7			; (the stubs' tables have four entries)
	move.w	d7,g_bank4
	move.w	(sp)+,d7
	bsr.s	bb_load_bank
	rts

; g_winbase, a4 from g_bank (0-3 the ROM banks, 4 the empty window and the first table)

bb_load_bank:
	move.l	d7,-(sp)
	moveq	#0,d7
	move.b	g_bank,d7
	lsl.l	#7,d7
	lsl.l	#7,d7			; * $4000
	add.l	#g_win+$8000,d7
	move.l	d7,g_winbase
	moveq	#0,d7
	move.b	g_bank,d7
	and.b	#3,d7
	swap	d7			; * 65536
	lsl.l	#2,d7			; * 256 KB: a table of 65536 longs
	lea	g1_dispatch_sw,a4
	add.l	d7,a4
	move.l	(sp)+,d7
	rts

; the sub CPU restarts: registers 0, at its reset vector, to boot to its idle loop

sub_reset:
	movem.l	d0-d1/a0,-(sp)
	lea	ctx2,a0
	moveq	#15,d0
.ctx:	clr.l	(a0)+
	dbf	d0,.ctx
	move.l	#g2_dispatch_sw,ctx2+4*12
	move.l	#g_block,ctx2+4*14
	move.l	#Y0000,ctx2+4*15
	clr.b	booted2
	st	sub_run
	movem.l	(sp)+,d0-d1/a0
	rts

; ------------------------------------------------------------------------------
; The MCU (m6801x.py's translation, mcu_mem = its memory).  Its registers are d0-d3 / d6 /
; d7, a5 (stack), a6 (memory), so the Z80 code's registers are saved around a run.
; ------------------------------------------------------------------------------

mcu_boot:
	movem.l	d0-d7/a0-a6,-(sp)
	move.l	sp,mcu_sp0
	lea	mcu_mem,a6
	lea	mcu_mem+$100,a5
	moveq	#0,d2
	bsr	MF003
	st	mcu_booted
mcu_exit:
	movem.l	(sp)+,d0-d7/a0-a6
	rts

mcu_irq:
	tst.b	mcu_booted
	beq.s	.no
	movem.l	d0-d7/a0-a6,-(sp)
	move.l	sp,mcu_sp0
	lea	mcu_mem,a6
	lea	mcu_mem+$100,a5
	moveq	#0,d2
	bsr	MF046
	bra.s	mcu_exit
.no:	rts

; F1BF: B = the byte at the shared RAM / input address X (d2).  The effects of the firmware routine
; (DDRs as the init leaves them: P1 $F0, P2 and P4 $FF): P1 data = P1 | $80, P3 DDR = 0, ($4A) = X,
; P4 = X low, P2 = X high nibble, then | $10 (the clock: the bus cycle), A = that, B = the byte.

mcu_bus_read:
	move.b	mcu_mem+2,d0
	and.b	#$F0,d0
	or.b	in0_val,d0		; P1 as the pins show
	or.b	#$80,d0
	move.b	d0,mcu_mem+2
	and.b	#$F0,d0
	or.b	#$0F,d0
	move.b	d0,p1_out		; (no edge of bit 6: the latch's bit 6 is what it was)
	clr.b	mcu_mem+4
	move.w	d2,mcu_mem+$4A
	move.b	d2,mcu_mem+7
	move.w	d2,d0
	lsr.w	#8,d0
	and.b	#$0F,d0
	move.b	d0,mcu_mem+3
	or.b	#$10,d0
	move.b	d0,mcu_mem+3
	move.b	d0,p2_out
	; the bus cycle (a read): X & $800 clear: DSW0, DSW1, IN1, IN2; X & $C00 = $C00: the shared RAM
	move.w	d2,d1
	and.w	#$0800,d1
	bne.s	.r_mc
	move.w	d2,d1
	and.w	#3,d1
	lea	dsw0,a0
	move.b	(a0,d1.w),p3_in
	bra.s	.r_done
.r_mc:
	move.w	d2,d1
	and.w	#$0C00,d1
	cmp.w	#$0C00,d1
	bne.s	.r_done
	move.w	d2,d1
	and.w	#$03FF,d1
	lea	G_MCRAM,a0
	move.b	(a0,d1.w),p3_in
.r_done:
	moveq	#0,d1
	move.b	p3_in,d1		; P3 read (the DDR is 0)
	tst.b	d1
	rts

; F1DB: write B (d1) at X (d2): P1 data = P1 & $7F, P3 DDR = $FF, P3 = B, ($4A) = X, P4 = X low,
; P2 = X high nibble, then | $10; A = that, B = X low.

mcu_bus_write:
	move.b	mcu_mem+2,d0
	and.b	#$F0,d0
	or.b	in0_val,d0
	and.b	#$7F,d0
	move.b	d0,mcu_mem+2
	and.b	#$F0,d0
	or.b	#$0F,d0
	move.b	d0,p1_out
	move.b	#$FF,mcu_mem+4
	move.b	d1,mcu_mem+6
	move.w	d2,mcu_mem+$4A
	move.b	d2,mcu_mem+7
	move.w	d2,d0
	lsr.w	#8,d0
	and.b	#$0F,d0
	move.b	d0,mcu_mem+3
	or.b	#$10,d0
	move.b	d0,mcu_mem+3
	move.b	d0,p2_out
	move.w	d2,d1			; the bus cycle (a write): only the shared RAM
	and.w	#$0C00,d1
	cmp.w	#$0C00,d1
	bne.s	.w_done
	move.w	d2,d1
	and.w	#$03FF,d1
	lea	G_MCRAM,a0
	move.b	mcu_mem+6,(a0,d1.w)
.w_done:
	moveq	#0,d1
	move.b	d2,d1			; B = X low (ldd $4A)
	tst.b	d0
	rts

mcu_restart:				; the firmware asked for a reset: the init runs again at the next turn
	clr.b	mcu_booted
	move.l	mcu_sp0,sp
	bra	mcu_exit

; The ports.  d7 = the value / the result; all other registers are kept.

; The usual cases first (P1: DDR $F0, P3 read: DDR 0, P2 / P3 / P4 outputs: DDR $FF): the bus is
; clocked tens of times per frame.  Anything else takes the general versions below.

mcu_rd_p1:
	cmp.b	#$F0,mcu_mem+0
	bne	mcu_rd_p1_slow
	move.b	mcu_mem+2,d7
	and.b	#$F0,d7
	or.b	in0_val,d7		; (in0's high bits are 1: only its low nibble is an input)
	rts

mcu_rd_p3:
	tst.b	mcu_mem+4
	bne	mcu_rd_p3_slow
	move.b	p3_in,d7
	rts

mcu_wr_p1:
	cmp.b	#$F0,mcu_mem+0
	bne	mcu_wr_p1_slow
	and.b	#$F0,d7
	or.b	#$0F,d7			; the output pins: data where the DDR bit is set, else 1
	btst	#6,p1_out
	beq.s	.n
	btst	#6,d7
	bne.s	.n
	st	main_irq		; bit 6 high -> low: the main CPU's interrupt
.n:
	move.b	d7,p1_out
	rts

mcu_wr_p2:
	cmp.b	#$FF,mcu_mem+1
	bne	mcu_wr_p2_slow
	cmp.b	#$FF,mcu_mem+5
	bne	mcu_wr_p2_slow
	btst	#4,d7			; the rising edge of bit 4 does the bus cycle
	beq	.store
	btst	#4,p2_out
	bne	.store
	movem.l	d0-d1/a0,-(sp)
	moveq	#0,d0
	move.b	d7,d0
	and.w	#$0F,d0
	lsl.w	#8,d0
	move.b	mcu_mem+7,d0		; the address: P2 bits 0-3 high, P4 low
	btst	#7,p1_out
	beq.s	.write
	move.w	d0,d1			; read
	and.w	#$0800,d1
	bne.s	.mc
	and.w	#3,d0
	lea	dsw0,a0
	move.b	(a0,d0.w),p3_in		; DSW0, DSW1, IN1, IN2
	bra.s	.bus_done
.mc:
	move.w	d0,d1
	and.w	#$0c00,d1
	cmp.w	#$0c00,d1
	bne.s	.bus_done
	and.w	#$03ff,d0
	lea	G_MCRAM,a0
	move.b	(a0,d0.w),p3_in
	bra.s	.bus_done
.write:
	move.w	d0,d1
	and.w	#$0c00,d1
	cmp.w	#$0c00,d1
	bne.s	.bus_done
	and.w	#$03ff,d0
	lea	G_MCRAM,a0
	cmp.b	#$FF,mcu_mem+4		; (the data pins are outputs: P3's latch)
	bne.s	.bus_done
	move.b	mcu_mem+6,(a0,d0.w)
.bus_done:
	movem.l	(sp)+,d0-d1/a0
.store:
	move.b	d7,p2_out
	rts


mcu_rd_p1_slow:			; P1 as the pins show: the latch where output, IN0 where input
	move.l	d3,-(sp)
	move.b	mcu_mem+0,d7		; DDR
	move.b	d7,d3
	not.b	d3
	and.b	in0_val,d3
	and.b	mcu_mem+2,d7
	or.b	d3,d7
	move.l	(sp)+,d3
	rts

mcu_rd_p3_slow:
	move.l	d3,-(sp)
	move.b	mcu_mem+4,d7
	move.b	d7,d3
	not.b	d3
	and.b	p3_in,d3
	and.b	mcu_mem+6,d7
	or.b	d3,d7
	move.l	(sp)+,d3
	rts

; the value an output port shows: data where the DDR bit is set, else 1:  d7 = data, d3 = DDR

mcu_out	macro
	cmp.b	#$ff,\2
	beq.s	.o\@
	and.b	\2,\1
	not.b	\2
	or.b	\2,\1
.o\@:
	endm

mcu_wr_p1_slow:
	move.l	d3,-(sp)
	move.b	mcu_mem+0,d3
	mcu_out	d7,d3
	move.b	p1_out,d3
	btst	#6,d3
	beq.s	.no_irq
	btst	#6,d7			; high -> low: the main CPU's interrupt
	bne.s	.no_irq
	st	main_irq
.no_irq:
	move.b	d7,p1_out
	move.l	(sp)+,d3
	rts

mcu_wr_p2_slow:
	movem.l	d0-d3/a0,-(sp)
	; P4 (the low address), P3 (the data) as they show, P2
	moveq	#0,d1
	move.b	mcu_mem+7,d1
	move.b	mcu_mem+5,d3
	mcu_out	d1,d3
	move.b	mcu_mem+6,d2
	move.b	mcu_mem+4,d3
	mcu_out	d2,d3
	move.b	mcu_mem+3,d0
	move.b	mcu_mem+1,d3
	mcu_out	d0,d3			; d0 = the new P2 output
	move.b	p2_out,d3
	btst	#4,d3
	bne	.done			; (only the rising edge of the clock)
	btst	#4,d0
	beq	.done
	and.w	#$0f,d0
	lsl.w	#8,d0
	or.w	d1,d0			; the address
	btst	#7,p1_out
	beq.s	.write
	move.w	d0,d3			; read
	and.w	#$0800,d3
	bne.s	.mc
	and.w	#3,d0
	lea	dsw0,a0
	move.b	(a0,d0.w),p3_in		; DSW0, DSW1, IN1, IN2
	bra.s	.done
.mc:
	move.w	d0,d3
	and.w	#$0c00,d3
	cmp.w	#$0c00,d3
	bne.s	.done
	and.w	#$03ff,d0
	lea	G_MCRAM,a0
	move.b	(a0,d0.w),p3_in
	bra.s	.done
.write:
	move.w	d0,d3
	and.w	#$0c00,d3
	cmp.w	#$0c00,d3
	bne.s	.done
	and.w	#$03ff,d0
	lea	G_MCRAM,a0
	move.b	d2,(a0,d0.w)
.done:
	move.b	mcu_mem+3,d0
	move.b	mcu_mem+1,d3
	mcu_out	d0,d3
	move.b	d0,p2_out
	movem.l	(sp)+,d0-d3/a0
	rts

; ------------------------------------------------------------------------------
; Keyboard / joystick (IKBD): the pressed bits of p1 / p2 / coins
; ------------------------------------------------------------------------------

	jagpad_text
	jagpad_maps

acia_isr:
	addq	#1,cnt_acia
	movem.l	d0-d2/a0,-(sp)

.again:
	move.b	$fffffc00.w,d0
	btst	#0,d0
	beq	.done

	moveq	#0,d1
	move.b	$fffffc02.w,d1

	move.b	ikbd_state,d0
	bne	.packet_byte

	cmp.b	#$fe,d1
	beq	.header_joy0
	cmp.b	#$ff,d1
	beq	.header_joy1
	cmp.b	#$f6,d1
	bhs	.again

	move.b	d1,d2
	and.b	#$7f,d1
	cmp.b	#KEY_ESC,d1
	bne	.not_esc
	tst.b	d2
	bmi	.again
	st	quit_flag
	bra	.again

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
	or.b	d0,p1_kbd
	move.b	3(a0),d0
	or.b	d0,p2_kbd
	bsr	compose_inputs
	bra	.again

.release:
	move.b	1(a0),d0
	not.b	d0
	and.b	d0,in0_kbd
	move.b	2(a0),d0
	not.b	d0
	and.b	d0,p1_kbd
	move.b	3(a0),d0
	not.b	d0
	and.b	d0,p2_kbd
	bsr	compose_inputs
	bra	.again

.header_joy0:
	move.b	#1,ikbd_state
	bra	.again

.header_joy1:
	move.b	#2,ikbd_state
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
	; joystick 1 (port 1) plays player 1, joystick 0 player 2
	moveq	#0,d0
	move.b	joy1_state,d1
	btst	#2,d1			; left
	beq	.j1
	bset	#0,d0
.j1:	btst	#3,d1			; right
	beq	.j2
	bset	#1,d0
.j2:	tst.b	d1			; fire = jump
	bpl	.j3
	bset	#5,d0
.j3:	btst	#0,d1			; up = bubble
	beq	.j4
	bset	#4,d0
.j4:	move.b	d0,p1_joy
	moveq	#0,d0
	move.b	joy0_state,d1
	btst	#2,d1
	beq	.k1
	bset	#0,d0
.k1:	btst	#3,d1
	beq	.k2
	bset	#1,d0
.k2:	tst.b	d1
	bpl	.k3
	bset	#5,d0
.k3:	btst	#0,d1
	beq	.k4
	bset	#4,d0
.k4:	move.b	d0,p2_joy
	bsr	compose_inputs
	bra	.again

.done:
	movem.l	(sp)+,d0-d2/a0
	rte

; in0_val: IN0 (bits 0 and 1 high when idle: tilt, service; coin 1 and 2 high when pressed),
; in1_val / in2_val: active low

compose_inputs:
	move.b	in0_kbd,d0
	or.b	jp_in,d0		; (the pads: jagpad_poll in the VBL)
	or.b	#$03,d0
	move.b	d0,in0_val
	move.b	p1_kbd,d0
	or.b	p1_joy,d0
	or.b	jp_in+1,d0
	not.b	d0
	move.b	d0,in1_val
	move.b	p2_kbd,d0
	or.b	p2_joy,d0
	or.b	jp_in+2,d0
	not.b	d0
	move.b	d0,in2_val
	rts

; scancode, IN0 bits (coins), player 1 bits (left 0, right 1, bubble 4, jump 5, start 6),
; player 2 bits

key_table:
	dc.b	$4d,$00,$02,$00		; right
	dc.b	$4b,$00,$01,$00		; left
	dc.b	$39,$00,$20,$00		; space = jump
	dc.b	$1d,$00,$20,$00		; control = jump
	dc.b	$38,$00,$10,$00		; alternate = bubble
	dc.b	$02,$00,$40,$00		; 1 = start 1
	dc.b	$03,$00,$00,$40		; 2 = start 2
	dc.b	$06,$04,$00,$00		; 5 = coin 1
	dc.b	$07,$08,$00,$00		; 6 = coin 2
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
	move.b	#' ',(a0)+
	move.l	dbg_vbl_pc,d1		; where the last VBL interrupted
	bsr	hex_long
	move.b	#' ',(a0)+
	move.l	dbg_t_pc,d1		; and the last timer
	bsr	hex_long
	move.b	#' ',(a0)+
	move.l	dbg_vbl_sp,d1		; the stack at the last VBL, the VBL nesting
	bsr	hex_long
	move.b	#' ',(a0)+
	move.w	dbg_nest,d1
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
sim_frame_done:				; the test harness stops here (once per frame, after the game's interrupts)
	bra.s	sim_frame_done
sim_renders:	dc.l	0			; renders started so far (tools/profile.py)
sim_game_frames:	dc.l	0			; the game's interrupt rounds run so far (tools/profile.py)
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
; The translated programs (and their dispatch tables in the data section).

	include "bb_code.s"
	include "bb_mcu.s"

	section text,code
	include "rtlib.s"

; ------------------------------------------------------------------------------
	section data,data
; ------------------------------------------------------------------------------

rom_table:				; source, destination, bytes
	dc.l	rom_main,G_ROM1,$8000
	dc.l	rom_banks,g_win,$10000
	dc.l	rom_sub,g_block,$8000
	dc.l	rom_mcu,mcu_rom,$1000
	dc.l	0
rom_main:	incbin	"rom_main.rom"
rom_banks:	incbin	"rom_banks.rom"
rom_sub:	incbin	"rom_sub.rom"
rom_mcu:	incbin	"rom_mcu.rom"
	even

bad_text:
	dc.b	13,10
	dc.b	"Bubble Bobble: the translated code reached an address it does not have",13,10
	dc.b	"(see the dispatch tables). Press a key.",13,10,0
	even

	include "data.s"

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
	jagpad_vars
border_a:	ds.b	1
border_b:	ds.b	1
frame_ready:	ds.b	1		; the draw screen is complete, to be shown at the VBL
in_logic:	ds.b	1		; the game's interrupts of a VBL are running
render_age:	ds.b	1		; VBLs since the frame being drawn began
skip_phase:	ds.b	1
in_render:	ds.b	1		; drawing: the main CPU's registers are in main_ctx
in_turn:	ds.b	1		; a booting chip runs with its registers live
current:	ds.b	1		; 0: the main CPU's code runs, 1: the sub CPU's
booted1:	ds.b	1		; the main CPU reached its idle loop
booted2:	ds.b	1		; the sub CPU reached its idle loop
sub_run:	ds.b	1		; the sub CPU is released (FB40 bit 4)
mcu_run:	ds.b	1		; the MCU is released (bit 5)
mcu_booted:	ds.b	1
main_irq:	ds.b	1		; the MCU raised the main CPU's interrupt
g1_iff:		ds.b	1		; the CPUs' interrupt enable (ei / di)
g2_iff:		ds.b	1
g1_ireg:	ds.b	1		; the main CPU's I register
g_fb40:		ds.b	1
g_bank:		ds.b	1
video_enable:	ds.b	1
video_flip:	ds.b	1
p1_out:		ds.b	1		; what the MCU's ports show
p2_out:		ds.b	1
p3_in:		ds.b	1
ikbd_state:	ds.b	1
joy0_state:	ds.b	1
joy1_state:	ds.b	1
in0_kbd:	ds.b	1
p1_kbd:		ds.b	1
p2_kbd:		ds.b	1
p1_joy:		ds.b	1
p2_joy:		ds.b	1
in0_val:	ds.b	1
dsw0:		ds.b	1		; the order matters: DSW0, DSW1, IN1, IN2
dsw1:		ds.b	1
in1_val:	ds.b	1
in2_val:	ds.b	1
	even
g_bank4:	ds.w	1
rnd_state:	ds.w	1
cnt_acia:	ds.w	1
cnt_late:	ds.w	1
cnt_vbl:	ds.w	1
crash_vector:	ds.w	1
crash_sp:	ds.l	1
dbg_vbl_pc:	ds.l	1
dbg_t_pc:	ds.l	1
dbg_vbl_sp:	ds.l	1
dbg_nest:	ds.w	1
crash_regs:	ds.l	16
crash_text:	ds.b	512
draw_index:	ds.w	1
scr_address:	ds.l	2
draw_screen_address:	ds.l	1
display_screen_address:	ds.l	1
frame_counter:	ds.l	1
g1_ret_to:	ds.l	1
g_winbase:	ds.l	1		; the current ROM bank's window copy + $8000
g2_ret_to:	ds.l	1
turn_sp:	ds.l	1
mcu_sp0:	ds.l	1
main_ctx:	ds.l	15
ctx2:		ds.l	16		; d0-d7, a0-a6, resume address

	ds.l	1024
own_stack_top:

g_block:	ds.b	$18000		; [sub ROM 32K | RAM 32K | main ROM 32K]
g_win:		ds.b	$14000		; the windows' copies: 4 banks + the empty one
mcu_rom:	ds.b	$1000
mcu_mem:	ds.b	$10000
g1_dispatch_sw:	ds.l	65536*4		; one table per bank
g2_dispatch_sw:	ds.l	65536

	cnop	0,256
screens:	ds.b	SCREEN_SIZE*2+256
