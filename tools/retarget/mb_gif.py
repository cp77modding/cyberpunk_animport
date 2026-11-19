"""The batch's moves as GIFs to look at offline: the end of A, the generated transition, the start of B, both actors.

Stick figures, side and front, the Root track dropped as the game lines a pair up; the banner gives the gap between the
bodies per frame (mb_gap's capsules, negative is overlap). index.html lists every move, worst overlap first, with
what pack_transitions does with it.

  python tools/retarget/mb_gif.py [--results F] [--moves F] [--out DIR] [--only FROM TO] [--workers 4]
"""
import argparse
import csv
import html
import json
import multiprocessing
import os
import sys

import numpy as np
from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import mb_gap as mg  # noqa: E402
import mb_soma as ms  # noqa: E402
import pack_transitions as pt  # noqa: E402
import retarget_glb as rg  # noqa: E402
import skyrim_port as sp  # noqa: E402

RUN = os.path.join(HERE, "work", "run")
HOLD = 20          # frames of A before and of B after
STEP = 2           # every second frame: 15 fps
PANEL, BANNER = 340, 34
SKIP = ("Armature", "Root", "Trajectory", "reference_joint", "Weapon", "Eye", "InHand")
COLOURS = {"a": (90, 160, 255), "b": (255, 110, 110)}
VIEWS = ((2, -1.0), (0, 1.0))  # side: -z right; front: x right


def stem(path):
    return os.path.basename(path.replace("\\", "/"))


_glbs = {}


def glb(path):
    if path not in _glbs:
        doc, buf = rg.read_glb(path)
        if len(_glbs) > 8:  # a worker holds a few sets, not the batch
            _glbs.clear()
        _glbs[path] = doc, buf, rg.Skeleton(doc)
    return _glbs[path]


def clip(path, name, times):
    """(skeleton, rot, tra) at 30 Hz, Root at rest."""
    doc, buf, sk = glb(path)
    rot, tra = ms.clip_in(doc, buf, sk, name, times)[1]
    i = sk.index["Root"]
    rot[i], tra[i] = sk.rest_r[i], sk.rest_t[i]
    return sk, rot, tra


def actor_track(side, mv):
    """One actor's A tail, transition and B head joined: (skeleton, world positions joints x frames x 3, parts)."""
    sets = os.path.join(RUN, "mb_sets")
    sk, ar, at = clip(os.path.join(sets, stem(mv["from_set"]) + ".glb"), mv["from_clip_s1"], ms.tail_times)
    _, gr, gt = clip(os.path.join(RUN, "mb_batch", os.path.splitext(stem(side["npc"]))[0] + ".glb"), side["clip"],
                     ms.head_times)
    _, br, bt = clip(os.path.join(sets, stem(mv["to_set"]) + ".glb"), mv["to_clip_first"], ms.head_times)
    rot = np.concatenate([ar[:, -HOLD:], gr, br[:, :HOLD]], axis=1)
    tra = np.concatenate([at[:, -HOLD:], gt, bt[:, :HOLD]], axis=1)
    return sk, rot, tra, (min(HOLD, ar.shape[1]), gr.shape[1])


def frame_gaps(cx, cy):
    """Per frame, the smallest surface distance between two capsules() sets, metres."""
    (p1, q1, r1), (p2, q2, r2) = cx, cy
    d = mg.seg_dist(p1[:, None], q1[:, None], p2[None], q2[None]) - (r1[:, None] + r2[None])[:, :, None]
    return d.min(axis=(0, 1))


def overlap_past(r):
    """How far the transition overlaps past the closer authored pose, m (negative is worse)."""
    return r["gap"] - min(r["gap_a"], r["gap_b"])


def verdict(r, drop, limit):
    if r.get("rejected"):
        return "rejected: " + r.get("reason", "")
    if overlap_past(r) < -limit:
        return "cut: overlaps %.0f cm past the authored poses" % (-overlap_past(r) * 100)
    if (r["from"], r["to"]) in drop:
        return "cut: on the drop list"
    if not all(s.get("player") for s in r["sides"]):
        return "cut: no V clip"
    return "packed"


def draw(bodies, f, centre, top, text, colour):
    """top: the highest bone over the move, m; the panel is cropped to it."""
    scale = PANEL / 2.6
    high = min(PANEL, int((top + 0.15) * scale) + 20)
    img = Image.new("RGB", (PANEL * 2, high + BANNER), (24, 24, 28))
    d = ImageDraw.Draw(img)
    for v, (axis, sign) in enumerate(VIEWS):
        ox = v * PANEL

        def px(p):
            return (ox + PANEL / 2 + sign * (p[axis] - centre[axis]) * scale, BANNER + high - 20 - p[1] * scale)

        d.line([px((centre[0] - 1.3, 0, centre[2] - 1.3)), px((centre[0] + 1.3, 0, centre[2] + 1.3))],
               fill=(80, 80, 80))
        for actor, sk, w in bodies:
            for i in sk.joints:
                p = sk.parent[i]
                if p < 0 or any(s in sk.names[i] for s in SKIP) or any(s in sk.names[p] for s in SKIP):
                    continue
                if "Hand" in sk.names[i] and sk.names[i][-1].isdigit():
                    continue
                d.line([px(w[i, f]), px(w[p, f])], fill=COLOURS[actor], width=2)
            h = px(w[sk.index["Head"], f])
            d.ellipse([h[0] - 5, h[1] - 5, h[0] + 5, h[1] + 5], outline=COLOURS[actor], width=2)
        d.text((ox + 6, BANNER + 4), ("side", "front")[v], fill=(150, 150, 150))
    d.text((8, 4), text[0], fill=colour)
    d.text((8, 18), text[1], fill=(200, 200, 200))
    return img


def render(job):
    """One move -> <out>/<key>.gif; returns (key, error or None)."""
    r, mvs, out = job
    k = pt.key(r["from"], r["to"])
    try:
        tracks = {s["actor"]: actor_track(s, mvs[s["actor"]]) for s in r["sides"]}
        n = min(t[1].shape[1] for t in tracks.values())
        bodies, caps = [], []
        for actor in sorted(tracks):
            sk, rot, tra, parts = tracks[actor]
            bodies.append((actor, sk, sk.world_pose(rot[:, :n], tra[:, :n])[1]))
            caps.append(mg.capsules(sk, rot[:, :n], tra[:, :n]))
        gaps = frame_gaps(*caps) * 100
        a_n, g_n = parts
        hips = np.concatenate([w[sk.index["Hips"]] for _, sk, w in bodies])
        centre = hips.mean(axis=0)
        top = max(float(w[:, :, 1].max()) for _, _, w in bodies)
        frames = []
        for f in range(0, n, STEP):
            if f < a_n:
                head, col = "A  " + r["from"].split(".")[-1], (90, 160, 255)
            elif f < a_n + g_n:
                head, col = "GENERATED %d/%d" % (f - a_n + 1, g_n), (255, 200, 80)
            else:
                head, col = "B  " + r["to"].split(".")[-1], (110, 220, 130)
            line = "gap %+.1f cm   (authored A end %+.1f, B start %+.1f)" % (gaps[f], r["gap_a"] * 100, r["gap_b"] * 100)
            frames.append(draw(bodies, f, centre, top, (head, line), col).quantize(colors=64))
        frames[0].save(os.path.join(out, k + ".gif"), save_all=True, append_images=frames[1:],
                       duration=1000 * STEP // 30, loop=0)
        return k, None
    except Exception as e:  # one move that cannot be drawn is listed, the rest go on
        return k, "%s: %s" % (type(e).__name__, e)


def index(rows, drop, limit, errors, out):
    order = sorted(rows, key=lambda r: (bool(r.get("rejected")), overlap_past(r) if not r.get("rejected") else 0))
    cells = []
    for r in order:
        k = pt.key(r["from"], r["to"])
        img = ("<img loading=lazy src='%s.gif'>" % k) if not r.get("rejected") and k not in errors else \
            html.escape(errors.get(k, ""))
        gap = "" if r.get("rejected") else "gap %+.1f cm (A %+.1f / B %+.1f)" % (
            r["gap"] * 100, r["gap_a"] * 100, r["gap_b"] * 100)
        cells.append("<tr><td>%s</td><td><b>%s</b><br>&rarr; %s<br>%s<br><i>%s</i></td></tr>" % (
            img, html.escape(r["from"]), html.escape(r["to"]), gap, html.escape(verdict(r, drop, limit))))
    with open(os.path.join(out, "index.html"), "w", encoding="utf-8") as fh:
        fh.write("<meta charset=utf-8><title>Generated transitions</title><style>body{background:#18181c;color:#ddd;"
                 "font:13px sans-serif}td{vertical-align:top;padding:4px}</style><p>%d moves, worst overlap first. "
                 "Blue actor a, red actor b.</p><table>%s</table>\n" % (len(rows), "\n".join(cells)))


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--results", default=pt.RESULTS)
    ap.add_argument("--moves", default=os.path.join(RUN, "moves.csv"))
    ap.add_argument("--out", default=os.path.join(RUN, "gifs"))
    ap.add_argument("--only", nargs=2, action="append", metavar=("FROM", "TO"))
    ap.add_argument("--drop")
    ap.add_argument("--max-overlap", type=float, default=0.20)
    ap.add_argument("--workers", type=int, default=4)
    a = ap.parse_args()
    sp.low_priority()
    rows = [json.loads(x) for x in open(a.results, encoding="utf-8") if x.strip()]
    if a.only:
        rows = [r for r in rows if [r["from"], r["to"]] in a.only]
    drop = frozenset(tuple(x.split()[:2]) for x in open(a.drop, encoding="utf-8") if x.strip()) if a.drop else frozenset()
    mv = {}
    with open(a.moves, encoding="utf-8", newline="") as f:
        for m in csv.DictReader(f):
            mv.setdefault((m["from"], m["to"]), {})[m["actor"]] = m
    os.makedirs(a.out, exist_ok=True)
    jobs = sorted(((r, mv[(r["from"], r["to"])], a.out) for r in rows if not r.get("rejected")),
                  key=lambda j: j[1]["a"]["from_set"])  # one A set per worker run: its glb is read once
    errors = {}
    with multiprocessing.Pool(a.workers) as pool:
        for n, (k, err) in enumerate(pool.imap(render, jobs, chunksize=4), 1):
            if err:
                errors[k] = err
                print("  %s: %s" % (k, err))
            if n % 25 == 0:
                print("  %d/%d" % (n, len(jobs)), flush=True)
    index(rows, drop, a.max_overlap, errors, a.out)
    print("%d gifs, %d failed -> %s" % (len(jobs) - len(errors), len(errors), os.path.join(a.out, "index.html")))


if __name__ == "__main__":
    main()
