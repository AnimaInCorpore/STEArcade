; Moon Patrol (Irem M52, 1982) for the Atari STE: the main Z80 program translated (tools/gen.py ->
; build/mpatrol/code_mpatrol.s).  So far the logic only, for the simulator (SIM: tools/logic_test.py); the STE's
; hardware, the picture and the sound come with the renderer.

	ifnd SIM
	fail	"Moon Patrol: only the simulator build (SIM) so far"
	endc
	ifnd MAX_SKIP
MAX_SKIP = 2				; arcade frames in a row that are not drawn while the game is behind
	endc

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
	lea	own_stack_top,sp
	move.w	#$ACE1,rnd_state
	bsr	put_inputs		; (the harness set io_in: the DIP switches of its seed)

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

; The memory-mapped inputs live in the Z80 block ($D000-$D004: IN0, IN1, IN2, DSW1, DSW2; the program reads them
; there, also through (de) and (hl)): io_in is copied there when an arcade frame starts.
put_inputs:
	move.l	io_in,Z_RAM+$D000
	move.b	io_in+4,Z_RAM+$D004
	rts

; ------------------------------------------------------------------------------
; The idle hooks (gen.py: machine.MoonPatrolPort.HOOKS and IRQ_WAITS; d7 = the pc): the foreground goes on (rts)
; unless it waits for the IRQ there; then the picture is drawn when due, the next arcade frame awaited and the IRQ
; (RST 38) delivered with TOKEN as its return address.  Its return (z80_irq_ret) continues after the hook
; (hook_resume): the instruction at the hook runs before its condition is looked at again.  When the handler restarts
; the foreground instead (0104: a new Z80 stack), the next hook simply comes.  An IRQ wait ($00AF, the stop mode:
; inside the handler) waits for the next arcade frame and goes on there, without an IRQ.
; ------------------------------------------------------------------------------

z80_hook:
	movem.l	d0-d7/a0-a6,-(sp)
	cmp.w	#$026E,d7		; the work loop: once a frame
	beq	.wait
	cmp.w	#$05ED,d7
	beq.s	.e050
	cmp.w	#$0359,d7
	beq.s	.e050
	cmp.w	#$0315,d7
	beq.s	.e050
	cmp.w	#$078E,d7
	beq.s	.e047
	cmp.w	#$010D,d7
	beq.s	.start
	cmp.w	#$01A7,d7
	beq.s	.cont
	cmp.w	#$0B59,d7
	beq.s	.select
	cmp.w	#$00AF,d7
	beq.s	.stop
	bra.s	.busy
.e050:	tst.b	Z_RAM+$E050		; a wait of $E050 frames
	bne.s	.wait
	bra.s	.busy
.e047:	tst.b	Z_RAM+$E047
	bne.s	.wait
	bra.s	.busy
.start:	bsr	starts			; push start
	beq.s	.wait
	bra.s	.busy
.cont:	tst.b	Z_RAM+$E050		; the continue's countdown
	beq.s	.busy
	tst.b	Z_RAM+$E048
	beq.s	.wait
	bsr	starts
	beq.s	.wait
	bra.s	.busy
.select: cmp.b	#1,Z_RAM+$E051		; sector selection: until the time runs out
	bhi.s	.wait
	bra.s	.busy
.stop:	btst	#0,Z_RAM+$D000		; stop mode: the handler waits for start 1
	beq.s	.busy
	bsr	next_frame
	movem.l	(sp)+,d0-d7/a0-a6
	rts
.busy:	movem.l	(sp)+,d0-d7/a0-a6
	rts
.wait:	bsr	next_frame
	movem.l	(sp)+,d0-d7/a0-a6
	move.l	(sp)+,hook_resume	; (the continuation: after the IRQ)
	move.w	#TOKEN,-(a5)
	jmp	Z0038
z80_irq_ret:
	move.l	hook_resume,-(sp)
	rts

; 0533's start check (machine.MoonPatrolPort.starts): ne when start 1, or start 2 with more than one credit
starts:
	btst	#0,Z_RAM+$E053
	bne.s	.yes
	btst	#1,Z_RAM+$E053
	beq.s	.no
	cmp.b	#1,Z_RAM+$E048
	beq.s	.no
.yes:	moveq	#-1,d7
	rts
.no:	moveq	#0,d7
	rts

; The end of an arcade frame: the picture when due, then the next arcade frame (its inputs into the block).
next_frame:
	tst.b	frame_dirty
	beq.s	.check
	tst.b	vbl_pending
	beq.s	.render
	addq.b	#1,render_skips
	cmp.b	#MAX_SKIP,render_skips
	bls.s	.check
.render:
	clr.b	render_skips
	clr.b	frame_dirty
	bsr	sim_render_start
	bsr	render_frame
	bsr	sim_frame_done
.check:	tst.b	vbl_pending
	bne.s	.go
	bsr	sim_wait
	bra.s	.check
.go:	subq.b	#1,vbl_pending
	st	frame_dirty
	addq.w	#1,isr_count
	bra	put_inputs

render_frame:				; (the renderer comes later)
	rts

; ------------------------------------------------------------------------------
; The latches and the I/O ports (gen.py): they keep the registers (but d7) and the flags (but mp_outi's)
; ------------------------------------------------------------------------------

; `ld ($D000),a`: the sound command (d0) into the ring; IN0 back into the block
mp_sound:
	move	sr,-(sp)
	move.l	a0,-(sp)
	lea	snd_ring,a0
	moveq	#0,d7
	move.b	snd_head,d7
	move.b	d0,(a0,d7.w)
	addq.b	#1,snd_head
	move.b	io_in,Z_RAM+$D000
	move.l	(sp)+,a0
	move	(sp)+,ccr
	rts

; `ld ($D001),a`: the flip latch and the coin counters; IN1 back into the block
mp_flip:
	move	sr,-(sp)
	move.b	d0,io_flip
	move.b	io_in+1,Z_RAM+$D001
	move	(sp)+,ccr
	rts

; `out ($C0),a`: the background control
mp_out_c0:
	move	sr,-(sp)
	move.b	d0,io_regs+6
	move	(sp)+,ccr
	rts

; `out (c),a`: the port is C (d1's high byte)
mp_out_c:
	move	sr,-(sp)
	move.w	d1,d7
	lsr.w	#8,d7
	bsr.s	mp_port
	move	(sp)+,ccr
	rts

; `outi`: (hl) to port C, hl + 1, b - 1; returns with the CCR's N and Z of b - 1 and C the carry of (hl) + l (MAME)
mp_outi:
	move.l	d0,-(sp)
	move.w	d1,d7
	lsr.w	#8,d7
	move.b	(a6,d3.w),d0
	bsr.s	mp_port
	addq.w	#1,d3
	add.b	d3,d0
	scs	d7
	move.l	(sp)+,d0
	subq.b	#1,d1
	move	sr,-(sp)
	andi.w	#$FFFE,(sp)
	tst.b	d7
	beq.s	.out
	ori.w	#1,(sp)
.out:	move	(sp)+,ccr
	rts

; d7.b = the port, d0.b = the byte: io_regs + (port >> 5); port $40 (background 1 x) also sets the protection read
; at $8800: popcount(x & $7F) ^ (x >> 7).  Keeps everything but d7 and the flags.
mp_port:
	movem.l	d0-d1/a0,-(sp)
	and.w	#$E0,d7
	lsr.w	#5,d7
	lea	io_regs,a0
	move.b	d0,(a0,d7.w)
	cmp.w	#2,d7
	bne.s	.out
	moveq	#0,d7
	moveq	#6,d1
.count:	btst	d1,d0
	beq.s	.zero
	addq.b	#1,d7
.zero:	dbf	d1,.count
	btst	#7,d0
	beq.s	.put
	eor.b	#1,d7
.put:	move.b	d7,Z_RAM+$8800
.out:	movem.l	(sp)+,d0-d1/a0
	rts

; `ld a,r` (the refresh register): a pseudo random byte; the reference (machine.MoonPatrolPort.rnd) has the same.
z80_rnd:
	move.w	rnd_state,d7
	lsr.w	#1,d7
	bcc.s	.no
	eor.w	#$B400,d7
.no:	move.w	d7,rnd_state
	move.b	d7,d0
	rts

sim_wait:				; the test harness stops here when the foreground waits with nothing pending: it
	bra.s	sim_wait		; sets vbl_pending (and the inputs) and returns (rts) from here
sim_render_start:			; (render tests measure from here)
	bra.s	sim_render_start
sim_frame_done:				; the harness compares here (a picture is drawn), returns with rts
	bra.s	sim_frame_done

z80_halt:				; (not in the program: a halt in data taken for code)
	rts

; Fatal errors of the translated code (d7 = the address)
z80_badpc:
z80_badjump:
z80_unsupported:
	move	#$2700,sr
	bra.s	z80_badpc

crash_common:				; (rtlib.s's crash notice; not used by the simulator build)
	bra.s	crash_common

; ------------------------------------------------------------------------------
; The translated program (and its dispatch table in the data section)
	include	"code_mpatrol.s"

	section text,code
	include	"rtlib.s"

	section data,data
; The Z80's 64 KB (a6 = its address 0, signed offsets): $8000-$FFFF (RAM, zero) first, then the ROM at $0000-$7FFF.
	cnop	0,4
g_block:	dcb.b	$8000,0
	incbin	"mpatrol.rom"

; ------------------------------------------------------------------------------
	section bss,bss
; ------------------------------------------------------------------------------
	even
hook_resume:	ds.l	1
io_in:		ds.b	8		; IN0, IN1, IN2, DSW1, DSW2 (active low; the harness / the IKBD keeps them)
io_regs:	ds.b	8		; the I/O ports by port >> 5: 0 text scroll, 2 / 3 bg 1 x / y, 4 / 5 bg 2 x / y, 6 control
vbl_pending:	ds.b	1		; arcade frames that have come (the VBL adds, the hook takes one)
render_skips:	ds.b	1
frame_dirty:	ds.b	1		; an arcade frame ran since the last picture
io_flip:	ds.b	1		; `ld ($D001),a`
snd_head:	ds.b	1
	even
snd_ring:	ds.b	256		; the sound commands (the last 256)
rnd_state:	ds.w	1
isr_count:	ds.w	1
frame_counter:	ds.l	1
	ds.l	1024
own_stack_top:
