"""src/mcu.s's mcu_int1 (the i8751's INT1 in 68000 code) against the translated firmware (M0013, tools/mcux.py) on
Musashi: every command value, each from random MCU states (R4, PSW, P3 bit 6, ACC, the stack, the reply count):
the internal RAM and SFRs (256 bytes), the reply latch, the transaction count, the pc it returns to.

    python mcu_native_test.py [states per command]
"""
import random
import sys
from pathlib import Path
sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[3] / 'engine')]
from sim import Sim
from machine68k import Register as R
from paths import ROOT, build_dir

STOP = 0x2F0000


def main():
    per = int(sys.argv[1]) if len(sys.argv) > 1 else 8
    run = ROOT / 'run' / '1943_sim'
    s = Sim(str(run / '1943.PRG'), ram_kib=16384, run_dir=run)
    sym = {k: v + s.base for k, v in s.symbols(build_dir('1943') / '1943_sim.map').items()}
    cpu, mem = s.cpu, s.mem
    ram, rom = sym['mcu_ram'], sym['mcu_rom']
    mem.w16(STOP, 0x4E71)
    rnd = random.Random(1)
    table = bytes(mem.r_block(rom + 0x800, 64))
    keys = set(table[0::2])
    hits = cases = 0
    for cmd in range(256):
        for _ in range(per):
            image = bytearray(rnd.getrandbits(8) for _ in range(256))
            sp = rnd.randrange(0x07, 0x60)
            image[0x81] = sp
            image[0xa8] |= 0x84                       # (INT1 enabled, as mcu_vblank requires)
            image[0xb0] = rnd.choice([0xff, rnd.getrandbits(8)])
            image[sp + 1], image[sp + 2] = 0x1a, 0x01  # (the pushed pc: the idle loop)
            image[0x81] = sp + 2
            acc = image[0xe0]
            resp, trans = rnd.getrandbits(8), rnd.getrandbits(16)
            out = []
            for entry in ('M0013', 'mcu_int1'):
                mem.w_block(ram, bytes(image))
                mem.w8(sym['mcu_command'], cmd)
                mem.w8(sym['g_mcu_response'], resp)
                mem.w16(sym['mcu_transactions'], trans)
                mem.w16(sym['mcu_pc'], 0)
                cpu.w_reg(R.A0, ram)
                cpu.w_reg(R.A1, rom)
                cpu.w_reg(R.D0, acc)
                cpu.w_reg(R.A7, 0x2EF000)
                mem.w32(0x2EF000, STOP)
                cpu.w_sr(0x2700)
                cpu.w_pc(sym[entry])
                n = 0
                while cpu.r_pc() != STOP:
                    cpu.execute(1)
                    n += 1
                    assert n < 100000, (entry, 'does not return', hex(cpu.r_pc()))
                out.append((bytes(mem.r_block(ram, 256)), mem.r8(sym['g_mcu_response']),
                            mem.r16(sym['mcu_transactions']), mem.r16(sym['mcu_pc'])))
            a, b = out
            assert a == b, (hex(cmd), [(hex(i), a[0][i], b[0][i]) for i in range(256) if a[0][i] != b[0][i]], a[1:], b[1:])
            cases += 1
            hits += cmd in keys
    print('%d cases (every command, %d states each; %d with a key of the table): native = translation (RAM and SFRs, '
          'reply, transactions, pc)' % (cases, per, hits))


if __name__ == '__main__':
    main()
