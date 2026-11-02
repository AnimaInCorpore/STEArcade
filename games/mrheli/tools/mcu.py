"""Mr. HELI's i8751 MCU (mh_c-pr-.ic1, 4 KB) after the boot as a native model: the twin of src/mcu.s.

The program (engine/i8051dis.py; the interface and the boot in docs/mcu-interface.md, "The MCU (agent B)"):
  boot (frames 0-483 of a power-on, timing-bound, not modelled): the RAM tests, then the V30 runs test and start
    code that the MCU writes into the dual-port RAM at $B0000 at offsets $58 = TL1 & $7F (the free-running timer 1 at
    the moment the MCU saw the V30's counter $B07FE change), the letters S A M O T O at $B07F7; then 16 copies of
    ROM $002F-$006E ("IREM CORPORATION 1987" ...) to $B0800-$B0BFF, $B0000-$B001F wiped ($20 $1F ... $01) and the
    main loop (02B1) entered with $58 = 0.
  main loop (what this model does):
    - INT1 (the sound CPU's latch, port 82, the value the V30 wrote to port C0 one or two lines earlier): commands
      $10 and $11 go to a ring for the main loop, any other value n starts a sample (0557, table $006F + 4n):
      entry[0] bits 0-6 the priority (lower wins), bit 7 = restart on the same priority; entry[1] + $AD the timer 1
      reload (a sample byte every 256 - reload machine cycles); entry[2] bits 4-7 the volume, bits 0-3 the sample
      address bits 13-16; entry[3] address bits 5-12.  Taken when the priority is below the playing one's (r3 of
      bank 1, $FF when idle) or equal with bit 7.
    - timer 1 (05C1): a sample byte a tick to port 1 (the DAC), scaled by the volume; the byte 0 ends it: P1 = $80,
      timer 1 stopped, r3 = $FF.
    - command $10 (02C8): ROM $0C3F-$0C5D (31 bytes: the V30's protection check, called at $B000:0000 by the V30's
      022D9 after it wrote $10 to port C0) to $B0000 + $58 = $B0000, then $5B = 3.
    - timer 0 (04F5), every 12118 machine cycles + the handler's latency (1.0013 frames): $5B counts down to 0
      ($FF = off); the main loop then wipes $B0000-$B001F again ($20 ... $01) and sets $5B = $FF.  The watchdog: $5D
      counts the V30's writes to the last word ($B0FFE/F, the V30 increments $B0FFE in its VBL handler); a tick
      with exactly one resets $44, else $44 + 1; at $44 >= $1E the MCU writes $44 to $B0FFC for ever (dead, no
      more samples).
    - command $11 (043E): the ROM test answer: 12 bytes from ROM $0907 and the ROM's 16-bit sum + ROM[$0C5E] at
      $B0FE0-$B0FED, 65721 cycles (5.4 frames, interrupts off) after the latch; then the MCU stops in 045E,
      samples only.  The model writes the answer at the frame boundary after that.
The V30 sees only the dual-port RAM: plain RAM but for the writes above.  So the model runs per arcade frame (one
timer 0 tick a frame) and at the V30's port C0 writes; time is in units of 1/3 machine cycle (an arcade frame is
145408 V30 cycles = 36352 units, a line 128) from the model's frame starts (the board's frame end: line 256).

    m = MCU.from_board(board)   # at a frame boundary after the boot (board.frame >= BOOT_END)
    m.frame()                   # at each frame boundary (before the V30's VBL handler)
    m.v30_write(o, n)           # the V30 wrote n bytes at dual-port offset o (only o >= $FFE matters: heartbeat)
    m.command(v, t)             # the V30 wrote v to port C0 at units t into the frame
    m.state_image()             # the bytes of src/mcu.s's mcu_state (for snapshots)

    venv/bin/python games/mrheli/tools/mcu.py --tables   # build/mrheli/mcu_tables.s for src/mcu.s
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "engine"))

UNITS_FRAME = 36352           # 145408 V30 cycles / 4
UNITS_LINE = 128
CMD_LAG = 2 * UNITS_LINE      # port C0 -> sound CPU NMI -> port 82 -> INT1 -> the sample's timer started (measured)
BOOT_END = 484                # the first frame boundary with the MCU in its main loop (power-on, no inputs)
WIPE = bytes(range(0x20, 0, -1))
TABLE = 0x006F                # sample commands
CHECK = 0x0C3F                # command $10's code
ST_IDLE, ST_ROMTEST, ST_DEAD, ST_ROMSUM = 0, 1, 2, 3
ROMTEST_UNITS = 3 * 65721     # latch read -> the answer's first byte (the sum loop, interrupts off: measured)


def rom_answer(rom):
    """command $11: the bytes at $FE0-$FED"""
    s = sum(rom[:0x1000]) & 0xFFFF
    lo = (s & 0xFF) + rom[0x0C5F]
    hi = ((s >> 8) + rom[0x0C5E] + (lo >> 8)) & 0xFF
    return bytes(rom[0x0907:0x0913]) + bytes([lo & 0xFF, hi])


def sample_entry(rom, n):
    """(priority, restart, period in machine cycles, volume, address) of sample command n"""
    e = [rom[TABLE + ((4 * n + k) & 0xFF)] for k in range(4)]
    reload = (e[1] + 0xAD) & 0xFF
    return e[0] & 0x7F, bool(e[0] & 0x80), 256 - reload, e[2] & 0xF0, ((e[2] & 0x0F) << 13) | (e[3] << 5)


def sample_bytes(samples, addr):
    """the bytes a sample plays (up to its 0)"""
    out = bytearray()
    while True:
        v = samples[addr & 0xFFFF]
        addr += 1
        if v == 0:
            return bytes(out)
        out.append(v)


def dac_value(v, vol):
    """timer 1's handler: the sample byte v (> 0) scaled by vol -> port 1"""
    neg = v < 0x80
    mag = (0x80 - v) if neg else (v - 0x80)
    if vol:
        sc = (mag * vol + 0x80) >> 8
        if vol >= 0x80:
            mag = sc
        else:
            mag = sc + mag
            if mag >= 0x80:
                mag = 0x7F
    mag &= 0xFF
    if neg:
        mag = (-mag) & 0xFF
    return (mag + 0x80) & 0xFF


class MCU:
    def __init__(self, rom, samples, dpram):
        self.rom, self.samples, self.dp = bytes(rom), bytes(samples), dpram
        self.state = ST_IDLE
        self.wipe = 0xFF          # $5B
        self.wd = 0               # $44
        self.hb = 0               # $5D
        self.prio = 0xFF          # bank 1 r3
        self.romsum = 0           # command $11: the answer's time (units from the current frame start)
        self.end = 0              # the playing sample's end (units from the current frame start), if prio != $FF
        self.events = []          # (kind, ...): ("start", n, addr, period, vol, t) ("ignore", n, t) ("cmd", v, t)

    @classmethod
    def from_board(cls, b):
        """the model at a frame boundary of the reference board (engine/m72board.py) after BOOT_END"""
        c = b.mcu.core.cpu
        m = cls(b.mcu_rom, b.samples, b.dpram)
        r = c.ram
        if c.pc in (0x0311, 0x0312):
            m.state = ST_DEAD
        elif c.pc in (0x045E,):
            m.state = ST_ROMTEST
        elif 0x043E <= c.pc < 0x045E or 0x0460 <= c.pc < 0x04B4:
            raise ValueError("MCU in its ROM test's sum (pc %04X)" % c.pc)
        elif not 0x02B1 <= c.pc <= 0x0312:
            raise ValueError("MCU not in its main loop (pc %04X)" % c.pc)
        if r[0x3C]:
            raise ValueError("MCU command queue not empty")
        m.wipe, m.wd, m.hb, m.prio = r[0x5B], r[0x44], r[0x5D], r[0x0B]
        if m.prio != 0xFF and c.tcon & 0x40:      # a sample plays: its remaining bytes
            left = len(sample_bytes(b.samples, b.mcu_sample_addr))
            period = 256 - c.th1
            m.end = 3 * ((left + 1) * period - (c.tl1 - c.th1))
        else:
            m.prio = 0xFF
        return m

    # ---- the V30's side ----------------------------------------------------------------------------------------
    def v30_write(self, o, n=1):
        if o + n > 0xFFE:
            self.hb += 1          # INT0 (a write to the right side's mailbox word)
        if self.state == ST_DEAD and o <= 0xFFC < o + n:
            self.dp[0xFFC] = self.wd

    def command(self, v, t=UNITS_LINE):
        """a port C0 write of v at t units into the frame"""
        t += CMD_LAG
        self.events.append(("cmd", v, t))
        if self.state in (ST_DEAD, ST_ROMSUM):
            return
        if v in (0x10, 0x11):
            if self.state != ST_IDLE:
                return            # (the ring is not served any more)
            if v == 0x10:
                self.dp[0:31] = self.rom[CHECK:CHECK + 31]
                self.wipe = 3
            else:
                self.state = ST_ROMSUM    # (interrupts off while it sums its ROM: no samples, no ticks)
                self.romsum = t - CMD_LAG + ROMTEST_UNITS
            return
        prio, restart, period, vol, addr = sample_entry(self.rom, v)
        cur = self.prio if (self.prio != 0xFF and t < self.end) else 0xFF
        if prio < cur or (prio == cur and restart):
            self.prio = prio
            self.end = t + 3 * period * (len(sample_bytes(self.samples, addr)) + 1)
            self.events.append(("start", v, addr, period, vol, t))
        else:
            self.events.append(("ignore", v, t))

    def frame(self):
        """a frame boundary: the frame's timer 0 tick and the main loop after it"""
        if self.prio != 0xFF:
            self.end -= UNITS_FRAME
            if self.end <= 0:
                self.prio = 0xFF
        if self.state != ST_IDLE:
            if self.state == ST_DEAD:
                self.dp[0xFFC] = self.wd
            elif self.state == ST_ROMSUM:
                self.romsum -= UNITS_FRAME
                if self.romsum <= 0:      # (the answer landed in the frame that ended)
                    self.dp[0xFE0:0xFEE] = rom_answer(self.rom)
                    self.state = ST_ROMTEST
            return
        if self.wipe not in (0, 0xFF):
            self.wipe -= 1
        if self.hb == 1:
            if self.wd != 0x80:
                self.wd = 0
        else:
            self.wd = (self.wd + 1) & 0xFF
        self.hb = 0
        if self.wipe == 0:
            self.wipe = 0xFF
            self.dp[0:0x20] = WIPE
        if self.wd >= 0x1E:
            self.state = ST_DEAD
            self.dp[0xFFC] = self.wd

    # ---- for mcu.s -------------------------------------------------------------------------------------------------
    def state_image(self):
        """src/mcu.s's mcu_state (14 bytes): state.b wipe.b wd.b hb.b prio.b pad.b end.l romsum.l"""
        end = max(self.end, 0) if self.prio != 0xFF else 0
        rs = max(self.romsum, 0) if self.state == ST_ROMSUM else 0
        return (bytes([self.state, self.wipe, self.wd, self.hb & 0xFF, self.prio, 0]) + end.to_bytes(4, "big") +
                rs.to_bytes(4, "big"))


def write_tables(path, rom, samples):
    """mcu.s's tables: mcu_check (command $10's 31 bytes), mcu_romans (command $11's 14), mcu_samples: 64 entries
    (n & 63: the table index wraps at 256) of prio.b restart.b period.b vol.b length.l (units: 3 x period x
    (bytes + 1), the sample's end after its start); mcu_sample_addr: 64 longs, the sample's address in the ROM"""
    def db(name, data):
        out = [name + ":"]
        for i in range(0, len(data), 16):
            out.append("\tdc.b\t" + ",".join("$%02X" % x for x in data[i:i + 16]))
        return out
    lines = ["; generated by games/mrheli/tools/mcu.py --tables (from mh_c-pr-.ic1 and c-v0-b.rom)"]
    lines += db("mcu_check", rom[CHECK:CHECK + 31])
    lines += db("mcu_romans", rom_answer(rom))
    lines += ["\teven", "mcu_samples:"]
    addrs = []
    for n in range(64):
        prio, restart, period, vol, addr = sample_entry(rom, n)
        length = 3 * period * (len(sample_bytes(samples, addr)) + 1)
        lines.append("\tdc.b\t$%02X,%d,$%02X,$%02X\n\tdc.l\t%d\t; command %d: address $%05X" %
                     (prio, restart, period & 0xFF, vol, length, n, addr))
        addrs.append(addr)
    lines.append("mcu_sample_addr:")
    lines += ["\tdc.l\t" + ",".join("$%05X" % x for x in addrs[i:i + 8]) for i in range(0, 64, 8)]
    Path(path).write_text("\n".join(lines) + "\n")


if __name__ == "__main__":
    from m72board import load_regions
    from paths import build_dir
    if "--tables" in sys.argv:
        r = load_regions("mrheli")
        out = build_dir("mrheli") / "mcu_tables.s"
        write_tables(out, r["mcu"], r["samples"])
        print("wrote", out)
