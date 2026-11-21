"""Headless: a body on a run's whole.glb, a PNG per frame from two cameras.

mb_transition.ps1 -Preview runs it. RUN is the run folder, RIG the body; STILL=<frame> renders only that frame.
"""
import json
import math
import os
import sys

import bpy
from i_scene_cp77_gltf.importers.import_with_materials import CP77GLBimport
from mathutils import Vector

BODY = os.path.join(os.path.dirname(os.path.abspath(__file__)), "work", "body", "glb")
MESH = {"man_base": "t0_000_ma_base__full.glb", "woman_base": "t0_000_wa_base__full.glb",
        "man_big": "t0_000_mb_base__full.glb", "man_fat": "t0_000_mf_base__full.glb"}
RUN = os.environ["RUN"]
OUT = os.path.join(RUN, "frames")
with open(os.path.join(RUN, "whole.json"), encoding="utf-8") as f:
    parts = json.load(f)
COUNT = parts["a"] + parts["gen"] + parts["b"]

for o in list(bpy.data.objects):
    bpy.data.objects.remove(o)
scene = bpy.context.scene


def imported(fn):
    before, acts = set(bpy.data.objects), set(bpy.data.actions)
    fn()
    return [o for o in bpy.data.objects if o not in before], [a for a in bpy.data.actions if a not in acts]


mesh_objs, _ = imported(lambda: CP77GLBimport(with_materials=False, filepath=os.path.join(BODY, MESH[os.environ["RIG"]]),
                                              scripting=True, hide_armatures=False))
anim_objs, acts = imported(lambda: CP77GLBimport(filepath=os.path.join(RUN, "whole.glb"), scripting=True,
                                                 hide_armatures=False))
rig = next(o for o in anim_objs if o.type == "ARMATURE")
act = next(a for a in acts if a.name.startswith("whole"))
for o in anim_objs:
    if o is not rig:
        bpy.data.objects.remove(o)
ad = rig.animation_data or rig.animation_data_create()
for t in list(ad.nla_tracks):
    ad.nla_tracks.remove(t)
ad.action = act
if ad.action_slot is None and ad.action_suitable_slots:
    ad.action_slot = ad.action_suitable_slots[0]
curves = act.fcurves if hasattr(act, "fcurves") else act.layers[0].strips[0].channelbag(ad.action_slot).fcurves
for fc in [c for c in curves if c.data_path.startswith('pose.bones["Root"]')]:
    curves.remove(fc)
rig.pose.bones["Root"].rotation_quaternion = (1, 0, 0, 0)
rig.pose.bones["Root"].location = (0, 0, 0)

rig_bones = set(rig.data.bones.keys())
body_rig = next(o for o in mesh_objs if o.type == "ARMATURE")
extra = [(b.name, b.head_local.copy(), b.tail_local.copy(), b.matrix_local.copy())
         for b in body_rig.data.bones if b.name not in rig_bones]
bpy.context.view_layer.objects.active = rig
bpy.ops.object.mode_set(mode="EDIT")
ebs = rig.data.edit_bones
anim_bones = [b for b in ebs if b.name in rig_bones]


def seg_dist(b, p):
    kids = [c for c in b.children if c.name in rig_bones]
    end = kids[0].head if kids else b.tail
    d = end - b.head
    f = max(0.0, min(1.0, (p - b.head).dot(d) / max(d.length_squared, 1e-9)))
    return (b.head + d * f - p).length


for name, head, tail, mat in extra:
    nb = ebs.new(name)
    nb.head, nb.tail = head, tail
    nb.align_roll(mat.to_3x3().col[2])
    nb.parent = min(anim_bones, key=lambda d: seg_dist(d, head))
bpy.ops.object.mode_set(mode="OBJECT")
for o in mesh_objs:
    if o.type == "MESH":
        for m in o.modifiers:
            if m.type == "ARMATURE":
                m.object = rig
        o.parent = rig
        o.matrix_parent_inverse.identity()
bpy.data.objects.remove(body_rig)
rig.hide_render = True

bpy.ops.mesh.primitive_plane_add(size=8, location=(0, 0, 0))

scene.render.engine = "BLENDER_WORKBENCH"
scene.display.shading.light = "STUDIO"
scene.display.shading.show_shadows = True
scene.display.shading.color_type = "SINGLE"
scene.display.shading.single_color = (0.75, 0.72, 0.68)
scene.render.resolution_x, scene.render.resolution_y = 540, 540
scene.render.image_settings.file_format = "PNG"
scene.render.film_transparent = False

bpy.context.view_layer.update()
first, last = act.frame_range
scene.frame_set(int(first))
head = rig.matrix_world @ rig.pose.bones["Hips"].head
focus = Vector((head.x, head.y, 0.45))


def camera(name, angle):
    cam_d = bpy.data.cameras.new(name)
    cam_d.lens = 50
    cam = bpy.data.objects.new(name, cam_d)
    scene.collection.objects.link(cam)
    r = 3.2
    cam.location = focus + Vector((math.cos(angle) * r, math.sin(angle) * r, 0.5))
    cam.rotation_euler = (focus - cam.location).to_track_quat("-Z", "Y").to_euler()
    return cam


os.makedirs(OUT, exist_ok=True)
cams = {"side": camera("side", 0.0), "quarter": camera("quarter", math.radians(-55))}
still = os.environ.get("STILL")
for i in ([int(still)] if still else range(COUNT)):
    scene.frame_float = first + (last - first) * i / (COUNT - 1)
    scene.frame_set(int(scene.frame_float), subframe=scene.frame_float % 1)
    for name, cam in cams.items():
        scene.camera = cam
        scene.render.filepath = os.path.join(OUT, "%s_%03d.png" % (name, i))
        bpy.ops.render.render(write_still=True)
print("DONE")
sys.stdout.flush()
