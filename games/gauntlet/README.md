# Gauntlet (Atari Games, 1985)

MAME set `gauntlet` (rev 14; driver `atari/gauntlet.cpp`).  So far the reference board: both CPUs, the sound
chips' observable timing and the picture equal MAME 0.289 from power-on through two loops of the attract mode.  The
STE port has not started; the game is not in `port.py` yet.

```sh
python games/gauntlet/tools/prepare.py      # verify assets/roms/gauntlet.zip, unpack to assets/roms/extracted/gauntlet/
python games/gauntlet/tools/mame_roms.py    # build/gauntlet/mame_roms/: the set as MAME 0.289 wants it (-rompath)
python games/gauntlet/ref/mame_cmp_gauntlet.py [frame ...] [--keep DIR] [--reuse DIR] [--render-only]
python games/gauntlet/ref/trace_cmp.py main|sound F0 F1 [--keep DIR]   # one CPU against MAME's trace
```

Supply `assets/roms/gauntlet.zip`: the 20 files of MAME's `gauntlet` under MAME's names (`docs/rom_manifest.json`
has their sizes, CRCs and SHA-1s).  All match MAME 0.289 but `136037-104.6p`, the alphanumerics: the archive has the
8 KB dump of the 27128, MAME lists the whole chip (16 KB, the second half $00, crc32 6c276a1d), so
`tools/mame_roms.py` writes MAME a copy padded with zeros.  Nothing ROM-derived is in git.

## The board

* **Main**: MC68010 at 14.318181 MHz / 2.  `engine/m68kmame.py` is MAME's own Musashi: the build takes MAME 0.289's
  core sources (`m68k_in.lst` through MAME's `m68kmake.py`, the functions of `m68kcpu.cpp` a 68010 needs, unchanged;
  downloaded from github.com/mamedev/mame, tag mame0289, into `build/mame0289/`) and compiles them outside MAME with
  a stand-in for MAME's framework (`engine/m68kmame/emu.h`) and a C interface (`glue.cpp`: 4 KB pages of RAM / ROM /
  unmapped / callback with mirrors, the board's callbacks through ctypes, an instruction hook, a trace buffer,
  coverage per instruction).  The copy of MAME in F030Arcade is 0.286 with local changes and its 68010 differs (0.289
  counts no per-bit shift cycles below the 68030).
* **Slapstic** 137412-104 (`mame/atari/slapstic.cpp`): MAME taps the whole program space, so every bus access of
  the 68010, opcode and immediate fetches included, is tested (a read after the access, a write before).  The state
  machine runs in `glue.cpp` on the tests `tools/machine.py` builds (MAME's checker); a bank change points the
  window's pages ($38000-$3FFFF, the 8 KB bank four times, and its mirrors) at that bank's copy.
* **Sound**: MOS 6502 at 14.318181 MHz / 8, `engine/m6502mame.py` (generated from MAME's `om6502.lst` by
  `engine/m6502mame_gen.py`: every bus access on MAME's cycle, dummy reads and writes too, resumable inside an
  instruction at a slice's end).  YM2151 (timers and status: `engine/m72board.py`'s model; its IRQ is not
  connected), POKEY (`engine/pokey.py`: an execute device of its own in MAME, run after the 6502; a read or write
  is a synchronize()), TMS5220C (`engine/tms5220.py`: the FIFO, the frame parsing, the ready line; its stream is
  rendered at the CPU's reads and writes, its io_ready timer and the 50 Hz sound update).  The audio itself is not
  made.  Both latches are MAME's generic_latch_8 (a write lands through a synchronize() timer); a sound command
  raises the 6502's NMI and a perfect quantum (the second smallest CPU minimum, 0.56 us) for 100 us.
* **Interrupts**: IRQ 4 at the vertical blank's start (acknowledged by a write to $803140), IRQ 6 while a sound
  response is pending; the 6502's IRQ from the scanline timer on lines 32, 96, 160 and 224.
* **Scheduler** (`tools/machine.py`): MAME's timeslice() in integer attoseconds, the default quantum (1/60 s), the
  three executing devices in device order (maincpu, audiocpu, pokey), the screen's timers (vertical blank begin and
  end, line 0), the scanline timer, the sound manager's 50 Hz update.

Memory (main CPU): ROM $000000-$00FFFF and $040000-$04FFFF (the "BIOS" and the game; the interrupt vectors jump
through $40000), the slapstic window $38000-$3FFFF, work RAM $800000 (unused in the attract mode: the program's
variables and stack are in the spare video RAM at $904000), the EEPROM $802000, I/O $803000, video RAM $900000
(playfield, motion objects, spare, alphanumerics, y scroll at $905F6E, SLIPs), palette $910000, x scroll $930000.

Video (`tools/video.py`, gauntlet.cpp + atarimo.cpp): the playfield 64 x 64 tiles of 8x8 (512 x 512, scrolled), the
motion objects (linked lists through the SLIP table, 8-line bands; pen 1 is a shadow: it flips the playfield
colour's bit $80), the alphanumerics 64 x 31 on top; 1024 pens IRGB_4444; 336 x 240 visible at 59.92 Hz.

## Reference (`tools/machine.py`, `ref/mame_cmp_gauntlet.py`, `ref/trace_cmp.py`)

* **Both CPUs exact** against MAME's debugger trace (address, cycle count; the 6502 also its registers): the main
  CPU frames 0-3, 380-420 and 9000-9010 (about 660,000 instructions), the sound CPU frames 370-400, 600-800 and
  9000-9100 (2.9 million, from its release from reset).
* **Memory and pictures**: `ref/mame_cmp_gauntlet.py` from power-on at 43 frames through 19801 (two loops of the
  attract mode: the demo play in the mazes, the monster pages, the high scores, the title): work RAM, video RAM,
  palette, the sound CPU's RAM, the x scroll and every sound command equal; the reference renderer on MAME's memory
  and the board's own picture both 0 differing pixels and 0 differing pens.
* `engine/m6502mame_test.py`, `engine/pokey_test.py`, `engine/tms5220_test.py`: the cores and chips against logs
  of MAME's gauntlet (every bus access of 613,395 sound CPU instructions, every opcode, all decimal ADC / SBC; 2.3
  million TMS5220 accesses with 15 internal fields; 116,000 POKEY accesses with its counters and polynomials).
* Speed: about 6 ms an arcade frame without the sound CPU's devices, 13 ms with them (the 68010 runs native).
* Not checked yet: play (coins, start, the levels) against MAME; the EEPROM's writes (the high-score table) beyond
  the attract mode.
