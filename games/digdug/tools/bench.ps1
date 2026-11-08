# Dig Dug's picture rate in Hatari (14 MB, fast forward): a --debug -D RATE=500 -D AUTOPLAY=1400 build plays the scripted game
# (a coin and a start at VBL 1400, then moves and pumps) and writes RATE.BIN (VBL and render counters every 500 VBLs);
# renders per VBL x 50 = pictures a second.
#
#   games\digdug\tools\bench.ps1 [-Frames 6000] [-Name digdug_bench] [-Extra '-D','NOSOUND=1'] [-MemSize 4]
#
# The game's course follows the CPU budget (the scripted moves are not the same moves at another speed): the windows of
# two builds compare as ranges, not frame by frame.
param([int]$Frames = 6000, [string]$Name = "digdug_bench", [string[]]$Extra = @(), [int]$MemSize = 14)
$root = (Resolve-Path "$PSScriptRoot\..\..\..").Path
$run = "$root\run\$Name"
New-Item -ItemType Directory -Force $run | Out-Null
& python "$root\games\digdug\tools\build.py" --debug -D RATE=500 -D AUTOPLAY=1400 --frames $Frames @Extra --out "$run\DIGDUG.PRG" | Select-Object -Last 1
Remove-Item "$run\RATE.BIN", "$run\CRASH.TXT" -ErrorAction SilentlyContinue
$env:PATH = "C:\msys64\ucrt64\bin;" + $env:PATH
$arcade = "C:\Arbeit\F030Arcade"
$h = "$arcade\third_party\hatari\build-ucrt64\src\hatari.exe"
$a = @("--machine", "ste", "--memsize", $MemSize, "--tos", "$arcade\third_party\tos\tos206de.img", "--fast-boot", "true", "--cpu-exact", "true",
       "--compatible", "true", "--sound", "off", "--confirm-quit", "off", "--statusbar", "false", "--fast-forward", "true",
       "--run-vbls", ($Frames + 600), "--log-file", "$run\hatari.log", "$run\DIGDUG.PRG")
$p = Start-Process $h -ArgumentList $a -WorkingDirectory $run -PassThru
if (-not $p.WaitForExit(600000)) { $p.Kill(); "killed" }
if (Test-Path "$run\CRASH.TXT") { "--- CRASH.TXT"; Get-Content "$run\CRASH.TXT" -TotalCount 10 }
if (-not (Test-Path "$run\RATE.BIN")) { "no RATE.BIN"; exit 1 }
$d = [IO.File]::ReadAllBytes("$run\RATE.BIN")
$pv = 0; $pr = 0; $pg = 0; $rates = @(); $logic = @()
for ($i = 0; $i + 5 -lt $d.Length; $i += 6) {
    $v = $d[$i] * 256 + $d[$i + 1]; $r = $d[$i + 2] * 256 + $d[$i + 3]; $g = $d[$i + 4] * 256 + $d[$i + 5]
    if ($v -gt $pv) {
        $rates += [math]::Round(50 * ($r - $pr) / ($v - $pv), 1)
        $logic += [math]::Round(100 * 50 * ($g - $pg) / ($v - $pv) / 60.606, 0)
    }
    $pv = $v; $pr = $r; $pg = $g
}
"arcade frames a second as % of 60.6 per 500 VBLs: " + ($logic -join " ")
"pictures a second per 500 VBLs: " + ($rates -join " ")
"average: " + [math]::Round(($rates | Measure-Object -Average).Average, 1)
