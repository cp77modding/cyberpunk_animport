"""The moves.csv mb_batch.ps1 generates: every move between two two-actor scenes in the packs, one row per actor.

A move already rewired through a generated transition is read as the move to that transition's `next`, so a rerun
lists the same graph as the first run. stage_end_spread_m is how far apart a scene's speeds end, per actor.

  python tools/retarget/mb_moves.py <out moves.csv>
"""
import csv
import glob
import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import skyrim_port as sp  # noqa: E402
import skyrim_retarget as sr  # noqa: E402

ANIMS = sp.build_config.load()["packs"]
PORTS = {"opensex": sp.PORT, "ostimng": os.path.join(sp.WORK, "skyrim", "ostimng")}
COLUMNS = ["from", "to", "actor", "sex", "from_set", "from_clip_s1", "to_set", "to_clip_first", "rig", "stages",
           "stage_end_spread_m", "to_actor"]


def load_scenes():
    out = {}
    for p in PORTS:
        for f in glob.glob(os.path.join(ANIMS, p, "bin", "**", "scenes", "**", "*.json"), recursive=True):
            if os.path.basename(f) != "clips.json":
                s = json.load(open(f, encoding="utf-8"))
                out[s["id"]] = s
    return out


def moves(scenes):
    """[(A, B)]: each two-actor move once, B behind a generated transition when A was rewired through one.
    A move to an authored transition (a pack's own XtoY or climax scene) is left out: rewire could not find it."""
    out, seen = [], set()
    for s in scenes.values():
        if s.get("transition") or len(s["actors"]) != 2:
            continue
        for m in s.get("moves") or []:
            t = scenes.get(m["to"])
            if t and t.get("transition") and ".gen." in t["id"]:  # ours: the move is to its next; an authored one stays
                t = scenes.get(t["next"])
            if not t or t.get("transition") or len(t["actors"]) != 2 or (s["id"], t["id"]) in seen:
                continue
            seen.add((s["id"], t["id"]))
            out.append((s, t))
    return out


def actor_map(s, t):
    """B's actor index for each of A's: the same, or swapped when the sexes sit the other way round ("any" fits both)."""
    same = all(x["sex"] == y["sex"] or "any" in (x["sex"], y["sex"]) for x, y in zip(s["actors"], t["actors"]))
    return [0, 1] if same else [1, 0]


class Poses:
    """A clip's first or last frame on our rig, from the ports' npz, with the set and rig it was baked on."""

    def __init__(self):
        self.rows, self.targets, self.cache, self.first = {}, {}, {}, {}
        for p, d in PORTS.items():
            for r in json.load(open(os.path.join(d, "manifest.json"), encoding="utf-8")):
                self.rows[(p, r["clip"], r["sex"])] = (d, r)
                self.first.setdefault((p, r["clip"]), r["sex"])  # the pack's own body: cast_roles.py appends the other

    def body(self, pack, clip, sex):
        """The body a side is generated on: its sex, or for an "any" side the one its pack gave the clip."""
        return sex if sex in ("m", "f") else self.first[(pack, clip)]

    def get(self, pack, clip, sex, frame):
        k = (pack, clip, sex, frame)
        if k not in self.cache:
            # a scene's sex can differ from the set its clip was baked in
            d, r = self.rows.get((pack, clip, sex)) or self.rows[(pack, clip, "f" if sex == "m" else "m")]
            f = os.path.join(d, "clips", r["npcSet"][:-len(".anims")], clip + ".npz")
            z = np.load(f if os.path.isfile(f) else os.path.join(d, "clips", r["rig"], clip + ".npz"))
            if r["rig"] not in self.targets:
                self.targets[r["rig"]] = sr.Target(sp.donor(r["rig"]))
            sl = slice(frame, frame + 1) if frame >= 0 else slice(-1, None)
            _, wt = self.targets[r["rig"]].skel.world_pose(z["rot"][:, sl].astype(float), z["tra"][:, sl].astype(float))
            self.cache[k] = (wt[:, 0], r["npcSet"], r["rig"])
        return self.cache[k]


def rows(pairs, poses):
    spread = {}
    for s, t in pairs:
        idx = actor_map(s, t)
        for i, a in enumerate(s["actors"]):
            j = idx[i]
            clips = [tuple(x["clips"][i].split("/", 1)) for x in s["speeds"]]
            sex = poses.body(*clips[0], a["sex"])
            if (s["id"], i) not in spread:
                e = [poses.get(p, c, sex, -1)[0] for p, c in clips]
                spread[(s["id"], i)] = max(float(np.linalg.norm(x - e[0], axis=1).max()) for x in e)
            fp, fc = clips[0]
            tp, tc = t["speeds"][0]["clips"][j].split("/", 1)
            _, fset, rig = poses.get(fp, fc, sex, -1)
            _, tset, _ = poses.get(tp, tc, sex, 0)
            yield [s["id"], t["id"], "abcdefgh"[i], sex, fset, fc, tset, tc, rig, len(clips),
                   round(spread[(s["id"], i)], 3), "abcdefgh"[j]]


def main():
    out = sys.argv[1]
    pairs = moves(load_scenes())
    with open(out, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(COLUMNS)
        n = sum(1 for r in rows(pairs, Poses()) if w.writerow(r) or True)
    print("%d moves, %d rows -> %s" % (len(pairs), n, out))


if __name__ == "__main__":
    main()
