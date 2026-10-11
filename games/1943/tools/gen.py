"""Bank-aware whole-program 1943 Z80 -> 68000 translation."""
from pathlib import Path
import sys
import pickle
import re
import json
sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[3] / 'engine')]
import os
import z80x, z80dis, discover
from z80x import Emitter, compute_liveness, Unsupported, hx, swap16
from translate import compile_code

from paths import build_dir, require_coverage

WIN_LO, WIN_HI, VBASE = 0x8000, 0xc000, 0x10000
IDLE = 0x00d4
BUILD = build_dir('1943')


def virt(pc, bank):
    return VBASE + bank*0x4000 + pc-WIN_LO


def real(pc):
    return WIN_LO + ((pc-VBASE) & 0x3fff) if pc >= VBASE else pc


def image():
    rom = (BUILD / 'maincpu.rom').read_bytes()
    return rom[:0x8000] + bytes([0x76])*0x8000 + rom[0x10000:]


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


class GameEmitter(Emitter):
    """The main CPU: banked window, stubs, window reads.

    The translator keeps A' BC' DE' HL' in a3 a0 a1 a2, so no address register is free for the
    window: accesses to it use the marker register `aW` in the lines of an instruction, and
    emit_ins turns that into  pea (a0) / move.l g_winbase,a0 ... move.l (sp)+,a0  around the
    instruction (flag neutral: pea and movea leave the CCR alone).  g_winbase = the current
    bank's copy + $8000 (the Z80 address - $10000 is the offset)."""

    def __init__(self, *a, window_sites=(), text_writers=(), **k):
        super().__init__(*a, **k)
        self.window_sites = set(window_sites)
        self.text_writers = set(text_writers)
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
        # (as a signed word, 8000-BFFF is exactly the range below C000)
        return ["lea (a6),aW", "cmp.w #$C000,%s" % reg, "bge.s %s" % l, "move.l g_winbase,aW", l + ":"]

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
        if pc in self.text_writers:
            self.text_mark(self.code[pc])

    def text_mark(self, ins):
        """after a store to the character RAM (D000-D7FF): its block of 32 bytes marked in chr_blocks (0-31 the codes,
        32-63 the attributes; the renderer compares only those), the CCR kept (the flag analysis may keep flags in it)"""
        dst = ins.ops[0]
        if ins.mn != 'ld':
            raise Unsupported('character RAM writer %s' % ins.mn)
        if dst[0] == 'ind16':
            self.e('st chr_blocks+%d' % (((dst[1] - 0xd000) >> 5) & 63))   # (Scc leaves the CCR alone)
            return
        if dst[0] != 'ind' or dst[1] not in ('hl', 'ix', 'iy'):
            raise Unsupported('character RAM writer %r' % (dst,))
        assert 'a0' in self.free_aregs()
        self.e('move sr,d5')
        self.e('move.w %s,d7' % {'hl': 'd3', 'ix': 'd4', 'iy': 'a2'}[dst[1]])
        if dst[2]:
            self.e('add.w #%d,d7' % dst[2])
        self.e('lsr.w #5,d7')
        self.e('and.w #63,d7')                 # (D000 / 32 = $680: the block)
        self.e('lea chr_blocks,a0')
        self.e('st (a0,d7.w)')
        self.e('move d5,ccr')


    def mem(self, addr, off=0, io_read=False):
        if addr >= 0x10000:
            return 'g_iy' if addr == 0x10000 and off == 0 else 'g_fshadow'
        a = (addr + off) & 0xffff
        if WIN_LO <= a < WIN_HI:
            return f'{a-0x10000}(aW)'
        if io_read and 0xc000 <= a <= 0xc004:
            return f'g_inputs+{a-0xc000}'
        if io_read and a == 0xc007:
            return 'g_mcu_response'
        return Emitter.mem(self, addr, off, io_read)

    def dispatch_d7(self):
        self.e('ror.w #8,d7')
        self.e('jmp g_dispatch')

    def label_of(self, pc):
        if WIN_LO <= pc < WIN_HI:
            self.stubs.add(pc)
            return f'BK{pc:04X}'
        return Emitter.label_of(self, pc)

    def x_in(self, ins):
        raise Unsupported('1943 has no mapped input ports')

    def x_out(self, ins):
        raise Unsupported('1943 has no mapped output ports')


def inside(pc):
    """the addresses of code: the fixed ROM and the banks' virtual copies"""
    return pc < 0x8000 or pc >= VBASE


# The fixed ROM's jump tables (`ld hl,T; add hl,de; ld e,(hl); inc hl; ld d,(hl); ex de,hl; jp (hl)`) whose entries the
# coverage runs did not all reach: T -> entries.  Random play reached 5AE2 (2026-10-10: z80_badpc, a silent quit);
# discover's hl_tables finds them too, but also reads data and the banked tables (all covered) as tables.
JUMP_TABLES = {0x59bc: 15,              # 59A4: by (ix+10) & $0F, the type of an object
               0x5c18: 8}               # 5BDE: by e - 1


def table_roots(rom):
    return {rom[t + 2*i] | rom[t + 2*i + 1] << 8 for t, n in JUMP_TABLES.items() for i in range(n)}


def script_handler_roots(rom):
    """The objects' scripts (7-byte records read at 5773, 5D89, 61C1, 6417; 5 bytes at 68D3) call a handler with a
    record 00, lo, hi; most handlers sit right behind their record (the word points 2 bytes on).  The scripts come
    from tables and the banked stage data too, so they are not walked; random play reached 7877 (2026-10-10)."""
    return {a + 2 for a in range(0x100, 0x7ffe) if rom[a - 1] == 0 and rom[a] | rom[a + 1] << 8 == a + 2}


def generate(extra_roots=()):
    rom = image()
    require_coverage('1943', [f'cover{s}.pkl' for s in (1, 2, 3)])
    pcs, wread, twrites, wdata = set(), set(), set(), set()
    for path in BUILD.glob('cover*.pkl'):
        with path.open('rb') as f:
            d = pickle.load(f)
        if d.get('set') != (BUILD / 'set.txt').read_text().strip():
            raise ValueError(f'Coverage set mismatch: {path}')
        for bank, pc in d['pcs']:
            pcs.add(virt(pc, bank) if bank >= 0 else pc)
        for bank, pc in d.get('wread', ()):
            wread.add(virt(pc, bank) if bank >= 0 else pc)
        for bank, pc in d.get('wdata', ()):
            wdata.add(virt(pc, bank) if bank >= 0 else pc)
        for bank, pc in d.get('twrites', ()):
            twrites.add(virt(pc, bank) if bank >= 0 else pc)
    roots = {0, 0x38, 0x66, IDLE, *extra_roots, *table_roots(rom), *script_handler_roots(rom)}
    saved = discover.decode
    discover.decode = decode
    skip_cache = {}
    try:
        while True:
            code, tables = discover.discover(rom, sorted(roots | pcs), known=pcs, rst28_tables=False)
            missing = discover.skip_returns(rom, code, inside, skip_cache) - set(code)  # (the allocators, the compares)
            if not missing:
                break
            roots.update(missing)
    finally:
        discover.decode = saved
    code = {pc: ins for pc, ins in code.items() if pc < 0x8000 or pc >= VBASE}
    cfg = z80x.Config(mode='signed', block=0x10000, table_entries=0xc000,
                      iyaddr=0x10000, fshadow=0x10002, io_read_redirect={},
                      write_hooks=[(0xc804,0xc804,"g_control_w",None),
                                   (0xc806,0xc806,"g_dma",None),
                                   (0xc807,0xc807,"g_mcu_w",None),
                                   (0xd806,0xd806,"g_layer_w",None)],
                      rst28_tables=False, bit_s=True, **z80x.FAST)
    # The indirect reads that may read the banked window get its guard: the block instructions, every site the coverage
    # saw reading the window (data, not its own bytes) and every site it never ran.  A site it ran only with other
    # addresses reads the block directly (a miss would show in logic_test.py: the reference reads the bank).
    # The sites are kept in docs/window-sites.json (a build without coverage files takes them from there; coverage
    # files write it again; W_GUARD_ALL=1 guards every indirect access).  logic_test.py --audit finds sites the coverage
    # missed on Musashi runs (w_sites_audit_*.pkl).
    blocks = ('ldir', 'lddr', 'ldi', 'ldd', 'cpi', 'cpir')
    indirect = {pc for pc, ins in code.items() if ins.mn in blocks or any(o[0] == 'ind' for o in ins.ops)}
    sites_file = Path(__file__).resolve().parents[1] / 'docs' / 'window-sites.json'
    if os.environ.get('W_GUARD_ALL'):
        sites = indirect
    elif pcs:
        sites = {pc for pc in indirect if pc in wdata or pc not in pcs}
        for f in BUILD.glob('w_sites_audit_*.pkl'):
            with f.open('rb') as h:
                sites |= indirect & set(pickle.load(h))
        sites_file.write_text(json.dumps(sorted(sites)) + '\n')
    elif sites_file.exists():
        sites = indirect & set(json.loads(sites_file.read_text()))
    else:
        sites = indirect
    joins = set(roots)                        # (compile_code adds the return points and the code addresses held as numbers)
    for nxt, targets in tables.values():
        joins |= set(targets)
    # The writers of the character RAM (D000-D7FF) the coverage saw set chr_written (the renderer compares the RAM with
    # its copy only then; logic_test.py checks that no change of the RAM comes without it).
    em = compile_code(code, joins, cfg, {IDLE}, emitter=GameEmitter, ijmp_flags=True, flags_at={IDLE}, window_sites=sites,
                      text_writers=twrites)
    out = ['; Generated 1943 main Z80, fixed and eight ROM banks', '\tsection text,code', *em.lines]
    for pc in sorted(em.refs-set(code)):
        out += [f'Z{pc:04X}:', f'\tmove.w #${real(pc):04x},d7', '\tjmp z80_badpc']
    for pc in sorted(em.stubs):
        out += [f'BK{pc:04X}:', f'\tmove.w #${pc:04x},d7', '\tjmp g_dispatch']
    # The entries are read once (init_dispatch): a macro the runtime puts last in the data section, where the screen
    # buffer begins (src/1943.s: its memory is the screen's afterwards).
    out += ['g_entries_data macro', 'g_entries_fixed:']
    for pc in sorted(code):
        if pc < WIN_LO and pc not in em.no_entry:   # (merged: z80_badpc)
            out += [f'\tdc.w ${pc:04x}', f'\tdc.l Z{pc:04X}']
    out += ['\tdc.w $ffff']
    for bank in range(8):
        out += [f'g_entries_bank{bank}:']
        for pc in sorted(code):
            if VBASE+bank*0x4000 <= pc < VBASE+(bank+1)*0x4000 and pc not in em.no_entry:
                out += [f'\tdc.w ${real(pc)-WIN_LO:04x}', f'\tdc.l Z{pc:04X}']
        out += ['\tdc.w $ffff']
    out += ['\tendm', '\tsection data,data', '\teven',
            'g_entry_banks:', '\tdc.l '+','.join(f'g_entries_bank{b}' for b in range(8))]
    report = {'instructions':len(code), 'unsupported':em.unsupported, 'window_sites':len(sites), 'text_writers': len(twrites),
              'unguarded': sum(1 for pc, ins in code.items() if any(o[0] == 'ind' for o in ins.ops) and pc not in sites),
              'banks': sorted({(pc-VBASE)//0x4000 for pc in code if pc>=VBASE})}
    banks = report['banks']
    out += ['g_dispatch_targets:', '\tdc.l '+','.join(f'g_window_dispatch{b}' if b in banks else 'g_invalid_dispatch' for b in range(8)),
            f'G_WINDOW_TABLES = {len(banks)+1}', '\tsection bss,bss', 'g_invalid_dispatch: ds.l 16384']
    for bank in banks:
        out += [f'g_window_dispatch{bank}: ds.l 16384']
    out += ['\tsection text,code']
    return '\n'.join(out)+'\n', report, code


if __name__ == '__main__':
    text, report, _ = generate()
    (BUILD / 'code_1943.s').write_text(text)
    (BUILD / 'translation.json').write_text(json.dumps(report,indent=2)+'\n')
    print(report)
    if report['unsupported']:
        raise SystemExit(1)
