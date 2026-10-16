; Double Dragon (Technos 1987) for the Atari STE: the translated main program (tools/gen.py, core.s), the sprite MCU
; as a native routine (mcu.s), the port's schedule of one arcade frame (core.s port_frame), the picture (render.s).
;
; The main loop: an arcade frame when the VBL has one pending (57.44 Hz on the STE's 50: eight frames to seven VBLs),
; the picture when no frame waits (or after MAX_SKIPS frames not drawn).  The simulator build (SIM, tools/logic_test.py,
; render_test.py): sim_wait (the harness sets the inputs) - one arcade frame - sim_frame_done - the picture when the
; harness asks (sim_render) - over and over.
KEY_ESC = $01
	ifnd PIC_TOP
PIC_TOP = 18				; the picture's first displayed line (240 lines, as Trojan's)
	endc
TA_DATA = 98
TA_NOPS = 84
PIC_LINES = 240
BD_PALETTE = 1
	ifnd FRAMES
FRAMES = 0
	endc
	ifnd MAX_SKIPS
MAX_SKIPS = 4				; arcade frames not drawn in a row while frames are pending (the game first)
	endc
	ifnd MAX_PENDING
MAX_PENDING = 3				; arcade frames that may wait (a game behind by more runs slower)
	endc

	section bss,bss
ring_area: ds.b RING_AREA		; (the display rings: render.s)
	section text,code
	include "borders.s"

; the pads (engine/rt/jagpad.s): P1, P2, EXTRA bits as in key_table (bytes 0-2 of each long)
JP_SH1 = 24
JP_SH2 = 16
JP_SHX = 8
JP1_RIGHT = $01<<JP_SH1
JP1_LEFT = $02<<JP_SH1
JP1_UP = $04<<JP_SH1
JP1_DOWN = $08<<JP_SH1
JP1_B1 = $10<<JP_SH1
JP1_B2 = $20<<JP_SH1
JP1_B3 = $02<<JP_SHX
JP2_RIGHT = $01<<JP_SH2
JP2_LEFT = $02<<JP_SH2
JP2_UP = $04<<JP_SH2
JP2_DOWN = $08<<JP_SH2
JP2_B1 = $10<<JP_SH2
JP2_B2 = $20<<JP_SH2
JP2_B3 = $04<<JP_SHX
JP_START1 = $40<<JP_SH1
JP_START2 = $80<<JP_SH1
JP_COIN1 = $40<<JP_SH2
JP_COIN2 = $80<<JP_SH2
	include	"jagpad.s"
	include	"ikbd.s"
BUSY = $80
HOG = $40

	section text,code
start:
    ifd SIM
	lea own_stack_top,sp
	bsr init_context
	bsr init_video
	lea in_bytes,a0
	move.b #$FF,(a0)+		; P1
	move.b #$FF,(a0)+		; P2
	move.b #$07,(a0)+		; EXTRA
	move.b dd_dsw,(a0)+		; DSW0
	move.b dd_dsw+1,(a0)+		; DSW1
.frame:
	jsr sim_wait
	bsr port_frame
	jsr sim_frame_done
	tst.b sim_render
	beq.s .frame
	bsr render_frame
	jsr sim_render_ret
	bra.s .frame

sim_wait:
	bra.s sim_wait
sim_frame_done:
	bra.s sim_frame_done
sim_render_ret:
	bra.s sim_render_ret
    else
	clr.l -(sp)
	move #$20,-(sp)
	trap #1
	addq #6,sp
	move.l d0,old_ssp
	lea own_stack_top,sp
	lea own_stack_top-4096,a0	; (the unused part of the stack marked: the crash dump says how deep it went)
	move #1024-1,d0
.mark:
	move.l #$A5A5A5A5,(a0)+
	dbf d0,.mark
	bsr init_context
	bsr init_hardware
	bsr init_video
	bsr snd_init
	move.b #$ff,in_p1
	move.b #$ff,in_p2
	move.b #$ff,in_ex
	move.b #$ff,m_p1
	move.b #$ff,m_p2
	move.b #$ff,m_ex
	lea in_bytes,a0
	move.b #$FF,(a0)+
	move.b #$FF,(a0)+
	move.b #$07,(a0)+
	move.b dd_dsw,(a0)+
	move.b dd_dsw+1,(a0)+
	move #$2300,sr
main_loop:
	tst.b quit_flag
	bne quit
	tst.b vbl_pending
	beq.s main_loop
	subq.b #1,vbl_pending
	addq.w #1,cnt_ticks
	ifd AUTOPLAY
	bsr ap_inputs
	endc
	bsr put_inputs
	bsr port_frame
	bsr snd_frame
	tst.b vbl_pending
	beq.s .draw
	addq.b #1,render_skips
	cmp.b #MAX_SKIPS+1,render_skips
	blo.s main_loop
.draw:	clr.b render_skips
	bsr render_frame
	addq.w #1,cnt_renders
	bra.s main_loop
    endc

; m_p1 / m_p2 / m_ex (the keyboard, the joysticks and the pads merged by the VBL) into in_bytes, where the I/O reads them: the coins and
; service are the port's pending presses (port_coins, set at a key's press in the VBL), never held bits.
put_inputs:
	move.b m_p1,in_bytes
	move.b m_p2,d0
	or.b #$C0,d0
	move.b d0,in_bytes+1
	move.b m_ex,d0
	or.b #$01,d0
	and.b #$07,d0
	move.b d0,in_bytes+2
	rts

hbl:
	rte

vbl:
	ifnd SIM
	borders_vbl
	endc
	movem.l d0-d7/a0,-(sp)
	addq.l #1,frame_counter
	ifnd AUTOPLAY
	bsr jagpad_poll			; (the pads merged)
	jp_merge in_p1,m_p1,0
	jp_merge in_p2,m_p2,1
	jp_merge in_ex,m_ex,2
	endc
	; a coin or service key pressed now (it was not before): the port's pending press
	move.b m_p2,d0
	not.b d0
	and.b #$C0,d0
	move.b m_ex,d1
	not.b d1
	and.b #$01,d1
	or.b d1,d0			; (held: coin 1 6, coin 2 7, service 0)
	move.b coins_held,d1
	move.b d0,coins_held
	not.b d1
	and.b d1,d0
	or.b d0,port_coins
	bsr vbl_video
	bsr snd_vbl
	cmp.b #MAX_PENDING,vbl_pending
	bhs.s .cap
	addq.b #1,vbl_pending
	; the arcade's 57.44 Hz on the STE's 50: eight frames to seven VBLs
	addq.b #1,tick_phase
	cmp.b #7,tick_phase
	blo.s .cap
	clr.b tick_phase
	addq.b #1,vbl_pending
.cap:
	if FRAMES
	cmp.l #FRAMES,frame_counter
	blo.s .go
	st quit_flag
.go:
	endc
	movem.l (sp)+,d0-d7/a0
	rte

	ifd AUTOPLAY
; (the benchmark build: the inputs by arcade frame, period 3000: a coin, the start, then walking right with punches;
; the same as tools/logic_test.py --auto)
ap_inputs:
	movem.l d0-d1,-(sp)
	moveq #0,d0
	move.w cnt_ticks,d0
	subq.w #1,d0
	divu #3000,d0
	swap d0
	cmp.w #900,d0
	bne.s .nc
	or.b #$40,port_coins
.nc:	moveq #-1,d1
	cmp.w #1000,d0
	blo.s .p1
	cmp.w #1006,d0
	bhs.s .walk
	and.b #~$40,d1			; start 1
	bra.s .p1
.walk:	cmp.w #1100,d0
	blo.s .p1
	and.b #~$01,d1			; right
	ext.l d0
	divu #45,d0
	swap d0
	cmp.w #8,d0
	bhs.s .p1
	and.b #~$10,d1			; punch
.p1:	move.b d1,m_p1
	move.b #$ff,m_p2
	move.b #$ff,m_ex
	movem.l (sp)+,d0-d1
	rts
	endc

	borders_handlers
	jagpad_text
	jagpad_maps
	borders_blit_go

	include "hardware.s"
	include "render.s"
	include "sound.s"
	include "rtlib.s"

z80_badpc:				; (rtlib.s's dispatch helper names it; not used here)
	bra main_badpc
port_crash:				; (core.s: a 6809 pc the translation does not have: CRASH.TXT names it)
	moveq #0,d7
	move.w badpc,d7
	swap d7
	move.w badslot,d7
	moveq #99,d0
	bra crash_common

	include "core.s"

	section data,data
dd_dsw:	dc.b $ff,$ff			; DSW0: 1 coin 1 credit, upright, no flip; DSW1: medium, demo sounds, 2 lives
	even

	section bss,bss
old_ssp: ds.l 1
old_screen: ds.l 1
old_palette: ds.l 8
old_exceptions: ds.l 10
old_hbl: ds.l 1
old_vbl: ds.l 1
old_acia: ds.l 1
old_timer_a: ds.l 1
old_timer_b: ds.l 1
old_res: ds.b 1
old_hz: ds.b 1
old_linewid: ds.b 1
old_fine: ds.b 1
old_fa07: ds.b 1
old_fa09: ds.b 1
old_fa13: ds.b 1
old_fa15: ds.b 1
old_fa17: ds.b 1
old_fa19: ds.b 1
old_fa1b: ds.b 1
old_fa1d: ds.b 1
old_fa1f: ds.b 1
old_fa21: ds.b 1
	borders_vars
	jagpad_vars
	ikbd_vars
quit_flag: ds.b 1
vbl_pending: ds.b 1
tick_phase: ds.b 1
render_skips: ds.b 1
sim_render: ds.b 1
coins_held: ds.b 1
joy0_state: ds.b 1
joy1_state: ds.b 1
p1_kbd: ds.b 1
p2_kbd: ds.b 1
ex_kbd: ds.b 1
p1_joy: ds.b 1
p2_joy: ds.b 1
in_p1: ds.b 1
in_p2: ds.b 1
in_ex: ds.b 1
m_p1: ds.b 1
m_p2: ds.b 1
m_ex: ds.b 1
	even
cnt_acia: ds.w 1
crash_vector: ds.w 1
crash_sp: ds.l 1
crash_regs: ds.l 16
crash_text: ds.b 512
frame_counter: ds.l 1
cnt_renders: ds.w 1
cnt_ticks: ds.w 1
	ds.b 8192
own_stack_top:
