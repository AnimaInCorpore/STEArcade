# Scratch scripts from the old `ste/` layout

Throw-away debugging scripts and logs from the Donkey Kong STE port, written before the repository was restructured
into `engine/` and `games/<game>/`. Committed as found; they import the old module names (`dkong`, `sim`, `rt/render.s`)
and expect the old `ste/build`, `ste/run` folders, so they do not run in the current tree.

* `ref/run4.py`, `ref/shapes1.py` — reference-machine runs and sprite-shape counting (`sprites1_4*.log` are shape-count outputs).
* `ref/simdbg1-3.py` — poking the simulated `DKSIM.PRG`.
* `tools/prof2.py` — PC sampling of the VBL handler; `tools/rcheck.py` — simulated screen against the reference renderer;
  `tools/simplay.py` — coin/start script with screenshots; `tools/patch_render.py` — one-off rewrite of `rt/render.s`.

The current equivalents live in `games/dkong/{tools,ref}`.
