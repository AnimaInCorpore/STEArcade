"""The STE picture (run/trackfld_sim: the translated logic and render.s on Musashi with its Blitter) against the
reference renderer, frame by frame, in the shown colours.

    python render_test.py [frames] [--seed N] [--start F] [--every K] [--shots DIR] [--stop] [--prof]

The logic runs as in logic_test.py (the reference's port schedule, ref/cover.py's inputs and cheats); every frame
render_frame draws, and the test reads the published buffer (the VBL's part is played by the test: it becomes the shown
one).  Expected: the reference's pens (machine.Video.render_raw at the frame's end, raw lines 16-239) through the pen
map (tools/assets.py: build/trackfld/tf_penmap.bin).  Checked from frame --start on, every --every-th: the 256 x 224
picture exact, the side bands (screen x 0-31, 288-319: on 16-pixel groups) black.  Reports the 68000 cycles a picture
(CPU and Blitter: Musashi's count of render_frame, the logic apart).
"""
from pathlib import Path
import argparse
import bisect
import collections
import random
import sys
import numpy as np
sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[1] / 'ref'),
                str(Path(__file__).resolve().parents[3] / 'engine')]
from machine68k import Register as R
from sim import Sim, TRAP1
from machine import TrackFieldPort, Video
from paths import ROOT, build_dir
import cover

BUILD = build_dir('trackfld')
PCS = __import__('os').environ.get('PCS')   # (a routine: its sampled cycles by offset, with --prof)
LB, PIC_TOP, LINES, LEFT = 160, 20, 224, 32
AREAS = ((0x1800, 0x2000), (0x2800, 0x4000))


def planes_to_idx(words):
    """[..., 4] plane words (big-endian ints) -> [..., 16] indices"""
    bits = np.arange(15, -1, -1)
    out = np.zeros(words.shape[:-1] + (16,), np.uint8)
    for p in range(4):
        out |= (((words[..., p, None] >> bits) & 1) << p).astype(np.uint8)
    return out


def ste_picture(mem, base):
    """[224, 320] indices of the buffer's picture lines"""
    raw = bytes(mem.r_block(base + PIC_TOP * LB, LINES * LB))
    arr = np.frombuffer(raw, '>u2').reshape(LINES, 20, 4).astype(np.int64)
    return planes_to_idx(arr).reshape(LINES, 320)


def expected(v, m, pmap):
    return pmap[v.render_raw(m.mem)[16:240]]


class Harness:
    """the simulator build and the reference in lock-step (logic_test.py's schedule), a picture each frame"""

    def __init__(self, seed, prof=False, tag='trackfld_sim'):
        run = ROOT / 'run' / tag
        self.s = s = Sim(str(run / 'TRACKFLD.PRG'), run_dir=run, ram_kib=16384)
        self.sym = sym = {k: v + s.base for k, v in s.symbols(BUILD / (tag + '.map')).items()}
        self.mem, self.cpu = s.mem, s.cpu
        self.bad = {sym['main_badpc'], sym['main_badpc'] + 4}
        self.base = sym['tf_mem']
        self.m = m = TrackFieldPort(*cover.dsw(seed))
        self.mem.w8(sym['io_dsw1'], m.dsw1)
        self.mem.w8(sym['io_dsw2'], m.dsw2)
        for n in ('io_sys', 'io_in0', 'io_in1'):
            self.mem.w8(sym[n], 0xFF)
        self.seed = seed
        self.rnd = random.Random(seed)
        self.state = {'two': seed in (10, 11)}
        self.cyc = collections.Counter()
        self.prof = collections.Counter() if prof else None
        self.prof_start = 0
        self.pcs = collections.Counter()
        import re as _re
        absolute = {m[1] for m in _re.finditer(r'\s0x[0-9a-f]{8} (\S+?): \S+ abs', (BUILD / (tag + '.map')).read_text())}
        labels = sorted((x, k) for k, x in sym.items() if not k.startswith(('M0', 'L')) and k not in absolute)
        self.lv, self.labels = [x for x, _ in labels], labels
        self.run_to({sym['sim_wait']})
        m.frame = -1
        m.run_to_idle()
        m.booted = True
        self.f = 0

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

    def frame(self, inputs=None):
        """one arcade frame and its picture -> the published buffer's base"""
        m, mem, sym, f = self.m, self.mem, self.sym, self.f
        if inputs is None:
            m.system, m.in0, m.in1 = cover.inputs(f, self.rnd, self.state)
            before = bytes(m.mem)
            cover.cheats(self.seed, f, m, self.state)
            after = bytes(m.mem)
            for lo, hi in AREAS:
                for a in range(lo, hi):
                    if before[a] != after[a]:
                        mem.w8(self.base + a, after[a])
        else:
            m.system, m.in0 = inputs
        for n, x in (('io_sys', m.system), ('io_in0', m.in0), ('io_in1', m.in1)):
            mem.w8(sym[n], x)
        mem.w8(sym['vbl_pending'], 1)
        m.frame = f
        m.run_frame_port()
        m.frame = f
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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('frames', nargs='?', type=int, default=600)
    ap.add_argument('--seed', type=int, default=1)
    ap.add_argument('--start', type=int, default=0, help='compare from this frame on')
    ap.add_argument('--every', type=int, default=1)
    ap.add_argument('--shots', default=None)
    ap.add_argument('--stop', action='store_true', help='stop at the first difference')
    ap.add_argument('--prof', action='store_true', help='sample render_frame\'s pc every 64 cycles: cycles by routine')
    ap.add_argument('--tag', default='trackfld_sim', help='the build in run/<tag> (build.py --sim --tag)')
    args = ap.parse_args()
    pmap = np.frombuffer((BUILD / 'tf_penmap.bin').read_bytes(), np.uint8)
    h = Harness(args.seed, args.prof, args.tag)
    h.prof_start = args.start
    v = Video()
    bad_frames = checked = 0
    for f in range(args.frames):
        base = h.frame()
        if base is None or f < args.start or (f - args.start) % args.every:
            continue
        got = ste_picture(h.mem, base)
        exp = expected(v, h.m, pmap)
        diff = got[:, LEFT:LEFT + 256] != exp
        n = int(diff.sum())
        nb = int((got[:, :LEFT] != 0).sum() + (got[:, LEFT + 256:] != 0).sum())
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
        elif args.shots and f % 500 == 0:
            save(args.shots, f, got, exp)
    n = max(1, h.cyc['n'])
    if args.prof:
        n = max(1, args.frames - args.start)
        tot = sum(h.prof.values())
        for k, c in h.prof.most_common(30):
            print('%-24s %8d cycles a picture %5.1f%%' % (k, c // n, 100 * c / tot))
        for off, c in sorted(h.pcs.items()):
            print('%s+%04x %7d' % (PCS, off, c // n))
    print('%s: %d frames checked (seed %d), %d differ; a picture: render_frame %d CPU cycles + %d Blitter bus cycles; '
          'the logic %d cycles a frame (Musashi)' % ('PASS' if not bad_frames else 'FAIL', checked, args.seed,
                                                    bad_frames, h.cyc['render'] // n, h.cyc['blit'] // n,
                                                    h.cyc['logic'] // n))
    return int(bad_frames != 0)


def save(d, f, got, exp):
    from PIL import Image
    cols = np.frombuffer((BUILD / 'tf_colours.bin').read_bytes(), np.uint8).reshape(16, 3)
    Path(d).mkdir(parents=True, exist_ok=True)
    e = np.zeros_like(got)
    e[:, LEFT:LEFT + 256] = exp
    dm = np.zeros((LINES, 320, 3), np.uint8)
    dm[:, LEFT:LEFT + 256][got[:, LEFT:LEFT + 256] != exp] = (255, 0, 255)
    dm[:, :LEFT][got[:, :LEFT] != 0] = (255, 255, 0)
    dm[:, LEFT + 256:][got[:, LEFT + 256:] != 0] = (255, 255, 0)
    Image.fromarray(np.hstack((cols[got], cols[e], dm))).save(Path(d) / ('r%05d.png' % f))


if __name__ == '__main__':
    sys.exit(main())
