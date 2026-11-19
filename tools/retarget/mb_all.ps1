<#
Every scene pack move as a generated transition, end to end: the move list, both actors generated and cooked on
man_base / woman_base, the same clips baked onto V's skeletons, packed into the packs, the workspots rebuilt.

  powershell -File tools\retarget\mb_all.ps1 [-MaxOverlap 0.20]

Steps: mb_moves.py -> mb_batch.ps1 -> mb_player.ps1 -> pack_transitions.py --into-source -> make_scene_workspots.py
-> mb_gif.py (work\run\gifs\index.html, every move to look at offline).
A rerun lists the same graph (a rewired move is read through its transition) and regenerates every move; a move that
now fails is unpacked and plays as a cut again. Low priority throughout. docs/design/generated-motion.md §7.
#>
[CmdletBinding()]
param(
  [double]$MaxOverlap = 0.20
)

$ErrorActionPreference = 'Stop'
& python (Join-Path $PSScriptRoot 'build_config.py') --motionbricks; if ($LASTEXITCODE -ne 0) { exit 1 }   # off in build.json
(Get-Process -Id $PID).PriorityClass = 'BelowNormal'
$root  = $PSScriptRoot
$moves = Join-Path $root 'work\run\moves.csv'

function Step($what, [scriptblock]$body) {
  Write-Host "=== $what ($(Get-Date -Format HH:mm))" -ForegroundColor Cyan
  & $body
  if ($LASTEXITCODE -ne 0) { throw "$what failed (exit $LASTEXITCODE)" }
}

Step 'moves' { python (Join-Path $root 'mb_moves.py') $moves }
Step 'generate and cook' { powershell -ExecutionPolicy Bypass -File (Join-Path $root 'mb_batch.ps1') -Moves $moves }
# a set V's bake refuses stops the run before the pack: packing without it would unpack its moves' transitions
Step 'bake onto V' { powershell -ExecutionPolicy Bypass -File (Join-Path $root 'mb_player.ps1') }
Step 'pack' { python (Join-Path $root 'pack_transitions.py') --into-source --max-overlap $MaxOverlap }
Step 'workspots' { python (Join-Path (Split-Path $root) 'make_scene_workspots.py') }
Step 'gifs' { python (Join-Path $root 'mb_gif.py') --max-overlap $MaxOverlap }
Write-Host 'OK' -ForegroundColor Green
