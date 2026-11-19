"""Generate a transition between two Cyberpunk clips with MotionBricks' SOMA engine: a glb on the Cyberpunk rig.

mb_transition.ps1 is the way in. It runs this from the MotionBricks clone, with the clone's venv:
  python mb_transition.py <a.glb> <a clip> <b.glb> <b clip> <rig.json> <clip name> <out dir> [--tokens 8,9,...]
Exits 1 when a transition fails the seam or speed limit. docs/design/generated-motion.md §7.
"""
import argparse
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mb_soma as ms  # noqa: E402
import retarget_glb as rg  # noqa: E402
import warp as wp  # noqa: E402
from motionbricks.io.usd import load_skeleton_from_usd  # noqa: E402
from motionbricks.io.utils import SOMA_SKELETON_PRIM_PATH, get_asset_file  # noqa: E402
from motionbricks.model.config import MotionBricksInferenceConfig  # noqa: E402
from motionbricks.model.soma.contract import SOMA_N1_FP32_ONNX_PATH  # noqa: E402
from motionbricks.model.soma.engine import MotionBricksSOMAEngine  # noqa: E402


def load_soma():
    sk = load_skeleton_from_usd(get_asset_file("human", "soma_base_skel_minimal_no_root.usd"), SOMA_SKELETON_PRIM_PATH)
    par = sk.parent_indices
    ref = sk.reference_local_transforms.numpy()
    return sk, ms.Soma(sk.joint_names, par.numpy() if hasattr(par, "numpy") else par, ref[:, :3], ref[:, 3:])


class Generator:
    """The model, held open: one call per transition, so a batch pays for the load once."""

    def __init__(self, skeleton, device):
        wp.init()
        wp.set_device(device)
        self.engine = MotionBricksSOMAEngine(SOMA_N1_FP32_ONNX_PATH)
        self.skeleton = skeleton

    def __enter__(self):
        self.engine.__enter__()
        self.scope = wp.ScopedStream(self.engine.stream)
        self.scope.__enter__()
        e = self.engine
        self.ctx, self.tgt = e.create_input(self.skeleton), e.create_input(self.skeleton)
        self.out = e.create_output(self.skeleton)
        return self

    def __exit__(self, *exc):
        self.scope.__exit__(*exc)
        return self.engine.__exit__(*exc)

    def __call__(self, context, target, tokens):
        """(poses, foot contacts) from two SOMA pose arrays; tokens are the lengths the model may pick."""
        e = self.engine
        self.ctx.update_from_poses(wp.array(context, dtype=wp.transform, device=e.device), stream=e.stream)
        self.tgt.update_from_poses(wp.array(target, dtype=wp.transform, device=e.device), stream=e.stream)
        e.generate_animation(self.ctx, self.tgt, self.out,
                             config=MotionBricksInferenceConfig(allowed_token_counts=tuple(tokens)))
        e.synchronize()
        n = self.out.num_frames
        return self.out.poses[:n].numpy(), self.out.foot_contacts[:n].numpy()


def main():
    ap = argparse.ArgumentParser()
    for name in ("a_glb", "a_clip", "b_glb", "b_clip", "rig_json", "name", "out"):
        ap.add_argument(name)
    ap.add_argument("--tokens", default="8,9,10,11,12,13,14", help="clip lengths the model may pick, 6-16")
    ap.add_argument("--device", default="cuda:0")
    ap.add_argument("--max-seam-cm", type=float, default=ms.MAX_SEAM_CM)
    ap.add_argument("--max-speed", type=float, default=ms.MAX_SPEED)
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)

    a_doc, a_buf, cp, a_anim, (a_rot, a_tra) = ms.load_clip(args.a_glb, args.a_clip, ms.tail_times)
    _, _, _, _, (b_rot, b_tra) = ms.load_clip(args.b_glb, args.b_clip, ms.head_times)
    skeleton, soma = load_soma()
    rig = ms.Rig(soma, cp)
    context = rig.to_soma(a_rot[:, -ms.CONTEXT:], a_tra[:, -ms.CONTEXT:])
    target = rig.to_soma(b_rot[:, :ms.CONTEXT], b_tra[:, :ms.CONTEXT])
    print("hip scale cp->soma %.3f" % rig.scale)

    tokens = tuple(int(t) for t in args.tokens.split(","))
    with Generator(skeleton, args.device) as generate:
        poses, contacts = generate(context, target, tokens)
    n = poses.shape[0]

    rot, tra = rig.from_soma(poses, a_rot, a_tra, b_rot, b_tra)
    metrics = ms.measure(cp, rot, tra, (a_rot, a_tra), (b_rot, b_tra))
    print(json.dumps(metrics))

    with open(args.rig_json, encoding="utf-8") as f:
        ref_tracks = json.load(f)["Data"]["RootChunk"].get("referenceTracks", [])
    extras = rg.player_extras(a_anim.get("extras", {}), ref_tracks)
    gd, gb = rg.build(a_doc, a_buf, cp, [(args.name, extras, np.arange(n, dtype=np.float64) / ms.FPS, rot, tra)])
    rg.write_glb(os.path.join(args.out, args.name + ".glb"), gd, gb)
    np.savez(os.path.join(args.out, args.name + ".npz"), rot=rot, tra=tra, soma=poses, contacts=contacts)
    with open(os.path.join(args.out, args.name + ".json"), "w", encoding="utf-8") as f:
        json.dump({"a_glb": args.a_glb, "a_clip": args.a_clip, "b_glb": args.b_glb, "b_clip": args.b_clip,
                   "metrics": metrics}, f, indent=1)

    bad = ms.failures(metrics, args.max_seam_cm, args.max_speed)
    if bad:
        sys.exit("transition rejected: " + "; ".join(bad))


if __name__ == "__main__":
    main()
