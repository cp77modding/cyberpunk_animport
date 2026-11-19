"""The packs' generated transitions (gen_*, pack_transitions.py's) onto the big and fat rigs, for each whose big/fat
set is missing or older than its npc set: the npc sets exported in one WolvenKit call, retargeted (retarget_glb.py)
and cooked by skyrim_port.py's parallel cook, then copied into the pack's depot. retarget.ps1 -Rig, one process per
set, did the same in make_release.ps1.
  python tools/retarget/gen_bodies.py [--packs opensex,ostimng] [--workers 4]"""
import argparse
import multiprocessing
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import skyrim_port as sp  # noqa: E402

ANIMS = r"C:\Work\WorkSpace\Cyberpunk\CyberpunkAnimations"


def stale(pack):
    """[(npc .anims path, body rig, body depot path)] for the pack's gen_ npc sets"""
    root = os.path.join(ANIMS, pack, "depot")
    npc = os.path.join(root, pack, "anims", "npc")
    out = []
    for f in sorted(os.listdir(npc)):
        if not f.startswith("gen_") or not f.endswith(("_ma.anims", "_wa.anims")):
            continue
        src = os.path.join(npc, f)
        for rig in sp.BODIES["man_base" if f.endswith("_ma.anims") else "woman_base"]:
            depot = "%s\\anims\\%s\\%s_%s.anims" % (pack, rig, f[:-len(".anims")], rig)
            dst = os.path.join(root, sp.local(depot))
            if not os.path.isfile(dst) or os.path.getmtime(dst) < os.path.getmtime(src):
                out.append((src, rig, depot))
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--packs", default="opensex,ostimng")
    ap.add_argument("--workers", type=int, default=4)
    o = ap.parse_args()
    a = sp.args_parser().parse_args(["bodies", "--workers", str(o.workers)])
    sp.low_priority()
    for pack in o.packs.split(","):
        jobs = stale(pack)
        print("== %s: %d big/fat transition sets" % (pack, len(jobs)), flush=True)
        if not jobs:
            continue
        sp.PORT = os.path.join(sp.WORK, "gen_bodies", pack)
        src_dir = os.path.join(sp.PORT, "src")
        shutil.rmtree(src_dir, ignore_errors=True)
        os.makedirs(src_dir)
        for src in {s for s, _, _ in jobs}:
            shutil.copy2(src, src_dir)
        sp.wk(a, "export", src_dir, "-o", src_dir, "-gp", a.game, "-v", "Minimal")
        work = []
        for src, rig, depot in jobs:
            glb = os.path.join(src_dir, os.path.basename(src) + ".glb")
            if not os.path.isfile(glb):
                sys.exit("export wrote no %s" % glb)
            os.makedirs(os.path.dirname(sp.glb_path(depot)), exist_ok=True)
            work.append((glb, sp.glb_path(depot), rig))
        with multiprocessing.Pool(o.workers) as pool:
            list(pool.imap_unordered(sp._body_glb, work))
        sp.cook_sets(a, {depot: (rig, None) for _, rig, depot in jobs})
        for _, _, depot in jobs:
            dst = os.path.join(ANIMS, pack, "depot", sp.local(depot))
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copy2(os.path.join(sp.PORT, "depot", sp.local(depot)), dst)
        print("%s: %d sets into the pack's depot" % (pack, len(jobs)), flush=True)


if __name__ == "__main__":
    main()
