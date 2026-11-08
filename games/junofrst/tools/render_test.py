"""The published picture against the reference: logic_test.py --render.

    python render_test.py [frames] [--seed N] [--start F] [--every K]

Every picture render_frame publishes (the planar buffer the VBL shows) is decoded and compared pixel for pixel with the
reference machine's video RAM (lines 16-239 of the arcade, turned: picture line 255 - x, column y - 16) and its palette
(the 16 palette RAM bytes through assets.ste_word).  --start / --every are accepted for the other ports' command lines
and ignored: every picture is compared.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import logic_test

if __name__ == '__main__':
    argv, out, i = sys.argv[1:], ['--render'], 0
    while i < len(argv):
        if argv[i] in ('--start', '--every'):
            i += 2
            continue
        out.append(argv[i])
        i += 1
    sys.argv = [sys.argv[0]] + out
    logic_test.main()
