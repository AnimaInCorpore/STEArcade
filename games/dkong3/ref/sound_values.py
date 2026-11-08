"""The values the game writes to the three sound latches ($7C00, $7C80, $7D00) under random play, with how long each is held
and what follows it: build/dkong3/sound_values_<seed>.json (the standard capture set of tools/sound_capture.py).

    python ref/sound_values.py <seed> <frames>
"""
import sys, os, random, json, collections
sys.path[:0] = [os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tools"), os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "engine")]
from machine import *
from paths import build_dir

seed = int(sys.argv[1]); nframes = int(sys.argv[2])
rnd = random.Random(seed)
m = DK3(dsw1=0x03 if seed % 3 == 0 else 0)
joy = jl = 0
log = []                                    # (frame, l1, l2, l3) at every change
last = None
for f in range(nframes):
    if jl == 0:
        joy = rnd.choice([0, 0, 1, 2, 4, 8, 16, 17, 18, 5, 9, 1, 2, 0]); jl = rnd.randint(3, 40)
    jl -= 1
    m.set_inputs(p1=joy, p2=joy if seed % 2 == 0 else 0, coin=f % 600 == 30, start1=f % 900 in (100, 101, 102), start2=seed % 2 == 0 and f % 900 in (400, 401))
    m.run_frame()
    cur = (m.snd[0x7C00], m.snd[0x7C80], m.snd[0x7D00])
    if cur != last:
        log.append((f,) + cur)
        last = cur
json.dump(log, open(build_dir("dkong3") / ("sound_values_%d.json" % seed), "w"))
print(len(log), "changes")
