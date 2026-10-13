"""The state the STE port starts from: the reference board at machine.START (both CPUs idle), as data for the runtime.

    from snapshot import write; write()     -> build/galaga88/snapshot.bin

The boot (RAM tests, the MCU handshake, the sub CPU's resets) is not translated; the port starts where the reference is
after it.  snapshot.bin holds, in this order:
    vio      $28000 bytes: the virtual space $2E0000-$307FFF (the CPU-visible bytes; the C116 registers in all copies)
    per CPU (main, sub): 8 words the virtual page in each slot, A B X Y U S (words), CC (word)
    key      8 bytes the key custom's registers, its remainder, quotient and the numerator's high word (words)
    mcu      the MCU model's state (games/splatter/tools/mcu.py MCUNative.state_image: the same CUS64 program)
The runtime copies vio to its image and fills the contexts (src/galaga88.s, snapshot_load).
"""
import struct
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parents[2] / "engine"), str(HERE.parents[1] / "splatter" / "tools")]
from machine import Galaga88
from paths import build_dir

VIO0, VIO_SIZE = 0x2E0000, 0x28000


def capture(m=None):
    if m is None:
        m = Galaga88()
        m.boot()
    vio = bytearray(VIO_SIZE)
    vio[0:0x8000] = bytes(m.c116_rd(o) for o in range(0x8000))
    vio[0x10000:0x18000] = m.vram
    vio[0x1C000:0x1C800] = m.scratch
    vio[0x1C800:0x1D000] = m.spriteram
    vio[0x1D000:0x1D020] = m.control
    vio[0x1E000:0x1E400] = m.sound_ram
    vio[0x1F000:0x1F800] = m.triram
    vio[0x20000:0x28000] = m.ram
    cpus = b""
    for i in (0, 1):
        c = m.cpus[i]
        cpus += struct.pack(">8H", *[o >> 13 for o in m.offsets[i]])
        cpus += struct.pack(">7H", c.a, c.b, c.x, c.y, c.u, c.s, c.cc)
    key = bytes(m.key[:8]) + struct.pack(">3H", m.key_reminder, m.key_quotient, m.key_numerator_high)
    from mcu import MCUNative
    mcu = MCUNative.from_board(m).state_image()
    return bytes(vio) + cpus + key + mcu, m


def write(build=None):
    build = build or build_dir("galaga88")
    data, m = capture()
    (build / "snapshot.bin").write_bytes(data)
    return m


if __name__ == "__main__":
    write()
    print("snapshot.bin written")
