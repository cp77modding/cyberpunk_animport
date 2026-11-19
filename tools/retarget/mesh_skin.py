"""Skin points for the interaction mesh whose source is Skyrim's own skin, not our offsets carried on Skyrim's bones.

The mesh's other surface points (interaction_mesh.Side.virtual) take their source position from OUR body's offset on
the Skyrim segment, so the mesh keeps a hand's place against her JOINTS, never against her skin as Skyrim has it. On
our differently shaped woman that left his palm 5.9 cm off her buttock in a cowgirl where Skyrim's lies 1 cm off.
These points give the mesh the real relation: his palm (the skin of the hand's metacarpals) and her buttocks, each
at its own body's place, and its source posed from Skyrim's bodies (HIMBO, CBBE) on the clip.

  pair_contact.py with MESH_SKIN=1 (MESH=1): passed to interaction_mesh.adapt
"""
import functools

import numpy as np

import pair_reach
import skyrim_body as sb
import skyrim_contact as sc
import skyrim_retarget as sr
import retarget_glb as rg

PALM = ("Index", "Middle", "Ring", "Pinky")
ROOT_SHARE = 0.15       # his penis root: this share of its points nearest the pelvis joint
MOUTH_HALF = 0.02       # m: half his mouth's width
ANUS_SHARE = 0.10      # her anus: this share of the butt crack nearest the vulva, where the crack ends
NG_INTO = {"vaginalsex": "vulva", "analsex": "anus"}   # as tools/opensex/scene_files.py names the game's canal


def entry_of(base, pack):
    """her opening a clip's sex goes into: 'vulva', 'anus', or None (no penetrative act). OpenSex's Sx is vaginal"""
    import json, os
    port, _ = pair_reach.PORTS[pack]
    for s in json.load(open(os.path.join(port, "scenes.json"), encoding="utf-8")):
        clips = {c for a in s.get("anims", []) for c in (a.get("clips") or []) if c}
        if not any(c.rsplit("_", 1)[0] == base for c in clips):
            continue
        for a in s.get("actions", []):
            if isinstance(a, dict) and a.get("type") in NG_INTO:
                return NG_INTO[a["type"]]
        parts = s["id"].split("|")
        if len(parts) > 2 and parts[2] == "Sx":
            return "vulva"
    return None


def opening(verts, area, entry):
    """her entry's points: the vulva as mapped, or the anus, the end of the butt crack nearest the vulva"""
    vulva = np.where(area == "vulva")[0]
    if entry == "vulva" or not len(vulva):
        return vulva
    crack = np.where(area == "butt_crack")[0]
    d = np.linalg.norm(verts[crack] - verts[vulva].mean(0), axis=1)
    return crack[d <= np.quantile(d, ANUS_SHARE)]


def root(verts, area, pelvis):
    """his penis root: the penis points nearest the pelvis joint"""
    pen = np.where(np.isin(area, ["penis", "glans"]))[0]
    d = np.linalg.norm(verts[pen] - pelvis, axis=1)
    return pen[d <= np.quantile(d, ROOT_SHARE)]


def his_mouth(him):
    """his lips on our head (no lips mesh for a man): the front-most centimetre of the head's middle, 0.5-3 cm under
    the Head joint, where our woman's lips sit"""
    head = np.where(np.isin(him.area, ["face", "head"]))[0]
    v = him.verts[head] - him.tg.w_t[him.idx["Head"]]
    band = (np.abs(v[:, 0]) < MOUTH_HALF) & (v[:, 1] > -0.03) & (v[:, 1] < -0.005)
    return head[band & (v[:, 2] < v[band, 2].min() + 0.01)]


@functools.cache
def sky_bodies():
    """read only: one load per process, shared by the skin points and the hand fit, and by a batch worker's clips"""
    fb, mb = sb.Body(), sb.Body(sb.MALE_NIF)
    fa, _ = sb.label(fb, sb.read_osd(sb.BODY_OSD))
    fa = sb.mark_dark(fa, fb.verts, fb.tris, sb.darkness(sb.BODY_TEX, fb.uvs), -np.array([1.0, 0, 0]))   # the vulva, as skyrim_contact
    ma, _ = sb.label(mb, sb.read_osd(sb.MALE_OSD), male=True)
    return (mb, ma), (fb, fa)


def to_ours(p):
    """Skyrim world points (units, z up) to the mesh's source space (metres, glTF axes), as the joints go"""
    return rg.qrot(sr.C, p) * sc.UNIT


def heel(verts, ix, wrist, knuckles):
    """the palm's points on the wrist's half, along the wrist-to-knuckles axis"""
    t = (verts[ix] - wrist) @ (knuckles - wrist)
    return ix[t <= np.median(t)]


def points(acts, base, pack, F, log=print):
    """{act: {name: (segment, our bind point, Skyrim's (F, 3))}} for a man and a woman; {} for any other cast"""
    if len(acts) != 2 or [a.male for a in acts] != [True, False]:
        log("mesh_skin: %s is not a man and a woman, no skin points" % base)
        return {}
    him, her = acts
    _, src = pair_reach.PORTS[pack]
    (mb, ma), (fb, fa) = sky_bodies()
    hb = sb.Body(sb.FEMALE_HEAD)
    ha = sb.head_areas(hb.verts)
    s_him, s_her = sc.Actor(him.row, [(mb, ma)], src), sc.Actor(her.row, [(fb, fa), (hb, ha)], src)
    n = min(F, s_him.frames, s_her.frames)
    if n < F:
        raise ValueError("%s: Skyrim's clip has %d frames, the solve %d" % (base, n, F))
    s_dom = np.array(mb.bones)[np.argmax(mb.weights, 1)]
    body = him.parts_src[0][0]
    dom = np.array(body.bones)[np.argmax(body.weights, 1)]
    her_area = her.area[:len(her.parts_src[0][0].verts)]
    want = {}   # name: (actor, segment, our bind point, Skyrim actor, Skyrim point indices)
    for S in ("Left", "Right"):
        # three points per hand, so the mesh keeps the palm's roll against her and not only its centre
        sb_ = lambda b: "NPC %s %s [%s%s]" % (S[0], b, S[0], {"Hand": "Hnd"}.get(b, b.replace("Finger", "F")))
        o_ix, o_pk = np.where(dom == S + "HandIndex1")[0], np.where(dom == S + "HandPinky1")[0]
        s_ix, s_pk = np.where(s_dom == sb_("Finger10"))[0], np.where(s_dom == sb_("Finger40"))[0]
        o_heel = heel(body.verts, np.where(np.isin(dom, [S + "InHand" + f for f in PALM]))[0],
                      him.tg.w_t[him.idx[S + "Hand"]], body.verts[np.r_[o_ix, o_pk]].mean(0))
        s_heel = heel(mb.verts, np.where(s_dom == sb_("Hand"))[0],
                      np.linalg.inv(mb.skin_to_bone[sb_("Hand")])[:3, 3], mb.verts[np.r_[s_ix, s_pk]].mean(0))
        for k, o, s in (("heel", o_heel, s_heel), ("index", o_ix, s_ix), ("pinky", o_pk, s_pk)):
            if not len(o) or not len(s):
                raise ValueError("%s %s: %d points on ours, %d on Skyrim's" % (S, k, len(o), len(s)))
            want["s_%s_%s" % (k, S)] = (him, S + "Hand", body.verts[o].mean(0), s_him, s)
    for side in ("l", "r"):
        ours = np.where(her_area == "butt_" + side)[0]
        sky = np.where(fa == "butt_" + side)[0]
        if not len(ours) or not len(sky):
            raise ValueError("butt_%s: %d points on ours, %d on Skyrim's" % (side, len(ours), len(sky)))
        want["s_butt_" + side] = (her, "Hips", her.parts_src[0][0].verts[ours].mean(0), s_her, sky)
    # both mouths: his face point is the centre of his face, so a kiss Skyrim has 0.8 cm off kept 8 cm (missionary hug)
    o_lp, s_lp = np.where(her.area == "lips")[0], len(fb.verts) + np.where(ha == "lips")[0]
    o_mo, s_mo = his_mouth(him), np.where((ma == "head") & (sb.head_areas(
        (np.c_[mb.verts, np.ones(len(mb.verts))] @ mb.skin_to_bone["NPC Head [Head]"].T)[:, :3]) == "lips"))[0]
    for k, o, s in (("lips", o_lp, s_lp), ("mouth", o_mo, s_mo)):
        if not len(o) or not len(s):
            raise ValueError("%s: %d points on ours, %d on Skyrim's" % (k, len(o), len(s)))
    want["s_lips"] = (her, "Head", her.verts[o_lp].mean(0), s_her, s_lp)
    want["s_mouth"] = (him, "Head", him.verts[o_mo].mean(0), s_him, s_mo)
    # the genital contact, as Skyrim has it on the skin: our retarget's pelvis turn put her vulva 11.6 cm up his belly
    # in a cowgirl (opensex-port.md 9.7). Skyrim's genital bones keep their bind, so his root is good and his tip not
    entry = entry_of(base, pack)
    if entry:
        o_in, s_in = opening(her.verts, her.area, entry), opening(fb.verts, fa, entry)
        o_rt = root(him.verts, him.area, him.tg.w_t[him.idx["Hips"]])
        s_rt = root(mb.verts, ma, np.linalg.inv(mb.skin_to_bone["NPC Pelvis [Pelv]"])[:3, 3])
        for k, o, s in (("entry", o_in, s_in), ("root", o_rt, s_rt)):
            if not len(o) or not len(s):
                raise ValueError("%s %s: %d points on ours, %d on Skyrim's" % (entry, k, len(o), len(s)))
        want["s_entry"] = (her, "Hips", her.verts[o_in].mean(0), s_her, s_in)
        want["s_root"] = (him, "Hips", him.verts[o_rt].mean(0), s_him, s_rt)
    src = {k: np.zeros((F, 3)) for k in want}
    for f in range(F):
        posed = {s_him: s_him.pose(f), s_her: s_her.pose(f)}
        for k, (_, _, _, sa, ix) in want.items():
            src[k][f] = posed[sa][ix].mean(0)
    out = {him: {}, her: {}}
    for k, (a, seg, p, _, _) in want.items():
        out[a][k] = (seg, p, to_ours(src[k]))
    log("mesh_skin: %s skin points %s" % (base, ", ".join(want)))
    return out
