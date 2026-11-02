; Mr. HELI no Daibouken (Irem M72) for the Atari STE.
;
; The translated main CPU program and its runtime: core.s (tools/gen.py, engine/v30x.py), as R-Type's
; (games/rtype/src/rtype.s).  The port starts from the reference's state after the boot (tools/machine.py START); the
; boot (the ROM / RAM tests, the code the i8751 MCU puts into the dual-port RAM) is not translated.
;
; SIM: the build the tests drive (tools/logic_test.py): the harness writes the reference's state into the image and the
; context, sets in_ports and calls port_frame once an arcade frame.  The STE program (snapshot, schedule, renderer,
; input) is not written yet.

	section bss,bss
; (the image's tail first in the BSS: it follows the ROM, the last thing in the data section; core.s init_image)
v30_tail:	ds.b	$60000

	section text,code
start:
	clr.l	-(sp)
	move	#$20,-(sp)
	trap	#1
	addq	#6,sp
	move.l	d0,old_ssp
	lea	own_stack_top,sp
	bsr	init_image
    ifd SIM
sim_wait:
	bra.s	sim_wait
    else
	move.l	old_ssp,-(sp)		; (no STE program yet: back to the desktop)
	move	#$20,-(sp)
	trap	#1
	addq	#6,sp
	clr	-(sp)
	trap	#1
port_crash:
	bra.s	port_crash
    endc

	include	"core.s"

	section data,data
; (last in the data section: the V30 image's ROM, followed by v30_tail)
	even
v30_image:
	incbin	"rom_image.bin"

	section bss,bss
old_ssp:	ds.l	1
		ds.b	4096
own_stack_top:
