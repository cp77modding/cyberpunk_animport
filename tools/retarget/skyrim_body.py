"""The Skyrim body a clip was authored on, read from its nif, with every skin point labelled by body area.

Areas come from BodySlide: each slider in the body's .osd moves only its own part of the skin, so the points a
slider moves most are that area, named by the body's authors. A point no chosen slider claims takes the area of
the bone that moves it. Left and right are the point's side of the body.

  python tools/retarget/skyrim_body.py <out.png> [male]   the CBBE body (or HIMBO's), coloured by area, three views
"""
import os
import struct
import sys

import numpy as np

NIFLY = os.environ.get("NIFLY_DIR", os.path.expandvars(
    r"%APPDATA%\Blender Foundation\Blender\4.5\scripts\addons\io_scene_nifly"))
CBBE_MOD = r"D:\mods\ModOrganizer\Portable_Skyrim_Special_Edition\mods\Caliente's Beautiful Bodies Enhancer -CBBE-"
CBBE = os.path.join(CBBE_MOD, r"CalienteTools\BodySlide\ShapeData\CBBE")
BODY_NIF = os.path.join(CBBE, "CBBE Body Physics.nif")   # the base body plus breast and butt bones
BODY_OSD = os.path.join(CBBE, "CBBE Body.osd")

# area: the sliders that define it (a point's share is its move over that slider's largest)
AREAS = {
    "nipple": ["NippleSize"],
    "navel": ["NavelEven"],
    "breast": ["Breasts", "BreastsSmall", "BreastCleavage"],
    "groin": ["Groin", "CrotchGap"],
    "butt_crack": ["ButtCrack"],
    "butt": ["Butt", "BigButt", "RoundAss"],
    "belly": ["Belly", "BigBelly", "MuscleAbs"],
    "thigh_inner": ["ThighInsideThicc_v2"],
    "thigh_outer": ["ThighOutsideThicc_v2"],
    "thigh": ["Thighs", "SlimThighs"],
    "knee": ["KneeShape"],
    "calf": ["CalfSize"],
    "ankle": ["AnkleSize"],
    "hips": ["Hips", "Hipbone"],
    "waist": ["waist"],
    "back": ["Back", "MuscleBack_v2"],
    "chest": ["MusclePecs", "SternumDepth"],
    "ribs": ["RibsProminance"],
    "clavicle": ["Clavicle_v2"],
    "wrist": ["WristSize"],
    "neck": ["NeckSeam"],
}
# listed most specific first: the first area whose slider moves a point enough takes it (a nipple is not a breast)
SHARE = 0.25        # a point belongs to an area when the area's slider moves it at least this share of its most
SHARE_OF = {"nipple": 0.5, "navel": 0.5, "butt_crack": 0.5, "breast": 0.4}   # sliders that drag the skin around
SIDED = {"nipple", "breast", "pecs", "butt", "thigh_inner", "thigh_outer", "thigh", "knee", "calf", "ankle", "hips",
         "clavicle", "wrist"}

# the man: HIMBO's body with its genitals merged in, and HIMBO's sliders; the penis is its own bones' (no slider moves it)
HIMBO = os.path.join(os.path.dirname(CBBE_MOD), "Highly Improved Male Body Overhaul",
                     r"CalienteTools\BodySlide\ShapeData\HIMBO", "HIMBO Ref - Merged Body with Genitals")
MALE_NIF, MALE_OSD = HIMBO + ".nif", HIMBO + ".osd"
MALE_AREAS = {
    "nipple": ["NipsAreola", "NipsTips"],
    "navel": ["Belly Button Match"],
    "pecs": ["PecsSize", "PecsMass"],
    "butt_crack": ["ButtCleft"],
    "butt": ["ButtBooty", "ButtRoundy"],
    "belly": ["TorsoBelly", "TorsoFlatAbs"],
    "thigh": ["LegsThigh"],
    "knee": ["LegsKneePit"],
    "calf": ["LegsCalfSize"],
    "hips": ["TorsoHip"],
    "waist": ["TorsoWaistSize"],
    "back": ["TorsoBackShape", "TorsoBackSize"],
    "clavicle": ["PecsClavicle"],
}
MALE_SHARE_OF = {"nipple": 0.5, "navel": 0.5, "butt_crack": 0.5}
# genital bones: a point that much theirs is that area, the tip first
GENITALS = (("glans", ["Genitals06", "Genitals05"]), ("scrotum", ["GenitalsScrotum"]),
            ("penis", ["GenitalsBase", "Genitals01", "Genitals02", "Genitals03", "Genitals04"]))
GENITAL_SHARE = 0.5

# her head: the CBBE body stops at the neck. A loose vanilla-shaped head, its points in the head bone's own space
FEMALE_HEAD = os.path.join(os.path.dirname(CBBE_MOD), "Baka Haeun UNP",
                           r"meshes\actors\character\ygNord\femalehead.nif")
LIPS = {"front": 8.0, "z": (-3.0, -1.0), "half_width": 2.6}   # units in head space; nose tip ~(0, 11.2, 0.6)


def head_areas(v):
    """lips / face / head on a head mesh in head-bone space (faces +y, z up)"""
    area = np.array(["head"] * len(v), dtype=object)
    area[v[:, 1] > 3.0] = "face"
    lips = (v[:, 1] > LIPS["front"]) & (v[:, 2] > LIPS["z"][0]) & (v[:, 2] < LIPS["z"][1]) & \
           (np.abs(v[:, 0]) < LIPS["half_width"])
    area[lips] = "lips"
    return area
# fallback by the bone with the largest weight
BONE_AREA = {"Pelvis": "hips", "Spine]": "belly", "Spine1": "belly", "Spine2": "chest", "Thigh": "thigh",
             "Calf": "calf", "Foot": "foot", "Clavicle": "clavicle", "UpperArm": "upper_arm",
             "UpperarmTwist": "upper_arm", "Forearm": "forearm", "ForearmTwist": "forearm", "Hand": "hand",
             "Finger": "hand", "Toe": "foot", "Head": "head", "Neck": "neck", "Breast": "breast", "Butt": "butt"}


def nifly():
    sys.path.insert(0, NIFLY)
    import pynifly  # noqa: E402  (PyNifly's reader; it needs only ctypes and its DLL)
    if pynifly.NifFile.nifly is None:
        pynifly.NifFile.Load(os.path.join(NIFLY, "NiflyDLL.dll"))
    return pynifly


def read_osd(path):
    """{slider data name: (vertex indices, offsets (n, 3))} from a BodySlide .osd"""
    b = open(path, "rb").read()
    if b[:4] != b"\x00DSO":
        raise ValueError("%s is not a BodySlide .osd" % path)
    count, o, out = struct.unpack_from("<I", b, 8)[0], 12, {}
    for _ in range(count):
        n = b[o]
        name = b[o + 1:o + 1 + n].decode("utf-8")
        o += 1 + n
        k = struct.unpack_from("<H", b, o)[0]
        rec = np.frombuffer(b, dtype=np.dtype([("i", "<u2"), ("d", "<f4", 3)]), count=k, offset=o + 2)
        out[name] = (rec["i"].astype(np.int64), rec["d"].astype(np.float64))
        o += 2 + k * 14
    if o != len(b):
        raise ValueError("%s: %d bytes left over" % (path, len(b) - o))
    return out


def normals(verts, tris):
    """per-point unit normals, the area-weighted sum of the triangles around it"""
    a, b, c = verts[tris[:, 0]], verts[tris[:, 1]], verts[tris[:, 2]]
    f = np.cross(b - a, c - a)
    n = np.zeros_like(verts)
    for k in range(3):
        np.add.at(n, tris[:, k], f)
    return n / np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-12)


class Body:
    """A skinned Skyrim body: rest points, triangles, bone weights and skin-to-bone transforms, in nif units."""

    def __init__(self, nif=BODY_NIF, shape=0):
        P = nifly()
        s = P.NifFile(nif).shapes[shape]
        self.name = s.name
        self.verts = np.array(s.verts, dtype=np.float64)
        self.tris = np.array(s.tris, dtype=np.int64)
        self.normals = normals(self.verts, self.tris)   # the CBBE nif stores none
        self.uvs = np.array(s.uvs, dtype=np.float64)
        self.bones = list(s.bone_names)
        self.weights = np.zeros((len(self.verts), len(self.bones)))
        for j, b in enumerate(self.bones):
            for v, w in s.bone_weights[b]:
                self.weights[v, j] = w
        self.skin_to_bone = {}
        for b in self.bones:
            t = s.get_shape_skin_to_bone(b)
            m = np.eye(4)
            m[:3, :3] = np.array([list(r) for r in t.rotation]) * t.scale
            m[:3, 3] = list(t.translation)
            self.skin_to_bone[b] = m


def genitals(body):
    """area per point from the genital bones, '' where they do not own it"""
    area = np.array([""] * len(body.verts), dtype=object)
    for name, keys in GENITALS:
        cols = [j for j, b in enumerate(body.bones) if any("[" in b and k in b for k in keys)]
        own = body.weights[:, cols].sum(1) if cols else np.zeros(len(area))
        area[(own >= GENITAL_SHARE) & (area == "")] = name
    return area


def label(body, osd, male=False):
    """(area per point, share per point): the first listed area moving it enough, else the heaviest bone's; sided
    areas get _l/_r. male: HIMBO's sliders, the genitals first by their bones"""
    n = len(body.verts)
    areas, prefix = (MALE_AREAS, "HIMBO Ref") if male else (AREAS, "BaseShapeHR")
    share_of = MALE_SHARE_OF if male else SHARE_OF
    best = np.zeros(n)
    area = genitals(body) if male else np.array([""] * n, dtype=object)
    for name, sliders in areas.items():
        s = np.zeros(n)
        for sl in sliders:
            key = prefix + sl
            if key not in osd:
                raise KeyError("no slider %s in the .osd" % sl)
            idx, d = osd[key]
            mag = np.linalg.norm(d, axis=1)
            s[idx] = np.maximum(s[idx], mag / max(mag.max(), 1e-9))
        take = (s >= share_of.get(name, SHARE)) & (area == "")
        best[take], area[take] = s[take], name
    heavy = np.array(body.bones)[np.argmax(body.weights, axis=1)]
    for i in np.where(area == "")[0]:
        area[i] = next((a for k, a in BONE_AREA.items() if k in heavy[i]), "other")
    x = body.verts[:, 0]
    for i in range(n):
        if area[i] in SIDED or area[i] in ("foot", "hand", "upper_arm", "forearm"):
            area[i] += "_l" if x[i] < 0 else "_r"   # the body faces +y; its left is -x (NPC L Thigh sits at x -6.6)
    return area, best


BODY_TEX = os.path.join(CBBE_MOD, r"textures\actors\character\female\femalebody_1.dds")
AREOLA = 0.4        # a point is areola when its skin is at least this share as dark as the side's darkest point


def darkness(tex, uvs):
    """per point: how much darker its skin is than the skin around it, as a share (0 = as light)"""
    from PIL import Image, ImageFilter
    im = Image.open(tex).convert("L")
    w, h = im.size
    near = np.asarray(im.filter(ImageFilter.GaussianBlur(w / 512)), float)
    wide = np.asarray(im.filter(ImageFilter.GaussianBlur(w / 40)), float)
    d = (wide - near) / np.maximum(wide, 1)
    x = np.clip((uvs[:, 0] % 1) * w, 0, w - 1).astype(int)
    y = np.clip((uvs[:, 1] % 1) * h, 0, h - 1).astype(int)
    return d[y, x]


def neighbours(verts, tris):
    """per point, the points it shares a triangle with or sits on: a seam splits a point into copies"""
    from scipy.spatial import cKDTree
    nbr = [[] for _ in range(len(verts))]
    for a, b, c in tris:
        nbr[a] += (b, c)
        nbr[b] += (a, c)
        nbr[c] += (a, b)
    span = np.ptp(verts, axis=0).max()
    for a, b in cKDTree(verts).query_pairs(span * 1e-5):
        nbr[a].append(b)
        nbr[b].append(a)
    return nbr


def dark_patch(m, dark, nbr, what):
    """the points of m joined to m's darkest point through skin at least AREOLA as dark as it"""
    if not m.any():
        raise ValueError("no skin to look for the %s on" % what)
    seed = np.where(m)[0][np.argmax(dark[m])]
    keep = m & (dark >= AREOLA * dark[seed])
    seen, todo = {seed}, [seed]
    while todo:
        for j in nbr[todo.pop()]:
            if keep[j] and j not in seen:
                seen.add(j)
                todo.append(j)
    return np.fromiter(seen, int)


def mark_dark(area, verts, tris, dark, left):
    """relabel from the skin texture, which outlines these far more sharply than any slider: each breast's areola as
    nipple_l / nipple_r, and the vulva inside the groin; each is the dark skin joined to its darkest point.
    left: the body's left as a direction"""
    base = np.array([base_area(a) for a in area])
    nbr = neighbours(verts, tris)
    area = area.copy()
    area[base == "nipple"] = "breast"   # the slider's guess goes; the side is set below
    on_chest = np.isin(base, ["breast", "nipple", "chest"])
    for side, sign in (("_l", 1), ("_r", -1)):
        area[dark_patch(on_chest & (sign * (verts @ left) > 0), dark, nbr, "nipple" + side)] = "nipple" + side
    for i in np.where(area == "breast")[0]:
        area[i] = "breast" + ("_l" if verts[i] @ left > 0 else "_r")
    groin = np.isin(base, ["groin", "vulva"])   # a transferred body brings Skyrim's vulva: find its own
    area[groin] = "groin"
    area[dark_patch(groin, dark, nbr, "vulva")] = "vulva"
    return area


SKYRIM_UP, SKYRIM_FWD = np.array([0, 0, 1.0]), np.array([0, 1.0, 0])


def base_area(a):
    return a[:-2] if a[-2:] in ("_l", "_r") else a


def draw(axes, v, nrm, area, up, fwd, names):
    """front / back / side-from-her-left point views of a labelled body; names: every base area, for fixed colours"""
    import matplotlib.pyplot as plt
    hue = {a: plt.get_cmap("hsv")(i / len(names)) for i, a in enumerate(names)}
    left = np.cross(up, fwd)
    h = v @ up
    # front: seen from ahead, her left on our right; back: from behind; side: from her left, her front to our left
    views = (("front", v @ left, v @ fwd, nrm @ fwd), ("back", -(v @ left), -(v @ fwd), -(nrm @ fwd)),
             ("side, from her left", -(v @ fwd), v @ left, nrm @ left))
    for ax, (title, x, near, facing) in zip(axes, views):
        seen = facing > 0.1                      # only skin turned toward us
        order = np.where(seen)[0][np.argsort(near[seen])]
        ax.scatter(x[order], h[order], s=3, c=[hue[base_area(a)] for a in area[order]], linewidths=0)
        for a in sorted(set(area)):
            m = (area == a) & seen
            if m.sum() < 3:
                continue
            ax.text(np.median(x[m]), np.median(h[m]), a, fontsize=7, ha="center", va="center",
                    bbox=dict(boxstyle="round,pad=0.1", fc="white", ec="none", alpha=0.7))
        ax.set_aspect("equal")
        ax.set_title(title)
        ax.axis("off")


def main():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    out = sys.argv[1]
    male = len(sys.argv) > 2 and sys.argv[2] == "male"
    body = Body(MALE_NIF) if male else Body()
    area, _ = label(body, read_osd(MALE_OSD if male else BODY_OSD), male)
    v = body.verts
    fig, axes = plt.subplots(1, 3, figsize=(20, 12))
    draw(axes, v, body.normals, area, SKYRIM_UP, SKYRIM_FWD, sorted({base_area(a) for a in area}))
    fig.suptitle("%s: %d points, areas from BodySlide sliders" % (body.name, len(v)))
    fig.savefig(out, dpi=90, bbox_inches="tight")
    print("wrote", out)


if __name__ == "__main__":
    main()
