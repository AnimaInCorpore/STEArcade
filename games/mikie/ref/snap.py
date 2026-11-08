"""Snapshot / restore of a machine.MikiePort (its state is plain ints, lists and the RAM: no closures)."""
import copy


def snapshot(m):
    s = {}
    for o, name in ((m, 'm'), (m.cpu, 'c')):
        for k, v in vars(o).items():
            if k in ('cpu', 'rom', 'video') or callable(v):
                continue
            s[name, k] = copy.copy(v)
    return s


def restore(m, s):
    for (name, k), v in s.items():
        setattr(m if name == 'm' else m.cpu, k, copy.copy(v))
