"""Every touch Skyrim's bodies have, held on ours: for each pair of body areas whose skin touches in Skyrim's clip, one
point on each skin, carried onto our bodies (hand_fit.spot_map), and a pull bringing the two back to Skyrim's gap in
the frames they touch, never pushing them apart. interaction_mesh.adapt takes the points as skin points and the pairs as ties.
  pair_contact.py with TOUCH_TIES=1 (MESH=1)
Design: docs/design/opensex-port.md section 9.8 (nightcitynet)."""
import collections
import os
import numpy as np
from scipy.spatial import cKDTree
import body_area_map as bm
import hand_fit
import interaction_mesh as im
import mesh_skin
import pair_reach
import skyrim_contact as sc
import touches

# the genitals and mouths have their own ties (opensex-port.md 9.7); heads and her hands are not one body mesh on
# both sides (her head and his are separate meshes, CBBE has no hands)
SKIP = {"penis", "glans", "scrotum", "vulva", "butt_crack", "other", "head", "face", "lips", "neck"}
SCALE = float(os.environ.get("TOUCH_SCALE", 1.0))   # a touch pull's weight, on W_TOUCH
MAX_TIES = 8           # per pair of actors, the touches held longest
# segments a point can ride: put_back needs the segment's own points, which every capsule's first joint has
SEGS = set(im.PARENT.values()) | {"Head"} | {a for a, _ in im.RADIUS}


def segment(act, bone):
    """the mesh segment a bone of our rig belongs to: itself, or its nearest ancestor the mesh has"""
    skel = act.tg.skel
    k = skel.index[bone]
    while skel.names[k] not in SEGS:
        k = skel.parent[k]
        if k < 0:
            raise KeyError("%s: no mesh segment above it" % bone)
    return skel.names[k]


def find(acts, base, pack, F, log=print):
    """(skin, pairs): skin {act: {name: (segment, our bind point, Skyrim's (F, 3))}} as mesh_skin.points gives;
    pairs [(actor index, name, actor index, name, (F,) weight)] for interaction_mesh.adapt's touch ties"""
    _, src = pair_reach.PORTS[pack]
    (mb, ma), (fb, fa) = mesh_skin.sky_bodies()
    sky = [(mb, ma) if a.male else (fb, fa) for a in acts]
    s_act = [sc.Actor(a.row, [s], src) for a, s in zip(acts, sky)]
    n = min([F] + [s.frames for s in s_act])
    posed = [hand_fit.sky_pose(s, n) * sc.UNIT for s in s_act]
    found = {}          # (i, A, j, B): per frame gap, its vertex on i, its vertex on j
    for f in range(n):
        for i in range(len(acts)):
            for j in range(i + 1, len(acts)):
                d, v = cKDTree(posed[j][f]).query(posed[i][f])
                ai, bj = sky[i][1], sky[j][1][v]
                close = d <= touches.OFF
                for A in np.unique(ai[close]):
                    if A in SKIP:
                        continue
                    for B in np.unique(bj[close & (ai == A)]):
                        if B in SKIP:
                            continue
                        m = np.where(close & (ai == A) & (bj == B))[0]
                        k = m[d[m].argmin()]
                        g = found.setdefault((i, A, j, B), [np.full(n, np.inf), np.zeros(n, int), np.zeros(n, int)])
                        g[0][f], g[1][f], g[2][f] = d[k], k, v[k]
    held = collections.defaultdict(list)
    for key, (gap, vi, vj) in found.items():
        on = touches.touching(gap)
        if on.mean() >= touches.MIN_SHARE:
            held[key[0], key[2]].append((on.mean(), key, on, vi, vj))
    skin, pairs = {a: {} for a in acts}, []
    for (i, j), rows in held.items():
        for share, (_, A, _, B), on, vi, vj in sorted(rows, key=lambda r: -r[0])[:MAX_TIES]:
            names = []
            for side, area, v in ((i, A, vi), (j, B, vj)):
                act, (body, s_area) = acts[side], sky[side]
                k = collections.Counter(v[on]).most_common(1)[0][0]    # the vertex touching in most frames
                part = act.parts_src[0][0]
                nb = len(part.verts)
                tris = bm.OurBody(part.path).tris
                t, bc = hand_fit.spot_map(mesh_skin.to_ours(body.verts), s_area, part.verts, act.area[:nb], tris,
                                          mesh_skin.to_ours(body.verts[k:k + 1]), np.array([area], dtype=object))
                tri = tris[t[0]]
                import pair_contact     # here: pair_contact imports this module
                bone = pair_contact.driver(part, part.bones[int(np.argmax(part.weights[tri[int(np.argmax(bc[0]))]]))],
                                           act.idx)
                name = "t_%s_%s" % (area, "abcdefgh"[len(skin[act]) % 8] + str(len(skin[act])))
                track = np.zeros((F, 3))
                track[:n] = mesh_skin.to_ours(posed[side][:, k] / sc.UNIT)
                track[n:] = track[n - 1]
                skin[act][name] = (segment(act, bone), bc[0] @ part.verts[tri], track)
                names.append(name)
            w = np.zeros(F)
            w[:n] = hand_fit.ramp(on) * SCALE
            pairs.append((i, names[0], j, names[1], w))
            log("touch tie: %s %s on %s %s, %d%% of frames (%s, %s)" % (
                "his" if acts[i].male else "her", A, "his" if acts[j].male else "her", B, 100 * share,
                skin[acts[i]][names[0]][0], skin[acts[j]][names[1]][0]))
    return skin, pairs
