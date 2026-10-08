import sys, os, random, time, collections
sys.path[:0] = [os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tools"), os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "engine")]
from machine import *
from paths import build_dir
from z80dis import decode
m = DKong(); cpu = m.cpu
rom = bytes(m.mem[:0x4000])
cnt = collections.Counter(); tcyc = collections.Counter()
nmi_cycles = 0
in_nmi=False
rnd = random.Random(5)
main_cyc = 0; nmi_cyc=0
for f in range(4000):
    m.in2 = 0
    if f % 700 == 200: m.in2 |= 0x80
    if f % 700 == 300: m.in2 |= 0x04
    m.in0 = rnd.choice([0,1,2,16,0,0,5,6,17])
    target = cpu.cycles + CYCLES_PER_FRAME
    if m.nmi_mask:
        cpu.nmi(); in_nmi=True
    while cpu.cycles < target:
        pc = cpu.pc
        c = cpu.step()
        cnt[pc]+=1; tcyc[pc]+=c
        if in_nmi: nmi_cyc += c
        else: main_cyc += c
        if in_nmi and pc==0xDF: in_nmi=False
    m.frame+=1
tot = sum(tcyc.values())
print('total T', tot, 'nmi frac', nmi_cyc/tot, 'per frame nmi', nmi_cyc/4000, 'main', main_cyc/4000)
# top routines by T
top = tcyc.most_common(40)
for pc,c in top:
    print('%04X %6.2f%% %s' % (pc, 100*c/tot, decode(rom,pc).text))
# instruction class mix
cls = collections.Counter()
for pc,c in cnt.items():
    i = decode(rom,pc)
    cls[i.mn]+=c
print(cls.most_common(40))
import pickle; pickle.dump((cnt,tcyc),open(build_dir('dkong') / 'profile.pkl','wb'))
