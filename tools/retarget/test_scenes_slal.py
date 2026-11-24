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
want("three actors: no postures, furniture kept", (p, f), ([None, None, None], "bed"))
want("mmf: the woman takes the first man", [(x["type"], x["actor"], x["target"]) for x in a],
     [("penetrative", "b", "a")])
_, a, _ = sl.rate(["vaginal", "ffm"], ["m", "f", "f"])
want("ffm: each woman with the man", [(x["actor"], x["target"]) for x in a], [("a", "b"), ("a", "c")])
_, a, _ = sl.rate(["blowjob"], ["m", "m", "f", "m"])
want("4P oral: the woman gives", [(x["type"], x["actor"], x["target"]) for x in a], [("oral_penis", "c", "a")])
want("three women: none", sl.rate(["vaginal"], ["f", "f", "f"])[1], [])
want("a kiss in a group: none", sl.rate(["kissing"], ["m", "f", "f"])[1], [])
want("the piece from the name", sl.rate(["vaginal", "ffm"], ["m", "f", "f"], "Anubs_adult_rbed2 Royal Bed 2")[2], "bed")
want("a sofa is a bench", sl.furniture_of(["furniture"], "Anubs_a_sofa Adult Sofa"), ("bench", False))
want("a stool is a chair", sl.furniture_of([], "Anubs_adult_stool Adult Bar Stool"), ("chair", False))
want("camel case split", sl.furniture_of([], "Anubs_BoundTable"), ("table", False))
want("a pillory has no place", sl.furniture_of(["furniture"], "Anubs_x x Pillory"), ("pillory", True))
want("furniture tag alone has no place", sl.furniture_of(["furniture", "doggy"], "Anubs_y"), (None, True))
want("a bedsleep is not matched by 'bed' inside a word", sl.furniture_of([], "Anubs_a_bedsleep Adult Bed Sleep"),
     ("bed", False))
want("embed is no bed", sl.furniture_of([], "Anubs_embed"), (None, False))
want("rbed2 in the id is a bed", sl.furniture_of([], "Anubs_adult_rbed2"), ("bed", False))
want("RBed is a bed", sl.furniture_of([], "RBed"), ("bed", False))
want("a cage on a bed: bed, never random", sl.furniture_of([], "Bed Cage"), ("bed", True))
want("a bed tagged furniture is a placed bed", sl.furniture_of(["furniture"], "Lux Bed"), ("bed", False))
want("tags in any case", sl.furniture_of(["Bed"], ""), ("bed", False))
want("barrel is no bar table", sl.furniture_of([], "Anubs_barrel_mast"), ("barrel", True))
want("a chair in the name seats the cowgirl's man", sl.rate(["vaginal", "cowgirl"], ["m", "f"], "Anubs_a_chair_cg")[0],
     ["sitting", "kneeling"])
want("the author's tag is dropped", sl.shown_name({"id": "Anubs_lustcowgirl", "name": "Anubs  Lust Cowgirl"}),
     "Lust Cowgirl")
want("a name that is only the tag stays", sl.shown_name({"id": "Anubs_x", "name": "Anubs"}), "Anubs")
want("no tag, name kept", sl.shown_name({"id": "lustcowgirl", "name": "Lust Cowgirl"}), "Lust Cowgirl")
want("open floor", sl.furniture_of(["missionary"], "Anubs_missionary_r Missionary"), (None, False))

for x in fails:
    print("FAIL " + x)
print("%d checks failed" % len(fails) if fails else "ok")
sys.exit(1 if fails else 0)
