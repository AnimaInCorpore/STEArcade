"""Juno First's sampled sound effects: the i8039 sound CPU's program (jfs2_p4.bin) run in engine/mcs48.py and its DAC
output rendered offline to PCM for the STE's DMA sound.

The board (MAME konami/junofrst.cpp): the i8039 runs at 8 MHz (533 333.3 machine cycles a second), its I/O space reads
give the sound latch 2 (the sound Z80's write to $5000), P1 drives an 8-bit R-2R DAC, a write to P2 with bit 7 clear
clears INT (the Z80's write to $6000 asserts it) and P2 bits 4-6 are the status the Z80 reads in AY port A bits 0-2.
Like Gyruss's: reset sets P1 = 0 and idles at $019 with INT enabled; the INT handler ($01C) reads the latch, clears
INT and plays command & 15 through a jump table; a new command always restarts the effect.

Rendering as games/gyruss/tools/i8039.py (box-averaged DAC step wave at the DMA rate, centred on the idle value, the
loudest command's peak 63, biased by 64).  Besides the DAC, each command's P2 writes (cycle, value) are recorded: the
status the Z80 sees while the effect runs (snd_stat_tab: per command, the status bits and the duration).  Not checked
against MAME's DAC writes (Gyruss's --mame check was against a private MAME 0.289 build).

    python games/junofrst/tools/i8039.py [--rate 12517|6258] [--signed] [--cap 3] [--trace]

writes build/junofrst/snd_dac.bin (all commands 0-15 concatenated), snd_dac.s (snd_dac_tab: offset, length per
command; snd_dac: the incbin) and build/junofrst/dac_<n>.wav previews.
"""
import argparse
import os
import struct
import sys
from collections import Counter

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
sys.path.insert(0, os.path.join(ROOT, 'engine'))
from mcs48 import MCS48, mnemonic  # noqa: E402

ROM = os.path.join(ROOT, 'assets', 'roms', 'extracted', 'junofrst', 'jfs2_p4.bin')
BUILD = os.path.join(ROOT, 'build', 'junofrst')
CPU_HZ = 8000000 / 15                   # MAME's mcs48: clock / 15 machine cycles
RATES = {12517: 8012800 / 640, 6258: 8012800 / 1280}    # the STE's DMA rates (as games/kungfum/tools/sound.py)
CAP = int(3 * CPU_HZ)                   # 3 seconds at most a command
QUIET = int(CPU_HZ / 50)                # idle with the DAC unchanged this long (20 ms) ends a command
COMMANDS = range(16)


class Board:
    """the i8039 with Juno First's I/O; dac = [(cycle, value)] of the P1 writes"""

    def __init__(self, rom):
        self.latch = 0
        self.dac = []
        self.p2_writes = []
        self.cpu = MCS48(rom, port_w=self.port_w, ext_r=lambda a: self.latch, bus_r=lambda: self.latch)
        self.cpu.ops = Counter()

    def port_w(self, n, v):
        cpu = getattr(self, 'cpu', None)
        t = cpu.cycles if cpu else 0
        if n == 1:
            self.dac.append((t, v))
        else:
            self.p2_writes.append((t, v))
            if cpu:
                if not v & 0x80:
                    cpu.set_int(False)      # i8039_irqen_and_status_w: bit 7 clear clears INT

    def idle(self):
        """in the idle loop ($019 nop / $01A jmp $019) with no interrupt pending or in progress"""
        c = self.cpu
        return c.pc in (0x019, 0x01A) and not c.irq_state and not c.irq_in_progress

    def run_until_idle(self, cap, quiet=QUIET):
        """run until idle with the DAC unchanged `quiet` cycles (or `cap` cycles); returns the cycles run"""
        c = self.cpu
        start = c.cycles
        idle_since = None
        while c.cycles - start < cap:
            c.step()
            if self.idle():
                last = self.dac[-1][0] if self.dac else 0
                if idle_since is None:
                    idle_since = max(c.cycles, last)
                if c.cycles - max(idle_since, last) >= quiet:
                    break
            else:
                idle_since = None
        return c.cycles - start


def render(rom, cmd, boot_cycles=None):
    """(start cycle, end cycle, [(cycle, value)] DAC writes from the command on, the DAC value before it, board)"""
    b = Board(rom)
    if boot_cycles is None:
        b.run_until_idle(CAP)
    else:
        b.cpu.run(boot_cycles)
    idle_value = b.dac[-1][1]
    n0 = len(b.dac)
    t0 = b.cpu.cycles
    b.latch = cmd
    b.cpu.set_int(True)                 # i8039_irq_w: ASSERT_LINE
    b.run_until_idle(CAP)
    return t0, b.cpu.cycles, b.dac[n0:], idle_value, b


def trim_end(t0, t1, writes, idle_value):
    """the end of the effect: the last DAC write (the program's own return to idle; a final write of the idle value
    counts as the end), or t1"""
    if not writes:
        return t0
    return writes[-1][0]


def resample(t0, t1, writes, idle_value, rate):
    """the DAC's step wave from t0 to t1 averaged over each output sample, minus idle_value (floats)"""
    n = max(0, int((t1 - t0) / CPU_HZ * rate + 0.999))
    out = [0.0] * n
    step = CPU_HZ / rate                # cycles per output sample
    # segments of constant value
    segs = []
    v = idle_value
    t = t0
    for (tw, vw) in writes:
        if tw > t:
            segs.append((t, tw, v))
            t = tw
        v = vw
    if t1 > t:
        segs.append((t, t1, v))
    for (a, b, v) in segs:
        d = v - idle_value
        if d == 0:
            continue
        x, y = (a - t0) / step, (b - t0) / step
        i = int(x)
        while x < y and i < n:
            e = min(y, i + 1)
            out[i] += d * (e - x)
            x = e
            i += 1
    return out


def wav(path, data, rate, signed):
    """8-bit mono WAV (unsigned: signed bytes + 128, biased bytes: (b - 64) * 2 + 128)"""
    if signed:
        pcm = bytes(((b if b < 128 else b - 256) + 128) & 0xFF for b in data)
    else:
        pcm = bytes(max(0, min(255, (b - 64) * 2 + 128)) for b in data)
    hdr = b'RIFF' + struct.pack('<I', 36 + len(pcm)) + b'WAVEfmt ' + struct.pack('<IHHIIHH', 16, 1, 1, int(rate),
                                                                                 int(rate), 1, 8)
    with open(path, 'wb') as f:
        f.write(hdr + b'data' + struct.pack('<I', len(pcm)) + pcm)


def restart_test(rom, first=5, second=2, after=0.05):
    """a second command while one plays (cmd 5, then cmd 2 50 ms later): (the pc it interrupts, whether the DAC
    writes from then on equal the second command played alone, times and values included, the delay from the
    INT to its first DAC write in cycles)"""
    b = Board(rom)
    b.run_until_idle(CAP)
    b.latch = first
    b.cpu.set_int(True)
    b.cpu.run(int(CPU_HZ * after))
    pc_at = b.cpu.pc
    n0 = len(b.dac)
    t0 = b.cpu.cycles
    b.latch = second
    b.cpu.set_int(True)
    b.run_until_idle(CAP)
    got = [(t - t0, v) for t, v in b.dac[n0:]]
    a0, _, alone, _, _ = render(rom, second)
    alone = [(t - a0, v) for t, v in alone]
    same_values = [v for _, v in got] == [v for _, v in alone]
    return pc_at, same_values, got == alone, got[0][0] if got else None, alone[0][0] if alone else None


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--rate', type=int, default=12517, choices=sorted(RATES))
    ap.add_argument('--signed', action='store_true', help='plain signed bytes, DAC value - idle (no scaling)')
    ap.add_argument('--trace', action='store_true', help='list the instructions the program executes')
    ap.add_argument('--cap', type=float, default=3.0, help='seconds at most a command (cmd 7 runs 6.09 s)')
    args = ap.parse_args()
    global CAP
    CAP = int(args.cap * CPU_HZ)
    rate = RATES[args.rate]
    rom = open(ROM, 'rb').read()
    os.makedirs(BUILD, exist_ok=True)

    ops = Counter()
    pcs = set()
    rendered = []
    busy = []
    for c in COMMANDS:
        t0, t1, writes, idle_value, b = render(rom, c)
        ops.update(b.cpu.ops)
        p2 = [(t, v) for t, v in b.p2_writes if t >= t0]       # the status the Z80 reads (P2 bits 4-6): frames busy
        on = [t for t, v in p2 if v & 0x70]
        off = [t for t, v in p2 if on and t > on[0] and not v & 0x70]
        busy.append(round(((off[0] if off else t1) - t0) / CPU_HZ * 1536000 / 25344) if on else 0)
        end = trim_end(t0, t1, writes, idle_value)
        s = resample(t0, end, writes, idle_value, rate)
        peak = max([abs(x) for x in s] or [0])
        rendered.append((c, s, peak, (end - t0) / CPU_HZ, len(writes), idle_value, (t1 - t0) / CPU_HZ))
    top = max(r[2] for r in rendered) or 1

    data = bytearray()
    tab = []
    print('rate %.1f Hz, %s' % (rate, 'signed (DAC - idle)' if args.signed else
                                 'biased by 64, peak %.1f -> 63' % top))
    for c, s, peak, dur, nw, idle_value, ran in rendered:
        if args.signed:
            p = bytearray((int(round(max(-128, min(127, x)))) & 0xFF) for x in s)
            pad = 0
        else:
            p = bytearray(int(round(max(-63, min(63, x * 63 / top)))) + 64 for x in s)
            pad = 64
        while len(p) & 3:
            p.append(pad)
        tab.append((len(data), len(p)))
        data += p
        wav(os.path.join(BUILD, 'dac_%d.wav' % c), p, rate, args.signed)
        print('cmd %d: %6.3f s, %5d bytes, %6d DAC writes, peak %5.1f (of 255, idle %d), idle again after %.3f s%s'
              % (c, dur, len(p), nw, peak, idle_value, ran, ' (CUT at the cap)' if ran >= CAP / CPU_HZ else ''))

    with open(os.path.join(BUILD, 'snd_dac.bin'), 'wb') as f:
        f.write(bytes(data))
    lines = ['; generated by games/junofrst/tools/i8039.py (ROM-derived: not in git)', '\tsection data,data', '\teven',
             'snd_dac_tab:\t\t\t; commands 0-7: offset, length (bytes at %.1f Hz, %s)'
             % (rate, 'signed' if args.signed else 'biased by 64, silence 64')]
    for off, n in tab:
        lines.append('\tdc.l\t%d,%d' % (off, n))
    lines += ['snd_busy_tab:\t\t\t; frames the i8039 status is set (commands 0-15; sound.py EFFECT_FRAMES)',
              '\tdc.b\t' + ','.join(str(x) for x in busy)]
    lines += ['snd_dac:\tincbin\t"snd_dac.bin"', '\teven', '\tsection text,code']
    with open(os.path.join(BUILD, 'snd_dac.s'), 'w') as f:
        f.write('\n'.join(lines) + '\n')
    print('wrote build/junofrst/snd_dac.bin (%d bytes), snd_dac.s, dac_0..7.wav' % len(data))

    pc_at, same_values, same, lat, lat_alone = restart_test(rom)
    print('restart: cmd 2 sent 50 ms into cmd 5 (at pc $%03X): the DAC writes from then on are %s cmd 2 played '
          'alone (first write %s / %s cycles after INT); cmd 5 does not continue' %
          (pc_at, 'exactly' if same else ('the values of' if same_values else 'NOT'), lat, lat_alone))

    print('opcodes executed: %d kinds' % len(ops))
    if args.trace:
        for op in sorted(ops):
            print('  %02X %-16s %d' % (op, mnemonic(bytes([op, 0]) + bytes(4094), 0)[0], ops[op]))
    else:
        print('  ' + ' '.join('%02X' % op for op in sorted(ops)))


if __name__ == '__main__':
    main()
