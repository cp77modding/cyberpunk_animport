"""A rig's armature as a glb, from the rig's json alone: the donor retarget_glb.py writes clips onto.

WolvenKit exports an armature only alongside a clip, and a rig nothing animates (woman_big) has none.

    python rig_glb.py <rig.json> <out.glb>
    python rig_glb.py --check <rig.json> <armature.glb>   compare with a WolvenKit-exported armature
"""
import json
import sys

import numpy as np

import retarget_glb as G


def zup_to_yup(t, q):
    """WolvenKit's export axes: the rig's (x, y, z) is the glb's (x, z, -y). Rig quaternions are stored short of unit."""
    r = np.array([q["i"], q["k"], -q["j"], q["r"]], dtype=np.float64)
    return [t["X"], t["Z"], -t["Y"]], (r / np.linalg.norm(r)).tolist()


def mat(r, t):
    m = np.eye(4)
    x, y, z, w = r
    m[:3, :3] = [[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
                 [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                 [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]]
    m[:3, 3] = t
    return m


def armature(rig):
    """(doc, buf): an Armature node over the rig's bones at rest, and a skin of every bone."""
    names = [n["$value"] for n in rig["boneNames"]]
    parents = rig["boneParentIndexes"]
    nodes = [{"name": "Armature", "children": []}]
    local = []
    # WolvenKit's armature rests in the A-pose where the rig has one (arms down, fingers curled).
    rest = rig["aPoseLS"] if len(rig.get("aPoseLS") or []) == len(names) else rig["boneTransforms"]
    for i, n in enumerate(names):
        tr = rest[i]
        t, r = zup_to_yup(tr["Translation"], tr["Rotation"])
        s = tr["Scale"]
        node = {"name": n, "rotation": r, "translation": t}
        if (s["X"], s["Y"], s["Z"]) != (1, 1, 1):
            node["scale"] = [s["X"], s["Z"], s["Y"]]
        nodes.append(node)
        local.append(mat(r, t))
        (nodes[0] if parents[i] < 0 else nodes[parents[i] + 1]).setdefault("children", []).append(i + 1)
    world = [None] * len(names)
    for i in range(len(names)):
        world[i] = local[i] if parents[i] < 0 else world[parents[i]] @ local[i]
    w = G.Writer()
    # glTF stores matrices column-major.
    ibm = w.add(np.array([np.linalg.inv(m).T.reshape(16) for m in world]), "MAT4")
    doc = {"asset": {"version": "2.0", "generator": "ncn rig_glb.py"}, "scene": 0, "scenes": [{"nodes": [0]}],
           "nodes": nodes, "skins": [{"joints": list(range(1, len(names) + 1)), "inverseBindMatrices": ibm}],
           "accessors": w.accessors, "bufferViews": w.views, "buffers": [{"byteLength": len(w.bin)}]}
    return doc, bytes(w.bin)


def check(rig, path):
    """Worst difference from a WolvenKit armature: per bone rest rotation (deg) and translation (mm)."""
    mine = G.Skeleton(armature(rig)[0])
    doc, _ = G.read_glb(path)
    theirs = G.Skeleton(doc)
    bad = []
    for name, i in mine.index.items():
        j = theirs.index.get(name)
        if j is None:
            bad.append("%s: missing from the exported armature" % name)
            continue
        if (mine.names[mine.parent[i]] if mine.parent[i] >= 0 else None) != \
                (theirs.names[theirs.parent[j]] if theirs.parent[j] >= 0 else None):
            bad.append("%s: parent differs" % name)
    rot = max(np.degrees(2 * np.arccos(min(1.0, abs(float(np.dot(mine.rest_r[i], theirs.rest_r[theirs.index[n]]))))))
              for n, i in mine.index.items() if n in theirs.index)
    tra = max(np.linalg.norm(mine.rest_t[i] - theirs.rest_t[theirs.index[n]]) * 1000
              for n, i in mine.index.items() if n in theirs.index)
    return bad, rot, tra


def main():
    args = [a for a in sys.argv[1:] if a != "--check"]
    if len(args) != 2:
        sys.exit(__doc__)
    rig = json.load(open(args[0], encoding="utf-8"))["Data"]["RootChunk"]
    if "--check" in sys.argv:
        bad, rot, tra = check(rig, args[1])
        for b in bad:
            print("FAIL", b)
        print("worst rest difference: %.5f deg, %.4f mm over %d bones" % (rot, tra, len(rig["boneNames"])))
        # WolvenKit's own rests sit 0.02-0.03 deg off the rig's; every clip track is written whole, so rest
        # rotation never reaches a clip. Bone lengths do, and they agree exactly.
        sys.exit(1 if bad or rot > 0.05 or tra > 0.01 else 0)
    G.write_glb(args[1], *armature(rig))
    print("wrote %s: %d bones" % (args[1], len(rig["boneNames"])))


if __name__ == "__main__":
    main()
