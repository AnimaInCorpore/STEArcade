; Z80 Flag Compatibility Helpers for selective AOT recompilation
; These helpers support translated code and routine boundaries that expose Z80 F.
; Native replacement routines may use the 68030 CCR internally when their contract
; does not expose Z80 flags. Do not update the shadow flags after every instruction
; by default; materialize only flags that are live or boundary-visible.

section data
Z80_FLAGS:   ds.b 1       ; Z80 F: bit 7=S,6=Z,5=Y,4=H,3=X,2=P/V,1=N,0=C
Z80_A:       ds.b 1       ; optional mirror of A for debugging

        section text

; ------------------------------------------------------------
; Conditional return stubs
; ------------------------------------------------------------
; On entry, Z80_FLAGS contains the Z80 F register for the current boundary.
; These hooks only test the shadow condition. The translated caller must
; implement the appropriate Z80 control-flow and emulated-stack behavior.

Z80_RET_NC:   ; RET NC – return if Carry = 0
        move.b  Z80_FLAGS,d0
        btst    #0,d0          ; Carry bit
        beq.s   .ret_nc_ok
        rts
.ret_nc_ok:
        ; condition false – continue execution
        rts

Z80_RET_C:    ; RET C – return if Carry = 1
        move.b  Z80_FLAGS,d0
        btst    #0,d0
        bne.s   .ret_c_ok
        rts
.ret_c_ok:
        rts

; ------------------------------------------------------------
; General flag update stub
; ------------------------------------------------------------
; Materialize Z80 F only where flag bits are live or observable. A complete
; implementation must handle S,Z,H,P/V,N,C per Z80 spec, especially half-carry;
; the M68k CCR is not a direct replacement for Z80 F.

Z80_UPDATE_FLAGS:
        ; Placeholder: compute only the flags required by the calling boundary.
        ; TODO: implement instruction-specific H, P/V, N, and undocumented X/Y rules.
        rts

; ------------------------------------------------------------
; Note on register mapping
; ------------------------------------------------------------
; Z80 A → D0
; Z80 B/C/D/E → D1-D4
; Z80 HL pair → A1 as pointer, H/L bytes kept in D5 high/low for now
; Z80 SP → A7
;
; Flag emulation is required because 68030 lacks Z80 half-carry H
; and has different parity/overflow semantics. Direct CCR sync is
; insufficient for DAA and for precise conditional branches.
;
; Rationale for using stubs: static translation keeps Z80 source
; as comment behind 68000 code per project rule, and flag-dependent
; instructions are routed through explicit emulation routines so
; traceability is maintained.
