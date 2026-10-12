; The i8751 of 1943: the dumped firmware (mcu.rom) translated to 68000 code by tools/mcux.py (mcu_code.s), run at reset
; and at each VBL INT1.  a0 = the internal RAM and SFRs (256 bytes), a1 = the ROM.  The SFRs that matter: P0 ($80, the
; command latch AND the port's output latch on a read), P3 ($b0: a falling edge of bit 6 copies P0 to the reply latch
; g_mcu_response), PSW ($d0: the register bank, CY, AC, OV; the parity bit is made exact where PSW is read and at the
; end of a run), ACC ($e0), DPTR ($82/$83).  The callers keep their registers (the hook saves them all).

mcu_init:
    lea mcu_ram,a0
    move #63,d0
.clear:
    clr.l (a0)+
    dbf d0,.clear
    lea mcu_ram,a0
    move.b #7,$81(a0)
    move.b #$ff,$80(a0)
    move.b #$ff,$90(a0)
    move.b #$ff,$a0(a0)
    move.b #$ff,$b0(a0)
    lea mcu_rom,a1
    move.b $e0(a0),d0              ; (ACC: d0 in the translated code)
    bra M0000                      ; (to the idle loop; its rts returns from here)

; INT1 (the VBL): push the pc (the idle loop), run from $0013 to the idle loop again.
mcu_vblank:
    lea mcu_ram,a0
    move.b $a8(a0),d0
    and.b #$84,d0
    cmp.b #$84,d0
    bne.s .off
    moveq #0,d0
    move.b $81(a0),d0
    addq.b #1,d0
    move.w mcu_pc,d1
    move.b d1,(a0,d0.w)
    addq.b #1,d0
    lsr.w #8,d1
    move.b d1,(a0,d0.w)
    move.b d0,$81(a0)
    lea mcu_rom,a1
    move.b $e0(a0),d0
    ifd MCU_XLATE
    bra M0013
    else
    bra mcu_int1
    endc
.off:
    jmp z80_unsupported            ; (INT1 not enabled: the firmware is not where it should be)

; INT1 ($0013 -> $0200-$023B) in 68000 code: the command (P0) looked up in the 32 (key, value) pairs at ROM $0800; the
; value of the last pair whose key matches (R4; none: R4 as it was) is the reply (P0, P3 bit 6 low-high).  The
; firmware walks all 32 pairs each time (~7k cycles translated); here the pairs are searched from the end, and what
; the walk leaves is set at once: R2 = R7 = the command, R3 = 0, DPTR = $0840, ACC and PSW's CY / AC / OV from the
; last pair's `subb` (ACC = its value if its key matched, else key - command).  -D MCU_XLATE: the translation.
    ifnd MCU_XLATE
mcu_int1:
    bclr #7,168(a0)                ; clr EA
    and.b #$e7,208(a0)             ; register bank 0
    move.b #$ff,128(a0)            ; mov P0,#$ff
    move.b 176(a0),d2              ; clr P3.7
    bclr #7,d2
    bsr mcu_p3
    move.b mcu_command,d3          ; mov R2,P0 / mov R7,P0
    and.b 128(a0),d3
    move.b d3,2(a0)
    move.b d3,7(a0)
    move.b 176(a0),d2              ; setb P3.7
    bset #7,d2
    bsr mcu_p3
    move.b #$08,131(a0)            ; DPTR = $0800 + 2 * 32
    move.b #$40,130(a0)
    clr.b 3(a0)                    ; R3
    lea $0800+62(a1),a3            ; the last matching key
    moveq #31,d7
.find:
    cmp.b (a3),d3
    beq.s .hit
    subq.l #2,a3
    dbf d7,.find
    bra.s .last
.hit:
    move.b 1(a3),4(a0)             ; R4
.last:
    move.b $0800+62(a1),d0         ; the last pair: clr C, subb A,R2
    move.b d0,d1
    sub.b d3,d1
    move sr,d5
    and.w #3,d5
    lea mcu_cvtab,a3
    move.b 208(a0),d7
    and.b #$3b,d7
    or.b (a3,d5.w),d7
    move.b d3,d2
    eor.b d1,d2
    eor.b d0,d2
    and.b #$10,d2
    lsl.b #2,d2
    or.b d2,d7
    move.b d7,208(a0)
    move.b d1,d0
    bne.s .reply
    move.b $0800+63(a1),d0         ; (its key matched: movc of the value)
.reply:
    move.b 4(a0),128(a0)           ; mov P0,R4
    move.b 176(a0),d2              ; clr P3.6, setb P3.6: the reply
    bclr #6,d2
    bsr mcu_p3
    move.b 176(a0),d2
    bset #6,d2
    bsr mcu_p3
    bclr #3,136(a0)                ; clr IE1
    bset #7,168(a0)                ; setb EA
    bsr mcu_reti
    cmp.w #$011a,d1
    beq M011A
    move.l d1,d7
    jmp z80_unsupported
    endc

; reti: d1 = the popped return address
mcu_reti:
    moveq #0,d3
    move.b $81(a0),d3
    moveq #0,d1
    move.b (a0,d3.w),d1
    lsl.w #8,d1
    subq.b #1,d3
    move.b (a0,d3.w),d1
    subq.b #1,d3
    move.b d3,$81(a0)
    rts

; d2 = the new P3: its bit 6 falling latches P0 as the reply
mcu_p3:
    btst #6,$b0(a0)
    beq.s .store
    btst #6,d2
    bne.s .store
    move.b $80(a0),g_mcu_response
    addq.w #1,mcu_transactions
.store:
    move.b d2,$b0(a0)
    rts

; PSW bit 0 = the parity of ACC (the 8051 keeps it so after every instruction).  Uses d2 and a3.
mcu_parity:
    moveq #0,d2
    move.b $e0(a0),d2
    lea mcu_partab(pc),a3
    move.b (a3,d2.w),d2
    bclr #0,$d0(a0)
    or.b d2,$d0(a0)
    rts

mcu_cvtab:                         ; the 68000's C (bit 0) and V (bit 1) as the 8051's CY (bit 7) and OV (bit 2)
    dc.b 0,$80,$04,$84
mcu_partab:
    rept 256
PB set REPTN
PB set (PB&1)+((PB>>1)&1)+((PB>>2)&1)+((PB>>3)&1)+((PB>>4)&1)+((PB>>5)&1)+((PB>>6)&1)+((PB>>7)&1)
    dc.b PB&1
    endr
    even
    include "mcu_code.s"
    section bss,bss
mcu_ram: ds.b 256
mcu_pc: ds.w 1
mcu_transactions: ds.w 1
    section text,code
