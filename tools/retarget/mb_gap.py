"""How far apart two bodies are: capsules on a clip's bones, surface to surface. Negative is overlap, in metres.

The radii are estimates of a body, not the game's ragdoll, so compare a transition with authored poses, never with 0.
"""
import numpy as np

SEGS = [("Hips", "Spine1", 0.14), ("Spine1", "Spine3", 0.14), ("Spine3", "Neck", 0.13), ("Neck", "Head", 0.05),
        ("Head", "Head", 0.10)]
for S in ("Left", "Right"):
    SEGS += [(S + "Arm", S + "ForeArm", 0.05), (S + "ForeArm", S + "Hand", 0.04), (S + "Hand", S + "HandMiddle1", 0.04),
             (S + "UpLeg", S + "Leg", 0.08), (S + "Leg", S + "Foot", 0.055), (S + "Foot", S + "ToeBase", 0.04)]


def capsules(cp, rot, tra):
    """(ends p, ends q, radii): segs x frames x 3. The Root track is dropped, as the game lines a pair up without it."""
    r, t = rot.copy(), tra.copy()
    root = cp.index["Root"]
    r[root], t[root] = cp.rest_r[root], cp.rest_t[root]
    w = cp.world_pose(r, t)[1]
    p = np.stack([w[cp.index[a]] for a, _, _ in SEGS])
    q = np.stack([w[cp.index[b]] for _, b, _ in SEGS])
    return p, q, np.array([x[2] for x in SEGS])


def seg_dist(p1, q1, p2, q2):
    """Closest distance between segments, broadcast over the leading axes (Ericson, Real-Time Collision Detection)."""
    d1, d2, r = q1 - p1, q2 - p2, p1 - p2
    a = np.sum(d1 * d1, axis=-1)
    e = np.sum(d2 * d2, axis=-1)
    f = np.sum(d2 * r, axis=-1)
    c = np.sum(d1 * r, axis=-1)
    b = np.sum(d1 * d2, axis=-1)
    safe_a, safe_e = np.maximum(a, 1e-12), np.maximum(e, 1e-12)
    den = np.maximum(a * e - b * b, 1e-12)
    s = np.where(a * e - b * b > 1e-12, np.clip((b * f - c * e) / den, 0, 1), 0.0)
    t = (b * s + f) / safe_e
    s = np.where(t < 0, np.clip(-c / safe_a, 0, 1), np.where(t > 1, np.clip((b - c) / safe_a, 0, 1), s))
    t = np.clip(t, 0, 1)
    s = np.where(e <= 1e-12, np.clip(-c / safe_a, 0, 1), s)
    s = np.where(a <= 1e-12, 0.0, s)
    t = np.where(e <= 1e-12, 0.0, t)
    return np.linalg.norm(p1 + d1 * s[..., None] - (p2 + d2 * t[..., None]), axis=-1)


def gap(a, b):
    """The smallest surface distance of two capsules() over their frames: (metres, frame, bone of a, bone of b)."""
    (p1, q1, r1), (p2, q2, r2) = a, b
    d = seg_dist(p1[:, None], q1[:, None], p2[None], q2[None]) - (r1[:, None] + r2[None])[:, :, None]
    i, j, f = np.unravel_index(int(d.argmin()), d.shape)
    return float(d[i, j, f]), int(f), SEGS[i][0], SEGS[j][0]
