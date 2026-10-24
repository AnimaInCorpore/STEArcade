"""Cost of Gun.Smoke's ticks on Musashi (sim build, CPU + Blitter): the game logic and render_frame, a picture every
tick, on the recorded play (build/gunsmoke/play_inputs.bin, play_search.py).

    python tools/perf_test.py [ticks] [first] [profile|logic]     (first: ticks not counted, default 1000)
        profile: render_frame's cycles by routine;  logic: the logic's cycles by routine (translated code as 'Z80')
    PERF_PCS=name: that routine's cycles by instruction offset (profile)
    PERF_EVERY=n: a picture every n-th tick only (Hatari draws about every 2.3rd), the means per picture drawn

Builds the sim (--sim -D PLAYBACK=1) first unless PERF_NOBUILD=1.  Musashi counts the 68000's own
cycles: Hatari takes about 1.35 times as many (bus alignment, interrupts, the Blitter's bus).
"""
from pathlib import Path
import bisect
import collections
import os
import subprocess
import sys

sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[1] / 'ref'),
                str(Path(__file__).resolve().parents[3] / 'engine')]
from machine68k import Register as R  # noqa: E402
from sim import Sim, TRAP1  # noqa: E402
from paths import ROOT, build_dir  # noqa: E402

EVERY = int(os.environ.get('PERF_EVERY', '1'))
PCS = os.environ.get('PERF_PCS')      # (a routine: its cycles by instruction offset too)


def main():
    ticks = int(sys.argv[1]) if len(sys.argv) > 1 else 2000
    first = int(sys.argv[2]) if len(sys.argv) > 2 else 1000
    mode = sys.argv[3] if len(sys.argv) > 3 else ''
    if not os.environ.get('PERF_NOBUILD'):
        cmd = [sys.executable, str(Path(__file__).with_name('build.py')), '--sim', '-D', 'PLAYBACK=1']
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL)
    run = ROOT / 'run' / 'gunsmoke_sim'
    s = Sim(str(run / 'GUNSMOKE.PRG'), ram_kib=16384, run_dir=run)
    mem, cpu = s.mem, s.cpu
    sym = {k: v + s.base for k, v in s.symbols(build_dir('gunsmoke') / 'gunsmoke_sim.map').items()}
    wait, done, render, bad = sym['sim_wait'], sym['sim_frame_done'], sym['render_frame'], sym['z80_badpc']
    import re
    absolute = {m[1] for m in re.finditer(r'\s0x[0-9a-f]{8} (\S+?): \S+ abs', (build_dir('gunsmoke') / 'gunsmoke_sim.map').read_text())}
    def group(k):
        return 'sprite routines (sfc*)' if re.fullmatch(r'sfc\d+', k) else k
    names = sorted((v, 'Z80' if k[0] == 'Z' and k[1:].isalnum() and len(k) > 4 and all(c in '0123456789ABCDEF' for c in k[1:])
                    else group(k)) for k, v in sym.items() if not k.startswith('.') and k not in absolute)
    addrs = [v for v, _ in names]
    by_name, by_pc = collections.Counter(), collections.Counter()
    mem.set_trace_mode(True)                         # (the Blitter model sees its registers)

    # (the shared Blitter starters' cycles, mostly the passes' bus cycles, go to their caller: 'caller>blit_go')
    entries = {sym[k]: k for k in ('blit_go', 'blit_go_lines', 'blit_go_fill', 'blit_go_copy') if k in sym}
    helper = [None, None]                            # (the caller's name, the return address)

    def name_of(pc):
        return names[bisect.bisect_right(addrs, pc) - 1][1]

    def run_to(targets, step=False):
        total = 0
        while total < 400_000_000:
            pc = cpu.r_pc()
            if pc in targets:
                return total
            if step:
                if helper[0] is None and pc in entries:
                    ret = mem.r32(cpu.r_reg(R.A7))
                    helper[0], helper[1] = name_of(ret) + '>blit_go', ret
                elif helper[0] is not None and pc == helper[1]:
                    helper[0] = None
                c = cpu.execute(1).cycles + s.blitter.cycles
                s.blitter.cycles = 0
                nm = helper[0] or name_of(pc)
                by_name[nm] += c
                if PCS and nm == PCS:
                    by_pc[pc - sym[PCS]] += c
                total += c
                continue
            r = cpu.execute(2000)                    # (the targets are loops: sim_wait, sim_frame_done, the stop)
            total += r.cycles + s.blitter.cycles
            s.blitter.cycles = 0
            pc = cpu.r_pc()
            if pc in targets:
                return total
            if pc in (bad, bad + 4) or s.terminated:
                raise RuntimeError(f'CPU stopped at {pc - s.base:06x}')
            if pc == TRAP1:
                s.gemdos()
        raise RuntimeError('timeout')

    def resume():
        sp = cpu.r_reg(R.A7)
        cpu.w_pc(mem.r32(sp))
        cpu.w_reg(R.A7, sp + 4)

    run_to({wait})
    logic, pics = [], []
    word = mem.r16(render)
    for f in range(ticks):
        draw = f % EVERY == 0
        mem.w16(render, 0x60fe)                      # (bra.s *: the logic stops at render_frame)
        mem.w8(sym['vbl_pending'], 1)
        resume()
        lc = run_to({render}, step=mode == 'logic' and f >= first)
        mem.w16(render, word if draw else 0x4e75)
        rc = run_to({done}, step=mode == 'profile' and f >= first)
        mem.w8(sym['frame_ready'], 0)                # (no VBL here takes the picture: the next one may be drawn)
        resume()
        lc += run_to({wait}, step=mode == 'logic' and f >= first)
        if f >= first:
            logic.append(lc)
            if draw:
                pics.append(rc)
    n, m = len(logic), len(pics)
    ps = sorted(pics)
    print(f'{n} ticks: logic mean {sum(logic) // n} max {max(logic)}; {m} pictures (CPU + Blitter) mean {sum(pics) // m} '
          f'median {ps[m // 2]} p90 {ps[m * 9 // 10]} max {ps[-1]}')
    print(f'at 8 MHz (Musashi cycles): {8e6 / (sum(logic) / n + sum(pics) / n):.1f} ticks a second with a picture each')
    if mode:
        tot = sum(by_name.values())
        for k, v in by_name.most_common(30):
            print(f'{k:28s} {v // (n if mode == "logic" else m):8d} {100 * v / tot:5.1f}%')
        if PCS:
            for off, v in sorted(by_pc.items()):
                print(f'{PCS}+{off:04x} {v // m:7d}')


if __name__ == '__main__':
    main()
