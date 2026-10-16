"""Kung-Fu Master's sound board (MAME irem/audio/irem.cpp, m62_audio_device): the reference model.

An M6803 at 3.579545 MHz (E = / 4: 894,886 cycles a second; engine/m6801.py, the 6801 core, in expanded mode here):
    $0000-$001F its registers (port 1 = the AY data bus, port 2 = the control: bit 0 the write strobe (falling edge),
                bit 2 address (1) / data (0), bit 3 selects AY 45M, bit 4 AY 45L), $0080-$00FF its RAM,
    $0800 (mirror $F7FC) w  IRQ acknowledge,  $0801 / $0802 w  the two MSM5205s' nibbles,
    $4000-$FFFF ROM (a-3e at $A000, a-3f at $C000: the ADPCM samples; a-3h at $E000: the program).
IRQ (level): a sound command from the main CPU (bit 7 0) until an acknowledge while the latch has bit 7 set (the game
writes each command, then $80); the command is read from AY 45M's
port A.  NMI: MSM5205 #1's VCK, 384 kHz / 96 = 4 kHz (AY 45M port B bits 2-4 set the prescaler: the driver keeps
S96 4-bit; bits 0 / 1 reset the two MSM5205s).
The driver (a-3h): the IRQ keeps the command ($BC = cmd & $3F); the NMI feeds the two ADPCM voices and counts: $BD
every NMI (the AY write routines wait for it: one register write an NMI), $C0 every 16th (the sequencers' tick,
250 Hz).  The main loop: a command (0 stop all, 1-2 voice 1, 3-15 voice 2, $10-$3F a sequence into one of four slots
$80-$83; $20 and up reset everything first: the tunes), then the four slots' sequencers, then their AY writes.

    b = Board(); b.command(0x2A); b.run(cycles); b.ay_writes -> [(cycle, chip, reg, value)]
"""
from pathlib import Path
import sys
sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[3] / 'engine')]
from m6801 import M6801, I
from paths import EXTRACTED

E_HZ = (3579545 + 3) // 4               # the M6803's E clock: MAME's clocks_to_cycles rounds up (894,887 a second)
NMI_HZ = 384000 / 96                    # MSM5205 #1's VCK (S96)
NMI_PERIOD = E_HZ / NMI_HZ              # 223.72 E cycles
MAIN_HZ = 3072000
FRAME_E = 54528 * E_HZ / MAIN_HZ        # E cycles in an arcade frame (15,884)
# The NMIs: MAME's first comes at E cycle 1156.8605, then every 223.72 (fitted to its debugger traces: the NMIs of the
# first four frames, of frames 700-703 and 1484-1487 all fall in (1156.859, 1156.8623] + k * 894887 / 4000), each taken at the
# first instruction boundary after it (a timeslice starts there)
NMI_FIRST = 1156.862


def rom_image():
    img = bytearray(0x10000)
    for name, a in (('a-3e-.bin', 0xA000), ('a-3f-.bin', 0xC000), ('a-3h-.bin', 0xE000)):
        d = (EXTRACTED / 'kungfum' / name).read_bytes()
        img[a:a + len(d)] = d
    return img


# MAME's m6801_cpu_device::cycles_6803 (m6801.cpp): the cycles of each opcode (engine/m6801.py counts by class;
# the board's timing, the NMI's place among the instructions, needs MAME's)
X_ = 0
CYCLES_6803 = [
    X_, 2, X_, X_, 3, 3, 2, 2, 3, 3, 2, 2, 2, 2, 2, 2,
    2, 2, X_, X_, X_, X_, 2, 2, X_, 2, X_, 2, X_, X_, X_, X_,
    3, 3, 3, 3, 3, 3, 3, 3, 3, 3, 3, 3, 3, 3, 3, 3,
    3, 3, 4, 4, 3, 3, 3, 3, 5, 5, 3, 10, 4, 10, 9, 12,
    2, X_, X_, 2, 2, X_, 2, 2, 2, 2, 2, X_, 2, 2, X_, 2,
    2, X_, X_, 2, 2, X_, 2, 2, 2, 2, 2, X_, 2, 2, X_, 2,
    6, X_, X_, 6, 6, X_, 6, 6, 6, 6, 6, X_, 6, 6, 3, 6,
    6, X_, X_, 6, 6, X_, 6, 6, 6, 6, 6, X_, 6, 6, 3, 6,
    2, 2, 2, 4, 2, 2, 2, 2, 2, 2, 2, 2, 4, 6, 3, 3,
    3, 3, 3, 5, 3, 3, 3, 3, 3, 3, 3, 3, 5, 5, 4, 4,
    4, 4, 4, 6, 4, 4, 4, 4, 4, 4, 4, 4, 6, 6, 5, 5,
    4, 4, 4, 6, 4, 4, 4, 4, 4, 4, 4, 4, 6, 6, 5, 5,
    2, 2, 2, 4, 2, 2, 2, 2, 2, 2, 2, 2, 3, X_, 3, 3,
    3, 3, 3, 5, 3, 3, 3, 3, 3, 3, 3, 3, 4, 4, 4, 4,
    4, 4, 4, 6, 4, 4, 4, 4, 4, 4, 4, 4, 5, 5, 5, 5,
    4, 4, 4, 6, 4, 4, 4, 4, 4, 4, 4, 4, 5, 5, 5, 5]


class CPU(M6801):
    """the 6801 core in expanded mode: the board's memory map, RAM $80-$FF, NMI"""
    def __init__(self, board, rom):
        self.board = board
        self.img = rom
        self.nmi_pending = False
        super().__init__(b'', out_p1=board.p1_w, out_p2=board.p2_w)
        self.in_p1 = board.p1_r

    def rd(self, a):
        a &= 0xFFFF
        if a < 0x20:
            if a in (0, 1, 4, 5):
                return 0xFF                   # (MAME's m6801_io: the DDRs read $FF)
            return self.rd_reg(a)
        if 0x80 <= a < 0x100:
            return self.ram[a]
        if a >= 0x4000:
            return self.img[a]
        return 0

    def wr(self, a, v):
        a &= 0xFFFF
        v &= 0xFF
        if a < 0x20:
            self.wr_reg(a, v)
        elif 0x80 <= a < 0x100:
            self.ram[a] = v
        elif a & 0x0800:
            k = a & 3
            if k == 0:
                self.board.irq_ack()
            elif k < 3:
                self.board.adpcm_w(k - 1, v)

    def step(self):
        op = self.rd(self.pc)
        i_set = self.cc & I
        self.step1(op)
        if op == 0x0E and i_set:              # (MAME's cli: a pending IRQ waits for one more instruction)
            self.step1(self.rd(self.pc))

    def step1(self, op):
        n0 = self.cycles
        super().step()
        d = CYCLES_6803[op] - (self.cycles - n0)
        self.cycles += d
        self.counter = (self.counter + d) & 0xFFFF

    def check_irq(self):
        if self.nmi_pending:
            self.nmi_pending = False
            self.take(0xFFFC)
            return
        super().check_irq()


class AY:
    def __init__(self):
        self.addr = 0
        self.regs = [0] * 16


class Board:
    """the sound board; ay_writes: (E cycle, chip 0 = 45M / 1 = 45L, register, value), adpcm: (cycle, voice, nibble)"""
    def __init__(self):
        self.ay = [AY(), AY()]
        self.latch = 0
        self.port1 = self.port2 = 0
        self.ay_writes = []
        self.adpcm = []
        self.msm_reset = [True, True]
        self.cpu = CPU(self, rom_image())
        self.cpu.reset()
        self.cpu.irq1 = True                  # (device_reset asserts the IRQ line; the driver acknowledges it)
        self.next_vck = NMI_FIRST             # (the first rise; the VCK toggles every half period)
        self.vck = False
        self.cmd_event = False
        self.last_sync = 0

    # ---- the ports ----
    def p1_w(self, v):
        self.port1 = v

    def p2_w(self, v):
        old = self.port2
        if old & 1 and not v & 1:
            if old & 4:
                for chip, bit in ((0, 8), (1, 16)):
                    if old & bit:
                        self.ay[chip].addr = self.port1 & 0x0F
            else:
                for chip, bit in ((0, 8), (1, 16)):
                    if old & bit:
                        self.ay_w(chip, self.port1)
        self.port2 = v

    def p1_r(self):
        if self.port2 & 8:
            return self.ay_r(0)
        if self.port2 & 16:
            return self.ay_r(1)
        return 0xFF

    def ay_w(self, chip, v):
        a = self.ay[chip].addr
        self.ay[chip].regs[a] = v
        self.ay_writes.append((self.cpu.cycles, chip, a, v))
        if chip == 0 and a == 15:
            self.msm_reset = [bool(v & 1), bool(v & 2)]

    def ay_r(self, chip):
        a = self.ay[chip].addr
        if chip == 0 and a == 14:
            return self.latch                 # (port A: the sound command)
        return self.ay[chip].regs[a]

    def irq_ack(self):
        if self.latch & 0x80:                 # (MAME's sound_irq_ack_w: only once the command has bit 7 set)
            self.cpu.irq1 = False

    def adpcm_w(self, voice, v):
        self.adpcm.append((self.cpu.cycles, voice, v & 15))

    # ---- the main CPU's side ----
    def command(self, v):
        self.latch = v
        if not v & 0x80:
            self.cpu.irq1 = True
        self.cmd_event = True

    def command_at(self, t, v):
        """a command written by the main CPU at E cycle t (MAME's timing): the latch is read by the 6803 without a
        synchronisation, so the value shows from the start of the timeslice the main CPU wrote it in (MAME runs the
        main CPU first: the last VCK toggle, frame start or synchronised command before t); a command with bit 7 0
        asserts the IRQ through a synchronisation at t"""
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

    def run(self, cycles):
        """runs the CPU for `cycles` E cycles more.  MAME's m6800 core looks at its interrupt lines only when a
        timeslice starts (a timer fired: here the MSM5205's VCK toggles every half period, the command's
        synchronisation) and inside CLI (after one more instruction if I was set) and RTI; a line changed by a timer
        is seen from the next slice on, and at least one instruction runs after an interrupt's entry before the
        next look."""
        c = self.cpu
        end = c.cycles + cycles
        while c.cycles < end:
            fired = self.cmd_event
            self.cmd_event = False
            while c.cycles >= self.next_vck:
                self.next_vck += NMI_PERIOD / 2
                self.vck = not self.vck
                if self.vck:
                    c.nmi_pending = True      # (the rising edge)
                fired = True
            if fired:
                c.check_irq()
            op = c.rd(c.pc)
            i_set = c.cc & I
            c.step1(op)
            if op == 0x0E:                    # CLI
                if i_set:
                    c.step1(c.rd(c.pc))
                c.check_irq()
            elif op == 0x3B:                  # RTI
                c.check_irq()


# ---- the STE's schedule of the driver (tools/sndgen.py translates it; src/sound.s runs it) ----
# The busy waits are left out: an AY write waits for the next NMI ($BD) and a voice's start for five; the STE runs the
# main loop's iteration (F922 .. jmp F922) once per command and once per tick instead of once per NMI.
SKIP = {0xFAF2: 0xFAF6, 0xFCE9: 0xFCF3, 0xFD1E: 0xFD28,
        0xF9C4: 0xF9D1}                 # (and the loop's write of 45M's port B: the MSM5205s' reset bits, no AY sound)
LOOP = 0xF922
TICKS_NUM, TICKS_DEN = 71, 16           # 250 ticks a second / 56.34 arcade frames = 4.4375 ticks a frame


class TickBoard(Board):
    """the driver as the STE runs it: boot(), then per arcade frame frame(commands): each command (bit 7 0) as its
    own iteration of the main loop ($BC = command & $3F), then the frame's ticks ($C0 = 1, an iteration each)"""
    def __init__(self):
        super().__init__()
        self.acc = 0
        self.iterations = 0

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
            op = c.rd(pc)
            c.step1(op)
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
            ram[0xBC] = v & 0x3F
            ram[0xC0] = 0
            self.iteration()
        self.acc += TICKS_NUM
        n, self.acc = self.acc // TICKS_DEN, self.acc % TICKS_DEN
        for _ in range(n):
            ram[0xC0] = 1
            self.iteration()


def scale(p):
    """an AY period at 894,886 Hz -> the YM2149's at 2 MHz (src/sound.s snd_scale)"""
    p &= 0xFFFF
    return 2 * p + ((p * 15396) >> 16)


class YM:
    """src/sound.s snd_ym: the YM2149's registers from the two AYs each arcade frame; writes: [(reg, value)]"""
    def __init__(self):
        self.ch = [-1, -1, -1]
        self.cache = [0xFF] * 16

    def frame(self, ay, env_written):
        regs = [ay[0][:16], ay[1][:16]]
        score = []
        for c in range(6):
            chip, v = divmod(c, 3)
            r = regs[chip]
            vol = r[8 + v] & 0x1F
            s = -1
            if vol and (not r[7] >> v & 1 or not r[7] >> (v + 3) & 1):
                s = 15 if vol & 16 else vol
            score.append(s)
        pick = []
        for _ in range(3):
            best, bc = -1, -1
            for c in range(6):
                if score[c] > best:
                    best, bc = score[c], c
            pick.append(bc)
            if bc >= 0:
                score[bc] = -2
        new = [-1, -1, -1]
        for i, c in enumerate(pick):
            if c >= 0:
                for k in (2, 1, 0):
                    if self.ch[k] == c:
                        new[k] = c
                        pick[i] = -1
        for c in pick:
            if c >= 0:
                k = new.index(-1)
                new[k] = c
        self.ch = new
        out = [0] * 16
        mixer = 0x3F
        noise = env = -1
        for k in range(3):
            c = new[k]
            if c < 0:
                continue
            chip, v = divmod(c, 3)
            r = regs[chip]
            p = min(scale((r[2 * v] | r[2 * v + 1] << 8) & 0x0FFF), 0x0FFF)
            out[2 * k], out[2 * k + 1] = p & 0xFF, p >> 8
            vol = r[8 + v] & 0x1F
            out[8 + k] = vol
            if vol & 16 and env < 0:
                env = chip
            if not r[7] >> v & 1:
                mixer &= ~(1 << k)
            if not r[7] >> (v + 3) & 1:
                mixer &= ~(8 << k)
                if noise < 0:
                    noise = chip
        out[7] = mixer | 0xC0
        if noise >= 0:
            out[6] = min(scale(regs[noise][6] & 0x1F), 31)
        if env >= 0:
            p = min(scale(regs[env][11] | regs[env][12] << 8), 0xFFFF)
            out[11], out[12] = p & 0xFF, p >> 8
            out[13] = regs[env][13]
        writes = []
        for r in range(14):
            if r == 13:
                if env >= 0 and env_written[env]:
                    self.cache[13] = out[13]
                    writes.append((13, out[13]))
                continue
            if out[r] != self.cache[r]:
                self.cache[r] = out[r]
                writes.append((r, out[r]))
        return writes


class STEBoard(TickBoard):
    """TickBoard and YM: what src/sound.s does in an arcade frame (the YM writes of each frame in ym_log)"""
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


# ---- the ADPCM voices (MSM5205, MAME msm5205.cpp) ----
def _diff_table():
    nbl2bit = [[1 if n < 8 else -1, (n >> 2) & 1, (n >> 1) & 1, n & 1] for n in range(16)]
    t = []
    for step in range(49):
        sv = int(16.0 * pow(11.0 / 10.0, step))
        for n in range(16):
            b = nbl2bit[n]
            t.append(b[0] * (sv * b[1] + sv // 2 * b[2] + sv // 4 * b[3] + sv // 8))
    return t


DIFF = _diff_table()
INDEX_SHIFT = [-1, -1, -1, -1, 2, 4, 6, 8]


class MSM:
    def __init__(self):
        self.signal = 0
        self.step = 0

    def clock(self, nibble, reset):
        if reset:
            self.signal, self.step = 0, 0
        else:
            s = self.signal + DIFF[self.step * 16 + (nibble & 15)]
            self.signal = max(-2048, min(2047, s))
            self.step = max(0, min(48, self.step + INDEX_SHIFT[nibble & 7]))
        return self.signal


def voice_signal(cmd, seconds=4.0):
    """the 4 kHz output (-2048..2047) of the MSM5205 that command `cmd` (1-15) plays, the command alone on the exact
    board after its boot, until the voice is reset again (the driver's end: $BE bits -> port B)"""
    b = Board()
    b.command_at(FRAME_E * 1.7, 0)
    b.command_at(FRAME_E * 1.7 + 5, 0x80)
    b.run(FRAME_E * 30 - b.cpu.cycles)
    voice = 0 if cmd < 3 else 1
    msm = MSM()
    out = []
    started = False
    b.adpcm = []
    t0 = b.cpu.cycles
    b.command_at(t0 + 10, cmd)
    b.command_at(t0 + 15, cmd | 0x80)
    end = t0 + seconds * E_HZ
    reset_log = []
    old_w = b.ay_w

    def ay_w(chip, v):
        old_w(chip, v)
        if chip == 0 and b.ay[0].addr == 15:
            reset_log.append((b.cpu.cycles, bool(v >> voice & 1)))
    b.ay_w = ay_w
    while b.cpu.cycles < end:
        n0 = len(b.adpcm)
        b.run(NMI_PERIOD)
        for c, v, nib in b.adpcm[n0:]:
            if v != voice:
                continue
            reset = b.msm_reset[voice]
            s = msm.clock(nib, reset)
            if not reset:
                started = True
            if started:
                out.append(s)
        if started and b.msm_reset[voice]:
            break
    while out and out[-1] == 0:
        out.pop()
    return out


def voices_exact(board, seconds):
    """runs the exact board `seconds` more, decoding both MSM5205s' 4 kHz output: [[signal] * NMIs] x 2"""
    msm = [MSM(), MSM()]
    out = [[], []]
    end = board.cpu.cycles + seconds * E_HZ
    while board.cpu.cycles < end:
        n0 = len(board.adpcm)
        board.run(NMI_PERIOD)
        for c, v, nib in board.adpcm[n0:]:
            out[v].append(msm[v].clock(nib, board.msm_reset[v]))
    return out


DMA_HZ = 8012800 / 1280                  # the STE's DMA sound at its lowest rate (6258 Hz), mono, 8 bits signed
VOICE_CMDS = range(1, 8)                 # the commands with a sample (8-15 have none)
STOPS = {0} | set(range(0x20, 0x40)) - {0x24}      # the commands that end both voices (FA93 clears their pointers)


def voice_pcm(cmd):
    """the voice of a command as bytes for the mixer: the MSM5205's 4 kHz output resampled (linear) to DMA_HZ, scaled
    to -63..63 and biased by 64 (1..127: two add without a carry out of the byte, snd_mix adds them as longs),
    padded with silence (64) to a multiple of 4"""
    s = voice_signal(cmd)
    n = int(len(s) * DMA_HZ / NMI_HZ)
    out = bytearray()
    for i in range(n):
        x = i * NMI_HZ / DMA_HZ
        k = int(x)
        a = s[k] if k < len(s) else 0
        b = s[k + 1] if k + 1 < len(s) else 0
        v = a + (b - a) * (x - k)
        out.append(int(round(max(-63, min(63, v * 63 / 2048)))) + 64)
    while len(out) & 3:
        out.append(64)
    return bytes(out)


def build_voices(build):
    """build/kungfum/snd_voices.bin and snd_voices.s (snd_vtab: per command 1-7 its offset and length)"""
    data = bytearray()
    tab = []
    for c in VOICE_CMDS:
        p = voice_pcm(c)
        tab.append((len(data), len(p)))
        data += p
    (build / 'snd_voices.bin').write_bytes(bytes(data))
    lines = ['; generated by games/kungfum/tools/sound.py build_voices (ROM-derived: not in git)', '\tsection data,data',
             '\teven', 'snd_vtab:\t\t\t; commands 1-7: offset, length (bytes at %.1f Hz)' % DMA_HZ]
    for off, n in tab:
        lines.append('\tdc.l\t%d,%d' % (off, n))
    lines += ['snd_voices:\tincbin\t"snd_voices.bin"', '\teven', '\tsection text,code']
    (build / 'snd_voices.s').write_text('\n'.join(lines) + '\n')
    return data, tab


class VoiceMix:
    """src/sound.s snd_voice / snd_mix: two voices (1-2: voice 1, 3-7: voice 2), each restarted by its commands and
    ended by STOPS; mix(n) (n a multiple of 4) adds the two (biased bytes, silence 64) into the next n bytes of the DMA
    ring: (a + b) ^ $80 is the signed a + b - 128"""
    RING = 2048

    def __init__(self, data, tab):
        self.data, self.tab = data, tab
        self.pos = [None, None]                 # (offset, end) of each voice
        self.ring = bytearray(self.RING)
        self.wp = 0

    def command(self, c):
        c &= 0x3F
        if c in STOPS:
            self.pos = [None, None]
        elif c in VOICE_CMDS:
            off, n = self.tab[c - 1]
            self.pos[0 if c < 3 else 1] = [off, off + n]

    def mix(self, n):
        for _ in range(n):
            v = 0
            for p in self.pos:
                if p and p[0] < p[1]:
                    v += self.data[p[0]]
                    p[0] += 1
                else:
                    v += 64
            self.ring[self.wp] = (v ^ 0x80) & 0xFF
            self.wp = (self.wp + 1) % self.RING
