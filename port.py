#!/usr/bin/env python3
"""One entry point for the ports.

    port.py list
    port.py cover  <game> [seeds ...]        coverage runs the translator is seeded from (parallel; ~15 min for dkong)
    port.py build  <game> [build.py args]    translate + assemble + link -> run/<game>/   (--sim: the simulator build)
    port.py test   <game> [frames]           the tests that compare the build with the reference machine
    port.py run    <game> [item@s ...]       Hatari (tools/hatari.sh): screenshots, key presses, memory dumps
    port.py mame   <game> [frames ...]       reference renderer against MAME's own picture (needs `mame`)

The python is the repository's venv (venv/bin/python) when it exists.  Everything it starts is a plain script in
games/<game>/tools or ref (see games/<game>/README.md); this file only knows the order and the arguments.
"""
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PY = str(ROOT / "venv" / "bin" / "python") if (ROOT / "venv" / "bin" / "python").exists() else sys.executable

# coverage: (script, seeds, frames) groups; the pickles land in build/<game>/
COVER = {
    "dkong": [("ref/cover1.py", [11, 12, 13, 14], 60000), ("ref/cover2.py", [21, 22, 23, 24], 40000),
              ("ref/colors3.py", [31, 32, 33], 30000)],       # the last one finds the palette pens
    "galaga": [("ref/cover.py", [1, 2, 3], 20000)],
    "bublbobl": [("ref/cover.py", [1, 2, 3, 4, 5, 6], 20000)],
}
# tests: command lines (relative to games/<game>), {n} = the frames argument
TESTS = {
    "dkong": [("tools/fullrun.py", ["{n}"], 3000)],
    "galaga": [("ref/galaga5.py", ["{n}", "/tmp"], 3000)],
    "bublbobl": [("tools/mcu_test.py", ["{n}"], 2600),
                 ("tools/build.py", ["--sim"], None),
                 ("tools/logic_test.py", ["{n}"], 700),
                 ("tools/render_test.py", ["seq", "1500", "20"], None),
                 ("tools/align_test.py", ["{n}"], 900)],
}
MAME = {"dkong": "ref/mame_cmp_dkong.py", "galaga": "ref/mame_cmp_galaga.py", "bublbobl": "ref/mame_cmp_bublbobl.py"}
GAMES = sorted(COVER)


def game_script(game, rel):
    return str(ROOT / "games" / game / rel)


def call(cmd, cwd=None):
    print("+", " ".join(cmd), flush=True)
    return subprocess.run(cmd, cwd=cwd).returncode


def main():
    a = sys.argv[1:]
    if not a or a[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    cmd = a[0]
    if cmd == "list":
        for g in GAMES:
            print(g)
        return 0
    if len(a) < 2 or a[1] not in GAMES:
        print("usage: port.py %s <%s> ..." % (cmd, "|".join(GAMES)))
        return 2
    game, rest = a[1], a[2:]
    if cmd == "build":
        return call([PY, game_script(game, "tools/build.py")] + rest)
    if cmd == "cover":
        jobs = []
        for script, seeds, frames in COVER[game]:
            for s in (int(x) for x in rest) if rest else seeds:
                jobs.append([PY, game_script(game, script), str(s), str(frames)])
        with ThreadPoolExecutor(max_workers=os.cpu_count()) as ex:
            codes = list(ex.map(lambda j: call(j, cwd=ROOT), jobs))
        return max(codes)
    if cmd == "test":
        for script, args, default in TESTS[game]:
            n = rest[0] if rest and default is not None else str(default)
            args = [x.format(n=n) for x in args]
            rc = call([PY, game_script(game, script)] + args)
            if rc:
                return rc
        return 0
    if cmd == "run":
        return call([str(ROOT / "tools" / "hatari.sh"), game] + rest)
    if cmd == "mame":
        return call([PY, game_script(game, MAME[game])] + rest)
    print("unknown command", cmd)
    return 2


if __name__ == "__main__":
    sys.exit(main())
