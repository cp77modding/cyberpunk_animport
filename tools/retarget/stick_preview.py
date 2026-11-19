"""Stick figures of animset glbs at a few frames, side and front views -- a look at a retarget without Blender.

Each glb is one colour (blue, red, green, ...): every bone drawn to its parent, a dot on the head. The frames
are spread evenly over the first glb's clip. A glb with many clips (a port set) takes --clip; without it, its
first clip is drawn.

Run: python tools/retarget/stick_preview.py <out.png> <a.glb>[:<clip>] [<b.glb>[:<clip>] ...] [--frames 4]
     e.g. work\\skyrim\\port\\glb\\opensex\\anims\\npc\\lybkne_ma.anims.glb:cr-mountedgrind_s2_0
"""
import argparse
import os
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import retarget_glb as rg  # noqa: E402

COLOURS = ["tab:blue", "tab:red", "tab:green", "tab:orange", "tab:purple"]
VIEWS = ((2, "side: forward(-z) / up"), (0, "front: x / up"))


def split(arg):
    # a Windows drive colon is not a clip separator
    head, sep, clip = arg.rpartition(":")
    return (head, clip) if sep and len(head) > 1 and not clip.startswith("\\") else (arg, None)


def pose(path, clip):
    doc, buf = rg.read_glb(path)
    sk = rg.Skeleton(doc)
    anims = {a["name"]: a for a in doc["animations"]}
    if clip is None:
        anim = doc["animations"][0]
    elif clip in anims:
        anim = anims[clip]
    else:
        sys.exit("%s has no clip %s (it has %d: %s ...)" % (path, clip, len(anims), ", ".join(sorted(anims)[:8])))
    t = rg.clip_times(doc, buf, anim)
    rot, tra = rg.sample_clip(doc, buf, anim, sk, t)
    return sk, sk.world_pose(rot, tra)[1], anim["name"]


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("out")
    ap.add_argument("glbs", nargs="+")
    ap.add_argument("--frames", type=int, default=4)
    a = ap.parse_args()
    poses = [pose(*split(g)) for g in a.glbs]
    frames = np.linspace(0, poses[0][1].shape[1] - 1, a.frames).astype(int)
    fig, axes = plt.subplots(2, len(frames), figsize=(4 * len(frames), 8), squeeze=False)
    for c, f in enumerate(frames):
        for row, (h, label) in enumerate(VIEWS):
            ax = axes[row, c]
            for k, (sk, w, _) in enumerate(poses):
                f_k = min(f, w.shape[1] - 1)
                col = COLOURS[k % len(COLOURS)]
                for i in sk.joints:
                    p = sk.parent[i]
                    if p >= 0 and p in sk.joints:
                        a_, b_ = w[i, f_k], w[p, f_k]
                        x = (-a_[h], -b_[h]) if h == 2 else (a_[h], b_[h])
                        ax.plot(x, (a_[1], b_[1]), color=col, lw=1.2)
                if "Head" in sk.index:
                    hd = w[sk.index["Head"], f_k]
                    ax.plot(-hd[2] if h == 2 else hd[0], hd[1], "o", color=col)
            ax.set_aspect("equal")
            ax.set_xlim(-1.4, 1.4)
            ax.set_ylim(-0.1, 1.8)
            ax.grid(alpha=.3)
            ax.set_title("frame %d  %s" % (f, label), fontsize=8)
    fig.suptitle("   ".join("%s: %s" % (COLOURS[k % len(COLOURS)][4:], name) for k, (_, _, name) in enumerate(poses)),
                 fontsize=9)
    fig.tight_layout()
    fig.savefig(a.out, dpi=80)
    print(a.out)


if __name__ == "__main__":
    main()
