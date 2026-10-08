"""Golden-frame regression for the host reference: hashes of rendered frames per ROM set.

usage: python bbgolden.py           (compare with docs/golden.json)
       python bbgolden.py --update  (rewrite it)
Frames are the 256x224 RGB output of bbvideo.Renderer, no input applied.
"""
import hashlib
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from bubble import Bubble          # noqa: E402
from bbvideo import Renderer       # noqa: E402

FRAMES = (300, 900, 1400)
GOLDEN = os.path.join(HERE, "..", "docs", "golden.json")


def run(variant):
    b = Bubble(variant=variant)
    r = Renderer()
    out = {}
    for f in range(1, max(FRAMES) + 1):
        b.run_frame()
        if f in FRAMES:
            out[str(f)] = hashlib.sha1(r.render_rgb(b).tobytes()).hexdigest()
    return out


def main():
    res = {v: run(v) for v in ("bublbobl", "bublboblr")}
    if "--update" in sys.argv:
        json.dump(res, open(GOLDEN, "w"), indent=1)
        print("updated", GOLDEN)
        return 0
    gold = json.load(open(GOLDEN))
    ok = gold == res
    print("golden frames:", "MATCH" if ok else "MISMATCH")
    if not ok:
        print(json.dumps({"expected": gold, "got": res}, indent=1))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
