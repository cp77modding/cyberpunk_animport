"""interaction_mesh's solve on two stick figures: no game data, no decode.

Run: python tools/retarget/test_interaction_mesh.py (also from tools/py_test.ps1).
"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import interaction_mesh as im  # noqa: E402
import retarget_glb as rg  # noqa: E402

fails = []
quiet = lambda *a: None

# The best rigid fit finds a known turn, as a matrix and as a quaternion.
q = rg.qnorm(np.array([0.2, -0.5, 0.3, 0.8]))
a = im.unit(np.array([[1.0, 0, 0], [0, 1.0, 0], [0.3, 0.2, 1.0]]))
b = rg.qrot(np.broadcast_to(q, (3, 4)), a)
R = im.kabsch(a[None], b[None])[0]
if np.abs(a @ R.T - b).max() > 1e-9:
    fails.append("kabsch missed a known turn by %.2g" % np.abs(a @ R.T - b).max())
if np.abs(rg.qrot(np.broadcast_to(im.m2q(R), (3, 4)), a) - b).max() > 1e-6:
    fails.append("m2q of the fitted turn is not the turn")

# Capsule gap: parallel segments 0.10 apart with radii 0.03 + 0.04 leave 0.03.
P = np.array([[0, 0, 0], [0, 1.0, 0], [0.1, 0.2, 0], [0.1, 0.8, 0]])
gap = im.capsule_gap(P, (0, 1, 0.03), (2, 3, 0.04))[0]
if abs(gap - 0.03) > 1e-9:
    fails.append("capsule gap %.4f, want 0.03" % gap)

# A's hand on B's head; A's arm comes out 40% shorter. Kept joint by joint the hand falls short of the head; the
# mesh keeps it there, at A's new arm length, with A's foot on the floor.
F = 3
A = [[0, 0, 0], [0, 0.9, 0], [0, 1.5, 0.02], [0.25, 1.4, 0.08], [0.52, 1.6, 0.0]]
B = [[0.62, 0, 0.03], [0.62, 0.9, 0], [0.6, 1.5, -0.03], [0.6, 1.62, -0.02], [0.75, 1.3, 0.1], [0.7, 1.05, 0.15]]
src = np.tile(np.array(A + B, float), (F, 1, 1))
bones = [(0, 1), (1, 2), (2, 3), (3, 4), (5, 6), (6, 7), (7, 8), (7, 9), (9, 10)]
l_src = np.array([np.linalg.norm(src[0, c] - src[0, p]) for p, c in bones])
l_our = l_src.copy()
l_our[2:4] *= 0.6
V = im.solve(src, bones, l_src, l_our, [0, 5], [], set(), steps=10, log=quiet)   # the paper's 10: a 40% shrink is
# far past any clip's (in 5 it lands 11.7 mm off; the real clips are held by LENGTH_TOL)
err = max(np.abs(np.linalg.norm(V[:, c] - V[:, p], axis=1) - l_our[e]).max() for e, (p, c) in enumerate(bones))
if err > 0.01:             # linearised once per step, as the paper: a 40% shrink settles within a few mm
    fails.append("bone lengths off by %.1f mm after the morph" % (1000 * err))
if np.abs(V[:, [0, 5], 1] - src[:, [0, 5], 1]).max() > 1e-6:
    fails.append("a foot left its height")
elbow = src[0, 2] + (src[0, 3] - src[0, 2]) * 0.6
naive = np.linalg.norm(elbow + (src[0, 4] - src[0, 3]) * 0.6 - src[0, 8])
kept = np.linalg.norm(V[0, 4] - V[0, 8])
was = np.linalg.norm(src[0, 4] - src[0, 8])
if not (naive > 0.15 and kept < was + 0.04):
    fails.append("hand to head: %.3f in the source, %.3f joint by joint, %.3f solved" % (was, naive, kept))

# A leans its top bone toward B, 4 cm clear in the source; ours is 1.6x as long. The capsules are pushed apart
# where our length drives them in; exempt, the pair overlaps.
cb = [(0, 1), (1, 2), (3, 4), (4, 5)]
caps = [(1, 2, 0.05), (4, 5, 0.05)]
C = np.tile(np.array([[0, 0, 0], [0, 1.0, 0.03], [0.12, 1.5, 0], [0.26, 0, 0.05], [0.26, 1.0, 0], [0.26, 2.0, 0.04]]),
            (F, 1, 1))
cl = np.array([np.linalg.norm(C[0, c] - C[0, p]) for p, c in cb])
co = cl.copy()
co[1] *= 1.6
pushed = im.capsule_gap(im.solve(C, cb, cl, co, [0, 3], caps, set(), log=quiet)[0], *caps)[0]
left = im.capsule_gap(im.solve(C, cb, cl, co, [0, 3], caps, {frozenset((0, 1))}, log=quiet)[0], *caps)[0]
if not (pushed > -0.005 and left < pushed - 0.008):
    fails.append("capsules not pushed apart: gap %.3f, %.3f exempt" % (pushed, left))
# Overlapping 2 cm in the source, same lengths: that contact is the scene's and is kept, not pushed to touching.
D = np.tile(np.array([[0, 0, 0], [0, 1.0, 0.02], [0, 2.0, 0], [0.1, 0, 0.05], [0.1, 1.0, 0.0], [0.1, 2.0, 0.04]]),
            (F, 1, 1))
dl = np.array([np.linalg.norm(D[0, c] - D[0, p]) for p, c in cb])
dcaps = [(1, 2, 0.06), (4, 5, 0.06)]
before = im.capsule_gap(D[0], *dcaps)[0]
kept = im.capsule_gap(im.solve(D, cb, dl, dl, [0, 3], dcaps, set(), log=quiet)[0], *dcaps)[0]
if not (before < -0.015 and abs(kept - before) < 0.002):
    fails.append("the source's own overlap moved: gap %.3f -> %.3f" % (before, kept))

# A tie (her opening on his penis root, opensex-port.md 9.7) holds two points at the offset it asks for, which the
# mesh alone does not: A's hand on B's point 8 at 2 cm, where the shrunken arm left it apart.
want = np.array([0.02, 0.0, 0.0])
Vtie = im.solve(src, bones, l_src, l_our, [0, 5], [], set(), steps=10, log=quiet, ties=[(4, 8)],
                tie_offset=lambda P: np.broadcast_to(want, (1, F, 3)))
untied, tied = (np.linalg.norm(X[:, 4] - X[:, 8] - want, axis=1).max() for X in (V, Vtie))
if not (untied > 0.03 and tied < untied / 3):
    fails.append("tie: hand %.3f m off the asked offset untied, %.3f tied" % (untied, tied))

# Nothing else holds the scene in x and z: point 0 follows the source in every frame.
pin = np.abs(V[:, 0][:, [0, 2]] - src[:, 0][:, [0, 2]]).max()
if pin > 1e-9:
    fails.append("point 0 left its source x/z by %.2e m" % pin)
# A foot on tiptoe: the ankle 15 cm over the toe, ours 14 cm long. Both heights held cannot hold (a squat's 2.6 m
# blow-up); with the ankle's height left free the foot keeps our length and the toe its floor.
T = np.tile(np.array([[0, 0.55, 0], [0, 0.15, 0.01], [0, 0.0, 0.03], [0.3, 0.9, 0], [0.3, 0.0, 0.1]], float), (4, 1, 1))
tb = [(0, 1), (1, 2), (3, 4)]
tl = np.array([np.linalg.norm(T[0, c] - T[0, p]) for p, c in tb])
to = tl.copy()
to[1] = 0.14
held = np.array([[False, True]] * 4)
H, _ = im.hard_rows(T, tb, [1, 2], tl, T, held)
if H.shape[0] != 4 * len(tb) + 4 + 2 * 4:
    fails.append("held mask: %d hard rows, want %d" % (H.shape[0], 4 * len(tb) + 4 + 2 * 4))
Vt = im.solve(T, tb, tl, to, [1, 2], [], set(), log=quiet, held=held)
terr = im.length_error(Vt, tb, to).max()
if not terr < 0.01 or abs(Vt[:, 2, 1]).max() > 1e-6:
    fails.append("tiptoe foot: length off %.3f m, toe off the floor %.3f m" % (terr, abs(Vt[:, 2, 1]).max()))

# A singular step raises: SuperLU hands back NaN, which a plain residual > tolerance would let through.
import scipy.sparse as spm  # noqa: E402
import warnings  # noqa: E402
gpu, im.nsa = im.nsa, None
try:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        im.KKT(None)(spm.csr_matrix(np.array([[1.0, 1.0], [1.0, 1.0]])), np.array([1.0, 2.0]))
    fails.append("a singular KKT step came back as a solution")
except RuntimeError:
    pass
finally:
    im.nsa = gpu

# A loose pair is not tied by the mesh: point 0's Laplacian row has no entry for point 4, its nearest neighbour.
L = np.tile(np.array([[0, 0, 0], [1.0, 0, 0], [0, 1.0, 0], [0, 0, 1.0], [0.05, 0.05, 0.05]]), (2, 1, 1))
ties = lambda loose: abs(im.mesh_rows(L, [], loose)[0].toarray()[0, 4 * 3]) > 0
if not ties(()) or ties([(4, 0)]):
    fails.append("loose pair: tied %s without it, %s with it" % (ties(()), ties([(4, 0)])))
# And the gap it leaves is filled: 0 sits between 1 and 6 inside a ring; loose, 1's row takes 6 in its place.
G = np.tile(np.array([[1.0, 0, 0], [0, 0, 0], [1, 1.2, 0], [1, -1.2, 0], [1, 0, 1.2], [1, 0, -1.2], [2, 0, 0]]),
            (2, 1, 1))
nb = lambda loose: set(np.flatnonzero(im.mesh_rows(G, [], loose)[0].toarray()[3, :7 * 3:3])) - {1}  # 1's x row
if 6 in nb(()) or nb([(0, 1), (0, 6)]) != {2, 3, 4, 5, 6}:
    fails.append("loose gap: 1's neighbours %s with 0 in the mesh, %s with 0 loose, want 2-6" % (
        sorted(nb(())), sorted(nb([(0, 1), (0, 6)]))))

# Three bodies, a woman, a man, a woman, ours 10% shorter: each solved to our lengths, his penis loose against both of
# them and nothing else, and the two women told apart in the log.
def figure(x0, scale, jit):
    p = {"Hips": (0, 1.0, 0), "Spine": (0, 1.1, 0), "Spine1": (0, 1.25, 0), "Spine3": (0, 1.4, 0),
         "Neck": (0, 1.55, 0), "Head": (0, 1.65, 0)}
    for s, x in (("Left", 1), ("Right", -1)):
        p.update({s + "UpLeg": (0.1 * x, 0.95, 0), s + "Leg": (0.1 * x, 0.5, 0.02), s + "Foot": (0.1 * x, 0.08, 0),
                  s + "ToeBase": (0.1 * x, 0.0, -0.12), s + "Shoulder": (0.05 * x, 1.45, 0),
                  s + "Arm": (0.18 * x, 1.45, 0), s + "ForeArm": (0.2 * x, 1.2, 0.03), s + "Hand": (0.22 * x, 0.95, 0),
                  s + "HandMiddle1": (0.23 * x, 0.87, -0.01)})
    return {n: np.array([x0 + scale * v[0], scale * v[1], scale * v[2]]) + jit[i] for i, (n, v) in enumerate(p.items())}


class Stick:
    def __init__(self, x0, male, F, rng):
        jit = rng.normal(0, 0.004, (len(im.JOINTS), 3))
        src, rest = figure(x0, 1.0, jit), figure(x0, 0.9, jit)
        self.male, self.idx = male, {n: i for i, n in enumerate(im.JOINTS)}
        self.tg = type("T", (), {"w_t": np.array([rest[n] for n in im.JOINTS]),
                                 "w_r": np.tile([0, 0, 0, 1.0], (len(im.JOINTS), 1))})()
        self.src_j = {n: np.tile(src[n] / im.UNIT, (F, 1)) for n in im.JOINTS}
        self.w_r = np.tile([0, 0, 0, 1.0], (len(im.JOINTS), F, 1))
        h = rest["Hips"]
        self.virt = {"front": rest["Head"] + [0, 0, -0.08], "groin": h + [0, -0.05, -0.08],
                     "palm_Left": rest["LeftHand"] + [0, 0, -0.02], "palm_Right": rest["RightHand"] + [0, 0, -0.02]}
        if male:
            self.virt.update(shaft=h + [0, -0.05, -0.12], tip=h + [0, -0.05, -0.25])


rng = np.random.default_rng(3)
cast = [Stick(0.0, False, 3, rng), Stick(0.6, True, 3, rng), Stick(1.2, False, 3, rng)]
seen = {}
orig_solve = im.solve
im.solve = lambda *a, **k: seen.update(k) or orig_solve(*a, **k)
try:
    out, sides, worst = im.adapt(cast, 3, {s: s.virt for s in cast}, steps=3, log=quiet)
finally:
    im.solve = orig_solve
m = [len(s.names) for s in sides]
if [o.shape for o in out] != [(3, k, 3) for k in m]:
    fails.append("three bodies: shapes %s, want %s" % ([o.shape for o in out], [(3, k, 3) for k in m]))
if worst[0] > 0.01:
    fails.append("three bodies: %s %.1f cm off its length" % (worst[2], 100 * worst[0]))
his = [m[0] + sides[1].names.index(p) for p in im.PENIS]
want = {(i, j) for i in his for j in list(range(m[0])) + list(range(m[0] + m[1], sum(m)))}
if set(seen.get("loose", ())) != want:
    fails.append("three bodies: %d loose pairs, want his penis on both women's %d" % (
        len(seen.get("loose", ())), len(want)))
if seen.get("names", [""])[0] != "her0 Hips" or im.labels([True, False]) != ["his", "her"]:
    fails.append("labels: %s first, a pair's %s" % (seen.get("names", [""])[0], im.labels([True, False])))

# No steps: the source back, and the solver closed without one ever made.
if not np.array_equal(im.solve(src, bones, l_src, l_our, [0, 5], [], set(), steps=0, log=quiet), src):
    fails.append("steps=0 changed the points")

for f in fails:
    print("FAIL", f)
print("test_interaction_mesh:", "FAILED" if fails else "ok")
sys.exit(1 if fails else 0)
