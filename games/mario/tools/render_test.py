"""The STE picture (run/mario_sim: the translated logic and render.s on Musashi with its Blitter) against the reference
renderer, frame by frame, in the shown colours.

    python render_test.py [frames] [--seed N] [--start F] [--every K] [--shots DIR] [--stop] [--tag T]

The logic runs in lock-step with the reference (tools/machine.py: the NMI at the idle loop $01CB, the inputs of
ref/cover.py's play, MAME's cheats: free play, lives, bonus time); every frame render_frame draws and the test reads the
published buffer (the VBL's part is played by the test: it becomes the shown one).  Expected: the reference's pens
(Mario.render_raw at the same point) through the pen map (tools/assets.py: build/mario/tm_penmap.bin).  Checked from
frame --start on, every --every-th: the 256 x 224 picture exact, the side bands (screen x 0-31, 288-319) black.
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

BUILD = build_dir('mario')
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
    def __init__(self, seed, tag='mario_sim'):
        run = ROOT / 'run' / tag
        self.s = s = Sim(str(run / 'MARIO.PRG'), run_dir=run, ram_kib=16384)
        self.sym = sym = {k: v + s.base for k, v in s.symbols(BUILD / (tag + '.map')).items()}
        self.mem, self.cpu = s.mem, s.cpu
        self.bad = {sym['z80_badpc'], sym['z80_badpc'] + 4}
        self.a6 = sym['g_block'] + 0x8000
        self.m = m = machine.Mario()
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
            if cpu.pc == 0x1CB:
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
            self.joy = self.rnd.choice([0, 0, 1, 2, 16, 17, 18, 1, 2, 0])
            self.jleft = self.rnd.randint(3, 40)
        self.jleft -= 1
        two = self.seed % 5 == 0
        return (self.joy, self.joy if two else 0, f % 400 == 30, f % 500 in (60, 61, 62),
                two and f % 500 in (200, 201))

    def frame(self):
        """one arcade frame and its picture -> the published buffer's base"""
        m, mem, sym, f = self.m, self.mem, self.sym, self.f
        p1, p2, coin, st1, st2 = self.inputs(f)
        m.ram[0x6BF0 - 0x6000] = 1                      # MAME's cheats: free play, lives, bonus time
        m.ram[0x6116 - 0x6000] = 7
        m.ram[0x66D4 - 0x6000] = 0x99
        for a in (0x6BF0, 0x6116, 0x66D4):
            mem.w8(self.a6 + a, m.ram[a - 0x6000])
        m.set_inputs(p1=p1, p2=p2, coin=coin, start1=st1, start2=st2)
        mem.w8(self.a6 + 0x7A00, m.in0)
        mem.w8(self.a6 + 0x7A80, m.in1)
        mem.w8(sym['vbl_pending'], 1)
        # the reference: the NMI (when enabled) and the foreground to the idle loop
        cpu = m.cpu
        if m.nmi_mask:
            sp0 = cpu.sp
            cpu.nmi()
            while not (cpu.pc == 0x1CB and cpu.sp == sp0):      # (the handler returns to the idle loop's head)
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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('frames', nargs='?', type=int, default=600)
    ap.add_argument('--seed', type=int, default=1)
    ap.add_argument('--start', type=int, default=0, help='compare from this frame on')
    ap.add_argument('--every', type=int, default=1)
    ap.add_argument('--shots', default=None)
    ap.add_argument('--stop', action='store_true', help='stop at the first difference')
    ap.add_argument('--tag', default='mario_sim', help='the build in run/<tag> (build.py --sim --tag)')
    args = ap.parse_args()
    pmap = np.frombuffer((BUILD / 'tm_penmap.bin').read_bytes(), np.uint8)
    h = Harness(args.seed, args.tag)
    bad_frames = checked = 0
    for f in range(args.frames):
        base = h.frame()
        if base is None or f < args.start or (f - args.start) % args.every:
            continue
        got = ste_picture(h.mem, base)
        exp = pmap[h.m.render_raw()[16:240]]
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
    cols = np.frombuffer((BUILD / 'tm_colours.bin').read_bytes(), np.uint8).reshape(16, 3)
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
