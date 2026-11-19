"""What clothes each scene takes off, into our scene files (docs/design/scene-undress.md §3.1).

- `"undress": [{"actor", "at", "slots"}]`: each undress clip's `OStimUndressPartial.<slot mask>` annotation, read
  through serde-hkx's hkxc (hkx -> xml); the Skyrim slot mask becomes our clothing slots here, once.
- `"strip": [[slots of actor 0], ...]`: what must be off before the scene mounts, OStim's per-act strippingSlots in our
  slots (strip_of); every scene file gets one, [] for each actor a scene leaves dressed.

Run: python tools/opensex/undress_events.py [--anims DIR] [--opensex DIR] [--ostimng DIR] [--hkxc EXE] [--dry]
"""
import argparse
import glob
import json
import os
import re
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(__file__))
import port_list  # noqa: E402
import scene_files  # noqa: E402

HKXC = r"C:\Modding\serde\hkxc.exe"

# Skyrim armour slot (bit n = slot 30 + n) -> our clothing slots (body/LookRead ClothingSlots labels).
SLOT_TO_OURS = {
    30: ["head"], 31: ["head"], 42: ["head"], 43: ["eyes"], 44: ["eyes"],
    32: ["outer", "inner"], 46: ["outer"], 56: ["inner"],
    49: ["legs"], 52: ["legs"], 53: ["legs"],
    37: ["feet"],
}
SLOT_NONE = {33, 55}   # hands (no gloves slot here) and misc/FX: known, and nothing of ours
ORDER = ["head", "eyes", "outer", "inner", "legs", "feet"]

BODY = ["outer", "inner", "legs"]   # OStim's strippingSlots 32, 49, 52, 53, 54: the receiver of every act
FACE = ["head", "eyes"]             # 30, 31, 44, 55: an oral act's giver
# OpenSex's class code of a sex stage, at any head count: everyone in it undressed when it has no rated acts.
SEX_CLASSES = {"sx", "bj", "boj", "hj", "fj", "vj", "cr", "po"}
SEX_TAGS = {"doggystyle", "missionary", "cowgirl", "facesitting"}   # the same for a scene tagged with a sex position
SIDE = {"a": 0, "b": 1}   # an act's sides (scene_files.SIDES); anything else names nobody


def strip_of(s):
    """-> per actor, the slots that must be off before scene `s` mounts."""
    n = len(s.get("actors", []))
    out = [set() for _ in range(n)]
    acts = s.get("acts") or []
    if acts:
        for a in acts:
            giver, taker = SIDE.get(a.get("actor"), -1), SIDE.get(a.get("target"), -1)
            if 0 <= taker < n:
                out[taker].update(BODY)
            if 0 <= giver < n:
                out[giver].update(BODY if a.get("type") == "penetrative" else FACE if a.get("type", "").startswith("oral") else [])
        # only somebody touching themselves (a jerk to her face, her butt): it is done over everyone's bare body
        if all(a.get("actor") in SIDE and a.get("actor") == a.get("target") for a in acts):
            for st in out:
                st.update(BODY)
    else:
        parts = s["id"].split(".")
        coded = parts[0] == "opensex" and len(parts) > 4 and parts[3] in SEX_CLASSES
        if coded or SEX_TAGS & set(s.get("tags", [])):
            for st in out:
                st.update(BODY)
    for i, actor in enumerate(s.get("actors", [])):
        if "nostrip" in actor.get("mods", []):
            out[i].clear()
    return [[x for x in ORDER if x in st] for st in out]


ANNO = re.compile(r'<hkparam name="time">([^<]+)</hkparam>\s*<hkparam name="text">OStimUndressPartial\.(0x[0-9A-Fa-f]+)')


def ours_of(mask):
    """-> (our slots in ORDER, Skyrim slots with no counterpart)."""
    got, lost = set(), []
    for bit in range(32):
        if mask >> bit & 1:
            slot = 30 + bit
            if slot in SLOT_TO_OURS:
                got.update(SLOT_TO_OURS[slot])
            elif slot not in SLOT_NONE:
                lost.append(slot)
    return [s for s in ORDER if s in got], lost


def hkx_index(roots):
    """lower-case clip name without the leading _ -> path, over every .hkx under the roots."""
    idx = {}
    for root in roots:
        for p in glob.glob(os.path.join(root, "**", "*.hkx"), recursive=True):
            idx.setdefault(os.path.splitext(os.path.basename(p))[0].lstrip("_").lower(), p)
    return idx


def annotations(hkxc, path, tmp):
    with open(path, "rb") as fh:
        if fh.read(5) == b"<?xml":   # most OpenSex clips are XML tagfiles already
            fh.seek(0)
            return [(float(t), int(m, 16)) for t, m in ANNO.findall(fh.read().decode("utf-8", "replace"))]
    out = os.path.join(tmp, os.path.basename(path) + ".xml")
    r = subprocess.run([hkxc, "convert", "-i", path, "-o", out, "-v", "xml"], capture_output=True, text=True)
    if r.returncode != 0 or not os.path.exists(out):
        raise RuntimeError("hkxc could not read %s: %s" % (path, (r.stderr or r.stdout).strip()))
    with open(out, encoding="utf-8") as fh:
        return [(float(t), int(m, 16)) for t, m in ANNO.findall(fh.read())]


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--anims", default=scene_files.ANIMS)
    ap.add_argument("--opensex", default=port_list.OPENSEX)
    ap.add_argument("--ostimng", default=port_list.OSTIMNG)
    ap.add_argument("--hkxc", default=HKXC)
    ap.add_argument("--dry", action="store_true", help="print what would be written, write nothing")
    a = ap.parse_args()

    idx = hkx_index([os.path.join(a.opensex, "meshes"), os.path.join(a.ostimng, "data", "meshes")])
    if not idx:
        sys.exit("no .hkx found under %s or %s" % (a.opensex, a.ostimng))
    cache, written, stripped = {}, 0, 0
    with tempfile.TemporaryDirectory() as tmp:
        for pack in ("opensex", "ostimng"):
            root = os.path.join(a.anims, pack, scene_files.SCENES_REL, pack)
            for path in sorted(glob.glob(os.path.join(root, "**", "*.json"), recursive=True)):
                if os.path.basename(path) == "clips.json":
                    continue
                with open(path, encoding="utf-8") as fh:
                    s = json.load(fh)
                before = json.dumps(s, sort_keys=True)
                s["strip"] = strip_of(s)
                if any(s["strip"]):
                    stripped += 1
                rows = undress_rows(s, idx, cache, a.hkxc, tmp) if "undressing" in s.get("tags", []) and s.get("speeds") else []
                if rows:
                    s["undress"] = rows
                else:
                    s.pop("undress", None)   # a rerun that finds none drops an old row
                if json.dumps(s, sort_keys=True) == before or a.dry:
                    continue
                with open(path, "w", encoding="utf-8", newline="\n") as fh:
                    json.dump(s, fh, indent=1, ensure_ascii=False)
                    fh.write("\n")
                written += 1
    print("%d scene(s) strip somebody at the mount; %d scene file(s) written" % (stripped, written))


def undress_rows(s, idx, cache, hkxc, tmp):
    """-> the undress beats in scene `s`'s clips, [] when they carry none."""
    rows = []
    for actor, clip in enumerate(s["speeds"][0]["clips"]):
        name = (clip or "").split("/", 1)[-1].lower()
        hkx = idx.get(name)
        if hkx is None:
            print("  [miss] %s actor %d: no .hkx for clip %s" % (s["id"], actor, clip))
            continue
        if hkx not in cache:
            cache[hkx] = annotations(hkxc, hkx, tmp)
        for at, mask in cache[hkx]:
            slots, lost = ours_of(mask)
            if lost:
                print("  [note] %s actor %d: Skyrim slots %s have no counterpart" % (s["id"], actor, lost))
            if slots:
                rows.append({"actor": actor, "at": round(at, 3), "slots": slots})
    print("  %s: %s" % (s["id"], json.dumps(rows) if rows else "[none] no undress event in its clips"))
    return rows


if __name__ == "__main__":
    main()
