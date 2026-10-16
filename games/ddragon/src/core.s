; The runtime of Double Dragon's translated main program (included by ddragon.s): the context, the port's schedule of
; one arcade frame (port_frame, as tools/machine.py DDragonPort), the hooks, the dispatcher, the ROM bank, the I/O.
;
; Registers in translated code (engine/m6809x.py): d0 A, d1 B, d2 X, d3 Y, d4 U, a5 = S as a pointer (g_mem + S),
; a6 = cur_ctx (the context of the bank selected), a3 = a4 = g_mem (VB of slots 0 and 1), a2 = PB[7]; d5 d6 d7 a0 a1 scratch.

; ---- the context block (engine/m6809x.py's offsets) ----
PB = 0				; 8 longs: the 68000 address of the page in each slot
VB = 32				; 8 longs: PB - slot * $2000
TBL = 64			; 8 longs: the dispatcher's table of the page in each slot
PID = 96			; 8 words: the virtual page in each slot
CCHI = 112			; the CC byte's E F H I bits (6809 positions)
R_D0 = 116			; the registers while the program waits: d0-d4 (5 longs)
R_A5 = 136
R_SR = 140
TABLES = 152			; the page tables of the dispatcher
CTXSIZE = 160
CTX_STRIDE = 256		; (ctx_banks: a context per ROM bank, its slots 2 and 3 the bank's pages)

PH_FG = 0			; port_phase: the foreground
PH_NMI = 1			; in the NMI handler
PH_FIRQ = 2			; in the FIRQ handler
PH_FIRST = 3			; the foreground's first instruction after the interrupts (no hook stops there)

	include	"gen_info.s"
	include	"mcu_info.s"

	section text,code
init_context:
	move.l #main_badpc,bad_table_base
	moveq #7,d0			; a context per bank (main_bank_w switches a6), bank 0's last
.bk:	move.w d0,d1
	lsl.w #8,d1			; (CTX_STRIDE)
	lea ctx_banks,a6
	add.w d1,a6
	move.l #main_page_tables,TABLES(a6)
	lea g_mem,a0
	moveq #0,d6			; the fixed slots 0, 1, 4-7: page = slot
.s:	move.w d6,d7
	add.w d7,d7
	add.w d7,d7			; slot * 4
	move.l d6,d5
	mulu #$2000,d5
	lea (a0,d5.l),a1
	move.l a1,PB(a6,d7.w)
	move.l a0,VB(a6,d7.w)
	move.w d6,d5
	add.w d5,d5
	move.w d6,PID(a6,d5.w)
	move.l TABLES(a6),a1
	move.l (a1,d7.w),TBL(a6,d7.w)
	addq.w #1,d6
	cmp.w #8,d6
	bne.s .s
	bsr bank_set			; (slots 2 and 3: the bank's pages)
	move.b #$50,CCHI(a6)		; (reset: I and F)
	clr.w R_SR(a6)
	lea R_D0(a6),a0
	moveq #5-1,d1
.c:	clr.l (a0)+
	dbf d1,.c
	move.l #g_mem,R_A5(a6)
	dbf d0,.bk
	move.l a6,cur_ctx
	rts

; d0.b = the bank (0-7): slots 2 and 3 get pages 8 + 2 * bank and 9 + 2 * bank (d5-d7 a0 a1 used)
bank_set:
	moveq #7,d5
	and.b d0,d5
	move.w d5,d6
	mulu #$4000,d6
	lea g_banks,a0
	add.l d6,a0			; slot 2's page
	add.w d5,d5
	addq.w #8,d5			; its page number
	move.w d5,PID+4(a6)
	move.l a0,PB+8(a6)
	lea -$4000(a0),a1
	move.l a1,VB+8(a6)
	move.l TABLES(a6),a1
	move.w d5,d7
	add.w d7,d7
	add.w d7,d7
	move.l (a1,d7.w),TBL+8(a6)
	addq.w #1,d5
	move.w d5,PID+6(a6)
	lea $2000(a0),a0
	move.l a0,PB+12(a6)
	lea -$6000(a0),a1
	move.l a1,VB+12(a6)
	move.l TABLES(a6),a1
	addq.w #4,d7
	move.l (a1,d7.w),TBL+12(a6)
	rts

; ---- the schedule: one arcade frame (tools/machine.py DDragonPort.run_frame_port) ----
port_frame:
	movem.l d0-d7/a0-a6,-(sp)
	move.l cur_ctx,a6
	tst.b port_booted
	bne.s .booted
	st port_booted
	move.b #PH_FG,port_phase	; the boot: from the reset vector to the first wait
	bsr enter_reset
.booted:
	move.b #1,port_vblank
	bsr enter_nmi			; NMI: the entire state, E I F set
	tst.b port_returned
	beq.s .done			; (the handler restarted the foreground: it waits already)
	btst #6,CCHI(a6)
	bne.s .fg			; (F masked: no FIRQ)
	bsr enter_firq
	tst.b port_returned
	beq.s .done
.fg:	move.b #PH_FIRST,port_phase
	bsr enter_idle
.done:	move.l a6,cur_ctx		; (the bank selected now: main_bank_w only switches a6)
	movem.l (sp)+,d0-d7/a0-a6
	rts

; The translated code from a 6809 pc (the dispatch); back here (rts) when a hook says the program waits or an
; interrupt returned.  The 68000 stack is the same at every hook.
enter_reset:
	bsr restore_regs
	move.w R_SR(a6),d7
	move.w d7,ccr
	jmp MAIN_RESET

enter_nmi:
	move.b #PH_NMI,port_phase
	bsr restore_regs
	move.l a5,port_expect		; (the RTI back at the idle point leaves S as it was)
	move.w port_idle_pc,d7
	move.b d7,-(a5)			; PC
	lsr.w #8,d7
	move.b d7,-(a5)
	move.b d4,-(a5)			; U
	move.w d4,d7
	lsr.w #8,d7
	move.b d7,-(a5)
	move.b d3,-(a5)			; Y
	move.w d3,d7
	lsr.w #8,d7
	move.b d7,-(a5)
	move.b d2,-(a5)			; X
	move.w d2,d7
	lsr.w #8,d7
	move.b d7,-(a5)
	clr.b -(a5)			; DP
	move.b d1,-(a5)			; B
	move.b d0,-(a5)			; A
	bsr cc_byte			; CC with E
	or.b #$80,d7
	move.b d7,-(a5)
	or.b #$D0,CCHI(a6)		; E I F
	move.w R_SR(a6),d7
	move.w d7,ccr
	jmp MAIN_NMI

enter_firq:
	move.b #PH_FIRQ,port_phase
	bsr restore_regs
	move.l a5,port_expect
	move.w port_idle_pc,d7
	move.b d7,-(a5)			; PC
	lsr.w #8,d7
	move.b d7,-(a5)
	bsr cc_byte			; CC, E clear
	and.b #$7F,d7
	move.b d7,-(a5)
	and.b #$7F,CCHI(a6)
	or.b #$50,CCHI(a6)		; I F
	move.w R_SR(a6),d7
	move.w d7,ccr
	jmp MAIN_FIRQ

enter_idle:				; the foreground at its idle point (the hook there runs its instruction)
	bsr restore_regs
	move.w port_idle_pc,d7
	move.w R_SR(a6),d5
	move.w d5,ccr
	jmp main_dispatch

; d7.b = the 6809 CC: E F H I from CCHI, N Z V C from R_SR
cc_byte:
	move.b CCHI(a6),d7
	and.b #$F0,d7
	move.b R_SR+1(a6),d6
	and.b #$0F,d6
	or.b d6,d7
	rts

restore_regs:
	movem.l R_D0(a6),d0-d4
	move.l R_A5(a6),a5
	lea g_mem,a3
	move.l a3,a4
	move.l PB+28(a6),a2
	rts

; ---- the hooks (gen.HOOKS): the instruction at the hook's pc replaced by a jump here, the CCR as the code left it.
; hook_wait pc,flag: the program waits there while its condition holds (port_wait: the registers saved, back to
; port_frame's caller); in an interrupt, the pc it came from with S as it was means the handler returned.
; HOOK_ENTRY pc: (d5 = the SR) the interrupt's return, the restart of the foreground by an interrupt, the first
; instruction of the foreground; falls through when the program goes on.
HOOK_ENTRY macro
	move.w sr,d5
	cmp.b #PH_FIRST,port_phase
	beq.s .first\@
	tst.b port_phase
	beq.s .fg\@
	cmp.w #\1,port_idle_pc		; (an interrupt: back at the idle point with S as it was?)
	bne.s .fg\@
	cmp.l port_expect,a5
	bne.s .fg\@
	st port_returned
	bra port_save
.first\@:
	move.b #PH_FG,port_phase
	bra \2
.fg\@:
	endm

; (the condition said wait: idle here)
HOOK_IDLE macro
	move.w #\1,port_idle_pc
	sf port_returned
	bra port_save
	endm

port_save:
	move.w d5,R_SR(a6)
	movem.l d0-d4,R_D0(a6)
	move.l a5,R_A5(a6)
	rts

; the 6809's load flags (N Z, V clear) of the byte in \1 with C from the SR in d5
LDFLAGS	macro
	tst.b \1
	move.w sr,d6
	and.w #1,d5
	or.w d5,d6
	move.w d6,ccr
	endm

hook_83E9:				; LDA <$22; ANDA #$02; BEQ $83E9 (wait for the NMI's update)
	HOOK_ENTRY $83E9,go_83E9
	btst #1,$22(a3)
	bne.s go_83E9
	HOOK_IDLE $83E9
go_83E9:	move.b $22(a3),d0
	LDFLAGS d0
	jmp NEXT_83E9

hook_8541:				; the same at $8541
	HOOK_ENTRY $8541,go_8541
	btst #1,$22(a3)
	bne.s go_8541
	HOOK_IDLE $8541
go_8541:	move.b $22(a3),d0
	LDFLAGS d0
	jmp NEXT_8541

hook_864C:				; the same at $864C
	HOOK_ENTRY $864C,go_864C
	btst #1,$22(a3)
	bne.s go_864C
	HOOK_IDLE $864C
go_864C:	move.b $22(a3),d0
	LDFLAGS d0
	jmp NEXT_864C

hook_B7AD:				; LDB $3802; ANDB #$08; BEQ $B7AD (wait for the vertical blank: always)
	HOOK_ENTRY $B7AD,go_B7AD
	HOOK_IDLE $B7AD
go_B7AD:	bsr extra_byte
	move.b d7,d1
	LDFLAGS d1
	jmp NEXT_B7AD

hook_EEB0:				; LDA $3802; ANDA #$08; BEQ $EEB0 (the same)
	HOOK_ENTRY $EEB0,go_EEB0
	HOOK_IDLE $EEB0
go_EEB0:	bsr extra_byte
	move.b d7,d0
	LDFLAGS d0
	jmp NEXT_EEB0

hook_B7A5:				; LDB $3802; ANDB #$08; BNE $B7A5: the vertical blank ends here (the foreground)
	move.w sr,d5
	tst.b port_phase
	bne.s .k
	clr.b port_vblank
.k:	bsr extra_byte
	move.b d7,d1
	LDFLAGS d1
	jmp NEXT_B7A5

hook_89C7:				; LDA $3801 in the FIRQ's wait for the coins' release: the port releases them
	move.w sr,d5
	clr.b port_coins
	bsr p2_byte
	move.b d7,d0
	LDFLAGS d0
	jmp NEXT_89C7

; ---- natives (gen.NATIVES) ----
; bank 0 $4205-$420F: LDX #0; LDA #0; then B times PSHU X; PSHU X,A (five zero bytes down from U), each byte in the
; shared RAM's 512 bytes (U runs from $2081 + 5 * the total, past $21FF into the mirrors).  The PULS CC,D,X,U,PC at
; $4211 restores the registers; A, B, X and U as the loop leaves them all the same.
native_clear_sprites:
	movem.l d5/a0,-(sp)
	lea g_mem+$2000,a0
.e:	moveq #5-1,d5
.b:	subq.w #1,d4
	move.w d4,d7
	and.w #$1FF,d7
	clr.b (a0,d7.w)
	dbf d5,.b
	subq.b #1,d1
	bne.s .e
	movem.l (sp)+,d5/a0
	moveq #0,d0
	moveq #0,d2
	move #$04,ccr			; (DECB to 0: Z)
	jmp CLEAR_SPRITES_END

; bank 0 $4231-$423F: LDX #$2081; LDY #$2800; then LDD ,X++; STD ,Y++ until X = $21FD: the MCU's 75 sprite entries
; (380 bytes) into the sprite RAM; then the RTS at $4241.  D the last word, X $21FD, Y $297C, CMPX's flags (Z).
native_copy_sprites:
	lea g_mem+$2081,a0
	lea g_mem+$2800,a1
	moveq #380/4-1,d7
.c:	move.b (a0)+,(a1)+
	move.b (a0)+,(a1)+
	move.b (a0)+,(a1)+
	move.b (a0)+,(a1)+
	dbf d7,.c
	st spr_written
	move.b g_mem+$21FB,d0
	move.b g_mem+$21FC,d1
	move.w #$21FD,d2
	move.w #$297C,d3
	move #$04,ccr
	jmp COPY_SPRITES_END

; The bank selectors $BB40 (ORA #$20), $FC82 (ORA #$A0), $FC8F (ANDA #$1F), $FF80 (ORA #$80): PSHS A; LDA <$3A;
; ORA / ANDA #n; STA <$3A; STA $3808; PULS A,PC.  The bank register's copy $3A changed and written, A kept, the flags
; of the value (N Z, V clear, C kept); the byte PSHS left below S written too; back through the return address.
BANK_NATIVE macro
	move.w sr,-(sp)
	move.b d0,-1(a5)		; (PSHS A's byte, below S once pulled)
	move.b $3A(a3),d5
	\1.b #\2,d5
	move.b d5,$3A(a3)
	move.b d5,-(sp)
	bsr main_bank_w
	move.b (sp)+,d5
	move.w (sp)+,d6
	and.w #1,d6			; (C kept)
	tst.b d5
	move.w sr,d7
	and.w #$FE,d7
	or.w d6,d7
	move.w d7,-(sp)
	moveq #0,d7
	move.b (a5)+,d7			; PC
	lsl.w #8,d7
	move.b (a5)+,d7
	move.w (sp)+,ccr
	jmp main_dispatch
	endm
native_bank_BB40:
	BANK_NATIVE or,$20
native_bank_FC82:
	BANK_NATIVE or,$A0
native_bank_FC8F:
	BANK_NATIVE and,$1F
native_bank_FF80:
	BANK_NATIVE or,$80

; ---- the dispatcher: d7.w = a 6809 pc, through the table of the page in its slot (TBL); the CCR kept ----
main_dispatch:
	move.w sr,d5
	move.w d7,d6
	rol.w #3,d6
	and.w #7,d6
	add.w d6,d6
	add.w d6,d6
	move.l TBL(a6,d6.w),a0
	and.w #$1FFF,d7
	add.w d7,d7
	moveq #0,d6
	move.w (a0,d7.w),d6
	add.l d6,d6
	move.l -4(a0),a0		; (the page's base)
	move.w d5,ccr
	jmp (a0,d6.l)

main_dispatch_nf:
	move.w d7,d6
	rol.w #3,d6
	and.w #7,d6
	add.w d6,d6
	add.w d6,d6
	move.l TBL(a6,d6.w),a0
	and.w #$1FFF,d7
	add.w d7,d7
	moveq #0,d6
	move.w (a0,d7.w),d6
	add.l d6,d6
	move.l -4(a0),a0
	jmp (a0,d6.l)

main_badpc:
main_unsupported:
	move.w d7,badpc
	move.w d6,badslot
    ifd SIM
sim_badpc:
	bra.s sim_badpc
    else
	bra port_crash
    endc

; ---- I/O ($3800-$380F): d7.w = the address; main_io_r: the byte in d7; main_io_w: d5.b = the value.  Every other
; register is kept. ----
main_io_r:
	cmp.w #$3800,d7
	bcs.s .mem
	beq.s .p1
	cmp.w #$3801,d7
	beq.s .p2
	cmp.w #$3802,d7
	beq.s .ex
	cmp.w #$3803,d7
	beq.s .d0
	cmp.w #$3804,d7
	beq.s .d1
	cmp.w #$4000,d7
	bcc.s .rom
	moveq #-1,d7
	and.l #$FF,d7
	rts
.rom:	move.l a0,-(sp)			; $4000-$FFFF (a site that also reads I/O): the ROM through the slot's page
	move.l d6,-(sp)
	and.l #$FFFF,d7
	move.w d7,d6
	rol.w #3,d6
	and.w #7,d6
	add.w d6,d6
	add.w d6,d6
	move.l 32(a6,d6.w),a0
	move.l (sp)+,d6
	move.b (a0,d7.l),d7
	and.l #$FF,d7
	move.l (sp)+,a0
	rts
.p1:	moveq #0,d7
	move.b in_bytes+0,d7
	rts
.p2:	bra p2_byte
.ex:	bra extra_byte
.d0:	moveq #0,d7
	move.b in_bytes+3,d7
	rts
.d1:	moveq #0,d7
	move.b in_bytes+4,d7
	rts
.mem:	move.l a0,-(sp)			; below $3800: memory; $2000-$27FF the shared RAM, mirrored every 512 bytes
	lea g_mem,a0
	cmp.w #$2000,d7
	bcs.s .plain
	cmp.w #$2800,d7
	bcc.s .plain
	and.w #$1FF,d7
	lea $2000(a0),a0
.plain:	move.b (a0,d7.w),d7
	and.w #$FF,d7
	move.l (sp)+,a0
	rts

; $3801: P2 with the pressed coins (bits 6, 7)
p2_byte:
	move.l d6,-(sp)
	moveq #0,d7
	move.b in_bytes+1,d7
	moveq #$C0-256,d6
	and.b port_coins,d6
	not.b d6
	and.b d6,d7
	move.l (sp)+,d6
	rts

; $3802: the buttons 3 and service, bit 3 the port's vertical blank, bit 4 low = the sub CPU's bus free
extra_byte:
	move.l d6,-(sp)
	moveq #0,d7
	move.b in_bytes+2,d7
	and.b #$07,d7
	btst #0,port_coins
	beq.s .ns
	and.b #$FE,d7			; (service pressed: bit 0 low)
.ns:
	tst.b port_vblank
	beq.s .nv
	or.b #$08,d7
.nv:	move.b g_bankreg,d6
	btst #4,d6
	bne.s .free
	btst #3,d6
	beq.s .free
	or.b #$10,d7
.free:	move.l (sp)+,d6
	rts

; main_bank_w: a static store to $3808 (gen.STATIC_WRITE; d5 = the value): the bank register; when the bank changes,
; a6 becomes that bank's context (ctx_banks: its slots 2 and 3 the bank's pages).  Keeps every register but d5-d7 / a0
; (and a6).
main_bank_w:
	move.b d5,g_bankreg
	lsr.b #3,d5
	and.w #$1C,d5			; (the bank * 4)
	move.l ctx_ptrs(pc,d5.w),a0
	cmp.l a0,a6
	beq.s .same
	move.b CCHI(a6),CCHI(a0)	; (the CC's E F H I go on; the saved registers are only read where saved)
	move.l a0,a6
.same:	rts
ctx_ptrs:
N	set 0
	rept 8
	dc.l ctx_banks+N*CTX_STRIDE
N	set N+1
	endr

main_io_w:
	cmp.w #$3800,d7
	bcc.s .io
	move.l a0,-(sp)			; below $3800: memory ($1400-$17FF nothing); the shared RAM mirrored
	lea g_mem,a0
	cmp.w #$2000,d7
	bcs.s .low
	cmp.w #$2800,d7
	bcc.s .wr
	and.w #$1FF,d7
	lea $2000(a0),a0
	bra.s .wr
.low:	cmp.w #$1400,d7
	bcs.s .wr
	cmp.w #$1800,d7
	bcs.s .none
.wr:	move.b d5,(a0,d7.w)
.none:	move.l (sp)+,a0
	rts
.io:	cmp.w #$3808,d7
	beq.s .bank
	cmp.w #$3809,d7
	beq.s .sx
	cmp.w #$380A,d7
	beq.s .sy
	cmp.w #$380E,d7
	beq.s .snd
	cmp.w #$380F,d7
	beq.s .mcu
	rts
.bank:	bra main_bank_w
.sx:	move.b d5,g_scroll_lo
	rts
.sy:	move.b d5,g_scroll_lo+1
	rts
.snd:	move.l a0,-(sp)			; the sound latch: a ring of commands (the sound player; the tests)
	move.l d6,-(sp)
	moveq #0,d6
	move.b snd_head,d6
	lea snd_ring,a0
	move.b d5,(a0,d6.w)
	addq.b #1,snd_head
	move.l (sp)+,d6
	move.l (sp)+,a0
	rts
.mcu:	bra mcu_job

	include	"m6809rt.s"
	include	"mcu.s"
	include	"natives.s"
	include	"selectors.s"
	include	"code_main.s"
	include	"tables_main.s"

	section data,data
	even
g_mem:					; the CPU's image: $0000-$3FFF RAM, video and I/O, $8000-$FFFF the fixed ROM
	ds.b $8000
	incbin "fixed.rom"
g_banks:
	incbin "banks.rom"		; the six 16 KB banks (6 and 7, never selected, would read what follows)
mcu_rom:				; the MCU's 16 KB ROM ($C000-$FFFF: its job reads its tables only there)
	incbin "mcu.rom"

	section bss,bss
ctx_banks:	ds.b 8*CTX_STRIDE	; the contexts of banks 0-7 (init_context)
cur_ctx:	ds.l 1			; the one of the bank selected (a6 in translated code; port_frame's end)
bad_table_base:	ds.l 1			; (main_badpc: init_context)
bad_table:	ds.w $2000		; (all 0: the base itself)
port_expect:	ds.l 1
port_idle_pc:	ds.w 1
badpc:		ds.w 1
badslot:	ds.w 1
port_booted:	ds.b 1
port_phase:	ds.b 1
port_returned:	ds.b 1
port_vblank:	ds.b 1
port_coins:	ds.b 1			; pressed until the FIRQ took them: bit 6 coin 1, bit 7 coin 2, bit 0 service
g_bankreg:	ds.b 1
g_scroll_lo:	ds.b 2
pal_written:	ds.b 1			; (set by the translated writers: gen.py)
fg_written:	ds.b 1
spr_written:	ds.b 1
bg_written:	ds.b 1
snd_head:	ds.b 1
snd_tail:	ds.b 1
in_bytes:	ds.b 6			; P1, P2, EXTRA (buttons 3, service), DSW0, DSW1
	even
snd_ring:	ds.b 256
	section text,code
