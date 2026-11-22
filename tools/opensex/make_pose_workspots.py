"""Build ncn_pose_workspots.archive -- a GENERATED workspot over a photo-mode pose pack's .anims.

WHY. A pose pack ships in two flavours (docs/design/multi-actor-tableau.md §5): the AMM one carries
an entity + .workspot and we can mount it directly; the PM one registers its .anims onto
`player_wa_photomode.ent` through ArchiveXL and ships NO workspot at all. 280 of the 367 installed
packs are PM-flavour, so "generate a workspot over a pack's anims" is the general case. This is that
generator.

WHAT IT MAKES. An INDEX workspot: one child sequence per clip, each looping one workAnimClip named
exactly as the animation is named in the .anims. That is the shape every mod pose pack uses --
measured, not guessed (bedroom_ff.workspot: 24 workAnimClip, ZERO workSyncAnimClip, no slot names).
Mount an actor on it and SendJumpToAnimEnt(clip) selects the pose; N actors on N components of the
same resource, each jumped to its own clip, is a tableau.

STRUCTURAL TEMPLATE: an installed AMM-flavour pose workspot, read at build time for its anim graph
(rootNode/nodesToInit/variables). Their file is never committed, and the animsets, rigs, clip entries,
transitions and tag lists are all replaced -- but the GRAPH IS THEIRS VERBATIM, and it is not pure
boilerplate: its four facialIdle CNames are authored picks that set the facial idle of every actor we
mount. FACIAL_IDLE below overrides them so the value is ours. The leak guard greps the stencil pack's
own name, so anything it re-uses from vanilla (as those CNames are) passes it -- the guard proves the
pack's content is gone, not that every value was chosen. FOR PUBLIC RELEASE: re-stencil from a vanilla
workspot so no pose pack has to be installed to build, and retarget the guard's literals with it.

NOTHING VANILLA IS REPLACED -- the output lives under ncn\\workspots\\poses\\.

Run:  python tools/opensex/make_pose_workspots.py     (then deploy + FULL RESTART; an archive mounts at startup)
Output: <mod>/archive/pc/mod/ncn_pose_workspots.archive. Its helpers (run, clip_names, rigs_of, renumber, ...) are
what make_scene_workspots.py and make_amm_poses.py build on; they need no pose pack.
"""
import copy
import json
import os
import re
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "retarget"))
import build_config  # noqa: E402

REPO = build_config.load()["mod"]   # its pose archive is the mod's
CLI = build_config.load()["tools"]["wolvenkit"] or "WolvenKit.CLI.exe"
MODS = r"D:\wabjack\cyberpunk\ultraviolence\mods"

BUILD = os.path.join(REPO, "build", "pose_workspots")
SRC = os.path.join(BUILD, "src")
RAW = os.path.join(BUILD, "raw")
PACKED = os.path.join(BUILD, "packed")
OUT_ARCHIVE = os.path.join(REPO, "archive", "pc", "mod", "ncn_pose_workspots.archive")
DEST_DIR = os.path.join("ncn", "workspots", "poses")

# The stencil: any installed AMM-flavour pose workspot. Only its graph survives.
STENCIL_ARCHIVE = os.path.join(
    MODS, "mynameisfive - Custom Poses - Bedroom Pack I (Erotic Poses for MF - FF - MBF)",
    "archive", "pc", "mod", "gh0st_Poses_Bedroom_Pack01_FF.archive")
STENCIL_LEAF = "bedroom_ff.workspot"

# `anims`: depot paths from the pack's .xl; its rigs are read off the .anims (rigs_of), never declared.
# `extra_rigs`: rigs the animsets do not name -- the player's, so a pose plays on V too.
PACKS = [
    {
        "name": "ncn_triple_play_vol2",
        "mod": "Busy - Triple Play VOL 2 - Threesome Pose Pack",
        "archive": "BV - Triple Play Pose Pack Vol. 2.archive",
        # one animset per rig row, as every shipped pack has; the bonus one holds only BONUS_* clips
        "anims": [
            r"base\busyvampire\bv_ncs_commission\bv_ncs_commission_female_vol2.anims",
        ],
        "extra_rigs": [r"base\characters\entities\player\player_woman_skeleton.rig"],
    },
    {
        # V lying in bed under the sleep dial (sleep-picker.md): vanilla's prologue wake-up idle, the pose the bed
        # scene's lie-down clip ends in. A game animset per player rig; the clips are named, there is no pose_packs row.
        "name": "ncn_v_bed",
        "game": True,
        "rig_anims": {
            r"base\characters\entities\player\player_man_skeleton.rig":
                r"base\animations\quest\main_quests\prologue\q001\q001_01_wakeup\anim\body\q001_01_wakeup__player_male.anims",
            r"base\characters\entities\player\player_woman_skeleton.rig":
                r"base\animations\quest\main_quests\prologue\q001\q001_01_wakeup\anim\body\q001_01_wakeup__player_female.anims",
        },
        "clips": ["q001_01_wakeup__lie_bed__turn90__01"],
    },
]
GAME_ARCHIVES = [r"D:\SteamLibrary\steamapps\common\Cyberpunk 2077\archive\pc\content",
                 r"D:\SteamLibrary\steamapps\common\Cyberpunk 2077\archive\pc\ep1"]

# the fade a pose switch costs: two static poses faded over the stencil's 0.5 s morph; 0.1 is joytoysex's
CLIP_BLEND_OUT = 0.1
# Both inherited from the stencil rather than chosen; these are the clip-jumped pack's values.
EXIT_FORCED = 0.2
BLACKLIST_TAGS = []
# the stencil's facial idles drive every mounted face; ours run their own solve, so these stay neutral
FACIAL_IDLE = {
    "facialIdleFemaleAnimation": "idle__neutral__female",
    "facialIdleMaleAnimation": "idle__neutral__male",
    "facialIdleKey_FemaleAnimation": "None",
    "facialIdleKey_MaleAnimation": "None",
}

M64 = (1 << 64) - 1


def run(args):
    r = subprocess.run(args, capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit("FAILED: %s\n%s\n%s" % (" ".join(args), (r.stdout or "")[-2000:],
                                         (r.stderr or "")[-2000:]))
    return r.stdout or ""


def cname(v):
    return {"$type": "CName", "$storage": "string", "$value": v}


def rpath(v, flags="Default"):
    return {"DepotPath": {"$type": "ResourcePath", "$storage": "string", "$value": v},
            "Flags": flags}


def fnv1a64(s):
    h = 0xCBF29CE484222325
    for b in s.encode():
        h ^= b
        h = (h * 0x100000001B3) & M64
    return h


def find_type(node, want, out=None):
    out = [] if out is None else out
    if isinstance(node, dict):
        if node.get("$type") == want:
            out.append(node)
        for v in node.values():
            find_type(v, want, out)
    elif isinstance(node, list):
        for v in node:
            find_type(v, want, out)
    return out


def renumber(doc):
    """Give every handle in the document a fresh HandleId, dense and in document order.

    WolvenKit writes them dense; splicing in new chunks by hand would leave holes or duplicates, and
    a duplicate silently aliases two chunks. Verified as a NO-OP on the untouched stencil (below),
    which is what says document order is the order WolvenKit itself uses.
    """
    n = [0]

    def walk(x):
        if isinstance(x, dict):
            if "HandleId" in x:
                x["HandleId"] = str(n[0])
                n[0] += 1
            for v in x.values():
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)

    walk(doc)
    return n[0]


def clip_names(anims_path):
    """Animation names as the .anims itself spells them.

    The pose ids in the tweak yaml are what pose_packs.json records, but the workspot has to name the
    ANIMATION, so they are read back out of the resource. WolvenKit cannot serialize .anims (it
    returns an empty file), so this reads the CR2W string table directly -- every animAnimation name
    is stored there as plain ASCII.
    """
    b = open(anims_path, "rb").read()
    return {s.decode() for s in re.findall(rb"[!-~]{4,}", b)}


def rigs_of(anims_path):
    """Every .rig the animset names, read the same way as the clip names. A rig is a depot path: compressed
    bytes can spell a bare ".RiG"."""
    return {s for s in clip_names(anims_path) if s.lower().endswith(".rig") and "\\" in s}


def main():
    if not os.path.isfile(CLI):
        sys.exit("WolvenKit CLI not found: " + CLI)
    if not os.path.isfile(STENCIL_ARCHIVE):
        sys.exit("stencil pack not installed: " + STENCIL_ARCHIVE)

    for d in (SRC, RAW, PACKED):
        shutil.rmtree(d, ignore_errors=True)
        os.makedirs(d)
    out_dir = os.path.join(RAW, DEST_DIR)
    os.makedirs(out_dir)

    print("stencil ...", flush=True)
    run([CLI, "extract", STENCIL_ARCHIVE, "-o", SRC, "-w", "*" + STENCIL_LEAF, "-v", "quiet"])
    stencil = None
    for root, _dirs, files in os.walk(SRC):
        if STENCIL_LEAF in files:
            stencil = os.path.join(root, STENCIL_LEAF)
            break
    if not stencil:
        sys.exit("stencil not found in " + STENCIL_ARCHIVE)
    run([CLI, "convert", "s", stencil, "-o", SRC, "-v", "quiet"])
    stencil_json = os.path.join(SRC, STENCIL_LEAF + ".json")
    base = json.load(open(stencil_json, encoding="utf-8"))

    # RENUMBER IS A NO-OP ON AN UNTOUCHED FILE, or the numbering below is not the numbering
    # WolvenKit reads. Cheap, and it fails the build instead of shipping aliased chunks.
    before = json.dumps(base)
    renumber(base)
    if json.dumps(base) != before:
        sys.exit("renumber changed the untouched stencil -- handle order is not document order")

    manifest = {}
    for pack in PACKS:
        if pack.get("game"):
            clips, rig_rows = game_pack(pack)
        else:
            clips, rig_rows = mod_pack(pack)

        doc = copy.deepcopy(base)
        tree = find_type(doc["Data"]["RootChunk"], "workWorkspotTree")
        if len(tree) != 1:
            sys.exit("expected one workWorkspotTree in the stencil, found %d" % len(tree))
        tree = tree[0]

        # `hash` is ours, constant per animset list as the cooker's is (its algorithm is not recovered);
        # nothing resolves through it
        tree["finalAnimsets"] = [{
            "$type": "workWorkspotAnimsetEntry",
            "animations": {
                "$type": "animAnimSetup",
                "cinematics": [{"$type": "animAnimSetupEntry", "animSet": rpath(a),
                                "priority": 128, "variableNames": []} for a in anims],
                "gameplay": [],
                "hash": str(fnv1a64("|".join(anims))),
            },
            "loadingHandles": [rpath(a) for a in anims],
            "rig": rpath(rig, "Soft"),
        } for rig, anims in rig_rows]
        emit(doc, tree, pack, clips, out_dir, manifest)

    print("pack ...", flush=True)
    run([CLI, "pack", RAW, "-o", PACKED, "-v", "quiet"])
    cands = [f for f in os.listdir(PACKED) if f.endswith(".archive")]
    if not cands:
        sys.exit("pack produced no archive")
    os.makedirs(os.path.dirname(OUT_ARCHIVE), exist_ok=True)
    shutil.copyfile(os.path.join(PACKED, cands[0]), OUT_ARCHIVE)
    print("OK -> %s (%.1f KB)" % (OUT_ARCHIVE, os.path.getsize(OUT_ARCHIVE) / 1024.0))


def game_pack(pack):
    """A pack over the game's own animsets: one animset per rig, the clips named and each present in every animset."""
    anims_dir = os.path.join(SRC, "anims", pack["name"])
    os.makedirs(anims_dir, exist_ok=True)
    leaves = [a.split("\\")[-1] for a in pack["rig_anims"].values()]
    pattern = "(" + "|".join(re.escape(l) for l in leaves) + ")$"
    for d in GAME_ARCHIVES:
        if os.path.isdir(d):
            run([CLI, "unbundle", d, "-r", pattern, "-o", anims_dir, "-v", "quiet"])
    rows = []
    for rig, a in pack["rig_anims"].items():
        p = os.path.join(anims_dir, *a.split("\\"))
        if not os.path.isfile(p):
            sys.exit("animset not in the game archives: " + a)
        if rig.lower() not in {r.lower() for r in rigs_of(p)}:
            sys.exit("%s does not name %s -- the rig row would play nothing" % (a, rig))
        bad = [c for c in pack["clips"] if c not in clip_names(p)]
        if bad:
            sys.exit("%s has no clip %s" % (a, ", ".join(bad)))
        rows.append((rig, [a]))
    print("%s: %d clip(s) over %d rig(s)" % (pack["name"], len(pack["clips"]), len(rows)))
    return list(pack["clips"]), rows


def mod_pack(pack):
    """A PM pose pack's animset out of its installed archive, its clips the ones pose_packs.json advertises."""
    anims_dir = os.path.join(SRC, "anims", pack["name"])
    os.makedirs(anims_dir, exist_ok=True)
    src_archive = os.path.join(MODS, pack["mod"], "archive", "pc", "mod", pack["archive"])
    if not os.path.isfile(src_archive):
        sys.exit("pack not installed: " + src_archive)
    run([CLI, "extract", src_archive, "-o", anims_dir, "-w", "*.anims", "-v", "quiet"])

    have, found_rigs = set(), set()
    for a in pack["anims"]:
        p = os.path.join(anims_dir, *a.split("\\"))
        if not os.path.isfile(p):
            sys.exit("animset not in the pack archive: " + a)
        have |= clip_names(p)
        found_rigs |= rigs_of(p)
    if not found_rigs:
        sys.exit("no .rig named in the animsets -- cannot tell which bodies can play " +
                 pack["name"])
    # every rig row is built from the whole `anims` list, so a second entry would put female clips under
    # man_base; a pack with an animset per rig uses `rig_anims` (game_pack)
    if len(pack["anims"]) != 1:
        sys.exit("%s: %d animsets. A rig row must name exactly one, or the build silently gives "
                 "every rig every animset." % (pack["name"], len(pack["anims"])))
    seen_rigs = {r.lower() for r in found_rigs}
    rigs = sorted(found_rigs)
    for r in pack.get("extra_rigs", []):
        if r.lower() not in seen_rigs:
            seen_rigs.add(r.lower())
            rigs.append(r)
    print("%s: rigs %s%s" % (pack["name"], ", ".join(sorted(found_rigs)),
                             ("  + declared " + ", ".join(pack.get("extra_rigs", [])))
                             if pack.get("extra_rigs") else ""))

    # Every clip the pack advertises, kept only if the .anims actually names it.
    packs_json = json.load(open(os.path.join(REPO, "data", "pose_packs.json"), encoding="utf-8"))
    rows = [r for r in packs_json["packs"]
            if r["mod"] == pack["mod"] and r.get("source") == "photomode"]
    if not rows:
        sys.exit("no photomode row in pose_packs.json for " + pack["mod"])
    advertised = []
    for r in rows:
        for lst in r.get("poses", {}).values():
            advertised += lst
    advertised = sorted(set(advertised))
    clips = [c for c in advertised if c in have]
    missing = [c for c in advertised if c not in have]
    print("%s: %d/%d advertised clips found in the animsets"
          % (pack["name"], len(clips), len(advertised)))
    if missing:
        # ALL of them, and the count first. A truncated list reads as "a few odd ones" when it
        # is really "an animset you dropped", and those two want opposite responses.
        print("  %d not in the listed animsets (an animset this pack declares but PACKS omits, "
              "or a name pose_packs.json has wrong):" % len(missing))
        for c in missing:
            print("    " + c)
    if not clips:
        sys.exit("no clip name matched -- the animset names differ from the tweak ids")
    return clips, [(rig, list(pack["anims"])) for rig in rigs]


def emit(doc, tree, pack, clips, out_dir, manifest):
    """The index tree over `clips`, written as the pack's .workspot and checked against the library."""
    # The stencil's transitions are vanilla clip names (stand_wall_lean180__*) that match none of
    # ours, so they are inert -- but they are content we did not choose and the leak guard below
    # cannot see them: it greps for the pack's own name, and these are vanilla strings.
    tree["customTransitionAnims"] = []

    # The index: root sequence -> one looping child per clip -> that clip.
    root = tree["rootEntry"]["Data"]
    # The graph came from the stencil; these four are the only authored values in it.
    hubs = find_type(doc["Data"]["RootChunk"], "animAnimNode_WorkspotHub")
    if len(hubs) != 1:
        sys.exit("expected one animAnimNode_WorkspotHub in the stencil, found %d" % len(hubs))
    for field, value in FACIAL_IDLE.items():
        if field not in hubs[0]:
            sys.exit("stencil hub has no %s -- the graph changed shape" % field)
        hubs[0][field] = cname(value)

    tree["inertializationDurationExitForced"] = EXIT_FORCED
    tree["blacklistVisualTags"] = {"$type": "redTagList",
                                   "tags": [cname(t) for t in BLACKLIST_TAGS]}
    root["idleAnim"] = cname("None")
    root["loopInfinitely"] = 0
    children, next_id = [], 2
    for c in clips:
        children.append({"HandleId": "0", "Data": {
            "$type": "workSequence", "category": "Any", "disableAutoTransition": 0, "flags": 0,
            "id": {"$type": "workWorkEntryId", "id": next_id},
            "idleAnim": cname(c),
            "list": [{"HandleId": "0", "Data": {
                "$type": "workAnimClip", "animName": cname(c), "blendOutTime": CLIP_BLEND_OUT,
                "flags": 2, "id": {"$type": "workWorkEntryId", "id": next_id + 1}}}],
            "loopInfinitely": 1, "previousLoopInfinitely": 0}})
        next_id += 2
    root["list"] = children
    tree["idCounter"] = next_id

    renumber(doc)
    out_ws = os.path.join(out_dir, pack["name"] + ".workspot")
    out_json = out_ws + ".json"
    if isinstance(doc.get("Header"), dict):
        doc["Header"]["ArchiveFileName"] = out_ws
    json.dump(doc, open(out_json, "w", encoding="utf-8"), indent=1)
    run([CLI, "convert", "d", out_json, "-o", out_dir, "-v", "quiet"])
    if not os.path.isfile(out_ws):
        sys.exit("deserialize produced no .workspot for " + pack["name"])
    os.remove(out_json)

    # NOTHING OF THE STENCIL'S OWN CONTENT MAY SURVIVE -- it is a third-party file we only
    # borrowed a graph from. Its depot prefix appearing in our output is a leak, and a leak means
    # a broken reference on any machine without that pack installed.
    blob = open(out_ws, "rb").read()
    for leak in (b"gh0st", b"bedroom_ff"):
        if leak in blob:
            sys.exit("stencil content leaked into %s: %s" % (pack["name"], leak.decode()))
    # THE NAMES THE RUNTIME WILL ACTUALLY JUMP TO. Nothing else checks them: this tool reads
    # pose_packs.json, make_anim_host_mod.py never opens the workspot, and a typo in `poses` is
    # a jump to no entry -- which renders as a body in its bind pose, found only in game.
    emitted = set(clips)
    for row in json.load(open(os.path.join(REPO, "data", "anim_library.json"),
                              encoding="utf-8"))["actions"]:
        if row.get("kind") != "tableau" or row.get("workspot", "").split("\\")[-1] \
                != pack["name"] + ".workspot":
            continue
        for tab, names in (row.get("poses") or {}).items():
            bad = [n for n in names if n not in emitted]
            if bad:
                sys.exit("anim_library row %s, tableau %s names clips this workspot has no "
                         "entry for: %s" % (row.get("id"), tab, ", ".join(bad)))
            if len(names) != len(row.get("slots") or []):
                sys.exit("anim_library row %s, tableau %s has %d clips for %d slots"
                         % (row.get("id"), tab, len(names), len(row.get("slots") or [])))

    manifest[pack["name"]] = clips
    print("  -> %s\\%s.workspot  %d entries  %.0f KB"
          % (DEST_DIR, pack["name"], len(clips), len(blob) / 1024.0))


if __name__ == "__main__":
    main()
