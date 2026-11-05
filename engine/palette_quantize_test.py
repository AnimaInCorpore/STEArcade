"""Shared fitter contracts: fixed colours, checker choices and sparse inputs."""
import collections
import tempfile

import numpy as np

import palette_quantize as pq


def main():
    # Only three slots: the two nearby grey anchors must remain exact, and the
    # original mid-grey must be represented by their linear-light checker mix.
    anchors = [[102, 102, 102], [119, 119, 119]]
    hist = [collections.Counter({(111, 111, 111):1000}), collections.Counter()]
    inputs = [[0, 0, 0], *anchors, [111, 111, 111]]
    with tempfile.TemporaryDirectory() as cache:
        pal, pairs = pq.fit(hist, inputs, count=3, fixed=anchors, cache=cache)
        again = pq.fit(hist, inputs, count=3, fixed=anchors, cache=cache)
        assert all(np.array_equal(a, b) for a, b in zip((pal, pairs), again))
        assert not pal[0].any() and pairs[0] == 0
        assert np.array_equal(pal[pq.indices(pairs[1:3], 0)], anchors)
        assert np.array_equal(pal[pq.indices(pairs[1:3], 1)], anchors)
        assert (pairs[-1] >> 4) != (pairs[-1] & 15)
        flat, mapping = pq.fit(hist, inputs, count=3, fixed=anchors, dither=False)
        assert np.array_equal(flat, pal) and np.all((mapping >> 4) == (mapping & 15))
    text = pq.flat_map(pal, [[111, 111, 111]])
    assert text.shape == (1,) and text[0] in (1, 2)
    pal, pairs = pq.fit([collections.Counter(), collections.Counter()], [[0, 0, 0]], count=16)
    assert pal.shape == (16, 3) and not pal.any() and pairs.tolist() == [0]
    print('PASS: fixed anchors, constrained checker, flat text mapping, cache replay, empty histogram')


if __name__ == '__main__':
    main()
