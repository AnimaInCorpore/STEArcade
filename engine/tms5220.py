"""The TMS5220C speech chip as the sound CPU of MAME 0.289's gauntlet sees it (src/devices/sound/tms5220.cpp,
tms5220.h, tms5110r.hxx; BSD-3-Clause, copyright-holders Frank Palazzolo, Aaron Giles, Jonathan Gevaryahu, Raphael
Nabet, Couriersud, Michael Zapf; the stream bookkeeping of src/emu/sound.cpp, BSD-3-Clause, copyright-holders Aaron
Giles, Olivier Galibert).

What is modelled: the FIFO, the commands (speak external, set rate, reset, ...), the frame parser (energy, repeat,
pitch, K1-K10 bits: how many bits a frame takes decides when the FIFO drains), the interpolation counters (IP, PC,
subcycle) that decide when a frame is parsed, TALK / TALKD / SPEN, buffer low / empty, the IRQ pin, the /RS /WS
handshake (m_timer_io_ready: 16 chip clocks after /WS falls, 13 us after /RS falls) and the READY line.  The
synthesized audio (lattice filter, excitation, energy / pitch / K interpolation, RNG) is left out: nothing the CPU can
read depends on it.

MAME's timing:
  * the chip's state advances only in sound stream updates, one stream sample (= one subcycle step of process())
    per 80 chip clocks: clock 14.318181 MHz / 2 / 11 = 650826 Hz -> 8135 samples/s (squeak latch on:
    / 9 = 795454 Hz -> 9943/s).  sound_stream::update() at machine time t (t != 0) renders the samples up to and
    including index floor(t * rate / 10**18) (`written` counts the rendered samples).
  * update() runs at data_w(), readyq_r() (also the 6502's dummy reads of $1030-$103F), status_r(), intq_r(), in the
    m_timer_io_ready callback, when the output gain changes (gauntlet mixer_w bits 5-7: set_output_gain -> update()
    only if the gain differs), when the clock changes (squeak: update(), then the output buffer is resampled, after
    which `written` = floor(t * new_rate / 10**18): that sample is not rendered again), and in sound_manager's
    periodic update (a scheduler timer every 1/50 s from time 0: call `stream_update()` from it).  wsq_w / rsq_w do
    NOT update the stream first: a reset by /RS and /WS low changes the state the next update renders from.
  * scheduler timers: only m_timer_io_ready (board.timer / board.cancel; adjust() re-arms it).  Everything else is
    lazy.  The board must also run the 50 Hz sound update timer (it cuts time slices too).

Interface: TMS5220C(board) with board.now() (machine().time() in attoseconds), board.timer(expire, fn) -> handle,
board.cancel(handle).  data_w(v), wsq_w(state), rsq_w(state), readyq_r() (1 = not ready: gauntlet's $1030 bit 5),
status_r(), intq_r(), set_clock(hz) (gauntlet speech_squeak_w: 14318181 // 2 // (16 - (5 | (state ? 2 : 0))) as
XTAL::value() truncates), set_output_gain(gain), stream_update() (sound_manager's 1/50 s update).  Power-on: the
constructor is device_start + device_reset; gauntlet's 74LS259 (soundctl) then clears its outputs at its own reset
(time 0): call wsq_w(0), rsq_w(0) (both low: reset()).

Verified with engine/tms5220_test.py against logs of the installed MAME 0.289 binary (gauntlet attract mode and a
started game: every sound CPU access to $1030-$103F / $1820 with the chip's internal state from MAME's save items).
"""

AS = 10 ** 18
FIFO_SIZE = 16
NOCOMMAND = 0xFF
RELOAD_TABLE = (0, 2, 4, 6)
ENERGY_BITS, PITCH_BITS = 4, 6                       # tms5220_coeff
KBITS = (5, 5, 4, 4, 4, 4, 4, 3, 3, 3)
NUM_K = 10
SUBC_RELOAD = 1                                      # FORCE_SUBC_RELOAD
CLOCK = 14318181 // 2 // 11                          # 650826: TMS5220C(config, m_tms5220, 14.318181_MHz_XTAL / 2 / 11)


class TMS5220C:
    def __init__(self, board, clock=CLOCK):
        self.b = board
        self.clock = clock
        self.apc = AS // clock                       # m_attoseconds_per_clock
        self.rate = clock // 80                      # stream_alloc(0, 1, clock() / 80)
        self.written = 0                             # the stream's write_sample()
        self.gain = 1.0
        self.timer_io_ready = None
        # device_start
        self.io_ready = True
        self.true_timing = False
        self.rs_ws = 3
        self.write_latch = 0
        self.read_latch = 0
        self.read_byte_register = 0
        self.schedule_dummy_read = False
        self.irq_cb = None                           # m_irq_handler (unconnected in gauntlet)
        self.readyq_cb = None                        # m_readyq_handler (unconnected in gauntlet)
        self.device_reset()

    # ---- device_reset ----------------------------------------------------------------------------------------
    def device_reset(self):
        self.fifo = [0] * FIFO_SIZE
        self.fifo_head = self.fifo_tail = self.fifo_count = self.fifo_bits_taken = 0
        self.SPEN = self.DDIS = self.TALK = self.TALKD = self.previous_talk_status = False
        self.irq_pin = self.ready_pin = False
        self.set_interrupt_state(0)
        self.update_ready_state()
        self.buffer_empty = self.buffer_low = True
        self.command_register = NOCOMMAND
        self.data_latched = False
        self.RDB_flag = False
        self.new_energy = self.new_pitch = 0
        self.new_k = [0] * NUM_K
        self.zpar = self.uv_zpar = False
        self.subcycle = self.c_variant_rate = self.PC = 0
        self.subc_reload = SUBC_RELOAD
        self.OLDE = self.OLDP = True
        self.IP = RELOAD_TABLE[self.c_variant_rate & 3]
        self.schedule_dummy_read = False             # perform_dummy_read (no VSM attached)

    reset = device_reset                             # device_t::reset(): no sound interface pre/post work

    # ---- the stream ------------------------------------------------------------------------------------------
    def stream_update(self):
        """sound_stream::update(): render up to and including the sample at machine time now"""
        t = self.b.now()
        if t == 0:
            return
        n = t * self.rate // AS - self.written + 1
        if n > 0:
            self.written += n
            self.process(n)

    def set_output_gain(self, gain):
        """device_sound_interface::set_output_gain(ALL_OUTPUTS, gain): an update first when the gain changes"""
        if gain != self.gain:
            self.stream_update()
            self.gain = gain

    def set_clock(self, clock):
        """set_unscaled_clock -> device_clock_changed -> m_stream->set_sample_rate(clock / 80)"""
        if clock == self.clock:
            return
        self.clock = clock
        self.apc = AS // clock
        rate = clock // 80
        if rate != self.rate:
            self.stream_update()
            self.rate = rate
            self.written = self.b.now() * rate // AS        # output_buffer_flat::resample: write_sample = si(now)

    # ---- process(): the sample generator, without the audio --------------------------------------------------
    def process(self, size):
        while size > 0:
            if self.TALKD:
                if self.IP == 0 and self.PC == 12 and self.subcycle == 1:
                    self.IP = RELOAD_TABLE[self.c_variant_rate & 3]
                    self.parse_frame()
                    if self.new_energy == 0x0F:
                        self.TALK = self.SPEN = False
                        self.update_fifo_status_and_ints()
                self.subcycle += 1
                if self.subcycle == 2 and self.PC == 12:
                    if self.IP == 7:
                        self.OLDE = self.new_energy == 0
                        self.OLDP = self.new_pitch == 0
                        self.TALKD = self.TALK
                        self.update_fifo_status_and_ints()
                        if not self.TALK and self.SPEN:
                            self.TALK = True
                    self.subcycle = self.subc_reload
                    self.PC = 0
                    self.IP = (self.IP + 1) & 7
                elif self.subcycle == 3:
                    self.subcycle = self.subc_reload
                    self.PC += 1
            else:
                self.subcycle += 1
                if self.subcycle == 2 and self.PC == 12:
                    if self.IP == 7:
                        self.TALKD = self.TALK
                        self.update_fifo_status_and_ints()
                        if not self.TALK and self.SPEN:
                            self.TALK = True
                    self.subcycle = self.subc_reload
                    self.PC = 0
                    self.IP = (self.IP + 1) & 7
                elif self.subcycle == 3:
                    self.subcycle = self.subc_reload
                    self.PC += 1
            size -= 1

    def parse_frame(self):
        self.uv_zpar = self.zpar = False
        if self.c_variant_rate & 4:
            self.IP = RELOAD_TABLE[self.read_bits(2)]
        else:
            self.IP = RELOAD_TABLE[self.c_variant_rate & 3]
        self.update_fifo_status_and_ints()
        if self.DDIS and self.buffer_empty:
            return
        self.new_energy = self.read_bits(ENERGY_BITS)
        self.update_fifo_status_and_ints()
        if self.DDIS and self.buffer_empty:
            return
        if self.new_energy == 0 or self.new_energy == 15:
            return
        rep_flag = self.read_bits(1)
        self.new_pitch = self.read_bits(PITCH_BITS)
        self.uv_zpar = self.new_pitch == 0
        self.update_fifo_status_and_ints()
        if self.DDIS and self.buffer_empty:
            return
        if rep_flag:
            return
        for i in range(4):
            self.new_k[i] = self.read_bits(KBITS[i])
            self.update_fifo_status_and_ints()
            if self.DDIS and self.buffer_empty:
                return
        if self.new_pitch == 0:
            return
        for i in range(4, NUM_K):
            self.new_k[i] = self.read_bits(KBITS[i])
            self.update_fifo_status_and_ints()
            if self.DDIS and self.buffer_empty:
                return

    def read_bits(self, count):
        val = 0
        if self.DDIS:
            while count:
                count -= 1
                val = (val << 1) | ((self.fifo[self.fifo_head] >> self.fifo_bits_taken) & 1)
                self.fifo_bits_taken += 1
                if self.fifo_bits_taken >= 8:
                    self.fifo_count -= 1
                    self.fifo[self.fifo_head] = 0
                    self.fifo_head = (self.fifo_head + 1) % FIFO_SIZE
                    self.fifo_bits_taken = 0
                    self.update_fifo_status_and_ints()
        else:
            val = (1 << count) - 1                   # no VSM: the input floats high
        return val

    # ---- status ------------------------------------------------------------------------------------------------
    def talk_status(self):
        return self.SPEN or self.TALKD

    def update_fifo_status_and_ints(self):
        self.update_ready_state()
        if self.fifo_count <= 8:
            if not self.buffer_low:
                self.buffer_low = True
                self.set_interrupt_state(1)
        else:
            self.buffer_low = False
        if self.fifo_count == 0:
            if not self.buffer_empty:
                self.buffer_empty = True
                self.set_interrupt_state(1)
            if self.DDIS:
                self.TALK = self.SPEN = False
        else:
            self.buffer_empty = False
        if self.previous_talk_status and not self.talk_status():
            self.set_interrupt_state(1)
            self.DDIS = False
            self.previous_talk_status = False
            if self.command_register != NOCOMMAND:
                self.process_command(self.command_register)
                if self.data_latched:
                    self.adjust_io_ready(16 * self.apc)
                else:
                    self.io_ready = True
                self.update_ready_state()
        self.previous_talk_status = self.talk_status()
        if self.rs_ws == 0x01 and not self.RDB_flag:
            self.read_latch = self.status_read(False)

    def set_interrupt_state(self, state):
        if state != self.irq_pin:
            self.irq_pin = state
            if self.irq_cb:
                self.irq_cb(not state)

    def update_ready_state(self):
        state = self.io_ready
        if self.ready_pin != state:
            if self.readyq_cb:
                self.readyq_cb(not state)
            self.ready_pin = state

    def status_read(self, clear_int):
        if self.RDB_flag:
            self.RDB_flag = False
            return self.read_byte_register
        if clear_int:
            self.set_interrupt_state(0)
        return (self.talk_status() << 7) | (self.buffer_low << 6) | (self.buffer_empty << 5)

    def ready_read(self):
        if not self.true_timing:
            return (self.fifo_count < FIFO_SIZE or not self.DDIS) and self.io_ready
        return self.io_ready

    # ---- commands and data -------------------------------------------------------------------------------------
    def process_command(self, cmd):
        self.command_register = cmd
        c = cmd & 0x70
        if c == 0x10:                                # read byte
            if not self.talk_status():
                self.schedule_dummy_read = False
                self.read_byte_register = self.read_bits(8)
                self.RDB_flag = True
                self.command_register = NOCOMMAND
        elif c in (0x00, 0x20):                      # set rate
            self.c_variant_rate = cmd & 0x0F
            self.command_register = NOCOMMAND
        elif c == 0x30:                              # read and branch
            if not self.talk_status():
                self.RDB_flag = False
                self.schedule_dummy_read = False
                self.command_register = NOCOMMAND
        elif c == 0x40:                              # load address
            if not self.talk_status():
                self.schedule_dummy_read = True
                self.command_register = NOCOMMAND
        elif c == 0x50:                              # speak (VSM)
            self.schedule_dummy_read = False
            self.SPEN = True
            self.TALK = True                         # FAST_START_HACK
            self.DDIS = False
            self.zero_frame()
            self.command_register = NOCOMMAND
        elif c == 0x60:                              # speak external
            self.fifo = [0] * FIFO_SIZE
            self.fifo_head = self.fifo_tail = self.fifo_count = self.fifo_bits_taken = 0
            self.DDIS = True
            self.zero_frame()
            self.RDB_flag = False
            self.command_register = NOCOMMAND
        elif c == 0x70:                              # reset
            self.schedule_dummy_read = False
            self.reset()
            self.command_register = NOCOMMAND
        self.update_fifo_status_and_ints()

    def zero_frame(self):
        self.zpar = self.uv_zpar = True
        self.OLDE = self.OLDP = True
        self.new_energy = self.new_pitch = 0
        self.new_k = [0, 0, 0, 0, 0xF, 0xF, 0xF, 7, 7, 7]

    def data_write(self, data):
        old_buffer_low = self.buffer_low
        if self.DDIS:
            if self.fifo_count < FIFO_SIZE:
                self.fifo[self.fifo_tail] = data
                self.fifo_tail = (self.fifo_tail + 1) % FIFO_SIZE
                self.fifo_count += 1
                self.update_fifo_status_and_ints()
                if not self.SPEN and old_buffer_low and not self.buffer_low:
                    self.zpar = self.uv_zpar = True
                    self.OLDE = self.OLDP = True
                    self.SPEN = True
                    self.TALK = True                 # FAST_START_HACK
                    self.new_energy = self.new_pitch = 0
                    self.new_k = [0, 0, 0, 0, 0xF, 0xF, 0xF, 7, 7, 7]
            self.data_latched = False
        else:
            self.process_command(data)
        if not self.data_latched:
            self.io_ready = True

    # ---- m_timer_io_ready --------------------------------------------------------------------------------------
    def adjust_io_ready(self, delay):
        if self.timer_io_ready is not None:
            self.b.cancel(self.timer_io_ready)
        self.timer_io_ready = self.b.timer(self.b.now() + delay, self.set_io_ready)

    def set_io_ready(self):
        self.timer_io_ready = None
        self.stream_update()
        rw = self.rs_ws
        if rw == 0x02:
            if self.fifo_count >= FIFO_SIZE and self.DDIS:
                self.adjust_io_ready(16 * self.apc)
            elif self.command_register == NOCOMMAND:
                self.data_latched = False
                self.data_write(self.write_latch)
        elif rw == 0x01:
            self.read_latch = self.status_read(True)
            self.io_ready = True
        else:
            self.io_ready = True
        self.update_ready_state()

    # ---- the pins ----------------------------------------------------------------------------------------------
    def rsq_w(self, state):
        self.true_timing = True
        state &= 1
        new_val = (self.rs_ws & 1) | (state << 1)
        if new_val != self.rs_ws:
            self.rs_ws = new_val
            if new_val == 0:
                self.reset()
                return
            if new_val == 3:
                self.read_latch = 0xFF
                return
            if not state:
                self.io_ready = False
                self.update_ready_state()
                self.adjust_io_ready(13 * 10 ** 12)             # attotime::from_usec(13)

    def wsq_w(self, state):
        self.true_timing = True
        state &= 1
        new_val = (self.rs_ws & 2) | state
        if new_val != self.rs_ws:
            self.rs_ws = new_val
            if new_val == 0:
                self.reset()
                return
            if new_val == 3:
                self.read_latch = 0xFF
                return
            if not state:
                self.io_ready = False
                self.update_ready_state()
                self.adjust_io_ready(16 * self.apc)             # clocks_to_attotime(16)

    def data_w(self, data):
        self.stream_update()
        self.write_latch = data
        self.data_latched = True
        if not self.true_timing:
            self.data_write(data)

    def status_r(self):
        self.stream_update()
        if not self.true_timing:
            return self.status_read(True)
        if self.rs_ws == 0x01:
            return self.read_latch
        return 0xFF

    def readyq_r(self):
        self.stream_update()
        return int(not self.ready_read())

    def intq_r(self):
        self.stream_update()
        return int(not self.irq_pin)
