#!/usr/bin/env bash
# The glbs and cook stages of both packs on a pod, from the unzipped bake bundle's root (bake_bundle.py), only the
# sets in each port's sets.txt; the cooked sets and their glbs packed as results_bake.zip. A timer stops the pod after
# MAX_HOURS whatever happens.  bash cyberpunk_animport/tools/retarget/pod/run_bake.sh
set -uo pipefail
cd "$(dirname "$0")/../../../.."
MAX_HOURS=${MAX_HOURS:-2}
eval "$(tr '\0' '\n' < /proc/1/environ | grep -E '^RUNPOD_(POD_ID|API_KEY)=' | sed 's/^/export /')"
( sleep $((MAX_HOURS * 3600)); echo "safety stop after ${MAX_HOURS} h" >> bake.log; runpodctl stop pod "$RUNPOD_POD_ID" ) &
# the pod's own key may stop its pod but not read it (`get pod` is Unauthorized), so check only what the stop needs
[ -n "${RUNPOD_POD_ID:-}" ] && [ -n "${RUNPOD_API_KEY:-}" ] && command -v runpodctl > /dev/null \
    && echo "safety stop armed: ${MAX_HOURS} h" || echo "WARNING: no runpodctl, pod id or key; no safety stop"
if ! command -v dotnet > /dev/null; then
    curl -sSL https://dot.net/v1/dotnet-install.sh -o /tmp/di.sh
    bash /tmp/di.sh --channel 8.0 --runtime dotnet --install-dir /opt/dotnet > /dev/null || exit 1
    bash /tmp/di.sh --channel 8.0 --runtime aspnetcore --install-dir /opt/dotnet > /dev/null || exit 1
    export PATH=/opt/dotnet:$PATH DOTNET_ROOT=/opt/dotnet
fi
python3 -c "import numpy" 2> /dev/null || python3 -m pip install --quiet numpy || exit 1
RT=cyberpunk_animport/tools/retarget
for pack in port ostimng; do
    P=$RT/work/skyrim/$pack
    for stage in glbs cook; do
        echo "== $pack $stage $(date +%T)"
        python3 $RT/skyrim_port.py $stage --port-dir $P --sets $P/sets.txt --workers ${JOBS:-$(nproc)} || { echo "FAILED $pack $stage"; exit 1; }
    done
done
rm -f results_bake.zip
( cd $RT/work/skyrim && python3 - <<'EOF'
import os, zipfile
names = {"port": "opensex", "ostimng": "ostimng"}
with zipfile.ZipFile("/root/results_bake.zip" if os.path.isdir("/root") else "results_bake.zip", "w", zipfile.ZIP_DEFLATED, compresslevel=1) as z:
    for d, label in names.items():
        for sub in ("glb", "depot"):
            for root, _, fs in os.walk(os.path.join(d, sub)):
                for f in fs:
                    p = os.path.join(root, f)
                    z.write(p, label + "/" + os.path.relpath(p, d).replace(os.sep, "/"))
EOF
)
echo "BAKE DONE $(date +%T)"
