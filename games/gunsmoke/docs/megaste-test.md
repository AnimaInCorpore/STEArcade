# Gun.Smoke: Darklord's Mega STE test

Gun.Smoke combines hardware scrolling on both axes, many Blitter sprites and three shooting directions. The focused
package identifies the executable and exercises the previously untested human input path. It does not establish
the cause of Darklord's earlier unidentified-game crash or certify the whole game.

## Delivered build

Run from the repository root with the locally supplied ROMs and normal toolchain:

```sh
venv/bin/python games/gunsmoke/tools/megaste_test.py --verify --verify-machine megaste \
  --out build/gunsmoke-megaste/package-v2
```

Output: `build/gunsmoke-megaste/package-v2/GUNMSTE.ZIP`. Give Darklord this archive and its
[operator instructions](megaste-instructions.txt). The executable is `GUNSMOKE.TOS`, avoiding the GEM desktop mouse
pointer. `BUILD.JSN` contains its SHA256, source hashes, build ID and flags; `GUNSMOKE.MAP` identifies native crash
addresses. `SOURCE.ZIP` retains the diagnostic hooks and shared timing/input source. The package contains no autoplay,
replay or lives cheat. A normal build is also regenerated at `run/gunsmoke/GUNSMOKE.PRG`.

Previously delivered version 1 build ID: `9e77235103519092`; executable SHA256:
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

## Darklord's return, 2026-11-09

Archive `GUNSMOKE(1).ZIP`, SHA256 `8c3a5491d16720bd1f9328795d1ebad686158d6b72686bf951278b8010ad89f5`,
matches the delivered version 1 manifest. It identifies a Mega STE, US TOS 2.06 (`os_conf=0000`) and a 60 Hz
desktop. All four CPU-mode samples are `$1F` (low bits 3: 16 MHz/cache on); exit phase is 01 and exception-vector
restore mismatches are zero. The run has 884 VBLs, 878 arcade ticks, 378 pictures, two startup fallbacks, zero late
events, zero late-PC entries and 25,255 split Blitter passes. The last quantities are decoded as eight words plus
one long from `COUNTERS.BIN`, not ten independent counters. The report shows joystick packet activity but no key
presses and only release `$7E`; it cannot confirm the reported coin/start trial came from this particular saved run.

The photographs show widespread colour/pattern corruption in the test build. Zero late counters do not prove that
the 50/60 Hz writes hit the Shifter's sub-line timing windows, and framebuffer contents were not captured in this
return. Do not mark physical scanout, US timing, or the complete graphics path as verified from these counters.
The older release's 200-line crop is separate from this new corruption; the game renders a 256-line picture.

### Confirmed diagnostic logger bug

`ikbd_byte` promises only **d0.b** at the joystick payload callback. The old `mt_joy` subtracted one from d0.w and
used that full word as an index into a two-byte OR-mask array. Header and payload normally arrive in separate ACIA
interrupts; foreground execution changes D0 between them. For example, a payload arriving with d0.w=`$3402` writes
13,313 bytes past `mt_joysticks`, into unrelated game memory, rather than updating port 1. This was reproduced with
the delivered version 1 native executable. It is an actual memory-safety bug, not proof that it caused every
photographed defect. Previous tests exercised the byte decoder but disabled host joysticks and missed this path.

Version 2 masks the callback selector to eight bits before indexing. The new `megaste_input_test.py` drives the
actual ACIA ISR with a separate interrupt for every header and payload. It covers all 256 stale upper-byte values
on both ports, all 256 payload values on both ports, register preservation, bounded RAM writes, keyboard make/break
events and Esc release. It fails on the delivered version 1 binary and passes after the correction.

```sh
venv/bin/python games/gunsmoke/tools/megaste_test.py --verify --verify-machine megaste \
  --out build/gunsmoke-megaste/package-v2
venv/bin/python games/gunsmoke/tools/megaste_input_test.py build/gunsmoke-megaste/package-v2
```

No border constants or renderer code are changed by this correction. An additional live-input run on the ordinary
8 MHz STE path recorded one late top event; the legacy STOP/ACIA interaction remains a separate limitation.
`--verify-machine megaste` explicitly confines this package's validation to the intended Mega STE target while
retaining both machine tests in the default `--verify` workflow. Physical confirmation of corrected graphics is
still required, and native US 60 Hz open-border operation is not provided.

Version 2 build ID: `997e584eddc94ee0`; executable SHA256
`7e201327954eebb0a0f5f0f69c5c761185445993dac22243328774b068594ec2`. Both normal and simulated 60 Hz startup Mega STE
runs passed four additional rounds of keyboard stress with zero late events and restored CPU mode/exception
vectors. The split-IRQ test passed 1024 packet cases plus neutral packets, keyboard make/break and Esc release.
This confirms the logger correction in native execution; it does not certify the physical game's scanout.

ST2VGA-type adapters generally preserve Atari video timings and require a 15 kHz-capable display, rather than
scaling the game into a VGA raster: see the [manufacturer's timing explanation](https://docs.sidecartridge.com/st2vga-family/)
and [Centurion's ST2VGA r4 specification](https://centuriontech.eu/product/st2vga-r4/). The exact Dell model and its
input status remain useful for checking cropping/scaling. Do not blame the monitor for a confirmed diagnostic
memory write or infer full 50 Hz overscan compatibility merely because an older cropped game displays.
