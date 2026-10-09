# Speed of Gun.Smoke in Hatari (Windows): a DEBUG + AUTOPLAY build (scripted coin, start, movement and the shots, period
# 3000 ticks) runs 6000 VBLs in run\gunsmoke_bench and writes COUNTERS.BIN.
#
#   games\gunsmoke\tools\bench.ps1 [-Frames 6000] [-Extra "-D","MAX_SKIP=1"]
#
# Hatari runs with --fast-forward (the emulated timing is unchanged).  Only the Hatari started here is stopped.
# F030ARCADE (default C:\Arbeit\F030Arcade) is the F030Arcade checkout, MSYS2 (default C:\msys64) the MSYS2 install.
# Reports the game ticks a second (the arcade: 59.6) and the frames drawn a second; the first VBLs are the boot.
param([int]$Frames = 6000, [string[]]$Extra = @())
$ErrorActionPreference = "Stop"
$root = (Resolve-Path "$PSScriptRoot\..\..\..").Path
$arcade = if ($env:F030ARCADE) { $env:F030ARCADE } else { "C:\Arbeit\F030Arcade" }
$msys = if ($env:MSYS2) { $env:MSYS2 } else { "C:\msys64" }
$py = if (Test-Path "$root\venv\Scripts\python.exe") { "$root\venv\Scripts\python.exe" } else { "python" }
$bench = "$root\run\gunsmoke_bench"
$env:PATH = "$msys\mingw64\bin;$msys\ucrt64\bin;$msys\usr\bin;" + $env:PATH     # (vasm / vlink and Hatari need its DLLs)
New-Item -ItemType Directory -Force $bench | Out-Null
& $py "$root\games\gunsmoke\tools\build.py" --debug -D AUTOPLAY=1 --frames $Frames @Extra | Select-String "built|rror"
Copy-Item "$root\run\gunsmoke\GUNSMOKE.PRG" "$bench\GUNSMOKE.PRG"
& $py "$root\games\gunsmoke\tools\build.py" | Select-String "built|rror"      # (run\gunsmoke gets the normal build back)
Remove-Item "$bench\COUNTERS.BIN", "$bench\CRASH.TXT" -ErrorAction SilentlyContinue
$p = Start-Process -FilePath "$arcade\third_party\hatari\build-ucrt64\src\hatari.exe" -WorkingDirectory $bench -PassThru -ArgumentList @(
  "--machine", "ste", "--memsize", "4", "--tos", "$arcade\third_party\tos\tos206de.img", "--fast-boot", "true",
  "--cpu-exact", "true", "--compatible", "true", "--sound", "off", "--confirm-quit", "off", "--statusbar", "false",
  "--fast-forward", "true", "--log-file", "$bench\hatari.log", "$bench\GUNSMOKE.PRG")
$deadline = (Get-Date).AddSeconds(300)
while ((Get-Date) -lt $deadline -and -not (Test-Path "$bench\COUNTERS.BIN") -and -not (Test-Path "$bench\CRASH.TXT")) {
  Start-Sleep -Milliseconds 500
}
Start-Sleep -Seconds 1
if (-not $p.HasExited) { Stop-Process -Id $p.Id -Force }
if (Test-Path "$bench\CRASH.TXT") { "--- CRASH.TXT"; Get-Content "$bench\CRASH.TXT" }
if (-not (Test-Path "$bench\COUNTERS.BIN")) { "no COUNTERS.BIN"; exit 1 }
$b = [IO.File]::ReadAllBytes("$bench\COUNTERS.BIN")
$vbl = $b[0] * 256 + $b[1]; $renders = $b[2] * 256 + $b[3]; $ticks = $b[4] * 256 + $b[5]
"VBLs $vbl, frames drawn $renders, ticks $ticks"
if ($b.Length -ge 20) {
  "borders: top border armed by the VBL in {0} frames; events that started too late: top border {1}, palette on {2}, bottom border {3}, palette off {4}" -f ($b[6] * 256 + $b[7]), ($b[8] * 256 + $b[9]), ($b[10] * 256 + $b[11]), ($b[12] * 256 + $b[13]), ($b[14] * 256 + $b[15])
  "passes run in pieces: {0}" -f [BitConverter]::ToUInt32(@($b[19], $b[18], $b[17], $b[16]), 0)
}
"game ticks {0:N1} /s (arcade 59.6) = {1:N0}% speed;  frames drawn {2:N1} /s" -f ($ticks / $vbl * 50), ($ticks / $vbl * 50 / 59.6 * 100), ($renders / $vbl * 50)
