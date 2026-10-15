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

def pen_planes(pixels,planes):
    """(objects, rows, planes) words: bit j of each pixel's pen, the first pixel in the high bit"""
    width=pixels.shape[-1]
    return np.stack([sum((((pixels[...,i]>>j)&1).astype(np.uint16))<<(15-i) for i in range(width))
                     for j in range(planes)],axis=-1)


def bake_rows(mapping):
    """The bake's row routines (render.s get_object_bake), one per kind and colour: a row's pen planes in d0-d1
    (characters), d0-d2 (tiles), d0-d3 (sprites) -> the STE planes 0-3 in d4-d7, through the colour map.  A pen's
    pixels are the product of its pair of the low planes (A: 8 bytes at a2, as movem.w d0/d1/d4/d5 leaves them) and
    of its pair of the high ones (B, in d0).  Characters keep their four products in registers and leave pen 3 (the
    transparent pen) in d2; their pixels are the high byte."""
    lines=[]
    def ors(reg,value):
        return [f'\tor.w {reg},d{4+k}' for k in range(4) if value>>k&1]
    pairs=['\tmove.w d0,d4','\tand.w d1,d4','\teor.w d4,d0','\teor.w d4,d1',
           '\tmove.w d0,d5','\tor.w d1,d5','\tor.w d4,d5','\tnot.w d5']   # pen bits 0-1: 3 d4, 1 d0, 2 d1, 0 d5
    clear=[f'\tmoveq #0,d{4+k}' for k in range(4)]
    offset={1:0,2:2,3:4,0:6}                                              # (movem.w d0/d1/d4/d5,(a2))
    highs={'tile':[['\tmove.w d2,d0','\tnot.w d0'],['\tmove.w d2,d0']],
           'spr':[['\tmove.w d2,d0','\tor.w d3,d0','\tnot.w d0'],['\tmove.w d3,d0','\tnot.w d0','\tand.w d2,d0'],
                  ['\tmove.w d2,d0','\tnot.w d0','\tand.w d3,d0'],['\tmove.w d2,d0','\tand.w d3,d0']]}
    for kind,base,pens,colours in (('tile',0,8,16),('spr',128,16,4)):
        lines.append(f'bake_{kind}_rows:')
        lines+=[f'\tdc.l bake_{kind}{c}' for c in range(colours)]
        for c in range(colours):
            lines+=[f'bake_{kind}{c}:']+pairs+['\tmovem.w d0/d1/d4/d5,(a2)']+clear
            for j,high in enumerate(highs[kind]):
                values=[int(mapping[base+c*pens+4*j+i]) for i in range(4)]
                if not any(values):continue
                lines+=high
                for i,v in enumerate(values):
                    if v:lines+=[f'\tmove.w {offset[i]}(a2),d1','\tand.w d0,d1']+ors('d1',v)
            lines.append('\trts')
    lines.append('bake_chr_rows:')
    lines+=[f'\tdc.l bake_chr{c}' for c in range(16)]
    for c in range(16):
        lines+=[f'bake_chr{c}:','\tmove.w d0,d2','\tand.w d1,d2','\teor.w d2,d0','\teor.w d2,d1',
                '\tmove.w d0,d3','\tor.w d1,d3','\tor.w d2,d3','\tnot.w d3','\tand.w #$ff00,d3']+clear
        for pen,reg in enumerate(('d3','d0','d1','d2')):
            lines+=ors(reg,int(mapping[192+c*4+pen]))
        lines.append('\trts')
    return lines


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
    # The objects as pen planes (render.s get_object_bake): per row the plane words (bit j of the pen), rows in order.
    for name,pixels,planes in [('tile',g.tiles,3),('spr',g.sprites,4),('chr',g.chars,2)]:
        oriented=pixels.transpose(0,2,1)[:,::-1]
        (BUILD/(name+'_planes.bin')).write_bytes(pen_planes(oriented,planes).astype('>u2').tobytes())
        (BUILD/(name+'_blank.bin')).write_bytes(bytes(int(np.all(t==(15 if name=='spr' else 3))) for t in oriented))
    oriented=g.sprites.transpose(0,2,1)[:,::-1]
    # The row order (equal masks together, blank rows last) comes from the sprite's own masks, for its flipped and
    # mirrored images too (a flip keeps equal rows equal and blank rows blank): spr_order holds base rows.  The baked
    # row j is the sprite's row order[j], which is row 15 - order[j] of the vertically flipped image (its routine's order).
    base=one_hot((oriented!=15).astype(np.uint8),2)[...,1]
    base_orders=[sorted(range(16),key=lambda r:(int(mask[r])==0,int(mask[r]),r)) for mask in base]
    (BUILD/'spr_order.bin').write_bytes(bytes(r for order in base_orders for r in order))
    variants=np.array([t[::-1 if flip&1 else 1, ::-1 if flip&2 else 1]
                       for t in oriented for flip in range(4)])
    opaque=one_hot((variants!=15).astype(np.uint8),2)[...,1]
    orders=[[15-r for r in base_orders[i//4]] if i&1 else base_orders[i//4] for i in range(len(variants))]
    result=sg.write(str(BUILD),opaque,orders)
    # The generic path's plans (spritegen.plan_bytes, one per image): equal plans stored once (an image and its mirror
    # image have the same rows and groups).
    offsets=np.frombuffer((BUILD/'spr_plan_offsets.bin').read_bytes(),'>u4')
    data=(BUILD/'spr_plan.bin').read_bytes();ends=list(offsets[1:])+[len(data)]
    shared,plans=bytearray(),{}
    for start,end in zip(offsets,ends):
        plans.setdefault(data[start:end],len(shared))
        if plans[data[start:end]]==len(shared):shared+=data[start:end]
    (BUILD/'spr_plan_offsets.bin').write_bytes(np.array([plans[data[a:b]] for a,b in zip(offsets,ends)],'>u4').tobytes())
    (BUILD/'spr_plan.bin').write_bytes(bytes(shared))
    result=result[:5]+(len(shared),)
    vranges()
    print('Blitter routines/bytes, streams/bytes, checked pairs, plan bytes:',result,flush=True)
    (BUILD/'reverse.bin').write_bytes(bytes(int(f'{i:08b}'[::-1],2) for i in range(256)))
    lines=bake_rows(mapping)
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
