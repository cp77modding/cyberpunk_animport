"""Who may play each side of a two-actor scene: a side needs a body only for the parts its acts use.

A kiss, a hug or a groped butt fits anyone on either side ("any"); a side that receives cunnilingus, fingering or a
breast act is a woman ("f"); a side with a penis in the act, giving sex or receiving oral or a handjob, is a man ("m").
A side whose acts need both, or a scene this cannot read, keeps the sex its pack gave it. Scenes of three or more,
and transitions, are left as they are. docs/design/scene-graph.md §2.1a.

  python tools/opensex/cast_roles.py plan               what would change, and the bakes it needs
  python tools/opensex/cast_roles.py write              the scene files' actor sex, and the new bakes into the ports'
                                                        manifest.json / source-map.json (then skyrim_port.py clips ...)
  python tools/opensex/cast_roles.py clips              after the port's pack stage: clips.json gains the new bodies
  python tools/opensex/cast_roles.py penis-plan|penis-write [--scene <id part>]
                                                        a woman with a penis plays the man's side: every "m" side's
                                                        clips baked on woman_base too (penis-side-cast.md §6)
"""
import argparse
import glob
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
import scene_files  # noqa: E402

ANIMS = scene_files.ANIMS
sys.path.insert(0, os.path.join(REPO, "tools", "retarget"))
import build_config  # noqa: E402
OSTIMNG = build_config.source("ostimng").get("input")

PORTS = {n: s["run"] for n, s in build_config.load()["sources"].items()}   # each source's run folder
PENIS, VAGINA, BREASTS = "penis", "vagina", "breasts"
# Our act types: (the giver needs, the receiver needs). A manual act is on a penis (HJ, BoJ, FJ) unless its target
# is a woman.
ACTS = {"penetrative": ({PENIS}, {VAGINA}), "oral_penis": (set(), {PENIS}), "oral_vagina": (set(), {VAGINA}),
        "manual": (set(), {PENIS})}
# OStimNG's action types, the same way; one not here needs nothing (holding, kissing, groping a butt, ...).
NG = {"vaginalsex": ({PENIS}, {VAGINA}), "analsex": ({PENIS}, set()), "blowjob": (set(), {PENIS}),
      "lickingpenis": (set(), {PENIS}), "handjob": (set(), {PENIS}), "footjob": (set(), {PENIS}),
      "buttjob": (set(), {PENIS}), "tailjob": (set(), {PENIS}), "boobjob": ({BREASTS}, {PENIS}),
      "malemasturbation": ({PENIS}, set()), "femalemasturbation": ({VAGINA}, set()), "facial": ({PENIS}, set()),
      "cumonchest": ({PENIS}, set()), "cumonbutt": ({PENIS}, set()), "cumonvulva": ({PENIS}, {VAGINA}),
      "cunnilingus": (set(), {VAGINA}), "lickingvagina": (set(), {VAGINA}), "vaginalfingering": (set(), {VAGINA}),
      "rubbingclitoris": (set(), {VAGINA}), "gropingbreast": (set(), {BREASTS})}
# A scene OpenSex gives no act, read by its name: what the woman's side needs, or None to keep both sides.
PENIS_WORDS = re.compile(r"penis|jerk|handjob|boobjob|blowjob|titfuck|climax|crotch|grind|masturbat|cum|tailjob|hj$|jo$")
BREAST_WORDS = re.compile(r"breast|nipple|boob")
VAGINA_WORDS = re.compile(r"fingering|cunnilingus|pussy")


def sex_of(needs, old):
    if PENIS in needs and needs & {VAGINA, BREASTS}:
        return old
    return "m" if PENIS in needs else "f" if needs else "any"


def needs_of(s, ng_root):
    """[set of parts] per actor, or None when the scene cannot be read."""
    n = [set(), set()]
    src = (s.get("sources") or [{}])[0]
    if src.get("pack") == "ostimng":
        path = os.path.join(ng_root, src["file"])
        if not os.path.isfile(path):
            return None
        for x in json.load(open(path, encoding="utf-8")).get("actions", []):
            give, take = NG.get(x.get("type"), (set(), set()))
            if x.get("actor") in (0, 1):
                n[x["actor"]] |= give
            if x.get("target") in (0, 1):
                n[x["target"]] |= take
    else:
        for act in s.get("acts") or []:
            give, take = ACTS[act["type"]]
            if act["type"] == "manual" and s["actors"]["ab".index(act["target"])]["sex"] == "f":
                take = {VAGINA}  # a hand on a woman: fingering, groped from behind
            if act["type"] == "penetrative" and act.get("into") == "anus":
                take = set()
            n["ab".index(act["actor"])] |= give
            n["ab".index(act["target"])] |= take
        if ".boj." in s["id"]:
            n["ab".index(s["acts"][0]["actor"])] |= {BREASTS}
        if not s.get("acts"):
            name = s["id"].split(".")[-1]
            sexes = [a["sex"] for a in s["actors"]]
            if sexes.count("f") != 1:
                return None
            woman = sexes.index("f")
            if BREAST_WORDS.search(name):
                n[woman] |= {BREASTS}
            if VAGINA_WORDS.search(name):
                n[woman] |= {VAGINA}
    if not any(PENIS in x for x in n) and PENIS_WORDS.search(s["id"].split(".")[-1]):
        return None
    return n


def scene_files_of(pack):
    for f in sorted(glob.glob(os.path.join(ANIMS, pack, scene_files.SCENES_REL, "**", "*.json"), recursive=True)):
        if os.path.basename(f) != "clips.json":
            yield f, json.load(open(f, encoding="utf-8"))


def plan(ng_root):
    """[(file, scene, new sexes)] for every two-actor scene whose sexes change."""
    out = []
    for pack in ("opensex", "ostimng"):
        for f, s in scene_files_of(pack):
            if s.get("transition") or len(s["actors"]) != 2:
                continue
            n = needs_of(s, ng_root)
            if n is None:
                continue
            new = [sex_of(x, a["sex"]) for x, a in zip(n, s["actors"])]
            if new != [a["sex"] for a in s["actors"]]:
                out.append((f, s, new))
    return out


def bakes(changes, clips):
    """{clip ref: {sex}}: the bodies each changed side's clips must now have, less those clips.json already has."""
    want = {}
    for _, s, new in changes:
        for i, sex in enumerate(new):
            for sp in s["speeds"]:
                c = sp["clips"][i]
                for b in ({"m", "f"} if sex == "any" else {sex}):
                    if b not in clips.get(c, {}):
                        want.setdefault(c, set()).add(b)
    return want


def penis_wants(scenes, clips, scene=""):
    """{clip ref: {"f"}} for every scene's "m" side, 2-5 actors, whose clip has no woman's bake; [scene ids]."""
    want, ids = {}, []
    for s in scenes:
        if s.get("transition") or len(s["actors"]) < 2 or scene not in s["id"]:
            continue
        got = False
        for i, a in enumerate(s["actors"]):
            if a["sex"] != "m":
                continue
            for sp in s["speeds"]:
                c = sp["clips"][i]
                if "f" not in clips.get(c, {}):
                    want.setdefault(c, set()).add("f")
                    got = True
        if got:
            ids.append(s["id"])
    return want, ids


def penis_bakes(clips, scene):
    return penis_wants((s for pack in ("opensex", "ostimng") for _, s in scene_files_of(pack)), clips, scene)


def read_clips_json():
    out = {}
    for pack in ("opensex", "ostimng"):
        out.update(json.load(open(os.path.join(ANIMS, pack, scene_files.SCENES_REL, pack, "clips.json"),
                                  encoding="utf-8")))
    return out


def body_set(path, sex):
    """A set path for the other body: <group>_ma.anims <-> <group>_wa.anims, _pma <-> _pwa."""
    return re.sub(r"_(p?)[mw]a\.anims$", lambda m: "_%s%sa.anims" % (m.group(1), "w" if sex == "f" else "m"), path)


def add_rows(manifest, source, ref, sex):
    """The bake of ref's clip on sex's body, copied from its row for the other body. False when it has none."""
    pack, rest = ref.split("/", 1)
    clip, _, group = rest.partition("#")
    rows = [r for r in manifest if r["clip"] == clip and (not group or ("\\%s_" % group) in r["npcSet"])]
    if not rows:
        return False
    if any(r["sex"] == sex for r in rows):
        return True
    r = dict(rows[0])
    r.update({"sex": sex, "rig": "man_base" if sex == "m" else "woman_base",
              "playerRig": "player_man" if sex == "m" else "player_woman",
              "npcSet": body_set(r["npcSet"], sex), "playerSet": body_set(r["playerSet"], sex)})
    if r.get("skeleton"):  # OStimNG: vanilla skeletons differ by body, the 242 one is shared
        d, f = os.path.split(r["skeleton"])
        r["skeleton"] = os.path.join(d, {"skeleton.hkx": "femskeleton.hkx", "femskeleton.hkx": "skeleton.hkx"}.get(f, f))
    manifest.append(r)
    for row in source:
        if row["clip"] == clip and any(x == rows[0]["npcSet"] for x in row["sets"]):
            row["sets"] += [r["npcSet"], r["playerSet"]]
            row["sex"] = sorted(set(row.get("sex") or []) | {sex})
    return True


def write_json(path, obj, indent=1):
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(obj, fh, indent=indent, ensure_ascii=False)
        fh.write("\n")


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("step", choices=("plan", "write", "clips", "penis-plan", "penis-write"))
    ap.add_argument("--ostimng", default=OSTIMNG)
    ap.add_argument("--scene", default="", help="penis-*: only scenes whose id contains this")
    a = ap.parse_args()
    if a.step.startswith("penis-"):
        want, ids = penis_bakes(read_clips_json(), a.scene)
        print("%d scenes, %d clips need a woman's bake for the man's side" % (len(ids), len(want)))
        if a.step == "penis-plan":
            for i in ids:
                print("  " + i)
            return
        ports = {p: (json.load(open(os.path.join(d, "manifest.json"), encoding="utf-8")),
                     json.load(open(os.path.join(d, "source-map.json"), encoding="utf-8"))) for p, d in PORTS.items()}
        missing = [ref for ref in sorted(want) if not add_rows(*ports[ref.split("/")[0]], ref, "f")]
        if missing:
            sys.exit("no port row for %d clips, nothing written: %s" % (len(missing), missing[:5]))
        for p, (m, src) in ports.items():
            write_json(os.path.join(PORTS[p], "manifest.json"), m)
            write_json(os.path.join(PORTS[p], "source-map.json"), src)
        print("written: %d bakes added to the ports' manifests" % len(want))
        return
    if a.step == "clips":
        full, _ = scene_files.read_clips(ANIMS)
        for pack in ("opensex", "ostimng"):
            # a clip the source map does not name at all (a hand-fixed "-fix" clip) is read off its port's manifest
            # rows; only after the port stages, which bake every row write added
            known = set(full)
            for r in json.load(open(os.path.join(PORTS[pack], "manifest.json"), encoding="utf-8")):
                ref = "%s/%s" % (pack, r["clip"])
                if ref not in known:
                    full.setdefault(ref, {}).setdefault(r["sex"], {"npc": r["npcSet"], "player": r["playerSet"]})
        for pack in ("opensex", "ostimng"):
            path = os.path.join(ANIMS, pack, scene_files.SCENES_REL, pack, "clips.json")
            cur = json.load(open(path, encoding="utf-8"))
            added = 0
            for ref, bodies in cur.items():
                for sex, row in full.get(ref, {}).items():
                    if sex not in bodies:
                        bodies[sex] = row
                        added += 1
            write_json(path, cur)
            print("%s: %d bodies added to clips.json" % (pack, added))
        return
    changes = plan(a.ostimng)
    want = bakes(changes, read_clips_json())
    kinds = {}
    for _, s, new in changes:
        k = "%s -> %s" % ("".join(x["sex"][0] for x in s["actors"]), "/".join(new))
        kinds[k] = kinds.get(k, 0) + 1
    print("%d scenes change: %s" % (len(changes), ", ".join("%s %d" % kv for kv in sorted(kinds.items()))))
    print("%d clips need a new body (%d bakes)" % (len(want), sum(len(v) for v in want.values())))
    if a.step == "plan":
        for f, s, new in changes:
            print("  %-70s %s -> %s" % (s["id"], [x["sex"] for x in s["actors"]], new))
        return
    ports = {p: (json.load(open(os.path.join(d, "manifest.json"), encoding="utf-8")),
                 json.load(open(os.path.join(d, "source-map.json"), encoding="utf-8"))) for p, d in PORTS.items()}
    missing = [ref for ref, sexes in sorted(want.items()) for sex in sorted(sexes)
               if not add_rows(*ports[ref.split("/")[0]], ref, sex)]
    if missing:
        sys.exit("no port row for %d clips, nothing written: %s" % (len(missing), missing[:5]))
    for p, (m, src) in ports.items():
        write_json(os.path.join(PORTS[p], "manifest.json"), m)
        write_json(os.path.join(PORTS[p], "source-map.json"), src)
    for f, s, new in changes:
        for x, sex in zip(s["actors"], new):
            x["sex"] = sex
        write_json(f, s)
    print("written: %d scene files, %d bakes added to the ports' manifests" % (len(changes),
                                                                               sum(len(v) for v in want.values())))


if __name__ == "__main__":
    main()
