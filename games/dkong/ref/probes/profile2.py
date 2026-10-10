import sys, os, random, collections
sys.path[:0] = [os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "tools"), os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "..", "engine")]
from machine import *
m = DKong(); cpu = m.cpu
rnd = random.Random(5)
idle = set(range(0x2BD,0x2E3)) | set(range(0x315,0x37F)) | set(range(0x350,0x37F))
idle -= set([0x378,0x37b,0x37c])
nmi_c = idle_c = other_c = 0
in_nmi=False
per_frame_other=[]
for f in range(4000):
    m.in2 = 0
    if f % 700 == 200: m.in2 |= 0x80
    if f % 700 == 300: m.in2 |= 0x04
    m.in0 = rnd.choice([0,1,2,16,0,0,5,6,17])
    target = cpu.cycles + CYCLES_PER_FRAME
    fo=0
    if m.nmi_mask:
        cpu.nmi(); in_nmi=True
    while cpu.cycles < target:
        pc = cpu.pc
        c = cpu.step()
        if in_nmi: nmi_c += c
        elif pc in idle: idle_c += c
        else: other_c += c; fo+=c
        if in_nmi and pc==0xDF: in_nmi=False
    per_frame_other.append(fo)
    m.frame+=1
print('nmi',nmi_c/4000,'idle',idle_c/4000,'other main',other_c/4000)
print('max other in a frame', max(per_frame_other), 'frames with other>1000:', sum(1 for x in per_frame_other if x>1000))
