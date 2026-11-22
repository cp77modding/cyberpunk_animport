"""His palm laid on her skin where Skyrim's is, after the interaction mesh: the mesh brings a hand near and stops.

Measured, cowgirl S1 (ostimbed2pcowgirlmf_s1): Skyrim's palm 1 cm off her skin on every frame, fingers 2-4 cm; ours
after the mesh 5.9 cm, the hand rolled onto its thumb edge, the pinky 9 cm off. On a frame where Skyrim's palm is on
her skin, the wrist turns the palm to face her (at most MAX_TURN) and the arm reaches it to GAP off her nearest skin
(at most MAX_REACH), two-bone, the elbow kept in its plane. Rotations only, so no bone changes length; blended in and
out over RAMP frames; a frame Skyrim's palm is off is left as the mesh made it.

  pair_contact.py with HANDFIT=1 (MESH=1): runs after the mesh, before the report, GIF and SAVE
"""
import json
import os

import numpy as np
from scipy.spatial import cKDTree

import body_area_map as bm
from frame_near import FramePoints, FrameTree, blend, release
import interaction_mesh as im
import mesh_skin as ms
import pair_contact as pc
import pair_cast
import pair_reach
import retarget_glb as rg
import skyrim_body as sb
import skyrim_contact as sc

ON = 0.02          # m: Skyrim's palm this near her skin is on it
OFF = sc.NEAR      # m: and off it again only past this: a palm hovering 1.7-2.4 cm flipped the fit every thrust
SWITCH = 0.01      # m: the palm's spot leaves its body area only for one this much nearer
SPOT_K = 64        # her points searched for the spot's area
STRAIGHT = 0.95    # of the arm's length: a reach past this straightens it
EDGE = 0.06       # m: a palm whose centre is this far off her touches with its edge (bench 8.4 cm; flat, 3.9-4.9)
GAP = 0.01         # m: where our palm is put, off her skin -- Skyrim's median
MAX_TURN = np.radians(float(os.environ.get("HANDFIT_TURN", 150)))
MAX_REACH = 0.10   # m
RAMP = 6           # frames in and out
PALM = ("Index", "Middle", "Ring", "Pinky")
GAP_FINGER = 0.005  # m: a finger curls until its pad is this near her skin
MAX_CURL = np.radians(60)   # added bend, all three joints together
CURL_SHARE = (0.4, 0.35, 0.25)
BISECT = 7
SNAP = 0.03        # m: an elbow moving this much more in one frame than before the fit has flipped


class HerSkin:
    """her skin posed once on the frames a fit touches, for both hands and both of fit's passes"""

    def __init__(self, her, nb, frames):
        self.row = {f: i for i, f in enumerate(frames)}
        s, vh, w = her.parts[0]     # her body, the first of her.pose's parts: nb points
        self.fp = FramePoints(*blend(w, s[frames], vh, keep=True)) if frames else FramePoints(np.zeros((0, nb, 3)))

    def at(self, f):
        return self.fp.pts[self.row[f]]

    def nearest(self, frames, pts):
        """pts (frames, k, 3): each one's distance to her nearest skin point on its frame, and that point"""
        d, j = self.fp.nearest([self.row[f] for f in frames], pts)
        return d, self.fp.flat[j]


def unit(v):
    return v / np.linalg.norm(v, axis=-1, keepdims=True)


def qbetween(a, b):
    q = np.concatenate([np.cross(a, b), 1 + (a * b).sum(-1, keepdims=True)], -1)
    return q / np.linalg.norm(q, axis=-1, keepdims=True)


def qscale(q, w):
    """the rotation q, w of the way from none; q (..., 4), w a number or one per q"""
    ang = 2 * np.arccos(np.clip(q[..., 3], -1, 1))
    still = ang < 1e-9
    axis = q[..., :3] / np.where(still, 1.0, np.sin(ang / 2))[..., None]
    half = np.asarray(w) * ang / 2
    out = np.concatenate([axis * np.sin(half)[..., None], np.cos(half)[..., None]], -1)
    out[still] = (0.0, 0, 0, 1)
    return out


def qcap(q, cap):
    ang = 2 * np.arccos(np.clip(abs(q[3]), -1, 1))
    return qscale(q if q[3] >= 0 else -q, min(1.0, cap / ang)) if ang > cap else q


def pelvis_axes(side, up):
    """(side, up, fwd) rows from a pelvis's left-minus-right and up, as skyrim_contact.body_frame builds them"""
    up = unit(up)
    side = unit(side - up * (side @ up))
    return np.array([side, up, np.cross(side, up)])


def skyrim_palm_on(base, pack, F):
    """(on, dirs, (spot, spot_area), (bind, area)) per hand and frame: Skyrim's palm (HIMBO's Hand-bone skin) within ON
    of her CBBE skin, staying on until past OFF; its hand frame in her pelvis's (side, up, fwd); the bind point and area
    of her skin under it; her bind points and areas, labelled as our woman's were (mark_dark: vulva, areolas)"""
    port, src = pair_reach.PORTS[pack]
    rows = {}
    for r in json.load(open(os.path.join(port, "manifest.json"))):
        rows.setdefault(r["clip"], r)
    (mb, ma), (fb, fa) = ms.sky_bodies()
    c0, c1 = pair_cast.clips(pack, base)[:2]
    him, her = sc.Actor(rows[c0], [(mb, ma)], src), sc.Actor(rows[c1], [(fb, fa)], src)
    dom = np.array(mb.bones)[np.argmax(mb.weights, 1)]
    palm = {S: np.where(dom == "NPC %s Hand [%sHnd]" % (S[0], S[0]))[0] for S in ("Left", "Right")}
    on = {S: np.full(F, np.inf) for S in palm}
    dirs = {S: np.zeros((F, 3, 3)) for S in palm}
    spot = {S: np.zeros((F, 3)) for S in palm}
    spot_area = {S: np.full(F, None, dtype=object) for S in palm}
    inc, bind = incidence(fb.tris, len(fb.verts)), ms.to_ours(fb.verts)
    pelv, spine, lt, rt = sc.SKY_BONES
    n = min(F, him.frames, her.frames)
    skins, mvs = sky_pose(her, n), sky_pose(him, n)
    fp, rows, V = FramePoints(skins), np.arange(n), skins.shape[1]
    near = {}       # every frame's queries at once: on, the centre's spot, the edge's
    for S, ix in palm.items():
        d, _ = fp.nearest(rows, mvs[:, ix])
        on[S][:n] = d.min(1) * sc.UNIT          # the distance; held_on makes it on/off below
        dc, jc = fp.knn(rows, mvs[:, ix].mean(1)[:, None], SPOT_K)
        ef = np.where(dc[:, 0, 0] * sc.UNIT > EDGE)[0]
        de, je = fp.knn(ef, mvs[ef][:, ix], SPOT_K)
        near[S] = dc[:, 0], jc[:, 0] % V, {f: (de[i], je[i] % V) for i, f in enumerate(ef)}
    for f in range(n):
        skin, mv = skins[f], mvs[f]
        ax = pelvis_axes(her.bone(lt, f) - her.bone(rt, f), her.bone(spine, f) - her.bone(pelv, f))
        for S, ix in palm.items():
            # under the palm's centre while it lies on her; a palm on its edge (centre 8 cm off her) under the point
            # touching. The touching point alone hops across a flat palm: his hand slid 1.0 cm, 0.7 by the centre
            p = mv[ix].mean(0)
            d, j = near[S][0][f], near[S][1][f]
            edge = f in near[S][2]
            if edge:
                d, j = near[S][2][f]
                p = mv[ix][np.unravel_index(d.argmin(), d.shape)[0]]
                o = np.argsort(d, axis=None)
                d, j = d.ravel()[o], j.ravel()[o]
            j0 = same_area(d, j, fa, spot_area[S][f - 1] if f else None)
            if edge and j0 != j[0]:    # the area kept: the palm point nearest it, not the one touching another area
                p = mv[ix][np.linalg.norm(mv[ix] - skin[j0], axis=1).argmin()]
            # the surface point under it, not a vertex: her belly's nearest vertex hopped 3.2 cm every half thrust
            t, bc = on_surface(skin, fb.tris, inc, p, [j0] + [v for v in j[:8] if fa[v] == fa[j0]])
            spot[S][f], spot_area[S][f] = bc @ bind[fb.tris[t]], fa[j0]
            b = lambda n: him.bone("NPC %s %s [%s%s]" % (S[0], n, S[0], n.replace("Finger", "F")), f)
            dirs[S][f] = ax @ hand_axes(b("Finger20") - him.bone("NPC %s Hand [%sHnd]" % (S[0], S[0]), f),
                                        b("Finger40") - b("Finger10"))
    for S in palm:      # past Skyrim's last frame (a ramp reaches there): its last spot, not the body's centre
        if 0 < n < F:
            spot[S][n:], spot_area[S][n:] = spot[S][n - 1], spot_area[S][n - 1]
    return {S: held_on(d) for S, d in on.items()}, dirs, (spot, spot_area), (bind, fa)


def sky_pose(act, n):
    """skyrim_contact.Actor.pose on frames 0..n-1 at once: (n, points, 3)"""
    return np.concatenate([blend(body.weights, skin[:n], vh) for skin, vh, body in act.parts], 1)


def incidence(tris, n):
    """each point's triangles"""
    flat = tris.ravel()
    order = np.argsort(flat, kind="stable")
    return np.split(order // 3, np.searchsorted(flat[order], np.arange(1, n)))


def closest_on_tri(p, a, b, c):
    """barycentric (u, v, w) of the point of triangle abc nearest p"""
    return closest_on_tris(p, a[None], b[None], c[None])[0]


def closest_on_tris(p, a, b, c):
    """closest_on_tri for many triangles at once: a, b, c (T, 3) -> (T, 3)"""
    dot = lambda x, y: (x * y).sum(-1)
    ab, ac, n = b - a, c - a, np.cross(b - a, c - a)
    nn = dot(n, n)
    flat = nn < 1e-20
    nn = np.where(flat, 1.0, nn)
    q = p - n * dot(p - a, n)[:, None] / nn[:, None]
    v, w = dot(np.cross(q - a, ac), n) / nn, dot(np.cross(ab, q - a), n) / nn
    out = np.stack([1 - v - w, v, w], 1)
    # outside the triangle: the nearest of its three edges, the first on a tie
    best, best_dd = np.zeros_like(out), np.full(len(a), np.inf)
    for i, j in ((0, 1), (1, 2), (2, 0)):
        e0, e1 = (a, b, c)[i], (a, b, c)[j]
        s = np.clip(dot(p - e0, e1 - e0) / np.maximum(dot(e1 - e0, e1 - e0), 1e-20), 0, 1)
        dd = np.sum((e0 + s[:, None] * (e1 - e0) - p) ** 2, -1)
        nearer = dd < best_dd
        best[nearer] = 0.0
        best[nearer, i], best[nearer, j], best_dd[nearer] = (1 - s)[nearer], s[nearer], dd[nearer]
    outside = ~((v >= 0) & (w >= 0) & (v + w <= 1))
    out[outside] = best[outside]
    out[flat] = (1.0, 0, 0)
    return out


def on_surface(verts, tris, inc, p, near):
    """(triangle, barycentric) of the surface point nearest p, among the triangles of points near"""
    ts = np.array(list({int(t) for v in near for t in inc[v]}))
    T = verts[tris[ts]]
    bc = closest_on_tris(p, T[:, 0], T[:, 1], T[:, 2])
    k = np.sum((np.einsum("tk,tkd->td", bc, T) - p) ** 2, -1).argmin()
    return int(ts[k]), bc[k]


def same_area(d, j, area, was):
    """of points j at distances d (nearest first, Skyrim units), the nearest; the nearest in area was while it is
    within SWITCH of that: a palm as near her buttock as her forearm flipped between them on 0.1 mm, its spot 39 cm"""
    keep = np.where(area[j] == was)[0]
    return j[keep[0]] if len(keep) and (d[keep[0]] - d[0]) * sc.UNIT < SWITCH else j[0]


def spot_map(sky_verts, sky_area, verts, area, tris, pts, pts_area):
    """our surface point, (triangle, barycentric) per frame, for each of Skyrim's bind points pts on area pts_area: the
    same place within the same body area, each area's bind points scaled to the other's on each axis (our woman is
    shaped otherwise); the whole body for an area we lack"""
    inc = incidence(tris, len(verts))
    out_t, out_b = np.zeros(len(pts), int), np.zeros((len(pts), 3))
    for a in set(pts_area):
        s_in, o_in = sky_area == a, area == a
        if not o_in.any():
            s_in, o_in = np.ones(len(sky_area), bool), np.ones(len(area), bool)
        S, O, ours = sky_verts[s_in], verts[o_in], np.where(o_in)[0]
        fs = np.where(pts_area == a)[0]
        q = O.mean(0) + (pts[fs] - S.mean(0)) / np.maximum(S.std(0), 1e-9) * O.std(0)
        near = cKDTree(O).query(q, k=min(8, len(ours)))[1].reshape(len(fs), -1)    # k=1 gives one per point
        for i, f in enumerate(fs):
            out_t[f], out_b[f] = on_surface(verts, tris, inc, q[i], ours[near[i]])
    return out_t, out_b


def held_on(d):
    """on from the palm's distance per frame: on within ON, and staying on until past OFF"""
    on = np.zeros(len(d), bool)
    for f, x in enumerate(d):
        on[f] = x < ON or (f > 0 and on[f - 1] and x < OFF)
    return on


def hand_axes(fingers, across):
    """(fingers, across, out of the back) as columns: the hand's frame from wrist-to-knuckle and index-to-pinky"""
    a = unit(fingers)
    s = unit(across - a * (across @ a))
    return np.stack([a, s, np.cross(a, s)], 1)


def ramp(on):
    """a 0..1 weight per frame: 1 on, easing to 0 over RAMP frames either side"""
    w = on.astype(float)
    for k in range(1, RAMP + 1):
        w = np.maximum(w, np.r_[on[k:], [False] * k] * (1 - k / (RAMP + 1)))
        w = np.maximum(w, np.r_[[False] * k, on[:-k]] * (1 - k / (RAMP + 1)))
    return w


def set_world(act, k, q_world, frames):
    """bone k's local turn on the frames from a wanted world turn per frame"""
    w_r, _ = act.tg.skel.world_pose(act.rot[:, frames], act.tra[:, frames])
    act.rot[k, frames] = rg.qnorm(rg.qmul(rg.qinv(w_r[act.tg.skel.parent[k]]), q_world))


def palm_normal(palm, curl):
    """out of the palm: the flat of the metacarpals' skin (its thinnest axis), turned to the side the fingers curl to"""
    Q = palm - palm.mean(0)
    n = np.linalg.svd(Q, full_matrices=False)[2][-1]
    return n if n @ curl > 0 else -n


def palm_centres(act, frames, palm_ix):
    """act.pose(f)[palm_ix].mean(0) on many frames at once, from the skins its last refresh made"""
    s, vh, w = act.parts[0]
    m = (w[palm_ix] @ s[frames].reshape(len(frames), s.shape[1], 16)).reshape(len(frames), len(palm_ix), 4, 4)
    return np.einsum("fvij,vj->fvi", m[:, :, :3], vh[palm_ix]).mean(1)


def target_frame(act, her, S, f, w_t, ht, c, sky_dir, spot, skin):
    """(turn, move) that lay the palm on her skin in frame f, at full weight: a world turn about the wrist, then the
    wrist's move. The palm faces her; the fingers point across her skin the way Skyrim's do in her pelvis's frame; the
    palm goes to spot, our point where Skyrim's palm is on her body (her nearest skin slid it 3.7 cm a thrust). w_t
    and ht are his and her joints on f, c his palm's centre, skin her HerSkin"""
    idx = act.idx
    h = w_t[idx[S + "Hand"]]
    ax = pelvis_axes(ht[her.idx["LeftUpLeg"]] - ht[her.idx["RightUpLeg"]], ht[her.idx["Spine"]] - ht[her.idx["Hips"]])
    # the whole hand turned to sit in her pelvis's frame as Skyrim's sits in hers: fingers and roll both
    now = hand_axes(w_t[idx[S + "HandMiddle1"]] - h, w_t[idx[S + "HandPinky1"]] - w_t[idx[S + "HandIndex1"]])
    turn = qcap(im.m2q(ax.T @ sky_dir @ now.T), MAX_TURN)
    c2 = h + rg.qrot(turn, c - h)
    if spot is None:    # her nearest skin
        d, at = skin.nearest([f], c2[None, None])
        d, at = d[0, 0], at[0, 0]
        out = unit(c2 - at) if d > 1e-6 else unit(c2 - c)
    else:               # (triangle's points, barycentric) on her posed skin
        a, b, cc = skin.at(f)[spot[0]]
        at, out = spot[1] @ skin.at(f)[spot[0]], unit(np.cross(b - a, cc - a))
    move = at + out * GAP - c2
    far = np.linalg.norm(move) > MAX_REACH
    if far:
        move *= MAX_REACH / np.linalg.norm(move)
    # or one the arm reaches only straight, past where the clip has it: a straight arm's elbow has no side and
    # snapped 4 cm in a frame (cowgirl hand on breast S4, 8 cm short of her breast)
    sh, el = w_t[idx[S + "Arm"]], w_t[idx[S + "ForeArm"]]
    arm = np.linalg.norm(el - sh) + np.linalg.norm(h - el)
    far |= np.linalg.norm(h + move - sh) > max(STRAIGHT * arm, np.linalg.norm(h - sh))
    return turn, move, far


def smooth(turns, moves, w):
    """each frame's target averaged with its neighbours' (a nearest-skin point jumps between frames), by weight"""
    out_t, out_m = [], []
    F = len(w)
    for f in range(F):
        lo, hi = max(0, f - RAMP), min(F, f + RAMP + 1)
        ws = np.array([w[g] * (1 - abs(g - f) / (RAMP + 1)) for g in range(lo, hi)])
        if ws.sum() <= 0:
            out_t.append(np.array([0.0, 0, 0, 1])), out_m.append(np.zeros(3))
            continue
        q = np.array([turns[g] if turns[g] @ turns[f] >= 0 else -turns[g] for g in range(lo, hi)])
        out_t.append(unit((q * ws[:, None]).sum(0)))
        out_m.append((np.array(moves[lo:hi]) * ws[:, None]).sum(0) / ws.sum())
    return out_t, out_m


def elbow_side(act, S, frames):
    """the elbow's offset off the shoulder-wrist line, per frame: the side apply_frames bends it to"""
    _, w_t = act.tg.skel.world_pose(act.rot[:, frames], act.tra[:, frames])
    s, e, h = w_t[act.idx[S + "Arm"]], w_t[act.idx[S + "ForeArm"]], w_t[act.idx[S + "Hand"]]
    along = unit(h - s)
    return (e - s) - along * ((e - s) * along).sum(1, keepdims=True)


def elbow_snap(act, S):
    """the elbow's largest move between two frames, m"""
    _, w_t = act.tg.skel.world_pose(act.rot, act.tra)
    return np.linalg.norm(np.diff(w_t[act.idx[S + "ForeArm"]], axis=0), axis=1).max()


def apply_frames(act, S, frames, w, turn, move, side):
    """the hand turned by turn about the wrist and the wrist moved by move, each scaled by w, two-bone with the elbow
    bent toward side (elbow_side before the fit: a reach that straightens the arm leaves no side of its own to keep):
    every frame at once, w (frames,), turn (frames, 4), move (frames, 3), side (frames, 3)"""
    sk, idx = act.tg.skel, act.idx
    arm, fore, hand = idx[S + "Arm"], idx[S + "ForeArm"], idx[S + "Hand"]
    w_r, w_t = sk.world_pose(act.rot[:, frames], act.tra[:, frames])
    turn, move = qscale(turn, w), move * w[:, None]
    s, e, h = w_t[arm], w_t[fore], w_t[hand]
    a, b = np.linalg.norm(e - s, axis=1), np.linalg.norm(h - e, axis=1)
    goal = h + move
    dist = np.clip(np.linalg.norm(goal - s, axis=1), abs(a - b) + 1e-4, a + b - 1e-4)
    goal = s + unit(goal - s) * dist[:, None]
    along = unit(goal - s)
    x = ((a * a - b * b + dist * dist) / (2 * dist))[:, None]
    bend = side - along * (side * along).sum(1, keepdims=True)
    lost = np.linalg.norm(bend, axis=1) <= 1e-6         # the old side along the new line: keep the elbow's own
    bend[lost] = (e - s - along * ((e - s) * along).sum(1, keepdims=True))[lost]
    e_new = s + along * x + unit(bend) * np.sqrt(np.maximum(a * a - x[:, 0] ** 2, 0.0))[:, None]
    hand_world = rg.qmul(turn, w_r[hand])
    set_world(act, arm, rg.qmul(qbetween(unit(e - s), unit(e_new - s)), w_r[arm]), frames)
    wr2, wt2 = sk.world_pose(act.rot[:, frames], act.tra[:, frames])
    set_world(act, fore, rg.qmul(qbetween(unit(wt2[hand] - wt2[fore]), unit(goal - wt2[fore])), wr2[fore]), frames)
    set_world(act, hand, hand_world, frames)


class Skin:
    """some of an actor's body points posed on one frame, from its current rot/tra: cheaper than a whole refresh"""

    def __init__(self, act):
        self.act, self.p = act, act.parts_src[0][0]
        self.drv = [act.idx[pc.driver(self.p, b, act.idx)] for b in self.p.bones]
        self.inv_rest = np.stack([np.linalg.inv(act.rest[k]) for k in self.drv])

    def pose(self, f, ix):
        a = self.act
        w_r, w_t = a.tg.skel.world_pose(a.rot[:, f:f + 1], a.tra[:, f:f + 1])
        M = pc.mats(w_r[:, 0], w_t[:, 0])
        skin = (M[self.drv] @ self.inv_rest).reshape(len(self.drv), 16)
        m = (self.p.weights[ix] @ skin).reshape(-1, 4, 4)[:, :3]
        return np.einsum("vij,vj->vi", m, np.c_[self.p.verts[ix], np.ones(len(ix))])

    def pose_many(self, frames, ix, world=None):
        """pose's points on many frames in one skeleton pass, or on world, a World kept on those frames: (frames,
        points, 3)"""
        a = self.act
        w_r, w_t = (world.r, world.t) if world else a.tg.skel.world_pose(a.rot[:, frames], a.tra[:, frames])
        M = pc.mats(w_r[self.drv], w_t[self.drv]) @ self.inv_rest[:, None]          # (bones, frames, 4, 4)
        return blend(self.p.weights[ix], M.transpose(1, 0, 2, 3), np.c_[self.p.verts[ix], np.ones(len(ix))])


def signed(skin, frames, pts, outs):
    """each point's distance to her nearest skin, negative where it is under it (the contact plane's side): pts
    (frames, k, 3), outs (frames, 3) -> (frames, k)"""
    d, near = skin.nearest(frames, pts)
    return d * np.where(((pts - near) * outs[:, None]).sum(-1) >= 0, 1.0, -1.0)


class World:
    """an actor's world pose on some frames, kept current as bones turn: a turn redoes that bone's subtree, not the
    whole skeleton (the fingers' bisection asked world_pose 224 times a clip), by world_pose's own arithmetic"""

    def __init__(self, act, frames):
        self.act, self.fr = act, frames
        self.r, self.t = act.tg.skel.world_pose(act.rot[:, frames], act.tra[:, frames])

    def redo(self, k):
        sk, a = self.act.tg.skel, self.act
        under = {k}
        for i in sk.order:
            if i == k or sk.parent[i] in under:
                under.add(i)
                p = sk.parent[i]
                self.r[i] = rg.qmul(self.r[p], a.rot[i, self.fr])
                self.t[i] = self.t[p] + rg.qrot(self.r[p], a.tra[i, self.fr])


def curl_finger_many(act, S, fn, frames, ang, base_rot, n, world):
    """the finger's three joints bent toward the palm side n by ang in all (CURL_SHARE), from base_rot, on every
    frame at once: ang (frames,), base_rot (bones, frames, 4), n (frames, 3); world, a World on frames, kept current"""
    idx = act.idx
    ks = [idx[S + "Hand%s%d" % (fn, k)] for k in (1, 2, 3)]
    for k in ks:
        act.rot[k, frames] = base_rot[k]
    world.redo(ks[0])
    for i, (k, share) in enumerate(zip(ks, CURL_SHARE)):
        w_r, w_t = world.r, world.t
        # the tip bone has no child: its segment carries on its parent's line
        seg = w_t[ks[i + 1]] - w_t[k] if i < 2 else w_t[k] - w_t[ks[i - 1]]
        axis = np.cross(unit(seg), n)
        ok = np.linalg.norm(axis, axis=1) >= 1e-6
        a_l = rg.qrot(rg.qinv(w_r[k]), unit(axis))
        a = (ang * share)[:, None]
        q = rg.qnorm(rg.qmul(act.rot[k, frames], np.concatenate([a_l * np.sin(a / 2), np.cos(a / 2)], 1)))
        rot = act.rot[k, frames]
        rot[ok] = q[ok]
        act.rot[k, frames] = rot
        world.redo(k)


def fit(acts, base, pack, F, log=print):
    """acts as pair_contact made them, after the mesh; him the man, her the woman. A cast of other shape is left"""
    if len(acts) != 2 or [a.male for a in acts] != [True, False]:
        log("handfit: %s is not a man and a woman, left" % base)
        return
    him, her = acts
    on, sky_dirs, sky_spot, (sky_verts, sky_area) = skyrim_palm_on(base, pack, F)
    body = him.parts_src[0][0]
    dom = np.array(body.bones)[np.argmax(body.weights, 1)]
    her_body = her.parts_src[0][0]
    nb = len(her_body.verts)
    tris = bm.OurBody(her_body.path).tris
    ws = {S: ramp(on[S][:F]) for S in ("Left", "Right")}
    her_skin = HerSkin(her, nb, sorted({int(f) for w in ws.values() for f in np.nonzero(w)[0]}))
    for S in ("Left", "Right"):
        w = ws[S]
        if not w.any():
            log("handfit: %s %s palm never on her skin in Skyrim, left" % (base, S))
            continue
        palm_ix = np.where(np.isin(dom, [S + "InHand" + n for n in PALM]))[0]
        turns, moves = [np.array([0.0, 0, 0, 1])] * F, [np.zeros(3)] * F
        st, sbc = spot_map(sky_verts, sky_area, her_body.verts, her.area[:nb], tris, sky_spot[0][S][:F],
                           sky_spot[1][S][:F])
        spots = [(tris[st[f]], sbc[f]) for f in range(F)]
        frames = [int(f) for f in np.nonzero(w)[0]]
        fr = np.array(frames)
        _, hts = her.tg.skel.world_pose(her.rot[:, fr], her.tra[:, fr])
        side = elbow_side(him, S, fr)
        snap0 = elbow_snap(him, S)
        rot0 = him.rot.copy()
        # Skyrim's spot out of reach on any frame, or a fit to it that snaps the elbow: the mesh put the hand
        # elsewhere on her (groping breast S1, 10 cm off on every frame; cooking pot raised leg S1, the heel's lift
        # straightened the arm and the elbow jumped 4.4 cm), so her nearest skin for the whole clip
        for by_spot in (True, False):
            far = False
            _, wts = him.tg.skel.world_pose(him.rot[:, fr], him.tra[:, fr])
            cs = palm_centres(him, fr, palm_ix)
            for i, f in enumerate(frames):
                turns[f], moves[f], fr_far = target_frame(him, her, S, f, wts[:, i], hts[:, i], cs[i], sky_dirs[S][f],
                                                          spots[f] if by_spot else None, her_skin)
                far |= fr_far and bool(on[S][f])    # a ramp frame is off her: its full move is never applied
            if by_spot and far:
                log("handfit: %s %s Skyrim's spot past %.0f cm or a straight arm, her nearest skin instead" % (
                    base, S, 100 * MAX_REACH))
                continue
            if fit_side(him, her_skin, S, F, w, fr, turns, moves, side, dom, palm_ix, base, log) <= snap0 + SNAP \
                    or not by_spot:
                break
            him.rot[:] = rot0
            log("handfit: %s %s the fit to Skyrim's spot snaps the elbow, her nearest skin instead" % (base, S))
        log("handfit: %s %s fitted on %d frames (%d on in Skyrim)" % (base, S, (w > 0).sum(), on[S][:F].sum()))
        snap = elbow_snap(him, S)
        if snap > snap0 + SNAP:     # the batch counts it failed: a snapping arm is never saved
            raise RuntimeError("BROKEN: %s %s elbow jumps %.1f cm in one frame after the fit, %.1f before" % (
                base, S, 100 * snap, 100 * snap0))
    him.refresh()
    del her_skin
    release()


def fit_side(him, skin, S, F, w, fr, turns, moves, side, dom, palm_ix, base, log):
    """one hand laid on her (skin, her HerSkin) by its targets: the reach, the heel lifted out of her skin, the
    fingers curled; the elbow's largest one-frame move after"""
    frames = [int(f) for f in fr]
    turns, moves = smooth(turns, moves, w)
    apply_frames(him, S, fr, w[fr], np.array(turns)[fr], np.array(moves)[fr], side)
    hand_ix = np.where(np.isin(dom, [S + "Hand", S + "HandThumb1", S + "HandThumb2"] +
                               [S + "InHand" + n for n in PALM + ("Thumb",)]))[0]
    sk = Skin(him)
    palm_c = sk.pose_many(fr, palm_ix).mean(1)
    outs = unit(palm_c - skin.nearest(frames, palm_c[:, None])[1][:, 0])
    # what of the heel and the thumb went under her skin, the hand lifted back out by it
    lift = [np.zeros(3)] * F
    under = np.maximum(0.0, -signed(skin, frames, sk.pose_many(fr, hand_ix), outs).min(1))
    for i, f in enumerate(frames):
        lift[f] = outs[i] * under[i]
    _, lift = smooth([np.array([0.0, 0, 0, 1])] * F, lift, w)
    apply_frames(him, S, fr, np.ones(len(fr)), np.tile([0.0, 0, 0, 1], (len(fr), 1)), np.array(lift)[fr], side)
    gap = lambda pts: signed(skin, frames, pts, outs).min(1)
    # each finger curled until its pad meets her skin, every frame's bisection at once
    for fn in PALM:
        pad = np.where(np.isin(dom, [S + "Hand%s%d" % (fn, k) for k in (2, 3)]))[0]
        # the palm's normal per frame, to the side the middle finger curls to (after the fingers before this one)
        world = World(him, fr)
        P = sk.pose_many(fr, palm_ix, world)
        k1, k3, h = (world.t[him.idx[S + nm]] for nm in ("HandMiddle1", "HandMiddle3", "Hand"))
        d, u = k3 - k1, unit(k1 - h)
        normals = np.array([palm_normal(P[i], d[i] - u[i] * (d[i] @ u[i])) for i in range(len(frames))])
        base_rot = him.rot[:, fr].copy()
        far = gap(sk.pose_many(fr, pad, world)) > GAP_FINGER
        lo, hi = np.zeros(len(fr)), np.full(len(fr), MAX_CURL)
        for _ in range(BISECT):
            mid = (lo + hi) / 2
            curl_finger_many(him, S, fn, fr, mid, base_rot, normals, world)
            out = gap(sk.pose_many(fr, pad, world)) > GAP_FINGER
            lo, hi = np.where(out, mid, lo), np.where(out, hi, mid)
        him.rot[:, fr] = base_rot
        angs = np.zeros(F)
        angs[fr] = np.where(far, lo, 0.0)
        sm = np.array([np.average(angs[max(0, f - RAMP):f + RAMP + 1]) for f in range(F)])
        curl_finger_many(him, S, fn, fr, sm[fr] * w[fr], base_rot, normals, world)
        log("handfit: %s %s %s curled %.0f deg median, %.0f max" % (base, S, fn, np.degrees(np.median(sm[frames])),
                                                                      np.degrees(sm.max())))
    return elbow_snap(him, S)
