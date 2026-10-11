; ------------------------------------------------------------------------------
; Bubble Bobble's sound on the YM2149: the sound driver's tracks as streams, a value a VBL (tools/sound.py records
; and checks them; its Player and play() are this code in Python).
;
; The main CPU's writes of the sound latch ($FA00, a write hook: bb_snd_put) are queued; bb_snd_vbl (the VBL) takes
; them: a command starts its items, one a track (28: $84-$BA / 2), unless the track plays one with a lower priority
; number (the driver's 0357), and queues the commands it chains.  Then each track steps: an OPL or FM channel's
; stream (cs_chan: a period and a volume) or the SSG's registers (cs_step); a track without a loop ends after its
; VBLs.  Each channel plays its A track while that plays, else its B track (0535); the SSG likewise ($84 over $86).
; The SSG is the effect of the mixer (cs_mix): the loudest of the twelve channels (OPL 0-8, FM 0-2; the FM ones, the
; effects, first: cs_boost) take the YM channels it leaves.
; ------------------------------------------------------------------------------

CS_MCH = 12
CS_BOOST = 1
	include	"capsnd_core.s"

; a track
TR_ON = 0				; .b  it plays
TR_PRI = 1				; .b  its item's priority
TR_KIND = 2				; .b  0 a channel stream, 1 SSG registers
TR_N = 4				; .w  VBLs played
TR_LEN = 6				; .w  its VBLs, 0: it loops
TR_ST = 8				; the stream's state: a channel (CH_SIZE) or an effect slot (SL_SIZE)
TR_SIZE = TR_ST+SL_SIZE
TRACKS = 28

; an item (bb_sound.s)
IT_TRACK = 0				; .b
IT_PRI = 1				; .b
IT_KIND = 2				; .b
IT_LEN = 4				; .w
IT_DATA = 6				; .l
IT_LOOP = 10				; .l
IT_SIZE = 14

; The write hook of $FA00: the command in d0 to the queue.  Keeps every register.
bb_snd_put:
	move.l	a0,-(sp)
	move.w	d1,-(sp)
	moveq	#0,d1
	move.b	bb_qhead,d1
	lea	bb_queue,a0
	move.b	d0,(a0,d1.w)
	addq.b	#1,d1
	and.b	#15,d1
	cmp.b	bb_qtail,d1
	beq.s	.full			; (16 waiting: the newest is dropped, as the driver's ring does)
	move.b	d1,bb_qhead
.full:	move.w	(sp)+,d1
	move.l	(sp)+,a0
	rts

; The VBL: the queued commands, a step of every track, the YM.  Uses d0-d7 / a0-a4.
bb_snd_vbl:
.q:	moveq	#0,d0
	move.b	bb_qtail,d0
	cmp.b	bb_qhead,d0
	beq.s	.steps
	lea	bb_queue,a0
	move.b	(a0,d0.w),d1
	addq.b	#1,d0
	and.b	#15,d0
	move.b	d0,bb_qtail
	move.b	d1,d0
	bsr	bb_command
	bra.s	.q
.steps:	bsr	bb_step
	lea	bb_ssg,a1
	bsr	cs_mix
	lea	cs_regs,a1
	lea	bb_ym,a2
	moveq	#0,d1
.w:	move.b	(a1)+,d0
	cmp.b	(a2),d0
	beq.s	.same
	move.b	d0,(a2)
	move.b	d1,$ffff8800.w
	move.b	d0,$ffff8802.w
.same:	addq.l	#1,a2
	addq.b	#1,d1
	cmp.b	#11,d1
	blo.s	.w
	rts

; command d0.b: its items, then the commands it chains.  Uses d0-d5 / a0-a3.
bb_command:
	cmp.b	#$35,d0
	bhs	.none
	and.w	#$FF,d0
	lsl.w	#2,d0
	lea	bb_cmds,a0
	move.l	(a0,d0.w),d0
	beq	.none
	move.l	d0,a3
	moveq	#0,d4
	move.b	(a3)+,d4		; the items
	moveq	#0,d5
	move.b	(a3)+,d5		; the chained commands
	bra.s	.next
.item:	moveq	#0,d0			; the track
	move.b	IT_TRACK(a3),d0
	mulu	#TR_SIZE,d0
	lea	bb_tracks,a0
	add.l	d0,a0
	tst.b	TR_ON(a0)
	beq.s	.start
	move.b	IT_PRI(a3),d1		; it plays: a lower priority number keeps it
	and.b	#$F0,d1
	cmp.b	TR_PRI(a0),d1
	bhi.s	.skip
.start:	st	TR_ON(a0)
	move.b	IT_PRI(a3),TR_PRI(a0)
	move.b	IT_KIND(a3),TR_KIND(a0)
	clr.w	TR_N(a0)
	move.w	IT_LEN(a3),TR_LEN(a0)
	lea	TR_ST(a0),a1
	tst.b	IT_KIND(a3)
	bne.s	.ssg
	move.l	IT_DATA(a3),CH_POS(a1)	; a channel stream
	move.l	IT_LOOP(a3),CH_LOOP(a1)
	clr.l	CH_PER(a1)
	bra.s	.skip
.ssg:	move.l	IT_DATA(a3),a2		; SSG registers: an effect slot
	move.l	a2,SL_ENT(a1)
	move.l	SE_RUNS(a2),SL_POS(a1)
	clr.w	SL_N(a1)
	clr.w	SL_T(a1)
	clr.b	SL_LEFT(a1)
	clr.b	SL_PHASE(a1)
	st	SL_EXCPH(a1)
.skip:	lea	IT_SIZE(a3),a3
.next:	dbf	d4,.item
	bra.s	.cnext
.chain:	moveq	#0,d0
	move.b	(a3)+,d0
	movem.l	d5/a3,-(sp)
	bsr	bb_command
	movem.l	(sp)+,d5/a3
.cnext:	dbf	d5,.chain
.none:	rts

; a VBL of every track -> bb_val (per track: its period and volume, or its registers' address), the channels' values
; (cs_vals: the A track's, else the B track's), the SSG's registers (bb_ssg).  Uses d0-d7 / a0-a4.
bb_step:
	lea	bb_tracks,a4
	moveq	#0,d7			; the track
.tr:	tst.b	TR_ON(a4)
	beq.s	.off
	move.w	TR_LEN(a4),d0
	beq.s	.go
	cmp.w	TR_N(a4),d0
	bhi.s	.go
	clr.b	TR_ON(a4)		; it ended
.off:	lea	bb_on,a0
	clr.b	(a0,d7.w)
	bra.s	.next
.go:	addq.w	#1,TR_N(a4)
	lea	bb_on,a0
	st	(a0,d7.w)
	tst.b	TR_KIND(a4)
	bne.s	.ssg
	lea	TR_ST(a4),a2		; (cs_chan uses a3, cs_step a1-a3)
	bsr	cs_chan
	lea	bb_val,a0
	move.w	d7,d2
	lsl.w	#2,d2
	move.w	d0,(a0,d2.w)
	move.w	d1,2(a0,d2.w)
	bra.s	.next
.ssg:	lea	TR_ST(a4),a0
	bsr	cs_step
	lea	TR_ST+SL_OUT(a4),a0
	lea	bb_val,a1
	move.w	d7,d2
	lsl.w	#2,d2
	move.l	a0,(a1,d2.w)
.next:	lea	TR_SIZE(a4),a4
	addq.w	#1,d7
	cmp.w	#TRACKS,d7
	blo.s	.tr
	lea	bb_chan_tracks,a1	; the channels: per channel its A and B track
	lea	cs_vals,a2
	moveq	#CS_MCH-1,d6
.ch:	moveq	#0,d0
	move.b	(a1)+,d0		; A
	bsr.s	bb_pick
	bne.s	.got
	moveq	#0,d0
	move.b	(a1),d0			; B
	bsr.s	bb_pick
	bne.s	.got
	clr.l	(a2)+			; neither: silent
	addq.l	#1,a1
	dbf	d6,.ch
	bra.s	.ssg_out
.got:	move.l	(a0),(a2)+
	addq.l	#1,a1
	dbf	d6,.ch
.ssg_out:
	moveq	#0,d0			; the SSG: $84, else $86
	bsr.s	bb_pick
	bne.s	.s_got
	moveq	#1,d0
	bsr.s	bb_pick
	bne.s	.s_got
	lea	bb_ssg+8,a0		; neither plays: the registers stay, silent
	clr.b	(a0)+
	clr.b	(a0)+
	clr.b	(a0)
	rts
.s_got:	move.l	(a0),a0
	lea	bb_ssg,a1
	moveq	#11-1,d0
.c:	move.b	(a0)+,(a1)+
	dbf	d0,.c
	rts

; track d0: Z clear when it plays, a0 its bb_val entry
bb_pick:
	lea	bb_on,a0
	tst.b	(a0,d0.w)
	beq.s	.no
	lea	bb_val,a0
	lsl.w	#2,d0
	add.w	d0,a0
	moveq	#1,d0
	rts
.no:	moveq	#0,d0
	rts

; per channel (OPL 0-8, FM 0-2): its A track, its B track
bb_chan_tracks:
	dc.b	10,11, 12,13, 14,15, 16,17, 18,19, 20,21, 22,23, 24,25, 26,27
	dc.b	4,5, 6,7, 8,9
	even

; At the start: no sound.
bb_snd_init:
	lea	bb_bss,a0
	move.w	#bb_bss_end-bb_bss-1,d0
.c:	clr.b	(a0)+
	dbf	d0,.c
	lea	bb_ym,a0
	moveq	#11-1,d0
.y:	st	(a0)+
	dbf	d0,.y
	lea	bb_ssg_idle,a0
	lea	bb_ssg,a1
	moveq	#11-1,d0
.s:	move.b	(a0)+,(a1)+
	dbf	d0,.s
	bra	cs_mix_init

	include	"bb_sound.s"

	section bss,bss
	even
bb_bss:
bb_tracks:	ds.b	TRACKS*TR_SIZE
bb_val:		ds.l	TRACKS		; per track: its period and volume (words), or its registers' address
bb_on:		ds.b	TRACKS		; per track: it played this VBL
bb_ssg:		ds.b	12		; the SSG's registers 0-10 (the mixer's effect)
bb_ym:		ds.b	12		; the YM2149's registers 0-10 as written
bb_queue:	ds.b	16		; the commands from the main CPU
bb_qhead:	ds.b	1
bb_qtail:	ds.b	1
	even
bb_bss_end:
	section text,code
