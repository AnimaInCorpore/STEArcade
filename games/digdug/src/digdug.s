; ------------------------------------------------------------------------------
;
; Dig Dug for the Atari STE
;
; The arcade's main, sub and sound Z80 programs are translated to 68000 code by
; tools/gen.py (engine/z80x.py); this file is the machine around them: STE video
; (320 x 277 with the borders removed, the game's 224 x 288 rotated picture), double
; buffering, the renderer (render.s, sprites.s), the custom I/O chips (06XX, the real 51XX
; and 53XX programs translated by engine/mb88x.py), input, and the schedule (as Galaga's):
;
;   The main CPU's program is the foreground thread.  At every VBL the main CPU's IRQ
;   handler runs (if the program enabled it), then the sub CPU's IRQ handler with the sub
;   CPU's own register set, then the sub CPU's EAROM command ($1DDC, its main loop's only
;   work) if one is pending, then the frame is drawn.  The 06XX's NMIs (transfers to and
;   from the 51XX / 53XX) run right at the control write, as often as the program keeps the
;   transfer going.  The boot handshake between the three CPUs (self-test results in RAM
;   flags; the self-tests themselves are patched out, machine.patch_tests) is run by giving
;   the sub CPU a turn at the main CPU's spin loops and at the VBL (z80_hook); the sound CPU's
;   part of it is done natively.  Once it has booted, its NMI handler (translated) runs twice
;   a VBL, its WSG registers become the YM2149's (snd_update, tools/sound.py).
;
; Memory: one block holds [sub ROM 32K | shared RAM 32K ($8000-$FFFF) | main ROM 32K];
; the main CPU's code addresses with a6 = its ROM and signed word offsets (the RAM lies
; below), the sub CPU's with a6 = its ROM and long offsets (the RAM above).  The
; registers $6800-$7FFF (latches, 06XX) are cells in each CPU's ROM half.  The EAROM
; ($B800-$B83F: cells in the RAM, g_earom_ctl) keeps its 64 bytes in earom_rom.
;
; The CPU ROMs dd1a.1-6 and dd1.7 (patched by machine.patch_tests) are embedded (rom_table).
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
CROP_TOP = 32				; the STE shows 277 of the 288 lines: from this buffer line on
					; (the picture starts at DISP_TOP = 32: its last 11 lines are lost)
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
G_EAROM = g_ram+$3800			; the EAROM window $B800
TOKEN = $0140				; $4001 on the Z80 stack, byte swapped

; Border removal: engine/rt/borders.s.  Its events come early and sync themselves to the video, so a Blitter pass
; may start at any time: none waits.  Passes longer than BLIT_PIECE words run in pieces (blit_go, there).

BD_PALETTE = 0
	include	"borders.s"

; the pads (engine/rt/jagpad.s): in0, in1 bits as in key_table (bytes 0-1 of each long); both pads play player 1
JP1_RIGHT = $02<<24
JP1_LEFT = $08<<24
JP1_UP = $01<<24
JP1_DOWN = $04<<24
JP1_B1 = $01<<16			; A, B, C: fire
JP1_B2 = $01<<16
JP1_B3 = $01<<16
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

	lea	g1_dispatch,a0		; the dispatch tables in the order the code uses them: one table of 65536 longs for the
	lea	g1_dispatch_sw,a1	; three CPUs (the index is the pc with its bytes swapped: the main CPU's pcs $0000-$3FFF and
	move	#TABLE_ENTRIES,d0	; its token $4001 take the columns $00-$40, the sub CPU's $0000-$1FFF and token the columns
	bsr	z80_init_dispatch	; $41-$60 and $81, the sound CPU's $0000-$0FFF and token $82-$91 and $C2: 256 KB, not 768)
	lea	g2_dispatch,a0
	lea	g2_dispatch_sw,a1
	move	#DISPATCH_ENTRIES2,d0
	bsr	dd_init_dispatch
	move.l	#g2_ret,TOKEN*4(a1)	; (the compact tables of these two end with their ROM)
	lea	g3_dispatch,a0
	lea	g3_dispatch_sw,a1
	move	#DISPATCH_ENTRIES3,d0
	bsr	dd_init_dispatch
	move.l	#g3_ret,TOKEN*4(a1)
	ifd RESETTRAP
	move.l	#reset_trap1,g1_dispatch_sw	; (-D RESETTRAP=1: a computed jump to $0000, the program restarting
	move.l	#reset_trap2,g2_dispatch_sw	; itself, ends in CRASH.TXT: vector 97 / 96, its stack the Z80's)
	endc

	; The sub CPU's context: registers 0, at its reset vector.

	lea	ctx2,a0
	moveq	#15,d0
.ctx:	clr.l	(a0)+
	dbf	d0,.ctx
	move.l	#g2_dispatch_sw,ctx2+4*12	; a4
	move.l	#g_block,ctx2+4*14		; a6
	move.l	#Y0000,ctx2+4*15		; resume

	; The sound CPU's context for its NMI handler: registers 0, SP = $8B80 (where its idle loop sets it).

	lea	ctx3,a0
	moveq	#15,d0
.ctx3:	clr.l	(a0)+
	dbf	d0,.ctx3
	move.l	#g3_dispatch_sw,ctx3+4*12	; a4
	move.l	#g3_ram+$0B80,ctx3+4*13		; a5
	move.l	#g3_block,ctx3+4*14		; a6
	move.b	#$FF,snd_expl_t		; (no explosion: the tables are Galaga's)
	bsr	snd_init

	st	n51_held		; (held in reset until the program releases latch $6823)
	lea	earom_rom,a0		; the EAROM: erased, its control as the chip's reset leaves it
	moveq	#15,d0
.earom:	move.l	#$FFFFFFFF,(a0)+
	dbf	d0,.earom
	move.b	#$12,earom_state
	; the 53XX's inputs: R0-R3 = the DIP switch banks A and B, low and high nibbles
	move.b	dswa,d0
	move.b	d0,d1
	and.b	#15,d0
	lsr.b	#4,d1
	move.b	d0,N53_state+N53_S_R
	move.b	d1,N53_state+N53_S_R+1
	move.b	dswb,d0
	move.b	d0,d1
	and.b	#15,d0
	lsr.b	#4,d1
	move.b	d0,N53_state+N53_S_R+2
	move.b	d1,N53_state+N53_S_R+3
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

; The I/O cells: the latches 0 (bss).  The DIP switches go to the 53XX (start: its R inputs).

init_cells:
	rts

dswa:	dc.b	$99			; 1 coin 1 credit (B), 20K and 60K bonus, 3 lives
dswb:	dc.b	$24			; 1 coin 1 credit (A), freeze off, demo sounds on, continue, upright, easy
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

	ifd RATE

; Measurement (-D RATE=N --debug --frames M): cnt_vbl and cnt_render every N VBLs,
; written to RATE.BIN when the program quits (renders per VBL = the frame rate / 50).

dump_rate:
	move.l	rate_ptr,d0
	bne.s	.some
	rts
.some:
	sub.l	#rate_buf,d0
	move.l	d0,d7
	clr	-(sp)			; Fcreate
	pea	rate_name
	move	#$3c,-(sp)
	trap	#1
	addq	#8,sp
	move	d0,d6
	pea	rate_buf		; Fwrite
	move.l	d7,-(sp)
	move	d6,-(sp)
	move	#$40,-(sp)
	trap	#1
	lea	12(sp),sp
	move	d6,-(sp)		; Fclose
	move	#$3e,-(sp)
	trap	#1
	addq	#4,sp
	rts

rate_name:
	dc.b	"RATE.BIN",0
	even

	endc

quit:
	ifd RATE
	bsr	dump_rate
	endc
	bsr	restore_hardware
	ifd DEBUG
	bsr	bd_report
	endc
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

	movem.l	dd_palette,d0-d7
	movem.l	d0-d7,$ffff8240.w

	clr.b	$ffff8260.w		; low resolution, 50 Hz (an NTSC desktop runs at 60: the border timing is for 50)
	move.b	#2,$ffff820a.w
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
	move	#2,$ffff8a30.w		; Destination Y increment
	move	#16,$ffff8a36.w		; X count: 16 words, 4096 lines = 128 KB
	move.l	d0,$ffff8a32.w
	move	#4096,$ffff8a38.w
	bra	blit_go			; (the interrupts run: in pieces)

; ------------------------------------------------------------------------------
; Interrupts
; ------------------------------------------------------------------------------

hbl:
	rte

; The VBL starts the frame: it switches the screen, starts the border timers, runs the
; two CPUs' IRQ handlers and draws.  The registers of the interrupted foreground thread
; are kept on the stack and restored at the end.

vbl:
	borders_vbl			; (first: Timer B counts the frame's lines)
	ifnd NOTHROTTLE
	and.b	#$70,$fffffa1d.w	; Timer D (81 us ticks) counts from this VBL (render
	clr.b	$fffffa25.w		; throttle); Timer C's bits stay
	or.b	#7,$fffffa1d.w
	endc
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
	bsr	jagpad_poll		; (the 51XX's inputs merge jp_in)
	ifd AUTOPLAY			; (-D AUTOPLAY=1: a scripted game for the Hatari captures: a coin and a start, then moves and pumps)
	bsr	autoplay
	endc
	bsr	n51_vbl			; the 51XX's frame: the vertical blank on its TC pin

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
	ifd SNDTEST
	bsr	sndtest			; (-D SNDTEST=<first VBL>: the command cells of the sound ids in sndtest_ids, one every 120 VBLs)
	endc

	ifd RATE
	addq	#1,rate_count		; every RATE VBLs: the VBL and render counters
	cmp	#RATE,rate_count
	blo.s	.no_rate
	clr	rate_count
	move.l	rate_ptr,a0
	move.l	a0,d0
	bne.s	.rate_on
	lea	rate_buf,a0		; the first sample
.rate_on:
	cmp.l	#rate_end,a0
	bhs.s	.no_rate
	move	cnt_vbl,(a0)+
	move	cnt_render,(a0)+
	move.l	a0,rate_ptr
.no_rate:
	endc

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
	tst.b	in_game			; a VBL inside the game's interrupts below (Timer B's handler lowers the IPL, Hatari): the
	bne	vbl_done		; interrupted code is a handler or the sub CPU's task, not the main thread: nothing
	st	in_game
	ifd FREEZEAT
	cmp.l	#FREEZEAT,frame_counter	; test: the game stands still from VBL FREEZEAT on,
	bhs	vbl_render		; the renderer goes on (screens of two builds compared)
	endc

	; Main CPU IRQ (IM 1: rst $38) with the interrupted registers, if enabled.  Its
	; register state afterwards is dropped: the handler restores every Z80 register
	; itself, and the interrupted code may hold a half-done value in d5 / d7.  While
	; the runtime renders (this VBL interrupted the renderer, not the main CPU), the
	; main CPU's registers are in main_ctx.

	btst	#0,G_IO1+$6820		; (the latches take bit 0 of the byte written)
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
	btst	#0,G_IO2+$6821
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

	; The sub CPU's main loop ($0078: call $1DDC, jr $0078) does its only work when the main CPU left a command in $9B3D
	; (the EAROM: load, save, check): once a frame, after its IRQ handler, as the reference does (run_foreground2).

	tst.b	booted2
	beq.s	.no_fg2
	tst.b	in_fg2			; (a nested VBL: the task is running)
	bne.s	.no_fg2
	tst.b	g_ram+$1B3D
	beq.s	.no_fg2
	st	in_fg2
	clr.b	g2_iff			; (a VBL during the task - Timer B's handler lowers the IPL - must not start the sub CPU's IRQ
					; handler on the registers of the task: the IRQ waits for the next VBL)
	movem.l	ctx2,d0-d7/a0-a6
	move.w	#TOKEN,-(a5)
	move.l	#.after_fg2,g2_ret_to
	jmp	Y1DDC
.after_fg2:
	movem.l	d0-d7/a0-a6,ctx2
	clr.b	in_fg2
	st	g2_iff
	chk_sp	21
.no_fg2:

	ifnd NOSOUND			; (-D NOSOUND=1: the sound CPU stays idle, the cost of the sound measured)
	bsr	g_sound_frame		; the sound CPU's NMIs, the YM
	endc
	chk_sp	23

	bsr	g_boot_turns		; a booting CPU waiting for the main CPU gets on
	chk_sp	22
	clr.b	in_game

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
	move	bd_fallbacks,256(a0)
	move	bd_late_low,512(a0)
	move	cnt_vbl,768(a0)
	move	cnt_render,1024(a0)
	addq	#1,cnt_render
	endc
	ifnd NOTHROTTLE
	bsr	throttle_start
	endc
	move	#$2300,sr
	bsr	render_frame
	move	#$2400,sr
	ifnd NOTHROTTLE
	bsr	throttle_update
	endc
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

	ifd SNDTEST

; tools/sound_mame.py's test in Hatari (tools/sound_hatari.py): from VBL SNDTEST on, every 120 VBLs one command cell of the
; sound CPU is set (the main CPU's cell for the sound id, $9A80 + id), the VBL before bit 1 of $8657 is cleared as there.
sndtest:
	move.l	frame_counter,d0
	sub.l	#SNDTEST,d0
	bmi.s	.none
	divu	#120,d0
	swap	d0			; the VBL in the piece (high word of divu: the remainder)
	cmp	#119,d0
	bne.s	.cell
	bclr	#1,g_ram+$0657
	rts
.cell:	tst	d0
	bne.s	.none
	swap	d0			; the piece
	cmp	#sndtest_n,d0
	bhs.s	.none
	lea	sndtest_ids,a0
	moveq	#0,d1
	move.b	(a0,d0.w),d1
	lea	g_ram+$1A00,a1
	move.b	#1,(a1,d1.w)
.none:	rts

sndtest_ids:	dc.b	$89,$8A,$8B,$8C,$8D,$8E,$8F,$92,$93	; the ids 9-15, 18, 19
sndtest_n = *-sndtest_ids
	even
	endc

	ifd AUTOPLAY
autoplay:
	move.l	frame_counter,d0
	moveq	#0,d1			; pressed bits of in1 (active high: the VBL inverts), d2: of in0
	moveq	#0,d2
	cmp.l	#AUTOPLAY,d0
	blo.s	.set
	move.l	d0,d3
	sub.l	#AUTOPLAY,d3
	cmp.l	#6,d3			; the coin
	bhs.s	.c1
	moveq	#$10,d1
.c1:	cmp.l	#40,d3			; the start
	blo.s	.m
	cmp.l	#46,d3
	bhs.s	.m
	moveq	#4,d1
.m:	cmp.l	#400,d3			; then moves (right / down / left / up in turn) and the pump
	blo.s	.set
	move.l	d3,d4
	lsr.l	#5,d4
	and.l	#3,d4
	move.b	.dirs(pc,d4.w),d2
	move.l	d3,d4
	and.l	#15,d4
	cmp.l	#4,d4
	bhs.s	.set
	or.b	#1,d1
.set:	move.b	d1,in1_kbd
	move.b	d2,in0_kbd
	rts
.dirs:	dc.b	2,4,8,1
	endc

; The token on a Z80 stack returns here: back to whoever started the handler.

g1_ret:
	move.l	g1_ret_to,-(sp)
	rts

g2_ret:
	move.l	g2_ret_to,-(sp)
	rts

g3_ret:
	move.l	g3_ret_to,-(sp)
	rts

; The sound CPU's two NMIs of a frame (lines 64 and 192), once it has booted, while its NMION ($6822) is off.  It
; has a RAM of its own (g3_ram, as the others' addresses $8000-$9FFF); what it shares with the other CPUs is copied in
; before and out afterwards (nothing else runs in between): the bytes $8657 and $87CF (game state it reads), $8A00-$8A47
; (the boot flags) and the page $9A80-$9B7F (the sound commands the others write, the status it writes).  Then the WSG
; to the YM.  Clobbers every register.

g_sound_frame:
	cmp.b	#2,cpu3_state
	bne	.no_nmi3
	; The shared RAM the sound CPU uses: the flags of the game it reads ($8401, $8646, $8657, $87CF) and $9A80-$9B7F (the
	; commands the main CPU writes, $9B1B / $9B33 / $9B3D among them, and the sound CPU's own state), 256 bytes each way
	; with movem.l.  (Of $8A00-$8A47 the sound CPU only writes $8A40-$8A47 at its boot and the main CPU reads none of those:
	; ref/sndtrace.py lists what a scripted game of 6000 frames touches.)
	move.b	g_ram+$0401,g3_ram+$0401
	move.b	g_ram+$0646,g3_ram+$0646
	move.b	g_ram+$0657,g3_ram+$0657
	move.b	g_ram+$07CF,g3_ram+$07CF
	lea	g_ram+$1A80,a0
	lea	g3_ram+$1A80,a1
	moveq	#8-1,d6
.in:	movem.l	(a0)+,d0-d5/a2-a3
	movem.l	d0-d5/a2-a3,(a1)
	lea	32(a1),a1
	dbf	d6,.in
	move.b	#2,nmi3_left
.nmi3:	btst	#0,g3_block+$6822
	bne.s	.nmi3_done
	movem.l	ctx3,d0-d7/a0-a6
	move.w	#TOKEN,-(a5)
	move.l	#.after,g3_ret_to
	jmp	X0066
.after:
	movem.l	d0-d7/a0-a6,ctx3
	subq.b	#1,nmi3_left
	bne.s	.nmi3
.nmi3_done:
	lea	g3_ram+$1A80,a0
	lea	g_ram+$1A80,a1
	moveq	#8-1,d6
.out:	movem.l	(a0)+,d0-d5/a2-a3
	movem.l	d0-d5/a2-a3,(a1)
	lea	32(a1),a1
	dbf	d6,.out
.no_nmi3:
	bra	snd_update


; ------------------------------------------------------------------------------
; Sound: the WSG (the sound CPU's $6800-$681F cells) on the YM2149, a square wave per voice, and the 54XX's explosion
; as noise on channel C.  tools/sound.py is the same in Python (ym_image, Explosion), sound_test.py compares them.
; ------------------------------------------------------------------------------

; at the start: the YM silent, its shadow
snd_init:
	lea	snd_ym,a0
	moveq	#0,d1
.y:	move.b	d1,$ffff8800.w
	moveq	#0,d0
	cmp.b	#7,d1
	bne.s	.w
	moveq	#-1,d0			; (mixer: everything off, both ports outputs)
.w:	move.b	d0,$ffff8802.w
	move.b	d0,(a0)+
	addq.b	#1,d1
	cmp.b	#11,d1
	blo.s	.y
	rts

snd_off:
	moveq	#8,d0
.v:	move.b	d0,$ffff8800.w
	clr.b	$ffff8802.w
	addq.b	#1,d0
	cmp.b	#11,d0
	blo.s	.v
	rts

; One game frame: the explosion's envelope steps, the YM's registers 0-10 from the WSG cells.  Clobbers d0-d7 / a0-a2.
snd_update:
	lea	g3_block+$6800,a0	; nothing to do when the WSG is as last time and no explosion sounds
	lea	snd_wsg,a1
	tst.b	snd_expl_t
	bpl.s	.changed
	moveq	#8-1,d0
.cmp:	cmpm.l	(a0)+,(a1)+
	dbne	d0,.cmp
	bne.s	.changed
	rts
.changed:
	lea	g3_block+$6800,a0
	lea	snd_wsg,a1
	moveq	#8-1,d0
.keep:	move.l	(a0)+,(a1)+
	dbf	d0,.keep
	lea	snd_buf,a2
	clr.l	(a2)
	clr.l	4(a2)
	clr.w	8(a2)
	clr.b	10(a2)
	moveq	#$3F,d6			; the mixer: bit k tone off, bit k + 3 noise off
	lea	g3_block+$6800,a0
	moveq	#0,d5			; the voice
.voice:	move.w	d5,d4
	mulu	#5,d4			; its register offset
	moveq	#0,d0			; the frequency
	tst.w	d5
	bne.s	.f1
	move.b	$10(a0),d0
	and.w	#15,d0
.f1:	moveq	#4,d2			; nibbles $11-$14 of the voice: << 4, 8, 12, 16
	lea	$11(a0,d4.w),a1
.fn:	moveq	#15,d1
	and.b	(a1)+,d1
	lsl.l	d2,d1
	add.l	d1,d0
	addq.w	#4,d2
	cmp.w	#20,d2
	blo.s	.fn
	moveq	#15,d1
	and.b	$15(a0,d4.w),d1		; the volume
	beq.s	.next
	tst.l	d0
	beq.s	.next
	moveq	#7,d3
	and.b	5(a0,d4.w),d3		; the waveform
	move.w	#4095,d2
	cmp.l	#334,d0
	blo.s	.per
	moveq	#20,d2
	cmp.l	#$FFFF,d0
	bhi.s	.per
	move.l	#DIVIDEND,d2
	divu	d0,d2
.per:	lea	snd_shift,a1
	move.b	(a1,d3.w),d7
	lsr.w	d7,d2
	bne.s	.p1
	moveq	#1,d2
.p1:	lsl.w	#4,d3
	add.w	d1,d3
	lea	snd_level,a1
	move.b	(a1,d3.w),d1		; the level
	beq.s	.next
	move.w	d5,d3
	add.w	d3,d3
	move.b	d2,(a2,d3.w)		; the period
	lsr.w	#8,d2
	move.b	d2,1(a2,d3.w)
	move.b	d1,8(a2,d5.w)
	bclr	d5,d6			; tone on
.next:	addq.w	#1,d5
	cmp.w	#3,d5
	blo	.voice
	; the explosion
	moveq	#0,d0
	move.b	snd_expl_t,d0
	bmi.s	.noexpl
	lea	snd_expl_env,a1
	move.b	(a1,d0.w),d1
	addq.b	#1,d0
	cmp.b	#SND_EXPL_LEN,d0
	blo.s	.t
	moveq	#-1,d0
.t:	move.b	d0,snd_expl_t
	cmp.b	10(a2),d1
	bls.s	.noexpl
	clr.b	4(a2)
	clr.b	5(a2)
	move.b	d1,10(a2)
	bset	#2,d6			; channel C: tone off, noise on
	bclr	#5,d6
	move.b	#SND_NOISE,6(a2)
.noexpl:
	or.b	#$C0,d6
	move.b	d6,7(a2)
	; the registers that changed (no interrupt handler of the port touches the YM)
	lea	snd_ym,a0
	moveq	#0,d1
.wr:	move.b	(a2)+,d0
	cmp.b	(a0),d0
	beq.s	.same
	move.b	d0,(a0)
	move.b	d1,$ffff8800.w
	move.b	d0,$ffff8802.w
.same:	addq.l	#1,a0
	addq.b	#1,d1
	cmp.b	#11,d1
	blo.s	.wr
	rts

DIVIDEND = 1365333			; 125000 * 2^20 / 96000: the YM period of a WSG frequency
	include	"sound_tables.s"

	borders_handlers
	borders_blit_go
	borders_report

; ------------------------------------------------------------------------------
; The boot schedule.  z80_hook is reached from the translated code at the spin loops
; of the boot handshake (d7 = the Z80 pc of the instruction): the main CPU gives the
; others a turn and continues; the sub CPU, running in a turn, hands back.  A turn
; runs a CPU from where it stopped to its next spin loop or its idle loop ($0078).
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
	cmp.w	#$0078,d7		; its main loop: the boot is done
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
	btst	#0,G_IO1+$6823
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

; The sound CPU's boot, natively (patched self-test: $067F posts $FF at once): it posts its result in $8A01, waits for
; the main CPU to clear it, then clears $8A40-$8A47 and its work area $9A80-$9B7F, copies 21 bytes of its ROM ($07E7) to
; $9B0A, enables its NMI ($6822 = 0) and idles ($00B0: ld sp,$8B80 / jr $00B0) for good.

g_cpu3_turn:
	move.b	cpu3_state,d0
	bne.s	.posted
	tst.b	g_ram+$0A01
	bne.s	.wait
	move.b	#$ff,g_ram+$0A01
	move.b	#1,cpu3_state
.wait:	rts
.posted:
	cmp.b	#1,d0
	bne.s	.wait
	tst.b	g_ram+$0A01
	bne.s	.wait
	lea	g_ram+$0A40,a0
	clr.l	(a0)+
	clr.l	(a0)
	lea	g_ram+$1A80,a0
	moveq	#256/4-1,d1
	moveq	#0,d0
.clear:	move.l	d0,(a0)+
	dbf	d1,.clear
	lea	g3_rom+$07E7,a0
	lea	g_ram+$1B0A,a1
	moveq	#21-1,d1
.copy:	move.b	(a0)+,(a1)+
	dbf	d1,.copy
	clr.b	g3_block+$6822
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
; control register ($7100, hooked after `ld ($7100),a`): bit 4 read/write, bits 0-1 the
; chip (0: 51XX, 1: the 53XX; Dig Dug uses $A1: write to the 51XX, $71: read the 51XX, $D2: read the 53XX), bits 5-7
; the clock, which pulses an NMI per byte; the NMI handler moves a byte between $7000 and memory with `ldi` and stops
; the transfer with control = $10 when done.  Here the handler runs right away, as often as the program keeps the clock
; going: a read puts the chip's byte into the $7000 cell first, a write takes it from there afterwards.
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

; The transfer runs right here, one clock period a pass, as tools/machine.py ctrl06_port: the R/W line and the chip
; selects; the NMI handler (a read's first pulse is suppressed: the chip puts out its byte first); the chips after the
; handler's access; the chip selects off.  The handler's stop ($10) comes back here nested and only sets the register.
; A VBL during a transfer leaves the 51XX's frame to the end of the pass (n51_tick).

g_ctrl06:
	tst.b	n51_busy
	bne	.nested
	move.l	g1_ret_to,-(sp)		; (the IRQ handler we may be in returns through it)
	st	n51_busy
	iolog	1,G_IO1+$7100
	bsr	n51_check
	st	n51_first
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
	move.b	ctrl06_mode,d7
	lsr.b	#1,d7
	and.b	#1,d7
	bsr	N53_set_irq
	btst	#4,ctrl06_mode
	beq	.nmi			; write
	tst.b	n51_first
	beq.s	.byte
	bsr	n51_run			; a read's first pulse: no NMI
	bra	.rise
.byte:	moveq	#-1,d7			; the byte the handler reads: the selected chips' latches ANDed
	btst	#0,ctrl06_mode
	beq.s	.n53
	and.b	N51_state+N51_S_PORTO,d7
.n53:	btst	#1,ctrl06_mode
	beq.s	.ff
	and.b	N53_state+N53_S_PORTO,d7
.ff:	iolog	3,d7
	lea	G_IO1+$7000,a0		; the port is the whole $7000-$70FF range: the handler's pointer walks through it
	move.b	d7,(a0)+
	move.b	d7,(a0)+
	move.b	d7,(a0)+
	move.b	d7,(a0)+
	move.b	d7,(a0)+
	move.b	d7,(a0)+
	move.b	d7,(a0)+
	move.b	d7,(a0)+
	move.b	d7,(a0)+
	move.b	d7,(a0)+
	move.b	d7,(a0)+
	move.b	d7,(a0)+
	move.b	d7,(a0)+
	move.b	d7,(a0)+
	move.b	d7,(a0)+
	move.b	d7,(a0)+
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
	move.l	d2,d7			; the handler's `ldi` wrote through de' (after its exx back the upper
	swap	d7			; word of d2: z80x.FAST keeps the alternate registers there),
	subq.w	#1,d7			; one past the byte
	move.b	(a6,d7.w),d7
	iolog	2,d7
	btst	#0,ctrl06_mode
	beq.s	.after			; (the 53XX has no write input)
	move.b	d7,N51_state+N51_S_PORTO
.after:	bsr	n51_run			; the chips take this pulse
.rise:	moveq	#0,d7			; the chip selects off
	bsr	N51_set_irq
	bsr	N53_set_irq
	bsr	n51_run_low
	clr.b	n51_first
	bsr	n51_late
	bra	.loop
.done:
	moveq	#0,d7
	bsr	N51_set_irq
	bsr	N53_set_irq
	bsr	n51_run_low
	clr.b	n51_busy
	bsr	n51_late
	move.l	(sp)+,g1_ret_to
.nested:
	rts

; ------------------------------------------------------------------------------
; Natives (tools/gen.py NATIVES: the translation of the sub CPU jumps here at the routine's pc; tools/native_test.py checks
; them against the Z80 reference).  Registers as engine/z80x.py keeps them (d0.b A, d1 BC with B in the low byte, d2.w DE,
; d3.w HL; the sub CPU's a0-a2 are BC' DE' HL', a6 its block).
;
; nat_y0e4c: the sub CPU's sprite position copy, $0E4C-$0E82 (6,300 cycles a frame translated): from the table at $9880 to
; the sprite RAM at $9380, 64 entries of two bytes: the first byte as it is, the second + $37 (the flipped cabinet, $8400
; bits 1 and 2 both set: $F2 - first, $27 - second); nothing when $87F0 bit 3 is set.  Leaves what the Z80 code would:
; HL = $9900, DE = $9400, B = 0, A the last byte written (with $87F0 set: HL = $9880, DE = $9380, B = $40, A = $87F0), and
; continues at the `ret` ($0E73).  The flags are not kept (the caller, the call at $0090, reads none).
; ------------------------------------------------------------------------------

nat_y0e4c:
	move.b	g_ram+$07F0,d0
	move.w	#$9880,d3
	move.w	#$9380,d2
	move.b	#$40,d1
	btst	#3,d0
	bne	Y0E73
	movem.l	a0-a1,-(a7)
	lea	g_ram+$1880,a0
	lea	g_ram+$1380,a1
	move.b	g_ram+$0400,d0
	btst	#1,d0
	beq.s	.plain
	btst	#2,d0
	beq.s	.plain
	moveq	#64-1,d5		; the flipped cabinet
.flip:	move.b	#$F2,d7
	sub.b	(a0)+,d7
	move.b	d7,(a1)+
	move.b	#$27,d7
	sub.b	(a0)+,d7
	move.b	d7,(a1)+
	dbf	d5,.flip
	bra.s	.done
.plain:	moveq	#8-1,d5			; 8 x 8 entries
.p8:	rept	8
	move.w	(a0)+,d7
	add.b	#$37,d7
	move.w	d7,(a1)+
	endr
	dbf	d5,.p8
.done:	move.b	d7,d0
	movem.l	(a7)+,a0-a1
	move.w	#$9900,d3
	move.w	#$9400,d2
	clr.b	d1
	bra	Y0E73

; Scatters the entries of a compact dispatch table (pc order, a0, d0 entries) that are code into the shared table at a1
; (z80_init_dispatch of the main CPU filled it with z80_badpc): the other CPUs' unused entries must not overwrite the columns
; of the CPU before.

dd_init_dispatch:
	move.l	#z80_badpc,d3
	moveq	#0,d1			; pc
.scatter:
	move.l	(a0)+,d4
	cmp.l	d3,d4
	beq.s	.skip
	move	d1,d2
	ror	#8,d2
	and.l	#$ffff,d2
	lsl.l	#2,d2
	move.l	d4,(a1,d2.l)
.skip:	addq	#1,d1
	cmp	d0,d1
	blo.s	.scatter
	rts

; A plain data write ($7000, hooked): into the 51XX's latch if the transfer is a write to it.

g_data06:
	move.b	G_IO1+$7100,d7
	btst	#4,d7
	bne.s	.done
	btst	#0,d7
	beq.s	.done
	move.b	G_IO1+$7000,N51_state+N51_S_PORTO
.done:
	rts

; The main CPU wrote $6821 (the sub CPU's IRQ enable): the latch is one bit for all CPUs, the sub CPU reads its own cell.

g1_latch1:
	move.b	G_IO1+$6821,G_IO2+$6821
	rts

; ------------------------------------------------------------------------------
; The EAROM (ER2055, tools/machine.py ER2055): the sub CPU's `ld ($B840),a` (hooked) is the control, d0 the byte: CK
; (bit 0), /C1 (bit 1), C2 (bit 2), CS1 (bit 3).  The address is the one the last store to $B800-$B83F had
; (earom_addr, set by the translated stores, gen.py Emitter); the data latch is the cell there (G_EAROM): a read
; clocks the chip's byte into it.  Keeps every register and the CCR.
; ------------------------------------------------------------------------------

g_earom_ctl:
	move	sr,-(sp)
	movem.l	d0-d3/a0-a1,-(sp)
	moveq	#0,d1
	move.b	d0,d1			; the control byte
	move.b	earom_state,d2		; (before)
	move.b	d2,d3
	and.b	#1,d3			; CK stays
	or.b	#16,d3			; CS2 is tied on
	btst	#3,d1
	beq.s	.c1
	or.b	#8,d3			; CS1
.c1:	btst	#1,d1
	bne.s	.c2
	or.b	#2,d3			; C1 = not bit 1
.c2:	btst	#2,d1
	beq.s	.set
	or.b	#4,d3			; C2
.set:	move.b	d3,earom_state
	move.b	d3,d0
	and.b	#24,d0
	cmp.b	#24,d0
	bne.s	.clk
	cmp.b	d2,d3
	beq.s	.clk
	bsr.s	.update
.clk:	move.b	earom_state,d2
	move.b	d2,d3
	btst	#0,d1
	beq.s	.low
	or.b	#1,d3			; the clock goes high: nothing
	move.b	d3,earom_state
	bra.s	.done
.low:	and.b	#$FE,d3
	move.b	d3,earom_state
	move.b	d3,d0
	and.b	#24,d0
	cmp.b	#24,d0
	bne.s	.done
	cmp.b	d2,d3
	beq.s	.done
	btst	#1,d3			; C1: a read
	beq.s	.upd
	moveq	#0,d0
	move.b	earom_addr,d0
	lea	earom_rom,a0
	lea	G_EAROM,a1
	move.b	(a0,d0.w),(a1,d0.w)
.upd:	bsr.s	.update
.done:	movem.l	(sp)+,d0-d3/a0-a1
	move	(sp)+,ccr
	rts

.update:
	moveq	#0,d0
	move.b	earom_addr,d0
	lea	earom_rom,a0
	move.b	earom_state,d2
	and.b	#6,d2			; C1 | C2
	bne.s	.u1
	lea	G_EAROM,a1		; write (an erase is needed first: AND with the old byte)
	move.b	(a1,d0.w),d2
	and.b	d2,(a0,d0.w)
	rts
.u1:	cmp.b	#4,d2
	bne.s	.ur
	move.b	#$FF,(a0,d0.w)		; erase
.ur:	rts

; ------------------------------------------------------------------------------
; 51XX and 53XX: the chips' own programs, translated (engine/mb88x.py -> build/digdug/n51_code.s, n53_code.s): they run
; from wait point to wait point at their events, as tools/machine.py's event-driven model (DigDug(mcu_events=True)).
; Every routine keeps every register.
; ------------------------------------------------------------------------------

; The reset line is latch $6823 (bit 0, 0: held); a release resets the chips and runs their boot to the main loops.

n51_check:
	btst	#0,G_IO1+$6823
	bne.s	.on
	st	n51_held
	rts
.on:	tst.b	n51_held
	beq.s	.r
	clr.b	n51_held
	bsr	N51_reset
	bsr	N51_run
	bsr	N53_reset
	bsr	N53_run
.r:	rts

n51_run:
	tst.b	n51_held
	bne.s	.r
	bsr	N53_run
	bra	N51_run
.r:	rts

; After the chip selects went low: only the 51XX's coinage command's wait for that ($00D) and the 53XX's transfer wait
; ($359) go on; anywhere else the chips would stop again at once (the run is left out: the event model's run changes
; nothing there).

n51_run_low:
	cmp.l	#N51_00D,N51_state+N51_S_RESUME
	beq.s	n51_run
	cmp.l	#N53_359,N53_state+N53_S_RESUME
	beq.s	n51_run
	rts

; At the VBL: the 51XX's TC pin goes high and low (the vertical blank counts), the frame body runs with this frame's
; inputs.  During a transfer it waits for the end of the pass.

n51_vbl:
	tst.b	n51_busy
	bne.s	.later
	bra.s	n51_frame
.later:	st	n51_tick
	rts

n51_late:
	tst.b	n51_tick
	beq.s	.r
	clr.b	n51_tick
	bra.s	n51_frame
.r:	rts

n51_frame:
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
	moveq	#1,d7			; (the rising edge counts nothing: no run)
	bsr	N51_set_tc
	moveq	#0,d7
	bsr	N51_set_tc
	bsr	n51_run
	movem.l	(sp)+,d6-d7
	rts

	include	"n51_code.s"
	include	"n53_code.s"

; ------------------------------------------------------------------------------
; Keyboard / joystick (IKBD): the pressed bits of in0 (joystick) and in1 (buttons)
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
.j2:	btst	#0,d1			; up
	beq	.j2a
	bset	#0,d0
.j2a:	btst	#1,d1			; down
	beq	.j2b
	bset	#2,d0
.j2b:	move.b	d0,in0_joy
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
	dc.b	$48,$01,$00		; up
	dc.b	$50,$04,$00		; down
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

; ------------------------------------------------------------------------------
; Fatal errors of the translated code
; ------------------------------------------------------------------------------

	ifd RESETTRAP
reset_trap1:
	moveq	#97,d0
	bra.s	reset_trap
reset_trap2:
	moveq	#96,d0
reset_trap:
	move	#$2700,sr
	move.l	a5,sp			; (the dump's stack words: the Z80 stack, return addresses byte swapped)
	bra	crash_common
	endc

; A Z80 pc without translated code (the dispatch table's default): CRASH.TXT with vector 98, d7 = the byte swapped
; pc times 4, a4 = the dispatch table of the CPU (g1/g2/g3_dispatch_sw), the stack words the Z80's (a5, return
; addresses byte swapped).
z80_badpc:
z80_badjump:
z80_unsupported:
	move	#$2700,sr
	moveq	#98,d0
	move.l	a5,sp
	bra	crash_common

	include "render.s"
	include "sprites.s"

; ------------------------------------------------------------------------------
; The translated programs (and their dispatch tables in the data section).

	include "digdug_code.s"

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
	even

	include "digdug_assets.s"

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
vbl_busy:	ds.b	1
frame_ready:	ds.b	1		; the draw screen is complete, to be shown at the VBL
in_render:	ds.b	1		; drawing: the main CPU's registers are in main_ctx
	even
main_ctx:	ds.l	15
	borders_vars
in0_kbd:	ds.b	1
in0_joy:	ds.b	1
in1_kbd:	ds.b	1
in1_joy:	ds.b	1
	ikbd_vars
joy0_state:	ds.b	1
joy1_state:	ds.b	1
in_turn:	ds.b	1		; a booting CPU runs with its registers live
current:	ds.b	1		; 0: the main CPU's code runs, 1: the sub CPU's
booted2:	ds.b	1		; the sub CPU reached its idle loop
cpu3_state:	ds.b	1
ctrl06_mode:	ds.b	1
in_game:	ds.b	1		; the VBL's game interrupts run (a nested VBL does nothing)
in_fg2:		ds.b	1		; the sub CPU's EAROM task runs
g1_iff:		ds.b	1		; the CPUs' interrupt enable (ei / di)
g2_iff:		ds.b	1
	even
	ifd IOLOG
iolog_ptr:	ds.l	1
	ifnd IOLOGSIZE
IOLOGSIZE = 512
	endc
iolog_buf:	ds.b	IOLOGSIZE
iolog_end:
	endc
	even

frame_counter:	ds.l	1
vbl_sp:		ds.l	1
cnt_acia:	ds.w	1
cnt_vbl:	ds.w	1
cnt_skip:	ds.w	1
cnt_render:	ds.w	1
	ifd RATE
rate_count:	ds.w	1
rate_ptr:	ds.l	1
rate_buf:	ds.l	1024
rate_end:
	endc
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
ctx3:		ds.l	16		; the sound CPU's registers for its NMI handler
g3_ret_to:	ds.l	1
snd_wsg:	ds.b	32		; the WSG cells at the last snd_update
snd_buf:	ds.b	12		; the YM registers of this frame
snd_ym:		ds.b	12		; the YM2149's registers 0-10 as written
nmi3_left:	ds.b	1
snd_expl_t:	ds.b	1		; the explosion: its frame of snd_expl_env, $FF off
earom_state:	ds.b	1		; the EAROM's control lines (CK 1, C1 2, C2 4, CS1 8, CS2 16)
earom_addr:	ds.b	1		; the address of the last store to the window (gen.py)
earom_de:	ds.w	1		; DE before a block instruction that writes the window (gen.py)
earom_rom:	ds.b	64		; the EAROM's bytes
	even

n51_held:	ds.b	1		; the 51XX and 53XX are in reset (latch $6823 is 0)
n51_busy:	ds.b	1		; a transfer runs (g_ctrl06)
n51_first:	ds.b	1		; its first pulse
n51_tick:	ds.b	1		; a VBL came during it: the 51XX's frame is due
	include	"n51_bss.s"
	include	"n53_bss.s"

	cnop 0,4
g_block:	ds.b	$18000		; [sub ROM 32K | RAM 32K | main ROM 32K]
g_ram = g_block+$8000
g3_block:	ds.b	$10000		; the sound CPU: its ROM, its I/O cells (the WSG at $6800), its RAM at + $8000
g3_rom = g3_block
g3_ram = g3_block+$8000
g_dispatch_sw:	ds.l	65536			; (see the start: the three CPUs' dispatch tables side by side, in columns)
g1_dispatch_sw = g_dispatch_sw
g2_dispatch_sw = g_dispatch_sw+4*$41
g3_dispatch_sw = g_dispatch_sw+4*$82

	ds.b	2048
own_stack_top:

	cnop 0,4
screens:
	ds.b	$10000			; alignment slack
	ds.b	$20000*3
