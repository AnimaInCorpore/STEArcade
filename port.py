#!/usr/bin/env python3
"""One entry point for the ports.

    port.py list
    port.py prepare <game>                 verify and unpack a newly added ROM set
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
    "1943": [("ref/cover.py", list(range(1, 21)), 20000)],     # 4-5: attract, the test inputs; 6-20: cheats, one stage each
    "commando": [("ref/cover.py", [1, 2, 3], 12000)],
    "gunsmoke": [("ref/cover.py", list(range(1, 15)), 20000)],    # 4-14: cheats, one round each
    "dkong": [("ref/cover1.py", [11, 12, 13, 14], 60000), ("ref/cover2.py", [21, 22, 23, 24], 40000),
              ("ref/colors3.py", [31, 32, 33], 30000)],       # the last one finds the palette pens
    "galaga": [("ref/cover.py", [1, 2, 3], 20000)],
    "bublbobl": [("ref/cover.py", [1, 2, 3, 4, 5, 6], 20000)],
    "1942": [("ref/cover.py", [1, 2, 3, 4, 5, 6, 7, 8], 60000)],     # 5-8: with MAME's cheats (later stages)
    "blktiger": [("ref/cover.py", [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11], 20000)],   # 4-11: cheats, one stage each
}
# tests: command lines (relative to games/<game>), {n} = the frames argument
TESTS = {
    "1943": [("tools/prepare.py", [], None), ("tools/video_test.py", [], None),
             ("tools/reference_test.py", ["700"], None),
             ("tools/build.py", ["--sim"], None),
             ("tools/logic_test.py", ["{n}"], 3000),
             ("tools/logic_test.py", ["3000", "--render", "--every", "3"], None),
             ("tools/logic_test.py", ["4000", "--render", "--every", "4", "--cheat", "13"], None),   # front layer scrolls sideways
             ("tools/logic_test.py", ["4000", "--render", "--every", "8", "--seed", "1"], None)],
    "gunsmoke": [("tools/reference_test.py", ["700"], None),
                 ("tools/build.py", ["--sim"], None),
                 ("tools/logic_test.py", ["{n}"], 3000),
                 ("tools/logic_test.py", ["4000", "--seed", "9"], None),     # MAME's cheats: round 6
                 ("tools/render_test.py", ["40", "seq", "--first", "1500"], None),
                 ("tools/render_test.py", ["20", "scroll"], None),
                 ("tools/render_test.py", ["4", "edges"], None)],
    "commando": [("tools/reference_test.py", [], None),
                 ("tools/build.py", ["--sim"], None),
                 ("tools/logic_test.py", ["{n}"], 3000),
                 ("tools/render_test.py", ["20", "scroll"], None),
                 ("tools/render_test.py", ["4", "edges"], None),
                 ("tools/sfx_test.py", ["{n}"], 1000)],
    "blktiger": [("tools/build.py", ["--sim"], None), ("tools/reference_test.py", ["700"], None),
                 ("tools/logic_test.py", ["{n}"], 1600),
                 ("tools/logic_test.py", ["4000", "--walk"], None),
                 ("tools/render_test.py", ["--frames", "3", "--step", "375", "--scroll-sweep", "--flip-layout-sweep", "--sprite-edges"], None)],
    "dkong": [("tools/fullrun.py", ["{n}"], 3000)],
    "galaga": [("ref/galaga5.py", ["{n}"], 3000)],
    "bublbobl": [("tools/mcu_test.py", ["{n}"], 2600),
                 ("tools/build.py", ["--sim"], None),
                 ("tools/logic_test.py", ["{n}"], 700),
                 ("tools/render_test.py", ["seq", "1500", "20"], None),
                 ("tools/align_test.py", ["{n}"], 900)],
    "1942": [("tools/build.py", ["--sim"], None),
             ("tools/logic_test.py", ["{n}"], 6000),
             ("tools/logic_test.py", ["9000", "--cheat"], None),      # MAME's cheats: the later stages
             ("tools/sprite_test.py", [], None),
             ("tools/render_test.py", ["seq", "200", "1", "1200"], None)],
}
MAME = {"1943": "ref/mame_cmp_1943.py", "commando": "ref/mame_cmp_commando.py", "gunsmoke": "ref/mame_cmp_gunsmoke.py", "blktiger": "ref/mame_cmp_blktiger.py", "dkong": "ref/mame_cmp_dkong.py", "galaga": "ref/mame_cmp_galaga.py", "bublbobl": "ref/mame_cmp_bublbobl.py",
        "1942": "ref/mame_cmp_1942.py"}
PREPARE = {"1943": "tools/prepare.py", "gunsmoke": "tools/prepare.py", "blktiger": "tools/prepare.py", "commando": "tools/prepare.py"}
GAMES = sorted(set(COVER) | set(PREPARE))


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
    if cmd == "prepare":
        if game not in PREPARE:
            print("no preparation command for", game)
            return 2
        return call([PY, game_script(game, PREPARE[game])] + rest)
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
        if game not in MAME:
            print(game + ": MAME renderer comparison is not implemented yet")
            return 2
        return call([PY, game_script(game, MAME[game])] + rest)
    print("unknown command", cmd)
    return 2


if __name__ == "__main__":
    sys.exit(main())
