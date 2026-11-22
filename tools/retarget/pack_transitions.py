"""Generated transitions into a scene pack: one transition scene per accepted move, and the move rewired through it.

Reads the generator's results (tools/retarget/work/run/gen_results.jsonl, one JSON line per move: from, to, pack,
length, sides[{actor, sex, rig, clip, npc, player}], or a rejected row with a reason) and the pack scene files.
docs/design/scene-graph.md §3: a move plays a transition only when it names the transition scene, which plays once
and rests on its `next`.

  --test (default): into the ncngen test pack, leaving opensex/ostimng alone -- per move a copy of A (ncngen.src.<k>)
                    whose one move is the transition, so the game starts the copy and moves; the real A is untouched.
  --into-source:    the transition lands in the move's own pack and A's move entry is rewritten to it.

  python tools/retarget/pack_transitions.py [--results FILE] [--into-source] [--drop FILE] [--max-overlap M] [--dry]
Then tools/make_scene_workspots.py rebuilds the workspot archive and workspot_rests.json.
"""
import argparse
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build_config  # noqa: E402

ANIMS = build_config.load()["packs"]
SCENES_REL = os.path.join("bin", "x64", "plugins", "cyber_engine_tweaks", "mods", "nightcitynet", "data", "scenes")
RESULTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "work", "run", "gen_results.jsonl")
WOLVENKIT = build_config.load()["tools"]["wolvenkit"] or "WolvenKit.CLI.exe"
TEST = "ncngen"


def key(a_id, b_id):
    """The move's name in ids, clips and sets: A's tail -- B's tail, folder-safe."""
    return re.sub(r"[^a-z0-9_-]", "_", ("%s--%s" % (a_id.split(".")[-1], b_id.split(".")[-1])).lower())


def scene_files(pack):
    return {json.load(open(f, encoding="utf-8"))["id"]: f
            for f in glob.glob(os.path.join(ANIMS, pack, SCENES_REL, "**", "*.json"), recursive=True)
            if os.path.basename(f) != "clips.json"}


def transition_scene(tid, a, b_id, length, clips, sexes):
    """A transition from A to B: A's actors on the bodies each side was generated on, one speed, played once,
    resting on B."""
    return {"id": tid, "name": "%s (generated transition)" % a["name"], "animator": "MotionBricks", "sources": [],
            "actors": [dict(x, tags=[], sex=sex) for x, sex in zip(a["actors"], sexes)],
            "speeds": [{"clips": clips, "playback": 1.0, "display": None}],
            "transition": True, "next": b_id, "length": round(float(length), 4), "moves": [], "tags": ["transition"],
            "furniture": a.get("furniture"), "acts": [], "strip": [[] for _ in a["actors"]]}


def depot_rel(pack, path):
    """A cooked .anims' depot path in pack: <pack>\\anims\\<npc|player>\\<file>."""
    return "\\".join([pack, "anims", os.path.basename(os.path.dirname(path)), os.path.basename(path)])


def plan(rows, pack_of, test, drop=frozenset()):
    """[(pack, scene id, scene dict, file rel)], {pack: {clip key: entry}}, {pack: {depot rel: source path}}, A edits.
    Into the source, a move with a side V has no clip for is left a cut: a rewired A with V in it could not play it."""
    scenes, clips, files, rewires = [], {}, {}, []
    for r in rows:
        if r.get("rejected") or (r["from"], r["to"]) in drop:
            continue
        if not test and not all(s.get("player") for s in r["sides"]):
            print("  no V clip, left a cut: %s -> %s" % (r["from"], r["to"]))
            continue
        a_pack = r["pack"]
        a_file = pack_of[a_pack][r["from"]]
        a = json.load(open(a_file, encoding="utf-8"))
        k = key(r["from"], r["to"])
        pack = TEST if test else a_pack
        tid = "%s.gen.%s" % (pack, k)
        if any(sid == tid for _, sid, _, _ in scenes):
            sys.exit("two moves name one transition %s: %s -> %s" % (tid, r["from"], r["to"]))
        sides = sorted(r["sides"], key=lambda s: s["actor"])
        names = []
        for s in sides:
            name = "%s/%s" % (pack, s["clip"])
            names.append(name)
            row = clips.setdefault(pack, {}).setdefault(name, {}).setdefault(s["sex"], {})
            for kind in ("npc", "player"):
                if s.get(kind):
                    row[kind] = depot_rel(pack, s[kind])
                    files.setdefault(pack, {})[row[kind]] = s[kind]
        scenes.append((pack, tid, transition_scene(tid, a, r["to"], r["length"], names, [s["sex"] for s in sides]),
                       os.path.join("gen", k + ".json")))
        if test:
            src = dict(a, id="%s.src.%s" % (TEST, k), name="%s (to %s)" % (a["name"], r["to"].split(".")[-1]),
                       moves=[{"to": tid, "label": "generated", "priority": 0}])
            scenes.append((TEST, src["id"], src, os.path.join("src", k + ".json")))
        else:
            rewires.append((a_file, r["to"], tid))
    return scenes, clips, files, rewires


def overlapping(rows, limit):
    """{(from, to)}: accepted moves whose bodies overlap more than limit m past the closer of A's end and B's start."""
    return {(r["from"], r["to"]) for r in rows
            if not r.get("rejected") and r["gap"] - min(r["gap_a"], r["gap_b"]) < -limit}


def missing_v(rows):
    """Accepted moves with a side V's bake has no clip for."""
    return [r for r in rows if not r.get("rejected") and not all(s.get("player") for s in r["sides"])]


def rewire(a_file, b_id, tid):
    """A's move to B now names the transition (already naming it is done). Rewritten whole: generated JSON."""
    a = json.load(open(a_file, encoding="utf-8"))
    if any(m["to"] == tid for m in a["moves"]):
        return
    hit = [m for m in a["moves"] if m["to"] == b_id]
    if not hit:
        sys.exit("%s has no move to %s" % (a["id"], b_id))
    for m in hit:
        m["to"] = tid
    write_json(a_file, a)


def unpack_stale(pack, keep, files):
    """A transition an earlier run packed and this one does not: A's move back to B, the scene and its clip rows gone.
    files: the pack's {scene id: path}. Its .anims stay in the depot, unreferenced."""
    stale = {sid: json.load(open(p, encoding="utf-8")) for sid, p in files.items() if ".gen." in sid and sid not in keep}
    for sid, p in files.items():
        if sid in stale:
            continue
        s = json.load(open(p, encoding="utf-8"))
        hit = [m for m in s.get("moves") or [] if m["to"] in stale]
        for m in hit:
            m["to"] = stale[m["to"]]["next"]
        if hit:
            write_json(p, s)
    clip_rows = {c for t in stale.values() for sp_ in t["speeds"] for c in sp_["clips"]}
    for sid in stale:
        os.remove(files[sid])
    gone = list(stale)
    if clip_rows:
        path = os.path.join(ANIMS, pack, SCENES_REL, pack, "clips.json")
        old = json.load(open(path, encoding="utf-8"))
        write_json(path, {c: v for c, v in old.items() if c not in clip_rows})
    return gone


def write_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(obj, fh, indent=1)
        fh.write("\n")


def pack_archive(pack):
    """<pack>/depot/<pack> -> <pack>/archive/pc/mod/<pack>.archive."""
    with tempfile.TemporaryDirectory() as tmp:
        stage = os.path.join(tmp, pack)
        shutil.copytree(os.path.join(ANIMS, pack, "depot", pack), os.path.join(stage, pack))
        subprocess.run([WOLVENKIT, "pack", stage, "-o", tmp, "-v", "Minimal"], check=True)
        arc = os.path.join(ANIMS, pack, "archive", "pc", "mod")
        os.makedirs(arc, exist_ok=True)
        shutil.copy2(os.path.join(tmp, pack + ".archive"), os.path.join(arc, pack + ".archive"))


def main():
    import build_config
    build_config.motionbricks_or_exit()   # its moves reach the packs only with MotionBricks on
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--results", default=RESULTS)
    ap.add_argument("--into-source", action="store_true")
    ap.add_argument("--drop", help="file of 'from to' lines (the first two words): accepted moves left a cut")
    ap.add_argument("--max-overlap", type=float, default=0.20,
                    help="m past the authored poses' overlap: a move overlapping more is left a cut")
    ap.add_argument("--allow-missing-v", action="store_true", help="pack anyway; a move with no V clip stays a cut")
    ap.add_argument("--dry", action="store_true")
    a = ap.parse_args()
    rows = [json.loads(x) for x in open(a.results, encoding="utf-8") if x.strip()]
    drop = frozenset(tuple(x.split()[:2]) for x in open(a.drop, encoding="utf-8") if x.strip()) if a.drop else frozenset()
    over = overlapping(rows, a.max_overlap)
    print("%d moves overlap over %.0f cm past the authored poses, left cuts" % (len(over), a.max_overlap * 100))
    drop |= over
    test = not a.into_source
    no_v = missing_v(rows)
    if not test and no_v and not a.allow_missing_v:
        sys.exit("%d accepted moves have no V clip (first %s -> %s): V's bake failed or did not run, and packing now "
                 "would unpack their transitions; --allow-missing-v leaves them cuts" % (
                     len(no_v), no_v[0]["from"], no_v[0]["to"]))
    pack_of = {p: scene_files(p) for p in {r["pack"] for r in rows}}
    scenes, clips, files, rewires = plan(rows, pack_of, test, drop)
    print("%d moves, %d rejected -> %d scenes, %d anims, %d rewires" % (
        len(rows), sum(1 for r in rows if r.get("rejected")), len(scenes),
        sum(len(f) for f in files.values()), len(rewires)))
    if a.dry:
        return
    if test:  # the test pack holds only this run's moves
        shutil.rmtree(os.path.join(ANIMS, TEST, SCENES_REL, TEST), ignore_errors=True)
        shutil.rmtree(os.path.join(ANIMS, TEST, "depot", TEST), ignore_errors=True)
    else:
        keep = {sid for _, sid, _, _ in scenes}
        for pack in sorted(pack_of):
            for sid in unpack_stale(pack, keep, scene_files(pack)):
                print("  no longer packed, A moves to B again: %s" % sid)
    for pack, _, s, rel in scenes:
        write_json(os.path.join(ANIMS, pack, SCENES_REL, pack, rel), s)
    for pack, rows_ in clips.items():
        path = os.path.join(ANIMS, pack, SCENES_REL, pack, "clips.json")
        old = json.load(open(path, encoding="utf-8")) if os.path.isfile(path) else {}
        write_json(path, dict(sorted({**old, **rows_}.items())))
    for pack, fs in files.items():
        for rel, src in fs.items():
            out = os.path.join(ANIMS, pack, "depot", rel)
            os.makedirs(os.path.dirname(out), exist_ok=True)
            shutil.copy2(src, out)
        pack_archive(pack)
    for f, b, t in rewires:
        rewire(f, b, t)
    print("done; next: python tools/make_scene_workspots.py")


if __name__ == "__main__":
    main()
