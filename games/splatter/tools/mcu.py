"""Splatterhouse's CUS64 MCU (HD63701) as a native model: what the program does, frame by frame, without running it.

The program (internal ROM cus64-64a1.mcu, and the copy of it in the voice ROM page $FB at $B800-$BFFF that the boot
jumps to): a main loop that, after the frame's IRQ1, does the frame's work, and otherwise polls the requests in
TRIRAM; the output compare interrupt (OCI, every 256 E clocks = 99 a frame) is the two channel voice player.

Every frame (MCUNative.frame, where machine.run_others runs the MCU: one window from a vertical blank's start to the
next; the main and sub CPU held):
  passes of the main loop (only while TRIRAM[0] = $A6, the kludge byte):
    - voice requests (F469): $02C/$02E bit 6 = start, low nibble = voice ROM page (table F5D6), $02B/$02D = sample
      number (0 = stop).  Bit 6 is cleared at once; a started sample sets bit 7 ("playing"), the player clears it
      at the sample's end.  A playing channel takes the new sample only if the new header's priority value (& $7C) is
      not above the playing one's (the same request again: restarted unless the header's bit 7 says "no restart").
    - commands $02F (BA75: 1-5 peek/poke/copy in the MCU's space, 6/7 EEPROM byte/block write, 8-10 set the time,
      coin and edge counters, 13 voice ROM read, 14/15 EEPROM test/format; 11/12 reset the MCU: not modelled)
    - $001 (BCCB): the RAM test and MCU reset when non zero (not modelled; the acknowledge of $8E is)
    - $03C (BE35): 1 = write the 16 byte record $03F-$04E to the EEPROM slot of index $03D (with its checksum),
      2 = read it back, result in $03E
  the frame's work after IRQ1 (vblank end, 3852 clocks into the window):
    - RAM $8F-$AD -> TRIRAM $00C-$02A (B91A): the time counters (BCD hh hh mm ss, power on + 3 players), the edge
      counters of $038, the coin totals, then $A9-$AD: CONTROL0, CONTROL1, the DIP nibbles (all inverted), coins
      (~COIN & $78) as read the frame before
    - the inputs read (B927), the coin counter pulses ($039/$03A: requests, 8 frames low, 8 high) and the lockout
      ($03B) on port 1
    - the counters (B9B6): power on time always, player time for the bits of $038, rising edges of $038 counted
The EEPROM is RAM in MAME (the write verify succeeds on the next pass; a written $FF is checked after $3C00 clocks).

Timing that the per-frame model cannot know exactly (the loop's position against the OCIs depends on every cycle
the MCU ran): when in the window a request is picked up and a sample starts playing.  The model takes the most
common tick (ACT_TICK = 3; the reference started at ticks 2 to 7 in play, mcu_test.py); a sample's end (bit 7
cleared) then comes out a frame early or late when it falls within that error of the window's end (the main CPU
reads $02C/$02E only when it asks for a sample: read, modify, write).  Stops: STOP_TICK (the reference 1 to 4).
The multi-pass commands go one step every PASS_TICKS ticks (EEPROM writes of $FF wait for the counter: the step a
command ends at can differ).

Voice data (sample_info / sample_ticks): the page's table of 16 bit pointers (sample n at 2(n-1); bit 15 = the next
32 KB page), the sample: a header byte (bits 2-6 priority, bit 7 no-restart, bits 0-1 the DAC gain), then one byte a
tick: $00 n = hold the last value for n more ticks (n+1 ticks with the zero byte's own), $FF = end, else the
DAC value (8 bit unsigned, $80 = silence).  The DAC written at a tick is the value the previous tick decoded.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "engine"))

TICKS = 99                      # OCIs a frame (25344 / 256)
TICK = 256                      # E clocks
IRQ1_TICK = 15                  # IRQ1 at 3852 clocks: after the 15th OCI (48 + 256 k)
JOB_TICKS = 6                   # the frame's work (copy, inputs, counters) holds the loop for about that long
PASS_TICKS = 2                  # one pass of the idle loop
ACT_TICK = 3                    # the tick at which a sample requested before the window starts playing
STOP_TICK = 1                   # a stop request (sample 0)
PAGE_TABLE = bytes.fromhex("f8faf4f6eceedcdebcbe7c7e")     # F5D6: $D800 values of the 12 voice ROM pages


def bank_of(v):
    """MAME's mcu_bankswitch_w: the 32 KB entry of the voice region for a $D800 value"""
    sel = v & 0xFC
    bank = {0xF8: 0, 0xF4: 4, 0xEC: 8, 0xDC: 12, 0xBC: 16, 0x7C: 20}.get(sel, 0)
    if sel == 0xF8:
        v ^= 2
    return bank + (v & 3)


def daa_add(a, b, c=0):
    """ADDA/ADCA then DAA as MAME's 6800 core does them: (result, carry)"""
    t = a + b + c
    h = ((a ^ b ^ t) & 0x10) != 0
    carry = t > 0xFF
    t &= 0xFF
    msn, lsn = t & 0xF0, t & 0x0F
    cf = 0
    if lsn > 9 or h:
        cf |= 0x06
    if msn > 0x80 and lsn > 9:
        cf |= 0x60
    if msn > 0x90 or carry:
        cf |= 0x60
    r = cf + t
    return r & 0xFF, carry or r > 0xFF


def page_value(nibble, rom=None):
    """the $D800 value of voice ROM page `nibble` (F5D6 + nibble; past the 12 entries the ROM's next bytes)"""
    if nibble < len(PAGE_TABLE):
        return PAGE_TABLE[nibble]
    if rom is None:
        raise NotImplementedError("voice page %d needs the MCU ROM" % nibble)
    return rom[0x5D6 + nibble]


def sample_info(voice, nibble, number, rom=None):
    """where sample `number` (1-255) of page `nibble` ($02C/$02E low nibble) is: ($D800 value, address $4000-$BFFF,
    voice region offset of the header byte, header byte).  F47B: the word at $4000 + 2 (number - 1) of the page,
    bit 15 = the next page, + $4000."""
    bv = page_value(nibble, rom)
    i = 2 * (number - 1)
    a = (((i >> 8) + 0x40) << 8) | (i & 0xFF)
    rd = lambda bv, a: voice[bank_of(bv) * 0x8000 + a - 0x4000]
    ptr = (rd(bv, a) << 8) | rd(bv, a + 1)
    if ptr & 0x8000:
        bv = (bv + 1) & 0xFF
        ptr &= 0x7FFF
    addr = ((((ptr >> 8) + 0x40) & 0xFF) << 8) | (ptr & 0xFF)
    return bv, addr, bank_of(bv) * 0x8000 + addr - 0x4000, rd(bv, addr)


def sample_length(voice, nibble, number, rom=None):
    """the ticks a sample plays: from the tick it starts at to the tick that reads its $FF (that tick clears bit 7)"""
    bv, addr, off, header = sample_info(voice, nibble, number, rom)
    n = 0
    base = bank_of(bv) * 0x8000 - 0x4000
    a = addr + 1
    hold = False
    while True:
        if a >= 0xC000:
            bv = (bv + 1) & 0xFF
            base = bank_of(bv) * 0x8000 - 0x4000
            a = 0x4000
        v = voice[base + a]
        a += 1
        if hold:
            n += 1 + v
            hold = False
        elif v == 0xFF:
            return n
        elif v == 0:
            hold = True
        else:
            n += 1


def sample_ticks(voice, nibble, number, limit=1 << 20, rom=None):
    """a sample as the player decodes it, one DAC value a tick (the run-length holds expanded; the values the DAC
    gets one tick later), and its header byte: (values, header).  Before the first value the channel outputs $80;
    after the end ($FF) $80 again (the gain bits cleared)."""
    bv, addr, off, header = sample_info(voice, nibble, number, rom)
    c = Channel()
    c.start(bv, addr, header)
    out = []
    while len(out) < limit:
        if c.tick(voice):
            break
        out.append(c.dac)
    return out, header


class Channel:
    """one voice channel's player state (D6 D7 D8 D9 DB DC / DF E0 E1 E2 E4 E5)"""

    def __init__(self):
        self.active = 0
        self.dac = 0x80
        self.hold = 0
        self.addr = 0x4000
        self.bank = 0xFB
        self.header = 0
        self.req = (0, 0)

    def start(self, bv, addr, header):
        self.active = 0
        self.hold = 0
        self.bank = bv
        self.header = header
        self.dac = 0x80
        addr += 1
        if addr >= 0xC000:
            addr = 0x4000
            self.bank = (self.bank + 1) & 0xFF
        self.addr = addr
        self.active = 1

    def _next(self):
        self.addr += 1
        if self.addr >= 0xC000:
            self.addr = 0x4000
            self.bank = (self.bank + 1) & 0xFF
            return True
        return False

    def tick(self, voice):
        """one OCI for an active channel; returns True when the sample ended (the $FF)"""
        if self.hold:
            self.hold -= 1
            return False
        rd = lambda: voice[bank_of(self.bank) * 0x8000 + self.addr - 0x4000]
        a = rd()
        if a == 0:
            self._next()
            self.hold = rd()
            self._next()
            return False
        self._next()
        if a == 0xFF:
            self.dac = 0x80
            self.active = 0
            self.header = 0
            return True
        self.dac = a
        return False


class MCUNative:
    """The MCU's effects frame by frame; its state is the MCU's RAM ($80-$FF, same addresses), the EEPROM and the
    port 1 latch."""

    def __init__(self, voice, nvram=None, rom=None):
        self.voice = bytes(voice)
        self.rom = rom
        self.ram = bytearray(0x100)             # $80-$FF used
        self.nvram = bytearray(nvram if nvram is not None else 0x800)
        self.p1 = 0
        self.patch = 0xA6
        self.time = 0                           # E clocks (the free running counter is its low 16 bits)
        self.frame_no = 0
        self.events = []
        self.log = None

    @classmethod
    def from_board(cls, board):
        """the state of the board's MCU (engine/namcos1.py) at the end of a frame"""
        n = cls(board.voice, board.nvram, board.mcu_rom)
        n.ram[0x80:0x100] = board.mcu.ram
        n.p1 = board.mcu.data[0]
        n.patch = board.mcu_patch
        n.time = board.mcu.ctd & 0xFFFF
        n.frame_no = board.frame
        return n

    # ---- the RAM's variables -----------------------------------------------
    def w16(self, a):
        return (self.ram[a] << 8) | self.ram[a + 1]

    def setw16(self, a, v):
        self.ram[a] = (v >> 8) & 0xFF
        self.ram[a + 1] = v & 0xFF

    def chan(self, ch):
        """the channel's state from RAM"""
        b = 0xD6 if ch == 0 else 0xDF
        c = Channel()
        c.active, c.dac, c.hold = self.ram[b], self.ram[b + 1], self.ram[b + 2]
        c.addr = self.w16(b + 3)
        c.bank, c.header = self.ram[b + 5], self.ram[b + 6]
        return c

    def put_chan(self, ch, c):
        b = 0xD6 if ch == 0 else 0xDF
        self.ram[b], self.ram[b + 1], self.ram[b + 2] = c.active, c.dac, c.hold
        self.setw16(b + 3, c.addr)
        self.ram[b + 5], self.ram[b + 6] = c.bank, c.header

    # ---- the MCU's address space (commands 1-5, 13) --------------------------
    def rd(self, tri, a, bank=0xFB):
        a &= 0xFFFF
        if 0x80 <= a < 0x100:
            return self.ram[a]
        if 0x4000 <= a < 0xC000:
            return self.voice[bank_of(bank) * 0x8000 + a - 0x4000]
        if 0xC000 <= a < 0xC800:
            return tri[a & 0x7FF]
        if 0xC800 <= a < 0xD000:
            return self.nvram[a & 0x7FF]
        if 0x1000 <= a < 0x1004:
            return self.dip_port(a)
        if a in (0x1400, 0x1401):
            return self.inputs[a & 1]
        raise NotImplementedError("MCU read of %04X (command) not modelled" % a)

    def wr(self, tri, a, v):
        a &= 0xFFFF
        if 0x80 <= a < 0x100:
            self.ram[a] = v
        elif 0xC000 <= a < 0xC800:
            self.tri_w(tri, a & 0x7FF, v)
        elif 0xC800 <= a < 0xD000:
            self.nvram[a & 0x7FF] = v
        else:
            raise NotImplementedError("MCU write of %04X (command) not modelled" % a)

    def ee_rd(self, a):
        """the EEPROM side of the space ($C800-$CFFF; a record past it reaches $D000-: nothing to read there)"""
        a &= 0xFFFF
        if 0xC800 <= a < 0xD000:
            return self.nvram[a & 0x7FF]
        if 0xD000 <= a < 0xF000:
            return 0
        raise NotImplementedError("EEPROM access at %04X" % a)

    def ee_wr(self, a, v):
        a &= 0xFFFF
        if 0xC800 <= a < 0xD000:
            self.nvram[a & 0x7FF] = v
        elif 0xD000 <= a < 0xF000 and a & 0xFC00 != 0xD800:
            pass                                # (a DAC latch, the next OCI writes it again; nothing)
        else:
            raise NotImplementedError("EEPROM access at %04X" % a)

    def tri_w(self, tri, o, v):
        """TRIRAM write with MAME's kludge (namcos1_state::mcu_patch_w)"""
        if o == 0:
            if self.patch == 0xA6:
                return
            self.patch = v
        tri[o] = v

    def dip_port(self, a):
        nib = (self.dipsw >> 4) if a & 2 else self.dipsw & 0xF
        return 0xF0 | ((nib & 1) << 3) | ((nib & 2) << 1) | ((nib & 4) >> 1) | ((nib & 8) >> 3)

    def counter(self, tick):
        return (self.time + 48 + tick * TICK) & 0xFFFF

    # ---- one frame -----------------------------------------------------------
    def frame(self, tri, control0=0xFF, control1=0xFF, coin=0xF8, dipsw=0xFF, switch_ticks=None):
        """one window of the MCU (machine.run_others): reads and writes `tri` (the board's TRIRAM bytearray);
        returns the frame's record: dict(dac=[ch0 99 values, ch1 99 values] (None when the OCI did not write
        them), p2=[99 port 2 values], p1=the port 1 write, events=[(tick, channel, what, data)]).
        switch_ticks: {channel: tick} the ticks the requests take effect at, instead of ACT_TICK / STOP_TICK (the
        tests give the reference's; a start's as (tick of the old sample's stop, of the gain bits, of the new one's start))"""
        self.switch_ticks = switch_ticks or {}
        self.inputs = (control0, control1)
        self.coin = coin
        self.dipsw = dipsw
        rec = dict(dac=[None, None], p2=None, p1=None, events=[])
        self.events = rec["events"]
        if tri[0] != 0xA6:                      # the loop spins on the kludge byte, the OCI does nothing
            self.time += TICKS * TICK
            self.frame_no += 1
            return rec
        ram = self.ram
        # the passes before the first tick: the voice requests of both channels (activation later), commands
        pending = []                            # (tick, channel, start args)
        self.voice_requests(tri, pending)
        busy = self.pass_rest(tri, 0)
        dac = [[], []]
        p2 = []
        chans = [self.chan(0), self.chan(1)]
        k_pass = PASS_TICKS
        for k in range(TICKS):
            for p in [p for p in pending if p[0] == k]:
                pending.remove(p)
                self.activate(tri, chans, p)
            # the OCI
            dac[0].append(chans[0].dac)
            dac[1].append(chans[1].dac)
            for ch in (0, 1):
                c = chans[ch]
                if c.active and c.tick(self.voice):
                    o = 0x2C + 2 * ch
                    self.tri_w(tri, o, tri[o] & 0x7F)
                    ram[0xD5] &= 0xF8 if ch == 0 else 0xE7
                    self.events.append((k, ch, "end", None))
            p2.append(ram[0xD5])
            if k == IRQ1_TICK:
                self.put_chan(0, chans[0])
                self.put_chan(1, chans[1])
                self.frame_work(tri)
                k_pass = k + JOB_TICKS
            if busy and k >= k_pass and k < TICKS - 1:
                self.put_chan(0, chans[0])
                self.put_chan(1, chans[1])
                busy = self.pass_rest(tri, k)
                chans = [self.chan(0), self.chan(1)]
                k_pass = k + PASS_TICKS
        self.put_chan(0, chans[0])
        self.put_chan(1, chans[1])
        rec["dac"], rec["p2"] = dac, p2
        rec["p1"] = self.p1
        ram[0xBA] = 0xFB
        self.time += TICKS * TICK
        self.frame_no += 1
        return rec

    def voice_requests(self, tri, pending):
        """F469 for channel 0 and 1: the requests seen at the window's start"""
        ram = self.ram
        for ch in (0, 1):
            o = 0x2C + 2 * ch
            b = tri[o]
            if not b & 0x40:
                continue
            b &= 0xBF
            self.tri_w(tri, o, b)
            bv = page_value(b & 0x0F, self.rom)
            ram[0xC9] = bv
            ram[0xBA] = bv
            n = tri[o - 1]
            act = ram[0xD6 if ch == 0 else 0xDF]
            if n == 0:                          # stop
                k = self.switch_ticks.get(ch, STOP_TICK)
                pending.append((k[-1] if isinstance(k, tuple) else k, ch, None))
                self.events.append((0, ch, "stop request", None))
                continue
            # the pointer, the header
            i = (n - 1) * 2
            hi = ((i >> 8) + 0x40) & 0xFF
            a = (hi << 8) | (i & 0xFF)
            ptr = (self.voice[bank_of(bv) * 0x8000 + a - 0x4000] << 8) | \
                self.voice[bank_of(bv) * 0x8000 + ((a + 1) & 0xFFFF) - 0x4000]
            if ptr & 0x8000:
                bv = (bv + 1) & 0xFF
                ram[0xC9] = ram[0xBA] = bv
                ptr &= 0x7FFF
            addr = ((((ptr >> 8) + 0x40) & 0xFF) << 8) | (ptr & 0xFF)
            header = self.voice[bank_of(bv) * 0x8000 + addr - 0x4000]
            ram[0xCD] = header
            ram[0xCB] = header & 0x7C
            ram[0xCC] = header & 3
            cur = 0xDC if ch == 0 else 0xE5
            same = 0xDD if ch == 0 else 0xE6
            if act:
                if (tri[o - 1], tri[o]) == (ram[same], ram[same + 1]):
                    if ram[cur] & 0x80:
                        self.events.append((0, ch, "ignored (no restart)", (b & 0x0F, n)))
                        continue
                elif (ram[cur] & 0x7C) < ram[0xCB]:
                    self.events.append((0, ch, "ignored (priority)", (b & 0x0F, n)))
                    continue
            k = self.switch_ticks.get(ch, ACT_TICK)
            mute, gain, k = k if isinstance(k, tuple) else (k, k, k)
            if mute < k:                        # (the old sample stopped and the DAC at $80 a little before,
                pending.append((mute, ch, "mute"))      # then the gain set)
            if gain < k:
                pending.append((gain, ch, ("gain", header)))
            pending.append((k, ch, (bv, addr, header, tri[o - 1], tri[o])))
            self.events.append((0, ch, "start request", (b & 0x0F, n, bank_of(bv) * 0x8000 + addr - 0x4000)))
        ram[0xBA] = 0xFB

    def activate(self, tri, chans, p):
        k, ch, args = p
        ram = self.ram
        c = chans[ch]
        if args == "mute":
            c.active = 0
            c.dac = 0x80
            return
        if isinstance(args, tuple) and args[0] == "gain":
            self.set_gain(ch, args[1])
            return
        if args is None:                        # stop: the channel off, its output kept
            c.active = 0
            c.header = 0
            self.events.append((k, ch, "stopped", None))
            return
        bv, addr, header, n, req = args
        c.start(bv, addr, header)
        c.dac = 0x80
        same = 0xDD if ch == 0 else 0xE6
        ram[same], ram[same + 1] = n, req
        self.set_gain(ch, header)
        o = 0x2C + 2 * ch
        self.tri_w(tri, o, tri[o] | 0x80)
        self.events.append((k, ch, "started", (bank_of(bv) * 0x8000 + addr - 0x4000, header)))

    def set_gain(self, ch, header):
        """the DAC gain bits of port 2 from the header (F4F8 / F5A5): ch 0 bits 0 and 2, ch 1 bits 3 and 4"""
        ram = self.ram
        g = header & 3
        if ch == 0:
            ram[0xD5] = (ram[0xD5] & 0xF8) | ((g << 1) | (g & 1))
        else:
            ram[0xD5] = (ram[0xD5] & 0xE7) | ((g << 3) & 0xFF)

    # ---- the rest of a pass: commands ($02F), $001, $03C ---------------------
    def pass_rest(self, tri, k):
        """BA75, BCCB, BE35 once; True while a command takes more passes"""
        busy = self.command(tri, k)
        self.test_request(tri)
        busy |= self.record_command(tri, k)
        return busy

    def command(self, tri, k):
        ram = self.ram
        cmd = tri[0x2F] & 0x0F
        self.tri_w(tri, 0, (cmd * 2) & 0xFF)    # (BA8B: ignored by the kludge)
        x = (tri[0x32] << 8) | tri[0x33]
        done = True
        if cmd == 0:
            return False
        if cmd == 1:
            tri[0x31] = self.rd(tri, x)
            x += 1
        elif cmd == 2:
            tri[0x30], tri[0x31] = self.rd(tri, x), self.rd(tri, x + 1)
            x += 2
        elif cmd == 3:
            self.wr(tri, x, tri[0x31])
            x += 1
        elif cmd == 4:
            self.wr(tri, x, tri[0x30])
            self.wr(tri, x + 1, tri[0x31])
            x += 2
        elif cmd == 5:
            while True:
                v = self.rd(tri, x)
                x = (x + 1) & 0xFFFF
                y = (tri[0x34] << 8) | tri[0x35]
                self.wr(tri, y, v)
                y = (y + 1) & 0xFFFF
                tri[0x34], tri[0x35] = y >> 8, y & 0xFF
                n = (((tri[0x36] << 8) | tri[0x37]) - 1) & 0xFFFF
                tri[0x36], tri[0x37] = n >> 8, n & 0xFF
                if n == 0:
                    break
        elif cmd in (6, 7, 14, 15):
            return self.eeprom_command(tri, cmd, k)
        elif cmd == 8:
            b = (tri[0x31] & 3) * 4
            ram[0x8F + b:0x93 + b] = tri[0x32:0x36]
            tri[0x2F] = 0
            return False
        elif cmd == 9:
            b = (tri[0x31] & 1) * 2
            ram[0xA5 + b], ram[0xA6 + b] = tri[0x32], tri[0x33]
            tri[0x2F] = 0
            return False
        elif cmd == 10:
            b = tri[0x31] & 3
            b = 0 if b == 3 else b
            ram[0x9F + 2 * b], ram[0xA0 + 2 * b] = tri[0x32], tri[0x33]
            tri[0x2F] = 0
            return False
        elif cmd == 13:
            a = tri[0x34]
            b = a >> 2
            b = 0 if b >= 6 else b
            bv = PAGE_TABLE[2 * b] | (a & 3)
            tri[0x31] = self.rd(tri, x, bv)
            x += 1
        else:
            raise NotImplementedError("MCU command %d (reset) not modelled" % cmd)
        tri[0x32], tri[0x33] = (x >> 8) & 0xFF, x & 0xFF
        tri[0x2F] = 0
        return not done

    def ee_write(self, a, v, k):
        """BB21: the byte written, the address, value and time kept for the verify"""
        self.setw16(0xBB, a)
        self.ram[0xBD] = v
        self.ee_wr(a, v)
        self.setw16(0xBF, self.counter(k))

    def ee_ok(self, k):
        """the verify of the last write: True = done, False = failed (timeout), None = again next pass"""
        ram = self.ram
        x = self.w16(0xBB)
        timeout = ((self.counter(k) - self.w16(0xBF)) & 0xFFFF) >= self.w16(0xD3)
        if ram[0xBD] == 0xFF:
            if not timeout:
                return None
            return self.ee_rd(x) == 0xFF
        if self.ee_rd(x) == ram[0xBD]:
            return True
        return False if timeout else None

    def eeprom_command(self, tri, cmd, k):
        ram = self.ram
        if cmd == 6 or cmd == 7:
            if ram[0xBE] == 0:
                tri[0x30] = 0
                ram[0xBE] += 1
                x = (tri[0x32] << 8) | tri[0x33]
                if cmd == 6:
                    self.ee_write(x, tri[0x31], k)
                else:
                    self.ee_write((tri[0x34] << 8) | tri[0x35], self.rd(tri, x), k)
                return True
            while True:
                ok = self.ee_ok(k)
                if ok is None:
                    return True
                x = self.w16(0xBB)
                if cmd == 6:
                    if not ok:
                        tri[0x30] = 0x80
                        x -= 1
                    x += 1
                    tri[0x32], tri[0x33] = (x >> 8) & 0xFF, x & 0xFF
                    break
                if not ok:
                    tri[0x30] = 0x80
                    tri[0x34], tri[0x35] = (x >> 8) & 0xFF, x & 0xFF
                    break
                x += 1
                tri[0x34], tri[0x35] = (x >> 8) & 0xFF, x & 0xFF
                y = ((tri[0x32] << 8) | tri[0x33]) + 1
                tri[0x32], tri[0x33] = (y >> 8) & 0xFF, y & 0xFF
                n = (((tri[0x36] << 8) | tri[0x37]) - 1) & 0xFFFF
                tri[0x36], tri[0x37] = n >> 8, n & 0xFF
                if n == 0:
                    break
                self.ee_write((tri[0x34] << 8) | tri[0x35], self.rd(tri, y), k)     # (BB71: next byte)
                return True
            ram[0xBE] = 0
            tri[0x2F] = 0
            return False
        # 14: test (0..$4F to $C800-$C84F), 15: format (+ $FF to $C850-$CFFD)
        if ram[0xBE] == 0:
            tri[0x30] = 0
            ram[0xBE] += 1
            self.ee_write(0xC800, 0, k)
            return True
        if cmd == 15 and ram[0xBE] == 2:        # the $FF part
            ok = self.ee_ok(k)
            if ok is None:
                return True
            if not ok:
                tri[0x30] = 0x80
            else:
                x = self.w16(0xBB) + 1
                if x != 0xCFFE:
                    self.ee_write(x, 0xFF, k)
                    return True
            ram[0xBE] = 0
            tri[0x2F] = 0
            return False
        ok = self.ee_ok(k)
        if ok is None:
            return True
        if not ok:
            tri[0x30] = 0x80
        else:
            x = self.w16(0xBB) + 1
            v = (ram[0xBD] + 1) & 0xFF
            if x != 0xC850:
                self.ee_write(x, v, k)
                return True
            if cmd == 15:
                ram[0xBE] += 1
                self.ee_write(x, 0xFF, k)
                return True
        ram[0xBE] = 0
        tri[0x2F] = 0
        return False

    def test_request(self, tri):
        """BCCB: $001 non zero starts the RAM test and resets the MCU (not modelled); $8E acknowledges"""
        b = tri[1]
        if self.ram[0x8E]:
            if b == 0:
                self.ram[0x8E] = 0
                tri[2] = 0
        elif b:
            raise NotImplementedError("MCU RAM test ($001) not modelled")

    def record_command(self, tri, k):
        """BE35: $03C = 1 write a record, 2 read it; True while the write goes on"""
        ram = self.ram
        a = tri[0x3C]
        if a == 0:
            return False
        tri[0x3E] = 0
        if a == 2:
            b = tri[0x3D]
            if b >= 0x50:
                return self.rec_done(tri, 4)
            v = self.ee_rd(0xC800 + b)
            if v >= 0x73:
                return self.rec_done(tri, 2)
            p = 0x850 + v * 0x11
            s = 0
            for i in range(16):
                d = self.ee_rd(0xC800 + p + i)
                s = (s + d) & 0xFF
                tri[0x3F + i] = d
            self.setw16(0xC9, 0xC800 + p + 16)
            self.setw16(0xCB, 0xC04E)
            if self.ee_rd(0xC800 + p + 16) != (-s) & 0xFF:
                return self.rec_done(tri, 5)
            tri[0x3C] = 0
            return False
        if a != 1:
            return self.rec_done(tri, 3)
        st = ram[0xC5]
        if st >= 5:
            ram[0xC5] = 0
            tri[0x3C] = 0
            return False
        if st == 0:
            return self.rec_start(tri, k)
        if st in (1, 2):
            x = self.w16(0xC1)
            if ram[0xC4] == 0xFF:
                if ((self.counter(k) - self.w16(0xC6)) & 0xFFFF) < self.w16(0xD3):
                    return True
                ok = self.ee_rd(x) == 0xFF
                if not ok:
                    ram[0xC5] = 3
                    return True
            elif self.ee_rd(x) != ram[0xC4]:
                if ((self.counter(k) - self.w16(0xC6)) & 0xFFFF) < self.w16(0xD3):
                    return True
                ram[0xC5] = 3
                return True
            if st == 2:
                ram[0xC5] = 0
                tri[0x3C] = 0
                return False
            self.setw16(0xC1, x + 1)
            ram[0xC3] = (ram[0xC3] + 1) & 0xFF
            if ram[0xC3] & 0x0F:
                self.rec_byte(tri, tri[0x3F + ram[0xC3]], k)
            else:
                ram[0xC5] = 2
                self.rec_byte(tri, (-ram[0xC8]) & 0xFF, k)
            return True
        if st == 3:                             # a new slot for the record
            a = 0x4F
            for i in range(0x50):
                if self.nvram[i] > a:
                    a = self.nvram[i]
            a = (a + 1) & 0xFF
            if a >= 0x73:
                return self.rec_done(tri, 1)
            if tri[0x3D] >= 0x50:
                return self.rec_done(tri, 4)
            self.setw16(0xC1, 0xC800 + tri[0x3D])
            ram[0xC5] = 4
            self.rec_byte(tri, a, k)
            return True
        # 4: the slot byte's verify, then the record again
        x = self.w16(0xC1)
        if self.ee_rd(x) == ram[0xC4]:
            return self.rec_start(tri, k)
        if ((self.counter(k) - self.w16(0xC6)) & 0xFFFF) < self.w16(0xD3):
            return True
        return self.rec_done(tri, 1)

    def rec_done(self, tri, code):
        tri[0x3E] = code
        tri[0x3C] = 0
        return False

    def rec_start(self, tri, k):
        """BEDA"""
        ram = self.ram
        b = tri[0x3D]
        if b >= 0x50:
            return self.rec_done(tri, 4)
        v = self.ee_rd(0xC800 + b)
        if v >= 0x73:
            return self.rec_done(tri, 1)
        self.setw16(0xC1, 0xC850 + v * 0x11)
        ram[0xC3] = 0
        ram[0xC8] = 0
        ram[0xC5] = 1
        self.rec_byte(tri, tri[0x3F], k)
        return True

    def rec_byte(self, tri, v, k):
        """BF0B"""
        ram = self.ram
        x = self.w16(0xC1)
        ram[0xC4] = v
        self.ee_wr(x, v)
        ram[0xC8] = (ram[0xC8] + v) & 0xFF
        self.setw16(0xC6, self.counter(k))

    # ---- the frame's work after IRQ1 ----------------------------------------
    def frame_work(self, tri):
        ram = self.ram
        ram[0xB9] = 0
        # B91A: the RAM block to TRIRAM
        for i in range(31):
            self.tri_w(tri, 0x0C + i, ram[0x8F + i])
        self.setw16(0xC9, 0xC02B)
        # B927: inputs, coin counters, lockout
        ram[0xA9] = ~self.inputs[0] & 0xFF
        ram[0xAA] = ~self.inputs[1] & 0xFF
        ram[0xAB] = ~self.dip_port(0x1000) & 0xFF
        ram[0xAC] = ~self.dip_port(0x1002) & 0xFF
        p1_in = (self.coin & 0x78) | (self.p1 & 0x87)
        ram[0xAD] = ~p1_in & 0x78
        b = ram[0xB4]
        self.p1 = b                             # (stb $02)
        for (t, req, flag, bit, tot, o) in ((0xB5, 0x39, 0xB7, 0x02, 0xA5, 0), (0xB6, 0x3A, 0xB8, 0x04, 0xA7, 1)):
            if ram[t]:
                ram[t] -= 1
            elif ram[flag]:
                ram[flag] = 0
                ram[t] = 8
                b &= ~bit
            elif tri[req]:
                tri[req] = (tri[req] - 1) & 0xFF
                ram[flag] = 1
                ram[t] = 8
                b |= bit
                self.setw16(tot, (self.w16(tot) + 1) & 0xFFFF)
        b = (b | 1) if tri[0x3B] else (b & 0xFE)
        ram[0xB4] = b & 0xFF
        # B9B6: edges of $038, the time counters
        old = ram[0xB2]
        new = tri[0x38]
        ram[0xB2] = new
        e = ~old & new
        for i, a in enumerate((0x9F, 0xA1, 0xA3)):
            if e >> i & 1:
                self.setw16(a, (self.w16(a) + 1) & 0xFFFF)
        self.time_count(0)
        for b2 in ((), (1,), (2,), (1, 2), (3,), (1, 3), (2, 3), (1, 2, 3))[new & 7]:
            self.time_count(b2)
        ram[0xB9] = 1

    def time_count(self, b):
        """BA28: frames (mod 60) at $AE+b, then BCD seconds, minutes, hours (4 digits) at $8F+4b"""
        ram = self.ram
        a = ram[0xAE + b] + 1
        if a >= 0x3C:
            a = 0
        ram[0xAE + b] = a
        if a:
            return
        x = 4 * b
        for o in (0x92, 0x91):
            a, _ = daa_add(ram[o + x], 1)
            if a >= 0x60:
                a = 0
            ram[o + x] = a
            if a:
                return
        lo, c = daa_add(ram[0x90 + x], 1)
        hi, _ = daa_add(ram[0x8F + x], 0, 1 if c else 0)
        ram[0x8F + x], ram[0x90 + x] = hi, lo


    # ---- for the 68000 side (src/mcu.s) --------------------------------------------
    def ticks_left(self, ch):
        """a playing channel: the tick of the next window at which it reads its $FF"""
        c = self.chan(ch)
        n = c.hold
        bv, a = c.bank, c.addr
        hold = False
        while True:
            if a >= 0xC000:
                bv, a = (bv + 1) & 0xFF, 0x4000
            v = self.voice[bank_of(bv) * 0x8000 + a - 0x4000]
            a += 1
            if hold:
                n += 1 + v
                hold = False
            elif v == 0xFF:
                return n
            elif v == 0:
                hold = True
            else:
                n += 1

    def state_image(self):
        """mcu.s's mcu_state..mcu_state_end: the RAM $80-$FF, the end ticks, the port 1 latch, 0"""
        ends = b"".join((self.ticks_left(ch) if self.ram[0xD6 if ch == 0 else 0xDF] else 0).to_bytes(4, "big")
                        for ch in (0, 1))
        return bytes(self.ram[0x80:0x100]) + ends + bytes([self.p1, 0])


def write_tables(path, voice, rom):
    """mcu.s's include: mcu_samples (page 0-15 x sample 1-255: header << 24 | ticks) and mcu_sample_offsets (the
    voice region offset of each header).  Derived from the ROMs: build/ only."""
    lines = ["; generated by games/splatter/tools/mcu.py from the voice ROMs: not for the repository", "\teven",
             "mcu_samples:"]
    offs = ["mcu_sample_offsets:"]
    for nib in range(16):
        for n in range(1, 256):
            bv, addr, off, header = sample_info(voice, nib, n, rom)
            ln = sample_length(voice, nib, n, rom)
            assert ln < 1 << 24
            lines.append("\tdc.l\t$%08X" % (header << 24 | ln))
            offs.append("\tdc.l\t$%06X" % off)
    Path(path).write_text("\n".join(lines + offs) + "\n")


if __name__ == "__main__":
    if "--tables" in sys.argv:
        from namcos1 import load_regions
        from paths import build_dir
        r = load_regions("splatter")
        out = build_dir("splatter") / "mcu_samples.s"
        write_tables(out, r["voice"], r["mcu"])
        print("wrote", out)
        sys.exit(0)
    from namcos1 import load_regions
    v = load_regions("splatter")["voice"]
    for nib in (3, 6):
        for n in range(1, 4):
            vals, header = sample_ticks(v, nib, n)
            print(nib, n, ["%X" % x for x in sample_info(v, nib, n)], len(vals), "ticks, header %02X" % header)
