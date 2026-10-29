# Pac-Man in the F030Arcade Hatari (STE, 4 MB, TOS 2.06, borders), hidden, for a set number of VBLs: the picture
# recorded (Hatari's AVI, the emulated screen with its borders), the counters printed (COUNTERS.BIN: VBLs, arcade
# frames, pictures drawn, pictures shown), stills extracted every -Every VBLs (ffmpeg).  Outputs in run/<Name>.
# Only the Hatari this script starts is stopped (other sessions may run their own).
#   powershell -File games/pacman/tools/hatari.ps1 [-Frames 1500] [-Every 250] [-Name pacman_hatari] [-Extra ...]
param([int]$Frames = 1500, [int]$Every = 250, [string]$Name = "pacman_hatari", [string[]]$Extra = @())
$ErrorActionPreference = "Stop"
$root = (Resolve-Path "$PSScriptRoot/../../..").Path
if ($Name -notmatch '^[a-zA-Z0-9_-]+$') { throw "Name must be a simple directory name" }
$out = Join-Path $root "run/$Name"
$arcade = if ($env:F030ARCADE) { $env:F030ARCADE } else { "C:/Arbeit/F030Arcade" }
$msys = if ($env:MSYS2) { $env:MSYS2 } else { "C:/msys64" }
$py = (Get-Command python).Source
$env:PATH += ";$msys/mingw64/bin;$msys/ucrt64/bin;$msys/usr/bin"
New-Item -ItemType Directory -Force $out | Out-Null
$out = (Get-Item -LiteralPath $out).FullName
& $py "$PSScriptRoot/build.py" --debug --frames $Frames --out "$out/PACMAN.PRG" @Extra
if ($LASTEXITCODE -ne 0) { throw "Build failed" }
foreach ($f in @('COUNTERS.BIN', 'CRASH.TXT', 'pacman.avi')) {
    $file = Join-Path $out $f
    if (Test-Path -LiteralPath $file) { Remove-Item -LiteralPath $file }
}
Get-ChildItem -LiteralPath $out -Filter 'still_*.png' | Remove-Item
$p = Start-Process -WindowStyle Hidden -PassThru -FilePath "$arcade/third_party/hatari/build-ucrt64/src/hatari.exe" -WorkingDirectory $out -ArgumentList @(
    '--machine','ste','--memsize','4','--tos',"$arcade/third_party/tos/tos206de.img",
    '--fast-boot','true','--cpu-exact','true','--compatible','true','--sound','off','--borders','true',
    '--confirm-quit','off','--statusbar','false','--run-vbls',($Frames+400),
    '--avirecord','true','--avi-vcodec','bmp','--avi-file',"$out\pacman.avi",
    '--log-file',"$out\hatari.log","$out\PACMAN.PRG")
try {
    if (-not $p.WaitForExit(600000)) { throw "Hatari timed out" }
} finally {
    if (-not $p.HasExited) { Stop-Process -Id $p.Id }
}
if (Test-Path "$out/CRASH.TXT") { "--- CRASH.TXT"; Get-Content "$out/CRASH.TXT" }
if (Test-Path "$out/COUNTERS.BIN") {
    $b = [IO.File]::ReadAllBytes("$out/COUNTERS.BIN")
    $v = @(0..3 | ForEach-Object { [BitConverter]::ToUInt32([byte[]]($b[(4*$_+3)..(4*$_)]), 0) })
    "VBLs {0}, arcade frames {1} ({2:N1} a second), pictures drawn {3} ({4:N1} a second), shown {5}" -f $v[0], $v[1], (50*$v[1]/$v[0]), $v[2], (50*$v[2]/$v[0]), $v[3]
} else { "no COUNTERS.BIN (the program did not reach its end)" }
if (Test-Path "$out/pacman.avi") {
    & ffmpeg -v error -i "$out/pacman.avi" -vf "select=not(mod(n\,$Every))" -fps_mode passthrough "$out/still_%03d.png"
    "stills: " + ((Get-ChildItem -LiteralPath $out -Filter 'still_*.png').Count)
}
