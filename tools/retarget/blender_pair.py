"""Blender preview: a PoNC pair on man_base (the original) beside the same pair on an NPC rig's bake.

Each row is one pose: man_base + woman_base on PoNC's own clips, and <rig> on our -Rig bake + the same woman.
Reads the run folders retarget.ps1 leaves under work/run and the body glbs under work/body/glb (README, "Seeing
a pair in Blender"). No materials: shape is what is being checked, and textures made the import 20 minutes.

  set SET=oral& set POSES=oral01_penis_sit_a:oral01_penis_kneel_b,oral05_penis_stand_a:oral05_penis_sit_b
  "C:\\Program Files\\Blender Foundation\\Blender 5.1\\blender.exe" --python tools\\retarget\\blender_pair.py

SET is the PoNC set, POSES is man clip:woman clip per row (_a is the man's half), RIG is man_big (default) or
man_fat. With SHOT=<png> and -b it renders one still at FRAME and exits.
"""
import glob
import os
import sys

import bpy
from i_scene_cp77_gltf.importers.import_with_materials import CP77GLBimport

WORK = os.path.join(os.path.dirname(os.path.abspath(__file__)), "work")
BODY = os.path.join(WORK, "body", "glb")
RUN = os.path.join(WORK, "run")
MESH = {"man_base": "t0_000_ma_base__full.glb", "woman_base": "t0_000_wa_base__full.glb",
        "man_big": "t0_000_mb_base__full.glb", "man_fat": "t0_000_mf_base__full.glb"}
SET = os.environ.get("SET", "missionary")
RIG = os.environ.get("RIG", "man_big")
POSES = [p.split(":") for p in os.environ.get("POSES", "missionary01_lie_a:missionary01_lie_b").split(",")]


def need(path):
    if not os.path.isfile(path):
        sys.exit("missing %s (README, Seeing a pair in Blender)" % path)
    return path


# Every run of a set exports the same source glb; any one will do.
src_m = need(next(iter(glob.glob(os.path.join(RUN, "%s_ma_*" % SET, "%s_ma.anims.glb" % SET))), ""))
src_w = need(next(iter(glob.glob(os.path.join(RUN, "%s_wa_*" % SET, "%s_wa.anims.glb" % SET))), ""))
bake = need(os.path.join(RUN, "%s_ma_%s" % (SET, RIG), "check", "%s_ma_%s.anims.glb" % (SET, RIG)))
SETS = []
for row, (clip_m, clip_w) in enumerate(POSES):
    woman = (need(os.path.join(BODY, MESH["woman_base"])), src_w, clip_w)
    SETS += [("man_base + woman_base (PoNC)  %s" % clip_m, -1.6, row * 3.0,
              [(need(os.path.join(BODY, MESH["man_base"])), src_m, clip_m), woman]),
             ("%s (our bake) + woman_base  %s" % (RIG, clip_m), 1.6, row * 3.0,
              [(need(os.path.join(BODY, MESH[RIG])), bake, clip_m), woman])]

for o in list(bpy.data.objects):
    bpy.data.objects.remove(o)
scene = bpy.context.scene
report = []


def imported(fn):
    before, acts = set(bpy.data.objects), set(bpy.data.actions)
    fn()
    return [o for o in bpy.data.objects if o not in before], [a for a in bpy.data.actions if a not in acts]


def body(mesh_glb, anims_glb, clip, x, y):
    mesh_objs, _ = imported(lambda: CP77GLBimport(with_materials=False, filepath=mesh_glb, scripting=True,
                                                  hide_armatures=False))
    anim_objs, acts = imported(lambda: CP77GLBimport(filepath=anims_glb, scripting=True, hide_armatures=False))
    rig = next((o for o in anim_objs if o.type == "ARMATURE"), None)
    act = next((a for a in acts if a.name.startswith(clip)), None)
    if rig is None or act is None:
        report.append("%s: rig=%s action=%s" % (anims_glb, rig, act))
        return 1
    for o in anim_objs:
        if o is not rig:
            bpy.data.objects.remove(o)
    ad = rig.animation_data or rig.animation_data_create()
    for t in list(ad.nla_tracks):
        ad.nla_tracks.remove(t)
    ad.action = act
    if ad.action_slot is None and ad.action_suitable_slots:
        ad.action_slot = ad.action_suitable_slots[0]
    # PoNC's _wa clips key Root at 180 deg yaw and the game lines the pair up without it; drop Root's track.
    curves = act.fcurves if hasattr(act, "fcurves") else act.layers[0].strips[0].channelbag(ad.action_slot).fcurves
    for fc in [c for c in curves if c.data_path.startswith('pose.bones["Root"]')]:
        curves.remove(fc)
    rig.pose.bones["Root"].rotation_quaternion = (1, 0, 0, 0)
    rig.pose.bones["Root"].location = (0, 0, 0)
    # The plugin's way (cp77.set_armature): the mesh binds to the anim rig. The skin's muscle bones are not in
    # it, so they are copied in at the body's bind and hung off the nearest anim bone.
    rig_bones = set(rig.data.bones.keys())
    body_rig = next((o for o in mesh_objs if o.type == "ARMATURE"), None)
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
    rig.location.x += x
    rig.location.y += y
    rig.hide_set(True)
    report.append("%s %s frames %d-%d" % (os.path.basename(mesh_glb), act.name, act.frame_range[0], act.frame_range[1]))
    return int(act.frame_range[1])


end = 1
for label, x, y, bodies in SETS:
    for mesh_glb, anims_glb, clip in bodies:
        end = max(end, body(mesh_glb, anims_glb, clip, x, y))
    bpy.ops.object.text_add(location=(x, y, 2.2))
    t = bpy.context.object
    t.data.body, t.data.align_x, t.data.size = label, "CENTER", 0.14
    t.rotation_euler = (1.5708, 0, 0)

scene.frame_start, scene.frame_end = 0, end
for line in report:
    print("[pair]", line)

shot = os.environ.get("SHOT")
if bpy.app.background and shot:
    scene.frame_set(int(os.environ.get("FRAME", "30")))
    bpy.ops.object.camera_add(location=(0.5, -8.5, 3.2), rotation=(1.25, 0, 0))
    scene.camera = bpy.context.object
    bpy.ops.object.light_add(type="SUN", location=(0, -3, 5))
    scene.render.engine = "BLENDER_WORKBENCH"
    scene.render.resolution_x, scene.render.resolution_y = 1400, 700
    scene.render.filepath = shot
    bpy.ops.render.render(write_still=True)
    sys.exit(0)


def start():
    for area in bpy.context.screen.areas:
        if area.type == "VIEW_3D":
            area.spaces[0].shading.type = "SOLID"
            with bpy.context.temp_override(area=area, region=area.regions[-1]):
                bpy.ops.view3d.view_all()
    bpy.ops.screen.animation_play()


if not bpy.app.background:
    bpy.app.timers.register(start, first_interval=1.5)
