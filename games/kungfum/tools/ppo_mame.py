"""Private synchronous MAME bridge; does not import Torch or alter canonical builds."""
import os
from pathlib import Path
import selectors
import shutil
import subprocess
import tempfile
import time

ROOT = Path(__file__).resolve().parents[3]


class Mame:
    def __init__(self, out, timeout=120):
        self.out = Path(out).resolve()
        self.out.mkdir(parents=True, exist_ok=True)
        self.directory = tempfile.TemporaryDirectory(prefix='kf-mame-')
        self.log = (self.out / 'mame.log').open('w')
        exe = os.environ.get('MAME') or shutil.which('mame')
        if not exe:
            raise RuntimeError('MAME not found; set MAME')
        self.process = subprocess.Popen([
            exe, 'kungfum', '-rompath', str(ROOT / 'assets/roms'), '-window', '-video', 'none',
            '-sound', 'none', '-nothrottle', '-skip_gameinfo', '-debug', '-debugger', 'none',
            '-autoboot_delay', '0', '-autoboot_script', str(Path(__file__).with_suffix('.lua')),
            '-seconds_to_run', '0'], cwd=self.directory.name, stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=self.log, text=True, bufsize=1)
        self.selector = selectors.DefaultSelector()
        self.selector.register(self.process.stdout, selectors.EVENT_READ)
        self.timeout = timeout

    def step(self, frames, system=255, p1=255):
        if not 1 <= frames <= 900 or not 0 <= system <= 255 or not 0 <= p1 <= 255:
            raise ValueError('invalid MAME step')
        self.process.stdin.write(f'step {frames} {system} {p1}\n')
        self.process.stdin.flush()
        deadline = time.monotonic() + self.timeout
        while True:
            if not self.selector.select(max(0, deadline - time.monotonic())):
                raise TimeoutError(f'MAME bridge timed out; see {self.out / "mame.log"}')
            line = self.process.stdout.readline()
            if not line:
                raise RuntimeError(f'MAME exited ({self.process.poll()}); see {self.out / "mame.log"}')
            if not line.startswith('KF1 '):
                self.log.write(line); self.log.flush()
                continue
            _, frame, scroll, pc, deaths, ram, sprites, pcs = line.rstrip('\n').split(' ', 7)
            return dict(frame=int(frame), scroll=int(scroll), pc=int(pc), deaths=int(deaths), ram=bytes.fromhex(ram),
                        sprites=bytes.fromhex(sprites), pcs=[int(p, 16) for p in pcs.split(',') if p])

    def close(self):
        if self.process.poll() is None:
            try:
                self.process.stdin.write('quit\n'); self.process.stdin.flush()
                self.process.wait(timeout=5)
            except (BrokenPipeError, subprocess.TimeoutExpired):
                self.process.kill(); self.process.wait()
        self.process.stdin.close()
        self.process.stdout.close()
        self.selector.close()
        self.log.close()
        self.directory.cleanup()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
