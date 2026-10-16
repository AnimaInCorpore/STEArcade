; The sound: the ADPCM samples (the punches, kicks, shouts: commands $80-$9A) on the STE's DMA sound, the YM2151's
; tunes and effects on the YM2149 (tools/sound.py: recorded per command on the reference board's sound part, three
; voices a frame, music_data.s).
;
; The YM part: a tune command starts its three voices (the music), an effect command its one voice, which takes YM
; voice C while it plays; $FF stops the music, $FE the effect, $FD both, $F0-$FC a channel (0-6 the music, 7 the
; effect).  A voice's stream (engine/capsnd.py's encoding): $00-$7F hold n + 1 frames, $80-$8F a volume (a frame),
; $90-$9F the volume - 1 then hold the low nibble's frames, $A0-$AF + a byte a period (no frame), $FF the end (the loop,
; or silence).
;
; The driver's ADPCM part (21j-0-1 $88E5, its table at $8966): a command stops its chip and starts its sample there
; (every priority is 0).  Each command's sample is decoded at build time (tools/build.py write_sound, tools/sound.py:
; MAME's MSM5205, read at 6258 Hz, the 12-bit signal >> 4 a byte): a command points its chip's voice at its stream; the
; two voices are mixed (their sum, clipped to 8 bits) into a looping DMA buffer at 6258 Hz (mono), filled once an
; arcade frame up to where the DMA reads.
SND_BUF = 1024				; samples (bytes): the looping DMA buffer
V_POS = 0				; the next sample's address
V_END = 4				; the stream's end (V_POS = V_END: the voice is silent)
V_SIZE = 8
; a YM voice
Y_PTR = 0
Y_LOOP = 4				; (0: none)
Y_PER = 8				; the period (word)
Y_LEFT = 10				; frames still held
Y_VOL = 11
Y_ON = 12
Y_SIZE = 14

	section text,code
snd_init:
	lea snd_buf,a0
	move.w #SND_BUF/4-1,d0
.c:	clr.l (a0)+
	dbf d0,.c
	clr.w snd_wpos
	lea ym_voices,a0
	moveq #4*Y_SIZE/2-1,d0
.y:	clr.w (a0)+
	dbf d0,.y
	lea ym_shadow,a0
	moveq #-1,d0
	move.l d0,(a0)+			; (all different: the first frame writes them)
	move.l d0,(a0)+
	move.l d0,(a0)+
	ifnd SIM
	move.b #7,$ffff8800.w
	move.b #$F8,$ffff8802.w		; the mixer: tones A B C, no noise (port A, B outputs)
	endc
	ifnd SIM
	move.l #snd_buf,d0
	move.b d0,$ffff8907.w		; the frame's start (low, mid, high)
	lsr.l #8,d0
	move.b d0,$ffff8905.w
	lsr.l #8,d0
	move.b d0,$ffff8903.w
	move.l #snd_buf+SND_BUF,d0
	move.b d0,$ffff8913.w		; its end
	lsr.l #8,d0
	move.b d0,$ffff8911.w
	lsr.l #8,d0
	move.b d0,$ffff890f.w
	move.b #$80,$ffff8921.w		; mono, 6258 Hz
	move.b #$03,$ffff8901.w		; play, loop
	endc
	rts

snd_off:
	ifnd SIM
	clr.b $ffff8901.w
	moveq #8,d0
.v:	move.b d0,$ffff8800.w		; the YM's volumes 0
	clr.b $ffff8802.w
	addq.b #1,d0
	cmp.b #11,d0
	bne.s .v
	endc
	rts

snd_vbl:
	rts

; snd_frame (once an arcade frame): the commands the program sent (core.s's ring) started, the buffer filled.
snd_frame:
	movem.l d0-d7/a0-a4,-(sp)
snd_cmd_loop:
	moveq #0,d0
	move.b snd_tail,d0
	cmp.b snd_head,d0
	beq .fill
	lea snd_ring,a0
	move.b (a0,d0.w),d1
	addq.b #1,snd_tail
	cmp.b #$80,d1
	blo.s .ym
	cmp.b #$F0,d1
	bhs.s .ym
	cmp.b #$9B,d1
	bhs.s snd_cmd_loop
	and.w #$7F,d1			; an ADPCM sample: its chip's voice on its stream
	mulu #10,d1
	lea adpcm_index,a0
	add.w d1,a0
	lea voice1,a1
	tst.w (a0)
	bne.s .v
	lea voice0,a1
.v:	lea adpcm_pcm,a2
	add.l 2(a0),a2
	move.l a2,V_POS(a1)
	add.l 6(a0),a2
	move.l a2,V_END(a1)
	bra snd_cmd_loop
.ym:	bra ym_command
.fill:
	ifd SIM
	move.w #126,d7			; (no DMA: a VBL's worth)
	else
	moveq #0,d0			; the DMA's read position
	move.b $ffff8909.w,d0
	swap d0
	move.b $ffff890b.w,d0
	lsl.w #8,d0
	move.b $ffff890d.w,d0
	sub.l #snd_buf,d0
	sub.w #16,d0			; (a margin)
	sub.w snd_wpos,d0
	and.w #SND_BUF-1,d0
	move.w d0,d7			; samples to write
	endc
	beq.s .done
	subq.w #1,d7
	lea snd_buf,a4
	move.w snd_wpos,d6
	movem.l voice0,a0/a2		; the voices' positions and ends
	movem.l voice1,a1/a3
	cmp.l a2,a0
	blo.s .loop
	cmp.l a3,a1
	blo.s .loop
.zero:	clr.b (a4,d6.w)			; (both silent)
	addq.w #1,d6
	and.w #SND_BUF-1,d6
	dbf d7,.zero
	bra.s .end
.loop:	moveq #0,d0
	cmp.l a2,a0
	bhs.s .n0
	move.b (a0)+,d0
	ext.w d0
.n0:	cmp.l a3,a1
	bhs.s .n1
	move.b (a1)+,d1
	ext.w d1
	add.w d1,d0
	cmp.w #127,d0
	ble.s .hi
	moveq #127,d0
.hi:	cmp.w #-128,d0
	bge.s .n1
	moveq #-128,d0
.n1:	move.b d0,(a4,d6.w)
	addq.w #1,d6
	and.w #SND_BUF-1,d6
	dbf d7,.loop
	move.l a0,voice0+V_POS
	move.l a1,voice1+V_POS
.end:	move.w d6,snd_wpos
.done:	bsr ym_frame
	movem.l (sp)+,d0-d7/a0-a4
	rts

; ym_command (from snd_frame's loop, d1.b = the command): a tune, an effect, a stop; back to the loop
ym_command:
	and.w #$FF,d1
	cmp.b #$FF,d1
	beq .stopm
	cmp.b #$FE,d1
	beq .stopf
	cmp.b #$FD,d1
	beq .stopb
	cmp.b #$F0,d1
	bhs .chan
	move.w d1,d2
	lsl.w #2,d2
	lea mu_table,a0
	move.l (a0,d2.w),d3
	beq.s .fx
	move.l d3,a0			; a tune: three stream pointers, three loop offsets
	lea ym_voices,a1
	moveq #0,d4
.t:	move.w d4,d5
	add.w d5,d5
	add.w d5,d5
	move.l (a0,d5.w),a2
	move.l a2,Y_PTR(a1)
	move.w d4,d5
	add.w d5,d5
	move.w 12(a0,d5.w),d3
	bmi.s .nl
	lea (a2,d3.w),a2
	move.l a2,Y_LOOP(a1)
	bra.s .l
.nl:	clr.l Y_LOOP(a1)
.l:	clr.b Y_LEFT(a1)
	clr.b Y_VOL(a1)
	st Y_ON(a1)
	lea Y_SIZE(a1),a1
	addq.w #1,d4
	cmp.w #3,d4
	bne.s .t
	bra snd_cmd_loop
.fx:	lea fx_table,a0
	move.l (a0,d2.w),d3
	beq snd_cmd_loop
	move.l d3,a0
	lea ym_voices+3*Y_SIZE,a1
	move.l (a0),Y_PTR(a1)
	clr.l Y_LOOP(a1)
	clr.b Y_LEFT(a1)
	clr.b Y_VOL(a1)
	st Y_ON(a1)
	bra snd_cmd_loop
.chan:	cmp.b #$F7,d1
	beq.s .stopf
	bra.s .stopm
.stopb:	bsr.s .m
.stopf:	clr.b ym_voices+3*Y_SIZE+Y_ON
	bra snd_cmd_loop
.stopm:	bsr.s .m
	bra snd_cmd_loop
.m:	clr.b ym_voices+Y_ON
	clr.b ym_voices+Y_SIZE+Y_ON
	clr.b ym_voices+2*Y_SIZE+Y_ON
	rts

; ym_frame: the four voices a frame on; the YM's registers 0-5 (periods) and 8-10 (volumes) from the music's voices,
; C from the effect while it plays; written where they changed
ym_frame:
	lea ym_voices,a1
	moveq #3,d4
.v:	bsr ym_step
	lea Y_SIZE(a1),a1
	dbf d4,.v
	lea ym_regs,a2
	moveq #0,d3			; the YM voice
.o:	move.w d3,d0
	mulu #Y_SIZE,d0
	lea ym_voices,a0
	add.w d0,a0
	cmp.w #2,d3
	bne.s .own
	tst.b ym_voices+3*Y_SIZE+Y_ON
	beq.s .own
	lea ym_voices+3*Y_SIZE,a0	; (the effect on C)
.own:	move.w d3,d1
	add.w d1,d1
	move.w Y_PER(a0),d0
	move.b d0,(a2,d1.w)
	lsr.w #8,d0
	move.b d0,1(a2,d1.w)
	moveq #0,d0
	tst.b Y_ON(a0)
	beq.s .z
	move.b Y_VOL(a0),d0
.z:	move.b d0,8(a2,d3.w)
	addq.w #1,d3
	cmp.w #3,d3
	bne.s .o
	lea ym_shadow,a0
	moveq #0,d1
.w:	cmp.w #6,d1
	beq.s .skip
	cmp.w #7,d1
	beq.s .skip
	move.b (a2,d1.w),d0
	cmp.b (a0,d1.w),d0
	beq.s .skip
	move.b d0,(a0,d1.w)
	ifnd SIM
	move.b d1,$ffff8800.w
	move.b d0,$ffff8802.w
	endc
.skip:	addq.w #1,d1
	cmp.w #11,d1
	bne.s .w
	rts

; ym_step: voice a1 by one frame (Channel.step of engine/capsnd.py).  Uses d0, a0.
ym_step:
	tst.b Y_ON(a1)
	beq.s .r
	tst.b Y_LEFT(a1)
	beq.s .read
	subq.b #1,Y_LEFT(a1)
.r:	rts
.read:	move.l Y_PTR(a1),a0
.n:	moveq #0,d0
	move.b (a0)+,d0
	cmp.b #$FF,d0
	beq.s .end
	cmp.b #$A0,d0
	bhs.s .per
	cmp.b #$90,d0
	bhs.s .down
	cmp.b #$80,d0
	bhs.s .vol
	move.b d0,Y_LEFT(a1)		; hold
	bra.s .out
.per:	and.w #15,d0
	lsl.w #8,d0
	move.b (a0)+,d0
	move.w d0,Y_PER(a1)
	bra.s .n
.down:	subq.b #1,Y_VOL(a1)
	and.b #15,d0
	move.b d0,Y_LEFT(a1)
	bra.s .out
.vol:	and.b #15,d0
	move.b d0,Y_VOL(a1)
.out:	move.l a0,Y_PTR(a1)
	rts
.end:	move.l Y_LOOP(a1),d0
	beq.s .stop
	move.l d0,a0
	bra.s .n
.stop:	clr.b Y_ON(a1)
	clr.b Y_VOL(a1)
	rts

	section data,data
	even
adpcm_index:	incbin "adpcm_index.bin"	; (per command $80-$9A: its chip (word), its stream's offset, length)
	even
adpcm_pcm:	incbin "adpcm_pcm.bin"		; (the commands' streams: a signed byte a sample, 6258 Hz)
	include "music_data.s"

	section bss,bss
	even
voice0:		ds.b V_SIZE
voice1:		ds.b V_SIZE
ym_voices:	ds.b 4*Y_SIZE		; the music's three, the effect
ym_regs:	ds.b 12
ym_shadow:	ds.b 12
snd_wpos:	ds.w 1
snd_buf:	ds.b SND_BUF
	section text,code
