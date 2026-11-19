# Defender in the F030Arcade Hatari (STE, 4 MB, TOS 2.06, borders), hidden, for a set number of VBLs; the program then
# writes its screen (SCREEN.BIN: -D SHOT=1) and quits, and shot.py turns it into a PNG.  No AVI (a still per run).
# Outputs in run/<Name>.  Only the Hatari this script starts is stopped.
#   powershell -File games/defender/tools/hatari.ps1 [-Frames 1500] [-Name defender_hatari] [-Extra build.py options]
param([int]$Frames = 1500, [string]$Name = "defender_hatari", [string[]]$Extra = @())
$ErrorActionPreference = "Stop"
$root = (Resolve-Path "$PSScriptRoot/../../..").Path
if ($Name -notmatch '^[a-zA-Z0-9_-]+$') { throw "Name must be a simple directory name" }
$arcade = if ($env:F030ARCADE) { $env:F030ARCADE } else { "C:/Arbeit/F030Arcade" }
$msys = if ($env:MSYS2) { $env:MSYS2 } else { "C:/msys64" }
$env:PATH += ";$msys/mingw64/bin;$msys/ucrt64/bin;$msys/usr/bin"
$py = Join-Path $root "venv/bin/python.exe"
if (-not (Test-Path $py)) { $py = "python" }
& $py "$PSScriptRoot/build.py" --frames $Frames --tag $Name -D SHOT=1 @Extra
if ($LASTEXITCODE -ne 0) { throw "Build failed" }
$out = (Get-Item -LiteralPath (Join-Path $root "run/$Name")).FullName
foreach ($f in @('CRASH.TXT', 'SCREEN.BIN', 'screen.png')) {
    $file = Join-Path $out $f
    if (Test-Path -LiteralPath $file) { Remove-Item -LiteralPath $file }
}
$args = @('--machine','ste','--memsize','4','--tos',"$arcade/third_party/tos/tos206de.img",
    '--fast-boot','true','--cpu-exact','true','--compatible','true','--sound','off','--borders','true',
    '--confirm-quit','off','--statusbar','false','--run-vbls',($Frames+600),'--log-file',"$out\hatari.log")
$p = Start-Process -WindowStyle Hidden -PassThru -FilePath "$arcade/third_party/hatari/build-ucrt64/src/hatari.exe" `
    -WorkingDirectory $out -ArgumentList ($args + "$out\DEFENDER.PRG")
try {
    if (-not $p.WaitForExit(900000)) { throw "Hatari timed out" }
} finally {
    if (-not $p.HasExited) { Stop-Process -Id $p.Id }
}
if (Test-Path "$out/CRASH.TXT") { "--- CRASH.TXT"; Get-Content "$out/CRASH.TXT" }
if (Test-Path "$out/SCREEN.BIN") { & $py "$PSScriptRoot/shot.py" "$out/SCREEN.BIN" "$out/screen.png" }
else { "no SCREEN.BIN (the program did not reach its end)" }
