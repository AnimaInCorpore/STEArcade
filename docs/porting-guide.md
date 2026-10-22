# Porting guide

How a game goes from a ROM set to a running STE port, with lessons from the ports. The architecture
is in `architecture.md`; `port.py` runs the registered ports (`port.py cover|build|test|run|mame <game>`).
Work in progress outside `port.py list` uses its own scripts under `games/<game>/tools/` and `ref/`.

## Steps

1. **Read the MAME driver** (`F030Arcade/third_party/jsm68kdisassembler/third_party/mame`, see PORTING there; the
   installed `mame` binary is newer than that source, so it is the truth for colours): memory map, interrupts,
   video RAM layout, sprite format, palette PROMs, helper chips.  Chips with their own program (Bubble Bobble's
   MC6801, Galaga's 51xx/54xx) are either run (translated, preferred when the ROM is in the set: "run the device,
   don't replay its answers") or simulated at the register interface.
2. **Reference machine** (`games/<game>/tools/machine.py`): CPUs, memory map, interrupts, renderer (`render_raw`).
   Keep a `run_frame_port` that follows the runtime's schedule.  Boot self-tests are skipped with patches
   (`skip_tests`) that keep any running checksum intact.
3. **Check the reference against MAME** before building graphics (next section).
4. **Coverage** (`ref/cover*.py`, random input, several seeds; `port.py cover <game>`): the program counters seen executing,
   the I/O and banked-window sites.  Discovery adds jump tables (`rst $28` tables, `ld hl,T ... jp (hl)`) and
   what static recursive descent finds; anything coverage found but discovery missed is a hook or a table.
5. **Translate** (`tools/gen.py` of the game, config in `engine/z80x.py`, pipeline `translate.compile_code`): memory
   model, register map (`z80x.FAST`, see below), hooks for I/O writes and yields, window/bank handling for banked ROMs.  `port.py test <game>`: lock-step against the reference (RAM every frame).
6. **Runtime** (`src/<game>.s`): loader, dispatch tables, VBL schedule, input (the IKBD handler around `ikbd_byte`
   of `engine/rt/ikbd.s` and key_table, the pads through `engine/rt/jagpad.s`: the `JP1_*` ... `JP_COIN2` bits, `jagpad_poll` and `jp_merge` in the VBL), border
   removal, hooks.  A new port gets a line in `port.py`'s `GAMES` (and its tables), `tools/release.py`'s list and the
   README's tables; its folder follows the README's "Layout" (ROMs: `tools/prepare.py` + `docs/rom_manifest.json`).
7. **Renderer**: exact against the reference bitmap through the colour table first (`render_test.py` style:
   copy the reference RAM in, call `render_frame`, compare pixels), fast second.
8. **Hatari** (`tools/hatari.sh`, F030Arcade build): look at the screen, then compare frame counters/skips from the `--debug` build.
   Looking found most bugs that the tests did not (wrong colours, missing sprites, bus errors on odd accesses).

## Lessons

* **Musashi is not a 68000 for faults and timing**: it executes odd word accesses silently (Hatari takes an address
  error) and has no MFP timers or border removal.  Test for odd accesses (`games/bublbobl/tools/align_test.py`) and
  build the simulator variant with `-DSIM`.  Crashes that appear only in Hatari have been: stack overflow by nested
  VBLs, window-read sites coverage missed, odd word loads in translated MCU code.
* **Guard only the coverage's window sites, and audit the rest** (Bubble Bobble, Black Tiger 2026-10-11): a check at every
  indirect access costs a quarter of the translated cycles.  Record the sites in the coverage runs (reads of the window and
  the banked RAM, writes of the latter), keep them in the repository (`docs/window-sites.json`) so a build needs no
  coverage files, and trace a simulator run for accesses to the unused image of the window (`logic_test.py --audit`): any
  such access is a site the coverage missed.  Black Tiger's play logic: 80.7k -> 65.3k cycles a tick; 1943's (whose
  gen had the site policy since 2026-10-09; now `docs/window-sites.json`, `W_GUARD_ALL=1`, `logic_test.py --audit`)
  69.8k with every access guarded -> 61.0k; 1942's 26.6k -> 23.8k a frame and Bubble Bobble's main CPU 67.7k -> 62.4k
  (both had the sites since their ports; now the sites file, `W_GUARD_ALL`, and 1942's `logic_test.py --audit`);
  Gun.Smoke's 40.5k -> 37.3k a frame (229 of 1479 sites).  Commando's ROM is flat: no window, nothing to guard.
* **Coverage must reach every phase of the game, not only the attract mode and the play**: Galaga 0.2 stopped at the
  high-score name entry (a score above 20000), whose two jump tables no coverage run had reached (see
  `games/galaga/README.md`).  Seed the states a short run never gets to (a high score, a game over, the ending) by poking
  the arcade's RAM in `ref/cover.py`, and keep a crash dump (CRASH.TXT) that names the unknown pc.
* **Self-tests flood the renderer** (video RAM test) and run ~700 frames: skip them in the reference and the
  translation, compensate any ROM checksum the game runs later, load the patched ROM files in the runtime.
* **Palette**: 16 STE colours against 22-26 on screen.  Keep the colours in order of appearance while they fit;
  otherwise the background, "volatile" entries (changed >= 4 times: flashing, they own a slot), and the heaviest by
  weight capped per bank.  Re-mapping must only rewrite the STE palette when the mapping is unchanged.
* **Memory budget (4 MB)**: text + data + BSS from the map must stay well below what GEMDOS leaves (see "Memory
  budget" below: at most 3,700,000 bytes, `tools/release.py` checks it).
* **Fixed palette, fitted per stage**: when the game's stages look different, fit the fixed colours to frames of
  every stage (cheats to reach them, as `games/blktiger/ref/palette_fit.py`), each set's histogram normalised;
  square-rooting the weights (Bubble Bobble) let a stage's sky lose its colour there.
* **Throttle the logic when it cannot keep up** so the renderer still runs; never let a pending VBL nest.
* **Reference renderers can be wrong in ways "port equals reference" cannot see** (plane order, palette weights,
  a sprite row off by one): the MAME check below is not optional.
* **Verify claims about other work by running it**: a summary that says a renderer is a stub may be stale.
* Script names in `ref/` and `tools/` must not shadow the standard library (`dis.py` broke `import inspect` inside numpy).
* Branch-out-of-range and `lea` displacement warnings in vasm are normal at this size; real errors stop the build.
* **A macro must not be named like a vasm directive** (Gyruss 2026-10-17): a macro called `LIST` expanded to nothing
  (vasm took the listing directive), silently; two of four natives were wrong until the listing (`vasm -L`) showed it.
* **Odd-sized BSS variables before word / long ones**: Musashi accepts the odd access, Hatari takes an address error
  (Gyruss's `snd_ym_new` after a 5-byte array).  Pad the arrays; look at the map for odd addresses of word data.
* **Sprite multiplexers that race the beam** (Gyruss): a CPU that reads the beam's line and reuses the sprite entries
  the beam has passed shows more sprites than the hardware has; MAME's partial updates draw each entry's old content
  above the write's line and the new one below.  A translation cannot follow the beam: give the reads a model fitted
  to the MAME-timed reference (Gyruss: line = 25 + 0.6 x the reads of the IRQ), render the reference per band of lines
  with it, and on the STE log each reused entry's old content and line and draw every content clipped to its band.
* **6809 translations** (engine/m6809x.py, 2026-10-17): `Program.opcode_reader` decodes encrypted opcodes (KONAMI-1:
  `lambda rd: konami1_opcode(rd)`); an indirect operand through a static pointer address (`[$4211]`) reads the
  pointer from the slot of its top bits (no run-time slot lookup: the same result in every port), and
  `Program.indirect_slots` names the target's slot where the coverage saw one besides the pointer's; a flat program
  (no MMU) maps each slot to its memory in the context (Gyruss: slot 3 is the main CPU's shared RAM in the Z80 block).
* **Z80 translations**: z80x computes H after `inc` / `dec` where it is read (a `daa` after `inc a`: Gyruss's frame
  counter); `inline_leaves` and an emitter's `x_rst` override put the short `rst` I/O helpers of a sound driver in
  place (Gyruss's sound: 57k -> 52k cycles a frame).
* **MAME's debugger for exact traces of a small CPU** (Gyruss's i8039, `games/gyruss/tools/i8039.py --mame`): a
  breakpoint action's `printf` reads the registers of the debugger's current CPU, not of the one that hit the
  breakpoint (stop once on that CPU first); a command reaching a CPU through a latch with a delayed write needs its
  interrupt a frame after the latch when the test drives both.

## Checking a reference against MAME (applies to every port)

"The port equals the reference renderer" only means something if the reference equals the arcade.
Compare the reference with MAME's own screenshot, pixel by pixel, before trusting it.  Donkey Kong's
reference had two errors that this found on 2026-10-08, neither visible in a Hatari-vs-reference test:

* **Sprites were one raw row off**: `top = 246 - y`, MAME's `draw_sprites` gives `247 - y` (its
  line buffer fetches the sprite one scanline ahead, hence the `+ 1` in `y + add_y + 1 + scanline`).
  Fixed in `games/dkong/tools/machine.py` and `games/dkong/src/sprites.s` (`u0 = y - 23`).  Every sprite was one pixel shifted
  along the arcade's raw Y axis.  Positions derived from the MAME source need a snapshot to confirm
  them (here the derivation and the snapshot agree: 0 pixels differ with 247, about 900 with 246).
* **The palette was wrong** (up to 75 levels per channel, e.g. skin 255,184,85 vs 245,188,160, blue
  0,0,170 vs 4,2,220): the Galaxian style weights 0x21/0x47/0x97 and 0x55/0xAA are not what current
  MAME computes.  Its colours come from resistor network models (`compute_res_net`: darlington stages,
  tri-state black) and are not a per channel sum of weighted PROM bits, so take the numbers from MAME
  itself: `games/dkong/tools/dkong_pens.py` is a dump of `pen_color()` for the 256 pens.  Do the same for any
  game whose reference computes colours from PROM weights; Galaga and Bubble Bobble should be checked.

How (`engine/mame_dump.lua`, `games/dkong/ref/mame_cmp_dkong.py`; MAME is `/opt/homebrew/bin/mame`, 0.289, the ROM zips
are in `assets/roms`): start MAME with **`-window`** (with `-video none` there is no snapshot), run a Lua
script at frame N that writes the pens (`palette:pen_color(i)`), a memory range and `video:snapshot()`, render
the same memory with the reference and count differing pixels.  `venv/bin/python games/dkong/ref/mame_cmp_dkong.py 700 1500 2500 4000`
prints 0 differing pixels for all four frames now.  Notes:

* Take several frames: the memory is read after the frame was drawn, so a fast sprite can be one step ahead.
* Write taps on the I/O latches (`install_write_tap`) did not report the palette bank reliably (it read 0 where the
  screen was bank 2), so the compare tool tries all palette/sprite banks and reports the best.  A bank mismatch
  shows as whole tile colour sets wrong, a position mismatch as a one pixel outline around every sprite.
* Checked and fine for Donkey Kong: tile colour codes, video RAM layout, sprite x (`x + $F8`), flip x/y, the
  8257 sprite DMA (the game programs `$6900` -> `$7000`, `$180` bytes, exactly what `z80_dma` copies).
* **No key press**: MAME shows its startup screens (game info, "ROMs not correct" warning) and waits for a key
  unless `-seconds_to_run` is below 300 (`ui.cpp`: the startup screens are off for `-str` < 300).  The scripts use
  `-seconds_to_run 250` (about 15000 frames with `-nothrottle`, enough for every check here).  The warning itself
  stays in the log; Galaga's came from blank MCU ROMs before its real ones were in (2026-10-21), Bubble Bobble's
  from the PAL dumps nobody has.
* **The MAME source in `F030Arcade/third_party/mame` is older than the binary** (Galaga's blue channel differs:
  the source says 0x47/0x97, MAME 0.289 produces 0x51/0xAE).  The installed `mame` is the truth.
* **Several frames in one run, write logs with the beam line** (`engine/mame_frames.lua` + `engine/mame_cmp.py`, used
  by Track & Field, Hyper Sports, Gyruss, 2026-10-12): dumps of any CPU's ranges, snapshots and pens at a list of
  frames, and a log of the writes to TAPS ranges.  Two MAME 0.289 Lua traps found on the way: a write tap installed
  while the autoboot script loads is silently lost (install it at the first `frame_done`), and the screen has no
  `vpos()`/`hpos()` in Lua (an error inside a tap callback is swallowed: the log just stays empty); the line is
  `(-screen:time_until_pos(0, 0) / screen.scan_period) % vtotal`.  Run MAME in a fresh directory per capture: it
  writes `nvram/` there and reads it back next time (high scores, NVRAM games boot differently).
* **Partial updates**: a driver whose RAM write handler calls `screen.update_partial(vpos)` (Gyruss's sprite RAM: the
  sub CPU writes sprites until line ~36) draws the lines up to the write's line with the old values.  A reference
  render of one end-of-frame memory dump then differs in a few pixels; render per band of lines from the previous
  frame's dump plus the logged writes (`games/gyruss/tools/machine.py: sprite_bands`).  The same driver marks the
  whole tilemap dirty only at the first band, so tile RAM is effectively sampled once per frame.
* **Encrypted opcodes** (Konami's KONAMI-1: Track & Field, Hyper Sports, Gyruss's sub CPU, and Circus Charlie, Juno
  First, Megazone, Jail Break, Finalizer, Roc'n Rope): `M6809(rd, wr, rd_op=konami1_opcode(rd, boundary))` and
  `m6809dis.decode(..., rd_op=...)`; only the opcode bytes (the first byte and the byte after $10/$11) go through
  `rd_op`, operands do not.  A translator reading code bytes must do the same (`engine/konami1_test.py`).
* **Irem M72** (R-Type, Mr. HELI; `engine/m72.py`, `engine/m72_mame.py`, 2026-10-12): 0 differing pixels and pens in
  every captured frame of both games.  The scroll, raster-line and sprite-DMA registers are V30 *I/O ports*: TAPS take
  `tag:space:start:end` (`maincpu:io:0x80:0x87`; a 16-bit bus's write is logged byte by byte, the tap range must
  cover whole bus words), `f<frame>_tapstate.txt` holds the registers' values before the logged writes, and DUMPS of
  20-bit ranges go to `f<frame>_<tag>_<space>_<start>.bin` (`load_dump` grows the image).  The sprite chip draws a
  buffer the program fills by a write to port $04 (MAME's buffered sprite RAM, in no address space): SNAPS
  `maincpu:io:0x04=maincpu:0xc0000:0xc03ff` copies the sprite RAM at that write.  MAME draws the lines up to the raster
  interrupt's line (port $06 - 128) when it fires and the rest at the frame's end, so render per band from the
  previous frame's dump plus the logged writes (video RAM writes do occur mid-frame); the palette is not banded (pens
  are looked up at the end).  R-Type: DMA and scroll in the VBLANK handler, the status bar is a raster split at line
  239 (FG scroll y $90, x 0: map rows 0-1).  Mr. HELI: a top panel split at line 31 and, in the cave, a second split
  where the handler re-programs the raster line.  Pens never written keep MAME's default pattern (pen bits 0/1/2 ->
  full red/green/blue), not black: 448 pens "differ" during R-Type's boot; compare after the game wrote the palette.

* **The M72 board's logic** (`engine/m72board.py`, 2026-10-13; R-Type and Mr. HELI equal to MAME in all RAM and in
  the picture through frame 4000, `games/<game>/ref/logic_<game>.py`): what it took beyond exact cores (`v30.py`,
  `i8051.py`, `z80mame.py`, each checked against MAME traces).  `abort_timeslice` takes the rest of icount as *stolen*
  cycles (a core that counts `start - icount` must give them back); suspended CPUs (a CPU held in reset) go to the
  end of the execute list but still eat cycles and can lower a round's target; the sound manager's 50 Hz update is a
  timer that cuts slices even with `-sound none`; `machine().time()` inside a timer callback is the timer's expiry,
  not the base time; ymfm's sample count at a register write is floor(t * rate) + 1 (the stream is brought up to
  the sample containing t), which sets timer B's start (-(count & 15)).  The V30's REP string instructions run in
  slice-sized chunks, so any of these shows up as a few cycles of drift in the main CPU.

#### Frames from an old MAME without Lua snapshots (F030Arcade `wolfmame-0162`, Windows)

`F030Arcade/third_party/wolfmame-0162/mame.exe` knows Bubble Bobble (`bublbobl` Japan Ver 0.1, `bublboblr` US Ver 5.1;
`-rompath assets/roms -verifyroms bublboblr` passes with the zips as shipped); the sibling `wolfmame-0184` build does
not.  Its Lua is the old API, so `engine/mame_dump.lua` and the `mame_cmp_*` scripts (written for 0.289) do not run on it:
the only per-frame hook is `emu.sethook(fn, "frame")`, `screen:frame_number()` and `manager:machine():exit()` exist,
`register_frame*` and `video:snapshot()` do not.  What works is MAME's own recording:

* `-aviwrite name.avi` writes **uncompressed RGB24 at the native size** (Bubble Bobble 256 x 224; the container says
  60 fps whatever the board runs at), so the pixels are exactly what MAME draws.  The file lands in MAME's `snap/`.
* The AVI writer is 32-bit: record ~300 s segments (3.1 GB each for 256 x 224) and chain them with `-autosave`;
  `-seconds_to_run` is the **cumulative** emulated time, so segment k uses `(k+1) * 300`.  `-sound none -nothrottle
  -frameskip 0 -skip_gameinfo -window`; about 25 s of wall clock per segment.
* Read the frames with `ffmpeg -i x.avi -an -f rawvideo -pix_fmt rgb24 -` (`-fps_mode passthrough`; newer ffmpeg
  has no `-vsync`), counting colours per frame as packed RGB: that is exact, no sampling.
* Run MAME from a scratch directory (it writes `cfg/`, `nvram/`, `snap/`, `sta/`), and **check the recording for stray
  input**: a key reaching the window registered a coin 27 s into the fifth segment of the Bubble Bobble run (the screens
  then read `CREDIT 1` / `PUSH ONLY 1 PLAYER BUTTON`); frames from there on were dropped.
* Example, `games/bublbobl/ref/mame_attract_collage.py`: 20 minutes of attract mode, 68 distinct colours, a 64 frame
  collage that contains every one of them.  The attract loop does not repeat exactly (the demo levels change per loop),
  so "all colours" means all colours seen, with the last new one at 12.3 minutes.

Colour budget for a 16 colour target: take that colour count, then reduce with the JsOklabQuantizer strategy
(`C:\Arbeit\jsoklabquantizer`, shared palette in Oklab, lightness ladder + k-means on a/b;
`games/bublbobl/ref/quantize_collage.py`).  Look at the worst-mapped colours before accepting a palette: Bubble Bobble's
default result has no green (Bub's `#00bb00` maps to a teal).

Results, 2026-10-08 (all with 0 differing pixels now, `games/dkong/ref/mame_cmp_dkong.py`, `games/galaga/ref/mame_cmp_galaga.py`,
`games/bublbobl/ref/mame_cmp_bublbobl.py`):

* **Donkey Kong**: sprite position and palette, see above.
* **Galaga** (found by the check): (1) `decode_gfx` made the first plane the *least* significant bit, MAME the
  most significant one: pixel values 1 and 2 of every character and sprite were swapped (the enemies were orange
  instead of teal, the ship blue instead of red, the NAMCO logo white instead of red); text only looked right because
  most character colour tables are symmetric in pens 1 and 2.  (2) Blue was 0x47/0x97 (maximum 222), MAME 0x51/0xAE
  (maximum 255; the star palette's blue likewise 0, 0x51, 0xAE, 0xFF).  Both are in `games/galaga/tools/machine.py`, so
  `games/galaga/tools/assets.py` (the STE graphics and palette) picks them up on the next `python port.py build galaga`.  The
  starfield is not verified (MAME's starfield was off in the frozen frames).  MAME can not run Galaga from the ROM set:
  the Namco 51xx/54xx MCU ROMs are missing, a blank 1 KB stand-in (`namco51.zip`, `namco54.zip`, wrong checksum,
  MAME warns and runs) ends in the test screen, so `engine/mame_dump.lua` with `INJECT=` writes the reference's RAM
  image into MAME's RAM and freezes it with write taps (MAME's Lua has no CPU halt; `set_input_line` is not exposed),
  and MAME draws it: that tests the renderer, not the game.
* **Bubble Bobble**: nothing to fix.  Palette (RGBx444, `v * 17`), tile decode, object/column layout, flip and the
  background pen 255 match MAME at frames 700, 1500 and 2500 (about 77 objects each).  MAME runs the set itself.

Lesson for new ports: do this check *before* building the port's graphics, and re-check whenever the reference
renderer changes.  A plane order or a colour weight that is wrong in the reference is wrong in the port, and
"port equals reference" tests can not see it.

* Known MAME behaviours the port does not have: the 16 sprites per scanline limit (later sprites of a line vanish)
  and the wrap around of sprites at the arcade's 256 pixel edge (MAME draws them again at x - 256 / y - 256).  Neither
  is visible in normal play.

## Recorded arcade games as an acceptance test (MARP; Black Tiger, 2026-10-22)

The MAME Action Replay Page (http://replay.marpirc.net/, plain HTTP) keeps
whole expert games recorded in WolfMAME. Played back in the WolfMAME version
that recorded it (Windows builds: github.com/mahlemiut/wolfmame/releases), a
recording is the board's own game, and a frame dump of it is ground truth.
F030Arcade replays such a game on its Falcon Black Tiger port, which uses
this repository's translation, frame for frame: 67 minutes, 2,006,700
points, equal at every check to game over. The workflow and tools are in
F030Arcade's `docs/marp-replay.md` (`scripts/mame_inp_dump.py` dumps any set's
ports and RAM per frame). Use it for any port whose exact set has a
recording: it found what coverage, PPO and reference tests had not.

What it found in this repository's Black Tiger translation:

- **`docs/window-sites.json` misses block copies.** Bank 0's `ldir` at `$AC71`
  copies the 32-byte object template at `$AF06` from the banked window. It is
  not a window site, so the translation reads the image and makes the object
  from zeros. Guard every block copy: the guard tests HL at run time.
- **Object-script handlers are missing as roots.** Scripts are 5-byte records;
  `00 lo hi` jumps to a handler in the script's bank. Scripts reached only
  through data tables are not followed by `gen.generate`'s `script()`
  discovery. F030Arcade added about 50 roots, in its
  `games/blktiger/docs/main-roots-extra.json`: 40 from scans for a handler
  record after a goto, between timed records, or before an end marker (target
  bytes like the known handlers), and 9 from replay stops.
- **Task starts are missing as roots.** The task kernel starts a task with
  `ld a,n / ld bc,entry / call $00F6`. BC is not followed as code, so the
  high-score name entry (`$51DE`, `$5276`) and three more entries (`$275D`,
  `$2778`, bank 6 `$A9E8`) were untranslated. Scan for `01 lo hi cd f6 00`:
  29 sites in the ROM.
- **The score is at `$E1E8`** (8 unpacked digits, shown with a trailing 0;
  `$E1E0` is the high score).
- **A frame-exact replay needs the Z80's time.** Delivering the frame
  interrupt only when the task kernel idles runs each frame's work in zero
  time. The boot's five overrun frames then leave the random generator
  `$E008` five frames ahead, and the game changes at the start press. A cycle
  budget charged per translated block (MAME's `z80.cpp` tables), with the
  interrupt taken mid-task through the game's own handler, fixes it (F030Arcade
  `games/blktiger/scripts/cycle_budget.py`, an `Emitter` subclass; its
  PORTING.md, "Original CPU time and recorded games").

## What the 1942 port added (2026-10-08)

* **A game whose foreground is the game.**  1942's Z80 runs a cooperative kernel (tasks, a scheduler with an idle loop, two interrupts); the
  arcade's interrupts come at arbitrary points of the tasks.  The runtime does not interrupt the translated code: the VBL only raises a flag
  and the idle hook of the scheduler (`$009A`, reached when no task is ready) delivers the interrupts and draws.  The Python reference has the
  same schedule (`run_frame_port`), so the lock-step compares RAM at the end of every frame.  An interrupt handler that hands the CPU to
  another task never returns to the token on the Z80 stack: the hook resets the 68000 stack before it starts a handler.
* **The task contexts on the Z80 stack are data too.**  The kernel pushes registers and flags of sleeping tasks on their stacks, so the RAM
  compare also sees stale flag bytes.  Making the translation equal needed: flags exact at `jp (hl)` and at hooks, `bit` setting S as the CPU
  does, and no scratch use of registers that tasks save (`a0-a3` are the alternate registers, `d4` is IX).
* **P/V flag**: `jp pe/po` after logic ops is parity (d6 bit 7), tracked by the translator's flag liveness; any other producer whose P/V is
  read makes the translation stop with an `unsupported` entry (it never guesses).
* **Jump tables behind a call** (`call T` with the words following it, T pops the return address) are found statically
  (`discover.py table_calls`); anything the coverage does not see stops the lock-step at `z80_badpc` and names the pc.
* **Coverage misses table entries**: Capcom's `ld hl,T; add hl,de; ld e,(hl); inc hl; ld d,(hl); ex de,hl; jp (hl)`
  tables have entries that no coverage run reaches (1943's object types 10-14 at `59BC`: a player's random play hit
  `5AE2` after 6 minutes).  `discover.py hl_tables` finds the form, but in a banked program it also reads data and the
  window's tables as tables; 1943 names its fixed tables (`gen.py JUMP_TABLES`).  Check every translated `jp (hl)`:
  its table's entries (or, behind a byte table of offsets as in Gun.Smoke, the entries those offsets select) must all
  be translated.  A random-input run in Hatari (keys through `--cmd-fifo`, a few minutes) finds what the coverage seeds
  did not.
* **Functions that return past the call** (`pop hl`, k x `inc hl`, `jp (hl)`, also across a `jr`): Capcom's
  allocators and the 8 / 4-byte compares (1943 `03C0`, Black Tiger `03B2`, Gun.Smoke `0365`: the caller has a `jr` /
  `jp` for less, equal, greater) continue at call + 3 + k.  `discover.skip_returns` finds those continuations; a port
  adds them as roots and discovers again until none is missing (1943, Black Tiger and Gun.Smoke do).  Before, only
  1943 had it, and only without the `jr`: 31 continuations of the compares were untranslated.
* **Coverage that dies**: random play with invincibility (1943 seeds 6-20) never runs what dying runs; seeds 21-40
  (play that dies, every start stage, faster input changes) found 1038 more bank/pc pairs, among them both targets the
  Hatari runs had crashed on.
* **Dirty flags by coverage**: the renderer only diffs the video RAM after a store to it; the sites are coverage results, the lock-step test checks
  that every change had its flag, and the renderer rescans now and then.
* **Test windows that wrap.**  The first renderer test passed for 1000+ frames and the wrapped half of the scroll ring was never drawn: a window
  position (T > 256) that the sampled frames had not covered hid a garbage upper register word.  Sweep the whole range of a scroll register.
* **Hatari**: a Blitter pass that hogs the bus delays the VBL and the border timers by more than half a scanline, the screen then flickers between
  open and closed borders.  Keep every pass short (see "Only short HOG passes" below); look at Hatari's own screenshot (RightAlt+G) of
  several frames, not one.  A 768 line, 56 word Blitter copy hung the emulation for good in one go (32 lines at a time are fine).
* **Generated sprite routines with streams** (`games/1942/tools/spritegen.py`, `FAST_BLITTER_SPRITES.md`).  Constants inside 8000 routines
  (one per sprite code and shift) took 995 KB, too much for the 4 MB machine next to the rings and caches; the routines are shared by row
  structure (772 of them, 93 KB) and the endmasks / skew of each shift are a stream read with `move (a0)+,(a2)`: same cycles, a third of
  the memory.  The routines add to the low word of the destination address, so parts at a 64 KB boundary of the ring need a second path
  (it reads the same streams: no masks are computed at runtime).  A routine must not use `d4-d7` / `a2-a6` for anything else: the
  decoding of the sprite list once used `d4` and drew garbage that only showed with several entries - test with the whole list, not only
  with single parts.  The simulator's Blitter must write the advanced addresses back for read-modify-write code (`Sim(ram_kib=16384)`).

* **Speed work on 1942 (2026-10-08)**, things that apply to the other ports too:
  * *Hatari scans the old ring out once more.*  After the video base is written at the VBL, the frame that starts still shows the ring that
    was shown before; a renderer that draws into the ring it just flipped away from tears the lower half of the picture.  Draw into a ring
    that was neither shown nor waiting during the last frame (three rings are enough at 50 frames a second).  Look for it with a recording
    (`tools/record.sh`, ffmpeg, one frame at a time), a ruler in the margin proved that the lines themselves were not skipped.
  * *Publish a finished frame with one store.*  The VBL runs between any two instructions: a ring index and a ready flag written one after
    the other can be seen half done (a ring that is shown and ready at once gave a draw ring 3 and a crash far away: records written past
    their array).  One byte = ring + 1.
  * *Decouple the ticks from the frames.*  The arcade ticks at 59.6 Hz, the STE shows 50: six ticks to five VBLs, and skip frames, not
    ticks, when the CPU is short.  The game then runs at the arcade's speed where the old schedule ran at the speed of the slowest frame.
  * *The cheats of MAME (`third_party/mamecheats/cheat.7z`, the xml of the set) reach the later stages*: lives, invincibility and a level
    skip.  Coverage and the lock-step test need them (the first coverage stopped the program at the first stage change), the RAM
    addresses are in the xml.
  * *Cycle counts of the simulator and Hatari differ by a factor (1.35 here)*: use the simulator to rank the routines and Hatari
    (`bench.sh`: counters of ticks and frames from a scripted run) to decide.

* **Scrolling with virtual screens (Commando, 2026-10-08)**, after stedaimakaimura (`~/Work/stedaimakaimura/emulator.s`); the
  numbers are in `games/commando/README.md`:
  * *No per-frame background copy.*  Each display buffer is a virtual screen shown at the scroll position by the video address.  Every
    buffer line `l` and `l+H` hold the same background (twin lines), so the window (and the guard lines of whole sprites) is contiguous
    wherever it is, without the Timer B wrap of stedaimakaimura (the border removal uses Timer A and B).  Only the tile rows that scroll
    into the band and the tiles whose RAM changed are drawn, into every buffer.  Commando's frame went from 962k to 255k cycles.
  * *The twin period must exceed the band by the tile overhang.*  Whole tiles at the edges of the band reach up to 15 lines beyond it; with
    H equal to the band (288) they overwrite the twin slots of visible rows.  H = 320 for a 288 line band (256 shown + 2 x 16 guard).
  * *Put sprites back from the twin lines, not from a clean copy.*  A damage list (address, twin address, words, lines; split at line H)
    of what sprites and characters covered is restored with short HOG Blitter bursts the next time that buffer is drawn.  The twins are
    always clean: the damage of a frame lies in its band, whose twins are outside it.
  * *Find changed video RAM by comparing it with a copy as longs* (`cmpm.l (a2)+,(a3)+`, about 17k cycles for 2 KB), not with a loop
    per cell (Commando's per-cell loops over the tile and character RAM cost 330k and 210k cycles a frame).  Text: keep a list of the
    visible, non-blank characters, rebuilt only on a change, and draw byte-aligned 8 x 8 characters with `movep.l` (keep mask, four plane
    bytes: about 600 cycles each).
  * *Lose no cycles on a cache hit.*  A `movem` of 14 registers around a hashed cache lookup cost more than the lookup; look up first with
    two or three registers and save the rest only to bake.
  * *Tools*: a cycle profiler needs `Sim(ram_kib=16384)` as soon as code reads Blitter registers back (the sprite streams add to the
    destination address; with 4 MB the reads return 0 and the sprites land elsewhere, in Commando on the stack).  `tools/hatari.sh` stops
    every running `hatari` first, so two sessions benchmarking at once kill each other's runs: `games/commando/tools/bench.sh` starts its
    own Hatari (`HATARI` may name a renamed copy of the pinned build).

## Virtual-screen follow-up (2026-10-19)

F030Arcade-private's Black Tiger keeps a persistent ring and repairs pages from a clean image. Its useful
STE lesson is to avoid preparing duplicates before a window needs them. Black Tiger's STE renderer now
checks other physical instances on entry instead of eagerly drawing eight offscreen twins. Do not apply
this blindly to Commando-style twin-line restoration: those twins are the clean source for old damage.

Keep a copy/fill's dispatch cost out of its inner loop: known full-mask, unskewed transfers can call
`blit_go_copy`, HOP 0 fills (including masked fills) `blit_go_fill`. A copy with partial masks needs
destination reads even with OP 3; FXSR can also add a source fetch. Count both before choosing a HOG
piece. Tests: `python engine/borders_blit_test.py`, also `--copies-only --entry blit_go_copy` and
`--fills-only --entry blit_go_fill`. The test compares split output and final registers with an unsplit
operation across shifts, reverse increments and 64 KB boundaries and rejects passes over 256 cycles.

The M72 renderer shares the existing access-count table in its transfer fallback and rotates its 64-bit
contribution maps by rotating A and A xor B, then exchanging the wrapped bits. This avoids four long
variable shifts; `python engine/m72_bitmap_test.py` checks all 512 pixel offsets against a mathematical
rotation. Preserve sprite/background priority and validate whole consecutive pictures after such a change.

Results and rejected experiments: [virtual-scroll-performance.md](virtual-scroll-performance.md).

On Windows, sound recording uses bounded `spawn` workers (`CAPSND_WORKERS`, default 4) because `fork`
is unavailable and each spawned worker imports its own Python modules. `OPENBLAS_NUM_THREADS=1` is
useful when generating assets alongside other builds. Gun.Smoke binds its own sound module before its
graphics builder adds another game's tools to the module search path. The Gauntlet renderer harness
generates its fixed address map independently of the program patcher's coverage. Shorter coverage runs
must not discard previously established ROM-window guards (1942 and 1943); native continuation targets
are explicit discovery roots even when a play seed does not take them (Double Dragon).

Double Dragon's sprite test still defaults to its canonical recorded play. `--seed 1` supplies an explicit
reference scenario when that private recording is absent; it supplements, and does not replace, replay
or full-game coverage checks.

## The translator's register maps and second pass (all ports, 2026-10-08)

The translated code got 1.08-1.73 times faster (`architecture.md`, "Translator").  What a port has to do to get it, and
the rules its runtime must keep:

* **gen.py**: go through `translate.compile_code()` (or `generate_program()`), not a copy of the steps: it does the flag
  liveness over calls, the CCR analysis and the second pass.  Pass the real entries as joins (reset, interrupts, hooks,
  jump table targets); making every pc the coverage saw a join (Commando did) switches the CCR analysis, the precise
  returns and the merges off.  A port with a banked window wraps its `aW` lines with `Emitter.window_wrap` and gives
  `ret_value` (the real address a call pushes) and `direct_ok` (no return points in the window) like Bubble Bobble.  Give the configs `**z80x.FAST` (signed memory model) or
  `**z80x.FAST_LONG` (long model); `alt_af="upper"` alone where the runtime uses a0-a3 (1942).  Table generators
  leave out `em.no_entry` (z80_badpc there); a generator that lists every pc still assembles (the merged labels have stubs).
* **Runtime, d0 and d6**: A' is in bits 16-23 of d0, F' in the upper word of d6.  Code that runs inside the translated
  context (hooks, `bsr` targets of write hooks, native replacements like 1942's `scan_native`) writes them as bytes /
  words only: `clr.w d6`, not `moveq #0,d6`.  Interrupt handlers that save registers with `movem.l` are fine.
* **Runtime, d1-d3 with FAST**: the upper words hold BC' DE' HL'.  A runtime that reads an alternate register reads the
  upper word (Galaga's `g_ctrl06`: DE' is `move.l d2,d7; swap d7`, it was `move.w a1,d7`).  IY is in a2 (its low word).
* **a0-a2 with FAST** are the translated code's scratch registers (`ldir` uses two of them); a runtime routine called
  from translated code may use them too, but must not expect them to keep anything between instructions.
* **The Z80 stack below SP is dead**: merged `push rr; pop rr'` does not write the word.  A lock-step test compares the
  stack above SP only (Donkey Kong's `logic_test.py` already did).
* **An interrupt's `push af` saves d6**, which need not hold the interrupted code's flags at that moment (they may be in
  the CCR; the 68000's own interrupt restores them).  The pushed byte is not state: compare it in a test only where the
  translation makes the flags exact (1942: hooks, `jp (hl)`).
* **`halt` goes on with the next instruction** (it waits for an interrupt).  Discovery used to end a flow there and the
  emitter put no jump behind it, so the code after a `halt` was translated only if a coverage run had reached it, and
  otherwise the translation fell into whatever was translated next: Galaga restarted at the end of every game, and
  Bubble Bobble's `11E6`, Commando's `2F4D` and 1942's `7953` (data read as code) fell into the wrong code too.
  `z80dis` gives `halt` the flow `seq` now; `x_halt` keeps the CCR across the runtime's wait.
* **Unforeseen entries stop loudly**: a computed jump to a pc the analysis did not count as an entry (joins: entries,
  return points, jump table targets, code addresses held as numbers) now ends at `z80_badpc` with the pc in d7 when the
  pc is inside a merge.  The cure is the same as for the CCR analysis: make it a join (a table root or a hook).
* **Check a change of the translator** with `engine/xbench.py` (all opcodes and random sequences in every memory layout),
  the ports' lock-step tests, and for Galaga `engine/xdiff.py` against the build before the change.  `engine/xprof.py
  <game>` says where the cycles go per Z80 instruction form.

## Sprite edges and guard damage (all ports)

The hardware display window and the arcade picture inside it are different bounds. Pixels outside the hardware
window are hidden; side bands inside it remain visible. Reserve a wider virtual screen and vertical guard rows
for shifted objects, and restore each draw buffer's old sprite damage, including guard damage, before drawing again.

At a picture's left or right edge on a 16-pixel group boundary, cull sprites wholly outside and draw only the inner
destination word of a crossing sprite. Use the prepared opaque masks with the outer end mask zero, or a one-word
pass using the inner word's prepared end mask. Do not calculate another edge mask or erase new overhang after drawing.
This applies to every sprite path, including generic, cache-miss and address-crossing fallbacks. Top and bottom:
draw whole sprites into guard rows. Where a side edge falls inside a group, keep whole drawing into margins;
ports with moving windows may clip at the surrounding full band words while preserving the partial edge group.

The former blanket no-clipping rule was superseded on 2026-10-12. See `AGENTS.md` for the current rules and
`docs/sprite-preparation.md` for the preparation method and per-port results. Verify all four edges, all 16 shifts,
transparent holes, priority, 64 KB address crossings and consecutive frames against an independent reference.

Try the full stefastbobs2 preparation in each port: opaque runs and chains, grouping equal masks, reordered source,
prepared masks and generated code per shift, with reusable Blitter state and advancing source addresses. Retain an
optimization only after measuring CPU plus Blitter bus cycles; keep logic speed separate from picture rate. Cost
estimates and partial prototypes do not complete that experiment. Every HOG pass must stay at or below 256 bus
cycles and use the shared early, synchronized border handlers; verify timer timing in the pinned Hatari build.

## Change detection by translated writers (2026-10-09)

Comparing video RAM with a copy every frame costs 7.5 cycles a byte (`cmpm.l` + `dbne`): 15k for 2 KB.  When few
instructions write a RAM region, let them say so: record the write sites in a reference run (Commando's `ref/cover.py`
keeps `(pc, address)`; for Black Tiger `wr8` was hooked with the instruction's start pc - the Z80 core's `pc` at write
time is already the next instruction), list them in `gen.py` and emit `st <flag>` after each (`Scc` leaves the CCR
alone).  The runtime compares only when the flag is set, plus a few hundred bytes a frame in case a writer is missing,
and the logic test checks that every change of the region comes with its flag.  Black Tiger: background RAM (14
writers) and palette (10); Commando: tile RAM (10) and character RAM (31); 1942 had done the same for its tile and
character RAM.  Keep the game's own state exact anyway: Black Tiger still copies the outgoing background bank at a
bank switch when no flag is set (the game reads its map for collisions).

Also seen in Black Tiger (2026-10-09):

* `moveq #0,dN` before `move.w x,dN` when dN is then used as a long (an address offset, a cache key): the upper word
  holds whatever the caller left there; a new caller changed it and characters disappeared.
* An AUTOPLAY build must not let the VBL copy the keyboard state into the inputs it scripts: the game then plays
  differently from the reference run that gave the coverage, and reaches code the coverage never saw (`z80_badpc`).
* Text that stays put while the background scrolls under it: compose runs of characters into planar strips when the
  text changes, draw each run with the Blitter (FXSR, a zero word at each end of a strip line, two passes a plane:
  NOT mask AND screen, then pixels OR screen).  65 HUD characters went from 300k cycles a frame to 13-49k (plus 18-24k for the text RAM compare).
* Incremental virtual screens: check only the cells that scrolled in; draw a new tile to its twins one page away too
  (outside the window), so the next page is ready; per display ring a damage list restored from the clean screen.

## What Gun.Smoke added (2026-10-09)

* **A reference that boots is not a reference that plays.**  Gun.Smoke's first reference returned the real vertical blank
  in SYSTEM bit 3; MAME declares it `IPT_CUSTOM` without a read callback, so it always reads 1, and the interrupt handler
  skips its body when it reads 0.  The game sat in its first screen, the coverage stopped at 300 pcs, and the MAME picture
  checks passed (they render MAME's state).  Look at the reference after a few thousand frames, and count the pcs.
* **Window reads through `(iy+d)`**: with `z80x.FAST` IY is the low word of a2 (the upper word is not 0), so a gen's
  window check must match `(a6,a2.w)` too and compare a copy of the word (`move.w a2,d5`).  z80x's `write8` takes its
  address from `read8(op, io_read=False)`: a gen that guards in `read8` also guards stores unless it tells them apart
  (`GSEmitter.storing`).  Fixed the same way in Black Tiger's and Bubble Bobble's gens (Bubble Bobble missed
  `ld a,(iy-1)` at two window read sites); 1943's gen still has the gap.
* **The STE shows 48 pixels on each side of a 224-pixel window**: whole tiles and sprites drawn into the side margins are
  visible there. Never clear newly drawn overhang to imitate arcade clipping. Restore the previous picture’s
  damage before drawing; compare the arcade picture independently of these intentionally visible side bands.
* **HOG blits also delay Timer A's palette switches** (the picture's first lines black when the palette came on late):
  `wait_borders` waits while the palette-on event is pending and just before palette-off; text restores in 2-line bursts.
  **And the VBL itself**: a HOG blit across it delays the VBL handler that arms Timer A, the top border stays closed and
  the picture drops for a frame.  Black Tiger's and 1943's `wait_heavy` (a long pass starts only between the palette on
  and 10 lines before the bottom border) is safe; Gun.Smoke runs a pass that would wait there in pieces of 16 words
  instead (`blit_go`: the Blitter keeps its addresses; the CPU takes its interrupts between pieces), which keeps HOG and
  loses no time (waiting had cost 12%).  Changing the top border routine's instructions moves the palette switches
  (Timer A is restarted at its end): keep its cycle count.
* **Only short HOG passes, in every port** (the rule of stefastbobs2, whose top border handler runs beside one-line bob
  passes): the top border interrupt may come at any moment of the foreground, and a HOG pass holds it back until the
  pass ends.  `blit_go` (`engine/rt/borders.s`) cuts every pass into pieces of at most 32 words of a copy, 16 when the op
  reads the destination (~256 bus cycles, half a line), and a line wider than that into column strips (1942's and
  1943's 56-word copies).  No pass shares the bus: one without HOG runs on during the interrupts and stretches the timed
  code that opens the borders (Commando's margin clear was one).  Check with `BLIT_STATS=256` (`engine/sim.py`): a
  simulator run then lists every HOG pass longer than 256 bus cycles and every pass without HOG. The seven bordered
  ports checked on 2026-10-11 listed none; repeat this check for each renderer change and new port.
* **Generated sprite code is large for big sprite sets**: 2008 shapes (x 16 shifts) would take 2.85 MB.  Generate the
  routines and streams for the shapes coverage drew most within a budget (1074 shapes, 96.5% of the draws, 830 KB) and
  draw the rest with the same Blitter calls a row at a time, end masks from the stored opaque rows.
* **Cheats that patch code** (MAME's start round of Gun.Smoke changes an instruction's operand) need the same patch in
  the translated instruction for a lock-step test; setting the value in RAM after a tick is too late.
* **Horizontal hardware scroll next to the vertical virtual screens** (Gun.Smoke's D802): keep the tiles at fixed buffer
  x and move the Shifter's window (video address + `$ffff8265`, line width 4 words less with a fine scroll).  Then the
  window's edges are anywhere in a word: side bar clears need end masks (plane by plane), and text cannot use `movep`
  at the screen (8-pixel steps): compose a strip per text row and blit it shifted (mask pass, plane pass).  A line pair
  that comes into the band must get black side bars: it may hold what an earlier window position drew there (a test
  with 25 spaced frames passed, one with 40 found it).

## FM music as square waves (Commando, 2026-10-11; the other Capcom boards have the same YM2203s)

* **`engine/opn.py`** turns a sound driver's YM2203 register writes into what a YM2149 can play: per FM channel the
  pitch of its carriers and their loudness through the envelope generator (MAME's ymfm: rates, key scaling, sustain
  level, total level; the modulators only shape the timbre and are left out).  Mind the prescaler the driver selects
  ($2D/$2E/$2F): it sets the FM rate (clock / 72, / 36, / 24) and the SSG clock.  ymfm's attack step relies on C's `~`
  of a promoted int (`att += (~att * inc) >> 4`): with `~att & 0x3FF` in Python the attack never leaves full
  attenuation.  1943, Gun.Smoke and Black Tiger have YM2203s too (MAME capcom/1943.cpp, gunsmoke.cpp, blktiger.cpp).
* **Record with the STE's interrupt timing, not the arcade's.**  The arcade's sound CPU loses an IRQ when a handler runs
  longer than the gap to the next (a tune's load); a driver that does part of its work on odd counts then drifts
  against its own loop.  The STE runs the four IRQs of a tick back to back, so record that way (run each handler to
  its return) and the tunes become periodic; their tempo still matches MAME's audio.
* **A repeat of a channel's RAM is a loop only if it keeps repeating**: check it over a whole period more.  Commando's
  channels repeated their 32 bytes after 24 ticks and then parted.
* **Six channels on three**: pick the loudest each tick (prefer the ones that played the tick before, keep each on its
  YM channel), after the effect has taken the channels it sounds on; per-channel streams loop independently, so the
  choice has to be made at run time, not in the recording.
* **Check the pitch against MAME's audio**: poke the sound latch from a Lua script (`space:write_u8` goes through the
  handlers) and `-wavwrite`; correlate semitone spectra of both (a wrong prescaler or octave shows as a shifted peak).

## Recorded sound for every port (Gun.Smoke, 1943, Black Tiger, Bubble Bobble; 2026-10-11)

Commando's method (record the sound driver's output per command, play it in the driver's own scheme) became shared:
`engine/capsnd.py` (a driver described by its addresses: the board, the recordings, the models, the checks, the data
of `engine/rt/capsnd.s`), `engine/rt/capsnd_core.s` (the stream decoders and the mixer, also used by Black Tiger's and
Bubble Bobble's own players).  Regenerating Commando's data with it gives Commando's recordings exactly.

* **Find the driver's facts by running it, not by reading it**: which commands stop which slots (run every handler on
  a board whose slots are all marked busy), which chip parts a command uses (log the writes of each command alone).
* **Check the model against the real driver, then the 68000 player against the model.**  Compare what sounds: a
  channel with tone and noise off is silent whatever its period and volume (`capsnd.audible`); start the model's IRQ
  counter where the driver's boot left it.  What is left are real limits of recording each command alone (a noise
  period an effect inherits from the one before; an FM envelope carried over), counted in the READMEs.
* **Drivers differ in the details**: Gun.Smoke's and 1943's end the lower effect slots under the shown one unless a
  byte of theirs is $FF (an effect opcode sets it and nothing clears it); Black Tiger's (timer-driven, ~250 Hz) has
  priorities, one effect slot a chip and a main / backup tune; Bubble Bobble's (Taito) has 26 tracks, two per channel,
  the A track winning, and a tempo the tunes change: record that one in real time (a value a VBL), and find loops on
  the chip writes of the driver's timer ticks, per timer (its RAM holds counters that never repeat).
* **Long effects and big tunes**: an effect that repeats a period for minutes keeps one period with a loop and a total
  (`compact`); tunes as data for a 250 Hz player pack 3x with a byte LZ (`engine/lz.py`, `rt/lz.s`): unpack when a tune
  starts, in the idle hook, not in the VBL.  Phase exceptions above 8 KB are dropped (`capsnd.EXC_LIMIT`).
* **Memory**: 1943 and Black Tiger had 26-45 KB free.  Their dispatch entry lists (91 / 115 KB) are read once at the
  start: the generator emits them as a macro placed last in the data section, where the screen buffer begins, the rest
  of which is the first thing in the BSS (the program checks that the two parts meet and fills the dispatch tables
  first).  The memory comes back for the sound.
* **Memory budget** (2026-10-15): a program asks TOS for at most 3,700,000 bytes (text + data + BSS + 256;
  `tools/release.py` refuses more).  TOS 2.06 alone leaves 4,061,212 from the desktop on a 4 MB STE
  (`tools/memfree.sh`; 4,145,998 before the desktop), but a tester's Mega STE with a hard disk driver and accessories
  had 3,831,554, and five ports at 3.93-4.05 MB would not start (Pexec fails, TOS says there is not enough memory).
  What brought them to 2.94-3.67 MB (the work of 2026-10-10 and 2026-10-15), without changing what the games do:
  - dispatch tables built as data at assembly time, not BSS filled from entry lists at the start: a word per Z80
    address, (the entry - the table or a region's base) / 2, the table in the text before its code so the jump is
    relative (1943, Black Tiger: 448 / 640 KB of long tables; 1943's banks as pages, a directory long per 64
    addresses, 104 -> 50 KB).  The ports whose translated `ret` indexes a long table inline (`z80x`, a4) keep it, as
    data;
  - ROMs assembled where the translated code reads them instead of copied there; what start reads once anyway (ROM
    images, entry lists: Bubble Bobble) under a buffer that is not used until later, the data's end aligned to the
    BSS's alignment so that the two meet (the start checks it);
  - per-pen masks (a word per pen per row) became the arcade's bit planes: Commando bakes a row through a routine per
    colour generated from the colour map (the products of the plane pairs), a quarter of the time; 1942's tiles get
    their masks from `engine/rt/penmasks.s` (its sprites keep theirs: their bakes cost the 99th percentile tick 12%);
  - shared row orders and Blitter routines of an image and its mirror image, equal plans stored once, the caches of
    baked graphics sized to their measured use (1942), the 68000 stack to what it uses (1943: 8 KB).

* **Pitfalls met**: Musashi does not fault a word access at an odd address (`clr.w` at `bb_ssg+9`; Hatari did), so
  start every BSS block of new code with `even`; a recording of a few seconds says nothing about a game whose attract
  mode is silent for its first 25 s (Black Tiger) — look at the reference's commands before calling Hatari silent; a
  driver may read back the SSG registers or wait for the second chip's timer at boot (Bubble Bobble); a game's asset
  builder may put another game's tools first in `sys.path` (1943's: 1942's `sound.py`).

## Two related projects compared (2026-10-11)

Read, not built or run: `stedaimakaimura` (Daimakaimura, Capcom 1988, an STE / Falcon test from 2017-2020) and
F030Arcade's spare-time renderer (`PORTING.md` there, "Spare-time renderer").

* **A 68000 board needs no translation.**  Daimakaimura's program is a traced disassembly (every byte marked code, data
  or pointer) reassembled at its own addresses: the inputs, the CPS-A/B registers, the graphics RAM and the work RAM are
  labels in STE RAM, the arcade's vectors point to the STE's VBL / HBL / IKBD / Timer B handlers, and the part that
  overlaps the TOS system variables (`$400-$84E`) moved to `$100000` behind `jmp` stubs.  The game's code runs natively.
* **Patches instead of the arcade's code**: `relocate_rom.js` lists the words in which the assembled program differs from
  the ROM; at start the program loads the user's ROM files, swaps their bytes and applies the list.  The renderer and the
  graphics are in a separate data file.  An alternative to the self-contained programs of the releases.
* **Its sprite renderer is this project's**: one Blitter copy per run of a line, the end masks as the mask (precomputed
  for the 16 shifts), a line with the edges of the line before only moves the destination.  Its sprites were grabbed
  from the running game, so a sprite never seen is not drawn: the graphics side of the coverage problem above.  The ports
  here bake their graphics from the ROM sets instead.
* **Its colours**: nearest colour in CIELAB, plus 50/50 checkerboard mixes of palette pairs that are close enough (for a
  CRT).  The ports here use exact palettes or a fixed Oklab palette (Bubble Bobble), no dithering.
* **"The frame is done"**: Daimakaimura patches one instruction into the game's task scheduler (all tasks idle ->
  `request_next_frame`); the VBL handler then draws, stops when Timer B's line count says the beam is close, and resumes
  at the next VBL.  F030Arcade generalises it: the VBL shows a completed page, runs one game step and asks for a picture;
  Timer B, ~0.5 ms later, starts or resumes the renderer on its own stack at IPL 3 once the game is parked; the renderer
  queues its page.  An overloaded renderer drops pictures, never logic.  The park test is per board (Nemesis: the
  command-queue wait with an empty queue; Snow Bros: a coroutine whose registers matter; Heavy Barrel: none, the frame is
  the VBL handler), and parking a wait loop can lose a side effect (DoDonPachi's loop advanced a random index).
* **What applies here**: the Z80 ports already run each frame as interrupt handlers to completion, so the end of the
  handlers is the end of the frame (see `docs/architecture.md`, "Runtime schedule").  Bubble Bobble already has the
  completed-page queue (three screens).  The cases left are the ports whose foreground does work (Galaga's main CPU draws
  text before it idles at `$038D`; 1942's cooperative kernel) and the ports that skip pictures to keep the game's speed
  (1943, Bubble Bobble).  Not measured: whether their drawing waits for logic it could overlap.

## Palette stamps and measuring (Bubble Bobble, 2026-10-12)

* **Stamps instead of cache walks.**  When a pen's colour slot changes, do not walk the baked caches: start a new
  palette epoch, record it for the pen (and the latest per bank), and store the epoch with each baked entry (tile,
  sprite image, cell composite).  A lookup whose stamp is older checks only the pens its tiles use (the per-tile pen
  mask the assets already have) and refreshes the stamp when none changed.  The keys stay exact; the epoch's wrap
  flushes everything.  Bubble Bobble: ~225k -> ~50k cycles a slot change, sprites no longer redrawn for pens they do
  not use.
* **Composite caches pay where the game repeats itself.**  A level's static cells come from a few dozen tile pairs
  (60 recipes for 896 cells); an exact cache of composed cells (keys + stamp + pixels + opacity) makes a rebuild and the
  usual redraws mostly copies.  A cache keyed by an interned colour mapping would also serve colour cycling.
* **Profilers attribute by the nearest label**: a `name = *` label (no colon) is a symbol too; a profiler that buckets
  by source file must include it (Bubble Bobble's block copy loop had been charged to the runtime), and absolute
  symbols (equates such as pad bit masks) must not be used as code labels.
* **Test the margins too**: when sprites are drawn whole into guard rows and visible side bands, the reference test
  should check that every set pixel outside the arcade picture belongs to a sprite drawn now (Bubble Bobble's
  `render_test.py`); a negative run (the guard restore disabled) shows that the check bites.
* **Before/after in Hatari**: a DEBUG + AUTOPLAY build that replays the simulator profile's input script by VBL and
  writes counters every 300 VBLs (Bubble Bobble's `tools/bench.sh`) gives windows comparable with `profile.py`'s.

## What the Namco System 1 work added (Splatterhouse, 2026-10-12)

* **CPU cores against MAME traces.**  MAME 0.289 writes per-instruction traces headless: `-debug -debugger none
  -autoboot_script t.lua` with `manager.machine.debugger:command("trace f.txt,maincpu,noloop,{tracelog \"%d \",totalcycles}")`
  (set `debugger.visible_cpu` to the traced CPU: tracelog prints for the visible one only; one CPU per run).  The 6809
  and HD63701 cores replay such traces with 0 mismatches (registers, writes, cycles), and a translator test runs every
  instruction against the core.
* **A reference that follows MAME exactly** is worth it on a multi-CPU board: with MAME's scheduler copied (see
  `docs/architecture.md`, "Namco System 1") the RAM equals MAME's for minutes, so a difference is a bug.  The details that
  mattered, each found by comparing traces: MAME's frame_done N is at time N frames (with `-debug` it counts one more);
  a 6809 reset's 4 cycles are time; an input line change takes effect when its synchronize() timer fires, at the end of
  the writing 6809 instruction (MAME's 6809 counts a bus cycle before it does the access; the 6800 cores count after
  the instruction), and it aborts the running slice only when it is the first timer; the HD63701's serial clock (RMCR
  $04) is a periodic timer every 4 CPU cycles that cuts every slice.
* **Run MAME in a fresh directory for every comparison**: a reused one keeps `nvram/`, and an initialised EEPROM made the
  MCU take another path.  Lua write taps installed while the autoboot script loads are lost: install them at the first
  frame_done.
* **Coverage through the game's own test features**: Splatterhouse's Stage Select DIP switch starts every stage; seven
  seeds grew the main CPU's translation from 5247 to 7172 instructions.
* **Test harnesses lie too**: a test of every instruction must make sure every opcode got tests (the first version filled
  one page and silently left out the rest); a stop address must not be `badpc + 2` when the next routine starts there; a
  move to memory spoils the flags a stub wants to record (save the SR first).
* **Speed of the 6809 translation** (68000 cycles per arcade frame for the two CPUs, lock-step identical throughout):
  play 452k -> 147k, stage 3 244k -> 211k.  What mattered: per-function return liveness (2250 flag wrappers -> 140),
  static and inline bank switches, I/O sites from the coverage's addresses (the sprite RAM plain), cached slot bases,
  byte-direct 16 bit operations, jump tables for `JSR [B,X]`, natives for the sub CPU's sprite builder.  Profile by
  6809 instruction and by 256 byte region (`tools/profile.py`).

## What the V30 translation added (R-Type, 2026-10-13)

* **Little-endian words on the 68000**: keep the arcade CPU's memory with the bytes of every word swapped.  Words at even
  addresses become native moves (R-Type reads 45 words for every byte), static byte addresses cost nothing, a byte at a
  register address costs `moveq #1,d7; eor.w dX,d7`.  The renderer reads the video, palette and sprite RAM as native
  words too.
* **Random play does not reach every computed target**: R-Type's object handlers are stored as immediates
  (`mov word ptr [bp+0h],2D50h`) and called later, some only through ROM tables copied to RAM, and its jump tables
  have entries play rarely takes.  The translation takes them from the program (`games/rtype/tools/gen.py`: tables in
  ROM, stored handlers, every stored code address, the idiom's bytes anywhere, code right after a RET that nothing
  refers to; "plausible" = ordinary instructions up to a transfer, never starting inside covered code); the long
  lock-step runs stopped at exactly these.  The flags these callers read cost ~10% more cycles: correct, not waste.
* **Liveness through computed calls**: a RET reached only through a computed call or a jump table had no return points
  and counted as reading every flag, which made shared functions keep flags for all callers (1055 wrapped
  instructions; 117 once those RETs got the return points of the computed calls).
* **Returns without the flags**: a table of 64K longs indexed by the popped IP (`move.w (a5)+,a0`, two `add.l a0,a0`)
  jumps without touching the CCR, so functions returning a carry need no SR save.
* **The port's schedule changes the game**: the VBL handler always runs to completion (MAME's game skips its logic when
  a frame overruns), so long runs reach states the MAME-scheduled coverage never saw; and a stale object pointer
  (seed 9, frame ~26900) reads unmapped memory, which the arcade reads as 0 and the image as what was written.
* **The renderer reads the arcade's byte order, the image keeps it swapped**: `games/rtype/src/video.s` copies only what
  changed - the translated stores into the video RAMs and palettes mark their 256-byte blocks (`gen.py` store_marks,
  checked by logic_test), and before a picture the marked blocks are swapped back (`movep`, ~3k cycles a block) into the
  renderer's video state, the sprite list after a DMA.  A swapped-order mode in `engine/rt/m72render.s` would make the
  copies unnecessary.

## Port completion claims

For every port, automated exploration can attempt full progression after its
adapter and native replay transport are verified. Success is not guaranteed by
agent support. Use the shared [status and full-game verification policy](port-status.md)
to distinguish natural completion, assisted coverage and incomplete verification;
reserve green **Complete** for verified Hatari playability with graphics and sound.
