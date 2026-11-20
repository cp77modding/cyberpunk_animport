"""port.py on a made-up machine: the local file merged over build.json, the check that names what is missing,
format detection, unpacking a zip once. No game, no tools.

Run: python tools/test_port.py (also from tools/py_test.ps1).
"""
import json
import os
import sys
import tempfile
import zipfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import port  # noqa: E402

fails = []


def check(cond, msg):
    print(("  ok   " if cond else "  FAIL ") + msg)
    if not cond:
        fails.append(msg)


def touch(p, text=""):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    open(p, "w", encoding="utf-8").write(text)


with tempfile.TemporaryDirectory() as tmp:
    build = os.path.join(tmp, "build.json")
    json.dump({"tools": {"wolvenkit_cook": "cook"}, "work": "work", "packs": "packs",
               "sources": {"a": {"run": "work/runs/a", "pack": "a", "inventory": "sexlab"}}}, open(build, "w"))
    cfg = port.build_config.load(build)
    check(cfg["tools"]["game"] is None and cfg["sources"]["a"]["input"] is None,
          "without a local file a machine path is None, not this machine's")
    json.dump({"tools": {"game": os.path.join(tmp, "game")}, "sources": {"a": {"input": "in"}}},
              open(os.path.join(tmp, "build.local.json"), "w"))
    cfg = port.build_config.load(build)
    check(cfg["tools"]["game"] == os.path.join(tmp, "game") and cfg["sources"]["a"]["run"].endswith(
        os.path.join("runs", "a")) and cfg["sources"]["a"]["input"] == os.path.join(tmp, "in"),
          "the local file fills the machine's paths and keeps build.json's")
    json.dump({"sources": {"b": {"input": "x", "run": "work/runs/a/b", "pack": "b"}}},
              open(os.path.join(tmp, "build.local.json"), "w"))
    try:
        port.build_config.load(build)
        check(False, "a local source inside another's run folder is refused")
    except ValueError:
        check(True, "a local source inside another's run folder is refused")
    os.remove(os.path.join(tmp, "build.local.json"))

    lines = []
    ok = port.check(port.build_config.load(build), out=lines.append)
    text = "\n".join(lines)
    check(not ok and "MISS game" in text and "get: your Steam" in text, "a missing game fails the check and says where")
    check("opt  skyrim_mods" in text, "the contact solve's bodies are optional")
    touch(os.path.join(tmp, "game", "archive", "pc", "content", "x.archive"))
    check(port.tool_ok("game", os.path.join(tmp, "game")), "a folder with archive/pc/content is the game")

    touch(os.path.join(tmp, "sl", "00 Data", "SLSB", "x.slsb.json"), "{}")
    touch(os.path.join(tmp, "ng", "data", "SKSE", "Plugins", "OStim", "scenes", "a.json"), "{}")
    check(port.detect(os.path.join(tmp, "sl")) == ["sexlab"], "an SLSB file is SexLab")
    check(port.detect(os.path.join(tmp, "ng")) == ["ostimng"], "OStim's scene folder is OStimNG")
    check(port.detect(os.path.join(tmp, "game")) == [], "a folder no reader knows is none")

    z = os.path.join(tmp, "p.zip")
    with zipfile.ZipFile(z, "w") as f:
        f.writestr("Data/SLAnims/json/a.json", "{}")
    dst = os.path.join(tmp, "unz")
    check(port.unpack(z, dst) == dst and port.detect(dst) == ["sexlab"], "a zip is unpacked and its format read")
    os.remove(z)
    check(port.unpack(z, dst) == dst, "an unpacked input is reused, not unpacked again")
    check(port.unpack(os.path.join(tmp, "sl"), dst) == os.path.join(tmp, "sl"), "a folder is read where it is")

print("\n%d failure(s)" % len(fails))
sys.exit(1 if fails else 0)
