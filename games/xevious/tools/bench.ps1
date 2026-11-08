# Repeatable Xevious rate samples (Hatari fast-forward, 4 MB STE, hidden window); outputs stay in run/<Name>.
# Reads RATE.BIN: per sample the VBL count, the pictures and the arcade (logic) frames since the start.
param([int]$Frames = 3000, [string]$Name = "xevious_bench", [string[]]$Extra = @())
$ErrorActionPreference = "Stop"
$root = (Resolve-Path "$PSScriptRoot/../../..").Path
if ($Name -notmatch '^[a-zA-Z0-9_-]+$') { throw "Name must be a simple directory name" }
$bench = Join-Path $root "run/$Name"
$arcade = if ($env:F030ARCADE) { $env:F030ARCADE } else { "C:/Arbeit/F030Arcade" }
$msys = if ($env:MSYS2) { $env:MSYS2 } else { "C:/msys64" }
$py = (Get-Command python).Source
$env:PATH += ";$msys/mingw64/bin;$msys/ucrt64/bin;$msys/usr/bin"
New-Item -ItemType Directory -Force $bench | Out-Null
$bench = (Get-Item -LiteralPath $bench).FullName
& $py "$PSScriptRoot/build.py" --tag $Name -D RATE=250 --frames $Frames @Extra
if ($LASTEXITCODE -ne 0) { throw "Build failed" }
foreach ($n in @('RATE.BIN', 'CRASH.TXT')) { $f = Join-Path $bench $n; if (Test-Path -LiteralPath $f) { Remove-Item -LiteralPath $f } }
$p = Start-Process -WindowStyle Hidden -PassThru -FilePath "$arcade/third_party/hatari/build-ucrt64/src/hatari.exe" -WorkingDirectory $bench -ArgumentList @(
    '--machine','ste','--memsize','4','--tos',"$arcade/third_party/tos/tos206de.img",
    '--fast-boot','true','--cpu-exact','true','--compatible','true','--sound','off',
    '--confirm-quit','off','--fast-forward','true','--run-vbls',($Frames+600),
    '--log-file',"$bench\hatari.log","$bench\XEVIOUS.PRG")
try {
    if (-not $p.WaitForExit(240000)) { throw "Hatari timed out" }
} finally {
    if (-not $p.HasExited) { Stop-Process -Id $p.Id }
}
if (Test-Path "$bench/CRASH.TXT") { throw (Get-Content "$bench/CRASH.TXT" -Raw) }
$b = [IO.File]::ReadAllBytes("$bench/RATE.BIN")
$pv = 0; $pr = 0; $pl = 0
for ($i = 0; $i -lt $b.Length; $i += 6) {
    $v = $pv + 250; $r = $b[$i+2]*256+$b[$i+3]; $l = $b[$i+4]*256+$b[$i+5]
    "VBL {0}-{1}: {2:N1} pictures/s, {3:N1} arcade frames/s" -f $pv, $v, (50*($r-$pr)/250), (50*($l-$pl)/250)
    $pv = $v; $pr = $r; $pl = $l
}
