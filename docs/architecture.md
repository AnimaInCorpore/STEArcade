# Architecture

The project ports Z80 arcade games to the Atari STE (8 MHz 68000, 4 MB, 16 colours, Blitter).  Every port has three
parts, and the first two are checked against each other with a lock-step test:

1. **A reference machine** (`games/<game>/tools/machine.py`, on `engine/z80.py` and, for Bubble Bobble's protection MCU,
   `engine/m6801.py`): a Python model of the arcade board from the MAME driver.  It is the ground truth for the logic
   (RAM compared every frame) and for the picture (`render_raw`, itself compared with MAME's own screenshot, see
   `docs/porting-guide.md`).
2. **A static translation** of the Z80 (and 6801) programs to 68000 code (`engine/z80x.py`, `engine/translate.py`,
   `engine/m6801x.py`; the game specific part in `games/<game>/tools/gen.py`).  No interpreter runs: the arcade program
   is 68000 code, with the hardware accesses calling runtime routines.
3. **The STE runtime and renderer** (`games/<game>/src/*.s`, shared `engine/rt/rtlib.s`): video with the borders removed,
   the arcade's interrupts at the vertical blank, input, and a renderer that draws the arcade's tile map and sprite
   list.  Sprites are drawn with the **Blitter** (one blit per sprite line, masks as end masks, no clearing pass);
   tiles with the CPU.

Layout: `engine/` (shared), `games/<game>/{src,tools,ref}` (plus `docs/` where a game keeps notes and reference captures),
`build/<game>/` and `run/<game>/` (generated, not in git), `assets/roms/` (archives; `extracted/<game>/` the unpacked files),
`tools/hatari.sh` (Hatari driver) and `tools/windows/`, `port.py` (build/test/run front end), `legacy/` (superseded, not
built).  `engine/paths.py` knows where things are; `engine/toolchain.py` assembles and links (VASM/VLINK environment
variables select the tools).

## Renderers of the ports

| game | tiles | sprites | what is exact |
|---|---|---|---|
| Donkey Kong | CPU, shadow diff of the tile map, dirty queue per draw screen | Blitter, generated per shape/skew code | pixel for pixel against the reference and MAME |
| Galaga | CPU, 8 x 8 cells per colour quad, `chars_over` on top of sprites | Blitter, double sizes split into 16 x 16 parts, stars plotted after | renderer against MAME (RAM injected), reference identical |
| Bubble Bobble | CPU, `movep.l` per planar row, tile bake cache, dirty 8 x 8 cells | none: objects are strips of 8 x 8 tiles, shifted tiles merged into two cells by the CPU | pixel for pixel against the reference |
| 1942 | hardware scroll of a 768 line ring (three draw rings + clean), tiles baked per palette bank, characters redrawn when the window moves | Blitter, one blit per line, masks as end masks, rectangles put back from the clean ring | pixel for pixel against the reference (which equals MAME) |
| Commando | hardware scroll of three virtual screens with twin lines (line l = line l+320), only scrolled-in tile rows and changed tiles drawn, no clean map; characters a list rebuilt on change, `movep.l` | Blitter, baked shift streams; a damage list put back from the twin lines | pixel for pixel against the reference (which equals MAME) |

Bubble Bobble's measured cost (`games/bublbobl/tools/profile.py`, `render_bench.py`; numbers in its README) is not mainly the
shifted tiles: in the play a frame has ~570 tile draws, 495 of them aligned and 77 shifted (about 2.7k cycles each), over ~200
dirty cells (~9k cycles a cell), and at a scene change the colour mapping change (a new palette for 13 of the 16 banks)
costs 3-9 M cycles in one frame.  Two techniques that apply to any renderer with two draw screens and a colour budget:
cells the other screen lacks from the last frame are **copied from the screen shown** (a cell copy is ~500 cycles, drawing it
~7000), and a **stable slot assignment** with a per-bank mapping change keeps a new colour from remapping the whole palette
(and from redrawing the whole screen).  The Blitter (halftone/endmask merge of a baked tile) is not the first step for this
renderer; the per-cell work is.

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
emission); every port's gen.py goes through it.

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
  through its lock-step harness (`fullrun.py`).  Idle loops are counted apart (`IDLE`).
* `engine/xdiff.py galaga <old.PRG> <old.map>`: two builds side by side (separate processes: Musashi keeps the CPU in
  globals), the arcade's RAM compared at every game frame.  The interrupts come on a clock of translated instructions
  (and when no Z80 code runs for two frames), so both builds are interrupted at the same points of the Z80 programs:
  Galaga's main CPU draws text in its foreground, and a faster build is otherwise legitimately ahead.  The stacks are
  not compared (an interrupt's `push af` saves d6, which need not hold the interrupted code's flags: they may be in
  the CCR).  This is Galaga's translation test (its `galaga5.py` checks the reference only).

Measured 2026-10-08 (`xprof`, translated code per game frame, Musashi cycles; Bubble Bobble without its idle loop):

| port | before | after | |
|---|---|---|---|
| Galaga (both CPUs, frames 800-1200, attract) | 47.6k | 27.6k | 1.73x |
| Bubble Bobble (main, sub, MCU; frames 500-800, play) | 70.3k | 54.2k | 1.30x |
| 1942 (ticks 1100-1500, play) | 28.1k | 24.3k | 1.16x |
| Commando (ticks 600-1000, attract; 2026-10-09) | 8.4k | 7.0k | 1.20x |
| Black Tiger (ticks 600-1000, attract; 2026-10-09) | 15.7k | 12.9k | 1.22x |
| Donkey Kong (NMI, 1500 frames of fullrun.py) | 5.2k | 4.8k | 1.08x |

The gain is where the old code was weak: Galaga's `ldir` clears (37% of its cycles), the `ret` dispatch with A' in a3,
the high bytes.  Donkey Kong's code was lean already (16 cycles a Z80 instruction, mostly memory moves that cannot get
cheaper).  Not done, by expected gain: inlining small leaf functions (call + ret = ~65 cycles; ~8% for Bubble Bobble),
the MCU translator `m6801x.py` (9% of Bubble Bobble's translated cycles, untouched), keeping the Z80 stack words in
68000 order so `push`/`pop` of DE/HL/IX need no `ror.w #8` (3-5%; but code that reads the stack as memory would break),
Black Tiger guards every indirect access as a possible window read (a window check of ~40 cycles each: a quarter of its
translated cycles); coverage-found sites as in Bubble Bobble would make that cheap.  A factor of 2 for every
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
scanline limit and the wrap-around of the arcade hardware; sprites are not clipped at the
left/right edge of the game area.

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
running (including Galaga's sprites).  Bubble Bobble's renderer (`games/bublbobl/src/bb_render.s`) is
a complete tile renderer that does not use the Blitter; it has no sprite blitter to optimize, and its
measured cost is elsewhere (see "Renderers of the ports" above).

The reference's arbitrary row reordering relies on matching reordered source data.
Copying that order directly into these ports would break their sequential source
walk. This revision retains the source layout and uses the reference's register
reuse and variable-width blits where they can be applied without new colour copies.

## Tiles (`games/dkong/src/render.s`)

The 1 KB tile map is compared with a shadow every frame (the 224 visible longs, eight
per turn); changed tiles go into the background screen at once and into a queue for each
draw screen.  A palette bank change redraws everything (three times 1024 tiles, about ten
frames); the arcade does that at level starts and in the title screen's colour wipe, where
the game shows a still picture anyway.

## Border removal

Timer A must arrive in the *middle* of scanline 31 (`TA_DATA`), its handler then waits for
the next scanline start.  The VBL handler arms both timers first thing, and the rest of
the frame runs below the VBL level, so a frame that overruns the next VBL is interrupted
by it (`vbl_skip`) and the borders keep being removed.  Blits do not start while Timer A
is pending or Timer B is within 5 lines (`wait_borders`).  A measurement for all of this:
the top row of the game area in a Hatari AVI of 1800 VBLs is 0 for 1788 frames, 58 (border
not removed) for none.

## Measuring (`games/dkong/tools/build.py` options, `games/dkong/tools/frametimes.py`)

* `--debug`: frame, Timer A, Timer B, VBL and skipped-VBL counters as bits in the top-left
  corner (plane 0, lines 0-4; read them back from a Hatari AVI).  An AVI starts at power
  on; the program starts about 300 VBLs later.
* `--dumpat N`: at frame N write Z80 memory `$6000-$7FFF` to `DUMP.BIN` and freeze the game;
  the screen can then be compared with `games/dkong/tools/machine.py render_raw()` of the same memory.
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


## Whole-object drawing (all ports)

Use a wider virtual screen with enough hidden space on both sides for a whole
object, including the extra destination word of a shifted sprite. Objects crossing
an edge are drawn whole and disappear behind the visible display window. Do not
implement sprite clipping routines or calculate edge masks at runtime. Reserve
vertical guard rows too when whole objects can cross the top or bottom.

Sprite drawing follows `C:/Arbeit/stefastbobs2/main.s`: reorder source rows to group
equal opaque masks, bake the end masks for all 16 horizontal shifts, and reuse
Blitter state and its automatically advancing source address. Use short HOG blits
with the border timer guard. This is the required approach for every port; older
renderers must be migrated when their sprite drawing is changed.
