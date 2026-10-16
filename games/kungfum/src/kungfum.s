; Kung-Fu Master (Irem M62, 1984) for the Atari STE: the main Z80 program translated (tools/gen.py ->
; build/kungfum/code_kungfum.s), the picture drawn by render.s.  No sound yet: the sound commands go into a ring.

	ifnd MAX_PENDING
MAX_PENDING = 3				; arcade frames that may be waiting (the game catches up after a slow picture)
	endc
	ifnd MAX_SKIP
MAX_SKIP = 2				; arcade frames in a row that are not drawn while the game is behind
	endc
	ifnd FRAMES
FRAMES = 0
	endc

BUSY = %10000000
HOG = %01000000
KEY_ESC = $01

; Border removal, the palettes and the HUD's own image: engine/rt/borders.s (BD_HUD + BD_VSWITCH: the score panel,
; picture lines 0-47, from its own image with its own palette; the playfield below it from the scrolled ring).

	ifnd TA_DATA
TA_DATA = 98
	endc
	ifnd TA_NOPS
TA_NOPS = 84
	endc
PIC_TOP = 10				; the picture's first displayed line
PIC_LINES = 256
BD_PALETTE = 1
BD_HUD = 1
BD_VSWITCH = 1
	include	"borders.s"

; the pads (engine/rt/jagpad.s): SYSTEM, P1, P2 bits as in key_table (bytes 0-2 of each long; active high there)
JP_SH1 = 16
JP_SH2 = 8
JP1_RIGHT = $01<<JP_SH1
JP1_LEFT = $02<<JP_SH1
JP1_DOWN = $04<<JP_SH1
JP1_UP = $08<<JP_SH1
JP1_B1 = $80<<JP_SH1			; (pad A: punch)
JP1_B2 = $20<<JP_SH1			; (pad B: kick)
JP1_B3 = 0
JP2_RIGHT = $01<<JP_SH2
JP2_LEFT = $02<<JP_SH2
JP2_DOWN = $04<<JP_SH2
JP2_UP = $08<<JP_SH2
JP2_B1 = $80<<JP_SH2
JP2_B2 = $20<<JP_SH2
JP2_B3 = 0
JP_START1 = $01<<24
JP_START2 = $02<<24
JP_COIN1 = $08<<24
JP_COIN2 = $10<<JP_SH2			; (coin 2 is P2 bit 4)
	include	"jagpad.s"
	include	"ikbd.s"

; The Z80's 64 KB: a6 = g_block + $8000 = Z80 address 0 (signed word offsets: $8000-$FFFF lie below a6).
G_Z80 = g_block+$8000
Z_RAM = g_block-$8000			; + a Z80 address >= $8000
TOKEN = $FEF7				; $F7FE on the Z80 stack, byte swapped (gen.py / machine.py TOKEN)

	section text,code

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

	bsr	init_hardware
	bsr	init_render
	ifnd NOSOUND
	bsr	snd_init
	endc

	ifnd SIM			; (the test harness sets the ports, the DIP switches of its seed)
	move.b	#$FF,io_ports		; SYSTEM, P1, P2: nothing pressed
	move.b	#$FF,io_ports+1
	move.b	#$FF,io_ports+2
	move.b	#$FF,io_ports+3		; DSW1: easy, slow energy loss, 3 lives, 1 coin 1 credit
	move.b	#$FD,io_ports+4		; DSW2: no flip, upright, coin mode 1, no cheats
	ifd DSW2
	move.b	#DSW2,io_ports+4
	endc
	endc
	move.b	#$FF,in_sys
	move.b	#$FF,in_p1
	move.b	#$FF,in_p2
	move.w	#$ACE1,rnd_state

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
; Hardware
; ------------------------------------------------------------------------------

init_hardware:
	move	#$2700,sr
	movem.l	$ffff8240.w,d0-d7
	movem.l	d0-d7,old_palette
	move.b	$ffff8260.w,old_res
	move.b	$ffff820a.w,old_hz
	move.b	$ffff820f.w,old_linewid
	move.b	$ffff8265.w,old_fine
	clr.b	$ffff8260.w		; low resolution, 50 Hz (the border timing is for 50)
	move.b	#2,$ffff820a.w
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
	move.b	#$14,$fffffc02.w	; joysticks on
.w2:	btst	#1,$fffffc00.w
	beq.s	.w2
	move.b	#$12,$fffffc02.w	; mouse off
	bsr	jagpad_init
	endc
	rts

restore_hardware:
	move	#$2700,sr
	clr.b	$ffff8901.w		; (the DMA sound off)
	moveq	#8,d0			; the YM2149 silent
.silence:
	move.b	d0,$ffff8800.w
	clr.b	$ffff8802.w
	addq.b	#1,d0
	cmp.b	#11,d0
	blo.s	.silence
	movem.l	old_palette,d0-d7
	movem.l	d0-d7,$ffff8240.w
	move.b	old_res,$ffff8260.w
	move.b	old_hz,$ffff820a.w
	move.b	old_linewid,$ffff820f.w
	move.b	old_fine,$ffff8265.w
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
	move.b	#$08,$fffffc02.w	; mouse on
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

; The VBL: the borders' events, the finished picture shown (render.s vbl_video), the inputs copied into the ports the
; program reads, the arcade's frames counted: 56.34 Hz against the STE's 50, nine to eight VBLs.

vbl:
	ifnd SIM
	borders_vbl
	endc
	movem.l	d0-d1/a0,-(sp)
	addq.l	#1,frame_counter
	ifd DEBUG
	subq.w	#1,dbg_tl_n		; every 100 VBLs: the arcade frames and pictures so far (RATE.BIN, bench.sh)
	bgt.s	.tl
	move.w	#100,dbg_tl_n
	move.l	dbg_tl_p,a0
	cmp.w	#0,a0
	bne.s	.tl1
	lea	dbg_tl,a0
.tl1:	cmp.l	#dbg_tl_end,a0
	bhs.s	.tl
	move.w	isr_count,(a0)+
	move.w	pic_count,(a0)+
	move.l	a0,dbg_tl_p
.tl:
	endc
	tst.b	quit_flag
	bne	quit
	bsr	vbl_video
	ifnd SIM
	bsr	bd_hud_plan
	endc
	ifnd PLAYBACK
	bsr	jagpad_poll
	jp_merge	in_sys,io_ports,0
	jp_merge	in_p1,io_ports+1,1
	jp_merge	in_p2,io_ports+2,2
	endc
	ifd AUTOPLAY				; (benchmark build: coin, start and random-ish play, period 4000 frames)
	moveq	#0,d0
	move.w	isr_count,d0
	divu	#4000,d0
	swap	d0
	cmp.w	#700,d0
	blo.s	.ap1
	cmp.w	#704,d0
	bhs.s	.ap1
	move.b	#$F7,io_ports			; coin 1
.ap1:	cmp.w	#760,d0
	blo.s	.ap2
	cmp.w	#764,d0
	bhs.s	.ap2
	move.b	#$FE,io_ports			; start 1
.ap2:	cmp.w	#840,d0
	blo.s	.ap3
	lsr.w	#4,d0
	and.w	#7,d0
	lea	ap_dirs(pc),a0
	move.b	(a0,d0.w),d0
	btst	#0,frame_counter+3
	beq.s	.ap4
	and.b	#$7F,d0				; punch every other frame
.ap4:	move.b	d0,io_ports+1
.ap3:
	endc
	addq.b	#1,vbl_pending		; one arcade frame a VBL, and a second one every 8th: 56.25 a second
	subq.b	#1,vbl_phase
	bpl.s	.ph
	move.b	#7,vbl_phase
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
ap_dirs:	dc.b	$FE,$FE,$FD,$FE,$DF,$FA,$FE,$F7	; (active low: right 0, left 1, down 2, up 3, kick 5)
	endc

; ------------------------------------------------------------------------------
; The idle hooks (gen.py: machine.KungFuPort.HOOKS; d7 = the pc): the foreground goes on (rts) unless it waits for
; the IRQ there; then the picture is drawn when due, the next arcade frame awaited and the IRQ (RST 38) delivered
; with TOKEN as its return address.  Its return (z80_irq_ret) continues after the hook (hook_resume): the instruction
; at the hook runs before its condition is looked at again.  When the handler restarts the foreground instead (012A,
; 0396: jp 0217, a new Z80 stack), the next hook simply comes; nothing waits on the 68000 stack: the hook took its
; continuation off it.
; ------------------------------------------------------------------------------

z80_hook:
	movem.l	d0-d7/a0-a6,-(sp)
	cmp.w	#$029C,d7		; the play loop: once a frame
	beq	.wait
	cmp.w	#$5714,d7
	beq.s	.e882
	cmp.w	#$0588,d7
	beq.s	.e882
	cmp.w	#$5061,d7
	beq.s	.e882
	cmp.w	#$542E,d7
	beq.s	.e882
	cmp.w	#$491B,d7
	beq.s	.e020_8
	cmp.w	#$4925,d7
	beq.s	.e020_b
	cmp.w	#$4946,d7
	beq.s	.e000_b
	cmp.w	#$4997,d7
	beq.s	.e000_b
	cmp.w	#$51B8,d7
	beq.s	.start
	cmp.w	#$03D2,d7
	beq.s	.release
	cmp.w	#$03D9,d7
	beq.s	.select
	cmp.w	#$7BE8,d7
	beq.s	.start2
	cmp.w	#$7BEF,d7
	beq.s	.start2_up
	bra	.busy
.e882:	tst.b	Z_RAM+$E882
	bne	.wait
	bra	.busy
.e020_8: cmp.b	#$08,Z_RAM+$E020
	bne	.wait
	bra	.busy
.e020_b: cmp.b	#$0B,Z_RAM+$E020
	bne	.wait
	bra	.busy
.e000_b: cmp.b	#$0B,Z_RAM+$E000
	bne	.wait
	bra	.busy
.start:	moveq	#3,d0
	and.b	Z_RAM+$E904,d0
	beq	.wait
	bra	.busy
.release: moveq	#-$60,d0		; ($A0)
	and.b	Z_RAM+$E906,d0
	bne	.wait
	bra	.busy
.select: btst	#1,Z_RAM+$E904
	bne	.busy
	moveq	#-$60,d0
	and.b	Z_RAM+$E906,d0
	beq	.wait
	bra	.busy
.start2: btst	#1,Z_RAM+$E904
	beq	.wait
	bra	.busy
.start2_up: btst #1,Z_RAM+$E904
	bne	.wait
.busy:	movem.l	(sp)+,d0-d7/a0-a6
	rts
.wait:	tst.b	frame_dirty
	beq	.check
	tst.b	vbl_pending
	beq	.render
	addq.b	#1,render_skips
	cmp.b	#MAX_SKIP,render_skips
	bls	.check
.render:
	clr.b	render_skips
	clr.b	frame_dirty
	ifd SIM
	bsr	sim_render_start
	endc
	bsr	render_frame
	ifd SIM
	bsr	sim_frame_done
	endc
.check:
	tst.b	vbl_pending
	bne	.deliver
	ifd SIM
	bsr	sim_wait
	bra	.check
	else
	bra	.check
	endc
.deliver:
	ifd PLAYBACK
	bsr	pb_inputs
	endc
	ifnd NOSOUND
	bsr	snd_frame		; (the sound board: the commands of the frame before, its ticks; sound.s)
	endc
	movem.l	(sp)+,d0-d7/a0-a6
	move.l	(sp)+,hook_resume	; (the continuation: after the IRQ)
	subq.b	#1,vbl_pending
	st	frame_dirty
	addq.w	#1,isr_count
	move.w	#TOKEN,-(a5)
	jmp	Z0038
z80_irq_ret:
	move.l	hook_resume,-(sp)
	rts

	ifd PLAYBACK
; The recorded play (tools/play_search.py, build/kungfum/play_inputs.bin; engine/playbot.py: runs of count, SYSTEM,
; P1, a count of 0 at the end): the inputs of the arcade frame about to run, and from frame PB_PLAY on the bot's
; infinite lives ($E084 = 6), as the bot had them.
	ifnd PB_PLAY
PB_PLAY = 900
	endc
pb_inputs:
	tst.b	pb_left
	bne.s	.same
	move.l	pb_ptr,a0
	cmp.w	#0,a0
	bne.s	.next
	lea	pb_data,a0
.next:	move.b	(a0)+,pb_left
	bne.s	.run
	st	quit_flag		; (the recording is over)
	rts
.run:	move.b	(a0)+,pb_sys
	move.b	(a0)+,pb_p1
	move.l	a0,pb_ptr
.same:	subq.b	#1,pb_left
	move.b	pb_sys,io_ports
	move.b	pb_p1,io_ports+1
	move.b	#$FF,io_ports+2
	cmp.w	#PB_PLAY,isr_count
	blo.s	.out
	move.b	#6,Z_RAM+$E084
.out:	rts
	endc

; `out (0),a`: the sound command (d0) into the ring (a player would read it); keeps the registers and the flags.
kf_sound:
	move	sr,-(sp)
	move.l	a0,-(sp)
	move.w	d7,-(sp)
	lea	snd_ring,a0
	moveq	#0,d7
	move.b	snd_head,d7
	move.b	d0,(a0,d7.w)
	addq.b	#1,snd_head
	move.w	(sp)+,d7
	move.l	(sp)+,a0
	move	(sp)+,ccr
	rts

; The tile RAM's stores (gen.py tile_marks): mark the 64-byte row (codes $D000-$D7FF, attributes $D800-$DFFF share
; it) the address hits.  Keep everything but d7 (a translator scratch register), the flags too.
kf_mark_hl:
	move	sr,-(sp)
	move.w	d3,d7
kf_mark_d7:
	lsr.w	#6,d7
	and.w	#31,d7
	move.l	a0,-(sp)
	lea	tile_rows,a0
	st	(a0,d7.w)
	move.l	(sp)+,a0
	move	(sp)+,ccr
	rts
kf_mark_de:
	move	sr,-(sp)
	move.w	d2,d7
	bra.s	kf_mark_d7
kf_mark_bc:
	move	sr,-(sp)
	move.w	d1,d7
	ror.w	#8,d7
	bra.s	kf_mark_d7
kf_mark_ix:				; (the displacement on the stack, above the return address)
	move	sr,-(sp)
	move.w	d4,d7
	add.w	8(sp),d7
	bra.s	kf_mark_d7
kf_mark_iy:
	move	sr,-(sp)
	move.w	a2,d7
	add.w	8(sp),d7
	bra.s	kf_mark_d7
kf_mark_all:
	move	sr,-(sp)
	move.l	a0,-(sp)
	lea	tile_rows,a0
	rept	8
	move.l	#-1,(a0)+
	endr
	move.l	(sp)+,a0
	move	(sp)+,ccr
	rts

; `ld a,r` (the refresh register): a pseudo random byte; the reference (machine.KungFuPort.rnd) has the same.
z80_rnd:
	move.w	rnd_state,d7
	lsr.w	#1,d7
	bcc.s	.no
	eor.w	#$B400,d7
.no:	move.w	d7,rnd_state
	move.b	d7,d0
	rts

	borders_handlers
	jagpad_text
	jagpad_maps
	borders_blit_go

; ------------------------------------------------------------------------------
; Keyboard / joystick (IKBD): SYSTEM, P1 and P2 are active low bytes
; ------------------------------------------------------------------------------

acia_isr:
	movem.l	d0-d2/a0,-(sp)
.again:
	ikbd_byte
.not_esc:
	lea	key_table,a0
.find:	move.b	(a0),d0
	beq	.again
	cmp.b	d0,d1
	beq	.found
	addq	#4,a0
	bra	.find
.found:	tst.b	d2
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
.joy1:	move.b	d1,joy1_state
.joy_update:
	; joystick 1 (port 1) plays player 1, joystick 0 player 2: right 0, left 1, down 2, up 3, fire = punch (7)
	move.b	joy1_state,d1
	bsr	.joy
	move.b	d0,p1_joy
	move.b	joy0_state,d1
	bsr	.joy
	move.b	d0,p2_joy
	bsr	compose_inputs
	bra	.again
.joy:	moveq	#0,d0
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
	bset	#7,d0
.j5:	rts
.done:	movem.l	(sp)+,d0-d2/a0
	rte

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

; scancode, SYSTEM bits (start 1 = 0, start 2 = 1, coin 1 = 3), P1 bits (right 0, left 1, down 2, up 3, kick 5,
; punch 7), P2 bits (coin 2 = 4)
key_table:
	dc.b	$4d,$00,$01,$00		; right
	dc.b	$4b,$00,$02,$00		; left
	dc.b	$50,$00,$04,$00		; down
	dc.b	$48,$00,$08,$00		; up
	dc.b	$39,$00,$80,$00		; space = punch
	dc.b	$1d,$00,$80,$00		; control = punch
	dc.b	$2c,$00,$80,$00		; Z = punch
	dc.b	$38,$00,$20,$00		; alternate = kick
	dc.b	$2d,$00,$20,$00		; X = kick
	dc.b	$02,$01,$00,$00		; 1 = start 1
	dc.b	$03,$02,$00,$00		; 2 = start 2
	dc.b	$06,$08,$00,$00		; 5 = coin 1
	dc.b	$07,$00,$00,$10		; 6 = coin 2
	dc.b	0,0,0,0
	even

; ------------------------------------------------------------------------------
; Crash dump (CRASH.TXT: vector, registers, the stack top)
; ------------------------------------------------------------------------------

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
.regs:	move.l	(a1)+,d1
	bsr	hex_long
	move.b	#' ',(a0)+
	dbf	d2,.regs
	move.b	#13,(a0)+
	move.b	#10,(a0)+
	move.l	crash_sp,a1
	moveq	#15,d2
.stack:	move	(a1)+,d1
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
sim_wait:				; the test harness stops here when the foreground waits with nothing pending: it
	bra.s	sim_wait		; sets vbl_pending (and the inputs) and returns (rts) from here
sim_render_start:			; (render_test.py measures from here)
	bra.s	sim_render_start
sim_frame_done:				; the harness compares here (a picture is drawn), returns with rts
	bra.s	sim_frame_done
sim_render_ret:				; render_test.py calls render_frame with this as the return address
	bra.s	sim_render_ret
	endc

z80_halt:				; (not in the program: a halt in data taken for code)
	move.l	frame_counter,d7
.wait:	cmp.l	frame_counter,d7
	beq.s	.wait
	rts

	ifd DEBUG
; COUNTERS.BIN (words): VBLs, pictures, arcade frames, the frames whose top border the VBL armed, the late border
; events (engine/rt/borders.s); RATE.BIN: (arcade frames, pictures) every 100 VBLs
dbg_counters:
	lea	dbg_buf,a0
	move.w	frame_counter+2,(a0)+
	move.w	pic_count,(a0)+
	move.w	isr_count,(a0)+
	move.w	bd_fallbacks,(a0)+
	move.w	bd_late_top,(a0)+
	move.w	bd_late_on,(a0)+
	move.w	bd_late_low,(a0)+
	move.w	bd_late_off,(a0)+
	move.l	bd_pieced,(a0)+
	lea	dbg_name3,a1
	lea	dbg_tl,a2
	move.l	dbg_tl_p,d0
	sub.l	a2,d0
	bsr	dbg_write
	lea	dbg_name2,a1
	lea	dbg_buf,a2
	moveq	#20,d0
	bsr	dbg_write
	rts
dbg_write:				; a1 = the name, a2 = the data, d0.l = its length
	movem.l	d0/a2,-(sp)
	clr	-(sp)
	move.l	a1,-(sp)
	move	#$3c,-(sp)
	trap	#1
	addq	#8,sp
	move	d0,d6
	movem.l	(sp)+,d0/a2
	move.l	a2,-(sp)
	move.l	d0,-(sp)
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
dbg_name3:
	dc.b	"RATE.BIN",0
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
	moveq	#99,d0			; the dump: d7 = the address
	bra	crash_common

	include	"render.s"
	ifnd NOSOUND
	include	"sound.s"
	endc

; ------------------------------------------------------------------------------
; The translated program (and its dispatch table in the data section)
	include	"code_kungfum.s"

	section text,code
	include	"rtlib.s"

	section data,data
	ifd PLAYBACK
pb_data:	incbin	"play_inputs.bin"
	even
	endc

; The Z80's 64 KB (a6 = its address 0, signed offsets): $8000-$FFFF (RAM, zero) first, then the ROM at $0000-$7FFF.
	cnop	0,4
g_block:	dcb.b	$8000,0
	incbin	"kungfum.rom"

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
hook_resume:	ds.l	1
old_res:	ds.b	1
old_hz:		ds.b	1
old_linewid:	ds.b	1
old_fine:	ds.b	1
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
vbl_pending:	ds.b	1		; arcade frames that have come (the VBL adds, the hook takes one)
vbl_phase:	ds.b	1
render_skips:	ds.b	1
frame_dirty:	ds.b	1		; an arcade frame ran since the last picture
io_ports:	ds.b	8		; what `in a,(n)` reads: SYSTEM, P1, P2, DSW1, DSW2
io_flip:	ds.b	1		; `out (1),a`
snd_head:	ds.b	1
	even
tile_rows:	ds.b	32		; the tile RAM rows written since the renderer looked (kf_mark_*)
snd_ring:	ds.b	256		; the sound commands (the last 256)
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
rnd_state:	ds.w	1
isr_count:	ds.w	1
pic_count:	ds.w	1
	ifd PLAYBACK
pb_ptr:		ds.l	1
pb_left:	ds.b	1
pb_sys:		ds.b	1
pb_p1:		ds.b	1
	even
	endc
	ifd DEBUG
dbg_tl_n:	ds.w	1
dbg_tl_p:	ds.l	1
dbg_tl:		ds.l	400		; (40000 VBLs)
dbg_tl_end:
dbg_buf:	ds.l	16
	endc
crash_vector:	ds.w	1
crash_sp:	ds.l	1
crash_regs:	ds.l	16
crash_text:	ds.b	512
frame_counter:	ds.l	1
	ds.l	1024
own_stack_top:
