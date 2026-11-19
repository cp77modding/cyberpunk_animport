"""Retarget every clip of a WolvenKit animset glb onto another skeleton -- the wiki's Rokoko step, headless.

The source and target skeletons must share bone names (man_base is a name-exact subset of the player
skeletons, see README). Both rigs lay each bone along the same local axis but rest in different poses
(V's upper arm rests 47 deg from man_base's), so the target takes the source bone's model-space rotation
as is -- a delta from rest would carry that rest difference into every frame. Lengths stay the target's.

V's IK targets are then placed on the bones they stand for, and every clip is marked for WolvenKit's SIMD
encoder with the rig's float tracks at reference -- the shape V's own clips have (README, "What V needs").

Run: python tools/retarget/retarget_glb.py <source.anims.glb> <target-armature.anims.glb> <out.glb>
     --rig=<player_*_skeleton.rig.json> [--only=clip,clip] [--drop-missing]
--drop-missing lets a source bone the target lacks go unplayed (woman_big has no eyes or reference_joint).
The target glb is any WolvenKit export of an animset bound to the target rig; only its skeleton is used.
The rig json is the target rig serialized by WolvenKit (extract.ps1 writes it to work/json).
"""
import json
import struct
import sys

import numpy as np

END_PAD = 1e-4
COMP = {5126: np.float32, 5125: np.uint32, 5123: np.uint16, 5121: np.uint8}
WIDTH = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT4": 16}

# V's IK targets and the bone each rides at its rest offset, as in every vanilla V clip (to 0.02 cm).
# Left at rest, the animation graph pulls V's limbs back to rest: the T-pose.
IK_FOLLOW = {}
for _side, _s in (("Left", "left"), ("Right", "right")):
    IK_FOLLOW.update({
        "Torso_%sLeg_Foot_IK_JNT" % _side: _side + "Foot", "Torso_World_%sLeg_Foot_IK_JNT" % _side: _side + "Foot",
        "leg_%s_ik" % _s: _side + "Foot",
        "Torso_%sLeg_PoleVector_JNT" % _side: _side + "Leg", "Torso_World_%sLeg_PoleVector_JNT" % _side: _side + "Leg",
        "Torso_%sArm_Hand_IK_JNT" % _side: _side + "Hand", "Torso_World_%sArm_Hand_IK_JNT" % _side: _side + "Hand",
        "arm_%s_ik" % _s: _side + "Hand", "arm_%s_ik_offset" % _s: _side + "Hand",
        "Torso_%sArm_PoleVector_JNT" % _side: _side + "ForeArm",
        "Torso_World_%sArm_PoleVector_JNT" % _side: _side + "ForeArm",
        "arm_%s_ik_weapon" % _s: "Weapon" + _side,
    })
# V's graph drives the torso from the COG control; at rest a lying clip plays standing (2026-10-25).
IK_FOLLOW.update({"Torso_COG_Control_JNT": "Hips", "legs_ik_A_master": "Hips"})
# The pelvis and chest V's graph builds hang under the COG; at rest they ride it rigid, hands and all. Vanilla holds
# each on its bone at the rest offset (q105 dollhouse, 0.01 cm).
IK_FOLLOW.update({n: "Hips" for n in ("Torso_Hips_Offset_JNT", "Torso_Hips_Driver_GRP", "Torso_Hips_SpineDriver_GRP",
                                       "Torso_Hips_SpineDriverOffset_GRP", "Torso_Hips_UpOffset_GRP")})
IK_FOLLOW.update({n: "Spine3" for n in ("Torso_Chest_Offset_JNT", "Torso_Chest_Driver_GRP", "Torso_Chest_SpineDriver_GRP",
                                         "Torso_Chest_UpOffset_GRP")})


def read_glb(path):
    raw = open(path, "rb").read()
    jlen = struct.unpack_from("<I", raw, 12)[0]
    doc = json.loads(raw[20:20 + jlen])
    blen = struct.unpack_from("<I", raw, 20 + jlen)[0]
    return doc, raw[28 + jlen:28 + jlen + blen]


def accessor(doc, buf, i):
    acc = doc["accessors"][i]
    view = doc["bufferViews"][acc["bufferView"]]
    dt = COMP[acc["componentType"]]
    w = WIDTH[acc["type"]]
    if view.get("byteStride") and view["byteStride"] != w * np.dtype(dt).itemsize:
        raise ValueError("strided accessor %d is not supported" % i)
    start = view.get("byteOffset", 0) + acc.get("byteOffset", 0)
    arr = np.frombuffer(buf, dtype=dt, count=acc["count"] * w, offset=start)
    return arr.reshape(acc["count"], w) if w > 1 else arr


# Quaternions are glTF order (x, y, z, w), arrays of shape (..., 4).
def qmul(a, b):
    ax, ay, az, aw = a[..., 0], a[..., 1], a[..., 2], a[..., 3]
    bx, by, bz, bw = b[..., 0], b[..., 1], b[..., 2], b[..., 3]
    return np.stack([aw * bx + ax * bw + ay * bz - az * by,
                     aw * by - ax * bz + ay * bw + az * bx,
                     aw * bz + ax * by - ay * bx + az * bw,
                     aw * bw - ax * bx - ay * by - az * bz], axis=-1)


def qinv(q):
    return q * np.array([-1, -1, -1, 1], dtype=q.dtype)


def qnorm(q):
    return q / np.linalg.norm(q, axis=-1, keepdims=True)


def cross(a, b):
    """np.cross for 3-vectors, a tenth of its cost: world_pose is most of a batch's time."""
    ax, ay, az = a[..., 0], a[..., 1], a[..., 2]
    bx, by, bz = b[..., 0], b[..., 1], b[..., 2]
    return np.stack([ay * bz - az * by, az * bx - ax * bz, ax * by - ay * bx], axis=-1)


def qrot(q, v):
    u, w = q[..., :3], q[..., 3:]
    return v + 2 * cross(u, cross(u, v) + w * v)


def slerp_sample(times, keys, t):
    """Sample a rotation track at times t; nlerp between neighbours is exact enough at 30 fps."""
    idx = np.clip(np.searchsorted(times, t, side="right") - 1, 0, len(times) - 1)
    nxt = np.minimum(idx + 1, len(times) - 1)
    span = np.where(nxt > idx, times[nxt] - times[idx], 1.0)
    f = np.clip((t - times[idx]) / span, 0.0, 1.0)[:, None]
    a, b = keys[idx], keys[nxt]
    b = np.where((np.sum(a * b, axis=1) < 0)[:, None], -b, b)
    return qnorm(a * (1 - f) + b * f)


def lerp_sample(times, keys, t):
    out = np.empty((len(t), keys.shape[1]))
    for c in range(keys.shape[1]):
        out[:, c] = np.interp(t, times, keys[:, c])
    return out


class Skeleton:
    """Node names, parents and rest TRS of an exported armature, parents ordered before children."""

    def __init__(self, doc):
        nodes = doc["nodes"]
        self.names = [n["name"] for n in nodes]
        self.index = {n: i for i, n in enumerate(self.names)}
        if len(self.index) != len(self.names):
            raise ValueError("duplicate node names in the armature")
        self.parent = [-1] * len(nodes)
        for i, n in enumerate(nodes):
            for c in n.get("children", []):
                self.parent[c] = i
        self.order, stack = [], [i for i, p in enumerate(self.parent) if p < 0]
        while stack:
            i = stack.pop(0)
            self.order.append(i)
            stack.extend(nodes[i].get("children", []))
        self.rest_r = np.array([n.get("rotation", [0, 0, 0, 1]) for n in nodes], dtype=np.float64)
        self.rest_t = np.array([n.get("translation", [0, 0, 0]) for n in nodes], dtype=np.float64)
        self.joints = set(doc["skins"][0]["joints"])

    def world_rot(self, local):
        """Model-space rotations from local ones, shape (nodes, frames, 4)."""
        world = np.empty_like(local)
        for i in self.order:
            p = self.parent[i]
            world[i] = local[i] if p < 0 else qmul(world[p], local[i])
        return world

    def world_pose(self, rot, tra):
        """Model-space (rotations, positions) from local ones, shapes (nodes, frames, 4 / 3)."""
        w_r, w_t = np.empty_like(rot), np.empty_like(tra)
        for i in self.order:
            p = self.parent[i]
            if p < 0:
                w_r[i], w_t[i] = rot[i], tra[i]
            else:
                w_r[i], w_t[i] = qmul(w_r[p], rot[i]), w_t[p] + qrot(w_r[p], tra[i])
        return w_r, w_t

    def ik_offsets(self):
        """Each IK target's rest offset in its bone's space: {target: (bone, rotation, position)}."""
        r, t = self.world_pose(self.rest_r[:, None, :], self.rest_t[:, None, :])
        out = {}
        for name, bone in IK_FOLLOW.items():
            i, b = self.index.get(name), self.index.get(bone)
            if i is not None and b is not None:
                inv = qinv(r[b, 0])
                out[i] = (b, qmul(inv, r[i, 0]), qrot(inv, t[i, 0] - t[b, 0]))
        return out


def drive_ik(skel, rot, tra):
    """Place every IK target on its bone at the rest offset, in place, parents before children."""
    offsets = skel.ik_offsets()
    w_r, w_t = skel.world_pose(rot, tra)
    for i in skel.order:
        p = skel.parent[i]
        if i not in offsets:
            # Below a moved control (COG -> ... -> hand target) the world pose must follow it.
            if p >= 0:
                w_r[i], w_t[i] = qmul(w_r[p], rot[i]), w_t[p] + qrot(w_r[p], tra[i])
            continue
        b, off_r, off_t = offsets[i]
        want_r, want_t = qmul(w_r[b], off_r), w_t[b] + qrot(w_r[b], off_t)
        if p < 0:
            rot[i], tra[i] = qnorm(want_r), want_t
        else:
            rot[i] = qnorm(qmul(qinv(w_r[p]), want_r))
            tra[i] = qrot(qinv(w_r[p]), want_t - w_t[p])
        w_r[i], w_t[i] = want_r, want_t
    return len(offsets)


def clip_times(doc, buf, anim):
    """The densest key grid any channel of the clip uses -- every output track is written on it."""
    best = max((s["input"] for s in anim["samplers"]), key=lambda i: doc["accessors"][i]["count"])
    return np.asarray(accessor(doc, buf, best), dtype=np.float64)


def sample_clip(doc, buf, anim, skel, t):
    """Local (rotation, translation) of every node at times t; an untracked node holds its rest."""
    n, f = len(skel.names), len(t)
    rot = np.repeat(skel.rest_r[:, None, :], f, axis=1)
    tra = np.repeat(skel.rest_t[:, None, :], f, axis=1)
    for ch in anim["channels"]:
        node, path = ch["target"]["node"], ch["target"]["path"]
        smp = anim["samplers"][ch["sampler"]]
        times = np.asarray(accessor(doc, buf, smp["input"]), dtype=np.float64)
        keys = np.asarray(accessor(doc, buf, smp["output"]), dtype=np.float64)
        if smp.get("interpolation") == "CUBICSPLINE":
            raise ValueError("cubic spline track on %s" % skel.names[node])
        if path == "rotation":
            rot[node] = slerp_sample(times, qnorm(keys), t)
        elif path == "translation":
            tra[node] = lerp_sample(times, keys, t)
    return rot, tra


def retarget(src_doc, src_buf, anim, src, tgt):
    """One clip onto the target skeleton: (times, rotations, translations), target node order."""
    t = clip_times(src_doc, src_buf, anim)
    s_rot, s_tra = sample_clip(src_doc, src_buf, anim, src, t)
    f = len(t)
    s_world = src.world_rot(s_rot)
    t_rot = np.repeat(tgt.rest_r[:, None, :], f, axis=1)
    t_tra = np.repeat(tgt.rest_t[:, None, :], f, axis=1)
    t_world = np.empty_like(t_rot)
    for i in tgt.order:
        name, p = tgt.names[i], tgt.parent[i]
        j = src.index.get(name)
        if j is not None and i in tgt.joints:
            # Same model-space rotation as the source bone: the shared bone axes make that the same pose.
            world = qnorm(s_world[j])
            t_rot[i] = world if p < 0 else qnorm(qmul(qinv(t_world[p]), world))
            moved = s_tra[j] - src.rest_t[j]
            if name == "Hips":
                # The pelvis carries the body's travel; scale it by the leg length it stands on.
                ratio = np.linalg.norm(tgt.rest_t[i]) / max(np.linalg.norm(src.rest_t[j]), 1e-6)
                t_tra[i] = s_tra[j] * ratio
            else:
                # Parents share the source's model-space rotation, so the offset needs no re-basing.
                t_tra[i] = tgt.rest_t[i] + moved
        elif j is not None:
            # Armature, Root, Trajectory: not deforming bones, the clip's own motion is kept as is.
            t_rot[i], t_tra[i] = s_rot[j], s_tra[j]
        t_world[i] = t_rot[i] if p < 0 else qmul(t_world[p], t_rot[i])
    drive_ik(tgt, t_rot, t_tra)
    return t, t_rot, t_tra


def player_extras(extras, ref_tracks):
    """A clip's WolvenKit settings as V's own: SIMD, raw rotations, the rig's float tracks at reference."""
    out = dict(extras)
    out["optimizationHints"] = {"preferSIMD": True, "maxRotationCompression": 0}
    out["constTrackKeys"] = [{"trackIndex": i, "time": 0.0, "value": float(v)} for i, v in enumerate(ref_tracks)]
    out["trackKeys"] = []
    # The container's fallback table is emptied (anims_json prep); an index into it is a null read in the blend.
    out["fallbackFrameIndices"] = []
    return out


class Writer:
    """Accumulates accessors into one binary chunk."""

    def __init__(self):
        self.bin = bytearray()
        self.views, self.accessors = [], []

    def add(self, arr, kind, minmax=False):
        arr = np.ascontiguousarray(arr, dtype=np.float32)
        while len(self.bin) % 4:
            self.bin.append(0)
        self.views.append({"buffer": 0, "byteOffset": len(self.bin), "byteLength": arr.nbytes})
        self.bin += arr.tobytes()
        acc = {"bufferView": len(self.views) - 1, "componentType": 5126,
               "count": arr.shape[0], "type": kind}
        if minmax:
            acc["min"], acc["max"] = [float(arr.min())], [float(arr.max())]
        self.accessors.append(acc)
        return len(self.accessors) - 1


def build(tgt_doc, tgt_buf, tgt, clips):
    """The target armature glb with its animations replaced by the retargeted clips."""
    w = Writer()
    out = {k: v for k, v in tgt_doc.items() if k not in ("animations", "accessors", "bufferViews", "buffers")}
    out["skins"] = json.loads(json.dumps(tgt_doc["skins"]))
    for skin in out["skins"]:
        ibm = accessor(tgt_doc, tgt_buf, skin["inverseBindMatrices"])
        skin["inverseBindMatrices"] = w.add(ibm, "MAT4")
    out["animations"] = []
    for name, extras, t, rot, tra in clips:
        # WolvenKit's SIMD cook resamples to ceil(duration * 30) frames, one short of a 30 fps clip; stretched
        # 0.1 ms, every key lands on a cooked frame. Moving only the last key put a fast arm 0.17 deg off.
        if len(t) == 1:
            t, rot, tra = np.array([0.0, END_PAD]), np.repeat(rot, 2, axis=1), np.repeat(tra, 2, axis=1)
        else:
            t = t * ((t[-1] + END_PAD) / t[-1])
        tin = w.add(t, "SCALAR", minmax=True)
        tconst = w.add(t[[0, -1]], "SCALAR", minmax=True)
        samplers, channels = [], []
        for i in sorted(tgt.joints):
            for path, data, kind in (("rotation", rot[i], "VEC4"), ("translation", tra[i], "VEC3")):
                # A still track goes out as two LINEAR keys: WolvenKit cooks STEP ones to const keys, which V
                # plays as a T-pose.
                if np.abs(data - data[0]).max() < 1e-6:
                    smp = {"input": tconst, "output": w.add(data[[0, 0]], kind), "interpolation": "LINEAR"}
                else:
                    if path == "rotation":
                        # One hemisphere frame to frame, so a resample between keys takes the short way.
                        s = np.sign(np.sum(data[1:] * data[:-1], axis=1))
                        data = data * np.concatenate([[1.0], np.cumprod(np.where(s == 0, 1.0, s))])[:, None]
                    smp = {"input": tin, "output": w.add(data, kind), "interpolation": "LINEAR"}
                samplers.append(smp)
                channels.append({"sampler": len(samplers) - 1, "target": {"node": i, "path": path}})
        out["animations"].append({"name": name, "samplers": samplers, "channels": channels, "extras": extras})
    out["accessors"], out["bufferViews"] = w.accessors, w.views
    out["buffers"] = [{"byteLength": len(w.bin)}]
    return out, bytes(w.bin)


def write_glb(path, doc, buf):
    js = json.dumps(doc, separators=(",", ":")).encode()
    js += b" " * (-len(js) % 4)
    buf += b"\0" * (-len(buf) % 4)
    total = 12 + 8 + len(js) + 8 + len(buf)
    with open(path, "wb") as fh:
        fh.write(struct.pack("<III", 0x46546C67, 2, total))
        fh.write(struct.pack("<I4s", len(js), b"JSON") + js)
        fh.write(struct.pack("<I4s", len(buf), b"BIN\0") + buf)


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    opts = dict(a[2:].split("=", 1) for a in sys.argv[1:] if a.startswith("--") and "=" in a)
    only = set(opts["only"].split(",")) if "only" in opts else None
    if len(args) != 3 or "rig" not in opts:
        sys.exit(__doc__)
    rig = json.load(open(opts["rig"], encoding="utf-8"))["Data"]["RootChunk"]
    ref_tracks = rig["referenceTracks"]
    if len(ref_tracks) != len(rig["trackNames"]):
        sys.exit("%s: %d reference tracks for %d track names" % (opts["rig"], len(ref_tracks), len(rig["trackNames"])))
    src_doc, src_buf = read_glb(args[0])
    tgt_doc, tgt_buf = read_glb(args[1])
    src, tgt = Skeleton(src_doc), Skeleton(tgt_doc)
    src_bones = {src.names[i] for i in src.joints}
    tgt_bones = {tgt.names[i] for i in tgt.joints}
    missing = sorted(src_bones - tgt_bones)
    if missing and "--drop-missing" not in sys.argv:
        sys.exit("source bones the target lacks (map them first): %s" % ", ".join(missing))
    if missing:
        print("dropped, the target has none: %s" % ", ".join(missing))
    clips = []
    for anim in src_doc["animations"]:
        if only and anim["name"] not in only:
            continue
        t, rot, tra = retarget(src_doc, src_buf, anim, src, tgt)
        clips.append((anim["name"], player_extras(anim.get("extras", {}), ref_tracks), t, rot, tra))
        print("%-28s %4d frames  %.2fs" % (anim["name"], len(t), t[-1]))
    unknown = sorted((only or set()) - {a["name"] for a in src_doc["animations"]})
    if unknown:
        sys.exit("--only names clips the source does not have: %s" % ", ".join(unknown))
    doc, buf = build(tgt_doc, tgt_buf, tgt, clips)
    write_glb(args[2], doc, buf)
    print("%d clips, %d -> %d bones, %d IK targets on their bones, %d tracks -> %s"
          % (len(clips), len(src_bones), len(tgt_bones), len(tgt.ik_offsets()), len(ref_tracks), args[2]))


if __name__ == "__main__":
    main()
