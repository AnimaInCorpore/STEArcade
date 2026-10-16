# Double Dragon (Technos, 1987) for Atari STE

MAME set `ddragonj` (Double Dragon, Japan set 1).  Started 2026-10-16: the ROM set and the reference board are done,
the STE port (translation, renderer, sound) is not started.

```sh
python games/ddragon/tools/prepare.py              # verify assets/roms/ddragon.zip, unpack to assets/roms/extracted/ddragon/
python games/ddragon/ref/mame_cmp_ddragon.py [frame ...] [--keep DIR]    # the reference board against MAME 0.289
python games/ddragon/ref/trace_cmp.py main|sub|sound F0 F1    # one CPU against MAME's trace, instruction for instruction
```

Supply `assets/roms/ddragon.zip`: the 23 files of MAME's `ddragonj` under MAME's names (`docs/rom_manifest.json`
has their sizes, CRCs and SHA-1s; they match MAME 0.289's `ddragonj` entry).  MAME runs it as `ddragonj` straight
from `assets/roms` (it looks for a clone's files in the parent's `ddragon.zip`).  Nothing ROM-derived is in git.

## The board

Three CPUs (MAME technos/ddragon.cpp, `ddragon` machine):

* **Main**: HD6309E at 3 MHz.  The program stays in 6809 emulation mode and uses no 6309 instruction (all 140
  mnemonics in a 60-second MAME trace of boot, attract and the demo are 6809 ones), and MAME's `hd6309.lst` gives
  every 6809 instruction the 6809's cycles in emulation mode, so `engine/m6809.py` runs it.  32 KB fixed ROM at
  $8000, a 16 KB bank at $4000 (six pages of 21j-2-3 / 21j-3 / 21j-4-1), 4 KB RAM, palette, two tilemaps, sprite
  RAM, the shared RAM.  NMI at the vertical blank's start (line 240), FIRQ every 16 lines, IRQ from the MCU.
* **Sprite MCU**: HD63701Y0 (6 MHz, 1.5 MHz E clock), 16 KB internal ROM `21jm-0.ic55`:
  `engine/hd63701.py` `HD63701Y0` (the Y0's memory map and port 6 on the shared 6301 core).  It only touches its
  RAM, port 6 and the 512-byte shared RAM: on the main CPU's NMI ($380F) it sorts the object list there and writes
  the sprite entries back, then raises the main CPU's IRQ (port 6 bit 1) and drops its own NMI (bit 0).  The main
  CPU halts it (bank register bit 4) or holds it in reset (bit 3) to reach the shared RAM, which reads $FF while
  the MCU runs; EXTRA bit 4 tells it when the bus is free.  On the first NMI it also sums its ROM into $8000.
* **Sound**: MC6809 at 1.5 MHz with a YM2151 and two MSM5205 (ADPCM samples in 21j-6 / 21j-7, idle bits at
  $1800).  The main CPU only writes the latch ($380E); the sound CPU still runs in the reference because its
  slices, its latch reads and the YM2151's and MSM5205's timers cut the other CPUs' slices in MAME.

`tools/machine.py` runs all three with MAME's scheduler (as `engine/namcos1.py`): 1/60000 s quanta in device order,
a suspended CPU (the MCU in reset or halted) moved to the end and eating its cycles, every timer (the scanline timer
each line, the screen's, the YM2151's, both MSM5205's VCK and capture timers, the 50 Hz stream update) and every
synchronised line change ending a slice.

Video (ddragon_v.cpp): bg 512 x 512 of 16x16 tiles (9-bit scroll x/y), sprites (16x16 to 32x32, pen 0
transparent, drawn first to last), fg 8x8 chars; screen line y shows tilemap line y + 8.  256 x 240 visible, 384 x
272 total at 6 MHz (57.44 Hz).

## State

* **All three CPUs exact**: `ref/trace_cmp.py` against MAME's debugger trace, every instruction's address,
  registers and cycle count equal: the main CPU frames 0-300 and 8000-8011 (4.6 million instructions), the MCU frames 0-1200
  (560,715, through its resets and halts), the sound CPU frames 0-3 and 600-1800 (6.9 million).
* **Memory**: `ref/mame_cmp_ddragon.py` from power-on: main CPU RAM, palette, tilemaps, sprite RAM, shared RAM, MCU
  RAM, sound RAM, scroll and every sound command equal at all checked frames through 9000 (boot, attract, the demo
  through its stages).  A dead stack byte can differ where MAME stops inside an instruction at a frame's end (frame
  8010: $0FEC-$0FED below S, the trace identical).
* **Picture**: the reference renderer draws MAME's memory with 0 differing pixels and all 384 layer pens equal; the
  board's own picture (each line with the video state at its scanline, as MAME's partial updates) is exact too,
  but for 26 pixels of frame 8000: while the program clears the background during the frame, MAME shows 16 old
  pixels at x 48 in line 0, x 144 in line 1, x 240 in line 2 (96 pixels further each line, a sub-line effect of its
  drawing that a line model does not give).
* Not checked yet: play (coins, start, the stages played) against MAME.  Not modelled: the flip screen
  (cocktail), the sound output itself (the YM2151 register writes and ADPCM starts are logged).

MAME's slices split instructions, the board's 6809 core runs whole ones.  Where that shows (a read on an
instruction's last bus cycle past a slice's end) the board reads by MAME's time: the vertical blank bit by the time
alone, the YM2151 status and the ADPCM idle bits after firing the YM2151 / MSM5205 timers that expire before the
read cycle (`DDragon.fire_early`); the YM2151's busy flag by the read cycle's time.

Next: coverage seeds and the 6809 translation of the main program (`engine/m6809x.py`), the MCU as a native
routine, the renderer, YM sound.
