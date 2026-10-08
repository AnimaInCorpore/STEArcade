import os
os.chdir(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
r = open("rt/render.s", newline="").read().replace("\r\n", "\n")
a = r.index("; ------------------------------------------------------------------------------\n; Sprites\n")
b = r.index("; ------------------------------------------------------------------------------\n; draw_tile: d0.w = tile index (visible), a0 = screen base")
r = r[:a] + '\tinclude "sprites.s"\n\n' + r[b:]
old = "\tmove\t(a2)+,d0\n\tmove.l\tdraw_screen_address,a0\n\tmove.l\ta2,-(sp)\n\tbsr\tdraw_tile"
new = "\tmove\t(a2)+,d0\n\tmove.l\tdraw_screen_address,a0\n\tmove.l\ta2,-(sp)\n\tbsr\tmark_tile\n\tbsr\tdraw_tile"
assert old in r
r = r.replace(old, new, 1)
assert "render_frame:\n" in r
r = r.replace("render_frame:\n", "render_frame:\n\tbsr\tclear_cells\n", 1)
old = "\tst\tspr_invalid\n\tst\tspr_invalid+1\n\trts"
assert old in r
r = r.replace(old, "\tst\tspr_invalid\n\tst\tspr_invalid+1\n\tlea\tspr_prev_rect,a0\n\tmove\t#95,d0\n\tmoveq\t#-1,d1\n.hide:\n\tmove.l\td1,(a0)+\n\tdbf\td0,.hide\n\trts", 1)
old = "spr_old_count:\tds.w\t2\ntiles_drawn:\tds.w\t1"
assert old in r
r = r.replace(old, "tiles_drawn:\tds.w\t1\nspr_inv_cur:\tds.b\t1\n\teven\ncells:\t\tds.b\t512\nspr_new_rect:\tds.w\t96\nspr_new_routine:\tds.l\t96\nspr_new_src:\tds.l\t96\nspr_redraw:\tds.b\t96\nspr_prev_rect:\tds.w\t96*2", 1)
r = r.replace("spr_list_ptr:\tds.l\t1\nspr_old_list:\tds.w\t96*2", "")
open("rt/render.s", "w", newline="").write(r)
print("patched")
