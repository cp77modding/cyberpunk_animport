"""A release zip from packs as built (never a rebake): each pack's archive/ and bin/ at the game root, its licence and
credits under licenses/<pack>/.

  python tools/retarget/pack_release.py 0.2.1                          -> dist/opensex-0.2.1.zip (opensex and ostimng)
  python tools/retarget/pack_release.py 0.1.0 --packs mypack           -> dist/mypack-0.1.0.zip
  [--name <zip name>] [--anims <the packs' folder, build.json's packs>]

opensex and ostimng without their own LICENSE take the packs folder's (ours); any other pack ships only its own, and
says so when it has none.
"""
import argparse
import os
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
import build_config  # noqa: E402

OURS = ("opensex", "ostimng")


def build(version, packs, name, anims):
    out = os.path.join(REPO, "dist", "%s-%s.zip" % (name, version))
    if os.path.exists(out):
        sys.exit("%s exists: a released zip is never rebuilt under its version" % out)
    for p in packs:
        if not os.path.isdir(os.path.join(anims, p, "archive")):
            sys.exit("%s has no archive/ under %s: nothing built to release" % (p, anims))
    os.makedirs(os.path.dirname(out), exist_ok=True)
    n = 0
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for p in packs:
            root = os.path.join(anims, p)
            for top in ("archive", "bin"):
                for d, _, fs in os.walk(os.path.join(root, top)):
                    for f in fs:
                        src = os.path.join(d, f)
                        z.write(src, os.path.relpath(src, root).replace("\\", "/"))
                        n += 1
            # the packs folder's licence is our packs' (CC BY-SA); a ported pack is someone else's work
            tries = [os.path.join(root, "LICENSE")] + ([os.path.join(anims, "LICENSE")] if p in OURS else [])
            lic = next((f for f in tries if os.path.isfile(f)), None)
            if lic:
                z.write(lic, "licenses/%s/LICENSE" % p)
                n += 1
            else:
                print("%s: no LICENSE, none shipped" % p)
            credits = os.path.join(root, "CREDITS.md")
            if os.path.isfile(credits):
                z.write(credits, "licenses/%s/CREDITS.md" % p)
                n += 1
            else:
                print("%s: no CREDITS.md, none shipped" % p)
    print(out, n, "files", os.path.getsize(out) // 2**20, "MB")
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("version")
    ap.add_argument("--packs", default="opensex,ostimng")
    ap.add_argument("--name", default="")
    ap.add_argument("--anims", default=build_config.load()["packs"])
    a = ap.parse_args()
    packs = [p for p in a.packs.split(",") if p]
    build(a.version, packs, a.name or ("opensex" if a.packs == "opensex,ostimng" else packs[0]), a.anims)


if __name__ == "__main__":
    main()
