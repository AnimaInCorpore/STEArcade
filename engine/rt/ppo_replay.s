; Private replay/transport audit, included only by engine/ppo_hatari.py's isolated
; build. Captures completed arcade frames, never changes production executables.
; Packet: completed frame (BE long), rolling input digest (BE word), profile RAM.
	section text,code
ppo_step:
	movem.l d0-d7/a0-a6,-(sp)
	move sr,-(sp)
	move.l ppo_count,d0
	cmp.l #PPO_BOOT,d0
	blo .input
	cmp.l #PPO_FRAMES,d0
	beq.s .capture
	sub.l #PPO_BOOT,d0
	divu #12,d0
	swap d0
	tst.w d0
	bne .input
.capture:
	lea ppo_packet,a0
	move.l ppo_count,(a0)+
	move.w ppo_digest,(a0)+
	lea ppo_ranges,a2
.range:	move.l (a2)+,a1
	move.l (a2)+,d0
	beq.s .write
	subq.l #1,d0
.copy:	move.b (a1)+,(a0)+
	dbf d0,.copy
	bra.s .range
.write:	move #$2700,sr
	tst.b ppo_open
	bne.s .append
	clr.w -(sp)
	pea ppo_name
	move #$3c,-(sp)
	trap #1
	addq #8,sp
	tst.l d0
	bmi .error
	move.w d0,ppo_handle
	st ppo_open
.append:
	pea ppo_packet
	move.l #PPO_SIZE+6,-(sp)
	move.w ppo_handle,-(sp)
	move #$40,-(sp)
	trap #1
	lea 12(sp),sp
	cmp.l #PPO_SIZE+6,d0
	bne .error
	cmp.l #PPO_FRAMES,ppo_count
	bne.s .input
	move.w ppo_handle,-(sp)
	move #$3e,-(sp)
	trap #1
	addq #4,sp
	clr.w -(sp)
	pea ppo_done
	move #$3c,-(sp)
	trap #1
	addq #8,sp
	move.w d0,-(sp)
	move #$3e,-(sp)
	trap #1
	addq #4,sp
	; Private replay exits directly; Hatari is terminated by its own PID after
	; the completion marker. Hardware does not need to return to an interactive desktop.
	clr.w -(sp)
	trap #1
.input:
	tst.b ppo_left
	bne.s .same
	move.l ppo_ptr,a0
	cmp.w #0,a0
	bne.s .next
	lea ppo_data,a0
.next:	move.b (a0)+,ppo_left
	beq .error
	move.b (a0)+,ppo_system
	move.b (a0)+,ppo_player
	move.l a0,ppo_ptr
.same:	subq.b #1,ppo_left
	move.w ppo_digest,d1
	moveq #0,d0
	move.b ppo_system,d0
	bsr .hash
	move.b ppo_player,d0
	bsr .hash
	move.w d1,ppo_digest
	bsr ppo_apply
	addq.l #1,ppo_count
	move (sp)+,sr
	movem.l (sp)+,d0-d7/a0-a6
	rts
.hash:	move.w d1,d2
	lsl.w #5,d1
	add.w d2,d1
	eor.w d0,d1
	rts
.error:	; Failure never writes PPO.OK; the host rejects missing/partial captures.
	illegal
	section data,data
ppo_name:	dc.b "PPO.BIN",0
ppo_done:	dc.b "PPO.OK",0
	even
ppo_data:	incbin "play_inputs.bin"
	even
	section bss,bss
ppo_count:	ds.l 1
ppo_ptr:	ds.l 1
ppo_digest:	ds.w 1
ppo_handle:	ds.w 1
ppo_open:	ds.b 1
ppo_left:	ds.b 1
ppo_system:	ds.b 1
ppo_player:	ds.b 1
	even
ppo_packet:	ds.b PPO_SIZE+6
	section text,code
	include "ppo_apply.s"
