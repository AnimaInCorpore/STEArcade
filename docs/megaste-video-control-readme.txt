MEGA STE - CONTROLLED VIDEO TEST 1
=================================

Purpose
-------
Compare the SAME frozen Gun.Smoke picture with three border settings.
The picture comes from a verified, clean RAM capture of Darklord's game.
There is no gameplay or Blitter drawing during this test.

All three stages use 16 MHz WITH cache enabled and a 50 Hz video mode.
The screen address, 256-byte line stride, palette and picture stay fixed.
The test restores your original CPU/video settings when it finishes.

How to run
----------
1. Extract the ZIP into a NEW folder on a writable disk with free space.
   Please clean-boot as for the previous tests. Keep the same monitor and
   ST2VGA setup for this run, so we change only one thing at a time.

2. Double-click VIDCTRL.TOS. No key presses or joystick input are needed.
   Please have your phone ready to photograph or film the screen.

3. Watch each stage for 20 seconds. A label and countdown appear in the
   left side band. The entire run lasts about one minute:

   A CLOSE - both borders closed.
             Only the upper part of the picture is visible.
   B TOP   - top border open, bottom closed.
             More of the picture should become visible.
   C BOTH  - top and bottom borders open.
             The full 256-line picture should become visible.

   Cropping in A and B is EXPECTED. The picture is frozen: the gunman
   does not move. Only the label and countdown change. Please look for
   displaced colours, scrambled pixels, horizontal jumps, or flickering
   border bands, particularly when the stage changes.

4. The program returns to the desktop automatically. Please wait for it
   to finish before opening files. Esc (press and release) stops early
   and restores the settings, but an uninterrupted run is most useful.

5. Please send VIDCTRL.TXT and one phone photo of EACH stage, or a short
   video covering the transitions. Include the A/B/C label if possible.
   Please say which stages look clean, when corruption first appears,
   and whether it persists or flickers. Mention any monitor warning or
   loss of sync. Keep using the same display setup for this comparison.

REFPIC.BMP is the clean, full source picture for viewing on a PC.
It is not a capture of what the monitor actually displays. Your phone
photos/video are essential here, even if this BMP looks correct.

Repeating the test
------------------
Use another fresh folder, or rename the old VIDCTRL.TXT first. The test
refuses to overwrite an existing report. It also refuses to run on a
non-Mega STE or when Timer A/B is already in use; clean-boot and retry.
If no report is created, please photograph the message on the desktop.

Report details (for the developer)
----------------------------------
All numbers in VIDCTRL.TXT are hexadecimal. STAGE 0=A, 1=B, 2=C.
Restoration register/vector mismatches should be zero.
After the stage number, columns are:
 frames, bad CPU-mode samples, late-frame DMA sample count,
 min DMA counter minus base, max DMA counter minus base,
 unexpected video-register samples, changed RAM words outside HUD,
 Timer-A fallbacks, late top events, late bottom events,
 completed-stage flag, first CPU register, last CPU register.

CPU register low bits must be 3 (16 MHz + cache). Timer-A fallbacks in
stage A are expected: the closed display has too few lines for Timer B.
The late-frame counter sampler uses Timer D only if it was idle; if not,
that sampler is omitted and the three visual stages still run normally.
DMA sampling excludes the first eight VBLs after each stage transition.
Its counter is sampled before the Shifter's late-frame address reset;
A/B should stop at 200/229 lines, while C is still reading black guard
rows. The report alone cannot certify correct physical scanout.

SOURCE.ZIP contains the exact native source and generated image/kernel
inputs for this build. BUILD.JSN and SHA256.TXT identify the executable.

Native rebuild from SOURCE.ZIP (developer)
----------------------------------------
Extract SOURCE.ZIP into its own directory. With vasm and vlink installed:

 vasmm68k_mot -m68000 -Fvobj -quiet -nowarn=2047 -I. \
   -o videoctrl.o videoctrl.s
 vlink -b ataritos -s -o VIDCTRL.TOS -MVIDCTRL.MAP videoctrl.o

The generated kernel has test-only frequency-write gates: a zero opens a
border, a two leaves it closed, through the same timed instruction path.
Delay constants are retained from the shared port handlers. This isolates
border opening with no game/palette interrupts or runtime Blitter work;
it does not certify every timing interaction of the full game.

Pinned Hatari's late counter reads can include an additional 96-byte
LINEWID skip in some horizontal phases below the closed display. Keep
min/max readbacks as telemetry; the phone pictures determine whether
actual pixels are damaged. The physical result is still to be measured.
