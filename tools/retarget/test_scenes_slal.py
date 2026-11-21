"""skyrim_scenes_slal.rate: a SexLab stage's tags as postures, acts and furniture; unrated where they cannot say who."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import skyrim_scenes_slal as sl  # noqa: E402

fails = []


def want(what, got, exp):
    if got != exp:
        fails.append("%s: %r, want %r" % (what, got, exp))


p, a, f = sl.rate(["vaginal", "cowgirl", "chair", "handjob"], ["f", "m"])
want("cowgirl on a chair", p, ["kneeling", "sitting"])
want("its acts", [(x["type"], x["actor"], x["target"]) for x in a], [("penetrative", "b", "a"), ("manual", "a", "b")])
want("its furniture", f, "chair")
p, a, f = sl.rate(["missionary", "anal"], ["m", "f"])
want("missionary, man first", p, ["kneeling", "lyingback"])
want("its giver", [(x["actor"], x["target"]) for x in a], [("a", "b")])
want("no furniture", f, None)
p, a, _ = sl.rate(["blowjob"], ["f", "m"])
want("blowjob", (p, [(x["type"], x["actor"]) for x in a]), (["kneeling", "standing"], [("oral_penis", "a")]))
p, a, _ = sl.rate(["vaginal", "cowgirl"], ["f", "f"])
want("two women: who gives is unknown", (p, a), ([None, None], []))
p, a, f = sl.rate(["vaginal", "bed"], ["f", "m", "m"])
want("three actors: unrated, furniture kept", (p, a, f), ([None, None, None], [], "bed"))

for x in fails:
    print("FAIL " + x)
print("%d checks failed" % len(fails) if fails else "ok")
sys.exit(1 if fails else 0)
