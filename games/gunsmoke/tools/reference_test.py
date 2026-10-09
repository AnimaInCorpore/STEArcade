"""Check bank mapping, sprite latch and unpatched main-CPU boot."""
import sys
from PIL import Image
from machine import GunSmoke
from paths import build_dir


def main():
    m = GunSmoke()
    for bank in range(4):
        m.wr8(0xc804, bank << 2)
        assert bytes(m.rd8(a) for a in range(0x8000, 0xc000)) == m.rom[0x8000+bank*0x4000:0xc000+bank*0x4000]
    m.mem[0xf000] = 123
    assert m.sprites[0] == 0
    m.wr8(0xc806, 0)
    assert m.sprites[0] == 123
    m.mem[0xf000] = 45
    assert m.sprites[0] == 123
    assert [m.rd8(a) for a in range(0xc4c9, 0xc4cc)] == [255, 0, 0]
    m = GunSmoke()
    frames = int(sys.argv[1]) if len(sys.argv) > 1 else 700
    for _ in range(frames):
        m.run_frame()
    assert m.irq_count, 'Boot did not accept interrupts'
    assert any(a == 0xc804 and v & 128 for _, _, a, v in m.io_log), 'Boot did not enable text'
    output = build_dir('gunsmoke') / 'reference.png'
    Image.fromarray(m.render_rgb()).save(output)
    print(output)
    print(f'Bank mapping and sprite latch passed; {frames} unpatched frames, {m.irq_count} IRQs, PC={m.cpu.pc:04x}, bank={m.bank}')


if __name__ == '__main__':
    main()
