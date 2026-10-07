import sys, os, pickle, glob
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'tools'))
from discover import *
rom = load_rom()
code, tables = discover(rom, [0x0000, 0x0008,0x0010,0x0018,0x0020,0x0028,0x0030,0x0038, 0x0066])
print('static instrs', len(code), 'rst28 sites', len(tables))
for site,(a,t) in sorted(tables.items()):
    print(hex(site), 'table@',hex(a), len(t), [hex(x) for x in t])
dyn=set()
for f in glob.glob('cover_*.pkl'):
    p,io=pickle.load(open(f,'rb')); dyn|=p
print('dyn', len(dyn))
missing = sorted(dyn-set(code))
print('dyn not static:', [hex(x) for x in missing][:80], len(missing))
# static not dyn
stat_only = sorted(set(code)-dyn)
print('static not dyn', len(stat_only))
