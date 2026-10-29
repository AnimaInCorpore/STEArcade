"""Mr. Do!: the Z80 program (32 KB, flat) translated to 68000 code.

    python gen.py   ->  build/mrdo/code_main.s (+ translation.json)

Roots: reset, the IRQ ($0038), the idle hooks ($00AC, $0154: machine.MrDoPort.HOOKS) and the coverage
(build/mrdo/cover<seed>.pkl, ref/cover.py in the port's schedule).  The runtime (src/mrdo.s, machine.MrDoPort):
z80_hook at a hook (d7 = the pc) waits for the next arcade frame and delivers the IRQ with TOKEN as its return
address; z80_irq_ret goes on at the hook.
Memory-mapped I/O: the inputs A000-A003 are read from the block (the runtime keeps them there); the stores to the
SN76489s ($9801 / $9802: `ld (nn),a`, and `ld (bc),a` at the sites the coverage saw) call md_sound1 /
md_sound2 / md_sound_bc; the flip latch $9800, the sprite RAM
$9000-$90FF and the scroll registers ($F000 / $F800) are plain stores the renderer reads.  The protection read
`$9803` gives the ROM byte at HL (MAME's stand-in for the PAL): translated as `ld a,(hl)` (PROT_SITES).  The stores
to the video RAM ($8000-$8FFF, the coverage's write sites) list the cell they hit (md_mark_*: cell_dirty,
cell_list; the cell = address & $3FF, + $400 for the foreground $8800-$8FFF).
"""
from pathlib import Path
import json
import os
import pickle
import sys
sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[3] / 'engine')]
import z80x
import discover
from translate import compile_code
from paths import build_dir, require_coverage
from machine import MrDoPort, load, PROGRAM

BUILD = build_dir('mrdo')
HOOKS = sorted(MrDoPort.HOOKS)
TOKEN = MrDoPort.TOKEN
SEEDS = [int(x) for x in os.environ.get('MD_SEEDS', '').split(',') if x] or range(1, 13)
ROM_END = 0x8000
IYADDR, FSHADOW = 0x9E00, 0x9E02            # (unmapped: nothing of the program's is there)
SOUND = {0x9801: 'md_sound1', 0x9802: 'md_sound2'}
INPUTS = range(0xA000, 0xA004)
PROT_OP = ('ind', 'hl', 0)                  # what `ld a,($9803)` becomes: ld a,(hl)
# calls of leaf functions of up to this many instructions are emitted in place, rst helpers and inner jumps too
INLINE = int(os.environ.get('MD_INLINE', '16'))


def image():
    rom = b''.join(load(n) for n in PROGRAM)
    return rom + bytes(0x10000 - len(rom))


def coverage():
    require_coverage('mrdo', ['cover%d.pkl' % s for s in SEEDS])
    pcs, jumps, writes, io, ports, halts = set(), set(), set(), set(), set(), set()
    for s in SEEDS:
        d = pickle.loads((BUILD / ('cover%d.pkl' % s)).read_bytes())
        pcs |= d['pcs']
        jumps |= d['jumps']
        writes |= d['writes']
        io |= d['io']
        ports |= d['ports']
        halts |= d['halts']
    return pcs, jumps, writes, io, ports, halts


def cell(a):
    return (a & 0x3FF) | ((a & 0x800) >> 1)


class MEmitter(z80x.Emitter):
    def __init__(self, *a, tile_sites=None, **k):
        super().__init__(*a, **k)
        self.tile_sites = tile_sites or {}

    def x_in(self, ins):
        raise z80x.Unsupported('in ' + ins.text)

    def x_out(self, ins):
        raise z80x.Unsupported('out ' + ins.text)

    def emit_ins(self, pc, live_out_override=None, with_label=True):
        super().emit_ins(pc, live_out_override, with_label)
        mark = self.tile_sites.get(pc)
        if mark:
            self.e(mark)                      # (the marks keep the flags)


def tile_marks(code, writes):
    """pc -> the line that lists the video RAM cell its store hit (a routine per address register; static stores
    list their cell directly; block moves mark every cell)"""
    out = {}
    for pc in sorted({pc for pc, a in writes if 0x8000 <= a < 0x9000}):
        ins = code.get(pc)
        if ins is None:
            continue
        if ins.mn in ('ldir', 'lddr', 'ldi', 'ldd'):
            out[pc] = 'bsr md_mark_all'
            continue
        dst = (ins.ops[-1] if ins.mn in ('set', 'res') else ins.ops[0]) if ins.ops else None
        if ins.mn in ('push', 'call', 'rst') or dst is None:
            raise RuntimeError('video RAM write by %04X %s' % (pc, ins.text))
        if dst[0] == 'ind16':
            out[pc] = 'pea %d.w\n\tbsr md_mark_n\n\taddq.l #4,a7' % cell(dst[1])
            if ins.mn == 'ld' and ins.ops[1][0] == 'r16':          # (ld (nn),rr: two bytes)
                out[pc] += '\n\tpea %d.w\n\tbsr md_mark_n\n\taddq.l #4,a7' % cell(dst[1] + 1)
        elif dst[0] == 'ind' and dst[1] in ('hl', 'de', 'bc', 'ix', 'iy') and ins.mn in (
                'ld', 'inc', 'dec', 'set', 'res', 'rlc', 'rrc', 'rl', 'rr', 'sla', 'sra', 'srl', 'sll', 'rld', 'rrd'):
            if dst[1] in ('ix', 'iy'):
                out[pc] = 'pea %d.w\n\tbsr md_mark_%s\n\taddq.l #4,a7' % (dst[2], dst[1])
            else:
                out[pc] = 'bsr md_mark_%s' % dst[1]
        else:
            raise RuntimeError('video RAM write by %04X %s (form)' % (pc, ins.text))
    return out


def check_io(code, io, ports, halts):
    """the accesses the translation handles; -> the protection read sites, the `ld (bc),a` sound sites"""
    prot, sound_bc = set(), set()
    for pc, a, rw in sorted(io):
        ins = code.get(pc)
        if ins is None:
            continue
        if rw == 'r':
            if a == 0x9803 and ins.mn == 'ld' and ins.ops == [('r8', 'a'), ('ind16', 0x9803)]:
                prot.add(pc)
            elif a in INPUTS:
                continue
            else:
                raise RuntimeError('read of %04X by %04X %s' % (a, pc, ins.text))
        elif a in SOUND:
            if ins.mn == 'ld' and ins.ops == [('ind', 'bc', 0), ('r8', 'a')]:
                sound_bc.add(pc)
            elif not (ins.mn == 'ld' and ins.ops == [('ind16', a), ('r8', 'a')]):
                raise RuntimeError('sound write to %04X by %04X %s (not ld (nn),a)' % (a, pc, ins.text))
        elif a == 0x9800 or 0x9000 <= a < 0x9100 or a in (0xF000, 0xF800):
            continue
        else:
            raise RuntimeError('store to %04X by %04X %s' % (a, pc, ins.text))
    if ports:
        raise RuntimeError('in / out at %s' % ['%04X' % p for p in sorted(ports)])
    if halts:
        raise RuntimeError('halts at %s' % sorted(halts))
    for pc, a, rw in io:
        if pc in sound_bc and a not in SOUND:
            raise RuntimeError('ld (bc),a at %04X writes %04X too' % (pc, a))
    return prot, sound_bc


def generate():
    rom = image()
    pcs, jumps, writes, io, ports, halts = coverage()
    pcs = {p for p in pcs if p < ROM_END}
    roots = {0, 0x38} | set(HOOKS) | {j for j in jumps if j < ROM_END}
    cache = {}
    while True:
        code, tables = discover.discover(rom, sorted(roots | pcs), known=pcs, rst28_tables=False, hl_tables=True)
        code = {pc: ins for pc, ins in code.items() if pc < ROM_END}
        missing = discover.skip_returns(rom, code, lambda pc: pc < ROM_END, cache) - set(code)
        if not missing:
            break
        roots |= missing
    prot, sound_bc = check_io(code, io, ports, halts)
    for pc in prot:                           # `ld a,($9803)`: the ROM byte at HL
        ins = code[pc]
        code[pc] = ins._replace(ops=[('r8', 'a'), PROT_OP], text='ld a,(hl) ; (%s: the protection)' % ins.text)
    cfg = z80x.Config(mode='signed', block=0x10000, table_entries=0x10000, iyaddr=IYADDR, fshadow=FSHADOW,
                      io_read_redirect={}, write_hooks=[(a, a, label, None) for a, label in SOUND.items()],
                      nmi_token=TOKEN, token_sym='z80_irq_ret', rst28_tables=False, hl_tables=True, bit_s=False,
                      inline_leaves=INLINE, inline_limit=ROM_END, inline_rst=True, inline_jumps=True, **z80x.FAST)
    joins = set(roots)
    for nxt, targets in tables.values():
        joins |= set(targets)
    marks = tile_marks(code, writes)
    for pc in sound_bc:
        marks[pc] = 'bsr md_sound_bc'         # (the chip by C: $01 / $02)
    em = compile_code(code, joins, cfg, set(HOOKS), emitter=MEmitter, ijmp_flags=True, flags_at=set(HOOKS),
                      tile_sites=marks)
    seen = [u for u in em.unsupported if u[0] in pcs]
    if seen:
        raise RuntimeError('observed instructions cannot be translated: %s' % seen)
    out = ['; generated: Mr. Do! Z80 -> 68000 (games/mrdo/tools/gen.py)', '\tsection text,code']
    out += em.lines
    missing = sorted(p for p in em.refs if p not in code)
    for p in missing:
        out += ['Z%04X:\tmove.w #$%04X,d7' % (p, p), '\tjmp z80_badpc']
    out += ['\tsection data,data'] + dispatch_table(code, em)
    report = {'instructions': len(code), 'unsupported': em.unsupported, 'missing': ['%04X' % p for p in missing],
              'tables': {'%04X' % k: ['%04X' % t for t in v[1]] for k, v in tables.items()},
              'tile_sites': len(marks), 'prot_sites': ['%04X' % p for p in sorted(prot)],
              'sound_bc': ['%04X' % p for p in sorted(sound_bc)], 'jumps': len(jumps),
              'coverage': len(pcs), 'discovered_only': len(set(code) - pcs), 'io': sorted(io)}
    return '\n'.join(out) + '\n', report, code


def dispatch_table(code, em):
    """a long per Z80 address in byte-swapped order (the word a ret reads from the Z80 stack): the translated label,
    z80_irq_ret for TOKEN, else z80_badpc"""
    labels = {p: 'Z%04X' % p for p in code if p not in em.no_entry}
    labels[TOKEN] = 'z80_irq_ret'
    rows, run = ['\tcnop 0,4', 'z80_dispatch_sw:'], 0
    for swapped in range(65536):
        label = labels.get(((swapped & 255) << 8) | (swapped >> 8))
        if label is None:
            run += 1
            continue
        if run:
            rows.append('\tdcb.l %d,z80_badpc' % run)
            run = 0
        rows.append('\tdc.l %s' % label)
    if run:
        rows.append('\tdcb.l %d,z80_badpc' % run)
    return rows


if __name__ == '__main__':
    text, report, _ = generate()
    (BUILD / 'code_main.s').write_text(text)
    (BUILD / 'translation.json').write_text(json.dumps(report, indent=1) + '\n')
    print({k: v for k, v in report.items() if k not in ('unsupported', 'tables', 'io')}, len(report['unsupported']),
          'unsupported')
