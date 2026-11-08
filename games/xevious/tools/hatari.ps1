# Super Xevious in the F030Arcade Hatari (STE, 4 MB, TOS 2.06, borders), hidden, for a set number of VBLs: the picture
# recorded (Hatari's AVI, the emulated screen with its borders), the counters printed (COUNTERS.BIN: VBLs, pictures,
# arcade frames, the border fallbacks and late events), stills extracted every -Every VBLs (ffmpeg).  Outputs in
# run/<Name>.  Only the Hatari this script starts is stopped (other sessions may run their own).  After Pac-Man's.
#   powershell -File games/xevious/tools/hatari.ps1 [-Frames 3000] [-Every 300] [-Name xevious_hatari] [-Avi 1]
#     [-Extra build.py options; default -D AUTOPLAY=1: a coin, start and play from the VBL]
param([int]$Frames = 600, [int]$Every = 100, [string]$Name = "xevious_hatari", [int]$Avi = 1, [string]$Sound = "off", [string]$Codec = "bmp", [int]$AviFps = 0,
      [string[]]$Extra = @('-D', 'AUTOPLAY=1', '-D', 'RATE=250'))
$ErrorActionPreference = "Stop"
# (the uncompressed AVI is ~1.3 MB a frame and the SSD has no DRAM cache: stills of short runs only; long runs: bench.ps1)
if ($Avi -and $Frames -gt 800) { throw "AVI recording only for short runs (-Frames <= 800); use bench.ps1 for long ones" }
$root = (Resolve-Path "$PSScriptRoot/../../..").Path
if ($Name -notmatch '^[a-zA-Z0-9_-]+$') { throw "Name must be a simple directory name" }
$arcade = if ($env:F030ARCADE) { $env:F030ARCADE } else { "C:/Arbeit/F030Arcade" }
$msys = if ($env:MSYS2) { $env:MSYS2 } else { "C:/msys64" }
$py = (Get-Command python).Source
$env:PATH += ";$msys/mingw64/bin;$msys/ucrt64/bin;$msys/usr/bin"
& $py "$PSScriptRoot/build.py" --frames $Frames --tag $Name @Extra
if ($LASTEXITCODE -ne 0) { throw "Build failed" }
$out = (Get-Item -LiteralPath (Join-Path $root "run/$Name")).FullName
foreach ($f in @('COUNTERS.BIN', 'CRASH.TXT', 'RATE.BIN', 'xevious.avi')) {
    $file = Join-Path $out $f
    if (Test-Path -LiteralPath $file) { Remove-Item -LiteralPath $file }
}
Get-ChildItem -LiteralPath $out -Filter 'still_*.png' | Remove-Item
$args = @('--machine','ste','--memsize','4','--tos',"$arcade/third_party/tos/tos206de.img",
    '--fast-boot','true','--cpu-exact','true','--compatible','true','--sound',$Sound,'--borders','true',
    '--confirm-quit','off','--statusbar','false','--run-vbls',($Frames+400),'--log-file',"$out\hatari.log")
if ($Avi) { $args += @('--avirecord','true','--avi-vcodec',$Codec,'--avi-file',"$out\xevious.avi"); if ($AviFps) { $args += @('--avi-fps',"$AviFps") } }
$p = Start-Process -WindowStyle Hidden -PassThru -FilePath "$arcade/third_party/hatari/build-ucrt64/src/hatari.exe" `
    -WorkingDirectory $out -ArgumentList ($args + "$out\XEVIOUS.PRG")
try {
    if (-not $p.WaitForExit(900000)) { throw "Hatari timed out" }
} finally {
    if (-not $p.HasExited) { Stop-Process -Id $p.Id }
}
if (Test-Path "$out/CRASH.TXT") { "--- CRASH.TXT"; Get-Content "$out/CRASH.TXT" }
if (Test-Path "$out/RATE.BIN") {
    $b = [IO.File]::ReadAllBytes("$out/RATE.BIN")
    for ($i = 0; $i -lt $b.Length; $i += 8) { "VBL {0}: pictures {1}, arcade frames {2}, area {3}" -f ($b[$i]*256+$b[$i+1]), ($b[$i+2]*256+$b[$i+3]), ($b[$i+4]*256+$b[$i+5]), ($b[$i+6]*256+$b[$i+7]) }
} else { "no RATE.BIN (the program did not reach its end)" }
if ($Avi -and (Test-Path "$out/xevious.avi")) {
    & ffmpeg -v error -i "$out/xevious.avi" -vf "select=not(mod(n\,$Every))" -fps_mode passthrough "$out/still_%03d.png"
    "stills: " + ((Get-ChildItem -LiteralPath $out -Filter 'still_*.png').Count)
}
