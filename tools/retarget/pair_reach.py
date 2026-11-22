"""A pair's oral reach kept as the Skyrim source had it: the giver slid along the floor, per clip.

The retarget places each pelvis where Skyrim had it and copies rotations, so a Cyberpunk body with a shorter torso
stops short of its partner (woman_base: head to pelvis 0.62 m against Skyrim's 0.73). For every oral act in the
pack's scenes this measures the giver's head to the target's pelvis -- Skyrim, then ours -- and writes the flat
slide that makes ours match into <port>/pair_shift.json; skyrim_port.py's glbs stage applies it to the giver's Hips.

  python tools/retarget/pair_reach.py [--pack opensex|ostimng] [--dry]
"""
import argparse
import glob
import json
import multiprocessing
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import pair_cast  # noqa: E402
import retarget_glb as rg  # noqa: E402
import skyrim_port as sp  # noqa: E402
import skyrim_retarget as sr  # noqa: E402

_cfg = sp.build_config.load()
ANIMS = _cfg["packs"]
SCENES_REL = r"bin\x64\plugins\cyber_engine_tweaks\mods\nightcitynet\data\scenes"
# pack name -> (run folder, source input), every build.json source
PORTS = {os.path.basename(s["pack"]): (s["run"], s["input"]) for s in _cfg["sources"].values()}
CFG = {"hkxc": _cfg["tools"]["hkxc"], "blender_hkx": _cfg["tools"]["blender_hkx"]}
PELV, HEAD = "NPC Pelvis [Pelv]", "NPC Head [Head]"
MIN_FIX = 0.02    # m: closer than this to the source is left alone
MAX_FIX = 0.15    # m: a bigger slide is a scene problem (wrong act roles), reported, not applied
MAX_REACH = 0.60  # m: a source head this far from its target is not oral contact
UP = np.array([0.0, 1.0, 0.0])  # glTF


def slide(ours, src):
    """(shift, after): the flat move of the giver's head that best gives |target - head| the source's length.
    ours, src: (frames, 3) target-minus-head vectors in metres."""
    mean = ours.mean(axis=0)
    flat = mean - UP * (mean @ UP)
    if np.linalg.norm(flat) < 1e-6:
        return np.zeros(3), float(np.linalg.norm(ours, axis=1).mean())
    u = flat / np.linalg.norm(flat)
    want = np.linalg.norm(src, axis=1)
    hs = np.arange(-MAX_FIX - 0.05, MAX_FIX + 0.05, 0.0025)
    err = [np.mean((np.linalg.norm(ours - h * u, axis=1) - want) ** 2) for h in hs]
    h = float(hs[int(np.argmin(err))])
    return h * u, float(np.linalg.norm(ours - h * u, axis=1).mean())


def why_not(reach_o, reach_s, shift):
    """Why a slide is not applied, or None."""
    gap, move = abs(reach_o - reach_s), float(np.linalg.norm(shift))
    if reach_s > MAX_REACH:
        return "source reach %.2f m is not contact (act roles?)" % reach_s
    if gap < MIN_FIX:
        return "within %.0f cm" % (MIN_FIX * 100)
    if move > MAX_FIX:
        return "slide %.2f m over the cap" % move
    if move > 3 * gap + 0.02:  # the gap is mostly up and down: a flat slide cannot close it
        return "slide %.2f m for a %.2f m gap (the gap is vertical)" % (move, gap)
    return None


def oral_pairs(pack):
    """[(scene id, act, giver (pack, clip, sex), target (pack, clip, sex))] for every speed of every oral act in pack's scenes.
    The sex picks the set: one clip name is in both the man's and the woman's set.
    A scene whose two actors both give (a 69) is left out: sliding one giver moves the other's reach."""
    out = []
    if pack in pair_cast.NAMED:
        files = sorted(glob.glob(os.path.join(ANIMS, pack, SCENES_REL, "**", "*.json"), recursive=True))
        scenes = [json.load(open(f, encoding="utf-8")) for f in files if os.path.basename(f) != "clips.json"]
    else:   # its scene files are written after the bake: the scene list they are made from
        scenes = json.load(open(os.path.join(ANIMS, pack, "scene-list.json"), encoding="utf-8"))
    for s in scenes:
        oral = [act for act in s.get("acts") or [] if act["type"].startswith("oral")]
        if len({act["actor"] for act in oral}) > 1:
            print("  %s: both actors give, left as ported" % s["id"])
            continue
        # an "any" side (cast_roles.py) plays on either body: each body it is baked for is measured
        bodies = [("m", "f") if x["sex"] == "any" else (x["sex"],) for x in s["actors"]]
        for act in oral:
            a, t = "abcdefgh".index(act["actor"]), "abcdefgh".index(act["target"])
            for speed in s["speeds"]:
                if not (speed["clips"][a] and speed["clips"][t]):
                    continue
                for ga in bodies[a]:
                    for tb in bodies[t]:
                        g = tuple(speed["clips"][a].split("/", 1)) + (ga,)
                        out.append((s["id"], act["type"], g, tuple(speed["clips"][t].split("/", 1)) + (tb,)))
    return out


def key(row):
    """pair_shift.json's key for a manifest row: the clip in one sex's set."""
    return "%s|%s" % (row["sex"], row["clip"])


class Decoded:
    """A source clip decoded once (kept under <port>/reach/), as Skyrim world tracks and as our retarget."""

    def __init__(self):
        self.rows = {p: {(r["clip"], r["sex"]): r for r in json.load(open(os.path.join(d, "manifest.json"), encoding="utf-8"))}
                     for p, (d, _) in PORTS.items()}
        self.targets, self.cache = {}, {}

    def target(self, rig):
        if rig not in self.targets:
            self.targets[rig] = sr.Target(sp.donor(rig))
        return self.targets[rig]

    def get(self, pack, clip, sex):
        if (pack, clip, sex) in self.cache:
            return self.cache[(pack, clip, sex)]
        row = self.rows[pack][(clip, sex)]
        port, root = PORTS[pack]
        # by the actor's sex: both bodies share the decode on the actor's skeleton
        tmp = os.path.join(port, "reach", row.get("srcSex", sex), clip)
        xml = os.path.join(tmp, "decoded.xml")
        if not os.path.isfile(xml):
            os.makedirs(tmp, exist_ok=True)
            xml = sp.decode(os.path.join(root, row["file"]), sp.skeleton_of(row), tmp, CFG)
        s_idx, s_parent, s_ot, s_or, s_rot, s_tra, _ = sr.read_clip(xml)
        _, s_wt = sr.to_gltf(*sr.world(s_parent, s_rot, s_tra))
        _, s_rt = sr.to_gltf(s_or, s_ot)
        tg = self.target(row["rig"])
        rot, tra = sr.retarget(xml, tg)
        _, o_wt = tg.skel.world_pose(rot, tra)
        scale = tg.w_t[tg.skel.index["Hips"], 1] / s_rt[s_idx[PELV], 1]
        d = {"rig": row["rig"], "scale": scale,
             "s_head": s_wt[s_idx[HEAD]], "s_pelvis": s_wt[s_idx[PELV]],
             "o_head": o_wt[tg.skel.index["Head"]], "o_pelvis": o_wt[tg.skel.index["Hips"]]}
        self.cache[(pack, clip, sex)] = d
        return d


_dec = None


def _fetch(key):
    global _dec
    _dec = _dec or Decoded()
    return key, _dec.get(*key)


def prefetch(dec, packs, workers):
    """Every clip the plan reads, decoded on `workers` processes (a clip costs ~15 s, nearly all of it in Python)."""
    keys = sorted({k for pack in packs for _, _, g, t in oral_pairs(pack) for k in (g, t)})
    keys = [k for k in keys if k not in dec.cache]
    with multiprocessing.Pool(workers) as pool:
        for n, (key, d) in enumerate(pool.imap_unordered(_fetch, keys), 1):
            dec.cache[key] = d
            if n % 25 == 0:
                print("  %d/%d decoded" % (n, len(keys)), flush=True)


def measure(dec, giver, target):
    """Target minus head per frame, ours and the source's (metres at the pair's mean retarget scale)."""
    g, t = dec.get(*giver), dec.get(*target)
    n = min(len(g["o_head"]), len(t["o_pelvis"]), len(g["s_head"]), len(t["s_pelvis"]))
    unit = (g["scale"] + t["scale"]) / 2
    return t["o_pelvis"][:n] - g["o_head"][:n], (t["s_pelvis"][:n] - g["s_head"][:n]) * unit


def merge(shifts, refused, k, entry, why):
    """Files one scene's verdict on giver clip k; returns why it is not slid, or None.
    A clip refused once, or slid two ways, stays refused whatever a later scene says."""
    old = shifts.get(k)
    if not why and old and np.linalg.norm(np.array(old["shift"]) - np.array(entry["shift"])) > 0.01:
        why = "clip also in %s with a different slide" % old["scene"]
    if why:
        shifts.pop(k, None)
        refused.add(k)
    elif k in refused:
        why = "refused by another scene"
    else:
        shifts[k] = entry
    return why


def plan(pack, dec):
    """{key: entry} for the giver clips pack owns, and the report lines."""
    shifts, refused, lines = {}, set(), []
    for sid, act, giver, target in oral_pairs(pack) + [p for other in PORTS if other != pack
                                                       for p in oral_pairs(other) if p[2][0] == pack]:
        if giver[0] != pack:
            continue
        ours, src = measure(dec, giver, target)
        reach_o, reach_s = float(np.linalg.norm(ours, axis=1).mean()), float(np.linalg.norm(src, axis=1).mean())
        shift, after = slide(ours, src)
        why = why_not(reach_o, reach_s, shift)
        entry = {"shift": [round(float(x), 4) for x in shift], "scene": sid, "act": act,
                 "skyrim": round(reach_s, 3), "before": round(reach_o, 3), "after": round(after, 3)}
        why = merge(shifts, refused, key({"clip": giver[1], "sex": giver[2]}), entry, why)
        lines.append("%-48s %-11s skyrim %.2f ours %.2f -> %.2f  %s" % (
            "%s %s" % (giver[2], giver[1]), act, reach_s, reach_o, after if not why else reach_o, why or "slide %+.2f m" % (
                np.linalg.norm(shift) * np.sign(reach_o - reach_s))))
    return shifts, lines


def apply_shift(skel, rot, tra, shift):
    """Moves the clip's Hips by a model-space shift, in place: the whole body slides, the root stays."""
    i = skel.index["Hips"]
    p = skel.parent[i]
    if p < 0:
        tra[i] += shift
        return
    w_r, _ = skel.world_pose(rot, tra)
    tra[i] += rg.qrot(rg.qinv(w_r[p]), np.broadcast_to(shift, tra[i].shape))


def load(port):
    path = os.path.join(port, "pair_shift.json")
    return json.load(open(path, encoding="utf-8")) if os.path.isfile(path) else {}


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--pack", choices=sorted(PORTS), action="append")
    ap.add_argument("--dry", action="store_true", help="report only, write nothing")
    ap.add_argument("--workers", type=int, default=4)
    a = ap.parse_args()
    sp.low_priority()
    dec = Decoded()
    prefetch(dec, a.pack or sorted(PORTS), a.workers)
    for pack in a.pack or sorted(PORTS):
        shifts, lines = plan(pack, dec)
        print("== %s: %d giver clips slid" % (pack, len(shifts)))
        print("\n".join(lines))
        if not a.dry:
            out = os.path.join(PORTS[pack][0], "pair_shift.json")
            with open(out, "w", encoding="utf-8", newline="\n") as fh:
                json.dump(dict(sorted(shifts.items())), fh, indent=1)
                fh.write("\n")
            print("-> %s" % out)


if __name__ == "__main__":
    main()
