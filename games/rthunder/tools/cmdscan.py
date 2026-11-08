"""How the firmware answers each sound command the main CPU can send (build/rthunder/snd_dur.json for src/mcu.s).

    python games/rthunder/tools/cmdscan.py PART NPARTS [FRAMES]    (run the parts in parallel; PART = 0 .. NPARTS - 1)

For every command 1-254 (those with c % NPARTS == PART): the reference board boots, the command byte $380 of the CUS30 RAM is
written (as the main CPU's `STA $4380`) and the board runs; the MCU acknowledges with $FF at once and, for a jingle that ends
by itself, clears the byte again (the main CPU waits for that in `TST $4380`).  The frame it clears it is the command's
duration; the others (music that loops, commands that do nothing) stay at $FF until the program clears the byte.  The YM2151
writes are counted (sound.s will need them).  One pickle a part at the end (F:/claude/tmp/rthunder/cmdscan_<part>.pkl).
`python games/rthunder/tools/cmdscan.py merge` writes snd_dur.json from the pickles.
"""
import json
import pickle
import sys
from pathlib import Path

sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[1] / "ref"),
                str(Path(__file__).resolve().parents[3] / "engine")]
from machine import RthunderRule
import cover
from paths import build_dir

TMP = Path("F:/claude/tmp/rthunder")


def main():
    if sys.argv[1] == "merge":
        res = {}
        for f in TMP.glob("cmdscan_*.pkl"):
            res.update(pickle.load(open(f, "rb")))
        d = {c: r["clear"] for c, r in res.items() if r["clear"] is not None}
        (build_dir("rthunder") / "snd_dur.json").write_text(json.dumps(d))
        print(len(res), "commands;", {hex(c): v for c, v in sorted(d.items())})
        return
    part, nparts = int(sys.argv[1]), int(sys.argv[2])
    frames = int(sys.argv[3]) if len(sys.argv) > 3 else 900
    dswa, dswb, _ = cover.schedule(1)
    res = {}
    for c in range(1, 255):
        if c % nparts != part:
            continue
        m = RthunderRule()
        m.dsw = [dswa, dswb]
        m.boot()
        for f in range(30):
            m.in0 = m.in1 = m.in2 = 0xFF
            m.run_frame_port()
        m.cus30[0x380] = c
        ymw = []
        fr = [0]
        o = m.ym.write

        def w(a, v, o=o):
            ymw.append((fr[0], a, v))
            o(a, v)
        m.ym.write = w
        ack = clr = None
        for f in range(frames):
            fr[0] = f
            m.in0 = m.in1 = m.in2 = 0xFF
            m.run_frame_port()
            if ack is None and m.cus30[0x380] == 0xFF:
                ack = f
            if ack is not None and clr is None and m.cus30[0x380] == 0:
                clr = f
            if clr is not None and f > clr + 3:
                break
        res[c] = dict(ack=ack, clear=clr, frames=f + 1, ym=len(ymw), final380=m.cus30[0x380])
    pickle.dump(res, open(TMP / ("cmdscan_%d.pkl" % part), "wb"))


if __name__ == "__main__":
    main()
