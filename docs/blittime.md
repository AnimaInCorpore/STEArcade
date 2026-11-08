# Focused Mega STE Blitter timing probe

`BLITTIME.TOS` investigates the remaining short-pass difference after Hatari's
Blitter bus-clock correction. It runs automatically and writes `BLITTIME.TXT`.
The distributable is `build/blittime/BLITTIME.ZIP`; the plain-text operator
instructions are [blittime-instructions.txt](blittime-instructions.txt).

The target is a Mega STE. The small executable needs roughly 340 KiB of private
RAM, rather than the large full diagnostic's 4 MiB configuration. No game ROMs,
external graphics, sound, screen changes, input or BMP files are needed.
The `.TOS` extension selects console launch mode and hides the desktop pointer.

## What the previous return establishes

In Darklord's DLTEST 4 return, cached 16 MHz zero-NOP setup kernels took 241 and
234 TOS 200 Hz ticks; the bus-clock-corrected Hatari took 226 for both. Those
15/8 tick differences amount to about 9.2/4.9 extra 8 MHz bus cycles per pass.
The gap is almost constant across the added-NOP profiles. Payload correctness
was already established by native compares and six pixel-exact BMP matches.

The new control tests found that Hatari's cached idle Blitter-register loop is
faster than the same stores to RAM. `src/cpu/memory.c` maps IO as
`CE_MEMBANK_FAST16` based on an STF measurement. The Mega STE 16 MHz wrappers in
`src/m68000.c` still charge four CPU cycles for its uncacheable FAST16 accesses.
That represents half the duration of four 8 MHz bus cycles.

A private candidate charges eight CPU cycles for accesses to `$FF8A00-$FF8A3F`
in those 16 MHz wrappers, leaving other IO regions and start countdowns alone.
Using the original DLTEST kernels, this moves cached timings to:

| Family; NOPs 0/1/2/4/8 | Darklord | Candidate Hatari |
|---|---|---|
| Destination writes | 241 / 247 / 254 / 268 / 294 | 239 / 246 / 253 / 266 / 292 |
| Immediate destination RMW | 234 / 241 / 247 / 261 / 288 | 233 / 240 / 246 / 259 / 286 |

All drawing checks pass. The remaining 1–2 ticks in cached mode are much smaller
than the old discrepancy. This is evidence for the register-access hypothesis,
not a hardware measurement of the register bus handshake. The authoritative
Hatari remains on the confirmed Blitter bus-clock fix; the additional MMIO
change stays private pending Darklord's independent controls.

The canonical emulator finding and its status are recorded in F030Arcade's
`third_party/hatari/doc/megaste-blitter-timing.txt`. The probe's design and
operator/build workflow live here.

## Measurement design

There are 65 profiles, repeated twice at 8 MHz/cache off, 16 MHz/cache off, and
16 MHz/cache on: 390 rows. Each profile has 16 batches of 1,024 passes, 16,384
passes total. Source addresses are reset between batches; source content is
periodic across each pass. Neither source generation nor reference painting,
output checking, console updates or disk I/O is inside a timed interval.

| Kind | Sequence |
|---|---|
| 0 | Destination long, Y-count word, control-byte start, alternating destinations |
| 1 | Y count, byte start, immediate ADD.W of the advanced destination register |
| 2 | Same RMW, with a busy fence before reading the advanced destination |
| 3 | Destination/Y writes and a word start that also writes skew |
| 4 | Destination/Y writes, HOG preload, then BSET of busy |
| 5 | Unshifted full copy with full end masks |
| 6 | Idle Blitter-register writes with busy clear; no transfer |
| 7 | The same idle loop writing ordinary private RAM |

Policy 0 uses normal TOS interrupt handlers, plus the small measurement Timer A
ISR. It covers kinds 0/1, four planes and 0/1/2/4/8 post-start NOPs. Policy 1
uses minimal HBL/VBL/Timer C handlers during timing, with only Timer A and
Timer C unmasked at the MFP. It covers kinds 0–4 with 4/8/12 Y rows and 0/2/8
NOPs, full copy with 4/8/12 rows and 0/8 NOPs, and both idle controls with 0/8
NOPs. Interrupts are restored before each checkpoint or console call.

Masked passes use HOP 2 / OP 3, prepared first/last masks and all four planes
per piece. The three payloads cost 80/160/240 data-bus cycles; Mega STE
8-cycle grant plus 4-cycle release keeps the largest at 252. Full-copy payloads
cost 64/128/192. BSET includes an additional HOG preload write; a busy fence
includes polling. Comparisons between those families include the instruction
and ordering changes and must not be called pure arbitration measurements.

Timer A runs at 2.4576 MHz / 200, reload 256, giving 81.380208 us/count and
about 48 overflow interrupts/second. An ISR extends its count. Atomic snapshots
include a pending rollover and re-read the data counter after detecting it.
The counter uses the MFP crystal, independently of the CPU setting and TOS
Timer C. Each mode starts with a one-second calibration against 200 TOS ticks;
per-case MFP counts, TOS ticks and VBLs are also recorded. The timer semantics
follow the [Motorola manual](https://www.nxp.com/docs/en/reference-manual/MC68901UM.pdf).
The same small Timer A handler runs under both interrupt policies.

If Timer A is active or has a pending/in-service interrupt, the program skips
running and saves the reason. It does not take over an existing timer task.
It also skips an already busy Blitter. It restores CPU setting, Blitter
registers, Timer A vector/configuration and original interrupt handlers/masks
on normal completion. Other timer data/control registers are never changed.

The screen shows progress and an estimated countdown between timed profiles.
No console operation or countdown update interrupts a kernel.

## Correctness and report interpretation

An independent CPU shifter/mask painter constructs expected words from the
source pattern and constant masks, outside timing. Every profile compares the
whole 128 KiB private destination area, including unused memory and guard
words. RMW batches reset the destination so even erroneous low-word addressing
stays within the program's private destination bank for the tested sequences.
The RAM-only control additionally checks the stored source pointer, destination,
Y count and control value. No AND/OR Blitter pass pairs are used.

`CASE` rows include mode, interrupt policy, repeat, profile ID, kind, row count,
NOP count, passes, MFP counts, TOS ticks, VBLs, bad-word count, first differing
word offset/expected/actual, speed register before/after, kernel PC, source
address and destination address. Values are hexadecimal. `FFFFFFFF` means no
first bad destination word. A RAM-control field failure is counted separately
and can leave that sentinel unchanged. Compare matching build/profile IDs.
The build ID and batch/repeat counts are embedded in the report.

The host analyser rejects incomplete, duplicated or reordered profiles,
inconsistent final counts, wrong build IDs, CPU-mode changes and failed clock
calibration. It retains drawing failures as explicit failed results rather than
silently discarding them. `RESULT.TXT`/`RETURN.TXT` summarise policy, payload,
start-family and idle-control comparisons; the JSON retains every sample.
Timing disagreement is not an automatic hardware-health failure.

A hardware return distinguishes the candidates:

- A larger idle-MMIO cost with the expected RAM-control timing supports missing
  peripheral access waits; compare with the candidate emulator's same profiles.
- A residual proportional to payload size suggests transfer clock or bus cost.
- A nearly constant difference per pass suggests setup/start/arbitration.
- A difference that follows the interrupt policy points to handler/OS overhead.
- RMW errors or changes eliminated by a fence expose completion/ordering issues.
- MFP/TOS disagreement points to the timekeeping path before blaming drawing.

## Build, verify and analyse

```sh
venv/bin/python tools/blittime.py --verify --out build/blittime
venv/bin/python tools/blittime.py --out build/blittime --report RETURNED/BLITTIME.TXT \
    --reference build/blittime/HATREF.TXT
```

`--hatari PATH` selects an explicit emulator. `--quick` is a developer smoke
configuration, one batch and one repeat, and is not the hardware package.
Production validation must use the actual 390-row distributable build.

The ZIP contains 8.3 outer filenames, the executable, CRLF ASCII instructions,
build/hash metadata, source archive and the selected Hatari reference report.
`MMIOREF.TXT`, when supplied, is the private candidate's report, not an expected
hardware answer. Both emulator reference reports must come from the same
executable/build ID as the hardware package.

To include a separately validated candidate report without rebuilding the
already verified executable:

```sh
venv/bin/python tools/blittime.py --package-only --out build/blittime \
    --candidate-reference build/blittime-mmio/HATARI/BLITTIME.TXT
```

Packaging checks its build/profile identity and drawing results. A source
change requires rebuilding before `--package-only` can be used.

## Validation, 2026-11-08

The actual distributable executable passes all 390 profiles in the selected
bus-clock-corrected Hatari and the private eight-cycle-MMIO candidate. Both
reference reports are included, with matching executable/build identities.
All guards and output comparisons pass; the three one-second clock checks
and each profile's MFP/TOS/VBL comparison pass. In the selected emulator,
the largest MFP/TOS elapsed disagreement is below one 200 Hz tick. Cached
idle-MMIO is about 3.38 us/pass in that build and 4.38 in the candidate;
ordinary RAM is about 5.01 in both. This is an emulator contrast for the
hardware probe to resolve, not a new hardware result.

A private fault-injection build writes `$DEAD` into a guard word after each
timed run. All 195 smoke profiles detect exactly one bad word at offset zero,
expected `$3333`, actual `$DEAD`. The analyser also rejects a removed profile,
a duplicate profile and a wrong build ID. ZIP CRCs, all manifest hashes,
8.3 outer names, ASCII/CRLF instructions and both reference identities were
checked. The private source/object/emulator experiment is temporary; the
candidate patch and compact results are retained under
`build/blittime-investigation/`.
