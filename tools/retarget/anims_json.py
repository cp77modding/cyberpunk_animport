"""Prepare the serialized .anims container the retargeted clips are cooked into.

prep   <source.anims.json> <target rig depot path> <out.anims.json>
       The source animset with its clips, chunks and fallback pose removed and its rig swapped --
       the wiki's "delete all array items" step, so the cooked set holds only the retargeted clips.
The wiki's numTracks = 0 step is not taken: V's clips carry the rig's 23 float tracks (README).

check  <cooked.anims.json>
       Fails when a clip's fallbackFrameIndices run past the set's fallback table: the engine's fallback
       blend reads that slot as a null pointer (docs/design/affection-actions.md).
"""
import json
import sys


def load(path):
    return json.load(open(path, encoding="utf-8"))


def save(doc, path):
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, indent=2)


def prep(src, rig, out):
    doc = load(src)
    root = doc["Data"]["RootChunk"]
    root["rig"]["DepotPath"]["$value"] = rig
    root["animations"] = []
    root["animationDataChunks"] = []
    root["fallbackAnimDataBuffer"] = None
    for key in ("fallbackAnimDescIndexes", "fallbackAnimFrameDescs", "fallbackDataAddresses",
                "fallbackDataAddressIndexes"):
        root[key] = []
    for key in ("fallbackNumFloatTrackData", "fallbackNumPositionData", "fallbackNumRotationData"):
        root[key] = 0
    save(doc, out)
    print("container: rig %s, cleared" % rig)


def dangling(root):
    """Clips whose fallback indices run past the set's fallback table."""
    n = len(root.get("fallbackAnimDescIndexes") or [])
    out = []
    for entry in root["animations"]:
        anim = entry["Data"]["animation"]["Data"]
        if any(i >= n for i in anim["animBuffer"]["Data"].get("fallbackFrameIndices") or []):
            out.append(anim["name"]["$value"])
    return out


def check(path):
    bad = dangling(load(path)["Data"]["RootChunk"])
    if bad:
        sys.exit("clips index a fallback frame the set lacks: " + ", ".join(bad))
    print("fallback: every clip's index is in the set's table")


def main():
    if len(sys.argv) == 5 and sys.argv[1] == "prep":
        prep(*sys.argv[2:])
    elif len(sys.argv) == 3 and sys.argv[1] == "check":
        check(sys.argv[2])
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
