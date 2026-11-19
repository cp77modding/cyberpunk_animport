"""cast_roles on made-up scenes and port rows: no packs, no OStimNG checkout.

Run: python tools/opensex/test_cast_roles.py (also from tools/py_test.ps1).
"""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cast_roles as cr  # noqa: E402

fails = []


def scene(sid, acts=(), sexes="mf", pack="opensex"):
    return {"id": sid, "actors": [{"sex": x} for x in sexes], "sources": [{"pack": pack, "file": "s.json"}],
            "acts": [{"type": t, "actor": a, "target": b} for t, a, b in acts]}


def sexes(s, ng=""):
    n = cr.needs_of(s, ng)
    return None if n is None else [cr.sex_of(x, a["sex"]) for x, a in zip(n, s["actors"])]


cases = [
    (scene("opensex.x.kiss"), ["any", "any"]),                                    # no act, no body word
    (scene("opensex.x.sex", [("penetrative", "a", "b")]), ["m", "f"]),
    (scene("opensex.x.sexb", [("penetrative", "a", "b")]), ["m", "f"]),          # no `into`: the vagina
    (dict(scene("opensex.x.anal"), acts=[{"type": "penetrative", "actor": "a", "target": "b", "into": "anus"}]),
     ["m", "any"]),
    (scene("opensex.x.bj", [("oral_penis", "b", "a")]), ["m", "any"]),
    (scene("opensex.x.cl", [("oral_vagina", "a", "b")]), ["any", "f"]),
    (scene("opensex.x.finger", [("manual", "a", "b")]), ["any", "f"]),           # a hand on a woman
    (scene("opensex.x.hj", [("manual", "b", "a")]), ["m", "any"]),
    (scene("opensex.x.boj.tits", [("manual", "b", "a")]), ["m", "f"]),           # breasts on the giver
    (scene("opensex.x.breastsuck"), ["any", "f"]),
    (scene("opensex.x.kneelingjerk"), None),                                       # a penis by name, no act: kept
    (scene("opensex.x.kneelinghj"), None),
    # b needs a penis and a vagina: neither body has both, so b keeps the pack's sex
    (scene("opensex.x.mixed", [("penetrative", "a", "b"), ("oral_penis", "a", "b")]), ["m", "f"]),
]
for s, want in cases:
    if sexes(s) != want:
        fails.append("%s: %s, want %s" % (s["id"], sexes(s), want))

# both needs on one side keep its sex
if cr.sex_of({cr.PENIS, cr.VAGINA}, "f") != "f" or cr.sex_of(set(), "m") != "any":
    fails.append("sex_of")

# OStimNG reads the source scene's actions
ng = tempfile.mkdtemp()
with open(os.path.join(ng, "s.json"), "w", encoding="utf-8") as fh:
    json.dump({"actions": [{"type": "analsex", "actor": 0, "target": 1}, {"type": "kissing", "actor": 1, "target": 0}]}, fh)
if sexes(scene("ostimng.x.anal", pack="ostimng"), ng) != ["m", "any"]:
    fails.append("ostimng anal: %s" % sexes(scene("ostimng.x.anal", pack="ostimng"), ng))
if cr.needs_of(scene("ostimng.x.gone", pack="ostimng"), os.path.join(ng, "nope")) is not None:
    fails.append("ostimng with no source scene is not left alone")

# the other body's set and row
if cr.body_set(r"opensex\anims\npc\ops_kne_ma.anims", "f") != r"opensex\anims\npc\ops_kne_wa.anims" or \
        cr.body_set(r"opensex\anims\player\ops_kne_pwa.anims", "m") != r"opensex\anims\player\ops_kne_pma.anims":
    fails.append("body_set")
man = {"key": "k", "file": "f.hkx", "clip": "kiss_0", "sex": "m", "rig": "man_base", "playerRig": "player_man",
       "npcSet": r"opensex\anims\npc\ops_kne_ma.anims", "playerSet": r"opensex\anims\player\ops_kne_pma.anims",
       "skeleton": r"C:\s\skeleton.hkx"}
manifest = [man]
source = [{"clip": "kiss_0", "sex": ["m"], "sets": [man["npcSet"], man["playerSet"]]}]
if not cr.add_rows(manifest, source, "opensex/kiss_0", "f") or len(manifest) != 2:
    fails.append("add_rows: %s" % manifest)
else:
    w = manifest[1]
    if (w["sex"], w["rig"], w["playerRig"], os.path.basename(w["skeleton"])) != \
            ("f", "woman_base", "player_woman", "femskeleton.hkx") or not w["npcSet"].endswith("_wa.anims"):
        fails.append("add_rows row: %s" % w)
    if source[0]["sex"] != ["f", "m"] or len(source[0]["sets"]) != 4:
        fails.append("add_rows source: %s" % source)
if not cr.add_rows(manifest, source, "opensex/kiss_0", "f") or len(manifest) != 2:
    fails.append("add_rows twice added a row")
if cr.add_rows(manifest, source, "opensex/nope_0", "f"):
    fails.append("add_rows with no row")

# bakes: an any side needs both bodies, less those clips.json has
ch = [(None, {"speeds": [{"clips": ["opensex/kiss_0", "opensex/kiss_1"]}]}, ["any", "f"])]
got = cr.bakes(ch, {"opensex/kiss_0": {"m": {}}, "opensex/kiss_1": {"f": {}}})
if got != {"opensex/kiss_0": {"f"}}:
    fails.append("bakes: %s" % got)

# penis side: an "m" side's clip wants a woman's bake unless clips.json has one, 2-5 actors; f/any sides, one actor,
# transitions never
two = {"id": "opensex.x.bj", "actors": [{"sex": "m"}, {"sex": "any"}],
       "speeds": [{"clips": ["opensex/bj_0", "opensex/bj_1"]}, {"clips": ["opensex/bjf_0", "opensex/bjf_1"]}]}
three = {"id": "opensex.x.three", "actors": [{"sex": "m"}, {"sex": "f"}, {"sex": "f"}],
         "speeds": [{"clips": ["opensex/t_0", "opensex/t_1", "opensex/t_2"]}]}
solo = {"id": "opensex.x.solo", "actors": [{"sex": "m"}], "speeds": [{"clips": ["opensex/s_0"]}]}
trans = dict(two, id="opensex.x.trans", transition=True)
got = cr.penis_wants([two, three, solo, trans], {"opensex/bj_0": {"m": {}}, "opensex/bjf_0": {"m": {}, "f": {}}})
if got != ({"opensex/bj_0": {"f"}, "opensex/t_0": {"f"}}, ["opensex.x.bj", "opensex.x.three"]):
    fails.append("penis_wants: %s" % (got,))
if cr.penis_wants([two], {}, "nomatch") != ({}, []):
    fails.append("penis_wants --scene filter")

for f in fails:
    print("FAIL", f)
print("test_cast_roles:", "FAILED" if fails else "ok")
sys.exit(1 if fails else 0)
