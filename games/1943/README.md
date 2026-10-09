# 1943: The Battle of Midway

Target: a playable Atari STE port, registered as `1943`. The main-Z80 reference
machine, i8751 firmware interpreter, graphics renderer, ROM preparation and
bank-aware coverage are implemented. The bank-aware Z80-to-68000 generator is implemented;
no playable STE executable is available yet.

```sh
python port.py prepare 1943                 # auto: US archive if present, otherwise Euro
python port.py prepare 1943 --set 1943       # explicitly choose the available Euro set
python port.py prepare 1943 --set 1943u      # requires the US Rev C program ROMs
python port.py test 1943                    # ROMs, graphics and 700 reference frames
python port.py mame 1943                    # pixel checks at frames 100, 700 and 1500
python port.py cover 1943 1                 # bank-aware execution/read/write coverage
venv/bin/python games/1943/tools/gen.py      # emit 68000 code from prepared ROMs and coverage
```

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

See [hardware notes](docs/hardware-notes.md). A 1,800-frame seeded coverage run reached 3,700+ bank/PC pairs; static discovery
and generation produced 7,688 instructions across fixed code and banks 0/1,
with zero unsupported instructions. This is generation, not yet a validated
68000 executable. The next work is lock-step logic checks, the STE runtime and Blitter renderer, then Hatari
playability and timing checks. `build` and `run` report that the runtime is pending.

## Translator (2026-10-09)

`tools/gen.py` goes through `translate.compile_code` with `z80x.FAST`, the engine's window wrapper and `ldir`, and the
banked return rules of Black Tiger (`ret_value`, `direct_ok`).  There is no runtime yet: it generates (7688
instructions, none unsupported) and assembles, nothing more is tested.  The runtime to come must keep the rules of
`docs/porting-guide.md` ("The translator's register maps"): no long writes to d0-d3 / d6 in code called from the
translated program, IY is in a2, a0-a1 are scratch.
