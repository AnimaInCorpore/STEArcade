import sys, os
sys.path[:0] = [os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tools"), os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "engine")]
from machine import *
from z80dis import decode
m = DKong()
cpu = m.cpu
rom = bytes(m.mem[:0x4000])
main_pcs = {}
nmi_pcs = {}
in_nmi = False
import collections
for f in range(1700):
    m.in2 = 0
    if 200 <= f < 210: m.in2 |= 0x80
    if 300 <= f < 310: m.in2 |= 0x04
    target = cpu.cycles + CYCLES_PER_FRAME
    if m.nmi_mask:
        cpu.nmi(); in_nmi = True
    while cpu.cycles < target:
        pc = cpu.pc
        (nmi_pcs if in_nmi else main_pcs)[pc] = 1
        if in_nmi and pc == 0xDF: 
            cpu.step(); in_nmi=False; continue
        cpu.step()
    m.frame += 1
print('main pcs', len(main_pcs), 'nmi pcs', len(nmi_pcs))
# print main-loop code ranges
pcs = sorted(main_pcs)
runs=[]; s=pcs[0]; p=pcs[0]
for a in pcs[1:]:
    if a - p > 6:
        runs.append((s,p)); s=a
    p=a
runs.append((s,p))
print([(hex(a),hex(b)) for a,b in runs])
