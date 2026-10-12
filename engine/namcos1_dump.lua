-- Namco System 1 ground truth from MAME (engine/namcos1_mame.py): at frame FRAME write the video state as the
-- CUS117 virtual space holds it, the pens and a snapshot into OUT, then quit.  Start MAME with -window.
--   OUT/video.bin: 2E0000-2E7FFF (CUS116), 2F0000-2F7FFF (CUS123 tile RAM), 2FC000-2FCFFF (scratch + sprite RAM),
--                  2FD000-2FD01F (CUS123 control), 2FF000-2FF7FF (TRIRAM), 300000-307FFF (RAM)
--   OUT/pens.txt ("pen rrggbb"), OUT/shot.png
-- FRAMES="a b c" takes several captures in one run (OUT/<frame>/...).
local frames = {}
for f in string.gmatch(os.getenv("FRAMES") or os.getenv("FRAME") or "700", "%d+") do frames[tonumber(f)] = true end
local last = 0
for f, _ in pairs(frames) do if f > last then last = f end end
local out = os.getenv("OUT") or "."
local frame = 0
local ranges = {{0x2e0000, 0x2e7fff}, {0x2f0000, 0x2f7fff}, {0x2fc000, 0x2fcfff}, {0x2fd000, 0x2fd01f},
                {0x2ff000, 0x2ff7ff}, {0x300000, 0x307fff}}
emu.register_frame_done(function()
  frame = frame + 1
  if not frames[frame] then return end
  local m = manager.machine
  local dir = out .. "/" .. frame
  os.execute("mkdir -p " .. dir)
  local space = m.devices[":c117"].spaces["program"]
  local g = io.open(dir .. "/video.bin", "wb")
  for _, r in ipairs(ranges) do
    for a = r[1], r[2] do g:write(string.char(space:read_u8(a))) end
  end
  g:close()
  local pal = m.palettes[":c116"]
  local f = io.open(dir .. "/pens.txt", "w")
  for i = 0, pal.entries - 1 do f:write(string.format("%d %06x\n", i, pal:pen_color(i) & 0xffffff)) end
  f:close()
  m.video:snapshot()
  os.execute("mv " .. out .. "/shot.png " .. dir .. "/shot.png 2>/dev/null")
  if frame >= last then m:exit() end
end)
