"""The state the BIOS hands the game: the reference board (tools/machine.py, as MAME) from power-on to the first
`jmp $40000` ($0009F0, frame 378; the self-tests, the sound CPU's start and the BIOS's wait are behind it).

    venv/bin/python games/gauntlet/tools/boot.py     -> build/gauntlet/boot.bin

The STE program starts there instead of running the BIOS (its ROM checksums would fail on the patched image, and it
waits six seconds for the sound CPU): the video RAM, palette, work RAM and EEPROM as they are, the registers, SR,
the slapstic's bank.  Layout of boot.bin (big-endian): $6000 video RAM ($900000), $800 palette, $2000 work RAM,
$400 EEPROM ($802000, the low bytes in the odd ones), 16 longs D0-D7/A0-A7, the word SR, the long PC, the word bank.
"""
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "engine"))
from machine import Gauntlet
from paths import build_dir
import m68kmame as M

HANDOFF = 0x40000


def capture():
    m = Gauntlet()
    c = m.cpu
    hit = []
    jumping = []

    def at(pc):
        """(the hook runs before the instruction: the state at the hand-off)"""
        if jumping and not hit:
            mem = c.mem
            eeprom = bytearray(0x400)
            for i, v in enumerate(m.eeprom.data):
                eeprom[2 * i] = 0xFF
                eeprom[2 * i + 1] = v
            regs = [c.get(i) for i in range(16)]
            hit.append((bytes(mem[0x900000:0x906000]) + bytes(mem[0x910000:0x910800]) +
                        bytes(mem[0x800000:0x802000]) + bytes(eeprom) +
                        struct.pack(">16IHIH", *regs, c.sr, pc, c.slapstic_state()[1]), m.frame))
    c.hook(0x9F0, lambda pc: jumping.append(pc))
    c.hook(HANDOFF, at)
    while not hit:
        m.run_frame()
        if m.frame > 1000:
            raise RuntimeError("no hand-off to $40000")
    return hit[0]


if __name__ == "__main__":
    data, frame = capture()
    (build_dir("gauntlet") / "boot.bin").write_bytes(data)
    print("hand-off at frame %d: %d bytes -> build/gauntlet/boot.bin" % (frame, len(data)))
