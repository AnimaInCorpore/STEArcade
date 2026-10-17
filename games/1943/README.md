# 1943: The Battle of Midway

![1943 on the STE (Hatari)](docs/screenshot.png)

Atari STE port (4 MB) of the `1943` set (Euro), registered as `1943`: the main Z80 translated to 68000 code, the
i8751 protection MCU's dumped firmware interpreted, a hardware scrolled Blitter renderer, the sound driver's effects
and music on the YM2149 (see "Sound").

```sh
python port.py prepare 1943                 # auto: US archive if present, otherwise Euro
python port.py prepare 1943 --set 1943       # explicitly choose the available Euro set
python port.py prepare 1943 --set 1943u      # requires the US Rev C program ROMs
python port.py cover 1943                   # 40 coverage runs (seeds 6-20: MAME's cheats, one stage each; 21-40: play that dies)
python port.py build 1943                   # assets + translation -> run/1943/1943.PRG (--sim: the Musashi build)
python port.py test 1943                    # ROMs, graphics, reference, lock-step logic and pictures
python port.py run 1943                     # Hatari (tools/hatari.sh)
python port.py mame 1943                    # pixel checks at frames 100, 700 and 1500
games/1943/tools/sprite_test.py             # sprites at the window edges: clipped, all shifts, 64 KB
games/1943/tools/front_test.py              # front tiles at the window edges: clipped, all shifts, 64 KB
games/1943/tools/bench.sh                   # Hatari speed: ticks and frames a second (DEBUG + AUTOPLAY, 6000 VBLs)
```

Controls: **5/6** coins, **1/2** start, **arrows** move, **Space/Ctrl** fire, **Alt** the loop (button 2),
**Escape** quits.  Joystick port 1 plays player 1, port 0 player 2.
Jaguar pad / PowerPad (STE enhanced ports, `docs/architecture.md` "Input"): pad A player 1, pad B player 2, the D-pad moves, **A** fire, **B** button 2, **Option** coin, **Pause** start, keypad **1/2** start, **5/6** coin, **\*** + **#** quit.

Both sets have 38 ROMs. Manifests come from the local MAME driver. The supplied
`1943.zip` plus `assets/roms/bm.7k` verifies completely as the Euro set.
MAME marks Euro's `bme01.12d` as `BAD_DUMP`: it is a historically modified dump,
used here unchanged. The US Rev C manifest remains available, but its three
program ROMs are not currently supplied. Set identity is recorded in
`build/1943/set.txt`; coverage from another set is rejected by the generator.

The archive swaps `bm05.4k` and `bm04.5h`. Preparation resolves files by size,
CRC32 and SHA1, then writes canonical filenames without changing the archives.
It verifies the complete set before writing extracted files or regions.
Extracted files go to `assets/roms/extracted/1943`; nine MAME-layout regions go
to `build/1943`. Loose ROMs and the parent archive can supply shared contents.

## Reference machine

`tools/machine.py` emulates the main Z80, eight ROM banks, mapped inputs and
latches, sprite buffering on c806, and IRQs at scanlines 144 and 240. The SYSTEM
VBL input follows the scanline. `tools/mcu.py` executes the actual i8751 firmware
at reset and each VBL INT1, including its table search and P3 falling-edge reply
strobe. Unknown MCU instructions fail explicitly. MCU execution is synchronous,
not cycle accurate; the sound CPU is not part of it (its driver is recorded alone: "Sound").

`tools/reference_test.py` checks all 256 MCU command values against the dumped
firmware tables (including retained replies for unknown commands), then runs
unpatched frames and saves `build/1943/reference.png`. Graphics tests check
4,000 decoded pixels against independent scalar ROM bit reads and exercise
layer enables, flips, maximum scroll, sprite ownership, priority and whole sprites at borders.

## MAME validation

`ref/mame_cmp_1943.py` constructs a temporary canonical ROM directory so MAME
sees correct audio/character names and the loose MCU firmware. It reads MAME's
RAM, video latches and actual buffered sprite RAM, renders the same state with
the reference, and compares the portrait screenshot pixel by pixel. The Euro
set matches at frames 100, 700 and 1500 with **zero differing pixels**.
This establishes video equivalence at those states; it does not establish
cycle-by-cycle CPU/MCU equivalence or STE performance.

See [hardware notes](docs/hardware-notes.md).

## Translation and schedule

`tools/gen.py` (`translate.compile_code`, `z80x.FAST`, the banked window rules of Black Tiger): 14,314 instructions
from the fixed ROM and banks 0, 1, 4, 6, none unsupported.  Besides the coverage roots, discovery adds the
continuations of the object allocators (`06EC` and relatives: `pop hl; inc hl` x3; `jp (hl)` returns to the call + 6
on success, and the compare `03C0` to + 3 / + 6: `discover.skip_returns`); random play reached one (bank 0 `A000`) that no coverage run had seen.  It also adds every
entry of the fixed ROM's jump tables (`JUMP_TABLES`: `59BC`, an object's type, and `5C18`): random play reached
`5AE2` after 6 minutes (2026-10-10, a quit to the desktop for a player: `z80_badpc`), 11 entries were untranslated.

The program is Capcom's task kernel (as Black Tiger): the scheduler at `00B6` runs the ready tasks of the table at
`EF80` and loops at `00D4` when none is ready.  `src/1943.s` hooks `00D4`: it draws the frame, then delivers a tick:
the line 144 IRQ (SYSTEM bit 3, the VBL, clear), the MCU's INT1, the line 240 IRQ (bit 3 set), each run to its
return to `00D4` with a token on the Z80 stack, then the tasks they woke.  `tools/machine.py run_frame_port` is the
same schedule.  Six ticks per five VBLs (59.6 Hz arcade), at most `MAX_SKIPS` frames skipped in a row.  The latches
`C804` (bank, flip, characters on), `C806` (the sprite list buffered: 128 entries of 4 bytes), `C807` (MCU command)
and `D806` (layer enables) are write hooks that keep every register and the CCR.

`src/mcu.s` interprets the i8751 firmware with exactly the instructions of `tools/mcu.py` (a jump table per opcode,
anything else stops at `z80_unsupported`); the P3 bit 6 falling edge latches the reply, PSW's parity is made exact
where PSW is read.

## Renderer (`src/render.s`)

The screen is the raw 256 x 224 picture rotated: 224 x 256, screen x = raw y - 16, y = 255 - raw x.  The back layer
(the sea, 32 x 32 tiles from the ROM map) scrolls vertically at half the speed of the front layer (clouds, islands,
ships), which also scrolls sideways (`D802`) in stages 3, 9 and 14.

* **Three display rings, virtual screens with twin lines** (the Commando port's scheme): ring line l and l + 320 hold
  the same picture of the back layer, so the 256 window lines and 32 guard lines above and below are contiguous
  wherever the window is.  Back layer lines are drawn once, as they scroll into the band (each a line of 8 baked
  tiles into all its copies; `back_line`); a change of the layer's enable or a jump draws the band whole.
* **Everything else is drawn every frame and listed as damage**, copied back from the twin lines at the ring's next
  visit: the sprites of colours 10 and 11 (behind the front layer), the front layer (whole 32 x 32 baked tiles, blank
  ones skipped; runs of lines with equal opaque masks: 4 lines and more one Blitter call per plane, shorter ones one
  call per line with the 4 planes as Y count, masks shifted to the horizontal scroll; an unshifted tile at the window's
  edge draws only its inner chunk), the other sprites (two lists sorted once a frame; the generated routines and
  endmask streams of `games/1942/tools/spritegen.py`, 3000 routines, a packed table), the characters (each baked as a
  small `movep.l` routine; the list is rebuilt when the character RAM changes, compared only in the 32-cell blocks
  its 55 translated writers mark).  A fully opaque front tile's damage is left where the next frame's opaque tiles
  cover it.  What an object draws into the 48 pixel margins beside the window is cleared.
* **Front-follow rings through cloud banks**: when the window's fully opaque front cells outnumber the blank ones (by
  16 of the 72, back again the other way; both layers on, no horizontal front scroll), a ring follows the front layer
  instead: its twin lines hold the front layer, drawn as its lines scroll in, and a sea pass draws the back layer where
  the front is transparent (blank cells two plain copies, the back tiles being in the same columns; mixed cells the
  tile's sea runs, inverted masks, one call per chunk and run).  Sprites of colours 10/11 get the front cells they
  overlap drawn over them again.  When such a ring's window wraps at the ring's end, the old band's lines are copied
  back from their twins (the sea is not damage).  A cloud bank frame went from 506k to 246k Musashi cycles.
* **Colours**: one 16 colour palette, Oklab k-means over the colours of every stage weighted by how often they show
  (`ref/palette_stats.py` -> `docs/palette_stats.json`, `docs/palette.json`).  Tiles of both layers are baked at
  build time (`tools/assets.py`: 396 back, 583 front tiles); sprites and characters are baked on first use into a
  pool with hashed caches.
* **Borders**: `engine/rt/borders.s` (shared with Commando and Gun.Smoke): Timer B fires 2 lines before the palette
  on, the bottom border and the palette off and polls to the line end, the bottom border starts Timer A for the next
  top border, which syncs to its HBL; nothing waits, HOG passes over 32 words run in pieces (`blit_go`).  Hatari, 4000
  VBLs: 0 late events.
* **Not exact**: where a sprite of colour 10/11 comes earlier in the list than an overlapping sprite of another
  colour, the arcade shows the first (or the front layer over it), the port the second.  The test recognises such
  pictures by rendering the reference in the port's order.

## Tests

`port.py test 1943` builds the simulator version and runs `tools/logic_test.py`: the dispatch tables as loaded (see "Memory"), then the translated program on Musashi
against the reference's port schedule, RAM, video latches, sprite buffer, latches, MCU reply and MCU RAM compared at
every tick, and that every change of the character RAM came with its block's mark; with `--render` each picture the
renderer finished is compared with the reference renderer through the palette map (the margins must be black),
`--twins` also checks the ring's twin lines (the back layer, or the front layer in front-follow).  `--cheat n` plays
stage n with MAME's cheats, `--seed n` random inputs.  Results (2026-10-09): every stage 0-14 with cheats (4000 ticks),
the default schedule, random seeds 1-3: logic exact, pictures exact but for the sprite order case above (stage 3: 127
of 2000 pictures, a few pixels each).

## Speed (2026-10-09)

| | first runtime | now |
|---|---|---|
| a tick's logic, Musashi (`tools/perf_test.py 1400 1300`, play) | 110k (MCU interpreter 62k) | 46k (translated MCU 8k) |
| a frame, open sea and a carrier | 340k | 222k |
| a frame, a cloud bank (`--cheat 9`, ticks 2600-2650) | 562k | 246k |
| Hatari, DEBUG + AUTOPLAY, 4000 VBLs (`tools/bench.sh`) | 31.9 ticks/s (53%), 6.4 frames/s | 55.7 ticks/s (93%), 11.4 frames/s |

The logic gains: the i8751 firmware translated (`tools/mcux.py`), the window guard only at the sites the
coverage saw reading the banked window (and sites it never ran; since 2026-10-11 block instructions on the same
terms: 883 of 3,784 indirect accesses, kept in `docs/window-sites.json` so a build takes them from there when the
coverage files have none; `W_GUARD_ALL=1` guards every access: 69.8k instead of 61.0k cycles a tick; `logic_test.py
--audit` traces a run for accesses to the image of the window, which only an unguarded site makes: none in 3000
random and 4000 stage-13 frames), a signed one-compare guard, a table bank switch.  `MAX_SKIPS` 8 (4 gave 87% speed and 15.5 frames/s).  `-D STAGE=n` makes the AUTOPLAY
build play stage n with the cheats; `engine/xprof.py 1943` profiles the translated code (`X1943_STAGE=n`).

Short Blitter passes (2026-10-11): no HOG pass is longer than ~256 bus cycles (`engine/rt/borders.s` `blit_go`; the
56-word copies of `restore_damage` and `ff_clean` run in two halves), so the top border interrupt is never held back
long.  It cost ~1% of a frame in Musashi (`perf_test.py 1600 1200`: 227k -> 230k) and in Hatari (DEBUG + AUTOPLAY, 6000
VBLs) 8.4 -> 7.9 drawn frames a second, the ticks unchanged (51.3); no border event started late in that run.
`tools/bench.sh` runs that benchmark (a DEBUG + AUTOPLAY build of 6000 VBLs in `run/1943_bench`, the counters
reported; `EXTRA="-D STAGE=n"` for a stage with the cheats): 2026-10-11, with the sound, the short passes and
the window guards at the coverage's sites, 51.4 ticks (86%) and 7.9 frames a second.

## Sound (2026-10-11)

The sound board (MAME `capcom/1943.cpp`): a Z80 at 3 MHz, two YM2203 at 1.5 MHz, four IRQs a frame (lines 32, 96,
160, 224).  The driver is Capcom's of Commando and Gun.Smoke (the same code at other addresses), recorded and played
with the engine's `engine/capsnd.py` / `engine/rt/capsnd.s` (see `games/gunsmoke/README.md` "Sound" for the method).
`tools/sound.py`: RAM C000, latch C800, the command table at 009F, five effect slots a chip (C500-C580, C600-C680)
that end the lower ones unless their byte 31 is $FF, four music slots C100-C400; command 00 stops everything, 33-39
and 3B-3F the music.  31 effects (the SSG) and 19 tunes (FM) are recorded: 122 KB in `build/1943/cs_data.s`.

Effect $0A (64 seconds of notes) would take 68 KB with its four phases: its phases 1-3 differ from phase 0 only in
which IRQ a volume step falls on (up to 3 IRQs, 12 ms), so it plays phase 0 in every phase (`capsnd.EXC_LIMIT`: an
effect whose phase exceptions exceed 8 KB), 50 KB less.

Checks: `sound.py check 6000`: the music streams through the decoder 0 of 445,113 channel ticks differ; the effects
with random commands 70 of 48,000 chip-IRQs differ audibly (the noise period an effect's first IRQs inherit), with the
game's commands (`logic_test.py`'s play) 0.  `sound_test.py` (in `port.py test`): the 68000 player against the model,
0 of 20,000 ticks differ; ~7,900 cycles a tick.  Hatari (DEBUG + AUTOPLAY, 4000 VBLs): 53.6 game ticks (90%) and 9.4 drawn
frames a second; without the sound (`-D NOSOUND=1`) 55.7 and 11.3 (the frames get what the ticks leave).  Hatari: sound in the attract mode and play.
Memory (2026-10-15): the program needs 3,668,442 bytes and leaves 384 KB from the desktop (`tools/memfree.sh`:
4,061,212 on a 4 MB STE with TOS 2.06; a tester's Mega STE with a hard disk driver and accessories had 3,831,554, and
the 4,051,070 bytes of 0.3 did not start).  Most of it is the memory work of 2026-10-10 below, whose branch was only
merged on 2026-10-15 (0.3 was built without it).  A bank's dispatch table, flat over its code's span (104 KB for
banks 0, 1, 4, 6), became a directory long per 64 window addresses and pages of words, (the entry - the page) / 2,
pages without an entry shared (50 KB): ~3 window dispatches a tick, ~50 cycles more each.  The fixed code's table stays
flat (80 cycles a dispatch).  Musashi (`perf_test.py 1600 1200`): logic 48,133 -> 48,062 cycles a tick, frames
unchanged (236.8k), 28.1 ticks and frames a second.  The tests' fixed buffers (`front_test.py`, `sprite_test.py`)
moved above the program, which now reached them.

## Memory (2026-10-10)

text + data + BSS from `build/1943/1943.map`: **3,587,774 bytes** (was 4,003,336: more than GEMDOS leaves on a real
4 MB STE with a hard disk driver and accessories, Pexec failed).  The program allocates nothing at run time (no
`Malloc`).  Nothing changed in the logic or the pictures, and nothing got slower:

| what | before | after |
|---|---|---|
| natural-PC dispatch tables | 448 KB BSS (a long per Z80 address: fixed 128 KB, banks 0, 1, 4, 6 and an "invalid bank" 64 KB each) + 85 KB of entry lists to fill them at start | 168 KB of data built by `gen.py dispatch_tables`: a word per Z80 address, the fixed code 64 KB, a bank only its code's span (15-31 KB) |
| fixed ROM | 32 KB data, copied into the 64 KB BSS Z80 image at start | assembled in place in the image (`g_block` in the data section) |
| 68000 stack | 16 KB | 8 KB (under 200 bytes used in the simulator; the rest for the TOS calls at the exit and on a crash) |

* **Dispatch tables**: an entry is (the label - the table) / 2, unsigned, and each table stands in the text section
  right before its region's code (the fixed code, each bank's code), so `g_dispatch` jumps relative to the table
  (`move.w (a4,d7.l),d7; add.l d7,d7; jmp (a4,d7.l)`: 80 cycles for the fixed code, was 92).  (2026-10-15: a bank's table is
  a directory long per 64 window addresses and pages of words relative to the page, see "Memory (2026-10-15)";
  $C000 and up is rejected, a bank without code points to `g_wd_none`, every page bad.)  vasm rejects an entry beyond
  128 KB; gen.py checks that the regions are in address order and that the line before each table ends its flow.
  Addresses without an entry (no code, merged labels) go to the region's `g_bad_<region>` stub (z80_badpc).
  `logic_test.py` first checks every table word and span as loaded against the map (`build/1943/dispatch.json`: each
  Z80 entry on its label, everything else on the stub).
* **Measured and kept**: the sprite / character caches (4096 slots, 32 KB each) are not larger than their working set:
  with 2048 slots the conflict misses use up the 96 KB pool faster, it rolls over once more in 6000-10000 ticks and
  the bakes rise 10-30% (`--cheat 9`: 1245 -> 1639 sprite bakes in 6000 ticks).  The damage lists (700 rectangles a
  ring, at most 172 used a frame in 6000 ticks of the default schedule, random inputs and stages 3, 9, 13, 14) have no
  overflow check and stay.  `front_map` as words (the tile's number, a table of the tiles' addresses: 30 KB less)
  was as fast in Musashi but drew 1.5-3% fewer frames in Hatari's cloud bank bench: dropped.
* **Speed**, 28fe0cb -> now, the same inputs.  Musashi `perf_test.py` (400 ticks): play (1700 1300) logic 47,991 ->
  47,719 cycles a tick, frame 206,404 -> 206,465; a cloud bank (3000 2600 --cheat 9) logic 82,141 -> 81,613, frame
  365,990 -> 365,888.  Hatari (`tools/bench.sh`, DEBUG + AUTOPLAY, ticks / frames
  drawn; the frames move by a few % with the screen's place in memory alone, so each case was run with the rings at
  more than one place, `-D PAD=n` before `screen_area` in a scratch copy):

  | | 28fe0cb | now |
  |---|---|---|
  | 4000 VBLs | 4460 / 924, 4446 / 910 | 4458 / 911 (55.7 ticks/s, 93%) |
  | 8000 VBLs | 8782 / 1899, 8768 / 1940 | 8787 / 1934 |
  | `EXTRA="-D STAGE=3"`, 6000 VBLs | 6631 / 4017, 6566 / 3873 | 6637 / 4105, 6626 / 3963 |
  | `EXTRA="-D STAGE=9"` (cloud banks), 8000 VBLs | 8469-8473 / 8625-8726 (6 places) | 8481 / 8591-8742 (3 places) |

## Not done

The flip screen (cocktail); the arcade's clipping of sprites at the raw 256 pixel edges; full speed in the
busiest scenes (the game's own logic is 86k cycles a tick there).

## Whole objects at borders (2026-10-11)

Partially visible sprites and front tiles now draw whole into the virtual ring. Removed the post-draw
`clear_outside` eraser and the one-word front-tile edge path. Their complete damage rectangles are restored
before the next picture. The 48-pixel side bands inside the hardware window may therefore contain overhang.
The existing sprite source rows already use the reordered mask-group method. Validation: 1,600 translated
logic/render frames match, with 160 game pictures and the twin background compared against the reference.
The comparisons cover the arcade picture; the side bands intentionally show whole objects.
The rebuilt 4 MB STE Hatari debug run completed 2,500 VBLs without a crash file and with zero late
border or palette events (two startup fallbacks).

## Sprites clipped at the window's left and right edges (2026-10-12)

The window's edges lie on 16-pixel chunks (3 chunks of side band each side), so a sprite across one has exactly one
word inside: `sprite_part` sends sprites left of window x 0 or right of 208 (one unsigned compare) to `sprite_edge`,
which culls those wholly in the right band and draws the others with `clip_part`: one word a line, the right edge's
first word with the skewed source under END1, the left edge's second word with FXSR and source Y increment 0 under
the stream's END3 mask; only that word is listed as damage.  The 48-pixel side bands no longer show sprites (front
tiles may still spill there).  Cost (Musashi, CPU + Blitter a frame): play 237,010 -> 237,061, stage 3 346,033 ->
346,166 (+0.02-0.04%, the compare); Hatari (bench.sh, 6000 VBLs) 51.2 ticks/s, 7.9 frames/s, no late border event.
`tools/sprite_test.py`: 4 sprites with holes, all 16 shifts, both edges and the culled band, plain and across 64 KB
(376 cases, 232 clipped) against the same sprite drawn whole by its generated routine, the bands untouched (the old
whole drawing fails it).  `logic_test.py --render` prints the clipped sprites: default 1600 frames (12), `--cheat 3`
2000 (62), `--seed 1` 1600 (15), `--cheat 9 --twins --every 2` 3000 (975): all pictures equal.
## Front tiles clipped at the window's left and right edges (2026-10-12)

The front layer's 32-pixel tiles spilled into the 16 pixels beside the window in nearly every picture (its rows start
at window x -16 when the front scroll D802 is 0): `logic_test.py --render` now counts the pictures whose side bands
are not black, and before this change found 941 of 1600 (default), 1341 of 2000 (stage 3) and 1170 of 1500 (stage 9),
~3,500 pixels each.  `front_tile` now draws only the words inside the window: an unshifted tile at chunk -1 or 13
draws one word (the general path's one-word mode: the right word at chunk 0, the left at chunk 13), a shifted one at
chunks -2/-1/12/13 its three words with the band words' end masks 0 (`ft_m12`, `ft_m3`, ANDed into the run's
shifted masks) and lists damage only for the chunks inside.  The common path pays one unsigned compare, as before
two.  Musashi (`perf_test.py`, CPU + Blitter a frame): play 237,061 -> 236,816 (-0.10%), `--cheat 3` 346,166 ->
341,561 (-1.33%), `--cheat 9` (ticks 2600-2900) 354,525 -> 353,716 (-0.23%); the logic unchanged.
`tools/front_test.py`: 4 tiles with holes, all 16 shifts, both edges and wholly outside, plain and across 64 KB
(768 cases, 496 across an edge) against the same tile drawn whole in the middle, bands untouched, every change inside
the listed damage, the damage inside the window (the old code fails it).  The side bands are now black in every
compared picture; `logic_test.py --render` also prints the front tiles clipped (`ft_uclips`, `ft_sclips`).

## The MCU's INT1 in 68000 code (2026-10-12)

The i8751's VBL interrupt (`$0013` -> `$0200`-`$023B`) looks the Z80's command up in 32 (key, value) pairs at ROM
`$0800` and replies with the value of the last matching pair (R4 as it was when none matches).  The firmware walks all
32 pairs every time; translated, each pass pays the 8051 flag bookkeeping of its `subb` (~10k cycles a tick).
`src/mcu.s` `mcu_int1` searches the pairs from the end and sets what the walk leaves at once (R2 = R7 = the command,
R3 = 0, DPTR = `$0840`, ACC and PSW's CY / AC / OV of the last pair's `subb`, P0, the reply through P3 bit 6, IE1, EA).
`-D MCU_XLATE` builds the translation.  `tools/mcu_native_test.py` (in `port.py test`): every command from 8 random
MCU states each against the translated firmware (the 256 bytes of RAM and SFRs, the reply, the transaction count, the
pc), identical; `logic_test.py` 4000 frames matched.  `tools/perf_test.py 1400 1300`: the logic 57.1k -> 48.0k cycles a
tick (the MCU 1.2k).


## Standard PPO exploration

Use `venv/bin/python port.py ppo 1943 test --steps 256 --frames 2100` to check the shared training/recording/replay workflow. See [the common PPO guide](../../docs/ppo.md). PPO supplements the existing scripted coverage; canonical replay fixtures are preserved.
