"""Frame by frame: the translated program (run/yiear_sim, Musashi) against the reference's port schedule
(machine.YieArPort.run_frame_port) through attract, coin, start, the name entry and play.

    python logic_test.py [frames] [--seed N]      (seeds as ref/cover.py: the DIP switches)

Compared every frame: the RAM $5000-$5FFF (sprite RAM, video RAM; the 64 bytes below the stack pointer are dead and
left out), the control latch (bits 1 and 2: the NMI and IRQ enables), the sound writes of the frame (SN76489A data,
VLM5030 control and data), the SN76489A's registers and the YM2149's (tools/sound.py: snd_ym a frame later).  Reports the 68000 cycles of the logic a frame (Musashi; the drawing is switched off: render_frame returns at
once).
"""
from pathlib import Path
import argparse
import random
import sys
sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[1] / 'ref'),
                str(Path(__file__).resolve().parents[3] / 'engine')]
from machine68k import Register as R
from sim import Sim, TRAP1
from machine import YieArPort
import sound as S
from paths import ROOT, build_dir
import cover

BUILD = build_dir('yiear')
import os
TRACE = int(os.environ.get('TRACE', '-2'))
AREAS = ((0x5000, 0x6000),)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('frames', nargs='?', type=int, default=3000)
    ap.add_argument('--seed', type=int, default=1)
    ap.add_argument('--quiet', action='store_true')
    ap.add_argument('--tag', default='yiear_sim', help='the build in run/<tag> (build.py --sim --tag)')
    args = ap.parse_args()
    run = ROOT / 'run' / args.tag
    s = Sim(str(run / 'YIEAR.PRG'), run_dir=run)
    s.mem.set_trace_mode(False)
    sym = {k: v + s.base for k, v in s.symbols(BUILD / (args.tag + '.map')).items()}
    mem, cpu = s.mem, s.cpu
    mem.w16(sym['render_frame'], 0x4e75)
    wait, done = sym['sim_wait'], sym['sim_frame_done']
    bad = {sym['main_badpc'], sym['main_badpc'] + 4}
    base = sym['ya_mem']

    m = YieArPort(*cover.dsws(args.seed))
    mem.w8(sym['io_dsw1'], m.dsw1)
    mem.w8(sym['io_dsw2'], m.dsw2)
    mem.w8(sym['io_dsw3'], m.dsw3)
    for n in ('io_sys', 'io_in1', 'io_in2'):
        mem.w8(sym[n], 0xFF)
    rnd = random.Random(args.seed)
    cycles = [0]

    def run_to(targets):
        total = 0
        while total < 400_000_000:
            total += cpu.execute(2000).cycles
            pc = cpu.r_pc()
            if pc in targets:
                cycles[0] += total
                return pc
            if pc in bad or s.terminated:
                raise RuntimeError('CPU stopped at %06x, d7=%08x (badpc %04x), log=%s' % (
                    pc - s.base, cpu.r_reg(R.D7), mem.r16(sym['badpc']), s.log[-3:]))
            if pc == TRAP1:
                s.gemdos()
        raise RuntimeError('CPU timeout at %06x' % (cpu.r_pc() - s.base))

    def resume():
        sp = cpu.r_reg(R.A7)
        cpu.w_pc(mem.r32(sp))
        cpu.w_reg(R.A7, sp + 4)

    snd = [0]
    sn, ym = S.SN(), S.YM()
    has_sound = 'snd_sn' in sym
    marks = [0]
    vst, vdata, phrases = 0, 0, [0]

    def compare(f):
        nonlocal vst, vdata
        sp = m.cpu.s
        for lo, hi in AREAS:
            want = bytes(m.mem[lo:hi])
            got = bytes(mem.r_block(base + lo, hi - lo))
            diff = [lo + i for i in range(hi - lo) if want[i] != got[i] and not (sp - 64 <= lo + i < sp)]
            if diff:
                raise RuntimeError('frame %d: %d RAM differences, ref pc %04x %s' % (
                    f, len(diff), m.cpu.pc, [(hex(a), hex(got[a - lo]), hex(want[a - lo])) for a in diff[:60]]))
        ctl = mem.r8(sym['ya_ctl']) & 6
        if ctl != m.control & 6:
            raise RuntimeError('frame %d: control %02x, reference %02x' % (f, ctl, m.control))
        head = mem.r8(sym['snd_head'])
        kind = {'sn': 0, 'vc': 1, 'vd': 2}
        got = [mem.r16(sym['snd_ring'] + 2 * ((snd[0] + i) & 255)) for i in range((head - snd[0]) & 255)]
        want = [kind[k] << 8 | v for fr, k, v in m.sound_log if fr == f]
        if got != want:
            raise RuntimeError('frame %d: sound writes %s, reference %s' % (f, got[:12], want[:12]))
        snd[0] = head
        if has_sound:
            # the YM as the frame's start left it (snd_ym once a frame, from the SN writes of the frames before)
            if f >= 0 and sn.dirty:
                ym.frame(sn)
                sn.dirty = False
            for fr, k, v in m.sound_log:
                if fr == f and k == 'sn':
                    sn.write(v)
            # the DMA's phrase: the one started last in this frame (ST falling), unless RST stopped it after
            last = None
            for fr, k, v in m.sound_log:
                if fr != f:
                    continue
                if k == 'vd':
                    vdata = v
                elif k == 'vc':
                    st = v >> 1 & 1
                    if vst and not st:
                        last = vdata
                    elif v & 4 and last is not None:
                        last = -1
                    vst = st
            if last is not None and last >= 0 and mem.r16(sym['snd_dma_last']) != last:
                raise RuntimeError('frame %d: DMA phrase %d, reference %d' % (f, mem.r16(sym['snd_dma_last']), last))
            phrases[0] += last is not None and last >= 0
            regs = [mem.r16(sym['snd_sn'] + 2 * i) for i in range(8)]
            if regs != sn.reg:
                raise RuntimeError('frame %d: SN registers %s, model %s' % (f, regs, sn.reg))
            cache = list(mem.r_block(sym['snd_ym_cache'], 11))
            if cache != ym.cache[:11]:
                raise RuntimeError('frame %d: YM registers %s, model %s' % (f, cache, ym.cache[:11]))

    labels = {}
    alias = {}                               # (instructions without code, NOP: labels at one address)
    for k, v in sym.items():
        if len(k) == 7 and k[0] == 'M' and all(c in '0123456789ABCDEF' for c in k[1:]):
            labels.setdefault(v, []).append(int(k[1:], 16))

    def trace_frame():
        """TRACE=<frame>: that frame instruction by instruction, the reference's registers against the translation's at
        each instruction label (the first difference is printed with the reference's last instructions)"""
        log = []
        step0 = m.cpu.step
        c = m.cpu

        def step():
            log.append((c.pc, c.a, c.b, c.x, c.y, c.u, c.s))
            return step0()
        c.step = step
        m.run_frame_port()
        c.step = step0
        resume()
        i = 0
        n = 0
        hits = []
        while n < 60_000_000:
            cpu.execute(1)
            n += 1
            pc = cpu.r_pc()
            if pc == done:
                break
            ps = labels.get(pc)
            if ps is None or i >= len(log):
                continue
            while len(ps) > 1 and log[i][0] in ps and m.mem[log[i][0]] == 0x12 and i + 1 < len(log):
                i += 1                       # (the NOPs before the label's instruction: no code, one address)
            p6 = log[i][0] if log[i][0] in ps else ps[-1]
            want = log[i]
            hits.append((pc - s.base, i, p6))
            got = (p6, cpu.r_reg(R.D0) & 255, cpu.r_reg(R.D1) & 255, cpu.r_reg(R.D2) & 0xFFFF, cpu.r_reg(R.D3) & 0xFFFF,
                   cpu.r_reg(R.D4) & 0xFFFF, (cpu.r_reg(R.A5) - base) & 0xFFFF)
            if p6 != want[0]:
                if p6 in (w[0] for w in log[i:i + 4]):
                    while log[i][0] != p6:
                        i += 1
                    continue
                print('instruction %d: pc %04x, reference %04x' % (i, p6, want[0]))
                print('STE label hits (address, index, pc):', [(hex(a), j, hex(q)) for a, j, q in hits[-8:]])
                print('reference before:', ['%04x %02x %02x x%04x y%04x u%04x s%04x' % w for w in log[max(0, i - 6):i + 1]])
                raise RuntimeError('trace: control flow differs')
            if got != want:
                print('instruction %d at %04x: got A %02x B %02x X %04x Y %04x U %04x S %04x, reference %02x %02x %04x %04x %04x %04x' % (
                    (i, p6) + got[1:] + want[1:]))
                print('previous reference:', ['%04x %02x %02x x%04x y%04x u%04x s%04x' % w for w in log[max(0, i - 6):i]])
                raise RuntimeError('trace: registers differ')
            i += 1
        print('trace: %d instructions equal' % i)

    run_to({wait})
    m.frame = -1
    m.boot()
    m.run_to_idle()
    m.booted = True
    ym.frame(sn)                             # (snd_init's)
    sn.dirty = False
    compare(-1)
    state = {'two': args.seed in (9, 28)}
    cycles[0] = 0
    for f in range(args.frames):
        m.frame = f
        m.system, m.in1, m.in2 = cover.inputs(f, rnd, state)
        for n, v in (('io_sys', m.system), ('io_in1', m.in1), ('io_in2', m.in2)):
            mem.w8(sym[n], v)
        before = bytes(m.mem[0x5000:0x6000])
        cover.cheats(args.seed, f, m, state)
        after = bytes(m.mem[0x5000:0x6000])
        for i in range(0x1000):
            if before[i] != after[i]:
                mem.w8(base + 0x5000 + i, after[i])
        mem.w8(sym['vbl_pending'], 1)
        if f == TRACE:
            trace_frame()
            m.frame = f
            compare(f)
            resume()
            run_to({wait})
            continue
        m.run_frame_port()
        m.frame = f
        snap = bytes(mem.r_block(base + 0x5800, 0x800))      # (the writer marks: a change of the video RAM needs `st vram_w`)
        mem.w8(sym['vram_w'], 0)
        mem.w8(sym['vram_n'], 0)
        resume()
        if run_to({done, sym['sim_render_start']}) != done:
            resume()
            run_to({done})
        now = bytes(mem.r_block(base + 0x5800, 0x800))
        if now != snap and not mem.r8(sym['vram_w']):
            for i in range(0x800):
                if now[i] != snap[i] and not (0x180 <= i < 0x1C0 and mem.r8(sym['vram_n'])):
                    raise RuntimeError('frame %d: video RAM byte $%04X changed without its writer mark (vram_w / vram_n)' % (
                        f, 0x5800 + i))
        if now == snap and mem.r8(sym['vram_w']):
            marks[0] += 1                                    # (written, not changed: fine)
        compare(f)
        resume()
        run_to({wait})
        if f % 1000 == 999 and not args.quiet:
            print('%d frames exact' % (f + 1), flush=True)
    print('%d VLM phrases started and followed on the DMA' % phrases[0])
    print('PASS: %d frames (seed %d), RAM, video RAM, control latch and sound writes exact' % (args.frames, args.seed))
    print('68000 cycles a frame (the logic, no drawing; Musashi): %d' % (cycles[0] // args.frames))


if __name__ == '__main__':
    main()
