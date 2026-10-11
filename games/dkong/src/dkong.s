; ------------------------------------------------------------------------------
;
; Donkey Kong for the Atari STE
;
; The arcade Z80 program is translated to 68000 code by tools/gen.py (engine/z80x.py);
; this file is the machine around it: STE video (320 x 256 with top and bottom
; border removed), double buffering, tile and sprite drawing, input, sound (sound.s).
;
; The four CPU ROMs (c_5et_g.bin c_5ct_g.bin c_5bt_g.bin c_5at_g.bin) are embedded:
; rom_table, build/dkong/rom_cpu.rom.
;
; ------------------------------------------------------------------------------

BUSY = %10000000
HOG = %01000000
NFSR = %01000000

STRIDE = 256				; bytes per line, 512 pixel virtual screen
GAME_X = 24				; byte offset of the game area in a line (3 chunks)
VISIBLE_ROWS = 28			; arcade tile rows 2..29
MARK_ROWS = 36				; 8 pixel rows of tile_marks (sprites.s): 32 shown, sprites may hang over
MARK_SIZE = MARK_ROWS*8
KEY_ESC = $01

; The VBL's Timer A for the top border when the last frame's bottom border did not start it (borders.s): TA_DATA *
; 20.3 us after the VBL, in scanline 31; the handler waits for the next scanline start.

	ifnd TA_DATA
TA_DATA = 98
	endc
	ifnd TA_NOPS
TA_NOPS = 84
	endc

	ifnd FRAMES
FRAMES = 0				; quit after n frames (0 = never), for measurements
	endc

; Border removal: engine/rt/borders.s.  Its events come early and sync themselves to the video, so a Blitter pass
; may start at any time: none waits.  Passes longer than BLIT_PIECE words run in pieces (blit_go, there).

BD_PALETTE = 0
	include	"borders.s"

; the pads (engine/rt/jagpad.s): IN0, IN2 bits as in key_table (bytes 0-1 of each long); both pads play player 1
JP1_RIGHT = $01<<24
JP1_LEFT = $02<<24
JP1_UP = $04<<24
JP1_DOWN = $08<<24
JP1_B1 = $10<<24			; A, B, C: jump
JP1_B2 = $10<<24
JP1_B3 = $10<<24
JP2_RIGHT = JP1_RIGHT
JP2_LEFT = JP1_LEFT
JP2_UP = JP1_UP
JP2_DOWN = JP1_DOWN
JP2_B1 = JP1_B1
JP2_B2 = JP1_B2
JP2_B3 = JP1_B3
JP_START1 = $04<<16
JP_START2 = $08<<16
JP_COIN1 = $80<<16
JP_COIN2 = JP_COIN1			; (one coin slot)
	include	"jagpad.s"
	include	"ikbd.s"

stage	macro
	ifd DEBUG
	move	#\1,$ffff8240.w
	endc
	endm

	section text,code

; ------------------------------------------------------------------------------
; Start
; ------------------------------------------------------------------------------

start:
	clr.l	-(sp)			; Super
	move	#$20,-(sp)
	trap	#1
	addq	#6,sp
	move.l	d0,old_ssp
	lea	own_stack_top,sp
	stage	$f00

	bsr	load_roms

	stage	$ff0
	bsr	init_hardware
	stage	$0ff
	bsr	init_video
	bsr	init_render
	ifd DEBUG
	move	dk_palette,$ffff8240.w	; stage colours off again
	endc
	ifd TIMES
	move.l	#frame_times,frame_times_ptr
	endc

	; Start the Z80 main thread.

	lea	z80_dispatch,a0		; the dispatch table in the order the code uses it
	lea	z80_dispatch_sw,a1
	move	#TABLE_ENTRIES,d0
	bsr	z80_init_dispatch

	lea	z80_dispatch_sw,a4
	lea	z80_block,a6
	move.b	#$80,$7f80(a6)		; DSW0 before the first VBL
	lea	$6c00(a6),a5
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
	bclr	#3,$fffffa17.w		; automatic end of interrupt

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

	bsr	init_sound

	; IKBD: joystick event reporting, mouse off.

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
	bsr	stop_sound

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
.w1:	btst	#1,$fffffc00.w		; IKBD: mouse relative again
	beq.s	.w1
	move.b	#$08,$fffffc02.w
	endc

	move	#$2300,sr
	rts

quit:
	ifd TIMES
	bsr	dump_times
	endc
	bsr	restore_hardware
	ifd DEBUG
	bsr	bd_report
	endc

	move.l	old_ssp,-(sp)		; Super off
	move	#$20,-(sp)
	trap	#1
	addq	#6,sp

	clr	-(sp)
	trap	#1

; ------------------------------------------------------------------------------
; Video
; ------------------------------------------------------------------------------

init_video:
	; 64 KiB aligned screens: background (tiles only), two draw buffers.

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

	movem.l	dk_palette,d0-d7
	movem.l	d0-d7,$ffff8240.w	; 16 colors from d0-d7 = 8 longs = 16 words

	clr.b	$ffff8260.w		; low resolution
	move.b	#(512-320)/2/2,$ffff820f.w	; virtual line width 512 pixels

	; buffer 1 shows first, buffer 0 is drawn into

	move.l	scr_address+4,draw_screen_address
	move.l	scr_address,display_screen_address
	clr	draw_index

	rts

; d0 = address of a 64 KiB screen

clear_screen:
	move	#2,$ffff8a2e.w		; Destination X increment
	move	#$ffff,$ffff8a28.w	; Endmask 1
	move	#$ffff,$ffff8a2a.w	; Endmask 2
	move	#$ffff,$ffff8a2c.w	; Endmask 3
	move.b	#1,$ffff8a3a.w		; HOP 1 (halftone only)
	move.b	#0,$ffff8a3b.w		; OP 0 (destination = 0)
	clr.b	$ffff8a3d.w		; FXSR, NFSR, Skew
	move	#2,$ffff8a30.w		; Destination Y increment
	move	#16,$ffff8a36.w		; X Count: 16 words, 2048 lines = 64 KB
	move.l	d0,$ffff8a32.w
	move	#2048,$ffff8a38.w
	bra	blit_go			; (the interrupts run: in pieces)

; ------------------------------------------------------------------------------
; Interrupts
; ------------------------------------------------------------------------------

hbl:
	rte

; The VBL starts the frame: it switches the screen, starts the border timers, runs
; the Z80 NMI and draws.  All Z80 registers of the interrupted main thread are kept
; on the stack and restored at the end.

vbl:
	borders_vbl			; (first: Timer B counts the frame's lines)

	ifd DEBUG
	addq	#1,cnt_vbl
	endc
	tst.b	vbl_busy
	bne	vbl_skip
	st	vbl_busy
	movem.l	d0-d7/a0-a6,-(sp)

	ifd TIMES
	clr.b	$fffffa1d.w		; Timer D counts the frame: 256 ticks of 81 us from here
	clr.b	$fffffa25.w
	move.b	#7,$fffffa1d.w
	endc

	; Screens: the one drawn during this frame is shown from the next one on
	; (the STE takes the new address at the next VBL).

	move.l	display_screen_address,d0
	move.l	draw_screen_address,display_screen_address
	move.l	d0,draw_screen_address
	eori	#1,draw_index

	move.l	d0,-(sp)
	move.b	1(sp),$ffff8201.w
	move.b	2(sp),$ffff8203.w
	move.b	3(sp),$ffff820d.w
	addq.l	#4,sp

	addq.l	#1,frame_counter

	tst.b	quit_flag
	bne	quit

	; The rest of the frame runs below the VBL level: a frame that takes longer than
	; one VBL is interrupted by the next one, which only restarts the border timers
	; (vbl_skip), so the borders go on being removed at the right lines.

	move	#$2300,sr

	lea	z80_block,a6

	; Input into the Z80 side shadows.

	bsr	jagpad_poll
	move.b	in0_kbd,d0
	or.b	in0_joy,d0
	or.b	jp_in,d0		; (the pads)
	ifd AUTOSTART			; test: from 8 s after the start, walk right and jump every 64 frames
	move.l	frame_counter,d1
	sub.l	#AUTOSTART+400,d1
	bmi.s	.no_walk
	or.b	#$01,d0
	and	#63,d1
	cmp	#4,d1
	bhs.s	.no_walk
	or.b	#$10,d0
.no_walk:
	endc
	move.b	d0,$7e00(a6)
	clr.b	$7e80(a6)
	move.b	in2_kbd,d1
	or.b	jp_in+1,d1
	ifd AUTOSTART			; test: a coin at frame AUTOSTART, start 1 a second later
	move.l	frame_counter,d0
	sub.l	#AUTOSTART,d0
	cmp.l	#4,d0
	bhs.s	.no_coin
	or.b	#$80,d1
.no_coin:
	sub.l	#50,d0
	cmp.l	#4,d0
	bhs.s	.no_start
	or.b	#$04,d1
.no_start:
	endc
	move.b	d1,$7f00(a6)
	move.b	#$80,$7f80(a6)		; DSW0: upright, 3 lives, 7000 bonus, 1 coin 1 credit

	; Z80 NMI.

	ifd DUMPAT
	tst.b	freeze_flag		; test: the game stands still after the dump
	bne	vbl_render
	endc
	btst	#0,$7d84(a6)
	beq.s	vbl_render

	movem.l	(sp),d0-d7/a0-a6	; the interrupted Z80 registers
	move.b	#$40,-(a5)		; return token $4001
	move.b	#$01,-(a5)
	jmp	Z0066

z80_nmi_ret:
vbl_render:
	ifd TIMES
	move.b	$fffffa25.w,frame_nmi_end
	endc
	lea	z80_block,a6
	bsr	sound_update
	ifd DEBUG
	move.l	draw_screen_address,a0
	move	frame_counter+2,(a0)
	move	bd_fallbacks,256(a0)
	move	bd_late_low,512(a0)
	move	cnt_vbl,768(a0)
	move	cnt_skip,1024(a0)
	endc
	bsr	render_frame

	ifd TIMES
	move.l	frame_times_ptr,a0	; Timer D when the NMI and the frame ended, skipped VBLs
	move.b	frame_nmi_end,(a0)+
	move.b	$fffffa25.w,(a0)+
	move.b	cnt_skip+1,(a0)+
	move.b	old_bank+1,(a0)+	; palette bank (a change redraws the tiles it recolours)
	cmp.l	#frame_times_end,a0
	bhs.s	.times_full
	move.l	a0,frame_times_ptr
.times_full:
	endc

	ifd DUMPAT
	ifd DUMPBANK
	tst.b	freeze_flag
	bne.s	.no_dump
	cmp	#DUMPBANK,bank_changes
	else
	cmp.l	#DUMPAT,frame_counter
	endc
	bne.s	.no_dump
	bsr	dump_state
	st	freeze_flag
.no_dump:
	endc

	if FRAMES
	move.l	frame_counter,d0
	cmp.l	#FRAMES,d0
	blt.s	.go_on
	st	quit_flag		; the next VBL quits (as the Escape key does)
.go_on:
	endc

	move	#$2400,sr		; no VBL between the flag and the rte
	clr.b	vbl_busy
	movem.l	(sp)+,d0-d7/a0-a6
	rte

vbl_skip:
	ifd DEBUG
	addq	#1,cnt_skip
	endc
	rte

	borders_handlers
	borders_blit_go
	borders_report

; ------------------------------------------------------------------------------
; Keyboard / joystick (IKBD)
; ------------------------------------------------------------------------------
;
; IN0: bit0 right, bit1 left, bit2 up, bit3 down, bit4 jump
; IN2: bit2 start 1, bit3 start 2, bit7 coin

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
	or.b	d0,in2_kbd
	bra	.again

.release:
	move.b	1(a0),d0
	not.b	d0
	and.b	d0,in0_kbd
	move.b	2(a0),d0
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
	beq	.j1
	bset	#2,d0
.j1:	btst	#1,d1			; down
	beq	.j2
	bset	#3,d0
.j2:	btst	#2,d1			; left
	beq	.j3
	bset	#1,d0
.j3:	btst	#3,d1			; right
	beq	.j4
	bset	#0,d0
.j4:	tst.b	d1			; fire
	bpl	.j5
	bset	#4,d0
.j5:	move.b	d0,in0_joy
	bra	.again

.done:
	movem.l	(sp)+,d0-d2/a0
	rte

; scancode, IN0 bits, IN2 bits

key_table:
	dc.b	$4d,$01,$00		; right
	dc.b	$4b,$02,$00		; left
	dc.b	$48,$04,$00		; up
	dc.b	$50,$08,$00		; down
	dc.b	$39,$10,$00		; space = jump
	dc.b	$1d,$10,$00		; control = jump
	dc.b	$38,$10,$00		; alternate = jump
	dc.b	$02,$00,$04		; 1 = start 1
	dc.b	$03,$00,$08		; 2 = start 2
	dc.b	$06,$00,$80		; 5 = coin
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

	ifd DUMPAT

; Test aid: write the Z80 memory $6000-$7FFF to DUMP.BIN (tools compare the screen with
; the reference renderer drawing the same state).

dump_state:
	pea	z80_block+$6000
	move.l	#$2000,-(sp)
	pea	dump_name
	bsr.s	write_file
	lea	12(sp),sp
	rts

dump_name:
	dc.b	"DUMP.BIN",0
	even

	endc

	ifd TIMES

; Measurement: the frame records to TIMES.BIN (tools/frametimes.py).

dump_times:
	move.l	frame_times_ptr,d0
	sub.l	#frame_times,d0
	pea	frame_times
	move.l	d0,-(sp)
	pea	times_name
	bsr.s	write_file
	lea	12(sp),sp
	rts

times_name:
	dc.b	"TIMES.BIN",0
	even

	endc

	ifd DUMPAT
WRITE_FILE = 1
	endc
	ifd TIMES
	ifnd WRITE_FILE
WRITE_FILE = 1
	endc
	endc
	ifd WRITE_FILE

; write_file: 4(sp) name, 8(sp) length, 12(sp) data (GEMDOS)

write_file:
	clr	-(sp)			; Fcreate
	move.l	4+2(sp),-(sp)
	move	#$3c,-(sp)
	trap	#1
	addq	#8,sp
	move	d0,d6

	move.l	12(sp),-(sp)		; Fwrite
	move.l	8+4(sp),-(sp)
	move	d6,-(sp)
	move	#$40,-(sp)
	trap	#1
	lea	12(sp),sp

	move	d6,-(sp)		; Fclose
	move	#$3e,-(sp)
	trap	#1
	addq	#4,sp
	rts

	endc

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
	bsr	crash_wait
	bra	quit

	include "render.s"
	include "sprites.s"
	include "sound.s"

; ------------------------------------------------------------------------------
; The translated Z80 program (also defines the dispatch table in the data section).

	include "dk_code.s"

	section text,code
	include "rtlib.s"

; ------------------------------------------------------------------------------
	section data,data
; ------------------------------------------------------------------------------

rom_table:				; source, destination, bytes
	dc.l	rom_cpu,z80_block,$4000
	dc.l	0
rom_cpu:	incbin	"rom_cpu.rom"
	even

bad_text:
	dc.b	13,10,"Donkey Kong: the translated program reached an unknown address.",13,10
	dc.b	"Press Return.",13,10,0

	include "dk_assets.s"

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
	jagpad_vars
vbl_busy:	ds.b	1
	borders_vars
freeze_flag:	ds.b	1
in0_kbd:	ds.b	1
in0_joy:	ds.b	1
in2_kbd:	ds.b	1
	ikbd_vars
joy0_state:	ds.b	1
joy1_state:	ds.b	1
	even

frame_counter:	ds.l	1
cnt_acia:	ds.w	1
cnt_vbl:	ds.w	1
cnt_skip:	ds.w	1
crash_vector:	ds.w	1
crash_sp:	ds.l	1
crash_regs:	ds.l	16
crash_text:	ds.b	512
draw_index:	ds.w	1
bg_address:	ds.l	1
scr_address:	ds.l	2
draw_screen_address:	ds.l	1
display_screen_address:	ds.l	1

	ifd TIMES
frame_nmi_end:	ds.b	1
	even
frame_times_ptr:	ds.l	1
frame_times:	ds.b	4*4096
frame_times_end:
	endc

z80_block:	ds.b	$8000

	cnop 0,4
z80_dispatch_sw:	ds.l	65536	; byte swapped Z80 pc -> 68k address (z80_init_dispatch)

	ds.b	1024
own_stack_top:

	cnop 0,4
screens:
	ds.b	$10000			; alignment slack
	ds.b	$20000*3
