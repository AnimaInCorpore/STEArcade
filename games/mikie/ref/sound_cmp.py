"""The STE's sound schedule (tools/sound.py TickBoard) against the reference (MameBoard: the sound CPU at its clock, the
timer's real waits, the IRQ taken between instructions), fed with the same game run.

    python games/mikie/ref/sound_cmp.py [seed] [frames]

The game's commands come from its port's schedule (ref/cover_sound.py game_commands); the reference gets each frame's
commands at the frame's start (the main CPU's IRQ handler writes them early in its frame), the STE gets them before the next
frame's ticks, as the port does.  Compared: each SN voice's audible states (period and attenuation while not silent; the
noise: its control and attenuation) in order of the two chips' eight voices, the time left out (difflib: the matching
share).  The STE starts an effect up to a frame later than the reference.
"""
from pathlib import Path
import difflib
import sys
sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[1] / 'tools'),
                str(Path(__file__).resolve().parents[3] / 'engine')]
from sound import MameBoard, TickBoard, CLOCK, FRAME_HZ
from cover_sound import game_commands


def voices(sn):
    out = []
    for c in (0, 1):
        r = sn[c].reg
        for k in range(4):
            a = r[2 * k + 1] & 15
            out.append(None if a == 15 else (r[2 * k] if k < 3 else r[6], a))
    return tuple(out)


def collapse(xs):
    return [x for i, x in enumerate(xs) if i == 0 or x != xs[i - 1]]


def main():
    seed = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    frames = int(sys.argv[2]) if len(sys.argv) > 2 else 6000
    cmds = game_commands(seed, frames)
    ref, ste = MameBoard(), TickBoard()
    states = ([], [])
    for i, b in enumerate((ref, ste)):
        def snw(chip, v, b=b, i=i, f=b.sn_write):
            f(chip, v)
            states[i].append(voices(b.sn))
        b.sn_write = snw
    per = CLOCK / FRAME_HZ
    for f, fc in enumerate(cmds):
        start = int(f * per)
        for j, v in enumerate(fc):
            ref.command(start + 200 + 3000 * j, v)
        ref.run_to(start + int(per))
        ste.run_frame(cmds[f - 1] if f else [])
    same = total = 0
    for k in range(8):
        seq = [collapse([s[k] for s in x if s[k] is not None]) for x in states]
        sm = difflib.SequenceMatcher(None, seq[0], seq[1], autojunk=False)
        same += sum(bl.size for bl in sm.get_matching_blocks())
        total += max(len(seq[0]), len(seq[1]))
    print('seed %d, %d frames, %d commands: the SN voices\' audible states in order (time left out) %d of %d equal (%.2f%%)'
          % (seed, frames, sum(map(len, cmds)), same, total, 100 * same / max(1, total)))
    return same / max(1, total)


if __name__ == '__main__':
    sys.exit(0 if main() > 0.98 else 1)
