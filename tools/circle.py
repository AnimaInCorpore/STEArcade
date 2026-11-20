#!/usr/bin/env python3
"""Build CIRCLE.PRG, the Mega STE interactive full-height test card."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import zipfile

import numpy as np
from PIL import Image

import bottomprobe
import videoctrl as vc

ROOT = vc.ROOT
HEIGHT = 276
# Black, white, primary/secondary colours, greys, and one accent.
PALETTE = [0x000, 0xfff, 0x700, 0x070, 0x007, 0x770, 0x077, 0x707,
           0x111, 0x222, 0x333, 0x444, 0x555, 0x666, 0x777, 0x753]
FONT = {
    'B': ['11110','10001','10001','11110','10001','10001','11110'],
    'D': ['11110','10001','10001','10001','10001','10001','11110'],
    'F': ['11111','10000','10000','11110','10000','10000','10000'],
    'U': ['10001','10001','10001','10001','10001','10001','01110'],
    'W': ['10001','10001','10001','10101','10101','10101','01010'],
}


def chart():
    """Draw an original colour/geometry chart with phase markers in both extensions."""
    y, x = np.indices((HEIGHT, 320))
    picture = np.full((HEIGHT, 320), 10, np.uint8)
    picture[(x % 16 == 0) | (y % 16 == 0)] = 13
    picture[(x % 64 == 0) | (y % 64 == 0)] = 14

    circle = ((x - 159.5) / 106)**2 + ((y - 132) / 102)**2
    picture[circle <= 1] = 1
    inside = circle <= .94

    def band(top, bottom, pixels):
        mask = inside & (y >= top) & (y < bottom)
        picture[mask] = pixels[mask]

    band(30, 67, np.where((x // 12) & 1, 0, 14))
    colours = np.array([5, 6, 3, 7, 2, 4], np.uint8)
    band(67, 107, colours[np.clip((x - 64) // 32, 0, 5)])
    greys = np.array([0, 8, 10, 12, 14, 1], np.uint8)
    band(107, 129, greys[np.clip((x - 64) // 32, 0, 5)])
    band(129, 141, np.where((y == 135) | (x == 159), 1, 0))
    pitch = np.array([8, 4, 3, 2, 1])[np.clip((x - 64) // 40, 0, 4)]
    band(141, 181, np.where((x // pitch) & 1, 1, 0))
    band(181, 205, np.where((x > 150) & (x < 168), 1, np.where(x < 160, 9, 13)))
    band(205, 240, np.where((x > 134) & (x < 185), 7, 15))

    # Side fiducials and black/white castellations expose centring and cropping.
    for start, palette in [(17, [2, 5, 3, 6]), (288, [4, 7, 2, 5])]:
        for i, colour in enumerate(palette):
            row = 73 + 36*i
            picture[row:row+24, start:start+15] = colour
    frame = np.zeros((320, 512), np.uint8)
    frame[:HEIGHT, :320] = picture
    frame[:3, :320] = ((x[:3] // 8) & 1)
    frame[271:274, :320] = ((x[:3] // 8) & 1)
    frame[:HEIGHT, :3] = ((y[:, :3] // 8) & 1)
    frame[:HEIGHT, 317:320] = ((y[:, :3] // 8) & 1)
    # Vertical blank masks the last two timing rows on the pinned STE model.
    frame[274:276, :320] = 0
    # Two phase strips with individually identifiable 16-pixel cells.
    strip = np.array([0, 1, 2, 3, 4, 5, 6, 7, 8, 9,
                      10, 11, 12, 13, 14, 15, 4, 2, 6, 1], np.uint8)
    frame[8:20, :320] = strip[x[8:20] // 16]
    frame[247:267, :320] = strip[x[247:267] // 16]
    frame[32:64, :48] = 0
    return frame


def kernel():
    body = bottomprobe.kernel()
    start = body.index('bd_fast_top:')
    end = body.index('; bd_speed_poll:', start)
    top = body[start:end]
    first = '\tmoveq #BD_FAST_TOP_DELAY,d2'
    second = '\tmoveq #BD_FAST_TOP_PULSE,d2'
    assert top.count(first) == top.count(second) == 1
    # Load both counts before the final HBL. The post-write MOVE.W register
    # form costs the same CPU cycles as the prior MOVEQ.
    top = top.replace(first, '\tmove.w circle_top_delay,d2\n\tmove.w circle_top_width,d0')
    top = top.replace(second, '\tmove.w d0,d2')
    return body[:start] + top + body[end:]


def build(out):
    out.mkdir(parents=True, exist_ok=True)
    frame = chart()
    (out/'FRAME.BIN').write_bytes(vc.planar(frame))
    (out/'PALETTE.BIN').write_bytes(np.array(PALETTE, dtype='>u2').tobytes())
    rgb = np.array([[17 * (((v >> n) & 7) * 2 + ((v >> (n + 3)) & 1))
                     for n in (8, 4, 0)] for v in PALETTE], dtype=np.uint8)
    Image.fromarray(rgb[frame[:HEIGHT, :320]]).save(out/'REFPIC.BMP')
    vc.FONT.update(FONT)
    tiles = {
        'MODE.BIN': ['BOTH', 'TOP', 'CLOSED', 'FULL'],
        'TOP.BIN': [f'U{d:03} W{w:02}' for d in range(74, 83) for w in range(6, 11)],
        'BOTTOM.BIN': [f'D{d:03} W{w:02}' for d in range(97, 106) for w in range(13, 22)],
        'CPU.BIN': ['16C ON'],
    }
    for name, labels in tiles.items():
        (out/name).write_bytes(b''.join(vc.tile([label], 1) for label in labels))
    # Shared data labels still expect these inputs. CIRCLE uses its own HUD.
    (out/'LABELS.BIN').write_bytes(bytes(24*24))
    (out/'TIMERS.BIN').write_bytes(bytes(24*8))
    (out/'bp_phases.i').write_text('\tdc.w 0,2,1,101,17,0\n')
    (out/'vc_borders.i').write_text(kernel())
    for name in ('circle.s', 'circle.i', 'videoctrl.s', 'bottomprobe.i'):
        shutil.copy(ROOT/'tools'/name, out/name)
    shutil.copy(vc.paths.RT_INCLUDE/'ikbd.s', out/'ikbd.s')

    sources = ['circle.s', 'circle.i', 'videoctrl.s', 'bottomprobe.i', 'ikbd.s',
               'vc_borders.i', 'bp_phases.i', 'FRAME.BIN', 'PALETTE.BIN',
               'LABELS.BIN', 'TIMERS.BIN', *tiles]
    hashes = {name: vc.sha(out/name) for name in sources}
    build_id = hashlib.sha256(json.dumps(hashes, sort_keys=True).encode()).hexdigest()[:16]
    (out/'vc_build.i').write_text(f"\tdc.b 'Build {build_id}',13,10\n")
    subprocess.run([vc.paths.VASM, '-m68000', '-Fvobj', '-quiet', '-nowarn=2047',
                    '-I.', '-o', 'circle.o', 'circle.s'], cwd=out, check=True)
    subprocess.run([vc.paths.VLINK, '-b', 'ataritos', '-s', '-o', 'CIRCLE.PRG',
                    '-MCIRCLE.MAP', 'circle.o'], cwd=out, check=True)
    manifest = dict(build=build_id, executable_sha256=vc.sha(out/'CIRCLE.PRG'),
                    sources=hashes, cpu='16 MHz/cache on', picture=[320, HEIGHT],
                    top_default=[78,8], bottom_default=[101,17],
                    default_status='Hatari reference; physical stability unverified')
    (out/'BUILD.JSN').write_text(json.dumps(manifest, indent=2)+'\n')
    for name, suffix in [('README.TXT', 'readme'), ('MESSAGE.TXT', 'message')]:
        doc = (ROOT/'docs'/f'megaste-circle-{suffix}.txt').read_text()
        (out/name).write_bytes(doc.replace('\n','\r\n').encode('ascii'))
    with zipfile.ZipFile(out/'SOURCE.ZIP', 'w', zipfile.ZIP_DEFLATED) as archive:
        for name in sources + ['vc_build.i', 'CIRCLE.MAP']:
            archive.write(out/name, name)
    names = ['CIRCLE.PRG', 'REFPIC.BMP', 'README.TXT', 'MESSAGE.TXT', 'BUILD.JSN', 'SOURCE.ZIP']
    (out/'SHA256.TXT').write_bytes(''.join(f'{vc.sha(out/n)}  {n}\r\n' for n in names).encode('ascii'))
    with zipfile.ZipFile(out/'CIRCLE.ZIP', 'w', zipfile.ZIP_DEFLATED) as archive:
        for name in names + ['SHA256.TXT']:
            archive.write(out/name, 'CIRCLE/'+name)
    print(out/'CIRCLE.ZIP', build_id, manifest['executable_sha256'])


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, default=ROOT/'build/megaste-circle')
    build(parser.parse_args().out.resolve())
