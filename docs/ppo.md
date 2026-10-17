# Standard PPO exploration workflow

PPO is the standard **supplemental input generator** for new port exploration. The shared entry point covers
all games registered by `port.py`; Galaga is explicitly deferred until its real Namco 51xx/54xx MCU ROMs are
available. Unregistered work-in-progress boards are not silently treated as finished ports.

Keep the curated `port.py cover` runs, scripted stage/boss/ending tests and existing search recordings. A short
PPO campaign does not replace their coverage. The Kung-Fu Master pilot passed independent port-reference and
picture checks, but its three short evaluations improved logical PC coverage by only 0.55% and stayed on floor 1.

## Commands

From the repository root, install the optional Python 3.13 environment once:

```sh
python3.13 -m venv build/ppo-venv
build/ppo-venv/bin/python -m pip install -r engine/ppo-requirements.txt
venv/bin/python engine/ppo_test.py
```

Prepare/build the port normally first. Then use the same commands for every registered game:

```sh
venv/bin/python port.py ppo kungfum train --steps 4096
venv/bin/python port.py ppo kungfum record --frames 3600 --seed 1
venv/bin/python port.py ppo kungfum verify --seed 1
# Short integration campaign; 256 decisions checks training/recording/replay, not skill:
venv/bin/python port.py ppo all test --steps 256 --frames 2100
```

`test` trains, saves/reloads the model, records, repeats the recording in a fresh native MAME process, and runs
an isolated native Hatari playback. `all` runs serially to bound RAM and SSD use, records failures, and skips the
user-deferred Galaga. A failed port is never reported as tested. `PPO_PYTHON`, `MAME`, `HATARI` and `TOS` override
the optional interpreter and emulator paths. MAME 0.289 and the project's pinned Hatari build are used locally.
`--steps` counts 12-frame decisions and rounds up to a 256-decision PPO rollout. `--frames` includes bootstrap;
it must extend beyond the profile's boot interval. No pretrained universal game-playing model is assumed.

Outputs are under `build/<game>/ppo-standard/`. Existing `play_inputs.bin`, normal PRG/map, simulator builds,
coverage pickles and the original Kung-Fu Master pilot checkpoint are preserved. Policy/profile hashes prevent
loading another game's model or a different action/RAM schema. `port.py ppo ... record` does not publish its
inputs over canonical regression fixtures. Use the existing per-game replay tests before promoting a recording
into those fixtures or adding its paths to translator coverage.

## Contracts and coverage

`engine/ppo_profiles.py` declares each game's MAME set, native SYSTEM/P1 polarity and bit assignments, bootstrap,
RAM ranges, port memory mapping and supported cheats. It uses the existing verified ROM preparation paths for
1943, Trojan, R-Type and Double Dragon. R-Type starts after its existing 400-frame snapshot offset. The profile
is shared by training, native MAME repeatability and Hatari replay. Galaga never substitutes blank MCU ROMs for
real gameplay. The existing R-Type preparation uses stand-ins only for PROMs/PALs that its driver never reads.

The shared model reads two successive RAM observations, stratified to at most 1,024 bytes each. This bounds RAM,
model size and checkpoint storage. Actor and critic each use two 64-unit hidden layers on CPU. Actions are fixed
per-profile direction/button macros, with attacks pulsed two frames on/two frames off. No text/vision model,
network service or search rewinds are involved. Native byte encodings retain the count/SYSTEM/P1 RLE format and
zero terminator. Ports without an older PLAYBACK decoder use a private profile-specific decoder during audits.

Coverage rewards newly executed **main CPU logical instruction-start addresses** after bootstrap. One-shot
MAME debugger breakpoints count actual execution. For Z80/6809 boards the profile's ROM ranges are instrumented;
R-Type uses statically translated V30 instruction starts to avoid allocating a breakpoint at every physical ROM
byte. Consequently the R-Type metric cannot discover previously unknown instruction starts. ROM banks, secondary
CPUs, edges and data accesses are not separate identities in this metric. Do not call it complete code coverage.
Reward is 0.1 per globally new PC, 0.002 per episodically new PC, minus 0.01 per decision. The earlier Kung-Fu
Master pilot used a larger, game-specific observation and additional progress/death rewards; its weights are not
interchangeable with the shared profile model.

## What verification establishes

The native MAME repeat run must match every captured RAM state and first-execution PC set byte for byte.
The private Hatari executable retains rendering, consumes controls by arcade tick, captures RAM at completed-tick
boundaries, and writes a rolling digest of **every consumed SYSTEM/P1 pair**. Missing, reordered or partial
checkpoints, different input digests, crashes and timeouts fail verification. Private source copies and temporary
builds are removed automatically. Production runtime source and executables are not patched by this process.

Native MAME-versus-Hatari RAM differences are reported at the earliest sampled checkpoint. The original boards
and ports have different schedules, boot shortcuts and sometimes random-number sources. Such differences alone
are not translation failures. The shared integration check establishes reproducible MAME training transitions
and native Hatari input transport/completion; it does **not** establish lock-step reference or picture equivalence
for every new port adapter. Those remain the per-game independent logic/render tests. Kung-Fu Master's separate
pilot audit provides that stronger comparison, with exact dead-stack exclusions, for its tested recordings.

## SSD budget

Only trained checkpoints, tiny RLE inputs, metrics and gzip-compressed MAME snapshots are retained by default.
Native Hatari programs, objects and raw capture buffers live in temporary directories. `--keep-captures` explicitly
retains a compressed diagnostic capture. Models are trained serially, and failed attempts do not trigger downloads
of unrelated language models. No global cache, ROM archive, normal build or unrelated work is deleted.

The retired Kev experiment's downloaded weights, checkout and unneeded MLX/language-model packages were removed.
The dedicated PPO environment retains Torch, Gymnasium and Stable-Baselines3; its interpreter is `build/ppo-venv`.
Small historical measurement reports remain available as evidence. Local adapter results are recorded in
[ppo-rollout-results.json](ppo-rollout-results.json).
