# Architecture

The project ports Z80, 6809-family and NEC V30 arcade games to the Atari STE (8 MHz 68000, 4 MB, 16 colours, Blitter).  Every port
has three parts, and the first two are checked against each other with a lock-step test:

1. **A reference machine** (`games/<game>/tools/machine.py`, on `engine/z80.py`, `engine/m6809.py` (KONAMI-1 too),
   `engine/m6801.py` / `engine/hd63701.py` for the MCUs, `engine/v30.py` for NEC V30, `engine/mcs48.py` for the
   i8039 (Gyruss's effects, rendered offline); shared boards:
   `engine/namcos1.py` and `engine/m72board.py`): a
   Python model of the arcade board from the MAME driver.  It is the ground truth for the logic
   (RAM compared every frame) and for the picture (`render_raw`, itself compared with MAME's own screenshot, see
   `docs/porting-guide.md`).
2. **A static translation** of the Z80, 6801, 6809-family and V30 programs to 68000 code (`engine/z80x.py`, `engine/translate.py`,
   `engine/m6801x.py`, `engine/m6809x.py`, `engine/v30x.py`; the game specific part in `games/<game>/tools/gen.py`).  The main arcade program runs as
   68000 code, with hardware accesses calling runtime routines. Auxiliary processors may use translated firmware,
   a native model, an interpreter (Black Tiger's MCU), or recorded sound as specified by each port.
3. **The STE runtime and renderer** (`games/<game>/src/*.s`, shared `engine/rt/rtlib.s`): video with the borders removed,
   the arcade's interrupts at the vertical blank, input, and a renderer that draws the arcade's tile map and sprite
   list. Sprites use short HOG **Blitter** passes with prepared opaque end masks and no clearing pass;
   tiles primarily with the CPU, with per-port Blitter composition and restore paths.

Layout (the conventions are in the README's "Layout"): `engine/` (shared), `games/<game>/{src,tools,ref,docs}`,
`build/<game>/`, `run/<game>/` and `release/` (generated, not in git), `assets/roms/` (the archives; `extracted/<game>/`
unpacked by `port.py prepare`, not in git), `tools/` (`hatari.sh`, `release.py`, `lz4prg.py` + `lz4stub.s` and `stdisk.py` for the floppy images, `windows/`), `port.py` (the front end
and the list of the ports), `legacy/` (superseded, not built).  `engine/paths.py` knows where things are; `engine/toolchain.py` assembles and links (VASM/VLINK environment
variables select the tools).

## The Z80 translator (`engine/z80x.py`)

Static translation, one 68000 snippet per Z80 instruction, labelled `Z<pc>`.  A
`z80x.Config` describes the program (several per machine: Galaga has two): label prefix,
dispatch table and token symbols, the memory model (see below), the two RAM words for IY
and F', write hooks (`ld (nn),a` to an I/O address calls a runtime routine), whether
`rst $28` is followed by a jump table.  `translate.generate_program()` (`engine/translate.py`) does one program:
discovery seeded by the coverage pickles, flag liveness, the CCR analysis, emission,
dispatch table.  Memory models: "signed" (a6 = Z80 address 0, signed word index, a 64 KB
block puts $8000-$FFFF below a6) and "long" (long index with the upper words of the
registers kept 0, static accesses to $8000 and up through an absolute symbol).
Instructions added for Galaga: `ldi`/`ldd`/`lddr`/`cpi`, `jp pe/po` right after them
(P/V = BC != 0, the only parity use), `rld`, `ex (sp),hl`, `halt` (runtime `z80_halt`:
wait for the next interrupt), `ld a,r` (runtime `z80_rnd`, a shift register the reference
reproduces), the IX/IY halves.  `translate.compile_code()` is the common pipeline (flag liveness, CCR analysis,
emission); the Z80 ports' gen.py files go through it. Other CPU families use their own translators below.

### Registers

d0 = A, d1 = BC (byte swapped), d2 = DE, d3 = HL, d4 = IX, d6 = flags image, a5 = Z80 SP (a pointer),
a6 = the Z80 block, a4 = the dispatch table, d5/d7 scratch.  Where A' F' BC' DE' HL' and IY live is set per program
(`z80x.Config`, `Emitter.regmap()`):

| Config | A' / F' | BC' DE' HL' | IY | used by |
|---|---|---|---|---|
| default | a3 / a block word | a0-a2 (`exx` = 3 `exg`) | a block word | (old builds) |
| `alt_af="upper"` | bits 16-23 of d0 / upper word of d6: `ex af,af'` = `swap d0; swap d6` (8 cycles, was 34) | | | all |
| `z80x.FAST` (signed mode) | as above | upper words of d1-d3: `exx` = 3 `swap` | a2 (the low word, `(d,a6,a2.w)`) | the Z80 ports' main programs (Galaga CPU1, Bubble Bobble main) |
| `z80x.FAST_LONG` (long mode) | as above | a0-a2 (the long mode needs the upper words 0) | the block | Galaga CPU2/3, Bubble Bobble sub |

1942 first measured `FAST` 0.4% slower: its own `ldir` cleared BC' with `moveq #0,d1`; with `clr.w d1` it uses `FAST`
since 2026-10-09 (a234c67; xprof 1100-1500: 24,254 cycles a tick against 24,306 with `alt_af="upper"` alone; its own
`ldir` beats the engine's, 24,407).  With A' out of a3, a3 is free in every program: a computed jump is
`move.l (a4,d7.l),a3; jmp (a3)` (50 cycles instead of 66 for `move.l ...,-(sp); rts`).  The rules a runtime must keep
(see `porting-guide.md`): no long writes to d0/d6 (`moveq` clears A' / F'), with `FAST` none to d1-d3 either, and
a0-a2 are scratch for the translated code (`ldir`), not for the runtime between instructions.

### What makes the translated code cheap

* The Z80 stack is always word aligned (the program sets SP to $6C00 and pushes words),
  so `call`/`ret`/`push`/`pop` are word moves.  A word read from the stack is the byte
  swapped pc, and the dispatch table (`z80_dispatch_sw`, 65536 longs, built at start by
  `z80_init_dispatch` from the compact table) is in that order.  The one place where the
  stack is odd in between, `inc sp; inc sp`, is one `addq.l #2` (the NMI pushes a word
  and crashed on the odd pointer).
* **Direct returns** (`Emitter.ret_cands`): a `ret` compares the word on the stack with the return points of the
  function(s) it belongs to (the instructions after the calls of every call target whose code reaches the ret
  without entering calls; up to three) and jumps there directly, 30 cycles; anything else (an interrupt token, a
  return address the program made itself) goes through the table as before.  It is only a guess, checked at run time.
* BC is kept byte swapped (B in the low byte): B is the register the game works with
  (`djnz` is `subq.b #1,d1; bne`, 14 cycles instead of 44; `ld b,(hl)` one move), the pair
  is rare, and the swapped order is the order of the bytes on the stack and in memory.
* **High bytes** (H, D, C, IXH) go through the 68000 stack: `move.w d3,-(a7); move.b (a7)+,d0` reads H in 16 cycles
  (`lsr.w #8` alone is 22: a byte move on a7 steps by 2, and an interrupt in between pushes below a7).  Writes are
  `move.w r,-(a7); move.b x,(a7); move.w (a7)+,r` (24 instead of 38), `inc h` without live flags is `add.w #$100,d3`.
* **`ldir`** runs on two address registers: a fill (`de = hl + 1`, the `ld (hl),n; ldir` idiom) writes the byte by
  longs, a copy of the same parity that does not overlap forward goes by longs, anything else by bytes, 8 a turn.  A
  copy across the ends of the 68000 block (the $8000 split of the signed mode, the $FFFF wrap) and BC = 0 take the old
  indexed loop.  Galaga's clears went from 46 to ~3 cycles a byte.
* **Carry into X** for `adc`/`sbc`/`rl`/`rr`: `moveq #1,d7; and.b d6,d7; lsr.b #1,d7` (X = C = the carry, Z set: what
  `addx`/`subx` need), 16 cycles without a branch (was ~40).
* Z80 jumps are `bra` (vasm makes them `bra.s`/`.w`, or a `jmp` when out of range).
* **Banked windows** (Bubble Bobble, 1942, Black Tiger, 1943): an access that may read the window uses the marker
  register `aW`; `Emitter.window_wrap` makes it a0, loaded at the start of the instruction (after its label and hook
  lines) and saved only where a0 holds BC'.  The start matters: the high-byte reads push on the 68000 stack, and a
  save of a0 pushed in between (as each port's own copy of this code did, before the first `aW` line) made
  `ld (hl),c` store a byte of the saved a0 (Black Tiger did not boot).  The base is not loaded when the instruction's
  window check (`lea (a6),aW ...`) sets it anyway.

### Flags

* Flags in the condition codes: a flag producing instruction leaves S Z C in the CCR, and a
  conditional jump that directly follows it branches on that instead of `move d6,ccr`
  (12 cycles).  `Emitter.analyze` is a forward must-analysis over the code (nothing known
  at the entries, the return points and the targets of computed jumps); the jumps that
  can read the CCR are no longer uses of d6, so a producer whose flags are only read
  that way stores nothing.  Note that a 68000 `move` or `tst` clears C: only address
  register operations, the bit instructions and branches keep the flags.
* The analysis also knows which data register's byte the Z80's S and Z describe (the result of the last flag op,
  `ccr_step`): a `move.b` or `tst.b` of it sets N and Z from the same byte, so `dec a; ld (hl),a; jr nz` branches on the
  CCR.  Where a producer that sets only S/Z must keep a live C (a merge into d6, which spoils the CCR) a `tst.b` of the
  result (4 cycles) brings S and Z back.
* **Precise liveness over calls** (`z80x.ret_targets`): a call no longer reads all flags; it passes them to the callee
  (whose own liveness says what it reads), and the rets of well-behaved functions pass them on to their return points.
  A function is well-behaved when its stack is balanced on every path (no pop of the return address, no `ex (sp)` of it,
  SP not set) and its rets are reached only from call targets (not from the reset or interrupt entries, jump tables, or
  code addresses the program holds); every other ret still counts as reading S Z C.  Bubble Bobble: 49% of the main
  CPU's rets qualify, 95% of the sub CPU's; flag stores -17%, merges -26%.

### The second pass: merges over labels nothing enters

The code of consecutive instructions is merged where the program cannot arrive between them other than by the
straight flow: not a join, not a jump or call target, not a hook (`Emitter.boundaries`).  The labels inside a merge
are in `em.no_entry` and get `z80_badpc` in the dispatch tables (a merged label that is not emitted gets a stub that
does the same), so an entry the analysis did not foresee stops loudly instead of running half-transformed code.

* `push rr; pop rr'` (the register copy idiom) is one move (the stack word below SP is not written: dead).
* `push af ... pop af` in straight code with the slot read by nothing else keeps the flags in the d6 format (two moves
  each instead of the conversions to and from the Z80 F byte, -112 cycles a pair; `pair_af`).
* A `bra` to the label right behind it and a `tst.b R` right before a `move.b R,...` are dropped.

### Native replacements (`natives`)

A port can replace Z80 code by a hand-written 68000 routine: `compile_code(..., natives={pc: label})` (the games'
gen.py) makes the translated label of `pc` a `jmp label`; the translation of the code behind it stays (its other
entries, a fallback the routine may jump into).  The pc is a boundary (no merge across it) and the CCR analysis knows
nothing after it.  The routine must leave what the code after it reads as the Z80 code would: the registers in the
port's map (`Emitter.regmap`), memory, and the flags its return point reads (`live_out` of the replaced code's `ret`; a
ret reached by `jp (hl)` reads S Z C), and continue there (a `ret` pops the Z80 stack and jumps through the dispatch
table, as the translation does).  Worth it where the translation pays for the Z80's limits: a loop with an index
register kept in memory, tests whose result does not change in the loop, flags merged for a later reader.  Each port
tests its routines against the translation they replace (random states: memory, registers, live flags) besides the
lock-step test.  Bubble Bobble (`games/bublbobl/src/natives.s`, 2026-10-12): the sub CPU's count of objects near IX
(`$0849`, ~210 -> ~50 cycles an object) and both CPUs' object state dispatch (`$5C37`, `$03CF`: a chain of `bit` /
`jp nz` with Z merged into F at each test, two tests native for an object with none set): the translated code 171k ->
116k + 16k native cycles a game frame in play, the game 18-40% more rounds a VBL there.  The same port replaces its MCU's
VBL interrupt (`src/mcu_native.s`, 6801 firmware, not through `natives`: the runtime calls it instead of the
translation): the bus cycles the firmware clocks through its ports become moves on the shared RAM, 27k -> 3.9k cycles
a game frame; with the natives and leaf inlining, in play in Hatari (the same game: inputs by game round; every VBL
counted) 0.455 -> 0.532 game rounds a VBL and 7.2 -> 12.2 pictures a second.

### Leaf functions emitted in place (`Config.inline_leaves`)

A call of a short leaf function (straight code and conditional rets up to a ret, no stack use, calls or jumps, no
hooks or natives, in the fixed code) is emitted as the function's instructions, its rets as branches to the return
point: no return address pushed, no dispatch at the ret (~70 cycles a call).  The callee's liveness and its CCR
knowledge (the meet over its callers) hold at every call; only the final emission inlines, the analysis sees ordinary
calls.  The return address the Z80 would leave below SP is not written (dead).  `ret_cands` leaves out the inlined
calls' return points.  Off by default (0).  Bubble Bobble used 16 (its main CPU 92.5k -> ~83.5k cycles a game frame), 48 since 2026-11-02;
every Z80 port has leaves since the audit of 2026-11-02 (`speed.md`).

### The 68030 forms (`Config(cpu030=True)`, F030Arcade)

The emitter's idioms are chosen by 68000 cycle counts (a pair's high byte through the 68000 stack: 16 cycles against 26
for `lsr.w #8`).  The Falcon ports of F030Arcade run the same translation on a 68030 from ST-RAM, where the program is far
larger than the 256-byte instruction cache, shifts cost a few cycles and every stack round trip two bus accesses:
`cpu030=True` (default: the `STE_XCPU` environment variable, 68000) reads a high byte as `move.w rr,d7` / `lsr.w #8,d7`,
writes it with `ror.w #8` around a byte move and turns `inc`/`dec` of one in the register.  The STE ports' output is
unchanged.  Check it on a 68030: `STE_XCPU=68030 python engine/xbench.py` (Musashi's 68030; the `long` layouts' two
`inc`/`dec (iy+d)` failures are older than this switch and show on a 68000 too).

### Tests and measurements of the translator

* `engine/xbench.py`: every Z80 opcode (operand bytes random) and random straight-line sequences with forward jumps
  and push/pop pairs, compiled through `compile_code` like a program, against `engine/z80.py` on Musashi, in the memory
  layouts of the ports (`dk`, `signed`, `long` and the `+` variants with the fast register maps).  Registers, memory
  (but the dead stack below SP), the next pc and the live flags must match.  Known by design: S after `bit` without
  `Config.bit_s`, H after `ccf`, P/V only for `jp pe/po` after `ldi`/`cpi` (right after, or past
  `inc`/`dec` of HL, DE, IX, IY with no entry between: `pv_block_before`, 2026-10-29).  `python engine/xbench.py --seq 1000`
  takes ~5 minutes for all six layouts (34k single cases, 6k sequences).
* `engine/xprof.py <game>`: a `--sim` build stepped instruction by instruction, each 68000 instruction charged to the
  Z80 instruction it was translated from: cycles per *game frame* (one round of the arcade's interrupts, so a faster
  build is not charged more work per VBL), by instruction form, by 68000 instruction, hottest pcs.  Donkey Kong runs
  through its lock-step harness (`logic_test.py`).  Idle loops are counted apart (`IDLE`).
* `engine/xdiff.py galaga <old.PRG> <old.map>`: two builds side by side (separate processes: Musashi keeps the CPU in
  globals), the arcade's RAM compared at every game frame.  The interrupts come on a clock of translated instructions
  (and when no Z80 code runs for two frames), so both builds are interrupted at the same points of the Z80 programs:
  Galaga's main CPU draws text in its foreground, and a faster build is otherwise legitimately ahead.  The stacks are
  not compared (an interrupt's `push af` saves d6, which need not hold the interrupted code's flags: they may be in
  the CCR).  This is Galaga's translation test (its `schedule_test.py` checks the reference only).

Measured 2026-10-08 (`xprof`, translated code per game frame, Musashi cycles; Bubble Bobble without its idle loop):

| port | before | after | |
|---|---|---|---|
| Galaga (both CPUs, frames 800-1200, attract) | 47.6k | 27.6k | 1.73x |
| Bubble Bobble (main, sub, MCU; frames 500-800, play) | 70.3k | 54.2k | 1.30x |
| 1942 (ticks 1100-1500, play) | 28.1k | 24.3k | 1.16x |
| Commando (ticks 600-1000, attract; 2026-10-09) | 8.4k | 7.0k | 1.20x |
| Black Tiger (ticks 600-1000, attract; 2026-10-09) | 15.7k | 12.9k | 1.22x |
| Donkey Kong (NMI, 1500 frames of logic_test.py) | 5.2k | 4.8k | 1.08x |

The gain is where the old code was weak: Galaga's `ldir` clears (37% of its cycles), the `ret` dispatch with A' in a3,
the high bytes.  Donkey Kong's code was lean already (16 cycles a Z80 instruction, mostly memory moves that cannot get
cheaper).  Not done, by expected gain: inlining small leaf functions (call + ret = ~65 cycles; ~8% for Bubble Bobble),
the MCU translator `m6801x.py` (9% of Bubble Bobble's translated cycles, untouched), keeping the Z80 stack words in
68000 order so `push`/`pop` of DE/HL/IX need no `ror.w #8` (3-5%; but code that reads the stack as memory would break),
Black Tiger guarded every indirect access as a possible window read (a window check of ~40 cycles each: a quarter of its
translated cycles); since 2026-10-11 only the coverage's sites are guarded, as in Bubble Bobble (`docs/window-sites.json`,
`logic_test.py --audit`: the logic in play 80.7k -> 65.3k cycles a tick).  A factor of 2 for every
port is not in reach of the translation alone; the renderers are the larger part of most frames anyway.

## The 6809 translator (`engine/m6809x.py`, Splatterhouse 2026-10-12)

One snippet per 6809 instruction, labelled `<prefix><virtual address>`: on Namco System 1 the code lives in 8 KB pages of
a 23 bit virtual space that the CUS117 MMU maps into the CPU's eight slots, and a page runs from one slot (the coverage
says which; a page seen in two slots stops the build).  `Program` describes one CPU: the pages and their slots, the roots,
the coverage (pcs, the data slots and I/O addresses of each access site, where computed jumps went), the hooks (the idle
point), natives, and per-game callbacks (static I/O reads, register files folded inline, inline bank switches).

Registers: A = d0, B = d1 (D composed only where needed: `ADDD` is `add.b lo,d1; addx.b hi,d0`, exact N Z V C), X Y U =
d2-d4 (upper words 0: they index as longs), S = a5 as a 68000 pointer into slot 0's page, a6 = the CPU's context
(`PB[8]` page addresses, `VB[8]` = PB - slot * $2000, the dispatcher's table per slot, the page numbers, the CC bits E F H
I; the fields used with an index register stay below 128), a3 = PB[0] (the direct page and the stack), a4 = VB[1],
a2 = PB[7], each kept by the runtime when its slot changes.

* **Flags** live in the CCR (the 6809's N Z V C are its low nibble).  Each instruction's code leaves some right (`ok`);
  the live ones it spoils (backward liveness) come back from the SR saved before (`wrap`).  Liveness is per function: an
  RTS reads what the return points of its callers read (`function_returns`), ANDCC / ORCC define only the bits they
  force, RTI reads nothing, the idle hook reads what the code after the idle loop reads.  H exists only for DAA.
* **Memory**: static addresses use PB[slot] + offset (a3 / a4 / a2 without a load); indexed ones VB[slot] + register with
  the slot the coverage saw at the site, else computed.  16 bit accesses are byte pairs (the 6809 has no alignment), the
  high byte through the 68000 stack (`move.b x,-(sp); move.w (sp)+,d6`).
* **I/O**: stores to $E000-$FFFF are the MMU (static ones inline: page number, page_base_table, PB / VB / the dispatcher's
  table, the cached registers); the sites the coverage saw touching I/O pages call the runtime, or fold inline (the
  CUS123 control, mirrored every 32 bytes), or read a known register (the key custom's random number).
* **Control flow**: branches inside a page are 68000 branches; JSR pushes the 6809 return address and branches (into
  another slot after checking its page); RTS compares the popped address with its callers' return points (the page
  checked unless the slot is fixed), else the dispatcher (the slot's page table, 32 KB a code page).  `JSR [B,X]` after
  `LDX #table` uses a 68000 table of the entries when they are code in a fixed slot or in the same page.
* **Natives** replace a pc with a hand-written routine; the translation stays under `<label>_t` (fallback, tests).

**68030 forms** (`m6809x.CPU = 68030`, default the `STE_XCPU` environment variable: F030Arcade's Falcon ports): the
68030 reads and writes words at odd addresses, so the return address JSR pushes, PSHS/PULS/RTI of X Y U PC and the indexed
16-bit operands are one word move each (the 6809's byte order is the 68000's), D is composed with `lsl.w #8` instead of
the stack, RTS / PULS PC compare a return point and branch only on the match (`ret_match`; when the flags are read
there a stub `<label>_rf: move.w d5,ccr` before the return point restores them, `place_ret_stubs`), and the
flag-keeping wrapper keeps the SR in d7 when the body leaves d7 alone (an OR instead of the merge when only V / C are kept
and the body's last instruction cleared them).  Two more, set on the Program after construction: `ret_weights` ({return
point: returns to it}, a profile of the port's play: `ret_order` compares up to `RET_WEIGHTED` seen ones, the most
frequent first, instead of the first `RET_CANDS` by address) and `slot_ctx` ((page, slot) -> the address of a context
that holds that page there for good: the page check is `cmpa.l #ctx,a6`, no read of PID; Double Dragon's `gen.bank_ctx`,
its port sets `gen.RET_WEIGHTS`).  Double Dragon on the Falcon: 6.76 -> 5.62 ms an arcade frame.  Tested by
`m6809x_test.py --cpu030` and the games' `logic_test.py` with `STE_XCPU=68030` (Musashi's 68030; `sim.py` follows it).

`Program.fast_forms` (2026-10-26, Double Dragon's STE port) gives the 68000 the forms of these that it runs too: the
flag-keeping wrapper through d7, `ret_match`, `slot_ctx` page checks and the `ret_weights` order (the word moves stay
68030 only: the 6809 stack is odd at about 29% of Double Dragon's stack instructions).  With it, a return point in the
returning instruction's own page needs no page check (`ret_here`: its slot holds that page while that code runs).
Double Dragon's weights come from `tools/ret_profile.py` (`docs/ret_weights.json`, seeds -1 and 4, frames 5000-12000).
Musashi, `profile.py 3000 3200 --seed -1`: 191.3k -> 182.7k -> 180.9k cycles a frame; `logic_test.py` identical.

Tests: `engine/m6809x_test.py` (every documented instruction in every mode, random states, against `engine/m6809.py` on
Musashi; batches of 8 KB pages; `--cpu030`: the 68030 forms on a 68030), the games' `logic_test.py` (frame by frame against the reference's port schedule, with
`--steplock F`: instruction by instruction inside a frame) and `profile.py` (68000 cycles per 6809 instruction).

## The V30 translator (`engine/v30x.py`, R-Type 2026-10-13)

One snippet per V30 instruction, labelled `R<linear address>`; each code address runs with one CS (the coverage says
which), so near jumps, calls and returns stay in their segment and PS-relative operands are absolute.  Structured
decoding is `engine/v30dec.py` (the text stays `engine/v30dis.py`'s).

* **Registers**: AW CW DW BW IX IY BP = d0 d1 d2 d3 d4 d5 d6 (upper words 0: any of them indexes as a long; the high
  bytes AH..BH through the 68000 stack), a5 = SS:SP as a pointer, a4 / a3 / a2 = the SS / DS0 / DS1 bases
  (image + segment * 16), a6 = the context (segment values, IE, DF, the parity and AC bytes), d7 a0 a1 scratch.
* **Memory**: the V30's 1 MB is one block whose bytes are swapped in every word (V30 byte a at image + (a ^ 1)): words
  at even addresses - the stack, the work RAM's words, video, sprite and palette RAM - are single native moves (R-Type
  reads 45 words for every byte), static bytes cost nothing, a byte at a register address computes its offset ^ 1.
  Odd words: static ones, and the sites the coverage saw odd (both parities, chosen at run time).
* **Flags** in the CCR (S Z O C = N Z V C) with backward liveness and `wrap` as in the 6809 translator; P and AC only
  where read (a result byte, dst ^ src ^ result in the context).  What made the liveness precise (wrapped instructions
  1055 -> 117, 18% fewer cycles): RETs reached through computed calls and jump tables get their return points, computed
  calls read only what the targets the coverage saw read, an unknown continuation reads S Z O C only.
* **Control flow**: RET compares its function's most executed return points (flags dead), else jumps through a 64K-long
  IP table of the main segment (`main_ip_mid + 4 * IP`, no flag spoiled: `move.w (a5)+,a0`, two `add.l a0,a0`);
  elsewhere a hash table by linear address.  Jump tables the random play did not exhaust come from the ROM
  (`games/rtype/tools/gen.py` `table_targets`: the table at the operand's segment + displacement, sized by an AND of the
  index before it, or the ROM's runs of plausible entries that hold the seen targets).
* **Interrupts**: the runtime pushes PSW, CS and IP of the idle point and runs a handler; IRET pops them and dispatches
  to the idle hook, which returns to the runtime when the CPU is idle (`games/rtype/src/core.s`).

Tests: `engine/v30x_test.py` (every opcode with random ModRM, prefixes and states against `engine/v30.py` on Musashi);
`games/rtype/tools/logic_test.py` (frame by frame against the reference's port schedule, `--steplock F`) and
`profile.py` (cycles per V30 instruction, per mnemonic, per 256 bytes).

## Namco System 1 (`engine/namcos1.py`)

The board after MAME: the CUS117 MMU (a 23 bit virtual space, eight 8 KB slots per CPU), the key customs (types 1-3:
Dragon Spirit, Pac-Mania / Galaga '88, Splatterhouse), the CUS116 palette with its clip registers, the CUS123 tile layers
(four scrolling, two fixed, 8 bits a pixel with 1 bit masks), the sprites (CUS48: 32 x 32 cells, 4 bits, sizes and
offsets within the cell, priorities, the shadow colour) and the reference renderer (0 pixels and 0 pens differ from
MAME 0.289 for all four games).  The CPUs (two 6809s behind the MMU, the sound 6809, the HD63701 MCU) run on a copy of
MAME's scheduler: attosecond time, 1/38400 s quanta in device order, timers cut the slices, `set_input_line` is a
synchronize() timer at the writing instruction's end that aborts the running slice only as the head of the list, the
MCU's serial clock is a periodic timer of 4 CPU cycles, the YM2151's timers as ymfm runs them, MAME's `machine().rand()`
for the key custom.  Splatterhouse's RAM equals MAME's for about 3200 frames.  `engine/namcos1_mame.py` compares the
renderer with MAME's picture (`port.py mame <game>`).

A port's schedule (`games/splatter/tools/machine.py` `run_frame_port`) is simpler: the vertical blank's work, the MCU and
the sound CPU for a frame, then the main CPU's IRQ until its idle point, then the sub CPU's.  The port starts from the
reference's state after the boot (`tools/snapshot.py`); the MCU is native (`src/mcu.s`, checked against
`tools/mcu.py`, which is checked against the real MCU); the sound CPU only reads what the main CPU writes.

## Runtime schedule (all ports)

The arcade's CPUs are not run as threads.  At every vertical blank the runtime delivers the arcade's interrupts in a
fixed order and runs each handler to completion (Galaga: main CPU IRQ, sub CPU IRQ; Bubble Bobble: MCU IRQ1, main
CPU IM 2 interrupt, sub CPU IRQ).  What the arcade's main loop does between interrupts is only the boot and
idle loops, so the foreground "thread" is the boot until the idle loop and the renderer afterwards.  The handler's
return address is a token pc (the dispatch table maps it to the runtime's return label), which also lets code that
inspects the interrupted pc run (Bubble Bobble requires its high byte < $C0).  `run_frame_port` in each machine.py is
the same schedule in Python: the lock-step tests compare against it, not against the interleaved reference.

Rules learned the hard way (details in `docs/porting-guide.md`):

* The VBL handler arms the border timers first, then runs the game's interrupts at IPL 3 (`move #$2300,sr`), then draws.
  A VBL arriving during the drawing runs the handlers again and skips the drawing: the game keeps its pace and the
  display drops frames.
* Timer A lowering the IPL can let a pending VBL nest 28 deep: guard with an `in_logic` flag.
* When the game logic alone takes longer than a frame the renderer starves: throttle (`render_age`, Galaga's star
  levels) - skip the logic every other VBL while drawing.
* Boot self-tests (RAM, ROM, checksums) are patched out in the reference and the translation; the code that
  checksums ROM while running is compensated by a dead byte.  Never use frames of a self-test as a performance
  reference: they fill video RAM and load the renderer unrealistically.

### The schedules in use

The rule above has grown into four forms; a new port picks the one its board fits:

| Schedule | How | Ports |
|---|---|---|
| VBL-locked | one round of the arcade's interrupts a VBL, then the drawing in the VBL handler (a nested VBL skips it): 50 of the arcade's 60 rounds, the game 5/6 slow | Donkey Kong, Donkey Kong Junior, Galaga (with its star throttle), Bubble Bobble (three screens; `-D TICK60` two rounds at most) |
| Idle hook, frames counted | the VBL only counts arcade frames (`vbl_phase`: six for five VBLs at 60 Hz; `ARCADE_FRAC` for other rates, Moon Patrol's 56.74 Hz); the idle hook of the arcade program (its wait loop, reached through a token return) runs the pending frames and draws; up to `MAX_PENDING` frames wait, at most `MAX_SKIP` in a row are not drawn; three buffers plus a clean screen | `MAX_PENDING` 3 / `MAX_SKIP` 3: Pac-Man, Pooyan, Mr. Do!, Time Pilot, Track & Field, Hyper Sports, Commando, Gun.Smoke, Moon Patrol; `MAX_SKIP` 2: Gyruss, Kung-Fu Master, 1942 (its cooperative kernel's idle point); the game first, `MAX_SKIPS` 4-8: 1943, Black Tiger, Trojan (`MAX_PENDING` 5), Double Dragon |
| Picture every n frames | one arcade frame a VBL, a picture every `PIC_EVERY` frames at most, the logic at most `MAX_BEHIND` frames behind; R-Type also starts a picture when `PIC_VBLS` VBLs passed (`pic_due`, Timer D) | `PIC_EVERY` 2 / `MAX_BEHIND` 3: Splatterhouse, Galaga '88, Dragon Spirit (8 / 12 measured as an option); 8 / 12: R-Type (with `PIC_VBLS` 3), Mr. HELI |
| Two threads | the picture is the foreground; the game runs per arcade interrupt until its wait loops (TRAP), a sixth IRQ every fifth VBL for 60 Hz | Gauntlet (its 68010 program runs natively) |

The names differ by port (rings, buffers, screens; `NBUF`, `ST_NBUF`, `REN_NBUF`): they are the same draw buffers.
At an idle hook whose flags the interrupt handler never reads, keep no flags (`flags_at=set()`, Black Tiger's `00D4`:
logic -2.5%).  A scheduler that can start a picture later than the frame it was planned for must capture the sprite list at every
DMA the arcade does (R-Type, `games/rtype/docs/sprite-dma-results.md`: with `PIC_VBLS` a picture used the current
scroll with an older list; copying the live slots before drawing is wrong too, the emitters may already have
overwritten them).

Compared with F030Arcade's spare-time renderer (a preemptible render thread on its own stack, started by Timer B once
the game is parked, its pages queued for the VBL) this schedule is the Heavy Barrel case there: the frame is the
interrupt handlers, so their return is the "frame is done" point and no park test is needed.  Bubble Bobble's three
screens are the queued pages; in the other ports a VBL nested into the drawing runs the game, so the drawing may go on
with a changed state (not checked port by port).  See `docs/porting-guide.md`, "Two related projects compared".

## Border removal

`engine/rt/borders.s` schedules events early and synchronizes them to the video. Timer B opens the bottom
border and arms Timer A at that line-exact point for the following top border. The VBL restarts Timer B and arms
Timer A as a fallback only when the preceding bottom event did not do so (including startup). `BD_HUD` extends
Timer B with palette switches; `BD_VSWITCH` also switches video addresses for separate HUD images.

Every Blitter pass is HOG and at most 256 bus cycles. `blit_go` splits longer transfers into lines or column
strips, allowing interrupts between pieces. The former `wait_borders` policy is superseded by these short passes
and early handlers. Verify actual timing in the pinned Hatari build: Musashi has no MFP timer model. Debug counters
record fallback arming and late border/palette events; `BLIT_STATS=256` reports oversized or non-HOG passes.

Mega STE at 16 MHz with cache enabled has a separate automatically selected pulse path.
It warms compact delay kernels after Blitter cache invalidation and masks other MFP sources
during the bounded HBL approach, preventing an ACIA/Timer C interrupt from waking STOP on
the wrong part of a line. It never writes the CPU/cache control register. The legacy 8 MHz
path remains available. [Mega STE timing verification](megaste-border-timing.md) records the
pulse windows, mixed-HOG load test, cache-placement sweeps and the physical-hardware limit.

Known full-mask, unskewed copies/fills use `blit_go_copy`; HOP 0 fills with arbitrary masks use
`blit_go_fill`. Both can budget 32 words per piece because there are at most two bus accesses per word.
The generic dispatcher accounts for masked destination reads and FXSR fetches. Strip line counts come from
tables rather than a division per strip. `engine/borders_blit_test.py` checks pixels, register endpoints,
preservation and pass lengths; `engine/m72_bitmap_test.py` checks the M72 contribution-bitmap rotation.

## Input (all ports)

Each port has its own IKBD handler (`acia_isr`): the keyboard through `key_table` (scancode -> the bits it sets in
the arcade's input bytes, active high), the two IKBD joysticks (port 1 player 1, port 0 player 2; Donkey Kong and
Galaga OR them into one player), Esc quits.  The IKBD gives a joystick one fire button: button 2 (and Gun.Smoke's
third) is on the keyboard, or Bubble Bobble's joystick up.

The byte stream itself is framed by `engine/rt/ikbd.s` (`ikbd_byte` at the top of every handler's loop, `ikbd_vars`
in the bss): a data byte read as a key is a key, and a joystick's "up" byte is $01 = Esc ("down" $02 = the key 1).
So every packet is skipped by its length ($F6-$FD too), an ACIA overrun (OVRN after a read: the next byte was lost)
drops the packet being read and the next byte when it can be a joystick data byte, and Esc quits only on its release
right after its press.  `engine/ikbd_test.py` feeds it streams with lost bytes (the MC6850's / Hatari's overrun: the
byte arriving into a full buffer is lost).  In Hatari the handlers read every byte within 2 lines (an overrun needs
~20), so this is a guard, not a cure: a "sudden quit" is more likely a crash (below).

A crash (an exception: `crash_stubs`; or `z80_badpc`, the vector 99) writes `CRASH.TXT` next to the program, gives the
hardware back and then shows `crash_notice` (`engine/rt/rtlib.s`): the message waits for Return, after dropping what
was typed, since a key still pressed from the game would take a "press a key" away at once (the ports quit
silently before).

The pads of the STE's enhanced joystick ports (Jaguar pad / PowerPad: pad A player 1, pad B player 2, A / B / C the
buttons, Option coin, Pause start, keypad 1 / 2 / 5 / 6 as the number keys, * + # quit) are read once a VBL by
`engine/rt/jagpad.s`.  The port only says which bits a pad button sets (`JP1_UP` ... `JP_COIN2`, longs in its
key_table's byte order); `jagpad_poll` ORs them into `jp_in`, which the port merges where it merges the keyboard: the
VBL's copy into the arcade's input bytes (`jp_merge`), Donkey Kong's and Galaga's input reads, Bubble Bobble's
`compose_inputs` (also called from the VBL, at IPL 6 against the keyboard's).  `jagpad_init` probes $FF9202 (a bus
error on a plain ST: the pads stay off); the SIM build does not call it.  `engine/jagpad_test.py` checks the reader
against Hatari's model of the pads.

An arcade program may reject a coin held too long: 1942 ignores one of 40 ticks (credits 3-20, the reference machine),
so a test script taps the coin key (`tools/hatari.sh tap:5@20`), a long `hold:` is lost.

## Hard disk streaming (`engine/rt/hdd.s`, 2026-10-13)

The driver for the plan in `docs/sprite-preparation.md` ("Memory: prepared data from the hard disk"); the blueprint
is stedaimakaimura's `dma_test.s`.  No port uses it yet.  Two phases:

* **`hdd_open`, while TOS still owns the machine** (before `init_hardware`, supervisor mode, interrupts on): reads the
  data file once through GEMDOS with a hook in `hdv_rw` ($476) that logs every sector read GEMDOS makes straight into
  the scan buffer.  With Getbpb (logical -> 512-byte sectors) and the AHDI partition table (`pun_info` at $516: the
  partition's start, ACSI or IDE, the unit) that gives the file's extents (file sector -> physical sector), so a
  fragmented file works (up to `HDD_EXTENTS` pieces).  An IDE drive is asked for LBA and its geometry (CHS otherwise).
  The file and the scan buffer are multiples of 32 KB: a partial sector or cluster goes through GEMDOS's own buffer,
  which the hook does not see (`HDD_E_CACHED`).
* **`hdd_read` / `hdd_poll` while the game runs**: one request at a time, started by `hdd_read` and advanced by
  `hdd_poll` from the main loop (never inside the border or VBL handlers), split at extents and into commands of
  `HDD_STEP` sectors.  ACSI: READ(6) through the DMA chip, which moves the data alone; only the six command bytes are
  waited for, completion is GPIP bit 5 (polled: the ports keep that MFP interrupt off), the floppy locked out (flock)
  meanwhile.  IDE ($FFF00000, the Falcon's registers and the ST / STE adapters that copy them): PIO, at most
  `HDD_IDE_POLL` sectors a call (~2600 cycles each), checked on the alternate status (no wait, no interrupt line).
  Timeouts count the port's VBLs (`hdd_vbl` in its handler).  `hdd_stop` before giving the hardware back (quit, crash)
  lets a command in flight finish.  Errors are codes (`HDD_E_*`): the caller keeps drawing by the path that needs no
  prepared data (the plan's fallback), so a slow or missing disk costs speed, never correctness.

Tests: `engine/hdd_test.py` (`port.py test engine`) runs `hdd_read` / `hdd_poll` against register models of the DMA
chip with an ACSI target and of an IDE drive: requests across extents and longer than a command, the ACSI command
bytes, IDE in LBA and CHS (master and slave), a request while busy, beyond the file, no ACSI target, error statuses,
an IDE drive busy for good.  `tools/hddtest.sh` runs the whole module in Hatari with EmuTOS's own drivers: a FAT16
image whose test file lies in two pieces, on ACSI and on IDE (LBA) with 512-byte logical sectors and on ACSI with
2 KB ones; every request reads back without a bad sector.  Not measured yet: the reads' cost in a game picture and
how the DMA chip's transfers share the bus with the Blitter's HOG passes.

## Renderers of the ports

Every port has its own renderer (`games/<game>/src/render*.s`; R-Type's `stage.s`; Mr. HELI the shared
`engine/rt/m72render.s`), checked pixel for pixel against its reference machine through the colour table.  Which
scrolling, sprite, damage, text and colour method each one uses is tabled in `speed.md`, "Which port uses what"; the
sprite methods and their measurements are in `sprite-preparation.md`, the rules for edges and guards in `AGENTS.md`
and `porting-guide.md`, "Renderer correctness".  The first renderer, Donkey Kong's (generated Blitter code per sprite
line, the tile map compared with a shadow), is described in its README.
