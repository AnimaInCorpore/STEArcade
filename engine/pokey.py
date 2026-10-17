"""The POKEY as the sound CPU of MAME 0.289's gauntlet sees it (src/devices/sound/pokey.cpp, pokey.h; BSD-3-Clause,
copyright-holders Brad Oliver, Eric Smith, Juergen Buchmueller).

MAME runs the POKEY as an execute device (device_execute_interface, clock 14.318181 MHz / 8 = 1789772 Hz, the same
as the 6502's): the scheduler runs it in each time slice after the 68010 and the 6502 (gauntlet's device order),
execute_run() steps one chip clock per cycle (step_one_clock: polynomial counters, prescalers, channels, borrows,
pots, keyboard scan).  The sound stream only renders m_out_raw (no state the CPU can read).  So what a read returns
depends on how far the scheduler has run the POKEY: during the 6502's part of a slice the POKEY stands at the end of
the previous slice.

  * read(): machine().scheduler().synchronize() (an empty timer at now: it ends the 6502's slice, so the POKEY then
    catches up to the 6502), then the register from the current state: POTn (m_POTx if its ALLPOT bit is set, else
    the running pot counter), ALLPOT ($00 / internal ^ $FF), KBCODE, RANDOM ($0A: poly9[p9] & $FF with AUDCTL bit 7,
    else (poly17[p17] >> 8) & $FF), SERIN, IRQST ^ $FF, SKSTAT ^ $FF, others $FF.  The 6502's dummy reads (STA abs,X)
    of POKEY registers are reads too: each one synchronizes.
  * write(): synchronize(sync_write): the register changes when that timer fires (after the POKEY ran to the
    writing cycle's end).
  * other scheduler timers: sync_pot (synchronize, from inside execute_run when the pot counter reaches 228 or
    passes a pot's value: it aborts the POKEY's slice), sync_set_irqst (synchronize, when a timer channel underflows
    with its IRQEN bit set), the serial timers (adjust(0)).  No periodic timers.
  * gauntlet: no IRQ callback (IRQST still reads back), no pot / keyboard / serial callbacks.

Interface (like engine/z80mame.py for the board's time slices): POKEY(board); `cycles` = MAME's m_totalcycles plus the
running slice's cycles; run(n) runs n clocks unless abort() is called (then it stops after the current clock) and
returns the clocks run (MAME's `ran`); executed() = clocks of the current run so far (the board's now() during the
POKEY's run: local + executed() * CLOCK_AS).  read(offset), write(offset, data) (offset 0-15).  board.now(),
board.synchronize(fn), board.timer(expire, fn), board.cancel(t); board.pokey_irq(state) if irq_cb is set.

run() advances stretches without anything the CPU could see in one step (polynomials, prescalers, pot counter and the
8- / 16-bit channel counters in closed form; clock by clock only around pot latches, while a borrow counts clocks for
a base-clock channel, or with timer IRQs / serial / two-tone / async modes): the same state as MAME's clock by clock
code (pokey_test.py --selfcheck compares them).  The channel outputs and the stream (audio only) are not kept.

Verified with engine/pokey_test.py against logs of the installed MAME 0.289 binary (every POKEY access of gauntlet's
sound CPU with the chip's polynomial, prescaler, channel, borrow and pot state from MAME's save items).
"""

AS = 10 ** 18
CLOCK = 14318181 // 8                    # 1789772
CLOCK_AS = AS // CLOCK
DIVSHIFT = 0                             # the scheduler's cycle count: divu_64x32(delta >> DIVSHIFT, DIVISOR)
while (CLOCK_AS >> DIVSHIFT) >= 1 << 32:
    DIVSHIFT += 1
DIVISOR = CLOCK_AS >> DIVSHIFT

# AUDC
NOTPOLY5, POLY4, PURE, VOLUME_ONLY = 0x80, 0x40, 0x20, 0x10
# AUDCTL
POLY9, CH1_HICLK, CH3_HICLK, CH12_JOINED, CH34_JOINED, CH1_FILTER, CH2_FILTER, CLK_15KHZ = \
    0x80, 0x40, 0x20, 0x10, 0x08, 0x04, 0x02, 0x01
# IRQ
IRQ_BREAK, IRQ_KEYBD, IRQ_SERIN, IRQ_SEROR, IRQ_SEROC, IRQ_TIMR4, IRQ_TIMR2, IRQ_TIMR1 = \
    0x80, 0x40, 0x20, 0x10, 0x08, 0x04, 0x02, 0x01
# SKSTAT
SK_FRAME, SK_KBERR, SK_OVERRUN, SK_SERIN, SK_SHIFT, SK_KEYBD, SK_BUSY = 0x80, 0x40, 0x20, 0x10, 0x08, 0x04, 0x02
# SKCTL
SK_BREAK, SK_OCLK, SK_ICLK, SK_ASYNC, SK_TWOTONE, SK_PADDLE, SK_RESET, SK_KEYSCAN = \
    0x80, 0x60, 0x30, 0x10, 0x08, 0x04, 0x03, 0x02
DIV_64, DIV_15 = 28, 114
INTMASK = (IRQ_TIMR1, IRQ_TIMR2, 0, IRQ_TIMR4)


def _poly_4_5(size):
    mask = (1 << size) - 1
    lfsr, out = 0, []
    x = size - 1
    for _ in range(mask):
        lfsr = (lfsr << 1) | (~((lfsr >> 2) ^ (lfsr >> x)) & 1)
        out.append(lfsr & mask)
    return out


def _poly_9_17(size):
    mask = (1 << size) - 1
    lfsr, out = mask, []
    for _ in range(mask):
        if size == 17:
            in8 = ((lfsr >> 8) ^ (lfsr >> 13)) & 1
            i = lfsr & 1
            lfsr >>= 1
            lfsr = (lfsr & 0xFF7F) | (in8 << 7)
            lfsr = (i << 16) | lfsr
        else:
            i = (lfsr ^ (lfsr >> 5)) & 1
            lfsr = (lfsr >> 1) | (i << 8)
        out.append(lfsr)
    return out


TAB4, TAB5, TAB9, TAB17 = _poly_4_5(4), _poly_4_5(5), _poly_9_17(9), _poly_9_17(17)
RANDOM9 = bytes(v & 0xFF for v in TAB9)
RANDOM17 = bytes((v >> 8) & 0xFF for v in TAB17)


class POKEY:
    def __init__(self, board):
        self.b = board
        self.cycles = 0
        self.n = 0
        self.icount = 0
        self.stolen = 0
        self.irq_cb = None                       # gauntlet: m_irq_w_cb unconnected
        # pokey_channel: AUDF, AUDC, borrow_cnt, counter (device_start: AUDC = 0xB0; the outputs are audio only)
        self.AUDF = [0, 0, 0, 0]
        self.AUDC = [0xB0] * 4
        self.borrow = [0, 0, 0, 0]
        self.counter = [0, 0, 0, 0]
        self.KBCODE = 0x09
        self.SKCTL = 0
        self.SKSTAT = 0
        self.IRQST = IRQ_SEROC
        self.IRQEN = 0
        self.AUDCTL = 0
        self.p4 = self.p5 = self.p9 = self.p17 = 0
        self.ALLPOT = 0
        self.SERIN = self.SEROUT = 0
        self.pot_counter = 0
        self.kbd_cnt = 0
        self.kbd_latch = 0
        self.kbd_state = 0
        self.serin_shift = 1
        self.serout_shift = 1
        self.serout_full = False
        self.ser_iclk = True
        self.ser_oclk = False
        self.sod_twotone = False
        self.clock_cnt = [0, 0, 0]
        self.POTx = [0] * 8
        self.timers = {}
        # device_reset
        self.potgo()

    # ---- execute interface --------------------------------------------------------------------------------------
    def executed(self):
        return self.n - self.stolen - self.icount

    def abort(self):
        """abort_timeslice(): the rest of the run is stolen; the current clock still finishes"""
        self.stolen += self.icount
        self.icount = 0

    def run(self, n):
        """execute_run(): do { step_one_clock(); icount--; } while (icount > 0); returns the clocks run"""
        self.n = self.icount = n
        self.stolen = 0
        while True:
            q = self.quiet(self.icount - 1)
            if q:
                self.skip(q)
                self.icount -= q
                self.cycles += q
            self.step_one_clock()
            self.icount -= 1
            self.cycles += 1
            if self.icount <= 0:
                break
        return self.n - self.icount - self.stolen      # the scheduler's `ran`

    def _timer(self, name, fn):
        """emu_timer::adjust(attotime::zero): re-arms the device timer"""
        t = self.timers.get(name)
        if t is not None:
            self.b.cancel(t)
        self.timers[name] = self.b.timer(self.b.now(), fn)

    # ---- quiet stretches --------------------------------------------------------------------------------------
    def quiet(self, limit):
        """clocks that skip() can advance in one go before the next clock that must be stepped (at most limit).
        Without timer IRQs and serial / two-tone / async modes the channels cannot raise anything, and skip()
        advances them in closed form; then only a pot latch (sync_pot) must be stepped.  Otherwise only stretches in
        which no counter wraps and no borrow counts down are skipped."""
        if limit <= 0:
            return 0
        sk = self.SKCTL
        if not sk & SK_RESET:
            return 0 if any(self.borrow) else limit
        c114 = self.clock_cnt[2]
        q = limit
        bw = self.borrow
        ctl = self.AUDCTL
        if (bw[1] or bw[3] or (bw[0] and not ctl & CH1_HICLK) or (bw[2] and not ctl & CH3_HICLK)):
            return 0                             # a borrow counts clocks while its channel counts base ticks
        if sk & 0x78 or self.IRQEN & 7:
            if any(self.borrow):
                return 0
            ctl = self.AUDCTL
            d = DIV_15 if ctl & CLK_15KHZ else DIV_64
            cb = c114 if ctl & CLK_15KHZ else self.clock_cnt[1]
            cnt = self.counter
            for ch, hi in ((0, ctl & CH1_HICLK), (2, ctl & CH3_HICLK), (1, None), (3, None)):
                if hi is None and ctl & (CH12_JOINED if ch == 1 else CH34_JOINED):
                    continue
                w = 256 - cnt[ch]                # increments until the counter wraps to 0
                e = w if hi else (d - cb) + (w - 1) * d
                if e - 1 < q:
                    q = e - 1
        if self.pot_counter < 228:
            target = 228
            for p in self.POTx:
                if p + 1 < target:
                    target = p + 1
            k = max(1, target - self.pot_counter)  # calls of step_pot until one latches
            e = k if sk & SK_PADDLE else (DIV_15 - c114) + (k - 1) * DIV_15
            if e - 1 < q:
                q = e - 1
        return q if q > 0 else 0

    def skip(self, q):
        """q clocks of step_one_clock() that quiet() allowed"""
        sk = self.SKCTL
        if not sk & SK_RESET:
            return
        self.p4 = (self.p4 + q) % 15
        self.p5 = (self.p5 + q) % 31
        self.p9 = (self.p9 + q) % 511
        self.p17 = (self.p17 + q) % 131071
        cc = self.clock_cnt
        t28, cc[1] = divmod(cc[1] + q, DIV_64)
        t114, cc[2] = divmod(cc[2] + q, DIV_15)
        ctl = self.AUDCTL
        base = t114 if ctl & CLK_15KHZ else t28
        hi1, hi3 = ctl & CH1_HICLK, ctl & CH3_HICLK
        if ctl & CH12_JOINED:
            self.pair(0, 1, q if hi1 else base, 6 if hi1 else 0)
        else:
            self.single(0, q if hi1 else base, 3 if hi1 else 0)
            self.single(1, base, 0)
        if ctl & CH34_JOINED:
            self.pair(2, 3, q if hi3 else base, 6 if hi3 else 0)
        else:
            self.single(2, q if hi3 else base, 3 if hi3 else 0)
            self.single(3, base, 0)
        if self.pot_counter < 228:
            self.pot_counter += q if sk & SK_PADDLE else t114
        if sk & SK_KEYSCAN:
            self.kbd_cnt = (self.kbd_cnt + t114) % 64

    def single(self, ch, n, d):
        """an 8-bit channel over n increments (clocks at 1.79 MHz: inc_chan(4), the reload d = 3 clocks after the
        wrap; base clock ticks: inc_chan(1), reloaded in the wrapping clock, d = 0)"""
        c, b = self.counter[ch], self.borrow[ch]
        r = self.AUDF[ch] ^ 0xFF
        period = 256 - r + d
        while n:
            if b:
                if n < b:
                    c += n
                    b -= n
                    break
                n -= b
                c, b = r, 0
                n %= period
                continue
            w = 256 - c
            if n < w:
                c += n
                break
            n -= w
            c, b = 0, d
            if not d:
                c = r
                n %= period
        self.counter[ch], self.borrow[ch] = c, b

    def pair(self, lo, hi, n, d):
        """a 16-bit channel pair over n increments of the low channel (1.79 MHz: inc_chan(7), the high channel
        counts d = 6 clocks after the low one wraps; base clock: d = 0); both reload when the high one wraps"""
        c, b, h = self.counter[lo], self.borrow[lo], self.counter[hi]
        rl, rh = self.AUDF[lo] ^ 0xFF, self.AUDF[hi] ^ 0xFF
        period = 256 - rl + d + 256 * (255 - rh)
        while n:
            if b:
                if n < b:
                    c += n
                    b -= n
                    break
                n -= b
                c += b
                b = 0
            else:
                if c == d and h != 0xFF and n >= 256:
                    k = min(n >> 8, 0xFF - h)    # whole low-channel rounds without the high one wrapping
                    h += k
                    n -= k << 8
                    continue
                w = 256 - c
                if n < w:
                    c += n
                    break
                n -= w
                c, b = 0, d
                if d:
                    continue
            h = (h + 1) & 0xFF
            if h == 0:
                c, b, h = rl, 0, rh
                n %= period
        self.counter[lo], self.borrow[lo], self.counter[hi] = c, b, h

    # ---- one clock ----------------------------------------------------------------------------------------------
    def inc_chan(self, ch, cycles):
        c = self.counter[ch] = (self.counter[ch] + 1) & 0xFF
        if c == 0 and self.borrow[ch] == 0:
            self.borrow[ch] = cycles
            m = INTMASK[ch]
            if self.IRQEN & m:
                self.b.synchronize(lambda: self.sync_set_irqst(m))

    def check_borrow(self, ch):
        if self.borrow[ch] > 0:
            self.borrow[ch] -= 1
            return self.borrow[ch] == 0
        return False

    def reset_channel(self, ch):
        self.counter[ch] = self.AUDF[ch] ^ 0xFF
        self.borrow[ch] = 0

    def step_one_clock(self):
        toggle_iclk = toggle_oclk = False
        sk = self.SKCTL
        ctl = self.AUDCTL
        if sk & SK_RESET:
            self.p4 = (self.p4 + 1) % 15
            self.p5 = (self.p5 + 1) % 31
            self.p9 = (self.p9 + 1) % 511
            self.p17 = (self.p17 + 1) % 131071
            cc = self.clock_cnt
            t28 = t114 = False
            cc[1] += 1
            if cc[1] >= DIV_64:
                cc[1] = 0
                t28 = True
            cc[2] += 1
            if cc[2] >= DIV_15:
                cc[2] = 0
                t114 = True
            if ctl & CH1_HICLK:
                self.inc_chan(0, 7 if ctl & CH12_JOINED else 4)
            base = t114 if ctl & CLK_15KHZ else t28
            if not ctl & CH1_HICLK and base:
                self.inc_chan(0, 1)
            async_reset = bool(sk & SK_ASYNC) and not self.SKSTAT & (SK_BUSY | SK_SERIN)
            if async_reset:
                self.ser_iclk = True
            if ctl & CH3_HICLK and not async_reset:
                self.inc_chan(2, 7 if ctl & CH34_JOINED else 4)
            if not ctl & CH3_HICLK and base and not async_reset:
                self.inc_chan(2, 1)
            if base:
                if not ctl & CH12_JOINED:
                    if self.counter[1] == 0xFF and sk & SK_OCLK == 0x60:
                        toggle_oclk = True
                    self.inc_chan(1, 1)
                if not ctl & CH34_JOINED and not async_reset:
                    if self.counter[3] == 0xFF:
                        if sk & SK_ICLK:
                            toggle_iclk = True
                        if sk & SK_OCLK and sk & SK_OCLK != 0x60:
                            toggle_oclk = True
                    self.inc_chan(3, 1)
            if (t114 or sk & SK_PADDLE) and self.pot_counter < 228:
                self.step_pot()
            if t114 and sk & SK_KEYSCAN:
                self.kbd_cnt += 1
                if self.kbd_cnt > 63:
                    self.kbd_cnt = 0               # step_keyboard: no keyboard callback in gauntlet
        if self.check_borrow(2):
            if ctl & CH34_JOINED:
                if self.counter[3] == 0xFF:
                    if sk & SK_ICLK:
                        toggle_iclk = True
                    if sk & SK_OCLK and sk & SK_OCLK != 0x60:
                        toggle_oclk = True
                self.inc_chan(3, 1)
            else:
                self.reset_channel(2)
        if self.check_borrow(3):
            if ctl & CH34_JOINED:
                self.reset_channel(2)
            self.reset_channel(3)
        if sk & SK_TWOTONE and self.borrow[1] == 1:
            self.reset_channel(0)
            self.sod_twotone = not self.sod_twotone
        if self.check_borrow(0):
            if ctl & CH12_JOINED:
                if self.counter[1] == 0xFF and sk & SK_OCLK == 0x60:
                    toggle_oclk = True
                self.inc_chan(1, 1)
            else:
                self.reset_channel(0)
                if sk & SK_TWOTONE and ((not sk & SK_BREAK) if self.IRQST & IRQ_SEROC else self.serout_shift & 1):
                    self.reset_channel(1)
                    self.sod_twotone = not self.sod_twotone
        if self.check_borrow(1):
            if ctl & CH12_JOINED:
                self.reset_channel(0)
            self.reset_channel(1)
        if toggle_iclk:
            self.ser_iclk = not self.ser_iclk
            if not self.ser_iclk:
                self.process_serin()
        if toggle_oclk and (self.serout_full or not self.IRQST & IRQ_SEROC):
            self.ser_oclk = not self.ser_oclk
            if self.ser_oclk:
                self.process_serout()

    def step_pot(self):
        self.pot_counter += 1
        upd = 0
        for pot in range(8):
            if self.POTx[pot] < self.pot_counter or self.pot_counter == 228:
                upd |= 1 << pot
        if upd:
            self.b.synchronize(lambda: self.sync_pot(upd))

    def potgo(self):
        self.ALLPOT = 0
        self.pot_counter = 0
        for pot in range(8):
            self.POTx[pot] = 228                 # no pot callbacks in gauntlet

    # ---- serial (not used by gauntlet: SKCTL = 3) ---------------------------------------------------------------
    def process_serin(self):
        if self.SKSTAT & SK_BUSY:
            self.serin_shift >>= 1
            if not self.SKSTAT & SK_SERIN:
                self.serin_shift |= 1 << 9
            if self.serin_shift & 1:
                self.SKSTAT &= ~SK_BUSY
                self._timer("serin_ready", self.serin_ready_irq)
        elif self.SKSTAT & SK_SERIN:
            self.serin_shift = 1 << 9
            self.SKSTAT |= SK_BUSY

    def process_serout(self):
        if self.serout_shift == 1:
            if self.serout_full:
                self.serout_shift = (self.SEROUT << 1) | (1 << 9)
                self.serout_full = False
                self._timer("serout_ready", self.serout_ready_irq)
            else:
                self._timer("serout_complete", self.serout_complete_irq)
        else:
            last = self.serout_shift & 1
            self.serout_shift >>= 1
            if last != self.serout_shift & 1:
                self._timer("serout_bit", lambda: None)          # serout_transmit_bit: only the SOD / OCLK lines

    def _irq(self, state):
        if self.irq_cb:
            self.irq_cb(state)

    def serout_ready_irq(self):
        self.IRQST &= ~IRQ_SEROC
        if self.IRQEN & IRQ_SEROR:
            self.IRQST |= IRQ_SEROR
            self._irq(1)

    def serout_complete_irq(self):
        self.IRQST |= IRQ_SEROC
        if self.IRQEN & IRQ_SEROC:
            self._irq(1)

    def serin_ready_irq(self):
        if not self.serin_shift & (1 << 9):
            self.SKSTAT |= SK_FRAME
        self.SERIN = (self.serin_shift >> 1) & 0xFF
        if self.IRQST & IRQ_SERIN:
            self.SKSTAT |= SK_OVERRUN
        elif self.IRQEN & IRQ_SERIN:
            self.IRQST |= IRQ_SERIN
            self._irq(1)

    # ---- timer callbacks ----------------------------------------------------------------------------------------
    def sync_pot(self, upd):
        self.ALLPOT |= upd & 0xFF

    def sync_set_irqst(self, m):
        if self.IRQEN & m:
            self.IRQST |= m
            self._irq(1)

    # ---- the bus ------------------------------------------------------------------------------------------------
    def read(self, offset):
        self.b.synchronize(lambda: None)
        return self.peek(offset)

    def peek(self, offset):
        """the register value without the synchronize() (debugger view)"""
        o = offset & 15
        if o < 8:
            return self.POTx[o] if self.ALLPOT & (1 << o) else self.pot_counter
        if o == 8:
            return self.ALLPOT if not self.SKCTL & SK_RESET else self.ALLPOT ^ 0xFF
        if o == 9:
            return self.KBCODE
        if o == 10:
            return RANDOM9[self.p9] if self.AUDCTL & POLY9 else RANDOM17[self.p17]
        if o == 13:
            return self.SERIN
        if o == 14:
            return self.IRQST ^ 0xFF
        if o == 15:
            return self.SKSTAT ^ 0xFF
        return 0xFF

    def write(self, offset, data):
        self.b.synchronize(lambda: self.write_internal(offset, data))

    def write_internal(self, offset, data):
        o = offset & 15
        if o in (0, 2, 4, 6):
            self.AUDF[o >> 1] = data
        elif o in (1, 3, 5, 7):
            self.AUDC[o >> 1] = data
        elif o == 8:
            self.AUDCTL = data
        elif o == 9:                             # STIMER
            for i in range(4):
                self.reset_channel(i)
        elif o == 10:                            # SKREST
            self.SKSTAT &= ~(SK_FRAME | SK_OVERRUN | SK_KBERR)
        elif o == 11:                            # POTGO
            if self.SKCTL & SK_RESET:
                self.potgo()
        elif o == 13:
            self.SEROUT = data
            if self.SKCTL & SK_RESET:
                self.serout_full = True
        elif o == 14:                            # IRQEN
            if self.IRQST & ~data:
                self.IRQST &= IRQ_SEROC | data
            self.IRQEN = data
            if self.IRQEN & self.IRQST & IRQ_SEROC:
                self._irq(1)
            elif not self.IRQEN & self.IRQST:
                self._irq(0)
        elif o == 15:                            # SKCTL
            if data == self.SKCTL:
                return
            self.SKCTL = data
            if not data & SK_RESET:
                self.write_internal(14, 0)
                self.write_internal(10, 0)
                self.p9 = self.p17 = self.p4 = self.p5 = 0
                self.clock_cnt = [0, 0, 0]
                self.serin_shift = 1
                self.serout_shift = 1
                self.serout_full = False
                self.SKSTAT &= ~SK_BUSY
                self._timer("serout_complete", self.serout_complete_irq)
            if not data & SK_KEYSCAN:
                self.SKSTAT &= ~SK_KEYBD
                self.kbd_cnt = 0
                self.kbd_state = 0
            if not data & SK_ICLK:
                self.ser_iclk = True
            if not data & SK_OCLK:
                self.ser_oclk = False
            if data & SK_ASYNC and not self.SKSTAT & SK_BUSY:
                self.reset_channel(2)
                self.reset_channel(3)
