# Bubble Bobble (Taito 1986) — hardware model used by the host reference

Sets: `bublbobl` (Japan) and `bublboblr` (US, Romstar licence) — see `rom_manifest.md`.
Only the two main-CPU ROMs differ; the model in `tools/bubble.py` runs both (`Bubble(variant=...)`).
**Port target set: `bublboblr`** (US); `bublbobl` is the cross-check.

Evidence grades: **Code** = read in the ROM disassembly; **Run** = reproduced by running the
original ROMs in the host model (frames compared by eye against the known game);
**Hyp** = recalled/assumed, not yet independently confirmed.

## CPUs

| CPU | clock | ROM | notes |
|---|---|---|---|
| main Z80 | 6 MHz | `a78-06-1.51`/`a78-25.51` at $0000-$7FFF, 4 banks x 16 KiB at $8000-$BFFF | `di; im 2; jp $00B9`; all game logic runs in the IM2 handler, foreground is `ei; jr $` at $01ED (Code) |
| sub Z80 | 6 MHz | `a78-08.37` | `di; im 1; ld sp,$F7CE`; shares $E000-$F7FF with main; IRQ at vblank (Run) |
| sound Z80 | 3 MHz | `a78-07.46` | YM2203 @ $9000/1, YM3526 @ $A000/1, latch @ $B000 (Hyp; sound is deferred) |
| MCU | MC6801 (4 KiB ROM at $F000, internal RAM $40-$FF) | `a78-01.17` | **not a 68705** — opcodes/vectors read as 6801 (Code). E clock = 750 kHz assumed (Hyp) |

## Main CPU map (model)

| range | use | grade |
|---|---|---|
| $0000-$7FFF | ROM | Code |
| $8000-$BFFF | banked ROM, bank = `$FB40 & 3` | Run (attract mode uses banked data/code with this rule); whether bit 2 matters is Hyp |
| $C000-$DCFF | "videoram": tile codes for the strips below | Run |
| $DD00-$DFFF | "objectram": 192 strip entries of 4 bytes (Y, num, X, attr) | Run |
| $E000-$F7FF | work RAM shared with the sub CPU | Code (boot RAM test, sub SP) |
| $F800-$F9FF | palette RAM, 256 x RGBx4444, high byte at the even address | Run (colours look right) |
| $FA00 | sound command | Hyp |
| $FA03 | sound NMI enable | Hyp |
| $FA80 | watchdog | Code (written in loops) |
| $FB40 | bank (bits 0-2), bit 4/5 = reset of sub+MCU / sound, bit 6/7 flip | Hyp for bit use; boot writes `$04,$44,$74` (Code) |
| $FC00-$FFFF | 1 KiB RAM shared with the MCU | Code |

### $FB40 bit 4/5 and the MCU
The boot RAM test of $FC01-$FFFF would be corrupted by a running MCU (the MCU writes its `$37`
handshake into $FC85 long before the test ends and the test later zeroes it). The model therefore
holds the sub CPU **and the MCU** in reset until the main CPU writes `$74` (bit 4 set). Run-confirmed
that the game then boots; *which* bit really drives the MCU reset is still Hyp.

## MCU <-> board protocol (Code, from `a78-01.17` routines $F1BF/$F1DB)

* Port 1: bits 0-3 inputs, bits 4-7 outputs. P1.7 = read(1)/write(0); P1.6 falling edge = raise main IRQ
  with vector = shared RAM[$FC00]; P1.4 = coin enable (written from `$FF94`, see below); P1.5 = set at start.
* Port 2 bits 0-3 = address high nibble, bit 4 = strobe (rising edge executes the bus cycle).
* Port 4 = address low byte; Port 3 = data.
* Address space seen by the MCU: `addr & $C00 == $C00` -> main $FC00 + (addr & $3FF); `addr < 4` -> input ports
  `0:DSW0 1:DSW1 2:IN0 3:IN1` as copied by the MCU to $FC20-$FC23 (main tests `$FC20` bit 2 as service mode).
* The MCU runs its vblank (IRQ1) handler at $F046, which: acks/pulses the main IRQ **only when $FF98 == $47**
  (set by the main CPU just before its idle loop), copies P1 pins to $FC1F, input ports to $FC20-$FC23,
  maintains credit counters, increments a heartbeat at $FC7C, and computes a 16-bit sum of its own ROM
  into $FC82/$FC83 (main requires 0) — so the **real MCU ROM is required**; it cannot be skipped.
* P1 pins: bit0 = tilt (idle 1: main CPU shows TILT and resets if $FC1F bit 0 is 0), bit1 idle 1 (role Hyp),
  bits 2/3 = coin 1/2, **active-high pulses, counted on the falling edge** (idle 0) (Code: $F16F edge coder, Run).
* `$FF94`: main writes `$FF` to enable coins while credits < 9, `$01` to lock them out (Code $0C5A-$0C67; MCU $F1B0).

## Video (Run)

No tilemap. A frame is a list of up to 192 *strips* in objectram: Y, `num`, X, `attr`.

* `num & $1F` picks 0x80 bytes of videoram (two columns of 32 tiles, 2 bytes each: code low, then
  `hhcccc cc`: bits 0-1 code high, 2-5 colour, 6 flipX, 7 flipY); `(num & $A0) == $A0` adds $1000.
* `num & $E0` selects a PROM line (`a71-25.41` + $80 + (num&$E0)>>1); PROM byte `[line + yc/2]`:
  bit 3 = skip this tile row, bits 0-1 = which 16-byte group of the column (so lines 0-3 are bottom-anchored
  two-row sprites, lines 4-7 full 32-row strips).
* Tile code = low + 256*(hi&3) + 1024*(attr & $0F); transparent pen 15; 16 palette groups of 16.
* **X continuation (Hyp, Run-supported):** if PROM bit 2 of the line's last row is set (gfx_num >= $C0) the
  strip is placed at *previous strip's X + 16* instead of its own X byte. Without it the title/level backgrounds
  collapse onto x=0; with it they render correctly (title logo, brick walls on both sides). `attr & $40` is X bit 8.
* Char ROMs: 4 bpp, planes (0,4 of the first half, 0,4 of the second half), 8 px = 2 bytes, region inverted
  (`tools/bbvideo.py:decode_chars`). Text and the logo are legible, which also settles the plane order.
* Visible area 256x224 (lines 16..239 of the 256-line strip space).

## Open items

* Sound: nothing beyond logging $FA00 / YM writes. Needs its own phase (YM2203 + YM3526 -> STE has no FM).
* DIP defaults: model feeds `$FF` to all four ports; the US set then shows the "FOR USE IN JAPAN ONLY"
  notice screen — DSW bit meanings must be read from code before choosing the shipped defaults.
* Player inputs (IN0/IN1 bit assignment) not yet mapped.
* Flip-screen ($FB40 bits 6/7) not rendered.
