"""Cost of a frame on Musashi (the sim build): the game logic (translated Z80 NMI, the VBL around it) and the
picture (render_frame, draw_sprites in it), CPU plus the Blitter model's bus cycles.

    python perf_test.py [frames] [first] [--prg P --map M] [--shot out.png]

Without --prg it builds run/dkong_sim/DKSIM.PRG (+ DKSIM.map): build.py --sim -D AUTOSTART=150 (a coin at frame 150,
then Mario walks right and jumps).  The game is not
deterministic in real time (its idle loop counts its spins, see README), so the VBL is raised here at every third visit
of the idle loop head (Z02BD), as logic_test.py injects the NMI: every build then plays the same frames and their
cycles compare exactly.  Musashi counts the 68000's own cycles: Hatari takes more (bus alignment, the borders).
"""
from pathlib import Path
import argparse, shutil, subprocess, sys
sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[3] / 'engine')]
from machine68k import Register as R
from sim import Sim, TRAP1
from paths import ROOT, build_dir

VISITS = 3


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('frames', nargs='?', type=int, default=1200)
    ap.add_argument('first', nargs='?', type=int, default=200)
    ap.add_argument('--prg')
    ap.add_argument('--map')
    ap.add_argument('--shot', help='the last frame as a PNG')
    a = ap.parse_args()
    if not a.prg:
        run = ROOT / 'run' / 'dkong_sim'
        run.mkdir(parents=True, exist_ok=True)
        a.prg, a.map = str(run / 'DKSIM.PRG'), str(run / 'DKSIM.map')
        subprocess.run([sys.executable, str(Path(__file__).resolve().parent / 'build.py'), '--sim', '-D', 'AUTOSTART=150',
                        '--out', a.prg], check=True, stdout=subprocess.DEVNULL)
        shutil.copy(build_dir('dkong') / 'dkong.map', a.map)
    s = Sim(a.prg, ram_kib=16384, run_dir=Path(a.prg).parent)
    cpu, mem = s.cpu, s.mem
    sym = {k: v + s.base for k, v in s.symbols(a.map).items()}
    idle, render, sprites = sym['Z02BD'], sym['render_frame'], sym['draw_sprites']
    edge = sym.get('sprite_edge')

    def step():
        c = cpu.execute(1).cycles + s.blitter.cycles
        s.blitter.cycles = 0
        return c

    def to_idle(measure):
        """Run to the idle loop head; with measure: (total, render_frame, draw_sprites) cycles, edge sprites."""
        total = pic = spr = edges = 0
        ret_r = ret_s = None
        while True:
            pc = cpu.r_pc()
            if pc == idle:
                return total, pic, spr, edges
            if pc == TRAP1:
                s.gemdos()
                if s.terminated:
                    raise RuntimeError('program ended')
                continue
            if pc == 0x600:
                raise RuntimeError('exception')
            if not measure:
                cpu.execute(1)
                s.blitter.cycles = 0
                continue
            if pc == render:
                ret_r = mem.r32(cpu.r_reg(R.A7))
            elif pc == sprites:
                ret_s = mem.r32(cpu.r_reg(R.A7))
            elif pc == ret_r:
                ret_r = None
            elif pc == ret_s:
                ret_s = None
            if pc == edge:
                edges += 1
            c = step()
            total += c
            if ret_r is not None:
                pic += c
            if ret_s is not None:
                spr += c

    to_idle(False)
    frames = visits = 0
    logic, pics, sprs, edge_n = [], [], [], 0
    while frames < a.frames:
        cpu.execute(1)                         # (off the loop head)
        to_idle(False)
        visits += 1
        if visits % VISITS:
            continue
        assert s.irq(4, 28), 'VBL masked at the idle loop'
        frames += 1
        t, p, sp, e = to_idle(frames > a.first)
        if frames > a.first:
            logic.append(t - p)
            pics.append(p)
            sprs.append(sp)
            edge_n += e
    if a.shot:
        from PIL import Image
        Image.fromarray(s.screen_rgb()).save(a.shot)
    n = len(logic)
    tot = [l + p for l, p in zip(logic, pics)]
    print(f'{n} frames ({a.first + 1}..{a.frames}), cycles a frame (CPU + Blitter bus): total {sum(tot) / n:.1f}, '
          f'logic {sum(logic) / n:.1f}, picture {sum(pics) / n:.1f} (draw_sprites {sum(sprs) / n:.1f}); '
          f'max total {max(tot)}; edge sprites drawn {edge_n}; frame sum {sum(tot)}')


if __name__ == '__main__':
    main()
