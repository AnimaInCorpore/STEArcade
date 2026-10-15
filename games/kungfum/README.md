# Kung-Fu Master (Irem, 1984) for Atari STE

![Kung-Fu Master on the STE (Hatari)](docs/screenshot.png)

MAME set `kungfum` (Irem M62).  The main Z80 program (32 KB, flat) is statically translated to 68000 code; the
picture (all 256 x 256 arcade pixels, centred in the 320-pixel screen, top and bottom borders open) is drawn by
`src/render.s` with a hardware-scrolled playfield and Blitter sprites.  For a 4 MB STE (it asks TOS for 1.5 MB).  No sound
yet: the sound commands are kept in a ring.

```sh
python games/kungfum/tools/prepare.py      # verify assets/roms/kungfum.zip, unpack to assets/roms/extracted/kungfum/
for s in $(seq 1 13); do python games/kungfum/ref/cover.py $s 20000; done   # coverage (~3 min in parallel)
python games/kungfum/tools/build.py        # -> run/kungfum/KUNGFUM.PRG (--sim: run/kungfum_sim for the tests)
python games/kungfum/tools/logic_test.py 20000 --seed 4     # the translation in lock-step with the reference
python games/kungfum/tools/render_test.py 20000 --seed 4    # the STE picture against the reference, every frame
python games/kungfum/tools/sprite_test.py                   # sprites at the edges, all shifts, holes, 64 KB crossings
python games/kungfum/tools/play_search.py 9000              # the recorded play (build/kungfum/play_inputs.bin)
games/kungfum/tools/bench.sh 6000          # Hatari speed (PLAY=1: the recorded play): logic and pictures a second
games/kungfum/tools/shots.sh tap:5@26 tap:1@29 shot@40      # its own Hatari: keys, screenshots
python games/kungfum/ref/mame_cmp_kungfum.py [frame ...]    # the reference against MAME 0.289
```

Supply `assets/roms/kungfum.zip` (MAME's 28 files under MAME's names; `docs/rom_manifest.json` has their sizes, CRCs
and SHA-1s).  Nothing ROM-derived is in git: the graphics, palettes and the ROM image are made into `build/kungfum/`
(`tools/assets.py`) and assembled into the program.

Controls: **5/6** coin 1 / 2, **1/2** start, **arrow keys** move (up jumps, down crouches), **Space / Ctrl / Z**
punch, **Alt / X** kick, **Esc** quits.  Joystick port 1 player 1, port 0 player 2 (fire punches).  Jaguar pad /
PowerPad: pad A player 1, pad B player 2, the D-pad moves, **A** punch, **B** kick, **Option** coin, **Pause**
start, keypad **1/2** start, **5/6** coin, **\*** + **#** quit.  For scripted Hatari events: coin `5`, start `1`,
`Left` / `Right`, `z` punch, `x` kick.  DIP switches: MAME's defaults.

## State

* **Logic**: exact.  `tools/logic_test.py` runs the translation (Musashi) in lock-step with the reference's port
  schedule (`machine.KungFuPort`): RAM, tile RAM, sprite RAM, scroll and the sound commands equal every frame, every
  changed tile RAM row marked: 20,000 frames each of the 13 coverage seeds (attract, coin, start, play, deaths,
  game over and the high-score entry, all five floors and their bosses, floor 2's pots, the ending, the
  invulnerability and level selection DIP switches) and the 9,000 frames of the recorded play.
* **Picture**: exact in the shown colours.  `tools/render_test.py` runs the program with its renderer and compares
  every frame's STE picture (panel image + the published ring at its window) with the reference renderer through the
  scene's pen map: 0 differences in 20,000 frames of each of the 13 seeds and in the 9,000 of the recorded play; the
  bands black but where a sprite overhangs an edge inside a word (below).  No HOG pass longer than 256 bus cycles,
  none without HOG (`BLIT_STATS=256`).  `tools/sprite_test.py`: 1,122 made-up pictures, cells across both edges at every pixel offset for
  24 window offsets, 1-, 2- and 4-cell sprites with transparent rows and holes, flips, overlaps, the three rings'
  64 KB crossings, moving sprites and window (damage restores, strips): exact; the band check fails 737 of them if no
  overhang is allowed (all at windows inside a word: at group-aligned windows the clipping is exact).
* **Hatari** (F030Arcade build, STE, 4 MB, TOS 2.06): attract, coin, start, play by keyboard and by the recorded play;
  no crash, no late border event (DEBUG counters, 6000 VBLs).
* Not done: sound (the M6803 board with two AY-3-8910s, the MSM5205 voices and the netlist drums: a recorded-driver
  player as `engine/capsnd.py` does for the Capcom boards would be the way), the flip screen (cocktail), the service
  mode (its code at $7666 is not translated: DSW2 bit 7 is off).

## Speed

`tools/bench.sh` (DEBUG build, 6000 VBLs from power-on, Hatari): the logic (arcade frames a second; the arcade 56.34)
and the pictures a second, separately; per 100 VBLs in RATE.BIN.

| run | logic | pictures |
|---|---|---|
| recorded play (`PLAY=1`), the whole run | 52.4 /s (93%) | 29.5 /s |
| recorded play, in play (VBLs 2000-6000) | 55-56 /s (~99%) | 24-39 /s |
| AUTOPLAY script (attract, coin, random play) | 48.8 /s (87%) | 31.1 /s |

Musashi (`render_test.py`, a picture's render_frame; `logic_test.py`, a frame's logic): the logic 37-47k cycles a
frame in play (21-27k in the level selection screens); a picture 125-160k CPU cycles and 15-36k Blitter bus cycles
(13 seeds' averages).  Where a picture's time goes (`render_test.py --prof`, seed 4): the sprite rows 25%, the front
tiles over the sprites 13%, bringing the ring to the window 11%, the sprite list 10%, cell copies 9%, the tile RAM
compare 7%.  The dips in the timeline are the scene changes (a new floor: the caches flushed, everything baked and
drawn again) and the window's jumps at the 512-pixel wrap (the ring's whole window copied).  The program needs
1,504,648 bytes (text 68 KB, data 454 KB: the dispatch table, the ROM and the graphics; BSS 982 KB: the four
playfield buffers, the caches).

## The schedule (src/kungfum.s)

The game's foreground waits for the IRQ in spin loops on RAM the IRQ handler changes ($E882: frames to wait, $E020
the intro's sequence, $E000 the state, $E904 / $E906 the inputs), and in play it runs a loop of HUD work (time,
score, extra lives) over and over while the IRQ handler plays the game.  Those pcs are idle hooks
(`machine.KungFuPort.HOOKS`, the translation's `z80_hook`): at a hook whose condition says the game waits, the runtime
draws the picture when due, waits for the next arcade frame and delivers the IRQ (RST 38) with a token as its return
address; the return continues at the hook (its instruction runs before the condition is looked at again), and a
handler that restarts the foreground (`jp $0217` at 012A / 0396: a coin in the attract mode) simply comes to the next
hook.  The play loop's head always yields: it runs once a frame instead of as often as the arcade's spare time
allows (its work is gated by the IRQ's counters, so the state is the same).  The VBL counts 56.25 arcade frames a
second (a second one every 8th VBL), at most 3 waiting; a picture at least every third frame.  `ld a,r` (the game's
random numbers) reads a shift register the reference has too.  The I/O ports: `in a,(n)` reads `io_ports`, `out (0)`
puts the sound command into a ring, `out (1)` the flip latch.  The tile RAM's 23 writers (from the coverage) mark the
64-byte row they hit; the renderer compares only marked rows with its copy.  The jump tables: coverage targets and
the 5th floor boss's table (`gen.py TABLES`); the other `jp (hl)` tables run whole or hold entries outside the ROM.

## The picture (src/render.s)

* **Two sources**, switched by `engine/rt/borders.s`' Timer B events (BD_HUD + BD_VSWITCH, as R-Type's status bar):
  the score panel (lines 0-47) from an image of its own with its own 16 colours, the playfield (lines 48-255) from a
  hardware-scrolled ring with the scene's 16 colours.  TA_DATA 98, PIC_TOP 10, PIC_LINES 256.
* **Virtual screens**: three rings and a clean screen of 304 lines x 424 bytes; buffer x b shows tilemap x (b mod 512)
  (twin columns up to 848), so the window Wx = (scroll + 96) mod 512 is contiguous: the video address by words,
  `$ffff8265` by pixels.  The tile RAM's changed cells are drawn (movep.l, baked per code, colour and scene in a
  cache) into the clean screen and marked in each ring's bitmap; a ring is brought to its picture from the clean
  screen with short HOG Blitter passes (`blit_go`): the columns the window's move brought into the picture span,
  the band columns blackened, its last sprites' rectangles, the marked cells (movep.l when inside the span).
* **Sprites**: cells baked on first use (see `docs/sprite-preparation.md`), a HOG pass a row (4 planes, under
  2 x 4 words), END1 / END3 from the row mask only when it changes, full destination addresses (no 64 KB limit).
  The picture's edges are at Wx + 32 and Wx + 288: a cell across the word boundary at or outside an edge draws only
  its inner word (left: FXSR, source X increment 0; right: the first word), a cell wholly outside is culled.  With Wx
  a multiple of 16 that is the edge itself (AGENTS.md); with the edge inside a word up to 15 pixels of a sprite show
  in the band (as Black Tiger's band words; nothing is erased after drawing), and the ring's next picture blackens
  them with its damage restore.  Top and bottom: whole cells into the guard lines (the panel covers the top).
* **Priority**: the tiles of colours 26-31 (MAME's category 1) copied back from the clean screen over the sprites'
  cells after drawing.
* **Colours** (`tools/assets.py`): a scene per floor (while a game or the demo runs) and one for the attract
  screens, each 16 colours: black (the bands) and 15 fitted by a weighted k-means in Oklab to that scene's pixels in
  the coverage runs, snapped to 4 bits a gun; every pen maps to the nearest.  The mean error per channel is 3.8-6.0
  of 255 (the playfield shows 30-51 colours a scene, 88 in all).  The panel: 15 fitted to its 36 pens (5.4).  A change
  of scene flushes the caches and draws everything again.

## The board (MAME irem/m62.cpp, m62_v.cpp)

* **Main CPU**: Z80 at 18.432 MHz / 6 = 3.072 MHz.  Map: $0000-$7FFF ROM, $A000 / $B000 write the scroll register's
  low / high byte, $C000-$C0FF sprite RAM (write only), $D000-$D7FF tile codes, $D800-$DFFF tile attributes,
  $E000-$EFFF RAM (stack at $F000 down).  I/O: reads 0 SYSTEM, 1 P1, 2 P2, 3 DSW1, 4 DSW2; writes 0 sound command,
  1 flip screen + coin counters.  IM 1; IRQ once a frame at the VBLANK (irq0_line_hold: held until acknowledged).
  The IRQ handler ($0038) copies the sprite list from RAM ($EB25.., 24 entries from $C020) and writes the scroll
  register right at the VBLANK, so the picture never changes mid-frame.
* **Sound board** (M6803 + 2 AY-3-8910 + 2 MSM5205): it only receives the command byte (bit 7 0 raises the M6803's
  IRQ); nothing comes back to the main CPU, so it is not emulated: `sound_log` keeps (frame, command).  In the attract
  sequence the game sends commands only at boot and around frame 2986 (no demo sounds).
* **Screen**: 6.144 MHz pixel clock, 384 x 284 total, 256 x 256 visible (x 128-383, lines 0-255), 56.34 Hz: 192 CPU
  cycles a line, 54528 a frame.
* **Tiles**: a 64 x 32 tilemap (512 x 256 pixels) of 8x8 3bpp tiles (1024, `g-4c/4d/4e`): code = $D000 byte + attr
  bits 6-7 << 8, colour = attr bits 0-4 (32 sets of 8 pens), attr bit 5 flips x.  Opaque.  Rows 0-5 (the score panel,
  48 lines) are never scrolled, rows 6-31 by the one 16-bit scroll register (x only).  Over the sprites: rows 0-5 and
  every tile whose colour >> 1 is above 12 (colours 26-31).
* **Sprites**: 32 entries of 8 bytes (colour, y 9 bits, code 11 bits + flip x/y, x 9 bits), 16x16 3bpp (1024 cells,
  `b-*`), drawn first to last (the last on top), pen 0 transparent.  The height PROM `b-5f` (by code >> 5) makes a
  sprite 1, 2 or 4 cells tall (16x16, 16x32, 16x64).
* **Colours**: two 256-pen palettes from 4-bit-a-gun PROMs (tiles `g-1j/1f/1h`, sprites `b-1m/1n/1l`; 2.2k / 1k /
  470 / 220 ohm, 470 ohm pulldown, MAME's compute_res_net), then m62_amplify_contrast scales both by 255000 / the
  brightest luminance.  MAME's `pen_color` (what the Lua sees) is the colour before that scaling, the screen after.
* **DIP switches**: MAME's defaults (DSW1 $FF: easy, slow energy loss, 3 lives, 1 coin 1 credit; DSW2 $FD: upright,
  coin mode 1, no cheats).

## The reference (tools/machine.py)

`KungFuMaster` runs the Z80 with `engine/z80mame.py` (MAME's core, resumable mid-instruction).  The schedule is
MAME's: the screen starts at the VBLANK, frame k ends at k x the frame period.  A CPU cycle (325520833333 as) is a
little longer than two pixels (2 x 162760416666 as), so up to frame k's end the CPU gets 54528 k - 1 cycles (and may
finish its last M-cycle beyond); the IRQ is taken at the next instruction.  Rounding this up to 54528 k takes the IRQ
one instruction late at some frames, and the game's random numbers (`ld a,r` into $E010-$E013) drift: MAME's
debugger trace (`trace` with `totalcycles`) showed the one-cycle difference.  `Video` draws a frame from the tile
RAM, the sprite RAM and the scroll register (numpy, `engine/mamegfx.py`).

## The reference against MAME (ref/mame_cmp_kungfum.py)

One MAME run (`engine/mame_frames.lua`) dumps $D000-$EFFF at each frame and taps the write-only registers (sprite
RAM, scroll, I/O ports 0 and 1); a second short run takes the sprite palette's pens.

* pens: 0 of 512 differ (both palettes, before the contrast);
* render: the reference renderer from MAME's memory, 0 differing pixels at 60, 120, 300, 600 ... 3600 (attract, the
  intro, the demo play with scrolling, the high-score table) and every 600 frames from 4200 to 13800, and 13801-13802;
* logic: the reference from power-on: 0 of 8192 RAM bytes, 0 sprite RAM bytes differ, the scroll register and the
  sound commands of the frame equal, at all the same frames (up to 13802, MAME's 250 s limit), and its own picture
  differs from MAME's in 0 pixels.

Not covered: the flip screen (cocktail; the renderer raises), play with coins and inputs (the comparison runs the
attract sequence only), the sound board.

