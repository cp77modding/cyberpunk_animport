"""Which clip each actor of a pair plays, for any pack. OpenSex and OStim name a cast's clips <base>_0, <base>_1, ...;
any other pack's casts come from its scene-list.json, each named by its first actor's clip."""
import functools
import json
import os

import build_config

NAMED = ("opensex", "ostimng")   # the mod's own packs: cast by clip name, as they always were


@functools.lru_cache(None)
def scene_casts(pack):
    """{base: ([clip per actor], [sex per actor], scene)}: every speed of the pack's scenes whose actors all have a clip"""
    path = os.path.join(build_config.load()["packs"], pack, "scene-list.json")
    if pack in NAMED or not os.path.isfile(path):
        return {}
    out = {}
    for s in json.load(open(path, encoding="utf-8")):
        for speed in s["speeds"]:
            refs = speed["clips"]
            if not all(refs) or any(r.split("/", 1)[0] != pack or "#" in r for r in refs):
                continue
            clips = [r.split("/", 1)[1] for r in refs]
            out.setdefault(clips[0], (clips, [a["sex"] for a in s["actors"]], s))
    return out


def clips(pack, base):
    """the clip each actor of base plays, in cast order"""
    cast = scene_casts(pack).get(base)
    return cast[0] if cast else ["%s_%d" % (base, n) for n in range(2)]


def entry(pack, base):
    """her opening a cast's penetration goes into, from its scene's acts: 'vulva', 'anus', or None; KeyError when the
    pack casts by clip name"""
    acts = scene_casts(pack)[base][2].get("acts") or []
    pen = [a for a in acts if a["type"] == "penetrative"]
    if not pen:
        return None
    return "anus" if any(a.get("into") == "anus" for a in pen) else "vulva"
