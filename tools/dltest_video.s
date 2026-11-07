	section text
palette_test:
	stage_begin 6,1,0
	lea palette_begin,a0
	bsr log_text
	clr.l palette_bad
	lea $ffff8240.w,a0
	moveq #15,d4
.reg:
	moveq #11,d5
.bit:
	moveq #1,d0
	lsl.w d5,d0
	move.w d0,(a0)
	move.w (a0),d1
	and.w #$fff,d1
	cmp.w d0,d1
	beq .one_ok
	addq.l #1,palette_bad
.one_ok:
	eor.w #$fff,d0
	move.w d0,(a0)
	move.w (a0),d1
	and.w #$fff,d1
	cmp.w d0,d1
	beq .zero_ok
	addq.l #1,palette_bad
.zero_ok:
	dbf d5,.bit
	addq.l #2,a0
	dbf d4,.reg
	movem.l test_palette,d0-d7
	movem.l d0-d7,$ffff8240.w
	bsr progress_unit
	bsr progress_end
	lea palette_result,a0
	bsr log_text
	move.l palette_bad,d0
	bsr log_hex
	bsr log_eol
	tst.l palette_bad
	beq .ok
	addq.l #1,auto_failures
.ok:
	rts
mode_validate:
	lea mode_end_text,a0
	bsr log_text
	moveq #0,d0
	tst.b is_mega
	beq .ste
	move.b $ffff8e21.w,d0
	move.l d0,d4
	bsr log_hex
	and.b #3,d4
	move.w mode_index,d0
	lea speeds,a0
	cmp.b (a0,d0.w),d4
	beq .ok
	addq.l #1,auto_failures
	bra .ok
.ste:
	bsr log_hex
.ok:
	bsr log_eol
	rts
summary:
	lea summary_text,a0
	bsr log_text
	move.l auto_failures,d0
	bsr log_hex
	bsr log_eol
	lea summary_scope,a0
	bsr log_text
	rts
	section data
palette_begin: dc.b 'BEGIN 16 palette registers: all 12 bits walking-one/zero',13,10,0
palette_result: dc.b 'PALETTE readback mismatches: ',0
mode_end_text: dc.b 'MODE end FF8E21 readback (STE=0): ',0
summary_text: dc.b 'SUMMARY automatic failure groups: ',0
summary_scope: dc.b 'SUMMARY input controls need exercise; audibility and scanout remain OBSERVATION ONLY. No whole-machine certification.',13,10,0
	even
	section bss
palette_bad: ds.l 1
