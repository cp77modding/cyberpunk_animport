# AGENTS.md

Ports Skyrim animation packs (OStim, SexLab) to NightCityNet packs for Cyberpunk 2077. How to use it: `README.md`.

## Rules

- **General tool, not one pack.** Every change works for any OStim or SexLab pack. Never special-case a pack by
  name outside the mod's own two (`opensex`, `ostimng`, `BUILTIN` in `tools/port.py`).
- **The mod's own packs do not move.** A change to a reader or stage that opensex or ostimng also run must leave
  their output byte-identical: save the output before the edit, compare after.
- **Machine paths go in `build.local.json`** (gitignored), never in `build.json`, a doc or code.
- **No third-party mod's data ships or is read at build time** beyond the input pack itself. Workspots and AMM
  hosts are built from `tools/opensex/templates/`.
- **Test on a few scenes, not a whole pack.** Cut the input to 2-3 scenes, run `port.py run` on that, compare the
  output with opensex's scene files, then remove the test source from `build.local.json` and its folders
  (`<packs>/<pack>`, `tools/retarget/work/runs/<pack>`, `build/integration/<pack>`).
- **Heavy runs take nightcitynet's lock** (`nightcitynet\tools\game_lock.ps1 take -Name <session> -What ...`) and
  release it the moment the run ends. No game is needed.
- **Tests**: `tools\py_test.ps1`. A new test goes into its list. `retarget\test_interaction_mesh` fails already.
- **Git**: commit only when the user says so, with `git commit -o <paths>`. No AI attribution in any commit.
- **Plain words** in docs, comments and messages.

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
| `tools/opensex/templates/` | Workspot and AMM host templates |
| `skeletons/` | Cyberpunk and Skyrim skeletons, shipped |
