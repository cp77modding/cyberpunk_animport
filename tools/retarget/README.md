# retarget: Skyrim clips onto Cyberpunk's bodies and V's

The tools behind `tools/port.py`: decode a Skyrim clip, fit it onto the Cyberpunk skeletons in
`skeletons/cyberpunk/`, cook it into an `.anims` set and check the cook. Porting a pack: the root `README.md`; the
steps in order: `docs/pipeline.md`. This file is the detail below them: the skeletons, what V needs, the toolchain,
the Linux bake and every file here. Links to `docs/design/`, `docs/research/` and `docs/guides/` are in the
nightcitynet repo, not this one.

`work/` is scratch: gitignored, rebuilt by the stages, never committed.

## The skeletons

V's skeletons (`player_man_skeleton`, `player_woman_skeleton`, 152 bones) hold every bone of the NPC rig
(`man_base`, `woman_base`, 71 bones) with the same names and parents; the 81 extras are rig controls and IK
targets. So a clip is moved between them by name, with no bone map. `compare_rigs.py` diffs two serialized rigs.
The big and fat NPC rigs: `man_big` and `man_fat` have `man_base`'s 71 bones; `woman_big` and `woman_fat` have
`woman_base`'s plus muscle bones left at rest, and lack `LeftEye`, `RightEye` and `reference_joint`, so a clip
baked onto them drops those tracks (`retarget_glb.py --drop-missing`).

### What V needs from a baked clip

Five faults, stacked — each fix alone still left V wrong. The evidence is the research doc, "What V needs from a
baked clip".

| fault | seen as | fix |
|---|---|---|
| WolvenKit 8.18.1 always cooks `animAnimationBufferCompressed`; V's own clips are `animAnimationBufferSimd` | the right start, then crazy movement | the SIMD encoder (8.19.1 nightly), asked for per clip by `optimizationHints.preferSIMD` |
| a still track written as two STEP keys is cooked to const keys | T-pose | two LINEAR keys |
| V's IK targets and pole vectors left at rest pull the limbs back to rest | T-pose | each target follows its bone at the rest offset (`IK_FOLLOW`) |
| the COG control and `legs_ik_A_master` left at standing rest (the NPC rig has neither) | a lying clip plays with the torso upright | both follow Hips at the rest offset (`IK_FOLLOW`); the targets below them are placed after |
| the `Torso_Hips_*` / `Torso_Chest_*` chains under the COG left at rest | the thrust in the whole upper body, V too high, the hands riding the back | their ends follow Hips and Spine3 at the rest offset, as in vanilla's dollhouse clip (`IK_FOLLOW`) |

WolvenKit's SIMD cook sizes a clip `ceil(duration × 30)` frames — one short of a 30 fps source — and
resamples, which put a foot 1.5° off. `retarget_glb.py` stretches each clip 0.1 ms, so the frame count
holds and every key lands on a cooked frame (moving only the last key still left a fast arm 0.17° off).

### Toolchain

The cook needs a WolvenKit with the SIMD encoder (PR #2833): any release from 8.20.0, the console zip
(`WolvenKit.Console-<version>.zip`) unpacked, set as build.local.json's `wolvenkit_cook` or `-WolvenKitCook <dir>`.
`wk_anims` is built for .NET 10, so it loads 9.x (which needs .NET 10) and the older 8.x builds alike; 9.1.1 and an
8.19.1 nightly both cook and verify the same set at 0.000 deg.

`-WolvenKit` (the source export) can stay the release CLI. `retarget.ps1` refuses to run without a
`-WolvenKitCook` build, and after the cook serializes the set and fails unless every buffer is
`animAnimationBufferSimd` — the pose check cannot see a compressed one.
A naive local-rotation copy is off by 180° (`reference_joint`'s bind is flipped between the rigs).
An earlier version carried each bone's change from its own rig's rest pose instead; V's skeleton rests
with the upper arm 47° and the forearm 68° from `woman_base`'s, so every arm pose came out that far off
(hands ~45 cm wide).

What this does **not** answer: contacts. Target lengths mean V's 38 mm longer female arm reaches
38 mm further — a hand on a partner's shoulder lands off it. The IK pass above only keeps V's IK
targets on V's own bones; it does not reach for a partner.

A bare `.rig` has no glb exporter, so `rig_glb.py` builds each armature in `skeletons/cyberpunk/` from the rig json
(`--check` against a WolvenKit-exported one: rests within 0.04°, lengths exact).

## Skyrim clips — the OpenSex port, `skyrim_port.py`

OpenSex (OStim NG, CC BY-SA 4.0) baked whole onto `man_base` / `woman_base` and V's skeletons. The output and its
credits live in the pack repo, `CyberpunkAnimations\opensex` (`depot/`, `archive/pc/mod/opensex.archive`,
`scenes.json`, `source-map.json`); this folder keeps the tools, and the pack holds no `.hkx`, no Skyrim skeleton
and no converter.

```
python tools\retarget\skyrim_port.py all            # inventory clips glbs cook pack, changed sets only; or one stage by name
python tools\retarget\skyrim_port.py all --verify   # with the check: after a WolvenKit or retarget change only
python tools\retarget\skyrim_port.py clips --only lybkne
```

| step | how |
|---|---|
| which clip is whom | `skyrim_scenes.py`: a scene's actor with a `penisAngle` is male, but a one-actor scene takes its sex from its id (every solo actor carries one); a clip cast as both sexes goes on both bodies; a clip is `<anim id>_<position>`. A clip no scene names (77: redressing, a few unused) is baked on both bodies. One set per folder under `anim/OpS/` and body. OpenSex's three woman-and-woman scenes, deleted upstream in `140a6680` while their clips stayed, are read back from the commit before (`RESTORED`, cast and name given there), and replace the OPrivacy redirect that took over the cunnilingus file |
| tagfile → packfile | OpenSex ships Havok 2010 **tagfile** XML, which hkxc cannot read. `skyrim_tagfile.py` writes the five objects of a spline clip as hkxc's packfile XML; a member a tagfile omits is its default |
| decode | hkxc → 32-bit packfile → blender-hkx `unpack` (resampled to 30 fps). Clips carry 242 tracks (99 bones + physics), so the skeleton is padded to 242 by `skyrim_skeleton.py`, or blender-hkx writes zero frames. Sources: `skeletons/skyrim/` |
| retarget | `skyrim_retarget.py`: per mapped bone a fixed offset from the Skyrim rest, swung to aim where the target's bone aims; Skyrim Z-up/+Y to glTF Y-up/−Z; hips travel scaled by hip height. Spine2, Neck1 and the metacarpals stay at rest |
| oral reach | `pair_reach.py`, run before `glbs`: for each oral act (`acts` in the pack's scene files) the giver's head to the target's pelvis, Skyrim against ours; the flat slide that matches is written to `<port>/pair_shift.json` and `glbs` moves that clip's Hips by it. Our shorter torsos left most givers 4–10 cm short. Not slid: within 2 cm, over 15 cm, or a source reach over 0.6 m (the act's roles are wrong) |
| V | `retarget_glb.py` on the NPC set's glb |
| cook | `wk_anims --list`: every set in one process, against `work/rigs/rigs.archive` (our four rigs, packed once) instead of the game's archives; each rig's empty container is built once into `work/empty_anims/` |

### Which stage needs Windows

Only the decode does, once per source clip (`decoded/`, shared by both bodies). The WolvenKit stages run on Linux
under .NET 10 (`dotnet WolvenKit.CLI.dll`, `libkraken.so` from `WolvenKit.Core/lib` beside it); `skyrim_port.py`
picks the `.dll` off Windows. The pod run: `pod/bake_bundle.py <zip>` here (the sets whose clips changed),
`pod/run_bake.sh` on the pod (glbs and cook of both packs), `bake_bundle.py --unpack <results.zip>` here, then `pack`
here, since it writes the pack repo. The pod's own key may stop its pod (`runpodctl stop pod`, tested 2026-11-17)
but not read it, so `run_bake.sh`'s timer stops the pod itself; a pod made, run and terminated is in
`docs/design/opensex-port.md` §9.6, "The pod".

| stage | tool | Windows needed | Linux, measured |
|---|---|---|---|
| inventory | Python | no | — |
| clips (decode) | `hkxc` + `blender-hkx` | **yes** | — |
| glbs (retarget) | Python, numpy | no | 73 OpenSex npc sets and their V sets under a minute, 14 vCPU (2026-11-10) |
| cook: empty template, once per rig | WolvenKit.CLI `convert deserialize` | no | 9.6 s, byte-identical |
| cook | `wk_anims` + `rigs.archive`, one process per worker | no | 146 OpenSex sets in 159 s, 88 OStimNG in 80 s, 14 processes; worst 0.000° against the Windows cook (Kraken, not Oodle) |
| verify (`--verify` only) | WolvenKit.CLI export | not tried | — |
| pack | WolvenKit.CLI `pack` | no | 7.3 s, every packed file byte-identical |
| `clips.json` merge | Python | no | — |

Checked: OpenSex's `_Cr-MountedGrind_S2_1` through this path decodes byte-identical to the OARE copy that
played in game on 2026-10-27, bar OpenSex's two foot events, and its glb is byte-identical to the tested one.

## Files

| | |
|---|---|
| `extract.ps1` | the game's rigs → `work/{cr2w,json,glb}`, then the rig bindings and the bone diff |
| `make_skeletons.py` | `skeletons/cyberpunk/` from the extracted rigs |
| `compare_rigs.py` | bone-name + parenting diff between two serialized rigs |
| `retarget.ps1` | the baked route, one animset end to end → `work/depot/<DepotPath>` |
| `retarget_glb.py` | glb → glb onto another skeleton, IK targets driven, V's clip settings; numpy only |
| `anims_json.py` | `prep` the container |
| `wk_anims/` | .NET 10 bridge to WolvenKit's anims importer, loaded from the WolvenKit dir it is given (4th arg) or `NCN_WOLVENKIT_DIR` |
| `verify_retarget.py` | cooked vs source, per clip, bone and IK target; fails over `--max-deg` / `--max-cm` |
| `rig_glb.py` | a rig json as the armature WolvenKit would export; `--check` against an exported one |
| `test_retarget_glb.py`, `test_rig_glb.py` | synthetic rigs, in `tools/py_test.ps1` |
| `skyrim_port.py` | the OpenSex port, stage by stage ("Skyrim clips") |
| `skyrim_scenes.py`, `skyrim_tagfile.py`, `skyrim_skeleton.py`, `skyrim_retarget.py` | its inventory, tagfile reader, skeleton padding and retarget |
| `test_skyrim_port.py` | those four on synthetic input, in `tools/py_test.ps1` |
| `pair_reach.py`, `test_pair_reach.py` | an oral giver slid to the source's reach ("oral reach" above); the test is in `tools/py_test.ps1` |
| `skyrim_contact.py`, `pair_contact.py` | which partner area each hand, mouth and genital touches: on Skyrim's bodies, then on ours on the retarget; `MESH=1` runs the clip through the interaction mesh, `GIF=1` draws Skyrim / retarget / after. Output in `work/contact/` (nightcitynet `docs/design/opensex-port.md` §9.6) |
| `pair_cast.py`, `test_pair_cast.py` | which clip each actor of a cast plays: OpenSex and OStim by clip name (`<base>_0`, `<base>_1`), any other pack from its `scene-list.json` |
| `interaction_mesh.py`, `test_interaction_mesh.py` | contacts kept through other proportions: Ho, Komura, Tai 2010 as written, then back to our rotations; the test is in `tools/py_test.ps1`. Solves on the GPU with `pip install nvmath-python[cu12]` (cuDSS), else SuperLU on one core |
| `mesh_skin.py` | `MESH_SKIN=1`: his palm and her buttocks in the mesh sourced from Skyrim's own skin (nightcitynet `docs/design/opensex-port.md` §9.6) |
| `hand_fit.py`, `test_hand_fit.py` | `HANDFIT=1`: after the mesh, his palm turned and reached onto her skin where Skyrim's is, the elbow kept on its own side; a clip whose elbow snaps fails. The test is in `tools/py_test.ps1` |
| `pack_release.py` | a release zip as built, `dist/<name>-<version>.zip` (`--packs`; opensex and ostimng by default): archive/ and bin/ at the game root, licences under `licenses/<pack>/`; refuses a version already built |
| `pod/` | the sweep on a RunPod GPU: `pod_bundle.py` (the bundle, run here), `setup.sh`, `pod_run.py` (any script from the bundle), `run_sweep.sh` (both packs, a self-stop timer); the port's glbs and cook: `bake_bundle.py` (bundle, and `--unpack` the results), `run_bake.sh` |
| `pair_batch.py`, `test_pair_batch.py` | `pair_contact.py` over every clip of a pack with the cast sizes in `ACTORS` (2 by default; `ACTORS=2,3`), N clips at once (`MESH=1 python pair_batch.py ostimng 4`); a log per clip in `work/contact/batch/<pack>/` |
| `mb_transition.ps1` | a generated transition between two clips, export to cooked `.anims` and checked; `-Preview` renders the body (nightcitynet `docs/guides/retarget-an-animation.md` §5) |
| `mb_transition.py` | the model call, run by that script from the MotionBricks clone's venv |
| `mb_batch.ps1`, `mb_batch.py`, `mb_gap.py`, `test_mb_batch.py` | a list of moves, both actors at one length, cooked in one launch, with the capsule gap between the bodies; the test is in `tools/py_test.ps1` |
| `mb_foot.py` | planted feet and floor lift on every generated clip, from the model's foot contacts; tested in `test_mb_batch.py` |
| `mb_help.py`, `mb_help.json` | the hard moves' help table: a move stays a cut, plays a plain blend, passes through an authored pose, or plays an authored stretch; tested in `test_mb_batch.py` |
| `mb_player.ps1` | bakes the batch's `gen_*` sets onto V's skeletons and fills `player` in `gen_results.jsonl` |
| `pack_transitions.py`, `test_pack_transitions.py` | the generator's accepted moves as transition scenes: into the `ncngen` test pack (a copy of A moving through it), or `--into-source` with A's move rewired; the test is in `tools/py_test.ps1` |
| `mb_all.ps1` | the whole run in one command: move list, generate and cook, V's bake, pack, workspots, GIFs |
| `mb_moves.py`, `test_mb_moves.py` | `moves.csv`: every move between two two-actor scenes, a rewired one read through its transition |
| `mb_gif.py`, `test_mb_gif.py` | each move as a stick-figure GIF, A's end, the transition and B's start, and `work/run/gifs/index.html`, worst overlap first |
| `mb_soma.py`, `test_mb_soma.py` | the Cyberpunk rig to SOMA and back, and the seam and speed limits; the test is in `tools/py_test.ps1` |
| `mb_preview.py`, `blender_transition.py` | A's end + the transition + B's start as one glb, rendered on a body per frame and made a gif |
| `stick_preview.py` | stick figures of glbs side and front at a few frames, one colour each, a clip picked by `glb:clip` — a retarget checked without Blender |

`work/json/` is where a rig reference is readable — the binding is not visible in the binary, and
the json round-trips byte-identical, so it is safe to edit and deserialize back.
