# cyberpunk_animport

Ports existing animation sets (Skyrim's OpenSex and OStimNG today) onto Cyberpunk 2077's rigs and writes them as
NightCityNet animation packs: cooked `.anims`, an archive, and the scene files the mod reads. Moved out of the
`nightcitynet` repo's `tools/retarget` and `tools/opensex` on 2026-11-19.

## build.json

One file says where everything is, with `build.local.json` beside it holding this machine's tool paths, source
inputs and the sources added here:

- `tools`: hkxc, blender-hkx, the Skyrim skeletons, WolvenKit, the game.
- `work`: the shared scratch (rigs, donors, cooked rig JSON).
- `packs`: the CyberpunkAnimations checkout; each source writes `<packs>/<pack>`.
- `sources`: per source its `input`, its own `run` folder and its `pack`. Two sources sharing a run folder or a
  pack, or one inside another, are refused before anything runs.
- `mod`: the nightcitynet checkout, for the two workspot builders that stay there.
- `motionbricks`: generated in-between moves. `false`: their launchers and `pack_transitions.py` stop.

Relative paths are from `build.json`'s folder. `python tools/retarget/build_config.py` prints what each source reads
and writes.

## Port a pack

```powershell
python tools\port.py setup                                  # finds the game and tools, extracts the rigs
python tools\port.py check                                  # what is still missing, and where to get it
python tools\port.py run --input <pack folder, .zip or .7z> --pack <name>
```

`run` unpacks the input, recognises its format, adds it as a source in `build.local.json`, reads it and runs every
stage; run it again to resume. This machine's paths live in `build.local.json` (gitignored), never in `build.json`.

## Run by hand

```powershell
.\tools\retarget\port_all.ps1                 # every source in build.json
.\tools\retarget\port_all.ps1 -Only ostimng   # one
python tools\retarget\skyrim_port.py <stage> --source opensex
.\tools\py_test.ps1                           # the tests, no game, seconds
```

## The Cyberpunk skeletons

`skeletons/cyberpunk/` holds every skeleton a clip is fitted onto (the NPC base, big and fat bodies and V's two),
each as the game's `.rig`, its json and its armature `.glb`, and `animset.anims.json`, the empty animation set the
cook fills. Built from the game's rigs by `tools/retarget/make_skeletons.py`; a port reads nothing else of the game's
rigs.

`skeletons/skyrim/` holds the Skyrim skeletons a clip is decoded against: `skeleton.hkx`, `femskeleton.hkx` and
`skeleton242.hkx` (the 242-track XPMSE one). build.json points `tools.skeletons` at it.

## Adding a source

A source needs only a reader. It writes the run folder's `manifest.json` (the clips to bake) and `source-map.json`,
the pack's `scenes.json` (its own record) and, through `scene_list(pack folder, input)`, the pack's
`scene-list.json`. Every stage after it reads only those, and `tools/retarget/scene_list.py`'s docstring is the
format. A run checks the manifest before it starts and the scene list before writing; either names the first rows it
refuses. Register the reader in `scene_list.readers()` under the name the source's `inventory` gives in build.json.
`skyrim_scenes.py` (OpenSex), `skyrim_scenes_ostimng.py` and `skyrim_scenes_slal.py` (SexLab, an example) are the
three there are.

The output layout is NightCityNet's scene graph (`nightcitynet/docs/design/scene-graph.md` §2.1). The stages and
their history: `tools/retarget/README.md`, `nightcitynet/docs/design/opensex-port.md`.
