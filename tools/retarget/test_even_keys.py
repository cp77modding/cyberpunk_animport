"""even_keys: a clip stuttering every third frame is evened, its kept frames exact; a clean one, a slap included,
is left as it is.  python tools/retarget/test_even_keys.py"""
import sys

import numpy as np

import even_keys as ek

FAILS = []


def check(ok, what):
    print("%s  %s" % ("ok  " if ok else "FAIL", what))
    if not ok:
        FAILS.append(what)


def clip(x):
    """one bone sliding along x (frames,), as (rot, tra, world)"""
    F = len(x)
    rot = np.tile([0.0, 0.0, 0.0, 1.0], (1, F, 1))
    tra = np.zeros((1, F, 3))
    tra[0, :, 0] = x * 40      # Skyrim units: a 40-unit swing, a body's bounce
    return rot, tra, tra.copy()


F = 301
t = np.arange(F) / 30.0
smooth = np.sin(2 * np.pi * 0.6 * t)
# the source's fault: within each three frames the motion runs 0.39, 0.51 then 0.10 of the way (the bed cowgirl's)
u = np.repeat(np.arange(0, F, 3), 3)[:F] + np.tile([0.0, 0.39 * 3, 0.90 * 3], F // 3 + 1)[:F]
u[np.arange(F) % 3 == 0] = np.arange(F)[np.arange(F) % 3 == 0]
stutter = np.sin(2 * np.pi * 0.6 * u / 30.0)

r, tr, w = clip(stutter)
before = ek.stutter(ek.body_steps(w))
r2, t2, ratio, n = ek.fix(r, tr, w)
after = ek.stutter(ek.body_steps(t2))
check(before > ek.CLIP_GATE, "the stutter is seen (%.0fx)" % before)
# the even sine itself reads ~7.7x (a 0.6 Hz sine's own 10 Hz leakage), so the curve is judged against it too
err = np.abs(t2[0, :, 0] - smooth * 40).max()
check(n == 1 and after < ek.CLIP_GATE and err < 0.01 * 40,
      "evened: %.0fx -> %.1fx, %d track rebuilt, %.3f units off the even motion" % (before, after, n, err))
check(np.allclose(t2[0, ::3], tr[0, ::3]) or np.allclose(t2[0, 1::3], tr[0, 1::3]) or np.allclose(t2[0, 2::3], tr[0, 2::3]),
      "every third frame kept exactly")
check(np.abs(t2 - tr).max() < 0.1 * 40, "no frame moved far (%.2f units)" % np.abs(t2 - tr).max())

# a loop whose kept poses sit on frames 1, 4, ...: the frames by the seam are evened too, and it still closes
u1 = np.r_[u[-2:-1] - 300, u[:-1]] + 1
r, tr, w = clip(np.sin(2 * np.pi * 0.6 * u1 / 30.0))
r2, t2, ratio, n = ek.fix(r, tr, w)
d = np.abs(np.diff(t2[0, :, 0]))
ideal = np.abs(np.diff(np.sin(2 * np.pi * 0.6 * np.arange(F) / 30.0) * 40))
check(n == 1 and t2[0, -1, 0] == t2[0, 0, 0], "a loop's last frame is its first")
check(np.abs(d[[0, 1, -2, -1]] - ideal[[0, 1, -2, -1]]).max() < 0.15 * ideal.max(),
      "the steps by the seam are even (worst off by %.2f of a %.2f step)" % (
          np.abs(d[[0, 1, -2, -1]] - ideal[[0, 1, -2, -1]]).max(), ideal.max()))

r, tr, w = clip(smooth)
r2, t2, ratio, n = ek.fix(r, tr, w)
check(n == 0 and np.array_equal(t2, tr), "a clean clip is untouched (%.1fx)" % ratio)

slap = smooth.copy()
slap[150] += 0.5              # one frame's hit, as a slap's contact frame
r, tr, w = clip(slap)
r2, t2, ratio, n = ek.fix(r, tr, w)
check(n == 0 and t2[0, 150, 0] == tr[0, 150, 0], "a slap's contact frame is kept (%.1fx)" % ratio)

sys.exit(1 if FAILS else 0)
