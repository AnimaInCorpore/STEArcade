"""The state the STE port starts from: the reference at machine.START (the main CPU idle), as data for the runtime.

    from snapshot import write; write()     -> build/mrheli/snapshot.bin

As R-Type's (games/rtype/tools/snapshot.py), with Mr. HELI's dual-port RAM and the MCU model's state.  The boot (the ROM
and RAM tests, the code the MCU puts into the dual-port RAM) is not translated: the port starts where the reference is
after it (START = 500 >= the MCU model's BOOT_END 484).  snapshot.bin holds, in this order (the V30's memory with the
bytes of each word swapped, as in v30_image):
    $4000 the work RAM ($A0000), $1000 the dual-port RAM ($B0000), $400 the sprite RAM ($C0000), $C00 palette 0
    ($C8000), $C00 palette 1 ($CC000), $4000 the FG video RAM ($D0000), $4000 the BG video RAM ($D8000), $400 the
    sprite buffer (the last DMA)
    words: DS1 PS SS DS0, IE, DF, the parity byte, the AC byte (bytes as words), AW CW DW BW IX IY BP, SP, the CCR,
    the scroll registers (ports $80-$86), the raster register (port $06), port $02
    14 bytes: the MCU model's state (tools/mcu.py MCU.from_board(...).state_image(): src/mcu.s mcu_init)
mrheli.s snapshot_load copies them to the image, the context, the port words and the MCU model.

A replay point (REPLAY=seed:frame in the environment, e.g. 8:3000): the reference with a lock-step test's inputs
(ref/cover.py; seeds 8+ with the Invulnerability DIP switch: build with -D INVULN) at that port frame instead.
"""
import os
import random
import struct
import sys
from pathlib import Path

sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[1] / "ref"),
                str(Path(__file__).resolve().parents[3] / "engine")]
from machine import MrHeli
from paths import build_dir
from v30 import PAR
import mcu


def swap(b):
    out = bytearray(len(b))
    out[0::2] = b[1::2]
    out[1::2] = b[0::2]
    return bytes(out)


def boot_board():
    path = build_dir("mrheli") / "state_boot.z"
    if path.exists():
        return MrHeli.load(path)[0]
    m = MrHeli()
    m.boot()
    m.save(path)
    return m


def mcu_state(m):
    """the MCU model's state from the reference's i8751 (stepped into its main loop if it is in a handler)"""
    u = m.mcu.core.cpu
    for _ in range(20000):
        try:
            return mcu.MCU.from_board(m).state_image()
        except ValueError:
            u.run(1)
    raise RuntimeError("the MCU did not come back to its main loop")


def capture(m):
    c = m.main.core.cpu
    data = b"".join(swap(bytes(x)) for x in (m.ram, m.dpram, m.spriteram, m.palette[0], m.palette[1], m.videoram[0],
                                            m.videoram[1], m.spritebuf))
    f = c.flags
    ccr = (f & 1) | (2 if f & 0x800 else 0) | (4 if f & 0x40 else 0) | (8 if f & 0x80 else 0)
    words = list(c.sr) + [0xFF if c.ie else 0, 0xFF if c.df else 0, 0 if PAR[c.pv & 0xFF] else 1,
                          0x10 if c.av else 0]
    words += [c.r[i] for i in (0, 1, 2, 3, 6, 7, 5)] + [c.sp, ccr]
    words += [m.scrolly[0], m.scrollx[0], m.scrolly[1], m.scrollx[1], (m.raster_line + 128) & 0xFFFF, m.port02]
    return data + struct.pack(">%dH" % len(words), *words) + mcu_state(m)


def replay_board(seed, frame):
    """the reference after `frame` port frames of seed's play (as logic_test.py runs it)"""
    import cover
    m = boot_board()
    rng, state = random.Random(seed), dict(hold=0, bits=0)
    if seed >= 8:
        m.dsw &= ~0x4000
    for f in range(frame):
        cover.press(m, f, seed, rng, state)
        m.run_frame_port()
    return m


def write(build=None):
    build = build or build_dir("mrheli")
    rp = os.environ.get("REPLAY")
    if rp:
        seed, frame = (int(x) for x in rp.split(":")[:2])
        m = replay_board(seed, frame)
        print("snapshot.bin: seed %d at frame %d" % (seed, frame))
    else:
        m = boot_board()
    (build / "snapshot.bin").write_bytes(capture(m))
    return m


if __name__ == "__main__":
    write()
    print("snapshot.bin written")
