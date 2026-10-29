"""Compare Gun.Smoke reference pixels and PROM palette with MAME snapshots."""
from pathlib import Path
import os
import shutil
import subprocess
import sys
import tempfile
import numpy as np
from PIL import Image
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
sys.path.insert(0,str(Path(__file__).resolve().parents[3]/'engine'))
import mamewin                       # (MAME runs minimized)
from machine import GunSmoke
from paths import ROMS


def main():
    executable = os.environ.get('MAME') or shutil.which('mame')
    if not executable: raise RuntimeError('MAME not found; set MAME')
    play = '--play' in sys.argv[1:]
    frames = [int(x) for x in sys.argv[1:] if x != '--play']
    worst = 0
    for frame in frames or ([900,1500,2500] if play else [100,700,1500,2500,4000,6000]):
        out=Path(tempfile.mkdtemp(prefix='mame_gunsmoke_'))
        with (out/'mame.log').open('w') as log:
            mamewin.run([executable,'gunsmoke','-rompath',str(ROMS),'-window','-sound','none',
                            '-nothrottle','-frameskip','0','-seconds_to_run','250','-skip_gameinfo',
                            '-autoboot_script',str(Path(__file__).with_name('mame_dump.lua')),
                            '-snapshot_directory',str(out),'-snapname','shot'],cwd=out,
                           env=dict(os.environ,OUT=str(out),FRAME=str(frame),PLAY=str(int(play))),stdout=log,stderr=log,
                           check=True,timeout=120)
        if not (out/'shot.png').exists() or not (out/'sprites.bin').exists():
            raise RuntimeError(f'MAME capture failed; inspect {out}/mame.log')
        m=GunSmoke()
        m.mem[0xd000:]=(out/'mem.bin').read_bytes()
        m.control,m.layers=(out/'regs.bin').read_bytes()
        m.sprites[:]=(out/'sprites.bin').read_bytes()
        rgb=m.render_rgb()
        shot=np.array(Image.open(out/'shot.png').convert('RGB'))
        if rgb.shape!=shot.shape: raise RuntimeError(f'Shape mismatch: {rgb.shape}, {shot.shape}')
        pens=np.array([[int(line.split()[1][i:i+2],16) for i in (0,2,4)]
                       for line in (out/'pens.txt').read_text().splitlines()],np.uint8)
        assert np.array_equal(m.video.pens,pens), 'PROM palette differs from MAME'
        diff=int(np.any(rgb!=shot,axis=2).sum());worst=max(worst,diff)
        Image.fromarray(np.hstack((rgb,shot))).save(out/'compare.png')
        print(f'frame {frame}: {diff} pixels differ; {out}/compare.png',flush=True)
    return int(worst!=0)


if __name__=='__main__': sys.exit(main())
