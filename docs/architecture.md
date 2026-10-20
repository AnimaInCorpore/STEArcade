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
unpacked by `port.py prepare`, not in git), `tools/` (`hatari.sh`, `release.py`, `windows/`), `port.py` (the front end
and the list of the ports), `legacy/` (superseded, not built).  `engine/paths.py` knows where things are; `engine/toolchain.py` assembles and links (VASM/VLINK environment
variables select the tools).

## Renderers of the ports

The table covers the registered ports in `port.py list`. Splatterhouse and Galaga '88 have standalone runtimes
and renderer tests; Mr. HELI uses the shared M72 renderer in a harness. Their READMEs and local tools describe
current limitations; the other game folders contain reference/board work. See `docs/sprite-preparation.md` for
which preparation experiments have actually been measured.

| game | tiles | sprites | what is exact |
|---|---|---|---|
| Donkey Kong | CPU, shadow diff of the tile map, dirty queue per draw screen | Blitter, generated per shape/skew code | pixel for pixel against the reference and MAME |
| Galaga | CPU, 8 x 8 cells per colour quad, `chars_over` on top of sprites | Blitter, double sizes split into 16 x 16 parts, stars plotted after | renderer against MAME (RAM injected), reference identical |
| Bubble Bobble | CPU tile bake cache; static column layers and dirty blocks | Blitter, unshifted cached 16 x 16 sprites with mask-grouped rows; CPU tile fallback for other object layouts | game picture pixel for pixel against the reference; whole sprites in the guards |
| 1942 | hardware scroll of a 768 line ring (three draw rings + clean), tiles baked per palette bank, characters redrawn when the window moves | Blitter, one blit per line, masks as end masks, rectangles put back from the clean ring | pixel for pixel against the reference (which equals MAME) |
| Commando | hardware scroll of three virtual screens with twin lines (line l = line l+320), only scrolled-in tile rows and changed tiles drawn, no clean map; characters a list rebuilt on change, `movep.l` | Blitter, baked shift streams; a damage list put back from the twin lines | pixel for pixel against the reference (which equals MAME) |
| 1943 | cached background and front layers in hardware-scrolled rings | reordered source, prepared shift masks, one-word side clipping | renderer and reference tests, including front-layer priority and edge sweeps |
| Black Tiger | hardware-scrolled tile ring, cached tiles and characters | reordered equal-mask rows, clipped at full band words | reference pictures, moving window edges and sprite priority |
| Gun.Smoke | hardware-scrolled rings and a separate character strip | reordered streams; aligned clipping and whole drawing at fine offsets | reference pictures, scroll sweeps and edge tests |
| R-Type | shared M72 layer composition, separate HUD image and palette | converted pieces, generated line routines; clipped and priority fallback | reference indices after colour reduction; centred 320 of 384 pixels |
| Kung-Fu Master | hardware-scrolled rings and a separate score panel | cached opaque rows in natural order by default; optional mask grouping | reference indices, sprite edges and panel/playfield composition |
| Trojan | cached background layers and foreground characters | reordered equal-mask rows and prepared masks | reference pictures, sprite priority and side-edge tests |
| Double Dragon | cached background and foreground characters | reordered equal-mask rows, multipart sprite objects | reference pictures, sprite priority and side-edge tests |
| Gauntlet | the playfield torus as a bitmap, two hardware-scrolled rings copying only new strips and damage; text runs as Blitter copies | objects baked per colour mapping, a pass a row, shadows from a shadow-coloured playfield | reference pictures (any level), edges, 16 shifts, shadows, 64 KB |

Bubble Bobble uses static column layers and a dirty-block sprite renderer for the usual object layouts.
The 512-pixel virtual screen has horizontal margins and vertical guards. Cached sprites contain unshifted
plane words in mask-group order; all 16 horizontal positions share a cache entry. The general tile
renderer handles other layouts. Restore old guard damage before drawing; never erase new overhang.
The translated game logic and scene rebuilds still prevent a steady 25 fps (see the game README).

## Translator (`engine/z80x.py`)

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
| `z80x.FAST` (signed mode) | as above | upper words of d1-d3: `exx` = 3 `swap` | a2 (the low word, `(d,a6,a2.w)`) | DK, Galaga CPU1, Bubble Bobble main, Commando, Black Tiger, 1943 |
| `z80x.FAST_LONG` (long mode) | as above | a0-a2 (the long mode needs the upper words 0) | the block | Galaga CPU2/3, Bubble Bobble sub |

1942 uses `alt_af="upper"` only: `FAST` works there too (`scan_native` writes d1-d3 as words), but it was 0.4% slower
(1942 uses IY and `exx` little; `ld a,n` and `ex de,hl` cost a few cycles more), and 1942 keeps its own `ldir`.  With A' out of a3, a3 is free in every program: a computed jump is
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
calls' return points.  Off by default (0); Bubble Bobble uses 16: its main CPU 92.5k -> ~83.5k cycles a game frame.

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
  `Config.bit_s`, H after `ccf`, P/V only for `jp pe/po` right after `ldi`/`cpi`.  `python engine/xbench.py --seq 1000`
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

Compared with F030Arcade's spare-time renderer (a preemptible render thread on its own stack, started by Timer B once
the game is parked, its pages queued for the VBL) this schedule is the Heavy Barrel case there: the frame is the
interrupt handlers, so their return is the "frame is done" point and no park test is needed.  Bubble Bobble's three
screens are the queued pages; in the other ports a VBL nested into the drawing runs the game, so the drawing may go on
with a changed state (not checked port by port).  See `docs/porting-guide.md`, "Two related projects compared".

## Blitter sprite renderer (`games/dkong/src/sprites.s`, `engine/sprite_codegen.py`)

Blitter, like the bob routines of `stefastbobs2/main.s`: one blit per sprite line writes the
four planes of the line (Y count 4, source = destination), and the endmasks are the mask:
END1/END3 hold the outline of the line (holes included) shifted to the two screen words, so
the opaque pixels replace what is below and the rest stays.  No clearing pass, no colour
mixing: the screen equals the reference renderer pixel for pixel (frozen at frames 650, 800,
1000 and 1200: 0 of 57344 pixels differ; frame 800 re-checked after the MAME fixes below), and
the reference equals MAME's screenshot (see "Checking a reference against MAME").  A sprite's
left display column is u0 = y - 23 (it was y - 22 until 2026-10-08, see below).  The masks of every (shape, flip y, skew) are
a table (`dk_spr_masks`, 256 KB), the line words come from colour data baked per colour quad
(`dk_spr_data`, 608 KB: 19 distinct mappings of the pen values to the planes) that the
Blitter's source address walks through, `NFSR` lets the second destination word reuse the
one source word of a plane (a sprite of skew 0 is one word wide), flip x draws the lines
upwards.  The blitter registers of the line loop are written through preloaded pointers
(END1, END3, control, Y count, and the low word of the destination address, advanced with
`add d4,(a3)` as in the demo; sprites whose lines cross a 64 KB boundary of the screen use
full address writes).  The empty lines at both ends of a shape are left out (`dk_spr_span`). The fast
path now selects generated code for the shape/skew (`engine/sprite_codegen.py`): masks
that stay the same are not written again, empty interior lines are skipped, and a
line whose END3 is zero uses X count 1 even at a nonzero skew. Such a line clears
NFSR and sets destination Y increment to 2; a two-word line sets NFSR and Y increment
-6. Both finish eight bytes past their starting destination and consume eight source
bytes. Lines whose END1 alone is zero still use two words: their source would need a
different shift/pipeline arrangement. Colour data remains shared by every skew.
The generated instruction sequences and compressed mask streams are deduplicated
separately. Sprites near a 64 KB boundary retain the original unrolled full-address
path. `-D NOSPRITECODE=1` selects the generic renderer for comparison. END2 is unused.  Not implemented: the 16-sprites-per-
scanline limit and the wrap-around of the arcade hardware. Sprites are clipped at the aligned
left/right picture edges, including the generic 64 KB fallback; top and bottom use guard rows.

Most of the 128 list entries are empty, and visiting them all twice a frame cost 24K
cycles: a frame first lists the entries that are not empty (`tst.l` over the list), and
each draw screen keeps the list it was last drawn with.  Each draw screen remembers per
slot what it got there (list entry, colour bank, rectangle, cells).  A frame restores the
background under the sprites of the screen's old list that changed or are gone, then
draws the active list: a sprite that is unchanged is drawn only if its rectangle touches
an 8x8 cell that was redrawn (tile), restored or drawn (a sprite earlier in the list) in
this frame.  The cells are a bitmap (`tile_marks`, 8 bytes per display row, cleared each
frame); a sprite's cells are a window of four bits in up to three rows, kept in its slot
record, so a test is three `and.l` and a mark three `or.l`.

`z80_dma` (`engine/rt/rtlib.s`) is the 8257 sprite DMA, hooked on the `ld ($7D85),a` stores.

### Sprite blitter revision (2026-10-08)

`venv/bin/python engine/sprite_blit_test.py` builds both paths and executes the
assembled 68000 code on Musashi with a blitter model. For each port it verifies all
8192 shape/skew/line-direction combinations against independent masked pixels,
then compares 48 successive complete sprite renders against the generic path,
including overlap, background restoration, colour changes and 64 KB crossings.
The workload gives 3.2% less CPU plus blitter bus work for Donkey Kong and 4.3% for
Galaga; isolated line bodies save 9.0% and 9.9%. These are simulated cycle counts,
not Hatari frame-rate measurements. Executables grow by about 407 KB and 558 KB;
both ports still fit the configured 4 MB STE. Both rebuilt binaries also completed
5000 VBLs in the pinned Hatari with no crash file; screenshots confirmed the games
running (including Galaga's sprites). Bubble Bobble gained a separate reordered Blitter sprite
renderer in `games/bublbobl/src/srender.s`; its tile renderer remains the fallback.

The reference's arbitrary row reordering relies on matching reordered source data.
Copying that order without also preparing matching source data would break their sequential source walk.
This revision retains the source layout and uses register reuse and variable-width blits. The later
`engine/sprite_reorder_audit.py` is an instruction-cost estimate for source seeks, not an executed prototype of
reordered source data; the full preparation experiment remains outstanding (see `docs/sprite-preparation.md`).

## Tiles (`games/dkong/src/render.s`)

The 1 KB tile map is compared with a shadow every frame (the 224 visible longs, eight
per turn); changed tiles go into the background screen at once and into a queue for each
draw screen.  A palette bank change (level starts, the title wipe, the title logo's colour
cycle: 48 changes in 96 frames) draws only the visible tiles that look different in the new
bank: `dk_tile_pens` (the pens a tile code uses) against `dk_bank_change` (per old and new
bank and colour code, the pens whose palette index moves), both from `assets.py`.  In the
logo cycle that is about 160 of 896 tiles; the first frame draws all of them.

## Border removal

`engine/rt/borders.s` schedules events early and synchronizes them to the video. Timer B opens the bottom
border and arms Timer A at that line-exact point for the following top border. The VBL restarts Timer B and arms
Timer A as a fallback only when the preceding bottom event did not do so (including startup). `BD_HUD` extends
Timer B with palette switches; `BD_VSWITCH` also switches video addresses for separate HUD images.

Every Blitter pass is HOG and at most 256 bus cycles. `blit_go` splits longer transfers into lines or column
strips, allowing interrupts between pieces. The former `wait_borders` policy is superseded by these short passes
and early handlers. Verify actual timing in the pinned Hatari build: Musashi has no MFP timer model. Debug counters
record fallback arming and late border/palette events; `BLIT_STATS=256` reports oversized or non-HOG passes.

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

## Measuring (`games/dkong/tools/build.py` options, `games/dkong/tools/frametimes.py`)

* `--debug`: frame, Timer A, Timer B, VBL and skipped-VBL counters as bits in the top-left
  corner (plane 0, lines 0-4; read them back from a Hatari AVI).  An AVI starts at power
  on; the program starts about 300 VBLs later.
* `--dumpat N`: at frame N write Z80 memory `$6000-$7FFF` to `DUMP.BIN` and freeze the game;
  the screen can then be compared with `games/dkong/tools/machine.py render_raw()` of the same memory.
  `--dumpbank N`: the same at the Nth palette bank change (frame numbers of two builds show
  different game phases; 20 and 21 are in the title logo's colour cycle).  With TIMES, give
  `--frames` more than the run reaches: the frame count goes on while the game stands still.
* `-D TIMES=1 --debug --frames N`: MFP Timer D (81 us ticks) is started at every VBL and
  its count recorded when the NMI and when the drawing end, with the skipped-VBL count
  and the palette bank; `TIMES.BIN` is written when the program quits after N frames
  (`python games/dkong/tools/frametimes.py TIMES.BIN` prints the histogram).  Run with
  `--run-vbls` of about N*5/4+600.
* `--nosprites`: no sprite drawing (frame-rate comparison).  `-D NAME=VALUE`: any define.
* Profile: in the Hatari debugger `profile on` at one VBL breakpoint and `profile save` at
  a later one; Hatari 2.6 prints the per-address lines to its stdout.

Measured on 2026-10-07 (2400 frames of attract mode and demo play, 50 Hz frame =
160256 cycles): the average frame takes 44% of a frame (Z80 NMI 14%, drawing 30%),
play frames 50-80%, the busiest play frames 96-119% (6 of 2400), 0.5% of the frames run
into the next VBL; before this round the average was 75% and 9% of the VBLs were skipped.
Level starts and the title wipe redraw every tile and take about ten frames each.

Measured on 2026-10-09 (4096 frames, coverage of `port.py cover dkong`, after the
translator speed-up and the selective bank redraw): average 35% (Z80 NMI 9%, drawing 26%),
2.6% of the frames run into the next VBL.  The title logo's colour cycle (96 frames,
1.6 s on the arcade) lost 618 VBLs when every bank change redrew all tiles, now 148 (2 at
a change, 1 the frame after, for the other draw screen; the game's own code takes 32% of
a frame there).  The rest are the start, the title wipe (0 -> 2: nearly every tile) and
single level starts.  The game runs one NMI per 50 Hz VBL: 5/6 of the arcade's speed.


## Sprite edges and guard damage (all ports)

The hardware display window and the arcade picture inside it are different bounds. Pixels outside the hardware
window are hidden; side bands inside it remain visible. Reserve a wider virtual screen and vertical guard rows
for shifted objects, and restore each draw buffer's old sprite damage, including guard damage, before drawing again.

At a picture's left or right edge on a 16-pixel group boundary, cull sprites wholly outside and draw only the inner
destination word of a crossing sprite. Use the prepared opaque masks with the outer end mask zero, or a one-word
pass using the inner word's prepared end mask. Do not calculate another edge mask or erase new overhang after drawing.
This applies to every sprite path, including generic, cache-miss and address-crossing fallbacks. Top and bottom:
draw whole sprites into guard rows. Where a side edge falls inside a group, keep whole drawing into margins;
ports with moving windows may clip at the surrounding full band words while preserving the partial edge group.

The former blanket no-clipping rule was superseded on 2026-10-12. See `AGENTS.md` for the current rules and
`docs/sprite-preparation.md` for the preparation method and per-port results. Verify all four edges, all 16 shifts,
transparent holes, priority, 64 KB address crossings and consecutive frames against an independent reference.

Try the full stefastbobs2 preparation in each port: opaque runs and chains, grouping equal masks, reordered source,
prepared masks and generated code per shift, with reusable Blitter state and advancing source addresses. Retain an
optimization only after measuring CPU plus Blitter bus cycles; keep logic speed separate from picture rate. Cost
estimates and partial prototypes do not complete that experiment. Every HOG pass must stay at or below 256 bus
cycles and use the shared early, synchronized border handlers; verify timer timing in the pinned Hatari build.

The eight ports measured on 2026-10-12 were Donkey Kong, Galaga, Bubble Bobble, 1942, 1943, Black Tiger,
Commando and Gun.Smoke. Their picture costs on Musashi, before -> after clipping: 1942 -0.004% a tick,
1943 +0.02-0.04%, Black Tiger -0.05..+0.06%, Bubble Bobble cheaper overall (edge sprite +2%, guard columns gone),
Commando +0.04%, Donkey Kong +0.03%, Galaga -0.17%, Gun.Smoke -0.10%. These are historical results for that
cohort, not a claim that every current or future port has completed the same validation.

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
