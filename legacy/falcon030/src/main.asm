; Donkey Kong Atari Falcon030 Port
;
; This is intentionally a clean build stub. Generated translations and native routine drafts are
; not linked until the virtual Z80 state, memory/I/O boundary, and differential harness are ready.
; See src/translated/README.md and PORTING.md.

        section text

_start:
        bra.s   PORT_NOT_READY
        nop

PORT_NOT_READY:
        bra.s   PORT_NOT_READY
