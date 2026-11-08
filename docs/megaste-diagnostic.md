# Darklord's Mega STE diagnostic — version 4

For the remaining setup-time difference, use the smaller, unattended
[BLITTIME follow-up](blittime.md). It records independent MFP/TOS clocks,
register-access controls and start/payload variants; the original diagnostic
below remains the broader correctness and screen-capture test.

**Start `DLTEST.TOS` and let it finish. No keyboard, mouse, or joystick input is
needed to advance the tests.** It saves a detailed report and nine stage-specific
BMP captures on a Mega STE. Physical controls and display/sound quality can be
checked optionally while it runs.

The `.TOS` extension selects console application launch mode so the desktop
hides its mouse pointer throughout the tests.

The target is **16 MHz with cache enabled on a Mega STE**. The same tests run
first at 8 MHz without cache and 16 MHz without cache to identify which setting
changes the result. Ordinary STEs run the 8 MHz path only.

## 1. Prepare the machine

1. Use a colour display and a machine with **4 MB RAM**. Copy the whole archive
   into a new, writable folder on the hard disk. Keep the `REF` folder.
2. Leave the normal AUTO programs, disk driver, and accessories enabled for the
   first run: we want to test the setup that showed the game problem.
3. Close other applications. If you want the optional sound check, connect the
   normal audio output at a comfortable volume. No audio response is requested.
4. Double-click **`DLTEST.TOS`**. The report is **`DLTEST.TXT`**, in the same
   working folder. Use an empty folder for each run to preserve earlier results.

There are no game ROMs in this package. The bob graphics are original procedural
32 × 32 sprites prepared using the mask grouping and source-order method used
by stefastbobs2 and STEArcade's shared sprite preparation.

## 2. Let the automatic tests run

Allow several minutes. A busy or apparently motionless screen during the RAM
and Blitter tests is normal. Every completed group is checkpointed to disk.
Do not reset just because a screen has been unchanged for a few seconds.

| Stage | What happens | What to expect / optional action |
|---|---|---|
| Machine information | Records TOS, machine cookie, memory allocation, original screen and CPU state. | No action. Unsupported machines or monochrome displays are reported as skipped. |
| TOS keyboard baseline | A text screen lasts 30 seconds. | Optional: tap `5`, `1`, arrows, Space and Control. Control alone is a modifier and produces no TOS console character. |
| CPU and RAM | Checks arithmetic, 1,024 code modifications/fetches, 37 RAM patterns, byte lanes, word transitions, and long writes. | No action. Only the program's private 128 KiB RAM region is written. |
| File transport | Creates a private 128 KiB file, writes it, closes/reopens it, reads and compares it, then deletes it. | No action. An existing `DLIO.TMP` is left untouched and that stage is skipped. |
| Bob setup timing | Runs two 65,536-pass kernel families for each post-start padding variant: 0, 1, 2, 4, and 8 NOPs. | No action. This specifically checks the short destination / Y-count / start sequence and Mega STE bus-grant/cache behaviour. |
| Blitter case matrix | Runs 1,308 fixtures in 24 setup/address configurations per CPU mode. | No action. Checks all shifts, masks, colours, side clipping, forward/reverse increments, and source/destination 64 KiB crossings. |
| Palette and normal screen | Opens 320 × 200 at 50 Hz, walks every palette-register bit, and draws shifted perforated strips. | Optional: note missing colours, flicker, displaced planes, or corruption. |
| Input under the game parser | The patterned screen remains for 30 seconds. | Optional: tap the game keys, move/click the mouse, then move/fire a joystick in port 1. Eight indicators latch for `5`, `1`, Up, Down, Left, Right, Space, Control. |
| Bob scenes | Draws 32 deterministic scenes with 26 objects; 24 can be visible and two are deliberately culled. | Watch for holes, clipped side edges, overlap order and moving positions. Every visible, background and guard word is automatically compared. The last scene stays visible for 10 seconds. |
| Sound | Plays a short YM beep, then a DMA tone on the left followed by a different tone on the right. | Optional: note missing, swapped or distorted sound. Audibility is not inferred from register checks. |
| Open borders | Displays a 320 × 256 test picture using the ports' actual synchronized border handlers, first idle and then under short-HOG Blitter load. | Expect a complete picture, thin edge markers, a top colour strip, a centre cross and diagonals. Photograph missing lines, plane slips, flicker, or unstable borders. |

The stages from CPU/RAM onward repeat for:

1. **Mode 0 — 8 MHz, cache off.**
2. **Mode 1 — 16 MHz, cache off.**
3. **Mode 2 — 16 MHz, cache on.**

The speed/cache register is recorded at the beginning and end of each mode. The
open-border stage retains that mode; it does not switch to 8 MHz as a workaround.
The program restores the original screen, palette, interrupt vectors and
CPU/cache setting on normal exit.

### If no one touches the controls

The automatic tests still complete and save their files. Missing physical
input is **NOT EXERCISED**, not a hardware failure. Joystick masks of zero and
no mouse movement are inconclusive in an unattended run. Sound and scanout
quality remain **OBSERVATION ONLY** unless you supply notes or photographs.

### Optional F10 capture

During the patterned input screen, **F10** snapshots its current framebuffer
and palette. The file write is deferred until that timing-sensitive phase has
ended. If F10 is not used, an automatic snapshot is taken at the end instead.
Each mode has its own filename; a capture never overwrites a different mode.

### Countdown display

Each stage has a small countdown in the upper right:

- `7-0020s` means stage 7 has **20 actual seconds remaining**.
- `5~0008s` means an **estimated 8 seconds remain** in stage 5's workload.
- `5~----s` means the first timing sample is still being collected.

Stage IDs are 0 keyboard baseline, 1 CPU, 2 RAM, 3 file, 4 setup timing,
5 Blitter matrix, 6 palette, 7 raw input, 8 bob scenes, 9 sound, A open borders,
and B the final bob observation hold. Estimates can change as samples improve.
Short sub-second stages may finish before the display reaches a second update.
Tight setup kernels update the display only between kernel profiles; the tested
instruction sequence is not changed. Underlying pixels are saved and restored
from the ACTUAL framebuffer, and countdowns are excluded from saved BMPs and
reference comparisons.

## 3. Return these files

After the test finishes and gives control back to the desktop, zip the output
folder, or at least return:

| File | Contents |
|---|---|
| `DLTEST.TXT` | Inventory, stage checkpoints, CPU modes, individual test results, failure details, input bytes/counts and timing measurements. |
| `INPT0.BMP`, `INPT1.BMP`, `INPT2.BMP` | The input/strip screen at 8 MHz, 16 MHz and 16 MHz/cache. Size: **320 × 200**. These can differ because the input indicators are interactive. |
| `BOBS0.BMP`, `BOBS1.BMP`, `BOBS2.BMP` | The same fixed final bob scene in each mode. Size: **320 × 200**. These are suitable for exact reference comparison. |
| `OPEN0.BMP`, `OPEN1.BMP`, `OPEN2.BMP` | The full border-open test picture in each mode. Size: **320 × 256**, without scaling. |

On an ordinary STE, only the files ending in `0` are produced. The diagnostic
uses standard uncompressed, indexed **4-bit Windows BMP**, including its palette;
it can be opened on a PC without Atari-specific image software.

Please also provide a short note containing:

- Mega STE RAM size, TOS version, disk driver and hardware modifications;
- which game executable originally failed, if it becomes known;
- any screen or sound problem, and the CPU mode in which it appeared;
- whether the controls were exercised or the run was unattended.

**A BMP captures memory, not the monitor's scanout.** A border-timing or analogue
video fault may leave a perfectly correct BMP. Return a photograph or short
video as well when the monitor is visibly wrong.

## 4. If the test stops or reports a failure

1. Keep **`DLTEST.TXT`**, including a partial file. Its last `BEGIN` entry
   identifies the active test and CPU mode. Unexpected CPU exceptions include
   the vector, PC, stack, load address and registers, with best-effort cleanup.
2. Keep every BMP that was written. Note the last screen and how long it remained.
3. If the machine hangs, a reset may be necessary; a hard hang cannot run cleanup.
4. Repeat from a clean boot without AUTO applications or accessories, using a
   **different output folder**. Keep the disk driver needed to access the folder.
5. Return both runs labelled **normal setup** and **clean boot**. Do not replace
   the original evidence with the second run.

If TOS cannot launch this larger diagnostic because of low memory, run the small
companion **`MSTEDIAG.TOS`** and return `MSTEDIAG.TXT` plus the TOS error. This
optional companion has a live display and needs a key to exit; it is separate
from the unattended DLTEST suite. On a Mega STE, its pad probe should say the
games ignore enhanced pads. Raw phantom pad readings are expected because the
Mega STE has no enhanced joystick sockets.

## 5. How the report separates results

- **Automatic comparisons:** CPU arithmetic/fetches, private RAM, file contents,
  palette readback, sprite bytes and coordinates, transparent holes, guard areas,
  untouched background, CPU mode retention and BMP write results.
- **Timing measurements:** setup-kernel elapsed 200 Hz ticks; matrix MMIO write
  counts, pass counts and MFP ticks; VBL counts; shared border late-event counters
  and video-counter samples. Interrupt and arbitration costs are included in
  wall-clock measurements. They are not presented as pure CPU execution time.
- **Optional input observations:** per-key press/release counts, mouse movement
  and buttons, accumulated joystick direction/fire bits, first 128 raw IKBD bytes,
  overrun observations and transmit timeouts.
- **Human observations:** monitor stability, analogue colour/signal quality,
  sound quality and channel routing. A zero error count does not prove these.

Every matrix failure records the first fixture ID, byte offset, expected word
and actual word. `BLITCASE.JSN` describes the fixtures and `SCENES.JSN` lists
all sprite coordinates and priority order. The bob scene comparison checks the
entire buffer, including guard rows; it is not just a sprite checksum.

The setup kernel uses **three MMIO writes per pass**: destination long, Y-count
word, start byte. The register-destination family has nominal MC68000 instruction costs of **28 CPU
cycles**, before instruction-fetch, memory waits and arbitration. The second
family performs a destination-register read/modify/write immediately AFTER
start, like the fast bob method: **32 nominal CPU cycles** for its three MMIO
instructions. It checks an additional 8 KiB leading guard region and 384-byte
trailing guard for incorrect destination advancement. Its two-word,
four-plane masked payload uses **80 bus cycles** before bus grant/release. Post-
start padding is unrolled; there is no per-pass busy poll hiding the shortest
sequence. The full test's measured ticks must not be confused with either figure.

Matrix profiles are full setup/word start; reused setup/byte start; and reused
setup with 1, 2, 4 or 8 NOP padding-loop iterations. Each profile runs with
neither boundary crossing, source crossing only, destination crossing only,
and both crossing. These longer fixture routines are correctness tests; the
separate short setup kernel is the relevant tight-loop timing test.

## 6. Compare returned images with Hatari

The package's `REF` folder contains independent CPU reference images and
verified native captures from the pinned Hatari build. Fixed bob scenes and
border images have matching contents at each CPU mode. Hatari monitor PNGs are
also retained to inspect the emulated open-border scanout.

On a computer with Python and Pillow, run:

```text
python3 COMPARE.PY RETURNED_FOLDER --reference REF
```

The tool writes `comparison/comparison.json`, counts changed RGB pixels, gives
the changed rectangle and first differences, and writes magenta difference PNGs.
Missing files and different dimensions are reported explicitly. Dynamic input
screens are retained for inspection and are not compared to a fixed scene.

Passing this suite narrows the fault; it does not certify the whole computer.
The private RAM test does not cover all installed RAM, and the GEMDOS round-trip
does not replace a full disk/ACSI integrity test. The original unknown game and
its exact failing instruction still need to be identified.

### Cache-on border correction in version 4

Version 3 exposed a cropped cache-on display despite correct BMPs. Version 4
uses the corrected shared border handler: compact warmed timing kernels,
HBL synchronization and bounded MFP masking. It retains 16 MHz/cache-on
throughout the test. The pinned Hatari run now opens the complete picture
with no missing cache-on frames under mixed short-HOG load. Both the native
BMP and actual monitor capture match the reference; the visible timer is
excluded from the monitor comparison.

The load alternates 80, 192 and 240 data-bus-cycle passes (at most 252 cycles
including Mega STE arbitration). The border stage retains its minimal clock
handler and post-picture observation hook. Pending MFP sources are preserved.
16 MHz without cache retains the earlier timing path and can still show
legacy missed-event counts; this correction targets cache-on operation.
Physical Mega STE results are still needed. See
[Mega STE timing verification](megaste-border-timing.md) for measurements.

## Maintainer: build and verify

```text
venv/bin/python tools/dltest.py --verify
```

VASM comes from `engine/paths.py`. `HATARI` and `TOS` override the pinned emulator
and TOS 2.06 paths. Output is `build/dltest/DARKLORD.ZIP`. The shortened verification
uses the same automatic cases and shortens only the timed observation periods.
Reports, BMPs, monitor PNGs and emulator logs remain in the build directory.
The source and fixture hashes are recorded with the package.
