"""Verify firmware transactions and run an unpatched reference boot."""
from pathlib import Path
import sys
from PIL import Image
from machine import BlackTiger
from paths import build_dir


def main():
    m = BlackTiger()
    for command in range(256):
        expected = m.mcu.rom[0x800 + (command & 15)]
        assert m.mcu.send(command) == expected, command
        assert not m.mcu.active
    # Restart to keep the boot independent of the transaction sweep.
    m = BlackTiger()
    frames = int(sys.argv[1]) if len(sys.argv) > 1 else 700
    for _ in range(frames):
        m.run_frame()
    commands = sum(row[2] == 7 for row in m.io_log)
    assert commands, 'Boot never contacted the protection device'
    assert m.irq_count, 'Boot did not accept interrupts'
    output = build_dir('blktiger') / 'reference.png'
    Image.fromarray(m.render_rgb()).save(output)
    print(f'256 firmware transactions passed; {frames} frames, {commands} MCU commands, PC={m.cpu.pc:04x}')
    print(output)


if __name__ == '__main__':
    main()
