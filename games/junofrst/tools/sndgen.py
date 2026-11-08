"""Juno First: the sound board's Z80 driver (4 KB) translated to 68000 code (engine/z80x.py).

    from sndgen import generate; text, report = generate()   -> build/junofrst/snd_code.s

Labels X<pc>, the dispatch table snd_dispatch_sw, the register map of the main program's translation (z80x.FAST: d0
A, d1 BC (byte-swapped), d2 DE, d3 HL, d4 IX, a2 IY, d6 the flags, a5 SP, a6 the sound CPU's 64 KB block, a4 the
table); src/sound.s saves the main program's registers around it.  The board is memory mapped: the stores to the AY's
address ($4000) and data ($4002), the i8039's latch ($5000) and IRQ ($6000) `bsr` to the runtime's hooks after the
store (z80x write_hooks; d0 = A); the read of $3000 is the command latch (snd_zlatch), the read of $4001 the AY's data
register (snd_ayr: filled by the address / data hooks).  The runtime enters at $0038 (a command, TOKEN as the return
address) and at $0186 (a tick: the loop's waits for the port A timer left out) and comes back at the loop's head $0169
(the hook snd_hook) or TOKEN; with bit 6 of the slot $2000 set a pass of the loop is entered at X0169_r.
"""
from pathlib import Path
import pickle
import sys
sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[3] / 'engine')]
import z80x
import discover
from translate import compile_code
from machine import load
from sound import LOOP, TICK, TOKEN
from paths import build_dir, require_coverage

ROM_END = 0x1000
TABLES = (0x02EC, 0x031C)           # per command & 63 (< $1C): the start routine, the sequencer routine


def image():
    rom = load('jfs1_j3.bin')
    return rom + bytes(0x10000 - len(rom))


class SEmitter(z80x.Emitter):
    def mem(self, addr, off=0, io_read=False):
        a = (addr + off) & 0xFFFF
        if io_read and a == 0x3000:
            return 'snd_zlatch'
        if io_read and a == 0x4001:
            return 'snd_ayr'
        return z80x.Emitter.mem(self, addr, off, io_read)


def coverage():
    """the pcs and computed jumps of ref/cover_sound.py's runs"""
    require_coverage('junofrst', ['cover_sound0.pkl'])
    pcs, jumps = set(), set()
    for f in sorted(build_dir('junofrst').glob('cover_sound*.pkl')):
        d = pickle.loads(f.read_bytes())
        pcs |= d['pcs']
        jumps |= d['jumps']
    return {p for p in pcs if p < ROM_END}, {j for j in jumps if j < ROM_END}


def generate():
    rom = image()
    pcs, jumps = coverage()
    roots = {0, 0x38, LOOP, TICK} | jumps
    for base in TABLES:                                    # (the tables' routines are roots whether or not seen)
        for i in range(0x1C):
            t = rom[base + 2 * i] | rom[base + 2 * i + 1] << 8
            if t < ROM_END:
                roots.add(t)
    cache = {}
    while True:
        code, tables = discover.discover(rom, sorted(roots | pcs), known=pcs, rst28_tables=False, hl_tables=True)
        code = {pc: ins for pc, ins in code.items() if pc < ROM_END}
        missing = discover.skip_returns(rom, code, lambda pc: pc < ROM_END, cache) - set(code)
        if not missing:
            break
        roots |= missing
    hooks = [(0x4000, 0x4000, 'snd_ay_addr', None), (0x4002, 0x4002, 'snd_ay_data', None),
             (0x5000, 0x5000, 'snd_latch2_w', None), (0x6000, 0x6000, 'snd_effect', None)]
    cfg = z80x.Config(prefix='X', table='snd_dispatch', token_sym='snd_token_ret', mode='signed', block=0x10000,
                      iyaddr=0x27F0, fshadow=0x27F2, io_read_redirect={}, write_hooks=hooks, nmi_token=TOKEN,
                      table_entries=0x10000, rst28_tables=False, bit_s=True, inline_leaves=16,
                      inline_limit=ROM_END, inline_rst=True, inline_jumps=True, **z80x.FAST)
    joins = set(roots)
    for nxt, targets in tables.values():
        joins |= set(targets)
    em = compile_code(code, joins, cfg, {LOOP}, emitter=SEmitter, ijmp_flags=True, flags_at={LOOP})
    out = ['; generated: Juno First sound Z80 -> 68000 (games/junofrst/tools/sndgen.py)', '\tsection text,code']
    out += [l.replace('z80_hook', 'snd_hook').replace('z80_badpc', 'snd_badpc').replace('z80_rnd', 'snd_badpc')
            for l in em.lines]
    missing = sorted(p for p in em.refs if p not in code)
    for p in missing:
        out += ['X%04X:\tmove.w #$%04X,d7' % (p, p), '\tjmp snd_badpc']
    out += ['\tsection data,data'] + dispatch_table(code, em)
    seen = [u for u in em.unsupported if u[0] in pcs]
    if seen:
        raise RuntimeError('observed sound instructions cannot be translated: %s' % seen)
    report = {'instructions': len(code), 'unsupported': em.unsupported, 'missing': ['%04X' % p for p in missing],
              'tables': {'%04X' % k: ['%04X' % t for t in v[1]] for k, v in tables.items()}}
    return '\n'.join(out) + '\n', report


def dispatch_table(code, em):
    labels = {p: 'X%04X' % p for p in code if p not in em.no_entry}
    labels[TOKEN] = 'snd_token_ret'
    rows, run = ['\tcnop 0,4', 'snd_dispatch_sw:'], 0
    for swapped in range(65536):
        label = labels.get(((swapped & 255) << 8) | (swapped >> 8))
        if label is None:
            run += 1
            continue
        if run:
            rows.append('\tdcb.l %d,snd_badpc' % run)
            run = 0
        rows.append('\tdc.l %s' % label)
    if run:
        rows.append('\tdcb.l %d,snd_badpc' % run)
    return rows


if __name__ == '__main__':
    text, rep = generate()
    print({k: v for k, v in rep.items() if k != 'tables'})
    out = build_dir('junofrst') / 'snd_code.s'
    out.write_text(text)
    print(out, len(text.splitlines()), 'lines')
