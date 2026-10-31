; The runtime of R-Type's translated main CPU program (included by rtype.s): the context, the schedule of one arcade
; frame (port_frame), the idle point, the dispatcher, the ports.  engine/v30x.py describes the register map and the
; image (the V30's 1 MB, the bytes of each word swapped).

; ---- the context block (V30_SEG ... V30_AX: engine/rt/v30rt.s) ----
R_D0 = 16			; the registers while the CPU is idle: d0-d6 (7 longs)
R_A2 = 44			; a2-a5 (4 longs)
R_SR = 60			; the CCR
CTXSIZE = 64
IDLE_TASK = $55E8		; [3060] while no foreground task runs (tools/machine.py)

	include	"gen_info.s"

	section text,code
; The image: v30_image is the ROM (rom_image.bin, its words as the 68000 reads them: the last thing in the data
; section, rtype.s), v30_tail the rest ($40000-$DFFFF: the first thing in the BSS, which follows the data directly; the
; sound RAM and the reset vector's ROM above $E0000 are the boot's, not mapped).  init_image checks that they meet.
init_image:
	move.l	#v30_tail,d0
	cmp.l	#v30_image+$40000,d0
	beq.s	.ok
	illegal
.ok:	bsr	nat_init
	bra	init_ip_table

; One arcade frame of the main CPU (the CPU idle at the main loop's head): the VBL interrupt (vector $20, the game's
; logic), then the raster interrupt (vector $22: the status bar's scroll), each run until the CPU is idle again.
; m72_scroll_vbl keeps the scroll the playfield is drawn with (the values before the raster interrupt).
port_frame:
	addq.l	#1,port_frames
	clr.b	es_ok			; (natives.s: nat_ecoll's summary is a frame's)
	movem.l	d0-d7/a0-a6,-(sp)
	lea	ctx_main,a6
	movem.l	R_D0(a6),d0-d6
	movem.l	R_A2(a6),a2-a5
	lea	VBL_LABEL,a0
	bsr.s	v30_irq
	move.l	m72_scroll,m72_scroll_vbl
	move.l	m72_scroll+4,m72_scroll_vbl+4
	lea	RASTER_LABEL,a0
	bsr.s	v30_irq
	movem.l	(sp)+,d0-d7/a0-a6
	rts

; a0 = an interrupt handler's label: the PSW, CS and IP of the idle point on the V30 stack, IE cleared, the handler;
; back (rts) through main_idle when the CPU is idle again
v30_irq:
	move.w	R_SR(a6),ccr
	move.l	a0,-(sp)
	jsr	v30_psw_out
	move.w	d7,-(a5)
	move.w	#IDLE_CS,-(a5)
	move.w	#IDLE_IP,-(a5)
	sf	V30_IE(a6)
	move.l	(sp)+,a0
	jmp	(a0)

; The idle point (0040:00D0, the translated label jumps here): idle when the foreground queue is empty ([2ED8] =
; [2EDA]) and no foreground task runs ([3060] = the plain RET): the state saved, back to v30_irq's caller; else the
; loop goes on (its own translation)
main_idle:
	move.w	sr,-(sp)
	move.w	v30_image+$42ED8,d7
	cmp.w	v30_image+$42EDA,d7
	bne.s	.go
	cmp.w	#IDLE_TASK,v30_image+$43060
	bne.s	.go
	move.w	(sp)+,R_SR(a6)
	movem.l	d0-d6,R_D0(a6)
	movem.l	a2-a5,R_A2(a6)
	rts
.go:	move.w	(sp)+,ccr
	jmp	IDLE_CONT

; ---- the dispatcher: d7.l = a linear address -> its label (main_disp_table: slot = address & $1FFF, linear
; probing; the table is laid out for a .w index around its middle); the CCR is kept ----
main_dispatch:
	move.w	sr,-(sp)
	move.l	d7,a1
	and.w	#$1FFF,d7
	lsl.w	#3,d7
	lea	main_disp_table+$8000,a0
.probe:	cmpa.l	(a0,d7.w),a1
	beq.s	.hit
	tst.l	(a0,d7.w)
	beq.s	.bad
	addq.w	#8,d7
	bra.s	.probe
.hit:	move.l	4(a0,d7.w),a0
	move.w	(sp)+,ccr
	jmp	(a0)
.bad:	move.l	a1,d7
	addq.l	#2,sp
	bra.s	main_badpc

; d7.w = an IP of CS $0040 (the code's main segment): its label from main_ip_table (64K longs, built at the start;
; IP i at main_ip_mid + 4 * i sign-extended: the translation indexes it with a0 = IP, `move.w`); the CCR is kept
main_dispatch_ip:
	move.w	d7,a0
	add.l	a0,a0
	add.l	a0,a0
	add.l	#main_ip_mid,a0
	move.l	(a0),a1
	jmp	(a1)
; (no entry at that IP: the linear address to main_badpc)
main_ip_bad:
	move.l	a0,d7			; (a0 = its slot: the linear address back from it)
	sub.l	#main_ip_mid,d7
	asr.l	#2,d7
	and.l	#$FFFF,d7
	add.l	#$400,d7
	bra.s	main_badpc

; main_ip_table from main_ip_entries (tools/gen.py: a count, then IP word, label long)
init_ip_table:
	lea	main_ip_table,a0
	move.l	#main_ip_bad,d0
	move.w	#$10000/4-1,d1
.fill:	move.l	d0,(a0)+
	move.l	d0,(a0)+
	move.l	d0,(a0)+
	move.l	d0,(a0)+
	dbf	d1,.fill
	lea	main_ip_entries,a1
	lea	main_ip_table,a0
	move.w	(a1)+,d1
	subq.w	#1,d1
.e:	moveq	#0,d0
	move.w	(a1)+,d0
	eor.w	#$8000,d0
	add.l	d0,d0
	add.l	d0,d0
	move.l	(a1)+,(a0,d0.l)
	dbf	d1,.e
	rts

; untranslated code reached (d7 = its linear address)
main_badpc:
main_unsupported:
	move.l	d7,badpc
	move.l	a6,badctx
    ifnd SIM
	bra	port_crash		; (rtype.s: CRASH.TXT, back to the desktop)
    endc
sim_badpc:
	bra.s	sim_badpc

; ---- I/O: the ports the translation does not fold (v30x port_in / port_out: tools/gen.py) ----
; d7.w = the port; IN: AL / AW in d0
v30_inb:
	cmp.w	#6,d7
	bcc.s	.none
	lea	in_ports,a0
	eor.w	#1,d7
	move.b	(a0,d7.w),d0
	rts
.none:	clr.b	d0
	rts
v30_inw:
	cmp.w	#6,d7
	bcc.s	.none
	lea	in_ports,a0
	move.w	(a0,d7.w),d0
	rts
.none:	moveq	#0,d0
	rts
v30_outb:
v30_outw:
	addq.l	#1,cnt_other_out
	rts

; a REP string store into the palettes / video RAMs: a0 = its first destination, a1 = past its last (either order:
; DF set runs down) -> the blocks between marked
main_mark_range:
	cmpa.l	a0,a1
	bcc.s	.up
	exg	a0,a1
	addq.l	#2,a1
.up:	suba.l	#v30_image+$C8000,a0
	suba.l	#v30_image+$C8000+1,a1	; (the last byte)
	move.l	a0,d7
	bpl.s	.lo
	moveq	#0,d7
.lo:	lsr.l	#8,d7			; the first block
	move.l	a1,-(sp)
	move.l	(sp)+,a1
	cmpa.w	#0,a1
	blt.s	.r			; (wholly below)
	exg	d7,a1
	lsr.l	#8,d7			; the last block
	cmp.l	#$17F,d7
	bls.s	.in
	move.l	#$17F,d7
.in:	exg	d7,a1
	lea	v30_vmarks,a0
.l:	cmpa.l	d7,a1
	blt.s	.r
	st	(a0,d7.l)
	addq.l	#1,d7
	bra.s	.l
.r:	rts

; port $04: the sprite DMA (the sprite RAM to the buffer the picture shows)
m72_sprite_dma:
	st	m72_dma_done
    ifd SPRITE_LIST
	movem.l	d0/a0-a1,-(sp)		; the objects' records (src/natives.s) from slot $C0 up to the list's pointer
	move.w	v30_image+$40000+$2EFC,d0	; (DS0 $4000: [2EFCh])
	cmp.w	m72_slots_hw,d0
	bcc.s	.p
	move.w	m72_slots_hw,d0		; (a slow frame: the last list's tail)
.p:	move.w	d0,m72_objs_end
	sub.w	#$C0,d0
	bls.s	.none
	lsr.w	#3,d0
	subq.w	#1,d0
	lea	m72_slots+$C0,a0
	lea	m72_objs+$C0,a1
.c:	move.l	(a0)+,(a1)+
	move.l	(a0)+,(a1)+
	dbf	d0,.c
.none:	lea	m72_slots+$3C0,a0	; (and the fixed slots above the list: the ship, the Force - natives.s nat_emit1f)
	lea	m72_objs+$3C0,a1
	moveq	#$40/4-1,d0
.f:	move.l	(a0)+,(a1)+
	dbf	d0,.f
	movem.l	(sp)+,d0/a0-a1
	rts
    endc
	movem.l	d0-d7/a0-a4,-(sp)
    ifd SPRITE_LIST
    else
	lea	v30_image+$C0000,a0
	lea	m72_spritebuf,a1
    endc
	moveq	#$400/32-1,d0
.l:	movem.l	(a0)+,d1-d7/a2
	movem.l	d1-d7/a2,(a1)
	lea	32(a1),a1
	dbf	d0,.l
	movem.l	(sp)+,d0-d7/a0-a4
	rts

; port $00: the sound latch (AL): kept in a ring for the sound side (sound_cmds, 64 bytes, sound_head the next)
m72_sound_latch:
	move.l	a0,-(sp)
	move.w	sound_head,d7
	lea	sound_cmds,a0
	move.b	d0,(a0,d7.w)
	addq.w	#1,d7
	and.w	#63,d7
	move.w	d7,sound_head
	move.l	(sp)+,a0
	rts

	include	"v30rt.s"
	include	"code_main.s"
	include	"tables_main.s"

	section data,data
	even
port_frames:	dc.l	1		; (port_frame calls)
    ifd INVULN
in_ports:	dc.w	$FFFF,$FFFF,$FDFB&~$4000	; (INVULN: DIP SW2:7, Invulnerability - for measurements)
    else
in_ports:	dc.w	$FFFF,$FFFF,$FDFB	; IN0 IN1 DSW (active low; IN1 bit 7: the sprite DMA is done)
    endc

	section bss,bss
	even
ctx_main:	ds.b	CTXSIZE
m72_scroll:	ds.w	4		; the ports $80-$86: FG y, FG x, BG y, BG x (the last written)
m72_scroll_vbl:	ds.w	4		; (the values before the raster interrupt: the playfield's)
m72_raster:	ds.w	1		; port $06: the raster interrupt's line + 128
m72_port02:	ds.w	1		; port $02: bit 3 display off, bit 2 flip
m72_dma_done:	ds.b	1		; (a sprite DMA since the last picture: video.s)
	even
v30_vmarks:	ds.b	$180		; (a byte per 256 bytes of $C8000-$DFFFF, the palettes and video RAMs: set after the
					; translated stores there, tools/gen.py store_marks; video.s copies the marked blocks)
sound_head:	ds.w	1
sound_cmds:	ds.b	64
badpc:		ds.l	1
badctx:		ds.l	1
cnt_other_out:	ds.l	1
m72_spritebuf:	ds.b	$400		; (the sprite list the picture shows)
    ifd SPRITE_LIST
m72_slots:	ds.b	$400		; (src/natives.s: per sprite RAM slot an object's record)
m72_objs:	ds.b	$400		; (their copy at the DMA, slots $C0 .. m72_objs_end: what the picture shows)
m72_objs_end:	ds.w	1
m72_slots_hw:	ds.w	1		; (the end of the list at the last fill)
    endc
main_ip_table:	ds.l	$8000		; (main_dispatch_ip: the labels of CS $0040's entry points by IP)
main_ip_mid:	ds.l	$8000
