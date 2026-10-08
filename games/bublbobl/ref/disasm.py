"""Disassemble a range of a Bubble Bobble CPU ROM: python ref/disasm.py <main|sub|snd> <from> <to>"""
import os, sys
sys.path[:0] = [os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tools"), os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "engine")]
from z80dis import decode
from machine import Bublbobl
m = Bublbobl()
rom = {"main": bytes(m.main_rom), "sub": m.sub_rom, "snd": m.snd_rom}[sys.argv[1]]
pc, end = int(sys.argv[2], 16), int(sys.argv[3], 16)
while pc < end:
    i = decode(rom, pc)
    print("%04X  %-12s %s" % (pc, rom[pc:pc + i.length].hex(), i.text))
    pc += i.length
