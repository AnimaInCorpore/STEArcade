"""The HD63701's mailbox as a native model (what src/mcu.s does on the STE), checked against the firmware.

    python games/rthunder/tools/mcu_model.py [frames] [--seed N]

The firmware (cus60-60a1.mcu + rt3_4.6b, run by tools/machine.py) reads the inputs and the DIP switches, keeps the credits
and acknowledges the main CPU's sound commands in CUS30 RAM (main $4000-$43FF).  The model runs once per arcade frame
before the CPUs (where the reference runs the MCU) and writes the bytes the main CPU reads:

  * every input has a pair of bytes: the level (the input one frame ago) and the pulse (its rising edge, a frame later);
  * the coins (coin 1: $266/$267, coin 2: $264/$265) are inverted levels; a coin counts when the line was low for at least two
    frames and rises: credits ($1A5) + 1, the coin counter ($18B) + 1, the display digits $189 / $18A; $1A6 follows $1A5 a frame
    late ($18A too, but at once after a coin);
  * start 1 / start 2 ($262 / $260 pulses): with credits (1 / 2) and no start taken ($18C = 0): the credits are used, $18C = 1 / 2,
    $1A7 = the players;
  * a sound command in $380: acknowledged with $FF (the sound engine itself is not modelled: its notes are recorded).

The bytes the model does not write keep the snapshot's values (the DIP switch copies, the sound engine's flags).
"""
import sys
from pathlib import Path

sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[1] / "ref"),
                str(Path(__file__).resolve().parents[3] / "engine")]

# (port, bit) -> the pulse's offset; the level is the next byte
PAIRS = {(0, 1): 0x276, (0, 2): 0x27C, (0, 3): 0x270, (0, 4): 0x272, (0, 6): 0x262,
         (1, 1): 0x26A, (1, 2): 0x27A, (1, 4): 0x268, (1, 3): 0x26E, (1, 6): 0x260, (1, 7): 0x25C,
         (2, 3): 0x278, (2, 4): 0x280, (2, 5): 0x27E, (2, 6): 0x26C, (2, 7): 0x274}
COINS = {(0, 5): 0x266, (1, 5): 0x264}


class McuModel:
    def __init__(self):
        self.hist = {}                  # (port, bit) -> pressed in the last four frames, newest first
        self.cred = 0
        self.coins = 0
        self.prev_cred = 0

    def pressed(self, ports, key):
        return (ports[key[0]] >> key[1]) & 1 == 0

    def frame(self, ram, in0, in1, in2):
        ports = (in0, in1, in2)
        ev = False
        for key in list(PAIRS) + list(COINS):
            h = self.hist.setdefault(key, [False] * 4)
            p1, p2, p3, p4 = h
            if key in PAIRS:
                off = PAIRS[key]
                ram[off + 1] = int(p1)
                ram[off] = int(p2 and not p3)
            else:
                off = COINS[key]
                ram[off + 1] = int(not p1)
                ram[off] = int((not p2) and p3 and p4)
                if (not p2) and p3 and p4:
                    ev = True
            h[:] = [self.pressed(ports, key), p1, p2, p3]
        if ram[0x268]:                  # (service 1: a coin at once)
            ev = True
        credits_before = ram[0x1A5]
        ram[0x1A6] = credits_before
        if ev:
            ram[0x1A5] = min(ram[0x1A5] + 1, 99)
            ram[0x18B] = (ram[0x18B] + 1) & 0xFF
            ram[0x18A] = ram[0x1A5] % 10
            ram[0x189] = ram[0x1A5] // 10
        else:
            ram[0x18A] = credits_before % 10
            ram[0x189] = credits_before // 10
        # the starts (their pulses are this frame's)
        if ram[0x18C] == 0:
            if ram[0x262] and ram[0x1A5] >= 1:
                ram[0x1A5] -= 1
                ram[0x18C] = 1
                ram[0x1A7] = 1
            elif ram[0x260] and ram[0x1A5] >= 2:
                ram[0x1A5] -= 2
                ram[0x18C] = 2
                ram[0x1A7] = 2
        c = ram[0x380]
        if c not in (0, 0xFF):
            ram[0x380] = 0xFF


def main():
    import argparse
    import cover
    from machine import RthunderRule
    ap = argparse.ArgumentParser()
    ap.add_argument("frames", nargs="?", type=int, default=3000)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--random", action="store_true", help="random inputs (bits held for random lengths) instead of the coverage's play")
    args = ap.parse_args()
    dswa, dswb, inputs = cover.schedule(args.seed)
    if args.random:
        import random
        rng = random.Random(args.seed)
        held = [0] * 24
        state = [0xFF, 0xFF, 0xFF]
        masks = {0: 0x7F, 1: 0xFF, 2: 0xF8}

        def inputs(f):
            for k in range(24):
                port, bit = divmod(k, 8)
                if not (masks[port] >> bit) & 1:
                    continue
                if held[k] > 0:
                    held[k] -= 1
                    continue
                if rng.random() < 0.02:
                    state[port] ^= 1 << bit
                    held[k] = rng.choice((1, 1, 2, 3, 5, 8, 20, 60))
            st = list(state)
            for lo, hi in (((2, 4), (2, 5)), ((2, 7), (0, 4)), ((1, 2), (0, 2)), ((1, 3), (0, 3))):     # (a stick has no opposite directions)
                if (st[lo[0]] >> lo[1]) & 1 == 0 and (st[hi[0]] >> hi[1]) & 1 == 0:
                    st[hi[0]] |= 1 << hi[1]
            return tuple(st)
    m = RthunderRule()
    m.dsw = [dswa, dswb]
    m.boot()
    model = McuModel()
    watch = sorted(set(list(range(0x25C, 0x282)) + [0x189, 0x18A, 0x18B, 0x18C, 0x18D, 0x1A5, 0x1A6, 0x1A7, 0x380]))
    bad = 0
    for f in range(args.frames):
        m.in0, m.in1, m.in2 = inputs(f)
        before = bytearray(m.cus30)
        m.run_others()
        pred = bytearray(before)
        model.frame(pred, m.in0, m.in1, m.in2)
        diff = [(o, pred[o], m.cus30[o]) for o in watch if pred[o] != m.cus30[o]]
        if diff:
            bad += 1
            if bad <= 12:
                print("frame %d in=%02x %02x %02x: %s" % (f, m.in0, m.in1, m.in2,
                                                         " ".join("%03x:%02x/%02x" % d for d in diff)))
        m.run_cpus()
    print("%d frames, %d differ (model/firmware)" % (args.frames, bad))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
