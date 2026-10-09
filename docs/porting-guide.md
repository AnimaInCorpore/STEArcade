# Porting guide

How a game goes from a ROM set to a running STE port, and what the first three ports taught.  The architecture
is in `architecture.md`; `port.py` runs every step (`port.py cover|build|test|run|mame <game>`).

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
6. **Runtime** (`src/<game>.s`): loader, dispatch tables, VBL schedule, input, border removal, hooks.
7. **Renderer**: exact against the reference bitmap through the colour table first (`render_test.py` style:
   copy the reference RAM in, call `render_frame`, compare pixels), fast second.
8. **Hatari** (`tools/hatari.sh`, F030Arcade build): look at the screen, then compare frame counters/skips from the `--debug` build.
   Looking found most bugs that the tests did not (wrong colours, missing sprites, bus errors on odd accesses).

## Lessons

* **Musashi is not a 68000 for faults and timing**: it executes odd word accesses silently (Hatari takes an address
  error) and has no MFP timers or border removal.  Test for odd accesses (`games/bublbobl/tools/align_test.py`) and
  build the simulator variant with `-DSIM`.  Crashes that appear only in Hatari have been: stack overflow by nested
  VBLs, window-read sites coverage missed, odd word loads in translated MCU code.
* **Self-tests flood the renderer** (video RAM test) and run ~700 frames: skip them in the reference and the
  translation, compensate any ROM checksum the game runs later, load the patched ROM files in the runtime.
* **Palette**: 16 STE colours against 22-26 on screen.  Keep the colours in order of appearance while they fit;
  otherwise the background, "volatile" entries (changed >= 4 times: flashing, they own a slot), and the heaviest by
  weight capped per bank.  Re-mapping must only rewrite the STE palette when the mapping is unchanged.
* **Throttle the logic when it cannot keep up** so the renderer still runs; never let a pending VBL nest.
* **Reference renderers can be wrong in ways "port equals reference" cannot see** (plane order, palette weights,
  a sprite row off by one): the MAME check below is not optional.
* **Verify claims about other work by running it**: a summary that says a renderer is a stub may be stale.
* Script names in `ref/` and `tools/` must not shadow the standard library (`dis.py` broke `import inspect` inside numpy).
* Branch-out-of-range and `lea` displacement warnings in vasm are normal at this size; real errors stop the build.

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
  stays in the log; Galaga's comes from the blank MCU ROMs below, Bubble Bobble's from the PAL dumps nobody has.
* **The MAME source in `F030Arcade/third_party/mame` is older than the binary** (Galaga's blue channel differs:
  the source says 0x47/0x97, MAME 0.289 produces 0x51/0xAE).  The installed `mame` is the truth.

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
* **Dirty flags by coverage**: the renderer only diffs the video RAM after a store to it; the sites are coverage results, the lock-step test checks
  that every change had its flag, and the renderer rescans now and then.
* **Test windows that wrap.**  The first renderer test passed for 1000+ frames and the wrapped half of the scroll ring was never drawn: a window
  position (T > 256) that the sampled frames had not covered hid a garbage upper register word.  Sweep the whole range of a scroll register.
* **Hatari**: a Blitter pass that hogs the bus delays the VBL and the border timers by more than half a scanline, the screen then flickers between
  open and closed borders.  Keep passes short or run them without HOG and wait for them; look at Hatari's own screenshot (RightAlt+G) of
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
  stack above SP only (Donkey Kong's `fullrun.py` already did).
* **An interrupt's `push af` saves d6**, which need not hold the interrupted code's flags at that moment (they may be in
  the CCR; the 68000's own interrupt restores them).  The pushed byte is not state: compare it in a test only where the
  translation makes the flags exact (1942: hooks, `jp (hl)`).
* **Unforeseen entries stop loudly**: a computed jump to a pc the analysis did not count as an entry (joins: entries,
  return points, jump table targets, code addresses held as numbers) now ends at `z80_badpc` with the pc in d7 when the
  pc is inside a merge.  The cure is the same as for the CCR analysis: make it a join (a table root or a hook).
* **Check a change of the translator** with `engine/xbench.py` (all opcodes and random sequences in every memory layout),
  the ports' lock-step tests, and for Galaga `engine/xdiff.py` against the build before the change.  `engine/xprof.py
  <game>` says where the cycles go per Z80 instruction form.

## Whole-object drawing (all ports)

Use a wider virtual screen with enough hidden space on both sides for a whole
object, including the extra destination word of a shifted sprite. Objects crossing
an edge are drawn whole and disappear behind the visible display window. Do not
implement sprite clipping routines or calculate edge masks at runtime. Reserve
vertical guard rows too when whole objects can cross the top or bottom.

Sprite drawing follows `C:/Arbeit/stefastbobs2/main.s`: reorder source rows to group
equal opaque masks, bake the end masks for all 16 horizontal shifts, and reuse
Blitter state and its automatically advancing source address. Use short HOG blits
with the border timer guard. This is the required approach for every port; older
renderers must be migrated when their sprite drawing is changed.

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
  visible there.  Clear the side chunks a tile or a sprite reached (the damage list then restores black from the twin);
  `render_test.py` checks the side bars.
* **HOG blits also delay Timer A's palette switches** (the picture's first lines black when the palette came on late):
  `wait_borders` waits while the palette-on event is pending and just before palette-off; text restores in 2-line bursts.
* **Generated sprite code is large for big sprite sets**: 2008 shapes (x 16 shifts) would take 2.85 MB.  Generate the
  routines and streams for the shapes coverage drew most within a budget (1074 shapes, 96.5% of the draws, 830 KB) and
  draw the rest with the same Blitter calls a row at a time, end masks from the stored opaque rows.
* **Cheats that patch code** (MAME's start round of Gun.Smoke changes an instruction's operand) need the same patch in
  the translated instruction for a lock-step test; setting the value in RAM after a tick is too late.
