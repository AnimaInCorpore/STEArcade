"""SCREEN.BIN (src/defender.s -D SHOT=1: the 16 STE colour words, the picture's 240 planar lines, the VBLs and the
arcade frames) -> a PNG, and the speed.

    python tools/shot.py SCREEN.BIN out.png
"""
import sys
import numpy as np
from PIL import Image


def ste_rgb(w):
    def gun(n):
        v = ((n & 7) << 1) | ((n >> 3) & 1)
        return v * 17
    return gun(w >> 8 & 15), gun(w >> 4 & 15), gun(w & 15)


def main():
    data = open(sys.argv[1], 'rb').read()
    pal = np.array([ste_rgb((data[2 * i] << 8) | data[2 * i + 1]) for i in range(16)], np.uint8)
    a = np.frombuffer(data[32:32 + 240 * 160], np.uint8).reshape(240, 20, 4, 2)
    w = (a[..., 0].astype(np.uint16) << 8) | a[..., 1]
    bits = (w[..., None] >> (15 - np.arange(16))) & 1
    pix = (bits * (1 << np.arange(4))[None, None, :, None]).sum(axis=2).reshape(240, 320)
    Image.fromarray(pal[pix]).save(sys.argv[2])
    print(sys.argv[2])
    rest = data[32 + 240 * 160:]
    if len(rest) >= 6:
        vbls = int.from_bytes(rest[0:4], 'big')
        frames = int.from_bytes(rest[4:6], 'big')
        print("VBLs %d, arcade frames %d: %.1f a second (%.0f%% of the arcade's 60.10)" % (
            vbls, frames, 50 * frames / vbls, 100 * 50 * frames / vbls / 60.10))


if __name__ == '__main__':
    main()
