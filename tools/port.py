"""Port an animation pack, one command: check the machine, unpack, find the format, register it, run every stage.

  python tools/port.py check                       what this machine has and lacks, and where to get it
  python tools/port.py setup                       finds what it can (the game, tools on PATH or under third_party/)
                                                   and writes it to build.local.json; the Cyberpunk skeletons ship
                                                   in skeletons/cyberpunk/
  python tools/port.py run --input <folder|.zip|.7z> --pack <name> [--format opensex|ostimng|sexlab]
                                                   a new source in build.local.json, its reader, then every stage
                                                   (tools/retarget/skyrim_port.py all); run again to resume
      [--version 0.1.0] [--name "Shown name"] [--link URL]
                                                   then, for a pack that is not the mod's own: its scene files and
                                                   workspots as a NightCityNet integration, its AMM list and
                                                   dist/<pack>-<version>.zip, ready to install

Every path a run reads is build.json's, merged with build.local.json (tools/retarget/build_config.py). A source's
run folder is work/runs/<pack>, its pack <packs>/<pack>.
"""
import argparse
import glob
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
RT = os.path.join(HERE, "retarget")
sys.path.insert(0, RT)
import build_config  # noqa: E402

THIRD = os.path.join(ROOT, "third_party")
SKELETONS = ("skeleton.hkx", "femskeleton.hkx", "skeleton242.hkx")
# what, why, where to get it; a None `why` is needed by every run
TOOLS = {
    "game": ("Cyberpunk 2077's folder", None, "your Steam / GOG / Epic install"),
    "wolvenkit": ("WolvenKit.CLI.exe", None, "WolvenKit's console release, github.com/WolvenKit/WolvenKit/releases"),
    "wolvenkit_cook": ("WolvenKit's console folder, 8.20.0 or later (the SIMD animation cook)", None,
                       "WolvenKit.Console-<version>.zip, github.com/WolvenKit/WolvenKit/releases, unpacked; "
                       "needs the .NET 10 runtime"),
    "hkxc": ("hkxc.exe, Havok packfile converter", None, "nexusmods.com/skyrimspecialedition/mods/166424, unpacked to third_party/hkxc/"),
    "blender_hkx": ("blender-hkx.exe, the Havok clip decoder", None, "nexusmods.com/skyrimspecialedition/mods/118525 (Files tab), unpacked to third_party/blender-hkx/"),
    "skeletons": ("Skyrim's skeletons: skeleton.hkx, femskeleton.hkx, skeleton242.hkx", None,
                  "they ship with this repo in skeletons/skyrim/"),
    "skyrim_mods": ("a mods folder holding CBBE, HIMBO and Baka Haeun UNP", "the contact solve's Skyrim bodies",
                    "your Skyrim mod manager's mods folder"),
}
# the Cyberpunk skeletons clips are fitted onto, shipped in skeletons/cyberpunk/ (tools/retarget/make_skeletons.py)
SKEL = os.path.join(ROOT, "skeletons", "cyberpunk")
SKEL_FILES = ["animset.anims.json"] + ["%s%s" % (r, ext) for r in (
    "man_base", "woman_base", "man_big", "man_fat", "woman_big", "woman_fat", "player_man_skeleton",
    "player_woman_skeleton") for ext in (".rig", ".rig.json", ".glb")]
# the mod's own packs, released by tools/opensex/make_release.ps1; any other pack ships as an integration
BUILTIN = ("opensex", "ostimng")
SCENES_REL = os.path.join("bin", "x64", "plugins", "cyber_engine_tweaks", "mods", "nightcitynet", "data", "scenes")
PACKAGES = {"numpy": None, "scipy": "the contact solve", "cupy": "the contact solve on an NVIDIA card (else slow)"}


def tool_ok(name, path):
    if not path:
        return False
    if name == "game":
        return os.path.isdir(os.path.join(path, "archive", "pc", "content"))
    if name == "skeletons":
        return all(os.path.isfile(os.path.join(path, f)) for f in SKELETONS)
    if name == "wolvenkit_cook":
        return os.path.isfile(os.path.join(path, "WolvenKit.CLI.dll"))
    if name == "skyrim_mods":
        return os.path.isdir(os.path.join(path, "Caliente's Beautiful Bodies Enhancer -CBBE-"))
    return os.path.isfile(path)


def check(cfg=None, out=print):
    """[(what, ok, why, where)]; True when every row a run needs is there"""
    cfg = cfg or build_config.load()
    rows = []
    for k, (what, why, where) in TOOLS.items():
        rows.append((k + ": " + what, tool_ok(k, cfg["tools"].get(k)), why, where, cfg["tools"].get(k)))
    lost = [f for f in SKEL_FILES if not os.path.isfile(os.path.join(SKEL, f))]
    rows.append(("skeletons/cyberpunk: the Cyberpunk skeletons", not lost, None,
                 "they ship with this repo; missing: %s" % ", ".join(lost[:4]), None))
    for p, why in PACKAGES.items():
        rows.append(("python package " + p, importlib.util.find_spec(p) is not None, why, "pip install " + p, None))
    ok = True
    for what, good, why, where, path in rows:
        need = why is None
        ok &= good or not need
        mark = "ok  " if good else ("MISS" if need else "opt ")
        out("%s %s%s" % (mark, what, "" if good else "\n       for: %s\n       get: %s%s" % (
            why or "every run", where, "\n       set: %s" % path if path else "")))
    return ok


def steam_games():
    """Cyberpunk 2077 under any Steam library this machine has"""
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam") as k:
            steam = winreg.QueryValueEx(k, "SteamPath")[0]
    except OSError:
        return []
    vdf = os.path.join(steam, "steamapps", "libraryfolders.vdf")
    libs = [steam]
    if os.path.isfile(vdf):
        import re
        libs += [p.replace("\\\\", "\\") for p in re.findall(r'"path"\s+"([^"]+)"', open(vdf, encoding="utf-8").read())]
    return [os.path.join(lib, "steamapps", "common", "Cyberpunk 2077") for lib in libs]


def gog_games():
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\GOG.com\Games\1423049311") as k:
            return [winreg.QueryValueEx(k, "path")[0]]
    except OSError:
        return []


def find(name):
    """candidate paths for a tool on this machine"""
    if name == "game":
        return steam_games() + gog_games() + [r"C:\Program Files\Epic Games\Cyberpunk 2077",
                                              r"C:\GOG Games\Cyberpunk 2077"]
    exe = {"wolvenkit": "WolvenKit.CLI.exe", "hkxc": "hkxc.exe", "blender_hkx": "blender-hkx.exe"}.get(name)
    if exe:
        return [p for p in [shutil.which(exe)] if p] + glob.glob(os.path.join(THIRD, "**", exe), recursive=True)
    if name == "skeletons":
        return [os.path.dirname(p) for p in glob.glob(os.path.join(THIRD, "**", "skeleton242.hkx"), recursive=True)]
    return []


def write_local(update):
    path = build_config.local_file()
    cur = json.load(open(path, encoding="utf-8")) if os.path.isfile(path) else {}
    cur = build_config.merge(cur, update)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(cur, fh, indent=1, ensure_ascii=False)
        fh.write("\n")
    build_config.load()   # refuses an overlap before anything runs


def setup():
    cfg = build_config.load()
    found = {}
    for k in TOOLS:
        if tool_ok(k, cfg["tools"].get(k)):
            continue
        hit = next((p for p in find(k) if tool_ok(k, p)), None)
        if hit:
            found[k] = hit
            print("found %s: %s" % (k, hit))
    if found:
        write_local({"tools": found})
    return check()


def seven_zip():
    return shutil.which("7z") or next((p for p in (r"C:\Program Files\7-Zip\7z.exe",
                                                  r"C:\Program Files (x86)\7-Zip\7z.exe") if os.path.isfile(p)), None)


def unpack(src, dst):
    """a folder as is; an archive into dst once (an unpacked dst is reused)"""
    if os.path.isdir(src):
        return src
    if os.path.isdir(dst) and os.listdir(dst):
        print("already unpacked: %s" % dst)
        return dst
    os.makedirs(dst, exist_ok=True)
    if src.lower().endswith(".zip"):
        zipfile.ZipFile(src).extractall(dst)
    else:
        z = seven_zip()
        if not z:
            sys.exit("%s needs 7-Zip (7-zip.org) to unpack" % src)
        subprocess.run([z, "x", "-y", "-o" + dst, src], check=True, stdout=subprocess.DEVNULL)
    return dst


def detect(root):
    """the format a folder is in, by its readers' marks: [name]"""
    marks = {
        "opensex": [os.path.join("**", "0SA", "mod", "0Sex", "scene")],
        "ostimng": [os.path.join("**", "SKSE", "Plugins", "OStim", "scenes")],
        "sexlab": [os.path.join("**", "*.slsb.json"), os.path.join("**", "SLAnims", "json", "*.json")],
    }
    return [n for n, pats in marks.items()
            if any(glob.glob(os.path.join(root, p), recursive=True) for p in pats)]


def run(a):
    cfg = build_config.load()
    if not check(cfg, out=lambda s: None):
        check(cfg)
        sys.exit("this machine lacks what a run needs (above); python tools/port.py setup finds what it can")
    pack = a.pack.lower()
    if not pack.replace("_", "").isalnum():
        sys.exit("--pack is a folder name: letters, digits, _")
    src = os.path.abspath(a.input)
    inp = unpack(src, os.path.join(cfg["work"], "inputs", pack))
    fmt = a.format or (detect(inp) or [None])[0]
    if fmt is None:
        sys.exit("%s: no reader knows this format (tools/retarget/scene_list.py readers)" % inp)
    if fmt == "opensex" and pack != "opensex":
        sys.exit("OpenSex's reader writes only the opensex source's run")
    run_dir = os.path.join(cfg["work"], "runs", pack)
    if pack not in cfg["sources"]:
        write_local({"sources": {pack: {"input": inp, "run": run_dir, "pack": pack, "inventory": fmt,
                                        "ship_glb": False}}})
        print("source %s added to %s" % (pack, build_config.local_file()))
    s = build_config.source(pack)
    py = sys.executable
    if not os.path.isfile(os.path.join(s["run"], "manifest.json")):
        print("== reading %s as %s" % (inp, fmt), flush=True)
        cmd = {"ostimng": [py, os.path.join(RT, "skyrim_scenes_ostimng.py"), s["run"], "--ostimng", s["input"],
                           "--pack", pack],
               "sexlab": [py, os.path.join(RT, "skyrim_scenes_slal.py"), s["run"], "--input", s["input"],
                          "--pack", pack],
               "opensex": [py, os.path.join(RT, "skyrim_port.py"), "inventory"]}[fmt]
        subprocess.run(cmd, check=True)
    if pack in BUILTIN:
        subprocess.run([py, os.path.join(RT, "skyrim_port.py"), "all", "--source", pack], check=True)
        return
    subprocess.run([py, os.path.join(RT, "skyrim_port.py"), "clips", "--source", pack], check=True)
    pair_fit(pack, cfg)
    subprocess.run([py, os.path.join(RT, "skyrim_port.py"), "all", "--source", pack], check=True)
    release(pack, a)


def pair_fit(pack, cfg):
    """pairs kept touching as Skyrim has them (README step 3); skipped, and said, without Skyrim's bodies"""
    if not tool_ok("skyrim_mods", cfg["tools"].get("skyrim_mods")) or importlib.util.find_spec("scipy") is None:
        print("== pair fit skipped: needs scipy and skyrim_mods (CBBE, HIMBO) in build.local.json; "
              "pairs keep the plain fit", flush=True)
        return
    py = sys.executable
    print("== pair fit: oral reach", flush=True)
    subprocess.run([py, os.path.join(RT, "pair_reach.py"), "--pack", pack], check=True, cwd=RT)
    print("== pair fit: 2-5 actors, hands, lips and groin (a clip that fails keeps the plain fit)", flush=True)
    env = dict(os.environ, MESH="1", SAVE="1", HANDFIT="1", MESH_SKIN="1", ACTORS="2,3,4,5")
    if subprocess.run([py, os.path.join(RT, "pair_batch.py"), pack, "4"], env=env, cwd=RT).returncode:
        print("== pair fit: some clips failed, their logs are under work/contact/batch/%s" % pack, flush=True)


def release(pack, a):
    py, ops = sys.executable, os.path.join(HERE, "opensex")
    folder = os.path.join(build_config.load()["packs"], pack, SCENES_REL, "integrations", pack)
    if os.path.isdir(folder) and os.listdir(folder):
        print("== %s kept: its scene files are hand-edited from here on (make_integration.py --force)" % folder)
    else:
        print("== scene files and workspots", flush=True)
        subprocess.run([py, os.path.join(ops, "make_integration.py"), "--pack", pack, "--name", a.name or pack,
                        "--link", a.link], check=True)
    print("== AMM poses", flush=True)
    subprocess.run([py, os.path.join(ops, "make_amm_poses.py"), "--packs", pack], check=True)
    zip_ = os.path.join(ROOT, "dist", "%s-%s.zip" % (pack, a.version))
    if os.path.isfile(zip_):
        print("== %s exists; --version for a new one" % zip_)
        return
    print("== release zip", flush=True)
    subprocess.run([py, os.path.join(RT, "pack_release.py"), a.version, "--packs", pack], check=True)
    print("done: %s -- install it like any mod; NightCityNet lists it under integrations" % zip_)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("check")
    sub.add_parser("setup")
    r = sub.add_parser("run")
    r.add_argument("--input", required=True)
    r.add_argument("--pack", required=True)
    r.add_argument("--format", choices=("opensex", "ostimng", "sexlab"))
    r.add_argument("--version", default="0.1.0", help="the release zip's version")
    r.add_argument("--name", default="", help="the pack's name in NightCityNet's panel")
    r.add_argument("--link", default="", help="where players get the source pack")
    a = ap.parse_args()
    if a.cmd == "check":
        sys.exit(0 if check() else 1)
    if a.cmd == "setup":
        sys.exit(0 if setup() else 1)
    run(a)


if __name__ == "__main__":
    main()
