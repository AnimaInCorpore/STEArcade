-- Dump of the main CPU's C000-EFFF at the given frames (the old wolfmame-0162 Lua API: only emu.sethook "frame" and memory reads):
--   FRAMES="50 700 1500" LAST=1600 mame.exe 1942 -rompath assets/roms -window -sound none -nothrottle -frameskip 0
--        -skip_gameinfo -seconds_to_run 100 -aviwrite m1942.avi -autoboot_script mame_dump.lua
-- writes dump_<n>.bin (0x3000 bytes) into the current folder; the AVI (224 x 256 RGB24, native size) lands in snap/.
-- The hook count n is 120 frames behind the emulated frame (the game's tick E00C and the AVI index are n + 119): the
-- comparison tool searches that lag.
local frames = {}
for f in string.gmatch(os.getenv("FRAMES") or "", "%d+") do frames[tonumber(f)] = true end
local last = tonumber(os.getenv("LAST") or "3000")
local n = 0
emu.sethook(function()
  n = n + 1
  local m = manager:machine()
  if frames[n] then
    local sp = m.devices[":maincpu"].spaces["program"]
    local g = io.open(string.format("dump_%d.bin", n), "wb")
    for a = 0xC000, 0xEFFF do g:write(string.char(sp:read_u8(a))) end
    g:close()
  end
  if n >= last then m:exit() end
end, "frame")
