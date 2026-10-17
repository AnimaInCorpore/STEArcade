; The sound board as the game sees it (tools/stemodel.py SoundModel; the protocol: tools/sound_hle.py): a command is
; taken when the program writes it (the status never shows one pending); $03 (the coins) replies the coin byte, $06
; $E2, $07 (the sound watchdog's ping) 0; the sound CPU's start (the reset bit rising) replies $FF.  A reply raises
; the game's IRQ 6 (its handler at $36C reads the latch at $80300F) through Timer D, ~100 us after the command (the
; BIOS sets its block pointer after the write, with IRQ 6 open), one after another; one waiting while the picture's
; thread runs is delivered by the next VBL before the IRQ 4.  The coins: 2-bit counters in the coin byte (coin 1
; bits 7-6 ... coin 4 bits 1-0), one count a key press.  No sound output yet: the commands go into snd_queue.

SND_RING = 16				; replies waiting (a power of 2)

snd_init:
	move.b	#1,snd_reset_bit
	rts

; the patched program's calls: the command in d0 / at ($a,a7) of the caller (past the return address: $e(sp))
snd_cmd_d0:
	move.l	d0,-(sp)
	bsr.s	snd_command
	move.l	(sp)+,d0
	rts
snd_cmd_sp10:
	move.l	d0,-(sp)
	move.w	4+$e(sp),d0
	bsr.s	snd_command
	move.l	(sp)+,d0
	rts

; d0.b = the command
snd_command:
	move	sr,-(sp)
	or	#$0700,sr
	movem.l	d1/a0,-(sp)
	moveq	#0,d1
	move.b	snd_qhead,d1		; the commands for the sound output (later)
	lea	snd_queue,a0
	move.b	d0,(a0,d1.w)
	addq.b	#1,d1
	and.b	#63,d1
	move.b	d1,snd_qhead
	cmp.b	#$03,d0
	bne.s	.n6
	move.b	coin_byte,d0
	bra.s	.reply
.n6:	cmp.b	#$06,d0
	bne.s	.n7
	move.b	#$e2,d0
	bra.s	.reply
.n7:	cmp.b	#$07,d0
	bne.s	.out
	moveq	#0,d0
.reply:	bsr.s	snd_push
.out:	movem.l	(sp)+,d1/a0
	move	(sp)+,sr
	rts

; the reset bit (Q7 of the latch at $803120-$80312F): d0 bit 0
snd_reset_d0:
	move	sr,-(sp)
	or	#$0700,sr
	move.l	d0,-(sp)
	and.b	#1,d0
	beq.s	.low
	tst.b	snd_reset_bit
	bne.s	.same
	move.b	#$ff,d0
	bsr.s	snd_push
	moveq	#1,d0
.low:	move.b	d0,snd_reset_bit
.same:	move.l	(sp)+,d0
	move	(sp)+,sr
	rts

; d0.b = a reply into the ring (interrupts off)
snd_push:
	movem.l	d1/a0,-(sp)
	moveq	#0,d1
	move.b	snd_rhead,d1
	lea	snd_ring,a0
	move.b	d0,(a0,d1.w)
	addq.b	#1,d1
	and.b	#SND_RING-1,d1
	move.b	d1,snd_rhead
	movem.l	(sp)+,d1/a0
	rts

; the next reply into the latch: d0 = 0 none, else 1 (interrupts off)
snd_pop:
	moveq	#0,d0
	move.b	snd_rtail,d0
	cmp.b	snd_rhead,d0
	beq.s	.none
	lea	snd_ring,a0
	move.b	(a0,d0.w),ARC_IO+$f
	addq.b	#1,d0
	and.b	#SND_RING-1,d0
	move.b	d0,snd_rtail
	moveq	#1,d0
	rts
.none:	moveq	#0,d0
	rts

; a coin key: d0 = the slot (0-3)
coin:
	movem.l	d0-d2,-(sp)
	move.w	d0,d2
	add.w	d2,d2
	moveq	#6,d1
	sub.w	d2,d1			; its counter's shift
	move.b	coin_byte,d0
	moveq	#0,d2
	move.b	d0,d2
	lsr.b	d1,d2
	addq.b	#1,d2
	and.b	#3,d2
	lsl.b	d1,d2
	moveq	#3,d0
	lsl.b	d1,d0
	not.b	d0
	and.b	coin_byte,d0
	or.b	d2,d0
	move.b	d0,coin_byte
	movem.l	(sp)+,d0-d2
	rts

sound_vars macro
snd_queue:	ds.b	64
snd_ring:	ds.b	SND_RING
snd_qhead:	ds.b	1
snd_rhead:	ds.b	1
snd_rtail:	ds.b	1
snd_reset_bit:	ds.b	1
coin_byte:	ds.b	1
	even
	endm
