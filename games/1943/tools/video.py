"""1943 reference video hardware; independent of the missing protection MCU.

Consumes verified graphics ROMs directly. This is an arcade reference renderer,
not the STE renderer. Coordinates are raw arcade coordinates (before ROT270).
"""
import numpy as np
from prepare import verify


def decode(data, width, height, planes, xoffsets, count, stride):
    bits = np.unpackbits(np.frombuffer(data, np.uint8))
    offsets = (np.arange(count)[:, None, None] * stride +
               np.arange(height)[None, :, None] * 16 +
               np.array(xoffsets)[None, None, :])
    pixels = np.zeros((count, height, width), np.uint8)
    for i, plane in enumerate(planes):
        pixels |= bits[offsets + plane] << (len(planes) - 1 - i)
    return pixels


class Video:
    def __init__(self, set_name=None):
        entries, files, _, missing = verify(set_name)
        required = {'gfx1', 'gfx2', 'gfx3', 'gfx4', 'tilerom', 'proms'}
        absent = [e['name'] for e in missing if e['region'] in required]
        if absent:
            raise ValueError('Missing verified graphics ROMs: ' + ', '.join(absent))
        regions = {}
        for region in required:
            records = [e for e in entries if e['region'] == region]
            data = bytearray(max(e['offset'] + e['size'] for e in records))
            for e in records:
                data[e['offset']:e['offset']+e['size']] = files[e['name']]
            regions[region] = bytes(data)
        self.regions = regions
        x8 = [0, 1, 2, 3, 8, 9, 10, 11]
        self.chars = decode(regions['gfx1'], 8, 8, [4, 0], x8, 2048, 128)
        for region, name, size in [('gfx2', 'front', 32), ('gfx3', 'back', 32),
                                   ('gfx4', 'sprites', 16)]:
            data = regions[region]
            half = len(data)*4
            xo = [block*size*16 + x for block in range(size//8) for x in x8]
            setattr(self, name, decode(data, size, size, [half+4, half, 4, 0],
                                      xo, len(data)//(size*size//2), size*size*2))
        prom = np.frombuffer(regions['proms'], np.uint8)
        self.prom = prom
        weights = np.array([14, 31, 67, 143])
        components = prom[:768].reshape(3, 256)
        self.palette = (((components[:, :, None] >> np.arange(4)) & 1) * weights).sum(2).T.astype(np.uint8)
        self.lookup = np.empty(896, np.uint8)
        self.lookup[:128] = (prom[0x300:0x380] & 15) | 0x40
        for base, lo, hi, mask, add in [(128, 0x400, 0x500, 3, 0),
                                      (384, 0x600, 0x700, 3, 0),
                                      (640, 0x800, 0x900, 7, 128)]:
            self.lookup[base:base+256] = (prom[lo:lo+256] & 15) | ((prom[hi:hi+256] & mask) << 4) | add
        self.tilemap = np.frombuffer(regions['tilerom'], np.uint8)

    def render_raw(self, mem, sprites, control, layers):
        """Return indirect palette indices for the full 256x256 raw screen.

        `sprites` is the 4096-byte buffer latched on c806, not live sprite RAM.
        """
        mem = np.frombuffer(mem, np.uint8)
        if len(mem) != 65536 or len(sprites) != 4096:
            raise ValueError('Expected 64 KB memory and 4 KB buffered sprites')
        yy, xx = np.indices((256, 256))
        # Flipped tilemaps reverse the visible 256x256 window, including scroll.
        if control & 64:
            xx, yy = 255-xx, 255-yy
        out = np.zeros((256, 256), np.uint8)
        front_opaque = np.zeros((256, 256), bool)
        for enabled, gfx, base, mapbase, sx, sy in [
            (layers & 32, self.back, 384, 0x8000, int(mem[0xd803]) | int(mem[0xd804]) << 8, 0),
            (layers & 16, self.front, 128, 0, int(mem[0xd800]) | int(mem[0xd801]) << 8, int(mem[0xd802]))]:
            if not enabled:
                continue
            wx, wy = (xx+sx) & 65535, (yy+sy) & 255
            idx = mapbase + 2*((wx//32)*8 + wy//32)
            attr = self.tilemap[idx+1]
            code = self.tilemap[idx].astype(np.uint16)
            if mapbase == 0:
                code += (attr.astype(np.uint16) & 1) << 8
            px = np.where(attr & 64, 31-(wx & 31), wx & 31)
            py = np.where(attr & 128, 31-(wy & 31), wy & 31)
            pens = gfx[code % len(gfx), py, px]
            colours = self.lookup[base + ((attr.astype(np.uint16) & 60) >> 2)*16 + pens]
            if mapbase:
                out[:] = colours
            else:
                front_opaque = colours != 15
                out[front_opaque] = colours[front_opaque]
        if layers & 64:
            drawn = np.zeros((256, 256), bool)
            for off in range(0, 4096, 32):
                code, attr, y, x = sprites[off:off+4]
                code += (attr & 224) << 3
                x -= (attr & 16) << 4
                pixels = self.sprites[code]
                if control & 64:
                    x, y = 240-x, 240-y
                    pixels = pixels[::-1, ::-1]
                x0, x1, y0, y1 = max(0, x), min(256, x+16), max(0, y), min(256, y+16)
                if x0 >= x1 or y0 >= y1:
                    continue
                p = pixels[y0-y:y1-y, x0-x:x1-x].astype(np.uint16)
                colour = attr & 15
                dest = out[y0:y1, x0:x1]
                taken = drawn[y0:y1, x0:x1]
                opaque = (p != 0) & ~taken
                priority = self.prom[0x900 + colour*16 + p] & 8
                visible = opaque & (~front_opaque[y0:y1, x0:x1] | (priority == 0))
                dest[visible] = self.lookup[640 + colour*16 + p][visible]
                taken[opaque] = True
        if control & 128:
            idx = (yy//8)*32 + xx//8
            attr = mem[0xd400+idx]
            code = mem[0xd000+idx].astype(np.uint16) + ((attr.astype(np.uint16) & 224) << 3)
            p = self.chars[code, yy & 7, xx & 7]
            colours = self.lookup[(attr.astype(np.uint16) & 31)*4+p]
            mask = p != 0
            out[mask] = colours[mask]
        return out

    def render_rgb(self, mem, sprites, control, layers, rotated=False):
        image = self.palette[self.render_raw(mem, sprites, control, layers)[16:240]]
        return np.rot90(image) if rotated else image
