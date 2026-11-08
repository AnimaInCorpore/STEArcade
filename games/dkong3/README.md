# Donkey Kong 3 (Nintendo, 1983) on the Atari STE

![Donkey Kong 3 on the STE (Hatari)](docs/screenshot.png)

MAME set `dkong3` (`nintendo/dkong.cpp`, `dkong_v.cpp`, `dkong_a.cpp`; the TKG-04 video board of Donkey Kong with a Z80 DMA
instead of the 8257).  The main Z80 (4 MHz) is statically translated to 68000 code (`engine/z80x.py` FAST) and checked in
lock-step against a reference machine (`tools/machine.py`); the Z80 DMA's sprite copy is a runtime routine.  The picture is
Mario Bros.' renderer (`games/mario/src/render.s`) turned to Donkey Kong's portrait screen: 224 x 256, tile playfield plus
generated-code sprites, equal to the reference pixel for pixel in the simulator.  The two sound CPUs (N2A03s, a 6502 with the
NES sound generator) are not run: their output is recorded in MAME per command and mixed on the DMA channel.  Status:
**Incomplete** (root README: the logic, the picture, the sprites and the sound driver's rules are checked in the simulator; Hatari
runs the whole program; no natural playthrough, the sound not listened to).  Speed: 51 arcade frames a second of 60.6 (84%),
27 pictures a second in the attract mode and the first stage (Hatari, `-D AUTOPLAY=1`, 3000 VBLs, 4 MB, 2026-11-08).

## Build and run

```sh
python port.py prepare dkong3            # or: python games/dkong3/tools/prepare.py   (assets/roms/dkong3.zip)
python port.py cover dkong3              # coverage (12 seeds of 20000 frames) and the pens the colours are fitted to (~3 min)
python games/dkong3/ref/sound_values.py 1 40000   # (seeds 1-8) the latch values the game sends: the sound's capture list
python games/dkong3/tools/build.py       # -> run/dkong3/DKONG3.PRG   (the first build records the sound in MAME: 94 captures, ~25 s;
                                         #    --sim: run/dkong3_sim for the tests; -D AUTOPLAY=1; -D NOSOUND=1)
python port.py test dkong3               # the lock-step, picture, sprite and sound tests
python games/dkong3/ref/mame_cmp_dkong3.py 300 1000 1800 3000   # the reference against MAME's picture
powershell -ExecutionPolicy Bypass -File games/dkong3/tools/hatari.ps1 -Frames 3000   # Hatari, hidden: AVI, stills, counters
```

Supply `assets/roms/dkong3.zip` (MAME's merged set: the parent's 16 files are used; `docs/rom_manifest.json` has their sizes, CRCs
and SHA-1s).  MAME is the F030Arcade checkout's WolfMAME 0.248 (`$MAME` overrides it; it runs on a desktop of its own,
`engine/mamewin.py`); the palette comes from it, the source of 0.286 agrees with its driver.  `VASM` / `VLINK` select the toolchain.
The program needs about 4 MB of RAM (the sprite code and the 256 KB dispatch table are most of it, the sound 0.87 MB).

## Controls

**5** coin, **1/2** start, **arrows** move (4-way: the ladders and vines go up and down), **Space/Ctrl/Z** fire (the spray gun),
**Esc** quits.  Joystick port 1 plays player 1, port 0 player 2; Jaguar pads as the other ports (D-pad, A/B/C fire).

## State

* **Logic**: exact against the reference.  `tools/logic_test.py` runs the idle loop `$0249` and the NMI in lock-step with the Z80
  reference: 3000 and 8000 frames of random play, and 3000 frames each with other DIP settings (lives, bonus, coinage, cabinet,
  the test mode) and a second seed; RAM, sound latches, latches `$7E81-$7E87`, registers and the unchanged ROM compared.
* **Reference against MAME**: the reference's picture equals MAME's snapshot at frames 300, 700, 1000, 1500, 1800, 2500 and 3000
  (0 of 57344 pixels differ; `ref/mame_cmp_dkong3.py`: MAME's RAM at the frame and its latch writes through the reference
  renderer).  Only the screen flip as the game sets it (flip 1) was seen; the unflipped (cocktail) orientation is MAME's source
  formula and Donkey Kong's checked one.  The reference's RAM is not compared with MAME's over time.
* **Picture**: exact.  `tools/render_test.py 3000 --start 100 --every 3` (seeds 1, 2, 5: 967 pictures each): 0 pixels differ, the
  side bands black.  `tools/sprite_test.py`: 316 pictures, both screen orientations: sprites across both edges at every pixel
  (16 shifts, generated code and row path), flips, colours, overlaps, the top and bottom guards, 64 KB crossings, consecutive
  pictures with all three buffers; a run with a planted band pixel fails (the test bites).
* **Sound**: `tools/sound_test.py 3000`: the driver's tables equal the converter's, 18000 voice states over 3000 frames equal a
  model of the rules, `snd_mix` against 40 random voice mixes (saturation, loops, ends, the ring wrapping): exact.  The clips
  themselves are MAME's output; nobody has listened to the STE's (Hatari ran with `--sound off`).
* **Hatari** (F030Arcade build, STE, 4 MB, TOS 2.06): 3000 VBLs of the attract mode, a coin, start and the first stage without a
  crash file; 2 border fallbacks, 1 late palette event in 3000 frames.
* **Not done**: a natural playthrough (the coverage and the tests play at random: the later stages and the ending have not been reached); the sound's open-ended loops and tune seams (below) heard; the arcade's 16 sprites per scanline
  limit and the wrap-around of sprites across the bitmap's edge (the reference has the wrap, `render_test.py` and `sprite_test.py`
  turn it off: the STE port does not draw the wrapped part); the Mega STE and a real STE; the speed work of the other ports.

## How it works

### The board and the reference

Memory map and latch bits: the header of `tools/machine.py` (ROM `$0000-$5FFF` and `$8000-$9FFF` (the sound driver's code and
tables), RAM `$6000-$6FFF`, sprite RAM `$7000`, video RAM `$7400`, the sound latches at `$7C00`, `$7C80`, `$7D00` that are also the
inputs and DIP switches when read, the latches `$7E81-$7E87`).  The game programs the Z80 DMA once per frame (`$6900` ->
`$7000`, `$19F + 1` = `$1A0` bytes: the chip transfers the block length plus one byte).  The picture: 32 x 32 tiles of 8 x 8
(codes `+ 256 *` the gfx bank, which is the inverted bit `$7E81`), colours from the PROM per column and four rows, 128 sprites
of 16 x 16 per sprite bank, 256 pens from the resistor network of `dkong3_palette` (`tools/dkong3_pens.py` is MAME's dump), shown
turned by 90 degrees.  The game sets the screen flip (every MAME frame dumped had it set): every tile and sprite is drawn as if turned by 180 degrees; MAME's
flipped sprites run their rows upward (row r on line `y + 8 - r`), which the reference reproduces.

### Translation

`tools/gen.py` translates 12,490 instructions (0 unsupported) from the coverage (`ref/cover.py`, 12 seeds: play, two players,
DIPs, the test mode) with `z80x.FAST`, a 64 KB block (`block=0x10000`: absolute reads of `$8000+` tables), calls of leaves up to 8
instructions in place.  The reads of the input ports go to unused bytes of the block (`IO_REDIRECT`); two register-indirect
reads of them (`ld hl,$7D00` in the coinage code, the boot test's `ld ix,$7C80`) are patched in the translated image because the
sound latches share their addresses.  Three stores through `HL` at `$0F56`, `$0F68`, `$0F6D` go to ROM addresses when the
pointer is still 0 (the arcade ignores them): `DK3Emitter` skips them below `$6000`.  `otir` at `$00DD` (the DMA's program) and
`ld a,r` are natives (`src/natives.s`); the store to `$7E85` calls `dk3_dma`.

### Schedule

As Mario Bros.: the foreground waits for the NMI at its idle loop (`$0249`, `z80_hook`); there the runtime draws the picture when
due, waits for the next arcade frame (the VBL adds one frame each VBL and a second one every fifth: 60 a second against the STE's
50), queues the sound commands (`snd_frame`) and delivers the NMI (`$0066`, token `$E001`) when `$7E84` allows it.

### Picture

`src/render.s` is Mario's renderer with the geometry turned: the picture is 224 wide (screen x 48-271, the side bands black) and
256 lines (`PIC_TOP` 10, `PIC_LINES` 256 as the other 256-line ports), three display buffers of 16 + 256 + 16 lines (sprites reach
the guard lines above and below) and a playfield of 224 x 256 pixels.  A video RAM cell (tx, ty) is the playfield cell (ty - 2,
31 - tx) (rows 2-29 of the map are the visible lines), with the screen flip at (29 - ty, tx) and the tile flipped in both
directions; the tiles and sprites are stored turned (`tools/assets.py`: `np.rot90`, so the arcade's sprite flip x is the picture's
flip y).  A cell is redrawn when its video RAM byte changes (the 1 KB compared with `cmpm.l`), or everything when the gfx bank, the
flip or the palette bank changes; a tile cache and a sprite cache fill on first use.  Sprite entries with y 0 are skipped fast.
The sprites are the generated code of `engine/sprite_programs.py` for the coverage's 135 shapes (row path for the others), OP 3
copy passes with the opaque pixels as end masks (no AND + OR), clipped at the picture's edges on its 16-pixel groups (the inner
word only), whole into the guard lines above and below.  Colours: 16 fitted to the coverage's pictures (`tools/assets.py`,
`ref/cover_pens.py`; mean error 1.7 levels a channel, the worst a grey that maps to blue).  Position formulas (`draw_sprites`): with
the screen flip clear X = 231 - y, Y = 240 - ((x - 8) & 255); flipped X = y - 23, Y = (x - 8) & 255; the flips inverted.

### Sound

Two N2A03s read the three latches in their vertical-blank NMI.  They are not run: `tools/sound_capture.py` records MAME's output
(`dkong3`, the main CPU parked on a `jr $`, a Lua script writing the latches; both N2A03s reset first) and `tools/sound_convert.py`
turns the recordings into 8 bit clips at 6258 Hz (`dkong3_sound.s`, 49 clips, 0.87 MB).  The standard captures come from
`ref/sound_values.py`'s lists (the values the game sends in 8 runs of 40000 frames): each value as a pulse of 3 frames (`P_`),
the values the game holds for 30 frames or more as a 5 s hold (`H_`: the tunes `$10`, `$40`, `$60` of latch 1), and every value
that contains a tune's bits as the tune with that value pulsed in (`S_`).  The effect on top of a tune is `S_` minus `H_`: the
difference is zero before and after the effect (checked for `$10` -> `$12`), so the tune goes on while the effect plays.  The
driver (`src/sound.s`) has six voices, a tune and an effect for each latch: a changed latch value starts or stops the tune it
holds and starts the effect it names; `snd_mix`, every VBL, brings a 2 KB ring buffer (the DMA plays it repeating) up to the DMA's
position plus 384 samples with the voices added (saturating).  Limits: a tune loops its 5 s recording from the start (a seam);
open-ended arcade sounds (some effects run until another command stops them) end after 4 s; values with no recording (silent
in MAME alone) play nothing; an effect that the CPU plays differently on another tune's bits is the one recorded on the first;
the clips are one level for all (peak 56 of 127: three voices add).

## Speed

| Date | Setup | Logic | Pictures | Musashi cycles |
|---|---|---|---|---|
| 2026-11-08 | Hatari, `-D AUTOPLAY=1 --debug`, 3000 VBLs, 4 MB, sound on (the DMA not played) | 51.1 arcade frames a second, 84% | 26.9 a second | logic 71k, picture 118k CPU + 53k Blitter bus cycles (`tools/render_test.py`, seed 1) |

Where a picture goes (`tools/profile.py 2500`): sprite cells 31%, the row copies from the playfield 25%, the sprite list 15%,
the tile compare 7%; the logic is flat (`$0240` idle loop 16%, the sound driver's code at `$8140` 6%).  The generated sprite code
against the row path: 134.6k + 56.1k -> 117.9k + 53.4k cycles a picture (`-D REN_GEN=0`), kept; leaves in place (8 instructions)
-2% of the logic.  Not tried: writer marks for the video RAM (the 1 KB compare is 7% of a picture), a native for the sound
driver's loop, dropping the playfield copy for the cells whose sprites moved.  Techniques other ports use:
[speed.md](../../docs/speed.md#techniques-that-look-applicable-elsewhere-2026-11-07).

## Tests and tools

* `tools/logic_test.py N [--seed S] [--dsw0 X --dsw1 Y]`: lock-step.  `tools/render_test.py N --seed S --start F --every K
  [--shots DIR]`: the STE picture against the reference.  `tools/sprite_test.py [--quick]`.  `tools/sound_test.py N`.
  `tools/profile.py N`.  `port.py test dkong3` runs them.
* `ref/mame_cmp_dkong3.py`: the reference against MAME's picture.  `ref/cover.py`, `ref/cover_pens.py`, `ref/sound_values.py`: the
  coverage and the data the build is made from (`build/dkong3/`, not committed).
* `tools/prepare.py`, `tools/gen.py`, `tools/assets.py`, `tools/build.py`, `tools/sound_capture.py`, `tools/sound_convert.py`,
  `tools/hatari.ps1` (an AUTOPLAY build in Hatari with the AVI, stills and `COUNTERS.BIN`).

## Lessons

* **A latch can be a read port at the same address** (2026-11-08): `$7C00`, `$7C80`, `$7D00`, `$7D80` are inputs and DIP switches
  when read and the sound latches when written.  The static redirect only covers `ld a,(nn)`; the two reads through a register
  (`ld hl,$7D00; ld a,(hl)`) gave the sound latch's last value: the lock-step test found it at the first frame.
* **A null pointer's stores must not reach the ROM image**: the arcade ignores writes to `$0000-$5FFF`, the translation's block
  holds the ROM.  The lock-step test compares the ROM bytes too (it first showed up as a wrong read of `ld a,($0008)` 230 frames
  later).
* **The flipped sprite's rows run upward** in MAME's line buffer; a first guess (rows downward from `y - 7`) was off in most sprites.
  The pictures of MAME at three frames fitted it exactly.
* **A MAME script's `--keep` directory must be absolute** (the Lua script is started in that directory).
* The 12-run coverage reached 7157-7360 pcs (the test mode run 1038); the lives, bonus and later stages come from random play only
  (MAME's cheat file was not read: no `7z`).

## Verification

Attract mode, a coin, the start and the first stage ran in Hatari without a crash (`tools/hatari.ps1`); the other checks are
simulator tests against the reference (above).  No natural playthrough and no PPO profile; see the
[status policy](../../docs/port-status.md).
