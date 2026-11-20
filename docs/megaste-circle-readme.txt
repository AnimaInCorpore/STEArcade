CIRCLE.PRG - MEGA STE BORDER TIMING
==================================

CIRCLE replaces PULSE for the next physical timing run. Extract the ZIP to
a writable folder, then open CIRCLE.PRG with the same display setup. It
selects 50 Hz and 16 MHz with cache on. A full opening shows the 320 by
276 test card, including the top and bottom colour strips. The grid,
circle, greyscale and fine bars help reveal clipping, colour errors and
shifts. REFPIC.BMP shows the clean expected card without the live labels.

Tap and release the number keys in the top row. A change takes effect
on the next video frame and continues until you change the setting.

  1 / 2  Move the upper pulse earlier / later
  3 / 4  Move the lower pulse earlier / later
  5 / 6  Shorten / lengthen the lower pulse
  7 / 8  Shorten / lengthen the upper pulse
  9      Cycle BOTH, TOP only, CLOSED, BOTH
  0      Restore the starting settings and select BOTH
  C      Mark the current setting as clean
  X      Mark corruption and return to TOP only
  R, S or Esc  Save the session and return to the desktop

Earlier and later refer to the timing of the opening pulse, which
changes whether the relevant lines are visible and correctly aligned.
U is upper delay, D is lower delay, W is the width of that pulse.
The values are loop counts. 16C ON means 16 MHz, cache on.

Starts in BOTH with upper U078 W08 and lower D101 W17. The lower
timings use the adjustable method from PULSE. These are Hatari
reference settings. Stable full-height output on physical hardware
still needs confirmation.

Look for both colour strips, correct colours across the whole card,
and the same alignment from top to bottom. A strip that loses a colour,
slides sideways by one cell, flickers or disappears is a useful clue.
Try one key at a time, wait a few seconds, and note the displayed counts.
If TOP stays scrambled after X, press R to leave, then relaunch from a
clean desktop before making a new comparison. CLOSED shows fewer rows
and the two extension strips should disappear. The original video and
CPU settings are restored on exit.

Please ZIP and return the CIRCnn.TXT logs. A photo or short video showing
the numbers and both strips helps identify which combination worked.
The log records the settings applied by each key, the video frame
number, C/X marks, and register restoration. File writes happen before
the test and after exiting. The log holds up to 128 events per session.

Native source rebuild from SOURCE.ZIP:

 vasmm68k_mot -m68000 -Fvobj -quiet -nowarn=2047 -I. -o circle.o circle.s
 vlink -b ataritos -s -o CIRCLE.PRG -MCIRCLE.MAP circle.o
