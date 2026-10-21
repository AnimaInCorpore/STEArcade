"""The event-driven 51XX (Galaga(mcu=True, mcu_events=True): no clock, run from wait point to wait point) against the
cycle-exact one (Galaga(mcu=True), which matches MAME 0.289, ref/mame_cmp_51xx.py): the same inputs from power-on, the
main CPU's reads of the 51XX, the 51XX's data RAM and the main CPU's RAM compared.

    python ref/mcu_events_test.py [frames] [script]     # default 3000 two; the scripts of ref/mame_cmp_51xx.py
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [HERE, os.path.join(HERE, "..", "tools"), os.path.join(HERE, "..", "..", "..", "engine")]
FRAMES = int(sys.argv[1]) if len(sys.argv) > 1 else 3000
SCRIPT = sys.argv[2] if len(sys.argv) > 2 else "two"
sys.argv = [sys.argv[0], str(FRAMES), SCRIPT]
import machine
import mame_cmp_51xx as cmp


def make(events):
    m = machine.Galaga(mcu=True, mcu_events=events)
    reads = []
    rd = m.cpus[0].rd8

    def rd8(a):
        v = rd(a)
        if 0x7000 <= a <= 0x70ff and m.ctrl06 & 1:
            reads.append((m.frame, v))
        return v
    m.cpus[0].rd8 = rd8
    return m, reads


def main():
    (a, ra), (b, rb) = make(False), make(True)
    bad_ram = []
    while a.frame < FRAMES:
        for m in (a, b):
            m.in0, m.in1 = cmp.inputs(m.frame)
            m.run_frame()
        if a.n51.mcu.ram != b.n51.mcu.ram:
            bad_ram.append(a.frame)
    d = [i for i in range(min(len(ra), len(rb))) if ra[i] != rb[i]]
    print("%s %d frames: 51XX reads %d / %d, %d differ%s" % (SCRIPT, FRAMES, len(ra), len(rb), len(d),
          (" (first: exact %s, events %s)" % (ra[d[0]], rb[d[0]])) if d else ""))
    print("51XX data RAM differs after %d frames%s; main CPU RAM at the end %s" % (len(bad_ram),
          (" (first %d)" % bad_ram[0]) if bad_ram else "", "equal" if a.ram == b.ram else "DIFFERS"))
    print("event-driven 51XX: %d instructions, %.0f a frame" % (b.steps51, b.steps51 / FRAMES))
    ok = not d and len(ra) == len(rb) and not bad_ram and a.ram == b.ram
    print("PASS" if ok else "FAIL")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
