"""Compare the reference renderer with actual Black Tiger MAME snapshots."""
from pathlib import Path
import os
import shutil
import subprocess
import sys
import tempfile
import numpy as np
from PIL import Image

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / 'tools'))
sys.path.insert(0, str(HERE.parents[2] / 'engine'))
import mamewin                       # (MAME runs minimized)
from machine import BlackTiger
from paths import ROMS


def main():
    frames = [int(v) for v in sys.argv[1:]] or [100, 700, 1500, 2500]
    executable = os.environ.get('MAME') or shutil.which('mame')
    if not executable:
        raise RuntimeError('MAME not found; set MAME to its executable')
    worst = 0
    for frame in frames:
        out = Path(tempfile.mkdtemp(prefix='mame_blktiger_'))
        mamewin.run([executable, 'blktiger', '-rompath', str(ROMS), '-window', '-sound', 'none',
                        '-nothrottle', '-frameskip', '0', '-seconds_to_run', '250', '-skip_gameinfo',
                        '-autoboot_script', str(HERE / 'mame_dump.lua'), '-snapshot_directory', str(out),
                        '-snapname', 'shot'], cwd=out, env=dict(os.environ, OUT=str(out), FRAME=str(frame)),
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True, timeout=120)
        m = BlackTiger()
        m.mem[0xd000:] = (out / 'mem.bin').read_bytes()
        m.bg[:] = (out / 'bg.bin').read_bytes()
        regs = (out / 'regs.bin').read_bytes()
        m.control, m.video_enable, m.layout = regs[4], regs[12], regs[14]
        m.scroll[:] = regs[8:12]
        shot = np.array(Image.open(out / 'shot.png').convert('RGB'))
        candidates = []
        for label, sprites in [('current', m.mem[0xfe00:]),
                               ('previous', (out / 'sprites_previous.bin').read_bytes())]:
            m.sprites[:] = sprites
            rgb = m.render_rgb()
            if rgb.shape != shot.shape:
                raise RuntimeError(f'Unexpected screenshot shape {shot.shape}')
            candidates.append((int(np.any(rgb != shot, axis=2).sum()), label, rgb))
        diff, label, rgb = min(candidates, key=lambda item: item[0])
        worst = max(worst, diff)
        Image.fromarray(np.hstack((rgb, shot))).save(out / 'compare.png')
        print(f'frame {frame}: {diff} pixels differ (sprites {label}); {out}/compare.png', flush=True)
    return 1 if worst else 0


if __name__ == '__main__':
    sys.exit(main())
