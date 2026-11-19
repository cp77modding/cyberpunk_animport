"""Probe 2: a PoNC pose with a finalAnimsets row for V's own skeletons, on top of the retarget probe.

Probe 1 (make_retarget_mod.py) gave V's skeletons a `retargets` source and failed in game: V entered the
workspot and nothing played, because the workspot has no row for V's rig to select. This adds that row --
player_man_skeleton -> the man_base animset, player_woman_skeleton -> the woman_base one -- to copies of
the pose's two halves, and packs them with probe 1's rigs. Row selects, rig converts: if that pair is how
the engine serves one animset to two skeletons, V plays.

The archive is named to load before PoNC's, so these copies shadow the originals at the same paths.
Install for a run only (tools/e2e/scenarios/v_rig_retarget.ps1 -Probe).

Probe 3, --baked: the player rows name the set baked onto V's skeleton by retarget.ps1
(work/depot/ncn/anims/player/<set>_player.anims) instead, and the archive carries those sets, not the rigs.

Run: python tools/retarget/make_v_row_probe.py [pose_stem] [--baked]   (after make_retarget_mod.py,
     or for --baked after retarget.ps1 has baked every set the pose names)
"""
import copy
import json
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
WORK = os.path.join(HERE, "work")
WKIT = r"C:\Modding\wolwenKit_upacker\WolvenKit.CLI.exe"
PONC = (r"D:\wabjack\cyberpunk\ultraviolence\mods\Pleasures of Night City - Sex Animations"
        r"\archive\pc\mod\PinkyDude_PleasuresOfNightCity_AnimsVol1.archive")
BAKED = "--baked" in sys.argv
NAME = "ncn_v_rig_baked" if BAKED else "ncn_v_rig_probe"
# '#' sorts the archive before PinkyDude_*; pack names an archive after its folder, so it is added after.
SHIPPED = "#" + NAME
PLAYER = {
    r"base\characters\base_entities\man_base\man_base.rig":
        r"base\characters\entities\player\player_man_skeleton.rig",
    r"base\characters\base_entities\woman_base\woman_base.rig":
        r"base\characters\entities\player\player_woman_skeleton.rig",
}


def run(*args):
    r = subprocess.run([WKIT] + list(args), capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit("WolvenKit failed: %s\n%s%s" % (" ".join(args), r.stdout, r.stderr))
    return r.stdout


def rows(doc):
    return doc["Data"]["RootChunk"]["workspotTree"]["Data"]["finalAnimsets"]


def baked_of(animset):
    return "ncn\\anims\\player\\%s_player.anims" % os.path.splitext(animset.split("\\")[-1])[0]


def fnv1a64(text):
    h = 0xcbf29ce484222325
    for c in text.lower().encode():
        h = ((h ^ c) * 0x100000001b3) & 0xFFFFFFFFFFFFFFFF
    return h


def point_at(row, animset):
    for entry in row["animations"]["cinematics"]:
        entry["animSet"]["DepotPath"]["$value"] = animset
    for handle in row["loadingHandles"]:
        handle["DepotPath"]["$value"] = animset


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    stem = args[0] if args else "ponc_synced_missionary_01"
    build = os.path.join(WORK, "vrow")
    shutil.rmtree(build, ignore_errors=True)
    raw, depot = os.path.join(build, "raw"), os.path.join(build, NAME)
    os.makedirs(raw)
    if not BAKED:
        rigs = os.path.join(WORK, "mod", "source")
        if not os.path.isdir(rigs):
            sys.exit("run make_retarget_mod.py first -- no %s" % rigs)
        shutil.copytree(rigs, depot)

    run("unbundle", PONC, "-o", raw, "-w", "*%s_*.workspot" % stem, "-v", "Quiet")
    found = []
    for root, _, files in os.walk(raw):
        for f in files:
            if f.endswith(".workspot"):
                found.append(os.path.join(root, f))
    if len(found) != 2:
        sys.exit("expected the pose's two halves, found %s" % found)

    for path in found:
        run("convert", "serialize", path, "-v", "Quiet")
        doc = json.load(open(path + ".json", encoding="utf-8"))
        added = []
        for row in list(rows(doc)):
            rig = row["rig"]["DepotPath"]["$value"]
            if rig in PLAYER:
                twin = copy.deepcopy(row)
                twin["rig"]["DepotPath"]["$value"] = PLAYER[rig]
                if BAKED:
                    animset = baked_of(row["animations"]["cinematics"][0]["animSet"]["DepotPath"]["$value"])
                    cooked = os.path.join(WORK, "depot", animset)
                    if not os.path.isfile(cooked):
                        sys.exit("not baked: %s -- run retarget.ps1 for it" % cooked)
                    point_at(twin, animset)
                    os.makedirs(os.path.dirname(os.path.join(depot, animset)), exist_ok=True)
                    shutil.copy(cooked, os.path.join(depot, animset))
                    # The engine caches a row's runtime setup by this hash; a copied one hands V the NPC row's setup.
                    twin["animations"]["hash"] = str(fnv1a64(os.path.basename(path) + "|" + PLAYER[rig] + "|" + animset))
                rows(doc).append(twin)
                added.append(os.path.basename(PLAYER[rig]))
        if len(added) != len(PLAYER):
            sys.exit("%s: rows for %s only" % (os.path.basename(path), added))
        rel = os.path.relpath(os.path.dirname(path), raw)
        out = os.path.join(build, "json", rel)
        os.makedirs(out, exist_ok=True)
        json.dump(doc, open(os.path.join(out, os.path.basename(path) + ".json"), "w", encoding="utf-8"), indent=2)
        # deserialize writes nothing, and fails, into a folder that does not exist yet.
        os.makedirs(os.path.join(depot, rel), exist_ok=True)
        run("convert", "deserialize", os.path.join(out, os.path.basename(path) + ".json"),
            "-o", os.path.join(depot, rel), "-v", "Quiet")
        print("%-40s + rows %s" % (os.path.basename(path), ", ".join(added)))

    # Read every cooked workspot back: four rows, the player ones naming the NPC animsets (or their bakes).
    for root, _, files in os.walk(depot):
        for f in files:
            if not f.endswith(".workspot"):
                continue
            check = os.path.join(build, "check")
            os.makedirs(check, exist_ok=True)
            shutil.copy(os.path.join(root, f), check)
            run("convert", "serialize", os.path.join(check, f), "-v", "Quiet")
            back = rows(json.load(open(os.path.join(check, f + ".json"), encoding="utf-8")))
            hashes = [r["animations"]["hash"] for r in back]
            if BAKED and len(set(hashes)) != len(hashes):
                sys.exit("%s: rows share a setup hash %s" % (f, hashes))
            got = {r["rig"]["DepotPath"]["$value"]: r["animations"]["cinematics"][0]["animSet"]["DepotPath"]["$value"]
                   for r in back}
            for npc, player in PLAYER.items():
                want = baked_of(got.get(npc) or "") if BAKED else got.get(npc)
                if got.get(player) != want:
                    sys.exit("%s: %s reads %s, not %s" % (f, player, got.get(player), want))

    if BAKED:
        # The same halves at a path nothing else ships, so a run need not trust that our shadow wins the load order.
        own = os.path.join(depot, "ncn", "workspots", "v")
        os.makedirs(own, exist_ok=True)
        for root, _, files in os.walk(os.path.join(depot, "pinkydude")):
            for f in files:
                if f.endswith(".workspot"):
                    shutil.copy(os.path.join(root, f), os.path.join(own, f))
                    print("own path: ncn\\workspots\\v\\%s" % f)

    run("pack", depot, "-o", build, "-v", "Quiet")
    archive = os.path.join(build, NAME + ".archive")
    if not os.path.isfile(archive):
        sys.exit("pack wrote no %s" % archive)
    final = os.path.join(build, SHIPPED + ".archive")
    os.replace(archive, final)
    print("packed: %s" % final)


if __name__ == "__main__":
    main()
