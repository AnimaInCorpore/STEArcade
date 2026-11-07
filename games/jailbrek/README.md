# Jail Break (Konami, 1986) on the Atari STE

![Jail Break on the STE (Hatari)](docs/screenshot.png)

MAME set `jailbrek` (Konami GX507; `konami/jailbrek.cpp`, `k005849.cpp`; the clones `jailbrekb`, `manhatan` are not
used).  The main CPU, a KONAMI-1 (an MC6809 with encrypted opcodes, 32 KB of ROM), is statically translated to 68000
code (`engine/m6809x.py`, 6,052 instructions) and checked against a reference board in lock-step; its idle point is a
native that delivers the Konami 005849's interrupts (eight NMIs and the IRQ a frame).  The VLM5030's BSY pin, which
the game polls, is modelled (in the reference and in the runtime); **the SN76489A and the speech are not played yet**
(no sound).  The picture is MAME's, 240 x 224, at screen x 48-287 with the top and bottom borders open, sprites by
generated code (`engine/sprite_programs.py`), exact against the reference in the shown colours; one 16-colour palette
by the shared default fitter.  Status: **Incomplete** (no sound; no full-game verification).
Speed (Hatari, STE, 4 MB, `tools/hatari.ps1`, the AUTOPLAY script, DEBUG build, 2026-11-07): in play about 50 arcade
frames a second (83% of 60.6) and 12 pictures a second; no tuning done yet.

## Build and run

```sh
python port.py cover jailbrek               # coverage: ref/cover.py seeds 1-12 (~10 min in parallel)
python port.py build jailbrek               # -> run/jailbrek/JAILBREK.PRG
python port.py test jailbrek                # lock-step (seeds 1, 3, 6), render (seed 3), sprite edges
python port.py run jailbrek shot@30         # Hatari (F030Arcade build), screenshot at 30 s
python port.py mame jailbrek                # the reference against MAME (ref/mame_cmp_jailbrek.py)
python games/jailbrek/tools/prepare.py      # verify assets/roms/jailbrek.zip, unpack to assets/roms/extracted/jailbrek/
python games/jailbrek/tools/build.py        # -> run/jailbrek/JAILBREK.PRG (--sim: run/jailbrek_sim; --assets: colours again)
python games/jailbrek/tools/logic_test.py 20000 --seed 3  # the translation in lock-step with the reference
python games/jailbrek/tools/render_test.py 3000 --seed 3 --start 700   # the STE picture against the reference
python games/jailbrek/tools/sprite_test.py                # edges, all 16 shifts, holes, guards, 64 KB crossings
powershell -File games/jailbrek/tools/hatari.ps1          # hidden Hatari: AVI, stills and counters (AUTOPLAY build)
python games/jailbrek/ref/mame_cmp_jailbrek.py [frame ...]  # the reference against MAME (wolfmame-0248)
```

Supply `assets/roms/jailbrek.zip` (MAME's parent set; `docs/rom_manifest.json` has the files' sizes, CRCs and
SHA-1s).  Nothing ROM-derived is in git: the graphics, colours and ROM image are made into `build/jailbrek/` and
assembled into the program.  The program is 3,317,500 bytes (text + data + BSS + 256) to load (`tools/release.py` MAX_LOAD 3,700,000).  Paths
are relative to this folder; `engine/`, `tools/`, `port.py` and `docs/` at the top are the repository's.

## Controls

**5/6** coin 1 / 2, **1/2** start, player 1: arrows move, **Space / Control** fire (button 1), **X / Alt** select
the weapon (button 2); player 2: **W A S D** move, **Q** fire, **E** select.  **Esc** quits.  Joystick port 1 player 1,
port 0 player 2.  Jaguar pad / PowerPad: pad A player 1, pad B player 2, the D-pad moves, **A / C** fire, **B**
selects, **Option** coin, **Pause** start.  DIP switches: MAME's defaults (3 lives, upright, bonus 30K 70K+, difficult,
demo sounds on, no flip, single controls).

## State

* **Logic**: exact against the reference's port schedule.  `tools/logic_test.py`: RAM $0000-$203F (colour and video
  RAM, sprite RAM, work RAM, scroll RAM), the video chip's control registers, the speech chip's BSY pin and its count,
  every frame.  Seeds 1-12, 20,000 frames each (attract, coin, start, random play to the game over and again; lives
  and weapons by MAME's cheats; two players; the other DIP switches).
* **Picture**: exact in the shown colours.  `tools/render_test.py`: 0 differences in the sampled pictures of seed 3's
  play (frames 700-3000) and of its attract mode; `tools/sprite_test.py`: 136 made-up pictures exact (both side edges
  at every shift, holes, flips, overlaps, x from -256, the guard lines, 64 KB crossings, 60 pictures in a row with
  moving sprites, scrolls and tiles).  `BLIT_STATS=256`: every pass HOG, the longest 124 bus cycles.  The reference
  equals MAME (How it works).
* **Hatari** (F030Arcade build, STE, 4 MB, TOS 2.06): boot (the RAM test), attract, coin, start, play (the scripted walk and fire: score 0 -> 400 in
  the stills, the 1UP, the lives, the weapon box, the car, enemies and shots), the score ranking; no crash, no late border event in 3,001 VBLs (2 border
  fallbacks).  Colours as the arcade's (a 16-colour fit).
* Not done, most important first: **the sound** (SN76489A, speech; the VLM5030's BSY pin is modelled, so the
  game's speech state machine runs); a full-game playthrough (the coverage is random play with lives and weapons
  cheats: the stages beyond the first were seen only as far as that play got); the cocktail flip (ctrl 4 bit 3: the
  reference renderer stops there); the 005849's column-scroll mode (ctrl 2 bit 2: in the reference renderer, never
  set by the game, not in `render.s`); the service mode; speed (below).

## How it works

### The board and the reference

`tools/machine.py` follows MAME's `konami/jailbrek.cpp` and `k005849.cpp`: the KONAMI-1 at 1.536 MHz, 60.6 Hz, 264
lines of 96 cycles.  The Konami 005849's timer runs every 16 lines: an NMI every 32 lines from line 16 (eight a frame;
its enable is ctrl 4 bit 0), the IRQ at line 240 (bit 1; an FIRQ every other frame, bit 2, never used), writing ctrl
4 with an enable bit 1 -> 0 clears that line.  RAM: colour RAM $0000-$07FF, video RAM $0800-$0FFF (a 64 x 32 tilemap of
8 x 8 tiles, 1024 of them: colour RAM bits 6-7 are code bits 8-9), 48 sprites at $1000 (code, attributes, x, y:
16 x 16, 512 of them, x 9 bits), work RAM to $1FFF, scroll RAM $2000-$203F (a row scroll a tile row, bit 8 in the second
half), ROM $8000-$FFFF.  The picture is 240 x 224 (bitmap columns 8-247, lines 16-239); colours are a 32-entry palette
PROM (4-4-4 bits) through two lookup PROMs.  A sprite pixel whose lookup entry is 0 is transparent.

The game reads the VLM5030's BSY pin at $6000 in the NMI handler and waits for the end of a phrase before it goes
on: the reference models the chip's BSY exactly as `vlm5030.cpp` does (ST rising raises it; ST falling starts the
phrase at the table entry the data latch names; the phrase's frames are walked as the chip does, six bytes a frame,
silent frames and the end mark by their command byte; BSY falls on the sample grid clock / 440).  Without it the
game's speech state never ends and the frame sequence of MAME is not reproduced.

`ref/mame_cmp_jailbrek.py` (MAME 0.248's `wolfmame-0248` from F030Arcade; the 0.286 source is the truth): **0 of 512
pens and 0 pixels differ** at frames 60, 300, 600, 1200, 1500, 1548, 2000, 3000, 4000, 6000 (the renderer draws MAME's
own memory).  The reference machine's RAM equals MAME's at frames 100 and 200 exactly and to frame 1548 but for the
stack bytes below the stack pointer and the NMI handler's scratch ($1706-$1721, $16C0-$16C5), then drifts by about one
arcade frame (the sprites move 1-3 pixels differently at 1550; its picture is equal to MAME's again at 4000 and
6000): the Lua `frame_done` callback does not fall exactly at line 240, where the interrupts come, so MAME's dump is
taken at an interrupt phase the model does not know (a test of the dump point 0-1500 cycles after line 240 made
it no better), and an IRQ at that moment is seen as taken or not.  The picture check does not depend on it.

### Translation

`tools/gen.py`: the 64 KB are one block (`jb_mem`), every slot's VB is the same address.  Coverage (`ref/cover.py`, 12
seeds of 20,000 frames: about 5,100 pcs) decides which accesses go through the runtime: the video chip's control
registers ($2040-$2047), the inputs and sound ports ($3000-$6000), stores to the colour and video RAM (listed as dirty
cells for the renderer; byte stores inline).  The direct page is $15 (set once, at the start of the RAM test; the work
RAM, the queue and the stack share the first slot).  A read-modify-write of the video RAM (`dec $0830` at $907B, a
timer on the screen) cannot go through the runtime (`m6809x` has no such form): `gen.py` runs it on the memory and
lists its cell afterwards (`RMW_VIDEO`).  No engine file was changed.

### Schedule

The foreground is the Konami task loop of Track & Field and Hyper Sports ($8073 `ldx <$3C; ldd ,x; asla; bcs`, the
queue's read pointer at $153C).  The NMI handler ($B05D) steps three random generators ($16C0-$16C5) and polls BSY;
the IRQ handler ($8A57) plays the game and queues tasks.  The idle point is a native (`jb_idle`): with an empty queue
it draws the picture when due, waits for the next arcade frame, then delivers one interrupt per idle visit: seven NMIs,
an NMI and the IRQ (the arcade's order at line 240), each with $8073 as the return address; the speech chip's BSY
count (in NMIs: 16.27 speech samples each) goes down after each NMI handler.  60 arcade frames to 50 VBLs as in the
other Konami ports.

### Picture

`src/render.s` is Hyper Sports': a 64 x 32 tilemap in a 768-pixel-wide playfield of STE planes, a tile cache, three
display buffers whose rows are copied at their scroll (+ 8: the picture starts at bitmap column 8; 15 words a line),
a sprite cache baked on first use, generated code per (transparency class, code, flips) shape (544 shapes of the
coverage, 100% of the draws: 7,457 routines, 477 k lines, 682 KB of end-mask streams), Blitter HOP 2 / OP 3 passes with
the opaque pixels as end masks (no AND + OR pairs), rows grouped by mask, clipped at the picture's group-aligned edges
(screen x 48 and 288).  Jail Break differs in the geometry (240 pixels, left edge at group 3: bands of 48 and 32
pixels), the 9-bit sprite x, the first-to-last order (the last on top), 512 sprite codes, no tile flips.

### Sound

Not done.  The SN76489A ($3100 writes) and the VLM5030 ($4000 pins, $5000 data) writes are in the reference's
`sound_log`; Track & Field's and Hyper Sports' `sndgen.py` / `sound.s` (the sound CPU translated, tones on the YM,
speech offline on the DMA) are the model, but their sound CPU is a Z80 board and this game's chips sit on the main
CPU's bus: the speech would be recorded offline per phrase (the table at the start of `507l01.8c`), the SN76489A
mapped on the YM directly from the writes.

## Speed

Hatari, 3,001 VBLs of the AUTOPLAY build (a coin, start, then walking and firing): 2,353 arcade frames (39.2 a second
over everything, the boot's RAM test and the attract mode included), 832 pictures; in play (RATE.BIN, the last 400
VBLs) about 50 arcade frames and 12 pictures a second.  Musashi (`tools/render_test.py 1600 --seed 3 --start 1000`,
600 pictures): the logic ~108,000 cycles an arcade frame, a picture 80,000 CPU cycles + 85,000 Blitter bus cycles
(`--prof`: `draw_rows` 38%, `draw_cell` 23%, `draw_sprites` 12%, `bake_sprite` 6%, `tile_draw` 5%).

* What is not tuned yet (`docs/speed.md`, "Where a picture's time goes"): the picture's biggest cost is the row
  recomposition (`draw_rows`: every row whose scroll changed is copied again, 8 lines x 4 planes x 15 words; the
  street scrolls row by row), then the sprite draws.  Candidates to propose to the user, gameplay kept: the NMI
  handler's random generators (three calls an NMI, eight NMIs a frame) as natives, the idle loop, rows whose scroll
  moves by whole 16-pixel groups as plain copies.  Not measured.
* The generated sprite code against the row path (`-D REN_GEN=0`, `render_test.py 1600 --seed 3 --start 1000`, 600
  pictures, Musashi, exact both): 91.6k CPU + 86.5k Blitter bus cycles -> 79.7k + 84.7k (kept).
* The code for all of the coverage's 544 shapes: 7,457 routines, 477 k lines; the order table is computed where a
  sprite is baked (`bake_sprite`).

## Tests and tools

`ref/cover.py` (coverage and pens), `ref/mame_cmp_jailbrek.py` (reference against MAME), `tools/prepare.py`,
`tools/gen.py`, `tools/assets.py` (palette fit and the speech chip's BSY table), `tools/build.py` (`--sim`, `--debug`,
`-D AUTOPLAY=1`), `tools/logic_test.py`, `tools/render_test.py`, `tools/sprite_test.py`, `tools/hatari.ps1`.
`python port.py test jailbrek` runs them.

## Lessons

* **A chip's busy pin is game state** (2026-11-07): the NMI handler polls the VLM5030's BSY at $6000 and clears a
  flag ($170D) when it falls; with BSY always 0 the reference left the RAM and the picture of MAME at the first speech
  (frame ~800).  Modelling it as `vlm5030.cpp` does put the speech sequences right; the port counts it in NMIs, with a
  table per bit-rate step and speed (the parameter latch's bits 0-1 and 3-5 both change a phrase's length: 17 =
  4800 bps halves it).
* **`screen().height()` is the total height** (264), not the visible one: the video chip's timer wraps after line 256.
  Its NMI is edge-triggered; the game clears and re-enables the line in the handler.
* **The reference's `frame_done` is not the interrupt**: see How it works; do not chase RAM equality at line 240 when
  two interrupts are due there.
* **A read-modify-write of a video RAM byte** (`dec $0830`) is outside `m6809x`: handled in `gen.py`.
* **The MAME snapshot is 240 x 224** (visible area x 8-247): the reference's `render_rgb` returns that.

## Verification

Playtest evidence: the Musashi tests above; the hidden Hatari run (`tools/hatari.ps1`: `tools/hatari.ps1`: coin, start and play to a score of 400 and beyond, in 3,001 VBLs, no crash, no late border event; the
stills are in `run/jailbrek_hatari/` (not in git)).  The full-game
status stays **Incomplete** (no sound, no playthrough); see the [status policy](../../docs/port-status.md).
