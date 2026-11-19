"""PoNC's AMM workspot with finalAnimsets rows for the big and fat NPC rigs, pointing at our bakes.

PoNC ships rows for man_base and woman_base only, so a man_big body (Jackie, River) mounts and plays nothing.
Each new row is a copy of its base row with every animset swapped for the set retarget.ps1 -Rig baked
(work/depot/ncn/anims/npc/<set>_<rig>.anims). The workspot lands at its own path, ncn\\workspots\\npc\\, so
nothing depends on winning PoNC's load order; clip names are PoNC's.

Run: python tools/retarget/make_npc_rig_rows.py   (after retarget.ps1 -Rig has baked every set below)
"""
import copy
import json
import os
import shutil
import subprocess
import sys

from make_v_row_probe import WKIT, PONC, WORK, fnv1a64, rows

NAME = "ncn_npc_rigs"
SOURCE = r"pinkydude\pleasures_of_nightcity\anims_vol1\amm\ponc_anims.workspot"
OWN = r"ncn\workspots\npc\ponc_anims.workspot"
BASE = r"base\characters\base_entities\%s\%s.rig"
ADD = {"man_base": ("man_big", "man_fat"), "woman_base": ("woman_big", "woman_fat")}


def run(*args):
    r = subprocess.run([WKIT] + list(args), capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit("WolvenKit failed: %s\n%s%s" % (" ".join(args), r.stdout, r.stderr))


def baked(animset, rig):
    return "ncn\\anims\\npc\\%s_%s.anims" % (os.path.splitext(animset.split("\\")[-1])[0], rig)


def main():
    build = os.path.join(WORK, "npcrow")
    shutil.rmtree(build, ignore_errors=True)
    raw, depot = os.path.join(build, "raw"), os.path.join(build, NAME)
    os.makedirs(raw)
    run("unbundle", PONC, "-o", raw, "-w", "*" + os.path.basename(SOURCE), "-v", "Quiet")
    src = os.path.join(raw, SOURCE)
    if not os.path.isfile(src):
        sys.exit("PoNC has no %s" % SOURCE)
    run("convert", "serialize", src, "-v", "Quiet")
    doc = json.load(open(src + ".json", encoding="utf-8"))

    want = {}
    for row in list(rows(doc)):
        base = row["rig"]["DepotPath"]["$value"].split("\\")[-1][:-4]
        for rig in ADD.get(base, ()):
            twin = copy.deepcopy(row)
            twin["rig"]["DepotPath"]["$value"] = BASE % (rig, rig)
            sets = []
            for entry in twin["animations"]["cinematics"]:
                animset = baked(entry["animSet"]["DepotPath"]["$value"], rig)
                cooked = os.path.join(WORK, "depot", animset)
                if not os.path.isfile(cooked):
                    sys.exit("not baked: %s -- run retarget.ps1 -Rig %s for it" % (cooked, rig))
                entry["animSet"]["DepotPath"]["$value"] = animset
                os.makedirs(os.path.dirname(os.path.join(depot, animset)), exist_ok=True)
                shutil.copy(cooked, os.path.join(depot, animset))
                sets.append(animset)
            twin["loadingHandles"] = [{**copy.deepcopy(twin["loadingHandles"][0]),
                                       "DepotPath": {**twin["loadingHandles"][0]["DepotPath"], "$value": s}} for s in sets]
            # The engine caches a row's runtime setup by this hash; a copied one hands the rig the base row's setup.
            twin["animations"]["hash"] = str(fnv1a64(OWN + "|" + BASE % (rig, rig)))
            rows(doc).append(twin)
            want[BASE % (rig, rig)] = sets
    if len(want) != sum(len(v) for v in ADD.values()):
        sys.exit("rows added for %s only" % sorted(want))

    out = os.path.join(build, "json", os.path.dirname(OWN))
    os.makedirs(out, exist_ok=True)
    os.makedirs(os.path.join(depot, os.path.dirname(OWN)), exist_ok=True)
    path = os.path.join(out, os.path.basename(OWN) + ".json")
    json.dump(doc, open(path, "w", encoding="utf-8"), indent=2)
    run("convert", "deserialize", path, "-o", os.path.join(depot, os.path.dirname(OWN)), "-v", "Quiet")

    # Read the cooked workspot back: every rig its own sets and its own setup hash.
    check = os.path.join(build, "check")
    os.makedirs(check)
    shutil.copy(os.path.join(depot, OWN), check)
    run("convert", "serialize", os.path.join(check, os.path.basename(OWN)), "-v", "Quiet")
    back = rows(json.load(open(os.path.join(check, os.path.basename(OWN) + ".json"), encoding="utf-8")))
    hashes = [r["animations"]["hash"] for r in back]
    if len(set(hashes)) != len(hashes):
        sys.exit("rows share a setup hash %s" % hashes)
    got = {r["rig"]["DepotPath"]["$value"]: [c["animSet"]["DepotPath"]["$value"] for c in r["animations"]["cinematics"]]
           for r in back}
    for rig, sets in want.items():
        handles = [h["DepotPath"]["$value"] for r in back if r["rig"]["DepotPath"]["$value"] == rig for h in r["loadingHandles"]]
        if got.get(rig) != sets or handles != sets:
            sys.exit("%s reads %s / handles %s, not %s" % (rig, got.get(rig), handles, sets))
    for rig in sorted(got):
        print("%-50s %d sets" % (rig, len(got[rig])))

    run("pack", depot, "-o", build, "-v", "Quiet")
    archive = os.path.join(build, NAME + ".archive")
    if not os.path.isfile(archive):
        sys.exit("pack wrote no %s" % archive)
    print("packed: %s  (play %s)" % (archive, OWN))


if __name__ == "__main__":
    main()
