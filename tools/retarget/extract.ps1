<#
The game's rigs and the entities that bind them, under tools/retarget/work/: what make_skeletons.py builds
skeletons/cyberpunk/ from. A port reads the shipped folder and needs none of this.

  work/cr2w/  extracted REDengine files (.rig .ent .anims)
  work/json/  the same, serialized -- this is where you read which rig a thing binds
  work/glb/   Blender-importable, via the WolvenKit Blender IO suite

Nothing here is committed: it is CDPR's data. Re-run to rebuild.

  powershell -File tools\retarget\extract.ps1
#>
[CmdletBinding()]
param(
  [string]$GamePath  = '',   # build.local.json's tools.game
  [string]$WolvenKit = '',   # build.local.json's tools.wolvenkit
  [switch]$Clean
)
$cfg = Join-Path $PSScriptRoot 'build_config.py'
if (-not $GamePath)  { $GamePath  = & python $cfg --get tools.game }
if (-not $WolvenKit) { $WolvenKit = & python $cfg --get tools.wolvenkit }

$ErrorActionPreference = 'Stop'
$root    = $PSScriptRoot
$work    = Join-Path $root 'work'
$cr2w    = Join-Path $work 'cr2w'
$json    = Join-Path $work 'json'
$glb     = Join-Path $work 'glb'
$content = Join-Path $GamePath 'archive\pc\content'

foreach ($p in @($WolvenKit, $content)) {
  if (-not (Test-Path $p)) { throw "not found: $p" }
}
if ($Clean -and (Test-Path $work)) { Remove-Item $work -Recurse -Force }
foreach ($d in @($cr2w, $json, $glb)) { New-Item -ItemType Directory -Force $d | Out-Null }

function Unbundle($archive, $regex, $what) {
  Write-Host "-- $what" -ForegroundColor Cyan
  & $WolvenKit unbundle $archive -o $cr2w -r $regex -v Quiet | Out-Null
  if ($LASTEXITCODE -ne 0) { throw "unbundle failed ($what)" }
}

# --- source skeleton: what every NPC body and BOTH stand-in doubles are built on ---------------
Unbundle "$content\basegame_1_engine.archive" `
  "characters\\base_entities\\(man_base|woman_base)\\(man_base|woman_base)\.rig$" `
  'man_base / woman_base rigs (every NPC)'

# --- target skeleton: V's own playable body ---------------------------------------------------
Unbundle "$content\basegame_1_engine.archive" `
  "characters\\entities\\player\\player_(man|woman)_skeleton\.rig$" `
  'player_man / player_woman skeleton rigs (V)'

# --- the entities, so the rig binding is checkable rather than assumed ------------------------
Unbundle "$content\basegame_1_engine.archive" `
  "characters\\entities\\player\\player_(ma|wa)_fpp\.ent$" `
  'player FPP entities (V''s real body)'
Unbundle "$content\basegame_4_appearance.archive" `
  "characters\\entities\\player\\player_(ma|wa)_tpp_cutscene\.ent$" `
  'player TPP cutscene entities (Character.TPP_Player_Cutscene_*, i.e. AnimDouble)'

# --- armature donors. WolvenKit cannot export a bare .rig to glb, but an .anims export carries
#     the skeleton it binds -- so a vanilla player clip is how the player armature reaches Blender.
Unbundle "$content\basegame_4_animation.archive" `
  "animations\\player\\(male\\body\\tpp_pma_locomotion|female\\body\\tpp_pwa_locomotion)\.anims$" `
  'vanilla TPP player locomotion (donor armature = player_*_skeleton)'

# --- serialize everything: the json is the only place the rig reference is readable ------------
Write-Host '-- serialize to json' -ForegroundColor Cyan
$all = Get-ChildItem $cr2w -Recurse -File -Include *.rig, *.ent, *.anims | ForEach-Object { $_.FullName }
& $WolvenKit convert serialize @all -o $json -v Quiet | Out-Null

# --- glb for Blender. Only .anims exports; -gp lets it resolve each set's rig from the archives.
Write-Host '-- export glb' -ForegroundColor Cyan
$anims = Get-ChildItem $cr2w -Recurse -File -Filter *.anims | ForEach-Object { $_.FullName }
& $WolvenKit export @anims -o $glb -gp $GamePath -v Quiet | Out-Null

# --- report: which rig does each thing bind? That is the whole question. -----------------------
Write-Host "`n=== rig binding (entity / animset -> rig) ===" -ForegroundColor Green
Get-ChildItem $json -File | Where-Object { $_.Name -notlike '*.rig.json' } | Sort-Object Name | ForEach-Object {
  $rigs = Select-String -Path $_.FullName -Pattern '"\$value": "(base\\\\characters\\\\[^"]*\.rig)"' -AllMatches |
          ForEach-Object { $_.Matches } | ForEach-Object { $_.Groups[1].Value.Replace('\\', '\') } |
          Where-Object { $_ -notmatch 'deformation|shadow' } | Sort-Object -Unique
  if ($rigs) { '{0,-42} {1}' -f $_.BaseName, ($rigs -join ', ') }
}

# A rig's own `retargets` is the engine's rig-to-rig seam -- an empty one is why V is stuck.
Write-Host "`n=== rig.retargets (engine-native retarget sources) ===" -ForegroundColor Green
Get-ChildItem $json -File -Filter *.rig.json | Sort-Object Name | ForEach-Object {
  $rc = (Get-Content $_.FullName -Raw | ConvertFrom-Json).Data.RootChunk
  $src = if ($rc.retargets.Count) { ($rc.retargets | ForEach-Object { $_.sourceRig.DepotPath.'$value' }) -join ', ' } else { '(none)' }
  '{0,-32} {1,3} bones   <- {2}' -f $_.BaseName, $rc.boneNames.Count, $src
}

# The last row is the control: CDPR SHIPS that retarget for the whole female cast. A hop smaller
# than it is a hop the engine is already known to survive.
Write-Host "`n=== bone diff (last row = CDPR's own shipped retarget) ===" -ForegroundColor Green
@(@('man_base', 'player_man_skeleton'),
  @('woman_base', 'player_woman_skeleton'),
  @('man_base', 'player_woman_skeleton'),
  @('man_base', 'woman_base')) | ForEach-Object {
  python (Join-Path $root 'compare_rigs.py') "$json\$($_[0]).rig.json" "$json\$($_[1]).rig.json" --summary
}

Write-Host "`nglb for Blender: $glb" -ForegroundColor Green
