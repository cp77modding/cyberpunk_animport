"""Where a climax lands in its clip, into our scene files (docs/design/climax-and-stimulation.md §4.2).

`"climax_at"`: the seconds into a scene's first clip of OStim's `OStimClimax` annotation. Two of the 2,432 source clips
carry one; a scene whose clips do not gets no field, and the game lands its climax at the clip's end.

Run: python tools/opensex/climax_events.py [--anims DIR] [--opensex DIR] [--ostimng DIR] [--hkxc EXE] [--dry]
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
from undress_events import HKXC, hkx_index  # noqa: E402

ANNO = re.compile(r'<hkparam name="time">([^<]+)</hkparam>\s*<hkparam name="text">OStimClimax')


def climax_at(xml):
    """-> the annotation's time in an hkx's XML, None when it has none."""
    m = ANNO.search(xml)
    return round(float(m.group(1)), 3) if m else None


def read_xml(hkxc, path, tmp):
    with open(path, "rb") as fh:
        head = fh.read(5)
        if head == b"<?xml":
            fh.seek(0)
            return fh.read().decode("utf-8", "replace")
    out = os.path.join(tmp, os.path.basename(path) + ".xml")
    r = subprocess.run([hkxc, "convert", "-i", path, "-o", out, "-v", "xml"], capture_output=True, text=True)
    if r.returncode != 0 or not os.path.exists(out):
        raise RuntimeError("hkxc could not read %s: %s" % (path, (r.stderr or r.stdout).strip()))
    with open(out, encoding="utf-8") as fh:
        return fh.read()


def carrying(paths):
    """-> {clip key: path} for the .hkx that name the annotation at all: a byte scan, so only those are converted."""
    out = {}
    for key, path in paths.items():
        with open(path, "rb") as fh:
            if b"OStimClimax" in fh.read():
                out[key] = path
    return out


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
    hits = carrying(idx)
    written = 0
    with tempfile.TemporaryDirectory() as tmp:
        times = {k: climax_at(read_xml(a.hkxc, p, tmp)) for k, p in hits.items()}
    print("%d of %d clips carry OStimClimax: %s" % (len(hits), len(idx), times))
    for pack in ("opensex", "ostimng"):
        root = os.path.join(a.anims, pack, scene_files.SCENES_REL, pack)
        for path in sorted(glob.glob(os.path.join(root, "**", "*.json"), recursive=True)):
            if os.path.basename(path) == "clips.json":
                continue
            with open(path, encoding="utf-8") as fh:
                s = json.load(fh)
            clips = s["speeds"][0]["clips"] if s.get("speeds") else []
            at = next((times[c] for c in (x.split("/", 1)[-1].lower() for x in clips if x)
                       if times.get(c) is not None), None)
            if at == s.get("climax_at"):
                continue
            print("  %s: climax_at %s" % (s["id"], at))
            if a.dry:
                continue
            if at is None:
                s.pop("climax_at", None)
            else:
                s["climax_at"] = at
            with open(path, "w", encoding="utf-8", newline="\n") as fh:
                json.dump(s, fh, indent=1, ensure_ascii=False)
                fh.write("\n")
            written += 1
    print("%d scene file(s) written" % written)


if __name__ == "__main__":
    main()
