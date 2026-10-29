"""The STE picture (run/mrdo_sim: the translated logic and render.s on Musashi with its Blitter) against the reference
renderer, frame by frame, in the shown colours.

    python render_test.py [frames] [--seed N] [--start F] [--every K] [--shots DIR] [--stop] [--prof]

The logic runs as in logic_test.py (the reference's port schedule, ref/cover.py's inputs and cheats); every frame
render_frame draws, and the test reads the published buffer (the VBL's part is played by the test: it becomes the shown
one).  Expected: the reference's pens (machine.MrDo.render_raw at the frame's end) turned as MAME's ROT270 turns them
(render_rgb), through the pen map (tools/assets.py: build/mrdo/md_penmap.bin).  Checked from frame --start on, every
--every-th: the 192 x 240 picture exact, the side bands (screen x 0-63, 256-319: on 16-pixel groups) black.  Reports
the 68000 cycles a picture (CPU and Blitter: Musashi's count of render_frame, the logic apart).
"""
from pathlib import Path
import argparse
import bisect
import collections
import random
import re
import sys
import numpy as np
sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[1] / 'ref'),
                str(Path(__file__).resolve().parents[3] / 'engine')]
from machine68k import Register as R
from sim import Sim, TRAP1
from machine import MrDoPort, VIS_X0, VIS_X1, VIS_Y0, VIS_Y1
from paths import ROOT, build_dir
import cover

BUILD = build_dir('mrdo')
PCS = __import__('os').environ.get('PCS')   # (a routine: its sampled cycles by offset, with --prof)
LB, GUARD, LEFT, W, H = 160, 24, 64, 192, 240
IN_P1, IN_P2, IN_DSW1, IN_DSW2 = 0xA000, 0xA001, 0xA002, 0xA003


def planes_to_idx(words):
    """[..., 4] plane words (big-endian ints) -> [..., 16] indices"""
    bits = np.arange(15, -1, -1)
    out = np.zeros(words.shape[:-1] + (16,), np.uint8)
    for p in range(4):
        out |= (((words[..., p, None] >> bits) & 1) << p).astype(np.uint8)
    return out


def ste_picture(mem, base, lines=H, first=GUARD):
    """[lines, 320] indices of the buffer's lines from `first`"""
    raw = bytes(mem.r_block(base + first * LB, lines * LB))
    arr = np.frombuffer(raw, '>u2').reshape(lines, 20, 4).astype(np.int64)
    return planes_to_idx(arr).reshape(lines, 320)


def expected(m, pmap):
    """the reference's picture in colour indices: [240, 192]"""
    raw = m.render_raw()[VIS_Y0:VIS_Y1, VIS_X0:VIS_X1]
    return np.ascontiguousarray(pmap[raw].T[::-1])


class Harness:
    """the simulator build and the reference in lock-step (logic_test.py's schedule), a picture each frame"""

    def __init__(self, seed, prof=False, tag='mrdo_sim'):
        run = ROOT / 'run' / tag
        self.s = s = Sim(str(run / 'MRDO.PRG'), run_dir=run, ram_kib=16384)
        self.sym = sym = {k: v + s.base for k, v in s.symbols(BUILD / (tag + '.map')).items()}
        self.mem, self.cpu = s.mem, s.cpu
        self.bad = {sym['z80_badpc'], sym['z80_badpc'] + 4}
        self.a6 = sym['g_block'] + 0x8000
        self.m = m = MrDoPort(*cover.dsw(seed))
        m.cpu.afmask = 0xc1
        for a, x in ((IN_P1, 0xFF), (IN_P2, 0xFF), (IN_DSW1, m.dsw1), (IN_DSW2, m.dsw2)):
            self.mem.w8(self.addr(a), x)
        self.seed = seed
        self.rnd = random.Random(seed)
        self.state = {'seed': seed}
        self.cyc = collections.Counter()
        self.prof = collections.Counter() if prof else None
        self.prof_start = 0
        self.pcs = collections.Counter()
        absolute = {x[1] for x in re.finditer(r'\s0x[0-9a-f]{8} (\S+?): \S+ abs', (BUILD / (tag + '.map')).read_text())}
        labels = sorted((x, k) for k, x in sym.items() if not k.startswith(('Z', 'S0', 'L')) and k not in absolute)
        self.lv, self.labels = [x for x, _ in labels], labels
        self.run_to({sym['sim_wait']})
        m.frame = -1
        m.run_to_idle()
        m.booted = True
        self.f = 0

    def addr(self, a):
        return self.a6 + (a if a < 0x8000 else a - 0x10000)

    def run_to(self, targets, count=None):
        cpu, s = self.cpu, self.s
        total = 0
        chunk = 64 if (self.prof is not None and count == 'render' and self.f >= self.prof_start) else 2000
        while total < 2_000_000_000:
            n = cpu.execute(chunk).cycles
            total += n
            if chunk == 64:
                pc = cpu.r_pc()
                i = bisect.bisect_right(self.lv, pc) - 1
                name = self.labels[i][1] if i >= 0 else '?'
                self.prof[name] += n
                if name == PCS:
                    self.pcs[pc - self.labels[i][0]] += n
            pc = cpu.r_pc()
            if pc in targets:
                if count is not None and self.f >= self.prof_start:
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
        cover.apply_inputs(m, f, self.rnd, self.state)
        for a, x in zip((IN_P1, IN_P2, IN_DSW1), (m.p1, m.p2, m.dsw1)):
            mem.w8(self.addr(a), x)
        before = bytes(m.ram)
        cover.cheats(self.seed, f, m, self.state)
        after = bytes(m.ram)
        for i in range(0x1000):
            if before[i] != after[i]:
                mem.w8(self.addr(0xE000 + i), after[i])
        mem.w8(sym['vbl_pending'], 1)
        m.frame = f
        m.run_frame_port()
        self.resume()
        self.run_to({sym['sim_render_start']}, 'logic')
        self.resume()
        b0 = self.s.blitter.cycles
        self.run_to({sym['sim_frame_done']}, 'render')
        if self.f >= self.prof_start:
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


def check(h, base, pmap):
    """-> (picture differences, band pixels, got [240, 320], expected [240, 192])"""
    got = ste_picture(h.mem, base)
    exp = expected(h.m, pmap)
    n = int((got[:, LEFT:LEFT + W] != exp).sum())
    nb = int((got[:, :LEFT] != 0).sum() + (got[:, LEFT + W:] != 0).sum())
    return n, nb, got, exp


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('frames', nargs='?', type=int, default=600)
    ap.add_argument('--seed', type=int, default=1)
    ap.add_argument('--start', type=int, default=0, help='compare from this frame on')
    ap.add_argument('--every', type=int, default=1)
    ap.add_argument('--shots', default=None)
    ap.add_argument('--stop', action='store_true', help='stop at the first difference')
    ap.add_argument('--prof', action='store_true', help='sample render_frame\'s pc every 64 cycles: cycles by routine')
    ap.add_argument('--tag', default='mrdo_sim', help='the build in run/<tag> (build.py --sim --tag)')
    args = ap.parse_args()
    pmap = np.frombuffer((BUILD / 'md_penmap.bin').read_bytes(), np.uint8)
    h = Harness(args.seed, args.prof, args.tag)
    h.prof_start = args.start
    bad_frames = checked = 0
    for f in range(args.frames):
        base = h.frame()
        if base is None or f < args.start or (f - args.start) % args.every:
            continue
        n, nb, got, exp = check(h, base, pmap)
        checked += 1
        if n or nb:
            bad_frames += 1
            ys, xs = np.nonzero(got[:, LEFT:LEFT + W] != exp)
            print('frame %d: %d pixels differ, %d band pixels; first (y, x) at %s' % (
                f, n, nb, list(zip(ys[:5].tolist(), xs[:5].tolist()))), flush=True)
            if args.shots:
                save(args.shots, f, got, exp)
            if args.stop:
                break
        elif args.shots and f % 100 == 0:
            save(args.shots, f, got, exp)
    n = max(1, h.cyc['n'])
    if args.prof:
        n = max(1, args.frames - args.start)
        tot = sum(h.prof.values())
        g = collections.Counter()
        for k, c in h.prof.items():
            g[re.sub(r'^(shp)_\w+', r'\1_*', k)] += c
        for k, c in g.most_common(30):
            print('%-24s %8d cycles a picture %5.1f%%' % (k, c // n, 100 * c / tot))
        for off, c in sorted(h.pcs.items()):
            print('%s+%04x %7d' % (PCS, off, c // n))
    print('%s: %d frames checked (seed %d), %d differ; a picture: render_frame %d CPU cycles + %d Blitter bus cycles; '
          'the logic %d cycles a frame (Musashi)' % ('PASS' if not bad_frames else 'FAIL', checked, args.seed,
                                                    bad_frames, h.cyc['render'] // n, h.cyc['blit'] // n,
                                                    h.cyc['logic'] // n))
    return int(bad_frames != 0)


def colours():
    b = (BUILD / 'md_colours.bin').read_bytes()
    return np.array([tuple(b[i:i + 3]) for i in range(0, 48, 3)], np.uint8)


def save(d, f, got, exp):
    from PIL import Image
    cols = colours()
    Path(d).mkdir(parents=True, exist_ok=True)
    e = np.zeros_like(got)
    e[:, LEFT:LEFT + W] = exp
    dm = np.zeros((H, 320, 3), np.uint8)
    dm[:, LEFT:LEFT + W][got[:, LEFT:LEFT + W] != exp] = (255, 0, 255)
    dm[:, :LEFT][got[:, :LEFT] != 0] = (255, 255, 0)
    dm[:, LEFT + W:][got[:, LEFT + W:] != 0] = (255, 255, 0)
    Image.fromarray(np.hstack((cols[got], cols[e], dm))).save(Path(d) / ('r%05d.png' % f))


if __name__ == '__main__':
    sys.exit(main())
