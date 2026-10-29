"""Add ROM file names, sizes and hashes from MAME driver sources to docs/mame-candidates.*.

Usage: python tools/mame_candidate_roms.py <mame source root>

Reads every ROM_START block under <root>/src/mame (driver-local #define macros
expanded), then adds a `roms` column to docs/mame-candidates.csv and a ROM files
section to docs/mame-candidates.md. Only the set's own ROMs are listed, as
`mame -listxml` does; ROMs of devices (MCUs such as Namco 51XX) live in their own
device sets.
"""

import csv
import io
import re
import sys
from pathlib import Path

DOCS = Path(__file__).resolve().parent.parent / "docs"

BLOCK = re.compile(r"ROM_START\(\s*(\w+)\s*\)(.*?)ROM_END", re.S)
DEFINE = re.compile(r"^[ \t]*#define[ \t]+(\w+)(\([^)]*\))?[ \t]*((?:[^\n]*\\\n)*[^\n]*)", re.M)
# A load macro: first quoted string is the file name; size is the argument after the offset.
LOAD = re.compile(r"\b(ROMX?_\w+)\s*\(([^;\n]*?\"[^\"]+\"[^\n]*)")
GROW = re.compile(r"\b(ROM_CONTINUE|ROM_IGNORE)\s*\(([^\n]*)")
REGION = re.compile(r"\bROM_REGION\w*\(\s*[^,]+,\s*\"([^\"]+)\"")
HASH = re.compile(r"CRC\(\s*([0-9a-fA-F]{8})\s*\)\s*SHA1\(\s*([0-9a-fA-F]{40})\s*\)")


TOKENS = re.compile(r'"(?:\\.|[^"\\\n])*"|/\*.*?\*/|//[^\n]*', re.S)


def strip_comments(text):
    """Remove comments, leaving string literals (which may hold // or /*) alone."""
    def keep(m):
        t = m.group(0)
        if t.startswith('"'):
            return t
        return "\n" * t.count("\n") or " "
    return TOKENS.sub(keep, text)


def call_end(s):
    """Index just past the parenthesis closing a call whose '(' was already consumed."""
    depth, quote = 0, False
    for k, ch in enumerate(s):
        if ch == '"':
            quote = not quote
        elif not quote and ch == "(":
            depth += 1
        elif not quote and ch == ")":
            if depth == 0:
                return k + 1
            depth -= 1
    return len(s)


def int_arg(s):
    """Value of a size argument: a number or simple arithmetic such as 0x4000*2."""
    s = s.strip()
    if not re.fullmatch(r"[0-9a-fA-FxX+\-*/() \t]+", s or "x"):
        return None
    try:
        v = eval(re.sub(r"\b0+(\d)", r"\1", s), {"__builtins__": {}})
        return int(v)
    except Exception:
        return None


def split_args(s):
    """Split a macro argument list at top-level commas (stops at the closing parenthesis)."""
    args, depth, cur, quote = [], 0, "", False
    for ch in s:
        if ch == '"':
            quote = not quote
        elif not quote:
            if ch == "(":
                depth += 1
            elif ch == ")":
                if depth == 0:
                    break
                depth -= 1
            elif ch == "," and depth == 0:
                args.append(cur.strip())
                cur = ""
                continue
        cur += ch
    args.append(cur.strip())
    return args


def expand(body, macros, depth=0):
    """Expand the file's own ROM macros, with or without parameters."""
    if depth > 5 or not macros:
        return body
    names = "|".join(sorted(map(re.escape, macros), key=len, reverse=True))
    pat = re.compile(r"\b(" + names + r")\b")
    out, pos = "", 0
    for m in pat.finditer(body):
        if m.start() < pos:
            continue
        params, mbody = macros[m.group(1)]
        end = m.end()
        call = re.match(r"\s*\(", body[end:])
        if params:
            if not call:
                continue
            inner = body[end + call.end():]
            args = split_args(inner)
            end += call.end() + call_end(inner)
            for p, a in zip(params, args):
                mbody = re.sub(r"\b" + re.escape(p) + r"\b", lambda _m, a=a: a, mbody)
        elif call:
            end += call.end() + call_end(body[end + call.end():])
        out += body[pos:m.start()] + "\n" + mbody + "\n"
        pos = end
    out += body[pos:]
    return out if out == body else expand(out, macros, depth + 1)


def parse_roms(body):
    roms, region = [], ""
    for line in body.split("\n"):
        r = REGION.search(line)
        if r:
            region = r.group(1)
        # ROM_CONTINUE / ROM_IGNORE read further bytes of the file loaded just before.
        for c in GROW.finditer(line):
            if roms and roms[-1]["size"] is not None:
                n = int_arg(split_args(c.group(2))[-1])
                roms[-1]["size"] = None if n is None else roms[-1]["size"] + n
        m = LOAD.search(line)
        if not m or m.group(1) in ("ROM_COPY", "ROM_SYSTEM_BIOS", "ROM_PARAMETER", "ROM_DEFAULT_BIOS") \
                or m.group(1).startswith("ROM_REGION"):
            continue
        args = split_args(m.group(2))
        names = [i for i, a in enumerate(args) if a.startswith('"')]
        if not names:
            continue
        i = names[0]
        name = args[i].strip('"')
        size = int_arg(args[i + 2]) if i + 2 < len(args) else None
        rest = m.group(2)
        h = HASH.search(rest)
        roms.append({
            "name": name,
            "size": size,
            "crc": h.group(1).lower() if h else "",
            "sha1": h.group(2).lower() if h else "",
            "status": "nodump" if "NO_DUMP" in rest else "baddump" if "BAD_DUMP" in rest else "",
            "region": region,
        })
    return roms


def read_sets(root):
    sets = {}
    for path in (Path(root) / "src" / "mame").rglob("*.cpp"):
        text = strip_comments(path.read_text(encoding="utf-8", errors="replace"))
        if "ROM_START" not in text:
            continue
        macros = {}
        for d in DEFINE.finditer(text):
            body = d.group(3).replace("\\\n", "\n")
            if "ROM_" in body:
                params = [a.strip() for a in d.group(2).strip("()").split(",")] if d.group(2) else []
                macros[d.group(1)] = ([a for a in params if a], body)
        for b in BLOCK.finditer(text):
            sets[b.group(1)] = (path.relative_to(Path(root) / "src" / "mame").as_posix(),
                                parse_roms(expand(b.group(2), macros)))
    return sets


def rom_field(r):
    size = "?" if r["size"] is None else str(r["size"])
    if r["status"] == "nodump":
        return f"{r['name']}:{size}:nodump"
    s = f"{r['name']}:{size}:{r['crc']}:{r['sha1']}"
    return s + ":baddump" if r["status"] else s


def unique(roms):
    """Drop repeats of the same file (ROM_RELOAD-style macros, BIOS alternatives sharing a file)."""
    seen, out = set(), []
    for r in roms:
        key = (r["name"], r["crc"])
        if key not in seen:
            seen.add(key)
            out.append(r)
    return out


def main(root):
    sets = read_sets(root)

    csv_path = DOCS / "mame-candidates.csv"
    rows = list(csv.DictReader(io.StringIO(csv_path.read_text(encoding="utf-8"))))
    fields = [f for f in rows[0].keys() if f != "roms"] + ["roms"]
    missing = []
    for row in rows:
        entry = sets.get(row["mame"])
        if entry is None:
            missing.append(row["mame"])
            row["roms"] = ""
        else:
            row["roms"] = "; ".join(rom_field(r) for r in unique(entry[1]))
    out = io.StringIO()
    w = csv.DictWriter(out, fieldnames=fields, lineterminator="\n")
    w.writeheader()
    w.writerows(rows)
    csv_path.write_text(out.getvalue(), encoding="utf-8")

    md_path = DOCS / "mame-candidates.md"
    md = md_path.read_text(encoding="utf-8")
    md = md.split("\n## ROM files\n")[0].rstrip("\n") + "\n"
    lines = ["", "## ROM files", "",
             "File names, sizes (bytes), CRC32 and SHA-1 of each candidate's own ROMs, from the "
             "`ROM_START` blocks of the MAME 0.286 driver sources (`tools/mame_candidate_roms.py`); "
             "each set's main CPU ROM total matches *Program* above (MAME 0.289). A clone set lists all "
             "its ROMs, including those shared with its parent; sets with selectable BIOSes list every "
             "BIOS version. ROMs of devices (MCUs such as the Namco 51XX) are in the device's own set "
             "and not listed here. The CSV has the same data in its `roms` column "
             "(`name:size:crc:sha1`, `;`-separated; `nodump`/`baddump` as MAME marks them).", ""]
    if missing:
        lines += ["Not in the 0.286 sources (added or renamed since): " +
                  ", ".join(f"`{m}`" for m in missing) + ".", ""]
    for row in rows:
        entry = sets.get(row["mame"])
        if entry is None:
            continue
        roms = unique(entry[1])
        total = sum(r["size"] or 0 for r in roms if r["status"] != "nodump")
        lines += [f"<details><summary>{row['rank']}. {row['game']} — <code>{row['mame']}</code> "
                  f"({entry[0]}, {len(roms)} files, {total:,} bytes)</summary>", "",
                  "| File | Region | Size | CRC32 | SHA-1 |", "|---|---|---:|---|---|"]
        for r in roms:
            size = "?" if r["size"] is None else str(r["size"])
            if r["status"] == "nodump":
                lines.append(f"| {r['name']} | {r['region']} | {size} | not dumped | |")
            else:
                note = " (bad dump)" if r["status"] else ""
                lines.append(f"| {r['name']} | {r['region']} | {size} | {r['crc']} | {r['sha1']}{note} |")
        lines += ["", "</details>", ""]
    md_path.write_text(md + "\n".join(lines), encoding="utf-8")

    print(f"{len(sets)} sets read; {len(rows) - len(missing)} of {len(rows)} candidates filled; "
          f"missing: {' '.join(missing) or 'none'}")


if __name__ == "__main__":
    main(sys.argv[1])
