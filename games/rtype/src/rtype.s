; R-Type (Irem M72) for the Atari STE.
;
; The translated main CPU program and its runtime: core.s (tools/gen.py, engine/v30x.py).  The port starts from the
; reference's state after the boot (tools/snapshot.py: build/rtype/snapshot.bin); the boot is not translated.
;
; SIM: the build the tests drive (tools/logic_test.py): the harness writes the reference's state into the image and the
; context, sets in_ports and calls port_frame once an arcade frame.
; Otherwise the program: the snapshot loaded, then in turn arcade frames (port_frame: the VBL interrupt's handler - the
; game's logic - then the raster interrupt's) and pictures (video.s m72_sync, then the renderer: render.s, the shared
; engine/rt/m72render.s, the centred 320-pixel window).  Time: the arcade runs at 55.02 Hz; the STE's VBL (50 Hz)
; counts 11 arcade frames per 10 fields into `ticks`.  The logic runs one arcade frame per tick when it keeps up (it
; does not: ~100k cycles a frame, the picture ~1M); a picture after every PIC_EVERY-th arcade frame (or when no tick
; is waiting); arcade frames the logic falls behind by more than MAX_BEHIND are dropped (the game slows down, its
; pace stays even).  DEBUG writes separate logic/picture counters to COUNTERS.BIN on quitting.
; The display: the renderer's buffers, engine/rt/borders.s (top and bottom border open, the picture's palette and the
; status bar's own screen and palette: BD_HUD, BD_VSWITCH).  Sound: none yet (the sound latch's bytes are kept in core.s' ring).
; Untranslated code reached: CRASH.TXT "BADPC xxxxx" (the linear address), back to the desktop.

KEY_ESC = $01
    ifnd SIM
      ifnd FADE_EXACT
FADE_SNAP = 1				; (src/natives.s: the palette fades left out)
      endc
PIC_TOP = 9				; the picture's first displayed line (256 lines: 9 .. 264)
TA_DATA = 98
TA_NOPS = 84
PIC_LINES = 256
BD_PALETTE = 1
BD_HUD = 1
BD_VSWITCH = 1			; (the status bar: its own screen and palette from its first line, borders.s)
MAX_BEHIND = 3
      ifnd PIC_EVERY
PIC_EVERY = 2				; (arcade frames a picture at most: the logic's share against the picture rate)
      endc
; the pads (engine/rt/jagpad.s): SYSTEM (IN1), P1 (IN0 low), P2 (IN0 high) bits as in key_table (bytes 0-2)
JP_SH1 = 16
JP_SH2 = 8
JP1_RIGHT = $01<<JP_SH1
JP1_LEFT = $02<<JP_SH1
JP1_DOWN = $04<<JP_SH1
JP1_UP = $08<<JP_SH1
JP1_B1 = $80<<JP_SH1			; (pad A: fire)
JP1_B2 = $40<<JP_SH1			; (pad B: the Force)
JP1_B3 = 0
JP2_RIGHT = $01<<JP_SH2
JP2_LEFT = $02<<JP_SH2
JP2_DOWN = $04<<JP_SH2
JP2_UP = $08<<JP_SH2
JP2_B1 = $80<<JP_SH2
JP2_B2 = $40<<JP_SH2
JP2_B3 = 0
JP_START1 = $01<<24
JP_START2 = $02<<24
JP_COIN1 = $04<<24
JP_COIN2 = $08<<24
	include	"ikbd.s"
	include	"borders.s"
	include	"jagpad.s"
shown_pal = m72r_vbl_pal
hud_pal = m72r_vbl_hpal
hud_top = m72r_vbl_htop
hud_bot = m72r_vbl_hbot
    endc

; (the image's tail first in the BSS: it follows the ROM, the last thing in the data section; core.s init_image)
	section bss,bss
v30_tail:	ds.b	$A0000

	section text,code
start:
	clr.l	-(sp)
	move	#$20,-(sp)
	trap	#1
	addq	#6,sp
	move.l	d0,old_ssp
	lea	own_stack_top,sp
	bsr	init_image
    ifd SIM
sim_wait:
	bra.s	sim_wait
    else
	bsr	snapshot_load
	bsr	m72_sync_all
	bsr	m72r_init
	bsr	init_hardware
main_loop:
	tst.b	quit_flag
	bne.s	.quit
	tst.b	ticks
	beq.s	main_loop
	cmp.b	#MAX_BEHIND,ticks	; (behind: drop arcade frames)
	bls.s	.go
	move.b	#MAX_BEHIND,ticks
	addq.l	#1,cnt_dropped
.go:	subq.b	#1,ticks
	bsr	port_frame
	addq.l	#1,cnt_logic
	addq.b	#1,since_pic		; a picture after every PIC_EVERY-th arcade frame, or when the logic caught up
	cmp.b	#PIC_EVERY,since_pic
	bhs.s	.pic
	tst.b	ticks
	bne	main_loop
.pic:	clr.b	since_pic
	bsr	m72_sync
	bsr	m72r_frame
	bra.s	main_loop
.quit:	bsr	restore_hardware
	bsr	write_counters
	move.l	old_ssp,-(sp)
	move	#$20,-(sp)
	trap	#1
	addq	#6,sp
	clr	-(sp)
	trap	#1

; ---- the snapshot (tools/snapshot.py) ----
snapshot_load:
	lea	snapshot,a0
	lea	v30_image+$40000,a1	; the work RAM
	move.w	#$4000/4-1,d0
	bsr	.copy
	lea	v30_image+$C0000,a1	; the sprite RAM
	move.w	#$400/4-1,d0
	bsr	.copy
	lea	v30_image+$C8000,a1	; the palettes
	move.w	#$C00/4-1,d0
	bsr	.copy
	lea	v30_image+$CC000,a1
	move.w	#$C00/4-1,d0
	bsr	.copy
	lea	v30_image+$D0000,a1	; the video RAMs
	move.w	#$4000/4-1,d0
	bsr	.copy
	lea	v30_image+$D8000,a1
	move.w	#$4000/4-1,d0
	bsr	.copy
	lea	m72_spritebuf,a1
	move.w	#$400/4-1,d0
	bsr	.copy
	lea	ctx_main,a6
	move.l	(a0)+,V30_SEG(a6)	; DS1 PS SS DS0
	move.l	(a0)+,V30_SEG+4(a6)
	move.w	(a0)+,d0
	move.b	d0,V30_IE(a6)
	move.w	(a0)+,d0
	move.b	d0,V30_DF(a6)
	move.w	(a0)+,d0
	move.b	d0,V30_PB(a6)
	move.w	(a0)+,d0
	move.b	d0,V30_AX(a6)
	lea	R_D0(a6),a1		; AW CW DW BW IX IY BP (d0-d6)
	moveq	#7-1,d1
.r:	moveq	#0,d0
	move.w	(a0)+,d0
	move.l	d0,(a1)+
	dbf	d1,.r
	moveq	#0,d1			; the bases: a2 DS1, a3 DS0, a4 SS, a5 SS:SP
	move.w	V30_SEG(a6),d1
	lsl.l	#4,d1
	add.l	#v30_image,d1
	move.l	d1,R_A2(a6)
	moveq	#0,d1
	move.w	V30_SEG+6(a6),d1
	lsl.l	#4,d1
	add.l	#v30_image,d1
	move.l	d1,R_A2+4(a6)
	moveq	#0,d1
	move.w	V30_SEG+4(a6),d1
	lsl.l	#4,d1
	add.l	#v30_image,d1
	move.l	d1,R_A2+8(a6)
	moveq	#0,d0
	move.w	(a0)+,d0		; SP
	add.l	d1,d0
	move.l	d0,R_A2+12(a6)
	move.w	(a0)+,R_SR(a6)
	move.l	(a0)+,m72_scroll
	move.l	(a0)+,m72_scroll+4
	move.l	m72_scroll,m72_scroll_vbl
	move.l	m72_scroll+4,m72_scroll_vbl+4
	move.w	(a0)+,m72_raster
	move.w	(a0)+,m72_port02
	rts
.copy:	move.l	(a0)+,(a1)+
	dbf	d0,.copy
	rts

; untranslated code reached (core.s main_badpc: badpc = the linear address): CRASH.TXT "BADPC xxxxx", the desktop
port_crash:
	move	#$2700,sr
	lea	own_stack_top,sp
	bsr	restore_hardware
	lea	crash_pc,a1
	move.l	badpc,d0
	moveq	#5-1,d2
	add.w	#5,a1
.h:	moveq	#15,d1
	and.w	d0,d1
	move.b	.digits(pc,d1.w),-(a1)
	lsr.l	#4,d0
	dbf	d2,.h
	clr.w	-(sp)
	pea	.name(pc)
	move.w	#$3C,-(sp)		; Fcreate
	trap	#1
	addq.l	#8,sp
	tst.w	d0
	bmi.s	.out
	move.w	d0,-(sp)
	pea	crash_text
	pea	crash_end-crash_text
	move.w	d0,-(sp)
	move.w	#$40,-(sp)		; Fwrite
	trap	#1
	lea	12(sp),sp
	move.w	#$3E,-(sp)		; Fclose
	trap	#1
	addq.l	#4,sp
.out:	bsr	write_counters
	move.l	old_ssp,-(sp)
	move	#$20,-(sp)
	trap	#1
	addq	#6,sp
	clr	-(sp)
	trap	#1
.digits:	dc.b	"0123456789ABCDEF"
.name:	dc.b	"CRASH.TXT",0
	even

; COUNTERS.BIN (longs): VBLs, arcade frames run, pictures drawn, arcade frames dropped, pictures skipped (no free
; buffer), renderer calls without a picture (conversions of a new scene)
write_counters:
	ifd DEBUG
	move.l	m72r_pictures,cnt_pictures
	move.l	m72r_skipped,cnt_skipped
	move.l	m72r_lates,cnt_lates
	clr.w	-(sp)
	pea	.name(pc)
	move.w	#$3C,-(sp)		; Fcreate
	trap	#1
	addq.l	#8,sp
	tst.w	d0
	bmi.s	.r
	move.w	d0,-(sp)
	pea	cnt_vbls
	pea	24.w
	move.w	d0,-(sp)
	move.w	#$40,-(sp)		; Fwrite
	trap	#1
	lea	12(sp),sp
	move.w	#$3E,-(sp)		; Fclose (the handle is on the stack)
	trap	#1
	addq.l	#4,sp
.r:	rts
.name:	dc.b	"COUNTERS.BIN",0
	even
	else
	rts
	endc

; ---- the hardware: the VBL (borders, the picture, the ticks, the pads), the timers (borders.s), the ACIA (keys,
; joysticks) ----
init_hardware:
	move	#$2700,sr
	movem.l	$ffff8240.w,d0-d7
	movem.l	d0-d7,old_palette
	move.b	$ffff8260.w,old_res
	move.b	$ffff820a.w,old_hz
	move.b	$ffff820f.w,old_linewid
	move.b	$ffff8265.w,old_fine
	move.b	$ffff8201.w,old_screen+1
	move.b	$ffff8203.w,old_screen+2
	move.b	$ffff820d.w,old_screen+3
	lea	$fffffa07.w,a0
	lea	old_mfp,a1
	moveq	#$21-$07,d0		; (the MFP's registers $fffffa07-$fffffa21, odd bytes)
.mfp:	move.b	(a0),(a1)+
	addq.l	#2,a0
	subq.w	#2,d0
	bpl.s	.mfp
	move.l	$68.w,old_hbl
	move.l	$70.w,old_vbl
	move.l	$118.w,old_acia
	move.l	$120.w,old_timer_b
	move.l	$134.w,old_timer_a
	clr.b	$fffffa07.w
	clr.b	$fffffa09.w
	clr.b	$fffffa13.w
	clr.b	$fffffa15.w
	bclr	#3,$fffffa17.w		; (automatic end of interrupt)
	clr.b	$fffffa19.w
	clr.b	$fffffa1b.w
	moveq	#0,d0
	movem.l	d0,$ffff8240.w
	clr.b	$ffff8260.w		; (low resolution, 50 Hz)
	move.b	#2,$ffff820a.w
	move.l	#hbl,$68.w
	move.l	#vbl,$70.w
	move.l	#acia_isr,$118.w
	move.l	#timer_b,$120.w
	move.l	#timer_a,$134.w
	bset	#0,$fffffa07.w		; Timer B
	bset	#0,$fffffa13.w
	bset	#5,$fffffa07.w		; Timer A
	bset	#5,$fffffa13.w
	bset	#6,$fffffa09.w		; ACIA
	bset	#6,$fffffa15.w
.w1:	btst	#1,$fffffc00.w
	beq.s	.w1
	move.b	#$14,$fffffc02.w	; joystick events
	bsr	jagpad_init		; (the STE pads: absent on a plain ST)
	move	#$2300,sr
	rts

restore_hardware:
	move	#$2700,sr
	clr.b	$fffffa19.w
	clr.b	$fffffa1b.w
	lea	old_mfp,a0
	lea	$fffffa07.w,a1
	moveq	#$21-$07,d0
.mfp:	move.b	(a0)+,(a1)
	addq.l	#2,a1
	subq.w	#2,d0
	bpl.s	.mfp
	move.l	old_hbl,$68.w
	move.l	old_vbl,$70.w
	move.l	old_acia,$118.w
	move.l	old_timer_b,$120.w
	move.l	old_timer_a,$134.w
	movem.l	old_palette,d0-d7
	movem.l	d0-d7,$ffff8240.w
	move.b	old_res,$ffff8260.w
	move.b	old_hz,$ffff820a.w
	move.b	old_linewid,$ffff820f.w
	move.b	old_fine,$ffff8265.w
	move.b	old_screen+1,$ffff8201.w
	move.b	old_screen+2,$ffff8203.w
	move.b	old_screen+3,$ffff820d.w
.w1:	btst	#1,$fffffc00.w
	beq.s	.w1
	move.b	#$08,$fffffc02.w	; mouse again
	move	#$2300,sr
	rts

hbl:	rte

; the VBL: borders.s' events, the picture published last, the pads, the ticks (11 arcade frames per 10 fields)
vbl:	borders_vbl
	bsr	m72r_vbl
	bsr	bd_hud_plan
	movem.l	d0-d2,-(sp)
	bsr	jagpad_poll
	bsr	compose
	movem.l	(sp)+,d0-d2
	addq.l	#1,cnt_vbls
	cmp.b	#32,ticks
	bhs.s	.r
	addq.b	#1,ticks
	addq.b	#1,tick_phase
	cmp.b	#10,tick_phase
	blo.s	.r
	clr.b	tick_phase
	addq.b	#1,ticks
.r:	rte

; Keyboard, joystick 1 (player 1), joystick 0 (the mouse port: player 2): IN0 low byte player 1, high byte player 2
; (right 0, left 1, down 2, up 3, button 2 = the Force 6, button 1 = fire 7), IN1 low byte (start 1 0, start 2 1,
; coin 1 2, coin 2 3), all active low.
acia_isr:
	movem.l	d0-d2/a0,-(sp)
.again:
	ikbd_byte
	lea	key_table,a0
.find:	move.b	(a0),d0
	beq	.again
	cmp.b	d0,d1
	beq.s	.found
	addq	#4,a0
	bra.s	.find
.found:	tst.b	d2
	bmi.s	.release
	move.b	1(a0),d0
	or.b	d0,kbd_sys
	move.b	2(a0),d0
	or.b	d0,kbd_p1
	move.b	3(a0),d0
	or.b	d0,kbd_p2
	bsr	compose
	bra	.again
.release:
	move.b	1(a0),d0
	not.b	d0
	and.b	d0,kbd_sys
	move.b	2(a0),d0
	not.b	d0
	and.b	d0,kbd_p1
	move.b	3(a0),d0
	not.b	d0
	and.b	d0,kbd_p2
	bsr	compose
	bra	.again
.packet_byte:
	clr.b	ikbd_state
	moveq	#0,d2			; joystick bits -> IN0 bits
	btst	#3,d1
	beq.s	.j1
	bset	#0,d2
.j1:	btst	#2,d1
	beq.s	.j2
	bset	#1,d2
.j2:	btst	#1,d1
	beq.s	.j3
	bset	#2,d2
.j3:	btst	#0,d1
	beq.s	.j4
	bset	#3,d2
.j4:	tst.b	d1
	bpl.s	.j5
	bset	#7,d2			; fire
.j5:	cmp.b	#2,d0
	bne.s	.p2
	move.b	d2,joy_p1		; joystick 1 (port 1)
	bra.s	.j6
.p2:	move.b	d2,joy_p2		; joystick 0 (the mouse port)
.j6:	bsr	compose
	bra	.again
.done:
	movem.l	(sp)+,d0-d2/a0
	rte

; in_ports: IN0 (high byte player 2, low byte player 1), IN1 (low byte the coins and starts), active low
compose:
	move.b	kbd_sys,d0
	or.b	jp_in,d0
	not.b	d0
	move.b	d0,in_ports+3
	move.b	kbd_p1,d0
	or.b	joy_p1,d0
	or.b	jp_in+1,d0
	not.b	d0
	move.b	d0,in_ports+1
	move.b	kbd_p2,d0
	or.b	joy_p2,d0
	or.b	jp_in+2,d0
	not.b	d0
	move.b	d0,in_ports
	rts

; scancode, IN1 bits, player 1 bits, player 2 bits
key_table:
	dc.b	$4d,$00,$01,$00		; right
	dc.b	$4b,$00,$02,$00		; left
	dc.b	$50,$00,$04,$00		; down
	dc.b	$48,$00,$08,$00		; up
	dc.b	$39,$00,$80,$00		; space = fire
	dc.b	$1d,$00,$80,$00		; control = fire
	dc.b	$38,$00,$40,$00		; alternate = the Force
	dc.b	$02,$01,$00,$00		; 1 = start 1
	dc.b	$03,$02,$00,$00		; 2 = start 2
	dc.b	$06,$04,$00,$00		; 5 = coin 1
	dc.b	$07,$08,$00,$00		; 6 = coin 2
	dc.b	0,0,0,0
	even
	borders_handlers
	borders_blit_go
	jagpad_text
	jagpad_maps
    endc

	include	"core.s"
	include	"natives.s"
    ifnd SIM
	include	"video.s"
	include	"render.s"
    endc

	section data,data
    ifnd SIM
snapshot:
	incbin	"snapshot.bin"
	even
black_pal:	dcb.w	16,0
crash_text:	dc.b	"BADPC "
crash_pc:	dc.b	"00000",13,10
crash_end:
	even
    endc
; (last in the data section: the V30 image's ROM, followed by v30_tail)
	even
v30_image:
	incbin	"rom_image.bin"

	section bss,bss
old_ssp:	ds.l	1
old_vbl:	ds.l	1
old_acia:	ds.l	1
old_hbl:	ds.l	1
old_timer_a:	ds.l	1
old_timer_b:	ds.l	1
old_palette:	ds.w	16
old_screen:	ds.l	1
cnt_vbls:	ds.l	1		; (counters: VBLs, arcade frames run, pictures, frames dropped, pictures skipped,
cnt_logic:	ds.l	1		; renderer calls that converted without a picture)
cnt_pictures:	ds.l	1
cnt_dropped:	ds.l	1
cnt_skipped:	ds.l	1
cnt_lates:	ds.l	1
old_mfp:	ds.b	14
old_res:	ds.b	1
old_hz:		ds.b	1
old_linewid:	ds.b	1
old_fine:	ds.b	1
ticks:		ds.b	1
tick_phase:	ds.b	1
since_pic:	ds.b	1
kbd_sys:	ds.b	1
kbd_p1:		ds.b	1
kbd_p2:		ds.b	1
joy_p1:		ds.b	1
joy_p2:		ds.b	1
quit_flag:	ds.b	1
	even
    ifnd SIM
	ikbd_vars
	even
	borders_vars
	even
	jagpad_vars
	even
    endc
		ds.b	4096
own_stack_top:
