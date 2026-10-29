"""The STE's sound schedule (tools/sound.py TickBoard) against the reference (MameBoard: the sound CPU at its clock with
the timer's waits, the VLM5030 emulated for BSY, the tunes' cycle-timed code), fed with the same game run.  Shared by
Track & Field and Hyper Sports.

    python games/trackfld/ref/sound_cmp.py <game> [seed] [frames]

The game's commands come from its port's schedule (ref/cover_sound.py game_commands: ref/cover.py's inputs and
cheats); the reference gets each frame's commands at the frame's start (the main CPU's IRQ handler writes them early in
its frame: within a tick of MAME), the STE gets them before the next frame's ticks, as the port does.  Compared: each
SN voice's audible states (period and attenuation while not silent; the noise: its control and attenuation) in order,
the time left out (difflib: the matching share), and the phrases and tunes started, in order.  The STE starts an
effect up to a frame later than the reference.
"""
from pathlib import Path
import difflib
import sys
sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[1] / 'tools'),
                str(Path(__file__).resolve().parents[3] / 'engine')]
from sound import MameBoard, TickBoard, GAMES, CLOCK
from cover_sound import game_commands


def voices(sn):
    r = sn.reg
    out = []
    for k in range(4):
        a = r[2 * k + 1] & 15
        if a == 15:
            out.append(None)
        else:
            out.append((r[2 * k] if k < 3 else r[6], a))
    return tuple(out)


def collapse(xs):
    return [x for i, x in enumerate(xs) if i == 0 or x != xs[i - 1]]


def main():
    game = sys.argv[1]
    seed = int(sys.argv[2]) if len(sys.argv) > 2 else 1
    frames = int(sys.argv[3]) if len(sys.argv) > 3 else 6000
    g = GAMES[game]
    cmds = game_commands(game, seed, frames)
    ref, ste = MameBoard(game), TickBoard(game)
    states = ([], [])
    for i, b in enumerate((ref, ste)):
        def snw(v, b=b, i=i, f=b.sn_write):
            f(v)
            states[i].append(voices(b.sn))
        b.sn_write = snw
    starts = ([], ste.events)
    ref_vlm = ref.vlm.st_w

    def st_w(state):
        if ref.vlm.pin_ST and not state:
            starts[0].append(('phrase', ref.vlm_data))
        ref_vlm(state)
    ref.vlm.st_w = st_w
    step0 = ref.cpu.step

    def step():
        if ref.cpu.pc == g.tune:
            starts[0].append(('tune', ref.mem[0x400A]))
        return step0()
    ref.cpu.step = step
    per = CLOCK / g.frame_hz
    t0 = 0
    for f, fc in enumerate(cmds):
        start = t0 + int(f * per)
        for j, v in enumerate(fc):
            ref.command(start + 200 + 3000 * j, v)     # (the IRQ handler's writes, a few hundred main CPU cycles apart)
        ref.run_to(start + int(per))
        ste.run_frame(cmds[f - 1] if f else [])
    same = total = 0
    for k in range(4):
        seq = [collapse([s[k] for s in x if s[k] is not None]) for x in states]
        sm = difflib.SequenceMatcher(None, seq[0], seq[1], autojunk=False)
        same += sum(bl.size for bl in sm.get_matching_blocks())
        total += max(len(seq[0]), len(seq[1]))
    a = [e for e in starts[0]]
    b = [(k, n) for _, k, n in starts[1] if k != 'stop']
    sm = difflib.SequenceMatcher(None, a, b, autojunk=False)
    sp = sum(bl.size for bl in sm.get_matching_blocks())
    print('%s seed %d, %d frames, %d commands: the SN voices\' audible states in order (time left out) %d of %d equal '
          '(%.2f%%); phrases and tunes started %d / %d, %d in the same order'
          % (game, seed, frames, sum(map(len, cmds)), same, total, 100 * same / max(1, total), len(a), len(b), sp))
    return same / max(1, total)


if __name__ == '__main__':
    sys.exit(0 if main() > 0.98 else 1)
