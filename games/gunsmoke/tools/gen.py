"""Bank-aware whole-program Gun.Smoke Z80 -> 68000 translation.

    python gen.py   ->  build/gunsmoke/code_gunsmoke.s (+ translation.json)

The main CPU's program: 0000-7FFF fixed, 8000-BFFF a window onto one of four 16 KB banks (C804 bits 2-3).  Code runs
from the window too (banks 0 and 2), so window code has virtual pcs VBASE + bank * $4000 + (pc - $8000), the way Black
Tiger's generator does it (games/blktiger/tools/gen.py): a jump from fixed code into the window goes through a stub
that dispatches by the current bank, a computed jump (ret, jp (hl)) through gs_dispatch with the natural pc.  Every
indirect read is guarded as a possible window read (coverage does not decide memory semantics).  The program is a
cooperative kernel; the interrupt (RST 38) is delivered by the runtime at the scheduler's idle point (IDLE, see
machine.py run_frame_port).  The service mode (DSW1 bit 7, code in bank 3 at 8000) is not exercised and not translated:
its jump lands on a `z80_badpc` stub.
"""
from pathlib import Path
import sys
import pickle
import json
import re
sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[3] / 'engine')]
import z80x, z80dis, discover
from z80x import Emitter
from translate import compile_code
from paths import build_dir, require_coverage

WIN_LO, WIN_HI, VBASE = 0x8000, 0xc000, 0x10000
IDLE = 0x00ce                  # the scheduler found no ready task (machine.py IDLE): the runtime's hook
RESCAN = 0x00b0                # where the interrupt returns to (the runtime pushes it as the return address)
LATCH_SITES = {0x0295, 0x02b1} # `ld (de),a` with DE = C804 (bank, text on, flip) or D806 (layers): gs_latch after the store
# E0F8-E0FB is a trampoline the program writes into RAM (08BB: call nnnn / ret, nnnn at E0F9): `call $E0F8` calls the
# round script's code.  It is native code here (TRAMPOLINE); its targets are entries (coverage 'jumps').
TRAMPOLINE = '''ZE0F8:
	move.w #$FBE0,-(a5)
	moveq #0,d7
	move.b -$1F06(a6),d7
	lsl.w #8,d7
	move.b -$1F07(a6),d7
	jmp gs_dispatch
ZE0FB:
	moveq #0,d7
	move.w (a5)+,d7
	ror.w #8,d7
	jmp gs_dispatch'''
BUILD = build_dir('gunsmoke')


def virt(pc, bank):
    return VBASE + bank * 0x4000 + pc - WIN_LO


def real(pc):
    return WIN_LO + ((pc - VBASE) & 0x3fff) if pc >= VBASE else pc


def image():
    rom = (BUILD / 'maincpu.rom').read_bytes()
    return rom[:0x8000] + bytes([0x76]) * 0x8000 + rom[0x8000:0x18000]


def decode(rom, pc):
    """the instruction at a virtual pc: targets in the window stay in the bank of the instruction"""
    ins = z80dis.decode(rom, pc)
    if pc < VBASE:
        return ins
    base = (pc - VBASE) // 0x4000

    def fix(o):
        if o[0] != 'addr':
            return o
        if ins.mn in ('jr', 'djnz'):
            delta = ((o[1] - ((pc + ins.length) & 0xffff) + 0x8000) & 0xffff) - 0x8000
            target = (real(pc) + ins.length + delta) & 0xffff
        else:
            target = o[1]
        return ('addr', virt(target, base) if WIN_LO <= target < WIN_HI else target)
    ops = [fix(o) for o in ins.ops]
    target = next((o[1] for o in ops if o[0] == 'addr'), ins.target)
    return ins._replace(ops=ops, target=target)


class GSEmitter(Emitter):
    """Window accesses use the marker register `aW` (Emitter.window_wrap: a0 = g_winbase, the current bank's copy +
    $8000, so the Z80 address - $10000 is the offset)."""

    def __init__(self, *a, text_sites=(), **k):
        super().__init__(*a, **k)
        self.text_sites = set(text_sites)
        self.stubs = set()

    def label_of(self, pc):
        if WIN_LO <= pc < WIN_HI:             # a window address from fixed code: the bank decides
            self.stubs.add(pc)
            return 'BK%04X' % pc
        return super().label_of(pc)

    def ret_value(self, pc):                  # (a call pushes the real address)
        return real(pc)

    def direct_ok(self, rp):                  # (a return point in the window: the ret cannot tell its bank)
        return rp in self.code and real(rp) == rp

    def mem(self, addr, off=0, io_read=False):
        a = (addr + off) & 0xffff
        if WIN_LO <= a < WIN_HI:
            return '%d(aW)' % (a - 0x10000)
        return super().mem(addr, off, io_read)

    win_src = None

    def ind(self, reg, disp=0):
        if self.win_src == reg:              # a block instruction reading the window
            return '%d(aW,%s.w)' % (disp, reg) if disp else '(aW,%s.w)' % reg
        return super().ind(reg, disp)

    def win_check(self, reg):
        """lines: aW = the window's base if the address in reg is in 8000-BFFF, else a6"""
        l = self.new_label()
        # (as a signed word, 8000-BFFF is exactly the range below C000)
        return ['lea (a6),aW', 'cmp.w #$C000,%s' % reg, 'bge.s %s' % l, 'move.l g_winbase,aW', l + ':']

    def block_win(self, fn, ins):
        for line in self.win_check('d3'):
            self.lines.append(line) if line.endswith(':') else self.e(line)
        self.win_src = 'd3'
        try:
            fn(ins)
        finally:
            self.win_src = None

    def x_ldir(self, ins): self.block_win(super().x_ldir, ins)
    def x_ldi(self, ins): self.block_win(super().x_ldi, ins)
    def x_ldd(self, ins): self.block_win(super().x_ldd, ins)
    def x_lddr(self, ins): self.block_win(super().x_lddr, ins)
    def x_cpi(self, ins): self.block_win(super().x_cpi, ins)
    def x_cpir(self, ins): self.block_win(super().x_cpir, ins)

    storing = False

    def write8(self, op, src_ea):             # (z80x's write8 takes its address from read8: a store is not guarded)
        self.storing = True
        try:
            return super().write8(op, src_ea)
        finally:
            self.storing = False

    def read8(self, op, io_read=True):
        """every read through (hl) / (de) / (bc) / (ix+d) / (iy+d) checks for the window (also bit n,(hl) and the
        read-modify-write forms, whose read8 calls pass io_read=False)"""
        pre, ea = Emitter.read8(self, op, io_read)
        if op[0] == 'ind' and not self.storing:
            match = re.fullmatch(r'(-?\d+)?\(a6,(d\d|a2)\.w\)', ea)
            if match:
                reg = match[2]
                if reg == 'a2':                 # (IY: the low word of a2, its upper word is not 0)
                    pre += ['move.w a2,d5']
                    reg = 'd5'
                pre += self.win_check(reg)
                ea = f'{match[1] or ""}(aW,{match[2]}.w)'
        return pre, ea

    def emit_ins(self, pc, live_out_override=None, with_label=True):
        n0 = len(self.lines)
        super().emit_ins(pc, live_out_override, with_label)
        self.window_wrap(n0)                  # (z80x: a0 = the window)
        if pc in LATCH_SITES:
            self.e('bsr gs_latch')              # (the byte is stored already; the routine reads it from the block)
        if pc in self.text_sites:
            self.e('st fg_written')             # (Scc leaves the flags alone)

    def dispatch_d7(self):
        self.e('ror.w #8,d7')
        self.e('jmp gs_dispatch')


def coverage():
    require_coverage('gunsmoke', [f'cover{s}.pkl' for s in range(1, 15)])
    pcs, text, jumps = set(), set(), set()
    for path in sorted(BUILD.glob('cover*.pkl')):
        d = pickle.loads(path.read_bytes())
        pcs |= {virt(pc, bank) if bank >= 0 else pc for bank, pc in d['pcs']}
        text |= {virt(pc, bank) if bank >= 0 else pc for bank, pc, a in d['writes'] if 0xd000 <= a < 0xd800}
        jumps |= {virt(pc, bank) if bank >= 0 else pc for bank, pc in d.get('jumps', ())}
    return pcs - {0xe0f8, 0xe0fb}, text, jumps


def generate():
    rom = image()
    pcs, text_sites, jumps = coverage()
    roots = {0, 0x38, IDLE, RESCAN} | jumps
    saved = discover.decode
    discover.decode = decode
    skip_cache = {}
    try:
        while True:
            code, tables = discover.discover(rom, sorted(roots | pcs), known=pcs, rst28_tables=False)
            # functions that return past the caller's next bytes (pop hl; inc hl ...; jp (hl)): the compares of
            # 8 / 4 bytes at 0365 return to the call + 2 / + 4 (a jr each) when equal / greater (2026-10-10: 15
            # of these continuations were untranslated)
            missing = discover.skip_returns(rom, code, lambda pc: pc < WIN_LO or pc >= VBASE, skip_cache) - set(code)
            if not missing:
                break
            roots |= missing
    finally:
        discover.decode = saved
    code = {pc: ins for pc, ins in code.items() if pc < WIN_LO or pc >= VBASE}
    cfg = z80x.Config(mode='signed', block=0x10000, table_entries=0xc000,
                      iyaddr=0x10000, fshadow=0x10002, io_read_redirect={}, write_hooks=[(0xc806, 0xc806, 'buffer_sprites', None)],
                      rst28_tables=False, bit_s=True, **z80x.FAST)
    joins = set(roots)                        # (compile_code adds the return points and the code addresses held as numbers)
    for nxt, targets in tables.values():
        joins |= set(targets)
    em = compile_code(code, joins, cfg, {IDLE}, emitter=GSEmitter, ijmp_flags=True, flags_at={IDLE},
                      text_sites=text_sites)
    seen_unsupported = [u for u in em.unsupported if u[0] in pcs]
    if seen_unsupported:
        raise RuntimeError(f'Observed instructions cannot be translated: {seen_unsupported}')
    out = ['; Generated Gun.Smoke main Z80, fixed ROM and four banks', '\tsection text,code', *em.lines]
    out.append(TRAMPOLINE)
    for pc in sorted(em.refs - set(code) - {0xe0f8}):
        out += [f'Z{pc:04X}:', f'\tmove.w #${real(pc):04x},d7', '\tjmp z80_badpc']
    for pc in sorted(em.stubs):
        out += [f'BK{pc:04X}:', f'\tmove.w #${pc:04x},d7', '\tjmp gs_dispatch']
    out += ['\tsection data,data', '\teven', 'gs_entries_fixed:']
    for pc in sorted(code):
        if pc < WIN_LO and pc not in em.no_entry:   # (merged: z80_badpc)
            out += [f'\tdc.w ${pc:04x}', f'\tdc.l Z{pc:04X}']
    out += ['\tdc.w $ffff']
    for bank in range(4):
        out += [f'gs_entries_bank{bank}:']
        for pc in sorted(code):
            if VBASE + bank * 0x4000 <= pc < VBASE + (bank + 1) * 0x4000 and pc not in em.no_entry:
                out += [f'\tdc.w ${real(pc) - WIN_LO:04x}', f'\tdc.l Z{pc:04X}']
        out += ['\tdc.w $ffff']
    out += ['gs_entry_banks:', '\tdc.l ' + ','.join(f'gs_entries_bank{b}' for b in range(4))]
    banks = sorted({(pc - VBASE) // 0x4000 for pc in code if pc >= VBASE})
    out += ['gs_dispatch_targets:', '\tdc.l ' + ','.join(f'gs_window_dispatch{b}' if b in banks else 'gs_invalid_dispatch'
                                                     for b in range(4)),
            f'GS_WINDOW_TABLES = {len(banks) + 1}', '\tsection bss,bss', 'gs_invalid_dispatch: ds.l 16384']
    for bank in banks:
        out += [f'gs_window_dispatch{bank}: ds.l 16384']
    out += ['\tsection text,code']
    report = {'instructions': len(code), 'unsupported': em.unsupported, 'banks': banks,
              'text_sites': len(text_sites), 'missing': [hex(real(p)) for p in sorted(em.refs - set(code) - {0xe0f8})],
              'jumps': len(jumps)}
    return '\n'.join(out) + '\n', report, code


if __name__ == '__main__':
    text, report, _ = generate()
    (BUILD / 'code_gunsmoke.s').write_text(text)
    (BUILD / 'translation.json').write_text(json.dumps(report, indent=2) + '\n')
    print({k: v for k, v in report.items() if k != 'unsupported'}, len(report['unsupported']), 'unsupported')
