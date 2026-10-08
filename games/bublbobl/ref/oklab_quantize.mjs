// Apply the JsOklabQuantizer strategy (C:\Arbeit\jsoklabquantizer) to a raw RGB image, unmodified.
//
// usage: node oklab_quantize.mjs <in.rgb> <width> <height> <out-prefix> [fatnessBias=0.75] [colorDecay=0] [count=16]
//
// Uses that repo's own js/quantizer.mjs + js/color.mjs (override the location with QUANTIZER_DIR) and
// follows js/main.mjs exactly: pixels -> Oklab with a packed-RGB `key`, one palette from *all* pixels at
// native size (the "original" summed-palette path: no crop/resize), iterations 18, lightnessMode "image",
// then every pixel -> nearest palette entry in Oklab (renderQuantizedImage).
// Writes <prefix>.json (palette, per-source-colour mapping, error) and <prefix>.idx (1 byte/pixel).
import { readFileSync, writeFileSync } from "node:fs";
import { pathToFileURL } from "node:url";
import { join } from "node:path";

const dir = process.env.QUANTIZER_DIR || "C:/Arbeit/jsoklabquantizer";
const { buildConstrainedOklabPalette, findNearestPaletteIndex } =
  await import(pathToFileURL(join(dir, "js", "quantizer.mjs")).href);
const { oklabToRgb8, rgb8ToOklab } = await import(pathToFileURL(join(dir, "js", "color.mjs")).href);

const [inFile, w, h, prefix, fat = "0.75", decay = "0", count = "16"] = process.argv.slice(2);
const W = Number(w), H = Number(h), COUNT = Number(count);
const data = readFileSync(inFile);
if (data.length !== W * H * 3) throw new Error(`expected ${W * H * 3} bytes, got ${data.length}`);

// extractLabs() from js/main.mjs (RGB source, alpha always opaque here)
const pixels = new Array(W * H);
for (let p = 0; p < W * H; p++) {
  const r = data[p * 3], g = data[p * 3 + 1], b = data[p * 3 + 2];
  const lab = rgb8ToOklab(r, g, b);
  pixels[p] = { L: lab.L, a: lab.a, b: lab.b, alpha: 255, key: (r << 16) | (g << 8) | b };
}

const options = { iterations: 18, lightnessMode: "image", fatnessBias: Number(fat), colorDecay: Number(decay) };
const palette = buildConstrainedOklabPalette(pixels, COUNT, options);
const paletteRgb = palette.map(c => oklabToRgb8(c.L, c.a, c.b));

// nearest palette index per distinct source colour (identical result to per-pixel lookup)
const byKey = new Map();
for (const px of pixels) {
  let e = byKey.get(px.key);
  if (!e) {
    const idx = findNearestPaletteIndex(px, palette);
    const c = palette[idx];
    const dist = Math.hypot(px.L - c.L, px.a - c.a, px.b - c.b);
    e = { key: px.key, px, idx, dist, count: 0 };
    byKey.set(px.key, e);
  }
  e.count++;
}
const idxOut = Buffer.alloc(W * H);
for (let p = 0; p < W * H; p++) idxOut[p] = byKey.get(pixels[p].key).idx;

let errSum = 0, errMax = 0;
for (const e of byKey.values()) {
  errSum += e.dist * e.count;
  errMax = Math.max(errMax, e.dist);
}
const hex = c => "#" + [c.r, c.g, c.b].map(v => v.toString(16).padStart(2, "0")).join("");
const colours = [...byKey.values()].sort((a, b) => b.count - a.count).map(e => ({
  rgb: hex({ r: e.key >> 16, g: (e.key >> 8) & 255, b: e.key & 255 }),
  pixels: e.count,
  paletteIndex: e.idx,
  deltaOklab100: +(e.dist * 100).toFixed(2)
}));

writeFileSync(prefix + ".idx", idxOut);
writeFileSync(prefix + ".json", JSON.stringify({
  strategy: "JsOklabQuantizer buildConstrainedOklabPalette (native-size summed palette)",
  options, count: COUNT, width: W, height: H,
  palette: palette.map((c, i) => ({ index: i, L: +c.L.toFixed(8), a: +c.a.toFixed(8), b: +c.b.toFixed(8), rgb: hex(paletteRgb[i]) })),
  sourceColours: byKey.size,
  meanDeltaOklab100: +(errSum / (W * H) * 100).toFixed(3),
  maxDeltaOklab100: +(errMax * 100).toFixed(2),
  colours
}, null, 1));
console.log(`palette ${palette.length} colours from ${byKey.size} source colours; mean dOklab x100 = ${(errSum / (W * H) * 100).toFixed(3)}, max = ${(errMax * 100).toFixed(2)}`);
