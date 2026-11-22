"""OStimNG's extra clips (none of OpenSex's) as the port's inventory, in skyrim_scenes.py's shapes, for pack ostimng/.

Which clips are extra comes from docs/generated/anim-port-list.json (tools/opensex/port_list.py): a clip whose
animation is in OpenSex is ported from OpenSex, never from here. A scene's actor i plays <speeds[].animation>_<i>;
its intendedSex picks the body ("any", or a clip two scenes cast differently, is baked onto both). Each row names the
skeleton it unpacks against, by the clip's track count: 97/99 vanilla, 242 XPMSE+3BA+SMP.

Sets group clips by their first three folders under OStim/ (OStim2P/MF/sexual -> ostim2p_mf_sexual), one per body;
OStimBed2P\\FF\\idle and \\MF\\idle both hold an OStimBed2PBothSittingMF_0/_1, different files, so they stay apart.

Run: python tools/retarget/skyrim_scenes_ostimng.py <out dir> [--ostimng DIR] [--list JSON] [--skeletons DIR]
  writes manifest.json (rows for skyrim_port.py --source-root <OStimNG>), scenes.json and source-map.json.
"""
import argparse
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, "tools", "opensex"))
import port_list  # noqa: E402
sys.path.insert(0, HERE)
from skyrim_scenes import source_sex  # noqa: E402

ANIMS = os.path.join("meshes", "actors", "character", "animations")
SCENES = os.path.join("SKSE", "Plugins", "OStim", "scenes")


def data_dir(root):
    """the mod's Data folder: OStimNG's checkout keeps it under data/, an unpacked mod is it"""
    sub = os.path.join(root, "data")
    return sub if os.path.isdir(os.path.join(sub, "SKSE")) else root


def anim_root(root, pack):
    base = os.path.join(data_dir(root), ANIMS)
    return os.path.join(base, "OStim") if pack == "ostimng" else base


def scene_root(root):
    return os.path.join(data_dir(root), SCENES)
RIG = {"m": ("man_base", "ma", "player_man", "pma"), "f": ("woman_base", "wa", "player_woman", "pwa")}
SEX = {"male": {"m"}, "female": {"f"}, "any": {"m", "f"}}
# Track count -> skeleton per body. Reskeletor's set: vanilla male / female, and XPMSE+3BA+SMP for both.
SKELETONS = {97: {"m": "skeleton.hkx", "f": "femskeleton.hkx"}, 99: {"m": "skeleton.hkx", "f": "femskeleton.hkx"},
             242: {"m": "skeleton242.hkx", "f": "skeleton242.hkx"}}


def clip_files(root, pack="ostimng"):
    """{(set, key): file info} for every .hkx; a clip is unique within its set, not across OStim/."""
    out = {}
    base = anim_root(root, pack)
    for d, _, fs in os.walk(base):
        for f in fs:
            if f.lower().endswith(".hkx"):
                parts = os.path.relpath(d, base).split(os.sep)
                group = "_".join(parts[:3]).lower()
                path = os.path.join(d, f)
                out[(group, f[:-4].lower())] = {"file": os.path.relpath(path, root).replace(os.sep, "/"),
                                                "stem": f[:-4], "set": group, "path": path}
    return out


def read_scene(path, root):
    j = json.load(open(path, encoding="utf-8-sig"))
    actors = [{"position": i, "intendedSex": a.get("intendedSex"), "tags": a.get("tags", []),
               "feetOnGround": a.get("feetOnGround")} for i, a in enumerate(j.get("actors", []))]
    speeds = [{k: s[k] for k in ("animation", "playbackSpeed", "displaySpeed") if k in s}
              for s in j.get("speeds", []) if s.get("animation")]
    return {
        "id": os.path.splitext(os.path.basename(path))[0],
        "file": os.path.relpath(path, root).replace(os.sep, "/"),
        "name": j.get("name"),
        "length": j.get("length"),
        "tags": j.get("tags", []),
        "furniture": j.get("furniture"),
        "offset": j.get("offset"),
        "actors": actors,
        "start": speeds[0]["animation"] if speeds else None,
        "anims": speeds,
        "goes": sorted({n["destination"] for n in j.get("navigations", []) if n.get("destination")}
                       | ({j["destination"]} if j.get("destination") else set())),
        "actions": j.get("actions", []),
    }


def scene_folders(path, root):
    return [p.lower() for p in os.path.relpath(path, scene_root(root)).split(os.sep)[:-1]]


def same_place(set_name, folders, pack):
    """is a clip set the one beside this scene: OStimNG names both by the same three folders; another pack's
    clips sit under a folder of its own (animations/MLC/MLCBed for scenes/MLCBed), so each scene folder is in the set"""
    if pack == "ostimng":
        return set_name == "_".join(folders[:3])
    parts = set_name.split("_")
    return bool(folders) and all(f in parts for f in folders)


def build(root, port_list_json, skel_dir, pack="ostimng"):
    clips = clip_files(root, pack)
    by_key = {}
    for (group, key), c in clips.items():
        by_key.setdefault(key, []).append(c)

    scenes = []
    for d, _, fs in os.walk(scene_root(root)):
        for f in sorted(fs):
            if f.endswith(".json"):
                scenes.append(read_scene(os.path.join(d, f), root))
    scenes.sort(key=lambda s: s["file"])

    from_opensex = {}
    if pack == "ostimng":   # the port list says which of OStimNG's clips are OpenSex's
        plist = json.load(open(port_list_json, encoding="utf-8"))
        extra = set(plist["orphans"]) | {c for s in plist["scenes"] if s["source"] == "OStimNG" for c in s["extra"]}
        for s in plist["scenes"]:
            from_opensex.update(s.get("fromOpenSex", {}))
    else:
        extra = {"%s_%d" % (a["animation"].lower(), x["position"]) for s in scenes for a in s["anims"]
                 for x in s["actors"]} & set(by_key)

    # A scene's clip is the file in the scene's own folder set when two sets share a name.
    def resolve(key, scene_file):
        cands = by_key.get(key, [])
        if len(cands) > 1:
            folders = scene_folders(os.path.join(root, scene_file), root)
            near = [c for c in cands if same_place(c["set"], folders, pack)]
            if len(near) != 1:
                print("%s: clip %s is in %d sets, none beside the scene alone; took %s" % (
                    scene_file, key, len(cands), (near or cands)[0]["file"]))
            cands = near or cands
        return cands[0] if cands else None

    sex, kept, shared = {}, [], set()
    for s in scenes:
        for a in s["anims"]:
            a["clips"] = []
            for actor in s["actors"]:
                key = "%s_%d" % (a["animation"].lower(), actor["position"])
                c = resolve(key, s["file"])
                if c is None:
                    a["clips"].append(None)
                elif key in extra:
                    a["clips"].append(key)
                    sex.setdefault((c["set"], key), set()).update(SEX.get(actor["intendedSex"], set()))
                    if len(s["actors"]) > 1:
                        shared.add((c["set"], key))
                elif key in from_opensex:
                    a["clips"].append("opensex:" + from_opensex[key].lstrip("_"))
                else:
                    a["clips"].append(None)
        if any(c and not c.startswith("opensex:") for a in s["anims"] for c in a["clips"]):
            kept.append(s)

    work, source, skipped = [], [], []
    for (group, key), c in sorted(clips.items()):
        if key not in extra:
            continue
        tracks, _ = port_list.clip_facts(c["path"])[1:3]
        if tracks not in SKELETONS:
            skipped.append((c["file"], tracks))
            continue
        sx = sex.get((group, key), set())
        # a side of a scene of two or more: any body may play it (scene-picker.md §1b)
        bodies = ["f", "m"] if (group, key) in shared else sorted(sx) or ["f", "m"]
        for b in bodies:
            npc, tag, player, ptag = RIG[b]
            src = source_sex(b, sx)
            work.append({"key": key, "file": c["file"], "clip": key, "sex": b, "srcSex": src, "known": bool(sx), "rig": npc,
                         "npcSet": "%s\\anims\\npc\\%s_%s.anims" % (pack, group, tag),
                         "playerRig": player,
                         "playerSet": "%s\\anims\\player\\%s_%s.anims" % (pack, group, ptag),
                         "skeleton": os.path.join(skel_dir, SKELETONS[tracks][src])})
        source.append({"clip": key, "source": c["file"], "tracks": tracks, "sex": sorted(sx) or None,
                       "sets": [r[k] for r in work if r["key"] == key and r["file"] == c["file"]
                                for k in ("npcSet", "playerSet")]})
    return work, kept, source, skipped


# The scene list (scene_list.py). The acts the arousal model rates from OStimNG's action types; a penetrative one names
# its opening (shaft-bones.md).
NG_SEX = {"male": "m", "female": "f"}
NG_ACTS = {"vaginalsex": "penetrative", "analsex": "penetrative", "blowjob": "oral_penis", "lickingpenis": "oral_penis",
           "cunnilingus": "oral_vagina", "lickingvagina": "oral_vagina", "handjob": "manual", "boobjob": "manual",
           "buttjob": "manual", "footjob": "manual", "vaginalfingering": "manual", "analfingering": "manual",
           "rubbingclitoris": "manual", "malemasturbation": "manual", "femalemasturbation": "manual"}
NG_INTO = {"vaginalsex": "vagina", "analsex": "anus"}
# one actor is a bare "lying" in a scene named lying-front
POSTURE_FIXES = {("ostimng.ostim2p.mm.idle.ostim2pkneelinglyingfrontmm", 1): "lyingfront"}


def read_translations(root):
    """OStimNG's English names; another pack ships none (its names are plain) or its own beside them"""
    out = {}
    for f in ("OScenes_ENGLISH.txt", "ONav_ENGLISH.txt"):
        path = os.path.join(data_dir(root), "Interface", "translations", f)
        if not os.path.isfile(path):
            continue
        for line in open(path, encoding="utf-16").read().splitlines():
            if line.startswith("$") and "\t" in line:
                k, v = line.split("\t", 1)
                out[k.lower()] = v.strip()
    return out


def nav_label(desc, tr):
    """'$ostim_nav_kiss_t{1}' -> 'kiss {1}': {N} is the name of actor N, as OStimNG fills it."""
    if not desc:
        return None
    m = re.search(r"\{(\d+)\}", desc)
    v = tr.get(re.sub(r"\{\d+\}", "{}", desc).lower())
    if v is None:
        return None
    return v.replace("{{}}", "{%s}" % m.group(1)) if m else v


def scene_acts(j, n):
    """OStimNG's actions as acts; a masturbation names no target: the actor works on themself."""
    out = []
    for x in j.get("actions", []):
        self_act = x.get("type", "").endswith("masturbation")
        target = x.get("actor") if self_act else x.get("target")
        if x.get("type") not in NG_ACTS or n != 2 or x.get("actor") not in (0, 1) or target not in (0, 1) \
                or (x["actor"] == target and not self_act):
            continue
        act = {"type": NG_ACTS[x["type"]], "actor": "ab"[x["actor"]], "target": "ab"[target]}
        if x["type"] in NG_INTO:
            act["into"] = NG_INTO[x["type"]]
        out.append(act)
    return out


def scene_list(pack_dir, root, list_json=port_list.OUT_JSON):
    import scene_list as sl
    pack = os.path.basename(pack_dir)
    clip_map = json.load(open(list_json, encoding="utf-8"))["clipMap"]
    own = {}
    for ref, r in sl.clip_refs(pack, json.load(open(os.path.join(pack_dir, "source-map.json"), encoding="utf-8"))):
        own.setdefault(r["clip"], []).append((sl.set_body(r["sets"][0])[0], ref))
    tr = read_translations(root)
    out = []
    for d, _, fs in sorted(os.walk(scene_root(root))):
        for f in sorted(fs):
            if not f.endswith(".json"):
                continue
            path = os.path.join(d, f)
            rel = os.path.relpath(path, root).replace(os.sep, "/")
            folders = scene_folders(path, root)
            j = json.load(open(path, encoding="utf-8-sig"))
            n = len(j.get("actors", []))
            under = os.path.relpath(path, scene_root(root))[:-len(".json")].split(os.sep)
            sid = pack + "." + ".".join(p.lower() for p in under)

            def ref(anim, i):
                key = "%s_%d" % (anim.lower(), i)
                if key in own:
                    return next((r for g, r in own[key] if same_place(g, folders, pack)), own[key][0][1])
                return "opensex/" + clip_map[key].lstrip("_") if key in clip_map else None

            actors = []
            for i, a in enumerate(j.get("actors", [])):
                row = {"sex": NG_SEX.get(a.get("intendedSex"), "any"), "tags": a.get("tags", [])}
                fix = next((p for (pre, k), p in POSTURE_FIXES.items() if k == i and sid.startswith(pre)), None)
                if fix:
                    row["posture"], row["postureFrom"] = fix, "fix"
                actors.append(row)
            transition = bool(j.get("destination"))
            s = {
                "id": sid,
                "name": tr.get(j.get("name", "").lower(), j.get("name", "").lstrip("$")),
                "animator": None,
                "sources": [{"pack": pack, "id": f[:-5], "file": rel,
                             "actions": [[x.get("type", ""), x.get("actor"), x.get("target", x.get("actor"))]
                                         for x in j.get("actions", [])]}],
                "actors": actors,
                "speeds": [{"clips": [ref(sp["animation"], i) for i in range(n)],
                            "playback": float(sp.get("playbackSpeed", 1.0)),
                            "display": float(sp["displaySpeed"]) if sp.get("displaySpeed") is not None else None}
                           for sp in j.get("speeds", []) if sp.get("animation")],
                "transition": transition,
                "next": j.get("destination") if transition else None,
                "length": float(j["length"]) if transition and j.get("length") else None,
                "moves": [dict({"to": nv["destination"], "label": nav_label(nv.get("description"), tr)},
                               **({"priority": nv["priority"]} if isinstance(nv.get("priority"), int) else {}))
                          for nv in j.get("navigations", []) if nv.get("destination")],
                "tags": j.get("tags", []),
                "furniture": j.get("furniture"),
                "acts": scene_acts(j, n),
            }
            # per actor, the scene its climax plays (autoTransitions.climax)
            climax = {"ab"[i]: a["autoTransitions"]["climax"] for i, a in enumerate(j.get("actors", [])[:2])
                      if isinstance(a.get("autoTransitions"), dict) and a["autoTransitions"].get("climax")}
            if climax:
                s["climax"] = climax
            if j.get("noRandomSelection") is True:
                s["noRandom"] = True   # never a random start; a menu may still offer it
            out.append(s)
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("out")
    ap.add_argument("--ostimng", default=port_list.OSTIMNG)
    ap.add_argument("--list", default=port_list.OUT_JSON)
    ap.add_argument("--skeletons", default=port_list.build_config.load()["tools"]["skeletons"])
    ap.add_argument("--pack", default="ostimng", help="the pack's folder name; its sets are <pack>\\anims\\...")
    a = ap.parse_args()
    for f in {v for m in SKELETONS.values() for v in m.values()}:
        if not os.path.isfile(os.path.join(a.skeletons, f)):
            sys.exit("missing skeleton %s in %s" % (f, a.skeletons))
    work, scenes, source, skipped = build(a.ostimng, a.list, a.skeletons, a.pack)
    if not work:
        counts = sorted({t for _, t in skipped})
        sys.exit("%s: no clip to port. %d scenes read; %s" % (a.pack, len(scenes), (
            "every clip's skeleton has %s tracks, and only 97, 99 or 242 can be decoded (skeletons/skyrim/)"
            % ", ".join(map(str, counts))) if skipped else "none of their clips is in the pack's animations folder"))
    os.makedirs(a.out, exist_ok=True)
    for name, data in (("manifest.json", work), ("scenes.json", scenes), ("source-map.json", source)):
        with open(os.path.join(a.out, name), "w", encoding="utf-8", newline="\n") as fh:
            json.dump(data, fh, indent=1, ensure_ascii=False)
            fh.write("\n")
    sets = {r["npcSet"] for r in work}
    both = sorted({r["clip"] for r in work if r["known"]} & {r["clip"] for r in work if r["sex"] == "m"}
                  & {r["clip"] for r in work if r["sex"] == "f"})
    unknown = sorted({r["clip"] for r in work if not r["known"]})
    print("%d clips -> %d bakes in %d npc sets, %d scenes" % (len(source), len(work), len(sets), len(scenes)))
    print("cast as both sexes (baked on both bodies): %d %s" % (len(both), both))
    print("no scene names (baked on both bodies): %d %s" % (len(unknown), unknown))
    print("skipped, track count with no skeleton: %d %s" % (len(skipped), skipped))


if __name__ == "__main__":
    main()
