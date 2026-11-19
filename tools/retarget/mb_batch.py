"""Many generated transitions at once, both actors of a move together. mb_batch.ps1 is the way in.

  python mb_batch.py sets <moves.csv> <only file|->                    the source .anims those moves need
  python mb_batch.py generate <moves.csv> <only|-> <set glbs> <out> --tokens 14,16,10   (MotionBricks venv)
  python mb_batch.py results <out> <depot dir> <results.jsonl>         the rows pack_transitions.py reads
  python mb_batch.py player <player depot dir> <results.jsonl>         fills each side's player set (mb_player.ps1)
  python mb_batch.py hard <results.jsonl>                              moves whose hips rise most: mb_help.json's candidates

moves.csv has one row per actor: from, to, actor, sex, from_set, from_clip_s1, to_set, to_clip_first, rig. An only file
is one "from to" per line. Both actors of a move get one length, tried at each --tokens and kept at the widest gap.
Every clip gets mb_foot's feet. A move that fails with all four target poses is retried with fewer, one that overlaps
past MAX_PAST goes through a pushed-apart middle pose, a failed move whose hips stay put is a plain blend, and
mb_help.json can cut, blend or help a named move.
A rejected move is a row with a reason and no clip. docs/design/generated-motion.md §7.
"""
import argparse
import csv
import json
import os
import re
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mb_foot as mf  # noqa: E402
import mb_gap as mg  # noqa: E402
import mb_help as mh  # noqa: E402
import mb_soma as ms  # noqa: E402
import retarget_glb as rg  # noqa: E402
from pack_transitions import key  # noqa: E402

BAD_SPREAD = 0.05   # m between a scene's stage ends: one transition cannot leave all of them
TARGET_POSES = (4, 2, 1)   # a first pose alone is a stop, which rescues moves four poses reject
MAX_PAST = 0.20     # m of overlap past the closer authored pose before a middle pose is tried
MIDDLE_TOKENS = (8, 10)
HARD_RISE = 0.40    # m the hips climb between A and B


def stem(depot_rel):
    return os.path.splitext(os.path.basename(depot_rel.replace("\\", "/")))[0]


def rig_of(depot_rel):
    return "woman_base" if stem(depot_rel).endswith("_wa") else "man_base"


def load_moves(path, only=None):
    """[{from, to, pack, key, sides: [csv row, ...], skip: reason or None}], in file order."""
    with open(path, encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    moves = {}
    for r in rows:
        moves.setdefault((r["from"], r["to"]), []).append(r)
    out = []
    for (a, b), sides in moves.items():
        if only is not None and (a, b) not in only:
            continue
        skip = None
        if len(sides) != 2:
            skip = "%d actors, this tool joins pairs" % len(sides)
        for s in sides:
            if rig_of(s["from_set"]) != rig_of(s["to_set"]):
                skip = "actor %s changes rig, %s to %s" % (s["actor"], stem(s["from_set"]), stem(s["to_set"]))
            elif float(s["stage_end_spread_m"]) > BAD_SPREAD:
                skip = "actor %s's stages end %s m apart" % (s["actor"], s["stage_end_spread_m"])
        out.append({"from": a, "to": b, "pack": a.split(".")[0], "key": key(a, b),
                    "sides": sorted(sides, key=lambda s: s["actor"]), "skip": skip})
    names = [m["key"] for m in out]
    for m in out:
        if names.count(m["key"]) > 1:
            m["skip"] = "key %s is not unique" % m["key"]
    return out


def read_only(path):
    if path == "-":
        return None
    with open(path, encoding="utf-8") as f:
        return {tuple(line.split()) for line in f if line.strip()}


class Sets:
    """Exported set glbs, each read once."""

    def __init__(self, folder):
        self.folder, self.open = folder, {}

    def get(self, depot_rel):
        name = stem(depot_rel)
        if name not in self.open:
            doc, buf = rg.read_glb(os.path.join(self.folder, name + ".anims.glb"))
            self.open[name] = doc, buf, rg.Skeleton(doc)
        return self.open[name]


def side_inputs(sets, s):
    doc, buf, cp = sets.get(s["from_set"])
    anim, a = ms.clip_in(doc, buf, cp, s["from_clip_s1"], ms.tail_times)
    b_doc, b_buf, b_cp = sets.get(s["to_set"])
    if b_cp.names != cp.names:
        raise ValueError("%s and %s are not one skeleton" % (stem(s["from_set"]), stem(s["to_set"])))
    return {"doc": doc, "buf": buf, "cp": cp, "anim": anim, "a": a,
            "b": ms.clip_in(b_doc, b_buf, b_cp, s["to_clip_first"], ms.head_times)[1]}


def judge(sides, made):
    """[(SOMA poses, contacts)] per side -> {clips: [(rot, tra)], soma, metrics, gap...}, or {reason}."""
    clips, metrics = [], []
    for x, (poses, contacts) in zip(sides, made):
        (a_r, a_t), (b_r, b_t) = x["a"], x["b"]
        rot, tra = x["rig"].from_soma(poses, a_r, a_t, b_r, b_t)
        rot = mf.planted(x["cp"], rot, tra, contacts, x["a"], x["b"])
        m = ms.measure(x["cp"], rot, tra, x["a"], x["b"])
        bad = ms.failures(m)
        if bad:
            return {"reason": "actor %s: %s" % (x["row"]["actor"], "; ".join(bad))}
        clips.append((rot, tra))
        metrics.append(m)
    if clips[0][0].shape[1] != clips[1][0].shape[1]:
        return {"reason": "the actors came out %d and %d frames" % (clips[0][0].shape[1], clips[1][0].shape[1])}
    return dict(scored(sides, clips, metrics), soma=[p for p, _ in made])


def blended(sides, frames=mh.BLEND_FRAMES):
    """No model: every bone eases from A's last pose to B's first. Same shape as judge()."""
    clips, metrics = [], []
    for x in sides:
        rot, tra = mh.blend(x, frames)
        rot = mf.planted(x["cp"], rot, tra, np.zeros((frames, 4)), x["a"], x["b"])   # no contacts: only the floor lift
        m = ms.measure(x["cp"], rot, tra, x["a"], x["b"])
        bad = ms.failures(m)
        if bad:
            return {"reason": "actor %s: %s" % (x["row"]["actor"], "; ".join(bad))}
        clips.append((rot, tra))
        metrics.append(m)
    return dict(scored(sides, clips, metrics), tokens=0, via="blend")


def scored(sides, clips, metrics):
    x, y = sides
    gen = mg.gap(*[mg.capsules(s["cp"], *c) for s, c in zip(sides, clips)])
    ends = mg.gap(mg.capsules(x["cp"], x["a"][0][:, -1:], x["a"][1][:, -1:]),
                  mg.capsules(y["cp"], y["a"][0][:, -1:], y["a"][1][:, -1:]))
    starts = mg.gap(mg.capsules(x["cp"], x["b"][0][:, :1], x["b"][1][:, :1]),
                    mg.capsules(y["cp"], y["b"][0][:, :1], y["b"][1][:, :1]))
    return {"clips": clips, "metrics": metrics, "frames": clips[0][0].shape[1],
            "gap": gen[0], "gap_frame": gen[1], "gap_bones": gen[2:], "gap_a": ends[0], "gap_b": starts[0]}


def attempt(generate, sides, tokens, target_poses=4):
    made = []
    for x in sides:
        ctx, tgt = mh.ends(x)
        made.append(generate(ctx, tgt[:target_poses], (tokens,)))
    return dict(judge(sides, made), tokens=tokens, target_poses=target_poses)


def past(t):
    """m of overlap past the closer authored pose."""
    return min(t["gap_a"], t["gap_b"]) - t["gap"]


def wants_middle(best, rule):
    """A blend has no model poses to push apart, and a rule says how its move goes."""
    return not rule and "soma" in best and past(best) > MAX_PAST


def middle(generate, sides, base):
    """A -> middle -> B: the base clip's worst frame, each body pushed off the other, as a pose to pass through."""
    n = base["frames"]
    f = int(np.clip(base["gap_frame"], n // 3, 2 * n // 3))
    hips = [mg.capsules(s["cp"], *c)[0][0, f] for s, c in zip(sides, base["clips"])]
    d = (hips[0] - hips[1])[[0, 2]]
    d = d / max(np.linalg.norm(d), 1e-6)
    out = []
    for push in (past(base), past(base) * 1.5):
        for tokens in MIDDLE_TOKENS:
            made = []
            for x, soma, sign in zip(sides, base["soma"], (1.0, -1.0)):
                ctx, tgt = mh.ends(x)
                mid = soma[f:f + ms.CONTEXT].copy()
                mid[:, 0, [0, 2]] -= sign * d * push / 2 * x["rig"].scale   # SOMA faces the other way: ms.YAW180
                made.append(mh.chain(generate, ctx, mid, tgt[:base["target_poses"]], tokens, tokens))
            out.append(dict(judge(sides, made), tokens=tokens * 2, target_poses=base["target_poses"], via="middle"))
    return out


def hip_rise(sides):
    """m the higher-climbing actor's hips gain between A's end and B's start."""
    rises = []
    for x in sides:
        hips = x["cp"].index["Hips"]
        a_r, a_t = x["a"][0][:, -1:], x["a"][1][:, -1:]
        b_r, b_t = x["b"][0][:, :1], x["b"][1][:, :1]
        rises.append(x["cp"].world_pose(b_r, b_t)[1][hips, 0, 1] - x["cp"].world_pose(a_r, a_t)[1][hips, 0, 1])
    return float(max(rises))


def generate_all(args):
    import mb_transition as mt
    os.makedirs(args.out, exist_ok=True)
    moves = load_moves(args.moves, read_only(args.only))
    tokens = [int(t) for t in args.tokens.split(",")]
    sets = Sets(args.sets)
    help_rules = mh.load()
    skeleton, soma = mt.load_soma()
    rigs, groups, rows = {}, {}, []
    with mt.Generator(skeleton, args.device) as generate:
        for i, m in enumerate(moves):
            row = {"from": m["from"], "to": m["to"], "pack": m["pack"]}
            rows.append(row)
            rule = mh.rule_for(help_rules, m["from"], m["to"])
            if m["skip"]:
                row.update(rejected=True, reason=m["skip"])
                continue
            if rule and "cut" in rule:
                row.update(rejected=True, reason="help table: " + rule["why"])
                continue
            try:
                sides = [dict(side_inputs(sets, s), row=s) for s in m["sides"]]
            except ValueError as e:
                row.update(rejected=True, reason=str(e))
                continue
            for x in sides:
                x["rig"] = rigs.setdefault(rig_of(x["row"]["from_set"]), ms.Rig(soma, x["cp"]))
            row["rise"] = hip_rise(sides)
            if rule and "blend" in rule:
                tries = [blended(sides)]
                good = [t for t in tries if "clips" in t]
            elif rule:
                try:
                    tries = mh.helped(generate, soma, sides, rule, sets, judge)
                except ValueError as e:   # the rule names a clip or skeleton its set does not have
                    row.update(rejected=True, reason="help table: %s" % e)
                    continue
                good = [t for t in tries if "clips" in t]
            else:
                for target_poses in TARGET_POSES:
                    tries = [attempt(generate, sides, t, target_poses) for t in tokens]
                    good = [t for t in tries if "clips" in t]
                    if good:
                        break
                if not good and mh.limbs_only(sides):
                    flat = blended(sides)
                    if "clips" in flat:
                        good = [flat]
                    else:
                        tries[0]["reason"] += "; blend: " + flat["reason"]
            if not good:
                row.update(rejected=True, reason=tries[0]["reason"])
                continue
            best = max(good, key=lambda t: t["gap"])
            if wants_middle(best, rule):
                good += [t for t in middle(generate, sides, best) if "clips" in t]
                best = max(good, key=lambda t: t["gap"])
            row.update(length=best["frames"] / ms.FPS, tokens=best["tokens"], gap=best["gap"], gap_a=best["gap_a"],
                       gap_b=best["gap_b"], gap_frame=best["gap_frame"], gap_bones=best["gap_bones"],
                       target_poses=best.get("target_poses"), via=best.get("via"),
                       tried=[[t["tokens"], round(t["gap"], 3)] for t in good], sides=[])
            for x, clip, metric in zip(sides, best["clips"], best["metrics"]):
                s = x["row"]
                name = "gen-%s_%d" % (m["key"], "ab".index(s["actor"]))
                group = "gen_" + stem(s["from_set"])
                groups.setdefault(group, {"from_set": s["from_set"], "rig": s["rig"], "x": x, "clips": []})
                times = np.arange(best["frames"], dtype=np.float64) / ms.FPS
                groups[group]["clips"].append((name, x["anim"].get("extras", {}), times, *clip))
                row["sides"].append({"actor": s["actor"], "sex": s["sex"], "rig": rig_of(s["from_set"]), "clip": name,
                                     "group": group, "metrics": metric})
            print("%d/%d %s tokens %d gap %.3f (A %.3f, B %.3f)" % (i + 1, len(moves), m["key"], best["tokens"],
                                                                     best["gap"], best["gap_a"], best["gap_b"]), flush=True)
    for group, g in groups.items():
        x = g["x"]
        rig_json = args.rig_json % {"rig": rig_of(g["from_set"])}
        with open(rig_json, encoding="utf-8") as f:
            ref = json.load(f)["Data"]["RootChunk"].get("referenceTracks", [])
        clips = [(n, rg.player_extras(e, ref), t, r, a) for n, e, t, r, a in g["clips"]]
        gd, gb = rg.build(x["doc"], x["buf"], x["cp"], clips)
        rg.write_glb(os.path.join(args.out, group + ".glb"), gd, gb)
    with open(os.path.join(args.out, "groups.tsv"), "w", encoding="utf-8") as f:
        for group, g in groups.items():
            f.write("%s\t%s\t%s\n" % (group, stem(g["from_set"]), rig_of(g["from_set"])))
    with open(os.path.join(args.out, "moves.json"), "w", encoding="utf-8") as f:
        json.dump(rows, f, indent=1)


def results(args):
    with open(os.path.join(args.out, "moves.json"), encoding="utf-8") as f:
        rows = json.load(f)
    with open(args.path, "w", encoding="utf-8") as f:
        for r in rows:
            for s in r.get("sides", []):
                s["npc"] = os.path.join(args.depot, s.pop("group") + ".anims")
                s["player"] = None
            f.write(json.dumps(r) + "\n")
    print("%d moves, %d rejected -> %s" % (len(rows), sum(1 for r in rows if r.get("rejected")), args.path))


def player_name(npc_path):
    """gen_kneafo_ma.anims -> gen_kneafo_pma.anims."""
    return re.sub(r"_([mw])a\.anims$", r"_p\1a.anims", os.path.basename(npc_path))


def fill_player(args):
    """Each side's player set, where one was baked; a side without one stays null."""
    with open(args.path, encoding="utf-8") as f:
        rows = [json.loads(line) for line in f]
    filled = missing = 0
    for r in rows:
        for s in r.get("sides", []):
            path = os.path.join(args.depot, player_name(s["npc"]))
            s["player"] = path if os.path.isfile(path) else None
            filled, missing = (filled + 1, missing) if s["player"] else (filled, missing + 1)
    with open(args.path, "w", encoding="utf-8") as f:
        f.writelines(json.dumps(r) + "\n" for r in rows)
    print("%d sides have a player set, %d do not" % (filled, missing))


def hard(args):
    with open(args.path, encoding="utf-8") as f:
        rows = [json.loads(line) for line in f]
    high = sorted((r for r in rows if r.get("rise", 0) > HARD_RISE), key=lambda r: -r["rise"])
    for r in high:
        print("%.2f %s %s %s" % (r["rise"], r.get("reason", "ok"), r["from"], r["to"]))
    print("%d moves rise over %.2f m" % (len(high), HARD_RISE))


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("sets")
    p.add_argument("moves")
    p.add_argument("only")
    p = sub.add_parser("generate")
    for name in ("moves", "only", "sets", "out"):
        p.add_argument(name)
    p.add_argument("--tokens", default="14,16,10")
    p.add_argument("--device", default="cuda:0")
    p.add_argument("--rig-json", required=True, help="path with %%(rig)s")
    p = sub.add_parser("results")
    for name in ("out", "depot", "path"):
        p.add_argument(name)
    p = sub.add_parser("player")
    for name in ("depot", "path"):
        p.add_argument(name)
    p = sub.add_parser("hard")
    p.add_argument("path")
    args = ap.parse_args()
    if args.cmd == "sets":
        need = set()
        help_rules = mh.load()
        for m in load_moves(args.moves, read_only(args.only)):
            if not m["skip"]:
                need |= {s["from_set"] for s in m["sides"]} | {s["to_set"] for s in m["sides"]}
                need.add(mh.needs_set(mh.rule_for(help_rules, m["from"], m["to"]) or {}))
        print("\n".join(sorted(need - {None})))
    elif args.cmd == "generate":
        generate_all(args)
    elif args.cmd == "player":
        fill_player(args)
    elif args.cmd == "hard":
        hard(args)
    else:
        results(args)


if __name__ == "__main__":
    main()
