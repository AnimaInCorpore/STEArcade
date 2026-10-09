"""Galaga sound probe: what the sound CPU writes to the WSG, what the main CPU sends the 54XX, and how much
the sound CPU works.  python ref/sound1.py [frames of play] -> build/galaga/sound/log.pkl

The reference machine (tools/machine.py, interleaved, the sound CPU's NMI at lines 64 and 192) runs the
attract mode with demo sounds (DSW A), then a scripted game: coin, start, left/right in turns, fire.
Logged: WSG register writes (frame, cycle in the frame, register, value), 54XX data writes (frame, cycle,
value: the 06XX data port while its chip select bit 3 is on), CPU3 instructions per frame.
"""
import os, pickle, random, sys
sys.path[:0] = [os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tools"),
                os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "engine")]
from machine import Galaga
from paths import build_dir

PLAY = int(sys.argv[1]) if len(sys.argv) > 1 else 3000
ATTRACT = 2400

m = Galaga()
log = dict(wsg=[], n54=[], cpu3=[], marks=[])
frame = [0]


class WSG(bytearray):
    def __setitem__(self, i, v):
        log["wsg"].append((frame[0], m.cpus[0].cycles - frame_start[0], i, v & 15))
        bytearray.__setitem__(self, i, v)


m.sound = WSG(0x20)
frame_start = [0]
orig_data06 = m.data06_w


def data06_w(v):
    if not (m.ctrl06 & 0x10) and (m.ctrl06 & 0x08):
        log["n54"].append((frame[0], m.cpus[0].cycles - frame_start[0], v))
    orig_data06(v)


m.data06_w = data06_w
cpu3 = m.cpus[2]
orig_step3 = cpu3.step
count3 = [0]


def step3():
    count3[0] += 1
    return orig_step3()


cpu3.step = step3


def run(n, inputs=None):
    for i in range(n):
        if inputs:
            inputs(i)
        frame_start[0] = m.cpus[0].cycles
        count3[0] = 0
        m.run_frame()
        log["cpu3"].append(count3[0])
        frame[0] += 1


run(ATTRACT)
log["marks"].append((frame[0], "coin"))
run(6, lambda i: setattr(m, "in1", 0xff & ~0x10))
m.in1 = 0xff
run(30)
log["marks"].append((frame[0], "start"))
run(6, lambda i: setattr(m, "in1", 0xff & ~0x04))
m.in1 = 0xff
rnd = random.Random(1)
state = {"dir": 0x02, "left": 0}


def play(i):
    if state["left"] <= 0:
        state["dir"] = rnd.choice((0x02, 0x08, 0x00))
        state["left"] = rnd.randint(10, 60)
    state["left"] -= 1
    m.in0 = 0xff & ~state["dir"] if state["dir"] else 0xff
    m.in1 = 0xff & ~0x01 if i % 12 < 2 else 0xff


run(PLAY, play)
out = build_dir("galaga") / "sound"
out.mkdir(parents=True, exist_ok=True)
pickle.dump(log, open(out / "log.pkl", "wb"))
c = log["cpu3"]
print("frames %d, WSG writes %d, 54XX writes %d" % (frame[0], len(log["wsg"]), len(log["n54"])))
print("CPU3 instructions a frame: mean %.0f, max %d (attract mean %.0f, play mean %.0f)"
      % (sum(c) / len(c), max(c), sum(c[:ATTRACT]) / ATTRACT, sum(c[-PLAY:]) / PLAY))
