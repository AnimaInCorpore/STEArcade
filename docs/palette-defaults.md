# Approved colour defaults — 2026-11-05

The new colours are the ordinary native-build default in all eleven ports shown
in the comparison gallery, in addition to R-Type: Gyruss, Time Pilot, Track &
Field, Hyper Sports, Mr. Do!, Pooyan, Commando, Gun.Smoke, Black Tiger, Double
Dragon and Gauntlet. This supersedes the initial decision to retain their old
palettes in the [audit](palette-audit.md). The remaining ports' distinct runtime,
direct-PROM and split-palette paths described there are unchanged.

`engine/palette_quantize.py` / `.js` retain the Alien/Zombies algorithm with the
approved saturation fix: original arcade RGB, count compression separately for
sprites and tiles (power 0.75), sprite preference 8x **after** compression, and
the smooth chroma bonus `1+C²/(C²+0.1²)`, below 2x. Black is fixed. The fitter now
also accepts fixed STE colours; Gauntlet keeps its red warrior, blue valkyrie,
yellow wizard and green elf. No external demo checkout is required.

## Native conversion

The six small-PROM ports use the bounded **flat** fit and one native index per
pen. These are the flat treatment in the gallery; their shown gameplay samples
selected no checker pairs. Gyruss and Pooyan's checker-refined palettes can
nevertheless differ from their flat fits, so the two treatments are not claimed
to be identical over the whole game. The approved sprite preference can increase
the background error; the audit records that tradeoff.

Commando and Gun.Smoke generate two row-conversion routines per colour. Black
Tiger, Double Dragon and Gauntlet cache both source-row parity tables. A packed
mapping byte holds the even-source index in its high nibble and the odd-source
index in its low nibble. The phase follows the source image through flips,
crops, sorted sprite rows and scrolling. It does not follow the screen or reset
at a clipped edge. The independent reference renderer tags original source
parity before composing layers and applies the colour map afterwards.

All text is flat: character/foreground layers use the nearest single colour
from the fitted palette, never a checker pair. The RAM-palette ports have a
separate flat hardware-word lookup for text; their map bytes duplicate that
single index in both nibbles. R-Type retains its separate flat HUD palette.
Sprites and background graphics keep their source-anchored checker choices.
Sprite drawing streams, opaque masks, priority and pass counts are unchanged. No new
AND/OR Blitter pairs are introduced. Palette comparisons and cache epochs compare
the entire packed byte, so changing only one half also invalidates an image.

The bus audit also found Commando's existing shifted-tile pass could reach 320
cycles. It now uses two eight-line HOG passes with advancing addresses; aligned tiles
keep their direct pass. The pixels and advancing source/destination addresses match.

Black Tiger and Double Dragon add 64 KiB of conversion tables and a 4 KiB flat
text lookup. Gauntlet adds a 64 KiB flat lookup, expands
its fixed lookup area into the former alpha-table area and moves its 128 KiB
alpha tables into runtime BSS, below the fixed buffers at $200000. Every normal
program still targets a 4 MB STE; R-Type retains its documented 14 MB target.
Cold conversions do more CPU work; this is a colour change, not a speedup claim.

## Training and rebuilds

- The six PROM ports use their existing curated coverage pen histograms;
  Mr. Do! uses its retained `pens*.pkl` recordings. Time Pilot includes seed 13.
- Commando keeps the original ten seed-1 training frames, from 100 through 2500.
  Gun.Smoke keeps its retained all-round `palette_stats.json` histogram.
- Black Tiger, Double Dragon and Gauntlet retain the approved sampled-play RGB
  counts in each game's `docs/colour_training.json`: frames 1100–2199, every 30
  frames. These are **not** whole-game palette-quality coverage. The generated
  mappings cover every possible RGB444 / IRGB4444 hardware word, including
  colours absent from the samples. The training counts are small and checked in;
  ROM images, snapshots, graphics and generated executables stay private.

`python port.py build <game>` uses the new colours. Build stamps for the eight
ports that cache generated assets invalidate the earlier colour policy on a
normal build. `--assets` explicitly regenerates assets after coverage changes.
The three RAM-palette ports regenerate their assets on every build as before.

The gallery tools remain read-only experiments:

```sh
venv/bin/python tools/palette_gallery.py
venv/bin/python tools/palette_gallery.py --reuse
venv/bin/python tools/palette_gallery.py --games commando gunsmoke gauntlet --reuse
```

They write `build/palette_gallery/index.html`, original-size images, comparisons
and compressed capture caches. “Current” reads the built native palette and map;
the flat/checker candidates are offline treatments. Candidate preview checkers
use screen parity; native current colours use source parity. The gallery does
not rewrite native assets or executables.

## Validation

Native pixel comparisons and the existing sprite suites cover gameplay,
consecutive damage restoration, every horizontal shift, flips, transparent holes,
aligned and unaligned edges, guard lines and 64 KiB destination crossings. The
independent reference's parity tags strip back to the unchanged arcade pens;
hardware RGB decoding is unchanged. R-Type's recorded-picture and focused
fallback suite is rerun after extending the shared fitter's fixed-colour API.

| Port | Native renderer checks | Focused sprite / colour checks |
|---|---|---|
| Gyruss | 30 gameplay pictures | 156 edge/shift/restore pictures |
| Time Pilot | 30 gameplay pictures | 168 edge/shift/restore pictures |
| Track & Field | 30 gameplay pictures | 154 edge/shift/restore pictures |
| Hyper Sports | 30 gameplay pictures | 154 edge/shift/restore pictures |
| Mr. Do! | 30 gameplay pictures | 476 edge/shift/restore pictures |
| Pooyan | 30 gameplay pictures | 140 edge/shift/restore pictures |
| Commando | 40 gameplay, scrolling and guard pictures | 143,360 baked objects; 456 edge/shift/damage cases |
| Gun.Smoke | 40 gameplay, scrolling and guard pictures | 3,600 generated/fallback edge/shift cases |
| Black Tiger | 3 scrolling gameplay pictures | 4,096 placed edge sprites in 512 pictures, then a 400-picture random walk |
| Double Dragon | 4 gameplay pictures | 32 edge pictures; 1,024 flat solid-text fill cases |
| Gauntlet | 4 gameplay pictures | 307 edge/shadow/overlap pictures, including a fresh all-$ff packed palette |
| R-Type | 1,625 recorded pictures | 226 forced fallback/edge cases; all pass after the shared fitter extension |

All comparisons pass. Black Tiger, Double Dragon and Gauntlet's full sprite
suites, plus Double Dragon's flat text-fill suite, were also run with `BLIT_STATS=256`:
no pass exceeds 256 bus cycles and none shares the bus. The new text-fill test
is included in `port.py test ddragon`; fixed-anchor, flat-text mapping and sparse-input fitting
contracts are included in `port.py test engine`.

Every normal program was rebuilt. The ten ports with automatic frame/counter
reports ran for 1,500 VBLs from boot in the pinned Hatari, compatible cycle-exact
STE mode with 4 MB: no late top-border, palette-on, bottom-border or palette-off
events. These are boot/attract checks, not stage-wide speed measurements. Logic
and picture rates are retained separately in `build/palette_native_default/`.
Gauntlet's added 64 KiB flat lookup is included in its runtime boundary check;
its fixed screen buffers still begin at $200000. Its 4 MB normal program also
reached the active attract-mode maze in a pinned Hatari capture at VBL 1500.

The eleven-port gallery was regenerated and its compressed-cache reuse checked.
The three RAM-palette current-colour caches include the native palette/map and
reference-source signature. These checks do not establish whole-game visual
quality for their sampled fits.
