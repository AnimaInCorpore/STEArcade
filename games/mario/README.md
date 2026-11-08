# Mario Bros., Atari STE

Nintendo, 1983 (MAME `mario`, US revision E, `nintendo/mario.cpp`).  Z80 at 4 MHz, a Z80 DMA for the sprite copy, a
sound MCU (M58715, internal ROM not dumped) with discrete sound.  256 x 224, horizontal, 59.185 Hz.

![Mario Bros. on the STE (Hatari)](docs/screenshot.png)

Status: **Incomplete** (root README).  State (2026-11-08): the picture runs on the STE (Hatari: title, attract, play; 1800 VBLs with `-D AUTOPLAY=1`: 56 arcade
frames a second of 59, 29 pictures a second) and equals the reference through the fitted 16-colour palette in the
simulator (`tools/render_test.py`: seeds 1, 2, 5, 3000 frames each, 0 differing pixels).  Sound: the board's output recorded in MAME and played on the DMA
channel (`src/sound.s`: the tunes and effects the game commands; one clip at a time, the newest wins; the walk pulses are silent
in MAME's netlist and not played); checked in the simulator only (`tools/sound_test.py`: the DMA registers name the
clip each command starts), not listened to in Hatari.  `tools/sprite_test.py` passes (316 pictures, both screen orientations: edges, 16 shifts, flips, guards, 64 KB crossings, sequences, in the simulator), no full-game verification, speed work started (a picture was ~113k CPU cycles + ~45k Blitter bus cycles; now ~96k + ~45k in Musashi, not re-measured in Hatari: a fast skip of unused sprite entries -8k, the video RAM compared with `cmpm.l`/`dbne` -8.5k; `tools/profile.py` shows the rest: sprites ~60%, row copies 15%, tile compare 8%).

```sh
python port.py cover mario                  # coverage (12 seeds), then
python games/mario/ref/cover_pens.py <seed> 12000   # (seeds 1-6) the colour fit's training data (tools/assets.py)
python games/mario/tools/build.py           # -> run/mario/MARIO.PRG   (--sim: run/mario_sim for the tests; -D AUTOPLAY=1)
python games/mario/tools/logic_test.py 3000 # lock-step translation vs reference
python games/mario/tools/render_test.py 3000 --seed 1 --start 100 --every 3   # the STE picture vs the reference
python games/mario/tools/sound_test.py 3000 --seed 5       # the sound driver vs the game's commands (clips: tools/sound_capture.py --all, MAME)
powershell -ExecutionPolicy Bypass -File games/mario/tools/hatari.ps1 -Frames 1800   # Hatari, hidden: AVI, stills, counters
```

Controls: **5** coin, **1/2** start, **Left/Right** move, **Up/Space/Ctrl/Z** jump, **Esc** quits; joystick port 1 player 1,
port 0 player 2; Jaguar pads as the other ports.

| part | state |
|---|---|
| `tools/prepare.py`, `docs/rom_manifest.json` | the 15 files of revision E verified (`mario.zip`, an older merged set: files from `marioe/` and the top level) |
| `tools/machine.py` | reference machine (Z80, Z80 DMA, latch, NMI, tile map + sprites); `ld a,r` reads the port's random byte like the other ports |
| `ref/mame_cmp_mario.py` | the picture against MAME (wolfmame 0.248 binary; `mario_pens.py` is its pen dump): 0 / 1 / 4 pixels differ in frames 1500 / 2500 / 700 (fast sprites a step ahead) |
| `ref/cover.py` | coverage, 12 seeds of 20000 frames (play, free play + lives by MAME's cheats, two players, DIPs, service mode) |
| `tools/gen.py`, `src/natives.s` | translation: 10450 instructions, 0 unsupported; `otir` ($00CD, the DMA's program) and `ld a,r` are native routines; the self-test's stores to unmapped $EC00-$EC02 go to unused bytes |
| `src/mario.s`, `src/render.s` (after Pooyan's runtime and Track & Field's renderer), `tools/assets.py`, `tools/build.py` | the STE program: NMI at the idle hook, 256 x 224 centred with the borders open, tile cache + playfield with the scroll and flip, sprite cache and generated Blitter code, bounded 16-colour fit |
| `tools/render_test.py` | the STE picture against the reference: 0 pixels differ (seeds 1, 2, 5) |
| `tools/logic_test.py` | lock-step against the reference at the idle loop $01CB with the NMI injected: OK over 3000 frames (coin, start, random joystick) |

## Hardware notes

* Memory map and latch bits: the header of `tools/machine.py`.  The game programs the Z80 DMA once per frame
  (`$6900` -> `$7000`, `$180 + 1` bytes: the chip transfers the block length plus one byte); the port uses the shared
  `z80_dma` (`$180` bytes: the extra byte read as 0 in every captured frame).
* The picture is MAME's with the LS259 latch's flip bit set in play: the tile map is flipped, sprite positions are
  already physical (`flip_screen_set` flips only the tile map).
* The translation's dispatch table has 65535 entries (the ROM at `$F000` holds code; `z80_init_dispatch` compares words);
  the NMI token is `$E001`.  The upper ROM lies below the Z80 block (signed word index).
* Not yet checked: the DMA's bus cycles (6 clocks a byte are modelled), the mid-frame latch writes (the title screen
  writes the gfx and palette bank at line 19), cocktail flip, the MAME 0.286 palette (the pens come from WolfMAME 0.248, a binary; the 0.286 source tree is authoritative, AGENTS.md).

## Next

speed (the picture's ~96k CPU cycles + ~45k Blitter bus cycles: `tools/profile.py`), a coverage that reaches the later phases, full-game checks (`docs/port-status.md`).
