"""OpenSex (Skyrim, CC BY-SA 4.0) ported whole onto Cyberpunk's NPC rigs and V's skeletons, cooked and packed.

  inventory  skyrim_scenes.py: the scene XML -> manifest.json (clip, actor sex, set), scenes.json, source-map.json
  clips      per source clip, once: tagfile -> packfile XML (skyrim_tagfile) -> hkxc win32 -> blender-hkx unpack
             against the padded skeleton of the actor's sex (skyrim_skeleton) -> decoded/<hash>.npz; then per body
             skyrim_retarget onto man_base / woman_base -> clips/<npc set>/<clip>.npz. Four workers; a clip newer
             than its source and skeleton is skipped, and a decode is reused by every body (only it needs Windows)
  (glbs, cook and verify skip a set whose input has not changed; --all redoes every set. `all` runs verify only with
  --verify.)
  glbs       per set: the npc glb from its clips, an oral giver slid by pair_reach.py's pair_shift.json, and
             retarget_glb.py from it onto V's skeleton
  cook       every set's container (anims_json prep), deserialized, then wk_anims --list, one process per worker
  bodies     every npc set's glb retargeted onto man_big / man_fat / woman_big / woman_fat and cooked
  verify     every cooked set re-exported and checked against its glb (verify_retarget.py), buffers all SIMD
  pack       depot, scenes.json and source-map.json into the pack repo, and its archive

Run: python tools/retarget/skyrim_port.py <stage> [--only <set substring>] [paths, see --help]
Everything but the pack lands under work/skyrim/port, gitignored: it is Bethesda-skeleton and CDPR data.

The inventory stage is OpenSex's. Another source brings its own manifest in the same rows (skyrim_scenes.py), a
row's `skeleton` naming the .hkx it decodes against, and runs the rest with --port-dir, --source-root and --pack:
  python tools/retarget/skyrim_scenes_ostimng.py work/skyrim/ostimng
  python tools/retarget/skyrim_port.py clips --port-dir work/skyrim/ostimng --source-root <OStimNG> ...
  ... pack --pack <CyberpunkAnimations>/ostimng --ship-glb       (GPL: the glb is the source)
"""
import argparse
import concurrent.futures
import hashlib
import json
import multiprocessing
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import anims_json  # noqa: E402
import build_config  # noqa: E402
import skyrim_retarget as sr  # noqa: E402
import skyrim_scenes  # noqa: E402
import skyrim_tagfile  # noqa: E402

WORK = os.path.join(HERE, "work")
PORT = build_config.load()["sources"]["opensex"]["run"]   # inventory writes OpenSex's manifest here alone
# Every skeleton a clip is fitted onto ships with the tool: skeletons/cyberpunk/<name>.rig, .rig.json, .glb, and the
# empty animset.anims.json the cook fills (make_skeletons.py)
SKEL = os.path.join(build_config.ROOT, "skeletons", "cyberpunk")
# rig -> (its depot path, its name in SKEL)
RIGS = {
    "man_base": (r"base\characters\base_entities\man_base\man_base.rig", "man_base"),
    "woman_base": (r"base\characters\base_entities\woman_base\woman_base.rig", "woman_base"),
    "player_man": (r"base\characters\entities\player\player_man_skeleton.rig", "player_man_skeleton"),
    "player_woman": (r"base\characters\entities\player\player_woman_skeleton.rig", "player_woman_skeleton"),
}


def skel_name(rig):
    return RIGS[rig][1] if rig in RIGS else rig


def rig_json(rig):
    return os.path.join(SKEL, skel_name(rig) + ".rig.json")
# The big and fat NPC rigs: each npc set's glb retargeted onto them (the bodies stage), as retarget.ps1 -Rig did
BODIES = {"man_base": ("man_big", "man_fat"), "woman_base": ("woman_big", "woman_fat")}
SKELETON = {"f": ("femskeleton.hkx", "female242.hkx"), "m": ("skeleton.hkx", "male242.hkx")}
# A 242-track clip: its track names pad the skeletons (skyrim_skeleton.py).
PAD_CLIP = r"meshes\0SA\mod\0Sex\anim\OpS\KneAFo\Ap\FemaleAllFours\_Ap-FemaleAllFours_0.hkx"


def args_parser():
    # every default is build.json's (build_config.py); a flag still wins
    cfg = build_config.load()
    t, os_ = cfg["tools"], cfg["sources"]["opensex"]
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("stage", choices=("inventory", "clips", "glbs", "cook", "bodies", "verify", "pack", "all"))
    ap.add_argument("--source", default="", help="a build.json source: its input, run folder, pack and ship_glb")
    ap.add_argument("--only", default="", help="sets whose depot path contains this")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--opensex", default=os_["input"])
    ap.add_argument("--port-dir", default=PORT, help="where the manifest is and the work goes")
    ap.add_argument("--source-root", default="", help="a manifest row's file is relative to this (default --opensex)")
    ap.add_argument("--ship-glb", action="store_true", help="pack each set's glb beside it (a GPL pack's source)")
    ap.add_argument("--hkxc", default=t["hkxc"])
    ap.add_argument("--blender-hkx", default=t["blender_hkx"])
    ap.add_argument("--skeletons", default=t["skeletons"], help="the Skyrim skeleton.hkx / femskeleton.hkx")
    ap.add_argument("--game", default=t["game"])
    # Linux: the nightly's WolvenKit.CLI.dll under dotnet, libkraken.so beside it (README, "Which stage needs Windows")
    ap.add_argument("--wolvenkit", default=t["wolvenkit"] if os.name == "nt"
                    else os.path.join(WORK, "wk_nightly", "WolvenKit.CLI.dll"))
    ap.add_argument("--wolvenkit-cook", default=t["wolvenkit_cook"])
    ap.add_argument("--pack", default=os_["pack"])
    ap.add_argument("--max-deg", type=float, default=0.1)
    ap.add_argument("--all", action="store_true", help="glbs, cook, verify: every set, not only those whose input changed")
    ap.add_argument("--verify", action="store_true", help="all: check the cooked sets too (after a WolvenKit or retarget change)")
    ap.add_argument("--sets", default="", help="a file of npc set depot paths, one a line: only those and their V sets")
    return ap


def wk(a, *args):
    """WolvenKit's CLI: the .exe, or a .dll under dotnet"""
    return run(*(("dotnet", a.wolvenkit) if a.wolvenkit.endswith(".dll") else (a.wolvenkit,)), *args)


def run(*cmd, env=None):
    r = subprocess.run([str(c) for c in cmd], capture_output=True, text=True,
                       env={**os.environ, "RAYON_NUM_THREADS": "4", **(env or {})})
    if r.returncode != 0:
        raise RuntimeError("%s failed (exit %d):\n%s%s" % (" ".join(map(str, cmd)), r.returncode, r.stdout, r.stderr))
    return r.stdout


SETS = None    # --sets: the npc sets this run is limited to


def manifest():
    path = os.path.join(PORT, "manifest.json")
    if not os.path.isfile(path):
        sys.exit("no %s: run the inventory stage first" % path)
    rows = json.load(open(path, encoding="utf-8"))
    return rows if SETS is None else [r for r in rows if r["npcSet"] in SETS]


def sets_of(rows, only):
    """{depot path: (rig, [rows in clip order])} for the npc and the player sets."""
    out = {}
    for r in rows:
        for depot, rig in ((r["npcSet"], r["rig"]), (r["playerSet"], r["playerRig"])):
            if only.lower() in depot.lower():
                out.setdefault(depot, (rig, []))[1].append(r)
    for _, rs in out.values():
        rs.sort(key=lambda r: r["clip"])
    return out


def fresh(out, srcs, a):
    """out exists and is newer than every source: a set nothing changed is not rebuilt, cooked or checked (--all redoes it)."""
    if a.all or not os.path.isfile(out):
        return False
    t = os.path.getmtime(out)
    return all(os.path.getmtime(s) <= t for s in srcs if os.path.isfile(s))


def local(depot):
    """a depot path (the game's backslashes) as a path on this machine"""
    return depot.replace("\\", os.sep)


def npz_path(row):
    # by set: one clip name can sit in two sets (OStimNG's OStimBed2PBothSittingMF, FF and MF)
    return os.path.join(PORT, "clips", local(row["npcSet"][:-len(".anims")]), row["clip"] + ".npz")


def rig_files(rig):
    """(the rig's depot path, its cr2w, the animset json its empty container is made from)"""
    path = RIGS[rig][0] if rig in RIGS else "base\\characters\\base_entities\\%s\\%s.rig" % (rig, rig)
    return path, os.path.join(SKEL, skel_name(rig) + ".rig"), os.path.join(SKEL, "animset.anims.json")


def body_sets(npc_sets):
    """{big/fat set depot path: (rig, its npc set)}: npc\\x_ma.anims -> man_big\\x_ma_man_big.anims, as the pack names them"""
    out = {}
    for depot, (rig, _) in npc_sets.items():
        for body in BODIES.get(rig, ()):
            out[depot.replace("\\npc\\", "\\%s\\" % body)[:-len(".anims")] + "_%s.anims" % body] = (body, depot)
    return out


def donor(rig):
    """the rig's armature, the glb clips are retargeted onto"""
    return os.path.join(SKEL, skel_name(rig) + ".glb")


def mesh_path(row, port=None):
    # the interaction mesh's pose of a pair clip (pair_contact.py SAVE=1), its pair_shift already in
    return os.path.join(port or PORT, "mesh", local(row["npcSet"][:-len(".anims")]), row["clip"] + ".npz")


def glb_path(depot):
    return os.path.join(PORT, "glb", local(depot) + ".glb")


def other_body(r):
    """r's row for the other body: a scene's side plays on either (scene-picker.md §1b)."""
    sex = "m" if r["sex"] == "f" else "f"
    flip = lambda p: re.sub(r"_(p?)[mw]a\.anims$", lambda m: "_%s%sa.anims" % (m.group(1), sex.replace("f", "w")), p)
    return {**r, "sex": sex, "srcSex": r.get("srcSex", r["sex"]), "rig": "man_base" if sex == "m" else "woman_base",
            "playerRig": "player_man" if sex == "m" else "player_woman",
            "npcSet": flip(r["npcSet"]), "playerSet": flip(r["playerSet"])}


def stage_inventory(a):
    work, scenes, source = skyrim_scenes.build(a.opensex)
    # a row the scenes do not make (a hand-fixed "-fix" clip, opensex-port.md) stays, on both bodies
    path = os.path.join(PORT, "manifest.json")
    made = {r["clip"] for r in work}
    kept = [r for r in json.load(open(path, encoding="utf-8")) if r["clip"] not in made] if os.path.isfile(path) else []
    have = {(r["clip"], r["sex"]) for r in kept}
    work += kept + [t for t in map(other_body, kept) if (t["clip"], t["sex"]) not in have]
    os.makedirs(PORT, exist_ok=True)
    for name, data in (("manifest.json", work), ("scenes.json", scenes), ("source-map.json", source)):
        with open(os.path.join(PORT, name), "w", encoding="utf-8", newline="\n") as fh:
            json.dump(data, fh, indent=1, ensure_ascii=False)
            fh.write("\n")
    skel = os.path.join(PORT, "skel")
    os.makedirs(skel, exist_ok=True)
    for src, out in SKELETON.values():
        if not os.path.isfile(os.path.join(skel, out)):
            run(sys.executable, os.path.join(HERE, "skyrim_skeleton.py"), a.hkxc, os.path.join(a.skeletons, src),
                os.path.join(a.opensex, PAD_CLIP), os.path.join(skel, out))
    print("%d bakes, %d scenes, skeletons in %s" % (len(work), len(scenes), skel))


_targets = {}


def _init(paths):
    global _cfg, PORT
    _cfg = paths
    PORT = paths["port"]  # a spawned worker re-imports the module, default and all
    for rig in ("man_base", "woman_base"):
        _targets[rig] = sr.Target(donor(rig))


def decode(src, skeleton, tmp, cfg):
    w32 = os.path.join(tmp, "clip_w32.hkx")
    if open(src, "rb").read(5) == b"<?xml":
        pack = os.path.join(tmp, "clip.xml")
        with open(pack, "w", encoding="ascii", newline="\n") as fh:
            fh.write(skyrim_tagfile.convert(src))
        run(cfg["hkxc"], "convert", "-i", pack, "-o", w32, "-v", "win32")
    else:
        run(cfg["hkxc"], "convert", "-i", src, "-o", w32, "-v", "win32")
    out = os.path.join(tmp, "decoded.xml")
    run(cfg["blender_hkx"], "unpack", w32, out, skeleton)
    return out


def skeleton_of(row):
    return row.get("skeleton") or os.path.join(PORT, "skel", SKELETON[row.get("srcSex", row["sex"])][1])


def decoded_path(row):
    """One source clip against one skeleton: decoded once, whichever bodies it is baked on."""
    tag = hashlib.sha1(("%s|%s" % (row["file"].lower(), os.path.basename(skeleton_of(row)).lower())).encode()).hexdigest()
    return os.path.join(PORT, "decoded", tag[:16] + ".npz")


def clip_done(row, out, srcs):
    if not os.path.isfile(out) or any(os.path.getmtime(s) > os.path.getmtime(out) for s in srcs if os.path.isfile(s)):
        return False
    with np.load(out) as z:
        if "skeleton" in z:
            return str(z["skeleton"]) == os.path.basename(skeleton_of(row))
    # written before the skeleton was recorded: decoded against the body's own sex's, right only when that is the actor's
    return row.get("srcSex", row["sex"]) == row["sex"]


def _decoded(row, src, skeleton):
    path = decoded_path(row)
    if os.path.isfile(path) and all(os.path.getmtime(s) <= os.path.getmtime(path) for s in (src, skeleton)):
        with np.load(path) as z:
            names = [str(n) for n in z["names"]]
            return ({n: i for i, n in enumerate(names)}, [int(p) for p in z["parent"]], z["obj_t"], z["obj_r"],
                    z["rot"].astype(np.float64), z["tra"].astype(np.float64), int(z["frames"])), False
    with tempfile.TemporaryDirectory() as tmp:
        clip = sr.read_clip(decode(src, skeleton, tmp, _cfg))
    idx, parent, obj_t, obj_r, rot, tra, frames = clip
    os.makedirs(os.path.dirname(path), exist_ok=True)
    np.savez_compressed(path + ".tmp.npz", names=np.array(sorted(idx, key=idx.get)), parent=np.array(parent),
                        obj_t=obj_t, obj_r=obj_r, rot=rot.astype(np.float32), tra=tra.astype(np.float32),
                        frames=frames)
    os.replace(path + ".tmp.npz", path)
    return (idx, parent, obj_t, obj_r, rot.astype(np.float32).astype(np.float64),
            tra.astype(np.float32).astype(np.float64), frames), True


def _clip(row):
    out, src, skeleton = npz_path(row), os.path.join(_cfg["source"], row["file"]), skeleton_of(row)
    if clip_done(row, out, (src, skeleton)):
        return row["clip"], "kept", 0
    t0 = time.time()
    try:
        clip, decoded = _decoded(row, src, skeleton)
        rot, tra = sr.retarget(clip, _targets[row["rig"]])
        os.makedirs(os.path.dirname(out), exist_ok=True)
        np.savez(out + ".tmp.npz", rot=rot.astype(np.float32), tra=tra.astype(np.float32),
                 skeleton=os.path.basename(skeleton))
        os.replace(out + ".tmp.npz", out)
        return row["clip"], "decoded" if decoded else "retargeted", time.time() - t0
    except (RuntimeError, ValueError, OSError) as e:
        return row["clip"], "FAILED %s" % str(e).strip().splitlines()[0], time.time() - t0


def _clips(rows):
    return [_clip(r) for r in rows]


def stage_clips(a):
    # V's set is baked from the npc clips, so --only on a player set selects its npc rows too
    rows = [r for r in manifest() if any(a.only.lower() in r[k].lower() for k in ("npcSet", "playerSet"))]
    cfg = {"source": a.source_root, "hkxc": a.hkxc, "blender_hkx": a.blender_hkx, "port": PORT}
    # the bodies of one decode go to one worker, so two never decode the same clip at once
    groups = {}
    for r in rows:
        groups.setdefault(decoded_path(r), []).append(r)
    failed, counts, n, t0 = [], {}, 0, time.time()
    with multiprocessing.Pool(a.workers, _init, (cfg,)) as pool:
        for done in pool.imap_unordered(_clips, list(groups.values())):
            for clip, what, dt in done:
                n += 1
                counts[what.split()[0]] = counts.get(what.split()[0], 0) + 1
                if what.startswith("FAILED"):
                    failed.append((clip, what))
                if what != "kept" and (n % 25 == 0 or what.startswith("FAILED")):
                    print("%4d/%d %-44s %s %.1fs" % (n, len(rows), clip, what, dt), flush=True)
    print("%d clips in %.0fs: %s" % (len(rows), time.time() - t0, ", ".join("%d %s" % (v, k) for k, v in sorted(counts.items()))))
    for clip, what in failed:
        print("  %s: %s" % (clip, what))
    return not failed


def _player_glb(job):
    src, out, rig = job
    run(sys.executable, os.path.join(HERE, "retarget_glb.py"), src, donor(rig), out, "--rig=" + rig_json(rig))
    return out


def stage_glbs(a):
    import pair_reach  # imports this module
    sets = sets_of(manifest(), a.only)
    shifts, slid, meshed = pair_reach.load(PORT), 0, 0
    jobs, skipped = [], 0
    shift_file = os.path.join(PORT, "pair_shift.json")
    for depot, (rig, rows) in sorted(sets.items()):
        if rig.startswith("player_"):
            continue
        out, player = glb_path(depot), rows[0]["playerSet"]
        if fresh(out, [npz_path(r) for r in rows] + [mesh_path(r) for r in rows] + [shift_file], a):
            skipped += 1
            if player in sets and not fresh(glb_path(player), [out], a):
                jobs.append((out, glb_path(player), rows[0]["playerRig"]))
            continue
        tg = sr.Target(donor(rig))
        extras = sr.extras_for(tg, rig_json(rig))
        clips = []
        for r in rows:
            p = npz_path(r)
            if not os.path.isfile(p):
                sys.exit("not decoded: %s (run the clips stage)" % p)
            m = mesh_path(r)
            if os.path.isfile(m):
                if os.path.getmtime(m) < os.path.getmtime(p):
                    sys.exit("stale: %s is older than its clip (rerun pair_batch.py with SAVE=1)" % m)
                z = np.load(m)
                clips.append((r["clip"], z["rot"].astype(np.float64), z["tra"].astype(np.float64)))
                meshed += 1
                continue
            z = np.load(p)
            rot, tra = z["rot"].astype(np.float64), z["tra"].astype(np.float64)
            if pair_reach.key(r) in shifts:  # pair_reach.py: the giver slid to the source's oral reach
                pair_reach.apply_shift(tg.skel, rot, tra, np.array(shifts[pair_reach.key(r)]["shift"]))
                slid += 1
            clips.append((r["clip"], rot, tra))
        os.makedirs(os.path.dirname(out), exist_ok=True)
        sr.write(tg, extras, clips, out)
        print("%-44s %3d clips" % (depot, len(clips)), flush=True)
        if player in sets:
            os.makedirs(os.path.dirname(glb_path(player)), exist_ok=True)
            jobs.append((out, glb_path(player), rows[0]["playerRig"]))
    print("%d clips slid by pair_shift.json, %d from the interaction mesh; %d npc sets unchanged, %d V sets to bake" % (
        slid, meshed, skipped, len(jobs)), flush=True)
    with multiprocessing.Pool(a.workers) as pool:
        for out in pool.imap_unordered(_player_glb, jobs):
            print("  V  " + os.path.relpath(out, PORT), flush=True)


def stage_cook(a):
    depot_root = os.path.join(PORT, "depot")
    every = sets_of(manifest(), a.only)
    sets = {d: s for d, s in every.items() if not fresh(os.path.join(depot_root, local(d)), [glb_path(d)], a)}
    print("%d sets to cook, %d unchanged" % (len(sets), len(every) - len(sets)), flush=True)
    cook_sets(a, sets)


def cook_sets(a, sets):
    """{depot path: (rig, _)}: each set's glb cooked onto its rig's empty container, under PORT/depot"""
    if not sets:
        return
    depot_root = os.path.join(PORT, "depot")
    # The empty container is the rig's alone: deserialized once per rig and kept, then copied under each set's name.
    empty = os.path.join(WORK, "empty_anims")
    os.makedirs(empty, exist_ok=True)
    for rig in sorted({rig for rig, _ in sets.values()}):
        rig_path, _, src = rig_files(rig)
        if not fresh(os.path.join(empty, rig + ".anims"), [src], a):
            anims_json.prep(src, rig_path, os.path.join(empty, rig + ".anims.json"))
            wk(a, "convert", "deserialize", os.path.join(empty, rig + ".anims.json"), "-o", empty, "-v", "Minimal")
            if not os.path.isfile(os.path.join(empty, rig + ".anims")):
                sys.exit("deserialize wrote no %s.anims in %s" % (rig, empty))
    pairs = []
    for depot, (rig, _) in sorted(sets.items()):
        anims = os.path.join(depot_root, local(depot))
        os.makedirs(os.path.dirname(anims), exist_ok=True)
        # cooked beside the set and renamed on success: a killed cook leaves no container that looks done
        shutil.copyfile(os.path.join(empty, rig + ".anims"), anims + ".cooking")
        pairs.append((glb_path(depot), anims))
    for glb, anims in pairs:
        if not os.path.isfile(glb):
            sys.exit("missing %s" % glb)
    bin_dir = os.path.join(HERE, "wk_anims", "bin", "Release", "net10.0")
    if os.name == "nt":   # elsewhere the build ships prebuilt (pod/bake_bundle.py): a runtime, no SDK
        run("dotnet", "build", os.path.join(HERE, "wk_anims", "WkAnims.csproj"), "-c", "Release", "-v", "q", "--nologo")
    bridge = (os.path.join(bin_dir, "WkAnims.exe"),) if os.name == "nt" else ("dotnet", os.path.join(bin_dir, "WkAnims.dll"))
    archive = rigs_archive(a)
    # one WkAnims per worker, each cooking its share in turn: one process cooks one set at a time
    shares = [pairs[i::a.workers] for i in range(min(a.workers, len(pairs)))]

    def cook(n):
        lst = os.path.join(PORT, "cook_%d.tsv" % n)
        with open(lst, "w", encoding="utf-8") as fh:
            fh.write("".join("%s\t%s.cooking\n" % p for p in shares[n]))
        out = run(*bridge, "--list", lst, archive, os.path.abspath(a.wolvenkit_cook), env={"NCN_GAME_DIR": a.game})
        for _, anims in shares[n]:
            os.replace(anims + ".cooking", anims)
        return len(shares[n]), out

    t0 = time.time()
    with concurrent.futures.ThreadPoolExecutor(len(shares)) as pool:
        for k, _ in pool.map(cook, range(len(shares))):
            print("  %d cooked" % k, flush=True)
    print("%d sets cooked by %d processes in %.0fs" % (len(pairs), len(shares), time.time() - t0))


def _body_glb(job):
    src, out, rig = job
    _, cr2w, _ = rig_files(rig)
    run(sys.executable, os.path.join(HERE, "retarget_glb.py"), src, donor(rig), out, "--rig=" + cr2w + ".json",
        "--drop-missing")   # an NPC rig may lack a source bone
    return out


def stage_bodies(a):
    """every npc set onto the big and fat rigs: its glb retargeted (retarget_glb.py), then cooked"""
    npc = {d: s for d, s in sets_of(manifest(), a.only).items() if s[0] in BODIES}
    every = body_sets(npc)
    jobs = [(glb_path(n), glb_path(d), rig) for d, (rig, n) in sorted(every.items())
            if not fresh(glb_path(d), [glb_path(n)], a)]
    for _, out, _ in jobs:
        os.makedirs(os.path.dirname(out), exist_ok=True)
    missing = [s for s, _, _ in jobs if not os.path.isfile(s)]
    if missing:
        sys.exit("no npc glb %s (run the glbs stage)" % missing[0])
    print("%d big/fat glbs to retarget, %d unchanged" % (len(jobs), len(every) - len(jobs)), flush=True)
    with multiprocessing.Pool(a.workers) as pool:
        for n, _ in enumerate(pool.imap_unordered(_body_glb, jobs), 1):
            if n % 25 == 0:
                print("  %d/%d retargeted" % (n, len(jobs)), flush=True)
    depot_root = os.path.join(PORT, "depot")
    sets = {d: s for d, s in every.items() if not fresh(os.path.join(depot_root, local(d)), [glb_path(d)], a)}
    print("%d big/fat sets to cook, %d unchanged" % (len(sets), len(every) - len(sets)), flush=True)
    cook_sets(a, sets)


def rigs_archive(a):
    """Every rig we cook onto (extract.ps1's, and the big and fat ones) packed once: all the cook reads of the game,
    so it needs no install."""
    rigs = [rig_files(r)[:2] for r in list(RIGS) + [b for bs in BODIES.values() for b in bs]]
    out = os.path.join(WORK, "rigs", "rigs.archive")
    # the rigs it holds, beside it: a rig added later is older than the archive, so dates alone would keep it out
    listed, want = os.path.join(WORK, "rigs", "rigs.txt"), "".join(p + "\n" for p, _ in rigs)
    held = open(listed, encoding="utf-8").read() if os.path.isfile(listed) else ""
    if held == want and fresh(out, [src for _, src in rigs], a):
        return out
    stage = os.path.join(WORK, "rigs", "rigs")
    shutil.rmtree(stage, ignore_errors=True)
    for path, src in rigs:
        os.makedirs(os.path.dirname(os.path.join(stage, local(path))), exist_ok=True)
        shutil.copyfile(src, os.path.join(stage, local(path)))
    wk(a, "pack", stage, "-o", os.path.dirname(out), "-v", "Minimal")
    with open(listed, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(want)
    return out


def stage_verify(a):
    check = os.path.join(PORT, "check")
    every = sets_of(manifest(), a.only)
    # passed already: its stamp is newer than the cooked set
    sets = {d: s for d, s in every.items() if not fresh(os.path.join(check, d) + ".ok", [os.path.join(PORT, "depot", d)], a)}
    print("%d sets to check, %d unchanged" % (len(sets), len(every) - len(sets)), flush=True)
    if not sets:
        return True
    # export takes a folder: only the sets being checked have their .anims there; the rest keep their re-exports
    for d in {os.path.dirname(os.path.join(check, dp)) for dp in sets}:
        for f in os.listdir(d) if os.path.isdir(d) else ():
            if f.endswith(".anims"):
                os.remove(os.path.join(d, f))
    for dp in sets:
        for ext in (".json", ".glb", ".ok"):
            if os.path.isfile(os.path.join(check, dp) + ext):
                os.remove(os.path.join(check, dp) + ext)
        os.makedirs(os.path.dirname(os.path.join(check, dp)), exist_ok=True)
        shutil.copy2(os.path.join(PORT, "depot", dp), os.path.join(check, dp))
    cli = os.path.join(a.wolvenkit_cook, "WolvenKit.CLI.exe")
    for d in sorted({os.path.dirname(os.path.join(check, dp)) for dp in sets}):
        run(cli, "export", d, "-o", d, "-gp", a.game, "-v", "Minimal")
        run(cli, "convert", "serialize", d, "-v", "Minimal")
    bad = []
    for depot in sorted(sets):
        cooked = os.path.join(check, depot)
        kinds = re.findall(r'"animAnimationBuffer(\w+)"', open(cooked + ".json", encoding="utf-8").read())
        r = subprocess.run([sys.executable, os.path.join(HERE, "verify_retarget.py"), glb_path(depot), cooked + ".glb",
                            "--max-deg", str(a.max_deg)], capture_output=True, text=True)
        last = (r.stdout.strip().splitlines() or [""])[-1]
        simd = bool(kinds) and all(k == "Simd" for k in kinds)
        if r.returncode != 0 or not simd:
            bad.append(depot)
        else:
            open(cooked + ".ok", "w").close()
        print("%-4s %-44s %3d buffers %s  %s" % ("ok" if depot not in bad else "BAD", depot, len(kinds),
                                                 "SIMD" if simd else "NOT ALL SIMD", last), flush=True)
    print("%d sets, %d bad" % (len(sets), len(bad)))
    return not bad


def stage_pack(a):
    sets = sets_of(manifest(), "")
    tops = {d.split("\\")[0] for d in sets}
    if len(tops) != 1:
        sys.exit("a pack's sets share one top folder; these have %s" % sorted(tops))
    top, name = tops.pop(), os.path.basename(os.path.normpath(a.pack))
    if not os.path.isdir(os.path.join(a.pack, "..", ".git")):
        sys.exit("%s is not inside the pack repo" % a.pack)
    dst, glbs = os.path.join(a.pack, "depot"), os.path.join(a.pack, "glb")
    arc = os.path.join(a.pack, "archive", "pc", "mod")
    # the big and fat sets the bodies stage made; one it did not keeps the pack's own (retarget.ps1 -Rig's)
    bodies = sorted(d for d in body_sets({k: v for k, v in sets.items() if v[0] in BODIES})
                    if os.path.isfile(os.path.join(PORT, "depot", local(d))))
    srcs = [os.path.join(PORT, "depot", local(d)) for d in list(sets) + bodies] + \
        [os.path.join(PORT, f) for f in ("scenes.json", "source-map.json")] + \
        [os.path.join(d, f) for d, _, fs in os.walk(dst) for f in fs]   # big/fat sets gen_bodies.py put there
    if fresh(os.path.join(arc, name + ".archive"), srcs + ([glb_path(d) for d in sets] if a.ship_glb else []), a):
        print("%s.archive is newer than every set: not repacked" % name)
        write_scene_list(a, name)
        merge_clips_json(a.pack, name)
        return
    # only the folders our sets live in, and not a generated transition (gen_*, pack_transitions.py's): the big and
    # fat rigs' folders are retarget.ps1 -Rig's, and clearing them dropped every one of those sets from the pack
    for d in {os.path.dirname(os.path.join(dst, local(depot))) for depot in sets}:
        for f in os.listdir(d) if os.path.isdir(d) else ():
            if not f.startswith("gen_") and os.path.isfile(os.path.join(d, f)):
                os.remove(os.path.join(d, f))
    shutil.rmtree(os.path.join(glbs, top), ignore_errors=True)
    for depot in sorted(sets):
        for src, out in [(os.path.join(PORT, "depot", local(depot)), os.path.join(dst, local(depot)))] + (
                [(glb_path(depot), os.path.join(glbs, local(depot) + ".glb"))] if a.ship_glb else []):
            os.makedirs(os.path.dirname(out), exist_ok=True)
            shutil.copy2(src, out)
    for depot in bodies:
        os.makedirs(os.path.dirname(os.path.join(dst, depot)), exist_ok=True)
        shutil.copy2(os.path.join(PORT, "depot", local(depot)), os.path.join(dst, local(depot)))
    for f in ("scenes.json", "source-map.json"):
        shutil.copy2(os.path.join(PORT, f), os.path.join(a.pack, f))
    write_scene_list(a, name)
    with tempfile.TemporaryDirectory() as tmp:
        stage = os.path.join(tmp, name)
        shutil.copytree(os.path.join(dst, top), os.path.join(stage, top))
        wk(a, "pack", stage, "-o", tmp, "-v", "Minimal")
        os.makedirs(arc, exist_ok=True)
        shutil.copy2(os.path.join(tmp, name + ".archive"), os.path.join(arc, name + ".archive"))
    print("packed %d sets%s, %d big/fat rebaked -> %s" % (len(sets), " and their glbs" if a.ship_glb else "", len(bodies),
                                      os.path.join(arc, name + ".archive")))
    merge_clips_json(a.pack, name)


def write_scene_list(a, name):
    """the pack's scene-list.json, by the source's own reader: what scene_files.py reads (scene_list.py)"""
    import scene_list  # noqa: E402
    inventory = build_config.source(a.source or "opensex").get("inventory")
    reader = scene_list.readers().get(inventory)
    if reader is None:
        sys.exit("%s: no scene list reader for inventory %r" % (a.source or "opensex", inventory))
    scene_list.write(os.path.join(a.pack, "scene-list.json"), reader(a.pack, a.source_root), name)


def merge_clips_json(pack, name):
    """Each body the pack now carries a clip on, into the pack's clips.json: the graph plays only the bodies it names."""
    sys.path.insert(0, os.path.join(os.path.dirname(HERE), "opensex"))
    import scene_files  # noqa: E402
    path = os.path.join(pack, scene_files.SCENES_REL, name, "clips.json")
    if not os.path.isfile(path):
        print("no %s: the pack's scene files are not written yet (scene_files.py)" % path)
        return
    full, _ = scene_files.read_clips(os.path.dirname(os.path.normpath(pack)))
    for r in manifest():   # a clip the source map does not name (a "-fix" one) is read off the manifest
        ref = "%s/%s" % (name, r["clip"])
        if ref not in full or r["sex"] not in full[ref]:
            full.setdefault(ref, {})[r["sex"]] = {"npc": r["npcSet"], "player": r["playerSet"]}
    cur = json.load(open(path, encoding="utf-8"))
    added = 0
    for ref, bodies in cur.items():
        for sex, row in full.get(ref, {}).items():
            if sex not in bodies:
                bodies[sex] = row
                added += 1
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(cur, fh, indent=1, ensure_ascii=False)
        fh.write("\n")
    print("%s: %d bodies added to clips.json" % (name, added))


def low_priority():
    """Below normal, inherited by every worker and tool it starts: the machine stays usable."""
    if os.name != "nt":
        os.nice(10)
    else:
        import ctypes
        k = ctypes.windll.kernel32
        # the pseudo-handle is -1; ctypes' default int return truncates it to an invalid handle
        k.GetCurrentProcess.restype = ctypes.c_void_p
        k.SetPriorityClass.argtypes = (ctypes.c_void_p, ctypes.c_uint32)
        if not k.SetPriorityClass(k.GetCurrentProcess(), 0x4000):  # BELOW_NORMAL_PRIORITY_CLASS
            print("could not lower the priority (error %d)" % k.GetLastError())


def main():
    global PORT, SETS
    a = args_parser().parse_args()
    if a.source:
        s = build_config.source(a.source)
        a.port_dir, a.pack, a.ship_glb = s["run"], s["pack"], a.ship_glb or s.get("ship_glb", False)
        if a.source != "opensex":
            a.source_root = a.source_root or s["input"]
    if a.sets:
        SETS = {l.strip() for l in open(a.sets, encoding="utf-8") if l.strip()}
    opensex_port = os.path.normcase(os.path.abspath(PORT))
    PORT = os.path.abspath(a.port_dir)
    a.source_root = a.source_root or a.opensex
    low_priority()
    # inventory is OpenSex's: another port dir brings its own manifest, which it must not overwrite
    own = os.path.normcase(PORT) == opensex_port
    if a.stage == "inventory" and not own:
        sys.exit("inventory writes OpenSex's manifest; %s has its own (skyrim_scenes_*.py)" % PORT)
    # verify only on --verify: after a WolvenKit or retarget change, not on a bake (it has never failed a set)
    stages = ((["inventory"] if own else []) + ["clips", "glbs", "cook", "bodies"] + (["verify"] if a.verify else []) + ["pack"]
              if a.stage == "all" else [a.stage])
    checked = False
    for s in stages:
        if s != "inventory" and not checked:
            import scene_list  # noqa: E402
            bad = scene_list.check_manifest(manifest())
            if bad:
                sys.exit("%s/manifest.json: %d problems, first: %s" % (PORT, len(bad), "; ".join(bad[:5])))
            checked = True
        print("== %s" % s, flush=True)
        if globals()["stage_" + s](a) is False:
            sys.exit("%s failed" % s)


if __name__ == "__main__":
    main()
