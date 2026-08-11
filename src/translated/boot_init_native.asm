; ------------------------------------------------------------
; Native 68030 replacement for Z80 boot init routine
; Z80 address range: 0x0000-0x0004
; Replacement contract: docs/analysis/boot_init_analysis.md
; ------------------------------------------------------------

        section .text

; ---- Contract ----
; Inputs: none
; Outputs:
;   * I/O write $7D84 = 0   ; interrupt enable clear
;   * PC -> $0266
; Clobbers: D0
; Flags: none observable
; Timing: not critical for boot

L_0000_native:
        ; Z80: 3E 00   LD A,$00
        moveq   #0,d0
        ; Z80: 32 84 7D   LD ($7D84),A
        move.b  d0,$7D84
        ; Z80: C3 66 02   JP $0266
        jbra    L_0266

; The original Z80 bytes are retained for traceability:
; 0000: 3E 00 32 84 7D C3 66 02
; Rationale: single I/O write and unconditional jump. No Z80 flags are
; consumed or produced. Native 68030 code preserves observable side effect
; and control flow. D0 is used internally only.

        ; End of native replacement
