"""Check a cooked, re-exported animset against the clip it was retargeted from.

For every clip and every bone the two skeletons share, the model-space rotation must agree -- that is
what the retarget promises, and the cook round trip must keep it. They are compared at the cooked clip's
frames, the source sampled there, and no clip may cook to fewer frames than its source has keys.
Every IK target the cooked rig has must sit on its bone (README, "What V needs").

Run: python tools/retarget/verify_retarget.py <source.anims.glb> <cooked.anims.glb> [--max-deg 0.1]
     [--max-cm 0.1]
"""
import argparse
import sys

import numpy as np

import retarget_glb as R


def angle(a, b):
    return np.degrees(2 * np.arccos(np.clip(np.abs(np.sum(a * b, axis=-1)), 0.0, 1.0)))


def model_pose(doc, buf, skel, anim, t):
    rot, tra = R.sample_clip(doc, buf, anim, skel, t)
    return skel.world_pose(rot, tra)


def ik_error_cm(skel, w_r, w_t):
    """Worst distance of any IK target from where its bone puts it, and that target's name."""
    worst, name = 0.0, ""
    for i, (b, _, off_t) in skel.ik_offsets().items():
        err = float(np.linalg.norm(w_t[i] - (w_t[b] + R.qrot(w_r[b], off_t)), axis=-1).max()) * 100
        if err > worst:
            worst, name = err, skel.names[i]
    return worst, name


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("source")
    ap.add_argument("cooked")
    ap.add_argument("--max-deg", type=float, default=0.1)
    ap.add_argument("--max-cm", type=float, default=0.1)
    args = ap.parse_args()
    limit = args.max_deg
    s_doc, s_buf = R.read_glb(args.source)
    c_doc, c_buf = R.read_glb(args.cooked)
    src, out = R.Skeleton(s_doc), R.Skeleton(c_doc)
    cooked = {a["name"]: a for a in c_doc["animations"]}
    worst_all, bad = 0.0, []
    for anim in s_doc["animations"]:
        name = anim["name"]
        if name not in cooked:
            bad.append("%s: missing from the cooked set" % name)
            continue
        t_s = R.clip_times(s_doc, s_buf, anim)
        t_c = R.clip_times(c_doc, c_buf, cooked[name])
        if abs(t_s[-1] - t_c[-1]) > 1 / 60:
            bad.append("%s: %.3fs became %.3fs" % (name, t_s[-1], t_c[-1]))
            continue
        if len(t_c) < len(t_s):
            # Exact at its own frames, a coarser grid still cuts fast motion: a foot came out 1.5 deg off.
            bad.append("%s: %d keys cooked to %d frames (END_PAD lost?)" % (name, len(t_s), len(t_c)))
        # At the cooked frames: a source's keys need not be evenly spaced and the SIMD grid is, so between frames
        # a 600 deg/s arm reads 0.13 deg off from interpolation alone. The source is unstretched by END_PAD.
        d_s, _ = model_pose(s_doc, s_buf, src, anim, t_c * (t_s[-1] / t_c[-1]))
        d_c, p_c = model_pose(c_doc, c_buf, out, cooked[name], t_c)
        ik, ik_name = ik_error_cm(out, d_c, p_c)
        if ik > args.max_cm:
            bad.append("%s: IK target %s %.2f cm off its bone" % (name, ik_name, ik))
        worst, bone = 0.0, ""
        for i in src.joints:
            j = out.index.get(src.names[i])
            if j is None:
                continue
            err = float(angle(d_s[i], d_c[j]).max())
            if err > worst:
                worst, bone = err, src.names[i]
        worst_all = max(worst_all, worst)
        print("%-28s %4d -> %4d frames  worst %.3f deg (%s)  IK %.3f cm" % (name, len(t_s), len(t_c), worst, bone, ik))
        if worst > limit:
            bad.append("%s: %.3f deg on %s" % (name, worst, bone))
    extra = sorted(set(cooked) - {a["name"] for a in s_doc["animations"]})
    if extra:
        bad.append("clips the source does not have: %s" % ", ".join(extra))
    if bad:
        sys.exit("FAIL\n  " + "\n  ".join(bad))
    print("OK  %d clips, worst %.3f deg (limit %.2f), IK targets within %.2f cm"
          % (len(s_doc["animations"]), worst_all, limit, args.max_cm))


if __name__ == "__main__":
    main()
