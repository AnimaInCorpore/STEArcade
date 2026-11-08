"""Frame by frame: the translated program (run/junofrst_sim, Musashi) against the reference's port schedule
(machine.JunoPort.run_frame_port) through attract, coin, start and play.

    python logic_test.py [frames] [--seed N]      (seeds as ref/cover.py: DIP switches, two players)

Compared every frame: the RAM $8100-$8FFF and the palette RAM $8000-$800F (the 64 bytes below the stack pointer are
dead and left out), the picture (the planar `vram` of src/render.s against the reference's video RAM, rows 16-239 of
the arcade, the only ones the STE keeps), the latch (Q0 the IRQ enable, Q4 / Q5 the flips), the bank register, the
sound commands of the frame (the writes of 1 after 0 to $8040).  Reports the 68000 cycles of the logic a frame (Musashi;
the drawing is switched off: render_frame returns at once; the video RAM's pixel routines are counted).
"""
from pathlib import Path
import argparse
import random
import sys
sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[1] / 'ref'),
                str(Path(__file__).resolve().parents[3] / 'engine')]
from machine68k import Register as R
from sim import Sim, TRAP1
import re
import numpy as np
from machine import JunoPort
from paths import ROOT, build_dir
import cover

BUILD = build_dir('junofrst')
AREAS = ((0x8000, 0x8010), (0x8100, 0x9000))


def picture(buf):
    """the planar picture (256 lines of 160 bytes, the 224 pixels at byte 24) -> pens [256 lines, 224]"""
    a = np.frombuffer(buf, np.uint8).reshape(256, 160)[:, 24:24 + 14 * 8].reshape(256, 14, 4, 2)
    w = (a[..., 0].astype(np.uint16) << 8) | a[..., 1]                    # [line, group, plane] words
    bits = (w[..., None] >> (15 - np.arange(16))) & 1                    # [line, group, plane, pixel]
    pix = (bits * (1 << np.arange(4))[None, None, :, None]).sum(axis=2)   # [line, group, pixel]
    return pix.reshape(256, 224).astype(np.uint8)


def expected(mem):
    """the reference's video RAM (rows 16-239) as the picture: line 255 - x, column y - 16"""
    v = np.frombuffer(bytes(mem[0:0x8000]), np.uint8).reshape(256, 128)
    px = np.empty((256, 256), np.uint8)
    px[:, 0::2] = v & 15
    px[:, 1::2] = v >> 4
    return px[16:240, ::-1].T.copy()                                      # [x reversed = line, y - 16 = column]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('frames', nargs='?', type=int, default=3000)
    ap.add_argument('--seed', type=int, default=1)
    ap.add_argument('--quiet', action='store_true')
    ap.add_argument('--render', action='store_true', help='draw (render_frame) and compare the published buffer and palette too')
    ap.add_argument('--profile', action='store_true', help='where the 68000 cycles go (a sample every 200 cycles)')
    ap.add_argument('--trace', type=int, default=-1, help='compare the executed instructions of this frame')
    ap.add_argument('--sound', action='store_true', help='run snd_frame every frame and compare the sound board with tools/sound.py STEBoard')
    ap.add_argument('--exact', action='store_true', help='with --profile: every instruction counted with its cycles (slow; use few frames)')
    ap.add_argument('--pfrom', type=int, default=0, help='with --profile: from this frame')
    ap.add_argument('--count', action='store_true', help='count the video RAM writes (vram_wr calls) and reads')
    ap.add_argument('--tag', default='junofrst_sim', help='the build in run/<tag> (build.py --sim --tag)')
    args = ap.parse_args()
    run = ROOT / 'run' / args.tag
    s = Sim(str(run / 'JUNOFRST.PRG'), run_dir=run, ram_kib=16384)   # (16 MB: the Blitter's registers read back)
    # (the trace mode stays on: the blitter's registers are emulated, the blits draw through it)
    sym = {k: v + s.base for k, v in s.symbols(BUILD / (args.tag + '.map')).items()}
    mem, cpu = s.mem, s.cpu
    import bisect, collections
    prof = collections.Counter()
    symlist = sorted((a, n) for n, a in sym.items() if not re.fullmatch('M[0-9A-F]{6}', n))
    allsyms = sorted((a, n) for n, a in sym.items())
    alladdrs = [a for a, n in allsyms]
    prof_all = collections.Counter()
    symaddrs = [a for a, n in symlist]
    if not args.render:
        mem.w16(sym['render_frame'], 0x4e75)
    wait, done = sym['sim_wait'], sym['sim_frame_done']
    bad = set(range(sym['main_badpc'], sym['main_badpc'] + 12, 2))
    base = sym['jf_mem']
    counts = collections.Counter()
    if args.count:
        lo, hi = sym['vw_ptr'], sym['vw_ptr'] + 4 * 0x8000
        on0 = s.on_access

        def on_count(mode, width, addr, value, on0=on0):
            if lo <= addr < hi and mode == "R" and width == 2:
                counts['vw_ptr reads'] += 1
            return on0(mode, width, addr, value)
        mem.set_trace_func(on_count)
    vram = sym['vram']

    m = JunoPort(*cover.dsw(args.seed))
    mem.w8(sym['io_dsw1'], m.dsw1)
    mem.w8(sym['io_dsw2'], m.dsw2)
    for n in ('io_sys', 'io_p1', 'io_p2'):
        mem.w8(sym[n], 0xFF)
    rnd = random.Random(args.seed)
    cycles = [0]
    fr = [-1]

    def run_to(targets):
        total = 0
        while total < 400_000_000:
            step = 1 if args.exact else 200 if args.profile else 2000
            r = cpu.execute(step).cycles
            total += r
            pc = cpu.r_pc()
            if args.profile and fr[0] >= args.pfrom:
                w = r if args.exact else 1
                prof[bisect.bisect_right(symaddrs, pc) - 1] += w
                prof_all[bisect.bisect_right(alladdrs, pc) - 1] += w
            if pc in targets:
                cycles[0] += total
                return pc
            if pc == sym['crash_sim_stop']:
                sp_ = mem.r32(sym['crash_sp'])
                regs = [mem.r32(sym['crash_regs'] + 4 * i) for i in range(15)]
                raise RuntimeError('exception %d: stack words %s; d1-d7 %s a0-a6 %s; ref frame %d ref pc %04x' % (
                    mem.r16(sym['crash_vector']), [hex(mem.r16(sp_ + 2 * i)) for i in range(8)], [hex(r) for r in regs[1:8]], [hex(r) for r in regs[8:]], m.frame, m.cpu.pc))
            if pc in bad or s.terminated:
                raise RuntimeError('CPU stopped at %06x, d7=%08x (badpc %04x), bank %d, ref bank %d pc %04x frame %d, log=%s' % (
                    pc - s.base, cpu.r_reg(R.D7), mem.r16(sym['badpc']), mem.r8(sym['jf_bank']), m.bank, m.cpu.pc, m.frame, s.log[-3:]))
            if pc == TRAP1:
                s.gemdos()
        sp_ = mem.r32(sym['crash_sp'])
        print('exception frame: SR %04x PC %06x; regs d0-a6: %s' % (mem.r16(sp_), mem.r32(sp_ + 2) - s.base, [hex(mem.r32(sym['crash_regs'] + 4 * i)) for i in range(15)]))
        raise RuntimeError('CPU timeout at %06x (exception vector %d, crash pc/regs: sp %08x; reference frame %d, ref pc %04x)' % (
            cpu.r_pc() - s.base, mem.r16(sym['crash_vector']), mem.r32(sym['crash_sp']), m.frame, m.cpu.pc))

    def resume():
        sp = cpu.r_reg(R.A7)
        cpu.w_pc(mem.r32(sp))
        cpu.w_reg(R.A7, sp + 4)

    sndb = [None]
    sndc = [0, 0, 0]

    def sound_frame(f):
        from sound import STEBoard
        if sndb[0] is None:
            sndb[0] = STEBoard()
        b = sndb[0]
        cmds = [v for fr, v in m.sound_log if fr == f - 1]      # (snd_frame runs at the frame's delivery: the commands
        b.run_frame(cmds)                                        # of the frame before)
        sndc[2] += len(cmds)
        sp = b.cpu.sp
        ram = bytes(mem.r_block(sym['snd_g'] + 0x8000 + 0x2000, 0x400))
        live = [i for i in range(0x400) if not 0x2300 <= 0x2000 + i < sp]
        if any(ram[i] != b.mem[0x2000 + i] for i in live):
            d = [(hex(0x2000 + i), ram[i], b.mem[0x2000 + i]) for i in live if ram[i] != b.mem[0x2000 + i]]
            raise RuntimeError('frame %d: sound RAM (address, STE, model) %s; commands %s' % (f, d[:10], cmds))
        ay = list(mem.r_block(sym['snd_ay'], 16))
        if ay != b.ay:
            raise RuntimeError('frame %d: AY registers %s, model %s' % (f, ay, b.ay))
        ym = list(mem.r_block(sym['snd_ym_cache'], 14))
        if ym != b.ym.cache[:14]:
            raise RuntimeError('frame %d: YM registers %s, model %s' % (f, ym, b.ym.cache[:14]))
        if mem.r8(sym['snd_status']) != b.status or mem.r8(sym['snd_busy']) != b.busy:
            raise RuntimeError('frame %d: i8039 status %d busy %d, model %d %d' % (
                f, mem.r8(sym['snd_status']), mem.r8(sym['snd_busy']), b.status, b.busy))

    snd = [0]
    pics = [0]
    last_pic = [0]

    def compare(f):
        sp = m.cpu.s
        for lo, hi in AREAS:
            want = bytes(m.mem[lo:hi])
            got = bytes(mem.r_block(base + lo, hi - lo))
            diff = [lo + i for i in range(hi - lo) if want[i] != got[i] and not (sp - 64 <= lo + i < sp)]
            if diff:
                raise RuntimeError('frame %d: %d RAM differences, ref pc %04x %s' % (
                    f, len(diff), m.cpu.pc, [(hex(a), hex(got[a - lo]), hex(want[a - lo])) for a in diff[:12]]))
        latch = list(mem.r_block(sym['jf_latch'], 8))
        if [latch[0], latch[4], latch[5]] != [m.latch[0], m.latch[4], m.latch[5]]:
            raise RuntimeError('frame %d: latch %s, reference %s' % (f, latch, m.latch))
        if mem.r8(sym['jf_bank']) != m.bank:
            raise RuntimeError('frame %d: bank %d, reference %d' % (f, mem.r8(sym['jf_bank']), m.bank))
        pic = picture(bytes(mem.r_block(vram, 256 * 160)))
        n = int((pic != expected(m.mem)).sum())
        if n:
            ys, xs = np.nonzero(pic != expected(m.mem))
            raise RuntimeError('frame %d: %d video RAM pixels differ, first (line, column) %s' % (
                f, n, list(zip(ys[:6].tolist(), xs[:6].tolist()))))
        head = mem.r8(sym['snd_head'])
        got = [mem.r8(sym['snd_ring'] + ((snd[0] + i) & 255)) for i in range((head - snd[0]) & 255)]
        want = [v for fr, v in m.sound_log if fr == f]
        if got != want:
            raise RuntimeError('frame %d: sound commands %s, reference %s' % (f, got, want))
        snd[0] = head
        pcn = mem.r16(sym['pic_count'])
        fresh = pcn != last_pic[0]
        last_pic[0] = pcn
        if args.render and f >= 0 and fresh and mem.r8(sym['frame_ready']):
            idx = mem.r8(sym['frame_ready']) - 1
            buf = mem.r32(sym['buf_base'] + 4 * idx)
            shown = picture(bytes(mem.r_block(buf + 10 * 160, 256 * 160)))
            n = int((shown != expected(m.mem)).sum())
            if n:
                ys, xs = np.nonzero(shown != expected(m.mem))
                raise RuntimeError('frame %d: the published buffer differs from the reference picture in %d pixels: lines %d-%d, columns %d-%d' % (f, n, ys.min(), ys.max(), xs.min(), xs.max()))
            from assets import ste_word
            from machine import pens
            want = [ste_word(c) for c in pens(m.mem[0x8000:0x8010])]
            got = [mem.r16(sym['pend_pal'] + 2 * i) for i in range(16)]
            if want != got:
                raise RuntimeError('frame %d: palette %s, reference %s' % (f, got, want))
            pics[0] += 1

    run_to({wait})
    m.frame = -1
    m.run_to_idle()
    m.booted = True
    compare(-1)
    state = {'two': args.seed == 7, 'coin2': True if args.seed in (2, 6) else None}
    cycles[0] = 0
    per_frame = []
    for f in range(args.frames):
        fr[0] = f
        m.frame = f
        m.system, m.p1, m.p2 = cover.inputs(f, rnd, state)
        for n, v in (('io_sys', m.system), ('io_p1', m.p1), ('io_p2', m.p2)):
            mem.w8(sym[n], v)
        mem.w8(sym['vbl_pending'], 1)
        if f == args.trace:
            ref = []
            c0 = m.cpu.step
            def tstep(c0=c0):
                ref.append(cover.virtual(m.cpu.pc, m.bank))
                return c0()
            m.cpu.step = tstep
        m.run_frame_port()
        m.frame = f
        resume()
        if f == args.trace:
            m.cpu.step = c0
            addr_of = {int(n[1:], 16): a for n, a in sym.items() if re.fullmatch('M[0-9A-F]{6}', n)}
            labels = {a: v for v, a in addr_of.items()}
            got = []
            for _ in range(5_000_000):
                cpu.execute(1)
                pc = cpu.r_pc()
                if pc in labels:
                    got.append(labels[pc])
                if pc in (done, sym['sim_render_start']) or pc in bad:
                    break
            def collapse(xs):
                out = []
                for x in xs:
                    if not out or out[-1] != x:
                        out.append(x)
                return out
            ref = [labels[a] for a in collapse([addr_of[v] for v in ref[1:] if v in addr_of])]
            got = [labels[a] for a in collapse([addr_of[v] for v in got])]
            n = next((i for i in range(min(len(ref), len(got))) if ref[i] != got[i]), min(len(ref), len(got)))
            print('trace frame %d: reference %d instructions, translation %d, first difference at %d' % (f, len(ref), len(got), n))
            print('reference:', ['%06X' % x for x in ref[max(0, n - 6):n + 4]])
            print('translation:', ['%06X' % x for x in got[max(0, n - 6):n + 4]])
            return
        if run_to({done, sym['sim_render_start']}) != done:
            resume()
            run_to({done})
        compare(f)
        if args.sound:
            sound_frame(f)
        resume()
        run_to({wait})
        per_frame.append(cycles[0] - sum(per_frame))
        if f % 1000 == 999 and not args.quiet:
            print('%d frames exact' % (f + 1), flush=True)
    print('PASS: %d frames (seed %d), RAM, palette RAM, picture, latch, bank and sound commands exact' % (args.frames, args.seed))
    if args.render:
        print('%d published pictures and palettes exact' % pics[0])
    if args.profile:
        tot = sum(prof.values())
        for i, n in prof.most_common(14):
            print('  %5.1f%% %s' % (100 * n / tot, symlist[i][1]))
        if args.sound:
            print('  sound hot spots: ' + ', '.join('%s %.1f%%' % (symlist[i][1], 100 * n / tot) for i, n in prof.most_common(60) if re.fullmatch('X[0-9A-F]{4}(_r)?', symlist[i][1]) or symlist[i][1].startswith('snd_')))
        bucket = collections.Counter()
        for i, n in prof_all.items():
            nm = allsyms[i][1]
            mm = re.match(r'M([0-9A-F]{6})', nm)
            if mm:
                a = int(mm.group(1), 16)
                bucket['page %02X %04X-%04X' % (a >> 16, a & 0xFFC0, (a & 0xFFC0) + 63)] += n
            else:
                bucket[nm] += n
        print('  by label (6809 code in 64-byte ranges, else the runtime symbol): ' + ', '.join('%s %.1f%%' % (k, 100 * v / tot) for k, v in bucket.most_common(28)))
        agg = collections.Counter()
        for i, n in prof.items():
            nm = symlist[i][1]
            agg['sound (X<pc> labels, snd_*)' if re.fullmatch('X[0-9A-F]{4}(_r)?', nm) or nm.startswith('snd_') else 'other'] += n
        print('  ' + ', '.join('%s %.1f%%' % (k, 100 * v / tot) for k, v in agg.items()))
    if per_frame:
        pf = sorted(per_frame)
        print('per arcade frame: median %d, 75%% %d, 90%% %d, 99%% %d, max %d cycles (the 50 Hz STE has 160,000 a VBL, the arcade 60.6 frames a second need <= 132,000 each)' % (pf[len(pf) // 2], pf[len(pf) * 3 // 4], pf[len(pf) * 9 // 10], pf[len(pf) * 99 // 100], pf[-1]))
    if args.count:
        print('vram_wr calls a frame: %.1f' % (counts['vw_ptr reads'] / args.frames))
    if args.sound:
        b = sndb[0]
        print('sound: AY registers, YM registers, sound RAM and i8039 status equal every frame; %d commands, %d YM writes, %d i8039 effects, %d fast loop passes' % (sndc[2], sum(len(w) for w in b.ym_log), len(b.dac_log), b.fast))
    print('68000 cycles a frame (the logic, no drawing; Musashi): %d' % (cycles[0] // args.frames))


if __name__ == '__main__':
    main()
