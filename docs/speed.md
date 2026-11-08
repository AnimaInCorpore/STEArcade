# Speed on the STE

Everything the ports learned about speed, by topic, with the measured figures, followed by a table of which port uses
which technique and a list of the techniques that look applicable to ports that do not use them yet.  The figures are
the ports' own (their READMEs, `sprite-preparation.md`, [the scrolling audit](virtual-scroll-performance.md)); they
come from different builds, scripts and dates, so they rank ideas, they do not compare ports.

The user's rules for every port (`AGENTS.md`): keep logic speed and picture rate apart; measure CPU plus Blitter bus
cycles before keeping an optimization; drop costly effects only with the user's OK, never gameplay ("keep the
gameplay, drop what only costs work": R-Type, Mr. HELI); cover the whole game before trusting a figure.

## The budget

* **25 pictures a second** at 50 Hz means a new completed picture at least every two VBLs: 320,000 cycles at 8 MHz for
  everything due in that time - the logic, sound, interrupts, CPU drawing and the Blitter's bus time.  A renderer-only
  320k is not enough.  For an arcade rate F and a logic cost L a frame: picture <= (8,000,000 - F x L - other work a
  second) / 25.  Neither a run's average above 25 nor its p99 below 40 ms proves a steady rate: measure the longest
  interval between shown pictures too, and say whether stage or floor changes are included.
* **Do the arithmetic first**: at 60 ticks against 25 pictures a second, 1k cycles saved a tick is ~2.4k a picture
  (Commando).  Black Tiger's 108k a tick in Hatari leaves ~61k a picture at 25 pictures a second; Bubble Bobble needs
  ~3-4x cheaper logic, more than translator tweaks give; Double Dragon's full-rate logic exceeds the 8 MHz budget.
* **Musashi and Hatari differ**: the simulator's cycles are instruction counts, Hatari's the emulated bus.  The ratio
  was 1.35 for 1942 and ~1.14 for Commando's play: use the simulator to rank routines and Hatari to decide.  Musashi
  picture tests must add the Blitter's cycles (a HOG pass holds the CPU).

## Measuring

* **Recorded play, per stage, in Hatari** (`bench.sh` with `PLAY=1` / `REPLAY` / `PLAYBACK`, recordings from
  `engine/playbot.py` / `play_search.py` or MARP): an attract demo or one scripted level misses the costs of later
  stages (R-Type's later stages, Mr. Do!'s title).  A DEBUG + AUTOPLAY build that replays an input script by VBL and
  writes counters every few hundred VBLs gives windows comparable with the simulator profile's (Bubble Bobble).
* **A scripted run is a fixed workload only if the game's course does not follow the CPU budget.**  Where the game gets
  whatever time the frame leaves, a faster build plays a different game from the same inputs (F030Arcade's Bubble
  Bobble: one more instruction, 121 sound commands instead of 151, 16.5 pictures a second instead of 10.6).  Compare the
  logic's own counters (rounds, sound commands, a RAM checksum at fixed rounds) before comparing rates; price a change
  on a deterministic harness and quote scripted figures as a range over repeats.
* **Count every VBL**: Bubble Bobble's bench left out late VBLs, and every rate before 2026-10-12 was ~2x too high
  (b89956a).  A counter that sees the same picture twice is not a picture rate (1943's STAGE=9 rows report more
  pictures than VBLs).
* **Check what a bench ran**: Double Dragon's first PLAY=1 had no PLAYBACK code (it measured the attract demo); R-Type
  writes no COUNTERS.BIN without `-D DEBUG`; `bench.sh` reused the old PRG when assembly failed (read the "built" line;
  Dragon Spirit's stops now); filters on its output hide "no COUNTERS.BIN" / CRASH.TXT; a REPLAY start late in the game
  first runs the reference to it (10+ minutes, not a hang); other sessions' Hatari runs slow the host; `tools/hatari.sh`
  kills every running Hatari.
* **Keep the memory layout fixed in A/B tests**: 64 KB crossings and the BSS layout move a picture by +-2k (Time Pilot
  and Gyruss were compared with buffers padded to the same address modulo 64 KB).
* **Profilers**: per arcade instruction (`engine/xprof.py`, the 6809 / V30 ports' `tools/profile.py`), per routine
  and per 256 bytes; per render phase (`REN_PHASES` / `PHASES=1`: Splatterhouse, Dragon Spirit).  A profiler attributes
  by the nearest label: a `name = *` label is a symbol too, and absolute symbols (equates) must not be used as code
  labels (Bubble Bobble's block copy loop had been charged to the runtime).  Non-stepped figures overshoot by up to
  2,000 cycles; Hatari's profiler and Musashi agree within ~5-10% a routine (Hatari's own profiler through the command
  fifo collected nothing for Dragon Spirit: in-program counters did).
* **Look at the 90th percentile**, not only the median: a few whole recompositions decide whether a steady rate is
  reached.
* **Per VBL** (the acceptance of the scrolling audit): logic rounds, picture starts / completions / publications, the
  shown buffer, the shown picture's age, pending logic and late border events; an interval histogram, its maximum,
  p95/p99 and the worst gameplay windows.  Zero late border events in the pinned Hatari.

## Where a picture's time goes: the checklist (R-Type's stages, 2026-11-01)

R-Type's stage renderer (`games/rtype/src/stage.s`) showed where an STE picture's time goes once the sprites are
prepared stefastbobs2's way.  Check every port with two tile layers, palette effects or a heavy CPU in this order:

1. **Parallax costs whole recompositions.**  A second layer composed into the buffer with the first (locked) is cheap
   only while it keeps its offset; a background at its own speed forces it again every few pixels.  Per scene, ask the
   user to drop the parallax: draw the background locked to the foreground from a strip recorded once from the
   reference (`games/rtype/tools/stage_bg.py`), or leave a decorative background out.  Check first that it holds no
   gameplay tiles (R-Type: tile codes below 7D0h are walls) - where it does, keep it at the arcade's place.  Dragon
   Spirit locks its water layer the same way (a lock shadow, `ren_lkshd`).
2. **Colour cycling costs recomposition when indices change.**  Freeze cycling rows at their scene's reference target
   (R-Type: FROZEN_ROWS), or give the changing pens dedicated STE indices whose colours are set per picture
   (DEDICATED, FADE_SNAP): a palette write instead of a recomposition.  Dragon Spirit's intro lightning is a palette
   flash of the chosen colours, not a new choice.
3. **Two full layers: draw the smaller one as pieces.**  Measure both layers' 16-pixel chunks with pixels in the window
   and switch which one is the buffer's layer at the crossover (R-Type stage 3's hybrid); clear instead of restoring
   where a piece layer has nothing under it.
4. **Erase only what can be seen.**  Guard rows the display never shows need no erasing; lines that scroll into view
   do.
5. **Then the logic** (68-150k cycles an arcade frame in R-Type): profile per stage and replace hot routines with
   natives or leaf calls, each checked in lock-step over the whole game (a broad-phase collision shortcut was wrong only
   in stages 7 and 8).
6. **Memory buys speed on the 14 MB development machine** (pre-coloured sprites, recorded strips); the release's load
   limit is solved later (per-stage loading, packing, `engine/rt/hdd.s`).

## Logic

* **Register maps and the second pass** (`architecture.md`, "The Z80 translator"): 1.08-1.73x for the Z80 ports
  (2026-10-08).  A port gets them by going through `translate.compile_code` with `z80x.FAST` / `FAST_LONG` and real
  joins only (`porting-guide.md`, "Translation").
* **Guard only the coverage's window sites, and audit the rest** (Bubble Bobble, Black Tiger 2026-10-11): a check at
  every indirect access costs a quarter of the translated cycles.  Record the sites in the coverage runs (reads of the
  window and the banked RAM, writes of the latter), keep them in `docs/window-sites.json`, and trace a simulator run
  for accesses to the unused image of the window (`logic_test.py --audit`).  Black Tiger's play logic 80.7k -> 65.3k a
  tick; 1943 69.8k -> 61.0k; 1942 26.6k -> 23.8k; Bubble Bobble's main CPU 67.7k -> 62.4k; Gun.Smoke 40.5k -> 37.3k (229
  of 1479 sites).  `W_GUARD_ALL=1` builds the old way for comparison.  Guard every block copy regardless (MARP,
  `porting-guide.md`).
* **Leaf functions in place** (`Config.inline_leaves`, `inline_rst`, `inline_jumps`; the 6809's `inline_calls`): a
  call of a short leaf is emitted as its instructions (~70 cycles a call).  Bubble Bobble's main CPU 92.5k -> 83.5k;
  Trojan's rst $18-$30 plus a copy native 61-65% -> 90% speed; Pooyan's sound 31k -> 21k; Gyruss's sound 57k -> 52k;
  Double Dragon's bank selectors at 205 sites; the 2026-11-02 audit added them to 1942, 1943, Gun.Smoke, Kung-Fu Master
  and Gyruss (logic -1.4..-3.5%) and larger leaves to Bubble Bobble (48).  Logic tests skip the 64 bytes below SP.
* **Per-call flag summaries and the 68030 forms on the 68000** (6809: `call_summaries`, `fast_forms`, `ret_weights`,
  `fixed_slots`, `slot_ctx`): Hyper Sports logic -16..21%, Track & Field -10..17%, Galaga '88 -3.4%, Splatterhouse
  -7.1%, Double Dragon 191.3k -> 180.9k.  The 6809 translation's own history (Splatterhouse, 2026-10-12: play 452k ->
  147k for the two CPUs): per-function return liveness (2250 flag wrappers -> 140), static and inline bank switches, I/O
  sites from the coverage's addresses, cached slot bases, byte-direct 16-bit operations, jump tables for `JSR [B,X]`.
  The V30's: liveness through computed calls (1055 wrapped instructions -> 117, 18% fewer cycles), returns through a
  64K-long IP table without touching the CCR.
* **Video RAM stores inline at the writer sites** (`Program.video_inline`: a range check and a cell mark, the I/O
  handler only outside the range): Hyper Sports logic -15.7% (the I/O handler was 37% of it), Track & Field -6%.  Look
  for a port's I/O write handler in the profile first.
* **No flags kept at an idle hook whose flags the interrupt handler never reads** (`flags_at=set()`; Black Tiger
  `00D4`): logic -2.5%.
* **Natives pay only where the logic is concentrated** - profile per routine first.  Bubble Bobble: the sub CPU 54.5k
  -> 15.9k with 16.0k of natives (`y_near`, `y_state`, `z_state`), the native MCU 27k -> 3.9k a frame; 1943's i8751
  57.1k -> 48.0k and its task kernel scan (24% of the translated code) -5.2%; Hyper Sports 82.7k -> 56.0k (a division);
  Double Dragon's collision (~25% of its 6809 time) 251k -> 193k; Gyruss's sub CPU 99k -> 55k; Dragon Spirit's three
  -16% (seed 5 106.8k -> 89.3k); R-Type's crawler handler was 36% of play logic (~35 natives now).  Did not pay:
  Commando's `$A498` (~14 cycles a Z80 instruction already; its top routine 12%); Double Dragon's remaining logic is
  flat (no routine over 2.5%).  Exact natives are checked against the translation (`porting-guide.md`, "Natives").
* **Writer marks instead of comparisons** (the same technique under many names: dirty flags, store marks, `*_written`,
  `*_mark_*`, `tile_marks`, `bg_note`): comparing video RAM with a copy costs 7.5 cycles a byte (`cmpm.l` + `dbne`, 15k
  for 2 KB).  Where few instructions write a region, record the write sites in a reference run (the instruction's start
  pc: the Z80 core's `pc` at write time is already the next one), list them in `gen.py` and emit `st <flag>` after each
  (`Scc` leaves the CCR alone) or a mark of the cell / block.  Compare only when marked, plus a few hundred bytes a frame
  in case a writer is missing; the logic test checks that every change came with its mark (`porting-guide.md`).  Black
  Tiger: background RAM (14 writers) and palette (10); Commando: tile RAM (10) and character RAM (31); Gauntlet: logic at
  60/s and 32.6 pictures/s in light play with comparisons only where the writers marked.  R-Type's 64-byte marks with a
  skip loop over unmarked rows: -3% a picture.  Rejected where one routine rewrites everything every round (Bubble
  Bobble's object RAM, `$04B6`).
* **Do sound work at build time**: Double Dragon's ADPCM decoded on the STE cost 98k of 163k a frame (now streams made
  at build time); Commando's effects as tables -1.7k..-4.2k a tick.
* **Dead ends**: return points ordered by coverage counts, predicting both of an object loop's return points, a native
  object loop costing what its call/ret saved, the higher-level logic set (-2..-3.5% isolated, not integrated), the
  later natives (box test, dispatch fusion) (R-Type, `games/rtype/docs/`); a shadow return stack (Double Dragon);
  Black Tiger's word dispatch table and the engine's `ldir` in 1942; interrupt-time loops whose flags reach the
  interrupted code (1943's timer loop).

## Pictures

### Scrolling

* **Hardware scroll over virtual screens, no per-frame background copy** (Commando 2026-10-08, after stedaimakaimura;
  the scrolling audit of 2026-10-19 confirmed it for every scrolling port).  Each display buffer is a virtual screen
  shown at the scroll position by the video address.  Every buffer line `l` and `l+H` hold the same background (twin
  lines), so the window (and the guard lines of whole sprites) is contiguous wherever it is, without a Timer B wrap.
  Only the tile rows that scroll into the band and the tiles whose RAM changed are drawn, into every buffer.  Commando's
  frame 962k -> 255k cycles.  The twin period must exceed the band by the tile overhang (H = 320 for a 288-line band).
* **Horizontal scroll** (Gun.Smoke's D802, Kung-Fu Master, Trojan, Black Tiger, Double Dragon, Splatterhouse, R-Type,
  Dragon Spirit): keep the tiles at fixed buffer x and move the Shifter's window (video address + `$ffff8265`, the line
  width 4 words less with a fine scroll); twin columns (x and x + the ring's width) do horizontally what twin lines do
  vertically.  The window's edges are then anywhere in a word: side bar clears need end masks, and text cannot use
  `movep` at the screen.  Gun.Smoke's in-place software shift was slower (441k against 238k).
* **Incremental virtual screens**: check only the cells that scrolled in; draw a new tile to its twins one page away too
  (outside the window), so the next page is ready; per display ring a damage list restored from the clean screen.
  Prepare twin instances on first use, not all at once (Black Tiger 26.2 -> 29.5 pictures/s); do not apply this to
  Commando-style twin-line restoration, whose twins are the clean source for old damage.
* **Don't flush caches at a scroll wrap** (Trojan's baking 27k -> 0, a picture 765k -> 695k), and choose the twin window
  nearest the previous position at a ring's wrap (Kung-Fu Master's dips at its 512-pixel wrap, open).

### Change detection, caches and palettes

* **Compare as longs** (`cmpm.l (a2)+,(a3)+`, ~17k for 2 KB), never per cell (Commando's per-cell loops cost 330k and
  210k a frame); better, writer marks (above).
* **Palette stamps instead of cache walks** (Bubble Bobble): when a pen's colour slot changes, start a new palette epoch,
  record it for the pen, and store the epoch with each baked entry; a lookup whose stamp is older checks only the pens
  its tiles use and refreshes the stamp when none changed.  ~225k -> ~50k a slot change.  Trojan and Double Dragon key
  their cells with palette epochs; Dragon Spirit uses slot stamps and a tile shadow per layer (a stamp scan 425k ->
  160k).
* **Composite caches pay where the game repeats itself**: a level's static cells come from a few dozen tile pairs
  (Bubble Bobble: 60 recipes for 896 cells); an exact cache of composed cells makes rebuilds mostly copies.  A cache
  keyed by an interned colour mapping would also serve colour cycling.
* **Recompose only the cells whose pens changed** (bank maps computed beforehand): Galaga '88 10.62 -> 12.14 arcade
  frames/s (BENCH -11.5%, p90 -36%), copied by Dragon Spirit; Donkey Kong redraws only the tiles whose pens move at a
  palette bank change.
* **Lose no cycles on a cache hit**: a `movem` of 14 registers around a hashed lookup cost more than the lookup; look up
  first with two or three registers and save the rest only to bake.
* **Pre-coloured data**: per-pen masks became the arcade's bit planes (`porting-guide.md`, "Memory"); R-Type pre-colours
  every sprite definition at build time (1 MB on the development machine).

### Sprites

The method and every port's measurements: `sprite-preparation.md`.  In short:

* **Generated code per shape and pass-type pattern with mask streams** (`engine/sprite_programs.py`, Time Pilot): rows
  grouped by mask, a one- or two-word pass per row and shift, the end masks read from a stream, code shared by content.
  Time Pilot 163.9k -> 103.6k a picture, Gyruss 116.1k + 28.4k -> 75.4k + 12.7k, Kung-Fu Master 131.3k + 25.1k -> 89.0k +
  20.0k, Pooyan, Mr. Do!, Track & Field, Hyper Sports -11..-30% of the sprite cost.  Older form: 1942's `spritegen.py`
  (routines shared by row structure, 772 for 8000 sprite x shift; streams read with `move (a0)+,(a2)`: the same cycles,
  a third of the memory), used by 1943, Commando and Gun.Smoke.  Large sets get code for the shapes coverage drew most
  within a budget (Gun.Smoke 1074 of 2008 shapes, 96.5% of the draws; Hyper Sports 147 of 405, 98%), the rest by the
  row path.  Not faster where shapes repeat few masks (Galaga) or change too often (Splatterhouse, Galaga '88: code made
  on first use eats the saving).
* **The setup and bookkeeping cost as much as the drawing**: keep the Blitter pointers and constants in registers from
  sprite to sprite, decide every fallback before listing damage, keep slot headers so the setup has no lookups (Time
  Pilot's `draw_one`); Commando's per-slot sprite cache (83% hits) ~680 -> ~560 cycles a sprite.
* **Damage only what was drawn** (the opaque rows, the drawn lines and words), not whole boxes: Commando's opaque-row
  damage 205k -> 177k a play picture; Kung-Fu Master skipping blank cells cut its front-tile and span copies by two
  thirds; rows dirtied only by sprites restore only their 16-pixel groups (Track & Field -12.5%, Hyper Sports -7.6%).
* **Restore by contour** (stefastbobs2's contour clear as a copy, prepared per sprite and shift; R-Type 2026-11-07):
  -0.3..-5% a picture, the saving almost all Blitter words from the corners of composed sprites.  Clear instead of copy
  over black where the test is cheap (R-Type's title, `st_clrtest`: -10% on the attract recording).
* **Skip the work of pictures that will be skipped** (the sprite list copies: Commando, Gun.Smoke).  Not where the list
  copied holds earlier frames' entries (Double Dragon: the sprite RAM copy takes all 76 MCU entries, those beyond the
  count are left from earlier frames in the arcade too).
* **Clean twins pay only when pictures are close together** (Double Dragon, 2026-11-07, exact, not kept): restoring
  sprite rectangles from a clean copy of each ring instead of redrawing their cells saved 6% of a picture drawn every
  2nd frame, nothing at the port's real rate (a picture every ~9 frames), where the cells scrolling in, written twice,
  and the text drawn again after each scroll dominate.
* **Dead ends**: merging overlapping restores (Black Tiger 32.8% duplicate words, exact but +0.8%; R-Type's damage
  coalescing; Commando's damage-bitmap union); keeping unchanged sprites (Splatterhouse: 2.6 a picture kept for 160k);
  reordering rows where masks rarely repeat (Gauntlet, Kung-Fu Master, Gyruss: natural order stays); aligned rows
  instead of FXSR (-0.05..-0.6%), code per alignment over the load budget (Gyruss +320 KB).

### Text

* **Unshifted text: the CPU** (`movep.l` a byte-aligned 8 x 8 character with a keep mask, ~600 cycles; Commando, 1943,
  1942, the tile ports).  A Blitter prototype for Commando's unshifted text was slower (`draw_foreground` 25.0k ->
  26.4k): without a shift the CPU's `movep` / `movem` line costs no more than a pass.
* **Text over a moving picture: pieces drawn like sprites** (mandatory since 2026-10-24: no AND + OR pairs): a run's
  lines cut into one- or two-word pieces with opaque pixels when the text changes, a copy pass a piece with the shifted
  mask words as end masks (`text_run_pieces`, `fg_pieces_build`).  Black Tiger's text 83.7k -> 57.3k a scrolling
  picture (24.6 -> 25.5 pictures/s in Hatari); Gun.Smoke's median picture 135.8k -> 110.5k.  Character pairs (Trojan,
  Double Dragon: one pass per character row); solid runs as Blitter fills (Double Dragon).
* **Redraw text only over the cells redrawn or drawn over** (a text entry drawn twice gives the same result): Double
  Dragon's mission 1 median 500k -> 400k.  Keep a list of the visible, non-blank characters, rebuilt only on a change
  (Commando).
* **A HUD as its own image** with a video-address switch (`BD_VSWITCH`; R-Type's status bar, Splatterhouse's
  `REN_VSW` bars, Kung-Fu Master's and Moon Patrol's panels): drawn only when it changes, its own palette.

### Blitter costs

* **A word with an end mask of 0 is not skipped**: the Blitter still reads the destination and writes it back, every
  plane (4 words a pass row, ~32 bus cycles).  Count Blitter words, not passes.  R-Type's sprites: 10.3% of their words
  (440 a picture) were such masked-off words; narrower passes for them cost 1-3% more a picture (more units, 2.1 -> 3.2
  MB of streams).  END2 = $FFFF only where every inner word is opaque after the shift (R-Type -0..3%).
* **Set it up once and keep its registers in address registers**: Commando's tile copies as two 32-word passes with one
  setup -13k a picture while scrolling, its damage restore -2k.
* **Known full-mask copies and HOP 0 fills** use `blit_go_copy` / `blit_go_fill` (32 words a piece); a copy with
  partial masks needs destination reads even with OP 3, FXSR adds a source fetch: count both before choosing a piece.
* **Short HOG passes cost a little** (1943 8.4 -> 7.9, Gun.Smoke 24.2 -> 23.0 frames/s): split wide copies at the caller
  (1943's generic strip path's `muls` cost ~6k a tick).  Edge clipping costs one compare on the hot path (1943: +0.02-
  0.25%).
* **The halftone RAM** (user, 2026-11-01): HOP 1 takes the source from the 16 halftone words, so with full end masks a
  word costs a write, as a clear does.  In the 4-planes-a-pass layout the 16 words hold 4 lines x 4 planes of a
  16-pixel pattern: a one-colour area (any colour) or a pattern repeating every 16 pixels across and 1, 2 or 4 lines down
  is restored at clearing speed.  No port's background has qualified so far (R-Type, 1943, Gun.Smoke, Commando, Trojan:
  0-2.6% of the words); verify the line-number stepping in the pinned Hatari before relying on it.
* **The Blitter for 1-2 pixel runs** costs more than four bit operations (Galaga '88's stars), and set-up costs more
  than it saves for aligned 8 x 8 tiles (Bubble Bobble).

## Schedule

The schedules are in `architecture.md`, "The schedules in use".

* **Decouple the ticks from the pictures**: the arcade ticks at 55-61 Hz, the STE shows 50; count arcade frames per
  VBL and skip pictures, not ticks, when the CPU is short.  The game then runs at the arcade's speed (1942, 2026-10-08).
* **The skip limits trade pictures for game speed where the logic is the limit**: Double Dragon's MAX_SKIPS 4 -> 8
  (the user's choice, 2026-11-07): 28.1 -> 32.3 arcade frames/s, 8.6 -> 7.1 pictures/s (in play ~4.5 -> ~3).
* **Where the picture is cheap they change the game's speed, not the picture rate**: Commando's MAX_SKIP 2 -> 3: 99% / 26.6 -> 100% /
  26.5 pictures/s (scheduling alone ~3%, noise level); Bubble Bobble's TICK60 0.532 -> 0.668 rounds a VBL but 12.2 ->
  5.2 pictures/s; Dragon Spirit with R-Type's PIC_EVERY 8 / MAX_BEHIND 12: 7.97 -> 11.2 arcade frames/s but 3.02 -> 1.40
  pictures/s.  Choose per port with the user.
* **Pictures can lock to a flickering layer's phase** (Splatterhouse at PIC_EVERY 2: a whole play on one phase of its
  30 Hz layer; ~4k cycles of nops changed 13.30 -> 13.69 frames/s): wait a frame when a layer turns off.
* **More buffers help only if a trace shows time waiting** for a free buffer or VBL.

## Sound and memory

* **Sound costs ~2 ticks and ~2 pictures a second** (Gun.Smoke, 1943, Black Tiger; capsnd ~9k a tick); Bubble Bobble
  8-9% of the CPU; Kung-Fu Master 27.1 vs 29.5 pictures/s without it; Pooyan 47.4 -> 43.5; Hyper Sports 93% / 34.6 ->
  85% / 26.9; Gyruss's sound driver is 39% of its logic.  Dead end: Commando's music mix cache (no hits).
* **A smaller layout can be slower on the bus** (1943's front_map as words: 1.5-3% fewer frames in Hatari).
* **Generated code is large for big sprite sets** (Gun.Smoke's 2008 shapes x 16 shifts would take 2.85 MB): budget it
  by coverage (above), or stream prepared data from the hard disk (`sprite-preparation.md`, "Memory").

## Biggest remaining costs (gathered 2026-11-07)

Parallax recompositions (Trojan's far background 22% of play pictures, Moon Patrol's mountains, 1943's sea,
Splatterhouse stage 2's wall, Mr. Do!'s title stripes ~180k of a 263k picture), star layers (Galaga '88 37.5%, Galaga),
Gauntlet's shadows (23% of a heavy picture) and title fades (~260 objects re-baked a picture), 1943's full-band redraws
when the scroll alternates every tick (15% of its picture cycles), stage-change re-bakes (1942: 1-2.4M cycles), the
logic in R-Type (30-46% of every stage), Bubble Bobble, Double Dragon, Gyruss and the Namco System 1 ports, sound
drivers (Gyruss 39% of its logic, Track & Field 15k of 35k).

## Which port uses what (2026-11-07)

Rates are the latest Hatari figures in each README (logic as % of the arcade's rate, pictures a second; the setup
differs: recorded play where there is one); "-" = not used, "n/a" = not applicable.  Musashi-only results of the
2026-11-02 audit are not in the rates (1942, 1943, Black Tiger, Gun.Smoke, Track & Field, Hyper Sports, Galaga '88 have
not been re-measured in Hatari since).

**Logic**

| Port | Rate (Hatari) | Window guards | Leaves in place | Flag summaries / fast forms | Natives | Writer marks | Idle flags |
|---|---|---|---|---|---|---|---|
| Donkey Kong, DK Junior | 83% (one round a VBL) / 50 | n/a | - | n/a | - | - (compare) | n/a (VBL-locked) |
| Dig Dug | 82% (one round a VBL) / 32.6 scripted play (17.9-49) | n/a | 32 + rst + jumps | n/a | sub CPU sprite copy, 53XX/51XX event model | cells (movep rows) | n/a (VBL-locked) |
| Galaga | ~82% / 31.1 attract | n/a | - | n/a | 51XX read, sound boot | 32-byte blocks | n/a (VBL-locked) |
| Jail Break | ~67% (40.5 of 60 arcade frames; 3 of 4 pictures skipped while behind) / 15.4 pictures a second, AUTOPLAY, sound on | video_inline | 6809 inline_calls (the SN write) | call_summaries, fast_forms, ret_weights, fixed_slots | SN write (`$AF96`), sprite-RAM copy (`$9272`) | cells + tile column spans | kept |
| Pac-Man | 100% / 49.8 attract | n/a | 16 + rst + jumps | n/a | - | cells | kept |
| Pooyan | ~100% / 43.5 with sound | n/a | 16 | n/a | - | cells | kept |
| Mr. Do! | ~100% / 44-50 play | n/a | 16 | n/a | - | cells | kept |
| Time Pilot | 100% / 32.5 play | n/a | 16 | n/a | clouds, checksums | cells | kept |
| Bubble Bobble | 45% / 12.2 | sites | 48 | n/a | 3 + the MCU | VRAM pages | n/a (VBL-locked) |
| 1942 | 98% / 35.7 autoplay | 97 sites | 32 | n/a | `scan_native` | bg / fg | kept |
| 1943 | 85% / 7.9 autoplay | 883 sites | yes (61 sites) | n/a | task scan, MCU INT1 | blocks | kept |
| Commando | 100% / 27.0 play | flat ROM | yes | n/a | - | tiles, characters | kept |
| Black Tiger | 98% / 25.5 MARP | 2577, every `ldir` | - | n/a | - | `bg_note`, text rows, palette | **dropped** |
| Gun.Smoke | 92% / 25.8 play | 229 (IY too) | 188 sites | n/a | E0F8 trampoline | `fg_written` | kept |
| Trojan | 90% / 10.4 play | 135 sites | rst only | n/a | `nat_1e95` | 114 writers | ? |
| Kung-Fu Master | 93% / 33.6 play | flat | 16 + rst + jumps | n/a | - | tile rows | kept |
| Moon Patrol | 95% / 27.0 autoplay | flat | - | n/a | - | - (text compare 14k) | kept |
| Gyruss | 55% / 12.7 autoplay | n/a | yes (main, sound) | sub: summaries | sub: copies, scans, projections | cells | kept |
| Track & Field | 95% / 41.9 autoplay | n/a | sound: 6 | both | idle, sound | `video_inline` | n/a (idle native) |
| Mikie | 92% / 35.4 attract + first room (with sound) | n/a (flat) | n/a | both | idle, CWAI, sort, sprite copy, `inline_calls` emitter, sound | `video_inline` | n/a (idle native) |
| Hyper Sports | 85% / 26.9 autoplay | n/a | sound | both | idle, copies, division, sound | `video_inline` | n/a (idle native) |
| Double Dragon | 56% / 7.1 play (MAX_SKIPS 8) | n/a (bank contexts) | `inline_calls` (bank selectors) | both + `RET_WEIGHTS` | collision, sprites, banks, MCU | `*_written` | ? |
| Yie Ar Kung-Fu | 96% / 37.7 autoplay | flat | - | both | sprite RAM builder, idle | `st vram_w` / `vram_n` after coverage-recorded store sites, `static_write` for the sound ports | n/a (idle native) |
| Super Basketball | 83-90% / 19-31 autoplay (5,000-9,000 VBLs) | n/a (flat) | - | both | 2 (division, sprite list) | `video_inline` | n/a (idle native) |
| Gauntlet | 98-100% / 32.6 light play | n/a (native 68010) | n/a | n/a | n/a | playfield blocks, text | n/a |
| R-Type | 63% / 18.4 (stage 2, 14 MB) | n/a | leaf calls 12 | - | ~35 | 64-byte | ? |
| Mr. HELI | 41% / 2.0 play (14 MB) | n/a | on, none listed | - | - | 64-byte | ? |
| Splatterhouse | ~23% / 6.4 play | n/a | - | both | 4 | `tile_written` | ? |
| Galaga '88 | ~20% / 6.1 BENCH | n/a | - | both | - | `tile_marks` | ? |
| Dragon Spirit | 13% / 3.0 BENCH (14 MB) | n/a | - | both | 3 | `tile_marks` | ? |

**Pictures**

| Port | Scroll | Sprite kernel | Sprite damage / restore | Text | Colours (`colours.md`) |
|---|---|---|---|---|---|
| Donkey Kong, DK Junior | - | per-line generated code (`sprite_codegen`) | slot records, redrawn when cells touched | tiles | merged PROM set |
| Galaga | - (stars plotted) | the same | rectangles; a clear over blank cells | CPU masked bytes (`chars_over`) | explicit set |
| Pac-Man, Pooyan, Mr. Do!, Time Pilot | - | `sprite_programs` | rectangles (Pac-Man), drawn lines (the rest), from a clean screen | tiles | PROM exact (Pac-Man), default fitter flat |
| Bubble Bobble | - (static columns) | cached unshifted, a row loop (151 cycles a row) | 16 x 4 blocks from the static image | tiles | fitted per scenario |
| 1942 | V (768-line ring) | `spritegen` | rectangles from the clean ring | CPU 16-pixel chunks | per bank |
| 1943 | V (twin lines, back layer) | `spritegen` | twin lines; front layer redrawn as damage | `movep` | fitted |
| Commando | V (twin lines) | `spritegen` + per-slot cache | opaque rows from the twins | `movep` cell list | checker pairs |
| Black Tiger | H + V | a stream interpreter (~107 a row) | cells + rectangles from clean | OP 3 pieces | checker pairs |
| Gun.Smoke | V + H (D802) | `spritegen` | opaque rows + merge, from the twins | OP 3 pieces | checker pairs |
| Trojan | H + V | a stream interpreter (~60 a row) | saved words | character pairs | fitted flat |
| Kung-Fu Master | H | `sprite_programs` (streams) | rectangles from clean, blank cells skipped | tiles; panel image | per floor |
| Moon Patrol | - (layers per line) | a row loop | dirty 16-pixel groups redrawn | `movep` panel; pieces | PROM per picture |
| Gyruss | - | `sprite_programs` | drawn lines from clean | tiles | default fitter flat |
| Track & Field, Hyper Sports | per row | `sprite_programs` | sprite-only rows: their groups | tiles | default fitter flat |
| Mikie | - | `sprite_programs` (key tables, row table per Y) | drawn lines from clean | tiles | PROM (4096 pens fitted to 16) |
| Double Dragon | H | a row loop, rows sorted by mask | cells invalidated | pairs, fills | checker pairs |
| Super Basketball | H, recomposed (hardware scroll tried: exact, slower) | `sprite_programs` (348 shapes, per-slot cache) | sprite-only rows and changed cells | tiles | default fitter flat |
| Gauntlet | H + V (torus) | baked 32-pixel strips, a pass a row | rectangles from clean | runs; CPU masks for transparent ones | checker pairs + player colours |
| R-Type | H (twin columns) | `sprite_programs` (streams) | contour from clean; clears over black | status bar image | checker pairs per scene |
| Mr. HELI | fine H (`m72render`) | per-code line routines | rows | **AND + OR (to convert)** | scene palettes |
| Splatterhouse | H (twin columns) | converted per colour, a pass a line | rectangles from the twins | bar images | chooser per scene |
| Galaga '88 | - (fixed buffers) | a pass a line (X count 3) | rectangles from clean | composed into cells | chooser per scene |
| Dragon Spirit | H + V (twin lines and columns) | Galaga '88's | row spans | OP 3 passes per fine shift | chooser + flash |

## Techniques that look applicable elsewhere (2026-11-07)

Found by comparing the ports' documented methods; none is measured yet.  Each needs the usual proof: exact in the
port's tests, faster in CPU plus Blitter cycles, then in Hatari.  Ordered roughly by expected gain for the effort.

**Correctness first**
* **1942 and 1943: guard `(iy+d)` window reads.**  Their gens match `(a6,dN.w)` only; Gun.Smoke's fix (match
  `(a6,a2.w)`, compare a copy, `storing`) applies.  Check whether any of their window sites reads through IY.
* **1943, Gun.Smoke and the other banked ports: guard every block copy** (Black Tiger's MARP finding: `block_win` at
  coverage sites only misses copies like `$AC71`).
* **Mr. HELI's foreground: OP 3 copy passes** instead of AND + OR (mandatory, `AGENTS.md`).

**Logic**
* **Drop the flags at idle hooks** (Black Tiger -2.5%): 1942, 1943, Commando (`8001`), Gun.Smoke (`00CE`), Pac-Man,
  Pooyan, Mr. Do!, Time Pilot, Kung-Fu Master, Moon Patrol, Gyruss (`05F7`) - wherever the interrupt handler reads no
  flags.
* **Leaves in place** (-1.4..-3.5%): Black Tiger, Trojan (rst only so far), Galaga (its logic is the limit), Moon
  Patrol, Donkey Kong; the 6809 ports' `inline_calls` for small leaves (Splatterhouse: an RTS ~72 cycles, an indirect
  JSR ~130; Double Dragon: a third of its 127k translated cycles are calls and returns).
* **The Capcom task kernel's scan native** (1943's `nat_scan`, -5.2%): Black Tiger and Gun.Smoke run the same kernel
  (table at `EF80`, idle at `00D4` / `00CE`).
* **Per-call flag summaries for the V30** (R-Type, Mr. HELI): all 50 direct leaf callers of R-Type's later-native study
  need no P / A flags, but the liveness is caller-conservative.
* **R-Type's natives for Mr. HELI** (the same board and compiler): the tile probes (`nat_fgtile` / `nat_bgtile`,
  `nat_h89b0`) for its object handler `06400` (15.2%), `nat_objloop` (7.1%), the SPRITE_LIST emitters and the unrolled
  DMA copy (3.2%), the guarded bulk fills (`nat_nc_*`, REP STMW 4%), FADE_SNAP.
* **Profile, then natives**: Pooyan (its idle pass calls a ROM check at `$0254`: Time Pilot answers its own with
  constant natives), Mr. Do! (the flood fill `$54EC` / `$558E` / `$5647`), Galaga (the sub CPU's enemy paths, 45k),
  Galaga '88 (none yet; Dragon Spirit's gave -16%), Track & Field (Hyper Sports' `snd_tick` / `snd_note`: its sound is
  15k of 35k).
* **The idle-hook schedule for Donkey Kong and DK Junior**: both run one round a VBL (5/6 of the arcade's speed) with
  35-44% of a frame used on average; Pac-Man's six-to-five schedule would give full speed (and a deterministic attract).
* **`fast_forms` for Gyruss's sub CPU** (it has `call_summaries` only).

**Pictures**
* **Writer marks instead of comparisons**: Donkey Kong / DK Junior (the whole tile map compared every frame), Moon
  Patrol's text RAM (14k; Kung-Fu Master's row marks, the same Irem family), Bubble Bobble's palette RAM (512 bytes
  compared every frame), Splatterhouse's palette checksum (~20k a picture) and Dragon Spirit's palette (Double Dragon's
  `pal_written`), 1942's character RAM (Commando's row marks), Trojan's full 336-cell key check (Black Tiger's
  `bg_note` entry list).
* **Damage only what was drawn**: Gun.Smoke's opaque-row damage and side-by-side merge for 1942, 1943 and Black Tiger;
  Time Pilot's drawn-lines damage for Pac-Man, Kung-Fu Master and Galaga; Commando's per-slot sprite cache for 1942 and
  Gun.Smoke (its per-part setup is 660-870 cycles); Dragon Spirit's row spans (one damage call a row) for
  Splatterhouse's rectangle lists (~19k).
* **Contour restores** (R-Type, -0.3..-5%) where rectangles are restored from a clean image: Gauntlet, Galaga '88, 1942,
  Kung-Fu Master, Splatterhouse.
* **`sprite_programs`**: Moon Patrol (row loop), Bubble Bobble (estimated 17k, ~10% of the median picture), Donkey Kong
  and DK Junior (their per-line code predates it; `AGENTS.md` asks for it for 16-pixel rows).  Not Black Tiger: measured
  -2.7% but +2.5 MB.
* **Skip the sprite latch copies of skipped pictures** (Commando, Gun.Smoke): 1943 copies 128 longs at every `C806`
  write.
* **Caches keyed by the colour mapping instead of flushed**: 1942's stage-change re-bakes (1-2.4M; Black Tiger keeps the
  last 8 mappings a colour, Trojan uses epochs; 1942 has 1 MB free); Gauntlet's title fade (~260 objects re-baked a
  picture: Bubble Bobble's stamps or R-Type's DEDICATED pens).
* **Spread big redraws over pictures** (Splatterhouse's `REN_BUDGET`: off-window dirty cells drawn later): Track & Field
  and Hyper Sports' screen changes (p10 22-23 pictures/s).
* **A HUD as its own image** (`BD_VSWITCH` / `REN_VSW`): Double Dragon (text ~190k, p90 pictures follow text changes),
  Dragon Spirit's text rows 0-15 / 264-287 where they are opaque bars.
* **Text as OP 3 pieces**: Gauntlet's transparent characters (now CPU pixel masks).
* **Dragon Spirit's per-layer tile shadow** for Galaga '88's bank-difference and star scans.
* **The twin window nearest the previous position at a wrap**: Kung-Fu Master's 512-pixel dips.

**Effects to put to the user** (drop or simplify, gameplay kept): Galaga '88's stars (`REN_NOSTARS`: 10.62 -> 16.10
frames/s), Moon Patrol's mountain parallax, Mr. Do!'s title and intermission stripe scroll, Trojan's far background,
1943's sea, Splatterhouse stage 2's wall, Gauntlet's shadows.

**Sound from another port**: Time Pilot <- Pooyan's `sndgen.py` + `sound.s` (the same board; ~21k cycles a frame, ~8% of
the pictures); the Namco System 1 ports <- Double Dragon's YM2151 recordings (`engine/opm.py` -> capsnd streams);
Commando's effects as tables in the shared capsnd for 1943, Gun.Smoke and Trojan.

**Colours**: the default fitter has not been tried in 1942, 1943, Trojan (a RAM-palette port like Black Tiger; level 5's
error 12.2), Kung-Fu Master, Bubble Bobble, Donkey Kong and DK Junior.

**Measuring**: no recorded-play bench yet in Pac-Man, Pooyan, Mr. Do!, Track & Field, Hyper Sports, Gyruss, Moon Patrol,
1942, 1943, Gauntlet and Galaga '88 (some have a `PLAY=1` mode without a recording).  `bench.sh` exists in 21 diverging
copies (46-102 lines; options `ROUNDS`, `PLAY`, `REPLAY`, `PLAYBACK`, `BENCH`, `PHASES`, `SOUND`, `AVI`, `MEM`, `EXTRA`):
a shared `tools/bench.sh` with per-port settings would make the figures comparable.

## History: the audit of 2026-11-02

All ports were checked against the checklist above (Musashi figures on recorded play or the ports' seeds).  What was
exact and faster was landed, one commit per port; Hatari confirmation of most figures is still open.  Landed: video RAM
stores inline (Hyper Sports, Track & Field); sprite-only rows restore their groups (Track & Field, Hyper Sports); text
redrawn only over redrawn cells (Double Dragon); bank maps by default (Galaga '88); stars plotted in the window scan that
finds them (Galaga -6.5..-8.4%); Gyruss's sound countdowns in place and its rst table as a direct table (logic -8%);
inline leaves in 1942, 1943, Gun.Smoke, Kung-Fu Master and Gyruss, larger ones in Bubble Bobble; `fast_forms` +
`call_summaries` in Galaga '88 and Splatterhouse; the idle-hook flag drop in Black Tiger; 1943's task-kernel native.
Dead ends: merging overlapping sprite restores, halftone restores without one-colour or periodic areas, interrupt-time
loops whose flags reach the interrupted code.
