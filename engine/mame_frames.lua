-- Ground truth from MAME at several frames in one run (the reference boards' mame_cmp_<game>.py):
--
--   OUT=/tmp/x FRAMES="60 600 1200" DUMPS="maincpu:0x0000:0xffff sub:0x4000:0x47ff" TAPS="sub:0x4040:0x40ff" \
--   mame trackfld -window -rompath assets/roms -sound none -nothrottle -seconds_to_run 250 -skip_gameinfo \
--        -autoboot_script engine/mame_frames.lua -snapshot_directory /tmp/x
--
-- At the end of each frame in FRAMES (the frame_done callback, at the start of the vertical blank) it writes
--   OUT/f<frame>_<tag>.bin   the bytes start..end of the CPU's program space (DUMPS: tag:start:end ...)
--   OUT/f<frame>.png         the screen (the snapshot, rotated as MAME shows it)
--   OUT/f<frame>_taps.txt    every write to a TAPS range since the previous frame's end
--                            ("tag line offset data", line = the beam position
--                            in lines, its integer part MAME's vpos(); from frame 2 on)
--   OUT/pens.txt             the palette's pens ("pen rrggbb"), once
-- and quits after the last.  Run it in a fresh directory: MAME writes nvram/ and cfg/ there and reads them back.
local out = assert(os.getenv("OUT"))
local frames = {}
local last = 0
for f in string.gmatch(os.getenv("FRAMES") or "60", "%d+") do
  frames[tonumber(f)] = true
  if tonumber(f) > last then last = tonumber(f) end
end
local m = manager.machine
local screen = m.screens[os.getenv("SCREEN") or ":screen"]
local vtotal = math.floor(screen.frame_period / screen.scan_period + 0.5)
local dumps = {}
for tag, a, b in string.gmatch(os.getenv("DUMPS") or "maincpu:0:0xffff", "([%w_]+):(%w+):(%w+)") do
  dumps[#dumps + 1] = {tag, tonumber(a), tonumber(b)}
end
local log = {}
local function beam()                       -- the beam position in lines (vpos + hpos / htotal; no vpos() in Lua)
  local lines = screen:time_until_pos(0, 0) / screen.scan_period   -- (seconds, a number)
  local v = (-lines) % vtotal
  return v
end
taps = {}                                   -- (global: the handlers must stay referenced)
local function install_taps()               -- (installed at the first frame's end: earlier ones were lost)
  for tag, a, b in string.gmatch(os.getenv("TAPS") or "", "([%w_]+):(%w+):(%w+)") do
    taps[#taps + 1] = m.devices[":" .. tag].spaces["program"]:install_write_tap(tonumber(a), tonumber(b),
      "log" .. tag .. a, function(offset, data, mask)
        log[#log + 1] = string.format("%s %.4f %04x %02x", tag, beam(), offset, data & 0xff)
      end)
  end
end
local frame = 0
local pens_done = false
sub = emu.register_frame_done(function()
  frame = frame + 1
  if frame == 1 then install_taps() end
  if frames[frame] then
    for _, d in ipairs(dumps) do
      local mem = m.devices[":" .. d[1]].spaces["program"]
      local t = {}
      for a = d[2], d[3] do t[#t + 1] = string.char(mem:read_u8(a)) end
      local f = io.open(string.format("%s/f%d_%s.bin", out, frame, d[1]), "wb")
      f:write(table.concat(t))
      f:close()
    end
    local f = io.open(string.format("%s/f%d_taps.txt", out, frame), "w")
    f:write(table.concat(log, "\n"))
    if #log > 0 then f:write("\n") end
    f:close()
    if not pens_done then
      pens_done = true
      local pal = m.palettes[os.getenv("PAL") or ":palette"]
      f = io.open(out .. "/pens.txt", "w")
      for i = 0, pal.entries - 1 do f:write(string.format("%d %06x\n", i, pal:pen_color(i) & 0xffffff)) end
      f:close()
    end
    screen:snapshot(string.format("f%d.png", frame))
    if frame >= last then m:exit() end
  end
  log = {}
end)
