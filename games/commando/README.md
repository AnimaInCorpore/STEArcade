# Commando (World) for Atari STE

The main Z80 program is statically translated to 68000 code and runs with keyboard
and joystick input on an unexpanded 8 MHz, 4 MB Atari STE. Graphics use a fixed
16-colour Oklab palette. The sound CPU and YM2203 output are omitted.

    python3 port.py build commando
    python3 port.py run commando
    python3 port.py test commando
    python3 port.py mame commando

The program is `run/commando/COMMANDO.PRG`; the main CPU ROM is embedded in it.
Controls: **5** inserts a coin, **1** starts, **arrows** move, **Space/Ctrl** fire,
**Alt** throws a grenade, and **Esc** exits. Joystick port 1 also controls player 1.
Wait for startup before inserting a coin. Player 2 uses joystick port 0; **6**
inserts its coin and **2** starts a two-player game.

The Python reference has separate encrypted operand/data and decrypted opcode
buses, including ordinary CB/ED prefixes and the data-bus indexed-CB tail. The
MAME IRQ PROM supplies RST 08 and RST 10. The runtime delivers both interrupts at
`8001` when the foreground work queue at `ED82` is empty. It preserves the Z80
and native task stacks and drains queued work before drawing. The STE schedules
six arcade ticks per five VBLs, skips up to two pictures to catch up, and caps
pending ticks (the speed is measured below).

`C806` latches all 96 sprites explicitly. The three display buffers are virtual
screens scrolled by the video address, following stedaimakaimura: buffer lines
`l` and `l+320` always hold the same background, so the 256 shown lines (plus 16
guard lines above and below for whole sprites) are contiguous wherever the
window is, without a Timer B wrap (Timer A/B remove the borders). Only the tile
rows that scroll into the 288-line band and tiles whose RAM changed (tile RAM
compared with a copy as longs) are drawn, into every buffer; the twin period is
320, not 288, because whole tiles at the band's edges overhang by up to 15 lines
into unused slots. What sprites and characters covered in a buffer is a damage
list of rectangles, copied back from the twin lines (short HOG Blitter bursts)
the next time that buffer is drawn. There is no clean map and no per-frame
background copy. Characters are a list of the visible, non-blank cells, rebuilt
only when the character RAM changes, drawn with `movep.l` (a keep mask and the
four plane bytes per row). Whole sprites draw into the guard lines and margin
chunks using reordered source rows, shared mask groups and baked shift streams,
with a full-address path for 64 KB crossings. A horizontal scroll that is not a
multiple of 16 (never seen in play) clears the margin chunks; a new horizontal
scroll or a jump of more than 200 lines draws the band whole. Foreground
transparency is pen 3; sprite transparency is pen 15. Flip-screen/cocktail mode is
not exposed by the STE runtime; its default DIP setting is upright.

Speed (2026-10-08): `tools/bench.sh` (DEBUG + AUTOPLAY build, 6000 VBLs in Hatari,
boot included) measured 52.2 game ticks and 21.5 drawn frames a second (the
arcade ticks at 59.6); before this renderer it was 23.6 ticks and 7.9 frames.
`tools/perf_test.py [ticks] [first] [profile]` gives the Musashi cycles of a tick
and of a frame and a profile by routine (one play scene, 54 visible sprites):
a frame went from 962k cycles (background scan 329k, character scan 208k, full
screen clear 151k) to 255k; a tick of the logic is about 36k. What is left is
real work: restoring the damage (46k), sprites (~120k with their streams) and
characters (40k).

2026-10-09: the tile and character RAM are compared with their copies only after
a translated writer ran: `gen.BG_WRITERS` / `FG_WRITERS` (10 and 31 instructions,
from the coverage's write sites) emit `st bg_written` / `st fg_written`, and 128
bytes of each are compared a frame in case a writer is missing (`logic_test.py`
checks that every change of the two RAMs comes with its flag). A frame went from
246k to 213k Musashi cycles; `tools/bench.sh`: 55.1 game ticks (93% of the
arcade) and 27.1 drawn frames a second.

2026-10-09, sprite pass: the sprite loop keeps its entry pointer in a register,
rejects the hidden entries (x = 0) first, sets the Blitter registers no sprite
routine changes once a frame, and does the cache lookup (get_object's hit path),
the destination and the damage inline; a shape that is blank at its shift is
skipped before the lookup.
`perf_test.py 2500 900` (play): a frame 189k -> 161k Musashi cycles.
`tools/bench.ps1` (the Windows counterpart of `bench.sh`, same build and counters):
26.5 -> 30.1 drawn frames and 55.4 -> 56.9 game ticks a second (the 6000 VBLs
include the boot; the scripted game unfolds differently with any timing change,
so compare runs of one build or use `perf_test.py`). A Hatari profile in play (VBL 4900-5200) puts the translated
Z80 code at 31% of the CPU, the sprite pass (loop, generated routines, 64 KB
parts) at 34%, the damage restore at 14% (nearly all of it Blitter time) and the
characters at 8%. Damage cut to each shape's opaque rows and chunks saved as much
Blitter time as the lookup cost the CPU, and was left out.

2026-10-09, borders without waiting (`engine/rt/borders.s`, shared by the Blitter
ports): a HOG blit holds the CPU and its interrupts, and the old guards made every
blit near the VBL or a timer event wait. Now each event comes early and syncs itself
to the video: Timer B fires 2 lines before its line (palette on, bottom border,
palette off) and polls its counter down to that line's end; the bottom border event
starts Timer A for the next frame's top border (a line-exact point, so a late VBL no
longer moves it), which fires ~3 lines early and picks its HBL by reading Timer A.
No blit waits; a restore rectangle longer than 32 words runs in pieces (`blit_go`).
The palette switches are line-exact now. The DEBUG build counts events that started
too late; `bench.ps1` prints them (0 in 6000 VBLs) and 55.7 game ticks, 27.3 drawn
frames a second.

Validation:

* All 22 ROM files pass the checked-in MAME CRC32/SHA1 manifest.
* The reference renderer and palette match actual MAME screenshots exactly at
  frames 100, 700, 1500 and 2500.
* Translation matches all work/video RAM, sprite latches and scroll/control
  registers for 12,000 reference frames with attract mode, coin/start and play.
* Whole-sprite guard checks pass at all four edges, including every opaque
  pixel outside the game window.
* Consecutive rendered frames (incremental scrolling, damage restore, character
  list) and scroll/wrap probes (full redraws) match reference pixels
  exactly through the STE colour map.
* 48,064 generated sprite/shift pairs pass the independent Blitter model.
* The pinned Hatari build runs the port with 4 MB RAM through coin/start, movement,
  fire, deaths and player restarts.
* Shared Donkey Kong/Galaga sprite regressions pass after the FXSR model fix.

`docs/coverage.json` retains baseline instruction and sprite-latch coverage for
reproducible clean builds. `port.py cover commando` expands it with seeded
attract/play runs in `build/commando/`; it does not overwrite the baseline.
Recursive discovery also translates unobserved branches. Unsupported speculative
code entries remain explicit traps; any unsupported instruction actually seen
by coverage stops the build. No unknown opcode becomes a silent NOP.

`python3 port.py build commando --assets` regenerates the palette, masks and sprite
streams. The generator reuses the existing 1942 Oklab and sprite-code tools.
`--sim` produces `run/commando_sim/COMMANDO.PRG`; `--debug` enables diagnostic
files, `--frames N` exits after N VBLs, and `-D AUTOPLAY=1` supplies coin/start,
movement and fire according to the arcade tick counter for Hatari checks.

## Translator speed (2026-10-09)

`gen.py` goes through `translate.compile_code` with `z80x.FAST` (A' F' BC' DE' HL' in the upper words of d0-d3 / d6,
IY in a2: the runtime saves all registers in its hooks, nothing else needed).  The joins are the real entries (reset,
the interrupts, the idle hook, the targets of the `RST 30` word tables, which `discover` now records); before, every pc
the coverage saw was a join, which switched the CCR analysis, the precise returns and the merges off.  Merged pcs get
z80_badpc in `z80_entries`.  `engine/xprof.py commando` (ticks 600-1000, attract): translated code 8.4k -> 7.0k cycles a
tick (1.20x).  `logic_test.py 3000`: exact.
