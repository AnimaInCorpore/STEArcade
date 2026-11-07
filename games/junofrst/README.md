# Juno First (Konami, 1983) on the Atari STE

![Juno First on the STE (Hatari)](docs/screenshot.png)

MAME set `junofrst` (Konami GX310, `konami/junofrst.cpp` with `tutankhm_v.cpp`).  The main CPU, a KONAMI-1 (an MC6809
with encrypted opcodes: ROM $A000-$FFFF and sixteen 4 KB banks in a window at $9000-$9FFF, nine of them with code) is
statically translated to 68000 code.  The picture is the arcade's 256 x 256 bitmap of 4 bpp turned as MAME's ROT90
turns it (224 x 256, centred in the 320-pixel screen, borders open); the CPU and the 16 x 16 blitter draw into it, and
here both draw into the planar STE picture directly.  Status **Experimental**: logic and picture are exact against the
reference, but the program is **slow and has no sound**.  The sound board (a Z80 with an AY-3-8910, an i8039 with a
DAC) is not done; the commands to it are collected (`snd_ring`) for later.

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
  the pen map, 3,000 consecutive frames of seed 1.
* **Hatari** (F030Arcade build, STE, 4 MB, TOS 2.06, `tools/hatari.ps1 -Frames 4000`, looked at by eye, not compared):
  title screen and score table (all 256 lines, the colours as MAME's) and the first wave's warp intro; no crash, no
  late border event in 4,001 VBLs (2 fallbacks of the top border).  Play beyond the first seconds of wave 1 was not
  watched there.
* **Not done / not verified**: sound; the prepared Blitter sprite passes and every speed measure below; the flip
  (cocktail) screen; `tools/sprite_test.py` (there is no sprite renderer to test); coverage is random play only (12 seeds,
  ~13,700 translated instructions): later waves, the high-score entry and other rarely reached code may run into
  `main_badpc`; no PPO / Go-Explore profile; no recorded-play comparison; the compare with MAME has no input.

## Speed

Hatari 2026-11-07, `hatari.ps1 -Frames 4000` (AUTOPLAY: coin, start, move): 1,058 arcade frames in 4,001 VBLs (13.2 a
second, 22% of the arcade's 60.6) and 331 pictures (4.1 a second); the first 2,000 VBLs are mostly the boot's screen clear.  The logic of a frame costs about 470,000 68000
cycles in Musashi: almost all of it is the pixel routines.  The first screen clear alone (the boot's `CLR ,X+` over the
whole video RAM) runs 32,768 stores through `vram_wr`.  Where the time goes, in the order of the expected gain:

1. every blit (16 x 16 pixels, one `put_px` of ~150 cycles each; 4 to 18 a frame) and the CPU's byte stores to the video
   RAM (about 210 a frame, 29,000 in a screen clear): the blitter is a candidate for the prepared Blitter passes of
   `docs/sprite-preparation.md` (one prepared image per source nibble address: the coverage lists ~100 `(address, copy)`
   pairs in `build/junofrst/cover*.pkl`, `blits`; rotated, 16 shifts, end masks = the opaque pixels, one copy pass or one
   OP 0 pass), the clear loops for natives;
2. the translation's indexed accesses (`wrapped` in the translation report: 5,193 sites, not examined);
3. the `a3_pb` static accesses through `a3 = jf_mem + $8000` are as cheap as the other ports'.

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
