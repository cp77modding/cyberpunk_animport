"""Reading any OStim pack: a scene's clip comes from the set beside it; SexLab's scene tags are lower case."""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import skyrim_scenes_ostimng as ng  # noqa: E402
import skyrim_scenes_slal as sl  # noqa: E402

fails = []


def want(what, got, exp):
    if got != exp:
        fails.append("%s: %r, want %r" % (what, got, exp))


# another pack: animations/MLC/MLCBed beside scenes/MLCBed
want("pack folder above the scene's", ng.same_place("mlc_mlcbed", ["mlcbed"], "mlc"), True)
want("another folder's set", ng.same_place("mlc_mlcbench", ["mlcbed"], "mlc"), False)
want("a scene loose in scenes/", ng.same_place("mlc_mlcbed", [], "mlc"), False)
# OStimNG: the same three folders on both sides
want("ostimng same folders", ng.same_place("ostim2p_mf_idle", ["ostim2p", "mf", "idle"], "ostimng"), True)
want("ostimng other folders", ng.same_place("ostim2p_ff_idle", ["ostim2p", "mf", "idle"], "ostimng"), False)

with tempfile.TemporaryDirectory() as d:
    path = os.path.join(d, "x.slsb.json")
    pos = [{"sex": {"female": True}, "race": "Human", "event": ["A"]},
           {"sex": {"male": True}, "race": "Human", "event": ["B"]}]
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"scenes": {"s": {"id": "s", "name": "S", "root": "a", "graph": {"a": {"dest": ["b"]}, "b": {"dest": []}},
                                    "stages": [{"id": "a", "tags": ["Vaginal", "Cowgirl"], "positions": pos},
                                               {"id": "b", "tags": [], "positions": pos}]}}}, f)
    s = sl.slsb_scenes(path, d)[0]
    want("scene tags lower case", s["tags"], ["vaginal", "cowgirl"])
    m = sl.man_first(s)
    want("man first", [a["sex"] for a in m["actors"]], [["m"], ["f"]])
    want("his clip moves with him", m["anims"][0]["events"], ["B", "A"])
    want("a stage with no tags rates from them", [x["type"] for x in sl.rate(s["anims"][1]["tags"] or s["tags"],
                                                                            ["f", "m"])[1]], ["penetrative"])

for x in fails:
    print("FAIL " + x)
print("%d checks failed" % len(fails) if fails else "ok")
sys.exit(1 if fails else 0)
