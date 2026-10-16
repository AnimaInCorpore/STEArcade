"""tools/mcu.py (the sprite MCU's job as a model) against the HD63701Y0 interpreter on every job of port runs.

    python games/ddragon/tools/mcu_test.py [FRAMES] [SEED ...]

The port's schedule (machine.DDragonPort, the coverage's inputs of ref/cover.py) runs the interpreter at each $380F
write; the model does the same job on a copy of the shared RAM before it: the shared RAM after it and the MCU's RAM
$40-$66 must be equal (the stack bytes above are not part of the job's result).
"""
import sys
from pathlib import Path

sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[1] / "ref"),
                str(Path(__file__).resolve().parents[3] / "engine")]
import machine as M
from mcu import Mcu


def main():
    args = [int(a) for a in sys.argv[1:]]
    frames = args[0] if args else 6000
    seeds = args[1:] or [0, 1, 11]
    import cover
    bad = 0
    total = 0
    for seed in seeds:
        model = Mcu(M.load("21jm-0.ic55"))
        orig = M.DDragonPort.mcu_job
        stats = dict(jobs=0, sprites=0)

        def job(self):
            nonlocal bad, total
            before = bytearray(self.comram)
            orig(self)
            mine = bytearray(before)
            model.job(mine)
            total += 1
            stats["jobs"] += 1
            stats["sprites"] += mine[0x1FD]
            ram_ok = model.ram[:0x27] == self.mcu.ram256[:0x27]
            if mine != self.comram or not ram_ok:
                bad += 1
                if bad <= 5:
                    diff = [i for i in range(0x200) if mine[i] != self.comram[i]]
                    rd = [0x40 + i for i in range(0x27) if model.ram[i] != self.mcu.ram256[i]]
                    print("seed %d frame %d job %d: shared RAM %d bytes differ %s, MCU RAM %s" % (
                        seed, self.frame, stats["jobs"], len(diff), ["%03X" % i for i in diff[:8]],
                        ["%02X" % a for a in rd[:8]]))
                model.ram[:] = self.mcu.ram256      # (go on from the interpreter's state)
                model.first = False
        M.DDragonPort.mcu_job = job
        try:
            cover.run(seed, frames, out=Path("/dev/null"))
        finally:
            M.DDragonPort.mcu_job = orig
        print("seed %d: %d jobs, %d sprite entries" % (seed, stats["jobs"], stats["sprites"]))
    print("%d of %d jobs differ" % (bad, total))
    return int(bad != 0)


if __name__ == "__main__":
    sys.exit(main())
