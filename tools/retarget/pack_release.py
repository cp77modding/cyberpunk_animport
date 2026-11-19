"""The animation packs' release zip, from the packs as built (never a rebake): each pack's archive/ and bin/ at the game
root, its licence and credits under licenses/<pack>/. Uploaded as the CyberpunkAnimations release's one asset.

  python tools/retarget/pack_release.py 0.2.1          -> dist/opensex-0.2.1.zip
  CA=<CyberpunkAnimations>                             the packs' repo, default beside this one
"""
import os
import sys
import zipfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CA = os.environ.get("CA", os.path.join(os.path.dirname(REPO), "CyberpunkAnimations"))
PACKS = ["opensex", "ostimng"]


def build(version):
    out = os.path.join(REPO, "dist", "opensex-%s.zip" % version)
    if os.path.exists(out):
        sys.exit("%s exists: a released zip is never rebuilt under its version" % out)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    n = 0
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for p in PACKS:
            root = os.path.join(CA, p)
            for top in ("archive", "bin"):
                for d, _, fs in os.walk(os.path.join(root, top)):
                    for f in fs:
                        src = os.path.join(d, f)
                        z.write(src, os.path.relpath(src, root).replace("\\", "/"))
                        n += 1
            own = os.path.join(root, "LICENSE")    # a pack without its own licence is the repo's CC BY-SA
            z.write(own if os.path.exists(own) else os.path.join(CA, "LICENSE"), "licenses/%s/LICENSE" % p)
            z.write(os.path.join(root, "CREDITS.md"), "licenses/%s/CREDITS.md" % p)
            n += 2
    print(out, n, "files", os.path.getsize(out) // 2**20, "MB")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    build(sys.argv[1])
