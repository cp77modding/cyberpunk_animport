"""skeletons/cyberpunk/: every Cyberpunk skeleton a port fits clips onto, shipped with the tool.

Per rig: <rig>.rig (the game's, packed for the cook), <rig>.rig.json (WolvenKit's serialization), <rig>.glb (its
armature, rig_glb.py: what clips are retargeted onto). And animset.anims.json: an animation set with no clips, the
container the cook copies per set and points at its rig (anims_json.prep).

Run once from serialized game rigs (extract.ps1, and the big and fat ones):
  python tools/retarget/make_skeletons.py <folder holding base\\characters\\...\\<rig>.rig and .rig.json> <an .anims.json>
"""
import json
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(os.path.dirname(os.path.dirname(HERE)), "skeletons", "cyberpunk")
# rig name -> its depot path
RIGS = {r: "base\\characters\\base_entities\\%s\\%s.rig" % (r, r)
        for r in ("man_base", "woman_base", "man_big", "man_fat", "man_massive", "woman_big", "woman_fat")}
RIGS.update({r: "base\\characters\\entities\\player\\%s.rig" % r
             for r in ("player_man_skeleton", "player_woman_skeleton")})


def main():
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    src, animset = sys.argv[1:3]
    os.makedirs(OUT, exist_ok=True)
    for rig, depot in RIGS.items():
        rig_file = os.path.join(src, *depot.split("\\"))
        for f in (rig_file, rig_file + ".json"):
            if not os.path.isfile(f):
                sys.exit("missing %s" % f)
        shutil.copyfile(rig_file, os.path.join(OUT, rig + ".rig"))
        shutil.copyfile(rig_file + ".json", os.path.join(OUT, rig + ".rig.json"))
        subprocess.run([sys.executable, os.path.join(HERE, "rig_glb.py"), rig_file + ".json",
                        os.path.join(OUT, rig + ".glb")], check=True)
    sys.path.insert(0, HERE)
    import anims_json
    out = os.path.join(OUT, "animset.anims.json")
    anims_json.prep(animset, RIGS["man_base"], out)
    doc = json.load(open(out, encoding="utf-8"))
    doc.get("Header", {}).pop("ArchiveFileName", None)   # where the source was read from
    with open(out, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(doc, fh, indent=2)
        fh.write("\n")
    print("%d rigs -> %s" % (len(RIGS), OUT))


if __name__ == "__main__":
    main()
