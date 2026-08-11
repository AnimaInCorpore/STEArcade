; Replacement contract for Z80 0x0266 init routine
; See docs/analysis/routine_0266_contract.md
;
; Inputs: none
; Outputs:
;   RAM $6000-$60FF cleared
;   RAM $7000-$70FF cleared
;   RAM $7400-$74FF cleared
;   $60B0 = $C0
;   $60B1 = $C0
;   I/O $7D82 = $00
;   I/O $7D83 = $00
;   I/O $7D86 = $00
;   I/O $7D87 = $00
;   I/O $7D84 = $01

        .section .text
L_0266_native:
        ; Clear $6000-$60FF
        move.l  #$6000,a1
        moveq   #0,d0
        move.w  #0xFF,d7
.clear6000:
        move.b  d0,(a1)+
        dbra    d7,.clear6000

        ; Clear $7000-$70FF
        move.l  #$7000,a1
        moveq   #0,d0
        move.w  #0xFF,d7
.clear7000:
        move.b  d0,(a1)+
        dbra    d7,.clear7000

        ; Clear $7400-$74FF
        move.l  #$7400,a1
        moveq   #0,d0
        move.w  #0xFF,d7
.clear7400:
        move.b  d0,(a1)+
        dbra    d7,.clear7400

        ; Set $60B0/$60B1
        move.b  #$C0,$60B0
        move.b  #$C0,$60B1

        ; I/O writes
        move.b  #0,$7D82
        move.b  #0,$7D83
        move.b  #0,$7D86
        move.b  #0,$7D87
        move.b  #1,$7D84

        jbra    L_03DE   ; continue to next init stage
