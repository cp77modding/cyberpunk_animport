"""retarget_glb on a synthetic three-bone pair: no game data, no WolvenKit.

The two skeletons share names but not rest poses or lengths -- the man_base / player_skeleton
situation in miniature. Run: python tools/retarget/test_retarget_glb.py (also from tools/py_test.ps1).
"""
import math
import os
import shutil
import sys
import tempfile

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import retarget_glb as R  # noqa: E402
import verify_retarget as V  # noqa: E402


def quat(axis, deg):
    a = np.asarray(axis, dtype=np.float64)
    a /= np.linalg.norm(a)
    h = math.radians(deg) / 2
    return [*(a * math.sin(h)), math.cos(h)]


def armature(rests):
    """Armature -> Root -> Hips -> Spine -> Arm, each with (rotation, translation) rest."""
    names = ["Armature", "Root", "Hips", "Spine", "Arm"]
    nodes = []
    for i, n in enumerate(names):
        node = {"name": n}
        if i + 1 < len(names):
            node["children"] = [i + 1]
        if n in rests:
            node["rotation"], node["translation"] = rests[n]
        nodes.append(node)
    return names, nodes


def source_glb():
    """A two-frame clip on the source skeleton, written and read back through the real glb code."""
    names, nodes = armature({"Hips": (quat([1, 0, 0], 90), [0, 1.0, 0]),
                             "Spine": (quat([0, 0, 1], 5), [0, 0.10, 0]),
                             "Arm": (quat([0, 1, 0], 0), [0, 0.14, 0])})
    w = R.Writer()
    t = w.add(np.array([0.0, 1.0]), "SCALAR", minmax=True)
    keys = {"Hips": [quat([1, 0, 0], 90), quat([1, 0, 0], 120)],
            "Spine": [quat([0, 0, 1], 5), quat([0, 0, 1], 40)],
            "Arm": [quat([0, 1, 0], 0), quat([1, 1, 0], 70)]}
    samplers, channels = [], []
    for n, k in keys.items():
        samplers.append({"input": t, "output": w.add(np.array(k), "VEC4")})
        channels.append({"sampler": len(samplers) - 1, "target": {"node": names.index(n), "path": "rotation"}})
    samplers.append({"input": t, "output": w.add(np.array([[0, 1.0, 0], [0.2, 0.8, 0.1]]), "VEC3")})
    channels.append({"sampler": len(samplers) - 1, "target": {"node": 2, "path": "translation"}})
    ibm = w.add(np.tile(np.eye(4).ravel(), (4, 1)), "MAT4")
    doc = {"asset": {"version": "2.0"}, "nodes": nodes, "scenes": [{"nodes": [0]}],
           "skins": [{"joints": [1, 2, 3, 4], "inverseBindMatrices": ibm}],
           "animations": [{"name": "clip", "samplers": samplers, "channels": channels, "extras": {"k": 1}}],
           "accessors": w.accessors, "bufferViews": w.views, "buffers": [{"byteLength": len(w.bin)}]}
    return doc, bytes(w.bin)


def target_glb():
    # A different rest pose (the arm 47 deg off, as V's is) and a longer spine and arm: the player skeleton.
    _, nodes = armature({"Hips": (quat([1, 0, 0], 92), [0, 1.02, 0]),
                         "Spine": (quat([0, 0, 1], 11), [0, 0.12, 0]),
                         "Arm": (quat([0, 0, 1], 47), [0, 0.17, 0])})
    w = R.Writer()
    ibm = w.add(np.tile(np.eye(4).ravel(), (4, 1)), "MAT4")
    doc = {"asset": {"version": "2.0"}, "nodes": nodes, "scenes": [{"nodes": [0]}],
           "skins": [{"joints": [1, 2, 3, 4], "inverseBindMatrices": ibm}],
           "accessors": w.accessors, "bufferViews": w.views, "buffers": [{"byteLength": len(w.bin)}]}
    return doc, bytes(w.bin)


def ik_case():
    """An IK target under Root must follow LeftHand, which moves with Hips; undriven it stays at rest."""
    nodes = [{"name": "Root", "children": [1, 3]},
             {"name": "Hips", "children": [2], "rotation": quat([1, 0, 0], 10), "translation": [0, 1.0, 0]},
             {"name": "LeftHand", "rotation": quat([0, 0, 1], 30), "translation": [0.3, 0.2, 0]},
             {"name": "Torso_LeftArm_Hand_IK_JNT", "rotation": quat([0, 1, 0], 15), "translation": [0.33, 1.25, 0.05]}]
    skel = R.Skeleton({"nodes": nodes, "skins": [{"joints": [0, 1, 2, 3]}]})
    rot = np.repeat(skel.rest_r[:, None, :], 3, axis=1)
    tra = np.repeat(skel.rest_t[:, None, :], 3, axis=1)
    rot[1] = [quat([1, 0, 0], 10), quat([1, 0, 0], 60), quat([0, 1, 1], 80)]
    tra[1] = [[0, 1.0, 0], [0.2, 0.7, 0.1], [0, 0.4, 0.3]]
    fails = []
    w_r, w_t = skel.world_pose(rot, tra)
    if V.ik_error_cm(skel, w_r, w_t)[0] < 1.0:
        fails.append("an undriven IK target passes the IK check -- the check proves nothing")
    if R.drive_ik(skel, rot, tra) != 1:
        fails.append("drive_ik did not find the IK target")
    w_r, w_t = skel.world_pose(rot, tra)
    err, _ = V.ik_error_cm(skel, w_r, w_t)
    if err > 1e-4:
        fails.append("IK target %.4f cm off its bone after drive_ik" % err)
    rest_r, _ = skel.world_pose(skel.rest_r[:, None, :], skel.rest_t[:, None, :])
    want = R.qmul(w_r[2], R.qmul(R.qinv(rest_r[2, 0]), rest_r[3, 0]))
    if V.angle(want, w_r[3]).max() > 1e-3:
        fails.append("IK target rotation does not keep its rest offset from the bone")
    return fails


def cog_case():
    """A hand target below the COG control, through a bone nobody drives: both must land on their bones."""
    nodes = [{"name": "Root", "children": [1, 3]},
             {"name": "Hips", "children": [2], "translation": [0, 1.0, 0]},
             {"name": "LeftHand", "translation": [0.3, 0.2, 0]},
             {"name": "Torso_COG_Control_JNT", "children": [4], "translation": [0, 1.02, 0]},
             {"name": "Torso_Mid", "children": [5], "rotation": quat([0, 0, 1], 20), "translation": [0, 0.1, 0]},
             {"name": "Torso_LeftArm_Hand_IK_JNT", "translation": [0.3, 0.1, 0]}]
    skel = R.Skeleton({"nodes": nodes, "skins": [{"joints": [0, 1, 2]}]})
    rot = np.repeat(skel.rest_r[:, None, :], 2, axis=1)
    tra = np.repeat(skel.rest_t[:, None, :], 2, axis=1)
    rot[1] = [quat([1, 0, 0], 0), quat([1, 0, 0], 90)]   # lying down
    tra[1] = [[0, 1.0, 0], [0, 0.3, 0]]
    offsets = skel.ik_offsets()
    R.drive_ik(skel, rot, tra)
    w_r, w_t = skel.world_pose(rot, tra)
    fails = []
    for i, (b, off_r, off_t) in offsets.items():
        err = np.linalg.norm(w_t[i] - (w_t[b] + R.qrot(w_r[b], off_t)), axis=-1).max() * 100
        if err > 1e-4:
            fails.append("%s %.4f cm off its bone below a moved COG control" % (skel.names[i], err))
    if len(offsets) != 2:
        fails.append("COG control not followed: %d targets" % len(offsets))
    return fails


def chain_case():
    """The pelvis and chest chains under the COG land on Hips and Spine3 when V lies down, as in vanilla."""
    nodes = [{"name": "Root", "children": [1, 4]},
             {"name": "Hips", "children": [2], "translation": [0, 1.0, 0]},
             {"name": "Spine", "children": [3], "translation": [0, 0.2, 0]},
             {"name": "Spine2", "children": [4], "translation": [0, 0.1, 0]},
             {"name": "Spine3", "translation": [0, 0.1, 0]},
             {"name": "Torso_COG_Control_JNT", "children": [6, 7], "translation": [0, 1.02, 0]},
             {"name": "Torso_Hips_Offset_JNT", "translation": [0, -0.02, 0]},
             {"name": "Torso_Chest_Offset_JNT", "translation": [0, 0.38, 0]}]
    skel = R.Skeleton({"nodes": nodes, "skins": [{"joints": [0, 1, 2, 3, 4]}]})
    rot = np.repeat(skel.rest_r[:, None, :], 2, axis=1)
    tra = np.repeat(skel.rest_t[:, None, :], 2, axis=1)
    rot[1] = [quat([1, 0, 0], 0), quat([1, 0, 0], 90)]
    tra[1] = [[0, 1.0, 0], [0, 0.3, 0]]
    # The back bends at two joints: a chest riding the COG, or one hung on Spine, misses Spine3.
    rot[2] = [quat([0, 0, 1], 0), quat([0, 0, 1], 40)]
    rot[3] = [quat([0, 0, 1], 0), quat([0, 0, 1], 30)]
    R.drive_ik(skel, rot, tra)
    w_r, w_t = skel.world_pose(rot, tra)
    fails = []
    for ctl, bone in (("Torso_Hips_Offset_JNT", "Hips"), ("Torso_Chest_Offset_JNT", "Spine3")):
        err = np.linalg.norm(w_t[skel.index[ctl]] - w_t[skel.index[bone]], axis=-1).max() * 100
        if err > 1e-4:
            fails.append("%s %.2f cm off %s with V lying -- V's graph builds the body from it" % (ctl, err, bone))
    return fails


def build_case():
    """A one-key clip still gets increasing times; a sign-flipped key is put back in its neighbours' hemisphere."""
    t_doc, t_buf = target_glb()
    tgt = R.Skeleton(t_doc)
    rot1 = np.repeat(tgt.rest_r[:, None, :], 1, axis=1)
    tra1 = np.repeat(tgt.rest_t[:, None, :], 1, axis=1)
    rot3 = np.repeat(tgt.rest_r[:, None, :], 3, axis=1)
    tra3 = np.repeat(tgt.rest_t[:, None, :], 3, axis=1)
    rot3[3] = [quat([0, 0, 1], 10), np.negative(quat([0, 0, 1], 20)), quat([0, 0, 1], 30)]
    doc, buf = R.build(t_doc, t_buf, tgt, [("one", {}, np.array([0.0]), rot1, tra1),
                                           ("flip", {}, np.array([0.0, 0.5, 1.0]), rot3, tra3)])
    fails = []
    for anim in doc["animations"]:
        for s in anim["samplers"]:
            times = R.accessor(doc, buf, s["input"])
            if len(times) < 2 or not np.all(np.diff(times) > 0):
                fails.append("%s: key times not increasing: %s" % (anim["name"], times.tolist()))
                break
    flip = doc["animations"][1]
    ch = next(c for c in flip["channels"] if c["target"] == {"node": 3, "path": "rotation"})
    q = R.accessor(doc, buf, flip["samplers"][ch["sampler"]]["output"])
    if np.any(np.sum(q[1:] * q[:-1], axis=1) < 0):
        fails.append("a rotation track crosses hemispheres between keys")
    return fails


def extras_case():
    ex = R.player_extras({"k": 1, "optimizationHints": {"preferSIMD": False, "maxRotationCompression": 1},
                          "fallbackFrameIndices": [1, 2]}, [0, 1, 0.5])
    fails = []
    if ex.get("k") != 1:
        fails.append("player_extras dropped the clip's own settings")
    if ex["optimizationHints"] != {"preferSIMD": True, "maxRotationCompression": 0}:
        fails.append("clip not marked for the SIMD encoder with raw rotations: %s" % ex["optimizationHints"])
    if [k["value"] for k in ex["constTrackKeys"]] != [0, 1, 0.5] or ex["trackKeys"]:
        fails.append("float tracks are not the rig's reference values")
    if ex["fallbackFrameIndices"]:
        fails.append("a clip still indexes the fallback table prep empties")
    return fails


def main():
    tmp = tempfile.mkdtemp()
    src_path, out_path = os.path.join(tmp, "src.glb"), os.path.join(tmp, "out.glb")
    R.write_glb(src_path, *source_glb())
    s_doc, s_buf = R.read_glb(src_path)
    t_doc, t_buf = target_glb()
    src, tgt = R.Skeleton(s_doc), R.Skeleton(t_doc)

    clip = s_doc["animations"][0]
    t, rot, tra = R.retarget(s_doc, s_buf, clip, src, tgt)
    R.write_glb(out_path, *R.build(t_doc, t_buf, tgt, [("clip", clip["extras"], t, rot, tra)]))
    o_doc, o_buf = R.read_glb(out_path)
    out = R.Skeleton(o_doc)
    fails = []
    # build() stretches the clip END_PAD; the source clamps there to its own last key.
    t = t * ((t[-1] + R.END_PAD) / t[-1])

    s_rot, _ = R.sample_clip(s_doc, s_buf, clip, src, t)
    o_rot, _ = R.sample_clip(o_doc, o_buf, o_doc["animations"][0], out, t)
    w_src, w_out = src.world_rot(s_rot), out.world_rot(o_rot)
    worst = max(V.angle(w_src[i], w_out[i]).max() for i in src.joints)
    if worst > 1e-3:
        fails.append("model-space pose not matched: %.4f deg" % worst)

    # The check must be able to fail: a delta from each rig's rest carries the 47 deg rest difference.
    s_rest = src.world_rot(src.rest_r[:, None, :])
    t_rest = tgt.world_rot(tgt.rest_r[:, None, :])
    delta = {i: R.qmul(R.qmul(w_src[i], R.qinv(s_rest[i])), t_rest[i]) for i in src.joints}
    if max(V.angle(w_src[i], delta[i]).max() for i in src.joints) < 1.0:
        fails.append("a delta-from-rest retarget passes the same check -- the check proves nothing")

    _, o_tra = R.sample_clip(o_doc, o_buf, o_doc["animations"][0], out, t)
    if not np.allclose(o_tra[4], [[0, 0.17, 0]] * 2, atol=1e-6):
        fails.append("arm length is not the target's: %s" % o_tra[4].tolist())
    if not np.allclose(o_tra[2][1], np.array([0.2, 0.8, 0.1]) * 1.02, atol=1e-5):
        fails.append("pelvis travel not scaled by leg length: %s" % o_tra[2][1].tolist())
    if o_doc["animations"][0].get("extras") != {"k": 1}:
        fails.append("clip extras (WolvenKit's animation settings) were dropped")
    smps = o_doc["animations"][0]["samplers"]
    if any(s["interpolation"] == "STEP" for s in smps):
        fails.append("a STEP track was written -- WolvenKit cooks it to a const key V plays as a T-pose")
    if not any(o_doc["accessors"][s["input"]]["count"] == 2 for s in smps):
        fails.append("still Root track was not written as a two-key constant")
    end = max(o_doc["accessors"][s["input"]]["max"][0] for s in smps)
    if abs(end - (1.0 + R.END_PAD)) > 1e-7:
        fails.append("clip ends at %.6f s, not padded -- WolvenKit's SIMD cook drops its last frame" % end)

    shutil.rmtree(tmp)

    fails += ik_case()
    fails += cog_case()
    fails += chain_case()
    fails += build_case()
    fails += extras_case()

    for f in fails:
        print("FAIL", f)
    if fails:
        sys.exit(1)
    print("ok  retarget matches the model-space pose (%.5f deg), target lengths, scaled pelvis, "
          "IK targets on their bones, V's clip settings" % worst)


if __name__ == "__main__":
    main()
