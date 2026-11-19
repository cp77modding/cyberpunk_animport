"""scene_files' licking rule on made-up acts: no packs, no OStimNG checkout.

Run: python tools/opensex/test_scene_files.py (also from tools/py_test.ps1).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import scene_files as sf  # noqa: E402

fails = []


def check(cond, msg):
    print(("  ok   " if cond else "  FAIL ") + msg)
    if not cond:
        fails.append(msg)


bj = [{"type": "oral_penis", "actor": "b", "target": "a"}]
cl = [{"type": "oral_vagina", "actor": "a", "target": "b"}]
licks = lambda *ids: any(sf.LICK_WORDS.search(i) for i in ids)  # noqa: E731

check(sf.lick_mouth(bj, licks("OStim2PKneelingLickingPenisMF")) == {"b": "lollipop"},
      "OStimNG's licking scene: the giver licks the shaft")
check(sf.lick_mouth(bj, licks("OpS|Sta!Kne|BJ|KneelingTongueFellatio")) == {"b": "lollipop"},
      "a tongue in OpenSex's id licks too")
check(sf.lick_mouth(bj, licks("OStim2PKneelingBlowjobMF", "OpS|Sta!Kne|BJ|KneelingFellatioEyeContact")) == {},
      "a blowjob sucks: the act's mouth, no tongue")
check(sf.lick_mouth(cl, licks("OStim2PLickingVaginaMF")) == {}, "cunnilingus licks through its act's own mouth")
check(sf.lick_mouth([], licks("OpS|Sta!Sta|Ho|TongueKiss")) == {}, "a scene with no act holds no mouth")
check(sf.lick_mouth(bj, licks("OpS|Sta!Kne|BJ|KneelingFellatio", "OpS|Sta!Sta|Ho|TongueKiss")) == {},
      "a blowjob merged with a tongue kiss still sucks")
check(sf.lick_mouth(bj, licks("OpS|Sta!Kne|BJ|ClickFellatio")) == {}, "the lick in Click is no lick")
check(sf.lick_mouth(bj, licks("ostim_licking_penis")) == {"b": "lollipop"}, "a lowercase lick on its own licks")

ff = [{"sex": "f"}, {"sex": "f"}]
check(sf.os_acts({"id": "OpS|Kne!LyB|VJ|LesbianKneLyBCunnilingus", "actors": ff})
      == [{"type": "oral_vagina", "actor": "b", "target": "a"}],
      "the lesbian kneeling cunnilingus: the lying actor licks, as its clips do")
check(sf.os_acts({"id": "OpS|Kne!Sta|VJ|KneelingCL", "actors": [{"sex": "m"}, {"sex": "f"}]})
      == [{"type": "oral_vagina", "actor": "a", "target": "b"}], "a man and a woman: the man gives cunnilingus")

have = {"p/a_s1_0", "p/a_s1_1", "p/a_s2_0", "p/a_s2_1", "p/a_s3_0", "p/a_s3_1"}
sp = lambda n, d, rate=1.0: {"clips": ["p/a_s%d_0" % n, "p/a_s%d_1" % n] if n else ["p/gone_0", "p/gone_1"],  # noqa: E731
                             "playback": rate, "display": d}
shown = lambda out: [(s["clips"][0], s["display"]) for s in out]  # noqa: E731
r = sf.Counter()
check(shown(sf.stages([sp(1, None), sp(1, 1.0), sp(2, 1.5)], 2, have, r)) == [("p/a_s1_0", 1.0), ("p/a_s2_0", 1.5)],
      "Standing Sex: a start anim filled as the first speed is that speed, kept with its shown speed")
check(shown(sf.stages([sp(1, 0.5), sp(3, 2.0), sp(3, 3.0)], 2, have, r)) == [("p/a_s1_0", 0.5), ("p/a_s3_0", 2.0)],
      "Prone: a speed naming a slower one's anim is dropped")
check(len(sf.stages([sp(3, 2.0), sp(3, 3.0, 1.5)], 2, have, r)) == 2, "the same clips at another rate is a stage")
check(shown(sf.stages([sp(0, None), sp(1, 0.5)], 2, have, r)) == [("p/a_s1_0", 0.5)],
      "an anim with no file for anybody takes the first speed's and is one with it")

import json  # noqa: E402
import tempfile  # noqa: E402

with tempfile.TemporaryDirectory() as tmp:
    for rel, text in {"os/a.xml": '<actions>\n<action type="thighjob" actor="1" target="0" performer="0"/>\n</actions>',
                      "ng/b.json": json.dumps({"actions": [{"type": "handjob", "actor": 1, "target": 0},
                                                           {"type": "malemasturbation", "actor": 0}]})}.items():
        os.makedirs(os.path.join(tmp, os.path.dirname(rel)), exist_ok=True)
        with open(os.path.join(tmp, rel), "w", encoding="utf-8") as fh:
            fh.write(text)
    src = lambda pack, f: {"pack": pack, "file": f}  # noqa: E731
    man = lambda: [{"type": "manual", "actor": "b", "target": "a"}, {"type": "manual", "actor": "a", "target": "a"}]  # noqa: E731
    notes = []
    s = {"id": "x", "sources": [src("opensex", "os/a.xml")], "acts": man()}
    check(sf.mark_with(s, tmp, tmp, notes) and s["acts"][0]["with"] == "thighs" and "with" not in s["acts"][1]
          and len(notes) == 1, "OpenSex: the scene XML's own action names the part; an act it does not name is noted")
    s = {"id": "y", "sources": [src("ostimng", "ng/b.json")], "acts": man()}
    check(sf.mark_with(s, tmp, tmp, []) and [a["with"] for a in s["acts"]] == ["hand", "hand"],
          "OStimNG: a handjob is a hand, a masturbation the actor's own")
    check(not sf.mark_with(s, tmp, tmp, []), "marked again changes nothing")
    with open(os.path.join(tmp, "ng/c.json"), "w", encoding="utf-8") as fh:
        fh.write(json.dumps({"actions": [{"type": "analfingering", "actor": 1, "target": 0}]}))
    s = {"id": "z", "sources": [src("ostimng", "ng/c.json")], "acts": man()[:1]}
    check(sf.mark_with(s, tmp, tmp, []) and s["acts"][0]["with"] == "fingers",
          "fingers in an opening are not a hand: a man fingered is never aimed into one")

    for rel, text in {"os/kiss.xml": '<actions>\n<action type="kissing" actor="0" target="1"/>\n'
                                     '<action type="vaginalsex" actor="0" target="1"/>\n</actions>',
                      "os/feet.xml": '<actions>\n<action type="kissingfeet" actor="0" target="1"/>\n</actions>',
                      "ng/kiss.json": json.dumps({"actions": [{"type": "kissingneck", "actor": 0, "target": 1},
                                                              {"type": "kissing", "actor": 0, "target": 1}]})}.items():
        with open(os.path.join(tmp, rel), "w", encoding="utf-8") as fh:
            fh.write(text)
    s = {"id": "k", "sources": [src("opensex", "os/kiss.xml")], "acts": []}
    check(sf.mark_kiss(s, tmp, tmp) and s["kiss"] == "mouth", "a kissing action is a mouth kiss, beside a sex act")
    check(not sf.mark_kiss(s, tmp, tmp), "marked again changes nothing")
    s = {"id": "f", "sources": [src("opensex", "os/feet.xml")], "acts": []}
    check(sf.mark_kiss(s, tmp, tmp) and s["kiss"] == "skin", "kissing feet is a kiss on the body")
    s = {"id": "n", "sources": [src("ostimng", "ng/kiss.json")], "acts": []}
    check(sf.mark_kiss(s, tmp, tmp) and s["kiss"] == "mouth", "a mouth kiss wins over a skin one in the same scene")
    s = {"id": "o", "sources": [src("opensex", "os/a.xml")], "acts": [], "kiss": "skin"}
    check(not sf.mark_kiss(s, tmp, tmp) and s["kiss"] == "skin", "no kiss in the sources leaves a hand-set one alone")
    s = {"id": "p", "sources": [src("opensex", "os/a.xml")], "acts": []}
    check(not sf.mark_kiss(s, tmp, tmp) and "kiss" not in s, "and adds none")

print("\n%d failure(s)" % len(fails))
sys.exit(1 if fails else 0)
