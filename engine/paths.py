"""Where things are: the repository layout and the assembler toolchain.

    engine/            shared translator, simulator, runtime pieces      (this folder)
    games/<game>/      src/ (68000 source), tools/ (generator, build, tests), ref/ (analysis scripts)
    build/<game>/      generated code, assets, coverage data, maps       (not in git)
    run/<game>/        the .PRG and the ROM files it loads               (not in git)
    assets/roms/       ROM archives; extracted/ holds the unpacked files
"""
import os
from pathlib import Path

ENGINE = Path(__file__).resolve().parent
ROOT = ENGINE.parent
ROMS = ROOT / "assets" / "roms"
EXTRACTED = ROMS / "extracted"


def game_dir(game):
    return ROOT / "games" / game


def src_dir(game):
    return ROOT / "games" / game / "src"


def build_dir(game):
    """Generated files; created on demand."""
    d = ROOT / "build" / game
    d.mkdir(parents=True, exist_ok=True)
    return d


def run_dir(game):
    return ROOT / "run" / game


# Assembler include path of every game: its build folder (generated code, assets) and the shared runtime.
RT_INCLUDE = ENGINE / "rt"

# Toolchain: VASM / VLINK env vars win; otherwise the Windows checkout, else a macOS build from f030dsp3d.
_HOME = os.path.expanduser("~/Work/f030dsp3d/tools")
VLINK = os.environ.get("VLINK") or (r"C:/Arbeit/F030Arcade/third_party/vlink/vlink.exe" if os.name == "nt" else os.path.join(_HOME, "vlink", "vlink"))
VASM = os.environ.get("VASM") or (r"C:\Arbeit\F030Arcade\third_party\vasm\vasmm68k_mot.exe" if os.name == "nt" else os.path.join(_HOME, "vasm", "vasmm68k_mot"))

