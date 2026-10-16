-- Kung-Fu Master's sound board in MAME (ref/mame_sound_kungfum.py): the M6803's writes to its port registers
-- ($00-$03: the AY buses), the IRQ acknowledge and the ADPCM nibbles ($0800-$0803), and the main CPU's sound
-- commands (I/O port 0), frame by frame:  OUT/sound.txt lines "frame kind address value [beam]".
--   OUT=dir FRAMES=n mame kungfum -window ... -autoboot_script mame_sound.lua
local out = assert(os.getenv("OUT"))
local last = tonumber(os.getenv("FRAMES") or "600")
local m = manager.machine
local f = io.open(out .. "/sound.txt", "w")
local frame = 0
local screen = m.screens[":screen"]
local vtotal = math.floor(screen.frame_period / screen.scan_period + 0.5)
taps = {}
local function install()
  local snd = m.devices[":irem_audio:iremsound"].spaces["program"]
  taps[#taps + 1] = snd:install_write_tap(0x0000, 0x0003, "ports", function(offset, data, mask)
    f:write(string.format("%d p %d %d\n", frame, offset, data & 0xff))
  end)
  taps[#taps + 1] = snd:install_write_tap(0x0800, 0x0803, "msm", function(offset, data, mask)
    f:write(string.format("%d m %d %d\n", frame, offset - 0x0800, data & 0xff))
  end)
  local io = m.devices[":maincpu"].spaces["io"]
  taps[#taps + 1] = io:install_write_tap(0x00, 0x00, "cmd", function(offset, data, mask)
    local beam = ((-screen:time_until_pos(0, 0) / screen.scan_period) % vtotal)
    f:write(string.format("%d c 0 %d %.4f\n", frame, data & 0xff, beam))
  end)
end
-- PLAY=1: a coin at frame 700, start at 760, then walking left with punches and kicks (MAME's inputs)
local play = os.getenv("PLAY") == "1"
local function field(port, name)
  for n, fld in pairs(m.ioport.ports[port].fields) do
    if n == name then return fld end
  end
end
local coin, start, left, punch, kick
if play then
  coin = field(":SYSTEM", "Coin 1"); start = field(":SYSTEM", "1 Player Start")
  left = field(":P1", "P1 Left"); punch = field(":P1", "P1 Button 1"); kick = field(":P1", "P1 Button 2")
end
sub = emu.register_frame_done(function()
  frame = frame + 1
  if play then
    coin:set_value((frame >= 700 and frame < 704) and 1 or 0)
    start:set_value((frame >= 760 and frame < 764) and 1 or 0)
    left:set_value((frame > 900 and frame % 200 < 150) and 1 or 0)
    punch:set_value((frame > 900 and frame % 8 < 3) and 1 or 0)
    kick:set_value((frame > 900 and frame % 50 > 44) and 1 or 0)
  end
  if frame == 1 then install() end
  if frame >= last then f:close(); m:exit() end
end)
