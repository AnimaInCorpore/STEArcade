; Focused Mega STE timing probe. Built by blittime.py; no ROMs/assets needed.
; All graphics tests use HOP 2 / OP 3, short HOG transfers, private ST RAM.
	section text
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
.cookie:
	move.l (a0)+,d0
	beq unsupported
	move.l (a0)+,d1
	cmp.l #'_MCH',d0
	bne .cookie
	cmp.l #$10010,d1
	bne unsupported
	move.b $ffff8e21.w,old_speed
	move.l $4f2.w,a0
	moveq #0,d0
	move.w 2(a0),d0
	bsr log_hex
	moveq #0,d0
	move.b old_speed,d0
	bsr log_hex
	bsr log_eol
	; Preserve old results. The operator uses a fresh directory for each run.
	clr.w -(sp)
	pea filename
	move.w #$3d,-(sp)
	trap #1
	addq.l #8,sp
	tst.l d0
	bmi .new_file
	move.w d0,-(sp)
	move.w #$3e,-(sp)
	trap #1
	addq.l #4,sp
	lea exists_text,a0
	bra quit_message
.new_file:
	tst.b $fffffa19.w
	bne timer_busy
	btst #5,$fffffa0b.w
	bne timer_busy
	btst #5,$fffffa0f.w
	bne timer_busy
	btst #7,$ffff8a3c.w
	bne blitter_busy
	; The timer vector base need not be TOS's usual $40.
	moveq #0,d0
	move.b $fffffa17.w,d0
	and.w #$f0,d0
	add.w #13,d0
	lsl.w #2,d0
	move.l d0,ta_vector
	move.l d0,a0
	move.l (a0),old_ta
	sub.w #32,d0
	move.l d0,tc_vector
	move.l d0,a0
	move.l (a0),old_tc
	move.l $68.w,old_hbl
	move.l $70.w,old_vbl
	move.b $fffffa07.w,old_iera
	move.b $fffffa13.w,old_imra
	move.b $fffffa15.w,old_imrb
	move.b $fffffa1f.w,old_tadr
	movem.l $ffff8a20.w,d0-d6
	movem.l d0-d6,old_blitter
	move.w $ffff8a3c.w,old_blitter+28
	ori.w #$700,sr
	move.l ta_vector,a0
	move.l #timer_a,(a0)
	bclr #5,$fffffa0b.w
	bclr #5,$fffffa0f.w
	clr.l overflows
	clr.b $fffffa1f.w	; reload 256, prescale 200: 81.380208 us/count
	bset #5,$fffffa07.w
	bset #5,$fffffa13.w
	move.b #7,$fffffa19.w
	move.w #$2300,sr
	lea source,a0
	move.w #8191,d7
.fill_source:
	move.l #$a55a5aa5,(a0)+
	move.l #$0f0ff0f0,(a0)+
	dbf d7,.fill_source
	; Entire selected 64 KiB destination bank is private, even if an RMW fails.
	lea destination+65536,a0
	move.l a0,d0
	and.l #$ffff0000,d0
	add.l #$4000,d0
	move.l d0,dest_base
	bsr save_report
	tst.b save_failed
	bne finish
	move.l $4ba.w,run_start
	clr.w mode
.mode:
	bsr set_speed
	bsr calibrate
	clr.w repetition
.repeat:
	clr.w case_id
.case:
	move.w case_id,d0
	mulu #12,d0
	lea cases,a0
	adda.l d0,a0
	move.l a0,descriptor
	bsr show_progress
	bsr prepare
	bsr run_case
	bsr check_output
	bsr log_case
	bsr save_report
	tst.b save_failed
	bne finish
	addq.w #1,completed
	addq.w #1,case_id
	cmp.w #CASE_COUNT,case_id
	blo .case
	addq.w #1,repetition
	cmp.w #REPEATS,repetition
	blo .repeat
	addq.w #1,mode
	cmp.w #3,mode
	blo .mode
finish:
	ori.w #$700,sr
	clr.b $fffffa19.w
	bclr #5,$fffffa13.w
	bclr #5,$fffffa07.w
	bclr #5,$fffffa0b.w
	bclr #5,$fffffa0f.w
	move.l ta_vector,a0
	move.l old_ta,(a0)
	move.b old_tadr,$fffffa1f.w
	move.b old_iera,$fffffa07.w
	move.b old_imra,$fffffa13.w
	movem.l old_blitter,d0-d6
	movem.l d0-d6,$ffff8a20.w
	move.w old_blitter+28,$ffff8a3c.w
	move.b old_speed,$ffff8e21.w
	move.w #$2300,sr
	lea done,a0
	bsr log_text
	move.l total_bad,d0
	bsr log_hex
	bsr log_eol
	bsr save_report
	lea done,a0
	tst.b save_failed
	beq quit_message
	lea disk_error,a0
	bra quit_message
unsupported:
	lea unsupported_text,a0
	bra quit_message
timer_busy:
	lea timer_text,a0
	bra skip_message
blitter_busy:
	lea blitter_text,a0
skip_message:
	move.l a0,a4
	bsr log_text
	bsr save_report
	move.l a4,a0
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

set_speed:
	move.w sr,-(sp)
	ori.w #$700,sr
	move.b old_speed,d0
	and.b #$fc,d0
	move.b d0,$ffff8e21.w
	move.w mode,d1
	lea speeds,a0
	or.b (a0,d1.w),d0
	move.b d0,$ffff8e21.w
	move.w (sp)+,sr
	rts

; Timer A overflow (48 Hz). It adds no Blitter writes or cache invalidation.
timer_a:
	addq.l #1,overflows
	bclr #5,$fffffa0f.w
	rte
minimal_tc:
	addq.l #1,$4ba.w
	bclr #5,$fffffa11.w
	rte
minimal_vbl:
	addq.l #1,$466.w
	rte
minimal_hbl:
	rte

; Atomic extended free-running count. A pending rollover is included before its
; ISR runs. Re-read the counter after detecting pending, avoiding a wrap race.
; d6 is the result; every other kernel register and the incoming SR are saved.
stamp:
	move.w sr,-(sp)
	ori.w #$700,sr
	movem.l d0-d1,-(sp)
	move.l overflows,d6
	moveq #0,d0
	move.b $fffffa1f.w,d0
	btst #5,$fffffa0b.w
	beq .phase
	addq.l #1,d6
	move.b $fffffa1f.w,d0
.phase:
	lsl.l #8,d6
	neg.b d0
	and.l #255,d0
	add.l d0,d6
	movem.l (sp)+,d0-d1
	move.w (sp)+,sr
	rts

; One-second independent-clock cross-check in each CPU mode, outside all kernels.
calibrate:
	move.l $4ba.w,start_tos
	move.l $466.w,start_vbl
	bsr stamp
	move.l d6,start_count
	move.l start_tos,d7
	add.l #200,d7
.wait:
	cmp.l $4ba.w,d7
	bhi .wait
	bsr stamp
	sub.l start_count,d6
	lea calibration_text,a0
	bsr log_text
	moveq #0,d0
	move.w mode,d0
	bsr log_hex
	move.l d6,d0
	bsr log_hex
	move.l $4ba.w,d0
	sub.l start_tos,d0
	bsr log_hex
	move.l $466.w,d0
	sub.l start_vbl,d0
	bsr log_hex
	bsr log_eol
	bsr save_report
	rts

prepare:
	lea destination,a0
	move.w #32767,d7
.clear:
	move.l #$33333333,(a0)+
	dbf d7,.clear
	lea expected,a0
	move.w #127,d7
.ref_clear:
	move.l #$33333333,(a0)+
	dbf d7,.ref_clear
	clr.w $ffff8a20.w
	move.w #2,$ffff8a22.w
	move.w #$017b,$ffff8a28.w
	move.w #$ffff,$ffff8a2a.w
	move.w #$da00,$ffff8a2c.w
	move.w #8,$ffff8a2e.w
	move.w #-6,$ffff8a30.w
	move.w #2,$ffff8a36.w
	move.w #$0203,$ffff8a3a.w
	move.w #$4047,$ffff8a3c.w
	move.l descriptor,a0
	cmp.w #5,2(a0)
	bne .masks_ready
	move.w #$ffff,$ffff8a28.w
	move.w #$ffff,$ffff8a2c.w
	move.w #2,$ffff8a20.w
	clr.b $ffff8a3d.w
.masks_ready:
	cmp.w #6,2(a0)
	bhs .done
	; Independent CPU shifter/mask painter: all planes and both alternating slots.
	move.w 4(a0),d7
	subq.w #1,d7
	lea expected+128,a1
	lea expected+256,a2
	lea source,a3
.row:
	move.w (a3)+,d0
	move.l descriptor,a4
	cmp.w #5,2(a4)
	bne .shifted
	move.w (a3)+,d1
	bra .copy_row
.shifted:
	move.w d0,d1
	lsr.w #7,d0
	lsl.w #8,d1
	add.w d1,d1
	move.w #$017b,d2
	move.w #$da00,d3
	and.w d2,d0
	and.w d3,d1
	not.w d2
	not.w d3
	bra .paint_row
.copy_row:
	moveq #0,d2
	moveq #0,d3
.paint_row:
	and.w d2,(a1)
	or.w d0,(a1)
	and.w d3,8(a1)
	or.w d1,8(a1)
	and.w d2,(a2)
	or.w d0,(a2)
	and.w d3,8(a2)
	or.w d1,8(a2)
	addq.l #2,a1
	addq.l #2,a2
	dbf d7,.row
.done:
	rts

run_case:
	movem.l d0-d7/a0-a6,-(sp)
	move.l descriptor,a0
	move.w 0(a0),d0
	beq .normal
	ori.w #$700,sr
	move.l tc_vector,a1
	move.l #minimal_tc,(a1)
	move.l #minimal_vbl,$70.w
	move.l #minimal_hbl,$68.w
	move.b #$20,$fffffa13.w
	move.b #$20,$fffffa15.w
	move.w #$2300,sr
.normal:
	move.w 4(a0),d1
	move.l 8(a0),a5
	lea source,a0
	lea $ffff8a24.w,a1
	lea $ffff8a32.w,a2
	lea $ffff8a38.w,a3
	lea $ffff8a3c.w,a4
	move.l dest_base,d0
	move.w #$c0,d2
	move.l descriptor,a6
	cmp.w #3,2(a6)
	bne .not_word
	move.w #$c047,d2
.not_word:
	cmp.w #6,2(a6)
	blo .blit
	move.w #$40,d2
	cmp.w #7,2(a6)
	bne .blit
	lea scratch,a1
	lea scratch+4,a2
	lea scratch+8,a3
	lea scratch+12,a4
.blit:
	move.w d1,d3
	add.w d3,d3
	move.w #128,d4
	sub.w d3,d4
	neg.w d3
	sub.w #128,d3
	move.w #BATCHES-1,d5
	move.b $ffff8e21.w,speed_before
	move.l $4ba.w,start_tos
	move.l $466.w,start_vbl
	bsr stamp
	move.l d6,start_count
	jsr (a5)
.fence:
	btst #7,$ffff8a3c.w
	bne .fence
	bsr stamp
	sub.l start_count,d6
	move.l d6,elapsed_count
	move.l $4ba.w,d6
	sub.l start_tos,d6
	move.l d6,elapsed_tos
	move.l $466.w,d6
	sub.l start_vbl,d6
	move.l d6,elapsed_vbl
	move.b $ffff8e21.w,speed_after
	; Restore TOS handlers and masks BEFORE GEMDOS, console, or report I/O.
	ori.w #$700,sr
	move.l tc_vector,a0
	move.l old_tc,(a0)
	move.l old_hbl,$68.w
	move.l old_vbl,$70.w
	move.b old_imra,d0
	or.b #$20,d0
	move.b d0,$fffffa13.w
	move.b old_imrb,$fffffa15.w
	move.w #$2300,sr
	movem.l (sp)+,d0-d7/a0-a6
	rts

check_output:
	clr.l bad_words
	clr.w first_expected
	clr.w first_actual
	move.l #-1,first_offset
	move.l dest_base,d0
	sub.l #128,d0
	move.l d0,compare_start
	lea destination,a0
	move.l d0,d7
	sub.l a0,d7
	lsr.l #1,d7
	subq.w #1,d7
.before:
	move.w (a0)+,d1
	move.w #$3333,d0
	bsr compare_word
	dbf d7,.before
	lea expected,a1
	move.w #255,d7
.picture:
	move.w (a1)+,d0
	move.w (a0)+,d1
	bsr compare_word
	dbf d7,.picture
	move.l #destination+131072,d7
	sub.l a0,d7
	lsr.l #1,d7
	subq.w #1,d7
.after:
	move.w (a0)+,d1
	move.w #$3333,d0
	bsr compare_word
	dbf d7,.after
	move.l descriptor,a0
	cmp.w #7,2(a0)
	bne .done
	lea scratch,a0
	move.l (a0),d0
	cmp.l #source,d0
	beq .scratch_dst
	addq.l #1,bad_words
.scratch_dst:
	move.l 4(a0),d0
	move.l dest_base,d1
	eor.l #128,d1
	cmp.l d1,d0
	beq .scratch_y
	addq.l #1,bad_words
.scratch_y:
	move.w 8(a0),d0
	move.l descriptor,a1
	cmp.w 4(a1),d0
	beq .scratch_control
	addq.l #1,bad_words
.scratch_control:
	cmp.b #$40,12(a0)
	beq .done
	addq.l #1,bad_words
.done:
	move.l bad_words,d0
	add.l d0,total_bad
	rts
compare_word:
	cmp.w d0,d1
	beq .out
	addq.l #1,bad_words
	cmp.l #-1,first_offset
	bne .out
	move.l a0,d2
	sub.l #destination+2,d2
	move.l d2,first_offset
	move.w d0,first_expected
	move.w d1,first_actual
.out:
	rts

log_case:
	move.l report_end,a5
	lea case_text,a0
	bsr log_text
	moveq #0,d0
	move.w mode,d0
	bsr log_hex
	move.l descriptor,a4
	move.w (a4),d0
	bsr log_hex
	move.w repetition,d0
	bsr log_hex
	move.w case_id,d0
	bsr log_hex
	move.w 2(a4),d0
	bsr log_hex
	move.w 4(a4),d0
	bsr log_hex
	move.w 6(a4),d0
	bsr log_hex
	move.l #BATCHES*1024,d0
	bsr log_hex
	move.l elapsed_count,d0
	bsr log_hex
	move.l elapsed_tos,d0
	bsr log_hex
	move.l elapsed_vbl,d0
	bsr log_hex
	move.l bad_words,d0
	bsr log_hex
	move.l first_offset,d0
	bsr log_hex
	moveq #0,d0
	move.w first_expected,d0
	bsr log_hex
	moveq #0,d0
	move.w first_actual,d0
	bsr log_hex
	moveq #0,d0
	move.b speed_before,d0
	bsr log_hex
	moveq #0,d0
	move.b speed_after,d0
	bsr log_hex
	move.l 8(a4),d0
	bsr log_hex
	move.l #source,d0
	bsr log_hex
	move.l dest_base,d0
	bsr log_hex
	bsr log_eol
	move.l a5,report_end
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
	move.l a5,report_end
	movem.l d0-d7/a0-a6,-(sp)
	clr.w -(sp)
	pea filename
	move.w #$3c,-(sp)
	trap #1
	addq.l #8,sp
	tst.l d0
	bmi .fail
	move.w d0,d6
	move.l report_end,d7
	sub.l #report,d7
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

show_progress:
	movem.l d0-d7/a0-a6,-(sp)
	moveq #0,d0
	move.w completed,d0
	addq.w #1,d0
	lea progress_number,a0
	bsr decimal3
	move.w mode,d0
	add.b #'0',d0
	move.b d0,progress_mode
	move.w completed,d1
	beq .print
	move.l $4ba.w,d0
	sub.l run_start,d0
	divu #200,d0
	and.l #65535,d0
	move.w #CASE_COUNT*REPEATS*3,d2
	sub.w d1,d2
	mulu d2,d0
	divu d1,d0
	and.l #65535,d0
	lea progress_eta,a0
	bsr decimal3
.print:
	pea progress
	move.w #9,-(sp)
	trap #1
	addq.l #6,sp
	movem.l (sp)+,d0-d7/a0-a6
	rts
decimal3:
	cmp.w #999,d0
	bls .fits
	move.w #999,d0
.fits:
	divu #100,d0
	add.b #'0',d0
	move.b d0,(a0)+
	clr.w d0
	swap d0
	divu #10,d0
	add.b #'0',d0
	move.b d0,(a0)+
	clr.w d0
	swap d0
	add.b #'0',d0
	move.b d0,(a0)
	rts

	include "btime_kernels.i"
	section data
speeds: dc.b 0,2,3
filename: dc.b 'BLITTIME.TXT',0
digits: dc.b '0123456789ABCDEF'
eol: dc.b 13,10,0
title: dc.b 'BLITTIME 1 - Mega STE short-pass timing',13,10
	include "btime_build.i"
	dc.b 'MFP: 2457600 Hz / 200; 12288 counts/second. All values HEX.',13,10
	dc.b 'CPU modes: 0=8MHz 1=16MHz/noCache 2=16MHz/cache.',13,10
	dc.b 'Policies: 0=TOS IRQs 1=minimal TC/VBL + Timer A.',13,10
	dc.b 'CASE mode policy repeat id kind rows nops passes mfpCounts tosTicks vbls badWords firstOffset expected actual speedBefore speedAfter kernelPC sourceAddress destinationAddress',13,10
	dc.b 'TOS version / original FF8E21: ',0
case_text: dc.b 'CASE ',0
calibration_text: dc.b 'CAL mode mfpCounts tosTicks vbls: ',0
done: dc.b 13,10,'DONE - original CPU, Blitter, timer and vectors restored. Total bad words: ',0
exists_text: dc.b 'BLITTIME.TXT exists. Please use a new empty folder.',13,10,0
unsupported_text: dc.b 'BLITTIME requires a Mega STE. No hardware settings changed.',13,10,0
timer_text: dc.b 'Timer A is active. Test skipped; no timer settings changed.',13,10,0
blitter_text: dc.b 'Blitter is active. Test skipped; no settings changed.',13,10,0
disk_error: dc.b 'Could not save BLITTIME.TXT. Original hardware settings restored.',13,10,0
progress: dc.b 27,'H','Mega STE Blitter timing - automatic, no input needed',13,10,'Test '
progress_number: dc.b '000 / '
	include "btime_total.i"
	dc.b '  Mode '
progress_mode: dc.b '0',13,10,'Estimated time remaining: '
progress_eta: dc.b '--- seconds',13,10,'Results: BLITTIME.TXT',27,'J',0
	section bss
old_ssp: ds.l 1
old_ta: ds.l 1
old_tc: ds.l 1
old_hbl: ds.l 1
old_vbl: ds.l 1
ta_vector: ds.l 1
tc_vector: ds.l 1
old_speed: ds.b 1
old_iera: ds.b 1
old_imra: ds.b 1
old_imrb: ds.b 1
old_tadr: ds.b 1
save_failed: ds.b 1
speed_before: ds.b 1
speed_after: ds.b 1
	even
old_blitter: ds.w 15
mode: ds.w 1
repetition: ds.w 1
case_id: ds.w 1
completed: ds.w 1
descriptor: ds.l 1
dest_base: ds.l 1
compare_start: ds.l 1
overflows: ds.l 1
start_count: ds.l 1
elapsed_count: ds.l 1
start_tos: ds.l 1
elapsed_tos: ds.l 1
start_vbl: ds.l 1
elapsed_vbl: ds.l 1
bad_words: ds.l 1
total_bad: ds.l 1
first_offset: ds.l 1
first_expected: ds.w 1
first_actual: ds.w 1
run_start: ds.l 1
report_end: ds.l 1
scratch: ds.b 16
source: ds.b 65536
destination: ds.b 131072
expected: ds.b 512
report: ds.b 131072
