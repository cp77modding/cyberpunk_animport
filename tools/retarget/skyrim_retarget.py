"""A Skyrim clip (blender-hkx unpack XML) onto a Cyberpunk NPC armature (woman_base / man_base).

The rigs disagree on names, bone counts per chain and bone axes, so each mapped bone gets a constant offset
O = inv(C) * R_target_rest, where C is the Skyrim rest rotation swung so the bone points where the target's
does. Animated: target world = source world * O. Unmapped target bones keep their local rest.

Run: python tools/retarget/skyrim_retarget.py <clip.xml> <donor.anims.glb> <rig.json> <out.glb> <clip name>
skyrim_port.py imports it and calls retarget() once per clip.
"""
import json
import sys
import xml.etree.ElementTree as ET

import numpy as np

import retarget_glb as rg

# target bone: (source bone, target aim child, source aim child); aim None = no swing (rest-relative).
MAP = {"Hips": ("NPC Pelvis [Pelv]", None, None)}
for S, s in (("Left", "L"), ("Right", "R")):
    MAP.update({
        S + "UpLeg": ("NPC %s Thigh [%sThg]" % (s, s), S + "Leg", "NPC %s Calf [%sClf]" % (s, s)),
        S + "Leg": ("NPC %s Calf [%sClf]" % (s, s), S + "Foot", "NPC %s Foot [%sft ]" % (s, s)),
        S + "Foot": ("NPC %s Foot [%sft ]" % (s, s), S + "ToeBase", "NPC %s Toe0 [%sToe]" % (s, s)),
        S + "ToeBase": ("NPC %s Toe0 [%sToe]" % (s, s), None, None),
        S + "Shoulder": ("NPC %s Clavicle [%sClv]" % (s, s), S + "Arm", "NPC %s UpperArm [%sUar]" % (s, s)),
        S + "Arm": ("NPC %s UpperArm [%sUar]" % (s, s), S + "ForeArm", "NPC %s Forearm [%sLar]" % (s, s)),
        S + "ForeArm": ("NPC %s Forearm [%sLar]" % (s, s), S + "Hand", "NPC %s Hand [%sHnd]" % (s, s)),
        S + "Hand": ("NPC %s Hand [%sHnd]" % (s, s), S + "HandMiddle1", "NPC %s Finger20 [%sF20]" % (s, s)),
    })
    for fname, fi in (("Thumb", 0), ("Index", 1), ("Middle", 2), ("Ring", 3), ("Pinky", 4)):
        tn = ([S + "InHandThumb", S + "HandThumb1", S + "HandThumb2"] if fi == 0
              else [S + "Hand%s%d" % (fname, k) for k in (1, 2, 3)])
        sn = ["NPC %s Finger%d%d [%sF%d%d]" % (s, fi, k, s, fi, k) for k in range(3)]
        for k in range(3):
            MAP[tn[k]] = (sn[k], tn[k + 1] if k < 2 else None, sn[k + 1] if k < 2 else None)
MAP.update({
    "Spine": ("NPC Spine [Spn0]", "Spine1", "NPC Spine1 [Spn1]"),
    "Spine1": ("NPC Spine1 [Spn1]", "Spine3", "NPC Spine2 [Spn2]"),
    "Spine3": ("NPC Spine2 [Spn2]", "Neck", "NPC Neck [Neck]"),
    "Neck": ("NPC Neck [Neck]", "Head", "NPC Head [Head]"),
    "Head": ("NPC Head [Head]", None, None),
})
# Bones that copy their bend from the bone below, not their direction in the world: Skyrim's neck stands 14 deg
# more upright and its collarbones slope 12 deg lower, so as directions every clip stood the neck up and dropped
# the shoulders. The spine keeps the world copy: bent from our rest it leaned a kneeling giver 20 deg further over.
LOCAL = {"Neck", "LeftShoulder", "RightShoulder"}
# bone: the child its axis runs to. Skyrim clips wring the neck up to 180 deg and turn the head back; our neck skin
# follows the bone, so the twist is dropped. The head is mapped in world space and keeps its turn.
UNTWIST = {"Neck": "Neck1"}
PELVIS = "NPC Pelvis [Pelv]"
FPS = 30.0  # blender-hkx resamples every clip to this

# Skyrim object space (Z up, faces +Y) to glTF (Y up, faces -Z): -90 deg about X.
C = np.array([-np.sqrt(0.5), 0, 0, np.sqrt(0.5)])


def qs(text):
    v = [float(x) for x in text.split()]
    return np.array(v[:3]), rg.qnorm(np.array([v[4], v[5], v[6], v[3]]))  # file is w x y z


def read_clip(path):
    root = ET.parse(path).getroot()
    frames = int(root.find("int[@name='frames']").text)
    if frames < 1:
        raise ValueError("%s: no frames (skeleton shorter than the clip's tracks?)" % path)
    names, parent, rest_t, rest_r = [], [], [], []

    def walk(el, p):
        for b in el.findall("bone"):
            t, r = qs(b.find("transform").text)
            names.append(b.get("name")), parent.append(p), rest_t.append(t), rest_r.append(r)
            walk(b, len(names) - 1)
    walk(root.find("skeleton"), -1)
    obj_t, obj_r = np.array(rest_t), np.array(rest_r)
    loc_t, loc_r = obj_t.copy(), obj_r.copy()
    for i, p in enumerate(parent):
        if p >= 0:
            inv = rg.qinv(obj_r[p])
            loc_r[i] = rg.qnorm(rg.qmul(inv, obj_r[i]))
            loc_t[i] = rg.qrot(inv, obj_t[i] - obj_t[p])
    idx = {n: i for i, n in enumerate(names)}
    rot = np.repeat(loc_r[:, None, :], frames, axis=1)
    tra = np.repeat(loc_t[:, None, :], frames, axis=1)
    for tr in root.find("animation").findall("track"):
        i = idx.get(tr.get("name"))
        if i is None or tr.get("type") != "transform":
            continue
        ks = tr.findall("transform")
        v = np.array([k.text.split()[:7] for k in ks], dtype=float)
        # a repeated frame keeps its last key; a frame without one holds the key before it, the first key before that
        kf, back = np.unique(np.array([int(k.get("name")) for k in ks])[::-1], return_index=True)
        v = v[len(ks) - 1 - back]
        sel = np.maximum(np.searchsorted(kf, np.arange(frames), side="right") - 1, 0)
        kt, kr = v[sel, :3], rg.qnorm(v[sel][:, [4, 5, 6, 3]])     # file is w x y z
        # a key is relative to the bone's local rest
        rot[i] = rg.qnorm(rg.qmul(loc_r[i], kr))
        tra[i] = loc_t[i] + rg.qrot(loc_r[i], kt)
    return idx, parent, obj_t, obj_r, rot, tra, frames


def world(parent, rot, tra):
    w_r, w_t = np.empty_like(rot), np.empty_like(tra)
    for i, p in enumerate(parent):  # parents precede children in the walk
        if p < 0:
            w_r[i], w_t[i] = rot[i], tra[i]
        else:
            w_r[i], w_t[i] = rg.qmul(w_r[p], rot[i]), w_t[p] + rg.qrot(w_r[p], tra[i])
    return w_r, w_t


def to_gltf(r, t):
    return rg.qnorm(rg.qmul(C, rg.qmul(r, rg.qinv(C)))), rg.qrot(C, t)


def swing(a, b):
    a, b = a / np.linalg.norm(a), b / np.linalg.norm(b)
    c, d = np.cross(a, b), float(np.dot(a, b))
    if d < -0.9999:
        return np.array([1.0, 0, 0, 0])
    return rg.qnorm(np.array([c[0], c[1], c[2], 1 + d]))


def untwist(d, axis):
    """Rotations d (n, 4) without their turn about axis (a unit vector in d's frame): the swing alone."""
    p = (d[:, :3] @ axis)[:, None] * axis
    t = np.concatenate([p, d[:, 3:]], axis=1)
    n = np.linalg.norm(t, axis=1, keepdims=True)
    t = np.where(n > 1e-9, t / np.maximum(n, 1e-9), [0, 0, 0, 1.0])   # a pure half swing has no twist
    return rg.qnorm(rg.qmul(d, rg.qinv(t)))


class Target:
    """A donor armature glb at rest: what every clip is retargeted onto."""

    def __init__(self, donor):
        self.doc, self.buf = rg.read_glb(donor)
        self.skel = rg.Skeleton(self.doc)
        s = self.skel
        w_r, w_t = s.world_pose(s.rest_r[:, None, :], s.rest_t[:, None, :])
        self.w_r, self.w_t = w_r[:, 0], w_t[:, 0]
        missing = sorted(n for n in MAP if n not in s.index)
        if missing:
            raise ValueError("%s lacks mapped bones: %s" % (donor, ", ".join(missing)))


def retarget(clip_xml, tg):
    """(rot, tra) per target bone and frame, the target's joint order, at FPS."""
    # a path, or read_clip's tuple already read (skyrim_port.py keeps it per source clip)
    s_idx, s_parent, s_obj_t, s_obj_r, s_rot, s_tra, frames = (read_clip(clip_xml) if isinstance(clip_xml, str)
                                                               else clip_xml)
    missing = sorted({v[0] for v in MAP.values()} - set(s_idx))
    if missing:
        raise ValueError("%s lacks source bones: %s" % (clip_xml if isinstance(clip_xml, str) else "the clip",
                                                         ", ".join(missing)))
    s_wr, s_wt = to_gltf(*world(s_parent, s_rot, s_tra))
    s_rr, s_rt = to_gltf(s_obj_r, s_obj_t)
    tgt = tg.skel
    scale = tg.w_t[tgt.index["Hips"], 1] / s_rt[s_idx[PELVIS], 1]
    offs = {}
    for tn, (sn, ta, sa) in MAP.items():
        i, j = tgt.index[tn], s_idx[sn]
        c = s_rr[j]
        if ta and tn not in LOCAL:
            c = rg.qnorm(rg.qmul(swing(s_rt[s_idx[sa]] - s_rt[j], tg.w_t[tgt.index[ta]] - tg.w_t[i]), c))
        offs[i] = (j, rg.qnorm(rg.qmul(rg.qinv(c), tg.w_r[i])))
    rot = np.repeat(tgt.rest_r[:, None, :], frames, axis=1)
    tra = np.repeat(tgt.rest_t[:, None, :], frames, axis=1)
    w_r, w_t = np.empty_like(rot), np.empty_like(tra)
    for i in tgt.order:
        p = tgt.parent[i]
        if i in offs:
            j, o = offs[i]
            if tgt.names[i] in LOCAL:
                # the source bone's turn from its rest under its own parent, carried into the target bone's frame
                ps = s_parent[j]
                d = rg.qmul(rg.qmul(rg.qinv(s_rr[j]), s_rr[ps]), rg.qmul(rg.qinv(s_wr[ps]), s_wr[j]))
                rot[i] = rg.qnorm(rg.qmul(tgt.rest_r[i], rg.qmul(rg.qmul(rg.qinv(o), d), o)))
            else:
                want = rg.qnorm(rg.qmul(s_wr[j], o))
                rot[i] = want if p < 0 else rg.qnorm(rg.qmul(rg.qinv(w_r[p]), want))
            if tgt.names[i] in UNTWIST:
                ax = tgt.rest_t[tgt.index[UNTWIST[tgt.names[i]]]]
                rest = np.broadcast_to(tgt.rest_r[i], rot[i].shape)
                rot[i] = rg.qnorm(rg.qmul(rest, untwist(rg.qmul(rg.qinv(rest), rot[i]), ax / np.linalg.norm(ax))))
            if tgt.names[i] == "Hips":
                pos = s_wt[j] * scale
                tra[i] = pos if p < 0 else rg.qrot(rg.qinv(w_r[p]), pos - w_t[p])
        if p < 0:
            w_r[i], w_t[i] = rot[i], tra[i]
        else:
            w_r[i], w_t[i] = rg.qmul(w_r[p], rot[i]), w_t[p] + rg.qrot(w_r[p], tra[i])
    return rot, tra


# WolvenKit's settings of an NPC set's clip, as its export writes them; player_extras sets the cook's own over them
CLIP_EXTRAS = {"schema": {"type": "wkit.cp2077.gltf.anims", "version": 4}, "animationType": "Normal",
               "rootMotionType": "Unknown", "frameClamping": True, "frameClampingStartFrame": -1,
               "frameClampingEndFrame": -1, "numExtraJoints": 0, "numExtraTracks": 0}


def extras_for(tg, rig_json):
    rig = json.load(open(rig_json, encoding="utf-8"))["Data"]["RootChunk"]
    return rg.player_extras(CLIP_EXTRAS, rig.get("referenceTracks", []))


def write(tg, extras, clips, out):
    """clips: (name, rot, tra) -> one glb on the donor armature."""
    built = [(n, extras, np.arange(rot.shape[1], dtype=np.float64) / FPS, rot, tra) for n, rot, tra in clips]
    gd, gb = rg.build(tg.doc, tg.buf, tg.skel, built)
    rg.write_glb(out, gd, gb)


def main():
    if len(sys.argv) != 6:
        sys.exit(__doc__)
    clip_xml, donor, rig_json, out, name = sys.argv[1:6]
    tg = Target(donor)
    rot, tra = retarget(clip_xml, tg)
    write(tg, extras_for(tg, rig_json), [(name, rot, tra)], out)
    print("%s: %d frames -> %s" % (name, rot.shape[1], out))


if __name__ == "__main__":
    main()
