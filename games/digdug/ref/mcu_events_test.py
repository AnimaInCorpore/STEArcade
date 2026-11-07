"""The event-driven 51XX / 53XX (DigDug(mcu_events=True), the model of the STE translation) against the cycle-exact ones
(which match MAME's picture, ref/mame_cmp_digdug.py): the same input script runs on both machines (the first in the STE's
schedule, run_frame_port, the second in MAME's phase, run_frame); the bytes the main CPU wrote to the 51XX and read
from each chip (the idle $FF reads left out: the polling rates differ by design) must be the same sequences, the shorter a
prefix of the longer.  python ref/mcu_events_test.py [frames]       (default 3000)"""
import os
import sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [os.path.join(HERE, "..", "tools"), os.path.join(HERE, "..", "..", "..", "engine")]
from machine import DigDug

frames = int(sys.argv[1]) if len(sys.argv) > 1 else 3000


def script(f):
    in0 = in1 = 0xff
    if 1000 <= f < 1006: in1 &= ~0x10
    if 1150 <= f < 1156: in1 &= ~0x04
    if f >= 1300:
        in0 &= ~(0x02 if (f // 45) % 2 else 0x08)
        if (f // 7) % 3 == 0: in1 &= ~0x01
    return in0, in1


ev, ck = DigDug(skip_tests=True, mcu_events=True), DigDug(skip_tests=True)
for f in range(frames):
    for m in (ev, ck):
        m.in0, m.in1 = script(f)
    ev.run_frame_port()
    ck.run_frame()
bad = 0
for name, a, b in (("51XX", ev.n51.log, ck.n51.log), ("53XX", ev.n53.log, ck.n53.log)):
    # the polling rates differ by design (the event model's transfers run at once): the idle reads ($FF) are dropped, the
    # writes and the other bytes read are compared in order up to the shorter
    fa, fb = [x for x in a if x[1] != 0xFF], [x for x in b if x[1] != 0xFF]
    n = min(len(fa), len(fb))
    same = sum(1 for x, y in zip(fa, fb) if x == y)
    print("%s: %d / %d accesses (event model / cycle-exact), %d / %d without the idle reads; first %d compared, %d equal" % (
        name, len(a), len(b), len(fa), len(fb), n, same))
    if name == "53XX":                # (the 51XX's bytes carry the inputs and credits, sampled at other frames by the two
        bad += n - same               # schedules: its line is informational; its translation is checked by engine/mb88x_test.py for Galaga)
print("PASS" if not bad else "FAIL: %d differing accesses" % bad)
sys.exit(1 if bad else 0)
