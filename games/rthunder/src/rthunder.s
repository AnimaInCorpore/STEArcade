; Rolling Thunder (Namco System 86) for the Atari STE.
;
; The translated main and sub CPU programs and their runtime: core.s (tools/gen.py, engine/m6809x.py).
; SIM: the build the tests drive (tools/logic_test.py): the harness does the vertical blank's work, the MCU and the
; sound CPU in the reference and calls port_frame once a frame.  (The program for the STE itself, with the renderer, is
; not written yet: see the README.)

	section text,code
start:
	clr.l	-(sp)
	move	#$20,-(sp)
	trap	#1
	addq	#6,sp
	lea	own_stack_top,sp
	lea	bad_block,a0
	move.w	#256-1,d0
.bad:	move.l	#cpu_badpc,(a0)+
	dbf	d0,.bad
	lea	bad_table,a0
	moveq	#32-1,d0
.bdir:	move.l	#bad_block,(a0)+
	dbf	d0,.bdir
	bsr	init_contexts
sim_wait:
	bra.s	sim_wait

	include	"core.s"
