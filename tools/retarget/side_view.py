"""A pair clip as the game plays it, from both sides: V's body on V's baked set beside the partner's body on the npc
set, skinned and shaded. A hollow back or a body through the other shows here before a game test; the in-game hollow
back of 2026-11-23 was baked sets nobody had looked at.
  python side_view.py <pack> <clip base> <cast> [--v 0] [--frames 0,60,120] [--out view.png]
  e.g. python side_view.py opensex sx-standingrearsexholdingarms_s2 m,f   (actor 0 a man, played by V)
"""
import argparse
import json
import os

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.collections import PolyCollection  # noqa: E402

import body_area_map as bm  # noqa: E402
import pair_reach  # noqa: E402
import retarget_glb as rg  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
GLB = os.path.join(HERE, "work", "body", "glb")
# V's bodies are the player meshes (t0_000_pma from the game's archive, exported with WolvenKit)
BODY = {(False, "m"): "t0_000_ma_base__full.glb", (False, "f"): "t0_000_wa_base__full.glb",
        (True, "m"): "t0_000_pma_base__full.glb", (True, "f"): "t0_000_pwa_base__full.glb"}
HEAD = {"m": "h0_000_ma_c__basehead.glb", "f": "h0_000_wa__basehead.glb"}   # V wears the npc head here: same bones
COLOURS = [(0.45, 0.6, 0.95), (0.95, 0.6, 0.6), (0.6, 0.85, 0.55)]
LIGHT = np.array([-0.6, 0.5, 0.6]) / np.linalg.norm([-0.6, 0.5, 0.6])
_DOCS, _BODIES = {}, {}


def mat(r, t):
    """(n, 4, 4) from quaternions xyzw (n, 4) and positions (n, 3)"""
    x, y, z, w = r[:, 0], r[:, 1], r[:, 2], r[:, 3]
    M = np.zeros((len(r), 4, 4))
    M[:, 0] = np.c_[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w), t[:, 0]]
    M[:, 1] = np.c_[2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w), t[:, 1]]
    M[:, 2] = np.c_[2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y), t[:, 2]]
    M[:, 3, 3] = 1
    return M


def glb(path):
    if path not in _DOCS:
        doc, buf = rg.read_glb(path)
        _DOCS[path] = (doc, buf, rg.Skeleton(doc))
    return _DOCS[path]


def body(path):
    if path not in _BODIES:
        if not os.path.isfile(path):
            raise SystemExit("no body mesh %s (export it from the game's archive with WolvenKit)" % path)
        _BODIES[path] = bm.OurBody(path)
    return _BODIES[path]


def posed(set_glb, clip, body_glb, frames):
    """the body's vertices on each frame of the clip, (len(frames), v, 3), and its triangles"""
    doc, buf, sk = glb(set_glb)
    an = [a for a in doc["animations"] if a.get("name") == clip]
    if not an:
        raise SystemExit("%s has no clip %s" % (set_glb, clip))
    t = rg.clip_times(doc, buf, an[0])
    frames = [min(f, len(t) - 1) for f in frames]
    w_r, w_t = sk.world_pose(*rg.sample_clip(doc, buf, an[0], sk, t[frames]))
    r_r, r_t = sk.world_pose(sk.rest_r[:, None], sk.rest_t[:, None])
    b = body(body_glb)
    # the body glb is flat: a helper bone follows its nearest main bone, as pair_contact's driver() has it
    rig_parent = {n: sk.names[sk.parent[k]] for n, k in sk.index.items() if sk.parent[k] >= 0}
    main = b.main_of(rig_parent, {n: r_t[sk.index[n], 0] for n in sk.names})
    car = [n if n in sk.index and n not in ("Armature", "Root") else main.get(n) for n in b.bones]
    rest_inv = {c: np.linalg.inv(mat(r_r[sk.index[c], 0][None], r_t[sk.index[c], 0][None])[0]) for c in set(car) if c}
    vh = np.c_[b.verts, np.ones(len(b.verts))]
    out = []
    for k in range(len(frames)):
        # pose times the rig's rest inverse: the body's bind sits on the rest
        J = np.stack([mat(w_r[sk.index[c], k][None], w_t[sk.index[c], k][None])[0] @ rest_inv[c] if c else np.eye(4)
                      for c in car])
        out.append(np.einsum("vab,vb->va", np.einsum("vj,jab->vab", b.weights, J), vh)[:, :3])
    return np.stack(out), b.tris


def draw(ax, actors, k, flip):
    """one frame from one side: painter's order along the view axis, Lambert shade"""
    s = -1.0 if flip else 1.0
    depth, xy, col = [], [], []
    for (v, tris), c in zip(actors, COLOURS):
        p = v[k][tris]
        n = np.cross(p[:, 1] - p[:, 0], p[:, 2] - p[:, 0])
        n /= np.linalg.norm(n, axis=1, keepdims=True) + 1e-12
        depth.append(s * p[:, :, 0].mean(1))
        xy.append(np.stack([s * p[:, :, 2], p[:, :, 1]], -1))
        col.append((np.clip(np.abs(n @ LIGHT), 0, 1) * 0.75 + 0.25)[:, None] * np.array(c))
    depth, xy, col = np.concatenate(depth), np.concatenate(xy), np.concatenate(col)
    o = np.argsort(depth)
    ax.add_collection(PolyCollection(xy[o], facecolors=col[o], edgecolors="none"))
    lo, hi = xy.reshape(-1, 2).min(0) - 0.05, xy.reshape(-1, 2).max(0) + 0.05
    ax.set_xlim(lo[0], hi[0]); ax.set_ylim(lo[1], hi[1])
    ax.set_aspect("equal"); ax.set_xticks([]); ax.set_yticks([])


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("pack", help="opensex | ostimng | ...")
    ap.add_argument("base", help="the clip without its _<actor> suffix")
    ap.add_argument("cast", help="each actor's sex in order, e.g. m,f")
    ap.add_argument("--v", type=int, default=0, help="the actor V plays (-1: none, all npc sets)")
    ap.add_argument("--frames", default="0,60,120")
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    port, _ = pair_reach.PORTS[a.pack]
    rows = json.load(open(os.path.join(port, "manifest.json"), encoding="utf-8"))
    frames = [int(x) for x in a.frames.split(",")]
    actors, names = [], []
    for k, sex in enumerate(a.cast.split(",")):
        clip, is_v = "%s_%d" % (a.base, k), k == a.v
        row = next((r for r in rows if r["clip"] == clip and r["sex"] == sex), None)
        if row is None:
            raise SystemExit("no manifest row for %s on a %s body" % (clip, sex))
        depot = row["playerSet" if is_v else "npcSet"]
        set_glb = os.path.join(port, "glb", depot.replace("\\", os.sep) + ".glb")
        parts = [posed(set_glb, clip, os.path.join(GLB, f), frames) for f in (BODY[(is_v, sex)], HEAD[sex])]
        offs = np.cumsum([0] + [p[0].shape[1] for p in parts])
        actors.append((np.concatenate([p[0] for p in parts], 1),
                       np.concatenate([p[1] + o for p, o in zip(parts, offs)])))
        names.append("%s%s" % ("V" if is_v else "npc", sex))
    fig, axes = plt.subplots(len(frames), 2, figsize=(14, 9 * len(frames)))
    axes = np.atleast_2d(axes)
    for k, f in enumerate(frames):
        for c, flip in enumerate((False, True)):
            draw(axes[k, c], actors, k, flip)
            axes[k, c].set_title("%s  frame %d  %s side  (%s)" % (a.base, f, "right" if flip else "left",
                                                                 " + ".join(names)), fontsize=12)
    fig.tight_layout()
    out = a.out or os.path.join(port, "side_view", "%s.png" % a.base)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    fig.savefig(out, dpi=55)
    print("wrote", out)


if __name__ == "__main__":
    main()
