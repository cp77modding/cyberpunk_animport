"""make_integration.as_integration: only this pack's scenes, every own id under integrations.<pack>, others kept."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import make_integration as mi  # noqa: E402

scenes = {
    "mine.a": {"id": "mine.a", "moves": [{"to": "mine.b", "label": ""}, {"to": "opensex.x", "label": ""}],
               "next": None, "climax": {"a": "mine.b"}, "speeds": []},
    "mine.b": {"id": "mine.b", "moves": [], "next": "opensex.y", "speeds": []},
    "opensex.x": {"id": "opensex.x", "moves": [{"to": "mine.a", "label": ""}], "speeds": []},
    "minepack.c": {"id": "minepack.c", "moves": [], "speeds": []},
}
out = mi.as_integration(scenes, "mine")
fails = []


def want(what, got, exp):
    if got != exp:
        fails.append("%s: %r, want %r" % (what, got, exp))


want("ids", sorted(out), ["integrations.mine.a", "integrations.mine.b"])
a, b = out["integrations.mine.a"], out["integrations.mine.b"]
want("own move", a["moves"][0]["to"], "integrations.mine.b")
want("move into another pack", a["moves"][1]["to"], "opensex.x")
want("climax", a["climax"], {"a": "integrations.mine.b"})
want("next into another pack", b["next"], "opensex.y")
want("input untouched", scenes["mine.a"]["moves"][0]["to"], "mine.b")
want("workspot path", mi.workspot_path("mine", 3), "ncn\\workspots\\integrations\\mine\\ncn_mine_3p.workspot")

for f in fails:
    print("FAIL " + f)
print("%d checks failed" % len(fails) if fails else "ok")
sys.exit(1 if fails else 0)
