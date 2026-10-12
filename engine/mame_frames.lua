-- Ground truth from MAME at several frames in one run (the reference boards' mame_cmp_<game>.py):
--
--   OUT=/tmp/x FRAMES="60 600 1200" DUMPS="maincpu:0x0000:0xffff sub:0x4000:0x47ff" TAPS="sub:0x4040:0x40ff" \
--   mame trackfld -window -rompath assets/roms -sound none -nothrottle -seconds_to_run 250 -skip_gameinfo \
--        -autoboot_script engine/mame_frames.lua -snapshot_directory /tmp/x
--
-- At the end of each frame in FRAMES (the frame_done callback, at the start of the vertical blank) it writes
--   OUT/f<frame>_<tag>.bin   the bytes start..end of the CPU's program space (DUMPS: tag:start:end ...);
--                            an entry tag:space:start:end names another space ("io", "opcodes", ...), and a dump of
--                            another space or a second range of the same tag goes to f<frame>_<tag>_<space>_<start>.bin
--                            (start in hex, at least 5 digits: 20-bit addresses are fine)
--   OUT/f<frame>.png         the screen (the snapshot, rotated as MAME shows it)
--   OUT/f<frame>_taps.txt    every write to a TAPS range since the previous frame's end
--                            ("tag line offset data", line = the beam position
--                            in lines, its integer part MAME's vpos(); from frame 2 on).  TAPS entries are
--                            tag:start:end (program space) or tag:space:start:end (the tag field then reads
--                            tag:space); a write wider than a byte is logged byte by byte (the mask's lanes, in
--                            the space's endianness)
--   OUT/f<frame>_tapstate.txt  the last byte written to each tapped address before the logged writes
--                            ("tag offset data": the registers at the previous frame's end; empty if never written)
--   OUT/f<frame>_snap<i>.bin, f<frame>_snap<i>_prev.bin  SNAPS (optional): "tag:space:addr=srctag:start:end ...":
--                            a write to addr copies srctag's program space start..end (a DMA on a port write, e.g.
--                            a buffered sprite RAM); the copy at the frame's end and at the previous frame's end
--   OUT/pens.txt             the palette's pens ("pen rrggbb"), once (PENS_EVERY=1: also f<frame>_pens.txt each time)
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

local function parse(spec)                  -- "tag:a:b" or "tag:space:a:b" -> tag, space, a, b
  local p = {}
  for x in string.gmatch(spec, "[^:]+") do p[#p + 1] = x end
  if #p == 3 then return p[1], "program", tonumber(p[2]), tonumber(p[3]) end
  return p[1], p[2], tonumber(p[3]), tonumber(p[4])
end
local function space(tag, sp) return m.devices[":" .. tag].spaces[sp] end

local dumps = {}
local count = {}
for spec in string.gmatch(os.getenv("DUMPS") or "maincpu:0:0xffff", "%S+") do
  local tag, sp, a, b = parse(spec)
  dumps[#dumps + 1] = {tag, sp, a, b}
  count[tag] = (count[tag] or 0) + 1
end
for _, d in ipairs(dumps) do
  if d[2] == "program" and count[d[1]] == 1 then d[5] = d[1]
  else d[5] = string.format("%s_%s_%05x", d[1], d[2], d[3]) end
end

local log = {}
local function beam()                       -- the beam position in lines (vpos + hpos / htotal; no vpos() in Lua)
  local lines = screen:time_until_pos(0, 0) / screen.scan_period   -- (seconds, a number)
  local v = (-lines) % vtotal
  return v
end
local shadow, shadow0 = {}, {}              -- [name] = {[offset] = byte}: now / at the previous frame's end
local snaps = {}                            -- {cur, prev}
taps = {}                                   -- (global: the handlers must stay referenced)
local function install_taps()               -- (installed at the first frame's end: earlier ones were lost)
  for spec in string.gmatch(os.getenv("TAPS") or "", "%S+") do
    local tag, sp, a, b = parse(spec)
    local s = space(tag, sp)
    local name = sp == "program" and tag or (tag .. ":" .. sp)
    local bytes = s.data_width // 8
    local big = s.endianness == "big"
    shadow[name] = shadow[name] or {}
    local sh = shadow[name]
    local a0, b0 = a - a % bytes, b - b % bytes + bytes - 1      -- (the tap's range must cover whole bus words)
    taps[#taps + 1] = s:install_write_tap(a0, b0, "log" .. name .. a, function(offset, data, mask)
      local line = beam()
      for lane = 0, bytes - 1 do
        local shift = 8 * lane
        if (mask >> shift) & 0xff ~= 0 then
          local o = big and (offset + bytes - 1 - lane) or (offset + lane)
          if o >= a and o <= b then
            local v = (data >> shift) & 0xff
            log[#log + 1] = string.format("%s %.4f %04x %02x", name, line, o, v)
            sh[o] = v
          end
        end
      end
    end)
  end
  for spec in string.gmatch(os.getenv("SNAPS") or "", "%S+") do
    local trig, src = string.match(spec, "([^=]+)=(.+)")
    local tag, sp, a = string.match(trig, "([^:]+):([^:]+):(%w+)")
    local stag, s0, s1 = string.match(src, "([^:]+):(%w+):(%w+)")
    s0, s1 = tonumber(s0), tonumber(s1)
    local n = #snaps + 1
    snaps[n] = {cur = string.rep("\0", s1 - s0 + 1)}
    snaps[n].prev = snaps[n].cur
    local smem = space(stag, "program")
    local ts = space(tag, sp)
    local bytes = ts.data_width // 8
    a = tonumber(a)
    local lane = ts.endianness == "big" and (bytes - 1 - a % bytes) or a % bytes
    taps[#taps + 1] = ts:install_write_tap(a - a % bytes, a - a % bytes + bytes - 1, "snap" .. n, function(offset, data, mask)
      if (mask >> (8 * lane)) & 0xff == 0 then return end
      local t = {}
      for x = s0, s1 do t[#t + 1] = string.char(smem:read_u8(x)) end
      snaps[n].cur = table.concat(t)
    end)
  end
end
local function copy(t)
  local c = {}
  for k, v in pairs(t) do
    local d = {}
    for o, x in pairs(v) do d[o] = x end
    c[k] = d
  end
  return c
end
local function write_file(name, data)
  local f = io.open(out .. "/" .. name, "wb")
  f:write(data)
  f:close()
end
local function pens_text()
  local pal = m.palettes[os.getenv("PAL") or ":palette"]
  local t = {}
  for i = 0, pal.entries - 1 do t[#t + 1] = string.format("%d %06x\n", i, pal:pen_color(i) & 0xffffff) end
  return table.concat(t)
end
local frame = 0
local pens_done = false
sub = emu.register_frame_done(function()
  frame = frame + 1
  if frame == 1 then install_taps() end
  if frames[frame] then
    for _, d in ipairs(dumps) do
      local mem = space(d[1], d[2])
      local t = {}
      for a = d[3], d[4] do t[#t + 1] = string.char(mem:read_u8(a)) end
      write_file(string.format("f%d_%s.bin", frame, d[5]), table.concat(t))
    end
    write_file(string.format("f%d_taps.txt", frame), table.concat(log, "\n") .. (#log > 0 and "\n" or ""))
    if next(shadow) ~= nil then
      local t = {}
      for name, sh in pairs(shadow0) do
        for o, v in pairs(sh) do t[#t + 1] = string.format("%s %04x %02x\n", name, o, v) end
      end
      table.sort(t)
      write_file(string.format("f%d_tapstate.txt", frame), table.concat(t))
    end
    for n, s in ipairs(snaps) do
      write_file(string.format("f%d_snap%d.bin", frame, n), s.cur)
      write_file(string.format("f%d_snap%d_prev.bin", frame, n), s.prev)
    end
    if not pens_done then
      pens_done = true
      write_file("pens.txt", pens_text())
    end
    if os.getenv("PENS_EVERY") == "1" then write_file(string.format("f%d_pens.txt", frame), pens_text()) end
    screen:snapshot(string.format("f%d.png", frame))
    if frame >= last then m:exit() end
  end
  log = {}
  if next(shadow) ~= nil then shadow0 = copy(shadow) end
  for _, s in ipairs(snaps) do s.prev = s.cur end
end)
