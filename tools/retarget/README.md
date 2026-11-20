# retarget — putting a man_base pose on V's own body

Workbench for the AnimDouble question: **can V perform a PoNC pose without a stand-in?**

The findings, written up: **`docs/research/player-rig-retarget.md`**. This file is the operating
manual; that one is the argument and the evidence. `docs/design/anim-actors-and-events.md` covers what
the double costs us in identity and events.

For the commands to bake one set for V or another NPC rig and add its workspot row, see
[`docs/guides/retarget-an-animation.md`](../../docs/guides/retarget-an-animation.md).

```
powershell -File tools\retarget\extract.ps1     # game archives + PoNC -> work/
python      tools\retarget\make_retarget_mod.py # the one-field probe mod (below)
```

`work/` is CDPR's and PinkyDude's data — gitignored, rebuild it, never commit it.

## There is no TPP_Player_Cutscene rig

That is why you could not find one. `Character.TPP_Player_Cutscene_Male|Female` is a **TweakDB
character record**, not a skeleton. Its entity is
`base\characters\entities\player\player_ma_tpp_cutscene.ent`, and that entity binds:

| body | entity | rig |
|---|---|---|
| V, playable | `player_ma_fpp.ent` / `player_wa_fpp.ent` | `player_man_skeleton.rig` / `player_woman_skeleton.rig` |
| **the double** | `player_ma_tpp_cutscene.ent` / `player_wa_tpp_cutscene.ent` | **`man_base.rig` / `woman_base.rig`** |
| every NPC | — | `man_base.rig` / `woman_base.rig` |
| PoNC clips | `*_ma.anims` / `*_wa.anims` | `man_base.rig` / `woman_base.rig` |

**The double is already on man_base.** Retargeting man_base → "the TPP_Player_Cutscene rig" is a
no-op: they are the same skeleton. The double exists *because* it is man_base — that is the whole
trick, CDPR's own third-person V happens to be built on the NPC rig.

The retarget that would actually delete the double runs the other way:
`man_base` → `player_man_skeleton`, onto V's real body.

## The two skeletons

`compare_rigs.py` diffs bone names, parenting and bind transforms. `extract.ps1` prints this table at
the end — the last row is the control, because **CDPR ships that retarget** for every female NPC:

```
man_base   -> player_man_skeleton     71/71 names  0 re-parented   4 moved (max  9.6 mm, Hips)
woman_base -> player_woman_skeleton   71/71 names  0 re-parented  16 moved (max 38.0 mm, RightArm)
man_base   -> player_woman_skeleton   71/71 names  0 re-parented  22 moved (max 71.4 mm, Hips)
man_base   -> woman_base              71/71 names  0 re-parented  26 moved (max 66.9 mm, Hips)
```

**Structure is identical** — man_base is a strict subset of the player skeletons, every name present,
every parent the same. The 81 extras are rig-control joints (`Torso_*_GRP`, IK and pole-vector
`*_JNT`, `*HandEnd`); none has a source bone, and every vanilla V clip keys the IK ones at their rest
offset from the bone they follow ("What V needs", below). So there is nothing to *map*: Rokoko exists to reconcile
skeletons that disagree about names and hierarchy, and any bone-mapping step in Blender is busywork.

**Proportions differ**, mildly for male and materially for female (a 38 mm longer upper arm). That is
the stretching PoNC's author warns about — and it is *smaller* than the hop the game already
retargets across in the last row. It also picks the female source: `woman_base`, not `man_base`.

## The one-field probe — FAILED in game 2026-10-17

V went into the workspot but nothing played, the same as without it
(`docs/research/player-rig-retarget.md`, status). Kept because the run that answered it is
`tools/e2e/scenarios/v_rig_retarget.ps1`, and the archive below is what it installs.

A rig carries a `retargets` array of `animRigRetarget`, and its **only** payload is a `sourceRig`
depot path. No bone table, no baked offsets — the engine derives the mapping from bone names.

```
man_base.rig               71 bones   <- (none)          -- the root
woman_base.rig             71 bones   <- man_base.rig    -- CDPR retargets the whole female cast
player_man_skeleton.rig   152 bones   <- (none)          -- V
player_woman_skeleton.rig 152 bones   <- (none)          -- V
```

CDPR ships every female NPC animation as a name-based retarget off `man_base`. V's skeletons
declare no source at all. `make_retarget_mod.py` adds the missing entry and packs
`work/mod/ncn_player_rig_retarget.archive` (two files, verified: 152 bones intact, `retargets=1`).

Install into `<game>\archive\pc\mod\`, load a save, play a PoNC pose on V with `animUseDouble`
**off**.

**Mind the load order if a third-person mod is installed.** Immersive Third Person - Best Of Both
Worlds `d2026.9.19` overrides `player_woman_skeleton.rig` itself (it adds a `tpp_upperbody_ms` rig
part for its headlook), and it patches both `player_*_fpp.ent` besides — so whichever archive loads
last wins the whole file and the probe can read as "the engine ignores `retargets`" when it was
simply overwritten. Checked 2026-09-19:
[`../../docs/research/third-person-view-teardown.md`](../../docs/research/third-person-view-teardown.md) §2.

**This is a probe, not a shipped fix.** What is proven is the data: the field exists, CDPR uses it
for exactly this, and the bone sets make the name mapping total. What is *not* proven is that the
engine consults `retargets` for a workspot-driven animset — it may only apply it where the animset
rig and entity rig already differ, which is our case, but that is an assumption until it runs.
The rig is also only necessary, not sufficient: V's FPP animgraph may still own the body pose. If
the pose plays deformed rather than not at all, the retarget worked and the graph is the next
problem.

## Baked route — `retarget.ps1`, no Blender — PLAYS on V in game 2026-10-18

A new `.anims` per set, cooked against the player skeleton. The
[wiki's procedure](https://wiki.redmodding.org/cyberpunk-2077-modding/modding-guides/animations/animations/retargeting-poses-animations)
does it by hand in Blender with Rokoko. `retarget.ps1` does the same steps headless, one command per set:

```
powershell -File tools\retarget\retarget.ps1 -Body woman `
  -Anims tools\retarget\work\cr2w\pinkydude\pleasures_of_nightcity\anims_vol1\cowgirl_wa.anims `
  -DepotPath ncn\anims\player\cowgirl_wa_player.anims
```

| wiki step | here |
|---|---|
| export the source from WolvenKit, import to Blender | `WolvenKit.CLI export -gp` → glb |
| Rokoko: build bone list, auto scale, rest pose, retarget | `retarget_glb.py` — names match, so no list; each bone takes the source bone's model-space rotation as is (the rigs share bone axes but not rest poses), bone lengths stay the target's, pelvis travel scaled by leg length |
| — (not in the wiki) | `retarget_glb.py` puts V's IK targets and pole vectors on the bones they follow, at their rest offset; a still track is two LINEAR keys; each clip is marked for the SIMD encoder and carries the rig's 23 float tracks |
| NLA push-down, delete the other animations | the output glb holds only the retargeted clips |
| empty `animations` / `animationDataChunks` in a container | `anims_json.py prep` — the source animset, emptied (fallback pose too), rig swapped |
| WolvenKit import, Target Format = Anims, use existing file | `wk_anims` — WolvenKit's own `ModTools.ImportAnims`, from the nightly (Toolchain, below); the CLI's `import` reads every glb as a mesh |
| `numTracks` = 0 | **not taken** — V's clips keep the rig's 23 tracks, and zeroing them changed nothing in game |
| test in game | **still the game's** — but first, `verify_retarget.py` re-exports the cooked file and compares every clip, every bone and every IK target against the source |

Measured 2026-10-18: all eight PoNC sets (missionary, cowgirl, doggy, oral × `_wa` / `_ma`, 116 clips)
worst 0.049° against the source's model-space pose at the cooked frames, IK targets within 0.031 cm of
their bones, every buffer SIMD. Each set takes about a minute, most of it WolvenKit loading the archives.
Output: `work/depot/ncn/anims/player/<set>_player.anims`.

**NPC rigs, `-Rig`** (2026-10-25). `-Rig man_big` targets a `base_entities` rig instead of V's skeleton. Its
donor armature is built from the rig json by `rig_glb.py`, because WolvenKit exports an armature only beside a
clip, and `woman_big` has none. Unbundle the `.rig` into `work/npcrig/cr2w` and `convert serialize` it first.
`rig_glb.py --check` against a WolvenKit-exported armature passes on `man_base` and `woman_base`: bone lengths
exact, rests within 0.03°. The `_ma` sets go onto `man_big` and `man_fat` (71 bones, `man_base`'s names), and the
`_wa` sets onto `woman_big` and `woman_fat` (249 bones, `woman_base`'s 71 plus muscle bones left at rest, and no
float tracks). `woman_big` and `woman_fat` lack `LeftEye`, `RightEye` and `reference_joint`, so `-Rig` passes
`retarget_glb.py --drop-missing`: those source tracks go unplayed, and verify skips a bone the output lacks.
Output: `work/depot/ncn/anims/npc/<set>_<rig>.anims`. All 16 (four sets × four rigs) verify: worst 0.049° on the
`_ma` sets, 0.037° on the `_wa` ones. `make_npc_rig_rows.py` then packs `ncn_npc_rigs.archive`: PoNC's AMM workspot
at `ncn\workspots\npc\ponc_anims.workspot` with a row per rig, because PoNC ships `man_base` and `woman_base` rows
only and a big body mounts it and plays nothing.

The bake keeps the joint angles, so a bigger body lands its parts elsewhere. `man_big` against `man_base`, joint
positions over the whole clip: missionary01 hips 6.6 cm (5 cm back from her, 4.5 cm up), hands 5 cm; oral01 (sitting)
hips 3.7 cm up, hands 6–9 cm above her head; oral05 (standing) hips 5.6 cm, hands 7–8 cm. Not yet corrected: a hip
offset fixes the pelvis, the hands need IK onto where `man_base`'s landed.

### Seeing a pair in Blender

`blender_pair.py` builds the scene: per row, `man_base` + `woman_base` on PoNC's clips beside `<rig>` on our bake
+ the same woman, playing. `SET`, `POSES` (`man clip:woman clip`, comma separated rows) and `RIG` pick what
(script header). It loads in seconds. What it gets right, each of which cost a wrong picture:

- **No materials.** The CP77 importer with `with_materials` and every appearance took 20 minutes for four bodies.
- **Drop the Root track.** PoNC's `_wa` clips key `Root` at 180° yaw; the game lines the pair up without it, so
  applying it turns the woman round and puts her 1.5 m away. No clip has root motion, and the workspots carry no
  per-actor offset: both halves play on one origin.
- **`_a` is the man's half, `_b` the woman's** (`missionary01_lie_a` on top, `oral01_penis_sit_a` sitting).
- **The skin's muscle bones** are not in the anim rig; they are copied in at the body's bind and hung off the
  nearest anim bone, as the plugin's `set_armature` does.

Its inputs: the source and bake glbs `retarget.ps1` leaves in `work/run/<set>_<ma|wa>_<rig>/`, and the body glbs in
`work/body/glb`. A body mesh is `unbundle`d from `archive\pc\content` (`-w "*t0_000_mb_base__full.mesh"`; `man_base`
is `t0_000_ma_`, `man_fat` `t0_000_mf_`, `woman_base` `t0_000_wa_`) and exported with `MeshExportArgs__MaterialRepo`
set in the environment to `work\body\depot` — the CLI refuses a mesh with no material depot, and its `--help` names
no flag for it. A headless still for checking the scene: `SHOT=<png>` with `blender -b`.

### What V needs from a baked clip

Five faults, stacked — each fix alone still left V wrong, and the probes that told them apart are in
`make_v_shape_probe.py`. The evidence is the research doc, "What V needs from a baked clip".

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
(hands ~45 cm wide). Seen in Blender with `blender_preview.py`, fixed the same day.

What this does **not** answer: contacts. Target lengths mean V's 38 mm longer female arm reaches
38 mm further — a hand on a partner's shoulder lands off it. The IK pass above only keeps V's IK
targets on V's own bones; it does not reach for a partner. PoNC's paired workspot has not run on V yet.

A bare `.rig` has no glb exporter — the CLI reports success and writes nothing. An `.anims` export
carries the skeleton it binds, so a vanilla player clip (`work/glb/tpp_p?a_locomotion.anims.glb`,
from `extract.ps1`) is the armature donor.

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
| decode | hkxc → 32-bit packfile → blender-hkx `unpack` (resampled to 30 fps). Clips carry 242 tracks (99 bones + physics), so the skeleton is padded to 242 by `skyrim_skeleton.py`, or blender-hkx writes zero frames. Sources: `skeleton.hkx` / `femskeleton.hkx` from the HKX exporter folder |
| retarget | `skyrim_retarget.py`: per mapped bone a fixed offset from the Skyrim rest, swung to aim where the target's bone aims; Skyrim Z-up/+Y to glTF Y-up/−Z; hips travel scaled by hip height. Spine2, Neck1 and the metacarpals stay at rest |
| oral reach | `pair_reach.py`, run before `glbs`: for each oral act (`acts` in the pack's scene files) the giver's head to the target's pelvis, Skyrim against ours; the flat slide that matches is written to `<port>/pair_shift.json` and `glbs` moves that clip's Hips by it. Our shorter torsos left most givers 4–10 cm short. Not slid: within 2 cm, over 15 cm, or a source reach over 0.6 m (the act's roles are wrong) |
| V | `retarget_glb.py` on the NPC set's glb, as for PoNC |
| cook | `wk_anims --list`: every set in one process, against `work/rigs/rigs.archive` (our four rigs, packed once) instead of the game's archives; each rig's empty container is built once into `work/empty_anims/` |

### Which stage needs Windows

Only the decode does, once per source clip (`decoded/`, shared by both bodies). The WolvenKit stages run on Linux
under .NET 8 (`dotnet WolvenKit.CLI.dll`, `libkraken.so` from `WolvenKit.Core/lib` beside it); `skyrim_port.py`
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
| `extract.ps1` | archives → `work/{cr2w,json,glb}`, then reports rig bindings and the bone diff |
| `compare_rigs.py` | bone-name + parenting diff between two serialized rigs |
| `make_retarget_mod.py` | injects the `animRigRetarget` entry, packs the probe archive |
| `retarget.ps1` | the baked route, one animset end to end → `work/depot/<DepotPath>` |
| `retarget_glb.py` | glb → glb onto another skeleton, IK targets driven, V's clip settings; numpy only |
| `anims_json.py` | `prep` the container |
| `wk_anims/` | .NET 8 bridge to WolvenKit's anims importer, loaded from the WolvenKit dir it is given (4th arg) or `NCN_WOLVENKIT_DIR` |
| `verify_retarget.py` | cooked vs source, per clip, bone and IK target; fails over `--max-deg` / `--max-cm` |
| `make_v_row_probe.py` | probes 2 and 3: a PoNC pose with `finalAnimsets` rows for V's skeletons; `--baked` names the `retarget.ps1` sets |
| `make_v_shape_probe.py` | the in-game probe archive behind "What V needs"; takes workspot names to build only those |
| `rig_glb.py` | a rig json as the armature WolvenKit would export (the `-Rig` donor); `--check` against an exported one |
| `test_retarget_glb.py`, `test_rig_glb.py` | synthetic rigs, in `tools/py_test.ps1` |
| `blender_preview.py` | Blender (CP77 IO Suite): NPC body on the source clip beside V's body on the cooked retarget. V's arm mesh not yet shown |
| `blender_pair.py` | Blender: a PoNC pair on `man_base` beside the same pair on an NPC rig's bake ("Seeing a pair in Blender") |
| `make_npc_rig_rows.py` | `ncn_npc_rigs.archive`: PoNC's AMM workspot with `man_big` / `man_fat` / `woman_big` / `woman_fat` rows on our bakes |
| `skyrim_port.py` | the OpenSex port, stage by stage ("Skyrim clips") |
| `skyrim_scenes.py`, `skyrim_tagfile.py`, `skyrim_skeleton.py`, `skyrim_retarget.py` | its inventory, tagfile reader, skeleton padding and retarget |
| `test_skyrim_port.py` | those four on synthetic input, in `tools/py_test.ps1` |
| `pair_reach.py`, `test_pair_reach.py` | an oral giver slid to the source's reach ("oral reach" above); the test is in `tools/py_test.ps1` |
| `skyrim_contact.py`, `pair_contact.py` | which partner area each hand, mouth and genital touches: on Skyrim's bodies, then on ours on the retarget; `MESH=1` runs the clip through the interaction mesh, `GIF=1` draws Skyrim / retarget / after. Output in `work/contact/` ([opensex-port §9.6](../../docs/design/opensex-port.md)) |
| `interaction_mesh.py`, `test_interaction_mesh.py` | contacts kept through other proportions: Ho, Komura, Tai 2010 as written, then back to our rotations; the test is in `tools/py_test.ps1`. Solves on the GPU with `pip install nvmath-python[cu12]` (cuDSS), else SuperLU on one core |
| `mesh_skin.py` | `MESH_SKIN=1`: his palm and her buttocks in the mesh sourced from Skyrim's own skin ([opensex-port §9.6](../../docs/design/opensex-port.md)) |
| `hand_fit.py`, `test_hand_fit.py` | `HANDFIT=1`: after the mesh, his palm turned and reached onto her skin where Skyrim's is, the elbow kept on its own side; a clip whose elbow snaps fails. The test is in `tools/py_test.ps1` |
| `pack_release.py` | the packs' release zip as built, `dist/opensex-<version>.zip`: archive/ and bin/ at the game root, licences under `licenses/<pack>/`; refuses a version already built |
| `pod/` | the sweep on a RunPod GPU: `pod_bundle.py` (the bundle, run here), `setup.sh`, `pod_run.py` (any script from the bundle), `run_sweep.sh` (both packs, a self-stop timer); the port's glbs and cook: `bake_bundle.py` (bundle, and `--unpack` the results), `run_bake.sh` |
| `pair_batch.py`, `test_pair_batch.py` | `pair_contact.py` over every clip of a pack with the cast sizes in `ACTORS` (2 by default; `ACTORS=2,3`), N clips at once (`MESH=1 python pair_batch.py ostimng 4`); a log per clip in `work/contact/batch/<pack>/` |
| `mb_transition.ps1` | a generated transition between two clips, export to cooked `.anims` and checked; `-Preview` renders the body ([guide §5](../../docs/guides/retarget-an-animation.md)) |
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
