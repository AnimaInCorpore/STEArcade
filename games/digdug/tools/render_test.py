"""The STE's picture against the reference renderer at frozen moments of a game: a --sim build with -D FREEZEAT=N runs on
Musashi (from VBL N the game's interrupts stop, the renderer goes on); some VBLs later the screen shown
(display_screen_address, the 224 x 288 display, rotated) is compared pixel by pixel with machine.render_raw(wrap=False)
of the arcade RAM the build froze and its video latch, through the palette map of tools/assets.py.  The inputs are
script() as schedule_test.py's: the moments are in the attract mode (N < 1000) and in play.

    python render_test.py [N ...]          (default: 1500 2500 3500 5000)
"""
import os
import subprocess
import sys
sys.path[:0] = [os.path.dirname(os.path.abspath(__file__)), os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "engine")]
import numpy as np
from sim import Sim
from paths import ROOT, build_dir
from machine import DigDug, Gfx, save_png
import assets

RUN = ROOT / "run" / "digdug_freeze"
DISP_TOP = 32
GAME_X = 24
STRIDE = 256


def script(f):
    in0 = in1 = 0xff
    if 800 <= f < 806: in1 &= ~0x10
    if 840 <= f < 846: in1 &= ~0x04
    if f >= 900:
        g = f - 900
        in0 &= ~(0x02 if (g // 40) % 2 else 0x08)
        if (g // 70) % 2: in0 &= ~(0x04 if (g // 30) % 2 else 0x01)
        if g % 20 < 3: in1 &= ~0x01
    return in0, in1


def screen(mem, base):
    """the 288 display lines x 224 pixels of the screen buffer at base: STE colour indices"""
    raw = np.frombuffer(bytes(mem.r_block(base + DISP_TOP * STRIDE, 288 * STRIDE)), np.uint8).reshape(288, STRIDE)
    area = raw[:, GAME_X:GAME_X + 112].reshape(288, 14, 4, 2)
    words = (area[..., 0].astype(np.uint16) << 8) | area[..., 1]
    out = np.zeros((288, 224), np.uint8)
    for k in range(4):
        w = words[:, :, k]
        for b in range(16):
            out[:, b::16] |= (((w >> (15 - b)) & 1).astype(np.uint8) << k)
    return out


def reference(mem, sym, pmap):
    """the reference renderer on the arcade RAM and video latch of the build, rotated like the STE's display"""
    m = DigDug(skip_tests=True)
    base = sym["g_block"] + 0x8000
    m.ram[:] = bytes(mem.r_block(base, 0x2000))
    m.vlatch[:] = [mem.r8(base + 0x2000 + k) & 1 for k in range(8)]
    raw = m.render_raw(wrap=False)              # [raw y][raw x], palette entries
    return np.array(pmap, np.uint8)[raw].T[:, ::-1]      # display y = raw x, display x = 223 - raw y


def check(n, pmap):
    RUN.mkdir(parents=True, exist_ok=True)
    prg = RUN / ("FREEZE%d.PRG" % n)
    subprocess.run([sys.executable, os.path.join(os.path.dirname(os.path.abspath(__file__)), "build.py"), "--sim",
                    "-D", "FREEZEAT=%d" % n, "--out", str(prg)], check=True, stdout=subprocess.DEVNULL)
    s = Sim(str(prg), ram_kib=16384, run_dir=RUN)
    sym = {k: v + s.base for k, v in s.symbols(build_dir("digdug") / "digdug.map").items()}

    def on_frame(sim):
        in0, in1 = script(s.frames)
        sim.mem.w8(sym["in0_kbd"], (~in0) & 0xff)
        sim.mem.w8(sym["in1_kbd"], (~in1) & 0xff)
    s.run_frames(n + 40, on_frame=on_frame)      # (a busy picture takes several VBLs: the shown one must be of the frozen state)
    mine = screen(s.mem, s.mem.r32(sym["display_screen_address"]))
    want = reference(s.mem, sym, pmap)
    diff = np.argwhere(mine != want)
    if len(diff):
        img = np.concatenate([mine, want, np.where(mine != want, 15, want)], axis=1)
        pal = np.array([[v * 17 for v in c] for c in assets.build_palette(Gfx())[0]], np.uint8)
        save_png(pal[img], str(build_dir("digdug") / ("render_diff_%d.png" % n)), 2)
    print("VBL %d: %d of %d pixels differ (%d drawn)%s" % (n, len(diff), 288 * 224, int((want != 0).sum()),
                                              "" if not len(diff) else ", first (line, x) %s; build/digdug/render_diff_%d.png" % (
                                                  [tuple(map(int, d)) for d in diff[:4]], n)))
    return len(diff)


def main():
    frames = [int(a) for a in sys.argv[1:]] or [1500, 2500, 3500, 5000]
    pmap = assets.build_palette(Gfx())[1]
    bad = sum(1 for n in frames if check(n, pmap))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
