# STE Donkey Kong Blitter work from `codex/blitter-renderer-optimizations` (commit f95bb40)

Kept verbatim when that branch was merged with `origin/master`, which had since restructured the repo
(`ste/` -> `engine/`, `games/<game>/`) and rewritten the Donkey Kong sprite renderer independently
(`engine/sprite_codegen.py`, `games/dkong/src/sprites.s`). The two `sprites.s` files were different
implementations, so upstream's won in the tree; nothing here is built or tested in the new layout.

* `rt/sprites.s`, `tools/sprites.py`, `tools/sprite_observed.json` — that branch's sprite renderer and its generator.
* `tools/check_render_perf.py`, `tools/prof.py` — perf checks written against it (use the old `sim.py`/`build.py` APIs).
* `blitter_renderer_performance.md` — the investigation notes (ranked improvements, e.g. restore/track two chunks
  instead of three); whether upstream's renderer already has them has not been checked.
* `f95bb40-edits-to-existing-files.patch` — the commit's changes to `render.s`, `dkong.s`, `sim.py`, `assets.py`,
  `build.py`, `dkong.py`, against the old paths.

The commit itself is in git history (`git show f95bb40`).
