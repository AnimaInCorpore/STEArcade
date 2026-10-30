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

; Natives with a subroutine entry too (tools/gen.py LEAF_CALLS): the CALL is a JSR with the return IP written below
; SP; the subroutine lowers SP by 2 (the arcade's stack after the CALL), runs the same body and returns with
; ADDQ #2,A5 / RTS (the RET: the flags as the body leaves them, the arcade's); a fallback into the translated original
; drops the JSR's return address (the original's RET goes through the IP table).
NEXIT	macro				; \1 1: the subroutine, \2 the RET's label
    if \1
	addq.l	#2,a5
	rts
    else
	jmp	\2
    endc
	endm
NFALL	macro				; \1 1: the subroutine, \2 the translated original
    if \1
	addq.l	#4,sp
    endc
	jmp	\2
	endm


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

EMIT1	macro
	move.w	$2EFC(a3),d4		; IX = IY = the pointer
	move.w	d4,d5
	EMIT_SIZE 0,d0
	add.w	d5,d0
	cmp.w	#$3C8,d0
	bcc	.x\@
	move.w	d0,$2EFC(a3)
	move.w	d0,-(sp)
	move.w	4(a4,d6.l),d1		; CW, DW: x, y
	move.w	8(a4,d6.l),d2
	move.w	6(a6),-2(a5)		; (push ds0)
	EMIT_ENTRY 0,d4
	move.w	(sp)+,d7
	EMIT_RECORD d4,d7,1
.x\@:	NEXIT	\1,R0201A
	endm

nat_emit1:
	EMIT1	0
leaf_emit1:
	subq.l	#2,a5
	EMIT1	1

; 0040:1BE9: the one-entry emitter entered with the slot in IX (the ship $3C0 / $3C8, the Force $3E8, $3D0, $3D8:
; the fixed slots above the list, $3C0-$3FF): no pointer, IY not touched
EMIT1F	macro
	move.w	4(a4,d6.l),d1
	move.w	8(a4,d6.l),d2
	move.w	6(a6),-2(a5)		; (push ds0)
	EMIT_ENTRY 0,d4
    ifd SPRITE_LIST
	EMIT_SIZE 0,d7
	add.w	d4,d7
	EMIT_RECORD d4,d7,1
    endc
	NEXIT	\1,R0201A
	endm
nat_emit1f:
	EMIT1F	0
leaf_emit1f:
	subq.l	#2,a5
	EMIT1F	1

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

; ---------------------------------------------------------------------------------------------------------------------
; The collision scans (0040:F560: 24 objects from DS0:176h, 0040:F548: 3 from DS0:4D6h, 32 bytes apart): for each
; object whose byte [IX+1] is set, the box test 0040:F578 against the object at BP (x [BP+4], y [BP+8], its extents
; DS1:[BW] .. [BW+6]) and its box [IX+2] .. [IX+8]; a hit returns with carry set, IX at the object.  The same steps
; as the translation, without its call / return per object and the flags it keeps across DBNZ: the registers (AW, CW,
; IX) and the flags at the return are the arcade's (a hit: the box test's last compare's, C set; none: the last
; ADD IX,20h's, C clear).
; ---------------------------------------------------------------------------------------------------------------------
COLL_SCAN macro				; \1 the first object, \2 the count, \3 the return, \4 the box test's return IP
	move.w	#\1,d4
	moveq	#\2,d1
.o\@:	tst.b	(a3,d4.l)		; [IX+1] (IX even: the byte at IX in the swapped image)
	beq.s	.n\@
	move.w	#\4,-2(a5)		; (the CALL's return IP below SP, as the arcade leaves it)
	bsr	nat_box
	bcs.s	.h\@
.n\@:	add.w	#$20,d4
	subq.w	#1,d1
	bne.s	.o\@
	move.w	d4,d7			; (the last ADD IX,20h's flags, carry clear)
	sub.w	#$20,d7
	add.w	#$20,d7
	andi	#$FE,ccr
.h\@:	jmp	\3
	endm

nat_coll24:
	COLL_SCAN $176,$18,R0F977,$F56F
nat_coll3:
	COLL_SCAN $4D6,3,R0F95F,$F557

; the box test 0040:F578: carry set when the point (x [BP+4], y [BP+8]) widened by DS1:[BW] .. [BW+6] meets the box
; [IX+2] .. [IX+8]; AW and the flags as the arcade's
nat_box:
	move.w	4(a4,d6.l),d0		; x
	cmp.w	2(a3,d4.l),d0
	bcs.s	.lft
.x2:	cmp.w	4(a3,d4.l),d0
	bcc.s	.rgt
.y:	move.w	8(a4,d6.l),d0		; y
	cmp.w	6(a3,d4.l),d0
	bcs.s	.top
	cmp.w	8(a3,d4.l),d0
	bcc.s	.bot
.hit:	ori	#1,ccr
	rts
.lft:	add.w	2(a2,d3.l),d0
	cmp.w	2(a3,d4.l),d0
	bcs.s	.miss
	bra.s	.y
.rgt:	add.w	(a2,d3.l),d0
	cmp.w	4(a3,d4.l),d0
	bcs.s	.y
	bra.s	.miss
.top:	add.w	6(a2,d3.l),d0
	cmp.w	6(a3,d4.l),d0
	bcc.s	.hit
	bra.s	.miss
.bot:	add.w	4(a2,d3.l),d0
	cmp.w	8(a3,d4.l),d0
	bcs.s	.hit
.miss:	andi	#$FE,ccr
	rts

; ---------------------------------------------------------------------------------------------------------------------
; The tile lookups under an object (BP: x [BP+4h], y [BP+8h]): 0040:1E6C the FG tile (AW = [BW] & $FFF, BW its offset
; in the FG video RAM $D0000, from the FG scroll [2EC1h]), 0040:1EB5 that and the BG tile (CW = [BW'] & $FFF, IY = BW'
; in $D8000, from the BG scroll [2EC9h] / [2ECDh]; AW, BW the FG's).  The scroll words are at odd addresses (two
; bytes).  Registers, the flags (the last AND's) and the stack below SP as the arcade leaves them.
; ---------------------------------------------------------------------------------------------------------------------
; The scroll words' terms are cached, keyed by the image longs that hold them (FG x [2EC1h]: the long at $2EC0, BG x
; [2EC9h]: $2EC8, BG y [2ECDh]: $2ECC; the initial values are those of all-zero longs).
FG_AT	macro				; -> d3 = BW (the FG tile's offset), d1 = CW (FG x & 7); d0, d7 used
	move.l	$2EC0(a3),d7
	cmp.l	tc_kf,d7
	beq.s	.c\@
	bsr	tc_fg
.c\@:	move.w	4(a4,d6.l),d3
	add.w	tc_cxf,d3
	lsr.w	#1,d3
	and.w	#$FFFC,d3
	add.w	tc_basef,d3
	and.w	#$10FF,d3
	move.w	tc_cwf,d1
	move.w	#$17F,d0
	sub.w	8(a4,d6.l),d0
	bcc.s	.y\@
	moveq	#0,d0
.y\@:	and.w	#$FFF8,d0
	lsl.w	#5,d0
	add.w	d0,d3
	and.w	#$3FFF,d3
	endm


FGTILE	macro
	FG_AT
	move.w	6(a6),-2(a5)		; (push ds0)
	lea	v30_image+$D0000,a0
	move.w	(a0,d3.l),d0
	and.w	#$FFF,d0
	NEXIT	\1,R022B4
	endm

BGTILE	macro
	FG_AT				; the FG tile (0040:1E6C)
	lea	v30_image+$D0000,a0
	move.w	(a0,d3.l),d0
	and.w	#$FFF,d0
	move.w	d3,-2(a5)		; (push bw, push aw)
	move.w	d0,-4(a5)
	move.l	$2EC8(a3),d7		; the BG's ([2EC9h], [2ECDh])
	cmp.l	tc_kbx,d7
	beq.s	.cx\@
	bsr	tc_bx
.cx\@:	move.l	$2ECC(a3),d7
	cmp.l	tc_kby,d7
	beq.s	.cy\@
	bsr	tc_by
.cy\@:	move.w	4(a4,d6.l),d5
	add.w	tc_cxb,d5
	lsr.w	#1,d5
	and.w	#$FFFC,d5
	add.w	tc_basebx,d5
	and.w	#$10FF,d5
	add.w	tc_byterm,d5
	move.w	tc_yb,d7
	sub.w	8(a4,d6.l),d7
	bcc.s	.by\@
	moveq	#0,d7
.by\@:	and.w	#$FFF8,d7
	lsl.w	#5,d7
	add.w	d7,d5			; IY
	and.w	#$3FFF,d5
	move.w	6(a6),-6(a5)		; (push ds0)
	lea	v30_image+$D8000,a0
	move.w	(a0,d5.l),d1
	and.w	#$FFF,d1		; (the flags)
	NEXIT	\1,R0231A
	endm

nat_fgtile:
	FGTILE	0
leaf_fgtile:
	subq.l	#2,a5
	FGTILE	1
nat_bgtile:
	BGTILE	0
leaf_bgtile:
	subq.l	#2,a5
	BGTILE	1

tc_word	macro				; d7 = the image long of an odd scroll word -> \1.w = the word (\2 scratch)
	moveq	#0,\1
	move.b	d7,\1
	lsl.w	#8,\1
	rol.l	#8,d7
	move.b	d7,\1
	endm
tc_fg:	move.l	d7,tc_kf		; x: CW = x & 7, the column term ((x >> 1) & $FC) + $1020
	tc_word	d0
	move.w	d0,d7
	and.w	#7,d7
	move.w	d7,tc_cwf
	sub.w	#$140,d7
	move.w	d7,tc_cxf
	lsr.w	#1,d0
	and.w	#$FC,d0
	add.w	#$1020,d0
	move.w	d0,tc_basef
	rts
tc_bx:	move.l	d7,tc_kbx
	tc_word	d1
	move.w	d1,d7
	and.w	#7,d7
	sub.w	#$140,d7
	move.w	d7,tc_cxb
	lsr.w	#1,d1
	and.w	#$FC,d1
	add.w	#$1020,d1
	move.w	d1,tc_basebx
	rts
tc_by:	move.l	d7,tc_kby		; y: the row term (y << 5) & $3F00, the line $17F + (y & 7)
	tc_word	d1
	move.w	d1,d7
	and.w	#7,d7
	add.w	#$17F,d7
	move.w	d7,tc_yb
	lsl.w	#5,d1
	and.w	#$3F00,d1
	move.w	d1,tc_byterm
	rts

	section data,data
tc_kf:	dc.l	0
tc_kbx:	dc.l	0
tc_kby:	dc.l	0
tc_cwf:	dc.w	0
tc_cxf:	dc.w	-$140
tc_basef:	dc.w	$1020
tc_cxb:	dc.w	-$140
tc_basebx:	dc.w	$1020
tc_byterm:	dc.w	0
tc_yb:	dc.w	$17F
	section text,code

; ---------------------------------------------------------------------------------------------------------------------
; STAGE: the colour animations switched off at their source (the user, 2026-10-30: no colour animation with the STE's
; 16 colours; change the game, not the renderer).  Both keep the brighter of their two targets (the ROM's colour
; tables, tools/stage_assets.py stage_pal.s):
;   0040:58B0  the power-up crystal's glow: every 32 frames sprite row [BP+6] fades to target $0A or $0B by bit 5 of
;              the frame counter - always PAL_GLOW (the brighter);
;   0040:FC0A  the cave lights: a tile row [BP+20h] fades to [BP+22h] or [BP+24h] by its own frame mask - always
;              the brighter of the two (pal_tile_bright).
; Without STAGE the arcade's code runs (the lock-step test).
; ---------------------------------------------------------------------------------------------------------------------
nat_glow:
    ifd STAGE
	move.w	#PAL_GLOW,d1		; CW: the target
	jmp	R05CBA
    else
	jmp	R05CB0_t
    endc

nat_blink:
    ifd STAGE
	move.w	$22(a4,d6.l),d1		; CW = [BP+22h], unless [BP+24h] is brighter
	move.w	$24(a4,d6.l),d7
	move.l	d0,-(sp)
	lea	pal_tile_bright,a0
	moveq	#0,d0
	move.b	d1,d0
	add.w	d0,d0
	move.w	(a0,d0.w),a1
	moveq	#0,d0
	move.b	d7,d0
	add.w	d0,d0
	cmp.w	(a0,d0.w),a1
	bcc.s	.a
	move.w	d7,d1
.a:	move.l	(sp)+,d0
	jmp	R10012
    else
	jmp	R1000A_t
    endc

    ifd STAGE
	section data,data
	include	"stage_pal.s"
	section text,code
    endc

PALROW	macro				; \1 the row's flag word, \2 CW, \3 IY, \4 IX (a set flag: cleared, the copy's pushes)
	tst.w	\1(a4)
	beq.s	.n\@
	clr.w	\1(a4)
	move.w	#\2,-6(a5)
	move.w	#\3,-8(a5)
	move.w	#\4,-10(a5)
.n\@:
	endm

; 0040:525A (STAGE): the palette rows into the arcade's palette RAM (REP MOVBKW from the work RAM's copy, for every
; row whose record's flag [BP+6] is set) - the STE's renderer takes the rows' targets from the records, nobody shows
; the arcade's palette: only the flags cleared.  The registers (AW $CC00, CW 0, IX, IY, BP at their loops' ends), the
; flags (the last ADD IY,20h) and the stack below SP (DS0, DS1, the last copied row's CW / IY / IX) as the arcade's.
nat_palcopy:
    ifd STAGE
	move.w	6(a6),-2(a5)		; (push ds0, push ds1)
	move.w	(a6),-4(a5)
k	set	0			; the sprite rows' flags, the tile rows' (unrolled)
	rept	16
	PALROW	$2D3A+$C*k,16-k,$20*k,$2134+$20*k
k	set	k+1
	endr
k	set	0
	rept	16
	PALROW	$2DFA+$C*k,16-k,$20*k,$2734+$20*k
k	set	k+1
	endr
	move.w	#$2DFA+16*$C,d6		; (the registers at the loops' ends)
	move.w	#$2734+16*$20,d4
	move.w	#16*$20,d5
	move.w	#$CC00,d0
	moveq	#0,d1
	move.w	#15*$20,d7		; (the flags of the last ADD IY,20h)
	add.w	#$20,d7
	jmp	R05700
    else
	jmp	R0565A_t
    endc

; ---------------------------------------------------------------------------------------------------------------------
; 0040:EB20 / EB53 / EB86 / EBBB: a map block into the tile video RAM (DS1:IY), 8 x 6 cells from the ROM (DS0 = $3000,
; IX = (AW & $3FFF) * 144: cells of 3 bytes, each copied as 4 bytes - the 4th is the next cell's first), rows $100
; apart; bit 15 of the map word AW flips Y (the rows from IY + $500 up, attribute bit 15 set), bit 14 flips X (the
; cells from IY + $1C left, attribute bit 14).  The arcade copies word by word (MOVBKW / LDMW + XOR + STMW); here a
; cell at an even IX is one long move (the image's swapped words are the destination's), at an odd IX four bytes.
; The video blocks' marks per row (its first and last word).  Registers as the arcade leaves them (AW = IX's start,
; flipped: the last cell's first word; CW $0800, DW, IX, IY after the rows), the stack below SP (the last row's
; pushes), then the arcade's ADD BW,2 / POP DS1 / POP DS0 / RET (R0EF45; the flags are dead).
; ---------------------------------------------------------------------------------------------------------------------
nat_tblk0:
	moveq	#0,d7
	bra.s	nat_tblk
nat_tblk8:
	move.w	#$8000,d7
	bra.s	nat_tblk
nat_tblk4:
	move.w	#$4000,d7
	bra.s	nat_tblk
nat_tblkc:
	move.w	#$C000,d7
nat_tblk:
	and.w	#$3FFF,d0
	lsl.w	#4,d0
	move.w	d0,d2			; DW
	lsl.w	#3,d0
	add.w	d2,d0			; AW = IX
	move.w	d0,d4
	movem.l	d0/d2/d3/d6,-(sp)
	moveq	#4,d2			; the cell step
	move.w	#$100,d6		; the row step
	moveq	#0,d3			; the attribute's flip bits
	tst.w	d7
	bpl.s	.ny
	add.w	#$500,d5
	neg.w	d6
	move.b	#$80,d3
.ny:	btst	#14,d7
	beq.s	.nx
	add.w	#$1C,d5
	neg.w	d2
	eor.b	#$40,d3
.nx:	moveq	#6-1,d1
.row:	move.w	d5,-4(a5)		; (push iy)
	moveq	#0,d7			; the row's video blocks: its words d5 (- $1C flipped X) .. + $1E
	move.w	d5,d7
	tst.w	d2
	bpl.s	.m
	sub.w	#$1C,d7
.m:	bsr.s	.mark
	add.w	#$1E,d7
	bsr.s	.mark
	move.w	d5,-(sp)
	swap	d1
	move.w	#8-1,d1
.cell:	btst	#0,d4
	bne.s	.odd
	lea	(a3,d4.l),a0
	lea	(a2,d5.l),a1
	move.l	(a0),(a1)
	bra.s	.x
.odd:	lea	-1(a3,d4.l),a0
	lea	(a2,d5.l),a1
	move.b	3(a0),(a1)
	move.b	(a0),1(a1)
	move.b	5(a0),2(a1)
	move.b	2(a0),3(a1)
.x:	eor.b	d3,(a1)
	addq.w	#3,d4
	add.w	d2,d5
	dbf	d1,.cell
	swap	d1
	move.w	(sp)+,d5
	add.w	d6,d5
	dbf	d1,.row
	move.w	#$0801,-2(a5)		; (push cw)
	move.l	#$0800,d1
	tst.b	d3
	movem.l	(sp)+,d0/d2/d3/d6	; (no flags)
	beq.s	.nf
	move.w	(a1),d0			; (flipped: the last LDMW's word, XORed)
.nf:	jmp	R0EF45
.mark:	move.l	a2,a0
	add.l	d7,a0
	move.l	a0,-(sp)
	sub.l	#v30_image+$C8000,(sp)
	cmp.l	#$18000,(sp)
	bcc.s	.mk
	move.l	(sp),a0
	move.l	d7,(sp)
	move.l	a0,d7
	lsr.l	#8,d7
	lea	v30_vmarks,a0
	st	(a0,d7.l)
	move.l	(sp)+,d7
	rts
.mk:	addq.l	#4,sp
	rts

; ---------------------------------------------------------------------------------------------------------------------
; The BEAM gauge's cells (FG video RAM, DS0:BW, a cell = the tile word and $008F), rewritten every frame:
;   0040:5008  AW cells $06BA (AW >= 1), on to 0040:5019 (the flags of the last DEC AW);
;   0040:503B  CW cells $06AE (CW >= 1, DBNZ), on to 0040:504B; 0040:5072 the same, on to 0040:5082 (the flags of
;              the last ADD BW,2h; CW 0).
; The video blocks marked once (the first and the last word: at most 64 bytes, two blocks).
; ---------------------------------------------------------------------------------------------------------------------
nat_mark:				; a0 = an address in the image: its 256-byte block marked (as a translated store)
	move.l	a0,d7
	sub.l	#v30_image+$C8000,d7
	cmp.l	#$18000,d7
	bcc.s	.n
	lsr.l	#8,d7
	lea	v30_vmarks,a0
	st	(a0,d7.l)
.n:	rts

nat_bar1:
	lea	(a3,d3.l),a0
	bsr	nat_mark
.l:	move.w	#$6BA,(a3,d3.l)
	addq.w	#2,d3
	move.w	#$8F,(a3,d3.l)
	addq.w	#2,d3
	subq.w	#1,d0
	bne.s	.l
	move.w	sr,-(sp)
	lea	-2(a3,d3.l),a0
	bsr	nat_mark
	move.w	(sp)+,ccr
	jmp	R05419

BAR_CW	macro				; \1 the continuation
	lea	(a3,d3.l),a0
	bsr	nat_mark
	move.w	d1,d7
	subq.w	#1,d7
	moveq	#0,d1
.l\@:	move.w	#$6AE,(a3,d3.l)
	addq.w	#2,d3
	move.w	#$8F,(a3,d3.l)
	addq.w	#2,d3
	dbf	d7,.l\@
	move.w	sr,-(sp)
	lea	-2(a3,d3.l),a0
	bsr	nat_mark
	move.w	(sp)+,ccr
	jmp	\1
	endm
nat_bar2:
	BAR_CW	R0544B
nat_bar3:
	BAR_CW	R05482

; ---------------------------------------------------------------------------------------------------------------------
; 0040:F694: an object's box (BP, its widths at DS1:IY) against the ship (56h, when its flag is clear), the Force and
; the bits (76h 136h 156h, F6h 116h), the ship's shots (B6h D6h; A8h C8h by their [+0Ch] / the other's owner), 3
; objects from 4D6h and 24 from 176h - ~19 times a frame, almost never a hit.  The tests in the arcade's order with its
; box test (nat_box: AW as the arcade's); the first hit hands over to the translated original from its start (no test
; has a side effect before it).  No hit: the arcade's end - AW the last test's, BW = IY, IX 476h, CW 0, the flags of the
; last ADD IX,20h, the return IPs below SP (the last call's at SP-2, the last box test's at SP-4) - then CLR1 CY / RET.
; ---------------------------------------------------------------------------------------------------------------------
FBOX	macro				; \1 IX: a hit -> .hit; d0 x, d1 x + [BW+2], d3 x + [BW], d2 y, d6 y + [BW+6], d7 y + [BW+4]
	move.w	#\1,a1			; (the last box tested)
	cmp.w	\1+2(a3),d0
	bcs.s	.l\@
	cmp.w	\1+4(a3),d0
	bcs.s	.y\@
	cmp.w	\1+4(a3),d3
	bcc.s	.m\@
	bra.s	.y\@
.l\@:	cmp.w	\1+2(a3),d1
	bcs.s	.m\@
.y\@:	cmp.w	\1+6(a3),d2
	bcs.s	.t\@
	cmp.w	\1+8(a3),d2
	bcs	.hit
	cmp.w	\1+8(a3),d7
	bcs	.hit
	bra.s	.m\@
.t\@:	cmp.w	\1+6(a3),d6
	bcc	.hit
.m\@:
	endm
FFLAG	macro				; \1 IX: the box test when the object's flag [IX+1] is set
	tst.b	\1(a3)
	beq.s	.n\@
	FBOX	\1
.n\@:
	endm

ECOLL	macro
	cmp.w	#$2B4,4(a4,d6.l)
	bcc	.fb			; (x >= 2B4h: the arcade's short way)
	movem.l	d2/d6,-(sp)		; (BP: 6(sp))
.again:	lea	(a2,d5.l),a1		; the widths, DS1:IY (BW = IY)
	move.l	d6,a0
	move.w	4(a4,a0.l),d0		; x
	move.w	d0,d1
	add.w	2(a1),d1
	move.w	d0,d3
	add.w	(a1),d3
	move.w	8(a4,a0.l),d2		; y
	move.w	d2,d6
	add.w	6(a1),d6
	move.w	d2,d7
	add.w	4(a1),d7
	; the broad phase (es_build once a frame): with ordered boxes and proper spans the arcade's test is the overlap of
	; the spans with the box; no overlap with any of the distinct live boxes -> no hit (the end as the arcade's)
.bs:	move.b	es_ok,d4		; (0: port_frame or a hit cleared it; 1: valid; 2: an unordered box)
	subq.b	#1,d4
	beq.s	.bk
	bpl	.full
	bsr	es_build
	bra.s	.bs
.bk:
    ifd ES_CHECK
	tst.b	es_rej
	bne	.full
    endc
	cmp.w	d0,d3			; (proper spans: x + [BW] <= x <= x + [BW+2], y + [BW+4] <= y <= y + [BW+6])
	bhi	.full
	cmp.w	d0,d1
	bcs	.full
	cmp.w	d2,d7
	bhi	.full
	cmp.w	d2,d6
	bcs	.full
	lea	es_boxes,a0		; the distinct live boxes: none overlapped -> no hit
	move.w	es_n,d4
	bra.s	.nx
.bl:	cmp.w	(a0)+,d1		; x + [BW+2] < L
	bcs.s	.m1
	cmp.w	(a0)+,d3		; x + [BW] >= R
	bcc.s	.m2
	cmp.w	(a0)+,d6		; y + [BW+6] < T
	bcs.s	.m3
	cmp.w	(a0)+,d7		; y + [BW+4] < B: overlap
	bcs	.full
	bra.s	.nx
.m1:	addq.l	#2,a0
.m2:	addq.l	#2,a0
.m3:	addq.l	#2,a0
.nx:	dbf	d4,.bl
.rej:	move.w	es_last,a1		; the box the arcade tests last (its CALL's return IP): the last active of the 24 /
	move.w	es_lastip,d7		; the 3 ...
	move.w	a1,d4
	bne.s	.rend
	move.w	$B4(a3),d0		; ... C8h / A8h by their conditions (BP: 6(sp)) ...
	move.w	$D4(a3),d1
	move.w	6(sp),d2
	tst.w	d0
	bne.s	.e1
	cmp.w	d1,d2
	beq.s	.e3			; (neither)
.e1:	tst.w	d1
	bne.s	.e2
	cmp.w	d0,d2
	beq.s	.e2
	move.w	#$C8,a1
	move.w	#$F503,d7
	bra	.rend
.e2:	tst.w	d0
	bne.s	.e3
	move.w	#$A8,a1
	move.w	#$F4EE,d7
	bra	.rend
.e3:	move.w	es_lastb,a1		; ... else D6h / B6h / 116h
	move.w	es_lastbip,d7
.rend:
    ifd ES_CHECK
	bra	.end
    endc
	movem.l	(sp)+,d2/d6
	move.w	d5,d3			; BW = IY
	move.w	a1,d4
    if \2=0
	bsr	nat_box			; (AW; d7 kept)
    endc
	bra	.r
.full:
	tst.b	$56(a3)			; 0040:F485 the ship (when its flag is clear)
	bne.s	.s2
	FBOX	$56
.s2:	FBOX	$76			; 0040:F493 / F4AA
	FBOX	$136
	FBOX	$156
	FBOX	$F6
	FBOX	$116
	FFLAG	$B6			; 0040:F4BF
	FFLAG	$D6
	tst.w	$B4(a3)			; [A8h+0Ch]
	bne.s	.c3
	move.w	$D4(a3),a0
	cmpa.w	6(sp),a0
	beq	.c5
	FBOX	$A8
.c3:	tst.w	$D4(a3)			; [C8h+0Ch]
	bne	.c5
	move.w	$B4(a3),a0
	cmpa.w	6(sp),a0
	beq	.c5
	FBOX	$C8
.c5:
k	set	0				; 0040:F548: 3 from 4D6h
	rept	3
	FFLAG	$4D6+$20*k
k	set	k+1
	endr
k	set	0				; 0040:F560: 24 from 176h
	rept	24
	FFLAG	$176+$20*k
k	set	k+1
	endr
	; no hit: AW from the last box test (nat_box again), its return IP at SP-4, the last call's at SP-2
.end:
    ifd ES_CHECK
	tst.b	es_rej
	bne.s	.chk2
	move.w	a1,es_pred		; (the rejection's prediction: now the full test)
	st	es_rej
	move.l	4(sp),d6		; (d6, d2 back: the spans again, then the full test)
	move.l	(sp),d2
	bra	.again
.chk2:	move.w	es_pred,d7
	cmp.w	a1,d7
	beq.s	.chk3
	addq.b	#1,$1FF2(a3)		; (a wrong last box: 41FF3)
.chk3:	clr.b	es_rej
    endc
	movem.l	(sp)+,d2/d6
	move.w	d5,d3			; BW = IY
	move.w	a1,d4
    if \2=0
	bsr	nat_box
    endc
	move.w	#$F56F,d7
	cmp.w	#$4D6,d4
	bcs.s	.r1
	move.w	#$F557,d7
	bra.s	.r
.r1:	cmp.w	#$176,d4
	bcc.s	.r
	lea	ecoll_ips,a0
.rl:	move.l	(a0)+,d7
	cmp.w	d7,d4
	bne.s	.rl
	swap	d7
.r:	move.w	d7,-4(a5)
	move.w	#$F6D4,-2(a5)
	move.w	#$476,d4
	moveq	#0,d1
	move.w	#$456,d7		; (the last ADD IX,20h's flags: the carry clear - the CLR1 CY)
	add.w	#$20,d7
	NEXIT	\1,R0FAD9
.hit:
    ifd ES_CHECK
	tst.b	es_rej
	beq.s	.hok
	addq.b	#1,$1FF0(a3)		; (a rejected enemy hits: the lock-step shows work RAM 41FF1)
.hok:
    endc
	movem.l	(sp)+,d2/d6
	clr.b	es_ok			; (a hit: the game changes the player's side - the summary again)
.fb:	NFALL	\1,R0FA94_t
	endm
nat_ecoll:
	ECOLL	0,0
leaf_ecoll:
	subq.l	#2,a5
	ECOLL	1,0
leaf_ecoll_naw:				; (for a CALL after which AW is dead: no AW from the last box test)
	subq.l	#2,a5
	ECOLL	1,1
ecoll_ips:	dc.w	$F499,$76,$F4A1,$136,$F4A9,$156,$F4B0,$F6,$F4B8,$116,$F4CB,$B6,$F4D9,$D6,$F4EE,$A8,$F503,$C8

; ---------------------------------------------------------------------------------------------------------------------
; 0040:0672 / 0689: an object's x / y (24 bits: [BP+3] .. [BP+5] / [BP+7] .. [BP+9]) plus the speed AW (signed): the
; arcade adds the odd word and carries / borrows into the high byte.  One 24-bit add here (BP even: the high and
; middle bytes are the image word at BP+4 / BP+8, the low byte at BP+2 / BP+6); the flags are dead after the RETs
; (every return point defines them first), AW unchanged.
; ---------------------------------------------------------------------------------------------------------------------
POS24	macro				; \1 the image offset of the word (BP+4 / BP+8), \2 the RET
	btst	#0,d6
	bne.s	.o\@
	lea	(a4,d6.l),a0
	move.w	\1(a0),d7
	lsl.l	#8,d7
	move.b	\1-2(a0),d7
	move.w	d0,a1
	add.l	a1,d7
	move.b	d7,\1-2(a0)
	lsr.l	#8,d7
	move.w	d7,\1(a0)
	jmp	\2
.o\@:	jmp	\3
	endm
nat_posx:
	POS24	4,R00A7F,R00A72_t
nat_posy:
	POS24	8,R00A96,R00A89_t

; (the same as subroutines for the CALLs (tools/gen.py LEAF_CALLS): the return IP below SP written by the caller)
LEAF24	macro				; \1 3 (x) / 7 (y): the 24 bits at [BP+\1] .. [BP+\1+2] plus AW
	lea	(a4,d6.l),a0
	btst	#0,d6
	bne.s	.o\@
	move.w	\1+1(a0),d7		; (BP even: the high bytes' word, the low byte)
	lsl.l	#8,d7
	move.b	\1-1(a0),d7
	move.w	d0,a1
	add.l	a1,d7
	move.b	d7,\1-1(a0)
	lsr.l	#8,d7
	move.w	d7,\1+1(a0)
	rts
.o\@:	moveq	#0,d7			; (BP odd: three bytes)
	move.b	\1+3(a0),d7
	lsl.w	#8,d7
	move.b	\1(a0),d7
	lsl.l	#8,d7
	move.b	\1+1(a0),d7
	move.w	d0,a1
	add.l	a1,d7
	move.b	d7,\1+1(a0)
	lsr.l	#8,d7
	move.b	d7,\1(a0)
	lsr.w	#8,d7
	move.b	d7,\1+3(a0)
	rts
	endm
leaf_posx:
	LEAF24	3
leaf_posy:
	LEAF24	7

; es_build: the player side's summary for nat_ecoll's broad phase, once a frame (port_frames; again after a hit):
; the distinct live boxes (R and B not 0: those never meet a proper span) of every box the arcade may test (the ship's when its flag is clear, the Force's and the bits',
; A8h / C8h, B6h / D6h, 4D6h.. and 176h.. when their flags are set), es_ok 2 when a box is not ordered (L > R or
; T > B: the broad phase off), the box tested last when nothing hits (es_last: of the 24 or the 3, else 0;
; es_lastb: D6h / B6h / 116h).  The calls of a frame come from the enemy loop, after the player's objects moved.
ESB	macro				; \1 IX: its box into the list
	move.w	#\1,d4
	bsr	.box
	endm
ESF	macro				; \1 IX: its box when its flag [IX+1] is set (es_last, its CALL's return IP \2)
	tst.b	\1(a3)
	beq.s	.n\@
	move.w	#\1,es_last
	move.w	#\2,es_lastip
	ESB	\1
.n\@:
	endm
es_build:
	movem.l	d0-d4/a0-a1,-(sp)
	move.b	#1,es_ok
	clr.w	es_n
	clr.w	es_last
	ESB	$76			; the Force, the bits, A8h / C8h (their tests' conditions: at the call)
	ESB	$136
	ESB	$156
	ESB	$F6
	ESB	$116
	ESB	$A8
	ESB	$C8
	tst.b	$56(a3)			; the ship: tested when its flag is clear
	bne.s	.s
	ESB	$56
.s:	move.w	#$116,es_lastb
	move.w	#$F4B8,es_lastbip
	tst.b	$B6(a3)
	beq.s	.b6
	move.w	#$B6,es_lastb
	move.w	#$F4CB,es_lastbip
	ESB	$B6
.b6:	tst.b	$D6(a3)
	beq.s	.d6
	move.w	#$D6,es_lastb
	move.w	#$F4D9,es_lastbip
	ESB	$D6
.d6:
k	set	0				; the 3, the 24
	rept	3
	ESF	$4D6+$20*k,$F557
k	set	k+1
	endr
k	set	0
	rept	24
	ESF	$176+$20*k,$F56F
k	set	k+1
	endr
	tst.w	es_last			; (no slot: with [B4h] and [D4h] 0 the arcade tests C8h last - BP is never 0)
	bne.s	.x
	move.w	$B4(a3),d0
	or.w	$D4(a3),d0
	bne.s	.x
	move.w	#$C8,es_last
	move.w	#$F503,es_lastip
.x:	movem.l	(sp)+,d0-d4/a0-a1
	rts
.box:	movem.l	2(a3,d4.w),d0-d1	; the box at IX d4 into the list (not when dead: R or B 0; once):
	tst.w	d0			; d0 L:R, d1 T:B
	beq.s	.bx
	tst.w	d1
	beq.s	.bx
	move.l	d0,d2			; (L > R or T > B: the overlap is not the arcade's test)
	swap	d2
	cmp.w	d0,d2
	bls.s	.o1
	move.b	#2,es_ok
.o1:	move.l	d1,d2
	swap	d2
	cmp.w	d1,d2
	bls.s	.o2
	move.b	#2,es_ok
.o2:	lea	es_boxes,a1
	move.w	es_n,d2
	bra.s	.q
.ql:	cmp.l	(a1)+,d0
	bne.s	.qn
	cmp.l	(a1),d1
	beq.s	.bx			; (the same box)
.qn:	addq.l	#4,a1
.q:	dbf	d2,.ql
	move.l	d0,(a1)+
	move.l	d1,(a1)
	addq.w	#1,es_n
.bx:	rts

	section bss,bss
es_ok:		ds.b	1
	even
es_n:		ds.w	1
es_boxes:	ds.w	4*40
es_last:	ds.w	1
es_lastb:	ds.w	1
es_lastip:	ds.w	1
es_lastbip:	ds.w	1
es_full:	ds.b	1
es_rej:		ds.b	1
	even
es_pred:	ds.w	1
	even
	section text,code

; ---------------------------------------------------------------------------------------------------------------------
; 0040:89B0: the cave crawler's handler (stage 1: ~10 a frame, a third of the play logic with what it calls) up to its
; sprite (0040:8A8F, translated on: the emitter, the collision test, the screen test).  Its timer (0040:F63A, the
; common way: neither limit reached - else the arcade's CALL), its direction toward the ship (every [BP+30h]-th frame,
; up to 400h: [BP+2Eh]), four terrain probes 18h away (FG tiles from DFCh: a step back at speed C0h; 0040:1E6C inline,
; the scroll terms once), the X / Y moves (leaf_posx / leaf_posy), its sprite (IX, BW).  BP even (else the
; translation).  Registers, the flags at 8A8F and the stack below SP (the pushes, the CALLs' return IPs, the tile
; lookup's push of DS0) as the arcade leaves them.
; ---------------------------------------------------------------------------------------------------------------------
FGXY	macro				; d4 x, d7 y -> d3 = BW (the FG tile's offset), d1 = CW, d0 = AW = the tile & FFFh
	move.w	d4,d3
	add.w	tc_cxf,d3
	lsr.w	#1,d3
	and.w	#$FFFC,d3
	add.w	tc_basef,d3
	and.w	#$10FF,d3
	move.w	#$17F,d0
	sub.w	d7,d0
	bcc.s	.y\@
	moveq	#0,d0
.y\@:	and.w	#$FFF8,d0
	lsl.w	#5,d0
	add.w	d0,d3
	and.w	#$3FFF,d3
	move.w	tc_cwf,d1
	lea	v30_image+$D0000,a1
	move.w	(a1,d3.l),d0
	and.w	#$FFF,d0
	endm
PROBE	macro				; \1 the direction bit, \2 4 (x) / 8 (y), \3 the offset, \4 the lookup's return IP,
	btst	#\1,$2F(a0)		; \5 the speed, \6 the move, \7 its return IP
	beq	.n\@
	move.w	\2(a0),-2(a5)		; (push [BP+\2])
	move.w	4(a0),d4
	move.w	8(a0),d7
    if \2=4
	add.w	#\3,d4
    else
	add.w	#\3,d7
    endc
	move.w	#\4,-4(a5)		; (CALL 226Ch)
	move.w	6(a6),-6(a5)		; (its PUSH DS0)
	FGXY
	cmp.w	#$DFC,d0
	bcs.s	.n\@
	subq.b	#1,$1F(a0)		; [BP+1Eh]
	move.w	#\5,d0			; AW: the speed
	move.w	#\7,-2(a5)		; (the CALL of 0040:0672 / 0689: \6 inline, BP even)
	move.w	\2(a0),d7		; the 24 bits at [BP+\2-1] .. [BP+\2+1] plus the speed
	lsl.l	#8,d7
	move.b	\2-2(a0),d7
	add.l	#\5-((\5&$8000)<<1),d7
	move.b	d7,\2-2(a0)
	lsr.l	#8,d7
	move.w	d7,\2(a0)
.n\@:
	endm

nat_h89b0:
	btst	#0,d6
	bne	.tr
	lea	(a4,d6.l),a0		; the object (BP even: a word [BP+k] at k(a0), a byte at (k ^ 1)(a0))
	move.w	$26(a0),d7		; 0040:F63A: the timer (AW): at [BP+2Ah] or from [BP+2Ch] on (then 0 again) its
	addq.w	#1,d7			; spawn when [BP+28h] is set (that: the arcade's routine)
	move.w	d7,d0
	cmp.w	$2A(a0),d7
	beq.s	.t1
	cmp.w	$2C(a0),d7
	bcs.s	.t2
	tst.w	$28(a0)
	bne	.fa
	moveq	#0,d7			; (reset)
	bra.s	.t2
.t1:	tst.w	$28(a0)
	bne	.fa
.t2:	move.w	d7,$26(a0)
	move.w	#$89B3,-2(a5)		; (its CALL)
	addq.w	#1,$20(a0)		; 0040:89B3
	move.w	$30(a0),d0
	move.w	$20(a0),d7
	and.w	d0,d7
	bne.s	.e
	cmp.w	#$400,$20(a0)
	bcc.s	.e
	moveq	#1,d7			; BL: the direction toward the ship ([28h] y, [24h] x)
	move.w	8(a0),d0
	cmp.w	$28(a3),d0
	bcs.s	.d1
	moveq	#2,d7
.d1:	move.w	4(a0),d0
	cmp.w	$24(a3),d0
	bcs.s	.d2
	or.b	#4,d7
	bra.s	.d3
.d2:	or.b	#8,d7
.d3:	move.b	d7,d3			; (BW's low byte)
	move.b	d7,$2F(a0)		; [BP+2Eh]
.e:	move.b	#2,$1F(a0)		; [BP+1Eh]
	move.l	$2EC0(a3),d7		; (the FG scroll's terms)
	cmp.l	tc_kf,d7
	beq.s	.c
	bsr	tc_fg
.c:	PROBE	0,8,$18,$89FB,$C0,leaf_posy,$8A0C
	PROBE	1,8,-$18,$8A1C,$FF40,leaf_posy,$8A2D
	PROBE	2,4,-$18,$8A3D,$FF40,leaf_posx,$8A4E
	PROBE	3,4,$18,$8A5E,$C0,leaf_posx,$8A6F
	move.w	#$3C2A,d4		; 0040:8A6F: the sprite
	btst	#3,$2F(a0)
	bne.s	.f1
	move.w	#$3C22,d4
.f1:	move.w	$2ED0(a3),d0
	add.w	d0,4(a0)
	moveq	#0,d7
	move.w	$2EB6(a3),d3
	and.w	#$30,d3
	lsr.w	#3,d3			; (the flags of SHR BW,3)
	move.w	d3,d7
	add.w	d4,d7
	lea	(a2,d7.l),a1
	move.w	(a1),d3
	move.w	#$8A92,-2(a5)		; 0040:8A8F CALL 1FCCh: the sprite
	jsr	leaf_emit1
	move.w	#$3C56,d5		; IY
	move.w	#$8A98,-2(a5)		; CALL 0FA94h: the collision test (AW is dead after it: 0040:1D6B sets it)
	jsr	leaf_ecoll_naw
	bcc.s	.h1
	jmp	R08E9A			; (a hit)
.h1:	move.w	#$8AA0,-2(a5)		; CALL 216Bh: on the screen (carry: off)
	move.w	4(a4,d6.l),d0
	sub.w	#$12C,d0
	bcs.s	.sc
	sub.w	#$1A8,d0
	bcc.s	.sc
	move.w	8(a4,d6.l),d0
	sub.w	#$7C,d0
	bcs.s	.sc
	sub.w	#$118,d0
	bcc.s	.sc
	tst.b	$2FC5(a3)		; 0040:8AA5 [2FC4h]
	beq.s	.t6
	jmp	R08EAC
.sc:	ori	#1,ccr
	jmp	R08EA2
.t6:	cmp.b	#2,$1F(a4,d6.l)		; [BP+1Eh] (BP even)
	bne.s	.rt
	jmp	R08EB5
.rt:	jmp	R08EB8
.fa:	move.w	#$89B3,-(a5)		; (a limit: the arcade's timer routine)
	jmp	R0FA3A
.tr:	jmp	R08DB0_t

; ---------------------------------------------------------------------------------------------------------------------
; 0040:5301 / 5330: the palette rows' fades, 16 sprite rows (records 2D34h + 0Ch k, BW 2134h + 20h k) and 16 tile rows
; (2DF4h.., 2734h..): a row whose word [BP] has bit 15 set fades (the arcade's code from 0040:5312 / 5341 with BP,
; BW, CW, AW and the TEST's flags as its loop has them there); the others only cost the loop - here an unrolled scan.
; At the end BP, BW, CW 0, AW (the last row's word) and the flags of the last ADD BW,20h as the arcade's.
; ---------------------------------------------------------------------------------------------------------------------
PROWK	macro				; \1 the record, \2 BW, \3 CW, \4 the arcade's code for an active row
	move.w	\1(a4),d0
	bpl.s	.n\@
	move.w	#\1,d6
	move.w	#\2,d3
	move.w	#\3,d1
	move.w	d0,d7			; (TEST AW,8000h: not zero)
	and.w	#$8000,d7
	jmp	\4
.n\@:
	endm
PROW	macro				; \1 the records, \2 BW's start, \3 the arcade's code for an active row, \4 the end
k	set	0
	rept	16
	PROWK	\1+$C*k,\2+$20*k,16-k,\3
k	set	k+1
	endr
	move.w	#\1+16*$C,d6
	move.w	#\2+16*$20,d3
	moveq	#0,d1
	move.w	#\2+15*$20,d7		; (the flags of the last ADD BW,20h)
	add.w	#$20,d7
	jmp	\4
	endm
nat_prow1:
	PROW	$2D34,$2134,R05712,R05730
nat_prow2:
	PROW	$2DF4,$2734,R05741,R0575F

; ---------------------------------------------------------------------------------------------------------------------
; 0040:E601: an enemy bullet's handler (~3 a frame): its move by [BP+30h] / [BP+32h], its sprite (every frame while
; [BP+0] = E603h or [BP+20h] runs out, else [BP+20h] counts down), the ship's box (0040:F885) and the Force's (76h)
; against it (BW 84C6h: its widths), every other frame the BG / FG tiles under it and the screen (0040:1D6B).  BP even
; (else the translation); a hit or a wall continues in the arcade's code with its flags.  The registers and the stack
; below SP (the CALLs' return IPs) as the arcade leaves them.
; ---------------------------------------------------------------------------------------------------------------------
POSADD	macro				; \1 the word offset (4 x / 8 y): the 24 bits at [BP+\1-1] .. [BP+\1+1] plus AW
	move.w	\1(a0),d7
	lsl.l	#8,d7
	move.b	\1-2(a0),d7
	move.w	d0,a1
	add.l	a1,d7
	move.b	d7,\1-2(a0)
	lsr.l	#8,d7
	move.w	d7,\1(a0)
	endm
nat_he601:
	btst	#0,d6
	bne	.tr
	lea	(a4,d6.l),a0
	move.w	$30(a0),d0		; CALL 0A72h: x
	move.w	#$E609,-2(a5)
	POSADD	4
	move.w	$32(a0),d0		; CALL 0A89h: y
	move.w	#$E60F,-2(a5)
	POSADD	8
	cmp.w	#$E603,(a0)
	beq.s	.em
	tst.w	$20(a0)
	beq.s	.em
	subq.w	#1,$20(a0)
	bra.s	.sh
.em:	move.w	d6,d3			; the sprite: 84AEh + 3 * ((((BP >> 3) + [2EB6h]) & 18h) >> 2)
	lsr.w	#3,d3
	add.w	$2EB6(a3),d3
	and.w	#$18,d3
	lsr.w	#1,d3
	move.w	d3,d1			; CW
	lsr.w	#1,d3
	add.w	d1,d3
	add.w	#$84AE,d3
	move.w	#$E642,-2(a5)
	jsr	leaf_emit1
.sh:	move.w	#$84C6,d3		; 0040:E642: the ship (0040:F885: its box when its flag is clear)
	move.w	#$56,d4
	move.w	#$E648,-2(a5)
	tst.b	$56(a3)
	bne.s	.f
	bsr	nat_box
	bcc.s	.f
	jmp	R0EA4A			; (the ship hit)
.f:	move.w	#$76,d4			; 0040:E64E: the Force
	move.w	#$E657,-2(a5)
	bsr	nat_box
	bcc.s	.t
	jmp	R0EA86
.t:	move.w	$2EB6(a3),d7		; every other frame the tiles
	and.w	#1,d7
	beq.s	.ti
	jmp	R0EA7B			; (RET)
.ti:	move.w	#$E664,-2(a5)		; CALL 22B5h
	jsr	leaf_bgtile
	cmp.w	#$DFC,d0
	bcs.s	.w
	cmp.w	#$7D0,d1
	bcs.s	.w
	tst.b	$2FC5(a3)		; [2FC4h]
	bne.s	.o
	move.w	#$E679,-2(a5)		; CALL 216Bh: on the screen (carry: off)
	move.w	4(a4,d6.l),d0
	sub.w	#$12C,d0
	bcs.s	.so
	sub.w	#$1A8,d0
	bcc.s	.so
	move.w	8(a4,d6.l),d0
	sub.w	#$7C,d0
	bcs.s	.so
	sub.w	#$118,d0
	bcc.s	.so
	andi	#$FE,ccr
	jmp	R0EA7B			; (RET)
.so:	ori	#1,ccr
.o:	jmp	R0EA7C
.w:	jmp	R0EA86
.tr:	jmp	R0EA01_t

; 0040:F6DA: the larger enemies' collision tests (their hits clear the player's shots' flags outside nat_ecoll): the
; broad phase's summary built again after it.
nat_eco2:
	clr.b	es_ok
	jmp	R0FADA_t

; ---------------------------------------------------------------------------------------------------------------------
; 0040:86EA: a handler of ~8 enemies a frame in stage 1 (its timer, the x scroll, its sprite [BP+22h], the collision
; test with IY 3AF6h, the screen's left edge 140h, [2FC4h]).  The timer as in nat_h89b0 (a spawn: the arcade's
; routine); the animation step every 16th frame (0040:86FB), a hit, the left edge and [2FC4h] continue in the
; translation with the arcade's flags.  BP even (else the translation).
; ---------------------------------------------------------------------------------------------------------------------
nat_h86ea:
	btst	#0,d6
	bne	.tr
	lea	(a4,d6.l),a0
	move.w	$26(a0),d7		; 0040:F63A: the timer (AW)
	addq.w	#1,d7
	move.w	d7,d0
	cmp.w	$2A(a0),d7
	beq.s	.t1
	cmp.w	$2C(a0),d7
	bcs.s	.t2
	tst.w	$28(a0)
	bne	.fa
	moveq	#0,d7
	bra.s	.t2
.t1:	tst.w	$28(a0)
	bne	.fa
.t2:	move.w	d7,$26(a0)
	move.w	#$86ED,-2(a5)		; (its CALL)
	move.w	$2ED0(a3),d0		; 0040:86ED: x + the scroll
	add.w	d0,4(a0)
	move.w	$2EB6(a3),d7		; every 16th frame the animation step
	and.w	#$F,d7
	bne.s	.sp
	jmp	R08AFB
.sp:	move.w	$22(a0),d3		; 0040:870D: the sprite
	move.w	#$8713,-2(a5)
	jsr	leaf_emit1
	move.w	#$3AF6,d5		; IY
	move.w	#$8719,-2(a5)		; the collision test
	jsr	leaf_ecoll
	bcc.s	.h
	jmp	R08B1B			; (a hit)
.h:	cmp.w	#$140,4(a4,d6.l)	; [BP+4] - 140h
	bcc.s	.k
	jmp	R08B25			; (past the left edge)
.k:	tst.b	$2FC5(a3)		; [2FC4h]
	beq.s	.r
	jmp	R08B2F
.r:	jmp	R08B32			; (RET)
.fa:	move.w	#$86ED,-(a5)		; (a spawn: the arcade's timer routine)
	jmp	R0FA3A
.tr:	jmp	R08AEA_t
