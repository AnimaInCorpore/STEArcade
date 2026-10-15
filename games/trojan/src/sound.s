; The sound: Capcom's sound driver (the YM2203 pair) recorded per command by engine/capsnd.py (tools/sound.py), played
; on the YM2149 by engine/rt/capsnd.s once an arcade frame (its four IRQs, with the latch the frame before left).  The
; ADPCM voices (the second sound Z80 and its MSM5205, latch $F80D) are not played.
CS_CMDMASK = $7F			; (the driver's dispatch keeps 7 bits: 128 commands)
CS_LATCH = g_sound_latch		; (the program's last $F80C store: tr_sound)
	include	"cs_data.s"
	section	text,code
	include	"capsnd.s"
snd_init:
	bra	cs_init
snd_off:
	bra	cs_off
snd_frame:
	movem.l	d0-d7/a0-a4,-(sp)
	bsr	cs_tick
	movem.l	(sp)+,d0-d7/a0-a4
	rts
snd_vbl:
	rts
