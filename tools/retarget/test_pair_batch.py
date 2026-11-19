"""pair_batch's clip list: no game data, no decode.

Run: python tools/retarget/test_pair_batch.py (also from tools/py_test.ps1).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pair_batch as pb  # noqa: E402

rows = [{"clip": c} for c in ("duo_0", "duo_1", "trio_0", "trio_1", "trio_2", "solo_0", "half_1", "duo_0",
                               "gap_0", "gap_1", "gap_3")]
fails = []
for sizes, want in (((2,), ["duo", "gap"]), ((3,), ["trio"]), ((2, 3), ["duo", "gap", "trio"]), ((1,), ["solo"])):
    got = pb.clip_bases(rows, sizes)
    if got != want:
        fails.append("clip_bases %s: want %s (a cast counted to its first gap, once), got %s" % (sizes, want, got))

# The body each actor is solved on: its one row, else a man on _0 and a woman after.
both = lambda c: [{"clip": c, "sex": "f"}, {"clip": c, "sex": "m"}]
every = {"a_0": both("a_0"), "a_1": both("a_1"), "a_2": both("a_2"),
         "b_0": [{"clip": "b_0", "sex": "f"}], "b_1": [{"clip": "b_1", "sex": "f"}],
         "c_0": [{"clip": "c_0", "sex": "f"}], "c_1": both("c_1")}
for base, want in (("a", "mff"), ("b", "ff"), ("c", "ff"), ("none", "")):
    got = "".join(r["sex"] for r in pb.cast_rows(every, base))
    if got != want:
        fails.append("cast_rows %s: %s, want %s" % (base, got, want))

# A stray actor no scene casts ends a cast whose earlier actors a scene does; a cast nobody casts runs to its gap.
rows = [{"clip": c, "known": k} for c, k in (("kissmf_0", True), ("kissmf_1", True), ("kissmf_2", False),
                                              ("free_0", False), ("free_1", False), ("free_2", False))]
for sizes, want in (((2,), ["kissmf"]), ((3,), ["free"])):
    if pb.clip_bases(rows, sizes) != want:
        fails.append("clip_bases %s over a stray actor: want %s, got %s" % (sizes, want, pb.clip_bases(rows, sizes)))
every = {r["clip"]: [dict(r, sex=s) for s in "fm"] for r in rows}
got = "".join(r["sex"] for r in pb.cast_rows(every, "kissmf"))
if got != "mf":
    fails.append("cast_rows over a stray actor: %s, want mf" % got)

# A scene-cast actor on both bodies: OStim's name says which (one clip, many castings), else the pack's own body.
every = {"x_mmmf_s1_%d" % n: [{"sex": "f", "known": True}, {"sex": "m", "known": True}] for n in range(4)}
every.update({"x_ff_%d" % n: [{"sex": "m", "known": True}, {"sex": "f", "known": True}] for n in range(2)})
every.update({"y_%d" % n: [{"sex": s, "known": True}, {"sex": "fm".replace(s, ""), "known": True}] for n, s in
              enumerate("fm")})
# the pack's own body is the actor's Skyrim sex, whichever row the manifest lists first
every.update({"z_%d" % n: [{"sex": "f", "known": True, "srcSex": s}, {"sex": "m", "known": True, "srcSex": s}]
              for n, s in enumerate("mf")})
for base, want in (("x_mmmf_s1", "mmmf"), ("x_ff", "ff"), ("y", "fm"), ("z", "mf")):
    got = "".join(r["sex"] for r in pb.cast_rows(every, base))
    if got != want:
        fails.append("cast_rows of a scene-cast %s: %s, want %s" % (base, got, want))
for f in fails:
    print("FAIL", f)
print("test_pair_batch:", "FAILED" if fails else "ok")
sys.exit(1 if fails else 0)
