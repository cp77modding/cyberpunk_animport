"""A Havok 2010 tagfile XML animation (OpenSex's .hkx) rewritten as the packfile XML hkxc reads.

hkxc turns that into a 32-bit packfile, which blender-hkx decodes. Only the objects a spline-compressed clip
holds are carried: root container, animation container, binding, the clip and its reference frame. A tagfile
leaves out every member at its default, so a missing int is 0 and a missing array empty.

Run: python tools/retarget/skyrim_tagfile.py <in.hkx> <out.xml>
"""
import struct
import sys
import xml.etree.ElementTree as ET
from xml.sax.saxutils import escape

# hkaAnimation::AnimationType as hkxc names it for hk_2010.2.0-r1 (value 3 is the spline clip OpenSex ships).
ANIM_TYPE = {3: "HK_WAVELET_COMPRESSED_ANIMATION"}
BLEND = {0: "NORMAL", 1: "ADDITIVE"}


def real(text):
    tok = text.split()[0]
    return struct.unpack(">f", bytes.fromhex(tok[1:]))[0] if tok.startswith("x") else float(tok)


def fmt(v):
    return "%.9g" % v


def vec(el):
    return [real(t) for t in el.text.split() if t.startswith("x") or t[:1].isdigit() or t[:1] == "-"]


class Obj:
    def __init__(self, el):
        self.type = el.get("type")
        self.m = {c.get("name"): c for c in el}

    def int(self, name):
        el = self.m.get(name)
        return int(el.text) if el is not None else 0

    def real(self, name):
        el = self.m.get(name)
        return real(el.text) if el is not None else 0.0

    def text(self, name, default=""):
        el = self.m.get(name)
        return el.text or "" if el is not None else default

    def ints(self, name):
        el = self.m.get(name)
        return el.text.split() if el is not None and el.text else []

    def items(self, name):
        el = self.m.get(name)
        return list(el) if el is not None else []


def load(path):
    root = ET.parse(path).getroot()
    if root.tag != "hktagfile":
        raise ValueError("%s: not a Havok tagfile (%s)" % (path, root.tag))
    objs = {o.get("id"): Obj(o) for o in root.iter("object")}
    by_type = {}
    for oid, o in objs.items():
        by_type.setdefault(o.type, []).append(oid)
    return objs, by_type


def one(by_type, kind, path):
    ids = by_type.get(kind, [])
    if len(ids) != 1:
        raise ValueError("%s: %d %s objects, want 1" % (path, len(ids), kind))
    return ids[0]


def block(values, per_line=16):
    return "\n".join("\t\t\t\t" + " ".join(values[i:i + per_line]) for i in range(0, len(values), per_line))


def param_list(name, values):
    if not values:
        return '\t\t\t<hkparam name="%s" numelements="0"></hkparam>' % name
    return '\t\t\t<hkparam name="%s" numelements="%d">\n%s\n\t\t\t</hkparam>' % (name, len(values), block(values))


def convert(path):
    objs, by_type = load(path)
    anim = objs[one(by_type, "hkaSplineCompressedAnimation", path)]
    bind = objs[one(by_type, "hkaAnimationBinding", path)]
    ref_id = anim.text("extractedMotion").strip()
    t = anim.int("type")
    if t not in ANIM_TYPE:
        raise ValueError("%s: animation type %d is not a spline clip" % (path, t))
    out = ['<?xml version="1.0" encoding="ascii"?>',
           '<hkpackfile classversion="8" contentsversion="hk_2010.2.0-r1" toplevelobject="#0001">', "",
           '\t<hksection name="__data__">', ""]
    motion = "null"
    if ref_id and ref_id in objs:
        rf = objs[ref_id]
        if rf.type != "hkaDefaultAnimatedReferenceFrame":
            raise ValueError("%s: extracted motion is a %s" % (path, rf.type))
        motion = "#0004"
        samples = ["(%s)" % " ".join(fmt(v) for v in vec(s)) for s in rf.items("referenceFrameSamples")]
        out += ['\t\t<hkobject name="#0004" class="hkaDefaultAnimatedReferenceFrame" signature="0x6d85e445">',
                '\t\t\t<hkparam name="up">(%s)</hkparam>' % " ".join(fmt(v) for v in vec(rf.m["up"])),
                '\t\t\t<hkparam name="forward">(%s)</hkparam>' % " ".join(fmt(v) for v in vec(rf.m["forward"])),
                '\t\t\t<hkparam name="duration">%s</hkparam>' % fmt(rf.real("duration")),
                param_list("referenceFrameSamples", samples),
                "\t\t</hkobject>", ""]
    tracks = []
    for ref in anim.items("annotationTracks"):
        tr = objs[ref.text.strip()]
        notes = []
        for st in tr.items("annotations"):
            s = {c.get("name"): c for c in st}
            tm = real(s["time"].text) if "time" in s else 0.0
            notes.append("\t\t\t\t\t\t<hkobject>\n\t\t\t\t\t\t\t<hkparam name=\"time\">%s</hkparam>\n"
                         "\t\t\t\t\t\t\t<hkparam name=\"text\">%s</hkparam>\n\t\t\t\t\t\t</hkobject>"
                         % (fmt(tm), escape(s["text"].text or "") if "text" in s else ""))
        ann = ('\t\t\t\t\t<hkparam name="annotations" numelements="%d">\n%s\n\t\t\t\t\t</hkparam>' % (len(notes), "\n".join(notes))
               if notes else '\t\t\t\t\t<hkparam name="annotations" numelements="0"></hkparam>')
        tracks.append("\t\t\t\t<hkobject>\n\t\t\t\t\t<hkparam name=\"trackName\">%s</hkparam>\n%s\n\t\t\t\t</hkobject>"
                      % (escape(tr.text("trackName")), ann))
    n_tracks = anim.int("numberOfTransformTracks")
    if tracks and len(tracks) != n_tracks:
        raise ValueError("%s: %d annotation tracks for %d transform tracks" % (path, len(tracks), n_tracks))
    out += ['\t\t<hkobject name="#0003" class="hkaSplineCompressedAnimation" signature="0x792ee0bb">',
            '\t\t\t<hkparam name="type">%s</hkparam>' % ANIM_TYPE[t],
            '\t\t\t<hkparam name="duration">%s</hkparam>' % fmt(anim.real("duration")),
            '\t\t\t<hkparam name="numberOfTransformTracks">%d</hkparam>' % n_tracks,
            '\t\t\t<hkparam name="numberOfFloatTracks">%d</hkparam>' % anim.int("numberOfFloatTracks"),
            '\t\t\t<hkparam name="extractedMotion">%s</hkparam>' % motion,
            ('\t\t\t<hkparam name="annotationTracks" numelements="%d">\n%s\n\t\t\t</hkparam>' % (len(tracks), "\n".join(tracks))
             if tracks else '\t\t\t<hkparam name="annotationTracks" numelements="0"></hkparam>')]
    for k in ("numFrames", "numBlocks", "maxFramesPerBlock", "maskAndQuantizationSize"):
        out.append('\t\t\t<hkparam name="%s">%d</hkparam>' % (k, anim.int(k)))
    for k in ("blockDuration", "blockInverseDuration", "frameDuration"):
        out.append('\t\t\t<hkparam name="%s">%s</hkparam>' % (k, fmt(anim.real(k))))
    for k in ("blockOffsets", "floatBlockOffsets", "transformOffsets", "floatOffsets", "data"):
        out.append(param_list(k, anim.ints(k)))
    out += ['\t\t\t<hkparam name="endian">%d</hkparam>' % anim.int("endian"), "\t\t</hkobject>", "",
            '\t\t<hkobject name="#0005" class="hkaAnimationBinding" signature="0x66eac971">',
            '\t\t\t<hkparam name="originalSkeletonName">%s</hkparam>' % escape(bind.text("originalSkeletonName")),
            '\t\t\t<hkparam name="animation">#0003</hkparam>',
            param_list("transformTrackToBoneIndices", bind.ints("transformTrackToBoneIndices")),
            param_list("floatTrackToFloatSlotIndices", bind.ints("floatTrackToFloatSlotIndices")),
            '\t\t\t<hkparam name="blendHint">%s</hkparam>' % BLEND[bind.int("blendHint")],
            "\t\t</hkobject>", "",
            '\t\t<hkobject name="#0002" class="hkaAnimationContainer" signature="0x8dc20333">',
            '\t\t\t<hkparam name="skeletons" numelements="0"></hkparam>',
            '\t\t\t<hkparam name="animations" numelements="1">\n\t\t\t\t#0003\n\t\t\t</hkparam>',
            '\t\t\t<hkparam name="bindings" numelements="1">\n\t\t\t\t#0005\n\t\t\t</hkparam>',
            '\t\t\t<hkparam name="attachments" numelements="0"></hkparam>',
            '\t\t\t<hkparam name="skins" numelements="0"></hkparam>',
            "\t\t</hkobject>", "",
            '\t\t<hkobject name="#0001" class="hkRootLevelContainer" signature="0x2772c11e">',
            '\t\t\t<hkparam name="namedVariants" numelements="1">',
            '\t\t\t\t<hkobject>\n\t\t\t\t\t<hkparam name="name">Merged Animation Container</hkparam>',
            '\t\t\t\t\t<hkparam name="className">hkaAnimationContainer</hkparam>',
            '\t\t\t\t\t<hkparam name="variant">#0002</hkparam>\n\t\t\t\t</hkobject>',
            "\t\t\t</hkparam>", "\t\t</hkobject>", "", "\t</hksection>", "", "</hkpackfile>", ""]
    return "\n".join(out)


def main():
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    with open(sys.argv[2], "w", encoding="ascii", newline="\n") as fh:
        fh.write(convert(sys.argv[1]))


if __name__ == "__main__":
    main()
