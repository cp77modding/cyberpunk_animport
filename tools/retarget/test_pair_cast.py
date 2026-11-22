"""pair_cast: a pack not cast by clip name takes its pairs from its scene list. No game data.

Run: python tools/retarget/test_pair_cast.py (also from tools/py_test.ps1).
"""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pair_batch as pb  # noqa: E402
import pair_cast  # noqa: E402

fails = []
packs = tempfile.mkdtemp()
os.makedirs(os.path.join(packs, "sl"))
scenes = [
    {"id": "sl.miss.s1", "actors": [{"sex": "m"}, {"sex": "f"}], "acts": [{"type": "penetrative", "actor": "a", "target": "b"}],
     "speeds": [{"clips": ["sl/miss_a2_s1", "sl/miss_a1_s1"]}]},
    {"id": "sl.anal.s1", "actors": [{"sex": "m"}, {"sex": "any"}],
     "acts": [{"type": "penetrative", "actor": "a", "target": "b", "into": "anus"}],
     "speeds": [{"clips": ["sl/anal_a2_s1", "sl/anal_a1_s1"]}]},
    {"id": "sl.hug.s1", "actors": [{"sex": "f"}, {"sex": "f"}], "acts": [],
     "speeds": [{"clips": ["sl/hug_a1_s1", None]}]},
    {"id": "sl.trio.s1", "actors": [{"sex": "m"}, {"sex": "f"}, {"sex": "f"}], "acts": [],
     "speeds": [{"clips": ["sl/trio_a1", "sl/trio_a2", "sl/trio_a3"]}]},
]
json.dump(scenes, open(os.path.join(packs, "sl", "scene-list.json"), "w"))
pair_cast.build_config.load = lambda: {"packs": packs}

rows = [{"clip": c, "sex": s, "srcSex": s} for c, s in (
    ("miss_a2_s1", "m"), ("miss_a1_s1", "f"), ("anal_a2_s1", "m"), ("anal_a1_s1", "f"), ("anal_a1_s1", "m"),
    ("hug_a1_s1", "f"), ("trio_a1", "m"), ("trio_a2", "f"), ("trio_a3", "f"))]
got = pb.clip_bases(rows, (2,), "sl")
if got != ["anal_a2_s1", "miss_a2_s1"]:
    fails.append("pairs: want anal_a2_s1, miss_a2_s1 (a speed missing a clip and a trio left out), got %s" % got)
if pb.clip_bases(rows, (3,), "sl") != ["trio_a1"]:
    fails.append("trios: want trio_a1, got %s" % pb.clip_bases(rows, (3,), "sl"))
every = {}
for r in rows:
    every.setdefault(r["clip"], []).append(r)
cast = [(r["clip"], r["sex"]) for r in pb.cast_rows(every, "anal_a2_s1", "sl")]
if cast != [("anal_a2_s1", "m"), ("anal_a1_s1", "f")]:
    fails.append("an 'any' side plays the pack's own body: want her f row, got %s" % cast)
if pair_cast.clips("sl", "miss_a2_s1") != ["miss_a2_s1", "miss_a1_s1"]:
    fails.append("clips: %s" % pair_cast.clips("sl", "miss_a2_s1"))
if (pair_cast.entry("sl", "miss_a2_s1"), pair_cast.entry("sl", "anal_a2_s1")) != ("vulva", "anus"):
    fails.append("entry: want vulva, anus, got %s, %s" % (pair_cast.entry("sl", "miss_a2_s1"),
                                                         pair_cast.entry("sl", "anal_a2_s1")))
if pair_cast.scene_casts("opensex") or pair_cast.clips("opensex", "kiss") != ["kiss_0", "kiss_1"]:
    fails.append("the mod's own packs are cast by clip name, never by a scene list")

print("\n".join(fails) or "ok")
sys.exit(1 if fails else 0)
