"""The state the STE port starts from: the reference board at machine.START (the main CPU idle), as data for the runtime.

    from snapshot import write; write()     -> build/rtype/snapshot.bin

The boot (the ROM and RAM tests, the sound CPU's program) is not translated; the port starts where the reference is
after it.  snapshot.bin holds, in this order (the V30's memory with the bytes of each word swapped, as in v30_image):
    $4000 the work RAM ($40000), $400 the sprite RAM ($C0000), $C00 palette 0 ($C8000), $C00 palette 1 ($CC000),
    $4000 the FG video RAM ($D0000), $4000 the BG video RAM ($D8000), $400 the sprite buffer (the last DMA)
    words: DS1 PS SS DS0, IE, DF, the parity byte, the AC byte (bytes as words), AW CW DW BW IX IY BP, SP, the CCR,
    the scroll registers (ports $80-$86), the raster register (port $06), port $02
rtype.s snapshot_load copies them to the image, the context and the port words.
"""
import struct
import sys
from pathlib import Path

sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[3] / "engine")]
from machine import RType
from paths import build_dir
from v30 import PAR


def swap(b):
    out = bytearray(len(b))
    out[0::2] = b[1::2]
    out[1::2] = b[0::2]
    return bytes(out)


def capture(m=None):
    if m is None:
        m = RType()
        m.boot()
    c = m.main.core.cpu
    data = b"".join(swap(bytes(x)) for x in (m.ram, m.spriteram, m.palette[0], m.palette[1], m.videoram[0],
                                            m.videoram[1], m.spritebuf))
    f = c.flags
    ccr = (f & 1) | (2 if f & 0x800 else 0) | (4 if f & 0x40 else 0) | (8 if f & 0x80 else 0)
    words = list(c.sr) + [0xFF if c.ie else 0, 0xFF if c.df else 0, 0 if PAR[c.pv & 0xFF] else 1,
                          0x10 if c.av else 0]
    words += [c.r[i] for i in (0, 1, 2, 3, 6, 7, 5)] + [c.sp, ccr]
    words += [m.scrolly[0], m.scrollx[0], m.scrolly[1], m.scrollx[1], (m.raster_line + 128) & 0xFFFF, m.port02]
    return data + struct.pack(">%dH" % len(words), *words), m


def write(build=None):
    build = build or build_dir("rtype")
    data, m = capture()
    (build / "snapshot.bin").write_bytes(data)
    return m


if __name__ == "__main__":
    write()
    print("snapshot.bin written")
