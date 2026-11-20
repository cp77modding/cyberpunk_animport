"""Body areas on a Cyberpunk body, carried over from the labelled Skyrim body (skyrim_body.py).

Each skin point rides a chain -- the torso (hips to neck to head), an arm (shoulder, elbow, wrist, hand) or a leg
(hip, knee, ankle, toes) -- by the main bone that moves it most. Its place is measured along the chain, joint to
joint (the torso as one piece by length: the two skeletons put their chest bones at different heights), and out
from it in the chain's frame (along, toward the body's front, across), as a share of that body's thickness there. A
Skyrim point is placed on our chain by the same measures, and each of our points takes the area of the nearest
placed Skyrim point. Hands and feet are separate meshes in Skyrim, so ours take them from the bone.

Nipples and the vulva are then marked on both from the skin texture: they are darker than the skin around them.

  python tools/retarget/body_area_map.py [--male] <out.png|out.glb> [body[,body...]] [rig] [skin.png]
      --male: HIMBO onto t0_000_ma_base__full on man_base, with Bag of Dicks' penis added
      a body is body.glb, or body.glb|rig|skin.png when it has its own rig and skin
      (default: t0_000_wa_base__full, woman_base, its naked skin; a .png draws the first body, a .glb all of them)
"""
import json
import os
import sys
import tempfile

import numpy as np
from scipy.spatial import cKDTree

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import retarget_glb as rg  # noqa: E402
import skyrim_body as sb  # noqa: E402
import skyrim_port as sp  # noqa: E402
import skyrim_retarget as sr  # noqa: E402

BODY = os.path.join(HERE, "work", "body", "glb", "t0_000_wa_base__full.glb")
BODY_TEX = os.path.join(HERE, "work", "body", "depot", "base", "characters", "common", "base_bodies", "woman_average",
                        "textures", "t0_000_wa__c_base_d02_naked.png")   # its skin: the areola marks the nipple
_tools = sp.build_config.load()["tools"]
CFG = {"hkxc": _tools["hkxc"], "blender_hkx": _tools["blender_hkx"]}
# a clip any skeleton reading needs: the rest pose comes with it
REST_CLIP = r"meshes/0SA/mod/0Sex/anim/OpS/LyBKne/Sx/AceCowgirl/_Sx-AceCowgirl_S2_1.hkx"

# our main bones and the bone each one's axis runs to
CHILD = {"Hips": "Spine", "Spine": "Spine1", "Spine1": "Spine3", "Spine3": "Neck", "Neck": "Head"}
for s in ("Left", "Right"):
    CHILD.update({s + "Shoulder": s + "Arm", s + "Arm": s + "ForeArm", s + "ForeArm": s + "Hand",
                  s + "Hand": s + "HandMiddle1", s + "UpLeg": s + "Leg", s + "Leg": s + "Foot",
                  s + "Foot": s + "ToeBase"})
# Skyrim bones the map does not name, and the main bone they move with
SKYRIM_EXTRA = {"UpperarmTwist": "Arm", "ForearmTwist": "ForeArm", "Breast": "Spine3", "Butt": "Hips"}
BONE_ONLY = {"Hand": "hand", "Foot": "foot"}   # no Skyrim skin on these: the area is the bone's


# chain: (joints, how many stretches the torso's first joints count as one); every other joint is one step
CHAINS = {"torso": ["Hips", "Neck", "Head"]}
for s in ("Left", "Right"):
    CHAINS[s + "_arm"] = [s + "Shoulder", s + "Arm", s + "ForeArm", s + "Hand", s + "HandMiddle1"]
    CHAINS[s + "_leg"] = [s + "UpLeg", s + "Leg", s + "Foot", s + "ToeBase"]
TORSO = {"Hips", "Spine", "Spine1", "Spine3", "Neck"}
BINS = 24          # thickness is matched per slice of a chain


def unit(v):
    return v / np.maximum(np.linalg.norm(v, axis=-1, keepdims=True), 1e-12)


def chain_of(main):
    if main in TORSO:
        return "torso"
    side = "Left" if main.startswith("Left") else "Right"
    return side + ("_leg" if any(k in main for k in ("UpLeg", "Leg", "Foot", "Toe")) else "_arm")


class Chain:
    """joint positions; a point's (step along, toward front, across) and back"""

    def __init__(self, pts, up, fwd):
        self.p = np.array(pts)
        self.seg = self.p[1:] - self.p[:-1]
        self.len = np.linalg.norm(self.seg, axis=1)
        self.ax = self.seg / self.len[:, None]
        self.e2, self.e3 = [], []
        for a in self.ax:
            f = fwd if abs(fwd @ a) < 0.9 else up      # a foot points forward: its second axis is up
            e2 = unit(f - (f @ a) * a)
            self.e2.append(e2)
            self.e3.append(np.cross(a, e2))
        self.e2, self.e3 = np.array(self.e2), np.array(self.e3)

    def measure(self, q):
        """(step, front, across, segment) per point: step k + t on segment k, the nearest segment"""
        best = None
        for k in range(len(self.seg)):
            d = q - self.p[k]
            t = d @ self.ax[k] / self.len[k]
            foot = self.p[k] + np.outer(np.clip(t, 0, 1) * self.len[k], self.ax[k])
            dist = np.linalg.norm(q - foot, axis=1)
            # the ends of the chain extend past their joints
            if k == 0:
                t = np.minimum(t, 1)
            elif k == len(self.seg) - 1:
                t = np.maximum(t, 0)
            else:
                t = np.clip(t, 0, 1)
            r = q - (self.p[k] + np.outer(t * self.len[k], self.ax[k]))
            row = np.stack([k + t, r @ self.e2[k], r @ self.e3[k], np.full(len(q), k)], 1)
            if best is None:
                best, bd = row, dist
            else:
                take = dist < bd
                best[take], bd = row[take], np.where(take, dist, bd)
        return best

    def place(self, m):
        k = np.clip(m[:, 3].astype(int), 0, len(self.seg) - 1)
        t = m[:, 0] - k
        return self.p[k] + (t * self.len[k])[:, None] * self.ax[k] + m[:, 1:2] * self.e2[k] + m[:, 2:3] * self.e3[k]


def thickness(m, steps):
    """per slice of the chain: the spread toward the front and across (rms)"""
    b = np.clip(((m[:, 0] - steps[0]) / (steps[1] - steps[0]) * BINS).astype(int), 0, BINS - 1)
    out = np.ones((BINS, 2))
    for i in range(BINS):
        s = m[b == i]
        if len(s) >= 8:
            out[i] = np.sqrt(np.mean(s[:, 1:3] ** 2, axis=0))
    return out, b


def owners(weights, bone_names, main_of):
    """main bone per point: weights summed per main bone, the heaviest"""
    mains = sorted(set(m for m in main_of.values() if m))
    tot = np.zeros((len(weights), len(mains)))
    for j, b in enumerate(bone_names):
        m = main_of.get(b)
        if m:
            tot[:, mains.index(m)] += weights[:, j]
    return np.array(mains)[np.argmax(tot, 1)]


class OurBody:
    """a skinned Cyberpunk body glb at bind: points, normals, per-point weights over the skin's joints"""

    def __init__(self, path):
        doc, buf = rg.read_glb(path)
        skin = doc["skins"][0]
        self.bones = [doc["nodes"][j]["name"] for j in skin["joints"]]
        ibm = rg.accessor(doc, buf, skin["inverseBindMatrices"]).reshape(-1, 4, 4).astype(np.float64)
        self.bind = {b: np.linalg.inv(m.T)[:3, 3] for b, m in zip(self.bones, ibm)}   # glTF stores column-major
        parent = {}
        for i, nd in enumerate(doc["nodes"]):
            for c in nd.get("children", []):
                parent[doc["nodes"][c]["name"]] = nd["name"]
        self.parent = parent
        v, nrm, w, t, uv = [], [], [], [], []
        for m in doc["meshes"]:
            for p in m["primitives"]:
                at = p["attributes"]
                base = sum(len(x) for x in v)
                pos = rg.accessor(doc, buf, at["POSITION"]).astype(np.float64)
                ww = np.zeros((len(pos), len(self.bones)))
                for k in (0, 1):
                    if "JOINTS_%d" % k in at:
                        jj = rg.accessor(doc, buf, at["JOINTS_%d" % k]).astype(np.int64)
                        wk = rg.accessor(doc, buf, at["WEIGHTS_%d" % k]).astype(np.float64)
                        np.add.at(ww, (np.arange(len(pos))[:, None].repeat(4, 1), jj), wk)
                v.append(pos)
                nrm.append(rg.accessor(doc, buf, at["NORMAL"]).astype(np.float64))
                uv.append(rg.accessor(doc, buf, at["TEXCOORD_0"]).astype(np.float64))
                w.append(ww)
                t.append(rg.accessor(doc, buf, p["indices"]).astype(np.int64).reshape(-1, 3) + base)
        self.verts, self.normals, self.weights = np.concatenate(v), np.concatenate(nrm), np.concatenate(w)
        self.tris = np.concatenate(t)
        self.uvs = np.concatenate(uv)

    def main_of(self, rig_parent, rig_pos):
        """each skin bone's nearest main ancestor in the rig's tree (the body glb's is flat); a helper bone the rig
        lacks (l_SHL_0_JNT, the deltoids) takes the main bone it sits nearest"""
        out = {}
        for b in self.bones:
            x = b
            while x and x not in CHILD:
                x = rig_parent.get(x)
            if not x:
                p = self.bind[b]

                def gap(m):
                    s, e = rig_pos[m], rig_pos[CHILD[m]]
                    t = np.clip((p - s) @ (e - s) / max((e - s) @ (e - s), 1e-12), 0, 1)
                    return np.linalg.norm(p - (s + t * (e - s)))
                x = min(CHILD, key=gap)
            out[b] = x
        return out


def skyrim_rest(sex="f"):
    """Skyrim bone rest positions by name, from the skeleton a clip decodes against"""
    with tempfile.TemporaryDirectory() as tmp:
        xml = sp.decode(os.path.join(sp.build_config.source("opensex")["input"], REST_CLIP),
                        os.path.join(sp.PORT, "skel", sp.SKELETON[sex][1]), tmp, CFG)
        idx, _, ot, _, _, _, _ = sr.read_clip(xml)
    return {n: ot[i] for n, i in idx.items()}


def on_line(a, b, heights, up):
    """the point on a->b at the mean of heights"""
    t = (np.mean(heights) - a @ up) / ((b - a) @ up)
    return a + t * (b - a)


def bust_height(v, hips, neck, up, fwd):
    """heights of each breast's most forward point: the upper torso, a hand's width either side of the middle"""
    h, side = (v - hips) @ up, (v - hips) @ np.cross(up, fwd)
    span = (neck - hips) @ up
    out = []
    for s in (-1, 1):
        m = (h > 0.45 * span) & (h < 0.9 * span) & (s * side > 0.03) & (s * side < 0.2)
        out.append((v[m] @ up)[np.argmax(v[m] @ fwd)])
    return np.array(out)


def transfer(ours, rig_pos, rig_parent, sky, sky_area, sky_rest, skip=None):
    """area per point of ours; skip: Skyrim points not to carry (the man's genitals: ours are a mesh of their own)"""
    to_sky = {o: s for o, (s, _, _) in sr.MAP.items()}
    up = np.array([0, 1.0, 0])
    toes = np.mean([rig_pos[s + "ToeBase"] - rig_pos[s + "Foot"] for s in ("Left", "Right")], 0)
    fwd = unit(toes - (toes @ up) * up)
    # which main bone each body point rides
    s_main = {}
    for b in sky.bones:
        s_main[b] = next((o for o, s in to_sky.items() if s == b and o in CHILD), None)
        for k, m in SKYRIM_EXTRA.items():
            if k in b:
                s_main[b] = ("Left" if " L " in b else "Right" if " R " in b else "") + m
    s_own = owners(sky.weights, sky.bones, s_main)
    o_own = owners(ours.weights, ours.bones, ours.main_of(rig_parent, rig_pos))
    s_ch = np.array([chain_of(b) for b in s_own])
    o_ch = np.array([chain_of(b) for b in o_own])
    placed, labels = [], []
    for name, joints in CHAINS.items():
        ms, mo = s_ch == name, o_ch == name
        if skip is not None:
            ms &= ~skip
        if not ms.any() or not mo.any():
            continue
        sj, oj = [sky_rest[to_sky[j]] for j in joints], [rig_pos[j] for j in joints]
        if name == "torso":
            # the bust as a joint between hips and neck: breasts sit at different heights on the two bodies
            nip = np.isin(sky_area, ["nipple_l", "nipple_r"])
            sj.insert(1, on_line(sj[0], sj[1], sky.verts[nip] @ sb.SKYRIM_UP, sb.SKYRIM_UP))
            oj.insert(1, on_line(oj[0], oj[1], bust_height(ours.verts[mo], oj[0], oj[1], up, fwd), up))
        cs = Chain(sj, sb.SKYRIM_UP, sb.SKYRIM_FWD)
        co = Chain(oj, up, fwd)
        joints = sj
        m_s, m_o = cs.measure(sky.verts[ms]), co.measure(ours.verts[mo])
        steps = (-0.5, len(joints) - 0.5)
        th_s, bin_s = thickness(m_s, steps)
        th_o, _ = thickness(m_o, steps)
        m = m_s.copy()
        m[:, 1:3] *= (th_o / th_s)[bin_s]
        placed.append(co.place(m))
        labels.append(sky_area[ms])
    placed, labels = np.concatenate(placed), np.concatenate(labels)
    _, near = cKDTree(placed).query(ours.verts)
    area = labels[near].astype(object)
    left = np.cross(up, fwd)
    for k, name in BONE_ONLY.items():
        for s in ("Left", "Right"):
            m = o_own == s + k
            area[m] = name + ("_l" if s == "Left" else "_r")
    return area, up, fwd, placed, left


SMOOTH = 3   # passes of the neighbours' vote: the nearest-point copy leaves stray points across a border


def smooth(area, nbr, fixed, passes=SMOOTH):
    """a stray point -- at most one neighbour shares its area (a seam copy is one) -- takes its neighbours' most
    common area; a plain majority vote would also wear thin bands like the wrist away"""
    area = area.copy()
    for _ in range(passes):
        new = area.copy()
        for i in np.where(~fixed)[0]:
            votes = {}
            for j in nbr[i]:
                votes[area[j]] = votes.get(area[j], 0) + 1
            if votes.get(area[i], 0) <= 1:
                new[i] = max(votes, key=votes.get)
        changed = int((new != area).sum())
        area = new
        if not changed:
            break
    return area


SKYRIM_M = 0.0142875   # metres per Skyrim unit


def write_area_glb(out, bodies):
    """bodies: (label, points (n,3) y-up metres facing -z, triangles, area per point); one mesh node per area,
    named '<label>/<area>', coloured by area, so a viewer lists and hides them"""
    import struct
    import matplotlib.pyplot as plt
    names = sorted({sb.base_area(a) for _, _, _, ar in bodies for a in ar})
    hue = {a: plt.get_cmap("hsv")(i / len(names))[:3] for i, a in enumerate(names)}
    blob, views, accs, meshes, nodes = bytearray(), [], [], [], []

    def add(arr, target, ctype, typ, minmax=False):
        while len(blob) % 4:
            blob.append(0)
        views.append({"buffer": 0, "byteOffset": len(blob), "byteLength": arr.nbytes, "target": target})
        blob.extend(arr.tobytes())
        acc = {"bufferView": len(views) - 1, "componentType": ctype, "count": len(arr), "type": typ}
        if minmax:
            acc["min"], acc["max"] = arr.min(0).tolist(), arr.max(0).tolist()
        accs.append(acc)
        return len(accs) - 1
    for label, v, tris, area in bodies:
        # a triangle is the area two of its corners share, else its first corner's: one corner alone saw-tooths borders
        c0, c1, c2 = area[tris[:, 0]], area[tris[:, 1]], area[tris[:, 2]]
        tri_area = np.where((c1 == c2) & (c0 != c1), c1, c0)
        nrm = sb.normals(v, tris).astype(np.float32)   # without them a viewer draws the body unlit, black
        for a in sorted(set(area)):
            t = tris[tri_area == a]
            if not len(t):
                continue
            used, inv = np.unique(t, return_inverse=True)
            pos = v[used].astype(np.float32)
            col = np.tile(np.array(hue[sb.base_area(a)], np.float32), (len(used), 1))
            mat = len(meshes)
            meshes.append({"name": "%s/%s" % (label, a), "primitives": [{
                "attributes": {"POSITION": add(pos, 34962, 5126, "VEC3", True),
                               "NORMAL": add(nrm[used], 34962, 5126, "VEC3"),
                               "COLOR_0": add(col, 34962, 5126, "VEC3")},
                "indices": add(inv.reshape(-1).astype(np.uint32), 34963, 5125, "SCALAR"), "material": 0}]})
            nodes.append({"name": "%s/%s" % (label, a), "mesh": mat})
    doc = {"asset": {"version": "2.0"}, "scene": 0, "scenes": [{"nodes": list(range(len(nodes)))}], "nodes": nodes,
           "meshes": meshes, "accessors": accs, "bufferViews": views, "buffers": [{"byteLength": len(blob)}],
           "materials": [{"pbrMetallicRoughness": {"baseColorFactor": [1, 1, 1, 1], "metallicFactor": 0,
                                                   "roughnessFactor": 0.8}, "doubleSided": True}]}
    js = json.dumps(doc).encode()
    js += b" " * (-len(js) % 4)
    while len(blob) % 4:
        blob.append(0)
    with open(out, "wb") as f:
        f.write(struct.pack("<III", 0x46546C67, 2, 12 + 8 + len(js) + 8 + len(blob)))
        f.write(struct.pack("<II", len(js), 0x4E4F534A) + js)
        f.write(struct.pack("<II", len(blob), 0x004E4942) + bytes(blob))


def skyrim_to_ours(v):
    """Skyrim points (z up, facing +y, units) to y up, facing -z, metres: our body's frame"""
    return np.stack([v[:, 0], v[:, 2], -v[:, 1]], 1) * SKYRIM_M


# Bag of Dicks' regular as the shaftware repo re-skins it (work\#shaftware\dp77\x_dicks\meshes), exported to glb with
# MeshExportArgs__MaterialRepo set: its scrotum_JNT weights mark the scrotum
PENIS = os.path.join(HERE, "work", "body", "glb", "i1_penis_regular_pma_shaftware.glb")
MAN_BODY = os.path.join(HERE, "work", "body", "glb", "t0_000_ma_base__full.glb")
PENIS_CHUNK = "submesh_00_LOD_1"   # dp77's uncut, erect; the others are cut and laid back
GLANS = 0.8                        # the tip's share of the shaft's length


def penis_areas(v, fwd, owner):
    """glans / penis / scrotum / groin on a penis mesh at bind, owner: each point's heaviest bone. The scrotum is
    scrotum_JNT's, the base skin left on Hips is groin; the shaft runs from the root to the point furthest from it"""
    root = v[(v @ fwd) < (v @ fwd).min() + 0.02].mean(0)       # the skin it grows from
    tip = v[np.argmax(np.linalg.norm(v - root, axis=1))]
    t = (v - root) @ (tip - root) / ((tip - root) @ (tip - root))
    area = np.array(["penis"] * len(v), dtype=object)
    area[t >= GLANS] = "glans"
    area[owner == "scrotum_JNT"] = "scrotum"
    area[owner == "Hips"] = "groin"
    return area


def add_penis(ours, area, path=PENIS, chunk=PENIS_CHUNK):
    """our body with dp77's penis on it, moved by the gap between the rig it was fitted on and this body's hips"""
    doc, buf = rg.read_glb(path)
    skin = doc["skins"][0]
    names = [doc["nodes"][j]["name"] for j in skin["joints"]]
    ibm = rg.accessor(doc, buf, skin["inverseBindMatrices"]).reshape(-1, 4, 4).astype(np.float64)
    hips = np.linalg.inv(ibm[names.index("Hips")].T)[:3, 3]
    m = next(x for x in doc["meshes"] if x["name"] == chunk)["primitives"][0]
    at = m["attributes"]
    v = rg.accessor(doc, buf, at["POSITION"]).astype(np.float64) + (ours.bind["Hips"] - hips)
    t = rg.accessor(doc, buf, m["indices"]).astype(np.int64).reshape(-1, 3)
    w = np.zeros((len(v), len(names)))
    for k in (0, 1):
        if "JOINTS_%d" % k in at:
            jj = rg.accessor(doc, buf, at["JOINTS_%d" % k]).astype(np.int64)
            np.add.at(w, (np.arange(len(v))[:, None].repeat(4, 1), jj), rg.accessor(doc, buf, at["WEIGHTS_%d" % k]))
    fwd = np.array([0, 0, -1.0])
    pa = penis_areas(v, fwd, np.array(names)[np.argmax(w, 1)])
    print("penis: %d points, moved %s m onto this body's hips, %.1f cm long; %s" % (
        len(v), np.round(ours.bind["Hips"] - hips, 3), 100 * np.ptp(v @ fwd),
        ", ".join("%s %d" % (a, (pa == a).sum()) for a in ("penis", "glans", "scrotum", "groin"))))
    return np.vstack([ours.verts, v]), np.vstack([ours.tris, t + len(ours.verts)]), np.concatenate([area, pa])


def map_body(name, ours, rig_pos, rig_parent, sky, sky_area, sky_rest, tex, male=False):
    """(ours, area per point, up, fwd): the transfer, its strays smoothed, then the nipples and vulva from the skin.
    male: nothing from the skin (HIMBO's nipples come by slider); the Skyrim genitals are not carried"""
    drift = max(np.linalg.norm(ours.bind[b] - rig_pos[b]) for b in CHILD if b in ours.bind)
    print("%s: rig rest against the body's bind, largest gap %.4f m" % (name, drift))
    # the body's own bones win: the player rigs rest in a T-pose, their bodies are modelled in an A-pose
    rig_pos = dict(rig_pos, **{b: p for b, p in ours.bind.items() if b in rig_pos})
    skip = np.isin(sky_area, ["penis", "glans", "scrotum"]) if male else None
    area, up, fwd, _, left = transfer(ours, rig_pos, rig_parent, sky, sky_area, sky_rest, skip)
    by_bone = np.array([sb.base_area(a) in BONE_ONLY.values() for a in area])
    smoothed = smooth(area, sb.neighbours(ours.verts, ours.tris), by_bone)
    print("%s: smoothing moved %d of %d points" % (name, (smoothed != area).sum(), len(area)))
    if male:
        return ours, smoothed, up, fwd
    area = sb.mark_dark(smoothed, ours.verts, ours.tris, sb.darkness(tex, ours.uvs), left)
    for a in ("nipple_l", "nipple_r", "vulva"):
        m = area == a
        print("%s: %s %d points, centre %s, size %s" % (name, a, m.sum(), np.round(ours.verts[m].mean(0), 3),
                                                       np.round(np.ptp(ours.verts[m], axis=0), 3)))
    return ours, area, up, fwd


def main():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    args = sys.argv[1:]
    male = args[:1] == ["--male"]
    if male:
        args = args[1:]
    out = args[0]
    bodies = args[1].split(",") if len(args) > 1 else [MAN_BODY if male else BODY]
    rig = args[2] if len(args) > 2 else ("man_base" if male else "woman_base")
    tex = args[3] if len(args) > 3 else BODY_TEX
    sky, sky_area, mapped, up, fwd = build(male, bodies, rig, tex)
    if out.endswith(".glb"):
        write_area_glb(out, glb_rows(sky, sky_area, mapped, fwd, male))
        print("wrote", out)
        return
    body, (_, verts, _, area) = bodies[0].split("|")[0], mapped[0]
    ours = OurBody(body)   # the drawing reads normals from the body; the penis is left out of it
    area = area[:len(ours.verts)]
    names = sorted({sb.base_area(a) for a in sky_area} | {sb.base_area(a) for a in area})
    fig, axes = plt.subplots(2, 3, figsize=(20, 22))
    sb.draw(axes[0], sky.verts, sky.normals, sky_area, sb.SKYRIM_UP, sb.SKYRIM_FWD, names)
    sb.draw(axes[1], ours.verts, ours.normals, area, up, fwd, names)
    axes[0, 0].set_title("Skyrim %s -- front" % ("HIMBO" if male else "CBBE"))
    axes[1, 0].set_title("%s -- front" % os.path.basename(body))
    fig.suptitle("body areas: Skyrim's from BodySlide (top), carried onto ours by bone (bottom)")
    fig.savefig(out, dpi=80, bbox_inches="tight")
    counts = {a: int((area == a).sum()) for a in sorted(set(area))}
    print(json.dumps(counts))
    print("wrote", out)


def glb_rows(sky, sky_area, mapped, fwd, male, z=0.0):
    """viewer rows: Skyrim on the right as you face them, ours in a row to its left; z moves the whole row back"""
    if fwd @ np.array([0, 0, -1.0]) < 0.99:
        raise ValueError("our body does not face -z (%s): the side by side would be turned" % fwd)
    back = np.array([0, 0, z])
    rows = [("skyrim_male" if male else "skyrim", skyrim_to_ours(sky.verts) + np.array([1.0, 0, 0]) + back, sky.tris,
             sky_area)]
    return rows + [(n, v - np.array([0.9 * i, 0, 0]) + back, t, a) for i, (n, v, t, a) in enumerate(mapped)]


def build(male, bodies, rig, tex):
    """(Skyrim body, its areas, [(name, points, triangles, areas)] per body of ours, up, fwd)"""
    if male:
        sky = sb.Body(sb.MALE_NIF)
        sky_area, _ = sb.label(sky, sb.read_osd(sb.MALE_OSD), male=True)
        # the man's skeleton, under HIMBO's own bind where its skin has the bone (it has no neck)
        sky_rest = dict(skyrim_rest("m"), **{b: np.linalg.inv(m)[:3, 3] for b, m in sky.skin_to_bone.items()})
    else:
        sky = sb.Body()
        sky_area, _ = sb.label(sky, sb.read_osd(sb.BODY_OSD))
        by_slider = int(np.isin(sky_area, ["nipple_l", "nipple_r"]).sum())
        sky_area = sb.mark_dark(sky_area, sky.verts, sky.tris, sb.darkness(sb.BODY_TEX, sky.uvs),
                                -np.array([1.0, 0, 0]))
        print("skyrim nipple points: %d by the slider, %d by the skin; vulva %d" % (
            by_slider, np.isin(sky_area, ["nipple_l", "nipple_r"]).sum(), (sky_area == "vulva").sum()))
        sky_rest = skyrim_rest()
    mapped = []
    for item in bodies:
        # a body may name its own rig and skin: body.glb|rig|skin.png
        body, b_rig, b_tex = (item.split("|") + [rig, tex])[:3] if "|" in item else (item, rig, tex)
        tg = sr.Target(sp.donor(b_rig))
        rig_pos = {n: tg.w_t[k] for n, k in tg.skel.index.items()}
        rig_parent = {n: tg.skel.names[tg.skel.parent[k]] for n, k in tg.skel.index.items() if tg.skel.parent[k] >= 0}
        name = os.path.splitext(os.path.basename(body))[0]
        ours, area, up, fwd = map_body(name, OurBody(body), rig_pos, rig_parent, sky, sky_area, sky_rest, b_tex,
                                       male)
        verts, tris = ours.verts, ours.tris
        if male:
            verts, tris, area = add_penis(ours, area)
        mapped.append((name, verts, tris, area))
    return sky, sky_area, mapped, up, fwd


if __name__ == "__main__":
    main()
