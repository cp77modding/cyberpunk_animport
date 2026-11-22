# AGENTS.md

Ports Skyrim animation packs (OStim, SexLab) to NightCityNet packs for Cyberpunk 2077. How to use it: `README.md`.
Every step in detail, with the diagram: `docs/pipeline.md`.

## How it works

`tools/port.py run` drives everything; each step is a separate script reading the files the step before wrote, so
any step can be run, fixed and rerun alone.

| Step | Script | Reads | Writes |
|---|---|---|---|
| read | `skyrim_scenes_ostimng.py` / `skyrim_scenes_slal.py` (`skyrim_scenes.py` for OpenSex) | the input pack's scene files | run folder: `manifest.json`, `scenes.json`, `source-map.json`; pack folder: `scene-list.json` |
| clips | `skyrim_port.py clips` | `.hkx` through hkxc, blender-hkx | `decoded/<hash>.npz` (per source clip), `clips/<set>/<clip>.npz` (per body) |
| pair fit | `pair_reach.py`, `pair_batch.py` (`pair_contact.py`) | `clips/`, Skyrim's bodies | `pair_shift.json`, `mesh/<set>/<clip>.npz` |
| glbs, cook, bodies, verify, pack | `skyrim_port.py all` | `clips/`, `mesh/` before `clips/` | `glb/`, `depot/`, `<pack>.archive`, `clips.json` |
| scenes | `tools/opensex/make_integration.py` (`scene_files.py`) | `scene-list.json`, `clips.json` | the scene files, `integration.json`, `<pack>_ncn.archive` |
| AMM | `tools/opensex/make_amm_poses.py` | the cooked sets | `<pack>_amm.archive`, AMM's `.lua` |
| zip | `tools/retarget/pack_release.py` | the pack folder as built | `dist/<pack>-<version>.zip` |

Where things are: the run folder is `work/runs/<pack>` (scratch, gitignored); the pack folder is
`<packs>/<pack>` (build.json's `packs`), laid out as the game's root, which is what the zip holds.

What to know before changing a step:

- **A manifest row** is one clip on one body: `clip`, `sex` (the body it is baked for), `srcSex` (the Skyrim
  actor's), `rig`, `npcSet` / `playerSet` (depot paths of its `.anims`), `file` (the `.hkx`), `skeleton`. A scene's
  side can play on either body, so most clips have an `m` row and an `f` row.
- **A set** is one `.anims` file. Its name ends with the body: `_ma` / `_wa` (NPC man, woman), `_pma` / `_pwa` (V).
  The big and fat bodies sit in folders beside, same names.
- **The scene list** (`tools/retarget/scene_list.py`'s docstring is the format) is the one shape every reader writes
  and every later step reads. A new format is a new reader and nothing else ("Adding a format" in `docs/pipeline.md`).
- **Cast order is man first.** The game casts a pair man first; SexLab lists the woman first, so its reader reorders
  (`man_first`). Breaking this gives "does not fit the cast mf" in the game's log.
- **Which clip each actor plays** in the pair fit: `pair_cast.py`. OpenSex and OStim by clip name (`<base>_0`,
  `<base>_1`), any other pack from its `scene-list.json`.
- **Skipping:** every step skips output newer than its input (`--all`, `REDO=1` redo). After changing a step's code,
  delete its output for the clips you test or the old result is reused.
- **The scene files are written once**, then hand-edited by players; `make_integration.py --force` rewrites them.
- **Scene ids** are `integrations.<pack>.<...>`, and the mod finds a scene file by its path under `data/scenes/`.

How to check a change, cheapest first:

1. `tools\py_test.ps1` (seconds).
2. One clip through the step you changed, read its output or log. For the pair fit: `MATCH=<base> MESH=1 SAVE=1
   HANDFIT=1 MESH_SKIN=1 python pair_batch.py <pack> 1`, the log under `work/contact/batch/<pack>/`, and
   `python skyrim_contact.py <base> <pack>` for Skyrim's own contacts to compare with.
3. Pictures: `compare_gif.py` (stick figures), `pair_contact.py` with `GIF=1` (bodies).
4. A cut-down pack through `port.py run`, then the game ("Build a full zip and play it in game" below).

## Rules

- **General tool, not one pack.** Every change works for any OStim or SexLab pack. Never special-case a pack by
  name outside the mod's own two (`opensex`, `ostimng`, `BUILTIN` in `tools/port.py`).
- **The mod's own packs do not move.** A change to a reader or stage that opensex or ostimng also run must leave
  their output byte-identical: save the output before the edit, compare after.
- **Machine paths go in `build.local.json`** (gitignored), never in `build.json`, a doc or code. Code reads them
  through `build_config.load()`; a `.ps1` through `python tools\retarget\build_config.py --get tools.<name>`.
- **No third-party mod's data ships or is read at build time** beyond the input pack itself. Workspots and AMM
  hosts are built from `tools/opensex/templates/`.
- **Test on a few scenes, not a whole pack.** Cut the input to 2-3 scenes, run `port.py run` on that, compare the
  output with opensex's scene files, then remove the test source from `build.local.json` and its folders
  (`<packs>/<pack>`, `tools/retarget/work/runs/<pack>`, `build/integration/<pack>`).
- **Heavy runs take nightcitynet's lock** (`<mod>\tools\game_lock.ps1 take -Name <session> -What ...`; `<mod>` is
  build.json's `mod`) and
  release it the moment the run ends. No game is needed.
- **Tests**: `tools\py_test.ps1`. A new test goes into its list; all of them pass.
- **Git**: commit only when the user says so, with `git commit -o <paths>`. No AI attribution in any commit.
- **Plain words** in docs, comments and messages.

## Build a full zip and play it in game

1. **Build.** `python tools\port.py run --input <mod folder|zip> --pack <name> --format sexlab|ostimng --name "<shown name>"`
   makes `dist\<pack>-<version>.zip`. Anub's 500 MB pack (1546 clips) took about 25 minutes.
   - A rerun keeps scene files already written: `tools\opensex\make_integration.py --pack <name> --force` rewrites them.
   - A zip that exists is not overwritten: pass `--version`, or run `tools\retarget\pack_release.py <version> --packs <name>`.
   - Only the zip step after a stopped run: `make_integration.py --force`, `make_amm_poses.py --packs <name>`,
     `pack_release.py`; the pack stage skips an archive already newer than every set.
2. **Install as its own MO2 mod**, as a player would: unpack the zip into a new folder under `<MO2>\mods\`, never
   into `nightcitynet`'s. Check first that no file in the zip exists in another mod. The user ticks it in MO2's
   profile (F5 to refresh); never edit `modlist.txt` while MO2 runs. A running game holds the old archives open, so
   replace them after it quits.
3. **Play it** under nightcitynet's lock: an archive mounts only at start, so restart with
   `<mod>\tools\game_e2e.ps1 -NoQuit -Name <session> -Save <save>`. Two copies of ours
   (`AIControl.SpawnCopyNearV`), then `NCN.StartScene({ man, woman }, 'integrations.<pack>.<scene>')`, `MoveScene` to the
   next stage, `StopScene`. The cast goes man first.
4. **What the brain log must say:** `[scenes] N scenes loaded, 0 problem(s)`; `tableau mounted` on
   `ncn\workspots\integrations\<pack>\ncn_<pack>_2p.workspot`, not `ncn_scenes_2p`; `plays '<the scene's clip>'` for
   each body, and no `NEVER landed`. Hand the game over or quit and release the lock the moment that is read.

## Map

| Path | What |
|---|---|
| `tools/port.py` | The one command: `setup`, `check`, `run` |
| `tools/retarget/build_config.py` | `build.json` + `build.local.json` merged; every path a stage reads |
| `tools/retarget/skyrim_scenes*.py` | Readers: OpenSex, any OStim pack, any SexLab pack |
| `tools/retarget/skyrim_port.py` | The stages after reading: decode, fit, cook, pack (`all` runs them) |
| `tools/retarget/scene_list.py` | The scene-list format every reader writes |
| `tools/opensex/scene_files.py` | Scene lists -> NightCityNet scene files |
| `tools/opensex/make_integration.py` | A ported pack as an integration: scene files, `integration.json`, workspots |
| `tools/opensex/make_amm_poses.py` | The AMM pose list and host |
| `tools/retarget/pack_release.py` | The release zip |
| `tools/retarget/compare_gif.py` | A scene's Skyrim clips beside the port, stick figures, as a GIF (`docs/kiss.gif`) |
| `tools/retarget/skyrim_retarget.py`, `retarget_glb.py` | A Skyrim clip onto the NPC skeleton; an NPC set onto V's |
| `tools/retarget/pair_reach.py` | Oral reach: the giver slid to Skyrim's distance (`pair_shift.json`) |
| `tools/retarget/pair_batch.py`, `pair_contact.py` | The pair fit over a pack, and one clip: report, GIF, `SAVE=1` |
| `tools/retarget/pair_cast.py` | Which clip each actor plays, for any pack |
| `tools/retarget/interaction_mesh.py`, `mesh_skin.py`, `hand_fit.py` | The fit: bodies kept touching; skin points; palms on skin |
| `tools/retarget/skyrim_contact.py`, `skyrim_body.py`, `body_area_map.py` | Skyrim's bodies on a clip, and body areas on both |
| `tools/retarget/skyrim_contact.py`, `pair_contact.py` | The same on the bodies, with where each touches (`GIF=1`; `docs/kiss_bodies.gif`) |
| `tools/retarget/stick_preview.py` | A few frames of any glb as a still |
| `tools/opensex/templates/` | Workspot and AMM host templates |
| `skeletons/` | Cyberpunk and Skyrim skeletons, shipped |
