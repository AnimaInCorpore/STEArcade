#!/usr/bin/env python3
"""Exercise the diagnostic's actual ACIA ISR with one interrupt per serial byte."""
import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'engine'))
from machine68k import Register as R
from sim import Sim


def test(out):
    sim = Sim(out / 'GUNSMOKE.TOS')
    sym = {k: v + sim.base for k, v in sim.symbols(out / 'GUNSMOKE.MAP').items()}
    pending = []
    writes = []

    def read_acia(addr):
        addr &= 0xffffff
        if addr == 0xfffc00:
            return int(bool(pending))  # RDRF only; no fabricated overrun
        if addr == 0xfffc02:
            return pending.pop(0) if pending else 0
        return 0

    sim.mem.set_special_range_read_funcs(0xff0000, r8=read_acia)
    scalars = ['ikbd_state', 'ikbd_lost', 'ikbd_esc', 'quit_flag',
               'joy0_state', 'joy1_state', 'p1_joy', 'p2_joy',
               'sys_kbd', 'p1_kbd', 'p2_kbd', 'in_sys', 'in_p1', 'in_p2']
    allowed = {sym[name] for name in scalars}
    allowed.update(range(sym['mt_joysticks'], sym['mt_joysticks'] + 2 + 128 + 128))

    def trace(mode, width, addr, value):
        if mode == 'W' and sim.base <= addr < 0x400000:
            writes.append((addr, width, value))

    sim.mem.set_trace_func(trace)

    def byte(value, upper):
        # A header and its payload normally arrive in DIFFERENT interrupts.
        # Foreground registers have changed before the payload interrupt.
        pending[:] = [value]
        sim.mem.w16(0x8000, 0x2300)
        sim.mem.w32(0x8002, 0x600)
        sim.cpu.w_sr(0x2700)
        sim.cpu.w_reg(R.A7, 0x8000)
        original = {R.D0: 0xa5000000 | upper << 8 | 0x55,
                    R.D1: 0x12345678, R.D2: 0x87654321, R.A0: 0xabcdef}
        for reg, val in original.items():
            sim.cpu.w_reg(reg, val)
        writes.clear()
        sim.cpu.w_pc(sym['acia_isr'])
        sim.cpu.execute(2000)
        assert not pending and sim.cpu.r_pc() == 0x600
        assert all(sim.cpu.r_reg(reg) == val for reg, val in original.items())
        bad = [(hex(a - sim.base), w, v) for a, w, v in writes if a not in allowed or w != 0]
        assert not bad, ('out-of-bounds ISR writes', hex(value), hex(upper), bad)

    cases = 0

    def packet(port, raw, upper):
        for i in range(2):
            sim.mem.w8(sym['mt_joysticks'] + i, 0)
        byte(0xfe + port, upper ^ 0xff)
        byte(raw, upper)
        assert sim.mem.r8(sym['mt_joysticks'] + port) == raw, ('logger port/raw/upper', port, raw, upper)
        assert sim.mem.r8(sym['mt_joysticks'] + (1 - port)) == 0
        expected = ((raw & 8) >> 3) | ((raw & 4) >> 1) | ((raw & 2) << 1) | ((raw & 1) << 3) | ((raw & 128) >> 2)
        assert sim.mem.r8(sym['p1_joy' if port else 'p2_joy']) == expected

    for port in (0, 1):
        for upper in range(256):
            packet(port, 0x8f, upper)
            cases += 1
        for raw in range(256):
            packet(port, raw, 0x34)
            cases += 1
        packet(port, 0, 0xff)
    for code in [0x06, 0x02, 0x4d, 0x4b, 0x50, 0x48, 0x1d, 0x39, 0x38]:
        byte(code, 0x34)
        byte(code | 0x80, 0xff)
        assert sim.mem.r8(sym['mt_pressed'] + code) == 0xff
        assert sim.mem.r8(sym['mt_released'] + code) == 0xff
    byte(0x01, 0x34)
    byte(0x81, 0xff)
    assert sim.mem.r8(sym['quit_flag']) == 0xff
    result = dict(split_irq_packets=cases, upper_byte_values=256, raw_joystick_values=256,
                  ports=2, memory_write_bounds=True, registers_preserved=True,
                  keyboard_make_break=True, scope='native ISR with synthetic serial bytes; physical device not exercised')
    print(result)
    return result


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('out', type=Path)
    test(ap.parse_args().out.resolve())
