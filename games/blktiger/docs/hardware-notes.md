# Hardware notes from F030Arcade's MAME sources

## Main Z80

| Address | Function |
|---|---|
| `0000–7fff` | Fixed program ROM |
| `8000–bfff` | 16 banks of 16 KB from maincpu region `10000` |
| `c000–cfff` | One of four 4 KB background RAM banks |
| `d000–d7ff` | Text codes and attributes |
| `d800–dbff` / `dc00–dfff` | Low / high halves of 1024 palette words (`xBRG_444`) |
| `e000–fdff` | Work RAM |
| `fe00–ffff` | Sprites, buffered on rising VBL |

I/O uses separate Z80 ports, masked to eight bits. Ports `00–05` read system,
player 1, player 2, DIP 0, DIP 1 and freeze. Writes: `00` sound latch, `01` ROM
bank (`data & 15`), `03` coin lockout, `04` control (bit 6 screen flip, bit 7
text disable), `06` watchdog, `07` MCU, `08–09` scroll X, `0a–0b` scroll Y,
`0c` background/sprite disable (bits 1/2), `0d` background bank (`data & 3`),
`0e` background layout (zero = 64 by 128 tiles; nonzero = 128 by 64).

## Protection firmware

MAME wires port `07` writes to a command latch and MCU INT1. MCU P0 reads
consume the latch and clear INT1; P0 writes publish the response. The firmware
starts at `0100`, initializes RAM, enables edge-triggered INT1, and idles at
`011c`. Its handler at `0200` reads P0, masks A with `0f`, sets DPTR to `0800`,
executes `MOVC A,@A+DPTR`, publishes A on P0, and returns with `RETI`.

Unlike Heavy Barrel's firmware, this dump has a simple ROM lookup for every
command. The reference still executes the actual reset and interrupt code,
with explicit failure on an opcode outside the implemented subset. It does
not use a recorded command transcript. The STE interpreter uses the same synchronous reset/transaction schedule.
All 256 commands and the translated main CPU have passed lock-step checks;
MCU timing relative to real board cycles has not been validated.

## Video

Text uses 2048 8 by 8 tiles, two planes `{4,0}`, pen 3 transparent, palette
`300–37f`. Background and sprites each use 2048 16 by 16 tiles with four planes
`{half+4,half,4,0}`; MAME assigns the first plane the most significant pixel bit.
Background uses palette `000–0ff`, sprites `200–27f` with pen 15 transparent.

The draw order is background back half, sprites in descending RAM order,
background front half, text. Background colour codes 0/1 put pens 0–11 in front,
2/3 put 0–7 in front, 4/5 put 0–3 in front, and 6–15 have no front pens.
The back half excludes front pens and pen 15. MAME documents this priority
scheme as a guess rather than a decoded PROM.

Raw output is 256 by 256; visible rows are 16–239, with no rotation. Both
background RAM mappings and all scroll values must be checked, including wrap
and screen flip, before producing STE graphics. The MAME comparison reads the
saved video latches directly through Lua `emu.item`, since I/O write taps did
not capture the scroll latches reliably in the installed MAME.

## STE scrolling reference: stedaimakaimura

Checked `/Users/saschaspringer/Work/stedaimakaimura/emulator.s`:

* Lines 1344–1537 (`scroll_horizontal`) and 1539–1723 (`scroll_vertical`)
  redraw newly exposed tile strips when the scroll crosses 16-pixel boundaries.
  Horizontal deltas up to two blocks and vertical deltas up to three are handled
  incrementally; wrap-aware larger jumps request a full background refresh.
* Lines 2074–2104 select the display window by changing the video address in a
  512 by 256 planar screen, not by copying the viewport. Its 256-byte row stride
  puts each screen on a 64 KB boundary. Word-sized pointer arithmetic wraps the
  row/column positions within that screen. Two virtual buffers are swapped by
  exchanging their high address words.
* Lines 1784–1795 set fine scroll (`ffff8265`) and line offset (`ffff820f`).
  The line offset is 48 words for the 320-pixel viewport, reduced by four words
  when fine scroll consumes an extra 16-pixel group.
* Lines 2559–2582 (`timer_b`) reset the video counter's high byte when scanout
  crosses the 64 KB boundary, making the vertical ring wrap on the display.
* The renderer maintains visible-tile and sprite-damage bitmaps. Whole objects
  are drawn into hidden virtual-screen margins instead of being clipped to the
  display window.

This is a useful implementation pattern for Black Tiger's two-axis background,
with adjustments for its 256 by 224 viewport, 64 by 128 / 128 by 64 world maps,
and split priority around sprites. Cache tiles by world coordinates; derive
ring coordinates separately. Keep text and sprites anchored to the viewport
when the background moves. Invalidate each buffer on layout/flip changes,
large jumps, RAM edits and palette remapping. Test fine shifts 0–15, both axes
at ring wrap, and whole sprites across hidden edges. Timer B currently also
serves border opening in this repository, so its wrap scheduling needs to be
integrated with the existing STE runtime rather than copied independently.

## Validation so far

MAME 0.289 verifies all 20 ROMs. The reference renderer matches its own-state
snapshots at frames 700, 1500 and 2500 with zero differing pixels (2500 uses the
previous frame's sprite RAM, accounting for buffering). The comparison reads
MAME state and therefore validates pixels, not reference CPU execution.
Translated CPU state matches the cooperative reference through 6,000 frames
with reproducible random controls, in addition to the scripted coin/start test.
STE pixels match the palette-mapped reference in both layouts and orientations,
all fine shifts, page crossings and sprite-edge cases. The native port boots
in the pinned Hatari on a 4 MB STE. This does not establish full-speed rendering
or cycle-accurate board timing.

The STE uses two 768 by 544 buffers and a clean background cache. Its viewport
fits inside each buffer at every physical phase, so Timer B only removes the
bottom border; no video-counter wrap handler is necessary. Native drawing
permits at most two consecutive skipped frames to avoid starving the display
when the tick queue remains nonempty.
