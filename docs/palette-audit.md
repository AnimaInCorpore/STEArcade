# Colour weighting audit — 2026-11-05

R-Type's approved bounded weighting is retained in `engine/palette_quantize.py`
and `engine/palette_quantize.js`, and is the default for its stage renderer and
new build-time fitted palette paths. The separate stefastbobs2 checkout is not a
build dependency. Existing ports were checked before changing their palettes.

The histogram policy compresses sprite and tile counts separately with power
0.75, applies sprite priority afterwards (8x), and uses the smooth bonus
`1 + C² / (C² + 0.1²)` in floating-point OKLab. The bonus stays below 2x; it does
not change input RGB saturation. The former R-Type multiplier reached about 32x.
Preserve scenario normalization, exact PROM mappings, explicit player colours,
HUD splits and reserved cycling pens when adapting a port.

## Source inspection

All 27 game directories were inspected: 22 registered ports, the Mr. HELI,
Galaga '88 and Splatterhouse renderer work, and two preparation-only ports.
This is a palette-path audit, not a new full-game verification of every port.

| Ports | Palette path and finding | Outcome |
|---|---|---|
| R-Type | `tools/stage_assets.py`: the sole 40x chroma factor; sprite weight was inside square-root compression | Replaced by bounded source-RGB fitting and baked checker pairs; ordinary build defaults to the stage renderer |
| Mr. HELI; R-Type legacy renderer | `engine/m72_palettes.py` / `engine/rt/m72render.s`: scene colours, packed OKLab L1 and count compression | No equivalent chroma multiplier; runtime path retained |
| Galaga '88 | `tools/assets.py:static_palette`, `src/render.s:ren_entries`: 4x sprite samples before square root; effective preference about 2x | Recorded as a separate runtime/static policy choice; changing the static helper alone would not update the runtime fitter |
| Splatterhouse | `src/render.s:ren_palette_of`: sprite colours receive 4x weight **after** square root | Already preserves the multiplier; no saturation boost |
| Gyruss, Time Pilot, Track & Field, Hyper Sports | `tools/assets.py`: pixel-count fits in OKLab; nearest STE-grid centres | No saturation boost; blanket replacement worsens background error in numerical comparisons below |
| Mr. Do! | `tools/assets.py`: deliberately chosen power 0.5 before Gyruss's fitter | Candidate improves the average but merges two distinct red shades; retained the current palette |
| Kung-Fu Master | `tools/assets.py`: separate per-floor/playfield and HUD count fits | No saturation boost; retain the scene/HUD budgets |
| 1942, 1943 | `tools/palettes.py` / `tools/assets.py`: count power 0.6 plus floor, with 1942's palette banks | No saturation boost; bank-specific palette constraints retained |
| Commando, Gun.Smoke | `tools/assets.py`: count power 0.6 plus floor | No saturation boost; no sprite multiplier is unintentionally compressed |
| Black Tiger, Trojan, Double Dragon | `ref/palette_fit.py`: equal scenario contributions with full frequency within a scenario | No saturation boost; retain normalization so large skies and walls keep their colours |
| Bubble Bobble | `ref/palette_fit.py`: square root of each scenario's normalized colour share | Intentional rare-colour preference; no saturation boost |
| Gauntlet | `ref/palette_fit.py`: normalized count power 0.5 plus fixed player colours | Keep the four fixed player colours; no saturation boost |
| Donkey Kong, Donkey Kong Junior | `tools/assets.py`: merge a small PROM colour set by distance and square root of minimum count | Different merge criterion; no saturation factor or compressed sprite multiplier |
| Galaga, Pac-Man, Moon Patrol | `tools/assets.py`: explicit colour sets / direct indices / separate panel and picture palettes | Preserve direct mappings and hardware budgets |
| Pooyan | `tools/assets.py`: most-frequent PROM colours, nearest OKLab mapping for the few omitted colours | No saturation boost; numerical replacement does not improve overall error |
| Dragon Spirit, Pac-Mania | Preparation and MAME-comparison scaffolding; no independent STE colour fitter | No palette implementation to change yet |

## Fixed-palette numerical comparisons

`venv/bin/python tools/palette_audit.py` reads each port's existing coverage
histograms and reference RGB. It fits a 16-colour **flat** candidate, since these
renderers do not consume checker pairs. No graphics, PROM model or palette JSON
is rewritten. These are recorded-sample colour comparisons, not new MAME runs.

Mean Euclidean OKLab distance ×100, with original pixel counts used for evaluation
independently of fitting weights; lower is better. Excluding black prevents the
large empty background in some ports from hiding colour errors.

| Port | Non-black pixels, current → candidate | Sprite pixels, current → candidate | Tile pixels, current → candidate |
|---|---:|---:|---:|
| Gyruss | 1.631 → 2.892 | 4.835 → 2.618 | 0.048 → 0.118 |
| Time Pilot | 0.951 → 1.513 | 2.272 → 1.724 | 0.540 → 0.913 |
| Track & Field | 0.604 → 0.651 | 1.345 → 1.200 | 0.319 → 0.346 |
| Hyper Sports | 0.733 → 1.617 | 2.681 → 1.447 | 0.330 → 0.799 |
| Mr. Do! | 1.539 → 1.476 | 1.569 → 1.098 | 0.786 → 0.764 |
| Pooyan | 0.247 → 0.249 | 0.272 → 0.268 | 0.247 → 0.249 |

Mr. Do!'s candidate maps both `(255,0,0)` and `(255,88,0)` to `(255,51,0)`;
the current palette keeps them separate. Its blue improves, but the average error
does not establish a visual improvement. The existing six palettes are retained.

Small per-port results, palettes and the Mr. Do! critical-colour mappings are in
`build/palette_audit/`. R-Type's independent renderer and Hatari validation are in
[its colour results](../games/rtype/docs/palette-results.md).
