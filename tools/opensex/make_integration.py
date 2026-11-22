"""A ported pack as a NightCityNet integration (nightcitynet docs/design/scene-graph.md §2.1b): its scene files,
clips.json and integration.json under the pack's data/scenes/integrations/<pack>/, and its own workspots in
archive/pc/mod/<pack>_ncn.archive. The mod's own packs and files are never written.

  python tools/opensex/make_integration.py --pack <name> [--name "Shown name"] [--link URL] [--force]

The scenes are scene_files.py's, built over every build.json source up to this one, so a scene made only of an earlier
pack's clips stays that pack's and a move into it keeps that pack's id. This pack's ids become integrations.<pack>.*.
The workspots are built from templates/workspot.json, one per head count. Written once: the files are hand-edited
after, so --force to regenerate.
"""
import argparse
import glob
import json
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import scene_files  # noqa: E402
import make_pose_workspots as mpw  # noqa: E402
import make_scene_workspots as msw  # noqa: E402
import build_config  # noqa: E402
import undress_events  # noqa: E402
from make_amm_poses import sibling, rig_of_set  # noqa: E402

TEMPLATE = os.path.join(HERE, "templates", "workspot.json")
BODIES = ("man_big", "man_fat", "woman_big", "woman_fat")


def add_bodies(clips, local):
    """each big and fat body's set beside npc and player, where the depot holds it (as make_amm_poses --add-rigs)"""
    added = 0
    for sexes in clips.values():
        for sides in sexes.values():
            npc = sides.get("npc", "")
            for rig in BODIES:
                path = sibling(npc, rig) if npc and "\\npc\\" in npc and rig_of_set(npc, rig) else ""
                if path and path.lower() in local and rig not in sides:
                    sides[rig] = path
                    added += 1
    return added


def workspot_path(pack, heads):
    return "ncn\\workspots\\integrations\\%s\\ncn_%s_%dp.workspot" % (pack, pack, heads)


def as_integration(scenes, pack):
    """This pack's scenes, every id of this pack (its own, its moves', next, climax) under integrations.<pack>."""
    def ren(sid):
        return "integrations." + sid if sid and sid.split(".")[0] == pack else sid
    out = {}
    for sid, s in scenes.items():
        if sid.split(".")[0] != pack:
            continue
        s = json.loads(json.dumps(s))
        s["id"] = ren(s["id"])
        for m in s["moves"]:
            m["to"] = ren(m["to"])
        if s.get("next"):
            s["next"] = ren(s["next"])
        if s.get("climax"):
            s["climax"] = {k: ren(v) for k, v in s["climax"].items()}
        out[s["id"]] = s
    return out


def depot_index(anims, names):
    """{set depot path, lower case: the cooked .anims} over every pack this one may borrow a clip from"""
    local = {}
    for p in names:
        root = os.path.join(anims, p, "depot")
        for f in glob.glob(os.path.join(root, "**", "*.anims"), recursive=True):
            local[os.path.relpath(f, root).replace("/", "\\").lower()] = f
    return local


def build_workspots(scenes, clips, local, pack, out_archive):
    """one workspot per head count over its scenes' clips; {heads: depot path}"""
    with open(TEMPLATE, encoding="utf-8") as f:
        base = json.load(f)
    mpw.renumber(base)
    every = list(scenes.values())
    idles, _ = msw.transition_idles(every)
    tiered = msw.tiered_clips(every)
    work = os.path.join(build_config.ROOT, "build", "integration", pack)
    shutil.rmtree(work, ignore_errors=True)
    raw, packed = os.path.join(work, "raw"), os.path.join(work, "packed")
    os.makedirs(packed)
    named, sets_names, sets_rigs = {}, {}, {}
    for heads in sorted({len(s["actors"]) for s in every}):
        refs = sorted({c for s in every if len(s["actors"]) == heads for sp in s["speeds"] for c in sp["clips"]})
        names, by_rig, seen = [], {}, {}
        for ref in refs:
            name = ref.split("/", 1)[1]
            if "#" in name:
                print("  %dP: %s -- a clip name two sets share, left out (one workspot entry per name)" % (heads, ref))
                continue
            if name in seen:
                sys.exit("%dP: clip name %s twice (%s, %s)" % (heads, name, seen[name], ref))
            seen[name] = ref
            names.append(name)
            for sides in clips[ref].values():
                for depot in sides.values():
                    key = depot.lower()
                    if key not in local:
                        sys.exit("%s names set %s, which no pack's depot holds" % (ref, depot))
                    if key not in sets_names:
                        sets_names[key] = mpw.clip_names(local[key])
                        sets_rigs[key] = sorted(mpw.rigs_of(local[key]))
                    if name not in sets_names[key]:
                        sys.exit("%s: clip %s is not in its set %s" % (ref, name, depot))
                    if len(sets_rigs[key]) != 1:
                        sys.exit("set %s names %d rigs, want one" % (depot, len(sets_rigs[key])))
                    by_rig.setdefault(sets_rigs[key][0], set()).add(depot)
        rows = [(rig, sorted(s)) for rig, s in sorted(by_rig.items())]
        doc = msw.build_tree(base, rows, names, {c: i for c, i in idles.items() if c in seen and i in seen}, tiered)
        depot = workspot_path(pack, heads)
        out_ws = os.path.join(raw, *depot.split("\\"))
        os.makedirs(os.path.dirname(out_ws), exist_ok=True)
        doc["Header"]["ArchiveFileName"] = out_ws
        with open(out_ws + ".json", "w", encoding="utf-8") as f:
            json.dump(doc, f, indent=1)
        mpw.run([mpw.CLI, "convert", "d", out_ws + ".json", "-o", os.path.dirname(out_ws), "-v", "quiet"])
        os.remove(out_ws + ".json")
        if not os.path.isfile(out_ws):
            sys.exit("deserialize produced no " + depot)
        named[str(heads)] = depot
        print("%dP: %d clips, %s" % (heads, len(names), ", ".join(
            "%s %d sets" % (os.path.basename(r).replace(".rig", ""), len(s)) for r, s in rows)))
    mpw.run([mpw.CLI, "pack", raw, "-o", packed, "-v", "quiet"])
    made = [f for f in os.listdir(packed) if f.endswith(".archive")]
    if not made:
        sys.exit("pack produced no archive")
    os.makedirs(os.path.dirname(out_archive), exist_ok=True)
    shutil.copyfile(os.path.join(packed, made[0]), out_archive)
    print("-> %s" % out_archive)
    return named


def write_json(path, doc):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(doc, fh, indent=1, ensure_ascii=False)
        fh.write("\n")


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--pack", required=True)
    ap.add_argument("--name", default="")
    ap.add_argument("--link", default="")
    ap.add_argument("--anims", default=scene_files.ANIMS)
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()
    order = [p for p, _ in scene_files.packs()]
    if a.pack not in order:
        sys.exit("%s is no source in build.json" % a.pack)
    names = order[:order.index(a.pack) + 1]
    folder = os.path.join(a.anims, a.pack, scene_files.SCENES_REL, "integrations", a.pack)
    if os.path.isdir(folder) and os.listdir(folder) and not a.force:
        sys.exit("%s exists and is hand-edited from here on; --force to regenerate" % folder)
    if not os.path.isfile(mpw.CLI):
        sys.exit("WolvenKit CLI not found: %s" % mpw.CLI)

    every, clips, report, notes = scene_files.build(a.anims, names)
    scenes = as_integration(every, a.pack)
    if not scenes:
        sys.exit("%s has no scene of its own (each is an earlier pack's)" % a.pack)
    for s in scenes.values():
        s["strip"] = undress_events.strip_of(s)
    used = {c for s in scenes.values() for sp in s["speeds"] for c in sp["clips"]}
    clips = json.loads(json.dumps({r: clips[r] for r in sorted(used)}))
    local = depot_index(a.anims, names)
    print("%d big/fat body sets named in clips.json" % add_bodies(clips, local))

    archive = os.path.join(a.anims, a.pack, "archive", "pc", "mod")
    if not os.path.isfile(os.path.join(archive, a.pack + ".archive")):
        sys.exit("no %s.archive in %s: run the port's pack stage first" % (a.pack, archive))
    workspots = build_workspots(scenes, clips, local, a.pack,
                                os.path.join(archive, a.pack + "_ncn.archive"))

    shutil.rmtree(folder, ignore_errors=True)
    heads = sorted(int(h) for h in workspots)
    write_json(os.path.join(folder, "integration.json"), {
        "id": a.pack, "name": a.name or a.pack, "link": a.link,
        "uses": "%d scenes (%s)" % (len(scenes), ", ".join("%dP" % h for h in heads)),
        "archive": a.pack + ".archive", "workspots": workspots})
    write_json(os.path.join(folder, "clips.json"), clips)
    root = os.path.join(a.anims, a.pack, scene_files.SCENES_REL)
    for sid, s in sorted(scenes.items()):
        write_json(scene_files.scene_path(root, sid), s)
    for n in notes:
        print(n)
    print("%s: %d scenes, %d clips, %d moves -> %s" % (a.pack, len(scenes), len(clips),
                                                       sum(len(s["moves"]) for s in scenes.values()), folder))
    for k, v in sorted(report.items()):
        print("  %s: %d" % (k, v))


if __name__ == "__main__":
    main()
