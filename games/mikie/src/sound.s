; Mikie's sound on the STE (included by mikie.s; tools/sound.py is the same in Python, tools/sound_test.py compares): the
; sound board's Z80 driver, translated (tools/sndgen.py -> build/mikie/snd_code.s, snd_data.s), drives two emulated
; SN76489A register files; their eight voices (two chips' three tones and the noise) go to the YM2149's three channels each
; arcade frame (snd_ym: the three loudest, a voice keeping its YM channel while it lasts, Mr. Do!'s method).  After
; games/trackfld/src/sound.s: the same schedule without speech, DAC and tunes.
;
; snd_frame (once an arcade frame, before its IRQ): the commands the game wrote since the last call (snd_ring) each run
; the driver's IRQ handler ($0038, TOKEN as the return address).  Then the frame's time (SND_FRAME_FX half Z80 cycles)
; runs ticks: each from the loop's code after the timer's wait (snd_tick_label) to the loop's head (snd_loop_label, the
; hook snd_hook, which goes on with the next tick while the time allows: 4096 cycles a tick).
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
	lea	snd_sn,a0		; (two chips: 8 registers and the latched register: MAME's reset, 0)
	moveq	#18-1,d0
.s:	clr.w	(a0)+
	dbf	d0,.s
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
	move.l	#$4400,snd_regs+12	; (HL = $4400 at the boot's `ld sp,hl`: the RAM test's result)
	move.l	#snd_boot_label,snd_entry
	bsr	snd_run			; the boot: to the loop's head (no time: no tick)
	bsr	snd_ym
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
snd_next:				; the next tick if the frame's time allows it (sound.py TickBoard.run_frame)
	move.l	#SND_TICK_FX,d7
	cmp.l	snd_acc,d7
	bgt.s	snd_back
	sub.l	d7,snd_acc
	jmp	snd_tick_label
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
	beq.s	.out
	bsr	snd_ym
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

; The tick's shortcuts (natives at the tick's start and at each channel's turn: sndgen.py NATIVES).  A channel's turn
; ($0188 ld a,n; ld ($400C),a; ld a,(started); or a,a; ld a,(effect); ..: effect = $4000 + 2 (n - 1), started the next byte)
; does nothing when the effect is 0 and it has started ($0252: `or a,a; ret z`), and for an effect whose handler is `ld
; ix,block; call $0357; ret` (snd_stub: eight voice blocks) only counts the block's (ix+1) down, as long as (ix+0) is not
; $FF and the counter does not reach 0 ($0395: `dec (ix+1); ret nz`; the end of the effect or the next note is translated
; code).  The registers it leaves are dead (the next turn loads A and the flags; $400C is set).
SND_CH	macro				; \1 the channel (1-6), \2 its translated code after `ld ($400C),a`, \3 where its turn ends
snd_ch\1:
	move.b	#\1,$400C(a6)
	move.b	$4001+2*\1-2(a6),d0	; started?
	beq.s	.slow
	move.b	$4000+2*\1-2(a6),d0	; the effect
	beq	\3
	bmi.s	.slow
	moveq	#0,d7
	move.b	d0,d7
	add.w	d7,d7
	lea	snd_stub,a0
	move.w	(a0,d7.w),d7		; its voice block
	beq.s	.slow
	cmp.b	#$FF,0(a6,d7.w)
	beq.s	.slow
	cmp.b	#1,1(a6,d7.w)
	beq.s	.slow
	subq.b	#1,1(a6,d7.w)
	bra	\3
.slow:	moveq	#\1,d0
	jmp	\2
	endm
	SND_CH	1,X018D,snd_ch2
	SND_CH	2,X01A8,snd_ch3
	SND_CH	3,X01C3,snd_ch4
	SND_CH	4,X01DE,snd_ch5
	SND_CH	5,X01F9,snd_ch6
	SND_CH	6,X0214,X0226

; snd_tick (the native at TICK, `di`): the whole tick at once when every channel only counts (above) or is idle, and for
; the frame's remaining ticks too while no counter gets to 1: m ticks (m = the least of the counters - 1, the ticks
; the frame's time still allows, 255 when no channel counts), each taking 1 off the counters; two channels on one voice block
; take 2 a tick: not this way.  Else the tick runs channel by channel (snd_ch1).
SND_SCAN macro				; \1 the channel (1-6): d5 the least safe tick count, a1 the voice blocks seen
	move.b	$4001+2*\1-2(a6),d0
	beq	.no
	move.b	$4000+2*\1-2(a6),d0
	beq.s	.n\@
	bmi	.no
	moveq	#0,d7
	move.b	d0,d7
	lea	snd_stubg,a0
	move.b	(a0,d7.w),d3		; the block's number
	add.w	d7,d7
	lea	snd_stub,a0
	move.w	(a0,d7.w),d7
	beq	.no
	cmp.b	#$FF,0(a6,d7.w)
	beq	.no
	moveq	#0,d0
	move.b	1(a6,d7.w),d0		; the counter: safe ticks = counter - 1 (counters 0 and 1 end the turn's count)
	subq.b	#1,d0
	bls	.no
	cmp.b	d5,d0
	bhs.s	.k\@
	move.b	d0,d5
.k\@:	bset	d3,d4			; a second channel on the block: not this way
	bne	.no
.n\@:
	endm
snd_tick:
	moveq	#-1,d5			; (the least safe count: 255 = none counting)
	and.w	#$FF,d5
	move.l	d4,-(sp)		; (IX: d4 is the voice-block bit set meanwhile)
	moveq	#0,d4
	SND_SCAN 1
	SND_SCAN 2
	SND_SCAN 3
	SND_SCAN 4
	SND_SCAN 5
	SND_SCAN 6
	move.l	(sp)+,d4
	move.l	snd_acc,d7		; the ticks the frame's time still allows besides this one
	moveq	#13,d0
	lsr.l	d0,d7
	addq.w	#1,d7
	cmp.w	d5,d7
	bls.s	.m
	move.w	d5,d7			; m ticks
.m:	move.w	d7,d5
	subq.w	#1,d5
	beq.s	.one
	swap	d5			; the other ticks' time
	clr.w	d5
	lsr.l	#3,d5			; (m - 1) << 13
	sub.l	d5,snd_acc
.one:	move.b	#6,$400C(a6)
	; every counting channel: m off its counter
	moveq	#5,d5
.c:	move.w	d5,d0
	add.w	d0,d0
	lea	$4000(a6),a0
	move.b	(a0,d0.w),d1
	beq.s	.nx
	andi.w	#$00FF,d1
	add.w	d1,d1
	lea	snd_stub,a0
	move.w	(a0,d1.w),d1
	beq.s	.nx
	sub.b	d7,1(a6,d1.w)
.nx:	dbf	d5,.c
	jmp	X0226
.no:	move.l	(sp)+,d4
	jmp	snd_ch1

; snd_sn1_w / snd_sn2_w (`ld ($8002),a` / `ld ($8004),a`): d0 = the byte into the chip's registers (MAME
; sn76496_base_device::write).  A chip: 8 words (0, 2, 4 the periods, 6 the noise control, 1, 3, 5, 7 the volumes) and the
; latched register.
snd_sn1_w:
	lea	snd_sn,a0
	bra.s	snd_sn_w
snd_sn2_w:
	lea	snd_sn+18,a0
snd_sn_w:
	movem.l	d1-d2,-(sp)
	st	snd_dirty
	move.b	d0,d1
	bpl.s	.data
	moveq	#$70,d7			; a latch byte: the register, its low 4 bits
	and.b	d1,d7
	lsr.b	#4,d7
	move.w	d7,16(a0)
.low:	ext.w	d7
	add.w	d7,d7
	moveq	#$0F,d2
	and.b	d1,d2
	and.w	#$3F0,(a0,d7.w)
	or.w	d2,(a0,d7.w)
	movem.l	(sp)+,d1-d2
	rts
.data:	move.w	16(a0),d7		; a data byte: the latched register
	btst	#0,d7
	bne.s	.low			; (a volume: its low 4 bits)
	cmp.b	#6,d7
	beq.s	.low			; (the noise control: the same)
	add.w	d7,d7			; a period: bits 4-9
	moveq	#$3F,d2
	and.b	d1,d2
	lsl.w	#4,d2
	and.w	#$0F,(a0,d7.w)
	or.w	d2,(a0,d7.w)
	movem.l	(sp)+,d1-d2
	rts

; ---- snd_ym: the YM's registers from the SNs' (sound.py YM).  A voice's key: (16 - attenuation) * 8 + 7 - voice (0:
; silent); the three best in d2 > d3 > d4.

SND_KEY	macro				; \1 the voice (0-7), \2 its attenuation's offset in snd_sn
	moveq	#$0F,d1
	and.w	\2(a0),d1
	cmp.w	#15,d1
	beq.s	.n\@
	moveq	#16,d0
	sub.w	d1,d0
	lsl.w	#3,d0
	add.w	#7-\1,d0
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
	SND_KEY	0,2
	SND_KEY	1,6
	SND_KEY	2,10
	SND_KEY	3,14
	SND_KEY	4,20
	SND_KEY	5,24
	SND_KEY	6,28
	SND_KEY	7,32
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
	lea	snd_vtab,a5
	moveq	#$3F,d7			; the mixer: all off
	moveq	#0,d6			; the YM channel
	moveq	#0,d5			; (the noise period not yet set)
.ych:	moveq	#0,d0
	move.b	(a3,d6.w),d0
	bmi	.yn
	move.l	a0,a1			; the voice's chip: snd_ptab1 / snd_ptab2, the registers at snd_sn / snd_sn + 18
	lea	snd_ptab1,a4
	btst	#2,d0
	beq.s	.c0
	lea	18(a0),a1
	lea	snd_ptab2,a4
.c0:	and.w	#3,d0
	lsl.w	#2,d0
	lea	(a1,d0.w),a1		; the voice's period (word 2k), its attenuation 2 further
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
	tst.b	d5			; the first noise voice sets the period
	bne.s	.vol
	st	d5
	lea	2048(a4),a4		; the chip's noise table
	moveq	#3,d1
	and.w	(a1),d1			; the noise control's mode
	cmp.w	#3,d1
	bne.s	.nm
	moveq	#31,d2			; mode 3: tone 2's period (31 from 32 up)
	move.w	-4(a1),d1
	cmp.w	#32,d1
	bhs.s	.np
	move.b	(a4,d1.w),d2
	bra.s	.np
.nm:	move.b	32(a4,d1.w),d2
.np:	move.b	d2,6(a2)
.vol:	moveq	#$0F,d1			; the level
	and.w	2(a1),d1
	move.b	(a5,d1.w),8(a2,d6.w)
.yn:	addq.w	#1,d6
	cmp.w	#3,d6
	blo	.ych
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
snd_acc:	ds.l	1		; the schedule's time (half Z80 cycles)
snd_sn:		ds.w	18		; the SN76489As' registers 0-7 and the latched register: sn1, sn2
snd_ym_writes:	ds.w	1
snd_cmd:	ds.b	1		; the command latch as the driver reads it
snd_tail:	ds.b	1
snd_dirty:	ds.b	1
	even
snd_ymch:	ds.b	4		; per YM channel its voice (-1: none; a long: even)
snd_pick:	ds.b	4
snd_newch:	ds.b	4
snd_ym_new:	ds.b	16
snd_ym_cache:	ds.b	16		; the YM's registers as last written ($FF: not yet)
	even
	section text,code
