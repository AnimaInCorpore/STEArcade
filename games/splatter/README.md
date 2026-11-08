# Splatterhouse (Namco, 1988) on the Atari STE

Atari STE port (4 MB) of the MAME set `splatter` (Namco System 1, `namco/namcos1.cpp`). The main and sub MC6809E
programs are translated to 68000 code (`engine/m6809x.py`, `tools/gen.py`, `src/core.s`) with natives, against the
reference board `engine/namcos1.py` (its renderer pixel-exact against MAME); the CUS64 MCU (HD63701) runs as native
68000 code (`src/mcu.s`); the sound CPU is not run (`splatter.s` only answers its handshakes) and the MCU's voice
starts (`mcu_start`) are not played. The picture (288 x 224 in a 320-pixel screen, twin columns, two palettes by line)
is exact against the reference; there is no sound. Status: Experimental / deferred (early implementation / reference
work); not registered in `port.py`, not released. The main gaps: no sound, and since 2026-11-02 the long lock-step
runs stop at a main CPU badpc because coverage pickles were lost. Latest speed: Hatari recorded play (4 MB,
2026-10-15) 13.80 arcade frames a second (23% of the arcade's 60.606 Hz), 6.40 pictures a second; Hatari BENCH
(arcade frames 600-1100, 2026-10-14) 15.33 arcade frames, 7.53 pictures a second; logic 117.2k Musashi cycles a frame
for the two CPUs (seed 5, 2026-11-02). Neither Hatari figure was taken again after the 2026-11-02 changes.

## Build and run

```sh
venv/bin/python games/splatter/tools/prepare.py       # checks splatter.zip (docs/rom_manifest.json), unpacks it
venv/bin/python games/splatter/ref/cover.py SEED FRAMES   # coverage -> build/splatter/cover_SEED.pkl
venv/bin/python games/splatter/tools/build.py         # run/splatter/SPLATTER.PRG (--sim: the Musashi test build; -D NAME=V)
venv/bin/python games/splatter/tools/logic_test.py FRAMES --seed N   # lock-step against the reference (--play: the recorded play)
venv/bin/python games/splatter/tools/render_test.py   # every picture against the reference (Tests and tools)
games/splatter/tools/bench.sh [TAG]                   # Hatari benchmark (Tests and tools)
```

ROM: the MAME set `splatter` (`assets/roms/splatter.zip`, unpacked to `assets/roms/extracted/splatter/`; build.py runs
prepare.py when it is missing). The port is not registered in `port.py` (no `tools/hatari.sh`, no release): start
`run/splatter/SPLATTER.PRG` in the pinned Hatari (STE, 4 MB) the way `bench.sh` does. Uncovered code writes CRASH.TXT.
Paths are relative to this folder; `engine/`, `tools/`, `port.py` and `docs/` at the top are the repository's.

## Controls

Arrows, space / Z attack, Alternate / X jump, 1 start, 5 / 6 coin, Esc quits (writes COUNTERS.BIN); joystick 1.

## State

* In Hatari the attract mode stops at an untranslated main CPU address after about 110 s (2026-11-07: CRASH.TXT
  "BADPC M PAGE 3FA PC 80DC"), part of the coverage gap below.
* Coverage gap (2026-11-02): `build/splatter` holds only `cover_1/4/5.pkl` (the seeds 6, 7, 11-17 and the play
  coverage are gone). `logic_test.py 9000 --play` (the recorded play) stops at frame 1482 at a main CPU badpc $4AE8
  and seed 15 at frame 527 at a main CPU badpc $2D08, both with and without the 2026-11-02 switches (seed 4: 2500
  frames identical). Regenerate the coverage (`ref/cover.py`, seeds 4-7, 11-17, the play) and rerun the long
  lock-step runs before trusting figures past stage 1.
* Logic before the loss: seeds 4, 5, 11-17 2500 frames identical (2026-10-14), the recorded play 9000 frames identical
  (2026-10-15); after the 2026-11-02 switches `logic_test.py 1300 --seed 5` identical.
* MCU: `tools/mcu_test.py` checks MCUNative (`tools/mcu.py`) against the board's HD63701, `tools/mcu68k_test.py`
  `src/mcu.s` against MCUNative.
* Picture exact (2026-10-12/13): play 1100 / 1100 pictures, attract 475 / 475, edges 218 / 218; stages 2-7 from
  stage-select captures (every 25th frame, ~90 pictures each); the BENCH states (601 pictures, both `--every 2`
  phases); also with `-D REN_NBUF=3`, `-D REN_DMG=6` (overflow path), with and without `TILE_FLAG`, `-D REN_ONEPAL=1`.
* Missing: sound (the sound CPU, the MCU's voices).
* Speed: ~2 VBLs a picture in play besides the logic; a new scene takes ~1/2 s of black pictures.
* Colours: a representative pen that does not fade like its colour's other pens (the HUD skulls stay white in a
  fade); colours appearing after the choice (stage 4's purple lightning, sprites of a new colour) map to the nearest
  existing colour until the next choice; stage 5's red scene leaves no teal for Rick.
* Not implemented in the renderer: the shadow sprite colour $7F (never used by Splatterhouse), the 16-sprites-per-line
  limit, the screen flip off (the game always flips).
* Memory: load size 4,034,040 bytes (2026-10-15), 27 KB free from the desktop. ~250 KB more could come from 4-bit
  characters with a palette per character (+50% conversion time).

## How it works

### The board and the reference

`tools/machine.py`: the reference board (`engine/namcos1.py`, MAME's scheduler) and the port's schedule: the vertical
blank, the MCU and the sound CPU on the board's scheduler, then the main CPU's IRQ and frame, then the sub CPU's.
`tools/snapshot.py` writes the start state; its 160 KB of vio is packed (`snapshot_vio.lz`, `engine/lz.py`: ~6 KB,
unpacked by `lz_unpack` at the start).

### Translation

`tools/gen.py` (m6809x) with `call_summaries` and `fast_forms` (as Hyper Sports and Double Dragon, 2026-11-02).
Computed jumps take their targets from the coverage and from `table_targets`: executed sites with fewer than two
targets seen are included, and direct jumps / calls of that code into the pages of a slot where the target is
plausible with all it reaches in its page (`plausible_tree`; Lessons, 2026-10-14). The translated tile RAM stores emit
`st tile_written` / `st tile_written_fix` (layers 0-3 / the fixed layers' words) and per-row fixed-layer flags
(`tile_fix_rows`): the writer marks the renderer reads.

### Natives

Hand-written 68000 code in place of translated 6809 routines (`src/natives.s`, `tools/gen.py` NATIVES; `NO_NATIVES=1`
builds the translation only); each leaves the registers, memory and stack bytes below S as the 6809 code does and
returns through the routine's own translated RTS / PULS. `tools/logic_test.py` (lock-step against the reference) is
their test. Sub CPU: the sprite list ($F4CF, `sub_spritelist` / `sl_core`) and one object's sprite parts ($F714,
`sub_sprites`). Main CPU (2026-10-13), the two largest self-contained routines of `tools/profile.py --dump` grouped by
call target:

* `$CA57` `main_mul16`: the word at X times the word at X+2 into X+6..9 (two passes of two MULs; 3 calls a frame,
  ~1800 cycles translated). Its `LDA -1,U; ADCA -1,U` doubles the byte below the partial sum: X+5 ends doubled.
* `$C5D5` + `$C630` `main_bgclass`: the background class under an object (slot 3's bank from the table at $C600, the
  map word, its count of the four thresholds at $C64B; 7.4 calls a frame, ~1100 -> ~770 cycles).

### MCU

The CUS64 (HD63701) runs as native 68000 code (`src/mcu.s`, the 68000 side of `tools/mcu.py` MCUNative). The same
model serves Galaga '88 and Dragon Spirit (the same ROM in all four Namco System 1 sets).

### Schedule

`src/splatter.s`: an arcade frame (MCU, main, sub), a picture every `PIC_EVERY` (2) arcade frames at most;
`MAX_BEHIND` 3. The game flickers some layers at 30 Hz (stage 1's lightning objects and stage 2's wall are layer 3,
enabled in every other frame): a due picture waits a frame (once) when a layer enabled in the frame before is off in
this one, so such layers are always shown (solid) and every build draws the same phase (Lessons, 2026-10-15). The
BENCH build writes the arcade frame of each picture (PICS.BIN).

### Picture

`src/render.s` draws the arcade picture (288 x 224, the player's view: MAME's screen turned by the cabinet's ROT180 with
the game's flip on) from the state in `vio`: the CUS116 palette RAM and its window registers, the CUS123 tile RAM and
control, the latched sprite list. `tools/assets.py` converts the graphics ROMs (`build/splatter/ren_*.bin`).

* **Screen**: 320 pixels wide, the picture at x 16-303; top and bottom borders opened (`engine/rt/borders.s`), the
  picture `PIC_TOP` lines down. The 16-pixel side bands show what the playfield has there (the arcade does not show
  it).
* **Buffers** (`REN_NBUF`, 2 by default, 3 possible): virtual screens of 1024 x 288 pixels (512 bytes a line; 32 guard
  lines above and below the picture for whole sprites). The scroll layers that share a scroll (the *group*: layers
  0-2 in play, their x registers differ by the hardware's offsets 4/2/1) are composed into it once per change: tilemap
  column u at buffer x u and u + 512 (*twin columns*), so the window (W .. W + 319, W = the group's x scroll - 16) is
  complete wherever it is and horizontal scrolling costs nothing but the video address and the fine scroll register.
  A change of the group's vertical scroll, members or priorities redraws the buffers (a new scene).
* **Group cells** (`ren_cell`): the members top first down to the first opaque one; one opaque member is converted
  directly (8bpp pens through the bank's c2p table, 44 cycles a pixel), several are merged by their masks; written
  into both twins of every buffer with `movep.l`, plus 3 priority bit planes (`ren_pri`) and per cell its highest and
  covering priorities. Changed cells come from a diff of the tile RAM with a copy: the window's columns every picture
  and a quarter of the rest in turn (exact: a column is diffed when it enters the window). Dirty cells in the window
  are drawn at once, others `REN_BUDGET` (12) a picture. With `TILE_FLAG` (on) tile RAM is compared only after a
  translated store set `tile_written` (the game changes it in ~4% of its frames); with `TILE_ROWS` (on) only the fixed
  layers' rows a writer marked are compared.
* **Sprites**: the list in arcade order from entry 0 up (the arcade draws from the last entry and the first drawn
  pixel wins, so the STE paints the other way round). Each (code, colour, sub-rectangle, flip x, palette) is converted
  once into a cache (`REN_POOL`, 192 KB, `REN_HASH` 4096 direct-mapped slots; per row the opaque mask and the 4 plane
  words plane by plane, so the Blitter's source runs on). The conversion reads the cell's box bytes directly: one
  unrolled step a byte of the row (`ren_cvf`, flip x `ren_cvb`; only the bytes inside the box run: an `rts` is put
  after the last one for the time of the image), each two table lookups by the byte * 16: the colour's pair table
  (4 KB: the pair's plane bits at each of the 4 positions in 8 pixels, `REN_PTS` (16) of them) and the mask table
  `ren_pm16` (the pair's mask bits at each of the 8 positions in 16 pixels). Drawn as OP 3 copy passes, one HOG pass
  a line (4 planes), flip y by drawing upwards: a row whose mask is the row before's leaves the Blitter as it is
  (destination, Y count, start: ~70 cycles); a new mask is shifted once into its three destination words and the pass
  covers only the words that are not 0 (END3 0: two words; END1 0: from the second word with FXSR; both: one word),
  so the Blitter skips the empty end words (~90 instead of 128 bus cycles a line).
* **Edges**: clipped at the group boundaries in the side bands nearest the picture's edges (the clip masks ANDed into
  the new mask's words: END mask 0 for the words outside, `ren_cl` / `ren_cr`), culled when wholly outside; top and
  bottom whole into the guard lines.
* **Palette lines**: an object drawn in one palette's lines (`ren_linesel`, across the HUD boundary) is drawn as the
  interval of those lines; only bar lines of a higher priority inside the range (not at its ends) need the
  line-by-line path.
* **Sprites behind a group layer** (Rick and the enemies behind the cage bars) leave those pixels out: in the cell rows
  with a group cell above the sprite (`ren_prio_rows`) each line's end masks lose the pixels whose group priority (the
  `ren_pri` planes) is above. Those pixels get the background from the twin column (`ren_pr_twin`) only when an object
  drawn before in this picture meets the sprite's rectangle (`ren_under`: this picture's damage list so far; the arcade
  composes the sprites first, so a hidden sprite pixel hides the sprites behind it too); else the buffer has the
  background there already. Two source words a row: a pass a line with code per priority (`.pr`); otherwise line by
  line (`ren_pri_line`), or drawn whole and *repaired* afterwards (`ren_repair`) when it lies over another object.
* **Overlays**: enabled layers 0-3 outside the group (layer 3: the flickering lightning and objects of stages 4 and 6)
  and the fixed layers' cells outside the HUD bars are drawn per picture as 8 x 8 images through the same sprite code,
  between the sprites by priority. Cells hidden by bars, wholly covered by group layers of higher priority, or opaque
  black under the whole group (the attract mode's backdrop) are skipped, and cells wholly outside the clip groups
  before their image is looked up. With `TILE_FLAG` layers 0-3 keep a bitmap of their non-empty cells (`ren_obm`,
  a row rebuilt when tile RAM was written since: `ren_tgen`), so a picture tests 5-6 bytes a visible row instead of
  37 words (stage 1's layer 3, on in every other frame: ~1000 words and ~60 blank cells of other codes a picture).
* **Fast rows** (stage 2's lightning wall: layer 3, priority 5, ~110-140 cells a picture): a row whose 8 lines are all
  playfield lines no bar hides, of a layer no group layer is above, draws its cells inside the clip groups straight
  from the cache (`ren_orow_draw`, the lookup inline; `ren_ocell_img`): an opaque cell in four passes, a plane each
  with its 8 lines (SXI = SYI = 8: Hatari steps a line's one source read with NFSR by SYI), others a pass a line
  (empty rows left out, a repeated mask keeps the end masks); a run of adjacent cells is one damage rectangle. Cells
  at a clip group's edge take the generic path.
* **Fixed layers 4/5**: rows of 36 opaque cells whose lowest priority is at least the group's form *bars* (the HUD:
  32 lines at the top, 32 at the bottom); they are a bar image (`ren_fi`, black side bands) copied into each buffer's
  bar lines at the window's position when the window moved (4 passes a run of lines, fine-shifted) or the lines were
  damaged. Sprites below a bar's priority skip its lines.
* **The HUD region from bar images** (`REN_VSW = 1` with borders.s' `BD_VSWITCH = 1`, on in splatter.s with `BD_HUD`,
  not with `REN_ONEPAL`): the HUD region's lines (the bars at the top and the bottom) are shown from a bar image per
  buffer (`ren_bi`, `FI_STRIDE` bytes a line, fine scroll 0) instead of the scrolled playfield: borders.s' HUD
  palette events load the video counter, the line width and the fine scroll at the bars' ends (render_vbl publishes
  `bd_vs_*`), so the bars are not copied when the window moves. An object's lines in the region are drawn into the
  bar image (as the HUD palette's part, `ren_linesel` 2: screen x, clipped at groups 1 and 19) and put back from
  `ren_fi` (damage words | $4000); a buffer's bar image is copied from `ren_fi` when it or the region changed. Bar
  lines between the bars are still copied into the buffer. The mode is per picture (`ren_vsw`): only when borders.s'
  plan keeps the switch lines exact (htop 0 or >= 3, 3 lines between the bars, the bottom bar's line not within 3
  lines of the bottom border's) and the C116 window is the whole picture; a buffer that changes mode gets all its bar
  lines again. An object is drawn in the HUD region only when a bar line it covers shows it (`ren_hud_vis`, a line a
  fixed row). The DEBUG counters show no late Timer B event (`bd_late_*` 0, one fallback at the start), screenshots
  while scrolling show clean bar edges.
* **Damage**: what a picture draws (sprites, overlay cells, the clip window) goes into the buffer's list (adjacent
  rectangles merged, `REN_DMG` 400 a buffer) and is copied back from the twin columns at the buffer's next turn (12
  words a line at most; overflow: the whole window). In bar lines the rectangle is copied from the bar image instead
  (words | $8000 in the list: a pass a plane, the window's fine scroll as skew with FXSR; only when the window and the
  bar image are as they were, else ren_bars copies all bar lines anyway): a sprite over the HUD does not cost whole
  bar lines. Clean-image restores and no-source fills use the shared dispatch paths (2026-10-19).
* **C116 window**: outside it black rectangles (attract mode's iris).
* **Blitter**: every pass HOG and at most 256 bus cycles (`blit_go` of `engine/rt/borders.s` for the restores, bars and
  fills; a sprite line is 3 words x 4 planes). `BLIT_STATS=256` on the test lists no longer pass and none without HOG.

### Colours

The arcade's colours live in palette RAM (they change per stage, fade by -32 a channel a step, and cycle tile banks
for lightning), 140-310 pens on screen. The renderer maps pens to STE indices at run time (`ren_palette_of`; not part
of the 2026-11-05 default-fitter rollout, [colours.md](../../docs/colours.md#what-each-port-uses)):

* **Per scene** (`ren_cluster`): samples of the screen (a pixel per group cell, fixed cells, overlay cells, 16 per
  sprite) give a histogram of the distinct colours (4 bits a channel). Each colour weighs 16 x the root of its count,
  four times that when a sprite uses it; a median cut (widest Oklab axis x root of the weight, weighted median) seeds
  15 centres, 12 rounds of k-means (L1 in byte Oklab) refine them. Index 0 is black. A pen's index is the nearest
  centre of its colour (`ren_pen_index`, a 4096-entry table filled on demand); the c2p tables of tile banks and sprite
  colours and the cache are made from it.
* **Two palettes**: the HUD region (the bar lines at the top and the bottom) gets its own 15 colours from its own
  samples; the playfield's are chosen without them. The main program changes the palette at the region's lines
  (below); `-D REN_ONEPAL=1` gives one palette for all lines (no raster change, worse colours).
* **Fades** without redrawing: the STE colour of an index is the current colour of a representative pen (the colour
  nearest the centre), so the STE palette fades with palette RAM. The mapping uses the palette as it was when the
  colours were chosen (`ren_palsnap`). A tile bank change of a group member alone (the intro's lightning) is a
  palette change too: the cells keep the drawn bank, the representatives take the current bank's colours.
* **When**: a new scene (the group changed, or 300 cells of the window changed, or the HUD region) shows black until
  the palette rests for 2 pictures (at most 6), then the colours are chosen and everything is drawn again. A palette
  that settles on other colours (8 pictures without a change) is chosen again too; every 128 pictures a light check of
  the error can trigger it.

Measured (render_test, Oklab distance of the STE colour to the arcade's, mean over the picture; saturated: pixels with
chroma > 0.08): the first count-weighted median cut 0.0404 in play, 0.0394 in the attract mode; with the method above
0.0324 (saturated 0.042) in play and 0.040 (0.056) in the attract mode; stages 3 / 5 / 7 (stage-select starts,
pictures 100 frames apart) 0.028 / 0.027 / 0.043. One palette for the whole picture (`REN_ONEPAL`): 0.047 in play.

### Interface for the main program (`src/splatter.s`)

* include `borders.s` (with `borders_blit_go` and `borders_vars`) and `render.s`; `render.s` needs the label `vio`.
* `render_init` once, after vio holds a state. All registers kept.
* `render_frame` once per picture, between the game's frames (e.g. in the main loop after the arcade frame); keeps all
  registers. It draws into a buffer that is neither shown nor the one shown just before (the Shifter scans the old
  one once more), publishes it (`ren_ready` = buffer + 1, one byte store) and returns; with no buffer free it returns
  at once (`ren_skipped` counts). A long picture (a new scene: up to ~25M cycles; usually 0.25-0.5M) is interrupted by
  the VBLs as usual: the game runs on, the picture comes later.
* `render_vbl` in every VBL (all registers kept): shows a published buffer (video base and counter, `$ffff8265` fine
  scroll, `$ffff820f` line width; it subtracts `PIC_TOP` lines when `PIC_TOP` is defined), copies its palettes to
  `ren_vbl_pal` (the playfield) and `ren_vbl_hpal` (the HUD) and its HUD lines to `ren_vbl_htop` / `ren_vbl_hbot`
  (picture lines 0 .. htop - 1 and hbot .. 223 use the HUD palette; htop = 0 and hbot = 224 when there are none).
  A VBL without a new picture frees the buffer shown before.
* Palette timing (Timer B, borders.s): `ren_vbl_hpal` from the picture's first line when htop > 0 (else
  `ren_vbl_pal`), `ren_vbl_pal` from line htop, `ren_vbl_hpal` from line hbot (< 224), black after line 223.
  borders.s has the on and off events (`BD_PALETTE`, `shown_pal`, `PIC_TOP`, `PIC_LINES` = 224); the two switches at
  htop and hbot use its `BD_HUD` Timer B chain, enabled by default in `splatter.s`.

### Memory

The renderer harness without vio (2026-10-12, then with a 128 KB cache and 32 pair tables): text 16 KB, data 1.59 MB
(characters 768 KB, masks 128 KB, sprite boxes 595 KB, tables), bss 0.84 MB (2 buffers 295 KB, cache, pair tables,
priority planes 57 KB, bar image 38 KB, tile copy 32 KB, ...): 2.45 MB, with the program's ~1.2 MB (code, 512 KB ROM
image, vio, the snapshot). Since 2026-10-15: a 192 KB cache, 16 pair tables, the packed start snapshot; load size
4,034,040 bytes (Lessons, 2026-10-15).

### Sound

Not implemented: the sound CPU is not run (`splatter.s` answers its handshakes), the MCU's voice starts (`mcu_start`)
are not played.

## Speed

| date | setup | arcade frames/s | % of 60.606 Hz | pictures/s | Musashi |
|---|---|---|---|---|---|
| 2026-10-15 | Hatari 4 MB, recorded play (`bench.sh PLAY=1`), phase steered | 13.80 | 23% | 6.40 | render 5.56 VBLs a picture |
| 2026-10-14 | Hatari 4 MB, BENCH (arcade frames 600-1100) | 15.33 | 25% | 7.53 | logic 1.162 VBLs an arcade frame |
| 2026-11-02 | Musashi, seed 5 | | | | logic 117.2k a frame for the two CPUs |
| 2026-10-15 | Musashi, recorded play | | | | stage 1 (frames 2000-2500) 653k a picture, stage 2 (4000-4500) 1.07M |

Cycles a picture on Musashi in the play states (CPU + Blitter bus cycles, 2026-10-13; in parentheses 2026-10-12):

| | median | 10% | 90% | max (new scene) |
|---|---|---|---|---|
| play (1100 pictures) | 448k (488k) | 351k (391k) | 608k (845k) | 25M |
| play, `TILE_FLAG` | 261k (346k) | 208k (248k) | 462k (710k) | 25M |
| play, `TILE_FLAG`, `--every 2`, phase 0 (layer 3 off) | 251k (298k) | 197k (242k) | 454k (719k) | 25M |
| play, `TILE_FLAG`, `--every 2`, phase 1 (layer 3 on) | 348k (486k) | 228k (342k) | 606k (865k) | 25M |
| attract (475) | 220k (234k) | 219k (224k) | 750k (849k) | 27M |
| attract, `TILE_FLAG` | 150k (169k) | 149k (154k) | 684k (779k) | 26M |

In play (`TILE_FLAG`, the mean over 1100 pictures without new scenes: ~318k): the sprite and overlay draws ~98k
(their setup ~2k a draw, ~16-20 draws; lines ~70 cycles CPU + ~90 Blitter when the mask repeats, ~200 + ~90 when
not), the restores ~27k (mostly Blitter), the palette ~20k, the damage lists ~19k, the repairs ~18k, the sprite list
~17k, the overlay layers ~17k, the group cells ~12k, conversions of new sprite images ~13k (~10-15k a 32 x 32 image;
before: ~60-70k). A new scene: ~1200 window cells (~5-7k each), the samples and k-means (~3-5M), the bar image. The
BENCH game costs more a picture than the play states: it scrolls and has more enemies (~340 sprite lines and ~80
behind the cage a picture), and the fixed layers are compared in every picture (the HUD writers set the flag every
frame).

What made it faster, newest first:

* 2026-11-02: `call_summaries` and `fast_forms` in `tools/gen.py`: `logic_test.py 1300 --seed 5` identical, 126.2k ->
  117.2k cycles a frame for the two CPUs (-7.1%; `call_summaries` alone 119.5k in [the 2026-11-02
  audit](../../docs/speed.md#history-the-audit-of-2026-11-02)). The NFSR fix (769c6fb) the same day.
* 2026-10-19: clean-image restores and no-source fills through specialized shared dispatch paths: the full-picture
  effect is small ([measurements](../../docs/virtual-scroll-performance.md#implementation-results)).
* 2026-10-15: the hidden pixels of a sprite behind a group layer put back only over an object drawn before
  (`ren_under`): stage 1 (frames 2000-2500) 697k -> 653k a picture; Hatari play (phase steered, both builds): 13.64 ->
  13.80 arcade frames/s, 6.26 -> 6.40 pictures/s, render 5.71 -> 5.56 VBLs a picture.
* 2026-10-15: overlay fast rows and a 192 KB cache, 16 pair tables, 4096 hash slots (the pool had been flushed every
  ~33 pictures, the direct-mapped hash evicted the wall's cells): stage 2's wall (frames 3000-4000) ~1.8M -> 1.04M
  cycles a picture with the fast rows; frames 4000-4500 1.21M -> 1.07M with the cache. Hatari play 10.49 -> 13.80
  arcade frames/s, 4.87 -> 6.29 pictures/s, render 8.03 -> 5.68 VBLs a picture.
* 2026-10-13/14: the main CPU natives `main_mul16` / `main_bgclass`: Musashi (`profile.py --start 1200 --frames 400`,
  seed 5 play) 132.4k -> 126.7k cycles a frame for the two CPUs (-4.3%); Hatari (BENCH=1, arcade frames 600-1100, the
  same sources built back to back) logic 1.232 -> 1.162 VBLs an arcade frame, 15.06 -> 15.33 arcade frames/s, 7.46 ->
  7.53 pictures/s.
* 2026-10-13 (1f3f24d): `TILE_ROWS`: only the fixed-layer rows the writers marked are compared (the HUD writers mark
  rows 1, 2 and 25 each frame; all rows in the 11-26% of frames in which a generic copy runs): BENCH Musashi median
  572k -> 547k a picture, Hatari 13.96 -> 14.21 arcade frames/s, the fixed phase 64 -> 34 VBLs.
* 2026-10-13: the HUD region from bar images (`REN_VSW`): BENCH states (`TILE_FLAG`, median) 582k -> 538k a picture;
  Hatari (`dbench`, `REN_PHASES`, the same sources built back to back) 14.52 -> 14.88 arcade frames/s, 7.19 -> 7.43
  pictures/s, render 1111 -> 1048 VBLs, bars 103 -> 18 VBLs (66k -> 12k a picture).
* 2026-10-13: the renderer's speed-up (the conversions from the box bytes, the Blitter left as it is for repeated
  masks, the skipped empty end words; the table above): BENCH states (`--bench 500-1100 --every 2`, `TILE_FLAG`;
  median / mean without new scenes) phase 0 650k / 656k -> 593k / 611k, phase 1 672k / 694k -> 616k / 651k. Hatari
  `dbench` with `REN_PHASES` (frames 600-1100, VBLs per phase, k cycles a picture): 13.28 -> 13.96 arcade frames/s,
  6.63 -> 6.96 pictures/s; objects 748 -> 666 VBLs (479k -> 426k), restore 112 -> 101, bars 96 -> 102, fixed 69 -> 64,
  palette 46 -> 35, bg 73 -> 71. An earlier step of it: Hatari BENCH 12.38 -> 13.30 arcade frames/s, 6.18 -> 6.64
  pictures/s.

Measured, not kept:

* The full stefastbobs2 method as a prototype (2026-10-13, `-D REN_GEN=1`, removed again): code generated per (image,
  skew, flip y) on first use (a pass a row, end masks / X count / Y increment written as constants when they change,
  no per-line decisions; `REN_GSORT`: rows grouped by equal masks). Exact, but the BENCH game makes ~6 new (image,
  skew, flip y) a picture (hits 57% with a 96 KB code pool; 75% with 2 MB): generating costs ~22k each, ~134k a
  picture, against ~42k saved in the draws. Musashi BENCH mean 612k -> 714k (row order), grouped order slower again;
  Hatari 13.96 -> 12.54 arcade frames/s, objects 426k -> 552k a picture. It would need ~0.5 MB of code to reach its
  best hit rate and still pay ~80k a picture for the generation.
* The stefastbobs2 reordered source (rows of equal masks grouped across the image, the destination from a table of
  row offsets). Measured over 400 play pictures: 94213 sprite rows drawn, 58178 mask changes in row order, 49777
  groups of equal masks: grouping saves ~21 mask changes a picture (~2.5k cycles), less than grouping costs in the
  conversions (~5-10k an image, ~0.5 images a picture), and the rows left out at bars and palette boundaries would need
  the line-by-line path. Row order with the Blitter left as it is for repeated masks keeps most of the gain (38% of
  the rows).
* Sprites that stay in the buffer (2026-10-15; a record per simple draw; kept when nothing put back or drawn before
  meets it, no group cell under it drawn since; a coarse map of 8-line bands and groups): exact, but in stage 1 only
  ~2.6 sprites a picture stayed (the unchanged ones lie near the HUD lines or under moving sprites), ~20k saved against
  ~160k for the bookkeeping.

Open: the draw setup (~1-2k a sprite or overlay cell: many memory variables), the restores (Blitter), the priority
rows' scan, the palette's per-picture checksum and representatives (~20k), the damage lists. In the logic: the sprite
list natives (~23% of the logic, ~200 cycles a part), the object loops ($CD9A, $AE09, $CCDF, $D5D7: 32 slots each, a
handler per object through `JSR [A,X]`), calls and returns (RTS ~72 cycles, indirect JSR ~130).

Techniques other ports use that may apply:
[speed.md](../../docs/speed.md#techniques-that-look-applicable-elsewhere-2026-11-07).

## Tests and tools

* `tools/logic_test.py FRAMES --seed N` (after `tools/build.py --sim`): lock-step against the reference; `--play` the
  recorded play's inputs and cheats.
* `tools/mcu_test.py`, `tools/mcu68k_test.py`: the MCU model against the board's HD63701, `src/mcu.s` against the
  model.
* `tools/profile.py [--start F --frames N] [--dump]`: Musashi cycles of the logic by routine.
* `tools/play_search.py`: the recorded play (a playbot on the reference, lives and health cheats; 9000 frames from the
  start into stage 2), replayed by the program with `-D PLAYBACK=1`.
* `tools/render_test.py [--edges] [--play A-B] [--attract A-B] [--png f,..] [-D NAME=V]`: the harness
  (`build/splatter/ren_harness.s`: render.s, borders.s' blit_go, vio) runs on Musashi with the simulator's Blitter.
  States from the reference (`tools/machine.py`, the inputs of `logic_test.py --seed 5`: attract, coin, start, random
  play; seed 1: the attract mode) are recorded once into `build/splatter/render_states.pkl` (1100 consecutive frames
  of play from frame 300, 475 attract frames every 4th). Each picture is read back as the Shifter shows it (the
  published address, fine scroll, the two palettes by line; with `REN_VSW` the HUD region's lines from the shown
  buffer's bar image, 168 bytes a line, fine scroll 0) and every pixel's index must be the renderer's mapping of the
  reference's pen (`engine/namcos1.py` `render_raw`; evaluated in Python from the renderer's centres and palette
  snapshot; black pictures of a new scene must have black palettes).
  * `--edges`: a 32 x 32 and a 16 x 16 sprite across both edges, all 16 fine positions with all flips, the top and
    bottom guards, lines across a 64 KB boundary of each buffer, at six window positions (aligned and not): exact, and
    no sprite pixel outside the clip groups in the side bands (the check bites: `-D REN_NOCLIP=1` fails).
  * `--png`: STE | reference into `build/splatter/render_*.png`.
  * `--every 2 --phase 0|1`: every other play frame (the program's `PIC_EVERY`; stage 1 enables layer 3 in every other
    frame, so the two phases cost differently).
  * `--bench 500-1100`: the states of splatter.s' BENCH game (its scripted inputs: coin at frame 60, start at 140,
    from 400 right with an attack 4 frames in 40; `build/splatter/render_bench.pkl`, recorded once): stage 1 scrolling
    with more enemies, the picture Hatari's `dbench` measures. The fixed layers' flag is set in every frame there (the
    program's HUD writers run every frame), so their diff runs in every picture as in the program (with `TILE_ROWS`,
    on in splatter.s, only the rows marked; render_test simulates the rows).
  * `--rec A-B`: the recorded play's states; use the phase the program draws (`--rec 3000-3500` = frames after the
    wall's on frames; `2999-...` the off phase, ~350k a picture in stage 2).
  * `--profile` (e.g. `--bench 560-1100 --every 2 --profile`) sums CPU + Blitter cycles by routine (`PROF_FOCUS=label`:
    that routine's instructions).
* `tools/bench.sh [TAG]`: splatter.s' BENCH game (arcade frames 600-1100) in `run/splatter_TAG` with Hatari started
  there (no pkill); `PHASES=1` adds render.s' phase VBLs, `PLAY=1` the recorded play with a RATE.BIN timeline,
  `EXTRA="-D BENCH_NOPIC=1"` the logic alone. Hatari's CPU profiler (`--parse`, a breakpoint on bench_inputs at frame
  600 starts it) agrees with Musashi per routine within ~5-10% (the bus's 4-cycle rounding); the interrupts (Timer B,
  the border chain, the HUD plan) take ~6% of the time.
* `tools/memfree.sh` (repository): what a 4 MB STE gives a program started from the desktop.
* `ref/mame_cmp_splatter.py [frames...]`: the reference renderer against MAME's picture.

## Lessons

### 2026-10-15: pictures lock to a flickering layer's phase

With `PIC_EVERY` 2 the program's pictures lock to one phase of the 30 Hz layers for a whole play: the committed build
drew stage 2's wall in every picture, a timing change of a few cycles made another build draw none of it (Hatari "20
frames/s", the objects phase 2.5 times cheaper: phase luck, not work saved). Since then a due picture waits a frame
(Schedule). Compare renderers in Hatari only with that, and in `render_test.py --rec` use the phase the program draws.

### 2026-10-15: the program outgrew 4 MB

The program (text + data + BSS, `build/splatter/splatter.map`) had grown to 4.17 MB, more than a 4 MB STE gives a
program started from the desktop (4,061,212 bytes, `tools/memfree.sh`; Hatari: "Program too large"). The start
snapshot's 160 KB of vio packed (`snapshot_vio.lz`): 4.01 MB, 51 KB free; with the larger cache of the same day
4,034,040 bytes (27 KB free).

### 2026-10-14: jump tables with one seen target

Seeds 11, 13, 17 stopped at a main CPU badpc (frames 1009, 1769, 587) with and without the natives, seed 14 at frame
644 at $883F `JSR [B,X]` (entry $2A, $887C: the coverage had seen one target there) and behind it at $887C's
`JSR $D3F4` (slot 6, pages 3B4 and 3FE). `table_targets` now also takes executed sites with fewer than two targets
seen, and the plausible direct jumps / calls of that code (`plausible_tree`): seeds 4, 5, 11-17 2500 frames identical.

### 2026-10-13: Hatari rates move with the picture phase

The rate depends on which arcade frames get a picture (layer 3's phase): the same renderer with ~4000 cycles of nops at
render_frame's start gave 13.69 arcade frames/s, a variant ~1k cycles a picture slower 13.75. Read changes of a few %
with care (and see 2026-10-15 above).

## Verification

Lock-step runs (seeds and the recorded play, see State: the long runs need the coverage regenerated), the MCU tests,
`render_test.py` on play, attract, BENCH, recorded-play states and stage-select captures of stages 2-7. The recorded
play (`tools/play_search.py`, with lives and health cheats) reaches stage 2 in 9000 frames; it is a speed and coverage
fixture, not a playthrough. No playtest or MARP replay yet.

Full-game verification follows the [status policy](../../docs/port-status.md); nothing here claims a complete playthrough.
