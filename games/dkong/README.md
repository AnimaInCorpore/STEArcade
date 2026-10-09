# Donkey Kong, Atari STE

First port and the reference design for the Blitter sprite renderer (`docs/architecture.md`).  Paths relative to
`games/dkong/`: `src/` (`dkong.s` runtime, `render.s` tiles, `sprites.s` Blitter sprites), `tools/` (`machine.py`
reference machine, `dkong_pens.py` palette dumped from MAME, `gen.py`, `assets.py`, `build.py`, `fullrun.py`, `nmitrace.py`,
`bench.py`, `frametimes.py`), `ref/` (analysis scripts, committed coverage logs, `mame_cmp_dkong.py`).

State: Donkey Kong runs from the static Z80 -> 68000 translation with the Blitter renderer, exact against the reference
emulator and MAME, 50 fps in play (see "Measuring" in `docs/architecture.md`).

## Build and run (macOS)

    python3 -m venv venv && venv/bin/pip install numpy pillow machine68k      # once, in the repository root
    python port.py cover dkong          # coverage + palette pens the translator seeds from (~15 min on 8 cores)
    python port.py build dkong          # -> run/dkong/DKONG.PRG (+ the four CPU ROM files)
    python port.py run dkong shot@30    # Hatari (F030Arcade build), screenshot at 30 s

The coverage and pens runs reproduce the committed logs (`ref/*.log`) exactly (3766/4949 PCs, 155/115/154 pens).
`VASM`/`VLINK` select the toolchain; the default on macOS is `~/Work/f030dsp3d/tools`.  The program needs about
2.3 MB of RAM (sprite data 0.9 MB, the dispatch table 256 KB).

Tests: `tools/fullrun.py 3000` (whole program, lock-step against the Z80 reference, the NMI injected at the idle loop head),
`tools/nmitrace.py N` (the NMIs from frame N on, instruction by instruction, names the first diverging instruction),
`engine/sprite_blit_test.py` (sprite code against independently masked pixels, DK and Galaga).  `tools/bench.py`
stops with `KeyError: 'pe'` on a conditional RET/CALL on the parity flag (not translated).

The game itself is not deterministic across builds: its idle loop counts its spins (`inc ($6019)`), so the attract
sequence and the demo play depend on how much CPU time a frame leaves.  Frame counts of two builds therefore show different
game phases; what compares exactly is a frozen frame of one build against the reference renderer.

## Translator speed (2026-10-08)

`z80x.FAST` (no runtime change was needed: Donkey Kong has no `exx` / `ex af,af'`; `fullrun.py` reads IY from a2).
`engine/xprof.py dkong` (1500 NMI frames of `fullrun.py`): translated code 5.2k -> 4.8k cycles a frame (1.08x): the
code was lean (16 cycles a Z80 instruction, mostly memory moves), the gain is the direct returns and the flags.
`tools/bench.py` knows the swapped BC and the 65536 entry dispatch table now (it failed 61 cases since BC was swapped);
the engine's `engine/xbench.py` covers every opcode and memory layout.  Known, not from this change: `fullrun.py`
stops at frame ~1030 (`z80_badjump`, d7 = $2BD) on the commit before it too; `port.py test dkong` runs 3000 frames.
