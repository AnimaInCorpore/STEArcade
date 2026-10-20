"""Windows Hatari replay support; no Dreamer model/training dependency.

Requires the patched Hatari named-pipe transport in adjacent F030Arcade-private.
Override its checkout with STEARCADE_HATARI_ROOT when located elsewhere.
"""
import hashlib
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
import numpy as np

STE = Path(__file__).resolve().parents[2]
ARC = Path(os.environ.get('STEARCADE_HATARI_ROOT', str(STE.parent/'F030Arcade-private')))
os.environ['PATH'] = 'C:/msys64/ucrt64/bin;C:/msys64/usr/bin;' + os.environ.get('PATH','')
sys.path[:0] = [str(STE/'engine'),str(ARC/'scripts')]
from exploration.hatari_live import Hatari, Pipe, Closed
from paths import VASM, VLINK, RT_INCLUDE
HATARI = ARC/'third_party/hatari/build-ucrt64-merge/src/hatari.exe'
TOS = ARC/'third_party/tos/tos206de.img'

def capture_commands(out, sym, game, label):
    ptr = sym['display_screen_address' if game == 'dkong' else 'flip_addr']
    pal = sym['dk_palette' if game == 'dkong' else 'shown_pal']
    return [f"savebin {(out / (label+'.bin')).as_posix()} '(TEXT+${ptr:x}).l' $10000",
            f"savebin {(out / (label+'.pal')).as_posix()} 'TEXT+${pal:x}' $20"]

def render_capture(raw, palette, output):
    from PIL import Image
    words = np.frombuffer(raw, dtype='>u2').reshape(256,32,4)
    pixels = np.zeros((256,512),np.uint8)
    for k in range(4):
        pixels |= (((words[:,:,k,None] >> np.arange(15,-1,-1)) & 1).reshape(256,512).astype(np.uint8) << k)
    colors = [[(((int(v)>>s)&7)*2+((int(v)>>(s+3))&1))*17 for s in [8,4,0]]
              for v in np.frombuffer(palette,dtype='>u2')]
    Image.fromarray(np.array(colors,dtype=np.uint8)[pixels[:,:320]]).resize((640,512)).save(output)

def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

class Live(Hatari):
    """Same tested Pipe/watchdog transport; TEXT-relative PRG observation addresses."""
    def __init__(self, out, program, sym, game):
        self.out, self.timeout = out, 45
        out.mkdir()
        self.pipe = Pipe(f'ste-dreamer-{os.getpid()}')
        self.obs = [out / 'ram.bin', out / 'input.bin']
        base = sym['z80_block'] + 0x6000 if game == 'dkong' else sym['g_block'] + 0x6000
        self.base = base
        size = 0xc00 if game == 'dkong' else 0x1000
        self.stepfile = out / 'step.ini'
        self.stepfile.write_text(f"savebin {self.obs[0].as_posix()} 'TEXT+${base:x}' ${size:x}\n"
                                 f"savebin {self.obs[1].as_posix()} 'TEXT+${sym['dream_system']:x}' $2\n"
                                 f"parse {self.pipe.guest_path}\n")
        entry = out / 'entry.ini'
        arm = out / 'arm.ini'
        arm.write_text(f"b pc = 'TEXT+${sym['dream_gate']:x}' :trace :quiet :file {self.stepfile.as_posix()}\n")
        entry.write_text(f"b VBL = 'VBL+1' :once :trace :quiet :file {arm.as_posix()}\n")
        env = dict(os.environ, PATH='C:/msys64/ucrt64/bin;' + os.environ.get('PATH', ''))
        self.argv = [str(HATARI), '--machine', 'ste', '--memsize', '4', '--tos', str(TOS),
                     '--fast-boot', 'true', '--cpu-exact', 'true', '--compatible', 'true',
                     '--sound', 'off', '--confirm-quit', 'off', '--statusbar', 'false',
                     '--fast-forward', 'true', '--disable-video', 'true', '--frameskips', '0',
                     '--parse', 'prg:' + str(entry), '--log-file', str(out / 'hatari.log'), str(program / 'GAME.PRG')]
        self.log = (out / 'process.log').open('wb')
        self.proc = subprocess.Popen(self.argv, cwd=program, env=env, stdout=self.log, stderr=self.log,
                                     creationflags=subprocess.CREATE_NO_WINDOW)
        self.last, self.ticks, self.pending = time.monotonic(), 0, None
        threading.Thread(target=self._watch, daemon=True).start()
