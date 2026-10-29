"""Compare arcade reference video with MAME's own RAM and sprite DMA buffer."""
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
from prepare import verify
from video import Video


def main():
    frames = [int(n) for n in sys.argv[1:]] or [100, 700, 1500]
    executable = os.environ.get('MAME') or shutil.which('mame')
    if not executable:
        raise RuntimeError('MAME not found; set MAME to its executable')
    entries, files, _, missing = verify()
    if missing:
        raise RuntimeError('Missing ROMs: ' + ', '.join(e['name'] for e in missing))
    set_name = '1943u' if entries[0]['name'].startswith('bmu') else '1943'
    outroot = Path(tempfile.mkdtemp(prefix='mame_1943_'))
    romroot = outroot / 'roms'
    romdir = romroot / set_name
    romdir.mkdir(parents=True)
    for name, data in files.items(): (romdir / name).write_bytes(data)
    v = Video()
    worst = 0
    for frame in frames:
        out = outroot / str(frame)
        out.mkdir()
        result = mamewin.run([executable, set_name, '-rompath', str(romroot), '-window',
                                 '-sound', 'none', '-nothrottle', '-frameskip', '0',
                                 '-seconds_to_run', '250', '-skip_gameinfo',
                                 '-autoboot_delay', '0', '-autoboot_script', str(HERE / 'mame_dump.lua'),
                                 '-snapshot_directory', str(out), '-snapname', 'shot'],
                                cwd=out, env=dict(os.environ, OUT=str(out), FRAME=str(frame)),
                                capture_output=True, timeout=60)
        (out / 'mame.log').write_bytes(result.stdout + result.stderr)
        if result.returncode or not (out / 'regs.bin').exists():
            raise RuntimeError(f'MAME capture failed (exit {result.returncode}): ' + str(out / 'mame.log'))
        mem = bytearray(65536)
        mem[0xd000:] = (out / 'mem.bin').read_bytes()
        control, layers = (out / 'regs.bin').read_bytes()
        rgb = v.render_rgb(mem, (out / 'sprites.bin').read_bytes(), control, layers, True)
        shot = np.array(Image.open(out / 'shot.png').convert('RGB'))
        if shot.shape != rgb.shape: raise RuntimeError(f'Unexpected screenshot size {shot.shape}')
        diff = int(np.any(rgb != shot, axis=2).sum())
        worst = max(worst, diff)
        Image.fromarray(np.hstack((rgb, shot))).save(out / 'compare.png')
        print(f'frame {frame}: {diff} differing pixels; {out}/compare.png', flush=True)
    return int(worst != 0)


if __name__ == '__main__':
    sys.exit(main())
