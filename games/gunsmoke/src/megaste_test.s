; Optional Darklord build. No replay/autoplay/cheats; normal game input paths.
; Text/disk work is before startup or after the game's hardware is restored.
	section text,code
mt_begin:
	move.b $ffff820a.w,d0
	and.b #2,d0
	move.b d0,mt_original_hz
	lea $8.w,a0
	lea mt_vectors,a1
	moveq #9,d0
.vectors:
	move.l (a0)+,(a1)+
	dbf d0,.vectors
	move.l $5a0.w,d0
	beq .ready
	move.l d0,a0
.cookie:
	move.l (a0)+,d0
	beq .ready
	move.l (a0)+,d1
	cmp.l #'_MCH',d0
	bne .cookie
	move.l d1,mt_machine
	cmp.l #$10010,d1
	bne .ready
	st mt_mega
	move.b $ffff8e21.w,mt_original
	move.b mt_original,d0
	or.b #3,d0	; 16 MHz/cache on: no intervening 8 MHz selection
	move.b d0,$ffff8e21.w
	move.b $ffff8e21.w,mt_selected
.ready:
	bra mt_report

mt_key:
	move.w d1,d0	; IKBD macro already framed the byte and removed release bit
	lea mt_pressed,a0
	tst.b d2
	bpl .set
	lea mt_released,a0
.set:
	st (a0,d0.w)
	rts
mt_joy:
	movem.l d0/a0,-(sp)
	and.w #$ff,d0	; IKBD promises only d0.b; a later serial-byte IRQ has arbitrary upper bits
	subq.w #1,d0	; 1=port 0, 2=port 1
	lea mt_joysticks,a0
	or.b d1,(a0,d0.w)
	movem.l (sp)+,d0/a0
	rts

mt_finish:
	move.b $ffff820a.w,d0
	and.b #2,d0
	move.b d0,mt_restored_hz
	move.b #1,mt_phase
	tst.w crash_vector
	beq .normal
	move.b #2,mt_phase
.normal:
	tst.b mt_mega
	beq .vectors
	move.b $ffff8e21.w,mt_final
	move.b mt_original,$ffff8e21.w
	move.b $ffff8e21.w,mt_restored
.vectors:
	lea $8.w,a0
	lea mt_vectors,a1
	moveq #9,d0
.compare:
	move.l (a0)+,d1
	cmp.l (a1)+,d1
	beq .same
	addq.w #1,mt_vector_bad
.same:
	dbf d0,.compare
	bra mt_report

mt_report:
	lea mt_buffer,a0
	lea mt_title,a1
	bsr mt_text
	lea mt_phase_text,a1
	bsr mt_text
	moveq #0,d1
	move.b mt_phase,d1
	bsr hex_byte
	bsr mt_eol
	lea mt_machine_text,a1
	bsr mt_text
	move.l mt_machine,d1
	bsr hex_long
	bsr mt_eol
	lea mt_tos_text,a1
	bsr mt_text
	move.l $4f2.w,a1
	move.w 2(a1),d1
	bsr hex_word
	move.b #' ',(a0)+
	move.w 28(a1),d1
	bsr hex_word
	bsr mt_eol
	lea mt_load_text,a1
	bsr mt_text
	lea start(pc),a1
	move.l a1,d1
	bsr hex_long
	bsr mt_eol
	lea mt_speed_text,a1
	bsr mt_text
	lea mt_original,a1
	moveq #3,d2
.speed:
	moveq #0,d1
	move.b (a1)+,d1
	bsr hex_byte
	move.b #' ',(a0)+
	dbf d2,.speed
	bsr mt_eol
	lea mt_video_text,a1
	bsr mt_text
	move.b mt_original_hz,d1
	bsr hex_byte
	move.b #' ',(a0)+
	move.b mt_restored_hz,d1
	bsr hex_byte
	bsr mt_eol
	lea mt_pad_text,a1
	bsr mt_text
	moveq #0,d1
	move.b jp_present,d1
	bsr hex_byte
	bsr mt_eol
	lea mt_keys_text,a1
	bsr mt_text
	lea mt_pressed,a2
	bsr mt_keys
	lea mt_up_text,a1
	bsr mt_text
	lea mt_released,a2
	bsr mt_keys
	lea mt_joy_text,a1
	bsr mt_text
	moveq #0,d1
	move.b mt_joysticks,d1
	bsr hex_byte
	move.b #' ',(a0)+
	move.b mt_joysticks+1,d1
	bsr hex_byte
	bsr mt_eol
	lea mt_counts_text,a1
	bsr mt_text
	move.w frame_counter+2,d1
	bsr hex_word
	move.b #' ',(a0)+
	move.w isr_count,d1
	bsr hex_word
	move.b #' ',(a0)+
	move.w dbg_renders,d1
	bsr hex_word
	bsr mt_eol
	lea mt_vec_text,a1
	bsr mt_text
	move.w mt_vector_bad,d1
	bsr hex_word
	bsr mt_eol
	move.l a0,d7
	sub.l #mt_buffer,d7
	clr.w -(sp)
	pea mt_filename
	move.w #$3c,-(sp)
	trap #1
	addq.l #8,sp
	tst.l d0
	bmi .out
	move.w d0,d6
	pea mt_buffer
	move.l d7,-(sp)
	move.w d6,-(sp)
	move.w #$40,-(sp)
	trap #1
	lea 12(sp),sp
	move.w d6,-(sp)
	move.w #$3e,-(sp)
	trap #1
	addq.l #4,sp
.out:
	rts
mt_keys:
	moveq #0,d2
.key:
	tst.b (a2,d2.w)
	beq .next
	move.w d2,d1
	bsr hex_byte
	move.b #' ',(a0)+
.next:
	addq.w #1,d2
	cmp.w #128,d2
	blo .key
	bra mt_eol
mt_text:
	move.b (a1)+,d1
	beq .done
	move.b d1,(a0)+
	bra mt_text
.done:
	rts
mt_eol:
	move.b #13,(a0)+
	move.b #10,(a0)+
	rts
	section data,data
mt_title:
	include "mt_build.i"
mt_phase_text: dc.b 'Phase (00=start,01=normal exit,02=crash): ',0
mt_machine_text: dc.b 'Machine _MCH: ',0
mt_tos_text: dc.b 'TOS version/country configuration (hex): ',0
mt_load_text: dc.b 'Text load address: ',0
mt_speed_text: dc.b 'FF8E21 original/selected/final/restored (Mega STE only): ',0
mt_video_text: dc.b 'Original/restored video sync (00=60Hz,02=50Hz): ',0
mt_pad_text: dc.b 'Enhanced pads enabled (Mega STE must be 00): ',0
mt_keys_text: dc.b 'Key presses (hex scancodes): ',0
mt_up_text: dc.b 'Key releases (hex scancodes): ',0
mt_joy_text: dc.b 'Standard joystick port 0/1 OR masks: ',0
mt_counts_text: dc.b 'VBLs/arcade ticks/pictures (hex): ',0
mt_vec_text: dc.b 'Exception-vector restore mismatches (must be 0000 at exit): ',0
mt_filename: dc.b 'GUNTEST.TXT',0
	even
	section bss,bss
mt_machine: ds.l 1
mt_vectors: ds.l 10
mt_vector_bad: ds.w 1
mt_mega: ds.b 1
mt_phase: ds.b 1
mt_original: ds.b 1
mt_selected: ds.b 1
mt_final: ds.b 1
mt_restored: ds.b 1
mt_original_hz: ds.b 1
mt_restored_hz: ds.b 1
mt_joysticks: ds.b 2
mt_pressed: ds.b 128
mt_released: ds.b 128
mt_buffer: ds.b 2048
	section text,code
