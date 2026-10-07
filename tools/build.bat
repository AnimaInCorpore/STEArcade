@echo off
setlocal
REM Donkey Kong Falcon030 assembly smoke build
REM This currently produces a raw 68000 binary, not a final GEMDOS PRG.

set "ASM=C:\msys64\ucrt64\bin\vasmm68k_mot.exe"
if not exist "%ASM%" (
    echo ERROR: VASM not found at %ASM%
    exit /b 1
)

if not exist build mkdir build

echo Building clean Falcon assembly stub...

"%ASM%" -Fbin -o build\dkong.raw src\main.asm
if errorlevel 1 (
    echo Build failed.
    exit /b 1
)

echo Wrote build\dkong.raw
echo NOTE: GEMDOS header and validated routine linking are still pending.
exit /b 0
