"""The patched program (tools/patch.py, as the STE runs it) against the original, both on the STE runtime's schedule
(tools/stemodel.py PortModel): the same idle points, and the video RAM, palette, work RAM, EEPROM and the sound
commands equal at each.

    venv/bin/python games/gauntlet/tools/logic_test.py [VBLS] [--seed N] [--level L]

Also checks the marks the renderer relies on: every playfield column and every alphanumerics change the patched
program made in a VBL was marked by its writers' stubs and hooks (tools/patch.py SITES pf_blk_* / mem_clear, HOOKS).

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
LEVEL_POKE_UNTIL = 790               # --level L: $904004 (render_test.py's way to any maze)
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
    level = 0
    if "--level" in args:
        level = int(args[args.index("--level") + 1])
        del args[args.index("--level"):args.index("--level") + 2]
    n = int(args[0]) if args else 3000
    a = PortModel(patched=False)
    b = PortModel(patched=True)
    rnd = random.Random(seed)
    players = []
    if seed:
        from cover import Player
        k = 1 if seed < 10 else rnd.randint(2, 4)
        players = [Player(rnd, i, 300 + 50 * i) for i in range(k)]
    last_pf = b.window_bytes("vram")[:0x2000]
    last_al = b.window_bytes("vram")[0x5000:0x5F00]
    for f in range(n):
        for p in players:
            if p.coin(f) and not p.coin(f - 1):          # (a press: one count)
                a.sound.coin(p.k)
                b.sound.coin(p.k)
            v = 0xFFFF & ~p.joy(f)
            a.inputs[p.k] = b.inputs[p.k] = v
        if level and f < LEVEL_POKE_UNTIL:               # (the level number, until the first maze is built)
            for m in (a, b):
                v = m.win["vram"] + 0x4004
                m.mem[v:v + 2] = (level >> 8, level & 0xFF)
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
        pf = b.window_bytes("vram")[:0x2000]             # every playfield quarter column changed was marked
        if ib != "busy":                                  # (the renderer compares only marked ones; it runs only
            missed = [q for q in range(256) if pf[q * 32:q * 32 + 32] != last_pf[q * 32:q * 32 + 32] and
                      q not in b.pf_marks]
            if missed:
                bad.append("playfield written without a mark: %s" % ["column %d quarter %d" % (q >> 2, q & 3)
                                                                     for q in missed])
            b.pf_marks.clear()                            #  when the game waits: a VBL that comes while it runs
            last_pf = pf                                  #  may split a writer from its mark)
            al = b.window_bytes("vram")[0x5000:0x5F00]   # and every change of the alphanumerics
            if al != last_al and not b.al_marked:
                k = next(i for i in range(len(al)) if al[i] != last_al[i])
                bad.append("the alphanumerics written without a mark (row %d column %d)" % (k >> 7, (k & 127) >> 1))
            b.al_marked = False
            last_al = al
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
