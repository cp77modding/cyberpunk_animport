"""Our scene files: one per scene, from OpenSex's and OStimNG's scene data (docs/design/scene-graph.md §2).

Written into each CyberpunkAnimations pack at <pack>/bin/.../mods/nightcitynet/data/scenes/<pack>/, so the pack's zip
installs them into our data folder. The first version is generated; from then on the files are ours, so this refuses
to overwrite them unless --force. A scene's id is its path under data/scenes/: opensex/<OpenSex's own id parts>/,
ostimng/<OStimNG's own folders>/. A clip is "<pack>/<clip>", resolved to its sets by that pack's clips.json.

An OStimNG scene made only of OpenSex clips, cast the same, is the OpenSex scene: it becomes an alias and its moves
join the OpenSex scene's, which is what links the two graphs. A scene with no playable speed (a redirect, a menu hub)
is an alias for its one way out, else dropped. Everything dropped is printed.

Run: python tools/opensex/scene_files.py [--anims DIR] [--ostimng DIR] [--list JSON] [--force]
     --acts: only mark each manual act's body part (`with`) and the scene's `kiss` in the files as they are, from the
             packs' sources.
"""
import argparse
import json
import os
import re
import sys
from collections import Counter

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import port_list  # noqa: E402

ANIMS = r"C:\Work\WorkSpace\Cyberpunk\CyberpunkAnimations"
# Inside a pack, at the game-root path of our data folder: the pack's zip installs them where the mod reads data.
SCENES_REL = os.path.join("bin", "x64", "plugins", "cyber_engine_tweaks", "mods", "nightcitynet", "data", "scenes")
NG_SCENES = os.path.join("data", "SKSE", "Plugins", "OStim", "scenes")
NG_TRANSLATIONS = os.path.join("data", "Interface", "translations")
NG_SEX = {"male": "m", "female": "f"}
OS_FURNITURE = {"Ben": "bench", "Cha": "chair", "Coo": "cookingpot", "Tab": "table", "She": "shelf"}
BODY = {"_ma": ("m", "npc"), "_wa": ("f", "npc"), "_pma": ("m", "player"), "_pwa": ("f", "player")}
SIDES = "ab"
# The acts the arousal model rates (data/anim_library.json's intimacy.acts), from each pack's own words for what a
# scene does. OpenSex's class code: (act, does the man give it). OStimNG's action types: the act; the action names
# actor and target itself.
# (act, given by the man); None = both ways, a 69.
OS_ACTS = {"Sx": ("penetrative", True), "BJ": ("oral_penis", False), "VJ": ("oral_vagina", True), "VHJ": ("oral_vagina", None),
           "HJ": ("manual", False), "BoJ": ("manual", False), "FJ": ("manual", False)}
NG_ACTS = {"vaginalsex": "penetrative", "analsex": "penetrative", "blowjob": "oral_penis", "lickingpenis": "oral_penis",
           "cunnilingus": "oral_vagina", "lickingvagina": "oral_vagina", "handjob": "manual", "boobjob": "manual",
           "buttjob": "manual", "footjob": "manual", "vaginalfingering": "manual", "analfingering": "manual",
           "rubbingclitoris": "manual", "malemasturbation": "manual", "femalemasturbation": "manual"}
# What a manual act is done with, from the pack's own action type: both packs' sources name it (OpenSex's <action> in
# its scene XML, OStimNG's "actions"). The shaft aims only into a hand (shaft-bones.md §2.4).
# Fingers in an opening are not a fist round a shaft: "fingers", so a man fingered is never aimed into a hand.
WITH = {"handjob": "hand", "malemasturbation": "hand", "femalemasturbation": "hand", "vaginalfingering": "fingers",
        "analfingering": "fingers", "rubbingclitoris": "fingers", "boobjob": "breasts", "buttjob": "butt", "footjob": "feet",
        "thighjob": "thighs"}
# A kiss, from the pack's own action type: on the mouth, else on the body. OSSO sounds `kissing` with its kiss and the
# rest with its skin kiss (intimacy-sound.md §5.11).
KISS = {"kissing": "mouth", "frenchkissing": "mouth", "kissingcheek": "skin", "kissingneck": "skin",
        "kissingfoot": "skin", "kissingfeet": "skin", "kissinghand": "skin"}
ACTION_XML = re.compile(r'<action\s+type="([^"]+)"\s+actor="(\d+)"(?:\s+target="(\d+)")?')
# A giver of oral who licks rather than sucks holds this mouth set over the act's (docs/design/mouth-hold.md).
LICK_MOUTH = {"oral_penis": "lollipop"}
# A word of its own (CamelCase or after a non-letter): not the "lick" in Click, not a tongue kiss.
LICK_WORDS = re.compile(r"(?:Lick|Tongue|(?<![A-Za-z])(?:lick|tongue))(?!_?[Kk]iss)")
# A penetrative act's opening, the shaft's aim (shaft-bones.md): OStimNG names it; OpenSex's Sx does not.
NG_INTO = {"vaginalsex": "vagina", "analsex": "anus"}
# One posture per actor, from both packs' actor tags. Two on one actor (bendover + standing) keep the first in this
# order, the more particular one; every other tag is a mod (facingaway, ontop, ...). An actor with none takes OpenSex's
# id code (opensex.ops.<a>-<b>.x).
POSTURES = ["bendover", "allfours", "handstanding", "suspended", "lyingback", "lyingfront", "lyingside", "squatting",
            "kneeling", "sitting", "standing"]
MODS = {"facingaway", "ontop", "onbottom", "climaxing", "drowsy", "kissing", "nostrip", "spreadlegs"}
POSTURE_CODES = {"sta": "standing", "kne": "kneeling", "sit": "sitting", "lyb": "lyingback", "lyf": "lyingfront",
                 "lys": "lyingside", "afo": "allfours", "squ": "squatting"}
# Where the tags and the code are both wrong: the carried actor of OpenSex's princess carries is coded standing, and
# one OStimNG actor is a bare "lying" in a scene named lying-front.
POSTURE_FIXES = {("opensex.ops.sta-sta.em.princesscarry", 1): "suspended",
                 ("ostimng.ostim2p.mm.idle.ostim2pkneelinglyingfrontmm", 1): "lyingfront"}
# Who gives where the class code's man is not the giver, measured from the clips (the giver's head at the other's hips):
# in the lesbian kneeling cunnilingus the lying actor 1 licks the kneeling actor 0.
GIVER_FIXES = {"OpS|Kne!LyB|VJ|LesbianKneLyBCunnilingus": 1}
# A scene whose class code rates nothing but whose clips do: Cr is caressing, and its grind is hips on hips.
ACT_FIXES = {"OpS|LyB!Kne|Cr|MountedGrind": [{"type": "grinding", "actor": "a", "target": "b"}]}


def set_body(path):
    stem = os.path.basename(path)[:-len(".anims")]
    for suffix in ("_pma", "_pwa", "_ma", "_wa"):
        if stem.endswith(suffix):
            return stem[:-len(suffix)], BODY[suffix]
    raise ValueError("set with no body suffix: " + path)


def read_clips(anims):
    """{ref: {sex: {npc, player}}}, and {ostimng clip: [ref]} for the one name two folders share."""
    clips, ng_refs = {}, {}
    for pack in ("opensex", "ostimng"):
        rows = json.load(open(os.path.join(anims, pack, "source-map.json"), encoding="utf-8"))
        names = Counter(r["clip"] for r in rows)
        for r in rows:
            group = set_body(r["sets"][0])[0]
            ref = "%s/%s" % (pack, r["clip"]) if names[r["clip"]] == 1 else "%s/%s#%s" % (pack, r["clip"], group)
            for s in r["sets"]:
                _, (sex, side) = set_body(s)
                clips.setdefault(ref, {}).setdefault(sex, {})[side] = s
            if pack == "ostimng":
                ng_refs.setdefault(r["clip"], []).append((group, ref))
    return clips, ng_refs


def read_translations(root):
    out = {}
    for f in ("OScenes_ENGLISH.txt", "ONav_ENGLISH.txt"):
        p = os.path.join(root, NG_TRANSLATIONS, f)
        for line in open(p, encoding="utf-16").read().splitlines():
            if line.startswith("$") and "\t" in line:
                k, v = line.split("\t", 1)
                out[k.lower()] = v.strip()
    return out


def nav_label(desc, tr):
    """'$ostim_nav_kiss_t{1}' -> 'kiss {1}': {N} is the name of actor N, as OStimNG fills it."""
    if not desc:
        return None
    m = re.search(r"\{(\d+)\}", desc)
    v = tr.get(re.sub(r"\{\d+\}", "{}", desc).lower())
    if v is None:
        return None
    return v.replace("{{}}", "{%s}" % m.group(1)) if m else v


def os_id(source):
    return "opensex." + source.lower().replace("|", ".").replace("!", "-")


def ng_id(rel):
    """data/SKSE/Plugins/OStim/scenes/OStim2P/MF/idle/X.json -> ostimng.ostim2p.mf.idle.x: OStimNG's own folders."""
    return "ostimng." + ".".join(p.lower() for p in rel[:-len(".json")].split("/")[5:])


def scene_path(out, sid):
    """The id is the path under data/scenes/: opensex.ops.sta-sta.ho.x -> opensex/ops/sta-sta/ho/x.json."""
    return os.path.join(out, *sid.split(".")) + ".json"


def os_acts(s):
    """OpenSex's class code as the act, given by the man (Sx, VJ) or to him (BJ, HJ, BoJ, FJ); [] = not rated."""
    if s["id"] in ACT_FIXES:
        return [dict(a) for a in ACT_FIXES[s["id"]]]
    parts = s["id"].split("|")
    act = OS_ACTS.get(parts[2]) if len(parts) > 2 and len(s["actors"]) == 2 else None
    if not act:
        return []
    if act[1] is None:
        return [{"type": act[0], "actor": SIDES[i], "target": SIDES[1 - i]} for i in (0, 1)]
    sexes = [a.get("sex") for a in s["actors"]]
    man = sexes.index("m") if sexes.count("m") == 1 else 0
    giver = GIVER_FIXES.get(s["id"], man if act[1] else 1 - man)
    return [{"type": act[0], "actor": SIDES[giver], "target": SIDES[1 - giver]}]


def ng_acts(j, n):
    """OStimNG's actions as acts, a penetrative one with the opening it names; [] = not rated. A masturbation names no
    target: the actor works on themself (the shaft aims into his own hand, shaft-bones.md)."""
    out = []
    for x in j.get("actions", []):
        self_act = x.get("type", "").endswith("masturbation")
        target = x.get("actor") if self_act else x.get("target")
        if x.get("type") not in NG_ACTS or n != 2 or x.get("actor") not in (0, 1) or target not in (0, 1) \
                or (x["actor"] == target and not self_act):
            continue
        act = {"type": NG_ACTS[x["type"]], "actor": SIDES[x["actor"]], "target": SIDES[target]}
        if x["type"] in NG_INTO:
            act["into"] = NG_INTO[x["type"]]
        out.append(act)
    return out


def source_actions(src, opensex, ostimng):
    """A source's own actions as (type, actor, target) with sides as indices; a masturbation's target is its actor."""
    root = opensex if src["pack"] == "opensex" else ostimng
    path = os.path.join(root, *src["file"].split("/"))
    if not os.path.isfile(path):
        return None
    with open(path, encoding="utf-8", errors="replace") as fh:
        text = fh.read()
    if src["pack"] == "opensex":
        found = [(t, int(a), int(g) if g else int(a)) for t, a, g in ACTION_XML.findall(text)]
    else:
        found = [(x.get("type", ""), x.get("actor"), x.get("target", x.get("actor"))) for x in json.loads(text).get("actions", [])]
    return [(t, a, g) for t, a, g in found if isinstance(a, int) and isinstance(g, int)]


def mark_with(s, opensex, ostimng, notes):
    """Each manual act's body part, from the first source that names an act for its sides; True = an act changed."""
    letters = "abcdefgh"
    parts = {}
    for src in s.get("sources", []):
        for t, a, g in source_actions(src, opensex, ostimng) or []:
            if t in WITH and a < len(letters) and g < len(letters):
                parts.setdefault((letters[a], letters[g]), WITH[t])
    changed = False
    for act in s.get("acts", []):
        if act.get("type") != "manual":
            continue
        part = parts.get((act["actor"], act["target"]))
        if not part:
            notes.append("manual act with no part in its sources: %s %s->%s" % (s["id"], act["actor"], act["target"]))
        elif act.get("with") != part:
            act["with"] = part
            changed = True
    return changed


def mark_kiss(s, opensex, ostimng):
    """The scene's kiss from its sources' actions, a mouth kiss over a skin one; True = it changed. None found leaves it."""
    found = {KISS[t] for src in s.get("sources", []) for t, _, _ in source_actions(src, opensex, ostimng) or []
             if t in KISS}
    kiss = "mouth" if "mouth" in found else "skin" if found else None
    if not kiss or s.get("kiss") == kiss:
        return False
    s["kiss"] = kiss
    return True


def lick_mouth(acts, licking):
    """The giver's mouth when the scene licks (OStimNG's lickingpenis, or lick/tongue in a source id); {} = the act's."""
    if not licking:
        return {}
    return {a["actor"]: LICK_MOUTH[a["type"]] for a in acts if a["type"] in LICK_MOUTH}


def normalise_actors(s, report, notes):
    """Each actor's `posture` and `mods` beside its pack's raw `tags`."""
    parts = s["id"].split(".")
    codes = parts[2].split("-") if parts[0] == "opensex" and len(parts) > 2 else []
    for i, a in enumerate(s["actors"]):
        tags = [t.lower() for t in a["tags"]]
        fix = next((p for (pre, n), p in POSTURE_FIXES.items() if n == i and s["id"].startswith(pre)), None)
        found = [p for p in POSTURES if p in tags]
        posture = fix or (found[0] if found else POSTURE_CODES.get(codes[i]) if i < len(codes) else None)
        if fix:
            report["actors whose posture is fixed by hand"] += 1
        elif not found and posture:
            report["actors whose posture is OpenSex's id code"] += 1
        elif not posture:
            notes.append("no posture: %s actor %d %s" % (s["id"], i, a["tags"]))
            report["actors with no posture"] += 1
        a["posture"] = posture
        a["mods"] = sorted({t for t in tags if t in MODS})
        for t in tags:
            if t not in MODS and t not in POSTURES and t != "lying":
                notes.append("unknown actor tag %r: %s actor %d" % (t, s["id"], i))
                report["unknown actor tags"] += 1


def opensex_scenes(anims):
    out = []
    for s in json.load(open(os.path.join(anims, "opensex", "scenes.json"), encoding="utf-8")):
        transition = all(a["t"] == "T" for a in s["anims"])
        furniture = None
        if s["id"].startswith("OpS_furniture|"):
            furniture = OS_FURNITURE.get(s["id"].split("|")[1][:3])
        out.append({
            "id": os_id(s["id"]),
            "name": s["name"],
            "animator": s["animator"] or None,
            "sources": [{"pack": "opensex", "id": s["id"], "file": s["file"]}],
            "actors": [{"sex": a.get("sex") or "any",
                        "tags": [t for t in (a.get("tags") or "").split(",") if t]} for a in s["actors"]],
            "speeds": [{"clips": [("opensex/" + c) if c else None for c in a["clips"]],
                        "playback": 1.0, "display": float(a["speed"]) if a.get("speed") else None}
                       for a in s["anims"]],
            "transition": transition,
            "next": s["anims"][0].get("dest") if transition else None,
            "length": float(s["anims"][0]["l"]) if transition else None,
            "moves": [{"to": g, "label": None} for g in s["goes"]],
            "tags": s["tags"],
            "furniture": furniture,
            "acts": os_acts(s),
        })
    return out


def ostimng_scenes(root, clip_map, clips, ng_refs, tr):
    out = []
    sdir = os.path.join(root, NG_SCENES)
    for d, _, fs in sorted(os.walk(sdir)):
        for f in sorted(fs):
            if not f.endswith(".json"):
                continue
            path = os.path.join(d, f)
            rel = os.path.relpath(path, root).replace(os.sep, "/")
            group = "_".join(rel.split("/")[5:8]).lower()
            j = json.load(open(path, encoding="utf-8-sig"))
            n = len(j.get("actors", []))

            def ref(anim, i):
                key = "%s_%d" % (anim.lower(), i)
                if key in ng_refs:
                    cands = ng_refs[key]
                    return next((r for g, r in cands if g == group), cands[0][1])
                if key in clip_map:
                    r = "opensex/" + clip_map[key].lstrip("_")
                    return r if r in clips else None
                return None

            transition = bool(j.get("destination"))
            stem = f[:-5]
            out.append({
                "id": ng_id(rel),
                "name": tr.get(j.get("name", "").lower(), j.get("name", "").lstrip("$")),
                "animator": None,
                "sources": [{"pack": "ostimng", "id": stem, "file": rel}],
                "actors": [{"sex": NG_SEX.get(a.get("intendedSex"), "any"), "tags": a.get("tags", [])}
                           for a in j.get("actors", [])],
                "speeds": [{"clips": [ref(s["animation"], i) for i in range(n)],
                            "playback": float(s.get("playbackSpeed", 1.0)),
                            "display": float(s["displaySpeed"]) if s.get("displaySpeed") is not None else None}
                           for s in j.get("speeds", []) if s.get("animation")],
                "transition": transition,
                "next": j.get("destination") if transition else None,
                "length": float(j["length"]) if transition and j.get("length") else None,
                "moves": [dict({"to": nv["destination"], "label": nav_label(nv.get("description"), tr)},
                               **({"priority": nv["priority"]} if isinstance(nv.get("priority"), int) else {}))
                          for nv in j.get("navigations", []) if nv.get("destination")],
                "tags": j.get("tags", []),
                "furniture": j.get("furniture"),
                "acts": ng_acts(j, n),
            })
            # OStimNG's climax: per actor, the scene its climax plays (autoTransitions.climax).
            climax = {SIDES[i]: a["autoTransitions"]["climax"] for i, a in enumerate(j.get("actors", [])[:2])
                      if isinstance(a.get("autoTransitions"), dict) and a["autoTransitions"].get("climax")}
            if climax:
                out[-1]["climax"] = climax
            if j.get("noRandomSelection") is True:
                out[-1]["noRandom"] = True   # never a random start; a menu may still offer it
    return out


def stages(speeds, actors, clips, report):
    """A scene's speeds with a file for every actor, none repeated."""
    # An actor with a file at one speed only keeps it at the others (inferred: the XML names no file for them).
    for i in range(actors):
        have = next((sp["clips"][i] for sp in speeds if sp["clips"][i] in clips), None)
        for sp in speeds:
            if have and sp["clips"][i] not in clips:
                sp["clips"][i] = have
                report["clips filled from the actor's slowest speed (inferred)"] += 1
    whole = [sp for sp in speeds if sp["clips"] and all(c and c in clips for c in sp["clips"])]
    report["speeds dropped, a clip with no file"] += len(speeds) - len(whole)
    # The same clips at the same rate is one stage: a start anim with no files filled as the first speed, or a
    # speed that names a slower one's anim. The one with a shown speed stays, where the first came.
    out = []
    for sp in whole:
        same = next((i for i, o in enumerate(out)
                     if o["clips"] == sp["clips"] and o["playback"] == sp["playback"]), None)
        if same is None:
            out.append(sp)
            continue
        if out[same]["display"] is None:
            out[same] = sp
        report["speeds dropped, a repeat of another"] += 1
    return out


def build(anims, ostimng, list_json):
    clip_map = json.load(open(list_json, encoding="utf-8"))["clipMap"]
    clips, ng_refs = read_clips(anims)
    tr = read_translations(ostimng)
    os_scenes = opensex_scenes(anims)
    ng_scenes = ostimng_scenes(ostimng, clip_map, clips, ng_refs, tr)
    report = Counter()
    notes = []

    for s in os_scenes + ng_scenes:
        s["speeds"] = stages(s["speeds"], len(s["actors"]), clips, report)

    # source id -> our id; an alias points at another scene's source id until resolved
    # Case-blind: OpenSex links OStimNG scenes as "OStim2PMIssionaryIdleMF".
    to_ours = {s["sources"][0]["id"].lower(): s["id"] for s in os_scenes + ng_scenes}
    alias = {}
    by_clips = {}
    for s in os_scenes:
        if s["speeds"]:
            by_clips.setdefault((tuple(a["sex"] for a in s["actors"]),
                                 tuple(tuple(sp["clips"]) for sp in s["speeds"])), s)
    scenes = {s["id"]: s for s in os_scenes}
    for s in ng_scenes:
        same = None
        if s["speeds"] and all(c.startswith("opensex/") for sp in s["speeds"] for c in sp["clips"]):
            sexes = tuple(a["sex"] for a in s["actors"])
            key = tuple(tuple(sp["clips"]) for sp in s["speeds"])
            same = by_clips.get((sexes, key)) or next(
                (o for (sx, k), o in by_clips.items() if k == key and all(a in (b, "any") for a, b in zip(sexes, sx))),
                None)
        if same is not None:
            alias[s["id"]] = same["id"]
            same["sources"] += s["sources"]
            same["moves"] += s["moves"]
            if s.get("climax"):
                same.setdefault("climax", {}).update(s["climax"])
            if not same.get("acts") and s.get("acts"):   # an OpenSex class code that rates nothing takes OStimNG's acts
                same["acts"] = s["acts"]
            for sp, osp in zip(s["speeds"], same["speeds"]):
                osp["playback"], osp["display"] = sp["playback"], osp["display"] or sp["display"]
            report["OStimNG scenes that are OpenSex scenes"] += 1
        else:
            scenes[s["id"]] = s

    for sid, s in list(scenes.items()):
        if s["speeds"]:
            continue
        out = [s["next"]] if s["transition"] and s["next"] else [m["to"] for m in s["moves"]]
        if len(set(out)) == 1:
            alias[sid] = to_ours.get(out[0].lower(), out[0])
            report["scenes with no playable speed, an alias for their one way out"] += 1
        else:
            notes.append("dropped, no playable speed and %d ways out: %s" % (len(set(out)), sid))
            report["scenes dropped, no playable speed"] += 1
        del scenes[sid]

    def resolve(source):
        sid = to_ours.get(source.lower(), source)
        seen = set()
        while sid in alias and sid not in seen:
            seen.add(sid)
            sid = alias[sid]
        return sid if sid in scenes else None

    for s in scenes.values():
        moves, seen = [], {}
        for m in s["moves"]:
            if m["to"].startswith("$"):   # OpenSex's menu commands ($InviteScan, $RemoveActor): a cast change
                report["moves dropped, a menu command"] += 1
                continue
            to = resolve(m["to"])
            if to is None:
                notes.append("move to a missing scene: %s -> %s" % (s["id"], m["to"]))
                report["moves dropped, missing scene"] += 1
            elif to in seen:
                seen[to]["label"] = seen[to]["label"] or m["label"]
                if "priority" in m and "priority" not in seen[to]:
                    seen[to]["priority"] = m["priority"]
            elif to != s["id"]:
                seen[to] = {"to": to, "label": m["label"]}
                if "priority" in m:
                    seen[to]["priority"] = m["priority"]
                moves.append(seen[to])
        s["moves"] = moves
        climax = {side: resolve(to) for side, to in (s.get("climax") or {}).items()}
        # OpenSex names a climax only in its scene ids (..._MaleClimax, ...ClimaxInternal): a move into one is the
        # man's climax from here.
        for m in moves:
            t = scenes[m["to"]]
            sid = t["sources"][0]["id"].lower()
            if "climax" in sid and "afterclimax" not in sid and s["id"].startswith("opensex."):
                sexes = [a["sex"] for a in s["actors"]]
                if len(sexes) == 2 and sexes.count("m") == 1:
                    climax.setdefault(SIDES[sexes.index("m")], m["to"])
        climax = {side: to for side, to in climax.items() if to and to != s["id"]}
        normalise_actors(s, report, notes)
        mark_with(s, port_list.OPENSEX, ostimng, notes)
        mark_kiss(s, port_list.OPENSEX, ostimng)
        mouth = lick_mouth(s["acts"], any(LICK_WORDS.search(src["id"]) for src in s["sources"]))
        if mouth:
            s["mouth"] = mouth
            report["scenes that lick, holding their own mouth"] += 1
        s.pop("climax", None)
        if climax:
            s["climax"] = climax
            report["scenes with a climax"] += 1
        if s["transition"]:
            s["next"] = resolve(s["next"]) if s["next"] else None
            if s["next"] is None:
                notes.append("transition with no next: %s" % s["id"])
                report["transitions with no next, played as a loop"] += 1
                s["transition"] = False
    used = {c for s in scenes.values() for sp in s["speeds"] for c in sp["clips"]}
    return scenes, {r: clips[r] for r in sorted(used)}, report, notes


def mark_files(files, ostimng):
    """--acts: the hand-edited files keep every byte but the parts; a file the writer would reformat is refused."""
    notes, changed = [], 0
    for f in files:
        if os.path.basename(f) == "clips.json":
            continue
        with open(f, encoding="utf-8", newline="") as fh:
            text = fh.read()
        s = json.loads(text)
        if json.dumps(s, indent=1, ensure_ascii=False) + "\n" != text:
            notes.append("not in the writer's format, left alone: %s" % f)
            continue
        withs = mark_with(s, port_list.OPENSEX, ostimng, notes)
        if mark_kiss(s, port_list.OPENSEX, ostimng) or withs:
            with open(f, "w", encoding="utf-8", newline="\n") as fh:
                json.dump(s, fh, indent=1, ensure_ascii=False)
                fh.write("\n")
            changed += 1
    for n in notes:
        print(n)
    print("%d scene files marked" % changed)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--anims", default=ANIMS)
    ap.add_argument("--ostimng", default=port_list.OSTIMNG)
    ap.add_argument("--list", default=port_list.OUT_JSON)
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--acts", action="store_true", help="only mark each manual act's body part and the kiss in the files")
    a = ap.parse_args()
    roots = {p: os.path.join(a.anims, p, SCENES_REL) for p in ("opensex", "ostimng")}
    old = [os.path.join(d, f) for r in roots.values() for d, _, fs in os.walk(r) for f in fs if f.endswith(".json")]
    if a.acts:
        return mark_files(old, a.ostimng)
    if old and not a.force:
        sys.exit("scene files exist under %s and are hand-edited from here on; --force to regenerate" % a.anims)
    scenes, clips, report, notes = build(a.anims, a.ostimng, a.list)
    for f in old:
        if os.path.basename(f) != "clips.json":   # climax_events.py's field: the clip's, not this build's
            with open(f, encoding="utf-8") as fh:
                s = json.load(fh)
            if s["id"] in scenes:
                if "climax_at" in s:
                    scenes[s["id"]]["climax_at"] = s["climax_at"]
                scenes[s["id"]]["name"] = s.get("name", scenes[s["id"]]["name"])   # names are hand-corrected
        os.remove(f)
    for r in roots.values():
        for d, _, _ in sorted(os.walk(r), reverse=True):
            if not os.listdir(d):
                os.rmdir(d)
    for sid, s in sorted(scenes.items()):
        path = scene_path(roots[sid.split(".")[0]], sid)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(s, fh, indent=1, ensure_ascii=False)
            fh.write("\n")
    # Each pack's clips.json holds the clips its own archive carries; an OStimNG scene's OpenSex half needs opensex/.
    for pack, r in roots.items():
        mine = {c: v for c, v in clips.items() if c.startswith(pack + "/")}
        with open(os.path.join(r, pack, "clips.json"), "w", encoding="utf-8", newline="\n") as fh:
            json.dump(mine, fh, indent=1)
            fh.write("\n")
    for n in notes:
        print(n)
    heads = Counter(len(s["actors"]) for s in scenes.values())
    print("%d scenes (%s), %d clips, %d moves, %d transitions" % (
        len(scenes), ", ".join("%dP %d" % kv for kv in sorted(heads.items())), len(clips),
        sum(len(s["moves"]) for s in scenes.values()), sum(s["transition"] for s in scenes.values())))
    for k, v in sorted(report.items()):
        print("  %s: %d" % (k, v))


if __name__ == "__main__":
    main()
