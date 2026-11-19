#!/usr/bin/env bash
# A fresh RunPod GPU pod (CUDA 12): Python 3.12 in /opt/ncn (by uv: the pins have no 3.11 builds) with the pipeline's
# packages at the versions it is built on, then a check that the GPU solver loads. Run from the unzipped bundle's root.
set -euo pipefail
PY=/opt/ncn/bin/python
if [ ! -x $PY ]; then
    python3 -m pip install --quiet uv
    uv venv --quiet --python 3.12 /opt/ncn
fi
uv pip install --quiet --python $PY numpy==2.5.3 scipy==1.18.1 matplotlib==3.11.2 pillow==12.3.0 \
    cupy-cuda12x==14.2.0 nvmath-python==1.0.0 nvidia-cudss-cu12==0.8.0.10 cuda-bindings==12.9.10
nvidia-smi --query-gpu=name,memory.total --format=csv,noheader
$PY -c "import cupy, nvmath.sparse.advanced; print('cupy', cupy.__version__, 'GPU', cupy.cuda.runtime.getDeviceCount())"
echo "ready: $PY cyberpunk_animport/tools/retarget/pod/pod_run.py pair_batch.py opensex 4"
