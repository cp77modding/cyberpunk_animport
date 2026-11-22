"""A scene's Skyrim clips beside our port of them, as one GIF: every actor a stick figure, side and front, left the
source as decoded, right the cooked set's glb on our rig. Reads only what a port run already wrote (the decode
cache and the glbs); nothing is decoded or baked here.

  python tools/retarget/compare_gif.py <out.gif> <clip base> [--source opensex] [--step 2]
  e.g. compare_gif.py docs\\kiss.gif ap-actionfemalekiss    (its actors' clips are ap-actionfemalekiss_0, _1)
"""
import argparse
import os
import sys

import numpy as np
from PIL import Image, ImageDraw

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build_config  # noqa: E402
import retarget_glb as rg  # noqa: E402
import skyrim_port as sp  # noqa: E402
import skyrim_retarget as sr  # noqa: E402

UNIT = 0.0142875   # metres in a Skyrim unit
PANEL, BANNER = 300, 26
COLOURS = [(90, 160, 255), (255, 110, 110), (110, 220, 130), (255, 200, 80)]
VIEWS = ((2, -1.0), (0, 1.0))   # side: -z right; front: x right
OUR_SKIP = ("Armature", "Root", "Trajectory", "reference_joint", "Weapon", "Eye", "InHand", "Twist", "Roll")


def rows_of(base):
    """one manifest row per actor: the body that actor was cast as"""
    out = {}
    for r in sp.manifest():
        if r["clip"].rsplit("_", 1)[0] == base and r["sex"] == r.get("srcSex", r["sex"]):
            out.setdefault(r["clip"], r)
    if not out:
        sys.exit("no clip %s_<n> in %s's manifest" % (base, sp.PORT))
    return [out[k] for k in sorted(out)]


def source(r):
    """Skyrim's world joints (joints, frames, 3) in glTF axes, metres, and the bones to draw"""
    path = sp.decoded_path(r)
    if not os.path.isfile(path):
        sys.exit("%s is not decoded yet: run the port's clips stage first" % r["clip"])
    with np.load(path) as z:
        names, parent = [str(n) for n in z["names"]], [int(p) for p in z["parent"]]
        rot, tra = z["rot"].astype(np.float64), z["tra"].astype(np.float64)
    w = rg.qrot(sr.C, sr.world(parent, rot, tra)[1]) * UNIT
    bones = [(i, p) for i, p in enumerate(parent) if p >= 0 and names[i].startswith("NPC ") and names[p].startswith("NPC ")
             and "Finger" not in names[i] and "Root" not in names[p]]
    return w, bones, names.index("NPC Head [Head]")


def ported(r):
    """our clip's world joints (joints, frames, 3), the Root at rest as the game lines a pair up, and the bones"""
    path = sp.glb_path(r["npcSet"])
    if not os.path.isfile(path):
        sys.exit("%s is not built yet: run the port's glbs stage first" % path)
    doc, buf = rg.read_glb(path)
    sk = rg.Skeleton(doc)
    anim = next((a for a in doc["animations"] if a["name"] == r["clip"]), None)
    if anim is None:
        sys.exit("%s has no clip %s" % (path, r["clip"]))
    rot, tra = rg.sample_clip(doc, buf, anim, sk, rg.clip_times(doc, buf, anim))
    i = sk.index["Root"]
    rot[i], tra[i] = sk.rest_r[i], sk.rest_t[i]
    w = sk.world_pose(rot, tra)[1]
    skip = lambda n: any(s in n for s in OUR_SKIP) or ("Hand" in n and n[-1].isdigit())   # noqa: E731
    bones = [(j, sk.parent[j]) for j in sk.joints if sk.parent[j] >= 0 and not skip(sk.names[j])
             and not skip(sk.names[sk.parent[j]])]
    return w, bones, sk.index["Head"]


def panel(d, ox, actors, f, centre, scale, floor):
    for v, (axis, sign) in enumerate(VIEWS):
        x0 = ox + v * PANEL

        def px(p):
            return (x0 + PANEL / 2 + sign * (p[axis] - centre[axis]) * scale, floor - p[1] * scale)

        d.line([(x0 + 20, floor), (x0 + PANEL - 20, floor)], fill=(70, 70, 70))
        for k, (w, bones, head) in enumerate(actors):
            g = min(f, w.shape[1] - 1)
            for i, p in bones:
                d.line([px(w[i, g]), px(w[p, g])], fill=COLOURS[k % len(COLOURS)], width=2)
            h = px(w[head, g])
            d.ellipse([h[0] - 5, h[1] - 5, h[0] + 5, h[1] + 5], outline=COLOURS[k % len(COLOURS)], width=2)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("out")
    ap.add_argument("base")
    ap.add_argument("--source", default="opensex")
    ap.add_argument("--step", type=int, default=2)
    a = ap.parse_args()
    sp.PORT = build_config.source(a.source)["run"]
    rows = rows_of(a.base)
    sky, ours = [source(r) for r in rows], [ported(r) for r in rows]
    n = max(w.shape[1] for w, _, _ in sky + ours)
    top = max(float(w[:, :, 1].max()) for w, _, _ in sky + ours)
    scale = (PANEL - 40) / max(top + 0.2, 1.0)
    high = int((top + 0.2) * scale) + 20
    frames = []
    for f in range(0, n, a.step):
        img = Image.new("RGB", (PANEL * 4, high + BANNER), (24, 24, 28))
        d = ImageDraw.Draw(img)
        for side, (actors, label) in enumerate(((sky, "Skyrim"), (ours, "Cyberpunk port"))):
            centre = np.concatenate([w[:, min(f, w.shape[1] - 1)] for w, _, _ in actors]).mean(axis=0)
            panel(d, side * 2 * PANEL, actors, f, centre, scale, BANNER + high - 10)
            d.text((side * 2 * PANEL + 8, 6), "%s   side, front" % label, fill=(210, 210, 210))
        d.line([(2 * PANEL, 0), (2 * PANEL, high + BANNER)], fill=(90, 90, 90))
        d.text((PANEL * 4 - 150, 6), "%s  %d/%d" % (a.base[:14], f + 1, n), fill=(150, 150, 150))
        frames.append(img.quantize(colors=64))
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    frames[0].save(a.out, save_all=True, append_images=frames[1:], duration=1000 * a.step // 30, loop=0)
    print("%s: %d frames, %d actors" % (a.out, len(frames), len(rows)))


if __name__ == "__main__":
    main()
