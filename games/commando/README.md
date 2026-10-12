# Commando (World) for Atari STE

![Commando on the STE (Hatari)](docs/screenshot.png)

The main Z80 program is statically translated to 68000 code and runs with keyboard
and joystick input on an unexpanded 8 MHz, 4 MB Atari STE. Graphics use a fixed
16-colour Oklab palette. The sound effects and the music play on the STE's YM2149 (see "Sound effects" and "Music").

    python3 port.py build commando
    python3 port.py run commando
    python3 port.py test commando
    python3 port.py mame commando

The program is `run/commando/COMMANDO.PRG`; the main CPU ROM is embedded in it.
Controls: **5** inserts a coin, **1** starts, **arrows** move, **Space/Ctrl** fire,
**Alt** throws a grenade, and **Esc** exits. Joystick port 1 also controls player 1.
Wait for startup before inserting a coin. Player 2 uses joystick port 0; **6**
inserts its coin and **2** starts a two-player game.
Jaguar pad / PowerPad (STE enhanced ports, `docs/architecture.md` "Input"): pad A player 1, pad B player 2, the D-pad moves, **A** fire, **B** grenade, **Option** coin, **Pause** start, keypad **1/2** start, **5/6** coin, **\*** + **#** quit.

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
* The music player matches its model tick for tick; the converted main theme matches MAME's audio in pitch and time
  (see "Music").

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

## Restores without divu (2026-10-09, later)

`restore_damage` takes the lines a piece from `piece_lines` (BLIT_PIECE / the words a line, 1-16 words) and calls
`blit_go_lines`; `blit_go`'s `divu` cost 9.5k cycles a frame over ~68 restores.  `perf_test.py 2500 900` (CPU +
Blitter, Musashi): a frame 185.8k -> 182.0k.  `render_test.py 300 seq`, `20 scroll`, `4 edges`: exact.  Hatari
`bench.sh`: 56.4 ticks (95%), 27.2 frames a second, no late border events (the run-to-run noise is larger than 2%).
What is left is spread thin: the sprite pass ~750 cycles of set-up a sprite, the characters ~610 a cell (8 rows of
`movep.l` read-modify-write; only 10 of 248 rows a frame are blank and 17 opaque), the restores' Blitter time ~36k,
the translated code flat (the largest form, `ret`, 10%).

## Sound effects (2026-10-10)

The sound board (`tools/sound.py`, from MAME capcom/commando.cpp): a Z80 at 3 MHz, latch at 6000 (the main CPU's
C800), two YM2203, four IRQs a frame from the scanline PROM.  Its driver keeps the two kinds of sound apart: the
music (commands $20-$2C, 13 tunes) uses only the six FM channels, the effects (commands $02-$1B) only the SSG
(square waves and noise, 3 channels of one chip each).  The STE has no FM, and the music as samples (the Donkey Kong
way) does not fit: the program uses ~3.95 of the 4 MB.  The effects map onto the STE's YM2149; the music became square
waves later (see "Music").

Translating the driver would cost ~3,800 Z80 instructions a frame (its IRQ handler; the effects alone ~2,700), so the
effects are register streams (`tools/sound_sfx.py`) played by `src/sfx.s`, in the driver's own scheme (audio ROM):
per chip four slots, only the highest active one is stepped (0537 / 0564) and output (0955 / 0A27); a command
(re)starts its effect in its slot (092E), command 0 / $1C-$1F clear all (00E6).  An effect's output after n steps
depends only on n and on the IRQ counter's phase (05F8: part of the work every 4th IRQ), so each effect is recorded
alone in the four phases (same length and loop in all; phases 1-3 as exceptions to phase 0): 41.5 KB
(`build.py --sound` records them again).  The SSG periods are scaled by 8/3: the driver sets the prescaler to 3 at
boot (0064: registers $2D then $2E; MAME ymfm `ym2203::write`), an SSG clock of 750 kHz; the STE's YM2149 runs at
2 MHz (derived, not yet measured against MAME's output).  Noise periods above 11 clamp at 31 (5 bits): the lowest
noises come out higher.

The STE plays one chip: the one whose shown effect started last (the arcade has 2 x 3 channels; both chips' effects
sound together in ~2% of the frames of the game run).  The four IRQs of an arcade tick run at the tick's start
(`.deliver`), with the latch as the tick before left it, and the YM gets the state after the fourth: a 60 Hz update
of the arcade's 240 (sweeps move in steps of four).  No interrupt handler of the port touches the YM, so its writes
are not masked (masking them made border events late).

Checks: `sound_sfx.py check 3000`: the encoded data through the decoder against the driver, IRQ by IRQ over 3000
frames of the game: 509 of 23812 chip outputs differ, all after an effect resumed from a pause (the quiet tail of
$06, at volume 1); `sfx_test.py 3000` (in `port.py test`): the 68000 player against that decoder, 0 of 23809
differ.  `logic_test.py 3000` and the render tests pass.  Hatari `bench.sh`: 55.6 ticks (93%), 27.2 frames a second,
no late border events.

## Music (2026-10-11)

The 13 tunes (commands $20-$2C) are FM: six channels on the two YM2203.  They play as square waves on the YM2149,
recorded per FM channel by `tools/sound_music.py` and played by `src/music.s` (its `Player`, `Channel`, `Mixer` and
`combine` are the 68000 code in Python, step for step).

The driver (audio ROM): a tune command clears its slot's six channels and loads them (01F7 / 0200 / 0209, then 0224);
$2D / $2E stop the music (0101).  Four slots of six channels, $4100-$4400 (32 bytes a channel); the IRQ (02B3) steps
only the highest slot whose first channel is active, so a jingle ($20 the start, $2B a death, $22 ...) pauses the main
theme ($21, the lowest slot), which resumes when it ends.  Slot channel n is FM channel n % 3 of chip n // 3.

Recording: each tune alone, from the boot, the driver's four IRQs of a tick run one after the other to their end, as
the STE runs them.  (The arcade loses an IRQ when a handler runs long, a tune's load for one: that shifts the IRQ
counter's parity, which a channel with the double-speed flag (ix+31, 02F6) depends on.  Recorded with the arcade's
timing, $28 did not repeat in 40,000 ticks and $21 only after 6,920.)  The register writes go through
`engine/opn.py`, the YM2203's envelope generator after MAME's ymfm (carriers only; 64 units = 6 dB): per tick and
channel the pitch of the carriers (the lowest within 12 dB of the loudest: their multipliers differ) as a period of
the 2 MHz YM2149, and their mean loudness over the four quarters of the tick as a volume (3 dB a step; a carrier at
full level is 14: ymfm peaks an FM carrier like an SSG square at 15, a sine sounds 3 dB below the square).  The FM
clock: 1.5 MHz / 36 (the prescaler 3 the driver selects, 0064), so Hz = fnum * 2^(block-1) * 41667 / 2^20.

Each channel loops on its own: its 32 bytes (and its output) repeat, and keep repeating with that period for a period
more (at least 600 ticks): a short repeat alone can part again (the bytes are not all of the state).  The loops: $21
1,728 ticks, $23 384, $24 864 from 25, $28 2,304 (two channels 9,217), $2C 864 from 193; the others end, and their
notes' release is recorded as a tail (up to 180 ticks), played while no other tune plays.  The loop seams differ from
the following ticks in 0-2% of the ticks (the envelopes' state at the seam).

The STE's form (34 KB): per channel a byte stream, a tick a step: hold n + 1 ticks, a volume, a volume - 1 with a
hold, a period (no tick), the end (the loop or silence).  `src/music.s`, after the effects' four IRQs of the tick: the
latch starts or stops slots, the highest slot that plays steps its six channels (else the highest tail), and
`mus_mix` builds the YM's registers: the effect keeps the YM channels it sounds on (a volume, the tone or the noise
on); the loudest music channels take the others (key volume * 2, +1 for a channel that played the tick before, the
lowest channel of a tie), each on the YM channel it had if it is free.  About 3.5k cycles a tick (Musashi: the tick
1.4k, the mix 2.2k).  The program leaves about 34 KB free from the desktop (`tools/memfree.sh`).

Checks: `sound_music.py check`: the encoded streams through the decoder against the recording (183,733 channel ticks,
0 differ).  `music_test.py 20000` (in `port.py test`): the 68000 player (`mus_tick`, `mus_mix`) against the Python
model, with random tunes, stops and effects (pauses, resumes, tails, loops, effect channels): 0 of 20,000 ticks
differ.  Against MAME 0.289's own audio (the latch poked to $21 at frame 300, `-wavwrite`): the semitone spectra of
the first 50 s correlate 0.94 at the same pitch and time (0.2 a semitone off, 0.4 an octave off), with no tempo drift.
Hatari (`--sound 44100 --avirecord true`, coin and start): its audio against the model's rendering of the start
jingle 0.955.  `sound_music.py wav XX` renders a tune through the player (`build/commando/music_XX.wav`).
Hatari `bench.sh`: 55.1 game ticks (92%) and 25.0 frames a second (before: 55.6 and 27.2; the scripted run differs
with any timing change, the player's cost is ~2.4% of the CPU).

## Foreground damage batching (2026-10-11)

An 8-pixel character row now adds one damage rectangle instead of four 2-line rectangles. Restoration still uses
the shared short HOG passes. The existing sprites already use reordered source data; whole sprites and guards
are unchanged. A damage-bitmap union prototype cost more cycles and was discarded.

On `perf_test.py 1000 900`, the same 100 gameplay ticks: render CPU + Blitter mean 233,717 → 218,556 cycles
(6.5% less), logic mean 38,889 in both builds. Masked destination reads are now included in the simulator.
The pinned 8 MHz/4 MB STE Hatari, `DEBUG=1 AUTOPLAY=1 FRAMES=6000`, measured 24.1 → 26.0 pictures/s and
54.8 → 55.2 game ticks/s. These are whole-run averages, not a guarantee that every scene stays above 25 fps.
Both builds reported zero late border events. The final renderer matches 300 consecutive reference frames
(700–999) pixel for pixel. Normal builds retain unlimited play.

## Sprites clipped at the left and right edges (2026-10-12)

The window's left and right edges lie on chunk boundaries (GAME_X = 24 bytes, 224 = 14 chunks), so a sprite across
one (x -15 .. -1 or 209 .. 223, always shifted) now draws only its inner word, as 1943's `clip_part`: right edge the
first word under END1, left edge the second word with FXSR, source Y increment 0 and the stream's END3 mask as END1;
one word a line, the rows from `spr_plan`.  Its damage is that one chunk, so no sprite touches the side bands any
more.  The top and bottom stay whole sprites in the guard lines.  `clear_margins` stays: it is there for the tiles
(a horizontal scroll that is no multiple of 16, and the full redraws).

`draw_sprites`' x test became `beq` (hidden) / `sub.b #16` / `cmp.b #208` / `bhi.s` to `.edge` (hidden on the
right, or across an edge): the same cycles as the old cull test plus `sub.w #16`.  `.edge` repeats the loop's set-up
off the hot path.  A first try with one more compare per drawn sprite cost +0.46% a frame (~50 sprites a frame);
one that sent the hidden sprites through the edge test cost +0.6%.

`perf_test.py`, same inputs, CPU + Blitter a frame, exact (profile mode, one instruction a step): ticks 900-999
217,657 -> 217,686 (no sprite at an edge: +29, the entry `bra.s`); ticks 900-2499 183,204 -> 183,270 (+0.04%;
`clip_part` 339 and `sprite_edge` 28 a frame, against fewer generated-routine and restore cycles).  The default
mode (2000-cycle chunks, up to one chunk's overshoot a frame): 218,556 -> 218,688 and 184,154 -> 184,212.  Logic:
38,889 and 45,204 in both builds.  Hatari `bench.sh` (pinned build, 6000 VBLs): 55.2 -> 55.5 game ticks a second,
26.0 -> 26.3 frames drawn a second (run-to-run noise), no late border events in either.

Tests: `tools/sprite_test.py` (new, in `port.py test`): 4 sprites with transparent holes, all 16 shifts at both
edges, plain and across a 64 KB boundary (the generic path): 248 cases, each against the same sprite drawn whole
in the middle; the bands unchanged and the damage inside the window.  It fails on the old code (the whole sprite
in the band).  `render_test.py 4 edges` now expects the clipped left/right sprites (top and bottom whole);
`render_test.py 300 seq` and `20 scroll` exact; `logic_test.py 3000`, `reference_test.py`, `sfx_test.py 1000`,
`music_test.py 20000` pass.
