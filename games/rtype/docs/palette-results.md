# Default colour quantization — 2026-11-05

The approved bounded Alien/Zombies-style quantization is now the ordinary R-Type
build's default. `build.py` selects the stage renderer, fits its scene palettes
and regenerates tile tables and precoloured sprites when the inputs change.
`--legacy-renderer` selects the older shared M72 renderer. Simulator builds keep
their existing selection unless `-D STAGE=1` is supplied.

The fitter is retained locally in `engine/palette_quantize.py` / `.js`.
It does not require the stefastbobs2 checkout. The JS colour algorithm originated
in the Alien and Zombies demos; their common normalized source hash is
`e469f9d6da5398c44528b0e01f2444be08d67dfd0f33592079be71c84e02edbf`.
The reference RGB expansion was checked against `pal5bit` in the authoritative
local MAME 0.286 `src/mame/irem/m72.cpp`; the arcade palette model is unchanged.

## Colour policy and rendering

The fitter's rules (5-bit arcade RGB fitted in OKLab, then snapped to the STE grid; black fixed; sprite and tile
counts compressed with exponent 0.75, sprite priority 8x, the bounded chroma bonus; checker pairs as a packed
even/odd byte whose phase follows the source) are in the [colour guide](../../../docs/colours.md), "The default
fitter".  R-Type's own settings and costs:

- 40 deterministic initial fits; checker pairs at most 0.12 apart in lightness and 0.08 in the chroma plane, and
  0.012 better than a flat colour, their mix evaluated in linear RGB.
- 16 playfield slots, including the four dedicated changing pens of scene 6 (one index in both parity nibbles);
  the HUD flat, with its own palette.
- Two conversion-table banks (tiles follow the source row and flips; sprite pieces keep their source parity
  through cropping and row reordering; runtime cache misses use the same parity-bank deltas as build-time
  precolouring): +96 KiB of conversion tables; colour-row setup and cold cache baking do extra work.
- Opaque masks, priority, drawing routines, end-mask streams, Blitter pass count and order unchanged: the
  drawing-code and pass-stream hashes equal the previous default's; no mask/OR passes or colour fitting in the
  drawing loop.

All 1,112 recorded/curated sprite definitions are retained. The automatic build
includes the separate warship recording for sprite coverage and colour training
without changing canonical scene references. Training uses each scene's actual
scrolling, strip or no-BG composition; sampling a locked BG instead could give
the warship's hull a cyan tint despite correct index rendering. Legacy recorded index rows are
migrated where the old scene tables are available; new `--colours` recordings
store `{scene, target}` so they survive later palette changes.

## Validation

`tools/palette_test.py` compares native 68000 plus Blitter output with separately
phased model pixels. All 1,625 recorded-picture checks pass across the title,
all eight stages and all 13 colour scenes. The sweep includes consecutive heavy
stage frames and entry into the scrolling-warship mode.

Another 226 focused sprite cases pass at aligned and unaligned windows, all 16
horizontal shifts, both side edges, transparent holes, guard rows and 64 KiB
destination crossings. Each case is repeated after invalidating the sprite cache
to force native baking, followed by damage restoration. The chosen composite
sprite is 64x28 with a cropped origin at (-32,-28). The native miss path was
exercised 189 times; wholly culled cases correctly require no bake.

Fresh seed-4 lock-step logic and object-list comparison passes 1,000 frames.
The new scene/target colour-recording transport was exercised in that run.
The normal installed program is 6,117,195 bytes; its TOS load including BSS and
basepage is 13,816,052 bytes, within the 14 MiB development target.

Pinned Hatari, STE, 14 MB, CPU-exact and compatible, existing native/scheduler
code in both builds, 600 logic ticks after each replay checkpoint:

| Sample | Logic/s, previous → default | Pictures/s, previous → default | Late border/palette events |
|---|---:|---:|---:|
| Warship, seed 1 at 12600 | 21.588 → 21.619 | 16.092 → 15.827 | 0 → 0 |
| Stage 7, seed 10 at 65000 | 22.904 → 22.904 | 18.064 → 17.912 | 0 → 0 |

These are bounded replay measurements, not a whole-game performance claim.
Logic throughput changes by +0.14% / 0.00% in these samples; picture throughput
changes by -1.64% / -0.84%. The fixed short HOG passes remain the same. The original
palette, sprite-plane data and pass stream were verified byte-for-byte inside the
saved pre-change executable before timing the baseline.

Small results and captures are retained under `build/rtype/palette_default_audit/`:
`renderer_results.json`, `pass_equivalence.json`, `hatari_results.json`, logs,
four native-renderer PNGs and source/previous/default comparison panels.
`tools/palette_test.py --capture-only` regenerates the visual captures.
The original preview variants remain in `build/rtype/quantization_preview/`.
See the [colour guide](../../../docs/colours.md) for the other games.
