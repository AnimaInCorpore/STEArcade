import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'tools'))
from sim import Sim, RUN, STE
s = Sim(RUN / "DKSIM.PRG")
syms = s.symbols(STE / "build" / "dkong.map")
base = s.base; blk = base + syms["z80_block"]
def on_frame(sim):
    f = sim.frames
    sim.mem.w8(base + syms["in2_kbd"], 0x80 if 40 <= f < 50 else (0x04 if 80 <= f < 90 else 0))
    if f in (250, 330, 420):
        spr = bytes(sim.mem.r_block(blk + 0x6900, 0x180))
        used = [(i // 4, spr[i:i+4].hex()) for i in range(0, 0x180, 4) if spr[i:i+4] != b'\0\0\0\0']
        print('frame', f, len(used), used[:8], 'old counts', [sim.mem.r16(base + syms['spr_old_count'] + 2*i) for i in range(2)])
s.run_frames(430, on_frame)
sid_list = []
spr = bytes(s.mem.r_block(blk + 0x6900, 0x180))
tab = base + syms["spr_shape_table"]
for i in range(0, 0x180, 4):
    y, b1, b2, x = spr[i:i+4]
    if (y, b1, b2, x) == (0,0,0,0): continue
    sid = ((b1 & 0x7F) << 2) | ((b2 >> 7) << 1) | (b1 >> 7)
    top = (247 - y) & 255; px = 224 - top; py = (x - 8) & 255
    ptr = s.mem.r32(tab + 4 * sid)
    print(i // 4, 'sid', sid, 'px', px, 'py', py, 'routine table', hex(ptr))
