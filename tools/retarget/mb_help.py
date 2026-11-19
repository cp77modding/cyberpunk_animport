"""The hard moves' help table, mb_help.json: what a move the plain model gets wrong needs. Read by mb_batch.py.

A rule is {"from", "to", "why"} (fnmatch patterns on the scene ids) plus one of:
  "cut": true                                  the move stays a hard cut
  "blend": true                                no model: every bone eases from A's last pose to B's first
  "via": {"actor", "set", "clip", "frame", "along", "tokens": [[first, second], ...]}
      that actor passes through a pose of an authored clip, `along` of the way from A to B
  "insert": {"actor", "set", "clip", "tokens": [[before, after], ...]}
      that actor plays the clip's low-to-high stretch for real, generated in and out; it ends where B starts
"actor" is a or b, and "set" is the depot path as moves.csv writes it, which `mb_batch.py sets` then exports.
docs/guides/retarget-an-animation.md §5.
"""
import fnmatch
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mb_soma as ms  # noqa: E402
import retarget_glb as rg  # noqa: E402

FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mb_help.json")
OTHER_TOKENS = 14
BLEND_FRAMES = 45
BLEND_HIPS = 0.20   # m a body's hips may move for a plain blend to read as limbs moving, not a body morphing


def load(path=FILE):
    with open(path, encoding="utf-8") as f:
        rules = json.load(f)
    for r in rules:
        kinds = [k for k in ("cut", "blend", "via", "insert") if k in r]
        if len(kinds) != 1 or not r.get("from") or not r.get("to") or not r.get("why"):
            raise ValueError("a help rule needs from, to, why and one of cut, blend, via, insert: %s" % r)
        spec = r[kinds[0]]
        if kinds[0] in ("cut", "blend") and spec is not True:
            raise ValueError("%s is true or absent: %s" % (kinds[0], r))
        if kinds[0] in ("via", "insert") and (spec.get("actor") not in ("a", "b") or not spec.get("clip") or not spec.get("tokens")
                                              or not str(spec.get("set")).endswith(".anims")):
            raise ValueError("a %s needs actor a or b, a clip, tokens and a set's depot path: %s" % (kinds[0], r))
    return rules


def rule_for(rules, a, b):
    """The first rule matching the move, or None."""
    return next((r for r in rules if fnmatch.fnmatchcase(a, r["from"]) and fnmatch.fnmatchcase(b, r["to"])), None)


def needs_set(rule):
    """The depot path of the set a rule reads, or None."""
    return (rule.get("via") or rule.get("insert") or {}).get("set")


def blend(x, frames):
    """(rot, tra) easing from the side's A end to its B start."""
    a_r, a_t, b_r, b_t = x["a"][0][:, -1:], x["a"][1][:, -1:], x["b"][0][:, :1], x["b"][1][:, :1]
    u = np.linspace(0, 1, frames)
    w = (u * u * (3 - 2 * u))[None, :, None]
    b_r = np.where(np.sum(a_r * b_r, axis=-1, keepdims=True) < 0, -b_r, b_r)
    return rg.qnorm(a_r * (1 - w) + b_r * w), a_t * (1 - w) + b_t * w


def limbs_only(sides):
    """Do both bodies' hips stay within BLEND_HIPS between A's end and B's start?"""
    for x in sides:
        i = x["cp"].index["Hips"]
        a = x["cp"].world_pose(x["a"][0][:, -1:], x["a"][1][:, -1:])[1][i, 0]
        b = x["cp"].world_pose(x["b"][0][:, :1], x["b"][1][:, :1])[1][i, 0]
        if np.linalg.norm(a - b) > BLEND_HIPS:
            return False
    return True


def yaw_of(soma, pose):
    """A SOMA pose's facing about Y, from the line between its thighs. Radians."""
    across = rg.qrot(pose[0, 3:].astype(np.float64), soma.ref_t[soma.index["LeftLeg"]] - soma.ref_t[soma.index["RightLeg"]])
    return float(np.arctan2(across[0], across[2]))


def moved(poses, yaw, ground, frame):
    """SOMA poses turned about Y, the frame's root put on ground (x, z)."""
    out = poses.astype(np.float64).copy()
    q = np.array([0.0, np.sin(yaw / 2), 0.0, np.cos(yaw / 2)])
    shift = np.asarray(ground) - rg.qrot(q, out[frame, 0, :3])[[0, 2]]
    out[:, 0, 3:] = rg.qnorm(rg.qmul(np.broadcast_to(q, out[:, 0, 3:].shape), out[:, 0, 3:]))
    out[:, 0, :3] = rg.qrot(q, out[:, 0, :3])
    out[:, 0, [0, 2]] += shift
    return out.astype(np.float32)


def stretch(poses, contacts, n):
    """A body that barely moves, played over n frames."""
    x = np.linspace(0, len(poses) - 1, n)
    i = np.minimum(x.astype(int), len(poses) - 2)
    w = (x - i)[:, None, None]
    a, b = poses[i, :, 3:].astype(np.float64), poses[i + 1, :, 3:].astype(np.float64)
    b = np.where(np.sum(a * b, axis=-1, keepdims=True) < 0, -b, b)
    out = np.concatenate([poses[i, :, :3] * (1 - w) + poses[i + 1, :, :3] * w, rg.qnorm(a * (1 - w) + b * w)], axis=-1)
    return out.astype(np.float32), contacts[np.rint(x).astype(int)]


def ends(x):
    """(context, target) of a side in SOMA, worked out once: every try of a move asks."""
    if "ends" not in x:
        (a_r, a_t), (b_r, b_t) = x["a"], x["b"]
        x["ends"] = (x["rig"].to_soma(a_r[:, -ms.CONTEXT:], a_t[:, -ms.CONTEXT:]),
                     x["rig"].to_soma(b_r[:, :ms.CONTEXT], b_t[:, :ms.CONTEXT]))
    return x["ends"]


def authored(sets, spec, x):
    """The rule's clip on this side's rig, Root at rest, in SOMA."""
    doc, buf, cp = sets.get(spec["set"])
    if cp.names != x["cp"].names:
        raise ValueError("%s is not actor %s's skeleton" % (spec["set"], spec["actor"]))
    rot, tra = ms.clip_in(doc, buf, cp, spec["clip"], ms.head_times)[1]
    i = cp.index["Root"]
    rot[i], tra[i] = cp.rest_r[i], cp.rest_t[i]
    return rot, tra


def chain(generate, ctx, mid, tgt, first, second):
    p1, c1 = generate(ctx, mid, (first,))
    p2, c2 = generate(p1[-ms.CONTEXT:], tgt, (second,))
    return np.concatenate([p1, p2[1:]]), np.concatenate([c1, c2[1:]])


def own_middle(generate, ctx, tgt):
    w, _ = generate(ctx, tgt, (OTHER_TOKENS,))
    f = len(w) // 2
    return w[f:f + ms.CONTEXT].copy()


def via(generate, soma, sides, spec, sets, judge):
    out = []
    for first, second in spec["tokens"]:
        made = []
        for x in sides:
            ctx, tgt = ends(x)
            if x["row"]["actor"] == spec["actor"]:
                rot, tra = authored(sets, spec, x)
                f = spec.get("frame", 0)
                pose = x["rig"].to_soma(rot[:, f:f + ms.CONTEXT], tra[:, f:f + ms.CONTEXT])
                along = spec.get("along", 0.35)
                mid = moved(pose, yaw_of(soma, ctx[-1]) - yaw_of(soma, pose[0]),
                            ctx[-1, 0, [0, 2]] * (1 - along) + tgt[0, 0, [0, 2]] * along, 0)
            else:
                mid = own_middle(generate, ctx, tgt)
            made.append(chain(generate, ctx, mid, tgt, first, second))
        out.append(dict(judge(sides, made), tokens=first + second, via="via"))
    return out


def insert(generate, soma, sides, spec, sets, judge):
    out = []
    x = next(s for s in sides if s["row"]["actor"] == spec["actor"])
    ctx, tgt = ends(x)
    rot, tra = authored(sets, spec, x)
    hips = x["cp"].world_pose(rot, tra)[1][x["cp"].index["Hips"], :, 1]
    low = int(hips.argmin())
    high = low + int(hips[low:].argmax())
    rise = x["rig"].to_soma(rot[:, low:high + 1], tra[:, low:high + 1])
    rise = moved(rise, yaw_of(soma, tgt[0]) - yaw_of(soma, rise[-1]), tgt[0, 0, [0, 2]], len(rise) - 1)
    for before, after in spec["tokens"]:
        p1, c1 = generate(ctx, rise[:ms.CONTEXT], (before,))
        p2, c2 = generate(rise[-ms.CONTEXT:], tgt, (after,))
        poses = np.concatenate([p1, rise[1:], p2[1:]])
        contacts = np.concatenate([c1, np.zeros((len(rise) - 1, c1.shape[1]), c1.dtype), c2[1:]])
        made = []
        for s in sides:
            if s is x:
                made.append((poses, contacts))
            else:
                c, t = ends(s)
                made.append(stretch(*generate(c, t, (OTHER_TOKENS,)), len(poses)))
        out.append(dict(judge(sides, made), tokens=before + after, via="insert"))
    return out


def helped(generate, soma, sides, rule, sets, judge):
    """Each try of a via or insert rule, as judge() returns them."""
    fn = via if "via" in rule else insert
    return fn(generate, soma, sides, rule.get("via") or rule["insert"], sets, judge)
