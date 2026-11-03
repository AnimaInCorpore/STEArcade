"""Exercise the real non-SIM sprite DMA capture under both picture schedulers.

The deadline scheduler must capture even with pending logic ticks and a picture
cadence count below PIC_EVERY: pic_due can subsequently request a picture.
Also check that post-DMA emitter writes cannot change the captured picture.
"""
import argparse
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'engine'))
from paths import VASM, VLINK
from sim import Sim, TRAP1
from machine68k import Register as R


def check(source, deadline, costs=None):
    out = ROOT / 'build/rtype/dma_test'
    out.mkdir(parents=True, exist_ok=True)
    tag = 'deadline' if deadline else 'cadence'
    asm, obj, prg, mp = [out / (tag + ext) for ext in ('.s', '.o', '.PRG', '.map')]
    routine = source.split('m72_sprite_dma:', 1)[1].split('; port $00:', 1)[0]
    asm.write_text('''SPRITE_LIST = 1
PIC_EVERY = 8
PIC_VBLS = %d
 section text,code
start:
 clr.l -(sp)
 move #$20,-(sp)
 trap #1
 addq #6,sp
 lea stack_top,sp
wait: bra.s wait
m72_sprite_dma:
%s
 section bss,bss
v30_image: ds.b $44000
m72_slots: ds.b $400
m72_objs: ds.b $400
m72_objs_end: ds.w 1
m72_slots_hw: ds.w 1
m72_dma_done: ds.b 1
ticks: ds.b 1
since_pic: ds.b 1
 even
 ds.b 4096
stack_top:
''' % (deadline, routine))
    for command in ([VASM, '-Fvobj', '-quiet', '-o', str(obj), str(asm)],
                    [VLINK, '-b', 'ataritos', '-s', '-o', str(prg), '-M' + str(mp), str(obj)]):
        result = subprocess.run(command, capture_output=True, text=True)
        if result.returncode:
            raise RuntimeError(result.stdout + result.stderr)
    s = Sim(str(prg), ram_kib=16384, run_dir=out)
    mem, cpu = s.mem, s.cpu
    sym = {k: v + s.base for k, v in s.symbols(mp).items()}

    def until_wait():
        cycles = 0
        for _ in range(10000):
            cycles += cpu.execute(1 if costs is not None else 1000).cycles
            if cpu.r_pc() == sym['wait']:
                return cycles
            if cpu.r_pc() == TRAP1:
                s.gemdos()
        raise AssertionError('DMA harness timeout')

    until_wait()
    cases = 0
    for pending in (0, 1, 8):
        for since in (0, 6, 7):
            for live, previous in ((0xc0, 0xc0), (0xe0, 0xd0), (0xd0, 0xf0), (0x400, 0x3c0)):
                old = bytes([0xa5]) * 1024
                slots = bytes((j * 37 + cases) & 255 for j in range(1024))
                mem.w_block(sym['m72_slots'], slots)
                mem.w_block(sym['m72_objs'], old)
                mem.w16(sym['m72_objs_end'], 0xbeef)
                mem.w16(sym['v30_image'] + 0x42efc, live)
                mem.w16(sym['m72_slots_hw'], previous)
                mem.w8(sym['ticks'], pending)
                mem.w8(sym['since_pic'], since)
                mem.w8(sym['m72_dma_done'], 0)
                saved = {R.D0: 0x12345678, R.A0: 0x2345678, R.A1: 0x3456789}
                for reg, value in saved.items():
                    cpu.w_reg(reg, value)
                sp = cpu.r_reg(R.A7)
                mem.w32(sp - 4, sym['wait'])
                cpu.w_reg(R.A7, sp - 4)
                cpu.w_pc(sym['m72_sprite_dma'])
                cycles = until_wait()
                capture = deadline != 0 or pending == 0 or since == 7
                end = max(live, previous)
                if costs is not None:
                    costs.append(dict(deadline=deadline, pending=pending, since=since,
                                      end=end, capture=capture, cycles=cycles))
                want = bytearray(old)
                if capture:
                    want[0xc0:end] = slots[0xc0:end]
                    want[0x3c0:] = slots[0x3c0:]
                assert bytes(mem.r_block(sym['m72_objs'], 1024)) == bytes(want), (deadline, pending, since)
                assert mem.r16(sym['m72_objs_end']) == (end if capture else 0xbeef)
                assert mem.r8(sym['m72_dma_done']) == 255
                assert cpu.r_reg(R.A7) == sp
                assert all(cpu.r_reg(reg) == value for reg, value in saved.items())
                mem.w_block(sym['m72_slots'], bytes([0x5a]) * 1024)
                assert bytes(mem.r_block(sym['m72_objs'], 1024)) == bytes(want)
                cases += 1
    for p in (prg, obj):
        p.unlink()
    return cases


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--source', type=Path, default=ROOT / 'games/rtype/src/core.s')
    ap.add_argument('--cycles', type=Path, help='write instruction-stepped CPU cycle measurements as JSON')
    args = ap.parse_args()
    source = args.source.read_text()
    costs = [] if args.cycles else None
    cases = sum(check(source, n, costs) for n in (3, 0))
    if args.cycles:
        args.cycles.write_text(json.dumps(costs, indent=2) + '\n')
    print('PASS: %d non-SIM DMA cases; deadlines, cadence, retained tails, fixed slots and post-DMA writes' % cases)


if __name__ == '__main__':
    main()
