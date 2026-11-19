"""Nearest points on a body posed over many frames, every frame's queries in one call.

The hand fit asked a KD tree per frame per finger step: 19,866 queries a clip, 5 s of its 45. On the GPU (cupy) one
thread per query scans its frame's points in float32, then picks among those within MARGIN of the best in float64 with
no fused multiply-add, so distances and indices match cKDTree's to the bit. pair_contact's report kernel is float32
only, one frame a call: 3e-7 m flips the fit's bisection and spot choices. Without cupy, one KD tree over every frame,
each FAR apart on a fourth axis.

  FrameTree(pts).query(rows, q, k)    k nearest, on the CPU
  FramePoints(pts).nearest(rows, q)   the nearest, on the GPU when cupy loads
"""
import numpy as np
from scipy.spatial import cKDTree

try:
    import cupy as cp
except ImportError:
    cp = None

FAR = 1e6          # FrameTree's spacing of frames on its fourth axis, past any distance in metres or Skyrim units
BLOCK = 128

# float32 finds the nearest within MARGIN, float64 picks among those: a consumer card runs float64 at 1/64 the rate
# one block row per frame (blockIdx.y), the frame's points read in tiles through shared memory
_SRC = r'''
#define TILE 1024
#define CAND 32
extern "C" __global__ void nearest(const double* pts, const float* pts32, const double* q, const long long* rows,
                                   int V, int m, float margin, double* dout, long long* jout) {
    __shared__ float tile[TILE * 3];
    int qi = blockIdx.x * blockDim.x + threadIdx.x;
    bool live = qi < m;
    long long base = rows[blockIdx.y] * (long long)V, i = (long long)blockIdx.y * m + qi;
    double x = 0, y = 0, z = 0;
    if (live) { x = q[3 * i]; y = q[3 * i + 1]; z = q[3 * i + 2]; }
    float fx = (float)x, fy = (float)y, fz = (float)z, b32 = 3.0e38f;
    for (int t0 = 0; t0 < V; t0 += TILE) {
        int n = min(TILE, V - t0);
        __syncthreads();
        for (int k = threadIdx.x; k < n * 3; k += blockDim.x) tile[k] = pts32[(base + t0) * 3 + k];
        __syncthreads();
        if (live)
            for (int v = 0; v < n; ++v) {
                float dx = tile[3 * v] - fx, dy = tile[3 * v + 1] - fy, dz = tile[3 * v + 2] - fz;
                b32 = fminf(b32, dx * dx + dy * dy + dz * dz);
            }
    }
    // the candidates within the margin, in index order; float64 only on them, after the scan (inside it, the compiler
    // predicated the float64 sum onto every point and the kernel ran 40 times slower)
    float lim = sqrtf(b32) + margin;
    lim *= lim;
    int cand[CAND], nc = 0;
    for (int t0 = 0; t0 < V; t0 += TILE) {
        int n = min(TILE, V - t0);
        __syncthreads();
        for (int k = threadIdx.x; k < n * 3; k += blockDim.x) tile[k] = pts32[(base + t0) * 3 + k];
        __syncthreads();
        if (live)
            for (int v = 0; v < n; ++v) {
                float dx = tile[3 * v] - fx, dy = tile[3 * v + 1] - fy, dz = tile[3 * v + 2] - fz;
                if (dx * dx + dy * dy + dz * dz <= lim) {
                    if (nc < CAND) cand[nc] = t0 + v;
                    ++nc;
                }
            }
    }
    if (!live) return;
    double best = 1e300;
    int bj = 0, all = nc > CAND ? V : nc;
    for (int c = 0; c < all; ++c) {
        int v = nc > CAND ? c : cand[c];
        const double* s = pts + (base + v) * 3;
        double ex = __dsub_rn(s[0], x), ey = __dsub_rn(s[1], y), ez = __dsub_rn(s[2], z);
        double d = __dadd_rn(__dadd_rn(__dmul_rn(ex, ex), __dmul_rn(ey, ey)), __dmul_rn(ez, ez));
        if (d < best) { best = d; bj = v; }
    }
    dout[i] = sqrt(best);
    jout[i] = base + bj;
}'''
# every query's squared distance to every point of its frame, float64 with no fused multiply-add: knn's sort reads it
_SRC_ALL = r'''
extern "C" __global__ void dist2(const double* pts, const double* q, const long long* base, int V, long long n,
                                 double* out) {
    long long t = blockIdx.x * (long long)blockDim.x + threadIdx.x;
    if (t >= n) return;
    long long i = t / V;
    const double* s = pts + (base[i] + t % V) * 3;
    double ex = __dsub_rn(s[0], q[3 * i]), ey = __dsub_rn(s[1], q[3 * i + 1]), ez = __dsub_rn(s[2], q[3 * i + 2]);
    out[t] = __dadd_rn(__dadd_rn(__dmul_rn(ex, ex), __dmul_rn(ey, ey)), __dmul_rn(ez, ez));
}'''
MARGIN = 1e-5      # float32's error is under 2e-7 of the largest coordinate: the margin is 4e-6 of it, at least this
KNN_BYTES = 64 << 20    # knn's distance block per pass (its argsort takes as much again)
BLEND_BYTES = 64 << 20  # blend's matrices per pass: all 301 frames of her body at once were 555 MB
_kernel = _kernel_all = None


def blend(w, s, vh, keep=False):
    """points skinned on many frames: weights w (P, B), bone skin matrices s (frames, B, 4, 4), bind points vh (P, 4)
    -> (frames, P, 3), on the GPU when cupy loads (her 14,411 points on 301 frames: 1.1 s on the CPU); keep=True also
    returns the GPU array (None without cupy)"""
    if cp is None:
        m = (w @ s.reshape(len(s), s.shape[1], 16)).reshape(len(s), len(w), 4, 4)
        out = np.einsum("fvij,vj->fvi", m[:, :, :3], vh)
        return (out, None) if keep else out
    wd, vd = cp.asarray(w), cp.asarray(vh)
    dev = cp.empty((len(s), len(w), 3))
    step = max(1, BLEND_BYTES // (128 * len(w)))     # a frame's blended matrices: points x 16 float64
    for a in range(0, len(s), step):
        m = (wd @ cp.asarray(s[a:a + step].reshape(-1, s.shape[1], 16))).reshape(-1, len(w), 4, 4)
        dev[a:a + step] = cp.einsum("fvij,vj->fvi", m[:, :, :3], vd)
    return (dev.get(), dev) if keep else dev.get()


def release():
    """hand the GPU memory pool back to the driver: cupy keeps a process's peak, and five batch workers' peaks
    overfilled a 16 GB card, which Windows then paged to RAM (one clip in ten minutes)"""
    if cp is not None:
        cp.get_default_memory_pool().free_all_blocks()


class FrameTree:
    """points posed on many frames (n, V, 3) in one KD tree, each frame FAR apart on a fourth axis"""

    def __init__(self, pts):
        n, self.V, _ = pts.shape
        self.pts, self.flat = pts, pts.reshape(-1, 3)
        self.tree = cKDTree(np.c_[self.flat, np.repeat(np.arange(n) * FAR, self.V)]) if n else None

    def query(self, rows, q, k=1):
        """q (len(rows), m, 3) against each row's frame: (distance, flat index), (len(rows), m) or (.., k)"""
        rows = np.asarray(rows, dtype=np.int64)
        shape = q.shape[:-1] + ((k,) if k > 1 else ())
        if not len(rows):
            return np.zeros(shape), np.zeros(shape, np.int64)
        x = np.concatenate([q, np.broadcast_to((rows * FAR)[:, None, None], q.shape[:-1] + (1,))], -1)
        d, j = self.tree.query(x.reshape(-1, 4), k=k)
        return d.reshape(shape), j.reshape(shape)


class FramePoints:
    """points posed on many frames (n, V, 3): the nearest to each query on its own frame"""

    def __init__(self, pts, dev=None):
        """dev: pts already on the GPU (blend's keep), saving the upload"""
        n, self.V, _ = pts.shape
        self.pts, self.flat = pts, pts.reshape(-1, 3)
        self.gpu = cp is not None and n > 0
        if self.gpu:
            global _kernel, _kernel_all
            if _kernel is None:
                _kernel, _kernel_all = cp.RawKernel(_SRC, "nearest"), cp.RawKernel(_SRC_ALL, "dist2")
            self.dev = cp.ascontiguousarray(dev.reshape(-1, 3)) if dev is not None else cp.asarray(np.ascontiguousarray(self.flat))
            self.dev32 = self.dev.astype(cp.float32)
            self.reach = float(np.abs(self.flat).max())
        else:
            self.cpu = FrameTree(pts)

    def knn(self, rows, q, k):
        """q (len(rows), m, 3): the k nearest on each row's frame, nearest first: (distance, flat index), each
        (len(rows), m, k)"""
        rows = np.asarray(rows, dtype=np.int64)
        if not self.gpu or not len(rows):
            return self.cpu.query(rows, q, k) if not self.gpu else (np.zeros(q.shape[:-1] + (k,)),
                                                                     np.zeros(q.shape[:-1] + (k,), np.int64))
        m = q.shape[1]
        base = np.repeat(rows * self.V, m)
        qd = cp.asarray(np.ascontiguousarray(q.reshape(-1, 3), dtype=np.float64))
        step = max(1, KNN_BYTES // (8 * self.V))
        d, j = [], []
        for a in range(0, len(base), step):
            b = min(len(base), a + step)
            n = (b - a) * self.V
            out = cp.empty(n)
            _kernel_all(((n + 255) // 256,), (256,), (self.dev, qd[a:b], cp.asarray(base[a:b]), np.int32(self.V),
                                                     np.int64(n), out))
            out = out.reshape(b - a, self.V)
            o = cp.argsort(out, axis=1)[:, :k]
            d.append(cp.sqrt(cp.take_along_axis(out, o, 1)).get())
            j.append((o + cp.asarray(base[a:b])[:, None]).get())
        return np.concatenate(d).reshape(len(rows), m, k), np.concatenate(j).reshape(len(rows), m, k)

    def nearest(self, rows, q):
        """q (len(rows), m, 3): (distance, flat index), each (len(rows), m)"""
        rows = np.asarray(rows, dtype=np.int64)
        if not self.gpu or not len(rows):
            return self.cpu.query(rows, q) if not self.gpu else (np.zeros(q.shape[:-1]), np.zeros(q.shape[:-1], np.int64))
        m = q.shape[1]
        nq = len(rows) * m
        d, j = cp.empty(nq), cp.empty(nq, cp.int64)
        _kernel(((m + BLOCK - 1) // BLOCK, len(rows)), (BLOCK,),
                (self.dev, self.dev32, cp.asarray(np.ascontiguousarray(q.reshape(-1, 3), dtype=np.float64)),
                 cp.asarray(rows), np.int32(self.V), np.int32(m),
                 np.float32(max(MARGIN, 4e-6 * max(self.reach, float(np.abs(q).max())))), d, j))
        return d.get().reshape(len(rows), m), j.get().reshape(len(rows), m)
