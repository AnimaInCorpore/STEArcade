; Extended native tests, fixtures, and 4bpp Windows BMP capture.
; Included by dltest.s; a5 always owns the report pointer.
	include "dltest_vectors.i"
	section text

; Tests every fixture with both source/destination boundary placements, six setup
; sequences, full independent 128-byte comparison, and unchanged guard bytes.
invalidate_piece_cache:
	move.w #$ffff,cached_sxi
	move.w #$ffff,cached_syi
	move.w #$ffff,cached_dxi
	move.w #$ffff,cached_dyi
	move.w #$ffff,cached_em1
	move.w #$ffff,cached_em3
	move.w #$ffff,cached_xc
	move.w #$ffff,cached_skew
	rts

matrix_test:
	lea matrix_begin,a0
	bsr log_text
	bsr save_report
	lea matrix_prompt,a0
	bsr print
	stage_begin 5,24*VECTOR_COUNT,0
	clr.w matrix_profile
.profile:
	clr.w matrix_placement
.placement:
	clr.l matrix_bad
	clr.l matrix_first
	clr.l matrix_ticks
	clr.l matrix_writes
	clr.l matrix_passes
	clr.l matrix_bus
	move.w #$ffff,cached_sxi
	move.w #$ffff,cached_syi
	move.w #$ffff,cached_dxi
	move.w #$ffff,cached_dyi
	move.w #$ffff,cached_em1
	move.w #$ffff,cached_em3
	move.w #$ffff,cached_xc
	move.w #$ffff,cached_skew
	clr.l source_cursor
	; Timer A is temporarily a /4 stopwatch; Timer C (TOS time) is untouched.
	move.w sr,-(sp)
	ori.w #$700,sr
	move.b $fffffa19.w,matrix_tacr
	move.b $fffffa1f.w,matrix_tadr
	move.b $fffffa07.w,matrix_iera
	move.b $fffffa13.w,matrix_imra
	bclr #5,$fffffa07.w
	bclr #5,$fffffa13.w
	clr.b $fffffa19.w
	clr.b $fffffa1f.w
	move.b #1,$fffffa19.w
	move.w (sp)+,sr
	move.l source,matrix_src
	btst #0,matrix_placement+1
	bne .src_ready
	lea source_space+128,a0
	move.l a0,matrix_src
.src_ready:
	lea dest_space+128,a0
	move.l a0,matrix_dst
	btst #1,matrix_placement+1
	beq .dst_ready
	lea dest_space+$20000,a0
	move.l a0,d0
	and.l #$ffff0000,d0
	sub.l #40,d0
	move.l d0,matrix_dst
.dst_ready:
	move.b #2,$ffff8a3a.w
	move.b #3,$ffff8a3b.w
	move.w #$ffff,$ffff8a2a.w
	lea blit_vectors,a6
	clr.w matrix_case
.case:
	lea 4(a6),a0
	move.l matrix_dst,a1
	moveq #31,d0
.initial:
	move.l (a0)+,(a1)+
	dbf d0,.initial
	lea 260(a6),a0
	move.l matrix_src,a1
	moveq #7,d0
.source:
	move.l (a0)+,(a1)+
	dbf d0,.source
	move.w 2(a6),matrix_npass
	lea 292(a6),a4
	move.b $fffffa1f.w,matrix_t0
	bsr run_pass_list
	; Busy is observed only at case end, NOT between the chained pieces.
.fence:
	btst #7,$ffff8a3c.w
	bne .fence
	moveq #0,d0
	move.b matrix_t0,d0
	sub.b $fffffa1f.w,d0
	and.l #255,d0
	add.l d0,matrix_ticks
	move.l matrix_dst,a0
	lea 132(a6),a1
	moveq #63,d4
.compare:
	move.w (a1)+,d0
	move.w (a0)+,d1
	cmp.w d0,d1
	beq .equal
	addq.l #1,matrix_bad
	tst.l matrix_first
	bne .equal
	moveq #1,d2
	move.l d2,matrix_first
	move.w matrix_case,matrix_first_case
	move.w d4,d2
	neg.w d2
	add.w #63,d2
	add.w d2,d2
	move.w d2,matrix_first_offset
	move.w d0,matrix_expected
	move.w d1,matrix_actual
.equal:
	dbf d4,.compare
	bsr progress_unit
	lea VECTOR_SIZE(a6),a6
	addq.w #1,matrix_case
	cmp.w #VECTOR_COUNT,matrix_case
	blo .case
	move.w sr,-(sp)
	ori.w #$700,sr
	clr.b $fffffa19.w
	move.b matrix_tadr,$fffffa1f.w
	move.b matrix_tacr,$fffffa19.w
	move.b matrix_iera,$fffffa07.w
	move.b matrix_imra,$fffffa13.w
	move.w (sp)+,sr
	bsr matrix_log
	bsr save_report
	addq.w #1,matrix_placement
	cmp.w #4,matrix_placement
	blo .placement
	addq.w #1,matrix_profile
	cmp.w #6,matrix_profile
	blo .profile
	bsr progress_end
	rts

; Pass descriptor: source,destination offsets,SXI,SYI,EM1,EM3,DXI,DYI,XC,skew.
; Profiles: 0 full word-start; 1 reused byte-start; 2..5 reused +1/2/4/8 post-start NOPs.
; NOPs are AFTER start: Mega STE cache can execute prefetched code during bus grant.
; There is no completion poll between pieces; the next MMIO accesses arbitrate naturally.
run_pass_list:
	tst.w matrix_npass
	beq .done
.next:
	bsr execute_piece
	lea 20(a4),a4
	subq.w #1,matrix_npass
	bne .next
.done:
	rts

cached_reg macro
	move.w \1(a4),d0
	tst.w matrix_profile
	beq.s .write\@
	cmp.w \3,d0
	beq.s .skip\@
.write\@:
	move.w d0,\2.w
	move.w d0,\3
	addq.l #1,matrix_writes
.skip\@:
	endm

execute_piece:
	cached_reg 4,$ffff8a20,cached_sxi
	cached_reg 6,$ffff8a22,cached_syi
	cached_reg 8,$ffff8a28,cached_em1
	cached_reg 10,$ffff8a2c,cached_em3
	cached_reg 12,$ffff8a2e,cached_dxi
	cached_reg 14,$ffff8a30,cached_dyi
	cached_reg 16,$ffff8a36,cached_xc
	tst.w matrix_profile
	bne .fixed
	move.w #$ffff,$ffff8a2a.w
	move.w #$0203,$ffff8a3a.w
	addq.l #2,matrix_writes
.fixed:
	moveq #0,d0
	move.w (a4),d0
	add.l matrix_src,d0
	tst.w matrix_profile
	beq .source
	cmp.l source_cursor,d0
	beq .source_skipped
.source:
	move.l d0,$ffff8a24.w
	addq.l #1,matrix_writes
.source_skipped:
	; Advance expected source cursor from the descriptor, including FXSR/NFSR.
	move.l d0,source_cursor
	move.w 16(a4),d1
	subq.w #1,d1
	btst #7,19(a4)
	beq .no_fxsr
	addq.w #1,d1
.no_fxsr:
	btst #6,19(a4)
	beq .no_nfsr
	subq.w #1,d1
.no_nfsr:
	muls 4(a4),d1
	move.w 6(a4),d2
	ext.l d2
	add.l d2,d1
	lsl.l #2,d1
	add.l d1,source_cursor
	moveq #0,d0
	move.w 2(a4),d0
	add.l matrix_dst,d0
	move.l d0,$ffff8a32.w
	move.w #4,$ffff8a38.w
	addq.l #3,matrix_writes	; destination, Y count, start
	move.w 18(a4),d0
	tst.w matrix_profile
	beq .word_start
	cmp.w cached_skew,d0
	beq .byte_start
	move.w d0,cached_skew
.word_start:
	or.w #$c000,d0
	move.w d0,$ffff8a3c.w
	bra .started
.byte_start:
	move.b #$c0,$ffff8a3c.w
.started:
	move.w matrix_profile,d0
	cmp.w #2,d0
	blo .no_gap
	subq.w #2,d0
	lea setup_nops,a0
	move.b (a0,d0.w),d0
	and.w #255,d0
	subq.w #1,d0
.gap:
	nop
	dbf d0,.gap
.no_gap:
	addq.l #1,matrix_passes
	rts

matrix_log:
	lea matrix_line,a0
	bsr log_text
	moveq #0,d0
	move.w matrix_profile,d0
	bsr log_hex
	move.w matrix_placement,d0
	bsr log_hex
	move.w #VECTOR_COUNT,d0
	bsr log_hex
	move.l matrix_bad,d0
	bsr log_hex
	move.l matrix_writes,d0
	bsr log_hex
	move.l matrix_passes,d0
	bsr log_hex
	move.l matrix_ticks,d0
	bsr log_hex
	bsr log_eol
	tst.l matrix_bad
	beq .ok
	addq.l #1,auto_failures
	lea matrix_first_text,a0
	bsr log_text
	moveq #0,d0
	move.w matrix_first_case,d0
	bsr log_hex
	move.w matrix_first_offset,d0
	bsr log_hex
	move.w matrix_expected,d0
	bsr log_hex
	move.w matrix_actual,d0
	bsr log_hex
	bsr log_eol
.ok:
	rts

; Freeze framebuffer + palette only; file writes are deferred until ISR restoration.
capture_snapshot:
	movem.l d0-d3/a0-a2,-(sp)
	bsr progress_hide
	move.l screen,a0
	lea capture_planar,a1
	moveq #0,d0
	move.w capture_height,d0
	mulu #40,d0
	subq.w #1,d0
.copy:
	move.l (a0)+,(a1)+
	dbf d0,.copy
	lea $ffff8240.w,a0
	lea capture_palette,a1
	moveq #15,d0
.palette:
	move.w (a0)+,(a1)+
	dbf d0,.palette
	move.b #2,capture_requested
	clr.l progress_next
	bsr progress_update
	movem.l (sp)+,d0-d3/a0-a2
	rts

save_bmp:
	clr.b bmp_error
	movem.l d0-d7/a0-a6,-(sp)
	lea bmp_template,a0
	lea bmp_buffer,a1
	moveq #58,d0
.header:
	move.w (a0)+,(a1)+
	dbf d0,.header
	moveq #0,d0
	move.w capture_height,d0
	mulu #160,d0
	move.l d0,capture_file_size
	lea bmp_buffer+34,a0
	bsr bmp_le32
	move.l capture_file_size,d0
	add.l #118,d0
	move.l d0,capture_file_size
	lea bmp_buffer+2,a0
	bsr bmp_le32
	moveq #0,d0
	move.w capture_height,d0
	lea bmp_buffer+22,a0
	bsr bmp_le32
	lea capture_palette,a0
	lea bmp_buffer+54,a1
	moveq #15,d7
.palette:
	move.w (a0)+,d3
	moveq #2,d6
.channel:
	move.w d3,d0
	and.w #15,d0
	; STE nibble is G3 G2 G1 G0 encoded as bit0 in bit3; convert to 0..255.
	move.w d0,d1
	and.w #7,d0
	lsl.w #1,d0
	lsr.w #3,d1
	or.w d1,d0
	mulu #17,d0
	move.b d0,(a1)+
	lsr.w #4,d3
	dbf d6,.channel
	clr.b (a1)+
	dbf d7,.palette
	lea bmp_buffer+118,a1
	move.w capture_height,d7
	subq.w #1,d7
	moveq #0,d0
	move.w d7,d0
	mulu #160,d0
	lea capture_planar,a2
	add.l d0,a2
.row:
	move.l a2,a0
	moveq #19,d6
.group:
	move.w (a0)+,d0
	move.w (a0)+,d1
	move.w (a0)+,d2
	move.w (a0)+,d3
	moveq #7,d5
.pair:
	; Two pixels, each assembled from the four plane MSBs.
	moveq #0,d4
	lsl.w #1,d3
	addx.b d4,d4
	lsl.w #1,d2
	addx.b d4,d4
	lsl.w #1,d1
	addx.b d4,d4
	lsl.w #1,d0
	addx.b d4,d4
	lsl.b #4,d4
	move.b d4,(a1)
	moveq #0,d4
	lsl.w #1,d3
	addx.b d4,d4
	lsl.w #1,d2
	addx.b d4,d4
	lsl.w #1,d1
	addx.b d4,d4
	lsl.w #1,d0
	addx.b d4,d4
	or.b d4,(a1)+
	dbf d5,.pair
	dbf d6,.group
	lea -160(a2),a2
	dbf d7,.row
	move.w mode_index,d0
	add.b #'0',d0
	move.b d0,bmp_name+4
	clr.w -(sp)
	pea bmp_name
	move.w #$3c,-(sp)
	trap #1
	addq.l #8,sp
	tst.l d0
	bmi .error
	move.w d0,d6
	pea bmp_buffer
	move.l capture_file_size,-(sp)
	move.w d6,-(sp)
	move.w #$40,-(sp)
	trap #1
	lea 12(sp),sp
	cmp.l capture_file_size,d0
	beq .close
	st bmp_error
.close:
	move.w d6,-(sp)
	move.w #$3e,-(sp)
	trap #1
	addq.l #4,sp
	tst.l d0
	bpl .logged
.error:
	st bmp_error
.logged:
	tst.b bmp_error
	beq .save_ok
	addq.l #1,auto_failures
.save_ok:
	movem.l (sp)+,d0-d7/a0-a6
	lea capture_text,a0
	bsr log_text
	lea bmp_name,a0
	bsr log_text
	move.b #32,(a5)+
	moveq #0,d0
	move.b bmp_error,d0
	bsr log_hex
	bsr log_eol
	rts

bmp_le32:
	move.b d0,(a0)+
	lsr.l #8,d0
	move.b d0,(a0)+
	lsr.l #8,d0
	move.b d0,(a0)+
	lsr.l #8,d0
	move.b d0,(a0)+
	rts

; Complete bob scenes; exact comparison includes all visible/guard/background words.
scene_test:
	stage_begin 8,32,0
	lea scene_begin,a0
	bsr log_text
	bsr save_report
	move.l screen,scene_old_screen
	lea dest_space+$20000,a0
	move.l a0,d0
	and.l #$ffff0000,d0
	sub.l #160*64,d0
	move.l d0,scene_base
	add.l #160*16,d0
	move.l d0,screen
	bsr open_screen
	lea scenes_data,a6
	clr.w scene_frame
.frame:
	bsr progress_hide
	moveq #0,d0
	move.w scene_frame,d0
	lsl.w #2,d0
	move.l (a6,d0.w),d0
	lea (a6,d0.l),a3
	move.w 2(a3),matrix_npass
	move.l 4(a3),d0
	lea 8(a3),a0
	lea (a0,d0.l),a4
	; Decode the independent CPU renderer's exact expected image.
	lea scene_expected,a1
.decode:
	moveq #0,d0
	move.w (a0)+,d0
	beq .decoded
	bmi .literal
	subq.w #1,d0
	move.w (a0)+,d1
.repeat:
	move.w d1,(a1)+
	dbf d0,.repeat
	bra .decode
.literal:
	and.w #$7fff,d0
	subq.w #1,d0
.lit:
	move.w (a0)+,(a1)+
	dbf d0,.lit
	bra .decode
.decoded:
	lea scene_bg,a0
	move.l scene_base,a1
	move.w #9599,d0
.restore:
	move.l (a0)+,(a1)+
	dbf d0,.restore
	move.l #scene_source,matrix_src
	move.l scene_base,matrix_dst
	move.w #1,matrix_profile	; shortest reused-register, no added NOPs
	move.w #$ffff,cached_sxi
	move.w #$ffff,cached_syi
	move.w #$ffff,cached_dxi
	move.w #$ffff,cached_dyi
	move.w #$ffff,cached_em1
	move.w #$ffff,cached_em3
	move.w #$ffff,cached_xc
	move.w #$ffff,cached_skew
	clr.l source_cursor
	move.w #$ffff,$ffff8a2a.w
	move.w #$0203,$ffff8a3a.w
	bsr run_pass_list
.fence:
	btst #7,$ffff8a3c.w
	bne .fence
	clr.l scene_bad
	move.l scene_base,a0
	lea scene_expected,a1
	move.w #19199,d4
.compare:
	move.w (a1)+,d0
	cmp.w (a0)+,d0
	beq .equal
	addq.l #1,scene_bad
.equal:
	dbf d4,.compare
	lea scene_result,a0
	bsr log_text
	moveq #0,d0
	move.w scene_frame,d0
	bsr log_hex
	move.l scene_bad,d0
	bsr log_hex
	bsr log_eol
	tst.l scene_bad
	beq .ok
	addq.l #1,auto_failures
.ok:
	bsr progress_unit
	addq.w #1,scene_frame
	cmp.w #32,scene_frame
	blo .frame
	bsr progress_end
	; Last frame is fixed, captured identically on real hardware and Hatari.
	bsr capture_snapshot
	move.l #'BOBS',bmp_name
	bsr save_bmp
	bsr save_report
	; Let the tester inspect the fixed scene. Disk I/O is over before this wait.
	ifd QUICK
	stage_begin 11,2,1
	else
	stage_begin 11,10,1
	endc
	move.l $4ba.w,d7
	ifd QUICK
	add.l #400,d7
	else
	add.l #200*10,d7
	endc
.hold:
	bsr progress_update
	cmp.l $4ba.w,d7
	bhi .hold
	bsr progress_end
	bsr close_screen
	move.l scene_old_screen,screen
	rts

	section data
setup_nops: dc.b 1,2,4,8
	even
matrix_begin: dc.b 'BEGIN exhaustive Blitter matrix',13,10,0
matrix_prompt: dc.b 27,'E','Automatic Blitter setup/shift tests.',13,10,'Please wait. No keys needed.',13,10,0
matrix_line: dc.b 'MATRIX profile/place/cases/badwords/MMIOwrites/passes/MFPticks: ',0
matrix_first_text: dc.b 'FIRST FAIL case/byteOffset/expected/actual: ',0
capture_text: dc.b 'CAPTURE file/error(0=OK): ',0
bmp_name: dc.b 'INPT0.BMP',0
scene_begin: dc.b 'BEGIN bob scenes: 32 frames, 26 objects, exact visible+guard comparison',13,10,0
scene_result: dc.b 'SCENE frame/badwords: ',0
	even
blit_vectors: incbin 'blit_vectors.bin'
	even
bmp_template: incbin 'bmp_header.bin'
	even
scenes_data: incbin 'scenes.bin'
	even
scene_source: incbin 'scene_source.bin'
	even
scene_bg: incbin 'scene_bg.bin'
	even
	section bss
matrix_src: ds.l 1
matrix_dst: ds.l 1
source_cursor: ds.l 1
matrix_ticks: ds.l 1
matrix_writes: ds.l 1
matrix_passes: ds.l 1
matrix_bus: ds.l 1
matrix_bad: ds.l 1
matrix_first: ds.l 1
matrix_first_case: ds.w 1
matrix_first_offset: ds.w 1
matrix_expected: ds.w 1
matrix_actual: ds.w 1
matrix_profile: ds.w 1
matrix_placement: ds.w 1
matrix_case: ds.w 1
matrix_npass: ds.w 1
matrix_tacr: ds.b 1
matrix_tadr: ds.b 1
matrix_iera: ds.b 1
matrix_imra: ds.b 1
matrix_t0: ds.b 1
capture_requested: ds.b 1
bmp_error: ds.b 1
	even
cached_sxi: ds.w 1
cached_syi: ds.w 1
cached_dxi: ds.w 1
cached_dyi: ds.w 1
cached_em1: ds.w 1
cached_em3: ds.w 1
cached_xc: ds.w 1
cached_skew: ds.w 1
auto_failures: ds.l 1
scene_old_screen: ds.l 1
scene_base: ds.l 1
scene_bad: ds.l 1
scene_frame: ds.w 1
capture_palette: ds.w 16
capture_height: ds.w 1
capture_file_size: ds.l 1
capture_planar: ds.b 44800
bmp_buffer: ds.b 44918
scene_expected: ds.b 38400
dest_space: ds.b 196608
