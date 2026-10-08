# ROM manifest (verified by tools/bbrom.py, 2026-10-08)

Common to both sets (identical CRCs) plus the two main-CPU ROMs per set.

| file | bytes | crc32 | sha1 | role |
|---|---:|---|---|---|
| a71-25.41 | 256 | 2d0f8545 | 089c31e2f614145ef2743164f7b52ae35bc06808 | sprite strip PROM |
| a78-01.17 | 4096 | b1bfb53d | 31b8f31acd3aa394acd80db362774749842e1285 | MC6801 MCU mask ROM ($F000-$FFFF) |
| a78-05-1.52 | 65536 | 9f8ee242 | 924150d4e7e087a9b2b0a294c2d0e9903a266c6c | main Z80 banked ROM, 4 x 16 KiB at $8000 |
| a78-06-1.51 | 32768 | 567934b6 | b0c4d49fd551f465d148c25c3e80b278835e2f0d | main Z80 $0000-$7FFF |
| a78-07.46 | 32768 | 4f9a26e8 | 3105b34b88a7134493c2b3f584729f8b0407a011 | sound Z80 |
| a78-08.37 | 32768 | ae11a07b | af7a335c8da637103103cc274e077f123908ebb7 | sub Z80 |
| a78-09.12 | 32768 | 20358c22 | 2297af6c53d5807bf90a8e081075b8c72a994fc5 | gfx plane 0/1 |
| a78-10.13 | 32768 | 930168a9 | fd358c3c3b424bca285f67a1589eb98a345ff670 | gfx plane 0/1 |
| a78-11.14 | 32768 | 9773e512 | 33c1687ee575d66bf0e98add45d06da827813765 | gfx plane 0/1 |
| a78-12.15 | 32768 | d045549b | 0c12077d3ddc2ce6aa45a0224ad5540f3f218446 | gfx plane 0/1 |
| a78-13.16 | 32768 | d0af35c5 | c5a89f4d73acc0db86654540b3abfd77b3757db5 | gfx plane 0/1 |
| a78-14.17 | 32768 | 7b5369a8 | 1307b26d80e6f36ebe6c442bebec41d20066eaf9 | gfx plane 0/1 |
| a78-15.30 | 32768 | 6b61a413 | 44eddf12fb46fceca2addbe6da929aaea7636b13 | gfx plane 2/3 |
| a78-16.31 | 32768 | b5492d97 | d5b045e3ebaa44809757a4220cefb3c6815470da | gfx plane 2/3 |
| a78-17.32 | 32768 | d69762d5 | 3326fef4e0bd86681a3047dc11886bb171ecb609 | gfx plane 2/3 |
| a78-18.33 | 32768 | 9f243b68 | 32dce8d311a4be003693182a999e4053baa6bb0a | gfx plane 2/3 |
| a78-19.34 | 32768 | 66e9438c | b94e62b6fbe7f4e08086d0365afc5cff6e0ccafd | gfx plane 2/3 |
| a78-20.35 | 32768 | 9ef863ad | 29f91b5a3765e4d6e6c3382db1d8d8297b6e56c8 | gfx plane 2/3 |
| file | bytes | crc32 | sha1 | role |
|---|---:|---|---|---|
| a71-25.41 | 256 | 2d0f8545 | 089c31e2f614145ef2743164f7b52ae35bc06808 | sprite strip PROM |
| a78-01.17 | 4096 | b1bfb53d | 31b8f31acd3aa394acd80db362774749842e1285 | MC6801 MCU mask ROM ($F000-$FFFF) |
| a78-07.46 | 32768 | 4f9a26e8 | 3105b34b88a7134493c2b3f584729f8b0407a011 | sound Z80 |
| a78-08.37 | 32768 | ae11a07b | af7a335c8da637103103cc274e077f123908ebb7 | sub Z80 |
| a78-09.12 | 32768 | 20358c22 | 2297af6c53d5807bf90a8e081075b8c72a994fc5 | gfx plane 0/1 |
| a78-10.13 | 32768 | 930168a9 | fd358c3c3b424bca285f67a1589eb98a345ff670 | gfx plane 0/1 |
| a78-11.14 | 32768 | 9773e512 | 33c1687ee575d66bf0e98add45d06da827813765 | gfx plane 0/1 |
| a78-12.15 | 32768 | d045549b | 0c12077d3ddc2ce6aa45a0224ad5540f3f218446 | gfx plane 0/1 |
| a78-13.16 | 32768 | d0af35c5 | c5a89f4d73acc0db86654540b3abfd77b3757db5 | gfx plane 0/1 |
| a78-14.17 | 32768 | 7b5369a8 | 1307b26d80e6f36ebe6c442bebec41d20066eaf9 | gfx plane 0/1 |
| a78-15.30 | 32768 | 6b61a413 | 44eddf12fb46fceca2addbe6da929aaea7636b13 | gfx plane 2/3 |
| a78-16.31 | 32768 | b5492d97 | d5b045e3ebaa44809757a4220cefb3c6815470da | gfx plane 2/3 |
| a78-17.32 | 32768 | d69762d5 | 3326fef4e0bd86681a3047dc11886bb171ecb609 | gfx plane 2/3 |
| a78-18.33 | 32768 | 9f243b68 | 32dce8d311a4be003693182a999e4053baa6bb0a | gfx plane 2/3 |
| a78-19.34 | 32768 | 66e9438c | b94e62b6fbe7f4e08086d0365afc5cff6e0ccafd | gfx plane 2/3 |
| a78-20.35 | 32768 | 9ef863ad | 29f91b5a3765e4d6e6c3382db1d8d8297b6e56c8 | gfx plane 2/3 |
| a78-24.52 | 65536 | b7afedc4 | 6e4c8712f1fdf000e231cfd622dd3b514c61a6fd | main Z80 banked ROM, 4 x 16 KiB at $8000 |
| a78-25.51 | 32768 | 2d901c9d | 72504225d3a26212e8f35508a79200eeb91138b6 | main Z80 $0000-$7FFF |
