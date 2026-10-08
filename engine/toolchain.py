"""Assemble and link one port: the part of every build.py that does not depend on the game.

    assemble_link(game, "dkong.s", "dkong", out_prg, defines)

The source is games/<game>/src/<main>; the assembler finds the generated files (build/<game>/) and the
shared runtime (engine/rt/) through -I.  Object and map land in build/<game>/.
"""
import subprocess
import sys

from paths import VASM, VLINK, RT_INCLUDE, src_dir, build_dir


def assemble_link(game, main, tag, out, defines=()):
    """defines: ["FRAMES=100", "DEBUG=1", ...].  Exits with the tool's status on an error."""
    build = build_dir(game)
    obj = build / (tag + ".o")
    cmd = [VASM, "-Fvobj", "-quiet", "-nowarn=2047", "-I", str(build), "-I", str(RT_INCLUDE)]
    cmd += ["-D" + d for d in defines]
    cmd += ["-o", str(obj), main]
    for step in (cmd, [VLINK, "-b", "ataritos", "-s", "-o", str(out), "-M" + str(build / (tag + ".map")), str(obj)]):
        r = subprocess.run(step, cwd=src_dir(game), capture_output=True, text=True)
        sys.stdout.write(r.stdout + r.stderr)
        if r.returncode:
            sys.exit(r.returncode)
