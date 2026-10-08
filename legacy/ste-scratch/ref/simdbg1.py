import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'tools'))
from sim import Sim, RUN, STE
s = Sim(RUN / "DKSIM.PRG")
syms = s.symbols(STE / "build" / "dkong.map")
s.run_frames(300)
blk = s.base + syms["z80_block"]
spr = bytes(s.mem.r_block(blk + 0x6900, 0x180))
used = [(i // 4, spr[i:i+4].hex()) for i in range(0, 0x180, 4) if spr[i:i+4] != b'\0\0\0\0']
print(len(used), used[:12])
print('old counts', [s.mem.r16(s.base + syms['spr_old_count'] + 2*i) for i in range(2)])
print('nmi mask', s.mem.r8(blk + 0x7d84), 'bank', s.mem.r8(blk+0x7d86), s.mem.r8(blk+0x7d87))
