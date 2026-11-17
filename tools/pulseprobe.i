IP_BASELINE = 0
IP_READY = 1
IP_SINGLE = 2
IP_REPEAT = 3
IP_OBSERVE = 4
IP_LOCKED = 5
IP_FULL = 6
IP_MAX = 64
IP_RECORD = 36
IP_START_MIN = 97
IP_START_MAX = 105
IP_WIDTH_MIN = 13
IP_WIDTH_MAX = 21

ip_code macro
; Release-only controls require a preceding make. Ignore held-key repeats.
ip_key:
	lea ip_held,a0
	tst.b d2
	bmi.s .release
	st (a0,d1.w)
	rts
.release:
	tst.b (a0,d1.w)
	beq.s .out
	sf (a0,d1.w)
	move.b d1,ip_input
.out:
	rts

; Called with the VBL's saved registers. Only the VBL changes the gate.
ip_vbl:
	move.w #2,low_gate
	tst.b quit_flag
	bne.s .done
	cmp.w #3,d0
	bne.s .stop
	btst #3,$fffffa03.w
	bne.s .stop
	tst.w ip_left
	beq.s .finished
	subq.w #1,ip_left
	clr.w low_gate
	rts
.stop:
	clr.w ip_left
.finished:
	tst.b ip_stop_pending
	beq.s .natural
	sf ip_stop_pending
	bsr ip_store_result
.natural:
	cmp.w #IP_SINGLE,ip_state
	beq.s .observe
	cmp.w #IP_REPEAT,ip_state
	bne.s .done
.observe:
	bsr ip_store_result
	move.w #IP_OBSERVE,ip_state
	st ip_redraw
.done:
	rts

; The input mailbox has one writer (ACIA); consume under IPL 7.
ip_step:
	move.w #$2700,sr
	moveq #0,d0
	move.b ip_input,d0
	clr.b ip_input
	move.w #$2300,sr
	cmp.b #$13,d0		; R or S, save on exit including an unclassified result
	beq .quit
	cmp.b #$1f,d0
	beq .quit
	cmp.b #$2d,d0		; X records corruption, stops repeat at next VBL, locks
	beq .corrupt
	cmp.b #$2e,d0		; C confirms a clean baseline or records a clean trial
	beq .clean
	cmp.w #IP_READY,ip_state
	bne .refresh
	cmp.b #$39,d0
	beq .single
	cmp.b #$14,d0
	beq .repeat
	cmp.b #$19,d0		; P switches between adjustable and fixed P01
	beq .preset
	cmp.b #$4b,d0
	beq.s .earlier
	cmp.b #$4d,d0
	beq.s .later
	cmp.b #$48,d0
	beq.s .longer
	cmp.b #$50,d0
	beq.s .shorter
	bra .refresh
.earlier:
	cmp.w #IP_START_MIN,bp_delay
	bls.s .adjusted
	subq.w #1,bp_delay
	bra.s .adjusted
.later:
	cmp.w #IP_START_MAX,bp_delay
	bhs.s .adjusted
	addq.w #1,bp_delay
	bra.s .adjusted
.longer:
	cmp.w #IP_WIDTH_MAX,bp_width
	bhs.s .adjusted
	addq.w #1,bp_width
	bra.s .adjusted
.shorter:
	cmp.w #IP_WIDTH_MIN,bp_width
	bls.s .adjusted
	subq.w #1,bp_width
.adjusted:
	move.w #1,bp_family
	bra.s .changed
.preset:
	eori.w #1,bp_family
	move.w #101,bp_delay
	move.w #17,bp_width
.changed:
	clr.b ip_can_repeat
	st ip_redraw
	bra .refresh
.single:
	moveq #1,d0
	bra.s .arm
.repeat:
	tst.b ip_can_repeat
	beq .refresh
	move.w #500,d0
.arm:
	cmp.w #IP_MAX,ip_trials
	bhs .refresh
	; Initialize the entire record before arming the VBL.
	move.w #$2700,sr
	moveq #0,d1
	move.w ip_trials,d1
	mulu #IP_RECORD,d1
	lea ip_records,a0
	adda.l d1,a0
	move.l a0,ip_current
	addq.w #1,ip_trials
	moveq #0,d1
	move.w ip_trials,d1
	move.l d1,(a0)+
	moveq #0,d1
	move.w bp_family,d1
	move.l d1,(a0)+
	move.w bp_delay,d1
	move.l d1,(a0)+
	move.w bp_width,d1
	move.l d1,(a0)+
	and.l #$ffff,d0
	move.l d0,(a0)+
	move.l stats,(a0)+
	clr.l (a0)+
	clr.l (a0)+
	clr.l (a0)
	clr.l ip_pulses
	move.w #IP_SINGLE,ip_state
	cmp.w #1,d0
	beq.s .armed
	move.w #IP_REPEAT,ip_state
.armed:
	move.w d0,ip_left
	move.w #$2300,sr
	st ip_redraw
	bra .refresh
.clean:
	tst.w ip_state
	bne.s .clean_trial
	cmp.l #10,stats
	blo .refresh
	bra.s .ready
.clean_trial:
	cmp.w #IP_OBSERVE,ip_state
	bne .refresh
	move.l ip_current,a0
	move.l #1,28(a0)
	cmp.l #1,16(a0)
	bne.s .ready
	cmp.l #1,ip_pulses
	bne.s .ready
	st ip_can_repeat
.ready:
	move.w #IP_READY,ip_state
	cmp.w #IP_MAX,ip_trials
	blo.s .ready_refresh
	move.w #IP_FULL,ip_state
.ready_refresh:
	st ip_redraw
	bra .refresh
.corrupt:
	cmp.w #IP_LOCKED,ip_state
	bhs .refresh
	move.w #$2700,sr
	clr.w ip_left
	move.l ip_current,d0
	beq.s .lock
	cmp.w #IP_SINGLE,ip_state
	blo.s .lock
	move.l d0,a0
	move.l #2,28(a0)
	st ip_stop_pending
.lock:
	move.w #IP_LOCKED,ip_state
	move.w #$2300,sr
	st ip_redraw
	bra .refresh
.quit:
	st quit_flag
	rts
.refresh:
	cmp.w #IP_REPEAT,ip_state
	bne.s .other
	moveq #0,d0
	move.w ip_left,d0
	add.w #49,d0
	divu #50,d0
	cmp.w countdown,d0
	beq.s .changed_hud
	move.w d0,countdown
	st ip_redraw
	bra.s .changed_hud
.other:
	clr.w countdown
.changed_hud:
	tst.b ip_redraw
	beq.s .return
	sf ip_redraw
	bsr ip_hud
.return:
	rts

ip_store_result:
	move.l ip_current,d0
	beq.s .out
	move.l d0,a0
	tst.l 32(a0)
	bne.s .out
	move.l ip_pulses,24(a0)
	move.l stats,32(a0)
.out:
	rts

ip_finish:
	bsr ip_store_result
	st completed
	rts

ip_log_name:
	moveq #0,d0
	move.w d7,d0
	divu #10,d0
	add.b #'0',d0
	move.b d0,filename+5
	swap d0
	add.b #'0',d0
	move.b d0,filename+6
	rts

ip_hud:
	move.l screen,a1
	adda.l #32*STRIDE,a1
	lea ip_labels,a0
	moveq #0,d0
	move.w ip_state,d0
	tst.w bp_family
	bne.s .adjustable
	addq.w #7,d0
.adjustable:
	mulu #192,d0
	adda.l d0,a0
	bsr ip_tile
	lea ip_delays,a0
	moveq #0,d0
	move.w bp_delay,d0
	sub.w #IP_START_MIN,d0
	mulu #192,d0
	adda.l d0,a0
	bsr ip_tile
	lea ip_widths,a0
	moveq #0,d0
	move.w bp_width,d0
	sub.w #IP_WIDTH_MIN,d0
	mulu #192,d0
	adda.l d0,a0
	bsr ip_tile
	lea timer_tiles,a0
	moveq #0,d0
	move.w countdown,d0
	mulu #192,d0
	adda.l d0,a0
ip_tile:
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
	lea ip_columns,a0
	bsr log_text
	lea ip_records,a4
	move.w ip_trials,d6
	beq.s .done
	subq.w #1,d6
.row:
	lea ip_trial_text,a0
	bsr log_text
	moveq #8,d7
.field:
	move.l (a4)+,d0
	bsr log_hex
	dbf d7,.field
	bsr log_eol
	dbf d6,.row
.done:
	rts
	endm

ip_data macro
ip_columns: dc.b 'Trial fields (hex): number family delay width requested armed_vbl pulses outcome last_vbl',13,10,0
ip_trial_text: dc.b 'TRIAL ',0
	even
ip_labels: incbin 'IPLABEL.BIN'
ip_delays: incbin 'IPDELAY.BIN'
ip_widths: incbin 'IPWIDTH.BIN'
	endm

ip_vars macro
ip_state: ds.w 1
ip_left: ds.w 1
ip_trials: ds.w 1
ip_input: ds.b 1
ip_redraw: ds.b 1
ip_can_repeat: ds.b 1
ip_stop_pending: ds.b 1
ip_held: ds.b 128
	even
ip_current: ds.l 1
ip_pulses: ds.l 1
ip_records: ds.b IP_RECORD*IP_MAX
	endm
