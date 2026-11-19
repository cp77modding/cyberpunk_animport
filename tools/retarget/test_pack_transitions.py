"""pack_transitions on a made-up scene pair: no pack repo, no WolvenKit.

Run: python tools/retarget/test_pack_transitions.py (also from tools/py_test.ps1).
"""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pack_transitions as pt  # noqa: E402

fails = []
tmp = tempfile.mkdtemp()
A = {"id": "opensex.ops.kne-afo.bj.blow", "name": "Blow", "furniture": None,
     "actors": [{"sex": "m", "tags": ["kneeling"], "posture": "kneeling", "mods": []},
                {"sex": "f", "tags": ["allfours"], "posture": "allfours", "mods": []}],
     "speeds": [{"clips": ["opensex/bj_0", "opensex/bj_1"], "playback": 1.0, "display": None}],
     "moves": [{"to": "opensex.ops.sit-kne.ho.sit", "label": "sit"}, {"to": "opensex.x.other", "label": None}]}
a_file = os.path.join(tmp, "blow.json")
pt.write_json(a_file, A)
row = {"from": A["id"], "to": "opensex.ops.sit-kne.ho.sit", "pack": "opensex", "length": 1.66666,
       "sides": [{"actor": "b", "sex": "f", "rig": "woman_base", "clip": "gen-blow--sit_1",
                  "npc": r"C:\x\npc\gen_kneafo_wa.anims", "player": r"C:\x\player\gen_kneafo_pwa.anims"},
                 {"actor": "a", "sex": "m", "rig": "man_base", "clip": "gen-blow--sit_0",
                  "npc": r"C:\x\npc\gen_kneafo_ma.anims", "player": r"C:\x\player\gen_kneafo_pma.anims"}]}
rejected = dict(row, to="opensex.x.other", rejected=True, reason="seam")
pack_of = {"opensex": {A["id"]: a_file}}

if pt.key(A["id"], row["to"]) != "blow--sit":
    fails.append("key: %s" % pt.key(A["id"], row["to"]))

# Test mode: a transition and a copy of A in ncngen; the real A is not rewired.
scenes, clips, files, rewires = pt.plan([row, rejected], pack_of, True)
by_id = {sid: s for _, sid, s, _ in scenes}
t, src = by_id.get("ncngen.gen.blow--sit"), by_id.get("ncngen.src.blow--sit")
if len(scenes) != 2 or not t or not src or rewires:
    fails.append("test mode: %s, rewires %s" % (sorted(by_id), rewires))
else:
    if not t["transition"] or t["next"] != row["to"] or t["moves"] or t["length"] != 1.6667:
        fails.append("transition fields: %s" % {k: t[k] for k in ("transition", "next", "moves", "length")})
    if t["speeds"][0]["clips"] != ["ncngen/gen-blow--sit_0", "ncngen/gen-blow--sit_1"]:
        fails.append("clips not in actor order: %s" % t["speeds"][0]["clips"])
    if [x["posture"] for x in t["actors"]] != ["kneeling", "allfours"]:
        fails.append("transition actors are not A's")
    if src["moves"] != [{"to": t["id"], "label": "generated", "priority": 0}] or src["speeds"] != A["speeds"]:
        fails.append("the copy of A does not play A and move only to the transition")
# An "any" side of A: the transition's side is the body it was generated on, which is all its clip is baked for.
pt.write_json(a_file, dict(A, actors=[dict(x, sex="any") for x in A["actors"]]))
t_any = {sid: s for _, sid, s, _ in pt.plan([row], pack_of, True)[0]}.get("ncngen.gen.blow--sit")
if not t_any or [x["sex"] for x in t_any["actors"]] != ["m", "f"]:
    fails.append("an any side: %s" % (t_any and [x["sex"] for x in t_any["actors"]]))
pt.write_json(a_file, A)
c = clips.get("ncngen", {})
if c.get("ncngen/gen-blow--sit_0") != {"m": {"npc": r"ncngen\anims\npc\gen_kneafo_ma.anims",
                                              "player": r"ncngen\anims\player\gen_kneafo_pma.anims"}}:
    fails.append("clips.json row: %s" % c.get("ncngen/gen-blow--sit_0"))
half = dict(row, sides=[row["sides"][0], dict(row["sides"][1], player=None)])
if "player" in pt.plan([half], pack_of, True)[1]["ncngen"]["ncngen/gen-blow--sit_0"]["m"]:
    fails.append("a side with no player clip got a player row")
if len(files.get("ncngen", {})) != 4:
    fails.append("anims to copy: %s" % files)

# Into the source: the transition in opensex and A's one move to B rewired; the other move kept.
scenes, clips, files, rewires = pt.plan([row], pack_of, False)
if [sid for _, sid, _, _ in scenes] != ["opensex.gen.blow--sit"] or len(rewires) != 1:
    fails.append("source mode: %s %s" % ([sid for _, sid, _, _ in scenes], rewires))
no_v = dict(row, sides=[dict(s, player=None) for s in row["sides"]])
if pt.plan([no_v], pack_of, False)[3] or not pt.plan([no_v], pack_of, True)[0]:
    fails.append("a move with no V clip was rewired into the source, or dropped from the test pack")
if pt.plan([row], pack_of, False, {(row["from"], row["to"])})[0]:
    fails.append("a dropped move was packed")
pt.rewire(*rewires[0])
moves = json.load(open(a_file, encoding="utf-8"))["moves"]
if [m["to"] for m in moves] != ["opensex.gen.blow--sit", "opensex.x.other"]:
    fails.append("rewire: %s" % [m["to"] for m in moves])
try:
    pt.rewire(*rewires[0])  # a second run over the same results
except SystemExit as e:
    fails.append("a rewire already done stopped the run: %s" % e)

# Two moves whose ids end the same name one transition: refused, not written twice.
twin = os.path.join(tmp, "twin.json")
pt.write_json(twin, dict(A, id="opensex.other.folder.blow"))
try:
    pt.plan([row, dict(row, **{"from": "opensex.other.folder.blow"})],
            {"opensex": {A["id"]: a_file, "opensex.other.folder.blow": twin}}, False)
    fails.append("two moves sharing a transition id were both planned")
except SystemExit:
    pass

# A transition a later run no longer packs: A moves to B again, the scene and its clip rows go.
pt.ANIMS = tmp
sdir = os.path.join(tmp, "opensex", pt.SCENES_REL, "opensex")
t_file = os.path.join(sdir, "gen", "blow--sit.json")
pt.write_json(t_file, pt.transition_scene("opensex.gen.blow--sit", A, row["to"], 1.0,
                                          ["opensex/gen-blow--sit_0", "opensex/gen-blow--sit_1"], "mf"))
pt.write_json(os.path.join(sdir, "clips.json"), {"opensex/gen-blow--sit_0": {}, "opensex/gen-blow--sit_1": {},
                                                 "opensex/bj_0": {}})
gone = pt.unpack_stale("opensex", set(), {A["id"]: a_file, "opensex.gen.blow--sit": t_file})
moves = [m["to"] for m in json.load(open(a_file, encoding="utf-8"))["moves"]]
left = json.load(open(os.path.join(sdir, "clips.json"), encoding="utf-8"))
if gone != ["opensex.gen.blow--sit"] or os.path.exists(t_file) or moves != [row["to"], "opensex.x.other"]:
    fails.append("unpack_stale: gone %s, file kept %s, moves %s" % (gone, os.path.exists(t_file), moves))
if sorted(left) != ["opensex/bj_0"]:
    fails.append("unpack_stale left clip rows: %s" % sorted(left))
pt.write_json(t_file, pt.transition_scene("opensex.gen.blow--sit", A, row["to"], 1.0, [], "mf"))
if pt.unpack_stale("opensex", {"opensex.gen.blow--sit"}, {A["id"]: a_file, "opensex.gen.blow--sit": t_file}) \
        or not os.path.exists(t_file):
    fails.append("unpack_stale removed a transition this run keeps")

# Two stale transitions at once, one of them referred to from the other's A: both unwired, both files and rows gone.
t2_file = os.path.join(sdir, "gen", "blow--x.json")
pt.write_json(t_file, pt.transition_scene("opensex.gen.blow--sit", A, row["to"], 1.0, ["opensex/gen-blow--sit_0"], "mf"))
pt.write_json(t2_file, pt.transition_scene("opensex.gen.blow--x", A, "opensex.x.other", 1.0, ["opensex/gen-blow--x_0"],
                                           "mf"))
pt.write_json(a_file, dict(A, moves=[{"to": "opensex.gen.blow--sit"}, {"to": "opensex.gen.blow--x"}]))
pt.write_json(os.path.join(sdir, "clips.json"), {"opensex/gen-blow--sit_0": {}, "opensex/gen-blow--x_0": {},
                                                 "opensex/bj_0": {}})
try:
    gone = pt.unpack_stale("opensex", set(), {A["id"]: a_file, "opensex.gen.blow--sit": t_file,
                                              "opensex.gen.blow--x": t2_file})
except OSError as e:
    gone = "crashed: %s" % e
moves = [m["to"] for m in json.load(open(a_file, encoding="utf-8"))["moves"]]
left = sorted(json.load(open(os.path.join(sdir, "clips.json"), encoding="utf-8")))
if sorted(gone) != ["opensex.gen.blow--sit", "opensex.gen.blow--x"] or moves != [row["to"], "opensex.x.other"] \
        or left != ["opensex/bj_0"] or os.path.exists(t_file) or os.path.exists(t2_file):
    fails.append("two stale: gone %s, moves %s, rows %s" % (gone, moves, left))

# A move with one side V's bake missed is named: packing would otherwise unpack it.
if [r["to"] for r in pt.missing_v([row, half, rejected])] != [half["to"]] or pt.missing_v([row]):
    fails.append("missing_v")

# Overlap past the closer authored pose: 21 cm past is dropped, 19 cm past and a rejected row are not.
deep = dict(row, gap=-0.31, gap_a=-0.10, gap_b=0.05)
near = dict(row, **{"from": "x.near"}, gap=-0.29, gap_a=-0.10, gap_b=0.05)
if pt.overlapping([deep, near, dict(rejected, gap=-1.0, gap_a=0.0, gap_b=0.0)], 0.20) != {(row["from"], row["to"])}:
    fails.append("overlapping: %s" % pt.overlapping([deep, near], 0.20))

for f in fails:
    print("FAIL", f)
print("test_pack_transitions:", "FAILED" if fails else "ok")
sys.exit(1 if fails else 0)
