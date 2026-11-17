MEGA STE INTERACTIVE BOTTOM-BORDER PROBE
======================================

1. Extract PULSE.ZIP to a writable folder. Keep your current monitor and
   converter setup for the first run. Double-click PULSE.TOS.
2. The test sets 16 MHz with cache on and displays a fixed alignment
   chart at 50 Hz. TOP mode crops the bottom coloured bar on purpose.
   When the visible chart looks clean, press C to confirm the baseline.
3. The first setting is the P01 pulse from the previous test. Press Space
   to fire it once. Watch whether the picture remains scrambled after it
   returns to TOP. One frame can be too quick to see on a phone.
4. Press C if TOP stays clean, or X if it becomes corrupted. X records
   the result and locks further trials. Press R, S or Esc to save and
   return to the desktop. Relaunch for another clean baseline.
5. If Space stays clean, press T to repeat the same setting for about
   ten seconds. The bottom coloured bar should be visible whenever the
   bottom opens. Press X at once if you see corruption. Otherwise wait
   until TOP returns, then record C or X. Report any partial opening,
   flicker or loss of sync separately with the settings or a phone clip.

KEYS
----
Tap and release each key. The probe does not repeat held keys.

 C           Confirm clean TOP at startup or log a clean trial.
 Left/Right  Start earlier/later by one DBF count (about 5 video cycles).
 Up/Down     Lengthen/shorten the pulse by one DBF count.
 P           Toggle the fixed P01 preset and adjustable reference.
 Space       Fire exactly one bottom pulse, then return to TOP.
 T           Repeat for 500 VBLs, enabled after a clean single-pulse
             result at the current settings. Editing clears eligibility.
 X           Log corruption and lock further tests for this session.
 R, S, Esc   Save the session and return to the desktop.

The adjustable start D runs from 97 to 105 (101 is the reference). Width
W runs from 13 to 21 (17 is the reference). Arrows switch from P01 to
the adjustable method. For P01, D101 is displayed but unused.
If the picture is too hard to read, X followed by R still records it.
If unsure whether it stayed clean, use S to retain an unclassified trial.
At 64 trials the session prompts for exit; the next launch starts a new log.

RETURNING RESULTS
-----------------
Please ZIP all PULSEnn.TXT files you created. Include which trials opened
the full picture, stayed cropped, flickered, or stayed scrambled after the
pulse. If possible, film the first P01 attempt, its aftermath and the desktop
return. Confirm the chart is clean again after relaunch before a new trial.

The program writes each run to the first unused PULSE00.TXT to PULSE99.TXT.
It saves a startup header first, then writes the full report after restoring
the desktop. Use R, S or Esc to finish and save the trials. Logging is
buffered in RAM while the test owns the screen.

Each TRIAL line contains hexadecimal fields documented in the log.
Family 0 is fixed P01, family 1 is adjustable. Outcome 0 is unclassified,
1 is clean and 2 is corruption. Requested and executed pulses are separate.
The program counts frequency writes; visual results come from the operator.
AER records Timer B's falling edge and its restored value. RESTORE rows
include the raw expected/actual values and the defined-bit comparison.
The fixed chart and palette are identical across all trials, with no runtime
Blitter drawing. REFPIC.BMP is the full source chart for viewing on a PC.

To rebuild the exact native binary, extract SOURCE.ZIP and run:

 vasmm68k_mot -m68000 -Fvobj -quiet -nowarn=2047 -I. -o pulse.o pulseprobe.s
 vlink -b ataritos -s -o PULSE.TOS -MPULSE.MAP pulse.o
