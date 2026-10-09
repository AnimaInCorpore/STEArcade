"""The translated 1943 program (and the i8751 interpreter) on Musashi against the reference's cooperative schedule.

Every tick: the RAM (video RAM, scroll latches, work RAM, sprite RAM; the dead stack bytes of merged push/pop
excepted), the buffered sprite list, the latches and the MCU's reply are compared.
"""
from pathlib import Path
import argparse, re
import random
import sys
import numpy as np
sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[3] / 'engine')]
from sim import Sim, TRAP1
from machine68k import Register as R
from machine import Game1943
from paths import ROOT, build_dir


def inputs(frame):
    """The default schedule (AUTOPLAY's too): a coin, start, then fire and left / right, period 3000 ticks."""
    frame %= 3000
    system = player = 0xff
    if 900 <= frame < 905:
        system &= ~0x40
    if 940 <= frame < 945:
        system &= ~1
    if frame >= 1000:
        player &= ~16
        player &= ~(1 if (frame % 180) >= 90 else 2)
    return system, player, 0xff


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('frames', nargs='?', type=int, default=1600)
    ap.add_argument('--seed', type=int, help='random inputs (ref/cover.py style) instead of the default schedule')
    ap.add_argument('--render', action='store_true', help='let render_frame run (else it returns at once) and compare '
                    'each picture with the reference renderer through the palette map')
    ap.add_argument('--every', type=int, default=1, help='with --render: compare every n-th picture (all are drawn)')
    ap.add_argument('--cheat', type=int, help='MAME cheats on both machines: energy, invincibility, start at this stage')
    ap.add_argument('--verbose', action='store_true')
    ap.add_argument('--twins', action='store_true', help='with --render: the twin lines of the window must hold the back layer alone')
    ap.add_argument('--trace', type=int)
    ap.add_argument('--watch', help='ring,line,chunk: report the writes and blits there (debug)')
    ap.add_argument('--save', help='with --render: write the first differing picture pair to this PNG')
    args = ap.parse_args()
    run = ROOT / 'run' / '1943_sim'
    sim = Sim(str(run / '1943.PRG'), ram_kib=16384, run_dir=run)
    sim.mem.set_trace_mode(args.render)          # (the trace runs the Blitter)
    sym = {k: v+sim.base for k, v in sim.symbols(build_dir('1943')/'1943_sim.map').items()}
    stops = {sym[n]: n for n in ['sim_wait', 'sim_frame_done', 'z80_badpc']}
    mem, cpu = sim.mem, sim.cpu
    if not args.render:
        mem.w16(sym['render_frame'], 0x4e75)
    ref = Game1943()
    ref.cpu.afmask = 0xc1                          # (push / pop af: the translation keeps S Z C)
    block = sym['g_block'] + 0x8000 - 0x10000       # (Z80 address a at block + a for a >= $8000)
    # The translator merges `push rr / pop rr'` into a move (the stack word below SP is dead): the bytes such a push
    # writes in the reference are not compared until another instruction writes them.
    merged = set()
    for line in (build_dir('1943') / 'code_1943.s').read_text().splitlines():
        hit = re.match(r'^Z([0-9A-F]{4,5}):\t\t; push .* \(merged\)', line)
        if hit:
            merged.add(int(hit[1], 16))
    dead = set()
    site = [0]
    step0, write0 = ref.cpu.step, ref.cpu.wr8

    def ref_step():
        pc = ref.cpu.pc
        site[0] = 0x10000 + ref.bank*0x4000 + pc-0x8000 if 0x8000 <= pc < 0xc000 else pc
        return step0()

    def ref_write(a, v):
        if site[0] in merged:
            dead.add(a)
        else:
            dead.discard(a)
        return write0(a, v)

    ref.cpu.step, ref.cpu.wr8 = ref_step, ref_write

    def run_to_stop():
        used = 0
        while used < 400_000_000:
            result = cpu.execute(2000)
            used += result.cycles
            pc = cpu.r_pc()
            if pc in stops:
                return stops[pc]
            if pc == TRAP1:
                sim.gemdos()
            if sim.terminated or pc == 0x600:
                raise RuntimeError(f'Runtime terminated at {pc:06x}: {sim.log[-3:]}')
        raise RuntimeError('68000 exceeded execution budget')

    def resume():
        sp = cpu.r_reg(R.A7)
        cpu.w_pc(mem.r32(sp))
        cpu.w_reg(R.A7, sp+4)

    def compare(frame):
        for name, lo, hi in [('video RAM', 0xd000, 0xd805), ('RAM', 0xe000, 0x10000)]:
            got = mem.r_block(block + lo, hi - lo)
            want = ref.mem[lo:hi]
            diff = [lo+i for i, (a, b) in enumerate(zip(got, want)) if a != b and lo+i not in dead]
            if diff:
                print(frame, name, 'diff', len(diff), [(hex(a), got[a-lo], want[a-lo]) for a in diff[:12]])
                return False
        got = mem.r_block(sym['g_sprites'], 512)
        want = bytes(b for o in range(0, 4096, 32) for b in ref.sprites[o:o+4])
        if got != want:
            i = next(i for i in range(512) if got[i] != want[i])
            print(frame, 'sprite buffer diff at entry', i//4)
            return False
        for name, want in [('g_bank', ref.bank), ('g_control', ref.control), ('g_layers', ref.layers),
                           ('g_mcu_response', ref.mcu.response), ('mcu_command', ref.mcu.command)]:
            if mem.r8(sym[name]) != want:
                print(frame, name, mem.r8(sym[name]), want)
                return False
        if mem.r_block(sym['mcu_ram'], 256) != ref.mcu.ram:
            got = mem.r_block(sym['mcu_ram'], 256)
            i = next(i for i in range(256) if got[i] != ref.mcu.ram[i])
            print(frame, f'MCU RAM {i:02x}', got[i], ref.mcu.ram[i])
            return False
        return True

    palmap = np.frombuffer((build_dir('1943') / 'palmap.bin').read_bytes(), np.uint8)
    pictures = [0]
    text_sum = [None]
    last_text = [None]

    def picture(frame):
        """the ring render_frame finished, against the reference's picture; then a VBL shows it"""
        ready = mem.r8(sym['frame_ready'])
        if not ready:
            return True
        shown = mem.r16(sym['shown_idx'])
        mem.w16(sym['prev_idx'], shown)
        mem.w16(sym['shown_idx'], ready - 1)
        mem.w8(sym['frame_ready'], 0)
        if args.verbose:
            idx = mem.r16(sym['draw_idx'])
            st, en = mem.r32(sym['dmg_start']), mem.r32(sym['dmg_ptr'])
            rects = [(mem.r32(a) - mem.r32(sym['ring_base'] + 4*idx), mem.r32(a+4) - mem.r32(a), mem.r16(a+8), mem.r16(a+10)) for a in range(st, en, 12)]
            lst = [(mem.r32(a), mem.r32(a+4)) for a in range(sym['chr_list'], mem.r32(sym['chr_list_end']), 8)]
            print(frame, 'ring', idx, 'top', mem.r16(sym['cur_top']), 'line 40 rects', [r for r in rects if r[0] >> 8 == 40],
                  'list at 40', [(o & 255) for o, _ in lst if o >> 8 == 40], 'rows', mem.r_block(sym['chr_rows'], 64).hex())
        if frame % args.every:
            return True
        base = mem.r32(sym['flip_addr']) + 10*256            # (PIC_TOP lines above the window)
        data = np.frombuffer(mem.r_block(base, 256*256), np.uint8)       # (a line: 3 chunks of margin, the window, 3 more)
        lines = data.reshape(256, 256)[:, :20*8].reshape(256, 20, 4, 2)
        words = (lines[..., 0].astype(np.uint16) << 8) | lines[..., 1]
        bits = (words[..., None] >> np.arange(15, -1, -1)) & 1          # [line][chunk][plane][pixel]
        got = (bits * (1 << np.arange(4))[None, None, :, None]).sum(2).reshape(256, 320)
        raw = ref.video.render_raw(ref.mem, ref.sprites, ref.control, ref.layers)
        want = np.zeros((256, 320), np.int64)
        want[:, 48:272] = palmap[np.rot90(raw[16:240])]
        pictures[0] += 1
        if args.twins:
            # the twin lines of the window hold the back layer alone
            top = mem.r16(sym['cur_top'])
            ring = mem.r32(sym['ring_base'] + 4 * mem.r16(sym['draw_idx']))
            lines = []
            for y in range(256):
                b = top + y
                t = b + 320 if b < 320 else b - 320
                lines.append(mem.r_block(ring + t * 256, 160))
            tw = np.frombuffer(b''.join(lines), np.uint8).reshape(256, 20, 4, 2)
            tw = (tw[..., 0].astype(np.uint16) << 8) | tw[..., 1]
            tw = (((tw[..., None] >> np.arange(15, -1, -1)) & 1) * (1 << np.arange(4))[None, None, :, None]).sum(2).reshape(256, 320)
            back = np.zeros((256, 320), np.int64)
            if ref.layers & 32:
                back[:, 48:272] = palmap[np.rot90(ref.video.render_raw(ref.mem, ref.sprites, ref.control & ~128, 32)[16:240])]
            if (tw != back).any():
                ys, xs = np.nonzero(tw != back)
                print(f'frame {frame}: the twin lines differ from the back layer in {len(ys)} pixels, first at window x {xs[0]-48} y {ys[0]}')
                return False
        bad = got != want
        if bad.any():
            # The port draws the sprites of colours 10 and 11 before the front layer, the others after it: where a
            # sprite of the first kind comes earlier in the list than an overlapping one of the second, the arcade
            # shows the first (or the front), the port the second.  Such pictures are counted, not failed.
            alt = np.zeros((256, 320), np.int64)
            alt[:, 48:272] = palmap[np.rot90(port_order(raw)[16:240])]
            if (got == alt).all():
                approx[0] += 1
                return True
            ys, xs = np.nonzero(bad)
            print(f'frame {frame}: {int(bad.sum())} pixels differ, first at window x {xs[0]-48} y {ys[0]}; '
                  f'margins {int(bad[:, :48].sum() + bad[:, 272:].sum())}; ring {mem.r16(sym["draw_idx"])}, '
                  f'top {mem.r16(sym["cur_top"])}, back {mem.r8(sym["cur_back"])}, layers {ref.layers:02x}, '
                  f'damage {(mem.r32(sym["dmg_ptr"]) - mem.r32(sym["dmg_start"])) // 12}')
            twin = np.frombuffer(mem.r_block(base + 320*256, 256*256), np.uint8).reshape(256, 256)[:, :160].reshape(256, 20, 4, 2)
            tw = (twin[..., 0].astype(np.uint16) << 8) | twin[..., 1]
            tb = ((tw[..., None] >> np.arange(15, -1, -1)) & 1)
            tgot = (tb * (1 << np.arange(4))[None, None, :, None]).sum(2).reshape(256, 320)
            from collections import Counter
            print('got/want at differing pixels', Counter(zip(got[bad].tolist(), want[bad].tolist())).most_common(6))
            ptrs = [mem.r32(sym['chr_ptr'] + 4*c) for c in range(1024)]
            vis = [c for c in range(64, 960) if ptrs[c]]
            chars = np.frombuffer(bytes(ref.mem[0xd000:0xd800]), np.uint8)
            blank = np.frombuffer((build_dir('1943') / 'chr_blank.bin').read_bytes(), np.uint8)
            codes = chars[:1024].astype(int) + ((chars[1024:].astype(int) & 0xe0) << 3)
            want_vis = [c for c in range(64, 960) if not blank[codes[c]]]
            raw_copy = mem.r_block(sym['chr_raw'], 2048)
            cmap = np.frombuffer((build_dir('1943') / 'chr_cmap.bin').read_bytes(), np.uint8)
            wrong = []
            for c in vis:
                code, attr = codes[c], int(chars[1024 + c])
                g = ref.video.chars[code]                       # [py][px]
                scr = g[:, ::-1].T
                baked = mem.r_block(ptrs[c], 64)
                for t in range(8):
                    keep = baked[8*t]
                    planes = baked[8*t+4:8*t+8]
                    for k in range(8):
                        opaque = not (keep >> (7 - k)) & 1
                        idx = sum(((planes[p] >> (7 - k)) & 1) << p for p in range(4))
                        pen = int(scr[t, k])
                        if opaque != (pen != 0) or (opaque and idx != cmap[(attr & 31)*4 + pen]):
                            wrong.append(hex(c)); break
                    else:
                        continue
                    break
            print('cells with a wrong glyph', len(wrong), wrong[:8])
            lst = [(mem.r32(a), mem.r32(a+4)) for a in range(sym['chr_list'], mem.r32(sym['chr_list_end']), 8)]
            print('list entries at lines 40-47:', [(o >> 8, o & 255) for o, _ in lst if 40 <= o >> 8 < 48])
            print('RAM row 26 codes:', [hex(codes[c*32+26]) for c in range(32)])
            print('list', (mem.r32(sym['chr_list_end']) - sym['chr_list']) // 8, 'cells drawn', len(vis), 'non-blank cells', len(want_vis), 'extra', [hex(c) for c in sorted(set(vis)-set(want_vis))][:10],
                  'raw copy equal', raw_copy == bytes(ref.mem[0xd000:0xd800]))
            print('twin differs from the picture in', int((tgot != got).sum()), 'from the wanted one in', int((tgot != want).sum()))
            if args.save:
                from PIL import Image
                rgb = np.frombuffer((build_dir('1943') / 'palette.bin').read_bytes(), '>u2')
                lv = lambda n: ((n & 7) << 1) | (n >> 3)
                cols = np.array([[lv((w >> sh) & 15) * 17 for sh in (8, 4, 0)] for w in rgb], np.uint8)
                Image.fromarray(np.hstack([cols[got], cols[want], (bad[..., None] * 255).repeat(3, 2).astype(np.uint8), cols[tgot]])).save(args.save)
            return False
        return True

    approx = [0]

    def port_order(raw):
        """the reference picture with the port's drawing order (back, sprites behind the front layer, front, the
        other sprites, the characters; sprites the last entry first)"""
        v, m = ref.video, np.frombuffer(bytes(ref.mem), np.uint8)
        if ref.layers & 16:
            fx = int(m[0xd800]) | int(m[0xd801]) << 8
            fy = int(m[0xd802])
            yy, xx = np.indices((256, 256))
            wx, wy = (xx + fx) & 65535, (yy + fy) & 255
            idx = 2*((wx//32)*8 + wy//32)
            attr = v.tilemap[idx+1]
            code = v.tilemap[idx].astype(np.uint16) + ((attr.astype(np.uint16) & 1) << 8)
            px = np.where(attr & 64, 31-(wx & 31), wx & 31)
            py = np.where(attr & 128, 31-(wy & 31), wy & 31)
            cols = v.lookup[128 + ((attr.astype(np.uint16) & 60) >> 2)*16 + v.front[code % len(v.front), py, px]]
            opaque_front = cols != 15
        out = v.render_raw(m, ref.sprites, ref.control & ~128, ref.layers & 32)
        def sprites(behind):
            for off in range(4096-32, -1, -32):
                code, attr, y, x = ref.sprites[off:off+4]
                if ((attr & 15) in (10, 11)) != behind:
                    continue
                code += (attr & 224) << 3
                x -= (attr & 16) << 4
                pix = v.sprites[code]
                x0, x1, y0, y1 = max(0, x), min(256, x+16), max(0, y), min(256, y+16)
                if x0 >= x1 or y0 >= y1:
                    continue
                p = pix[y0-y:y1-y, x0-x:x1-x].astype(np.uint16)
                d = out[y0:y1, x0:x1]
                mask = p != 0
                d[mask] = v.lookup[640 + (attr & 15)*16 + p][mask]
        if ref.layers & 64:
            sprites(True)
        if ref.layers & 16:
            out[opaque_front] = cols[opaque_front]
        if ref.layers & 64:
            sprites(False)
        if ref.control & 128:
            yy, xx = np.indices((256, 256))
            idx = (yy//8)*32 + xx//8
            attr = m[0xd400+idx]
            code = m[0xd000+idx].astype(np.uint16) + ((attr.astype(np.uint16) & 224) << 3)
            p = v.chars[code, yy & 7, xx & 7]
            mask = p != 0
            out[mask] = v.lookup[(attr.astype(np.uint16) & 31)*4+p][mask]
        return out

    ref.render_rgb()
    ref.scanline = 16
    ref.run_to_idle()
    ref.booted = True
    stop = run_to_stop()
    if stop != 'sim_wait':
        raise RuntimeError(f'Boot stopped at {stop}, Z80 PC {cpu.r_reg(R.D7)&65535:04x}')
    if not compare(-1):
        return 1
    print('boot matched', flush=True)
    if args.watch:
        ring_n, line, chunk = (int(x) for x in args.watch.split(','))
        lo = mem.r32(sym['ring_base'] + 4 * ring_n) + line * 256 + 24 + 8 * chunk
        on_access0 = sim.on_access
        def watch(mode, width, addr, value):
            if mode == 'W' and lo <= (addr & 0xffffff) < lo + 8:
                print(f'  write {addr:06x} = {value:x} from pc {cpu.r_pc() - sim.base:06x}')
            return on_access0(mode, width, addr, value)
        sim.mem.set_trace_func(watch)
        blit0 = sim.blitter.run
        def blit():
            dst = sim.blitter.reg32(0xA32) & 0xFFFFFE
            ycount = sim.blitter.reg16(0xA38)
            dyi = sim.blitter.s16(sim.blitter.reg16(0xA30))
            xcount = sim.blitter.reg16(0xA36)
            if xcount and ycount:
                span = abs(dyi) * ycount + 8 * xcount
                if dst - span <= lo <= dst + span:
                    print(f'  blit dst {dst - mem.r32(sym["ring_base"] + 4 * ring_n):x} x {xcount} y {ycount} yinc {dyi} src {sim.blitter.reg32(0xA24):06x} pc {cpu.r_pc() - sim.base:06x} frame {frame_now[0]}')
            return blit0()
        sim.blitter.run = blit
    frame_now = [0]
    rng = random.Random(args.seed)
    values = (255, 255, 255)
    for frame in range(args.frames):
        if args.seed is None:
            values = inputs(frame)
        elif frame > 700 and frame % 30 == 0:
            system = 255 & ~(0x40 if frame % 180 == 0 else 0) & ~(1 if frame % 120 == 0 else 0)
            values = system, 255 ^ rng.choice([0, 1, 2, 4, 8, 16, 32, 17, 18, 20, 24, 33, 34]), 255
        if args.cheat is not None:
            for addr, value, f0 in ((0xe450, args.cheat, 700), (0xf206, 0x40, 0), (0xf214, 2, 0)):
                if f0 <= frame and (addr != 0xe450 or frame < 1100):
                    ref.mem[addr] = value
                    mem.w8(block + addr, value)
        ref.inputs[:3] = values
        vbl = mem.r8(sym['g_inputs']) & 8
        mem.w8(sym['g_inputs'], values[0] & ~8 | vbl)
        mem.w8(sym['g_inputs']+1, values[1])
        mem.w8(sym['g_inputs']+2, values[2])
        frame_now[0] = frame
        ref.run_frame_port()
        mem.w8(sym['vbl_pending'], 1)
        resume()
        if args.trace is not None and frame == args.trace:
            # (debug: the ring's line 40 after restore_damage)
            rd = sym['restore_damage']
            while cpu.r_pc() != rd:
                cpu.execute(1)
                if cpu.r_pc() == TRAP1: sim.gemdos()
            ret = mem.r32(cpu.r_reg(R.A7))
            print('restore: list', hex(mem.r32(sym['dmg_start'])), 'end', hex(mem.r32(sym['ring_dmg_end'] + 4*mem.r16(sym['draw_idx']))))
            while cpu.r_pc() != ret:
                cpu.execute(1)
            idx = mem.r16(sym['draw_idx'])
            rb = mem.r32(sym['ring_base'] + 4*idx)
            for y in (40, 80, 96, 112):
                a_, b_ = mem.r_block(rb + y*256, 256), mem.r_block(rb + (y+320)*256, 256)
                print('after restore, ring', idx, 'line', y, 'differs at bytes', [i for i in range(256) if a_[i] != b_[i]][:20])
            print('twin              :', mem.r_block(rb + 360*256 + 24, 32).hex())
            for name in ('draw_sprites', 'draw_front', 'draw_chars', 'sim_frame_done'):
                while cpu.r_pc() != sym[name]:
                    cpu.execute(1)
                print('at', name, mem.r_block(rb + 40*256 + 24, 32).hex())
        stop = run_to_stop()
        if stop != 'sim_frame_done':
            print(f'frame {frame}: stopped {stop}, target={mem.r16(sym["g_dispatch_pc"]):04x}, d7={cpu.r_reg(R.D7):08x}, bank={mem.r8(sym["g_bank"])}')
            return 1
        if not compare(frame):
            return 1
        if not args.render:                   # (every change of the character RAM came with chr_written: gen.py)
            text = bytes(ref.mem[0xd000:0xd800])
            if last_text[0] is not None and text != last_text[0] and not mem.r8(sym['chr_written']):
                i = next(i for i in range(2048) if text[i] != last_text[0][i])
                print(f'frame {frame}: {0xd000 + i:04x} changed without chr_written (a writer missing in the coverage)')
                return 1
            last_text[0] = text
            mem.w8(sym['chr_written'], 0)
        if args.render and not picture(frame):
            return 1
        if args.render:
            text = mem.r_block(sim.base, 0x24000)
            if frame == 0 or text_sum[0] is None:
                text_sum[0] = text
            elif text != text_sum[0]:
                i = next(i for i in range(len(text)) if text[i] != text_sum[0][i])
                print(f'frame {frame}: the program changed at {i:x}')
                return 1
        resume()
        stop = run_to_stop()
        if stop != 'sim_wait':
            raise RuntimeError(f'Unexpected stop {stop}')
        if frame % 100 == 0:
            print('frame', frame, 'matched', flush=True)
    print(args.frames, 'frames matched' + (f'; {pictures[0]} pictures compared, all equal' if args.render else '') +
          (f' ({approx[0]} only in the drawing order of overlapping sprites behind / before the front layer)' if approx[0] else ''))
    return 0


if __name__ == '__main__':
    sys.exit(main())
