"""The real 51XX / 54XX of tools/machine.py (Galaga(mcu=True)) against MAME 0.289 with the real MCU ROMs.

Both run the same input script from power-on (no RAM-test patch); MAME logs every 06XX access of the main CPU
(ref/mame_51xx.lua), the reference machine the same, and the two logs and the RAM at the dump frames are compared.
MAME's frame_done callback runs at the end of a frame (line 264): frame k of the logs is the reference's frame index
k (k frames done), its inputs are set before that frame runs, and the RAM / MCU states are taken after a frame.

    python ref/mame_cmp_51xx.py [frames] [script]      # default 2400 coin; scripts: attract, coin, two, coins

Results 2026-10-21 (MAME 0.289): coin 2400 frames and two 6000 frames: the 51XX traffic (8448 / 15861 accesses) and the
51XX's data RAM in every frame identical; coins 3000 frames: see the README.  The 54XX: identical until its release from
reset, which the reference's main CPU writes 16.4 lines earlier than MAME's (main CPU timing, not the MCU); started at
MAME's moment it matches within the sampling jitter through its first commands.
"""
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [os.path.join(HERE, "..", "tools"), os.path.join(HERE, "..", "..", "..", "engine")]
import machine
from paths import ROMS

FRAMES = int(sys.argv[1]) if len(sys.argv) > 1 else 2400
SCRIPT = sys.argv[2] if len(sys.argv) > 2 else "coin"
DUMPS = [f for f in (600, 900, 1200, 1500, 1800, 2100, 2400, 3000, 3600) if f <= FRAMES]


def inputs(f):
    """(in0, in1) for frame f, active low"""
    in0 = in1 = 0xff
    if SCRIPT == "coins":
        # coin 2, the service coin, a held coin, coins during a game, both start buttons with too few credits
        for t, bit in ((1000, 0x20), (1040, 0x10), (1080, 0x40), (1120, 0x08), (1160, 0x20), (1200, 0x04),
                       (1500, 0x10), (1540, 0x20), (1580, 0x08)):
            if t <= f < t + 6: in1 &= ~bit
        if 1300 <= f < 1400: in1 &= ~0x10                          # held for 100 frames
        if f >= 1250 and (f // 9) % 4 == 0: in1 &= ~0x01
        if f >= 1250: in0 &= ~(0x02 if (f // 60) % 2 else 0x08)
    if SCRIPT in ("coin", "two"):
        if 1000 <= f < 1006: in1 &= ~0x10                          # coin 1
        if SCRIPT == "two" and 1060 <= f < 1066: in1 &= ~0x10
        if 1150 <= f < 1156: in1 &= ~(0x08 if SCRIPT == "two" else 0x04)
        if f >= 1400:
            if (f // 7) % 3 == 0: in1 &= ~0x01                    # fire
            in0 &= ~(0x02 if (f // 45) % 2 else 0x08)             # right / left
    return in0, in1


def run_mame(out):
    if os.path.exists(os.path.join(out, "ram_%d.bin" % DUMPS[-1])):
        print("MAME run cached in", out)
        return parse_mame(out)
    print("running MAME ...", flush=True)
    rompath = tempfile.mkdtemp()
    for z in ("galaga.zip", "namco51.zip", "namco54.zip"):
        os.symlink(os.path.join(ROMS, z), os.path.join(rompath, z))
    with open(os.path.join(out, "inputs.txt"), "w") as f:
        last = None
        for fr in range(FRAMES + 1):
            v = inputs(fr)
            if v != last:
                f.write("%d %02x %02x\n" % (fr, v[0], v[1]))
                last = v
    env = dict(os.environ, OUT=out, INPUTS=os.path.join(out, "inputs.txt"), FRAMES=str(FRAMES),
               DUMP=" ".join(map(str, DUMPS)))
    subprocess.run(["mame", "galaga", "-window", "-video", "none", "-rompath", rompath, "-sound", "none",
                    "-nothrottle", "-seconds_to_run", "250", "-skip_gameinfo", "-autoboot_script",
                    os.path.join(HERE, "mame_51xx.lua")], env=env, cwd=out, check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return parse_mame(out)


def mcu_state(chip):
    return "".join("%x" % (v & 15) for v in chip.mcu.ram)


def parse_mame(out):
    io, dsw, mcus = [], None, {}
    for line in open(os.path.join(out, "io.txt")):
        p = line.split()
        if p[0] == "reinstalls":
            print("MAME: taps reinstalled %s times" % p[1])
            continue
        if p[1] in ("m51", "m54"):
            mcus[(int(p[0]), p[1])] = p[2]
            continue
        if p[0] == "dsw":
            dsw = (int(p[1], 16), int(p[2], 16))
            continue
        io.append((int(p[0]), p[1], int(p[2], 16)))
    rams = {f: open(os.path.join(out, "ram_%d.bin" % f), "rb").read() for f in DUMPS}
    return io, rams, dsw, mcus


def run_ref(dsw):
    m = machine.Galaga(mcu=True)
    if dsw:
        m.dswa, m.dswb = dsw
    io, rams, mcus = [], {}, {}
    rd, wr = m.cpus[0].rd8, m.cpus[0].wr8

    def rd8(a):
        v = rd(a)
        if 0x7000 <= a <= 0x70ff:
            io.append((m.frame, "r", v))
        return v

    def wr8(a, v):
        if 0x7000 <= a <= 0x70ff:
            io.append((m.frame, "w", v))
        elif a == 0x7100:
            io.append((m.frame, "c", v))
        wr(a, v)
    m.cpus[0].rd8, m.cpus[0].wr8 = rd8, wr8

    while m.frame < FRAMES:
        m.in0, m.in1 = inputs(m.frame)
        m.run_frame()
        f = m.frame
        mcus[(f, "m51")] = mcu_state(m.n51)
        mcus[(f, "m54")] = mcu_state(m.n54)
        if f in DUMPS:
            rams[f] = bytes(m.ram)
    return io, rams, m, mcus


def main():
    out = os.path.join(tempfile.gettempdir(), "galaga_51xx_%s_%d" % (SCRIPT, FRAMES))
    os.makedirs(out, exist_ok=True)
    mio, mrams, dsw, mmcu = run_mame(out)
    print("MAME: %d 06XX accesses, DSW %s" % (len(mio), dsw and "%02x %02x" % dsw))
    rio, rrams, m, rmcu = run_ref(dsw)
    print("reference: %d 06XX accesses" % len(rio))
    n = min(len(mio), len(rio))
    first = next((i for i in range(n) if mio[i][1:] != rio[i][1:]), None)
    if first is None and len(mio) == len(rio):
        print("the access sequences are identical (values and kinds)")
    else:
        i = first if first is not None else n
        print("first difference at access %d of %d / %d:" % (i, len(mio), len(rio)))
        for j in range(max(0, i - 6), min(n, i + 10)):
            print("  %5d  MAME f%-5d %s %02X   ref f%-5d %s %02X%s" % (j, mio[j][0], mio[j][1], mio[j][2], rio[j][0],
                  rio[j][1], rio[j][2], "   <--" if mio[j][1:] != rio[j][1:] else ""))
    # the 51XX's own traffic: the reads and writes while the 06XX selects it (control bit 0); gameplay that diverges
    # (the reference's random numbers are not MAME's) changes the 54XX commands, not this
    def only51(log):
        ctrl, out = 0, []
        for e in log:
            if e[1] == "c":
                ctrl = e[2]
            elif ctrl & 1:
                out.append(e)
        return out
    m51, r51 = only51(mio), only51(rio)
    k = min(len(m51), len(r51))
    d51 = next((i for i in range(k) if m51[i] != r51[i]), None)
    print("51XX traffic: %d / %d accesses, %s" % (len(m51), len(r51), "identical (frames too)" if d51 is None and
          len(m51) == len(r51) else "first difference at %d: MAME %s, ref %s" % (d51 if d51 is not None else k,
          m51[d51] if d51 is not None else "-", r51[d51] if d51 is not None else "-")))
    fd = [i for i in range(n) if mio[i][0] != rio[i][0]]
    print("accesses in a different frame: %d" % len(fd), ("(first at %d: MAME %d, ref %d)" % (fd[0], mio[fd[0]][0], rio[fd[0]][0])) if fd else "")
    for chip in ("m51", "m54"):
        keys = sorted(k for k in mmcu if k[1] == chip and k in rmcu)
        bad = [k[0] for k in keys if mmcu[k] != rmcu[k]]
        print("%s data RAM at the vertical blank: %d of %d frames differ%s" % (chip, len(bad), len(keys),
              (" (first %d: MAME %s, ref %s)" % (bad[0], mmcu[(bad[0], chip)], rmcu[(bad[0], chip)])) if bad else ""))
    for f in DUMPS:
        a, b = mrams[f], rrams.get(f)
        if b is None:
            continue
        d = [i for i in range(0x2000) if a[i] != b[i]]
        print("frame %d: %d RAM bytes differ%s" % (f, len(d), (": " + " ".join("%04X:%02X/%02X" % (0x8000 + i, a[i], b[i]) for i in d[:10])) if d else ""))


if __name__ == "__main__":
    main()
