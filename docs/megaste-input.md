# Mega STE input devices: port contract

The Mega STE retains the keyboard and standard Atari mouse/joystick interface.
Its detached keyboard has mouse/joystick port **0** and joystick port **1**,
both 9-pin connectors. It does **not** have the 1040STE's two enhanced 15-pin
joystick ports. Do not infer those ports from the word STE in the machine name.

This was rechecked against Atari's [Mega STE owner's manual,
C302016-004 Rev A](https://www.atariworld.org/files/docs/C302016-004-REV-A.pdf):
"Tastatur und Maus" (PDF page 12), "Joysticks" (PDF page 17), and appendix F's
mouse/joystick 0 and joystick 1 pinouts (PDF page 123). Its specification and
connector inventory show the standard keyboard ports, not enhanced connectors.
The original technical [STE FAQ by The Paranoid/Paradox](https://github.com/Number0000009/atari-wiki/blob/master/Atari%20STE%20FAQ%20compiled%20by%20The%20Paranoid%20Paradox.txt)
explicitly distinguishes 1040STE/Falcon enhanced ports from Mega STE/TT.
Some third-party Mega STE specification lists copy the enhanced-port feature
incorrectly; the Atari connector documentation is the basis for this contract.

| Device/path | Mega STE expectation |
|---|---|
| Keyboard | Available through the IKBD/ACIA path; coin/start must work independently of any gamepad |
| Standard Atari mouse | Available on port 0; a game's choice not to use mouse input is separate from hardware support |
| Standard one-button digital joystick | Available on port 1; port 0 can serve a second joystick when not used by the mouse |
| Native Jaguar pad / PowerPad on an STE enhanced connector | Unavailable: no corresponding 15-pin connectors |
| Analogue paddles through the STE enhanced ports | Unavailable through that interface |
| Special controller/adapter | Requires its own supported protocol; do not assume an adapter provides native enhanced-port capabilities |

Standard joysticks do not supply Jaguar Option/Pause/keypad or three separate
fire buttons. In Gun.Smoke the joystick fire maps to the straight shot; keyboard
keys still provide coin, start and the left/right shots. Mouse packets are
explicitly disabled by that game while playing. This is not a broken mouse or
an omitted Mega STE input device.

`engine/rt/jagpad.s` already implements the required exclusion: `_MCH ==
$00010010` leaves `jp_present` zero and returns **before** reading or writing
`$FF9200/$FF9202`. Readable or floating values in that address area do not prove
that enhanced controllers exist. Merging such values as pressed pad buttons
can hold coin/start continuously and hide the real keyboard edges.

The focused Gun.Smoke build records `jp_present`, framed key make/break events
and standard-joystick packet OR masks in `GUNTEST.TXT`. Mega STE must report
pads disabled. No joystick events in a keyboard-only run mean **not exercised**,
not a hardware failure. The host joystick decoder test checks all 256 input
bytes against the native conversion routine; that does not establish that a
physical joystick or the full serial packet transport was exercised.
