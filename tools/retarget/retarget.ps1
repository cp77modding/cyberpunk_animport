<#
Retargets NPC-rig animsets onto V's own skeleton, end to end, with no Blender and no GUI.

  source .anims (man_base / woman_base)
    -> WolvenKit export            glb, the source skeleton
    -> retarget_glb.py             same clips on player_man / player_woman_skeleton, IK targets on their
                                   bones, SIMD hint and the rig's 23 float tracks
    -> anims_json.py prep          container: the source animset, emptied, rig swapped
    -> wk_anims (ImportAnims)      cooked into the container by the WolvenKit nightly's SIMD encoder
    -> export + verify_retarget.py every clip re-read and compared to its source, per bone

  powershell -File tools\retarget\retarget.ps1 -Anims <an NPC set, .anims> -Body woman `
      -DepotPath ncn\anims\player\<name>_player.anims

-Rig man_big (or man_fat, woman_big, woman_fat, any base_entities rig) targets that NPC rig instead of V's; its
donor is built from the rig alone by rig_glb.py, from the rig json under work\npcrig.

The armature donor glb and the rig json come from extract.ps1. The cook needs a WolvenKit build with the
SIMD encoder (8.19.1 nightly or later; 8.18.1 writes the compressed buffer V plays wrong) -- README,
"Toolchain". Output lands at work\depot\<DepotPath>, ready to pack. docs/research/player-rig-retarget.md.
#>
[CmdletBinding()]
param(
  [Parameter(Mandatory)][string]$Anims,
  [ValidateSet('man', 'woman')][string]$Body,
  [string]$Rig = '',
  [Parameter(Mandatory)][string]$DepotPath,
  [string]$GamePath  = 'D:\SteamLibrary\steamapps\common\Cyberpunk 2077',
  [string]$WolvenKit = 'C:\Modding\wolwenKit_upacker\WolvenKit.CLI.exe',
  [string]$WolvenKitCook = '',
  [double]$MaxDeg = 0.1,
  [double]$MaxCm = 0.1,
  [switch]$SkipBuild,   # mb_player.ps1 builds wk_anims once for all its workers
  [string]$RunName = ''   # two packs hold sets of one name; a worker on each needs its own run folder
)

$ErrorActionPreference = 'Stop'
$root  = $PSScriptRoot
$work  = Join-Path $root 'work'
# Windows PowerShell leaves $PSScriptRoot empty in a param default.
if (-not $WolvenKitCook) { $WolvenKitCook = Join-Path $work 'wk_nightly' }
if (-not $RunName) { $RunName = [IO.Path]::GetFileNameWithoutExtension($DepotPath) }
$run   = Join-Path $work "run\$RunName"
$depot = Join-Path $work 'depot'
$out   = Join-Path $depot $DepotPath
if ([bool]$Body -eq [bool]$Rig) { throw "give -Body (V's skeleton) or -Rig (an NPC rig), one of them" }
if ($Rig) {
  $rig     = "base\characters\base_entities\$Rig\$Rig.rig"
  $rigJson = Join-Path $work "npcrig\cr2w\$rig.json"
  $donor   = Join-Path $work "npcrig\donor\$Rig.glb"
  if (-not (Test-Path $rigJson)) { throw "not found: $rigJson (unbundle the rig, then convert serialize it)" }
  New-Item -ItemType Directory -Force (Split-Path $donor) | Out-Null
  # parallel workers share the donor: built once, and only when the rig is newer
  if (-not (Test-Path $donor) -or (Get-Item $rigJson).LastWriteTime -gt (Get-Item $donor).LastWriteTime) {
    python (Join-Path $root 'rig_glb.py') $rigJson $donor
    if ($LASTEXITCODE -ne 0) { throw "donor armature failed (exit $LASTEXITCODE)" }
  }
} else {
  $tag     = if ($Body -eq 'man') { 'pma' } else { 'pwa' }
  $donor   = Join-Path $work "glb\tpp_${tag}_locomotion.anims.glb"
  $rig     = "base\characters\entities\player\player_${Body}_skeleton.rig"
  $rigJson = Join-Path $work "json\player_${Body}_skeleton.rig.json"
}

foreach ($p in @($WolvenKit, $donor, $rigJson, $Anims)) {
  if (-not (Test-Path $p)) { throw "not found: $p (run extract.ps1 for the donor and the rig)" }
}
$Anims = (Resolve-Path $Anims).Path
if (-not (Test-Path (Join-Path $WolvenKitCook 'WolvenKit.Modkit.dll'))) {
  throw "no SIMD-capable WolvenKit at $WolvenKitCook -- build it (README, Toolchain)"
}
if (Test-Path $run) { Remove-Item $run -Recurse -Force }
New-Item -ItemType Directory -Force $run, (Split-Path $out) | Out-Null

function Step($what, [scriptblock]$body) {
  Write-Host "-- $what" -ForegroundColor Cyan
  & $body
  if ($LASTEXITCODE -ne 0) { throw "$what failed (exit $LASTEXITCODE)" }
}

$name = [IO.Path]::GetFileName($Anims)
Copy-Item $Anims (Join-Path $run $name)
Step 'export source' { & $WolvenKit export (Join-Path $run $name) -o $run -gp $GamePath -v Minimal }
Step 'serialize source' { & $WolvenKit convert serialize (Join-Path $run $name) -v Minimal }
$srcGlb = Join-Path $run "$name.glb"

$stem = [IO.Path]::GetFileName($out)
$retargeted = Join-Path $run "$stem.glb"
$drop = if ($Rig) { '--drop-missing' } else { '' }   # V's skeletons hold every source bone; an NPC rig may not
Step 'retarget' { python (Join-Path $root 'retarget_glb.py') $srcGlb $donor $retargeted "--rig=$rigJson" $drop }

$container = Join-Path $run "container\$stem.json"
New-Item -ItemType Directory -Force (Split-Path $container) | Out-Null
Step 'prep container' { python (Join-Path $root 'anims_json.py') prep (Join-Path $run "$name.json") $rig $container }
Step 'deserialize container' { & $WolvenKit convert deserialize $container -o (Split-Path $out) -v Minimal }

$bridge = Join-Path $root 'wk_anims\bin\Release\net10.0\WkAnims.exe'
if (-not $SkipBuild) { Step 'build wk_anims' { dotnet build (Join-Path $root 'wk_anims\WkAnims.csproj') -c Release -v q --nologo | Out-Null } }
Step 'cook' { & $bridge $retargeted $out $GamePath $WolvenKitCook }

$check = Join-Path $run 'check'
New-Item -ItemType Directory -Force $check | Out-Null
Step 'export cooked' { & (Join-Path $WolvenKitCook 'WolvenKit.CLI.exe') export $out -o $check -gp $GamePath -v Minimal }
Step 'verify' { python (Join-Path $root 'verify_retarget.py') $srcGlb (Join-Path $check "$stem.glb") --max-deg $MaxDeg --max-cm $MaxCm }

# A compressed buffer re-exports the same pose and V still plays it wrong, so verify cannot see it.
Copy-Item $out (Join-Path $check $stem)
Step 'serialize cooked' { & (Join-Path $WolvenKitCook 'WolvenKit.CLI.exe') convert serialize (Join-Path $check $stem) -v Minimal }
$kinds = Select-String -Path (Join-Path $check "$stem.json") -Pattern '"animAnimationBuffer(\w+)"' -AllMatches |
  ForEach-Object { $_.Matches } | ForEach-Object { $_.Groups[1].Value }
$notSimd = @($kinds | Where-Object { $_ -ne 'Simd' })
if (-not $kinds -or $notSimd) {
  throw "cooked buffers are not all SIMD: $(($kinds | Group-Object | ForEach-Object { "$($_.Count) $($_.Name)" }) -join ', ')"
}
Write-Host "   $(@($kinds).Count) SIMD buffers"
# The set's fallback table is empty, so a clip indexing it crashes the blend (affection-actions.md).
Step 'check fallback' { python (Join-Path $root 'anims_json.py') check (Join-Path $check "$stem.json") }

Write-Host "OK  $out" -ForegroundColor Green
