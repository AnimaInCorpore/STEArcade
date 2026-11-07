; Exact post-start padding kernels. All variants contain the same three setup
; writes per pass: destination long, Y count word, control byte. No per-pass fence.
; Nominal MC68000 setup instructions: 12+8+8=28 CPU cycles, BEFORE memory waits.
; The two-word/4-plane masked transfer has 4 source reads + 8 destination reads
; + 8 destination writes = 80 bus cycles, excluding grant/release and setup.
	section text
setup_test:
	stage_begin 4,10,0
	lea setup_begin,a0
	bsr log_text
	bsr save_report
	clr.w setup_family
.family:
	clr.w setup_profile
.profile:
	bsr setup_kernel_run
	bsr progress_unit
	lea setup_result,a0
	bsr log_text
	moveq #0,d0
	move.w setup_family,d0
	bsr log_hex
	moveq #0,d0
	move.w setup_profile,d0
	lea kernel_nops,a0
	move.b (a0,d0.w),d0
	and.l #255,d0
	bsr log_hex
	move.l setup_ticks,d0
	bsr log_hex
	move.l setup_bad,d0
	bsr log_hex
	bsr log_eol
	tst.l setup_bad
	beq .ok
	addq.l #1,auto_failures
.ok:
	bsr save_report
	addq.w #1,setup_profile
	cmp.w #5,setup_profile
	blo .profile
	addq.w #1,setup_family
	cmp.w #2,setup_family
	blo .family
	bsr progress_end
	rts

setup_kernel_run:
	movem.l d0-d7/a0-a6,-(sp)
	lea source_space+128,a0
	move.w #1023,d0
.source:
	move.l #$ffff0000,(a0)+
	move.l #$ffff0000,(a0)+
	dbf d0,.source
	lea dest_space+$10000,a0
	move.l a0,d0
	and.l #$ffff0000,d0
	add.l #$4000,d0
	move.l d0,setup_dst
	sub.l #8192,d0
	move.l d0,a0
	move.w #2175,d0
.clear:
	clr.l (a0)+
	dbf d0,.clear
	clr.w $ffff8a20.w
	move.w #2,$ffff8a22.w
	move.w #$017b,$ffff8a28.w	; $bded >> 7
	move.w #$ffff,$ffff8a2a.w
	move.w #$da00,$ffff8a2c.w	; $bded << 9
	move.w #8,$ffff8a2e.w
	move.w #-6,$ffff8a30.w
	move.w #2,$ffff8a36.w
	move.w #$0203,$ffff8a3a.w
	move.b #$47,$ffff8a3d.w
	lea source_space+128,a0
	lea $ffff8a32.w,a4
	lea $ffff8a38.w,a5
	lea $ffff8a3c.w,a6
	move.l setup_dst,d0
	moveq #4,d1
	move.w #$c0,d2
	moveq #63,d5		; 64 batches x 1024 = 65536 short passes
	move.l $4ba.w,setup_start_tick
	moveq #0,d3
	move.w setup_profile,d3
	lsl.w #2,d3
	lea kernel_table,a1
	tst.w setup_family
	beq .table
	lea rmw_table,a1
.table:
	move.l (a1,d3.w),a1
	jsr (a1)
.fence:
	btst #7,(a6)
	bne .fence
	move.l $4ba.w,d3
	sub.l setup_start_tick,d3
	move.l d3,setup_ticks
	; Both target rows must match, INCLUDING untouched words and transparent holes.
	move.l setup_dst,a0
	lea setup_expected,a1
	moveq #63,d0
	clr.l setup_bad
.compare:
	move.w (a0)+,d1
	cmp.w (a1)+,d1
	beq .equal
	addq.l #1,setup_bad
.equal:
	dbf d0,.compare
	move.l setup_dst,a0
	lea -8192(a0),a0
	move.w #2047,d0
.guard_before:
	tst.l (a0)+
	beq .before_ok
	addq.l #1,setup_bad
.before_ok:
	dbf d0,.guard_before
	move.l setup_dst,a0
	lea 128(a0),a0
	move.w #95,d0
.guard_after:
	tst.l (a0)+
	beq .after_ok
	addq.l #1,setup_bad
.after_ok:
	dbf d0,.guard_after
	movem.l (sp)+,d0-d7/a0-a6
	rts

bob_kernel macro
kernel_\1:
.batch:
	move.l a0,$ffff8a24.w
	move.w #1023,d7
.pass:
	move.l d0,(a4)
	move.w d1,(a5)
	move.b d2,(a6)
	rept \1
	nop
	endr
	eor.l #32,d0
	dbf d7,.pass
	dbf d5,.batch
	rts
	endm
	bob_kernel 0
	bob_kernel 1
	bob_kernel 2
	bob_kernel 4
	bob_kernel 8

rmw_kernel macro
rmw_\1:
.batch:
	move.l a0,$ffff8a24.w
	move.l d0,(a4)
	moveq #24,d4
	moveq #-40,d3
	move.w #1023,d7
.pass:
	move.w d1,(a5)
	move.b d2,(a6)
	rept \1
	nop
	endr
	add.w d4,2(a4)	; read Blitter-updated destination immediately after start
	exg d3,d4
	dbf d7,.pass
	dbf d5,.batch
	rts
	endm
	rmw_kernel 0
	rmw_kernel 1
	rmw_kernel 2
	rmw_kernel 4
	rmw_kernel 8

	section data
kernel_nops: dc.b 0,1,2,4,8
	even
kernel_table: dc.l kernel_0,kernel_1,kernel_2,kernel_4,kernel_8
rmw_table: dc.l rmw_0,rmw_1,rmw_2,rmw_4,rmw_8
setup_begin: dc.b 'BEGIN bob setup timing: 65536 passes/profile; kind0=3writes/28cycles, kind1=post-start destination RMW/32cycles; payload=80 bus cycles/pass',13,10,0
setup_result: dc.b 'SETUP kind/postStartNOPs/elapsed200HzTicks/badwords: ',0
	even
setup_expected:
	dc.w $017b,0,$017b,0,$da00,0,$da00,0
	dcb.w 8,0
	dc.w $017b,0,$017b,0,$da00,0,$da00,0
	dcb.w 40,0
	section bss
setup_profile: ds.w 1
setup_ticks: ds.l 1
setup_bad: ds.l 1

setup_dst: ds.l 1

setup_family: ds.w 1
setup_start_tick: ds.l 1
