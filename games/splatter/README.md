# Splatterhouse

Atari STE port (4 MB) of the MAME set `splatter` (Namco System 1): the main and sub MC6809E programs translated to
68000 code (`engine/m6809x.py`, `tools/gen.py`, `src/core.s`), the reference board `engine/namcos1.py` (its renderer
pixel-exact against MAME), and the STE renderer below.  Work in progress.

## Renderer

`src/render.s` draws the arcade picture (288 x 224, the player's view: MAME's screen turned by the cabinet's ROT180 with
the game's flip on) from the state in `vio`: the CUS116 palette RAM and its window registers, the CUS123 tile RAM and
control, the latched sprite list.  `tools/assets.py` converts the graphics ROMs (`build/splatter/ren_*.bin`),
`tools/render_test.py` checks every picture against `engine/namcos1.py` `render_raw`.

### Design

* **Screen**: 320 pixels wide, the picture at x 16-303; top and bottom borders opened (`engine/rt/borders.s`), the
  picture `PIC_TOP` lines down.  The 16-pixel side bands show what the playfield has there (the arcade does not show it).
* **Buffers** (`REN_NBUF`, 2 by default, 3 possible): virtual screens of 1024 x 288 pixels (512 bytes a line; 32 guard
  lines above and below the picture for whole sprites).  The scroll layers that share a scroll (the *group*: layers
  0-2 in play, their x registers differ by the hardware's offsets 4/2/1) are composed into it once per change: tilemap
  column u at buffer x u and u + 512 (*twin columns*), so the window (W .. W + 319, W = the group's x scroll - 16) is
  complete wherever it is and horizontal scrolling costs nothing but the video address and the fine scroll register.
  A change of the group's vertical scroll, members or priorities redraws the buffers (a new scene).
* **Group cells** (`ren_cell`): the members top first down to the first opaque one; one opaque member is converted
  directly (8bpp pens through the bank's c2p table, 44 cycles a pixel), several are merged by their masks; written
  into both twins of every buffer with `movep.l`, plus 3 priority bit planes (`ren_pri`) and per cell its highest and
  covering priorities.  Changed cells come from a diff of the tile RAM with a copy: the window's columns every picture
  and a quarter of the rest in turn (exact: a column is diffed when it enters the window).  Dirty cells in the window
  are drawn at once, others `REN_BUDGET` a picture.
* **Sprites**: the list in arcade order from entry 0 up (the arcade draws from the last entry and the first drawn pixel
  wins, so the STE paints the other way round).  Each (code, colour, sub-rectangle, flip x, palette) is converted once
  into a cache (`REN_POOL`, 128 KB; per row the opaque mask and the 4 plane words plane by plane, so the Blitter's
  source runs on).  The conversion reads the cell's box bytes directly: one unrolled step a byte of the row
  (`ren_cvf`, flip x `ren_cvb`; only the bytes inside the box run: an `rts` is put after the last one for the time of
  the image), each two table lookups by the byte * 16: the colour's pair table (4 KB: the pair's plane bits at each of
  the 4 positions in 8 pixels, `REN_PTS` of them) and the mask table `ren_pm16` (the pair's mask bits at each of the
  8 positions in 16 pixels).  Drawn one HOG pass a line (4 planes), flip y by drawing upwards: a row whose mask is
  the row before's leaves the Blitter as it is (destination, Y count, start: ~70 cycles); a new mask is shifted once
  into its three destination words and the pass covers only the words that are not 0 (END3 0: two words; END1 0:
  from the second word with FXSR; both: one word), so the Blitter skips the empty end words (~90 instead of 128 bus
  cycles a line).  Clipped at the group boundaries in the side bands nearest the picture's edges (the clip masks
  ANDed into the new mask's words: END mask 0 for the words outside, `ren_cl`/`ren_cr`), culled when wholly outside;
  top and bottom whole into the guard lines.  An object drawn in one palette's lines (`ren_linesel`, across the HUD
  boundary) is drawn as the interval of those lines; only bar lines of a higher priority inside the range (not at
  its ends) need the line-by-line path.  Sprites below a group layer's priority (Rick and the enemies behind the
  cage bars) leave those pixels out: in the cell rows with a group cell above the sprite (`ren_prio_rows`) each
  line's end masks lose the pixels whose group priority (the `ren_pri` planes) is above, and those pixels get the
  background from the twin column (`ren_pr_twin`: an object drawn before may be under them; the arcade composes the
  sprites first, so a hidden sprite pixel hides the sprites behind it too).  Two source words a row: a pass a line
  with code per priority (`.pr`); otherwise line by line (`ren_pri_line`), or drawn whole and *repaired* afterwards
  (`ren_repair`) when it lies over another object.
* **Overlays**: enabled layers 0-3 outside the group (layer 3: the flickering lightning and objects of stages 4 and 6)
  and the fixed layers' cells outside the HUD bars are drawn per picture as 8 x 8 images through the same sprite code,
  between the sprites by priority.  Cells hidden by bars, wholly covered by group layers of higher priority, or opaque
  black under the whole group (the attract mode's backdrop) are skipped, and cells wholly outside the clip groups
  before their image is looked up.  With `TILE_FLAG` layers 0-3 keep a bitmap of their non-empty cells (`ren_obm`,
  a row rebuilt when tile RAM was written since: `ren_tgen`), so a picture tests 5-6 bytes a visible row instead of
  37 words (stage 1's layer 3, on in every other frame: ~1000 words and ~60 blank cells of other codes a picture).
* **Fixed layers 4/5**: rows of 36 opaque cells whose lowest priority is at least the group's form *bars* (the HUD:
  32 lines at the top, 32 at the bottom); they are a bar image (`ren_fi`, black side bands) copied into each buffer's
  bar lines at the window's position when the window moved (4 passes a run of lines, fine-shifted) or the lines were
  damaged.  Sprites below a bar's priority skip its lines.
* **Damage**: what a picture draws (sprites, overlay cells, the clip window) goes into the buffer's list (adjacent
  rectangles merged) and is copied back from the twin columns at the buffer's next turn (12 words a line at most;
  overflow: the whole window).  In bar lines the rectangle is copied from the bar image instead (words | $8000 in the
  list: a pass a plane, the window's fine scroll as skew with FXSR; only when the window and the bar image are as
  they were, else ren_bars copies all bar lines anyway): a sprite over the HUD no longer costs whole bar lines.
* **C116 window**: outside it black rectangles (attract mode's iris).
* **Blitter**: every pass HOG and at most 256 bus cycles (`blit_go` of `engine/rt/borders.s` for the restores, bars and
  fills; a sprite line is 3 words x 4 planes).  `BLIT_STATS=256` on the test lists no longer pass and none without HOG.
* **Not implemented**: the shadow sprite colour $7F (never used by Splatterhouse), the 16-sprites-per-line limit, the
  screen flip off (the game always flips).

### Colours

The arcade's colours live in palette RAM (they change per stage, fade by -32 a channel a step, and cycle tile banks
for lightning), 140-310 pens on screen.  The renderer maps pens to STE indices at run time:

* **Per scene** (`ren_cluster`): samples of the screen (a pixel per group cell, fixed cells, overlay cells, 16 per
  sprite) give a histogram of the distinct colours (4 bits a channel).  Each colour weighs 16 x the root of its count,
  four times that when a sprite uses it; a median cut (widest Oklab axis x root of the weight, weighted median) seeds
  15 centres, 12 rounds of k-means (L1 in byte Oklab) refine them.  Index 0 is black.  A pen's index is the nearest
  centre of its colour (`ren_pen_index`, a 4096-entry table filled on demand); the c2p tables of tile banks and sprite
  colours and the cache are made from it.
* **Two palettes**: the HUD region (the bar lines at the top and the bottom) gets its own 15 colours from its own
  samples; the playfield's are chosen without them.  The main program changes the palette at the region's lines
  (below); `-D REN_ONEPAL=1` gives one palette for all lines (no raster change, worse colours).
* **Fades** without redrawing: the STE colour of an index is the current colour of a representative pen (the colour
  nearest the centre), so the STE palette fades with palette RAM.  The mapping uses the palette as it was when the
  colours were chosen (`ren_palsnap`).  A tile bank change of a group member alone (the intro's lightning) is a
  palette change too: the cells keep the drawn bank, the representatives take the current bank's colours.
* **When**: a new scene (the group changed, or 300 cells of the window changed, or the HUD region) shows black until
  the palette rests for 2 pictures (at most 6), then the colours are chosen and everything is drawn again.  A palette
  that settles on other colours (8 pictures without a change) is chosen again too; every 128 pictures a light check of
  the error can trigger it.

Measured (render_test, Oklab distance of the STE colour to the arcade's, mean over the picture; saturated: pixels with
chroma > 0.08): the first count-weighted median cut 0.0404 in play, 0.0394 in the attract mode; with the method above
0.0324 (saturated 0.042) in play and 0.040 (0.056) in the attract mode; stages 3 / 5 / 7 (stage-select starts,
pictures 100 frames apart) 0.028 / 0.027 / 0.043.  One palette for the whole picture (`REN_ONEPAL`): 0.047 in play.

### Interface for the main program (`src/splatter.s`)

* include `borders.s` (with `borders_blit_go` and `borders_vars`) and `render.s`; `render.s` needs the label `vio`.
* `render_init` once, after vio holds a state.  All registers kept.
* `render_frame` once per picture, between the game's frames (e.g. in the main loop after the arcade frame); keeps all
  registers.  It draws into a buffer that is neither shown nor the one shown just before (the Shifter scans the old
  one once more), publishes it (`ren_ready` = buffer + 1, one byte store) and returns; with no buffer free it returns
  at once (`ren_skipped` counts).  A long picture (a new scene: up to ~25M cycles; usually 0.25-0.5M) is interrupted by
  the VBLs as usual: the game runs on, the picture comes later.
* `render_vbl` in every VBL (all registers kept): shows a published buffer (video base and counter, `$ffff8265` fine
  scroll, `$ffff820f` line width; it subtracts `PIC_TOP` lines when `PIC_TOP` is defined), copies its palettes to
  `ren_vbl_pal` (the playfield) and `ren_vbl_hpal` (the HUD) and its HUD lines to `ren_vbl_htop` / `ren_vbl_hbot`
  (picture lines 0 .. htop - 1 and hbot .. 223 use the HUD palette; htop = 0 and hbot = 224 when there are none).
  A VBL without a new picture frees the buffer shown before.
* Palette timing (Timer B, borders.s): `ren_vbl_hpal` from the picture's first line when htop > 0 (else
  `ren_vbl_pal`), `ren_vbl_pal` from line htop, `ren_vbl_hpal` from line hbot (< 224), black after line 223.
  borders.s has the on and off events (`BD_PALETTE`, `shown_pal`, `PIC_TOP`, `PIC_LINES` = 224); the two switches at
  htop and hbot are an extension of its Timer B chain (not done here: `-D REN_ONEPAL=1` until then, with
  `shown_pal = ren_vbl_pal`).
* Proposed for `tools/gen.py`: `st tile_written` / `st tile_written_fix` after the translated stores into tile RAM
  (layers 0-3 / the fixed layers' words), and `-D TILE_FLAG=1`: the tile RAM is then compared only after a store
  (the game changes it in ~4% of its frames): -110k cycles a picture in play.

### Tests

    venv/bin/python games/splatter/tools/render_test.py [--edges] [--play A-B] [--attract A-B] [--png f,..] [-D NAME=V]

The harness (`build/splatter/ren_harness.s`: render.s, borders.s' blit_go, vio) runs on Musashi with the simulator's
Blitter.  States from the reference (`tools/machine.py`, the inputs of `logic_test.py --seed 5`: attract, coin, start,
random play; seed 1: the attract mode) are recorded once into `build/splatter/render_states.pkl` (1100 consecutive
frames of play from frame 300, 475 attract frames every 4th).  Each picture is read back as the Shifter shows it (the
published address, fine scroll, the two palettes by line) and every pixel's index must be the renderer's mapping of the
reference's pen (evaluated in Python from the renderer's centres and palette snapshot; black pictures of a new scene
must have black palettes).  `--edges`: a 32 x 32 and a 16 x 16 sprite across both edges, all 16 fine positions with
all flips, the top and bottom guards, lines across a 64 KB boundary of each buffer, at six window positions (aligned
and not): exact, and no sprite pixel outside the clip groups in the side bands (the check bites: `-D REN_NOCLIP=1`
fails).  `--png`: STE | reference into `build/splatter/render_*.png`.  `--every 2 --phase 0|1`: every other play frame
(the program's `PIC_EVERY`; stage 1 enables layer 3 in every other frame, so the two phases cost differently).
`--bench 500-1100`: the states of splatter.s' BENCH game (its scripted inputs: coin at frame 60, start at 140, from
400 right with an attack 4 frames in 40; `build/splatter/render_bench.pkl`, recorded once): stage 1 scrolling with
more enemies, the picture Hatari's `dbench` measures.  The fixed layers' flag is set in every frame there (the
program's HUD writers run every frame), so their diff runs in every picture as in the program.

Results (2026-10-12): play 1100 / 1100 pictures exact, attract 475 / 475, edges 218 / 218; stages 2-7 from
stage-select captures (every 25th frame, ~90 pictures each) exact; also `-D REN_NBUF=3`, `-D REN_DMG=6` (overflow
path), `-D TILE_FLAG=1`, `-D REN_ONEPAL=1` exact.  2026-10-13 (the speed-up below): play, attract, edges, both
`--every 2` phases, with and without `TILE_FLAG`, `REN_NBUF=3`, `REN_ONEPAL=1`, `REN_DMG=6`: all exact; and the
BENCH states (601 pictures, both `--every 2` phases) in all these variants.

### Measurements

Cycles a picture on Musashi (CPU + Blitter bus cycles; the game's logic is apart: ~150-170k a frame):

| | median | 10% | 90% | max (new scene) |
|---|---|---|---|---|
| play (1100 pictures) | 448k (2026-10-12: 488k) | 351k (391k) | 608k (845k) | 25M |
| play, `TILE_FLAG` | 261k (346k) | 208k (248k) | 462k (710k) | 25M |
| play, `TILE_FLAG`, `--every 2`, phase 0 (layer 3 off) | 251k (298k) | 197k (242k) | 454k (719k) | 25M |
| play, `TILE_FLAG`, `--every 2`, phase 1 (layer 3 on) | 348k (486k) | 228k (342k) | 606k (865k) | 25M |
| attract (475) | 220k (234k) | 219k (224k) | 750k (849k) | 27M |
| attract, `TILE_FLAG` | 150k (169k) | 149k (154k) | 684k (779k) | 26M |

In play (`TILE_FLAG`, the mean over 1100 pictures without new scenes: ~318k): the sprite and overlay draws ~98k
(their setup ~2k a draw, ~16-20 draws; lines ~70 cycles CPU + ~90 Blitter when the mask repeats, ~200 + ~90 when
not), the restores ~27k (mostly Blitter), the palette ~20k, the damage lists ~19k, the repairs ~18k, the sprite list
~17k, the overlay layers ~17k, the group cells ~12k, conversions of new sprite images ~13k (~10-15k a 32 x 32 image;
before: ~60-70k).  A new scene: ~1200 window cells (~5-7k each), the samples and k-means (~3-5M), the bar image.

Hatari (BENCH=1 build, arcade frames 600-1100 of the scripted game): 12.38 -> 13.30 arcade frames/s, 6.18 -> 6.64
pictures/s.  The rate depends on which arcade frames get a picture (layer 3's phase): the same renderer with ~4000
cycles of nops at render_frame's start gives 13.69, a variant ~1k cycles a picture slower 13.75; read changes of a
few % with care.

BENCH states (`--bench 500-1100 --every 2`, `TILE_FLAG`; median / mean without new scenes): phase 0 650k / 656k ->
593k / 611k, phase 1 672k / 694k -> 616k / 651k.  Hatari, `dbench` with `REN_PHASES` (frames 600-1100, VBLs per phase, k cycles a picture): 13.28 ->
13.96 arcade frames/s, 6.63 -> 6.96 pictures/s; objects 748 -> 666 VBLs (479k -> 426k), restore 112 -> 101, bars 96
-> 102, fixed 69 -> 64, palette 46 -> 35, bg 73 -> 71.  Hatari's CPU profiler (`--parse`, a breakpoint on
bench_inputs at frame 600 starts it) agrees with Musashi per routine within ~5-10% (the bus's 4-cycle rounding); the
interrupts (Timer B, the border chain, the HUD plan) take ~6% of the time.  The higher picture cost than the play
states is the game: the BENCH game scrolls and has more enemies (~340 sprite lines and ~80 behind the cage a
picture), and the fixed layers are compared in every picture (~33k; the HUD writers set the flag every frame).

Tried and dropped (2026-10-13): the full stefastbobs2 method as a prototype (`-D REN_GEN=1`, removed again): code
generated per (image, skew, flip y) on first use (a pass a row, end masks / X count / Y increment written as
constants when they change, no per-line decisions; `REN_GSORT`: rows grouped by equal masks).  Exact, but the BENCH
game makes ~6 new (image, skew, flip y) a picture (hits 57% with a 96 KB code pool; 75% with 2 MB): generating costs
~22k each, ~134k a picture, against ~42k saved in the draws.  Musashi BENCH mean 612k -> 714k (row order), grouped
order slower again; Hatari 13.96 -> 12.54 arcade frames/s, objects 426k -> 552k a picture.  It would need ~0.5 MB
of code to reach its best hit rate and still pay ~80k a picture for the generation.

Tried and dropped: the stefastbobs2 reordered source (rows of equal masks grouped across the image, the destination
from a table of row offsets).  Measured over 400 play pictures: 94213 sprite rows drawn, 58178 mask changes in row
order, 49777 groups of equal masks: grouping saves ~21 mask changes a picture (~2.5k cycles), less than grouping
costs in the conversions (~5-10k an image, ~0.5 images a picture), and the rows left out at bars and palette
boundaries would need the line-by-line path.  Row order with the Blitter left as it is for repeated masks keeps most
of the gain (38% of the rows).

Memory (the harness without vio): text 16 KB, data 1.59 MB (characters 768 KB, masks 128 KB, sprite boxes 595 KB,
tables), bss 0.84 MB (2 buffers 295 KB, cache 128 KB, the pair tables 128 KB (`REN_PTS` 32 x 4 KB), priority planes
57 KB, bar image 38 KB, tile copy 32 KB, ...): 2.45 MB.  With the program's ~1.2 MB (code, 512 KB ROM image, vio, the
snapshot) about 3.65 MB of 4 MB (`REN_PTS` 16 would give 64 KB back).

### Open problems

* Speed: ~2 VBLs a picture in play besides the logic; a new scene takes ~1/2 s of black pictures.  Next: the draw
  setup (~1-2k a sprite or overlay cell: many memory variables), the restores (Blitter), the priority rows' scan, the
  palette's per-picture checksum and representatives (~20k), the damage lists.  Outside render.s: per-row flags from
  the fixed layers' writers (gen.py) would cut the fixed layers' diff (~33k a picture); showing the HUD bars from a
  fixed image by switching the video address at the bar lines (borders.s' Timer B events already switch the
  palette there) would remove the bar copies while scrolling (~65k a picture in Hatari).
* The HUD palette needs the Timer B extension; `REN_ONEPAL` meanwhile.
* Colours: a representative pen that does not fade like its colour's other pens (the HUD skulls stay white in a
  fade); colours appearing after the choice (stage 4's purple lightning, sprites of a new colour) map to the nearest
  existing colour until the next choice; stage 5's red scene leaves no teal for Rick.
* Memory: ~250 KB more could come from 4-bit characters with a palette per character (+50% conversion time).
* Not run in Hatari: the main program (splatter.s) is not written yet.
