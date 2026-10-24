# Black Tiger (Capcom, 1987)

![Black Tiger on the STE (Hatari)](docs/screenshot.png)

STE port of MAME set `blktiger`, with a bank-aware translation of the unmodified
main Z80 and an i8751 interpreter running the dumped protection firmware.
Requires a 4 MB STE. The sound driver's effects and music play on the YM2149
(see "Sound").

```sh
python port.py build blktiger         # verify ROMs, build assets and BLKTIGER.PRG
python port.py run blktiger           # pinned F030Arcade Hatari, STE / 4 MB / TOS 2.06
python port.py test blktiger          # firmware, CPU lockstep and renderer checks
python port.py mame blktiger 1500     # reference bitmap against MAME state
python port.py cover blktiger 1       # optional additional bank-aware coverage
games/blktiger/tools/perf_test.py     # Musashi: a tick's and a frame's cycles (profile, logic, frames)
games/blktiger/tools/bench.sh         # Hatari: DEBUG + AUTOPLAY build, ticks and frames a second
games/blktiger/tools/sprite_test.py   # edge sprites: the whole hardware window, side bands included
python games/blktiger/ref/palette_fit.py   # refit the fixed palette (docs/palette.json), its error against the one before
```

Supply `assets/roms/blktiger.zip`. Preparation checks all 20 ROMs against the
size, CRC32 and SHA1 manifest before extracting or constructing regions. Build
uses the repository Python environment, numpy, Pillow, vasm and vlink. MAME is
only needed for `mame`; its executable can be overridden with `MAME`.
The executable is `run/blktiger/BLKTIGER.PRG`; its ROMs and graphics are embedded.
Committed instruction roots and window-guard sites (`docs/`) make a fresh build independent of coverage files.

Controls: **5/6** insert coins, **1/2** start, **arrow keys** move,
**Space/Ctrl** attack, **Alt** jumps, **Escape** returns to the desktop.
Joystick fire attacks; use Alt for jump (joystick port 1 player 1, port 0 player 2).
Jaguar pad / PowerPad (STE enhanced ports, `docs/architecture.md` "Input"): pad A player 1, pad B player 2, the D-pad moves, **A** attack, **B** jump, **Option** coin, **Pause** start, keypad **1/2** start, **5/6** coin, **\*** + **#** quit.
For scripted Hatari events, use ST
scancodes for special keys: Right `77`, Space `57`, Alt `56`, Escape `01`.

## Display and timing

Two 768 by 544 planar buffers (the display rings) and a third, clean one hold
the background as virtual screens: the camera moves the Shifter address
(coarse) and `$ffff8265` (fine, with the extra-fetch correction in
`$ffff820f`); the larger buffers avoid a scanout wrap interrupt sharing Timer B.
Sprites clip at the full band words; at fine picture edges and in vertical guards
they draw whole, as described below. Per frame
(`render.s`):

* **The clean screen** holds the 17 by 15 cells the view can touch. Only the
  cells scrolled in are checked against their cache key; a full check of the
  window comes with a new 256-pixel page, a mode (flip, layout, background
  off), map or palette change. Other physical instances are checked and filled
  when they enter the window, rather than drawing up to eight offscreen twins
  speculatively. `-D BT_EAGER_TWINS=1` retains the old path for comparisons.
  See [the scrolling measurements](../../docs/virtual-scroll-performance.md).
* **Each ring** keeps a damage list of cells (those the clean screen changed,
  margin cells that must lose their black) and a list of rectangles (what its
  sprites covered, and its text runs once the text is redone: a run's 8 lines,
  a sprite's 16). Only those are copied from the clean screen, by the Blitter
  in short HOG pieces; a damage cell in a margin column gets its black bits
  with the copy (zeroes, or the clean screen AND a halftone mask).
* **Front pens** (the background's priority half) are in the clean tiles; they
  are drawn again only over the cells sprites touched (a mask per cell).
* **The text layer** is a list of runs (characters on one row, gaps of up to
  three blanks), composed when the text RAM or the flip changes and drawn like
  stefastbobs2's bobs (`text_run_pieces`, `character_pass`): each line's opaque
  words in pieces of two (or one), a copy pass a piece (HOP 2, OP 3) with the
  opaque pixels as end masks and all four planes in the pass, the planes stored
  in pass order, the shift as the pass's skew (no AND + OR passes). A ring
  keeps its text while the scroll and the text are the same; else the runs'
  rectangles are restored and the text drawn whole.
* **The black side margins** (32 pixels each side of the 320-pixel window) are
  a mask per cell and ring, changed only where the window moved; the two word
  columns the fine scroll masks in part are copied whole by the Blitter (the
  clean screen AND the visible bits) before drawing when the window moved. Whole new sprites may spill
  into the side bands; no mask is applied after drawing.
* **Change detection**: the translated writers of the background RAM set
  `bg_dirty` (`gen.BG_WRITERS`, from coverage) and the block copies to the
  palette note their ranges before they run (`pal_note`, `gen.PAL_WRITERS`:
  only those blocks of 128 entries are compared and mapped again); 256 / 128
  bytes a frame are compared in case a writer is missing (a DEBUG build counts
  what that finds). The text RAM (about 80 writers) is compared each frame.
  A tile the game changes (an animation) is drawn where it shows only; its
  twins are found stale when the page jumps there.

Whole sprites use precomputed shifted masks and equal-mask row groups, including
mirrored variants. Tiles, sprites and characters are baked into planes with a
byte table a colour (two pixels a lookup, `movep` for the plane bytes; 32 tables
cached). Background split priority and viewport-anchored text follow
MAME. A fixed 16-colour STE palette approximates the arcade palette; renderer
comparisons use that same colour mapping.

**The palette** is fixed: black and 15 colours fitted by a weighted k-means in
Oklab (`ref/palette_fit.py`, Bubble Bobble's method) to the reference's
pictures of the logic test's script and of each stage 0-7 (cover.py's cheats),
each set's colour histogram normalised, the colours snapped to ones that occur
(4 bits a channel, exact on the STE). Every palette word maps to the nearest of
them in Oklab (`tools/assets.py`: a 4096-entry table at build time). A palette
change remaps the pens of the colours it touched; their tiles and sprites are
baked again unless one of the colour's last eight mappings returns (flashes and
cycles find their bakes in the caches). Renderer comparisons use that same
colour mapping.

| palette | error per channel (0-255), mean of the 9 sets | exact pixels | worst set |
|---|---|---|---|
| before: median cut of the script's colours, RGB-weighted map | 17.2 | 27.7% | 38.8 (stage 5) |
| now | 11.6 | 42.7% | 17.9 (stage 7) |
| square-rooted weights (as Bubble Bobble) | 15.5 | 35.4% | 40.4 |
| 13 colours + 2 lent to flashing entries | 12.4 | 40.3% | 21.1 |

Only the script set (the old fit's own data) is a little worse (9.9 -> 10.8).

Lending colours does not pay here: the frequent changes are the fades and a
four-entry ramp of the player's colours (every few hundred frames). The
palette's choice costs nothing at run time.

The cooperative task scheduler yields at the game's idle loop. Native VBLs
queue six game ticks per five 50 Hz fields; drawing is skipped while ticks are
pending, at most `MAX_SKIPS` (4) frames in a row: the game first, then the frames.

## Memory (2026-10-10)

text + data + BSS = 3,484,734 bytes (`build/blktiger/blktiger.map`: text 297,744,
data 2,089,628, BSS 1,097,362); there is no Malloc, the screens are BSS.  It was
4,023,518, more than GEMDOS leaves on a 4 MB STE with a hard disk driver,
accessories and TOS 1.62 (TOS 2.06 without AUTO programs: 4,145,998).

`MAX_SKIPS=2` gave 33.5 ticks/s and 14.0 frames/s. The logic is the larger
part: the bank switches of the background RAM (4 KB copied out and in, the game
reads its map for collisions) and the guarded window reads. `perf_test.py`
takes `profile` (render_frame by routine; `PERF_CPU=1` without the Blitter's
bus cycles), `logic [regions]` (the tick by routine or Z80 page), `frames` (a
frame's cost and the renderer's DEBUG counters: bakes, cells restored, tiles
drawn, sprites, text runs, margin cells, with `build.py --sim --debug`).
`render_test.py --consecutive --walk` draws every frame (the incremental paths)
and checks the black margins too.

### Renderer work of 2026-10-11

In play the game logic takes about 80k Musashi cycles a tick (108k in Hatari:
78% of the STE at 60 ticks a second), so the frames get what is left. The
renderer was cut where the per-frame counters (`perf_test.py frames`) showed
the work: a scrolling play frame restored 118 cells a frame (52 under the text,
34 under sprites, 35 margin cells whose partial mask moved, 34 new tiles and
their twins), redrew 12.7 text runs and baked 2.5 sprites. Now sprites and text
runs are restored as rectangles, the part-masked margin columns as two Blitter
passes, damage cells in margin columns with their mask, every copy by the
Blitter; a changed tile is not drawn to its twins; the palette is compared in
the blocks the game's block copies touched; `bake_pixels` uses `movep`.
A scrolling play frame (`PERF_EVERY=3 perf_test.py 1600 1430`): 552k -> 437k
Musashi cycles (320k CPU + 118k Blitter bus); a frame of the start screen
251k -> 210k. The Blitter's bus time and the half-line pieces are now a quarter
of a frame: the restores and the text's eight passes a run are bus bound.

### Memory work of 2026-10-10 (merged 2026-10-15)

* **Dispatch tables** (`gen.py`, `bt_dispatch`): a word per Z80 address,
  (the entry - the region's base) / 2, built as data: the fixed code in two
  regions (below and from $4000, 64 KB, a4) and each bank's code (32 KB, its
  base in the long before the table; `g_wdispatch` 0 for a bank without code).
  Before: 640 KB of long tables in BSS (an invalid bank's too), filled at start
  from 113 KB of entry lists.  A region's base is a label before its first
  line, its `z80_badpc` stub follows an unconditional jump inside it; vasm
  rejects an entry out of range.  About 24 cycles more a dispatch (16 a tick).
* **The fixed ROM** is assembled into the Z80 image (`g_block`, data) instead
  of copied there (32 KB).
* **Sprite row orders**: a sprite and its mirror image share theirs (32 KB).

The largest items then: the three 768 by 544 screens (612 KB), the graphics
(tiles, sprites 256 KB each, characters 64 KB), the ROM banks (256 KB), the
shifted sprite masks (250 KB), the caches (tiles 96 KB, sprites 64 KB, byte
tables 64 KB; `perf_test.py 4000 300 frames` bakes the same with half the
tile or sprite entries, but later stages were not measured).

## Validation and limitations

The firmware test exercises all 256 commands. CPU checks compare work RAM,
saved task stacks, background banks, sprite buffers, scroll and control latches
against the cooperative reference. Renderer checks cover both map layouts,
normal/flipped video, all 16 fine-scroll positions, page-boundary crossings,
and whole sprites at viewport edges. The independent MAME comparison validates
reference pixels using MAME's actual memory and saved video state; it does not
validate the reference CPU's timing.

The audio Z80 runs only in `tools/sound.py` (its output recorded, see "Sound"). MCU transactions are synchronous rather
than cycle accurate. The watchdog, coin counters and board timing are not
fully emulated. Instruction discovery combines committed coverage and static
control flow, including allocator return-address adjustment; a missed dynamic
target produces `CRASH.TXT` instead of silently continuing.

See [hardware notes](docs/hardware-notes.md) for the F030Arcade MAME sources and
stedaimakaimura scrolling references.

## Sound (2026-10-11)

The sound board (MAME `capcom/blktiger.cpp`): a Z80 at 3.58 MHz, two YM2203 at 3.58 MHz (the default prescaler: FM
at 3.58 MHz / 72, the SSG at / 4), interrupts from the first chip's timers: timer A (~250 Hz) runs the effects and
the music, timer B (~259 Hz) reads the latch.  A later Capcom driver than Commando's (`tools/sound.py` has the
details): commands through a table with a header byte each; effects one slot a chip with a priority (byte 31, cleared
when the effect ends), the SSG only; tunes six FM channels in a main slot (C100) and a backup (C300): a tune of the
main one's priority replaces it, a higher one moves it to the backup, a lower one goes to the backup unless that holds
a higher one; when the main tune ends the backup takes over, and a main tune with header bit 6 lets the backup step on
silently.  `tools/sound.py` models the board (the timers, the busy flag) and records with `engine/capsnd.py`'s forms:

* 40 effects, each alone in the four phases of C022 (12 values a driver step: the SSG registers and the priority).
  $14 repeats 564 steps for 144 s and $3C 68 steps 255 times: one period is kept with a loop and the total
  (`compact`, 250 KB less).
* 25 tunes, each channel alone through `engine/opn.py` (a YM2149 period and volume a driver step), with its loop;
  a channel at 30 Hz or lower (FM without a frequency, the carriers' level left from the tune before) counts as silent.

`src/sound.s` plays them in the VBL, five driver steps a VBL (250 Hz), in the driver's scheme (`Player` in
`tools/sound.py` is that code in Python).  The tunes would take 158 KB: they are packed (`engine/lz.py`, a
byte-aligned LZ77, 57 KB) and unpacked when they start into one of two 17.7 KB buffers (the main and the backup
slot); the unpacking runs in the idle hook (`bt_snd_load`, up to 0.5 M cycles), not in the VBL: a tune starts when it
is unpacked.  Data 91 KB, the buffers 35 KB; the player ~9,500 cycles a VBL (Musashi, random commands).  `tools/bench.sh` (DEBUG + AUTOPLAY, 6000 VBLs): 51.5 game ticks (86%) and 21.2 frames a
second; without the sound (`EXTRA="-D NOSOUND=1"`) 52.8 and 22.9 (the renderer work of 2026-10-09 and later
made the 65% / 12 frames above out of date).  With the renderer work of 2026-10-11 (see "Speed"): 54.0 ticks
(90%) and 23.8 frames a second.

Memory (2026-10-15): 3,972,764 bytes in 0.3 -> 3,546,696, 504 KB left from the desktop (4,061,212 on a 4 MB STE with
TOS 2.06; a tester's Mega STE with a hard disk driver and accessories had 3,831,554: TOS refused to start 0.3).  The
memory work of 2026-10-10 ("Memory work of 2026-10-10" above: word dispatch tables built as data, the fixed ROM in
place, shared sprite row orders; its fixed palette fit came with it) was only merged on 2026-10-15 (0.3 was built
without it).  Musashi (`perf_test.py`): logic 37,414 -> 37,805 cycles a tick, frames unchanged (168.6k ->
168.7k), 38.8 -> 38.7 ticks a second.

Checks: `sound.py check 120` runs the real driver beside the model, a step at a time: the effects 0 of 59,958
chip-steps differ audibly (random commands and the game's own); the music 794 of 102,068 sounding channel-steps differ
in the game's commands, all by one volume step (an envelope carried over from the note before), 1-3% with random
commands (also tunes that start on another tune's chip state).  `sound_test.py` (in `port.py test`): the 68000 player
against the model, 0 of 6,000 VBLs differ.  Hatari: coin, start and play have music and effects (the attract mode's first
command comes at game tick 1509, its demo play: the first ~40 s on the STE are silent, as the arcade's first 25).  `build.py --sound` records again (~6 min).

## Translator speed (2026-10-09)

`gen.py` goes through `translate.compile_code` with `z80x.FAST`; the window code is the engine's `Emitter.window_wrap`
(a0 is free with `FAST`: no save around each access, and no base load where the window check sets it), `ldir` the
engine's, the jump table targets of `discover` are joins, merged pcs get z80_badpc in the entry tables, and the
return points in the window are left out of the direct returns (`direct_ok`: a stack word cannot tell the bank;
`ret_value` is the real address).  `engine/xprof.py blktiger` (ticks 600-1000, attract): translated code 15.7k -> 12.9k
cycles a tick (1.22x).  What is left is mostly the policy of guarding every indirect access as a possible window
read: the checks are a quarter of the cycles (`ld a,(hl)` 58 cycles); the coverage's window-read sites, as Bubble
Bobble uses them, would make most of them plain moves.  Tests: `logic_test.py 1600`, `logic_test.py 4000 --walk`,
`render_test.py --frames 3 --step 375 --scroll-sweep --flip-layout-sweep --sprite-edges` all match.  The first build
with the new translator did not boot: each gen's own window wrapper saved a0 in the middle of `ld (hl),c`'s stack use
(see `docs/architecture.md`, "Banked windows"); the engine's wrapper fixed it for all ports.

### Window guards at the coverage's sites (2026-10-11)

The guards are now emitted only at the indirect accesses the coverage saw reading the window or the background
bank (8000-CFFF) or writing the bank (`ref/cover.py` records the sites: seeds 1-11 with every stage, `--walk`,
`--auto`); the other 2,800 of the 5,242 indirect accesses are plain reads of the Z80 image.  The sites are kept
in `docs/window-sites.json` (a fresh build needs no coverage files; coverage files that record the sites write
it again; `BT_GUARD_ALL=1` guards every access as before).  `logic_test.py --audit` traces a Musashi run and
reports every translated instruction that touches the image of the window and the bank (`g_block` to +$4FFF),
where an unguarded access would read the wrong memory: `bt_wsites_audit_*.pkl`, which gen adds to the sites; the
1600-frame and the 4000-frame walk runs report only the eight block copies whose source is the bank's image.
The logic in play: 80.7k -> 65.3k Musashi cycles a tick (-19%), the start screen's 26.8k -> 21.7k; Hatari
(`tools/bench.sh`, DEBUG + AUTOPLAY, 6000 VBLs): 23.8 -> 26.3 frames and 54.0 -> 55.1 game ticks (92%) a second, 0 late
border events.  (Like stedaimakaimura, which runs the arcade's 68000 code as it is and
handles the few special accesses by their faulting PC: the common path pays nothing, the exceptions are enumerated.)

### Roots and block copies from F030Arcade's replays (2026-10-23)

F030Arcade's Falcon port runs this translation and replays a recorded MARP game (all eight stages) against MAME.
That replay and its PPO plays found code and accesses the coverage here never reached; both are now in this port:

- **87 roots** (`docs/translation-roots.json`): 14 handlers named by bank 5's 8-byte object tables (a hand-played
  game crashed into bank 2 `$B8C0`), object-script handlers (`00 lo hi` records in banks 0-4), and task starts
  (`ld bc,entry / call $00F6`: `$275D`, `$2778`, bank 6 `$A9E8`).  The translation: 19,273 -> 24,628 instructions,
  none unsupported.
- **Every block copy guarded** (`gen.py`: each `ldir`/`lddr` is a window site): bank 0's `ldir` at `$AC71` was not
  a coverage site and copied zeros for the 32-byte object template at `$AF06`, so the player's attack object had no
  type, timer or script (MARP game, frame 6,832).  2,426 -> 2,577 guarded sites.

`port.py test blktiger` passes; Hatari (`tools/bench.sh`): 58.0 -> 57.9 game ticks and 29.5 -> 29.3 frames a second
(noise), 2,436,385 -> 2,471,966 bytes.  Not taken over: F030Arcade's Z80 cycle budget (`CYCLES=1`), which a
recorded game needs to stay in step with MAME (without it the game's tasks finish in zero frames and the random
generator runs ahead) but which costs the STE logic time.

### MARP replay with the cycle budget (2026-10-24)

F030Arcade's budget is now a test build here (the normal build is unchanged): `tools/cycle_budget.py` and
`tools/z80_cycles.py` (MAME 0.184's Z80 tables) are taken over from F030Arcade, `gen.py` uses them with
`BT_CYCLES=1`, and `src/blktiger.s` has `cyc_poll` / `cyc_ei` under `ifd CYCLES` (the tick start is `tick_begin`,
shared by the idle hook and `cyc_poll`).  `build.py --sim --cycles` also guards every indirect access.

    venv/bin/python games/blktiger/tools/marp_replay.py fw666_blktiger_2006700_wolf184.zip --shift 1

`marp_replay.py` decodes the recording (`marp_inputs.py`, with its DIP switches: fw666 has DSW1 `$2F`, continue off,
where the port's default is `$6F`), builds `--sim --cycles -D PLAYBACK=1 -D MARP=1` (no lives kept) and plays it on
Musashi, logic only, about 8,500 ticks a second.  MARP lists the final score: a port that follows the recorded game
reaches it.  Port tick n takes the recording's frame n + 1 (`--shift 1`; shifts 0, 2, 3, 4 lose the first stage).

Result on fw666 (2,006,700 points, 240,662 frames, WolfMAME 0.184):

- Without the budget the game leaves the recording 30 frames after the start (F030Arcade's finding).
- With it the port plays the expert's game through seven of the eight stages: stage 2 at tick 7,837, stage 3 at
  15,763 ... stage 7 at 129,364, about 1.2 million points.  The 68030 forms (`STE_XCPU=68030`, F030Arcade's) give the
  same game.
- In stage 7 it leaves: from tick 162,519 the player loses a life every 7,664 ticks (the stage timer), the game ends
  in stage 8 at 1,766,650.  F030Arcade's port, the same translation, followed this game to the end against a
  WolfMAME 0.184 dump; the cause here is not found yet.

The ground truth for locating it is a WolfMAME 0.184 RAM dump (F030Arcade's `scripts/mame_inp_dump.py`, Windows
build): `marp_replay.py --out x.npz --ram first-last` saves the port's state at each idle point for that comparison.
MAME 0.289 cannot play the recording (its blktiger screen is 384 x 262 lines, 59.63 Hz, and the playback stops as
out of sync after frame 1).  `tools/marp_reference.py --mame184 --dsw1 0x2f` plays it on the reference board with
0.184's timing (100,000 cycles a frame, the interrupt from the end of frame 0): it equals the port at every idle point
to tick 16,409, then leaves (the port takes the interrupt at a block start, the reference at the instruction, and
the random generator's task then runs a different number of times); 78 frames a second.

## Text drawn like sprites (2026-10-24)

The text runs were drawn with an AND pass (the mask) and an OR pass (the pixels) per plane, eight passes over the
run's 8 lines. They are now cut once, when the run is composed, into stefastbobs2's bob pieces: per line the words
with opaque pixels, two (or one) from the left; an entry holds each piece's two mask words and its destination step,
then the pieces' planes in pass order. A frame draws a piece as one copy pass (HOP 2, OP 3; destination X increment 8,
Y count 4 = the planes, Y increment back to the next plane) whose end masks are the mask words shifted by the run's
shift; with a shift the pass covers one destination word more and reads its words with NFSR (the skew in the pass),
so the source runs on from piece to piece and nothing is shifted in advance. Two intermediate versions were measured
and dropped: pieces cut in destination words with the masks and the shifted planes prepared per run and shift in a
64 KB pool (the preparation cost 16k a scrolling picture: the timer and the score change the text every second), and
the same with only the masks prepared (the source address written per piece).

Measured on the MARP game's inputs (`PERF_PLAY=1 PERF_EVERY=3 perf_test.py 9000 1000`, 8000 ticks, Musashi CPU +
Blitter; `PERF_SEL=moved` the 768 pictures whose window moved): `character_pass` 83.7k -> 57.3k cycles a scrolling
picture (the Blitter's part 45k -> 18.5k, the CPU's 38.7k -> 38.8k), a scrolling picture 347k -> 322k, every picture
195.4k -> 185.7k (-5%). Hatari (`PLAY=1 EXTRA="--frames 30000" WAIT=640 tools/bench.sh`, the MARP inputs from
`marp_inputs.py`, 30,000 VBLs): 24.6 -> 25.5 pictures a second (98% game speed both), the median 2-second stretch
22 -> 23, stretches under 15 pictures a second 60 -> 55 of 196. `port.py test blktiger` passes (the render sweep covers
all 16 shifts).

## Whole sprites at borders (2026-10-11)

Removed the final side-band masking pass. Background restoration still prepares its margin cells before
sprites are drawn; `strip_track` records those cells for the next camera move without changing pixels.
Whole sprites/front objects remain visible wherever they enter the 320-pixel hardware window. Sprite
source rows already use the reordered mask-group method. Reference checks pass the scroll and flip/layout
sweeps, including 32 combinations of edge sprites and all fine-scroll positions. The longest HOG pass is
256 bus cycles; none share the bus.
The rebuilt 4 MB STE Hatari debug run completed 2,500 VBLs without a crash file and with zero late
border or palette events (two startup fallbacks).

## Sprites clipped at the band words (2026-10-12)

The game's edges lie at window word 2 (18) + the fine scroll, so they are group-aligned only at fine scroll 0. The
group boundaries next to them, words 1|2 and 18|19, separate the always-black band words (0, 1 and 19, 20) from the
rest. A sprite across one of them now draws only its inner word (`clip_sprite`, one word a line, as 1943's
`clip_part`: right, the first word under END1; left, the second word with FXSR and source Y increment 0, the
stream's END1/END3 registers swapped so END1 gets the second word's mask); its damage is that word column only. The
band part of words 2 and 18 still shows whole sprites (no runtime edge mask). No sprite can lie wholly in band words:
the arcade's own range (x -15..255) already culls those. The hot path adds the fine scroll to x and makes one
unsigned compare instead of the two range compares (`.edge` does the culling and the clipping out of line).

Before, a sprite's part in word 1 or 19 showed in the black band, and its rectangle's restore copied the clean
screen's background there (`sprite_test.py --whole` on the old build shows the background in word 19). Musashi
(`perf_test.py`, CPU + Blitter a frame drawn): play 1000-1600 164,658 -> 164,586 (-0.04%), with `PERF_EVERY=3`
269,392 -> 269,251, attract 400-1200 76,011 -> 76,054 (+0.06%); logic unchanged (37.4k). Hatari (`bench.sh`, 6000
VBLs): 26.5 -> 26.8 frames and 55.4 -> 55.6 ticks a second, 0 late border or palette events (two startup fallbacks).
Tests: `sprite_test.py` (4096 edge sprites in 256 frames, 1800 clipped, 172 across 64 KB, two sprites with holes,
all fine scrolls and shifts, both orientations; fails on the old build), `render_test.py --frames 3 --step 375
--scroll-sweep --flip-layout-sweep --sprite-edges`, `logic_test.py 1600`, `logic_test.py 4000 --walk`,
`reference_test.py 700`, `sound_test.py 6000`.

### The side bands black in every frame (2026-10-12)

The four band faults the clipping work found are fixed; all lay in what the earlier removal of the after-drawing
masking pass left behind, before any drawing:

1. A window step left background in band words 0, 1, 19, 20: cells entering them were never blacked.
   `strip_enter` (only when the window's word or first row moved since the ring's last frame) blacks those of the
   four columns' cells not wholly black in that ring (`applied`), 16 lines a Blitter pass, no damage list.
2. The rows: the lines of background in the left band (flipped, fine scroll 13) were cells of rows that had left
   the window with their old mask, or entered it unblacked. `strip_unmask` now restores a listed cell whose row left
   the window while it keeps black bits (any column), `strip_enter` covers rows entering.
3. `render_test.py --consecutive ... --walk` at frame 1450 (a renderer bug): `touch_cells` cleared a cell's
   `applied` when a sprite or a restore changed only some of its lines; the rest kept the word-18 mask, so after the
   window's step `strip_unmask` skipped the cell and 2-5 black columns stayed in the picture (x 240-255, word 17).
   `applied` now stays what the cell may still hold.
4. A rectangle's restore over words 0-2 or 18-20 copied the clean screen without the band. Such rectangles are
   flagged where they are made (the edge sprites' `.edge` path, text runs at the picture's sides; every rectangle
   after a window step: `rect_all`); `ring_rects`, now before the cell restores, blacks their band bits right after
   the copy (`rect_band`: zeroes under end masks, 8 or 16 lines a pass), or, for one reaching out of the window's
   rows, lists its band cells. The front pass keeps front pens out of the band (`front_band_pass`, only after an
   edge sprite).

The normal sprite path is unchanged in cost (one compare: x 16-240 from window word 2). Musashi (`perf_test.py`,
CPU + Blitter a frame drawn), the clipped build above -> now (the committed version with its after-drawing pass):
play 1000-1600 164,586 -> 168,637 (+2.5%; 170,080), `PERF_EVERY=3` 269,251 -> 278,833 (+3.6%; 279,924), attract
400-1200 76,054 -> 76,222 (+0.2%; 78,809), 1600-3000 169,779 -> 172,531 (+1.6%; 175,348); logic unchanged. The
cost is in scrolling frames: about 2.7 text rectangles a frame over word 2 or 18 (`rect_band`), the cells blacked at
window steps (about 3 a frame) and their checks. Hatari (`bench.sh`, 6000 VBLs): 26.8 -> 26.2 frames and 55.6 ->
55.0 ticks a second, 0 late border or palette events (two startup fallbacks). The longest HOG pass stays at 256 bus
cycles.

Tests: `sprite_test.py` now checks every band pixel, with the background and text on, two restoring frames without
sprites after each, window steps every frame, rows jumping, and a 400-frame random walk (3000 also passed): 4096
edge sprites in 512 frames plus the walk, exact; the build before this fix fails 194 frames (94 of the 512, 100 of
the walk). `render_test.py` checks words 0, 1, 19, 20 black in all its frames (the old build fails the walk at once);
`render_test.py --consecutive --first 1100 --step 25 --frames 20 --walk` (20 matched), `--consecutive --first 1600
--step 50 --frames 28 --walk` (28), `--consecutive --first 700 --step 50 --frames 12` (12), `--frames 3 --step 375
--scroll-sweep --flip-layout-sweep --sprite-edges` (253), `logic_test.py 1600`, `logic_test.py 4000 --walk`,
`reference_test.py 700`, `sound_test.py 6000`.

## The intro story (2026-10-12)

Since 0.2.1 the story after the start ("Long long ago, three dragons ...") showed rows of one character on black:
the window guards are only at the coverage's access sites (`docs/window-sites.json`), and every coverage and test
schedule pressed a button right after the start, which skips the story.  Its routines in bank 6 read the story text
and palettes from the window unguarded (the image of another bank), and their stores were not in `gen.TEXT_WRITERS` /
`PAL_WRITERS`.  `logic_test.py --idle N` keeps the player's inputs released until frame N; `--idle 2400` (in
`port.py test`) runs the whole story.  Added: 9 window sites (`2BA0F`, `2BA8A`, `2BA95`, `2BAE6`, `2BAF1`, `2BAF4`,
`2BAF6`, `2BAFE`, `2BAFF`), the text writers `BA18`/`BA1B`, `BAFF`/`BB02`, `BB1D`/`BB21` and the palette copies
`BA8A`, `BA95`, `BAE6`, `BAF1` of bank 6, and the twelve palette copies at `7BB5`-`7C2B` (every block copy to the
palette is now noted).  `--audit` names the instruction that made the access (the PC is past it when the access
happens: the next instruction's label was named before) and adds to its file instead of replacing it.
`BT_GUARD_ALL=1` (every indirect access guarded) showed the story right, which pointed at the sites.

## Standard PPO exploration

Use `venv/bin/python port.py ppo blktiger test --steps 256 --frames 2100` to check the shared training/recording/replay workflow. See [the common PPO guide](../../docs/ppo.md). PPO supplements the existing scripted coverage; canonical replay fixtures are preserved.

## Full-game verification status

Automated players such as Dreamer can attempt a full playthrough once this port's
adapter and native Hatari replay transport are verified. An attempt or assisted
stage visit does not establish completion; a successful natural Hatari playthrough
and graphics, sound and control checks are required for green **Complete** status.
See the shared [status and verification policy](../../docs/port-status.md) and
[current port status](../../README.md). Existing test results above retain their
stated scope; this note does not claim a new successful run or Dreamer integration.
