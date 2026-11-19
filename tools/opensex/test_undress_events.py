#!/usr/bin/env python3
"""test_undress_events.py -- the packs' Skyrim slot masks as our clothing slots, and the annotation read.

docs/design/scene-undress.md §1.1: each mask below is the one an undress clip carries. Run by tools/py_test.ps1; no
clip, no hkxc -- the annotation is read from an XML fragment written here.
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import undress_events as ue  # noqa: E402

fails = checks = 0


def check(cond, what):
    global fails, checks
    checks += 1
    print(("  ok   " if cond else "  FAIL ") + what)
    if not cond:
        fails += 1


check(ue.ours_of(0x4010004) == (["outer", "inner"], []), "top: body 32, 46, 56 -> outer + inner")
check(ue.ours_of(0xC80000) == (["legs"], []), "bottom: 49, 52, 53 -> legs")
check(ue.ours_of(0x80) == (["feet"], []), "shoes: 37 -> feet")
check(ue.ours_of(0x2005003) == (["head", "eyes"], []), "head item: 30, 31, 42, 44, 55 -> head + eyes")
check(ue.ours_of(0x2C90004) == (["outer", "inner", "legs"], []), "his bottom: 32 + pelvis + legs")
check(ue.ours_of(0x8) == ([], []), "gloves: hands is known and has nothing of ours")
check(ue.ours_of(1 << 15) == ([], [45]), "a slot with no row is reported, not dropped quietly")

def scene(sid, n, acts=None, mods=None):
    return {"id": sid, "actors": [{"mods": (mods or {}).get(i, [])} for i in range(n)], "acts": acts or []}


B = ["outer", "inner", "legs"]
check(ue.strip_of(scene("ostimng.x", 2, [{"type": "penetrative", "actor": "a", "target": "b"}])) == [B, B],
      "penetrative: both bodies")
check(ue.strip_of(scene("ostimng.x", 2, [{"type": "oral_penis", "actor": "b", "target": "a"}])) == [B, ["head", "eyes"]],
      "oral: the receiver's body, the giver's head")
check(ue.strip_of(scene("ostimng.x", 2, [{"type": "manual", "actor": "a", "target": "b"}])) == [[], B],
      "manual: the receiver only")
check(ue.strip_of(scene("ostimng.x", 2, [{"type": "manual", "actor": "a", "target": "a"}])) == [B, B],
      "only a self-touch (a jerk to her face): both bodies")
check(ue.strip_of(scene("ostimng.x", 2, [{"type": "manual", "actor": "a", "target": "a"},
                                          {"type": "oral_penis", "actor": "b", "target": "a"}])) == [B, ["head", "eyes"]],
      "a self-touch beside an act on him: the act decides")
check(ue.strip_of(scene("opensex.ops.3p-lying.sx.x", 3)) == [B, B, B], "an OpenSex sex class with no acts: everyone")
check(ue.strip_of(scene("opensex.ops.3p-lying.em.x", 3)) == [[], [], []], "an embrace: nobody")
check(ue.strip_of(dict(scene("ostimng.x", 2), tags=["missionary"])) == [B, B], "a sex-position tag with no acts: everyone")
check(ue.strip_of(scene("opensex.ops.x.sx.y", 2, mods={1: ["nostrip"]})) == [B, []], "nostrip keeps that actor dressed")

with tempfile.TemporaryDirectory() as tmp:
    p = os.path.join(tmp, "clip.hkx")
    with open(p, "w", encoding="utf-8") as fh:
        fh.write('<?xml version="1.0"?><hkparam name="time">0.000000</hkparam><hkparam name="text">FootLeft</hkparam>'
                 '<hkparam name="time">2.000000</hkparam>\n  <hkparam name="text">OStimUndressPartial.0x4010004</hkparam>')
    check(ue.annotations("unused", p, tmp) == [(2.0, 0x4010004)], "an XML clip's undress annotation: its time and mask")

print("%d checks, %d failures" % (checks, fails))
sys.exit(1 if fails else 0)
