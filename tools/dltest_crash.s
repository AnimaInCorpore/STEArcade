; Unexpected exceptions leave a native report and best-effort desktop recovery.
; Expected ILLEGAL checks temporarily replace vector 4 and return normally.
	section text
install_crash:
	move.w sr,-(sp)
	ori.w #$700,sr
	lea fatal_stubs,a0
	lea $8.w,a1
	lea original_vectors,a2
	moveq #9,d0
.loop:
	move.l (a1),(a2)+
	move.l a0,(a1)+
	addq.l #6,a0
	dbf d0,.loop
	move.l $68.w,original_hbl
	move.l $70.w,original_vbl
	move.l $118.w,original_acia
	move.l $120.w,original_tb
	move.l $134.w,original_ta
	move.l $114.w,original_tc
	move.b $fffffa07.w,original_iera
	move.b $fffffa09.w,original_ierb
	move.b $fffffa13.w,original_imra
	move.b $fffffa15.w,original_imrb
	move.b $fffffa17.w,original_vr
	move.b $fffffa19.w,original_tacr
	move.b $fffffa1b.w,original_tbcr
	move.b $fffffa1f.w,original_tadr
	move.b $fffffa21.w,original_tbdr
	move.w (sp)+,sr
	rts
restore_vectors:
	move.w sr,-(sp)
	ori.w #$700,sr
	lea original_vectors,a0
	lea $8.w,a1
	moveq #9,d0
.loop:
	move.l (a0)+,(a1)+
	dbf d0,.loop
	move.w (sp)+,sr
	rts
fatal_stubs:
	rept 10
	moveq #REPTN+2,d0
	bra.w fatal_exception
	endr
fatal_exception:
	move.w #$2700,sr
	move.w d0,fatal_vector
	movem.l d0-d7/a0-a6,fatal_regs
	move.l sp,fatal_sp
	move.l 2(sp),fatal_pc
	cmp.w #3,d0
	bhi .standard
	move.l 10(sp),fatal_pc
.standard:
	lea fatal_stack_top,sp
	clr.b $ffff8901.w
	clr.b $fffffa19.w
	clr.b $fffffa1b.w
	move.l original_hbl,$68.w
	move.l original_vbl,$70.w
	move.l original_acia,$118.w
	move.l original_tb,$120.w
	move.l original_ta,$134.w
	move.l original_tc,$114.w
	move.b original_tadr,$fffffa1f.w
	move.b original_tbdr,$fffffa21.w
	move.b original_tacr,$fffffa19.w
	move.b original_tbcr,$fffffa1b.w
	move.b original_vr,$fffffa17.w
	move.b original_iera,$fffffa07.w
	move.b original_ierb,$fffffa09.w
	move.b original_imra,$fffffa13.w
	move.b original_imrb,$fffffa15.w
	tst.b is_mega
	beq .speed
	move.b old_speed,$ffff8e21.w
.speed:
	bsr restore_vectors
	move.w #$2300,sr
	bsr close_screen
	move.l report_checkpoint,a5
	lea fatal_text,a0
	bsr log_text
	moveq #0,d0
	move.w fatal_vector,d0
	bsr log_hex
	move.l fatal_pc,d0
	bsr log_hex
	move.l fatal_sp,d0
	bsr log_hex
	lea start,a0
	move.l a0,d0
	bsr log_hex
	bsr log_eol
	lea fatal_registers_text,a0
	bsr log_text
	lea fatal_regs,a4
	moveq #14,d6
.reg:
	move.l (a4)+,d0
	bsr log_hex
	dbf d6,.reg
	bsr log_eol
	bsr save_report
	lea fatal_prompt,a0
	bsr print
	bra exit
	section data
fatal_text: dc.b 'FATAL unexpected vector/PC/SP/loadBase: ',0
fatal_registers_text: dc.b 'FATAL registers D0(vector),D1-D7,A0-A6: ',0
fatal_prompt: dc.b 'DLTEST stopped. Return partial DLTEST.TXT.',13,10,0
	even
	section bss
report_checkpoint: ds.l 1
fatal_vector: ds.w 1
fatal_pc: ds.l 1
fatal_sp: ds.l 1
fatal_regs: ds.l 15
original_vectors: ds.l 10
original_hbl: ds.l 1
original_vbl: ds.l 1
original_acia: ds.l 1
original_tb: ds.l 1
original_ta: ds.l 1
original_iera: ds.b 1
original_ierb: ds.b 1
original_imra: ds.b 1
original_imrb: ds.b 1
original_vr: ds.b 1
original_tacr: ds.b 1
original_tbcr: ds.b 1
original_tadr: ds.b 1
original_tbdr: ds.b 1
	even
fatal_stack: ds.b 4096
fatal_stack_top:

original_tc: ds.l 1
