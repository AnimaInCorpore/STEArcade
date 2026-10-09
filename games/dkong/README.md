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

## Sound (2026-10-09)

The arcade's 8035 sound board (tunes on `$7C00`, effects on `$7D03-$7D05`, death on `$7D80`) plays one mono DAC
stream, so it is pre-rendered and played by STE DMA sound (`src/sound.s`, a few hundred cycles a frame, estimated, not measured).
`tools/sound_capture.py` records the board in MAME (the main CPU parked on a `jr $`, a Lua script writes the
ports; needs a full MAME build, default `C:\Arbeit\F030Arcade\third_party\wolfmame-0162\mame.exe`, `$MAME`
overrides), `tools/sound_convert.py` turns the recordings into `build/dkong/dk_sound.s` / `dk_sound.bin`: 8 bit
signed, 6258 Hz (the board low-passes at ~1.9 kHz), 317 KB.  `build.py` runs both only when their output is missing
(~1 min).  Two MAME runs are not sample-exact: a rebuild differs in ~0.3% of the bytes, by a few steps.

What the driver copies from the 8035 (measured in MAME): a one-shot tune starts when `$7C00` changes to it and
plays to its end (the game holds it 3 frames); a background tune (03 04 08 09 0B) loops while `$7C00` holds it and
starts again from its beginning after a one-shot; a rising edge on a pin starts its effect; the newest sound
wins.  The background loops are one measured period each (2.29 s barrels ... 4.92 s out of time), seams in silence.
Walk, jump and stomp (`$7D00-$7D02`) are discrete circuits on the arcade board, independent of the 8035: YM
channels A, B, C, one (tone period, volume) a 50 Hz frame, restarted by a rising edge.  `tools/sound_ym.py`
measures the patches from the MAME recordings (pitch by autocorrelation, stomp: the mean of its own random
5.5-13 ms cycles per frame; level by RMS, matched through Hatari's measured YM volume table and a gain measured in
Hatari, -11.9 dB) -> `build/dkong/dk_ym.s`, plus A/B files in `build/dkong/sound/ym/`.  Loudness and pitch follow
the arcade frame by frame (< 1 dB a frame); the tone is brighter: the arcade circuits are integrated (stomp has
95% of its energy below 200 Hz, nothing above 800 Hz), a YM square puts 7-19% above 800 Hz, and the pitch only
changes 50 times a second (the stomp's real cycles change every 4-6 ms).

`build.py -D AUTOSTART=150` inserts a coin at frame 150 and starts a game a second later; with Hatari's
`--avirecord true --sound 44100 --run-vbls 3000` it records coin, intro, How high, the barrels loop and the
deaths (the AVI says 60 fps for the 50 Hz frames).

## Translator speed (2026-10-08)

`z80x.FAST` (no runtime change was needed: Donkey Kong has no `exx` / `ex af,af'`; `fullrun.py` reads IY from a2).
`engine/xprof.py dkong` (1500 NMI frames of `fullrun.py`): translated code 5.2k -> 4.8k cycles a frame (1.08x): the
code was lean (16 cycles a Z80 instruction, mostly memory moves), the gain is the direct returns and the flags.
`tools/bench.py` knows the swapped BC and the 65536 entry dispatch table now (it failed 61 cases since BC was swapped);
the engine's `engine/xbench.py` covers every opcode and memory layout.  Known, not from this change: `fullrun.py`
stops at frame ~1030 (`z80_badjump`, d7 = $2BD) on the commit before it too; `port.py test dkong` runs 3000 frames.
