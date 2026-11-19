"""make_amm_poses on synthetic input: which clips are poses, AMM's list file, a rig's set path. No game, no WolvenKit.

Run: python tools/opensex/test_amm_poses.py (also from tools/py_test.ps1).
"""
import json
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import make_amm_poses as ma  # noqa: E402

fails = []

scenes = [{"speeds": [{"clips": ["p/a_0", "p/a_1"]}, {"clips": ["p/a_0", "p/b_0"]}]},
          {"transition": True, "speeds": [{"clips": ["p/move_0"]}]},
          {"speeds": [{"clips": ["p/twice#2"]}]}]
if ma.pose_refs(scenes) != ["p/a_0", "p/a_1", "p/b_0"]:
    fails.append("pose_refs: %s" % ma.pose_refs(scenes))

lua = ma.amm_lua("OpenSex", "ncn\\workspots\\amm\\x.ent", {"woman_big": ["x"], "man_base": ["b", "a"], "man_big": ["a"]})
if '["Man Average"] = {"a", "b"}' not in lua or '["Big"] = {"a"}' not in lua:
    fails.append("the list file lacks a rig: %s" % lua)
if "woman_big" in lua or '"x"' in lua:
    fails.append("a rig AMM has no row for was listed")
if 'entity_path = "ncn\\\\workspots\\\\amm\\\\x.ent"' not in lua:
    fails.append("the entity path is not escaped for Lua: %s" % lua)
if ma.rig_name(r"base\characters\entities\player\player_man_skeleton.rig") != "player_man_skeleton":
    fails.append("rig_name kept the path")

if ma.sibling("opensex\\anims\\npc\\x_ma.anims", "man_big") != "opensex\\anims\\man_big\\x_ma_man_big.anims":
    fails.append("sibling: %s" % ma.sibling("opensex\\anims\\npc\\x_ma.anims", "man_big"))
if not ma.rig_of_set("x_ma.anims", "man_fat") or ma.rig_of_set("x_wa.anims", "man_fat") \
        or ma.rig_of_set("x_ma.anims", "woman_big") or not ma.rig_of_set("x_wa.anims", "woman_big"):
    fails.append("a rig took the other body's set")

work = tempfile.mkdtemp()
try:
    root = os.path.join(work, "p", ma.msw.SCENES_REL, "p")
    os.makedirs(root)
    depot = os.path.join(work, "p", "depot", "p", "anims", "man_big")
    os.makedirs(depot)
    open(os.path.join(depot, "x_ma_man_big.anims"), "w").close()
    clips = {"p/a": {"m": {"npc": "p\\anims\\npc\\x_ma.anims", "player": "p\\anims\\player\\x_pma.anims"},
                     "f": {"npc": "p\\anims\\npc\\x_wa.anims", "player": "p\\anims\\player\\x_pwa.anims"}}}
    with open(os.path.join(root, "clips.json"), "w", encoding="utf-8") as f:
        json.dump(clips, f)
    ma.add_rigs(work, "p", ["man_big", "man_fat", "woman_big"])
    with open(os.path.join(root, "clips.json"), encoding="utf-8") as f:
        got = json.load(f)["p/a"]
    if got["m"].get("man_big") != "p\\anims\\man_big\\x_ma_man_big.anims":
        fails.append("a baked rig was not named: %s" % got)
    if "man_fat" in got["m"] or "woman_big" in got["f"]:
        fails.append("a rig with no baked set was named: %s" % got)
finally:
    shutil.rmtree(work)

for f in fails:
    print("FAIL", f)
print("test_amm_poses:", "FAILED" if fails else "ok")
sys.exit(1 if fails else 0)
