"""A Skyrim skeleton padded to a clip's 242 tracks, as the 32-bit packfile blender-hkx decodes against.

OpenSex's clips carry the 99 core bones and then 143 physics, hair and cloak tracks; blender-hkx writes zero
frames for a clip with more tracks than its skeleton has bones. The dummies hang off bone 0 at identity, so
the real bones keep their rest pose. The core 99 come first in both, in the same order.

Run: python tools/retarget/skyrim_skeleton.py <hkxc.exe> <skeleton.hkx> <a 242-track OpenSex clip> <out.hkx>
"""
import os
import re
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET


def grow(block, param, n, k, add):
    m = re.search(r'(<hkparam name="%s" numelements=")(\d+)(">)(.*?)(\n\t\t\t</hkparam>)' % param, block, re.S)
    if not m or int(m.group(2)) != n:
        raise ValueError("skeleton has no %d-long %s" % (n, param))
    return block[:m.start()] + m.group(1) + str(n + k) + m.group(3) + m.group(4) + add + m.group(5) + block[m.end():]


def pad(text, names):
    start = text.index('class="hkaSkeleton"')
    end = text.find('class="hkaSkeleton"', start + 1)
    end = len(text) if end < 0 else end
    skel = text[start:end]
    n = int(re.search(r'name="bones" numelements="(\d+)"', skel).group(1))
    bones = skel[skel.index('<hkparam name="bones"'):]
    have = re.findall(r'<hkparam name="name">([^<]*)</hkparam>', bones)[:n]
    if [x.lower() for x in names[:n]] != [x.lower() for x in have]:  # the clips write SHIELD for Shield
        raise ValueError("the clip's first %d tracks are not the skeleton's bones" % n)
    extra = names[n:]
    k = len(extra)
    skel = grow(skel, "parentIndices", n, k, "\n\t\t\t\t" + " ".join(["0"] * k) if k else "")
    skel = grow(skel, "bones", n, k, "".join(
        "\n\t\t\t\t<hkobject>\n\t\t\t\t\t<hkparam name=\"name\">%s</hkparam>\n"
        "\t\t\t\t\t<hkparam name=\"lockTranslation\">false</hkparam>\n\t\t\t\t</hkobject>" % nm for nm in extra))
    skel = grow(skel, "referencePose", n, k, "".join(
        "\n\t\t\t\t(0.000000 0.000000 0.000000)(0.000000 0.000000 0.000000 1.000000)(1.000000 1.000000 1.000000)"
        for _ in extra))
    return text[:start] + skel + text[end:], n, k


def run(*args):
    r = subprocess.run(list(args), capture_output=True, text=True, env={**os.environ, "RAYON_NUM_THREADS": "4"})
    if r.returncode != 0:
        raise RuntimeError("%s failed:\n%s%s" % (" ".join(args), r.stdout, r.stderr))


def track_names(hkxc, clip, tmp):
    """a clip's track names: an OpenSex XML clip read as is, a packfile (SexLab's) through hkxc's XML"""
    if open(clip, "rb").read(5) == b"<?xml":
        return [e.text or "" for e in ET.parse(clip).getroot().iter("string") if e.get("name") == "trackName"]
    xml = os.path.join(tmp, "clip.xml")
    run(hkxc, "convert", "-i", clip, "-o", xml, "-v", "xml")
    return re.findall(r'<hkparam name="trackName">([^<]*)</hkparam>', open(xml, encoding="utf-8").read())


def main():
    if len(sys.argv) != 5:
        sys.exit(__doc__)
    hkxc, skeleton, clip, out = sys.argv[1:5]
    with tempfile.TemporaryDirectory() as tmp:
        names = track_names(hkxc, clip, tmp)
        xml = os.path.join(tmp, "skeleton.xml")
        run(hkxc, "convert", "-i", skeleton, "-o", xml, "-v", "xml")
        text, n, k = pad(open(xml, encoding="utf-8").read(), names)
        padded = os.path.join(tmp, "padded.xml")
        open(padded, "w", encoding="utf-8").write(text)
        run(hkxc, "convert", "-i", padded, "-o", out, "-v", "win32")
    print("%s: %d bones + %d dummies -> %s" % (skeleton, n, k, out))


if __name__ == "__main__":
    main()
