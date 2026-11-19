"""mb_gif's verdicts and per-frame gap on made-up rows and capsules: no clips, no glbs.

Run: python tools/retarget/test_mb_gif.py (also from tools/py_test.ps1).
"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mb_gif as mgif  # noqa: E402

fails = []
side = {"player": "p.anims"}
ok = {"from": "a", "to": "b", "gap": -0.05, "gap_a": -0.02, "gap_b": 0.03, "sides": [side, side]}
cases = [
    (ok, frozenset(), "packed"),
    (dict(ok, gap=-0.30), frozenset(), "cut: overlaps 28 cm past the authored poses"),
    (ok, frozenset({("a", "b")}), "cut: on the drop list"),
    (dict(ok, sides=[side, {"player": None}]), frozenset(), "cut: no V clip"),
    ({"from": "a", "to": "b", "rejected": True, "reason": "sinks"}, frozenset(), "rejected: sinks"),
]
for r, drop, want in cases:
    if mgif.verdict(r, drop, 0.20) != want:
        fails.append("verdict %s: %s" % (want, mgif.verdict(r, drop, 0.20)))

# One capsule each, two frames: 1 m apart then touching 10 cm deep.
p1 = np.array([[[0, 0, 0], [0, 0, 0]]], float)
q1 = np.array([[[0, 1, 0], [0, 1, 0]]], float)
p2, q2 = p1 + [[[1.2, 0, 0], [0.3, 0, 0]]], q1 + [[[1.2, 0, 0], [0.3, 0, 0]]]
g = mgif.frame_gaps((p1, q1, np.array([0.1])), (p2, q2, np.array([0.1])))
if not np.allclose(g, [1.0, 0.1]):
    fails.append("frame_gaps: %s" % g)

for f in fails:
    print("FAIL", f)
print("test_mb_gif:", "FAILED" if fails else "ok")
sys.exit(1 if fails else 0)
