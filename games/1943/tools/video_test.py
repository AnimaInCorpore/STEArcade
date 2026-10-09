"""Independent ROM bit-decode checks and synthetic video priority regressions."""
import numpy as np
from PIL import Image
from video import Video
from paths import build_dir


def main():
    v = Video()
    x8 = [0, 1, 2, 3, 8, 9, 10, 11]
    rng = np.random.default_rng(1943)
    # Compare vector decoding to scalar MSB-first ROM bit accesses.
    for region, name, size in [('gfx1', 'chars', 8), ('gfx2', 'front', 32),
                               ('gfx3', 'back', 32), ('gfx4', 'sprites', 16)]:
        data = v.regions[region]
        gfx = getattr(v, name)
        planes = [4, 0] if size == 8 else [len(data)*4+4, len(data)*4, 4, 0]
        stride = 128 if size == 8 else size*size*2
        for _ in range(1000):
            code, y, x = int(rng.integers(len(gfx))), int(rng.integers(size)), int(rng.integers(size))
            offset = code*stride + y*16 + (x//8)*size*16 + x8[x%8]
            pixel = 0
            for plane in planes:
                bit = offset+plane
                pixel = (pixel << 1) | ((data[bit//8] >> (7-bit%8)) & 1)
            assert gfx[code, y, x] == pixel, (name, code, y, x)
    mem, sprites = bytearray(65536), bytearray(4096)
    for control in [0, 64, 128, 192]:
        for layers in range(0, 128, 16):
            mem[0xd800:0xd805] = bytes([255, 255, 255, 255, 255])
            rgb = v.render_rgb(mem, sprites, control, layers)
            assert rgb.shape == (224, 256, 3)
    # Distinguish first-sprite ownership from background priority: a hidden
    # first sprite must still block a later, higher-priority sprite.
    v.front[:] = 1
    v.tilemap = np.zeros(65536, np.uint8)
    v.lookup[129] = 7
    v.sprites[:] = 0
    v.sprites[1] = 1
    v.sprites[2] = 2
    v.lookup[641], v.lookup[642] = 100, 101
    v.prom = v.prom.copy()
    v.prom[0x901], v.prom[0x902] = 8, 0
    mem[0xd800:0xd805] = bytes(5)
    sprites[:4] = bytes([1, 0, 32, 32])
    sprites[32:36] = bytes([2, 0, 32, 32])
    assert v.render_raw(mem, sprites, 0, 80)[32, 32] == 7
    assert v.render_raw(mem, sprites, 0, 64)[32, 32] == 100
    sprites[:4] = bytes(4)
    assert v.render_raw(mem, sprites, 0, 80)[32, 32] == 101
    # Upper sprite bank and negative X must clip without wrapping into screen.
    v.sprites[2047] = 2
    sprites[32:36] = bytes([255, 0xf0, 32, 250])
    raw = v.render_raw(mem, sprites, 0, 64)
    assert raw[32, 0] == 101 and raw[32, 10] == 0
    # Save a real-ROM scrolling-layer preview with every layer enabled.
    v = Video()
    output = build_dir('1943') / 'video_reference.png'
    Image.fromarray(v.render_rgb(mem, bytearray(4096), 0, 48, rotated=True)).save(output)
    print('4000 scalar decode checks, layer/flip/scroll sweeps and sprite priority/edge checks passed')
    print(output)


if __name__ == '__main__':
    main()
