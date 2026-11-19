"""Bone-name diff between two serialized .rig files.

A retarget is only viable when the two skeletons share bone names; where they do, Rokoko/Auto-Rig
maps 1:1 and the work is mechanical. Where they don't, every unshared bone is a hand-mapped or
dropped track.

Run: python tools/retarget/compare_rigs.py work/json/man_base.rig.json work/json/player_man_skeleton.rig.json
"""
import json
import os
import sys


def bones(path):
    """Ordered bone names, parents and bind transforms out of a WolvenKit-serialized animRig."""
    doc = json.load(open(path, encoding="utf-8"))
    data = doc["Data"]["RootChunk"]
    names = [b["$value"] if isinstance(b, dict) else b for b in data.get("boneNames", [])]
    parents = data.get("boneParentIndexes", data.get("boneParents", []))
    return names, parents, data.get("boneTransforms", [])


def xform(t):
    """(translation, rotation) as flat tuples; the bind pose is what a name match cannot promise."""
    def vals(node, keys):
        return tuple(round(float(node.get(k, 0)), 5) for k in keys) if isinstance(node, dict) else ()
    return (vals(t.get("Translation", {}), "XYZ"), vals(t.get("Rotation", {}), "IJKR"))


def main():
    args = [a for a in sys.argv[1:] if a != "--summary"]
    summary = "--summary" in sys.argv
    if len(args) != 2:
        sys.exit(__doc__)
    here = os.path.dirname(os.path.abspath(__file__))
    a_path, b_path = (p if os.path.isabs(p) else os.path.join(here, p) for p in args)
    a_names, a_par, a_xf = bones(a_path)
    b_names, b_par, b_xf = bones(b_path)
    a_set, b_set = set(a_names), set(b_names)
    shared = a_set & b_set

    def stem(p):
        return os.path.basename(p).replace(".rig.json", "")

    if not summary:
        print("A  %-34s %d bones" % (os.path.basename(a_path), len(a_names)))
        print("B  %-34s %d bones" % (os.path.basename(b_path), len(b_names)))
        print("shared %d   A-only %d   B-only %d"
              % (len(shared), len(a_set - b_set), len(b_set - a_set)))

    # A shared name is still a broken mapping if its parent differs -- the pose would be applied
    # under a different joint. Check hierarchy, not just names.
    a_idx = {n: i for i, n in enumerate(a_names)}
    b_idx = {n: i for i, n in enumerate(b_names)}

    def parent_of(names, par, i):
        p = par[i] if i < len(par) else -1
        return names[p] if 0 <= p < len(names) else None

    rehomed = [n for n in sorted(shared)
               if parent_of(a_names, a_par, a_idx[n]) != parent_of(b_names, b_par, b_idx[n])]

    # Matching names on a different bind pose is the case that deforms: the clip's rotations are
    # authored against A's proportions and get applied to B's. Distance is the honest unit here --
    # "16 bones differ" says nothing until you know whether that is a millimetre or a limb.
    moved, worst, worst_bone = [], 0.0, None
    if a_xf and b_xf:
        for n in sorted(shared):
            if a_idx[n] >= len(a_xf) or b_idx[n] >= len(b_xf):
                continue
            ta, tb = xform(a_xf[a_idx[n]]), xform(b_xf[b_idx[n]])
            if ta == tb:
                continue
            moved.append(n)
            d = sum((x - y) ** 2 for x, y in zip(ta[0], tb[0])) ** 0.5
            if d > worst:
                worst, worst_bone = d, n

    if summary:
        print("%-26s -> %-26s %d/%d names  %d re-parented  %d moved (max %.1f mm, %s)"
              % (stem(a_path), stem(b_path), len(shared), len(a_names), len(rehomed),
                 len(moved), worst * 1000, worst_bone or "-"))
        return

    print("shared but re-parented: %d" % len(rehomed))
    for n in rehomed[:40]:
        print("   %-32s A<-%-24s B<-%s" % (n, parent_of(a_names, a_par, a_idx[n]),
                                           parent_of(b_names, b_par, b_idx[n])))

    print("shared but different bind transform: %d   (max %.1f mm at %s)"
          % (len(moved), worst * 1000, worst_bone or "-"))
    for n in moved[:20]:
        print("   %-30s A%s\n   %-30s B%s" % (n, xform(a_xf[a_idx[n]])[0], "", xform(b_xf[b_idx[n]])[0]))
    if len(moved) > 20:
        print("   ... +%d more" % (len(moved) - 20))

    for label, only in (("A-only", sorted(a_set - b_set)), ("B-only", sorted(b_set - a_set))):
        print("\n--- %s (%d) ---" % (label, len(only)))
        for n in only[:80]:
            print("   " + n)
        if len(only) > 80:
            print("   ... +%d more" % (len(only) - 80))


if __name__ == "__main__":
    main()
