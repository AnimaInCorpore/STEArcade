# 1942, Atari STE

Fourth port (started 2026-10-08), the first with a **hardware scrolled** background.  The `1942` set (Capcom 1984, Revision B,
`assets/roms/1942.zip`, extracted to `assets/roms/extracted/1942/`).  Paths in this file are relative to `games/1942/`; the
shared pieces are described in `docs/architecture.md`, the method in `docs/porting-guide.md`.

* `src/` the runtime and renderer: `1942.s` (start, schedule, input, timers), `1942_render.s` (video, palette banks, baking),
  `1942_bg.s`, `1942_chr.s` + `1942_chr2.s`, `1942_spr.s`, `1942_frame.s` (one frame, data, variables)
* `tools/` `machine.py` (reference machine), `gen.py` (translation), `assets.py` / `palettes.py` (graphics, palettes), `build.py`,
  `logic_test.py`, `render_test.py`, `profile.py`
* `ref/` coverage (`cover.py`), the MAME check (`mame_cmp_1942.py`, `mame_dump_1942.lua`), `palette_stats.py`
* `docs/` `palette_stats.json` (how often every palette entry shows) and `palettes.json` (the four 16 colour palettes)

Build and run from the repository root (needs the venv of the quick start; `python port.py cover 1942` first, about 15 minutes):

    python port.py cover 1942
    python port.py build 1942              # -> run/1942/1942.PRG (+ the five ROM files)
    python port.py test 1942               # lock-step against the reference, renderer against the reference
    tools/hatari.sh 1942 shot@30           # (or the Windows scripts, see below)

## What runs

* **One Z80** (the sound CPU is not translated: the main CPU only writes commands to it).  15k translated instructions
  (`tools/gen.py`, "signed" memory model: the 64 KB block with the video RAM and RAM below `a6`).  The program is a small
  cooperative kernel (tasks that sleep with `rst $18`, a scheduler that scans a 16 entry task table, `$0084-$009A`) with two
  interrupts: RST 08 (line 109, a sound command) and RST 10 (the vertical blank: sprite DMA `$EB00 -> $CC00`, scroll, timers).
* **The schedule** (`src/1942.s`, header and `z80_hook`; `tools/machine.py run_frame_port` is the same in Python): the foreground runs
  the tasks; when the scheduler finds nothing to run (the hook at `$009A`) the runtime draws the frame (if its tasks have all slept
  again) and delivers a pending VBL: RST 08 and RST 10 run to completion with a token on the Z80 stack.  RST 10 may hand the CPU to
  another task (`jp $0084`): the 68000 stack was reset before, so nothing leaks.  The VBL of the STE only raises `vbl_pending`
  (a flag: the arcade holds an interrupt line while it is masked); a game that does not finish its tasks in a frame runs slower, the
  display goes on.  The scheduler's search for a ready task is done natively (`scan_native`, saves 10% of the logic).
* **ROM banks**: `$8000-$BFFF` is a window onto three 16 KB banks (`$C806`); the program only reads them as data (the service mode
  is the one place that runs code from them, not translated).  Window reads go through `g_winbase` at the 87 instruction sites the
  coverage found (the mechanism of Bubble Bobble's main CPU); every store to `$C806` (`ld ($C806),a`, `ld (hl),n`, `ld ($C805),hl`)
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
* **Double buffering**: `render_frame` draws into one draw ring, the other is shown; at the VBL `vbl_video` switches the display to the
  finished ring (video address = ring + `T` * 256 - `PIC_TOP` lines) and the next frame may start (the hook waits while `frame_ready`).
* **A frame** (`src/1942_frame.s`): window and palette bank from the Z80's registers; background RAM and character RAM are compared with
  shadows (`bg_shadow`, `fg_shadow`) only when a store to them was seen (the translated code sets `bg_dirty` / `fg_dirty` at the 25 store
  sites the coverage found, plus a rescan every 32nd frame; `logic_test.py` checks that no change goes unflagged); new tiles are baked
  and put into `clean` and noted for both draw rings; the old sprite rectangles of the ring go back (Blitter copy from `clean`); tiles;
  characters (when the window moved: every occupied 16 x 8 chunk, the old lines that no new picture covers put back; else the changed
  chunks); sprites (below), entry 31 first; the characters that sprites cover are drawn again.
* **Colours**: 16 per palette bank (`tools/palettes.py`: weighted k-means in Oklab over the colours of the bank's background, the sprite
  and the character entries, weights from `ref/palette_stats.py`).  The pen masks of the graphics (`tools/assets.py`) are baked into STE
  planes on first use (`tile_get`, `sprite_get`, `char_get`) and cached; a bank change flushes the caches and redraws the background.
* **Timers**: Timer A removes the top border, then switches the palette on at the picture's first line and off after its last (the black
  bars; `TA2_DATA`, `TA3_DATA` found by looking at screenshots), Timer B the bottom border.  **Blits that hog the bus delay the VBL and
  the border timers and make the picture flicker**: a sprite part (16 short row blits, about three scanlines) starts only when
  `wait_borders` allows; `blit_copy` runs without HOG and is waited for.
* **Sprites** (`src/1942_spr.s`, `tools/spritegen.py`, the method of `stefastbobs2/FAST_BLITTER_SPRITES.md`): the baked source of a part
  has its rows in blit order (equal opaque masks adjacent, transparent rows left out, `assets.sprite_orders`), one Blitter call per
  row draws the four planes (Y count 4, the opaque mask cut into the two destination words as END1 / END3, holes included, NFSR for
  the second word, X / Y increment 2 so the Blitter walks through the source itself).  There is a generated routine per row
  structure (772 for the 500 shapes, shifted or not, 93 KB) whose instructions are only register writes (`add d4,(a4)`, `move (a0)+,(a2)`,
  `move d6,(a5)`, `move.b d7,(a6)`, the Blitter's registers held in `a2-a6`, `d4-d7`); the masks and the control word (skew, NFSR) of
  the 16 shifts are a stream per (code, shift) (`spr_code_tab`, 202 KB), baked, nothing is computed at runtime.  Parts are drawn whole
  into the virtual ring without clipping.  The routines add to the low word of the destination address, so a part that reaches a 64 KB
  boundary of the ring (1 in 16) goes through `generic_part` (a Blitter call per row with the full address, same streams, rows from
  the shift independent `spr_plan`).  `spritegen.py` runs every (code, shift) routine against a model of the Blitter (stale source
  buffer bits, skew, NFSR, endmasks) over noise and refuses to write anything that fails.

## Tests

    python port.py test 1942                       # build --sim, logic_test (6000 frames), render_test seq 200
    python games/1942/tools/logic_test.py 40000    # whole program on Musashi against the Z80 reference, RAM compared every frame
    python games/1942/tools/sprite_test.py         # every sprite code, shift, many positions (edges, 64 KB boundaries, re-baking), restore
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

Musashi cycle counts per frame (a 50 Hz frame is 160256): game logic mean 40k (95%: 70k, level changes up to 1.5M once), `render_frame`
mean 80k over 1200 frames of the attract demo from frame 1200 (median 70k, 90% under 102k, 99% under 154k, baking spikes aside; the
Blitter's own cycles, 8k, come on top), with the generated sprite routines (a part takes about 1000 CPU cycles; the sprite pass is
about a fifth of the frame, the characters of the HUD and the scroll steps are most of the rest).  Measured in
Hatari with `COUNTERS.BIN` (before the generated sprite routines, with the table driven sprite code; not measured again with play, the
keys of the automated run did not register - a 3000 VBL attract run now: 2570 Z80 ticks, 2547 renders, the 6 s boot included): 1501 VBLs of attract mode (including the 6 s boot) 43 fps, 3500 VBLs with a coin, start and play 38 fps
(the game ticks once per drawn frame: 64% of the arcade's 59.6 Hz).  So about 40 of 50 frames a second so far; the busy frames are
the scroll steps with many character chunks, many sprites and the first use of a tile / sprite / colour (baking is 4-12k cycles).

## Not done

Sound; the flip screen (cocktail / DIP switch); the service mode (code in ROM bank 2); the arcade's wrap around of sprites at the raw
256 pixel edges (they spill into the black margins instead of being clipped, entirely outside parts are not drawn); a palette per
scanline band (the HUD's colours are quantized with the playfield's); real hardware (only Hatari was used).  Ideas for speed: native
replacements for the kernel's hot routines, characters of the HUD rows drawn only when they change (static bands), pre-baked tiles for the
common colour codes.

## Translator speed (2026-10-08)

`alt_af="upper"` (A' in d0's upper bits, F' in d6's upper word: `ex af,af'` is two swaps, a3 is free for `ret`), not
the whole `z80x.FAST`: the kernel saves tasks' registers and `scan_native` / the window reads use a0-a3 as the
alternate registers.  `scan_native` clears F with `clr.w d6` (a `moveq` would clear F').  `gen.py` goes through
`translate.compile_code` (precise flag liveness over calls; the tasks started with `jp (hl)` and the hooks keep their
exact flags).  `engine/xprof.py 1942` (ticks 1100-1500): translated code 28.1k -> 24.3k cycles a tick (1.16x).  The
rest is spread thin: `ret`, `ldir` (by longs already), `push`/`pop af` around calls, `bit n,(ix+d)` with the exact S.
Tests: `logic_test.py 6000`, `sprite_test.py`, `render_test.py seq 200 1 1200` pass; Hatari runs the attract mode.
