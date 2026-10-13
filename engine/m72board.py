"""Irem M72 reference board, the logic (MAME irem/m72.cpp, m72_a.cpp; machine/pic8259.cpp, mb8421.h, rstbuf.cpp,
gen_latch.cpp; emu/schedule.cpp): R-Type (`rtype`) and Mr. HELI no Daibouken (`mrheli`, with the i8751 MCU).
The picture is engine/m72.py's; this file is the CPUs, the buses and the time.

CPUs, in MAME's device order: the main NEC V30 at 8 MHz (engine/v30.py), the sound Z80 at 3.579545 MHz
(engine/z80mame.py), the i8751 MCU at 8 MHz / 12 (engine/i8051.py; mrheli only).  The screen: 8 MHz pixel clock, 512 x
284 (a line = 512 main CPU cycles, a frame 145408: 55.017 Hz), visible lines 0-255, the blank starts at line 256.

Main CPU (rtype_map / m72_protected_map): 00000-3FFFF ROM (mrheli 00000-7FFFF), work RAM 40000-43FFF (mrheli A0000-
A3FFF), mrheli B0000-B0FFF the MB8421/MB8431 dual-port RAM (writes reach it through a synchronize() timer),
C0000-C03FF sprite RAM (copied to the buffer the picture shows by a write to port 04), C8000-C8BFF / CC000-CCBFF the
palettes (R, G, B planes of 256 words, 5 bits; A9 not decoded; reads have bits 5-15 set), D0000-D3FFF / D8000-DBFFF
the FG / BG tile RAM, E0000-EFFFF the sound CPU's 64 KB RAM (byte wide), FFFF0-FFFFF ROM (the region's end).
Ports: 00/02/04 IN0 / IN1 / DSW (words), write 00 sound latch, 02 control (bit 4: sound CPU out of reset, bit 3
display off, bit 2 flip), 04 sprite DMA, 06 raster line (ISET: line = value - 128), 40/42 the uPD71059 (an 8259 in
x86 mode, low byte lane), 80/82/84/86 scroll Y / X of FG and BG; mrheli: C0 the second sound latch (sound CPU NMI).

Interrupts: a timer at every line (MAME's scanline_interrupt): IR2 at the raster line (the picture is cut there),
IR0 at line 256 (a one-line pulse: the 8259 is edge triggered and a falling input clears its request).  Sound: the
latch (RST 18) and the YM2151 (RST 28) through an RST_NEG_BUFFER (vector $FF ^ inputs) on the Z80's INT.  MCU:
dual-port RAM mailbox (main writes the right side's last word -> INT0), the sound CPU's latch (port 82) -> INT1;
its data space: 0000 sample ROM byte (auto increment) / sample address bits 5-12, 0001 address bits 13+, 0002 the
latch (read; a write acknowledges), C000-CFFF the dual-port RAM's other side; port 1 -> the DAC.

Scheduler: MAME's timeslice() with integer attoseconds; quanta: 1/60 s (the default) and 1.5 us for the first 25
s (machine_reset's synch_callback adds MASTER_CLOCK/4/12); a timer inserted at the list's head aborts the running
CPU's slice after its current instruction; input lines change through synchronize() timers (device_input queues);
the sound manager's 50 Hz update timer cuts slices too (REP string instructions run in slice-sized chunks, so the
slice ends show in the program's timing).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from paths import EXTRACTED

AS = 10 ** 18
MAIN_HZ = 8000000
SOUND_HZ = 3579545
MCU_HZ = 8000000                 # machine cycles at /12 (the core's clock divider)
PIXEL_HZ = 8000000
HTOTAL, VTOTAL, VBSTART = 512, 284, 256
SCAN_AS = HTOTAL * (AS // PIXEL_HZ)
FRAME_AS = VTOTAL * SCAN_AS
QUANTUM_60 = AS // 60                                  # attotime::from_hz(60)
QUANTUM_SYNC = int(AS / (32000000 / 4 / 12))           # attotime::from_hz(double): 1.5 us
QUANTUM_SYNC_FOR = 25 * AS
YM_AS = AS // SOUND_HZ
SOUND_UPDATE_AS = AS // 50          # sound_manager's periodic stream update: a timer, it splits slices
YM_RATE = SOUND_HZ // 64

# MAME's ROM loads per set (our archive names): ("main16", name, start, reloads) are ROM_LOAD16_BYTE
GAMES = {
    "rtype": dict(mcu=False, ram=0x40000, rom_end=0x40000, dsw=0xFDFB, files=[
        ("main16", "rt_r-l0-b.3b", 0x00000, ()), ("main16", "rt_r-h0-b.1b", 0x00001, ()),
        ("main16", "rt_r-l1-b.3c", 0x20000, (0xE0000,)), ("main16", "rt_r-h1-b.1c", 0x20001, (0xE0001,))]),
    "mrheli": dict(mcu=True, ram=0xA0000, rom_end=0x80000, dsw=0xFDFF, files=[
        ("main16", "mh-c-l0.bin", 0x00000, ()), ("main16", "mh-c-h0.bin", 0x00001, ()),
        ("main16", "mh-c-l1.bin", 0x20000, ()), ("main16", "mh-c-h1.bin", 0x20001, ()),
        ("main16", "mh-c-l3.bin", 0x60000, (0xE0000,)), ("main16", "mh-c-h3.bin", 0x60001, (0xE0001,)),
        ("mcu", "mh_c-pr-.ic1", 0, ()), ("samples", "c-v0-b.rom", 0, ())]),
}


def load_regions(game, romdir=None):
    romdir = romdir or str(EXTRACTED / game)
    r = {"main": bytearray(0x100000), "mcu": bytearray(0x1000), "samples": bytearray(0x10000)}
    for kind, name, start, reloads in GAMES[game]["files"]:
        with open(os.path.join(romdir, name), "rb") as f:
            data = f.read()
        if kind == "main16":
            for s in (start,) + reloads:
                r["main"][s:s + 2 * len(data):2] = data
        else:
            r[kind][start:start + len(data)] = data
    return r


class Timer:
    __slots__ = ("expire", "seq", "fn", "live")

    def __init__(self, fn):
        self.fn = fn
        self.expire = None
        self.seq = 0
        self.live = False


class PIC8259:
    """pic8259_device as the M72 uses it (single, x86 mode): the inputs, IRR/ISR/IMR, priority rotation, the
    acknowledge; every change re-evaluates through m_irq_timer (adjust(zero): a timer at now())."""

    def __init__(self, board, out_int):
        self.b = board
        self.out_int = out_int
        self.timer = board.new_timer(self.tick)
        self.reset()

    def reset(self):
        self.state = "READY"
        self.isr = self.irr = self.irq_lines = self.prio = self.imr = 0
        self.ocw3 = 2
        self.level_trig = self.vector_size = self.cascade = self.icw4_needed = 0
        self.base = self.slave = self.nested = self.mode = self.auto_eoi = self.is_x86 = 0
        self.vec_low = self.vec_high = 0
        self.current = -1
        self.inta_seq = 0

    def kick(self):
        self.b.adjust(self.timer, self.b.now())

    def tick(self):
        irq = self.prio
        for _ in range(8):
            mask = 1 << irq
            if self.isr & mask:
                break
            if self.state == "READY" and (self.irr & mask) and not (self.imr & mask):
                self.current = irq
                self.out_int(1)
                return
            irq = (irq + 1) & 7
        self.current = -1
        self.out_int(0)

    def set_irq_line(self, irq, state):
        mask = 1 << irq
        if state and not (self.irq_lines & mask):
            self.irr |= mask
            self.irq_lines |= mask
        elif not state and (self.irq_lines & mask):
            self.irq_lines &= ~mask
            self.irr &= ~mask
        if self.inta_seq == 0:
            self.kick()

    def acknowledge(self):
        if not self.is_x86:
            raise NotImplementedError("8080 mode INTA")
        if self.current == -1:
            return self.base + 7
        mask = 1 << self.current
        if not self.level_trig:
            self.irr &= ~mask
        if not self.auto_eoi:
            self.isr |= mask
        self.kick()
        return self.current + self.base

    def read(self, offset):
        if offset == 0:
            if self.ocw3 & 4:
                if self.current == -1:
                    return 0
                v = 0x80 | self.current
                if not self.level_trig:
                    self.irr &= ~(1 << self.current)
                if not self.auto_eoi:
                    self.isr |= 1 << self.current
                self.kick()
                return v
            return {2: self.irr, 3: self.isr & ~self.imr & 0xFF}.get(self.ocw3 & 3, 0)
        return self.imr

    def write(self, offset, data):
        if offset == 0:
            if data & 0x10:
                self.imr = self.isr = self.irr = self.slave = 0
                self.level_trig = (data >> 3) & 1
                self.vector_size = (data >> 2) & 1
                self.cascade = 0 if data & 2 else 1
                self.icw4_needed = data & 1
                self.vec_low = data & 0xE0
                self.state = "ICW2"
                self.current = -1
                self.inta_seq = 0
                self.out_int(0)
            elif self.state == "READY":
                if (data & 0x98) == 0x08:
                    self.ocw3 = data
                elif (data & 0x18) == 0:
                    n = data & 7
                    op = data & 0xE0
                    if op == 0x00:
                        self.prio = 0
                    elif op in (0x20, 0xA0):                 # non-specific EOI (0xA0: and rotate)
                        mask = 1 << self.prio
                        for _ in range(8):
                            if self.isr & mask:
                                self.isr &= ~mask
                                if op == 0xA0:
                                    self.prio = (self.prio + 1) & 7
                                break
                            mask = ((mask << 1) | (mask >> 7)) & 0xFF
                    elif op == 0x60:
                        self.isr &= ~(1 << n)
                    elif op == 0x80:
                        self.prio = (self.prio + 1) & 7
                    elif op == 0xC0:
                        self.prio = (n + 1) & 7
                    elif op == 0xE0:
                        if self.isr & (1 << n):
                            self.isr &= ~(1 << n)
                            self.prio = (n + 1) & 7
        else:
            if self.state == "ICW2":
                self.base = data & 0xF8
                self.vec_high = data
                self.state = "ICW3" if self.cascade else ("ICW4" if self.icw4_needed else "READY")
            elif self.state == "ICW3":
                self.slave = data
                self.state = "ICW4" if self.icw4_needed else "READY"
            elif self.state == "ICW4":
                self.nested = (data >> 4) & 1
                self.mode = (data >> 2) & 3
                self.auto_eoi = (data >> 1) & 1
                self.is_x86 = data & 1
                self.state = "READY"
            elif self.state == "READY":
                self.imr = data
        self.kick()


class Latch:
    """generic_latch_8_device with a separate acknowledge: write() stores through a synchronize() timer and raises
    data pending; the reader's acknowledge_w clears it (read() does not)."""

    def __init__(self, board, pending_cb):
        self.b = board
        self.cb = pending_cb
        self.value = 0
        self.written = False

    def write(self, v):
        self.b.synchronize(lambda: self._sync(v))

    def _sync(self, v):
        self.value = v
        self.set_written(True)

    def set_written(self, w):
        if self.written != w:
            self.written = w
            self.cb(1 if w else 0)

    def acknowledge(self):
        self.set_written(False)


class RstNegBuffer:
    """rst_neg_buffer_device: RST 18 (latch) / RST 28 (YM2151) inputs, synchronized; vector $FF ^ inputs"""

    def __init__(self, board, int_cb):
        self.b = board
        self.cb = int_cb
        self.buf = 0

    def input(self, state, mask):
        self.b.synchronize(lambda: self._set(mask) if state else self._clear(mask))

    def _set(self, mask):
        if self.buf == 0:
            self.buf = mask
            self.cb(1)
        else:
            self.buf |= mask

    def _clear(self, mask):
        if self.buf == mask:
            self.buf = 0
            self.cb(0)
        else:
            self.buf &= ~mask

    def vector(self):
        return 0xFF ^ self.buf


class YM2151:
    """The sound CPU's view of the YM2151 (as engine/namcos1.py's, after ymfm): timers A and B as scheduler timers,
    status, the IRQ (-> RST 28), busy for 64 clocks after a data write; other writes are kept in `writes`."""

    def __init__(self, board, irq_cb):
        self.b = board
        self.irq_cb = irq_cb
        self.addr = 0
        self.regs = bytearray(256)
        self.status = 0
        self.irq_state = False
        self.running = [False, False]
        self.timer = [board.new_timer(lambda: self.expired(0)), board.new_timer(lambda: self.expired(1))]
        self.busy_end = 0
        self.writes = []

    def read_status(self):
        st = self.status & 3
        if self.b.now() < self.busy_end:
            st |= 0x80
        return st

    def write(self, port, v):
        if port == 0:
            self.addr = v
            return
        r = self.addr
        if r == 0x14:
            self.b.synchronize(lambda: self.mode_write(v))
        else:
            self.regs[r] = v
            if r not in (0x10, 0x11, 0x12):
                self.writes.append((self.b.now(), r, v))
        self.busy_end = self.b.now() + 64 * YM_AS

    def mode_write(self, v):
        self.regs[0x14] = v
        self.set_reset_status(0, ((v >> 4) & 1) | (((v >> 5) & 1) << 1))
        total = (self.b.now() * YM_RATE) // AS + 1       # samples made by the stream update before the write
        self.update_timer(1, v & 2, -(total & 15))
        self.update_timer(0, v & 1, 0)

    def update_timer(self, t, enable, delta):
        if enable and not self.running[t]:
            period = (1024 - ((self.regs[0x10] << 2) | (self.regs[0x11] & 3))) if t == 0 else 16 * (256 - self.regs[0x12])
            self.b.adjust(self.timer[t], self.b.now() + (period + delta) * 64 * YM_AS)
            self.running[t] = True
        elif not enable:
            self.b.cancel(self.timer[t])
            self.running[t] = False

    def expired(self, t):
        if self.regs[0x14] & (4 << t):
            self.set_reset_status(1 << t, 0)
        self.running[t] = False
        self.update_timer(t, 1, 0)

    def set_reset_status(self, set_, reset):
        self.status = (self.status | set_) & ~reset
        if self.b.executing is not None:
            self.b.synchronize(self.check_interrupts)
        else:
            self.check_interrupts()

    def check_interrupts(self):
        old = self.irq_state
        self.irq_state = bool(self.status & 3)
        if old != self.irq_state:
            self.irq_cb(self.irq_state)


class Exec:
    """A CPU in the scheduler.  core protocol: run(n) -> cycles executed (stops at the first instruction boundary at
    or past n; an interrupt is taken at an instruction boundary as the core's MAME original does), executed() ->
    cycles done so far in this run as MAME's icount shows them at a bus access (machine().time()), abort() -> stop
    after the current instruction, set_line(line, state), reset()."""

    def __init__(self, name, core, hz):
        self.name = name
        self.core = core
        self.as_per_cycle = AS // hz                # HZ_TO_ATTOSECONDS(cycles per second)
        self.shift = 0                              # divu_64x32(delta >> divshift, divisor) (diexec.cpp)
        while (self.as_per_cycle >> self.shift) >= 1 << 31:
            self.shift += 1
        self.div = self.as_per_cycle >> self.shift
        self.local = 0
        self.suspended = False                    # held in reset: eats its cycles
        self.queues = {}


class M72:
    def __init__(self, game, regions=None, cpus=True):
        self.game = game
        info = GAMES[game]
        self.info = info
        r = regions or load_regions(game)
        self.rom = bytes(r["main"])
        self.mcu_rom = bytes(r["mcu"])
        self.samples = bytes(r["samples"])
        self.rom_end = info["rom_end"]
        self.ram_base = info["ram"]
        self.ram = bytearray(0x4000)
        self.spriteram = bytearray(0x400)
        self.spritebuf = bytearray(0x400)          # BUFFERED_SPRITERAM16: what the picture shows
        self.palette = [bytearray(0xC00), bytearray(0xC00)]   # as words (little endian), A9 folded
        self.videoram = [bytearray(0x4000), bytearray(0x4000)]
        self.soundram = bytearray(0x10000)
        self.dpram = bytearray(0x1000)             # MB8421/MB8431: 0x800 words, little endian
        self.scrollx = [0, 0]
        self.scrolly = [0, 0]
        self.raster_line = 0
        self.video_off = 0
        self.flip = 0
        self.port02 = 0
        self.in0 = 0xFFFF
        self.in1 = 0xFFFF
        self.dsw = info["dsw"]
        self.video_writes = []                     # (line, what, value) this frame: the picture's raster splits
        self.bands, self.drawn = [], -1            # MAME's partial updates: [(first line, last line, VideoState)]
        self.frame_bands = []                      # the last finished picture's bands (m72.Video.render_rgb)
        self.dac = []                              # (attotime, value): mrheli's MCU port 1
        self.mcu_sample_addr = 0
        self.frame = 0
        # the scheduler
        self.base = 0
        self.timers = []                           # sorted by (expire, seq)
        self.seq = 0
        self.executing = None
        self.cb_time = None
        self.execs = []
        self.order = []
        self.quanta = [[QUANTUM_60, None]]         # [requested, expire] sorted by requested
        self.stop = False
        if cpus:
            self.make_cpus()

    # ---- the scheduler ----------------------------------------------------
    def now(self):
        e = self.executing
        if e is None:
            return self.base if self.cb_time is None else self.cb_time
        return e.local + e.core.executed() * e.as_per_cycle

    def new_timer(self, fn):
        return Timer(fn)

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

    def synchronize(self, fn):
        return self.timer_at(self.now(), fn)

    def add_quantum(self, quantum, duration):
        expire = self.base + duration
        q = [x for x in self.quanta if x[1] is None or x[1] > self.base]
        k = 0
        while k < len(q) and q[k][0] <= quantum:
            k += 1
        if k and q[k - 1][0] == quantum:
            q[k - 1][1] = expire if q[k - 1][1] is not None else None
        else:
            q.insert(k, [quantum, expire])
        self.quanta = q

    def rebuild(self):
        """rebuild_execute_list: the running CPUs in device order, then the suspended ones (which still eat their
        cycles and can lower a slice's target)"""
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
                    e.suspended = True
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
            target = self.base + self.quanta[0][0]
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
            self.cb_time = t.expire                # time() in a callback: the timer's expiry (schedule.cpp)
            t.fn()
        self.cb_time = None

    # ---- the CPUs ---------------------------------------------------------
    def make_cpus(self):
        from v30 import V30
        from z80mame import Z80Mame
        self.pic = PIC8259(self, lambda s: self.set_line(self.main, "irq", s))
        self.soundirq = RstNegBuffer(self, lambda s: self.set_line(self.sound, "irq", s))
        self.soundlatch = Latch(self, lambda s: self.soundirq.input(s, 0x20))
        self.ym = YM2151(self, lambda s: self.soundirq.input(s, 0x10))
        main = V30Exec(V30(self.main_rd, self.main_wr, self.io_rd, self.io_wr, self.pic.acknowledge,
                           wr16=self.main_wr16, io_wr16=self.io_wr16))
        sound = Z80Exec(Z80Mame(self.snd_rd, self.snd_wr, self.snd_in, self.snd_out, self.soundirq.vector))
        self.main = Exec("maincpu", main, MAIN_HZ)
        self.sound = Exec("soundcpu", sound, SOUND_HZ)
        self.execs = [self.main, self.sound]
        if self.info["mcu"]:
            from i8051 import I8051
            self.soundlatch2 = Latch(self, lambda s: self.set_line(self.sound, "nmi", s))
            self.mculatch = Latch(self, lambda s: self.set_line(self.mcu, "int1", s))
            self.mcu = Exec("mcu", I8051Exec(I8051(self.mcu_rom, self.mcu_data_rd, self.mcu_data_wr,
                                                   port_out=self.mcu_port_out)), (MCU_HZ + 11) // 12)
            self.execs.append(self.mcu)
        # machine_reset: the sound CPU waits in reset for its program; the line timer starts at line 0
        self.sound.suspended = True
        self.rebuild()
        self.line_timer = self.new_timer(None)
        self.line_timer.fn = lambda: self.scanline(0)
        self.adjust(self.line_timer, self.time_until_line(0))
        self.synchronize(lambda: self.add_quantum(QUANTUM_SYNC, QUANTUM_SYNC_FOR))
        self.vblank_timer = self.timer_at(FRAME_AS, self.vblank_begin)
        self.timer_at(SOUND_UPDATE_AS, self.sound_update)

    def sound_update(self):
        self.timer_at(self.base + SOUND_UPDATE_AS, self.sound_update)

    def time_until_line(self, line):
        """screen_device::time_until_pos(line, 0) from now; at time 0 the beam is at the blank's start"""
        now = self.base
        pos = (now + VBSTART * SCAN_AS) % FRAME_AS
        want = line * SCAN_AS
        d = (want - pos) % FRAME_AS
        if d == 0:
            d = FRAME_AS
        return now + d

    def vpos(self):
        """screen_device::vpos(): rounded to the nearest pixel"""
        return int(((self.now() % FRAME_AS + (AS // PIXEL_HZ) // 2) // SCAN_AS + VBSTART) % VTOTAL)

    def scanline(self, line):
        if line == self.raster_line:
            self.video_writes.append((line, "raster", 0))
            self.partial_update(line)
            self.pic.set_irq_line(2, 1)
        else:
            self.pic.set_irq_line(2, 0)
        self.pic.set_irq_line(0, 1 if line == VBSTART else 0)
        nxt = line + 1 if line + 1 < VTOTAL else 0
        self.line_timer.fn = lambda: self.scanline(nxt)
        self.adjust(self.line_timer, self.time_until_line(nxt))

    def partial_update(self, line):
        """screen.update_partial(line): the lines since the last update are drawn with the state of now"""
        if self.drawn < line <= VBSTART - 1:
            self.bands.append((self.drawn + 1, line, self.video_state()))
            self.drawn = line

    def vblank_begin(self):
        """screen frame_update (the rest of the picture is drawn, `frame_bands`); MAME's Lua frame_done runs here
        (run_frame returns)"""
        self.partial_update(VBSTART - 1)
        self.frame_bands, self.bands, self.drawn = self.bands, [], -1
        self.timer_at(self.base + FRAME_AS, self.vblank_begin)
        self.stop = True

    def run_frame(self):
        self.video_writes = []
        self.stop = False
        while not self.stop:
            self.timeslice()
        self.frame += 1

    # ---- the main CPU's buses ---------------------------------------------
    def main_rd(self, a):
        a &= 0xFFFFF
        if a < self.rom_end:
            return self.rom[a]
        r = a - self.ram_base
        if 0 <= r < 0x4000:
            return self.ram[r]
        if 0xC0000 <= a < 0xC0400:
            return self.spriteram[a - 0xC0000]
        if 0xC8000 <= a < 0xC8C00 or 0xCC000 <= a < 0xCCC00:
            p = self.palette[(a >> 14) & 1]
            o = (a & 0xFFF) & ~0x200
            return (p[o] | 0xE0) if not (o & 1) else 0xFF
        if 0xD0000 <= a < 0xD4000:
            return self.videoram[0][a - 0xD0000]
        if 0xD8000 <= a < 0xDC000:
            return self.videoram[1][a - 0xD8000]
        if 0xE0000 <= a < 0xF0000:
            return self.soundram[a - 0xE0000]
        if a >= 0xFFFF0:
            return self.rom[a]
        if self.info["mcu"] and 0xB0000 <= a < 0xB1000:
            return self.dpram_left_r(a - 0xB0000)
        return 0                                   # (unmapped: MAME reads 0)

    def main_wr(self, a, v):
        a &= 0xFFFFF
        r = a - self.ram_base
        if 0 <= r < 0x4000:
            self.ram[r] = v
        elif 0xC0000 <= a < 0xC0400:
            self.spriteram[a - 0xC0000] = v
        elif 0xC8000 <= a < 0xC8C00 or 0xCC000 <= a < 0xCCC00:
            self.palette[(a >> 14) & 1][(a & 0xFFF) & ~0x200] = v
        elif 0xD0000 <= a < 0xD4000:
            self.videoram[0][a - 0xD0000] = v
        elif 0xD8000 <= a < 0xDC000:
            self.videoram[1][a - 0xD8000] = v
        elif 0xE0000 <= a < 0xF0000:
            self.soundram[a - 0xE0000] = v
        elif self.info["mcu"] and 0xB0000 <= a < 0xB1000:
            o = a - 0xB0000
            self.synchronize(lambda: self.dpram_left_w(o & ~1, v << 8 * (o & 1), 0xFF << 8 * (o & 1)))

    def main_wr16(self, a, v):
        """a word write: one bus cycle at an even address (MAME calls a 16-bit handler once), two byte cycles at
        an odd one"""
        a &= 0xFFFFF
        if a & 1:
            self.main_wr(a, v & 0xFF)
            self.main_wr((a + 1) & 0xFFFFF, v >> 8)
        elif self.info["mcu"] and 0xB0000 <= a < 0xB1000:
            o = a - 0xB0000
            self.synchronize(lambda: self.dpram_left_w(o, v, 0xFFFF))
        else:
            self.main_wr(a, v & 0xFF)
            self.main_wr(a + 1, v >> 8)

    def io_rd(self, p):
        p &= 0xFF
        if p < 6:
            v = (self.in0, self.in1, self.dsw)[p >> 1]
            return (v >> 8) & 0xFF if p & 1 else v & 0xFF
        if p in (0x40, 0x42):
            return self.pic.read(1 if p & 2 else 0)
        return 0

    def io_wr(self, p, v):
        p &= 0xFF
        self.io_write(p & ~1, v << 8 * (p & 1), 0xFF << 8 * (p & 1))

    def io_wr16(self, p, v):
        p &= 0xFF
        if p & 1:
            self.io_wr(p, v & 0xFF)
            self.io_wr((p + 1) & 0xFF, v >> 8)
        else:
            self.io_write(p, v, 0xFFFF)

    def io_write(self, p, data, mask):
        """one bus cycle to the word at even port p: data in its lanes, mask the lanes written (MAME's handlers)"""
        lo = mask & 0xFF
        if p == 0x00:
            if lo:
                self.soundlatch.write(data & 0xFF)
        elif p == 0x02:
            if lo:
                v = data & 0xFF
                self.port02 = v
                self.flip = ((v >> 2) & 1) ^ ((~self.dsw >> 8) & 1)
                self.video_off = (v >> 3) & 1
                self.set_line(self.sound, "reset", 0 if v & 0x10 else 1)
        elif p == 0x04:
            if lo:
                self.spritebuf[:] = self.spriteram
        elif p == 0x06:                                   # irq_line_w(data): the word as written, no COMBINE
            self.raster_line = (data & 0x1FF) - 128
            self.pic.set_irq_line(2, 0)
            self.video_writes.append((self.vpos(), "iset", data))
        elif p in (0x40, 0x42):
            if lo:
                self.pic.write(1 if p & 2 else 0, data & 0xFF)
        elif 0x80 <= p < 0x88:
            layer, xy = (p >> 2) & 1, (p >> 1) & 1
            regs = self.scrollx if xy else self.scrolly
            regs[layer] = (regs[layer] & ~mask) | (data & mask)
            self.video_writes.append((self.vpos(), ("sx%d" if xy else "sy%d") % layer, regs[layer]))
        elif p == 0xC0 and self.info["mcu"]:
            if lo:
                self.soundlatch2.write(data & 0xFF)

    # ---- the dual-port RAM (mrheli) -----------------------------------------
    def dpram_left_r(self, o):
        if (o >> 1) == 0x7FE:                      # INT_ADDR_LEFT read: clears INTL (not connected)
            pass
        return self.dpram[o]

    def dpram_left_w(self, o, data, mask):
        """delayed_ram16_w -> left_w(offset, data, mask): COMBINE_DATA on the word at even byte offset o"""
        if mask & 0xFF:
            self.dpram[o] = data & 0xFF
        if mask & 0xFF00:
            self.dpram[o + 1] = data >> 8
        if (o >> 1) == 0x7FF:                      # the right side's mailbox: INTR -> MCU INT0
            self.set_line(self.mcu, "int0", 1)

    def mcu_data_rd(self, a):
        if a == 0:
            v = self.samples[self.mcu_sample_addr & 0xFFFF]
            self.mcu_sample_addr += 1
            return v
        if a == 2:
            return self.mculatch.value
        if 0xC000 <= a < 0xD000:
            o = a - 0xC000
            if (o >> 1) == 0x7FF:                  # INT_ADDR_RIGHT read: clears INTR
                self.set_line(self.mcu, "int0", 0)
            return self.dpram[o]
        return 0xFF

    def mcu_data_wr(self, a, v):
        if a == 0:
            self.mcu_sample_addr = (self.mcu_sample_addr & 0xFFE000) | (v << 5)
        elif a == 1:
            self.mcu_sample_addr = (self.mcu_sample_addr & 0x1FFF) | (v << 13)
        elif a == 2:
            self.mculatch.acknowledge()
        elif 0xC000 <= a < 0xD000:
            o = a - 0xC000
            self.synchronize(lambda: self._dpram_right_w(o, v))

    def _dpram_right_w(self, o, v):
        self.dpram[o] = v                          # (INTL, the main side's mailbox, is not connected)

    def mcu_port_out(self, port, v):
        if port == 1:
            self.dac.append((self.now(), v))

    # ---- the sound CPU ----------------------------------------------------
    def snd_rd(self, a):
        return self.soundram[a & 0xFFFF]

    def snd_wr(self, a, v):
        self.soundram[a & 0xFFFF] = v

    def snd_in(self, p):
        p &= 0xFF
        if p in (0, 1):
            return self.ym.read_status() if p == 1 else 0xFF
        if p == 0x02:
            return self.soundlatch.value
        if p == 0x84 and self.info["mcu"]:
            self.soundlatch2.set_written(False)           # (no separate acknowledge: a read clears the NMI)
            return self.soundlatch2.value
        return 0xFF

    def snd_out(self, p, v):
        p &= 0xFF
        if p in (0, 1):
            self.ym.write(p, v)
        elif p == 0x06:
            self.soundlatch.acknowledge()
        elif p == 0x82 and self.info["mcu"]:
            self.mculatch.write(v)

    # ---- for the renderer ---------------------------------------------------
    def video_state(self):
        from m72 import VideoState
        return VideoState(self.videoram[0], self.videoram[1], self.spritebuf, self.scrollx, self.scrolly,
                          bool(self.video_off))


class V30Exec:
    """engine/v30.py in the scheduler's protocol (see Exec).  MAME sets icount = the slice at its start (the overshoot
    is already in the CPU's local time), so icount is zeroed before each run; executed() is MAME's
    cycles_running - icount.  abort_timeslice takes the rest out of icount and counts it as stolen: the core's step
    (start - icount) would count it as executed, so it comes off the cycle counter again."""

    def __init__(self, cpu):
        self.cpu = cpu
        self.n = 0
        self.stolen = 0
        cpu.reset()

    def run(self, n):
        c = self.cpu
        c.icount = 0
        self.n = n
        self.stolen = 0
        ran = c.run(n) - self.stolen
        c.cycles -= self.stolen
        return ran

    def executed(self):
        return self.n - self.cpu.icount

    def abort(self):
        c = self.cpu
        if c.icount > 0:
            self.n -= c.icount
            self.stolen += c.icount
            c.icount = 0

    def set_line(self, line, state):
        if line == "irq":
            self.cpu.irq_line = bool(state)
        elif line == "nmi":
            self.cpu.set_nmi(state)

    def reset(self):
        self.cpu.reset()


class I8051Exec(V30Exec):
    """engine/i8051.py likewise (machine cycles; lines INT0/INT1; its cycle counter counts instructions, so nothing
    is stolen from it)"""

    def __init__(self, cpu):
        self.cpu = cpu
        self.n = 0
        self.stolen = 0
        cpu.reset()

    def run(self, n):
        self.cpu.icount = 0
        self.n = n
        return self.cpu.run(n)

    def set_line(self, line, state):
        self.cpu.set_input_line({"int0": self.cpu.INT0_LINE, "int1": self.cpu.INT1_LINE}[line], bool(state))


class Z80Exec:
    """engine/z80mame.py (MAME's Z80, resumable mid-instruction) in the scheduler's protocol.  The interrupt
    acknowledge reads the RST_NEG_BUFFER's vector (IM 0 runs it as an RST).  total: MAME's totalcycles (zeroed by
    the reset: device_execute_interface::interface_pre_reset); an NMI edge at total 0 is not taken (execute_set_input).
    abort_timeslice: the core swallows its remaining cycles (cycles_stolen), they are not counted as run."""

    def __init__(self, cpu):
        self.cpu = cpu
        self.total = 0

    def run(self, n):
        ran = self.cpu.run(n)
        self.total += ran
        return ran

    def executed(self):
        return self.cpu.executed()

    def total_cycles(self):
        return self.total

    def abort(self):
        self.cpu.abort()

    def set_line(self, line, state):
        self.cpu.set_input(line, state, self.total)

    def reset(self):
        self.cpu.reset()
        self.total = 0
