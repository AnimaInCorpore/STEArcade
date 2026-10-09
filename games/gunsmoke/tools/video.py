"""MAME-layout graphics decode and raw 256x256 Gun.Smoke renderer."""
import numpy as np
from paths import build_dir


def decode(data, planes, xo, yo, stride, count):
    bits = np.unpackbits(np.frombuffer(data, np.uint8))
    offsets = (np.arange(count)[:, None, None]*stride +
               np.array(yo)[None, :, None] + np.array(xo)[None, None, :])
    result = np.zeros(offsets.shape, np.uint8)
    for i, plane in enumerate(planes):
        result |= bits[offsets+plane] << (len(planes)-1-i)
    return result


class Video:
    def __init__(self):
        folder = build_dir('gunsmoke')
        load = lambda name: (folder / (name+'.rom')).read_bytes()
        self.chars = decode(load('chars'), [4, 0], [11, 10, 9, 8, 3, 2, 1, 0],
                            list(range(112, -1, -16)), 128, 1024)
        xo = [block*512+x for block in range(4) for x in (0,1,2,3,8,9,10,11)]
        self.tiles = decode(load('tiles'), [1048580,1048576,4,0], xo,
                            [y*16 for y in range(32)], 2048, 512)
        xo = [block*256+x for block in range(2) for x in (0,1,2,3,8,9,10,11)]
        self.sprites = decode(load('sprites'), [1048580,1048576,4,0], xo,
                              [y*16 for y in range(16)], 512, 2048)
        self.map = np.frombuffer(load('bgtiles'), np.uint8).reshape(-1,2)
        prom = np.frombuffer(load('proms'), np.uint8)
        self.colors = np.stack([prom[i:i+256]*17 for i in (0,256,512)],axis=1)
        self.lookup = np.concatenate((prom[0x300:0x380] | 0x40,
                                     prom[0x400:0x500] | ((prom[0x500:0x600]&3)<<4),
                                     prom[0x600:0x700] | ((prom[0x700:0x800]&7)<<4) | 0x80))
        self.pens = self.colors[self.lookup]
        self.y, self.x = np.indices((256,256))

    def render_raw(self, m):
        flip = bool(m.control & 64)
        x, y = (255-self.x,255-self.y) if flip else (self.x,self.y)
        out = np.full((256,256), 640, np.uint16)
        if m.layers & 16:
            bx = (x + m.mem[0xd800] + 256*m.mem[0xd801]) % 65536
            by = (y + m.mem[0xd802]) % 256
            tile = self.map[(bx//32)*8 + by//32]
            attr = tile[:,:,1]
            code = tile[:,:,0].astype(np.uint16) + ((attr&1).astype(np.uint16)<<8)
            tx,ty = bx%32,by%32
            tx = np.where(attr&64,31-tx,tx)
            ty = np.where(attr&128,31-ty,ty)
            out = 128 + ((attr&60).astype(np.uint16)>>2)*16 + self.tiles[code,ty,tx]
        if m.layers & 32:
            for off in range(4096-32,-1,-32):
                code,attr,sy,sx = m.sprites[off:off+4]
                bank = attr>>6
                if bank == 3:
                    bank += m.layers&7
                code = (code+256*bank)%2048
                sx -= (attr&32)<<3
                fx,fy = False,bool(attr&16)
                if flip:
                    sx,sy = 240-sx,240-sy
                    fx,fy = True,not fy
                pixels = self.sprites[code]
                if fx: pixels = pixels[:,::-1]
                if fy: pixels = pixels[::-1]
                left,right,top,bottom = max(0,sx),min(256,sx+16),max(0,sy),min(256,sy+16)
                if left >= right or top >= bottom: continue
                p = pixels[top-sy:bottom-sy,left-sx:right-sx]
                view = out[top:bottom,left:right]
                mask = p != 0
                view[mask] = 384+(attr&15)*16+p[mask].astype(np.uint16)
        if m.control & 128:
            ram = np.frombuffer(m.mem,np.uint8)
            index = (y//8)*32+x//8
            attr = ram[0xd400+index]
            code = ram[0xd000+index].astype(np.uint16)+((attr&224).astype(np.uint16)<<2)
            p = self.chars[code,y%8,x%8]
            pens = (attr&31).astype(np.uint16)*4+p
            mask = self.lookup[pens] != 0x4f
            out[mask] = pens[mask]
        return out

    def render_rgb(self,m):
        raw = self.render_raw(m)
        colors = np.vstack((self.pens, np.zeros((1,3), np.uint8)))
        return np.rot90(colors[raw][16:240], k=1)
