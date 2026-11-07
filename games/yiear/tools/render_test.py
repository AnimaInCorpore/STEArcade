"""The STE picture (run/yiear_sim: the translated logic and render.s on Musashi with its Blitter) against the reference
renderer, frame by frame, in the shown colours.

    python render_test.py [frames] [--seed N] [--start F] [--every K] [--shots DIR] [--stop] [--tag T]

The logic runs in lock-step with the reference (tools/machine.py YieArPort: the IRQ and the eight NMIs at the idle
point $807C, the inputs of ref/cover.py's play); every frame render_frame draws and the test reads the published buffer
(the VBL's part is played by the test: it becomes the shown one).  Expected: the reference's pens (Video.render_raw at
the same point) through the pen map (tools/assets.py: build/yiear/ya_penmap.bin).  Checked from frame --start on, every
--every-th: the 256 x 224 picture exact, the side bands (screen x 0-31, 288-319) black.  Reports the 68000 cycles a
picture (CPU and Blitter: Musashi's count of render_frame, the logic apart).
"""
from pathlib import Path
import argparse
import collections
import random
import sys
import numpy as np
sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[1] / 'ref'),
                str(Path(__file__).resolve().parents[3] / 'engine')]
from machine68k import Register as R
from sim import Sim, TRAP1
import machine
import cover
from paths import ROOT, build_dir

BUILD = build_dir('yiear')
LB, PIC_TOP = 160, 20


def planes_to_idx(words):
    bits = np.arange(15, -1, -1)
    out = np.zeros(words.shape[:-1] + (16,), np.uint8)
    for p in range(4):
        out |= (((words[..., p, None] >> bits) & 1) << p).astype(np.uint8)
    return out


def ste_picture(mem, base):
    """[224, 320] indices of the buffer's picture lines"""
    raw = bytes(mem.r_block(base + PIC_TOP * LB, 224 * LB))
    arr = np.frombuffer(raw, '>u2').reshape(224, 20, 4).astype(np.int64)
    return planes_to_idx(arr).reshape(224, 320)


class Harness:
    def __init__(self, seed, tag='yiear_sim'):
        run = ROOT / 'run' / tag
        self.s = s = Sim(str(run / 'YIEAR.PRG'), run_dir=run, ram_kib=16384)
        self.sym = sym = {k: v + s.base for k, v in s.symbols(BUILD / (tag + '.map')).items()}
        self.mem, self.cpu = s.mem, s.cpu
        self.bad = {sym['main_badpc'], sym['main_badpc'] + 4}
        self.m = m = machine.YieArPort(*cover.dsws(seed))
        self.seed = seed
        self.rnd = random.Random(seed)
        self.state = {'two': seed == 9}
        self.cyc = collections.Counter()
        mem = self.mem
        mem.w8(sym['io_dsw1'], m.dsw1)
        mem.w8(sym['io_dsw2'], m.dsw2)
        mem.w8(sym['io_dsw3'], m.dsw3)
        for n in ('io_sys', 'io_in1', 'io_in2'):
            mem.w8(sym[n], 0xFF)
        self.run_to({sym['sim_wait']})
        m.boot()
        m.run_to_idle()
        m.booted = True
        self.f = 0

    def run_to(self, targets, count=None):
        cpu, s = self.cpu, self.s
        total = 0
        while total < 2_000_000_000:
            total += cpu.execute(2000).cycles
            pc = cpu.r_pc()
            if pc in targets:
                if count is not None:
                    self.cyc[count] += total
                return pc
            if pc in self.bad or s.terminated:
                raise RuntimeError('CPU stopped at %06x, d7=%08x' % (pc - s.base, cpu.r_reg(R.D7)))
            if pc == TRAP1:
                s.gemdos()
        raise RuntimeError('CPU timeout at %06x' % (cpu.r_pc() - s.base))

    def resume(self):
        sp = self.cpu.r_reg(R.A7)
        self.cpu.w_pc(self.mem.r32(sp))
        self.cpu.w_reg(R.A7, sp + 4)

    def frame(self):
        """one arcade frame and its picture -> the published buffer's base"""
        m, mem, sym, f = self.m, self.mem, self.sym, self.f
        m.frame = f
        m.system, m.in1, m.in2 = cover.inputs(f, self.rnd, self.state)
        for n, v in (('io_sys', m.system), ('io_in1', m.in1), ('io_in2', m.in2)):
            mem.w8(sym[n], v)
        mem.w8(sym['vbl_pending'], 1)
        m.run_frame_port()
        m.frame = f
        self.resume()
        self.run_to({sym['sim_render_start']}, 'logic')
        self.resume()
        b0 = self.s.blitter.cycles
        self.run_to({sym['sim_frame_done']}, 'render')
        self.cyc['blit'] += self.s.blitter.cycles - b0
        self.cyc['n'] += 1
        ready = mem.r8(sym['frame_ready'])            # (vbl_video's bookkeeping: the published buffer shown)
        mem.w16(sym['prev_idx'], mem.r16(sym['shown_idx']))
        if ready:
            mem.w8(sym['frame_ready'], 0)
            mem.w16(sym['shown_idx'], ready - 1)
        base = mem.r32(sym['buf_base'] + 4 * (ready - 1)) if ready else None
        self.resume()
        self.run_to({sym['sim_wait']})
        self.f += 1
        return base


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('frames', nargs='?', type=int, default=600)
    ap.add_argument('--seed', type=int, default=1)
    ap.add_argument('--start', type=int, default=0, help='compare from this frame on')
    ap.add_argument('--every', type=int, default=1)
    ap.add_argument('--shots', default=None)
    ap.add_argument('--stop', action='store_true', help='stop at the first difference')
    ap.add_argument('--tag', default='yiear_sim', help='the build in run/<tag> (build.py --sim --tag)')
    args = ap.parse_args()
    pmap = np.frombuffer((BUILD / 'ya_penmap.bin').read_bytes(), np.uint8)
    h = Harness(args.seed, args.tag)
    bad_frames = checked = 0
    for f in range(args.frames):
        base = h.frame()
        if base is None or f < args.start or (f - args.start) % args.every:
            continue
        got = ste_picture(h.mem, base)
        exp = pmap[h.m.video_raw()[16:240]]
        diff = got[:, 32:288] != exp
        n = int(diff.sum())
        nb = int((got[:, :32] != 0).sum() + (got[:, 288:] != 0).sum())
        checked += 1
        if n or nb:
            bad_frames += 1
            ys, xs = np.nonzero(diff)
            print('frame %d: %d pixels differ, %d band pixels; first (y, x) at %s' % (
                f, n, nb, list(zip(ys[:5].tolist(), xs[:5].tolist()))), flush=True)
            if args.shots:
                save(args.shots, f, got, exp)
            if args.stop:
                break
    n = max(1, h.cyc['n'])
    print('%s: %d frames checked (seed %d), %d differ; a picture: render_frame %d CPU cycles + %d Blitter bus cycles; '
          'the logic %d cycles a frame (Musashi)' % ('PASS' if not bad_frames else 'FAIL', checked, args.seed,
                                                    bad_frames, h.cyc['render'] // n, h.cyc['blit'] // n,
                                                    h.cyc['logic'] // n))
    return int(bad_frames != 0)


def save(d, f, got, exp):
    from PIL import Image
    cols = np.frombuffer((BUILD / 'ya_colours.bin').read_bytes(), np.uint8).reshape(16, 3)
    Path(d).mkdir(parents=True, exist_ok=True)
    e = np.zeros_like(got)
    e[:, 32:288] = exp
    dm = np.zeros((224, 320, 3), np.uint8)
    dm[:, 32:288][got[:, 32:288] != exp] = (255, 0, 255)
    dm[:, :32][got[:, :32] != 0] = (255, 255, 0)
    dm[:, 288:][got[:, 288:] != 0] = (255, 255, 0)
    Image.fromarray(np.hstack((cols[got], cols[e], dm))).save(Path(d) / ('r%05d.png' % f))


if __name__ == '__main__':
    sys.exit(main())
