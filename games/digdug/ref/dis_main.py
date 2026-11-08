"""Disassembly listing of a Dig Dug CPU ROM range: python ref/dis_main.py <cpu 1-3> <lo> <hi> (hex)"""
import sys, os
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [os.path.join(HERE, "..", "tools"), os.path.join(HERE, "..", "..", "..", "engine")]
import z80dis, machine
roms = [b"".join(machine.load(f) for f in ("dd1a.1", "dd1a.2", "dd1a.3", "dd1a.4")),
        machine.load("dd1a.5") + machine.load("dd1a.6"), machine.load("dd1.7")]
rom = roms[int(sys.argv[1]) - 1]
pc, hi = int(sys.argv[2], 16), int(sys.argv[3], 16)
while pc < hi:
    i = z80dis.decode(rom, pc)
    print("%04X  %s" % (pc, i.text))
    pc += i.length
