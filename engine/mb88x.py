"""MB88xx (MB8843 / MB8844) program -> 68000 code that runs without a clock, from wait point to wait point.

The model is games/galaga/tools/machine.py's event-driven 51XX (wait51 / run51): the runtime changes the chip's pins
(set_irq, set_tc, the port values in the state block) and calls <P>_run, which carries on from where the chip stopped
and returns when it reaches a wait point whose condition holds.  A pending interrupt is taken after the next
instruction, as MAME does after each one; it can only become pending while the chip is stopped, so the check follows
the wait points' instructions only.

Every instruction reachable from the reset ($000) and the external interrupt ($002) gets a label <P>_<addr>; JPA
becomes a table of the 16 targets of its page.  CALL / RTS / the interrupt / RTI keep the chip's own four-entry stack
(68000 label addresses and the saved flags in the state block), so a return to the runtime is a plain rts at any depth.

Registers inside: d0 A, d1 X, d2 Y (low nibbles; d2's upper bytes 0), d3 ST, d4 ZF (0 or nonzero), d5 CF (0 / 1),
d6 / d7 / a1 scratch, a0 the state block <P>_state (layout: the S_ constants; RAM first), a2 = a0 + 16 x (X & 3): the
data address X:Y is (a2,d2.w).  The serial port and the internal
timer clock are not translated (the 51XX enables the serial port but never reads it back): their instructions raise.

    python mb88x.py <rom> <prefix> <wait spec> [-o out.s]      (see translate() for the wait specs)
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mb88dis import dis, next_pc

# state block layout (bytes)
S_RAM = 0           # 64 nibbles
S_TL, S_TH, S_VF, S_PIO, S_IRQ, S_INIRQ, S_PEND, S_SI = 64, 65, 66, 67, 68, 69, 70, 71
S_A, S_X, S_Y, S_ST, S_ZF, S_CF, S_CTR, S_SB = 72, 73, 74, 75, 76, 77, 78, 79
S_O, S_P = 80, 81                     # the O output (both nibbles), the last P output
S_R = 82                              # R0-R3 inputs (the runtime sets them)
S_PORTO, S_RW = 86, 87                # 51XX: the shared latch, the R/W line
S_RESUME = 88                         # long: where <P>_run carries on
S_STACK = 92                          # 4 x (long label, bytes ST ZF CF (an interrupt's), 1 spare)
S_SIZE = 124

UNSUPPORTED = {0x17: "TSA", 0x27: "TSTS", 0x2A: "STS", 0x2B: "LS"}   # the serial register read back


def reachable(rom, entries):
    """{address: (text, length, kind)} of every instruction reachable from entries; jpa tables {address: page}"""
    seen, todo, tables = {}, list(entries), {}
    end = len(rom)
    while todo:
        a = todo.pop()
        if a in seen:
            continue
        if a >= end:
            raise ValueError("flow leaves the program at %03X" % a)
        text, n, target = dis(rom, a)
        op = rom[a]
        seen[a] = (text, n)
        nxt = next_pc(a) if n == 1 else next_pc(next_pc(a))
        if op in (0x2C, 0x3C):                    # rts, rti
            continue
        if op == 0x3D:                            # jpa: the 16 entries of the page
            page = rom[next_pc(a)] & 0x1F
            tables[a] = page
            for i in range(16):
                todo.append((page << 6) | (i * 4))
            continue
        if target is not None:
            todo.append(target)
        todo.append(nxt)
    # an instruction must not start inside another
    starts = set(seen)
    for a, (_, n) in seen.items():
        if n == 2 and next_pc(a) in starts:
            raise ValueError("%03X: a jump target inside the instruction at %03X" % (next_pc(a), a))
    return seen, tables


ST, ZF, CF = "st", "zf", "cf"
ALL = frozenset((ST, ZF, CF))
X_Y_CHANGERS = {0x04, 0x08, 0x0A, 0x18, 0x1A, 0x1B} | set(range(0x54, 0x60)) | set(range(0x80, 0x90))
EA_USERS = {0x09, 0x0A, 0x0B, 0x0D, 0x0E, 0x0F, 0x19, 0x1A, 0x1D, 0x1E, 0x1F, 0x2E, 0x2F} | set(range(0x30, 0x3C))


def flag_use_def(op):
    """(flags read, flags written) of an instruction, as the templates below do it"""
    s, z, c = {ST}, {ST, ZF}, {ST, ZF, CF}
    if op in (0x01,):
        return {CF}, s
    if op in (0x0C, 0x0E, 0x1C, 0x1E):
        return {CF}, c
    if op in (0x10, 0x11):
        return {CF}, {CF, ST}
    if op == 0x28:
        return {CF}, s
    if op == 0x29:
        return {ZF}, s
    if op in (0x21, 0x23):
        return set(), {CF, ST}
    if op == 0x2E or 0x70 <= op < 0x80 or 0xA0 <= op < 0xC0:
        return set(), c
    if op == 0x3C:
        return set(), c
    if 0x60 <= op < 0x70 or op >= 0xC0:
        return {ST}, s
    if op in (0x08, 0x09, 0x0A, 0x0B, 0x0D, 0x0F, 0x12, 0x13, 0x14, 0x15, 0x16, 0x19, 0x1A, 0x1B, 0x1F, 0x2F) \
            or 0x50 <= op < 0x60 or 0x80 <= op < 0xA0:
        return set(), z
    return set(), s


def cfg(rom, seen, tables, waits):
    """successors of every instruction (rts: every return site; rti: the instructions after the wait points, where
    the only interrupts are taken), the entries (where a jump, table, return or the runtime lands)"""
    succ, entries = {}, {0x000, 0x002} | set(waits)
    after = lambda a: next_pc(a) if seen[a][1] == 1 else next_pc(next_pc(a))
    returns = {after(a) for a in seen if 0x60 <= rom[a] < 0x68}
    resumes = {after(w) for w in waits}
    entries |= returns
    for a in seen:
        op, nxt = rom[a], after(a)
        if op == 0x2C:
            succ[a] = sorted(returns)
        elif op == 0x3C:
            succ[a] = sorted(resumes)
            entries |= resumes
        elif op == 0x3D:
            page = tables[a]
            succ[a] = [(page << 6) | (i * 4) for i in range(16) if (page << 6) | (i * 4) in seen]
            entries |= set(succ[a])
        elif 0x60 <= op < 0x70:
            t = ((op & 7) << 8) | rom[next_pc(a)]
            succ[a] = [t, nxt]
            entries.add(t)
        elif op >= 0xC0:
            t = (next_pc(a) & ~0x3F) | (op & 0x3F)
            succ[a] = [t, nxt]
            entries.add(t)
        else:
            succ[a] = [nxt]
        if a in waits:
            succ[a] = succ[a] + [0x002]
    return succ, entries


def flag_liveness(rom, seen, succ, waits):
    """the flags live after each instruction (a wait point: all, the runtime may stop or interrupt there)"""
    live_in = {a: set() for a in seen}
    changed = True
    while changed:
        changed = False
        for a in sorted(seen, reverse=True):
            out = set(ALL) if a in waits else set().union(*(live_in.get(t, ALL) for t in succ[a]))
            u, d = flag_use_def(rom[a])
            new = set(ALL) if a in waits else (u | (out - d))
            if new != live_in[a]:
                live_in[a] = new
                changed = True
    return {a: (set(ALL) if a in waits else set().union(*(live_in.get(t, ALL) for t in succ[a]))) for a in seen}


PLAIN = bool(os.environ.get("MB88X_PLAIN"))     # (measurement: without the flag liveness, the address and the quick entry)


class Gen:
    def __init__(self, rom, prefix, waits, k_asm, r_asm=None, o_asm="", p_asm="", rout_asm=None, fast=None):
        self.rom, self.p, self.waits = rom, prefix, waits
        self.fast = fast or {}                  # {wait point: asm for an interrupt pending there (d7 = PEND & PIO)}
        self.k_asm, self.o_asm, self.p_asm = k_asm, o_asm, p_asm
        self.r_asm = r_asm or "\tmove.b\t%d+%s(a0),d0\n" % (S_R, "%s")       # (filled with the port number)
        self.rout_asm = rout_asm or ""
        self.out = []
        self.n = 0

    def L(self, a):
        return "%s_%03X" % (self.p, a)

    def e(self, s):
        self.out.append(s)

    def local(self):
        self.n += 1
        return ".l%d" % self.n

    # ---- pieces ----------------------------------------------------------
    def ea(self):
        """the data address X:Y is (a2,d2.w): a2 = the state block + 16 x (X & 3), kept by every change of X"""

    def st1(self):
        self.e("\tmoveq\t#-1,d3")

    def carry_from_bit4(self, reg, st=True):
        """cf = bit 4 of reg (a result of 0..$1F or a byte borrow); st = !cf (only what is live afterwards)"""
        if CF in self.live:
            self.e("\tmove.b\t%s,d5\n\tlsr.b\t#4,d5\n\tand.b\t#1,d5" % reg)
            if st:
                self.e("\tseq\td3")
        elif st and ST in self.live:
            self.e("\tbtst\t#4,%s\n\tseq\td3" % reg)

    def read_r(self, nreg):
        """d0 = R[n] for n in the register (0-3), via the port snippet"""
        self.e("\tmoveq\t#0,d7\n\tmove.b\t%s,d7\n\tand.w\t#3,d7\n\tmove.b\t%d(a0,d7.w),d0" % (nreg, S_R))

    # ---- one instruction ---------------------------------------------------
    def insn(self, a):
        rom = self.rom
        op = rom[a]
        arg = rom[next_pc(a)]
        nxt = self.L(next_pc(a) if op not in range(0x3D, 0x40) and not (0x60 <= op < 0x70) else next_pc(next_pc(a)))
        e = self.e
        if op in UNSUPPORTED:
            raise NotImplementedError("%03X: %s (the serial register) is not translated" % (a, UNSUPPORTED[op]))
        if op == 0x00:
            self.st1()
        elif op == 0x01:                                       # outO: the nibble the carry selects
            l = self.local()
            e("\tmove.b\t%d(a0),d6\n\ttst.b\td5\n\tbne.s\t%sh\n\tand.b\t#$f0,d6\n\tor.b\td0,d6\n\tbra.s\t%ss" % (S_O, l, l))
            e("%sh:\tand.b\t#$0f,d6\n\tmove.b\td0,d7\n\tlsl.b\t#4,d7\n\tor.b\td7,d6\n%ss:\tmove.b\td6,%d(a0)" % (l, l, S_O))
            e(self.o_asm)
            self.st1()
        elif op == 0x02:
            e("\tmove.b\td0,%d(a0)" % S_P)
            e(self.p_asm)
            self.st1()
        elif op == 0x03:
            e(self.rout_asm)
            self.st1()
        elif op == 0x04:
            e("\tmove.b\td0,d2")
            self.st1()
        elif op in (0x05, 0x06, 0x07):
            e("\tmove.b\td0,%d(a0)" % {5: S_TH, 6: S_TL, 7: S_SB}[op])
            self.st1()
        elif op in (0x08, 0x0A):                               # icy / stic
            if op == 0x0A:
                self.ea()
                e("\tmove.b\td0,(a2,d2.w)")
            e("\taddq.b\t#1,d2\n\tbtst\t#4,d2\n\tseq\td3\n\tand.b\t#$0f,d2\n\tseq\td4")
        elif op in (0x09, 0x19):                               # icm / dcm
            self.ea()
            e("\tmove.b\t(a2,d2.w),d7\n\t%s.b\t#1,d7\n\tbtst\t#4,d7\n\tseq\td3\n\tand.b\t#$0f,d7\n\tseq\td4\n"
              "\tmove.b\td7,(a2,d2.w)" % ("addq" if op == 0x09 else "subq"))
        elif op == 0x0B:                                       # x
            self.ea()
            e("\tmove.b\t(a2,d2.w),d7\n\tmove.b\td0,(a2,d2.w)\n\tmove.b\td7,d0\n\tseq\td4")
            self.st1()
        elif op == 0x0C:                                       # rol
            e("\tadd.b\td0,d0\n\tor.b\td5,d0")
            self.carry_from_bit4("d0")
            e("\tand.b\t#$0f,d0\n\tseq\td4")
        elif op == 0x0D:                                       # l
            self.ea()
            e("\tmove.b\t(a2,d2.w),d0\n\tseq\td4")
            self.st1()
        elif op in (0x0E, 0x1E):                               # adc / sbc
            self.ea()
            if op == 0x0E:
                e("\tmove.b\t(a2,d2.w),d7\n\tadd.b\td0,d7\n\tadd.b\td5,d7")
            else:
                e("\tmove.b\t(a2,d2.w),d7\n\tsub.b\td0,d7\n\tsub.b\td5,d7")
            self.carry_from_bit4("d7")
            e("\tand.b\t#$0f,d7\n\tseq\td4\n\tmove.b\td7,d0")
        elif op in (0x0F, 0x1F):                               # and / or
            self.ea()
            e("\t%s.b\t(a2,d2.w),d0\n\tseq\td4\n\tsne\td3" % ("and" if op == 0x0F else "or"))
        elif op in (0x10, 0x11):                               # daa / das
            l = self.local()
            e("\ttst.b\td5\n\tbne.s\t%sa\n\tcmp.b\t#9,d0\n\tbls.s\t%sn\n%sa:\t%s,d0\n%sn:" %
              (l, l, l, "addq.b\t#6" if op == 0x10 else "add.b\t#10", l))
            self.carry_from_bit4("d0")
            e("\tand.b\t#$0f,d0")
        elif op == 0x12:                                       # inK
            e(self.k_asm)
            e("\tand.b\t#$0f,d0\n\tseq\td4")
            self.st1()
        elif op == 0x13:                                       # inR
            self.read_r("d2")
            e("\tand.b\t#$0f,d0\n\tseq\td4")
            self.st1()
        elif op in (0x14, 0x15, 0x16):                         # tya / ttha / ttla
            e("\tmove.b\t%s,d0\n\tseq\td4" % {0x14: "d2", 0x15: "%d(a0)" % S_TH, 0x16: "%d(a0)" % S_TL}[op])
            self.st1()
        elif op == 0x18:                                       # dcy (ZF kept)
            e("\tsubq.b\t#1,d2\n\tbtst\t#4,d2\n\tseq\td3\n\tand.b\t#$0f,d2")
        elif op == 0x1A:                                       # stdc
            self.ea()
            e("\tmove.b\td0,(a2,d2.w)\n\tsubq.b\t#1,d2\n\tbtst\t#4,d2\n\tseq\td3\n\tand.b\t#$0f,d2\n\tseq\td4")
        elif op == 0x1B:                                       # xx
            e("\texg\td0,d1\n\tmoveq\t#3,d7\n\tand.b\td1,d7\n\tlsl.w\t#4,d7\n\tlea\t(a0,d7.w),a2\n\ttst.b\td0\n\tseq\td4")
            self.st1()
        elif op == 0x1C:                                       # ror
            e("\tlsl.b\t#4,d5\n\tor.b\td5,d0\n\tmove.b\td0,d5\n\tand.b\t#1,d5\n\tseq\td3\n\tlsr.b\t#1,d0\n\tseq\td4")
        elif op == 0x1D:                                       # st
            self.ea()
            e("\tmove.b\td0,(a2,d2.w)")
            self.st1()
        elif op in (0x20, 0x22):                               # setR / rstR: R[Y >> 2] bit Y & 3
            if self.rout_asm:
                raise NotImplementedError("%03X: setR / rstR with R outputs" % a)
            self.st1()                                         # (no R outputs: only the read happens)
        elif op in (0x21, 0x23):                               # setc / rstc
            e("\tmoveq\t#%d,d5" % (1 if op == 0x21 else 0))
            self.st1()
        elif op == 0x24:                                       # tstr
            e("\tmove.b\td2,d7\n\tlsr.b\t#2,d7")
            self.read_r("d7")
            e("\tmove.b\td2,d7\n\tand.b\t#3,d7\n\tbtst\td7,d0\n\tseq\td3")
        elif op == 0x25:                                       # tsti
            e("\ttst.b\t%d(a0)\n\tseq\td3" % S_IRQ)
        elif op == 0x26:                                       # tstv
            e("\ttst.b\t%d(a0)\n\tseq\td3\n\tclr.b\t%d(a0)" % (S_VF, S_VF))
        elif op == 0x28:                                       # tstc
            e("\ttst.b\td5\n\tseq\td3")
        elif op == 0x29:                                       # tstz
            e("\ttst.b\td4\n\tseq\td3")
        elif op == 0x2C:                                       # rts
            e("\tmoveq\t#0,d7\n\tmove.b\t%d(a0),d7\n\tsubq.b\t#1,d7\n\tand.b\t#3,d7\n\tmove.b\td7,%d(a0)\n"
              "\tlsl.w\t#3,d7\n\tmove.l\t%d(a0,d7.w),a1" % (S_SI, S_SI, S_STACK))
            self.st1()
            e("\tjmp\t(a1)")
            return
        elif op == 0x2D:                                       # neg
            e("\tneg.b\td0\n\tand.b\t#$0f,d0\n\tsne\td3")
        elif op == 0x2E:                                       # c
            self.ea()
            e("\tmove.b\t(a2,d2.w),d7\n\tsub.b\td0,d7")
            self.carry_from_bit4("d7", st=False)
            e("\tand.b\t#$0f,d7\n\tsne\td3\n\tseq\td4")
        elif op == 0x2F:                                       # eor
            self.ea()
            e("\tmove.b\t(a2,d2.w),d7\n\teor.b\td7,d0\n\tsne\td3\n\tseq\td4")
        elif 0x30 <= op < 0x3C:                                # sbit / rbit / tbit
            self.ea()
            b = op & 3
            if op < 0x34:
                e("\tbset\t#%d,(a2,d2.w)" % b)
                self.st1()
            elif op < 0x38:
                e("\tbclr\t#%d,(a2,d2.w)" % b)
                self.st1()
            else:
                e("\tbtst\t#%d,(a2,d2.w)\n\tseq\td3" % b)
        elif op == 0x3C:                                       # rti: the flags back
            e("\tclr.b\t%d(a0)" % S_INIRQ)
            e("\tmoveq\t#0,d7\n\tmove.b\t%d(a0),d7\n\tsubq.b\t#1,d7\n\tand.b\t#3,d7\n\tmove.b\td7,%d(a0)\n"
              "\tlsl.w\t#3,d7\n\tlea\t%d(a0,d7.w),a1\n\tmove.b\t(a1)+,d3\n\tmove.b\t(a1)+,d4\n\tmove.b\t(a1),d5\n"
              "\tmove.l\t%d(a0,d7.w),a1\n\tjmp\t(a1)" % (S_SI, S_SI, S_STACK + 4, S_STACK))
            return
        elif op == 0x3D:                                       # jpa: the table of the page
            page = arg & 0x1F
            e("\tmoveq\t#0,d7\n\tmove.b\td0,d7\n\tand.w\t#$0f,d7\n\tlsl.w\t#2,d7\n\tlea\t%s_t%02X,a1\n"
              "\tmove.l\t(a1,d7.w),a1" % (self.p, page))
            self.st1()
            e("\tjmp\t(a1)")
            self.tables.add(page)
            return
        elif op in (0x3E, 0x3F):                               # en / dis
            if op == 0x3E and arg & 0x83:                      # (the serial port itself may run: it is never read back)
                raise NotImplementedError("%03X: EN #$%02X (internal timer clock / timer or serial interrupt)" % (a, arg))
            e("\t%s.b\t#$%02X,%d(a0)" % ("or" if op == 0x3E else "and", arg if op == 0x3E else (~arg) & 0xFF, S_PIO))
            self.st1()
        elif 0x40 <= op < 0x48:                                # setD / rstD: R0 outputs
            if self.rout_asm:
                raise NotImplementedError("%03X: setD / rstD with R outputs" % a)
            self.st1()
        elif 0x48 <= op < 0x4C:                                # tstD: R2 bit
            e("\tmove.b\t%d(a0),d7\n\tbtst\t#%d,d7\n\tseq\td3" % (S_R + 2, op & 3))
        elif 0x4C <= op < 0x50:                                # tba
            e("\tbtst\t#%d,d0\n\tseq\td3" % (op & 3))
        elif 0x50 <= op < 0x58:                                # xd / xyd
            reg = "d0" if op < 0x54 else "d2"
            addr = (op & 3) + (0 if op < 0x54 else 4)
            e("\tmove.b\t%d(a0),d7\n\tmove.b\t%s,%d(a0)\n\tmove.b\td7,%s\n\tseq\td4" % (addr, reg, addr, reg))
            self.st1()
        elif op < 0x60:                                        # lxi
            e("\tmoveq\t#%d,d1\n\tlea\t%d(a0),a2\n\t%s\td4" % (op & 7, 16 * (op & 3), "st" if op & 7 == 0 else "sf"))
            self.st1()
        elif op < 0x70:                                        # call / jpl
            target = self.L(((op & 7) << 8) | arg)
            l = self.local()
            e("\ttst.b\td3\n\tbeq.s\t%s" % l)
            if op < 0x68:
                e("\tmoveq\t#0,d7\n\tmove.b\t%d(a0),d7\n\tlsl.w\t#3,d7\n\tlea\t%s(pc),a1\n\tmove.l\ta1,%d(a0,d7.w)\n"
                  "\tclr.b\t%d(a0,d7.w)\n\tlsr.w\t#3,d7\n\taddq.b\t#1,d7\n\tand.b\t#3,d7\n\tmove.b\td7,%d(a0)" %
                  (S_SI, nxt, S_STACK, S_STACK + 4, S_SI))
            self.st1()
            e("\tjmp\t%s" % target)
            e("%s:" % l)
            self.st1()
        elif op < 0x80:                                        # ai
            e("\tadd.b\t#%d,d0" % (op & 0x0F))
            self.carry_from_bit4("d0")
            e("\tand.b\t#$0f,d0\n\tseq\td4")
        elif op < 0x90:                                        # lyi
            e("\tmoveq\t#%d,d2\n\t%s\td4" % (op & 0x0F, "st" if op & 0x0F == 0 else "sf"))
            self.st1()
        elif op < 0xA0:                                        # li
            e("\tmoveq\t#%d,d0\n\t%s\td4" % (op & 0x0F, "st" if op & 0x0F == 0 else "sf"))
            self.st1()
        elif op < 0xC0:                                        # cyi / ci
            e("\tmoveq\t#%d,d7\n\tsub.b\t%s,d7" % (op & 0x0F, "d2" if op < 0xB0 else "d0"))
            self.carry_from_bit4("d7", st=False)
            e("\tand.b\t#$0f,d7\n\tsne\td3\n\tseq\td4")
        else:                                                  # jmp
            target = self.L((next_pc(a) & ~0x3F) | (op & 0x3F))
            e("\tmove.b\td3,d7")
            self.st1()
            e("\ttst.b\td7\n\tbne\t%s" % target)
        return True

    def quick_entry(self):
        """<P>_run: when the chip stopped at a wait point that still holds (and no interrupt is pending), return
        right away (only d7 used, kept); else the full entry"""
        p, out = self.p, []
        st = "%s_state" % p
        out.append("%s_run:\n\tmove.l\td7,-(sp)\n\tmove.l\t%s+%d,d7" % (p, st, S_RESUME))
        # (the main loop's wait first: most runs find the chip there)
        for i, (a, kind) in enumerate(sorted(self.waits.items(), key=lambda w: (w[1][0] != "timer", w[0]))):
            nx = ".q%d" % (i + 1)
            out.append("\tcmp.l\t#%s,d7\n\tbne\t%s" % (self.L(a), nx))
            out.append("\ttst.b\t%s+%d\n\tbne.s\t.c%d\n\tmove.b\t%s+%d,d7\n\tand.b\t%s+%d,d7\n\tbne%s\t%s" %
                       (st, S_INIRQ, i, st, S_PEND, st, S_PIO, "",
                        ".f%d" % i if a in self.fast and not PLAIN else ".full"))
            out.append(".c%d:" % i)
            if kind[0] == "timer":
                out.append("\ttst.b\t%s+%d\n\tbne\t.full\n\tmove.b\t%s+%d,d7\n\tcmp.b\t%s+%d,d7\n\tbne\t.full" %
                           (st, S_INIRQ, st, kind[1], st, S_TL))
            else:
                out.append("\ttst.b\t%s+%d\n\t%s\t.full" % (st, S_IRQ, "beq" if kind[1] else "bne"))
            out.append("\tmove.l\t(sp)+,d7\n\trts")
            if a in self.fast and not PLAIN:
                out.append(".f%d:\t\t\t\t; an interrupt pending at %03X: the native way (else .full)" % (i, a))
                out.append(self.fast[a] % dict(st=st, **{k: v for k, v in globals().items() if k.startswith("S_")}))
            out.append("%s:" % nx)
        out.append(".full:\tmove.l\t(sp)+,d7")
        return "\n".join(out)

    def prune(self, start):
        """drop the stores of flags that are dead after the instruction (its lines from start on)"""
        dead = {ST: ("\tseq\td3", "\tsne\td3", "\tmoveq\t#-1,d3"), ZF: ("\tseq\td4", "\tsne\td4", "\tst\td4", "\tsf\td4")}
        lines = "\n".join(x for x in self.out[start:] if x).split("\n")
        keep = []
        for ln in lines:
            f = next((k for k, v in dead.items() if ln in v and k not in self.live), None)
            if f:
                self.saved[f] += 1
            else:
                keep.append(ln)
        self.out[start:] = ["\n".join(keep)]

    # ---- the program -------------------------------------------------------
    def wait_check(self, a, kind):
        """at a wait point: a pending interrupt first (it follows this instruction); else stop if the wait holds"""
        p = self.p
        l = self.local()
        e = self.e
        e("\ttst.b\t%d(a0)\n\tbne.s\t%sc\n\tmove.b\t%d(a0),d7\n\tand.b\t%d(a0),d7\n\tbne.s\t%sx" %
          (S_INIRQ, l, S_PEND, S_PIO, l))
        e("%sc:" % l)
        if kind[0] == "timer":                                 # the main loop: the saved timer nibble unchanged
            e("\ttst.b\t%d(a0)\n\tbne.s\t%sx\n\tmove.b\t%d(a0),d7\n\tcmp.b\t%d(a0),d7\n\tbne.s\t%sx" %
              (S_INIRQ, l, kind[1], S_TL, l))
        elif kind[0] == "irq":                                 # the /IRQ line at a level
            e("\ttst.b\t%d(a0)\n\t%s.s\t%sx" % (S_IRQ, "beq" if kind[1] else "bne", l))
        else:
            raise ValueError(kind)
        e("\tlea\t%s(pc),a1\n\tbra\t%s_stop" % (self.L(a), p))
        e("%sx:" % l)

    def irq_check(self, a, after):
        """after a wait point's instruction: take a pending interrupt (the external one: $002)"""
        l = self.local()
        e = self.e
        e("\ttst.b\t%d(a0)\n\tbne.s\t%s\n\tmove.b\t%d(a0),d7\n\tand.b\t%d(a0),d7\n\tbeq.s\t%s" %
          (S_INIRQ, l, S_PEND, S_PIO, l))
        e("\tbtst\t#2,d7\n\tbeq\t%s_bad" % self.p)
        e("\tlea\t%s(pc),a1\n\tbra\t%s_take" % (self.L(after), self.p))
        e("%s:" % l)

    def program(self):
        p, e = self.p, self.e
        seen, tables = reachable(self.rom, [0x000, 0x002] + list(self.waits))
        self.tables = set()
        succ, entries = cfg(self.rom, seen, tables, self.waits)
        live_out = flag_liveness(self.rom, seen, succ, self.waits) if not PLAIN else {a: set(ALL) for a in seen}
        order = sorted(seen)
        preds = {}
        for a in seen:
            for t in succ[a]:
                preds.setdefault(t, set()).add(a)
        ea_out = {}
        self.saved = {"st": 0, "zf": 0, "cf": 0, "ea": 0}
        e("; generated by engine/mb88x.py: do not edit")
        e(self.quick_entry() if not PLAIN else "%s_run:" % p)
        e("%s_full:\n\tmovem.l\td0-d7/a0-a2,-(sp)\n\tlea\t%s_state,a0" % (p, p))
        e("\tmoveq\t#0,d0\n\tmoveq\t#0,d1\n\tmoveq\t#0,d2\n\tmoveq\t#0,d5\n\tmoveq\t#0,d6")
        e("\tmove.b\t%d(a0),d0\n\tmove.b\t%d(a0),d1\n\tmove.b\t%d(a0),d2\n\tmove.b\t%d(a0),d3\n\tmove.b\t%d(a0),d4\n"
          "\tmove.b\t%d(a0),d5\n\tmoveq\t#3,d7\n\tand.b\td1,d7\n\tlsl.w\t#4,d7\n\tlea\t(a0,d7.w),a2\n"
          "\tmove.l\t%d(a0),a1\n\tjmp\t(a1)" % (S_A, S_X, S_Y, S_ST, S_ZF, S_CF, S_RESUME))
        e("%s_stop:\t\t\t\t; a1 = where to carry on\n\tmove.l\ta1,%d(a0)\n\tmove.b\td0,%d(a0)\n\tmove.b\td1,%d(a0)\n"
          "\tmove.b\td2,%d(a0)\n\tmove.b\td3,%d(a0)\n\tmove.b\td4,%d(a0)\n\tmove.b\td5,%d(a0)\n"
          "\tmovem.l\t(sp)+,d0-d7/a0-a2\n\trts" % (p, S_RESUME, S_A, S_X, S_Y, S_ST, S_ZF, S_CF))
        e("%s_take:\t\t\t\t; the interrupt: a1 = the return address, the flags saved\n"
          "\tmoveq\t#0,d7\n\tmove.b\t%d(a0),d7\n\tlsl.w\t#3,d7\n\tmove.l\ta1,%d(a0,d7.w)\n"
          "\tlea\t%d(a0,d7.w),a1\n\tmove.b\td3,(a1)+\n\tmove.b\td4,(a1)+\n\tmove.b\td5,(a1)\n"
          "\tlsr.w\t#3,d7\n\taddq.b\t#1,d7\n\tand.b\t#3,d7\n"
          "\tmove.b\td7,%d(a0)\n\tst\t%d(a0)\n\tclr.b\t%d(a0)\n\tmoveq\t#-1,d3\n\tjmp\t%s" %
          (p, S_SI, S_STACK, S_STACK + 4, S_SI, S_INIRQ, S_PEND, self.L(0x002)))
        e("%s_bad:\t\t\t\t; a jump table entry or an interrupt the program does not have\n\tillegal" % p)
        for i, a in enumerate(order):
            e("%s:\t\t\t\t; %s" % (self.L(a), seen[a][0]))
            if a in self.waits:
                self.wait_check(a, self.waits[a])
            prev = order[i - 1] if i else None
            op = self.rom[a]
            self.ea_valid = (a not in entries and preds.get(a) == {prev} and ea_out.get(prev, False)
                             and op in EA_USERS and not PLAIN)
            if self.ea_valid:
                self.saved["ea"] += 1
            self.live = live_out[a]
            start = len(self.out)
            self.insn(a)
            if op in EA_USERS and op not in (0x0A, 0x1A):
                ea_out[a] = True
            elif op in X_Y_CHANGERS or op == 0x01 or op in EA_USERS:
                ea_out[a] = False
            else:
                ea_out[a] = (a not in entries and preds.get(a) == {prev} and ea_out.get(prev, False))
            self.prune(start)
            n = seen[a][1]
            nxt = next_pc(a) if n == 1 else next_pc(next_pc(a))
            if a in self.waits:
                self.irq_check(a, nxt)
            if op not in (0x2C, 0x3C, 0x3D) and nxt not in seen:
                e("\tbra\t%s_bad" % p)                # (the program never falls through to here)
            elif op not in (0x2C, 0x3C, 0x3D) and order[i + 1:i + 2] != [nxt]:
                e("\tbra\t%s" % self.L(nxt))
        for page in sorted(self.tables):
            e("\tcnop\t0,4\n%s_t%02X:" % (p, page))
            for i in range(16):
                t = (page << 6) | (i * 4)
                e("\tdc.l\t%s" % (self.L(t) if t in seen else p + "_bad"))
        return "\n".join(x for x in self.out if x) + "\n", seen


def translate(rom, prefix, waits, k_asm, o_asm="", p_asm="", fast=None):
    """rom: the program; waits: {address: ("timer", ram address) | ("irq", level)}; k_asm: leaves K in d0 (a0 = the
    state block, d7 free); o_asm: after OUTO (d6 = the O byte); p_asm: after OUTP (d0).  -> (asm text, reachable)"""
    g = Gen(rom, prefix, waits, k_asm, o_asm=o_asm, p_asm=p_asm, fast=fast)
    return g.program()


def support(prefix):
    """the runtime side: the state block, reset, the pins.  <P>_reset (registers as the chip's reset; the RAM kept;
    carry on at $000), <P>_set_irq / <P>_set_tc (d7.b = the level), as MAME's execute_set_input."""
    p = prefix
    return ("""
; generated by engine/mb88x.py: the pins and the reset
%(p)s_S_R = %(sr)d		; the state block: R0-R3 inputs, the 51XX's shared latch and R/W line
%(p)s_S_PORTO = %(sporto)d
%(p)s_S_RW = %(srw)d
%(p)s_S_RESUME = %(sres)d		; (long: where the chip stopped)
%(p)s_reset:				; (the RAM, the pins, the ports and O are kept)
	movem.l	d0/a0-a1,-(sp)
	lea	%(p)s_state,a0
%(clears)s	st	%(st)d(a0)
	moveq	#%(stack_n)d-1,d0
.c:	clr.b	%(stack)d(a0,d0.w)
	dbf	d0,.c
	lea	%(p)s_000,a1
	move.l	a1,%(resume)d(a0)
	movem.l	(sp)+,d0/a0-a1
	rts

%(p)s_set_irq:
	tst.b	%(irq)d+%(p)s_state
	bne.s	.lvl
	tst.b	d7
	beq.s	.lvl
	btst	#2,%(pio)d+%(p)s_state
	beq.s	.lvl
	bset	#2,%(pend)d+%(p)s_state
.lvl:	move.b	d7,%(irq)d+%(p)s_state
	rts

%(p)s_set_tc:
	tst.b	%(ctr)d+%(p)s_state
	beq.s	.lvl
	tst.b	d7
	bne.s	.lvl
	btst	#6,%(pio)d+%(p)s_state
	beq.s	.lvl
	addq.b	#1,%(tl)d+%(p)s_state
	and.b	#$0f,%(tl)d+%(p)s_state
	bne.s	.lvl
	addq.b	#1,%(th)d+%(p)s_state
	and.b	#$0f,%(th)d+%(p)s_state
	bne.s	.lvl
	st	%(vf)d+%(p)s_state
	bset	#1,%(pend)d+%(p)s_state
.lvl:	move.b	d7,%(ctr)d+%(p)s_state
	rts
""" % dict(p=p, sr=S_R, sporto=S_PORTO, srw=S_RW, sres=S_RESUME, st=S_ST, resume=S_RESUME, stack=S_STACK, stack_n=S_SIZE - S_STACK,
           clears="".join("\tclr.b\t%d(a0)\n" % o for o in (S_TL, S_TH, S_VF, S_PIO, S_INIRQ, S_PEND, S_SI, S_A, S_X,
                                                              S_Y, S_ZF, S_CF, S_SB)), irq=S_IRQ, pio=S_PIO, pend=S_PEND, ctr=S_CTR,
           tl=S_TL, th=S_TH, vf=S_VF)).lstrip("\n")


def bss(prefix):
    return "\tcnop\t0,4\n%s_state:\tds.b\t%d\n" % (prefix, S_SIZE)


# The 51XX of Galaga (games/galaga/tools/machine.py: wait51): the main loop at $182 compares the timer's low nibble with
# RAM $09; the coinage command waits for the chip select to end ($00D) and to come again ($010).
WAITS_51XX = {0x182: ("timer", 0x09), 0x00D: ("irq", 1), 0x010: ("irq", 0)}
K_51XX = ("\tmove.b\t%d(a0),d0\n\tlsl.b\t#3,d0\n\tmove.b\t%d(a0),d7\n\tand.b\t#7,d7\n\tor.b\td7,d0" % (S_RW, S_PORTO))
O_51XX = "\tmove.b\td6,%d(a0)" % S_PORTO           # the O output is the shared latch


# The 51XX's read at its main loop's wait (the bulk of its interrupts: three a frame): the interrupt after TTLA, $002
# (XD 0, INK, DIS, JPA #1) -> $060.. JPL $24F (XX, XD 1, XYD 6: Y = the read pointer RAM $06, LXI 2, two OUTO of RAM
# $20+Y / $21+Y, Y + 2, $C -> 4, XYD 6, XD 1: RAM $01 = the high nibble, XX, XD 0: RAM $00 = 2, EN, RTI) and back through $183 (C: RAM $09 = TL,
# not taken, JMP $182) to the wait: A = TL, X, Y kept, ST ZF set, CF clear.  Only when the body is not due (RAM $09 =
# TL) and the R/W line reads (K 8-15); else the translated way.  Checked by engine/mb88x_test.py like the rest.
FAST_51XX = {0x182: """\tbtst\t#2,d7
\tbeq\t.full
\tmove.b\t%(st)s+%(S_TL)d,d7
\tcmp.b\t%(st)s+9,d7
\tbne\t.full
\ttst.b\t%(st)s+%(S_RW)d
\tbeq\t.full
\tmovem.l\td6/a0,-(sp)
\tlea\t%(st)s,a0
\tmoveq\t#15,d7
\tand.b\t6(a0),d7
\tmove.b\t$20(a0,d7.w),d6
\taddq.b\t#1,d7
\tand.b\t#15,d7
\tmove.b\t$20(a0,d7.w),d7
\tmove.b\td7,1(a0)
\tlsl.b\t#4,d7
\tor.b\td7,d6
\tmove.b\td6,%(S_O)d(a0)
\tmove.b\td6,%(S_PORTO)d(a0)
\tmoveq\t#15,d7
\tand.b\t6(a0),d7
\taddq.b\t#2,d7
\tand.b\t#15,d7
\tcmp.b\t#12,d7
\tbne.s\t.fp
\tmoveq\t#4,d7
.fp:\tmove.b\td7,6(a0)
\tmove.b\t#2,(a0)
\tmove.b\t%(S_TL)d(a0),%(S_A)d(a0)
\tst\t%(S_ST)d(a0)
\tst\t%(S_ZF)d(a0)
\tclr.b\t%(S_CF)d(a0)
\tclr.b\t%(S_PEND)d(a0)
\tmovem.l\t(sp)+,d6/a0
\tmove.l\t(sp)+,d7
\trts"""}


def translate_51xx(rom, prefix="N51"):
    text, seen = translate(rom, prefix, WAITS_51XX, K_51XX, o_asm=O_51XX, fast=FAST_51XX)
    return text + support(prefix), seen


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("rom")
    ap.add_argument("-p", "--prefix", default="N51")
    ap.add_argument("-o", "--out")
    a = ap.parse_args()
    text, seen = translate_51xx(open(a.rom, "rb").read(), a.prefix)
    print("%d instructions" % len(seen), file=sys.stderr)
    if a.out:
        open(a.out, "w").write(text + "\n\tsection\tbss,bss\n" + bss(a.prefix))
    else:
        sys.stdout.write(text)
