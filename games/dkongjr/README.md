# Donkey Kong Junior, Atari STE (work in progress)

MAME set `dkongjr` (US set F-2, `assets/roms/dkongjr.zip`, the 13 files of `docs/rom_manifest.json`).  Not registered in
`port.py`'s `GAMES` yet.  Paths relative to `games/dkongjr/`.

## The board against Donkey Kong's

Junior runs on Donkey Kong's board (MAME `nintendo/dkong.cpp` in the authoritative 0.286 tree, `AGENTS.md`: `dkongjr_map`,
`ROM_START( dkongjr )`; `dkong_v.cpp`, `resnet.cpp`, `palette.cpp` and `i8257.cpp` checked identical there), so the port starts
from the Donkey Kong port (`games/dkong`):

- **CPU ROMs**: 24 KB ($0000-$5FFF) in three 8 KB chips whose 2 KB / 4 KB pieces are not in address order
  (`tools/prepare.py` puts them back: `assets/roms/extracted/dkongjr/cpu.rom`).
- **Tiles**: 512; bit 0 of a write to `$7C80` adds 256 to every tile code (`dkongjr_gfxbank_w`).  Sprites, the 8257
  DMA ($6900 -> $7000, $180 bytes), the column colour PROM, the palette banks `$7D86/7`, the flip and sprite bank
  latches and the NMI mask `$7D84` are Donkey Kong's.
- **Palette**: Donkey Kong's circuit with Junior's PROMs (2e, 2f).  No current MAME build is installed to dump the
  pens, so `tools/dkongjr_pens.py` is MAME's code in Python (`compute_res_net`, the tri-state black,
  `normalize_range`); run on Donkey Kong's PROMs it gives all 256 pens of `games/dkong/tools/dkong_pens.py` (MAME 0.289's
  dump) exactly.
- **Inputs**: Donkey Kong's bits.  DSW0 bits 2-3 are the bonus life (10000-25000); IN2 bit 6 reads low (no MCU line).
- **Sound**: the 8035 board with Junior's program (`djr1-c_3h.3h`), `$7C00` tune, `$7C81-$7C87` and `$7D00-$7D07`
  effect bits, `$7D80` the 8035 IRQ.  Not ported yet (`src/sound.s` is silent).
- **RAM layout**: the game keeps Donkey Kong's: `$6227` stage (1 springboard, 2 vines = the first, 3 chains,
  4 hideout; setting it during the intro starts that stage), `$6228` lives, `$6229` level, `$60B2` P1 score (BCD),
  `$60B8` high score, `$6100` the table.  The idle-loop head is `$02BD` as in Donkey Kong.

## Files

`tools/`: `prepare.py` (ROMs), `machine.py` (reference machine: Donkey Kong's with the tile bank, a register model of
the 8257, Junior's PROMs), `dkongjr_pens.py`, `gen.py` (translation; the dispatch table covers $0000-$6001, the NMI
return token is $6001), `assets.py`, `build.py`, `logic_test.py` (lock-step against the reference, from Donkey Kong's), `render_test.py`,
`frametimes.py` (Donkey Kong's).
`src/`: `dkongjr.s` (Donkey Kong's runtime: the ROM size, the token, the DIP switches), `render.s` (Donkey Kong's with
the tile bank: a bank switch redraws every tile), `sprites.s` (Donkey Kong's), `sound.s` (silent).
`ref/`: `cover.py` (coverage and pens: random play, every stage by `$6227`, lives, a high score for the name entry),
`probes/` (bring-up).

## State (2026-10-29)

- The reference machine boots and plays: attract mode, high-score table, coin, the intro, all four stages by `$6227`.
  Not compared with MAME's picture yet (no MAME with a Lua API installed here; the wolfmame 0.162 in F030Arcade
  has an older one).
- Coverage: `ref/cover.py` seeds 1-3 (random play), 4-5 (no coin: the whole attract sequence), 11-16 (stages, lives),
  21-23 (also the name entry), 20000-40000 frames each (~8 min in parallel): 7.3k PCs.  A coin cuts the attract
  sequence short: before seeds 4-5 no run reached its steps 3, 5-7 ($600A, the table at $0747), among them the title logo
  ($07CB: palette cycling, tile bank 1, the only write of bank 1 at $07F9).
- Unmapped memory: the game reads `$85A0-$B5F8` at `$24FC` (its loop at `$24F3` steps IX by `$1010` instead of `$10`) and
  writes `$8B21-$C960` at `$0F34` (odd entries of a table).  MAME reads 0 there and ignores the writes; the reference
  does the same, and the runtime has a 32 KB zero guard below `z80_block` (the signed index puts `$8000-$FFFF` there).
- Translation: 9461 instructions, nothing unsupported.  The `rst $28` table at `$1648` has 6 entries
  (`Config.rst28_counts`, a new engine option): the scan read the code after it as two more and followed them into data.
  `$8000`/`$8003` (jumps taken when IN2 bit 0, a service input, is set) stay `z80_badpc` stubs.
- `tools/logic_test.py 3000`: lock-step OK (attract, coin, the first stage); `--nocoin`: OK through the title.
- `tools/build.py`: `run/dkongjr/DKONGJR.PRG` (2.94 MB loaded, below MAX_LOAD).  In Hatari (`-D AUTOSTART=150`) it shows
  the boot self-test, the attract demo, the intro and play on the vines stage.
- `tools/render_test.py` (Galaga's method on Donkey Kong's `DUMPAT` freeze; `-D STAGE=n` starts stage n during the
  intro, a test define in `src/dkongjr.s`): the STE's screen against `render_raw()` of the frozen RAM, 0 pixels differ
  in all 14 frames: attract, intro and play on all four stages, palette banks 1-3, the title in tile bank 1.  The
  freeze counts the frames the program drew, the simulator its VBLs, and a slow frame skips VBLs: the test waits for the
  freeze (without that, a moving sprite was one frame behind the frozen RAM).
- `games/dkong/tools/sprite_test.py --prg run/dkongjr/DKONGJR.PRG --map build/dkongjr/dkongjr.map` (`sprites.s` is Donkey
  Kong's): 2048 edge cases exact (both edges, 16 shifts, flips, holes, 64 KB, the restore).  A map from another build
  (an `--out` build writes `dkongjr.map` too) makes it fail: rebuild the plain program first.
- Speed (Hatari, `-D AUTOSTART=150 -D TIMES=1 --debug --frames 3000`, `tools/frametimes.py`): a frame takes 34% of the
  50 Hz frame on average (Z80 NMI 8%, drawing 27%); 0.9% of the frames run into the next VBL (the full redraws: the
  boot's video RAM test, the tile bank switches, the palette bank changes), as Donkey Kong's 0.8%.
- Palette: 22 colours besides black are shown; the 7 rarest (each < 2% of the pixels) are merged into neighbours by
  Donkey Kong's fit.  Fit per stage (see the porting guide) if they look wrong.

## Next

1. MAME check of the reference picture (`ref/mame_cmp_dkongjr.py`).  The authoritative MAME is the 0.286 source
   (`AGENTS.md`); its `m68k.exe` has no Donkey Kong driver, so the picture needs another MAME build.
2. Sound as in Donkey Kong (MAME recordings of the 8035, the discrete effects on the YM).
3. Register in `port.py` (GAMES, COVER, TESTS), `tools/release.py`, the README tables; play through in Hatari.
4. The boot's video RAM test (the first frames, a full redraw each): skip it if it matters.
