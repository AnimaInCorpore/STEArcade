# Hardware requirements

Source: `F030Arcade/third_party/jsm68kdisassembler/third_party/mame/src/mame/capcom/1943.cpp`,
`1943_v.cpp` and `1943.h`. ROM sets: `1943` (Euro, available) and `1943u` (US Rev C), display rotation ROT270.

* Main Z80: 6 MHz. Sound Z80: 3 MHz. i8751: 3 MHz.
* Raster: 384 clocks by 262 lines, visible x=0..255 and y=16..239.
  Main CPU held IRQs at lines 144 and 240. Sound IRQs at lines 32, 96, 160 and 224.
* Fixed ROM at 0000–7fff; eight 16 KB banks at 8000–bfff, selected by
  bits 2–4 of c804. Bank images begin at maincpu region offset 10000.
* Inputs at c000–c004; c000 bit 3 is active-high VBL. MCU reply at c007.
  c800 is the sound latch. c804 also controls sound reset (bit 5), screen flip
  (bit 6), and character enable (bit 7). c806 explicitly buffers sprite RAM;
  buffering must follow this write rather than assume a VBL latch.
* Main CPU command to the MCU at c807. MCU P0 reads the command and writes
  the reply; a falling edge of P3 bit 6 transfers P0 to the CPU reply latch.
  P2 communicates with the sound CPU. P1 reads the scanline. VBL asserts INT1.
  Execute the dumped firmware; do not bypass protection or replace replies.
* Character RAM d000–d3ff, attributes d400–d7ff. Front layer scroll X
  d800–d801, scroll Y d802. Back layer scroll X d803–d804. Layer enables at
  d806: front bit 4, back bit 5, sprites bit 6. RAM e000–efff;
  sprite RAM f000–ffff, one four-byte entry per 32 bytes.
* Two ROM tilemaps, 2048 columns by eight rows of 32x32 tiles, column-major.
  Front map occupies tilerom 0000–7fff, back map 8000–ffff. Attributes:
  bit 0 extends the front code, bits 2–5 colour, bits 6–7 X/Y flips.
  Character map is 32x32 8x8 tiles, row-major; attribute bits 5–7 extend
  the code, bits 0–4 colour. Transparent character pen is 0.
* Sprites are 16x16; attribute bits 5–7 extend the code, bits 0–3 colour,
  bit 4 subtracts 256 from X. Transparent sprite pen is 0. Earlier entries
  win overlapping pixels, including when hidden behind the front layer.
  Sprite priority against the front layer depends on bit 3 of the sprite
  palette-bank PROM at 0900 + colour*16 + pen.
* Front tile transparency uses indirect palette colour 0x0f, not a fixed
  decoded pen. Palette lookup PROMs map characters, both backgrounds and
  sprites to 256 RGB colours. RGB PROM nibble weights in the driver are
  0x0e, 0x1f, 0x43, 0x8f. Validate against installed MAME screenshots before
  building the STE graphics.

Reference boot, MCU command checks, and MAME pixel comparison are implemented.
Next steps: bank-aware code coverage and whole-program translation;
lock-step logic verification; STE runtime and renderer using the whole-object
Blitter approach in the porting guide; simulator pixel tests and Hatari gameplay
and timing checks on an 8 MHz 4 MB STE.
