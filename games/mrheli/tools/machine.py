"""Mr. HELI no Daibouken (MAME `mrheli`, Irem M72 with the i8751 MCU, 1987; a clone of `bchopper`): the reference
board.  The video is engine/m72.py (shared with R-Type); the board logic comes here later.

Main CPU: NEC V30 (8 MHz), uPD71059C interrupts (IR0 VBLANK at line 256, IR2 the raster line), the same screen as
R-Type (384 x 256 visible, 55.017 Hz).  Sound: a Z80 with a YM2151 and a DAC fed by the i8751 MCU (samples ROM).

Memory map (main CPU; m72_protected_map = m72_map + the MCU's dual-port RAM):
    $00000-$7FFFF  ROM (c-l0/h0 at $00000, c-l1/h1 at $20000, c-l3/h3 at $60000 and again at $E0000)
    $A0000-$A3FFF  work RAM            $B0000-$B0FFF MB8421 dual-port RAM shared with the i8751 (writes delayed to a
                                                     scheduler sync)
    $C0000-$C03FF  sprite RAM          $C8000-$C8BFF palette 0 (sprites)   $CC000-$CCBFF palette 1 (tiles)
    $D0000-$D3FFF  FG video RAM        $D8000-$DBFFF BG video RAM           $E0000-$EFFFF sound CPU RAM window
Ports: as R-Type ($00-$07, $40-$43, $80-$87) plus $C0 the second sound latch (NMI to the Z80).

The status panel is at the top: the VBLANK handler sets FG scroll x $1C0, y $180 (the panel's map rows) and raster
line 31; at line 31 the raster interrupt loads the playfield's FG scroll, and on some stages (the cave) re-programs
the raster line for a second FG y split lower down (three bands, FG y + 128 at the second cut).  The BG scroll is the
same in all bands (the panel's tiles are opaque over it).

Horizontal layout (MAME snapshots): the panel (lines 0-31) uses the full width: row 1 "1P-" score ~x 8-90, "HI-"
~110-200, "2P-" ~210-290, "TIME" ~300-380; row 2 lives ~5-40, ENERGY ~45-200, MONEY ~220-360. The playfield is x
0-383 too. A 320-pixel STE window cuts the panel's edges: TIME or the 1P score.  The user's choice (2026-10-12): always
the centred window, x 32-351 (MAME bitmap x 96-415), as for R-Type: "1P-" and the lives icon are cut, TIME stays
readable (its last digit cut), MONEY whole; the panel is not rearranged.
"""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "engine"))
from m72 import Video as M72Video, VideoState, pens, bands  # noqa: F401


class Video(M72Video):
    def __init__(self):
        super().__init__("mrheli")


# ---- the port's schedule (the translation's lock-step reference: tools/logic_test.py) ----
from m72board import M72, VTOTAL  # noqa: E402

START = 500                       # the port starts from the board's state at this frame (the boot is not translated:
#                                   the ROM / RAM tests and the code the MCU puts into the dual-port RAM, B000:xxxx, end
#                                   near frame 490; from then on the main CPU reads the dual-port RAM only at 0040:7F20
#                                   - "IREM CORPORATION 1987" at B0900, the MCU's - and increments the MCU's mailbox
#                                   byte B0FFE in the VBL handler)
IDLE = (0x0040, 0x01F2)           # the main loop's head: mov bp,3712h; call [bp]; the queue [27C0] / [27C2]
VBL_VECTOR, RASTER_VECTOR = 0x20, 0x22
IDLE_TASK = 0x3323                # [3712] while nothing runs in the foreground (0040:3323: [3710] = 0 -> it stays)
RAM = 0xA0000
DPRAM = 0xB0000


MCU_FRAME = 145408 / 12            # (the i8751's machine cycles an arcade frame: 8 MHz / 12 against the V30's 8 MHz)


class MrHeli(M72):
    """The board (MAME's schedule) to START; then the port's schedule: no sound CPU, no PIC, no time.  A port
    frame: the VBL interrupt (vector $20) taken at the idle point, the handler (the game's logic) and the foreground
    until the idle point again; then the raster interrupt (vector $22: the playfield's FG scroll after the top panel)
    the same - and again while the raster handler moves the raster line further down the same frame (the cave's
    second FG split: [293A] bit 15 clear, 0040:033A).  The idle point: the main loop's head with the foreground queue
    empty, the idle task in [3712] and the busy flag [27C4] clear.  Writes to the ports go to `port_writes` ((port,
    value, width) this frame); the scroll, raster line and sprite DMA act as on the board, port 02 sets port02 / flip
    / video_off only (no sound CPU reset).  The dual-port RAM: both sides' writes land at once.  The i8751 (the real
    program on engine/i8051.py) runs an arcade frame's machine cycles after the main CPU's frame: the main CPU's
    mailbox write (B0FFE, the VBL handler) raises its INT0 at once (its read of CFFE clears it); each port C0 write
    of the frame (the Z80 hands it on to the MCU's latch on the board: port 82, INT1) goes to its latch in turn, the
    MCU running until it acknowledges.  Its effects the main CPU sees: command $10's copy of the protection code to
    B0000 (called at B000:0000 a frame later), the wipe three timer ticks later, the watchdog byte B0FFC."""

    def __init__(self, **kw):
        super().__init__("mrheli", **kw)
        self.port_frames = 0
        self.port_writes = []
        self.irq_psw_addr = None
        self.mailbox = 0
        self.rasters = 0                     # (raster interrupts run in the last port frame)
        self.mcu_cmds = []                   # (this frame's port C0 writes, for the MCU's latch)
        self.mcu_budget = 0.0

    def word(self, o):
        return self.ram[o] | (self.ram[o + 1] << 8)

    def idle(self):
        c = self.main.core.cpu
        return ((c.cs, c.ip) == IDLE and self.word(0x27C0) == self.word(0x27C2) and self.word(0x3712) == IDLE_TASK
                and self.word(0x27C4) == 0 and c.sr[3] == 0xA000 and c.sr[2] == 0xA000)

    def boot(self, frames=START):
        while self.frame < frames:
            self.run_frame()
        c = self.main.core.cpu
        for _ in range(2000):
            if self.idle():
                break
            c.step()
        if not self.idle():
            raise RuntimeError("main CPU not idle at frame %d (%04X:%04X)" % (self.frame, c.cs, c.ip))
        self.port_mode()

    def port_mode(self):
        c = self.main.core.cpu
        c.rd_op = c.rd
        c.io_wr = self.port_wr
        c.io_wr16 = self.port_wr16
        c.wr = self.port_mem_wr
        c.wr16 = self.port_mem_wr16
        c.icount = 1 << 40                               # (steps without a slice)
        u = self.mcu.core.cpu
        u.rd_data = self.port_mcu_rd
        u.wr_data = self.port_mcu_wr
        u.port_out = lambda port, v: None

    def port_mcu_rd(self, a):
        if a == 0:
            v = self.samples[self.mcu_sample_addr & 0xFFFF]
            self.mcu_sample_addr += 1
            return v
        if a == 2:
            return self.mculatch.value
        if 0xC000 <= a < 0xD000:
            o = a - 0xC000
            if (o >> 1) == 0x7FF:                  # INT_ADDR_RIGHT read: clears INTR
                self.mcu.core.cpu.set_input_line(0, False)
            return self.dpram[o]
        return 0xFF

    def port_mcu_wr(self, a, v):
        if a == 0:
            self.mcu_sample_addr = (self.mcu_sample_addr & 0xFFE000) | (v << 5)
        elif a == 1:
            self.mcu_sample_addr = (self.mcu_sample_addr & 0x1FFF) | (v << 13)
        elif a == 2:
            self.mculatch.written = False
            self.mcu.core.cpu.set_input_line(1, False)
        elif 0xC000 <= a < 0xD000:
            self.dpram[a - 0xC000] = v

    def run_mcu(self):
        """the MCU's share of the frame: the commands in turn, then the rest of the frame's machine cycles"""
        u = self.mcu.core.cpu
        self.mcu_budget += MCU_FRAME
        for v in self.mcu_cmds:
            self.mculatch.value = v
            self.mculatch.written = True
            u.set_input_line(1, True)
            for _ in range(64):
                self.mcu_budget -= u.run(32)
                if not self.mculatch.written:
                    break
        self.mcu_cmds = []
        n = int(self.mcu_budget)
        if n > 0:
            self.mcu_budget -= u.run(n)

    STATE = ("ram", "dpram", "spriteram", "spritebuf", "palette", "videoram", "scrollx", "scrolly", "raster_line",
             "video_off", "flip", "port02", "in0", "in1", "dsw", "frame", "port_frames", "mailbox", "mcu_sample_addr",
             "mcu_budget")

    def save(self, path, extra=None):
        """the port's state (memories, ports, the V30's registers: everything run_frame_port uses) -> zlib(pickle)"""
        import pickle
        import zlib
        c = self.main.core.cpu
        cpu = {k: (list(v) if isinstance(v, list) else v) for k, v in vars(c).items()
               if isinstance(v, (int, bool, list)) and k != "ops"}
        u = self.mcu.core.cpu
        mcu = {k: (list(v) if isinstance(v, list) else v) for k, v in vars(u).items()
               if isinstance(v, (int, bool, list, bytearray)) and k != "insn"}
        st = dict(board={k: getattr(self, k) for k in self.STATE}, cpu=cpu, mcu=mcu, extra=extra,
                  latch=(self.mculatch.value, self.mculatch.written))
        Path(path).write_bytes(zlib.compress(pickle.dumps(st), 6))

    @classmethod
    def load(cls, path):
        """a machine in the port's schedule from save()'s file (no boot) -> (machine, extra)"""
        import copy
        import pickle
        import zlib
        st = pickle.loads(zlib.decompress(Path(path).read_bytes()))
        m = cls()
        for k, v in st["board"].items():
            setattr(m, k, copy.deepcopy(v))
        c = m.main.core.cpu
        for k, v in st["cpu"].items():
            setattr(c, k, v)
        u = m.mcu.core.cpu
        for k, v in st["mcu"].items():
            setattr(u, k, copy.deepcopy(v))
        m.mculatch.value, m.mculatch.written = st["latch"]
        m.port_mode()
        return m, st["extra"]

    def port_mem_wr(self, a, v):
        a &= 0xFFFFF
        if DPRAM <= a < DPRAM + 0x1000:
            o = a - DPRAM
            self.dpram[o] = v
            if o >> 1 == 0x7FF:
                self.mailbox += 1
                self.mcu.core.cpu.set_input_line(0, True)
        else:
            self.main_wr(a, v)

    def port_mem_wr16(self, a, v):
        a &= 0xFFFFF
        if a & 1 or not DPRAM <= a < DPRAM + 0x1000:
            if a & 1:
                self.port_mem_wr(a, v & 0xFF)
                self.port_mem_wr((a + 1) & 0xFFFFF, v >> 8)
            else:
                self.main_wr16(a, v)
            return
        self.port_mem_wr(a, v & 0xFF)
        self.port_mem_wr(a + 1, v >> 8)

    def port_wr(self, p, v):
        self.port_writes.append((p & 0xFF, v, 1))
        self.port_io(p & 0xFF, v << 8 * (p & 1), 0xFF << 8 * (p & 1))

    def port_wr16(self, p, v):
        self.port_writes.append((p & 0xFF, v, 2))
        p &= 0xFF
        if p & 1:
            self.port_io(p, v & 0xFF, 0xFF << 8)
            self.port_io((p + 1) & 0xFF, (v >> 8), 0xFF)
        else:
            self.port_io(p, v, 0xFFFF)

    def port_io(self, p, data, mask):
        p &= 0xFE
        if p == 0xC0 and mask & 0xFF:
            self.mcu_cmds.append(data & 0xFF)            # (the MCU's latch through the Z80: run_mcu)
        if p in (0x00, 0xC0):
            return                                       # (the sound latches: port_writes)
        if p == 0x02:
            if mask & 0xFF:
                v = data & 0xFF
                self.port02 = v
                self.flip = ((v >> 2) & 1) ^ ((~self.dsw >> 8) & 1)
                self.video_off = (v >> 3) & 1
            return
        self.io_write(p, data, mask)

    def run_irq(self, vector, limit=5000000):
        """the interrupt at the idle point, then until the idle point again"""
        c = self.main.core.cpu
        self.irq_psw_addr = (c.ss << 4) + ((c.sp - 2) & 0xFFFF)
        c.interrupt(vector)
        for _ in range(limit):
            c.step()
            if self.idle():
                return
        raise RuntimeError("the main CPU did not come back to its idle point (%04X:%04X)" % (c.cs, c.ip))

    def run_frame_port(self):
        self.port_writes = []
        self.run_irq(VBL_VECTOR)
        self.rasters = 0
        last = -1
        while last < self.raster_line < VTOTAL and self.rasters < 4:
            last = self.raster_line
            self.run_irq(RASTER_VECTOR)
            self.rasters += 1
        self.run_mcu()
        self.port_frames += 1
