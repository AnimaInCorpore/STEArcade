# 1943: The Battle of Midway

![1943 on the STE (Hatari)](docs/screenshot.png)

Atari STE port (4 MB) of the `1943` set (Euro), registered as `1943`: the main Z80 translated to 68000 code, the
i8751 protection MCU's dumped firmware interpreted, a hardware scrolled Blitter renderer.  Sound is not implemented.

```sh
python port.py prepare 1943                 # auto: US archive if present, otherwise Euro
python port.py prepare 1943 --set 1943       # explicitly choose the available Euro set
python port.py prepare 1943 --set 1943u      # requires the US Rev C program ROMs
python port.py cover 1943                   # 20 coverage runs (seeds 6-20: MAME's cheats, one stage each)
python port.py build 1943                   # assets + translation -> run/1943/1943.PRG (--sim: the Musashi build)
python port.py test 1943                    # ROMs, graphics, reference, lock-step logic and pictures
python port.py run 1943                     # Hatari (tools/hatari.sh)
python port.py mame 1943                    # pixel checks at frames 100, 700 and 1500
```

Controls: **5/6** coins, **1/2** start, **arrows** move, **Space/Ctrl** fire, **Alt** the loop (button 2),
**Escape** quits.  Joystick port 1 plays player 1, port 0 player 2.
Jaguar pad / PowerPad (STE enhanced ports, `docs/architecture.md` "Input"): pad A player 1, pad B player 2, the D-pad moves, **A** fire, **B** button 2, **Option** coin, **Pause** start, keypad **1/2** start, **5/6** coin, **\*** + **#** quit.

Both sets have 38 ROMs. Manifests come from the local MAME driver. The supplied
`1943.zip` plus `assets/roms/bm.7k` verifies completely as the Euro set.
MAME marks Euro's `bme01.12d` as `BAD_DUMP`: it is a historically modified dump,
used here unchanged. The US Rev C manifest remains available, but its three
program ROMs are not currently supplied. Set identity is recorded in
`build/1943/set.txt`; coverage from another set is rejected by the generator.

The archive swaps `bm05.4k` and `bm04.5h`. Preparation resolves files by size,
CRC32 and SHA1, then writes canonical filenames without changing the archives.
It verifies the complete set before writing extracted files or regions.
Extracted files go to `assets/roms/extracted/1943`; nine MAME-layout regions go
to `build/1943`. Loose ROMs and the parent archive can supply shared contents.

## Reference machine

`tools/machine.py` emulates the main Z80, eight ROM banks, mapped inputs and
latches, sprite buffering on c806, and IRQs at scanlines 144 and 240. The SYSTEM
VBL input follows the scanline. `tools/mcu.py` executes the actual i8751 firmware
at reset and each VBL INT1, including its table search and P3 falling-edge reply
strobe. Unknown MCU instructions fail explicitly. MCU execution is synchronous,
not cycle accurate; sound CPU and YM2203s are not implemented.

`tools/reference_test.py` checks all 256 MCU command values against the dumped
firmware tables (including retained replies for unknown commands), then runs
unpatched frames and saves `build/1943/reference.png`. Graphics tests check
4,000 decoded pixels against independent scalar ROM bit reads and exercise
layer enables, flips, maximum scroll, sprite ownership, priority and clipping.

## MAME validation

`ref/mame_cmp_1943.py` constructs a temporary canonical ROM directory so MAME
sees correct audio/character names and the loose MCU firmware. It reads MAME's
RAM, video latches and actual buffered sprite RAM, renders the same state with
the reference, and compares the portrait screenshot pixel by pixel. The Euro
set matches at frames 100, 700 and 1500 with **zero differing pixels**.
This establishes video equivalence at those states; it does not establish
cycle-by-cycle CPU/MCU equivalence or STE performance.

See [hardware notes](docs/hardware-notes.md).

## Translation and schedule

`tools/gen.py` (`translate.compile_code`, `z80x.FAST`, the banked window rules of Black Tiger): 14,103 instructions
from the fixed ROM and banks 0, 1, 4, 6, none unsupported.  Besides the coverage roots, discovery adds the
continuations of the object allocators (`06EC` and relatives: `pop hl; inc hl` x3; `jp (hl)` returns to the call + 6
on success, `skips()`); random play reached one (bank 0 `A000`) that no coverage run had seen.

The program is Capcom's task kernel (as Black Tiger): the scheduler at `00B6` runs the ready tasks of the table at
`EF80` and loops at `00D4` when none is ready.  `src/1943.s` hooks `00D4`: it draws the frame, then delivers a tick:
the line 144 IRQ (SYSTEM bit 3, the VBL, clear), the MCU's INT1, the line 240 IRQ (bit 3 set), each run to its
return to `00D4` with a token on the Z80 stack, then the tasks they woke.  `tools/machine.py run_frame_port` is the
same schedule.  Six ticks per five VBLs (59.6 Hz arcade), at most `MAX_SKIPS` frames skipped in a row.  The latches
`C804` (bank, flip, characters on), `C806` (the sprite list buffered: 128 entries of 4 bytes), `C807` (MCU command)
and `D806` (layer enables) are write hooks that keep every register and the CCR.

`src/mcu.s` interprets the i8751 firmware with exactly the instructions of `tools/mcu.py` (a jump table per opcode,
anything else stops at `z80_unsupported`); the P3 bit 6 falling edge latches the reply, PSW's parity is made exact
where PSW is read.

## Renderer (`src/render.s`)

The screen is the raw 256 x 224 picture rotated: 224 x 256, screen x = raw y - 16, y = 255 - raw x.  The back layer
(the sea, 32 x 32 tiles from the ROM map) scrolls vertically at half the speed of the front layer (clouds, islands,
ships), which also scrolls sideways (`D802`) in stages 3, 9 and 14.

* **Three display rings, virtual screens with twin lines** (the Commando port's scheme): ring line l and l + 320 hold
  the same picture of the back layer, so the 256 window lines and 32 guard lines above and below are contiguous
  wherever the window is.  Back layer lines are drawn once, as they scroll into the band (each a line of 8 baked
  tiles into all its copies; `back_line`); a change of the layer's enable or a jump draws the band whole.
* **Everything else is drawn every frame and listed as damage**, copied back from the twin lines at the ring's next
  visit: the sprites of colours 10 and 11 (behind the front layer), the front layer (whole 32 x 32 baked tiles, blank
  ones skipped; runs of lines with equal opaque masks: 4 lines and more one Blitter call per plane, shorter ones one
  call per line with the 4 planes as Y count, masks shifted to the horizontal scroll; an unshifted tile at the window's
  edge draws only its inner chunk), the other sprites (two lists sorted once a frame; the generated routines and
  endmask streams of `games/1942/tools/spritegen.py`, 3000 routines, a packed table), the characters (each baked as a
  small `movep.l` routine; the list is rebuilt when the character RAM changes, compared only in the 32-cell blocks
  its 55 translated writers mark).  A fully opaque front tile's damage is left where the next frame's opaque tiles
  cover it.  What an object draws into the 48 pixel margins beside the window is cleared.
* **Front-follow rings through cloud banks**: when the window's fully opaque front cells outnumber the blank ones (by
  16 of the 72, back again the other way; both layers on, no horizontal front scroll), a ring follows the front layer
  instead: its twin lines hold the front layer, drawn as its lines scroll in, and a sea pass draws the back layer where
  the front is transparent (blank cells two plain copies, the back tiles being in the same columns; mixed cells the
  tile's sea runs, inverted masks, one call per chunk and run).  Sprites of colours 10/11 get the front cells they
  overlap drawn over them again.  When such a ring's window wraps at the ring's end, the old band's lines are copied
  back from their twins (the sea is not damage).  A cloud bank frame went from 506k to 246k Musashi cycles.
* **Colours**: one 16 colour palette, Oklab k-means over the colours of every stage weighted by how often they show
  (`ref/palette_stats.py` -> `docs/palette_stats.json`, `docs/palette.json`).  Tiles of both layers are baked at
  build time (`tools/assets.py`: 396 back, 583 front tiles); sprites and characters are baked on first use into a
  pool with hashed caches.
* **Borders**: `engine/rt/borders.s` (shared with Commando and Gun.Smoke): Timer B fires 2 lines before the palette
  on, the bottom border and the palette off and polls to the line end, the bottom border starts Timer A for the next
  top border, which syncs to its HBL; nothing waits, HOG passes over 32 words run in pieces (`blit_go`).  Hatari, 4000
  VBLs: 0 late events.
* **Not exact**: where a sprite of colour 10/11 comes earlier in the list than an overlapping sprite of another
  colour, the arcade shows the first (or the front layer over it), the port the second.  The test recognises such
  pictures by rendering the reference in the port's order.

## Tests

`port.py test 1943` builds the simulator version and runs `tools/logic_test.py`: the translated program on Musashi
against the reference's port schedule, RAM, video latches, sprite buffer, latches, MCU reply and MCU RAM compared at
every tick, and that every change of the character RAM came with its block's mark; with `--render` each picture the
renderer finished is compared with the reference renderer through the palette map (the margins must be black),
`--twins` also checks the ring's twin lines (the back layer, or the front layer in front-follow).  `--cheat n` plays
stage n with MAME's cheats, `--seed n` random inputs.  Results (2026-10-09): every stage 0-14 with cheats (4000 ticks),
the default schedule, random seeds 1-3: logic exact, pictures exact but for the sprite order case above (stage 3: 127
of 2000 pictures, a few pixels each).

## Speed (2026-10-09)

| | first runtime | now |
|---|---|---|
| a tick's logic, Musashi (`tools/perf_test.py 1400 1300`, play) | 110k (MCU interpreter 62k) | 46k (translated MCU 8k) |
| a frame, open sea and a carrier | 340k | 222k |
| a frame, a cloud bank (`--cheat 9`, ticks 2600-2650) | 562k | 246k |
| Hatari, DEBUG + AUTOPLAY, 4000 VBLs | 31.9 ticks/s (53%), 6.4 frames/s | 55.7 ticks/s (93%), 11.2 frames/s |

The logic gains: the i8751 firmware translated (`tools/mcux.py`), the window guard only at the 291 sites the
coverage saw reading the banked window (and sites it never ran; block instructions always), a signed one-compare
guard, a table bank switch.  `MAX_SKIPS` 8 (4 gave 87% speed and 15.5 frames/s).  `-D STAGE=n` makes the AUTOPLAY
build play stage n with the cheats; `engine/xprof.py 1943` profiles the translated code (`X1943_STAGE=n`).

## Not done

Sound; the flip screen (cocktail); the arcade's clipping of sprites at the raw 256 pixel edges; full speed in the
busiest scenes (the game's own logic is 86k cycles a tick there).
