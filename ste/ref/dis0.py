import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'tools'))
from z80dis import decode
rom = open('../assets/roms/extracted/cpu.rom','rb').read() if os.path.exists('../assets/roms/extracted/cpu.rom') else open('../../assets/roms/extracted/cpu.rom','rb').read()
pc = int(sys.argv[1],16); end = int(sys.argv[2],16)
while pc < end:
    i = decode(rom, pc)
    print('%04X  %-12s %s' % (pc, rom[pc:pc+i.length].hex(), i.text))
    pc += i.length
