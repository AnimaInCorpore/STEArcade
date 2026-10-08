# Workload and target feasibility (measured on the host reference, `bublboblr`)

Reproduce: `python tools/bbprofile.py bublboblr` (demo gameplay, frames 2000-2300; colours: frames 700-3600).

| measure | result |
|---|---|
| main Z80, non-idle | ~4,100 instructions/frame = 46.8 % of its T-states (the rest is the `jr $` wait at $01ED) |
| sub Z80, non-idle | ~1,400 instructions/frame = 15.5 % (rest is the `jp $000A` wait) |
| MCU | runs its handler once per frame; not profiled yet |
| screen colours | up to **25 distinct RGB values** in one frame, drawn from up to **9 palette groups** |
| strip tiles walked per frame | ~2,230 (most are transparent; real opaque tile count not yet measured) |

## What this means (analysis, not yet a decision)

* About 5,500 Z80 instructions per frame x 59.19 fps = ~325k Z80 instr/s for both CPUs. At roughly 5-6
  68000 instructions per translated Z80 instruction that is ~1.9M 68k instr/s: more than a plain 8 MHz
  68000 delivers (~1 MIPS), comfortable for a 16 MHz 68030 (Falcon030) even before native routine
  replacement. Block ops (`ldir`, ~360 bytes/frame to objectram alone) are cheap to replace natively.
* 25 distinct colours/frame exceeds the STE's 16 (4096-colour palette, 16 on screen). The Falcon030 shows
  all of them exactly. On an STE the options are per-scanline palette changes or colour merging — both
  deviate from the original picture.
* The sprite/strip engine draws up to 192 strips of up to 64 tiles; the renderer, not the Z80 code, is
  likely the real cost on either machine.

Conclusion for planning: the **Falcon030 target in `PORTING.md` is the one that can plausibly keep full
speed and exact colours**; an STE version would need explicit, documented fidelity trade-offs.
Open decision for the project owner.
