"""64-frame attract-mode collage from MAME AVI recordings, covering every colour that appears.

Recording (F030Arcade's wolfmame-0162 is the only build there that knows bublbobl*; its AVI is
uncompressed RGB24 at the native 256x224, i.e. lossless).  MAME's AVI writer is 32-bit, so record
~300 s segments and resume the machine between them with -autosave (-seconds_to_run is cumulative):
  for k in 0 1 2 ...:  mame bublboblr -rompath <assets/roms> -skip_gameinfo -nothrottle -frameskip 0
        -window -sound none -autosave -seconds_to_run $(( (k+1)*300 )) -aviwrite seg$k.avi
  (files land in MAME's snap/ directory; run from a scratch directory)

usage: python mame_attract_collage.py out_prefix skip_frames until_frames seg0.avi [seg1.avi ...]
  (frames >= until_frames are ignored, e.g. everything after a stray coin; 0 = use all)
  pass 1: stream every frame, record its exact colour set; frames before `skip_frames` (boot) are ignored;
  pass 2: greedily pick frames that add the most uncovered colours until every colour of the whole
          recording is covered, fill the remaining slots evenly in time (preferring stable frames, not
          scene-transition glitches), extract exactly those frames;
  output: <prefix>.png (8x8, time order, no labels), <prefix>.json, and a check that the PNG itself
          contains every colour of the recording.
"""
import json
import subprocess
import sys

import numpy as np
from PIL import Image

W, H = 256, 224
FB = W * H * 3
FPS = 60.0           # MAME's AVI timeline (container says 60/1)


def frames(avi, vf=None):
    cmd = ["ffmpeg", "-v", "error", "-i", avi, "-an"]
    if vf:
        cmd += ["-vf", vf]
    cmd += ["-fps_mode", "passthrough", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, bufsize=FB * 8)
    while True:
        buf = p.stdout.read(FB)
        if len(buf) < FB:
            break
        yield np.frombuffer(buf, np.uint8).reshape(H, W, 3)
    p.wait()


def colour_set(img):
    v = (img[..., 0].astype(np.uint32) << 16) | (img[..., 1].astype(np.uint32) << 8) | img[..., 2]
    return frozenset(np.unique(v).tolist())


def main():
    prefix, skip, until, avis = sys.argv[1], int(sys.argv[2]), int(sys.argv[3]), sys.argv[4:]
    sets, seg_of = [], []                     # per global frame
    for s, avi in enumerate(avis):
        for n, img in enumerate(frames(avi)):
            g = len(sets)
            if until and g >= until:
                break
            sets.append(colour_set(img) if g >= skip else frozenset())
            seg_of.append((s, n))
        if until and len(sets) >= until:
            break
    N = len(sets)
    if N == 0:
        raise SystemExit("no frames decoded")
    universe = frozenset().union(*sets)
    first = {}
    for g in range(skip, N):
        for c in sets[g]:
            first.setdefault(c, g)
    last_new = max(first.values())
    print("frames: %d (%.1f s over %d segments), distinct colours after boot: %d"
          % (N, N / FPS, len(avis), len(universe)))
    print("last previously-unseen colour appears at frame %d (%.1f s); recording ends at %.1f s"
          % (last_new, last_new / FPS, N / FPS))

    def stable(k):        # same colour set 5 frames before and after: not a scene-transition glitch
        return sets[k - 5] == sets[k] == sets[min(k + 5, N - 1)]
    stable_frames = [k for k in range(skip + 5, N) if stable(k)]
    chosen, covered = [], set()
    for pool in (stable_frames, range(skip, N)):          # fall back to glitch frames only if needed
        while covered != universe and len(chosen) < 64:
            i = max(pool, key=lambda k: len(sets[k] - covered))
            gain = sets[i] - covered
            if not gain:
                break
            chosen.append(i)
            covered |= gain
    if covered != universe:
        raise SystemExit("cannot cover all colours in 64 frames")
    need = len(chosen)
    free = list(range(skip, N))
    want = 64 - len(chosen)
    fill = []
    for j in range(want):
        target = skip + (j + 0.5) / want * (N - skip)
        cands = [k for k in free if all(abs(k - c) > 60 for c in chosen + fill)]
        near = sorted(cands, key=lambda k: abs(k - target))[:90]
        # prefer a stable frame (same colour set 5 frames before and after) over a transition glitch
        fill.append(([k for k in near if stable(k)] or near)[0])
    chosen = sorted(set(chosen + fill))
    print("colour cover alone needed %d frames; collage has %d" % (need, len(chosen)))
    assert len(chosen) == 64

    # extract exactly those frames, segment by segment
    by_seg = {}
    for g in chosen:
        s, n = seg_of[g]
        by_seg.setdefault(s, []).append((n, g))
    got_imgs = {}
    for s, lst in by_seg.items():
        sel = "+".join("eq(n\\,%d)" % n for n, _ in sorted(lst))
        out = list(frames(avis[s], "select='%s'" % sel))
        assert len(out) == len(lst), (s, len(out), len(lst))
        for (n, g), im in zip(sorted(lst), out):
            got_imgs[g] = im
    sheet = np.zeros((8 * H, 8 * W, 3), np.uint8)
    for i, g in enumerate(chosen):
        y, x = divmod(i, 8)
        sheet[y * H:(y + 1) * H, x * W:(x + 1) * W] = got_imgs[g]
    Image.fromarray(sheet).save(prefix + ".png")

    present = colour_set(np.array(Image.open(prefix + ".png").convert("RGB")))
    ok = universe <= present
    print("colours in collage PNG: %d / %d -> %s" % (len(present & universe), len(universe),
                                                     "ALL COVERED" if ok else "MISSING"))
    json.dump({"sources": [a.replace("\\", "/").split("/")[-1] for a in avis],
               "grid": "8x8 row-major, time order", "tile": [W, H],
               "frames": chosen, "seconds": [round(k / FPS, 1) for k in chosen],
               "boot_frames_ignored": skip, "frames_used": N, "colours_in_recording": len(universe),
               "last_new_colour_frame": last_new, "recording_frames": N,
               "all_colours_covered": ok}, open(prefix + ".json", "w"), indent=1)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
