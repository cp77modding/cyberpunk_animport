"""mb_moves.moves on a made-up scene graph: no packs, no clips.

Run: python tools/retarget/test_mb_moves.py (also from tools/py_test.ps1).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mb_moves as mm  # noqa: E402

fails = []


def scene(sid, sexes, moves=(), transition=False, nxt=None, posture="kneeling"):
    return {"id": sid, "actors": [{"sex": x, "posture": posture} for x in sexes], "transition": transition,
            "next": nxt, "moves": [{"to": m} for m in moves]}


S = {s["id"]: s for s in [
    scene("a", "mf", ["b", "same", "trio", "x.gen.a--c", "gone", "b", "climax"]),
    scene("climax", "mf", transition=True, nxt="a"),  # authored: not followed to its next
    scene("b", "mf", ["a"], posture="lying"),
    scene("same", "fm", ["a"]),                      # same postures: listed too
    scene("trio", "mff", ["a"]),
    scene("c", "mf", posture="standing"),
    scene("x.gen.a--c", "mf", transition=True, nxt="c"),
]}
got = [(s["id"], t["id"]) for s, t in mm.moves(S)]
want = [("a", "b"), ("a", "same"), ("a", "c"), ("b", "a"), ("same", "a")]
if got != want:
    fails.append("moves: %s" % got)
if mm.actor_map(S["a"], S["b"]) != [0, 1] or mm.actor_map(S["a"], S["same"]) != [1, 0]:
    fails.append("actor_map")
# "any" fits either body: an any/any or m/any scene keeps the order, an f/any one against m/any swaps
if mm.actor_map(scene("k", ["any", "any"]), S["same"]) != [0, 1] or \
        mm.actor_map(scene("k", ["m", "any"]), S["a"]) != [0, 1] or \
        mm.actor_map(scene("k", ["f", "any"]), scene("l", ["m", "any"])) != [1, 0]:
    fails.append("actor_map with any")
p = mm.Poses.__new__(mm.Poses)
p.first = {("opensex", "kiss_0"): "f"}
if p.body("opensex", "kiss_0", "any") != "f" or p.body("opensex", "kiss_0", "m") != "m":
    fails.append("Poses.body")

for f in fails:
    print("FAIL", f)
print("test_mb_moves:", "FAILED" if fails else "ok")
sys.exit(1 if fails else 0)
