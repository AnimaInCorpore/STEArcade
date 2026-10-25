# STEArcade 0.5

This release adds Time Pilot as the fifteenth program, runs Galaga's real 51XX
MCU program, brings Commando to the arcade's full speed in play, and draws
sprites and text with prepared Blitter passes in several ports. No port is
certified Complete; the status of each port is in the README's table and the
[status policy](docs/port-status.md).

- **Time Pilot (new, Incomplete):** the main Z80 is translated with exact logic and
  picture (the reference board matches MAME 0.289: 0 pens, 0 pixels differ). It runs
  at the arcade's full speed, a median of 32.5 pictures a second on the recorded play
  (10th percentile 26.5, Hatari). There is no sound yet.
- **Galaga (Verification pending):** the real 51XX program is translated from the
  MB88 to 68000 code and runs instead of the old simulation; its traffic matches
  the reference tick by tick, and the reference's 51XX matches MAME 0.289. The 54XX's
  explosions are still simulated. Hatari attract mode: 31.1 pictures a second
  (33.2 with the simulation). Full-game checks are pending.
- **Commando:** full game speed in play (about 95% before), 26.5 pictures a second
  on the recorded play (Hatari). The changes are inlined leaf functions, table-driven
  sound effects, faster sprite and tile drawing, and up to 3 skipped pictures.
- **Gun.Smoke:** faster sprite scanning, edge tiles drawn as inner chunks, and text
  rows drawn as prepared passes. On the recorded play: 92% of the arcade's speed (84%
  before), 25.8 pictures a second (22.9 before).
- **Black Tiger:** 87 more translated entry points and every block copy guarded,
  found by replaying a recorded MARP game in F030Arcade's port of this translation.
  Text is drawn as prepared passes: 24.6 -> 25.5 pictures a second on that recording.
- **Gyruss and Kung-Fu Master:** both use the shared generated sprite code
  (`engine/sprite_programs.py`, from Time Pilot). Gyruss: 11.6 -> 12.1 pictures a second.
  Kung-Fu Master: 27.4 -> 33.2 on the recorded play. The game logic is unchanged.
- **Renderer:** masked sprites and text are drawn as single copy passes with the
  opaque pixels as end masks, all four planes in a pass, in the stefastbobs2 style.
  The AND + OR pass pairs are gone from Black Tiger and Gun.Smoke. The M72 front
  layer still uses them. Method and measurements:
  [sprite preparation](docs/sprite-preparation.md).
- **Tools:** an Intel 8080 reference interpreter, MAME's MB88 core, MARP recordings as
  recorded play and a cycle-budgeted replay build (Black Tiger), and new perf_test
  options.

The performance figures are per-port measurements in Hatari on an 8 MHz STE with
4 MB of RAM and no accelerator. They are not measurements of this package on real
hardware.

The release archive contains default, self-contained TOS programs and a README.TXT
with controls and SHA-256 sums, built from the release commit. ROM sets are not
included.
