-- WolfMAME 0.184's Lua API (manager:machine(), method calls): at each frame in FRAMES (comma list) write the main
-- CPU's $6000-$7FFF to OUT/mem_<frame>.bin and a snapshot (OUT/snap/<frame>.png via -snapname), then quit after the
-- last.  The memory is read after the frame was drawn (a moving sprite can be one step ahead of the picture).
local out = os.getenv("OUT") or "."
local frames = {}
local last = 0
for f in string.gmatch(os.getenv("FRAMES") or "700", "%d+") do
  frames[tonumber(f)] = true
  if tonumber(f) > last then last = tonumber(f) end
end
local frame = 0
emu.register_frame_done(function()
  frame = frame + 1
  local m = manager:machine()
  if frames[frame] then
    local mem = m.devices[":maincpu"].spaces["program"]
    local f = io.open(out .. "/mem_" .. frame .. ".bin", "wb")
    for a = 0x6000, 0x7fff do f:write(string.char(mem:read_u8(a))) end
    f:close()
    m:video():snapshot()
  end
  if frame >= last then m:exit() end
end)
