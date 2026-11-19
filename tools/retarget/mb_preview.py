"""A transition with its neighbours, for looking at. mb_transition.ps1 -Preview runs both steps.

  python mb_preview.py whole <run dir> <name>   the end of A, the transition, the start of B -> whole.glb
  python mb_preview.py gif <run dir> <name>     blender_transition.py's frames -> <name>.gif, a banner on each part
"""
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mb_soma as ms  # noqa: E402
import retarget_glb as rg  # noqa: E402

HOLD = 25


def whole(run, name):
    with open(os.path.join(run, name + ".json"), encoding="utf-8") as f:
        case = json.load(f)
    doc, buf, sk, anim, (ar, at) = ms.load_clip(case["a_glb"], case["a_clip"], ms.tail_times)
    _, _, _, _, (br, bt) = ms.load_clip(case["b_glb"], case["b_clip"], ms.head_times)
    d = np.load(os.path.join(run, name + ".npz"))
    rot = np.concatenate([ar[:, -HOLD:], d["rot"], br[:, :HOLD]], axis=1)
    tra = np.concatenate([at[:, -HOLD:], d["tra"], bt[:, :HOLD]], axis=1)
    times = np.arange(rot.shape[1], dtype=np.float64) / ms.FPS
    gd, gb = rg.build(doc, buf, sk, [("whole", anim.get("extras", {}), times, rot, tra)])
    rg.write_glb(os.path.join(run, "whole.glb"), gd, gb)
    parts = {"a": min(HOLD, ar.shape[1]), "gen": d["rot"].shape[1], "b": min(HOLD, br.shape[1]),
             "a_clip": case["a_clip"], "b_clip": case["b_clip"]}
    with open(os.path.join(run, "whole.json"), "w", encoding="utf-8") as f:
        json.dump(parts, f)
    print("whole.glb", rot.shape[1], "frames")


def gif(run, name):
    from PIL import Image, ImageDraw
    with open(os.path.join(run, "whole.json"), encoding="utf-8") as f:
        p = json.load(f)
    out = []
    for i in range(p["a"] + p["gen"] + p["b"]):
        a = Image.open(os.path.join(run, "frames", "side_%03d.png" % i)).convert("RGB")
        b = Image.open(os.path.join(run, "frames", "quarter_%03d.png" % i)).convert("RGB")
        w = Image.new("RGB", (a.width * 2, a.height + 26), (20, 20, 20))
        w.paste(a, (0, 26))
        w.paste(b, (a.width, 26))
        if i < p["a"]:
            text, col = p["a_clip"], (90, 160, 255)
        elif i < p["a"] + p["gen"]:
            text, col = "GENERATED %d/%d" % (i - p["a"] + 1, p["gen"]), (255, 90, 80)
        else:
            text, col = p["b_clip"], (90, 220, 120)
        ImageDraw.Draw(w).text((10, 7), text, fill=col)
        out.append(w.quantize(colors=128, method=Image.Quantize.MEDIANCUT))
    path = os.path.join(run, name + ".gif")
    out[0].save(path, save_all=True, append_images=out[1:], duration=33, loop=0)
    print(path, len(out), "frames")


if __name__ == "__main__":
    {"whole": whole, "gif": gif}[sys.argv[1]](sys.argv[2], sys.argv[3])
