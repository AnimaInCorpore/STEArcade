; Donkey Kong Atari Falcon030 Port
; Main entry point
; Generated with AOT static translation

        ; GEMDOS PRG header
        ; Magic "M", version, etc.
        ; Will be filled by build script

        section .text
_start:
        ; TODO: Initialize Videl, Blitter, set up frame buffer
        ; TODO: Copy ROM data to memory

_start:
        ; Jump to native boot init replacement
        jbra    L_0000_native

        ; Translated code will be included here
        include "translated/boot_init_native.asm"
        include "translated/init_0266_native.asm"
        include "translated/routine_0450_native.asm"
        include "translated/routine_04ac_native.asm"
        include "translated/routine_04e1_native.asm"
        include "translated/routine_051c_native.asm"
        include "translated/routine_0578_native.asm"
        include "translated/routine_0583_native.asm"
        include "translated/routine_05c6_native.asm"
        ; include "translated/*.asm"

; End of file
        include "translated/routine_06B8_native.asm"
        include "translated/routine_07DA_native.asm"
        include "translated/routine_0938_native.asm"
        include "translated/routine_0C2B_native.asm"
        include "translated/routine_0C92_native.asm"
        include "translated/routine_0CC6_native.asm"
        include "translated/routine_0D5F_native.asm"
        include "translated/routine_0DA7_native.asm"
        include "translated/routine_0E19_native.asm"
        include "translated/routine_0E62_native.asm"
