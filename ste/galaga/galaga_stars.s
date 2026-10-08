; ------------------------------------------------------------------------------
; The 05XX starfield (MAME starfield_05xx.cpp).
;
; A 16-bit LFSR (taps 16, 13, 11, 6; period 65535) runs over a 256 x 256 field once per
; frame, plus a few steps before and after the visible part that make the field scroll
; (the x speed from the video latch bits 0-2; Galaga's y scroll pins are tied down).
; Wherever 8 bits of its state match, there is a star of one of 4 sets with a 6-bit
; colour; two sets are on at a time (latch bits 3, 4).  Latch bit 5 enables the field
; (and off resets the LFSR).
;
; The sequence is computed once at start: the position of every star in the period
; (index 0..65534) with its STE colour, in four lists by set, each sorted (black stars
; are left out).  A frame is a window of 224 * 256 steps into the period starting at
; `star_idx`: the stars of the two sets that are on and lie in it are listed (star_list:
; step within the window = raw x | raw y << 8, and the colour) and the index moves on.
; ------------------------------------------------------------------------------

LFSR_SEED = $7FFF
STAR_WINDOW = 224*256

init_stars:
	lea	star_set_n,a2
	clr.l	(a2)
	clr.l	4(a2)
	lea	ga_star_colour,a3
	move	#LFSR_SEED,d0
	moveq	#0,d1			; index
.walk:
	move	d0,d2
	and	#$FA14,d2
	cmp	#$7800,d2
	bne.s	.no_hit
	; set = bits 10, 8; colour = ~(bit 4, 1, 0, 7, 6, 5) & $3f
	move	d0,d2
	lsr	#8,d2
	and	#1,d2
	move	d0,d4
	moveq	#9,d5
	lsr	d5,d4
	and	#2,d4
	or	d4,d2			; set
	move	d0,d4
	lsr	#5,d4
	and	#7,d4
	move	d0,d5
	lsl	#3,d5
	and	#$18,d5
	or	d5,d4
	move	d0,d5
	lsl	#2,d5
	and	#$20,d5
	or	d5,d4
	not.b	d4
	and	#$3f,d4			; colour
	moveq	#0,d5
	move.b	(a3,d4.w),d5		; STE colour
	beq.s	.no_hit			; black: never visible
	add	d2,d2
	move	(a2,d2.w),d3		; the set's count (in bytes)
	move	d2,d4
	lsl	#7,d4			; set * 128 words
	lea	star_set_pos,a0
	add	d4,a0
	move	d1,(a0,d3.w)
	lea	star_set_col,a0
	add	d4,a0
	move	d5,(a0,d3.w)
	addq	#2,(a2,d2.w)
.no_hit:
	; next state: bit = b0 ^ b3 ^ b5 ^ b10 -> bit 15, shift right
	move	d0,d2
	move	d0,d4
	lsr	#3,d4
	eor	d4,d2
	move	d0,d4
	lsr	#5,d4
	eor	d4,d2
	move	d0,d4
	moveq	#10,d5
	lsr	d5,d4
	eor	d4,d2
	and	#1,d2
	lsr	#1,d0
	ror	#1,d2
	or	d2,d0
	addq	#1,d1
	cmp	#65535,d1
	blo	.walk

	; per raw y (0..223): the byte offset of the pixel in its line and its bit
	; (display x = 223 - raw y, from GAME_X in chunks of 16 pixels = 8 bytes)
	lea	star_ytab,a0
	lea	star_ybit,a1
	moveq	#0,d1
.ytab:
	move	#223,d0
	sub	d1,d0			; display x
	move	d0,d2
	lsr	#4,d2
	lsl	#3,d2
	move	d0,d3
	lsr	#3,d3
	and	#1,d3
	add	d3,d2
	add	#GAME_X,d2
	move	d2,(a0)+
	moveq	#7,d2
	and	d0,d2
	eor	#7,d2
	move	d2,(a1)+
	addq	#1,d1
	cmp	#224,d1
	blo.s	.ytab

	clr	star_idx
	clr.b	star_enable
	clr	star_n
	rts

; Walk a frame: the stars of the window -> star_list (step.w, colour.w per star), star_n.
; The video latch ($A000-$A007 cells of the shared RAM) was set by the program's IRQ
; handler; as MAME does, the frame uses the settings of the previous vertical blank
; (star_params), and the new ones are taken afterwards.

star_frame:
	clr	star_n
	tst.b	star_enable
	beq	.params
	move	star_idx,d0
	add	star_pre,d0		; the steps before the visible part
	cmp	#65535,d0
	blo.s	.s_ok
	sub	#65535,d0
.s_ok:
	move	d0,d6			; window start
	lea	star_list,a2
	moveq	#0,d5			; stars listed
	move.b	star_set_a,d0
	bsr.s	.set
	move.b	star_set_b,d0
	bsr.s	.set
	move	d5,star_n
	move	d6,d0
	add	#STAR_WINDOW&$ffff,d0	; (224 * 256 = 57344)
	bcc.s	.w1
	addq	#1,d0			; modulo 65535 after a 16-bit wrap
.w1:
	cmp	#65535,d0
	blo.s	.w2
	sub	#65535,d0
.w2:
	add	star_post,d0
	cmp	#65535,d0
	blo.s	.w3
	sub	#65535,d0
.w3:
	move	d0,star_idx
	bra	.params

	; the stars of set d0.b in the window (start d6) -> (a2)+, counted in d5
.set:
	and	#3,d0
	add	d0,d0
	lea	star_set_n,a3
	move	(a3,d0.w),d7		; bytes of entries
	beq.s	.set_done
	lsl	#7,d0
	lea	star_set_pos,a0
	add	d0,a0
	lea	star_set_col,a1
	add	d0,a1
	moveq	#0,d1
.scan:
	move	(a0,d1.w),d2
	sub	d6,d2			; step within the frame
	bcc.s	.in
	add	#65535,d2
.in:
	cmp	#STAR_WINDOW,d2
	bhs.s	.skip
	move	d2,(a2)+
	move	(a1,d1.w),(a2)+
	addq	#1,d5
.skip:
	addq	#2,d1
	cmp	d7,d1
	blo.s	.scan
.set_done:
	rts

.params:
	; the settings for the next frame from the latch
	; (the cells hold the byte the program wrote; the latch takes its bit 0)
	lea	g_ram+$2000,a0		; $A000
	moveq	#0,d0
	move.b	(a0),d0
	and	#1,d0
	move.b	1(a0),d1
	and	#1,d1
	add	d1,d1
	or.b	d1,d0
	move.b	2(a0),d1
	and	#1,d1
	lsl	#2,d1
	or.b	d1,d0			; x speed index 0..7
	move	d0,d1
	add	d1,d1
	lea	star_speed_pre,a1
	move	(a1,d1.w),star_pre
	move	#10*256,star_post
	move.b	3(a0),d0
	and.b	#1,d0
	move.b	d0,star_set_a
	move.b	4(a0),d0
	and.b	#1,d0
	or.b	#2,d0
	move.b	d0,star_set_b
	btst	#0,5(a0)
	bne.s	.enabled
	clr	star_idx		; off: the LFSR is reset
	clr.b	star_enable
	rts
.enabled:
	st	star_enable
	rts

; the steps before the visible lines (22 lines) with the x speed offset 0 1 2 3 -4 -3 -2 -1

star_speed_pre:
	dc.w	22*256+0,22*256+1,22*256+2,22*256+3,22*256-4,22*256-3,22*256-2,22*256-1

; ------------------------------------------------------------------------------
	section bss,bss
; ------------------------------------------------------------------------------

star_set_pos:	ds.w	4*128		; per set: the positions (the period has 256 hits)
star_set_col:	ds.w	4*128		; and their STE colours
star_set_n:	ds.w	4		; bytes used per set
star_ytab:	ds.w	224		; raw y -> byte offset in the line
star_ybit:	ds.w	224		; raw y -> bit
star_idx:	ds.w	1
star_pre:	ds.w	1
star_post:	ds.w	1
star_set_a:	ds.b	1
star_set_b:	ds.b	1
star_enable:	ds.b	1
	even
star_n:		ds.w	1
star_list:	ds.b	256*4
	section text,code
