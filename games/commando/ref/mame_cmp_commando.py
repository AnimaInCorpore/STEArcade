"""Compare the reference renderer with actual Commando MAME snapshots."""
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
from machine import Commando
from paths import ROMS


def main():
    frames = [int(v) for v in sys.argv[1:]] or [100, 700, 1500, 2500]
    executable = os.environ.get('MAME') or shutil.which('mame')
    if not executable:
        raise RuntimeError('MAME not found; set MAME to its executable')
    worst = 0
    for frame in frames:
        out = Path(tempfile.mkdtemp(prefix='mame_commando_'))
        mamewin.run([executable, 'commando', '-rompath', str(ROMS), '-window', '-sound', 'none',
                        '-nothrottle', '-frameskip', '0', '-seconds_to_run', '250', '-skip_gameinfo',
                        '-autoboot_script', str(HERE / 'mame_dump.lua'), '-snapshot_directory', str(out),
                        '-snapname', 'shot'], cwd=out, env=dict(os.environ, OUT=str(out), FRAME=str(frame)),
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True, timeout=120)
        m = Commando()
        m.mem[0xd000:] = (out / 'mem.bin').read_bytes()
        regs = (out / 'regs.bin').read_bytes()
        m.scroll[:] = regs[:4]
        m.control = regs[4]
        # Compare the PROM-derived colours too, before any palette substitution.
        from machine import Gfx
        m.gfx = Gfx()
        palette = np.frombuffer((out / 'palette.bin').read_bytes(), np.uint8).reshape(256,3)
        if not np.array_equal(m.gfx.rgb, palette):
            raise RuntimeError(f'Palette mismatch: maximum channel error {np.abs(m.gfx.rgb.astype(int)-palette).max()}')
        shot = np.array(Image.open(out / 'shot.png').convert('RGB'))
        candidates = []
        for label, sprites in [('current', m.mem[0xfe00:0xff80]),
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
