"""Screen-oriented pen masks, 16-colour STE palette and baked Blitter streams."""
from pathlib import Path
import sys,importlib.util,json,random
import numpy as np
from machine import Gfx,Commando,BUILD

def helper(name,file):
    old=list(sys.path)
    spec=importlib.util.spec_from_file_location(name,file);mod=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod);sys.path[:]=old
    return mod
HERE=Path(__file__).resolve().parents[2]/'1942/tools'
sg=helper('commando_sprite_codegen',HERE/'spritegen.py')
pal=helper('commando_palette_quantizer',HERE/'palettes.py')

def one_hot(pixels,pens):
    width=pixels.shape[-1]
    return np.stack([sum((pixels[...,i]==p).astype(np.uint16)<<(15-i) for i in range(width))
                     for p in range(pens)],axis=-1)

def build():
    g=Gfx()
    m=Commando();m.gfx=g;weights=np.zeros(256)
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'ref'))
    from cover import inputs
    rnd=random.Random(1)
    for f in range(2600):
        m.inputs[:3]=inputs(f,rnd);m.run_frame_port()
        if f in (100,300,700,900,1000,1200,1500,1800,2200,2500):
            weights+=np.bincount(m.render_raw()[16:240].ravel(),minlength=256)
    colours=pal.oklab_to_rgb(pal.kmeans(g.rgb,weights**0.6+1,16))
    colours=np.round(colours/17)*17;colours[0]=0
    mapping=((pal.rgb_to_oklab(g.rgb)[:,None]-pal.rgb_to_oklab(colours)[None])**2).sum(axis=2).argmin(axis=1)
    (BUILD/'palmap.bin').write_bytes(mapping.astype(np.uint8).tobytes())
    (BUILD/'palette.bin').write_bytes(np.array([pal.ste_word(c) for c in colours],'>u2').tobytes())
    docs=Path(__file__).resolve().parents[1]/'docs'
    (docs/'palette.json').write_text(json.dumps(dict(rgb=colours.astype(int).tolist(),map=mapping.tolist()),indent=2)+'\n')
    # The arcade pens as bit planes, a word a plane a row (render.s expand_pens makes a mask a pen of them when it
    # bakes an object: 2.25 x less than the masks themselves; 3, 4 and 2 planes).
    for name,pixels,pens in [('tile',g.tiles,8),('spr',g.sprites,16),('chr',g.chars,4)]:
        oriented=pixels.transpose(0,2,1)[:,::-1]
        width=oriented.shape[-1]
        planes=np.stack([sum((((oriented[...,i]>>b)&1).astype(np.uint16)<<(15-i)) for i in range(width))
                         for b in range(pens.bit_length()-1)],axis=-1)
        (BUILD/(name+'_planes.bin')).write_bytes(planes.astype('>u2').tobytes())
        (BUILD/(name+'_blank.bin')).write_bytes(bytes(int(np.all(t==(15 if name=='spr' else 3))) for t in oriented))
    oriented=g.sprites.transpose(0,2,1)[:,::-1]
    variants=np.array([t[::-1 if flip&1 else 1, ::-1 if flip&2 else 1]
                       for t in oriented for flip in range(4)])
    opaque=one_hot((variants!=15).astype(np.uint8),2)[...,1]
    orders=[sorted(range(16),key=lambda r:(int(mask[r])==0,int(mask[r]),r)) for mask in opaque]
    (BUILD/'spr_order.bin').write_bytes(bytes(r for order in orders for r in order))
    result=sg.write(str(BUILD),opaque,orders)
    vranges()
    print('Blitter routines/bytes, streams/bytes, checked pairs, plan bytes:',result,flush=True)
    # Shifted character masks are baked as words for fixed 8px positions (0 or 8).
    chars=g.chars.transpose(0,2,1)[:,::-1]
    variants=np.array([t[::-1 if flip&1 else 1, ::-1 if flip&2 else 1]
                       for t in chars for flip in range(4)])
    opaque=one_hot((variants!=3).astype(np.uint8),2)[...,1]
    (BUILD/'chr_opaque.bin').write_bytes(np.stack([opaque,opaque>>8],axis=1).astype('>u2').tobytes())
    (BUILD/'reverse.bin').write_bytes(bytes(int(f'{i:08b}'[::-1],2) for i in range(256)))
    lines=['orp_tab:']+[f'\tdc.l orp{i}' for i in range(16)]
    for i in range(16):
        lines += [f'orp{i}:']+[f'\tor.w d7,d{3+k}' for k in range(4) if i&(1<<k)]+['\trts']
    # Tile end masks/control are baked for every scroll skew.
    lines+=['tile_shift:']
    for shift in range(16):
        lines.append('\tdc.w $%04x,$%04x,$%04x,%d,%d' % (0xffff>>shift, (0xffff<<(16-shift))&65535 if shift else 65535,
                        (0xc000|shift|(0x40 if shift else 0)),2 if shift else 1,256-(8 if shift else 0)))
    lines+=['copy_shift:']
    for shift in range(16):
        lines.append('\tdc.w $%04x,%d,8' % (((0x80|(16-shift))<<8) if shift else 0,384-(112 if shift else 104)))
    (BUILD/'render_tables.s').write_text('\n'.join(lines)+'\n')
def vranges():
    """spr_vrange.bin: per sprite variant (code * 4 + flips, the generated routines' index) its opaque screen rows as
    one byte: the first << 4 | their number - 1 (a blank variant: 0; it is never drawn).  draw_sprites records the damage
    of these rows only."""
    g=Gfx()
    oriented=g.sprites.transpose(0,2,1)[:,::-1]
    out=bytearray()
    for t in oriented:
        for flip in range(4):
            rows=np.flatnonzero((t[::-1 if flip&1 else 1, ::-1 if flip&2 else 1]!=15).any(axis=1))
            out.append(int(rows[0])<<4|int(rows[-1]-rows[0]) if len(rows) else 0)
    (BUILD/'spr_vrange.bin').write_bytes(bytes(out))
if __name__=='__main__':build()
