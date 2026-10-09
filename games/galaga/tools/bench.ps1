# Repeatable Galaga rate samples; outputs stay in run/<Name>.
param([int]$Frames = 9000, [string]$Name = "galaga_bench", [string[]]$Extra = @())
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
& $py "$PSScriptRoot/build.py" --debug -D RATE=500 --frames $Frames --out "$bench/GALAGA.PRG" @Extra
if ($LASTEXITCODE -ne 0) { throw "Build failed" }
Copy-Item "$root/build/galaga/galaga.map" "$bench/galaga.map"
foreach ($name in @('RATE.BIN', 'CRASH.TXT')) {
    $file = Join-Path $bench $name
    if (Test-Path -LiteralPath $file) { Remove-Item -LiteralPath $file }
}
$p = Start-Process -WindowStyle Hidden -PassThru -FilePath "$arcade/third_party/hatari/build-ucrt64/src/hatari.exe" -WorkingDirectory $bench -ArgumentList @(
    '--machine','ste','--memsize','4','--tos',"$arcade/third_party/tos/tos206de.img",
    '--fast-boot','true','--cpu-exact','true','--compatible','true','--sound','off',
    '--confirm-quit','off','--fast-forward','true','--run-vbls',($Frames+600),
    '--log-file',"$bench\hatari.log","$bench\GALAGA.PRG")
try {
    if (-not $p.WaitForExit(180000)) { throw "Hatari timed out" }
} finally {
    if (-not $p.HasExited) { Stop-Process -Id $p.Id }
}
if (Test-Path "$bench/CRASH.TXT") { throw (Get-Content "$bench/CRASH.TXT" -Raw) }
$b = [IO.File]::ReadAllBytes("$bench/RATE.BIN")
$prevVbl = 0; $prevRender = 0
for ($i=0; $i -lt $b.Length; $i+=4) {
    $vbl = $b[$i]*256+$b[$i+1]; $renders = $b[$i+2]*256+$b[$i+3]
    "VBL {0}-{1}: {2:N1} fps" -f $prevVbl,$vbl,(50*($renders-$prevRender)/($vbl-$prevVbl))
    $prevVbl=$vbl; $prevRender=$renders
}
