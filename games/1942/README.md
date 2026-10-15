# 1942, Atari STE

![1942 on the STE (Hatari)](docs/screenshot.png)

Fourth port (started 2026-10-08), the first with a **hardware scrolled** background.  The `1942` set (Capcom 1984, Revision B,
`assets/roms/1942.zip`, extracted to `assets/roms/extracted/1942/`).  Paths in this file are relative to `games/1942/`; the
shared pieces are described in `docs/architecture.md`, the method in `docs/porting-guide.md`.

* `src/` the runtime and renderer: `1942.s` (start, schedule, input, timers), `render.s` (video, palette banks, baking),
  `bg.s`, `chr.s` + `chr2.s`, `spr.s`, `frame.s` (one frame, data, variables), `sound.s` (the YM2149)
* `tools/` `machine.py` (reference machine), `gen.py` (translation), `assets.py` / `palettes.py` (graphics, palettes), `build.py`,
  `logic_test.py`, `render_test.py`, `profile.py`, `perf_test.py` (cost of a tick), `bench.sh` / `record.sh` (speed and frames in Hatari),
  `sound.py` (the sound driver's programs recorded, the player model), `sound_test.py`
* `ref/` coverage (`cover.py`), the MAME check (`mame_cmp_1942.py`, `mame_dump.lua`), `palette_stats.py`
* `docs/` `palette_stats.json` (how often every palette entry shows) and `palettes.json` (the four 16 colour palettes)

Controls: **5/6** coins, **1/2** start, **arrows** move, **Space/Ctrl** fire, **Alt** loop, **Esc** quits.  Joystick port 1
plays player 1, port 0 player 2 (fire = fire).
Jaguar pad / PowerPad (STE enhanced ports, `docs/architecture.md` "Input"): pad A player 1, pad B player 2, the D-pad moves, **A** fire, **B** loop, **Option** coin, **Pause** start, keypad **1/2** start, **5/6** coin, **\*** + **#** quit.
Tap the coin key: the game ignores a coin held for 40 ticks (the reference machine credits 3-20).

Build and run from the repository root (needs the venv of the quick start; `python port.py cover 1942` first, 16 runs of 60000 frames, about an hour;
seeds 5-8 play with MAME's cheats, 9-12 two-player games, 13-16 long games with the lives cheat, see "Later stages" below):

    python port.py cover 1942
    python port.py build 1942              # -> run/1942/1942.PRG (the ROMs embedded)
    python port.py test 1942               # lock-step against the reference, renderer against the reference
    tools/hatari.sh 1942 shot@30           # (or the Windows scripts, see below)

## What runs

* **One Z80** (the sound CPU is not translated: its output is recorded, see "Sound").  15k translated instructions
  (`tools/gen.py`, "signed" memory model: the 64 KB block with the video RAM and RAM below `a6`).  The program is a small
  cooperative kernel (tasks that sleep with `rst $18`, a scheduler that scans a 16 entry task table, `$0084-$009A`) with two
  interrupts: RST 08 (line 109, a sound command) and RST 10 (the vertical blank: sprite DMA `$EB00 -> $CC00`, scroll, timers).
* **The schedule** (`src/1942.s`, header and `z80_hook`; `tools/machine.py run_frame_port` is the same in Python): the foreground runs
  the tasks; when the scheduler finds nothing to run (the hook at `$009A`) the runtime draws the frame (if its tasks have all slept
  again) and delivers a pending VBL: RST 08 and RST 10 run to completion with a token on the Z80 stack.  RST 10 may hand the CPU to
  another task (`jp $0084`): the 68000 stack was reset before, so nothing leaks.  The VBL of the STE adds one tick to `vbl_pending`, and every
  5th VBL a second one: the game ticks 60 times a second (the arcade: 59.6) while the screen shows 50 frames.  Ticks that are due run before
  the next frame is drawn (at most `MAX_SKIP` + 1 ticks per frame, at most `MAX_PENDING` waiting): a game that is behind loses frames, not
  speed.  `-D NOTICK60` builds the old schedule, one tick per VBL.  The scheduler's search for a ready task is done natively (`scan_native`, saves 10% of the logic).
* **ROM banks**: `$8000-$BFFF` is a window onto three 16 KB banks (`$C806`); the program only reads them as data (the service mode
  is the one place that runs code from them, not translated).  Window reads go through `g_winbase` at the 97 instruction sites the
  coverage found (the mechanism of Bubble Bobble's main CPU), kept in `docs/window-sites.json` (read from there when no coverage file
  is present; `W_GUARD_ALL=1` guards every indirect access: the translated code 26.6k instead of 23.8k cycles a frame, `engine/xprof.py`);
  `tools/logic_test.py --audit` traces a run for reads of the block's own window area, which only an unguarded site makes (none in
  600 frames each of the attract, the cheats and two players).  Every store to `$C806` (`ld ($C806),a`, `ld (hl),n`, `ld ($C805),hl`)
  calls `g_bank_w`.
* **Translator changes** (`engine/z80x.py`, `engine/discover.py`, all opt-in so that the other ports generate the same code): the P/V flag
  of `and/or/xor` as parity in `d6` bit 7 for `jp pe/po` (also through the `ex af,af'` pair at `$261A` -> `$262D`), `bit` sets S as the
  CPU does, flags exact at `jp (hl)` and at the hook (the task contexts the kernel saves on its stack are compared byte for byte),
  `add iy,bc`, jump tables behind `call $66F7` (an index in A, the words follow the call).
* **Renderer** (below).  Border removal as in the other ports, plus the black bars (the picture is centred in the 276 lines).

## Renderer

The screen is the arcade raster rotated 270 degrees: 224 x 256, the background tilemap is 512 pixels long along the screen's vertical
axis and scrolls by one line every second frame, sprites (16 x 16, 16 colours) and characters (8 x 8, 2 bit) are fixed to the screen.

* **Hardware scroll.**  Three rings (two draw rings, `clean` = the background alone) of 768 lines of 256 bytes (the Shifter's line
  offset, `LINEWID`); line `L` is tilemap column `511 - L`, lines 512-767 repeat 0-255, so that the 256 line window from
  `T = (256 - scroll) & 511` never wraps (what is drawn into lines below 256 is drawn twice only for the background; sprites and
  characters go where the window of the frame has them).  No Timer B wrap trick is needed.
* **Three draw rings**: `render_frame` draws into a ring that is not shown, not waiting to be shown (`frame_ready` = its number + 1, one
  byte: the VBL sees a finished frame whole or not at all) and **not the ring that was shown until the last VBL**: Hatari scans that
  one out once more after the new video base is written, a ring drawn into then tears (the lower half of the picture showed the
  characters of the next frame, one or two lines off, while the upper half was steady).  The VBL shows the newest finished frame
  (video address = ring + `T` * 256 - `PIC_TOP` lines, palette `frame_pal`); a frame that is not shown when the next one is done is dropped.
  Every ring keeps its own state (`ring_T`, sprite rectangles, characters drawn, tiles to copy).
* **A frame** (`src/frame.s`): window and palette bank from the Z80's registers; background RAM and character RAM are compared with
  shadows (`bg_shadow`, `fg_shadow`) only when a store to them was seen (the translated code sets `bg_dirty` / `fg_dirty` at the 25 store
  sites the coverage found, plus a rescan every 32nd frame; `logic_test.py` checks that no change goes unflagged); new tiles are baked
  and put into `clean` and noted for both draw rings; the old sprite rectangles of the ring go back (Blitter copy from `clean`); tiles;
  characters (when the window moved - at every visit of a ring, the window moves between two of them - every occupied 16 x 8 chunk, in the
  order that draws the neighbour after: the old lines of a chunk that the new picture does not cover are put back as the chunk is drawn;
  else the changed chunks); sprites (below), entry 31 first; the characters that sprites cover are drawn again.
* **Colours**: 16 per palette bank (`tools/palettes.py`: weighted k-means in Oklab over the colours of the bank's background, the sprite
  and the character entries, weights from `ref/palette_stats.py`).  The pen masks of the graphics (`tools/assets.py`) are baked into STE
  planes on first use (`tile_get`, `sprite_get`, `char_get`) and cached; a bank change flushes the caches and redraws the background.
* **Timers**: `engine/rt/borders.s` (shared by the Blitter ports): Timer A removes the top border, Timer B the bottom one and
  switches the palette on at the picture's first line and off after its last (the black bars).  Blits that hog the bus delay the
  interrupts, so every event comes ~2-3 lines early and syncs itself to the video (Timer B polls its line counter, Timer A picks its
  HBL by reading its own counter); no blit waits.  `blit_copy` runs rows longer than 32 words a line a pass (`blit_go`).
* **Sprites** (`src/spr.s`, `tools/spritegen.py`, the method of `stefastbobs2/FAST_BLITTER_SPRITES.md`): the baked source of a part
  has its rows in blit order (equal opaque masks adjacent, transparent rows left out, `assets.sprite_orders`), one Blitter call per
  row draws the four planes (Y count 4, the opaque mask cut into the two destination words as END1 / END3, holes included, NFSR for
  the second word, X / Y increment 2 so the Blitter walks through the source itself).  There is a generated routine per row
  structure (772 for the 500 shapes, shifted or not, 93 KB) whose instructions are only register writes (`add d4,(a4)`, `move (a0)+,(a2)`,
  `move d6,(a5)`, `move.b d7,(a6)`, the Blitter's registers held in `a2-a6`, `d4-d7`); the masks and the control word (skew, NFSR) of
  the 16 shifts are a stream per (code, shift) (`spr_code_tab`, 202 KB), baked, nothing is computed at runtime.  Parts are drawn whole
  vertically (guard rows); across the game area's left or right edge only the inner word is drawn (`draw_edge`, see below).  The routines add to the low word of the destination address, so a part that reaches a 64 KB
  boundary of the ring (1 in 16) goes through `generic_part` (a Blitter call per row with the full address, same streams, rows from
  the shift independent `spr_plan`).  `render_test.py` checks that the margin chunks beside the game area stay black.  `spritegen.py` runs every (code, shift) routine against a model of the Blitter (stale source
  buffer bits, skew, NFSR, endmasks) over noise and refuses to write anything that fails.

## Sound (2026-10-11)

The sound board (MAME capcom/1942.cpp): a Z80 at 3 MHz, two AY-3-8910 at 1.5 MHz, four IRQs a frame; the STE's YM2149 is
the same chip with three channels instead of six.  Translating the driver would cost about 1700 Z80 instructions a tick
(as much as the game logic itself), so `tools/sound.py` records its output: every program (11 tunes, 14 effects) alone,
in ticks of four IRQs, as YM register images (periods x 4/3 for the YM's 2 MHz, tones clamp at 4095, noise at 31), until
its slot ends or its RAM repeats (a loop).  `src/sound.s` plays them in the driver's scheme (`sound.py` `Player` is the same
in Python): music slots `$4480 > $4300 > $4580 > $4600` and effect slots `$4100 > $4200 > $4180 > $4080`, only the highest
active one of each steps (the lower ones pause), `$4180` / `$4080` restart their effect every 32 / 8 IRQs, the stop
commands.  Six channels to three: the in-game drums (command `$11`) and the other first-chip tunes are the music, and
every channel an effect (second chip) sounds on replaces the music's channel of the same letter; the two-chip jingles
play three fixed channels each (`PICKS`: octave doublings dropped, the louder kept).  37 KB (2130 images of 12 bytes,
8.8 KB of program words).  The latch is read at every tick (`.deliver`, the command of the tick before), the YM gets
the registers that changed; no interrupt handler of the port touches the YM.

Room for it: `tile_ptr` holds word numbers of the baked tiles instead of pointers (128 KB less); the program leaves
about 125 KB free from the desktop (`tools/memfree.sh`).

Memory (2026-10-15): 3,933,862 -> 3,606,364 bytes, 444 KB left from the desktop (4,061,212 on a 4 MB STE with TOS 2.06;
a tester's Mega STE with a hard disk driver and accessories had 3,831,554: TOS refused to start it).  The tiles are
kept as the arcade's three bit planes (`tile_planes.bin`, 192 KB instead of 512 KB of pen masks); `tile_get` makes a
row's eight masks as it bakes (`engine/rt/penmasks.s` `pm_expand`, ~250 cycles a row).  Musashi (`perf_test.py`): tick
mean 139,461 -> 139,596, 99th percentile 238,852 -> 242,414.  The sprites as planes would save 196 KB more, but their
bakes made the 99th percentile 266,472 (+12%), so they keep their masks.

Checks: `sound.py check 3000` (the model against the driver run beside the game and with random commands): 273 of 3000
game ticks differ, 230 of them by a volume step of 1-2 (an effect that resumes in the middle of a tick: the model steps
whole ticks), the random command runs 15 and 0; `sound_test.py 3000` (in `port.py test`): the 68000 player against the
model, 0 of 9000 ticks differ.  `build.py --sound` records the programs again.

## Edge clipping of sprites (2026-10-12)

The game area's left and right edges (byte 24 and 136 of a line, black margins beside them, no horizontal scroll) are chunk
boundaries, so they follow the updated rule: a part across one draws only its inner destination word, a part wholly in a margin is
culled, nothing is erased afterwards; top and bottom stay whole in the guard rows.  `sprite_entry` tests the screen x with one
unsigned compare (`cmp.w #208` / `bhi .edge`, which replaces the two compares of the old cull, so inner parts got cheaper); the
edge branch culls x < -15 or >= 224 and calls `draw_edge` (`spr.s`): one Blitter call per row with X count 1 and the full address
(no 64 KB limit), masks from the existing streams of `spritegen.py` (unchanged, so 1943 is not affected), rows from `spr_plan`.
Right edge (x 209-223): the first word, skew s, END1.  Left edge (x -15..-1): the second word at chunk 0, FXSR with source Y
increment 0 (two reads a line advance one word), END1 := the stream's END3; source Y increment 2 again afterwards.  Only the
inner chunk is recorded for the restore and the character overlay.  (Before this the uncommitted tree drew parts whole into the
visible margins; HEAD cleared the margin chunk after drawing, `spr_clip`.)

Musashi, same frames and inputs, before (whole parts) -> after:
- `perf_test.py 3000` (2100 ticks from 900, CPU + Blitter a tick): 139461 -> 139455 (CPU 126281 -> 126408, Blitter 13180 -> 13046)
- `perf_test.py 3000 600` (level skips): 116884 -> 116897 (+0.01%)
- `profile.py 300 1250` (render_frame alone): 65915 -> 65798 cycles a frame (-0.18%; `draw_edge` 547 CPU cycles, Blitter 9556 -> 9294)
- Hatari (`bench.sh`, logic speed / picture rate): 58.1 ticks/s (98%) and 35.7 frames/s both before and after; no late border events.

Tests: `sprite_test.py` (new edge cases: every code at both edges with all 15 shifts, plain and across a 64 KB boundary, holes and
margins checked against the seed): 56993 draws and restores pass (33912 at an edge, 15000 of them across 64 KB; SEED=3: 57159); the
old whole-drawing build fails it at once.  `render_test.py` checks the margins again: `seq 600 1 1200` 0 differ / 0 with margin
pixels (old build: 56 of 600 frames with margin pixels), `seq 200` and `ATTRACT=1 seq 300` 0 / 0; `port.py test 1942` passes
(logic_test 6000 + more, 0 differences).

## Tests

    python port.py test 1942                       # build --sim, logic_test (6000 frames), render_test seq 200
    python games/1942/tools/logic_test.py 40000    # whole program on Musashi against the Z80 reference, RAM compared every frame
    python games/1942/tools/logic_test.py 12000 --two   # the same with a two-player game
    python games/1942/tools/sound_test.py 3000     # the YM player against tools/sound.py's model
    python games/1942/tools/sprite_test.py         # every sprite code, shift, many positions (edge clipping, 64 KB boundaries, re-baking), restore
    python games/1942/tools/spritegen.py           # sizes and the Blitter model check of all 8000 generated routine / stream pairs
    python games/1942/tools/render_test.py seq 600 1 1200   # picture of every frame against the reference renderer through the palette map
    python games/1942/tools/profile.py 60 1250     # cycles of render_frame by routine
    python games/1942/ref/mame_cmp_1942.py         # the reference renderer against MAME (needs ffmpeg and the wolfmame of F030Arcade)

Results (2026-10-08): the translation equals the reference over 40000 frames of attract mode and random play (RAM, video RAM,
sprite RAM and latches compared every frame, 0 differences); the renderer equals the oracle pixel for pixel in the 224 x 256 area
over 3000+ frames (attract mode and play, both palette banks seen, window positions with and without the wrapped part of the
ring); the reference renderer equals MAME's own picture (0 of 57344 pixels differ in 10 frames, palette banks 0 and 2, scrolling, sprites,
characters) and its RAM follows MAME's (the hook count of the old wolfmame is 120 frames behind its emulated frame).

## Hatari on Windows

`tools/windows/run.ps1` kills every running Hatari and its screenshots grab a wrong area at high DPI scaling.  What worked: start
Hatari with `--borders true --screenshot-dir <dir> --screenshot-format png`, send RightAlt+G (with scan codes) to its window and read the
PNG (Hatari's own screenshot, 2x the emulated 416 x 276); keys with scan codes and a hold time of 700 ms (the game polls the inputs
once per tick).  `-D DEBUG=1` builds count VBLs, renders and Z80 ticks and write `COUNTERS.BIN` at the end (`--frames N` quits after N
VBLs).  Never kill other Hatari instances.

## Speed (Hatari, 2026-10-08)

`games/1942/tools/bench.sh [finish_period]` builds the DEBUG + AUTOPLAY version (scripted coin, start, fire and joystick; MAME's cheats
for 1942b: lives E101, invincibility E0A5 and, every `finish_period` frames, "Finish Current Level Now!" EBD0 / E099 / E102 - the cheat that
selects a starting level did nothing in this set), runs 6000 VBLs in Hatari and reads `COUNTERS.BIN`: ticks a second (the arcade: 59.6),
frames drawn a second, VBLs between two ticks, CPU idle.  The first 300 VBLs are the boot, so 57.2 of 59.6 ticks is full speed.  Since 2026-10-12 it builds into
`run/1942_bench` (with the ROM bank files; `run/1942` keeps the normal build) and starts its own Hatari, stopped by its
PID: `tools/hatari.sh` stops every running Hatari, other benchmarks and interactive sessions too.  Items (`shot@60`,
`tap:5@20`, `dump:...`) work as in `tools/hatari.sh`; results land in `run/1942_bench`.

| | game ticks / s | frames drawn / s |
|---|---|---|
| before (one tick per drawn frame), the heavy scene (stage 1, many sprites) | about 40 (67% of the arcade) | about 40 |
| now, the same scene | 57.8 (full speed) | 35.3 |
| now, stages skipped every 600 frames | 57.6 (full speed) | 43.6 |

What was lost before: (1) a double buffer that blocked the renderer while the finished ring waited for the VBL (the CPU idled for a tenth
of its time), (2) one tick per drawn frame, so every slow frame slowed the game, (3) the characters redrawn at every ring visit (the
window moves between two of them): `draw8` and its bookkeeping were two thirds of a frame.  Musashi (`tools/perf_test.py`, `profile.py`)
counts the 68000's own cycles, Hatari takes about 1.35 times as many.  A tick of the logic costs about 36k, a frame 65-90k (heavy scenes:
sprites 50%, characters 30%), 8M cycles a second do not allow 60 ticks and 50 frames in the busiest scenes: the frames give way.
`tools/perf_test.py [ticks] [finish] [first] [norender|profile]` gives the cost of a tick, the heaviest ticks (stage changes cost 1-2.4M
cycles: the palette bank changes and every cached picture is baked again) and a profile by routine and by Z80 region.

Ideas for speed: sprite entries kept in registers (`sprite_entry` / `draw_part` are 15% of the frames of busy scenes), fewer rectangles
(one restore per sprite part), a faster bake of tiles at a stage change, native replacements for the kernel's timer loop (`$0055`) and the
task switch; a 4th ring is not possible (the program uses 3.85 of the 4 MB).

## Later stages (the coverage and the cheats)

The coverage of the translator comes from `ref/cover.py`; the first runs (random play without cheats) never got past the first stages,
and the program stopped at `z80_badpc` at the first stage change.  Seeds 5-8 play with MAME's cheats (lives, invincibility, a level skip
every 400 frames) and add 1800 program addresses.  `logic_test.py --cheat` (12000 frames, about ten stage changes, 0 differences) and
`profile.py [n] [first] cheat|finish` use the same cheats on both machines.  `render_test.py` takes `ATTRACT=1` (no coin) and `SCROLLRND=1`
(random scroll jumps: every sign and size of the window's move between two visits of a ring).

Two players and long games (2026-10-11): seeds 9-12 play two-player games (two coins, start 2, both joysticks, the turns
change at every death), seeds 13-16 long games with the lives cheat only (no invincibility, no level skips: the stages are
reached by playing, with deaths on the way).  They reach 69 program addresses the first eight runs did not (the two-player
turn change among them), but the static discovery had translated all of them already: the generated code is the same,
and no new window reads or video stores turned up.  `logic_test.py --two` (in `port.py test`) runs a two-player game in
lock-step (12000 frames, 0 differences).

## Debug options of the build (`build.py -D ...`)

`DEBUG=1` counters (`COUNTERS.BIN`) and assertions (list entries, Blitter rectangles), `AUTOPLAY=1` scripted play, `FINISH=n` level skips
with it, `RULER=1` a ring line number as colours in the left margin (the display of the lines can be read from a screenshot: no line
skipped or repeated), `NOTICK60=1` one tick per VBL, `STAGES=1` progress as colours.  `tools/record.sh` records Hatari's picture
(`recanim`) to look at frames one by one.

## Not done

The two AYs' six channels (three play); the flip screen (cocktail / DIP switch); the service mode (code in ROM bank 2); the arcade's
wrap around of sprites at the raw 256 pixel edges (entirely outside parts are not drawn); a palette per
scanline band (the HUD's colours are quantized with the playfield's); real hardware (only Hatari was used).  Ideas for speed: native
replacements for the kernel's hot routines, characters of the HUD rows drawn only when they change (static bands), pre-baked tiles for the
common colour codes.

## Translator speed (2026-10-08)

`alt_af="upper"` (A' in d0's upper bits, F' in d6's upper word: `ex af,af'` is two swaps, a3 is free for `ret`).  The
whole `z80x.FAST` passes the tests too (2026-10-09: `scan_native` writes d1-d3 as words now, the DEBUG histogram in
`z80_hook` saves d0/d1/a0), but it was 0.4% slower, and the engine's `ldir` was slower than 1942's own on its short
copies with the alternates in a0-a2: both stay as they were.  `scan_native` clears F with `clr.w d6` (a `moveq` would
clear F').  `gen.py` goes through
`translate.compile_code` (precise flag liveness over calls; the tasks started with `jp (hl)` and the hooks keep their
exact flags).  `engine/xprof.py 1942` (ticks 1100-1500): translated code 28.1k -> 24.3k cycles a tick (1.16x).  The
rest is spread thin: `ret`, `ldir` (by longs already), `push`/`pop af` around calls, `bit n,(ix+d)` with the exact S.
Tests: `logic_test.py 6000`, `sprite_test.py`, `render_test.py seq 200 1 1200` pass; Hatari runs the attract mode.
