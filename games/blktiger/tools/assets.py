"""Packed ROM graphics, a fixed STE palette, and mask-grouped sprite programs."""
from pathlib import Path
import sys
import numpy as np
from PIL import Image
sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[3] / 'engine')]
from machine import Gfx, BlackTiger
from paths import build_dir

STRIDE = 384


def packed(pixels):
    return ((pixels[..., ::2] << 4) | pixels[..., 1::2]).tobytes()


def programs(sprites):
    mask_values = sorted({sum((int(p)!=15) << (15-x) for x,p in enumerate(row))
                          for pixels in sprites for row in pixels})
    mask_index = {v:i for i,v in enumerate(mask_values)}
    streams = {}
    pointers, orders, blanks = [], [], []
    # The row order (equal masks together, blank rows last) of a sprite and its mirror image (the second half) is
    # the same, from the sprite's own masks: sprite_order holds the first half only (render.s sprite_get).
    half = len(sprites)//2
    base = [[sum((int(p)!=15) << (15-x) for x,p in enumerate(row)) for row in pixels] for pixels in sprites[:half]]
    for flip_y in (False,True):
      for index,pixels in enumerate(sprites):
        opaque = [sum((int(p)!=15) << (15-x) for x,p in enumerate(row)) for row in pixels]
        key = base[index % half]
        order = sorted(range(16),key=lambda y:(key[y]==0,key[y],y))
        if not flip_y:
            if index < half:
                orders.extend(order)
            blanks.append(int(not any(opaque)))
        groups=[]
        for row in order:
            mask=opaque[row]
            if not mask:
                break
            if not groups or groups[-1][0]!=mask:
                groups.append((mask,[]))
            groups[-1][1].append(row)
        values=[('w',len(groups)-1)]
        pos=0
        for mask,rows in groups:
            values += [('w',mask_index[mask]*4),('w',len(rows)-1)]
            for row in rows:
                draw_row = 15-row if flip_y else row
                values.append(('l',draw_row*STRIDE-pos))
                pos=draw_row*STRIDE+8
        stream=tuple(values)
        if stream not in streams:
            streams[stream]=len(streams)
        pointers.append(streams[stream])
    out=['\tsection data,data','\teven',f'BT_MASK_STRIDE = {len(mask_values)*4}','bt_sprite_masks:']
    for shift in range(16):
        for mask in mask_values:
            out.append(f'\tdc.w ${mask>>shift:04x},${((mask<<(16-shift))&65535) if shift else 0:04x}')
    out += ['bt_sprite_streams:', '\tdc.l '+','.join(f'btstr{i}' for i in pointers)]
    for stream,index in streams.items():
        out += [f'btstr{index}:']
        for kind,value in stream:
            out.append(f'\tdc.{kind} {value}')
    out += ['\tsection text,code', 'bt_sprite_draw:',
            '\tmove.w (a0)+,d2', '\tbmi.s .done', '.group:',
            '\tmove.w (a0)+,d0', '\tmove.l (a1,d0.w),d0',
            '\tmove.w d0,(a3)', '\tswap d0', '\tmove.w d0,(a2)',
            '\tmove.w (a0)+,d3', '.row:', '\tmove.l (a0)+,d1',
            '\tadd.l d1,(a4)', '\tmove.w #4,(a5)', '\tmove.w d6,(a6)',
            '\tdbf d3,.row', '\tdbf d2,.group', '.done:', '\trts']
    return '\n'.join(out)+'\n',bytes(orders),bytes(blanks)


def palette():
    # Deterministic samples from the reference's own attract/gameplay sequence.
    m = BlackTiger()
    hist = np.zeros(4096,np.int64)
    from logic_test import inputs
    for frame in range(2600):
        m.inputs[:3] = inputs(frame)
        m.run_frame_port()
        if frame % 20 == 0 and frame > 300:
            values = np.frombuffer(m.mem,np.uint8)
            pal = values[0xd800:0xdc00].astype(np.uint16) | values[0xdc00:0xe000].astype(np.uint16)<<8
            hist += np.bincount((pal[m.render_raw()[16:240]]&4095).ravel(),minlength=4096)
    rgb = np.array([[(v>>4&15)*17,(v&15)*17,(v>>8&15)*17] for v in range(4096)],np.uint8)
    # Cap the repeated black backdrop; dedicate slot 0 to true black.
    counts = np.minimum(hist,50000)
    counts[0]=0
    samples = np.repeat(rgb, np.maximum(0, counts//50),axis=0)
    q = Image.fromarray(samples.reshape(1,-1,3)).quantize(colors=15)
    colours = np.array(q.getpalette()[:45],np.uint8).reshape(15,3)
    colours = np.round(colours/17).astype(np.uint8)*17
    colours = np.vstack((np.zeros((1,3),np.uint8),colours))
    distance = ((rgb[:,None,:].astype(np.int32)-colours[None,:,:])**2 * np.array([2,4,1])).sum(axis=2)
    mapping = distance.argmin(axis=1).astype(np.uint8)
    regs=[]
    for r,g,b in colours//17:
        conv=lambda n: ((int(n)>>1)&7) | ((int(n)&1)<<3)
        regs.append((conv(r)<<8)|(conv(g)<<4)|conv(b))
    return colours,mapping,np.array(regs,'>u2')


def build():
    dest = build_dir('blktiger')
    g=Gfx()
    tile = np.concatenate((g.tiles,g.tiles[:,:,::-1]))
    sprites = np.concatenate((g.sprites,g.sprites[:,:,::-1]))
    (dest/'tile_pixels.bin').write_bytes(packed(g.tiles))
    (dest/'tile_front.bin').write_bytes(bytes(sum(int((p < limit).any()) << bit for bit,limit in enumerate((4,8,12))) for p in g.tiles))
    (dest/'sprite_pixels.bin').write_bytes(packed(g.sprites))
    (dest/'char_pixels.bin').write_bytes(packed(g.chars))
    text,order,blank = programs(sprites)
    (dest/'sprite_code.s').write_text(text)
    (dest/'sprite_order.bin').write_bytes(order)
    (dest/'sprite_blank.bin').write_bytes(blank)
    (dest/'char_blank.bin').write_bytes(bytes(int(not (p!=3).any()) for p in g.chars))
    if not (dest/'palette_rgb.bin').exists():
        colours,mapping,regs=palette()
        (dest/'palette_rgb.bin').write_bytes(colours.tobytes())
        (dest/'rgb_map.bin').write_bytes(mapping.tobytes())
        (dest/'palette.bin').write_bytes(regs.tobytes())
    print('renderer assets:',dest,flush=True)


class Oracle:
    def __init__(self):
        dest=build_dir('blktiger')
        self.mapping=np.frombuffer((dest/'rgb_map.bin').read_bytes(),np.uint8)
        self.rgb=np.frombuffer((dest/'palette_rgb.bin').read_bytes(),np.uint8).reshape(16,3)

    def frame(self,m):
        values=np.frombuffer(m.mem,np.uint8)
        pal=values[0xd800:0xdc00].astype(np.uint16)|values[0xdc00:0xe000].astype(np.uint16)<<8
        return self.mapping[pal[m.render_raw()[16:240]]&4095]


if __name__ == '__main__':
    build()
