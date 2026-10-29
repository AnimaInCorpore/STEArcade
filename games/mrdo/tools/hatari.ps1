# Mr. Do! in the F030Arcade Hatari (STE, 4 MB, TOS 2.06, borders), hidden, for a set number of VBLs: the picture
# recorded (Hatari's AVI, the emulated screen with its borders), the counters printed (COUNTERS.BIN: VBLs, pictures,
# arcade frames, the border fallbacks and late events), stills extracted every -Every VBLs (ffmpeg).  Outputs in
# run/<Name>.  Only the Hatari this script starts is stopped (other sessions may run their own).  After Pooyan's.
#   powershell -File games/mrdo/tools/hatari.ps1 [-Frames 3000] [-Every 300] [-Name mrdo_hatari] [-Avi 1]
#     [-Extra build.py options; default -D AUTOPLAY=1: a coin, start and play from the VBL]
param([int]$Frames = 3000, [int]$Every = 300, [string]$Name = "mrdo_hatari", [int]$Avi = 1,
      [string[]]$Extra = @('-D', 'AUTOPLAY=1'))
$ErrorActionPreference = "Stop"
$root = (Resolve-Path "$PSScriptRoot/../../..").Path
if ($Name -notmatch '^[a-zA-Z0-9_-]+$') { throw "Name must be a simple directory name" }
$arcade = if ($env:F030ARCADE) { $env:F030ARCADE } else { "C:/Arbeit/F030Arcade" }
$msys = if ($env:MSYS2) { $env:MSYS2 } else { "C:/msys64" }
$py = Join-Path $root "venv/bin/python.exe"
$env:PATH += ";$msys/mingw64/bin;$msys/ucrt64/bin;$msys/usr/bin"
& $py "$PSScriptRoot/build.py" --debug --frames $Frames --tag $Name @Extra
if ($LASTEXITCODE -ne 0) { throw "Build failed" }
$out = (Get-Item -LiteralPath (Join-Path $root "run/$Name")).FullName
foreach ($f in @('COUNTERS.BIN', 'CRASH.TXT', 'RATE.BIN', 'mrdo.avi')) {
    $file = Join-Path $out $f
    if (Test-Path -LiteralPath $file) { Remove-Item -LiteralPath $file }
}
Get-ChildItem -LiteralPath $out -Filter 'still_*.png' | Remove-Item
$args = @('--machine','ste','--memsize','4','--tos',"$arcade/third_party/tos/tos206de.img",
    '--fast-boot','true','--cpu-exact','true','--compatible','true','--sound','off','--borders','true',
    '--confirm-quit','off','--statusbar','false','--run-vbls',($Frames+400),'--log-file',"$out\hatari.log")
if ($Avi) { $args += @('--avirecord','true','--avi-vcodec','bmp','--avi-file',"$out\mrdo.avi") }
$p = Start-Process -WindowStyle Hidden -PassThru -FilePath "$arcade/third_party/hatari/build-ucrt64/src/hatari.exe" `
    -WorkingDirectory $out -ArgumentList ($args + "$out\MRDO.PRG")
try {
    if (-not $p.WaitForExit(900000)) { throw "Hatari timed out" }
} finally {
    if (-not $p.HasExited) { Stop-Process -Id $p.Id }
}
if (Test-Path "$out/CRASH.TXT") { "--- CRASH.TXT"; Get-Content "$out/CRASH.TXT" }
if (Test-Path "$out/COUNTERS.BIN") {
    $b = [IO.File]::ReadAllBytes("$out/COUNTERS.BIN")
    $w = @(0..7 | ForEach-Object { $b[2*$_]*256 + $b[2*$_+1] })
    "VBLs {0}, arcade frames {1} ({2:N1} a second), pictures {3} ({4:N1} a second); border fallbacks {5}, late top/on/low/off {6}/{7}/{8}/{9}" -f `
        $w[0], $w[2], (50*$w[2]/$w[0]), $w[1], (50*$w[1]/$w[0]), $w[3], $w[4], $w[5], $w[6], $w[7]
} else { "no COUNTERS.BIN (the program did not reach its end)" }
if ($Avi -and (Test-Path "$out/mrdo.avi")) {
    & ffmpeg -v error -i "$out/mrdo.avi" -vf "select=not(mod(n\,$Every))" -fps_mode passthrough "$out/still_%03d.png"
    "stills: " + ((Get-ChildItem -LiteralPath $out -Filter 'still_*.png').Count)
}
