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
  source runs on), drawn one HOG pass a line (4 planes, the row mask shifted into END1-3), flip y by drawing upwards.
  Clipped at the group boundaries in the side bands nearest the picture's edges (END mask 0 for the words outside,
  `ren_cl`/`ren_cr`), culled when wholly outside; top and bottom whole into the guard lines.  Sprites below a group
  layer's priority (Rick behind the foreground) are drawn and then *repaired*: where the priority planes say a layer
  above shows, the background is copied back from the twin column (only in the cell rows that need it).
* **Overlays**: enabled layers 0-3 outside the group (layer 3: the flickering lightning and objects of stages 4 and 6)
  and the fixed layers' cells outside the HUD bars are drawn per picture as 8 x 8 images through the same sprite code,
  between the sprites by priority.  Cells hidden by bars, wholly covered by group layers of higher priority, or opaque
  black under the whole group (the attract mode's backdrop) are skipped.
* **Fixed layers 4/5**: rows of 36 opaque cells whose lowest priority is at least the group's form *bars* (the HUD:
  32 lines at the top, 32 at the bottom); they are a bar image (`ren_fi`, black side bands) copied into each buffer's
  bar lines at the window's position when the window moved (4 passes a run of lines, fine-shifted) or the lines were
  damaged.  Sprites below a bar's priority skip its lines.
* **Damage**: what a picture draws (sprites, overlay cells, the clip window) goes into the buffer's list (adjacent
  rectangles merged) and is copied back from the twin columns at the buffer's next turn (12 words a line at most;
  overflow: the whole window); bar lines are copied again from the bar image instead.
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
fails 47 cases).  `--png`: STE | reference into `build/splatter/render_*.png`.

Results (2026-10-12): play 1100 / 1100 pictures exact, attract 475 / 475, edges 218 / 218; stages 2-7 from
stage-select captures (every 25th frame, ~90 pictures each) exact; also `-D REN_NBUF=3`, `-D REN_DMG=6` (overflow
path), `-D TILE_FLAG=1`, `-D REN_ONEPAL=1` exact.

### Measurements

Cycles a picture on Musashi (CPU + Blitter bus cycles; the game's logic is apart: ~150-170k a frame):

| | median | 10% | 90% | max (new scene) |
|---|---|---|---|---|
| play (1100 pictures) | 488k (CPU 431k) | 391k | 845k | 25M |
| play, `TILE_FLAG` | 346k (CPU 291k) | 248k | 710k | 25M |
| attract (475) | 234k | 224k | 849k | 28M |
| attract, `TILE_FLAG` | 169k | 154k | 779k | 28M |

In play: sprite lines ~120 cycles CPU + ~130 Blitter each (a 32 x 32 sprite ~8k), conversions of new sprite images
~25-35k each, the bars ~16k CPU + ~40k Blitter when the window moved, the sprite list ~28k, the tile RAM diff ~110k
(without `TILE_FLAG`).  A new scene: ~1200 window cells (~5-7k each), the samples and k-means (~3-5M), the bar image.

Memory (the harness without vio): text 16 KB, data 1.59 MB (characters 768 KB, masks 128 KB, sprite boxes 595 KB,
tables), bss 0.74 MB (2 buffers 295 KB, cache 128 KB, priority planes 57 KB, bar image 38 KB, tile copy 32 KB, ...):
2.35 MB.  With the program's ~1.2 MB (code, 512 KB ROM image, vio, the snapshot) about 3.55 MB of 4 MB.

### Open problems

* Speed: ~2-3 VBLs a picture in play besides the logic; a new scene takes ~1/2 s of black pictures.  Next: the
  `TILE_FLAG` writers, cheaper sprite conversion (the per-colour pair tables), the stefastbobs2 row grouping (30% of
  sprite rows repeat the row before), fewer slow-path draws of overlay cells at the edges.
* The HUD palette needs the Timer B extension; `REN_ONEPAL` meanwhile.
* Colours: a representative pen that does not fade like its colour's other pens (the HUD skulls stay white in a
  fade); colours appearing after the choice (stage 4's purple lightning, sprites of a new colour) map to the nearest
  existing colour until the next choice; stage 5's red scene leaves no teal for Rick.
* Memory: ~250 KB more could come from 4-bit characters with a palette per character (+50% conversion time).
* Not run in Hatari: the main program (splatter.s) is not written yet.
