"""Super Xevious graphics for the STE: build/xevious/xevious_assets.s (first version: the palette only)."""
import os, sys
sys.path[:0] = [os.path.dirname(os.path.abspath(__file__)), os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "engine")]
from paths import build_dir

BUILD = str(build_dir("xevious"))


def build():
    lines = ["ga_palette:"]
    pal = [0x000, 0x888, 0xFFF, 0xF00, 0x0F0, 0x00F, 0xFF0, 0x0FF, 0xF0F, 0x444, 0xCCC, 0x840, 0x480, 0x048, 0x804, 0x084]
    lines.append("\tdc.w\t" + ",".join("$%03X" % c for c in pal))
    open(os.path.join(BUILD, "xevious_assets.s"), "w").write("\n".join(lines) + "\n")


if __name__ == "__main__":
    build()
