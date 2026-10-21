-- MAME ground truth for the real 51XX / 54XX in tools/machine.py (ref/mame_cmp_51xx.py starts it):
-- the inputs of a script, then every 06XX access of the main CPU logged and the RAM written at given frames.
--
--   INPUTS=file   lines "frame in0 in1" (hex, active low as the ports): from that frame on
--   OUT=dir       writes OUT/io.txt ("frame r|w|c value" for 7000 reads, 7000 writes, 7100 writes; "frame m51|m54
--                 ram pc": the MCUs' 64 data nibbles and program counter at each frame_done) and
--                 OUT/ram_<frame>.bin (8000-9FFF) for every frame in DUMP
--   DUMP="a b c"  FRAMES=n (quit after n frames)
--
-- Frame k is the k-th frame_done callback (the start of the vertical blank); the inputs for frame k are set there,
-- as the reference machine takes the inputs of its frame k before running it.
local out = os.getenv("OUT") or "."
local frames = tonumber(os.getenv("FRAMES") or "1000")
local dump = {}
for f in string.gmatch(os.getenv("DUMP") or "", "%d+") do dump[tonumber(f)] = true end
local script = {}
for line in io.lines(os.getenv("INPUTS")) do
  local f, a, b = line:match("(%d+)%s+(%x+)%s+(%x+)")
  if f then script[#script + 1] = {tonumber(f), tonumber(a, 16), tonumber(b, 16)} end
end
local m = manager.machine
local ports = {m.ioport.ports[":IN0"], m.ioport.ports[":IN1"]}
local function set_inputs(v0, v1)
  local vals = {v0, v1}
  for i = 1, 2 do
    for _, f in pairs(ports[i].fields) do
      f:set_value(((vals[i] & f.mask) == 0) and 1 or 0)
    end
  end
end
local log = io.open(out .. "/io.txt", "w")
local frame = 0
local mem = m.devices[":maincpu"].spaces["program"]
-- (the taps are kept in a global: a tap that the garbage collector takes is removed)
local function install()
  return {
  mem:install_read_tap(0x7000, 0x70ff, "r06", function(offset, data, mask)
    log:write(string.format("%d r %02x\n", frame, data & 0xff)) return data end),
  mem:install_write_tap(0x7000, 0x70ff, "w06", function(offset, data, mask)
    log:write(string.format("%d w %02x\n", frame, data & 0xff)) return data end),
  mem:install_write_tap(0x7100, 0x7100, "c06", function(offset, data, mask)
    log:write(string.format("%d c %02x\n", frame, data & 0xff)) return data end),
  }
end
taps = install()
reinstalls = 0
local si = 1
local cur0, cur1 = 0xff, 0xff
set_inputs(cur0, cur1)
log:write(string.format("dsw %02x %02x\n", m.ioport.ports[":DSWA"]:read(), m.ioport.ports[":DSWB"]:read()))
local mcus = {{"m51", m.devices[":51xx:mcu"]}, {"m54", m.devices[":54xx:mcu"]}}
emu.register_frame_done(function()
  frame = frame + 1
  -- the MCUs' data RAM (64 nibbles) and PA:PC at the start of the vertical blank
  for _, d in ipairs(mcus) do
    local sp = d[2].spaces["data"]
    local t = {}
    for a = 0, 63 do t[#t + 1] = string.format("%x", sp:read_u8(a) & 15) end
    log:write(string.format("%d %s %s %03x\n", frame, d[1], table.concat(t), d[2].state["GENPC"].value))
  end
  if dump[frame] then
    local g = io.open(string.format("%s/ram_%d.bin", out, frame), "wb")
    for a = 0x8000, 0x9fff do g:write(string.char(mem:read_u8(a))) end
    g:close()
  end
  while si <= #script and script[si][1] <= frame do
    cur0, cur1 = script[si][2], script[si][3]
    si = si + 1
  end
  set_inputs(cur0, cur1)
  if frame >= frames then
    log:write(string.format("reinstalls %d\n", reinstalls))
    log:close()
    m:exit()
  end
end)
