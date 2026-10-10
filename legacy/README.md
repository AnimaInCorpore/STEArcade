# legacy

Superseded or unmaintained material, kept for reference. Nothing here is built, tested or referenced by `port.py`.
The Falcon030 converter's outputs (`src/generated/cpu_*.asm`, `src/dkong_initial*.asm`, `src/test.asm`) and the
routine disassemblies (`analysis/*_disasm*.txt`) were removed from the repository and its history: they are ROM
content; the notes that mention them remain.

| folder | what it is |
|---|---|
| `falcon030/` | the first plan: Donkey Kong on the Falcon030 by routine-by-routine native replacement (PORTING.md, analysis notes, 400+ routine skeletons). Replaced by whole-program static translation to the STE. |
| `ste-blitter-branch/` | the Donkey Kong Blitter renderer work of the former `codex/blitter-renderer-optimizations` branch (commit `f95bb40`), kept verbatim when upstream rewrote the renderer. See its README. |
| `ste-scratch/` | scratch scripts and logs from the Donkey Kong STE work under the old `ste/` layout (before the move to `engine/` and `games/<game>/`). They import the old `ste/tools` modules and will not run as they are. |
