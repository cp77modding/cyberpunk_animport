"""mb_soma on a synthetic pair of skeletons: no game data, no model.

The two rest poses face opposite ways and have different heights, as Cyberpunk's and SOMA's do.
Run: python tools/retarget/test_mb_soma.py (also from tools/py_test.ps1).
"""
import math
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mb_soma as ms  # noqa: E402
import retarget_glb as rg  # noqa: E402

fails = []


def quat(axis, deg):
    a = np.asarray(axis, dtype=np.float64)
    a /= np.linalg.norm(a)
    h = math.radians(deg) / 2
    return np.array([*(a * math.sin(h)), math.cos(h)])


def side(s, names):
    """(name, parent, world position) of one side; x is +left, SOMA's way."""
    x = 1 if s == "Left" else -1
    n = names
    return [(s + "Shoulder", n["chest"], [0.05 * x, 1.40, 0]), (s + "Arm", s + "Shoulder", [0.18 * x, 1.40, 0]),
            (s + "ForeArm", s + "Arm", [0.46 * x, 1.40, 0]), (s + "Hand", s + "ForeArm", [0.72 * x, 1.40, 0]),
            (s + "HandMiddle1", s + "Hand", [0.80 * x, 1.40, 0]),
            (n["thigh"] % s, "Hips", [0.10 * x, 0.90, 0]), (n["calf"] % s, n["thigh"] % s, [0.10 * x, 0.50, 0.01]),
            (s + "Foot", n["calf"] % s, [0.10 * x, 0.08, 0]), (s + "ToeBase", s + "Foot", [0.10 * x, 0.02, 0.14])]


def soma_rest():
    spine = [("Hips", None, [0, 0.95, 0]), ("Spine1", "Hips", [0, 1.05, 0]), ("Spine2", "Spine1", [0, 1.17, 0]),
             ("Chest", "Spine2", [0, 1.30, 0]), ("Neck1", "Chest", [0, 1.46, 0]), ("Neck2", "Neck1", [0, 1.52, 0]),
             ("Head", "Neck2", [0, 1.58, 0])]
    bones = spine + side("Left", {"chest": "Chest", "thigh": "%sLeg", "calf": "%sShin"}) \
        + side("Right", {"chest": "Chest", "thigh": "%sLeg", "calf": "%sShin"})
    names = [b[0] for b in bones]
    pos = {b[0]: np.array(b[2], np.float64) for b in bones}
    parent = [names.index(b[1]) if b[1] else -1 for b in bones]
    ref_t = [pos[b[0]] - (pos[b[1]] if b[1] else 0) for b in bones]
    ref_r = np.tile([0.0, 0, 0, 1], (len(bones), 1))
    return ms.Soma(names, parent, ref_t, ref_r)


def cyberpunk_skeleton():
    """Faces -Z with left at -X, a bit shorter, every bone with a rest twist of its own."""
    spine = [("Root", None, [0, 0, 0]), ("Hips", "Root", [0, 0.90, 0]), ("Spine", "Hips", [0, 1.00, 0]),
             ("Spine1", "Spine", [0, 1.12, 0]), ("Spine3", "Spine1", [0, 1.25, 0]), ("Neck", "Spine3", [0, 1.40, 0]),
             ("Neck1", "Neck", [0, 1.46, 0]), ("Head", "Neck1", [0, 1.52, 0])]
    bones = spine + side("Left", {"chest": "Spine3", "thigh": "%sUpLeg", "calf": "%sLeg"}) \
        + side("Right", {"chest": "Spine3", "thigh": "%sUpLeg", "calf": "%sLeg"})
    names = [b[0] for b in bones]
    nodes = [{"name": n} for n in names]
    world_r, world_t = {}, {}
    for i, (n, p, w) in enumerate(bones):
        wp = np.array([-w[0], w[1], -w[2]], np.float64) * 0.95
        r = quat([1, 2, 3], 7 * i)
        pr, pt = (world_r[p], world_t[p]) if p else (np.array([0.0, 0, 0, 1]), np.zeros(3))
        nodes[i]["rotation"] = [float(v) for v in rg.qmul(rg.qinv(pr), r)]
        nodes[i]["translation"] = [float(v) for v in rg.qrot(rg.qinv(pr), wp - pt)]
        world_r[n], world_t[n] = r, wp
        if p:
            nodes[names.index(p)].setdefault("children", []).append(i)
    return rg.Skeleton({"nodes": nodes, "skins": [{"joints": list(range(len(nodes)))}]})


def clip(cp, frames, seed):
    rng = np.random.default_rng(seed)
    rot = np.repeat(cp.rest_r[:, None, :], frames, axis=1)
    tra = np.repeat(cp.rest_t[:, None, :], frames, axis=1)
    for i in range(1, len(cp.names)):
        for f in range(frames):
            rot[i, f] = rg.qnorm(rg.qmul(rot[i, f], quat(rng.normal(size=3), rng.uniform(0, 50))))
    tra[cp.index["Hips"]] += rng.normal(scale=0.1, size=(frames, 3))
    return rot, tra


soma = soma_rest()
cp = cyberpunk_skeleton()
rig = ms.Rig(soma, cp)

# The rest pose lands on SOMA's: the half turn and the thigh/calf names are both in this.
rest = rig.to_soma(cp.rest_r[:, None, :], cp.rest_t[:, None, :])
out = ms.Soma(soma.names, soma.parent, soma.ref_t, rest[0, :, 3:].astype(np.float64))
worst = 0.0
for sn, (_, sa, _) in ms.MAP.items():
    if sa:
        s, a = soma.index[sn], soma.index[sa]
        got, want = out.wt[a] - out.wt[s], soma.wt[a] - soma.wt[s]
        cos = np.dot(got, want) / (np.linalg.norm(got) * np.linalg.norm(want))
        worst = max(worst, math.degrees(math.acos(min(1.0, cos))))
if worst > 1.0:
    fails.append("Cyberpunk's rest misses SOMA's by %.1f deg on a limb" % worst)
if abs(rest[0, soma.index["Hips"], 1] - soma.wt[soma.index["Hips"], 1]) > 1e-4:
    fails.append("hips are not scaled to SOMA's height")

# Our thigh drives SOMA's Leg, and leaves SOMA's Shin where it was.
rot = np.repeat(cp.rest_r[:, None, :], 1, axis=1)
tra = np.repeat(cp.rest_t[:, None, :], 1, axis=1)
rot[cp.index["LeftUpLeg"], 0] = rg.qmul(rot[cp.index["LeftUpLeg"], 0], quat([1, 0, 0], 60))
bent = rig.to_soma(rot, tra)
if ms.angle(bent[0, soma.index["LeftLeg"], 3:], rest[0, soma.index["LeftLeg"], 3:]) < 30:
    fails.append("the thigh does not reach SOMA's Leg")
if ms.angle(bent[0, soma.index["LeftShin"], 3:], rest[0, soma.index["LeftShin"], 3:]) > 0.1:
    fails.append("the thigh moved SOMA's Shin")

# There and back: every mapped bone and the hips come home, the unmapped blend A into B.
a_rot, a_tra = clip(cp, 4, 1)
b_rot, b_tra = clip(cp, 4, 2)
poses = rig.to_soma(np.concatenate([a_rot[:, -1:], b_rot[:, :1]], axis=1),
                    np.concatenate([a_tra[:, -1:], b_tra[:, :1]], axis=1))
rot, tra = rig.from_soma(poses, a_rot, a_tra, b_rot, b_tra)
want = cp.world_rot(np.concatenate([a_rot[:, -1:], b_rot[:, :1]], axis=1))
got_r, got_t = cp.world_pose(rot, tra)
err = max(ms.angle(want[cp.index[v[0]]], got_r[cp.index[v[0]]]).max() for v in ms.MAP.values())
if err > 0.05:
    fails.append("round trip off by %.3f deg" % err)
hips = cp.index["Hips"]
if np.linalg.norm(got_t[hips, 0] - cp.world_pose(a_rot, a_tra)[1][hips, -1]) > 1e-4:
    fails.append("round trip moved the hips")
finger = cp.index["LeftHandMiddle1"]
if ms.angle(rot[finger, 0], a_rot[finger, -1]) > 0.1 or ms.angle(rot[finger, -1], b_rot[finger, 0]) > 0.1:
    fails.append("an unmapped bone does not run from A's last to B's first")

# The limits pass the transition that joins and fail the ones that do not.
m = ms.measure(cp, rot, tra, (a_rot, a_tra), (a_rot, a_tra))
if m["seam_a_cm"] > 0.01:
    fails.append("a clean seam measured %.3f cm" % m["seam_a_cm"])
if not ms.failures(m):
    fails.append("the limits passed a clip that ends somewhere else entirely")
good = {"seam_a_cm": 0.0, "seam_b_cm": 0.0, "max_speed": 1.3}
if ms.failures(good):
    fails.append("the limits failed the first good run")
if not ms.failures(dict(good, seam_a_cm=2.0)) or not ms.failures(dict(good, seam_b_cm=2.0)) \
        or not ms.failures(dict(good, max_speed=22.0)):
    fails.append("a limit does not fail")

# 30 Hz from the clip's own end, whatever its length.
t = ms.tail_times(1.0)
if len(t) != 31 or t[-1] != 1.0 or abs(t[-1] - t[-2] - 1 / 30) > 1e-9:
    fails.append("tail_times does not end on the last frame at 30 Hz")
t = ms.head_times(1.05)
if t[0] != 0.0 or len(t) != 32:
    fails.append("head_times does not start on the first frame at 30 Hz")

for f in fails:
    print("FAIL", f)
print("test_mb_soma:", "FAILED" if fails else "ok")
sys.exit(1 if fails else 0)
