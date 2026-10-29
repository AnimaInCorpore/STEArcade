; R-Type: hand-written replacements for translated V30 code (tools/gen.py NATIVES: the translated label jumps here,
; the instruction's own translation follows under <label>_t).
;
; FADE_SNAP (the STE program's default; the SIM build the lock-step test drives keeps the arcade's fade unless it is
; defined): the palette fade's inner loop (0040:5384 and 0040:5436, the same loop over a row of 16 pens x 3 channels in
; the work RAM's palette copy, DS0:[BW], toward the target bytes DS1:[IX]) sets every channel to its target at once
; instead of a step of 1 where the remaining difference reaches the fade's counter [BP+0Ah].  The fade's own bookkeeping
; runs on unchanged ([BP+2h] counts the channels changed, the counter still counts down: the game sees the fade end at
; the same frame), so only the colours between the start and the end are left out (the user's choice, 2026-10-29).
; The registers and the stack below SP are left as the loop leaves them (CW 0, BW + 32, IX + 48, AW the last channel's
; target - value, the last pushes BW + 30 and CW 1); the flags are dead after the loop (the translation does not keep
; them either).

	section text,code

    ifd FADE_SNAP
FADE_ROW macro
	movem.l	d2/d5,-(sp)
	lea	(a3,d3.l),a0		; DS0:[BW]: pen 0's red word (green +$200, blue +$400)
	moveq	#0,d2			; channels changed
	moveq	#16-1,d5
.pen\@:
	moveq	#1,d7
	eor.w	d4,d7
	moveq	#0,d0
	move.b	(a2,d7.l),d0		; red's target
	sub.w	(a0),d0
	beq.s	.g\@
	add.w	d0,(a0)
	addq.w	#1,d2
.g\@:	addq.w	#1,d4
	moveq	#1,d7
	eor.w	d4,d7
	moveq	#0,d0
	move.b	(a2,d7.l),d0
	sub.w	$200(a0),d0
	beq.s	.b\@
	add.w	d0,$200(a0)
	addq.w	#1,d2
.b\@:	addq.w	#1,d4
	moveq	#1,d7
	eor.w	d4,d7
	moveq	#0,d0
	move.b	(a2,d7.l),d0
	sub.w	$400(a0),d0
	beq.s	.n\@
	add.w	d0,$400(a0)
	addq.w	#1,d2
.n\@:	addq.w	#1,d4
	addq.l	#2,a0
	dbf	d5,.pen\@
	add.w	d2,2(a4,d6.l)		; [BP+2h]
	add.w	#32,d3
	moveq	#0,d1
	move.w	d3,d7
	subq.w	#2,d7
	move.w	d7,-2(a5)		; (the loop's last pushes)
	move.w	#1,-4(a5)
	movem.l	(sp)+,d2/d5
	jmp	\1
	endm

nat_fade_a:
	FADE_ROW	R057B4
nat_fade_b:
	FADE_ROW	R05866
    else
nat_fade_a:
	jmp	R05784_t
nat_fade_b:
	jmp	R05836_t
    endc

; ---------------------------------------------------------------------------------------------------------------------
; The sprite emitters (0040:1BCC one entry, 0040:1C1B two, 0040:1CA6 three) and the fill of the unused slots
; (0040:0653).  An object (BP: x [BP+4h], y [BP+8h], colour [BP+6h]) is drawn from a definition in ROM, DS1:[BW]: per
; entry 6 bytes (x offset, y offset: signed bytes; the code; the attribute word, its low byte replaced by the colour).
; The entries go to the sprite RAM slots from [2EFCh] (8 bytes an entry, 16 a 32-pixel-wide one; the list ends at
; $3C8: an object that does not fit leaves the pointer, its entries written so far are blanked by the fill).  The
; frame: the DMA (port $04) at the VBL copies the slots, the list starts again at $C0 (0040:023B), the objects emit,
; the fill blanks the slots from the pointer to $3C0 (attribute and x 0).
; Without SPRITE_LIST the natives write the sprite RAM as the arcade does (the lock-step test); with SPRITE_LIST
; (the stage renderers) they write m72_slots instead: per slot of an object's first entry its definition (BW), the
; entry count and the colour, x and y; the slots of its other entries 0.  As the sprite RAM, a slot keeps its record
; until it is written again or blanked: the fill clears the records from the pointer to the last list's end
; (m72_slots_hw); core.s m72_sprite_dma copies the slots from $C0 up to that end or the pointer, the further (a DMA
; while the game is still emitting - a slow frame - shows the last list's tail, as the arcade).  The registers, [2EFCh] and the stack below SP
; are left as the arcade's code leaves them either way (the flags are dead at these returns).
; ---------------------------------------------------------------------------------------------------------------------

; d7 = 8 or 16: the slot bytes of the definition entry at offset \1 (its attribute word's bit 14)
EMIT_SIZE macro
	moveq	#8,\2
	btst	#6,\1+4(a2,d3.l)	; (the word's high byte: bit 14)
	beq.s	.s\@
	moveq	#16,\2
.s\@:
	endm

; the entry at definition offset \1 into the sprite RAM slot at \2 (ix or iy); AW = its attribute with the colour
EMIT_ENTRY macro
	move.w	\1(a2,d3.l),d7		; (y offset << 8 | x offset)
    ifnd SPRITE_LIST
	lea	v30_image+$C0000,a0
	move.b	d7,d0
	ext.w	d0
	add.w	d1,d0
	move.w	d0,6(a0,\2.l)		; x
	move.w	d7,d0
	asr.w	#8,d0
	add.w	d2,d0
	move.w	d0,(a0,\2.l)		; y
	move.w	\1+2(a2,d3.l),2(a0,\2.l)	; the code
    endc
	move.w	\1+4(a2,d3.l),d0
	moveq	#6,d7
	add.w	d6,d7
	eor.w	#1,d7
	move.b	(a4,d7.l),d0		; (the colour: [BP+6h])
    ifnd SPRITE_LIST
	move.w	d0,4(a0,\2.l)
    endc
	endm

; SPRITE_LIST: the object's record at slot \1, its other slots up to the pointer \2 cleared; \3 the entry count
EMIT_RECORD macro
    ifd SPRITE_LIST
	lea	m72_slots,a0
	add.l	\1,a0
	move.w	d3,(a0)+		; the definition
	move.b	#\3,(a0)+
	move.b	d0,(a0)+		; the colour (AW's low byte)
	move.w	d1,(a0)+		; x
	move.w	d2,(a0)+		; y
	move.w	\2,d7
	sub.w	\1,d7
	subq.w	#8,d7
	beq.s	.e\@
.c\@:	clr.w	(a0)
	addq.l	#8,a0
	subq.w	#8,d7
	bne.s	.c\@
.e\@:
    endc
	endm

nat_emit1:
	move.w	$2EFC(a3),d4		; IX = IY = the pointer
	move.w	d4,d5
	EMIT_SIZE 0,d0
	add.w	d5,d0
	cmp.w	#$3C8,d0
	bcc	R0201A
	move.w	d0,$2EFC(a3)
	move.w	d0,-(sp)
	move.w	4(a4,d6.l),d1		; CW, DW: x, y
	move.w	8(a4,d6.l),d2
	move.w	6(a6),-2(a5)		; (push ds0)
	EMIT_ENTRY 0,d4
	move.w	(sp)+,d7
	EMIT_RECORD d4,d7,1
	jmp	R0201A

nat_emit2:
	move.w	$2EFC(a3),d4
	move.w	d4,d5
	EMIT_SIZE 0,d0
	add.w	d0,d5			; IY: the second entry's slot
	cmp.w	#$3C8,d5
	bcc	R0201A
	move.w	4(a4,d6.l),d1
	move.w	8(a4,d6.l),d2
	move.w	6(a6),-2(a5)
	EMIT_ENTRY 0,d4
	EMIT_SIZE 6,d0
	add.w	d5,d0
	cmp.w	#$3C8,d0
	bcc	R0201A
	move.w	d0,$2EFC(a4)		; (ss:)
	move.w	d0,-(sp)
	EMIT_ENTRY 6,d5
	move.w	(sp)+,d7
	EMIT_RECORD d4,d7,2
	jmp	R0201A

nat_emit3:
	move.w	$2EFC(a3),d4
	move.w	d4,d5
	EMIT_SIZE 0,d0
	add.w	d0,d5
	cmp.w	#$3C8,d5
	bcc	R0201A
	move.w	4(a4,d6.l),d1
	move.w	8(a4,d6.l),d2
	move.w	6(a6),-2(a5)
	move.w	d4,-(sp)		; (the first slot, for the record)
	EMIT_ENTRY 0,d4
	move.w	d5,d4			; IX = IY
	EMIT_SIZE 6,d0
	add.w	d0,d5
	cmp.w	#$3C8,d5
	bcc	.full
	EMIT_ENTRY 6,d4
	EMIT_SIZE 12,d0
	add.w	d5,d0
	cmp.w	#$3C8,d0
	bcc	.full
	move.w	d0,$2EFC(a4)
	EMIT_ENTRY 12,d5
    ifd SPRITE_LIST
	moveq	#0,d7
	move.w	(sp)+,d7
	move.l	d7,a1
	move.w	$2EFC(a4),d7
	EMIT_RECORD a1,d7,3
    else
	addq.l	#2,sp
    endc
	jmp	R0201A
.full:	addq.l	#2,sp
	jmp	R0201A

; the fill: BW = [2EFCh]; the slots from it up to $3C0 blanked; AW 0, BW the first offset >= $3C0 (or the pointer)
nat_fill:
	move.w	$2EFC(a3),d3
	move.w	6(a6),-2(a5)		; (push ds0)
	moveq	#0,d0
	cmp.w	#$3C0,d3
	bcc	R00A71
    ifd SPRITE_LIST
	move.w	m72_slots_hw,d7		; (the records from the pointer up to the last list's end cleared: the list
	sub.w	d3,d7			; ends here now)
	bls.s	.nc
	lsr.w	#3,d7
	subq.w	#1,d7
	lea	m72_slots,a0
	add.l	d3,a0
.cl:	clr.w	(a0)
	addq.l	#8,a0
	dbf	d7,.cl
.nc:	move.w	d3,m72_slots_hw
	moveq	#7,d7			; BW as the loop leaves it: the pointer + a multiple of 8, the first >= $3C0
	add.w	#$3C0,d7
	sub.w	d3,d7
	and.w	#$FFF8,d7
	add.w	d7,d3
    else
	lea	v30_image+$C0000,a0
.l:	clr.l	4(a0,d3.l)
	addq.w	#8,d3
	cmp.w	#$3C0,d3
	bcs.s	.l
    endc
	jmp	R00A71
