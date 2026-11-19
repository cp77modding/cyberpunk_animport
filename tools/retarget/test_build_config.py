"""build_config on made-up build files: paths made absolute, overlaps refused, MotionBricks off by the flag."""
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import build_config as bc  # noqa: E402

fails = 0


def check(ok, what):
    global fails
    if not ok:
        fails += 1
        print("FAIL:", what)


def write(d, sources, mb=False):
    p = os.path.join(d, "build.json")
    json.dump({"tools": {"hkxc": "t/hkxc.exe"}, "work": "w", "packs": "../packs", "motionbricks": mb, "sources": sources},
              open(p, "w", encoding="utf-8"))
    return p


with tempfile.TemporaryDirectory() as d:
    ok = {"a": {"input": "in/a", "run": "w/a", "pack": "a"}, "b": {"input": "in/b", "run": "w/b", "pack": "b"}}
    c = bc.load(write(d, ok))
    check(c["sources"]["a"]["run"] == os.path.normpath(os.path.join(d, "w", "a")), "a run folder from the file's folder")
    check(c["sources"]["b"]["pack"] == os.path.normpath(os.path.join(d, "..", "packs", "b")), "a pack under packs")
    check(c["tools"]["hkxc"] == os.path.normpath(os.path.join(d, "t", "hkxc.exe")), "a tool path made absolute")
    for bad, why in ((dict(ok, b=dict(ok["b"], run="w/a")), "two sources, one run folder"),
                     (dict(ok, b=dict(ok["b"], run="w/a/sub")), "a run folder inside another"),
                     (dict(ok, b=dict(ok["b"], pack="a")), "two sources, one pack")):
        try:
            bc.load(write(d, bad))
            check(False, "refused: " + why)
        except ValueError:
            pass
    bc.load(write(d, ok, mb=False))
    try:
        bc.motionbricks_or_exit()
        check(False, "MotionBricks off stops its entry")
    except SystemExit:
        pass
    bc.motionbricks_or_exit(bc.load(write(d, ok, mb=True)))

check(bc.load(os.path.join(bc.ROOT, "build.json"))["motionbricks"] is False, "the shipped build.json has MotionBricks off")
print("%d failures" % fails)
sys.exit(1 if fails else 0)
