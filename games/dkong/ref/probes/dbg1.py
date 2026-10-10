import sys, os, bisect
sys.path[:0] = [os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "tools"), os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "..", "engine")]
from logic_test import *
L = Lock()
L.set_inputs(0,0,0,0x80)
labs = sorted((v,k) for k,v in L.sym.items() if re.fullmatch(r'Z[0-9A-F]{4}(_r)?', k))
addrs=[a for a,_ in labs]
def where(pc):
    i=bisect.bisect_right(addrs,pc)-1
    return labs[i][1], pc-labs[i][0]
for i in range(8):
    L.cpu.execute(20000)
    print(hex(L.cpu.r_pc()), where(L.cpu.r_pc()), 'hl=%X bc=%X de=%X d6=%X a=%X' % (L.cpu.r_reg(R.D3)&0xFFFF, L.cpu.r_reg(R.D1)&0xFFFF, L.cpu.r_reg(R.D2)&0xFFFF, L.cpu.r_reg(R.D6)&0xFFFF, L.cpu.r_reg(R.D0)&0xFF))
print('---')
for i in range(30):
    L.cpu.execute(2_000_000)
    pc=L.cpu.r_pc()
    print(hex(pc), where(pc), 'hl=%X bc=%X de=%X d6=%X a=%X' % (L.cpu.r_reg(R.D3)&0xFFFF, L.cpu.r_reg(R.D1)&0xFFFF, L.cpu.r_reg(R.D2)&0xFFFF, L.cpu.r_reg(R.D6)&0xFFFF, L.cpu.r_reg(R.D0)&0xFF))
    if pc == L.sym['z80_hook']: break
