"""pair_reach on synthetic tracks and a two-bone skeleton: no game data, no decode.

Run: python tools/retarget/test_pair_reach.py (also from tools/py_test.ps1).
"""
import math
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pair_reach as pr  # noqa: E402
import retarget_glb as rg  # noqa: E402

fails = []
frames = 40
t = np.linspace(0, 2 * math.pi, frames)
# The source: the target 0.30 m in front of the head and a little below, bobbing 3 cm.
src = np.stack([np.zeros(frames), -0.12 + 0.03 * np.sin(t), -0.27 + 0.0 * t], axis=1)

# Ours stops 10 cm short along the floor: the slide closes it, toward the target.
ours = src + np.array([0.0, 0.0, -0.10])
shift, after = pr.slide(ours, src)
want = np.linalg.norm(src, axis=1).mean()
if abs(after - want) > 0.005:
    fails.append("a 10 cm flat shortfall left %.3f m against %.3f" % (after, want))
if abs(shift[0]) > 1e-9 or shift[1] != 0.0 or shift[2] > -0.08:
    fails.append("the slide is not flat and straight toward the target: %s" % shift)

# Ours too close (the face inside the body): the slide backs off.
shift, after = pr.slide(src * 0.75, src)
if abs(after - want) > 0.005 or shift[2] < 0.02:
    fails.append("a reach 25%% short was not backed off: shift %s after %.3f" % (shift, after))

# Already right: no slide.
shift, after = pr.slide(src.copy(), src)
if np.linalg.norm(shift) > 0.003:
    fails.append("a matching pair was slid %s" % shift)

# The rules: source not in contact, over the cap, close enough, and a plain fix.
if not pr.why_not(0.50, 0.70, np.array([0.05, 0, 0])):
    fails.append("a source reach of 0.70 m was taken as oral contact")
if not pr.why_not(0.50, 0.30, np.array([0.20, 0, 0])):
    fails.append("a 20 cm slide passed the cap")
if not pr.why_not(0.31, 0.30, np.array([0.01, 0, 0])):
    fails.append("a 1 cm difference was slid")
if pr.why_not(0.40, 0.30, np.array([0.10, 0, 0])):
    fails.append("a 10 cm shortfall was refused")
if not pr.why_not(0.21, 0.20, np.array([0.20, 0, 0])):
    fails.append("a 1 cm gap was slid 20 cm (checked before the cap)")
if not pr.why_not(0.51, 0.48, np.array([0.12, 0, 0])):
    fails.append("a 12 cm slide for a 3 cm gap (a vertical gap) was taken")

# One clip name in both sexes' sets: two keys, so a slide measured on one body never lands on the other.
if pr.key({"clip": "bj_0", "sex": "m"}) == pr.key({"clip": "bj_0", "sex": "f"}):
    fails.append("the man's and the woman's bj_0 share a key")


# merge: a clip refused once, or slid two ways, stays refused through any later scene.
def entry(x, scene):
    return {"shift": [x, 0.0, 0.0], "scene": scene}


shifts, refused = {}, set()
pr.merge(shifts, refused, "k", entry(0.10, "s1"), None)
pr.merge(shifts, refused, "k", entry(0.05, "s2"), None)
if not pr.merge(shifts, refused, "k", entry(0.10, "s3"), None) or "k" in shifts:
    fails.append("a third scene agreeing with the first put back a clip slid two ways")
shifts, refused = {}, set()
pr.merge(shifts, refused, "k", entry(0.10, "s1"), "within 2 cm")
if not pr.merge(shifts, refused, "k", entry(0.10, "s2"), None) or "k" in shifts:
    fails.append("a later scene slid a clip an earlier scene refused")
shifts, refused = {}, set()
pr.merge(shifts, refused, "k", entry(0.10, "s1"), None)
if pr.merge(shifts, refused, "k", entry(0.105, "s2"), None) or "k" not in shifts:
    fails.append("two scenes agreeing within 1 cm refused the clip")


# apply_shift under a turned root: the Hips land exactly `shift` away in model space, rotations untouched.
class Skel:
    names = ["Root", "Hips", "Head"]
    index = {"Root": 0, "Hips": 1, "Head": 2}
    parent = [-1, 0, 1]
    order = [0, 1, 2]
    world_pose = rg.Skeleton.world_pose


h = math.radians(90) / 2
rot = np.zeros((3, frames, 4))
rot[0] = [0, math.sin(h), 0, math.cos(h)]  # root turned 90 degrees about up
rot[1] = [0, 0, 0, 1]
rot[2] = [0, 0, 0, 1]
tra = np.zeros((3, frames, 3))
tra[1] = [0.0, 0.9, 0.2]
tra[2] = [0.0, 0.6, 0.0]
sk = Skel()
_, before = sk.world_pose(rot, tra)
move = np.array([0.05, 0.0, -0.10])
r2, t2 = rot.copy(), tra.copy()
pr.apply_shift(sk, r2, t2, move)
_, moved = sk.world_pose(r2, t2)
if np.abs(moved[1] - before[1] - move).max() > 1e-9 or np.abs(moved[2] - before[2] - move).max() > 1e-9:
    fails.append("apply_shift under a turned root moved the body by %s, not %s" % (moved[1, 0] - before[1, 0], move))
if not np.array_equal(r2, rot) or not np.array_equal(moved[0], before[0]):
    fails.append("apply_shift touched a rotation or the root")

for f in fails:
    print("FAIL", f)
print("test_pair_reach:", "FAILED" if fails else "ok")
sys.exit(1 if fails else 0)
