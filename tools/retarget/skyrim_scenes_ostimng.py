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
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, "tools", "opensex"))
import port_list  # noqa: E402
sys.path.insert(0, HERE)
from skyrim_scenes import source_sex  # noqa: E402

ANIM_ROOT = os.path.join("data", "meshes", "actors", "character", "animations", "OStim")
SCENE_ROOT = os.path.join("data", "SKSE", "Plugins", "OStim", "scenes")
RIG = {"m": ("man_base", "ma", "player_man", "pma"), "f": ("woman_base", "wa", "player_woman", "pwa")}
SEX = {"male": {"m"}, "female": {"f"}, "any": {"m", "f"}}
# Track count -> skeleton per body. Reskeletor's set: vanilla male / female, and XPMSE+3BA+SMP for both.
SKELETONS = {97: {"m": "skeleton.hkx", "f": "femskeleton.hkx"}, 99: {"m": "skeleton.hkx", "f": "femskeleton.hkx"},
             242: {"m": "skeleton242.hkx", "f": "skeleton242.hkx"}}


def clip_files(root):
    """{(set, key): file info} for every .hkx; a clip is unique within its set, not across OStim/."""
    out = {}
    base = os.path.join(root, ANIM_ROOT)
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


def build(root, port_list_json, skel_dir):
    plist = json.load(open(port_list_json, encoding="utf-8"))
    extra = set(plist["orphans"]) | {c for s in plist["scenes"] if s["source"] == "OStimNG" for c in s["extra"]}
    from_opensex = {}
    for s in plist["scenes"]:
        from_opensex.update(s.get("fromOpenSex", {}))
    clips = clip_files(root)
    by_key = {}
    for (group, key), c in clips.items():
        by_key.setdefault(key, []).append(c)

    scenes = []
    for d, _, fs in os.walk(os.path.join(root, SCENE_ROOT)):
        for f in sorted(fs):
            if f.endswith(".json"):
                scenes.append(read_scene(os.path.join(d, f), root))
    scenes.sort(key=lambda s: s["file"])

    # A scene's clip is the file in the scene's own folder set when two sets share a name.
    def resolve(key, scene_file):
        cands = by_key.get(key, [])
        if len(cands) > 1:
            group = "_".join(scene_file.split("/")[5:8]).lower()  # after data/SKSE/Plugins/OStim/scenes/
            cands = [c for c in cands if c["set"] == group] or cands
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
                         "npcSet": "ostimng\\anims\\npc\\%s_%s.anims" % (group, tag),
                         "playerRig": player,
                         "playerSet": "ostimng\\anims\\player\\%s_%s.anims" % (group, ptag),
                         "skeleton": os.path.join(skel_dir, SKELETONS[tracks][src])})
        source.append({"clip": key, "source": c["file"], "tracks": tracks, "sex": sorted(sx) or None,
                       "sets": [r[k] for r in work if r["key"] == key and r["file"] == c["file"]
                                for k in ("npcSet", "playerSet")]})
    return work, kept, source, skipped


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("out")
    ap.add_argument("--ostimng", default=port_list.OSTIMNG)
    ap.add_argument("--list", default=port_list.OUT_JSON)
    ap.add_argument("--skeletons", default=r"C:\Modding\hkx_backport\Reskeletor\skeletons")
    a = ap.parse_args()
    for f in {v for m in SKELETONS.values() for v in m.values()}:
        if not os.path.isfile(os.path.join(a.skeletons, f)):
            sys.exit("missing skeleton %s in %s" % (f, a.skeletons))
    work, scenes, source, skipped = build(a.ostimng, a.list, a.skeletons)
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
