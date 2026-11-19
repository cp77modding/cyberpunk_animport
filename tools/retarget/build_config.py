"""build.json at the repo root: the tools, and per source its input, its own run folder and its pack.

  load()            the file, every path absolute; refuses two sources sharing a run folder or a pack, or one inside another
  source(name)      one source's row, with "pack" as the pack's folder
  python build_config.py           prints each source's paths: what a run reads and writes
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
FILE = os.environ.get("ANIMPORT_BUILD", os.path.join(ROOT, "build.json"))


def _abs(p, base):
    return os.path.normpath(p if os.path.isabs(p) else os.path.join(base, p))


def _inside(a, b):
    a, b = os.path.normcase(a), os.path.normcase(b)
    return a == b or a.startswith(b.rstrip("\\/") + os.sep)


def load(path=None):
    path = path or FILE
    cfg = json.load(open(path, encoding="utf-8"))
    base = os.path.dirname(os.path.abspath(path))
    cfg["file"] = path
    cfg["tools"] = {k: _abs(v, base) for k, v in cfg["tools"].items()}
    cfg["work"] = _abs(cfg["work"], base)
    cfg["mod"] = _abs(cfg.get("mod", "../nightcitynet"), base)
    cfg["packs"] = _abs(cfg["packs"], base)
    seen = []
    for name, s in cfg["sources"].items():
        s["input"] = _abs(s["input"], base)
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
    print("build: %s  motionbricks: %s" % (FILE, c["motionbricks"]))
    for n, s in c["sources"].items():
        print("%-8s input %s\n         run   %s\n         pack  %s" % (n, s["input"], s["run"], s["pack"]))
