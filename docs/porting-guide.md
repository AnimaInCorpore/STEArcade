# Porting guide

How a game goes from a ROM set to a running STE port, and the correctness lessons of the ports, by topic.
`port.py` runs the registered ports (`port.py cover|build|test|run|mame <game>`); work in progress outside
`port.py list` uses its own scripts under `games/<game>/tools/` and `ref/`.

Where the rest is:

| Page | Topic |
|---|---|
| [architecture.md](architecture.md) | how a port works: reference machine, translators, runtime schedule, borders, input, boards |
| this page | the method and what went wrong: MAME checks, coverage, translation, STE / Hatari pitfalls, sound, memory |
| [speed.md](speed.md) | speed: budgets, measuring, every logic and picture technique, dead ends, which port uses what |
| [sprite-preparation.md](sprite-preparation.md) | sprites the stefastbobs2 way: the method and every port's measurements |
| [colours.md](colours.md) | palettes: rules, the default fitter, each port's path, the 2026-11-05 rollout |
| [port-status.md](port-status.md), [ppo.md](ppo.md), [go-explore.md](go-explore.md) | completion claims, PPO exploration, cell archives |
| [megaste-border-timing.md](megaste-border-timing.md), [megaste-diagnostic.md](megaste-diagnostic.md) | the Mega STE's 16 MHz border path and the tester's diagnostic |
| [virtual-scroll-performance.md](virtual-scroll-performance.md) | the dated scrolling audit of 2026-10-19 and its results |
| [mame-candidates.md](mame-candidates.md) | generated list of MAME games with hardware like the ported ones |

## Steps

1. **Read the MAME driver** (`F030Arcade/third_party/jsm68kdisassembler/third_party/mame`, MAME 0.286, see PORTING
   there): the authoritative MAME for every port (user, 2026-10-29, `AGENTS.md`), colours included: where a MAME
   binary disagrees with this source, the source wins and the port's README notes it.  Memory map, interrupts,
   video RAM layout, sprite format, palette PROMs, helper chips.  Chips with their own program (Bubble Bobble's
   MC6801, Galaga's 51xx/54xx) are either run (translated, preferred when the ROM is in the set: "run the device,
   don't replay its answers") or simulated at the register interface.  Never substitute blank MCU ROMs for gameplay.
2. **Reference machine** (`games/<game>/tools/machine.py`): CPUs, memory map, interrupts, renderer (`render_raw`).
   Keep a `run_frame_port` that follows the runtime's schedule.  Boot self-tests are skipped with patches
   (`skip_tests`) that keep any running checksum intact.
3. **Check the reference against MAME** before building graphics (next section).
4. **Coverage** (`ref/cover*.py`, random input, several seeds; `port.py cover <game>`): the program counters seen
   executing, the I/O and banked-window sites.  Discovery adds jump tables and what static recursive descent finds;
   anything coverage found but discovery missed is a hook or a table ("Coverage and discovery" below).
5. **Translate** (`tools/gen.py` of the game; `engine/z80x.py` + `translate.compile_code`, `engine/m6809x.py`,
   `engine/v30x.py`): memory model, register map, hooks for I/O writes and yields, window/bank handling for banked
   ROMs.  `port.py test <game>`: lock-step against the reference (RAM every frame).
6. **Runtime** (`src/<game>.s`): loader, dispatch tables, VBL schedule, input (the IKBD handler around `ikbd_byte`
   of `engine/rt/ikbd.s` and key_table, the pads through `engine/rt/jagpad.s`: the `JP1_*` ... `JP_COIN2` bits,
   `jagpad_poll` and `jp_merge` in the VBL), border removal (`engine/rt/borders.s`), hooks.  A new port gets a line in
   `port.py`'s `GAMES` (and its tables), `tools/release.py`'s list and the README's tables; its folder follows the
   README's "Layout" (ROMs: `tools/prepare.py` + `docs/rom_manifest.json`).
7. **Renderer**: exact against the reference bitmap through the colour table first (`render_test.py` style: copy the
   reference RAM in, call `render_frame`, compare pixels), fast second (`speed.md`).  Colours: `colours.md`.  Sprites:
   `sprite-preparation.md` and the rules in `AGENTS.md`.
8. **Hatari** (`tools/hatari.sh`, the F030Arcade build): look at the screen, then compare frame counters/skips from the
   `--debug` build.  Looking found most bugs that the tests did not (wrong colours, missing sprites, bus errors on odd
   accesses).  Then a recorded-play bench (`speed.md`, "Measuring").

General rules: translate whole programs; no silent NOPs (an unknown instruction stops the build or the run at
`z80_badpc` with its pc); verify claims about other work by running it (a summary that says a renderer is a stub may
be stale); script names in `ref/` and `tools/` must not shadow the standard library (`dis.py` broke `import inspect`
inside numpy).

## Checking the reference

"The port equals the reference renderer" only means something if the reference equals the arcade.  Reference
renderers can be wrong in ways "port equals reference" cannot see (plane order, palette weights, a sprite row off by
one): the MAME check is not optional.  Do it *before* building the port's graphics, and again whenever the reference
renderer changes.

### Against MAME's picture (every port)

Donkey Kong's reference had two errors that this found on 2026-10-08, neither visible in a Hatari-vs-reference test:

* **Sprites were one raw row off**: `top = 246 - y`, MAME's `draw_sprites` gives `247 - y` (its line buffer fetches the
  sprite one scanline ahead, hence the `+ 1` in `y + add_y + 1 + scanline`).  Positions derived from the MAME source
  need a snapshot to confirm them (0 pixels differ with 247, about 900 with 246).
* **The palette was wrong** (up to 75 levels per channel): the Galaxian style weights 0x21/0x47/0x97 and 0x55/0xAA are
  not what current MAME computes.  Its colours come from resistor network models (`compute_res_net`: darlington
  stages, tri-state black), so take the numbers from MAME itself: `games/dkong/tools/dkong_pens.py` is a dump of
  `pen_color()` for the 256 pens.  Do the same for any game whose reference computes colours from PROM weights.

The 2026-10-08 checks of Galaga found that `decode_gfx` made the first plane the *least* significant bit (MAME: the
most significant; pixel values 1 and 2 of every character and sprite were swapped) and a wrong blue (0x47/0x97 against
MAME's 0x51/0xAE).  Bubble Bobble needed nothing.  All three now show 0 differing pixels
(`games/<game>/ref/mame_cmp_<game>.py`).

How (`engine/mame_dump.lua`, `games/dkong/ref/mame_cmp_dkong.py`; MAME is `/opt/homebrew/bin/mame`, 0.289; the ROM
zips are in `assets/roms`): start MAME with **`-window`** (with `-video none` there is no snapshot), run a Lua script at
frame N that writes the pens (`palette:pen_color(i)`), a memory range and `video:snapshot()`, render the same memory
with the reference and count differing pixels (`venv/bin/python games/dkong/ref/mame_cmp_dkong.py 700 1500 2500 4000`).

* **Take several frames**: the memory is read after the frame was drawn, so a fast sprite can be one step ahead.
* **Banks**: write taps on the I/O latches did not report the palette bank reliably, so the compare tools try all
  palette/sprite banks and report the best.  A bank mismatch shows as whole tile colour sets wrong, a position
  mismatch as a one pixel outline around every sprite.
* **No key press**: MAME shows its startup screens and waits for a key unless `-seconds_to_run` is below 300; the
  scripts use `-seconds_to_run 250` (about 15000 frames with `-nothrottle`).  A "ROMs not correct" warning stays in the
  log (Bubble Bobble's PAL dumps nobody has).
* **Binaries and the authoritative source can differ** (Galaga's blue: the 0.286 source says 0x47/0x97, MAME 0.289
  produces 0x51/0xAE).  The source is the truth (`AGENTS.md`); a binary is still useful for pictures and traces of the
  drivers whose source is the same in both.  Galaga's reference still uses 0.289's blue (not changed yet).
* **Several frames in one run, write logs with the beam line** (`engine/mame_frames.lua` + `engine/mame_cmp.py`; Track
  & Field, Hyper Sports, Gyruss): dumps of any CPU's ranges, snapshots and pens at a list of frames, and a log of the
  writes to TAPS ranges.  A write tap installed while the autoboot script loads is silently lost (install it at the
  first `frame_done`); the screen has no `vpos()`/`hpos()` in Lua (an error inside a tap callback is swallowed): the
  line is `(-screen:time_until_pos(0, 0) / screen.scan_period) % vtotal`.
* **A fresh directory per run**: MAME writes `nvram/` (and `cfg/`, `snap/`, `sta/`) and reads it back next time (high
  scores; an initialised EEPROM made Splatterhouse's MCU take another path).
* **MAME never in the user's way** (user, 2026-10-29: "Always run mame minimized!"): start every MAME that opens a
  window through `engine/mamewin.py` (`mamewin.run` / `mamewin.popen`; `mame_cmp.run_mame` uses it).  On Windows MAME
  then runs on a desktop of its own with `-video gdi` (a minimized MAME still took the foreground; Direct3D and bgfx
  crash on such a desktop).  `-video none` opens no window.  Lua numbers printed under a German locale have a decimal
  comma: parse with `.replace(",", ".")`.
* **Partial updates**: a driver whose RAM write handler calls `screen.update_partial(vpos)` (Gyruss's sprite RAM: the
  sub CPU writes sprites until line ~36) draws the lines up to the write's line with the old values.  Render per band
  of lines from the previous frame's dump plus the logged writes (`games/gyruss/tools/machine.py: sprite_bands`).  The
  same driver marks the whole tilemap dirty only at the first band, so tile RAM is effectively sampled once a frame.
* **Sprite multiplexers that race the beam** (Gyruss): a CPU that reads the beam's line and reuses the sprite entries
  the beam has passed shows more sprites than the hardware has.  A translation cannot follow the beam: give the reads a
  model fitted to the MAME-timed reference (Gyruss: line = 25 + 0.6 x the reads of the IRQ), render the reference per
  band of lines with it, and on the STE log each reused entry's old content and line and draw every content clipped to
  its band.
* **Encrypted opcodes** (KONAMI-1: Track & Field, Hyper Sports, Gyruss's sub CPU; also Circus Charlie, Juno First,
  Megazone, Jail Break, Finalizer, Roc'n Rope): `M6809(rd, wr, rd_op=konami1_opcode(rd, boundary))` and
  `m6809dis.decode(..., rd_op=...)`; only the opcode bytes (the first byte and the byte after $10/$11) go through
  `rd_op`.  A translator reading code bytes must do the same (`engine/konami1_test.py`).
* **Irem M72** (R-Type, Mr. HELI; `engine/m72.py`, `engine/m72_mame.py`): the scroll, raster-line and sprite-DMA
  registers are V30 *I/O ports*: TAPS take `tag:space:start:end` (`maincpu:io:0x80:0x87`; a 16-bit bus's write is
  logged byte by byte, the range must cover whole bus words), `f<frame>_tapstate.txt` holds the registers' values
  before the logged writes, DUMPS of 20-bit ranges go to `f<frame>_<tag>_<space>_<start>.bin`.  The sprite chip draws
  a buffer the program fills by a write to port $04: SNAPS `maincpu:io:0x04=maincpu:0xc0000:0xc03ff` copies the sprite
  RAM at that write.  MAME draws the lines up to the raster interrupt's line (port $06 - 128) when it fires and the
  rest at the frame's end: render per band (the palette is not banded).  Pens never written keep MAME's default
  pattern, not black: compare after the game wrote the palette.
* **Known MAME behaviours the ports do not have**: the 16 sprites per scanline limit and the wrap-around of sprites at
  the arcade's 256-pixel edge.  Neither is visible in normal play.
* **Galaga before its MCU ROMs** (until 2026-10-21) could not run in MAME: `engine/mame_dump.lua` with `INJECT=` wrote
  the reference's RAM into MAME's and froze it with write taps, which tests the renderer, not the game.

### Frames from an old MAME without Lua snapshots (WolfMAME 0.162, Windows)

`F030Arcade/third_party/wolfmame-0162/mame.exe` knows Bubble Bobble (`bublbobl`, `bublboblr`); `wolfmame-0184` does
not.  Its Lua is the old API (`emu.sethook(fn, "frame")`, `screen:frame_number()`, `manager:machine():exit()`; no
`register_frame*`, no `video:snapshot()`).  What works is MAME's own recording:

* `-aviwrite name.avi` writes uncompressed RGB24 at the native size (the container says 60 fps whatever the board
  runs at); the file lands in `snap/`.  The writer is 32-bit: record ~300 s segments chained with `-autosave`
  (`-seconds_to_run` is cumulative: segment k uses `(k+1) * 300`); `-sound none -nothrottle -frameskip 0
  -skip_gameinfo -window`.
* Read the frames with `ffmpeg -i x.avi -an -f rawvideo -pix_fmt rgb24 -` (`-fps_mode passthrough`).
* **Check the recording for stray input**: a key reaching the window registered a coin 27 s into a segment.
* Example: `games/bublbobl/ref/mame_attract_collage.py` (20 minutes of attract mode, 68 colours, a 64-frame collage
  that contains every one; the last new colour at 12.3 minutes).

### MAME traces and multi-CPU boards

* **CPU cores against MAME traces** (Namco System 1): `-debug -debugger none -autoboot_script t.lua` with
  `manager.machine.debugger:command("trace f.txt,maincpu,noloop,{tracelog \"%d \",totalcycles}")` (set
  `debugger.visible_cpu` to the traced CPU; one CPU per run).  The 6809, HD63701, V30, i8051 and Z80 cores replay such
  traces with 0 mismatches, and a translator test runs every instruction against the core.
* **A reference that follows MAME's scheduler exactly** is worth it on a multi-CPU board (`architecture.md`, "Namco
  System 1"): the RAM then equals MAME's for minutes, so a difference is a bug.  Namco System 1: MAME's frame_done N is
  at time N frames (with `-debug` it counts one more); a 6809 reset's 4 cycles are time; an input line change takes
  effect when its synchronize() timer fires, at the end of the writing instruction, and aborts the running slice only
  as the first timer; the HD63701's serial clock is a periodic timer every 4 CPU cycles that cuts every slice.  Irem M72
  (`engine/m72board.py`, equal to MAME in all RAM and the picture through frame 4000): `abort_timeslice` takes the rest
  of icount as stolen cycles; suspended CPUs still eat cycles and can lower a round's target; the sound manager's 50 Hz
  update cuts slices even with `-sound none`; `machine().time()` inside a timer callback is the timer's expiry; ymfm's
  sample count at a register write is floor(t * rate) + 1, which sets timer B's start.
* **MAME's debugger for a small CPU** (Gyruss's i8039, `games/gyruss/tools/i8039.py --mame`): a breakpoint action's
  `printf` reads the registers of the debugger's current CPU, not of the one that hit it (stop once on that CPU first);
  a command reaching a CPU through a latch with a delayed write needs its interrupt a frame after the latch.

### A reference that boots is not a reference that plays

Gun.Smoke's first reference returned the real vertical blank in SYSTEM bit 3; MAME declares it `IPT_CUSTOM` without a
read callback, so it always reads 1, and the interrupt handler skips its body when it reads 0.  The game sat in its
first screen, the coverage stopped at 300 pcs, and the MAME picture checks passed (they render MAME's state).  Look at
the reference after a few thousand frames, and count the pcs.

### Recorded arcade games as an acceptance test (MARP; Black Tiger, 2026-10-22)

The MAME Action Replay Page (http://replay.marpirc.net/) keeps whole expert games recorded in WolfMAME.  Played back
in the WolfMAME version that recorded it, a recording is the board's own game, and a frame dump of it is ground truth.
F030Arcade replays such a game on its Falcon Black Tiger port (this repository's translation): 67 minutes, 2,006,700
points, equal at every check to game over (F030Arcade's `docs/marp-replay.md`, `scripts/mame_inp_dump.py`).  Use it
for any port whose set has a recording: it found what coverage, PPO and reference tests had not (below, "Coverage and
discovery"; every port has recordings: the port's schedule then has to leave them as the arcade does).

## Coverage and discovery

* **Every phase of the game, not only the attract mode and the play**: Galaga 0.2 stopped at the high-score name
  entry, whose two jump tables no coverage run had reached.  Seed the states a short run never gets to (a high score, a
  game over, the ending) by poking the arcade's RAM in `ref/cover.py`, and keep a crash dump (CRASH.TXT) that names the
  unknown pc.
* **MAME's cheats reach the later stages** (`third_party/mamecheats/cheat.7z`, the set's xml: lives, invincibility, a
  level skip).  Coverage and the lock-step test need them.  Cheats that patch code (Gun.Smoke's start round changes an
  operand) need the same patch in the translated instruction for a lock-step test.
* **The game's own test features**: Splatterhouse's Stage Select DIP switch starts every stage; seven seeds grew the
  main CPU's translation from 5247 to 7172 instructions.
* **Coverage that dies**: random play with invincibility (1943 seeds 6-20) never runs what dying runs; seeds 21-40 (play
  that dies, every start stage, faster input changes) found 1038 more bank/pc pairs, among them both Hatari crash
  targets.  Long runs through the whole game (R-Type: seeds 10-12 to 86000 frames) find what early stages never reach.
* **Jump tables behind a call** (`call T` with the words following it, T pops the return address) are found statically
  (`discover.py table_calls`).  Capcom's `ld hl,T; add hl,de; ld e,(hl); inc hl; ld d,(hl); ex de,hl; jp (hl)` tables
  have entries no coverage run reaches (1943's object types 10-14 at `59BC`): `discover.py hl_tables` finds the form,
  but in a banked program it also reads data as tables; 1943 names its fixed tables (`gen.py JUMP_TABLES`).  Check every
  translated `jp (hl)`: its table's entries (or, behind a byte table of offsets as in Gun.Smoke, the entries those
  offsets select) must all be translated.
* **Functions that return past the call** (`pop hl`, k x `inc hl`, `jp (hl)`, also across a `jr`): Capcom's allocators
  and the 8 / 4-byte compares (1943 `03C0`, Black Tiger `03B2`, Gun.Smoke `0365`) continue at call + 3 + k.
  `discover.skip_returns` finds them; a port adds them as roots and discovers again until none is missing.
* **`halt` goes on with the next instruction**: discovery used to end a flow there, so the code after a `halt` was
  translated only if coverage had reached it (Galaga restarted at the end of every game; Bubble Bobble's `11E6`,
  Commando's `2F4D` and 1942's `7953` fell into the wrong code).  `z80dis` gives `halt` the flow `seq` now.
* **Computed targets play rarely takes** (R-Type): object handlers stored as immediates (`mov word ptr
  [bp+0h],2D50h`) and called later, some only through ROM tables copied to RAM.  `games/rtype/tools/gen.py` takes them
  from the program: tables in ROM, stored handlers, every stored code address, code right after a RET nothing refers to
  ("plausible" = ordinary instructions up to a transfer, never starting inside covered code).
* **What the MARP replay found in Black Tiger**: `docs/window-sites.json` misses block copies (bank 0's `ldir` at
  `$AC71` copies a 32-byte template from the window: guard every block copy, the guard tests HL at run time);
  object-script handlers reached only through data tables (5-byte records, `00 lo hi` jumps to a handler: F030Arcade
  added ~50 roots, `games/blktiger/docs/main-roots-extra.json`); task starts `ld a,n / ld bc,entry / call $00F6` (BC is
  not followed as code: scan for `01 lo hi cd f6 00`, 29 sites).  The score is at `$E1E8`.
* **Unforeseen entries stop loudly**: a computed jump to a pc the analysis did not count as an entry ends at
  `z80_badpc` with the pc in d7 when the pc is inside a merge.  Make it a join (a table root or a hook).
* **Random play in Hatari** (keys through `--cmd-fifo`, a few minutes) finds what the coverage seeds did not; an
  AUTOPLAY build must not let the VBL copy the keyboard state into the inputs it scripts (the game then plays
  differently from the coverage run and reaches code it never saw).
* **Shorter coverage runs must not discard established guards** (1942, 1943's ROM-window sites); native continuation
  targets are explicit discovery roots even when a play seed does not take them (Double Dragon).
* **Self-tests flood the renderer** (video RAM test) and run ~700 frames: skip them in the reference and the
  translation, compensate any ROM checksum the game runs later, load the patched ROM files in the runtime; never use
  their frames as a performance reference.

## Translation

### Z80 (`engine/z80x.py`, `engine/translate.py`)

The register maps and the second pass are described in `architecture.md`, "Translator".  What a port's gen.py and
runtime have to keep:

* **gen.py**: go through `translate.compile_code()` (or `generate_program()`), not a copy of the steps: it does the flag
  liveness over calls, the CCR analysis and the second pass.  Pass the real entries as joins (reset, interrupts, hooks,
  jump table targets); making every pc the coverage saw a join (Commando did) switches the CCR analysis, the precise
  returns and the merges off.  A port with a banked window wraps its `aW` lines with `Emitter.window_wrap` and gives
  `ret_value` (the real address a call pushes) and `direct_ok` (no return points in the window) like Bubble Bobble.
  Give the configs `**z80x.FAST` (signed memory model) or `**z80x.FAST_LONG` (long model); `alt_af="upper"` alone where
  the runtime needs a0-a3.  Table generators leave out `em.no_entry` (z80_badpc there).
* **Runtime, d0 and d6**: A' is in bits 16-23 of d0, F' in the upper word of d6.  Code inside the translated context
  (hooks, write hook targets, natives) writes them as bytes / words only: `clr.w d6`, not `moveq #0,d6`.
* **Runtime, d1-d3 with FAST**: the upper words hold BC' DE' HL'; a runtime that reads an alternate register reads the
  upper word (Galaga's `g_ctrl06`: DE' is `move.l d2,d7; swap d7`).  IY is in a2 (its low word).  a0-a2 are the
  translated code's scratch registers (`ldir`); a runtime routine may use them but must not expect them to keep
  anything between instructions.
* **`moveq #0,dN` before `move.w x,dN`** when dN is then used as a long (an address offset, a cache key): the upper word
  holds whatever the caller left there (Black Tiger's characters disappeared when a new caller changed it).
* **The Z80 stack below SP is dead**: merged `push rr; pop rr'` does not write the word, inlined calls write no return
  address.  Lock-step tests compare the stack above SP only (and skip the 64 bytes below SP).
* **An interrupt's `push af` saves d6**, which need not hold the interrupted code's flags (they may be in the CCR): the
  pushed byte is not state, compare it only where the translation makes the flags exact.
* **Cooperative kernels** (1942): the arcade's interrupts come at arbitrary points of the tasks.  The VBL only raises a
  flag and the scheduler's idle hook (`$009A`) delivers the interrupts and draws; the Python reference has the same
  schedule.  An interrupt handler that hands the CPU to another task never returns to the token: the hook resets the
  68000 stack before it starts a handler.  The task contexts on the Z80 stack are data too: flags exact at `jp (hl)`
  and at hooks, `bit` setting S as the CPU does, and no scratch use of registers that tasks save.
* **P/V**: `jp pe/po` after logic ops is parity (d6 bit 7), tracked by the flag liveness; any other producer whose P/V
  is read stops the build with an `unsupported` entry.  `ldi; inc hl; jp pe` (Mr. Do! `$10C6`): `pv_block_before` looks
  back past `inc`/`dec` of HL, DE, IX, IY when no entry lands between.
* **H** is computed after `inc` / `dec` where it is read (a `daa` after `inc a`: Gyruss's frame counter).  `inc` /
  `dec (iy+d)` with H live in the block-IY layouts took its test byte from the wrong address until 2026-10-29
  (`xbench.py` had reported it; no port's code had the case).
* **The I register as data** (Pooyan: loop counters, `ld i,a` / `ld a,i`): `Config.iaddr`, an unused byte of the block;
  `ld a,i`'s P/V (IFF2) is not produced, so a reader of it stops the build.  `inc` / `dec` of IYH / IYL are translated.
* **Window reads through `(iy+d)`**: with `z80x.FAST` IY is the low word of a2 (the upper word is not 0), so a gen's
  window check must match `(a6,a2.w)` too and compare a copy of the word (`move.w a2,d5`).  z80x's `write8` takes its
  address from `read8(op, io_read=False)`: a gen that guards in `read8` also guards stores unless it tells them apart
  (`GSEmitter.storing`; fixed in Black Tiger's and Bubble Bobble's gens too).  1942's and 1943's gens still match
  `(a6,dN.w)` only (2026-11-07): an `(iy+d)` read at one of their window sites is not guarded.
* **Which window sites to guard**: only the coverage's, kept in `docs/window-sites.json` and audited
  (`logic_test.py --audit`); see `speed.md`, "Logic".
* **A frame-exact replay needs the Z80's time**: delivering the frame interrupt only when the task kernel idles runs
  each frame's work in zero time (Black Tiger's boot then left its random generator five frames ahead).  F030Arcade's
  cycle budget charged per translated block, with the interrupt taken mid-task (`scripts/cycle_budget.py`, PORTING.md
  "Original CPU time and recorded games"), fixes it.

### 6809, HD6309 and KONAMI-1 (`engine/m6809x.py`)

* `Program.opcode_reader` decodes encrypted opcodes (KONAMI-1: `lambda rd: konami1_opcode(rd)`).
* An indirect operand through a static pointer address (`[$4211]`) reads the pointer from the slot of its top bits;
  `Program.indirect_slots` names the target's slot where the coverage saw one besides the pointer's.  A flat program
  (no MMU) maps each slot to its memory in the context (Gyruss: slot 3 is the main CPU's shared RAM in the Z80 block).
* A page seen in two slots stops the build; natives keep the translation under `<label>_t`.
* **Test harnesses lie too**: a test of every instruction must make sure every opcode got tests (the first version
  filled one page and silently left out the rest); a stop address must not be `badpc + 2` when the next routine starts
  there; a move to memory spoils the flags a stub wants to record (save the SR first).

### V30 (`engine/v30x.py`, R-Type, Mr. HELI)

* **Little-endian words on the 68000**: the memory with the bytes of every word swapped.  Words at even addresses are
  native moves (R-Type reads 45 words for every byte), a byte at a register address costs `moveq #1,d7; eor.w dX,d7`.
* **Liveness through computed calls**: a RET reached only through a computed call or a jump table had no return
  points and counted as reading every flag (1055 wrapped instructions; 117 once those RETs got the return points).  The
  flags the computed-target callers read cost ~10% more cycles: correct, not waste.
* **Returns without the flags**: a table of 64K longs indexed by the popped IP (`move.w (a5)+,a0`, two `add.l a0,a0`)
  jumps without touching the CCR.
* **The port's schedule changes the game**: the VBL handler always runs to completion (MAME's game skips its logic when
  a frame overruns), so long runs reach states MAME-scheduled coverage never saw; a stale object pointer (seed 9, frame
  ~26900) reads unmapped memory, which the arcade reads as 0 and the image as what was written.
* **MCUs that patch the main program** (Mr. HELI's i8751): after the boot a native model exact at every V30 read; the
  boot is not (the MCU places code at an address set by the cycle it saw the V30's write), so the port starts from a
  snapshot after frame 484.  The protection command and the call into the code it copies need a frame between them.

### Natives

The mechanism is in `architecture.md`, "Native replacements"; where they pay is in `speed.md`.  Correctness:

* Each native is tested against the translation it replaces (random states: memory, registers, live flags) besides the
  lock-step test, and over the whole game: R-Type's collision broad phase was wrong only in stages 7 and 8.
* **A native that hands back to the translation needs its own flag check.**  `em.live_in` is not that check (nearly
  every pc shows live flags, since rets reached from coverage seeds count as reading them).  For a native's exits redo
  the liveness over `em.code` with a `ret` that reads nothing and ends the path, a call followed into its callee and on
  at its return point, `push af` / `pop af` carrying F; check the continuations' real return pcs as well as the targets,
  and stop the build if one reads a flag (F030Arcade `games/bublbobl/scripts/generate.py` `tick_liveness`).  F030Arcade
  `PORTING.md` ("Callouts"): a token return address whose dispatch entry is the native's continuation lets a native
  call a rare translated routine and get control back.
* Interrupt-time loops whose flags reach the interrupted code (1943's timer loop through `ex af,af'`) are no easy
  natives.

### Checking a translator change

`engine/xbench.py` (every Z80 opcode and random sequences in every memory layout), `engine/m6809x_test.py`,
`engine/v30x_test.py`, the ports' lock-step tests, for Galaga `engine/xdiff.py` against the build before the change.
`engine/xprof.py <game>` and the 6809 / V30 ports' `tools/profile.py` say where the cycles go per arcade instruction.

## The STE, the simulator and Hatari

* **Musashi is not a 68000 for faults and timing**: it executes odd word accesses silently (Hatari takes an address
  error) and has no MFP timers or border removal.  Test for odd accesses (`games/bublbobl/tools/align_test.py`), build
  the simulator variant with `-DSIM`, start every BSS block of new code with `even` and pad odd-sized arrays before word
  data (Gyruss's `snd_ym_new` after a 5-byte array; Bubble Bobble's `clr.w` at `bb_ssg+9`).  Crashes only in Hatari have
  been: stack overflow by nested VBLs, window-read sites coverage missed, odd word loads in translated MCU code.
* **The simulator's Blitter follows Hatari** (`blitter.c`, "as on real blitter"): with NFSR the last source read of a
  line is skipped and the source **Y** increment is added after the read before it (until 2026-10-25 `engine/sim.py`
  added X).  A simulator fix breaks renderers that relied on the old behaviour: ddcec89 left Galaga '88's 3-word sprite
  passes (SYI 0: 623 of 750 play pictures wrong) and Splatterhouse's opaque fast rows wrong until 769c6fb.  After any
  change to the simulator's Blitter, run every port's render test.
* **Code that reads Blitter registers back** needs `Sim(ram_kib=16384)` (with 4 MB the reads return 0 and sprites land
  elsewhere, in Commando on the stack).
* **A macro must not be named like a vasm directive** (Gyruss: a macro `LIST` expanded to nothing, silently; `vasm -L`
  showed it).  Branch-out-of-range and `lea` displacement warnings are normal at this size; real errors stop the build.
* **Never let a pending VBL nest**: Timer A lowering the IPL can let one nest 28 deep (an `in_logic` flag); throttle
  the logic when it cannot keep up so the renderer still runs (`architecture.md`, "Runtime schedule").
* **Hatari scans the old ring out once more**: after the video base is written at the VBL, the frame that starts still
  shows the ring shown before; drawing into the ring just flipped away from tears the lower half.  Draw into a ring
  that was neither shown nor waiting during the last frame (three rings at 50 pictures a second).  Look with a
  recording (`tools/record.sh`, ffmpeg, a frame at a time).
* **Publish a finished picture with one store**: the VBL runs between any two instructions; a ring index and a ready
  flag written one after the other can be seen half done (a draw ring 3 and a crash far away).  One byte = ring + 1.
* **Only short HOG passes** (the rule of stefastbobs2): the border interrupts may come at any moment of the
  foreground, and a HOG pass holds them back until it ends; a pass without HOG runs on during the interrupts and
  stretches the timed code that opens the borders (Commando's margin clear was one).  `blit_go` (`engine/rt/borders.s`)
  cuts every pass into pieces of at most ~256 bus cycles (32 words of a copy, 16 when the op reads the destination) and
  a wider line into column strips; `blit_go_copy` / `blit_go_fill` for known full-mask copies and HOP 0 fills.  HOG
  passes also delayed Timer A's palette switches and, across the VBL, the handler that arms Timer A (the picture
  dropped for a frame); changing the top border routine's instructions moves the palette switches: keep its cycle
  count.  A 768-line, 56-word copy hung Hatari for good.  Check with `BLIT_STATS=256` (`engine/sim.py` lists every HOG
  pass over 256 bus cycles and every pass without HOG) after each renderer change, and `python
  engine/borders_blit_test.py` (`--copies-only --entry blit_go_copy`, `--fills-only --entry blit_go_fill`) after a
  change to the splitter.  Look at several frames of Hatari's own screenshot (RightAlt+G), not one.
* **The Mega STE** (16 MHz, cache on) has its own border pulse path: `megaste-border-timing.md`.
* **`tools/hatari.sh` stops every running `hatari` first**: two sessions benchmarking at once kill each other's runs.
  Benchmarks start their own Hatari (`bench.sh`; `HATARI` may name a renamed copy of the pinned build).
* **An arcade program may reject a coin held too long** (1942 ignores one of 40 ticks): tap the coin key in scripts
  (`tools/hatari.sh tap:5@20`).
* **Headless Hatari debugger screenshots may be black** while the guest framebuffer holds a valid picture: decode the
  game's buffer (pointer, stride, palette); that does not check scanout or border timing.

## Renderer correctness

* **The hardware window and the arcade picture are different bounds** (`AGENTS.md`): pixels outside the hardware
  window are hidden; side bands inside it stay visible (the STE shows 48 pixels on each side of a 224-pixel picture).
  Reserve a wider virtual screen and vertical guard rows for shifted objects, and restore each draw buffer's old
  damage, guards included, before drawing again.  Never clear newly drawn overhang to imitate arcade clipping.
* **Side edges on 16-pixel group boundaries** (since 2026-10-12; the old no-clipping rule is superseded): cull sprites
  wholly outside, draw only the inner destination word of a crossing sprite (its prepared end mask, an outer end mask of
  0 or a one-word pass), compute no other edge mask, erase nothing after drawing.  This applies to every sprite path,
  generic, cache-miss and 64 KB fallbacks included.  Top and bottom: whole sprites into guard rows.  Where a side edge
  falls inside a group, draw whole into margins; ports with moving windows may clip at the surrounding full band words.
  The eight ports measured on 2026-10-12 (Musashi, before -> after clipping): 1942 -0.004% a tick, 1943 +0.02-0.04%,
  Black Tiger -0.05..+0.06%, Bubble Bobble cheaper overall, Commando +0.04%, Donkey Kong +0.03%, Galaga -0.17%,
  Gun.Smoke -0.10%.
* **Verify** all four edges, all 16 shifts, transparent holes, priority, 64 KB address crossings and consecutive
  pictures against an independent reference.  Test the margins too: every set pixel outside the arcade picture must
  belong to a sprite drawn now (Bubble Bobble's `render_test.py`); a negative run (the guard restore disabled) shows
  that the check bites.  Test with the whole sprite list, not single parts (1942's list decoding once used `d4` and
  drew garbage only with several entries).
* **Tests that do not depend on private data**: Double Dragon's sprite test defaults to its canonical recorded play;
  `--seed 1` supplies a reference scenario when that private recording is absent (a supplement, not a replacement for
  replay or full-game coverage).  Gauntlet's renderer harness generates its fixed address map independently of the
  program patcher's coverage.
* **Test windows that wrap**: the first 1942 renderer test passed for 1000+ frames and the wrapped half of the scroll
  ring was never drawn (a window position T > 256 hid a garbage upper register word).  Sweep the whole range of a
  scroll register; with a horizontal hardware scroll a line pair that comes into the band must get black side bars (a
  test with 25 spaced frames passed, one with 40 found it).
* **Change detection must not miss a writer**: where translated writers set dirty flags (`speed.md`), the lock-step
  test checks that every change of the region came with its flag, the renderer rescans a few hundred bytes a frame in
  case one is missing, and the game's own state stays exact (the game reads its map for collisions: Black Tiger's bank switch
  keeps both background banks addressable).
* **Mandatory (user, 2026-10-24): no AND + OR Blitter pass pairs** for anything drawn over a background; masked
  graphics are HOP 2 / OP 3 copy passes with the opaque pixels as end masks (`AGENTS.md`, `sprite-preparation.md`).

## Sound

### FM music as square waves (Commando, 2026-10-11; the other Capcom boards have the same YM2203s)

* **`engine/opn.py`** turns a sound driver's YM2203 register writes into what a YM2149 can play: per FM channel the
  pitch of its carriers and their loudness through the envelope generator (MAME's ymfm: rates, key scaling, sustain
  level, total level; the modulators only shape the timbre and are left out).  Mind the prescaler the driver selects
  ($2D/$2E/$2F): it sets the FM rate (clock / 72, / 36, / 24) and the SSG clock.  ymfm's attack step relies on C's `~`
  of a promoted int (`att += (~att * inc) >> 4`): with `~att & 0x3FF` in Python the attack never leaves full
  attenuation.  `engine/opl.py` does the same for Bubble Bobble's YM3526, `engine/opm.py` is planned for R-Type's YM2151.
* **Record with the STE's interrupt timing, not the arcade's.**  The arcade's sound CPU loses an IRQ when a handler
  runs longer than the gap to the next; a driver that does part of its work on odd counts then drifts against its own
  loop.  The STE runs the IRQs of a tick back to back, so record that way and the tunes become periodic; their tempo
  still matches MAME's audio.
* **A repeat of a channel's RAM is a loop only if it keeps repeating**: check it over a whole period more (Commando's
  channels repeated their 32 bytes after 24 ticks and then parted).
* **Six channels on three**: pick the loudest each tick (prefer the ones that played the tick before, keep each on its
  YM channel), after the effect has taken the channels it sounds on; per-channel streams loop independently, so the
  choice is made at run time.
* **Check the pitch against MAME's audio**: poke the sound latch from a Lua script (`space:write_u8` goes through the
  handlers) and `-wavwrite`; correlate semitone spectra of both.

### Recorded sound for every port (2026-10-11)

Commando's method (record the sound driver's output per command, play it in the driver's own scheme) is shared:
`engine/capsnd.py` (a driver described by its addresses: the board, the recordings, the models, the checks, the data
of `engine/rt/capsnd.s`), `engine/rt/capsnd_core.s` (the stream decoders and the mixer, also used by Black Tiger's and
Bubble Bobble's own players).  Ports with a small sound CPU translate it instead and map its chips onto the YM and the
DMA sound (Pac-Man's WSG, Pooyan's and Gyruss's AYs, Mr. Do!'s SN76489s, Moon Patrol's and Kung-Fu Master's M6803,
Track & Field's and Hyper Sports' SN76489A with speech on the DMA); see the READMEs.

* **Find the driver's facts by running it, not by reading it**: which commands stop which slots (run every handler on a
  board whose slots are all marked busy), which chip parts a command uses (log the writes of each command alone).
* **Check the model against the real driver, then the 68000 player against the model.**  Compare what sounds: a
  channel with tone and noise off is silent whatever its period and volume (`capsnd.audible`); start the model's IRQ
  counter where the driver's boot left it.  What is left are real limits of recording each command alone (a noise
  period an effect inherits from the one before; an FM envelope carried over), counted in the READMEs.
* **Drivers differ in the details**: Gun.Smoke's and 1943's end the lower effect slots under the shown one unless a byte
  of theirs is $FF; Black Tiger's (timer-driven, ~250 Hz) has priorities, one effect slot a chip and a main / backup
  tune; Bubble Bobble's (Taito) has 26 tracks, two per channel, the A track winning, and a tempo the tunes change:
  record that one in real time, and find loops on the chip writes of the driver's timer ticks, per timer.
* **Long effects and big tunes**: an effect that repeats a period for minutes keeps one period with a loop and a total
  (`compact`); tunes for a 250 Hz player pack 3x with a byte LZ (`engine/lz.py`, `rt/lz.s`): unpack when a tune starts,
  in the idle hook, not in the VBL.  Phase exceptions above 8 KB are dropped (`capsnd.EXC_LIMIT`).
* **Pitfalls**: a recording of a few seconds says nothing about a game whose attract mode is silent for its first 25 s
  (Black Tiger): look at the reference's commands before calling Hatari silent; a driver may read back the SSG
  registers or wait for the second chip's timer at boot (Bubble Bobble); a game's asset builder may put another game's
  tools first in `sys.path` (1943's: 1942's `sound.py`; Gun.Smoke binds its own sound module first).  On Windows sound
  recording uses bounded `spawn` workers (`CAPSND_WORKERS`, default 4); `OPENBLAS_NUM_THREADS=1` helps when generating
  assets alongside other builds.

## Memory and release

* **The load budget** (2026-10-15): a program asks TOS for at most 3,700,000 bytes (text + data + BSS + 256;
  `tools/release.py` refuses more, R-Type is deferred through `OVER_LOAD`).  TOS 2.06 alone leaves 4,061,212 bytes from
  the desktop on a 4 MB STE (`tools/memfree.sh`), but a tester's Mega STE with a hard disk driver and accessories had
  3,831,554, and five ports at 3.93-4.05 MB would not start.  What brought them to 2.94-3.67 MB without changing what
  the games do:
  - dispatch tables built as data at assembly time, not BSS filled from entry lists: a word per arcade address, (the
    entry - the table or a region's base) / 2, the table in the text before its code so the jump is relative (1943,
    Black Tiger: 448 / 640 KB of long tables; 1943's banks as pages, a directory long per 64 addresses, 104 -> 50 KB);
  - ROMs assembled where the translated code reads them instead of copied there; what the start reads once anyway (ROM
    images, entry lists) placed under a buffer not used until later, the data's end aligned to the BSS so the two meet
    (the start checks it; 1943 and Black Tiger put their dispatch entry lists last in the data section this way);
  - per-pen masks (a word per pen per row) became the arcade's bit planes (Commando bakes a row through a routine per
    colour; 1942's tiles get their masks from `engine/rt/penmasks.s`);
  - shared row orders and Blitter routines of an image and its mirror image, equal plans stored once, caches sized to
    their measured use (1942), the 68000 stack to what it uses (1943: 8 KB).
* **A smaller layout can be slower on the bus**: 1943's front_map as words saved 30 KB, equal in Musashi, 1.5-3% fewer
  frames in Hatari.  Memory buys speed on the 14 MB development machine (R-Type's pre-coloured sprites and recorded
  strips); the release's load limit is solved later (per-stage loading, packing, `engine/rt/hdd.s`).
* **Floppy disks** (2026-10-28): `tools/release.py` packs each program with LZ4 (`tools/lz4prg.py`, `lz4 -12`) behind a
  0.9 KB stub (`tools/lz4stub.s`) in the AUTO folder of a bootable 720 or 800 KB image (`tools/stdisk.py`) when it
  fits (12 ports; not Black Tiger, 1943 or Double Dragon at 0.99-1.26 MB packed).  The stub unpacks in place: the packer
  simulates the depacker byte for byte and moves the frame only as far up as the output never overtakes it (~920 bytes
  more than the program; `tools/lz4prg_test.py` runs the stub on Musashi for every port).  4.4-12.7 s at 8 MHz, a VBL
  handler draws the progress bar from the depacker's output pointer; the lengths are longs (matches over 64 KB exist).
  From a floppy's AUTO folder TOS 2.06 leaves 4,108,870 bytes, so R-Type (3.85 MB) starts there.

## Two related projects compared (2026-10-11)

Read, not built or run: `stedaimakaimura` (Daimakaimura, Capcom 1988, an STE / Falcon test from 2017-2020) and
F030Arcade's spare-time renderer (`PORTING.md` there).

* **A 68000 board needs no translation.**  Daimakaimura's program is a traced disassembly reassembled at its own
  addresses: the inputs, the CPS-A/B registers, the graphics RAM and the work RAM are labels in STE RAM, the arcade's
  vectors point to the STE's handlers, and the part that overlaps the TOS system variables moved behind `jmp` stubs.
  Gauntlet does the same with its MC68010 program, patched in place.
* **Patches instead of the arcade's code**: `relocate_rom.js` lists the words in which the assembled program differs
  from the ROM; the program loads the user's ROM files and applies the list.  An alternative to self-contained programs.
* **Its sprite renderer is this project's** (a Blitter copy per run of a line, the end masks as the mask), but its
  sprites were grabbed from the running game, so a sprite never seen is not drawn; the ports here bake from the ROMs.
* **Its colours**: nearest colour in CIELAB plus checkerboard mixes of close pairs (`colours.md`).
* **"The frame is done"**: Daimakaimura patches the game's task scheduler (all tasks idle -> `request_next_frame`); the
  VBL handler draws until Timer B says the beam is close and resumes at the next VBL.  F030Arcade generalises it: the
  VBL shows a completed page, runs one game step and asks for a picture; Timer B starts or resumes the renderer on its
  own stack once the game is parked; an overloaded renderer drops pictures, never logic.  The park test is per board,
  and parking a wait loop can lose a side effect (DoDonPachi's loop advanced a random index).  Here the frame is the
  interrupt handlers (`architecture.md`, "Runtime schedule"); the ports whose foreground does work (Galaga's main CPU
  draws text before it idles; 1942's kernel) are the open cases.

## The port's README (2026-11-07)

Every `games/<game>/README.md` has the same sections in this order (one left out when it has nothing): the title
`<Game> (<maker>, <year>) on the Atari STE`, the screenshot, a summary of the current state (the MAME set; each CPU
and how it is handled; the status as in the root README's table; the latest speed with its date and setup), **Build
and run**, **Controls**, **State** (what is verified, what is missing), **How it works** (the board and the
reference, translation, schedule, picture, sound), **Speed** (the current figures first, then what made it fast,
then what was measured and not kept), **Tests and tools**, **Lessons** (dated findings, pitfalls and experiments
worth knowing), **Verification** (the port's own playtest evidence, the PPO command if it has a profile, a link to
the [status policy](port-status.md)).  The current state comes first; history stays only where there is something
to learn from it (the user, 2026-11-07): superseded figures and states without a lesson are removed.  Terms:
"arcade frames a second" for the logic, "pictures a second" for the frames drawn, dates as YYYY-MM-DD.

## Port completion claims

Automated exploration can attempt full progression once a port's adapter and native replay transport are verified;
success is not guaranteed by agent support.  The [status and full-game verification policy](port-status.md)
distinguishes natural completion, assisted coverage and incomplete verification; green **Complete** is reserved for
verified Hatari playability with graphics and sound.
