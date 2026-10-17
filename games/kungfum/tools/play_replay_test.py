"""Build and verify a bot recording without replacing play_inputs.bin or the normal simulator build.

    venv/bin/python games/kungfum/tools/play_replay_test.py build/kungfum/bots/kev_1.bin

All recorded frames are checked for logic; renderer comparisons default to every
12th frame. --every 1 compares consecutive pictures. The model is not required.
"""
import argparse
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[2] / 'engine'))
from paths import ROOT, VASM, VLINK, RT_INCLUDE, build_dir, src_dir
import playbot


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('recording', type=Path)
    ap.add_argument('--every', type=int, default=12)
    ap.add_argument('--logic-only', action='store_true')
    args = ap.parse_args()
    recording = args.recording.resolve()
    frames = len(playbot.load(recording))
    if not frames or args.every < 1:
        ap.error('recording must be nonempty and --every positive')
    with tempfile.TemporaryDirectory(prefix='kf-replay-') as directory:
        temp = Path(directory)
        shutil.copyfile(recording, temp / 'play_inputs.bin')
        obj, prg, mapfile = (temp / n for n in ('replay.o', 'KUNGFUM.PRG', 'replay.map'))
        # First include directory wins: only the replay comes from temp, all
        # translated code/graphics stay in build/kungfum. No shared file changes.
        subprocess.run([VASM, '-Fvobj', '-quiet', '-nowarn=2047', '-DSIM=1', '-DPLAYBACK=1',
                        '-I', str(temp), '-I', str(build_dir('kungfum')), '-I', str(RT_INCLUDE),
                        '-o', str(obj), 'kungfum.s'], cwd=src_dir('kungfum'), check=True)
        subprocess.run([VLINK, '-b', 'ataritos', '-s', '-o', str(prg), '-M' + str(mapfile), str(obj)], check=True)
        common = [str(frames), '--play', '--recording', str(recording), '--program', str(prg), '--map', str(mapfile)]
        subprocess.run([sys.executable, str(HERE / 'logic_test.py'), *common], check=True)
        if not args.logic_only:
            subprocess.run([sys.executable, str(HERE / 'render_test.py'), *common,
                            '--every', str(args.every), '--stop'], check=True)


if __name__ == '__main__':
    main()
