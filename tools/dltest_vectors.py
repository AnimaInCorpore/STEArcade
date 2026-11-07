"""ROM-free Blitter fixtures. Pixel reference deliberately does not simulate registers.

Pass preparation is the actual shared sprite preparation used by the ports;
expected output paints coloured opaque pixels into an independent planar image.
"""
import json
import math
import random
from pathlib import Path
import struct
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'engine'))
from sprite_programs import align_of, pass_of, clipped_pass


def planar_pixel(buf, x, colour):
    group, bit = divmod(x, 16)
    for plane in range(4):
        off = group * 8 + plane * 2
        word = int.from_bytes(buf[off:off+2], 'big')
        word = (word & ~(1 << (15-bit))) | (((colour >> plane) & 1) << (15-bit))
        buf[off:off+2] = word.to_bytes(2, 'big')


def generate(out):
    out = Path(out)
    masks = [0, 0xffff, 0x8001, 0x5555, 0x0100, 0x0001, 0x0810, 0x7ffe, 0xbded]
    records, manifest = [], []
    # Fixed record: header (id,pass count), initial/expected/source (128+128+32),
    # up to 2 pass records (source/destination offset,SXI,SYI,E1,E3,DXI,DYI,XC,skew).
    for mask in masks:
        for shift in range(16):
            for clip in range(3):
                for colour_set in range(3):
                    cid = len(records)
                    initial = bytearray(((i*73 + cid*29 + (i >> 2)) & 255) for i in range(128))
                    expected = bytearray(initial)
                    source = bytearray(32)
                    colours = [[5]*16, list(range(16)), [(i*7+cid) & 15 for i in range(16)]][colour_set]
                    if mask:
                        lz = align_of(mask)
                        for p in range(4):
                            word = sum(((colours[x] >> p) & 1) << (15-x) for x in range(16))
                            word = (word << lz) & 0xffff
                            source[2*p:2*p+2] = word.to_bytes(2, 'big')
                        ps = clipped_pass(mask, shift, clip) if clip and shift else pass_of(mask, shift)
                    else:
                        ps = None
                    passes = []
                    if ps:
                        kind, em1, em3, xc, dyi, ctl = ps
                        passes.append((0, 32+(8 if kind == 'R' else 0), 0, 2, em1, em3, 8, dyi, xc, ctl & 255))
                    for x in range(16):
                        dx = shift+x
                        if not mask & (0x8000 >> x):
                            continue
                        # Shift 0 has no straddling edge, matching the port's clip contract.
                        if shift and ((clip == 1 and dx < 16) or (clip == 2 and dx >= 16)):
                            continue
                        planar_pixel(expected, 64+dx, colours[x])
                    packed = struct.pack('>HH', cid, len(passes)) + initial + expected + source
                    for ps in passes:
                        packed += struct.pack('>10H', *(v & 0xffff for v in ps))
                    packed += bytes(40 - 20*len(passes))
                    assert len(packed) == 332
                    records.append(packed)
                    manifest.append(dict(id=cid, kind='sprite', mask=f'{mask:04x}', shift=shift,
                                         clip=['none','left','right'][clip], colours=colour_set, passes=passes))
    # Wide forward/reverse four-plane copies exercise X/Y increments and end masks.
    for width in [1, 2, 4]:
        for reverse in [False, True]:
            for opaque in [False, True]:
                cid = len(records)
                initial = bytearray((i*41+cid*13) & 255 for i in range(128))
                expected = bytearray(initial)
                source = bytearray((i*89+cid*17) & 255 for i in range(32))
                left, right = ((0xffff,0xffff) if opaque else (0xbdef,0x7bf7))
                if width == 1:
                    right = left
                for x in range(width*16):
                    group, bit = divmod(x,16)
                    mask = left if group == 0 else right if group == width-1 else 0xffff
                    if mask & (0x8000 >> bit):
                        colour = sum(((source[p*width*2+group*2] << 8 |
                                      source[p*width*2+group*2+1]) >> (15-bit) & 1) << p for p in range(4))
                        planar_pixel(expected, 64+x, colour)
                ps = ((2*(width-1) if reverse else 0), 32+(8*(width-1) if reverse else 0),
                      -2 if reverse and width>1 else 2, 4*width-2 if reverse else 2,
                      right if reverse else left, left if reverse else right,
                      -8 if reverse else 8, 8*(width-1)+2 if reverse else 2-8*(width-1), width, 0xc0 if reverse and width>1 else 0)
                packed = struct.pack('>HH',cid,1) + initial + expected + source
                packed += struct.pack('>10H', *(v & 0xffff for v in ps)) + bytes(20)
                records.append(packed)
                manifest.append(dict(id=cid,kind='wide',width=width,reverse=reverse,opaque=opaque,passes=[ps]))
    rng=random.Random(0x68000)
    cpu=bytearray()
    for _ in range(64):
        a,b=rng.randrange(65536),rng.randrange(65536)
        divisor=rng.randrange(1,65536); dividend=rng.randrange(divisor*65536)
        q,r=divmod(dividend,divisor)
        cpu+=struct.pack('>HHIIHI',a,b,a*b,dividend,divisor,(r<<16)|q)
    (out/'cpu_vectors.bin').write_bytes(cpu)
    audio=bytearray()
    for i in range(6258*2):
        t=i/6258; f=440 if t<1 else 660
        value=round(32*math.sin(2*math.pi*f*t)) & 255
        audio+=bytes([value,0] if t<1 else [0,value])
    (out/'audio.bin').write_bytes(audio)
    (out/'blit_vectors.bin').write_bytes(b''.join(records))
    (out/'blit_cases.json').write_text(json.dumps(dict(record_bytes=332, cases=manifest),indent=2)+'\n')
    (out/'dltest_vectors.i').write_text(f'VECTOR_COUNT = {len(records)}\nVECTOR_SIZE = 332\n')
    return len(records)



# Palette deliberately uses only STE nibbles 0..7: emulator RGB decoding is unambiguous.
PALETTE = [0x000,0x111,0x222,0x333,0x444,0x555,0x666,0x777,
           0x700,0x070,0x007,0x770,0x707,0x077,0x731,0x157]


def bmp_bytes(planar, height=200, palette=PALETTE):
    pixels = bytearray()
    for y in reversed(range(height)):
        row = planar[y*160:(y+1)*160]
        for x in range(0,320,2):
            pair = 0
            for xx in [x,x+1]:
                g,b = divmod(xx,16)
                col = sum(((int.from_bytes(row[g*8+p*2:g*8+p*2+2],'big') >> (15-b)) & 1) << p for p in range(4))
                pair = pair*16+col
            pixels.append(pair)
    header = struct.pack('<2sIHHI',b'BM',118+len(pixels),0,0,118)
    header += struct.pack('<IiiHHIIiiII',40,320,height,1,4,0,len(pixels),2835,2835,16,16)
    for c in palette:
        header += bytes([(c & 7)*34,((c>>4)&7)*34,((c>>8)&7)*34,0])
    return header+pixels


def scene_generate(out):
    """32 complete bob scenes, with CPU reference drawn in input priority order.

    Four 32x32 original procedural bobs. Prepared rows are mask-grouped as in
    stefastbobs2; a 32-pixel bob is two 16-pixel pieces for the shared port method.
    Every frame includes partial left/right edges, top/bottom guards, overlaps,
    and wholly culled objects. No copyrighted game graphics or external assets.
    """
    from sprite_programs import shape_order
    art = []
    source = bytearray()
    rows = {}
    for sid in range(4):
        sprite = []
        for y in range(32):
            row=[]
            for x in range(32):
                r2=(x-15.5)**2+(y-15.5)**2
                if r2>15.3**2 or (sid & 1 and 12<=x<20 and 12<=y<20):
                    row.append(None)
                elif (x-10)**2+(y-9)**2<10:
                    row.append(7)
                else:
                    shade=max(1,min(6,round(7-(r2**.5)/3.2+(15-y)/10)))
                    row.append([shade,8+(shade%8),8+((shade+sid)%8),shade][sid])
            sprite.append(row)
        art.append(sprite)
        for chunk in range(2):
            masks=[sum(1<<(15-x) for x in range(16) if sprite[y][chunk*16+x] is not None) for y in range(32)]
            prepared=[]
            for group in shape_order(masks):
                for y in group:
                    mask=masks[y]; lz=align_of(mask); offset=len(source)
                    for p in range(4):
                        word=sum((((sprite[y][chunk*16+x] or 0)>>p)&1)<<(15-x) for x in range(16))
                        source += struct.pack('>H',(word<<lz)&0xffff)
                    prepared.append((y,mask,offset))
            rows[sid,chunk]=prepared
    (out/'scene_source.bin').write_bytes(source)
    background=bytearray(38400)
    for y in range(240):
        line=bytearray(160)
        for x in range(320):
            if x%32==0 or (y-16)%32==0:
                planar_pixel(line,x,1)
        background[y*160:(y+1)*160]=line
    (out/'scene_bg.bin').write_bytes(background)
    blobs=[]; refs=[]; manifest=[]
    for frame in range(32):
        shift=frame & 15
        objects=[]
        # 20 regular bobs, drawn in order; crowded positions overlap with the next.
        for i in range(20):
            x=28+(i%5)*48+shift
            y=16+(i//5)*42
            if frame>=16:
                x += (i%3)*9; y -= (i%2)*6
            objects.append((i%4,x,y))
        objects += [(0,-31+shift,70),(1,304+shift,105),(2,90,-12+shift%4),
                    (3,220,188+shift%4),(0,-40,25),(1,336,25)]
        if frame>=16:
            objects.reverse()
        expected=bytearray(background)
        passes=[]
        for sid,x,y in objects:
            if x>=320 or x+32<=0:
                continue
            # Independent painter preserves priority, holes, and guard pixels.
            for ry,row in enumerate(art[sid]):
                yy=y+ry+16
                if not 0<=yy<240:
                    continue
                for rx,col in enumerate(row):
                    xx=x+rx
                    if col is not None and 0<=xx<320:
                        off=yy*160
                        sub=expected[off:off+160]
                        planar_pixel(sub,xx,col)
                        expected[off:off+160]=sub
            for chunk in range(2):
                xx=x+16*chunk
                if xx>=320 or xx+16<=0:
                    continue
                shiftx=xx & 15; group=xx//16
                clip=1 if group<0 else 2 if group==19 else 0
                for ry,mask,src in rows[sid,chunk]:
                    yy=y+ry+16
                    if not 0<=yy<240:
                        continue
                    ps=clipped_pass(mask,shiftx,clip) if clip and shiftx else pass_of(mask,shiftx)
                    if ps is None:
                        continue
                    kind,em1,em3,xc,dyi,ctl=ps
                    dst=yy*160+group*8+(8 if kind=='R' else 0)
                    assert 0<=dst<38400
                    passes.append((src,dst,0,2,em1,em3,8,dyi,xc,ctl&255))
        # Word PackBits: high bit literal count; otherwise count plus repeated word.
        words=struct.unpack('>19200H',expected)
        rle=bytearray(); i=0
        while i<len(words):
            j=i+1
            while j<len(words) and words[j]==words[i] and j-i<32767:
                j+=1
            if j-i>=3:
                rle += struct.pack('>HH',j-i,words[i]); i=j
            else:
                j=i+1
                while j<len(words) and j-i<32767:
                    if j+2<len(words) and words[j]==words[j+1]==words[j+2]:
                        break
                    j+=1
                rle += struct.pack('>H',0x8000|(j-i))+struct.pack('>'+str(j-i)+'H',*words[i:j]); i=j
        rle += b'\0\0'
        body=b''.join(struct.pack('>10H',*(v&65535 for v in ps)) for ps in passes)
        blobs.append(struct.pack('>HHI',frame,len(passes),len(rle))+rle+body)
        refs.append(expected)
        manifest.append(dict(frame=frame,objects=objects,passes=len(passes)))
    offsets=[]; offset=32*4
    for blob in blobs:
        offsets.append(offset); offset+=len(blob)
    (out/'scenes.bin').write_bytes(struct.pack('>32I',*offsets)+b''.join(blobs))
    (out/'scene_cases.json').write_text(json.dumps(manifest,indent=2)+'\n')
    reference=out/'REFERENCE'; reference.mkdir(exist_ok=True)
    for frame in [0,15,31]:
        (reference/f'CPU{frame:02}.BMP').write_bytes(bmp_bytes(refs[frame][2560:34560]))
    # Full 256-line test picture inside the ports' 276-line hardware window.
    opened=bytearray(276*160)
    for y in range(256):
        line=bytearray(160)
        for x in range(320):
            col=1 if ((x//16)^(y//16))&1 else 2
            if y<32:
                col=x//20
            if x==160 or y==128:
                col=7
            if abs(x-160)==abs(y-128):
                col=8+(y//16)%8
            if x==0: col=8
            if x==319: col=9
            if y==0 or y==255: col=7
            if y in [1,254] and x%8<4: col=12
            planar_pixel(line,x,col)
        opened[(y+10)*160:(y+11)*160]=line
    (out/'open_screen.bin').write_bytes(opened)
    (reference/'OPENCPU.BMP').write_bytes(bmp_bytes(opened[1600:1600+40960],256))
    (out/'bmp_header.bin').write_bytes(bmp_bytes(bytes(32000))[:118])
    return len(source), sum(len(x) for x in blobs)

if __name__ == '__main__':
    generate(sys.argv[1])
    scene_generate(Path(sys.argv[1]))
