"""Our scene files: one per scene, from each build.json source's scene list (docs/design/scene-graph.md §2).

Written into each CyberpunkAnimations pack at <pack>/bin/.../mods/nightcitynet/data/scenes/<pack>/, so the pack's zip
installs them into our data folder. The first version is generated; from then on the files are ours, so this refuses
to overwrite them unless --force. Every pack's input is its scene-list.json (tools/retarget/scene_list.py, written by
the source's reader): nothing here knows a source's own format. A scene's id is its path under data/scenes/. A clip is
"<pack>/<clip>", resolved to its sets by that pack's clips.json.

A scene made only of an earlier pack's clips, cast the same, is that pack's scene: it becomes an alias and its moves
join that scene's, which is what links two packs' graphs. A scene with no playable speed (a redirect, a menu hub) is an
alias for its one way out, else dropped. Everything dropped is printed.

Run: python tools/opensex/scene_files.py [--anims DIR] [--force]
     --acts: only mark each manual act's body part (`with`) and the scene's `kiss` in the files as they are, from the
             packs' scene lists.
"""
import argparse
import json
import os
import re
import sys
from collections import Counter

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "tools", "retarget"))
import build_config  # noqa: E402
import scene_list  # noqa: E402

ANIMS = build_config.load()["packs"]
# Inside a pack, at the game-root path of our data folder: the pack's zip installs them where the mod reads data.
SCENES_REL = os.path.join("bin", "x64", "plugins", "cyber_engine_tweaks", "mods", "nightcitynet", "data", "scenes")
BODY = scene_list.BODY
SIDES = "ab"
set_body = scene_list.set_body
# What a manual act is done with, from the sources' action types. The shaft aims only into a hand (shaft-bones.md
# §2.4). Fingers in an opening are not a fist round a shaft: "fingers", so a man fingered is never aimed into a hand.
WITH = {"handjob": "hand", "malemasturbation": "hand", "femalemasturbation": "hand", "vaginalfingering": "fingers",
        "analfingering": "fingers", "rubbingclitoris": "fingers", "boobjob": "breasts", "buttjob": "butt", "footjob": "feet",
        "thighjob": "thighs"}
# A kiss, from the sources' action types: on the mouth, else on the body. OSSO sounds `kissing` with its kiss and the
# rest with its skin kiss (intimacy-sound.md §5.11).
KISS = {"kissing": "mouth", "frenchkissing": "mouth", "kissingcheek": "skin", "kissingneck": "skin",
        "kissingfoot": "skin", "kissingfeet": "skin", "kissinghand": "skin"}
# A giver of oral who licks rather than sucks holds this mouth set over the act's (docs/design/mouth-hold.md).
LICK_MOUTH = {"oral_penis": "lollipop"}
# A word of its own (CamelCase or after a non-letter): not the "lick" in Click, not a tongue kiss.
LICK_WORDS = re.compile(r"(?:Lick|Tongue|(?<![A-Za-z])(?:lick|tongue))(?!_?[Kk]iss)")
# One posture per actor, from its tags. Two on one actor (bendover + standing) keep the first in this order, the more
# particular one; every other tag is a mod (facingaway, ontop, ...). An actor with none takes its reader's posture.
POSTURES = ["bendover", "allfours", "handstanding", "suspended", "lyingback", "lyingfront", "lyingside", "squatting",
            "kneeling", "sitting", "standing"]
MODS = {"facingaway", "ontop", "onbottom", "climaxing", "drowsy", "kissing", "nostrip", "spreadlegs"}


def packs():
    """[(pack name, pack folder)] in build.json's source order: an earlier pack's scene takes a later one's alias"""
    return [(os.path.basename(s["pack"]), s["pack"]) for s in build_config.load()["sources"].values()]


def read_clips(anims, names=None):
    """{ref: {sex: {npc, player}}}, and {pack: {clip: [(set, ref)]}}"""
    clips, refs = {}, {}
    for pack in names or [p for p, _ in packs()]:
        rows = json.load(open(os.path.join(anims, pack, "source-map.json"), encoding="utf-8"))
        for ref, r in scene_list.clip_refs(pack, rows):
            for s in r["sets"]:
                _, (sex, side) = set_body(s)
                clips.setdefault(ref, {}).setdefault(sex, {})[side] = s
            refs.setdefault(pack, {}).setdefault(r["clip"], []).append((set_body(r["sets"][0])[0], ref))
    return clips, refs


def read_lists(anims, names):
    """every pack's scene list, in order, and {(pack, source id): [(type, actor, target)]}"""
    lists, actions = [], {}
    for pack in names:
        rows = json.load(open(os.path.join(anims, pack, "scene-list.json"), encoding="utf-8"))
        bad = scene_list.check(rows, pack)
        if bad:
            sys.exit("%s's scene-list.json: %d problems, first: %s" % (pack, len(bad), "; ".join(bad[:5])))
        for s in rows:
            for src in s["sources"]:
                actions[src["pack"], src["id"]] = [(t, a, g) for t, a, g in src.pop("actions")
                                                   if isinstance(a, int) and isinstance(g, int)]
        lists.append((pack, rows))
    return lists, actions


def scene_path(out, sid):
    """The id is the path under data/scenes/: opensex.ops.sta-sta.ho.x -> opensex/ops/sta-sta/ho/x.json."""
    return os.path.join(out, *sid.split(".")) + ".json"


def mark_with(s, actions, notes):
    """Each manual act's body part, from the first source that names an act for its sides; True = an act changed."""
    letters = "abcdefgh"
    parts = {}
    for src in s.get("sources", []):
        for t, a, g in actions.get((src["pack"], src["id"]), []):
            if t in WITH and a < len(letters) and g < len(letters):
                parts.setdefault((letters[a], letters[g]), WITH[t])
    changed = False
    for act in s.get("acts", []):
        if act.get("type") != "manual":
            continue
        part = parts.get((act["actor"], act["target"]))
        if not part:
            notes.append("manual act with no part in its sources: %s %s->%s" % (s["id"], act["actor"], act["target"]))
        elif act.get("with") != part:
            act["with"] = part
            changed = True
    return changed


def mark_kiss(s, actions):
    """The scene's kiss from its sources' actions, a mouth kiss over a skin one; True = it changed. None found leaves it."""
    found = {KISS[t] for src in s.get("sources", []) for t, _, _ in actions.get((src["pack"], src["id"]), [])
             if t in KISS}
    kiss = "mouth" if "mouth" in found else "skin" if found else None
    if not kiss or s.get("kiss") == kiss:
        return False
    s["kiss"] = kiss
    return True


def lick_mouth(acts, licking):
    """The giver's mouth when the scene licks (lick/tongue in a source id); {} = the act's."""
    if not licking:
        return {}
    return {a["actor"]: LICK_MOUTH[a["type"]] for a in acts if a["type"] in LICK_MOUTH}


def normalise_actors(s, report, notes):
    """Each actor's `posture` and `mods` beside its raw `tags`; the reader's posture, if any, is dropped here."""
    for i, a in enumerate(s["actors"]):
        hint, frm = a.pop("posture", None), a.pop("postureFrom", None)
        tags = [t.lower() for t in a["tags"]]
        found = [p for p in POSTURES if p in tags]
        posture = hint if frm == "fix" else found[0] if found else hint
        if frm == "fix":
            report["actors whose posture is fixed by hand"] += 1
        elif not found and posture:
            report["actors whose posture is the id's code"] += 1
        elif not posture:
            notes.append("no posture: %s actor %d %s" % (s["id"], i, a["tags"]))
            report["actors with no posture"] += 1
        a["posture"] = posture
        a["mods"] = sorted({t for t in tags if t in MODS})
        for t in tags:
            if t not in MODS and t not in POSTURES and t != "lying":
                notes.append("unknown actor tag %r: %s actor %d" % (t, s["id"], i))
                report["unknown actor tags"] += 1


def stages(speeds, actors, clips, report):
    """A scene's speeds with a file for every actor, none repeated."""
    # An actor with a file at one speed only keeps it at the others (inferred: the source names no file for them).
    for i in range(actors):
        have = next((sp["clips"][i] for sp in speeds if sp["clips"][i] in clips), None)
        for sp in speeds:
            if have and sp["clips"][i] not in clips:
                sp["clips"][i] = have
                report["clips filled from the actor's slowest speed (inferred)"] += 1
    whole = [sp for sp in speeds if sp["clips"] and all(c and c in clips for c in sp["clips"])]
    report["speeds dropped, a clip with no file"] += len(speeds) - len(whole)
    # The same clips at the same rate is one stage: a start anim with no files filled as the first speed, or a
    # speed that names a slower one's anim. The one with a shown speed stays, where the first came.
    out = []
    for sp in whole:
        same = next((i for i, o in enumerate(out)
                     if o["clips"] == sp["clips"] and o["playback"] == sp["playback"]), None)
        if same is None:
            out.append(sp)
            continue
        if out[same]["display"] is None:
            out[same] = sp
        report["speeds dropped, a repeat of another"] += 1
    return out


def build(anims, names=None):
    names = names or [p for p, _ in packs()]
    clips, _ = read_clips(anims, names)
    lists, actions = read_lists(anims, names)
    report = Counter()
    notes = []
    every = [s for _, rows in lists for s in rows]
    for s in every:
        s["speeds"] = stages(s["speeds"], len(s["actors"]), clips, report)

    # source id -> our id, case-blind (OpenSex links OStimNG scenes as "OStim2PMIssionaryIdleMF"); an alias points
    # at another scene's source id until resolved
    to_ours = {s["sources"][0]["id"].lower(): s["id"] for s in every}
    # a ported pack's link goes to its own scene first: its file may share a name with the mod's packs'
    own_ids = {(s["id"].split(".")[0], s["sources"][0]["id"].lower()): s["id"] for s in every
               if s["id"].split(".")[0] not in ("opensex", "ostimng")}

    def ours(source, pack):
        return own_ids.get((pack, source.lower())) or to_ours.get(source.lower(), source)
    alias, by_clips, scenes = {}, {}, {}
    for k, (pack, rows) in enumerate(lists):
        earlier = {p for p, _ in lists[:k]}
        for s in rows:
            same = None
            owner = {c.split("/")[0] for sp in s["speeds"] for c in sp["clips"]}
            if s["speeds"] and len(owner) == 1 and owner <= earlier:
                sexes = tuple(a["sex"] for a in s["actors"])
                key = tuple(tuple(sp["clips"]) for sp in s["speeds"])
                same = by_clips.get((sexes, key)) or next(
                    (o for (sx, kk), o in by_clips.items()
                     if kk == key and all(a in (b, "any") for a, b in zip(sexes, sx))), None)
            if same is not None:
                alias[s["id"]] = same["id"]
                same["sources"] += s["sources"]
                same["moves"] += s["moves"]
                if s.get("climax"):
                    same.setdefault("climax", {}).update(s["climax"])
                if not same.get("acts") and s.get("acts"):   # an earlier scene that rates nothing takes this one's
                    same["acts"] = s["acts"]
                for sp, osp in zip(s["speeds"], same["speeds"]):
                    osp["playback"], osp["display"] = sp["playback"], osp["display"] or sp["display"]
                report["scenes that are an earlier pack's scene"] += 1
            else:
                scenes[s["id"]] = s
        for s in rows:
            if s["id"] in scenes and s["speeds"]:
                by_clips.setdefault((tuple(a["sex"] for a in s["actors"]),
                                     tuple(tuple(sp["clips"]) for sp in s["speeds"])), s)

    for sid, s in list(scenes.items()):
        if s["speeds"]:
            continue
        out = [s["next"]] if s["transition"] and s["next"] else [m["to"] for m in s["moves"]]
        if len(set(out)) == 1:
            alias[sid] = ours(out[0], sid.split(".")[0])
            report["scenes with no playable speed, an alias for their one way out"] += 1
        else:
            notes.append("dropped, no playable speed and %d ways out: %s" % (len(set(out)), sid))
            report["scenes dropped, no playable speed"] += 1
        del scenes[sid]

    def resolve(source, pack=None):
        sid = ours(source, pack)
        seen = set()
        while sid in alias and sid not in seen:
            seen.add(sid)
            sid = alias[sid]
        return sid if sid in scenes else None

    for s in scenes.values():
        moves, seen = [], {}
        here = s["id"].split(".")[0]
        for m in s["moves"]:
            if m["to"].startswith("$"):   # a menu command ($InviteScan, $RemoveActor): a cast change
                report["moves dropped, a menu command"] += 1
                continue
            to = resolve(m["to"], here)
            if to is None:
                notes.append("move to a missing scene: %s -> %s" % (s["id"], m["to"]))
                report["moves dropped, missing scene"] += 1
            elif to in seen:
                seen[to]["label"] = seen[to]["label"] or m["label"]
                if "priority" in m and "priority" not in seen[to]:
                    seen[to]["priority"] = m["priority"]
            elif to != s["id"]:
                seen[to] = {"to": to, "label": m["label"]}
                if "priority" in m:
                    seen[to]["priority"] = m["priority"]
                moves.append(seen[to])
        s["moves"] = moves
        climax = {side: resolve(to, here) for side, to in (s.get("climax") or {}).items()}
        # a move into a scene whose source id says climax is the man's climax from here
        if s.pop("climaxFromMoves", False):
            for m in moves:
                sid = scenes[m["to"]]["sources"][0]["id"].lower()
                if "climax" in sid and "afterclimax" not in sid:
                    sexes = [a["sex"] for a in s["actors"]]
                    if len(sexes) == 2 and sexes.count("m") == 1:
                        climax.setdefault(SIDES[sexes.index("m")], m["to"])
        climax = {side: to for side, to in climax.items() if to and to != s["id"]}
        normalise_actors(s, report, notes)
        mark_with(s, actions, notes)
        mark_kiss(s, actions)
        mouth = lick_mouth(s["acts"], any(LICK_WORDS.search(src["id"]) for src in s["sources"]))
        if mouth:
            s["mouth"] = mouth
            report["scenes that lick, holding their own mouth"] += 1
        s.pop("climax", None)
        if climax:
            s["climax"] = climax
            report["scenes with a climax"] += 1
        if s["transition"]:
            s["next"] = resolve(s["next"], here) if s["next"] else None
            if s["next"] is None:
                notes.append("transition with no next: %s" % s["id"])
                report["transitions with no next, played as a loop"] += 1
                s["transition"] = False
    used = {c for s in scenes.values() for sp in s["speeds"] for c in sp["clips"]}
    return scenes, {r: clips[r] for r in sorted(used)}, report, notes


def mark_files(files, actions):
    """--acts: the hand-edited files keep every byte but the parts; a file the writer would reformat is refused."""
    notes, changed = [], 0
    for f in files:
        if os.path.basename(f) == "clips.json":
            continue
        with open(f, encoding="utf-8", newline="") as fh:
            text = fh.read()
        s = json.loads(text)
        if json.dumps(s, indent=1, ensure_ascii=False) + "\n" != text:
            notes.append("not in the writer's format, left alone: %s" % f)
            continue
        withs = mark_with(s, actions, notes)
        if mark_kiss(s, actions) or withs:
            with open(f, "w", encoding="utf-8", newline="\n") as fh:
                json.dump(s, fh, indent=1, ensure_ascii=False)
                fh.write("\n")
            changed += 1
    for n in notes:
        print(n)
    print("%d scene files marked" % changed)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--anims", default=ANIMS)
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--acts", action="store_true", help="only mark each manual act's body part and the kiss in the files")
    a = ap.parse_args()
    names = [p for p, _ in packs()]
    roots = {p: os.path.join(a.anims, p, SCENES_REL) for p in names}
    old = [os.path.join(d, f) for r in roots.values() for d, _, fs in os.walk(r) for f in fs if f.endswith(".json")]
    if a.acts:
        return mark_files(old, read_lists(a.anims, names)[1])
    if old and not a.force:
        sys.exit("scene files exist under %s and are hand-edited from here on; --force to regenerate" % a.anims)
    scenes, clips, report, notes = build(a.anims, names)
    for f in old:
        if os.path.basename(f) != "clips.json":   # climax_events.py's field: the clip's, not this build's
            with open(f, encoding="utf-8") as fh:
                s = json.load(fh)
            if s["id"] in scenes:
                if "climax_at" in s:
                    scenes[s["id"]]["climax_at"] = s["climax_at"]
                scenes[s["id"]]["name"] = s.get("name", scenes[s["id"]]["name"])   # names are hand-corrected
        os.remove(f)
    for r in roots.values():
        for d, _, _ in sorted(os.walk(r), reverse=True):
            if not os.listdir(d):
                os.rmdir(d)
    for sid, s in sorted(scenes.items()):
        path = scene_path(roots[sid.split(".")[0]], sid)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(s, fh, indent=1, ensure_ascii=False)
            fh.write("\n")
    # Each pack's clips.json holds the clips its own archive carries; a scene's earlier-pack half needs that pack's.
    for pack, r in roots.items():
        mine = {c: v for c, v in clips.items() if c.startswith(pack + "/")}
        os.makedirs(os.path.join(r, pack), exist_ok=True)
        with open(os.path.join(r, pack, "clips.json"), "w", encoding="utf-8", newline="\n") as fh:
            json.dump(mine, fh, indent=1)
            fh.write("\n")
    for n in notes:
        print(n)
    heads = Counter(len(s["actors"]) for s in scenes.values())
    print("%d scenes (%s), %d clips, %d moves, %d transitions" % (
        len(scenes), ", ".join("%dP %d" % kv for kv in sorted(heads.items())), len(clips),
        sum(len(s["moves"]) for s in scenes.values()), sum(s["transition"] for s in scenes.values())))
    for k, v in sorted(report.items()):
        print("  %s: %d" % (k, v))


if __name__ == "__main__":
    main()
