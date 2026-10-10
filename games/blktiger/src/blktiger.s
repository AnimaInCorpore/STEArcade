; Black Tiger: translated whole Z80 program, cooperative tasks, STE display.
KEY_ESC = $01
PIC_TOP = 26
TA_DATA = 98
TA_NOPS = 84
PIC_LINES = 224
BD_PALETTE = 1
; Border removal and the palette on / off: engine/rt/borders.s.  Its events come early and sync themselves to the
; video, so a Blitter pass may start at any time: none waits.  Passes longer than BLIT_PIECE words run in pieces
; (blit_go, there).
    include "borders.s"

; the pads (engine/rt/jagpad.s): SYSTEM, P1, P2 bits as in key_table (bytes 0-2 of each long)
JP_SH1 = 16
JP_SH2 = 8
JP1_RIGHT = $01<<JP_SH1
JP1_LEFT = $02<<JP_SH1
JP1_DOWN = $04<<JP_SH1
JP1_UP = $08<<JP_SH1
JP1_B1 = $10<<JP_SH1
JP1_B2 = $20<<JP_SH1
JP1_B3 = 0<<JP_SH1
JP2_RIGHT = $01<<JP_SH2
JP2_LEFT = $02<<JP_SH2
JP2_DOWN = $04<<JP_SH2
JP2_UP = $08<<JP_SH2
JP2_B1 = $10<<JP_SH2
JP2_B2 = $20<<JP_SH2
JP2_B3 = 0<<JP_SH2
JP_START1 = $01<<24
JP_START2 = $02<<24
JP_COIN1 = $40<<24
JP_COIN2 = $80<<24
	include	"jagpad.s"
BUSY = $80
HOG = $40
G_Z80 = g_block+$8000
IDLE_PC = $00d4
    ifnd FRAMES
FRAMES = 0
    endc
    ifnd MAX_SKIPS
MAX_SKIPS = 4                    ; frames skipped in a row while game ticks are pending (the game first)
    endc
    section text,code
start:
    clr.l -(sp)
    move #$20,-(sp)
    trap #1
    addq #6,sp
    move.l d0,old_ssp
    lea own_stack_top,sp
    bsr init_hardware
    bsr init_video
    bsr mcu_init
    move.b #$ff,in_sys
    move.b #$ff,in_p1
    move.b #$ff,in_p2
    moveq #0,d0
    bsr bt_out_01
    lea G_Z80,a6
    lea G_Z80-1,a5
    lea bt_fixed_dispatch,a4
    moveq #0,d0
    moveq #0,d1
    moveq #0,d2
    moveq #0,d3
    moveq #0,d4
    moveq #0,d5
    moveq #0,d6
    moveq #0,d7
    sub.l a0,a0
    sub.l a1,a1
    sub.l a2,a2
    sub.l a3,a3
    move #$2300,sr
    jmp Z0000

; Natural-PC dispatch through word tables (gen.py: a word per Z80 address, (the entry - the region's base) / 2):
; the fixed code in two regions ($0000-$3FFF, $4000-$7FFF: 64 KB, a4), the window through the bank's table (32 KB,
; its base the long before it; g_wdispatch 0 for a bank without code).
bt_dispatch:                    ; d7.w = the Z80 address (kept for z80_badpc); a0 / d5 are free at a jump
    move.w d7,g_dispatch_pc
    bmi.s .window
    moveq #0,d5
    move.w d7,d5
    add.w d5,d5                     ; (N: from $4000)
    bmi.s .high
    move.w (a4,d5.l),d5
    add.l d5,d5
    lea bt_base_lo,a0
    jmp (a0,d5.l)
.high:
    move.w (a4,d5.l),d5
    add.l d5,d5
    lea bt_base_hi,a0
    jmp (a0,d5.l)
.window:
    cmp.w #$c000,d7
    bhs.s .bad
    move.l g_wdispatch,d5
    beq.s .bad
    move.l d5,a0
    moveq #0,d5
    move.w d7,d5
    add.w d5,d5                     ; ($8000-$bfff: 0-$7ffe)
    move.w (a0,d5.l),d5
    add.l d5,d5
    move.l -4(a0),a0
    jmp (a0,d5.l)
.bad:
    jmp z80_badpc

; The scheduler has scanned all sixteen task records with no ready task.
z80_hook:
    tst.b quit_flag
    bne quit
    tst.b isr_stage
    beq.s .normal
    clr.b isr_stage
    rts                         ; handler returned; run the tasks before ending this tick
.normal:
    tst.b frame_dirty
    beq.s .check
    clr.b frame_dirty
    movem.l d0-d7/a0-a6,-(sp)
    ifnd SIM
    tst.b vbl_pending
    beq.s .draw_now
    addq.b #1,render_skips
    cmp.b #MAX_SKIPS+1,render_skips
    blo.s .skip_draw
.draw_now:
    clr.b render_skips
    endc
    bsr render_frame
    addq.w #1,cnt_renders
.skip_draw:
    movem.l (sp)+,d0-d7/a0-a6
    ifd SIM
    jsr sim_frame_done
    endc
.check:
    tst.b vbl_pending
    bne.s .deliver
    ifd SIM
    jsr sim_wait
    bra.s .check
    else
    tst.b quit_flag
    bne quit
    rts
    endc
.deliver:
    subq.b #1,vbl_pending
    addq.w #1,cnt_ticks
    ifd AUTOPLAY
    ; (benchmark build: logic_test's inputs, period 3000 ticks: coin, start, then right + attack)
    movem.l d0-d1,-(sp)
    moveq #0,d0
    move.w cnt_ticks,d0
    divu #3000,d0
    swap d0
    moveq #-1,d1
    cmp.w #900,d0
    blo.s .ap_sys
    cmp.w #905,d0
    bhs.s .ap_start
    and.b #~$40,d1
.ap_start:
    cmp.w #940,d0
    blo.s .ap_sys
    cmp.w #945,d0
    bhs.s .ap_sys
    and.b #~1,d1
.ap_sys:
    move.b d1,bt_inputs
    moveq #-1,d1
    cmp.w #1000,d0
    blo.s .ap_p1
    eor.b #1|16,d1
    ext.l d0
    divu #90,d0
    swap d0
    cmp.w #15,d0
    bhs.s .ap_p1
    eor.b #32,d1
.ap_p1:
    move.b d1,bt_inputs+1
    movem.l (sp)+,d0-d1
    endc
    st frame_dirty
    st isr_stage
    ; The sprite RAM as the VBL latches it, for this tick's frame: not when that frame will be skipped (VBLs still
    ; pending now are pending at its end too, and .normal then skips it unless MAX_SKIPS were skipped already).
    ifnd SIM
    tst.b vbl_pending
    beq.s .sprites
    cmp.b #MAX_SKIPS,render_skips
    blo.s .no_sprites
    endc
.sprites:
    movem.l d0-d7/a0-a2,-(sp)
    lea g_block+$7e00,a0
    lea bt_sprites,a1
    moveq #$200/32-1,d0
.spr:
    movem.l (a0)+,d1-d7/a2
    movem.l d1-d7/a2,(a1)
    lea 32(a1),a1
    dbf d0,.spr
    movem.l (sp)+,d0-d7/a0-a2
.no_sprites:
    lea own_stack_top,sp
    clr.b g_iff
    move.w #$d400,-(a5)          ; real return address $00d4, exact kernel stack data
    jmp Z0038

; Main CPU ports. Handlers keep all game registers and the Z80 flags image.
bt_out_00:
    move.b d0,g_sound_latch
    rts
bt_out_01:                      ; (d5 / a0: scratch at an instruction's end)
    moveq #15,d5
    and.b d0,d5
    move.b d5,g_bank
    lsl.w #2,d5
    lea bt_dispatch_targets,a0      ; (gen.py: the banks' tables, 0 without code)
    move.l (a0,d5.w),g_wdispatch
    lea bt_winbases,a0
    move.l (a0,d5.w),g_winbase
    rts
bt_out_02:
    rts
bt_out_05:
    rts
bt_out_0f:
    rts
bt_out_03:
    move.b d0,g_coin_lockout
    rts
bt_out_04:
    move.b d0,g_control
    rts
bt_out_06:
    rts
bt_out_07:
    movem.l d0-d7/a0-a6,-(sp)
    move.b d0,mcu_command
    bsr mcu_send
    movem.l (sp)+,d0-d7/a0-a6
    rts
bt_out_08:
    move.b d0,g_scroll
    rts
bt_out_09:
    move.b d0,g_scroll+1
    rts
bt_out_0a:
    move.b d0,g_scroll+2
    rts
bt_out_0b:
    move.b d0,g_scroll+3
    rts
bt_out_0c:
    move.b d0,g_video_enable
    rts
bt_out_0d:
    move.l d0,-(sp)
    and.l #3,d0
    move.b d0,g_bg_bank
    lsl.w #8,d0
    lsl.w #4,d0
    add.l #g_bg+$4000,d0             ; (C000 is -$4000 as the signed index of the translated accesses)
    move.l d0,g_bgbase
    move.l (sp)+,d0
    rts
bt_out_0e:
    move.b d0,g_layout
    rts
; A translated write to the background (gen.py win_check): a1 = the byte in g_bg.  Its map entry goes to bg_noted
; (the renderer checks those cells), map_dirty (all of them) when the list is full.  All registers and the CCR kept.
BG_NOTES = 64
bg_note:
    move sr,-(sp)
    movem.l d0-d1,-(sp)
    move.l a1,d0
    sub.l #g_bg,d0
    lsr.w #1,d0                     ; (the entry: 2 bytes)
    move.w bg_noted_n,d1
    beq.s .add
    add.w d1,d1
    lea bg_noted-2,a1
    cmp.w (a1,d1.w),d0
    beq.s .done                     ; (the entry's other byte, written right after)
    move.w bg_noted_n,d1
    cmp.w #BG_NOTES,d1
    bhs.s .full
.add:
    addq.w #1,bg_noted_n
    add.w d1,d1
    lea bg_noted,a1
    move.w d0,(a1,d1.w)
.done:
    movem.l (sp)+,d0-d1
    move (sp)+,ccr
    rts
.full:
    st map_dirty
    bra.s .done

; Block instructions (gen.py block_win): when the source or the destination range of one meets C000-CFFF, the
; background bank is copied into the image there for it and back afterwards (bt_bg_post, which marks the map).
; d3 = HL, d2 = DE, d5.w = the count - 1; bt_bg_bwd: the ranges end at HL / DE.  All registers and the CCR kept.
bt_bg_bwd:
    movem.l d0/d7,-(sp)
    move.w d3,d0
    sub.w d5,d0
    bsr.s bg_meets
    bne.s bg_in
    move.w d2,d0
    sub.w d5,d0
    bra.s bg_dst
bt_bg_fwd:
    movem.l d0/d7,-(sp)
    move.w d3,d0
    bsr.s bg_meets
    bne.s bg_in
    move.w d2,d0
bg_dst:
    bsr.s bg_meets
    bne.s bg_in
    movem.l (sp)+,d0/d7
    rts
bg_in:
    movem.l d1-d6/a0-a2,-(sp)
    move.l g_bgbase,a0
    lea -$4000(a0),a0
    lea g_block+$4000,a1
    bsr.s bg_copy
    movem.l (sp)+,d1-d6/a0-a2
    st bg_mat
    movem.l (sp)+,d0/d7
    rts
; Z clear if the d5.w + 1 bytes from d0.w (mod 64K) meet C000-CFFF; uses d7
bg_meets:
    move.w d0,d7
    sub.w #$C000,d7
    cmp.w #$1000,d7
    blo.s .yes
    move.w #$C000,d7
    sub.w d0,d7                     ; (the bytes before C000)
    cmp.w d5,d7
    bls.s .yes
    moveq #0,d7
    rts
.yes:
    moveq #1,d7
    rts
bt_bg_post:
    move sr,-(sp)
    tst.b bg_mat
    bne.s .back
    move (sp)+,ccr
    rts
.back:
    movem.l d0-d7/a0-a2,-(sp)
    lea g_block+$4000,a0
    move.l g_bgbase,a1
    lea -$4000(a1),a1
    bsr.s bg_copy
    movem.l (sp)+,d0-d7/a0-a2
    clr.b bg_mat
    st map_dirty
    move (sp)+,ccr
    rts
; 4 KB (a0)+ -> (a1); uses d0-d7 / a2
bg_copy:
    moveq #$1000/32-1,d0
.c:
    movem.l (a0)+,d1-d7/a2
    movem.l d1-d7/a2,(a1)
    lea 32(a1),a1
    dbf d0,.c
    rts

hbl:
    rte
vbl:
    ifnd SIM
    borders_vbl
    endc
    movem.l d0-d7/a0,-(sp)
    addq.l #1,frame_counter
    ifnd AUTOPLAY                ; (the benchmark's inputs are set at each tick)
    bsr jagpad_poll              ; (the pads merged)
    jp_merge in_sys,bt_inputs,0
    jp_merge in_p1,bt_inputs+1,1
    jp_merge in_p2,bt_inputs+2,2
    endc
    bsr vbl_video
    cmp.b #32,vbl_pending
    bhs.s .cap
    addq.b #1,vbl_pending
    ; Six arcade ticks per five 50 Hz fields (60 Hz average).
    addq.b #1,tick_phase
    cmp.b #5,tick_phase
    blo.s .cap
    clr.b tick_phase
    addq.b #1,vbl_pending
.cap:
    if FRAMES
    cmp.l #FRAMES,frame_counter
    blo.s .go
    st quit_flag
.go:
    endc
    movem.l (sp)+,d0-d7/a0
    rte

	borders_handlers
	jagpad_text
	jagpad_maps
	borders_blit_go

    ifd DEBUG
; COUNTERS.BIN (words): VBLs, frames drawn, game ticks, 0 (was: background changes the hooks missed), the frames whose top border the VBL armed, the top border / palette on / bottom border
; / palette off events that started too late (engine/rt/borders.s), 0; then longs: blit_go's passes run in pieces,
; the text rows rebuilt, the frames a ring kept its text, the byte tables bake_pixels built
dbg_counters:
    lea dbg_buf,a0
    move.w frame_counter+2,(a0)+
    move.w cnt_renders,(a0)+
    move.w cnt_ticks,(a0)+
    clr.w (a0)+
    move.w bd_fallbacks,(a0)+
    move.w bd_late_top,(a0)+
    move.w bd_late_on,(a0)+
    move.w bd_late_low,(a0)+
    move.w bd_late_off,(a0)+
    clr.w (a0)+
    move.l bd_pieced,(a0)+
    move.l dbg_text_rows,(a0)+
    move.l dbg_text_kept,(a0)+
    move.l dbg_byte_luts,(a0)+
    clr -(sp)
    pea dbg_name
    move #$3c,-(sp)
    trap #1
    addq #8,sp
    move d0,d6
    pea dbg_buf
    move.l #36,-(sp)
    move d6,-(sp)
    move #$40,-(sp)
    trap #1
    lea 12(sp),sp
    move d6,-(sp)
    move #$3e,-(sp)
    trap #1
    addq #4,sp
    rts
dbg_name:
    dc.b "COUNTERS.BIN",0
    even
    else
dbg_counters:
    rts
    endc
    include "hardware.s"
    include "mcu.s"
    include "render.s"
    include "code_blktiger.s"
    include "rtlib.s"
z80_badpc:
z80_badjump:
z80_unsupported:
    ifd SIM
    bra.s z80_badpc
    else
    cmp.l #$ffff,d7
    bls.s .target
    moveq #0,d7
    move.w g_dispatch_pc,d7
.target:
    moveq #0,d0
    move.b g_bank,d0
    swap d0
    or.l d0,d7
    moveq #99,d0
    bra crash_common
    endc
z80_halt:
    jmp z80_badpc
    ifd SIM
sim_wait:
    bra.s sim_wait
sim_frame_done:
    bra.s sim_frame_done
sim_render_ret:
    bra.s sim_render_ret
    endc
    section data,data
bt_inputs:
    dc.b $ff,$ff,$ff,$ff,$6f,$ff
    even
g_bgbase:                        ; the background bank selected (out $0d) + $4000
    dc.l g_bg+$4000
bt_winbases:                     ; g_winbase of each bank: its copy + $8000 (the Z80 address - $10000 the offset)
N   set 0
    rept 16
    dc.l bank_rom+$8000+N*$4000
N   set N+1
    endr
bank_rom:
    incbin "banks.rom"
    cnop 0,4
g_block:                         ; the Z80 image (G_Z80 its middle): $8000-$ffff, then the fixed ROM in place
    ds.b $8000
    incbin "fixed.rom"
mcu_rom:
    incbin "mcu.rom"
    section bss,bss
old_ssp: ds.l 1
old_screen: ds.l 1
old_palette: ds.l 8
old_exceptions: ds.l 10
old_hbl: ds.l 1
old_vbl: ds.l 1
old_acia: ds.l 1
old_timer_a: ds.l 1
old_timer_b: ds.l 1
old_res: ds.b 1
old_hz: ds.b 1
old_linewid: ds.b 1
old_fine: ds.b 1
old_fa07: ds.b 1
old_fa09: ds.b 1
old_fa13: ds.b 1
old_fa15: ds.b 1
old_fa17: ds.b 1
old_fa19: ds.b 1
old_fa1b: ds.b 1
old_fa1d: ds.b 1
old_fa1f: ds.b 1
old_fa21: ds.b 1
	borders_vars
	jagpad_vars
quit_flag: ds.b 1
vbl_pending: ds.b 1
tick_phase: ds.b 1
render_skips: ds.b 1
    even
frame_dirty: ds.b 1
isr_stage: ds.b 1
g_iff: ds.b 1
g_ireg: ds.b 1
g_bank: ds.b 1
g_bg_bank: ds.b 1
bg_mat: ds.b 1                   ; the bank is in the image (a block instruction runs)
g_control: ds.b 1
g_video_enable: ds.b 1
g_layout: ds.b 1
g_scroll: ds.b 4
g_sound_latch: ds.b 1
g_coin_lockout: ds.b 1
g_mcu_response: ds.b 1
mcu_command: ds.b 1
ikbd_state: ds.b 1
joy0_state: ds.b 1
joy1_state: ds.b 1
sys_kbd: ds.b 1
p1_kbd: ds.b 1
p2_kbd: ds.b 1
p1_joy: ds.b 1
p2_joy: ds.b 1
in_sys: ds.b 1
in_p1: ds.b 1
in_p2: ds.b 1
    even
cnt_acia: ds.w 1
bg_noted_n: ds.w 1               ; the background entries written since the last frame (bg_note)
bg_noted: ds.w BG_NOTES
crash_vector: ds.w 1
crash_sp: ds.l 1
crash_regs: ds.l 16
crash_text: ds.b 512
frame_counter: ds.l 1
g_winbase: ds.l 1
g_wdispatch: ds.l 1
g_dispatch_pc: ds.w 1
cnt_renders: ds.w 1
cnt_ticks: ds.w 1
dbg_buf: ds.w 18
dbg_text_rows: ds.l 1
dbg_text_kept: ds.l 1
dbg_byte_luts: ds.l 1
g_iy: ds.w 1
g_fshadow: ds.w 1
    ds.b 16384
own_stack_top:
g_bg: ds.b $4000
bt_sprites: ds.b $200

