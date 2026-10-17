"""The 68010 as MAME 0.289 runs it: MAME's own Musashi core (src/devices/cpu/m68000: m68kmusashi.h, m68kcpu.h,
m68kmmu.h, m68kcpu.cpp, m68k_in.lst -> m68kops.cpp by m68kmake.py; BSD-3-Clause, copyright-holders Karl Stenerud),
compiled outside MAME into build/m68kmame/libm68kmame.dylib and driven through ctypes, for boards that must follow
MAME instruction for instruction (games/gauntlet/tools/machine.py).

The build takes the core's sources from MAME 0.289's tree (MAME_SRC, default build/mame0289/src: `fetch()` downloads
the seven files from github.com/mamedev/mame, tag mame0289; the copy vendored in F030Arcade is 0.286 with local
changes, and its 68010 differs, e.g. 0.289 counts no per-bit shift cycles below the 68030):
m68kmake.py generates m68kops.h / m68kops.cpp, and the functions of m68kcpu.cpp a 68010 needs (the tables, the
opcode table builder, execute_run, device_reset, init_cpu_common / init_cpu_m68010, init16, the interrupt lines and
exception) are copied out unchanged; engine/m68kmame/emu.h stands in for MAME's framework and glue.cpp is the C
interface (memory pages, callbacks, the instruction hook).  It rebuilds when a source is newer than the library.

    cpu = M68010(read, write)              read(addr, mask, kind) -> u16; write(addr, data, mask): CALLBACK pages
    cpu.map(start, end, mode, base=None)   pages of 4 KB: RAM, ROM, UNMAPPED, CALLBACK (base: mirror of that address)
    cpu.mem                                the 16 MB of bytes (numpy uint8, big-endian words), shared with the core
    cpu.reset(); n = cpu.run(cycles)       MAME's device_reset / execute_run (n may overshoot: whole instructions)
    cpu.executed()                         cycles of the running slice so far, as MAME's machine time sees them
    cpu.abort()                            MAME's abort_timeslice: icount -> 0 (run returns after the instruction)
    cpu.set_input(line, state)             execute_set_input: M68K_IRQ_1..7 (MAME's interrupt mixer)
    cpu.pc, cpu.sr, cpu.d(i), cpu.a(i)     registers; cpu.hook(pc, fn): fn(pc) before the instruction at pc
"""
import ctypes
import os
import re
import subprocess
import sys
from pathlib import Path

import numpy as np

from paths import ENGINE, ROOT

MAME_SRC = Path(os.environ.get("MAME_SRC") or ROOT / "build" / "mame0289" / "src")
CORE_FILES = ("m68k_in.lst", "m68kcpu.cpp", "m68kcpu.h", "m68kmusashi.h", "m68kmmu.h", "m68kcommon.h", "m68kmake.py")
CORE = MAME_SRC / "devices" / "cpu" / "m68000"
GLUE = ENGINE / "m68kmame"
OUT = ROOT / "build" / "m68kmame"
LIB = OUT / "libm68kmame.dylib"

RAM, ROM, UNMAPPED, CALLBACK = range(4)

# the functions of m68kcpu.cpp a 68010 needs (the rest is device plumbing, other CPU types, the PMMU/HMMU memory paths)
FUNCTIONS = ["set_irq_line", "m68k_cause_bus_error", "execute_run", "init_cpu_common", "device_reset", "init16",
             "init_cpu_m68010", "m68ki_exception_interrupt", "clear_all", "execute_set_input", "m68ki_set_one",
             "m68ki_build_opcode_table", "supervisor_mode", "get_fc"]


def _extract():
    """m68kcpu.cpp's tables (everything up to the first function) and FUNCTIONS, unchanged."""
    lines = (CORE / "m68kcpu.cpp").read_text().splitlines()
    start = next(i for i, l in enumerate(lines) if l.startswith("u16 m68000_musashi_device::m68ki_instruction_state"))
    first = next(i for i, l in enumerate(lines) if re.match(r"^\S.*m68000_musashi_device::set_irq_line\(", l))
    out = ['#include "emu.h"', '#include "m68kmusashi.h"', ""] + lines[start:first]
    for name in FUNCTIONS:
        i = next(k for k, l in enumerate(lines) if re.match(r"^\S.*m68000_musashi_device::%s\(" % name, l))
        j = next(k for k in range(i, len(lines)) if lines[k] == "}")
        out += lines[i:j + 1] + [""]
    return "\n".join(out) + "\n"


def fetch():
    """MAME 0.289's 68000 core sources into MAME_SRC (only those build() reads)"""
    import urllib.request
    CORE.mkdir(parents=True, exist_ok=True)
    for n in CORE_FILES:
        if not (CORE / n).exists():
            url = "https://raw.githubusercontent.com/mamedev/mame/mame0289/src/devices/cpu/m68000/" + n
            (CORE / n).write_bytes(urllib.request.urlopen(url).read())


def build(force=False):
    if not all((CORE / n).exists() for n in CORE_FILES):
        fetch()
    srcs = [CORE / n for n in CORE_FILES] + [GLUE / "glue.cpp", GLUE / "emu.h", Path(__file__)]
    if not force and LIB.exists() and all(LIB.stat().st_mtime >= s.stat().st_mtime for s in srcs):
        return LIB
    OUT.mkdir(parents=True, exist_ok=True)
    subprocess.run([sys.executable, str(CORE / "m68kmake.py"), str(CORE / "m68k_in.lst"), str(OUT / "m68kops.h"),
                    str(OUT / "m68kops.cpp")], check=True)
    (OUT / "m68kcpu_part.cpp").write_text(_extract())
    for n in ("m68kmusashi.h", "m68kcpu.h", "m68kmmu.h", "m68kcommon.h"):
        (OUT / n).write_text((CORE / n).read_text())
    cmd = [os.environ.get("CXX", "c++"), "-std=c++17", "-O2", "-shared", "-fPIC", "-w", "-I", str(OUT), "-I", str(GLUE),
           "-o", str(LIB), str(GLUE / "glue.cpp"), str(OUT / "m68kcpu_part.cpp"), str(OUT / "m68kops.cpp")]
    subprocess.run(cmd, check=True)
    return LIB


READ = ctypes.CFUNCTYPE(ctypes.c_uint16, ctypes.c_uint32, ctypes.c_uint16, ctypes.c_int)
WRITE = ctypes.CFUNCTYPE(None, ctypes.c_uint32, ctypes.c_uint16, ctypes.c_uint16)
LINE = ctypes.CFUNCTYPE(None, ctypes.c_int)
HOOK = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_uint32)

_lib = None
U32P = ctypes.POINTER(ctypes.c_uint32)


def _load():
    global _lib
    if _lib is None:
        lib = ctypes.CDLL(str(build()))
        for name, res, args in [("m68k_memory", ctypes.POINTER(ctypes.c_uint8), []),
                                ("m68k_modes", ctypes.POINTER(ctypes.c_uint8), []),
                                ("m68k_bases", ctypes.POINTER(ctypes.c_uint32), []),
                                ("m68k_hookmap", ctypes.POINTER(ctypes.c_uint8), []),
                                ("m68k_callbacks", None, [READ, WRITE, LINE, LINE, HOOK]),
                                ("m68k_hooks_on", None, [ctypes.c_int]),
                                ("m68k_slapstic", None, [U32P, U32P, ctypes.c_int, U32P, ctypes.c_int, U32P, ctypes.c_int]),
                                ("m68k_slapstic_state", ctypes.c_int, []),
                                ("m68k_coverage", None, [U32P, ctypes.POINTER(ctypes.c_uint8)]),
                                ("m68k_create", None, []), ("m68k_reset", None, []),
                                ("m68k_run", ctypes.c_int, [ctypes.c_int]), ("m68k_icount", ctypes.c_int, []),
                                ("m68k_set_icount", None, [ctypes.c_int]),
                                ("m68k_set_input", None, [ctypes.c_int, ctypes.c_int]),
                                ("m68k_get", ctypes.c_uint32, [ctypes.c_int]),
                                ("m68k_set", None, [ctypes.c_int, ctypes.c_uint32]),
                                ("m68k_trace", None, [ctypes.c_int]),
                                ("m68k_trace_buf", ctypes.POINTER(ctypes.c_uint32), []),
                                ("m68k_trace_len", ctypes.c_int, []), ("m68k_trace_clear", None, [])]:
            f = getattr(lib, name)
            f.restype = res
            f.argtypes = args
        _lib = lib
    return _lib


PC, SR, USP, ISP, PPC, IR, STOPPED, IPL = 16, 17, 18, 19, 20, 21, 22, 23


class M68010:
    """One per process (the core's state is global in the library)."""

    def __init__(self, read, write, reset_out=None, irq_ack=None):
        lib = self.lib = _load()
        lib.m68k_create()
        self.mem = np.ctypeslib.as_array(lib.m68k_memory(), shape=(1 << 24,))
        self.mem[:] = 0
        self.modes = np.ctypeslib.as_array(lib.m68k_modes(), shape=(4096,))
        self.bases = np.ctypeslib.as_array(lib.m68k_bases(), shape=(4096,))
        self.hookmap = np.ctypeslib.as_array(lib.m68k_hookmap(), shape=(1 << 21,))
        self.hookmap[:] = 0
        self.hooks = {}
        self._cb = [READ(read), WRITE(write), LINE(reset_out or (lambda s: None)), LINE(irq_ack or (lambda l: None)),
                    HOOK(self._hook)]
        lib.m68k_callbacks(*self._cb)
        lib.m68k_hooks_on(0)
        self.total = 0                      # cycles of finished runs
        self.n = 0                          # the running slice's budget
        self.stolen = 0

    def map(self, start, end, mode, base=None):
        """pages start..end (inclusive, 4 KB aligned) as mode; base: they show the bytes from base on (a mirror)"""
        for p in range(start >> 12, (end >> 12) + 1):
            self.modes[p] = mode
            self.bases[p] = ((base if base is not None else start) + ((p << 12) - start)) & 0xFFF000

    def phys(self, a):
        """the byte offset in mem of arcade address a"""
        return int(self.bases[(a & 0xFFFFFF) >> 12]) + (a & 0xFFF)

    def reset(self):
        self.lib.m68k_reset()

    def run(self, n):
        """MAME's execute_run for n cycles: returns the cycles it ran (MAME's `ran`: the budget minus what is left minus
        what abort() stole)"""
        self.n = n
        self.stolen = 0
        done = self.lib.m68k_run(n) - self.stolen
        self.total += done
        self.n = 0
        return done

    def executed(self):
        """cycles into the running slice at the current access (MAME's time: the instruction's cycles come off icount
        after it)"""
        return self.n - self.stolen - self.lib.m68k_icount()

    def abort(self):
        icount = self.lib.m68k_icount()
        if icount > 0:
            self.stolen += icount
            self.lib.m68k_set_icount(0)

    def slapstic(self, tests, shift, pages, bankbase, start):
        """the slapstic in the core: tests = [(mask, value)] in glue.cpp's SL_* order"""
        arr = lambda xs: (ctypes.c_uint32 * len(xs))(*xs)
        self.lib.m68k_slapstic(arr([m for m, v in tests]), arr([v for m, v in tests]), shift, arr(pages), len(pages),
                               arr(bankbase), start)

    def coverage(self, regions):
        """start recording, per instruction address < $80000, the regions (regions[page] = 0-15) its data accesses
        touch: returns the numpy array (bit r read, bit 16 + r write), filled while the CPU runs"""
        self.cov = np.zeros(0x40000, np.uint32)
        self.regions = np.ascontiguousarray(regions, np.uint8)
        self.lib.m68k_coverage(self.cov.ctypes.data_as(U32P), self.regions.ctypes.data_as(ctypes.POINTER(ctypes.c_uint8)))
        return self.cov

    def slapstic_state(self):
        s = self.lib.m68k_slapstic_state()
        return s & 0xFF, (s >> 8) & 0xFF, (s >> 16) & 0xFF      # state, bank, loaded bank

    def set_input(self, line, state):
        self.lib.m68k_set_input(line, 1 if state else 0)

    def hook(self, pc, fn):
        self.hooks[pc] = fn
        self.hookmap[pc >> 4] |= 1 << ((pc >> 1) & 7)
        self.lib.m68k_hooks_on(1)

    def _hook(self, pc):
        fn = self.hooks.get(pc)
        if fn is not None:
            fn(pc)
        return 0

    def get(self, r):
        return self.lib.m68k_get(r)

    def set(self, r, v):
        self.lib.m68k_set(r, v & 0xFFFFFFFF)

    def d(self, i):
        return self.lib.m68k_get(i)

    def a(self, i):
        return self.lib.m68k_get(8 + i)

    @property
    def pc(self):
        return self.lib.m68k_get(PC)

    @property
    def sr(self):
        return self.lib.m68k_get(SR)

    def trace(self, on):
        self.lib.m68k_trace(1 if on else 0)

    def take_trace(self):
        """[(pc, cycles before it in the slice)] since the last call (the slice offsets as the trace recorded them)"""
        n = self.lib.m68k_trace_len()
        if not n:
            return []
        buf = np.ctypeslib.as_array(self.lib.m68k_trace_buf(), shape=(n,)).copy()
        self.lib.m68k_trace_clear()
        return list(zip(buf[0::2].tolist(), buf[1::2].tolist()))
