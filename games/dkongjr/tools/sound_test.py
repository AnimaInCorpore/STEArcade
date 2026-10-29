"""src/sound.s on Musashi: port sequences into the Z80 block, sound_update once a frame, and what it does to the DMA
sound and the YM checked against the rules of the driver (the board's behaviour measured in MAME, see sound.s):

  - a background tune (01-06) loops (DMA control 3) from when $7C00 changes to it, and stops when $7C00 leaves it;
  - a one-shot tune (07-0E) starts once (control 1) when $7C00 changes to it, plays on when $7C00 drops to 0, and when
    it has ended the background tune $7C00 holds starts again from its beginning;
  - a rising edge on a pin ($7D03-$7D06, $7C81, $7D80) starts its effect, the highest pin bit wins;
  - the YM: a rising edge on $7D00 starts walk on channel A (walk2 when $7D07 is set), $7D01 jump on B, $7D02 climb on
    C, $7D81 fall on A; a patch's frames go out one a frame, then volume 0; fall stops the frame after $7D81 drops.

    python sound_test.py [--prg run/dkongjr/DKONGJR.PRG --map build/dkongjr/dkongjr.map]

The program and its map must be one build (tools/build.py without --out writes both).
"""
import argparse, re, sys
from pathlib import Path
sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[3] / 'engine')]
from machine68k import Register as R
from sprite_blit_test import Harness
from paths import ROOT, build_dir

BLOCK = 0x350000
BUILD = build_dir('dkongjr')


class SoundHarness(Harness):
    def __init__(self, prg, mapfile):
        super().__init__(prg, mapfile)
        self.ym = []                    # (register, value) in write order
        self.ym_sel = 0

    def on_access(self, mode, width, addr, value):
        a = addr & 0xffffff
        if mode == 'W' and width == 0 and a == 0xff8800:
            self.ym_sel = value & 0xff
        elif mode == 'W' and width == 0 and a == 0xff8802:
            self.ym.append((self.ym_sel, value & 0xff))
        super().on_access(mode, width, addr, value)


def clip_table():
    """dkjr_sound.s: tune n -> (start, end, loop), effect name -> (start, end)"""
    text = (BUILD / 'dkjr_sound.s').read_text()
    tunes = [(int(a), int(b), int(c)) for a, b, c in
             re.findall(r'\tdc\.l\t(\d+),(\d+)\n\tdc\.w\t(\d)', text)]
    fx = {m[0]: int(m[1]) for m in re.findall(r'^snd_(\w+?):\tequ\t(\d+)', text, re.M)}
    return tunes, fx


def ym_patches():
    """dkjr_ym.s: name -> [(period, volume)]"""
    out, cur = {}, None
    for line in (BUILD / 'dkjr_ym.s').read_text().splitlines():
        m = re.match(r'ym_(\w+):\tdc\.w\t(\d+)', line)
        if m:
            cur = out.setdefault(m.group(1), [])
            continue
        m = re.match(r'\tdc\.w\t(\d+),(\d+)', line)
        if m and cur is not None:
            cur.append((int(m.group(1)), int(m.group(2))))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--prg', default=str(ROOT / 'run' / 'dkongjr' / 'DKONGJR.PRG'))
    ap.add_argument('--map', default=str(BUILD / 'dkongjr.map'))
    a = ap.parse_args()
    h = SoundHarness(a.prg, a.map)
    mem = h.mem
    base = h.addr('dk_sound')
    tunes, fx = clip_table()
    patches = ym_patches()
    ports = {}

    def dma():
        """(start offset in dk_sound, control) of the clip the DMA was last told to play"""
        io = h.io
        start = (io[0x903] << 16) | (io[0x905] << 8) | io[0x907]
        return start - base, io[0x901]

    def frame(**kw):
        for k, v in kw.items():
            ports[int(k[1:], 16)] = v
        for p, v in ports.items():
            mem.w8(BLOCK + p, v)
        h.ym.clear()
        h.cpu.w_reg(R.A6, BLOCK)
        h.call(h.addr('sound_update'))
        return dma()

    def end_clip():                     # the DMA reaches the end of a one-shot: the hardware clears bit 0
        h.io[0x901] &= ~1
        mem.w8(0xff8901, h.io[0x901])

    h.call(h.addr('init_sound'))
    fails = []

    def check(what, got, want):
        if got != want:
            fails.append('%s: got %s, want %s' % (what, got, want))

    # backgrounds and one-shots
    for n in range(1, 7):
        check('background %d starts' % n, frame(p7c00=n), (tunes[n][0], 3))
        check('background %d holds' % n, frame(), (tunes[n][0], 3))
    frame(p7c00=2)
    check('one-shot 7 over background 2', frame(p7c00=7), (tunes[7][0], 1))
    frame(); frame(p7c00=2)
    check('the one-shot plays on', frame(), (tunes[7][0], 1))
    end_clip()
    check('background 2 again after it', frame(), (tunes[2][0], 3))
    check('leaving the background stops it', frame(p7c00=0)[1] & 1, 0)
    for n in range(7, 15):
        frame(p7c00=0)
        check('one-shot %d' % n, frame(p7c00=n), (tunes[n][0], 1))
        frame(p7c00=0)
        check('one-shot %d plays on at 0' % n, frame(), (tunes[n][0], 1))
        end_clip()
    frame(p7c00=0)
    # the pins, alone and together
    names = [('p7d03', '7d03'), ('p7d04', '7d04'), ('p7d05', '7d05'), ('p7d06', '7d06'), ('p7c81', '7c81'), ('p7d80', 'irq')]
    for port, name in names:
        check('pin %s' % name, frame(**{port: 1}), (fx['fx_' + name], 1))
        check('pin %s held: no restart' % name, frame(), (fx['fx_' + name], 1))
        frame(**{port: 0})
        end_clip()
    check('pins together: the IRQ wins', frame(p7d03=1, p7d80=1), (fx['fx_irq'], 1))
    frame(p7d03=0, p7d80=0)
    end_clip()
    check('pins 7D04 + 7C81: 7C81 wins', frame(p7d04=1, p7c81=1), (fx['fx_7c81'], 1))
    frame(p7d04=0, p7c81=0)
    end_clip()

    # the YM
    def ym_frames(n, **kw):
        out = []
        for i in range(n):
            frame(**(kw if i == 0 else {}))
            out.append(list(h.ym))
        return out

    def vol(writes, ch):
        v = [d for r, d in writes if r == 8 + ch]
        return v[-1] if v else None

    def period(writes, ch):
        lo = [d for r, d in writes if r == 2 * ch]
        hi = [d for r, d in writes if r == 2 * ch + 1]
        return (hi[-1] << 8 | lo[-1]) if lo and hi else None

    for port, name, ch, extra in (('p7d00', 'walk', 0, {}), ('p7d00', 'walk2', 0, {'p7d07': 1}),
                                  ('p7d01', 'jump', 1, {}), ('p7d02', 'climb', 2, {})):
        frame(**{k: v for k, v in extra.items()})
        pat = patches[name]
        got = ym_frames(len(pat) + 2, **{port: 1})
        for i, (per, v) in enumerate(pat):
            check('%s frame %d' % (name, i), (period(got[i], ch), vol(got[i], ch)), (per, v))
        check('%s: then silent' % name, vol(got[len(pat)], ch), 0)
        frame(**{port: 0}, **{k: 0 for k in extra})
    pat = patches['fall']
    got = ym_frames(10, p7d81=1)
    for i in range(10):
        check('fall frame %d' % i, (period(got[i], 0), vol(got[i], 0)), pat[i])
    got = ym_frames(2, p7d81=0)
    check('fall: silent the frame $7D81 drops', vol(got[0], 0), 0)
    check('fall: and stays so', vol(got[1], 0), None)

    if fails:
        print('%d failures' % len(fails))
        for f in fails[:30]:
            print('  ' + f)
        return 1
    print('sound driver: backgrounds 01-06 loop, one-shots 07-0E play to their end and give the channel back, the six '
          'pins by priority, walk / walk2 / jump / climb / fall frame by frame on the YM: all as the rules say')
    return 0


if __name__ == '__main__':
    sys.exit(main())
