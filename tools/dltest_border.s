; Real shared synchronized top/bottom border handlers. Timed code is unmodified.
; We test its actual behaviour at each speed/cache setting; no switch to 8MHz.
TA_DATA = 98
TA_NOPS = 84
PIC_TOP = 10
PIC_LINES = 256
BD_PALETTE = 1
DEBUG = 1
	include "dltest_borders.i"
	ifnd BORDER_SECONDS
	ifd QUICK
BORDER_SECONDS = 1
	else
BORDER_SECONDS = 3
	endc
	endc
	section text
border_test:
	stage_begin 10,BORDER_SECONDS*2,1
	lea border_begin,a0
	bsr log_text
	bsr save_report
	move.l screen,border_old_screen
	lea dest_space+256,a0
	move.l a0,d0
	and.l #$ffffff00,d0
	move.l d0,border_base
	move.l d0,screen
	bsr open_screen
	move.l border_base,a1
	lea open_image,a0
	move.w #11039,d0
.copy_image:
	move.l (a0)+,(a1)+
	dbf d0,.copy_image
	; No TOS VBL palette/cursor work while timing-sensitive handlers own the display.
	move.w sr,border_sr
	ori.w #$700,sr
	move.l $68.w,border_old_hbl
	move.l $70.w,border_old_vbl
	move.l $120.w,border_old_tb
	move.l $134.w,border_old_ta
	move.l $114.w,border_old_tc
	move.b $fffffa07.w,border_iera
	move.b $fffffa13.w,border_imra
	move.b $fffffa17.w,border_vr
	move.b $fffffa19.w,border_tacr
	move.b $fffffa1b.w,border_tbcr
	move.b $fffffa1f.w,border_tadr
	move.b $fffffa21.w,border_tbdr
	clr.b $fffffa19.w
	clr.b $fffffa1b.w
	clr.b bd_ta_state
	clr.b bd_tb_state
	clr.w bd_fallbacks
	clr.w bd_late_top
	clr.w bd_late_on
	clr.w bd_late_low
	clr.w bd_late_off
	clr.l border_vbls
	clr.l border_off_samples
	clr.l border_missed_frames
	clr.b border_off_seen
	move.l #$7fffffff,border_min_dma
	clr.l border_max_dma
	move.l #border_hbl,$68.w
	move.l #border_vbl,$70.w
	move.l #timer_a,$134.w
	move.l #timer_b,$120.w
	move.l #border_tick,$114.w
	bclr #3,$fffffa17.w
	bset #0,$fffffa07.w
	bset #5,$fffffa07.w
	bset #0,$fffffa13.w
	bset #5,$fffffa13.w
	move.w border_sr,sr
	move.w #10,progress_origin
	move.l $4ba.w,d0
	add.l #BORDER_SECONDS*400,d0
	move.l d0,progress_deadline
	clr.l progress_next
	move.l $4ba.w,d7
	add.l #BORDER_SECONDS*200,d7
.idle:
	bsr progress_update
	cmp.l $4ba.w,d7
	bhi .idle
	; A continuous stream of short masked HOG passes stresses interrupt arbitration.
	move.l source,matrix_src
	move.l #dest_space+160*284,matrix_dst
	move.w #1,matrix_profile
	clr.l source_cursor
	bsr invalidate_piece_cache
	lea border_stress_pieces,a4
	move.w #$5a5a,$ffff8a2a.w
	move.w #$0203,$ffff8a3a.w
	move.l $4ba.w,d7
	add.l #BORDER_SECONDS*200,d7
.loaded:
	bsr progress_update
	bsr execute_piece
	lea 20(a4),a4
	cmp.l #border_stress_end,a4
	blo .piece_ready
	lea border_stress_pieces,a4
.piece_ready:
	cmp.l $4ba.w,d7
	bhi .loaded
	bsr progress_end
	ori.w #$700,sr
	clr.b $fffffa19.w
	clr.b $fffffa1b.w
	move.l border_old_hbl,$68.w
	move.l border_old_vbl,$70.w
	move.l border_old_tb,$120.w
	move.l border_old_ta,$134.w
	move.l border_old_tc,$114.w
	move.b border_tadr,$fffffa1f.w
	move.b border_tbdr,$fffffa21.w
	move.b border_tacr,$fffffa19.w
	move.b border_tbcr,$fffffa1b.w
	move.b border_iera,$fffffa07.w
	move.b border_imra,$fffffa13.w
	move.b border_vr,$fffffa17.w
	bclr #0,$fffffa0f.w
	bclr #5,$fffffa0f.w
	move.w border_sr,sr
	; Capture 256 picture rows, not the ten hidden palette-blanked guard rows.
	add.l #1600,screen
	move.w #256,capture_height
	movem.l shown_pal,d0-d7
	movem.l d0-d7,$ffff8240.w
	bsr capture_snapshot
	move.l #'OPEN',bmp_name
	bsr save_bmp
	bsr close_screen
	move.l border_old_screen,screen
	move.w #200,capture_height
	lea border_result,a0
	bsr log_text
	move.l border_vbls,d0
	bsr log_hex
	moveq #0,d0
	move.w bd_fallbacks,d0
	bsr log_hex
	move.w bd_late_top,d0
	bsr log_hex
	move.w bd_late_on,d0
	bsr log_hex
	move.w bd_late_low,d0
	bsr log_hex
	move.w bd_late_off,d0
	bsr log_hex
	bsr log_eol
	lea border_dma_text,a0
	bsr log_text
	move.l border_min_dma,d0
	bsr log_hex
	move.l border_max_dma,d0
	bsr log_hex
	bsr log_eol
	lea border_confirm_text,a0
	bsr log_text
	moveq #0,d0
	tst.l border_off_samples
	beq .not_confirmed
	moveq #1,d0
	bra .confirmed
.not_confirmed:
	addq.l #1,auto_failures
.confirmed:
	bsr log_hex
	bsr log_eol
	lea border_samples_text,a0
	bsr log_text
	move.l border_off_samples,d0
	bsr log_hex
	move.l border_missed_frames,d0
	bsr log_hex
	bsr log_eol
	lea border_observe,a0
	bsr log_text
	bsr save_report
	rts
border_tick:
	addq.l #1,$4ba.w
	bclr #5,$fffffa11.w
	rte
border_hbl:
	rte
border_vbl:
	borders_vbl
	movem.l d0-d2,-(sp)
	addq.l #1,$466.w
	addq.l #1,border_vbls
	cmp.l #9,border_vbls
	blo .done
	tst.b border_off_seen
	bne .seen
	addq.l #1,border_missed_frames
.seen:
	clr.b border_off_seen
.done:
	movem.l (sp)+,d0-d2
	rte

border_off_sample:
	movem.l d0-d2,-(sp)
	st border_off_seen
	cmp.l #8,border_vbls
	blo .done
	addq.l #1,border_off_samples
	moveq #0,d0
	move.b $ffff8205.w,d0
	lsl.l #8,d0
	move.b $ffff8207.w,d0
	lsl.l #8,d0
	move.b $ffff8209.w,d0
	sub.l border_base,d0
	cmp.l border_min_dma,d0
	bhs .min_ok
	move.l d0,border_min_dma
.min_ok:
	cmp.l border_max_dma,d0
	bls .done
	move.l d0,border_max_dma
.done:
	movem.l (sp)+,d0-d2
	rts
	borders_handlers
	section data
border_begin: dc.b 'BEGIN OPEN BORDERS: shared port handlers, 320x256 test image, idle + short-HOG load; CPU mode retained',13,10,0
border_result: dc.b 'BORDERS VBLs/fallbacks/lateTop/lateOn/lateLow/lateOff: ',0
border_dma_text: dc.b 'BORDERS post-picture video-counter offset min/max bytes: ',0
border_confirm_text: dc.b 'BORDERS opening confirmed (1=yes,0=no): ',0
border_samples_text: dc.b 'BORDERS post-picture samples / missing frames after warmup: ',0
border_observe: dc.b 'BORDERS display stability: HUMAN OBSERVATION; BMP is framebuffer, not scanout.',13,10,0
	even
border_piece: dc.w 0,0,0,2,$017b,$da00,8,-6,2,$47
; 80, 192 and 240 data-bus cycles; longest is 252 with Mega STE grant/release.
border_stress_pieces:
	dc.w 0,0,0,2,$017b,$da00,8,-6,2,$47
	dc.w 0,0,2,2,$5a5a,$5a5a,8,-22,4,0
	dc.w 0,0,2,2,$5a5a,$5a5a,8,-30,5,0
border_stress_end:
shown_pal: dc.w $000,$111,$222,$333,$444,$555,$666,$777,$700,$070,$007,$770,$707,$077,$731,$157
black_pal: dcb.w 16,0
; A 256-byte screen base is necessary for the XBIOS / STE shifter.
	even
open_image: incbin 'open_screen.bin'
	section bss
border_old_screen: ds.l 1
border_old_hbl: ds.l 1
border_old_vbl: ds.l 1
border_old_ta: ds.l 1
border_old_tb: ds.l 1
border_vbls: ds.l 1
border_min_dma: ds.l 1
border_max_dma: ds.l 1
border_sr: ds.w 1
border_iera: ds.b 1
border_imra: ds.b 1
border_vr: ds.b 1
border_tacr: ds.b 1
border_tbcr: ds.b 1
border_tadr: ds.b 1
border_tbdr: ds.b 1
	even
	borders_vars

border_base: ds.l 1

border_off_samples: ds.l 1
border_missed_frames: ds.l 1
border_off_seen: ds.b 1
	even

border_old_tc: ds.l 1
