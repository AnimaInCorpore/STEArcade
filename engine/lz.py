"""A byte-aligned LZ77 for data the 68000 unpacks (engine/rt/lz.s lz_unpack is this decode in 68000 code).

A stream of tokens:
    $00-$7F n, n + 1 bytes      a literal run of n + 1 bytes
    $80-$FE, hi, lo             a match: (c & $7F) + 3 bytes (3-129) from offset hi:lo + 1 bytes back (1-65536)
    $FF                         the end

    compress(data) -> bytes, decompress(bytes) -> bytes
"""

MIN, MAX = 3, 129
WINDOW = 65536


def compress(data, chain=256):
    data = bytes(data)
    n = len(data)
    out = bytearray()
    lit = bytearray()
    heads = {}
    prev = [-1] * n

    def flush():
        while lit:
            k = min(len(lit), 128)
            out.append(k - 1)
            out.extend(lit[:k])
            del lit[:k]

    def insert(i):
        if i + 3 <= n:
            key = data[i:i + 3]
            prev[i] = heads.get(key, -1)
            heads[key] = i

    i = 0
    while i < n:
        best_len, best_off = 0, 0
        if i + MIN <= n:
            j = heads.get(data[i:i + 3], -1)
            tries = chain
            while j >= 0 and i - j <= WINDOW and tries:
                l = 0
                m = min(MAX, n - i)
                while l < m and data[j + l] == data[i + l]:
                    l += 1
                if l > best_len:
                    best_len, best_off = l, i - j
                    if l == m:
                        break
                j = prev[j]
                tries -= 1
        if best_len >= MIN:
            flush()
            out += bytes([0x80 | (best_len - MIN), (best_off - 1) >> 8, (best_off - 1) & 255])
            for k in range(best_len):
                insert(i + k)
            i += best_len
        else:
            lit.append(data[i])
            insert(i)
            i += 1
    flush()
    out.append(0xFF)
    return bytes(out)


def decompress(src):
    out = bytearray()
    p = 0
    while True:
        c = src[p]
        p += 1
        if c == 0xFF:
            return bytes(out)
        if c < 0x80:
            out += src[p:p + c + 1]
            p += c + 1
        else:
            off = (src[p] << 8 | src[p + 1]) + 1
            p += 2
            for _ in range((c & 0x7F) + MIN):
                out.append(out[-off])


if __name__ == "__main__":
    import os
    import random
    rnd = random.Random(1)
    for t in range(200):
        d = bytes(rnd.choice(b"abcab\x00\xff") for _ in range(rnd.randrange(0, 3000)))
        assert decompress(compress(d)) == d
    print("ok")
