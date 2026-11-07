# Colours on the STE

The STE shows 16 colours from 4096 (4 bits a channel); the arcade games show 22-90 at once. This page gathers how
the ports choose and map their colours: the general rules, the default build-time fitter, which port uses what, and
the evidence behind the defaults (the approved rollout and the audit of 2026-11-05). The reference's own colours
must first equal MAME's: see `porting-guide.md`, "Checking the reference against MAME" (Donkey Kong's resistor
networks, Galaga's blue).

## Rules

* **Exact where it fits.** A small PROM set that fits 16 colours (or 16 per bank, switched with the game's bank)
  keeps its colours and one STE index per pen: Galaga, Pac-Man, Moon Patrol (separate panel and picture palettes),
  Donkey Kong (merged by distance), 1942 (banks).
* **Order of appearance while it fits; otherwise rank.** When more colours are on screen than slots: the background,
  "volatile" entries (changed >= 4 times: flashing, they own a slot) and the heaviest by weight, capped per bank.
  Re-mapping must only rewrite the STE palette when the mapping is unchanged.
* **Fixed palette, fitted per stage.** When the stages look different, fit the fixed colours to frames of every stage
  (cheats to reach them, as `games/blktiger/ref/palette_fit.py`), each set's histogram normalised; square-rooting
  the weights (Bubble Bobble) let a stage's sky lose its colour there.
* **Runtime choice per scene** (Namco System 1, M72): where the palette RAM changes per scene, the runtime chooses
  16 colours when the scene changes (Galaga '88's chooser, reused by Dragon Spirit; `engine/m72_palettes.py` for
  R-Type's legacy renderer and Mr. HELI). Choices cost time: count them in benchmarks, and avoid re-choosing during
  effects (Dragon Spirit's lightning is a palette flash of the chosen representative, not a re-choice).
* **Colour cycling** costs recomposition when an STE index changes for a pen: freeze such rows at the scene's
  reference target, or give the cycling pens dedicated STE indices whose colours change per picture (R-Type's
  FROZEN_ROWS / DEDICATED; see `speed.md`).
* **Look at the worst-mapped colours** before accepting a palette: Bubble Bobble's first Oklab result had no green
  (Bub's `#00bb00` mapped to a teal); Mr. Do!'s candidate merged two distinct reds.
* **Text is always flat** (one colour a pen, never a checker pair).

## The default fitter (`engine/palette_quantize.py`, R-Type 2026-11-05)

Use it for every new fitted palette path. It fits the original arcade RGB in OKLab: sprite and tile counts are
compressed separately (power 0.75), sprite priority applied after compression (8x), and the smooth chroma bonus
`1 + C² / (C² + 0.1²)` stays below 2x; RGB saturation itself is never increased. Black is fixed; the fitter accepts
further fixed STE colours (Gauntlet keeps its red warrior, blue valkyrie, yellow wizard and green elf). The former
R-Type multiplier reached about 32x. `engine/palette_quantize.js` is the same for the gallery; no external demo
checkout is needed.

**Checker pairs** (after stedaimakaimura: 50/50 checkerboard mixes of close palette pairs, for a CRT): a mapping byte
holds the even-source index in its high nibble and the odd-source one in its low nibble. The phase follows the source
image through flips, crops, sorted sprite rows and scrolling, not the screen, and does not reset at a clipped edge:
bake the parity in asset coordinates before flipping, cropping or reordering rows, preserving the opaque masks and
pass order. The independent reference renderer tags the original source parity before composing layers and applies
the colour map afterwards. Palette comparisons and cache epochs compare the whole packed byte.

Keep exact PROM mappings, fixed player colours, HUD palettes and cycling-pen slots where a port needs them, and
compare before changing a port's weighting: a blanket replacement worsened backgrounds (audit below).

Older method, still the reference for 16-colour budgets from a MAME capture: take the colours seen (a collage of
frames that contains every one, `games/bublbobl/ref/mame_attract_collage.py`) and reduce with the JsOklabQuantizer
strategy (`C:\Arbeit\jsoklabquantizer`: a shared palette in Oklab, lightness ladder + k-means on a/b;
`games/bublbobl/ref/quantize_collage.py`).

## What each port uses

Approved by the user after a visual comparison (2026-11-05); this replaced the audit's first decision to keep the old
palettes. Dragon Spirit and Splatterhouse were not part of the rollout.

| Ports | Path |
|---|---|
| Gyruss, Time Pilot, Track & Field, Hyper Sports, Mr. Do!, Pooyan | the default fitter, **flat**: one native index per pen (their shown gameplay samples selected no checker pairs; Gyruss's and Pooyan's checker-refined palettes can still differ from the flat fit over a whole game) |
| Commando, Gun.Smoke | the default fitter with **checker pairs**: two row-conversion routines generated per colour |
| Black Tiger, Double Dragon, Gauntlet | the default fitter with **checker pairs**: both source-row parity tables cached (+64 KB conversion tables, 4 KB flat text lookup; Gauntlet +64 KB flat lookup, its 128 KB alpha tables moved into the BSS below the fixed buffers at $200000); Gauntlet with its four fixed player colours |
| R-Type (stage renderer) | the default fitter with checker pairs; a separate flat HUD palette ([its results](../games/rtype/docs/palette-results.md)) |
| Mr. HELI, R-Type's legacy renderer | `engine/m72_palettes.py` / `engine/rt/m72render.s`: scene colours, packed OKLab L1 and count compression |
| Galaga '88, Dragon Spirit | runtime chooser per scene (`ren_entries`; 4x sprite samples before the square root, an effective preference of about 2x) |
| Splatterhouse | runtime `ren_palette_of`: sprite colours 4x after the square root |
| Kung-Fu Master | separate per-floor/playfield and HUD count fits |
| 1942, 1943 | count power 0.6 plus a floor; 1942's palette banks |
| Trojan | `ref/palette_fit.py`: equal scenario contributions, full frequency within a scenario |
| Bubble Bobble | `ref/palette_fit.py`: the square root of each scenario's normalized colour share (a deliberate rare-colour preference) |
| Donkey Kong, Donkey Kong Junior | a small PROM set merged by distance and the square root of the minimum count |
| Galaga, Pac-Man, Moon Patrol | explicit colour sets, direct indices, separate panel and picture palettes |
| Pac-Mania | no STE colour path yet |

Cold conversions in the checker ports do more CPU work: the rollout was a colour change, not a speed-up. The bus
audit of the rollout also found Commando's shifted-tile pass could reach 320 bus cycles; it now uses two eight-line
HOG passes with advancing addresses.

## Training data and rebuilds

* The six PROM ports use their curated coverage pen histograms; Mr. Do! its retained `pens*.pkl` recordings; Time
  Pilot includes seed 13.
* Commando keeps its ten seed-1 training frames (100-2500); Gun.Smoke its all-round `palette_stats.json`.
* Black Tiger, Double Dragon and Gauntlet: the sampled-play RGB counts in each game's `docs/colour_training.json`
  (frames 1100-2199, every 30). Not whole-game coverage; the generated mappings cover every possible RGB444 /
  IRGB4444 hardware word, including colours absent from the samples. The counts are small and checked in; ROM
  images, snapshots, graphics and programs stay private.
* `python port.py build <game>` uses the colours; build stamps of the eight ports that cache generated assets
  invalidate an older colour policy, `--assets` regenerates after coverage changes; the three RAM-palette ports
  regenerate on every build.

The gallery (read-only experiments; `build/palette_gallery/index.html`):

```sh
venv/bin/python tools/palette_gallery.py
venv/bin/python tools/palette_gallery.py --reuse
venv/bin/python tools/palette_gallery.py --games commando gunsmoke gauntlet --reuse
```

"Current" reads the built native palette and map; the flat / checker candidates are offline treatments. Preview
checkers use screen parity, native colours source parity. The gallery rewrites no assets or programs.

## Validation of the rollout (2026-11-05)

Native pixel comparisons and the sprite suites cover gameplay, consecutive damage restoration, every horizontal
shift, flips, transparent holes, aligned and unaligned edges, guard lines and 64 KB destination crossings; the
reference's parity tags strip back to the unchanged arcade pens.

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
| R-Type | 1,625 recorded pictures | 226 forced fallback/edge cases |

All pass. Black Tiger's, Double Dragon's and Gauntlet's sprite suites and Double Dragon's text-fill suite also ran
with `BLIT_STATS=256`: no pass over 256 bus cycles, none sharing the bus. Every program was rebuilt; the ten ports
with frame/counter reports ran 1,500 VBLs from boot in the pinned Hatari (4 MB, cycle-exact) with no late border or
palette events (boot/attract checks, not speed measurements; the rates are in `build/palette_native_default/`).
These checks do not establish whole-game visual quality for sampled fits.

## The audit before the rollout (2026-11-05)

All 27 game folders were inspected for their palette paths (the table above is its result, updated to the
rollout). `venv/bin/python tools/palette_audit.py` reads each port's coverage histograms and reference RGB and fits
a flat 16-colour candidate; nothing is rewritten. Mean OKLab distance x 100, original pixel counts, black excluded
(lower is better):

| Port | Non-black pixels, old -> candidate | Sprite pixels | Tile pixels |
|---|---:|---:|---:|
| Gyruss | 1.631 -> 2.892 | 4.835 -> 2.618 | 0.048 -> 0.118 |
| Time Pilot | 0.951 -> 1.513 | 2.272 -> 1.724 | 0.540 -> 0.913 |
| Track & Field | 0.604 -> 0.651 | 1.345 -> 1.200 | 0.319 -> 0.346 |
| Hyper Sports | 0.733 -> 1.617 | 2.681 -> 1.447 | 0.330 -> 0.799 |
| Mr. Do! | 1.539 -> 1.476 | 1.569 -> 1.098 | 0.786 -> 0.764 |
| Pooyan | 0.247 -> 0.249 | 0.272 -> 0.268 | 0.247 -> 0.249 |

The sprite preference lowers sprite error and raises background error; Mr. Do!'s candidate maps both `(255,0,0)` and
`(255,88,0)` to `(255,51,0)`. The audit first kept the six palettes; the visual comparison then approved the new
ones. Per-port results are in `build/palette_audit/`.
