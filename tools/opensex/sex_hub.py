"""Every scene a pair can play is two moves at most from a sex scene: the scene -> its cast's hub -> sex.

A one-time fix of our scene files' moves (docs/design/scene-graph.md §2.2a). The packs leave scenes three to six moves
from sex, and furniture and bed idles often never get there. Each such scene gets a move to its cast's hub, a standing
scene one move from sex; a hub further than that gets a move to every sex scene the cast can play. Two women's hub is
OpenSex's "Standing Together" (f/f), so only they see its moves. Idempotent; a move already there is left alone.

  python tools/opensex/sex_hub.py plan
  python tools/opensex/sex_hub.py write
"""
import argparse
import glob
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import scene_files  # noqa: E402
from cast_roles import write_json  # noqa: E402

ANIMS = scene_files.ANIMS
PACKS = ("opensex", "ostimng")
HUBS = {"ff": "opensex.ops.sta-sta.ho.lesbiananimationhub",
        "mf": "opensex.ops.sta-sta.ho.standingholding",
        "mm": "opensex.ops.sta-sta.ho.standingholding"}
MOST = 2
LABEL = "get closer"
UP = "get up"   # off furniture, the floor or a lap
SEX_ACTS = ("penetrative", "manual", "grinding", "mutual_oral")
SEX_CODES = {"sx", "bj", "boj", "fj", "hj", "vj", "vhj"}
CHAIN = 8   # SceneGraph's kMaxChain


def is_sex(s):
    """SceneGraph.cpp's IsSexScene: a rated act, else the pack's class code in the id."""
    p = s["id"].split(".")
    return any(a["type"] in SEX_ACTS or a["type"].startswith("oral") for a in s.get("acts") or []) or len(p) > 4 and (
        p[0] == "opensex" and p[3] in SEX_CODES or p[0] == "ostimng" and p[3] == "sexual")


def fits(s, cast, clips):
    """SceneGraph::Fits and Playable: the sexes in order, and every clip baked for that body."""
    if len(s["actors"]) != len(cast):
        return False
    if any(a["sex"] not in ("any", x) for a, x in zip(s["actors"], cast)):
        return False
    return all(c in clips and x in clips[c] for sp in s["speeds"] for c, x in zip(sp["clips"], cast))


def posture(s):
    return "/".join(a.get("posture") or "" for a in s["actors"])


def lands(scenes, to, cast, clips):
    """SceneGraph::Follow: where a move into `to` rests, past its transitions; None = it cannot play."""
    for _ in range(CHAIN + 1):
        s = scenes.get(to)
        if s and s.get("transition") and not fits(s, cast, clips):
            to = s.get("next")
            continue
        if not s or not fits(s, cast, clips):
            return None
        if not s.get("transition"):
            return to
        to = s.get("next")
    return None


def to_sex(scenes, cast, clips, ok):
    """Each playable scene's fewest moves to a sex scene, None = never."""
    out = {i: 0 for i, s in ok.items() if is_sex(s)}
    edges = {i: {t for m in s.get("moves") or [] if (t := lands(scenes, m["to"], cast, clips)) and t != i}
             for i, s in ok.items()}
    for d in range(1, len(ok)):
        new = {i: d for i in ok if i not in out and any(out.get(t) == d - 1 for t in edges[i])}
        if not new:
            break
        out.update(new)
    return {i: out.get(i) for i in ok}


def plan(scenes, clips, cast):
    """(the scenes that gain a move to the cast's hub, the sex scenes the hub gains a move to)."""
    hub = HUBS[cast]
    ok = {i: s for i, s in scenes.items() if not s.get("transition") and fits(s, cast, clips)}
    if hub not in ok:
        return [], []
    d = to_sex(scenes, cast, clips, ok)
    sex = sorted(i for i, s in ok.items() if is_sex(s)) if d[hub] is None or d[hub] > MOST - 1 else []
    reach = 1 if sex else d[hub] + 1
    starts = sorted(i for i in ok if i != hub and (d[i] is None or d[i] > MOST) and reach <= MOST)
    return starts, sex


def rests(scenes, to):
    """Where a move into `to` comes to rest past its transitions, whoever plays them."""
    for _ in range(CHAIN + 1):
        s = scenes.get(to)
        if not s or not s.get("transition"):
            return to
        to = s.get("next")
    return None


def add_move(scenes, s, to, hub):
    """True when s gained a move to `to`: one through a transition that rests there counts as there."""
    if any(rests(scenes, m["to"]) == to for m in s.get("moves") or []):
        return False
    label = (LABEL if posture(s) == "standing/standing" and not s.get("furniture") else UP) if to == hub else None
    s.setdefault("moves", []).append({"to": to, "label": label})
    return True


def load():
    scenes, files, clips = {}, {}, {}
    for pack in PACKS:
        for f in glob.glob(os.path.join(ANIMS, pack, scene_files.SCENES_REL, "**", "*.json"), recursive=True):
            j = json.load(open(f, encoding="utf-8"))
            if os.path.basename(f) == "clips.json":
                clips.update(j)
            else:
                scenes[j["id"]], files[j["id"]] = j, f
    return scenes, files, clips


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("step", choices=("plan", "write"))
    a = ap.parse_args()
    scenes, files, clips = load()
    changed = set()
    for cast, hub in HUBS.items():
        if hub not in scenes:
            sys.exit("no hub scene %s" % hub)
        starts, sex = plan(scenes, clips, cast)
        print("%s: %d scenes -> %s, hub -> %d sex scenes" % (cast, len(starts), hub, len(sex)))
        if a.step == "write":
            changed |= {i for i in starts if add_move(scenes, scenes[i], hub, hub)}
            changed |= {hub} if sum(add_move(scenes, scenes[hub], x, hub) for x in sex) else set()
    for i in sorted(changed):
        write_json(files[i], scenes[i])
    if a.step == "write":
        print("written: %d scene files" % len(changed))


if __name__ == "__main__":
    main()
