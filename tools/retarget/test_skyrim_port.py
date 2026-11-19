"""The OpenSex port's readers: tagfile -> packfile, the skeleton padding, the scene inventory, the axis swap.
No Skyrim data -- every input is a few synthetic lines."""
import os
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import skyrim_retarget as SR  # noqa: E402
import skyrim_scenes as SC  # noqa: E402
import skyrim_skeleton as SK  # noqa: E402
import skyrim_tagfile as TF  # noqa: E402

TAG = """<?xml version="1.0" encoding="ascii"?>
<hktagfile version="1">
<object id="#0001" type="hkaSplineCompressedAnimation">
  <int name="type">%(type)d</int>
  <real name="duration">x41200000 <!-- 10.0 --></real>
  <int name="numberOfTransformTracks">2</int>
  <ref name="extractedMotion">#0004</ref>
  <array name="annotationTracks" size="%(n)d">%(refs)s</array>
  <int name="numFrames">601</int>
  <array name="data" size="3">1 2 3</array>
</object>
<object id="#0002" type="hkaAnnotationTrack">
  <string name="trackName">NPC Root [Root]</string>
  <array name="annotations" size="1"><struct><string name="text">FootLeft</string></struct></array>
</object>
<object id="#0003" type="hkaAnnotationTrack"><string name="trackName">NPC Pelvis [Pelv]</string></object>
<object id="#0004" type="hkaDefaultAnimatedReferenceFrame">
  <vec4 name="up">x00000000 x00000000 x3f800000 x00000000</vec4>
  <vec4 name="forward">x00000000 x3f800000 x00000000 x00000000</vec4>
  <real name="duration">x41200000</real>
  <array name="referenceFrameSamples" size="1"><vec4>x3f800000 x40000000 x40400000 x00000000</vec4></array>
</object>
<object id="#0005" type="hkaAnimationBinding"><string name="originalSkeletonName">NPC Root [Root]</string></object>
</hktagfile>
"""

SKEL = """<hkobject name="#0002" class="hkaSkeleton" signature="0x0">
\t\t\t<hkparam name="name">NPC Root [Root]</hkparam>
\t\t\t<hkparam name="parentIndices" numelements="2">
\t\t\t\t-1 0
\t\t\t</hkparam>
\t\t\t<hkparam name="bones" numelements="2">
\t\t\t\t<hkobject><hkparam name="name">NPC Root [Root]</hkparam></hkobject>
\t\t\t\t<hkobject><hkparam name="name">Shield</hkparam></hkobject>
\t\t\t</hkparam>
\t\t\t<hkparam name="referencePose" numelements="2">
\t\t\t\t(0 0 0)(0 0 0 1)(1 1 1)
\t\t\t\t(0 0 0)(0 0 0 1)(1 1 1)
\t\t\t</hkparam>
</hkobject>"""

SCENE = """<scene id="OpS|A!B|Sx|Thing" actors="2" style="OScene">
<info name="Thing" animator="Ace"/>
<anim id="_Sx-Thing_S1" t="L" l="2"/>
<speed a="1"><sp qnt=".5"><anim id="_Sx-Thing_S1" t="L" l="2"/></sp><sp qnt="1"><anim id="_Sx-Thing_S2" t="L"/></sp></speed>
<nav><option go="OpS|A!B|Ho|Other"/></nav>
<actors><actor position="0" penisAngle="9" tags="lyingback"/><actor position="1" tags="kneeling"/></actors>
</scene>"""


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


def tagfile_cases(tmp, fails):
    path = os.path.join(tmp, "clip.hkx")
    write(path, TAG % {"type": 3, "n": 2, "refs": "<ref>#0002</ref><ref>#0003</ref>"})
    root = ET.fromstring(TF.convert(path))
    anim = root.find(".//hkobject[@class='hkaSplineCompressedAnimation']")
    p = {e.get("name"): e for e in anim}
    if float(p["duration"].text) != 10.0:
        fails.append("hex real x41200000 read as %s, not 10" % p["duration"].text)
    if p["numberOfFloatTracks"].text != "0" or p["numBlocks"].text != "0":
        fails.append("an int the tagfile omits is not written as its default 0")
    if p["data"].text.split() != ["1", "2", "3"] or p["blockOffsets"].get("numelements") != "0":
        fails.append("arrays not carried, or an omitted one not empty")
    if p["type"].text != "HK_WAVELET_COMPRESSED_ANIMATION" or p["extractedMotion"].text != "#0004":
        fails.append("type or extracted motion not as hkxc names them")
    notes = anim.findall(".//hkparam[@name='annotations']")
    if len(notes) != 2 or notes[0].get("numelements") != "1" or notes[1].get("numelements") != "0":
        fails.append("annotation tracks not carried one per transform track")
    if "FootLeft" not in ET.tostring(notes[0], encoding="unicode"):
        fails.append("an annotation's text was lost")
    rf = root.find(".//hkobject[@class='hkaDefaultAnimatedReferenceFrame']")
    if rf is None or "(1 2 3 0)" not in ET.tostring(rf, encoding="unicode"):
        fails.append("reference frame samples not carried as (x y z w)")
    for kind, bad in (("non-spline", {"type": 1, "n": 2, "refs": "<ref>#0002</ref><ref>#0003</ref>"}),
                      ("short annotations", {"type": 3, "n": 1, "refs": "<ref>#0002</ref>"})):
        write(path, TAG % bad)
        try:
            TF.convert(path)
            fails.append("a %s clip converted instead of failing" % kind)
        except ValueError:
            pass


def skeleton_cases(fails):
    text, n, k = SK.pad(SKEL, ["NPC Root [Root]", "SHIELD", "Hair1", "Hair2"])
    if (n, k) != (2, 2) or 'name="bones" numelements="4"' not in text or "Hair2" not in text:
        fails.append("padding did not grow the skeleton to the clip's tracks")
    if 'name="parentIndices" numelements="4"' not in text or 'name="referencePose" numelements="4"' not in text:
        fails.append("parents or reference pose not grown with the bones")
    try:
        SK.pad(SKEL, ["NPC Root [Root]", "Weapon", "Hair1"])
        fails.append("a clip whose core tracks are not the skeleton's bones was padded")
    except ValueError:
        pass


def scene_cases(tmp, fails):
    root = os.path.join(tmp, "os")
    write(os.path.join(root, SC.SCENE_ROOT, "OpS", "AB", "Sx", "Thing.xml"), SCENE)
    for stem in ("_Sx-Thing_S1_0", "_Sx-Thing_S1_1", "_Sx-Thing_S2_0", "_Sx-Thing_S2_1", "_Ho-Lonely_0"):
        write(os.path.join(root, SC.ANIM_ROOT, "OpS", "AB", "Sx", "Thing", stem + ".hkx"), "<?xml")
    work, scenes, source = SC.build(root, {})
    s = scenes[0]
    if [a["sex"] for a in s["actors"]] != ["m", "f"]:
        fails.append("actor sex is not read from penisAngle")
    if s["start"] != "_Sx-Thing_S1" or [a.get("speed") for a in s["anims"]] != [0.5, 1.0]:
        fails.append("the start anim and its speed listing are not one row each: %s" % s["anims"])
    if s["anims"][1]["clips"] != ["sx-thing_s2_0", "sx-thing_s2_1"] or s["goes"] != ["OpS|A!B|Ho|Other"]:
        fails.append("clips per actor or the scene's links wrong")
    by = {(r["clip"], r["rig"]) for r in work}
    if ("sx-thing_s1_0", "man_base") not in by or ("sx-thing_s1_1", "woman_base") not in by:
        fails.append("a clip is not baked on its actor's body")
    if ("ho-lonely_0", "man_base") not in by or ("ho-lonely_0", "woman_base") not in by:
        fails.append("a clip no scene names is not baked on both bodies")
    if next(r for r in work if r["clip"] == "sx-thing_s1_1")["npcSet"] != r"opensex\anims\npc\ab_wa.anims":
        fails.append("set not named for the clip's folder and body")
    if len(source) != 5:
        fails.append("source-map does not hold one row per clip")
    solo = ('<scene id="OpS_solo|S!tanding|Ap|%s"><anim id="_Ap-%s"/><actors>'
            '<actor position="0" penisAngle="6"/></actors></scene>')
    for name in ("SoloIdleFemale", "SoloIdleMale", "SoloIdle"):
        write(os.path.join(root, SC.SCENE_ROOT, "OpS_solo", name + ".xml"), solo % (name, name))
        write(os.path.join(root, SC.ANIM_ROOT, "OpS_solo", "Standing", "_Ap-%s_0.hkx" % name), "<?xml")
    work = SC.build(root, {})[0]
    bodies = {n: sorted(r["rig"] for r in work if r["clip"] == "ap-%s_0" % n.lower())
              for n in ("SoloIdleFemale", "SoloIdleMale", "SoloIdle")}
    if bodies != {"SoloIdleFemale": ["woman_base"], "SoloIdleMale": ["man_base"],
                  "SoloIdle": ["man_base", "woman_base"]}:
        fails.append("a solo scene's sex is not its name (every solo actor has a penisAngle): %s" % bodies)
    write(os.path.join(root, SC.SCENE_ROOT, "OpS", "AB", "Sx", "Swap.xml"),
          SCENE.replace('position="0" penisAngle="9"', 'position="0"').replace("Thing\" actors", "Swap\" actors"))
    work = SC.build(root, {})[0]
    if sorted(r["rig"] for r in work if r["clip"] == "sx-thing_s1_0") != ["man_base", "woman_base"]:
        fails.append("a clip cast as a man in one scene and a woman in another is not baked on both bodies")
    restore_cases(tmp, fails)


OLD = """<scene id="OpS|K!L|VJ|Gone" actors="2"><info name="Gone" animator="Ace"/>
<anim id="0SxOpS_VJ-Gone_S0" t="L" l="2"/>
<speed a="1"><sp qnt=".5"><anim id="0SxOpS_VJ-Gone_S0" t="L"/></sp></speed></scene>"""
REDIRECT = """<scene id="OpS|K!L|VJ|Gone" actors="2"><anim id="_Ho-Redirect" t="T" l="1" dest="X"/>
<actors><actor position="0" penisAngle="2" tags="kneeling"/><actor position="1" tags="lyingback"/></actors></scene>"""


def restore_cases(tmp, fails):
    root = os.path.join(tmp, "restore")
    rel = os.path.join(SC.SCENE_ROOT, "OpS", "KL", "VJ", "Gone.xml")
    write(os.path.join(root, rel), OLD)
    for stem in ("_VJ-Gone_S0_0", "_VJ-Gone_S0_1", "_Ho-Redirect_0", "_Ho-Redirect_1"):
        write(os.path.join(root, SC.ANIM_ROOT, "OpS", "KL", "VJ", "Gone", stem + ".hkx"), "<?xml")
    git = ["git", "-C", root, "-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false"]
    subprocess.run(["git", "init", "-q", root], check=True)
    subprocess.run(git + ["add", "-A"], check=True)
    subprocess.run(git + ["commit", "-q", "-m", "old"], check=True)
    write(os.path.join(root, rel), REDIRECT)
    work, scenes, _ = SC.build(root, {"OpS/KL/VJ/Gone.xml": ("Gone Again", ["idle"], [("kneeling", "f"), ("lyingback", "f")])}, "HEAD")
    gone = [s for s in scenes if s["id"] == "OpS|K!L|VJ|Gone"]
    if len(gone) != 1 or gone[0]["start"] != "_VJ-Gone_S0":
        fails.append("a restored scene does not replace the file that took its place: %s" % gone)
        return
    if gone[0]["name"] != "Gone Again":
        fails.append("a restored scene does not take the name given: %s" % gone[0]["name"])
    if gone[0]["tags"] != ["idle"]:
        fails.append("a restored scene with no <metadata> does not take the tags given: %s" % gone[0]["tags"])
    if [a["sex"] for a in gone[0]["actors"]] != ["f", "f"]:
        fails.append("a restored scene's cast is not the one given: %s" % gone[0]["actors"])
    if gone[0]["anims"][0]["clips"] != ["vj-gone_s0_0", "vj-gone_s0_1"]:
        fails.append("an old 0SxOpS_ anim does not find its _X_<position> clips: %s" % gone[0]["anims"])
    if sorted(r["rig"] for r in work if r["clip"] == "vj-gone_s0_0") != ["man_base", "woman_base"]:
        fails.append("a two-actor scene's clip is not baked on both bodies (scene-picker.md §1b)")


def axis_cases(fails):
    r, t = SR.to_gltf(np.array([[0, 0, 0, 1.0]]), np.array([[0, 0, 1.0], [0, 1.0, 0]]))
    if not np.allclose(t, [[0, 1, 0], [0, 0, -1]]):
        fails.append("Skyrim up / forward are not glTF +Y / -Z: %s" % t.tolist())
    q = SR.swing(np.array([1.0, 0, 0]), np.array([0, 1.0, 0]))
    if not np.allclose(SR.rg.qrot(q, np.array([1.0, 0, 0])), [0, 1, 0]):
        fails.append("swing does not turn a onto b")
    ax = np.array([0, 1.0, 0])
    sw = np.array([np.sin(np.radians(10)), 0, 0, np.cos(np.radians(10))])   # 20 deg bend about x
    tw = np.array([0, np.sin(np.radians(45)), 0, np.cos(np.radians(45))])   # 90 deg about the bone
    u = SR.untwist(SR.rg.qmul(sw, tw)[None], ax)[0]
    if not np.allclose(np.abs(np.dot(u, sw)), 1, atol=1e-9):
        fails.append("untwist does not leave the bend alone: %s" % u.tolist())
    if not np.allclose(SR.rg.qrot(u, ax), SR.rg.qrot(SR.rg.qmul(sw, tw), ax)):
        fails.append("untwist moves where the bone points")


def pack_cases(tmp, fails):
    """The pack stage replaces our npc/player sets and drops a stale one; a generated transition and the big/fat rigs'
    folders (retarget.ps1 -Rig's) stay. WolvenKit is stubbed: only its archive's name is written"""
    import types
    import skyrim_port as sp
    port, pack = os.path.join(tmp, "port"), os.path.join(tmp, "repo", "opensex")
    os.makedirs(os.path.join(tmp, "repo", ".git"))
    anims = os.path.join(pack, "depot", "opensex", "anims")

    def touch(p, s):
        os.makedirs(os.path.dirname(p), exist_ok=True)
        open(p, "w").write(s)
    for f in ("npc/a_ma.anims", "npc/old_ma.anims", "npc/gen_a_ma.anims", "player/a_pma.anims",
              "man_big/a_ma_man_big.anims", "man_big/gen_a_ma_man_big.anims"):
        touch(os.path.join(anims, f), "old")
    for f in ("depot/opensex/anims/npc/a_ma.anims", "depot/opensex/anims/player/a_pma.anims", "scenes.json",
              "source-map.json"):
        touch(os.path.join(port, f), "new")
    saved = sp.PORT, sp.manifest, sp.run
    sp.PORT = port
    sp.manifest = lambda: [{"npcSet": r"opensex\anims\npc\a_ma.anims", "rig": "man_base", "clip": "a",
                            "playerSet": r"opensex\anims\player\a_pma.anims", "playerRig": "player_man"}]
    packed = []
    sp.run = lambda *cmd, env=None: (packed.append(1), touch(os.path.join(cmd[4], "opensex.archive"), "")) \
        if cmd[1] == "pack" else ""
    try:
        sp.stage_pack(types.SimpleNamespace(pack=pack, ship_glb=False, wolvenkit="wk", all=False))
        sp.stage_pack(types.SimpleNamespace(pack=pack, ship_glb=False, wolvenkit="wk", all=False))
        if len(packed) != 1:
            fails.append("pack ran WolvenKit %d times for one change, want 1" % len(packed))
    finally:
        sp.PORT, sp.manifest, sp.run = saved
    got = sorted("%s=%s" % (os.path.relpath(os.path.join(d, f), anims).replace("\\", "/"), open(os.path.join(d, f)).read())
                 for d, _, fs in os.walk(anims) for f in fs)
    want = ["man_big/a_ma_man_big.anims=old", "man_big/gen_a_ma_man_big.anims=old", "npc/a_ma.anims=new",
            "npc/gen_a_ma.anims=old", "player/a_pma.anims=new"]
    if got != want:
        fails.append("pack stage left %s, want %s" % (got, want))


def decode_cases(tmp, fails):
    """A clip is decoded against its actor's skeleton whatever body bakes it, so both bodies share one decode; a clip
    written before the skeleton was recorded is kept only where the old rule (the body's sex) picked the same one"""
    import skyrim_port as sp
    import skyrim_scenes as ss
    for body, cast, want in (("f", {"m"}, "m"), ("m", {"m"}, "m"), ("f", {"m", "f"}, "f"), ("m", set(), "m")):
        if ss.source_sex(body, cast) != want:
            fails.append("source_sex(%s, %s) = %s, want %s" % (body, sorted(cast), ss.source_sex(body, cast), want))
    saved = sp.PORT
    sp.PORT = tmp
    try:
        his = {"file": "a.hkx", "clip": "a", "sex": "m", "srcSex": "m"}
        hers = {**his, "sex": "f"}
        if sp.decoded_path(his) != sp.decoded_path(hers):
            fails.append("a man's clip baked on her body is decoded apart from his")
        if sp.decoded_path(his) == sp.decoded_path({**his, "srcSex": "f"}):
            fails.append("one decode for two skeletons")
        old = os.path.join(tmp, "old.npz")
        np.savez(old, rot=np.zeros(1), tra=np.zeros(1))
        if not sp.clip_done(his, old, ()) or sp.clip_done(hers, old, ()):
            fails.append("a pre-skeleton clip: kept on the actor's body %s, kept on the other %s"
                         % (sp.clip_done(his, old, ()), sp.clip_done(hers, old, ())))
        new = os.path.join(tmp, "new.npz")
        np.savez(new, rot=np.zeros(1), tra=np.zeros(1), skeleton="male242.hkx")
        if not sp.clip_done(hers, new, ()):
            fails.append("her copy decoded against his skeleton is not kept")
        src = os.path.join(tmp, "src.hkx")
        open(src, "w").close()
        os.utime(src, (os.path.getmtime(new) + 10,) * 2)
        if sp.clip_done(hers, new, (src,)):
            fails.append("a clip older than its source is kept")
    finally:
        sp.PORT = saved


def main():
    fails = []
    with tempfile.TemporaryDirectory() as tmp:
        tagfile_cases(tmp, fails)
        scene_cases(tmp, fails)
        pack_cases(tmp, fails)
        decode_cases(tmp, fails)
    skeleton_cases(fails)
    axis_cases(fails)
    if fails:
        print("FAIL\n  " + "\n  ".join(fails))
        sys.exit(1)
    print("OK  skyrim port readers")


if __name__ == "__main__":
    main()
