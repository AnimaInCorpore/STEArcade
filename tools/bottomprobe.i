; Probe-only helpers. No logging/file calls execute inside a timed pulse.
bp_code macro
bp_load_phase:
	moveq #0,d0
	move.w phase,d0
	mulu #12,d0
	lea bp_phases,a0
	adda.l d0,a0
	move.w (a0)+,d0
	move.w d0,bp_seconds
	move.w d0,countdown
	mulu #50,d0
	move.w d0,bp_frames
	move.w (a0)+,low_gate
	move.w (a0)+,bp_family
	move.w (a0)+,bp_delay
	move.w (a0)+,bp_width
	rts

; Every row is: address, size(bytes), expected, actual, mask, masked XOR.
; Raw values are retained even when all differences are outside defined bits.
bp_restore_add:
	move.l d2,d5
	eor.l d3,d5
	and.l d4,d5
	beq.s .ok
	addq.l #1,restore_bad
.ok:
	movem.l d0-d5,(a3)
	lea 24(a3),a3
	addq.w #1,bp_restore_n
	rts

bp_verify_restoration:
	lea bp_restore_rows,a3
	lea reg_addresses,a0
	lea old_regs,a1
	lea bp_mfp_masks,a4
	moveq #8,d7
.mfp:
	move.l (a0)+,d0
	move.l d0,a2
	moveq #1,d1
	moveq #0,d2
	move.b (a1)+,d2
	moveq #0,d3
	move.b (a2),d3
	moveq #0,d4
	move.b (a4)+,d4
	bsr bp_restore_add
	dbf d7,.mfp
	lea restored_addresses,a0
	lea restored_values,a1
	lea bp_video_masks,a4
	moveq #8,d7
.video:
	move.l (a0)+,d0
	move.l d0,a2
	moveq #1,d1
	moveq #0,d3
	move.b (a2),d3
	move.l (a1)+,a2
	moveq #0,d2
	move.b (a2),d2
	moveq #0,d4
	move.b (a4)+,d4
	bsr bp_restore_add
	dbf d7,.video
	move.l #$fffffa03,d0
	moveq #1,d1
	moveq #0,d2
	move.b bp_old_aer,d2
	moveq #0,d3
	move.b $fffffa03.w,d3
	move.l #$ff,d4
	bsr bp_restore_add
	lea bp_vector_offsets,a0
	lea old_ta,a1
	moveq #3,d7
.vectors:
	moveq #0,d0
	move.w (a0)+,d0
	add.l mfp_base,d0
	move.l d0,a2
	moveq #4,d1
	move.l (a1)+,d2
	move.l (a2),d3
	moveq #-1,d4
	bsr bp_restore_add
	dbf d7,.vectors
	lea $68.w,a2
	lea old_hbl,a1
	moveq #1,d7
.autovectors:
	move.l a2,d0
	moveq #4,d1
	move.l (a1)+,d2
	move.l (a2),d3
	addq.l #8,a2
	moveq #-1,d4
	bsr bp_restore_add
	dbf d7,.autovectors
	lea $ffff8240.w,a2
	lea old_palette,a1
	moveq #15,d7
.palette:
	move.l a2,d0
	moveq #2,d1
	moveq #0,d2
	move.w (a1)+,d2
	moveq #0,d3
	move.w (a2)+,d3
	move.l #$fff,d4
	bsr bp_restore_add
	dbf d7,.palette
	tst.b td_enabled
	beq.s .done
	move.l #$fffffa25,d0
	moveq #1,d1
	moveq #0,d2
	move.b old_tddr,d2
	moveq #0,d3
	move.b $fffffa25.w,d3
	move.l #$ff,d4
	bsr bp_restore_add
.done:
	rts

bp_report:
	lea bp_edge_text,a0
	bsr log_text
	moveq #0,d0
	move.b bp_old_aer,d0
	bsr log_hex
	move.b bp_selected_aer,d0
	bsr log_hex
	move.b bp_end_aer,d0
	bsr log_hex
	move.b bp_restored_aer,d0
	bsr log_hex
	bsr log_eol
	lea bp_phases,a4
	moveq #0,d6
.phases:
	lea bp_case_text,a0
	bsr log_text
	move.l d6,d0
	bsr log_hex
	moveq #5,d7
.values:
	moveq #0,d0
	move.w (a4)+,d0
	bsr log_hex
	dbf d7,.values
	bsr log_eol
	addq.w #1,d6
	cmp.w #PHASE_COUNT,d6
	bne .phases
	lea bp_restore_rows,a4
	moveq #0,d6
.rows:
	cmp.w bp_restore_n,d6
	bhs.s .done
	lea bp_restore_text,a0
	bsr log_text
	moveq #5,d7
.cols:
	move.l (a4)+,d0
	bsr log_hex
	dbf d7,.cols
	bsr log_eol
	addq.w #1,d6
	bra.s .rows
.done:
	rts
	endm

bp_data macro
bp_phases:
	include "bp_phases.i"
bp_mfp_masks: dc.b $ff,$ff,$ff,$ff,$f8,$ff,$ff,$0f,$0f
bp_video_masks: dc.b $ff,$ff,$fe,$03,$03,$0f,$ff,$03,$77
	even
bp_vector_offsets: dc.w 52,32,24,16
bp_edge_text: dc.b 'AER original / selected / end / restored (bit3: 0=DE falling): ',0
bp_case_text: dc.b 'CASE ',0
bp_restore_text: dc.b 'RESTORE addr size expected actual mask diff: ',0
	endm

bp_vars macro
bp_seconds: ds.w 1
bp_frames: ds.w 1
bp_family: ds.w 1
bp_delay: ds.w 1
bp_width: ds.w 1
bp_restore_n: ds.w 1
bp_old_aer: ds.b 1
bp_selected_aer: ds.b 1
bp_end_aer: ds.b 1
bp_restored_aer: ds.b 1
	even
bp_restore_rows: ds.b 64*24
	endm
