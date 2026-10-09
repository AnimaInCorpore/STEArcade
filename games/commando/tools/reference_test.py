"""Regression checks for separate opcode/operand buses and FXSR source fetching."""
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[3]/'engine'))
from machine import CommandoZ80
from z80dis import decode
from sim import Blitter

class Image(bytes):pass

def main():
    # Immediate bytes stay encrypted/data bytes; ED/CB M1 bytes use opcode space.
    data=bytearray(65536);ops=bytearray(65536)
    data[:9]=bytes([0x99,0x42,0x99,0x99,0x99,0x99,0x99,0,0x46])
    ops[:9]=bytes([0x3e,0xff,0xed,0x44,0x00,0xdd,0xcb,0xff,0xff])
    cpu=CommandoZ80(lambda a:data[a],lambda a,v:data.__setitem__(a,v));cpu.opcodes=ops
    cpu.step();assert cpu.a==0x42
    cpu.step();assert cpu.a==0xbe
    cpu.step();cpu.ix=0xe000;data[0xe000]=1
    cpu.step();assert cpu.pc==9 and not(cpu.f&0x40), 'DDCB tail must use data space'
    image=Image(data);image.opcodes=ops
    assert decode(image,0).ops[-1]==('imm',0x42)
    assert decode(image,2).mn=='neg'
    assert decode(image,5).mn=='bit' and decode(image,5).ops[0]==('imm',0)
    class Memory:
        def __init__(self):self.data=bytearray(4096)
        def r16(self,a):return int.from_bytes(self.data[a:a+2],'big')
        def w16(self,a,v):self.data[a:a+2]=v.to_bytes(2,'big')
    class Bus:
        def __init__(self):self.io=bytearray(32768);self.mem=Memory()
    bus=Bus()
    def reg(off,value,size=2):bus.io[off:off+size]=value.to_bytes(size,'big')
    for i,v in enumerate([0xa123,0xb456,0xc789]):bus.mem.w16(0x100+2*i,v)
    for off,v in [(0xa20,2),(0xa22,2),(0xa28,65535),(0xa2a,65535),(0xa2c,65535),
                  (0xa2e,2),(0xa30,2),(0xa36,2),(0xa38,1),(0xa3a,0x0203)]:reg(off,v)
    reg(0xa24,0x100,4);reg(0xa32,0x200,4)
    reg(0xa3c,0x8088)
    Blitter(bus).run()
    assert bus.mem.r16(0x200)==0x23b4 and bus.mem.r16(0x202)==0x56c7
    print('PASS: encrypted opcode/operand decoding, indexed CB data fetch, FXSR extra source fetch')
if __name__=='__main__':main()
