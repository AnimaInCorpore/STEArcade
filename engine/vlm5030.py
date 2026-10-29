"""The Sanyo VLM5030 speech chip after MAME 0.286 src/devices/sound/vlm5030.cpp (BSD-3-Clause, copyright-holder
Tatsuyuki Satoh) and its coefficients (tms5110r.hxx vlm5030_coeff): the pins (data_w, st_w, rst_w, bsy_r) and the
stream, one sample per 440 chip clocks (3.579545 MHz: 8135.3 a second).

MAME's integer arithmetic is kept (C division truncates toward zero: cdiv); the unvoiced excitation uses
machine().rand() & 1 in MAME, a fixed LFSR here (the noise's timbre, not its timing).  BSY is updated when the stream
is: render(n) advances n samples (MAME renders at bsy_r, st_w and rst_w; the board calls render up to the instant).

    v = VLM5030(rom); v.data_w(x); v.st_w(1); v.st_w(0); samples = v.render(n)   # ints in -512..511
    phrase(rom, data, param=0) -> (samples, busy): the phrase's samples and how many samples BSY stays high after ST
    goes low (the start).
"""

FR_SIZE = 4
IP_SIZE_SLOWER, IP_SIZE_SLOW, IP_SIZE_NORMAL, IP_SIZE_FAST, IP_SIZE_FASTER = 240 // 4, 200 // 4, 160 // 4, 120 // 4, 80 // 4
SPEED = (IP_SIZE_NORMAL, IP_SIZE_FAST, IP_SIZE_FASTER, IP_SIZE_FASTER, IP_SIZE_NORMAL, IP_SIZE_SLOWER, IP_SIZE_SLOW,
         IP_SIZE_SLOW)
PH_RESET, PH_IDLE, PH_SETUP, PH_WAIT, PH_RUN, PH_STOP, PH_END = range(7)
CLOCK = 3579545
RATE = CLOCK / 440

ENERGY = (0, 1, 2, 3, 5, 6, 7, 9, 11, 13, 15, 17, 19, 22, 24, 27, 31, 34, 38, 42, 47, 51, 57, 62, 68, 75, 82, 89, 98,
          107, 116, 127)
PITCH = (0, 21, 22, 23, 24, 25, 26, 27, 28, 29, 31, 33, 35, 37, 39, 41, 43, 45, 49, 53, 57, 61, 65, 69, 73, 77, 85, 93,
         101, 109, 117, 125)
_K5 = (0, 128, 256, 384, -512, -384, -256, -128)
_K3 = (0, 64, 128, 192, 256, 320, 384, 448, -512, -448, -384, -320, -256, -192, -128, -64)
KTABLE = (
    (390, 403, 414, 425, 434, 443, 450, 457, 463, 469, 474, 478, 482, 485, 488, 491, 494, 496, 498, 499, 501, 502, 503,
     504, 505, 506, 507, 507, 508, 508, 509, 509, -390, -376, -360, -344, -325, -305, -284, -261, -237, -211, -183,
     -155, -125, -95, -64, -32, 0, 32, 64, 95, 125, 155, 183, 211, 237, 261, 284, 305, 325, 344, 360, 376),
    (0, 50, 100, 149, 196, 241, 284, 325, 362, 396, 426, 452, 473, 490, 502, 510, 0, -510, -502, -490, -473, -452, -426,
     -396, -362, -325, -284, -241, -196, -149, -100, -50),
    _K3, _K3, _K5, _K5, _K5, _K5, _K5, _K5)
KBITS = (6, 5, 4, 4, 3, 3, 3, 3, 3, 3)
KSTART = (42, 37, 33, 29, 26, 23, 20, 17, 14, 11)    # (the first bit of K1 .. K10 in a frame)


def cdiv(a, b):
    q = abs(a) // abs(b)
    return q if (a < 0) == (b < 0) else -q


class VLM5030:
    def __init__(self, rom):
        self.rom = bytes(rom)
        self.mask = len(self.rom) - 1 if len(self.rom) & (len(self.rom) - 1) == 0 else None
        self.pin_RST = self.pin_ST = self.pin_VCU = 0
        self.latch_data = 0
        self.rand = 0x1FFFF
        self.reset()
        self.phase = PH_IDLE

    def read_byte(self, a):
        a &= 0xFFFF
        if self.mask is not None:
            return self.rom[a & self.mask]
        return self.rom[a] if a < len(self.rom) else 0

    def reset(self):
        self.phase = PH_RESET
        self.address = 0
        self.vcu_addr_h = 0
        self.pin_BSY = 0
        self.old_energy = self.old_pitch = 0
        self.new_energy = self.new_pitch = 0
        self.current_energy = self.current_pitch = 0
        self.target_energy = self.target_pitch = 0
        self.old_k = [0] * 10
        self.new_k = [0] * 10
        self.current_k = [0] * 10
        self.target_k = [0] * 10
        self.interp_count = self.sample_count = self.pitch_count = 0
        self.x = [0] * 10
        self.setup_parameter(0)

    def get_bits(self, sbit, bits):
        off = self.address + (sbit >> 3)
        d = self.read_byte(off) | self.read_byte(off + 1) << 8
        return (d >> (sbit & 7)) & (0xFF >> (8 - bits))

    def parse_frame(self):
        self.old_energy, self.old_pitch, self.old_k = self.new_energy, self.new_pitch, list(self.new_k)
        cmd = self.read_byte(self.address)
        if cmd & 1:
            self.new_energy = self.new_pitch = 0
            self.new_k = [0] * 10
            self.address = (self.address + 1) & 0xFFFF
            if cmd & 2:
                return 0
            return ((cmd >> 2) + 1) * 2 * FR_SIZE
        p = PITCH[self.get_bits(1, 5)]
        if p > 0:
            p = (p + self.pitch_offset) & 0xFF          # (uint8_t)
        self.new_pitch = p
        self.new_energy = ENERGY[self.get_bits(6, 5)]
        self.new_k = [KTABLE[i][self.get_bits(KSTART[i], KBITS[i])] for i in range(10)]
        self.address = (self.address + 6) & 0xFFFF
        return FR_SIZE

    def setup_parameter(self, param):
        self.parameter = param
        self.interp_step = 4 if param & 2 else 2 if param & 1 else 1
        self.frame_size = SPEED[(param >> 3) & 7]
        self.pitch_offset = -8 if param & 0x80 else 8 if param & 0x40 else 0

    def bsy_r(self):
        return self.pin_BSY

    def data_w(self, v):
        self.latch_data = v & 0xFF

    def rst_w(self, state):
        state = 1 if state else 0
        if self.pin_RST != state:
            self.pin_RST = state
            if not state:
                self.setup_parameter(self.latch_data)
            elif self.pin_BSY:
                self.reset()

    def vcu_w(self, state):
        self.pin_VCU = 1 if state else 0

    def st_w(self, state):
        state = 1 if state else 0
        if self.pin_ST == state:
            return
        self.pin_ST = state
        if not state:
            if self.pin_VCU:
                self.vcu_addr_h = (self.latch_data << 8) + 1
            else:
                if self.vcu_addr_h:
                    self.address = (self.vcu_addr_h & 0xFF00) + self.latch_data
                    self.vcu_addr_h = 0
                else:
                    table = (self.latch_data & 0xFE) + ((self.latch_data & 1) << 8)
                    self.address = self.read_byte(table) << 8 | self.read_byte(table + 1)
                self.sample_count = self.frame_size
                self.interp_count = FR_SIZE
                self.phase = PH_RUN
        else:
            self.phase = PH_SETUP
            self.sample_count = 1
            self.pin_BSY = 1

    def noise(self):
        b = (self.rand ^ (self.rand >> 3)) & 1
        self.rand = (self.rand >> 1) | (b << 16)
        return b

    def render(self, n):
        """n samples (ints, u[0] clamped to -512..511 as put_int_clamp(.., 512)); the phase and BSY advanced"""
        out = []
        stop = False
        if self.phase in (PH_RUN, PH_STOP):
            for _ in range(n):
                if self.sample_count == 0:
                    if self.phase == PH_STOP:
                        self.phase = PH_END
                        self.sample_count = 1
                        stop = True
                        break
                    self.sample_count = self.frame_size
                    if self.interp_count == 0:
                        self.interp_count = self.parse_frame()
                        if self.interp_count == 0:
                            self.interp_count = FR_SIZE
                            self.sample_count = self.frame_size
                            self.phase = PH_STOP
                        self.current_energy = self.old_energy
                        self.current_pitch = self.old_pitch
                        self.current_k = list(self.old_k)
                        if self.current_energy == 0:
                            self.target_energy = 0
                            self.target_pitch = self.current_pitch
                            self.target_k = list(self.current_k)
                        else:
                            self.target_energy = self.new_energy
                            self.target_pitch = self.new_pitch
                            self.target_k = list(self.new_k)
                    self.interp_count = (self.interp_count - self.interp_step) & 0xFF
                    e = FR_SIZE - self.interp_count % FR_SIZE
                    self.current_energy = self.old_energy + cdiv((self.target_energy - self.old_energy) * e, FR_SIZE)
                    if self.old_pitch > 1:
                        self.current_pitch = self.old_pitch + cdiv((self.target_pitch - self.old_pitch) * e, FR_SIZE)
                    self.current_k = [self.old_k[i] + cdiv((self.target_k[i] - self.old_k[i]) * e, FR_SIZE)
                                      for i in range(10)]
                if self.old_energy == 0:
                    val = 0
                elif self.old_pitch <= 1:
                    val = self.current_energy if self.noise() else -self.current_energy
                else:
                    val = self.current_energy if self.pitch_count == 0 else 0
                u = [0] * 11
                u[10] = val
                k, x = self.current_k, self.x
                for i in range(9, -1, -1):
                    u[i] = u[i + 1] - cdiv(-k[i] * x[i], 512)
                for i in range(9, 0, -1):
                    x[i] = x[i - 1] + cdiv(-k[i - 1] * u[i - 1], 512)
                x[0] = u[0]
                out.append(max(-512, min(511, u[0])))
                self.sample_count -= 1
                self.pitch_count = (self.pitch_count + 1) & 0xFF
                if self.pitch_count >= self.current_pitch:
                    self.pitch_count = 0
        rest = n - len(out)
        if stop:
            out += [0] * rest               # (MAME: the stream's remaining samples of this update stay 0)
        if self.phase == PH_SETUP:
            if self.sample_count <= n:
                self.sample_count = 0
                self.phase = PH_WAIT
            else:
                self.sample_count -= n
        elif self.phase == PH_END:
            if self.sample_count <= n:
                self.sample_count = 0
                self.pin_BSY = 0
                self.phase = PH_IDLE
            else:
                self.sample_count -= n
        return out + [0] * (n - len(out))


def phrase(rom, data, param=0, limit=200000):
    """the phrase the indirect table's entry `data` starts: (samples rendered one at a time until BSY falls, the
    number of samples BSY stays high after ST falls)"""
    v = VLM5030(rom)
    v.data_w(param)
    v.rst_w(1)
    v.rst_w(0)
    v.data_w(data)
    v.st_w(1)
    v.render(1)
    v.st_w(0)
    out = []
    while v.bsy_r() and len(out) < limit:
        out += v.render(1)
    return out, len(out)
