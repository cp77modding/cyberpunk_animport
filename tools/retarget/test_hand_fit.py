"""hand_fit's two-bone reach on a three-bone stick arm: no game data, no decode.

Run: python tools/retarget/test_hand_fit.py (also from tools/py_test.ps1).
"""
import os
import sys
from types import SimpleNamespace

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hand_fit as hf  # noqa: E402
import retarget_glb as rg  # noqa: E402

fails = []

# Shoulder at the origin, upper arm and forearm 0.3 each, the elbow bent 140 deg toward -y.
F = 24
doc = {"nodes": [{"name": "Root", "children": [1]}, {"name": "LeftArm", "children": [2]},
                 {"name": "LeftForeArm", "children": [3]}, {"name": "LeftHand"}], "skins": [{"joints": [1, 2, 3]}]}
sk = rg.Skeleton(doc)
bend = np.radians(20)
rot = np.tile([0.0, 0, 0, 1], (4, F, 1))
rot[1] = [0, 0, -np.sin(bend / 2), np.cos(bend / 2)]
rot[2] = [0, 0, np.sin(bend), np.cos(bend)]
tra = np.zeros((4, F, 3))
tra[2, :, 0] = tra[3, :, 0] = 0.3
act = SimpleNamespace(rot=rot, tra=tra, tg=SimpleNamespace(skel=sk), idx={n: i for i, n in enumerate(sk.names)})
fr = np.arange(F)
side = hf.elbow_side(act, "Left", fr)
ident = np.tile([0.0, 0, 0, 1], (F, 1))

# A reach past the arm's length pulls it straight; then a lift back in, out of the arm's plane, a different way
# each frame. The straight arm has no bend of its own: the elbow must bend back to the side it had.
hf.apply_frames(act, "Left", fr, np.ones(F), ident, np.tile([0.2, 0, 0], (F, 1)), side)
_, t = sk.world_pose(act.rot, act.tra)
straight = np.degrees(np.arccos(np.clip((hf.unit(t[1] - t[2]) * hf.unit(t[3] - t[2])).sum(1), -1, 1)))
if straight.min() < 175:
    fails.append("the reach left the elbow at %.0f deg, want it straight" % straight.min())
# as a solved clip leaves it: the straight arm rolled about its own line by a different amount each frame
a = np.linspace(0, 2 * np.pi, F, endpoint=False)
w_r, _ = sk.world_pose(act.rot, act.tra)
roll = np.concatenate([hf.unit(t[3] - t[1]) * np.sin(a / 2)[:, None], np.cos(a / 2)[:, None]], 1)
hf.set_world(act, 1, rg.qmul(roll, w_r[1]), fr)
_, t = sk.world_pose(act.rot, act.tra)
lift = np.stack([np.full(F, -0.08), 0.03 * np.cos(a), 0.03 * np.sin(a)], 1)
goal = t[3] + lift
hf.apply_frames(act, "Left", fr, np.ones(F), ident, lift, side)
_, t = sk.world_pose(act.rot, act.tra)
wrong = ((hf.elbow_side(act, "Left", fr) * side).sum(1) <= 0).sum()
if wrong:
    fails.append("the elbow bent to the other side on %d of %d frames" % (wrong, F))
if np.abs(t[3] - goal).max() > 1e-6:
    fails.append("the wrist missed its goal by %.2g m" % np.abs(t[3] - goal).max())
for k in (2, 3):
    if np.abs(np.linalg.norm(t[k] - t[k - 1], axis=1) - 0.3).max() > 1e-9:
        fails.append("bone %s changed length" % sk.names[k])

# Skyrim's palm hovering 1.7-2.4 cm (doggystyle lowered torso S3) stays on; lifted past 4 cm it is off until back in 2
d = np.array([0.03, 0.019, 0.024, 0.017, 0.024, 0.05, 0.03, 0.019])
want = [False, True, True, True, True, False, False, True]
if list(hf.held_on(d)) != want:
    fails.append("held_on %s, want %s" % (list(hf.held_on(d)), want))

# Skyrim's palm spot goes to the same place within the same area on our body, shaped otherwise: a buttock twice as wide
g = np.stack(np.meshgrid(np.linspace(-1, 1, 5), np.linspace(-1, 1, 5), [0.0]), -1).reshape(-1, 3)
sky_v = np.vstack([g * [0.1, 0.1, 1], g * [0.1, 0.1, 1] + [0, 1, 0]])
sky_a = np.array(["butt_l"] * 25 + ["back"] * 25, dtype=object)
our_v = np.vstack([g * [0.2, 0.1, 1] + [6.5, 0, 0], g * [0.2, 0.1, 1] + [5, 0, 0]])   # the whole body: lands on back
our_a = np.array(["back"] * 25 + ["butt_l"] * 25, dtype=object)
cells = [(r * 5 + c, r * 5 + c + 1, r * 5 + c + 6) for r in range(4) for c in range(4)] + \
        [(r * 5 + c, r * 5 + c + 6, r * 5 + c + 5) for r in range(4) for c in range(4)]
our_t = np.array(cells + [tuple(np.array(t) + 25) for t in cells])
# a point between grid points stays between them (Skyrim's x +0.07, y -0.03 -> ours 2x as wide: 5.14, -0.03)
t, bc = hf.spot_map(sky_v, sky_a, our_v, our_a, our_t, np.array([[0.07, -0.03, 0]]), np.array(["butt_l"], object))
p = bc[0] @ our_v[our_t[t[0]]]
if our_a[our_t[t[0]][0]] != "butt_l" or not np.allclose(p, [5.14, -0.03, 0], atol=1e-6):
    fails.append("spot_map: Skyrim's buttock point went to %s %s, want butt_l [5.14, -0.03, 0]" % (our_a[our_t[t[0]][0]], p))
# an area of one point on our body still maps (a k=1 query returns a scalar)
one_a = np.array(["back"] * 49 + ["butt_l"], dtype=object)
t, bc = hf.spot_map(sky_v, sky_a, our_v, one_a, our_t, np.array([[0.07, -0.03, 0]]), np.array(["butt_l"], object))
if 49 not in our_t[t[0]]:
    fails.append("spot_map: a one-point area mapped to triangle %s, not one of its point's" % our_t[t[0]])
# a palm as near her forearm as her buttock keeps its buttock spot; one a whole SWITCH nearer to the forearm moves
area = np.array(["butt_l", "forearm_l", "butt_l"], dtype=object)
u = hf.SWITCH / hf.sc.UNIT
if hf.same_area(np.array([10.0, 10.0 + 0.01 * u]), np.array([1, 0]), area, "butt_l") != 0:
    fails.append("same_area: a palm 0.01 SWITCH nearer her forearm left her buttock")
if hf.same_area(np.array([10.0, 10.0 + 1.5 * u]), np.array([1, 0]), area, "butt_l") != 1:
    fails.append("same_area: a palm 1.5 SWITCH nearer her forearm stayed on her buttock")

# the nearest point of a triangle: inside it, and off an edge
tri = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0]], float)
for p, want in (([0.2, 0.3, 5.0], [0.2, 0.3, 0]), ([2.0, -1.0, 1.0], [1, 0, 0]), ([0.5, -2.0, 0], [0.5, 0, 0])):
    got = hf.closest_on_tri(np.array(p), *tri) @ tri
    if not np.allclose(got, want):
        fails.append("closest_on_tri %s: %s, want %s" % (p, got, want))

# the many-frame nearest search finds what a KD tree per frame finds, to the bit: a body 2 m off the origin
rng = np.random.default_rng(1)
pts, q = rng.normal(2.0, 0.3, (7, 500, 3)), rng.normal(2.0, 0.3, (4, 9, 3))
rows = np.array([6, 0, 3, 3])
want = [hf.cKDTree(pts[r]).query(q[i]) for i, r in enumerate(rows)]
wd, wj = np.array([w[0] for w in want]), np.array([w[1] for w in want]) + rows[:, None] * 500
for name, (d, j) in (("FramePoints", hf.FramePoints(pts).nearest(rows, q)), ("FrameTree", hf.FrameTree(pts).query(rows, q))):
    if not (np.array_equal(d, wd) and np.array_equal(j, wj)):
        fails.append("%s: %d of %d nearest points differ from a KD tree's" % (name, (j != wj).sum(), j.size))
want = [hf.cKDTree(pts[r]).query(q[i], k=5) for i, r in enumerate(rows)]
wd, wj = np.array([w[0] for w in want]), np.array([w[1] for w in want]) + rows[:, None, None] * 500
d, j = hf.FramePoints(pts).knn(rows, q, 5)
if not (np.array_equal(d, wd) and np.array_equal(j, wj)):
    fails.append("FramePoints.knn: %d of %d of the 5 nearest differ from a KD tree's" % ((j != wj).sum(), j.size))
# Skyrim units: a body 150 units off the origin, where a margin in metres would be under float32's error
far = pts * 70 + 150
d, j = hf.FramePoints(far).nearest(rows, q * 70 + 150)
if not np.array_equal(j, np.array([hf.cKDTree(far[r]).query(q[i] * 70 + 150)[1] for i, r in enumerate(rows)]) + rows[:, None] * 500):
    fails.append("FramePoints.nearest: points 150 units off the origin differ from a KD tree's")
# skinned on many frames: blend as a frame at a time does it
w, vh = rng.random((6, 4)), np.c_[rng.normal(size=(6, 3)), np.ones(6)]
s = rng.normal(size=(3, 4, 4, 4))
one = np.stack([np.einsum("vij,vj->vi", (w @ s[f].reshape(4, 16)).reshape(-1, 4, 4)[:, :3], vh) for f in range(3)])
if not np.allclose(hf.blend(w, s, vh), one, rtol=0, atol=1e-12):
    fails.append("blend: not the frame-at-a-time skin")

print("FAIL\n  " + "\n  ".join(fails) if fails else "ok: hand_fit")
sys.exit(1 if fails else 0)
