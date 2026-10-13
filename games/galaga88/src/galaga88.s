; Galaga '88 (Namco System 1) for the Atari STE.
;
; The translated main and sub CPU programs and their runtime: core.s (tools/gen.py, engine/m6809x.py).  The port
; starts from the reference's state after the boot (tools/machine.py START).
;
; SIM: the build the tests drive (tools/logic_test.py): the harness does the vertical blank's work, the MCU and the
; sound CPU in the reference and calls port_frame once a frame.
; (The program for the STE - snapshot, MCU, renderer, display - is not written yet.)

    ifnd SIM
	fail	"only the SIM build exists so far (tools/build.py --sim)"
    endc

; the idle loops' pass counters (core.s main_idle / sub_idle): one a frame, as the port's schedule (tools/machine.py)
idle_add	macro
	addq.b	#1,\1
	endm

	section text,code
start:
	clr.l	-(sp)
	move	#$20,-(sp)
	trap	#1
	addq	#6,sp
	lea	own_stack_top,sp
	lea	bad_table,a0
	move.w	#$2000-1,d0
.bad:	move.l	#cpu_badpc,(a0)+
	dbf	d0,.bad
	bsr	init_page_bases
	bsr	init_contexts
sim_wait:
	bra.s	sim_wait

	include	"core.s"
