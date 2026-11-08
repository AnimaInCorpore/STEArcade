; Darklord's Mega STE isolation test. 68000 only, no game ROMs.
; See docs/megaste-diagnostic.md. Files are checkpoints; no disk I/O in the raw-input phase.
	include "dltest_ikbd.i"
KEY_ESC = 1
	ifd QUICK
SECONDS = 3
	else
SECONDS = 30
	endc
stage_begin macro
	movem.l d0-d2,-(sp)
	move.w #\1,d0
	move.w #\2,d1
	move.w #\3,d2
	bsr progress_begin
	movem.l (sp)+,d0-d2
	endm
	section text
start:
	ifd BORDER_PAD
	bra.w .entry
	dcb.b BORDER_PAD,0
.entry:
	endc
	move.l 4(sp),a0
	move.l (a0),basepage_start
	move.l 4(a0),basepage_end
	clr.l -(sp)
	move.w #$20,-(sp)
	trap #1
	addq.l #6,sp
	move.l d0,old_ssp
	lea report,a5
	lea title,a0
	bsr log_text
	move.l $5a0.w,d0
	beq .machine_done
	move.l d0,a0
.cookie:
	move.l (a0)+,d0
	beq .machine_done
	move.l (a0)+,d1
	cmp.l #'_MCH',d0
	bne .cookie
	move.l d1,machine
.machine_done:
	lea mch_text,a0
	bsr log_text
	move.l machine,d0
	bsr log_hex
	lea tos_text,a0
	bsr log_text
	move.l $4f2.w,a0
	moveq #0,d0
	move.w 2(a0),d0
	bsr log_hex
	bsr log_eol
	cmp.l #$10010,machine
	bne .not_mega
	st is_mega
	move.b $ffff8e21.w,old_speed
.not_mega:
	lea speed_text,a0
	bsr log_text
	moveq #0,d0
	move.b old_speed,d0
	bsr log_hex
	bsr log_eol
	bsr save_report
	; Reject monochrome/unsupported hardware before touching STE display or Blitter registers.
	move.w #4,-(sp)
	trap #14
	addq.l #2,sp
	move.w d0,old_res
	cmp.w #2,d0
	beq unsupported
	move.l machine,d0
	and.l #$ffff0000,d0
	cmp.l #$10000,d0
	bne unsupported
	; Physical and logical screens are kept separately; never write the desktop buffer.
	move.w #2,-(sp)
	trap #14
	addq.l #2,sp
	move.l d0,old_phys
	move.w #3,-(sp)
	trap #14
	addq.l #2,sp
	move.l d0,old_log
	move.b $ffff820a.w,old_sync
	move.b $ffff820f.w,old_line
	move.b $ffff8265.w,old_fine
	movem.l $ffff8240.w,d0-d7
	movem.l d0-d7,old_palette
	movem.l $ffff8a20.w,d0-d6
	movem.l d0-d6,old_blitter
	move.w $ffff8a3c.w,old_blitter+28
	bclr #7,old_blitter+28
	bsr system_inventory
	bsr install_crash
	; Align our private screen and a source straddling a 64 KiB boundary.
	lea screen_space+256,a0
	move.l a0,d0
	and.l #$ffffff00,d0
	move.l d0,screen
	lea source_space+$10000,a0
	move.l a0,d0
	and.l #$ffff0000,d0
	subq.l #2,d0
	move.l d0,source
	move.l d0,a0
	move.w #$ffff,(a0)+
	clr.w (a0)+
	move.w #$ffff,(a0)+
	clr.w (a0)+
	ifd BORDER_ONLY
	bra border_only
	endc
	ifd SETUP_ONLY
	bra setup_only
	endc
	; Baseline BIOS key path, before replacing the ACIA handler.
	lea bios_text,a0
	bsr log_text
	bsr save_report
	lea bios_prompt,a0
	bsr print
	stage_begin 0,SECONDS,1
	move.l $4ba.w,d7
	add.l #SECONDS*200,d7
.bios:
	move.w #2,-(sp)
	move.w #1,-(sp)
	trap #13
	addq.l #4,sp
	tst.l d0
	beq .bios_time
	move.w #2,-(sp)
	move.w #2,-(sp)
	trap #13
	addq.l #4,sp
	addq.l #1,bios_count
	swap d0
	and.w #$7f,d0
	lea bios_seen,a0
	st (a0,d0.w)
.bios_time:
	bsr progress_update
	cmp.l $4ba.w,d7
	bhi .bios
	bsr progress_end
	lea bios_result,a0
	bsr log_text
	move.l bios_count,d0
	bsr log_hex
	bsr log_eol
	lea bios_seen,a4
	bsr log_keys
	bsr save_report
	clr.w mode_index
.mode:
	lea mode_text,a0
	bsr log_text
	moveq #0,d0
	move.w mode_index,d0
	bsr log_hex
	bsr log_eol
	bsr set_speed
	lea register_text,a0
	bsr log_text
	moveq #0,d0
	tst.b is_mega
	beq .reg
	move.b $ffff8e21.w,d0
.reg:
	bsr log_hex
	bsr log_eol
	bsr save_report
	bsr cpu_test
	bsr ram_extended
	bsr file_test
	bsr setup_test
	bsr matrix_test
	lea screen_text,a0
	bsr log_text
	bsr save_report
	bsr open_screen
	bsr palette_test
	bsr draw_test
	lea raw_begin_text,a0
	bsr log_text
	bsr save_report
	lea screen_labels,a0
	bsr print
	move.w mode_index,d0
	add.w #'0',d0
	move.w d0,-(sp)
	move.w #2,-(sp)
	trap #1
	addq.l #4,sp
	bsr raw_test
	bsr save_bmp
	bsr close_screen
	bsr scene_test
	bsr sound_test
	bsr border_test
	bsr log_results
	bsr mode_validate
	bsr save_report
	tst.b is_mega
	beq border_only_finish
	addq.w #1,mode_index
	cmp.w #3,mode_index
	blo .mode
border_only_finish:
.finished:
	bsr restore_vectors
	movem.l old_blitter,d0-d6
	movem.l d0-d6,$ffff8a20.w
	move.w old_blitter+28,$ffff8a3c.w
	tst.b is_mega
	beq .done
	move.b old_speed,$ffff8e21.w
.done:
	bsr summary
	lea done_text,a0
	bsr log_text
	bsr save_report
	lea done_prompt,a0
	tst.b save_failed
	beq .print_done
	lea save_error,a0
.print_done:
	bsr print
	bra exit
unsupported:
	lea unsupported_text,a0
	bsr log_text
	bsr save_report
exit:
	move.l old_ssp,-(sp)
	move.w #$20,-(sp)
	trap #1
	addq.l #6,sp
	clr.w -(sp)
	trap #1

	ifd SETUP_ONLY
; Focused timing investigation; the production diagnostic is unchanged.
setup_only:
	clr.w mode_index
.mode:
	lea mode_text,a0
	bsr log_text
	moveq #0,d0
	move.w mode_index,d0
	bsr log_hex
	bsr log_eol
	bsr set_speed
	bsr setup_test
	bsr mode_validate
	bsr save_report
	tst.b is_mega
	beq .done
	addq.w #1,mode_index
	cmp.w #3,mode_index
	blo .mode
.done:
	bra border_only_finish
	endc

	ifd BORDER_ONLY
border_only:
	ifd BORDER_TARGET
	move.w #BORDER_TARGET,mode_index
	else
	clr.w mode_index
	endc
.mode:
	bsr set_speed
	lea mode_text,a0
	bsr log_text
	moveq #0,d0
	move.w mode_index,d0
	bsr log_hex
	bsr log_eol
	bsr border_test
	bsr mode_validate
	bsr save_report
	ifd BORDER_TARGET
	bra .done
	endc
	tst.b is_mega
	beq .done
	addq.w #1,mode_index
	cmp.w #3,mode_index
	blo .mode
.done:
	bra border_only_finish
	endc

set_speed:
	tst.b is_mega
	beq .out
	move.w sr,-(sp)
	ori.w #$700,sr
	; Preserve all bits other than speed/cache, and flush before enabling cache.
	move.b old_speed,d0
	and.b #$fc,d0
	move.b d0,$ffff8e21.w
	move.w mode_index,d1
	lea speeds,a0
	or.b (a0,d1.w),d0
	move.b d0,$ffff8e21.w
	move.w (sp)+,sr
.out:
	rts

; Five complete write/read sweeps over ONLY the test's own 64 KiB, not all ST RAM.
ram_test:
	clr.l ram_bad
	lea patterns,a2
	moveq #4,d5
.pass:
	move.w (a2)+,d4
	lea ram_space,a0
	move.w #32767,d3
.fill:
	move.w d3,d0
	eor.w d4,d0
	move.w d0,(a0)+
	dbf d3,.fill
	lea ram_space,a0
	move.w #32767,d3
.check:
	move.w d3,d0
	eor.w d4,d0
	cmp.w (a0)+,d0
	beq .ok
	addq.l #1,ram_bad
.ok:
	dbf d3,.check
	dbf d5,.pass
	rts

; Intentional ILLEGAL: verify exception delivery/return at the selected CPU mode.
exception_test:
	clr.l trap_count
	move.l $10.w,old_illegal
	move.l #illegal_handler,$10.w
	illegal
	move.l old_illegal,$10.w
	rts
illegal_handler:
	addq.l #1,trap_count
	move.l 2(sp),trap_pc
	addq.l #2,2(sp)
	rte

open_screen:
	bsr progress_hide
	clr.w -(sp)
	move.l screen,-(sp)
	move.l screen,-(sp)
	move.w #5,-(sp)
	trap #14
	lea 12(sp),sp
	move.b #2,$ffff820a.w
	clr.b $ffff820f.w
	clr.b $ffff8265.w
	lea test_palette,a0
	movem.l (a0),d0-d7
	movem.l d0-d7,$ffff8240.w
	move.w #37,-(sp)
	trap #14
	addq.l #2,sp
	rts
close_screen:
	bsr progress_hide
	move.w old_res,-(sp)
	move.l old_phys,-(sp)
	move.l old_log,-(sp)
	move.w #5,-(sp)
	trap #14
	lea 12(sp),sp
	move.b old_sync,$ffff820a.w
	move.b old_line,$ffff820f.w
	move.b old_fine,$ffff8265.w
	movem.l old_palette,d0-d7
	movem.l d0-d7,$ffff8240.w
	rts

; 16 sparse 16-pixel shapes at every horizontal shift. Opaque end masks, HOP2/OP3,
; four planes per pass, <=16 bus accesses. Independently compute expected pixels.
; The same source crosses a 64 KiB boundary on every pass.
draw_test:
	stage_begin 7,SECONDS,1
	move.w #200,capture_height
	move.l source,a0
	move.l #$ffff0000,(a0)+
	move.l #$ffff0000,(a0)+
	clr.b capture_requested
	clr.l input_bytes
	clr.w input_trace_count
	clr.l mouse_packets
	clr.l mouse_dx
	clr.l mouse_dy
	clr.b mouse_buttons
	clr.b mouse_pending
	lea key_down_count,a0
	move.w #127,d0
.clear_counts:
	clr.l (a0)+
	dbf d0,.clear_counts
	move.l #'INPT',bmp_name
	clr.l blit_bad
	move.l screen,a0
	lea expected,a1
	move.w #15999,d7
.background:
	move.w d7,d0
	and.w #$1111,d0
	move.w d0,(a0)+
	move.w d0,(a1)+
	dbf d7,.background
	move.w #2,$ffff8a20.w
	move.w #2,$ffff8a22.w
	move.w #8,$ffff8a2e.w
	move.w #2,$ffff8a30.w
	move.w #$ffff,$ffff8a2a.w
	move.b #2,$ffff8a3a.w
	move.b #3,$ffff8a3b.w
	clr.b $ffff8a3d.w
	moveq #0,d6
.shape:
	move.w d6,d0
	mulu #160*10,d0
	add.l #160*16+8*3,d0
	move.l d0,draw_offset
	moveq #7,d5
.row:
	; CPU reference uses individual pixel bits, not the Blitter pass masks.
	moveq #15,d4
.pixel:
	move.w #$bded,d0
	btst d4,d0
	beq .next_pixel
	moveq #15,d1
	sub.w d4,d1
	add.w d6,d1
	move.w d1,d2
	lsr.w #4,d2
	lsl.w #3,d2
	and.w #15,d1
	eor.w #15,d1
	moveq #1,d0
	lsl.w d1,d0
	lea expected,a0
	add.l draw_offset,a0
	add.w d2,a0
	or.w d0,(a0)
	or.w d0,4(a0)
	not.w d0
	and.w d0,2(a0)
	and.w d0,6(a0)
.next_pixel:
	dbf d4,.pixel
	move.w #$bded,d4
	lsr.w d6,d4
	move.l screen,a0
	add.l draw_offset,a0
	bsr blit_piece
	tst.w d6
	beq .next_row
	moveq #16,d0
	sub.w d6,d0
	move.w #$bded,d4
	lsl.w d0,d4
	move.l screen,a0
	add.l draw_offset,a0
	addq.l #8,a0
	bsr blit_piece
.next_row:
	add.l #160,draw_offset
	dbf d5,.row
	addq.w #1,d6
	cmp.w #16,d6
	blo .shape
	; Compare all 32000 bytes, including the untouched background between shapes.
	move.l screen,a0
	lea expected,a1
	move.w #15999,d7
.compare:
	move.w (a1)+,d0
	cmp.w (a0)+,d0
	beq .equal
	addq.l #1,blit_bad
.equal:
	dbf d7,.compare
	rts
blit_piece:
	move.l source,$ffff8a24.w
	move.w d4,$ffff8a28.w
	move.w d4,$ffff8a2c.w
	move.l a0,$ffff8a32.w
	move.w #1,$ffff8a36.w
	move.w #4,$ffff8a38.w
	; Starting HOG resumes at the following instruction once this short pass completes.
	move.b #$c0,$ffff8a3c.w
	nop
	rts

; Same byte framer as the games. Keep TOS VBL/200Hz alive, replace only ACIA ISR.
; No BIOS/GEMDOS calls until its vector and MFP bits have been restored.
raw_test:
	stage_begin 7,SECONDS,1
	move.w #200,capture_height
	lea key_down,a0
	move.w #255,d0
.clear:
	clr.b (a0)+
	dbf d0,.clear
	clr.l joy_seen
	clr.l raw_count
	clr.l overrun_count
	clr.b quit_flag
	clr.b ikbd_state
	clr.b ikbd_lost
	clr.b ikbd_esc
	move.w sr,saved_sr
	ori.w #$700,sr
	move.l $118.w,old_acia
	move.b $fffffa09.w,old_ierb
	move.b $fffffa15.w,old_imrb
	move.l #acia_isr,$118.w
	bset #6,$fffffa09.w
	bset #6,$fffffa15.w
	move.w saved_sr,sr
	moveq #$12,d0
	bsr send_ikbd
	moveq #$14,d0
	bsr send_ikbd
	moveq #8,d0
	bsr send_ikbd
	move.l source,matrix_src
	move.l #dest_space+160*284,matrix_dst
	move.w #1,matrix_profile
	clr.l source_cursor
	bsr invalidate_piece_cache
	lea border_piece,a4
	move.w #$ffff,$ffff8a2a.w
	move.w #$0203,$ffff8a3a.w
	move.l matrix_dst,a0
	moveq #31,d0
.clear_load:
	clr.l (a0)+
	dbf d0,.clear_load
	move.l $4ba.w,d7
	move.l d7,raw_start
	move.l $466.w,raw_vbl_start
	add.l #SECONDS*200,d7
	move.l d7,progress_deadline
	clr.l progress_next
.loop:
	bsr progress_update
	bsr execute_piece
	cmp.b #1,capture_requested
	bne .captured
	bsr capture_snapshot
.captured:
	; Indicators along the bottom: coin, start, arrows, fire; filled on press.
	lea indicator_keys,a2
	move.l screen,a0
	add.l #160*190+8*2,a0
	moveq #7,d3
.indicator:
	moveq #0,d0
	move.b (a2)+,d0
	lea key_down,a1
	tst.b (a1,d0.w)
	beq .off
	move.w #$ffff,(a0)
.off:
	addq.l #8,a0
	dbf d3,.indicator
	cmp.l $4ba.w,d7
	bls .stop
	tst.b quit_flag
	beq .loop
.stop:
	move.l $4ba.w,d0
	sub.l raw_start,d0
	move.l d0,raw_ticks
	move.l $466.w,d0
	sub.l raw_vbl_start,d0
	move.l d0,raw_vbls
	cmp.b #2,capture_requested
	beq .have_capture
	bsr capture_snapshot
.have_capture:
	bsr progress_end
	bsr raw_load_check
	moveq #$1a,d0
	bsr send_ikbd
	moveq #8,d0
	bsr send_ikbd
	; Let pending replies drain through our handler before TOS owns the byte stream.
	move.l $4ba.w,d7
	addq.l #8,d7
.drain:
	cmp.l $4ba.w,d7
	bhi .drain
	ori.w #$700,sr
	move.l old_acia,$118.w
	move.b old_ierb,$fffffa09.w
	move.b old_imrb,$fffffa15.w
	bclr #6,$fffffa11.w
	move.w saved_sr,sr
	rts
send_ikbd:
	move.l $4ba.w,d1
	add.l #200,d1
.wait:
	btst #1,$fffffc00.w
	bne .send
	cmp.l $4ba.w,d1
	bhi .wait
	addq.l #1,tx_timeout
	rts
.send:
	move.b d0,$fffffc02.w
	rts
acia_isr:
	movem.l d0-d2/a0,-(sp)
	btst #5,$fffffc00.w
	beq .again
	addq.l #1,overrun_count
.again:
	ikbd_byte
	addq.l #1,raw_count
	cmp.b #$44,d2
	bne .not_capture
	move.b #1,capture_requested
.not_capture:
	lea key_down_count,a0
	tst.b d2
	bpl .down_count
	lea key_up_count,a0
.down_count:
	add.w d1,d1
	addq.w #1,(a0,d1.w)
	lsr.w #1,d1
	lea key_down,a0
	tst.b d2
	bpl .key
	lea key_up,a0
.key:
	st (a0,d1.w)
	bra .again
.packet_byte:
	clr.b ikbd_state
	lea joy_seen,a0
	subq.w #1,d0
	or.b d1,(a0,d0.w)
	bra .again
.done:
	bclr #6,$fffffa11.w
	movem.l (sp)+,d0-d2/a0
	rte

log_results:
	lea raw_load_text,a0
	bsr log_text
	move.l raw_load_bad,d0
	bsr log_hex
	bsr log_eol
	move.l ram_bad,d0
	or.l blit_bad,d0
	or.l tx_timeout,d0
	beq .errors_ok
	addq.l #1,auto_failures
.errors_ok:
	cmp.l #1,trap_count
	beq .trap_ok
	addq.l #1,auto_failures
.trap_ok:
	bsr input_summary
	lea timing_text,a0
	bsr log_text
	move.l raw_ticks,d0
	bsr log_hex
	move.l raw_vbls,d0
	bsr log_hex
	bsr log_eol
	lea ram_text,a0
	bsr log_text
	move.l ram_bad,d0
	bsr log_hex
	lea blit_text,a0
	bsr log_text
	move.l blit_bad,d0
	bsr log_hex
	lea trap_text,a0
	bsr log_text
	move.l trap_count,d0
	bsr log_hex
	bsr log_eol
	lea raw_text,a0
	bsr log_text
	move.l raw_count,d0
	bsr log_hex
	lea overrun_text,a0
	bsr log_text
	move.l overrun_count,d0
	bsr log_hex
	lea tx_text,a0
	bsr log_text
	move.l tx_timeout,d0
	bsr log_hex
	bsr log_eol
	lea key_down,a4
	bsr log_keys
	lea releases_text,a0
	bsr log_text
	lea key_up,a4
	bsr log_keys
	lea joy_text,a0
	bsr log_text
	moveq #0,d0
	move.w joy_seen,d0
	bsr log_hex
	bsr log_eol
	rts
log_keys:
	lea keys_text,a0
	bsr log_text
	moveq #0,d6
.key:
	tst.b (a4,d6.w)
	beq .next
	move.l d6,d0
	bsr log_hex
.next:
	addq.w #1,d6
	cmp.w #128,d6
	blo .key
	bra log_eol
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
	move.l a5,report_checkpoint
	movem.l d0-d7/a0-a6,-(sp)
	clr.w -(sp)
	pea filename
	move.w #$3c,-(sp)
	trap #1
	addq.l #8,sp
	tst.l d0
	bmi .fail
	move.w d0,d6
	move.l a5,d7
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
print:
	move.l a0,-(sp)
	move.w #9,-(sp)
	trap #1
	addq.l #6,sp
	rts

	section data
speeds: dc.b 0,2,3
indicator_keys: dc.b $06,$02,$48,$50,$4b,$4d,$39,$1d
	even
patterns: dc.w 0,$ffff,$5555,$aaaa,$1234
test_palette: dc.w $000,$111,$222,$333,$444,$555,$666,$777,$700,$070,$007,$770,$707,$077,$731,$157
filename: dc.b 'DLTEST.TXT',0
title: dc.b 'DLTEST 4 - STEArcade Mega STE isolation',13,10,0
mch_text: dc.b '_MCH: ',0
tos_text: dc.b 'TOS: ',0
speed_text: dc.b 'Original FF8E21 (Mega STE only): ',0
bios_text: dc.b 'BEGIN BIOS keyboard phase',13,10,0
bios_prompt: dc.b 27,'E','DLTEST: keyboard test (30 seconds)',13,10,'Tap 5, 1, arrows, Space, Control.',13,10,'Then watch the patterned screen.',13,10,'Repeat keys and move/fire joystick',13,10,'during EACH screen (30 seconds).',13,10,'Three screens on a Mega STE:',13,10,'8 MHz; 16 MHz; 16 MHz + cache.',13,10,0
bios_result: dc.b 'BIOS events: ',0
mode_text: dc.b 'BEGIN mode (0=8MHz,1=16MHz,2=16MHz/cache): ',0
register_text: dc.b 'FF8E21 readback (STE=0): ',0
screen_text: dc.b 'BEGIN screen opening / checked Blitter drawing',13,10,0
raw_begin_text: dc.b 'BEGIN raw input / visual observation',13,10,0
screen_labels: dc.b 27,'Y',32,32,'DLTEST: 5,1,arrows,Space,Ctrl + joystick',13,10,'Mode 0=8MHz  1=16MHz  2=16MHz/cache',13,10,'F10=capture. Current mode: ',0
ram_text: dc.b 'RAM mismatched words: ',0
blit_text: dc.b 'Blitter mismatched words: ',0
trap_text: dc.b 'ILLEGAL caught (expected 1): ',0
raw_text: dc.b 'Raw key events: ',0
timing_text: dc.b 'Raw phase elapsed 200Hz ticks / VBLs: ',0
overrun_text: dc.b 'ACIA overrun observations: ',0
tx_text: dc.b 'IKBD transmit timeouts: ',0
keys_text: dc.b 'Scancodes seen: ',0
releases_text: dc.b 'Releases: ',0
joy_text: dc.b 'Joystick 0/1 OR masks (UDLR/fire=01/02/04/08/80): ',0
done_text: dc.b 'DONE - original display and CPU settings restored.',13,10,0
done_prompt: dc.b 'DLTEST finished. Return DLTEST.TXT.',13,10,0
save_error: dc.b 'DLTEST: REPORT WRITE FAILED.',13,10,'Use a writable folder and rerun.',13,10,0
unsupported_text: dc.b 'SKIP: colour STE / Mega STE required. No hardware tests run.',13,10,0
eol: dc.b 13,10,0
digits: dc.b '0123456789ABCDEF'
	even
	section bss
old_ssp: ds.l 1
machine: ds.l 1
old_phys: ds.l 1
old_log: ds.l 1
screen: ds.l 1
source: ds.l 1
old_illegal: ds.l 1
trap_pc: ds.l 1
trap_count: ds.l 1
old_acia: ds.l 1
bios_count: ds.l 1
raw_count: ds.l 1
overrun_count: ds.l 1
tx_timeout: ds.l 1
ram_bad: ds.l 1
blit_bad: ds.l 1
draw_offset: ds.l 1
old_palette: ds.l 8
old_blitter: ds.w 15
raw_start: ds.l 1
raw_vbl_start: ds.l 1
raw_ticks: ds.l 1
raw_vbls: ds.l 1
old_res: ds.w 1
mode_index: ds.w 1
saved_sr: ds.w 1
joy_seen: ds.l 1
old_speed: ds.b 1
is_mega: ds.b 1
old_sync: ds.b 1
old_line: ds.b 1
old_fine: ds.b 1
old_ierb: ds.b 1
old_imrb: ds.b 1
quit_flag: ds.b 1
save_failed: ds.b 1
	ikbd_vars
bios_seen: ds.b 128
key_down: ds.b 128
key_up: ds.b 128
	even
basepage_start: ds.l 1
basepage_end: ds.l 1
report: ds.b 131072
ram_space: ds.b 131072
source_space: ds.b 131080
expected: ds.b 32000
screen_space: ds.b 32256

	include "dltest_extra.s"

	include "dltest_setup.s"

	include "dltest_system.s"

	include "dltest_border.s"

	include "dltest_crash.s"

	include "dltest_video.s"

	include "dltest_progress.s"

	section text
raw_load_check:
.wait:
	btst #7,$ffff8a3c.w
	bne .wait
	move.l matrix_dst,a0
	lea setup_expected,a1
	moveq #7,d4
	clr.l raw_load_bad
.compare:
	move.w (a0)+,d0
	cmp.w (a1)+,d0
	beq .equal
	addq.l #1,raw_load_bad
.equal:
	dbf d4,.compare
	tst.l raw_load_bad
	beq .ok
	addq.l #1,auto_failures
.ok:
	rts
	section bss
raw_load_bad: ds.l 1

	section data
raw_load_text: dc.b 'RAW concurrent short-HOG destination badwords: ',0
	even
