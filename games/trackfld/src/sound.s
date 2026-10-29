; Track & Field's and Hyper Sports' sound on the STE (included by trackfld.s and hyperspt.s; tools/sound.py is the same
; in Python, tools/sound_test.py compares): the sound board's Z80 driver, translated (tools/sndgen.py ->
; build/<game>/snd_code.s, snd_data.s), drives an emulated SN76489A register file; its four voices (three tones and the
; noise) go to the YM2149's three channels each arcade frame (snd_ym: the three loudest, a voice keeping its YM channel
; while it lasts, Mr. Do!'s method).  The VLM5030's phrases and the tunes (the DAC and SN music the driver plays in
; cycle-timed loops) were rendered offline (sndgen.pcm) and play on the DMA sound (12517 Hz, 8 bits, mono).
;
; snd_frame (once an arcade frame, before its IRQ): the commands the game wrote since the last call (snd_ring) each run
; the driver's IRQ handler ($0038, TOKEN as the return address); while a tune plays (snd_acc below 0) only the last one
; is kept and delivered after it.  Then the frame's time (SND_FRAME_FX half Z80 cycles) runs ticks: each from the
; loop's code after the timer's wait (snd_tick_label) to the loop's head (snd_loop_label, the hook snd_hook, which goes
; on with the next tick while the time allows: 4096 cycles a tick, Hyper Sports with $400B set 2048).
;
; The VLM: the driver's stores of its pins (snd_vlm_pins) and data byte; BSY (snd_bsy) is high from ST's rising edge;
; ST's falling edge starts the phrase of the data byte (busy for its time, snd_busy_tab; its samples on the DMA), RST
; rising while busy stops it.  A tune (the native snd_tune at the tune routine): its measured effect at once (the RAM
; bytes and SN registers it leaves, its time taken from snd_acc and the VLM's busy time, its samples on the DMA).
;
; The driver's registers between runs: snd_regs (d0-d4, d6, a2, a5: z80x.FAST's map); a6 = snd_g + $8000 (its 64 KB,
; signed offsets: $8000-$FFFF below), a4 = snd_dispatch_sw.  The main program's registers are saved around a run.

	include	"snd_data.s"

SND_TOKEN = $FEFF			; $FFFE on the Z80 stack, byte swapped (sound.py TOKEN)
G_SND = snd_g+$8000

	section text,code

snd_init:
	movem.l	d0-d7/a0-a6,-(sp)
	move.b	snd_head,snd_tail
	clr.l	snd_acc
	clr.l	snd_busy
	move.w	#-1,snd_pending
	clr.l	snd_pins		; (ST, RST, the data byte, the SN's latched byte)
	clr.w	snd_dma_last
	move.w	#-1,snd_pin_addr
	clr.b	snd_dma_req
	lea	snd_sn,a0		; (8 words: periods 0, 2, 4, the noise control 6; volumes 1, 3, 5, 7: MAME's reset, 0)
	moveq	#8-1,d0
.s:	clr.w	(a0)+
	dbf	d0,.s
	clr.b	snd_sn_latch
	st	snd_dirty
	lea	snd_ym_cache,a0
	moveq	#16-1,d0
.y:	move.b	#$FF,(a0)+
	dbf	d0,.y
	move.l	#-1,snd_ymch		; (no voice on the YM's three: -1 bytes)
	lea	snd_regs,a0
	moveq	#8-1,d0
.r:	clr.l	(a0)+
	dbf	d0,.r
	move.l	#G_SND-1,snd_regs+28	; (a5: SP = $FFFF; the driver sets it)
	move.l	#X0000,snd_entry
	bsr	snd_run			; the boot: to the loop's head (no time: no tick)
	bsr	snd_ym
	ifnd SIM
	clr.b	$ffff8901.w
	endc
	movem.l	(sp)+,d0-d7/a0-a6
	rts

; snd_run: the driver from snd_entry until it comes back (snd_hook at the loop's head out of time, or snd_token_ret)
snd_run:
	move.l	sp,snd_sp0
	movem.l	snd_regs,d0-d4/d6/a2/a5
	lea	G_SND,a6
	lea	snd_dispatch_sw,a4
	move.l	snd_entry,a0
	jmp	(a0)
snd_hook:				; (d7 = the pc: only the loop's head is a hook; its resume label on the stack)
	addq.l	#4,sp
snd_next:				; the next tick if the frame's time allows it (TickBoard.run_frame)
	move.l	#SND_TICK_FX,d7
	ifne	SND_HS
	tst.b	SND_FAST(a6)		; ($400B: the fast ticks, the timer's bit 0)
	beq.s	.c
	lsr.l	#1,d7
.c:
	endc
	cmp.l	snd_acc,d7
	bgt.s	snd_back
	sub.l	d7,snd_acc
	tst.l	snd_busy		; (the VLM's busy time: counted down while above 0)
	ble.s	.t
	sub.l	d7,snd_busy
	bpl.s	.t
	clr.l	snd_busy
.t:	jmp	snd_tick_label
snd_back:
	movem.l	d0-d4/d6/a2/a5,snd_regs
	move.l	snd_sp0,sp
	rts
snd_token_ret:				; the IRQ handler returned: the loop's head it interrupted popped
	addq.l	#2,a5
	bra.s	snd_back

snd_badpc:
	move	#$2700,sr
	ifd SIM
.l:	bra.s	.l
	endc
	moveq	#97,d0
	bra	crash_common

; snd_frame: an arcade frame of the sound board.  Keeps all registers.
snd_frame:
	movem.l	d0-d7/a0-a6,-(sp)
	lea	snd_ring,a1
	tst.l	snd_acc
	bpl.s	.live
.wait:	moveq	#0,d0			; a tune plays: the commands wait, the last one kept
	move.b	snd_tail,d0
	cmp.b	snd_head,d0
	beq.s	.time
	addq.b	#1,snd_tail
	moveq	#0,d1
	move.b	(a1,d0.w),d1
	move.w	d1,snd_pending
	bra.s	.wait
.live:	move.w	snd_pending,d0
	bmi.s	.cmd
	move.w	#-1,snd_pending
	move.b	d0,snd_cmd
	bsr	snd_irq
.cmd:	moveq	#0,d0
	move.b	snd_tail,d0
	cmp.b	snd_head,d0
	beq.s	.time
	addq.b	#1,snd_tail
	move.b	(a1,d0.w),snd_cmd
	bsr	snd_irq
	bra.s	.cmd
.time:	add.l	#SND_FRAME_FX,snd_acc
	move.l	#snd_next,snd_entry
	bsr	snd_run
	tst.b	snd_dirty
	beq.s	.d
	bsr	snd_ym
.d:	tst.b	snd_dma_req
	beq.s	.out
	bsr	snd_dma
.out:	movem.l	(sp)+,d0-d7/a0-a6
	rts

snd_irq:				; the IRQ: the loop's head and TOKEN pushed, the handler run
	move.l	snd_regs+28,a5
	move.w	#SND_LOOP_SW,-(a5)
	move.w	#SND_TOKEN,-(a5)
	move.l	a5,snd_regs+28
	move.l	#X0038,snd_entry
	bra	snd_run

; ---- the chips, called from the translated driver: every register kept but d7 / a0 ------------------------------

; snd_bsy (`ld a,($E002)` / `ld a,($8000)`): d0 = BSY as the port shows it (the timer's bits 0: the waits are left out)
snd_bsy:
	moveq	#0,d0
	tst.l	snd_busy
	beq.s	.n
	moveq	#1<<SND_BSY_BIT,d0
.n:	rts

; snd_vlm_pins: d7 = the address of the store (ST and RST its bits SND_PIN_ST, SND_PIN_RST)
snd_vlm_pins:
	cmp.w	snd_pin_addr,d7		; (the drivers store the same pins every tick: nothing changes)
	bne.s	.new
	rts
.new:	move.w	d7,snd_pin_addr
	move.l	d1,-(sp)
	moveq	#0,d1
	btst	#SND_PIN_RST,d7
	sne	d1
	cmp.b	snd_rst,d1
	beq.s	.st
	move.b	d1,snd_rst
	beq.s	.st			; (falling: the parameter byte latched; the drivers latch 0)
	tst.l	snd_busy		; rising while busy: the chip reset, the phrase stopped
	beq.s	.st
	clr.l	snd_busy
	move.w	#$0300,d1
	bsr	snd_req
.st:	moveq	#0,d1
	btst	#SND_PIN_ST,d7
	sne	d1
	cmp.b	snd_st,d1
	beq.s	.x
	move.b	d1,snd_st
	beq.s	.go
	move.l	#-1,snd_busy		; rising: BSY high
	bra.s	.x
.go:	moveq	#0,d7			; falling: the phrase of the data byte
	move.b	snd_vlm_data,d7
	move.w	d7,d1
	or.w	#$0100,d1
	bsr	snd_req
	lsl.w	#2,d7
	lea	snd_busy_tab,a0
	move.l	(a0,d7.w),snd_busy
.x:	move.l	(sp)+,d1
	rts

snd_req:				; d1 = the DMA's request (kind << 8 | n: 1 a phrase, 2 a tune, 3 stop)
	move.w	d1,snd_dma_last
	st	snd_dma_req
	rts

; snd_sn_w (the strobe): the latched byte into the SN's registers (MAME sn76496_base_device::write)
snd_sn_w:
	movem.l	d1-d2,-(sp)
	st	snd_dirty
	move.b	snd_snl,d1
	bpl.s	.data
	moveq	#$70,d7			; a latch byte: the register, its low 4 bits
	and.b	d1,d7
	lsr.b	#4,d7
	move.b	d7,snd_sn_latch
.low:	ext.w	d7
	add.w	d7,d7
	lea	snd_sn,a0
	moveq	#$0F,d2
	and.b	d1,d2
	and.w	#$3F0,(a0,d7.w)
	or.w	d2,(a0,d7.w)
	movem.l	(sp)+,d1-d2
	rts
.data:	move.b	snd_sn_latch,d7		; a data byte: the latched register
	btst	#0,d7
	bne.s	.low			; (a volume: its low 4 bits)
	cmp.b	#6,d7
	beq.s	.low			; (the noise control: the same)
	ext.w	d7			; a period: bits 4-9
	add.w	d7,d7
	lea	snd_sn,a0
	moveq	#$3F,d2
	and.b	d1,d2
	lsl.w	#4,d2
	and.w	#$0F,(a0,d7.w)
	or.w	d2,(a0,d7.w)
	movem.l	(sp)+,d1-d2
	rts

; snd_idle: the native at the tick's start (TICK, `di`): a tick with nothing to do is done at once, else the
; translated tick runs (from the instruction after the `di`).  Idle: every channel started ($4001, $4003, $4005 set)
; with effect 0 ($4000, $4002, $4004 clear: the handler returns at once), no fast ticks / DAC envelope ($400B), no
; phrase queued (Track & Field $400F, Hyper Sports $4015).  What the driver's code then does: $4008 = 3, Hyper Sports
; $4010 = 0 and the VLM pins' word $402E with H bit 0 and L bits 6-7 set and stored to (03F4 with A = 0, C = 1); the
; registers it leaves (A, C, HL); on to the tune check before the loop's head (01A1 / 0231).  (SND_TICK_FX is a power of
; two: the remaining ticks' time is acc & -SND_TICK_FX.)
snd_idle:
	tst.b	$4000(a6)
	bne.s	.slow
	tst.b	$4002(a6)
	bne.s	.slow
	tst.b	$4004(a6)
	bne.s	.slow
	tst.b	$4001(a6)
	beq.s	.slow
	tst.b	$4003(a6)
	beq.s	.slow
	tst.b	$4005(a6)
	beq.s	.slow
	tst.b	$400B(a6)
	bne.s	.slow
	ifne	SND_HS
	tst.b	$4015(a6)
	bne.s	.slow
	move.b	#3,$4008(a6)
	clr.b	$4010(a6)
	move.b	$402F(a6),d3		; HL = ($402E) | $01C0
	lsl.w	#8,d3
	move.b	$402E(a6),d3
	or.w	#$01C0,d3
	move.b	d3,$402E(a6)
	move.w	d3,d7
	lsr.w	#8,d7
	move.b	d7,$402F(a6)
	move.b	d3,d0			; A = L
	andi.w	#$00FF,d1
	ori.w	#$0100,d1		; C = 1
	move.w	d3,d7
	bsr	snd_vlm_pins
	bsr.s	.rest
	jmp	X0231
.slow:	ifd	SND_TICK_TRANSLATED
	jmp	X024F
	else
	bra	snd_tick
	endc
	else
	tst.b	$400F(a6)
	bne.s	.slow
	move.b	#3,$4008(a6)
	moveq	#0,d0			; A = 0
	andi.w	#$00FF,d1		; C = 0
	bsr.s	.rest
	jmp	X01A1
.slow:	jmp	X01B8
	endc
; The next idle ticks change nothing (the same stores, no command comes within a frame; unless a tune is to start): the
; frame's remaining whole ticks (normal ones: $400B is clear) pass at once, their time counted off the VLM's busy time
; as snd_next would.
.rest:	tst.b	$4009(a6)		; (a tune to start: it comes after this tick)
	bne.s	.r
	move.l	snd_acc,d7
	and.l	#-SND_TICK_FX,d7
	beq.s	.r
	sub.l	d7,snd_acc
	tst.l	snd_busy
	ble.s	.r
	sub.l	d7,snd_busy
	bpl.s	.r
	clr.l	snd_busy
.r:	rts

	ifne	SND_HS
	ifnd	SND_TICK_TRANSLATED
; snd_tick: Hyper Sports' tick ($024F-$02D0, after the `di`) in 68000 code where it only keeps books, the translated
; code where there is work: each channel ($4008 = n; $4001 + 2n - 2 set: $033B with A = $4000 + 2n - 2, which returns
; at once for 0, else on at $033D; clear: $0328), the DAC envelope ($02D3 when $400B, again after the speech queue when
; $4010: its counter $400E counted down here, the rest translated from $02D8), the speech queue ($044C: returns at once
; when $4015 is 0, else on at $0451), the VLM's output pins ($03F4 with A = 0 and C = 0 / 1: the pins' word $402E, its
; store to the pins), then the tune check ($0231).  A part that runs translated code is entered with a return address
; on the Z80 stack that the driver never uses ($FFE0-$FFEA, SND_TK*: sndgen.py points their dispatch entries at the
; continuations here), so its `ret` comes back.  The registers the driver's code would leave: A (d0), B and C (d1:
; C in bits 8-15, B in 0-7), HL (d3); the flags are written before they are read where each part goes on (the
; continuations here, $033D, $0328, $0451 and $02D8 write them first).  -D SND_TICK_TRANSLATED=1: the translated tick
; (to measure).
SND_TK1 = $E0FF				; ($FFE0 .. $FFEA, byte swapped as the Z80 stack holds them)
SND_TK2 = $E2FF
SND_TK3 = $E4FF
SND_TK4 = $E6FF
SND_TK5 = $E8FF
SND_TK6 = $EAFF
SND_CH	macro				; \1 the channel (1-3), \2 the return token
	move.b	#\1,$4008(a6)
	move.b	$4000+2*\1-2(a6),d0	; A
	tst.b	$4001+2*\1-2(a6)
	beq.s	.off\@
	tst.b	d0			; ($033B: or a; ret z)
	beq.s	.n\@
	move.w	#\2,-(a5)
	jmp	X033D
.off\@:	move.w	#\2,-(a5)
	jmp	X0328
.n\@:
	endm

snd_tick:
	SND_CH	1,SND_TK1
snd_tk1:
	SND_CH	2,SND_TK2
snd_tk2:
	move.b	$400B(a6),d0		; ld a,($400B); ld ($4010),a; call nz,$02D3
	move.b	d0,$4010(a6)
	beq.s	snd_tk5
	move.w	#SND_TK5,-(a5)
	bra	snd_dac
snd_tk5:
	SND_CH	3,SND_TK3
snd_tk3:
	move.b	$4015(a6),d0		; $044C: ld a,($4015); or a; ret z
	beq.s	snd_tk4
	move.w	#SND_TK4,-(a5)
	jmp	X0451
snd_tk4:
	tst.b	$4010(a6)		; ld a,($4010); or a; jr z: the DAC envelope again (after `ld a,($400F)`, counted
	beq.s	snd_tk6			; down to 0 by `dec a; jr nz`: A = 0)
	moveq	#0,d0
	move.w	#SND_TK6,-(a5)
	bra	snd_dac
snd_tk6:
	move.b	$4000(a6),d0		; ($4000) | ($4002) | ($4004) | ($4015): 0 -> C = 1, else C = 0 (C's value
	or.b	$4002(a6),d0		; in between is written over)
	or.b	$4004(a6),d0
	or.b	$4015(a6),d0
	move.b	$402F(a6),d3		; HL = ($402E)
	lsl.w	#8,d3
	move.b	$402E(a6),d3
	tst.b	d0
	beq.s	.on
	and.w	#$F03F,d3		; ($03F4, C = 0: H & $F0, L & $3F)
	andi.w	#$00FF,d1		; C = 0
	bra.s	.st
.on:	or.w	#$01C0,d3		; (C = 1: H | 1, L | $C0)
	andi.w	#$00FF,d1
	ori.w	#$0100,d1		; C = 1
.st:	move.b	d3,$402E(a6)		; ld ($402E),hl
	move.w	d3,d7
	lsr.w	#8,d7
	move.b	d7,$402F(a6)
	move.b	d3,d0			; A = L; ld (hl),a: the pins
	move.w	d3,d7
	bsr	snd_vlm_pins
	jmp	X0231

; snd_dac: the DAC envelope ($02D3; a call: its return address on the Z80 stack): ld hl,$400E; dec (hl); ret nz, the
; rest translated
snd_dac:
	move.w	#$400E,d3
	subq.b	#1,$400E(a6)
	beq.s	.go
	moveq	#0,d7			; ret: to the token's continuation
	move.w	(a5)+,d7
	lsl.l	#2,d7
	move.l	0(a4,d7.l),a3
	jmp	(a3)
.go:	jmp	X02D8

	else
snd_tk1 = snd_badpc			; (the translated tick: the tokens' dispatch entries unused)
snd_tk2 = snd_badpc
snd_tk3 = snd_badpc
snd_tk4 = snd_badpc
snd_tk5 = snd_badpc
snd_tk6 = snd_badpc
	endc

; snd_note1-3: the channels' note step handlers $0E76 / $0E7E / $0E86 (`ld ix,$407B / $4086 / $4091; call $0C03;
; ret`, reached through the channel's jump table).  $0C03: ld a,(ix+0); cp a,$FF; ret z; call $0C2E (dec (ix+1); ret
; nz); xor a,a; ret.  Done here while the note's counter (ix+1) has not run out (the flags as the translated code keeps
; them, then the handler's own `ret`); when it runs out, the Z80 stack is made as the two calls make it ($0E7D, $0C0C)
; and the translated code goes on at $0C32.
snd_note1:
	move.w	#$407B,d4
	move.w	#$7D0E,d7		; ($0E7D: the return address of the handler's call, byte swapped)
	bra.s	snd_note
snd_note2:
	move.w	#$4086,d4
	move.w	#$850E,d7
	bra.s	snd_note
snd_note3:
	move.w	#$4091,d4
	move.w	#$8D0E,d7
snd_note:
	move.b	(a6,d4.w),d0		; ld a,(ix+0)
	cmp.b	#$FF,d0			; cp a,$FF; ret z
	move	sr,d6
	beq.s	.ret
	subq.b	#1,1(a6,d4.w)		; dec (ix+1); ret nz
	beq.s	.out
	eor.b	d0,d0			; xor a,a
	move	sr,d6
.ret:	moveq	#0,d7			; (the handler's ret)
	move.w	(a5)+,d7
	lsl.l	#2,d7
	move.l	0(a4,d7.l),a3
	jmp	(a3)
.out:	move.w	d7,-(a5)		; (call $0C03 from the handler)
	move.w	#$0C0C,-(a5)		; (call $0C2E from $0C09)
	jmp	X0C32
	endc

; snd_tune: the native at the tune routine (sound.py TickBoard.tune): the tune $400A's effect, then the loop's head
snd_tune:
	movem.l	d0-d2/a1,-(sp)
	moveq	#0,d7
	move.b	$400A(a6),d7
	cmp.w	#SND_TUNES,d7
	bhs	.bad
	lsl.w	#2,d7
	lea	snd_tune_tab,a1
	move.l	(a1,d7.w),a1
	move.l	(a1)+,d2		; its time
	addq.l	#8,a1			; (the samples' offset and length: the DMA's request below)
	move.w	(a1)+,d1		; the RAM bytes it leaves
	bra.s	.r1
.r0:	move.w	(a1)+,d7
	move.w	(a1)+,d0
	move.b	d0,(a6,d7.w)
.r1:	dbf	d1,.r0
	move.w	(a1)+,d1		; its SN bytes
	bra.s	.s1
.s0:	move.w	(a1)+,d0
	move.b	d0,snd_snl
	bsr	snd_sn_w
.s1:	dbf	d1,.s0
	move.w	(a1)+,d0		; the VLM reset (-1: none)
	bmi.s	.t
	move.b	d0,snd_vlm_data
	tst.l	snd_busy
	beq.s	.t
	clr.l	snd_busy
	move.w	#$0300,d1
	bsr	snd_req
.t:	sub.l	d2,snd_acc
	tst.l	snd_busy
	ble.s	.q
	sub.l	d2,snd_busy
	bpl.s	.q
	clr.l	snd_busy
.q:	moveq	#0,d1
	move.b	$400A(a6),d1
	or.w	#$0200,d1
	bsr	snd_req
	movem.l	(sp)+,d0-d2/a1
	jmp	snd_loop_label
.bad:	move.w	#$400A,d7
	bra	snd_badpc

; snd_dma (the frame's end): the last request of the frame on the DMA sound (sound.py TickBoard.events)
snd_dma:
	clr.b	snd_dma_req
	ifnd SIM
	clr.b	$ffff8901.w		; (stopped; a new start sets the addresses)
	move.w	snd_dma_last,d0
	moveq	#0,d1
	move.b	d0,d1
	lsl.w	#3,d1			; (the phrase's offset and length: 8 bytes)
	lea	snd_phr_tab,a0
	cmp.w	#$0200,d0
	blo.s	.go
	cmp.w	#$0300,d0
	bhs.s	.x
	lsr.w	#1,d1			; a tune: its table entry, the offset and length after the time
	lea	snd_tune_tab,a0
	move.l	(a0,d1.w),a0
	addq.l	#4,a0
	moveq	#0,d1
.go:	move.l	(a0,d1.w),d0		; the offset
	move.l	4(a0,d1.w),d1		; the length (0: none)
	beq.s	.x
	add.l	#snd_pcm,d0
	add.l	d0,d1
	move.l	d0,-(sp)
	move.b	1(sp),$ffff8903.w
	move.b	2(sp),$ffff8905.w
	move.b	3(sp),$ffff8907.w
	move.l	d1,(sp)
	move.b	1(sp),$ffff890f.w
	move.b	2(sp),$ffff8911.w
	move.b	3(sp),$ffff8913.w
	addq.l	#4,sp
	move.b	#$81,$ffff8921.w	; mono, 12517 Hz
	move.b	#1,$ffff8901.w		; play once
.x:
	endc
	rts

; ---- snd_ym: the YM's registers from the SN's (sound.py YM).  A voice's key: (16 - attenuation) * 8 + 7 - voice (0:
; silent); the three best in d2 > d3 > d4.

SND_KEY	macro				; \1 the voice (0-3): its attenuation at snd_sn + 4 * \1 + 2
	moveq	#$0F,d1
	and.w	4*\1+2(a0),d1
	cmp.w	#15,d1
	beq.s	.n\@
	moveq	#16,d0
	sub.w	d1,d0
	lsl.w	#3,d0
	addq.w	#7-\1,d0
	cmp.w	d4,d0
	bls.s	.n\@
	cmp.w	d3,d0
	bhi.s	.g2\@
	move.w	d0,d4
	bra.s	.n\@
.g2\@:	move.w	d3,d4
	cmp.w	d2,d0
	bhi.s	.g1\@
	move.w	d0,d3
	bra.s	.n\@
.g1\@:	move.w	d2,d3
	move.w	d0,d2
.n\@:
	endm

SND_PICK macro				; \1 a key register -> d0.b its voice (-1: none)
	moveq	#-1,d0
	tst.w	\1
	beq.s	.p\@
	moveq	#7,d1
	and.w	\1,d1
	moveq	#7,d0
	sub.w	d1,d0
.p\@:
	endm

SND_YMW	macro				; \1 a YM register: written if it changed
	move.b	\1(a2),d1
	cmp.b	\1(a1),d1
	beq.s	.s\@
	move.b	d1,\1(a1)
	ifnd SIM
	move.b	#\1,$ffff8800.w
	move.b	d1,$ffff8802.w
	endc
	addq.w	#1,snd_ym_writes
.s\@:
	endm

snd_ym:
	clr.b	snd_dirty
	lea	snd_sn,a0
	moveq	#0,d2
	moveq	#0,d3
	moveq	#0,d4
	SND_KEY	0
	SND_KEY	1
	SND_KEY	2
	SND_KEY	3
	lea	snd_pick,a2
	SND_PICK d2
	move.b	d0,(a2)
	SND_PICK d3
	move.b	d0,1(a2)
	SND_PICK d4
	move.b	d0,2(a2)
	; the YM channels: one that holds a chosen voice keeps it; the others take the remaining ones in order
	lea	snd_ymch,a3
	lea	snd_newch,a4
	move.b	#-1,(a4)
	move.b	#-1,1(a4)
	move.b	#-1,2(a4)
	moveq	#2,d6
.keep:	move.b	(a2,d6.w),d0
	bmi.s	.kn
	moveq	#2,d5
.kc:	cmp.b	(a3,d5.w),d0
	beq.s	.kp
	dbf	d5,.kc
	bra.s	.kn
.kp:	move.b	d0,(a4,d5.w)		; (kept on YM channel d5)
	st	(a2,d6.w)		; (placed)
.kn:	dbf	d6,.keep
	moveq	#0,d6			; the rest, in order of loudness, into the free YM channels from 0
.fill:	move.b	(a2,d6.w),d0
	bmi.s	.fn
	moveq	#0,d5
.ff:	tst.b	(a4,d5.w)
	bpl.s	.fx
	move.b	d0,(a4,d5.w)
	bra.s	.fn
.fx:	addq.w	#1,d5
	bra.s	.ff
.fn:	addq.w	#1,d6
	cmp.w	#3,d6
	blo.s	.fill
	move.b	(a4),(a3)
	move.b	1(a4),1(a3)
	move.b	2(a4),2(a3)
	; the YM's registers into snd_ym_new
	lea	snd_ym_new,a2
	clr.l	(a2)
	clr.l	4(a2)
	clr.l	8(a2)
	clr.l	12(a2)
	lea	snd_ptab,a4
	lea	snd_vtab,a5
	moveq	#$3F,d7			; the mixer: all off
	moveq	#0,d6			; the YM channel
.ych:	moveq	#0,d0
	move.b	(a3,d6.w),d0
	bmi.s	.yn
	lsl.w	#2,d0
	lea	(a0,d0.w),a1		; the voice's period (word 2k), its attenuation 2 further
	cmp.w	#12,d0
	beq.s	.noise
	move.w	(a1),d2			; the period (10 bits), scaled
	add.w	d2,d2
	move.w	(a4,d2.w),d2
	move.w	d6,d1
	add.w	d1,d1
	move.b	d2,(a2,d1.w)
	lsr.w	#8,d2
	move.b	d2,1(a2,d1.w)
	bclr	d6,d7			; tone on
	bra.s	.vol
.noise:	addq.w	#3,d6			; noise on (the tone stays off)
	bclr	d6,d7
	subq.w	#3,d6
	moveq	#31,d2			; the noise period: 31 but for mode 3 with tone 2's period below 16
	moveq	#3,d1
	and.w	12(a0),d1
	cmp.w	#3,d1
	bne.s	.np
	move.w	8(a0),d1
	cmp.w	#16,d1
	bhs.s	.np
	lea	snd_ntab,a1
	move.b	(a1,d1.w),d2
	lea	12(a0),a1
.np:	move.b	d2,6(a2)
.vol:	moveq	#$0F,d1			; the level
	and.w	2(a1),d1
	move.b	(a5,d1.w),8(a2,d6.w)
.yn:	addq.w	#1,d6
	cmp.w	#3,d6
	blo.s	.ych
	or.b	#$C0,d7			; (bits 6 / 7: the STE's ports A and B stay outputs)
	move.b	d7,7(a2)
	lea	snd_ym_cache,a1
	SND_YMW	0
	SND_YMW	1
	SND_YMW	2
	SND_YMW	3
	SND_YMW	4
	SND_YMW	5
	SND_YMW	6
	SND_YMW	7
	SND_YMW	8
	SND_YMW	9
	SND_YMW	10
	rts

	include	"snd_code.s"

	section data,data
; The sound Z80's 64 KB (a6 = its address 0, signed offsets): $8000-$FFFF first, then the ROM at $0000-$3FFF, the RAM
; and the rest zero.
	cnop	0,4
snd_g:		dcb.b	$8000,0
	incbin	"snd.rom"
	dcb.b	$4000,0

	section bss,bss
	even
snd_regs:	ds.l	8		; d0-d4, d6, a2, a5 between runs
snd_entry:	ds.l	1
snd_sp0:	ds.l	1
snd_acc:	ds.l	1		; the schedule's time (half Z80 cycles; below 0 while a tune plays)
snd_busy:	ds.l	1		; the VLM's BSY time left (half cycles; -1: ST high, not started)
snd_sn:		ds.w	8		; the SN76489A's registers 0-7
snd_pending:	ds.w	1		; the command held while a tune plays (-1: none)
snd_dma_last:	ds.w	1		; the DMA's last request (kind << 8 | n)
snd_ym_writes:	ds.w	1
snd_pin_addr:	ds.w	1		; the address of the last store to the VLM's pins
snd_pins:
snd_st:		ds.b	1
snd_rst:	ds.b	1
snd_vlm_data:	ds.b	1
snd_snl:	ds.b	1		; the SN's latched byte
snd_sn_latch:	ds.b	1		; the SN's latched register
snd_cmd:	ds.b	1		; the command latch as the driver reads it
snd_tail:	ds.b	1
snd_dirty:	ds.b	1
snd_dma_req:	ds.b	1
	even
snd_ymch:	ds.b	4		; per YM channel its voice (-1: none; a long: even)
snd_pick:	ds.b	4
snd_newch:	ds.b	4
snd_ym_new:	ds.b	16
snd_ym_cache:	ds.b	16		; the YM's registers as last written ($FF: not yet)
	even
	section text,code
