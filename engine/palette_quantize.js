// Shared build-time STE palette fitting and checker quantization.
// Adapted from stefastbobs2 demos/alien/make_alien.js and demos/zombies/make_zombies.js.
// Original normalized colour-algorithm SHA256: e469f9d6da5398c44528b0e01f2444be08d67dfd0f33592079be71c84e02edbf
// Keep the original OKLab metric, 40 deterministic starts, STE snapping and
// constrained linear-RGB checker refinement. Callers supply their weighted histogram.
const fs = require("fs");
const job = JSON.parse(fs.readFileSync(0, "utf8"));
const colorWeights = new Map(job.hist);
const COLOR_COUNT = job.color_count;
function argumentValue(name, fallback) {
    return ({"dither-l": job.dither_l, "dither-ab": job.dither_ab, "hue-weight": job.hue_weight})[name] ?? fallback;
}
function srgbToLinear(value) {
    value /= 255;

    return value > 0.04045 ? Math.pow((value + 0.055) / 1.055, 2.4) : value / 12.92;
}

function linearToOklab(rgb) {
    const [ r, g, b ] = rgb;

    const l = Math.cbrt(0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b);
    const m = Math.cbrt(0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b);
    const s = Math.cbrt(0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b);

    return [
        0.2104542553 * l + 0.7936177850 * m - 0.0040720468 * s,
        1.9779984951 * l - 2.4285922050 * m + 0.4505937099 * s,
        0.0259040371 * l + 0.7827717662 * m - 0.8086757660 * s
    ];
}

function rgb2oklab(rgb) {
    return linearToOklab(rgb.map(srgbToLinear));
}

// Squared distance with the lightness first: a small hue or chroma difference (a, b) counts less
// than a lightness difference, so the palette keeps the shading (--hue-weight=<factor>, default 0.75, 1 = OKLab).

const HUE_WEIGHT = Number(argumentValue("hue-weight", 0.75));

function oklabDistance(a, b) {
    return Math.pow(a[0] - b[0], 2) + Math.pow((a[1] - b[1]) * HUE_WEIGHT, 2) + Math.pow((a[2] - b[2]) * HUE_WEIGHT, 2);
}

// The STE has 4 bits per color component.

function steLevel(value) {
    return Math.round(value / 17);
}

function steColor(rgb) {
    return rgb.map(value => steLevel(value) * 17);
}

function steWord(rgb) {
    const [ r, g, b ] = rgb.map(steLevel);
    const nibble = level => ((level & 1) << 3) | (level >> 1);

    return (nibble(r) << 8) | (nibble(g) << 4) | nibble(b);
}

// ------------------------------------------------------------------------------
const colors = [ ...colorWeights.entries() ].map(([ key, weight ]) => {
    const rgb = key.split(",").map(Number);

    return { rgb, lab: rgb2oklab(rgb), weight };
});

const FIT_COUNT = Math.min(COLOR_COUNT, new Set(["0,0,0", ...colors.map(c => steColor(c.rgb).join(","))]).size);

const steColors = [];

for(let r = 0; r < 16; r++) {
    for(let g = 0; g < 16; g++) {
        for(let b = 0; b < 16; b++) {
            const rgb = [ r * 17, g * 17, b * 17 ];

            steColors.push({ rgb, lab: rgb2oklab(rgb) });
        }
    }
}

function nearestSteColor(lab) {
    let best = null;
    let bestDistance = Infinity;

    for(const steColorEntry of steColors) {
        const distance = oklabDistance(lab, steColorEntry.lab);

        if(distance < bestDistance) {
            best = steColorEntry;
            bestDistance = distance;
        }
    }

    return best;
}

function createPalette(seed) {
    let state = seed;
    const random = () => { state = (state * 1664525 + 1013904223) >>> 0; return state / 4294967296; };

    const centers = [ { rgb: [ 0, 0, 0 ], lab: rgb2oklab([ 0, 0, 0 ]), fixed: true } ];

    // k-means++ initialization.

    while(centers.length < FIT_COUNT) {
        const distances = colors.map(color => Math.min(...centers.map(center => oklabDistance(color.lab, center.lab))) * color.weight);
        let pick = random() * distances.reduce((a, b) => a + b, 0);
        let index = 0;

        while(index < colors.length - 1 && pick > distances[index]) {
            pick -= distances[index];
            index++;
        }

        centers.push({ rgb: colors[index].rgb, lab: colors[index].lab, fixed: false });
    }

    for(let iteration = 0; iteration < 40; iteration++) {
        const sums = centers.map(() => ({ weight: 0, l: 0, a: 0, b: 0 }));

        for(const color of colors) {
            let best = 0;
            let bestDistance = Infinity;

            centers.forEach((center, index) => {
                const distance = oklabDistance(color.lab, center.lab);

                if(distance < bestDistance) {
                    best = index;
                    bestDistance = distance;
                }
            });

            sums[best].weight += color.weight;
            sums[best].l += color.lab[0] * color.weight;
            sums[best].a += color.lab[1] * color.weight;
            sums[best].b += color.lab[2] * color.weight;
        }

        // Move the centers to the mean of their cluster, snapped to the nearest STE color.

        let moved = false;

        centers.forEach((center, index) => {
            if(center.fixed || !sums[index].weight) {
                return;
            }

            const nearest = nearestSteColor([ sums[index].l / sums[index].weight, sums[index].a / sums[index].weight, sums[index].b / sums[index].weight ]);

            if(nearest.rgb.join() != center.rgb.join()) {
                moved = true;
            }

            center.rgb = nearest.rgb;
            center.lab = nearest.lab;
        });

        if(!moved) {
            break;
        }
    }

    // Total weighted error.

    let error = 0;

    for(const color of colors) {
        error += Math.min(...centers.map(center => oklabDistance(color.lab, center.lab))) * color.weight;
    }

    const unique = new Set(centers.map(center => center.rgb.join(","))).size;

    return { centers, error: unique == FIT_COUNT ? error : Infinity };
}

let bestPalette = null;

for(let seed = 1; seed <= 40; seed++) {
    const candidate = createPalette(seed);

    if(!bestPalette || candidate.error < bestPalette.error) {
        bestPalette = candidate;
    }
}

// ------------------------------------------------------------------------------
// Checker dithering: a pixel gets the nearest palette color or a checker pattern of two palette
// colors, which the eye mixes (the mix is the mean in linear RGB). Only pairs with a small
// lightness difference (OKLab L) and a similar hue (OKLab a/b) are used, so the pattern stays calm
// and does not sprinkle other colors. A pattern is used only if it is clearly better than the
// nearest single color.
//
// --dither-l=<distance>, --dither-ab=<distance>: the limits (--dither-l=0: no dithering)
// ------------------------------------------------------------------------------

const DITHER_MAX_L = Number(argumentValue("dither-l", 0.12)); // Maximum OKLab L difference of the two colors
const DITHER_MAX_AB = Number(argumentValue("dither-ab", 0.08)); // Maximum OKLab a/b distance of the two colors
const DITHER_GAIN = 0.012; // Minimum improvement (OKLab distance) for using a pattern

// The checker pairs of a palette (labs: the OKLab colors of the palette).

function ditherPairsOf(rgbs, labs) {
    const pairs = [];

    for(let first = 0; first < rgbs.length; first++) {
        for(let second = first + 1; second < rgbs.length; second++) {
            const lightness = Math.abs(labs[first][0] - labs[second][0]);
            const hue = Math.hypot(labs[first][1] - labs[second][1], labs[first][2] - labs[second][2]);

            if(lightness <= DITHER_MAX_L && hue <= DITHER_MAX_AB) {
                const linearFirst = rgbs[first].map(srgbToLinear);
                const linearSecond = rgbs[second].map(srgbToLinear);

                pairs.push({ first, second, lab: linearToOklab(linearFirst.map((value, index) => (value + linearSecond[index]) / 2)) });
            }
        }
    }

    return pairs;
}

// The weighted squared error of the sprite colors with a palette, with the patterns. Squared like
// k-means: a few colors far off (a lost hue) count more than many colors a bit off.

function ditheredError(rgbs, labs) {
    const pairs = ditherPairsOf(rgbs, labs);
    let error = 0;

    for(const color of colors) {
        let best = Infinity;

        for(const lab of labs) {
            best = Math.min(best, oklabDistance(color.lab, lab));
        }

        for(const pair of pairs) {
            best = Math.min(best, Math.pow(Math.sqrt(oklabDistance(color.lab, pair.lab)) + DITHER_GAIN, 2));
        }

        error += best * color.weight;
    }

    return error;
}

// Refine the k-means palette for the patterns: every color (not black) is replaced by the STE
// color which makes the error smallest, until no replacement helps. So the palette can leave out
// shades that a pattern of two neighbors makes.

const refinedRgbs = bestPalette.centers.map(center => center.rgb);
const refinedLabs = refinedRgbs.map(rgb2oklab);

if(DITHER_MAX_L > 0) {
    let error = ditheredError(refinedRgbs, refinedLabs);

    for(let round = 0, improved = true; improved && round < 8; round++) {
        improved = false;

        for(let index = 1; index < refinedRgbs.length; index++) {
            const used = new Set(refinedRgbs.map(rgb => rgb.join(",")));
            const original = { rgb: refinedRgbs[index], lab: refinedLabs[index] };
            let best = original;

            for(const candidate of steColors) {
                if(used.has(candidate.rgb.join(","))) {
                    continue;
                }

                refinedRgbs[index] = candidate.rgb;
                refinedLabs[index] = candidate.lab;

                const candidateError = ditheredError(refinedRgbs, refinedLabs);

                if(candidateError < error - 1e-9) {
                    error = candidateError;
                    best = candidate;
                    improved = true;
                }
            }

            refinedRgbs[index] = best.rgb;
            refinedLabs[index] = best.lab;
        }
    }
}

// Sort by lightness, black stays first.

const palette = [ ...refinedRgbs ].sort((a, b) => (a.join() == "0,0,0" ? -1 : b.join() == "0,0,0" ? 1 : rgb2oklab(a)[0] - rgb2oklab(b)[0]));
const paletteLabs = palette.map(rgb2oklab);
const ditherPairs = ditherPairsOf(palette, paletteLabs);

const quantizeCache = new Map();

// The choice for a color: { first, second, error } (first == second: no pattern).

function quantizeColor(rgb) {
    const key = rgb.join(",");

    if(quantizeCache.has(key)) {
        return quantizeCache.get(key);
    }

    const lab = rgb2oklab(rgb);
    let choice = { first: 0, second: 0, error: Infinity };

    paletteLabs.forEach((paletteLab, index) => {
        const distance = Math.sqrt(oklabDistance(lab, paletteLab));

        if(distance < choice.error) {
            choice = { first: index, second: index, error: distance };
        }
    });

    for(const pair of ditherPairs) {
        const distance = Math.sqrt(oklabDistance(lab, pair.lab));

        if(distance + DITHER_GAIN < choice.error) {
            choice = { first: pair.first, second: pair.second, error: distance };
        }
    }

    quantizeCache.set(key, choice);

    return choice;
}

function quantize(frame) {
    const pixels = Buffer.from(frame.pixels);
    let error = 0;
    let squared = 0;
    let count = 0;
    let dithered = 0;

    for(let y = 0; y < frame.height; y++) {
        for(let x = 0; x < frame.width; x++) {
            const index = y * frame.width + x;

            if(pixels[index * 4 + 3]) {
                const choice = quantizeColor([ pixels[index * 4], pixels[index * 4 + 1], pixels[index * 4 + 2] ]);

                pixels.set(palette[(x + y) & 1 ? choice.second : choice.first], index * 4);

                error += choice.error;
                squared += choice.error * choice.error;
                count++;
                dithered += choice.first != choice.second ? 1 : 0;
            }
        }
    }

    return { width: frame.width, height: frame.height, pixels, error, squared, count, dithered };
}


process.stdout.write(JSON.stringify({palette, choices:job.input_colors.map(quantizeColor)}));
