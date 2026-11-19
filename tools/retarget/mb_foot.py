"""Feet on a generated clip: the model's foot contacts pin a planted foot, and a foot under its authored floor is lifted.

Two-bone IK on the Cyberpunk rig, after the clip is back from SOMA. The foot keeps its world rotation.
"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import retarget_glb as rg  # noqa: E402

CONTACT = 0.5
MAX_DRIFT = 0.30   # m: a foot that travels this far is not planted, whatever the model says
RAMP = 3           # frames a pin eases in and out over
COLUMNS = {"Left": (0, 1), "Right": (2, 3)}   # the model's heel and toe


def runs(flags):
    """[(first, last)] of each stretch of true."""
    out, start = [], None
    for i, on in enumerate(flags):
        if on and start is None:
            start = i
        if start is not None and (not on or i == len(flags) - 1):
            out.append((start, i if on else i - 1))
            start = None
    return out


def targets(cp, side, rot, tra, contacts, a, b):
    """(where the ankle goes, weight), one each per frame. The ends of a clip pin to its seams."""
    w_t = cp.world_pose(rot, tra)[1]
    n = rot.shape[1]
    pos = w_t[cp.index[side + "Foot"]]
    tgt, wgt = pos.copy(), np.zeros(n)
    for s, e in runs(contacts[:, COLUMNS[side]].max(axis=1) > CONTACT):
        if e - s < 3 or np.linalg.norm(pos[s:e + 1] - pos[s], axis=1).max() > MAX_DRIFT:
            continue
        if s == 0 and e == n - 1:
            u = np.linspace(0, 1, n)[:, None]
            tgt[:] = pos[0] * (1 - u) + pos[-1] * u
        else:
            tgt[s:e + 1] = pos[0] if s == 0 else pos[-1] if e == n - 1 else pos[(s + e) // 2]
        for i in range(s, e + 1):
            edge = min(i - s + 1 if s else RAMP, e - i + 1 if e < n - 1 else RAMP)
            wgt[i] = max(wgt[i], min(1.0, edge / RAMP))
    chain = [cp.index[side + x] for x in ("Foot", "Heel", "ToeBase") if side + x in cp.index]
    low = w_t[chain][..., 1].min(axis=0) + (tgt[:, 1] - pos[:, 1]) * wgt
    floor = min(cp.world_pose(a[0][:, -1:], a[1][:, -1:])[1][chain, 0, 1].min(),
                cp.world_pose(b[0][:, :1], b[1][:, :1])[1][chain, 0, 1].min())
    lift = np.maximum(floor - low, 0)
    if lift.max() <= 0:
        return tgt, wgt
    lift = np.array([lift[max(i - 4, 0):i + 5].max() for i in range(n)])
    lift = np.convolve(np.pad(lift, 2, mode="edge"), np.array([1.0, 2, 3, 2, 1]) / 9, "valid")
    lift[0] = lift[-1] = 0
    tgt = pos * (1 - wgt[:, None]) + tgt * wgt[:, None]
    tgt[:, 1] += lift
    return tgt, ((wgt > 0) | (lift > 0)).astype(np.float64)


def turn(axis, angle):
    n = np.linalg.norm(axis)
    if n < 1e-9:
        return np.array([0.0, 0, 0, 1])
    return np.array([*(axis / n * np.sin(angle / 2)), np.cos(angle / 2)])


def unit(v):
    return v / max(np.linalg.norm(v), 1e-9)


def acos(x):
    return np.arccos(np.clip(x, -1, 1))


def solve(cp, rot, tra, side, tgt, wgt):
    """Holden's two-joint IK (theorangeduck.com/page/simple-two-joint) on thigh and calf, per frame."""
    rot = rot.copy()
    w_r, w_t = cp.world_pose(rot, tra)
    u, k, f = cp.index[side + "UpLeg"], cp.index[side + "Leg"], cp.index[side + "Foot"]
    hip = cp.parent[u]
    for i in np.nonzero(wgt > 0)[0]:
        a, b, c = w_t[u, i], w_t[k, i], w_t[f, i]
        t = c + wgt[i] * (tgt[i] - c)
        if np.linalg.norm(t - c) < 1e-6:   # a seam frame: the solve would clamp a straight leg off its pose
            continue
        thigh, calf = np.linalg.norm(b - a), np.linalg.norm(c - b)
        d = np.clip(np.linalg.norm(t - a), abs(thigh - calf) + 1e-3, thigh + calf - 1e-3)
        was_a, was_b = acos(unit(c - a) @ unit(b - a)), acos(unit(a - b) @ unit(c - b))
        now_a = acos((calf * calf - thigh * thigh - d * d) / (-2 * thigh * d))
        now_b = acos((d * d - thigh * thigh - calf * calf) / (-2 * thigh * calf))
        axis = np.cross(c - a, b - a)
        if np.linalg.norm(axis) < 1e-6:   # a straight leg: bend it the way the thigh faces
            axis = np.cross(c - a, rg.qrot(w_r[u, i], np.array([0.0, 0, 1])))
        top = rg.qmul(turn(np.cross(c - a, t - a), acos(unit(c - a) @ unit(t - a))), turn(axis, now_a - was_a))
        new_u = rg.qnorm(rg.qmul(top, w_r[u, i]))
        new_k = rg.qnorm(rg.qmul(rg.qmul(top, turn(axis, now_b - was_b)), w_r[k, i]))
        rot[u, i] = rg.qnorm(rg.qmul(rg.qinv(w_r[hip, i]), new_u))
        rot[k, i] = rg.qnorm(rg.qmul(rg.qinv(new_u), new_k))
        rot[f, i] = rg.qnorm(rg.qmul(rg.qinv(new_k), w_r[f, i]))
    return rot


def planted(cp, rot, tra, contacts, a, b):
    """The clip's rotations with both feet fixed."""
    for side in COLUMNS:
        rot = solve(cp, rot, tra, side, *targets(cp, side, rot, tra, contacts, a, b))
    return rot
