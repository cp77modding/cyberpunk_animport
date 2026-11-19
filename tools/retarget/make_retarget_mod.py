"""Patch V's skeletons to declare man_base/woman_base as a retarget source, and pack it as a mod.

The engine already retargets between rigs: `woman_base.rig` carries one `animRigRetarget` whose
only payload is `sourceRig -> man_base.rig`. No bone map, no baked data -- the mapping is derived
from bone names, and man_base's 71 bones are a name-exact, parent-exact subset of the player
skeleton's 152 (see compare_rigs.py). So the same one-field entry is all V's skeleton is missing.

If the engine honours it for workspot animsets, a man_base clip plays on V's own body and the
AnimDouble stand-in is unnecessary. That is the thing this mod exists to test -- it is a probe,
not a shipped feature.

Run: python tools/retarget/make_retarget_mod.py   (after extract.ps1)
"""
import json
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
WORK = os.path.join(HERE, "work")
JSON = os.path.join(WORK, "json")
BUILD = os.path.join(WORK, "mod")
WKIT = r"C:\Modding\wolwenKit_upacker\WolvenKit.CLI.exe"
DEPOT = r"base\characters\entities\player"

# Which source rig each player skeleton learns to accept. The female player skeleton takes
# woman_base, which itself retargets from man_base -- one hop, the same chain an NPC woman uses.
TARGETS = {
    "player_man_skeleton.rig": r"base\characters\base_entities\man_base\man_base.rig",
    "player_woman_skeleton.rig": r"base\characters\base_entities\woman_base\woman_base.rig",
}


def retarget_entry(source_rig):
    return {
        "$type": "animRigRetarget",
        "sourceRig": {
            "DepotPath": {"$type": "ResourcePath", "$storage": "string", "$value": source_rig},
            "Flags": "Default",
        },
    }


def run(*args):
    r = subprocess.run([WKIT] + list(args), capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit("WolvenKit failed: %s\n%s%s" % (" ".join(args), r.stdout, r.stderr))
    return r.stdout


def main():
    if not os.path.isdir(JSON):
        sys.exit("run tools/retarget/extract.ps1 first -- no %s" % JSON)
    shutil.rmtree(BUILD, ignore_errors=True)
    patched_json = os.path.join(BUILD, "json")
    source = os.path.join(BUILD, "source", DEPOT)
    os.makedirs(patched_json)
    os.makedirs(source)

    for rig, src in TARGETS.items():
        path = os.path.join(JSON, rig + ".json")
        doc = json.load(open(path, encoding="utf-8"))
        chunk = doc["Data"]["RootChunk"]
        if chunk.get("retargets"):
            print("%s already declares a retarget -- leaving it alone" % rig)
            continue
        chunk["retargets"] = [retarget_entry(src)]
        out = os.path.join(patched_json, rig + ".json")
        json.dump(doc, open(out, "w", encoding="utf-8"), indent=2)
        print("%-28s + retarget <- %s" % (rig, src))

    run("convert", "deserialize", patched_json, "-o", source, "-v", "Quiet")
    built = sorted(f for f in os.listdir(source) if f.endswith(".rig"))
    if len(built) != len(TARGETS):
        sys.exit("expected %d rigs, got %s" % (len(TARGETS), built))

    # Read the cooked rigs back: the path must be the one the engine hashes, byte for byte. The first
    # build wrote doubled separators here and the pack still succeeded.
    check = os.path.join(BUILD, "check")
    os.makedirs(check)
    for rig in built:
        shutil.copy(os.path.join(source, rig), check)
        run("convert", "serialize", os.path.join(check, rig), "-v", "Quiet")
        back = json.load(open(os.path.join(check, rig + ".json"), encoding="utf-8"))
        got = [r["sourceRig"]["DepotPath"]["$value"] for r in back["Data"]["RootChunk"]["retargets"]]
        if got != [TARGETS[rig]]:
            sys.exit("%s cooked with retargets %s, wanted %s" % (rig, got, TARGETS[rig]))
    shutil.rmtree(check)

    run("pack", os.path.join(BUILD, "source"), "-o", BUILD, "-v", "Quiet")
    archives = [f for f in os.listdir(BUILD) if f.endswith(".archive")]
    for a in archives:
        final = os.path.join(BUILD, "ncn_player_rig_retarget.archive")
        os.replace(os.path.join(BUILD, a), final)
        print("\npacked: %s" % final)
        print("install: copy into <game>\\archive\\pc\\mod\\ (or the MO2 mod folder), then load a save")
        print("test:    play a PoNC pose on V with animUseDouble OFF")


if __name__ == "__main__":
    main()
