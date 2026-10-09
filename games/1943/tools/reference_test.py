"""Check all MCU commands against firmware tables, then unpatched reference frames."""
import sys
from PIL import Image
from machine import Game1943
from paths import build_dir


def main():
    m = Game1943()
    table = dict(zip(m.mcu.rom[0x800:0x840:2], m.mcu.rom[0x801:0x840:2]))
    previous = 0
    for command in range(256):
        m.mcu.command = command
        response = m.mcu.vblank()
        previous = table.get(command, previous)
        assert response == previous, (command, response, previous)
        assert not m.mcu.active
        assert m.mcu.ram[0x81] == 0x2f
    # An arbitrary retained reply is the firmware's behavior on unknown input.
    m = Game1943()
    frames = int(sys.argv[1]) if len(sys.argv)>1 else 700
    for _ in range(frames): m.run_frame()
    assert m.irq_count > 0 and m.dma_count > 0
    assert m.mcu.transactions == frames
    assert m.control & 128 and m.layers & 112
    out = build_dir('1943') / 'reference.png'
    Image.fromarray(m.render_rgb(True)).save(out)
    print(f'256 MCU commands passed; {frames} frames; {m.irq_count} IRQs; {m.dma_count} DMA requests; PC={m.cpu.pc:04x}')
    print(out)


if __name__ == '__main__': main()
