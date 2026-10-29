"""The STE's sound schedule (tools/sound.py TickBoard) against the reference (MameBoard: the sound CPU at its clock, each
command at the main CPU's instant in MAME's schedule, machine.Pooyan), fed with the same game run.

    python ref/sound_cmp.py [seed] [frames]

The STE gets a frame's commands before the next frame's ticks, as the port does (snd_frame before the NMI).  The
audible state (each channel's period and volume, a silent channel's period left out) after every tick: compared tick
by tick (the STE's ticks aligned to the reference's, which boots for ~38,000 cycles first; exact and within a tick),
and per channel as the sequence of its states with the time left out (difflib: the matching share).  The STE starts an
effect up to a frame later, and an effect that starts later may take another free slot (another AY channel): those
are the differences.  Exits 1 below 99% of the states equal.
"""
from pathlib import Path
import difflib
import random
import sys
sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[1] / 'tools'),
                str(Path(__file__).resolve().parents[3] / 'engine')]
import cover
from sound import MameBoard, TickBoard, TimedPooyan, CLOCK, MAIN_CLOCK, LOOP


def voices(ay):
    """the audible state: per channel (period, volume); a silent channel's period does not count"""
    return tuple(((r[2 * v] | r[2 * v + 1] << 8) & 0xFFF, r[8 + v] & 0x1F) if r[8 + v] & 0x1F else (0, 0)
                 for r in ay for v in range(3))


def collapse(xs):
    return [x for i, x in enumerate(xs) if i == 0 or x != xs[i - 1]]


def main():
    seed = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    frames = int(sys.argv[2]) if len(sys.argv) > 2 else 6000
    m = TimedPooyan(*cover.dsw(seed))
    rnd, st = random.Random(seed), {'two': seed in (10, 11)}
    ref, ste = MameBoard(), TickBoard()
    ticks = ([], [])
    boot = [0, 0]
    for i, b in enumerate((ref, ste)):
        def step(b=b, i=i, step0=b.cpu.step):
            n = step0()
            if b.cpu.pc == LOOP:
                ticks[i].append(voices(b.ay))
                boot[i] = boot[i] or b.cpu.cycles
            return n
        b.cpu.step = step
    done, last = 0, []
    for f in range(frames):
        m.system, m.p1, m.p2 = cover.inputs(f, rnd, st)
        cover.cheats(seed, f, m, st)
        m.run_frame()
        new = m.timed[done:]
        done = len(m.timed)
        for cyc, v in new:
            ref.command(cyc, v)
        ref.run_to(m.cpu.cycles * CLOCK // MAIN_CLOCK)
        ste.run_frame(last)                     # (the port: the commands of a frame's NMI before the next frame's)
        last = [v for _, v in new]
    n = min(len(ticks[0]), len(ticks[1])) - 20
    a, b = ticks
    shift = max(range(-16, 17), key=lambda sh: sum(a[i] == b[i + sh] for i in range(20, n, 7)))
    tk = sum(a[i] == b[i + shift] for i in range(20, n))
    tk1 = sum(a[i] in b[i + shift - 1:i + shift + 2] for i in range(20, n))
    print('ticks %d / %d, the STE %+d ticks (the reference boots for %d cycles): equal %.2f%%, within a tick %.2f%%'
          % (len(a), len(b), shift, boot[0], 100 * tk / (n - 20), 100 * tk1 / (n - 20)))
    same = 0
    total = 0
    for ch in range(6):
        seq = [collapse([t[ch] for t in x]) for x in (a, b)]
        sm = difflib.SequenceMatcher(None, seq[0], seq[1], autojunk=False)
        same += sum(bl.size for bl in sm.get_matching_blocks())
        total += max(len(seq[0]), len(seq[1]))
    print('seed %d, %d frames, %d commands, %d AY writes (reference %d); each channel\'s audible states in order (time '
          'left out): %d of %d equal (%.2f%%)'
          % (seed, frames, len(m.timed), len(ste.writes), len(ref.writes), same, total, 100 * same / total))
    return same / total


if __name__ == '__main__':
    sys.exit(0 if main() > 0.99 else 1)
