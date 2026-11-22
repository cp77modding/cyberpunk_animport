<#
.SYNOPSIS
  The animation port's Python tests. No game, no packs; seconds.
.EXAMPLE
  .\tools\py_test.ps1
  .\tools\py_test.ps1 -Filter pair
#>
param(
  [string]$Filter = '',
  [switch]$Quiet
)

$ErrorActionPreference = 'Continue'
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$tests = @(
  'test_port',   # one command: the local file over build.json, the check naming what is missing, format, unpack
  'retarget\test_build_config',   # build.json: every path read, the sources' run folders apart, MotionBricks off
  'retarget\test_retarget_glb',   # NPC-rig clip onto V's skeleton: motion kept, target lengths, no game data
  'retarget\test_rig_glb',   # a rig json as WolvenKit's armature: axes, parents, bind matrices, A-pose rest
  'retarget\test_skyrim_port',   # the port: tagfile -> packfile, skeleton padding, scene inventory, axes
  'retarget\test_mb_soma',   # baked transitions: Cyberpunk rig <-> SOMA, the half turn, thigh names, seam and speed limits
  'retarget\test_mb_batch',   # the batch's move list and skips; capsule distance, surface to surface
  'retarget\test_pair_reach',   # an oral giver slid flat to the source's reach; the shift under a turned root
  'retarget\test_interaction_mesh',   # a hand kept on a head through a 40% shorter arm; feet held; capsules pushed, exempt ones not
  'retarget\test_hand_fit',   # a reach that straightens the arm, then a lift: the elbow bends back to its own side
  'retarget\test_pair_batch',   # the batch's clips: the cast sizes asked for, counted to the first gap, each once
  'retarget\test_pair_cast',   # a SexLab pack's pairs from its scene list, man first; the mod's own still by clip name
  'retarget\test_pack_transitions',   # a generated transition as a scene: the test pack's copy of A, or A's move rewired
  'retarget\test_mb_moves',   # every two-actor move, same posture included; a rewired move read through its transition
  'retarget\test_mb_gif',   # a move's verdict in the GIF index; the gap between two bodies per frame
  'opensex\test_amm_poses',   # a pack's poses in AMM's list: poses only, AMM's rig labels, a baked rig's set path
  'opensex\test_undress_events',   # the undress clips' Skyrim slot masks as our clothing slots
  'opensex\test_climax_events',   # where OStimClimax lands in a clip
  'opensex\test_sex_hub',   # every scene a pair can play is two moves at most from sex, through its cast's hub
  'opensex\test_cast_roles',   # who may play a side: the parts its acts use, "any" for none; the other body's port row
  'opensex\test_scene_files',   # a scene that licks names its giver's mouth; a blowjob keeps the act's
  'opensex\test_make_integration',   # a ported pack's ids under integrations.<pack>, another pack's kept
  'retarget\test_scenes_slal',   # a SexLab stage's tags as postures, acts, furniture; unrated where they cannot say who
  'retarget\test_scenes_ostim'   # any OStim pack: a scene's clip from the set beside it; SexLab scene tags lower case
)
if ($Filter) { $tests = $tests | Where-Object { $_ -match $Filter } }
if (-not $tests) { Write-Host "no test matches /$Filter/" -ForegroundColor Yellow; exit 1 }

$failed = @(); $missing = @()
foreach ($t in $tests) {
  $path = Join-Path $root "tools\$t.py"
  if (-not (Test-Path $path)) { $missing += $t; continue }
  $out = & python $path 2>&1
  if ($LASTEXITCODE -ne 0) {
    $failed += $t
    Write-Host "FAIL  $t" -ForegroundColor Red
    $out | Select-Object -Last 20 | ForEach-Object { Write-Host "      $_" }
  } elseif (-not $Quiet) {
    Write-Host ("ok    {0,-34} {1}" -f $t, ($out | Select-Object -Last 1)) -ForegroundColor DarkGray
  }
}
Write-Host ''
if ($missing) { Write-Host "MISSING harness: $($missing -join ', ')" -ForegroundColor Red }
if ($failed -or $missing) {
  Write-Host "$($failed.Count) failed, $($missing.Count) missing, of $($tests.Count)" -ForegroundColor Red
  exit 1
}
Write-Host "all $($tests.Count) passed" -ForegroundColor Green
