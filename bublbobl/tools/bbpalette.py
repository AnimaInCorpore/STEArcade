"""The port's 16-colour palette (JsOklabQuantizer default result) and Oklab nearest-colour mapping.

  python bbpalette.py            build docs/palette16.json from docs/quant/attract_collage_q16_default.json
                                 and verify the numpy mapping reproduces the quantizer's own image bit for bit
Library: load_palette16(), quantize_rgb(rgb_hxwx3) -> (index map, rgb), lut_from_palette_ram(palram).

Mapping rule = js/main.mjs renderQuantizedImage: nearest palette entry by squared Euclidean distance in
Oklab (first entry wins ties); source colour -> Oklab exactly as js/color.mjs rgb8ToOklab.
"""
import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
DOCS = os.path.join(HERE, "..", "docs")
PALETTE16 = os.path.join(DOCS, "palette16.json")


def srgb_to_linear(v):
    v = v / 255.0
    return np.where(v <= 0.04045, v / 12.92, ((v + 0.055) / 1.055) ** 2.4)


def rgb_to_oklab(rgb):
    """rgb: [...,3] uint8 -> [...,3] float64 (L, a, b), same constants as js/color.mjs"""
    r, g, b = (srgb_to_linear(rgb[..., i].astype(np.float64)) for i in range(3))
    l = np.cbrt(0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b)
    m = np.cbrt(0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b)
    s = np.cbrt(0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b)
    return np.stack([0.2104542553 * l + 0.7936177850 * m - 0.0040720468 * s,
                     1.9779984951 * l - 2.4285922050 * m + 0.4505937099 * s,
                     0.0259040371 * l + 0.7827717662 * m - 0.8086757660 * s], axis=-1)


def load_palette16():
    p = json.load(open(PALETTE16))["palette"]
    lab = np.array([[c["L"], c["a"], c["b"]] for c in p])
    rgb = np.array([[int(c["rgb"][i:i + 2], 16) for i in (1, 3, 5)] for c in p], np.uint8)
    return lab, rgb


def quantize_rgb(img):
    """-> (indices uint8 [H,W], rgb uint8 [H,W,3]); one lookup per distinct colour"""
    lab, pal = load_palette16()
    flat = img.reshape(-1, 3)
    key = (flat[:, 0].astype(np.uint32) << 16) | (flat[:, 1].astype(np.uint32) << 8) | flat[:, 2]
    uk, inv = np.unique(key, return_inverse=True)
    ucol = np.stack([(uk >> 16) & 255, (uk >> 8) & 255, uk & 255], axis=-1).astype(np.uint8)
    d = ((rgb_to_oklab(ucol)[:, None, :] - lab[None, :, :]) ** 2).sum(axis=2)
    uidx = d.argmin(axis=1).astype(np.uint8)          # argmin = first minimum, like the JS loop
    idx = uidx[inv].reshape(img.shape[:2])
    return idx, pal[idx]


def lut_from_palette_ram(palram):
    """256 board palette entries (RGBx4444 in the 512-byte palette RAM) -> 16-colour index per entry"""
    from bbvideo import palette_rgb
    return quantize_rgb(palette_rgb(palram).reshape(1, 256, 3))[0].reshape(256)


def build():
    from PIL import Image
    src = json.load(open(os.path.join(DOCS, "quant", "attract_collage_q16_default.json")))
    out = {"name": "bublbobl 16-colour palette",
           "origin": "JsOklabQuantizer default settings on docs/attract_collage_64.png (MAME 0.162, bublboblr)",
           "quantizer": {"repo": "C:/Arbeit/jsoklabquantizer", "commit": "066f401",
                         "note": "uncommitted js/main.mjs native-size palette path; quantizer.mjs/color.mjs as committed",
                         "options": src["options"]},
           "order": "ascending Oklab lightness (the quantizer's ladder order)",
           "palette": [{k: c[k] for k in ("index", "rgb", "L", "a", "b", "ste444")} for c in src["palette"]],
           "meanDeltaOklab100": src["meanDeltaOklab100"], "maxDeltaOklab100": src["maxDeltaOklab100"],
           "status": "adopted as the working palette; not yet validated against gameplay frames"}
    json.dump(out, open(PALETTE16, "w"), indent=1)

    # verification: our mapping of the source collage == the quantizer's output image, every pixel
    img = np.array(Image.open(os.path.join(DOCS, "attract_collage_64.png")).convert("RGB"))
    ref = np.array(Image.open(os.path.join(DOCS, "quant", "attract_collage_q16_default.png")).convert("RGB"))
    _, got = quantize_rgb(img)
    bad = int((got != ref).any(axis=2).sum())
    print("palette16.json written; pixels differing from the quantizer's own output: %d of %d" % (bad, ref.shape[0] * ref.shape[1]))
    return bad


if __name__ == "__main__":
    sys.path.insert(0, HERE)
    sys.exit(1 if build() else 0)
