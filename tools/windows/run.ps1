# usage: run.ps1 [-Game dkong|galaga|bublbobl] [-Wait 15] [-Out shot.png] [-Keep] [-Prg DKONG.PRG] [-Extra "--option"]
param([int]$Wait = 15, [string]$Out = "shot.png", [switch]$Keep, [string]$Game = "dkong", [string]$Prg = "DKONG.PRG", [string[]]$Extra = @())
$ErrorActionPreference = "Continue"
Get-Process hatari -ErrorAction SilentlyContinue | Stop-Process -Force
$run = "C:\Temp\Z80Test\run\$Game"
Remove-Item "$run\CRASH.TXT" -ErrorAction SilentlyContinue
$env:PATH = "C:\msys64\ucrt64\bin;C:\msys64\usr\bin;" + $env:PATH
$h = "C:\Arbeit\F030Arcade\third_party\hatari\build-ucrt64\src\hatari.exe"
$cargs = @("--machine","ste","--memsize","4","--tos","C:\Arbeit\F030Arcade\third_party\tos\tos206de.img","--fast-boot","true","--cpu-exact","true","--compatible","true","--sound","off","--confirm-quit","off","--statusbar","false","--borders","true","--log-file","$run\hatari.log") + $Extra + @("$run\$Prg")
$p = Start-Process -FilePath $h -ArgumentList $cargs -PassThru
Start-Sleep -Seconds $Wait
if ($p.HasExited) { "hatari exited early"; exit 1 }
$job = Start-Job { param($id, $out) & "C:\Temp\Z80Test\tools\windows\shot.ps1" -ProcId $id -Out $out } -ArgumentList $p.Id, "$run\$Out"
if (Wait-Job $job -Timeout 30) { Receive-Job $job } else { "capture timed out"; Stop-Job $job }
if (Test-Path "$run\CRASH.TXT") { "--- CRASH.TXT"; Get-Content "$run\CRASH.TXT" }
if (-not $Keep) { Stop-Process -Id $p.Id -Force }
