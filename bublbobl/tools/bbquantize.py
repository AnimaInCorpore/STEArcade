"""Quantize an image to 16 colours with the JsOklabQuantizer strategy and render the results.

usage: python bbquantize.py [in.png] [out_dir]
  default input  docs/attract_collage_64.png     default out_dir  docs/quant

Runs tools/oklab_quantize.mjs (which imports C:\\Arbeit\\jsoklabquantizer's quantizer.mjs/color.mjs
unmodified) twice on the native-size image: the tool's default settings (fatnessBias 0.75, colorDecay 0)
and colorDecay 1 (every distinct colour counts once per cluster, so rare colours are not out-voted by
the black background).  Writes, per variant: <name>.png (quantized image), <name>.json (palette, per-colour
mapping, error), and one combined sheet with source / both results / palette swatches.
"""
import json
import os
import subprocess
import sys
import tempfile

import numpy as np
from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
DOCS = os.path.join(HERE, "..", "docs")
VARIANTS = (("default", 0.75, 0.0), ("decay1", 0.75, 1.0))


def ste12(rgb):
    """nearest 4-bit-per-channel (STE) value as $0RGB, for reference only"""
    r, g, b = (int(round(int(rgb[i:i + 2], 16) / 17)) for i in (1, 3, 5))
    return "$%X%X%X" % (r, g, b)


def run(src, out_dir):
    img = np.array(Image.open(src).convert("RGB"))
    H, W = img.shape[:2]
    os.makedirs(out_dir, exist_ok=True)
    tmp = tempfile.mkdtemp()
    raw = os.path.join(tmp, "in.rgb")
    img.tofile(raw)
    results = {}
    for name, fat, decay in VARIANTS:
        prefix = os.path.join(tmp, name)
        r = subprocess.run(["node", "--max-old-space-size=8192", os.path.join(HERE, "oklab_quantize.mjs"),
                            raw, str(W), str(H), prefix, str(fat), str(decay)],
                           capture_output=True, text=True)
        if r.returncode:
            raise SystemExit(r.stderr)
        print(name, "->", r.stdout.strip())
        meta = json.load(open(prefix + ".json"))
        idx = np.fromfile(prefix + ".idx", np.uint8).reshape(H, W)
        pal = np.array([[int(c["rgb"][i:i + 2], 16) for i in (1, 3, 5)] for c in meta["palette"]], np.uint8)
        q = pal[idx]
        Image.fromarray(q).save(os.path.join(out_dir, "attract_collage_q16_%s.png" % name))
        for p in meta["palette"]:
            p["ste444"] = ste12(p["rgb"])
        # which of the source colours end up unchanged / how many palette slots are used
        meta["paletteSlotsUsed"] = int(len(np.unique(idx)))
        meta["sourceImage"] = os.path.basename(src)
        json.dump(meta, open(os.path.join(out_dir, "attract_collage_q16_%s.json" % name), "w"), indent=1)
        results[name] = (q, pal, meta)
    return img, results


def sheet(img, results, out_dir):
    H, W = img.shape[:2]
    sw = 64
    names = [n for n, _, _ in VARIANTS]
    canvas = Image.new("RGB", (W, 3 * (H + 40 + sw) + 20), (24, 24, 24))
    d = ImageDraw.Draw(canvas)
    panels = [("source (%d distinct colours)" % results[names[0]][2]["sourceColours"], img, None)]
    for n in names:
        q, pal, meta = results[n]
        panels.append(("%s: fatnessBias %.2f, colorDecay %.0f  |  mean dOklab x100 %.2f, max %.1f" %
                       (n, meta["options"]["fatnessBias"], meta["options"]["colorDecay"],
                        meta["meanDeltaOklab100"], meta["maxDeltaOklab100"]), q, pal))
    y = 0
    for title, im, pal in panels:
        d.text((8, y + 6), title, fill=(255, 255, 255))
        canvas.paste(Image.fromarray(im), (0, y + 30))
        y += H + 40
        if pal is not None:
            for i, c in enumerate(pal):
                d.rectangle([i * (W // 16), y - 8, (i + 1) * (W // 16) - 2, y - 8 + sw], fill=tuple(int(v) for v in c))
        y += sw if pal is not None else 0
    canvas = canvas.crop((0, 0, W, y + 8))
    canvas.save(os.path.join(out_dir, "attract_collage_q16_compare.png"))


if __name__ == "__main__":
    src = sys.argv[1] if len(sys.argv) > 1 else os.path.join(DOCS, "attract_collage_64.png")
    out = sys.argv[2] if len(sys.argv) > 2 else os.path.join(DOCS, "quant")
    img, res = run(src, out)
    sheet(img, res, out)
