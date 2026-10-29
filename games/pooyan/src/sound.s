; Pooyan's sound on the STE (included by pooyan.s): the sound board's Z80 driver (Time Pilot's board: a Z80 and two
; AY-3-8910 at 1.789772 MHz), translated (tools/sndgen.py -> build/pooyan/snd_code.s), drives two emulated AY register
; files; their six channels go to the YM2149's three each arcade frame (snd_ym: the loudest audible ones, kept on their
; YM channel while they last; Gyruss's and Kung-Fu Master's method), the periods scaled from the AYs' 1.789772 MHz to
; the YM's 2 MHz.  The RC filters the driver sets (stores to $8000-$FFFF) are left out: plain stores into the block.
;
; snd_frame (once an arcade frame, before its NMI): the commands the game wrote since the last call (py_sound's ring)
; each run the driver's IRQ handler ($0038, TOKEN as the return address), then the frame's ticks run its main loop once
; each (from $00DA, after the timer waits, to the loop's head $00CB, the hook snd_hook, which goes on with the next
; tick: one run for the frame's ticks): SND_TICKS_FX (16.16) a frame.  tools/sound.py STEBoard is the same in Python (tools/sound_test.py compares).
;
; The driver's registers between runs: snd_regs (d0-d4, d6, a2, a5: z80x.FAST's map); a6 = snd_g + $8000 (its 64 KB,
; signed offsets: $8000-$FFFF below), a4 = snd_dispatch_sw.  The main program's registers are saved around a run.

SND_TICKS_FX = 378000			; (tools/sound.py TICKS_FX: 5.768 ticks an arcade frame)
SND_TOKEN = $FEFF			; $FFFE on the Z80 stack, byte swapped (sound.py TOKEN)
SND_LOOP_SW = $CB00			; $00CB (sound.py LOOP), byte swapped
G_SND = snd_g+$8000

	section text,code

snd_init:
	movem.l	d0-d7/a0-a6,-(sp)
	clr.b	snd_tail
	clr.l	snd_acc
	st	snd_dirty
	lea	snd_ym_cache,a0
	moveq	#16-1,d0
.y:	move.b	#$FF,(a0)+
	dbf	d0,.y
	move.l	#-1,snd_ymch		; (no AY channel on the YM's three: -1 bytes)
	lea	snd_regs,a0
	moveq	#8-1,d0
.r:	clr.l	(a0)+
	dbf	d0,.r
	move.l	#G_SND-1,snd_regs+28	; (a5: SP = $FFFF; the driver sets it)
	bsr	snd_ptab_init
	move.l	#X0000,snd_entry
	bsr	snd_run			; the boot: to the loop's head
	movem.l	(sp)+,d0-d7/a0-a6
	rts

; snd_run: the driver from snd_entry until it comes back (snd_hook at the loop's head, or snd_token_ret)
snd_run:
	move.l	sp,snd_sp0
	movem.l	snd_regs,d0-d4/d6/a2/a5
	lea	G_SND,a6
	lea	snd_dispatch_sw,a4
	move.l	snd_entry,a0
	jmp	(a0)
snd_hook:				; (d7 = the pc: only the loop's head is a hook)
	subq.w	#1,snd_n		; (the frame's next tick: the loop's code after the waits, as TickBoard.run_frame)
	bpl	X00DA
	clr.w	snd_n
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
.cmd:	move.b	snd_tail,d0
	cmp.b	snd_head,d0
	beq.s	.ticks
	addq.b	#1,snd_tail
	and.w	#$FF,d0
	lea	snd_ring,a0
	move.b	(a0,d0.w),snd_latch
	move.l	snd_regs+28,a5		; the IRQ: the loop's head and TOKEN pushed
	move.w	#SND_LOOP_SW,-(a5)
	move.w	#SND_TOKEN,-(a5)
	move.l	a5,snd_regs+28
	move.l	#X0038,snd_entry
	bsr	snd_run
	bra.s	.cmd
.ticks:	move.l	snd_acc,d0
	add.l	#SND_TICKS_FX,d0
	move.l	d0,d1
	and.l	#$FFFF,d0
	move.l	d0,snd_acc
	swap	d1
	subq.w	#1,d1			; the frame's ticks in one run: snd_hook starts the next ones
	bmi.s	.none
	move.w	d1,snd_n
	move.l	#X00DA,snd_entry	; (sound.py TICK)
	bsr	snd_run
.none:	bsr	snd_ym
	movem.l	(sp)+,d0-d7/a0-a6
	rts

; snd_in (`ld a,($4000)` / `ld a,($6000)`): d7 = the chip -> d7.l the byte of its selected register (AY #1's port A:
; the command latch; its port B: the timer, 0 here: the schedule leaves out the waits; AY #2's ports: the register),
; masked as the AY-3-8910 reads (MAME ay8910_read_ym).  Keeps every register but d7 / a0 (the translation's scratch;
; the flags: the Z80's are in d6).
snd_in:
	move.w	d6,-(sp)
	lea	snd_addr,a0
	moveq	#0,d6
	move.b	(a0,d7.w),d6		; the register
	tst.w	d7
	bne.s	.reg
	cmp.w	#14,d6
	bne.s	.n14
	move.b	snd_latch,snd_ay+14	; (port A: the latch, into the register as MAME does)
	bra.s	.reg
.n14:	cmp.w	#15,d6
	bne.s	.reg
	clr.b	snd_ay+15		; (port B: the timer)
.reg:	lsl.w	#4,d7
	add.w	d6,d7
	lea	snd_ay,a0
	move.b	(a0,d7.w),d7
	lea	snd_mask,a0
	and.b	(a0,d6.w),d7
	and.l	#$FF,d7
	move.w	(sp)+,d6
	rts

; snd_ym: the YM's registers from the two AYs (tools/sound.py YM): each channel's score (its volume, 15 for the
; envelope; silent: volume 0 or neither tone nor noise on), the three best (ties: the lower number), a YM channel
; holding a chosen one keeps it, the others take the rest in order; periods x 2000000 / 1789772 (snd_ptab); the noise
; and envelope of the first chosen channel's chip that uses them; only the changed registers written (the shape when
; its chip wrote it this frame).  The three best in one pass: a channel's key (score + 1) * 8 + 7 - channel (0:
; silent) goes into d2 > d3 > d4.

SND_KEY	macro				; \1 the channel, \2 its chip's offset, \3 its voice
	moveq	#0,d0
	move.b	8+\2+\3(a0),d1
	and.b	#$1F,d1
	beq.s	.n\@
	btst	#\3,7+\2(a0)
	beq.s	.on\@
	btst	#\3+3,7+\2(a0)
	bne.s	.n\@
.on\@:	moveq	#16,d0
	btst	#4,d1
	bne.s	.k\@
	move.b	d1,d0
	addq.w	#1,d0
.k\@:	lsl.w	#3,d0
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

SND_PICK macro				; \1 a key register -> d0.b its channel (-1: none)
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
	tst.b	snd_dirty		; (no AY register written: the YM's stay)
	beq	.yout
	clr.b	snd_dirty
	lea	snd_ay,a0
	moveq	#0,d2
	moveq	#0,d3
	moveq	#0,d4
	SND_KEY	0,0,0
	SND_KEY	1,0,1
	SND_KEY	2,0,2
	SND_KEY	3,16,0
	SND_KEY	4,16,1
	SND_KEY	5,16,2
	; the YM channels: one that holds a chosen channel keeps it; the others take the remaining ones in order
	lea	snd_pick,a2
	SND_PICK d2
	move.b	d0,(a2)
	SND_PICK d3
	move.b	d0,1(a2)
	SND_PICK d4
	move.b	d0,2(a2)
	lea	snd_ymch,a3
	moveq	#-1,d5			; the new choice: bytes 0-2 (-1 none)
	moveq	#2,d6
.keep:	move.b	(a2,d6.w),d0
	bmi.s	.kn
	cmp.b	(a3),d0
	bne.s	.k1
	move.b	d0,d5			; (byte 3 of d5: YM channel 0)
	bra.s	.kp
.k1:	cmp.b	1(a3),d0
	bne.s	.k2
	ror.l	#8,d5
	move.b	d0,d5
	rol.l	#8,d5
	bra.s	.kp
.k2:	cmp.b	2(a3),d0
	bne.s	.kn
	swap	d5
	move.b	d0,d5
	swap	d5
.kp:	st	(a2,d6.w)		; (placed)
.kn:	dbf	d6,.keep
	move.l	d5,snd_newch		; (bytes: YM channel 2, 1, 0, - from the top: stored reversed below)
	lea	snd_newch+4,a4		; (YM channel k at -1-k(a4))
	moveq	#0,d6
.fill:	move.b	(a2,d6.w),d0
	bmi.s	.fn
	lea	snd_newch+4,a4
.ff:	tst.b	-(a4)
	bpl.s	.ff
	move.b	d0,(a4)
.fn:	addq.w	#1,d6
	cmp.w	#3,d6
	blo.s	.fill
	lea	snd_newch,a4		; snd_ymch: channel k = newch byte 3-k
	move.b	3(a4),(a3)
	move.b	2(a4),1(a3)
	move.b	1(a4),2(a3)
	; the YM's registers into snd_ym_new
	lea	snd_ym_new,a2
	clr.l	(a2)
	clr.l	4(a2)
	clr.l	8(a2)
	clr.l	12(a2)
	lea	snd_ptab,a4
	moveq	#$3F,d7			; the mixer: all off
	moveq	#-1,d4			; the chip whose noise is used (-1 none: its offset)
	moveq	#-1,d5			; the chip whose envelope
	moveq	#0,d6			; the YM channel
.ych:	move.b	(a3,d6.w),d0
	bmi.s	.yn
	ext.w	d0
	add.w	d0,d0
	lea	snd_cv,a1
	move.b	(a1,d0.w),d3		; the chip's offset
	ext.w	d3
	move.b	1(a1,d0.w),d0		; the voice
	ext.w	d0
	lea	(a0,d3.w),a1		; the chip's registers
	move.w	d0,d1
	add.w	d1,d1
	move.b	1(a1,d1.w),d2		; the period (12 bits), scaled through snd_ptab
	lsl.w	#8,d2
	move.b	(a1,d1.w),d2
	and.w	#$0FFF,d2
	add.w	d2,d2
	move.w	(a4,d2.w),d2
	move.w	d6,d1
	add.w	d1,d1
	move.b	d2,(a2,d1.w)
	lsr.w	#8,d2
	move.b	d2,1(a2,d1.w)
	move.b	8(a1,d0.w),d1		; volume
	and.b	#$1F,d1
	move.b	d1,8(a2,d6.w)
	btst	#4,d1
	beq.s	.ne
	tst.w	d5
	bpl.s	.ne
	move.w	d3,d5
.ne:	move.b	7(a1),d1		; tone / noise enables (0 = on)
	btst	d0,d1
	bne.s	.nt
	bclr	d6,d7
.nt:	addq.w	#3,d0
	btst	d0,d1
	bne.s	.yn
	addq.w	#3,d6
	bclr	d6,d7
	subq.w	#3,d6
	tst.w	d4
	bpl.s	.yn
	move.w	d3,d4
.yn:	addq.w	#1,d6
	cmp.w	#3,d6
	blo	.ych
	or.b	#$C0,d7			; (bits 6 / 7: the STE's ports A and B stay outputs)
	move.b	d7,7(a2)
	tst.w	d4			; noise period
	bmi.s	.nn
	moveq	#0,d2
	move.b	6(a0,d4.w),d2
	and.w	#$1F,d2
	add.w	d2,d2
	move.w	(a4,d2.w),d2
	cmp.w	#31,d2
	bls.s	.n1
	moveq	#31,d2
.n1:	move.b	d2,6(a2)
.nn:	tst.w	d5			; envelope period and shape
	bmi.s	.ne2
	moveq	#0,d2
	move.b	12(a0,d5.w),d2
	lsl.w	#8,d2
	move.b	11(a0,d5.w),d2
	bsr	snd_scale
	cmp.l	#$FFFF,d2
	bls.s	.e1
	move.w	#$FFFF,d2
.e1:	move.b	d2,11(a2)
	lsr.w	#8,d2
	move.b	d2,12(a2)
	move.b	13(a0,d5.w),13(a2)
.ne2:	; write the registers that changed; the shape when the chosen chip's was written
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
	SND_YMW	11
	SND_YMW	12
	tst.w	d5
	bmi.s	.yout
	move.w	d5,d1
	lsr.w	#4,d1			; (the chip)
	lea	snd_env,a3
	tst.b	(a3,d1.w)
	beq.s	.yout
	move.b	13(a2),d1
	move.b	d1,13(a1)
	ifnd SIM
	move.b	#13,$ffff8800.w
	move.b	d1,$ffff8802.w
	endc
	addq.w	#1,snd_ym_writes
.yout:
	clr.w	snd_env
	rts

; snd_ptab_init: snd_ptab[p] = min(snd_scale(p), $0FFF) for the 4096 tone periods
snd_ptab_init:
	lea	snd_ptab,a0
	moveq	#0,d0
.l:	move.w	d0,d2
	bsr	snd_scale
	cmp.l	#$0FFF,d2
	bls.s	.s
	move.w	#$0FFF,d2
.s:	move.w	d2,(a0)+
	addq.w	#1,d0
	cmp.w	#$1000,d0
	blo.s	.l
	rts

snd_scale:				; d2.w = an AY period -> d2.l the YM's (x 2000000 / 1789772: p + p * 7698 / 65536)
	move.l	d3,-(sp)
	and.l	#$FFFF,d2
	move.l	d2,d3
	mulu	#7698,d3
	swap	d3
	and.l	#$FFFF,d3
	add.l	d3,d2
	move.l	(sp)+,d3
	rts

	include	"snd_code.s"

	section data,data
snd_cv:		dc.b	0,0,0,1,0,2,16,0,16,1,16,2	; channel 0-5 -> its chip's offset in snd_ay, its voice
snd_mask:	dc.b	$FF,$0F,$FF,$0F,$FF,$0F,$1F,$FF,$1F,$1F,$1F,$FF,$FF,$0F,$FF,$FF	; (the AY-3-8910's reads)
; The sound Z80's 64 KB (a6 = its address 0, signed offsets): $8000-$FFFF first (the filter stores land there), then
; the ROM at $0000-$1FFF, the rest ($2000-$7FFF: the RAM at $3000-$33FF) zero.
	cnop	0,4
snd_g:		dcb.b	$8000,0
	incbin	"snd.rom"
	dcb.b	$6000,0

	section bss,bss
	even
snd_regs:	ds.l	8		; d0-d4, d6, a2, a5 between runs
snd_ptab:	ds.w	4096		; an AY tone period -> the YM's (snd_ptab_init)
snd_entry:	ds.l	1
snd_sp0:	ds.l	1
snd_acc:	ds.l	1
snd_ymch:	ds.l	1		; the AY channel on each YM channel (-1 none), 4th byte unused
snd_newch:	ds.l	1		; (snd_ym: the new choice, YM channel k in byte 3-k)
snd_n:		ds.w	1
snd_ym_writes:	ds.w	1
snd_ay:		ds.b	2*16
snd_env:	ds.b	2		; the envelope shape written this frame, by chip
snd_addr:	ds.b	2		; the selected register, by chip
snd_pick:	ds.b	4
snd_ym_new:	ds.b	16
snd_ym_cache:	ds.b	16
snd_tail:	ds.b	1
snd_latch:	ds.b	1
snd_dirty:	ds.b	1
	even
