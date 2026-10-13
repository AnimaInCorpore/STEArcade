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
  the next picture, including damage in guard areas.
- Try the reordered-source method from stefastbobs2 for every game's sprites:
  group rows with identical opaque masks, prepare shift masks, reuse Blitter state
  and advancing source addresses. Preserve transparent holes and priority order.
  Measure CPU plus Blitter bus cycles before retaining an optimization. The full
  preparation (opaque runs, chains, mask order, reordered source, generated code per
  shift) and each port's result are in `docs/sprite-preparation.md`: prototype it and
  measure, do not decide from estimates; add your port's result there.
- Use short HOG Blitter passes, at most 256 bus cycles, with the shared early,
  synchronized border handlers. Verify timer timing in the pinned Hatari build.
- Verify sprites at every edge (clipped or whole), all 16 horizontal shifts, transparent holes,
  and 64 KB address crossings, as well as consecutive game frames against the
  independent reference renderer. Keep logic speed and picture rate separate in
  performance reports.

See `docs/architecture.md` and `docs/porting-guide.md` for the runtime contracts.
