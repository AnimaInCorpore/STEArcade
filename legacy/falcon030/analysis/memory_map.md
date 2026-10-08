# Donkey Kong Memory Map Analysis

Based on MAME source: `C:/Arbeit/F030Arcade/third_party/jsm68kdisassembler/third_party/mame/src/mame/nintendo/dkong.cpp`

## Main CPU (Z80)

### Memory
- `0000-3FFF` ROM (Donkey Kong Jr. and Donkey Kong 3: 0000-5FFF)
- `6000-6FFF` RAM
- `7000-73FF` sprites
- `7400-77FF` Video RAM
- `8000-9FFF` ROM (DK3 only)

### Memory-mapped I/O
**Read:**
- `7C00` IN0  (Player 1 controls)
- `7C80` IN1  (Player 2 controls)
- `7D00` IN2  (Coin/Start, DK3: DSW2)
- `7D80` DSW1 (Dip switches)

**Write:**
- `7800-780F` P8257 Control registers
- `7C00` Background sound/music select
- `7C80` gfx bank select (Donkey Kong Jr. only)
- `7D00` digital sound trigger - walk
- `7D01` digital sound trigger - jump
- `7D02` digital sound trigger - boom
- `7D03` digital sound trigger - coin input/spring
- `7D04` digital sound trigger - gorilla fall
- `7D05` digital sound trigger - barrel jump/prize
- `7D06` ?
- `7D07` ?
- `7D80` digital sound trigger - dead
- `7D82` flip screen
- `7D83` ?
- `7D84` interrupt enable
- `7D85` 0/1 toggle
- `7D86-7D87` palette bank selector

### I8035 Sound CPU
- `0000-07FF` ROM
- `0800-0FFF` Compressed sound sample
- Read ports: 0x20 Read current tune, P2.5, T0, T1
- Write ports: P1 Digital out, P2.7 External decay, P2.6 Select second ROM, P2.2-0 Bank select

## Screen Orientation
From MAME: MASTER_CLOCK 61.44MHz, PIXEL_CLOCK 6.144MHz
HTOTAL 384/HBSTART 256/HBEND 0, VTOTAL 264/VBSTART 240/VBEND 16
Visible 256×224, total 384×264.
MAME declares Donkey Kong with `ROT270`; validate the rotated 224×256 portrait presentation
against a reference frame before choosing the Falcon framebuffer layout.

## Notes
- Do not confuse the raw 256×224 raster with the final portrait presentation; implement and test
  the required rotation and cocktail/flip-screen behavior.
- DSP 56001 available for later offload
- Final output: Atari .PRG with GEMDOS header, assembled with VASM/RMAC
- Sprite placement (MAME `draw_sprites`, verified against a MAME snapshot with 0 differing pixels): raw row
  `top = 247 - y` (not 246: the hardware line buffer fetches a sprite one scanline ahead), raw column `x - 8`.
- Pen colours are MAME's resistor network output, not weighted PROM bits; use `games/dkong/tools/dkong_pens.py`.
  The method (MAME `-window`, Lua dump of pens, memory and snapshot, pixel compare) is in `docs/porting-guide.md`,
  "Checking a reference against MAME".
