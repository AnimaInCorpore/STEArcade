"""The STE picture (run/dkong3_sim: the translated logic and render.s on Musashi with its Blitter) against the reference
renderer, frame by frame, in the shown colours.

    python render_test.py [frames] [--seed N] [--start F] [--every K] [--shots DIR] [--stop] [--tag T]

The logic runs in lock-step with the reference (tools/machine.py: the NMI at the idle loop $0249, the inputs of
ref/cover.py's play); every frame render_frame draws and the test reads the
published buffer (the VBL's part is played by the test: it becomes the shown one).  Expected: the reference's pens
(DK3.render_raw(wrap=False) at the same point: the STE port does not draw the sprites' wrap-around) through the pen map (tools/assets.py: build/dkong3/tm_penmap.bin).  Checked from
frame --start on, every --every-th: the 224 x 256 picture exact, the side bands (screen x 0-47, 272-319) black.
Reports the 68000 cycles a picture (CPU and Blitter: Musashi's count of render_frame, the logic apart).
"""
from pathlib import Path
import argparse
import collections
import random
import sys
import numpy as np
sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[3] / 'engine')]
from machine68k import Register as R
from sim import Sim, TRAP1
import machine
from paths import ROOT, build_dir

BUILD = build_dir('dkong3')
LB, PIC0 = 160, 16 * 160                  # (render.s: the picture's line 0 in a buffer)


def planes_to_idx(words):
    bits = np.arange(15, -1, -1)
    out = np.zeros(words.shape[:-1] + (16,), np.uint8)
    for p in range(4):
        out |= (((words[..., p, None] >> bits) & 1) << p).astype(np.uint8)
    return out


def ste_picture(mem, base):
    """[256, 320] indices of the buffer's picture lines"""
    raw = bytes(mem.r_block(base + PIC0, 256 * LB))
    arr = np.frombuffer(raw, '>u2').reshape(256, 20, 4).astype(np.int64)
    return planes_to_idx(arr).reshape(256, 320)


class Harness:
    def __init__(self, seed, tag='dkong3_sim', cheat=False):
        self.cheat = cheat
        run = ROOT / 'run' / tag
        self.s = s = Sim(str(run / 'DKONG3.PRG'), run_dir=run, ram_kib=16384)
        self.sym = sym = {k: v + s.base for k, v in s.symbols(BUILD / (tag + '.map')).items()}
        self.mem, self.cpu = s.mem, s.cpu
        self.bad = {sym['z80_badpc'], sym['z80_badpc'] + 4}
        self.a6 = sym['g_block'] + 0x8000
        self.m = m = machine.DK3()
        m.gfx = machine.Gfx()
        self.seed = seed
        self.rnd = random.Random(seed)
        self.joy = 0
        self.jleft = 0
        self.cyc = collections.Counter()
        self.run_to({sym['sim_wait']})
        self.run_ref_to_idle()
        self.f = 0

    def run_ref_to_idle(self):
        cpu = self.m.cpu
        n = 0
        while True:
            cpu.step()
            n += 1
            if cpu.pc == 0x249:
                return
            if n > 20_000_000:
                raise RuntimeError('the reference did not reach the idle loop')

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

    def inputs(self, f):
        if self.jleft == 0:
            self.joy = self.rnd.choice([0, 0, 1, 2, 4, 8, 16, 17, 18, 5, 9, 1, 2, 0])
            self.jleft = self.rnd.randint(3, 40)
        self.jleft -= 1
        two = self.seed % 5 == 0
        return (self.joy, self.joy if two else 0, f % 400 == 30, f % 500 in (60, 61, 62),
                two and f % 500 in (200, 201))

    def frame(self):
        """one arcade frame and its picture -> the published buffer's base"""
        m, mem, sym, f = self.m, self.mem, self.sym, self.f
        p1, p2, coin, st1, st2 = self.inputs(f)
        if self.cheat:                                  # MAME's cheats (credits, lives) and the stage poked while a game starts
            pokes = {0x6BF1: 0x63, 0x601A: 6}
            if f % 500 in range(63, 200):
                pokes[0x601B] = (self.seed + f // 500) % 3
            for a_, v_ in pokes.items():
                m.ram[a_ - 0x6000] = v_
                mem.w8(self.a6 + a_, v_)
            coin, st1 = coin or f % 500 == 30, st1 or f % 500 in (60, 61, 62)
        m.set_inputs(p1=p1, p2=p2, coin=coin, start1=st1, start2=st2)
        mem.w8(self.a6 + 0x7A00, m.in0)
        mem.w8(self.a6 + 0x7A80, m.in1)
        mem.w8(sym['vbl_pending'], 1)
        # the reference: the NMI (when enabled) and the foreground to the idle loop
        cpu = m.cpu
        if m.nmi_mask:
            sp0 = cpu.sp
            cpu.nmi()
            while not (cpu.pc == 0x249 and cpu.sp == sp0):      # (the handler returns to the idle loop's head)
                cpu.step()
            cpu.step()                                          # the foreground's pass: the flag the NMI set
        self.run_ref_to_idle()
        m.frame += 1
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


def expected(m, pmap):
    """the picture as indices: the arcade bitmap's lines 16-239 turned (display [Y][X] = raw [16 + X][255 - Y])"""
    return pmap[m.render_raw(wrap=False)[16:240]].T[::-1]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('frames', nargs='?', type=int, default=600)
    ap.add_argument('--seed', type=int, default=1)
    ap.add_argument('--start', type=int, default=0, help='compare from this frame on')
    ap.add_argument('--every', type=int, default=1)
    ap.add_argument('--shots', default=None)
    ap.add_argument('--cheat', action='store_true', help='credits, lives and the stage by RAM pokes (tools/logic_test.py --cheat)')
    ap.add_argument('--stop', action='store_true', help='stop at the first difference')
    ap.add_argument('--tag', default='dkong3_sim', help='the build in run/<tag> (build.py --sim --tag)')
    args = ap.parse_args()
    pmap = np.frombuffer((BUILD / 'tm_penmap.bin').read_bytes(), np.uint8)
    h = Harness(args.seed, args.tag, args.cheat)
    bad_frames = checked = 0
    for f in range(args.frames):
        base = h.frame()
        if base is None or f < args.start or (f - args.start) % args.every:
            continue
        got = ste_picture(h.mem, base)
        exp = expected(h.m, pmap)
        diff = got[:, 48:272] != exp
        n = int(diff.sum())
        nb = int((got[:, :48] != 0).sum() + (got[:, 272:] != 0).sum())
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
    cols = np.frombuffer((BUILD / 'tm_colours.bin').read_bytes(), np.uint8).reshape(16, 3)
    Path(d).mkdir(parents=True, exist_ok=True)
    e = np.zeros_like(got)
    e[:, 48:272] = exp
    dm = np.zeros((256, 320, 3), np.uint8)
    dm[:, 48:272][got[:, 48:272] != exp] = (255, 0, 255)
    dm[:, :48][got[:, :48] != 0] = (255, 255, 0)
    dm[:, 272:][got[:, 272:] != 0] = (255, 255, 0)
    Image.fromarray(np.hstack((cols[got], cols[e], dm))).save(Path(d) / ('r%05d.png' % f))


if __name__ == '__main__':
    sys.exit(main())
