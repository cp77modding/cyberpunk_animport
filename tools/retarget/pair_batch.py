"""pair_contact.py over every clip of a pack with the cast sizes asked for, several clips at once: one worker process
per slot, each loading our bodies once and running its clips in turn, below normal priority, WORKERS=1 so the clips are
the parallelism, the GPU shared. A log per clip under work/contact/batch/<pack>/, one line per clip here as it ends.
  python pair_batch.py [pack] [jobs]      pack: ostimng (default) or opensex; jobs: clips at once (4)
  ACTORS=2,3   the cast sizes to run (2)
  MATCH=a,b    only clips whose base contains one of these
Every other env option reaches pair_contact.py (MESH=1, STEP=n, ...)."""
import contextlib, json, multiprocessing, os, re, sys, time, traceback
from concurrent.futures import ProcessPoolExecutor, as_completed
from concurrent.futures.process import BrokenProcessPool
import skyrim_port as sp
import pair_reach


def cast_size(clips, known, base):
    """_0, _1, ... to the first gap, and to the first actor no scene casts once one is cast: OStim ships a stray _2
    beside some of its pairs, which its scene file never names"""
    n = 0
    while "%s_%d" % (base, n) in clips and not (n and known.get("%s_0" % base) and not known.get("%s_%d" % (base, n))):
        n += 1
    return n


def clip_bases(rows, sizes=(2,)):
    """the bases whose cast has one of these sizes"""
    clips = {r["clip"] for r in rows}
    known = {}
    for r in rows:
        known[r["clip"]] = known.get(r["clip"]) or bool(r.get("known"))
    return sorted(c[:-2] for c in clips if c.endswith("_0") and cast_size(clips, known, c[:-2]) in sizes)


def cast_rows(every, base):
    """the manifest row each actor of base is solved on, from {clip: [rows]}. OStim names its cast (..._mmmf_s1), and
    its scenes replay one clip cast other ways; otherwise the pack's own body, and one no scene casts m on _0, f after"""
    known = {c: any(r.get("known") for r in rows) for c, rows in every.items()}
    size = cast_size(every, known, base)
    named = re.search(r"([mf]{%d})$" % size, re.sub(r"_s\d+$", "", base))
    cast = []
    for n in range(size):
        rows = every["%s_%d" % (base, n)]
        # the pack's own body is the actor's Skyrim sex, never the manifest's row order: a rebuild put f first
        own = rows[0].get("srcSex")
        want = named.group(1)[n] if named else own if known["%s_%d" % (base, n)] else "m" if not n else "f"
        cast.append(next((r for r in rows if r["sex"] == want), rows[0]))
    return cast


def pick_gpu(seq):
    """this worker's GPU: the workers in turn over every card (GPUS=0,1 picks some), so a many-GPU pod's cards each
    take a share; through cupy, not CUDA_VISIBLE_DEVICES, which a forked pod worker reads too late"""
    try:
        import cupy as cp
        n = cp.cuda.runtime.getDeviceCount()
    except Exception as e:      # no cupy or no card: the CPU paths run, as they do without a batch
        print("pair_batch: no GPU for this worker: %s" % e, file=sys.stderr)
        return
    cards = [int(g) for g in os.environ.get("GPUS", "").split(",") if g] or list(range(n))
    with seq.get_lock():
        k, seq.value = seq.value, seq.value + 1
    cp.cuda.Device(cards[k % len(cards)]).use()
    print("pair_batch: worker %d on GPU %d of %d" % (os.getpid(), cards[k % len(cards)], n), file=sys.stderr)


def start_worker(seq=None):
    os.environ["WORKERS"] = "1"         # read when pair_contact is imported, below
    if seq is not None:
        pick_gpu(seq)
    if sys.platform == "win32":
        import ctypes
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.GetCurrentProcess.restype = ctypes.c_void_p     # the pseudo-handle -1, cut to 32 bits without this
        k32.SetPriorityClass.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        if not k32.SetPriorityClass(k32.GetCurrentProcess(), 0x4000):    # BELOW_NORMAL_PRIORITY_CLASS
            print("pair_batch: could not lower worker priority, error %d" % ctypes.get_last_error(), file=sys.stderr)


def run(base, pack, out):
    import pair_contact
    t = time.time()
    sys.stdout.flush(); sys.stderr.flush()
    saved = os.dup(1), os.dup(2)
    with open(os.path.join(out, base + ".log"), "w", encoding="utf-8") as log:
        # the descriptors too, not only sys.stdout: cuDSS and numpy write from C
        os.dup2(log.fileno(), 1); os.dup2(log.fileno(), 2)
        try:
            with contextlib.redirect_stdout(log), contextlib.redirect_stderr(log):
                try:
                    pair_contact.run(base, pack)
                    code = 0
                except (Exception, SystemExit):
                    traceback.print_exc()
                    code = 1
        finally:
            log.flush()
            os.dup2(saved[0], 1); os.dup2(saved[1], 2)
            os.close(saved[0]); os.close(saved[1])
    return base, code, time.time() - t


def main():
    pack = sys.argv[1] if len(sys.argv) > 1 else "ostimng"
    jobs = int(sys.argv[2]) if len(sys.argv) > 2 else 4
    port, _ = pair_reach.PORTS[pack]
    want = [w for w in os.environ.get("MATCH", "").split(",") if w] or [""]     # a stray comma is not "every clip"
    sizes = tuple(int(s) for s in os.environ.get("ACTORS", "2").split(",") if s)
    bases = [b for b in clip_bases(json.load(open(os.path.join(port, "manifest.json"))), sizes)
             if any(w in b for w in want)]
    out = os.path.join(sp.WORK, "contact", "batch", pack)
    os.makedirs(out, exist_ok=True)
    print("%d clips of %s, casts of %s, %d at once, logs in %s" % (
        len(bases), pack, ",".join(map(str, sizes)), jobs, out))
    t, failed = time.time(), []
    with ProcessPoolExecutor(jobs, initializer=start_worker, initargs=(multiprocessing.Value("i", 0),)) as pool:
        futures = {pool.submit(run, b, pack, out): b for b in bases}
        for n, f in enumerate(as_completed(futures), 1):
            try:
                base, code, dt = f.result()
            except BrokenProcessPool:       # a worker died in native code: this clip and every one queued behind it
                base, code, dt = futures[f], 1, 0.0
            if code:
                failed.append(base)
            print("  [%d/%d] %-55s %5.1f s%s" % (n, len(bases), base, dt, "" if not code else "  FAILED, see its log"),
                  flush=True)
    print("%d clips in %.0f s, %d failed%s" % (len(bases), time.time() - t, len(failed),
                                                ": " + ", ".join(failed) if failed else ""))
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
