"""Build ncn_scene_workspots.archive -- one INDEX workspot per head count over the scene packs' clips.

docs/design/scene-graph.md §3: every clip a head count's scenes play sits on one workspot, one sequence per clip named
as the clip, so a move between scenes is a clip jump (NCN_JumpHostTableau) and never a remount. A pose's sequence
loops; a transition's plays once and rests on its next scene's clip.

The clips and their sets come from the installed packs' scene files (CyberpunkAnimations, <pack>/bin/.../data/scenes/),
the rigs from the cooked .anims themselves. A rig row names EVERY animset of that rig -- the one shape no shipped pose
pack uses (each names one), so whether the engine reads past the first is what the 2P workspot's first run measures.

The graph is templates/workspot.json, shipped with this tool. The workspot lives in the mod's archive, over the
packs' anims, so the packs carry no workspot.

Run:  python tools/opensex/make_scene_workspots.py [--anims DIR] [--packs a,b] [--heads 1,2,3,4,5] [--skip-missing]
      [--out DIR]
Output, in the mod (build.json's `mod`) unless --out: archive/pc/mod/ncn_scene_workspots.archive  (ncn\\workspots\\scenes\\ncn_scenes_<N>p.workspot)
        data/scenes/workspot_rests.json  {transition id: the scene it rests on}
"""
import argparse
import copy
import glob
import json
import os
import shutil
import sys

import make_pose_workspots as mpw
import build_config

_CFG = build_config.load()
REPO = _CFG["mod"]   # the archive and the rests are the mod's
ANIMS = _CFG["packs"]
# every source's pack, in build.json's order
PACKS = tuple(dict.fromkeys(os.path.basename(s["pack"]) for s in _CFG["sources"].values()))
TEMPLATE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "templates", "workspot.json")
SCENES_REL = os.path.join("bin", "x64", "plugins", "cyber_engine_tweaks", "mods", "nightcitynet", "data", "scenes")
BUILD = os.path.join(build_config.ROOT, "build", "scene_workspots")
OUT_ARCHIVE = os.path.join(REPO, "archive", "pc", "mod", "ncn_scene_workspots.archive")
# Which transitions this archive plays once and rests on their next scene: the DLL's only source for that (SceneGraph).
OUT_RESTS = os.path.join(REPO, "data", "scenes", "workspot_rests.json")
DEST_DIR = os.path.join("ncn", "workspots", "scenes")
# A scene's moves were authored to flow, and Skyrim cross-fades them (FNIS's default; OpenSex sets no -B). The pose
# packs' 0.1 (mpw.CLIP_BLEND_OUT) is for unrelated static poses, where a long fade morphs; vanilla mostly uses 0.5, and
# 1.0 on its longest. 0.6 still read as a cut in game (2026-10-27).
SCENE_BLEND_OUT = 1.0
# A play-once transition is the move itself: 1.0 s of fade cut the last second off a 1.5 s one (2026-10-28).
TRANSITION_BLEND_OUT = 0.25
# A tier key jumps at once, as OStim's SetSpeed: a short fade hides the cut, 1.0 s read as a drift (2026-11-14).
TIER_BLEND_OUT = 0.25


def tiered_clips(scenes):
    """The clip names a scene with more than one speed plays: a tier key leaves them mid-loop."""
    return {c.split("/", 1)[1] for s in scenes if not s.get("transition") and len(s["speeds"]) > 1
            for sp in s["speeds"] for c in sp["clips"]}


def read_packs(anims):
    """(scenes, {ref: {sex: {side: set}}}, {set depot path: local .anims path})."""
    scenes, clips, local = [], {}, {}
    for pack in PACKS:
        root = os.path.join(anims, pack, SCENES_REL)
        for f in glob.glob(os.path.join(root, "**", "*.json"), recursive=True):
            if os.path.basename(f) == "integration.json":   # an integration's own record, not a scene
                continue
            j = json.load(open(f, encoding="utf-8"))
            if os.path.basename(f) == "clips.json":
                clips.update(j)
            else:
                scenes.append(j)
        for f in glob.glob(os.path.join(anims, pack, "depot", "**", "*.anims"), recursive=True):
            local[os.path.relpath(f, os.path.join(anims, pack, "depot")).replace("/", "\\").lower()] = f
    return scenes, clips, local


def start_speed(scene):
    """The tier a scene starts on: the pack's 1x, else its first -- the DLL's anim::StartSpeedOf."""
    return next((sp for sp in scene["speeds"] if sp.get("display") == 1.0), scene["speeds"][0])


def transition_idles(scenes):
    """({transition clip name: the next scene's clip for the same actor}, {transition id: (next, [(clip, idle)])}) --
    played once, then rested on (vanilla's loopInfinitely 0 + idleAnim shape); a looped transition snaps back to its
    first frame, which reads as a spin. A sequence is one per clip NAME, so a clip only rests where every scene that
    plays it agrees: next a pose (an idle loops, so a transition there would loop), one idle, and no pose of its own."""
    by_id = {s["id"]: s for s in scenes}
    poses = {c.split("/", 1)[1] for s in scenes if not s.get("transition") for sp in s["speeds"] for c in sp["clips"]}
    want, per = {}, {}
    for s in scenes:
        if not s.get("transition"):
            continue
        nxt = by_id.get(s.get("next"))
        own = s["speeds"][0]["clips"] if s["speeds"] else []
        to = start_speed(nxt)["clips"] if nxt and nxt["speeds"] else []
        if nxt and nxt.get("transition"):
            print("  %s: next %s is a transition, left looping" % (s["id"], s["next"]))
            continue
        if len(own) != len(to):
            print("  %s: next %s has %d clip(s) for %d actor(s), left looping" % (s["id"], s.get("next"), len(to), len(own)))
            continue
        pairs = [(a.split("/", 1)[1], b.split("/", 1)[1]) for a, b in zip(own, to)]
        per[s["id"]] = (s["next"], pairs)
        for a, b in pairs:
            want.setdefault(a, set()).add(b)
    idles = {}
    for c, to in sorted(want.items()):
        if len(to) > 1 or c in poses:
            print("  %s: %s, left looping" % (c, "a pose plays it too" if c in poses else "rests on " + " / ".join(sorted(to))))
        else:
            idles[c] = next(iter(to))
    return idles, per


def build_tree(base, rows, names, idles, tiered):
    """The stencil's document with our rig rows and one sequence per clip name: a pose loops, a transition plays
    once and rests on the pose it leads to."""
    doc = copy.deepcopy(base)
    tree = mpw.find_type(doc["Data"]["RootChunk"], "workWorkspotTree")
    if len(tree) != 1:
        sys.exit("expected one workWorkspotTree in the stencil, found %d" % len(tree))
    tree = tree[0]
    tree["finalAnimsets"] = [{
        "$type": "workWorkspotAnimsetEntry",
        "animations": {
            "$type": "animAnimSetup",
            "cinematics": [{"$type": "animAnimSetupEntry", "animSet": mpw.rpath(a),
                            "priority": 128, "variableNames": []} for a in sets],
            "gameplay": [],
            "hash": "0",   # 0 = the engine keys its setup cache itself (anim::BuildRuntimeAnimSetup)
        },
        "loadingHandles": [mpw.rpath(a) for a in sets],
        "rig": mpw.rpath(rig, "Soft"),
    } for rig, sets in rows]
    tree["customTransitionAnims"] = []
    hubs = mpw.find_type(doc["Data"]["RootChunk"], "animAnimNode_WorkspotHub")
    if len(hubs) != 1:
        sys.exit("expected one animAnimNode_WorkspotHub in the stencil, found %d" % len(hubs))
    for field, value in mpw.FACIAL_IDLE.items():
        hubs[0][field] = mpw.cname(value)
    tree["inertializationDurationExitForced"] = mpw.EXIT_FORCED
    tree["blacklistVisualTags"] = {"$type": "redTagList", "tags": []}
    root = tree["rootEntry"]["Data"]
    root["idleAnim"] = mpw.cname("None")
    root["loopInfinitely"] = 0
    children, next_id = [], 2
    for c in names:
        idle = idles.get(c)
        children.append({"HandleId": "0", "Data": {
            "$type": "workSequence", "category": "Any", "disableAutoTransition": 0, "flags": 0,
            "id": {"$type": "workWorkEntryId", "id": next_id},
            "idleAnim": mpw.cname(idle or c),
            "list": [{"HandleId": "0", "Data": {
                "$type": "workAnimClip", "animName": mpw.cname(c),
                "blendOutTime": TRANSITION_BLEND_OUT if idle else TIER_BLEND_OUT if c in tiered else SCENE_BLEND_OUT,
                "flags": 2, "id": {"$type": "workWorkEntryId", "id": next_id + 1}}}],
            "loopInfinitely": 0 if idle else 1, "previousLoopInfinitely": 0}})
        next_id += 2
    root["list"] = children
    tree["idCounter"] = next_id
    mpw.renumber(doc)
    return doc


def main():
    global PACKS   # read_packs reads it
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--anims", default=ANIMS)
    ap.add_argument("--packs", default=",".join(PACKS))
    ap.add_argument("--heads", default="1,2,3,4,5")
    ap.add_argument("--reverse-sets", action="store_true", help="test: each rig row's sets in reverse order")
    ap.add_argument("--only-clips", default="", help="test: only these clip names, comma-separated")
    ap.add_argument("--skip-missing", action="store_true",
                    help="a set a scene names that no pack holds yet is left out, said, not fatal (a pack mid-regeneration)")
    ap.add_argument("--out", default="", help="write the archive and rests here, not into the repo")
    a = ap.parse_args()
    out_archive = os.path.join(a.out, os.path.basename(OUT_ARCHIVE)) if a.out else OUT_ARCHIVE
    out_rests = os.path.join(a.out, os.path.basename(OUT_RESTS)) if a.out else OUT_RESTS
    if not os.path.isfile(mpw.CLI):
        sys.exit("WolvenKit CLI not found: " + mpw.CLI)
    PACKS = tuple(p for p in a.packs.split(",") if p)
    scenes, clips, local = read_packs(a.anims)

    src, raw, packed = (os.path.join(BUILD, d) for d in ("src", "raw", "packed"))
    for d in (src, raw, packed):
        shutil.rmtree(d, ignore_errors=True)
        os.makedirs(d)
    out_dir = os.path.join(raw, DEST_DIR)
    os.makedirs(out_dir)
    with open(TEMPLATE, encoding="utf-8") as f:
        base = json.load(f)
    before = json.dumps(base)
    mpw.renumber(base)
    if json.dumps(base) != before:
        sys.exit("renumber changed the template -- handle order is not document order")

    all_idles, per = transition_idles(scenes)
    tiered = tiered_clips(scenes)
    rests = {}
    anims_names, anims_rigs = {}, {}
    for heads in (int(h) for h in a.heads.split(",")):
        refs = sorted({c for s in scenes if len(s["actors"]) == heads for sp in s["speeds"] for c in sp["clips"]})
        names, by_name, by_rig, skipped = [], {}, {}, set()
        for ref in refs:
            name = ref.split("/", 1)[1]
            if a.only_clips and name not in a.only_clips.split(","):
                continue
            if "#" in name:
                print("  %dP: %s -- a clip name two sets share, left out (one workspot entry per name)" % (heads, ref))
                continue
            if name in by_name:
                sys.exit("%dP: clip name %s is in two packs (%s, %s)" % (heads, name, by_name[name], ref))
            by_name[name] = ref
            names.append(name)
            for sides in clips[ref].values():
                for depot in sides.values():
                    key = depot.lower()
                    if key not in local and a.skip_missing:
                        skipped.add(depot)
                        continue
                    if key not in local:
                        sys.exit("%s names set %s, which no pack's depot holds" % (ref, depot))
                    if key not in anims_names:
                        anims_names[key] = mpw.clip_names(local[key])
                        anims_rigs[key] = sorted(mpw.rigs_of(local[key]))
                    if name not in anims_names[key]:
                        sys.exit("%s: clip %s is not in its set %s" % (ref, name, depot))
                    if len(anims_rigs[key]) != 1:
                        sys.exit("set %s names %d rigs, want one: %s" % (depot, len(anims_rigs[key]), anims_rigs[key]))
                    by_rig.setdefault(anims_rigs[key][0], set()).add(depot)
        if skipped:
            print("  %dP: %d set(s) no pack holds yet, left out: %s" % (heads, len(skipped), ", ".join(sorted(skipped)[:4])))
        rows = [(rig, sorted(sets, reverse=a.reverse_sets)) for rig, sets in sorted(by_rig.items())]
        idles = {c: i for c, i in all_idles.items() if c in by_name and i in by_name}
        rests.update({t: nxt for t, (nxt, pairs) in per.items() if all(idles.get(c) == i for c, i in pairs)})
        doc = build_tree(base, rows, names, idles, tiered)
        leaf = "ncn_scenes_%dp.workspot" % heads
        out_ws = os.path.join(out_dir, leaf)
        if isinstance(doc.get("Header"), dict):
            doc["Header"]["ArchiveFileName"] = out_ws
        json.dump(doc, open(out_ws + ".json", "w", encoding="utf-8"), indent=1)
        mpw.run([mpw.CLI, "convert", "d", out_ws + ".json", "-o", out_dir, "-v", "quiet"])
        if not os.path.isfile(out_ws):
            sys.exit("deserialize produced no " + leaf)
        os.remove(out_ws + ".json")
        blob = open(out_ws, "rb").read()
        print("%dP: %d entries (%d transitions play once), %s  %.0f KB" % (heads, len(names), len(idles), ", ".join(
            "%s %d sets" % (os.path.basename(r).replace(".rig", ""), len(s)) for r, s in rows), len(blob) / 1024.0))

    mpw.run([mpw.CLI, "pack", raw, "-o", packed, "-v", "quiet"])
    cands = [f for f in os.listdir(packed) if f.endswith(".archive")]
    if not cands:
        sys.exit("pack produced no archive")
    os.makedirs(os.path.dirname(out_archive), exist_ok=True)
    shutil.copyfile(os.path.join(packed, cands[0]), out_archive)
    print("OK -> %s (%.1f KB)" % (out_archive, os.path.getsize(out_archive) / 1024.0))
    os.makedirs(os.path.dirname(out_rests), exist_ok=True)
    json.dump(dict(sorted(rests.items())), open(out_rests, "w", encoding="utf-8"), indent=1)
    print("OK -> %s (%d transitions rest on their next scene)" % (out_rests, len(rests)))


if __name__ == "__main__":
    main()
