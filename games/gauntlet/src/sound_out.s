; Gauntlet's sound on the STE (tools/sound.py: the recordings, the data, the same player in Python): the commands the
; game sends (sound.s's ring snd_queue / snd_qhead) played the way the arcade's 6502 driver plays them, as far as it
; matters:
;   * 12 logical channels (0-3 the POKEY's, 4-11 the YM2151's), voices with priorities: a sound starts one voice per
;     channel of its chain (recorded alone on the reference board: a stream of YM2149 values a tick, the ticks it
;     lives in the driver's lists); a voice of the same priority on the channel is replaced, a lower one keeps running
;     underneath and is heard again when the higher one ends; a voice whose life is over plays on as a tail (the
;     chip's release) while nothing else is on its channel; 30 live voices at most (the driver's rule when full);
;   * $00 stops everything (and empties the speech queue), $30/$32/$34/$36 stop a sound, $43 / $48 fade the music
;     (FADE_STEP ticks a volume step), $01/$02 the floor (speech and voices below it muted: the attract mode hears
;     only the priorities from 60 on), $DD-$E0 the mixer (the POKEY's gain);
;   * speech: a phrase with its priority (the driver's 8-deep queue: a higher priority empties it, the same is
;     appended, a lower one dropped), 4-bit ADPCM decoded a chunk a tick into a buffer that the DMA sound plays (8-bit,
;     6258 Hz mono, play once, no interrupt); the YM2151 / POKEY gains lowered while it speaks;
;   * the 12 channels on the YM2149's 3: each tick the loudest (a channel that had a YM channel keeps it on a tie),
;     tone / noise / both; the noise period of the loudest channel with noise.
; snd_out_init: once, interrupts off.  snd_out_vbl: every VBL (50 Hz: the recordings' tick), at IPL 4: everything
; above (the YM streams are played where they are; a phrase's ADPCM is decoded 64 bytes a tick, ~6000 cycles, while
; it speaks).  It runs on its own 512-byte stack: the VBL may interrupt the game's thread, whose stack (in the arcade's
; video RAM, above the game's variables) has no room for it.  Uses no MFP timer and no interrupt; registers saved.
; Cycles (tools/sound_test.py, a game frame a tick): median 1600 (one player) / 4500 (three), 99 % 11500-12500, a
; tick that starts several sounds up to ~28000; the title music ~10000.  SIM: no hardware writes.

SO_NSLOT = 40				; voice slots (tools/sound.py NSLOT)
SO_LIVE_MAX = 30
SO_FADE_STEP = 11
SO_FADE_END = 15
SO_NCH = 12
SO_DEC_LEAD = 128			; tools/sound.py DEC_LEAD, DEC_TICK
SO_DEC_TICK = 64
; a voice slot
V_PTR = 0				; the stream's next byte
V_LOOP = 4				; the loop's address (0: none)
V_LIFE = 8				; live ticks left (-1: for ever)
V_PER = 10				; tone period
V_LEFT = 12				; ticks still held
V_VOL = 13
V_NP = 14				; noise period
V_MODE = 15				; 1 tone, 2 noise, 3 both
V_CH = 16
V_PRI = 17
V_SND = 18
V_FADE = 19				; 0, or the ticks into the fade's step (1..SO_FADE_STEP)
V_FOFF = 20				; the fade's volume offset
V_ON = 21				; 0 free, 1 live, 2 tail, 3 its life just ended
V_KEY = 22				; the priority + 1 while live, else 0
V_CH4 = 23				; the channel * 4
V_P41 = 24				; the priority * 4 + 1 (the driver's $03AE: against the floor)
V_SIZE = 32
; a channel's value for the mixer (so_vals)
C_PTR = 0				; the voice
C_VOL = 4				; its volume with the fade and the gains
C_SIZE = 8
; a phrase (so_phrases)
P_PCM = 0
P_LEN = 4
P_PRI = 8
P_DROP = 9
P_BUSY = 10
P_DUCK = 12
P_SIZE = 16
; a voice of a sound (after the sound's word count)
E_CH = 0
E_PRI = 1
E_LIFE = 2
E_DATA = 4
E_LOOP = 8
E_SIZE = 12
; command kinds (so_cmds)
K_NONE = 0
K_STOPALL = 1
K_SOUND = 2
K_KILL = 3
K_FADE = 4
K_FADEPRI = 5
K_SPEECH = 6
K_FLOOR = 7
K_MIXER = 8

; the slot loops run over the slots in use (so_hw: 1 + the highest active one; at least one pass)
SLOTS	macro
	move.w	so_hw,\1
	subq.w	#1,\1
	bpl.s	*+4
	moveq	#0,\1
	endm

	section text,code
snd_out_init:
	movem.l	d0-d1/a0,-(sp)
	lea	so_vars,a0
	move.w	#(so_vars_end-so_vars)/2-1,d0
.c:	clr.w	(a0)+
	dbf	d0,.c
	lea	so_assigned,a0
	moveq	#SO_NCH-1,d0
.a:	st	(a0)+
	dbf	d0,.a
	lea	so_shadow,a0
	moveq	#16-1,d0
.s:	st	(a0)+
	dbf	d0,.s
	move.b	#$ff,so_regs+7
	move.b	#$ff,so_regs+11		; (never written: so_mix compares 12 bytes with the shadow)
	move.b	#$ff,so_mixer
	move.b	#$ff,so_duckmix
	move.b	snd_qhead,so_tail	; (what the game sent before is not played)
	move.w	#-1,so_speech
	ifnd SIM
	move.b	#7,$ffff8800.w		; tones and noises off (ports A, B outputs)
	move.b	#$ff,$ffff8802.w
	moveq	#8,d0
.v:	move.b	d0,$ffff8800.w		; volumes 0
	clr.b	$ffff8802.w
	addq.b	#1,d0
	cmp.b	#11,d0
	bne.s	.v
	clr.b	$ffff8901.w		; the DMA sound: stopped, mono 6258 Hz
	move.b	#$80,$ffff8921.w
	endc
	movem.l	(sp)+,d0-d1/a0
	rts

; ---- a tick ------------------------------------------------------------------------------------------------------
snd_out_vbl:
	move.l	sp,so_savesp		; (an own stack: the VBL may come while the game's thread runs deep in its small
	lea	so_stack_top,sp		; stack in the arcade's video RAM)
	movem.l	d0-d7/a0-a6,-(sp)
	move.w	#-1,so_speech
	bsr	so_speech_tick
.cmd:	moveq	#0,d0			; the commands sent since the last tick
	move.b	so_tail,d0
	cmp.b	snd_qhead,d0
	beq.s	.cmds_done
	lea	snd_queue,a0
	moveq	#0,d1
	move.b	(a0,d0.w),d1
	addq.b	#1,d0
	and.b	#63,d0
	move.b	d0,so_tail
	bsr	so_command
	bra.s	.cmd
.cmds_done:
	bsr	so_voices
	bsr	so_channels
	bsr	so_mix
	bsr	so_decode
	movem.l	(sp)+,d0-d7/a0-a6
	move.l	so_savesp,sp
	rts

; d1.w = a command
so_command:
	lea	so_cmds,a0
	add.w	d1,d1
	moveq	#0,d0
	move.b	(a0,d1.w),d0		; kind
	move.b	1(a0,d1.w),d1		; argument
	and.w	#$ff,d1
	add.w	d0,d0
	move.w	.k(pc,d0.w),d0
	jmp	.k(pc,d0.w)
.k:	dc.w	.none-.k,.stopall-.k,so_start_sound-.k,.kill-.k,.fade-.k,.fadepri-.k,so_speak-.k,.floor-.k,.mixer-.k
.none:	rts
.stopall:
	lea	so_slots,a1
	SLOTS	d0
.sa:	clr.b	V_ON(a1)
	lea	V_SIZE(a1),a1
	dbf	d0,.sa
	clr.w	so_hw
	move.b	so_qhead,so_qtail
	rts
.kill:	lea	so_slots,a1
	SLOTS	d0
.ki:	tst.b	V_ON(a1)
	beq.s	.ki2
	cmp.b	V_SND(a1),d1
	bne.s	.ki2
	clr.b	V_ON(a1)
.ki2:	lea	V_SIZE(a1),a1
	dbf	d0,.ki
	rts
.fade:	lea	so_slots,a1
	SLOTS	d0
.fa:	tst.b	V_ON(a1)
	beq.s	.fa2
	cmp.b	V_SND(a1),d1
	bne.s	.fa2
	tst.b	V_FADE(a1)
	bne.s	.fa2
	move.b	#1,V_FADE(a1)
.fa2:	lea	V_SIZE(a1),a1
	dbf	d0,.fa
	rts
.fadepri:
	lea	so_slots,a1
	SLOTS	d0
.fp:	cmp.b	#1,V_ON(a1)
	bne.s	.fp2
	cmp.b	V_PRI(a1),d1
	bne.s	.fp2
	tst.b	V_FADE(a1)
	bne.s	.fp2
	move.b	#1,V_FADE(a1)
.fp2:	lea	V_SIZE(a1),a1
	dbf	d0,.fp
	rts
.floor:	move.b	d1,so_floor
	rts
.mixer:	move.b	d1,so_mixer
	rts

; d1.w = a sound: a voice for each of its entries (stops at the first the driver would not start)
so_start_sound:
	lea	so_sounds,a0
	add.w	d1,d1
	add.w	d1,d1
	move.l	(a0,d1.w),a2
	lsr.w	#2,d1
	move.w	(a2)+,d7		; voices
	subq.w	#1,d7
.entry:	moveq	#0,d2
	move.b	E_CH(a2),d2
	move.b	E_PRI(a2),d3
	; the driver's 30 voices: when full, the channel's lowest voice is taken if the new one is not lower
	cmp.w	#SO_LIVE_MAX,so_hw	; (fewer slots in use: room for sure)
	blo.s	.room
	lea	so_slots,a1
	SLOTS	d0
	moveq	#0,d4
.cnt:	cmp.b	#1,V_ON(a1)
	bne.s	.cnt2
	addq.w	#1,d4
.cnt2:	lea	V_SIZE(a1),a1
	dbf	d0,.cnt
	cmp.w	#SO_LIVE_MAX,d4
	blo.s	.room
	lea	so_slots,a1
	SLOTS	d0
	sub.l	a3,a3
.low:	cmp.b	#1,V_ON(a1)
	bne.s	.low2
	cmp.b	V_CH(a1),d2
	bne.s	.low2
	move.l	a3,d5
	beq.s	.low1
	move.b	V_PRI(a1),d5
	cmp.b	V_PRI(a3),d5
	bhs.s	.low2
.low1:	move.l	a1,a3
.low2:	lea	V_SIZE(a1),a1
	dbf	d0,.low
	move.l	a3,d5
	beq	.out
	cmp.b	V_PRI(a3),d3
	blo	.out
	clr.b	V_ON(a3)
.room:	; a tail on the channel, or a live voice of the same priority: replaced
	lea	so_slots,a1
	SLOTS	d0
	sub.l	a3,a3			; (the first free slot)
.kill:	move.b	V_ON(a1),d5
	beq.s	.free
	cmp.b	V_CH(a1),d2
	bne.s	.kill2
	cmp.b	#1,d5
	bne.s	.kill1
	cmp.b	V_PRI(a1),d3
	bne.s	.kill2
.kill1:	clr.b	V_ON(a1)
.free:	move.l	a3,d5
	bne.s	.kill2
	move.l	a1,a3
.kill2:	lea	V_SIZE(a1),a1
	dbf	d0,.kill
	move.l	a3,d5
	bne.s	.got
	move.w	so_hw,d5		; none free below so_hw: the next one
	cmp.w	#SO_NSLOT,d5
	bhs.s	.out
	lsl.w	#5,d5
	lea	so_slots,a3
	add.w	d5,a3
.got:	move.l	a3,d5			; so_hw past it
	sub.l	#so_slots,d5
	lsr.w	#5,d5
	addq.w	#1,d5
	cmp.w	so_hw,d5
	bls.s	.hw
	move.w	d5,so_hw
.hw:	move.l	E_DATA(a2),V_PTR(a3)
	move.l	E_LOOP(a2),V_LOOP(a3)
	move.w	E_LIFE(a2),V_LIFE(a3)
	clr.w	V_PER(a3)
	clr.l	V_LEFT(a3)		; left, volume, noise, mode
	move.b	d2,V_CH(a3)
	move.b	d3,V_PRI(a3)
	move.b	d3,d5
	addq.b	#1,d5
	move.b	d5,V_KEY(a3)
	move.b	d2,d5
	add.b	d5,d5
	add.b	d5,d5
	move.b	d5,V_CH4(a3)
	move.b	d3,d5
	lsl.b	#2,d5
	addq.b	#1,d5
	move.b	d5,V_P41(a3)
	move.b	d1,V_SND(a3)
	clr.b	V_FADE(a3)
	clr.b	V_FOFF(a3)
	move.b	#1,V_ON(a3)
	lea	E_SIZE(a2),a2
	dbf	d7,.entry
.out:	rts

; ---- speech ------------------------------------------------------------------------------------------------------
; d1.w = a phrase
so_speak:
	move.w	d1,d0
	lsl.w	#4,d0
	lea	so_phrases,a0
	move.b	P_PRI(a0,d0.w),d2
	cmp.b	so_floor,d2
	blo.s	.out
	tst.w	so_busy
	beq	so_start_phrase
	moveq	#0,d0
	move.b	so_qhead,d0
	addq.b	#1,d0
	and.b	#7,d0
	cmp.b	so_qtail,d0
	beq.s	.out
	cmp.b	so_curpri,d2
	blo.s	.out
	beq.s	.same
	move.b	so_qhead,so_qtail	; a higher priority: the queue emptied
.same:	move.b	d2,so_curpri
	move.b	d0,so_qhead
	lea	so_queue,a0
	move.b	d1,(a0,d0.w)
.out:	rts

; d1.w = a phrase: started now
so_start_phrase:
	move.w	d1,so_speech
	move.w	d1,d0
	lsl.w	#4,d0
	lea	so_phrases,a0
	add.w	d0,a0
	move.b	P_PRI(a0),so_curpri
	move.w	P_BUSY(a0),so_busy
	move.w	P_DUCK(a0),so_duck
	moveq	#0,d2			; the mixer while it speaks: YM gain - drop / 2, POKEY gain - drop / 4
	move.b	P_DROP(a0),d2
	move.b	so_mixer,d3
	moveq	#7,d4
	and.b	d3,d4
	move.w	d2,d5
	lsr.w	#1,d5
	sub.w	d5,d4
	bpl.s	.y
	moveq	#0,d4
.y:	moveq	#$18,d5
	and.b	d3,d5
	lsr.w	#3,d5
	lsr.w	#2,d2
	sub.w	d2,d5
	bpl.s	.p
	moveq	#0,d5
.p:	lsl.w	#3,d5
	and.b	#$e0,d3
	or.b	d5,d3
	or.b	d4,d3
	move.b	d3,so_duckmix
	move.l	P_PCM(a0),so_dsrc	; its ADPCM bytes: decoded into so_spbuf (so_decode), played from there
	move.l	P_LEN(a0),d0
	move.w	d0,so_dleft
	move.l	#so_spbuf,d1
	move.l	d1,so_dout
	move.l	d1,so_dma_start
	add.l	d0,d1
	add.l	d0,d1
	move.l	d1,so_dma_end
	clr.w	so_dstate
	clr.b	so_dsample
	st	so_dfirst
	ifnd SIM
	clr.b	$ffff8901.w		; (a phrase still playing is cut)
	endc
	rts

; the phrase's next ADPCM bytes into so_spbuf: SO_DEC_LEAD at its start (then the DMA starts: play once, the whole
; phrase), SO_DEC_TICK a tick after that (128 samples; the DMA plays 125.2 a tick at 6258 Hz, so the decoder stays
; ahead).  A byte: (state << 8 | byte) * 4 into so_adpcm -> the two samples' deltas, the next state << 8.
so_decode:
	move.w	so_dleft,d7
	beq	.out
	moveq	#SO_DEC_TICK,d0
	tst.b	so_dfirst
	beq.s	.n
	move.w	#SO_DEC_LEAD,d0
.n:	cmp.w	d0,d7
	bls.s	.m
	move.w	d0,d7
.m:	sub.w	d7,so_dleft
	move.l	so_dsrc,a0
	move.l	so_dout,a4
	lea	so_adpcm,a2
	move.w	so_dstate,d1
	move.b	so_dsample,d3
	subq.w	#1,d7
.l:	move.b	(a0)+,d1
	move.w	d1,d4
	add.w	d4,d4
	add.w	d4,d4
	add.b	(a2,d4.w),d3
	move.b	d3,(a4)+
	add.b	1(a2,d4.w),d3
	move.b	d3,(a4)+
	move.w	2(a2,d4.w),d1
	dbf	d7,.l
	move.l	a0,so_dsrc
	move.l	a4,so_dout
	move.w	d1,so_dstate
	move.b	d3,so_dsample
	tst.b	so_dfirst
	beq.s	.out
	sf	so_dfirst
	ifnd SIM
	move.l	so_dma_start,d0
	move.b	d0,$ffff8907.w
	lsr.l	#8,d0
	move.b	d0,$ffff8905.w
	lsr.l	#8,d0
	move.b	d0,$ffff8903.w
	move.l	so_dma_end,d0
	move.b	d0,$ffff8913.w
	lsr.l	#8,d0
	move.b	d0,$ffff8911.w
	lsr.l	#8,d0
	move.b	d0,$ffff890f.w
	move.b	#1,$ffff8901.w		; play once
	endc
.out:	rts

so_speech_tick:
	tst.w	so_duck
	beq.s	.d
	subq.w	#1,so_duck
.d:	tst.w	so_busy
	beq.s	.out
	subq.w	#1,so_busy
	bne.s	.out
	move.b	so_qtail,d0
	cmp.b	so_qhead,d0
	beq.s	.idle
	addq.b	#1,d0
	and.w	#7,d0
	move.b	d0,so_qtail
	lea	so_queue,a0
	moveq	#0,d1
	move.b	(a0,d0.w),d1
	bra	so_start_phrase
.idle:	clr.b	so_curpri
.out:	rts

; ---- the voices: each one a step; then each channel's voice ------------------------------------------------------
so_voices:
	lea	so_slots,a1
	SLOTS	d6
.v:	tst.b	V_ON(a1)
	beq.s	.next
	bsr	so_step
	tst.w	d0
	bne.s	.kill
	move.b	V_FADE(a1),d0
	beq.s	.life
	cmp.b	#SO_FADE_STEP,d0
	bne.s	.fstep
	move.b	#1,V_FADE(a1)
	addq.b	#1,V_FOFF(a1)
	cmp.b	#SO_FADE_END,V_FOFF(a1)
	bhs.s	.kill
	bra.s	.life
.fstep:	addq.b	#1,V_FADE(a1)
.life:	cmp.b	#1,V_ON(a1)
	bne.s	.next
	move.w	V_LIFE(a1),d0
	cmp.w	#-1,d0
	beq.s	.next
	tst.w	d0
	bne.s	.dec
	move.b	#3,V_ON(a1)
	clr.b	V_KEY(a1)
	st	so_ended
	bra.s	.next
.dec:	subq.w	#1,V_LIFE(a1)
	bra.s	.next
.kill:	clr.b	V_ON(a1)
.next:	lea	V_SIZE(a1),a1
	dbf	d6,.v
	move.w	so_hw,d0		; so_hw down to the last active slot
	beq.s	.hw2
	move.w	d0,d1
	lsl.w	#5,d1
	lea	so_slots-V_SIZE,a1
	add.w	d1,a1
.hw:	tst.b	V_ON(a1)
	bne.s	.hw1
	lea	-V_SIZE(a1),a1
	subq.w	#1,d0
	bne.s	.hw
.hw1:	move.w	d0,so_hw
.hw2:	rts

; a1 = a voice: its stream one tick on (the decoder of tools/sound.py Stream).  d0 = 0, or 1 at its end.  Uses a0.
so_step:
	tst.b	V_LEFT(a1)
	beq.s	.read
	subq.b	#1,V_LEFT(a1)
	moveq	#0,d0
	rts
.read:	move.l	V_PTR(a1),a0
.n:	moveq	#0,d0
	move.b	(a0)+,d0
	cmp.b	#$ff,d0
	beq.s	.end
	cmp.b	#$c0,d0
	bhs.s	.noise
	cmp.b	#$b0,d0
	bhs.s	.mode
	cmp.b	#$a0,d0
	bhs.s	.per
	cmp.b	#$90,d0
	bhs.s	.down
	cmp.b	#$80,d0
	bhs.s	.vol
	move.b	d0,V_LEFT(a1)		; hold
	bra.s	.out
.noise:	and.b	#31,d0
	move.b	d0,V_NP(a1)
	bra.s	.n
.mode:	and.b	#3,d0
	move.b	d0,V_MODE(a1)
	bra.s	.n
.per:	and.w	#15,d0
	lsl.w	#8,d0
	move.b	(a0)+,d0
	move.w	d0,V_PER(a1)
	bra.s	.n
.down:	subq.b	#1,V_VOL(a1)
	and.b	#15,d0
	move.b	d0,V_LEFT(a1)
	bra.s	.out
.vol:	and.b	#15,d0
	move.b	d0,V_VOL(a1)
.out:	move.l	a0,V_PTR(a1)
	moveq	#0,d0
	rts
.end:	move.l	V_LOOP(a1),d0
	beq.s	.stop
	move.l	d0,a0
	bra.s	.n
.stop:	moveq	#1,d0
	rts

; each channel's voice: the live one of the highest priority, else a tail; a voice whose life just ended goes, or
; stays as a tail while no live voice is on its channel.  Then the channels' values with the floor and the mixer's
; gains: those with sound in so_vals and, as (key = volume * 2 + 1 if it has a YM channel, channel), in so_cand.
so_channels:
	tst.w	so_hw			; no voices: no sound
	bne.s	.any
	clr.w	so_ncand
	rts
.any:	moveq	#0,d0
	moveq	#0,d1
	moveq	#0,d2
	moveq	#0,d3
	moveq	#0,d4
	moveq	#0,d5
	lea	so_best+4*SO_NCH,a0	; the slot (address) of each channel, 0: none
	movem.l	d0-d5,-(a0)
	movem.l	d0-d5,-(a0)
	moveq	#-1,d0
	moveq	#-1,d1
	moveq	#-1,d2
	moveq	#-1,d3
	moveq	#-1,d4
	moveq	#-1,d5
	lea	so_bkey4+4*SO_NCH,a0	; its key (a long a channel): the priority + 1 (live), 0 (tail); -1: none
	movem.l	d0-d5,-(a0)
	movem.l	d0-d5,-(a0)
	lea	so_best,a2
	lea	so_bkey4,a3
	lea	so_slots,a1
	SLOTS	d6
.b:	tst.b	V_ON(a1)
	beq.s	.b2
	moveq	#0,d3
	move.b	V_CH4(a1),d3
	move.b	V_KEY(a1),d2
	cmp.b	(a3,d3.w),d2
	ble.s	.b2
	move.b	d2,(a3,d3.w)
	move.l	a1,(a2,d3.w)
.b2:	lea	V_SIZE(a1),a1
	dbf	d6,.b
	tst.b	so_ended		; the voices whose life ended
	beq.s	.gains
	sf	so_ended
	lea	so_slots,a1
	SLOTS	d6
.e:	cmp.b	#3,V_ON(a1)
	bne.s	.e3
	moveq	#0,d3
	move.b	V_CH4(a1),d3
	tst.b	(a3,d3.w)
	ble.s	.e1
	clr.b	V_ON(a1)		; a live voice on its channel: gone
	bra.s	.e3
.e1:	move.b	#2,V_ON(a1)		; a tail
.e3:	lea	V_SIZE(a1),a1
	dbf	d6,.e
.gains:	; the gains: the mixer (lowered while a phrase speaks)
	move.b	so_mixer,d0
	tst.w	so_duck
	beq.s	.g
	move.b	so_duckmix,d0
.g:	moveq	#7,d1
	and.w	d0,d1
	lea	so_ym_off,a0
	move.b	(a0,d1.w),d4		; the YM2151's offset ($80: mute)
	lsr.b	#3,d0
	and.w	#3,d0
	move.b	so_pokey_off-so_ym_off(a0,d0.w),d5
	lea	so_vals,a4
	lea	so_cand,a0
	lea	so_assigned,a3
	moveq	#0,d7			; the candidates
	moveq	#0,d6			; the channel
	move.b	d5,d2			; the POKEY's 4
	moveq	#4-1,d3
	bsr.s	.grp
	move.b	d4,d2			; the YM2151's 8
	moveq	#8-1,d3
	bsr.s	.grp
	move.w	d7,so_ncand
	rts
; d2 = the group's gain offset, d3 = its channels - 1, d6 its first channel, a2 its so_best
.grp:	cmp.b	#$80,d2
	bne.s	.gl
	addq.w	#1,d3			; (muted: skipped)
	add.w	d3,d6
	add.w	d3,d3
	add.w	d3,d3
	add.w	d3,a2
	rts
.gl:	move.l	(a2)+,d0
	beq.s	.gn
	move.l	d0,a1
	move.b	V_P41(a1),d1		; the floor: a voice below it is muted (its tail too)
	cmp.b	so_floor,d1
	blo.s	.gn
	move.b	V_VOL(a1),d1
	sub.b	V_FOFF(a1),d1
	ble.s	.gn
	tst.b	V_MODE(a1)
	beq.s	.gn
	add.b	d2,d1
	ble.s	.gn
	move.w	d6,d0
	lsl.w	#3,d0
	move.l	a1,C_PTR(a4,d0.w)
	move.b	d1,C_VOL(a4,d0.w)
	ext.w	d1
	add.w	d1,d1
	tst.b	(a3,d6.w)
	bmi.s	.gk
	addq.w	#1,d1
.gk:	move.w	d1,(a0)+
	move.w	d6,(a0)+
	addq.w	#1,d7
.gn:	addq.w	#1,d6
	dbf	d3,.gl
	rts

so_ym_off:	dc.b	$80,-6,-4,-2,-2,-1,0,0	; tools/sound.py YM_OFF
so_pokey_off:	dc.b	$80,-3,-1,0
	even

; ---- the YM2149: the three loudest channels ----------------------------------------------------------------------
so_mix:
	moveq	#-1,d0
	move.l	d0,so_picked
	lea	so_vals,a4
	lea	so_assigned,a3
	move.w	so_ncand,d5
	lea	so_picked,a2
	subq.w	#1,d5
	bmi.s	.rend
	moveq	#3-1,d7			; three rounds: the highest key not picked yet (the first channel on a tie)
.round:	moveq	#-1,d2
	moveq	#-1,d3
	lea	so_cand,a0
	move.w	d5,d4
.rl:	move.w	(a0),d0
	cmp.w	d2,d0
	ble.s	.rn
	move.w	d0,d2
	move.l	a0,a5
	move.w	2(a0),d3
.rn:	addq.l	#4,a0
	dbf	d4,.rl
	tst.w	d3
	bmi.s	.rend
	move.w	#-1,(a5)		; (picked)
	move.b	d3,(a2)+
	dbf	d7,.round
.rend:	; the YM channels: a picked channel keeps its own, the others take the free ones in order
	lea	so_out,a0
	moveq	#-1,d0
	move.l	d0,(a0)			; (so_out: 3 bytes, -1 free)
	lea	so_new,a1
	move.l	d0,(a1)
	move.l	d0,4(a1)
	move.l	d0,8(a1)
	lea	so_picked,a2
	moveq	#3-1,d1
.k:	move.b	(a2)+,d0
	bmi.s	.k2
	ext.w	d0
	move.b	(a3,d0.w),d2
	bmi.s	.k2
	ext.w	d2
	move.b	d0,(a0,d2.w)
	move.b	d2,(a1,d0.w)
.k2:	dbf	d1,.k
	lea	so_picked,a2
	moveq	#3-1,d1
.f:	move.b	(a2)+,d0
	bmi.s	.f3
	ext.w	d0
	tst.b	(a1,d0.w)
	bpl.s	.f3
	moveq	#0,d2
.f1:	tst.b	(a0,d2.w)
	bmi.s	.f2
	addq.w	#1,d2
	bra.s	.f1
.f2:	move.b	d0,(a0,d2.w)
	move.b	d2,(a1,d0.w)
.f3:	dbf	d1,.f
	move.l	(a1),(a3)		; so_assigned = so_new (12 bytes)
	move.l	4(a1),4(a3)
	move.l	8(a1),8(a3)
	; the registers
	lea	so_regs,a1
	moveq	#$3f,d5			; the mixer's tone / noise off bits
	moveq	#0,d4			; the loudest volume with noise
	moveq	#0,d1			; the YM channel
.r:	move.b	(a0,d1.w),d0
	bpl.s	.r1
	clr.b	8(a1,d1.w)
	bra.s	.r4
.r1:	ext.w	d0
	lsl.w	#3,d0
	lea	(a4,d0.w),a2
	move.b	C_VOL(a2),d2
	move.b	d2,8(a1,d1.w)
	move.l	C_PTR(a2),a2		; (the voice)
	move.b	V_MODE(a2),d3
	btst	#0,d3
	beq.s	.r2
	move.w	d1,d0
	add.w	d0,d0
	move.b	V_PER+1(a2),(a1,d0.w)
	move.b	V_PER(a2),1(a1,d0.w)
	bclr	d1,d5
.r2:	btst	#1,d3
	beq.s	.r4
	move.w	d1,d0
	addq.w	#3,d0
	bclr	d0,d5
	cmp.b	d4,d2
	bls.s	.r4
	move.b	d2,d4
	move.b	V_NP(a2),6(a1)
.r4:	addq.w	#1,d1
	cmp.w	#3,d1
	bne.s	.r
	or.b	#$c0,d5
	move.b	d5,7(a1)
	lea	so_shadow,a0		; written where they changed
	cmpm.l	(a0)+,(a1)+		; (most ticks: none)
	bne.s	.diff
	cmpm.l	(a0)+,(a1)+
	bne.s	.diff
	cmpm.l	(a0)+,(a1)+
	beq.s	.same
.diff:	lea	so_regs,a1
	lea	so_shadow,a0
	moveq	#0,d1
	moveq	#11-1,d2
.w:	move.b	(a1)+,d0
	cmp.b	(a0)+,d0
	beq.s	.w2
	move.b	d0,-1(a0)
	ifnd SIM
	move.b	d1,$ffff8800.w
	move.b	d0,$ffff8802.w
	endc
.w2:	addq.b	#1,d1
	dbf	d2,.w
.same:	rts

	section data,data
	even
	include	"sound_data.s"		; (tools/sound.py: so_cmds, so_sounds, so_phrases, the streams, the speech)
	even

	section bss,bss
	even
so_vars:
so_slots:	ds.b	SO_NSLOT*V_SIZE
so_best:	ds.l	SO_NCH
so_vals:	ds.b	SO_NCH*C_SIZE
so_bkey4:	ds.l	SO_NCH
so_assigned:	ds.b	SO_NCH
so_new:		ds.b	SO_NCH
so_out:		ds.b	4
so_picked:	ds.b	4
so_cand:	ds.l	SO_NCH
so_regs:	ds.b	16		; the YM2149's registers 0-10 as the tick leaves them
so_shadow:	ds.b	16
so_queue:	ds.b	8		; the speech queue
so_dsrc:	ds.l	1		; the phrase's next ADPCM byte
so_dout:	ds.l	1		; ... its next sample in so_spbuf
so_dleft:	ds.w	1		; its ADPCM bytes left
so_dstate:	ds.w	1		; the decoder's state << 8
so_dsample:	ds.b	1		; ... its sample
so_dfirst:	ds.b	1		; the phrase starts: the lead is decoded, then the DMA starts
so_dma_start:	ds.l	1
so_dma_end:	ds.l	1
so_hw:		ds.w	1
so_ncand:	ds.w	1		; 1 + the highest slot in use
so_busy:	ds.w	1		; ticks until the next phrase may start
so_duck:	ds.w	1		; ticks the mixer stays lowered
so_speech:	ds.w	1		; the phrase started this tick (-1: none)
so_tail:	ds.b	1		; snd_queue's next command
so_qhead:	ds.b	1
so_qtail:	ds.b	1
so_curpri:	ds.b	1
so_floor:	ds.b	1
so_mixer:	ds.b	1
so_duckmix:	ds.b	1
so_ended:	ds.b	1		; a voice's life ended this tick
	even
so_vars_end:
so_spbuf:	ds.b	SO_SPBUF	; the phrase being spoken (signed 8-bit, 6258 Hz)
	even
so_savesp:	ds.l	1
		ds.b	512		; snd_out_vbl's stack (and the interrupts' that come during it)
so_stack_top:
	section text,code
