"""Gyruss's sampled sound effects: the i8039 sound CPU's program (gyrussk.3a) run in engine/mcs48.py and its DAC
output rendered offline to PCM for the STE's DMA sound.

The board (MAME konami/gyruss.cpp): the i8039 runs at 8 MHz (533 333.3 machine cycles a second), its I/O space reads
give the sound latch 2 (the sound Z80's `out ($18),a`), P1 drives an 8-bit DAC (left channel only), a write to P2
clears INT, the Z80's `out ($14),a` asserts it.  The program: reset sets P1 = 0 and idles in a loop at $019 with INT
enabled.  The INT handler ($01C) reads the latch, clears INT, rewrites the stack so that its RETR "returns" to the
command dispatch at $016 (whatever was playing is abandoned) and plays command & 15 through a jump table: 0 and 8-15
write 0 to the DAC (silence), 1-7 play an effect computed from tables and the free-running timer (MOV A,T as the
noise source), then return to the idle loop.  So a new command always restarts: the effect playing stops at once and
the new one starts from its beginning; there is one DAC voice, effects never overlap (the AY music is separate).

Rendering: per command boot the CPU from reset, run until idle, set the latch and assert INT (the program's P2
write clears it), record every P1 write with its cycle time until the program idles again with the DAC unchanged
(cap 3 s), then box-average the DAC's step wave into each output sample (DMA rate 12517 Hz, or 6258 with --rate
6258), centred on the idle value (0: the DAC's output is positive only), scaled so the loudest command's peak is 63
and biased by 64 (1..127, silence 64: the format of games/kungfum/tools/sound.py voice_pcm, which snd_mix adds as
longs) and padded with silence to a multiple of 4.  --signed writes plain signed bytes instead (scale 1: DAC value
- idle, 0..127 here).  The timer's value at the command decides the noise; it is free-running from reset, so the
rendering takes the boot idle time the program has after reset (one fixed choice; the noise differs on the board).

    venv/bin/python games/gyruss/tools/i8039.py [--rate 12517|6258] [--signed] [--cap 3] [--trace]
    venv/bin/python games/gyruss/tools/i8039.py --mame

--mame checks the interpreter against MAME 0.289: commands 1-7 sent by Lua (latch, then INT a frame later) with the
sound Z80's own INT writes patched out, every DAC write logged by debugger breakpoints with the i8039's cycle count,
then the same INT times replayed here: all 32 858 writes equal in cycle and value (2026-10-17), the timer noise of
commands 4-6 included.  MAME's analog path after the DAC (the mixer's 8 kHz RC low-pass and its DC removal, left
channel only) is not modelled.

writes build/gyruss/snd_dac.bin (all commands 0-7 concatenated), build/gyruss/snd_dac.s (snd_dac_tab: offset, length
per command; snd_dac: the incbin) and build/gyruss/dac_<n>.wav previews (the same bytes as 8-bit WAV at the rate).
"""
import argparse
import os
import struct
import sys
from collections import Counter

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
sys.path.insert(0, os.path.join(ROOT, 'engine'))
from mcs48 import MCS48, mnemonic  # noqa: E402

ROM = os.path.join(ROOT, 'assets', 'roms', 'extracted', 'gyruss', 'gyrussk.3a')
BUILD = os.path.join(ROOT, 'build', 'gyruss')
CPU_HZ = 8000000 / 15                   # MAME's mcs48: clock / 15 machine cycles
RATES = {12517: 8012800 / 640, 6258: 8012800 / 1280}    # the STE's DMA rates (as games/kungfum/tools/sound.py)
CAP = int(3 * CPU_HZ)                   # 3 seconds at most a command
QUIET = int(CPU_HZ / 50)                # idle with the DAC unchanged this long (20 ms) ends a command
COMMANDS = range(8)


class Board:
    """the i8039 with the Gyruss board's I/O; dac = [(cycle, value)] of the P1 writes"""

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
                cpu.set_int(False)          # irq_clear_w: any P2 write clears INT

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


MAME_LUA = r"""
-- the Gyruss i8039's DAC writes (its outl p1,a sites) and INT handler entries ($01D: A = the command) logged by
-- debugger breakpoints; the sound Z80's own `out ($14),a` ($000A, $036B) are patched to nops, the commands are
-- written from here: latch at frame START + GAP*k, INT one frame later
local m = manager.machine
local snd = m.devices[':audiocpu']
local dbg = assert(m.devices[':audio2'].debug)
local rgn = m.memory.regions[':audiocpu']
for _, a in ipairs({0x000A, 0x000B, 0x036B, 0x036C}) do rgn:write_u8(a, 0) end
local cmds = {1, 2, 3, 4, 5, 6, 7}
local START, GAP = 120, 450
local frame, flushed, stopbp = 0, 0, nil
local out = io.open('dac_mame.txt', 'w')
local function flush()
  local log = m.debugger.consolelog
  for i = flushed + 1, #log do out:write(log[i], '\n') end
  flushed = #log
end
emu.register_frame_done(function()
  frame = frame + 1
  if frame == 60 then
    stopbp = dbg:bpset(0x019, '1', '')    -- one stop on the i8039 makes it the console's visible CPU (the
  elseif frame == 61 then                 -- printf actions below evaluate their symbols in that CPU)
    dbg:bpclear(stopbp)
    for _, a in ipairs({0x00C, 0x07F, 0x196, 0x1A5, 0x311, 0x34D}) do
      dbg:bpset(a, '1', 'printf "W %d %d",totalcycles,a; g')
    end
    dbg:bpset(0x01D, '1', 'printf "I %d %d",totalcycles,a; g')
  end
  local k = (frame - START) // GAP + 1
  if frame >= START and cmds[k] then
    if (frame - START) % GAP == 0 then snd.spaces['io']:write_u8(0x18, cmds[k])
    elseif (frame - START) % GAP == 1 then snd.spaces['io']:write_u8(0x14, 0) end
  end
  if frame % 30 == 0 then flush() end
  if frame == START + GAP * #cmds then flush(); out:close(); m:exit() end
end)
m.debugger.execution_state = 'run'
"""


def mame_check(rom):
    """run MAME 0.289 (gyruss, -debug with no debugger UI) sending commands 1-7 7.5 s apart, log every DAC write with
    the i8039's cycle count, replay the same INT times here and compare every write (cycle and value)"""
    import subprocess
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        lua = os.path.join(tmp, 'dac.lua')
        with open(lua, 'w') as f:
            f.write(MAME_LUA)
        subprocess.run(['/opt/homebrew/bin/mame', 'gyruss', '-rompath', os.path.join(ROOT, 'assets', 'roms'), '-window',
                        '-video', 'none', '-sound', 'none', '-nothrottle', '-skip_gameinfo', '-debug', '-debugger',
                        'none', '-autoboot_delay', '0', '-autoboot_script', lua, '-seconds_to_run', '250'],
                       cwd=tmp, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
        ev = []
        for line in open(os.path.join(tmp, 'dac_mame.txt')):
            p = line.split()
            if len(p) == 3 and p[0] in 'WI' and p[1].isdigit():
                ev.append((p[0], int(p[1]), int(p[2])))
    ints = [(t, v) for k, t, v in ev if k == 'I']
    mw = [(t + 2, v) for k, t, v in ev if k == 'W']     # the breakpoint is before outl's 2 cycles
    b = Board(rom)
    c = b.cpu
    for ti, cmd in ints:
        # INT taken at an instruction boundary, then 2 (taking it) + 2 (jmp $01C) + 2 (movx) cycles to $01D
        while c.cycles + (1 if rom[c.pc] == 0 else 2) <= ti - 6:
            c.step()
        b.latch = cmd
        c.set_int(True)
        while c.pc != 0x01D:
            c.step()
        if c.cycles != ti:
            print('cmd %d: INT handler at %d here, %d in MAME' % (cmd, c.cycles, ti))
    while mw and c.cycles < mw[-1][0] + 1000:
        c.step()
    mine = [(t, v) for t, v in b.dac if t >= ints[0][0]] if ints else []
    bad = 0
    for k, (ti, cmd) in enumerate(ints):
        te = ints[k + 1][0] if k + 1 < len(ints) else 1 << 62
        a = [x for x in mw if ti <= x[0] < te]
        m = [x for x in mine if ti <= x[0] < te]
        nd = sum(1 for x, y in zip(a, m) if x != y) + abs(len(a) - len(m))
        bad += nd
        print('cmd %d: MAME %5d DAC writes over %.3f s, here %5d, %d differ (cycle or value)'
              % (cmd, len(a), (a[-1][0] - ti) / CPU_HZ if a else 0, len(m), nd))
    print('MAME check: %s (%d commands, %d DAC writes)' % ('EXACT' if ints and not bad else 'DIFFERENT', len(ints),
                                                         len(mw)))
    return not bad and bool(ints)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--rate', type=int, default=12517, choices=sorted(RATES))
    ap.add_argument('--signed', action='store_true', help='plain signed bytes, DAC value - idle (no scaling)')
    ap.add_argument('--trace', action='store_true', help='list the instructions the program executes')
    ap.add_argument('--cap', type=float, default=3.0, help='seconds at most a command (cmd 7 runs 6.09 s)')
    ap.add_argument('--mame', action='store_true', help='compare every DAC write with MAME 0.289 (about 30 s)')
    args = ap.parse_args()
    if args.mame:
        sys.exit(0 if mame_check(open(ROM, 'rb').read()) else 1)
    global CAP
    CAP = int(args.cap * CPU_HZ)
    rate = RATES[args.rate]
    rom = open(ROM, 'rb').read()
    os.makedirs(BUILD, exist_ok=True)

    ops = Counter()
    pcs = set()
    rendered = []
    for c in COMMANDS:
        t0, t1, writes, idle_value, b = render(rom, c)
        ops.update(b.cpu.ops)
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
    lines = ['; generated by games/gyruss/tools/i8039.py (ROM-derived: not in git)', '\tsection data,data', '\teven',
             'snd_dac_tab:\t\t\t; commands 0-7: offset, length (bytes at %.1f Hz, %s)'
             % (rate, 'signed' if args.signed else 'biased by 64, silence 64')]
    for off, n in tab:
        lines.append('\tdc.l\t%d,%d' % (off, n))
    lines += ['snd_dac:\tincbin\t"snd_dac.bin"', '\teven', '\tsection text,code']
    with open(os.path.join(BUILD, 'snd_dac.s'), 'w') as f:
        f.write('\n'.join(lines) + '\n')
    print('wrote build/gyruss/snd_dac.bin (%d bytes), snd_dac.s, dac_0..7.wav' % len(data))

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
