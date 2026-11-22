"""Contacts of a clip's two or more actors kept on our bodies: Ho, Komura, Tai 2010, "Spatial Relationship Preserving
Character Motion Adaptation", as written (Algorithm 1). The source is the Skyrim clip itself, in metres; each frame's
interaction mesh is a Delaunay over every skeleton's joints, end effectors and one virtual vertex per bone, kept fixed;
N_STEPS morph steps blend the bone lengths from Skyrim's to ours, each one solve of Eq. 11: Laplacian deformation, hard
bone lengths and foot heights, soft collisions (4.0), acceleration (W_ACC); then the segments re-oriented and the
virtual vertices put back. Design and results: docs/design/opensex-port.md section 9.6.

The paper ends at joint positions. Our rig's rest shape is not Skyrim's (the pelvis, the collarbones), so the way back
to rotations is ours: his pelvis takes only the turn the solve gave it, on top of the retarget's; every other segment
aims from our real joints at the solved points."""
import logging
import numpy as np
import scipy.sparse as spm
from scipy.sparse.linalg import spsolve
try:
    import nvmath.sparse.advanced as nsa
    from nvmath.bindings import cudss
except ImportError:
    nsa = None
from scipy.spatial import Delaunay
import retarget_glb as rg

UNIT = 0.0142875          # Skyrim units to metres
N_STEPS = 5               # the paper's 10 pulled her hips apart on 7 clips pressed together (wheelbarrow 4.7 cm); 5 solves all 627
W_ACC = 1.0               # w_delta, Eq. 10; the paper's 0.2 shook his pelvis 3 deg a frame under a cowgirl. More
                          # fights his hips held on Skyrim's thrust: standing bend-over, his hips-to-spine 0.7 cm off at 2, 2.3 at 5
W_COL = 4.0               # soft collision weight, section 5.1
W_TIE = 25.0              # her entry held at Skyrim's offset from his penis root: the Laplacian alone left it 5 cm up his body
MOUTHS = ("s_lips", "s_mouth")  # mesh_skin's mouth points: they ride the head, never aim it
KISS = (0.05, 0.08)      # m: Skyrim's lips this near his mouth tie the heads fully, past the second not at all
W_TIE_BACK = (5.0, 1.0, 0.0) # tried in turn when a bone breaks: from behind 25 stretched his hips-to-spine 2-3 cm, 1 held it
JOINTS = ["Hips", "Spine", "Spine1", "Spine3", "Neck", "Head"]
for _s in ("Left", "Right"):
    JOINTS += [_s + n for n in ("UpLeg", "Leg", "Foot", "ToeBase", "Shoulder", "Arm", "ForeArm", "Hand", "HandMiddle1")]
PARENT = {"Spine": "Hips", "Spine1": "Spine", "Spine3": "Spine1", "Neck": "Spine3", "Head": "Neck"}
for _s in ("Left", "Right"):
    PARENT.update({_s + "UpLeg": "Hips", _s + "Leg": _s + "UpLeg", _s + "Foot": _s + "Leg",
                   _s + "ToeBase": _s + "Foot", _s + "Shoulder": "Spine3", _s + "Arm": _s + "Shoulder",
                   _s + "ForeArm": _s + "Arm", _s + "Hand": _s + "ForeArm", _s + "HandMiddle1": _s + "Hand"})
BONES = [(p, c) for c, p in PARENT.items()]
FEET = [s + n for s in ("Left", "Right") for n in ("Foot", "ToeBase")]
RADIUS = {("Hips", "Spine"): 0.11, ("Spine", "Spine1"): 0.11, ("Spine1", "Spine3"): 0.11, ("Spine3", "Neck"): 0.10,
          ("Neck", "Head"): 0.05}
for _s in ("Left", "Right"):
    RADIUS.update({(_s + "UpLeg", _s + "Leg"): 0.065, (_s + "Leg", _s + "Foot"): 0.045,
                   (_s + "Foot", _s + "ToeBase"): 0.035, (_s + "Arm", _s + "ForeArm"): 0.04,
                   (_s + "ForeArm", _s + "Hand"): 0.03, (_s + "Hand", _s + "HandMiddle1"): 0.025})
HEAD_R, SHAFT_R = 0.08, 0.018
TORSO = [("Hips", "Spine"), ("Spine", "Spine1"), ("Spine1", "Spine3")]
THIGHS = [(s + "UpLeg", s + "Leg") for s in ("Left", "Right")]
HEAD = [("Neck", "Head"), ("Head", "v_Head")]
ANKLE_ROOM = 0.9          # an ankle's height is held while Skyrim's ankle-over-toe drop is under this share of our foot
LENGTH_TOL = 0.01         # m: a solved bone further than this off its length is a broken clip
PENIS = ("shaft", "tip")
HAND_TURN = np.radians(15)  # a hand's local turn off the retarget's: her fists by her own shoulders folded her wrists 70 deg
NECK_LEAN = np.radians(5)   # the neck off the chest past Skyrim's: reaching her head on to him leaned it 26 deg to Skyrim's 9
NECK_SMOOTH = 15            # frames the neck's turn back is averaged over (odd)


def unit(v):
    return v / np.maximum(np.linalg.norm(v, axis=-1, keepdims=True), 1e-9)


def qbetween(a, b):
    a, b = unit(a), unit(b)
    q = np.concatenate([np.cross(a, b), 1 + (a * b).sum(-1, keepdims=True)], -1)
    return q / np.linalg.norm(q, axis=-1, keepdims=True)


def m2q(m):
    """rotation matrices (..., 3, 3) to quaternions (..., 4) xyzw"""
    w = np.sqrt(np.maximum(1 + m[..., 0, 0] + m[..., 1, 1] + m[..., 2, 2], 1e-12)) / 2
    x = np.copysign(np.sqrt(np.maximum(1 + m[..., 0, 0] - m[..., 1, 1] - m[..., 2, 2], 0)) / 2, m[..., 2, 1] - m[..., 1, 2])
    y = np.copysign(np.sqrt(np.maximum(1 - m[..., 0, 0] + m[..., 1, 1] - m[..., 2, 2], 0)) / 2, m[..., 0, 2] - m[..., 2, 0])
    z = np.copysign(np.sqrt(np.maximum(1 - m[..., 0, 0] - m[..., 1, 1] + m[..., 2, 2], 0)) / 2, m[..., 1, 0] - m[..., 0, 1])
    return rg.qnorm(np.stack([x, y, z, w], -1))


def kabsch(a, b):
    """per frame, the rotation matrix R minimising sum |R a_k - b_k|^2; a, b (F, k, 3)"""
    U, _, Vt = np.linalg.svd(np.einsum("fki,fkj->fij", a, b))
    D = np.zeros((len(b), 3, 3))
    D[:, 0, 0] = D[:, 1, 1] = 1
    D[:, 2, 2] = np.sign(np.linalg.det(np.einsum("fji,fkj->fik", Vt, U)))
    return np.einsum("fji,fjk,flk->fil", Vt, D, U)


def seg_closest(p0, p1, q0, q1):
    """(s, t) of the closest points between segments p0p1 and q0q1; any leading shape, last axis xyz"""
    d1, d2, r = p1 - p0, q1 - q0, p0 - q0
    a, e, f = (d1 * d1).sum(-1), (d2 * d2).sum(-1), (d2 * r).sum(-1)
    c, b = (d1 * r).sum(-1), (d1 * d2).sum(-1)
    den = a * e - b * b
    sa, se, sd = np.maximum(a, 1e-12), np.maximum(e, 1e-12), np.where(den > 1e-12, den, 1.0)
    s = np.where(den > 1e-12, np.clip((b * f - c * e) / sd, 0, 1), 0.0)
    t = np.where(e > 1e-12, (b * s + f) / se, 0.0)
    s = np.where(t < 0, np.where(a > 1e-12, np.clip(-c / sa, 0, 1), 0.0),
                 np.where(t > 1, np.where(a > 1e-12, np.clip((b - c) / sa, 0, 1), 0.0), s))
    return s, np.clip(t, 0, 1)


def capsule_gap(P, cap_a, cap_b):
    """(gap, s, t): surface distance between two capsules (i, j, r) on points P (..., m, 3), negative on overlap"""
    (a0, a1, ra), (b0, b1, rb) = cap_a, cap_b
    s, t = seg_closest(P[..., a0, :], P[..., a1, :], P[..., b0, :], P[..., b1, :])
    pa = P[..., a0, :] + s[..., None] * (P[..., a1, :] - P[..., a0, :])
    pb = P[..., b0, :] + t[..., None] * (P[..., b1, :] - P[..., b0, :])
    return np.linalg.norm(pa - pb, axis=-1) - ra - rb, s, t


def pair_caps(pairs, capsules):
    """the two capsules of every pair as (i, j, r) arrays, for capsule_gap over every pair at once"""
    c = [np.array([capsules[p[w]][k] for p in pairs], dtype=float if k == 2 else np.int64).reshape(-1)
         for w in (0, 1) for k in range(3)]
    return tuple(c[:3]), tuple(c[3:])


def pair_gaps(P, ca, cb, chunk=256):
    """capsule_gap of every pair, (..., pairs) each, a chunk of pairs at a time to bound the temporaries"""
    out = [capsule_gap(P, tuple(x[k:k + chunk] for x in ca), tuple(x[k:k + chunk] for x in cb))
           for k in range(0, max(len(ca[0]), 1), chunk)]
    return tuple(np.concatenate([o[i] for o in out], -1) for i in range(3))


def current_gpu():
    try:
        import cupy
    except ImportError:         # nvmath without cupy: one card
        return 0
    return cupy.cuda.Device().id


def csr_keys(K):
    """row * ncols + col of every stored entry, in CSR order"""
    return np.repeat(np.arange(K.shape[0], dtype=np.int64), np.diff(K.indptr)) * K.shape[1] + K.indices


REFINE = 12        # solves at most refining a float32 factor's answer in float64
REFINE_TO = 1e-12  # residual where refining stops; the answer then matches a float64 factor's to ~1e-11


class KKT:
    """K x = b for every morph step. With nvmath, cuDSS on the GPU over one fixed sparsity pattern: the plan (ordering
    and matching, the CPU half of a solve) runs once and each step only refactorizes, in float32 (1.0 s to 0.29 on an
    RTX 4080: consumer and A-series cards run float64 at 1/32-1/64), the answer refined in float64. Else SuperLU on
    one CPU core"""

    def __init__(self, pattern):
        self.gpu = nsa is not None
        if self.gpu:
            self.P = pattern.tocsr()
            self.P.sum_duplicates(); self.P.sort_indices()
            self.keys, self.s, self.at = csr_keys(self.P), None, {}

    def place(self, rows, cols, key=None):
        """where entries (rows, cols) sit in the planned pattern; a block under key whose entries are the ones it had
        last step (the mesh rows, the hard rows) reuses its lookup: 4.8M binary searches a step were 1 s a clip"""
        hit = self.at.get(key)
        if hit is not None and np.array_equal(hit[0], rows) and np.array_equal(hit[1], cols):
            return hit[2]
        k = rows.astype(np.int64) * self.P.shape[1] + cols
        pos = np.searchsorted(self.keys, k)
        if (pos >= len(self.keys)).any() or (self.keys[np.minimum(pos, len(self.keys) - 1)] != k).any():
            raise RuntimeError("KKT entry outside the planned pattern")
        if key is not None:
            self.at[key] = (rows, cols, pos)
        return pos

    def blocks(self, AtA, extra, H, b):
        """K = [[AtA + extra, H.T], [H, 0]] x = b, K put straight into the planned pattern; AtA's and H's entries repeat
        step to step, extra's (the collisions, None for none) do not"""
        if not self.gpu:
            return self(spm.bmat([[AtA if extra is None else AtA + extra, H.T], [H, None]]), b)
        n = AtA.shape[0]
        if self.at.get("mesh", (None,))[0] is not AtA:     # the same matrix every step: placed once
            M = AtA.tocsr()
            M.sum_duplicates()
            whole = np.zeros(len(self.keys))
            whole[self.place(np.repeat(np.arange(n), np.diff(M.indptr)), M.indices)] = M.data
            self.at["mesh"] = (AtA, whole)
        data = self.at["mesh"][1].copy()
        if extra is not None:
            M = extra.tocsr()
            M.sum_duplicates()
            data[self.place(np.repeat(np.arange(n), np.diff(M.indptr)), M.indices)] += M.data
        H = H.tocsr()
        H.sum_duplicates()
        r = np.repeat(np.arange(H.shape[0]), np.diff(H.indptr)) + n
        data[self.place(np.r_[r, H.indices], np.r_[H.indices, r], "hard")] = np.r_[H.data, H.data]
        return self(spm.csr_matrix((data, self.P.indices, self.P.indptr), shape=self.P.shape), b, placed=True)

    def __call__(self, K, b, placed=False):
        """placed: K is already in the planned pattern (blocks)"""
        if not self.gpu:
            x = spsolve(K.tocsc(), b)
            res = np.abs(K @ x - b).max()
            if not res <= 1e-8:            # a singular K comes back NaN, and NaN > tol is False
                raise RuntimeError("SuperLU residual %.1e" % res)
            return x
        if placed:
            A = spm.csr_matrix((K.data.astype(np.float32), self.P.indices, self.P.indptr), shape=self.P.shape)
        else:
            K = K.tocsr()
            K.sum_duplicates(); K.sort_indices()
            A = spm.csr_matrix((np.zeros(len(self.keys), np.float32), self.P.indices, self.P.indptr), shape=self.P.shape)
            A.data[self.place(np.repeat(np.arange(K.shape[0]), np.diff(K.indptr)), K.indices)] = K.data
        if self.s is None:
            # no multithreading_lib: cuDSS's OpenMP layer (cudss_mtlayer_vcomp) crashes the test's many small solves
            quiet = logging.getLogger("interaction_mesh.cudss")     # it warns on every reset, and we refactorize
            quiet.setLevel(logging.ERROR)
            # the card this process uses (pair_batch.pick_gpu): host operands otherwise go to card 0
            self.s = nsa.DirectSolver(A, b.astype(np.float32), options=nsa.DirectSolverOptions(logger=quiet),
                                      execution=nsa.ExecutionCUDA(device_id=current_gpu()))
            # the KKT block has a zero diagonal: without matching cuDSS's static pivots leave a 5e-2 residual
            self.s.plan_config.matching_algorithm = cudss.MatchingAlg.MAX_DIAG_PRODUCT
            self.s.solution_config.ir_num_steps = 0
            self.s.plan()
        else:
            self.s.reset_operands(a=A)
        self.s.factorize()
        x, r = np.zeros_like(b), b.copy()
        res = was = np.inf
        for _ in range(REFINE):
            self.s.reset_operands(b=r.astype(np.float32))
            x += self.s.solve().astype(np.float64)
            r = b - K @ x
            res, was = np.abs(r).max(), res
            if res <= REFINE_TO or res >= was:
                break
        if res <= 1e-8:
            return x
        # pivots fixed at the plan can go bad on a later step's values (a standing bend-over, 0.4); SuperLU pivots afresh
        K = K.copy()
        K.eliminate_zeros()         # a placed K stores the whole pattern
        x = spsolve(K.tocsc(), b)
        cpu = np.abs(K @ x - b).max()
        logging.getLogger("interaction_mesh").warning("cuDSS residual %.1e, this step on SuperLU: %.1e", res, cpu)
        if not cpu <= 1e-8:
            raise RuntimeError("cuDSS residual %.1e, SuperLU %.1e" % (res, cpu))
        return x

    def close(self):
        if self.gpu and self.s is not None:
            self.s.free()


def kkt_pattern(base, H, pairs, capsules, F, m):
    """every entry a step's KKT matrix can hold: the Laplacian and acceleration, every collision pair's four points
    coupled within a frame, and the hard rows, whose pattern never changes"""
    vp = set()
    for u, v in pairs:
        pts = {capsules[u][0], capsules[u][1], capsules[v][0], capsules[v][1]}
        vp |= {(i, j) for i in pts for j in pts}
    vp = np.array(sorted(vp), dtype=np.int64).reshape(-1, 2)
    f = np.arange(F)[:, None, None, None]
    c, d = np.meshgrid(np.arange(3), np.arange(3), indexing="ij")
    r = ((f * m + vp[None, :, 0, None, None]) * 3 + c).ravel()
    q = ((f * m + vp[None, :, 1, None, None]) * 3 + d).ravel()
    n = F * m * 3
    one = lambda M: spm.csr_matrix((np.ones(M.nnz), M.indices, M.indptr), shape=M.shape)
    AA = one(abs(base).T.tocsr() @ abs(base)) + spm.csr_matrix((np.ones(len(r)), (r, q)), shape=(n, n))
    Hp = one(H.tocsr())
    return spm.bmat([[AA, Hp.T], [Hp, None]])


TET_EDGES = np.array([(a, b) for a in range(4) for b in range(4) if a != b])


def tet_edges(t):
    """every (i, j) edge of the tetrahedra t, both ways"""
    return np.stack([t[:, TET_EDGES[:, 0]].ravel(), t[:, TET_EDGES[:, 1]].ravel()], 1)


def mesh_rows(src, bones, loose=()):
    """(rows, b): the Laplacian of the source's Delaunay mesh, Eq. 3, bone neighbours and loose (i, j) pairs left out
    (section 5.1), j's gap filled from the mesh without the i's; then acceleration, Eq. 4, not on the end frames.
    A row's entries go in the order the solver sums them"""
    F, m, _ = src.shape
    skip = np.zeros((m, m), bool)
    for i, j in list(bones) + list(loose):
        skip[i, j] = skip[j, i] = True
    keep = np.setdiff1d(np.arange(m), [i for i, _ in loose])
    fill = np.zeros(m, bool)
    fill[[j for _, j in loose]] = True
    R, C, W, B = [], [], [], []
    r = 0
    for f in range(F):
        P = src[f]
        e = tet_edges(Delaunay(P).simplices)
        if len(keep) < m:
            g = keep[tet_edges(Delaunay(P[keep]).simplices)]
            e = np.concatenate([e, g[fill[g[:, 0]]]])
        # unique (i, j) in (i, j) order, as np.unique(axis=0) gave them: a mark per pair, m is a few hundred points
        mark = np.zeros((m, m), bool)
        mark[e[:, 0], e[:, 1]] = True
        e = np.argwhere(mark & ~skip)
        if not len(e):
            continue
        i, j = e[:, 0], e[:, 1]
        own, start = np.unique(i, return_index=True)
        q = np.searchsorted(own, i)
        w = 1 / np.maximum(np.linalg.norm(P[j] - P[i], axis=1), 1e-6)
        w /= np.add.reduceat(w, start)[q]
        delta = P[own] - np.add.reduceat(w[:, None] * P[j], start)
        for c in range(3):
            R += [r + 3 * np.arange(len(own)) + c, r + 3 * q + c]
            C += [(f * m + own) * 3 + c, (f * m + j) * 3 + c]
            W += [np.ones(len(own)), -w]
        B.append(delta.ravel())
        r += 3 * len(own)
    sa = W_ACC ** 0.5
    k = max(F - 2, 0) * m * 3
    fi, ii, cc = (g.ravel() for g in np.meshgrid(np.arange(1, F - 1), np.arange(m), np.arange(3), indexing="ij"))
    for df, v in ((-1, 1.0), (0, -2.0), (1, 1.0)):
        R.append(r + np.arange(k)); C.append(((fi + df) * m + ii) * 3 + cc); W.append(np.full(k, sa * v))
    B.append(np.zeros(k))
    r += k
    return spm.csr_matrix((np.concatenate(W), (np.concatenate(R), np.concatenate(C))), shape=(r, F * m * 3)), \
        np.concatenate(B)


def hard_rows(V, bones, feet, l, src, held=None):
    """(H, b): bone lengths linearised at the current V (Eq. 5); the feet's source heights (section 6) in the frames
    held (F, len(feet)) marks, every frame when None; point 0's x and z in every frame"""
    F, m, _ = V.shape
    nb = len(bones)
    p, c = np.array([b[0] for b in bones]), np.array([b[1] for b in bones])
    d = unit(V[:, c] - V[:, p])                                              # (F, nb, 3)
    f = np.arange(F)[:, None, None]
    k = np.arange(3)[None, None, :]
    row = np.broadcast_to((f * nb + np.arange(nb)[None, :, None]), (F, nb, 3))
    rows = np.stack([row, row], -1)
    cols = np.stack([(f * m + c[None, :, None]) * 3 + k, (f * m + p[None, :, None]) * 3 + k], -1)
    vals = np.stack([d, -d], -1)
    ft = np.array(feet, dtype=np.int64)
    hf, hk = np.nonzero(np.ones((F, len(ft)), bool) if held is None else held)
    frow = F * nb + np.arange(len(hf))
    fcol = (hf * m + ft[hk]) * 3 + 1
    # nothing else holds the scene in x and z: an offset or a drift costs no energy, and solvers (cuDSS run to run)
    # picked different ones, 1 cm apart. Point 0, his hips, follows the source in every frame: held only at the ends
    # her riding dragged him lying still 3.6 cm. Height stays free, as his legs are ours
    ends = range(F)
    arow = F * nb + len(hf) + np.arange(2 * len(ends))
    acol = np.array([f * m * 3 + ax for f in ends for ax in (0, 2)])
    ab = [src[f, 0, ax] for f in ends for ax in (0, 2)]
    H = spm.csr_matrix((np.r_[vals.ravel(), np.ones(len(frow) + len(acol))],
                        (np.r_[rows.ravel(), frow, arow], np.r_[cols.ravel(), fcol, acol])),
                       shape=(F * nb + len(hf) + len(ab), F * m * 3))
    hb = np.r_[np.broadcast_to(l, (F, nb)).ravel(), src[hf, ft[hk], 1], ab]
    return H, hb


def tie_rows(F, m, ties, w):
    """rows weighting V_i - V_j for each (i, j) in ties by w (ties, F), frame by frame; tie_b gives their targets"""
    st = np.sqrt(w)
    R, C, W = [], [], []
    for k, (i, j) in enumerate(ties):
        for c in range(3):
            rows = (k * 3 + c) * F + np.arange(F)
            R += [rows, rows]
            C += [(np.arange(F) * m + i) * 3 + c, (np.arange(F) * m + j) * 3 + c]
            W += [st[k], -st[k]]
    return spm.csr_matrix((np.concatenate(W), (np.concatenate(R), np.concatenate(C))), shape=(3 * F * len(ties), F * m * 3))


def tie_b(offset, w):
    """tie_rows' targets from offset (ties, F, 3), the wanted V_i - V_j, weighted by w (ties, F)"""
    return (np.sqrt(w)[:, None, :] * np.transpose(offset, (0, 2, 1))).ravel()


def length_error(V, bones, l):
    """(F, bones) |length - l| of every bone in every frame"""
    p, c = np.array([b[0] for b in bones]), np.array([b[1] for b in bones])
    return np.abs(np.linalg.norm(V[:, c] - V[:, p], axis=-1) - l)


def solve(src, bones, l_src, l_our, feet, capsules, exempt, after_step=None, steps=N_STEPS, log=print, held=None,
          names=None, loose=(), ties=(), tie_offset=None, tie_weight=None):
    """the paper's morph: src (F, m, 3) source points; bones [(i, j)] with lengths l_src -> l_our; feet, the points
    whose height stays the source's in the frames held (F, len(feet)) marks, all when None; capsules [(i, j, r)];
    exempt, capsule index pairs never pushed apart (a pair sharing a point never is); after_step(V) puts the virtual
    vertices back, in place; names label the log; loose, point pairs the mesh does not tie; ties, joint pairs whose
    difference tie_offset(V) -> (ties, F, 3) wants, re-read each step from the current turn, weighted by tie_weight
    (ties, F), W_TIE when None. Returns V (F, m, 3)"""
    F, m, _ = src.shape
    if ties and tie_weight is None:
        tie_weight = np.full((len(ties), F), W_TIE)
    base, base_b = mesh_rows(src, bones, loose)
    T = tie_rows(F, m, ties, tie_weight) if ties and tie_weight.max() > 0 else None
    pairs = [(u, v) for u in range(len(capsules)) for v in range(u + 1, len(capsules))
             if not set(capsules[u][:2]) & set(capsules[v][:2]) and frozenset((u, v)) not in exempt]
    V = src.copy()
    caps = pair_caps(pairs, capsules)
    # contact the source already has is the scene's: our capsules are rough, so skin on skin (her hands round his
    # neck, her thighs on his) reads as overlap, and pushing it apart broke her hip bones by 4.4 cm in a cowgirl.
    # A pair is pushed only past the source's own overlap in that frame
    allow = np.minimum(pair_gaps(src, *caps)[0], 0)
    pattern = base if T is None else spm.vstack([base, T]).tocsr()
    kkt = KKT(kkt_pattern(pattern, hard_rows(V, bones, feet, l_src, src, held)[0], pairs, capsules, F, m))
    mesh = (base.T @ base, base.T @ base_b)     # the Laplacian and acceleration rows never change across steps
    if T is not None:
        mesh = (mesh[0] + T.T @ T, mesh[1])
    try:                        # nvmath's solver frees its GPU memory only on close: a batch worker runs many clips
        for step in range(1, steps + 1):
            now = mesh if T is None else (mesh[0], mesh[1] + T.T @ tie_b(tie_offset(V), tie_weight))
            V, hits = morph_step(V, step / steps, kkt, now, caps, src, bones, l_src, l_our, feet, held, allow)
            if after_step:
                after_step(V)
            err = length_error(V, bones, (1 - step / steps) * l_src + step / steps * l_our)
            f, e = np.unravel_index(err.argmax(), err.shape)
            log("  morph step %2d: lengths %3d%% of the way, worst length error %.1f cm (frame %d, %s), %d collisions"
                % (step, 100 * step / steps, 100 * err.max(), f, bone_label(bones[e], names), hits))
    finally:
        kkt.close()
    return V


def bone_label(bone, names):
    return "%s->%s" % (names[bone[0]], names[bone[1]]) if names else "%d->%d" % bone


def morph_step(V, a, kkt, mesh, caps, src, bones, l_src, l_our, feet, held=None, allow=None):
    """one step of Algorithm 1: soft collisions from the current V (Eq. 7, all frames and pairs at once), lengths a of
    the way; mesh is (base.T base, base.T base_b), caps pair_caps' arrays; allow (F, pairs) is how far each pair may
    overlap in each frame (<= 0), none when None. Returns (V, collision rows)"""
    F, m, _ = V.shape
    n = F * m * 3
    sc = W_COL ** 0.5
    gap, s, t = pair_gaps(V, *caps)
    room = np.zeros_like(gap) if allow is None else allow
    k, fr = np.nonzero((gap < room).T)          # pair by pair, as the rows always went
    hits = len(k)
    AtA, Atb = mesh
    CtC = None
    if hits:
        (a0, a1, ra), (b0, b1, rb) = ((x[k] for x in c) for c in caps)
        s, t = s[fr, k][:, None], t[fr, k][:, None]
        nrm = unit(V[fr, a0] + s * (V[fr, a1] - V[fr, a0]) - V[fr, b0] - t * (V[fr, b1] - V[fr, b0]))
        crow, ccol, cval = [], [], []
        for idx, wgt in ((a0, 1 - s), (a1, s), (b0, -(1 - t)), (b1, -t)):
            for c in range(3):
                crow.append(np.arange(hits)); ccol.append((fr * m + idx) * 3 + c); cval.append(sc * wgt[:, 0] * nrm[:, c])
        C = spm.csr_matrix((np.concatenate(cval), (np.concatenate(crow), np.concatenate(ccol))), shape=(hits, n))
        CtC, Atb = C.T @ C, Atb + C.T @ (sc * (ra + rb + room[fr, k]))
    H, hb = hard_rows(V, bones, feet, (1 - a) * l_src + a * l_our, src, held)
    return kkt.blocks(AtA, CtC, H, np.r_[Atb, hb])[:n].reshape(F, m, 3), hits


class Side:
    """one actor's points (joints, then virtual vertices, each riding one segment); act is pair_contact's Actor"""

    def __init__(self, act, F, virt, penis, skin=None):
        self.act, self.F = act, F
        skin = skin or {}
        rest_t, rest_r = act.tg.w_t, act.tg.w_r
        k = lambda n: act.idx[n]
        # one virtual vertex per bounding volume, on its surface; the head's is the mouth, the hand's the palm
        self.virtual = {"v_" + a: (a, (rest_t[k(a)] + rest_t[k(c)]) / 2 + np.array([0, 0, -r]))
                        for (a, c), r in RADIUS.items()}
        self.virtual["v_Head"] = ("Head", virt["front"])
        for s in ("Left", "Right"):
            self.virtual["v_" + s + "Hand"] = (s + "Hand", virt["palm_" + s])
        self.virtual["v_Hips"] = ("Hips", virt["groin"])
        if penis:               # an object fixed on the pelvis
            for n in PENIS:
                self.virtual[n] = ("Hips", virt[n])
        for n, (seg, p, _) in skin.items():     # skin points whose source is Skyrim's own skin (mesh_skin.py)
            self.virtual[n] = (seg, p)
        self.local = {n: rg.qrot(rg.qinv(rest_r[k(seg)]), p - rest_t[k(seg)]) for n, (seg, p) in self.virtual.items()}
        self.names = JOINTS + list(self.virtual)
        src = {n: act.src_j[n][:F] * UNIT for n in JOINTS}
        for n, (seg, _) in self.virtual.items():   # turned as the retarget turns its segment
            src[n] = src[seg] + rg.qrot(act.w_r[k(seg), :F], np.broadcast_to(self.local[n], (F, 3)))
        for n, (_, _, s) in skin.items():
            src[n] = s[:F]
        self.src = np.stack([src[n] for n in self.names], 1)
        self.l_src = np.array([np.median(np.linalg.norm(src[c] - src[p], axis=1)) for p, c in BONES])
        self.l_our = np.array([np.linalg.norm(rest_t[k(c)] - rest_t[k(p)]) for p, c in BONES])
        self.refs = {}          # a segment's points: its child joints and its virtual vertices
        for j in JOINTS:
            # a mouth beside the face point gave the head two near-parallel aims, whose roll is free: it spun 180 deg
            tgt = [c for c, p in PARENT.items() if p == j] + [n for n, (seg, _) in self.virtual.items()
                                                               if seg == j and n not in MOUTHS]
            if tgt:
                self.refs[j] = tgt
        self.capsules = [(a, c, r) for (a, c), r in RADIUS.items()] + [("Head", "v_Head", HEAD_R)]
        if penis:
            self.capsules.append(PENIS + (SHAFT_R,))
        # volumes of one body that overlap at rest are that body, not a penetration
        at = {j: rest_t[k(j)] for j in JOINTS}
        at.update({n: p for n, (_, p) in self.virtual.items()})
        ix = {n: i for i, n in enumerate(at)}
        pts = np.array(list(at.values()))
        caps = [(ix[a], ix[b], r) for a, b, r in self.capsules]
        self.rest_overlap = {frozenset((u, v)) for u in range(len(caps)) for v in range(u + 1, len(caps))
                             if capsule_gap(pts, caps[u], caps[v])[0] < 0}

    def orient(self, P):
        """each segment's world rotation: its turn from the source to the solved points P, on the retarget's turn"""
        out = {}
        for j, tgt in self.refs.items():
            ij = self.names.index(j)
            a = unit(np.stack([self.src[:, self.names.index(t)] - self.src[:, ij] for t in tgt], 1))
            b = unit(np.stack([P[:, self.names.index(t)] - P[:, ij] for t in tgt], 1))
            dq = qbetween(a[:, 0], b[:, 0]) if len(tgt) == 1 else m2q(kabsch(a, b))
            out[j] = rg.qnorm(rg.qmul(dq, self.act.w_r[self.act.idx[j], :self.F]))
        return out

    def put_back(self, P):
        """the virtual vertices back on their segments (Algorithm 1, last line)"""
        rot = self.orient(P)
        for n, (seg, _) in self.virtual.items():
            P[:, self.names.index(n)] = P[:, self.names.index(seg)] + rg.qrot(
                rot[seg], np.broadcast_to(self.local[n], (self.F, 3)))


def labels(males):
    """each actor's name in the log: his / her, numbered only where two share one"""
    who = ["his" if m else "her" for m in males]
    return [w + ("%d" % i if who.count(w) > 1 else "") for i, w in enumerate(who)]


def adapt(acts, F, virt, steps=N_STEPS, log=print, skin=None):
    """a clip's actors' points solved together onto our bodies, a man's with his penis (act.male): ([(F, m, 3) per
    actor], sides, (worst length error m, its frame, its bone)). skin: {act: {name: (segment, our bind point, Skyrim's
    (F, 3))}}, extra points from mesh_skin.py"""
    sides = [Side(a, F, virt[a], a.male, (skin or {}).get(a)) for a in acts]
    n = len(sides)
    offs = list(np.cumsum([0] + [len(s.names) for s in sides]))
    g = lambda s, name: offs[s] + sides[s].names.index(name)
    bones = [(g(s, p), g(s, c)) for s in range(n) for p, c in BONES]
    caps, owner = [], []
    for s in range(n):
        caps += [(g(s, a), g(s, b), r) for a, b, r in sides[s].capsules]
        owner += [(s, (a, b)) for a, b, _ in sides[s].capsules]
    base = list(np.cumsum([0] + [len(s.capsules) for s in sides]))
    exempt = {frozenset((base[s] + u, base[s] + v)) for s in range(n) for u, v in map(tuple, sides[s].rest_overlap)}
    for u in range(len(caps)):  # his penis's penetrations are the scene's, as the paper's sword: never pushed
        if owner[u][1] == PENIS:
            exempt |= {frozenset((u, v)) for v in range(len(caps)) if v != u}
    # thighs on the other's torso, thighs or head are the scene's too: pushed out, a thigh can only swing its hip or tip
    # the pelvis, which broke her hip bone 4 cm in a cowgirl, her lower spine 1.7 cm on his lap and 5.5 cm on his face
    for u, (su, cu) in enumerate(owner):
        for v, (sv, cv) in enumerate(owner):
            if su != sv and cu in TORSO + THIGHS + HEAD and cv in THIGHS:
                exempt.add(frozenset((u, v)))

    def put_back(V):
        for s, side in enumerate(sides):
            P = V[:, offs[s]:offs[s] + len(side.names)]
            side.put_back(P)
            V[:, offs[s]:offs[s] + len(side.names)] = P

    src = np.concatenate([s.src for s in sides], 1)
    feet = [g(s, ft) for s in range(n) for ft in FEET]
    held = np.ones((F, len(feet)), bool)
    who_of = labels([a.male for a in acts])
    for s, who in enumerate(who_of):
        for side in ("Left", "Right"):
            # the toe on Skyrim's floor and the ankle at Skyrim's height ask for more drop than our foot is long
            # when the foot stands steep (a squat on tiptoe): the ankle's height goes free in those frames
            ankle, toe = g(s, side + "Foot"), g(s, side + "ToeBase")
            foot = sides[s].l_our[BONES.index((side + "Foot", side + "ToeBase"))]
            drop = np.abs(src[:, ankle, 1] - src[:, toe, 1])
            free = drop > ANKLE_ROOM * foot
            held[:, feet.index(ankle)] = ~free
            if free.any():
                log("  %s %sFoot height free in %d of %d frames: Skyrim's ankle up to %.1f cm over the toe, our foot "
                    "%.1f cm" % (who, side, free.sum(), F, 100 * drop.max(), 100 * foot))
    names = [w + " " + nm for w, side in zip(who_of, sides) for nm in side.names]
    # a penis inside a body sits a centimetre from its hip or spine joint and took 80% of its Laplacian: his pelvis
    # turning swung it 14 cm a step and tore her lower spine 6.5 cm (opensex-port.md 9.6). Loose on every other body
    loose = [(g(s, p), offs[t] + i) for s in range(n) if acts[s].male for p in PENIS
             for t in range(n) if t != s for i in range(len(sides[t].names))]
    l_src, l_our = np.concatenate([s.l_src for s in sides]), np.concatenate([s.l_our for s in sides])
    # her entry on his penis root as Skyrim has it (mesh_skin.py's points for a penetrative clip), held through the
    # pelvis joints: a tie on the skin points alone was undone by put_back, which carries them on the joints' turn
    # (actor, its point, actor, its point, the joint both ride, (F,) share of the weight)
    pair = [(t, "s_entry", s, "s_root", "Hips", np.ones(F)) for s in range(n) if "s_root" in sides[s].names
            for t in range(n) if t != s and "s_entry" in sides[t].names]
    # her lips on his mouth, the same way through the head joints, only while Skyrim's are near (a kiss)
    for t in range(n):
        for s in range(n):
            if t != s and "s_lips" in sides[t].names and "s_mouth" in sides[s].names:
                d = np.linalg.norm(sides[t].src[:, sides[t].names.index("s_lips")]
                                   - sides[s].src[:, sides[s].names.index("s_mouth")], axis=1)
                share = np.clip((KISS[1] - d) / (KISS[1] - KISS[0]), 0, 1)
                if share.any():
                    pair.append((t, "s_lips", s, "s_mouth", "Head", share))
                    log("  kiss: Skyrim's lips within %.0f cm of his mouth in %d of %d frames"
                        % (100 * KISS[0], (share == 1).sum(), F))
    ties = [(g(t, j), g(s, j)) for t, _, s, _, j, _ in pair]

    def tie_offset(V):
        out = []
        for t, a, s, b, j, _ in pair:
            # a head's turn read off the solve swung it 180 deg (its only points are the tied ones): the retarget's
            turn = [sides[x].orient(V[:, offs[x]:offs[x] + len(sides[x].names)])[j] if j == "Hips" else
                    sides[x].act.w_r[sides[x].act.idx[j], :F] for x in (t, s)]
            want = sides[t].src[:, sides[t].names.index(a)] - sides[s].src[:, sides[s].names.index(b)]
            out.append(want - rg.qrot(turn[0], np.broadcast_to(sides[t].local[a], (F, 3)))
                       + rg.qrot(turn[1], np.broadcast_to(sides[s].local[b], (F, 3))))
        return np.array(out)

    for w in (W_TIE,) + W_TIE_BACK if ties else (0.0,):
        if ties:
            log("  tied: %s, weight %.0f" % (", ".join("%s to %s" % (a, b) for _, a, _, b, _, _ in pair), w) if w else
                "  untied: every tie weight broke a bone")
        V = solve(src, bones, l_src, l_our, feet, caps, exempt, put_back, steps=steps, log=log, held=held,
                  names=names, loose=loose, ties=ties, tie_offset=tie_offset,
                  tie_weight=w * np.array([p[5] for p in pair]) if ties else None)
        err = length_error(V, bones, l_our)
        if err.max() <= LENGTH_TOL:
            break
    f, e = np.unravel_index(err.argmax(), err.shape)
    worst = (err.max(), int(f), bone_label(bones[e], names))
    return [V[:, offs[s]:offs[s + 1]] for s in range(n)], sides, worst


def neck_lean(t):
    """the neck's angle off the chest per frame, from joint points t[name] (F, 3)"""
    a, b = unit(t["Head"] - t["Neck"]), unit(t["Spine3"] - t["Spine1"])
    return np.arccos(np.clip((a * b).sum(1), -1, 1)), a, b


def hold_neck(side, act, F, log=print):
    """the neck leaned off the chest no further than Skyrim's lean and NECK_LEAN, turned back toward the chest at the
    neck's root; the head keeps its world turn, so the face looks where it did"""
    sk, k, kh = act.tg.skel, act.idx["Neck"], act.idx["Head"]
    want = neck_lean({n: side.src[:, side.names.index(n)] for n in ("Head", "Neck", "Spine3", "Spine1")})[0] + NECK_LEAN
    w_r, w_t = sk.world_pose(act.rot, act.tra)
    lean, a, b = neck_lean({n: w_t[act.idx[n], :F] for n in ("Head", "Neck", "Spine3", "Spine1")})
    over = lean > want
    if not over.any():
        return
    ax = np.cross(a, b)
    ok = over & (np.linalg.norm(ax, axis=1) > 1e-9)
    # the turn back smoothed over frames: each frame's own, from two noisy leans, shook the head 0.9 cm a frame
    rv = unit(ax) * np.where(ok, lean - want, 0.0)[:, None]
    box = np.ones(NECK_SMOOTH) / NECK_SMOOTH
    pad = np.pad(rv, ((NECK_SMOOTH // 2, NECK_SMOOTH // 2), (0, 0)), mode="edge")
    rv = np.stack([np.convolve(pad[:, c], box, mode="valid") for c in range(3)], 1)
    ang = np.linalg.norm(rv, axis=1, keepdims=True)
    q = np.concatenate([unit(rv) * np.sin(ang / 2), np.cos(ang / 2)], 1)
    head = w_r[kh, :F].copy()
    act.rot[k, :F] = rg.qnorm(rg.qmul(rg.qinv(w_r[sk.parent[k], :F]), rg.qmul(q, w_r[k, :F])))
    w_r, _ = sk.world_pose(act.rot, act.tra)
    act.rot[kh, :F] = rg.qnorm(rg.qmul(rg.qinv(w_r[sk.parent[kh], :F]), head))
    log("  %s neck leaned up to %.0f deg off the chest past Skyrim's, held to %.0f in %d of %d frames" % (
        act.row["clip"], np.degrees((lean - want + NECK_LEAN).max()), np.degrees(NECK_LEAN), over.sum(), F))


def to_rotations(side, P, log=print):
    """our rig posed on the solved points: torso segments by their turn, the hips placed, limbs aimed from our real
    joints at the solved points; bones the mesh lacks keep their local turn"""
    act, F = side.act, side.F
    sk = act.tg.skel
    rot0 = act.rot.copy()
    h, root = act.idx["Hips"], sk.parent[act.idx["Hips"]]
    w_r, w_t = sk.world_pose(act.rot, act.tra)
    act.tra[h, :F] = rg.qrot(rg.qinv(w_r[root, :F]), P[:, side.names.index("Hips")] - w_t[root, :F])
    # a pelvis with a penis keeps the source's turn: our hips-to-spine rest is 34-55 deg off Skyrim's and swung it
    # 10 cm off the mouth. Every other segment aims our joints at the solved points, or heads and hands slid off
    turned = PENIS[0] in side.virtual
    if turned:
        w_r, _ = sk.world_pose(act.rot, act.tra)
        act.rot[h, :F] = rg.qnorm(rg.qmul(rg.qinv(w_r[root, :F]), side.orient(P)["Hips"]))
    for j in sorted(side.refs, key=lambda n: sk.order.index(act.idx[n])):
        if j == "Hips" and turned:
            continue
        k = act.idx[j]
        w_r, w_t = sk.world_pose(act.rot, act.tra)
        # child joints only, keeping the retarget's twist: a surface vertex sits a few cm off the bone, so mm of solve
        # noise in it spun her upper arm up to 57 deg a frame. The hand keeps its palm and the head its face, well off it
        joints = [t for t in side.refs[j] if t not in side.virtual]
        refs = side.refs[j] if j.endswith("Hand") or not joints else joints
        cur = [rg.qrot(w_r[k, :F], np.broadcast_to(side.local[t], (F, 3))) if t in side.virtual
               else w_t[act.idx[t], :F] - w_t[k, :F] for t in refs]
        tgt = [P[:, side.names.index(t)] - w_t[k, :F] for t in refs]
        a, b = unit(np.stack(cur, 1)), unit(np.stack(tgt, 1))
        dq = qbetween(a[:, 0], b[:, 0]) if len(tgt) == 1 else m2q(kabsch(a, b))
        act.rot[k, :F] = rg.qnorm(rg.qmul(rg.qinv(w_r[sk.parent[k], :F]), rg.qmul(dq, w_r[k, :F])))
    hold_neck(side, act, F, log)
    # the mesh holds a hand to its own body's points too, and the wrist is the joint that gives: capped
    for s in ("Left", "Right"):
        k = act.idx[s + "Hand"]
        d = rg.qmul(rg.qinv(rot0[k, :F]), act.rot[k, :F])
        d = d * np.sign(d[:, 3:4] + 1e-12)
        ang = 2 * np.arccos(np.clip(d[:, 3], 0, 1))
        over = ang > HAND_TURN
        if over.any():
            ax = unit(d[over, :3])
            cap = np.concatenate([ax * np.sin(HAND_TURN / 2), np.full((over.sum(), 1), np.cos(HAND_TURN / 2))], 1)
            act.rot[k, :F][over] = rg.qnorm(rg.qmul(rot0[k, :F][over], cap))
            log("  %s %s turned off the retarget up to %.0f deg, held to %.0f in %d of %d frames" % (
                act.row["clip"], s + "Hand", np.degrees(ang.max()), np.degrees(HAND_TURN), over.sum(), F))
    w_r, w_t = sk.world_pose(act.rot, act.tra)
    off = {j: 100 * np.median(np.linalg.norm(w_t[act.idx[j], :F] - P[:, side.names.index(j)], axis=1)) for j in JOINTS}
    bend = []
    for j in ("Spine", "Spine1", "Spine3", "Neck", "Head"):
        d = rg.qmul(rg.qinv(rot0[act.idx[j], :F]), act.rot[act.idx[j], :F])
        ang = 2 * np.degrees(np.arccos(np.clip(np.abs(d[:, 3]), 0, 1)))
        bend.append("%s %.0f/%.0f" % (j, np.median(ang), ang.max()))
    log("  %s turned off the retarget (deg, median/max): %s" % (act.row["clip"], ", ".join(bend)))
    log("  %s joints off the solved points (cm, median): %s" % (act.row["clip"], ", ".join(
        "%s %.1f" % kv for kv in sorted(off.items(), key=lambda kv: -kv[1])[:5])))
    act.refresh()
