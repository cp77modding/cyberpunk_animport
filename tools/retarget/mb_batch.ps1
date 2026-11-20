<#
Generated transitions for a list of moves: both actors of each, one model load, one cook launch, every set checked.

  powershell -File tools\retarget\mb_batch.ps1 -Moves moves.csv [-Only sample.txt] [-Tokens 14,16,10]

-Moves has one row per actor (mb_batch.py). -Only limits it to "from to" lines. Source sets are exported once to
work\run\mb_sets and re-exported only when the set is newer. Runs at low priority, one worker: the model holds the GPU.
Output: work\depot\ncn\anims\npc\gen_<set>.anims, grouped by A's set, and work\run\gen_results.jsonl for
pack_transitions.py. docs/design/generated-motion.md §7.
#>
[CmdletBinding()]
param(
  [Parameter(Mandatory)][string]$Moves,
  [string]$Only = '-',
  [string]$Tokens = '14,16,10',
  [string]$MotionBricks = $env:NCN_MOTIONBRICKS,
  [string]$Packs = 'C:\Work\WorkSpace\Cyberpunk\CyberpunkAnimations',
  [string]$GamePath  = 'D:\SteamLibrary\steamapps\common\Cyberpunk 2077',
  [string]$WolvenKit = 'C:\Modding\wolwenKit_upacker\WolvenKit.CLI.exe',
  [string]$WolvenKitCook = '',
  [double]$MaxDeg = 0.1,
  [double]$MaxCm = 0.1
)

$ErrorActionPreference = 'Stop'
& python (Join-Path $PSScriptRoot 'build_config.py') --motionbricks; if ($LASTEXITCODE -ne 0) { exit 1 }   # off in build.json
(Get-Process -Id $PID).PriorityClass = 'BelowNormal'
$root = $PSScriptRoot
$work = Join-Path $root 'work'
if (-not $WolvenKitCook) { $WolvenKitCook = Join-Path $work 'wk_nightly' }
if (-not $MotionBricks) { $MotionBricks = Join-Path (Split-Path (Split-Path (Split-Path $root))) 'MotionBricks' }
$mbPython = Join-Path $MotionBricks '.venv\Scripts\python.exe'
$batch = Join-Path $root 'mb_batch.py'
$sets  = Join-Path $work 'run\mb_sets'
$run   = Join-Path $work 'run\mb_batch'
$depot = Join-Path $work 'depot\ncn\anims\npc'
$Moves = (Resolve-Path $Moves).Path
if ($Only -ne '-') { $Only = (Resolve-Path $Only).Path }
foreach ($p in @($WolvenKit, $mbPython, (Join-Path $WolvenKitCook 'WolvenKit.Modkit.dll'))) {
  if (-not (Test-Path $p)) { throw "not found: $p" }
}
if (Test-Path $run) { Remove-Item $run -Recurse -Force }
New-Item -ItemType Directory -Force $sets, $run, $depot | Out-Null

function Step($what, [scriptblock]$body) {
  Write-Host "-- $what" -ForegroundColor Cyan
  & $body
  if ($LASTEXITCODE -ne 0) { throw "$what failed (exit $LASTEXITCODE)" }
}

$need = @(python $batch sets $Moves $Only)
if ($LASTEXITCODE -ne 0) { throw 'reading the moves failed' }
foreach ($rel in $need) {
  $pack = $rel.Split('\')[0]
  $src  = Join-Path $Packs "$pack\depot\$rel"
  $file = Join-Path $sets ([IO.Path]::GetFileName($rel))
  # an export cut short leaves an empty json: redo it
  $done = (Test-Path "$file.glb") -and (Test-Path "$file.json") -and (Get-Item "$file.json").Length -gt 0
  if ($done -and (Get-Item $file).LastWriteTime -ge (Get-Item $src).LastWriteTime) { continue }
  Copy-Item $src $file -Force
  Step "export $rel" { & $WolvenKit export $file -o $sets -gp $GamePath -v Minimal }
  Step "serialize $rel" { & $WolvenKit convert serialize $file -v Minimal }
}

$rigJson = Join-Path $work 'npcrig\cr2w\base\characters\base_entities\%(rig)s\%(rig)s.rig.json'
Push-Location $MotionBricks
try {
  Step 'generate' { & $mbPython $batch generate $Moves $Only $sets $run --tokens $Tokens --rig-json $rigJson }
} finally { Pop-Location }

$groups = @(Get-Content (Join-Path $run 'groups.tsv') | Where-Object { $_ } | ForEach-Object {
  $g, $set, $rig = $_ -split "`t"
  [pscustomobject]@{ Name = $g; Set = $set; Rig = $rig; Stem = "$g.anims" }
})
$containers = Join-Path $run 'container'
# deserialized and cooked here, into the depot only once every set verifies: a stop between leaves the depot as it was
$stage = Join-Path $run 'depot'
New-Item -ItemType Directory -Force $containers, $stage | Out-Null
$pairs = Join-Path $run 'pairs.tsv'
Set-Content $pairs -Value '' -Encoding ascii
foreach ($g in $groups) {
  $rigPath = "base\characters\base_entities\$($g.Rig)\$($g.Rig).rig"
  $json = Join-Path $containers "$($g.Stem).json"
  Step "container $($g.Name)" { python (Join-Path $root 'anims_json.py') prep (Join-Path $sets "$($g.Set).anims.json") $rigPath $json }
  Step "deserialize $($g.Name)" { & $WolvenKit convert deserialize $json -o $stage -v Minimal }
  Add-Content $pairs "$(Join-Path $run "$($g.Name).glb")`t$(Join-Path $stage $g.Stem)" -Encoding ascii
}

$bridge = Join-Path $root 'wk_anims\bin\Release\net10.0\WkAnims.exe'
Step 'build wk_anims' { dotnet build (Join-Path $root 'wk_anims\WkAnims.csproj') -c Release -v q --nologo | Out-Null }
Step 'cook' { & $bridge --list $pairs $GamePath $WolvenKitCook }

$check = Join-Path $run 'check'
New-Item -ItemType Directory -Force $check | Out-Null
foreach ($g in $groups) {
  $out = Join-Path $stage $g.Stem
  Step "export $($g.Name)" { & (Join-Path $WolvenKitCook 'WolvenKit.CLI.exe') export $out -o $check -gp $GamePath -v Minimal }
  Step "verify $($g.Name)" { python (Join-Path $root 'verify_retarget.py') (Join-Path $run "$($g.Name).glb") (Join-Path $check "$($g.Stem).glb") --max-deg $MaxDeg --max-cm $MaxCm }
  Copy-Item $out (Join-Path $check $g.Stem)
  Step "serialize $($g.Name)" { & (Join-Path $WolvenKitCook 'WolvenKit.CLI.exe') convert serialize (Join-Path $check $g.Stem) -v Minimal }
  $cooked = Join-Path $check "$($g.Stem).json"
  $kinds = Select-String -Path $cooked -Pattern '"animAnimationBuffer(\w+)"' -AllMatches |
    ForEach-Object { $_.Matches } | ForEach-Object { $_.Groups[1].Value }
  if (-not $kinds -or @($kinds | Where-Object { $_ -ne 'Simd' })) { throw "$($g.Name): buffers are not all SIMD" }
  Step "check fallback $($g.Name)" { python (Join-Path $root 'anims_json.py') check $cooked }
}
foreach ($g in $groups) { Copy-Item (Join-Path $stage $g.Stem) (Join-Path $depot $g.Stem) -Force }

Step 'results' { python $batch results $run $depot (Join-Path $work 'run\gen_results.jsonl') }
Write-Host 'OK' -ForegroundColor Green
