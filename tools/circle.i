; Settings are a contiguous table of four words, copied atomically at VBL.
CIRCLE_TOP_DELAY = 78
CIRCLE_TOP_WIDTH = 8
CIRCLE_LOW_DELAY = 101
CIRCLE_LOW_WIDTH = 17
CIRCLE_EVENT_MAX = 128
CIRCLE_EVENT_SIZE = 28

ip_code macro
ip_key:
	lea circle_held,a0
	tst.b d2
	bmi.s .release
	st (a0,d1.w)
	rts
.release:
	tst.b (a0,d1.w)
	beq.s .out
	sf (a0,d1.w)
	move.b d1,circle_input
.out:
	rts

circle_init:
	bsr circle_defaults
	clr.w circle_mode
	move.w #$ff,circle_pending
	rts

circle_defaults:
	move.l #CIRCLE_TOP_DELAY*65536+CIRCLE_TOP_WIDTH,circle_wanted
	move.l #CIRCLE_LOW_DELAY*65536+CIRCLE_LOW_WIDTH,circle_wanted+4
	rts

; Called from VBL after arming the timers. Change parameters only here.
ip_vbl:
	move.w #2,top_gate
	move.w #2,low_gate
	tst.b quit_flag
	bne.s .out
	cmp.w #3,d0
	bne.s .out
	btst #3,$fffffa03.w
	bne.s .out
	tst.w circle_pending
	beq.s .gates
	move.l a0,-(sp)
	move.l circle_wanted,circle_top_delay
	move.l circle_wanted+4,bp_delay
	bsr circle_log
	clr.w circle_pending
	st circle_redraw
	move.l (sp)+,a0
.gates:
	cmp.w #2,circle_mode
	beq.s .out
	clr.w top_gate
	tst.w circle_mode
	bne.s .out
	clr.w low_gate
.out:
	rts

; 1/2 top start, 3/4 bottom start, 5/6 bottom width, 7/8 top width.
; 9 cycles BOTH/TOP/CLOSED, 0 restores defaults and BOTH. X marks and closes.
ip_step:
	move.w #$2700,sr
	moveq #0,d0
	move.b circle_input,d0
	clr.b circle_input
	cmp.b #$13,d0		; R
	beq .quit
	cmp.b #$1f,d0		; S
	beq .quit
	tst.w circle_pending
	bne .refresh
	cmp.w #CIRCLE_EVENT_MAX,circle_event_count
	bhs.s .full
	cmp.b #$02,d0
	blo .refresh
	cmp.b #$09,d0
	bls.s .adjust
	cmp.b #$0a,d0
	beq.s .mode
	cmp.b #$0b,d0
	beq.s .defaults
	cmp.b #$2e,d0		; C marks clean
	beq.s .queue
	cmp.b #$2d,d0		; X marks corruption and selects TOP
	bne .refresh
	move.w #1,circle_mode
	bra.s .queue
.full:
	; Preserve the recorded settings, but allow recovery if the log fills.
	cmp.b #$2d,d0
	bne.s .refresh
	move.w #1,circle_mode
	st circle_redraw
	bra.s .refresh
.adjust:
	move.w d0,d1
	subq.w #2,d1
	lsr.w #1,d1
	mulu #6,d1
	lea circle_controls,a0
	adda.w d1,a0
	lea circle_wanted,a1
	adda.w (a0)+,a1
	btst #0,d0
	bne.s .later
	move.w (a1),d1
	cmp.w (a0),d1
	bls.s .refresh
	subq.w #1,(a1)
	bra.s .queue
.later:
	move.w (a1),d1
	cmp.w 2(a0),d1
	bhs.s .refresh
	addq.w #1,(a1)
	bra.s .queue
.mode:
	addq.w #1,circle_mode
	cmp.w #3,circle_mode
	blo.s .queue
	clr.w circle_mode
	bra.s .queue
.defaults:
	bsr circle_defaults
	clr.w circle_mode
.queue:
	move.w d0,circle_pending
.refresh:
	move.w #$2300,sr
	tst.b circle_redraw
	beq.s .out
	sf circle_redraw
	bsr ip_hud
.out:
	rts
.quit:
	st quit_flag
	move.w #$2300,sr
	rts

; Event fields are all longwords. Record the selected state and the VBL
; on which it became active, including the initial state and C/X marks.
circle_log:
	moveq #0,d0
	move.w circle_event_count,d0
	mulu #CIRCLE_EVENT_SIZE,d0
	lea circle_events,a0
	adda.l d0,a0
	addq.w #1,circle_event_count
	move.l stats,(a0)+
	moveq #0,d0
	move.w circle_pending,d0
	move.l d0,(a0)+
	move.w circle_mode,d0
	move.l d0,(a0)+
	move.w circle_top_delay,d0
	move.l d0,(a0)+
	move.w circle_top_width,d0
	move.l d0,(a0)+
	move.w bp_delay,d0
	move.l d0,(a0)+
	move.w bp_width,d0
	move.l d0,(a0)
	rts

ip_finish:
	st completed
	rts

ip_log_name:
	moveq #0,d0
	move.w d7,d0
	divu #10,d0
	add.b #'0',d0
	move.b d0,filename+4
	swap d0
	add.b #'0',d0
	move.b d0,filename+5
	rts

ip_hud:
	move.l screen,a1
	adda.l #32*STRIDE,a1
	lea circle_mode_tiles,a0
	moveq #0,d0
	move.w circle_mode,d0
	cmp.w #CIRCLE_EVENT_MAX,circle_event_count
	blo.s .mode
	moveq #3,d0
.mode:
	bsr circle_tile
	lea circle_top_tiles,a0
	move.w circle_wanted,d0
	sub.w #74,d0
	mulu #5,d0
	add.w circle_wanted+2,d0
	subq.w #6,d0
	bsr circle_tile
	lea circle_bottom_tiles,a0
	move.w circle_wanted+4,d0
	sub.w #97,d0
	mulu #9,d0
	add.w circle_wanted+6,d0
	sub.w #13,d0
	bsr circle_tile
	lea circle_cpu_tile,a0
	moveq #0,d0
circle_tile:
	mulu #192,d0
	adda.l d0,a0
	moveq #7,d2
.row:
	moveq #5,d1
.copy:
	move.l (a0)+,(a1)+
	dbf d1,.copy
	adda.w #STRIDE-24,a1
	dbf d2,.row
	rts

ip_report:
	lea circle_columns,a0
	bsr log_text
	lea circle_events,a4
	move.w circle_event_count,d6
	beq.s .out
	subq.w #1,d6
.row:
	lea circle_event_text,a0
	bsr log_text
	moveq #6,d7
.field:
	move.l (a4)+,d0
	bsr log_hex
	dbf d7,.field
	bsr log_eol
	dbf d6,.row
.out:
	rts
	endm

ip_data macro
circle_controls: dc.w 0,74,82,4,97,105,6,13,21,2,6,10
circle_columns: dc.b 'Events (hex): VBL key_scancode mode top_delay top_width bottom_delay bottom_width',13,10
	dc.b 'Mode 0=BOTH 1=TOP 2=CLOSED. Key FF=start, 2E=clean mark, 2D=corrupt mark then TOP.',13,10,0
circle_event_text: dc.b 'EVENT ',0
	even
circle_mode_tiles: incbin 'MODE.BIN'
circle_top_tiles: incbin 'TOP.BIN'
circle_bottom_tiles: incbin 'BOTTOM.BIN'
circle_cpu_tile: incbin 'CPU.BIN'
	endm

ip_vars macro
circle_wanted: ds.w 4
circle_top_delay: ds.w 1
circle_top_width: ds.w 1
circle_mode: ds.w 1
circle_pending: ds.w 1
circle_event_count: ds.w 1
circle_input: ds.b 1
circle_redraw: ds.b 1
circle_held: ds.b 128
	even
circle_events: ds.b CIRCLE_EVENT_SIZE*CIRCLE_EVENT_MAX
	endm
