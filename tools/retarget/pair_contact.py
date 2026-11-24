"""Which area of a partner each effector touches, on OUR bodies posed on a retargeted clip's actors (_0, _1, ...), each
by its sex: our woman (body + head, lips from the game's own lips-makeup mesh) or our man (body + head + penis), the
pair slid as the converter ships it (pair_shift), areas from body_area_map. The report skyrim_contact.py gives for
Skyrim's bodies.
  python pair_contact.py <clip base without _0/_1> [pack]
  MESH=1      the clip through the interaction mesh first (interaction_mesh.py); STEPS=n morph steps (5; the paper's 10)
  SAVE=1      with MESH=1, a clip that is not broken saved to <port>/mesh/, which skyrim_port.py's glbs stage plays
  MESH_SKIN=1 with MESH=1, his palm and her buttocks sourced from Skyrim's skin (mesh_skin.py)
  HANDFIT=1   with MESH=1, a man and a woman: his hands turned and reached to her skin as Skyrim's (hand_fit.py)
  GIF=1       a man and a woman: Skyrim | our retarget | after, side by side (run skyrim_contact.py with GIF=1 first)
  POSE=1      with MESH=1, solved in our rig's own joint turns instead of free points (pose_solve.py)
  TOUCH_TIES=1 with MESH=1, every touch Skyrim's skin has held by a tie (touch_ties.py)
  TOUCHES=1   every area Skyrim's skin touches, kept or lost on ours, and touches ours invents (touches.py)
  HEADDIST=1  a man and a woman: his hands to her head frame by frame, beside what Skyrim touches there
  BODY_F=big  every woman on the big woman's body and head, on man_big as the game plays her (no SAVE: no set has it)
  FRAMES=n    the first n frames only; STEP=n frames between contact samples
  WORKERS=n   cores for the skin lookups (4) when CuPy is missing; with it, they run on the GPU
Writes into work/contact/. Design and results: docs/design/opensex-port.md section 9.6."""
import hashlib, json, logging, os, shutil, sys, tempfile
import numpy as np
from scipy.spatial import cKDTree
try:
    import cupy as cp    # the contact report on the GPU; without it, cKDTree on the CPU
except ImportError:
    cp = None
import skyrim_port as sp, skyrim_retarget as sr, skyrim_body as sb, body_area_map as bm, retarget_glb as rg
import pair_reach
import pair_batch
import interaction_mesh as im
import mesh_skin
logging.disable(logging.CRITICAL)

OUT = os.path.join(sp.WORK, "contact")
GLB = os.path.dirname(bm.BODY)
HEAD_F = os.path.join(GLB, "h0_000_wa__basehead.glb")
LIPS = os.path.join(GLB, "hx_000_wa_c__basehead_lc_makeup_lips_01.glb")
HEAD_M = os.path.join(GLB, "h0_000_ma_c__basehead.glb")
BIG_F = os.environ.get("BODY_F") == "big"
# the big woman: no rig of her own (woman_big is a muscle rig nothing plays on), man_big's body and head bones
WOMAN = ("man_big", os.path.join(GLB, "t0_000_wba_base__full.glb"), os.path.join(GLB, "h0_000_wba_c__basehead.glb")) \
    if BIG_F else ("woman_base", bm.BODY, HEAD_F)
NEAR = 0.04       # m: a contact is skin within this of an effector point
SUB = 3           # GIF: every 3rd point drawn
GIF_STEP = 4      # GIF: every 4th frame, as skyrim_contact.py writes Skyrim's
SKY_FLIP = -1     # Skyrim's panel mirrored to face the way ours do
WORKERS = int(os.environ.get("WORKERS", 4))


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


class Part:
    """points of a skinned glb with their weights and inverse binds"""

    def __init__(self, path, verts=None, weights=None, bones=None, ibm=None, ride=None):
        self.path, self.ride = path, ride
        doc, buf = rg.read_glb(path)
        skin = doc["skins"][0]
        self.bones = bones or [doc["nodes"][j]["name"] for j in skin["joints"]]
        self.ibm = ibm if ibm is not None else \
            rg.accessor(doc, buf, skin["inverseBindMatrices"]).reshape(-1, 4, 4).astype(np.float64).transpose(0, 2, 1)
        if verts is None:
            b = bm.OurBody(path)
            verts, weights = b.verts, b.weights
        self.verts, self.weights = verts, weights


def driver(part, b, rig):
    """the glbs are flat (every joint under Armature): a bone the rig lacks takes the part's own fallback (Head for
    the head, Hips for the penis) or, on the body, the main bone it sits nearest"""
    if b in rig:
        return b
    return part.ride or part.main[b]


def decoded(clip, skel):
    """the clip decoded on skel, kept under work/contact/decoded/ by the two files' bytes, so a copy serves another
    machine: every body solves the same clips, and a decode runs two tools"""
    h = hashlib.sha1()
    for p in (clip, skel):
        with open(p, "rb") as fh:
            h.update(hashlib.sha1(fh.read()).digest())
    out = os.path.join(OUT, "decoded", h.hexdigest()[:20] + ".xml")
    if os.path.isfile(out):
        return out
    os.makedirs(os.path.dirname(out), exist_ok=True)
    tmp_out = "%s.%d.tmp" % (out, os.getpid())
    try:
        with tempfile.TemporaryDirectory() as tmp:
            shutil.copyfile(sp.decode(clip, skel, tmp, pair_reach.CFG), tmp_out)
        os.replace(tmp_out, out)
    except PermissionError:
        # Windows refuses to replace a file another worker, decoding the same clip, already has open
        if not os.path.isfile(out):
            raise
        print("decoded: %s written by another worker first" % os.path.basename(out))
    finally:
        if os.path.exists(tmp_out):
            os.remove(tmp_out)
    return out


class Actor:
    """one actor of a clip: our rig retargeted on its clip, Skyrim's joints under our names, our body parts on it"""

    def __init__(self, row, parts, port, src):
        if row["sex"] not in ("m", "f"):
            raise ValueError("%s: sex %r, want m or f" % (row["clip"], row["sex"]))
        self.male = row["sex"] == "m"
        self.rig = row["rig"] if self.male else WOMAN[0]
        tg = sr.Target(sp.donor(self.rig))
        rig_pos = {n: tg.w_t[k] for n, k in tg.skel.index.items()}
        rig_parent = {n: tg.skel.names[tg.skel.parent[k]] for n, k in tg.skel.index.items() if tg.skel.parent[k] >= 0}
        for p, _ in parts:
            if not p.ride:
                if (p.path, self.rig) not in _MAIN:
                    _MAIN[p.path, self.rig] = bm.OurBody(p.path).main_of(rig_parent, rig_pos)
                p.main = _MAIN[p.path, self.rig]
        xml = decoded(os.path.join(src, row["file"]), sp.skeleton_of(row))   # the actor's skeleton, not this body's
        rot, tra = sr.retarget(xml, tg)
        s_idx, s_parent, _, _, s_rot, s_tra, _ = sr.read_clip(xml)
        _, s_wt = sr.to_gltf(*sr.world(s_parent, s_rot, s_tra))
        self.src_j = {tn: s_wt[s_idx[v[0]]] for tn, v in sr.MAP.items() if v[0] in s_idx}   # glTF axes, Skyrim units
        shifts = pair_reach.load(port)
        k = pair_reach.key(row)
        if k in shifts:
            pair_reach.apply_shift(tg.skel, rot, tra, np.array(shifts[k]["shift"]))
        self.tg, self.rot, self.tra, self.row = tg, rot, tra, row
        self.rest = mats(tg.w_r, tg.w_t)
        self.idx, self.frames = tg.skel.index, rot.shape[1]
        self.parts_src = parts
        self.verts = np.vstack([p.verts for p, _ in parts])     # bind = the rig's rest pose
        self.area = np.concatenate([a for _, a in parts])
        self.refresh()

    def refresh(self):
        """bone matrices and skins from the current rot/tra"""
        self.w_r, self.w_t = self.tg.skel.world_pose(self.rot, self.tra)
        M = mats(self.w_r, self.w_t)
        self.parts = []
        for p, _ in self.parts_src:
            # the body's bind has the rig rest's positions but other bone frames: skin from the rig's rest
            skin = [M[self.idx[driver(p, b, self.idx)]] @ np.linalg.inv(self.rest[self.idx[driver(p, b, self.idx)]])
                    for b in p.bones]
            self.parts.append((np.stack(skin, 1), np.c_[p.verts, np.ones(len(p.verts))], p.weights))

    def pose(self, f):
        # blend the matrices with one matmul first: the three-way einsum loops vertex x bone x entry in C
        return np.vstack([np.einsum("vij,vj->vi", (w @ s[f].reshape(len(s[f]), 16)).reshape(-1, 4, 4)[:, :3], vh)
                          for s, vh, w in self.parts])


def her_parts():
    """our woman: body areas from the map, head areas from the lips-makeup mesh, moved onto her head's Head bone"""
    rig, body, head_glb = WOMAN
    _, _, mapped, _, _ = bm.build(False, ["%s|%s|%s" % (body, rig, bm.BODY_TEX)], rig, bm.BODY_TEX)
    head = Part(head_glb, ride="Head")
    lips = bm.OurBody(LIPS)
    d, _ = cKDTree(lips.verts + bm.OurBody(head_glb).bind["Head"] - lips.bind["Head"]).query(head.verts)
    area = np.where(d < 0.003, "lips", np.where(head.verts[:, 2] < -0.02, "face", "head")).astype(object)
    print("her head %s: lips %d points" % (os.path.basename(head_glb), (area == "lips").sum()))
    return [(Part(body), mapped[0][3]), (head, area)]


def his_parts():
    """our man: body, the penis glb's own joints and binds moved onto this body's hips as the map does, head"""
    _, _, mapped, _, _ = bm.build(True, [bm.MAN_BODY], "man_base", bm.BODY_TEX)
    body = Part(bm.MAN_BODY)
    nb = len(body.verts)
    doc, buf = rg.read_glb(bm.PENIS)
    pn = Part(bm.PENIS, verts=np.zeros((0, 3)), weights=np.zeros((0, 0)), ride="Hips")
    move = bm.OurBody(bm.MAN_BODY).bind["Hips"] - np.linalg.inv(pn.ibm[pn.bones.index("Hips")])[:3, 3]
    at = next(x for x in doc["meshes"] if x["name"] == bm.PENIS_CHUNK)["primitives"][0]["attributes"]
    pv = rg.accessor(doc, buf, at["POSITION"]).astype(np.float64) + move
    pw = np.zeros((len(pv), len(pn.bones)))
    for k in (0, 1):
        if "JOINTS_%d" % k in at:
            jj = rg.accessor(doc, buf, at["JOINTS_%d" % k]).astype(np.int64)
            np.add.at(pw, (np.arange(len(pv))[:, None].repeat(4, 1), jj), rg.accessor(doc, buf, at["WEIGHTS_%d" % k]))
    T = np.eye(4)
    T[:3, 3] = move
    pn.ibm = pn.ibm @ np.linalg.inv(T)
    pn.verts, pn.weights = pv, pw
    head = Part(HEAD_M, ride="Head")
    h_area = np.where(head.verts[:, 2] < -0.02, "face", "head").astype(object)
    area = mapped[0][3]
    return [(body, area[:nb]), (pn, area[nb:]), (head, h_area)]


# loaded once per process: pair_batch.py runs many clips in one, and loading the bodies was a quarter of a clip
_PARTS, _MAIN = {}, {}


def parts(male):
    if male not in _PARTS:
        _PARTS[male] = his_parts() if male else her_parts()
    return _PARTS[male]


def patch(a, names):
    return np.where(np.isin(a.area, names))[0]


def mesh_points(acts):
    """bind positions of the points the interaction mesh needs beyond the joints: mouth, groin, palms, a man's penis"""
    virt = {}
    for act in acts:
        front, groin = (["face"], ["groin"]) if act.male else (["lips"], ["vulva"])
        out = {"front": act.verts[patch(act, front)].mean(0), "groin": act.verts[patch(act, groin)].mean(0)}
        for a in ("hand_l", "hand_r"):
            c = act.verts[patch(act, [a])].mean(0)
            s = min(("Left", "Right"), key=lambda s: np.linalg.norm(c - act.tg.w_t[act.idx[s + "Hand"]]))
            out["palm_" + s] = c
        if act.male:
            pts = act.verts[patch(act, ["penis", "glans"])]
            fz = pts[:, 2]           # straight at bind; its angle is the shaft mod's at runtime
            out["shaft"] = pts[fz > fz.max() - 0.02].mean(0)
            out["tip"] = pts[fz < fz.min() + 0.02].mean(0)
        virt[act] = out
    return virt


def nearest_cpu(acts, eff, f):
    """{effector: (distance, area)}: the nearest skin of any other actor to the effector's points in frame f"""
    posed = {a: a.pose(f) for a in acts}
    trees = {a: cKDTree(p) for a, p in posed.items()}
    out = {}
    for (a, k), idx in eff.items():
        near = []
        for other in acts:
            if other is not a:
                d, i = trees[other].query(posed[a][idx], workers=WORKERS)
                j = int(np.argmin(d))
                near.append((d[j], other.area[i[j]]))
        out[k] = min(near, key=lambda x: x[0])
    return out


class GpuSkin:
    """an actor's skin posed on the GPU: the weights there once, a frame's bone matrices up per pose"""

    def __init__(self, act):
        self.act = act
        self.parts = [(s, cp.asarray(w, cp.float32), cp.asarray(vh, cp.float32)) for s, vh, w in act.parts]

    def pose(self, f):
        return cp.concatenate([cp.einsum("vij,vj->vi", (w @ cp.asarray(s[f].reshape(len(s[f]), 16), cp.float32))
                                         .reshape(-1, 4, 4)[:, :3], vh) for s, w, vh in self.parts])


_NEAREST = r"""
extern "C" __global__ void nearest(const float* q, int n, const float* s, int m, float* best, int* at) {
    __shared__ float t[3 * 256];
    int i = blockIdx.x * blockDim.x + threadIdx.x;
    float x = 0, y = 0, z = 0, b = 3.4e38f;
    int k = -1;
    if (i < n) { x = q[3 * i]; y = q[3 * i + 1]; z = q[3 * i + 2]; }
    for (int o = 0; o < m; o += 256) {
        int j = o + threadIdx.x;
        if (j < m) { t[3 * threadIdx.x] = s[3 * j]; t[3 * threadIdx.x + 1] = s[3 * j + 1]; t[3 * threadIdx.x + 2] = s[3 * j + 2]; }
        __syncthreads();
        int e = min(256, m - o);
        for (int u = 0; u < e; u++) {
            float dx = t[3 * u] - x, dy = t[3 * u + 1] - y, dz = t[3 * u + 2] - z;
            float d = dx * dx + dy * dy + dz * dz;
            if (d < b) { b = d; k = o + u; }
        }
        __syncthreads();
    }
    if (i < n) { best[i] = b; at[i] = k; }
}"""
_kernel = None


def nearest_gpu(gpu, eff, f):
    """nearest_cpu by brute force on the GPU, each effector point's nearest skin point in one kernel (a tile of skin
    in shared memory, a running minimum per point), about the frame's centre"""
    global _kernel
    if _kernel is None:
        _kernel = cp.RawKernel(_NEAREST, "nearest")
    posed = {a: g.pose(f) for a, g in gpu.items()}
    mid = cp.concatenate(list(posed.values())).mean(0)
    posed = {a: p - mid for a, p in posed.items()}
    out = {}
    for a in posed:
        keys = [(k, idx) for (b, k), idx in eff.items() if b is a]
        others = [o for o in posed if o is not a]
        q = cp.ascontiguousarray(posed[a][cp.asarray(np.concatenate([idx for _, idx in keys]))])
        skin = cp.ascontiguousarray(cp.concatenate([posed[o] for o in others]))
        area = np.concatenate([o.area for o in others])
        d2, j = cp.empty(len(q), cp.float32), cp.empty(len(q), cp.int32)
        _kernel(((len(q) + 255) // 256,), (256,), (q, np.int32(len(q)), skin, np.int32(len(skin)), d2, j))
        d, j = d2.get().astype(np.float64) ** 0.5, j.get()
        if (j < 0).any():                       # a NaN point compares false against every skin point
            raise ValueError("frame %d: %d effector points with no nearest skin (NaN pose)" % (f, (j < 0).sum()))
        at = 0
        for k, idx in keys:
            i = at + int(d[at:at + len(idx)].argmin())
            out[k] = (float(d[i]), area[j[i]])
            at += len(idx)
    return out


def contacts(acts, F, step):
    eff = {}
    for act, who in zip(acts, im.labels([a.male for a in acts])):
        for k, area in [("L hand", "hand_l"), ("R hand", "hand_r")] + (
                [("glans", "glans"), ("penis", "penis")] if act.male else [("vulva", "vulva"), ("lips", "lips")]):
            eff[(act, "%s %s" % (who, k))] = patch(act, [area])
    for (_, k), idx in eff.items():
        if not len(idx):
            raise ValueError("%s: no points" % k)
    hits = {}
    gpu = {a: GpuSkin(a) for a in acts} if cp is not None else None
    for f in range(0, F, step):
        for k, near in (nearest_gpu(gpu, eff, f) if gpu else nearest_cpu(acts, eff, f)).items():
            hits.setdefault(k, []).append(near)
    print("\nnearest partner skin (frames every %d; contact = within %.0f cm)" % (step, NEAR * 100))
    for k, h in hits.items():
        d = np.array([x for x, _ in h])
        top = {}
        for x, a in h:
            if x < NEAR:
                top[a] = top.get(a, 0) + 1
        print("  %-12s in contact %3d%% of frames, distance min/median %4.1f / %4.1f cm, on %s" % (
            k, 100 * (d < NEAR).mean(), 100 * d.min(), 100 * np.median(d),
            ", ".join("%s %d%%" % (a, 100 * c / len(h)) for a, c in sorted(top.items(), key=lambda kv: -kv[1])[:3])
            or "-"))
    return eff


def head_distance(him, her, F, step, eff, sky):
    """his hands to her head skin, frame by frame, beside the area Skyrim's hand touches at that frame"""
    head_i = patch(her, ["head", "face", "lips"])
    rows = []
    for f in range(0, F, step):
        tree, mv = cKDTree(her.pose(f)[head_i]), him.pose(f)
        d = [100 * tree.query(mv[eff[(him, k)]], workers=WORKERS)[0].min() for k in ("his L hand", "his R hand")]
        sf = f // sky["step"]
        rows.append((f, d, [sky["eff"][k][sf] if sf < len(sky["eff"][k]) else (1.0, "-")
                            for k in ("his L hand", "his R hand")]))
    for s, nm in ((0, "L"), (1, "R")):
        ours = np.array([r[1][s] for r in rows])
        on = np.array([r[2][s][1] in ("head", "face", "lips") and r[2][s][0] < NEAR for r in rows])
        print("  his %s hand on her head: Skyrim %d%% of frames, ours %d%%; ours median %.1f cm, %.1f cm where Skyrim's "
              "touches" % (nm, 100 * on.mean(), 100 * (ours < NEAR * 100).mean(), np.median(ours),
                           np.median(ours[on]) if on.any() else float("nan")))
    for f, d, sk in rows[::10]:
        print("    frame %3d  L %5.1f cm (Skyrim: %s)  R %5.1f cm (Skyrim: %s)" % (f, d[0], sk[0][1], d[1], sk[1][1]))


def gif(base, him, her, before, after, title):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from PIL import Image
    key_hue = {"hand": (0.25, 0.25, 0.25, 1), "lips": (1, 0, 0, 1), "glans": (0, 0.2, 1, 1), "penis": (0.3, 0.5, 1, 1),
               "vulva": (1, 0, 0.8, 1), "butt": (1, 0.6, 0, 1), "butt_crack": (1, 0.6, 0, 1), "chest": (0, 0.7, 0.3, 1),
               "pecs": (0, 0.7, 0.3, 1), "belly": (0.6, 0.3, 0.9, 1), "head": (0.6, 0.6, 0.6, 1),
               "face": (0.75, 0.75, 0.75, 1)}
    male, female = (0.55, 0.75, 0.95, 0.35), (0.95, 0.7, 0.7, 0.35)
    hc = [key_hue.get(sb.base_area(a), male) for a in him.area[::SUB]]
    fc = [key_hue.get(sb.base_area(a), female) for a in her.area[::SUB]]
    allp = np.vstack([np.vstack(p) for p in before[:1] + after[:1]])
    lo, hi = allp.min(0) - 0.1, allp.max(0) + 0.1
    sg = np.load(os.path.join(OUT, "skygif_%s.npz" % base))     # skyrim_contact.py GIF=1: z up, metres
    shc = [key_hue.get(sb.base_area(a), male) for a in sg["him_area"]]
    sfc = [key_hue.get(sb.base_area(a), female) for a in sg["her_area"]]
    sp0 = np.vstack([sg["him"][0], sg["her"][0]])
    slo, shi = sp0.min(0) - 0.1, sp0.max(0) + 0.1
    frames = []
    for n, ((mb_, fb_), (ma_, fa_)) in enumerate(zip(before, after)):
        if n >= len(sg["him"]):
            break
        fig, axes = plt.subplots(1, 3, figsize=(15, 5.5))
        for pts, c in ((sg["him"][n], shc), (sg["her"][n], sfc)):
            axes[0].scatter(SKY_FLIP * pts[:, 1], pts[:, 2], s=1.2, c=c, linewidths=0)
        axes[0].set_xlim(*sorted(SKY_FLIP * np.array([slo[1], shi[1]])))
        axes[0].set_ylim(slo[2], shi[2])
        axes[0].set_title("Skyrim (CBBE + HIMBO)", fontsize=10)
        for ax, (m_, w_), t in ((axes[1], (mb_, fb_), "our retarget"), (axes[2], (ma_, fa_), title)):
            for pts, c in ((m_, hc), (w_, fc)):
                ax.scatter(pts[:, 2], pts[:, 1], s=1.2, c=c, linewidths=0)
            ax.set_xlim(lo[2], hi[2]); ax.set_ylim(lo[1], hi[1]); ax.set_title(t, fontsize=10)
        for ax in axes:
            ax.set_aspect("equal"); ax.set_xticks([]); ax.set_yticks([])
        fig.suptitle("%s  frame %d   grey hands, red lips, blue penis" % (base, n * GIF_STEP), fontsize=9)
        fig.canvas.draw()
        frames.append(Image.fromarray(np.asarray(fig.canvas.buffer_rgba())).convert("P", palette=Image.ADAPTIVE))
        plt.close(fig)
    g = os.path.join(OUT, "contact_%s.gif" % base)
    frames[0].save(g, save_all=True, append_images=frames[1:], duration=100, loop=0)
    print("wrote", g)


def main():
    run(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "ostimng")


def run(base, pack):
    port, src = pair_reach.PORTS[pack]
    step = int(os.environ.get("STEP", 3))
    save = os.environ.get("SAVE") == "1"
    if save and (os.environ.get("MESH") != "1" or "FRAMES" in os.environ or BIG_F):
        raise ValueError("SAVE=1 saves the whole clip's interaction mesh: MESH=1, no FRAMES, no BODY_F")
    os.makedirs(OUT, exist_ok=True)
    every = {}
    for r in json.load(open(os.path.join(port, "manifest.json"))):
        every.setdefault(r["clip"], []).append(r)
    print(base)
    cast = pair_batch.cast_rows(every, base, pack)
    if len(cast) < 2:
        raise ValueError("%s: %d actors, want two or more" % (base, len(cast)))
    acts = [Actor(r, parts(r["sex"] == "m"), port, src) for r in cast]
    F = min([a.frames for a in acts] + [int(os.environ.get("FRAMES", 100000))])
    want_gif, head = os.environ.get("GIF") == "1", os.environ.get("HEADDIST") == "1"
    if (want_gif or head) and [a.male for a in acts] != [True, False]:
        raise ValueError("GIF and HEADDIST draw a man (_0) and a woman (_1); %s has %s" % (
            base, "".join(r["sex"] for r in cast)))
    poses = lambda: [tuple(a.pose(f)[::SUB] for a in acts) for f in range(0, F, GIF_STEP)]
    before = poses() if want_gif else None
    mesh = os.environ.get("MESH") == "1"
    if mesh:
        print("interaction mesh over %d frames, %d actors" % (F, len(acts)))
        skin = mesh_skin.points(acts, base, pack, F) if os.environ.get("MESH_SKIN") == "1" else None
        touch = ()
        if os.environ.get("TOUCH_TIES") == "1":     # every touch Skyrim's skin has, tied (opensex-port.md 9.8)
            import touch_ties
            more, touch = touch_ties.find(acts, base, pack, F)
            skin = skin or {}
            for a, pts in more.items():
                skin.setdefault(a, {}).update(pts)
        if os.environ.get("POSE") == "1":      # solved in our rig's own pose (pose_solve.py, opensex-port.md 9.9)
            import pose_solve
            pose_solve.solve(acts, F, mesh_points(acts), skin=skin, touch=touch)
            worst = (0.0, 0, "none: our rig's own lengths")
        else:
            solved, sides, worst = im.adapt(acts, F, mesh_points(acts), int(os.environ.get("STEPS", im.N_STEPS)),
                                            skin=skin, touch=touch)
            for side, P in zip(sides, solved):
                im.to_rotations(side, P)
        if os.environ.get("HANDFIT") == "1":    # his palm onto her skin where Skyrim's is, turned as Skyrim's
            import hand_fit                     # here: hand_fit imports this module
            hand_fit.fit(acts, base, pack, F)
    eff = contacts(acts, F, step)
    if os.environ.get("TOUCHES") == "1":       # Skyrim's touches, area to area, kept or lost on ours
        import touches
        touches.report(acts, base, pack, F, step, OUT)
    if head:
        head_distance(*acts, F, step, eff, json.load(open(os.path.join(OUT, "sky_%s.json" % base))))
    if want_gif:
        gif(base, *acts, before, poses(), "the interaction mesh" if mesh else "our retarget")
    if mesh:
        # after the report and the GIF, which are how a broken clip gets looked at; the batch counts it failed
        print("mesh: worst bone %.1f cm off its length, frame %d, %s" % (100 * worst[0], worst[1], worst[2]))
        if worst[0] > im.LENGTH_TOL:
            raise RuntimeError("BROKEN: %s %.1f cm off at frame %d, over %.0f cm" % (
                worst[2], 100 * worst[0], worst[1], 100 * im.LENGTH_TOL))
    if save:
        save_mesh(port, acts, every)


def save_mesh(port, acts, every):
    """the solved clips where skyrim_port.py's glbs stage takes them, for every set playing them on the same rig and
    body: each actor was solved on its own sex's body"""
    for act in acts:
        for r in every[act.row["clip"]]:
            if r["rig"] != act.row["rig"] or r["sex"] != act.row["sex"]:
                continue
            out = sp.mesh_path(r, port)
            os.makedirs(os.path.dirname(out), exist_ok=True)
            np.savez(out + ".tmp.npz", rot=act.rot.astype(np.float32), tra=act.tra.astype(np.float32))
            os.replace(out + ".tmp.npz", out)
            print("mesh: saved %s" % os.path.relpath(out, port))


if __name__ == "__main__":
    main()
