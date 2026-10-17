"""Gauntlet (MAME `gauntlet`, Atari Games 1985, rev 14): the reference board, from MAME atari/gauntlet.cpp, slapstic.cpp
and the devices it uses (machine/gen_latch.cpp, 74259.cpp, eeprompar.cpp; emu/schedule.cpp, screen.cpp, timer.cpp).
The picture is tools/video.py's; this file is the CPUs, the buses and the time.

Executing devices, in MAME's order: the main MC68010 at 14.318181 MHz / 2 (engine/m68kmame.py: MAME's own Musashi
built outside MAME), the sound MOS 6502 at 14.318181 MHz / 8 (engine/m6502mame.py) and the POKEY at the same clock
(engine/pokey.py; MAME's POKEY is a device_execute_interface).  The screen: 7.159 MHz pixel
clock, 456 x 262 (a line = 456 main CPU cycles, a frame 119472: 59.92 Hz), visible 336 x 240, the blank starts at
line 240 (MAME's time 0) and lasts 22 lines.

Main CPU (main_map, every range mirrored as MAME maps it):
    000000-037FFF ROM, 038000-03FFFF the slapstic's 8 KB bank (4 banks of 136037-205/-206; mirrored 4 times),
    040000-07FFFF ROM (only 000000-00FFFF, 038000-04FFFF are populated)
    800000-801FFF work RAM; 802000-8023FF the 2804 EEPROM (low byte lane; locked after each write, 803150 unlocks)
    r 803000-803006 the players' inputs, 803008 status (bit 3 service, 4 sound response pending, 5 sound command
      pending, 6 low in the vertical blank), 80300F the sound response (clears IRQ 6)
    w 803100 watchdog, 803120-80312F the 74LS259 (bit 0 of A1-A3's latch; Q7 = sound CPU out of reset),
      803140 IRQ 4 acknowledge, 803150 EEPROM unlock, 803171 the sound command (the 6502's NMI)
    900000-905FFF video RAM (playfield, motion objects, spare, alphanumerics; 905F6E the y scroll / tile bank),
    910000-9107FF palette (1024 pens IRGB_4444), w 930000 x scroll
    IRQ 4 = vertical blank (asserted at its start until 803140 is written), IRQ 6 = sound response pending.
Sound CPU: 0000-0FFF RAM, w 1000 response, r 1010 command, r 1020 coins / w mixer, r 1030 status (bit 7 command
pending, 6 response pending, 5 speech not ready, 4 service) / w 1030-1037 the second 74LS259 (Q0 YM2151 reset, Q1
speech write, Q2 speech reset, Q3 speech squeak, Q4-5 coin counters), 1800 POKEY, 1810 YM2151, 1820 speech data,
1830 IRQ acknowledge, 4000-FFFF ROM.  IRQ = the scanline timer on lines 32, 96, 160, 224; NMI = command pending.

The slapstic (137412-104) sees every bus access of the main CPU, opcode fetches included (MAME taps the whole
program space): engine/m68kmame/glue.cpp runs its state machine on the tests built here (MAME's checker).

Scheduler: MAME's timeslice() with integer attoseconds; the quantum 1/60 s (no machine config sets one), a perfect
quantum (the 2nd smallest CPU minimum quantum) for 100 us after each sound command; a timer inserted at the list's
head aborts the running CPU's slice after its instruction; input lines change through synchronize() timers; the
sound manager's 50 Hz update timer and the scanline timer (every 32 lines) cut slices.
"""
from pathlib import Path
import sys

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "engine"))
from paths import EXTRACTED
import m68kmame as M

AS = 10 ** 18
XTAL = 14318181
MAIN_HZ = int(XTAL / 2 + 1e-3)           # XTAL::value(): 7159090
SOUND_HZ = int(XTAL / 8 + 1e-3)          # 1789772
YM_HZ = int(XTAL / 4 + 1e-3)             # 3579545
PIXEL_HZ = MAIN_HZ
HTOTAL, VTOTAL, VBSTART = 456, 262, 240
FRAME_AS = (AS // PIXEL_HZ) * HTOTAL * VTOTAL      # screen_device::set_raw's refresh
SCAN_AS = FRAME_AS // VTOTAL
PIXEL_AS = FRAME_AS // (VTOTAL * HTOTAL)
VBLANK_AS = SCAN_AS * (VTOTAL - VBSTART)
QUANTUM_60 = AS // 60
SOUND_UPDATE_AS = AS // 50               # sound_manager's periodic stream update
MAIN_AS = AS // MAIN_HZ
SOUND_AS = AS // SOUND_HZ
PERFECT_AS = min(4 * MAIN_AS, SOUND_AS) if False else max(4 * MAIN_AS, SOUND_AS)   # (2nd smallest minimum quantum)
LATCH_QUANTUM_FOR = AS // 10000          # perfect_quantum(attotime::from_usec(100))

SLAPSTIC_START = 3                       # slapstic104: bankstart; bank select values 0x20/0x28/0x30/0x38
SLAPSTIC_BANKS = [0x0020, 0x0028, 0x0030, 0x0038]
SLAPSTIC_104 = dict(alt1=(0x007f, 0x0069), alt2=(0x3fff, 0x3735), alt3=(0x3ffc, 0x3764), alt4=(0x3fe7, 0x0020),
                    altshift=0, bit1=(0x3ff0, 0x3d90), bit2=(0x3fe7, 0x0020), bit3c0=(0x3ff3, 0x3d90),
                    bit3s0=(0x3ff3, 0x3d91), bit3c1=(0x3ff3, 0x3d92), bit3s1=(0x3ff3, 0x3d93), bit4=(0x3ff8, 0x3da0))
BANK_COPY = 0xF00000                     # where the core's memory keeps the four slapstic banks (an unused area)

M68K_IRQ_4, M68K_IRQ_6 = 4, 6
INPUT_IDLE = 0xFFFF                      # 803000-803006: nothing pressed (active low; bits 8-15 unused, read 1)


def load(name):
    return (EXTRACTED / "gauntlet" / name).read_bytes()


def main_rom():
    """MAME's maincpu region (0x80000): ROM_LOAD16_BYTE with ROM_CONTINUE (the files' halves swapped)"""
    rom = bytearray(0x80000)

    def l16(name, off, cont=None):
        b = load(name)
        h = len(b) if cont is None else len(b) // 2
        rom[off:off + 2 * h:2] = b[:h]
        if cont is not None:
            rom[cont:cont + 2 * h:2] = b[h:]
    l16("136037-1307.9a", 0x8000, 0x0000)
    l16("136037-1308.9b", 0x8001, 0x0001)
    l16("136037-205.10a", 0x38000)
    l16("136037-206.10b", 0x38001)
    l16("136037-1409.7a", 0x48000, 0x40000)
    l16("136037-1410.7b", 0x48001, 0x40001)
    return bytes(rom)


def sound_rom():
    rom = bytearray(0x10000)
    rom[0x4000:0x8000] = load("136037-120.16r")
    rom[0x8000:0x10000] = load("136037-119.16s")
    return bytes(rom)


def mirrors(start, end, mirror):
    """the (start, end) copies of a range under a MAME mirror mask (only the bits above a 4 KB page matter here)"""
    bits = [1 << b for b in range(12, 24) if mirror & (1 << b)]
    out = []
    for k in range(1 << len(bits)):
        off = sum(b for i, b in enumerate(bits) if k >> i & 1)
        out.append((start | off, end | off))
    return out


class Timer:
    __slots__ = ("expire", "seq", "fn", "live")

    def __init__(self, fn):
        self.fn = fn
        self.expire = None
        self.seq = 0
        self.live = False


class Exec:
    """a device_execute_interface: local time, the cycle period and divisor (divu_64x32 of the delta), suspension"""

    def __init__(self, name, core, hz):
        self.name = name
        self.core = core
        self.as_per_cycle = AS // hz
        self.shift = 0
        while (self.as_per_cycle >> self.shift) >= 1 << 32:
            self.shift += 1
        self.div = self.as_per_cycle >> self.shift
        self.local = 0
        self.suspended = False
        self.queues = {}


class Latch:
    """generic_latch_8_device: a write lands through a synchronize() timer, a read clears the pending flag at once"""

    def __init__(self, board, pending_cb):
        self.b = board
        self.cb = pending_cb
        self.value = 0
        self.written = False

    def write(self, v):
        self.b.synchronize(lambda: self.sync(v))

    def sync(self, v):
        self.value = v
        self.set_written(True)

    def set_written(self, state):
        if self.written != state:
            self.written = state
            self.cb(state)

    def read(self):
        self.set_written(False)
        return self.value


class LS259:
    """addressable_latch_device (74LS259): Q0-Q7, the clear input; cb(bit, state) on each change"""

    def __init__(self, cb):
        self.cb = cb
        self.q = 0xFF                        # device_start's arbitrary state; device_reset clears it
        self.clear = False

    def reset(self):
        self.set_all(0)

    def set_all(self, v):
        old, self.q = self.q, v
        for b in range(8):
            if (old ^ v) >> b & 1:
                self.cb(b, v >> b & 1)

    def write_bit(self, bit, d):
        """write_bit: the address and data, then the enable pulse (the bit only, or clear the others in clear mode)"""
        d = 1 if d else 0
        if (self.q >> bit & 1) == d:
            return
        if not self.clear:
            self.set_all((self.q & ~(1 << bit)) | (d << bit))
        else:
            self.set_all(d << bit)

    def clear_w(self, state):
        self.clear = not state
        if self.clear:
            self.set_all(0)


class EEPROM2804:
    """eeprom_parallel_28xx (2804, 512 bytes, lock_after_write): blank = $FF; reads while unlocked read the bus"""

    def __init__(self, board):
        self.b = board
        self.data = bytearray(b"\xff" * 512)
        self.oe = 0                          # device_reset with lock_after_write: locked
        self.done = 0                        # m_completion_time

    def read(self, offset):
        if self.oe == 1:
            return None                      # space.unmap()
        return self.data[offset]

    def write(self, offset, v):
        if self.oe == 0:
            return
        self.data[offset] = v
        self.done = self.b.now() + 1750 * AS // 1000000
        self.oe = 0


class Gauntlet:
    def __init__(self, inputs=None, sound=True):
        self.rom = main_rom()
        self.snd_rom = sound_rom()
        self.inputs = [INPUT_IDLE] * 4       # 803000-803006 (active low)
        self.coins = 0xFF                    # the sound CPU's 1020 (active low)
        self.service = False
        self.frame = 0
        self.sound_log = []                  # (frame, command)
        self.reply_log = []                  # (frame, response)
        self.xscroll = 0
        self.lines = []                      # (beam line, x scroll, y scroll) before each scroll change this picture
        # the scheduler
        self.base = 0
        self.timers = []
        self.seq = 0
        self.executing = None
        self.cb_time = None
        self.quanta = [[QUANTUM_60, None]]   # [requested, expire], sorted by requested
        self.stop = False
        self.watchdog = 0
        self.vblank_end_time = 0
        # devices
        self.soundlatch = Latch(self, self.soundlatch_pending)     # main -> sound
        self.mainlatch = Latch(self, lambda s: self.set_line(self.main, M68K_IRQ_6, s))
        self.eeprom = EEPROM2804(self)
        self.outlatch = LS259(self.outlatch_changed)
        self.soundctl = LS259(self.soundctl_changed)
        self.make_main()
        self.main = Exec("maincpu", MainExec(self.cpu), MAIN_HZ)
        self.execs = [self.main]
        if sound:
            self.make_sound()
        self.rebuild()
        # machine reset: the latches (gen_latch device_reset), the 74LS259s (cleared: Q7 low holds the sound CPU in
        # reset), the CPUs
        self.outlatch.reset()
        if sound:
            self.snd_devices.tms.device_reset()
        self.soundctl.reset()
        self.cpu.reset()
        # the screen and the timers, in MAME's start order
        self.vblank_timer = self.timer_at(FRAME_AS, self.vblank_begin)
        self.vblank_end_timer = self.timer_at(VBLANK_AS, self.vblank_end)
        self.scanline0_timer = self.timer_at(VBLANK_AS, self.scanline0)
        self.scan_timer = self.timer_at(VBLANK_AS, lambda: self.scanline(0))
        self.timer_at(SOUND_UPDATE_AS, self.sound_update)

    # ---- the main CPU -----------------------------------------------------
    def make_main(self):
        cpu = self.cpu = M.M68010(self.main_rd, self.main_wr)
        mem = cpu.mem
        mem[:0x80000] = np.frombuffer(self.rom, np.uint8)
        for b in range(4):                  # the slapstic's banks, apart
            mem[BANK_COPY + b * 0x2000:BANK_COPY + (b + 1) * 0x2000] = np.frombuffer(
                self.rom[0x38000 + b * 0x2000:0x3A000 + b * 0x2000], np.uint8)
        for s, e in mirrors(0x000000, 0x037FFF, 0x280000):
            cpu.map(s, e, M.ROM, 0x000000)
        for s, e in mirrors(0x040000, 0x07FFFF, 0x280000):
            cpu.map(s, e, M.ROM, 0x040000)
        bank_pages = []
        for s, e in mirrors(0x038000, 0x03FFFF, 0x280000):
            cpu.map(s, e, M.ROM)
            bank_pages += list(range(s >> 12, (e >> 12) + 1))
        for s, e in mirrors(0x800000, 0x801FFF, 0x2FC000):
            cpu.map(s, e, M.RAM, 0x800000)
        for s, e in mirrors(0x802000, 0x802FFF, 0x2FC000):
            cpu.map(s, e, M.CALLBACK, 0x802000)          # EEPROM
        for s, e in mirrors(0x803000, 0x803FFF, 0x2FC000):
            cpu.map(s, e, M.CALLBACK, 0x803000)          # I/O
        for s, e in mirrors(0x900000, 0x904FFF, 0x2C8000):
            cpu.map(s, e, M.RAM, 0x900000)
        for s, e in mirrors(0x905000, 0x905FFF, 0x2C8000):
            cpu.map(s, e, M.CALLBACK, 0x905000)          # alphanumerics, y scroll, SLIPs
        for s, e in mirrors(0x910000, 0x91FFFF, 0x2C0000):
            cpu.map(s, e, M.CALLBACK, 0x910000)          # palette (2 KB, mirrored in each page)
        for s, e in mirrors(0x930000, 0x93FFFF, 0x2C0000):
            cpu.map(s, e, M.CALLBACK, 0x930000)          # x scroll
        rng = ~(0x7FFF | 0x280000) & 0xFFFFFFFF          # checker(0x38000, 0x3ffff, 0x280000, 16 bits, 14 lines)
        val, sh, inp = 0x38000, 1, 0x3FFF << 1
        test_in = lambda mv: ((rng | (mv[0] << sh)) & 0xFFFFFFFF, val | (mv[1] << sh))
        test_any = lambda mv: (mv[0] << sh, mv[1] << sh)
        d = SLAPSTIC_104
        tests = [((rng | inp) & 0xFFFFFFFF, val)]                                   # reset
        tests += [((rng | inp) & 0xFFFFFFFF, val | (b << sh)) for b in SLAPSTIC_BANKS]
        tests += [test_any(d["alt1"]), test_in(d["bit1"]), test_in(d["alt2"]), test_in(d["alt3"]),
                  test_in(d["alt4"]), test_in(d["bit2"])]
        tests += [test_in(d[k]) for k in ("bit3c0", "bit3s0", "bit3c1", "bit3s1")]      # odd: clear0 set0 clear1 set1
        tests += [test_in(d[k]) for k in ("bit3s1", "bit3c1", "bit3s0", "bit3c0")]      # even
        tests += [test_in(d["bit4"])]
        cpu.slapstic(tests, sh + d["altshift"], bank_pages, [BANK_COPY + b * 0x2000 for b in range(4)], SLAPSTIC_START)

    def vblank(self):
        """screen_device::vblank() at the executing CPU's time"""
        return self.now() < self.vblank_end_time

    def main_rd(self, a, mask, kind):
        cpu = self.cpu
        page = a >> 12 & 0xF0F
        if page == 0x803:
            o = a & 0x10F
            if o < 8:
                return self.inputs[o >> 1]
            if o == 8:
                v = 0x0008 if not self.service else 0
                v |= (0x10 if self.mainlatch.written else 0) | (0x20 if self.soundlatch.written else 0)
                return v | (0 if self.vblank() else 0x40)
            if o == 0x0E:
                if mask & 0x00FF:
                    v = self.mainlatch.read()
                    self.reply_log.append((self.frame, v))
                    return 0xFF00 | v
                return 0xFFFF
            return 0xFFFF
        if page == 0x802:
            if not mask & 0x00FF:
                return 0xFFFF
            v = self.eeprom.read((a & 0x3FF) >> 1)
            return 0xFFFF if v is None else 0xFF00 | v
        if page == 0x905:
            p = 0x905000 + (a & 0xFFF)
            return (int(cpu.mem[p]) << 8) | int(cpu.mem[p + 1])
        if page == 0x910 or (a >> 16 & 0xF) == 0x1 and (a >> 20 & 0xF) == 0x9:
            p = 0x910000 + (a & 0x7FF)
            return (int(cpu.mem[p]) << 8) | int(cpu.mem[p + 1])
        return 0xFFFF

    def main_wr(self, a, v, mask):
        cpu = self.cpu
        top = a >> 16
        if top & 0xF0 == 0x80 or top & 0xF0 == 0xA0:
            if a >> 12 & 0xF == 2:
                if mask & 0x00FF:
                    self.eeprom.write((a & 0x3FF) >> 1, v & 0xFF)
                return
            o = a & 0x171
            if o == 0x100:
                self.watchdog = 0
            elif o & 0x170 == 0x120 or (a & 0x170) == 0x120:
                if mask & 0x00FF:
                    self.outlatch.write_bit((a >> 1) & 7, v & 1)
            elif o == 0x140:
                self.set_line(self.main, M68K_IRQ_4, False)
            elif o == 0x150:
                self.eeprom.oe = 1
            elif o == 0x170:
                if mask & 0x00FF:
                    self.sound_log.append((self.frame, v & 0xFF))
                    self.soundlatch.write(v & 0xFF)
            return
        sub = (a >> 16) & 0x3                 # 0x90/0x91/0x93 within the VBUS
        if a >> 12 & 0xF0F == 0x905:
            p = 0x905000 + (a & 0xFFF)
            old = (int(cpu.mem[p]) << 8) | int(cpu.mem[p + 1])
            new = (old & ~mask) | (v & mask)
            if p == 0x905F6E and new != old:
                self.partial_update()
            cpu.mem[p] = new >> 8
            cpu.mem[p + 1] = new & 0xFF
            return
        if sub == 1:
            p = 0x910000 + (a & 0x7FF)
            old = (int(cpu.mem[p]) << 8) | int(cpu.mem[p + 1])
            new = (old & ~mask) | (v & mask)
            cpu.mem[p] = new >> 8
            cpu.mem[p + 1] = new & 0xFF
            return
        if sub == 3:
            new = (self.xscroll & ~mask) | (v & mask)
            if new != self.xscroll:
                self.partial_update()
                self.xscroll = new

    def outlatch_changed(self, bit, state):
        if bit == 7:
            self.sound_reset_w(state)

    def sound_reset_w(self, state):
        """gauntlet_state::sound_reset_w: Q7 low holds the sound CPU in reset (and clears the second latch, the
        response's pending flag and the mixer)"""
        if hasattr(self, "sound"):
            self.set_line(self.sound, "reset", not state)
        self.soundctl.clear_w(state)
        if not state:
            self.mainlatch.set_written(False)
            if hasattr(self, "snd_devices"):
                self.snd_devices.mixer_w(0)

    def soundctl_changed(self, bit, state):
        if hasattr(self, "snd_devices"):
            self.snd_devices.soundctl(bit, state)

    def reply_written(self, v):
        """the sound CPU's 1000: the response latch (IRQ 6 while pending)"""
        self.mainlatch.write(v)

    def soundlatch_pending(self, state):
        if hasattr(self, "sound"):
            self.set_line(self.sound, "nmi", state)
        if state:
            self.add_quantum(0, LATCH_QUANTUM_FOR)

    def partial_update(self):
        """update_partial(vpos()) before a scroll change: lines up to the beam's keep the old scroll (recorded as
        (beam line, x scroll, y scroll) with the values before the change; video.py's segments start a line later)"""
        m = self.cpu.mem
        self.lines.append((self.vpos(), self.xscroll, (int(m[0x905F6E]) << 8) | int(m[0x905F6F])))

    def segments(self):
        """the picture's (first line, x scroll, y scroll) ranges for video.Video.render_rgb (the current scroll from
        the last change on)"""
        m = self.cpu.mem
        now = (self.xscroll, (int(m[0x905F6E]) << 8) | int(m[0x905F6F]))
        segs, first = [], 0
        for line, xs, ys in self.lines:
            if line >= VBSTART - 1:
                continue
            segs.append((first, xs, ys))
            first = line + 1
        segs.append((first,) + now)
        return segs

    def render_rgb(self):
        if not hasattr(self, "video"):
            from video import Video
            self.video = Video()
        segs = self.segments()
        return self.video.render_rgb(self.vram(), self.palette(), segs[-1][1], segs[-1][2],
                                     segments=segs if len(segs) > 1 else None)

    # ---- the sound CPU ----------------------------------------------------
    def make_sound(self):
        from gauntlet_sound import SoundBoard
        self.snd_devices = SoundBoard(self)
        self.sound = Exec("audiocpu", self.snd_devices.exec_core(), SOUND_HZ)
        self.sound.suspended = False
        from pokey import CLOCK
        self.pokey = Exec("pokey", self.snd_devices.pokey, CLOCK)
        self.execs += [self.sound, self.pokey]

    # ---- the scheduler ----------------------------------------------------
    def now(self):
        e = self.executing
        if e is None:
            return self.base if self.cb_time is None else self.cb_time
        return e.local + e.core.executed() * e.as_per_cycle

    def adjust(self, t, expire):
        """emu_timer::adjust: (re)inserted after the timers with the same expiry; at the head it aborts the
        executing CPU's slice"""
        if t.live:
            self.timers.remove(t)
        t.expire = expire
        t.seq = self.seq
        self.seq += 1
        t.live = True
        k = len(self.timers)
        while k and self.timers[k - 1].expire > expire:
            k -= 1
        self.timers.insert(k, t)
        if k == 0 and self.executing is not None:
            self.executing.core.abort()
        return t

    def cancel(self, t):
        if t.live:
            self.timers.remove(t)
            t.live = False

    def timer_at(self, expire, fn):
        return self.adjust(Timer(fn), expire)

    def new_timer(self, fn):
        return Timer(fn)

    def timer(self, expire, fn):
        return self.timer_at(expire, fn)

    def synchronize(self, fn):
        return self.timer_at(self.now(), fn)

    def add_quantum(self, quantum, duration):
        """device_scheduler::add_quantum (perfect_quantum: quantum 0, its actual length the perfect interleave)"""
        cur = self.now()
        expire = cur + duration
        q = [x for x in self.quanta if x[1] is None or cur < x[1]]
        k = 0
        while k < len(q) and q[k][0] <= quantum:
            k += 1
        if k and q[k - 1][0] == quantum:
            if q[k - 1][1] is not None:
                q[k - 1][1] = max(q[k - 1][1], expire)
        else:
            q.insert(k, [quantum, expire])
        self.quanta = q

    def rebuild(self):
        """rebuild_execute_list: the running CPUs in device order, then the suspended ones"""
        self.order = [e for e in self.execs if not e.suspended] + [e for e in self.execs if e.suspended]

    def set_line(self, e, line, state):
        """device_input::set_state_synced: queued, applied by a synchronize() timer"""
        q = e.queues.setdefault(line, [])
        q.append(state)
        if len(q) == 1:
            self.synchronize(lambda: self.apply_line(e, line))

    def apply_line(self, e, line):
        for state in e.queues.pop(line):
            if line == "reset":
                if state:
                    if not e.suspended:
                        e.suspended = True
                        self.rebuild()
                        if self.executing is e:
                            e.core.abort()
                elif e.suspended:
                    e.core.reset()
                    e.suspended = False
                    self.rebuild()
            else:
                e.core.set_line(line, state)

    def timeslice(self):
        timers = self.timers
        while self.quanta[0][1] is not None and self.base >= self.quanta[0][1]:
            self.quanta.pop(0)
        while self.base < timers[0].expire:
            q = self.quanta[0][0]
            target = self.base + (q if q > PERFECT_AS else PERFECT_AS)
            if timers[0].expire < target:
                target = timers[0].expire
            for e in self.order:
                delta = target - e.local
                if delta >= e.as_per_cycle:
                    n = (delta >> e.shift) // e.div
                    if e.suspended:
                        ran = n
                    else:
                        self.executing = e
                        ran = e.core.run(n)
                        self.executing = None
                    e.local += ran * e.as_per_cycle
                    if e.local < target:
                        target = max(e.local, self.base)
            self.base = target
        while timers and timers[0].expire <= self.base and not self.stop:
            t = timers.pop(0)
            t.live = False
            self.cb_time = t.expire
            t.fn()
        self.cb_time = None

    # ---- the screen and the timers ------------------------------------------
    def vpos(self):
        """screen_device::vpos(): rounded to the nearest pixel; time 0 is the blank's start (line 240)"""
        return int(((self.now() % FRAME_AS + PIXEL_AS // 2) // SCAN_AS + VBSTART) % VTOTAL)

    def time_until_line(self, line):
        """screen_device::time_until_pos(line, 0) from now"""
        now = self.now()
        pos = (now + VBSTART * SCAN_AS) % FRAME_AS
        d = (line * SCAN_AS - pos) % FRAME_AS
        return now + (d if d else FRAME_AS)

    def vblank_begin(self):
        """screen_device::vblank_begin: the IRQ 4 line, the watchdog's vblank count, frame_update (MAME's frame_done:
        run_frame returns here)"""
        self.vblank_end_time = self.cb_time + VBLANK_AS
        self.adjust(self.vblank_timer, self.cb_time + FRAME_AS)
        self.adjust(self.vblank_end_timer, self.cb_time + VBLANK_AS)
        self.set_line(self.main, M68K_IRQ_4, True)
        self.watchdog += 1
        if self.watchdog >= 8:
            raise RuntimeError("watchdog reset at frame %d" % self.frame)
        self.stop = True

    def vblank_end(self):
        pass

    def scanline0(self):
        self.adjust(self.scanline0_timer, self.cb_time + FRAME_AS)
        self.lines = []

    def scanline(self, line):
        """the scanline timer device (lines 0, 32, ..., 256): the sound CPU's IRQ on 32V"""
        nxt = line + 32 if line + 32 < VTOTAL else 0
        self.adjust(self.scan_timer, self.time_until_line(nxt))
        self.scan_timer.fn = lambda: self.scanline(nxt)
        if line & 32 and hasattr(self, "sound"):
            self.set_line(self.sound, "irq", True)

    def sound_update(self):
        self.timer_at(self.cb_time + SOUND_UPDATE_AS, self.sound_update)
        if hasattr(self, "snd_devices"):
            self.snd_devices.stream_update()

    def run_frame(self):
        """One arcade frame, ending where MAME's frame_done comes (the vertical blank's start)."""
        self.stop = False
        while not self.stop:
            self.timeslice()
        self.frame += 1

    # ---- memory views ---------------------------------------------------------
    def ram(self):
        return bytes(self.cpu.mem[0x800000:0x802000])

    def vram(self):
        return bytes(self.cpu.mem[0x900000:0x906000])

    def palette(self):
        return bytes(self.cpu.mem[0x910000:0x910800])


class MainExec:
    """engine/m68kmame.py's 68010 in the scheduler's protocol (run, executed, abort, set_line, reset)"""

    def __init__(self, cpu):
        self.cpu = cpu

    def run(self, n):
        return self.cpu.run(n)

    def executed(self):
        return self.cpu.executed()

    def abort(self):
        self.cpu.abort()

    def set_line(self, line, state):
        self.cpu.set_input(line, state)

    def reset(self):
        self.cpu.reset()
