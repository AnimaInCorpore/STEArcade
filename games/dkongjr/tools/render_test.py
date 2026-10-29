"""The STE's picture against the reference renderer at frozen moments: a --sim build with -D DUMPAT=N (and AUTOSTART,
so the play is drawn too) runs on Musashi; from VBL N the game stands still and the renderer goes on.  Some VBLs later
the screen shown (display_screen_address: 256 lines x the 224 pixel game area) is compared pixel by pixel with
machine.render_raw() of the arcade RAM and latches the build froze, through the palette map of tools/assets.py.

    python render_test.py [N | N:STAGE ...]   (default: 400 1100 1700 2300, 900 / 1300 on stages 1, 3, 4, and
                                              the 60th / 200th / 450th frame of the title, tile bank 1)

The frames are VBLs of the STE build, not arcade frames: the game's idle loop counts its spins, so a build's attract
mode depends on its speed (see games/dkong/README.md); what is compared is a frozen frame against its own RAM.
"""
import os
import subprocess
import sys
sys.path[:0] = [os.path.dirname(os.path.abspath(__file__)), os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "engine")]
import numpy as np
from sim import Sim
from paths import ROOT, build_dir
from machine import DKongJr, Gfx, save_png
import assets

RUN = ROOT / "run" / "dkongjr_freeze"
GAME_X = 24                     # bytes: the game area starts 3 chunks into the line
STRIDE = 256
LINES = 256


def screen(mem, base):
    """the 256 display lines x 224 pixels of the screen buffer at base: STE colour indices"""
    raw = np.frombuffer(bytes(mem.r_block(base, LINES * STRIDE)), np.uint8).reshape(LINES, STRIDE)
    area = raw[:, GAME_X:GAME_X + 112].reshape(LINES, 14, 4, 2)
    words = (area[..., 0].astype(np.uint16) << 8) | area[..., 1]
    out = np.zeros((LINES, 224), np.uint8)
    for k in range(4):
        w = words[:, :, k]
        for b in range(16):
            out[:, b::16] |= (((w >> (15 - b)) & 1).astype(np.uint8) << k)
    return out


def reference(block, penmap):
    """render_raw() of the frozen RAM and latches, as STE colour indices on the STE's display (line = raw x,
    column = 239 - raw y: the upright cabinet's picture, $7D82 = 1)"""
    m = DKongJr()
    m.mem[0x6000:0x8000] = block[0x6000:0x8000]
    m.palette_bank = (block[0x7D86] & 1) | (block[0x7D87] & 1) << 1
    m.gfx_bank = block[0x7C80] & 1
    m.sprite_bank = block[0x7D83] & 1
    raw = m.render_raw()                            # [y][x] pens
    ste = np.array(penmap, np.uint8)[raw]
    return ste[16:240].T[:, ::-1]                   # [x][239 - y]


def check(n, penmap, pal, stage=None, bank=None):
    RUN.mkdir(parents=True, exist_ok=True)
    tag = ("%d" % n if stage is None else "%d_s%d" % (n, stage)) + ("" if bank is None else "_t%d" % bank)
    prg = RUN / ("FREEZE%s.PRG" % tag)
    out = build_dir("dkongjr") / "render_test"
    out.mkdir(exist_ok=True)
    mapfile = out / ("freeze%s.map" % tag)
    r = subprocess.run([sys.executable, os.path.join(os.path.dirname(os.path.abspath(__file__)), "build.py"), "--sim",
                        "--dumpat" if bank is None else "--dumptile", str(n), "--out", str(prg)]
                       + ([] if stage == 0 else ["-D", "AUTOSTART=150"])
                       + ([] if not stage else ["-D", "STAGE=%d" % stage]), capture_output=True, text=True)
    if r.returncode:
        raise SystemExit(r.stdout + r.stderr)
    (build_dir("dkongjr") / "dkongjr.map").replace(mapfile)     # (build.py names the map after the game)
    s = Sim(str(prg), ram_kib=16384, run_dir=RUN)
    sym = {k: v + s.base for k, v in s.symbols(mapfile).items()}
    # DUMPAT counts the frames the program drew (frame_counter), the simulator its VBLs: a slow frame skips VBLs, so the
    # freeze comes later than VBL n.  Run until it has happened, then three more so both screens show the frozen RAM.
    # (DUMPTILE: the n-th frame with tile bank 1, whenever the title comes: its time follows the build's speed.)
    s.run_frames(n if bank is None else 1000)
    for extra in range(n if bank is None else 6000):
        if s.mem.r8(sym["freeze_flag"]):
            break
        s.run_frames(1)
    else:
        raise SystemExit("VBL %d: the build never froze" % n)
    s.run_frames(3)
    block = bytes(s.mem.r_block(sym["z80_block"], 0x8000))
    if block[0x7D82] & 1 == 0:
        print("VBL %d: the game set $7D82 = 0 (flipped picture), not compared" % n)
        return 0
    if bank is not None and block[0x7C80] & 1 != bank:
        print("%d: tile bank %d, not %d: not the frame this check is for (the attract mode's timing follows the "
              "program's speed: pick another VBL)" % (n, block[0x7C80] & 1, bank))
        return 1
    mine = screen(s.mem, s.mem.r32(sym["display_screen_address"]))
    want = reference(block, penmap)
    diff = np.argwhere(mine != want)
    if len(diff):
        img = np.concatenate([mine, want, np.where(mine != want, 15, want)], axis=1)
        save_png(pal[img], str(out / ("render_diff_%s.png" % tag)), 2)
    else:
        save_png(pal[mine], str(out / ("render_%s.png" % tag)), 2)
    print("%s %d: %d of %d pixels differ (%d drawn; stage $6227 = %d, tile bank %d, palette bank %d)%s" % (
        "VBL" if bank is None else "title frame", n, len(diff), mine.size, int((want != 0).sum()), block[0x6227], block[0x7C80] & 1,
        (block[0x7D86] & 1) | (block[0x7D87] & 1) << 1,
        "" if not len(diff) else ", first (line, x) %s; %s" % ([tuple(map(int, d)) for d in diff[:4]],
                                                                out / ("render_diff_%s.png" % tag))))
    return len(diff)


def main():
    """arguments: VBLs, or VBL:STAGE (the game started on that stage, see STAGE in src/dkongjr.s; 0: no coin, the
    attract sequence with the title logo in tile bank 1), or N:0:1: the N-th frame drawn with tile bank 1 (the title,
    whose time follows the build's speed: the idle loop counts its spins and the demo's length depends on them)"""
    args = sys.argv[1:] or ["400", "1100", "1700", "2300", "900:1", "900:3", "900:4", "1300:1", "1300:3", "1300:4",
                            "60:0:1", "200:0:1", "450:0:1"]
    frames = [tuple(int(x) for x in a.split(":")) for a in args]
    palette, penmap, _ = assets.build()
    pal = np.array([[v * 17 for v in c] for c in palette], np.uint8)
    mainmap = build_dir("dkongjr") / "dkongjr.map"          # the plain build's map: the test builds write over it
    keep = mainmap.read_bytes() if mainmap.exists() else None
    try:
        bad = sum(1 for f in frames if check(f[0], penmap, pal, f[1] if len(f) > 1 else None, f[2] if len(f) > 2 else None))
    finally:
        if keep is not None:
            mainmap.write_bytes(keep)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
