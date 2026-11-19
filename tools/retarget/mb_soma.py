"""The Cyberpunk rig <-> MotionBricks' SOMA rig, and what a generated transition must pass. No model, no warp.

The method is skyrim_retarget.py's: one constant offset per bone, world to world. docs/design/generated-motion.md §7.
"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import retarget_glb as rg  # noqa: E402

FPS = 30.0
CONTEXT = 4
MAX_SEAM_CM = 1.0
MAX_SPEED = 6.0   # m/s; the half-turn bug read 22, the first good run 1.3
MAX_SINK_CM = 8.0   # below the lower of A and B; the first good run sank 6.3
YAW180 = np.array([0.0, 1.0, 0.0, 0.0])
FEET = ("LeftFoot", "RightFoot", "LeftToeBase", "RightToeBase", "LeftHeel", "RightHeel")

# soma bone: (cyberpunk bone, soma aim child, cyberpunk aim child)
MAP = {
    "Hips": ("Hips", None, None),
    "Spine1": ("Spine", "Spine2", "Spine1"),
    "Spine2": ("Spine1", "Chest", "Spine3"),
    "Chest": ("Spine3", "Neck1", "Neck"),
    "Neck1": ("Neck", "Neck2", "Neck1"),
    "Neck2": ("Neck1", "Head", "Head"),
    "Head": ("Head", None, None),
}
for S in ("Left", "Right"):
    MAP.update({
        S + "Shoulder": (S + "Shoulder", S + "Arm", S + "Arm"),
        S + "Arm": (S + "Arm", S + "ForeArm", S + "ForeArm"),
        S + "ForeArm": (S + "ForeArm", S + "Hand", S + "Hand"),
        S + "Hand": (S + "Hand", S + "HandMiddle1", S + "HandMiddle1"),
        S + "Leg": (S + "UpLeg", S + "Shin", S + "Leg"),   # SOMA's Leg is the thigh, Cyberpunk's is the calf
        S + "Shin": (S + "Leg", S + "Foot", S + "Foot"),
        S + "Foot": (S + "Foot", S + "ToeBase", S + "ToeBase"),
        S + "ToeBase": (S + "ToeBase", None, None),
    })


def swing(a, b):
    a, b = a / np.linalg.norm(a), b / np.linalg.norm(b)
    c, d = np.cross(a, b), float(np.dot(a, b))
    if d < -0.9999:
        return np.array([1.0, 0, 0, 0])
    return rg.qnorm(np.array([c[0], c[1], c[2], 1 + d]))


def angle(a, b):
    d = np.abs(np.sum(a * b, axis=-1)).clip(0, 1)
    return np.degrees(2 * np.arccos(d))


class Soma:
    """SOMA's rest: joint names, parents and local transforms, with the world pose worked out."""

    def __init__(self, names, parent, ref_t, ref_r):
        self.names = list(names)
        self.index = {n: i for i, n in enumerate(self.names)}
        self.parent = [int(p) for p in parent]
        self.ref_t, self.ref_r = np.asarray(ref_t, np.float64), np.asarray(ref_r, np.float64)
        self.wr = np.empty_like(self.ref_r)
        self.wt = np.empty_like(self.ref_t)
        for i, p in enumerate(self.parent):
            if p < 0:
                self.wr[i], self.wt[i] = self.ref_r[i], self.ref_t[i]
            else:
                self.wr[i] = rg.qmul(self.wr[p], self.ref_r[i])
                self.wt[i] = self.wt[p] + rg.qrot(self.wr[p], self.ref_t[i])


class Rig:
    """The per-bone offsets between the Cyberpunk armature and SOMA: soma_world = cp_world * O."""

    def __init__(self, soma, cp):
        self.soma, self.cp = soma, cp
        wr, wt = self.canon(*cp.world_pose(cp.rest_r[:, None, :], cp.rest_t[:, None, :]))
        self.cwr, self.cwt = wr[:, 0], wt[:, 0]
        self.off = {}
        for sn, (cn, sa, ca) in MAP.items():
            s, c = soma.index[sn], cp.index[cn]
            r = self.cwr[c]
            if sa:
                r = rg.qnorm(rg.qmul(swing(self.cwt[cp.index[ca]] - self.cwt[c], soma.wt[soma.index[sa]] - soma.wt[s]), r))
            self.off[s] = (c, rg.qnorm(rg.qmul(rg.qinv(r), soma.wr[s])))
        self.scale = soma.wt[soma.index["Hips"], 1] / self.cwt[cp.index["Hips"], 1]

    @staticmethod
    def canon(r, t):
        """Cyberpunk's rest faces -Z with left at -X, SOMA's faces +Z with left at +X: a half turn about Y."""
        return rg.qnorm(rg.qmul(YAW180, r)), rg.qrot(YAW180, t)

    def to_soma(self, rot, tra):
        """Cyberpunk local (nodes, frames, 4/3) -> SOMA local transforms (frames, joints, 7)."""
        s, cp = self.soma, self.cp
        w_r, w_t = self.canon(*cp.world_pose(rot, tra))
        frames = rot.shape[1]
        out = np.zeros((frames, len(s.names), 7), np.float32)
        for f in range(frames):
            pw = np.empty((len(s.names), 4))
            for i, p in enumerate(s.parent):
                if i in self.off:
                    c, o = self.off[i]
                    pw[i] = rg.qnorm(rg.qmul(w_r[c, f], o))
                    local = pw[i] if p < 0 else rg.qmul(rg.qinv(pw[p]), pw[i])
                else:
                    local = s.ref_r[i]
                    pw[i] = local if p < 0 else rg.qmul(pw[p], local)
                t = s.ref_t[i]
                if p < 0:
                    t = w_t[cp.index["Hips"], f] * self.scale
                out[f, i, :3], out[f, i, 3:] = t, rg.qnorm(local)
        return out

    def from_soma(self, poses, a_rot, a_tra, b_rot, b_tra):
        """SOMA local (frames, joints, 7) -> Cyberpunk local; unmapped bones blend A's last into B's first."""
        s, cp = self.soma, self.cp
        frames = poses.shape[0]
        sw_r = np.empty((len(s.names), frames, 4))
        sw_t = np.empty((frames, 3))
        lr = poses[:, :, 3:].astype(np.float64)
        for i, p in enumerate(s.parent):
            sw_r[i] = lr[:, i] if p < 0 else rg.qmul(sw_r[p], lr[:, i])
        sw_t[:] = poses[:, 0, :3]
        want = {c: (i, rg.qinv(o)) for i, (c, o) in self.off.items()}
        w = (np.arange(frames) / max(frames - 1, 1))[None, :, None]
        ar, br = a_rot[:, -1:, :], b_rot[:, :1, :]
        br = np.where(np.sum(ar * br, axis=-1, keepdims=True) < 0, -br, br)
        rot = rg.qnorm(ar * (1 - w) + br * w)
        tra = a_tra[:, -1:, :] * (1 - w) + b_tra[:, :1, :] * w
        w_r, w_t = np.empty_like(rot), np.empty_like(tra)
        for i in cp.order:
            p = cp.parent[i]
            if i in want:
                sidx, inv_o = want[i]
                g = rg.qnorm(rg.qmul(rg.qinv(YAW180), rg.qmul(sw_r[sidx], inv_o)))
                rot[i] = g if p < 0 else rg.qnorm(rg.qmul(rg.qinv(w_r[p]), g))
                if cp.names[i] == "Hips":
                    pos = rg.qrot(rg.qinv(YAW180), sw_t / self.scale)
                    tra[i] = pos if p < 0 else rg.qrot(rg.qinv(w_r[p]), pos - w_t[p])
            if p < 0:
                w_r[i], w_t[i] = rot[i], tra[i]
            else:
                w_r[i], w_t[i] = rg.qmul(w_r[p], rot[i]), w_t[p] + rg.qrot(w_r[p], tra[i])
        return rot, tra


def tail_times(end):
    """The end of a clip at 30 Hz, on its last frame: the model's context is 30 Hz whatever the clip's own rate."""
    return end - np.arange(int(end * FPS + 1e-6) + 1)[::-1] / FPS


def head_times(end):
    return np.arange(int(end * FPS + 1e-6) + 1) / FPS


def clip_in(doc, buf, sk, clip, times):
    """(animation, (rot, tra)) with the clip resampled by times(end). ValueError names what is wrong with it."""
    anim = next((x for x in doc["animations"] if x["name"] == clip), None)
    if anim is None:
        raise ValueError("no clip %s; the set has %s" % (clip, sorted(x["name"] for x in doc["animations"])))
    t = times(float(rg.clip_times(doc, buf, anim)[-1]))
    if len(t) < CONTEXT:
        raise ValueError("%s is %d frames at 30 Hz, the model needs %d" % (clip, len(t), CONTEXT))
    return anim, rg.sample_clip(doc, buf, anim, sk, t)


def load_clip(path, clip, times):
    """(doc, buf, skeleton, animation, (rot, tra)) with the clip resampled by times(end)."""
    doc, buf = rg.read_glb(path)
    sk = rg.Skeleton(doc)
    return (doc, buf, sk, *clip_in(doc, buf, sk, clip, times))


def measure(cp, rot, tra, a, b):
    """The numbers a transition is judged on, against A's last frame and B's first."""
    w_t = cp.world_pose(rot, tra)[1]
    a_t = cp.world_pose(a[0][:, -1:], a[1][:, -1:])[1]
    b_t = cp.world_pose(b[0][:, :1], b[1][:, :1])[1]
    bones = sorted(cp.joints)
    feet = [cp.index[n] for n in FEET if n in cp.index]
    return {
        "frames": rot.shape[1],
        "seconds": rot.shape[1] / FPS,
        "seam_a_cm": float(np.linalg.norm(w_t[bones, 0] - a_t[bones, -1], axis=-1).max() * 100),
        "seam_b_cm": float(np.linalg.norm(w_t[bones, -1] - b_t[bones, 0], axis=-1).max() * 100),
        "max_speed": float(np.linalg.norm(np.diff(w_t[bones], axis=1), axis=-1).max() * FPS),
        "lowest_foot": float(w_t[feet][..., 1].min()) if feet else None,
        "lowest_bone": float(w_t[bones][..., 1].min()),
        "lowest_bone_a": float(a_t[bones, -1, 1].min()),
        "lowest_bone_b": float(b_t[bones, 0, 1].min()),
    }


def failures(m, max_seam_cm=MAX_SEAM_CM, max_speed=MAX_SPEED):
    out = []
    if m["seam_a_cm"] > max_seam_cm:
        out.append("seam A %.2f cm over %.2f" % (m["seam_a_cm"], max_seam_cm))
    if m["seam_b_cm"] > max_seam_cm:
        out.append("seam B %.2f cm over %.2f" % (m["seam_b_cm"], max_seam_cm))
    if m["max_speed"] > max_speed:
        out.append("a bone moves %.2f m/s, over %.2f" % (m["max_speed"], max_speed))
    if "lowest_bone" in m:
        floor = min(m["lowest_bone_a"], m["lowest_bone_b"]) - MAX_SINK_CM / 100
        if m["lowest_bone"] < floor:
            out.append("a bone sinks to %.1f cm, under %.1f" % (m["lowest_bone"] * 100, floor * 100))
    return out
