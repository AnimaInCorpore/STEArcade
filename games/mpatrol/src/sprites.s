; Moon Patrol's sprites on the playfield (included by render.s).
;
; The sprite RAM ($C800-$C8FF in the Z80 block): 64 entries of 4 bytes (y, attributes: colour bits 0-3 (of 0-5; the
; arcade takes it modulo the 16 colours), flip x 6, flip y 7; code; x), drawn per group of 16 from the group's last
; entry to its first, the groups in order (m52.cpp draw_sprites: later on top).  A sprite's picture line is
; 235 - y (MAME's 257 - y less the screen's 22), its screen x x + 25 (MAME's x + 129 less 136, plus the picture's 32).
; A pixel value whose pen the colour's lookup maps to colour 0 is transparent (mp_sptr: a bit per value; colours 5
; and 6 hide everything).
;
; Drawn whole into the buffers' guard lines at the top and bottom; at the picture's side edges (screen x 32 and 272,
; both on 16-pixel groups) only the inner destination word (AGENTS.md): a sprite at x 17-31 draws its second word
; (clip 1), at x 257-271 its first (clip 2), one at x 272 and beyond is culled.
;
; A sprite (code, colour, flip x) is baked on first use into the sprite cache (sc_data): its opaque rows in order, each
; with its row, its leading empty columns (lz), its mask and its four plane words shifted left by lz (aligned at the
; source word's left, as stefastbobs2 and engine/sprite_programs.py store them); the slots of its pixel values 1-3
; are kept with it and checked when it is drawn again (a slot given to another colour meanwhile: baked again).  The
; row path draws each opaque row as one HOG pass of its four planes (Y count 4, HOP 2 / OP 3, the end masks the row's
; opaque pixels: engine/sprite_programs.py's pass_of / clipped_pass: 'A' two destination words with NFSR, 'L' / 'R'
; one; source X increment 0, Y increment 2).
;
; Colours: the sprites' pens' ids get slots like the text's, for the picture: an id that only the sprites used in the
; last picture and not in this one gives its slot back (spr_release, before the text takes slots), the ids this
; picture's sprites need take free ones after the text (spr_alloc).

SC_ROW = 12				; a baked row: row.b, lz.b, mask.w, 4 plane words
SC_SIZE = 4+16*SC_ROW			; slots of values 1-3, rows; then the rows
SC_MAX = 512
SPR_RAM = Z_RAM+$C800

	section text,code

; spr_need: the shown sprites listed in the drawing order (spr_list: the entry's address, colour, transparent
; values, picture line, screen x), the ids they need flagged in cid_need (keeps all)
spr_need:
	movem.l	d0-d7/a0-a4,-(sp)
	lea	cid_need,a0
	moveq	#MP_NCID-1,d0
.cl:	clr.b	(a0)+
	dbf	d0,.cl
	lea	spr_list,a3
	moveq	#0,d7
	move.w	#$3C,d2			; the groups' last entries
.g:	move.w	d2,d1
.e:	lea	SPR_RAM,a1
	add.w	d1,a1
	movem.w	d1-d2,-(sp)
	bsr	spr_shown
	beq.s	.n
	move.l	a1,(a3)+
	movem.w	d3-d6,(a3)
	movem.w	(a3),d3-d6		; (d5 is used below: the entry keeps the line)
	addq.w	#8,a3
	addq.w	#1,d7
	move.w	d3,d0			; pens 512 + colour * 8 + value
	lsl.w	#3,d0
	lea	mp_pencid+512,a2
	add.w	d0,a2
	moveq	#0,d0			; the values its code has, but the transparent ones
	move.b	2(a1),d0
	and.w	#$7F,d0
	lea	mp_sused,a0
	move.b	(a0,d0.w),d5
	not.b	d4
	and.b	d4,d5
	not.b	d4
	lea	cid_need,a0
	moveq	#1,d0
.v:	btst	d0,d5
	beq.s	.nv
	moveq	#0,d1
	move.b	(a2,d0.w),d1
	st	(a0,d1.w)
.nv:	addq.w	#1,d0
	cmp.w	#4,d0
	blo.s	.v
.n:	movem.w	(sp)+,d1-d2
	move.w	d1,d0
	and.w	#$C0,d0
	cmp.w	d0,d1
	beq.s	.gn
	subq.w	#4,d1
	bra.s	.e
.gn:	add.w	#$40,d2
	cmp.w	#$100,d2
	blo	.g
	move.w	d7,spr_count
	movem.l	(sp)+,d0-d7/a0-a4
	rts

; spr_colours: the slots of the 16 colours' pixel values 1-3 for this picture (spr_cslots: 4 bytes a colour; $FF a
; transparent value), after the slots were given (spr_alloc)
spr_colours:
	movem.l	d3-d4/a0/a2,-(sp)
	lea	spr_cslots,a2
	lea	mp_sptr,a0
	moveq	#0,d3
.c:	move.b	(a0,d3.w),d4
	bsr	spr_slots
	addq.w	#4,a2
	addq.w	#1,d3
	cmp.w	#16,d3
	blo.s	.c
	movem.l	(sp)+,d3-d4/a0/a2
	rts

; spr_shown: the entry at a1: ne if it shows (on the picture's lines and columns, a colour that shows one of its
; code's pixel values);
; d3 = its colour (0-15), d4 = its transparent values, d5 = its picture line, d6 = its screen x.  d0-d6 changed.
spr_shown:
	moveq	#0,d5
	move.b	(a1),d5
	move.w	#235,d0
	sub.w	d5,d0
	move.w	d0,d5			; the picture line
	cmp.w	#PF_TOP-15,d5
	blt.s	.no
	cmp.w	#PF_BOT,d5
	bge.s	.no
	moveq	#0,d6
	move.b	3(a1),d6
	add.w	#25,d6			; the screen x
	cmp.w	#272,d6
	bge.s	.no
	moveq	#15,d3
	and.b	1(a1),d3
	lea	mp_sptr,a0
	move.b	(a0,d3.w),d4
	moveq	#0,d0			; any value of its code that the colour shows? (code 0 of the empty entries has none)
	move.b	2(a1),d0
	and.w	#$7F,d0
	lea	mp_sused,a0
	move.b	(a0,d0.w),d0
	not.b	d4
	and.b	d4,d0
	not.b	d4
	tst.b	d0
	beq.s	.no
	moveq	#1,d0			; (ne)
	rts
.no:	moveq	#0,d0
	rts

; spr_release: the slots of ids that no text cell uses and no sprite of this picture needs are free again (and a
; borrowed id of no text cell is forgotten)
spr_release:
	movem.l	d0-d2/a0-a3,-(sp)
	lea	cid_slot,a0
	lea	cid_ref,a1
	lea	cid_need,a2
	lea	slot_cid,a3
	moveq	#0,d0
.c:	move.b	(a0,d0.w),d1
	beq.s	.n
	move.w	d0,d2
	add.w	d2,d2
	tst.w	(a1,d2.w)
	bne.s	.n			; (text cells use it)
	tst.b	d1
	bpl.s	.own
	clr.b	(a0,d0.w)		; (borrowed: asked again by spr_alloc)
	bra.s	.n
.own:	cmp.b	#MP_NPIN,d1
	blo.s	.n			; (pinned)
	tst.b	(a2,d0.w)
	bne.s	.n			; (this picture's sprites need it)
	and.w	#15,d1
	st	(a3,d1.w)
	clr.b	(a0,d0.w)
.n:	addq.w	#1,d0
	cmp.w	#MP_NCID,d0
	blo.s	.c
	movem.l	(sp)+,d0-d2/a0-a3
	rts

; spr_alloc: the ids this picture's sprites need get slots (a free one, or the nearest colour's, borrowed)
spr_alloc:
	movem.l	d0-d6/a0-a2,-(sp)
	lea	cid_need,a2
	moveq	#1,d0			; (id 0 is slot 0's)
.c:	tst.b	(a2,d0.w)
	beq.s	.n
	lea	cid_slot,a0
	tst.b	(a0,d0.w)
	bne.s	.n
	move.w	d0,-(sp)
	bsr	cid_give		; (cid_count's slot search: text.s)
	move.w	(sp)+,d0
.n:	addq.w	#1,d0
	cmp.w	#MP_NCID,d0
	blo.s	.c
	movem.l	(sp)+,d0-d6/a0-a2
	rts

; spr_draw: the listed sprites into the drawn buffer, in the arcade's order (the row path)
spr_draw:
	movem.l	d0-d7/a0-a6,-(sp)
	move.w	#0,B_SXI.w
	move.w	#2,B_SYI.w
	move.w	#8,B_DXI.w
	move.b	#2,B_HOP.w
	move.b	#3,B_OP.w
	lea	spr_list,a5
	move.w	spr_count,d7
	bra.s	.nx
.s:	move.l	(a5)+,a1
	movem.w	(a5)+,d3-d6
	move.w	d7,-(sp)
	move.l	a5,-(sp)
	bsr	spr_one
	move.l	(sp)+,a5
	move.w	(sp)+,d7
.nx:	dbf	d7,.s
	movem.l	(sp)+,d0-d7/a0-a6
	rts

; spr_one: the sprite at a1 (spr_shown: d3 colour, d4 transparent values, d5 picture line, d6 screen x)
spr_one:
	moveq	#0,d0
	move.b	2(a1),d0		; the code (0-127)
	and.w	#$7F,d0
	moveq	#0,d1			; flip x
	btst	#6,1(a1)
	beq.s	.fx
	moveq	#1,d1
.fx:	moveq	#0,d7			; flip y in bit 15 (the row's line 15 - row), the clip in the low byte
	btst	#7,1(a1)
	beq.s	.fy
	move.w	#$8000,d7
.fy:	ifd SIM
	addq.l	#1,cnt_drawn
	endc
	bsr	spr_baked		; a0 = the baked sprite
	move.w	d6,d0			; the clip: 1 the second word only (x 17-31), 2 the first (x 257-271), 0 both
	lsr.w	#4,d0
	moveq	#15,d1
	and.w	d6,d1			; s: the shift
	beq.s	.c3			; (no shift: one word, inside)
	cmp.w	#1,d0
	bne.s	.c2
	addq.b	#1,d7
.c2:	cmp.w	#16,d0
	bne.s	.c3
	addq.b	#2,d7
.c3:	moveq	#16,d2
	sub.w	d1,d2			; 16 - s
	move.l	draw_buf,a2		; the destination of row 0: line d5, the sprite's first word
	move.w	d5,d3
	muls	#PF_LB,d3
	add.l	d3,a2
	lsl.w	#3,d0
	add.w	d0,a2
	moveq	#0,d6
	move.b	3(a0),d6		; the rows
	lea	4(a0),a0
	subq.w	#1,d6
	bmi	.out
.row:	moveq	#0,d0
	move.b	(a0),d0			; the row (flipped: 15 - row)
	tst.w	d7
	bpl.s	.r0
	neg.w	d0
	add.w	#15,d0
.r0:	mulu	#PF_LB,d0
	lea	(a2,d0.l),a3		; the row's first destination word
	moveq	#0,d0
	move.b	1(a0),d0		; lz
	add.w	d1,d0			; t = s + lz
	move.w	2(a0),d4		; the mask
	move.w	d4,d5
	lsr.w	d1,d5			; left = mask >> s
	move.w	d4,d3
	lsl.w	d2,d3			; right = mask << (16 - s) (s = 0: a shift by 16 leaves 0)
	tst.b	d7
	bne.s	.clip
	cmp.w	#16,d0
	bge.s	.typr
	tst.w	d3
	beq.s	.typl
	move.w	d5,B_END1.w		; 'A': two words, NFSR, skew t
	move.w	d3,B_END3.w
	move.w	#2,B_XC.w
	move.w	#-6,B_DYI.w
	or.w	#$40,d0
	bra.s	.go
.typl:	move.w	d5,B_END1.w		; 'L': the first word, skew t
	bra.s	.one
.typr:	sub.w	#16,d0			; 'R': the second word, skew t - 16
	move.w	d3,B_END1.w
	addq.w	#8,a3
.one:	move.w	#1,B_XC.w
	move.w	#2,B_DYI.w
.go:	lea	4(a0),a4
	move.l	a4,B_SRC.w
	move.l	a3,B_DST.w
	move.w	#4,B_YC.w
	move.b	d0,B_SKEW.w
	move.b	#$C0,$ffff8a3c.w	; (start: busy, HOG; at most 8 words: a short pass)
.nx:	lea	SC_ROW(a0),a0
	dbf	d6,.row
.out:	rts
.clip:	cmp.b	#1,d7
	bne.s	.cl2
	tst.w	d3			; clip 1: the second word only
	beq.s	.nx
	move.w	d3,B_END1.w
	addq.w	#8,a3
	cmp.w	#16,d0
	blt.s	.cf
	sub.w	#16,d0			; (the row lies in the second word)
	bra.s	.one
.cf:	or.w	#$80,d0			; (straddling: FXSR, the pre-read is the row's word)
	bra.s	.one
.cl2:	tst.w	d5			; clip 2: the first word only
	beq.s	.nx
	cmp.w	#16,d0
	bge.s	.nx
	move.w	d5,B_END1.w
	bra.s	.one

; spr_baked: code d0 / colour d3 / flip x d1 -> a0 = its baked rows (baked now if new or its slots changed).
; Keeps d1-d7/a1-a2.
spr_baked:
	movem.l	d1-d7/a1-a2,-(sp)
	move.w	d0,d5			; the key: code << 5 | colour << 1 | flip x
	lsl.w	#5,d5
	move.w	d3,d6
	add.w	d6,d6
	or.w	d6,d5
	or.w	d1,d5
	lea	spr_cslots,a2		; the colour's slots of values 1-3 this picture (spr_colours)
	move.w	d3,d6
	lsl.w	#2,d6
	add.w	d6,a2
	lea	sc_index,a1
	add.w	d5,d5
	move.w	(a1,d5.w),d6
	beq.s	.new
	subq.w	#1,d6
	mulu	#SC_SIZE,d6
	lea	sc_data,a0
	add.l	d6,a0
	move.b	(a2),d6			; still the same slots?
	cmp.b	(a0),d6
	bne.s	.bake
	move.b	1(a2),d6
	cmp.b	1(a0),d6
	bne.s	.bake
	move.b	2(a2),d6
	cmp.b	2(a0),d6
	beq.s	.out
	bra.s	.bake
.new:	move.w	sc_used,d6
	cmp.w	#SC_MAX,d6
	blo.s	.room
	movem.l	d0-d1/a1,-(sp)		; (full: emptied)
	move.w	#4096/2-1,d6
.cf:	clr.l	(a1)+
	dbf	d6,.cf
	movem.l	(sp)+,d0-d1/a1
	clr.w	sc_used
	moveq	#0,d6
.room:	addq.w	#1,sc_used
	addq.w	#1,d6
	move.w	d6,(a1,d5.w)
	subq.w	#1,d6
	mulu	#SC_SIZE,d6
	lea	sc_data,a0
	add.l	d6,a0
.bake:	bsr	spr_bake
.out:	movem.l	(sp)+,d1-d7/a1-a2
	rts

; spr_slots: colour d3, transparent values d4 -> the slots of values 1-3 at a2 (a transparent one: $FF)
spr_slots:
	movem.l	d0-d2/a0-a1,-(sp)
	move.w	d3,d0
	lsl.w	#3,d0
	lea	mp_pencid+512,a0
	add.w	d0,a0
	lea	cid_slot,a1
	moveq	#1,d0
.v:	st	-1(a2,d0.w)
	btst	d0,d4
	bne.s	.nv
	moveq	#0,d1
	move.b	(a0,d0.w),d1
	move.b	(a1,d1.w),d1
	and.b	#15,d1
	move.b	d1,-1(a2,d0.w)
.nv:	addq.w	#1,d0
	cmp.w	#4,d0
	blo.s	.v
	movem.l	(sp)+,d0-d2/a0-a1
	rts

; spr_bake: code d0, flip x d1, the slots at a2 (sc_slots) -> the entry at a0: the slots (bytes 0-2), the rows
; (byte 3), then for each opaque row: row, lz, mask, the 4 plane words << lz.  Keeps all.
spr_bake:
	ifd SIM
	addq.l	#1,cnt_bake
	endc
	movem.l	d0-d7/a0-a4,-(sp)
	move.b	(a2),(a0)
	move.b	1(a2),1(a0)
	move.b	2(a2),2(a0)
	clr.b	3(a0)
	lsl.w	#7,d0			; the pixels: (code * 2 + flip x) * 64 bytes
	lsl.w	#6,d1
	add.w	d1,d0
	lea	mp_spix,a1
	add.w	d0,a1
	lea	4(a0),a3
	lea	sb_planes,a4
	moveq	#0,d7			; the row
.row:	move.w	(a1)+,d4		; hi
	move.w	(a1)+,d5		; lo
	moveq	#0,d0			; the mask
	clr.l	(a4)
	clr.l	4(a4)
	move.w	d5,d6			; value 1: lo, not hi
	move.w	d4,d3
	not.w	d3
	and.w	d3,d6
	move.b	(a2),d3
	bsr.s	.add
	move.w	d4,d6			; value 2: hi, not lo
	move.w	d5,d3
	not.w	d3
	and.w	d3,d6
	move.b	1(a2),d3
	bsr.s	.add
	move.w	d4,d6			; value 3: both
	and.w	d5,d6
	move.b	2(a2),d3
	bsr.s	.add
	tst.w	d0
	beq.s	.nr
	move.b	d7,(a3)+		; the row, lz, the mask
	moveq	#0,d3			; lz: the leading empty columns
	move.w	d0,d6
.lz:	tst.w	d6
	bmi.s	.lzd
	add.w	d6,d6
	addq.w	#1,d3
	bra.s	.lz
.lzd:	move.b	d3,(a3)+
	move.w	d0,(a3)+
	moveq	#3,d1
.pl:	move.w	(a4)+,d6		; the plane words << lz
	lsl.w	d3,d6
	move.w	d6,(a3)+
	dbf	d1,.pl
	lea	sb_planes,a4
	addq.b	#1,3(a0)
.nr:	addq.w	#1,d7
	cmp.w	#16,d7
	blo.s	.row
	movem.l	(sp)+,d0-d7/a0-a4
	rts
.add:	cmp.b	#$FF,d3			; d6 = the pixels of the value, d3 = its slot ($FF: transparent)
	beq.s	.a4
	or.w	d6,d0
	btst	#0,d3
	beq.s	.a0
	or.w	d6,(a4)
.a0:	btst	#1,d3
	beq.s	.a1
	or.w	d6,2(a4)
.a1:	btst	#2,d3
	beq.s	.a2
	or.w	d6,4(a4)
.a2:	btst	#3,d3
	beq.s	.a4
	or.w	d6,6(a4)
.a4:	rts

	section bss,bss
	even
sc_index:	ds.w	4096		; key (code << 5 | colour << 1 | flip x) -> entry + 1
sc_used:	ds.w	1
spr_cslots:	ds.b	16*4
sb_planes:	ds.w	4
spr_count:	ds.w	1
	ifd SIM
cnt_bake:	ds.l	1		; (the tests: bakes so far)
cnt_drawn:	ds.l	1
	endc
spr_list:	ds.b	64*12
cid_need:	ds.b	MP_NCID
	even
sc_data:	ds.b	SC_MAX*SC_SIZE
	section text,code
