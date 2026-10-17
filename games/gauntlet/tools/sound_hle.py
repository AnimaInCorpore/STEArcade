"""Gauntlet's sound board as the main CPU sees it: a high-level model ("HLE") for the STE port, where the 6502 does not
run.  Worked out from the sound program (136037-120.16r / -119.16s) and checked against the reference board
(tools/sound_hle_test.py).

THE PROTOCOL (6502 side; addresses of the sound CPU)

Latches: one byte each way (generic_latch_8).  Main -> sound: the command ($803171 write; the 6502's NMI; $803008
bit 5 while unread).  Sound -> main: the response ($1000-$100F write; the main CPU's IRQ 6; $803008 bit 4 while
unread; the main CPU reads it at $80300F, which clears it).

Boot / reset (Q7 of the main 74LS259, $80312E bit 0; low holds the 6502 in reset and clears the response's pending
flag): the 6502's reset code ($599E) waits for "command pending and response not pending" (it never boots without a
command), then initialises (zero page cleared, queues reset, chips silenced: about 1.39 ms; with the service switch
on it runs its self-test first: RAM, ROM checksums, IRQ), reads the command (discarded) and replies $FF.  On the way
it writes $FF,$33,$00,$22,$0F to the response latch within 15 us (left-over 6522 set-up writes into $1000-$100F;
the main CPU never sees them, the last write before it reads is $FF).  The main BIOS's reset ($42F8, jump table
$254): Q7 low, read $80300E (clears the response), write the command (0), Q7 high.

Commands (NMI $5729: waits until the response is not pending, then reads the latch):
    $03  coin query: replies at once (in the NMI) the coin byte, then waits in the NMI until the main CPU read it
    $06  replies $E2 (the number of commands; the main CPU's service mode sound test uses it)
    $07  ping / status: replies the status byte $02 (0 when all is well: bit 0 "main loop not run since the last
         ping", bit 2 "no IRQ since the last ping", bits 3-7 self-test errors (RAM / ROM checksums))
    $E1  replies $55 (through the 6502's reply ring, sent by its main loop; unused by the game)
    $00-$E1 otherwise: queued for the 6502's main loop (sound only, no reply); $E2-$FF ignored.
Type table $5D6A[cmd] (handler $4630[type], argument $5E4C[cmd]): $00 stop all (type 2), $01/$02 set the speech
priority floor $1B (= arg * 4: $01 -> $F0 = speech off, $02 -> 0 = all speech on), $08 and $51-$DC speech (type
$0A, phrase = arg 0-$8C), $09-$50 sounds (type 6: music and effects on YM2151 + POKEY), $30/$32/$34/$36 stop a
sound (type 4), $43 (type 8: stop a group), $48 (type 9), $DD-$E0 mixer volumes (type $0C), $E1 (type 7).
A reply that the RAM test fails is $10 (then the 6502 halts).

Coins: the coin switches are on the 6502 ($1020 bits 3..0 = coin 1..4, active low).  Its IRQ (lines 32, 96, 160,
224: four a frame, after boot) debounces each slot (the byte $3A+slot, see irq_tick) and counts a coin when the
switch was down for at least 5 IRQs (but less than about 210: a jammed switch counts nothing) and then up for 8
IRQs (2 frames).  The counts are two-bit counters in the coin byte $40: coin 1 bits 7-6, coin 2 bits 5-4, coin 3
bits 3-2, coin 4 bits 1-0 (+$40/+$10/+$04/+$01 a coin, mod 4).  With the service switch on (test mode), the coin
byte is the raw switches instead ($40/$10/$04/$01 while a coin switch is down).  The 6502 reads the switches 0.1
to over 1 ms after each IRQ (its handler feeds the TMS5220 and runs the music first); while a speech phrase starts
the handler can overrun the next IRQ and one of the frame's four samples is lost.  irq_tick is exact per sample
taken; real coin pulses (several frames) count the same either way.

Main CPU side (BIOS $4198-$432C, jump table $15A/$178/$23C/$242/$254): every vertical blank ($40394 -> $41FA) it
sends $03 with a "block request" ($4198: (5,A1) = count 1, (6,A1) = destination $904F8E); the IRQ 6 handler
($36C -> $4001E -> $17E -> $427A) stores a reply into the block while one is requested, otherwise into the ring
$904F98 (16 bytes, $42C8 reads it).  $41FA compares the new coin byte with the previous one and credits the
difference ($35C4).  The ring is read once a frame by the sound watchdog $40E84: after a reset it waits up to 180
frames for $FF; every 240 frames it pings with $07 and wants a reply with (reply & 7) == 0 within 30 frames; a
missing reply, a wrong one or any other reply in the ring resets the sound board ($40F3E -> $254 with command 0).
Sound commands go through $242 (one try: fails while $803008 bit 5 is set; $48064 keeps an 8-entry queue and
retries it every frame, $4811A).  In test mode (service, $803008 bit 3 low) IRQ 6 stores the reply at $90400E and
the test code waits for it ($27AC: send, wait up to 30 frames).

TIMING on the reference board (MAME 0.289): a command is read 38-43 us after the main CPU's write, an immediate
reply ($03/$06/$07) is written 77-82 us after it; the main CPU reads it ~40 us later (IRQ 6).  The boot's $FF is
written 1.38 ms after Q7 rises (command already pending).

FOR THE STE PORT: there are no latches; the runtime traps the main CPU's accesses:
  * write $803171 (command): if booted, process it (a few instructions); remember a reply for $03/$06/$07/$E1.
    Bit 5 can then always read 0 (the command is gone at once), except after a reset before the boot reply.
  * deliver a reply as IRQ 6 (vector 30) NOT at once: the BIOS sets its block pointer ((6,A1)) after the write, with
    IRQ 6 unmasked (SR $2500); a reply before that lands in the ring and the watchdog resets the board.  Any point
    after the sending routine returned works: e.g. at the end of the vertical-blank handler, or an MFP timer
    (also level 6 on the ST) ~100 us later.  $803008 bit 4 = a reply is waiting; reading $80300F returns it and
    clears it (and IRQ 6).
  * write $80312E bit 0 (Q7): 0 = held in reset (forget a waiting reply, not booted); 1 = boots on the pending
    command: a frame later (or any small delay), reply $FF.
  * coins: once a frame run irq_tick four times with the switches (or an equivalent counter per slot); the reply to
    $03 is the coin byte.
"""

AS_PER_US = 10 ** 12

CMD_COINS, CMD_COUNT, CMD_PING, CMD_ECHO = 0x03, 0x06, 0x07, 0xE1
N_COMMANDS = 0xE2
COIN_FIELD = [0x40, 0x10, 0x04, 0x01]      # coin 1..4: the increment in the coin byte (bits 7-6, 5-4, 3-2, 1-0)
COIN_SWITCH = [0x08, 0x04, 0x02, 0x01]     # coin 1..4 in the 6502's $1020 (active low)



class SoundHLE:
    """The sound board seen from the main CPU.  Times are in the caller's units (`unit` = units per microsecond;
    default attoseconds as tools/machine.py counts).  Call advance(t) before looking at status(); after each call
    next_event() is the time of the next internal change (None if none).

    The 6502's NMI nests: a command written while an immediate reply is being prepared is still taken (40 us after
    its write) and delays that reply to 24 us after that; a command waits only while a reply sits unread in the
    latch."""

    CONSUME_US = 40          # command written -> read by the 6502 (bit 5 clears)
    REPLY_US = 80            # command written -> its immediate reply in the latch (bit 4, IRQ 6)
    NEST_US = 24             # a nested command taken -> the delayed reply written
    BOOT_US = 1385           # Q7 high with a command pending -> boot reply $FF

    def __init__(self, unit=AS_PER_US):
        self.u = unit
        self.service = False
        self.in_reset = True             # machine reset: Q7 low
        self.booted = False
        self.boot_at = None              # the boot reply's time (Q7 high and a command pending)
        self.boot_from = None            # Q7's rise (the 6502 waits for a command)
        self.cmd_pending = False
        self.cmd = 0
        self.cmd_time = 0
        self.consume_at = None
        self.resp_pending = False
        self.resp = 0
        self.free_time = 0               # when the response latch was last emptied
        self.replies_due = []            # immediate replies not written yet (values; -1 = the coin byte)
        self.reply_at = None             # when the first of them is written
        self.reset_coins()
        self.log = []                    # [(time, command)] the commands the 6502 took (the boot's included)
        self.replies = []                # [(time, value)] the replies written

    # ---- coins (the 6502's IRQ routine $80C9) -----------------------------
    def reset_coins(self):
        self.coin_state = [0, 0, 0, 0]   # $3A-$3D (zero page cleared at boot)
        self.coin_byte = 0               # $40
        self.ticks = 0                   # $3E

    def irq_tick(self, switches):
        """one of the 6502's four IRQs a frame (lines 32, 96, 160, 224); switches = its $1020 (bits 3..0 = coin
        1..4, active low)"""
        if not self.booted:
            return
        for k in range(4):
            pressed = not switches & COIN_SWITCH[k]
            f = COIN_FIELD[k]
            if self.service:
                self.coin_byte = (self.coin_byte & ~(3 * f)) | (f if pressed else 0)
                continue
            s = self.coin_state[k]
            low = s & 0x1F
            if pressed:
                if low == 0:
                    s = 0
                elif low >= 0x1B or (self.ticks & 7) == 7:
                    s = low - 1
                else:
                    s = low
            elif low >= 0x1B:
                s = 0x1F                 # too short: not a coin
            elif s + 0x20 < 0x100:
                s += 0x20                # counting the IRQs released (8 needed)
            else:
                if low:                  # (held down too long: low reached 0, no coin)
                    self.coin_byte = (self.coin_byte & ~(3 * f)) | ((self.coin_byte + f) & (3 * f))
                s = 0x1F
            self.coin_state[k] = s
        self.ticks = (self.ticks + 1) & 0xFF

    def frame(self, switches):
        for _ in range(4):
            self.irq_tick(switches)

    # ---- the main CPU's accesses ------------------------------------------
    def status(self):
        """$803008 bits 4 (response pending: also the IRQ 6 line) and 5 (command pending)"""
        return (0x10 if self.resp_pending else 0) | (0x20 if self.cmd_pending else 0)

    def command(self, v, t):
        """the main CPU wrote the command latch ($803171); an unread command is replaced"""
        self.advance(t)
        self.cmd, self.cmd_pending, self.cmd_time = v & 0xFF, True, t
        if self.reply_at is not None and t < self.reply_at:
            # its NMI comes before the reply is written: the reply waits for the nested NMI
            self.reply_at = max(self.reply_at, t + (self.CONSUME_US + self.NEST_US) * self.u)
        self._plan()

    def read_reply(self, t):
        """the main CPU read $80300E/F: the latch's value (the last one written), the pending flag cleared"""
        self.advance(t)
        if self.resp_pending:
            self.resp_pending = False
            self.free_time = t
            if self.replies_due and self.reply_at is None:
                self.reply_at = t + self.NEST_US * self.u
            self._plan()
        return self.resp

    def reset(self, state, t):
        """Q7 ($80312E bit 0): 0 holds the 6502 in reset (and clears the response's pending flag); 1 lets it boot"""
        self.advance(t)
        if not state:
            self.in_reset, self.booted = True, False
            self.boot_from = self.boot_at = self.consume_at = self.reply_at = None
            self.replies_due = []
            self.resp_pending = False
        elif self.in_reset:
            self.in_reset = False
            self.boot_from = t
            self._plan()

    # ---- the 6502's side --------------------------------------------------
    def next_event(self):
        ts = [x for x in (self.boot_at, self.consume_at, self.reply_at) if x is not None]
        return min(ts) if ts else None

    def advance(self, t):
        while True:
            when = self.next_event()
            if when is None or when > t:
                return
            if when == self.boot_at:
                self.boot_at = self.boot_from = None
                self.cmd_pending = False
                self.log.append((when, self.cmd))
                self.booted = True
                self.reset_coins()
                self._write(when, 0xFF)
            elif when == self.consume_at:
                self.consume_at = None
                self.cmd_pending = False
                self.log.append((when, self.cmd))
                r = self.reply_for(self.cmd)
                if self.replies_due and self.reply_at is not None:     # nested in a reply's NMI: delays it
                    self.reply_at = max(self.reply_at, when + self.NEST_US * self.u)
                if r is not None:
                    self.replies_due.append(r)
                    if self.reply_at is None and not self.resp_pending:
                        self.reply_at = max(when, self.cmd_time + self.REPLY_US * self.u)
            else:
                self.reply_at = None
                v = self.replies_due.pop(0)
                self._write(when, self.coin_byte if v == -1 else v)
            self._plan()

    def reply_for(self, v):
        if v == CMD_COINS:
            return -1                    # the coin byte at the reply's time
        if v == CMD_COUNT:
            return N_COMMANDS
        if v == CMD_PING:
            return 0x00
        if v == CMD_ECHO:
            return 0x55
        return None

    def _write(self, t, v):
        self.resp, self.resp_pending = v, True
        self.replies.append((t, v))

    def _plan(self):
        """the 6502 takes a command only while the response latch is empty"""
        if not self.cmd_pending or self.resp_pending or self.in_reset:
            return
        if not self.booted:
            if self.boot_from is not None and self.boot_at is None:
                self.boot_at = max(self.boot_from, self.cmd_time, self.free_time) + self.BOOT_US * self.u
            return
        if self.consume_at is None:
            self.consume_at = max(self.cmd_time, self.free_time) + self.CONSUME_US * self.u
