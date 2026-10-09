# Speed of Commando in Hatari (Windows): a DEBUG + AUTOPLAY build (scripted coin, start, fire and joystick, period 3000
# frames) runs 6000 VBLs in run\commando_bench and writes COUNTERS.BIN.  The Windows counterpart of bench.sh.
#
#   games\commando\tools\bench.ps1 [-Frames 6000] [-Extra "-D","MAX_SKIP=1"]
#
# Hatari runs with --fast-forward (the emulated timing is unchanged).  Only the Hatari started here is stopped.
# F030ARCADE (default C:\Arbeit\F030Arcade) is the F030Arcade checkout, MSYS2 (default C:\msys64) the MSYS2 install.
# Reports the game ticks a second (the arcade: 59.6) and the frames drawn a second; the first VBLs are the boot.
param([int]$Frames = 6000, [string[]]$Extra = @())
$ErrorActionPreference = "Stop"
$root = (Resolve-Path "$PSScriptRoot\..\..\..").Path
$arcade = if ($env:F030ARCADE) { $env:F030ARCADE } else { "C:\Arbeit\F030Arcade" }
$msys = if ($env:MSYS2) { $env:MSYS2 } else { "C:\msys64" }
$py = if (Test-Path "$root\venv\Scripts\python.exe") { "$root\venv\Scripts\python.exe" } else { (Get-Command python).Source }
$bench = "$root\run\commando_bench"
$env:PATH = $env:PATH + ";$msys\mingw64\bin;$msys\ucrt64\bin;$msys\usr\bin"      # (vasm / vlink and Hatari need its DLLs; after the Python in use)
New-Item -ItemType Directory -Force $bench | Out-Null
& $py "$root\games\commando\tools\build.py" --debug -D AUTOPLAY=1 --frames $Frames @Extra | Select-String "built|rror"
if ($LASTEXITCODE) { "build failed"; exit 1 }
Copy-Item "$root\run\commando\COMMANDO.PRG" $bench
& $py "$root\games\commando\tools\build.py" | Select-String "built|rror"      # (run\commando gets the normal build back)
Remove-Item "$bench\COUNTERS.BIN", "$bench\CRASH.TXT" -ErrorAction SilentlyContinue
$p = Start-Process -FilePath "$arcade\third_party\hatari\build-ucrt64\src\hatari.exe" -WorkingDirectory $bench -PassThru -ArgumentList @(
  "--machine", "ste", "--memsize", "4", "--tos", "$arcade\third_party\tos\tos206de.img", "--fast-boot", "true",
  "--cpu-exact", "true", "--compatible", "true", "--sound", "off", "--confirm-quit", "off", "--statusbar", "false",
  "--fast-forward", "true", "--log-file", "$bench\hatari.log", "$bench\COMMANDO.PRG")
$deadline = (Get-Date).AddSeconds(300)
while ((Get-Date) -lt $deadline -and -not (Test-Path "$bench\COUNTERS.BIN") -and -not (Test-Path "$bench\CRASH.TXT")) {
  Start-Sleep -Milliseconds 500
}
Start-Sleep -Seconds 1
if (-not $p.HasExited) { Stop-Process -Id $p.Id -Force }
if (Test-Path "$bench\CRASH.TXT") { "--- CRASH.TXT"; Get-Content "$bench\CRASH.TXT" }
if (-not (Test-Path "$bench\COUNTERS.BIN")) { "no COUNTERS.BIN"; exit 1 }
$b = [IO.File]::ReadAllBytes("$bench\COUNTERS.BIN")
$vbl = $b[0] * 256 + $b[1]; $renders = $b[4] * 256 + $b[5]; $ticks = $b[8] * 256 + $b[9]
"VBLs $vbl, frames drawn $renders, ticks $ticks"
"game ticks {0:N1} /s (arcade 59.6) = {1:N0}% speed;  frames drawn {2:N1} /s" -f ($ticks / $vbl * 50), ($ticks / $vbl * 50 / 59.6 * 100), ($renders / $vbl * 50)
"borders: top border armed by the VBL in {0} frames; events that started too late: top border {1}, palette on {2}, bottom border {3}, palette off {4}" -f ($b[10] * 256 + $b[11]), ($b[12] * 256 + $b[13]), ($b[14] * 256 + $b[15]), ($b[16] * 256 + $b[17]), ($b[18] * 256 + $b[19])
if ($b.Length -ge 48) { "passes run in pieces: {0}" -f [BitConverter]::ToUInt32(@($b[47], $b[46], $b[45], $b[44]), 0) }
