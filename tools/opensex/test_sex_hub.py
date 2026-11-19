"""sex_hub on made-up scenes: no packs.

Run: python tools/opensex/test_sex_hub.py (also from tools/py_test.ps1).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sex_hub as sh  # noqa: E402

fails = []


def scene(sid, sexes, postures, acts=(), moves=(), **extra):
    return dict({"id": sid, "actors": [{"sex": x, "posture": p} for x, p in zip(sexes, postures)],
                 "speeds": [{"clips": ["p/%s_%d" % (sid, i) for i in range(len(sexes))]}],
                 "acts": [{"type": t, "actor": "a", "target": "b"} for t in acts],
                 "moves": [{"to": m} for m in moves]}, **extra)


ST = ["standing"] * 2
FF, MF = sh.HUBS["ff"], sh.HUBS["mf"]
S = {s["id"]: s for s in [
    scene(FF, ["f", "f"], ST),
    scene(MF, ["any", "any"], ST, moves=["opensex.ops.sta-sta.sx.sex"]),
    scene("opensex.ops.sta-sta.sx.sex", ["m", "f"], ST),                                       # sex by its code
    scene("opensex.ops.kne-sta.vj.cl", ["any", "f"], ["kneeling", "standing"], acts=["oral_vagina"]),
    scene("opensex.ops.sta-sta.ap.near", ["any", "any"], ST, moves=[MF]),                      # two moves: left alone
    scene("opensex.ops.sta-sta.ap.far", ["any", "any"], ST, moves=["opensex.ops.sta-sta.ap.near"]),
    scene("opensex.ops.lys-lys.ho.lying", ["any", "any"], ["lyingside"] * 2),                  # never
    scene("opensex.ops_furniture.cha-ir.ap.chair", ["any", "any"], ["sitting", "standing"], furniture="chair"),
    scene("opensex.ops.sta-sta.ap.cut", ["any", "any"], ST, moves=["opensex.gen.cut--sex"]),
    scene("opensex.gen.cut--sex", ["f", "f"], ST, transition=True, next="opensex.ops.sta-sta.sx.sex"),
    scene("opensex.ops.sta-sta.ap.mfonly", ["m", "f"], ST),
]}
clips = {c: {"m": {}, "f": {}} for s in S.values() for sp in s["speeds"] for c in sp["clips"]}

starts, sex = sh.plan(S, clips, "mf")
want = ["opensex.ops.lys-lys.ho.lying", "opensex.ops.sta-sta.ap.far", "opensex.ops.sta-sta.ap.mfonly",
        "opensex.ops_furniture.cha-ir.ap.chair"]
if starts != want or sex:   # cut: the f/f transition is a cut for m/f, so it is one move from sex
    fails.append("mf: %s %s" % (starts, sex))
starts, sex = sh.plan(S, clips, "ff")
if sex != ["opensex.ops.kne-sta.vj.cl"]:
    fails.append("ff: a hub more than one move from sex gains its sex scenes: %s" % sex)
if "opensex.ops.sta-sta.ap.mfonly" in starts or "opensex.ops.sta-sta.ap.near" not in starts:
    fails.append("ff: %s" % starts)
one = dict(clips, **{"p/opensex.ops.sta-sta.ap.far_0": {"m": {}}})
if "opensex.ops.sta-sta.ap.far" not in sh.plan(S, one, "mf")[0] or \
        "opensex.ops.sta-sta.ap.far" in sh.plan(S, one, "ff")[0]:
    fails.append("a scene two women have no clip for is not theirs")
if sh.plan({i: s for i, s in S.items() if i != MF}, clips, "mf") != ([], []):
    fails.append("no hub: nothing planned")

if not sh.add_move(S, S["opensex.ops.sta-sta.ap.far"], MF, MF) or \
        S["opensex.ops.sta-sta.ap.far"]["moves"][-1]["label"] != sh.LABEL:
    fails.append("standing: %s" % S["opensex.ops.sta-sta.ap.far"]["moves"])
for sid in ("opensex.ops.lys-lys.ho.lying", "opensex.ops_furniture.cha-ir.ap.chair"):
    if not sh.add_move(S, S[sid], MF, MF) or S[sid]["moves"][-1]["label"] != sh.UP:
        fails.append("off the floor or furniture: %s" % S[sid]["moves"])
if sh.add_move(S, S["opensex.ops.sta-sta.ap.near"], MF, MF):
    fails.append("add_move added a move already there")
S["opensex.gen.hub--cl"] = scene("opensex.gen.hub--cl", ["f", "f"], ST, transition=True, next="opensex.ops.kne-sta.vj.cl")
S["opensex.gen.hub--sex"] = scene("opensex.gen.hub--sex", ["f", "f"], ST, transition=True, next=MF)   # a name, not a rest
S[FF]["moves"] = [{"to": "opensex.gen.hub--cl"}, {"to": "opensex.gen.hub--sex"}]
if sh.add_move(S, S[FF], "opensex.ops.kne-sta.vj.cl", FF):
    fails.append("add_move added a move its transition already makes")
if not sh.add_move(S, S[FF], "opensex.ops.sta-sta.sx.sex", FF) or S[FF]["moves"][-1]["label"] is not None:
    fails.append("add_move into a sex scene: %s" % S[FF]["moves"])
sh.add_move(S, S["opensex.ops.sta-sta.ap.mfonly"], MF, MF)
starts, _ = sh.plan(S, clips, "mf")
if starts:
    fails.append("after the moves every m/f scene is two moves from sex: %s" % starts)

for f in fails:
    print("FAIL", f)
print("test_sex_hub:", "FAILED" if fails else "ok")
sys.exit(1 if fails else 0)
