"""Moon Patrol's sound board: Irem's M52 "Sound C" (MAME 0.286 irem/irem.cpp, m52_soundc_audio_device): the
reference model, the model of the STE's schedule and its YM mix-down.

The board (MAME's device_add_mconfig and m52_small_sound_map):
    an M6803 at 3.579545 MHz (E = / 4: 894,887 cycles a second), expanded mode: $0000-$001F its registers, $0080-$00FF
    its RAM; the external map has global_mask $7FFF: $0000-$0FFF w the MSM5205's nibble (offset bit 0: the board's
    only MSM5205; bit 1 would be a second one, which this board has not), $1000-$1FFF w IRQ acknowledge, $2000-$7FFF
    ROM (`mp-s1.1a`, 4 KB, at $7000; the program runs at its mirror $F000-$FFFF, where the vectors are).
    Port 1 = the AY data bus, port 2 the control (bit 0 the write strobe, its falling edge; bit 2 address (1) / data
    (0); bit 3 AY 45M, bit 4 AY 45L), as Kung-Fu Master's M62 board.  Two AY-3-8910s at 3.579545 / 4 MHz; AY 45M's
    port A reads the command latch, its port B sets the MSM5205's prescaler (bits 2-4: the driver writes $13, S96
    4-bit) and its reset (bit 0); AY 45L's port A (the M62 boards' analog drums) drives nothing on this board.
    IRQ (level): a command with bit 7 0 asserts it; the acknowledge clears it only once the latch has bit 7 set (the
    game writes each command, then the command | $80).  NMI: the MSM5205's VCK (384 kHz / 96 = 4 kHz).
    MAME's discrete mixer ("filtermix") adds the two AYs (each a single output: its three channels tied) and the
    MSM5205's filtered output; the STE has no such filters.

The driver (mp-s1.1a; the same family as Kung-Fu Master's a-3h):
    reset $FB00: clears the RAM ($80-$CE), silences both AYs, port B = $13; the main loop $FB1B: the tick ($C0 > 0:
    one tick off, the four slots' delays $80-$83 and the six volume decay counters $AE-$B3 count), the command
    ($BC < $80: 0 stops all, 1-15 the ADPCM voice of table $F400, $10-$17 an effect into slots 1-3, $18-$1F a tune
    into slot 0 after a reset of everything; then $BC = $FF), the four slots' sequencers (each when its delay is 0),
    the volume decays ($A8-$AD: one volume step down of a channel, to 7 at least), then port B = $D8 | $BE (the
    voice's end resets the MSM5205), and a voice 2 that ended goes on with voice 3 ($BC = 3).  Every AY write waits
    for an NMI ($BD); a voice's start waits for five.
    IRQ $FC8B: acknowledge, $BC = the latch & $1F.  NMI $FBD9: the nibble of the last NMI to the MSM5205 ($C1; $C2
    to the absent second chip), $BD + 1, $BF + 1; odd counts the high nibble of ($C7) (the count $C3 down: at 0
    $BE bit 0, the voice's end), even counts the low nibble and $C7 + 1, and every 16th a tick ($C0 + 1: 250 a
    second).  The voices (table $F400: start, count): 1 $F000 / $400, 2 $F004 / $E0, 3 $F004 / $3FC (the same
    1 KB of ADPCM at $F000-$F3FF, the ROM's first quarter); 4-15 none.  The game sends 0, 1-3 and $10-$1F (the
    coverage seeds: the voices in play from the Beginner course's later points on).

    b = Board(); b.command_at(t, v); b.run(cycles); b.ay_writes -> [(cycle, chip, reg, value)]
"""
from pathlib import Path
import importlib.util
import sys
sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[3] / 'engine')]
from m6801 import I
from paths import EXTRACTED

# Kung-Fu Master's board model (games/kungfum/tools/sound.py): the 6803 core with MAME's cycle table, the AY register
# files, the MSM5205's decoder and the YM mix-down are the same chips at the same clocks
_spec = importlib.util.spec_from_file_location(
    'kungfum_sound', Path(__file__).resolve().parents[2] / 'kungfum' / 'tools' / 'sound.py')
kf = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(kf)
YM, MSM, scale, CYCLES_6803 = kf.YM, kf.MSM, kf.scale, kf.CYCLES_6803

E_HZ = kf.E_HZ                          # 894,887 (MAME's clocks_to_cycles rounds up)
NMI_HZ = 384000 / 96                    # the MSM5205's VCK (S96)
NMI_PERIOD = E_HZ / NMI_HZ              # 223.72 E cycles
MAIN_HZ = 3072000                       # (m52.cpp: Z80 at 18.432 MHz / 6)
FRAME_MAIN = 384 * 282 // 2             # 54,144 main CPU cycles a frame (6.144 MHz pixel clock, 384 x 282)
FRAME_E = FRAME_MAIN * E_HZ / MAIN_HZ   # E cycles in an arcade frame (15,772)
NMI_FIRST = kf.NMI_FIRST                # (the MSM5205's first VCK rise after the reset: its timer starts with the
                                        # machine, as on Kung-Fu Master's board, whose MAME traces fitted it)
ROM_FILE = 'mp-s1.1a'


def rom_image():
    """the 6803's $0000-$7FFF (global_mask $7FFF): the ROM at $7000, $2000-$6FFF zero (MAME's region)"""
    img = bytearray(0x8000)
    d = (EXTRACTED / 'mpatrol' / ROM_FILE).read_bytes()
    img[0x7000:0x7000 + len(d)] = d
    return img


class CPU(kf.CPU):
    """Kung-Fu Master's 6803 (expanded mode, MAME's cycles, NMI) on the M52 small map"""
    def rd(self, a):
        a &= 0xFFFF
        if a < 0x20:
            if a in (0, 1, 4, 5):
                return 0xFF                   # (MAME's m6801_io: the DDRs read $FF)
            return self.rd_reg(a)
        if 0x80 <= a < 0x100:
            return self.ram[a]
        m = a & 0x7FFF
        if m >= 0x2000:
            return self.img[m]
        return 0

    def wr(self, a, v):
        a &= 0xFFFF
        v &= 0xFF
        if a < 0x20:
            self.wr_reg(a, v)
        elif 0x80 <= a < 0x100:
            self.ram[a] = v
        else:
            m = a & 0x7FFF
            if m < 0x1000:
                if m & 1:
                    self.board.adpcm_w(0, v)  # (m & 2: the second MSM5205, not on this board)
            elif m < 0x2000:
                self.board.irq_ack()


class Board(kf.Board):
    """the sound board (Kung-Fu Master's Board on the M52 map and frame); ay_writes: (E cycle, chip 0 = 45M / 1 = 45L,
    register, value), adpcm: (cycle, 0, nibble)"""
    def __init__(self):
        self.ay = [kf.AY(), kf.AY()]
        self.latch = 0
        self.port1 = self.port2 = 0
        self.ay_writes = []
        self.adpcm = []
        self.msm_reset = [True, True]
        self.cpu = CPU(self, rom_image())
        self.cpu.reset()
        self.cpu.irq1 = True                  # (device_reset asserts the IRQ line)
        self.next_vck = NMI_FIRST
        self.vck = False
        self.cmd_event = False
        self.last_sync = 0

    def command_at(self, t, v):
        """a command written by the main CPU at E cycle t (as Kung-Fu Master's: the latch shows from the start of the
        main CPU's timeslice, the IRQ is asserted through a synchronisation at t), on this board's frame"""
        k = int((t - NMI_FIRST) // (NMI_PERIOD / 2))
        s = max(NMI_FIRST + k * NMI_PERIOD / 2, (t // FRAME_E) * FRAME_E, self.last_sync)
        if s > self.cpu.cycles:
            self.run(s - self.cpu.cycles)
        self.latch = v
        if t > self.cpu.cycles:
            self.run(t - self.cpu.cycles)
        if not v & 0x80:
            self.cpu.irq1 = True
            self.cmd_event = True
            self.last_sync = t


# ---- the STE's schedule of the driver (tools/sndgen.py translates it; src/sound.s runs it) ----
# The busy waits are left out (an AY write waits for the next NMI, a voice's start for five) and the loop's write of
# port B each iteration ($FBD1: the MSM5205's reset, no AY sound); the STE runs the main loop's iteration ($FB1B ..
# jmp $FB1B) once per command and once per tick instead of without end.
SKIP = {0xFCF5: 0xFCF9, 0xFF00: 0xFF0C, 0xFBD1: 0xFBD6}
LOOP = 0xFB1B
TICKS_NUM, TICKS_DEN = 141, 32          # 250 ticks a second / 56.7376 arcade frames = 4.40625 ticks a frame


class TickBoard(Board):
    """the driver as the STE runs it: boot(), then per arcade frame frame(commands): each command (bit 7 0) its own
    iteration of the main loop ($BC = command & $1F, $C0 = 0), then the frame's ticks ($C0 = 1, an iteration each)"""
    def __init__(self):
        super().__init__()
        self.acc = 0

    def iteration(self, limit=200000):
        c = self.cpu
        first = True
        for _ in range(limit):
            pc = c.pc
            if pc == LOOP and not first:
                return
            first = False
            if pc in SKIP:
                c.pc = SKIP[pc]
                continue
            c.step1(c.rd(pc))
        raise RuntimeError('the driver did not come back to its main loop (pc %04X)' % c.pc)

    def boot(self):
        c = self.cpu
        while c.pc != LOOP:
            if c.pc in SKIP:
                c.pc = SKIP[c.pc]
                continue
            c.step1(c.rd(c.pc))
        c.irq1 = False
        self.iteration()

    def frame(self, commands):
        ram = self.cpu.ram
        for v in commands:
            if v & 0x80:
                continue
            self.latch = v
            ram[0xBC] = v & 0x1F
            ram[0xC0] = 0
            self.iteration()
        self.acc += TICKS_NUM
        n, self.acc = self.acc // TICKS_DEN, self.acc % TICKS_DEN
        for _ in range(n):
            ram[0xC0] = 1
            self.iteration()


class STEBoard(TickBoard):
    """TickBoard and YM: what src/sound.s does in an arcade frame (returns the frame's YM writes)"""
    def __init__(self):
        super().__init__()
        self.ym = YM()
        self.env_written = [False, False]

    def ay_w(self, chip, v):
        super().ay_w(chip, v)
        if self.ay[chip].addr == 13:
            self.env_written[chip] = True

    def frame(self, commands):
        super().frame(commands)
        w = self.ym.frame([self.ay[0].regs, self.ay[1].regs], self.env_written)
        self.env_written = [False, False]
        return w


# ---- the ADPCM voices ----
VOICE_CMDS = (1, 2, 3)                   # (4-15: count 1 at address 0, nothing to hear)
STOPS = {0} | set(range(0x18, 0x20))     # the commands that reset the MSM5205 (FC98: port B = $13)


def voice_signal(cmd, seconds=3.0):
    """the 4 kHz output (-2048..2047) of the MSM5205 that command `cmd` plays, the command alone on the exact board
    after its boot, from its start until it has been reset for 20 ms (voice 2 goes on with voice 3: one signal)"""
    b = Board()
    b.command_at(FRAME_E * 1.7, 0)
    b.command_at(FRAME_E * 1.7 + 5, 0x80)
    b.run(FRAME_E * 30 - b.cpu.cycles)
    msm = MSM()
    out = []
    started = False
    quiet = 0
    t0 = b.cpu.cycles
    b.command_at(t0 + 10, cmd)
    b.command_at(t0 + 15, cmd | 0x80)
    end = t0 + seconds * E_HZ
    while b.cpu.cycles < end:
        n0 = len(b.adpcm)
        b.run(NMI_PERIOD)
        for c, v, nib in b.adpcm[n0:]:
            reset = b.msm_reset[0]
            s = msm.clock(nib, reset)
            if not reset:
                started = True
                quiet = 0
            elif started:
                quiet += 1
            if started:
                out.append(s)
        if started and quiet >= 80:
            break
    while out and out[-1] == 0:
        out.pop()
    return out


DMA_HZ = kf.DMA_HZ                       # the STE's DMA sound at 6258 Hz, mono, 8 bits signed


def voice_pcm(cmd):
    """the voice as signed bytes at DMA_HZ (the 4 kHz output resampled linearly, -127..127), padded with silence to a
    multiple of 4"""
    s = voice_signal(cmd)
    n = int(len(s) * DMA_HZ / NMI_HZ)
    out = bytearray()
    for i in range(n):
        x = i * NMI_HZ / DMA_HZ
        k = int(x)
        a = s[k] if k < len(s) else 0
        b = s[k + 1] if k + 1 < len(s) else 0
        v = a + (b - a) * (x - k)
        out.append(int(round(max(-127, min(127, v * 127 / 2048)))) & 0xFF)
    while len(out) & 3:
        out.append(0)
    return bytes(out)


def build_voices(build):
    """build/mpatrol/snd_voices.bin and snd_voices.s (snd_vtab: per voice command its offset and length)"""
    data = bytearray()
    tab = []
    for c in VOICE_CMDS:
        p = voice_pcm(c)
        tab.append((len(data), len(p)))
        data += p
    (build / 'snd_voices.bin').write_bytes(bytes(data))
    lines = ['; generated by games/mpatrol/tools/sound.py build_voices (ROM-derived: not in git)', '\tsection data,data',
             '\teven', 'snd_vtab:\t\t\t; commands 1-3: offset, length (bytes at %.1f Hz)' % DMA_HZ]
    for off, n in tab:
        lines.append('\tdc.l\t%d,%d' % (off, n))
    lines += ['snd_voices:\tincbin\t"snd_voices.bin"', '\teven', '\tsection text,code']
    (build / 'snd_voices.s').write_text('\n'.join(lines) + '\n')
    return data, tab


class VoiceMix:
    """src/sound.s snd_voice / snd_mix: one voice, (re)started by commands 1-3, ended by STOPS; mix(n) copies the next
    n bytes (silence 0) into the DMA ring"""
    RING = 2048

    def __init__(self, data, tab):
        self.data, self.tab = data, tab
        self.pos = None
        self.ring = bytearray(self.RING)
        self.wp = 0

    def command(self, c):
        c &= 0x1F
        if c in STOPS:
            self.pos = None
        elif c in VOICE_CMDS:
            off, n = self.tab[c - 1]
            self.pos = [off, off + n]

    def mix(self, n):
        for _ in range(n):
            p = self.pos
            if p and p[0] < p[1]:
                self.ring[self.wp] = self.data[p[0]]
                p[0] += 1
            else:
                self.ring[self.wp] = 0
            self.wp = (self.wp + 1) % self.RING


if __name__ == '__main__':
    for c in VOICE_CMDS:
        s = voice_signal(c)
        print('voice %d: %d samples at 4 kHz (%.2f s), peak %d' % (c, len(s), len(s) / NMI_HZ, max(map(abs, s or [0]))))
