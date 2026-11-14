#!/usr/bin/env python3
"""Compare test 3's native RAM capture/BMP with Gun.Smoke's independent renderer.

Run with locally prepared Gun.Smoke assets, e.g. megaste_capture.py GSCAP0.BIN.
A correct RAM image does not prove that the monitor displayed that image.
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import sys
import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(Path(__file__).resolve().parent), str(ROOT / 'engine')]
HEAD = 96
RAW = 168 * 256
SLOT = HEAD + RAW + 2048 + 512


def decode(path):
    data = path.read_bytes()
    assert len(data) == SLOT and data[:4] == b'GSF3', (path, len(data))
    version, fine = struct.unpack_from('>2H', data, 4)
    assert version == 3 and 0 <= fine < 16
    assert struct.unpack_from('>3H', data, 28) == (168, 336, 256)
    raw = np.frombuffer(data[HEAD:HEAD+RAW], np.uint8).reshape(256, 21, 4, 2)
    words = raw[..., 0].astype(np.uint16) * 256 + raw[..., 1]
    pixels = np.zeros((256, 336), np.uint8)
    for plane in range(4):
        for bit in range(16):
            pixels[:, bit::16] |= ((words[:, :, plane] >> (15-bit)) & 1).astype(np.uint8) << plane
    palette = np.frombuffer(data[48:80], '>u2').astype(np.uint16)
    rgb = np.stack([(((palette >> shift) & 7) * 2 + ((palette >> (shift+3)) & 1)) * 17
                    for shift in (8, 4, 0)], axis=1).astype(np.uint8)
    return data, pixels[:, fine:fine+320], rgb


def compare(path):
    from machine import GunSmoke
    from video import Video
    import palette_quantize as pq
    manifest=path.parent/'BUILD.JSN'
    assets=json.loads(manifest.read_text()).get('asset_sha256',{}) if manifest.exists() else {}
    for name,digest in assets.items():
        assert hashlib.sha256((ROOT/name).read_bytes()).hexdigest()==digest, ('reference asset differs',name)
    data, pixels, rgb = decode(path)
    bmp = np.array(Image.open(path.with_suffix('.BMP')).convert('RGB'))
    assert np.array_equal(bmp, rgb[pixels]), 'native BMP does not match captured planar RAM'
    m = GunSmoke()
    m.control, m.layers = data[20], data[21]
    m.mem[0xd800:0xd803] = data[22:25]
    state = data[HEAD+RAW:]
    m.mem[0xd000:0xd800] = state[:2048]
    m.sprites[:] = bytes(4096)
    for i in range(128):
        m.sprites[i*32:i*32+4] = state[2048+i*4:2048+i*4+4]
    palette = json.loads((ROOT/'games/gunsmoke/docs/palette.json').read_text())
    mapping = np.array(palette['map'], np.uint8)
    approved_rgb = np.array(palette['rgb'], np.uint8)
    palette_matches = data[48:80] == (ROOT/'build/gunsmoke/palette.bin').read_bytes() and np.array_equal(rgb,approved_rgb)
    raw = Video().render_raw(m, checker=True)[16:240].T[::-1]
    want = np.zeros_like(pixels)
    want[:, 48:272] = pq.indices(mapping[raw & 1023], raw >> 10)
    different = int(np.count_nonzero(pixels != want))
    Image.fromarray(approved_rgb[want]).save(path.with_name(path.stem+'-reference.png'))
    result = dict(file=path.name, tick=struct.unpack_from('>L', data, 8)[0],
                  vbl=struct.unpack_from('>L', data, 40)[0], fine=struct.unpack_from('>H', data, 6)[0],
                  cpu_mode=data[25] & 3, bmp_matches_planar_ram=True,
                  asset_identity_checked=bool(assets),
                  palette_matches_reference=palette_matches,
                  differing_reference_pixels=different, scope='framebuffer, not monitor scanout')
    path.with_suffix('.json').write_text(json.dumps(result, indent=2)+'\n')
    if different or not palette_matches:
        Image.fromarray((pixels != want).astype(np.uint8)*255).save(path.with_name(path.stem+'-difference.png'))
        raise AssertionError(result)
    print(result)
    return result


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('capture', type=Path, nargs='+')
    for path in ap.parse_args().capture:
        compare(path.resolve())
