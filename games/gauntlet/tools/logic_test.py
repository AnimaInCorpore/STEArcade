"""The patched program (tools/patch.py, as the STE runs it) against the original, both on the STE runtime's schedule
(tools/stemodel.py PortModel): the same idle points, and the video RAM, palette, work RAM, EEPROM and the sound
commands equal at each.

    venv/bin/python games/gauntlet/tools/logic_test.py [VBLS] [--seed N]

Seeds as ref/cover.py (0: the attract mode; 1-9 one player at random; 10-19 two to four players).
"""
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ref"))
from stemodel import PortModel
from patch import ste_addr, MAP

AREAS = ["vram", "palette", "ram", "eeprom"]
# a pointer and its STE form differ in their high byte only, by a window's move (patch.MAP: $90 -> $3F ...); the
# program also keeps flags above it ($01904DD4) and adds to it ($984DCA, a mirror of $904DCA)
DELTAS = {((lo - ste) >> 16) & 0xFF for name, lo, hi, ste in MAP}


def differs(x, y):
    """the first offset where the areas differ, not counting longs that hold an address and its STE form"""
    if x == y:
        return None
    i = 0
    n = len(x)
    while i < n:
        if x[i] != y[i]:
            ok = False
            for s in (i - (i & 1), i - (i & 1) - 2):        # (an even long covering the byte)
                if 0 <= s and s + 4 <= n:
                    a, b = int.from_bytes(x[s:s + 4], "big"), int.from_bytes(y[s:s + 4], "big")
                    if a != b and a & 0xFFFF == b & 0xFFFF and ((a - b) >> 16) & 0xFF in DELTAS:
                        ok = True
                        i = s + 4
                        break
            w = i & ~1                                       # (a pointer's high word kept apart: $0090 / $003F)
            if not ok and x[w] == y[w] == 0 and (x[w + 1] - y[w + 1]) & 0xFF in DELTAS:
                ok = True
                i = w + 2
            if not ok:
                return i
            continue
        i += 1
    return None


def main():
    args = sys.argv[1:]
    seed = 0
    if "--seed" in args:
        seed = int(args[args.index("--seed") + 1])
        del args[args.index("--seed"):args.index("--seed") + 2]
    n = int(args[0]) if args else 3000
    a = PortModel(patched=False)
    b = PortModel(patched=True)
    rnd = random.Random(seed)
    players = []
    if seed:
        from cover import Player
        k = 1 if seed < 10 else rnd.randint(2, 4)
        players = [Player(rnd, i, 300 + 50 * i) for i in range(k)]
    for f in range(n):
        for p in players:
            if p.coin(f) and not p.coin(f - 1):          # (a press: one count)
                a.sound.coin(p.k)
                b.sound.coin(p.k)
            v = 0xFFFF & ~p.joy(f)
            a.inputs[p.k] = b.inputs[p.k] = v
        ia, ib = a.step(), b.step()
        bad = []
        if ia != ib:
            bad.append("idle point %s vs %s" % (ia, ib))
        sp = a.cpu.a(7) - 0x900000                           # (the stack below SP is dead: the STE's runtime calls
        for area in AREAS:                                    #  leave their return addresses there)
            x, y = a.window_bytes(area), b.window_bytes(area)
            if area == "vram" and 0x4000 <= sp <= 0x5000:
                x = x[:sp - 0x400] + bytes(0x400) + x[sp:]
                y = y[:sp - 0x400] + bytes(0x400) + y[sp:]
            k = differs(x, y)
            if k is not None:
                s0 = k & ~1
                bad.append("%s +%04X: %s vs %s" % (area, k, x[s0 - 2:s0 + 4].hex(), y[s0 - 2:s0 + 4].hex()))
        if a.sound.commands != b.sound.commands:
            bad.append("sound %s vs %s" % (a.sound.commands[-3:], b.sound.commands[-3:]))
        if bad:
            print("frame %d differs: %s" % (f, "; ".join(bad)))
            return 1
        if f % 500 == 0:
            print("frame %5d: equal (idle %s, %d cycles; bank %d)" % (f, ia, a.cycles, b.bank))
    print("%d VBLs equal" % n)
    return 0


if __name__ == "__main__":
    sys.exit(main())
