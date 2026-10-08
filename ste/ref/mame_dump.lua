-- Ground truth from MAME for the reference renderers: at frame FRAME write the pen colours, a memory
-- range of the main CPU and a screenshot, then quit.  Start MAME with -window (with -video none there is
-- no snapshot):
--
--   FRAME=700 OUT=/tmp/dk START=0x6000 END=0x7fff PAL=:palette \
--   mame dkong -window -rompath ../assets/roms -sound none -nothrottle -seconds_to_run 250 \
--        -skip_gameinfo -autoboot_script ref/mame_dump.lua -snapshot_directory /tmp/dk -snapname shot
--
-- (-seconds_to_run below 300 turns MAME's startup screens off, so no key has to be pressed.)
-- writes OUT/pens.txt ("pen rrggbb"), OUT/mem.bin and OUT/shot.png (the snapshot).  The memory and the
-- screenshot are taken after the frame was drawn, so a moving sprite can be one step ahead of the
-- picture: compare several frames (see ref/mame_cmp_dkong.py).  Latches written by the game ($7D82-$7D87)
-- can not be read back reliably from here, the compare tool searches the palette bank instead.
--
-- INJECT=file: instead of the game's own memory, write the file over START..END at frame FRAME (a RAM image
-- of the reference machine) and take the snapshot DELAY (default 2) frames later; mem.bin then holds what
-- MAME has at that time, so a game that rewrites the range can be seen.  This renders the reference's state
-- with MAME's video code when MAME can not run the game itself (Galaga: no 51xx ROM).
local frame_no = tonumber(os.getenv("FRAME") or "700")
local out = os.getenv("OUT") or "."
local first = tonumber(os.getenv("START") or "0x6000")
local last = tonumber(os.getenv("END") or "0x7fff")
local inject = os.getenv("INJECT")
local delay = tonumber(os.getenv("DELAY") or "2")
local frame = 0
local taps = {}
emu.register_frame_done(function()
  frame = frame + 1
  local m = manager.machine
  local mem = m.devices[os.getenv("CPU") or ":maincpu"].spaces["program"]
  if inject and frame == frame_no then
    local f = io.open(inject, "rb")
    local data = f:read("*a")
    f:close()
    for a = first, last do mem:write_u8(a, data:byte(a - first + 1)) end
    -- freeze the range: a write tap on every CPU (CPUS, default the three of Galaga) puts the injected
    -- byte back, so the game running on does not rewrite what was injected; the screen keeps being
    -- drawn from the RAM
    for tag in string.gmatch(os.getenv("CPUS") or ":maincpu :sub :sub2", "%S+") do
      local dev = m.devices[tag]
      if dev then
        taps[#taps + 1] = dev.spaces["program"]:install_write_tap(first, last, "freeze" .. tag,
          function(offset, d, mask) return data:byte(offset - first + 1) end)
      end
    end
    return
  end
  if frame ~= frame_no + (inject and delay or 0) then return end
  local pal = m.palettes[os.getenv("PAL") or ":palette"]
  local f = io.open(out .. "/pens.txt", "w")
  for i = 0, pal.entries - 1 do
    f:write(string.format("%d %06x\n", i, pal:pen_color(i) & 0xffffff))
  end
  f:close()
  local g = io.open(out .. "/mem.bin", "wb")
  for a = first, last do g:write(string.char(mem:read_u8(a))) end
  g:close()
  m.video:snapshot()
  m:exit()
end)
