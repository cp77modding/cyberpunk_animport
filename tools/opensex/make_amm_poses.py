"""A pack's poses in AMM's list, PoNC's three pieces with no PoNC at play: a workspot, its host .ent and AMM's list file.

  python tools/opensex/make_amm_poses.py [--packs opensex,ostimng] [--anims DIR]
  python tools/opensex/make_amm_poses.py --add-rigs man_big,man_fat,woman_big,woman_fat   names baked rigs in clips.json

Output, inside the pack: archive/pc/mod/<pack>_amm.archive and AMM's Collabs/Custom Poses/nightcitynet/<pack>.lua.
The .ent is stencilled from PoNC's, so PoNC must be on this machine to build; the output does not need it.
AMM plays a clip by jumping to its name, so one sequence per pose, transitions left out. docs/design/opensex-port.md §5.
"""
import argparse
import json
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "retarget"))
import build_config  # noqa: E402

TOOLS = os.path.join(build_config.load()["mod"], "tools")   # the workspot builders stay the mod's
sys.path.insert(0, TOOLS)
import make_pose_workspots as mpw  # noqa: E402
import make_scene_workspots as msw  # noqa: E402

PONC_ARCHIVE = (r"D:\wabjack\cyberpunk\ultraviolence\mods\Pleasures of Night City - Sex Animations"
                r"\archive\pc\mod\PinkyDude_PleasuresOfNightCity_AnimsVol1.archive")
PONC_ENT = r"pinkydude\pleasures_of_nightcity\anims_vol1\amm\ponc_anims.ent"
PONC_WORKSPOT = r"pinkydude\pleasures_of_nightcity\anims_vol1\amm\ponc_anims.workspot"
BUILD = os.path.join(build_config.ROOT, "build", "amm_poses")
POSES_REL = os.path.join("bin", "x64", "plugins", "cyber_engine_tweaks", "mods", "AppearanceMenuMod", "Collabs",
                         "Custom Poses", "nightcitynet")
CATEGORY = {"opensex": "OpenSex", "ostimng": "OStimNG"}
# AMM's Poses.rigs. It has no row for woman_big or woman_fat, so those bodies get no list.
LABELS = {"man_base": "Man Average", "woman_base": "Woman Average", "man_big": "Big", "man_fat": "Fat",
          "player_man_skeleton": "Player Man", "player_woman_skeleton": "Player Woman"}


def pose_refs(scenes):
    """Every clip a scene holds on, by name: a transition plays once, so it is no pose to pick."""
    refs = {c for s in scenes if not s.get("transition") for sp in s["speeds"] for c in sp["clips"]}
    return sorted(r for r in refs if "#" not in r)


def rig_name(path):
    return os.path.basename(path.replace("\\", "/")).rsplit(".", 1)[0]


def amm_lua(category, entity, by_rig):
    """AMM's list file: {rig file name: [clip names]} under AMM's rig labels."""
    lines = ['return {', '  modder = "NightCityNet",', '  category = %s,' % json.dumps(category),
             '  entity_path = %s,' % json.dumps(entity), '  anims = {']
    for rig in sorted(by_rig):
        if rig in LABELS:
            names = ", ".join(json.dumps(n) for n in sorted(by_rig[rig]))
            lines.append('    [%s] = {%s},' % (json.dumps(LABELS[rig]), names))
    return "\n".join(lines + ['  }', '}', ''])


def sibling(npc_set, rig):
    """opensex\\anims\\npc\\x_ma.anims -> opensex\\anims\\man_big\\x_ma_man_big.anims."""
    head, leaf = npc_set.rsplit("\\npc\\", 1)
    return "%s\\%s\\%s_%s.anims" % (head, rig, leaf[:-len(".anims")], rig)


def rig_of_set(npc_set, rig):
    return npc_set.endswith("_ma.anims") == rig.startswith("man_")


def add_rigs(anims, pack, rigs):
    """clips.json names each baked rig's set beside npc and player; the DLL reads those two and ignores the rest."""
    root = os.path.join(anims, pack, msw.SCENES_REL, pack, "clips.json")
    with open(root, encoding="utf-8") as f:
        clips = json.load(f)
    added = 0
    for sexes in clips.values():
        for sides in sexes.values():
            for rig in rigs:
                npc = sides.get("npc", "")
                path = sibling(npc, rig) if npc and rig_of_set(npc, rig) else ""
                if path and os.path.isfile(os.path.join(anims, pack, "depot", path)):
                    added += rig not in sides
                    sides[rig] = path
    with open(root, "w", encoding="utf-8", newline="\n") as f:
        json.dump(clips, f, indent=1, ensure_ascii=False)
    print("%s: %d rig entries added to clips.json" % (pack, added))


def host_stencil(work):
    """PoNC's AMM .ent as json text: an arcade machine with one workspot component, amm_workspot_collab."""
    mpw.run([mpw.CLI, "unbundle", PONC_ARCHIVE, "-o", work, "-w", "*" + os.path.basename(PONC_ENT), "-v", "quiet"])
    ent = os.path.join(work, PONC_ENT)
    if not os.path.isfile(ent):
        sys.exit("PoNC has no " + PONC_ENT)
    mpw.run([mpw.CLI, "convert", "s", ent, "-v", "quiet"])
    with open(ent + ".json", encoding="utf-8") as f:
        return f.read()


def deserialize(doc_text, out, what):
    with open(out + ".json", "w", encoding="utf-8") as f:
        f.write(doc_text)
    mpw.run([mpw.CLI, "convert", "d", out + ".json", "-o", os.path.dirname(out), "-v", "quiet"])
    if not os.path.isfile(out):
        sys.exit("deserialize produced no " + what)
    os.remove(out + ".json")
    with open(out, "rb") as f:
        blob = f.read()
    for leak in (b"gh0st", b"bedroom_ff", b"pinkydude", b"ponc_anims"):
        if leak in blob:
            sys.exit("stencil content leaked into %s: %s" % (what, leak.decode()))


def build(anims, pack, base, ent_text):
    msw.PACKS = (pack,)
    scenes, clips, local = msw.read_packs(anims)
    rel = os.path.join("ncn", "workspots", "amm")
    work = os.path.join(BUILD, pack)
    raw, packed = os.path.join(work, "raw", rel), os.path.join(work, "packed")
    shutil.rmtree(work, ignore_errors=True)
    os.makedirs(raw)
    os.makedirs(packed)

    seen, sets_of, names_of, by_rig, names = {}, {}, {}, {}, []
    for ref in pose_refs(scenes):
        owner, name = ref.split("/", 1)
        if owner != pack:   # a scene may hold on another pack's clip; that pack lists it
            continue
        if name in seen:
            sys.exit("clip name %s twice: %s, %s" % (name, seen[name], ref))
        seen[name] = ref
        names.append(name)
        for sides in clips[ref].values():
            for depot in sides.values():
                key = depot.lower()
                if key not in local:
                    sys.exit("%s names set %s, which the pack's depot does not hold" % (ref, depot))
                if key not in names_of:
                    names_of[key] = mpw.clip_names(local[key])
                    rigs = sorted(mpw.rigs_of(local[key]))
                    if len(rigs) != 1:
                        sys.exit("set %s names %d rigs, want one" % (depot, len(rigs)))
                    sets_of[key] = rigs[0]
                if name not in names_of[key]:
                    sys.exit("%s: clip %s is not in its set %s" % (ref, name, depot))
                by_rig.setdefault(sets_of[key], {}).setdefault(depot, set()).add(name)

    rows = [(rig, sorted(sets)) for rig, sets in sorted(by_rig.items())]
    leaf = "%s_poses" % pack
    workspot = "%s\\%s.workspot" % (rel, leaf)
    doc = msw.build_tree(base, rows, names, {})
    if isinstance(doc.get("Header"), dict):
        doc["Header"]["ArchiveFileName"] = os.path.join(raw, leaf + ".workspot")
    deserialize(json.dumps(doc, indent=1), os.path.join(raw, leaf + ".workspot"), leaf + ".workspot")
    entity = "%s\\%s.ent" % (rel, leaf)
    text = ent_text.replace(json.dumps(PONC_WORKSPOT)[1:-1], json.dumps(workspot)[1:-1])
    text = text.replace(json.dumps(PONC_ENT)[1:-1], json.dumps(entity)[1:-1])
    deserialize(text, os.path.join(raw, leaf + ".ent"), leaf + ".ent")

    mpw.run([mpw.CLI, "pack", os.path.join(work, "raw"), "-o", packed, "-v", "quiet"])
    made = [f for f in os.listdir(packed) if f.endswith(".archive")]
    if not made:
        sys.exit("pack produced no archive")
    arc = os.path.join(anims, pack, "archive", "pc", "mod", pack + "_amm.archive")
    shutil.copyfile(os.path.join(packed, made[0]), arc)

    lists = {rig_name(rig): sorted({n for ns in sets.values() for n in ns}) for rig, sets in by_rig.items()}
    lua = os.path.join(anims, pack, POSES_REL, pack + ".lua")
    os.makedirs(os.path.dirname(lua), exist_ok=True)
    with open(lua, "w", encoding="utf-8", newline="\n") as f:
        f.write(amm_lua(CATEGORY[pack], entity, lists))
    print("%s: %d poses, %s -> %s" % (pack, len(names), ", ".join(
        "%s %d" % (r, len(n)) for r, n in sorted(lists.items())), arc))


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--anims", default=msw.ANIMS)
    ap.add_argument("--packs", default="opensex,ostimng")
    ap.add_argument("--add-rigs", default="", help="only name these baked rigs' sets in clips.json")
    a = ap.parse_args()
    packs = a.packs.split(",")
    if a.add_rigs:
        for pack in packs:
            add_rigs(a.anims, pack, a.add_rigs.split(","))
        return
    for need in (mpw.CLI, mpw.STENCIL_ARCHIVE, PONC_ARCHIVE):
        if not os.path.isfile(need):
            sys.exit("not found: " + need)
    src = os.path.join(BUILD, "stencil")
    shutil.rmtree(src, ignore_errors=True)
    os.makedirs(src)
    mpw.run([mpw.CLI, "extract", mpw.STENCIL_ARCHIVE, "-o", src, "-w", "*" + mpw.STENCIL_LEAF, "-v", "quiet"])
    stencil = next((os.path.join(r, mpw.STENCIL_LEAF) for r, _, fs in os.walk(src) if mpw.STENCIL_LEAF in fs), None)
    if not stencil:
        sys.exit("stencil not found in " + mpw.STENCIL_ARCHIVE)
    mpw.run([mpw.CLI, "convert", "s", stencil, "-o", src, "-v", "quiet"])
    with open(os.path.join(src, mpw.STENCIL_LEAF + ".json"), encoding="utf-8") as f:
        base = json.load(f)
    mpw.renumber(base)
    ent_text = host_stencil(src)
    for pack in packs:
        build(a.anims, pack, base, ent_text)


if __name__ == "__main__":
    main()
