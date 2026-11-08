"""The 68000's snd_update against tools/sound.py (the same model in Python): every frame of a scripted game the YM
registers 0-10 the runtime holds (snd_ym) must equal sound.ym_image of the WSG registers the translated sound CPU wrote
(its $6800-$681F cells, g3_block).  Not compared with MAME's audio.   python sound_test.py [frames]"""
import os, subprocess, sys
sys.path[:0] = [os.path.dirname(os.path.abspath(__file__)), os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "engine")]
from sim import Sim
from paths import ROOT, build_dir
import render_test as rt
import sound

frames = int(sys.argv[1]) if len(sys.argv) > 1 else 2600
RUN = ROOT / "run" / "digdug_sim"
s = Sim(str(RUN / "DIGDUG.PRG"), ram_kib=16384, run_dir=RUN)
sym = {k: v + s.base for k, v in s.symbols(build_dir("digdug") / "digdug.map").items()}
n = [0, 0, 0]


def on_frame(sim):
    in0, in1 = rt.script(s.frames)
    sim.mem.w8(sym["in0_kbd"], (~in0) & 0xff)
    sim.mem.w8(sym["in1_kbd"], (~in1) & 0xff)
    # (snd_update ran in this frame's VBL before this callback; the WSG cells are as it read them unless the next VBL's NMIs
    # changed them: compare against the cells' value at the same moment: the callback follows the VBL)
    wsg = [v & 15 for v in sim.mem.r_block(sym["g3_block"] + 0x6800, 32)]
    want = sound.ym_image(wsg, 0)
    got = list(sim.mem.r_block(sym["snd_ym"], 11))
    n[0] += 1
    if got == want:
        n[1] += 1
        if any(want[8:11]):
            n[2] += 1


s.run_frames(frames, on_frame=on_frame)
print("%d frames: the YM registers equal sound.py's image in %d (%d with a voice sounding)" % (n[0], n[1], n[2]))
sys.exit(0 if n[1] == n[0] else 1)
