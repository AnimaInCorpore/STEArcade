; 1943: The Battle of Midway (Euro).  The translated main Z80 program, its cooperative tasks, the i8751
; firmware, the STE display.
;
; The schedule (tools/machine.py run_frame_port is the same in Python): the translated program runs its tasks;
; when the scheduler finds none ready (the hook at IDLE_PC) the runtime draws the frame and delivers a tick: the
; line 144 IRQ (SYSTEM bit 3, the VBL, clear), the MCU's INT1, the line 240 IRQ (bit 3 set), each run to its
; return to the idle point with a token on the Z80 stack; then the tasks they made ready run.
KEY_ESC = $01
PIC_TOP = 10                     ; (the picture: 256 lines from the 10th displayed line; Commando's timer values)
TA_DATA = 98
TA_NOPS = 84
TA2_DATA = 28
TA3_DATA = 200
arm_border_timers macro
    clr.b $fffffa19.w
    clr.b $fffffa1b.w
    move.b #228,$fffffa21.w
    move.b #8,$fffffa1b.w
    clr.b ta_state
    move.b #TA_DATA,$fffffa1f.w
    move.b #4,$fffffa19.w
    st border_a
    st border_b
    endm
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
    lea fixed_rom,a0
    lea G_Z80,a1
    move #$8000/4-1,d0
.copyrom:
    move.l (a0)+,(a1)+
    dbf d0,.copyrom
    bsr init_hardware
    bsr init_video
    bsr mcu_init
    bsr init_dispatch
    move.b #$ff,in_sys
    move.b #$ff,in_p1
    move.b #$ff,in_p2
    moveq #0,d0
    bsr g_control_w
    lea G_Z80,a6
    lea G_Z80-1,a5
    lea g_fixed_dispatch,a4
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

; Natural-PC dispatch: fixed table 128 KB, a 64 KB table per ROM bank with code.
g_dispatch:
    move.w d7,g_dispatch_pc
    and.l #$ffff,d7
    cmp.w #$8000,d7
    bhs.s .window
    lsl.l #2,d7
    move.l (a4,d7.l),-(sp)
    rts
.window:
    cmp.w #$c000,d7
    blo.s .valid
    jmp z80_badpc
.valid:
    sub.w #$8000,d7
    lsl.l #2,d7
    move.l a0,-(sp)
    move.l g_wdispatch,a0
    move.l (a0,d7.l),d7
    move.l (sp)+,a0
    move.l d7,-(sp)
    rts

init_dispatch:
    lea g_fixed_dispatch,a0
    move.l #z80_badpc,d0
    move.l #32768/4-1,d1
    bsr fill_dispatch
    lea g_invalid_dispatch,a0
    move.l #(G_WINDOW_TABLES*16384)/4-1,d1
    bsr fill_dispatch
    lea g_fixed_dispatch,a0
    lea g_entries_fixed,a1
    bsr scatter
    lea g_entry_banks,a2
    lea g_dispatch_targets,a3
    moveq #7,d3
.bank:
    move.l (a2)+,a1
    move.l (a3)+,a0
    bsr scatter
    dbf d3,.bank
    rts
fill_dispatch:
    move.l d0,(a0)+
    move.l d0,(a0)+
    move.l d0,(a0)+
    move.l d0,(a0)+
    subq.l #1,d1
    bpl.s fill_dispatch
    rts
scatter:
    moveq #0,d1
.next:
    move.w (a1)+,d1
    cmp.w #$ffff,d1
    beq.s .done
    lsl.l #2,d1
    move.l (a1)+,(a0,d1.l)
    moveq #0,d1
    bra.s .next
.done:
    rts

; The scheduler has scanned all sixteen task records with no ready task.
z80_hook:
    tst.b quit_flag
    bne quit
    move.b isr_stage,d7
    beq.s .normal
    subq.b #1,d7
    beq.s .tasks
    ; the line 144 IRQ returned: the MCU's INT1, then the line 240 IRQ
    move.b #1,isr_stage
    movem.l d0-d7/a0-a6,-(sp)
    bsr mcu_vblank
    movem.l (sp)+,d0-d7/a0-a6
    bset #3,g_inputs
    lea own_stack_top,sp
    move.w #$d400,-(a5)          ; real return address $00d4
    jmp Z0038
.tasks:
    clr.b isr_stage
    bclr #3,g_inputs
    rts                         ; both handlers returned: run the tasks before ending this tick
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
    bsr autoplay
    endc
    st frame_dirty
    move.b #2,isr_stage
    bclr #3,g_inputs
    lea own_stack_top,sp
    move.w #$d400,-(a5)          ; real return address $00d4, exact kernel stack data
    jmp Z0038

    ifd AUTOPLAY
; (benchmark build: the inputs of logic_test.py's default schedule, period 3000 ticks: coin, start, then fire
; and left / right)
autoplay:
    movem.l d0-d1,-(sp)
    moveq #0,d0
    move.w cnt_ticks,d0
    divu #3000,d0
    swap d0
    moveq #-1,d1
    cmp.w #900,d0
    blo.s .sys
    cmp.w #905,d0
    bhs.s .start
    and.b #~$40,d1
.start:
    cmp.w #940,d0
    blo.s .sys
    cmp.w #945,d0
    bhs.s .sys
    and.b #~1,d1
.sys:
    and.b #~8,d1
    move.b g_inputs,d0
    and.b #8,d0
    or.b d0,d1                   ; (the VBL bit stays the runtime's)
    move.b d1,g_inputs
    moveq #0,d0
    move.w cnt_ticks,d0
    divu #3000,d0
    swap d0
    moveq #-1,d1
    cmp.w #1000,d0
    blo.s .p1
    and.b #~16,d1
    ext.l d0
    divu #180,d0
    swap d0
    cmp.w #90,d0
    blo.s .left
    and.b #~1,d1
    bra.s .p1
.left:
    and.b #~2,d1
.p1:
    move.b d1,g_inputs+1
    movem.l (sp)+,d0-d1
    rts
    endc

; The latches the program writes with ld (nn),a.  Called after the store with A in d0: every register and the
; CCR (the flags the translation may keep there) are kept.
g_control_w:                    ; c804: bank (bits 2-4), sound reset, flip, characters on
    move sr,-(sp)
    movem.l d0/d7/a0,-(sp)
    move.b d0,g_control
    lsr.b #2,d0
    and.l #7,d0
    move.b d0,g_bank
    move.l d0,d7
    lsl.w #2,d7
    lea g_dispatch_targets,a0
    move.l (a0,d7.w),g_wdispatch
    swap d0
    lsr.l #2,d0                  ; (bank * $4000)
    add.l #bank_rom+$8000,d0
    move.l d0,g_winbase
    movem.l (sp)+,d0/d7/a0
    rtr
g_dma:                          ; c806: the sprite list buffered (the 128 entries of 4 bytes, one per 32 bytes)
    move sr,-(sp)
    movem.l d0/a0-a1,-(sp)
    lea g_block+$7000,a0
    lea g_sprites,a1
SPR set 0
    rept 128
    move.l SPR(a0),(a1)+
SPR set SPR+32
    endr
    addq.w #1,dma_count
    movem.l (sp)+,d0/a0-a1
    rtr
g_mcu_w:                        ; c807: the command to the MCU (it answers at its next INT1)
    move.b d0,mcu_command
    rts
g_layer_w:                      ; d806: front layer, back layer, sprites on
    move.b d0,g_layers
    rts

hbl:
    rte
vbl:
    ifnd SIM
    arm_border_timers
    endc
    movem.l d0-d7/a0,-(sp)
    addq.l #1,frame_counter
    ifnd AUTOPLAY                ; (the benchmark's inputs are set at each tick)
    move.b in_sys,d0
    and.b #~8,d0
    move.b g_inputs,d1
    and.b #8,d1
    or.b d1,d0                   ; (the VBL bit stays the runtime's)
    move.b d0,g_inputs
    move.b in_p1,g_inputs+1
    move.b in_p2,g_inputs+2
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

wait_borders:
    ifnd SIM
.again:
    tst.b border_a
    bne.s .again
    cmp.b #6,$fffffa21.w
    bhi.s .done
    tst.b border_b
    bne.s .again
.done:
    endc
    rts

; wait_heavy: a long HOG blit may start only in the visible area: after the top border is open and at least 10
; lines before the bottom border's Timer B event.  Started later, it would delay that event or the VBL that arms
; Timer A, and the border would stay closed (a jump of the picture).  Short blits use wait_borders.
wait_heavy:
    ifnd SIM
.again:
    tst.b border_a
    bne.s .again                 ; the top border is not open yet
    tst.b border_b
    beq.s .again                 ; the bottom border is open already: wait for the next frame's top
    cmp.b #10,$fffffa21.w
    bls.s .again                 ; too close to the bottom border
    endc
    rts

timer_a:
	tst.b	ta_state
	bne	timer_a_later
	move	#$2100,sr		; Enable HBL
	stop	#$2100			; Wait for HBL
	move	#$2700,sr		; Stop all interrupts
	clr.b	$fffffa19.w		; Stop Timer A
	rept TA_NOPS
	nop
	endr
	clr.b	$ffff820a.w		; Remove the top border
	rept 9
	nop
	endr
	move.b	#2,$ffff820a.w
	move.b	#1,ta_state		; the next event: the palette on
	move.b	#TA2_DATA,$fffffa1f.w
	move.b	#4,$fffffa19.w
	rte

timer_a_later:
	movem.l	d0-d7,-(sp)
	clr.b	$fffffa19.w
	cmp.b	#1,ta_state
	bne.s	.off
	movem.l	shown_pal,d0-d7
	movem.l	d0-d7,$ffff8240.w
	clr.b	border_a		; (blits may start now: a HOG blit before would delay the palette, the first line flickers)
	move.b	#2,ta_state		; the next event: the palette off
	move.b	#TA3_DATA,$fffffa1f.w
	move.b	#7,$fffffa19.w
	bra.s	.out
.off:	movem.l	black_pal,d0-d7
	movem.l	d0-d7,$ffff8240.w
	move.b	#3,ta_state
.out:	movem.l	(sp)+,d0-d7
	rte

; Bottom border removal (Timer B)

timer_b:
	movem.l	d0/a0,-(sp)
	lea	$fffffa21.w,a0
	move.b	(a0),d0
.wait1:	cmp.b	(a0),d0
	beq.s	.wait1
	clr.b	$ffff820a.w
	moveq	#2,d0
.wait2:	nop
	dbf	d0,.wait2
	nop
	nop
	nop
	nop
	nop
	move.b	#2,$ffff820a.w
	move.b	(a0),d0
.wait3:	cmp.b	(a0),d0
	beq.s	.wait3
	movem.l	(sp)+,d0/a0
	clr.b	border_b
	rte

    ifd DEBUG
; COUNTERS.BIN (words): VBLs, frames drawn, game ticks, sprite list buffers, MCU replies
dbg_counters:
    lea dbg_buf,a0
    move.w frame_counter+2,(a0)+
    move.w cnt_renders,(a0)+
    move.w cnt_ticks,(a0)+
    move.w dma_count,(a0)+
    move.w mcu_transactions,(a0)+
    clr -(sp)
    pea dbg_name
    move #$3c,-(sp)
    trap #1
    addq #8,sp
    move d0,d6
    pea dbg_buf
    move.l #10,-(sp)
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
    include "code_1943.s"
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
g_inputs:
    dc.b $ff,$ff,$ff,$f8,$ff     ; SYSTEM (bit 3: VBL, the runtime's), P1, P2, DSWA, DSWB (the reference's)
    even
bank_rom:
    incbin "banks.rom"
fixed_rom:
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
border_a: ds.b 1
border_b: ds.b 1
ta_state: ds.b 1
quit_flag: ds.b 1
vbl_pending: ds.b 1
tick_phase: ds.b 1
render_skips: ds.b 1
    even
frame_dirty: ds.b 1
isr_stage: ds.b 1
g_ireg: ds.b 1
g_bank: ds.b 1
g_control: ds.b 1
g_layers: ds.b 1
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
dma_count: ds.w 1
dbg_buf: ds.w 8
g_iy: ds.w 1
g_fshadow: ds.w 1
    ds.b 16384
own_stack_top:
g_block: ds.b $10000
g_sprites: ds.b 512
g_fixed_dispatch: ds.l 32768
