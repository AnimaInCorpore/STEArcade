# MAME reference

- Authoritative MAME (user, 2026-10-29), for every port: the source tree
  `C:\Arbeit\F030Arcade\third_party\jsm68kdisassembler\third_party\mame` (MAME 0.286 with local telemetry patches).
  Read drivers, palettes, resistor networks and devices there, not in other copies (`F030MXDRV`, `mamesrc`,
  `F030Arcade\third_party\mame`) or GitHub. Where a MAME binary (0.289, WolfMAME 0.162) disagrees with this source,
  the source wins: note the difference in the port's README. The `m68k.exe` beside it is a 0.286 build without
  most arcade drivers (no `dkong`/`dkongjr`).

# STEArcade renderer rules

These rules apply to every game port and every sprite fallback path.

- Clip sprites at the picture's left and right edges where those edges lie on
  16-pixel group boundaries (the old "never clip" rule is deprecated, 2026-10-12:
  measured in all eight ports, clipping keeps the sprite drawing speed and
  leaves the visible side bands clean). Draw only the inner destination word of a
  sprite across such an edge: its end mask from the prepared masks (an end mask of
  0, or a one-word pass), no other edge-mask computation, no erasing after drawing.
  Cull sprites wholly outside. Top and bottom: whole sprites into guard rows. Where
  an edge is not group-aligned, draw whole into margins as before.
- Distinguish the hardware display window from the arcade picture inside it:
  pixels outside the hardware window are hidden automatically; side bands within
  the hardware window are still visible. Restore old sprite damage before drawing
  the next picture, including damage in guard areas. Exception (user, 2026-10-31): R-Type's stage renderer
  never shows its guard rows (the display address always skips them), so it draws sprites into them and never
  erases them; its erase rectangles cover only the visible lines (`games/rtype/src/stage.s`).
- Try the reordered-source method from stefastbobs2 for every game's sprites:
  group rows with identical opaque masks, prepare shift masks, reuse Blitter state
  and advancing source addresses. Preserve transparent holes and priority order.
  Measure CPU plus Blitter bus cycles before retaining an optimization. The full
  preparation (opaque runs, chains, mask order, reordered source, generated code per
  shift) and each port's result are in `docs/sprite-preparation.md`: prototype it and
  measure, do not decide from estimates; add your port's result there. For 16-pixel-wide
  rows use `engine/sprite_programs.py` (Time Pilot): rows grouped by mask, a one- or
  two-word pass per row and shift as stefastbobs2 chooses it (each row baked aligned in its source word with its own skew: no FXSR; NFSR for straddling rows), code per shape
  and pass-type pattern with the end masks streamed from an address, both shared by content.
- Mandatory (user, 2026-10-24): no AND + OR Blitter pass pairs (a mask pass with OP 1 or 4,
  then an OR pass with OP 7) for anything drawn over a background: sprites, text,
  front layers. Draw masked graphics the stefastbobs2 way: HOP 2 / OP 3 copy passes
  whose end masks are the opaque pixels, pieces of one or two destination words, all
  four planes in one pass (destination X increment 8, Y count 4, the destination Y
  increment back to the next plane), the planes stored in pass order so the source
  address runs on, the shift in the pass (skew, NFSR: a piece of c words covers c + 1
  destination words) and only the registers that change written between passes.
  Prepare per image (or text run) when it changes, at build time or on first use.
  Text is drawn like sprites (Black Tiger, Gun.Smoke: `text_run_pieces`,
  `fg_pieces_build`). The M72 front layer still uses AND + OR and is to be converted;
  see `docs/sprite-preparation.md`.
- Use short HOG Blitter passes, at most 256 bus cycles, with the shared early,
  synchronized border handlers. Verify timer timing in the pinned Hatari build.
- Verify sprites at every edge (clipped or whole), all 16 horizontal shifts, transparent holes,
  and 64 KB address crossings, as well as consecutive game frames against the
  independent reference renderer. Keep logic speed and picture rate separate in
  performance reports.

See `docs/architecture.md` and `docs/porting-guide.md` for the runtime contracts.

# Gameplay exploration

- Use the shared `port.py ppo <game> train|record|verify|test` workflow for new PPO exploration; see
  `docs/ppo.md`. Add explicit per-game RAM/input profiles and test their native replay transport before use.
- Preserve the count/SYSTEM/P1 replay contract, curated coverage scripts and canonical fixtures. A short PPO
  integration test is not full-game coverage or lock-step reference/render equivalence.
- Keep snapshots compressed and private emulator builds temporary. Retain small reports and usable checkpoints;
  avoid downloading language-model weights for this workflow.
- Galaga runs its real 51XX (namco51.zip, translated by engine/mb88x.py) since 2026-10-21; the 54XX's explosions
  are still simulated. Never substitute blank MCU ROMs for gameplay. It has no PPO profile yet.
- Before a new PPO profile or a longer search recording, consider Go-Explore (`docs/go-explore.md`): a cell
  archive over `playbot.py`'s snapshot/restore and segments reaches side paths and deep states that PPO and the
  forward-only progress search miss.
