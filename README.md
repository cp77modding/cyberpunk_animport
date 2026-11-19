# cyberpunk_animport

Ports existing animation sets (Skyrim's OpenSex and OStimNG today) onto Cyberpunk 2077's rigs and writes them as
NightCityNet animation packs: cooked `.anims`, an archive, and the scene files the mod reads. Moved out of the
`nightcitynet` repo's `tools/retarget` and `tools/opensex` on 2026-11-19.

## build.json

One file says where everything is:

- `tools`: hkxc, blender-hkx, the Skyrim skeletons, WolvenKit, the game.
- `work`: the shared scratch (rigs, donors, cooked rig JSON).
- `packs`: the CyberpunkAnimations checkout; each source writes `<packs>/<pack>`.
- `sources`: per source its `input`, its own `run` folder and its `pack`. Two sources sharing a run folder or a
  pack, or one inside another, are refused before anything runs.
- `mod`: the nightcitynet checkout, for the two workspot builders that stay there.
- `motionbricks`: generated in-between moves. `false`: their launchers and `pack_transitions.py` stop.

Relative paths are from `build.json`'s folder. `python tools/retarget/build_config.py` prints what each source reads
and writes.

## Run

```powershell
.\tools\retarget\port_all.ps1                 # every source in build.json
.\tools\retarget\port_all.ps1 -Only ostimng   # one
python tools\retarget\skyrim_port.py <stage> --source opensex
.\tools\py_test.ps1                           # the tests, no game, seconds
```

The output layout is NightCityNet's scene graph (`nightcitynet/docs/design/scene-graph.md` §2.1). The stages and
their history: `tools/retarget/README.md`, `nightcitynet/docs/design/opensex-port.md`.
