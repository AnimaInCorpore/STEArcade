"""The STE runtime's schedule in Python, for the patched program (tools/patch.py) and for the original one.

    m = PortModel(patched=True)       # the STE's image and memory map (build/gauntlet/program.bin), instance 1
    a = PortModel(patched=False)      # the arcade's ROM and map, the real slapstic, instance 0
    m.step()                          # one VBL: the game's IRQ 4 handler, then its main program up to an idle point

The runtime does not interleave anything with the 68010 program: at each vertical blank it runs the game's IRQ 4
handler (vector 28, as an interrupt) and then lets the game's main program run until it waits (IDLE: the main
loop's wait for the frame counter $904002 at $40C22; the BIOS's delay loop at boot); the waiting is where the STE
draws.  The sound board is the runtime's model (SoundModel: the commands are kept, the status reads "no command
pending"; tools/sound_hle.py later), the inputs are words in the I/O block.  So both programs, run this way, must
leave the same memory at every idle point: tools/logic_test.py compares them (the arcade's windows at their STE
addresses in the patched one).  An access of the patched program outside the STE map (an arcade address the
patcher missed) stops it with the instruction's address.
"""
from pathlib import Path
import sys

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "engine"))
import m68kmame as M
from machine import main_rom, mirrors, SLAPSTIC_104, SLAPSTIC_BANKS, SLAPSTIC_START, BANK_COPY
from patch import MAP, IMAGE_END, HOOKS, HOOKS_AT, HOOK_SIZE
from paths import build_dir

STUBS = 0x50000                      # (the STE runtime's routines; here: an rts each, the work done in Python)
COUNTER = 0x904002                   # the frame counter the IRQ 4 handler increments and the main loop waits for
IDLE = {0x40C28: "main loop: the frame counter was 0 (the STE: TRAP #14 in place of bra.s $40C22)",
        0x40F88: "the queue at $904FA8 is not empty (jsr $4802; tst.l d0; bne.s $40F80: the STE: TRAP #13)"}
IRQ4 = 4
IRQ6 = 6
VBL_INSTRUCTIONS = 25000             # a VBL comes after this many instructions of the program if it does not wait
                                     # before (the STE's 160,256 cycles; counted outside the patched sites, so both
                                     # builds are interrupted at the same instruction)
FRAME_LIMIT = 4000000                # cycles without an idle point or a VBL: something is wrong


class LeakError(RuntimeError):
    pass


class SoundModel:
    """the sound board as the STE's runtime answers (the protocol: tools/sound_hle.py): a command is taken at once (the
    status never shows one pending); $03 (the coins) replies the coin byte, $07 (the watchdog's ping) 0, $06 $E2; the
    sound CPU's start (Q7 rising) replies $FF.  Replies raise IRQ 6 when the game's frame is done (at its wait,
    before the picture gets the time; the BIOS sets its block pointer after the write, with IRQ 6 open: the 6502
    answers ~80 us later, a reply at once would miss it) and at the VBL before the IRQ 4, one after another in order.  The coins: 2-bit counters in the coin
    byte (coin 1 bits 7-6 ... coin 4 bits 1-0), one count a press."""

    REPLIES = {0x03: None, 0x06: 0xE2, 0x07: 0x00}

    def __init__(self):
        self.commands = []
        self.reset_bit = 1
        self.coin_byte = 0
        self.pending = []

    def command(self, frame, v):
        v &= 0xFF
        self.commands.append((frame, v))
        if v in self.REPLIES:
            self.pending.append(self.coin_byte if v == 0x03 else self.REPLIES[v])

    def reset(self, state):
        if state and not self.reset_bit:
            self.pending.append(0xFF)
        self.reset_bit = state

    def coin(self, k):
        sh = 6 - 2 * k
        self.coin_byte = (self.coin_byte & ~(3 << sh)) | ((((self.coin_byte >> sh) + 1) & 3) << sh)


class PortModel:
    def __init__(self, patched, instance=None):
        self.patched = patched
        self.frame = 0
        self.inputs = [0xFFFF] * 4
        self.sound = SoundModel()
        self.pf_marks = set()               # the playfield quarter columns (32 bytes) the patched program's writers marked
        self.al_marked = False              # the alphanumerics' writers ran (patch.HOOKS, mem_clear)
        self.stopped = None
        self.leak = None
        inst = (1 if patched else 0) if instance is None else instance
        cpu = self.cpu = M.M68010(self.rd, self.wr, instance=inst)
        self.mem = cpu.mem
        rom = main_rom()
        self.banks = [rom[0x38000 + b * 0x2000:0x3A000 + b * 0x2000] for b in range(4)]
        self.bank = SLAPSTIC_START
        if patched:
            image = (build_dir("gauntlet") / "program.bin").read_bytes()
            self.mem[:IMAGE_END] = np.frombuffer(image, np.uint8)
            cpu.map(0, IMAGE_END - 1, M.ROM)                 # (the STE's RAM: a write here would change the program)
            for name, lo, hi, ste in MAP:
                cpu.map(ste & ~0xFFF, (ste + hi - lo - 1) | 0xFFF, M.RAM)
            self.win = {name: ste for name, lo, hi, ste in MAP}
            self.load_window(self.bank)
            cpu.map(STUBS, STUBS + 0xFFF, M.ROM)
            self.stub_names = {}
            for k, name in enumerate(sorted({n for _, _, n in __import__("patch").SITES})):
                a = STUBS + 2 * k
                self.mem[a:a + 2] = (0x4E, 0x75)            # rts
                self.stub_names[name] = a
                cpu.hook(a, lambda pc, name=name: self.stub(name))
            self.link_sites()
            # the hooks (patch.HOOKS): the instruction and rts at the STE's address, the mark taken in Python
            import json
            for k, (pc, n, words) in enumerate(json.loads((build_dir("gauntlet") / "hooks.json").read_text())):
                a = HOOKS_AT + HOOK_SIZE * k
                for i, w in enumerate(list(words) + [0x4E75]):
                    self.mem[a + 2 * i] = w >> 8
                    self.mem[a + 2 * i + 1] = w & 0xFF
                cpu.hook(a, self.al_hook)
            # everything else: an arcade address the patcher missed
            for p in range(4096):
                if self.cpu.modes[p] == M.UNMAPPED:
                    self.cpu.modes[p] = M.CALLBACK
        else:
            self.mem[:0x80000] = np.frombuffer(rom, np.uint8)
            for b in range(4):
                self.mem[BANK_COPY + b * 0x2000:BANK_COPY + (b + 1) * 0x2000] = np.frombuffer(self.banks[b], np.uint8)
            cpu.map(0, 0x37FFF, M.ROM)
            cpu.map(0x40000, 0x7FFFF, M.ROM)
            cpu.map(0x38000, 0x3FFFF, M.ROM)
            for lo, hi in ((0x800000, 0x801FFF), (0x900000, 0x905FFF), (0x910000, 0x910FFF), (0x930000, 0x930FFF)):
                cpu.map(lo, hi, M.RAM)
            cpu.map(0x802000, 0x802FFF, M.RAM)
            cpu.map(0x803000, 0x803FFF, M.CALLBACK)
            self.win = {name: lo for name, lo, hi, ste in MAP}
            self.slapstic()
        self.mem[self.win["eeprom"]:self.win["eeprom"] + 0x400] = 0xFF
        for pc in IDLE:
            cpu.hook(pc, self.idle)
        from patch import SITES
        excl = [a for pc, n, _ in SITES for a in range(pc, pc + n, 2)]
        excl += [a for pc, n in HOOKS for a in range(pc, pc + n, 2)]
        if patched:
            excl += list(range(STUBS, STUBS + 0x1000, 2))
        else:
            excl += list(range(0x4FED0, 0x4FF26, 2))         # (the slapstic's routines: the STE's replace them)
        cpu.budget(0, excl)
        cpu.hook(0x34A, lambda pc: cpu.set_input(IRQ4, 0))      # (the handler's entry: the VBL was taken)
        cpu.hook(0x36C, self.irq6_taken)
        self.reply = 0xFF
        cpu.reset()
        self.load_boot()

    def load_boot(self):
        """tools/boot.py's state at the BIOS's hand-off (the registers that hold window addresses relocated)"""
        import struct
        from patch import ste_addr
        d = (build_dir("gauntlet") / "boot.bin").read_bytes()
        parts = [("vram", 0x6000), ("palette", 0x800), ("ram", 0x2000), ("eeprom", 0x400)]
        k = 0
        for name, n in parts:
            self.mem[self.win[name]:self.win[name] + n] = np.frombuffer(d[k:k + n], np.uint8)
            k += n
        if self.patched:
            # the BIOS's pointers in its variables and on its stack ($904000-$904FFF: longs with a window address)
            base = self.win["vram"] + 0x4000
            for o in range(0, 0x1000 - 3, 2):
                v = int.from_bytes(bytes(self.mem[base + o:base + o + 4]), "big")
                if ste_addr(v) is not None:
                    self.mem[base + o:base + o + 4] = np.frombuffer(ste_addr(v).to_bytes(4, "big"), np.uint8)
        *regs, sr, pc, bank = struct.unpack(">16IHIH", d[k:k + 72])
        c = self.cpu
        c.run(0)                                 # (the reset's vector fetch and cycles, so the registers stay set)
        for i, v in enumerate(regs):
            if self.patched and ste_addr(v) is not None:
                v = ste_addr(v)
            c.set(i, v)
        c.set(M.SR, sr)
        if self.patched and ste_addr(regs[15]) is not None:
            c.set(M.ISP, ste_addr(regs[15]))
        c.set(M.PC, pc)
        if self.patched:
            self.load_window(bank)
        assert bank == SLAPSTIC_START

    # ---- the arcade's slapstic (the original program) ---------------------------------
    def slapstic(self):
        rng = ~(0x7FFF | 0x280000) & 0xFFFFFFFF
        val, sh, inp = 0x38000, 1, 0x3FFF << 1
        tin = lambda mv: ((rng | (mv[0] << sh)) & 0xFFFFFFFF, val | (mv[1] << sh))
        d = SLAPSTIC_104
        tests = [((rng | inp) & 0xFFFFFFFF, val)] + [((rng | inp) & 0xFFFFFFFF, val | (b << sh)) for b in SLAPSTIC_BANKS]
        tests += [(d["alt1"][0] << sh, d["alt1"][1] << sh), tin(d["bit1"]), tin(d["alt2"]), tin(d["alt3"]),
                  tin(d["alt4"]), tin(d["bit2"])]
        tests += [tin(d[k]) for k in ("bit3c0", "bit3s0", "bit3c1", "bit3s1")]
        tests += [tin(d[k]) for k in ("bit3s1", "bit3c1", "bit3s0", "bit3c0")]
        tests += [tin(d["bit4"])]
        pages = [p for s, e in mirrors(0x38000, 0x3FFFF, 0) for p in range(s >> 12, (e >> 12) + 1)]
        self.cpu.slapstic(tests, sh, pages, [BANK_COPY + b * 0x2000 for b in range(4)], SLAPSTIC_START)

    # ---- the patched program's runtime calls --------------------------------------------
    def load_window(self, bank):
        """the STE's bank switch: the bank into all four mirrors of $38000-$3FFFF"""
        self.bank = bank
        data = np.frombuffer(self.banks[bank], np.uint8)
        for k in range(4):
            self.mem[0x38000 + k * 0x2000:0x3A000 + k * 0x2000] = data

    def link_sites(self):
        """each site: jsr (or jmp) the runtime's routine, nops to the original length"""
        from patch import SITES
        for pc, n, name in SITES:
            op = 0x4EF9 if name.startswith("slap") else 0x4EB9
            words = [op, self.stub_names[name] >> 16, self.stub_names[name] & 0xFFFF] + [0x4E71] * ((n - 6) // 2)
            for i, w in enumerate(words):
                self.mem[pc + 2 * i] = w >> 8
                self.mem[pc + 2 * i + 1] = w & 0xFF

    def bank_of(self, a):
        """the bank a direct-switch access selects ($38040/50/60/70 and their mirrors), else None"""
        a &= 0xFFFFFF
        if a & ~(0x7FFF | 0x280000) & 0xFFFFFF != 0x38000:
            return None
        sel = (a >> 1) & 0x3FFF
        return SLAPSTIC_BANKS.index(sel) if sel in SLAPSTIC_BANKS else None

    def stub(self, name):
        c = self.cpu
        if name == "snd_cmd_d0":
            self.sound.command(self.frame, c.d(0))
        elif name == "snd_cmd_sp10":
            sp = c.a(7)
            self.sound.command(self.frame, (int(self.mem[sp + 0xE]) << 8) | int(self.mem[sp + 0xF]))
        elif name == "snd_reset_d0":
            self.sound.reset(c.d(0) & 1)
        elif name == "slap_bank0":
            self.load_window(0)
        elif name == "slap_bank3":
            self.load_window(3)
        elif name == "slap_a0d0":
            d0 = c.d(0) & 0xFFFF
            a = (c.a(0) + (d0 - 0x10000 if d0 & 0x8000 else d0)) & 0xFFFFFF
            b = self.bank_of(a)
            if b is not None:
                self.load_window(b)
        elif name == "slap_a0":
            a = c.a(0) & 0xFFFFFE
            v = self.mem[a:a + 2].copy()                  # (the read sees the old bank, then the switch)
            b = self.bank_of(a)
            if b is not None:
                self.load_window(b)
            a1 = c.a(1) & 0xFFFFFE
            self.mem[a1:a1 + 2] = v
        elif name.startswith("pf_blk_"):                 # addi.l #130,dN; the block at a2: its two columns marked
            r = int(name[-1])
            c.set(r, c.d(r) + 130)
            o = c.a(2) - self.win["vram"]                    # (each word's quarter column: 32 bytes)
            self.pf_marks |= {((o + d) >> 5) & 255 for d in (0, 2, 128, 130)}
        elif name == "mem_clear":                        # move.w (6,a7),d0; movea.l (8,a7),a0 (+4: the jsr)
            sp = c.a(7)
            w = (int(self.mem[sp + 10]) << 8) | int(self.mem[sp + 11])
            c.set(0, (c.d(0) & 0xFFFF0000) | w)
            a0 = int.from_bytes(bytes(self.mem[sp + 12:sp + 16]), "big")
            c.set(8, a0)
            if a0 < self.win["vram"] + 0x2000:
                self.pf_marks |= set(range(256))
            n = w - 0x10000 if w & 0x8000 else w
            if a0 < self.win["vram"] + 0x5F00 and a0 + 2 * n > self.win["vram"] + 0x5000:
                self.al_marked = True

    def al_hook(self, pc):
        self.al_marked = True

    # ---- the sound replies -------------------------------------------------------------------
    def irq6_taken(self, pc):
        """the handler's entry: the reply is in the latch now; the next one (if any) after its RTE"""
        self.reply = self.sound.pending.pop(0) if self.sound.pending else 0xFF
        if self.patched:
            self.mem[self.win["io"] + 0xF] = self.reply
        self.cpu.set_input(IRQ6, 1 if self.sound.pending else 0)

    # ---- memory callbacks --------------------------------------------------------------
    def io_read(self, o):
        if o < 8:
            return self.inputs[o >> 1]
        if o == 8:
            return 0x0048                     # service off, nothing pending, not in the vertical blank
        if o == 0x0E:
            return 0xFF00 | self.reply
        return 0xFFFF

    def rd(self, a, mask, kind):
        if not self.patched and a >> 12 == 0x803:
            return self.io_read(a & 0xFFF)
        self.leak = (a, "read", self.cpu.get(M.PPC))
        self.cpu.abort()
        return 0xFFFF

    def wr(self, a, v, mask):
        if not self.patched and a >> 12 == 0x803:
            o = a & 0xFFF
            if o == 0x170 and mask & 0xFF:
                self.sound.command(self.frame, v)
            elif o == 0x12E and mask & 0xFF:
                self.sound.reset(v & 1)
            return
        self.leak = (a, "write", self.cpu.get(M.PPC))
        self.cpu.abort()

    # ---- the schedule --------------------------------------------------------------------
    def put_io(self):
        """the patched program reads the I/O block from RAM: the runtime keeps it"""
        if self.patched:
            io = self.win["io"]
            for k, v in enumerate(self.inputs):
                self.mem[io + 2 * k] = v >> 8
                self.mem[io + 2 * k + 1] = v & 0xFF
            self.mem[io + 8:io + 10] = (0x00, 0x48)
            self.mem[io + 0xE] = 0xFF

    def idle(self, pc):
        """(a hook runs before its instruction, the abort ends the slice after it: the bra / bne is taken, the frame
        ends at its target as the STE's trap handler resumes there)"""
        if pc == 0x40F88 and not self.cpu.d(0):
            return                             # (the queue is empty: on)
        if self.sound.pending:                 # (sound replies first: IRQ 6, then the wait again)
            self.cpu.set_input(IRQ6, 1)
            self.cpu.abort()                   # (Musashi looks at the lines when a slice starts)
            return
        self.stopped = pc
        self.cpu.abort()

    def step(self):
        """one VBL: IRQ 4, then the main program up to its next idle point"""
        self.stopped = None
        if self.frame:                         # (the first: the program starts with the VBL's IRQ 4 not asked for)
            if self.sound.pending:
                self.cpu.set_input(IRQ6, 1)
            self.cpu.set_input(IRQ4, 1)
        self.put_io()
        self.cpu.budget(VBL_INSTRUCTIONS, None)
        spent = 0
        while self.stopped is None:
            spent += self.cpu.run(20000)
            if self.cpu.counted() >= VBL_INSTRUCTIONS:
                self.stopped = "busy"
                break
            if self.leak:
                a, rw, pc = self.leak
                raise LeakError("%s of $%06X at pc $%06X (frame %d)" % (rw, a, pc, self.frame))
            if spent > FRAME_LIMIT:
                import collections
                self.cpu.trace(True)
                self.cpu.run(20000)
                hot = collections.Counter(pc for pc, _ in self.cpu.take_trace()).most_common(8)
                self.cpu.trace(False)
                raise RuntimeError("no idle point in %d cycles (frame %d; hot: %s)" % (
                    spent, self.frame, " ".join("%06X" % pc for pc, _ in hot)))
        self.frame += 1
        self.cycles = spent
        return self.stopped

    # ---- comparing ---------------------------------------------------------------------------
    def window_bytes(self, name):
        lo, hi = next((l, h) for n, l, h, s in MAP if n == name)
        b = self.win[name]
        return bytes(self.mem[b:b + hi - lo])
