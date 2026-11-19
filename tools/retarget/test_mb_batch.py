"""mb_gap's capsules and mb_batch's move list, on synthetic input: no game data, no model.

Run: python tools/retarget/test_mb_batch.py (also from tools/py_test.ps1).
"""
import csv
import json
import os
import shutil
import sys
import tempfile

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mb_batch as mb  # noqa: E402
import mb_gap as mg  # noqa: E402

fails = []


def dist(p1, q1, p2, q2):
    return float(mg.seg_dist(*[np.array(v, np.float64) for v in (p1, q1, p2, q2)]))


def near(got, want, what):
    if abs(got - want) > 1e-6:
        fails.append("%s: got %.6f, want %.6f" % (what, got, want))


near(dist([0, 0, 0], [1, 0, 0], [0, 1, 0], [1, 1, 0]), 1.0, "parallel segments")
near(dist([0, 0, 0], [1, 0, 0], [0.5, -1, 0.3], [0.5, 1, 0.3]), 0.3, "crossing segments")
near(dist([0, 0, 0], [1, 0, 0], [2, 0, 0], [3, 0, 0]), 1.0, "end to end")
near(dist([0, 0, 0], [0, 0, 0], [0, 2, 0], [0, 2, 0]), 2.0, "two points")
near(dist([0, 0, 0], [1, 0, 0], [0.5, 2, 0], [0.5, 2, 0]), 2.0, "a segment and a point")

# Two one-capsule bodies: surface distance, then overlap, and which frame.
p1 = np.array([[[0, 0, 0], [0, 0, 0]]], np.float64)
q1 = np.array([[[0, 1, 0], [0, 1, 0]]], np.float64)
p2 = np.array([[[1, 0, 0], [0.1, 0, 0]]], np.float64)
q2 = np.array([[[1, 1, 0], [0.1, 1, 0]]], np.float64)
mg.SEGS[:] = [("A", "A", 0.2)]
got = mg.gap((p1, q1, np.array([0.2])), (p2, q2, np.array([0.2])))
near(got[0], 0.1 - 0.4, "overlap is negative")
if got[1] != 1:
    fails.append("gap names frame %d, the overlap is frame 1" % got[1])

if mb.player_name("x\\gen_ma_ma.anims") != "gen_ma_pma.anims" or mb.player_name("gen_a_wa.anims") != "gen_a_pwa.anims":
    fails.append("player_name does not map _ma/_wa to _pma/_pwa")



class Leg:
    """One leg down -Y: hip, thigh, calf and foot, 0.4 m each."""
    names = ["Hips", "LeftUpLeg", "LeftLeg", "LeftFoot"]
    index = {n: i for i, n in enumerate(names)}
    parent = [-1, 0, 1, 2]
    order = [0, 1, 2, 3]
    world_pose = mb.rg.Skeleton.world_pose


leg = Leg()
leg_rot = np.tile([0.0, 0, 0, 1], (4, 3, 1))
leg_tra = np.tile(np.array([[0, 1.0, 0], [0, 0, 0], [0.05, -0.4, 0], [0.05, -0.4, 0]]), (3, 1, 1)).transpose(1, 0, 2)
bent = mb.mf.turn(np.array([1.0, 0, 0]), 0.5)
leg_rot[1] = bent
goal = leg.world_pose(leg_rot, leg_tra)[1][3] + np.array([0.05, 0.03, 0.02])
solved = mb.mf.solve(leg, leg_rot, leg_tra, "Left", goal, np.ones(3))
got_r, got_t = leg.world_pose(solved, leg_tra)
if np.abs(got_t[3] - goal).max() > 1e-4:
    fails.append("IK missed the ankle goal by %.5f" % np.abs(got_t[3] - goal).max())
if np.abs(np.abs(np.sum(got_r[3] * leg.world_pose(leg_rot, leg_tra)[0][3], axis=-1)) - 1).max() > 1e-6:
    fails.append("IK turned the foot")
if mb.mf.runs([False, True, True, False, True]) != [(1, 2), (4, 4)]:
    fails.append("runs did not find the stretches")

rules = [{"from": "*legsheld", "to": "*missionary", "why": "x", "cut": True}]
if mb.mh.rule_for(rules, "a.legsheld", "b.missionary") is not rules[0] or mb.mh.rule_for(rules, "a.b", "c.d"):
    fails.append("rule_for matched the wrong moves")
mb.mh.load()   # the shipped table: raises on a bad rule


def refused(rule, what):
    work = tempfile.mkdtemp()
    try:
        path = os.path.join(work, "help.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump([dict({"from": "a", "to": "b", "why": "x"}, **rule)], f)
        try:
            mb.mh.load(path)
            fails.append("load took " + what)
        except ValueError:
            pass
    finally:
        shutil.rmtree(work)


spec = {"actor": "a", "set": "p\\anims\\x_ma.anims", "clip": "c", "tokens": [[8, 8]]}
refused({}, "a rule of no kind")
refused({"cut": False}, "cut false")
refused({"via": dict(spec, actor="c")}, "an actor no side has")
refused({"insert": dict(spec, tokens=[])}, "no tokens")
refused({"via": dict(spec, set="x_ma")}, "a set that is not a depot path")
if mb.mh.needs_set({"via": spec}) != spec["set"] or mb.mh.needs_set({"cut": True}) is not None:
    fails.append("needs_set did not name a rule's set")

# Feet: a planted run holds its middle frame; a foot under the seams' floor is lifted.
walk = leg_tra.copy()
walk = np.repeat(walk[:, :1], 12, axis=1)
walk[0, :, 2] = np.linspace(0, 0.11, 12)
still = np.tile([0.0, 0, 0, 1], (4, 12, 1))
contact = np.zeros((12, 4))
contact[3:9, :2] = 1
ends = (still[:, :1], walk[:, :1])
foot = leg.world_pose(still, walk)[1][3]
tgt, wgt = mb.mf.targets(leg, "Left", still, walk, contact, ends, ends)
if np.abs(tgt[3:9] - foot[5]).max() > 1e-9 or wgt[0] != 0 or wgt[6] != 1 or not 0 < wgt[3] < 1:
    fails.append("a planted run was not held at its middle: %s" % wgt)
sunk = walk.copy()
sunk[0, 4:8, 1] -= 0.1
tgt, wgt = mb.mf.targets(leg, "Left", still, sunk, np.zeros((12, 4)), ends, ends)
near(float(tgt[6, 1]), float(foot[6, 1]), "a foot under the floor is lifted to it")
if wgt[0] != 0 or wgt[-1] != 0:
    fails.append("the lift moved a seam")

blend_row = {"gap": -0.9, "gap_a": 0.0, "gap_b": 0.0}
if mb.wants_middle(blend_row, None) or not mb.wants_middle(dict(blend_row, soma=[]), None) \
        or mb.wants_middle(dict(blend_row, soma=[]), {"via": spec}):
    fails.append("wants_middle: a blend or a ruled move took a middle pose")


class Scaled:
    scale = 1.0


seen = []


def fake_generate(ctx, tgt, tokens):
    seen.append(len(tgt))
    return np.zeros((10, 1, 7), np.float32), np.zeros((10, 4))


judge, capsules = mb.judge, mb.mg.capsules
mb.judge = lambda sides, made: {"reason": "x"}
mb.mg.capsules = lambda cp, rot, tra: (np.zeros((1, 10, 3)),)
pose = np.zeros((4, 1, 7), np.float32)
base = dict(blend_row, frames=10, gap_frame=5, target_poses=1, soma=[np.zeros((10, 1, 7), np.float32)] * 2,
            clips=[(0, 0), (0, 0)])
one = {"ends": (pose, pose), "rig": Scaled(), "cp": None}
mb.middle(fake_generate, [one, one], base)
mb.judge, mb.mg.capsules = judge, capsules
if set(seen[1::2]) != {1}:
    fails.append("a middle pose ended on %s target poses, its base passed on 1" % set(seen[1::2]))

a_rot, b_rot = leg_rot[:, :1], leg_rot[:, :1].copy()
b_rot[1] = mb.mf.turn(np.array([1.0, 0, 0]), 1.0)
b_tra = leg_tra[:, :1].copy()
b_tra[0, 0, 0] = 0.1
side = {"a": (a_rot, leg_tra[:, :1]), "b": (b_rot, b_tra), "cp": leg}
b_r, b_t = mb.mh.blend(side, 5)
if np.abs(b_r[:, 0] - a_rot[:, 0]).max() > 1e-9 or np.abs(b_r[:, -1] - b_rot[:, 0]).max() > 1e-9:
    fails.append("a blend does not join its ends")
near(float(b_t[0, 2, 0]), 0.05, "a blend's halfway frame")
if not mb.mh.limbs_only([side, side]):
    fails.append("10 cm of hips is not limbs only")
b_tra[0, 0, 0] = 0.5
if mb.mh.limbs_only([side, side]):
    fails.append("50 cm of hips is limbs only")
poses = np.zeros((3, 2, 7), np.float32)
poses[:, :, 6] = 1
poses[:, 0, :3] = [[1, 0.5, 0], [2, 0.5, 0], [3, 0.5, 0]]
turned = mb.mh.moved(poses, np.pi / 2, (5, 6), 2)
near(float(turned[2, 0, 0]), 5, "moved puts the frame on the ground x")
near(float(turned[2, 0, 2]), 6, "moved puts the frame on the ground z")
near(float(turned[2, 0, 1]), 0.5, "moved keeps the height")
longer, contact = mb.mh.stretch(poses, np.arange(12.0).reshape(3, 4), 5)
near(float(longer[2, 0, 0]), 2, "stretch's middle frame")
if longer.shape[0] != 5 or contact.shape != (5, 4):
    fails.append("stretch did not reach its length")

work = tempfile.mkdtemp()
try:
    path = os.path.join(work, "moves.csv")
    cols = ["from", "to", "actor", "sex", "from_set", "from_clip_s1", "to_set", "to_clip_first", "rig", "stages",
            "stage_end_spread_m", "to_actor"]
    base = {"from_clip_s1": "x", "to_clip_first": "y", "rig": "man_base", "stages": "1", "stage_end_spread_m": "0.0"}

    def rows(a, b, ma_from, wa_from, ma_to, wa_to, spread="0.0"):
        return [dict(base, **{"from": a, "to": b, "actor": "a", "sex": "m", "from_set": ma_from, "to_set": ma_to,
                              "to_actor": "a", "stage_end_spread_m": spread}),
                dict(base, **{"from": a, "to": b, "actor": "b", "sex": "f", "from_set": wa_from, "to_set": wa_to,
                              "to_actor": "b"})]

    N = "opensex\\anims\\npc\\"
    data = rows("opensex.a.Good", "opensex.b.Next", N + "a_ma.anims", N + "a_wa.anims", N + "b_ma.anims", N + "b_wa.anims") \
        + rows("opensex.a.Swap", "opensex.b.Next", N + "a_ma.anims", N + "a_wa.anims", N + "b_wa.anims", N + "b_wa.anims") \
        + rows("opensex.a.Stage", "opensex.b.Next", N + "a_ma.anims", N + "a_wa.anims", N + "b_ma.anims", N + "b_wa.anims", "0.3")
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, cols)
        w.writeheader()
        w.writerows(data)

    moves = mb.load_moves(path)
    by = {m["from"].split(".")[-1]: m for m in moves}
    if by["Good"]["skip"] or by["Good"]["key"] != "good--next" or by["Good"]["pack"] != "opensex":
        fails.append("a good move was not read: %s" % by["Good"])
    if "changes rig" not in (by["Swap"]["skip"] or ""):
        fails.append("a side changing rig was not skipped")
    if "stages" not in (by["Stage"]["skip"] or ""):
        fails.append("a scene whose stages end apart was not skipped")
    if [s["actor"] for s in by["Good"]["sides"]] != ["a", "b"]:
        fails.append("sides are not in actor order")
    if len(mb.load_moves(path, {("opensex.a.Good", "opensex.b.Next")})) != 1:
        fails.append("an only list did not limit the moves")
finally:
    shutil.rmtree(work)

for f in fails:
    print("FAIL", f)
print("test_mb_batch:", "FAILED" if fails else "ok")
sys.exit(1 if fails else 0)
