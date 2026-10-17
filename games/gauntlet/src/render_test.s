; The renderer in a harness for engine/sim.py (tools/render_test.py, tools/sprite_test.py): no game, no interrupts.
; The harness writes the arcade's video RAM, palette and x scroll at their STE addresses (map.i) while the program
; waits at sim_wait, then lets it draw a picture (render_frame; it stops at sim_render_ret).  The first time,
; init_video runs before the picture (on the first state, as gauntlet.s calls it on the BIOS's).

	include	"map.i"
	ifnd PIC_TOP
PIC_TOP = 18
	endc
TA_DATA = 98
TA_NOPS = 84
PIC_LINES = 240
BD_PALETTE = 1
	include	"borders.s"

	section	text,code
start:
	lea	stack_top,sp
	jsr	sim_wait
	bsr	init_video
.loop:	bsr	render_frame
	jsr	sim_render_ret
	jsr	sim_wait
	bra.s	.loop

sim_wait:
	bra.s	sim_wait
sim_render_ret:
	bra.s	sim_render_ret

	include	"render.s"
	borders_blit_go

	section	bss,bss
	borders_vars
	even
	ds.b	16384
stack_top:
