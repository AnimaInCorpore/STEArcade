import sys, os
sys.path[:0] = [os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tools"), os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "engine")]
from z80dis import decode
from paths import EXTRACTED
rom = open(EXTRACTED / 'dkong' / 'cpu.rom','rb').read()
pc = int(sys.argv[1],16); end = int(sys.argv[2],16)
while pc < end:
    i = decode(rom, pc)
    print('%04X  %-12s %s' % (pc, rom[pc:pc+i.length].hex(), i.text))
    pc += i.length
