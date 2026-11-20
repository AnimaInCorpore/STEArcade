# Gun.Smoke: Darklord's Mega STE test

Gun.Smoke combines hardware scrolling on both axes, many Blitter sprites and three shooting directions. The focused
package identifies the executable and exercises the previously untested human input path. It does not establish
the cause of Darklord's earlier unidentified-game crash or certify the whole game.

## Delivered build

Run from the repository root with the locally supplied ROMs and normal toolchain:

```sh
venv/bin/python games/gunsmoke/tools/megaste_test.py --verify --verify-machine megaste \
  --out build/gunsmoke-circle
```

Output: `build/gunsmoke-circle/GUNMSTE.ZIP`. Give Darklord this archive and its
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

The following historical test 2 reproduction uses commit `2af9094`; the current builder produces test 3.

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

## Test 2 return, 2026-11-11

`GS_TEST.ZIP` SHA256 `193c568614236470191fbfd2ad1f298a450c02250ecc5efabddb5f26def3b27b` contains the exact test 2
manifest. The return records a Mega STE with US TOS 2.06, original/restored 60 Hz desktop, normal exit, zero
exception-vector mismatches and enhanced pads disabled. CPU samples are `$1C / $1F / $1F / $1C`: the diagnostic
selected 16 MHz/cache on and restored its original low mode bits 0 afterward.

There are 9959 VBLs (about 199 seconds at nominal 50 Hz), 11195 arcade ticks, 6758 pictures, 293281 split Blitter
passes, two startup fallbacks, zero late events and zero late-PC entries. Coin/start make and break events are now
present (`06`, `02`); joystick port 1 OR mask `$8F` includes all directions and fire. Port 0 records `$06`. This
confirms the corrected input log is functioning on the physical machine; it does not prove that every control or
sound was exercised. The report and manifest were retained under `build/darklord-gunsmoke-2026-11-11/`.

Darklord reports persistent colour/pattern corruption and a flickering, partly visible bottom border. Therefore
fixing the real logger bug did **not** resolve the display fault. Zero late-event counters over this longer run
still do not certify Shifter fetch alignment or the sub-line 50/60 Hz pulse windows. Neither a defective Mega STE
nor an incompatible Dell monitor has been established. Do not replace the renderer or apply an unmeasured delay
change from these symptoms alone.

### Continuing the game

The original [Romstar/Capcom operator manual](https://arcarc.xmission.com/PDF_Arcade_Manuals_and_Schematics/Gunsmoke.pdf),
Game Operation / Buy-In Feature (also available as [searchable manual text](https://www.scribd.com/document/1006042005/gunsmoke-manual-arcade)),
requires a credit followed by Start before the continue timer expires. The port's player-1 sequence is **tap 5,
then tap 1**. Fire, Enter and Return do not map to Start. The authoritative MAME 0.286 driver permits continues
with DSW2 bit `$40`, which is set in the port's `$FF` default. The manual establishes the intended control sequence;
this investigation does not claim a newly completed native continue regression.

### Test 3: compare RAM with scanout

Test 3 leaves the border constants and renderer algorithm unchanged and retains 16 MHz/cache on during play. It
captures a completed, unpublished frame plus the state that produced it, avoiding a comparison against newer game
logic or a different triple buffer. No disk calls occur during gameplay. One capture is automatic at/after arcade
tick 700; **F10** requests up to two more. Capture copying briefly delays the foreground, while video interrupts
continue. Files are saved only after restoring the hardware on exit:

* `GSCAP0.BIN` through `GSCAP2.BIN`: 96-byte big-endian header, 43008 bytes of planar picture (336 pixels, 256 rows,
  168 bytes/row), 2048 bytes of text RAM and the 512-byte latched sprite list. The header includes fine scroll,
  tick/VBL, draw/display addresses, control/layer/scroll state, selected CPU mode and the 16-colour palette.
* Matching `.BMP`: ordinary Windows 4bpp, bottom-up, 320×256 image with a 16-entry palette. The fine-scroll crop is
  applied, and STE palette bit ordering is converted to RGB. File size 41078 bytes; raw `.BIN` size 45664 bytes.

The capture is **RAM, not monitor scanout**. A photograph remains necessary for the visible corruption; the capture
also permits independent CPU rendering of the exact scene instead of guessing at a screenshot's game state.

```sh
venv/bin/python games/gunsmoke/tools/megaste_test.py --verify --verify-machine megaste \
  --out build/gunsmoke-megaste/package-v3
venv/bin/python games/gunsmoke/tools/megaste_capture.py returned/GSCAP0.BIN
venv/bin/python games/gunsmoke/tools/megaste_capture_test.py build/gunsmoke-megaste/package-v3
```

The analyser requires the locally prepared, matching Gun.Smoke graphics/palette assets. It checks the native BMP
against captured planar RAM, reconstructs text, scroll/layers and the arcade sprite latch, then compares the
320×256 RAM picture (including clean side bands) against `tools/video.py` through the approved colour map. It
writes a small JSON report and independent reference PNG; a mismatch also writes a difference image and fails.
`BUILD.JSN` records the reference asset hashes; place it beside returned captures so the analyser checks its local
assets before deciding whether the picture differs. Missing asset provenance is marked in the JSON report.

Native capture/BMP conversion passed all 16 fine-scroll values, alternating whole-word offsets and a 64 KB source
crossing; registers are preserved and the program requests 3495426 bytes including its basepage, below 3.7 MB.
Both normal and simulated 60 Hz startup Mega STE runs produced three exact RAM/BMP/reference captures and zero
late counters. Their warmed video traces checked 7824 and 7825 pulses inside the existing top/bottom windows.
One earlier instrumented 60 Hz startup run recorded one late-top event; its three RAM captures were also exact.
That run is retained under `first-v3-60start/` in the investigation folder and is not discarded by the later passes.
Capture copying/cache layout can perturb timing; this diagnostic does not establish uninterrupted physical
scanout or resolve that intermittent emulator event. The synthetic 60 Hz startup still uses DE TOS/PAL master
clock, not a US oscillator model. Physical test 3 results remain outstanding.

Test 3 build ID `05bfd5bcf9a03493`, executable SHA256
`38b1ad968706130b4cd457d4631484f46bf95865c7ff40b6a3dae66af387f0cd`. The non-diagnostic program is byte-for-byte
identical to its pre-capture build. Negative controls deliberately corrupt a RAM pixel and its matching BMP pixel
and confirm that the independent renderer rejects them; palette words/RGB are also checked against the approved
palette, rather than colouring both sides with a potentially corrupted captured palette.

## Test 3 return, received 2026-11-14

`GS_TEST(1).zip`, SHA256 `8fb40d191e1c6191de5aad991d640a841d9a0aa0f1ead5b4986bdde673859ef6`, includes the exact
delivered executable, map, manifest and source archive; all six bundled file hashes match. The manifest's eight
reference asset hashes also match the local reference inputs. Returned files and analyser output are retained in
`build/darklord-gunsmoke-2026-11-14/`.

All three returned captures pass independent comparison: **zero differing pixels out of 81920 per image**, correct
palette words/RGB, and BMPs identical to the decoded planar RAM. This includes the 48-pixel side bands. Each header
records CPU mode `$1F` (low bits 3), physical text base `$40564`, fine scroll 0 and hardware line-width/fine-scroll
readback `$30/$00`. The programmed 48 extra words plus the 160 visible bytes give the renderer's 256-byte stride.
The first image is an attract/title picture; the second is the ranking screen; the third is gameplay. These are
physical-machine framebuffer results, not substituted Hatari screenshots.

Capture provenance needs care. The final `GUNTEST.TXT` records **one** capture, with no F10 make/break event. Slot 0
is the automatic capture (tick 701, VBL 704). Slots 1 and 2 have earlier DOS modification times (88 seconds before
slot 0), matching an earlier run rather than this final report; they remain valid renderer evidence. Do not claim
that all three were captured in the final run or that a phone photograph is pixel-aligned with any of them.

The final run has 3554 VBLs (about 71 seconds at nominal 50 Hz), 3736 arcade ticks, 1981 pictures and 111466 split
Blitter passes. It exits normally, restores CPU/video state and exception vectors, and records three top-border
fallbacks, **one late top event**, and zero late palette-on/bottom/palette-off events. `LATEPC.BIN` has zero entries
because that existing logger covers late Timer B events, not the late Timer A top event. Its empty log does not
contradict the top counter.

Together with Darklord's corrupted live-screen photographs, the clean, reference-exact RAM images narrow this
failure to the path from a completed picture to visible output. Screen-base/counter updates, fetch/plane alignment,
border pulses, live palette writes and the adapter/display remain candidates. They do not yet identify a specific
cycle error, prove a Hatari defect, or certify the full renderer for every frame. A renderer replacement is not
supported by this result.

The next useful control is the same frozen picture, address, stride and palette at 16 MHz/cache on, comparing
ordinary 50 Hz video, top opening alone, then top plus bottom opening. Compare the common visible region and record
video-counter/fetch alignment as well as event lateness. This isolates display changes without changing the drawing
algorithm or using an 8 MHz fallback. No timing constants have been changed on the strength of these photos.


## Test 4 on the Mega STE

Gun.Smoke uses CIRCLE's warmed top pulse at U078/W08 and its delayed bottom
pulse at D101/W17 when running at 16 MHz with cache enabled. Timer B counts
falling display-enable edges. The delayed routine polls one edge earlier and
waits one cached scanline before the bottom pulse. Gameplay exposed one late
bottom event with the old three-line interrupt lead. The game now arms the
handler four lines ahead and allows enough polls for that lead. The border
pulse settings stay fixed throughout play.
