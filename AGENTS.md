# AGENTS.md

Ports Skyrim animation packs (OStim, SexLab) to NightCityNet packs for Cyberpunk 2077. How to use it: `README.md`.

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
| `tools/retarget/skyrim_contact.py`, `pair_contact.py` | The same on the bodies, with where each touches (`GIF=1`; `docs/kiss_bodies.gif`) |
| `tools/retarget/stick_preview.py` | A few frames of any glb as a still |
| `tools/opensex/templates/` | Workspot and AMM host templates |
| `skeletons/` | Cyberpunk and Skyrim skeletons, shipped |
