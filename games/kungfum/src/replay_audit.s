; Optional Hatari replay instrumentation. Called at a completed arcade frame's
; idle hook, independent of picture skipping and the STE's VBL count. Normal
; builds do not include this file. Format: frame, hook PC, LFSR, scroll (BE words),
; D000-EFFF RAM, C000-C0FF sprites. Flush in short batches, outside rendering.
AUDIT_SIZE = 8+$2000+$100
AUDIT_BATCH = 16
	section text,code
replay_audit:
	movem.l	d0-d7/a0-a6,-(sp)
	move	sr,-(sp)
	move.w	isr_count,d0
	cmp.w	#900,d0
	blo	.out
	cmp.w	audit_last,d0
	beq	.out
	moveq	#0,d1
	move.w	d0,d1
	divu	#12,d1
	swap	d1
	tst.w	d1
	bne	.out
	move.w	d0,audit_last
	move.l	audit_ptr,a0
	cmp.w	#0,a0
	bne.s	.have
	lea	audit_buffer,a0
.have:	move.w	d0,(a0)+
	move.w	d7,(a0)+
	move.w	rnd_state,(a0)+
	moveq	#0,d1
	move.b	Z_RAM+$B000,d1
	lsl.w	#8,d1
	move.b	Z_RAM+$A000,d1
	move.w	d1,(a0)+
	lea	Z_RAM+$D000,a1
	move.w	#$2000/4-1,d1
.ram:	move.l	(a1)+,(a0)+
	dbf	d1,.ram
	lea	Z_RAM+$C000,a1
	move.w	#$100/4-1,d1
.spr:	move.l	(a1)+,(a0)+
	dbf	d1,.spr
	move.l	a0,audit_ptr
	cmp.l	#audit_buffer+AUDIT_BATCH*AUDIT_SIZE,a0
	bne.s	.final
	bsr	audit_flush
.final:	cmp.w	#REPLAY_AUDIT_FRAMES,isr_count
	blo.s	.out
	bsr	audit_flush
	move.w	audit_handle,-(sp)
	move.w	#$3e,-(sp)
	trap	#1
	addq	#4,sp
	clr.w	-(sp)
	pea	audit_done
	move.w	#$3c,-(sp)
	trap	#1
	addq	#8,sp
	move.w	d0,-(sp)
	move.w	#$3e,-(sp)
	trap	#1
	addq	#4,sp
	move	(sp)+,sr
	movem.l	(sp)+,d0-d7/a0-a6
	jmp	quit
.out:	move	(sp)+,sr
	movem.l	(sp)+,d0-d7/a0-a6
	rts

audit_flush:
	move.l	audit_ptr,d4
	beq.s	.empty
	sub.l	#audit_buffer,d4
	beq.s	.empty
	move	#$2700,sr
	tst.b	audit_open
	bne.s	.write
	clr.w	-(sp)
	pea	audit_name
	move.w	#$3c,-(sp)
	trap	#1
	addq	#8,sp
	tst.l	d0
	bmi.s	.error
	move.w	d0,audit_handle
	st	audit_open
.write:	pea	audit_buffer
	move.l	d4,-(sp)
	move.w	audit_handle,-(sp)
	move.w	#$40,-(sp)
	trap	#1
	lea	12(sp),sp
	cmp.l	d4,d0
	bne.s	.error
	move.l	#audit_buffer,audit_ptr
.empty:	rts
.error:	moveq	#98,d0
	jmp	crash_common
	section data,data
audit_name:	dc.b	"AUDIT.BIN",0
audit_done:	dc.b	"AUDIT.OK",0
	even
	section bss,bss
audit_ptr:	ds.l	1
audit_handle:	ds.w	1
audit_last:	ds.w	1
audit_open:	ds.b	1
	even
audit_buffer:	ds.b	AUDIT_SIZE*AUDIT_BATCH
	section text,code
