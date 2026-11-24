"""Which body areas touch in Skyrim's clip, and whether ours still do in those frames: "touches kept", and the touches
ours has that Skyrim's has not, "invented". Skin to skin, both sides: Skyrim's bodies (HIMBO, CBBE) posed on the clip,
ours as pair_contact.py poses them.
  pair_contact.py with TOUCHES=1 (after MESH=1 and HANDFIT=1 when they are on)
Writes work/contact/touches_<clip>.json. Design: docs/design/opensex-port.md section 9.8 (nightcitynet)."""
import json, os
import numpy as np
from scipy.spatial import cKDTree
import skyrim_body as sb
import skyrim_contact as sc
import pair_reach
import mesh_skin

ON, OFF = 0.01, 0.02     # m: Skyrim's skin within ON starts a touch, past OFF ends it (one line flickers)
KEPT = 0.02              # m: ours within this in a touch's frames keeps it
INVENT = (0.01, 0.04)    # m: ours within the first where Skyrim's is past the second is a touch Skyrim has not
MIN_SHARE = 0.10         # a touch in fewer of the sampled frames is noise, not the scene's
REACH = 0.06            # m: past this, a gap is only "far"
HAND_R = 0.012          # m: CBBE has no hands; hers are points along the hand bone, this far inside the skin
SKIP = {"penis", "glans", "other"}   # the shaft's angle is the shaft mod's at runtime (opensex-port.md 9.7)
WORKERS = int(os.environ.get("WORKERS", 4))


def norm(area, male):
    """one area name both sides share: HIMBO's head is one area, ours a face and a head"""
    a = area.astype(object).copy()
    if male:
        a[np.isin(a, ["face", "lips"])] = "head"
    return a


class SkySide:
    """one Skyrim actor posed in metres, with her hands as points along the hand bones"""

    def __init__(self, act, src):
        (mb, ma), (fb, fa) = mesh_skin.sky_bodies()
        if act.male:
            parts = [(mb, ma)]
        else:
            hb = sb.Body(sb.FEMALE_HEAD)
            parts = [(fb, fa), (hb, sb.head_areas(hb.verts))]
        self.male, self.a = act.male, sc.Actor(act.row, parts, src)
        self.frames = self.a.frames
        extra = [] if act.male else ["hand_l"] * 6 + ["hand_r"] * 6
        self.area = norm(np.concatenate([self.a.area, np.array(extra, dtype=object)]), act.male)
        self.stand_in = np.r_[np.zeros(len(self.a.area), bool), np.ones(len(extra), bool)]

    def pose(self, f):
        p = self.a.pose(f)
        if not self.male:
            h = sc.her_hands(self.a, f)
            p = np.vstack([p, h["her L hand"], h["her R hand"]])
        return mesh_skin.to_ours(p)


class OurSide:
    def __init__(self, act):
        self.act, self.male = act, act.male
        self.area = norm(act.area, act.male)
        self.stand_in = np.zeros(len(self.area), bool)

    def pose(self, f):
        return self.act.pose(f)


def pair_gaps(sides, frames):
    """{(i, area, j, area): (len(frames),) the nearest skin between the two areas, nan past REACH}, each area pair once
    per actor pair, smaller actor index first. Area to area, not by each point's nearest area: our areas' borders are
    not Skyrim's, and by the nearest alone a thigh on her inner thigh read as lost from her thigh"""
    out = {}
    for k, f in enumerate(frames):
        posed = [s.pose(f) for s in sides]
        for i in range(len(sides)):
            for j in range(i + 1, len(sides)):
                d, _ = cKDTree(posed[j]).query(posed[i], workers=WORKERS, distance_upper_bound=REACH)
                cand = np.where(np.isfinite(d))[0]          # i's points within reach of j at all
                if not len(cand):
                    continue
                a = sides[i].area[cand]
                for B in np.unique(sides[j].area):
                    if B in SKIP:
                        continue
                    mb = sides[j].area == B
                    db, nb = cKDTree(posed[j][mb]).query(posed[i][cand], workers=WORKERS, distance_upper_bound=REACH)
                    ok = np.isfinite(db)
                    if not ok.any():
                        continue
                    db = db - HAND_R * (sides[i].stand_in[cand] | sides[j].stand_in[mb][np.minimum(nb, mb.sum() - 1)])
                    for A in np.unique(a[ok]):
                        if A in SKIP:
                            continue
                        g = out.setdefault((i, A, j, B), np.full(len(frames), np.nan))
                        g[k] = db[ok & (a == A)].min()
    return out


def touching(g):
    """Skyrim's frames in touch, ON to start and OFF to end"""
    on, now = np.zeros(len(g), bool), False
    for k, x in enumerate(g):
        now = (x <= ON) if not now else not (x > OFF)
        on[k] = now
    return on


def report(acts, base, pack, F, step, out_dir, log=print):
    """the kept and invented tables for a clip's actors, posed as they are now; returns the summary"""
    _, src = pair_reach.PORTS[pack]
    sky = [SkySide(a, src) for a in acts]
    n = min([F] + [s.frames for s in sky])
    frames = list(range(0, n, step))
    names = ["%s%d" % ("his" if a.male else "her", i) for i, a in enumerate(acts)]
    s_g, o_g = pair_gaps(sky, frames), pair_gaps([OurSide(a) for a in acts], frames)
    rows, invented = [], []
    for key in sorted(set(s_g) | set(o_g)):
        s = s_g.get(key, np.full(len(frames), np.nan))
        o = o_g.get(key, np.full(len(frames), np.nan))
        s_on = touching(np.nan_to_num(s, nan=1.0))
        label = "%s %s on %s %s" % (names[key[0]], key[1], names[key[2]], key[3])
        if s_on.mean() >= MIN_SHARE:
            near = np.nan_to_num(o[s_on], nan=REACH)     # past reach shows as the reach
            rows.append((label, s_on.mean(), (near <= KEPT).mean(), float(np.median(near))))
        new = (np.nan_to_num(o, nan=1.0) <= INVENT[0]) & (np.nan_to_num(s, nan=1.0) > INVENT[1])
        if new.mean() >= MIN_SHARE:
            invented.append((label, new.mean()))
    log("\ntouches (Skyrim's skin within %.0f cm in %d%%+ of %d frames; kept = ours within %.0f cm then)"
        % (100 * ON, 100 * MIN_SHARE, len(frames), 100 * KEPT))
    for label, share, kept, med in sorted(rows, key=lambda r: r[2]):
        log("  %-40s Skyrim %3d%%  kept %3d%%  ours median %5.1f cm" % (label, 100 * share, 100 * kept, 100 * med))
    for label, share in invented:
        log("  invented: %-30s %3d%% of frames" % (label, 100 * share))
    kept = sum(r[2] >= 0.5 for r in rows)
    summary = {"clip": base, "frames": len(frames), "touches": len(rows), "kept": kept, "invented": len(invented),
               "rows": [dict(zip(("touch", "skyrim", "kept", "median_m"), r)) for r in rows],
               "invented_rows": [dict(zip(("touch", "share"), r)) for r in invented]}
    log("touches: Skyrim %d, kept %d, lost %d, invented %d" % (len(rows), kept, len(rows) - kept, len(invented)))
    os.makedirs(out_dir, exist_ok=True)
    tag = os.environ.get("TOUCHES_TAG", "")
    with open(os.path.join(out_dir, "touches_%s%s.json" % (base, "_" + tag if tag else "")), "w") as fh:
        json.dump(summary, fh, indent=1, default=float)
    return summary
