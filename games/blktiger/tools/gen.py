"""Bank-aware whole-program Black Tiger Z80 -> 68000 translation."""
from pathlib import Path
import sys
import pickle
import json
import re
sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[3] / 'engine')]
import z80x, z80dis, discover
from z80x import Emitter, compute_liveness, Unsupported, hx, swap16
from translate import compile_code
from machine import load
from paths import build_dir

WIN_LO, WIN_HI, VBASE = 0x8000, 0xc000, 0x10000
IDLE = 0x00d4
BUILD = build_dir('blktiger')


def virt(pc, bank):
    return VBASE + bank*0x4000 + pc-WIN_LO


def real(pc):
    return WIN_LO + ((pc-VBASE) & 0x3fff) if pc >= VBASE else pc


def image():
    fixed = load('bdu-01a.5e')
    banks = b''.join(load(n) for n in ('bdu-02a.6e','bdu-03a.8e','bd-04.9e','bd-05.10e'))
    return fixed + bytes([0x76])*0x8000 + banks


def decode(rom, pc):
    ins = z80dis.decode(rom, pc)
    if pc < VBASE:
        return ins
    base = (pc-VBASE)//0x4000
    def fix(o):
        if o[0] != 'addr':
            return o
        if ins.mn in ('jr','djnz'):
            # Relative targets wrap at the Z80's 64 KB boundary, not the virtual bank boundary.
            delta = ((o[1] - ((pc+ins.length) & 0xffff) + 0x8000) & 0xffff) - 0x8000
            target = (real(pc)+ins.length+delta) & 0xffff
        else:
            target = o[1]
        return ('addr', virt(target, base) if WIN_LO <= target < WIN_HI else target)
    ops = [fix(o) for o in ins.ops]
    target = next((o[1] for o in ops if o[0]=='addr'), ins.target)
    return ins._replace(ops=ops, target=target)


class BTEmitter(Emitter):
    """The main CPU: banked window, stubs, window reads.

    The translator keeps A' BC' DE' HL' in a3 a0 a1 a2, so no address register is free for the
    window: accesses to it use the marker register `aW` in the lines of an instruction, and
    emit_ins turns that into  pea (a0) / move.l g_winbase,a0 ... move.l (sp)+,a0  around the
    instruction (flag neutral: pea and movea leave the CCR alone).  g_winbase = the current
    bank's copy + $8000 (the Z80 address - $10000 is the offset)."""

    def __init__(self, *a, window_sites=(), **k):
        super().__init__(*a, **k)
        self.window_sites = set(window_sites)
        self.stubs = set()

    def x_ld_i_a(self, ins):                  # the interrupt vector page (the program checks it)
        self.e("move.b d0,g_ireg")

    def x_ld_a_i(self, ins):
        self.e("move.b g_ireg,d0")
        self.e("tst.b d0")
        self.flags(z80x.S | z80x.Z, const_clear=z80x.H | z80x.N)

    def label_of(self, pc):
        if WIN_LO <= pc < WIN_HI:             # a window address from fixed code: the bank decides
            self.stubs.add(pc)
            return "BK%04X" % pc
        return super().label_of(pc)

    def ret_value(self, pc):                  # (a call pushes the real address)
        return real(pc)

    def direct_ok(self, rp):                  # (a return point in the window: which bank it is in, the ret cannot tell)
        return rp in self.code and real(rp) == rp

    def mem(self, addr, off=0, io_read=False):
        a = (addr + off) & 0xFFFF
        if WIN_LO <= a < WIN_HI:
            return "%d(aW)" % (a - 0x10000)
        return super().mem(addr, off, io_read)

    win_src = None

    def ind(self, reg, disp=0):
        if self.win_src == reg:              # a block instruction reading the window
            return "%d(aW,%s.w)" % (disp, reg) if disp else "(aW,%s.w)" % reg
        return super().ind(reg, disp)

    def win_check(self, reg):
        """lines: aW = the window's base if the address in reg is in 8000-BFFF, else a6"""
        l = self.new_label()
        return ["lea (a6),aW", "cmp.w #$8000,%s" % reg, "blo.s %s" % l, "cmp.w #$C000,%s" % reg, "bhs.s %s" % l,
                "move.l g_winbase,aW", l + ":"]

    def block_win(self, fn, ins):
        """a block instruction at a site that read the window: aW = the base of the source (hl)"""
        if ins.pc in self.window_sites:
            for line in self.win_check("d3"):
                self.lines.append(line) if line.endswith(":") else self.e(line)
            self.win_src = "d3"
        try:
            fn(ins)
        finally:
            self.win_src = None

    def x_ldir(self, ins): self.block_win(super().x_ldir, ins)     # (z80x: on address registers, by longs where it can)
    def x_ldi(self, ins): self.block_win(super().x_ldi, ins)
    def x_ldd(self, ins): self.block_win(super().x_ldd, ins)
    def x_lddr(self, ins): self.block_win(super().x_lddr, ins)
    def x_cpi(self, ins): self.block_win(super().x_cpi, ins)
    def x_cpir(self, ins): self.block_win(super().x_cpir, ins)

    def read8(self, op, io_read=True):
        pre, ea = Emitter.read8(self, op, io_read)
        if op[0] == 'ind' and self.cur is not None and self.cur.pc in self.window_sites:
            match = re.fullmatch(r'(-?\d+)?\(a6,(d\d)\.w\)', ea)
            if match:
                pre += self.win_check(match[2])
                ea = f'{match[1] or ""}(aW,{match[2]}.w)'
        return pre, ea

    def emit_ins(self, pc, live_out_override=None, with_label=True):
        n0 = len(self.lines)
        super().emit_ins(pc, live_out_override, with_label)
        self.window_wrap(n0)                  # (z80x: a0 = the window, saved only where it holds BC')


    def mem(self, addr, off=0, io_read=False):
        if addr >= 0x10000:
            return 'g_iy' if addr == 0x10000 and off == 0 else 'g_fshadow'
        a = (addr + off) & 0xffff
        if WIN_LO <= a < WIN_HI:
            return f'{a-0x10000}(aW)'
        return Emitter.mem(self, addr, off, io_read)

    def dispatch_d7(self):
        self.e('ror.w #8,d7')
        self.e('jmp bt_dispatch')

    def label_of(self, pc):
        if WIN_LO <= pc < WIN_HI:
            self.stubs.add(pc)
            return f'BK{pc:04X}'
        return Emitter.label_of(self, pc)

    def x_in(self, ins):
        dst, port = ins.ops
        if dst != ('r8','a') or port[0] != 'port':
            raise Unsupported('non-immediate input port')
        p = port[1] & 255
        if p < 6:
            self.e(f'move.b bt_inputs+{p},d0')
        elif p == 7:
            self.e('move.b g_mcu_response,d0')
        else:
            self.e('move.b #$ff,d0')

    def x_out(self, ins):
        port, src = ins.ops
        if port[0] != 'port' or src != ('r8','a'):
            raise Unsupported('non-immediate output port')
        self.e(f'jsr bt_out_{port[1]&255:02x}')
        if port[1] == 1 and ins.pc >= VBASE:
            self.e(f'move.w #${real(ins.pc+ins.length):04x},d7')
            self.e('jmp bt_dispatch')


def generate(extra_roots=()):
    rom = image()
    pcs = {virt(pc, bank) if bank >= 0 else pc for bank,pc in json.loads((Path(__file__).resolve().parents[1]/"docs"/"translation-roots.json").read_text())}
    wread = set()
    for path in BUILD.glob('cover*.pkl'):
        with path.open('rb') as f:
            d = pickle.load(f)
        for bank, pc in d['pcs']:
            pcs.add(virt(pc, bank) if bank >= 0 else pc)
        for bank, pc in d.get('wread', ()):
            wread.add(virt(pc, bank) if bank >= 0 else pc)
    roots = {0, 0x38, 0x66, IDLE, *extra_roots}
    saved = discover.decode
    discover.decode = decode
    try:
        while True:
            code, tables = discover.discover(rom, sorted(roots | pcs), known=pcs, rst28_tables=False)
            # Object allocators return normally on failure, but use $03c5 to
            # skip the caller's three-byte JP on success. Discover both paths.
            continuations = {pc+6 for pc,ins in code.items()
                             if ins.mn == 'call' and ins.target is not None
                             and 0x412 <= ins.target < 0x550
                             and rom[pc+3] == 0xc3}
            # $0408 dispatches A through a little-endian HL table. Tables
            # end at the earliest following handler, or the first pointer
            # outside their fixed/banked code region.
            for pc,ins in code.items():
                if ins.mn != 'ld' or ins.ops[0] != ('r16','hl') or ins.ops[1][0] != 'imm':
                    continue
                nxt = code.get(pc+ins.length)
                if not nxt or nxt.mn not in ('jp','call') or nxt.target != 0x408:
                    continue
                table = ins.ops[1][1]
                bank = (pc-VBASE)//0x4000 if pc >= VBASE else -1
                window = WIN_LO <= table < WIN_HI
                if window and bank < 0:
                    raise RuntimeError('Fixed dispatcher needs explicit bank roots')
                address = virt(table,bank) if window else table
                boundary = table+256
                for offset in range(0,256,2):
                    if table+offset >= boundary:
                        break
                    target = int.from_bytes(rom[address+offset:address+offset+2],'little')
                    if not (WIN_LO <= target < WIN_HI if window else 0x100 <= target < WIN_LO):
                        break
                    if target > table:
                        boundary = min(boundary,target)
                    continuations.add(virt(target,bank) if window else target)
            # Animation scripts passed to $3006 contain five-byte frames,
            # $00 + code pointer, and $ff + script pointer. A code record can
            # resume at its following record, so discover the complete chain.
            for pc,ins in code.items():
                if ins.mn != 'ld' or ins.ops[0] != ('r16','hl') or ins.ops[1][0] != 'imm':
                    continue
                nxt=code.get(pc+ins.length)
                if not nxt or nxt.mn not in ('jp','call') or nxt.target != 0x3006:
                    continue
                cursor=ins.ops[1][1]
                bank=(pc-VBASE)//0x4000 if pc >= VBASE else -1
                visited=set()
                for _ in range(256):
                    if cursor in visited or not WIN_LO <= cursor < WIN_HI or bank < 0:
                        break
                    visited.add(cursor)
                    addr=virt(cursor,bank)
                    tag=rom[addr]
                    if tag == 0xfe:
                        break
                    if tag in (0,0xff):
                        target=int.from_bytes(rom[addr+1:addr+3],'little')
                        if not WIN_LO <= target < WIN_HI:
                            break
                        if tag == 0xff:
                            cursor=target
                            continue
                        continuations.add(virt(target,bank))
                        cursor+=3
                    elif tag < 128:
                        cursor+=5
                    else:
                        break
            missing = continuations - set(code)
            if not missing:
                break
            roots.update(missing)
    finally:
        discover.decode = saved
    code = {pc: ins for pc, ins in code.items() if pc < 0x8000 or pc >= VBASE}
    cfg = z80x.Config(mode='signed', block=0x10000, table_entries=0xc000,
                      iyaddr=0x10000, fshadow=0x10002, io_read_redirect={}, write_hooks=[],
                      iff_sym='g_iff', rst28_tables=False, bit_s=True, **z80x.FAST)
    # Every indirect read is guarded: coverage must not decide memory semantics.
    sites = {pc for pc, ins in code.items() if any(o[0]=='ind' for o in ins.ops) or ins.mn in ('ldir','lddr','ldi','ldd','cpi','cpir')}
    joins = set(roots)                        # (compile_code adds the return points and the code addresses held as numbers)
    for nxt, targets in tables.values():
        joins |= set(targets)
    em = compile_code(code, joins, cfg, {IDLE}, emitter=BTEmitter, ijmp_flags=True, flags_at={IDLE}, window_sites=sites)
    out = ['; Generated Black Tiger main Z80, fixed and sixteen ROM banks', '\tsection text,code', *em.lines]
    for pc in sorted(em.refs-set(code)):
        out += [f'Z{pc:04X}:', f'\tmove.w #${real(pc):04x},d7', '\tjmp z80_badpc']
    for pc in sorted(em.stubs):
        out += [f'BK{pc:04X}:', f'\tmove.w #${pc:04x},d7', '\tjmp bt_dispatch']
    out += ['\tsection data,data', '\teven', 'bt_entries_fixed:']
    for pc in sorted(code):
        if pc < WIN_LO and pc not in em.no_entry:   # (merged: z80_badpc)
            out += [f'\tdc.w ${pc:04x}', f'\tdc.l Z{pc:04X}']
    out += ['\tdc.w $ffff']
    for bank in range(16):
        out += [f'bt_entries_bank{bank}:']
        for pc in sorted(code):
            if VBASE+bank*0x4000 <= pc < VBASE+(bank+1)*0x4000 and pc not in em.no_entry:
                out += [f'\tdc.w ${real(pc)-WIN_LO:04x}', f'\tdc.l Z{pc:04X}']
        out += ['\tdc.w $ffff']
    out += ['bt_entry_banks:', '\tdc.l '+','.join(f'bt_entries_bank{b}' for b in range(16))]
    report = {'instructions':len(code), 'unsupported':em.unsupported, 'window_sites':len(sites),
              'banks': sorted({(pc-VBASE)//0x4000 for pc in code if pc>=VBASE})}
    banks = report['banks']
    out += ['bt_dispatch_targets:', '\tdc.l '+','.join(f'bt_window_dispatch{b}' if b in banks else 'bt_invalid_dispatch' for b in range(16)),
            f'BT_WINDOW_TABLES = {len(banks)+1}', '\tsection bss,bss', 'bt_invalid_dispatch: ds.l 16384']
    for bank in banks:
        out += [f'bt_window_dispatch{bank}: ds.l 16384']
    out += ['\tsection text,code']
    return '\n'.join(out)+'\n', report, code


if __name__ == '__main__':
    text, report, _ = generate()
    (BUILD / 'code_blktiger.s').write_text(text)
    (BUILD / 'translation.json').write_text(json.dumps(report,indent=2)+'\n')
    print(report)
