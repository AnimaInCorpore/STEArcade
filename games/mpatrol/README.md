# Moon Patrol (Irem, 1982) for Atari STE — work in progress

MAME set `mpatrol` (Irem M52, the parent set; `assets/roms/mpatrol.zip` also holds the Williams clone `mpatrolw`).
Started 2026-10-29.  Not in `port.py list` yet: the scripts here run on their own.

```sh
python games/mpatrol/tools/prepare.py              # verify assets/roms/mpatrol.zip, unpack to assets/roms/extracted/mpatrol/
python games/mpatrol/tools/machine.py 300 2400     # run the reference board, pictures to build/mpatrol/ref<frame>.png
MAME=<mpatrol.exe> python games/mpatrol/ref/mame_cmp_mpatrol.py [frame ...] [--play] [--keep <absolute dir>]
for s in $(seq 1 9); do python games/mpatrol/ref/cover.py $s 20000; done   # coverage (~2 min each, in parallel)
python games/mpatrol/tools/build.py --sim            # the translation -> run/mpatrol_sim/MPATROL.PRG (no STE build yet)
python games/mpatrol/tools/logic_test.py 20000 --seed 1   # the translation in lock-step with MoonPatrolPort
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

## The schedule (`tools/machine.py` `MoonPatrolPort`)

The IRQ handler ($0038) does the game: it copies the sprite list ($E100) to the sprite RAM and writes the scroll
registers ($056D), counts the frame ($E04E) and two timers ($E050, $E051: decremented every frame, wrapping), reads
the inputs ($E053 = IN0 inverted) and runs the game's step ($040E and on); at $0104 (a coin in the attract mode) it
restarts the foreground with a new stack.  The foreground waits for the IRQ in loops on RAM the IRQ changes; those pcs
are the idle hooks (the runtime draws there, waits for the next arcade frame and delivers the IRQ with a token as its
return address, as Kung-Fu Master's):

| pc | waits while | what |
|---|---|---|
| $026E | always (once a frame) | the work loop: five helpers, then the IRQ's task queue ($E600, $E1CF / $E1D0) |
| $05ED, $0359, $0315 | $E050 != 0 | waits of $E050 frames (screens, the typewriter texts) |
| $078E | $E047 != 0 | until the IRQ clears $E047 |
| $010D | no start (`starts()`) | "push start": start 1, or start 2 with more than one credit (0533) |
| $01A7 | $E050 != 0 and no start | the continue's countdown ($E054 every $40 frames) |
| $0B59 | $E051 > 1 | sector selection: no new start 1 press until the time runs out |
| $00AF (in the IRQ) | IN0 bit 0 set | stop mode: the handler waits for start 1; the next frame goes on there, no new IRQ |

The work loop's helpers run once a frame instead of as often as the arcade's spare time allows; they are gated by the
IRQ's counters and the game's state, so the game is the same: in the attract mode every port frame equals a MAME frame
pixel for pixel (the port 7 frames ahead after the boot, whose frames with interrupts off the arcade loses, 15 by
frame 2400).  `ld a,r` (the random numbers at $1B45) reads a 16-bit shift register (`rnd`), as in Kung-Fu Master.

## Coverage (`ref/cover.py`)

Nine seeds of 20,000 frames in the port's schedule (RAM addresses from MAME's cheats, mpatrol.xml): 1-2 plain play
(deaths, continue, game over, new games; seed 2 two players), 3-6 invulnerable with MAME's "finish current section"
every 900 frames (every point of the Beginner and Champion courses, the courses after them: $E510 up to 5), 7 the
sector selection DIP switch, 8 the stop mode, 9 other DIP switches (5 lives, no bonus, 1 coin 2 credits, coin mode 2).
Together 4,030 pcs, 65 computed jump targets, 50 text RAM writers, 158 sprite (code, colour, flip) combinations on the
screen.  Static discovery (`engine/discover.py`) finds 631 more pcs: the service mode ($3300-$393B, DSW2 bit 7: left
out, as in Kung-Fu Master), the typewriter's pause codes ($0310), rare paths of the game ($184E, $11BC, $07B1: other
coinage settings).  Not covered: the flip screen (cocktail).

## The translation (`tools/gen.py`, `src/mpatrol.s`)

The 16 KB program is translated statically (`translate.compile_code`, `z80x.FAST`, the signed 64 KB block): 4,312
instructions from the coverage's pcs and computed jump targets, the hooks, and every entry of the three jump tables
(`gen.TABLES`: the object types at $020C through `rst $28`, 49 words; the work loop's tasks at $02D3, 11; $08F5, 24),
plus what static discovery reaches from them; the service mode ($3300 on) is left out (`z80_badpc`).  The
memory-mapped I/O lives in the Z80 block, so reads need nothing: the runtime keeps IN0, IN1, IN2, DSW1, DSW2 at
$D000-$D004 (copied there when an arcade frame starts; the program also reads them through (de) and (hl)) and the
protection byte at $8800 (computed when port $40 is written).  The stores to the latches (`ld ($D000),a`, the sound
command; `ld ($D001),a`, the flip latch) get a write hook (`mp_sound` / `mp_flip`) that takes A and puts the input
byte back.  The ports (`out ($C0),a`, `out (c),a`, `outi`) go to `mp_out_*` routines that store the byte into
`io_regs` by port >> 5 and keep the flags, but `outi`, whose S, Z, N and C are MAME's (B - 1; the carry of (hl) + l).
`ld a,r` (13 sites) reads `z80_rnd`.  `src/mpatrol.s` is the simulator's runtime so far: the hooks (`z80_hook`, the
conditions of `MoonPatrolPort.HOOKS`, the stop mode's wait inside the handler), no picture, no sound, no STE hardware.

`tools/logic_test.py` runs the translation (Musashi) in lock-step with `MoonPatrolPort` through the coverage seeds'
inputs, cheats and DIP switches: the text RAM, the RAM, the sprite RAM, the six video registers, the flip latch and
the sound commands are equal every frame, 20,000 frames of each of the nine seeds.  The logic takes 24.6k-29.1k
68000 cycles a frame (Musashi), a fifth of an STE frame.

## Next steps (docs/porting-guide.md)

1. The STE runtime (hardware, borders, IKBD and pads, the VBL's arcade frames: 56.74 Hz on 50) and the renderer:
   the score panel (picture lines 0-49) from its own image with its own colours, the playfield as three parallax
   layers (two 256-pixel-wide backgrounds and the ground) plus Blitter sprites prepared the stefastbobs2 way
   (`engine/sprite_programs.py`, HOP 2 / OP 3 copy passes, no AND + OR pairs; see `AGENTS.md`).
2. Sound from the M6803 driver, after Kung-Fu Master's.
