# STEArcade 0.7

This release adds seven games: Donkey Kong Junior, Pac-Man, Pooyan, Mr. Do!, Moon
Patrol, Track & Field and Hyper Sports. In each, the arcade program is translated
and checked frame by frame against its reference machine, and the pictures are
exact against the reference renderer. R-Type is not part of this
release: while it is developed it needs more than 4 MB of RAM. No port is certified
Complete; the status of each port is in the README's table and the
[status policy](docs/port-status.md).

- **Donkey Kong Junior (new):** full speed, the picture equal to MAME's. Sound: the
  8035 board's music recorded in MAME and played on the DMA sound, the walk, jump,
  climb and fall effects on the YM. 22 arcade colours fitted into 16. Too large for
  a floppy disk (848 KB packed): start it from a hard disk.
- **Pac-Man (new):** the arcade's 60 frames and 50 pictures a second in play, logic
  and picture exact; the WSG's three voices on the YM.
- **Pooyan (new):** full speed, 40-50 pictures a second in play; the picture, the
  palette and the RAM equal to MAME 0.289's. Sound: the Z80 sound driver translated,
  its two AY chips mixed onto the YM.
- **Mr. Do! (new):** full speed in most of play, 44-50 pictures a second; one fitted
  palette of 15 colours. Sound: the two SN76489s' tones on the YM.
- **Moon Patrol (new):** about 95% of the arcade's speed, 14-30 pictures a second in
  Hatari; the renderer redraws only the changed parts of the parallax layers. Frames
  with more than 16 colours on the playfield (a few, in busy scenes) show the
  nearest colour for one of them. Sound: the M6803 driver translated, its two AY
  chips on the YM, the sampled sounds on the DMA sound.
- **Track & Field (new):** the encrypted KONAMI-1 6809 program translated; full
  speed, 20-50 pictures a second. Sound: the Z80 driver translated, the SN76489A on
  the YM, the speech and tunes on the DMA sound.
- **Hyper Sports (new):** the same board and sound as Track & Field; 83% of the
  arcade's speed with sound, 5-50 pictures a second.
- **Floppy disks:** 17 of the 21 games have a bootable .ST image in `DISKS/`. Black
  Tiger, 1943, Double Dragon and Donkey Kong Junior are too large for one disk.
- **Commando:** faster character rows and sprite slots.

In Hatari (STE, 4 MB, TOS 2.06), every new game's program started a game from the
keyboard (coin, start, a move), and every new floppy image booted to its game's
attract mode. No new game has been played through to its end, and the controls
and the sound of the new games have not yet been checked by hand. The performance
figures are per-port measurements in Hatari or Musashi on an 8 MHz STE with 4 MB of
RAM and no accelerator, not measurements of this package on real hardware.

The release archive contains default, self-contained TOS programs for a hard
disk, the floppy images in `DISKS/` and a README.TXT with controls and SHA-256
sums, built from the release commit. ROM sets are not included.
