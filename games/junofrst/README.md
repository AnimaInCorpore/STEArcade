# Juno First (Konami, 1983) on the Atari STE

![Juno First on the STE (Hatari)](docs/screenshot.png)

MAME set `junofrst` (Konami GX310, `konami/junofrst.cpp` with `tutankhm_v.cpp`).  The main CPU, a KONAMI-1 (an MC6809
with encrypted opcodes: ROM $A000-$FFFF and sixteen 4 KB banks in a window at $9000-$9FFF, nine of them with code) is
statically translated to 68000 code.  The picture is the arcade's 256 x 256 bitmap of 4 bpp turned as MAME's ROT90
turns it (224 x 256, centred in the 320-pixel screen, borders open); the CPU and the 16 x 16 blitter draw into it, and
here both draw into the planar STE picture directly.  Status **Experimental**: logic and picture are exact against the
reference, but the program runs at ~58% speed and has **no sound**.  The sound board (a Z80 with an AY-3-8910, an i8039 with a
DAC) is not done; the commands to it are collected (`snd_ring`) for later.  The driver's structure and the plan are in
the session notes (tick = port A bit 5 edge, 14.4 a frame; Gyruss's `TickBoard` / `sndgen.py` / `sound.s` are the template).

## Build and run

```sh
python port.py prepare junofrst          # verify assets/roms/junofrst.zip, unpack to assets/roms/extracted/junofrst/
python port.py cover junofrst            # coverage: ref/cover.py seeds 1-12 (30,000 frames each, ~15 min in parallel)
python port.py build junofrst            # -> run/junofrst/JUNOFRST.PRG (--sim: run/junofrst_sim; --tag: another folder)
python port.py test junofrst             # logic and render tests
python port.py mame junofrst             # the reference against MAME (WolfMAME 0.248: set MAME=...\wolfmame-0248\mame.exe)
powershell -File games/junofrst/tools/hatari.ps1 -Frames 4000 -Every 400    # hidden Hatari, AVI stills in run/junofrst_hatari
```

Supply `assets/roms/junofrst.zip` (MAME's 14 files under MAME's names; `docs/rom_manifest.json` has their sizes, CRCs
and SHA-1s).  Nothing ROM-derived is in git.  Paths are relative to this folder; `engine/`, `tools/`, `port.py` and
`docs/` at the top are the repository's.

## Controls

**Arrow keys** move the ship, **Space / Control / Z** fire (X: the second button), **5/6** coin 1 / 2, **1/2** start,
**Esc** quits.  Joystick port 1 player 1, port 0 player 2; Jaguar pads: D-pad and A / B / C, **Option** coin,
**Pause** start.  Player 2 on the keyboard: R F A D move, G fires.  DIP switches: MAME's defaults (3 lives, difficulty 1,
1 coin 1 credit, demo sounds on).

## State

* **The reference against MAME** (`ref/mame_cmp_junofrst.py`, WolfMAME 0.248, frames 60-3600, no input): 0 of 16 pens
  and 0 pixels differ; the reference's RAM ($0000-$800F, $8100-$8FFF) equals MAME's at every frame checked.
* **Logic**: `tools/logic_test.py`: the translation on Musashi frame by frame against the reference's port schedule
  (`machine.JunoPort`): RAM, palette RAM, the picture (the planar `vram` against the reference's video RAM, lines 16-239),
  the latch, the bank register and the sound commands, 6,000 frames in each of the seeds 1-12 (attract, coin, start, random
  play and game overs, 256 lives, coin 2, two players, other DIP switches).
* **Picture**: `tools/render_test.py`: every published display buffer and palette equals the reference picture through
  the pen map, 3,000 consecutive frames of seed 1 (run before the speed work below; the logic test compares `vram`
  after it, in all 12 seeds).  `tools/sprite_test.py`: the fast blitter path against the reference blit.
* **Hatari** (F030Arcade build, STE, 4 MB, TOS 2.06, `tools/hatari.ps1 -Frames 4000`, looked at by eye, not compared):
  title screen and score table (all 256 lines, the colours as MAME's) and the first wave's warp intro; no crash, no
  late border event in 4,001 VBLs (2 fallbacks of the top border).  Play beyond the first seconds of wave 1 was not
  watched there.
* **Not done / not verified**: sound; the flip (cocktail) screen; coverage is random play only (12 seeds,
  ~13,700 translated instructions): later waves, the high-score entry and other rarely reached code may run into
  `main_badpc`; no PPO / Go-Explore profile; no recorded-play comparison; the compare with MAME has no input.

## Speed

Hatari 2026-11-07, `hatari.ps1 -Frames 4000` (AUTOPLAY: coin, start, move, the ship dies and the game plays on): 2,822
arcade frames in 4,001 VBLs (35.3 a second, 58% of the arcade's 60.6; 13.2 before the work below) and 935 pictures
(11.7 a second).  Musashi (`tools/logic_test.py`, 6,000 frames, seeds 1-12): the IRQ comes every other arcade frame, so
the cost is per game tick (two arcade frames, 264,000 cycles at full speed): the frames between cost about 14,000; the
75th percentile of the ticks is ~320,000-360,000 cycles, the 90th ~400,000-450,000, the maximum 1.5 million (a screen
that the program draws with its CPU loops).  What was done, in the order of the gain:

* the blitter (4-18 blits a frame): prepared images (`tools/assets.py`, 169 images, 865 KB: every non-empty 256-aligned
  image of the blitter ROM and every source the coverage saw; 16 shifts x 16 lines of two mask words and the plane words)
  drawn by 16 short HOG Blitter passes each (HOP 2 / OP 3 with the opaque pixels as the end masks, an erase HOP 0 /
  OP 0 with the same masks; one pass is 8 words, <= 96 bus cycles), ~2,300 cycles a blit instead of ~40,000; the words
  outside the picture are not drawn (group-aligned edges), a source without an image or a row that wraps (x > 240)
  takes the pixel by pixel path (`blit_slow`, the reference).  `tools/sprite_test.py`: 1,000 random cases (all 16
  shifts, every edge, copy and erase, unprepared sources, past the ROM) equal the reference blit;
* the program's clear loops ($A0ED, the boot's $A055) are natives (`native_clear_*`: Blitter fills of the picture's
  columns, short HOG pieces by `blit_go_fill`) instead of 29,000 byte stores each;
* `vram_wr` (the CPU's byte stores to the video RAM, ~140 a frame; the 98F0 copy loop of the title screens is the
  largest user): a table of every byte's plane address (`vw_ptr`, 128 KB) and `movep.l` read-modify-write of the four
  planes: ~350 cycles a byte instead of ~1,000.

What is left, by cost: `vram_wr` is still half of the logic's cycles (the CPU's own drawing loops, e.g. the byte copy at
$98EA that draws the title's image from ROM: a native that converts whole rows would remove most of it); the
translation's indexed accesses (`wrapped` in the translation report: 5,193 sites, not examined); the full-picture
Blitter copy of `render_frame` (40 KB, ~80,000 bus cycles a picture: a dirty-column copy would cut it).  Nothing
had to be dropped from the game so far.

## How it works

### The board and the reference (`tools/machine.py`)

* **Main CPU**: KONAMI-1 at 1.536 MHz (25,344 cycles a frame).  $0000-$7FFF video RAM (a 256 x 256 bitmap, 128 bytes a
  line, the even x in the low nibble), $8000-$800F palette RAM (one byte a pen, 3-3-2 bits through a resistor network),
  $8010 DSW2, $8020 SYSTEM, $8024 P1, $8028 P2, $802C DSW1, $8030-$8037 an LS259 (Q0 the IRQ enable, Q4 / Q5 the flips),
  $8040 the sound IRQ, $8050 the sound latch, $8060 the bank register, $8070-$8073 the blitter, $8100-$8FFF RAM,
  $9000-$9FFF the bank window, $A000-$FFFF ROM.  The IRQ comes on every other frame (a flip-flop at the VBLANK that has
  toggled once before frame 1: the first IRQ is the second frame).
* **Blitter** (`blitter_w`): 16 x 16 pixels from the 24 KB blitter ROM (nibble address, the high nibble first) to the
  video RAM at a nibble address (a row is 256 nibbles on); source pixels of 0 are skipped, the others are written, or a
  0 when bit 0 of the source address is clear (erasing).
* **Screen**: 256 x 224 visible (lines 16-239), ROT90: MAME's snapshot is 224 x 768 (every arcade column three rows);
  `np.rot90(rgb, +1)` equals it, picture line = 255 - x, column = y - 16.
* **Port schedule** (`JunoPort`): the foreground is a task loop at $A010 (queue read pointer $8872); the IRQ ($A00A) is
  delivered there on every other frame and the foreground then runs the queued tasks to the idle point again.
* **Difference to the 0.286 source**: the game writes Q4 = Q5 = 1 from frame 28 on; the 0.286 source's
  `flip_screen_x_w` flips the picture with the bit as is, but WolfMAME 0.248 shows the unflipped picture (what the
  reference matches: it flips while the bits are 0).  Not tested against a 0.286 arcade binary (none here).

### The translation (`tools/gen.py`, `engine/m6809x.py`)

* The window's code is virtual pages 8 + bank (slot 4's upper half), a context per bank (`ctx_banks`, a6; the bank
  register switches a6 and keeps the CC's E F H I); every data access of the program is flat (every VB is `jf_mem`).
* `engine/m6809x.py` got two backwards compatible Program options for this: `a3_pb` (DP and the stack are in slot 4,
  above $7FFF, out of reach of a 68000 displacement from VB: a3 = jf_mem + $8000, the static accesses `$offset(a3)`) and
  `indirect_io` (the pointer of `JSR [A,U]` / `JMP [A,U]` with the table in the bank window's data is read through
  `main_io_r`).  The constructor's assertion allows `a3_slot` up to 7.
* The accesses of the video RAM, $8000-$80FF and $9000-$9FFF go through `main_io_r` / `main_io_w`; the idle point is a
  native (`jf_idle`).

### The picture (`src/render.s`)

* The video RAM is not kept as bytes: `vram` is the picture, 256 lines of 160 bytes, planar.  `vram_wr` / `vram_rd`
  turn a byte (two pixels) into pixel writes / reads, `blit_run` runs the blit pixel by pixel; pixels in the arcade's
  lines 0-15 and 240-255 (not shown) are dropped.
* `render_frame`: a free one of three display buffers gets `vram` by one Blitter copy (HOG pieces, `borders_blit_go`) and
  the 16 palette RAM bytes through `ste_pal_tab` (the 16 pens are the 16 STE colours: exact, no fit; `tools/assets.py`),
  and is published for the next VBL (as Gyruss).
* Not optimised (see "Speed").

## Layout

`tools/` (prepare, machine, gen, assets, build, logic_test, render_test, hatari.ps1), `ref/` (cover, mame_cmp_junofrst),
`src/` (junofrst.s the runtime, render.s), `docs/` (rom_manifest.json, screenshot.png).
