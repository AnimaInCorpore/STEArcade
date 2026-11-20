; Production ports select the CIRCLE timing family on the Mega STE.
; Standalone timing probes still instantiate their measured kernels separately.
BD_CIRCLE = 1
	ifnd BD_POLL
BD_POLL = 320			; enough polls for a four-line lead at 16 MHz
	endc
	include "circle_borders.i"
	include "borders.s"
