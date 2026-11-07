"""src/render.s from src/render_new.s (Dragon Spirit's own parts) and the routines it shares with Galaga '88's
renderer (games/galaga88/src/render.s: the colours, the banks' maps, the sprite cache, its conversion), copied by
label so they stay identical.

    venv/bin/python games/dspirit/tools/make_render.py      (after a change to either source)
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
G = (ROOT / "games/galaga88/src/render.s").read_text().split("\n")


def find(label):
    for i, l in enumerate(G):
        if l.startswith(label + ":"):
            return i
    raise KeyError(label)


def head(i):
    """the line where the comment block (and constant definitions) above line i starts"""
    import re
    while i > 0 and (G[i - 1].startswith(";") or re.match(r"[A-Z_0-9]+\s*=", G[i - 1])):
        i -= 1
    return i


def chunk(a, b):
    """from label a (with its comments) to label b's comments (exclusive)"""
    return G[head(find(a)):head(find(b))]


def between(start_text, end_label):
    i = next(k for k, l in enumerate(G) if l.startswith(start_text))
    return G[i:head(find(end_label))]


parts = [
    ("ren_palette", "ren_quality"),          # the palette's state per picture (a scene, a re-choice)
    ("ren_pen_err", "ren_bg_pen"),
    ("ren_buf_palette", "ren_choose"),       # the buffer's colours, pen -> index, the nearest centre
    ("ren_hist_add", "ren_sample_bg"),
    ("ren_sample_sprites", "ren_bg_check"),  # the sprites' samples, entries, median cut, k-means, representatives
    ("ren_spread", "ren_restore"),           # the spread longs, a bank's map
    ("ren_spr_offsets", "ren_spr_geom"),
]
# Dragon Spirit's changes to copied routines (exact text, once each): the representative pens' colours through
# ren_flash_pen (layer 0 drawn with its held bank while the game shows another: the intro's lightning as a palette
# flash, the user 2026-11-07)
PATCHES = {
    # (no re-choice for colours that fit worse while layer 0 flashes)
    "ren_palette": [("\taddq.l\t#1,ren_ch_rest\n\tbsr\tren_choose",
                     "\tbsr\tren_flashing\n\tbne\t.r\n\taddq.l\t#1,ren_ch_rest\n\tbsr\tren_choose")],
    "ren_buf_palette": [("\tbmi\t.z\t\t\t; (no colour)\n\tbsr\tren_pen_addr",
                         "\tbmi\t.z\t\t\t; (no colour)\n\tbsr\tren_flash_pen\n\tbsr\tren_pen_addr")],
    "ren_pen_err": [("\tbmi\t.blk\n\tbsr\t.lab", "\tbmi\t.blk\n\tbsr\tren_flash_pen\n\tbsr\t.lab"),
                    # (a pen shown: its index the one its pen in the held bank was drawn with)
                    ("\tbsr\tren_pen_index\t\t; d1 = its index",
                     "\tmove.w\td0,-(sp)\n\tbsr\tren_unflash_pen\n\tbsr\tren_pen_index\t\t; d1 = its index\n"
                     "\tmove.w\t(sp)+,d0")],
}
out = (ROOT / "games/dspirit/src/render_new.s").read_text().rstrip("\n").split("\n")
out += ["", "; ======== from games/galaga88/src/render.s (tools/make_render.py) ========", ""]
for a, b in parts:
    c = "\n".join(chunk(a, b))
    for x, y in PATCHES.get(a, ()):
        assert c.count(x) == 1, (a, x)
        c = c.replace(x, y)
    out += c.split("\n")
out += between("; ---- the sprite cache", "ren_spr_image")       # the cache, ren_spr_pen
conv = chunk("ren_convert", "ren_sb2_draw")
while conv and not conv[-1].strip().startswith("ifd"):           # (up to the REN_SB2 prototype)
    conv.pop()
conv.pop()
out += conv
out += (ROOT / "games/dspirit/src/render_data.s").read_text().rstrip("\n").split("\n")
(ROOT / "games/dspirit/src/render.s").write_text("\n".join(out) + "\n")
print("render.s: %d lines" % len(out))
