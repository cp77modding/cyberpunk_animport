#!/usr/bin/env bash
# The whole sweep on a pod, from the unzipped bundle's root: setup, then a pass over both packs' pairs,
# each pass's meshes packed as results_<label>.zip. A timer stops the pod after MAX_HOURS whatever happens, so a lost
# connection never leaves it billing.  bash cyberpunk_animport/tools/retarget/pod/run_sweep.sh
set -uo pipefail
cd "$(dirname "$0")/../../../.."
MAX_HOURS=${MAX_HOURS:-10}
JOBS=${JOBS:-5}
PY=/opt/ncn/bin/python
# an ssh session lacks the container's own env, which holds this pod's id and its stop key
eval "$(tr '\0' '\n' < /proc/1/environ | grep -E '^RUNPOD_(POD_ID|API_KEY)=' | sed 's/^/export /')"
( sleep $((MAX_HOURS * 3600)); echo "safety stop after ${MAX_HOURS} h" >> sweep.log; runpodctl stop pod "$RUNPOD_POD_ID" ) &
# the pod's own key may stop its pod but not read it (`get pod` is Unauthorized), so check only what the stop needs
[ -n "${RUNPOD_POD_ID:-}" ] && [ -n "${RUNPOD_API_KEY:-}" ] && command -v runpodctl > /dev/null \
    && echo "safety stop armed: ${MAX_HOURS} h" || echo "WARNING: no runpodctl, pod id or key; no safety stop"
bash cyberpunk_animport/tools/retarget/pod/setup.sh || exit 1
RT=cyberpunk_animport/tools/retarget
pass() {    # label, then env for pair_contact
    local label=$1; shift
    rm -rf $RT/work/skyrim/port/mesh $RT/work/skyrim/ostimng/mesh $RT/work/contact/batch
    for pack in opensex ostimng; do
        env MESH=1 SAVE=1 ACTORS=2 "$@" $PY $RT/pod/pod_run.py pair_batch.py $pack $JOBS
    done
    $PY $RT/pod/pod_run.py --collect results_$label.zip
    echo "PASS DONE $label"
}
pass handfit MESH_SKIN=1 HANDFIT=1
echo "SWEEP DONE"
