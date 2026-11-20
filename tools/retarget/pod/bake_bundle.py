"""The port's glbs and cook stages for a Linux pod, only the sets whose clips changed: the code, each pack's manifest
and pair_shift.json, those sets' clips and interaction meshes, our rigs, WolvenKit's nightly with libkraken.so, and
WkAnims prebuilt. The decode stays here (hkxc, blender-hkx); the pack stays here (it writes the pack repo).
  python tools/retarget/pod/bake_bundle.py <out.zip>          on Windows, after the clips stage
  bash cyberpunk_animport/tools/retarget/pod/run_bake.sh             on the pod, from the unzipped bundle's root
  python tools/retarget/pod/bake_bundle.py --unpack <results.zip>   here: the pod's glbs and cooked sets into the ports
then skyrim_port.py pack for each pack."""
import os, sys, types, zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
RT = os.path.dirname(HERE)
sys.path.insert(0, RT)
import skyrim_port as sp  # noqa: E402

PACKS = {"opensex": os.path.join(sp.WORK, "skyrim", "port"), "ostimng": os.path.join(sp.WORK, "skyrim", "ostimng")}
KRAKEN = r"C:\Work\WorkSpace\Cyberpunk\WolvenKit\WolvenKit.Core\lib\libkraken.so"


def changed_sets(port):
    """the npc sets whose glb is older than a clip, a mesh or pair_shift.json: as the glbs stage decides"""
    sp.PORT = port
    a = types.SimpleNamespace(all=False)
    shift = os.path.join(port, "pair_shift.json")
    return sorted(d for d, (rig, rows) in sp.sets_of(sp.manifest(), "").items() if not rig.startswith("player_")
                  and not sp.fresh(sp.glb_path(d), [sp.npz_path(r) for r in rows] + [sp.mesh_path(r) for r in rows]
                                   + [shift], a))


def arc(p):
    return "cyberpunk_animport/tools/retarget/" + os.path.relpath(p, RT).replace(os.sep, "/")


def bundle(dest):
    files, extra = {}, {}
    for f in os.listdir(RT):
        if f.endswith(".py"):
            files[arc(os.path.join(RT, f))] = os.path.join(RT, f)
    for f in ("run_bake.sh",):
        files[arc(os.path.join(HERE, f))] = os.path.join(HERE, f)
    trees = [os.path.join(sp.WORK, "wk_nightly"), os.path.join(RT, "wk_anims", "bin", "Release", "net10.0")]
    for root in trees:
        for d, _, fs in os.walk(root):
            for f in fs:
                if f != "appsettings.json" or "wk_nightly" in d:   # WkAnims copies the nightly's beside itself
                    files[arc(os.path.join(d, f))] = os.path.join(d, f)
    # build.json and this machine's half (its Windows paths map on the pod as pod_run's MAP does), and the skeletons
    root = sp.build_config.ROOT
    for f in ("build.json", "build.local.json"):
        if os.path.isfile(os.path.join(root, f)):
            files["cyberpunk_animport/" + f] = os.path.join(root, f)
    for f in os.listdir(sp.SKEL):
        files["cyberpunk_animport/skeletons/cyberpunk/" + f] = os.path.join(sp.SKEL, f)
    for rig in sp.RIGS:
        e = os.path.join(sp.WORK, "empty_anims", rig + ".anims")
        if os.path.isfile(e):
            files[arc(e)] = e
    for f in ("rigs.archive", "rigs.txt"):   # without its list the pod rebuilds it from cr2w files it does not have
        files[arc(os.path.join(sp.WORK, "rigs", f))] = os.path.join(sp.WORK, "rigs", f)
    files[arc(os.path.join(sp.WORK, "wk_nightly", "libkraken.so"))] = KRAKEN
    total = 0
    for pack, port in PACKS.items():
        sets = changed_sets(port)
        extra[arc(os.path.join(port, "sets.txt"))] = "".join(s + "\n" for s in sets)
        for f in ("manifest.json", "pair_shift.json"):
            if os.path.isfile(os.path.join(port, f)):
                files[arc(os.path.join(port, f))] = os.path.join(port, f)
        rows = [r for r in sp.manifest() if r["npcSet"] in set(sets)]
        for r in rows:
            for p in (sp.npz_path(r), sp.mesh_path(r)):
                if os.path.isfile(p):
                    files[arc(p)] = p
        total += len(sets)
        print("%s: %d npc sets, %d clips" % (pack, len(sets), len(rows)))
    missing = [p for p in files.values() if not os.path.isfile(p)]
    if missing:
        sys.exit("missing %d, first %s" % (len(missing), missing[0]))
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED, compresslevel=1) as z:
        for name, text in extra.items():
            z.writestr(name, text)
        for n, (name, p) in enumerate(sorted(files.items()), 1):
            z.write(p, name)
            if n % 1000 == 0:
                print("%d/%d files" % (n, len(files)), flush=True)
    print("%s: %d files, %d npc sets, %.0f MB" % (dest, len(files) + len(extra), total, os.path.getsize(dest) / 1e6))


def unpack(results):
    """the pod's glb/ and depot/ for each pack into the port here; a file extracted now is newer than its inputs"""
    n = 0
    with zipfile.ZipFile(results) as z:
        for name in z.namelist():
            pack, rel = name.split("/", 1)
            out = os.path.join(PACKS[pack], *rel.split("/"))
            os.makedirs(os.path.dirname(out), exist_ok=True)
            with z.open(name) as src, open(out, "wb") as dst:
                dst.write(src.read())
            n += 1
    print("%d files into %s" % (n, ", ".join(PACKS.values())))


if __name__ == "__main__":
    if sys.argv[1:2] == ["--unpack"]:
        unpack(sys.argv[2])
    else:
        bundle(sys.argv[1])
