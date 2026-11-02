# Mr. HELI: the main CPU's side of the i8751 MCU (agent A, 2026-11-02)

What the translated V30 program (games/mrheli/tools/gen.py, src/core.s) does with the MCU, for the STE MCU model.
Measured on the reference board (engine/m72board.py, MAME 0.286 m72.cpp `m72_mcu_state`) with the scripts in the
session scratchpad: 1500 attract frames and 6000 frames of invulnerable play (seed 8) from power-on.

## The hardware (MAME `m72_8751`, `m72_protected_map`)

* MB8421/MB8431 dual-port RAM, 4 KB (0x800 words, little endian).  Main CPU side (left): $B0000-$B0FFF.  MCU side
  (right): data space $C000-$CFFF.
* The main CPU's writes reach it through `synchronize()` (delayed_ram16_w); the MCU's through `synchronize()` too.
* Mailbox: a main CPU write to the last word (byte offset $FFE/$FFF, word $7FF) raises INTR = the MCU's INT0; the MCU
  reading $CFFE/$CFFF clears it.  INTL (the main side's mailbox, word $7FE) is not connected (no main CPU interrupt).
* The MCU's other data addresses: $0000 read = the sample ROM byte (address auto-increments), $0000 write = sample
  address bits 5-12, $0001 write = bits 13+, $0002 read = the sound CPU's latch (Z80 `out ($82)` -> INT1), $0002
  write = its acknowledge.  Port 1 = the DAC.

## Boot (not translated; the port starts at machine.py START = frame 500)

From frame ~11 the MCU fills the dual-port RAM (test patterns, then V30 code) and the main CPU runs that code at
B000:xxxx until frame ~490 (its wait loop B0190-B01A8; handshake words at $7F8, $7FA, $7FC written by the main CPU,
$7F7 read).  The MCU's last writes are at frame 483: among them the strings "IREM  CORPORATION  1987" at $900, $A40
and $B00 (and "(C)IREM CORPORATION" around $8F0).  None of this runs again later (no MCU write to the dual-port RAM
after frame 490 in either run).

The STE port therefore takes the dual-port RAM's contents from the snapshot (the reference at START; logic_test.py
loads it into the image) and needs no MCU for the main CPU's logic.

## In the game (after the boot): the only main CPU accesses

| site (CS 0040) | linear | access | what |
|---|---|---|---|
| 0040:034C | 0078C | `inc byte ptr [0FFEh]` with DS0 = B000 (read, then write) | every VBL, first thing in the handler: the MCU's INT0 once an arcade frame |
| 0040:7F20 | 08320 | `mov aw,[ix]` with DS0 = B000, then `cmp al,49h` ('I') | the protection check, a subroutine at 0040:7F1A, called from 0040:2327 (IX = $B00), 0040:7F26 (IX = $900) and 0040:96AD; if the byte is not 'I' the object is killed (jump to 0040:20A8) |
| 0040:1ECA | 022CA | `out 0C0h,al` with AL = $10, the object's next state 0040:1ED9 | command $10 (agent B: the MCU copies its ROM $0C3F-$0C5D, 31 bytes, to $B0000) |
| 0040:1ED9 | 022D9 | `call B000:0000` (one arcade frame after the $10) | runs the MCU's code in the dual-port RAM (a protection check) |

The last two were not reached in my first measured runs (1500 attract, 6000 play frames), so no MCU write showed
there; agent B found them in the MCU program.  The translation takes the 31 bytes from the MCU ROM as code at
B000:0000 (they are static).  The reference's port schedule runs the real i8051 (engine/i8051.py), so the copy, the
wipe of $B0000-$B001F three timer ticks later and the watchdog byte $B0FFC appear in the lock-step as on the board.
The mailbox byte is a frame counter (it wraps; the MCU counts its writes as a watchdog).

## Sound (no main CPU involvement)

The main CPU sends sound commands through two latches: port $00 (the Z80's latch, RST 18) and port $C0 (the second
latch: the Z80's NMI; the samples).  The Z80 passes sample requests to the MCU through its port $82 (MCU INT1, data
$0002); the MCU plays them from the sample ROM (c-v0-b.rom) on its port 1 DAC.

## What the translated side offers the STE MCU model

* The image: `v30_image` is the V30's 1 MB with the bytes of each word swapped (V30 byte a at `v30_image + (a ^ 1)`).
  The dual-port RAM is at `v30_image+$B0000`; the mailbox byte $B0FFE is at `v30_image+$B0FFF`.
* `port_frame` (src/core.s) runs one arcade frame of the main CPU: the VBL handler (which increments the mailbox
  byte), then the raster interrupt(s).  An MCU model can run once per `port_frame` (one INT0 per arcade frame), or
  compare the byte with its last value.
* Sound commands: `sound_cmds` / `sound_head` (port $00, a 64-byte ring, head = the next slot) and `sound2_cmds` /
  `sound2_head` (port $C0).  They are what the Z80 side (and through it the MCU's samples) gets.
* Exactness: `tools/logic_test.py` compares the whole dual-port RAM ($B0000-$B0FFF) with the reference every frame
  (the reference's port schedule runs the i8051 too: tools/machine.py MrHeli).

## The MCU (agent B)

The i8751 (`assets/roms/mh_c-pr-.ic1`, 4 KB, 654 instructions; `engine/i8051dis.py`) after the boot as a native
model: `tools/mcu.py` (Python, the twin) and `src/mcu.s` (68000). MAME's "protection simulation" comment block in
`m72.cpp` is stale (made-up routines from before the dump); MAME runs the real program (`m72_8751`).

### Boot (frames 0-483 of a power-on): not modelled

The MCU's RAM test; it checks the V30's dual-port RAM pattern (`(page & 15) + offset`) and writes it back inverted;
then per step it writes the V30 code `inc byte cs:[7FE]; jmp $` (19 bytes, ROM `$0614`) to `$B0000` and one of 10
test / start routines (ROM table `$0087`: 6-byte entries source, destination, count) to `$B0010 + $58`, patches the
`jmp` (`$B0006 = 9 + $58`) to start it, and the routine returns by `jmp aw = 0`; the letters `S A M O T O` go to
`$B07F7` (the V30 keeps them at RAM `$3838`). `$58 = TL1 & $7F` (`$7x -> $6x`): timer 1 runs free and is read when
the MCU sees the V30's counter `$B07FE` change, so the code's place, the V30's stack and the number of `inc` the V30
makes while the MCU patches all depend on the cycle at which the V30 wrote. Not reproducible without cycle-exact V30
timing: the port starts after it (any frame boundary `>= mcu.BOOT_END = 484`; START = 500). At frame 481 entry 9
jumps to the game (`0040:0168`); 481-483: 16 copies of ROM `$002F-$006E` to `$B0800-$B0BFF`, `$B0000-$B001F` wiped
(`$20 $1F ... $01`), the main loop entered with `$58 = 0`.

### The main loop (what the model does)

* **Heartbeat / watchdog.** INT0 = a V30 write to `$B0FFE/F` (`$5D + 1`). Timer 0 (reload `$D0AA`, restarted by its
  handler: 12118 cycles + latency = 1.0013 frames): exactly one heartbeat since the last tick resets `$44`, else
  `$44 + 1`; at `$44 >= $1E` the MCU writes `$44` to `$B0FFC` for ever and does nothing else (no samples). The model
  ticks once a frame, so its `$44` stays 0 while the V30 increments `$B0FFE` every VBL; the real tick drifts against
  the frame and its `$44` reached 5 in 7500 reference frames (never near `$1E`). Not visible to the V30 below `$1E`.
* **Commands**: V30 port `$C0` -> sound latch 2 -> Z80 NMI -> the Z80 writes the same byte to port `$82` -> INT1,
  in the same line (the V30 writes port `$C0` in its VBL handler, line 256-257).
  * `$10`: ROM `$0C3F-$0C5D` (31 bytes: `mov [bp+0],0470h`, sum of the 6 words at RAM `$3838` = `$01D3` or
    `jmp 0040:00A3`, `retf`) to `$B0000 + $58 = $B0000` (copied 4-12 lines after the latch), `$5B = 3`; 3 timer 0
    ticks later the main loop wipes `$B0000-$B001F` again. The V30's object task 0040:1ECA sends `$10` (and sets
    the task to 1ED9, which calls `B000:0000` one frame later); the task's address is in a ROM table (`$18857`).
    Not reached by random play so far; `mcu_test.py --check F` forces it (task `[3712]` = 1ECA one frame, 1ED9 the
    next): exact. (Run back to back in one frame, the V30 executes the wipe bytes before the copy: the game needs
    the frame in between, as its object tasks give.)
  * `$11`: the ROM test's answer: ROM `$0907-$0912`, then the ROM's 16-bit sum + ROM `$0C5E/F` (= `$0000`) at
    `$B0FE0-$B0FED`, 65721 cycles (5.4 frames, interrupts off: no samples, no ticks) after the latch; then the MCU
    stops in `045E` (samples only). The model writes the answer at the first frame boundary after that time.
  * any other byte n: a sample. Entry `$006F + 4n` (the offsets wrap at 256: `n & 63`): `[0]` bits 0-6 priority
    (lower wins), bit 7 restart on an equal one; `[1] + $AD` the timer 1 reload (a byte every `256 - reload` cycles:
    83 = 8.03 kHz for 0-5); `[2]` bits 4-7 volume, bits 0-3 address bits 13-16; `[3]` address bits 5-12. Taken when
    its priority is below the playing one's (`$FF` idle; set again when the byte 0 ends a sample) or equal with the
    restart bit. The DAC gets the byte (`$80` = 0) scaled: volume 0 as is, `$10-$70` x (1 + v/256) clipped at `$7F`,
    `$80-$F0` x v/256 (`mcu.dac_value`). The table's 0-5 are real (0: an empty sample = stop); the game used 1, 3, 4.
* The V30 reads (after the boot) `$B0900/1`, `$B0B00/1` (agent A's 0040:7F20), `$B0FFE` and, in the check,
  `$B0000-$B0018`, `$B001E`.

### Files and checks

* `tools/mcu.py`: `MCU.from_board(board)`, `frame()`, `v30_write(o, n)`, `command(v, units)`, `state_image()`;
  `--tables` writes `build/mrheli/mcu_tables.s` (from the ROMs: `mcu_check`, `mcu_romans`, `mcu_samples`,
  `mcu_sample_addr`).
* `tools/mcu_test.py [frames] --seed N [--check F] [--romtest F] [--starve F] [--trace T]`: the board from power-on,
  the model from frame 484 with only the STE's inputs (V30 dual-port RAM writes, port `$C0`, frame boundaries).
  Checked: every byte the V30 reads from the dual-port RAM (fetches included), the whole RAM at every frame
  boundary (reported; timing-only differences: the wipe's tick and the ROM answer's frame), every sample command
  (taken, address), every sample's DAC bytes, the samples' ends (lines, board - model).
* `tools/mcu68k_test.py T [--poll] [--noswap]` / `--synthetic N`: `src/mcu.s` on Musashi on a trace of
  `mcu_test.py` (the board's bytes) or a synthetic one made by the model (heartbeat gaps up to the watchdog, the ROM
  test, random commands at any time of a frame).

### The 68000 interface (`src/mcu.s`)

All entries keep every register; `a0` = `v30_image + $B0000`. `include "mcu_tables.s"` needs `-I build/mrheli`.

| entry | when | in |
|---|---|---|
| `mcu_init` | once, after the snapshot is loaded | `a1` = the 14 bytes of the model's state (`MCU.from_board(board at START).state_image()`: store them with the snapshot) |
| `mcu_frame` | every arcade frame boundary (the board's line 256), before the V30's VBL interrupt | |
| `mcu_cmd` | the V30 writes port `$C0` | `d0.b` the byte, `d1.w` units (1/3 MCU cycle = 4 V30 cycles) since the boundary; the VBL handler's: 128 |
| `mcu_hb` | the V30 writes `$B0FFE` or `$B0FFF` (0040:034C) | |

Options: `MCU_SWAP` (1, default: V30 byte `o` at `a0 + (o ^ 1)`; 0: V30 order), `MCU_HB_POLL` (0, default; 1: no
`mcu_hb`, `mcu_frame` counts a heartbeat when `$B0FFE` changed since the last frame: exact while the V30 writes it
at most once a frame, as it does). For the sound code (DMA, later): `mcu_snd_start.b` = the command taken last (`$FF`
none: the sound code clears it), `mcu_snd_count.w` + 1 a start; the sample's data from `mcu_sample_addr`, its DAC
stream = `mcu.dac_value` of its bytes at 8.03 kHz (prepare per command at build time; a new start cuts the old).

Cost (Musashi): `mcu_frame` ~420 cycles mean (1900 with the wipe), `mcu_cmd` ~550 (1650 for `$10`), `mcu_hb` ~70.

Python port schedule (`tools/machine.py MrHeli`): `self.mcu = mcu.MCU.from_board(self)` after `boot()` (it shares
`self.dpram`), `self.mcu.frame()` at each port frame's start, `self.mcu.v30_write(o, n)` at dual-port RAM writes,
`self.mcu.command(v, 128)` at port `$C0`.
