-- gauntlet: log every sound CPU access to $1000-$1FFF / $3000-$3FFF with MAME's time (attoseconds), the audio CPU's
-- and the POKEY's m_totalcycles and, at POKEY / TMS5220 accesses, the chip's internals from MAME's save items; the main
-- CPU's outlatch writes ($803120-$80312F: Q7 = sound reset).  For engine/pokey_test.py and engine/tms5220_test.py.
-- env OUT (log file), FRAMES (frames to run), INPUTS ("frame:port:field:value ...", '_' for spaces in field names).
-- A read tap sees the value after the handler ran, a write tap runs before the handler.
local cpu = manager.machine.devices[":audiocpu"]
local space = cpu.spaces["program"]
local out = os.getenv("OUT") or "acc.txt"
local f = io.open(out, "w")
local function items(tag)
  local t = {}
  for k, v in pairs(manager.machine.devices[tag].items) do t[k:gsub("^0/", "")] = emu.item(v) end
  return t
end
local P = items(":pokey")
local T = items(":tms")
local C = items(":audiocpu")
local buf, n = {}, 0
local function put(s)
  n = n + 1
  buf[n] = s
  if n >= 5000 then f:write(table.concat(buf, "\n"), "\n"); buf = {}; n = 0 end
end
local function tmsstate()
  return string.format("io%d fc%d ip%d pc%d sc%d tk%d td%d sp%d dd%d rw%d bl%d be%d cr%x dl%d tt%d", T.m_io_ready:read(0),
    T.m_fifo_count:read(0), T.m_IP:read(0), T.m_PC:read(0), T.m_subcycle:read(0), T.m_TALK:read(0), T.m_TALKD:read(0),
    T.m_SPEN:read(0), T.m_DDIS:read(0), T.m_rs_ws:read(0), T.m_buffer_low:read(0), T.m_buffer_empty:read(0),
    T.m_command_register:read(0), T.m_data_latched:read(0), T.m_true_timing:read(0))
end
local function pokeystate()
  return string.format("lt %d ch %d %d %d %d b %d %d %d %d ", P["m_localtime.attoseconds"]:read(0), P["m_channel.m_counter"]:read(0), P["m_channel.m_counter"]:read(1),
    P["m_channel.m_counter"]:read(2), P["m_channel.m_counter"]:read(3), P["m_channel.m_borrow_cnt"]:read(0), P["m_channel.m_borrow_cnt"]:read(1),
    P["m_channel.m_borrow_cnt"]:read(2), P["m_channel.m_borrow_cnt"]:read(3)) .. string.format("p17 %d p9 %d p4 %d p5 %d cc %d %d %d pot %d all %x sk %x irqst %x irqen %x", P.m_p17:read(0), P.m_p9:read(0),
    P.m_p4:read(0), P.m_p5:read(0), P.m_clock_cnt:read(0), P.m_clock_cnt:read(1), P.m_clock_cnt:read(2), P.m_pot_counter:read(0),
    P.m_ALLPOT:read(0), P.m_SKCTL:read(0), P.m_IRQST:read(0), P.m_IRQEN:read(0))
end
local function acc(kind, off, data)
  local tm = manager.machine.time
  local o = off & 0x1fff
  local extra = ""
  if o >= 0x1800 and o < 0x1810 then extra = pokeystate()
  elseif (o & 0x1ff8) == 0x1030 or (o & 0x1ff0) == 0x1820 then extra = tmsstate() end
  put(string.format("%s %x %x %d %d %d %d %s", kind, off, data, tm.seconds, tm.attoseconds, C.m_totalcycles:read(0),
    P.m_totalcycles:read(0), extra))
end
taps = {}
for _, base in ipairs({0x1000, 0x3000}) do
  taps[#taps + 1] = space:install_read_tap(base, base + 0xfff, "r" .. base, function(off, data, mask) acc("r", off, data) end)
  taps[#taps + 1] = space:install_write_tap(base, base + 0xfff, "w" .. base, function(off, data, mask) acc("w", off, data) end)
end
local mspace = manager.machine.devices[":maincpu"].spaces["program"]
taps[#taps + 1] = mspace:install_write_tap(0x803000, 0x803fff, "mw", function(off, data, mask)
  if off >= 0x803120 and off < 0x803130 then
    local tm = manager.machine.time
    put(string.format("m %x %x %d %d %x", off, data, tm.seconds, tm.attoseconds, mask))
  end
end)
-- inputs: COIN / START at given frames (env INPUTS = "frame:port:field:value ...")
local inputs = {}
for item in string.gmatch(os.getenv("INPUTS") or "", "%S+") do
  local fr, port, field, v = item:match("(%d+):([^:]+):([^:]+):(%d+)")
  inputs[#inputs + 1] = {tonumber(fr), port, field:gsub("_", " "), tonumber(v)}
end
local frame = 0
local last = tonumber(os.getenv("FRAMES") or "3000")
sub = emu.register_frame_done(function()
  frame = frame + 1
  for _, i in ipairs(inputs) do
    if i[1] == frame then
      manager.machine.ioport.ports[":" .. i[2]].fields[i[3]]:set_value(i[4])
    end
  end
  if frame == last then manager.machine:exit() end
end)
stop = emu.add_machine_stop_notifier(function() f:write(table.concat(buf, "\n"), "\n"); f:close() end)
