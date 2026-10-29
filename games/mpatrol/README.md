# Moon Patrol (Irem, 1982) for Atari STE — work in progress

MAME set `mpatrol` (Irem M52, the parent set; `assets/roms/mpatrol.zip` also holds the Williams clone `mpatrolw`).
Started 2026-10-29.  Not in `port.py list` yet: the scripts here run on their own.

```sh
python games/mpatrol/tools/prepare.py              # verify assets/roms/mpatrol.zip, unpack to assets/roms/extracted/mpatrol/
python games/mpatrol/tools/machine.py 300 2400     # run the reference board, pictures to build/mpatrol/ref<frame>.png
MAME=<mpatrol.exe> python games/mpatrol/ref/mame_cmp_mpatrol.py [frame ...] [--play] [--keep <absolute dir>]
```

The authoritative MAME for this port is the 0.286 source in `F030Arcade/third_party/jsm68kdisassembler/third_party/mame`
(the reference follows its `src/mame/irem/m52.cpp`).  Its `m68k.exe` has no M52 driver; `mpatrol.exe` next to it is
the same source built with only that driver, in its own build folder (MSYS2 UCRT64, from that folder):

```sh
mingw32-make MINGW64=/c/msys64/ucrt64 ARCHITECTURE=_x64 TOOLCHAIN=/c/msys64/ucrt64/bin/ \
  BUILDDIR=build_mpatrol SUBTARGET=mpatrol SOURCES=src/mame/irem/m52.cpp REGENIE=1 NOWERROR=1 -j32
```

(`OS=Windows_NT MSYSTEM=UCRT64`, `/c/msys64/ucrt64/bin` and `/c/msys64/usr/bin` first in PATH,
`CXXFLAGS=-D__USE_W32_SOCKETS`, as its `build_m68k_all.sh`.)  `--keep` needs an absolute path: MAME runs inside
that folder.

`docs/rom_manifest.json` lists the 17 files of the parent set (MAME's names, sizes, CRCs, SHA-1s).

## The board (MAME irem/m52.cpp)

* **Main CPU**: Z80 at 3.072 MHz, 16 KB of ROM (flat, no banking), 2 KB of RAM at $E000.  IRQ 0 at the VBLANK
  (HOLD_LINE), 56.74 Hz (384 x 282 at 6.144 MHz): 54,144 CPU cycles a frame.  A custom "protection" read at $8800
  returns popcount(bg1 x & $7F) ^ (bg1 x >> 7) of the last write to I/O port $40.
* **Picture**: 240 x 252 (x 136-375, lines 22-273), drawn back to front: the sprite palette's pen 0; the distant
  mountains (256 x 64, 2bpp, own x / y); the hills *or* the city (256 x 64, 2bpp, sharing the second x / y), each
  with its lowest colour filled over the 128 lines below; the text layer (32 x 32 tiles of 8 x 8, 2bpp, 512 codes, 128
  colours; tile rows 0-6 opaque, the score panel), whose tilemap lines 192-255 (the ground) scroll by the scroll
  register and the rest stay; 64 sprites of 16 x 16 (3bpp with a zero plane: 4 pens, 16 colours), drawn per group of
  16 from the last entry to the first, with transparency by colour lookup (a pen is transparent when the lookup PROM
  gives colour 0).  No partial updates: the state at the VBLANK is the picture.
* **Colours**: three PROM palettes through resistor networks (text 512 pens, sprites 256 through a lookup PROM,
  backgrounds 12).  The reference shows up to 23 colours in one frame (median 15) and 28 overall in 9,000 frames of
  attract and random play; the score panel (tile rows 0-6: picture lines 0-49) uses 8, the playfield below it 26.
* **Sound**: Irem's M52 "Sound C" board: the M6803 driver (4 KB, `mp-s1.1a`), two AY-3-8910s and one MSM5205, on a
  smaller map than Kung-Fu Master's M62 board, whose translated driver (`games/kungfum/tools/sound.py`,
  `src/sound.s`) is the model to start from.

## State

* `tools/machine.py`: the reference board (MAME's Z80 core, MAME's timing, the renderer from m52.cpp of the current
  MAME source).  It boots without patches (no long self-test), runs the attract mode (title, demo play, insert coin)
  and plays: coin, start, the beginner course, scoring, dying, the continue countdown, game over.
* **Reference == MAME 0.286** (`ref/mame_cmp_mpatrol.py`, 2026-10-29): all 780 pens equal; at frames 60, 300, 600,
  900, 1200, 1500, 1800, 2100, 2400, 2700, 3000 and 3600 of the attract mode 0 differing pixels (the reference
  drawing MAME's memory and registers, and drawing its own), and the reference machine from power-on equal to MAME in
  the text RAM and RAM (4 KB), the sprite RAM, the six video registers and the sound commands.
  With input (`--play`, the same inputs and DIP switches read
  by MAME through `engine/mame_frames.lua`'s INPUTS read taps and by the reference): coin, start, invulnerable random
  driving: all equal at frames 420-8400, the city background (control $03) from frame 5488 on included.
* WolfMAME 0.162 / 0.184 are no substitute for the picture: their m52 video (MAME 0.183's `video/m52.cpp`) puts the
  backgrounds at x + 128 / y + 14 (now + 124 / + 16), the sprites at x + 128 (now + 129) in another order, fills
  with pen 0 and draws hills and city together.

## Next steps (docs/porting-guide.md)

1. The port schedule (`MoonPatrolPort`: idle hooks of the foreground's wait loops) and coverage (`ref/cover.py`, random
   play over every course and sector: the Sector Selection DIP switch reaches them, plus game over, the high-score
   entry and the continue).
2. Translation (`tools/gen.py`, `z80x.FAST`), lock-step `logic_test.py`.
3. Runtime and renderer: the score panel (picture lines 0-49) from its own image with its own colours, the playfield as
   three parallax layers (two 256-pixel-wide backgrounds and the ground) plus Blitter sprites prepared the
   stefastbobs2 way (`engine/sprite_programs.py`, HOP 2 / OP 3 copy passes, no AND + OR pairs; see `AGENTS.md`).
4. Sound from the M6803 driver, after Kung-Fu Master's.
