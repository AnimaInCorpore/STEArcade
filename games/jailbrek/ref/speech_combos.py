"""The speech phrases the game can ask for: (data latch at ST's falling edge, the parameter latched at RST's falling
edge) of every sound command $80-$98 ($16CA with the flag $16CB set, as the sound queue's reader $B001 takes them),
each run on a copy of the reference machine (attract mode, frame 450).  tools/assets.py SPEECH is this list.

    python games/jailbrek/ref/speech_combos.py
"""
import sys,copy,random,collections
sys.path[:0]=["games/jailbrek/tools","games/jailbrek/ref","engine"]
from machine import JailBreakPort, vlm_nmis
import cover
def combos(log):
    latch=0; st=rst=0; param=0; out=[]
    for fr,k,v in log:
        if k=='vlm': latch=v
        elif k=='pins':
            s=v>>1&1; r=v>>2&1
            if r!=rst:
                rst=r
                if not r: param=latch
            if s!=st:
                st=s
                if not s: out.append((latch,param))
    return out
m=JailBreakPort(*cover.dsw(1))
rnd=random.Random(1); state={}
for f in range(450):
    m.frame=f; m.system,m.p1,m.p2=cover.inputs(f,rnd,state); m.run_frame_port()
print("base",combos(m.sound_log))
found=collections.Counter()
for code in range(0x80,0x99):
    m2=copy.deepcopy(m); m2.sound_log=[]
    m2.mem[0x16CA]=code; m2.mem[0x16CB]=1; m2.mem[0x16C9]=0; m2.mem[0x170D]=0; m2.mem[0x16C8]=0
    for f in range(450,520):
        m2.frame=f; m2.system,m2.p1,m2.p2=0xFF,0xFF,0xFF; m2.run_frame_port()
    c=combos(m2.sound_log)
    print(hex(code),c[:6],flush=True)
    for x in c: found[x]+=1
print(sorted(found))
