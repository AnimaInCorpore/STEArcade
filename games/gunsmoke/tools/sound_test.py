"""Gun.Smoke's STE sound player (engine/rt/capsnd.s, the --sim build) against engine/capsnd.py's model, tick by tick
(engine/capsnd_test.py: random effects, tunes and stops).  The model against the sound driver itself: tools/sound.py check.

    python sound_test.py [ticks]
"""
import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "engine"))
import capsnd_test

if __name__ == "__main__":
    sys.exit(capsnd_test.run("gunsmoke", int(sys.argv[1]) if len(sys.argv) > 1 else 20000))
