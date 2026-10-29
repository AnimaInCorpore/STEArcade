; ------------------------------------------------------------------------------
;
; Sound: not ported yet.  Junior's sound board is Donkey Kong's 8035 with its own
; program (djr1-c_3h.3h) and its own discrete circuits; the plan is the Donkey Kong
; port's (games/dkong/src/sound.s): the 8035's DAC recorded in MAME and played as DMA
; sound, the discrete effects on the YM.  Until then the program is silent.
;
; ------------------------------------------------------------------------------

init_sound:
stop_sound:
sound_update:
	rts
