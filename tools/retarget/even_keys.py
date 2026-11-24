"""A Skyrim clip whose motion stutters every third frame, evened out at decode.

Some sources (the bed cowgirl's woman, sx-cowgirlpushlegsup, ...) were authored with a pose every third frame and the
two frames between eased so the body nearly stops at each pose: 10 times a second, at any frame rate, the first-person
camera, hair and breast springs all feel it. Havok's own SDK decodes the same steps (ck-cmd to FBX), so it is the data.

A clip is fixed only when its whole body's travel per frame peaks at 10 Hz well above the bands beside it (clean clips
spread up to ~8x, the stuttering ones run 10x to 900x); within it, a bone track is rebuilt only when it stutters itself.
A rebuilt track keeps every third frame exactly -- the phase that leaves the least stutter -- and the two between come
from a Catmull-Rom curve through those. On a clean clip that would round off a slap's contact frame, hence the gate.
"""
import numpy as np

import retarget_glb as rg

FPS = 30.0
CLIP_GATE = 10.0     # the whole body's 10 Hz peak over its neighbours, above which a clip is fixed
TRACK_GATE = 5.0     # the same for one track, inside a fixed clip
SLIDE = 0.05         # a translation's units weighed against a turn's radians, Skyrim units


def stutter(d):
    """the 10 Hz (every third frame) peak of a step series' spectrum, against the bands beside it; 0 for too short"""
    if len(d) < 59 or d.sum() < 1e-6:
        return 0.0
    p = np.abs(np.fft.rfft(d - d.mean())) ** 2
    fr = np.fft.rfftfreq(len(d), 1 / FPS)
    side = p[((fr > 6.5) & (fr < 8.5)) | ((fr > 11.5) & (fr < 13.5))].mean()
    return float(p[(fr > 9.5) & (fr < 10.5)].max() / max(side, 1e-30))


def body_steps(w_t):
    """(F-1,) the whole body's travel per frame, from world positions (bones, frames, 3)"""
    return np.linalg.norm(np.diff(w_t, axis=1), axis=2).sum(0)


def track_steps(q, t):
    a = 2 * np.arccos(np.clip(np.abs((q[1:] * q[:-1]).sum(1)), 0, 1))
    return a + np.linalg.norm(np.diff(t, axis=0), axis=1) * SLIDE


def _catmull(keys, kt, t):
    h = kt[1] - kt[0]
    i = np.clip(((t - kt[0]) // h).astype(int), 0, len(kt) - 2)
    u = ((t - kt[i]) / h)[:, None]
    p0, p1 = keys[np.maximum(i - 1, 0)], keys[i]
    p2, p3 = keys[i + 1], keys[np.minimum(i + 2, len(kt) - 1)]
    return 0.5 * (2 * p1 + (p2 - p0) * u + (2 * p0 - 5 * p1 + 4 * p2 - p3) * u ** 2 + (3 * p1 - p0 - 3 * p2 + p3) * u ** 3)


def _loop(q, t, phase):
    """a loop (last frame the first, period a multiple of 3): the curve runs through the seam, so no end is left out"""
    n = len(q) - 1
    k = np.arange(phase, n, 3)
    if len(k) < 2:
        return q, t
    s = (np.arange(n) - phase) % n
    i, u = s // 3, ((s % 3) / 3.0)[:, None]
    m = len(k)

    def curve(x, quat=False):
        p0, p1, p2, p3 = x[k[(i - 1) % m]], x[k[i % m]], x[k[(i + 1) % m]], x[k[(i + 2) % m]]
        if quat:    # the seam may flip the hemisphere: each key on p1's side
            p0, p2, p3 = (p * np.sign((p * p1).sum(1, keepdims=True) + 1e-12) for p in (p0, p2, p3))
        return 0.5 * (2 * p1 + (p2 - p0) * u + (2 * p0 - 5 * p1 + 4 * p2 - p3) * u ** 2 + (3 * p1 - p0 - 3 * p2 + p3) * u ** 3)

    q2, t2 = q.copy(), t.copy()
    r = curve(q, True)
    q2[:n] = r / np.linalg.norm(r, axis=1, keepdims=True)
    t2[:n] = curve(t)
    q2[n], t2[n] = q2[0] * np.sign((q2[0] * q2[n - 1]).sum() + 1e-12), t2[0]
    return q2, t2


def rebuild(q, t, phase):
    """one track with every third frame from phase kept and the two between on a curve through them"""
    q = q.copy()
    for f in range(1, len(q)):          # one hemisphere, so the components blend
        if (q[f] * q[f - 1]).sum() < 0:
            q[f] = -q[f]
    n = len(q) - 1
    if n % 3 == 0 and abs((q[-1] * q[0]).sum()) > 1 - 1e-8 and np.allclose(t[-1], t[0], atol=1e-5):
        return _loop(q, t, phase)
    kt = np.arange(phase, len(q), 3, dtype=float)
    if len(kt) < 2:
        return q, t
    m = np.arange(len(q), dtype=float)
    m = m[(m >= kt[0]) & (m <= kt[-1])]   # frames before the first kept one and after the last stay as they are
    k = kt.astype(int)
    q2, t2 = q.copy(), t.copy()
    r = _catmull(q[k], kt, m)
    q2[m.astype(int)] = r / np.linalg.norm(r, axis=1, keepdims=True)
    t2[m.astype(int)] = _catmull(t[k], kt, m)
    return q2, t2


def fix(rot, tra, w_t):
    """(rot, tra, clip ratio, tracks rebuilt): rot (bones, frames, 4) and tra local, w_t their world positions"""
    ratio = stutter(body_steps(w_t))
    if ratio <= CLIP_GATE:
        return rot, tra, ratio, 0
    rot, tra, n = rot.copy(), tra.copy(), 0
    for b in range(len(rot)):
        if stutter(track_steps(rot[b], tra[b])) <= TRACK_GATE:
            continue
        best = min((rebuild(rot[b], tra[b], p) for p in range(3)), key=lambda qt: stutter(track_steps(*qt)))
        rot[b], tra[b] = rg.qnorm(best[0]), best[1]
        n += 1
    return rot, tra, ratio, n
