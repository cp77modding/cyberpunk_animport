"""OpenSex's scene XML and clip files as the port's inventory: which clip is which actor, of which sex, in which set.

A scene's <actors> list its actors by position; a clip is <anim id> + "_<position>" (_Cr-MountedGrind_S2_1 is
actor 1 of _Cr-MountedGrind_S2). An actor with a penisAngle is male, except in a solo scene, where every actor has
one and the scene's name says Female or Male. A clip no scene names (the redressing clips, a few unreferenced
ones), or a solo scene's whose name says neither, has no known sex and is baked onto both bodies.

OpenSex's only woman-and-woman scenes were deleted upstream (140a6680) while their clips stayed; RESTORED reads
them back from the commit before, in place of the OPrivacy redirect that took over one of their files.

Sets group clips by their folder under anim/<module>/ (StaSta, LyBKne, ...), one set per folder and body.

Run: python tools/retarget/skyrim_scenes.py <OpenSex root> <out dir>   (root: a full git clone, for RESTORED)
  writes manifest.json (the port's work list), scenes.json and source-map.json (the pack's).
"""
import json
import os
import re
import subprocess
import sys
import xml.etree.ElementTree as ET

ANIM_ROOT = os.path.join("meshes", "0SA", "mod", "0Sex", "anim")
SCENE_ROOT = os.path.join("meshes", "0SA", "mod", "0Sex", "scene")
RIG = {"m": ("man_base", "ma", "player_man", "pma"), "f": ("woman_base", "wa", "player_woman", "pwa")}
# Those files predate <actors> and <metadata>, so each cast is given here: (tags, sex) per position, as the id's codes
# say; and the scene's tags (the hub is where a cast starts, as standing.xml is: idle, intro); and the name, where
# theirs is wrong (the cunnilingus file is titled "Breast Groping").
RESTORED_AT = "140a6680^"
RESTORED = {
    "OpS/StaSta/Ho/LesbianAnimationHub.xml": ("Standing Together", ["idle", "intro"],
                                              [("standing", "f"), ("standing", "f")]),
    "OpS/KneLyB/VJ/LesbianKneLyBCunnilingus.xml": ("Kneeling Cunnilingus", [], [("kneeling", "f"), ("lyingback", "f")]),
    "OpS/LyBAFo/VHJ/AceLesbian69Fingering.xml": (None, [], [("lyingback", "f"), ("allfours", "f")]),
}


def source_sex(body, cast):
    """The sex whose skeleton a clip is decoded against: its one cast sex, else the body's (cast as both, or by nobody)."""
    return next(iter(cast)) if len(cast) == 1 else body


def clip_files(root):
    out = {}
    base = os.path.join(root, ANIM_ROOT)
    for d, _, fs in os.walk(base):
        for f in fs:
            if f.lower().endswith(".hkx"):
                rel = os.path.relpath(os.path.join(d, f), root)
                parts = os.path.relpath(d, base).split(os.sep)
                group = parts[1] if parts[0] == "OpS" and len(parts) > 1 else "_".join(parts[:2])
                key = f[:-4].lower()
                if key in out:
                    raise ValueError("two clips named %s: %s, %s" % (key, out[key]["file"], rel))
                out[key] = {"file": rel.replace(os.sep, "/"), "stem": f[:-4], "set": group.lower()}
    return out


def attrs(el, keep):
    return {k: el.get(k) for k in keep if el.get(k) is not None}


def read_scene(path, root):
    with open(path, "rb") as fh:
        return parse_scene(fh.read(), os.path.relpath(path, root).replace(os.sep, "/"))


def parse_scene(data, rel, cast=None):
    try:
        x = ET.fromstring(data)
    except ET.ParseError as e:
        raise ValueError("%s: %s" % (rel, e))
    # Older scene files name an anim 0SxOpS_X where its clip files are _X_<position>.
    for el in x.iter("anim"):
        if el.get("id"):
            el.set("id", re.sub(r"^0SxOpS_", "_", el.get("id")))
    actors = []
    found = x.find("actors")
    for a in found if found is not None else []:
        row = attrs(a, ("position", "penisAngle", "feetOnGround", "tags", "lookUp"))
        row["position"] = int(row["position"])
        row["sex"] = "m" if "penisAngle" in row else "f"
        actors.append(row)
    if cast:
        actors = [{"position": i, "tags": t, "sex": s} for i, (t, s) in enumerate(cast)]
    actors.sort(key=lambda r: r["position"])
    if len(actors) == 1 and not cast:
        # A solo scene's actor has a penisAngle whatever the sex (FemaleSoloStandingIdle too): its name decides,
        # and a name that says neither is either body.
        sid = (x.get("id") or "").lower()
        actors[0]["sex"] = "f" if "female" in sid else "m" if "male" in sid else None
    # The scene's own <anim> is the one it starts on; a <speed> block lists it again with the others.
    anims = {}
    for el in x.iter("anim"):
        row = anims.setdefault(el.get("id"), attrs(el, ("id", "t", "l", "dest")))
        sp = next((p for p in x.iter("sp") if el in list(p)), None)
        if sp is not None and sp.get("qnt") is not None:
            row["speed"] = float(sp.get("qnt"))
    first = x.find("anim")
    anims = list(anims.values())
    info = x.find("info")
    meta = x.find("metadata")
    return {
        "id": x.get("id"),
        "file": rel,
        "name": info.get("name") if info is not None else None,
        "animator": info.get("animator") if info is not None else None,
        "style": x.get("style"),
        "tags": [t for t in (meta.get("tags") or "").split(",") if t] if meta is not None else [],
        "actors": actors,
        "start": first.get("id") if first is not None else None,
        "anims": anims,
        "goes": sorted({o.get("go") for o in x.iter("option") if o.get("go")}),
        "actions": [attrs(a, ("type", "actor", "target")) for a in x.iter("action")],
    }


def restored_scene(root, at, rel, name, tags, cast):
    path = "%s/%s" % (SCENE_ROOT.replace(os.sep, "/"), rel)
    git = subprocess.run(["git", "-C", root, "show", "%s:%s" % (at, path)], capture_output=True)
    if git.returncode != 0:
        raise ValueError("%s at %s: %s" % (path, at, git.stderr.decode(errors="replace").strip()))
    s = parse_scene(git.stdout, path, cast)
    s["name"] = name or s["name"]
    s["tags"] = s["tags"] or list(tags)
    s["restoredFrom"] = at
    return s


def build(root, restored=None, at=RESTORED_AT):
    restored = RESTORED if restored is None else restored
    clips = clip_files(root)
    scenes = [restored_scene(root, at, rel, name, tags, cast) for rel, (name, tags, cast) in restored.items()]
    replaced = {"%s/%s" % (SCENE_ROOT.replace(os.sep, "/"), rel) for rel in restored}
    for d, _, fs in os.walk(os.path.join(root, SCENE_ROOT)):
        for f in sorted(fs):
            if f.lower().endswith(".xml"):
                s = read_scene(os.path.join(d, f), root)
                if s["file"] not in replaced:
                    scenes.append(s)
    scenes.sort(key=lambda s: s["id"] or "")
    sex, shared = {}, set()
    for s in scenes:
        for a in s["anims"]:
            a["clips"] = []
            for actor in s["actors"]:
                key = "%s_%d" % (a["id"].lower(), actor["position"])
                c = clips.get(key)
                a["clips"].append(c and c["stem"])
                if c and actor["sex"]:
                    sex.setdefault(key, set()).add(actor["sex"])
                if c and len(s["actors"]) > 1:
                    shared.add(key)
    work, source = [], []
    for key, c in sorted(clips.items()):
        sx = sex.get(key, set())
        # cast as both (FemaleSoloLyingIdle plays _Ap-MaleSoloLyingIdle_0), by nobody, or a side of a scene of two or
        # more, which any body may play (scene-picker.md §1b): both bodies
        bodies = ["f", "m"] if key in shared else sorted(sx) or ["f", "m"]
        name = key.lstrip("_")
        for b in bodies:
            npc, tag, player, ptag = RIG[b]
            # decoded against the skeleton of the actor it was made for, whichever body it is baked on
            row = {"key": key, "file": c["file"], "clip": name, "sex": b, "srcSex": source_sex(b, sx), "known": bool(sx),
                   "rig": npc,
                   "npcSet": "opensex\\anims\\npc\\%s_%s.anims" % (c["set"], tag),
                   "playerRig": player,
                   "playerSet": "opensex\\anims\\player\\%s_%s.anims" % (c["set"], ptag)}
            work.append(row)
        source.append({"clip": name, "source": c["file"], "sex": sorted(sx),
                       "sets": [r[k] for r in work if r["key"] == key for k in ("npcSet", "playerSet")]})
    for s in scenes:
        for a in s["anims"]:
            a["clips"] = [c and c.lower().lstrip("_") for c in a["clips"]]
    return work, scenes, source


# The scene list (scene_list.py) from the pack's scenes.json. Furniture by the id's second part; the act from the class
# code, given by the man (Sx, VJ) or to him (BJ, HJ, BoJ, FJ), None = both ways, a 69.
FURNITURE = {"Ben": "bench", "Cha": "chair", "Coo": "cookingpot", "Tab": "table", "She": "shelf"}
ACTS = {"Sx": ("penetrative", True), "BJ": ("oral_penis", False), "VJ": ("oral_vagina", True),
        "VHJ": ("oral_vagina", None), "HJ": ("manual", False), "BoJ": ("manual", False), "FJ": ("manual", False)}
# Who gives where the class code's man is not, measured from the clips (the giver's head at the other's hips): in the
# lesbian kneeling cunnilingus the lying actor 1 licks the kneeling actor 0.
GIVER_FIXES = {"OpS|Kne!LyB|VJ|LesbianKneLyBCunnilingus": 1}
# A scene whose class code rates nothing but whose clips do: Cr is caressing, and its grind is hips on hips.
ACT_FIXES = {"OpS|LyB!Kne|Cr|MountedGrind": [{"type": "grinding", "actor": "a", "target": "b"}]}
# An actor whose tags name no posture takes the id's code; the princess carry's carried actor is coded standing.
POSTURE_CODES = {"sta": "standing", "kne": "kneeling", "sit": "sitting", "lyb": "lyingback", "lyf": "lyingfront",
                 "lys": "lyingside", "afo": "allfours", "squ": "squatting"}
POSTURE_FIXES = {("opensex.ops.sta-sta.em.princesscarry", 1): "suspended"}
ACTION_XML = re.compile(r'<action\s+type="([^"]+)"\s+actor="(\d+)"(?:\s+target="(\d+)")?')


def scene_acts(s):
    if s["id"] in ACT_FIXES:
        return [dict(a) for a in ACT_FIXES[s["id"]]]
    parts = s["id"].split("|")
    act = ACTS.get(parts[2]) if len(parts) > 2 and len(s["actors"]) == 2 else None
    if not act:
        return []
    if act[1] is None:
        return [{"type": act[0], "actor": "ab"[i], "target": "ab"[1 - i]} for i in (0, 1)]
    sexes = [a.get("sex") for a in s["actors"]]
    man = sexes.index("m") if sexes.count("m") == 1 else 0
    giver = GIVER_FIXES.get(s["id"], man if act[1] else 1 - man)
    return [{"type": act[0], "actor": "ab"[giver], "target": "ab"[1 - giver]}]


def file_actions(root, rel):
    """the scene file's <action>s as [type, actor, target]; a target-less one is the actor's own"""
    path = os.path.join(root, *rel.split("/"))
    if not os.path.isfile(path):
        return []
    with open(path, encoding="utf-8", errors="replace") as fh:
        return [[t, int(a), int(g) if g else int(a)] for t, a, g in ACTION_XML.findall(fh.read())]


def scene_list(pack_dir, root):
    pack = os.path.basename(pack_dir)
    out = []
    for s in json.load(open(os.path.join(pack_dir, "scenes.json"), encoding="utf-8")):
        sid = pack + "." + s["id"].lower().replace("|", ".").replace("!", "-")
        transition = all(a["t"] == "T" for a in s["anims"])
        furniture = FURNITURE.get(s["id"].split("|")[1][:3]) if s["id"].startswith("OpS_furniture|") else None
        codes = sid.split(".")[2].split("-") if len(sid.split(".")) > 2 else []
        actors = []
        for i, a in enumerate(s["actors"]):
            row = {"sex": a.get("sex") or "any", "tags": [t for t in (a.get("tags") or "").split(",") if t]}
            fix = next((p for (pre, n), p in POSTURE_FIXES.items() if n == i and sid.startswith(pre)), None)
            if fix or (i < len(codes) and codes[i] in POSTURE_CODES):
                row["posture"], row["postureFrom"] = (fix, "fix") if fix else (POSTURE_CODES[codes[i]], "code")
            actors.append(row)
        out.append({
            "id": sid,
            "name": s["name"],
            "animator": s["animator"] or None,
            "sources": [{"pack": pack, "id": s["id"], "file": s["file"], "actions": file_actions(root, s["file"])}],
            "actors": actors,
            "speeds": [{"clips": [(pack + "/" + c) if c else None for c in a["clips"]],
                        "playback": 1.0, "display": float(a["speed"]) if a.get("speed") else None}
                       for a in s["anims"]],
            "transition": transition,
            "next": s["anims"][0].get("dest") if transition else None,
            "length": float(s["anims"][0]["l"]) if transition else None,
            "moves": [{"to": g, "label": None} for g in s["goes"]],
            "tags": s["tags"],
            "furniture": furniture,
            "acts": scene_acts(s),
            # OpenSex names a climax only in its scene ids (..._MaleClimax, ...ClimaxInternal)
            "climaxFromMoves": True,
        })
    return out


def main():
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    root, out = sys.argv[1:3]
    work, scenes, source = build(root)
    os.makedirs(out, exist_ok=True)
    for name, data in (("manifest.json", work), ("scenes.json", scenes), ("source-map.json", source)):
        with open(os.path.join(out, name), "w", encoding="utf-8", newline="\n") as fh:
            json.dump(data, fh, indent=1, ensure_ascii=False)
            fh.write("\n")
    sets = {r["npcSet"] for r in work}
    unknown = sorted({r["clip"] for r in work if not r["known"]})
    missing = sorted({a["id"] for s in scenes for a in s["anims"] if not any(a["clips"])})
    print("%d clips -> %d bakes in %d npc sets, %d scenes" % (len(source), len(work), len(sets), len(scenes)))
    print("no scene names (baked on both bodies): %d %s" % (len(unknown), unknown))
    print("scene anims with no clip file: %d %s" % (len(missing), missing))


if __name__ == "__main__":
    main()
