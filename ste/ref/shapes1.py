import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'tools'))
from dkong import Gfx
import numpy as np
g = Gfx()
tot_words = 0; tot_lines = 0; empty = 0; shapes = {}
for code in range(128):
    for fx in (0,1):
        for fy in (0,1):
            s = g.sprites[code]
            if fx: s = s[:, ::-1]
            if fy: s = s[::-1, :]
            D = s.T[:, ::-1]               # display bitmap [v][u]
            lines = []
            for v in range(16):
                row = D[v] != 0
                u = 0
                while u < 16:
                    if row[u]:
                        u0 = u
                        while u < 16 and row[u]: u += 1
                        lines.append((v, u0, u - u0))
                    else:
                        u += 1
            if not lines: empty += 1; continue
            words = sum(4 * ((w + 15) // 16) for _, _, w in lines)
            key = tuple((x0, w) for v, x0, w in lines)
            shapes[(code, fx, fy)] = (len(lines), words)
            tot_words += words; tot_lines += len(lines)
print('nonempty shapes', len(shapes), 'empty', empty, 'avg lines', tot_lines / len(shapes), 'words per shape', tot_words / len(shapes))
print('stream bytes for all shapes x 19 triples:', tot_words * 2 * 19)
print('routine lines total', tot_lines, ' x16 shifts, ~14 bytes/line =', tot_lines * 16 * 14)
