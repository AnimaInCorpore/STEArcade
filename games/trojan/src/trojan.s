; Trojan (Capcom 1986) for the Atari STE: the translated main Z80 (tools/gen.py), the NMI a frame at the idle point,
; the STE display (render.s).
KEY_ESC = $01
	ifnd PIC_TOP
PIC_TOP = 18				; the picture's first displayed line (240 lines centred like 1942's 256 at 10)
	endc
TA_DATA = 98
TA_NOPS = 84
PIC_LINES = 240
BD_PALETTE = 1
	ifnd FRAMES
FRAMES = 0
	endc
	ifnd MAX_SKIPS
MAX_SKIPS = 4				; arcade frames not drawn in a row while frames are pending (the game first)
	endc
	ifnd MAX_PENDING
MAX_PENDING = 3				; arcade frames that may wait (a game behind by more runs slower)
	endc

; Border removal and the palette on / off: engine/rt/borders.s (its events come early and sync themselves; every
; Blitter pass is short and HOG: borders_blit_go).
	section bss,bss
ring_area: ds.b RING_AREA		; (the display rings and buffers: render.s)
	section text,code
	include "borders.s"

; the pads (engine/rt/jagpad.s): SERVICE, P1, P2 bits as in key_table (bytes 0-2 of each long)
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
	include	"ikbd.s"
BUSY = $80
HOG = $40
G_Z80 = g_block+$8000			; a6: the Z80's address 0; $8000-$FFFF below it (signed word offsets)
Z_RAM = G_Z80-$10000			; + a Z80 address of $8000-$FFFF
Z_IN = Z_RAM+$F808			; SERVICE, P1, P2, DSWB, DSWA: the program reads them from the image
IDLE_PC = $0491
QUEUE = $CD82				; the task queue's read pointer (little endian): (it) = $FF when empty

	section text,code
start:
	clr.l -(sp)
	move #$20,-(sp)
	trap #1
	addq #6,sp
	move.l d0,old_ssp
	lea own_stack_top,sp
	lea own_stack_top-4096,a0	; (the unused part of the stack marked: the crash dump says how deep it went)
	move #1024-1,d0
.mark:
	move.l #$A5A5A5A5,(a0)+
	dbf d0,.mark
	bsr init_hardware
	bsr init_video
	bsr snd_init
	move.b #$ff,in_sys
	move.b #$ff,in_p1
	move.b #$ff,in_p2
	lea tr_inputs,a0
	move.b #$ff,(a0)+		; SERVICE
	move.b #$ff,(a0)+		; P1
	move.b #$ff,(a0)+		; P2
	move.b tr_dsw,(a0)+		; DSWB
	move.b tr_dsw+1,(a0)+		; DSWA
	bsr tr_put_inputs
	moveq #0,d0
	bsr tr_bank
	lea G_Z80,a6
	lea G_Z80-1,a5
	lea tr_fixed_dispatch,a4
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

; The dispatch through word tables (gen.py: a word per Z80 address, (the entry - the region's base) / 2): the fixed
; code in two regions ($0000-$3FFF, $4000-$7FFF: a4), the window through the bank's table (its base the long before
; it; g_wdispatch 0 for a bank without code).  d7.w = the Z80 address; a0 / d5 are free at a jump.
tr_dispatch:
	move.w d7,g_dispatch_pc
	bmi.s .window
	moveq #0,d5
	move.w d7,d5
	add.w d5,d5			; (N: from $4000)
	bmi.s .high
	move.w (a4,d5.l),d5
	add.l d5,d5
	lea tr_base_lo,a0
	jmp (a0,d5.l)
.high:
	move.w (a4,d5.l),d5
	add.l d5,d5
	lea tr_base_hi,a0
	jmp (a0,d5.l)
.window:
	cmp.w #$c000,d7
	bhs.s .bad
	move.l g_wdispatch,d5
	beq.s .bad
	move.l d5,a0
	moveq #0,d5
	move.w d7,d5
	add.w d5,d5			; ($8000-$bfff: 0-$7ffe)
	move.w (a0,d5.l),d5
	add.l d5,d5
	move.l -4(a0),a0
	jmp (a0,d5.l)
.bad:
	jmp z80_badpc

; The idle loop ($0491: ei / call $0498, which selects bank 0 and looks at the task queue at $A000 / jp $0491).
; The arcade's NMI (line 248, the vertical blank) is delivered here, when the queue is empty: the handler runs to its
; return (its `ret` comes back to $0491 with isr_stage set: then the foreground goes on with the tasks it queued).
; The IRQ of line 128 is not delivered: its handler is `di / ret`.  The schedule of tools/machine.py TrojanPort.
z80_hook:
	tst.b quit_flag
	bne quit
	tst.b isr_stage
	beq.s .normal
	clr.b isr_stage
	rts				; the handler returned: the tasks it queued now
.normal:
	moveq #0,d5
	move.b Z_RAM+QUEUE+1,d5
	lsl.w #8,d5
	move.b Z_RAM+QUEUE,d5
	cmp.b #$ff,(a6,d5.w)
	beq.s .idle
	rts				; (a task is ready)
.idle:
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
	bra.s .check
	endc
.deliver:
	subq.b #1,vbl_pending
	addq.w #1,cnt_ticks
	ifd AUTOPLAY
	bsr ap_inputs
	endc
	ifd PLAYBACK
	bsr pb_inputs
	endc
	st frame_dirty
	bsr tr_put_inputs
	btst #3,g_bankreg		; the NMI enabled (bankswitch bit 3)
	bne.s .nmi
	rts				; (no NMI: the foreground goes on)
.nmi:
	bsr snd_frame
	lea own_stack_top,sp		; (the hook's continuation dropped: the handler returns through the dispatch)
	st isr_stage
	move.w #$9104,-(a5)		; the return address $0491 (byte swapped, as a call pushes it)
	jmp Z0066

; tr_inputs (SERVICE, P1, P2, DSWB, DSWA: what the VBL, the benchmark or a test set) into the image, where the
; program reads them; the stores to $F808 and $F80C (the DMA, the sound latch) overwrite two of them there.
tr_put_inputs:
	move.l tr_inputs,Z_IN
	move.b tr_inputs+4,Z_IN+4
	rts

; The registers ($F80x): stores of `ld (nn),a` (gen.REG_HOOKS) call these; all registers and the CCR are kept but
; the scratch d5 / d7 / a0 at an instruction's end.
tr_dma:					; $F808: the sprite DMA (in the vertical blank: the NMI handler)
	tst.b isr_stage
	beq .out
	movem.l d1-d4/d6/a1-a2,-(sp)
	lea Z_RAM+$DE00,a0
	lea tr_sprites,a1
	rept $180/32
	movem.l (a0)+,d1-d7/a2
	movem.l d1-d7/a2,(a1)
	lea 32(a1),a1
	endr
	movem.l (sp)+,d1-d4/d6/a1-a2
	st sprites_new
.out:
	move.b tr_inputs,Z_IN		; (SERVICE again)
	rts
tr_sound:				; $F80C: the sound latch
	move.b d0,g_sound_latch
	st g_sound_new
	move.b tr_inputs+4,Z_IN+4	; (DSWA again)
	rts
tr_adpcm:				; $F80D: the ADPCM latch
	move.b d0,g_adpcm_latch
	rts
tr_bank:				; $F80E: flip (bit 0 = 0), the bank (bits 1-2), NMI enable (bit 3), sound reset (5)
	move.b d0,g_bankreg
	moveq #6,d5
	and.b d0,d5
	add.w d5,d5			; (the bank * 4)
	move.b d5,g_bank
	lea tr_dispatch_targets,a0	; (gen.py: the banks' tables, 0 without code)
	move.l (a0,d5.w),g_wdispatch
	lea tr_winbases,a0
	move.l (a0,d5.w),g_winbase
	rts

hbl:
	rte

vbl:
	ifnd SIM
	borders_vbl
	endc
	movem.l d0-d7/a0,-(sp)
	addq.l #1,frame_counter
	ifd DEBUG
	subq.w #1,dbg_tl_n		; every 100 VBLs: the arcade frames and the pictures so far (RATE.BIN, bench.sh)
	bgt.s .tl
	move.w #100,dbg_tl_n
	move.l dbg_tl_p,a0
	cmp.w #0,a0
	bne.s .tl1
	lea dbg_tl,a0
.tl1:
	cmp.l #dbg_tl_end,a0
	bhs.s .tl
	move.w cnt_ticks,(a0)+
	move.w cnt_renders,(a0)+
	move.l a0,dbg_tl_p
.tl:
	endc
	ifnd AUTOPLAY
	ifnd PLAYBACK
	bsr jagpad_poll			; (the pads merged)
	jp_merge in_sys,tr_inputs,0
	jp_merge in_p1,tr_inputs+1,1
	jp_merge in_p2,tr_inputs+2,2
	endc
	endc
	bsr vbl_video
	bsr snd_vbl
	cmp.b #MAX_PENDING,vbl_pending
	bhs.s .cap
	addq.b #1,vbl_pending
	; the arcade's 55.4 Hz on the STE's 50: eleven frames to ten VBLs
	addq.b #1,tick_phase
	cmp.b #10,tick_phase
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

	ifd AUTOPLAY
; (the benchmark build: the inputs by arcade frame, period 3000: a coin, the start, then walking right with attacks,
; jumps now and then; the lives kept: ref/bench schedule = tools/logic_test.py --auto)
ap_inputs:
	movem.l d0-d1,-(sp)
	moveq #0,d0
	move.w cnt_ticks,d0
	subq.w #1,d0
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
	move.b d1,tr_inputs
	moveq #-1,d1
	cmp.w #1000,d0
	blo.s .p1
	eor.b #1|16,d1
	ext.l d0
	divu #90,d0
	swap d0
	cmp.w #15,d0
	bhs.s .p1
	eor.b #32,d1
.p1:
	move.b d1,tr_inputs+1
	cmp.w #1000,d0
	blo.s .out
	move.b #3,Z_RAM+$CDA0		; (the lives)
.out:
	movem.l (sp)+,d0-d1
	rts
	endc

	ifd PLAYBACK
; The recorded play (tools/play_search.py, build/trojan/play_inputs.bin; engine/playbot.py: runs of count, SERVICE,
; P1, a count of 0 at the end): the inputs of the frame about to run, and from frame PB_PLAY on the bot's lives
; ($CDA0 = 3), as the bot had them.
PB_PLAY = 1000
pb_inputs:
	movem.l d0/a0,-(sp)
	tst.b pb_left
	bne.s .same
	move.l pb_ptr,a0
	cmp.w #0,a0
	bne.s .next
	lea pb_data,a0
.next:
	move.b (a0)+,pb_left
	bne.s .run
	st quit_flag			; (the recording is over)
	bra.s .out
.run:
	move.b (a0)+,pb_sys
	move.b (a0)+,pb_p1
	move.l a0,pb_ptr
.same:
	subq.b #1,pb_left
	move.b pb_sys,tr_inputs
	move.b pb_p1,tr_inputs+1
	move.b #$ff,tr_inputs+2
	moveq #0,d0
	move.w cnt_ticks,d0
	subq.l #1,d0
	cmp.w #PB_PLAY,d0
	blo.s .out
	move.b #3,Z_RAM+$CDA0
.out:
	movem.l (sp)+,d0/a0
	rts
	endc

	borders_handlers
	jagpad_text
	jagpad_maps
	borders_blit_go

	ifd DEBUG
; COUNTERS.BIN (words): VBLs, pictures drawn, arcade frames, 0, the frames whose top border the VBL armed, the top
; border / palette on / bottom border / palette off events that started too late (engine/rt/borders.s), 0; then a
; long: blit_go's passes run in pieces.  RATE.BIN: every 100 VBLs the arcade frames and the pictures so far.
dbg_counters:
	clr -(sp)
	pea dbg_name3
	move #$3c,-(sp)
	trap #1
	addq #8,sp
	move d0,d6
	pea dbg_tl
	move.l dbg_tl_p,d0
	sub.l #dbg_tl,d0
	bpl.s .tl_len
	moveq #0,d0
.tl_len:
	move.l d0,-(sp)
	move d6,-(sp)
	move #$40,-(sp)
	trap #1
	lea 12(sp),sp
	move d6,-(sp)
	move #$3e,-(sp)
	trap #1
	addq #4,sp
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
	clr -(sp)
	pea dbg_name
	move #$3c,-(sp)
	trap #1
	addq #8,sp
	move d0,d6
	pea dbg_buf
	move.l #24,-(sp)
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
dbg_name3:
	dc.b "RATE.BIN",0
	even
	endc

	include "hardware.s"
	include "render.s"
	include "sound.s"
	include "code_trojan.s"
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
	lsr.b #2,d0
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
	ifd PLAYBACK
pb_data:
	incbin "play_inputs.bin"
	even
	endc
tr_dsw:	dc.b $fc,$ff			; DSWB: upright, bonus 30000 60000, level 1; DSWA: 1 coin 1 credit, 3 lives, no
					; flip, continue (MAME's defaults; the tests patch them)
	even
tr_winbases:				; g_winbase of each bank: its copy + $8000 (the Z80 address - $10000 the offset)
N	set 0
	rept 4
	dc.l bank_rom+$8000+N*$4000
N	set N+1
	endr
bank_rom:
	incbin "banks.rom"
	cnop 0,4
g_block:				; the Z80 image (G_Z80 its middle): $8000-$FFFF, then the fixed ROM in place
	ds.b $8000
	incbin "fixed.rom"

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
frame_dirty: ds.b 1
isr_stage: ds.b 1
g_bankreg: ds.b 1			; the last $F80E value
g_bank: ds.b 1				; its bank * 4
g_sound_latch: ds.b 1
g_sound_new: ds.b 1
g_adpcm_latch: ds.b 1
sprites_new: ds.b 1			; a DMA since the last picture
fg_written: ds.b 1			; (set by the translated writers of the character RAM: gen.py)
bg_written: ds.b 1			; (the bg1 tile RAM)
pal_written: ds.b 1			; (the palette)
	ikbd_vars
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
	ifd DEBUG
dbg_tl_n: ds.w 1
dbg_tl_p: ds.l 1
dbg_tl: ds.l 200			; (20000 VBLs)
dbg_tl_end:
	endc
	ifd PLAYBACK
pb_ptr: ds.l 1
pb_left: ds.b 1
pb_sys: ds.b 1
pb_p1: ds.b 1
	even
	endc
dbg_buf: ds.w 18
g_iy: ds.w 1
g_fshadow: ds.w 1
	ds.b 8192
own_stack_top:
tr_sprites: ds.b $180
tr_inputs: ds.b 6			; the sprite buffer (the DMA's copy)
