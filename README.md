# cyberpunk_animport

Turns a Skyrim animation pack (OStim or SexLab) into a NightCityNet animation pack for Cyberpunk 2077: the clips
fitted onto Cyberpunk's bodies and V, the scenes the mod plays, and a zip you install like any mod.

## What you need

| | Where to get it |
|---|---|
| Cyberpunk 2077 | your Steam / GOG / Epic install |
| Python 3.12 with `numpy` and `scipy` (`cupy` too on an NVIDIA card: the body fit is much faster) | python.org, then `pip install numpy scipy` |
| WolvenKit console, 8.20.0 or later, and the .NET 10 runtime | [WolvenKit releases](https://github.com/WolvenKit/WolvenKit/releases): `WolvenKit.Console-<version>.zip` |
| hkxc | [Nexus 166424](https://www.nexusmods.com/skyrimspecialedition/mods/166424), unpacked to `third_party/hkxc/` |
| blender-hkx | [Nexus 118525](https://www.nexusmods.com/skyrimspecialedition/mods/118525?tab=files), unpacked to `third_party/blender-hkx/` |
| 7-Zip, only for a `.7z` input | 7-zip.org |

The Skyrim skeletons (from [XPMSE](https://www.nexusmods.com/skyrimspecialedition/mods/1988)) and the Cyberpunk
skeletons ship in `skeletons/`.

## Port a pack

```powershell
python tools\port.py setup     # finds the game and the tools, writes them to build.local.json
python tools\port.py check     # what is still missing, and where to get it

python tools\port.py run --input "D:\mods\Some OStim Pack" --pack somepack --name "Some OStim Pack"
python tools\port.py run --input "D:\downloads\SomeSexLabPack.7z" --pack slpack --link https://www.nexusmods.com/...
```

- `--input`: the mod as installed (a folder) or as downloaded (`.zip` / `.7z`).
- `--pack`: a short folder name, letters, digits and `_`.
- `--format ostimng|sexlab`: only when the format is not recognised by itself.
- `--name`, `--link`, `--version` (default 0.1.0): what the mod's panel shows for the pack.

A run takes minutes for a few scenes and hours for a big pack. Stopped part way, run the same command again: it
picks up where it stopped. It ends with:

```
done: dist\<pack>-<version>.zip -- install it like any mod; NightCityNet lists it under integrations
```

### What is in the zip

- `archive/pc/mod/<pack>.archive`: the animations, on the NPC body, big and fat bodies and V.
- `archive/pc/mod/<pack>_ncn.archive`: the workspots that play them.
- `archive/pc/mod/<pack>_amm.archive` and an AMM list: every clip as an AMM pose.
- `.../nightcitynet/data/scenes/integrations/<pack>/`: `integration.json`, `clips.json` and one file per scene.
- `licenses/<pack>/`: the pack's own `LICENSE` and `CREDITS.md`, if it has them.

### After the first run

The scene files are yours to edit (under `<packs>/<pack>/.../scenes/integrations/<pack>/`); a rerun keeps them.
To rebuild them from the pack, delete that folder and run again.

What the port reads from each format:

- **OStim**: postures, acts, furniture, moves between scenes and names come from the pack's scene files.
- **SexLab**: each stage is a scene that moves to the next. Postures, acts and furniture are guessed from the
  stage's tags, for two actors where exactly one has a penis; other scenes are left unrated and play as idles.
  SexLab's furniture props are not carried over.

Check the result in game before you publish it.

## Developers

### build.json

`build.json` is shared; `build.local.json` beside it (gitignored) holds this machine's paths and the sources
`port.py run` added.

- `tools`: hkxc, blender-hkx, the Skyrim skeletons, WolvenKit, the game.
- `work`: the shared scratch (rigs, donors, cooked rig JSON).
- `packs`: where packs are written; each source writes `<packs>/<pack>`.
- `sources`: per source its `input`, its own `run` folder, its `pack` and its reader (`inventory`). Two sources
  sharing a run folder or a pack are refused before anything runs.
- `mod`: the nightcitynet checkout, for the mod's own packs' workspots.
- `motionbricks`: generated in-between moves; `false` turns them off.

`python tools/retarget/build_config.py` prints what each source reads and writes.

### Run by hand

```powershell
.\tools\retarget\port_all.ps1                 # every source in build.json
.\tools\retarget\port_all.ps1 -Only ostimng   # one
python tools\retarget\skyrim_port.py <stage> --source <pack>
.\tools\py_test.ps1                           # the tests, no game, seconds
```

The mod's own packs (opensex, ostimng) are released by `tools/opensex/make_release.ps1`, not as integrations.

### Skeletons

- `skeletons/cyberpunk/`: every body a clip is fitted onto (NPC base, big and fat, V's two), each as `.rig`,
  `.rig.json` and `.glb`, and `animset.anims.json`, the empty set the cook fills. Built by
  `tools/retarget/make_skeletons.py`.
- `skeletons/skyrim/`: `skeleton.hkx`, `femskeleton.hkx`, `skeleton242.hkx` (the 242-track XPMSE one).

### Adding a format

A format needs only a reader. It writes the run folder's `manifest.json` (the clips to bake) and
`source-map.json`, the pack's `scenes.json`, and through `scene_list(pack folder, input)` the scene list every later
stage reads (`tools/retarget/scene_list.py`'s docstring is the format). Register it in `scene_list.readers()` and in
`tools/port.py` (`detect` and the reader command). The readers: `skyrim_scenes.py` (OpenSex),
`skyrim_scenes_ostimng.py` (any OStim pack) and `skyrim_scenes_slal.py` (any SexLab pack).

The output layout is NightCityNet's scene graph (`nightcitynet/docs/design/scene-graph.md` §2.1, integrations
§2.1b). The stages: `tools/retarget/README.md`.
