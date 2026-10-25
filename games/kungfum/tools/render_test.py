"""The STE picture (run/kungfum_sim: the translated logic and render.s on Musashi with its Blitter) against the
reference renderer, frame by frame, in the shown colours.

    python render_test.py [frames] [--seed N] [--from F] [--every K] [--shots DIR] [--play]

The logic runs as in logic_test.py (the reference's port schedule, ref/cover.py's inputs and cheats); every frame
render_frame draws, and the test reads the picture the STE would show: lines 0-47 from the panel image, 48-255 from the
published ring at its Wx (the VBL's part is played by the test: the ring becomes the shown one).  Expected: the
reference's pens (machine.Video.render_raw) through the scene's pen map (assets.py; the panel's map above line 48).
Checked from frame --from on, every --every-th: the 256 x 256 picture exact, the bands (screen x 0-31, 288-319) black
but where a sprite may overhang the picture's edge inside a word (the clip boundary: render.s).  Reports the 68000
cycles a picture (CPU and Blitter: Musashi's count of the frames' render_frame, the logic subtracted).
"""
from pathlib import Path
import argparse
import pickle
import random
import sys
import numpy as np
sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[1] / 'ref'),
                str(Path(__file__).resolve().parents[3] / 'engine')]
from machine68k import Register as R
from sim import Sim, TRAP1
from machine import KungFuPort, Video
from paths import ROOT, build_dir
import assets
import cover

BUILD = build_dir('kungfum')
LB, ROW_OFF = 424, 16


def planes_to_idx(words):
    """[..., 4] plane words (big-endian ints) -> [..., 16] indices"""
    bits = np.arange(15, -1, -1)
    out = np.zeros(words.shape[:-1] + (16,), np.uint8)
    for p in range(4):
        out |= (((words[..., p, None] >> bits) & 1) << p).astype(np.uint8)
    return out


def ste_picture(mem, sym, ring, wx):
    """[256, 320] indices as shown: the panel image above line 48, the ring at wx below"""
    pic = np.zeros((256, 320), np.uint8)
    hud = np.frombuffer(bytes(mem.r_block(sym['hud_img'], 48 * 160)), '>u2').reshape(48, 20, 4)
    pic[:48] = planes_to_idx(hud.astype(np.int64)).reshape(48, 320)
    base = mem.r32(sym['ring_base'] + 4 * ring)
    w0 = wx >> 4
    raw = bytes(mem.r_block(base + (48 + ROW_OFF) * LB, 208 * LB))
    arr = np.frombuffer(raw, '>u2').reshape(208, LB // 8, 4).astype(np.int64)
    idx = planes_to_idx(arr[:, w0:w0 + 21]).reshape(208, 21 * 16)
    f = wx & 15
    pic[48:] = idx[:, f:f + 320]
    return pic


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('frames', nargs='?', type=int, default=600)
    ap.add_argument('--seed', type=int, default=1)
    ap.add_argument('--start', type=int, default=0, help='compare from this frame on')
    ap.add_argument('--every', type=int, default=1)
    ap.add_argument('--shots', default=None)
    ap.add_argument('--play', action='store_true')
    ap.add_argument('--stop', action='store_true', help='stop at the first difference')
    ap.add_argument('--prof', action='store_true', help='sample render_frame\'s pc every 64 cycles: cycles by routine')
    ap.add_argument('--recording', type=Path, default=BUILD / 'play_inputs.bin', help='reference inputs with --play')
    ap.add_argument('--program', type=Path, help='alternate simulator PRG')
    ap.add_argument('--map', dest='mapfile', type=Path, default=BUILD / 'kungfum_sim.map')
    args = ap.parse_args()
    pal = pickle.loads((BUILD / 'kf_palettes.pkl').read_bytes())
    maps, pmap = pal['maps'], pal['panel_map']
    run = ROOT / 'run' / 'kungfum_sim'
    program = args.program or run / 'KUNGFUM.PRG'
    s = Sim(str(program), run_dir=program.parent, ram_kib=16384)
    sym = {k: v + s.base for k, v in s.symbols(args.mapfile).items()}
    mem, cpu = s.mem, s.cpu
    wait, done, bad = sym['sim_wait'], sym['sim_frame_done'], sym['z80_badpc']
    a6 = sym['g_block'] + 0x8000

    def addr(a):
        return a6 + (a if a < 0x8000 else a - 0x10000)

    m = KungFuPort(*cover.dsw(args.seed))
    m.cpu.afmask = 0xc1
    for i in range(3):
        mem.w8(sym['io_ports'] + i, 0xFF)
    mem.w8(sym['io_ports'] + 3, m.dsw1)
    mem.w8(sym['io_ports'] + 4, m.dsw2)
    rnd = random.Random(args.seed)
    v = Video()
    cyc = {'render': 0, 'logic': 0, 'n': 0, 'blit': 0}

    import bisect
    import collections
    import re as _re
    _map = args.mapfile.read_text()
    absolute = {m[1] for m in _re.finditer(r'\s0x[0-9a-f]{8} (\S+?): \S+ abs', _map)}
    labels = sorted((v, k) for k, v in sym.items() if not k.startswith('Z') and not k.startswith('L') and
                    k not in absolute)
    lv = [x for x, _ in labels]
    prof = collections.Counter()

    def run_to(targets, count=None):
        total = 0
        chunk = 64 if (args.prof and count == 'render') else 2000
        while total < 2_000_000_000:
            n = cpu.execute(chunk).cycles
            total += n
            if chunk == 64:
                i = bisect.bisect_right(lv, cpu.r_pc()) - 1
                prof[labels[i][1] if i >= 0 else '?'] += n
            pc = cpu.r_pc()
            if pc in targets:
                if count is not None:
                    cyc[count] += total
                return pc
            if pc in (bad, bad + 4) or s.terminated:
                raise RuntimeError('CPU stopped at %06x, d7=%08x' % (pc - s.base, cpu.r_reg(R.D7)))
            if pc == TRAP1:
                s.gemdos()
        raise RuntimeError('CPU timeout at %06x' % (cpu.r_pc() - s.base))

    def resume():
        sp = cpu.r_reg(R.A7)
        cpu.w_pc(mem.r32(sp))
        cpu.w_reg(R.A7, sp + 4)

    def vbl():
        """vbl_video's bookkeeping: the published ring becomes the shown one"""
        ready = mem.r8(sym['frame_ready'])
        mem.w16(sym['prev_idx'], mem.r16(sym['shown_idx']))
        if ready:
            mem.w8(sym['frame_ready'], 0)
            mem.w16(sym['shown_idx'], ready - 1)
        return ready - 1

    run_to({wait})
    m.frame = -1
    m.run_to_idle()
    m.booted = True
    state = {'select': args.seed in (12, 13)}
    play = None
    if args.play:
        import playbot
        play = playbot.load(args.recording)
        if len(play) < args.frames:
            ap.error('--recording is shorter than the requested frame count')
    bad_frames = 0
    checked = 0
    for f in range(args.frames):
        if play:
            m.system, m.p1 = play[f]
            if f >= 900:
                m.mem[0xE084] = 6
        else:
            m.system, m.p1 = cover.inputs(f, rnd, state, m)
            before = bytes(m.mem[0xE000:0xF000])
            cover.cheats(args.seed, f, m, state)
            after = bytes(m.mem[0xE000:0xF000])
            for i in range(0x1000):
                if before[i] != after[i]:
                    mem.w8(addr(0xE000 + i), after[i])
        for a, x in zip((0, 1), (m.system, m.p1)):
            mem.w8(sym['io_ports'] + a, x)
        mem.w8(sym['vbl_pending'], 1)
        m.frame = f
        m.run_frame_port()
        resume()
        run_to({sym['sim_render_start']}, 'logic')
        resume()
        b0 = s.blitter.cycles
        run_to({done}, 'render')
        cyc['blit'] += s.blitter.cycles - b0
        cyc['n'] += 1
        ring = vbl()
        if f >= args.start and (f - args.start) % args.every == 0 and ring >= 0:
            wx = mem.r16(sym['pub_wx'] + 2 * ring)
            scene = mem.r16(sym['pub_scene'])
            want_scene = assets.scene_of(m.mem)
            got = ste_picture(mem, sym, ring, wx)
            raw = v.render_raw(m.mem, m.sprite_ram, m.scroll)[:, 128:384]
            exp = np.zeros((256, 256), np.uint8)
            exp[:48] = pmap[raw[:48]]
            exp[48:] = maps[want_scene][raw[48:]]
            pic = got[:, 32:288]
            diff = pic != exp
            n = int(diff.sum())
            band = np.concatenate([got[48:, :32], got[48:, 288:]], 1)
            # the allowed overhang: the band pixels between the clip boundary and the picture's edge
            a = wx + 32
            cl, cr = a & ~15, (wx + 288 + 15) & ~15
            allow = np.zeros(320, bool)
            allow[max(0, cl - wx):32] = True
            allow[288:min(320, cr - wx)] = True
            bad_band = (got[48:] != 0) & ~allow[None, :]
            bad_band[:, 32:288] = False
            nb = int(bad_band.sum()) + int((got[:48, :32] != 0).sum() + (got[:48, 288:] != 0).sum())
            checked += 1
            if n or nb or scene != want_scene:
                bad_frames += 1
                ys, xs = np.nonzero(diff)
                print('frame %d: %d pixels differ, %d band pixels, scene %d (want %d), wx %d; first at %s' % (
                    f, n, nb, scene, want_scene, wx, list(zip(ys[:5].tolist(), xs[:5].tolist()))), flush=True)
                if args.shots:
                    save(args.shots, f, got, exp, pal, scene, want_scene)
                if args.stop:
                    break
        resume()
        run_to({wait})
    n = max(1, cyc['n'])
    if args.prof:
        tot = sum(prof.values())
        grouped = collections.Counter()
        for k, c in prof.items():
            grouped[_re.sub(r'^kshp_\w+', 'kshp_*', k)] += c
        if 'cnt_gen' in sym:
            print('cells: generated %.1f, row path %.1f (clipped %.1f, 64 KB %.1f, no code %.1f) a picture' % tuple(
                mem.r32(sym[k]) / n for k in ('cnt_gen', 'cnt_rows', 'cnt_clip', 'cnt_64k', 'cnt_nocode')))
        for k, c in grouped.most_common(30):
            print('%-24s %8d cycles a picture %5.1f%%' % (k, c // n, 100 * c / tot))
    print('%s: %d frames checked (seed %d), %d differ; a picture: render_frame %d CPU cycles + %d Blitter bus cycles; '
          'the logic %d cycles a frame (Musashi)' % ('PASS' if not bad_frames else 'FAIL', checked, args.seed, bad_frames,
                                                    cyc['render'] // n, cyc['blit'] // n, cyc['logic'] // n))
    return int(bad_frames != 0)


def save(d, f, got, exp, pal, scene, want_scene):
    from PIL import Image
    Path(d).mkdir(parents=True, exist_ok=True)

    def rgb(idx, cols):
        c = np.array(cols, np.uint8)
        return c[idx]
    g = np.zeros((256, 320, 3), np.uint8)
    g[:48] = rgb(got[:48], pal['panel'])
    g[48:] = rgb(got[48:], pal['cols'][scene])
    e = np.zeros((256, 320, 3), np.uint8)
    e[:48, 32:288] = rgb(exp[:48], pal['panel'])
    e[48:, 32:288] = rgb(exp[48:], pal['cols'][want_scene])
    dm = np.zeros((256, 320, 3), np.uint8)
    dm[:, 32:288][got[:, 32:288] != exp] = (255, 0, 255)
    Image.fromarray(np.hstack((g, e, dm))).save(Path(d) / ('r%05d.png' % f))


if __name__ == '__main__':
    sys.exit(main())
