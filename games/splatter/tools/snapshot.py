"""The state the STE port starts from: the reference board at machine.START (both CPUs idle), as data for the runtime.

    from snapshot import write; write(build_dir)     -> build/splatter/snapshot.bin + snapshot.s (the layout)

The boot (RAM tests, the MCU handshake, the sub CPU's resets) is not translated; the port starts where the reference is
after it.  snapshot.bin holds, in this order:
    vio      $28000 bytes: the virtual space $2E0000-$307FFF (the CPU-visible bytes; the C116 registers in their first copy)
    per CPU (main, sub): 8 words the virtual page in each slot, A B X Y U S (words), CC (word)
    key      8 bytes the key custom's registers, 4 bytes MAME's rand() seed
    mcu      the MCU model's state (tools/mcu.py, when there)
The runtime copies vio to its image and fills the contexts (src/splatter.s, snapshot_load).
"""
import struct
import sys
from pathlib import Path

sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[3] / "engine")]
from machine import Splatter
from paths import build_dir

VIO0, VIO_SIZE = 0x2E0000, 0x28000


def capture(m=None):
    if m is None:
        m = Splatter()
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
    key = bytes(m.key[:8]) + struct.pack(">I", m.rand_seed)
    return bytes(vio) + cpus + key, m


def write(build=None):
    build = build or build_dir("splatter")
    data, m = capture()
    (build / "snapshot.bin").write_bytes(data)
    return m


if __name__ == "__main__":
    write()
    print("snapshot.bin written")
