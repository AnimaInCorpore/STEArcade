# STEArcade 0.6

This release adds bootable floppy disk images, so the ports run on an STE with
only a floppy drive or a floppy emulator (Gotek, GoEX, HxC). It also brings
Gauntlet to the arcade's 60 frames a second and speeds up Double Dragon's logic.
No port is certified Complete; the status of each port is in the README's table
and the [status policy](docs/port-status.md).

- **Floppy disks (new):** `DISKS/` holds a bootable .ST image for 12 of the 15
  games: 720 KB (80 tracks, 9 sectors) or 800 KB (80 tracks, 10 sectors). Each game
  is packed with LZ4 into a self-unpacking program in the disk's AUTO folder. Boot
  the STE from the disk with no hard disk. The game unpacks itself in 4-13 seconds
  behind a progress bar and then starts. Black Tiger, 1943 and Double Dragon are
  too large for one disk (0.99-1.26 MB packed); use their .PRG from a hard disk.
- **How the disks work:** the stub unpacks in place and needs about 920 bytes more
  memory than the game. It is checked for every port on a 68000 emulator against
  a normal TOS load, at two memory alignments and in all three resolutions. All 12
  disks boot to the game's attract mode in Hatari (STE, 4 MB, TOS 2.06). R-Type
  needs 3.85 MB and starts from the disk: TOS leaves 4.1 MB to a floppy's AUTO
  folder.
- **Gauntlet:** the game runs at the arcade's 60 frames a second, six game frames
  for every five VBLs (83% before). The renderer compares only the areas the
  game's own writers marked, and 88 more jump-table targets are relocated (level 12
  reached an unrelocated address before). Hatari: 32.6 pictures a second in light
  play (23.4 before), 16.0 in the attract mode.
- **Double Dragon:** the 6809 translation's faster forms are used on the 68000 too:
  the logic needs 180.9k cycles a frame instead of 191.3k (Musashi). Lock-step
  logic tests over 6,000 frames are identical on five seeds.

The performance figures are per-port measurements in Hatari or Musashi on an
8 MHz STE with 4 MB of RAM and no accelerator. They are not measurements of this
package on real hardware. The floppy images have not yet been tried on a real STE
or a GoEX.

The release archive contains default, self-contained TOS programs for a hard
disk, the floppy images in `DISKS/` and a README.TXT with controls and SHA-256
sums, built from the release commit. ROM sets are not included.
