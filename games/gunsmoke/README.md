# Gun.Smoke (Capcom, 1985) for Atari STE

MAME set `gunsmoke`. The main Z80 program (fixed ROM and four 16 KB banks) is
statically translated to 68000 code and runs on an unexpanded 8 MHz, 4 MB Atari STE
with keyboard and joystick input. Graphics use a fixed 16-colour Oklab palette; the
sound CPU and the YM2203s are omitted.

```sh
python port.py prepare gunsmoke      # verify the 32 ROMs, build the MAME regions
python port.py cover gunsmoke        # coverage: 14 seeded runs of 20000 frames (~3 min, needed by the build)
python port.py build gunsmoke        # -> run/gunsmoke/GUNSMOKE.PRG (ROMs and graphics embedded)
python port.py test gunsmoke         # reference, lock-step translation, renderer against the reference
python port.py mame gunsmoke         # the reference renderer against MAME's own picture (needs `mame`)
games/gunsmoke/tools/bench.ps1       # Hatari speed (Windows): ticks and frames a second
```

Controls: **5/6** insert coins, **1/2** start, **arrow keys** move, **Ctrl** or **Z**
shoots left, **Space** or **X** straight, **Alt** or **C** right, **Esc** quits.
Joystick port 1 plays player 1 (fire shoots straight). Wait for the attract mode
before inserting a coin.

## The reference machine

`tools/machine.py` (MAME `capcom/gunsmoke.cpp`): memory map, the four ROM banks (C804
bits 2-3), the sprite latch (C806 copies F000-FFFF), the protection reads C4C9-C4CB,
DSW defaults. **SYSTEM bit 3** is MAME's `IPT_CUSTOM` "VBLANK" without a read callback:
it always reads 1. The first version of the reference returned the real vertical blank
there; the interrupt handler skips its whole body when it reads 0, so the game never
left its first screen (the MAME picture checks did not notice: they render MAME's state).

The program is a cooperative kernel like 1942's: eight tasks at EF80, a scheduler at
00AD-00CE, tasks sleep with `call 0110`. `run_frame_port` is the runtime's schedule:
when the scheduler has found no ready task (00CE) the interrupt (RST 38) runs to
completion, returning to the scheduler's scan at 00B0, and the tasks it woke run until
it idles again.

## The translation

`tools/gen.py` translates the fixed ROM and the code of banks 0 and 2 (8294
instructions, `z80x.FAST`) with virtual pcs per bank, as Black Tiger's generator does:
a jump from fixed code into the window dispatches by the current bank, `ret` and
`jp (hl)` go through `gs_dispatch` with the natural pc. Every indirect read checks for
the window (`(hl)`, `(de)`, `(bc)`, `(ix+d)` and `(iy+d)`: with `FAST`, IY is the low
word of a2, which the first version did not check: `ld a,(iy+7)` read RAM instead of bank
2 at frame 683). Stores are not checked. The bank latch and the layer latch share one
`ld (de),a` (0295 / 02B1), which calls `gs_latch` after the store. E0F8 is a trampoline
the program writes into RAM (`call nnnn / ret`, the round scripts' code): it is native
(`gen.TRAMPOLINE`), and coverage records where computed jumps went (502 entries). The
33 instructions that write the text RAM set `fg_written`. The service mode (code in bank
3) is not translated.

Coverage (`ref/cover.py`): seeds 1-3 play from the attract mode, seeds 4-14 use MAME's
cheats (infinite lives, invincibility, the start round, one-hit bosses) to start at
rounds 1-10 and the ending. The start round cheat patches an instruction's operand
(`ld hl,$8068` at 08C5), so `logic_test.py --seed` patches the same operand in the
translated `move.w #$8068,d3` too (setting the pointer in RAM after a tick is too late:
the round's data is read within the tick). Random play with infinite lives alone never
gets past round 1's boss.

## The renderer

`src/gunsmoke_render.s`, the method of Commando's renderer (`docs/porting-guide.md`,
"Scrolling with virtual screens"):

* **Background**: 32 x 32 tiles from the map ROM (2048 columns of 8 tiles), a function of
  the scroll registers alone: D800/D801 along the screen's vertical axis, D802 the map
  rows' horizontal offset. Three display buffers are virtual screens with twin lines;
  the twin period is 320 (a band of 288 lines plus 32 for the overhang of whole 32-line
  tiles), with 32 lines above and below for the twins of tiles that cross line 320.
  Each buffer draws the tile rows that scrolled into its band since it was last drawn.
  A new D802 (the game slides it 0 -> 48 a line a frame, e.g. at the round's poster),
  background on/off or a jump of more than 200 lines redraws the band: about 1-1.8M
  cycles, the slow frames of the port.
* **The screen shows 48 pixels on each side of the 224-pixel window**: tiles and
  sprites drawn whole into the margins would be visible there, so each tile that
  reaches a side clears the two chunks there and each sprite over a side clears its 16
  lines of the side chunk (the damage list restores the chunk from its black twin).
* **Sprites** (128, entry 0 on top, 2048 codes, a y flip that mirrors on the screen):
  `tools/assets.py` generates the Blitter routines and mask streams of
  `games/1942/tools/spritegen.py` for the shapes (code, flip) the coverage drew most,
  within 900 KB: 1074 of the 1818 shapes seen, 96.5% of the draws. All 2008 shapes would
  take 2.85 MB. The other shapes go through `any_part`: the same Blitter calls, a row at
  a time, the end masks made from the shape's opaque rows (stored with the baked sprite).
* **Text**: Commando's list of visible characters drawn with `movep.l`; the
  transparent pens of a colour are those the lookup PROM marks $4F.
* **Baking**: tiles, sprites and characters are kept as pixel-value bit planes; a miss
  of the hashed cache makes the 16 pen masks of each row and a generated routine per
  colour bank ORs them into the four STE planes. One pool per kind.
* **Timers**: `wait_borders` also keeps HOG blits away from Timer A's palette switches
  (the picture's first lines were black when the palette came on late); text damage is
  restored in 2-line bursts.

Memory: 3.07 MB of program, data and buffers on the 4 MB machine.

## Speed (2026-10-09)

`tools/bench.ps1` (DEBUG + AUTOPLAY build, 6000 VBLs in Hatari, boot and attract
included): 54.4 game ticks a second (91% of the arcade's 59.6) and 29.0 drawn frames a
second. `render_test.py` (Musashi, CPU + Blitter): a frame of consecutive play costs
84-380k cycles (median 84k in round 1, 243k in round 3, 381k in round 7), a full
redraw 1-1.8M.

## Validation

* All 32 ROM files pass the checked-in MAME CRC32/SHA1 manifest.
* The reference renderer and palette matched MAME's screenshots exactly at frames 100,
  700, 1500, 2500, 4000 and 6000 and in play (checked on the machine with MAME 0.289; this
  Windows machine has no current MAME, so the VBLANK fix of the reference is checked
  against the driver source and the attract mode, not a MAME run).
* `logic_test.py`: the translation equals the reference (RAM, video RAM, latches, bank,
  sprite latch, every text RAM change flagged) for 6000 frames each of seeds 1, 2, 4, 5,
  6, 9, 12 and 14: attract, coin, start, play, deaths, rounds 1, 2, 3, 6, 9 and the
  ending.
* `render_test.py`: pixel exact through the colour map in consecutive play (rounds 1, 3,
  7, the ending), spaced samples (rounds 6, 9), a sweep of S and D802 over their range,
  and whole sprites at the window's edges; the side bars stay black.
* Hatari (F030Arcade build, STE, 4 MB, TOS 2.06): attract mode, coin, start, the round
  poster with its sideways slide, play.

Not done: sound, the flip screen (the DIP switch is upright), the service mode, a
cheaper D802 slide (a Blitter shift of the band instead of a redraw).
