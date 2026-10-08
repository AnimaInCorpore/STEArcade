; ------------------------------------------------------------------------------
;
; Donkey Kong for the Atari STE
;
; The arcade Z80 program is translated to 68000 code by tools/gen.py (z80x.py);
; this file is the machine around it: STE video (320 x 256 with top and bottom
; border removed), double buffering, tile and sprite drawing, input.
;
; Needs the four CPU ROM files c_5et_g.bin c_5ct_g.bin c_5bt_g.bin c_5at_g.bin
; in the current folder.
;
; ------------------------------------------------------------------------------

BUSY = %10000000
HOG = %01000000
NFSR = %01000000

STRIDE = 256				; bytes per line, 512 pixel virtual screen
GAME_X = 24				; byte offset of the game area in a line (3 chunks)
VISIBLE_ROWS = 28			; arcade tile rows 2..29
KEY_ESC = $01

	ifnd FRAMES
FRAMES = 0				; quit after n frames (0 = never), for measurements
	endc

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
	tst.l	d0
	bne	rom_error

	stage	$ff0
	bsr	init_hardware
	stage	$0ff
	bsr	init_video
	bsr	init_render
	stage	$f0f

	; Start the Z80 main thread.

	lea	z80_dispatch,a4
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
; ROM loading (GEMDOS)
; ------------------------------------------------------------------------------

load_roms:
	lea	rom_names,a3
	lea	z80_block,a4
	moveq	#3,d6

.next:
	clr	-(sp)			; Fopen, read only
	pea	(a3)
	move	#$3d,-(sp)
	trap	#1
	addq	#8,sp
	tst	d0
	bmi.s	.fail

	move	d0,d7
	pea	(a4)			; Fread 4096 bytes
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

	lea	$1000(a4),a4

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

	; IKBD: joystick event reporting, mouse off.

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
.w1:	btst	#1,$fffffc00.w		; IKBD: mouse relative again
	beq.s	.w1
	move.b	#$08,$fffffc02.w
	endc

	move	#$2300,sr
	rts

quit:
	bsr	restore_hardware

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
	move	#$8000,$ffff8a36.w	; X Count = 64 KB
	move.l	d0,$ffff8a32.w
	move	#1,$ffff8a38.w
	move.b	#$c0,$ffff8a3c.w	; Busy + Hog
	rts

; ------------------------------------------------------------------------------
; Interrupts
; ------------------------------------------------------------------------------

hbl:
	rte

; The VBL starts the frame: it switches the screen, starts the border timers, runs
; the Z80 NMI and draws.  All Z80 registers of the interrupted main thread are kept
; on the stack and restored at the end.

vbl:
	tst.b	vbl_busy		; a VBL inside a long frame (Timer A lowers the IPL)
	bne	vbl_skip
	st	vbl_busy
	movem.l	d0-d7/a0-a6,-(sp)

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

	clr.b	$fffffa1b.w
	move.b	#199+29,$fffffa21.w	; Timer B data
	move.b	#8,$fffffa1b.w		; Timer B control

	move.b	#97,$fffffa1f.w		; Timer A data
	move.b	#4,$fffffa19.w		; Timer A control

	addq.l	#1,frame_counter

	tst.b	quit_flag
	bne	quit

	lea	z80_block,a6

	; Input into the Z80 side shadows.

	move.b	in0_kbd,d0
	or.b	in0_joy,d0
	move.b	d0,$7e00(a6)
	clr.b	$7e80(a6)
	move.b	in2_kbd,$7f00(a6)
	move.b	#$80,$7f80(a6)		; DSW0: upright, 3 lives, 7000 bonus, 1 coin 1 credit

	; Z80 NMI.

	btst	#0,$7d84(a6)
	beq.s	vbl_render

	movem.l	(sp),d0-d7/a0-a6	; the interrupted Z80 registers
	move.b	#$40,-(a5)		; return token $4001
	move.b	#$01,-(a5)
	jmp	Z0066

z80_nmi_ret:
vbl_render:
	lea	z80_block,a6
	ifd DEBUG
	move.l	draw_screen_address,a0
	move	frame_counter+2,(a0)
	move	cnt_timer_a,256(a0)
	move	cnt_timer_b,512(a0)
	move	cnt_acia,768(a0)
	endc
	bsr	render_frame

	if FRAMES
	move.l	frame_counter,d0
	cmp.l	#FRAMES,d0
	blt.s	.go_on
	bsr	quit
.go_on:
	endc

	clr.b	vbl_busy
	movem.l	(sp)+,d0-d7/a0-a6
vbl_skip:
	rte

; Top border removal (Timer A), see balls64.s of the fast Blitter objects demo.

timer_a:
	addq	#1,cnt_timer_a
	move	#$2100,sr		; Enable HBL
	stop	#$2100			; Wait for HBL
	move	#$2700,sr		; Stop all interrupts

	clr.b	$fffffa19.w		; Stop Timer A

	rept 84
	nop
	endr

	clr.b	$ffff820a.w		; Remove the top border

	rept 9
	nop
	endr

	move.b	#2,$ffff820a.w

	rte

; Bottom border removal (Timer B)

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

	rte

; ------------------------------------------------------------------------------
; Keyboard / joystick (IKBD)
; ------------------------------------------------------------------------------
;
; IN0: bit0 right, bit1 left, bit2 up, bit3 down, bit4 jump
; IN2: bit2 start 1, bit3 start 2, bit7 coin

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
	bhs	.again			; other packets are not expected

	; Scancode.

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

	include "render.s"

; ------------------------------------------------------------------------------
; The translated Z80 program (also defines the dispatch table in the data section).

	include "../build/dk_code.s"

	section text,code
	include "../tools/rtlib.s"

	include "../build/dk_sprites.s"

; ------------------------------------------------------------------------------
	section data,data
; ------------------------------------------------------------------------------

rom_names:
	dc.b	"c_5et_g.bin",0
	dc.b	"c_5ct_g.bin",0
	dc.b	"c_5bt_g.bin",0
	dc.b	"c_5at_g.bin",0

rom_error_text:
	dc.b	13,10
	dc.b	"Donkey Kong: cannot read the arcade CPU ROM files",13,10
	dc.b	"c_5et_g.bin c_5ct_g.bin c_5bt_g.bin c_5at_g.bin",13,10
	dc.b	"They have to be in the current folder. Press a key.",13,10,0

bad_text:
	dc.b	13,10,"Donkey Kong: the translated program reached an unknown address.",13,10
	dc.b	"Press a key.",13,10,0

	include "../build/dk_assets.s"

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
in0_kbd:	ds.b	1
in0_joy:	ds.b	1
in2_kbd:	ds.b	1
ikbd_state:	ds.b	1
joy0_state:	ds.b	1
joy1_state:	ds.b	1
	even

frame_counter:	ds.l	1
cnt_timer_a:	ds.w	1
cnt_timer_b:	ds.w	1
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

z80_block:	ds.b	$8000

	ds.b	4096
own_stack_top:

	cnop 0,4
screens:
	ds.b	$10000			; alignment slack
	ds.b	$20000*3
