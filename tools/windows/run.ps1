# usage: run.ps1 [-Game dkong|galaga|bublbobl] [-Wait 15] [-Out shot.png] [-Keep] [-Prg DKONG.PRG] [-Extra "--option"]
# Runs run\<game>\<Prg> in the F030Arcade Hatari and screenshots it.  The repository is found from this script's
# location; F030ARCADE (default C:\Arbeit\F030Arcade) is the F030Arcade checkout and MSYS2 (default C:\msys64)
# the MSYS2 install.
param([int]$Wait = 15, [string]$Out = "shot.png", [switch]$Keep, [string]$Game = "dkong", [string]$Prg = "DKONG.PRG", [string[]]$Extra = @())
$ErrorActionPreference = "Continue"
Get-Process hatari -ErrorAction SilentlyContinue | Stop-Process -Force
$root = (Resolve-Path "$PSScriptRoot\..\..").Path
$arcade = if ($env:F030ARCADE) { $env:F030ARCADE } else { "C:\Arbeit\F030Arcade" }
$msys = if ($env:MSYS2) { $env:MSYS2 } else { "C:\msys64" }
$run = "$root\run\$Game"
Remove-Item "$run\CRASH.TXT" -ErrorAction SilentlyContinue
$env:PATH = "$msys\ucrt64\bin;$msys\usr\bin;" + $env:PATH
$h = "$arcade\third_party\hatari\build-ucrt64\src\hatari.exe"
$cargs = @("--machine","ste","--memsize","4","--tos","$arcade\third_party\tos\tos206de.img","--fast-boot","true","--cpu-exact","true","--compatible","true","--sound","off","--confirm-quit","off","--statusbar","false","--borders","true","--log-file","$run\hatari.log") + $Extra + @("$run\$Prg")
$p = Start-Process -FilePath $h -ArgumentList $cargs -PassThru
Start-Sleep -Seconds $Wait
if ($p.HasExited) { "hatari exited early"; exit 1 }
$shot = "$PSScriptRoot\shot.ps1"
$job = Start-Job { param($id, $out, $shot) & $shot -ProcId $id -Out $out } -ArgumentList $p.Id, "$run\$Out", $shot
if (Wait-Job $job -Timeout 30) { Receive-Job $job } else { "capture timed out"; Stop-Job $job }
if (Test-Path "$run\CRASH.TXT") { "--- CRASH.TXT"; Get-Content "$run\CRASH.TXT" }
if (-not $Keep) { Stop-Process -Id $p.Id -Force }
