# Gun.Smoke: Darklord's Mega STE test

Gun.Smoke combines hardware scrolling on both axes, many Blitter sprites and three shooting directions. The focused
package identifies the executable and exercises the previously untested human input path. It does not establish
the cause of Darklord's earlier unidentified-game crash or certify the whole game.

## Delivered build

Run from the repository root with the locally supplied ROMs and normal toolchain:

```sh
venv/bin/python games/gunsmoke/tools/megaste_test.py --verify
```

Output: `build/gunsmoke-megaste/package/GUNMSTE.ZIP`. Give Darklord this archive and its
[operator instructions](megaste-instructions.txt). The executable is `GUNSMOKE.TOS`, avoiding the GEM desktop mouse
pointer. `BUILD.JSN` contains its SHA256, source hashes, build ID and flags; `GUNSMOKE.MAP` identifies native crash
addresses. `SOURCE.ZIP` retains the diagnostic hooks and shared timing/input source. The package contains no autoplay,
replay or lives cheat. A normal build is also regenerated at `run/gunsmoke/GUNSMOKE.PRG`.

Validated build ID: `9e77235103519092`; executable SHA256:
`476237ae597b4b52e089892dbe9955ac1538aa945295f349ba6b7e1b7bddbadb`.

The helper selects low bits 3 of `$FF8E21` once after recognizing the Mega STE cookie. Drawing and border opening
retain 16 MHz/cache on. Disk reporting happens before hardware takeover and after restoration. Exit restores the
original CPU setting; the normal game also now restores exception vectors 2–11 that its crash handlers replace.
An independent pre-start snapshot verifies those vectors after exit.

`GUNTEST.TXT` records startup/normal-exit/crash phase, machine cookie, TOS version/country word, text load address,
CPU state, original/restored video sync, enhanced-pad detection, observed framed key presses/releases, standard
joystick packet masks and game counters. Missing physical joystick activity is **not exercised**, not failure.
See [the hardware input contract](../../../docs/megaste-input.md) for supported devices and primary sources.

## Validation, 2026-11-08

Corrected F030Arcade Hatari source `df3fe2b6a7fd0e6f7fc82614b8156e4eb2850aa0`, binary SHA256
`cd8952c77903744163ecd74737d71ddf31310fcb44729dcb85a7336c81f791a8`; 4 MB, cycle-exact/compatible CPU, TOS 2.06 DE.

The delivered executable passed keyboard coin/start, all four movements, three shots and normal Esc exit on:

| Configuration | Late top / palette on / bottom / palette off | Exit vector mismatches |
|---|---|---|
| Mega STE 16 MHz/cache on | 0 / 0 / 0 / 0 | 0 |
| STE 8 MHz | 0 / 0 / 0 / 0 | 0 |
| Mega STE, simulated 60 Hz startup, then game's 50 Hz screen | 0 / 0 / 0 / 0 | 0 |

The harness injects ST make/break scancodes through Hatari's IKBD event path, checks native active-low P1 bits while
held, and repeats the seven movement/shot controls four additional times. It checks selected/final Mega STE CPU
mode 3, restoration to the original mode, and disabled enhanced-pad support. All 256 byte values also passed the
native standard-joystick conversion routine. This last check does not exercise physical joystick wiring or serial
packet transport. Sound generation stays enabled, but host audio output is disabled in these automated runs.

Logic/reference: 1500 ticks, seed 4, equal RAM/video/latches/bank/sprite latch/text flags. Independent renderer:
20 consecutive frames from tick 850, seed 4, exact pixels. These limited regression checks supplement existing
coverage; they do not replace full-game verification.

### Timing guard

Live keyboard stress exposed occasional palette lateness with Gun.Smoke's former two-line lead. It now requests
three lines and a 240-iteration polling bound; the cached CPU can exhaust the old 120-iteration bound before three
lines pass. The handler still synchronizes to the same line ends, uses short HOG passes, and never selects 8 MHz
to open borders. Shared defaults remain two lines/120 iterations; compiling the default DLTEST before/after the
shared macro extension produced identical binaries (SHA256 `70689b7eaed310b31707137802f76c6e6aa486b7bffca758b2923121bd82835d`).

The complete 16 MHz replay trace checked 7957 top and 7957 bottom pulses after warmup. Top pulses begin on line 33
at cycles 471–475 and return to 50 Hz on line 34 at cycles 14–20. Bottom pulses begin on line 262 at cycles 418–428
and return on line 263 at cycles 6–16. All satisfy the STE line-start limit before cycle 36. Trace units are 8 MHz
bus cycles. Hardware confirmation of this game/input workload remains Darklord's next step.

### Speed comparison

```sh
venv/bin/python games/gunsmoke/tools/build.py
venv/bin/python games/gunsmoke/tools/megaste_bench.py --mode 0
venv/bin/python games/gunsmoke/tools/megaste_bench.py --mode 3
```

The separate benchmark retains the unchanged 9000-tick count/SYSTEM/P1 recording and its existing replay-only
lives cheat. CPU instructions select and sample the actual speed register; debugger I/O pokes are not used. Rates
come from VBL counts at nominal 50 Hz, not host execution time. Gameplay samples are 100-VBL windows whose initial
tick is at least 900; windows cover slightly different states because picture skipping differs.

| Metric | 8 MHz/cache off | 16 MHz/cache on |
|---|---:|---:|
| VBLs through recording end | 8156 | 7962 |
| Arcade ticks delivered (including terminal tick) | 9001 | 9001 |
| Pictures | 4156 | 4815 |
| Overall arcade ticks/s | 55.18 | 56.52 |
| Overall pictures/s | 25.48 | 30.24 |
| Gameplay window mean arcade ticks/s | 57.02 | 57.81 |
| Gameplay window mean pictures/s | 26.44 | 31.25 |
| Late events, all four counters | 0 | 0 |

This is an 18.2% gain in gameplay picture rate. Each run has two startup Timer A fallbacks; these are counted
separately from late events. Reports, compressed video traces, executable fixtures and screenshots remain under
`build/gunsmoke-megaste/full-mode0` and `full-mode3`.

## US machines and displays

The game uses raw Atari scancodes, not localized TOS character tables. US keyboard 5/1, arrows, Ctrl, Space and Alt
use the same controls. A US Mega STE still needs a colour display accepting **50 Hz** for this build. Native 60 Hz
open-border timing is not implemented here. An NTSC-only television is not a verified display path.

The additional startup fixture executes a real CPU write selecting 60 Hz before `mt_begin`, then runs the exact
delivered executable and checks restoration to 60 Hz. It uses DE TOS and Hatari's PAL master clock, not a US TOS ROM
or physical US oscillator. No US TOS 2.06 image was available locally. Therefore this checks a startup transition,
not full US hardware compatibility. Hatari's local `src/clocks_timings.c` declares PAL and NTSC master clocks but
selects `ATARI_MEGA_STE_PAL_MCLK` when initializing Mega STE. Do not equate a 60 Hz startup with emulating the US
master oscillator. TOS country/sync configuration is documented in the
[Atari Compendium, OS Configuration Bits](https://info-coach.fr/atari/software/_development/Atari-Compendium.pdf#page=158).
