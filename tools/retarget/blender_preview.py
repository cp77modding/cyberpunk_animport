"""Blender preview: the NPC body playing PoNC's clip beside V's body playing our retarget of it.

Needs the Cyberpunk IO Suite add-on (i_scene_cp77_gltf) and the body glbs under work/body/glb (WolvenKit
mesh export with materials). V's arms are their own mesh and are not shown yet: their bind holds the hand
about 52 cm from the anim rig's rest, so binding them to the anim rig breaks them (player-rig-retarget.md).

Run: "C:\\Program Files\\Blender Foundation\\Blender 5.1\\blender.exe" --python tools\\retarget\\blender_preview.py
"""
import os

import bpy
from i_scene_cp77_gltf.importers.import_with_materials import CP77GLBimport

W = os.path.join(os.path.dirname(os.path.abspath(__file__)), "work")
CLIP = "missionary01_lie_a"
SETS = [
    ("NPC body + PoNC original", W + r"\body\glb\t0_000_wa_base__full.glb",
     W + r"\run\missionary_wa_player\missionary_wa.anims.glb", -1.2),
    ("V body + our retarget (cooked file)", W + r"\body\glb\t0_000_pwa_base__full.glb",
     W + r"\run\missionary_wa_player\check\missionary_wa_player.anims.glb", 1.2),
]

for o in list(bpy.data.objects):
    bpy.data.objects.remove(o)
scene = bpy.context.scene
report = []


def imported(fn):
    before = set(bpy.data.objects)
    acts = set(bpy.data.actions)
    fn()
    return [o for o in bpy.data.objects if o not in before], [a for a in bpy.data.actions if a not in acts]


end = 1
MAIN = set()
for label, mesh_glb, anims_glb, x in SETS:
    mesh_objs, _ = imported(lambda: CP77GLBimport(with_materials=True, filepath=mesh_glb, scripting=True,
                                                  hide_armatures=False, appearances=["ALL"]))
    anim_objs, acts = imported(lambda: CP77GLBimport(filepath=anims_glb, scripting=True, hide_armatures=False))
    rig = next((o for o in anim_objs if o.type == "ARMATURE"), None)
    act = next((a for a in acts if a.name.startswith(CLIP)), None)
    if rig is None or act is None:
        report.append("%s: rig=%s action=%s" % (label, rig, act))
        continue
    ad = rig.animation_data or rig.animation_data_create()
    for t in list(ad.nla_tracks):
        ad.nla_tracks.remove(t)
    ad.action = act
    if ad.action_slot is None and ad.action_suitable_slots:
        ad.action_slot = ad.action_suitable_slots[0]
    # The plugin's way (cp77.set_armature): the mesh binds to the anim rig. The skin's muscle bones are not in
    # it, so they are copied in at the body's bind and hung off the nearest anim bone.
    rig_bones = set(rig.data.bones.keys())
    body_rig = next((o for o in mesh_objs if o.type == "ARMATURE"), None)
    if body_rig is None:
        report.append("%s: %s has no armature" % (label, mesh_glb))
        continue
    extra = [(b.name, b.head_local.copy(), b.tail_local.copy(), b.matrix_local.copy())
             for b in body_rig.data.bones if b.name not in rig_bones]
    bpy.context.view_layer.objects.active = rig
    bpy.ops.object.mode_set(mode="EDIT")
    ebs = rig.data.edit_bones
    # The skin hangs off the NPC rig's bones only; V's IK and control joints carry no skin.
    MAIN.update(() if MAIN else rig_bones)
    anim_bones = [b for b in ebs if b.name in MAIN]

    def seg_dist(b, p):
        kids = [c for c in b.children if c.name in MAIN]
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
    rig.hide_set(True)
    followed, missing = len(rig_bones), extra
    s, e = act.frame_range
    end = max(end, int(e))
    bpy.ops.object.text_add(location=(x, 0, 2.3))
    t = bpy.context.object
    t.data.body, t.data.align_x, t.data.size = label, "CENTER", 0.12
    t.rotation_euler = (1.5708, 0, 0)
    report.append("%s: %s frames %d-%d, body bones following the anim: %d, not in anim rig: %d"
                  % (label, act.name, s, e, followed, len(missing)))

scene.frame_start, scene.frame_end = 0, end
for line in report:
    print("[show_bodies]", line)


def start():
    for area in bpy.context.screen.areas:
        if area.type == "VIEW_3D":
            area.spaces[0].shading.type = "MATERIAL"
            with bpy.context.temp_override(area=area, region=area.regions[-1]):
                bpy.ops.view3d.view_all()
    bpy.ops.screen.animation_play()


if not bpy.app.background:
    bpy.app.timers.register(start, first_interval=1.5)
