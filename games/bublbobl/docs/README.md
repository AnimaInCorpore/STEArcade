# games/bublbobl/docs — reference captures, palette, ROM manifest

Everything here was produced from the original ROMs / MAME, not from the STE port.

| file | what | reproduce |
|---|---|---|
| `attract_collage_64.png` / `.json` | 64 MAME attract-mode frames (bublboblr, US Ver 5.1), 8x8, every on-screen colour (68) present; frame times in the JSON | `ref/mame_attract_collage.py` (command for the MAME 0.162 AVI recording is in its docstring) |
| `palette16.json` | the 16-colour palette adopted from the JsOklabQuantizer default result (Oklab, sRGB, nearest STE $0RGB) | `ref/palette16.py` |
| `quant/` | quantized collage (default + colorDecay 1), compare sheet, per-colour mapping and error | `ref/quantize_collage.py` (runs `ref/oklab_quantize.mjs` -> `C:\Arbeit\jsoklabquantizer`, commit 066f401) |
| `rom_manifest.md` | CRC32/SHA1 of both sets (Japan `bublbobl`, US `bublboblr`) | `ref/rom_manifest.py` |
| `hardware-notes.md` | hardware findings with evidence grades (see its header) | — |

Facts worth knowing: the capture saw 68 distinct colours; the last new one appeared at 12.3 min and none in the
following 8 min, so coverage looks saturated but is not proven. A stray coin registered at 20:27 of the recording
and later frames were excluded. The 16-colour default palette has no green (Bub's `#00bb00` maps to a teal,
mean error 2.37 dOklab x100); `palette16.json` is not yet validated against gameplay frames.
