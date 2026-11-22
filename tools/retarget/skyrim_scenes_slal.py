"""A SexLab pack (SLAL, with or without SLSB) as the port's inventory, in skyrim_scenes.py's shapes.

The pack is a folder of one or more Data roots, as a mod archive unpacks (`00 Data/SLAL H/...`): every
`*.slsb.json` is a scene source, and an SLAL `SLAnims/json/*.json` with no SLSB file beside it is read instead. A
stage's actor plays an FNIS event; the `FNIS_*_List.txt` beside the clips names its .hkx. Only human scenes are kept:
Cyberpunk has no creature bodies, so a scene with any non-human position is skipped and counted.

A clip with more tracks than vanilla's 99 and no listed skeleton (Anub's 115: items and wings) decodes against
vanilla's skeleton padded to its track names, written to <out>/skel/ (skyrim_skeleton.py).

Sets are one per scene and body: <pack>\\anims\\npc\\<scene>_ma|_wa.anims. A side of a scene of two or more may be
played by any body (scene-picker.md §1b), so it is baked onto both; a solo clip only onto its own sex.

Run: python tools/retarget/skyrim_scenes_slal.py <out dir> --input DIR --pack NAME [--skeletons DIR]
  writes manifest.json (rows for skyrim_port.py --source-root <input>), scenes.json and source-map.json.
"""
import argparse
import glob
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "opensex"))
import port_list  # noqa: E402
sys.path.insert(0, HERE)
from skyrim_scenes import source_sex  # noqa: E402
import build_config  # noqa: E402

RIG = {"m": ("man_base", "ma", "player_man", "pma"), "f": ("woman_base", "wa", "player_woman", "pwa")}
SKELETONS = {97: {"m": "skeleton.hkx", "f": "femskeleton.hkx"}, 99: {"m": "skeleton.hkx", "f": "femskeleton.hkx"},
             242: {"m": "skeleton242.hkx", "f": "skeleton242.hkx"}}
HUMAN = {"human"}
SLAL_TYPE = {"male": {"m"}, "female": {"f"}}


def rel(path, root):
    return os.path.relpath(path, root).replace(os.sep, "/")


def fnis_events(root):
    """{event or file stem (lower): .hkx path} from every character FNIS list; files are relative to the list"""
    out = {}
    for lst in glob.glob(os.path.join(root, "**", "FNIS_*_List.txt"), recursive=True):
        d = os.path.dirname(lst)
        if os.sep + "character" + os.sep not in d.lower().replace("/", os.sep):
            continue
        for line in open(lst, encoding="utf-8", errors="replace"):
            parts = line.split()
            if not parts or parts[0] not in ("b", "s", "+", "a", "so", "fu", "fuo", "ofa"):
                continue
            words = [w for w in parts[1:] if not w.startswith("-")]
            hkx = next((i for i, w in enumerate(words) if w.lower().endswith(".hkx")), None)
            if hkx is None or hkx == 0:
                continue
            path = os.path.join(d, words[hkx])
            if os.path.isfile(path):
                # SLAL names the FNIS event, SLSB the file's stem
                out[words[hkx - 1].lower()] = path
                out.setdefault(words[hkx][:-4].lower(), path)
    return out


def sex_of(flags):
    s = set()
    if flags.get("male") or flags.get("futa"):
        s.add("m")
    if flags.get("female"):
        s.add("f")
    return s


def stage_order(scene):
    """stage ids from the root along the graph; stages off the path follow in file order"""
    graph, seen, order = scene.get("graph") or {}, set(), []
    sid = scene.get("root")
    while sid and sid not in seen:
        seen.add(sid)
        order.append(sid)
        nxt = (graph.get(sid) or {}).get("dest") or []
        sid = nxt[0] if nxt else None
    order += [st["id"] for st in scene["stages"] if st["id"] not in seen]
    return order


def slsb_scenes(path, root):
    j = json.load(open(path, encoding="utf-8-sig"))
    out = []
    for s in j.get("scenes", {}).values():
        stages = {st["id"]: st for st in s["stages"]}
        first = stages[stage_order(s)[0]]
        races = {p.get("race", "").lower() for st in s["stages"] for p in st["positions"]}
        out.append({
            "id": s["id"], "file": rel(path, root), "name": (s.get("name") or "").strip(), "pack": j.get("pack_name"),
            "author": j.get("pack_author"), "human": races <= HUMAN, "races": sorted(races),
            "tags": [t.lower() for t in first.get("tags") or []], "furniture": s.get("furniture"),
            "actors": [{"position": i, "sex": sorted(sex_of(p.get("sex", {}))),
                        "submissive": bool((p.get("extra") or {}).get("submissive")),
                        "offset": p.get("offset"), "prop": p.get("anim_obj") or None}
                       for i, p in enumerate(first["positions"])],
            "anims": [{"stage": sid, "events": [(p.get("event") or [None])[0] for p in stages[sid]["positions"]],
                       "length": (stages[sid].get("extra") or {}).get("fixed_len") or None,
                       "tags": [t.lower() for t in stages[sid].get("tags", [])]}
                      for sid in stage_order(s)],
            "goes": [], "actions": [],
        })
    return out


def slal_scenes(path, root):
    j = json.load(open(path, encoding="utf-8-sig"))
    out = []
    for a in j.get("animations", []):
        actors = a.get("actors", [])
        n = max((len(x.get("stages", [])) for x in actors), default=0)
        types = {(x.get("type") or "").lower() for x in actors}
        out.append({
            "id": a["id"], "file": rel(path, root), "name": (a.get("name") or "").strip(), "pack": j.get("name"),
            "author": None, "human": types <= {"male", "female"}, "races": sorted(types),
            "tags": [t.strip().lower() for t in (a.get("tags") or "").split(",") if t.strip()], "furniture": None,
            "actors": [{"position": i, "sex": sorted(SLAL_TYPE.get((x.get("type") or "").lower(), set())),
                        "submissive": False, "offset": None, "prop": None} for i, x in enumerate(actors)],
            "anims": [{"stage": str(k + 1), "events": [(x["stages"][k]["id"] if k < len(x.get("stages", [])) else None)
                                                       for x in actors], "length": None} for k in range(n)],
            "goes": [], "actions": [],
        })
    return out


def man_first(scene):
    """SexLab lists the woman first; the game casts a pair man first (OpenSex's order), so a male side leads"""
    rank = [0 if a["sex"] == ["m"] else 2 if a["sex"] == ["f"] else 1 for a in scene["actors"]]
    order = sorted(range(len(rank)), key=lambda i: rank[i])
    scene["actors"] = [scene["actors"][i] for i in order]
    for a in scene["anims"]:
        a["events"] = [a["events"][i] if i < len(a["events"]) else None for i in order]
    return scene


def read_scenes(root):
    slsb = glob.glob(os.path.join(root, "**", "*.slsb.json"), recursive=True)
    covered = {os.path.basename(p)[:-len(".slsb.json")].lower() for p in slsb}
    scenes = [s for p in sorted(slsb) for s in slsb_scenes(p, root)]
    for p in sorted(glob.glob(os.path.join(root, "**", "SLAnims", "json", "*.json"), recursive=True)):
        if os.path.basename(p)[:-5].lower() not in covered:
            scenes += slal_scenes(p, root)
    return [man_first(s) for s in scenes]


def set_name(scene_id):
    return re.sub(r"[^a-z0-9]+", "_", scene_id.lower()).strip("_")


def padder(hkxc, skel_dir, out_dir):
    """make_pad(tracks, clip) -> {"m","f": skeleton path}: vanilla's 99 bones padded to the clip's track names, as
    skeleton242 is for XPMSE clips; None when the clip's first 99 tracks are not vanilla's"""
    made = {}

    def make_pad(tracks, clip):
        if tracks not in made:
            os.makedirs(out_dir, exist_ok=True)
            made[tracks] = {}
            for b, src in (("m", "skeleton.hkx"), ("f", "femskeleton.hkx")):
                out = os.path.join(out_dir, "%s%d.hkx" % ({"m": "male", "f": "female"}[b], tracks))
                if not os.path.isfile(out):
                    r = subprocess.run([sys.executable, os.path.join(HERE, "skyrim_skeleton.py"), hkxc,
                                        os.path.join(skel_dir, src), clip, out], capture_output=True, text=True)
                    if r.returncode != 0:
                        print("no %d-track skeleton from %s:\n%s" % (tracks, clip, r.stderr.strip()[-400:]))
                        made[tracks] = None
                        break
                made[tracks][b] = out
        return made[tracks]
    return make_pad


def build(root, pack, skel_dir, make_pad=None):
    events = fnis_events(root)
    scenes = read_scenes(root)
    kept, dropped, missing = [], [], []
    clips = {}   # key -> {path, sex set, shared, set}
    for s in scenes:
        if not s["human"]:
            dropped.append((s["id"], s["races"]))
            continue
        sset = set_name(s["id"])
        multi = len(s["actors"]) > 1
        for a in s["anims"]:
            a["clips"] = []
            for i, ev in enumerate(a["events"]):
                path = events.get((ev or "").lower())
                if path is None:
                    a["clips"].append(None)
                    if ev:
                        missing.append(ev)
                    continue
                key = ev.lower()
                c = clips.setdefault(key, {"path": path, "sex": set(), "shared": False, "set": sset})
                c["sex"].update(s["actors"][i]["sex"] if i < len(s["actors"]) else [])
                c["shared"] |= multi
                a["clips"].append(key)
        if any(c for a in s["anims"] for c in a["clips"]):
            kept.append(s)

    work, source, skipped = [], [], []
    for key, c in sorted(clips.items()):
        tracks = port_list.clip_facts(c["path"])[1]
        f = rel(c["path"], root)
        skel = {b: os.path.join(skel_dir, n) for b, n in SKELETONS[tracks].items()} if tracks in SKELETONS else \
            (make_pad(tracks, c["path"]) if make_pad and tracks and tracks > 99 else None)
        if not skel:
            skipped.append((f, tracks))
            continue
        sx = c["sex"]
        bodies = ["f", "m"] if c["shared"] else sorted(sx) or ["f", "m"]
        sets = []
        for b in bodies:
            npc, tag, player, ptag = RIG[b]
            src = source_sex(b, sx)
            row = {"key": key, "file": f, "clip": key, "sex": b, "srcSex": src, "known": bool(sx), "rig": npc,
                   "npcSet": "%s\\anims\\npc\\%s_%s.anims" % (pack, c["set"], tag), "playerRig": player,
                   "playerSet": "%s\\anims\\player\\%s_%s.anims" % (pack, c["set"], ptag),
                   "skeleton": skel[src]}
            work.append(row)
            sets += [row["npcSet"], row["playerSet"]]
        source.append({"clip": key, "source": f, "tracks": tracks, "sex": sorted(sx) or None, "sets": sets})
    return work, kept, source, {"creature": dropped, "no clip": sorted(set(missing)), "no skeleton": skipped}


FURNITURE = {"bed": "bed", "chair": "chair", "throne": "chair", "bench": "bench", "couch": "couch", "sofa": "couch"}


def rate(tags, sexes):
    """(postures per actor, acts, furniture) from one stage's tags. SexLab names an act but not who gives it, so acts
    are rated only for two actors where exactly one has a penis: the giver of anything penetrative. Else none."""
    t = set(tags)
    furniture = next((FURNITURE[k] for k in FURNITURE if k in t), None)
    postures, acts = [None] * len(sexes), []
    pen = [i for i, s in enumerate(sexes) if s in ("m", "any") and s != "f"]
    if len(sexes) != 2 or len(pen) != 1 or sexes[1 - pen[0]] != "f":
        return postures, acts, furniture
    g, r = pen[0], 1 - pen[0]
    sit = bool(t & {"chair", "throne", "sitting", "bench", "couch", "sofa"})
    if t & {"vaginal", "anal"}:
        acts.append({"type": "penetrative", "actor": "ab"[g], "target": "ab"[r]})
    if t & {"blowjob", "oral", "deepthroat"} and "cunnilingus" not in t:
        acts.append({"type": "oral_penis", "actor": "ab"[r], "target": "ab"[g]})
    if "cunnilingus" in t:
        acts.append({"type": "oral_vagina", "actor": "ab"[g], "target": "ab"[r]})
    if t & {"handjob", "boobjob", "titjob", "footjob"}:
        acts.append({"type": "manual", "actor": "ab"[r], "target": "ab"[g]})
    if t & {"cowgirl", "reversecowgirl"}:
        postures[g], postures[r] = ("sitting" if sit else "lyingback"), "kneeling"
    elif "missionary" in t:
        postures[r], postures[g] = "lyingback", "kneeling"
    elif t & {"doggy", "doggystyle"}:
        postures[r], postures[g] = "allfours", "kneeling"
    elif "standing" in t:
        postures = ["standing", "standing"]
    elif t & {"blowjob", "oral"}:
        postures[r], postures[g] = "kneeling", ("sitting" if sit else "standing")
    return postures, acts, furniture


def scene_list(pack_dir, root):
    """The scene list (scene_list.py): a SexLab stage is a scene of its own that moves on to the next stage. Its
    postures, acts and furniture come from the stage's tags (rate)."""
    pack = os.path.basename(pack_dir)
    out = []
    for s in json.load(open(os.path.join(pack_dir, "scenes.json"), encoding="utf-8")):
        base = "%s.%s" % (pack, set_name(s["id"]))
        actors = [{"sex": a["sex"][0] if len(a["sex"]) == 1 else "any", "tags": []} for a in s["actors"]]
        stages = [a for a in s["anims"] if any(a["clips"])]
        for k, a in enumerate(stages):
            sid = "%s.s%d" % (base, k + 1)
            postures, acts, furniture = rate(a.get("tags") or s["tags"], [x["sex"] for x in actors])
            out.append({
                "id": sid, "name": "%s %d" % (s["name"] or s["id"], k + 1), "animator": s.get("author"),
                "sources": [{"pack": pack, "id": "%s#%s" % (s["id"], a["stage"]), "file": s["file"], "actions": []}],
                "actors": [dict(x, posture=p) if p else dict(x) for x, p in zip(actors, postures)],
                "speeds": [{"clips": [pack + "/" + c if c else None for c in a["clips"]], "playback": 1.0,
                            "display": None}],
                "transition": False, "next": None, "length": None,
                "moves": [{"to": "%s#%s" % (s["id"], stages[k + 1]["stage"]), "label": "next stage"}]
                if k + 1 < len(stages) else [],
                "tags": a.get("tags") or s["tags"], "furniture": furniture, "acts": acts,
            })
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("out")
    ap.add_argument("--input", required=True, help="the unpacked pack: one or more Data roots below it")
    ap.add_argument("--pack", required=True)
    tools = build_config.load()["tools"]
    ap.add_argument("--skeletons", default=tools["skeletons"])
    ap.add_argument("--hkxc", default=tools["hkxc"])
    a = ap.parse_args()
    for f in {v for m in SKELETONS.values() for v in m.values()}:
        if not os.path.isfile(os.path.join(a.skeletons, f)):
            sys.exit("missing skeleton %s in %s" % (f, a.skeletons))
    pads = padder(a.hkxc, a.skeletons, os.path.join(os.path.abspath(a.out), "skel"))
    work, scenes, source, skipped = build(a.input, a.pack, a.skeletons, pads)
    os.makedirs(a.out, exist_ok=True)
    for name, data in (("manifest.json", work), ("scenes.json", scenes), ("source-map.json", source)):
        with open(os.path.join(a.out, name), "w", encoding="utf-8", newline="\n") as fh:
            json.dump(data, fh, indent=1, ensure_ascii=False)
            fh.write("\n")
    with open(os.path.join(a.out, "skipped.json"), "w", encoding="utf-8", newline="\n") as fh:
        json.dump(skipped, fh, indent=1, ensure_ascii=False)
    print("%d scenes kept, %d clips -> %d bakes in %d npc sets" %
          (len(scenes), len(source), len(work), len({r["npcSet"] for r in work})))
    print("skipped: %d creature scenes, %d events with no .hkx, %d clips with no skeleton (skipped.json)" %
          (len(skipped["creature"]), len(skipped["no clip"]), len(skipped["no skeleton"])))


if __name__ == "__main__":
    main()
