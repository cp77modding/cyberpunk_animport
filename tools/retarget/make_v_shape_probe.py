"""Probe 4: which half fails V -- the PoNC workspot's shape, or the animset baked onto V's skeleton?

V plays a vanilla player-rig lying workspot (q203_01_wakeup player__lie_bed_lean_right__01) and an NPC plays
PoNC's half alone, but V on PoNC's half with the baked set shows nothing. This crosses the two:
  A  ncn\\workspots\\v\\ctl_ponc_shape_q203.workspot  -- PoNC's half, player rows -> vanilla q203 player sets,
     its clip renamed to a q203 clip. V lies = PoNC's shape is fine for V, the baked set is at fault.
  B  ncn\\workspots\\v\\ctl_q203_shape_baked.workspot -- q203's workspot, player rows -> our baked sets, its clip
     renamed to missionary01_lie_a. V lies = the baked set plays, PoNC's shape is at fault.
  C  ncn\\workspots\\v\\ctl_q203_roundtrip.workspot   -- q203's workspot, player rows -> q203's own sets pushed
     through our cook unchanged (work/roundtrip, no retarget). V lies = the cook is fine and the retarget's
     output is at fault; V frozen = our cook pipeline is at fault.
  D  ncn\\workspots\\v\\ctl_q203_nofb.workspot        -- C with every fallback trace removed. V lies = V needs no
     fallback pose.
  E  ncn\\workspots\\v\\ctl_q203_noclamp.workspot     -- B with frameClamping off on every clip.
  F  ncn\\workspots\\v\\ctl_q203_genfb_baked.workspot -- B with a generated fallback pose.
  G  ncn\\workspots\\v\\ctl_q203_genfb.workspot       -- D with a generated fallback pose: the generator's control.
  H  ncn\\workspots\\v\\ctl_q203_guide.workspot       -- the redmodding guide's chain (CP77 plugin, Rokoko, a vanilla
     V container that keeps its fallback); female set on both rows.
  J1 ncn\\workspots\\v\\ctl_q203_move_vanilla.workspot -- q203 playing a clip that moves, on the game's own sets.
  J2 ncn\\workspots\\v\\ctl_q203_move_cooked.workspot  -- the same clip on C's sets. Moves like J1 = our cooked clip
     data plays on V; a held pose = V only ever showed the fallback pose.
  K1 ncn\\workspots\\v\\ctl_q203_guide_fb.workspot    -- H with its clip pointed at q203's lying fallback pair.
  K2 ncn\\workspots\\v\\ctl_q203_baked_q203fb.workspot -- B with q203's fallback copied in, every clip on that pair.
  J3 ncn\\workspots\\v\\ctl_q203_move_trk.workspot     -- J2 with numTracks back at the rig's 23.
  H23 ncn\\workspots\\v\\ctl_q203_guide23.workspot     -- H without the guide's numTracks = 0.
  L  ncn\\workspots\\v\\ctl_q203_trk.workspot          -- our retarget with the rig's 23 reference tracks, no fallback.
  J4 ncn\\workspots\\v\\ctl_q203_move_raw.workspot     -- J2 cooked with raw rotations and the game's fallback.
  L2 ncn\\workspots\\v\\ctl_q203_raw.workspot          -- L cooked with raw rotations.
  L2fb ncn\\workspots\\v\\ctl_q203_rawfb.workspot      -- L2 on q203's lying fallback pair.
  N  ncn\\workspots\\v\\ctl_q203_norm.workspot         -- L2 on a glb made to look like a vanilla V export: Root
     identity, eyes at rest, scale channels, LINEAR samplers. ctl_q203_norm_{root,eyes,scale,linear} apply one each.
  J5 ncn\\workspots\\v\\ctl_q203_move_motion.workspot  -- J4 with each clip's vanilla motionExtraction copied back.
  J6 ncn\\workspots\\v\\ctl_q203_move_simd.workspot    -- J4 cooked by the WolvenKit nightly as SIMD, like vanilla.
  S  ncn\\workspots\\v\\ctl_q203_simd.workspot         -- N_linear cooked as SIMD; Sfb (ctl_q203_simdfb) on q203's pair;
     Snc (ctl_q203_simdnc) with frameClamping off.
  H1 ncn\\workspots\\v\\ctl_q203_h1.workspot           -- S's 24 animated bones, every other channel J6's frame 0.
  H2 ncn\\workspots\\v\\ctl_q203_move_h2.workspot      -- J6 with every channel S holds constant set to S's value.
  Sik ncn\\workspots\\v\\ctl_q203_sik.workspot         -- S with V's IK helpers driven from the bones they follow;
     Sik_root (ctl_q203_sik_root) also holds Root at identity.
All of them are packed with the baked sets into #ncn_v_shape_probe.archive. Install for a run only.

Run: python tools/retarget/make_v_shape_probe.py [workspot ...]   (after make_v_row_probe.py --baked and retarget.ps1)
Naming workspots builds only those and the sets they use; none builds all.
"""
import json
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
WORK = os.path.join(HERE, "work")
WKIT = r"C:\Modding\wolwenKit_upacker\WolvenKit.CLI.exe"
GAME = r"D:\SteamLibrary\steamapps\common\Cyberpunk 2077\archive\pc\content"
NAME = "ncn_v_shape_probe"
PONC_JSON = os.path.join(WORK, "vrow", "check", "ponc_synced_missionary_01_a.workspot.json")
Q203_WS = r"base\workspots\quest\main_quests\epilogue\q203\q203_01_wakeup\player__lie_bed_lean_right__01.workspot"
Q203_ANIMS = {
    "player_man_skeleton": r"base\animations\quest\main_quests\epilogue\q203\q203_01_wakeup\body\q203_01_wakeup__player_male.anims",
    "player_woman_skeleton": r"base\animations\quest\main_quests\epilogue\q203\q203_01_wakeup\body\q203_01_wakeup__player_female.anims",
}
BAKED = {
    "player_man_skeleton": r"ncn\anims\player\missionary_ma_player.anims",
    "player_woman_skeleton": r"ncn\anims\player\missionary_wa_player.anims",
}
ROUNDTRIP = {
    "player_man_skeleton": r"ncn\anims\player\q203_roundtrip_ma.anims",
    "player_woman_skeleton": r"ncn\anims\player\q203_roundtrip_wa.anims",
}
NOFB = {
    "player_man_skeleton": r"ncn\anims\player\q203_nofb_ma.anims",
    "player_woman_skeleton": r"ncn\anims\player\q203_nofb_wa.anims",
}
NOCLAMP = {
    "player_man_skeleton": r"ncn\anims\player\missionary_ma_noclamp.anims",
    "player_woman_skeleton": r"ncn\anims\player\missionary_wa_noclamp.anims",
}
GENFB_BAKED = {
    "player_man_skeleton": r"ncn\anims\player\missionary_ma_genfb.anims",
    "player_woman_skeleton": r"ncn\anims\player\missionary_wa_genfb.anims",
}
GENFB = {
    "player_man_skeleton": r"ncn\anims\player\q203_genfb_ma.anims",
    "player_woman_skeleton": r"ncn\anims\player\q203_genfb_wa.anims",
}
GUIDE = {
    "player_man_skeleton": r"ncn\anims\player\missionary_wa_guide.anims",
    "player_woman_skeleton": r"ncn\anims\player\missionary_wa_guide.anims",
}
GUIDE_FB = {
    "player_man_skeleton": r"ncn\anims\player\missionary_wa_guide_fb.anims",
    "player_woman_skeleton": r"ncn\anims\player\missionary_wa_guide_fb.anims",
}
BAKED_Q203FB = {
    "player_man_skeleton": r"ncn\anims\player\missionary_wa_q203fb.anims",
    "player_woman_skeleton": r"ncn\anims\player\missionary_wa_q203fb.anims",
}
TRK_Q203 = {
    "player_man_skeleton": r"ncn\anims\player\q203_trk_wa.anims",
    "player_woman_skeleton": r"ncn\anims\player\q203_trk_wa.anims",
}
GUIDE23 = {
    "player_man_skeleton": r"ncn\anims\player\missionary_wa_guide23.anims",
    "player_woman_skeleton": r"ncn\anims\player\missionary_wa_guide23.anims",
}
TRK_BAKED = {
    "player_man_skeleton": r"ncn\anims\player\missionary_wa_trk.anims",
    "player_woman_skeleton": r"ncn\anims\player\missionary_wa_trk.anims",
}
RAW_Q203 = {
    "player_man_skeleton": r"ncn\anims\player\q203_raw_wa.anims",
    "player_woman_skeleton": r"ncn\anims\player\q203_raw_wa.anims",
}
RAW_BAKED = {
    "player_man_skeleton": r"ncn\anims\player\missionary_wa_raw.anims",
    "player_woman_skeleton": r"ncn\anims\player\missionary_wa_raw.anims",
}
RAWFB_BAKED = {
    "player_man_skeleton": r"ncn\anims\player\missionary_wa_rawfb.anims",
    "player_woman_skeleton": r"ncn\anims\player\missionary_wa_rawfb.anims",
}
MOTION_Q203 = {rig: r"ncn\anims\player\q203_motion_wa.anims" for rig in ("player_man_skeleton", "player_woman_skeleton")}
SIMD_Q203 = {rig: r"ncn\anims\player\q203_simd_wa.anims" for rig in ("player_man_skeleton", "player_woman_skeleton")}
SIMD = {"ctl_q203_" + v: {rig: r"ncn\anims\player\missionary_wa_%s.anims" % v
                           for rig in ("player_man_skeleton", "player_woman_skeleton")} for v in ("simd", "simdfb", "simdnc", "h1", "sik", "sik_root")}
H2_Q203 = {rig: r"ncn\anims\player\q203_h2_wa.anims" for rig in ("player_man_skeleton", "player_woman_skeleton")}
NORM = {"ctl_q203_" + v: {rig: r"ncn\anims\player\missionary_wa_%s.anims" % v
                           for rig in ("player_man_skeleton", "player_woman_skeleton")}
        for v in ("norm", "norm_root", "norm_eyes", "norm_scale", "norm_linear")}
MOVE_CLIP = "stand_wall_lean0__2h_on_wall__01__to__stand_wall_lean0__rh_blood__01__cough_blood__01"
Q203_CLIP, PONC_CLIP = "lie_bed_90__sleep__02", "missionary01_lie_a"


def run(*args):
    r = subprocess.run([WKIT] + list(args), capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit("WolvenKit failed: %s\n%s%s" % (" ".join(args), r.stdout, r.stderr))


def fnv1a64(text):
    h = 0xcbf29ce484222325
    for c in text.lower().encode():
        h = ((h ^ c) * 0x100000001b3) & 0xFFFFFFFFFFFFFFFF
    return h


def rows(doc):
    return doc["Data"]["RootChunk"]["workspotTree"]["Data"]["finalAnimsets"]


def rename(node, old, new):
    """Every CName in the tree equal to `old` becomes `new`; returns how many."""
    n = 0
    if isinstance(node, dict):
        if node.get("$type") == "CName" and node.get("$value") == old:
            node["$value"] = new
            return 1
        for v in node.values():
            n += rename(v, old, new)
    elif isinstance(node, list):
        for v in node:
            n += rename(v, old, new)
    return n


def point_player_rows(doc, animsets, label):
    hit = 0
    for row in rows(doc):
        rig = row["rig"]["DepotPath"]["$value"].split("\\")[-1][:-len(".rig")]
        if rig not in animsets:
            continue
        a = animsets[rig]
        row["animations"]["cinematics"] = [row["animations"]["cinematics"][0]]
        row["animations"]["cinematics"][0]["animSet"]["DepotPath"]["$value"] = a
        row["loadingHandles"] = [row["loadingHandles"][0]]
        row["loadingHandles"][0]["DepotPath"]["$value"] = a
        row["animations"]["hash"] = str(fnv1a64(label + "|" + rig + "|" + a))
        hit += 1
    if hit != len(animsets):
        sys.exit("%s: %d player rows, want %d" % (label, hit, len(animsets)))


ONLY = {a[:-len(".workspot")] if a.endswith(".workspot") else a for a in sys.argv[1:]}


def built(name):
    return not ONLY or name[:-len(".workspot")] in ONLY


def cook(doc, out_dir, name):
    if not built(name):
        return
    os.makedirs(out_dir, exist_ok=True)
    src = os.path.join(BUILD, "json", name + ".json")
    os.makedirs(os.path.dirname(src), exist_ok=True)
    json.dump(doc, open(src, "w", encoding="utf-8"), indent=2)
    run("convert", "deserialize", src, "-o", out_dir, "-v", "Quiet")
    if not os.path.isfile(os.path.join(out_dir, name)):
        sys.exit("deserialize wrote no %s" % name)


BUILD = os.path.join(WORK, "vshape")


def main():
    for p in [PONC_JSON] + [os.path.join(WORK, "depot", a) for a in BAKED.values()]:
        if not os.path.isfile(p):
            sys.exit("missing %s -- run make_v_row_probe.py --baked and retarget.ps1 first" % p)
    shutil.rmtree(BUILD, ignore_errors=True)
    depot = os.path.join(BUILD, NAME)
    own = os.path.join(depot, "ncn", "workspots", "v")

    # A: PoNC's shape, vanilla V sets. The PoNC readback json still carries our baked rows; repoint them.
    a = json.load(open(PONC_JSON, encoding="utf-8"))
    point_player_rows(a, Q203_ANIMS, "ctl_ponc_shape_q203")
    if rename(a["Data"]["RootChunk"]["workspotTree"], PONC_CLIP, Q203_CLIP) < 1:
        sys.exit("A: no %s clip to rename" % PONC_CLIP)
    cook(a, own, "ctl_ponc_shape_q203.workspot")

    # B: q203's shape, our baked sets.
    raw = os.path.join(BUILD, "raw")
    run("unbundle", GAME, "-o", raw, "-r", r"q203_01_wakeup\\player__lie_bed_lean_right__01\.workspot", "-v", "Quiet")
    ws = os.path.join(raw, Q203_WS)
    if not os.path.isfile(ws):
        sys.exit("q203 workspot not unbundled: %s" % ws)
    run("convert", "serialize", ws, "-v", "Quiet")
    b = json.load(open(ws + ".json", encoding="utf-8"))
    point_player_rows(b, BAKED, "ctl_q203_shape_baked")
    if rename(b["Data"]["RootChunk"]["workspotTree"], Q203_CLIP, PONC_CLIP) < 1:
        sys.exit("B: no %s clip to rename" % Q203_CLIP)
    cook(b, own, "ctl_q203_shape_baked.workspot")

    # C: q203's shape and clip names, our cook of q203's own sets.
    c = json.load(open(ws + ".json", encoding="utf-8"))
    point_player_rows(c, ROUNDTRIP, "ctl_q203_roundtrip")
    cook(c, own, "ctl_q203_roundtrip.workspot")

    # D: C without its fallback pose.  E: B with frameClamping off.
    d = json.load(open(ws + ".json", encoding="utf-8"))
    point_player_rows(d, NOFB, "ctl_q203_nofb")
    cook(d, own, "ctl_q203_nofb.workspot")
    e = json.load(open(ws + ".json", encoding="utf-8"))
    point_player_rows(e, NOCLAMP, "ctl_q203_noclamp")
    if rename(e["Data"]["RootChunk"]["workspotTree"], Q203_CLIP, PONC_CLIP) < 1:
        sys.exit("E: no %s clip to rename" % Q203_CLIP)
    cook(e, own, "ctl_q203_noclamp.workspot")

    # F: B with a generated fallback pose.  G: q203 with a generated one.
    f = json.load(open(ws + ".json", encoding="utf-8"))
    point_player_rows(f, GENFB_BAKED, "ctl_q203_genfb_baked")
    if rename(f["Data"]["RootChunk"]["workspotTree"], Q203_CLIP, PONC_CLIP) < 1:
        sys.exit("F: no %s clip to rename" % Q203_CLIP)
    cook(f, own, "ctl_q203_genfb_baked.workspot")
    g = json.load(open(ws + ".json", encoding="utf-8"))
    point_player_rows(g, GENFB, "ctl_q203_genfb")
    cook(g, own, "ctl_q203_genfb.workspot")

    # H: the redmodding guide's chain.
    h = json.load(open(ws + ".json", encoding="utf-8"))
    point_player_rows(h, GUIDE, "ctl_q203_guide")
    if rename(h["Data"]["RootChunk"]["workspotTree"], Q203_CLIP, PONC_CLIP) < 1:
        sys.exit("H: no %s clip to rename" % Q203_CLIP)
    cook(h, own, "ctl_q203_guide.workspot")

    # J1 / J2: a clip that moves, on the game's own sets and on our cook of them.
    for name, sets in (("ctl_q203_move_vanilla", Q203_ANIMS), ("ctl_q203_move_cooked", ROUNDTRIP)):
        j = json.load(open(ws + ".json", encoding="utf-8"))
        point_player_rows(j, sets, name)
        if rename(j["Data"]["RootChunk"]["workspotTree"], Q203_CLIP, MOVE_CLIP) < 1:
            sys.exit("%s: no %s clip to rename" % (name, Q203_CLIP))
        cook(j, own, name + ".workspot")

    # K1 / K2: our clips pointed at q203's own lying fallback pair.
    for name, sets in (("ctl_q203_guide_fb", GUIDE_FB), ("ctl_q203_baked_q203fb", BAKED_Q203FB)):
        k = json.load(open(ws + ".json", encoding="utf-8"))
        point_player_rows(k, sets, name)
        if rename(k["Data"]["RootChunk"]["workspotTree"], Q203_CLIP, PONC_CLIP) < 1:
            sys.exit("%s: no %s clip to rename" % (name, Q203_CLIP))
        cook(k, own, name + ".workspot")

    # J3 / H23 / L: the rig's 23 float tracks kept.
    for name, sets, clip in (("ctl_q203_move_trk", TRK_Q203, MOVE_CLIP), ("ctl_q203_guide23", GUIDE23, PONC_CLIP),
                             ("ctl_q203_trk", TRK_BAKED, PONC_CLIP), ("ctl_q203_move_raw", RAW_Q203, MOVE_CLIP),
                             ("ctl_q203_raw", RAW_BAKED, PONC_CLIP), ("ctl_q203_rawfb", RAWFB_BAKED, PONC_CLIP)) \
            + tuple((name, sets, PONC_CLIP) for name, sets in NORM.items()) \
            + (("ctl_q203_move_motion", MOTION_Q203, MOVE_CLIP), ("ctl_q203_move_simd", SIMD_Q203, MOVE_CLIP),
               ("ctl_q203_move_h2", H2_Q203, MOVE_CLIP)) \
            + tuple((name, sets, PONC_CLIP) for name, sets in SIMD.items()):
        t = json.load(open(ws + ".json", encoding="utf-8"))
        point_player_rows(t, sets, name)
        if rename(t["Data"]["RootChunk"]["workspotTree"], Q203_CLIP, clip) < 1:
            sys.exit("%s: no %s clip to rename" % (name, Q203_CLIP))
        cook(t, own, name + ".workspot")

    baked =list(BAKED.values()) + list(NOCLAMP.values()) + list(GENFB_BAKED.values()) + list(set(GUIDE.values())) \
        + list(set(GUIDE_FB.values())) + list(set(BAKED_Q203FB.values())) + list(set(GUIDE23.values())) \
        + list(set(TRK_BAKED.values())) + list(set(RAW_BAKED.values())) + list(set(RAWFB_BAKED.values())) \
        + sorted({p for sets in NORM.values() for p in sets.values()}) \
        + sorted({p for sets in SIMD.values() for p in sets.values()})
    trips = list(ROUNDTRIP.values()) + list(NOFB.values()) + list(GENFB.values()) + list(set(TRK_Q203.values())) \
        + list(set(RAW_Q203.values())) + list(set(MOTION_Q203.values())) + list(set(SIMD_Q203.values())) + list(set(H2_Q203.values()))
    checks = (("ctl_ponc_shape_q203.workspot", Q203_ANIMS), ("ctl_q203_shape_baked.workspot", BAKED),
                       ("ctl_q203_roundtrip.workspot", ROUNDTRIP), ("ctl_q203_nofb.workspot", NOFB),
                       ("ctl_q203_noclamp.workspot", NOCLAMP), ("ctl_q203_genfb_baked.workspot", GENFB_BAKED),
                       ("ctl_q203_genfb.workspot", GENFB), ("ctl_q203_guide.workspot", GUIDE),
                       ("ctl_q203_move_vanilla.workspot", Q203_ANIMS), ("ctl_q203_move_cooked.workspot", ROUNDTRIP),
                       ("ctl_q203_guide_fb.workspot", GUIDE_FB), ("ctl_q203_baked_q203fb.workspot", BAKED_Q203FB),
                       ("ctl_q203_move_trk.workspot", TRK_Q203), ("ctl_q203_guide23.workspot", GUIDE23),
                       ("ctl_q203_trk.workspot", TRK_BAKED), ("ctl_q203_move_raw.workspot", RAW_Q203),
                       ("ctl_q203_raw.workspot", RAW_BAKED), ("ctl_q203_rawfb.workspot", RAWFB_BAKED)) \
            + tuple((name + ".workspot", sets) for name, sets in NORM.items()) \
            + (("ctl_q203_move_motion.workspot", MOTION_Q203), ("ctl_q203_move_simd.workspot", SIMD_Q203),
               ("ctl_q203_move_h2.workspot", H2_Q203)) \
            + tuple((name + ".workspot", sets) for name, sets in SIMD.items())
    checks = [(name, want) for name, want in checks if built(name)]
    if ONLY and len(checks) != len(ONLY):
        sys.exit("unknown workspot in %s" % sorted(ONLY))
    needed = {p for _, want in checks for p in want.values()}
    for a_path, src in [(p, os.path.join(WORK, "depot", p)) for p in baked] + \
                       [(p, os.path.join(WORK, "roundtrip", "depot", p)) for p in trips]:
        if a_path not in needed:
            continue
        if not os.path.isfile(src):
            sys.exit("missing %s" % src)
        dst = os.path.join(depot, a_path)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy(src, dst)

    # Read both back: every player row names the animset it was given, and no two rows share a hash.
    for name, want in checks:
        chk = os.path.join(BUILD, "check")
        os.makedirs(chk, exist_ok=True)
        shutil.copy(os.path.join(own, name), chk)
        run("convert", "serialize", os.path.join(chk, name), "-v", "Quiet")
        back = rows(json.load(open(os.path.join(chk, name + ".json"), encoding="utf-8")))
        got = {r["rig"]["DepotPath"]["$value"].split("\\")[-1][:-len(".rig")]:
               r["animations"]["cinematics"][0]["animSet"]["DepotPath"]["$value"] for r in back}
        for rig, a_path in want.items():
            if got.get(rig) != a_path:
                sys.exit("%s: %s reads %s, not %s" % (name, rig, got.get(rig), a_path))
        hashes = [r["animations"]["hash"] for r in back]
        if len(set(hashes)) != len(hashes):
            sys.exit("%s: rows share a setup hash" % name)
        print("%-34s %s" % (name, ", ".join("%s -> %s" % (k, v.split("\\")[-1]) for k, v in want.items())))

    run("pack", depot, "-o", BUILD, "-v", "Quiet")
    final = os.path.join(BUILD, "#" + NAME + ".archive")
    os.replace(os.path.join(BUILD, NAME + ".archive"), final)
    print("packed: %s" % final)


if __name__ == "__main__":
    main()
