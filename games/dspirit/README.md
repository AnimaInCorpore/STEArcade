# Dragon Spirit

Atari STE port (4 MB) of the MAME set `dspirit` (Namco System 1, ROT90): the main and sub MC6809E programs translated
to 68000 code (`engine/m6809x.py`, `tools/gen.py`, `src/core.s`) on the reference board `engine/namcos1.py`, as
Galaga '88 (`games/galaga88`) and Splatterhouse (`games/splatter`).  Work in progress: the translated logic runs in
lock-step with the reference (SIM build only); the STE program, the MCU, the renderer and sound are not written yet.
This port uses its standalone scripts and is not registered in `port.py` or included in releases.

## Logic

* **Coverage** (`ref/cover.py SEED FRAMES [--port]` -> `build/dspirit/cover_[port_]SEED.pkl`): seeds 1-3 the attract
  mode, seeds 4+ coin, start and random play (the 8-way stick, air shot 60%, bomb 15% of the holds: `random_bits`).
  `--port` runs the port's schedule (`tools/machine.py run_frame_port`) with the inputs of `tools/logic_test.py`: the
  port runs ahead of MAME's schedule (no frames the game overran), so MAME-schedule coverage misses scenes the port
  reaches (the attract mode's later scenes, page $371).  `tools/gen.py` reads both kinds.
* **Schedule** (`tools/machine.py`): as Galaga '88's (the vertical blank, the MCU and the sound CPU on the board's
  scheduler, then the main CPU's IRQ and frame, then the sub CPU's).  The port starts at frame 300.
  * Main (DP $40: slot 2, the work RAM): `8048: JSR $8770` (the random numbers: an LFSR step of `<$D3/$D4`),
    `804B: STA $F200; LDA <$FF; BNE 8048`, then `INC <$FF; JSR $8140` (the frame).  The IRQ handler ($81B4) clears
    `<$FF`.  The arcade steps the LFSR on every pass (~3600 a frame); the port once a frame: idle at $804B while `<$FF`
    is set (core.s `main_idle`).
  * Sub (DP $20: slot 1, the scratch RAM; its stack in slot 2): it never waits.  The IRQ handler ($D6CD) clears byte 9
    of every sprite entry; the foreground loop `D6C5: STA $F200; JSR $D8B0; BRA D6C5` builds the sprite list from the
    objects in the work RAM ($41A0 + $28 n) on every pass, from scratch (~12 passes a frame in the arcade).  The port
    runs one pass a frame: back from the IRQ at $D6C5 the pass starts, at its end the sub is idle (`sub_pass`, core.s
    `sub_idle`).
  * The port's game runs ahead of the arcade's (frame 600 of the intro: the dragon already formed, MAME still in the
    flash): the arcade's main CPU overruns some frames; the port's schedule has no such frames.
* **Direct page**: per CPU (`Program(dp=, a3_slot=)`; core.s `DPS` / `DPR` in the context).  The main CPU's bank
  routines in page $334 ($A215, $A22A) use DP as a scratch register (`TFR B,DP`: DP = slot * $20 + $10) and map slot 6
  to the C116 registers (page $173) or TRIRAM (page $17F); the code after them reaches those through `<$xx` with DP
  $C0 / $D0 (a constant per site, `dp_sites`).  The routines' shared instructions run with several DPs: allowed where
  the instruction neither addresses the direct page nor reads DP (`gen.py dp_free`).
* **Page $334 in two slots**: the main CPU runs that page's position-independent code from slots 5 and 6.  The
  translation keeps one slot per page: slot 6's copy is page $30C (a mirror of the same ROM bytes; `PAGE_ALIAS` in
  ref/cover.py and tools/gen.py, `Program.page_alias` for the translation's inline bank writes, core.s `bank_set` and
  `alias_page`, its own 8 KB copy so the translation's page checks by address tell the two apart).
* **Jump tables** (`gen.py table_targets`): random play does not reach every entry of the state machines' tables
  (`JMP [A,U]`, `JMP $2000,U` after `LDU A,U`, `JMP D,X`).  Per computed jump the coverage saw: the table's base from
  an immediate load on an executed path just before it, then its entries while they stay in the slot of the seen
  targets, outside the table and the executed instructions, and decode as legal code; they become roots (30 tables,
  ~250 entries).  Entries into a slot whose page is set just before the jump (main $B80B: slot 3 = page $371) are not
  found that way: coverage only.
* **The protection check** (main $B65C-$B672): slot 0 gets page $173 (the C116's registers), the program patches the
  byte at $0004 from $0001 / $0003 and calls `JSR $0002`: `PSHU` with no registers, then `RTS` ($39) when the check
  passes.  The port does not run code from RAM: core.s `main_prot` checks the three bytes and goes on after the JSR
  (else badpc $0002).
* **Stores into ROM**: main $AC00-$AC1A (`STA $6000` / `$6200` / `$6400` / `$6600`) write into slot 3's ROM page; the
  arcade ignores them.  Such sites (`gen.py rom_writes`) go through core.s `io_w`, which drops stores into ROM pages.
* **Key custom**: CUS136 (type 1): registers 0-2 read the remainder and the quotient of regs 1-2 (16 bits) by reg 0
  (8 bits), register 3 the id $36 (core.s `key_divide`: one `divu`).

Translator fix found here (engine/m6809x.py, all 6809 ports): a post-increment operand whose slot is computed at run
time (`LDD ,Y++`) took the slot of the incremented register when the 16-bit access emitted the operand twice (Y = $7FFE
read $8000's slot).  Galaga '88 and Splatterhouse: 600 frames still identical.

Test: `tools/build.py --sim`, then `tools/logic_test.py FRAMES --seed N` (frame by frame against the reference: work
RAM, TRIRAM, the CUS30 RAM, tile RAM, palette, scratch and sprite RAM, CUS123 control, the key custom, `sub_pass`,
both CPUs' registers and pages; `--steplock F` instruction by instruction, with the slot pages, the cached registers and
the ROM image's changed bytes at a difference; `--trace F` the last translated labels).

Results (2026-11-07): main 13579, sub 2657 instructions translated, none unsupported (coverage: MAME schedule seeds 1,
4-8, 4000-6000 frames; port schedule seeds 1, 5, 6, 12-15, 8000 frames).  `logic_test.py 7700` identical for the
attract mode (seed 1), the covered play seeds 5 and 6 and the uncovered seeds 9, 10 and 11; 96k-114k 68000 cycles a
frame for the two CPUs (Musashi), the attract mode ~63k.  Random play reaches only the first stage or two: later
stages' code is translated where static flow and the jump tables reach it (`badpc` / CRASH.TXT where not); coverage
of later stages (snapshots, a scripted or Go-Explore player, `docs/go-explore.md`) is open.

Next: the STE program (snapshot at frame 300, the MCU - Splatterhouse's native model of the CUS64 program, to be
checked for Dragon Spirit -, the display, a renderer from Galaga '88's), then sound.

## Display (decided with the user, 2026-11-07)

Upright (the arcade picture 288 x 224 turned to 224 x 288, as MAME shows it), on the STE's 320-pixel width: the
picture in the middle, 48-pixel side bands.  The open borders give 277 lines (engine/rt/borders.s, as Galaga '88), 11
short of 288: the text lines that do not fit are to be placed elsewhere (the side bands) later.

## Full-game verification status

Automated players such as Dreamer can attempt a full playthrough once this port's
adapter and native Hatari replay transport are verified. An attempt or assisted
stage visit does not establish completion; a successful natural Hatari playthrough
and graphics, sound and control checks are required for green **Complete** status.
See the shared [status and verification policy](../../docs/port-status.md) and
[current port status](../../README.md). Existing test results above retain their
stated scope; this note does not claim a new successful run or Dreamer integration.
