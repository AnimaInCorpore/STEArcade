-- Jail Break: every write to the 005849's control registers ($2040-$2047) and to the watchdog ($3300) with the main CPU's
-- local time in CPU cycles (1.536 MHz) since power-on, up to frame LAST.  OUT=<file> LAST=<frame>
local m = manager.machine
local out = assert(io.open(assert(os.getenv("OUT")), "w"))
local last = tonumber(os.getenv("LAST") or "1560")
local function now()
  local t = emu.time()
  if type(t) ~= "number" then t = t:as_double() end
  return t * 1536000
end
local frame = 0
taps = {}
local s = m.devices[":maincpu"].spaces["program"]
local function tap(a, b, name)
  taps[#taps + 1] = s:install_write_tap(a, b, name, function(offset, data, mask)
    out:write(string.format("%d %.2f %s %04x %02x\n", frame, now(), name, offset, data & 0xff))
  end)
end
sub = emu.register_frame_done(function()
  frame = frame + 1
  out:write(string.format("%d %.2f F\n", frame, now()))
  if frame == 1 then tap(0x2040, 0x2047, "c") tap(0x3300, 0x3300, "w")
    taps[#taps + 1] = s:install_read_tap(0xFFF6, 0xFFFD, "vec", function(offset, data, mask)
      out:write(string.format("%d %.2f v %04x\n", frame, now(), offset))
    end)
  end
  if frame >= last then out:close() m:exit() end
end)
