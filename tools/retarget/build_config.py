"""build.json at the repo root: the tools, and per source its input, its own run folder and its pack.

build.json holds what is the same on every machine; build.local.json beside it (gitignored, written by
tools/port.py setup and run) holds this machine's tool paths, source inputs and added sources, merged over it.

  load()            the file, every path absolute; refuses two sources sharing a run folder or a pack, or one inside another
  source(name)      one source's row, with "pack" as the pack's folder
  python build_config.py           prints each source's paths: what a run reads and writes
  python build_config.py --get tools.game   one value, "" when unset
"""
import json
import ntpath
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
FILE = os.environ.get("ANIMPORT_BUILD", os.path.join(ROOT, "build.json"))
TOOLS = ("hkxc", "blender_hkx", "skeletons", "wolvenkit", "wolvenkit_cook", "game", "skyrim_mods", "cyberpunk_mods",
         "blender", "kraken")


def _abs(p, base):
    # ntpath too: on a pod, this machine's C:/ paths are absolute and pod_run remaps them, not joined under base
    return os.path.normpath(p if os.path.isabs(p) or ntpath.isabs(p) else os.path.join(base, p))


def _inside(a, b):
    a, b = os.path.normcase(a), os.path.normcase(b)
    return a == b or a.startswith(b.rstrip("\\/") + os.sep)


def local_file(path=None):
    """this machine's half, beside build.json: tool paths, source inputs, sources added here; gitignored"""
    return os.path.join(os.path.dirname(os.path.abspath(path or FILE)), "build.local.json")


def merge(base, over):
    out = dict(base)
    for k, v in over.items():
        out[k] = merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def load(path=None):
    path = path or FILE
    cfg = json.load(open(path, encoding="utf-8"))
    if os.path.isfile(local_file(path)):
        cfg = merge(cfg, json.load(open(local_file(path), encoding="utf-8")))
    base = os.path.dirname(os.path.abspath(path))
    cfg["file"] = path
    cfg["tools"] = {k: _abs(v, base) if v else None for k, v in cfg.get("tools", {}).items()}
    for k in TOOLS:
        cfg["tools"].setdefault(k, None)
    cfg["work"] = _abs(cfg["work"], base)
    cfg["mod"] = _abs(cfg.get("mod", "../nightcitynet"), base)
    cfg["packs"] = _abs(cfg["packs"], base)
    seen = []
    for name, s in cfg["sources"].items():
        s["input"] = _abs(s["input"], base) if s.get("input") else None
        s["run"] = _abs(s["run"], base)
        s["pack"] = os.path.join(cfg["packs"], s["pack"])
        for what in ("run", "pack"):
            for other, kind, p in seen:
                if _inside(s[what], p) or _inside(p, s[what]):
                    raise ValueError("build.json: %s's %s %s overlaps %s's %s %s" % (name, what, s[what], other, kind, p))
            seen.append((name, what, s[what]))
    return cfg


def source(name, cfg=None):
    cfg = cfg or load()
    if name not in cfg["sources"]:
        raise KeyError("build.json has no source %r (it has %s)" % (name, ", ".join(cfg["sources"])))
    return cfg["sources"][name]


def pod_map(cfg=None):
    """[(this machine's path, lower case and forward slashes, where a pod bundle keeps it)]: pod_run.py remaps by it"""
    cfg = cfg or load()
    t, s = cfg["tools"], cfg["sources"]
    wk = os.path.dirname(t["wolvenkit"]) if t["wolvenkit"] else None
    rows = [(t["skyrim_mods"], "ext/mods"), (s.get("opensex", {}).get("input"), "ext/OpenSex"),
            (s.get("ostimng", {}).get("input"), "ext/OStimNG"),
            (wk, "ext/Modding/" + os.path.basename(wk or "")), (ROOT, "cyberpunk_animport")]
    return [(p.replace("\\", "/").lower(), b) for p, b in rows if p]


def motionbricks_or_exit(cfg=None):
    """A MotionBricks entry point stops here while build.json has it off."""
    cfg = cfg or load()
    if not cfg.get("motionbricks"):
        sys.exit("MotionBricks is off in %s (\"motionbricks\": false)" % cfg["file"])


if __name__ == "__main__":
    if sys.argv[1:] == ["--motionbricks"]:   # a MotionBricks launcher's first line: exits 1 while it is off
        motionbricks_or_exit()
        sys.exit(0)
    c = load()
    if sys.argv[1:2] == ["--get"]:   # a .ps1's default: python build_config.py --get tools.game
        v = c
        for k in sys.argv[2].split("."):
            v = v.get(k) if isinstance(v, dict) else None
        print(v or "")
        sys.exit(0)
    print("build: %s  motionbricks: %s" % (FILE, c["motionbricks"]))
    for n, s in c["sources"].items():
        print("%-8s input %s\n         run   %s\n         pack  %s" % (n, s["input"], s["run"], s["pack"]))
