; Rolling Thunder (Namco System 86) for the Atari STE.
;
; The translated main and sub CPU programs and their runtime: core.s (tools/gen.py, engine/m6809x.py), the picture:
; render.s, the MCU (the mailbox of the HD63701) as a native model: mcu.s, the STE program around them: ste.s.
; SIM: the build the tests drive (tools/logic_test.py): the harness does the vertical blank's work, the MCU and the
; sound CPU in the reference and calls port_frame once a frame.

	ifd SIM
	section text,code
start:
	clr.l	-(sp)
	move	#$20,-(sp)
	trap	#1
	addq	#6,sp
	lea	own_stack_top,sp
	bsr	init_tables
	bsr	init_contexts
sim_wait:
	bra.s	sim_wait

; the dispatch tables' unused entries
init_tables:
	lea	bad_block,a0
	move.w	#256-1,d0
.bad:	move.l	#cpu_badpc,(a0)+
	dbf	d0,.bad
	lea	bad_table,a0
	moveq	#32-1,d0
.bdir:	move.l	#bad_block,(a0)+
	dbf	d0,.bdir
	rts

	include	"core.s"
	include	"render.s"
	else
	include	"ste.s"
	endc
