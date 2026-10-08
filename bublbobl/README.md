# Bubble Bobble (Taito 1986) — Atari port, working notes

Same method as the Donkey Kong port in `../ste/` (host reference → Z80 translator → 68000 runtime),
with the extra work Bubble Bobble needs: **three Z80s and an MC6801 MCU**, a strip-based sprite
engine instead of a tilemap, 256 palette entries, and FM sound.

ROM sets (`../assets/roms/`): `bublbobl.zip` (Japan) and `bublboblr.zip` (US / Romstar — the port
target). Verified by `tools/bbrom.py`; manifest in `docs/rom_manifest.md`.

## Status

| phase | state | evidence |
|---|---|---|
| ROM provenance | done | `python tools/bbrom.py` — 18/18 files per set, CRC32 checked |
| Host reference machine | boots both sets to a full attract loop (notice, title, demo levels) | `python tools/bbgolden.py` (frame hashes), `build/frames/` screenshots |
| MCU (MC6801) | real ROM executed; board protocol decoded from the ROM | `tools/m6801.py`, `tools/mcudis.py`, `docs/hardware.md` |
| Video | strips, tiles, palette, X-continuation rendered; flip-screen not yet | `tools/bbvideo.py` |
| Inputs | coin pins work; player/DIP bits not mapped | — |
| Workload profile | measured | `python tools/bbprofile.py`, `docs/feasibility.md` |
| Sound | not started (writes are logged) | — |
| Z80 → 68000 translation | not started | — |
| STE/Falcon runtime | not started | — |

Nothing here is a claim about the *original* beyond the grade written next to it in
`docs/hardware.md` (Code / Run / Hyp).

## MAME reference (screenshots)

`F030Arcade/third_party/wolfmame-0162/mame.exe` (at `C:\Arbeit\F030Arcade`) is the only MAME there that knows
Bubble Bobble: `bublboblr` = "Bubble Bobble (US, Ver 5.1)", `bublbobl` = "Japan, Ver 0.1"; both zips in
`assets/roms/` pass `-verifyroms`. Its Lua has no snapshot call (`emu.sethook(fn,"frame")` is the only
per-frame hook), so frames come from `-aviwrite` (uncompressed RGB24, lossless, native 256x224).
The AVI writer is 32-bit: record ~300 s segments and chain them with `-autosave` (`-seconds_to_run` is cumulative).
`tools/bbmame_collage.py` documents the exact command and builds `docs/attract_collage_64.png`
(64 attract-mode frames, 8x8, 2048x1792) covering **every colour** seen in the recording.

Facts from the capture run (`docs/attract_collage_64.json`): 68 distinct on-screen colours after boot;
the last new colour first appeared at 736 s and none in the following 490 s, so coverage looks saturated
but is not proven (the demo levels vary between loops, no exact long period was found). A stray coin
registered at 1227 s (an input reached MAME's window; none was sent by the tooling) � frames from then on
are excluded.

## 16-colour quantization (JsOklabQuantizer strategy)

`tools/bbquantize.py` runs `tools/oklab_quantize.mjs`, which imports `C:\Arbeit\jsoklabquantizer`'s own
`quantizer.mjs` / `color.mjs` unmodified (that repo at `066f401`; its uncommitted `main.mjs` change is the
native-size summed palette used here, so nothing is cropped or resized). One palette is built from all
pixels of the collage in Oklab (fixed lightness ladder, k-means on a/b, defaults: fatnessBias 0.75,
colorDecay 0, 18 iterations) and every pixel is mapped to its nearest entry.
Results in `docs/quant/` (`attract_collage_q16_default.*` is the tool's default; `_decay1` is colorDecay 1
for comparison; `_compare.png` shows source, both results and palettes; the JSON has the palette with the
nearest 12-bit STE value for reference, and the per-colour mapping/error).

Default result: mean error 2.37 (dOklab x100) over the 68 source colours, 15 of 16 slots used, no green
in the palette (Bub's `#00bb00`, 2,008 px, maps to a teal; worst error 20.8). colorDecay 1 fixes the greens
but turns the yellow logo green and has a higher mean error (2.81). Read this as an input to the
STE-vs-Falcon decision, not a final palette.

### Adopted palette

The default result is the working palette: `docs/palette16.json` (16 entries, ascending lightness, with Oklab
values, sRGB and the nearest STE $0RGB). `tools/bbpalette.py` maps any RGB to it with the same nearest-Oklab rule
and reproduces the quantizer's own image exactly (0 of 3,670,016 pixels differ). `Renderer.render_q16(machine)`
returns a frame as 16-colour indices + RGB via a 256-entry lookup built from the board's palette RAM
(`bbgolden.py` now also hashes these). Status: not yet validated against gameplay frames, and the missing green
(see above) is a known weakness.

## Tools

* `tools/bubble.py` — machine model (`Bubble(variant="bublboblr")`, `run_frame()`).
* `tools/m6801.py` — MC6801 core + disassembler; `tools/mcudis.py` — recursive-descent listing.
* `tools/bbvideo.py` — char decode + strip renderer (`Renderer().render_rgb(machine)`).
* `tools/bbgolden.py` — golden frame hashes for both sets (`docs/golden.json`).
* Z80 core and disassembler are shared with the Donkey Kong port: `../ste/tools/z80.py`, `z80dis.py`.
