"""The retarget pipeline packed for a Linux GPU pod (RunPod): the code, our bodies and rigs, both packs' manifests and
every clip's cached decode, plus what the Windows-only steps produce (the Skyrim bodies PyNifly reads, Skyrim's rest
skeletons hkxc decodes), so the pod never needs a Windows tool. Run on the Windows machine:
  python tools/retarget/pod/pod_bundle.py <out.zip>     ALL=0: only the clips a sweep solves (ACTORS=2,3, MATCH=a,b
                                                        as pair_batch)
On the pod: setup.sh, then pod_run.py (see its header)."""
import hashlib, json, os, pickle, sys, zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
RT = os.path.dirname(HERE)
REPO = os.path.dirname(os.path.dirname(RT))
sys.path.insert(0, RT)
import skyrim_port as sp, skyrim_body as sb, body_area_map as bm, pair_reach, pair_batch, pair_contact as pc  # noqa: E402


def norm_clip(path):
    """a clip path as both machines spell it: the Windows source path, slashes forward, lower case"""
    return path.replace("\\", "/").lower()


def skel_of(row):
    return sp.skeleton_of(row)


def decode_map(rows_of):
    """{(clip, skeleton file name): cache file name} for every row, and the rows whose decode is not cached"""
    sha, out, missing = {}, {}, []
    for pack, src, row in rows_of:
        clip, skel = os.path.join(src, row["file"]), skel_of(row)
        for p in (clip, skel):
            if p not in sha:
                sha[p] = hashlib.sha1(open(p, "rb").read()).digest()
        name = hashlib.sha1(sha[clip] + sha[skel]).hexdigest()[:20] + ".xml"
        if os.path.isfile(os.path.join(pc.OUT, "decoded", name)):
            out[norm_clip(clip), os.path.basename(skel).lower()] = name
        else:
            missing.append("%s %s" % (pack, row["file"]))
    return out, missing


def native_cache():
    out = {"body": {}, "rest": {}}
    for nif in (sb.BODY_NIF, sb.MALE_NIF, sb.FEMALE_HEAD):
        if os.path.exists(nif):
            out["body"][os.path.basename(nif), 0] = dict(vars(sb.Body(nif)))
    for sex in ("f", "m"):
        out["rest"][sex] = bm.skyrim_rest(sex)
    return out


def tree(root):
    for d, _, fs in os.walk(root):
        for f in fs:
            yield os.path.join(d, f)


def main():
    dest = sys.argv[1]
    every = os.environ.get("ALL", "1") == "1"
    rows_of = []
    for pack, (port, src) in pair_reach.PORTS.items():
        rows = json.load(open(os.path.join(port, "manifest.json")))
        if not every:
            sizes = [int(s) for s in os.environ.get("ACTORS", "2").split(",") if s]
            match = [m for m in os.environ.get("MATCH", "").split(",") if m] or [""]   # as pair_batch's MATCH
            want = {r["clip"] for b in pair_batch.clip_bases(rows, sizes) if any(m in b for m in match)
                    for r in rows if r["clip"].startswith(b + "_")}
            rows = [r for r in rows if r["clip"] in want]
        rows_of += [(pack, src, r) for r in rows]
    dmap, missing = decode_map(rows_of)
    if missing:
        sys.exit("%d decodes not cached, first: %s -- run the decode first" % (len(missing), missing[0]))
    files = {}      # path in the zip: source path
    for f in os.listdir(RT):
        if f.endswith(".py"):
            files["cyberpunk_animport/tools/retarget/" + f] = os.path.join(RT, f)
    for f in os.listdir(HERE):
        files["cyberpunk_animport/tools/retarget/pod/" + f] = os.path.join(HERE, f)
    for p in tree(os.path.join(sp.WORK, "body")):
        files["cyberpunk_animport/tools/retarget/" + os.path.relpath(p, RT).replace(os.sep, "/")] = p
    # build.json and this machine's half (its Windows paths map as MAP does), and the skeletons clips are fitted onto
    for f in ("build.json", "build.local.json"):
        if os.path.isfile(os.path.join(sp.build_config.ROOT, f)):
            files["cyberpunk_animport/" + f] = os.path.join(sp.build_config.ROOT, f)
    for p in tree(sp.SKEL):
        files["cyberpunk_animport/skeletons/cyberpunk/" + os.path.basename(p)] = p
    for name in set(dmap.values()):
        files["cyberpunk_animport/tools/retarget/work/contact/decoded/" + name] = os.path.join(pc.OUT, "decoded", name)
    for pack, (port, _) in pair_reach.PORTS.items():
        for f in ("manifest.json", "pair_shift.json", "scenes.json"):
            if os.path.isfile(os.path.join(port, f)):
                files["cyberpunk_animport/tools/retarget/" + os.path.relpath(os.path.join(port, f), RT).replace(os.sep, "/")] = os.path.join(port, f)
    for p in tree(os.path.join(sp.PORT, "skel")):
        files["cyberpunk_animport/tools/retarget/" + os.path.relpath(p, RT).replace(os.sep, "/")] = p
    mods = os.path.dirname(sb.CBBE_MOD)
    for p in (sb.BODY_OSD, sb.MALE_OSD, sb.BODY_TEX):     # read in Python, not through the DLL
        files["ext/mods/" + os.path.relpath(p, mods).replace(os.sep, "/")] = p
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        z.writestr("native_cache.pkl", pickle.dumps(native_cache()))
        z.writestr("decode_map.json", json.dumps({"%s|%s" % k: v for k, v in dmap.items()}))
        z.writestr("pod_map.json", json.dumps(sp.build_config.pod_map()))
        for n, (arc, p) in enumerate(sorted(files.items()), 1):
            z.write(p, arc)
            if n % 500 == 0:
                print("%d/%d files" % (n, len(files)), flush=True)
    print("%s: %d files, %d decodes, %.0f MB" % (dest, len(files) + 2, len(dmap), os.path.getsize(dest) / 1e6))


if __name__ == "__main__":
    main()
