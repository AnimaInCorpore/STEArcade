# Mega STE 16 MHz/cache-on border timing

## Playable ports, 2026-11-20

Darklord saw the full CIRCLE card with correct colours on each fresh start at U078/W08
and D101/W17. All 38 playable ports now use those settings on the Mega STE. The game
selects 16 MHz with cache on during takeover and restores the desktop mode on exit.
Pac-Mania currently consists of reference work and has no STE executable.

In the pinned Hatari, 26 game executables each passed 1,790 consecutive frame checks
after startup, with both frequency pulses in their scanline windows. The verifier
read back cache-on mode during the run and observed the return to the 8 MHz desktop.
The runs exercise attract and keyboard input on a 50 Hz display. They cover portions
of each game. Physical evidence for these settings comes from the CIRCLE card.

Hatari ran 23 of those games with 4 MB. Dragon Spirit, Mr. Heli and R-Type used their
14 MB development configuration. Dragon Spirit needed shorter background Blitter passes
under load. R-Type's refillable sprite colour pool is 128 KiB smaller to leave room for
the current executable and TOS. Ordinary 8 MHz STE checks on 1942, Donkey Kong and
Kung-Fu Master observed both border pulses and zero writes to the Mega STE speed register.

The following ports have the common runtime changes and still need an executable
test with their ROMs: Defender, Dig Dug, Donkey Kong 3, Jail Break, Juno First, Mario
Bros., Mikie, Roc'n Rope, Rolling Thunder, Super Basketball, Xevious and Yie Ar Kung-Fu.
Each uses a border configuration exercised by at least one of the other ports.

To repeat a game check with locally supplied assets:

```sh
venv/bin/python games/1942/tools/build.py
venv/bin/python tools/megaste_game_test.py 1942 run/1942/1942.PRG
```

The tool writes the executable hash, timing exceptions, clock observations and a
screen capture under `build/megaste-rollout/<game>/`. Use `--ram 14` for the
larger development builds.

## Original automatic timing selection (November 2026)

The shared `engine/rt/borders.s` now selects a separate top/bottom timing path
when `_MCH` identifies a Mega STE and `$FF8E21 & 3` is 3. It reads that register;
it never writes it. Foreground code, Blitter drawing and the border handlers
continue at 16 MHz with cache enabled.

The 8 MHz instruction delays remain in the legacy path. 16 MHz without cache
also retains its prior path; this change specifically fixes cache-on operation.
The shared handler is used by the registered ports, including the HUD and
video-address-switching variants.

## Cause and change

A Blitter bus request invalidates the Mega STE's unified external cache. A
linear NOP delay therefore takes different amounts of video time when its
instruction words are warm or cold. Doubling the NOP count opened the wrong
line or restored 50 Hz outside the shifter's preload window under drawing load.

The cached top path approaches the HBL before the opening line using Timer A,
reads a compact 32-byte kernel into the cache, then waits for the final HBL and
executes short DBF delays. MFP masks are saved and cleared during this bounded
approach: `STOP #$2100` must be woken by HBL, not by an ACIA or Timer C interrupt.
The masks, registers and pending sources are restored afterward. The guarded
wait is below one millisecond, shorter than one IKBD serial byte; enable and
pending registers are not cleared. Startup can use two fallback frames before
the bottom-to-top Timer A chain is established.

The cached bottom path warms its short pulse before polling Timer B. The poll
and all palette/HUD/video-switch scheduling continue to use the existing early
synchronization scheme. No long HOG passes or extra erase/mask passes are added.

## Pinned Hatari verification

The emulator is the repository's pinned 2026-10-20 build, TOS 2.06, 4 MB Mega STE.
These are emulator results; confirmation on a physical Mega STE remains needed.

| Check | Result |
|---|---|
| 50 seconds idle + 50 seconds mixed HOG drawing | 5,000 traced top pulses, 5,001 bottom pulses; zero missing post-picture frames after warmup |
| Source/destination Blitter loads | 80, 192 and 240 data-bus cycles; maximum 252 including Mega STE grant/release |
| Top frequency pulse | 60 Hz at line 33, cycles 469–475; 50 Hz restored on line 34, cycles 12–20 |
| Bottom frequency pulse | 60 Hz at line 262, cycles 418–428; 50 Hz restored on line 263, cycles 6–16 |
| CPU/cache control writes in the long test | `[0, 3, 0]`: setup, target mode, then original desktop restoration; no write during border rendering |
| Monitor scanout, idle and loaded | Every picture pixel matches the independent 320×256 reference, excluding the deliberately visible countdown |
| Code/cache-index shifts | Pads of 3,408, 3,424, 8,192 and 12,288 bytes: zero missing frames, all pulse writes inside the required windows |
| Full diagnostic | CPU, RAM, file, palette, Blitter matrix, bob scenes and BMP comparisons pass in all three modes; cache-on border opening confirmed with zero missing frames |
| Registered ports | All 22 assemble; executables and matching default maps rebuilt |
| Time Pilot, real game runtime | 1,201 VBLs, two startup fallbacks, zero late top/palette/bottom/off events; real CPU write selects `$03`, sampled unchanged during play |

Cycles in the table are 8 MHz video-clock units, not 16 MHz CPU instruction
cycles. At each vertical check the frequency remains 60 Hz through cycle 500;
50 Hz is restored before the STE's next-line cycle-36 preload check.

For the Time Pilot test, a temporary startup fixture executes an actual
supervisor-mode `move.b #3,$ffff8e21.w`. A debugger `w b` memory poke does not
invoke Hatari's hardware write callback and is not a valid way to select this
CPU/cache mode. The production shared handler never selects the CPU mode.

The 8 MHz before/after diagnostic preserves the ordinary pulse windows. Its
extra Timer C clock can still wake the legacy STOP sequence: both before and
after recorded six missing frames in the same 300-frame mixed-load check.
That pre-existing legacy behavior is not the cache-on path fixed here, and
must not be represented as new 8 MHz coverage or as physical-hardware evidence.

## Reproduce

### Physical return and emulator clock correction, 2026-11-08

Darklord's DLTEST 4 return (4 MB Mega STE, TOS 2.06) has zero drawing errors;
all six fixed bob/open-border BMPs match Hatari and the independent CPU
renders. At 16 MHz/cache on, its 300-VBL border test has two startup fallbacks,
zero late counters and zero missing post-picture callbacks after warmup. The
8 MHz and uncached 16 MHz paths have four and five missing callbacks. Input
devices were not exercised; framebuffer captures do not establish monitor
stability.

The return also exposed missing conversion from 8 MHz Blitter bus cycles to
16 MHz CPU cycles in the authoritative F030Arcade Hatari's
`Blitter_AddCycles()`. That checkout is now corrected and rebuilt. Most of
the setup-time discrepancy disappears, but a remaining short-pass difference
is unresolved. Its canonical evidence and limits are in F030Arcade's
`third_party/hatari/doc/megaste-blitter-timing.txt` and the corresponding
`DEBUGGING.md` section. The historical verification table above predates this
emulator correction; it must not be used as a calibrated hardware timing model.

`tools/dltest_setup_timing.py --hatari PATH --out DIR --hardware DLTEST.TXT`
builds a focused `SETUP_ONLY` launcher using the original kernels, runs all
30 profiles, checks drawing results and saves timings with build hashes.
Ordinary DLTEST builds do not enable that launcher. Returned files and
before/after results are retained in `build/darklord-setup-investigation/`.

### Commands

```sh
venv/bin/python tools/dltest_timing.py --mode 2 --seconds 50 --check-control
venv/bin/python tools/dltest_timing.py --mode 2 --pad 3424
venv/bin/python tools/dltest.py --verify --verify-machine megaste --unattended
```

`dltest_timing.py` checks the native report, every warmed top/bottom pulse,
optional CPU-control writes, the BMP and the actual monitor captures. It keeps
small JSON summaries, PNGs and compressed traces under `build/border-timing/`.
`--borders PATH` permits before/after comparison against a saved handler.

The detailed local reports are `build/border-timing/long-cache/timing.json`,
`build/border-port-check/assembly.json` and
`build/border-timing/timeplt-game/verified.json`. These generated files are not
source fixtures. The updated `build/dltest/DARKLORD.ZIP` contains the standalone
console diagnostic and fresh reference captures for real-hardware comparison.

## Controlled fixed-picture return test (2026-11-14)

`tools/videoctrl.py` builds `VIDCTRL.TOS` and `VIDCTRL.ZIP` for Darklord's
next physical comparison. It uses the independently verified gameplay frame
from the latest return's `GSCAP2.BIN`, with ten black guard rows, the same
256-byte stride, fine scroll zero and constant palette. Its three automatic
20-second stages are closed borders, top only, then top and bottom. CPU
low bits remain 3 (16 MHz/cache on) throughout; the original mode is restored
only after the test. There is no game execution or runtime Blitter work.
A small CPU-written label/countdown occupies the otherwise black side band.
The closed and top-only stages intentionally crop the lower picture.

The builder creates an instrumented copy of `engine/rt/borders.s`; production
source is unchanged. The fast first frequency writes use D3 (0 enabled,
2 disabled) plus a NOP in place of CLR, loading the gate before warming/polling.
The top kernel's extra word is explicitly warmed. Bottom D3 is saved/restored.
Both enabled stages follow the same timed paths and retain the shared delay
constants. Constant palette and absence of game/Blitter traffic are deliberate
isolation controls, so a clean result is not full-game timing certification.

`VIDCTRL.TXT` records per-stage VBLs, CPU samples, RAM integrity outside the
HUD, border fallback/late counters, optional late DMA counter ranges, and
native register/vector restoration mismatches. No file I/O happens during
the display stages. Timer D is used only when originally idle with no pending
or in-service interrupt; normal TOS 2.06's serial Timer D is left running and
its sampler is reported unavailable. Report zero samples as unavailable,
not as successful DMA verification. The optional sampler runs before the
STE's line-310 address reset; a VBL sample would already see the reset base.
The pinned Hatari `Video_CalculateAddress` adds LINEWID when read in the right
horizontal border before its vertical end test, allowing an extra 96 bytes
below a closed display. Preserve those readbacks without calling them a
pixel mismatch.

Build and verify from the checkout:

```sh
venv/bin/python tools/videoctrl.py --capture build/darklord-gunsmoke-2026-11-14/GSCAP2.BIN
venv/bin/python tools/videoctrl_test.py
venv/bin/python tools/videoctrl_test.py --fixture
```

The second verification uses a separate native launcher to select a 60 Hz,
16 MHz/cache-on starting desktop and an idle Timer D before Pexec of the exact
diagnostic. It exercises transition and optional-sampler paths with German
TOS 2.06; it does not emulate a US oscillator or certify Darklord's ST2VGA/Dell
scanout. The debugger takes screenshots/reads guest state and never pokes IO
or timing registers. Verification checks the full visible arcade region
against the independently verified reference (190, 219 and 256 picture rows),
frequency-pulse margins, CPU writes, per-stage native checks and restoration.
Retain the exact build IDs, executable/emulator hashes and results in the
ignored output's `BUILD.JSN` and `hatari*/RESULT.JSN`.

The operator instructions and BBCode forum draft are
`docs/megaste-video-control-readme.txt` and
`docs/megaste-video-control-message.txt`. Request `VIDCTRL.TXT` and phone
photos of all three stages or a transition video; `REFPIC.BMP` is the
source picture, not a monitor recording. No physical fix is inferred until
those observations return.

Validated build `d56cc302402067b6` (executable SHA256
`4417c7be9d191462cde70cdc39a29bce863db42a7a0e1a287b09f94d2e852f93`)
against the currently pinned Hatari `4be28430610455af9c313fc837312889ea0ecd22`
(binary SHA256 `c2b0b334200b47f8f6a952a7e821939fca9eb9afc70531ae2b1fe80cc486e3bc`).
Both startup cases passed: zero differences across the full 320-pixel hardware
window, including side bands/HUD/guards; zero RAM, CPU-mode, restoration or
late-border errors. Each stage recorded 1006 VBLs, including the final RAM
integrity scan. Active pulses stayed within the required windows (top line 33,
return on 34 before cycle 36; bottom line 262, return on 263 before cycle 36).
The optional sampler recorded 998 samples per stage with an idle Timer D;
normal TOS correctly left the active serial timer alone. A real emulated IKBD
Esc press/release exited early with mode/vector restoration checks passing.
The source inside the delivered archive rebuilt byte-for-byte, all outer
filenames fit 8.3, and archive checksums passed. Physical results remain pending.

## Physical VIDCTRL return (2026-11-15)

Darklord's `Downloads/VIDCTRL.ZIP` (SHA256
`b78cd176608ffe116dedb78af02fd8e7d44546083a07d60cb069094abd2d45a0`)
contains only `VIDCTRL.TXT`, reporting build `d56cc302402067b6`. There is no
returned executable to rehash. The report, original supplied photo bytes and
machine-readable findings are retained under
`build/darklord-videoctrl-2026-11-15/` (ignored).

| Stage | Physical photograph / operator observation | Report |
|---|---|---|
| A: closed | Clean visible picture; expected lower crop | 1006 VBLs, 1006 Timer-A fallbacks |
| B: top only | Clean visible picture; more picture visible | 1006 VBLs, one startup fallback |
| C: top + bottom | Corrupted in both photos; bottom band changes, reportedly about every half-second | 1006 VBLs, no fallbacks |

All three stages completed with zero changed RAM words outside the HUD,
zero bad CPU-mode samples and zero coarse late-top/late-bottom counters.
Original/selected/end/restored CPU readbacks are all `$27`; first/last VBL
samples are `$47` in each stage. Both values have low bits 3, so there is no
reported transition away from 16 MHz/cache on. The report identifies TOS
2.06, `os_conf=0` (US), with fixed screen base `$056C00`, stride 256 and fine
scroll zero. Timer D was unavailable, so zero DMA/video-register samples are
**unavailable measurements**, not successful scanout/register verification.

The controlled result reproduces the failure without gameplay, animation,
runtime Blitter transfers, palette switching or file I/O during the display.
It localizes the observed trigger to enabling the bottom frequency pulse
while the top border is open, on this machine/display chain. The top-only
case is a working physical baseline at 16 MHz/cache on. It does not exclude
a display/converter reaction to the altered signal, identify an exact bad
cycle, or establish that every top-border timing variant is correct.
The existing late counters check line/event synchronization, not whether both
frequency writes fall inside the narrow Shifter window. Their zero values
do not certify the fine timing. A software-first investigation should keep
the working top path and CPU mode fixed and measure bottom pulse start and
width independently, with a top-only recovery baseline between variants.
The roughly half-second rhythm is an operator observation; no video or timing
trace establishes its period or clock source.

There is also **one aggregate restoration mismatch**. Test 1 does not log
which register/vector failed, so the error cannot be dismissed as harmless or
attributed to a particular register. Its full-byte comparisons include
`$FF8E21`, whose non-mode bits differ between read sites in this return even
though the two mode bits remain correct. A follow-up must log per-register
expected/actual/masked values and compare defined bits. The error is recorded
separately from the visual result; it does not prove a damaged Mega STE.

The Timer-B poll also assumes the DE falling edge but neither logs nor selects
MFP AER bit 3. The authoritative Hatari `MFP_ActiveEdge_WriteByte` and
`Video_TimerB_GetPosFromDE` explicitly model that selection. Record and control
that precondition in the next probe before interpreting a delay sweep.
The pinned emulator's Mega STE clock initialization still selects its PAL
master frequency, so a 60 Hz desktop launcher alone does not cover physical
US clock ratios. Do not tune the production handler or emulator into an
unmeasured presumed correction from these photos alone. No timing fix has yet
been physically verified by this return.

## Bottom-pulse sweep probe (2026-11-15)

`tools/bottomprobe.py` packages `BOTTOM.TOS`/`BOTTOM.ZIP` from the same
independently checked static Gun.Smoke frame. `tools/bottomprobe.s` enables
probe-only hooks in `tools/videoctrl.s`; `tools/bottomprobe.i` implements the
phase table and per-register logging. The original default VIDCTRL executable
still assembles byte-for-byte with its original generated build include.
Production `engine/rt/borders.s` and the special Hatari are not modified.

The top path is the same warmed gated kernel as VIDCTRL 1. All 21 phases keep
16 MHz/cache on and top open: B00 TOP (four seconds), P01 (ten seconds), B01,
P02, ... P10, B10. The total is 144 seconds plus about three seconds of RAM
checks/phase latching. Every timing transition waits for the next VBL after
the RAM check, then loads the new descriptor atomically with interrupts
masked. Short TOP recovery stages retain the same dummy frequency-write
path and close only the bottom, so recovery itself can be photographed.

MFP AER is saved, bit 3 is explicitly cleared for DE falling, and original,
selected, end and restored AER are reported. Every VBL logs CPU mode and AER,
including bad-edge counts. P01 uses the previous DE poll target/pulse method
with the width preloaded before the timed region. P02 polls one DE falling
edge earlier, then waits in a warmed DBF loop: initial count 101 has 101 taken
iterations at 10 CPU cycles plus the final 14, totalling one 1024-cycle CPU
scanline. This provides room for genuinely earlier as well as later starts.
P03-P06 vary only that start loop; P07-P10 vary only the pulse loop. The masks,
gates and changing parameters are loaded before the warmed/polled region.

| Probe | Nominal start change from P02 | Width DBF count | Hatari median start / duration (8 MHz units) |
|---|---:|---:|---:|
| P01 OLD | previous method | 17 | 420 / 104 |
| P02 REF | 0 | 17 | 415 / 104 |
| P03 E20 | -20 | 17 | 395 / 104 |
| P04 E10 | -10 | 17 | 405 / 104 |
| P05 L10 | +10 | 17 | 425 / 104 |
| P06 L20 | +20 | 17 | 435 / 104 |
| P07 W13 | 0 | 13 | 415 / 84 |
| P08 W15 | 0 | 15 | 415 / 94 |
| P09 W19 | 0 | 19 | 415 / 114 |
| P10 W21 | 0 | 21 | 415 / 124 |

These are emulator measurements, not physical calibration. Some trials
intentionally miss a safe window: P03 and P07 are cropped at the sampled
Hatari frames and sometimes open on other frames. They are useful negative
controls. Do not certify all ten scanouts as correct or install one of these
settings as a production fix without Darklord's photographs/video.

`BOTTOM.TXT` retains per-stage RAM/CPU/coarse late/optional DMA checks and
logs all restored registers separately as address, size, expected, actual,
mask and masked XOR. Non-mode CPU bits, unused video/MFP control bits and
unused palette bits are retained raw but excluded from failure comparisons.
All six replaced vectors are checked in full. There are 41 rows with serial
Timer D left alone, or 42 including Timer-D data when it was idle and used.
A native simulator regression checks that `$27` versus `$47` with mask 3
passes while a true mode-bit mismatch fails, and that palette/vector masks
preserve the same distinction.

Verification (`tools/bottomprobe_test.py`, `--fixture`, `--abort`) uses one
persistent guest-PC breakpoint, read-only guest snapshots and a blocking
host reply FIFO. It records every phase and derives the B/P timing runs from
the actual frequency-write gates/PCs. Start and duration changes are checked
independently against P02, with every recovery window compared to the reference.
The separate native startup fixture selects 60 Hz, cache on, an initially
rising Timer-B edge and an idle Timer D before Pexec; it verifies edge selection
and restoration without debugger IO pokes. It remains a PAL-master emulator
transition test, not US oscillator emulation. Full runs, Esc restoration and
native mask regressions passed on the current pinned Hatari; hashes, pulse
histograms, snapshots and reports are under `build/megaste-bottom-probe/`.

Build and verify:

```sh
venv/bin/python tools/bottomprobe.py --capture build/darklord-gunsmoke-2026-11-14/GSCAP2.BIN
venv/bin/python tools/bottomprobe_test.py
venv/bin/python tools/bottomprobe_test.py --fixture
venv/bin/python tools/bottomprobe_test.py --abort
```

The ZIP includes an ASCII/CRLF README, BBCode draft, reference BMP, manifest,
checksums and exact native source/generated assets. Native reconstruction
from SOURCE.ZIP must match the delivered executable byte-for-byte. All outer
filenames fit TOS 8.3. Request the complete BOTTOM.TXT and a phone recording
showing the P/B labels, specifically clean full-height P cases, flicker and
whether each subsequent TOP stage becomes clean again.

## Physical BOTTOM return (2026-11-17)

Darklord's returned ZIP has SHA256
`0fad2f34a1a6db2eb099899c644ddfaed407c2e736258d5af3513f412a2f4926`.
It contains only `BOTTOM.TXT`, which reports shipped build
`09b94f162a92fe95`. All 21 case descriptors match the build manifest.
The run completed all 7,347 VBLs with one startup Timer-A fallback and
zero changed image words, CPU-mode errors or coarse late-border events.
AER was `$04` before, during and after the run, confirming DE falling was
already selected. The serial Timer D was active, so the run has no video
counter samples. All 41 masked restoration checks passed. The only raw
readback difference was `$FF8E21` (`$27` expected, `$5F` read);
the two mode bits matched. This explains how the earlier full-byte check
could flag a mismatch, although that earlier report did not name the register.

The phone video shows clean, cropped B00 TOP at about 7 s. P01 briefly
shows the full picture at about 8.2 s. By about 8.3 s the picture is
scrambled above the bottom extension. B01 TOP crops the lower area as
intended, but the remaining picture is still scrambled at 20 s. The same
upper-image corruption is visible in sampled views of every later P and
TOP stage, including P10 at 142 s and B10 at 149 s. Several P stages show
a clean bottom strip below the scrambled area. The desktop looks clean at
155 s after the display blanks on exit. These are observations of the
complete display chain from the phone footage.

The in-run TOP intervals therefore fail to restore the clean baseline.
P02–P10 start after the fault has appeared, so the sweep cannot rank those
settings by whether they would trigger the fault from a clean start.
The emulator's clean TOP recoveries do not match this physical return.
Keep 16 MHz/cache on in the next measurement and run only one bottom
variant after a verified clean TOP baseline. A single P01 pulse followed
by clean-state recovery measurements would help distinguish a one-pulse
trigger from a fault that requires repeated pulses. Testing recovery
through a desktop mode transition and, if available, a second video path
would help distinguish the Atari video state from converter/display state.
The report is retained in `build/darklord-bottom-2026-11-17/BOTTOM.TXT`.

## Physical interactive PULSE return (2026-11-18)

Darklord returned five complete numbered session logs for build
`84826d544c50299b`. The ZIP SHA256 is
`edd7c0ff1598a36050e10d60ad85a177b02b6b04000b0ba45fde52ffac159059`.
There were 8 single-pulse trials (5 marked clean, 3 marked corrupted) and
two repeats (500 pulses each, both marked corrupted). Each trial used
family 0, the fixed P01 preset with width count 17. Its displayed D101
does not enter the legacy pulse timing. The report confirms cache-on
16 MHz during the trials, a Timer-B falling edge, and all 41 masked
restoration checks passing in each session. Timer D was unavailable for
video counter sampling. A single P01 pulse can reproduce the fault by the
operator's classification, and two full repeats failed the visual goal.

The phone clip shows the P01 repeat without obvious corruption of the
upper grid. At about 20 s its lower band starts white, red, green and
blue and lines up with the grid. At about 22 s and 28 s it reaches one
16-pixel cell farther left and starts grey, black, grey, white, salmon,
red and light green. After the repeat, TOP crops that band and the upper
grid looks clean. This clip shows a separate, local alignment symptom
from the persistent upper-picture scramble seen in the earlier sweep.

The band uses palette indices 1 through 14. If the Shifter consumes the
interleaved data starting one 16-bit word ahead, each group combines the
last three planes from the current cell with the first plane from the
next cell. The predicted indices from the preceding black margin are
8, 0, 9, 1, 10, 2, 11, 3, 12, 4, 13, 5, 14, 6, 7. The visible sequence
and extra cell agree with that model. This is evidence for a two-byte
slip in the displayed extension. It does not measure the physical write
cycles or identify the exact cause of the slip.

The five runs validate the P01 baseline. To compare timing methods in
the next run, confirm clean TOP, press P once to select the adjustable
reference (the P01 prefix disappears), leave D101/W17, and fire one
pulse. Run the repeat only after a clean single pulse. Report whether
the lower band stays aligned and keeps its expected colour order for
all ten seconds. The logs are retained under
`build/darklord-pulse-2026-11-18/`.
