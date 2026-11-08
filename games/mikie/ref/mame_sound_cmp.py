"""Mikie's sound board reference (tools/sound.py MameBoard: the Z80 translation's source) against MAME.

    python games/mikie/ref/mame_sound_cmp.py [frames] [--keep DIR]

One MAME run (engine/mame_frames.lua, attract mode: no input) logs every write of both SN76489As ($8002, $8004 of the
sound CPU) and the main CPU's sound latch ($2400) and LS259 ($2000-$2007) per frame.  The commands (the latch's value at
each Q2 rising edge) are fed to MameBoard at the frames' beam positions; the SN bytes it writes must be MAME's, in
order and per chip.  Reports the equal share (difflib) and the first frames where the sequences differ.
"""
from pathlib import Path
import difflib
import sys
sys.path[:0] = [str(Path(__file__).resolve().parents[1] / "tools"), str(Path(__file__).resolve().parents[3] / "engine")]
import mame_cmp
from sound import MameBoard, CLOCK, FRAME_HZ


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    keep = sys.argv[sys.argv.index("--keep") + 1] if "--keep" in sys.argv else None
    if keep:
        args = [a for a in args if a != keep]
    n = int(args[0]) if args else 2400
    frames = list(range(2, n + 1))
    d = mame_cmp.run_mame("mikie", frames, [], taps=["audiocpu:0x8002:0x8002", "audiocpu:0x8004:0x8004",
                                                      "maincpu:0x2000:0x2007", "maincpu:0x2400:0x2400"], keep=keep)
    ref = MameBoard()
    per = CLOCK / FRAME_HZ
    latch, q2 = 0, 0
    want = ([], [])
    cmds = 0
    for f in frames:
        for tag, line, off, data in mame_cmp.load_taps(d, f):
            if tag == "audiocpu" or tag.startswith("audiocpu"):
                want[0 if off == 0x8002 else 1].append((f, data))
            elif off == 0x2400:
                latch = data
            elif off == 0x2002:
                b = data & 1
                if b and not q2:
                    ref.command(int((f - 1 + line / 264.0) * per) + 100, latch)
                    cmds += 1
                q2 = b
        ref.run_to(int(f * per))
    got = ([], [])
    for cy, chip, v in ref.sn_log:
        got[chip].append((int(cy / per) + 1, v))
    ok = True
    for c in (0, 1):
        a, b = [v for _, v in want[c]], [v for _, v in got[c]]
        sm = difflib.SequenceMatcher(None, a, b, autojunk=False)
        same = sum(bl.size for bl in sm.get_matching_blocks())
        print("SN%d: MAME %d bytes, reference %d, %d equal in order (%.2f%%); %d commands" % (
            c + 1, len(a), len(b), same, 100 * same / max(1, max(len(a), len(b))), cmds))
        if a != b:
            ok = False
            for i, (x, y) in enumerate(zip(a, b)):
                if x != y:
                    print("  first difference at byte %d: MAME %02X (frame %d), reference %02X (frame %d)" % (
                        i, x, want[c][i][0], y, got[c][i][0]))
                    break
    print("equal" if ok else "DIFFERENT", "- logs in", d)
    return int(not ok)


if __name__ == "__main__":
    sys.exit(main())
