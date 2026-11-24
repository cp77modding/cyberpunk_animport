"""The interaction mesh solved in our rig's own pose: the unknowns are each actor's hips position and each joint's turn
per frame, and every point (joints, palm, lips, penis, Skyrim's skin points) is our skeleton posed. Bone lengths and
the pelvis's and chest's shape are ours by construction, so nothing turns points back into rotations afterwards
(interaction_mesh.to_rotations, whose mismatch bent his back -81/+74 deg). The goals are interaction_mesh's: the
source's Laplacian and acceleration, soft collisions, ties and touch pulls; the feet's heights, the first hips' x and
z and pins held exactly. Gauss-Newton, each round linearised at the current pose and solved with the hard rows.
Design: docs/design/opensex-port.md section 9.9.

  pair_contact.py with MESH=1 POSE=1
"""
import os
import time

import numpy as np
import scipy.sparse as spm
from scipy.sparse.linalg import spsolve

import interaction_mesh as im
import retarget_glb as rg

ROUNDS = 12          # Gauss-Newton rounds at most
STILL = 1e-4         # m: a round moving no point further than this ends the solve
SETTLED = 1e-4       # or one lowering the energy by less than this share of it
DAMP = 1e-6          # each unknown's own weight, relative to the mean diagonal: holds a turn nothing sees (a foot's twist)
# each joint held to its retarget turn, per rad^2 a frame: free, the solve folded the lower back to bring the groins
# together (cowgirl -64 deg against Skyrim's -10), since a bend cost it nothing and moving the hips did
W_TORSO = float(os.environ.get("W_TORSO", 10.0))   # 1 and 10 bent the same; 10 kept the blowjob's mouth 80% vs 66%
W_LIMB = float(os.environ.get("W_LIMB", 0.01))
TORSO = {"Hips", "Spine", "Spine1", "Spine3", "Neck"}


def qexp(w):
    """(..., 4) turn by the rotation vector w (..., 3)"""
    a = np.linalg.norm(w, axis=-1, keepdims=True)
    s = np.where(a > 1e-12, np.sin(a / 2) / np.maximum(a, 1e-12), 0.5)
    return np.concatenate([w * s, np.cos(a / 2)], -1)


def qlog(q):
    """(..., 3) the rotation vector of the turn q (..., 4), the short way round"""
    q = np.where(q[..., 3:] < 0, -q, q)
    s = np.linalg.norm(q[..., :3], axis=-1, keepdims=True)
    a = 2 * np.arctan2(s, q[..., 3:])
    return q[..., :3] * np.where(s > 1e-12, a / np.maximum(s, 1e-12), 2.0)


class Rig:
    """one actor's unknowns and points: which rig bone carries each point, which joints turn it"""

    def __init__(self, side, F):
        self.side, self.act, self.F = side, side.act, F
        sk, idx = self.act.tg.skel, self.act.idx
        self.sk = sk
        # a joint point is carried by its rig parent, a virtual point by its segment
        self.carrier = [sk.parent[idx[nm]] if nm not in side.virtual else idx[side.virtual[nm][0]] for nm in side.names]
        anc = lambda b: [b] + anc(sk.parent[b]) if b >= 0 else []
        hips = idx["Hips"]
        moved = set()
        for c in self.carrier:
            moved |= {b for b in anc(c) if b in {idx[j] for j in im.JOINTS}}
        self.joints = sorted(moved, key=sk.order.index)     # rig bones turned, each 3 unknowns after the hips' 3
        self.col = {b: 3 + 3 * i for i, b in enumerate(self.joints)}
        self.dof = 3 + 3 * len(self.joints)
        # each point's turning joints, the hips and below only (the root above them is never turned)
        self.turns = [[b for b in anc(c) if b in self.col] for c in self.carrier]
        self.hips, self.root = hips, sk.parent[hips]
        self.local = np.array([side.local[nm] if nm in side.virtual else np.zeros(3) for nm in side.names])
        self.is_virtual = np.array([nm in side.virtual for nm in side.names])
        self.at = np.array([idx[nm] if nm not in side.virtual else -1 for nm in side.names])
        self.rot0 = self.act.rot[:, :F].copy()     # the retarget's turns, what the stiffness holds each joint to
        self.stiff = {b: W_TORSO if sk.names[b] in TORSO else W_LIMB for b in self.joints}

    def drift(self):
        """{joint: (F, 3)} each joint's turn off the retarget, a world rotation vector, and its stiffness"""
        w_r, _ = self.sk.world_pose(self.act.rot[:, :self.F], self.act.tra[:, :self.F])
        out = {}
        for b, k in self.stiff.items():
            d = qlog(rg.qmul(self.act.rot[b, :self.F], rg.qinv(self.rot0[b])))   # in the parent's frame
            p = self.sk.parent[b]
            out[b] = (d if p < 0 else rg.qrot(w_r[p], d), k)
        return out

    def points(self):
        """(F, m, 3) every point on the current pose, and the rig's world (rotations, positions)"""
        a, F = self.act, self.F
        w_r, w_t = self.sk.world_pose(a.rot[:, :F], a.tra[:, :F])
        P = np.empty((F, len(self.carrier), 3))
        for i, c in enumerate(self.carrier):
            P[:, i] = (w_t[c] + rg.qrot(w_r[c], np.broadcast_to(self.local[i], (F, 3)))) if self.is_virtual[i] \
                else w_t[self.at[i]]
        return P, w_r, w_t

    def jacobian(self, P, w_t, m0, M, D, d0):
        """the (rows, cols, values) of d point / d unknown, every frame: rows in the scene's (F, M, 3) points, columns
        (F, D) unknowns; this actor's points start at m0, its unknowns at d0"""
        F = self.F
        R, C, W = [], [], []
        f = np.arange(F)
        for i, turns in enumerate(self.turns):
            row = lambda c: ((f * M + m0 + i) * 3 + c)
            for c in range(3):                                   # the hips' move moves every point
                R.append(row(c)); C.append(f * D + d0 + c); W.append(np.ones(F))
            for b in turns:
                d = P[:, i] - w_t[b]                             # a turn w moves the point by w x d = -[d]x w
                blk = ((None, d[:, 2], -d[:, 1]), (-d[:, 2], None, d[:, 0]), (d[:, 1], -d[:, 0], None))
                for r in range(3):
                    for c in range(3):
                        if blk[r][c] is not None:
                            R.append(row(r)); C.append(f * D + d0 + self.col[b] + c); W.append(blk[r][c])
        return np.concatenate(R), np.concatenate(C), np.concatenate(W)

    def apply(self, x):
        """the step x (F, dof) onto the pose: the hips moved, each joint turned about itself in the world"""
        a, F = self.act, self.F
        w_r, _ = self.sk.world_pose(a.rot[:, :F], a.tra[:, :F])
        a.tra[self.hips, :F] += x[:, :3] if self.root < 0 else rg.qrot(rg.qinv(w_r[self.root]), x[:, :3])
        for b, c in self.col.items():
            p = self.sk.parent[b]
            q = qexp(x[:, c:c + 3])                              # local' = inv(R_parent) exp(w) R_parent local
            a.rot[b, :F] = rg.qnorm(rg.qmul(rg.qmul(rg.qinv(w_r[p]), rg.qmul(q, w_r[p])), a.rot[b, :F]))


def pull_rows(V, pulls, n):
    """(rows, b): each touch's two skin points pulled back to their gap along the line between them, never pushed"""
    F, m, _ = V.shape
    sw = im.W_TOUCH ** 0.5
    R, C, W, B = [], [], [], []
    r = 0
    for ia, ib, _, _, gap, w in pulls:
        d = V[:, ia] - V[:, ib]
        dist = np.linalg.norm(d, axis=1)
        fr = np.where((w > 0) & (dist > gap))[0]
        if not len(fr):
            continue
        nrm, s = d[fr] / dist[fr, None], sw * np.sqrt(w[fr])
        rows = r + np.arange(len(fr))
        for j, sign in ((ia, 1.0), (ib, -1.0)):
            for c in range(3):
                R.append(rows); C.append((fr * m + j) * 3 + c); W.append(sign * s * nrm[:, c])
        B.append(s * gap[fr])
        r += len(fr)
    if not r:
        return None, None
    return spm.csr_matrix((np.concatenate(W), (np.concatenate(R), np.concatenate(C))), shape=(r, n)), np.concatenate(B)


def solve(acts, F, virt, log=print, skin=None, touch=(), pins=(), pin_to=None):
    """the clip's actors posed onto our bodies in place (act.rot, act.tra), refreshed; returns the scene's points
    [(F, m, 3) per actor] and its sides, as interaction_mesh.adapt's"""
    sc = im.scene(acts, F, virt, log, skin, touch)
    rigs = [Rig(side, F) for side in sc.sides]
    M = sc.offs[-1]
    n = F * M * 3
    d0 = list(np.cumsum([0] + [r.dof for r in rigs]))
    D = d0[-1]
    # ties hold the two points themselves: here put_back cannot undo them, as every point is the rig posed
    ties = [(sc.g(t, a), sc.g(s, b)) for t, a, s, b, _, _ in sc.pair]
    tie_w = np.array([im.W_TIE * p[5] for p in sc.pair]) if ties else None
    want = np.array([sc.src[:, i] - sc.src[:, j] for i, j in ties]) if ties else None
    pins = list(pins)
    # each body keeps its own shape (our rig on the retarget); only the bodies' relation is Skyrim's
    own = np.concatenate([r.points()[0] for r in rigs], 1)
    body = np.concatenate([np.full(len(s.names), k) for k, s in enumerate(sc.sides)])
    base, base_b = im.mesh_rows(sc.src, sc.bones, sc.loose, pins, own, body)
    AtA, Atb0 = base.T @ base, base.T @ base_b
    if ties:
        T = im.tie_rows(F, M, ties, tie_w)
        AtA, Atb0 = AtA + T.T @ T, Atb0 + T.T @ im.tie_b(want, tie_w)
    pairs = [(u, v) for u in range(len(sc.caps)) for v in range(u + 1, len(sc.caps))
             if not set(sc.caps[u][:2]) & set(sc.caps[v][:2]) and frozenset((u, v)) not in sc.exempt]
    caps = im.pair_caps(pairs, sc.caps)
    allow = np.minimum(im.pair_gaps(sc.src, *caps)[0], 0)
    side = im.pair_sides(sc.src, caps)
    pin_at = pin_to if pins else None

    def energy(V):
        """what the solve minimises, its soft rows re-read at V (collisions and pulls change with it)"""
        v = V.ravel()
        e = np.sum((base @ v - base_b) ** 2)
        if ties:
            e += np.sum((T @ v - im.tie_b(want, tie_w)) ** 2)
        C, cb, hits = im.collision_rows(V, caps, allow, side)
        if hits:
            e += np.sum((C @ v - cb) ** 2)
        U, ub = pull_rows(V, sc.pulls, n)
        if U is not None:
            e += np.sum((U @ v - ub) ** 2)
        for r in rigs:
            e += sum(k * np.sum(d ** 2) for d, k in r.drift().values())
        return e

    def stiffness(K, g):
        """each joint's pull back to its retarget turn, linearised: k |x_b + drift_b|^2 over the unknowns"""
        diag, rhs = np.zeros(F * D), np.zeros(F * D)
        f = np.arange(F)
        for s, r in enumerate(rigs):
            for b, (d, k) in r.drift().items():
                for c in range(3):
                    at = f * D + d0[s] + r.col[b] + c
                    diag[at] += k
                    rhs[at] -= k * d[:, c]
        return K + spm.diags(diag), g + rhs

    def broken(V):
        """how far V is off the hard rows (feet, first hips, pins), squared metres"""
        H, hb = im.hard_rows(V, [], sc.feet, np.zeros(0), sc.src, sc.held, pins, pin_at)
        return np.sum((H @ V.ravel() - hb) ** 2)

    posed_now = lambda: np.concatenate([r.points()[0] for r in rigs], 1)
    log("pose solve: %d actors, %d frames, %d points, %d unknowns a frame" % (len(rigs), F, M, D))
    for rnd in range(1, ROUNDS + 1):
        t0 = time.time()
        posed = [r.points() for r in rigs]
        V = np.concatenate([p[0] for p in posed], 1)
        parts = [r.jacobian(posed[s][0], posed[s][2], sc.offs[s], M, D, d0[s]) for s, r in enumerate(rigs)]
        G = spm.csr_matrix((np.concatenate([p[2] for p in parts]),
                            (np.concatenate([p[0] for p in parts]), np.concatenate([p[1] for p in parts]))),
                           shape=(n, F * D))
        Q, Qb = AtA, Atb0
        C, cb, hits = im.collision_rows(V, caps, allow, side)
        if hits:
            Q, Qb = Q + C.T @ C, Qb + C.T @ cb
        U, ub = pull_rows(V, sc.pulls, n)
        if U is not None:
            Q, Qb = Q + U.T @ U, Qb + U.T @ ub
        v = V.ravel()
        K = (G.T @ (Q @ G)).tocsc()
        g = G.T @ (Qb - Q @ v)
        K = K + spm.identity(F * D) * (DAMP * K.diagonal().mean())
        K, g = stiffness(K, g)
        K = K.tocsc()
        H, hb = im.hard_rows(V, [], sc.feet, np.zeros(0), sc.src, sc.held, pins, pin_at)
        HG = (H @ G).tocsr()
        keep = np.asarray(abs(HG).sum(1)).ravel() > 0
        HG, hr = HG[keep], (hb - H @ v)[keep]
        A = spm.bmat([[K, HG.T], [HG, None]]).tocsc()
        x = spsolve(A, np.r_[g, hr])[:F * D].reshape(F, D)
        if not np.isfinite(x).all():
            raise FloatingPointError("pose solve round %d: the KKT system is singular (conflicting hard rows?)" % rnd)
        # a step is taken only if it lowers the energy, else halved: the linearised collisions overshot, and from
        # round 5 the steps grew again (0.5 to 5.4 cm a round on 40 frames of holding arms)
        e0, keep_pose = energy(V), [(a.rot.copy(), a.tra.copy()) for a in acts]
        h0 = broken(V)
        scale = 1.0
        while True:
            for s, r in enumerate(rigs):
                r.apply(scale * x[:, d0[s]:d0[s + 1]])
            P = posed_now()
            e1, h1 = energy(P), broken(P)
            # the hard rows first: a step that meets them is kept even if the soft energy rises
            if h1 < h0 - STILL ** 2 or (h1 <= h0 + STILL ** 2 and e1 <= e0) or scale < 1e-3:
                break
            for a, (rr, tt) in zip(acts, keep_pose):
                a.rot[:], a.tra[:] = rr, tt
            scale /= 2
        moved = scale * np.abs((G @ x.ravel())).max()
        log("  round %2d: %d collisions, energy %.4g -> %.4g (step x%g), a point moved up to %.2f cm, %.1f s" % (
            rnd, hits, e0, e1, scale, 100 * moved, time.time() - t0))
        if e1 > e0 and h1 >= h0 - STILL ** 2:
            for a, (rr, tt) in zip(acts, keep_pose):
                a.rot[:], a.tra[:] = rr, tt
            log("  no step lowers the energy: stopped")
            break
        # settled only once the hard rows are met: a step meeting them may raise the energy, and is no reason to stop
        if moved < STILL or (h1 >= h0 - STILL ** 2 and e0 - e1 < SETTLED * e0):
            break
    for a in acts:
        a.refresh()
    V = np.concatenate([r.points()[0] for r in rigs], 1)
    return [V[:, sc.offs[s]:sc.offs[s + 1]] for s in range(sc.n)], sc.sides
