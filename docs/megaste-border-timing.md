# Mega STE 16 MHz/cache-on border timing

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
