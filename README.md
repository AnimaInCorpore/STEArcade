# Z80 arcade games on the Atari STE

Static translation of Z80 arcade programs to 68000 code, with a Blitter based renderer, running on an unexpanded
8 MHz Atari STE (4 MB).  Each port is a reference machine written from the MAME driver, a whole-program translation
checked against it in lock-step, and a runtime that delivers the arcade's interrupts at the vertical blank and draws the
arcade's tiles and sprites (sprites with the Blitter: one blit per sprite line, masks as end masks).

| game | CPUs | state |
|---|---|---|
| [Donkey Kong](games/dkong/README.md) | Z80 | plays at 50 fps, pixel exact against MAME |
| [Galaga](games/galaga/README.md) | 3 x Z80 (+ simulated 51xx/54xx) | attract mode and play, 25-43 fps in the light phases, 9-21 with the full formation |
| [Bubble Bobble](games/bublbobl/README.md) | 3 x Z80 + MC6801 (its own firmware, translated) | boots into the attract mode, exact logic and picture; too slow to play on a plain STE, no sound |

## Layout

    engine/            shared: Z80 / 6801 emulators and disassemblers, translators (z80x, translate, m6801x), STE simulator on
                       Musashi (sim.py), Blitter sprite code generator, shared runtime (rt/rtlib.s), paths and toolchain
    games/<game>/      src/ 68000 source, tools/ reference machine + generator + build + tests, ref/ analysis scripts, README
    tools/             hatari.sh (run, press keys, screenshot, dump memory in the F030Arcade Hatari), windows/ (PowerShell helpers)
    docs/              architecture.md, porting-guide.md, reference/ (68000 and Z80 manuals)
    assets/roms/       ROM archives (extracted/ holds the unpacked files)
    build/ run/        generated code, assets, coverage data / the .PRG with its ROM files (not in git)
    legacy/falcon030/  the earlier Falcon030 plan (routine-by-routine replacement), kept for reference
    port.py            build / test / run / cover / mame for every game

## Quick start

    python3 -m venv venv && venv/bin/pip install numpy pillow machine68k      # once
    python port.py list
    python port.py build bublbobl && python port.py run bublbobl shot@20      # screenshot in /tmp/hrun
    python port.py test bublbobl                                              # reference vs translation vs renderer

Reading order: `docs/architecture.md` (how a port works), `docs/porting-guide.md` (method, MAME check, lessons),
then the game README.  Rules that hold for all ports: translate whole programs, no silent NOPs (unknown instructions
are a deliberate failure), check the reference against MAME before building graphics, and verify with the pinned
F030Arcade Hatari build.  MAME source: `F030Arcade/third_party/jsm68kdisassembler/third_party/mame`.
