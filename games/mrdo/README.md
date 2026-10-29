# Mr. Do!, Atari STE

Port started 2026-10-29.  Set: MAME `mrdo`, Mr. Do! (Universal), 1982; one Z80, two SN76489s, two 2-bit tile layers
and 64 sprites of 16 x 16 (2 bits).  Paths in this file are relative to `games/mrdo/`; the method is
`docs/porting-guide.md`, the driver MAME 0.286's `universal/mrdo.cpp`, `mrdo_v.cpp` (the authoritative source tree).

State (2026-10-29): the reference machine's picture equals MAME's frame for frame (2696 of 2701 frames of the attract
mode; the other five differ in a tile column written at the frame's end); the Z80 program is translated and runs on
the 68000 in lock-step with the reference's port schedule (12 seeds, 144,000 frames exact) and at full speed in
Hatari.  The runtime (`src/mrdo.s`) is complete but for the sound;
`src/render.s` is a stand-in (a black screen) until the renderer is written.  Not registered in `port.py` yet.

* `src/mrdo.s` the runtime (schedule, IRQ delivery, borders, inputs, sound bytes into a ring, crash dump);
  `src/render.s` the picture (a stand-in)
* `tools/prepare.py` the ROMs; `tools/machine.py` the reference machine (`MrDo`) and the port's schedule (`MrDoPort`);
  `tools/gen.py` the translation; `tools/build.py`; `tools/logic_test.py` the lock-step test; `tools/hatari.ps1` a
  hidden Hatari run (counters, AVI; `-Extra -DAUTOPLAY=1`: a coin, start and play from the VBL)
* `ref/cover.py` coverage; `ref/mame_cmp_mrdo.py` the reference against MAME's picture

From the repository root: `python games/mrdo/tools/prepare.py`, coverage `python games/mrdo/ref/cover.py <seed> 20000`
for seeds 1-12 (`build/mrdo/cover<seed>.pkl`, needed by the translation; about 20 minutes each, run them in
parallel), `python games/mrdo/tools/build.py --sim` (`run/mrdo_sim/MRDO.PRG`), then
`python games/mrdo/tools/logic_test.py 12000 --seed <n>`.  `build.py` without `--sim` builds `run/mrdo/MRDO.PRG`.
Controls (planned as on the other ports): arrows or joystick move, Space / Control / Z fire, **5** / **6** coin,
**1** / **2** start, **Esc** quits; either Jaguar pad plays (the players take turns on the upright cabinet).

## ROMs

`python games/mrdo/tools/prepare.py` verifies the fifteen files against `docs/rom_manifest.json` and writes them to
`assets/roms/extracted/mrdo/` and `build/mrdo/mame_roms/mrdo/` (MAME's `-rompath`).  The archive is
`assets/roms/mrdo.zip`, MAME's merged set; the parent's files are at its top.

## Reference machine

`tools/machine.py` (`MrDo`), from MAME's driver:

* Z80 at 4.1 MHz (8.2 MHz / 2).  The screen: 312 x 262 pixel clocks at 4.9 MHz (19.6 MHz / 4), 59.943 Hz, so
  68398.04 CPU cycles a frame (kept fractional: a frame ends at the exact cycle); visible raw x 8-247, y 32-223
  (240 x 192), ROT270.
* ROM 0000-7FFF; background video RAM 8000-87FF (attributes 8000: bit 7 code bit 8, bit 6 opaque, bits 0-5 colour;
  codes 8400), foreground 8800-8FFF (the same; its writes also latch the PAL U001, which does nothing in the `mrdo`
  set); sprite RAM 9000-90FF (write only); 9800 flip screen, 9801 / 9802 the SN76489s, 9803 the protection; inputs
  A000 P1, A001 P2 (coins), A002 / A003 the DIP switches (defaults $DF / $FF); RAM E000-EFFF; scroll x F000-F7FF,
  y F800-FFFF (written only at F000 / F800).  Unmapped reads give 0.
* The protection read `$9803` gives the ROM byte at HL: MAME's stand-in for the PAL (`mrdo_state::protection_r`, "HACK:
  workaround until accurate PAL emulation").  The program reads it once (`$0494`, with HL in a ROM table at `$0547`).
* IRQ0 at the vertical blank (line 224), `irq0_line_hold`: held until taken; IM 1 (RST 38).  A frame starts at the
  vertical blank (`frame_line=224`, MAME's phase): `render_raw` after `run_frame` is the picture MAME draws.
* Colours: `palette_init`'s diode / resistor levels (150, 120, 100, 75 ohm, 220 pull-down, 0.7 V) computed in single
  precision as the C++ does; 256 character pens, 64 sprite pens through the lookup PROM `f10--1.bin`.
* Renderer: the background (scrolled: screen x + scroll x, screen y + scroll y) then the foreground, 32 x 32 tiles of
  8 x 8 each; a tile's pen 0 is transparent unless its attribute bit 6 makes it opaque.  The sprites from entry 63 down
  to 0 (entry 0 on top), x = byte 3, y = 256 - byte 1, skipped when byte 1 is 0, clipped to the visible area; pen 0
  transparent.  MAME flips the tile layers for the cocktail cabinet but not the sprites; the reference draws upright
  only.  `python games/mrdo/tools/machine.py 900 out.png` boots and saves a picture.

## Checked against MAME

`python games/mrdo/ref/mame_cmp_mrdo.py [seconds]` records MAME's attract mode with F030Arcade's WolfMAME 0.162
(`-aviwrite`; the local 0.286 builds `m68k.exe` / `mpatrol.exe` have no `mrdo`) and looks every MAME frame up among the
reference's frames by its exact RGB picture.  WolfMAME's `-listxml` gives the same clocks and screen as the 0.286
source.  2026-10-29, 45 s (2701 frames):

* 2696 frames equal a reference frame; all 14 colours on screen are exactly MAME's.
* 5 others (frames 3, 517, 2074, 2075, 2077) differ from the nearest reference frame in 67-1100 pixels within one or
  two tile columns: video RAM written right at the frame's end, a few Z80 cycles apart (the old core's timing).

Not checked yet: play with input, the flip screen (cocktail; the port is upright), sound.

## The port's schedule

The whole game runs from the IRQ (RST 38, the handler at `$00B8`): the objects through a table of 20 handlers at
`$0156`, the sound, the screen.  Its end looks at `$E001`: bit 0 restarts the maze search (`$54EC`, a flood fill over the
13 x 12 cells, which runs on into `$558E` and `$5647`) on a fresh stack at `$0138`; bit 2 runs `$558E` at `$0141` and
returns to the interrupted code through the registers the IRQ saved; bit 4 restarts `$5647` at `$014D`; bits 1 / 3 (a
search runs) return to it.  The searches run with interrupts enabled, and on the arcade the next IRQ cuts into them.
Otherwise the foreground spins at `$00AC` (after the boot) or `$0154` (after a search).

`machine.MrDoPort` (the reference) and `src/mrdo.s` (the runtime) do the same: the IRQ is delivered only at those two
spins (the idle hooks), with TOKEN (`$FFFE`) as the interrupted pc; the handler runs to its return to TOKEN (the
foreground goes on at the hook) or into a search, which runs to its end at `$0154`.  So a search never sees an IRQ in
its middle.  Measured in the reference with the arcade's timing (attract and random play, 4000 frames): the handler
takes 22.8k Z80 cycles a frame (median; 46.5k at the 99th percentile; 307k once, while a scene is drawn), a search up
to 59k (0.86 frame), and a search was still running at the next IRQ in about 75 frames of the 4000.  Those frames get
longer here and the search's result comes a frame or two earlier than on the arcade; the arcade's restart of a running
search by a new dig cannot happen.  Yield points inside the searches (their loop heads `$552E`, `$5609`, `$5665`, with
a deterministic budget) would keep the arcade's pace if the long frames show in Hatari.

## Coverage

`ref/cover.py <seed> [frames]` (20000 frames each, the seeds in its docstring): random play to the game over, MAME's
cheats (infinite lives `$E097`, the start scene `$E09B`), two players, the other DIP switches, the rack test switch.
2026-10-29: 8824 pcs; scenes 1-12 and 21-23 reached.  The service test (both fire buttons at power on, `$56AF`) and
the cocktail cabinet are left out.

What it found:

* The SN76489s are written with `ld (nn),a` (`$5AE7`, `$5AEE`) and with `ld (bc),a` (`$5C3A`, `$5C3E`, `$5C45`: C is
  the chip, $01 / $02); every other I/O store is the flip latch, the sprite RAM or the scroll registers.
* Inputs are read with `ld a,(nn)` only: the runtime keeps them at `$A000-$A003` in the block.
* 28 computed jumps (the object table at `$0156`, `jp (hl)` dispatchers); no `in` / `out`, `halt` or `ld a,r`.

## Translation

`tools/gen.py`: the program flat (32 KB) in a 64 KB block (`signed` mode, the fast register map), IY / F' at `$9E00` /
`$9E02` (unmapped on the board).  10980 instructions (8824 seen by the coverage, 2156 found by discovery), nothing
unsupported, nothing missing.  The protection read at `$0494` is translated as `ld a,(hl)`.  The SN76489 stores call
`md_sound1` / `md_sound2` (`ld (nn),a`) or `md_sound_bc` (`ld (bc),a`: the chip from C), which put (chip, byte) pairs
into `snd_ring`; the 36 video RAM store sites list their cell (`md_mark_*`: the address & $3FF, + $400 for the
foreground) for the renderer.

`tools/logic_test.py` compares every frame: the video, sprite and work RAM, the flip latch, the scroll registers, the
SN76489 bytes of the frame, and that every changed video RAM cell is listed.  2026-10-29: seeds 1-12, 12000 frames
each (144,000 frames), all exact.  The logic takes 35-54k 68000 cycles an arcade frame over those runs (Musashi; 43-46k
in attract and normal play, 51-54k with the cheats' longer games).

Found on the way, fixed in `engine/z80x.py` (`pv_block_before`): the two-player game copies a player's maze with
`ldi; inc hl; jp pe,$10C6`, and the translator produced P/V only for a `jp pe/po` right after the block instruction;
past the `inc hl` it read a stale flag (seed 7 differed from frame 1043 on).  No other port's generated code has that
shape.

Hatari (`tools/hatari.ps1`, DEBUG + AUTOPLAY, 3000 VBLs, the stand-in renderer): no crash, 59.5 arcade frames a
second (the arcade's 59.94).

## Next steps

1. The renderer (`src/render.s`, `tools/assets.py`, `tools/render_test.py`): the two tile layers (the background
   scrolled), the sprites by the reordered-source method (`engine/sprite_programs.py`, `docs/sprite-preparation.md`),
   the palette (the 14+ colours of a scene into 16), and the picture's 240 x 192 on the STE (ROT270: rotated, or the
   arcade's raw orientation with the playfield sideways; to be decided).
2. Hatari: the logic's pace with the long search frames; yield points if they show.
3. The sound: the two SN76489s on the YM2149 (three tone voices and noise each).
4. Registration in `port.py`, `tools/release.py`, the README's table.
