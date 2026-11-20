"""The scene list: what a source's reader hands every later stage, whatever the source's own format was.

A pack folder holds, beside its own scenes.json (the source's record, as read):
  source-map.json  [{clip, source, sets: [depot paths ending _ma/_wa/_pma/_pwa.anims], ...}]
  scene-list.json  [scene], each:
    id         "<pack>.<a>.<b>...": the scene file's path under data/scenes/, dots for folders; unique
    name, animator (or None), tags [str], furniture (or None)
    sources    [{pack, id: the source's own scene id, file, actions: [[type, actor index, target index]]}]
    actors     [{sex: m|f|any, tags: [str]}] by position; optional `posture` with `postureFrom` (fix|code): a
               posture for an actor whose tags name none
    speeds     [{clips: [clip ref or None per actor], playback: float, display: float or None}]
    transition bool; next: the source id it plays into, length: seconds (or None)
    moves      [{to: a source id, label (or None), priority (optional)}]
    acts       [{type, actor: a|b, target: a|b, into (optional)}]: what the arousal model rates, [] = nothing
    climax     optional {side: source id}; climaxFromMoves: optional, a move into a scene whose source id says
               climax is the man's climax; noRandom: optional
A clip ref is "<pack>/<clip>", "#<set>" appended when two of the pack's sets hold one clip name (clip_refs). A ref
to another pack's clip is that pack's ref. Readers write it with write(); check() names what breaks the shape.

Run: python tools/retarget/scene_list.py [source ...]   writes each build.json source's pack/scene-list.json
"""
import json
import os
import sys
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import build_config  # noqa: E402

BODY = {"_ma": ("m", "npc"), "_wa": ("f", "npc"), "_pma": ("m", "player"), "_pwa": ("f", "player")}
SEXES = {"m", "f", "any"}
SIDES = {"a", "b"}


def set_body(path):
    stem = os.path.basename(path.replace("\\", "/"))[:-len(".anims")]
    for suffix in ("_pma", "_pwa", "_ma", "_wa"):
        if stem.endswith(suffix):
            return stem[:-len(suffix)], BODY[suffix]
    raise ValueError("set with no body suffix: " + path)


def clip_refs(pack, rows):
    """[(ref, row)] for a pack's source-map rows: <pack>/<clip>, #<set> where two sets share the clip name"""
    names = Counter(r["clip"] for r in rows)
    return [("%s/%s" % (pack, r["clip"]) if names[r["clip"]] == 1
             else "%s/%s#%s" % (pack, r["clip"], set_body(r["sets"][0])[0]), r) for r in rows]


def check(scenes, pack):
    """[problem]: every scene in the shape above, ids unique and under the pack"""
    bad, seen = [], set()
    for i, s in enumerate(scenes):
        where = s.get("id") or "scene %d" % i
        if not isinstance(s.get("id"), str) or not s["id"].startswith(pack + "."):
            bad.append("%s: id must start %s." % (where, pack))
        if s.get("id") in seen:
            bad.append("%s: id repeats" % where)
        seen.add(s.get("id"))
        actors = s.get("actors")
        if not isinstance(actors, list) or not actors:
            bad.append("%s: no actors" % where)
            continue
        if any(a.get("sex") not in SEXES or not isinstance(a.get("tags"), list) for a in actors):
            bad.append("%s: an actor's sex is not m/f/any or its tags not a list" % where)
        for sp in s.get("speeds") or []:
            if len(sp.get("clips") or []) != len(actors):
                bad.append("%s: a speed's clips are not one per actor" % where)
            if not all(c is None or (isinstance(c, str) and "/" in c) for c in sp.get("clips") or []):
                bad.append("%s: a clip ref is not <pack>/<clip>" % where)
        if not s.get("sources") or any(not {"pack", "id", "file", "actions"} <= set(x) for x in s["sources"]):
            bad.append("%s: sources need pack, id, file, actions" % where)
        if any(a.get("actor") not in SIDES or a.get("target") not in SIDES for a in s.get("acts", [])):
            bad.append("%s: an act's actor/target is not a/b" % where)
        if any(not isinstance(m.get("to"), str) for m in s.get("moves", [])):
            bad.append("%s: a move has no target" % where)
        for k in ("transition", "tags"):
            if k not in s:
                bad.append("%s: no %s" % (where, k))
    return bad


MANIFEST_KEYS = ("key", "file", "clip", "sex", "rig", "npcSet", "playerRig", "playerSet")


def check_manifest(rows):
    """[problem] in a reader's manifest.json: the work list every stage after it reads. Optional: `skeleton`
    (OpenSex's rows take theirs from the stage) and `srcSex`, the skeleton's sex (the row's own when absent)."""
    bad = []
    if not isinstance(rows, list) or not rows:
        return ["manifest.json is empty or not a list"]
    for i, r in enumerate(rows):
        miss = [k for k in MANIFEST_KEYS if not r.get(k)]
        if miss:
            bad.append("row %d (%s): no %s" % (i, r.get("key"), ", ".join(miss)))
        elif r["sex"] not in ("m", "f") or r.get("srcSex", r["sex"]) not in ("m", "f"):
            bad.append("row %d (%s): sex and srcSex are m or f" % (i, r["key"]))
        else:
            try:
                set_body(r["npcSet"])
                set_body(r["playerSet"])
            except ValueError as e:
                bad.append("row %d (%s): %s" % (i, r["key"], e))
    return bad


def write(path, scenes, pack):
    bad = check(scenes, pack)
    if bad:
        raise ValueError("%s: %d problems, first: %s" % (path, len(bad), "; ".join(bad[:5])))
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(scenes, fh, indent=1, ensure_ascii=False)
        fh.write("\n")


def readers():
    """build.json's inventory name -> (pack folder, source input) -> scene list"""
    import skyrim_scenes
    import skyrim_scenes_ostimng
    import skyrim_scenes_slal
    return {"opensex": skyrim_scenes.scene_list, "ostimng": skyrim_scenes_ostimng.scene_list,
            "sexlab": skyrim_scenes_slal.scene_list}


def main():
    cfg = build_config.load()
    names = sys.argv[1:] or list(cfg["sources"])
    for n in names:
        s = build_config.source(n, cfg)
        fn = readers().get(s.get("inventory"))
        if fn is None:
            sys.exit("%s: no scene list reader for inventory %r" % (n, s.get("inventory")))
        scenes = fn(s["pack"], s["input"])
        pack = os.path.basename(s["pack"])
        write(os.path.join(s["pack"], "scene-list.json"), scenes, pack)
        print("%s: %d scenes -> %s" % (n, len(scenes), os.path.join(s["pack"], "scene-list.json")))


if __name__ == "__main__":
    main()
