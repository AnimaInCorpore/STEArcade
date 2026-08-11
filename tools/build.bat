@echo off
REM Donkey Kong Falcon030 Build Script
REM Requires VASM or RMAC assembler

echo Building Donkey Kong Falcon030 port...

REM Assemble main
C:\msys64\ucrt64\bin\vasmm68k_mot.exe -Fbin -o build/dkong.prg src/main.asm

REM TODO: Add GEMDOS header, link translated modules
echo Build complete.
