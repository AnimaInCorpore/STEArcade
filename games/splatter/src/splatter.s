; Splatterhouse (Namco System 1) for the Atari STE.
;
; The translated main and sub CPU programs and their runtime: core.s (tools/gen.py, engine/m6809x.py).  The port
; starts from the reference's state after the boot (tools/snapshot.py: build/splatter/snapshot.bin).
;
; SIM: the build the tests drive (tools/logic_test.py): the harness does the vertical blank's work, the MCU and the
; sound CPU in the reference and calls port_frame once a frame.
; Otherwise the program: the snapshot loaded, then per arcade frame (one per VBL at most: the arcade's 60 Hz on the
; STE's 50 when the logic keeps up) the vertical blank's work (the sprite list latch, the MCU), the main CPU, the sub
; CPU.  The picture (render.s) is not there yet; the background colour beats with the game's frame counter.

KEY_ESC = $01
    ifnd SIM
	include	"ikbd.s"
    endc

	section text,code
start:
	clr.l	-(sp)
	move	#$20,-(sp)
	trap	#1
	addq	#6,sp
	move.l	d0,old_ssp
	lea	own_stack_top,sp
	lea	bad_table,a0
	move.w	#$2000-1,d0
.bad:	move.l	#cpu_badpc,(a0)+
	dbf	d0,.bad
	bsr	init_page_bases
	bsr	init_contexts
    ifd SIM
sim_wait:
	bra.s	sim_wait
    else
	bsr	snapshot_load
	bsr	init_hardware
main_loop:
.wait:	tst.w	ticks
	beq.s	.wait
	clr.w	ticks
	bsr	vblank_work
	bsr	port_frame
	move.w	vio+$20030,d0		; (the game's frame counter, RAM $0030: a heartbeat in the background colour)
	and.w	#$0777,d0
	move.w	d0,$ffff8240.w
	tst.b	quit_flag
	beq.s	main_loop
	bsr	restore_hardware
	move.l	old_ssp,-(sp)
	move	#$20,-(sp)
	trap	#1
	addq	#6,sp
	clr	-(sp)
	trap	#1

; the vertical blank: the sprite list latched when the program wrote $7F2 (namcos1_sprite copy_sprites), the MCU
vblank_work:
	tst.b	sprite_latch
	beq.s	.mcu
	sf	sprite_latch
	lea	vio+$1C800,a0
	move.w	#128-1,d0
.copy:	move.l	4(a0),10(a0)
	move.w	8(a0),14(a0)
	lea	16(a0),a0
	dbf	d0,.copy
.mcu:	bra	mcu_frame

; The MCU until its native replacement: what main reads of it (TRIRAM, its frame copies one frame late): $026 / $027
; the controls (active high), $028 / $029 the DIP switches (all off: 0), $02A the coin and service bits; $039 cleared.
mcu_frame:
	lea	vio+$1F000,a0
	move.b	mcu_last,$26(a0)
	move.b	mcu_last+1,$27(a0)
	clr.b	$28(a0)
	clr.b	$29(a0)
	move.b	mcu_last+2,$2A(a0)
	clr.b	$39(a0)
	move.b	in_control0,d0
	not.b	d0
	move.b	d0,mcu_last
	move.b	in_control1,d0
	not.b	d0
	move.b	d0,mcu_last+1
	move.b	in_coin,d0
	not.b	d0
	and.b	#$78,d0
	move.b	d0,mcu_last+2
	rts

; ---- the snapshot (tools/snapshot.py) ----
snapshot_load:
	lea	snapshot,a0
	lea	vio,a1
	move.w	#$28000/4-1,d0
.vio:	move.l	(a0)+,(a1)+
	dbf	d0,.vio
	lea	ctx_main,a6
	bsr.s	load_ctx
	lea	ctx_sub,a6
	bsr.s	load_ctx
	lea	key_regs,a1
	moveq	#8-1,d0
.key:	move.b	(a0)+,(a1)+
	dbf	d0,.key
	move.l	(a0)+,rand_seed
	rts

; a0 -> 8 page words, A B X Y U S CC (words); a6 = the context
load_ctx:
	moveq	#0,d6
	sub.l	a5,a5
.slot:	move.w	(a0)+,d7
	move.l	a0,-(sp)
	move.w	d6,-(sp)
	bsr	bank_set		; (PB, VB, TBL, PID)
	move.w	(sp)+,d6
	move.l	(sp)+,a0
	addq.w	#2,d6
	cmp.w	#16,d6
	bne.s	.slot
	moveq	#0,d0
	lea	R_D0(a6),a1
	moveq	#5-1,d1
.regs:	move.w	(a0)+,d0
	move.l	d0,(a1)+
	dbf	d1,.regs
	move.w	(a0)+,d0		; S
	add.l	PB(a6),d0
	move.l	d0,R_A5(a6)
	move.w	(a0)+,d0		; CC
	move.b	d0,CCHI(a6)
	and.w	#$0F,d0
	move.w	d0,R_SR(a6)
	rts

; ---- the hardware: the VBL counts ticks, the ACIA handler reads keys and joysticks ----
init_hardware:
	move	#$2700,sr
	move.l	$70.w,old_vbl
	move.l	$118.w,old_acia
	move.b	$fffffa09.w,old_iera
	move.b	$fffffa15.w,old_imra
	move.l	#vbl,$70.w
	move.l	#acia_isr,$118.w
	bset	#6,$fffffa09.w
	bset	#6,$fffffa15.w
	move.b	#$FF,in_control0
	move.b	#$FF,in_control1
	move.b	#$FF,in_coin
.w1:	btst	#1,$fffffc00.w
	beq.s	.w1
	move.b	#$14,$fffffc02.w	; joystick events
	move	#$2300,sr
	rts

restore_hardware:
	move	#$2700,sr
	move.l	old_vbl,$70.w
	move.l	old_acia,$118.w
	move.b	old_iera,$fffffa09.w
	move.b	old_imra,$fffffa15.w
.w1:	btst	#1,$fffffc00.w
	beq.s	.w1
	move.b	#$08,$fffffc02.w	; mouse again
	move.w	#$0777,$ffff8240.w
	move	#$2300,sr
	rts

vbl:	addq.w	#1,ticks
	rte

; Keyboard and joystick 1: CONTROL0 (right 0, left 1, down 2, up 3, attack 4, jump 5, start 7) and COIN (coin 1 bit
; 4, coin 2 bit 3), active low.
acia_isr:
	movem.l	d0-d2/a0,-(sp)
.again:
	ikbd_byte
	lea	key_table,a0
.find:	move.b	(a0),d0
	beq	.again
	cmp.b	d0,d1
	beq.s	.found
	addq	#4,a0
	bra.s	.find
.found:	tst.b	d2
	bmi.s	.release
	move.b	1(a0),d0
	or.b	d0,kbd_control
	move.b	2(a0),d0
	or.b	d0,kbd_coin
	bsr.s	compose
	bra	.again
.release:
	move.b	1(a0),d0
	not.b	d0
	and.b	d0,kbd_control
	move.b	2(a0),d0
	not.b	d0
	and.b	d0,kbd_coin
	bsr.s	compose
	bra	.again
.packet_byte:
	clr.b	ikbd_state
	cmp.b	#2,d0
	bne	.again			; (joystick 1, port 1, plays)
	moveq	#0,d0
	btst	#3,d1
	beq.s	.j1
	bset	#0,d0
.j1:	btst	#2,d1
	beq.s	.j2
	bset	#1,d0
.j2:	btst	#1,d1
	beq.s	.j3
	bset	#2,d0
.j3:	btst	#0,d1
	beq.s	.j4
	bset	#3,d0
.j4:	tst.b	d1
	bpl.s	.j5
	bset	#4,d0
.j5:	move.b	d0,joy_control
	bsr.s	compose
	bra	.again
.done:
	movem.l	(sp)+,d0-d2/a0
	rte

compose:
	move.b	kbd_control,d0
	or.b	joy_control,d0
	not.b	d0
	move.b	d0,in_control0
	move.b	kbd_coin,d0
	not.b	d0
	move.b	d0,in_coin
	rts

; scancode, CONTROL0 bits, COIN bits
key_table:
	dc.b	$4d,$01,$00,0		; right
	dc.b	$4b,$02,$00,0		; left
	dc.b	$50,$04,$00,0		; down
	dc.b	$48,$08,$00,0		; up
	dc.b	$39,$10,$00,0		; space = attack
	dc.b	$2c,$10,$00,0		; Z = attack
	dc.b	$38,$20,$00,0		; alternate = jump
	dc.b	$2d,$20,$00,0		; X = jump
	dc.b	$02,$80,$00,0		; 1 = start
	dc.b	$06,$00,$10,0		; 5 = coin 1
	dc.b	$07,$00,$08,0		; 6 = coin 2
	dc.b	0,0,0,0
	even
    endc

	include	"core.s"

	section data,data
    ifnd SIM
snapshot:
	incbin	"snapshot.bin"
	even
    endc

	section bss,bss
old_ssp:	ds.l	1
old_vbl:	ds.l	1
old_acia:	ds.l	1
ticks:		ds.w	1
old_iera:	ds.b	1
old_imra:	ds.b	1
in_control0:	ds.b	1
in_control1:	ds.b	1
in_coin:	ds.b	1
kbd_control:	ds.b	1
kbd_coin:	ds.b	1
joy_control:	ds.b	1
mcu_last:	ds.b	4
quit_flag:	ds.b	1
	even
    ifnd SIM
	ikbd_vars
	even
    endc
