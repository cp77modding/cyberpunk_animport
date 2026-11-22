"""Any retarget script on the pod, unchanged, from the bundle pod_bundle.py built: the repo's Windows paths are mapped
into the bundle at open time, every Skyrim decode comes from the cache, the Skyrim bodies and rest skeletons from
native_cache.pkl, and a Windows tool or DLL reached is an error, never a silent substitute. From the bundle root:
  python cyberpunk_animport/tools/retarget/pod/pod_run.py pair_batch.py opensex 4      (MESH=1 SAVE=1 ACTORS=2 etc. as ever)
  python cyberpunk_animport/tools/retarget/pod/pod_run.py --collect results.zip         the solved meshes and the batch logs"""
import builtins, io, json, multiprocessing, os, pickle, runpy, sys, zipfile

# before numpy loads: each of pair_batch's workers would start a BLAS thread per core, 10 x 20 on 20 cores
for _v in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ.setdefault(_v, os.environ.get("THREADS", "2"))

HERE = os.path.dirname(os.path.abspath(__file__))
RT = os.path.dirname(HERE)
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(RT)))
# the Windows machine's paths, written by the bundler from its build.local.json (build_config.pod_map)
MAP = [(a, os.path.join(ROOT, *b.split("/"))) for a, b in json.load(open(os.path.join(ROOT, "pod_map.json")))]


def remap(p):
    """a Windows path into the bundle; anything else as given"""
    if not isinstance(p, str) or ("\\" not in p and ":" not in p[:3]):
        return p
    q = p.replace("\\", "/")
    for a, b in MAP:
        i = q.lower().find(a)
        if i >= 0:
            return b + q[i + len(a):]
    return q


TOOLS = ("hkxc", "blender-hkx", "blender.exe", "wolvenkit", "nifly")


def no_windows(ev, a):
    if ev in ("subprocess.Popen", "ctypes.dlopen") and any(t in str(a).lower() for t in TOOLS):
        raise RuntimeError("a Windows-only step was reached on the pod: %s %s" % (ev, str(a)[:200]))


def install():
    _open, _ioopen = builtins.open, io.open
    builtins.open = lambda f, *a, **k: _open(remap(f), *a, **k)
    io.open = lambda f, *a, **k: _ioopen(remap(f), *a, **k)
    for mod, names in ((os.path, ("exists", "isfile", "isdir", "getsize", "getmtime")),
                       (os, ("listdir", "stat", "makedirs", "mkdir", "remove", "unlink"))):
        for n in names:
            setattr(mod, n, (lambda fn: lambda p, *a, **k: fn(remap(p), *a, **k))(getattr(mod, n)))
    for n in ("replace", "rename"):     # a manifest's set names carry Windows backslashes into every output path
        setattr(os, n, (lambda fn: lambda s, d, *a, **k: fn(remap(s), remap(d), *a, **k))(getattr(os, n)))
    import numpy as np
    _load = np.load
    np.load = lambda f, *a, **k: _load(remap(f), *a, **k)
    sys.addaudithook(no_windows)
    os.environ.setdefault("WORKERS", "1")       # read by pair_contact at import, which happens here, before any fork
    sys.path.insert(0, RT)
    import skyrim_body as sb, body_area_map as bm, skyrim_port as sp, pair_contact as pc
    cache = pickle.load(_open(os.path.join(ROOT, "native_cache.pkl"), "rb"))
    dmap = {tuple(k.split("|")): v for k, v in json.load(_open(os.path.join(ROOT, "decode_map.json"))).items()}

    def body_init(self, nif=sb.BODY_NIF, shape=0):
        vars(self).update(cache["body"][os.path.basename(remap(nif)), shape])

    def cached(clip, skel, *_):
        k = clip.replace("\\", "/").lower(), os.path.basename(remap(skel)).lower()
        if k not in dmap:
            raise FileNotFoundError("no cached decode for %s on %s: rebuild the bundle after decoding it" % k)
        return os.path.join(pc.OUT, "decoded", dmap[k])

    # skyrim_body builds these with dirname on a Windows path, which Linux reads as one name: rebuilt in the bundle
    j = os.path.join
    sb.CBBE_MOD = remap(sb.CBBE_MOD)
    mods = os.path.dirname(sb.CBBE_MOD)
    sb.CBBE = j(sb.CBBE_MOD, "CalienteTools", "BodySlide", "ShapeData", "CBBE")
    sb.BODY_NIF, sb.BODY_OSD = j(sb.CBBE, "CBBE Body Physics.nif"), j(sb.CBBE, "CBBE Body.osd")
    sb.HIMBO = j(mods, "Highly Improved Male Body Overhaul", "CalienteTools", "BodySlide", "ShapeData", "HIMBO",
                 "HIMBO Ref - Merged Body with Genitals")
    sb.MALE_NIF, sb.MALE_OSD = sb.HIMBO + ".nif", sb.HIMBO + ".osd"
    sb.FEMALE_HEAD = j(mods, "Baka Haeun UNP", "meshes", "actors", "character", "ygNord", "femalehead.nif")
    sb.BODY_TEX = j(sb.CBBE_MOD, "textures", "actors", "character", "female", "femalebody_1.dds")
    sb.Body.__init__ = body_init
    bm.skyrim_rest = lambda sex="f": dict(cache["rest"][sex])
    sp.decode = cached          # pair_reach's decode
    pc.decoded = cached         # pair_contact.Actor's and skyrim_contact.Actor's


def collect(dest):
    sys.path.insert(0, RT)
    import pair_reach, skyrim_port as sp
    n = 0
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as z:
        roots = [os.path.join(port, "mesh") for port, _ in pair_reach.PORTS.values()] + [os.path.join(sp.WORK, "contact", "batch")]
        for r in roots:
            for d, _, fs in os.walk(r):
                for f in fs:
                    p = os.path.join(d, f)
                    z.write(p, os.path.relpath(p, RT).replace(os.sep, "/"))
                    n += 1
    print("%s: %d files, %.0f MB" % (dest, n, os.path.getsize(dest) / 1e6))


if __name__ == "__main__":
    if sys.argv[1] == "--collect":
        collect(sys.argv[2])
    else:
        if sys.platform != "win32":     # a bundle check on Windows runs one clip, without the pool
            multiprocessing.set_start_method("fork")    # workers inherit the mapping; spawn would start them bare
        install()
        script = os.path.join(RT, sys.argv[1])
        sys.argv = [script] + sys.argv[2:]
        mod = sys.modules.get(os.path.splitext(os.path.basename(script))[0])
        if mod is not None and hasattr(mod, "main"):
            mod.main()          # the patched module itself: run_path would load a second, unpatched copy
        else:
            runpy.run_path(script, run_name="__main__")
