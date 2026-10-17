-- Synchronous frame-boundary MAME bridge. Private stdin/stdout; no network server.
-- Coverage is exact first execution at every main-ROM byte address, including
-- code missing from the project's disassembly. One-shot debugger breakpoints
-- disable themselves and continue without stopping the emulated frame.
local m = manager.machine
local cpu = m.devices[":maincpu"]
local mem, ios = cpu.spaces["program"], cpu.spaces["io"]
local debug = assert(cpu.debug, "start MAME with -debug")
local frame, target, system, p1, scroll = 0, 0, 255, 255, 0
local sprites, taps = {}, {}
local armed, deaths = false, 0
local function sys_at(t)
  if t >= 700 and t < 704 then return 247 end
  if t >= 760 and t < 764 then return 254 end
  return 255
end
local function arm()
  debug:bpclear()
  -- Determine the next index, rather than assuming the debugger starts at 1.
  local first = debug:bpset(0, "1", "g")
  debug:bpclear(first)
  for a = 0, 0x7fff do
    local index = first + 1 + a
    assert(debug:bpset(a, "1", string.format("bpdisable %x; g", index)) == index)
  end
  armed = true
end
local function dump(a, b)
  local t = {}
  for x = a, b do t[#t + 1] = string.format("%02x", mem:read_u8(x)) end
  return table.concat(t)
end
local function reply()
  local pcs = {}
  if armed then
    for index, bp in pairs(debug:bplist()) do
      if not bp.enabled then
        pcs[#pcs + 1] = string.format("%04x", bp.address)
        debug:bpclear(index)
      end
    end
  end
  table.sort(pcs)
  local spr = {}
  for a = 0, 255 do spr[#spr + 1] = string.format("%02x", sprites[a] or 0) end
  io.stdout:write(string.format("KF1 %d %d %d %d %s %s %s\n", frame, scroll, cpu.state["PC"].value, deaths,
                               dump(0xd000, 0xefff), table.concat(spr), table.concat(pcs, ",")))
  io.stdout:flush()
end
local function command()
  local line = io.stdin:read("*l")
  if not line or line == "quit" then m:exit(); return false end
  local n, s, p = line:match("^step (%d+) (%d+) (%d+)$")
  n, s, p = tonumber(n), tonumber(s), tonumber(p)
  assert(n and n >= 1 and n <= 900 and s <= 255 and p <= 255, "invalid bridge command")
  target, system, p1 = frame + n, s, p
  return true
end
local function install()
  taps[#taps+1] = ios:install_read_tap(0, 4, "ppo_inputs", function(a, data)
    if a == 0 then return frame < 900 and sys_at(frame) or system end
    if a == 1 then return frame % 4 < 2 and p1 or (p1 | 0xa0) end
    if a == 2 or a == 3 then return 255 end
    if a == 4 then return 253 end
  end)
  taps[#taps+1] = mem:install_write_tap(0xc000, 0xc0ff, "ppo_sprites", function(a, v) sprites[a-0xc000] = v end)
  taps[#taps+1] = mem:install_write_tap(0xa000, 0xa000, "ppo_scroll_lo", function(a,v) scroll = (scroll & 0xff00) | v end)
  taps[#taps+1] = mem:install_write_tap(0xb000, 0xb000, "ppo_scroll_hi", function(a,v) scroll = (scroll & 255) | (v << 8) end)
end
io.stdout:setvbuf("no")
assert(command())
sub = emu.register_frame_done(function()
  frame = frame + 1
  if frame == 1 then install() end
  if frame > 900 and mem:read_u8(0xe084) < 6 then deaths = deaths + 1 end
  if frame >= 900 then mem:write_u8(0xe084, 6) end
  if frame == 900 then arm() end -- exclude boot and attract code from the reward
  if frame == target then reply(); command() end
end)
m.debugger.execution_state = "run"
