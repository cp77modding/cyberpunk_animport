"""Which Skyrim scene to port from which repo, into which pack: docs/generated/anim-port-list.{md,json}.

Rule (docs/design/opensex-port.md §8): a clip whose animation is in OpenSex is taken from OpenSex (CC BY-SA,
pack opensex/); OStimNG (GPLv3, pack ostimng/) supplies only clips with no OpenSex match. "Match" = byte-identical
file, or OpenSex's whole compressed spline block found inside the OStimNG file.

Run: python tools/opensex/port_list.py [--opensex DIR] [--ostimng DIR]   (re-run after pulling either repo)
"""
import argparse
import hashlib
import json
import os
import re
import struct
import sys
from collections import defaultdict

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUT_MD = os.path.join(REPO, "docs", "generated", "anim-port-list.md")
OUT_JSON = os.path.join(REPO, "docs", "generated", "anim-port-list.json")

sys.path.insert(0, os.path.join(REPO, "tools", "retarget"))
import build_config  # noqa: E402
_sources = build_config.load()["sources"]
OPENSEX = (_sources.get("opensex") or {}).get("input")
OSTIMNG = (_sources.get("ostimng") or {}).get("input")

# 97 = vanilla less two bones; unpack against vanilla skeleton.hkx decodes all 49 such OStimNG clips (2026-10-27).
SKELETON = {99: "vanilla", 97: "vanilla", 242: "XPMSE"}
# Skeletons on hand: vanilla skeleton.hkx and Reskeletor's skeleton242.hkx (XPMSE+3BA+SMP); both decode, 2026-10-27.
DECODES = {"vanilla", "XPMSE"}

DATA_RX = re.compile(rb'<array name="data" size="\d+">(.*?)</array>', re.S)
TRACKS_RX = re.compile(rb'<int name="numberOfTransformTracks">(\d+)</int>')
DURATION_RX = re.compile(rb'<real name="duration">x[0-9a-f]+ <!-- ([0-9.]+) -->')


def hkx_files(root):
    """{clip name: path}. A name in two folders keeps the first path and is reported, since scenes name clips only."""
    out = {}
    for r, _, fs in sorted(os.walk(root)):
        for f in sorted(fs):
            if f.lower().endswith(".hkx"):
                name = f[:-4].lower()
                if name in out:
                    print(f"same clip name in two folders, kept {out[name]}: {os.path.join(r, f)}", file=sys.stderr)
                    continue
                out[name] = os.path.join(r, f)
    return out


def binary_header(b):
    """(tracks, duration) of a packfile's spline animation: the hkaAnimation fields type, duration, tracks, floats.
    The spline type is stored as 3 in some OStimNG files and 5 in others (both read back as spline by hkxc)."""
    best = None
    for t in (3, 5):
        pat = struct.pack("<i", t)
        i = b.find(pat)
        while i != -1 and i + 16 <= len(b):
            dur, = struct.unpack_from("<f", b, i + 4)
            nt, nf = struct.unpack_from("<ii", b, i + 8)
            if 0.05 < dur < 1000 and 1 <= nt <= 400 and 0 <= nf <= 64:
                if best is None or i < best[0]:
                    best = (i, nt, round(dur, 3))
                break
            i = b.find(pat, i + 1)
    return (best[1], best[2]) if best else (None, None)


def clip_facts(path):
    b = open(path, "rb").read()
    if b.startswith(b"<?xml"):
        t, d, m = TRACKS_RX.search(b), DURATION_RX.search(b), DATA_RX.search(b)
        blob = bytes(int(x) for x in m.group(1).split()) if m else None
        return b, int(t.group(1)) if t else None, float(d.group(1)) if d else None, blob
    nt, dur = binary_header(b)
    return b, nt, dur, None


def opensex_scenes(root):
    scenes = []
    sdir = os.path.join(root, "meshes", "0SA", "mod", "0Sex", "scene")
    for r, _, fs in os.walk(sdir):
        for f in fs:
            if not f.endswith(".xml"):
                continue
            s = open(os.path.join(r, f), encoding="utf-8", errors="replace").read()
            sid = re.search(r'<scene id="([^"]+)"', s)
            n = re.search(r'actors="(\d+)"', s)
            info = re.search(r'<info name="([^"]*)"(?: animator="([^"]*)")?', s)
            anims = list(dict.fromkeys(re.findall(r'<anim id="([^"]+)"', s)))
            scenes.append({
                "id": sid.group(1) if sid else f[:-4],
                "file": os.path.relpath(os.path.join(r, f), sdir),
                "name": info.group(1) if info else "",
                "animator": (info.group(2) or "") if info else "",
                "actors": int(n.group(1)) if n else 0,
                "speeds": len(anims),
                "clips": [f"{a}_{i}".lower() for a in anims for i in range(int(n.group(1)) if n else 0)],
            })
    return scenes


def ostimng_scenes(root):
    scenes = []
    sdir = os.path.join(root, "data", "SKSE", "Plugins", "OStim", "scenes")
    for r, _, fs in os.walk(sdir):
        for f in fs:
            if not f.endswith(".json"):
                continue
            j = json.load(open(os.path.join(r, f), encoding="utf-8-sig"))
            n = len(j.get("actors", []))
            anims = list(dict.fromkeys(s.get("animation", "") for s in j.get("speeds", []) if s.get("animation")))
            scenes.append({
                "id": f[:-5],
                "file": os.path.relpath(os.path.join(r, f), sdir),
                "name": j.get("name", ""),
                "actors": n,
                "speeds": len(anims),
                "clips": [f"{a}_{i}".lower() for a in anims for i in range(n)],
            })
    return scenes


def build(opensex, ostimng):
    os_files = hkx_files(os.path.join(opensex, "meshes", "0SA", "mod", "0Sex", "anim"))
    ng_files = hkx_files(os.path.join(ostimng, "data", "meshes", "actors", "character", "animations", "OStim"))

    clips = {}
    os_hash, os_blobs = {}, []
    for name, p in os_files.items():
        b, nt, dur, blob = clip_facts(p)
        clips[("opensex", name)] = {"tracks": nt, "duration": dur}
        os_hash[hashlib.sha1(b).hexdigest()] = name
        if blob:
            os_blobs.append((name, blob))
    ng_match = {}
    for name, p in ng_files.items():
        b, nt, dur, _ = clip_facts(p)
        clips[("ostimng", name)] = {"tracks": nt, "duration": dur}
        same = os_hash.get(hashlib.sha1(b).hexdigest())
        if same is None:
            same = next((n for n, blob in os_blobs if blob in b), None)
        if same:
            ng_match[name] = same
    print(f"opensex {len(os_files)} clips, ostimng {len(ng_files)} clips, {len(ng_match)} from OpenSex, "
          f"{len(ng_files) - len(ng_match)} only in OStimNG", file=sys.stderr)

    def skeleton(src, names):
        kinds = {SKELETON.get(clips[(src, c)]["tracks"], f"{clips[(src, c)]['tracks']} tracks")
                 for c in names if (src, c) in clips}
        return "+".join(sorted(kinds)) or "?"

    in_ostimng = defaultdict(list)
    for ng, os_name in ng_match.items():
        in_ostimng[os_name].append(ng)

    rows = []
    for s in opensex_scenes(opensex):
        have = [c for c in s["clips"] if c in os_files]
        rows.append({**s, "source": "OpenSex", "pack": "opensex", "license": "CC BY-SA 4.0",
                     "missing": [c for c in s["clips"] if c not in os_files],
                     "skeleton": skeleton("opensex", have),
                     "decodes": all(SKELETON.get(clips[("opensex", c)]["tracks"]) in DECODES for c in have) and bool(have),
                     "alsoInOStimNG": sum(1 for c in have if c in in_ostimng)})

    used_extra = set()
    for s in ostimng_scenes(ostimng):
        extra = [c for c in s["clips"] if c in ng_files and c not in ng_match]
        if not extra:
            continue
        used_extra.update(extra)
        rows.append({**s, "source": "OStimNG", "pack": "ostimng", "license": "GPLv3", "animator": "",
                     "extra": extra,
                     "fromOpenSex": {c: ng_match[c] for c in s["clips"] if c in ng_match},
                     "missing": [c for c in s["clips"] if c not in ng_files],
                     "skeleton": skeleton("ostimng", extra),
                     "decodes": all(SKELETON.get(clips[("ostimng", c)]["tracks"]) in DECODES for c in extra)})

    orphans = sorted(c for c in ng_files if c not in ng_match and c not in used_extra)
    return rows, orphans, {"opensexClips": len(os_files), "ostimngClips": len(ng_files),
                           "ostimngFromOpenSex": len(ng_match), "ostimngOnly": len(ng_files) - len(ng_match)}, ng_match


def write(rows, orphans, totals, clip_map):
    os_rows = [r for r in rows if r["source"] == "OpenSex"]
    ng_rows = [r for r in rows if r["source"] == "OStimNG"]
    extra_n = totals["ostimngOnly"]
    lines = [
        "# Animation port list — which scene, from which repo, into which pack",
        "",
        "**Generated by `tools/opensex/port_list.py` — do not edit; re-run after pulling OpenSex or OStimNG.** "
        "The rule and the reasons: nightcitynet's `docs/design/opensex-port.md` §8.",
        "",
        "- A clip whose animation is in OpenSex comes from **OpenSex** (pack `opensex/`, CC BY-SA 4.0), even when "
        "OStimNG has it too.",
        "- **OStimNG** (pack `ostimng/`, GPLv3) supplies only clips with no OpenSex match. A scene mixing both takes "
        "each clip from its own source.",
        "- *Skeleton* = the authoring skeleton by track count: vanilla (99) or XPMSE (242). *Decodes* = every clip's "
        "skeleton is on hand. *Missing* = the scene names a clip no file in the repo is called.",
        "",
        f"OpenSex: {totals['opensexClips']} clips, {len(os_rows)} scenes. OStimNG: {totals['ostimngClips']} clips, "
        f"{totals['ostimngFromOpenSex']} of them OpenSex's; **{extra_n} only in OStimNG**, in {len(ng_rows)} scenes "
        f"plus {len(orphans)} in no scene.",
        "",
        f"## OpenSex — pack `opensex/` ({len(os_rows)} scenes)",
        "",
        "| scene | name | animator | actors | speeds | clips | skeleton | decodes | also in OStimNG |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for r in sorted(os_rows, key=lambda r: r["id"]):
        miss = f" ({len(r['missing'])} missing)" if r["missing"] else ""
        lines.append(f"| `{r['id']}` | {r['name']} | {r['animator']} | {r['actors']} | {r['speeds']} | "
                     f"{len(r['clips'])}{miss} | {r['skeleton']} | {'yes' if r['decodes'] else 'no'} | "
                     f"{r['alsoInOStimNG'] or ''} |")
    lines += ["", f"## OStimNG — pack `ostimng/` ({len(ng_rows)} scenes)", "",
              "| scene | actors | speeds | clips from OStimNG | clips from OpenSex | skeleton | decodes |",
              "|---|---|---|---|---|---|---|"]
    for r in sorted(ng_rows, key=lambda r: r["file"]):
        lines.append(f"| `{r['file'].replace(os.sep, '/')}` | {r['actors']} | {r['speeds']} | {len(r['extra'])} | "
                     f"{len(r['fromOpenSex']) or ''} | {r['skeleton']} | {'yes' if r['decodes'] else 'no'} |")
    lines += ["", f"## OStimNG clips in no scene ({len(orphans)})", ""]
    lines += [f"- `{c}`" for c in orphans] or ["none"]
    os.makedirs(os.path.dirname(OUT_MD), exist_ok=True)
    with open(OUT_MD, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines) + "\n")
    with open(OUT_JSON, "w", encoding="utf-8", newline="\n") as f:
        # clipMap: every OStimNG clip that is an OpenSex clip, for the scene files (tools/opensex/scene_files.py).
        json.dump({"totals": totals, "scenes": rows, "orphans": orphans, "clipMap": dict(sorted(clip_map.items()))},
                  f, indent=1)
        f.write("\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--opensex", default=OPENSEX)
    ap.add_argument("--ostimng", default=OSTIMNG)
    a = ap.parse_args()
    rows, orphans, totals, clip_map = build(a.opensex, a.ostimng)
    write(rows, orphans, totals, clip_map)
    print(f"wrote {os.path.relpath(OUT_MD, REPO)} and {os.path.relpath(OUT_JSON, REPO)}", file=sys.stderr)


if __name__ == "__main__":
    main()
