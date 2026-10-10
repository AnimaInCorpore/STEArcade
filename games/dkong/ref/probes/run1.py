import sys, time
import os; sys.path[:0] = [os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "tools"), os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "..", "engine")]
from machine import *
m = DKong()
t=time.time()
for f in range(200):
    m.run_frame()
    if f in (5,20,60,120,199):
        print(f, hex(m.cpu.pc), hex(m.cpu.sp), 'nmi', m.nmi_mask, 'pb', m.palette_bank, time.time()-t)
        save_png(m.render_rgb(), f'frame_{f:04d}.png')
print({hex(k):v for k,v in m.io_writes.items()})
print(m.dma_log[:40])
