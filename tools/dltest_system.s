; CPU, private RAM, file transport, input observation, and audible checks.
	section text
system_inventory:
	lea inventory_text,a0
	bsr log_text
	move.l basepage_start,d0
	bsr log_hex
	move.l basepage_end,d0
	bsr log_hex
	move.l basepage_end,d0
	sub.l basepage_start,d0
	bsr log_hex
	move.l $42e.w,d0
	bsr log_hex
	bsr log_eol
	lea state_text,a0
	bsr log_text
	moveq #0,d0
	move.b old_res+1,d0
	bsr log_hex
	move.b old_sync,d0
	bsr log_hex
	move.l old_phys,d0
	bsr log_hex
	move.l old_log,d0
	bsr log_hex
	bsr log_eol
	rts

cpu_test:
	stage_begin 1,1,0
	lea cpu_begin,a0
	bsr log_text
	bsr save_report
	clr.l cpu_bad
	move.w #1023,d4
.smc:
	move.w d4,smc_code+2
	jsr smc_code
	cmp.w d4,d0
	beq .smc_ok
	addq.l #1,cpu_bad
.smc_ok:
	dbf d4,.smc
	lea cpu_vectors,a4
	moveq #63,d4
.arithmetic:
	moveq #0,d0
	move.w (a4)+,d0
	mulu (a4)+,d0
	cmp.l (a4)+,d0
	beq .mul_ok
	addq.l #1,cpu_bad
.mul_ok:
	move.l (a4)+,d0
	divu (a4)+,d0
	cmp.l (a4)+,d0
	beq .div_ok
	addq.l #1,cpu_bad
.div_ok:
	dbf d4,.arithmetic
	bsr exception_test
	bsr progress_unit
	bsr progress_end
	lea cpu_result,a0
	bsr log_text
	move.l cpu_bad,d0
	bsr log_hex
	bsr log_eol
	tst.l cpu_bad
	beq .ok
	addq.l #1,auto_failures
.ok:
	rts
smc_code:
	move.w #0,d0
	rts

; Independent address-derived patterns, walking one/zero, byte lane writes and
; a March-style ascending/descending transition sweep over 128 KiB OWNED BSS.
ram_extended:
	stage_begin 2,40,0
	lea ram_begin,a0
	bsr log_text
	bsr save_report
	clr.w ram_pattern
	clr.l ram_total
.pattern:
	clr.l ram_errors
	clr.l ram_first_addr
	clr.w ram_first_expected
	clr.w ram_first_actual
	moveq #0,d4
	bsr ram_value
	move.w d0,d5
	lea ram_space,a0
	move.w #65535,d4
	cmp.w #5,ram_pattern
	bhs .uniform_write
.address_write:
	move.w d4,d0
	eor.w d5,d0
	move.w d0,(a0)+
	dbf d4,.address_write
	bra .read_start
.uniform_write:
	move.w d5,(a0)+
	dbf d4,.uniform_write
.read_start:
	lea ram_space,a0
	move.w #65535,d4
	cmp.w #5,ram_pattern
	bhs .uniform_read
.address_read:
	move.w d4,d0
	eor.w d5,d0
	move.w (a0)+,d1
	cmp.w d0,d1
	beq .address_equal
	bsr ram_note_error
.address_equal:
	dbf d4,.address_read
	bra .pattern_done
.uniform_read:
	move.w d5,d0
	move.w (a0)+,d1
	cmp.w d0,d1
	beq .uniform_equal
	bsr ram_note_error
.uniform_equal:
	dbf d4,.uniform_read
.pattern_done:
	lea ram_pattern_text,a0
	bsr log_text
	moveq #0,d0
	move.w ram_pattern,d0
	bsr log_hex
	move.l ram_errors,d0
	bsr log_hex
	move.l ram_first_addr,d0
	bsr log_hex
	moveq #0,d0
	move.w ram_first_expected,d0
	bsr log_hex
	move.w ram_first_actual,d0
	bsr log_hex
	bsr log_eol
	bsr progress_unit
	addq.w #1,ram_pattern
	cmp.w #37,ram_pattern
	blo .pattern
	; Byte writes exercise both byte lanes without a word write hiding a fault.
	lea ram_space,a0
	move.l #65535,d4
.bytes:
	move.b #$5a,(a0)
	move.b #$a5,1(a0)
	move.w (a0)+,d1
	move.w #$5aa5,d0
	cmp.w d0,d1
	beq .bytes_ok
	bsr ram_note_error
.bytes_ok:
	subq.l #1,d4
	bpl .bytes
	bsr progress_unit
	; March transitions: w0; ascending r0/w1; descending r1/w0; ascending r0.
	lea ram_space,a0
	move.w #32767,d4
.zero:
	clr.l (a0)+
	dbf d4,.zero
	lea ram_space,a0
	move.l #65535,d4
.march_up:
	moveq #0,d0
	move.w (a0),d1
	tst.w d1
	beq .up_ok
	bsr ram_note_error
.up_ok:
	move.w #$ffff,(a0)+
	subq.l #1,d4
	bpl .march_up
	lea ram_space+131072,a0
	move.l #65535,d4
.march_down:
	move.w -(a0),d1
	move.w #$ffff,d0
	cmp.w d0,d1
	beq .down_ok
	addq.l #2,a0
	bsr ram_note_error
	subq.l #2,a0
.down_ok:
	clr.w (a0)
	subq.l #1,d4
	bpl .march_down
	bsr progress_unit
	lea ram_space,a0
	move.w #32767,d4
.long:
	move.l (a0),d0
	tst.l d0
	beq .long_ok
	addq.l #1,ram_total
.long_ok:
	move.l #$89abcdef,(a0)
	cmp.l #$89abcdef,(a0)+
	beq .long_written
	addq.l #1,ram_total
.long_written:
	dbf d4,.long
	bsr progress_unit
	bsr progress_end
	move.l ram_total,ram_bad
	lea ram_total_text,a0
	bsr log_text
	move.l ram_total,d0
	bsr log_hex
	bsr log_eol
	tst.l ram_total
	beq .ok
	addq.l #1,auto_failures
.ok:
	rts
ram_value:
	move.w ram_pattern,d0
	cmp.w #5,d0
	bhs .walking
	lea ram_masks,a1
	add.w d0,d0
	move.w (a1,d0.w),d0
	eor.w d4,d0
	move.l d4,d1
	swap d1
	eor.w d1,d0
	rts
.walking:
	subq.w #5,d0
	moveq #1,d1
	and.w #15,d0
	lsl.w d0,d1
	cmp.w #21,ram_pattern
	blo .one
	not.w d1
.one:
	move.w d1,d0
	rts
ram_note_error:
	addq.l #1,ram_total
	addq.l #1,ram_errors
	tst.l ram_first_addr
	bne .out
	move.l a0,ram_first_addr
	subq.l #2,ram_first_addr
	move.w d0,ram_first_expected
	move.w d1,ram_first_actual
.out:
	rts

file_test:
	stage_begin 3,3,0
	lea io_begin,a0
	bsr log_text
	bsr save_report
	clr.l io_error
	clr.l io_bad
	; Never overwrite an existing file of unknown ownership.
	clr.w -(sp)
	pea io_name
	move.w #$3d,-(sp)
	trap #1
	addq.l #8,sp
	tst.l d0
	bmi .create
	move.w d0,-(sp)
	move.w #$3e,-(sp)
	trap #1
	addq.l #4,sp
	lea io_skip,a0
	bsr log_text
	bsr progress_end
	rts
.create:
	clr.w -(sp)
	pea io_name
	move.w #$3c,-(sp)
	trap #1
	addq.l #8,sp
	tst.l d0
	bmi .failed
	move.w d0,io_handle
	lea ram_space,a0
	move.w #32767,d4
.fill:
	move.l d4,d0
	eor.l #$13579bdf,d0
	move.l d0,(a0)+
	dbf d4,.fill
	pea ram_space
	move.l #131072,-(sp)
	move.w io_handle,-(sp)
	move.w #$40,-(sp)
	trap #1
	lea 12(sp),sp
	cmp.l #131072,d0
	beq .written
	move.l d0,io_error
.written:
	bsr progress_unit
	bsr io_close
	clr.w -(sp)
	pea io_name
	move.w #$3d,-(sp)
	trap #1
	addq.l #8,sp
	tst.l d0
	bmi .failed
	move.w d0,io_handle
	pea source_space
	move.l #131072,-(sp)
	move.w io_handle,-(sp)
	move.w #$3f,-(sp)
	trap #1
	lea 12(sp),sp
	cmp.l #131072,d0
	beq .read
	move.l d0,io_error
.read:
	bsr progress_unit
	bsr io_close
	lea ram_space,a0
	lea source_space,a1
	move.w #32767,d4
.compare:
	move.l (a0)+,d0
	cmp.l (a1)+,d0
	beq .equal
	addq.l #1,io_bad
.equal:
	dbf d4,.compare
	pea io_name
	move.w #$41,-(sp)
	trap #1
	addq.l #6,sp
	tst.l d0
	beq .report
.failed:
	move.l d0,io_error
.report:
	bsr progress_unit
	bsr progress_end
	lea io_result,a0
	bsr log_text
	move.l io_error,d0
	bsr log_hex
	move.l io_bad,d0
	bsr log_hex
	bsr log_eol
	move.l io_error,d0
	or.l io_bad,d0
	beq .ok
	addq.l #1,auto_failures
.ok:
	rts
io_close:
	move.w io_handle,-(sp)
	move.w #$3e,-(sp)
	trap #1
	addq.l #4,sp
	tst.l d0
	beq .out
	move.l d0,io_error
.out:
	rts

; Non-invasive tap of exactly the bytes consumed by the shared IKBD parser.
; This hook is injected ONLY in the diagnostic's generated include.
input_observer:
	movem.l d0-d3/a0,-(sp)
	move.w sr,-(sp)
	addq.l #1,input_bytes
	moveq #0,d0
	move.w input_trace_count,d0
	cmp.w #128,d0
	bhs .traced
	lea input_trace,a0
	move.b d1,(a0,d0.w)
	addq.w #1,input_trace_count
.traced:
	move.b mouse_pending,d0
	beq .header
	cmp.b #2,d0
	bne .dy
	move.b d1,d0
	ext.w d0
	ext.l d0
	add.l d0,mouse_dx
	bra .decrement
.dy:
	move.b d1,d0
	ext.w d0
	ext.l d0
	add.l d0,mouse_dy
.decrement:
	subq.b #1,mouse_pending
	bra .out
.header:
	; The common parser's state distinguishes headers from packet data.
	tst.b ikbd_state
	bne .out
	cmp.b #$f8,d1
	blo .out
	cmp.b #$fb,d1
	bhi .out
	move.b #2,mouse_pending
	addq.l #1,mouse_packets
	move.b d1,d0
	and.b #3,d0
	or.b d0,mouse_buttons
.out:
	move.w (sp)+,ccr
	movem.l (sp)+,d0-d3/a0
	rts

input_summary:
	lea input_counts_text,a0
	bsr log_text
	move.l input_bytes,d0
	bsr log_hex
	move.l mouse_packets,d0
	bsr log_hex
	move.l mouse_dx,d0
	bsr log_hex
	move.l mouse_dy,d0
	bsr log_hex
	moveq #0,d0
	move.b mouse_buttons,d0
	bsr log_hex
	bsr log_eol
	lea key_counts,a0
	bsr log_text
	moveq #0,d6
.key:
	lea key_down_count,a4
	move.w d6,d0
	add.w d0,d0
	move.w (a4,d0.w),d1
	beq .next
	move.l d6,d0
	bsr log_hex
	move.w d6,d0
	add.w d0,d0
	moveq #0,d1
	move.w (a4,d0.w),d1
	move.l d1,d0
	bsr log_hex
	lea key_up_count,a4
	move.w d6,d0
	add.w d0,d0
	moveq #0,d1
	move.w (a4,d0.w),d1
	move.l d1,d0
	bsr log_hex
	bsr log_eol
.next:
	addq.w #1,d6
	cmp.w #128,d6
	blo .key
	lea input_trace_text,a0
	bsr log_text
	moveq #0,d6
.trace:
	cmp.w input_trace_count,d6
	bhs .traced
	lea input_trace,a0
	moveq #0,d0
	move.b (a0,d6.w),d0
	bsr log_hex
	addq.w #1,d6
	bra .trace
.traced:
	bsr log_eol
	lea input_not_exercised,a0
	tst.l raw_count
	beq .status
	lea input_exercised,a0
.status:
	bsr log_text
	rts

sound_test:
	lea sound_begin,a0
	bsr log_text
	bsr save_report
	lea sound_prompt,a0
	bsr print
	stage_begin 9,3,1
	lea ym_saved,a0
	moveq #0,d0
.save:
	move.b d0,$ffff8800.w
	move.b $ffff8800.w,(a0)+
	addq.w #1,d0
	cmp.w #14,d0
	blo .save
	move.b #0,$ffff8800.w
	move.b #$1c,$ffff8802.w
	move.b #1,$ffff8800.w
	move.b #1,$ffff8802.w
	move.b #7,$ffff8800.w
	move.b ym_saved+7,d0
	and.b #$c0,d0
	or.b #$3e,d0
	move.b d0,$ffff8802.w
	move.b #8,$ffff8800.w
	move.b #6,$ffff8802.w
	move.l $4ba.w,d7
	add.l #100,d7
.beep:
	bsr progress_update
	cmp.l $4ba.w,d7
	bhi .beep
	lea ym_saved,a0
	moveq #0,d0
.restore:
	move.b d0,$ffff8800.w
	move.b (a0)+,$ffff8802.w
	addq.w #1,d0
	cmp.w #14,d0
	blo .restore
	move.b $ffff8901.w,d0
	and.b #1,d0
	beq .dma
	lea sound_skip,a0
	bsr log_text
	bsr progress_end
	rts
.dma:
	move.b $ffff8901.w,dma_saved
	move.b $ffff8921.w,dma_saved+1
	move.b $ffff8903.w,dma_saved+2
	move.b $ffff8905.w,dma_saved+3
	move.b $ffff8907.w,dma_saved+4
	move.b $ffff890f.w,dma_saved+5
	move.b $ffff8911.w,dma_saved+6
	move.b $ffff8913.w,dma_saved+7
	move.l #audio_data,d0
	move.b d0,$ffff8907.w
	lsr.l #8,d0
	move.b d0,$ffff8905.w
	lsr.l #8,d0
	move.b d0,$ffff8903.w
	move.l #audio_end,d0
	move.b d0,$ffff8913.w
	lsr.l #8,d0
	move.b d0,$ffff8911.w
	lsr.l #8,d0
	move.b d0,$ffff890f.w
	clr.b $ffff8921.w	; 6258 Hz, stereo, signed 8 bit
	move.b #1,$ffff8901.w
	move.l $4ba.w,d7
	add.l #600,d7
.wait:
	bsr progress_update
	btst #0,$ffff8901.w
	beq .ended
	cmp.l $4ba.w,d7
	bhi .wait
	addq.l #1,auto_failures
.ended:
	moveq #0,d0
	move.b $ffff8901.w,d0
	move.l d0,dma_end_control
	moveq #0,d0
	move.b $ffff8909.w,d0
	lsl.l #8,d0
	move.b $ffff890b.w,d0
	lsl.l #8,d0
	move.b $ffff890d.w,d0
	move.l d0,dma_end_counter
	clr.b $ffff8901.w
	move.b dma_saved+2,$ffff8903.w
	move.b dma_saved+3,$ffff8905.w
	move.b dma_saved+4,$ffff8907.w
	move.b dma_saved+5,$ffff890f.w
	move.b dma_saved+6,$ffff8911.w
	move.b dma_saved+7,$ffff8913.w
	move.b dma_saved+1,$ffff8921.w
	move.b dma_saved,$ffff8901.w
	bsr progress_end
	lea sound_result,a0
	bsr log_text
	move.l dma_end_control,d0
	bsr log_hex
	move.l dma_end_counter,d0
	bsr log_hex
	bsr log_eol
	rts

	section data
inventory_text: dc.b 'MEMORY basepageStart/end/TPAbytes/phystop: ',0
state_text: dc.b 'ORIGINAL resolution/sync/physical/logical: ',0
cpu_begin: dc.b 'BEGIN CPU arithmetic and self-modifying instruction fetch',13,10,0
cpu_result: dc.b 'CPU 1024 SMC +64 MULU +64 DIVU mismatches: ',0
ram_begin: dc.b 'BEGIN private 128KiB RAM: 37 patterns + byte lanes + March transitions + long writes',13,10,0
ram_pattern_text: dc.b 'RAM pattern/errors/firstAddress/expected/actual: ',0
ram_total_text: dc.b 'RAM EXTENDED total mismatches: ',0
io_begin: dc.b 'BEGIN GEMDOS 128KiB create/write/close/reopen/read/compare/delete',13,10,0
io_name: dc.b 'DLIO.TMP',0
io_skip: dc.b 'FILE SKIP: DLIO.TMP already exists; it was not modified.',13,10,0
io_result: dc.b 'FILE error(0=OK)/badlongs: ',0
input_counts_text: dc.b 'INPUT bytes/mousePackets/signedDX/signedDY/buttons: ',0
key_counts: dc.b 'KEY scancode/pressCount/releaseCount:',13,10,0
input_trace_text: dc.b 'INPUT first128 raw bytes: ',0
input_exercised: dc.b 'KEYBOARD status: key events observed; unpressed controls NOT EXERCISED.',13,10,0
input_not_exercised: dc.b 'KEYBOARD status: NOT EXERCISED (unattended run).',13,10,0
sound_begin: dc.b 'BEGIN sound: YM beep, DMA left440Hz then right660Hz',13,10,0
sound_prompt: dc.b 27,'E','Sound: short beep, then left/right.',13,10,'No response needed. Note missing sound.',13,10,0
sound_skip: dc.b 'DMA SKIP: playback was already active. Audibility NOT OBSERVED automatically.',13,10,0
sound_result: dc.b 'DMA finalControl/lastCounter (audibility NOT OBSERVED): ',0
	even
ram_masks: dc.w 0,$ffff,$5555,$aaaa,$1234
cpu_vectors: incbin 'cpu_vectors.bin'
	even
audio_data: incbin 'audio.bin'
audio_end:
	even
	section bss
cpu_bad: ds.l 1
ram_pattern: ds.w 1
ram_errors: ds.l 1
ram_total: ds.l 1
ram_first_addr: ds.l 1
ram_first_expected: ds.w 1
ram_first_actual: ds.w 1
io_error: ds.l 1
io_bad: ds.l 1
io_handle: ds.w 1
input_bytes: ds.l 1
input_trace_count: ds.w 1
input_trace: ds.b 128
mouse_packets: ds.l 1
mouse_dx: ds.l 1
mouse_dy: ds.l 1
mouse_buttons: ds.b 1
mouse_pending: ds.b 1
key_down_count: ds.w 128
key_up_count: ds.w 128
ym_saved: ds.b 14
dma_saved: ds.b 8
	even
dma_end_control: ds.l 1
dma_end_counter: ds.l 1
