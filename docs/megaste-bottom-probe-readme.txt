MEGA STE - BOTTOM-BORDER TIMING PROBE 1
======================================

WHAT IT DOES
------------
The top border stays open. Ten numbered bottom-pulse tests use the same
frozen Gun.Smoke picture. Each runs for ten seconds, with a four-second
TOP-only recovery stage before and after it. Each stage has a countdown.

CPU: 16 MHz with cache ON for the whole probe. Video: 50 Hz.
No gameplay, runtime Blitter drawing, palette changes or disk I/O occur
while the probe owns the display. Original settings are restored on exit.

RUNNING IT
----------
1. Extract BOTTOM.ZIP into a NEW folder on a writable disk.
2. Clean-boot as before. Keep the same ST2VGA and monitor setup.
3. Have your phone ready, then double-click BOTTOM.TOS.
4. Let it run automatically for about two and a half minutes. A video of
   the complete run is ideal. Include the stage label in photos/video.
5. It returns to the desktop. Please ZIP and return BOTTOM.TXT, together
   with the video/photos and your observations.

No key presses are required. Esc (press/release) stops early and restores
settings. Do not press F10; this probe uses phone recordings, not captures.
Use a fresh folder for another run; it refuses to overwrite BOTTOM.TXT.
If it stops before showing the picture, please photograph the message.

WHAT TO LOOK FOR
----------------
B00 TOP through B10 TOP are recovery stages: the bottom stays closed.
Lower cropping here is EXPECTED. Please note whether the picture becomes
clean again after each pulse test, or whether corruption persists.

P01 OLD repeats the previous pulse method, with a defined Timer-B edge.
P02 REF synchronizes one line earlier and waits one cached scanline.
The remaining tests vary one timing parameter from P02:

  P03 E20   start about 20 video cycles earlier, same width
  P04 E10   start about 10 video cycles earlier, same width
  P05 L10   start about 10 video cycles later, same width
  P06 L20   start about 20 video cycles later, same width
  P07 W13   shorter pulse, DBF count 13 (reference 17)
  P08 W15   shorter pulse, DBF count 15
  P09 W19   longer pulse, DBF count 19
  P10 W21   longer pulse, DBF count 21

These are exploratory timings, so some may crop, corrupt, flicker or
briefly lose sync. A failed timing is still a useful result. Please tell
us which P numbers look clean AND show the full lower picture/player,
which flicker, and whether any TOP recovery stage stays corrupted.
The picture does not move; only labels/countdowns change.

REFPIC.BMP is the clean source picture for PC viewing. It cannot record
the physical video fault. Please use your phone for that comparison.

LOG DETAILS FOR THE DEVELOPER
-----------------------------
All numbers are hexadecimal. STAGE indexes are the sequential phases
0..20, alternating B00/P01/B01/P02/.../P10/B10.
STAGE fields after the index:
 frames, bad CPU-mode samples, optional late-frame DMA sample count,
 min/max DMA counter offset, unexpected late video-register samples,
 changed RAM words outside HUD, Timer-A fallbacks, late top/bottom events,
 completed flag, first/last raw CPU register, first/last AER, bad edge samples.

CASE fields after the index:
 seconds, low gate (2=TOP recovery,0=bottom pulse), family (0=old,1=delayed),
 start DBF count, pulse DBF count, P number (0=recovery).

AER original/selected/end/restored logs all four bytes. Bit 3 is explicitly
cleared for the DE falling edge throughout the probe, and restored on exit.
CPU raw readbacks may differ in non-mode bits; low bits must remain 3.

RESTORE rows log address, size in bytes, expected, actual, comparison mask,
then masked XOR. A nonzero XOR is a defined-bit mismatch. Raw differences
outside the mask are retained without declaring a mode failure. MFP/video
registers, all six replaced vectors, 16 palette words, AER and (if used)
Timer-D data are checked individually. This should identify the previous
probe's single aggregate mismatch rather than hide it.

Timer D is used only if originally idle, with no pending/service IRQ. If
unavailable, DMA and late video-register samples are NOT exercised; zero
samples are not a pass. Late-border counters do not measure exact cycles.
Physical photographs/video remain the important result.

SOURCE.ZIP contains the exact native inputs. To rebuild on a development
PC after extracting it, with vasm and vlink on PATH:

 vasmm68k_mot -m68000 -Fvobj -quiet -nowarn=2047 -I. \
   -o bottom.o bottomprobe.s
 vlink -b ataritos -s -o BOTTOM.TOS -MBOTTOM.MAP bottom.o

BUILD.JSN and SHA256.TXT identify this build. Emulator checks characterize
the intended sweep; no timing here is claimed to be a physical fix yet.

The small S/W readout is a nominal delay offset and DBF width count, not
a measured physical time. P01 uses the previous method; compare P03-P10
with P02 for the independent parameter changes. Every timing transition
is latched just after VBL, so no bottom pulse sees half-updated settings.
Host Python verification tools require the STEArcade checkout; the native
sources and generated inputs above rebuild without the original ROMs.
