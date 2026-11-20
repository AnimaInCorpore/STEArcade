; Unattended Mega STE video isolation. No gameplay or runtime Blitter work.
; Generated gates keep active/dummy frequency pulses on the same instruction path.
TA_DATA = 98
TA_NOPS = 84
PIC_TOP = 10
PIC_LINES = 256
BD_PALETTE = 0
BD_K = 3
BD_POLL = 240
DEBUG = 1
KEY_ESC = 1
	ifnd SECONDS
SECONDS = 20
	endc
	ifnd PHASE_COUNT
PHASE_COUNT = 3
	endc
	ifnd LABEL_HEIGHT
LABEL_HEIGHT = 16
	endc
	ifd BOTTOM_PROBE
	include "bottomprobe.i"
	endc
	ifd INTERACTIVE_PULSE
	ifd CIRCLE_PROBE
	include "circle.i"
	else
	include "pulseprobe.i"
	endc
	endc
FRAMES = SECONDS*50
STRIDE = 256
ROWS = 320
RECSIZE = 64
	include "vc_borders.i"
	include "ikbd.s"
	section text,code
start:
	clr.l -(sp)
	move.w #$20,-(sp)
	trap #1
	addq.l #6,sp
	move.l d0,old_ssp
	lea report,a5
	lea title,a0
	bsr log_text
	move.l $5a0.w,d0
	beq unsupported
	move.l d0,a0
	moveq #31,d2
.cookie:
	move.l (a0)+,d0
	beq unsupported
	move.l (a0)+,d1
	cmp.l #'_MCH',d0
	beq .machine
	dbf d2,.cookie
	bra unsupported
.machine:
	cmp.l #$10010,d1
	bne unsupported
	move.l $4f2.w,a0
	moveq #0,d0
	move.w 2(a0),d0
	bsr log_hex
	moveq #0,d0
	; a0 was used by log_hex: read the OS header again.
	move.l $4f2.w,a0
	move.w 28(a0),d0
	bsr log_hex
	bsr log_eol
	ifd INTERACTIVE_PULSE
	moveq #0,d7
.find_log:
	bsr ip_log_name
	endc
	clr.w -(sp)
	pea filename
	move.w #$3d,-(sp)
	trap #1
	addq.l #8,sp
	tst.l d0
	bmi .new
	move.w d0,-(sp)
	move.w #$3e,-(sp)
	trap #1
	addq.l #4,sp
	ifd INTERACTIVE_PULSE
	addq.w #1,d7
	cmp.w #100,d7
	blo .find_log
	endc
	lea exists_text,a0
	bra quit_message
.new:
	tst.b $fffffa19.w
	bne busy
	tst.b $fffffa1b.w
	bne busy
	move.b $fffffa0b.w,d0
	or.b $fffffa0f.w,d0
	and.b #$21,d0
	bne busy
	move.b $ffff8e21.w,old_speed
	move.b $fffffa1d.w,old_cd
	move.b $ffff820a.w,old_sync
	move.b $ffff8260.w,old_res
	move.b $ffff8265.w,old_fine
	move.b $ffff820f.w,old_width
	move.b $ffff8201.w,old_base+1
	move.b $ffff8203.w,old_base+2
	move.b $ffff820d.w,old_base+3
	movem.l $ffff8240.w,d0-d7
	movem.l d0-d7,old_palette
	; One private aligned screen, plus a read-only copy used for integrity checks.
	lea screen_space+255,a0
	move.l a0,d0
	and.l #$ffffff00,d0
	move.l d0,screen
	move.l d0,a1
	lea frozen_image,a0
	move.w #STRIDE*ROWS/4-1,d0
.copy:
	move.l (a0)+,(a1)+
	dbf d0,.copy
	lea stats,a4
	move.l a4,current_stats
	moveq #PHASE_COUNT-1,d0
.initstats:
	move.l #$7fffffff,12(a4)
	lea RECSIZE(a4),a4
	dbf d0,.initstats
	clr.w phase
	move.w #2,top_gate
	move.w #2,low_gate
	move.w #SECONDS,countdown
	ifd BOTTOM_PROBE
	clr.w top_gate
	bsr bp_load_phase
	endc
	ifd INTERACTIVE_PULSE
	ifd CIRCLE_PROBE
	bsr circle_init
	endc
	bsr ip_hud
	else
	bsr draw_hud
	endc
	; Confirm the output directory is writable before owning the display.
	bsr save_report
	tst.b save_failed
	bne disk_error
	move.w sr,old_sr
	ori.w #$700,sr
	move.l $68.w,old_hbl
	move.l $70.w,old_vbl
	lea reg_addresses,a0
	lea old_regs,a1
	moveq #8,d0
.saveregs:
	move.l (a0)+,a2
	move.b (a2),(a1)+
	dbf d0,.saveregs
	moveq #0,d0
	move.b $fffffa17.w,d0
	and.w #$f0,d0
	lsl.w #2,d0
	move.l d0,mfp_base
	move.l d0,a0
	move.l 52(a0),old_ta
	move.l 32(a0),old_tb
	move.l 24(a0),old_acia
	move.l 16(a0),old_td
	move.l #timer_a,52(a0)
	move.l #timer_b,32(a0)
	move.l #acia,24(a0)
	; Only use Timer D if TOS left it stopped and without pending/service IRQs.
	move.b $fffffa1d.w,d0
	and.b #7,d0
	bne .no_td
	move.b $fffffa0d.w,d0
	or.b $fffffa11.w,d0
	and.b #$10,d0
	bne .no_td
	st td_enabled
	move.b $fffffa25.w,old_tddr
	move.l #timer_d,16(a0)
.no_td:
	ifd BOTTOM_PROBE
	move.b $fffffa03.w,bp_old_aer
	bclr #3,$fffffa03.w
	move.b $fffffa03.w,bp_selected_aer
	endc
	move.l #hbl,$68.w
	move.l #vbl,$70.w
	bclr #3,$fffffa17.w
	move.b #$21,$fffffa07.w
	move.b #$40,d0
	tst.b td_enabled
	beq .maskready
	or.b #$10,d0
.maskready:
	move.b d0,$fffffa09.w
	move.b d0,$fffffa15.w
	move.b #$21,$fffffa13.w
	move.b old_speed,d0
	or.b #3,d0
	move.b d0,$ffff8e21.w
	move.b $ffff8e21.w,selected_speed
	st bd_speed_known
	st bd_is_mste
	st bd_fast
	clr.b $ffff8260.w
	move.b #2,$ffff820a.w
	clr.b $ffff8265.w
	move.b #48,$ffff820f.w
	move.l screen,d0
	move.b d0,$ffff820d.w
	lsr.l #8,d0
	move.b d0,$ffff8203.w
	lsr.l #8,d0
	move.b d0,$ffff8201.w
	movem.l image_palette,d0-d7
	movem.l d0-d7,$ffff8240.w
	move.w #$2300,sr
.wait:
	stop #$2300
	tst.b quit_flag
	bne .exit
	ifd INTERACTIVE_PULSE
	bsr ip_step
	bra .wait
	else
	move.w phase_frames,d0
	ifd BOTTOM_PROBE
	cmp.w bp_frames,d0
	else
	cmp.w #FRAMES,d0
	endc
	bhs .next
	moveq #0,d0
	move.w phase_frames,d0
	divu #50,d0
	ifd BOTTOM_PROBE
	move.w bp_seconds,d1
	else
	moveq #SECONDS,d1
	endc
	sub.w d0,d1
	cmp.w countdown,d1
	beq .wait
	move.w d1,countdown
	bsr draw_hud
	bra .wait
.next:
	bsr check_image
	ifd BOTTOM_PROBE
	; Latch every new timing at VBL, never halfway through a pulse frame.
	move.w phase_frames,d0
.wait_phase_vbl:
	stop #$2300
	cmp.w phase_frames,d0
	beq.s .wait_phase_vbl
	endc
	ori.w #$700,sr
	bsr snapshot_counters
	move.l current_stats,a4
	move.l #1,40(a4)
	cmp.w #PHASE_COUNT-1,phase
	beq .all_done
	addq.w #1,phase
	add.l #RECSIZE,current_stats
	clr.w phase_frames
	clr.w top_gate
	cmp.w #2,phase
	bne .gate_ready
	clr.w low_gate
.gate_ready:
	move.w #SECONDS,countdown
	ifd BOTTOM_PROBE
	bsr bp_load_phase
	endc
	move.w #$2300,sr
	bsr draw_hud
	bra .wait
.all_done:
	st completed
	endc
.exit:
	ifd INTERACTIVE_PULSE
	; Keep the check before teardown, at the same interrupt level as normal foreground.
	st quit_flag
	bsr check_image
	endc
	ori.w #$700,sr
	ifd INTERACTIVE_PULSE
	bsr ip_finish
	endc
	tst.b completed
	bne .snapshot_done
	bsr snapshot_counters
.snapshot_done:
	ifd BOTTOM_PROBE
	move.b $fffffa03.w,bp_end_aer
	endc
	move.b $ffff8e21.w,end_speed
	clr.b $fffffa19.w
	clr.b $fffffa1b.w
	tst.b td_enabled
	beq .td_done
	and.b #$f0,$fffffa1d.w
	move.b old_tddr,$fffffa25.w
	bclr #4,$fffffa0d.w
	bclr #4,$fffffa11.w
.td_done:
	bclr #5,$fffffa0b.w
	bclr #0,$fffffa0b.w
	bclr #5,$fffffa0f.w
	bclr #0,$fffffa0f.w
	move.l mfp_base,a0
	move.l old_ta,52(a0)
	move.l old_tb,32(a0)
	move.l old_acia,24(a0)
	move.l old_td,16(a0)
	move.l old_hbl,$68.w
	move.l old_vbl,$70.w
	ifd BOTTOM_PROBE
	move.b bp_old_aer,$fffffa03.w
	move.b $fffffa03.w,bp_restored_aer
	endc
	lea reg_addresses,a0
	lea old_regs,a1
	moveq #8,d0
.restoreregs:
	move.l (a0)+,a2
	move.b (a1)+,(a2)
	dbf d0,.restoreregs
	move.b old_res,$ffff8260.w
	move.b old_sync,$ffff820a.w
	move.b old_fine,$ffff8265.w
	move.b old_width,$ffff820f.w
	move.b old_base+1,$ffff8201.w
	move.b old_base+2,$ffff8203.w
	move.b old_base+3,$ffff820d.w
	movem.l old_palette,d0-d7
	movem.l d0-d7,$ffff8240.w
	move.b old_speed,$ffff8e21.w
	move.b $ffff8e21.w,restored_speed
	; Verify saved masks, vectors and the explicitly owned video registers.
	ifd BOTTOM_PROBE
	bsr bp_verify_restoration
	else
	lea reg_addresses,a0
	lea old_regs,a1
	moveq #8,d0
.verify_regs:
	move.l (a0)+,a2
	move.b (a1)+,d1
	cmp.b (a2),d1
	beq .reg_ok
	addq.l #1,restore_bad
.reg_ok:
	dbf d0,.verify_regs
	bsr verify_restoration
	endc
	move.w old_sr,sr
	; Finish a desktop frame before returning; no disk access during any stage.
	move.w #37,-(sp)
	trap #14
	addq.l #2,sp
	bsr final_report
	bsr save_report
	tst.b save_failed
	bne disk_error
	lea done_text,a0
	bra quit_message
unsupported:
	lea unsupported_text,a0
	bra quit_message
busy:
	lea busy_text,a0
	bra quit_message
disk_error:
	lea disk_text,a0
quit_message:
	move.l a0,-(sp)
	move.w #9,-(sp)
	trap #1
	addq.l #6,sp
	move.l old_ssp,-(sp)
	move.w #$20,-(sp)
	trap #1
	addq.l #6,sp
	clr.w -(sp)
	trap #1

verify_restoration:
	lea restored_addresses,a0
	; Saved MFP vectors are not contiguous in their vector table.
	move.l mfp_base,a2
	move.l old_ta,d0
	cmp.l 52(a2),d0
	beq .tb
	addq.l #1,restore_bad
.tb:
	move.l old_tb,d0
	cmp.l 32(a2),d0
	beq .acia
	addq.l #1,restore_bad
.acia:
	move.l old_acia,d0
	cmp.l 24(a2),d0
	beq .td
	addq.l #1,restore_bad
.td:
	move.l old_td,d0
	cmp.l 16(a2),d0
	beq .hbl
	addq.l #1,restore_bad
.hbl:
	move.l old_hbl,d0
	cmp.l $68.w,d0
	beq .vbl
	addq.l #1,restore_bad
.vbl:
	move.l old_vbl,d0
	cmp.l $70.w,d0
	beq .video
	addq.l #1,restore_bad
.video:
	lea restored_values,a1
	moveq #8,d2
.next:
	move.l (a1)+,a2
	move.b (a2),d0
	move.l (a0)+,a2
	cmp.b (a2),d0
	beq .good
	addq.l #1,restore_bad
.good:
	dbf d2,.next
	lea old_palette,a0
	lea $ffff8240.w,a1
	moveq #15,d2
.palette:
	move.w (a0)+,d0
	cmp.w (a1)+,d0
	beq .pal_ok
	addq.l #1,restore_bad
.pal_ok:
	dbf d2,.palette
	rts

hbl:
	rte
vbl:
	borders_vbl
	movem.l d0-d2/a0-a1,-(sp)
	addq.l #4,$4ba.w
	addq.w #1,phase_frames
	move.l current_stats,a0
	addq.l #1,(a0)
	moveq #0,d0
	move.b $ffff8e21.w,d0
	move.l d0,48(a0)
	tst.l 44(a0)
	bne .gotfirst
	move.l d0,44(a0)
.gotfirst:
	and.w #3,d0
	cmp.w #3,d0
	beq .speed_ok
	addq.l #1,4(a0)
.speed_ok:
	ifd INTERACTIVE_PULSE
	bsr ip_vbl
	endc
	ifd BOTTOM_PROBE
	moveq #0,d0
	move.b $fffffa03.w,d0
	move.l d0,56(a0)
	cmp.l #1,(a0)
	bne.s .edge_first_done
	move.l d0,52(a0)
.edge_first_done:
	btst #3,d0
	beq.s .edge_ok
	addq.l #1,60(a0)
.edge_ok:
	endc
	tst.b td_enabled
	beq .out
	and.b #$f0,$fffffa1d.w
	bclr #4,$fffffa0d.w
	move.b #238,$fffffa25.w
	or.b #7,$fffffa1d.w
.out:
	movem.l (sp)+,d0-d2/a0-a1
	rte

; /200 * 238 = 19.369 ms after VBL: after the picture, before line-310 reset.
; C is sampled during black guard-row DMA, so its counter can vary within a line.
timer_d:
	movem.l d0-d2/a0-a1,-(sp)
	and.b #$f0,$fffffa1d.w
	cmp.w #8,phase_frames
	blo .out
	move.l current_stats,a0
	addq.l #1,8(a0)
.retry:
	moveq #0,d0
	move.b $ffff8205.w,d0
	lsl.l #8,d0
	move.b $ffff8207.w,d0
	move.w d0,d1
	lsl.l #8,d0
	move.b $ffff8209.w,d0
	moveq #0,d2
	move.b $ffff8205.w,d2
	lsl.w #8,d2
	move.b $ffff8207.w,d2
	cmp.w d1,d2
	bne .retry
	sub.l screen,d0
	cmp.l 12(a0),d0
	bhs .minok
	move.l d0,12(a0)
.minok:
	cmp.l 16(a0),d0
	bls .maxok
	move.l d0,16(a0)
.maxok:
	tst.b $ffff8260.w
	bne .bad
	tst.b $ffff8265.w
	bne .bad
	cmp.b #48,$ffff820f.w
	bne .bad
	move.b $ffff820a.w,d0
	and.b #2,d0
	cmp.b #2,d0
	beq .out
.bad:
	addq.l #1,20(a0)
.out:
	movem.l (sp)+,d0-d2/a0-a1
	rte
acia:
	ifd INTERACTIVE_PULSE
	movem.l d0-d2/a0,-(sp)
	else
	movem.l d0-d2,-(sp)
	endc
.again:
	ikbd_byte
	ifd INTERACTIVE_PULSE
	bsr ip_key
	endc
	bra .again
.packet_byte:
	clr.b ikbd_state
	bra .again
.done:
	; Drain MIDI too if it shares the asserted ACIA line.
	btst #0,$fffffc04.w
	beq .out
	move.b $fffffc06.w,d0
	bra .done
.out:
	ifd INTERACTIVE_PULSE
	movem.l (sp)+,d0-d2/a0
	else
	movem.l (sp)+,d0-d2
	endc
	rte

snapshot_counters:
	move.l current_stats,a0
	lea bd_fallbacks,a1
	lea counter_baseline,a2
	lea 28(a0),a0
	moveq #0,d0
	move.w (a1),d0
	sub.w (a2),d0
	move.l d0,(a0)+
	moveq #0,d0
	move.w 2(a1),d0
	sub.w 2(a2),d0
	move.l d0,(a0)+
	moveq #0,d0
	move.w 6(a1),d0
	sub.w 6(a2),d0
	move.l d0,(a0)
	; Caller advances phase; snapshot once per phase (not twice at normal finish).
	movem.l (a1),d0-d1
	movem.l d0-d1,(a2)
	rts
check_image:
	movem.l d0-d3/a0-a2,-(sp)
	lea frozen_image,a0
	move.l screen,a1
	move.l current_stats,a2
	move.w #ROWS-1,d2
	moveq #0,d3
.row:
	move.w #STRIDE/2-1,d1
.word:
	move.w (a0)+,d0
	cmp.w (a1)+,d0
	beq .same
	; HUD occupies bytes 0..23, rows 32..63 only; everything else is immutable.
	cmp.w #32,d3
	blo .bad
	cmp.w #64,d3
	bhs .bad
	cmp.w #STRIDE/2-12,d1
	bhs .same
.bad:
	addq.l #1,24(a2)
.same:
	dbf d1,.word
	addq.w #1,d3
	dbf d2,.row
	movem.l (sp)+,d0-d3/a0-a2
	rts

; Pre-rendered 48px HUD tiles: A/B/C + mode, constant CPU legend, countdown.
; Only black side-band bytes are changed; no game pixels are touched.
draw_hud:
	movem.l d0-d2/a0-a2,-(sp)
	moveq #0,d0
	move.w phase,d0
	mulu #24*LABEL_HEIGHT,d0
	lea label_tiles,a0
	adda.l d0,a0
	move.l screen,a1
	adda.l #32*STRIDE,a1
	moveq #LABEL_HEIGHT-1,d2
.labels:
	moveq #5,d1
.lcopy:
	move.l (a0)+,(a1)+
	dbf d1,.lcopy
	adda.w #STRIDE-24,a1
	dbf d2,.labels
	move.w countdown,d0
	mulu #24*8,d0
	lea timer_tiles,a0
	adda.l d0,a0
	move.l screen,a1
	adda.l #56*STRIDE,a1
	moveq #7,d2
.timer:
	moveq #5,d1
.tcopy:
	move.l (a0)+,(a1)+
	dbf d1,.tcopy
	adda.w #STRIDE-24,a1
	dbf d2,.timer
	movem.l (sp)+,d0-d2/a0-a2
	rts
	borders_handlers
	ifd BOTTOM_PROBE
	bp_code
	endc
	ifd INTERACTIVE_PULSE
	ip_code
	endc

final_report:
	lea cpu_text,a0
	bsr log_text
	moveq #0,d0
	move.b old_speed,d0
	bsr log_hex
	move.b selected_speed,d0
	bsr log_hex
	move.b end_speed,d0
	bsr log_hex
	move.b restored_speed,d0
	bsr log_hex
	bsr log_eol
	lea restore_text,a0
	bsr log_text
	move.l restore_bad,d0
	bsr log_hex
	bsr log_eol
	lea base_text,a0
	bsr log_text
	move.l screen,d0
	bsr log_hex
	bsr log_eol
	lea td_text,a0
	bsr log_text
	moveq #0,d0
	move.b td_enabled,d0
	and.w #1,d0
	bsr log_hex
	bsr log_eol
	lea stats,a4
	moveq #0,d5
.stage:
	lea stage_text,a0
	bsr log_text
	move.l d5,d0
	bsr log_hex
	lea (a4),a3
	ifd BOTTOM_PROBE
	moveq #15,d4
	else
	moveq #12,d4
	endc
.field:
	move.l (a3)+,d0
	bsr log_hex
	dbf d4,.field
	bsr log_eol
	lea RECSIZE(a4),a4
	addq.l #1,d5
	cmp.w #PHASE_COUNT,d5
	bne .stage
	ifd BOTTOM_PROBE
	bsr bp_report
	endc
	ifd INTERACTIVE_PULSE
	bsr ip_report
	endc
	lea end_text,a0
	bsr log_text
	moveq #0,d0
	move.b completed,d0
	and.w #1,d0
	bsr log_hex
	bsr log_eol
	rts
log_text:
	move.b (a0)+,d0
	beq .out
	move.b d0,(a5)+
	bra log_text
.out:
	rts
log_eol:
	lea eol,a0
	bra log_text
log_hex:
	moveq #7,d2
.digit:
	rol.l #4,d0
	moveq #15,d1
	and.w d0,d1
	lea digits,a0
	move.b (a0,d1.w),(a5)+
	dbf d2,.digit
	move.b #' ',(a5)+
	rts
save_report:
	movem.l d0-d7/a0-a6,-(sp)
	move.l a5,d7
	sub.l #report,d7
	clr.w -(sp)
	pea filename
	move.w #$3c,-(sp)
	trap #1
	addq.l #8,sp
	tst.l d0
	bmi .fail
	move.w d0,d6
	pea report
	move.l d7,-(sp)
	move.w d6,-(sp)
	move.w #$40,-(sp)
	trap #1
	lea 12(sp),sp
	cmp.l d7,d0
	beq .close
	st save_failed
.close:
	move.w d6,-(sp)
	move.w #$3e,-(sp)
	trap #1
	addq.l #4,sp
	tst.l d0
	bpl .out
.fail:
	st save_failed
.out:
	movem.l (sp)+,d0-d7/a0-a6
	rts
	section data,data
reg_addresses:
	dc.l $fffffa07,$fffffa09,$fffffa13,$fffffa15,$fffffa17
	dc.l $fffffa1f,$fffffa21,$fffffa19,$fffffa1b
restored_addresses:
	dc.l $ffff8201,$ffff8203,$ffff820d,$ffff820a
	dc.l $ffff8260,$ffff8265,$ffff820f,$ffff8e21
	dc.l $fffffa1d
restored_values:
	dc.l old_base+1,old_base+2,old_base+3,old_sync
	dc.l old_res,old_fine,old_width,old_speed
	dc.l old_cd
	ifd BOTTOM_PROBE
	ifd INTERACTIVE_PULSE
	ifd CIRCLE_PROBE
filename: dc.b 'CIRC00.TXT',0
	else
filename: dc.b 'PULSE00.TXT',0
	endc
	else
filename: dc.b 'BOTTOM.TXT',0
	endc
	else
filename: dc.b 'VIDCTRL.TXT',0
	endc
digits: dc.b '0123456789ABCDEF'
eol: dc.b 13,10,0
	ifd BOTTOM_PROBE
	ifd INTERACTIVE_PULSE
	ifd CIRCLE_PROBE
title: dc.b 'CIRCLE 1 - Mega STE border timing test card',13,10
	else
title: dc.b 'PULSE 1 - Mega STE interactive bottom-border probe',13,10
	endc
	else
title: dc.b 'BOTTOM 1 - Mega STE bottom-border pulse probe',13,10
	endc
	else
title: dc.b 'VIDCTRL 1 - Mega STE controlled scanout test',13,10
	endc
	include "vc_build.i"
	dc.b 'TOS version / os_conf (HEX): ',0
cpu_text: dc.b 'CPU original / selected / end / restored FF8E21: ',0
restore_text: dc.b 'Restoration register/vector mismatches (must be zero): ',0
base_text: dc.b 'Fixed screen base, stride=256, fine=0, LINEWID=48: ',0
td_text: dc.b 'Late-frame Timer D sampler available (1=yes): ',0
stage_text: dc.b 'STAGE ',0
	ifd INTERACTIVE_PULSE
end_text: dc.b 'DONE interactive session: ',0
	else
end_text: dc.b 'DONE completed (1=yes,0=Esc abort): ',0
	endc
	ifd BOTTOM_PROBE
	ifd INTERACTIVE_PULSE
	ifd CIRCLE_PROBE
exists_text: dc.b 'All CIRC00-CIRC99 log slots are used.',13,10,0
	else
exists_text: dc.b 'All PULSE00-PULSE99 log slots are used.',13,10,0
	endc
	else
exists_text: dc.b 'BOTTOM.TXT exists. Use a fresh folder for another run.',13,10,0
	endc
	else
exists_text: dc.b 'VIDCTRL.TXT exists. Use a fresh folder for another run.',13,10,0
	endc
unsupported_text: dc.b 'VIDCTRL needs a Mega STE. Settings unchanged.',13,10,0
busy_text: dc.b 'Timer A/B busy. Please clean-boot and retry. Settings unchanged.',13,10,0
	ifd BOTTOM_PROBE
	ifd INTERACTIVE_PULSE
	ifd CIRCLE_PROBE
disk_text: dc.b 'Cannot save CIRC log. Check free space/write protection.',13,10,0
done_text: dc.b 'CIRCLE finished. Results saved in the next numbered CIRC log.',13,10,0
	else
disk_text: dc.b 'Cannot save PULSE log. Check free space/write protection.',13,10,0
done_text: dc.b 'PULSE finished. Results saved in the next numbered PULSE log.',13,10,0
	endc
	else
disk_text: dc.b 'Cannot save BOTTOM.TXT. Check free space/write protection.',13,10,0
done_text: dc.b 'BOTTOM finished. Please return BOTTOM.TXT and phone video.',13,10,0
	endc
	else
disk_text: dc.b 'Cannot save VIDCTRL.TXT. Please check free space/write protection.',13,10,0
done_text: dc.b 'VIDCTRL finished. Please return VIDCTRL.TXT and phone photos/video.',13,10,0
	endc
	ifd INTERACTIVE_PULSE
	even
	endc
	ifd BOTTOM_PROBE
	bp_data
	endc
	even
	ifd INTERACTIVE_PULSE
	ip_data
	even
	endc
image_palette: incbin 'PALETTE.BIN'
label_tiles: incbin 'LABELS.BIN'
timer_tiles: incbin 'TIMERS.BIN'
frozen_image: incbin 'FRAME.BIN'
	section bss,bss
old_ssp: ds.l 1
old_hbl: ds.l 1
old_vbl: ds.l 1
old_ta: ds.l 1
old_tb: ds.l 1
old_acia: ds.l 1
old_td: ds.l 1
mfp_base: ds.l 1
old_base: ds.l 1
old_palette: ds.l 8
old_regs: ds.b 9
old_speed: ds.b 1
old_cd: ds.b 1
selected_speed: ds.b 1
end_speed: ds.b 1
restored_speed: ds.b 1
old_sync: ds.b 1
old_res: ds.b 1
old_fine: ds.b 1
old_width: ds.b 1
old_tddr: ds.b 1
td_enabled: ds.b 1
save_failed: ds.b 1
quit_flag: ds.b 1
completed: ds.b 1
	ikbd_vars
	even
old_sr: ds.w 1
phase: ds.w 1
phase_frames: ds.w 1
top_gate: ds.w 1
low_gate: ds.w 1
countdown: ds.w 1
screen: ds.l 1
current_stats: ds.l 1
restore_bad: ds.l 1
counter_baseline: ds.w 4
	borders_vars
	even
stats: ds.b RECSIZE*PHASE_COUNT
screen_space: ds.b STRIDE*ROWS+255
	ifd BOTTOM_PROBE
	even
	bp_vars
	ifd INTERACTIVE_PULSE
	ip_vars
	endc
report: ds.b 16384
	else
report: ds.b 4096
	endc
