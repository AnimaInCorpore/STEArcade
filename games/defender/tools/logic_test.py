"""Frame by frame: the translated program (run/defender_sim, Musashi) against the reference's port schedule
(machine.DefenderPort.run_frame_port) through the boot, attract, coin, start and play (ref/cover.py's inputs).

    python logic_test.py [frames] [--seed N] [--tag T]

Compared after the boot and every arcade frame: the RAM $0000-$BFFF (video RAM included; the 64 bytes below the stack
pointer are dead and left out), the palette, the CMOS, the view, the sound commands of the frame and the STE screen
(the planar picture: equal to the reference's picture, machine.render_pixels, at x + 14, the side bands 0).  Reports
the 68000 cycles a frame (Musashi; the screen writes included).
"""
from pathlib import Path
import argparse
import os
import random
import sys
sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[1] / 'ref'),
                str(Path(__file__).resolve().parents[3] / 'engine')]
from machine68k import Register as R
from sim import Sim, TRAP1
from machine import DefenderPort, factory_cmos, render_pixels
import numpy as np

PIC_TOP, LB = 18, 160


def picture(buf):
    """the planar screen's picture lines (240 lines of 160 bytes) -> pens [240, 320]"""
    a = np.frombuffer(buf, np.uint8).reshape(240, 20, 4, 2)
    w = (a[..., 0].astype(np.uint16) << 8) | a[..., 1]                    # [line, group, plane] words
    bits = (w[..., None] >> (15 - np.arange(16))) & 1                    # [line, group, plane, pixel]
    pix = (bits * (1 << np.arange(4))[None, None, :, None]).sum(axis=2)   # [line, group, pixel]
    return pix.reshape(240, 320).astype(np.uint8)
from paths import ROOT, build_dir
import cover

BUILD = build_dir('defender')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('frames', nargs='?', type=int, default=3000)
    ap.add_argument('--seed', type=int, default=1)
    ap.add_argument('--quiet', action='store_true')
    ap.add_argument('--tag', default='defender_sim')
    ap.add_argument('--nopic', action='store_true', help='do not compare the screen with the reference picture')
    ap.add_argument('--profile', action='store_true', help='where the 68000 cycles go (a sample every 200 cycles)')
    ap.add_argument('--trace', type=int, default=-1, help='compare the executed instructions of this frame')
    ap.add_argument('--wtrace', type=int, default=-1, help='compare the writes to the 6809 RAM of this frame, in order')
    args = ap.parse_args()
    run = ROOT / 'run' / args.tag
    s = Sim(str(run / 'DEFENDER.PRG'), run_dir=run, ram_kib=4096)
    sym = {k: v + s.base for k, v in s.symbols(BUILD / (args.tag + '.map')).items()}
    mem, cpu = s.mem, s.cpu
    wait, done = sym['sim_wait'], sym['sim_frame_done']
    bad = set(range(sym['main_badpc'], sym['main_badpc'] + 12, 2))   # (m6809_daa follows)
    base = sym['df_mem']
    m = DefenderPort(factory_cmos())
    rnd = random.Random(args.seed)
    cycles = [0]

    import bisect, collections, re
    names = sorted((a, n) for n, a in sym.items() if not n.startswith('.') and not re.fullmatch('M[0-9A-F]{6}(_.*)?', n)
                   and not n.isupper())                       # (the translation's labels and the constants left out)
    names = [(a, 'df_terrain' if re.fullmatch(r'tc\d+(_.*)?', n) else n) for a, n in names]   # (its columns' code)
    names.append((sym['main_page_tables'] - 1, 'translated code'))
    names.sort()
    code0 = min(a for n, a in sym.items() if re.fullmatch('M[0-9A-F]{6}', n))
    names.append((code0, 'translated code'))
    names.sort()
    naddr = [a for a, n in names]
    prof = collections.Counter()
    mlabs = sorted((a, int(n[1:], 16)) for n, a in sym.items() if re.fullmatch('M[0-9A-F]{6}', n))
    maddr = [a for a, n in mlabs]
    prof6809 = collections.Counter()
    profcall = collections.Counter()
    profins = collections.Counter()

    def run_to(targets):
        total = 0
        while total < 2_000_000_000:
            r = cpu.execute(200 if args.profile else 2000).cycles
            total += r
            pc = cpu.r_pc()
            if args.profile:
                nm = names[bisect.bisect_right(naddr, pc) - 1][1]
                prof[nm] += 1
                if nm == 'translated code':
                    v = mlabs[bisect.bisect_right(maddr, pc) - 1][1]
                    prof6809['%05X' % (v & ~0x3F)] += 1
                    profins[v] += 1
                elif nm in ('main_io_r', 'main_io_w', 'main_vlist', 'main_dispatch'):
                    ra = mem.r32(cpu.r_reg(R.A7) + (36 if nm == 'main_vlist' else 0)) - 2  # (the caller: roughly)
                    i = bisect.bisect_right(maddr, ra) - 1
                    if i >= 0:
                        profcall['%s %05X' % (nm, mlabs[i][1])] += 1
            if pc in targets:
                cycles[0] += total
                return pc
            if pc in bad or s.terminated:
                raise RuntimeError('CPU stopped at %06x, badpc %04x (last dispatch %04x), view %d, ref view %d pc %04x frame %d, log=%s' % (
                    pc - s.base, mem.r16(sym['badpc']), mem.r16(sym['dispatch_pc']), mem.r8(sym['df_view']), m.view, m.cpu.pc, m.frame, s.log[-3:]))
            if pc == TRAP1:
                s.gemdos()
        raise RuntimeError('CPU timeout at %06x (reference frame %d, pc %04x)' % (cpu.r_pc() - s.base, m.frame, m.cpu.pc))

    def resume():
        sp = cpu.r_reg(R.A7)
        cpu.w_pc(mem.r32(sp))
        cpu.w_reg(R.A7, sp + 4)

    snd = [0]

    def compare(f):
        if bytes(mem.r_block(0, 0x400)) != low0:
            raise RuntimeError('frame %d: the 68000 vectors ($0-$3FF) were written (Hatari: a bus error at 0)' % f)
        sp = m.cpu.s
        want = bytes(m.mem[0:0xC000])
        got = bytes(mem.r_block(base, 0xC000))
        if want != got:
            diff = [i for i in range(0xC000) if want[i] != got[i] and not (sp - 64 <= i < sp)]
            if diff:
                raise RuntimeError('frame %d: %d RAM differences, ref pc %04x S %04x %s' % (
                    f, len(diff), m.cpu.pc, sp, [(hex(a), hex(got[a]), hex(want[a])) for a in diff[:12]]))
        for name, addr, ref in (('palette', base + 0xC000, m.palette), ('CMOS', sym['df_cmos'], m.cmos)):
            got = bytes(mem.r_block(addr, len(ref)))
            if got != bytes(ref):
                raise RuntimeError('frame %d: %s %s, reference %s' % (f, name, got.hex(), bytes(ref).hex()))
        pic = picture(bytes(mem.r_block(mem.r32(sym['screen']) + PIC_TOP * LB, 240 * LB)))
        want = np.zeros((240, 320), np.uint8)
        want[:, 14:306] = render_pixels(m.mem)
        if not args.nopic and (pic != want).any():
            ys, xs = np.nonzero(pic != want)
            y0, x0 = int(ys[0]), int(xs[0])
            raise RuntimeError('frame %d: %d screen pixels differ from the reference picture, first (line, x) %s; '
                               'line %d x %d-%d: screen %s, reference %s' % (
                f, len(ys), list(zip(ys[:6].tolist(), xs[:6].tolist())), y0, x0, x0 + 11,
                pic[y0, x0:x0 + 12].tolist(), want[y0, x0:x0 + 12].tolist()))
        if mem.r8(sym['df_view']) != m.view:
            raise RuntimeError('frame %d: view %d, reference %d' % (f, mem.r8(sym['df_view']), m.view))
        head = mem.r8(sym['snd_head'])
        got = [mem.r8(sym['snd_ring'] + ((snd[0] + i) & 255)) for i in range((head - snd[0]) & 255)]
        want = [v for fr, v in m.sound_log if fr == f]
        if got != want:
            raise RuntimeError('frame %d: sound commands %s, reference %s' % (f, got, want))
        snd[0] = head

    # the boot: to the first idle
    run_to({done})
    low0 = bytes(mem.r_block(0, 0x400))         # (after the runtime set its vectors)
    m.frame = -1
    m.run_to_idle()
    m.booted = True
    compare(-1)
    boot = cycles[0]
    print('boot: %d 68000 cycles (the reference %d 6809 cycles)' % (boot, m.cpu.cycles), flush=True)
    resume()
    state = {'two': args.seed == 7}
    cycles[0] = 0
    for f in range(args.frames):
        run_to({wait})
        m.frame = f
        m.in0, m.in1, m.in2 = cover.inputs(args.seed, f, rnd, state)
        cover.cheats(args.seed, state, m.mem)
        for a in (cover.P1_LIVES, cover.P1_SMART, cover.P1_WAVE, cover.P2_LIVES, cover.P1_SCORE + 1):
            mem.w8(base + a, m.mem[a])
        for n, v in (('io_in0', m.in0), ('io_in1', m.in1), ('io_in2', m.in2)):
            mem.w8(sym[n], v)
        mem.w8(sym['vbl_pending'], 1)
        resume()
        if f == args.wtrace:
            import m6809dis
            refw = []
            w0 = m.wr
            c = m.cpu
            cur = [0]
            def wr(a, v):
                if a < 0xC000:
                    refw.append((a, v, cur[0], m.view))
                w0(a, v)
            c.wr = wr
            o = c.step
            def stp():
                cur[0] = c.pc
                return o()
            c.step = stp
            try:
                m.run_frame_port()
            except Exception as e:
                print('reference:', e)
            gotw = []
            on0 = s.on_access
            def on(mode, width, addr, value):
                if mode == 'W' and base <= addr < base + 0xC000:
                    n = (1, 2, 4)[width]
                    for i in range(n):
                        gotw.append((addr - base + i, (value >> (8 * (n - 1 - i))) & 0xFF))
                return on0(mode, width, addr, value)
            mem.set_trace_func(on)
            import bisect, collections, re
            names = sorted((a, n) for n, a in sym.items() if not n.startswith('.'))
            addrs = [a for a, n in names]
            ring = collections.deque(maxlen=60)
            for _ in range(30_000_000):
                cpu.execute(1)
                pc = cpu.r_pc()
                ring.append(pc)
                if pc == done or pc in bad:
                    break
            if pc in bad:
                print('translation stopped; its last 68000 pcs (nearest label + offset):')
                last = None
                for x in ring:
                    i = bisect.bisect_right(addrs, x) - 1
                    t = '%s+%d' % (names[i][1], x - names[i][0])
                    if names[i][1] != last:
                        print('   ', t, 'd7=%08x a5-df_mem=%04x' % (cpu.r_reg(R.D7), (cpu.r_reg(R.A5) - base) & 0xFFFF) if x == ring[-1] else '')
                    last = names[i][1]
            if os.environ.get('DF_WMIN'):              # (only the writes at or above this address: the inline video
                lo, _, hi = os.environ['DF_WMIN'].partition('-')   # stores leave out a byte that is there already;
                lo, hi = int(lo, 16), int(hi or 'FFFF', 16)          # LO-HI: only those)
                refw = [w for w in refw if lo <= w[0] <= hi]
                gotw = [w for w in gotw if lo <= w[0] <= hi]
            k = None
            i = 0
            while i < min(len(refw), len(gotw)):
                if refw[i][:2] == gotw[i] or 0xBF00 <= refw[i][0] < 0xC000:
                    i += 1
                elif i + 1 < min(len(refw), len(gotw)) and refw[i][:2] == gotw[i + 1] and refw[i + 1][:2] == gotw[i]:
                    i += 2                                  # (a word's bytes stored in the other order)
                else:
                    k = i
                    break
            print('writes: reference %d, translation %d, first difference at %s' % (len(refw), len(gotw), k))
            if os.environ.get('DF_WALL'):
                print('  reference:', ' '.join('%04X=%02X@%04X' % (a, v, pc) for a, v, pc, view in refw))
                print('  translation:', ' '.join('%04X=%02X' % x for x in gotw))
            if k is None and len(gotw) < len(refw):
                for a, v, pc, view in refw[max(0, len(gotw) - 6):len(gotw) + 4]:
                    print('  ref %04X=%02X by %04X (view %d) %s' % (a, v, pc, view, m6809dis.decode(m.rd, pc, 0xA0).text))
            if k is not None:
                for a, v, pc, view in refw[max(0, k - 4):k + 4]:
                    print('  ref %04X=%02X by %04X (view %d) %s' % (a, v, pc, view, m6809dis.decode(m.rd, pc, 0xA0).text))
                print('  translation:', ['%04X=%02X' % x for x in gotw[max(0, k - 4):k + 4]])
            return
        if f == args.trace:
            import re
            ref = []
            c0 = m.cpu.step
            def tstep(c0=c0):
                ref.append(cover.virtual(m.cpu.pc, m.view))
                return c0()
            m.cpu.step = tstep
            try:
                m.run_frame_port()
            except Exception as e:
                print('reference:', e)
            m.cpu.step = c0
            addr_of = {int(n[1:], 16): a for n, a in sym.items() if re.fullmatch('M[0-9A-F]{6}', n)}
            labels = {a: v for v, a in addr_of.items()}
            got = []
            for _ in range(20_000_000):
                cpu.execute(1)
                pc = cpu.r_pc()
                if pc in labels:
                    got.append(labels[pc])
                if pc == done or pc in bad:
                    break
            def collapse(xs):
                out = []
                for x in xs:
                    if not out or out[-1] != x:
                        out.append(x)
                return out
            ref = collapse([v for v in ref if v in addr_of])
            got = collapse(got)
            if len(ref) > 1 and got and ref[0] != got[0] and ref[1] == got[0]:
                ref = ref[1:]                           # (the idle point the reference stepped from)
            # (the single-step capture can miss a label: a difference is real when the translation's pc is not the
            # reference's next or the one after)
            i = j = 0
            while i < len(ref) and j < len(got):
                if ref[i] == got[j]:
                    i += 1; j += 1
                    continue
                for di, dj in ((1, 0), (0, 1), (1, 1), (2, 0), (0, 2), (2, 1), (1, 2), (2, 2)):
                    if i + di < len(ref) and j + dj < len(got) and ref[i + di] == got[j + dj] and                             ref[i + di + 1:i + di + 4] == got[j + dj + 1:j + dj + 4]:
                        i += di; j += dj
                        break
                else:
                    break
            n = i
            got = got[j - i:] if j >= i else [0] * (i - j) + got
            print('trace frame %d: reference %d instructions, translation %d, first difference at %d' % (f, len(ref), len(got), n))
            print('reference:  ', ['%06X' % x for x in ref[max(0, n - 12):n + 6]])
            print('translation:', ['%06X' % x for x in got[max(0, n - 12):n + 6]])
            return
        m.run_frame_port()
        m.frame = f
        run_to({done})
        compare(f)
        resume()
        if f % 1000 == 999 and not args.quiet:
            print('%d frames exact' % (f + 1), flush=True)
    print('PASS: %d frames (seed %d): RAM, palette, CMOS, view, sound commands%s exact' % (
        args.frames, args.seed, '' if args.nopic else ' and the screen'))
    print('68000 cycles an arcade frame (the logic and the screen writes; Musashi): %d' % (cycles[0] // max(1, args.frames)))
    if args.profile:
        tot = sum(prof.values())
        print('  ' + ', '.join('%s %.1f%%' % (n, 100 * k / tot) for n, k in prof.most_common(16)))
        print('  6809 code by 64-byte range: ' + ', '.join('%s %.1f%%' % (n, 100 * k / tot) for n, k in prof6809.most_common(20)))
        if os.environ.get('DF_PROFINS'):
            print('  6809 instructions: ' + ', '.join('%05X %.2f%%' % (n, 100 * k / tot) for n, k in profins.most_common(int(os.environ['DF_PROFINS']))))
        if 'terr_calls' in sym:
            print('  df_terrain calls a frame: %.2f' % (mem.r32(sym['terr_calls']) / args.frames))
        print('  routines by 6809 caller (roughly): ' + ', '.join('%s %.1f%%' % (n, 100 * k / tot) for n, k in profcall.most_common(16)))


if __name__ == '__main__':
    main()
