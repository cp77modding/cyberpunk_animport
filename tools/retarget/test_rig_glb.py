"""rig_glb.py: a rig json becomes the armature WolvenKit would export. No game data -- a three-bone rig."""
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import retarget_glb as G  # noqa: E402
import rig_glb as R  # noqa: E402


def qs(t, q):
    return {"Translation": dict(zip("XYZW", t + [0])), "Rotation": dict(zip("ijkr", q)),
            "Scale": {"X": 1, "Y": 1, "Z": 1, "W": 1}}


def rig(apose):
    s = 0.5 ** 0.5
    bones = [qs([0, 0, 0], [0, 0, 0, 1]),
             qs([0, -0.04, 1.0], [s, 0, 0, s * 0.9999]),   # Z-up, 90 deg about x, stored short of unit
             qs([0.1, 0, 0], [0, 0, 0, 1])]
    out = {"boneNames": [{"$value": n} for n in ("Root", "Hips", "Spine")], "boneParentIndexes": [-1, 0, 1],
           "boneTransforms": bones, "aPoseLS": []}
    if apose:
        out["aPoseLS"] = bones[:2] + [qs([0.1, 0, 0], [0, 0, np.sin(0.2), np.cos(0.2)])]
    return out


def main():
    fails = []
    doc, buf = R.armature(rig(False))
    sk = G.Skeleton(doc)
    hips = sk.index["Hips"]
    if not np.allclose(sk.rest_t[hips], [0, 1.0, 0.04]):
        fails.append("Z-up (x, y, z) is not Y-up (x, z, -y): %s" % sk.rest_t[hips].tolist())
    if abs(np.linalg.norm(sk.rest_r[hips]) - 1) > 1e-9:
        fails.append("a rig quaternion short of unit was written as is")
    if sk.names[sk.parent[sk.index["Spine"]]] != "Hips" or sk.names[sk.parent[sk.index["Root"]]] != "Armature":
        fails.append("parents not wired from boneParentIndexes")
    # Each inverse bind matrix undoes its bone's world rest: applied to the bone's own origin it gives zero.
    ibm = G.accessor(doc, buf, doc["skins"][0]["inverseBindMatrices"]).reshape(-1, 4, 4).transpose(0, 2, 1)
    w_r, w_t = sk.world_pose(sk.rest_r[:, None, :], sk.rest_t[:, None, :])
    for k, j in enumerate(doc["skins"][0]["joints"]):
        if not np.allclose(ibm[k] @ np.append(w_t[j, 0], 1), [0, 0, 0, 1], atol=1e-6):
            fails.append("inverse bind matrix of %s does not undo its rest" % sk.names[j])
    a = G.Skeleton(R.armature(rig(True))[0])
    if np.allclose(a.rest_r[a.index["Spine"]], sk.rest_r[sk.index["Spine"]]):
        fails.append("the A-pose was ignored where the rig has one")
    json.dumps(doc)
    for f in fails:
        print("FAIL", f)
    if fails:
        sys.exit(1)
    print("ok  axes, unit rotations, parents, bind matrices, A-pose rest")


main()
