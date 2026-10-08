; ------------------------------------------------------------------------------
;
; Galaga for the Atari STE
;
; The arcade's main and sub Z80 programs are translated to 68000 code by
; tools/galaga_gen.py (z80x.py); this file is the machine around them: STE video
; (320 x 277 with the borders removed, the game's 224 x 288 rotated picture with a few
; lines cropped), double buffering, the tile and sprite renderer (galaga_render.s,
; galaga_sprites.s), the custom I/O chips (06XX, 51XX), input, and the schedule:
;
;   The main CPU's program is the foreground thread.  At every VBL the main CPU's IRQ
;   handler runs (if the program enabled it), then the sub CPU's IRQ handler with the sub
;   CPU's own register set (its main loop only idles once it has booted), then the frame
;   is drawn.  The 06XX's NMIs (transfers to and from the 51XX) run right at the control
;   write, as often as the program keeps the transfer going.  The boot handshake between
;   the three CPUs (self-test results in RAM flags) is run by giving the sub CPU a turn at
;   the main CPU's spin loops and at the VBL (z80_hook); the sound CPU's part of it is
;   done natively, it is not translated (no sound).
;
; Memory: one block holds [sub ROM 32K | shared RAM 32K ($8000-$FFFF) | main ROM 32K];
; the main CPU's code addresses with a6 = its ROM and signed word offsets (the RAM lies
; below), the sub CPU's with a6 = its ROM and long offsets (the RAM above).  The
; registers $6800-$7FFF (switches, latches, 06XX) are cells in each CPU's ROM half.
;
; Needs gg1_1b.3p gg1_2b.3m gg1_3.2m gg1_4b.2l gg1_5b.3f gg1_7b.2c in the current folder.
;
; ------------------------------------------------------------------------------

BUSY = %10000000
HOG = %01000000
NFSR = %01000000

STRIDE = 256				; bytes per line, 512 pixel virtual screen
GAME_X = 24				; byte offset of the game area in a line (3 chunks)
GAME_LINES = 288			; the rotated arcade picture
MARK_TOP = 8				; cell rows of tile_marks above the display (sprites hang over)
MARK_ROWS = MARK_TOP+36+8		; 8 pixel rows of tile_marks
MARK_SIZE = MARK_ROWS*8
KEY_ESC = $01

	ifnd CROP_TOP
CROP_TOP = 24				; the STE shows 277 of the 288 lines: from this buffer line on
					; (the picture starts at DISP_TOP = 32, so 8 black lines above it)
	endc

	ifnd TA_DATA
TA_DATA = 98
	endc
	ifnd TA_NOPS
TA_NOPS = 84
	endc
	ifnd FRAMES
FRAMES = 0
	endc

; The Z80 address space as 68k addresses (see the header).

G_ROM1 = g_block+$10000			; main CPU: a6
G_IO1 = G_ROM1				; its $6800-$7FFF cells: G_IO1+addr
G_IO2 = g_block				; the sub CPU's
TOKEN = $0140				; $4001 on the Z80 stack, byte swapped

arm_border_timers	macro
	clr.b	$fffffa1b.w
	move.b	#199+29,$fffffa21.w
	move.b	#8,$fffffa1b.w
	move.b	#TA_DATA,$fffffa1f.w
	move.b	#4,$fffffa19.w
	st	border_a
	st	border_b
	endm

chk_sp	macro
	ifd CHKSP
	cmp.l	vbl_sp,sp
	beq.s	.ok\@
	moveq	#\1,d0
	bra	crash_common
.ok\@:
	endc
	endm

wait_borders	macro
.a\@:	tst.b	border_a
	bne.s	.a\@
	cmp.b	#6,$fffffa21.w
	bhi.s	.d\@
	tst.b	border_b
	bne.s	.a\@
.d\@:
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
	tst.l	d0
	bne	rom_error

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

	; The sub CPU's context: registers 0, at its reset vector.

	lea	ctx2,a0
	moveq	#15,d0
.ctx:	clr.l	(a0)+
	dbf	d0,.ctx
	move.l	#g2_dispatch_sw,ctx2+4*12	; a4
	move.l	#g_block,ctx2+4*14		; a6
	move.l	#Y0000,ctx2+4*15		; resume

	bsr	n51_reset
	move.l	#$1234,rnd_state
	ifd IOLOG
	move.l	#iolog_buf,iolog_ptr
	endc

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
; ROM loading (GEMDOS): 6 files of 4 KB
; ------------------------------------------------------------------------------

load_roms:
	lea	rom_names,a3
	lea	rom_places,a2
	moveq	#5,d6

.next:
	clr	-(sp)			; Fopen, read only
	pea	(a3)
	move	#$3d,-(sp)
	trap	#1
	addq	#8,sp
	tst	d0
	bmi.s	.fail

	move	d0,d7
	move.l	(a2)+,-(sp)		; Fread 4096 bytes
	move.l	#$1000,-(sp)
	move	d7,-(sp)
	move	#$3f,-(sp)
	trap	#1
	lea	12(sp),sp
	cmp.l	#$1000,d0
	bne.s	.fail

	move	d7,-(sp)		; Fclose
	move	#$3e,-(sp)
	trap	#1
	addq	#4,sp

.skip:
	tst.b	(a3)+
	bne.s	.skip

	dbf	d6,.next

	moveq	#0,d0
	rts

.fail:
	moveq	#1,d0
	rts

rom_error:
	pea	rom_error_text
	move	#9,-(sp)
	trap	#1
	addq	#6,sp
	move	#1,-(sp)
	trap	#1
	addq	#2,sp
	clr	-(sp)
	trap	#1

; The I/O cells: the DIP switches as the program reads them (one bit of each bank per
; address), in both CPUs' halves; the latches 0.

init_cells:
	lea	G_IO1+$6800,a0
	lea	G_IO2+$6800,a1
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
	addq	#1,d1
	cmp	#8,d1
	blt.s	.dsw
	rts

dswa:	dc.b	$f7			; easy, demo sounds on, upright
dswb:	dc.b	$97			; 1 coin 1 credit, 20K 70K 70K, 3 lives
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
	; 64 KiB aligned screens of 128 KiB (the lines beyond 288 are slack for sprites
	; hanging over the bottom): background (tiles only), two draw buffers.

	move.l	#screens,d0
	add.l	#$10000-1,d0
	and.l	#$ffff0000,d0
	move.l	d0,bg_address
	add.l	#$20000,d0
	move.l	d0,scr_address
	add.l	#$20000,d0
	move.l	d0,scr_address+4

	move.l	bg_address,d0
	bsr	clear_screen
	move.l	scr_address,d0
	bsr	clear_screen
	move.l	scr_address+4,d0
	bsr	clear_screen

	movem.l	ga_palette,d0-d7
	movem.l	d0-d7,$ffff8240.w

	clr.b	$ffff8260.w		; low resolution
	move.b	#(512-320)/2/2,$ffff820f.w	; virtual line width 512 pixels

	move.l	scr_address+4,draw_screen_address
	move.l	scr_address,display_screen_address
	clr	draw_index
	rts

; d0 = address of a 128 KiB screen

clear_screen:
	move	#2,$ffff8a2e.w
	move	#$ffff,$ffff8a28.w
	move	#$ffff,$ffff8a2a.w
	move	#$ffff,$ffff8a2c.w
	move.b	#1,$ffff8a3a.w		; HOP 1 (halftone only)
	move.b	#0,$ffff8a3b.w		; OP 0 (destination = 0)
	clr.b	$ffff8a3d.w
	move	#$8000,$ffff8a36.w	; X count = 64 KB
	move.l	d0,$ffff8a32.w
	move	#1,$ffff8a38.w
	move.b	#$c0,$ffff8a3c.w
	add.l	#$10000,d0
	move.l	d0,$ffff8a32.w
	move	#1,$ffff8a38.w
	move.b	#$c0,$ffff8a3c.w
	rts

; ------------------------------------------------------------------------------
; Interrupts
; ------------------------------------------------------------------------------

hbl:
	rte

; The VBL starts the frame: it switches the screen, starts the border timers, runs the
; two CPUs' IRQ handlers and draws.  The registers of the interrupted foreground thread
; are kept on the stack and restored at the end.

vbl:
	arm_border_timers
	ifd CHKSP
	cmp.l	#own_stack_top-6,sp	; the interrupted thread's stack above its top?
	bls.s	.sp_ok
	moveq	#24,d0
	bra	crash_common
.sp_ok:
	endc

	ifd DEBUG
	addq	#1,cnt_vbl
	endc
	movem.l	d0-d7/a0-a6,-(sp)

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
.no_swap:

	addq.l	#1,frame_counter

	tst.b	quit_flag
	bne	quit

	; The game's interrupts, at every VBL (the border timers may interrupt, the next
	; VBL may not).

	move	#$2400,sr
	ifd CHKSP
	move.l	sp,vbl_sp
	endc

	tst.b	in_turn			; a booting CPU's registers are live: no handlers
	bne	vbl_render

	; Main CPU IRQ (IM 1: rst $38) with the interrupted registers, if enabled.  Its
	; register state afterwards is dropped: the handler restores every Z80 register
	; itself, and the interrupted code may hold a half-done value in d5 / d7.  While
	; the runtime renders (this VBL interrupted the renderer, not the main CPU), the
	; main CPU's registers are in main_ctx.

	tst.b	G_IO1+$6820
	beq.s	.no_irq1
	tst.b	g1_iff			; the program's ei / di
	beq.s	.no_irq1
	clr.b	g1_iff			; (the handler's ei sets it again)
	movem.l	(sp),d0-d7/a0-a6
	tst.b	in_render
	beq.s	.regs1
	movem.l	main_ctx,d0-d7/a0-a6
.regs1:
	move.w	#TOKEN,-(a5)
	move.l	#.after_irq1,g1_ret_to
	jmp	Z0038
.after_irq1:
	chk_sp	20
.no_irq1:

	; Sub CPU IRQ with its own registers, once it has booted and enabled it.

	tst.b	booted2
	beq.s	.no_irq2
	tst.b	G_IO2+$6821
	beq.s	.no_irq2
	tst.b	g2_iff
	beq.s	.no_irq2
	clr.b	g2_iff
	movem.l	ctx2,d0-d7/a0-a6
	move.w	#TOKEN,-(a5)
	move.l	#.after_irq2,g2_ret_to
	jmp	Y0038
.after_irq2:
	movem.l	d0-d7/a0-a6,ctx2
	chk_sp	21
.no_irq2:

	bsr	g_boot_turns		; a booting CPU waiting for the main CPU gets on
	chk_sp	22

vbl_render:
	; Draw the frame, with the VBL enabled: when it takes longer than a frame, the
	; next VBL runs the game's interrupts (above) and skips the drawing; the game
	; keeps its pace and the display drops frames.
	tst.b	in_render
	bne.s	vbl_done
	tst.b	in_turn
	bne.s	vbl_done
	movem.l	(sp),d0-d7/a0-a6	; the main CPU's registers for its IRQ handler
	movem.l	d0-d7/a0-a6,main_ctx
	st	in_render
	ifd DEBUG
	move.l	draw_screen_address,a0
	add.l	#CROP_TOP*STRIDE,a0
	move	frame_counter+2,(a0)
	move	cnt_timer_a,256(a0)
	move	cnt_timer_b,512(a0)
	move	cnt_vbl,768(a0)
	move	cnt_render,1024(a0)
	addq	#1,cnt_render
	endc
	move	#$2300,sr
	bsr	render_frame
	move	#$2400,sr
	clr.b	in_render
	st	frame_ready

vbl_done:
	if FRAMES
	move.l	frame_counter,d0
	cmp.l	#FRAMES,d0
	blt.s	.go_on
	st	quit_flag
.go_on:
	endc

	movem.l	(sp)+,d0-d7/a0-a6
	rte

; The token on a Z80 stack returns here: back to whoever started the handler.

g1_ret:
	move.l	g1_ret_to,-(sp)
	rts

g2_ret:
	move.l	g2_ret_to,-(sp)
	rts

timer_a:
	addq	#1,cnt_timer_a
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
	addq	#1,cnt_timer_b
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
; others a turn and continues; the sub CPU, running in a turn, hands back.  A turn
; runs a CPU from where it stopped to its next spin loop or its idle loop.
; ------------------------------------------------------------------------------

z80_hook:				; (the hook pushed the address it continues at)
	tst.b	current
	bne.s	.sub_yields

	movem.l	d0-d7/a0-a6,-(sp)
	bsr	g_boot_turns
	movem.l	(sp)+,d0-d7/a0-a6
	rts				; to the resume address

.sub_yields:
	movem.l	d0-d7/a0-a6,ctx2
	move.l	(sp)+,ctx2+4*15		; where it continues next time
	cmp.w	#$05B1,d7		; its idle loop: the boot is done
	bne.s	.back
	st	booted2
.back:
	move.l	turn_sp,sp
	movem.l	(sp)+,d0-d7/a0-a6
	clr.b	in_turn			; (after the registers: a VBL in between sees the turn)
	clr.b	current
	rts

; Turns for the CPUs that are released (latch $6823) and still booting.  Keeps every
; register.

g_boot_turns:
	tst.b	G_IO1+$6823
	beq.s	.none
	bsr.s	g_boot_turn2
	bsr.s	g_cpu3_turn
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

; The sound CPU's boot, natively: it waits for the main CPU to clear its flag $9101,
; posts its ROM checksum result ($FF: good), waits for the flag to be cleared again,
; then clears its work area $9A00-$9AFF and idles for good.

g_cpu3_turn:
	move.b	cpu3_state,d0
	bne.s	.posted
	tst.b	g_ram+$1101
	bne.s	.wait
	move.b	#$ff,g_ram+$1101
	move.b	#1,cpu3_state
.wait:	rts
.posted:
	cmp.b	#1,d0
	bne.s	.wait
	tst.b	g_ram+$1101
	bne.s	.wait
	lea	g_ram+$1a00,a0
	moveq	#0,d0
	move	#255/4,d1
.clear:	move.l	d0,(a0)+
	dbf	d1,.clear
	move.b	#2,cpu3_state
	rts

; ------------------------------------------------------------------------------
; Halt (the main CPU waits for its interrupt = the next VBL) and the refresh register
; (`ld a,r`: a pseudo random byte, the reference uses the same generator).

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
; 06XX: transfers between the main CPU and the custom chips.  The program writes the
; control register ($7100, hooked after `ld ($7100),a`): bit 4 read/write, bits 0-3 the
; chip (0: 51XX, 3: 54XX noise, ignored), bits 5-7 the clock, which pulses an NMI per
; byte; the NMI handler moves a byte between $7000 and memory with `ldi` and stops the
; transfer with control = $10 when done.  Here the handler runs right away, as often as
; the program keeps the clock going: a read puts the chip's byte into the $7000 cell
; first, a write takes it from there afterwards.
; ------------------------------------------------------------------------------

iolog	macro
	ifd IOLOG
	move.l	a0,-(sp)
	move.l	iolog_ptr,a0
	move.b	#\1,(a0)+
	move.b	\2,(a0)+
	cmp.l	#iolog_end,a0
	blo.s	.l\@
	lea	iolog_buf,a0
.l\@:	move.l	a0,iolog_ptr
	move.l	(sp)+,a0
	endc
	endm

g_ctrl06:
	move.l	g1_ret_to,-(sp)		; (the IRQ handler we may be in returns through it)
	iolog	1,G_IO1+$7100
.loop:
	move.b	G_IO1+$7100,d7
	move.b	d7,ctrl06_mode
	and.b	#$e0,d7
	beq	.done
	btst	#4,ctrl06_mode
	beq.s	.nmi			; write
	btst	#0,ctrl06_mode
	beq.s	.nmi
	bsr	n51_read
	move.b	d7,G_IO1+$7000		; the port is the whole $7000-$70FF range: the
	move.b	d7,G_IO1+$7001		; handler's pointer walks through it
	move.b	d7,G_IO1+$7002
	move.b	d7,G_IO1+$7003
	move.b	d7,G_IO1+$7004
	move.b	d7,G_IO1+$7005
	move.b	d7,G_IO1+$7006
	move.b	d7,G_IO1+$7007
	move.b	d7,G_IO1+$7008
	move.b	d7,G_IO1+$7009
	move.b	d7,G_IO1+$700A
	move.b	d7,G_IO1+$700B
	move.b	d7,G_IO1+$700C
	move.b	d7,G_IO1+$700D
	move.b	d7,G_IO1+$700E
	move.b	d7,G_IO1+$700F
.nmi:
	move.b	g1_iff,-(sp)		; an NMI disables the interrupts until its retn
	clr.b	g1_iff
	move.w	#TOKEN,-(a5)
	move.l	#.back,g1_ret_to
	jmp	Z0066
.back:
	move.b	(sp)+,g1_iff
	btst	#4,ctrl06_mode
	bne	.loop
	btst	#0,ctrl06_mode
	beq	.loop
	move.w	a1,d7			; the handler's `ldi` wrote through de' (a1 after
	subq.w	#1,d7			; its exx back), one past the byte
	move.b	(a6,d7.w),d7
	bsr	n51_write
	bra	.loop
.done:
	move.l	(sp)+,g1_ret_to
	rts

; A plain data write ($7000, hooked): to the chip if the transfer is a write.

g_data06:
	move.b	G_IO1+$7100,d7
	btst	#4,d7
	bne.s	.done
	btst	#0,d7
	beq.s	.done
	move.b	G_IO1+$7000,d7
	bsr	n51_write
.done:
	rts

; ------------------------------------------------------------------------------
; 51XX: coins, credits, start buttons, joysticks (the old MAME simulation; see
; galaga.py Namco51).  d7 = the byte; everything else is kept.
; ------------------------------------------------------------------------------

n51_reset:
	lea	n51_state,a0
	moveq	#0,d0
	moveq	#(N51_SIZE/2)-1,d1
.c:	move	d0,(a0)+
	dbf	d1,.c
	move.b	#1,n51_cpc
	move.b	#1,n51_cpc+1
	move.b	#1,n51_crc
	move.b	#1,n51_crc+1
	rts

n51_write:
	movem.l	d0-d1/a0,-(sp)
	iolog	2,d7
	and	#7,d7
	move.b	n51_coincred,d0
	beq.s	.command
	subq.b	#1,n51_coincred
	lea	n51_cpc,a0		; 4: coins/credit 1, 3: credits/coin 1, 2: coins/credit 2, 1: credits/coin 2
	moveq	#4,d1
	sub.b	d0,d1
	move.b	d7,(a0,d1.w)
	bra	.done
.command:
	cmp.b	#1,d7
	bne.s	.c2
	move.b	#4,n51_coincred
	bra	.done
.c2:	cmp.b	#2,d7
	bne.s	.c3
	move.b	#1,n51_mode
	clr.b	n51_count
	bra	.done
.c3:	cmp.b	#3,d7
	bne.s	.c4
	clr.b	n51_remap
	bra	.done
.c4:	cmp.b	#4,d7
	bne.s	.c5
	move.b	#1,n51_remap
	bra	.done
.c5:	cmp.b	#5,d7
	bne.s	.done
	clr.b	n51_mode
	clr.b	n51_count
.done:
	movem.l	(sp)+,d0-d1/a0
	rts

; The inputs, active low as the arcade's: in0 = joysticks (bit 1 right, bit 3 left),
; in1 = fire (bit 0), start 1 (2), start 2 (3), coin 1 (4), coin 2 (5), service (6).

n51_read:
	movem.l	d0-d3/a0,-(sp)
	move.b	in0_kbd,d2
	or.b	in0_joy,d2
	not.b	d2			; in0
	move.b	in1_kbd,d3
	or.b	in1_joy,d3
	not.b	d3			; in1
	move.b	n51_count,d0
	addq.b	#1,n51_count
	cmp.b	#3,n51_count
	blo.s	.k
	clr.b	n51_count
.k:
	tst.b	n51_mode
	bne.s	.credit_mode
	; switch mode: the raw switches
	tst.b	d0
	bne.s	.sw1
	move.b	d2,d7
	bra	.done
.sw1:	cmp.b	#1,d0
	bne.s	.sw2
	move.b	d3,d7
	bra	.done
.sw2:	moveq	#0,d7
	bra	.done

.credit_mode:
	tst.b	d0
	bne	.joystick
	; coins and start buttons; the credits in BCD
	move.b	d3,d1
	not.b	d1			; inp: pressed bits set
	move.b	n51_lastcoins,d7
	eor.b	d1,d7			; toggle
	move.b	d1,n51_lastcoins
	and.b	d1,d7			; newly pressed
	tst.b	n51_cpc
	beq.s	.free_play
	btst	#4,d7
	beq.s	.no_coin1
	addq.b	#1,n51_coins
	move.b	n51_coins,d0
	cmp.b	n51_cpc,d0
	blo.s	.no_coin1
	move.b	n51_cpc,d0
	sub.b	d0,n51_coins
	move.b	n51_crc,d0
	add.b	d0,n51_credits
.no_coin1:
	btst	#5,d7
	beq.s	.no_coin2
	addq.b	#1,n51_coins+1
	move.b	n51_coins+1,d0
	cmp.b	n51_cpc+1,d0
	blo.s	.no_coin2
	move.b	n51_cpc+1,d0
	sub.b	d0,n51_coins+1
	move.b	n51_crc+1,d0
	add.b	d0,n51_credits
.no_coin2:
	btst	#6,d7
	beq.s	.starts
	addq.b	#1,n51_credits
	bra.s	.starts
.free_play:
	move.b	#100,n51_credits
.starts:
	cmp.b	#1,n51_mode
	bne.s	.cap
	btst	#2,d7
	beq.s	.start2
	tst.b	n51_credits
	beq.s	.cap
	subq.b	#1,n51_credits
	move.b	#2,n51_mode
	bra.s	.cap
.start2:
	btst	#3,d7
	beq.s	.cap
	cmp.b	#2,n51_credits
	blo.s	.cap
	subq.b	#2,n51_credits
	move.b	#2,n51_mode
.cap:
	moveq	#0,d0
	move.b	n51_credits,d0
	cmp.b	#99,d0
	bls.s	.bcd
	moveq	#99,d0
	move.b	d0,n51_credits
.bcd:
	divu	#10,d0			; tens in the low word, ones in the high
	move	d0,d7
	lsl.b	#4,d7
	swap	d0
	or.b	d0,d7
	bra	.done

.joystick:
	move.b	d3,d1
	not.b	d1			; buttons pressed
	move.b	n51_lastbuttons,d7
	eor.b	d1,d7			; toggle
	cmp.b	#1,d0
	bne.s	.player2
	move.b	n51_lastbuttons,d0
	and.b	#2,d0
	move.b	d1,d3
	and.b	#1,d3
	or.b	d3,d0
	move.b	d0,n51_lastbuttons
	and.b	d1,d7			; newly pressed
	and.b	#1,d7
	eor.b	#1,d7
	lsl.b	#4,d7			; bit 4: not newly pressed
	move.b	d1,d0
	and.b	#1,d0
	eor.b	#1,d0
	lsl.b	#5,d0
	or.b	d0,d7			; bit 5: not held
	move.b	d2,d0
	and.b	#$0f,d0
	or.b	d0,d7			; joystick 1
	bra	.done
.player2:
	move.b	n51_lastbuttons,d0
	and.b	#1,d0
	move.b	d1,d3
	and.b	#2,d3
	or.b	d3,d0
	move.b	d0,n51_lastbuttons
	and.b	d1,d7
	and.b	#2,d7
	eor.b	#2,d7
	lsl.b	#3,d7
	move.b	d1,d0
	and.b	#2,d0
	eor.b	#2,d0
	lsl.b	#4,d0
	or.b	d0,d7
	move.b	d2,d0
	lsr.b	#4,d0
	or.b	d0,d7			; joystick 2
.done:
	iolog	3,d7
	movem.l	(sp)+,d0-d3/a0
	rts

; ------------------------------------------------------------------------------
; Keyboard / joystick (IKBD): the pressed bits of in0 (joystick) and in1 (buttons)
; ------------------------------------------------------------------------------

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
	addq	#3,a0
	bra	.find

.found:
	tst.b	d2
	bmi	.release

	move.b	1(a0),d0
	or.b	d0,in0_kbd
	move.b	2(a0),d0
	or.b	d0,in1_kbd
	bra	.again

.release:
	move.b	1(a0),d0
	not.b	d0
	and.b	d0,in0_kbd
	move.b	2(a0),d0
	not.b	d0
	and.b	d0,in1_kbd
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
	move.b	joy0_state,d1
	or.b	joy1_state,d1
	moveq	#0,d0
	btst	#2,d1			; left
	beq	.j1
	bset	#3,d0
.j1:	btst	#3,d1			; right
	beq	.j2
	bset	#1,d0
.j2:	move.b	d0,in0_joy
	moveq	#0,d0
	tst.b	d1			; fire
	bpl	.j3
	bset	#0,d0
.j3:	move.b	d0,in1_joy
	bra	.again

.done:
	movem.l	(sp)+,d0-d2/a0
	rte

; scancode, in0 bits, in1 bits

key_table:
	dc.b	$4d,$02,$00		; right
	dc.b	$4b,$08,$00		; left
	dc.b	$39,$00,$01		; space = fire
	dc.b	$1d,$00,$01		; control = fire
	dc.b	$38,$00,$01		; alternate = fire
	dc.b	$02,$00,$04		; 1 = start 1
	dc.b	$03,$00,$08		; 2 = start 2
	dc.b	$06,$00,$10		; 5 = coin
	dc.b	0,0,0
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

; ------------------------------------------------------------------------------
; Fatal errors of the translated code
; ------------------------------------------------------------------------------

z80_badpc:
z80_badjump:
z80_unsupported:
	move	#$2700,sr
	bsr	restore_hardware
	pea	bad_text
	move	#9,-(sp)
	trap	#1
	addq	#6,sp
	move	#1,-(sp)
	trap	#1
	addq	#2,sp
	bra	quit

	include "galaga_render.s"
	include "galaga_sprites.s"
	include "galaga_stars.s"

; ------------------------------------------------------------------------------
; The translated programs (and their dispatch tables in the data section).

	include "../build/galaga_code.s"

	section text,code
	include "../tools/rtlib.s"

; ------------------------------------------------------------------------------
	section data,data
; ------------------------------------------------------------------------------

rom_names:
	dc.b	"gg1_1b.3p",0
	dc.b	"gg1_2b.3m",0
	dc.b	"gg1_3.2m",0
	dc.b	"gg1_4b.2l",0
	dc.b	"gg1_5b.3f",0
	dc.b	"gg1_7b.2c",0
	even
rom_places:
	dc.l	G_ROM1,G_ROM1+$1000,G_ROM1+$2000,G_ROM1+$3000,g_block,g3_rom

rom_error_text:
	dc.b	13,10
	dc.b	"Galaga: cannot read the arcade CPU ROM files",13,10
	dc.b	"gg1_1b.3p gg1_2b.3m gg1_3.2m gg1_4b.2l gg1_5b.3f gg1_7b.2c",13,10
	dc.b	"They have to be in the current folder. Press a key.",13,10,0

bad_text:
	dc.b	13,10,"Galaga: the translated program reached an unknown address.",13,10
	dc.b	"Press a key.",13,10,0

	include "../build/galaga_assets.s"

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
old_fa1f:	ds.b	1
old_fa21:	ds.b	1

quit_flag:	ds.b	1
vbl_busy:	ds.b	1
frame_ready:	ds.b	1		; the draw screen is complete, to be shown at the VBL
in_render:	ds.b	1		; drawing: the main CPU's registers are in main_ctx
	even
main_ctx:	ds.l	15
border_a:	ds.b	1
border_b:	ds.b	1
in0_kbd:	ds.b	1
in0_joy:	ds.b	1
in1_kbd:	ds.b	1
in1_joy:	ds.b	1
ikbd_state:	ds.b	1
joy0_state:	ds.b	1
joy1_state:	ds.b	1
in_turn:	ds.b	1		; a booting CPU runs with its registers live
current:	ds.b	1		; 0: the main CPU's code runs, 1: the sub CPU's
booted2:	ds.b	1		; the sub CPU reached its idle loop
cpu3_state:	ds.b	1
ctrl06_mode:	ds.b	1
g1_iff:		ds.b	1		; the CPUs' interrupt enable (ei / di)
g2_iff:		ds.b	1
	even
	ifd IOLOG
iolog_ptr:	ds.l	1
iolog_buf:	ds.b	512
iolog_end:
	endc
	even

frame_counter:	ds.l	1
vbl_sp:		ds.l	1
cnt_timer_a:	ds.w	1
cnt_timer_b:	ds.w	1
cnt_acia:	ds.w	1
cnt_vbl:	ds.w	1
cnt_skip:	ds.w	1
cnt_render:	ds.w	1
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
turn_sp:	ds.l	1
rnd_state:	ds.l	1
ctx2:		ds.l	16		; d0-d7, a0-a6, resume address

n51_state:
n51_mode:	ds.b	1		; 0 switches, 1 credits, 2 in game
n51_count:	ds.b	1
n51_coincred:	ds.b	1
n51_remap:	ds.b	1
n51_cpc:	ds.b	2		; coins per credit (two slots)
n51_crc:	ds.b	2		; credits per coin
n51_coins:	ds.b	2
n51_credits:	ds.b	1
n51_lastcoins:	ds.b	1
n51_lastbuttons:	ds.b	1
	ds.b	1
N51_SIZE = *-n51_state

	cnop 0,4
g_block:	ds.b	$18000		; [sub ROM 32K | RAM 32K | main ROM 32K]
g_ram = g_block+$8000
g3_rom:		ds.b	$1000		; the sound CPU's ROM (loaded, unused)
g1_dispatch_sw:	ds.l	65536
g2_dispatch_sw:	ds.l	65536

	ds.b	1024
own_stack_top:

	cnop 0,4
screens:
	ds.b	$10000			; alignment slack
	ds.b	$20000*3
