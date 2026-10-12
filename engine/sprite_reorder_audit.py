"""Try mask-group order for DK/Galaga without duplicating their plane assets.

Their generic 64 KB fallback shares the original-order plane data. This candidate
therefore seeks the source pointer between reordered lines and preserves both
vertical directions. It estimates 68000 instruction costs, including the extra
source/destination moves; bus costs are identical for either order. Retain the
existing emitter if no variant improves. Run after building both ports:

    venv/bin/python engine/sprite_reorder_audit.py

This is an experiment report, not a frame-rate measurement. Ports with a packed
reordered source and destination-offset stream use a different contract.
"""
from paths import build_dir


def cost(masks, order, first, end):
    cycles = 0
    source = first
    previous = None
    end1 = end3 = width = None
    for row in order:
        if row != source:
            cycles += 28                    # add.l #delta,BLT_SRC_ADDR.w
        if previous is not None:
            gap = row - previous
            cycles += 12 * abs(gap)          # add/sub d4,(a3), both directions
            if gap != 1:
                cycles += 20                # word-group correction
        e1, e3 = masks[row]
        words = 1 if not e3 else 2
        changed_width = words != width
        cycles += 32 if changed_width else 0
        cycles += 12 * (e1 != end1)
        cycles += 12 * (words == 2 and e3 != end3)
        cycles += 8 + (12 if changed_width else 8)
        end1 = e1
        if words == 2:
            end3 = e3
        width, previous, source = words, row, row + 1
    if source != end:
        cycles += 28                        # preserve the source end-pointer contract
    return cycles


def main():
    for game, prefix in (("dkong", "dk"), ("galaga", "ga")):
        data = (build_dir(game) / f"{prefix}_spr_masks.bin").read_bytes()
        wins = saved = tested = 0
        for off in range(0, len(data), 64):
            masks = [tuple(int.from_bytes(data[off + row * 4 + k:off + row * 4 + k + 2], "big")
                           for k in (0, 2)) for row in range(16)]
            rows = [row for row in range(16) if any(masks[row])]
            if not rows:
                continue
            groups = {}
            for row in rows:
                groups.setdefault(masks[row], []).append(row)
            reordered = [row for group in groups.values() for row in group]
            before = cost(masks, rows, rows[0], rows[-1] + 1)
            after = cost(masks, reordered, rows[0], rows[-1] + 1)
            tested += 1
            if after < before:
                wins += 1
                saved += before - after
        print(f"{game}: {tested} nonblank shape/skew variants; reordered winners {wins}; "
              f"estimated cycles saved {saved}")


if __name__ == "__main__":
    main()
