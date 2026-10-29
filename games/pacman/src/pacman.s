; Pac-Man (Namco / Midway, 1980) for the Atari STE: the Z80 program translated (tools/gen.py -> build/pacman/
; code_main.s), the turned picture drawn by render.s (274 lines: the top and bottom border open, engine/rt/borders.s).
;
; The schedule (machine.PacmanPort): the foreground waits at the task loop's spin ($238D, the hook: the task ring's
; read entry has bit 7 set) and at the boot's halt ($234A).  There the picture is drawn when due, the next arcade frame
; awaited, and the IRQ delivered when latch bit 0 ($5000) and IFF1 (pm_iff) allow it: the 68000 stack is reset, the
; waiting pc pushed on the Z80 stack, and the IM 2 vector's target entered ($3FFA -> $3000 at boot, $3FFC -> $008D).
; The frame handler's reti returns to $238D through the dispatch table, and the hook looks at the ring again.

	ifnd MAX_PENDING
MAX_PENDING = 3				; arcade frames that may be waiting (the game catches up after a slow picture)
	endc
	ifnd MAX_SKIP
MAX_SKIP = 3				; arcade frames in a row that are not drawn while the game is behind
	endc
	ifnd FRAMES
FRAMES = 0
	endc

KEY_ESC = $01

; Border removal (engine/rt/borders.s, Galaga's timing): Hatari shows 274 lines from the video base, one palette.
	ifnd TA_DATA
TA_DATA = 98
	endc
	ifnd TA_NOPS
TA_NOPS = 84
	endc
BD_PALETTE = 0
	include	"borders.s"
	include	"ikbd.s"

; The Z80's 64 KB: a6 = g_block + $8000 = Z80 address 0 (signed word offsets: $8000-$FFFF lie below a6).
G_Z80 = g_block+$8000
IO_IN0 = G_Z80+$5100			; what the reads of $5000, $5040, $5080, $50C0 give (gen.py IO_IN)
IO_IN1 = G_Z80+$5101
IO_DSW1 = G_Z80+$5102
IO_DSW2 = G_Z80+$5103
LATCH_IRQ = G_Z80+$5000			; latch bit 0: the IRQ enable (plain stores of the program)
HOOK_RET = $8D23			; $238D on the Z80 stack, byte swapped

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
	bsr	snd_init

	lea	G_Z80+$4800,a0		; the empty addresses $4800-$4BFF read $BF (machine.Pacman.rd8)
	move	#$400/4-1,d0
.hole:	move.l	#$BFBFBFBF,(a0)+
	dbf	d0,.hole
	ifnd SIM			; (the test harness sets the ports, the DIP switches of its seed)
	move.b	#$C9,IO_DSW1		; DSW1: 1 coin 1 credit, 3 lives, bonus 10000, normal, normal ghost names
	ifd DSW1
	move.b	#DSW1,IO_DSW1
	endc
	move.b	#$FF,IO_IN0		; IN0, IN1: nothing pressed, upright
	move.b	#$FF,IO_IN1
	clr.b	IO_DSW2
	endc
	move.b	#$FF,in0_kbd
	move.b	#$FF,in1_kbd

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
	move.b	$ffff8201.w,old_screen+1
	move.b	$ffff8203.w,old_screen+2
	move.b	$ffff820d.w,old_screen+3
	clr.b	$ffff8260.w		; low resolution, 50 Hz
	move.b	#2,$ffff820a.w
	move.b	$fffffa07.w,old_fa07
	move.b	$fffffa09.w,old_fa09
	move.b	$fffffa13.w,old_fa13
	move.b	$fffffa15.w,old_fa15
	move.b	$fffffa17.w,old_fa17
	move.l	$68.w,old_hbl
	move.l	$70.w,old_vbl
	move.l	$118.w,old_acia
	move.l	$120.w,old_timer_b
	move.l	$134.w,old_timer_a
	move.b	$fffffa19.w,old_fa19
	move.b	$fffffa1b.w,old_fa1b
	move.b	$fffffa1d.w,old_fa1d
	move.b	$fffffa1f.w,old_fa1f
	move.b	$fffffa21.w,old_fa21
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
	endc
	rts

restore_hardware:
	move	#$2700,sr
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
	move.l	old_timer_b,$120.w
	move.l	old_timer_a,$134.w
	move.l	old_hbl,$68.w
	move.l	old_vbl,$70.w
	move.l	old_acia,$118.w
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

; The VBL: the inputs copied into the ports the program reads, the arcade's frames counted: 60 Hz against the STE's
; 50, six to five VBLs.
vbl:
	ifnd SIM
	borders_vbl			; (first: Timer B counts the frame's lines)
	endc
	movem.l	d0-d1/a0,-(sp)
	addq.l	#1,frame_counter
	tst.b	quit_flag
	bne	quit
	bsr	vbl_video
	ifnd SIM
	move.b	in0_kbd,IO_IN0
	move.b	in1_kbd,IO_IN1
	endc
	ifd AUTOPLAY				; (measuring build: a coin and start, then the joystick in a new direction
	move.l	frame_counter,d0	; every 24 VBLs; period 6000 VBLs: a new game after a game over)
	divu	#6000,d0
	swap	d0
	cmp.w	#400,d0
	blo.s	.ap
	cmp.w	#404,d0
	bhs.s	.ap1
	move.b	#$DF,IO_IN0		; coin 1
	bra.s	.ap
.ap1:	cmp.w	#460,d0
	blo.s	.ap
	cmp.w	#464,d0
	bhs.s	.ap2
	move.b	#$DF,IO_IN1		; start 1
	bra.s	.ap
.ap2:	moveq	#0,d0
	move.w	frame_counter+2,d0
	lsr.w	#3,d0
	divu	#3,d0
	mulu	#$9E37,d0		; (a direction per 24 VBLs, scrambled)
	swap	d0
	and.w	#3,d0
	move.b	.ap_dirs(pc,d0.w),IO_IN0
	bra.s	.ap
.ap_dirs:	dc.b	$FE,$FD,$FB,$F7		; (active low: up, left, right, down)
.ap:
	endc
	addq.b	#1,vbl_pending		; one arcade frame a VBL, and a second one every 5th: 60 a second
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

; ------------------------------------------------------------------------------
; The idle hook (gen.py HOOKS: $238D, d7 = the pc): the foreground goes on (rts) while the task ring holds an entry
; (the byte at the address in $4C82 without bit 7); else the next arcade frame (pm_frame) and the IRQ.
; ------------------------------------------------------------------------------

z80_hook:
	movem.l	d0/a0,-(sp)
	moveq	#0,d0
	move.b	G_Z80+$4C83,d0		; (the ring pointer: little-endian)
	lsl.w	#8,d0
	move.b	G_Z80+$4C82,d0
	lea	G_Z80,a0
	tst.b	(a0,d0.l)
	bmi.s	.wait
	movem.l	(sp)+,d0/a0
	rts
.wait:	movem.l	(sp)+,d0/a0
	bsr	pm_frame
	tst.b	pm_deliver
	bne.s	.irq
	rts				; (no IRQ: the frame passes, the spin goes on)
.irq:	lea	own_stack_top,sp	; (the foreground waits at its top level: nothing on the 68000 stack is needed)
	move.w	#HOOK_RET,-(a5)
	bra	pm_irq

; The boot's halt ($234A; d7 = the next pc): frames pass until the IRQ comes; it returns to the next pc.  SP is $FFFF
; there (odd): the return address is pushed byte by byte.
pm_halt:
	move.w	d7,-(sp)
.next:	bsr	pm_frame
	tst.b	pm_deliver
	beq.s	.next
	move.w	(sp)+,d7
	lea	own_stack_top,sp
	subq.l	#2,a5
	move.b	d7,(a5)			; (low byte at the lower address)
	lsr.w	#8,d7
	move.b	d7,1(a5)
	; (falls through)

; The IRQ: IFF1 off, the IM 2 vector's target (the word at $3F00 + the vector) through the dispatch table.
pm_irq:
	clr.b	pm_iff
	moveq	#0,d7
	move.b	pm_vector,d7
	lea	G_Z80+$3F00,a0
	move.w	(a0,d7.w),d7		; (the target byte swapped: the dispatch table's index)
	add.l	d7,d7
	add.l	d7,d7
	move.l	(a4,d7.l),a0
	jmp	(a0)

; One arcade frame: the picture when due, the wait for the frame, then pm_deliver = whether the IRQ is taken (latch
; bit 0 and IFF1).  Keeps the registers and the flags.
pm_frame:
	move	sr,-(sp)
	movem.l	d0-d7/a0-a6,-(sp)
	tst.b	frame_dirty
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
	endc
	bra	.check
.deliver:
	subq.b	#1,vbl_pending
	st	frame_dirty
	addq.w	#1,isr_count
	bsr	snd_update		; (the WSG as the last frame's handler left it)
	clr.b	pm_deliver
	btst	#0,LATCH_IRQ
	beq.s	.out
	tst.b	pm_iff
	beq.s	.out
	st	pm_deliver
.out:	movem.l	(sp)+,d0-d7/a0-a6
	move	(sp)+,ccr
	rts

; The video and colour RAM's stores (gen.py tile_marks): the cell (address & $3FF: code $4000-$43FF and colour
; $4400-$47FF share it) listed once in cell_list (cell_dirty: its flag) for the renderer.  Keep everything but d7 and
; a0 (the translator's scratch registers), the flags too.
pm_mark_hl:
	move	sr,-(sp)
	move.w	d3,d7
pm_mark_d7:
	and.w	#$3FF,d7
	lea	cell_dirty,a0		; (a0: a scratch register of the translated code)
	tst.b	(a0,d7.w)
	bne.s	.out
	st	(a0,d7.w)
	move.l	cell_ptr,a0
	move.w	d7,(a0)+
	move.l	a0,cell_ptr
.out:	move	(sp)+,ccr
	rts
pm_mark_de:
	move	sr,-(sp)
	move.w	d2,d7
	bra.s	pm_mark_d7
pm_mark_bc:
	move	sr,-(sp)
	move.w	d1,d7
	ror.w	#8,d7
	bra.s	pm_mark_d7
pm_mark_ix:				; (the displacement on the stack, above the return address)
	move	sr,-(sp)
	move.w	d4,d7
	add.w	8(sp),d7
	bra.s	pm_mark_d7
pm_mark_iy:
	move	sr,-(sp)
	move.w	a2,d7
	add.w	8(sp),d7
	bra.s	pm_mark_d7
pm_mark_n:				; (a static address: the cell on the stack)
	move	sr,-(sp)
	move.w	8(sp),d7
	bra.s	pm_mark_d7
pm_mark_all:
	st	tiles_all
	rts

	borders_handlers

; ------------------------------------------------------------------------------
; Keyboard / joystick (IKBD): IN0 and IN1 are active low bytes
; ------------------------------------------------------------------------------

acia_isr:
	movem.l	d0-d2/a0,-(sp)
.again:
	ikbd_byte
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
	or.b	d0,in0_keys
	move.b	2(a0),d0
	or.b	d0,in1_keys
	bsr	compose_inputs
	bra	.again
.release:
	move.b	1(a0),d0
	not.b	d0
	and.b	d0,in0_keys
	move.b	2(a0),d0
	not.b	d0
	and.b	d0,in1_keys
	bsr	compose_inputs
	bra	.again
.packet_byte:
	clr.b	ikbd_state
	moveq	#0,d0			; either joystick moves Pac-Man (upright: the players take turns)
	btst	#0,d1			; up
	beq.s	.j1
	bset	#0,d0
.j1:	btst	#2,d1			; left
	beq.s	.j2
	bset	#1,d0
.j2:	btst	#3,d1			; right
	beq.s	.j3
	bset	#2,d0
.j3:	btst	#1,d1			; down
	beq.s	.j4
	bset	#3,d0
.j4:	move.b	d0,in0_joy
	bsr	compose_inputs
	bra	.again
.done:	movem.l	(sp)+,d0-d2/a0
	rte

compose_inputs:
	move.b	in0_keys,d0
	or.b	in0_joy,d0
	not.b	d0
	move.b	d0,in0_kbd
	move.b	in1_keys,d0
	not.b	d0
	move.b	d0,in1_kbd
	rts

; scancode, IN0 bits (up 0, left 1, right 2, down 3, coin 1 = 5, coin 2 = 6), IN1 bits (start 1 = 5, start 2 = 6)
key_table:
	dc.b	$48,$01,$00,$00		; up
	dc.b	$4b,$02,$00,$00		; left
	dc.b	$4d,$04,$00,$00		; right
	dc.b	$50,$08,$00,$00		; down
	dc.b	$02,$00,$20,$00		; 1 = start 1
	dc.b	$03,$00,$40,$00		; 2 = start 2
	dc.b	$06,$20,$00,$00		; 5 = coin 1
	dc.b	$07,$40,$00,$00		; 6 = coin 2
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

	ifd DEBUG
; COUNTERS.BIN (longs): VBLs, arcade frames, pictures drawn, pictures shown (tools/hatari.ps1)
dbg_counters:
	lea	dbg_buf,a0
	move.l	frame_counter,(a0)+
	moveq	#0,d0
	move.w	isr_count,d0
	move.l	d0,(a0)+
	move.w	pic_count,d0
	move.l	d0,(a0)+
	move.w	pic_shown,d0
	move.l	d0,(a0)+
	clr	-(sp)			; Fcreate
	pea	dbg_name
	move	#$3c,-(sp)
	trap	#1
	addq	#8,sp
	move	d0,d6
	pea	dbg_buf			; Fwrite
	move.l	#16,-(sp)
	move	d6,-(sp)
	move	#$40,-(sp)
	trap	#1
	lea	12(sp),sp
	move	d6,-(sp)		; Fclose
	move	#$3e,-(sp)
	trap	#1
	addq	#4,sp
	rts
dbg_name:
	dc.b	"COUNTERS.BIN",0
	even
	endc

	ifd SIM
sim_wait:				; the test harness stops here when the foreground waits with nothing pending: it
	bra.s	sim_wait		; sets vbl_pending (and the inputs) and returns (rts) from here
sim_render_start:			; (render_test.py measures from here)
	bra.s	sim_render_start
sim_frame_done:				; the harness compares here (a picture is drawn), returns with rts
	bra.s	sim_frame_done
sim_render_ret:				; sprite_test.py calls render_frame with this as the return address
	bra.s	sim_render_ret
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

; ------------------------------------------------------------------------------
; Sound: the WSG ($5040-$505F, written by the frame handler) on the YM2149, a square wave per voice (Galaga's
; snd_update without the explosion; latch bit 1, $5001, enables it).  tools/sound.py is the same in Python (ym_image),
; tools/sound_test.py compares them.
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
	st	snd_en			; (no WSG state seen yet: the first update writes)
	rts

; One arcade frame: the YM's registers 0-10 from the WSG cells.  Clobbers d0-d7 / a0-a2.
snd_update:
	moveq	#1,d0			; nothing to do when the WSG and the enable are as last time
	and.b	G_Z80+$5001,d0
	cmp.b	snd_en,d0
	bne.s	.changed
	lea	G_Z80+$5040,a0
	lea	snd_wsg,a1
	moveq	#8-1,d0
.cmp:	cmpm.l	(a0)+,(a1)+
	dbne	d0,.cmp
	bne.s	.changed
	rts
.changed:
	moveq	#1,d0
	and.b	G_Z80+$5001,d0
	move.b	d0,snd_en
	lea	G_Z80+$5040,a0
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
	tst.b	snd_en
	beq	.mix			; (the sound disabled: every voice off)
	lea	G_Z80+$5040,a0
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
	move.b	(a1,d3.w),d7		; (the waveform's strongest harmonic: an octave a shift)
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
.mix:	or.b	#$C0,d6
	move.b	d6,7(a2)
	lea	snd_ym,a0		; the registers that changed (no interrupt handler of the port touches the YM)
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

	include	"render.s"

; ------------------------------------------------------------------------------
; The translated program (and its dispatch table in the data section)
	include	"code_main.s"

	section text,code
	include	"rtlib.s"

	section data,data
; The Z80's 64 KB: $8000-$FFFF first (not on the board: A15 is not decoded, the program never goes there but for the
; boot halt's push below SP $FFFF), then the ROM at $0000-$3FFF, the RAM and I/O at $4000-$7FFF.
	cnop	0,4
g_block:	dcb.b	$8000,0
	incbin	"pacman.rom"
	dcb.b	$4000,0

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
	borders_vars
vbl_pending:	ds.b	1		; arcade frames that have come (the VBL adds, the hook takes one)
vbl_phase:	ds.b	1
render_skips:	ds.b	1
frame_dirty:	ds.b	1		; an arcade frame ran since the last picture
pm_vector:	ds.b	1		; the IM 2 vector (out ($00),a)
pm_iff:		ds.b	1		; IFF1 (ei / di)
pm_deliver:	ds.b	1		; pm_frame: the IRQ is taken
tiles_all:	ds.b	1		; (a block copy or fill into the video RAM: every cell)
	even
cell_ptr:	ds.l	1		; the end of cell_list (the renderer empties it)
cell_list:	ds.w	1024		; the video RAM cells written since the renderer looked (pm_mark_*), once each
cell_dirty:	ds.b	1024		; their flags
	ikbd_vars
in0_keys:	ds.b	1
in1_keys:	ds.b	1
in0_joy:	ds.b	1
in0_kbd:	ds.b	1
in1_kbd:	ds.b	1
	even
isr_count:	ds.w	1
snd_wsg:	ds.b	32		; the WSG cells at the last snd_update
snd_buf:	ds.b	12		; the YM registers of this frame
snd_ym:		ds.b	12		; the YM2149's registers 0-10 as written
snd_en:		ds.b	1		; latch bit 1 at the last snd_update
	even
crash_vector:	ds.w	1
crash_sp:	ds.l	1
crash_regs:	ds.l	16
crash_text:	ds.b	512
frame_counter:	ds.l	1
	ifd DEBUG
dbg_buf:	ds.l	4
	endc
	ds.l	1024
own_stack_top:
