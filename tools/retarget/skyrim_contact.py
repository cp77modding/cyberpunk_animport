"""Which area of the partner's body each effector touches in a Skyrim pair clip, frame by frame -- what our retarget
must reproduce. Her: CBBE, areas from BodySlide + skin. Him: HIMBO with genitals, areas from HIMBO's sliders + genital
bones (the clip has no genital bones, so they keep their bind: straight out, on the pelvis).
  python skyrim_contact.py <clip base without _0/_1> [pack]
  GIF=1      also writes the posed bodies for pair_contact.py's GIF
  TILT=deg   the shaft swung about GenitalsBase, as SOS bends it at runtime (+ = tip up); STEP=n frames between samples
Writes work/contact/sky_<clip>.json. Design and results: docs/design/opensex-port.md section 9.6."""
import functools, json, logging, os, sys
import numpy as np
from scipy.spatial import cKDTree
import skyrim_port as sp, skyrim_retarget as sr, skyrim_body as sb
import pair_reach
logging.disable(logging.CRITICAL)

OUT = os.path.join(sp.WORK, "contact")
UNIT = 0.0142875
NEAR = 0.04                 # m: a contact is skin within this of an effector point (both on skin)
GIF_STEP, SUB = 4, 3        # pair_contact.py's GIF: every 4th frame, every 3rd point
# body bones a vanilla clip skeleton lacks, and the bone each rides
DRIVER = {"Breast": "NPC Spine2 [Spn2]", "Butt": "NPC Pelvis [Pelv]", "Genital": "NPC Pelvis [Pelv]"}
SKY_BONES = ("NPC Pelvis [Pelv]", "NPC Spine [Spn0]", "NPC L Thigh [LThg]", "NPC R Thigh [RThg]")


def q2m(q):
    x, y, z, w = np.moveaxis(q, -1, 0)
    m = np.empty(q.shape[:-1] + (3, 3))
    m[..., 0, 0] = 1 - 2 * (y * y + z * z); m[..., 0, 1] = 2 * (x * y - z * w); m[..., 0, 2] = 2 * (x * z + y * w)
    m[..., 1, 0] = 2 * (x * y + z * w); m[..., 1, 1] = 1 - 2 * (x * x + z * z); m[..., 1, 2] = 2 * (y * z - x * w)
    m[..., 2, 0] = 2 * (x * z - y * w); m[..., 2, 1] = 2 * (y * z + x * w); m[..., 2, 2] = 1 - 2 * (x * x + y * y)
    return m


def mats(r, t):
    m = np.zeros(r.shape[:-1] + (4, 4))
    m[..., :3, :3], m[..., :3, 3], m[..., 3, 3] = q2m(r), t, 1
    return m


@functools.cache
def clip_world(clip, skel):
    """(bone index, world matrices (bones, frames, 4, 4), frames) of clip decoded on skel, read only: one read per
    process (the skin points and the hand fit both pose the clip), the decode kept on disk by pair_contact.decoded"""
    import pair_contact     # here: pair_contact imports this module
    idx, parent, _, _, rot, tra, frames = sr.read_clip(pair_contact.decoded(clip, skel))
    return idx, mats(*sr.world(parent, rot, tra)), frames


class Actor:
    """one side of the clip: its bones per frame, and its body parts skinned on them"""

    def __init__(self, row, parts, src):
        self.idx, self.W, self.frames = clip_world(os.path.join(src, row["file"]), sp.skeleton_of(row))
        self.parts = [self.skin_part(body) + (body,) for body, _ in parts]
        self.area = np.concatenate([a for _, a in parts])

    def skin_part(self, body):
        skin = []
        for b in body.bones:
            d = b if b in self.idx else next((v for k, v in DRIVER.items() if k in b), None)
            if d not in self.idx:
                raise KeyError("body bone %s: no clip bone drives it" % b)
            # a bone the clip lacks rides its driver, keeping its bind offset from it
            off = body.skin_to_bone[d] @ np.linalg.inv(body.skin_to_bone[b]) if d != b else np.eye(4)
            skin.append(self.W[self.idx[d]] @ off @ body.skin_to_bone[b])
        return np.stack(skin, 1), np.c_[body.verts, np.ones(len(body.verts))]

    def pose(self, f):
        # the weights times the bone matrices as one matrix product: a three-way einsum does it without BLAS
        out = []
        for skin, vh, body in self.parts:
            m = (body.weights @ skin[f].reshape(len(skin[f]), 16)).reshape(-1, 4, 4)
            out.append(np.einsum("vij,vj->vi", m, vh)[:, :3])
        return np.vstack(out)

    def bone(self, name, f):
        return self.W[self.idx[name], f, :3, 3]


def patch(a, names):
    return np.where(np.isin(a.area, names))[0]


def her_hands(her, f):
    """her hands are not in the CBBE body mesh: points along the clip's hand bones stand in"""
    return {"her %s hand" % s: np.linspace(her.bone("NPC %s Hand [%sHnd]" % (s, s), f),
                                           her.bone("NPC %s Finger22 [%sF22]" % (s, s), f), 6) for s in ("L", "R")}


def body_frame(a, f, pelv, spine, lt, rt):
    """(origin, [side, up, fwd]) of a's pelvis from its bones"""
    o = a.bone(pelv, f)
    up = a.bone(spine, f) - o
    up /= np.linalg.norm(up)
    side = a.bone(lt, f) - a.bone(rt, f)
    side -= up * (side @ up)
    side /= np.linalg.norm(side)
    return o, np.array([side, up, np.cross(side, up)])


def main():
    base = sys.argv[1]
    port, src = pair_reach.PORTS[sys.argv[2] if len(sys.argv) > 2 else "ostimng"]
    step = int(os.environ.get("STEP", 3))
    os.makedirs(OUT, exist_ok=True)
    rows = {}
    for r in json.load(open(os.path.join(port, "manifest.json"))):
        rows.setdefault(r["clip"], r)
    fb, mb = sb.Body(), sb.Body(sb.MALE_NIF)
    fa, _ = sb.label(fb, sb.read_osd(sb.BODY_OSD))
    fa = sb.mark_dark(fa, fb.verts, fb.tris, sb.darkness(sb.BODY_TEX, fb.uvs), -np.array([1.0, 0, 0]))
    ma, _ = sb.label(mb, sb.read_osd(sb.MALE_OSD), male=True)
    tilt = float(os.environ.get("TILT", 0))
    if tilt:
        gb = next(b for b in mb.bones if "GenitalsBase" in b)
        pivot = np.linalg.inv(mb.skin_to_bone[gb])[:3, 3]
        w = mb.weights[:, [j for j, b in enumerate(mb.bones) if "Genitals0" in b]].sum(1)[:, None]
        a = np.radians(tilt)
        rx = np.array([[1, 0, 0], [0, np.cos(a), -np.sin(a)], [0, np.sin(a), np.cos(a)]])
        mb.verts = mb.verts + w * ((mb.verts - pivot) @ rx.T + pivot - mb.verts)
    hb = sb.Body(sb.FEMALE_HEAD)
    print(base)
    him = Actor(rows[base + "_0"], [(mb, ma)], src)
    her = Actor(rows[base + "_1"], [(fb, fa), (hb, sb.head_areas(hb.verts))], src)
    F = min(him.frames, her.frames)
    eff = {(him, "his L hand"): patch(him, ["hand_l"]), (him, "his R hand"): patch(him, ["hand_r"]),
           (him, "his glans"): patch(him, ["glans"]), (him, "his penis"): patch(him, ["penis"]),
           (her, "her vulva"): patch(her, ["vulva"]), (her, "her lips"): patch(her, ["lips"])}
    # his penis root and length, for where her mouth sits against it
    gb = next(j for j, b in enumerate(mb.bones) if "GenitalsBase" in b)
    pivot = np.linalg.inv(mb.skin_to_bone[mb.bones[gb]])[:3, 3]
    gcols = [j for j, b in enumerate(mb.bones) if "Genital" in b]
    shaft = np.linalg.norm(mb.verts[mb.weights[:, gcols].sum(1) > 0.5] - pivot, axis=1).max()
    dump = {"step": step, "frames": F, "eff": {}, "mouth": []}
    for f in range(0, F, step):
        pv, mv = her.pose(f), him.pose(f)
        root = (him.parts[0][0][f][gb] @ np.r_[pivot, 1])[:3]
        _, ax = body_frame(him, f, *SKY_BONES)
        dump["mouth"].append(list(ax @ (pv[eff[(her, "her lips")]].mean(0) - root) / shaft))
        trees, posed = {her: cKDTree(pv), him: cKDTree(mv)}, {her: pv, him: mv}
        pts = {k: posed[a][idx] for (a, k), idx in eff.items()}
        pts.update(her_hands(her, f))
        for k, p in pts.items():
            other = him if k.startswith("her") else her
            d, i = trees[other].query(p, workers=int(os.environ.get("WORKERS", 4)))
            j = int(np.argmin(d))
            dump["eff"].setdefault(k, []).append([float(d[j] * UNIT), str(other.area[i[j]])])
    with open(os.path.join(OUT, "sky_%s.json" % base), "w") as fh:
        json.dump(dump, fh)
    print("  shaft %.1f cm; mouth against the root, in shafts (side, up, fwd), median %s" % (
        100 * UNIT * shaft, np.round(np.median(dump["mouth"], 0), 2)))
    print("\nnearest partner skin (frames every %d; contact = within %.0f cm)" % (step, NEAR * 100))
    for k, h in dump["eff"].items():
        d = np.array([x for x, _ in h])
        top = {}
        for x, a in h:
            if x < NEAR:
                top[a] = top.get(a, 0) + 1
        print("  %-12s in contact %3d%% of frames, distance min/median %4.1f / %4.1f cm, on %s" % (
            k, 100 * (d < NEAR).mean(), 100 * d.min(), 100 * np.median(d),
            ", ".join("%s %d%%" % (a, 100 * c / len(h)) for a, c in sorted(top.items(), key=lambda kv: -kv[1])[:3])
            or "-"))
    if os.environ.get("GIF") == "1":
        hands = her_hands(her, 0)
        gm = [him.pose(f)[::SUB] * UNIT for f in range(0, F, GIF_STEP)]
        gf = [np.vstack([her.pose(f)[::SUB]] + list(her_hands(her, f).values())) * UNIT for f in range(0, F, GIF_STEP)]
        np.savez(os.path.join(OUT, "skygif_%s.npz" % base), him=np.stack(gm), her=np.stack(gf),
                 him_area=him.area[::SUB].astype(str),
                 her_area=np.r_[her.area[::SUB].astype(str), ["hand_l"] * sum(len(p) for p in hands.values())])
        print("wrote the GIF poses: %d frames" % len(gm))


if __name__ == "__main__":
    main()
